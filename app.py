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
import uuid
import chainlit as cl
from chainlit import Message, Image, Text

logger = logging.getLogger(__name__)

from agents.graph import run_query
from agents.data_agent import get_mcp_tools
from agents.viz_agent import get_antv_tools
from agents.stats_agent import get_stats_tools
from config.duckdb_store import SessionStore


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

    await cl.Message(
        content="👋 Willkommen beim **IIoT Analytics Assistant**!\n\n"
                "Ich kann dir helfen, Sensordaten vom KRC5 Roboter zu analysieren und zu visualisieren.\n\n"
                "**Beispiel-Fragen:**\n"
                "- *Zeig Drehmomente vom 16. Dezember*\n"
                "- *Wie ist die aktuelle Position von Achse 1?*\n"
                "- *Zeig mir den Verlauf der Bahngeschwindigkeit der letzten Stunde*\n"
                "- *Zeig Maximum statt Durchschnitt*\n\n"
                "Was möchtest du wissen? 🤖"
    ).send()


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
    """Wird aufgerufen wenn der User eine Nachricht sendet."""
    user_query = message.content

    thread_id = cl.user_session.get("thread_id")
    session_id = cl.user_session.get("session_id")

    # Thinking-Nachricht anzeigen
    thinking_msg = cl.Message(content="⏳ Analysiere deine Anfrage...")
    await thinking_msg.send()

    try:
        # Prüfe ob es eine Follow-up Antwort auf eine gestoppte Pipeline ist
        pending_query = cl.user_session.get("pending_query")
        pending_context = cl.user_session.get("pending_context")

        if pending_query and pending_context:
            # Kombiniere die ursprüngliche Anfrage mit der User-Antwort
            combined_query = (
                f"KONTEXT: Der User wollte ursprünglich: '{pending_query}'\n"
                f"Das System hat gefragt: '{pending_context}'\n"
                f"Der User antwortet jetzt: '{user_query}'\n\n"
                f"Bitte führe die ursprüngliche Anfrage aus, unter Berücksichtigung der User-Antwort."
            )
            # Pending-State zurücksetzen
            cl.user_session.set("pending_query", None)
            cl.user_session.set("pending_context", None)

            effective_query = combined_query
        else:
            effective_query = user_query

        # Graph ausführen mit thread_id für State-Persistenz (DEC-013)
        # DEC-025: session_id separat für DuckDB SessionStore
        result = await run_query(effective_query, thread_id=thread_id, session_id=session_id)

        # Thinking-Nachricht entfernen
        await thinking_msg.remove()

        # Prüfe ob die Pipeline gestoppt hat und auf User-Input wartet
        response_text = result.get("response", "")
        is_waiting_for_input = (
            "möchtest du" in response_text.lower() or
            "was möchtest du tun" in response_text.lower() or
            "bitte wähle" in response_text.lower() or
            ("1." in response_text and "2." in response_text)
        )

        if is_waiting_for_input:
            cl.user_session.set("pending_query", user_query)
            cl.user_session.set("pending_context", response_text[:500])

        # Response zusammenbauen
        response_parts = []

        # Hauptantwort
        if result.get("response"):
            response_parts.append(result["response"])

        # Chart anzeigen wenn vorhanden
        if result.get("chart_url"):
            response_parts.append(f"\n\n🖼️ **Chart:** [Öffnen]({result['chart_url']})")

        # Response senden
        final_response = "\n".join(response_parts)
        await cl.Message(content=final_response).send()

        # Chart als Bild einbetten
        if result.get("chart_url"):
            try:
                elements = [
                    cl.Image(
                        url=result["chart_url"],
                        name="chart",
                        display="inline",
                    )
                ]
                await cl.Message(
                    content="📊 Visualisierung:",
                    elements=elements
                ).send()
            except Exception as e:
                pass

        # Chat-History aktualisieren
        history = cl.user_session.get("chat_history", [])
        history.append({"role": "user", "content": user_query})
        history.append({"role": "assistant", "content": response_text})
        cl.user_session.set("chat_history", history[-10:])

    except Exception as e:
        await thinking_msg.remove()

        cl.user_session.set("pending_query", None)
        cl.user_session.set("pending_context", None)
        error_msg = f"❌ **Fehler bei der Verarbeitung:**\n\n```\n{str(e)}\n```\n\nBitte versuche es erneut oder formuliere deine Frage anders."
        await cl.Message(content=error_msg).send()


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("Starte mit: chainlit run app.py")
