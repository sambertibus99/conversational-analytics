"""
Integration Tests - Happy Paths.

End-to-End Tests für erfolgreiche Szenarien.
Diese Tests benötigen ThingsBoard-Verbindung.

Referenz: docs/AP9_DEBUGGING_TESTING.md Abschnitt 5.1
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pytest
import asyncio

# Integration Tests brauchen ThingsBoard
pytestmark = [pytest.mark.integration, pytest.mark.slow]


# =============================================================================
# DATA AGENT HAPPY PATH TESTS
# =============================================================================

@pytest.mark.asyncio
class TestDataAgentHappyPath:
    """Happy Path Tests für Data Agent."""
    
    @pytest.fixture(autouse=True)
    async def setup_cleanup(self, cleanup_mcp_after_test):
        """Nutzt die Cleanup-Fixture für jeden Test."""
        pass
    
    async def test_get_latest_telemetry(self):
        """Testet Abruf aktueller Werte."""
        from agents.data_agent import run_data_agent
        from agents.state import AgentState
        from langchain_core.messages import HumanMessage
        
        state = AgentState(
            messages=[HumanMessage(content="Wie ist die aktuelle Position von Achse 1?")]
        )
        
        result = await run_data_agent(state)
        
        # Kein Fehler
        assert result.get("error") is None, f"Fehler: {result.get('error')}"
        
        # Daten oder Summary vorhanden
        has_data = result.get("data") is not None or result.get("datasets")
        assert has_data, "Weder data noch datasets vorhanden"
    
    async def test_list_telemetry_keys(self):
        """Testet Auflistung der Telemetrie-Keys."""
        from agents.data_agent import run_data_agent
        from agents.state import AgentState
        from langchain_core.messages import HumanMessage
        
        state = AgentState(
            messages=[HumanMessage(content="Welche Telemetrie-Keys sind verfügbar?")]
        )
        
        result = await run_data_agent(state)
        
        assert result.get("error") is None
        
        # Sollte eine Liste von Keys zurückgeben
        data = result.get("data")
        if data is not None:
            assert isinstance(data, list) or isinstance(data, dict)
    
    async def test_get_data_availability(self):
        """Testet Abfrage der Daten-Verfügbarkeit."""
        from agents.data_agent import run_data_agent
        from agents.state import AgentState
        from langchain_core.messages import HumanMessage
        
        state = AgentState(
            messages=[HumanMessage(content="Wann gibt es Daten?")]
        )
        
        result = await run_data_agent(state)
        
        assert result.get("error") is None
        
        # Meta sollte Info über Verfügbarkeit enthalten
        meta = result.get("data_meta", {})
        has_info = meta.get("type") in ("data_availability", "no_data", "success") or result.get("datasets")
        assert has_info, f"Keine Zeitraum-Info. Meta: {meta}"


# =============================================================================
# DATA + VIZ PIPELINE TESTS
# =============================================================================

@pytest.mark.asyncio
class TestDataVizPipeline:
    """Tests für Data → Viz Pipeline."""
    
    @pytest.fixture(autouse=True)
    async def setup_cleanup(self, cleanup_mcp_after_test):
        """Nutzt die Cleanup-Fixture für jeden Test."""
        pass
    
    async def test_data_to_viz_with_known_data(self):
        """
        Testet Pipeline mit bekanntem Daten-Zeitraum.
        
        Verwendet Dienstag 16.12.2025 12:00 (bekannter Datenbereich).
        """
        from agents.data_agent import run_data_agent
        from agents.viz_agent import run_viz_agent
        from agents.state import AgentState
        from langchain_core.messages import HumanMessage
        
        # 1. Daten laden
        data_state = AgentState(
            messages=[HumanMessage(content="TCP Position von Dienstag 12 Uhr")]
        )
        
        data_result = await run_data_agent(data_state)
        
        # Prüfe ob Daten vorhanden (könnte no_data sein wenn Roboter nicht lief)
        if data_result.get("data") is None:
            pytest.skip("Keine Daten für Dienstag 12 Uhr verfügbar")
        
        # 2. Visualisieren
        viz_state = AgentState(
            messages=[HumanMessage(content="Zeig als Liniendiagramm")],
            data=data_result.get("data"),
            data_meta=data_result.get("data_meta"),
        )
        
        viz_result = await run_viz_agent(viz_state)
        
        # Chart-URL sollte vorhanden sein
        assert viz_result.get("chart_url") is not None, \
            f"Kein Chart generiert. Error: {viz_result.get('error')}"


# =============================================================================
# FULL GRAPH TESTS
# =============================================================================

@pytest.mark.asyncio
class TestFullGraphHappyPath:
    """Tests für den kompletten Graph."""
    
    @pytest.fixture(autouse=True)
    async def setup_cleanup(self, cleanup_mcp_after_test):
        """Nutzt die Cleanup-Fixture für jeden Test."""
        pass
    
    async def test_simple_data_query(self):
        """Testet einfache Datenabfrage durch Graph."""
        from agents.graph import run_query
        
        result = await run_query("Welche Geräte gibt es?")
        
        assert result.get("response") is not None
        assert result.get("plan") is not None
        assert "data_agent" in result.get("plan", [])
    
    async def test_data_availability_query(self):
        """Testet Daten-Verfügbarkeitsabfrage durch Graph."""
        from agents.graph import run_query
        
        result = await run_query("Wann gibt es Daten?")
        
        assert result.get("response") is not None
        # Response sollte Zeitraum oder Hinweis enthalten
        response = result.get("response", "")
        has_info = any(word in response.lower() for word in 
                      ["dezember", "dienstag", "verfügbar", "keine", "daten"])
        assert has_info, f"Response enthält keine relevante Info: {response}"


# =============================================================================
# STATS AGENT HAPPY PATH TESTS
# =============================================================================

@pytest.mark.asyncio
class TestStatsAgentHappyPath:
    """Happy Path Tests für Stats Agent."""
    
    async def test_stats_with_simulated_data(self):
        """Testet Stats Agent mit simulierten Daten."""
        from agents.stats_agent import run_stats_agent
        from agents.state import AgentState
        from langchain_core.messages import HumanMessage
        from datetime import datetime, timedelta
        
        # Simulierte Daten
        now = datetime.now()
        test_data = {
            "temperature": [
                {"value": str(25.0 + i * 0.1), "timestamp": int((now - timedelta(minutes=50-i)).timestamp() * 1000)}
                for i in range(50)
            ]
        }
        
        state = AgentState(
            messages=[HumanMessage(content="Was ist die Durchschnittstemperatur?")],
            data=test_data,
        )
        
        result = await run_stats_agent(state)
        
        # Sollte Statistiken berechnet haben
        assert result.get("error") is None, f"Fehler: {result.get('error')}"
        
        # Entweder statistics oder statistics_summary sollte vorhanden sein
        has_stats = (result.get("statistics") is not None or 
                    result.get("statistics_summary") is not None)
        assert has_stats, "Keine Statistiken berechnet"


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
