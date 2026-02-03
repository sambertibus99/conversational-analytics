"""
Supervisor Agent für die Planung von Agent-Ausführungen.

Der Supervisor analysiert User-Anfragen und erstellt einen Plan,
welche Agents in welcher Reihenfolge ausgeführt werden sollen.

Er führt selbst KEINE Aktionen aus – er plant nur!

DESIGN-ENTSCHEIDUNGEN:
- DEC-013: Multi-Turn Support (berücksichtigt vorhandene Datasets)
- DEC-016: Strukturiertes Logging
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
from prompts.supervisor_prompt import SUPERVISOR_SYSTEM_PROMPT
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

def create_supervisor_llm():
    """Erstellt das LLM für den Supervisor mit aktuellem API Key (DEC-018)."""
    return create_anthropic_client()


def parse_supervisor_response(response: str) -> dict[str, Any]:
    """
    Parst die Supervisor-Antwort zu einem Plan-Dict.
    
    Erwartet JSON: {"plan": [...], "reasoning": "..."}
    Ist robust gegen Markdown-Codeblöcke.
    """
    if not response:
        return {"plan": [], "reasoning": "Keine Antwort vom Supervisor"}
    
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
            return {"plan": [], "reasoning": f"Ungültiges Format: {type(result)}"}
        
        if "plan" not in result:
            return {"plan": [], "reasoning": "Kein 'plan' Feld in Antwort"}
        
        if not isinstance(result["plan"], list):
            return {"plan": [], "reasoning": f"'plan' ist keine Liste: {type(result['plan'])}"}
        
        # Validiere Agent-Namen
        for agent in result["plan"]:
            if agent not in VALID_AGENTS:
                logger.warning(f"Unbekannter Agent '{agent}' im Plan")
        
        return {
            "plan": result["plan"],
            "reasoning": result.get("reasoning", "Keine Begründung"),
        }
    
    except json.JSONDecodeError as e:
        logger.warning(f"JSON Parse Error: {e}")
        logger.debug(f"Response war: {cleaned[:200]}")
        return {"plan": [], "reasoning": f"JSON Parse Error: {str(e)}"}


def validate_plan(plan: list[str], has_datasets: bool) -> Tuple[bool, str, list[str]]:
    """
    Validiert den Plan auf logische Konsistenz.
    
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
    
    # Prüfe ob data_agent fehlt wenn stats/viz vorhanden
    needs_data = "stats_agent" in plan or "viz_agent" in plan
    has_data_agent = "data_agent" in plan
    
    if needs_data and not has_data_agent and not has_datasets:
        # Reparieren: data_agent hinzufügen
        repaired = ["data_agent"] + repaired
        logger.debug(f"Plan repariert: data_agent hinzugefügt")
        return True, "Plan repariert", repaired
    
    # Prüfe Reihenfolge
    if has_data_agent:
        data_idx = repaired.index("data_agent")
        
        if "stats_agent" in repaired and repaired.index("stats_agent") < data_idx:
            return False, "stats_agent muss nach data_agent kommen", []
        
        if "viz_agent" in repaired and repaired.index("viz_agent") < data_idx:
            return False, "viz_agent muss nach data_agent kommen", []
    
    return True, "Plan ist valide", repaired


def build_dataset_context(datasets: dict, data_summary: str) -> str:
    """Baut Kontext-Info über vorhandene Datasets."""
    if not datasets:
        return ""
    
    dataset_keys = list(datasets.keys())
    all_data_keys = []
    for ds in datasets.values():
        if isinstance(ds, dict) and "data" in ds:
            all_data_keys.extend(ds["data"].keys())
    
    return f"""

## BEREITS GELADENE DATEN

Datasets: {', '.join(dataset_keys)}
Verfügbare Keys: {', '.join(all_data_keys[:10])}{'...' if len(all_data_keys) > 10 else ''}
Summary: {data_summary}

WICHTIG: 
- Wenn der User nach NEUEN Daten fragt (andere Keys/Zeitraum), MUSS data_agent im Plan sein!
- Wenn der User nur Analyse/Visualisierung der VORHANDENEN Daten will, kann data_agent weggelassen werden.
- Bei "Zusammenhang mit X" oder "Korrelation mit X" - prüfe ob X schon geladen ist!
"""


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
            }
        
        # 2. Dataset-Kontext
        datasets = state.get("datasets", {})
        data_summary = state.get("data_summary", "")
        context_info = build_dataset_context(datasets, data_summary)
        
        if datasets:
            logger.debug(f"Datasets vorhanden: {list(datasets.keys())}")
        
        # 3. LLM aufrufen (DEC-021: Prompt Caching via list[dict] content)
        llm = create_supervisor_llm()
        enhanced_prompt = SUPERVISOR_SYSTEM_PROMPT + context_info

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
            }
        
        final_plan = repaired_plan if repaired_plan != result["plan"] else result["plan"]
        
        logger.info(f"Plan erstellt: {final_plan}")
        
        return {
            "plan": final_plan,
            "reasoning": result["reasoning"],
            "current_step": 0,  # Step zurücksetzen für neuen Plan
            "messages": [AIMessage(content=f"Plan erstellt: {final_plan}")],
        }
    
    except Exception as e:
        error_msg = f"Fehler bei der Planung: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {
            "plan": [],
            "reasoning": error_msg,
            "error": str(e),
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
