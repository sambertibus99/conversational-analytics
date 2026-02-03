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
import uuid
import chainlit as cl
from chainlit import Message, Image, Text

from agents.graph import run_query
from agents.data_agent import get_mcp_tools
from agents.viz_agent import get_antv_tools
from agents.stats_agent import get_stats_tools


# =============================================================================
# CHAINLIT EVENT HANDLERS
# =============================================================================

@cl.on_chat_start
async def on_chat_start():
    """Wird aufgerufen wenn ein neuer Chat startet."""
    # Eindeutige Thread-ID für diese Chat-Session (DEC-013)
    thread_id = str(uuid.uuid4())
    cl.user_session.set("thread_id", thread_id)
    
    # Session-State initialisieren
    cl.user_session.set("pending_query", None)
    cl.user_session.set("pending_context", None)
    cl.user_session.set("chat_history", [])
    
    # MCP Server im Hintergrund vorwärmen
    init_msg = await cl.Message(
        content="⏳ Initialisiere System..."
    ).send()
    
    try:
        # Alle 3 MCP Server parallel starten
        print("🔄 Starte MCP Server Warmup...")
        mcp_tools, antv_tools, stats_tools = await asyncio.gather(
            get_mcp_tools(),         # ThingsBoard MCP Server
            get_antv_tools(),        # AntV Chart MCP Server
            get_stats_tools(),       # Stats Tools (InjectedState, kein MCP)
        )
        print(f"✅ ThingsBoard Tools: {len(mcp_tools)}")
        print(f"✅ AntV Tools: {len(antv_tools)}")
        print(f"✅ Stats Tools: {len(stats_tools)}")
        
        # Init-Nachricht aktualisieren
        await init_msg.remove()
        
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
        
    except Exception as e:
        await init_msg.remove()
        await cl.Message(
            content=f"⚠️ System gestartet, aber MCP-Initialisierung fehlgeschlagen: {e}\n\n"
                    "Das System funktioniert trotzdem, der erste Request könnte aber länger dauern."
        ).send()


@cl.on_message
async def on_message(message: cl.Message):
    """Wird aufgerufen wenn der User eine Nachricht sendet."""
    user_query = message.content
    
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
    
    # Thinking-Nachricht anzeigen
    thinking_msg = cl.Message(content="⏳ Analysiere deine Anfrage...")
    await thinking_msg.send()
    
    try:
        # Graph ausführen mit thread_id für State-Persistenz (DEC-013)
        thread_id = cl.user_session.get("thread_id")
        result = await run_query(effective_query, thread_id=thread_id)
        
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
