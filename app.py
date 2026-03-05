"""
Chainlit Frontend für das Conversational Analytics System.

Startet mit: chainlit run app.py

PERFORMANCE-OPTIMIERUNG (19.12.2025):
- MCP Server werden beim Chat-Start vorgewärmt
- Erster Request ist dadurch auch schnell!
"""

import sys
from pathlib import Path

# Projekt-Root zu sys.path hinzufügen
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

import asyncio
import logging
import time
import uuid
import chainlit as cl
from chainlit import Message, Image, Text
from langchain_core.messages import AIMessageChunk

logger = logging.getLogger(__name__)

from agents.graph import run_query, stream_query
from agents.data_agent import get_mcp_tools
from agents.viz_agent import get_antv_tools
from agents.stats_agent import get_stats_tools
from config.duckdb_store import SessionStore


# =============================================================================
# STEP-KONFIGURATION FÜR STREAMING UI
# =============================================================================

# Status-Banner Konfiguration: Emoji + Label + Default-Detail pro Agent-Node
STATUS_CONFIG = {
    "supervisor": {
        "icon": "\u2699\ufe0f",
        "label": "Analyse & Planung",
        "detail": "Anfrage wird analysiert",
    },
    "data_agent": {
        "icon": "\U0001f4e1",
        "label": "Daten abrufen",
        "detail": "Lade Telemetrie-Daten von ThingsBoard",
    },
    "stats_agent": {
        "icon": "\U0001f4ca",
        "label": "Statistik berechnen",
        "detail": "Berechne statistische Kennwerte",
    },
    "viz_agent": {
        "icon": "\U0001f3a8",
        "label": "Visualisierung erstellen",
        "detail": "Erstelle Diagramm",
    },
    "replan_bridge": {
        "icon": "\U0001f504",
        "label": "N\u00e4chste Phase",
        "detail": "Bereite n\u00e4chsten Schritt vor",
    },
    "error_handler": {
        "icon": "\u26a0\ufe0f",
        "label": "Fehler behandeln",
        "detail": "Fehler wird verarbeitet",
    },
}

# Kurzlabels für die Progress-Bar (Agent-Name → kurzer Text)
_PROGRESS_LABELS = {
    "data_agent": "Daten abrufen",
    "stats_agent": "Stats berechnen",
    "viz_agent": "Visualisierung",
}

# Tool-Call Labels: MCP/Agent Tool-Namen → deutsche Beschreibung
TOOL_LABELS = {
    # ThingsBoard MCP Tools
    "search_telemetry_keys": "Telemetrie-Keys suchen",
    "get_telemetry": "Telemetrie-Daten abrufen",
    "get_latest_telemetry": "Aktuelle Werte abrufen",
    "check_data_availability": "Datenverfügbarkeit prüfen",
    "get_device_info": "Geräte-Info abrufen",
    "check_dataset": "Vorhandene Daten prüfen",
    # Viz Agent Chart Tools
    "generate_line_chart_tool": "Line-Chart erstellen",
    "generate_area_chart_tool": "Area-Chart erstellen",
    "generate_column_chart_tool": "Column-Chart erstellen",
    "generate_bar_chart_tool": "Bar-Chart erstellen",
    "generate_scatter_chart_tool": "Scatter-Chart erstellen",
    "generate_boxplot_chart_tool": "Boxplot erstellen",
    "generate_violin_chart_tool": "Violin-Chart erstellen",
    "generate_histogram_chart_tool": "Histogramm erstellen",
    "generate_pie_chart_tool": "Pie-Chart erstellen",
    "generate_radar_chart_tool": "Radar-Chart erstellen",
    # Stats Agent Tools
    "mean_tool": "Mittelwert berechnen",
    "std_tool": "Standardabweichung berechnen",
    "min_max_tool": "Min/Max berechnen",
    "correlation_tool": "Korrelation berechnen",
    "trend_tool": "Trend berechnen",
    "percentiles_tool": "Perzentile berechnen",
    "anomaly_tool": "Anomalien erkennen",
    "summary_tool": "Zusammenfassung erstellen",
}


def _build_step_summary(node_name: str, update: dict) -> str:
    """Erstellt eine kurze Zusammenfassung für den Step-Output."""
    if node_name == "supervisor":
        plan = update.get("plan")
        if plan:
            return f"Plan: {' → '.join(plan)}"
        return ""
    if node_name == "data_agent":
        keys = update.get("active_dataset_keys") or []
        return f"{len(keys)} Dataset(s) geladen" if keys else ""
    if node_name == "stats_agent":
        summary = update.get("statistics_summary") or ""
        return summary[:200] if summary else ""
    if node_name == "viz_agent":
        chart = update.get("chart_type") or ""
        return f"Chart: {chart}" if chart else ""
    return ""


def _build_checklist_html(steps: list[dict]) -> str:
    """Baut HTML-Checklist mit Items in 3 States (done/active/pending).

    Active-Item hat pulsierende Animation, Tool-Chain darunter, und Live-Timer.
    """
    if not steps:
        return ""

    items = []
    for step in steps:
        cfg = STATUS_CONFIG.get(step["node"])
        if not cfg:
            continue

        status = step["status"]
        summary = step.get("summary", "")
        tools = step.get("tools", [])

        if status == "done":
            summary_str = f" \u2014 {summary}" if summary else ""
            items.append(
                f'<div class="checklist-item checklist-done">'
                f'<span class="checklist-check">\u2713</span> '
                f'{cfg["icon"]} {cfg["label"]}{summary_str}'
                f'</div>'
            )
        elif status == "active":
            start_ts = step.get("start_ts", 0)
            items.append(
                f'<div class="checklist-item checklist-active" data-start="{start_ts}">'
                f'<span class="checklist-icon">{cfg["icon"]}</span> '
                f'{cfg["label"]}<span class="checklist-dots"></span>'
                f'<span class="checklist-timer"></span>'
                f'</div>'
            )
            # Tool-Chain: erledigte + aktive Sub-Schritte
            for tool in tools:
                tool_label = TOOL_LABELS.get(tool["name"], tool["name"])
                if tool["status"] == "done":
                    items.append(
                        f'<div class="checklist-tool checklist-tool-done">'
                        f'\u2713 {tool_label}</div>'
                    )
                else:
                    items.append(
                        f'<div class="checklist-tool checklist-tool-active">'
                        f'\u2514 {tool_label}</div>'
                    )
        else:  # pending
            items.append(
                f'<div class="checklist-item checklist-pending">'
                f'<span class="checklist-circle">\u25cb</span> '
                f'{cfg["label"]}'
                f'</div>'
            )

    return f'<div class="checklist">{"".join(items)}</div>'


def _build_collapsed_html(steps: list[dict], total_elapsed_s: int = 0) -> str:
    """Baut <details> mit eingeklappter Schritt-Zusammenfassung f\u00fcr die Antwort-Phase."""
    done_steps = [s for s in steps if s["status"] == "done"]
    n = len(done_steps)
    if n == 0:
        return ""

    step_items = []
    for step in done_steps:
        cfg = STATUS_CONFIG.get(step["node"])
        if not cfg:
            continue
        summary = step.get("summary", "")
        summary_str = f" \u2014 {summary}" if summary else ""
        step_items.append(
            f'<div class="collapsed-step">{cfg["icon"]} {cfg["label"]}{summary_str}</div>'
        )

    time_str = f" ({total_elapsed_s}s)" if total_elapsed_s > 0 else ""
    return (
        f'<details class="checklist-collapsed">'
        f'<summary>\u2705 {n} Schritt{"e" if n != 1 else ""} ausgef\u00fchrt{time_str}</summary>'
        f'{"".join(step_items)}'
        f'</details>'
    )


# =============================================================================
# PERSISTENTER SESSION-STATE (überlebt Browser-Refresh)
# =============================================================================

# SessionStore-ID bleibt gleich (DuckDB-Instanz wiederverwenden, nur leeren)
_persistent_session_id: str | None = None
# MCP Warmup nur beim allerersten Start
_mcp_initialized: bool = False


# =============================================================================
# CHAINLIT EVENT HANDLERS
# =============================================================================

@cl.on_chat_start
async def on_chat_start():
    """Wird aufgerufen wenn ein neuer Chat startet."""
    global _persistent_session_id, _mcp_initialized

    # Neuer thread_id pro Chat → sauberer LangGraph-State (keine alten Datasets/Messages)
    thread_id = str(uuid.uuid4())
    cl.user_session.set("thread_id", thread_id)

    # SessionStore: Instanz wiederverwenden, nur Daten leeren
    if _persistent_session_id is None:
        _persistent_session_id = str(uuid.uuid4())
        SessionStore.get_instance(_persistent_session_id)
        logger.info(f"Neue Session: thread={thread_id}, store={_persistent_session_id}")
    else:
        store = SessionStore.get_instance(_persistent_session_id)
        if store._in_use:
            logger.warning(f"Pipeline läuft noch — DuckDB wird NICHT geleert: {_persistent_session_id}")
        else:
            store.clear()
        logger.info(f"Neuer Chat: thread={thread_id}, store={_persistent_session_id} (DuckDB geleert)")

    cl.user_session.set("session_id", _persistent_session_id)

    # Session-State initialisieren
    cl.user_session.set("pending_query", None)
    cl.user_session.set("pending_context", None)
    cl.user_session.set("chat_history", [])

    if not _mcp_initialized:
        # MCP Warmup nur beim allerersten Start
        init_msg = await cl.Message(
            content="⏳ Initialisiere System..."
        ).send()

        try:
            print("🔄 Starte MCP Server Warmup...")
            mcp_tools, antv_tools, stats_tools = await asyncio.gather(
                get_mcp_tools(),         # ThingsBoard MCP Server
                get_antv_tools(),        # AntV Chart MCP Server
                get_stats_tools(),       # Stats Tools (InjectedState, kein MCP)
            )
            print(f"✅ ThingsBoard Tools: {len(mcp_tools)}")
            print(f"✅ AntV Tools: {len(antv_tools)}")
            print(f"✅ Stats Tools: {len(stats_tools)}")

            _mcp_initialized = True
            await init_msg.remove()

        except Exception as e:
            await init_msg.remove()
            await cl.Message(
                content=f"⚠️ System gestartet, aber MCP-Initialisierung fehlgeschlagen: {e}\n\n"
                        "Das System funktioniert trotzdem, der erste Request könnte aber länger dauern."
            ).send()

    # Keine Welcome-Message senden — Chainlit zeigt dann die Starters (set_starters)
    # Willkommenstext wird per CSS unter dem Logo eingefügt (siehe stylesheet.css)


@cl.set_starters
async def set_starters():
    """Klickbare Starter-Buttons für den Welcome-Screen."""
    return [
        cl.Starter(
            label="Drehmomente anzeigen",
            message="Zeig mir die Drehmomente aller Achsen vom 16. Dezember",
            icon="/public/icons/chart.svg",
        ),
        cl.Starter(
            label="Aktuelle Position",
            message="Wie ist die aktuelle Position von Achse 1?",
            icon="/public/icons/position.svg",
        ),
        cl.Starter(
            label="Bahngeschwindigkeit",
            message="Zeig mir den Verlauf der Bahngeschwindigkeit der letzten Stunde",
            icon="/public/icons/trend.svg",
        ),
        cl.Starter(
            label="Statistik berechnen",
            message="Berechne Mittelwert und Standardabweichung der Drehmomente von Achse 1",
            icon="/public/icons/stats.svg",
        ),
    ]


@cl.on_chat_end
async def on_chat_end():
    """
    Wird aufgerufen wenn der Chat beendet wird.

    HINWEIS: SessionStore wird hier NICHT zerstört, da on_chat_end auch bei
    Browser-Refresh feuert, während die Pipeline noch läuft. Die In-Memory
    DuckDB-Instanzen werden beim Prozess-Neustart automatisch aufgeräumt.
    """
    thread_id = cl.user_session.get("thread_id")
    if thread_id:
        logger.info(f"Chat beendet: {thread_id} (SessionStore bleibt aktiv)")


@cl.on_message
async def on_message(message: cl.Message):
    """Wird aufgerufen wenn der User eine Nachricht sendet.

    Perplexity-Style: Eine einzige cl.Message entwickelt sich durch 3 Phasen:
    1. Checklist baut sich auf (msg.update())
    2. Checklist klappt ein (msg.update())
    3. Antwort streamt (msg.stream_token())
    """
    user_query = message.content

    thread_id = cl.user_session.get("thread_id")
    session_id = cl.user_session.get("session_id")

    try:
        # Prüfe ob es eine Follow-up Antwort auf eine gestoppte Pipeline ist
        pending_query = cl.user_session.get("pending_query")
        pending_context = cl.user_session.get("pending_context")

        if pending_query and pending_context:
            combined_query = (
                f"KONTEXT: Der User wollte ursprünglich: '{pending_query}'\n"
                f"Das System hat gefragt: '{pending_context}'\n"
                f"Der User antwortet jetzt: '{user_query}'\n\n"
                f"Bitte führe die ursprüngliche Anfrage aus, unter Berücksichtigung der User-Antwort."
            )
            cl.user_session.set("pending_query", None)
            cl.user_session.set("pending_context", None)
            effective_query = combined_query
        else:
            effective_query = user_query

        # === SINGLE MESSAGE für alles (Perplexity-Style) ===
        msg = cl.Message(content="")
        msg_sent = False

        # Checklist State
        checklist_steps: list[dict] = []   # [{node, status, summary, tools, start_ts}]
        step_lookup: dict[str, int] = {}   # node → index in checklist_steps
        response_streaming = False
        first_step_ts: int = 0             # Timestamp des ersten Steps (für Gesamtzeit)

        current_node = None
        supervisor_count = 0  # PLAN vs EVAL unterscheiden
        chart_url = None
        response_text = ""

        def add_step(node: str, status: str = "active"):
            """Step hinzufügen oder Status aktualisieren."""
            nonlocal first_step_ts
            ts = int(time.time() * 1000)
            if not first_step_ts and status == "active":
                first_step_ts = ts
            if node in step_lookup:
                checklist_steps[step_lookup[node]]["status"] = status
                if status == "active":
                    checklist_steps[step_lookup[node]]["start_ts"] = ts
            else:
                step_lookup[node] = len(checklist_steps)
                checklist_steps.append({
                    "node": node, "status": status, "summary": "",
                    "tools": [], "start_ts": ts if status == "active" else 0,
                })

        def complete_step(node: str, summary: str = ""):
            """Step als erledigt markieren mit optionaler Zusammenfassung."""
            if node in step_lookup:
                step = checklist_steps[step_lookup[node]]
                step["status"] = "done"
                if summary:
                    step["summary"] = summary
                for tool in step.get("tools", []):
                    tool["status"] = "done"

        def add_tool(tool_name: str):
            """Tool zum aktuell aktiven Step hinzufügen (Tool-Chain)."""
            for step in checklist_steps:
                if step["status"] != "active":
                    continue
                # Kein Duplikat wenn letztes Tool identisch und noch aktiv
                if (step["tools"] and step["tools"][-1]["name"] == tool_name
                        and step["tools"][-1]["status"] == "active"):
                    return
                # Vorheriges aktives Tool als erledigt markieren
                for t in step["tools"]:
                    if t["status"] == "active":
                        t["status"] = "done"
                step["tools"].append({"name": tool_name, "status": "active"})
                return

        async def refresh_checklist():
            """Checklist-HTML neu bauen und Message updaten."""
            nonlocal msg_sent
            html = _build_checklist_html(checklist_steps)
            if not html:
                return
            msg.content = html
            if not msg_sent:
                await msg.send()
                msg_sent = True
            else:
                await msg.update()

        # Graph streamen mit Live-Updates
        # DEC-013: thread_id für State-Persistenz, DEC-025: session_id für DuckDB
        async for mode, chunk in stream_query(effective_query, thread_id=thread_id, session_id=session_id):
            if mode == "messages":
                msg_chunk, metadata = chunk
                node = metadata.get("langgraph_node", "")

                # Text-Token extrahieren
                token = ""
                if hasattr(msg_chunk, "content") and isinstance(msg_chunk.content, str):
                    token = msg_chunk.content

                # Tool-Call-Chunks extrahieren
                tool_call_chunks = getattr(msg_chunk, "tool_call_chunks", None) or []

                # Nichts Nützliches → skip
                if not token and not tool_call_chunks:
                    continue

                if node == "respond":
                    # Phase 2→3: Checklist einklappen, dann Antwort streamen
                    if not response_streaming:
                        response_streaming = True
                        # Verbleibende active/pending Steps + Tools als done markieren
                        for step in checklist_steps:
                            if step["status"] in ("active", "pending"):
                                step["status"] = "done"
                            for tool in step.get("tools", []):
                                tool["status"] = "done"
                        # Gesamtzeit berechnen
                        total_elapsed = int((time.time() * 1000 - first_step_ts) / 1000) if first_step_ts else 0
                        collapsed = _build_collapsed_html(checklist_steps, total_elapsed_s=total_elapsed)
                        msg.content = collapsed + "\n\n" if collapsed else ""
                        if not msg_sent:
                            await msg.send()
                            msg_sent = True
                        else:
                            await msg.update()

                    # Finale Antwort Token-für-Token streamen
                    if token and isinstance(msg_chunk, AIMessageChunk):
                        await msg.stream_token(token)
                        response_text += token

                elif node == "supervisor" and supervisor_count > 0:
                    # EVAL-Calls verstecken (zu noisy)
                    pass

                else:
                    # Phase 1: Checklist aufbauen
                    if node != current_node and node in STATUS_CONFIG:
                        if not (node == "supervisor" and supervisor_count > 0):
                            add_step(node, "active")
                            await refresh_checklist()

                    # Tool-Chain: Tools zum aktiven Step hinzufügen
                    for tc in tool_call_chunks:
                        tool_name = tc.get("name")
                        if tool_name and tool_name in TOOL_LABELS:
                            add_tool(tool_name)
                            await refresh_checklist()

                    current_node = node

            elif mode == "updates":
                for node_name, update in chunk.items():
                    if node_name == "supervisor":
                        supervisor_count += 1

                        # Plan extrahieren → pending Steps hinzufügen
                        new_plan = update.get("plan") if isinstance(update, dict) else None
                        if new_plan:
                            for agent in new_plan:
                                if agent in STATUS_CONFIG and agent not in step_lookup:
                                    add_step(agent, "pending")

                        # Ersten Supervisor als done markieren
                        if supervisor_count == 1:
                            summary = ""
                            if isinstance(update, dict):
                                summary = _build_step_summary(node_name, update)
                            complete_step(node_name, summary)

                        await refresh_checklist()

                    # Agent / replan_bridge / error_handler fertig
                    if node_name in _PROGRESS_LABELS or node_name in ("replan_bridge", "error_handler"):
                        summary = ""
                        if isinstance(update, dict):
                            summary = _build_step_summary(node_name, update)
                        complete_step(node_name, summary)
                        await refresh_checklist()

                    # Chart-URL sammeln
                    if isinstance(update, dict) and update.get("chart_url"):
                        chart_url = update["chart_url"]

        # Haupt-Message finalisieren
        if msg_sent:
            await msg.update()

        # Prüfe ob die Pipeline auf User-Input wartet
        if response_text:
            is_waiting_for_input = (
                "möchtest du" in response_text.lower() or
                "was möchtest du tun" in response_text.lower() or
                "bitte wähle" in response_text.lower() or
                ("1." in response_text and "2." in response_text)
            )
            if is_waiting_for_input:
                cl.user_session.set("pending_query", user_query)
                cl.user_session.set("pending_context", response_text[:500])

        # Chart als Bild einbetten (separate Message — Chainlit-Requirement)
        if chart_url:
            try:
                elements = [
                    cl.Image(
                        url=chart_url,
                        name="chart",
                        display="inline",
                    )
                ]
                await cl.Message(
                    content="",
                    elements=elements,
                ).send()
            except Exception:
                pass

        # Chat-History aktualisieren
        history = cl.user_session.get("chat_history", [])
        history.append({"role": "user", "content": user_query})
        history.append({"role": "assistant", "content": response_text})
        cl.user_session.set("chat_history", history[-10:])

    except Exception as e:
        cl.user_session.set("pending_query", None)
        cl.user_session.set("pending_context", None)
        error_msg = f"❌ **Fehler bei der Verarbeitung:**\n\n```\n{str(e)}\n```\n\nBitte versuche es erneut oder formuliere deine Frage anders."
        await cl.Message(content=error_msg).send()


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("Starte mit: chainlit run app.py")
