"""
LangGraph Orchestrierung für das Conversational Analytics System.

Der Graph verbindet alle Agents und führt sie basierend auf dem
Supervisor-Plan in der richtigen Reihenfolge aus.

Ablauf:
1. Supervisor erstellt Plan
2. Agents werden gemäß Plan ausgeführt
3. Respond-Node generiert finale Antwort
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import asyncio
from typing import Literal, Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langgraph.graph import StateGraph, START, END

from agents.state import AgentState
from agents.supervisor import supervisor_node
from agents.data_agent import data_agent_node
from agents.stats_agent import stats_agent_node
from agents.viz_agent import viz_agent_node
from config.settings import ANTHROPIC_API_KEY, DEFAULT_MODEL


# Debug-Modus
DEBUG = False


def debug_print(msg: str):
    """Gibt Debug-Nachrichten aus wenn DEBUG=True."""
    if DEBUG:
        print(f"🔍 GRAPH DEBUG: {msg}")


# =============================================================================
# RESPOND NODE
# =============================================================================

RESPOND_SYSTEM_PROMPT = """
Du bist ein freundlicher Assistent für IIoT-Datenanalyse.
Fasse die Ergebnisse für den Nutzer zusammen.

## KONTEXT
Du hast Zugriff auf:
- Die ursprüngliche Frage des Nutzers
- Geladene Daten (falls vorhanden)
- Berechnete Statistiken (falls vorhanden)
- Generiertes Chart (falls vorhanden)

## REGELN
1. Antworte auf Deutsch
2. Sei freundlich und hilfreich
3. Wenn ein Chart erstellt wurde, erwähne es und zeige die URL
4. Wenn Statistiken berechnet wurden, präsentiere sie verständlich
5. Wenn keine Daten gefunden wurden, erkläre warum
6. Halte die Antwort kurz und prägnant

## FORMAT
- Bei Charts: "Hier ist [Beschreibung]: [URL]"
- Bei Statistiken: Interpretiere die Zahlen, nicht nur auflisten
- Bei Fehlern: Erkläre was schief ging und was der User tun kann
"""


async def respond_node(state: AgentState) -> dict[str, Any]:
    """
    Generiert die finale Antwort für den User.
    
    WICHTIG: Bei needs_user_input=True wird die Frage des vorherigen Agents
    direkt weitergegeben (keine neue Response generieren!).
    """
    debug_print("Starte Respond Node")
    
    # SPEZIALFALL: User-Input wird benötigt
    # Die letzte AI-Message enthält bereits die Frage an den User
    if state.get("needs_user_input", False):
        debug_print(f"needs_user_input=True: {state.get('user_input_reason')}")
        
        # Finde und gib die letzte AI-Message direkt zurück
        for msg in reversed(state.get("messages", [])):
            if isinstance(msg, AIMessage) and isinstance(msg.content, str):
                debug_print("Gebe vorherige AI-Message direkt weiter")
                return {
                    "messages": [msg],  # Die Frage direkt weitergeben
                }
        
        # Fallback falls keine AI-Message gefunden
        return {
            "messages": [AIMessage(content="Es ist ein Problem aufgetreten. Bitte versuche es nochmal.")],
        }
    
    # Sammle Kontext für normale Response
    context_parts = []
    
    # Original-Query
    user_query = ""
    for msg in state["messages"]:
        if isinstance(msg, HumanMessage):
            user_query = msg.content
            break
    context_parts.append(f"User-Anfrage: {user_query}")
    
    # Plan
    if state.get("plan"):
        context_parts.append(f"Ausgeführte Agents: {state['plan']}")
    
    # Daten-Summary
    if state.get("data_summary"):
        context_parts.append(f"Geladene Daten: {state['data_summary']}")
    
    # Statistiken
    if state.get("statistics"):
        context_parts.append(f"Statistiken: {state['statistics']}")
    if state.get("statistics_summary"):
        context_parts.append(f"Statistik-Zusammenfassung: {state['statistics_summary']}")
    
    # Chart
    if state.get("chart_url"):
        context_parts.append(f"Chart erstellt: {state['chart_url']}")
        context_parts.append(f"Chart-Typ: {state.get('chart_type', 'unbekannt')}")
    
    # Fehler
    if state.get("error"):
        context_parts.append(f"Fehler aufgetreten: {state['error']}")
    
    # Leerer Plan (Abstention)
    if state.get("plan") == []:
        context_parts.append("HINWEIS: Die Anfrage konnte nicht bearbeitet werden (kein Plan erstellt)")
        if state.get("reasoning"):
            context_parts.append(f"Grund: {state['reasoning']}")
    
    context = "\n".join(context_parts)
    debug_print(f"Context: {context[:500]}...")
    
    # LLM für Response
    llm = ChatAnthropic(
        model=DEFAULT_MODEL,
        api_key=ANTHROPIC_API_KEY,
        temperature=0.3,  # Etwas Variation für natürlichere Antworten
    )
    
    messages = [
        SystemMessage(content=RESPOND_SYSTEM_PROMPT),
        HumanMessage(content=f"Erstelle eine Antwort basierend auf:\n\n{context}"),
    ]
    
    response = await llm.ainvoke(messages)
    debug_print(f"Response: {response.content[:200]}...")
    
    return {
        "messages": [AIMessage(content=response.content)],
    }


# =============================================================================
# ROUTING LOGIC
# =============================================================================

def get_next_agent(state: AgentState) -> str:
    """
    Bestimmt den nächsten Agent basierend auf dem Plan.
    
    WICHTIG: Prüft zuerst ob needs_user_input=True ist!
    Wenn ja, wird die Pipeline gestoppt und zu respond geleitet.
    
    Returns:
        Name des nächsten Nodes oder "respond" wenn Pipeline stoppen soll
    """
    plan = state.get("plan", [])
    current_step = state.get("current_step", 0)
    
    debug_print(f"get_next_agent: plan={plan}, current_step={current_step}")
    
    # ZUERST: Prüfen ob User-Input benötigt wird
    if state.get("needs_user_input", False):
        debug_print(f"needs_user_input=True, Grund: {state.get('user_input_reason')}")
        debug_print("Pipeline wird gestoppt → respond")
        return "respond"
    
    # Leerer Plan → direkt zu respond
    if not plan:
        debug_print("Leerer Plan → respond")
        return "respond"
    
    # Plan abgearbeitet → respond
    if current_step >= len(plan):
        debug_print("Plan fertig → respond")
        return "respond"
    
    # Nächster Agent im Plan
    next_agent = plan[current_step]
    debug_print(f"Nächster Agent: {next_agent}")
    return next_agent


def increment_step(state: AgentState) -> dict[str, Any]:
    """Erhöht den current_step Counter."""
    return {"current_step": state.get("current_step", 0) + 1}


# =============================================================================
# WRAPPER NODES (mit Step-Increment)
# =============================================================================

async def data_agent_wrapper(state: AgentState) -> dict[str, Any]:
    """Wrapper für Data Agent mit Step-Increment."""
    debug_print("=== DATA AGENT ===")
    result = await data_agent_node(state)
    result["current_step"] = state.get("current_step", 0) + 1
    return result


async def stats_agent_wrapper(state: AgentState) -> dict[str, Any]:
    """Wrapper für Stats Agent mit Step-Increment."""
    debug_print("=== STATS AGENT ===")
    result = await stats_agent_node(state)
    result["current_step"] = state.get("current_step", 0) + 1
    return result


async def viz_agent_wrapper(state: AgentState) -> dict[str, Any]:
    """Wrapper für Viz Agent mit Step-Increment."""
    debug_print("=== VIZ AGENT ===")
    result = await viz_agent_node(state)
    result["current_step"] = state.get("current_step", 0) + 1
    return result


# =============================================================================
# GRAPH BUILDER
# =============================================================================

def build_graph() -> StateGraph:
    """
    Baut den LangGraph StateGraph.
    
    Struktur:
    START → supervisor → router → [data_agent|stats_agent|viz_agent|respond] → ... → END
    """
    # Graph erstellen
    graph = StateGraph(AgentState)
    
    # Nodes hinzufügen
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("data_agent", data_agent_wrapper)
    graph.add_node("stats_agent", stats_agent_wrapper)
    graph.add_node("viz_agent", viz_agent_wrapper)
    graph.add_node("respond", respond_node)
    
    # START → Supervisor
    graph.add_edge(START, "supervisor")
    
    # Supervisor → Router (conditional)
    graph.add_conditional_edges(
        "supervisor",
        get_next_agent,
        {
            "data_agent": "data_agent",
            "stats_agent": "stats_agent",
            "viz_agent": "viz_agent",
            "respond": "respond",
        }
    )
    
    # Data Agent → Router
    graph.add_conditional_edges(
        "data_agent",
        get_next_agent,
        {
            "data_agent": "data_agent",  # Sollte nicht passieren
            "stats_agent": "stats_agent",
            "viz_agent": "viz_agent",
            "respond": "respond",
        }
    )
    
    # Stats Agent → Router
    graph.add_conditional_edges(
        "stats_agent",
        get_next_agent,
        {
            "data_agent": "data_agent",  # Sollte nicht passieren
            "stats_agent": "stats_agent",  # Sollte nicht passieren
            "viz_agent": "viz_agent",
            "respond": "respond",
        }
    )
    
    # Viz Agent → Router
    graph.add_conditional_edges(
        "viz_agent",
        get_next_agent,
        {
            "data_agent": "data_agent",  # Sollte nicht passieren
            "stats_agent": "stats_agent",  # Sollte nicht passieren
            "viz_agent": "viz_agent",  # Sollte nicht passieren
            "respond": "respond",
        }
    )
    
    # Respond → END
    graph.add_edge("respond", END)
    
    return graph


def compile_graph():
    """Kompiliert den Graph für die Ausführung."""
    graph = build_graph()
    return graph.compile()


# Globale Graph-Instanz (lazy initialization)
_compiled_graph = None


def get_graph():
    """Gibt die kompilierte Graph-Instanz zurück."""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = compile_graph()
    return _compiled_graph


# =============================================================================
# PUBLIC API
# =============================================================================

async def run_query(query: str) -> dict[str, Any]:
    """
    Führt eine User-Query durch den gesamten Graph.
    
    Args:
        query: Die Frage des Users
        
    Returns:
        dict mit:
        - response: Die finale Antwort
        - plan: Der ausgeführte Plan
        - data_summary: Zusammenfassung der geladenen Daten
        - statistics: Berechnete Statistiken
        - chart_url: URL zum generierten Chart
    """
    graph = get_graph()
    
    initial_state = {
        "messages": [HumanMessage(content=query)],
        "plan": None,
        "current_step": 0,
        "data": None,
        "data_summary": None,
        "data_meta": None,
        "statistics": None,
        "statistics_summary": None,
        "chart_url": None,
        "chart_type": None,
        "error": None,
    }
    
    debug_print(f"Starting query: {query}")
    
    # Graph ausführen
    result = await graph.ainvoke(initial_state)
    
    debug_print(f"Graph finished. Plan was: {result.get('plan')}")
    
    # Finale Response extrahieren
    final_response = ""
    for msg in reversed(result.get("messages", [])):
        if isinstance(msg, AIMessage) and isinstance(msg.content, str):
            final_response = msg.content
            break
    
    return {
        "response": final_response,
        "plan": result.get("plan", []),
        "reasoning": result.get("reasoning"),
        "data_summary": result.get("data_summary"),
        "statistics": result.get("statistics"),
        "statistics_summary": result.get("statistics_summary"),
        "chart_url": result.get("chart_url"),
        "chart_type": result.get("chart_type"),
        "error": result.get("error"),
    }


# =============================================================================
# STANDALONE TESTS
# =============================================================================

async def test_graph():
    """Test des kompletten Graphs mit verschiedenen Queries."""
    
    test_queries = [
        "Wie ist die aktuelle Position von Achse 1?",
        "Zeig mir den Verlauf der Bahngeschwindigkeit der letzten 5 Minuten als Liniendiagramm",
        "Was ist der Durchschnitt der Achsposition 1 der letzten 10 Minuten?",
        "Wie wird das Wetter morgen?",  # Sollte ablehnen
    ]
    
    print("\n" + "="*70)
    print("🧪 Graph End-to-End Test")
    print("="*70)
    
    for query in test_queries:
        print(f"\n{'='*70}")
        print(f"📝 Query: {query}")
        print("="*70)
        
        try:
            result = await run_query(query)
            
            print(f"\n📋 Plan: {result['plan']}")
            if result.get('reasoning'):
                print(f"💭 Reasoning: {result['reasoning']}")
            
            if result.get('data_summary'):
                print(f"📊 Daten: {result['data_summary']}")
            
            if result.get('statistics_summary'):
                print(f"📈 Statistik: {result['statistics_summary']}")
            
            if result.get('chart_url'):
                print(f"🖼️  Chart: {result['chart_url']}")
            
            if result.get('error'):
                print(f"❌ Fehler: {result['error']}")
            
            print(f"\n🤖 Response:\n{result['response']}")
            
        except Exception as e:
            print(f"❌ Exception: {str(e)}")
            import traceback
            traceback.print_exc()
        
        print()


async def interactive_test():
    """Interaktiver Test mit eigenen Queries."""
    print("\n" + "="*60)
    print("🤖 Conversational Analytics - Interactive Test")
    print("="*60)
    print("Gib eine Frage ein (oder 'quit' zum Beenden):\n")
    
    while True:
        query = input("📝 Du: ").strip()
        
        if query.lower() in ["quit", "exit", "q"]:
            break
        
        if not query:
            continue
        
        print("\n⏳ Verarbeite...")
        
        try:
            result = await run_query(query)
            
            print(f"\n📋 Plan: {result['plan']}")
            
            if result.get('chart_url'):
                print(f"🖼️  Chart: {result['chart_url']}")
            
            print(f"\n🤖 Assistent: {result['response']}")
            
        except Exception as e:
            print(f"❌ Fehler: {str(e)}")
        
        print("\n" + "-"*40)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--interactive":
        asyncio.run(interactive_test())
    else:
        asyncio.run(test_graph())
