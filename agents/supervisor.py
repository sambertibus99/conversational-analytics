"""
Supervisor Agent für die Planung von Agent-Ausführungen.

Der Supervisor analysiert User-Anfragen und erstellt einen Plan,
welche Agents in welcher Reihenfolge ausgeführt werden sollen.

Er führt selbst KEINE Aktionen aus – er plant nur!
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import json
import asyncio
import re
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from agents.state import AgentState
from prompts.supervisor_prompt import SUPERVISOR_SYSTEM_PROMPT
from config.settings import ANTHROPIC_API_KEY, DEFAULT_MODEL


# Debug-Modus
DEBUG = False


def debug_print(msg: str):
    """Gibt Debug-Nachrichten aus wenn DEBUG=True."""
    if DEBUG:
        print(f"🔍 SUPERVISOR DEBUG: {msg}")


def create_supervisor_llm():
    """Erstellt das LLM für den Supervisor."""
    return ChatAnthropic(
        model=DEFAULT_MODEL,
        api_key=ANTHROPIC_API_KEY,
        temperature=0,  # Deterministisch für konsistente Planung
    )


def extract_user_query(state: AgentState) -> str:
    """Extrahiert die User-Query aus dem State."""
    for msg in state["messages"]:
        if isinstance(msg, HumanMessage):
            return msg.content
    return ""


def parse_supervisor_response(response: str) -> dict[str, Any]:
    """
    Parst die Supervisor-Antwort zu einem Plan-Dict.
    
    Erwartet JSON: {"plan": [...], "reasoning": "..."}
    Ist robust gegen Markdown-Codeblöcke und Whitespace.
    """
    if not response:
        return {"plan": [], "reasoning": "Keine Antwort vom Supervisor"}
    
    # Bereinigen: Markdown Codeblöcke entfernen
    cleaned = response.strip()
    
    # ```json ... ``` entfernen
    if "```" in cleaned:
        # Finde JSON zwischen Codeblöcken
        match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', cleaned, re.DOTALL)
        if match:
            cleaned = match.group(1)
        else:
            # Alternativ: alles zwischen ``` entfernen
            cleaned = re.sub(r'```(?:json)?', '', cleaned).strip()
    
    # Versuche JSON zu parsen
    try:
        result = json.loads(cleaned)
        
        # Validierung
        if not isinstance(result, dict):
            return {"plan": [], "reasoning": f"Ungültiges Format: {type(result)}"}
        
        if "plan" not in result:
            return {"plan": [], "reasoning": "Kein 'plan' Feld in Antwort"}
        
        if not isinstance(result["plan"], list):
            return {"plan": [], "reasoning": f"'plan' ist keine Liste: {type(result['plan'])}"}
        
        # Validiere Agent-Namen
        valid_agents = {"data_agent", "stats_agent", "viz_agent"}
        for agent in result["plan"]:
            if agent not in valid_agents:
                debug_print(f"Warnung: Unbekannter Agent '{agent}' im Plan")
        
        return {
            "plan": result["plan"],
            "reasoning": result.get("reasoning", "Keine Begründung"),
        }
    
    except json.JSONDecodeError as e:
        debug_print(f"JSON Parse Error: {e}")
        debug_print(f"Response war: {cleaned[:200]}")
        return {"plan": [], "reasoning": f"JSON Parse Error: {str(e)}"}


def validate_plan(plan: list[str]) -> tuple[bool, str]:
    """
    Validiert den Plan auf logische Konsistenz.
    
    Regeln:
    - data_agent muss vor stats_agent kommen (wenn beide vorhanden)
    - data_agent muss vor viz_agent kommen (wenn beide vorhanden)
    """
    if not plan:
        return True, "Leerer Plan ist valide"
    
    valid_agents = {"data_agent", "stats_agent", "viz_agent"}
    
    # Prüfe auf ungültige Agents
    for agent in plan:
        if agent not in valid_agents:
            return False, f"Ungültiger Agent: {agent}"
    
    # Prüfe Reihenfolge
    if "stats_agent" in plan or "viz_agent" in plan:
        if "data_agent" not in plan:
            return False, "stats_agent/viz_agent brauchen data_agent"
        
        data_idx = plan.index("data_agent")
        
        if "stats_agent" in plan and plan.index("stats_agent") < data_idx:
            return False, "stats_agent muss nach data_agent kommen"
        
        if "viz_agent" in plan and plan.index("viz_agent") < data_idx:
            return False, "viz_agent muss nach data_agent kommen"
    
    return True, "Plan ist valide"


async def run_supervisor(state: AgentState) -> dict[str, Any]:
    """
    Führt den Supervisor aus und erstellt einen Plan.
    
    Returns:
        dict mit 'plan' und 'reasoning'
    """
    try:
        debug_print("Starte Supervisor")
        
        # User-Query extrahieren
        user_query = extract_user_query(state)
        debug_print(f"User Query: {user_query}")
        
        if not user_query:
            return {
                "plan": [],
                "reasoning": "Keine User-Anfrage gefunden",
            }
        
        # LLM aufrufen
        llm = create_supervisor_llm()
        
        messages = [
            SystemMessage(content=SUPERVISOR_SYSTEM_PROMPT),
            HumanMessage(content=user_query),
        ]
        
        debug_print("Rufe LLM auf...")
        response = await llm.ainvoke(messages)
        debug_print(f"LLM Response: {response.content[:200]}...")
        
        # Response parsen
        result = parse_supervisor_response(response.content)
        debug_print(f"Parsed Plan: {result['plan']}")
        
        # Plan validieren
        is_valid, validation_msg = validate_plan(result["plan"])
        if not is_valid:
            debug_print(f"Plan ungültig: {validation_msg}")
            # Versuche Plan zu reparieren
            if "data_agent" not in result["plan"] and (
                "stats_agent" in result["plan"] or "viz_agent" in result["plan"]
            ):
                result["plan"] = ["data_agent"] + result["plan"]
                debug_print(f"Plan repariert: {result['plan']}")
        
        return {
            "plan": result["plan"],
            "reasoning": result["reasoning"],
            "messages": [AIMessage(content=f"Plan erstellt: {result['plan']}")],
        }
    
    except Exception as e:
        debug_print(f"Fehler: {str(e)}")
        return {
            "plan": [],
            "reasoning": f"Fehler bei der Planung: {str(e)}",
            "error": str(e),
        }


async def supervisor_node(state: AgentState) -> dict[str, Any]:
    """LangGraph Node für den Supervisor."""
    return await run_supervisor(state)


# =============================================================================
# STANDALONE TESTS
# =============================================================================

async def test_supervisor():
    """Test des Supervisors mit verschiedenen Queries."""
    
    test_cases = [
        # (Query, Erwarteter Plan)
        ("Zeig mir die Temperatur von Roboter 1", ["data_agent", "viz_agent"]),
        ("Wie ist die aktuelle Position von Achse 1?", ["data_agent"]),
        ("Was ist die Durchschnittstemperatur?", ["data_agent", "stats_agent"]),
        ("Korrelation zwischen Drehmoment und Geschwindigkeit als Chart", ["data_agent", "stats_agent", "viz_agent"]),
        ("Liste alle Geräte auf", ["data_agent"]),
        ("Wie wird das Wetter morgen?", []),
        ("Gab es Anomalien beim Drehmoment?", ["data_agent", "stats_agent"]),
        ("Zeig den Verlauf der Bahngeschwindigkeit als Liniendiagramm", ["data_agent", "viz_agent"]),
    ]
    
    print("\n" + "="*70)
    print("🧪 Supervisor Test")
    print("="*70)
    
    passed = 0
    failed = 0
    
    for query, expected in test_cases:
        print(f"\n📝 Query: {query}")
        print(f"   Erwartet: {expected}")
        
        state = AgentState(messages=[HumanMessage(content=query)])
        result = await run_supervisor(state)
        
        actual = result.get("plan", [])
        reasoning = result.get("reasoning", "")
        
        print(f"   Erhalten: {actual}")
        print(f"   Reasoning: {reasoning}")
        
        # Vergleich (Reihenfolge muss stimmen)
        if actual == expected:
            print("   ✅ PASS")
            passed += 1
        else:
            print("   ❌ FAIL")
            failed += 1
    
    print(f"\n{'='*70}")
    print(f"Ergebnis: {passed}/{len(test_cases)} Tests bestanden")
    print("="*70)


async def interactive_test():
    """Interaktiver Test mit eigenen Queries."""
    print("\n" + "="*60)
    print("🤖 Supervisor Interactive Test")
    print("="*60)
    print("Gib eine Frage ein (oder 'quit' zum Beenden):\n")
    
    while True:
        query = input("📝 Query: ").strip()
        
        if query.lower() in ["quit", "exit", "q"]:
            break
        
        if not query:
            continue
        
        state = AgentState(messages=[HumanMessage(content=query)])
        result = await run_supervisor(state)
        
        print(f"\n📋 Plan: {result.get('plan', [])}")
        print(f"💭 Reasoning: {result.get('reasoning', 'N/A')}")
        print()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--interactive":
        asyncio.run(interactive_test())
    else:
        asyncio.run(test_supervisor())
