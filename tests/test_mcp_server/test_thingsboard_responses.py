"""
Tests für ThingsBoard MCP Server Response-Formate.

Prüft ob alle Response-Formate die erwarteten Felder haben:
- success: status, timerange, data_points, statistics, data_file
- no_data: status, message, requested_timerange, hint
- data_available: status, data_range, message, total_points
- error: status, error_type, message

Referenz: docs/AP9_DEBUGGING_TESTING.md Abschnitt 1.1
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pytest
import json


# =============================================================================
# RESPONSE FORMAT DEFINITIONS
# =============================================================================

EXPECTED_RESPONSE_FORMATS = {
    "get_telemetry_success": {
        "required": ["status", "timerange", "data_points", "statistics", "data_file"],
        "status_value": "success",
    },
    "get_telemetry_no_data": {
        "required": ["status", "message", "requested_timerange", "hint"],
        "status_value": "no_data",
    },
    "get_data_availability_success": {
        "required": ["status", "data_range", "message", "total_points"],
        "status_value": "data_available",
    },
    "get_data_availability_no_data": {
        "required": ["status", "message"],
        "status_value": "no_data",
    },
    "get_latest_telemetry": {
        # Format: {"key": {"value": "...", "timestamp": ..., "timestamp_human": "...", "weekday": "..."}}
        "required_per_key": ["value", "timestamp"],
        "optional_per_key": ["timestamp_human", "weekday"],
    },
    "error": {
        "required": ["status", "message"],
        "optional": ["error_type"],
        "status_value": "error",
    },
}


# =============================================================================
# SUCCESS RESPONSE TESTS
# =============================================================================

class TestSuccessResponse:
    """Tests für erfolgreiche Responses."""
    
    def test_success_has_required_fields(self, success_response):
        """Prüft ob success-Response alle erforderlichen Felder hat."""
        required = EXPECTED_RESPONSE_FORMATS["get_telemetry_success"]["required"]
        
        for field in required:
            assert field in success_response, f"Feld '{field}' fehlt in success_response"
    
    def test_success_status_value(self, success_response):
        """Prüft ob status='success' gesetzt ist."""
        assert success_response["status"] == "success"
    
    def test_success_timerange_structure(self, success_response):
        """Prüft timerange-Struktur."""
        timerange = success_response["timerange"]
        
        assert "start" in timerange, "timerange.start fehlt"
        assert "end" in timerange, "timerange.end fehlt"
        assert "weekday" in timerange, "timerange.weekday fehlt"
    
    def test_success_statistics_structure(self, success_response):
        """Prüft statistics-Struktur."""
        stats = success_response["statistics"]
        
        assert isinstance(stats, dict), "statistics muss ein dict sein"
        
        for key, stat in stats.items():
            assert "count" in stat, f"statistics[{key}].count fehlt"
            assert "min" in stat, f"statistics[{key}].min fehlt"
            assert "max" in stat, f"statistics[{key}].max fehlt"
            assert "avg" in stat, f"statistics[{key}].avg fehlt"
    
    def test_success_data_file_is_path(self, success_response):
        """Prüft ob data_file ein gültiger Pfad ist."""
        data_file = success_response["data_file"]
        
        assert isinstance(data_file, str), "data_file muss ein String sein"
        assert len(data_file) > 0, "data_file darf nicht leer sein"


# =============================================================================
# NO_DATA RESPONSE TESTS
# =============================================================================

class TestNoDataResponse:
    """Tests für no_data Responses."""
    
    def test_no_data_has_required_fields(self, no_data_response):
        """Prüft ob no_data-Response alle erforderlichen Felder hat."""
        required = EXPECTED_RESPONSE_FORMATS["get_telemetry_no_data"]["required"]
        
        for field in required:
            assert field in no_data_response, f"Feld '{field}' fehlt in no_data_response"
    
    def test_no_data_status_value(self, no_data_response):
        """Prüft ob status='no_data' gesetzt ist."""
        assert no_data_response["status"] == "no_data"
    
    def test_no_data_has_message(self, no_data_response):
        """Prüft ob eine verständliche Message vorhanden ist."""
        message = no_data_response["message"]
        
        assert isinstance(message, str), "message muss ein String sein"
        assert len(message) > 10, "message sollte aussagekräftig sein"
    
    def test_no_data_requested_timerange_structure(self, no_data_response):
        """Prüft requested_timerange-Struktur."""
        timerange = no_data_response["requested_timerange"]
        
        assert isinstance(timerange, dict), "requested_timerange muss ein dict sein"
        assert "start" in timerange, "requested_timerange.start fehlt"
        assert "end" in timerange, "requested_timerange.end fehlt"
    
    def test_no_data_has_hint(self, no_data_response):
        """Prüft ob ein hilfreicher Hint vorhanden ist."""
        hint = no_data_response["hint"]
        
        assert isinstance(hint, str), "hint muss ein String sein"
        assert "get_data_availability" in hint.lower() or "verfügbar" in hint.lower(), \
            "hint sollte auf get_data_availability verweisen"


# =============================================================================
# DATA_AVAILABLE RESPONSE TESTS
# =============================================================================

class TestDataAvailableResponse:
    """Tests für data_available Responses."""
    
    def test_data_available_has_required_fields(self, data_available_response):
        """Prüft ob data_available-Response alle erforderlichen Felder hat."""
        required = EXPECTED_RESPONSE_FORMATS["get_data_availability_success"]["required"]
        
        for field in required:
            assert field in data_available_response, f"Feld '{field}' fehlt in data_available_response"
    
    def test_data_available_status_value(self, data_available_response):
        """Prüft ob status='data_available' gesetzt ist."""
        assert data_available_response["status"] == "data_available"
    
    def test_data_available_data_range_structure(self, data_available_response):
        """Prüft data_range-Struktur."""
        data_range = data_available_response["data_range"]
        
        assert "first_data" in data_range, "data_range.first_data fehlt"
        assert "first_time" in data_range, "data_range.first_time fehlt"
        assert "last_data" in data_range, "data_range.last_data fehlt"
        assert "last_time" in data_range, "data_range.last_time fehlt"
        assert "first_weekday" in data_range, "data_range.first_weekday fehlt"
        assert "last_weekday" in data_range, "data_range.last_weekday fehlt"
    
    def test_data_available_total_points(self, data_available_response):
        """Prüft ob total_points eine positive Zahl ist."""
        total_points = data_available_response["total_points"]
        
        assert isinstance(total_points, int), "total_points muss int sein"
        assert total_points > 0, "total_points muss positiv sein"


# =============================================================================
# LATEST TELEMETRY RESPONSE TESTS
# =============================================================================

class TestLatestTelemetryResponse:
    """Tests für get_latest_telemetry Responses."""
    
    def test_latest_telemetry_structure(self, latest_telemetry_response):
        """Prüft Struktur von get_latest_telemetry Response."""
        assert isinstance(latest_telemetry_response, dict)
        assert len(latest_telemetry_response) > 0, "Response darf nicht leer sein"
    
    def test_latest_telemetry_value_structure(self, latest_telemetry_response):
        """Prüft ob jeder Key die erwartete Struktur hat."""
        required = EXPECTED_RESPONSE_FORMATS["get_latest_telemetry"]["required_per_key"]
        
        for key, value in latest_telemetry_response.items():
            assert isinstance(value, dict), f"{key} muss ein dict sein"
            
            for field in required:
                assert field in value, f"{key}.{field} fehlt"
    
    def test_latest_telemetry_has_human_readable_time(self, latest_telemetry_response):
        """Prüft ob timestamp_human und weekday vorhanden sind."""
        for key, value in latest_telemetry_response.items():
            assert "timestamp_human" in value, f"{key}.timestamp_human fehlt"
            assert "weekday" in value, f"{key}.weekday fehlt"
    
    def test_latest_telemetry_value_is_string(self, latest_telemetry_response):
        """Prüft ob value ein String ist (ThingsBoard-Format)."""
        for key, value in latest_telemetry_response.items():
            assert isinstance(value["value"], str), f"{key}.value sollte String sein"


# =============================================================================
# ERROR RESPONSE TESTS
# =============================================================================

class TestErrorResponse:
    """Tests für Error Responses."""
    
    def test_error_has_required_fields(self, error_response):
        """Prüft ob error-Response alle erforderlichen Felder hat."""
        required = EXPECTED_RESPONSE_FORMATS["error"]["required"]
        
        for field in required:
            assert field in error_response, f"Feld '{field}' fehlt in error_response"
    
    def test_error_status_value(self, error_response):
        """Prüft ob status='error' gesetzt ist."""
        assert error_response["status"] == "error"
    
    def test_error_has_meaningful_message(self, error_response):
        """Prüft ob die Fehlermeldung aussagekräftig ist."""
        message = error_response["message"]
        
        assert isinstance(message, str)
        assert len(message) > 5, "Fehlermeldung sollte aussagekräftig sein"


# =============================================================================
# TELEMETRY KEYS RESPONSE TESTS
# =============================================================================

class TestTelemetryKeysResponse:
    """Tests für list_telemetry_keys Response."""
    
    def test_keys_is_list(self, telemetry_keys_response):
        """Prüft ob Response eine Liste ist."""
        assert isinstance(telemetry_keys_response, list)
    
    def test_keys_contains_strings(self, telemetry_keys_response):
        """Prüft ob alle Keys Strings sind."""
        for key in telemetry_keys_response:
            assert isinstance(key, str), f"Key {key} ist kein String"
    
    def test_keys_not_empty(self, telemetry_keys_response):
        """Prüft ob mindestens ein Key vorhanden ist."""
        assert len(telemetry_keys_response) > 0


# =============================================================================
# JSON SERIALIZATION TESTS
# =============================================================================

class TestJsonSerialization:
    """Tests für JSON-Serialisierung."""
    
    def test_success_response_serializable(self, success_response):
        """Prüft ob success_response zu JSON serialisierbar ist."""
        json_str = json.dumps(success_response)
        restored = json.loads(json_str)
        
        assert restored == success_response
    
    def test_no_data_response_serializable(self, no_data_response):
        """Prüft ob no_data_response zu JSON serialisierbar ist."""
        json_str = json.dumps(no_data_response)
        restored = json.loads(json_str)
        
        assert restored == no_data_response
    
    def test_data_available_response_serializable(self, data_available_response):
        """Prüft ob data_available_response zu JSON serialisierbar ist."""
        json_str = json.dumps(data_available_response)
        restored = json.loads(json_str)
        
        assert restored == data_available_response


# =============================================================================
# STATUS FIELD CONSISTENCY TESTS
# =============================================================================

class TestStatusFieldConsistency:
    """Tests für konsistente Status-Feld-Nutzung."""
    
    @pytest.mark.parametrize("status,fixture_name", [
        ("success", "success_response"),
        ("no_data", "no_data_response"),
        ("data_available", "data_available_response"),
        ("error", "error_response"),
    ])
    def test_status_values_are_valid(self, status, fixture_name, request):
        """Prüft ob alle Status-Werte aus der bekannten Menge sind."""
        valid_statuses = {"success", "no_data", "data_available", "error"}
        
        fixture = request.getfixturevalue(fixture_name)
        
        if "status" in fixture:
            assert fixture["status"] in valid_statuses, \
                f"Unbekannter Status: {fixture['status']}"
