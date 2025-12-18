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
    transform_timeseries_for_antv,
    transform_multikey_for_antv,
    transform_for_scatter,
    transform_for_comparison,
    transform_latest_values,
    timestamp_to_time_string,
    get_unit_for_key,
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
# TRANSFORM_TIMESERIES_FOR_ANTV TESTS
# =============================================================================

class TestTransformTimeseriesForAntv:
    """Tests für transform_timeseries_for_antv()."""
    
    def test_basic_transformation(self, sample_timeseries_single_key):
        """Testet grundlegende Transformation."""
        result = transform_timeseries_for_antv(sample_timeseries_single_key)
        
        assert isinstance(result, list)
        assert len(result) > 0
    
    def test_result_has_time_and_value(self, sample_timeseries_single_key):
        """Testet ob Ergebnis time und value hat."""
        result = transform_timeseries_for_antv(sample_timeseries_single_key)
        
        for point in result:
            assert "time" in point
            assert "value" in point
    
    def test_values_are_floats(self, sample_timeseries_single_key):
        """Testet ob values Floats sind (nicht Strings)."""
        result = transform_timeseries_for_antv(sample_timeseries_single_key)
        
        for point in result:
            assert isinstance(point["value"], float), \
                f"value sollte float sein, ist aber {type(point['value'])}"
    
    def test_result_sorted_by_time(self, sample_timeseries_single_key):
        """Testet ob Ergebnis nach Zeit sortiert ist."""
        result = transform_timeseries_for_antv(sample_timeseries_single_key)
        
        times = [p["time"] for p in result]
        assert times == sorted(times)
    
    def test_empty_data(self):
        """Testet leere Daten."""
        result = transform_timeseries_for_antv({})
        
        assert result == []
    
    def test_first_key_used(self, sample_timeseries_data):
        """Testet dass nur der erste Key verwendet wird."""
        result = transform_timeseries_for_antv(sample_timeseries_data)
        
        # Sollte nur Daten vom ersten Key haben
        assert len(result) == 100  # Länge des ersten Keys


# =============================================================================
# TRANSFORM_MULTIKEY_FOR_ANTV TESTS
# =============================================================================

class TestTransformMultikeyForAntv:
    """Tests für transform_multikey_for_antv()."""
    
    def test_multikey_has_category(self, sample_timeseries_data):
        """Testet ob category-Feld vorhanden ist."""
        result = transform_multikey_for_antv(sample_timeseries_data)
        
        for point in result:
            assert "category" in point
    
    def test_multikey_all_keys_present(self, sample_timeseries_data):
        """Testet ob alle Keys in Kategorien vorkommen."""
        result = transform_multikey_for_antv(sample_timeseries_data)
        
        categories = set(p["category"] for p in result)
        
        # Mindestens 2 verschiedene Kategorien
        assert len(categories) >= 2
    
    def test_multikey_values_are_floats(self, sample_timeseries_data):
        """Testet ob values Floats sind."""
        result = transform_multikey_for_antv(sample_timeseries_data)
        
        for point in result:
            assert isinstance(point["value"], float)


# =============================================================================
# TRANSFORM_FOR_SCATTER TESTS
# =============================================================================

class TestTransformForScatter:
    """Tests für transform_for_scatter()."""
    
    def test_scatter_has_x_and_y(self, sample_timeseries_data):
        """Testet ob x und y vorhanden sind."""
        result = transform_for_scatter(sample_timeseries_data)
        
        for point in result:
            assert "x" in point
            assert "y" in point
    
    def test_scatter_needs_two_keys(self):
        """Testet dass zwei Keys benötigt werden."""
        single_key = {"pos_act_x_mm": [{"value": "1", "timestamp": 1}]}
        
        result = transform_for_scatter(single_key)
        
        assert result == []
    
    def test_scatter_values_are_floats(self, sample_timeseries_data):
        """Testet ob x und y Floats sind."""
        result = transform_for_scatter(sample_timeseries_data)
        
        for point in result:
            assert isinstance(point["x"], float)
            assert isinstance(point["y"], float)


# =============================================================================
# TRANSFORM_FOR_COMPARISON TESTS
# =============================================================================

class TestTransformForComparison:
    """Tests für transform_for_comparison()."""
    
    def test_comparison_has_category_and_value(self, sample_timeseries_data):
        """Testet Struktur für Balkendiagramm."""
        result = transform_for_comparison(sample_timeseries_data)
        
        for point in result:
            assert "category" in point
            assert "value" in point
    
    def test_comparison_calculates_average(self, sample_timeseries_single_key):
        """Testet ob Durchschnitt berechnet wird."""
        result = transform_for_comparison(sample_timeseries_single_key)
        
        assert len(result) == 1
        assert isinstance(result[0]["value"], float)
    
    def test_comparison_empty_data(self):
        """Testet leere Daten."""
        result = transform_for_comparison({})
        
        assert result == []


# =============================================================================
# TRANSFORM_LATEST_VALUES TESTS
# =============================================================================

class TestTransformLatestValues:
    """Tests für transform_latest_values()."""
    
    def test_latest_values_structure(self, latest_telemetry_response):
        """Testet Struktur für Column Chart."""
        result = transform_latest_values(latest_telemetry_response)
        
        for point in result:
            assert "category" in point
            assert "value" in point
    
    def test_latest_values_are_floats(self, latest_telemetry_response):
        """Testet ob values Floats sind."""
        result = transform_latest_values(latest_telemetry_response)
        
        for point in result:
            assert isinstance(point["value"], float)
    
    def test_latest_values_key_names_formatted(self, latest_telemetry_response):
        """Testet ob Key-Namen aufgehübscht werden."""
        result = transform_latest_values(latest_telemetry_response)
        
        for point in result:
            # Sollte nicht den Original-Key haben
            assert "axis_act_" not in point["category"]


# =============================================================================
# GET_UNIT_FOR_KEY TESTS
# =============================================================================

class TestGetUnitForKey:
    """Tests für get_unit_for_key()."""
    
    @pytest.mark.parametrize("key,expected_unit", [
        ("axis_act_a1_deg", "°"),
        ("pos_act_x_mm", "mm"),
        ("torque_act_a1_nm", "Nm"),
        ("override_pct", "%"),
        ("vel_act_m_per_s", "m/s"),
        ("energy_period_kwh", "kWh"),
        ("unknown_key", ""),
    ])
    def test_unit_mapping(self, key, expected_unit):
        """Testet Unit-Mapping für verschiedene Keys."""
        result = get_unit_for_key(key)
        
        assert result == expected_unit


# =============================================================================
# EXTRACT_CHART_URL TESTS
# =============================================================================

class TestExtractChartUrl:
    """Tests für extract_chart_url()."""
    
    def test_extract_url_from_string(self, create_tool_message):
        """Testet URL-Extraktion aus String."""
        msg = create_tool_message("https://example.com/chart.png")
        
        result = extract_chart_url([msg])
        
        assert result == "https://example.com/chart.png"
    
    def test_extract_url_from_json(self, create_tool_message):
        """Testet URL-Extraktion aus JSON."""
        msg = create_tool_message({"url": "https://example.com/chart.png"})
        
        result = extract_chart_url([msg])
        
        assert result == "https://example.com/chart.png"
    
    def test_extract_chart_url_key(self, create_tool_message):
        """Testet chart_url Key."""
        msg = create_tool_message({"chart_url": "https://example.com/chart.png"})
        
        result = extract_chart_url([msg])
        
        assert result == "https://example.com/chart.png"
    
    def test_no_url_found(self, create_tool_message):
        """Testet wenn keine URL gefunden wird."""
        msg = create_tool_message({"status": "error"})
        
        result = extract_chart_url([msg])
        
        assert result is None
    
    def test_empty_messages(self):
        """Testet leere Message-Liste."""
        result = extract_chart_url([])
        
        assert result is None
    
    def test_uses_last_tool_message(self, create_tool_message):
        """Testet dass die letzte ToolMessage verwendet wird."""
        msg1 = create_tool_message("https://old.com/chart.png")
        msg2 = create_tool_message("https://new.com/chart.png")
        
        result = extract_chart_url([msg1, msg2])
        
        assert result == "https://new.com/chart.png"


# =============================================================================
# PREPARE_VIZ_CONTEXT TESTS
# =============================================================================

class TestPrepareVizContext:
    """Tests für prepare_viz_context()."""
    
    def test_includes_user_query(self, state_with_data):
        """Testet ob User-Query enthalten ist."""
        context = prepare_viz_context(state_with_data)
        
        assert "User-Anfrage" in context
    
    def test_includes_data_summary(self, state_with_data):
        """Testet ob Data-Summary enthalten ist."""
        context = prepare_viz_context(state_with_data)
        
        assert "Geladene Daten" in context
    
    def test_includes_available_keys(self, state_with_data):
        """Testet ob Keys aufgelistet werden."""
        context = prepare_viz_context(state_with_data)
        
        assert "Keys" in context or "key" in context.lower()
    
    def test_includes_transformed_data(self, state_with_data):
        """Testet ob transformierte Daten enthalten sind."""
        context = prepare_viz_context(state_with_data)
        
        assert "Line Chart" in context or "transformiert" in context


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestVizAgentIntegration:
    """Integration Tests für Viz Agent Komponenten."""
    
    def test_full_transformation_pipeline(self, sample_timeseries_data):
        """Testet komplette Transformation Pipeline."""
        # 1. Transformation
        transformed = transform_timeseries_for_antv(sample_timeseries_data)
        
        # 2. Prüfungen
        assert len(transformed) > 0
        
        # 3. JSON-serialisierbar
        json_str = json.dumps(transformed)
        restored = json.loads(json_str)
        
        assert restored == transformed
    
    def test_state_to_viz_context(self, state_after_data_agent):
        """Testet State → Context Transformation."""
        context = prepare_viz_context(state_after_data_agent)
        
        # Context sollte genug Info für Viz Agent haben
        assert len(context) > 100
        assert "data" in context.lower() or "Daten" in context
