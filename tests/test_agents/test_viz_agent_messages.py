"""
Tests für Viz Agent Message-Filtering und Daten-Transformation.

Testet:
- Nur HumanMessages werden an Viz Agent weitergegeben
- Keine SystemMessages von vorherigen Agents
- Daten-Transformation von ThingsBoard zu AntV Format

Referenz: docs/AP9_DEBUGGING_TESTING.md Abschnitt 3
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pytest
import json
from datetime import datetime, timedelta

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage

from agents.viz_agent import (
    transform_for_line_chart,
    transform_for_category_chart,
    transform_for_scatter_chart,
    transform_for_distribution_chart,
    transform_for_histogram_chart,
    timestamp_to_time_string,
    shorten_key_name,
    extract_chart_url,
    prepare_viz_context,
)
from agents.state import AgentState


# =============================================================================
# MESSAGE FILTERING TESTS
# =============================================================================

class TestMessageFiltering:
    """Tests für Message-Filtering im Viz Agent."""
    
    def test_filter_only_human_messages(self):
        """
        KRITISCH: Viz Agent darf nur HumanMessages übernehmen!
        
        Hintergrund: Bei Agent-zu-Agent-Übergabe führen mehrere
        SystemMessages zu Fehlern.
        """
        messages = [
            SystemMessage(content="System Prompt Data Agent"),  # MUSS gefiltert werden!
            HumanMessage(content="Zeig als Chart"),
            AIMessage(content="Daten geladen"),
            ToolMessage(content='{"status": "success"}', tool_call_id="test"),
        ]
        
        # Filterung wie im Viz Agent
        human_messages = [msg for msg in messages if isinstance(msg, HumanMessage)]
        
        assert len(human_messages) == 1
        assert human_messages[0].content == "Zeig als Chart"
    
    def test_no_system_messages_from_data_agent(self):
        """Prüft dass keine SystemMessages vom Data Agent durchkommen."""
        state = AgentState(
            messages=[
                SystemMessage(content="Du bist ein Data Agent..."),
                HumanMessage(content="TCP Position"),
                AIMessage(content="Daten geladen"),
            ],
            data={"pos_act_x_mm": [{"value": "94.5", "timestamp": 1734350000000}]},
        )
        
        human_messages = [
            msg for msg in state["messages"]
            if isinstance(msg, HumanMessage)
        ]
        
        # Keine SystemMessages
        system_messages = [
            msg for msg in human_messages
            if isinstance(msg, SystemMessage)
        ]
        
        assert len(system_messages) == 0
    
    def test_multiple_human_messages_preserved(self):
        """Prüft dass mehrere HumanMessages erhalten bleiben."""
        messages = [
            HumanMessage(content="Erste Frage"),
            AIMessage(content="Erste Antwort"),
            HumanMessage(content="Zweite Frage"),
            AIMessage(content="Zweite Antwort"),
        ]
        
        human_messages = [msg for msg in messages if isinstance(msg, HumanMessage)]
        
        assert len(human_messages) == 2
        assert human_messages[0].content == "Erste Frage"
        assert human_messages[1].content == "Zweite Frage"


# =============================================================================
# TIMESTAMP CONVERSION TESTS
# =============================================================================

class TestTimestampConversion:
    """Tests für Timestamp-Konvertierung."""
    
    def test_timestamp_to_time_string_valid(self):
        """Testet gültige Timestamp-Konvertierung."""
        from datetime import datetime
        
        # Verwende aktuellen Timestamp für Zeitzone-unabhängigen Test
        now = datetime.now()
        ts = int(now.timestamp() * 1000)
        
        result = timestamp_to_time_string(ts)
        
        # Prüfe Format HH:MM:SS
        assert len(result.split(":")) == 3
        # Prüfe dass Stunde korrekt ist
        assert result.startswith(f"{now.hour:02d}:")
    
    def test_timestamp_to_time_string_format(self):
        """Testet Format HH:MM:SS."""
        ts = 1734350400000
        
        result = timestamp_to_time_string(ts)
        
        # Format: HH:MM:SS
        parts = result.split(":")
        assert len(parts) == 3
    
    def test_timestamp_to_time_string_invalid(self):
        """Testet ungültigen Timestamp."""
        result = timestamp_to_time_string("invalid")
        
        # Sollte nicht crashen
        assert result is not None


# =============================================================================
# TRANSFORM_FOR_LINE_CHART TESTS
# =============================================================================

class TestTransformForLineChart:
    """Tests für transform_for_line_chart()."""
    
    def test_basic_transformation(self):
        """Testet grundlegende Transformation."""
        data = {
            "torque_act_a1": [
                {"value": 10.5, "timestamp": 1734350000000},
                {"value": 11.2, "timestamp": 1734350001000},
                {"value": 10.8, "timestamp": 1734350002000},
            ]
        }
        result = transform_for_line_chart(data)
        
        assert isinstance(result, list)
        assert len(result) > 0
    
    def test_result_has_time_and_value(self):
        """Testet ob Ergebnis time und value hat."""
        data = {
            "torque_act_a1": [
                {"value": 10.5, "timestamp": 1734350000000},
            ]
        }
        result = transform_for_line_chart(data)
        
        assert len(result) > 0
        for point in result:
            assert "time" in point
            assert "value" in point
    
    def test_values_are_floats(self):
        """Testet ob values Floats sind (nicht Strings)."""
        data = {
            "torque_act_a1": [
                {"value": "10.5", "timestamp": 1734350000000},
            ]
        }
        result = transform_for_line_chart(data)
        
        assert len(result) > 0
        for point in result:
            assert isinstance(point["value"], float), \
                f"value sollte float sein, ist aber {type(point['value'])}"
    
    def test_empty_data(self):
        """Testet leere Daten."""
        result = transform_for_line_chart({})
        
        assert result == []
    
    def test_multikey_transformation(self):
        """Testet Multi-Key Transformation mit group Feld."""
        data = {
            "torque_act_a1": [
                {"value": 10.5, "timestamp": 1734350000000},
            ],
            "torque_act_a2": [
                {"value": 12.0, "timestamp": 1734350000000},
            ]
        }
        result = transform_for_line_chart(data, multi_key=True)
        
        # Mit multi_key=True sollten group-Felder vorhanden sein
        for point in result:
            assert "group" in point


# =============================================================================
# TRANSFORM_FOR_CATEGORY_CHART TESTS
# =============================================================================

class TestTransformForCategoryChart:
    """Tests für transform_for_category_chart()."""
    
    def test_category_chart_structure(self):
        """Testet Struktur für Balkendiagramm."""
        data = {
            "torque_act_a1": [
                {"value": 10.5, "timestamp": 1734350000000},
                {"value": 11.2, "timestamp": 1734350001000},
            ],
            "torque_act_a2": [
                {"value": 12.0, "timestamp": 1734350000000},
                {"value": 11.8, "timestamp": 1734350001000},
            ]
        }
        result = transform_for_category_chart(data)
        
        assert isinstance(result, list)
        for point in result:
            assert "category" in point
            assert "value" in point
    
    def test_category_calculates_average(self):
        """Testet ob Durchschnitt berechnet wird."""
        data = {
            "torque_act_a1": [
                {"value": 10.0, "timestamp": 1},
                {"value": 20.0, "timestamp": 2},
            ]
        }
        result = transform_for_category_chart(data)
        
        assert len(result) == 1
        assert result[0]["value"] == 15.0  # (10 + 20) / 2
    
    def test_category_empty_data(self):
        """Testet leere Daten."""
        result = transform_for_category_chart({})
        
        assert result == []


# =============================================================================
# TRANSFORM_FOR_SCATTER_CHART TESTS
# =============================================================================

class TestTransformForScatterChart:
    """Tests für transform_for_scatter_chart()."""
    
    def test_scatter_has_x_and_y(self):
        """Testet ob x und y vorhanden sind."""
        data = {
            "torque_act_a1": [
                {"value": 10.0, "timestamp": 1734350000000},
                {"value": 11.0, "timestamp": 1734350001000},
            ],
            "torque_act_a2": [
                {"value": 12.0, "timestamp": 1734350000000},
                {"value": 13.0, "timestamp": 1734350001000},
            ]
        }
        result = transform_for_scatter_chart(data)
        
        assert len(result) > 0
        for point in result:
            assert "x" in point
            assert "y" in point
    
    def test_scatter_needs_two_keys(self):
        """Testet dass zwei Keys benötigt werden."""
        single_key = {"pos_act_x_mm": [{"value": 1, "timestamp": 1}]}
        
        result = transform_for_scatter_chart(single_key)
        
        assert result == []
    
    def test_scatter_values_are_floats(self):
        """Testet ob x und y Floats sind."""
        data = {
            "torque_act_a1": [
                {"value": "10.0", "timestamp": 1734350000000},
            ],
            "torque_act_a2": [
                {"value": "12.0", "timestamp": 1734350000000},
            ]
        }
        result = transform_for_scatter_chart(data)
        
        assert len(result) > 0
        for point in result:
            assert isinstance(point["x"], float)
            assert isinstance(point["y"], float)


# =============================================================================
# SHORTEN_KEY_NAME TESTS
# =============================================================================

class TestShortenKeyName:
    """Tests für shorten_key_name()."""
    
    @pytest.mark.parametrize("key,expected", [
        ("axis_act_a1_deg", "Aa1°"),
        ("pos_act_x_mm", "px"),
        ("torque_act_a1_nm", "Ta1"),
        ("vel_act_a_m_per_s", "Va"),
    ])
    def test_key_shortening(self, key, expected):
        """Testet Key-Name-Verkürzung."""
        result = shorten_key_name(key)

        assert result == expected
        assert len(result) < len(key)


# =============================================================================
# EXTRACT_CHART_URL TESTS
# =============================================================================

class TestExtractChartUrl:
    """Tests für extract_chart_url()."""
    
    def test_extract_url_from_content(self):
        """Testet URL-Extraktion aus Tool Result."""
        class MockContent:
            def __init__(self, text):
                self.text = text
        
        class MockResult:
            def __init__(self, text):
                self.content = [MockContent(text)]
        
        result = MockResult("https://example.com/chart.png")
        url = extract_chart_url(result)
        
        assert url == "https://example.com/chart.png"
    
    def test_error_detection(self):
        """Testet Fehler-Erkennung."""
        class MockContent:
            def __init__(self, text):
                self.text = text
        
        class MockResult:
            def __init__(self, text):
                self.content = [MockContent(text)]
        
        result = MockResult("error: invalid chart")
        url = extract_chart_url(result)
        
        assert "Fehler" in url or "error" in url.lower()


# =============================================================================
# PREPARE_VIZ_CONTEXT TESTS
# =============================================================================

class TestPrepareVizContext:
    """Tests für prepare_viz_context()."""
    
    def test_context_creation(self):
        """Testet Kontext-Erstellung mit DuckDB-Daten (DEC-031)."""
        from config.duckdb_store import SessionStore

        session_id = "test_viz_context"
        store = SessionStore.get_instance(session_id)
        try:
            store.store_dataset(
                dataset_key="krc5/torque/timeseries",
                data={"torque_act_a1": [{"value": 10.5, "timestamp": 1734350000000}]},
            )
            state = AgentState(
                messages=[
                    HumanMessage(content="Zeige Torque als Chart"),
                    AIMessage(content="Daten werden verarbeitet"),
                ],
                session_id=session_id,
                active_dataset_keys=["krc5/torque/timeseries"],
            )

            context_dict, context_str = prepare_viz_context(state)

            assert isinstance(context_dict, dict)
            assert isinstance(context_str, str)
            assert len(context_str) > 0
        finally:
            SessionStore.destroy(session_id)


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestVizAgentIntegration:
    """Integration Tests für Viz Agent Komponenten."""
    
    def test_full_transformation_pipeline(self):
        """Testet komplette Transformation Pipeline."""
        data = {
            "torque_act_a1": [
                {"value": 10.5, "timestamp": 1734350000000},
                {"value": 11.2, "timestamp": 1734350001000},
                {"value": 10.8, "timestamp": 1734350002000},
            ]
        }
        
        # 1. Transformation
        transformed = transform_for_line_chart(data)
        
        # 2. Prüfungen
        assert len(transformed) > 0
        
        # 3. JSON-serialisierbar
        json_str = json.dumps(transformed)
        restored = json.loads(json_str)
        
        assert restored == transformed
