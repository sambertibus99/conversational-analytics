"""
Supervisor Agent für die Planung von Agent-Ausführungen.

Der Supervisor analysiert User-Anfragen und erstellt einen Plan,
welche Agents in welcher Reihenfolge ausgeführt werden sollen.

Er führt selbst KEINE Aktionen aus – er plant nur!

DESIGN-ENTSCHEIDUNGEN:
- DEC-013: Multi-Turn Support (berücksichtigt vorhandene Datasets)
- DEC-016: Strukturiertes Logging
- DEC-023: Query-Typ-basierte Datenstrategie (detail vs overview)
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import json
import asyncio
import logging
import re
from typing import Any, Tuple, Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from agents.state import AgentState
from agents.utils import extract_user_query
from prompts.supervisor_prompt import get_supervisor_prompt
from config.settings import DEFAULT_MODEL, api_key_rotator, create_anthropic_client, create_cached_system_message


# =============================================================================
# LOGGING KONFIGURATION (DEC-016)
# =============================================================================

logger = logging.getLogger(__name__)

# Retry-Konfiguration
MAX_RETRIES = 3
RETRY_DELAY_BASE = 2

# Gültige Agents
VALID_AGENTS = {"data_agent", "stats_agent", "viz_agent"}


# =============================================================================
# HILFSFUNKTIONEN
# =============================================================================

SUPERVISOR_MODEL = "claude-opus-4-20250514"  # DEC-029: Opus für besseres Reasoning


def create_supervisor_llm():
    """Erstellt das LLM für den Supervisor mit aktuellem API Key (DEC-018, DEC-029: Opus)."""
    return create_anthropic_client(model=SUPERVISOR_MODEL)


def parse_supervisor_response(response: str) -> dict[str, Any]:
    """
    Parst die Supervisor-Antwort zu einem Plan-Dict.

    Erwartet JSON: {"plan": [...], "reasoning": "...", "data_mode": "..."}
    Ist robust gegen Markdown-Codeblöcke.
    """
    if not response:
        return {"plan": [], "reasoning": "Keine Antwort vom Supervisor", "data_mode": "overview"}

    cleaned = response.strip()

    # Markdown Codeblöcke entfernen
    if "```" in cleaned:
        match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', cleaned, re.DOTALL)
        if match:
            cleaned = match.group(1)
        else:
            cleaned = re.sub(r'```(?:json)?', '', cleaned).strip()

    try:
        result = json.loads(cleaned)

        if not isinstance(result, dict):
            return {"plan": [], "reasoning": f"Ungültiges Format: {type(result)}", "data_mode": "overview"}

        if "plan" not in result:
            return {"plan": [], "reasoning": "Kein 'plan' Feld in Antwort", "data_mode": "overview"}

        if not isinstance(result["plan"], list):
            return {"plan": [], "reasoning": f"'plan' ist keine Liste: {type(result['plan'])}", "data_mode": "overview"}

        # Validiere Agent-Namen
        for agent in result["plan"]:
            if agent not in VALID_AGENTS:
                logger.warning(f"Unbekannter Agent '{agent}' im Plan")

        # DEC-023: Data Mode validieren
        data_mode = result.get("data_mode", "overview")
        if data_mode not in ("detail", "overview"):
            logger.warning(f"Ungültiger data_mode '{data_mode}', verwende 'overview'")
            data_mode = "overview"

        return {
            "plan": result["plan"],
            "reasoning": result.get("reasoning", "Keine Begründung"),
            "data_mode": data_mode,
            "data_instructions": result.get("data_instructions"),
            "needs_user_input": result.get("needs_user_input", False),
            "user_input_reason": result.get("user_input_reason"),
        }

    except json.JSONDecodeError as e:
        logger.warning(f"JSON Parse Error: {e}")
        logger.debug(f"Response war: {cleaned[:200]}")
        return {"plan": [], "reasoning": f"JSON Parse Error: {str(e)}", "data_mode": "overview"}


def validate_plan(plan: list[str], has_datasets: bool) -> Tuple[bool, str, list[str]]:
    """
    Validiert den Plan auf logische Konsistenz.

    DEC-028: data_agent wird IMMER eingefügt wenn stats/viz geplant ist,
    auch wenn Datasets vorhanden sind. Der Data Agent entscheidet selbst
    über active_dataset_keys (check_dataset).

    Returns:
        Tuple von (is_valid, message, repaired_plan)
    """
    if not plan:
        return True, "Leerer Plan ist valide", plan

    repaired = plan.copy()

    # Prüfe auf ungültige Agents
    for agent in plan:
        if agent not in VALID_AGENTS:
            return False, f"Ungültiger Agent: {agent}", []

    # DEC-028: data_agent IMMER wenn stats/viz geplant
    needs_data = "stats_agent" in plan or "viz_agent" in plan
    has_data_agent = "data_agent" in plan

    if needs_data and not has_data_agent:
        repaired = ["data_agent"] + repaired
        logger.debug("Plan repariert: data_agent hinzugefügt (DEC-028: wird immer gebraucht)")
        return True, "Plan repariert", repaired
    
    # Prüfe Reihenfolge
    if has_data_agent:
        data_idx = repaired.index("data_agent")
        
        if "stats_agent" in repaired and repaired.index("stats_agent") < data_idx:
            return False, "stats_agent muss nach data_agent kommen", []
        
        if "viz_agent" in repaired and repaired.index("viz_agent") < data_idx:
            return False, "viz_agent muss nach data_agent kommen", []
    
    return True, "Plan ist valide", repaired


def build_turn_context(turn_history: list, datasets: dict) -> str:
    """
    Baut Kontext aus turn_history für den Supervisor (DEC-029).

    Ersetzt build_dataset_context(). Der Supervisor bekommt nun den
    strukturierten Konversationsverlauf statt nur data_summary.

    Fallback: Alte Sessions ohne turn_history bekommen minimalen Hinweis.
    """
    if not turn_history and not datasets:
        return ""

    parts = []

    if turn_history:
        parts.append("\n## BISHERIGER VERLAUF\n")
        for i, turn in enumerate(turn_history[-15:], 1):  # Max 15 Turns
            query = turn.get("user_query", "?")
            plan = turn.get("plan", [])
            turn_datasets = turn.get("datasets", [])
            result_type = turn.get("result_type", "?")
            result_summary = turn.get("result_summary", "")

            parts.append(f"Turn {i}: \"{query}\"")
            if plan:
                parts.append(f"  Plan: {plan}")
            for ds in turn_datasets:
                keys = ds.get("keys", [])
                tr = ds.get("timerange", "")
                if keys:
                    parts.append(f"  Daten: {', '.join(keys[:8])} ({tr})")
            if result_summary:
                parts.append(f"  Ergebnis ({result_type}): {result_summary}")
            parts.append("")
    elif datasets:
        # Fallback für alte Sessions ohne turn_history
        parts.append("\n## VORHANDENE DATEN\n")
        parts.append("Daten vorhanden (Details beim Data Agent).")

    return "\n".join(parts)


# =============================================================================
# HAUPTLOGIK
# =============================================================================

async def invoke_llm_with_retry(
    llm,
    messages: list,
    max_retries: int = MAX_RETRIES
) -> str:
    """
    Ruft LLM auf mit Retry bei transienten Fehlern.
    """
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            response = await llm.ainvoke(messages)
            return response.content
        
        except (ConnectionError, TimeoutError) as e:
            last_exception = e
            delay = RETRY_DELAY_BASE * (2 ** attempt)
            logger.warning(f"LLM Fehler (Versuch {attempt + 1}/{max_retries}): {e}")
            
            if attempt < max_retries - 1:
                await asyncio.sleep(delay)
        
        except Exception as e:
            error_str = str(e).lower()
            if "429" in error_str or "rate limit" in error_str:
                last_exception = e
                delay = RETRY_DELAY_BASE * (2 ** attempt)
                logger.warning(f"Rate Limit (Versuch {attempt + 1}/{max_retries})")
                
                if attempt < max_retries - 1:
                    await asyncio.sleep(delay)
            else:
                raise
    
    raise last_exception or Exception("LLM invocation failed after retries")


async def run_supervisor(state: AgentState) -> dict[str, Any]:
    """
    Führt den Supervisor aus und erstellt einen Plan.
    
    Orchestriert:
    1. User-Query extrahieren
    2. Dataset-Kontext aufbauen
    3. LLM aufrufen
    4. Response parsen und validieren
    """
    try:
        logger.debug("Starte Supervisor")
        
        # 1. User-Query extrahieren
        user_query = extract_user_query(state["messages"])
        logger.debug(f"User Query: {user_query}")
        
        if not user_query:
            return {
                "plan": [],
                "reasoning": "Keine User-Anfrage gefunden",
                "needs_user_input": False,
                "user_input_reason": None,
            }
        
        # 2. Turn-Kontext (DEC-029: turn_history statt data_summary)
        turn_history = state.get("turn_history", [])
        datasets = state.get("datasets", {})
        context_info = build_turn_context(turn_history, datasets)

        if turn_history:
            logger.debug(f"Turn History: {len(turn_history)} Turns")
        if datasets:
            logger.debug(f"Datasets vorhanden: {list(datasets.keys())}")
        
        # 3. LLM aufrufen (DEC-021: Prompt Caching via list[dict] content)
        llm = create_supervisor_llm()
        enhanced_prompt = get_supervisor_prompt() + context_info

        messages = [
            create_cached_system_message(enhanced_prompt),
            HumanMessage(content=user_query),
        ]

        logger.debug("Rufe LLM auf mit Prompt Caching...")
        response_content = await invoke_llm_with_retry(llm, messages)
        logger.debug(f"LLM Response: {response_content[:200]}...")
        
        # 4. Response parsen
        result = parse_supervisor_response(response_content)
        logger.debug(f"Parsed Plan: {result['plan']}")
        
        # 5. Plan validieren und ggf. reparieren
        is_valid, validation_msg, repaired_plan = validate_plan(
            result["plan"], 
            has_datasets=bool(datasets)
        )
        
        if not is_valid:
            logger.warning(f"Plan ungültig: {validation_msg}")
            return {
                "plan": [],
                "reasoning": f"Plan ungültig: {validation_msg}",
                "current_step": 0,
                "needs_user_input": False,
                "user_input_reason": None,
            }
        
        final_plan = repaired_plan if repaired_plan != result["plan"] else result["plan"]
        data_mode = result.get("data_mode", "overview")

        data_instructions = result.get("data_instructions")
        needs_input = result.get("needs_user_input", False)
        input_reason = result.get("user_input_reason")

        logger.info(f"Plan erstellt: {final_plan}, data_mode: {data_mode}")
        if data_instructions:
            logger.info(f"Data Instructions: {data_instructions[:80]}...")
        if needs_input:
            logger.info(f"Rückfrage nötig: {input_reason}")

        # Bei Rückfrage → leerer Plan, respond zeigt Frage
        if needs_input and input_reason:
            return {
                "plan": [],
                "reasoning": result["reasoning"],
                "current_step": 0,
                "needs_user_input": True,
                "user_input_reason": input_reason,
                "active_dataset_keys": None,  # DEC-028: Reset
                "messages": [AIMessage(content=input_reason)],
            }

        return {
            "plan": final_plan,
            "reasoning": result["reasoning"],
            "current_step": 0,  # Step zurücksetzen für neuen Plan
            "data_retrieval_mode": data_mode,  # DEC-023
            "data_instructions": data_instructions,
            "active_dataset_keys": None,  # DEC-028: Reset — Data Agent setzt neu
            "needs_user_input": False,  # Explizit zurücksetzen (Checkpointer persistiert!)
            "user_input_reason": None,
            # Per-Turn Outputs resetten (Checkpointer persistiert alte Werte!)
            "chart_url": None,
            "chart_type": None,
            "statistics": None,
            "statistics_summary": None,
            "error": None,
            "error_count": 0,
            "should_abstain": False,
            "abstain_reason": None,
            "messages": [AIMessage(content=f"Plan erstellt: {final_plan}")],
        }
    
    except Exception as e:
        error_msg = f"Fehler bei der Planung: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {
            "plan": [],
            "reasoning": error_msg,
            "error": str(e),
            "needs_user_input": False,
            "user_input_reason": None,
        }


async def supervisor_node(state: AgentState) -> dict[str, Any]:
    """LangGraph Node für den Supervisor."""
    return await run_supervisor(state)


# =============================================================================
# TESTS
# =============================================================================

async def test_supervisor():
    """Test des Supervisors mit verschiedenen Queries."""
    
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    
    test_cases = [
        ("Zeig mir die Temperatur von Roboter 1", ["data_agent", "viz_agent"]),
        ("Wie ist die aktuelle Position von Achse 1?", ["data_agent"]),
        ("Was ist die Durchschnittstemperatur?", ["data_agent", "stats_agent"]),
        ("Wie wird das Wetter morgen?", []),
    ]
    
    print("\n" + "="*70)
    print("🧪 Supervisor Test")
    print("="*70)
    
    passed = 0
    
    for query, expected in test_cases:
        print(f"\n📝 Query: {query}")
        print(f"   Erwartet: {expected}")
        
        state = AgentState(messages=[HumanMessage(content=query)])
        result = await run_supervisor(state)
        
        actual = result.get("plan", [])
        print(f"   Erhalten: {actual}")
        
        if actual == expected:
            print("   ✅ PASS")
            passed += 1
        else:
            print("   ❌ FAIL")
    
    print(f"\n{'='*70}")
    print(f"Ergebnis: {passed}/{len(test_cases)} Tests bestanden")


if __name__ == "__main__":
    asyncio.run(test_supervisor())
