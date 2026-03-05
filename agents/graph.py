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
from datetime import datetime
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
from config.duckdb_store import SessionStore
from agents.utils import get_dataset_meta_from_duckdb


# =============================================================================
# LOGGING KONFIGURATION (DEC-016)
# =============================================================================

logger = logging.getLogger(__name__)

# Debug-Log: Gleiche Datei wie supervisor für vollständigen Flow
_FLOW_DEBUG_LOG = PROJECT_ROOT / "logs" / "supervisor_debug.log"


def _log_flow_event(event_type: str, details: dict) -> None:
    """Schreibt ein Graph-Flow-Event in die Debug-Datei.

    Args:
        event_type: z.B. "AGENT_START", "AGENT_RESULT", "ROUTING", "REPLAN_BRIDGE"
        details: Key-Value-Paare mit relevanten Infos
    """
    _FLOW_DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep = "-" * 60

    lines = [
        "",
        sep,
        f"  {event_type}  |  {timestamp}",
        sep,
    ]
    for key, value in details.items():
        lines.append(f"  {key}: {value}")
    lines.append("")

    with open(_FLOW_DEBUG_LOG, "a", encoding="utf-8") as f:
        f.write("\n".join(lines))


# =============================================================================
# KONSTANTEN
# =============================================================================

# Alle verfügbaren Agent-Nodes
AGENT_NODES = ["data_agent", "stats_agent", "viz_agent"]

# Routing-Map für conditional edges (DRY)
ROUTING_MAP = {agent: agent for agent in AGENT_NODES}
ROUTING_MAP["respond"] = "respond"
ROUTING_MAP["error_handler"] = "error_handler"
ROUTING_MAP["replan_bridge"] = "replan_bridge"

# Maximale Schritte bevor Notfall-Exit (Cycle Guard)
DEFAULT_MAX_STEPS = 15


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
    active_keys = state.get("active_dataset_keys")

    # DEC-031: DuckDB ist Single Source of Truth
    session_id = state.get("session_id", "default")
    filtered = get_dataset_meta_from_duckdb(session_id, active_keys)

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
    if state.get("data_response"):
        return "info"
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
    if result_type == "info":
        return (state.get("data_response") or "")[:200]
    # data: Zusammenfassung aus aktiven DatasetMeta (DEC-031: DuckDB-first)
    active_keys = state.get("active_dataset_keys") or []
    session_id = state.get("session_id", "default")
    datasets = get_dataset_meta_from_duckdb(session_id, active_keys)
    parts = []
    for k in active_keys[:3]:
        ds = datasets.get(k)
        if isinstance(ds, dict):
            keys = ds.get("keys", [])
            pts = ds.get("point_count", "?")
            parts.append(f"{', '.join(keys[:2])}: {pts} Punkte")
    if parts:
        return "; ".join(parts)[:200]
    # Fallback: data_response (Attribute, Key-Listings etc.)
    data_response = state.get("data_response")
    if data_response:
        return data_response[:200]
    return ""


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

    # DEC-030: Stats-Dataset-Keys in turn_history aufnehmen
    active_stats = state.get("active_stats_keys")
    if active_stats:
        entry["stats_dataset_keys"] = active_stats

    # DEC-034: Stats-Findings für Cross-Turn-Referenzen
    stats_findings = state.get("stats_findings")
    if stats_findings:
        entry["key_facts"] = stats_findings

    return entry


# =============================================================================
# REPLAN BRIDGE (DEC-032)
# =============================================================================

async def replan_bridge(state: AgentState) -> dict[str, Any]:
    """Erstellt Snapshot der Phase-Ergebnisse und routet zurück zum Supervisor."""
    logger.info("=== REPLAN BRIDGE ===")
    result = {
        "replan_count": state.get("replan_count", 0) + 1,
        "replan_context": {
            "phase": state.get("replan_count", 0) + 1,
            "plan": state.get("plan", []),
            "active_dataset_keys": state.get("active_dataset_keys"),
            "active_stats_keys": state.get("active_stats_keys"),
            "statistics_summary": state.get("statistics_summary"),
            "data_retrieval_mode": state.get("data_retrieval_mode"),
            "agent_signals": state.get("agent_signals"),
        },
    }

    _log_flow_event("REPLAN_BRIDGE", {
        "new_replan_count": result["replan_count"],
        "snapshot": result["replan_context"],
    })

    return result


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
    
    # DEC-032: Plan und Step zurücksetzen damit der nächste Turn sauber im PLAN-Modus startet
    turn_reset = {"plan": None, "current_step": 0}

    # State-Validierung
    messages = state.get("messages")
    if not messages:
        logger.warning("Keine Messages im State!")
        return {
            **turn_reset,
            "messages": [AIMessage(content="Es ist ein Fehler aufgetreten: Keine Anfrage gefunden.")],
            "turn_history": [_build_turn_entry(state)],
        }
    
    # SPEZIALFALL: User-Input wird benötigt
    if state.get("needs_user_input", False):
        logger.debug(f"needs_user_input=True: {state.get('user_input_reason')}")
        
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and isinstance(msg.content, str):
                logger.debug("Gebe vorherige AI-Message direkt weiter")
                return {**turn_reset, "messages": [msg], "turn_history": [_build_turn_entry(state)]}

        return {
            **turn_reset,
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
    
    # Datasets Info (DEC-031: DuckDB-first, Fallback auf State)
    # Nur aktive Datasets dieses Turns anzeigen (nicht akkumulierte aus vorherigen Turns)
    active_keys = state.get("active_dataset_keys")
    session_id = state.get("session_id", "default")
    datasets = get_dataset_meta_from_duckdb(session_id, active_keys)

    if datasets:
        context_parts.append(f"Verfügbare Datasets: {', '.join(datasets.keys())}")
        context_parts.append("\n## DATENWERTE")

        for ds_name, ds_content in datasets.items():
            if not isinstance(ds_content, dict):
                continue

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

            # Aktuellster Wert pro Signal (jüngster Timestamp)
            try:
                if session_id in SessionStore._instances:
                    store = SessionStore.get_instance(session_id)
                    rows = store._conn.execute(
                        """SELECT signal_key, value, unit
                           FROM telemetry t1
                           WHERE dataset_key = ?
                             AND ts = (SELECT MAX(ts) FROM telemetry t2
                                       WHERE t2.dataset_key = t1.dataset_key
                                         AND t2.signal_key = t1.signal_key)""",
                        [ds_name],
                    ).fetchall()
                    for sig_key, value, unit in rows:
                        unit_str = f" {unit}" if unit else ""
                        context_parts.append(f"- {sig_key} aktuell: {float(value):.4g}{unit_str}")
            except Exception:
                pass  # Graceful fallback to metadata-only

            # Statistiken aus Meta
            meta = ds_content.get("meta", {})
            if isinstance(meta, dict) and meta.get("statistics"):
                stats = meta["statistics"]
                for sk, sv in list(stats.items())[:3]:
                    if isinstance(sv, dict):
                        context_parts.append(
                            f"- {sk}: min={sv.get('min','?')}, max={sv.get('max','?')}, avg={sv.get('avg','?')}"
                        )
    
    # Data Response: Text-Antwort des Data Agents (Attribute, Key-Listings, Geräte-Infos)
    data_response = state.get("data_response")
    if data_response:
        context_parts.append(f"\n## DATEN-ERGEBNIS\n{data_response}")

    # DEC-032: Ergebnisse vorheriger Phase (Replan-Kontext)
    if state.get("replan_context"):
        rc = state["replan_context"]
        context_parts.append("\n## ERGEBNISSE VORHERIGER PHASE")
        if rc.get("statistics_summary"):
            context_parts.append(f"Statistik: {rc['statistics_summary']}")
        if rc.get("active_dataset_keys"):
            context_parts.append(f"Daten: {', '.join(rc['active_dataset_keys'])}")

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
        **turn_reset,
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
    
    def _route_decision(target: str, reason: str) -> str:
        _log_flow_event("ROUTING", {
            "decision": target,
            "reason": reason,
            "plan": plan,
            "current_step": current_step,
            "pending_goals": state.get("pending_goals"),
            "replan_count": state.get("replan_count", 0),
        })
        return target

    # 1. Cycle Guard: max_steps überschritten
    if current_step >= max_steps:
        logger.warning(f"max_steps erreicht ({current_step}/{max_steps}) - Notfall-Exit!")
        return _route_decision("respond", f"max_steps erreicht ({current_step}/{max_steps})")

    # 2. User-Input benötigt
    if state.get("needs_user_input", False):
        logger.debug("needs_user_input=True → respond")
        return _route_decision("respond", "needs_user_input=True")

    # 3. Fehler vorhanden (aber nicht schon behandelt)
    error = state.get("error")
    error_count = state.get("error_count", 0)
    if error and error_count == 0:
        logger.debug(f"Fehler erkannt → error_handler")
        return _route_decision("error_handler", f"error={error}")

    # 4. Leerer Plan oder Plan fertig
    if not plan:
        logger.debug("Leerer Plan → respond")
        return _route_decision("respond", "Leerer Plan")

    if current_step >= len(plan):
        if state.get("pending_goals") and state.get("replan_count", 0) < 2:
            logger.debug("Plan fertig, pending_goals vorhanden -> replan_bridge")
            return _route_decision("replan_bridge", f"pending_goals={state.get('pending_goals')}")
        logger.debug("Plan fertig → respond")
        return _route_decision("respond", "Plan abgeschlossen")
    
    # 5. Nächster Agent
    next_agent = plan[current_step]
    logger.debug(f"Nächster Agent: {next_agent}")
    return _route_decision(next_agent, f"plan[{current_step}]")


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

        # Debug-Log: Was der Agent als Input sieht (vom Supervisor)
        _log_flow_event(f"AGENT_START: {agent_name}", {
            "step": f"{state.get('current_step', 0)} / plan={state.get('plan', [])}",
            "data_retrieval_mode": state.get("data_retrieval_mode"),
            "data_instructions": state.get("data_instructions"),
            "active_dataset_keys": state.get("active_dataset_keys"),
            "active_stats_keys": state.get("active_stats_keys"),
            "statistics_summary": (state.get("statistics_summary") or "")[:200],
            "chart_url": state.get("chart_url"),
            "error": state.get("error"),
        })

        try:
            result = await agent_func(state)
            result["current_step"] = state.get("current_step", 0) + 1

            # Error-Flag zurücksetzen wenn erfolgreich
            if "error" not in result:
                result["error"] = None

            # Debug-Log: Was der Agent zurückgibt (an State → Supervisor EVAL)
            _log_flow_event(f"AGENT_RESULT: {agent_name}", {
                "active_dataset_keys": result.get("active_dataset_keys"),
                "active_stats_keys": result.get("active_stats_keys"),
                "statistics_summary": (result.get("statistics_summary") or "")[:200],
                "chart_url": result.get("chart_url"),
                "chart_type": result.get("chart_type"),
                "error": result.get("error"),
                "agent_signals": result.get("agent_signals"),
                "messages_count": len(result.get("messages", [])),
            })

            return result

        except Exception as e:
            logger.error(f"{agent_name} Exception: {e}", exc_info=True)
            _log_flow_event(f"AGENT_ERROR: {agent_name}", {"error": str(e)})
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
    graph.add_node("replan_bridge", replan_bridge)
    graph.add_node("error_handler", error_handler_node)
    graph.add_node("respond", respond_node)
    
    # START → Supervisor
    graph.add_edge(START, "supervisor")
    
    # Supervisor → Router
    graph.add_conditional_edges("supervisor", get_next_agent, ROUTING_MAP)
    
    # Alle Agents → Supervisor (feste Edge, DEC-032: Eval nach jedem Agent)
    for agent in AGENT_NODES:
        graph.add_edge(agent, "supervisor")
    
    # Replan Bridge → Supervisor (feste Edge, DEC-032)
    graph.add_edge("replan_bridge", "supervisor")

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

async def stream_query(
    query: str,
    thread_id: str = "default",
    session_id: str | None = None,
):
    """
    Streamt Graph-Events für Live-UI-Updates.

    Yields (mode, chunk) Tuples:
    - ("updates", {node_name: state_dict}) nach jeder Node-Ausführung
    - ("messages", (msg_chunk, metadata)) für LLM-Tokens während der Ausführung

    Args:
        query: Die Frage des Users
        thread_id: Eindeutige ID für die Konversation
        session_id: DuckDB SessionStore ID (default: thread_id)
    """
    graph = get_graph()
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 30}

    effective_session_id = session_id or thread_id
    try:
        store = SessionStore.get_instance(effective_session_id)
        store.acquire()
    except Exception:
        pass

    input_state = {
        "messages": [HumanMessage(content=query)],
        "max_steps": DEFAULT_MAX_STEPS,
        "session_id": effective_session_id,
    }

    logger.info(f"Stream starten: '{query[:50]}...' (thread: {thread_id})")
    try:
        async for event in graph.astream(
            input_state, config, stream_mode=["updates", "messages"]
        ):
            yield event
    finally:
        try:
            store = SessionStore.get_instance(effective_session_id)
            store.release()
        except Exception:
            pass


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
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 30}

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

    # Plan aus turn_history extrahieren (respond_node setzt plan=None für Multi-Turn)
    plan = result.get("plan") or []
    if not plan:
        turn_history = result.get("turn_history") or []
        if turn_history:
            plan = turn_history[-1].get("plan") or []
    logger.info(f"Query fertig. Plan war: {plan}")

    # Finale Response extrahieren
    final_response = ""
    for msg in reversed(result.get("messages", [])):
        if isinstance(msg, AIMessage) and isinstance(msg.content, str):
            final_response = msg.content
            break

    return {
        "response": final_response,
        "plan": plan,
        "reasoning": result.get("reasoning"),
        "statistics": result.get("statistics"),
        "statistics_summary": result.get("statistics_summary"),
        "chart_url": result.get("chart_url"),
        "chart_type": result.get("chart_type"),
        "error": result.get("error"),
        "messages": result.get("messages", []),
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
