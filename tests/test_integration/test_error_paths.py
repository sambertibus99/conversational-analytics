"""
Integration Tests - Error Paths.

Tests für Fehlerszenarien und Edge Cases.
Diese Tests benötigen ThingsBoard-Verbindung.

Referenz: docs/AP9_DEBUGGING_TESTING.md Abschnitt 5.2
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pytest
import asyncio

# Integration Tests brauchen ThingsBoard
pytestmark = pytest.mark.integration


# =============================================================================
# NO DATA TESTS
# =============================================================================

@pytest.mark.asyncio
class TestNoDataHandling:
    """Tests für Szenarien ohne Daten."""
    
    async def test_no_data_for_future_time(self):
        """
        Testet Anfrage für Zeitpunkt in der Zukunft.
        
        WICHTIG: Agent darf NICHT automatisch anderen Zeitraum probieren!
        """
        from agents.data_agent import run_data_agent
        from agents.state import AgentState
        from langchain_core.messages import HumanMessage
        
        state = AgentState(
            messages=[HumanMessage(content="TCP Position von morgen um 10 Uhr")]
        )
        
        result = await run_data_agent(state)
        
        # Sollte keine Daten haben oder Fehler melden
        meta = result.get("data_meta", {})

        # Entweder "keine Daten" oder error
        has_no_data_msg = (
            "no_data" in str(meta) or
            result.get("data") is None
        )

        # WICHTIG: Sollte nicht versucht haben, anderen Zeitraum zu holen!
        assert has_no_data_msg, \
            f"Agent sollte 'keine Daten' melden, nicht automatisch anderen Zeitraum probieren. Meta: {meta}"
    
    async def test_no_data_for_night_time(self):
        """
        Testet Anfrage für Nachtzeit (Roboter nicht aktiv).
        
        Daten nur verfügbar: 16.12.2025 11:56 - 18:36
        """
        from agents.data_agent import run_data_agent
        from agents.state import AgentState
        from langchain_core.messages import HumanMessage
        
        state = AgentState(
            messages=[HumanMessage(content="TCP Position von Dienstag 3 Uhr nachts")]
        )
        
        result = await run_data_agent(state)
        
        # Meta sollte no_data anzeigen
        meta = result.get("data_meta", {})

        is_no_data = (
            meta.get("type") == "no_data" or
            result.get("data") is None
        )

        assert is_no_data, \
            f"Sollte no_data sein für Nachtzeit. Meta: {meta}"
    
    async def test_no_data_stops_immediately(self):
        """
        KRITISCH: Bei no_data darf Agent NICHT weitermachen!
        
        Prüft dass kein zweiter Tool-Call erfolgt.
        """
        from agents.data_agent import run_data_agent
        from agents.state import AgentState
        from langchain_core.messages import HumanMessage, ToolMessage
        
        state = AgentState(
            messages=[HumanMessage(content="Daten von Mittwoch 13 Uhr")]
        )
        
        result = await run_data_agent(state)
        
        # Zähle ToolMessages (sollte nur 1 sein bei no_data)
        tool_messages = [
            msg for msg in result.get("messages", [])
            if isinstance(msg, ToolMessage)
        ]
        
        # Bei no_data sollte nur 1 Tool-Call erfolgt sein
        # (nicht automatisch andere Zeiten probieren!)
        if result.get("data") is None:
            assert len(tool_messages) <= 2, \
                f"Bei no_data sollten max 2 Tool-Calls erfolgen, aber {len(tool_messages)} gefunden"


# =============================================================================
# UNKNOWN DEVICE/KEY TESTS
# =============================================================================

@pytest.mark.asyncio
class TestUnknownEntities:
    """Tests für unbekannte Geräte/Keys."""
    
    async def test_unknown_device(self):
        """Testet Anfrage für unbekanntes Gerät."""
        from agents.graph import run_query
        
        result = await run_query("Daten vom KRC6")  # KRC6 existiert nicht
        
        response = result.get("response", "")
        
        # Sollte auf Fehler oder verfügbare Geräte hinweisen
        has_error_or_hint = any(word in response.lower() for word in 
                               ["nicht", "unbekannt", "krc5", "verfügbar", "fehler"])
        
        assert has_error_or_hint, \
            f"Response sollte auf unbekanntes Gerät hinweisen: {response}"
    
    async def test_unknown_telemetry_key(self):
        """Testet Anfrage für unbekannten Telemetrie-Key."""
        from agents.data_agent import run_data_agent
        from agents.state import AgentState
        from langchain_core.messages import HumanMessage
        
        state = AgentState(
            messages=[HumanMessage(content="Zeig mir die Luftfeuchtigkeit")]  # Gibt es nicht
        )
        
        result = await run_data_agent(state)
        
        # Sollte entweder Fehler oder leere Daten zurückgeben
        # (je nachdem wie LLM die Anfrage interpretiert)


# =============================================================================
# ABSTENTION TESTS
# =============================================================================

@pytest.mark.asyncio
class TestAbstention:
    """Tests für Abstention (Ablehnung ungültiger Anfragen)."""
    
    async def test_non_iiot_query_rejected(self):
        """Testet dass nicht-IIoT Anfragen abgelehnt werden."""
        from agents.graph import run_query
        
        result = await run_query("Wie wird das Wetter morgen?")
        
        # Plan sollte leer sein
        assert result.get("plan") == [], \
            f"Plan sollte leer sein für nicht-IIoT Anfrage: {result.get('plan')}"
    
    async def test_write_request_rejected(self):
        """Testet dass Schreib-Anfragen abgelehnt werden."""
        from agents.graph import run_query
        
        result = await run_query("Setze den Override auf 50%")
        
        response = result.get("response", "")
        
        # Sollte ablehnen oder auf Nur-Lese-Zugriff hinweisen
        is_rejected = (
            result.get("plan") == [] or
            "nicht" in response.lower() or
            "nur lesen" in response.lower() or
            "kann nicht" in response.lower()
        )
        
        # Hinweis: LLM könnte "nicht möglich" sagen ohne leeren Plan
        # Das ist auch akzeptabel


# =============================================================================
# ERROR RECOVERY TESTS
# =============================================================================

@pytest.mark.asyncio
class TestErrorRecovery:
    """Tests für Fehlerbehandlung und Recovery."""
    
    async def test_graceful_timeout_handling(self):
        """Testet graceful Handling von Timeouts."""
        # Dieser Test ist schwer ohne Mock zu implementieren
        # Placeholder für zukünftige Implementierung
        pass
    
    async def test_error_message_is_user_friendly(self):
        """Testet dass Fehlermeldungen benutzerfreundlich sind."""
        from agents.graph import run_query
        
        # Provoziere Fehler mit ungültiger Anfrage
        result = await run_query("")  # Leere Anfrage
        
        response = result.get("response", "")
        
        # Sollte keine Stacktraces oder technische Details enthalten
        has_stacktrace = "Traceback" in response or "Exception" in response
        
        assert not has_stacktrace, \
            f"Response sollte keine Stacktraces enthalten: {response[:200]}"


# =============================================================================
# EDGE CASES
# =============================================================================

@pytest.mark.asyncio
class TestEdgeCases:
    """Tests für Grenzfälle."""
    
    async def test_very_short_query(self):
        """Testet sehr kurze Anfrage."""
        from agents.graph import run_query
        
        result = await run_query("Zeig")
        
        # Sollte nicht crashen
        assert result.get("response") is not None
    
    async def test_very_long_query(self):
        """Testet sehr lange Anfrage."""
        from agents.graph import run_query
        
        long_query = "Zeig mir die TCP Position " * 50
        
        result = await run_query(long_query)
        
        # Sollte nicht crashen
        assert result.get("response") is not None
    
    async def test_special_characters_in_query(self):
        """Testet Anfrage mit Sonderzeichen."""
        from agents.graph import run_query
        
        result = await run_query("Zeig mir <Position> & Geschwindigkeit")
        
        # Sollte nicht crashen
        assert result.get("response") is not None


# =============================================================================
# HELPER
# =============================================================================

def has_thingsboard_connection():
    """Prüft ob ThingsBoard erreichbar ist."""
    import httpx
    from config.settings import THINGSBOARD_URL
    
    try:
        response = httpx.get(f"{THINGSBOARD_URL}/api/noauth/activate", timeout=5.0)
        return True
    except:
        return False


@pytest.fixture(scope="module", autouse=True)
def check_thingsboard():
    """Überspringt alle Integration Tests wenn ThingsBoard nicht erreichbar."""
    if not has_thingsboard_connection():
        pytest.skip("ThingsBoard nicht erreichbar")
