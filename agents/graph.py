"""
LangGraph Orchestrierung für das Conversational Analytics System.

Der Graph verbindet alle Agents und führt sie basierend auf dem
Supervisor-Plan in der richtigen Reihenfolge aus.

Ablauf:
1. Supervisor erstellt Plan
2. Agents werden gemäß Plan ausgeführt
3. Respond-Node generiert finale Antwort

DESIGN-ENTSCHEIDUNGEN:
- DEC-013: Multi-Turn Support mit Checkpointer
- DEC-016: Strukturiertes Logging
- DEC-017: Graph Best Practices (max_steps, error_handler, validation)
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import asyncio
import logging
import threading
from typing import Literal, Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver

from agents.state import AgentState, TurnEntry, TurnDataset
from agents.supervisor import supervisor_node
from agents.data_agent import data_agent_node
from agents.stats_agent import stats_agent_node
from agents.viz_agent import viz_agent_node
from prompts.respond_prompt import RESPOND_SYSTEM_PROMPT
from config.settings import DEFAULT_MODEL, api_key_rotator, create_anthropic_client, create_cached_system_message


# =============================================================================
# LOGGING KONFIGURATION (DEC-016)
# =============================================================================

logger = logging.getLogger(__name__)


# =============================================================================
# KONSTANTEN
# =============================================================================

# Alle verfügbaren Agent-Nodes
AGENT_NODES = ["data_agent", "stats_agent", "viz_agent"]

# Routing-Map für conditional edges (DRY)
ROUTING_MAP = {agent: agent for agent in AGENT_NODES}
ROUTING_MAP["respond"] = "respond"
ROUTING_MAP["error_handler"] = "error_handler"

# Maximale Schritte bevor Notfall-Exit (Cycle Guard)
DEFAULT_MAX_STEPS = 10


# =============================================================================
# TURN HISTORY HELPERS (DEC-029 AP2)
# =============================================================================

def _format_timerange(timerange: dict) -> str:
    """Formatiert timerange dict zu lesbarem String."""
    if not timerange:
        return ""
    start = timerange.get("start_human") or timerange.get("start", "")
    end = timerange.get("end_human") or timerange.get("end", "")
    if start and end:
        return f"{start} - {end}"
    return str(start or end or "")


def _group_datasets_by_timerange(state: AgentState) -> list[dict]:
    """Gruppiert aktive Datasets nach Zeitraum für TurnEntry."""
    all_datasets = state.get("datasets", {})
    active_keys = state.get("active_dataset_keys")

    # Nur aktive Datasets (dieser Turn)
    if active_keys:
        filtered = {k: v for k, v in all_datasets.items() if k in active_keys}
    else:
        filtered = all_datasets

    # Gruppiere nach timerange-String
    groups: dict[str, list[str]] = {}  # timerange -> signal_keys
    for ds_key, ds_meta in filtered.items():
        if not isinstance(ds_meta, dict):
            continue
        timerange = ds_meta.get("timerange", {})
        tr_str = _format_timerange(timerange)
        signal_keys = ds_meta.get("keys", [])
        groups.setdefault(tr_str, []).extend(signal_keys)

    # Dedupliziere keys pro Gruppe
    return [
        {"keys": sorted(set(keys)), "timerange": tr}
        for tr, keys in groups.items()
        if keys
    ]


def _determine_result_type(state: AgentState) -> str:
    """Bestimmt den Ergebnis-Typ des aktuellen Turns."""
    if state.get("chart_url"):
        return "chart"
    if state.get("statistics_summary"):
        return "statistics"
    if state.get("needs_user_input"):
        return "clarification"
    if state.get("error"):
        return "error"
    plan = state.get("plan")
    if plan == []:
        return "abstention"
    return "data"


def _determine_result_summary(state: AgentState, result_type: str) -> str:
    """Erstellt eine kurze Zusammenfassung des Ergebnisses."""
    if result_type == "statistics":
        return (state.get("statistics_summary") or "")[:300]
    if result_type == "chart":
        return state.get("chart_type") or "Chart erstellt"
    if result_type == "error":
        return (state.get("error") or "")[:200]
    if result_type == "abstention":
        return (state.get("reasoning") or "")[:200]
    if result_type == "clarification":
        return (state.get("user_input_reason") or "")[:200]
    # data: Zusammenfassung aus aktiven DatasetMeta
    active_keys = state.get("active_dataset_keys") or []
    datasets = state.get("datasets", {})
    parts = []
    for k in active_keys[:3]:
        ds = datasets.get(k)
        if isinstance(ds, dict):
            keys = ds.get("keys", [])
            pts = ds.get("point_count", "?")
            parts.append(f"{', '.join(keys[:2])}: {pts} Punkte")
    return "; ".join(parts)[:200] if parts else ""


def _build_turn_entry(state: AgentState) -> dict:
    """Baut einen TurnEntry aus dem aktuellen State (DEC-029 AP2)."""
    messages = state.get("messages", [])

    # user_query: Letzte HumanMessage, truncated auf 200 Zeichen
    user_query = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            user_query = msg.content[:200]
            break

    # plan
    plan = state.get("plan") or []

    # data_mode
    data_mode = state.get("data_retrieval_mode", "overview")

    # datasets: Gruppiert nach Zeitraum aus DatasetMeta
    datasets_grouped = _group_datasets_by_timerange(state)

    # result_type
    result_type = _determine_result_type(state)

    # result_summary
    result_summary = _determine_result_summary(state, result_type)

    entry: dict = {"user_query": user_query, "plan": plan, "data_mode": data_mode}
    if datasets_grouped:
        entry["datasets"] = datasets_grouped
    entry["result_type"] = result_type
    if result_summary:
        entry["result_summary"] = result_summary
    return entry


# =============================================================================
# RESPOND NODE
# =============================================================================

async def respond_node(state: AgentState) -> dict[str, Any]:
    """
    Generiert die finale Antwort für den User.
    
    WICHTIG: Bei needs_user_input=True wird die Frage des vorherigen Agents
    direkt weitergegeben (keine neue Response generieren!).
    """
    logger.debug("Starte Respond Node")
    
    # State-Validierung
    messages = state.get("messages")
    if not messages:
        logger.warning("Keine Messages im State!")
        return {
            "messages": [AIMessage(content="Es ist ein Fehler aufgetreten: Keine Anfrage gefunden.")],
            "turn_history": [_build_turn_entry(state)],
        }
    
    # SPEZIALFALL: User-Input wird benötigt
    if state.get("needs_user_input", False):
        logger.debug(f"needs_user_input=True: {state.get('user_input_reason')}")
        
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and isinstance(msg.content, str):
                logger.debug("Gebe vorherige AI-Message direkt weiter")
                return {"messages": [msg], "turn_history": [_build_turn_entry(state)]}

        return {
            "messages": [AIMessage(content="Es ist ein Problem aufgetreten. Bitte versuche es nochmal.")],
            "turn_history": [_build_turn_entry(state)],
        }
    
    # Sammle Kontext für normale Response
    context_parts = []
    
    # Aktuelle User-Query (die LETZTE HumanMessage)
    user_query = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            user_query = msg.content
            break
    
    if not user_query:
        logger.warning("Keine User-Query gefunden!")
    
    context_parts.append(f"User-Anfrage: {user_query}")
    
    # Plan
    plan = state.get("plan")
    if plan:
        context_parts.append(f"Ausgeführte Agents: {plan}")
    
    # Datasets Info (DEC-025: DatasetMeta oder Legacy)
    # Nur aktive Datasets dieses Turns anzeigen (nicht akkumulierte aus vorherigen Turns)
    all_datasets = state.get("datasets", {})
    active_keys = state.get("active_dataset_keys")
    if active_keys:
        datasets = {k: v for k, v in all_datasets.items() if k in active_keys}
    else:
        datasets = all_datasets
    if datasets:
        context_parts.append(f"Verfügbare Datasets: {', '.join(datasets.keys())}")
        context_parts.append("\n## DATENWERTE")

        for ds_name, ds_content in datasets.items():
            if not isinstance(ds_content, dict):
                continue

            # DEC-025: DatasetMeta-Format (hat "dataset_key")
            if "dataset_key" in ds_content:
                context_parts.append(f"\n### Dataset: {ds_name}")
                signal_keys = ds_content.get("keys", [])
                point_count = ds_content.get("point_count", "?")
                timerange = ds_content.get("timerange", {})
                context_parts.append(f"- Signals: {', '.join(signal_keys[:6])}")
                context_parts.append(f"- Punkte: {point_count}")
                if timerange:
                    start = timerange.get("start") or timerange.get("start_human", "?")
                    end = timerange.get("end") or timerange.get("end_human", "?")
                    context_parts.append(f"- Zeitraum: {start} - {end}")

                # Statistiken aus Meta
                meta = ds_content.get("meta", {})
                if isinstance(meta, dict) and meta.get("statistics"):
                    stats = meta["statistics"]
                    for sk, sv in list(stats.items())[:3]:
                        if isinstance(sv, dict):
                            context_parts.append(
                                f"- {sk}: min={sv.get('min','?')}, max={sv.get('max','?')}, avg={sv.get('avg','?')}"
                            )
            else:
                # Legacy-Format: hat "data" Key
                data = ds_content.get("data", {})
                if not isinstance(data, dict):
                    continue

                context_parts.append(f"\n### Dataset: {ds_name}")

                for key, values in data.items():
                    if isinstance(values, list) and len(values) > 0:
                        if isinstance(values[0], dict) and "value" in values[0]:
                            first_val = values[0].get("value", "?")
                            last_val = values[-1].get("value", "?")
                            context_parts.append(f"- {key}: {len(values)} Punkte, von {first_val} bis {last_val}")
                        else:
                            context_parts.append(f"- {key}: {len(values)} Werte")
                    elif isinstance(values, dict) and "value" in values:
                        val = values.get("value", "?")
                        ts = values.get("timestamp", "?")
                        context_parts.append(f"- {key}: {val} (Zeitstempel: {ts})")
                    else:
                        context_parts.append(f"- {key}: {values}")
    
    # Statistiken
    if state.get("statistics"):
        context_parts.append(f"Statistiken: {state['statistics']}")
    if state.get("statistics_summary"):
        context_parts.append(f"Statistik-Zusammenfassung: {state['statistics_summary']}")
    
    # Chart
    chart_url = state.get("chart_url")
    if chart_url:
        context_parts.append(f"Chart erstellt: {chart_url}")
        context_parts.append(f"Chart-Typ: {state.get('chart_type', 'unbekannt')}")
    
    # Fehler
    error = state.get("error")
    if error:
        context_parts.append(f"Fehler aufgetreten: {error}")
    
    # Leerer Plan (Abstention)
    if plan == []:
        context_parts.append("HINWEIS: Die Anfrage konnte nicht bearbeitet werden (kein Plan erstellt)")
        reasoning = state.get("reasoning")
        if reasoning:
            context_parts.append(f"Grund: {reasoning}")
    
    context = "\n".join(context_parts)
    logger.info(f"Respond-Context ({len(context)} chars):\n{context}")
    
    # LLM für Response (DEC-018: API Key Rotation, DEC-021: Prompt Caching)
    llm = create_anthropic_client(temperature=0.3)

    llm_messages = [
        create_cached_system_message(RESPOND_SYSTEM_PROMPT),
        HumanMessage(content=f"Erstelle eine Antwort basierend auf:\n\n{context}"),
    ]

    response = await llm.ainvoke(llm_messages)
    logger.debug(f"Response generiert: {response.content[:100]}...")

    return {
        "messages": [AIMessage(content=response.content)],
        "turn_history": [_build_turn_entry(state)],
    }


# =============================================================================
# ERROR HANDLER NODE
# =============================================================================

async def error_handler_node(state: AgentState) -> dict[str, Any]:
    """
    Behandelt Fehler von Agents.
    
    Strategie:
    - Loggt den Fehler
    - Erhöht error_count
    - Setzt freundliche Fehlermeldung
    """
    error = state.get("error", "Unbekannter Fehler")
    error_count = state.get("error_count", 0) + 1
    
    logger.error(f"Error Handler aufgerufen (Fehler #{error_count}): {error}")
    
    # Freundliche Fehlermeldung für User
    error_message = f"Bei der Verarbeitung ist ein Fehler aufgetreten: {error}"
    
    if error_count >= 3:
        error_message += "\n\nBitte versuche es später nochmal oder formuliere deine Anfrage anders."
        logger.warning(f"Max Fehleranzahl erreicht ({error_count})")
    
    return {
        "error_count": error_count,
        "messages": [AIMessage(content=error_message)],
    }


# =============================================================================
# ROUTING LOGIC
# =============================================================================

def get_next_agent(state: AgentState) -> str:
    """
    Bestimmt den nächsten Agent basierend auf dem Plan.
    
    Prüft:
    1. max_steps überschritten? → respond (Notfall-Exit)
    2. needs_user_input? → respond (Pipeline stoppen)
    3. error vorhanden? → error_handler
    4. Plan leer oder fertig? → respond
    5. Sonst: nächster Agent im Plan
    """
    plan = state.get("plan", [])
    current_step = state.get("current_step", 0)
    max_steps = state.get("max_steps", DEFAULT_MAX_STEPS)
    
    logger.debug(f"Router: plan={plan}, step={current_step}/{max_steps}")
    
    # 1. Cycle Guard: max_steps überschritten
    if current_step >= max_steps:
        logger.warning(f"max_steps erreicht ({current_step}/{max_steps}) - Notfall-Exit!")
        return "respond"
    
    # 2. User-Input benötigt
    if state.get("needs_user_input", False):
        logger.debug(f"needs_user_input=True → respond")
        return "respond"
    
    # 3. Fehler vorhanden (aber nicht schon behandelt)
    error = state.get("error")
    error_count = state.get("error_count", 0)
    if error and error_count == 0:
        logger.debug(f"Fehler erkannt → error_handler")
        return "error_handler"
    
    # 4. Leerer Plan oder Plan fertig
    if not plan:
        logger.debug("Leerer Plan → respond")
        return "respond"
    
    if current_step >= len(plan):
        logger.debug("Plan fertig → respond")
        return "respond"
    
    # 5. Nächster Agent
    next_agent = plan[current_step]
    logger.debug(f"Nächster Agent: {next_agent}")
    return next_agent


def route_after_error(state: AgentState) -> str:
    """
    Routing nach Error Handler.
    
    Bei zu vielen Fehlern: direkt zu respond.
    Sonst: zurück zum Router (retry möglich).
    """
    error_count = state.get("error_count", 0)
    
    if error_count >= 3:
        logger.warning("Zu viele Fehler - gehe zu respond")
        return "respond"
    
    # Error wurde behandelt, gehe zu respond
    return "respond"


# =============================================================================
# AGENT WRAPPER FACTORY (DRY)
# =============================================================================

def make_agent_wrapper(agent_func, agent_name: str):
    """
    Factory für Agent-Wrapper mit Step-Increment und Error-Handling.
    
    Args:
        agent_func: Die eigentliche Agent-Funktion
        agent_name: Name für Logging
    """
    async def wrapper(state: AgentState) -> dict[str, Any]:
        logger.info(f"=== {agent_name.upper()} ===")
        
        try:
            result = await agent_func(state)
            result["current_step"] = state.get("current_step", 0) + 1
            
            # Error-Flag zurücksetzen wenn erfolgreich
            if "error" not in result:
                result["error"] = None
            
            return result
            
        except Exception as e:
            logger.error(f"{agent_name} Exception: {e}", exc_info=True)
            return {
                "current_step": state.get("current_step", 0) + 1,
                "error": str(e),
                "messages": [AIMessage(content=f"Fehler in {agent_name}: {str(e)}")],
            }
    
    return wrapper


# =============================================================================
# GRAPH BUILDER
# =============================================================================

def build_graph() -> StateGraph:
    """
    Baut den LangGraph StateGraph.
    
    Struktur:
    START → supervisor → router → [agents|error_handler|respond] → ... → END
    """
    graph = StateGraph(AgentState)
    
    # Nodes hinzufügen
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("data_agent", make_agent_wrapper(data_agent_node, "data_agent"))
    graph.add_node("stats_agent", make_agent_wrapper(stats_agent_node, "stats_agent"))
    graph.add_node("viz_agent", make_agent_wrapper(viz_agent_node, "viz_agent"))
    graph.add_node("error_handler", error_handler_node)
    graph.add_node("respond", respond_node)
    
    # START → Supervisor
    graph.add_edge(START, "supervisor")
    
    # Supervisor → Router
    graph.add_conditional_edges("supervisor", get_next_agent, ROUTING_MAP)
    
    # Alle Agents → Router (DRY: eine Schleife statt Copy-Paste)
    for agent in AGENT_NODES:
        graph.add_conditional_edges(agent, get_next_agent, ROUTING_MAP)
    
    # Error Handler → respond oder retry
    graph.add_conditional_edges(
        "error_handler",
        route_after_error,
        {"respond": "respond"}
    )
    
    # Respond → END
    graph.add_edge("respond", END)
    
    return graph


def compile_graph():
    """
    Kompiliert den Graph für die Ausführung.
    
    Nutzt InMemorySaver für State-Persistenz zwischen Turns (DEC-013).
    Für Production: PostgresSaver oder SqliteSaver verwenden.
    """
    graph = build_graph()
    checkpointer = InMemorySaver()
    
    logger.info("Graph kompiliert mit InMemorySaver")
    return graph.compile(checkpointer=checkpointer)


# =============================================================================
# SINGLETON GRAPH INSTANCE (Thread-Safe)
# =============================================================================

_graph_lock = threading.Lock()
_compiled_graph = None


def get_graph():
    """
    Gibt die kompilierte Graph-Instanz zurück (Thread-Safe Singleton).
    """
    global _compiled_graph
    
    if _compiled_graph is None:
        with _graph_lock:
            if _compiled_graph is None:  # Double-check
                logger.info("Erstelle Graph-Instanz...")
                _compiled_graph = compile_graph()
    
    return _compiled_graph


# =============================================================================
# PUBLIC API
# =============================================================================

async def run_query(
    query: str,
    thread_id: str = "default",
    session_id: str | None = None,
) -> dict[str, Any]:
    """
    Führt eine User-Query durch den gesamten Graph.

    Args:
        query: Die Frage des Users
        thread_id: Eindeutige ID für die Konversation (für State-Persistenz)
        session_id: DuckDB SessionStore ID (DEC-025, default: thread_id)

    Returns:
        dict mit response, plan, statistics, chart_url, etc.
    """
    graph = get_graph()

    # Config mit thread_id für Checkpointer
    config = {"configurable": {"thread_id": thread_id}}

    # DEC-025: SessionStore als "in use" markieren (Schutz gegen Destroy bei Page-Refresh)
    effective_session_id = session_id or thread_id
    try:
        from config.duckdb_store import SessionStore
        store = SessionStore.get_instance(effective_session_id)
        store.acquire()
    except Exception:
        pass  # Store existiert evtl. noch nicht — OK

    # Graph ausführen
    try:
        input_state = {
            "messages": [HumanMessage(content=query)],
            "max_steps": DEFAULT_MAX_STEPS,
            "session_id": session_id or thread_id,
        }
        logger.info(f"Query starten: '{query[:50]}...' (thread: {thread_id})")
        result = await graph.ainvoke(input_state, config)
    finally:
        # Store wieder freigeben
        try:
            store = SessionStore.get_instance(effective_session_id)
            store.release()
        except Exception:
            pass

    logger.info(f"Query fertig. Plan war: {result.get('plan')}")

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
        "statistics": result.get("statistics"),
        "statistics_summary": result.get("statistics_summary"),
        "chart_url": result.get("chart_url"),
        "chart_type": result.get("chart_type"),
        "error": result.get("error"),
    }


# =============================================================================
# TESTS
# =============================================================================

async def test_graph():
    """Test des kompletten Graphs mit verschiedenen Queries."""
    
    # Logging für Tests
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    test_queries = [
        "Wie ist die aktuelle Position von Achse 1?",
        "Zeig mir den Verlauf der Drehmomente der letzten 5 Minuten",
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


if __name__ == "__main__":
    asyncio.run(test_graph())
