"""
Pytest Fixtures für Conversational Analytics Tests.

Stellt Mocks, Fixtures und Hilfsfunktionen bereit.
Ermöglicht Tests ohne echte ThingsBoard-Verbindung.

Daten-Kontext:
- Letzte verfügbare Daten: Dienstag, 16.12.2025, 11:56 - 18:36 Uhr
- Device: KRC5
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import json
import asyncio

import pytest

# Projektroot zum Pfad hinzufügen
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# =============================================================================
# MCP SESSION CLEANUP (für Integration Tests)
# =============================================================================

@pytest.fixture(scope="session")
def event_loop():
    """
    Session-scoped event loop für alle async Tests.
    
    Best Practice: Ein Event Loop für alle Tests vermeidet
    Probleme mit MCP Session Cleanup zwischen Tests.
    """
    import asyncio
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="function")
async def cleanup_mcp_after_test():
    """
    Cleanup MCP Session nach jedem Integration Test.
    
    Best Practice aus FastMCP Docs:
    - Session nach jedem Test aufräumen
    - Globale Variablen zurücksetzen
    - Delay um Rate Limits zu vermeiden
    """
    yield
    # Cleanup nach dem Test
    try:
        from agents.data_agent import cleanup_mcp, _mcp_tools, _mcp_exit_stack
        import agents.data_agent as da
        
        # Globale Session schließen
        if da._mcp_exit_stack is not None:
            try:
                await da._mcp_exit_stack.aclose()
            except Exception:
                pass
        
        # Globale Variablen zurücksetzen
        da._mcp_tools = None
        da._mcp_exit_stack = None
        
        # Rate Limit Best Practice: 2 Sekunden Pause zwischen Tests
        # um 30k tokens/minute Limit nicht zu überschreiten
        await asyncio.sleep(2)
    except Exception:
        pass


# =============================================================================
# PYTEST MARKERS
# =============================================================================

def pytest_configure(config):
    """Registriert custom markers."""
    config.addinivalue_line(
        "markers", "integration: Tests die ThingsBoard-Verbindung brauchen"
    )
    config.addinivalue_line(
        "markers", "slow: Langsame Tests (LLM-Aufrufe)"
    )


# =============================================================================
# ZEITKONSTANTEN
# =============================================================================

# Referenz-Datum: Dienstag, 16.12.2025 (letzte verfügbare Daten)
REFERENCE_DATE = datetime(2025, 12, 16, 12, 0, 0)
DATA_START = datetime(2025, 12, 16, 11, 56, 0)
DATA_END = datetime(2025, 12, 16, 18, 36, 0)


@pytest.fixture
def reference_date():
    """Referenz-Datum für Zeitraum-Tests."""
    return REFERENCE_DATE


@pytest.fixture
def data_availability_range():
    """Zeitraum in dem Daten verfügbar sind."""
    return {
        "start": DATA_START,
        "end": DATA_END,
        "start_ts": int(DATA_START.timestamp() * 1000),
        "end_ts": int(DATA_END.timestamp() * 1000),
    }


# =============================================================================
# MCP RESPONSE FIXTURES
# =============================================================================

@pytest.fixture
def success_response():
    """Erfolgreiche get_telemetry Response."""
    return {
        "status": "success",
        "timerange": {
            "start": "16.12.2025 12:00",
            "end": "16.12.2025 12:10",
            "weekday": "Dienstag",
        },
        "data_points": {"pos_act_x_mm": 627},
        "statistics": {
            "pos_act_x_mm": {
                "count": 627,
                "min": 94.123,
                "max": 95.456,
                "avg": 94.789,
                "first": 94.5,
                "last": 94.8,
            }
        },
        "data_file": "/tmp/telemetry_test.json",
    }


@pytest.fixture
def no_data_response():
    """Response wenn keine Daten gefunden wurden."""
    return {
        "status": "no_data",
        "message": "Keine Daten für den Zeitraum Mittwoch, 17.12.2025 13:00 bis 13:10 gefunden.",
        "requested_timerange": {
            "start": "17.12.2025 13:00",
            "end": "17.12.2025 13:10",
            "weekday": "Mittwoch",
        },
        "hint": "Nutze get_data_availability um zu prüfen, wann Daten verfügbar sind.",
        "action": "Informiere den Nutzer, dass keine Daten für diesen Zeitraum existieren.",
    }


@pytest.fixture
def data_available_response():
    """Response von get_data_availability."""
    return {
        "status": "data_available",
        "device": "KRC5",
        "key_checked": "pos_act_x_mm",
        "data_range": {
            "first_data": "2025-12-16",
            "first_time": "11:56",
            "first_weekday": "Dienstag",
            "last_data": "2025-12-16",
            "last_time": "18:36",
            "last_weekday": "Dienstag",
        },
        "total_points": 24000,
        "message": "Daten verfügbar von 16.12.2025 11:56 bis 16.12.2025 18:36",
    }


@pytest.fixture
def latest_telemetry_response():
    """Response von get_latest_telemetry."""
    return {
        "axis_act_a1_deg": {
            "value": "25.34",
            "timestamp": 1734364596000,
            "timestamp_human": "16.12.2025 18:36:36",
            "weekday": "Dienstag",
        },
        "vel_act_m_per_s": {
            "value": "0.0",
            "timestamp": 1734364596000,
            "timestamp_human": "16.12.2025 18:36:36",
            "weekday": "Dienstag",
        },
    }


@pytest.fixture
def telemetry_keys_response():
    """Response von list_telemetry_keys."""
    return [
        "axis_act_a1_deg", "axis_act_a2_deg", "axis_act_a3_deg",
        "axis_act_a4_deg", "axis_act_a5_deg", "axis_act_a6_deg",
        "pos_act_x_mm", "pos_act_y_mm", "pos_act_z_mm",
        "vel_act_m_per_s", "torque_act_a1_nm",
    ]


@pytest.fixture
def error_response():
    """Fehler-Response."""
    return {
        "status": "error",
        "error_type": "not_found",
        "message": "Device 'KRC6' nicht gefunden. Verfügbare Devices: KRC5",
    }


# =============================================================================
# TELEMETRIE-DATEN FIXTURES
# =============================================================================

@pytest.fixture
def sample_timeseries_data():
    """Beispiel-Zeitreihendaten im ThingsBoard-Format."""
    base_ts = int(REFERENCE_DATE.timestamp() * 1000)
    
    return {
        "pos_act_x_mm": [
            {"value": str(94.5 + i * 0.01), "timestamp": base_ts + i * 1000}
            for i in range(100)
        ],
        "pos_act_y_mm": [
            {"value": str(105.2 + i * 0.02), "timestamp": base_ts + i * 1000}
            for i in range(100)
        ],
    }


@pytest.fixture
def sample_timeseries_single_key():
    """Zeitreihe mit nur einem Key."""
    base_ts = int(REFERENCE_DATE.timestamp() * 1000)
    
    return {
        "axis_act_a1_deg": [
            {"value": str(25.0 + i * 0.1), "timestamp": base_ts + i * 1000}
            for i in range(50)
        ]
    }


@pytest.fixture
def sample_data_with_anomalies():
    """Zeitreihe mit Ausreißern für Anomalie-Tests."""
    base_ts = int(REFERENCE_DATE.timestamp() * 1000)
    values = [25.0 + i * 0.1 for i in range(50)]
    
    # Ausreißer einfügen
    values[10] = 50.0  # Spike
    values[30] = 5.0   # Dip
    
    return {
        "temperature": [
            {"value": str(v), "timestamp": base_ts + i * 1000}
            for i, v in enumerate(values)
        ]
    }


@pytest.fixture
def large_dataset():
    """Großer Datensatz für Token-Budget-Tests."""
    base_ts = int(REFERENCE_DATE.timestamp() * 1000)
    
    return {
        "pos_act_x_mm": [
            {"value": str(94.5 + (i % 100) * 0.01), "timestamp": base_ts + i * 100}
            for i in range(10000)  # 10k Punkte
        ]
    }


# =============================================================================
# AGENT STATE FIXTURES
# =============================================================================

@pytest.fixture
def empty_state():
    """Leerer AgentState."""
    from agents.state import AgentState
    from langchain_core.messages import HumanMessage
    
    return AgentState(
        messages=[HumanMessage(content="Test query")],
    )


@pytest.fixture
def state_with_data(sample_timeseries_data):
    """AgentState mit geladenen Daten."""
    from agents.state import AgentState
    from langchain_core.messages import HumanMessage
    
    return AgentState(
        messages=[HumanMessage(content="Zeig mir die TCP Position")],
        data=sample_timeseries_data,
        data_meta={
            "type": "success",
            "data_points": {"pos_act_x_mm": 100, "pos_act_y_mm": 100},
        },
    )


@pytest.fixture
def state_with_plan():
    """AgentState mit Plan vom Supervisor."""
    from agents.state import AgentState
    from langchain_core.messages import HumanMessage
    
    return AgentState(
        messages=[HumanMessage(content="Zeig die Temperatur als Chart")],
        plan=["data_agent", "viz_agent"],
        current_step=0,
    )


@pytest.fixture
def state_after_data_agent(sample_timeseries_data):
    """AgentState nachdem Data Agent gelaufen ist."""
    from agents.state import AgentState
    from langchain_core.messages import HumanMessage, AIMessage
    
    return AgentState(
        messages=[
            HumanMessage(content="TCP Position der letzten 10 Minuten"),
            AIMessage(content="Daten erfolgreich geladen."),
        ],
        plan=["data_agent", "viz_agent"],
        current_step=1,
        data=sample_timeseries_data,
        data_meta={"type": "success", "data_points": {"pos_act_x_mm": 100}},
    )


# =============================================================================
# MOCK FIXTURES
# =============================================================================

@pytest.fixture
def mock_thingsboard_client():
    """Mock für ThingsBoardClient."""
    mock = AsyncMock()
    mock.list_devices.return_value = [
        {"id": "test-id", "name": "KRC5", "type": "KUKA", "label": "Roboter 1"}
    ]
    mock.get_telemetry_keys.return_value = [
        "axis_act_a1_deg", "pos_act_x_mm", "vel_act_m_per_s"
    ]
    mock.get_latest_telemetry.return_value = {
        "axis_act_a1_deg": {"value": "25.34", "timestamp": 1734364596000}
    }
    mock.get_telemetry.return_value = {}
    return mock


@pytest.fixture
def mock_llm_response():
    """Mock für LLM-Responses."""
    mock = MagicMock()
    mock.content = '{"plan": ["data_agent"], "reasoning": "Test"}'
    return mock


@pytest.fixture
def mock_mcp_tools():
    """Mock für MCP Tools."""
    tools = []
    
    for name in ["get_telemetry", "get_latest_telemetry", "list_telemetry_keys", 
                 "get_data_availability", "list_devices"]:
        tool = MagicMock()
        tool.name = name
        tool.description = f"Mock tool: {name}"
        tools.append(tool)
    
    return tools


# =============================================================================
# HILFSFUNKTIONEN
# =============================================================================

@pytest.fixture
def create_tool_message():
    """Factory für ToolMessage-Erstellung."""
    from langchain_core.messages import ToolMessage
    
    def _create(content: dict | list | str, name: str = "test_tool"):
        if isinstance(content, (dict, list)):
            content = json.dumps(content)
        return ToolMessage(content=content, tool_call_id=f"{name}_call_1", name=name)
    
    return _create


@pytest.fixture
def create_messages_with_system():
    """Factory für Message-Listen mit SystemMessage."""
    from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
    
    def _create(user_content: str, system_content: str = "System prompt"):
        return [
            SystemMessage(content=system_content),
            HumanMessage(content=user_content),
        ]
    
    return _create


# =============================================================================
# FILE FIXTURES
# =============================================================================

@pytest.fixture
def temp_data_file(tmp_path, sample_timeseries_data):
    """Temporäre Datendatei für File-Loading-Tests."""
    file_path = tmp_path / "telemetry_test.json"
    
    data = {
        "timerange": {
            "start_ts": int(REFERENCE_DATE.timestamp() * 1000),
            "end_ts": int((REFERENCE_DATE + timedelta(minutes=10)).timestamp() * 1000),
            "start_human": "16.12.2025 12:00",
            "end_human": "16.12.2025 12:10",
            "weekday": "Dienstag",
        },
        "keys": list(sample_timeseries_data.keys()),
        "data": sample_timeseries_data,
    }
    
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    
    return file_path


# =============================================================================
# SUPERVISOR FIXTURES
# =============================================================================

@pytest.fixture
def supervisor_test_cases():
    """Test-Cases für Supervisor-Planung."""
    return [
        # (Query, Erwarteter Plan)
        ("Zeig mir die Temperatur", ["data_agent", "viz_agent"]),
        ("Wie ist die aktuelle Position von Achse 1?", ["data_agent"]),
        ("Was ist die Durchschnittstemperatur?", ["data_agent", "stats_agent"]),
        ("Korrelation als Chart", ["data_agent", "stats_agent", "viz_agent"]),
        ("Liste alle Geräte auf", ["data_agent"]),
        ("Wie wird das Wetter morgen?", []),
        ("Wann gibt es Daten?", ["data_agent"]),
        ("TCP Position Dienstag 12 Uhr als Liniendiagramm", ["data_agent", "viz_agent"]),
    ]


@pytest.fixture
def supervisor_edge_cases():
    """Edge Cases für Supervisor."""
    return [
        ("", []),  # Leer
        ("asdfghjkl", []),  # Gibberish
        ("Zeig", ["data_agent", "viz_agent"]),  # Unvollständig aber interpretierbar
        ("   ", []),  # Nur Whitespace
    ]


# =============================================================================
# TIMERANGE FIXTURES
# =============================================================================

@pytest.fixture
def timerange_test_cases():
    """Test-Cases für Zeitraum-Parsing."""
    # Format: (Input, Erwarteter Wochentag im Result)
    return [
        ("Dienstag 12 Uhr", "Dienstag"),
        ("Dienstag um 13:30", "Dienstag"),
        ("letzten Montag", "Montag"),
        ("gestern um 14 Uhr", None),  # Hängt vom aktuellen Tag ab
        ("letzte Stunde", None),
        ("letzte 30 Minuten", None),
        ("heute", None),
        ("letzte 24 Stunden", None),
    ]


# =============================================================================
# PYTEST HOOKS
# =============================================================================

def pytest_collection_modifyitems(config, items):
    """Automatisch 'slow' Marker für Integration-Tests."""
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(pytest.mark.slow)
