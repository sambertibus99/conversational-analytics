"""
Chainlit Frontend für das Conversational Analytics System.

Startet mit: chainlit run app.py

WICHTIG: Speichert Chat-Kontext zwischen Nachrichten für Follow-up Fragen!
"""

import sys
from pathlib import Path

# Projekt-Root zu sys.path hinzufügen
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

import asyncio
import chainlit as cl
from chainlit import Message, Image, Text

from agents.graph import run_query


# =============================================================================
# CHAINLIT EVENT HANDLERS
# =============================================================================

@cl.on_chat_start
async def on_chat_start():
    """Wird aufgerufen wenn ein neuer Chat startet."""
    # Session-State initialisieren
    cl.user_session.set("pending_query", None)
    cl.user_session.set("pending_context", None)
    cl.user_session.set("chat_history", [])
    
    await cl.Message(
        content="👋 Willkommen beim **IIoT Analytics Assistant**!\n\n"
                "Ich kann dir helfen, Sensordaten vom KRC5 Roboter zu analysieren und zu visualisieren.\n\n"
                "**Beispiel-Fragen:**\n"
                "- *Wie ist die aktuelle Position von Achse 1?*\n"
                "- *Zeig mir den Verlauf der Bahngeschwindigkeit der letzten Stunde*\n"
                "- *Was ist der Durchschnitt des Drehmoments von Achse 3?*\n"
                "- *Gibt es Anomalien beim Drehmoment?*\n\n"
                "Was möchtest du wissen? 🤖"
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
        # Graph ausführen
        result = await run_query(effective_query)
        
        # Thinking-Nachricht entfernen
        await thinking_msg.remove()
        
        # Prüfe ob die Pipeline gestoppt hat und auf User-Input wartet
        # (erkennbar an bestimmten Patterns in der Response)
        response_text = result.get("response", "")
        is_waiting_for_input = (
            "möchtest du" in response_text.lower() or
            "was möchtest du tun" in response_text.lower() or
            "bitte wähle" in response_text.lower() or
            ("1." in response_text and "2." in response_text)  # Nummerierte Optionen
        )
        
        if is_waiting_for_input:
            # Speichere den Kontext für die nächste Nachricht
            cl.user_session.set("pending_query", user_query)
            cl.user_session.set("pending_context", response_text[:500])  # Erste 500 Zeichen
        
        # Response zusammenbauen
        response_parts = []
        
        # Plan anzeigen (optional, für Debug)
        if result.get("plan"):
            plan_str = " → ".join(result["plan"])
            response_parts.append(f"📋 *Plan: {plan_str}*\n")
        
        # Hauptantwort
        if result.get("response"):
            response_parts.append(result["response"])
        
        # Chart anzeigen wenn vorhanden
        if result.get("chart_url"):
            response_parts.append(f"\n\n🖼️ **Chart:** [Öffnen]({result['chart_url']})")
        
        # Response senden
        final_response = "\n".join(response_parts)
        await cl.Message(content=final_response).send()
        
        # Chart als Bild einbetten (wenn URL vorhanden)
        if result.get("chart_url"):
            try:
                # Chainlit kann URLs als Bilder anzeigen
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
                # Falls Bild-Embedding fehlschlägt, nur Link zeigen
                pass
        
        # Chat-History aktualisieren
        history = cl.user_session.get("chat_history", [])
        history.append({"role": "user", "content": user_query})
        history.append({"role": "assistant", "content": response_text})
        cl.user_session.set("chat_history", history[-10:])  # Letzte 10 behalten
        
    except Exception as e:
        # Thinking-Nachricht entfernen
        await thinking_msg.remove()
        
        # Pending-State zurücksetzen bei Fehler
        cl.user_session.set("pending_query", None)
        cl.user_session.set("pending_context", None)
        
        # Fehlermeldung
        error_msg = f"❌ **Fehler bei der Verarbeitung:**\n\n```\n{str(e)}\n```\n\nBitte versuche es erneut oder formuliere deine Frage anders."
        await cl.Message(content=error_msg).send()


# =============================================================================
# OPTIONAL: Actions für häufige Anfragen
# =============================================================================

@cl.action_callback("quick_status")
async def quick_status(action: cl.Action):
    """Quick Action: Aktueller Roboter-Status."""
    await on_message(cl.Message(content="Wie ist die aktuelle Position aller Achsen?"))


@cl.action_callback("quick_chart")
async def quick_chart(action: cl.Action):
    """Quick Action: Schnelles Chart."""
    await on_message(cl.Message(content="Zeig mir den Verlauf der Achsposition 1 der letzten 10 Minuten als Liniendiagramm"))


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    # Für lokales Testing ohne chainlit run
    print("Starte mit: chainlit run app.py")
    print("Oder: chainlit run app.py --port 8000")
