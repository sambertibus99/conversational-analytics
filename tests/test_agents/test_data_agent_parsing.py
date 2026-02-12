"""
Tests für Data Agent Parsing-Funktionen.

Testet extract_data_from_parsed() und generate_data_summary()
mit allen bekannten Response-Formaten.

Referenz: docs/AP9_DEBUGGING_TESTING.md Abschnitt 2
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pytest
import json
from unittest.mock import patch, MagicMock

from agents.data_agent import (
    extract_data_from_parsed,
    generate_data_summary,
    extract_text_from_tool_content,
    parse_json_safe,
    load_data_from_file,
    determine_dataset_key_rich,
    _extract_time_range,
)


# =============================================================================
# EXTRACT_TEXT_FROM_TOOL_CONTENT TESTS
# =============================================================================

class TestExtractTextFromToolContent:
    """Tests für extract_text_from_tool_content()."""
    
    def test_string_content(self):
        """Testet String-Content."""
        result = extract_text_from_tool_content('{"status": "success"}')
        
        assert result == '{"status": "success"}'
    
    def test_list_with_text_block(self):
        """Testet Liste mit Text-Block."""
        content = [{"type": "text", "text": '{"status": "success"}'}]
        
        result = extract_text_from_tool_content(content)
        
        assert result == '{"status": "success"}'
    
    def test_list_with_string(self):
        """Testet Liste mit String."""
        content = ['{"status": "success"}']
        
        result = extract_text_from_tool_content(content)
        
        assert result == '{"status": "success"}'
    
    def test_dict_with_text_key(self):
        """Testet Dict mit 'text' Key."""
        content = {"text": '{"status": "success"}'}
        
        result = extract_text_from_tool_content(content)
        
        assert result == '{"status": "success"}'
    
    def test_none_content(self):
        """Testet None-Content."""
        result = extract_text_from_tool_content(None)
        
        assert result is None
    
    def test_empty_list(self):
        """Testet leere Liste."""
        result = extract_text_from_tool_content([])
        
        assert result is None


# =============================================================================
# PARSE_JSON_SAFE TESTS
# =============================================================================

class TestParseJsonSafe:
    """Tests für parse_json_safe()."""
    
    def test_valid_json(self):
        """Testet gültiges JSON."""
        result = parse_json_safe('{"status": "success"}')
        
        assert result == {"status": "success"}
    
    def test_invalid_json(self):
        """Testet ungültiges JSON."""
        result = parse_json_safe('not json')
        
        assert result is None
    
    def test_empty_string(self):
        """Testet leeren String."""
        result = parse_json_safe('')
        
        assert result is None
    
    def test_none_input(self):
        """Testet None Input."""
        result = parse_json_safe(None)
        
        assert result is None
    
    def test_json_list(self):
        """Testet JSON-Liste."""
        result = parse_json_safe('["key1", "key2"]')
        
        assert result == ["key1", "key2"]


# =============================================================================
# EXTRACT_DATA_FROM_PARSED TESTS - NO_DATA
# =============================================================================

class TestExtractNoData:
    """Tests für no_data Response-Handling."""
    
    def test_no_data_detected(self, no_data_response):
        """Testet ob no_data erkannt wird."""
        data, meta, file = extract_data_from_parsed(no_data_response)
        
        assert data is None
        assert meta is not None
        assert meta["type"] == "no_data"
    
    def test_no_data_has_message(self, no_data_response):
        """Testet ob Message übernommen wird."""
        data, meta, file = extract_data_from_parsed(no_data_response)
        
        assert "message" in meta
        assert meta["message"] is not None
    
    def test_no_data_has_timerange(self, no_data_response):
        """Testet ob requested_timerange übernommen wird."""
        data, meta, file = extract_data_from_parsed(no_data_response)
        
        assert "requested_timerange" in meta
    
    def test_no_data_priority_over_other_fields(self):
        """Testet ob status='no_data' Priorität hat."""
        # Response die no_data ist aber auch andere Felder hat
        response = {
            "status": "no_data",
            "message": "Keine Daten",
            "data": {"fake": "data"},  # Sollte ignoriert werden!
        }
        
        data, meta, file = extract_data_from_parsed(response)
        
        assert data is None
        assert meta["type"] == "no_data"


# =============================================================================
# EXTRACT_DATA_FROM_PARSED TESTS - DATA_AVAILABLE
# =============================================================================

class TestExtractDataAvailable:
    """Tests für data_available Response-Handling."""
    
    def test_data_available_detected(self, data_available_response):
        """Testet ob data_available erkannt wird."""
        data, meta, file = extract_data_from_parsed(data_available_response)
        
        assert data is not None  # Originales dict zurückgeben
        assert meta["type"] == "data_availability"
    
    def test_data_available_has_range(self, data_available_response):
        """Testet ob data_range übernommen wird."""
        data, meta, file = extract_data_from_parsed(data_available_response)
        
        assert "data_range" in meta
        assert "first_data" in meta["data_range"]
        assert "last_data" in meta["data_range"]
    
    def test_data_available_has_total_points(self, data_available_response):
        """Testet ob total_points übernommen wird."""
        data, meta, file = extract_data_from_parsed(data_available_response)
        
        assert "total_points" in meta


# =============================================================================
# EXTRACT_DATA_FROM_PARSED TESTS - SUCCESS WITH FILE
# =============================================================================

class TestExtractSuccessWithFile:
    """Tests für success Response mit data_file."""
    
    def test_success_with_file_detected(self, success_response, temp_data_file, sample_timeseries_data):
        """Testet ob success mit data_file erkannt wird."""
        # Modifiziere Response um auf temp_data_file zu zeigen
        response = {**success_response, "data_file": str(temp_data_file)}
        
        data, meta, file = extract_data_from_parsed(response)
        
        assert data is not None
        assert meta["type"] == "success"
        assert file == str(temp_data_file)
    
    def test_success_loads_data_from_file(self, success_response, temp_data_file):
        """Testet ob Daten aus Datei geladen werden."""
        response = {**success_response, "data_file": str(temp_data_file)}
        
        data, meta, file = extract_data_from_parsed(response)
        
        # Daten sollten aus Datei geladen sein
        assert isinstance(data, dict)
        assert len(data) > 0
    
    def test_success_has_statistics_in_meta(self, success_response, temp_data_file):
        """Testet ob statistics in meta sind."""
        response = {**success_response, "data_file": str(temp_data_file)}
        
        data, meta, file = extract_data_from_parsed(response)
        
        assert "statistics" in meta
    
    def test_success_with_missing_file(self, success_response):
        """Testet Verhalten bei fehlender Datei."""
        response = {**success_response, "data_file": "/nonexistent/file.json"}
        
        data, meta, file = extract_data_from_parsed(response)
        
        # Sollte nicht crashen, aber keine Daten laden
        # (Fallback-Verhalten)


# =============================================================================
# EXTRACT_DATA_FROM_PARSED TESTS - LATEST TELEMETRY
# =============================================================================

class TestExtractLatestTelemetry:
    """Tests für get_latest_telemetry Response-Handling."""
    
    def test_latest_telemetry_detected(self, latest_telemetry_response):
        """Testet ob latest telemetry erkannt wird."""
        data, meta, file = extract_data_from_parsed(latest_telemetry_response)
        
        assert data is not None
        assert meta["type"] == "latest"
    
    def test_latest_telemetry_data_preserved(self, latest_telemetry_response):
        """Testet ob Daten erhalten bleiben."""
        data, meta, file = extract_data_from_parsed(latest_telemetry_response)
        
        assert data == latest_telemetry_response
    
    def test_latest_telemetry_data_points(self, latest_telemetry_response):
        """Testet ob data_points korrekt sind."""
        data, meta, file = extract_data_from_parsed(latest_telemetry_response)
        
        assert "data_points" in meta
        for key in latest_telemetry_response:
            assert meta["data_points"][key] == 1


# =============================================================================
# EXTRACT_DATA_FROM_PARSED TESTS - LIST RESPONSES
# =============================================================================

class TestExtractListResponse:
    """Tests für Listen-Responses (keys, devices)."""
    
    def test_list_detected(self, telemetry_keys_response):
        """Testet ob Liste erkannt wird."""
        data, meta, file = extract_data_from_parsed(telemetry_keys_response)
        
        assert data is not None
        assert meta["type"] == "list"
    
    def test_list_count_correct(self, telemetry_keys_response):
        """Testet ob count korrekt ist."""
        data, meta, file = extract_data_from_parsed(telemetry_keys_response)
        
        assert meta["count"] == len(telemetry_keys_response)
    
    def test_list_data_preserved(self, telemetry_keys_response):
        """Testet ob Liste erhalten bleibt."""
        data, meta, file = extract_data_from_parsed(telemetry_keys_response)
        
        assert data == telemetry_keys_response


# =============================================================================
# EXTRACT_DATA_FROM_PARSED TESTS - EDGE CASES
# =============================================================================

class TestExtractEdgeCases:
    """Tests für Edge Cases."""
    
    def test_none_input(self):
        """Testet None Input."""
        data, meta, file = extract_data_from_parsed(None)
        
        assert data is None
        assert meta is None
        assert file is None
    
    def test_empty_dict(self):
        """Testet leeres Dict."""
        data, meta, file = extract_data_from_parsed({})
        
        # Leeres dict ist kein Fehler
        assert data is None or data == {}
    
    def test_unknown_format(self):
        """Testet unbekanntes Format."""
        data, meta, file = extract_data_from_parsed({"unknown": "format"})
        
        # Sollte als "other" behandelt werden
        assert meta is not None
        assert meta["type"] == "other"


# =============================================================================
# GENERATE_DATA_SUMMARY TESTS
# =============================================================================

class TestGenerateDataSummary:
    """Tests für generate_data_summary()."""
    
    def test_no_data_summary(self):
        """Testet Summary für no_data."""
        meta = {
            "type": "no_data",
            "message": "Keine Daten gefunden",
            "requested_timerange": {
                "weekday": "Mittwoch",
                "start": "17.12.2025 13:00",
                "end": "17.12.2025 13:10",
            },
        }

        summary = generate_data_summary(None, meta)

        assert "KEINE DATEN" in summary
        assert "Keine Daten gefunden" in summary

    def test_data_availability_summary(self):
        """Testet Summary für data_availability."""
        meta = {
            "type": "data_availability",
            "data_range": {
                "first_data": "16.12.2025 11:56",
                "first_weekday": "Dienstag",
                "last_data": "16.12.2025 18:36",
                "last_weekday": "Dienstag",
            },
            "total_points": 24000,
        }

        summary = generate_data_summary({}, meta)

        assert "VERFÜGBAR" in summary
        assert "16.12.2025" in summary

    def test_success_with_statistics_summary(self):
        """Testet Summary für success mit Statistiken."""
        meta = {
            "type": "success",
            "timerange": {
                "weekday": "Dienstag",
                "start": "16.12.2025 12:00",
                "end": "16.12.2025 12:10",
            },
            "statistics": {
                "pos_act_x_mm": {
                    "avg": 94.789,
                    "min": 94.123,
                    "max": 95.456,
                    "count": 627,
                }
            },
        }

        summary = generate_data_summary({"pos_act_x_mm": []}, meta)

        assert "pos_act_x_mm" in summary
        assert "627" in summary

    def test_latest_telemetry_summary(self, latest_telemetry_response):
        """Testet Summary für latest telemetry."""
        meta = {"type": "latest", "data_points": {"axis_act_a1_deg": 1}}

        summary = generate_data_summary(latest_telemetry_response, meta)

        assert "Aktuelle Werte" in summary

    def test_list_summary(self, telemetry_keys_response):
        """Testet Summary für Listen."""
        meta = {"type": "list", "count": len(telemetry_keys_response)}

        summary = generate_data_summary(telemetry_keys_response, meta)

        assert len(summary) > 0
    
    def test_none_data_none_meta(self):
        """Testet Summary für None/None."""
        summary = generate_data_summary(None, None)
        
        assert "Keine Daten" in summary


# =============================================================================
# LOAD_DATA_FROM_FILE TESTS
# =============================================================================

class TestLoadDataFromFile:
    """Tests für load_data_from_file()."""
    
    def test_load_valid_file(self, temp_data_file):
        """Testet Laden einer gültigen Datei."""
        data = load_data_from_file(str(temp_data_file))
        
        assert data is not None
        assert "data" in data
    
    def test_load_nonexistent_file(self):
        """Testet Laden einer nicht-existenten Datei."""
        data = load_data_from_file("/nonexistent/file.json")
        
        assert data is None
    
    def test_load_invalid_json_file(self, tmp_path):
        """Testet Laden einer Datei mit ungültigem JSON."""
        invalid_file = tmp_path / "invalid.json"
        invalid_file.write_text("not valid json")
        
        data = load_data_from_file(str(invalid_file))
        
        assert data is None


# =============================================================================
# PRIORITY TESTS (aus AP9-Dokumentation)
# =============================================================================

class TestResponsePriority:
    """Tests für Response-Priorität."""
    
    def test_no_data_checked_first(self):
        """
        KRITISCH: status='no_data' MUSS zuerst geprüft werden!
        
        Auch wenn andere Felder vorhanden sind, muss no_data erkannt werden.
        """
        response = {
            "status": "no_data",
            "message": "Keine Daten",
            "requested_timerange": {"start": "...", "end": "..."},
            # Diese Felder könnten fälschlicherweise als success interpretiert werden:
            "data_file": "/some/file.json",
            "statistics": {"fake": "stats"},
        }
        
        data, meta, file = extract_data_from_parsed(response)
        
        # MUSS no_data sein, nicht success!
        assert meta["type"] == "no_data"
        assert data is None
    
    def test_data_available_checked_second(self):
        """data_available vor success prüfen."""
        response = {
            "status": "data_available",
            "data_range": {"first_data": "...", "last_data": "..."},
            "message": "Daten verfügbar",
            # Diese Felder könnten fälschlicherweise als success interpretiert werden:
            "statistics": {"fake": "stats"},
        }
        
        data, meta, file = extract_data_from_parsed(response)

        assert meta["type"] == "data_availability"


# =============================================================================
# DETERMINE_DATASET_KEY_RICH TESTS (DEC-026)
# =============================================================================

class TestDetermineDatasetKeyRich:
    """Tests für determine_dataset_key_rich()."""

    def test_basic_timeseries_overview(self):
        """Overview Timeseries-Key mit Metadaten."""
        data = {"torque_act_a1_nm": [{"value": "25.0", "timestamp": 1000}]}
        meta = {
            "type": "success",
            "timerange": {
                "start_human": "16.12.2025 12:00",
                "end_human": "16.12.2025 14:00",
            },
            "settings": {
                "interval_human": "60 Sekunden",
                "aggregation": "AVG",
            },
        }
        key = determine_dataset_key_rich(data, meta, "overview")
        assert key == "krc5/torque_act_a1_nm/timeseries/overview/2025-12-16_12-00_14-00/60sekunden_avg"

    def test_detail_mode_no_interval(self):
        """Detail-Modus ohne Intervall."""
        data = {"torque_act_a1_nm": [{"value": "25.0", "timestamp": 1000}]}
        meta = {
            "type": "success",
            "timerange": {
                "start_human": "16.12.2025 12:00",
                "end_human": "16.12.2025 14:00",
            },
        }
        key = determine_dataset_key_rich(data, meta, "detail")
        assert key == "krc5/torque_act_a1_nm/timeseries/detail/2025-12-16_12-00_14-00"

    def test_latest_telemetry(self):
        """Latest-Telemetrie-Key."""
        data = {"axis_act_a1_deg": {"value": "25.34", "timestamp": 1000}}
        meta = {"type": "latest"}
        key = determine_dataset_key_rich(data, meta, "overview")
        assert key == "krc5/axis_act_a1_deg/latest/overview"

    def test_no_meta(self):
        """Key ohne Metadaten — Fallback auf Basis-Key."""
        data = {"vel_act_m_per_s": [{"value": "1.0", "timestamp": 1000}]}
        key = determine_dataset_key_rich(data, None, "overview")
        assert key == "krc5/vel_act_m_per_s/timeseries/overview"

    def test_none_data(self):
        """None-Daten geben 'unknown'."""
        key = determine_dataset_key_rich(None, None, "overview")
        assert key == "unknown"

    def test_empty_data(self):
        """Leere Daten geben 'unknown'."""
        key = determine_dataset_key_rich({}, None, "overview")
        assert key == "unknown"

    def test_different_signals_different_keys(self):
        """Verschiedene Signale erzeugen verschiedene Keys."""
        torque_data = {"torque_act_a1_nm": [{"value": "25.0", "timestamp": 1000}]}
        vel_data = {"vel_act_m_per_s": [{"value": "1.0", "timestamp": 1000}]}
        meta = {"type": "success", "timerange": {"start_human": "16.12.2025 12:00", "end_human": "16.12.2025 14:00"}}

        key_torque = determine_dataset_key_rich(torque_data, meta, "overview")
        key_vel = determine_dataset_key_rich(vel_data, meta, "overview")

        assert key_torque != key_vel
        assert "torque_act_a1_nm" in key_torque
        assert "vel_act_m_per_s" in key_vel

    def test_different_time_ranges_different_keys(self):
        """Verschiedene Zeiträume erzeugen verschiedene Keys."""
        data = {"torque_act_a1_nm": [{"value": "25.0", "timestamp": 1000}]}
        meta1 = {"type": "success", "timerange": {"start_human": "16.12.2025 12:00", "end_human": "16.12.2025 14:00"}}
        meta2 = {"type": "success", "timerange": {"start_human": "16.12.2025 14:00", "end_human": "16.12.2025 16:00"}}

        key1 = determine_dataset_key_rich(data, meta1, "overview")
        key2 = determine_dataset_key_rich(data, meta2, "overview")

        assert key1 != key2

    def test_different_modes_different_keys(self):
        """detail vs overview erzeugen verschiedene Keys."""
        data = {"torque_act_a1_nm": [{"value": "25.0", "timestamp": 1000}]}
        meta = {"type": "success", "timerange": {"start_human": "16.12.2025 12:00", "end_human": "16.12.2025 14:00"}}

        key_detail = determine_dataset_key_rich(data, meta, "detail")
        key_overview = determine_dataset_key_rich(data, meta, "overview")

        assert key_detail != key_overview
        assert "/detail/" in key_detail
        assert "/overview/" in key_overview


# =============================================================================
# _EXTRACT_TIME_RANGE TESTS (DEC-026)
# =============================================================================

class TestExtractTimeRange:
    """Tests für _extract_time_range()."""

    def test_same_day_german_format(self):
        """Gleicher Tag, deutsches Datumsformat."""
        tr = {"start_human": "16.12.2025 12:00", "end_human": "16.12.2025 14:00"}
        assert _extract_time_range(tr) == "2025-12-16_12-00_14-00"

    def test_different_days(self):
        """Verschiedene Tage."""
        tr = {"start_human": "16.12.2025 12:00", "end_human": "17.12.2025 08:00"}
        assert _extract_time_range(tr) == "2025-12-16_12-00_2025-12-17_08-00"

    def test_iso_format(self):
        """ISO-Datumsformat."""
        tr = {"start": "2025-12-16 12:00", "end": "2025-12-16 14:00"}
        assert _extract_time_range(tr) == "2025-12-16_12-00_14-00"

    def test_empty_dict(self):
        """Leeres Dict gibt leeren String."""
        assert _extract_time_range({}) == ""

    def test_only_start(self):
        """Nur Start vorhanden."""
        tr = {"start_human": "16.12.2025 12:00"}
        result = _extract_time_range(tr)
        assert result.startswith("2025-12-16_12-00")

    def test_no_time(self):
        """Unparsbare Zeitangabe."""
        tr = {"start_human": "gestern", "end_human": "heute"}
        assert _extract_time_range(tr) == ""

    def test_start_fallback_to_start_key(self):
        """Fallback: 'start' statt 'start_human'."""
        tr = {"start": "16.12.2025 12:00", "end": "16.12.2025 14:00"}
        assert _extract_time_range(tr) == "2025-12-16_12-00_14-00"
