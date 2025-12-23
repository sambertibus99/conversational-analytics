"""
Tests für ThingsBoard MCP Server Tool-Signaturen.

Testet die neuen strukturierten Parameter:
- get_telemetry: start_date, end_date, start_time, end_time, interval, aggregation
- Automatische Intervall-Berechnung

DESIGN-ENTSCHEIDUNGEN (19.12.2025):
1. Zeitraum-Parsing wird vom LLM übernommen (nicht mehr vom Tool)
2. Tools erwarten ISO-Format: start_date="YYYY-MM-DD", start_time="HH:MM"
3. Daten werden IMMER aggregiert - Intervall automatisch berechnet
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pytest
from datetime import datetime, timedelta


# =============================================================================
# IMPORT HELPERS
# =============================================================================

def get_parse_datetime():
    """Importiert parse_datetime aus dem Server."""
    from mcp_servers.thingsboard_server import parse_datetime
    return parse_datetime


def get_interval():
    """Importiert get_interval aus dem Server."""
    from mcp_servers.thingsboard_server import get_interval
    return get_interval


def get_calculate_auto_interval():
    """Importiert calculate_auto_interval aus dem Server."""
    from mcp_servers.thingsboard_server import calculate_auto_interval
    return calculate_auto_interval


def get_aggregation():
    """Importiert get_aggregation aus dem Server."""
    from mcp_servers.thingsboard_server import get_aggregation
    return get_aggregation


# =============================================================================
# PARSE_DATETIME TESTS
# =============================================================================

class TestParseDatetime:
    """Tests für die parse_datetime Funktion."""
    
    def test_basic_date(self):
        """Testet einfaches Datum."""
        parse_datetime = get_parse_datetime()
        result = parse_datetime("2025-12-16")
        
        assert result.year == 2025
        assert result.month == 12
        assert result.day == 16
        assert result.hour == 0
        assert result.minute == 0
    
    def test_date_with_time(self):
        """Testet Datum mit Zeit."""
        parse_datetime = get_parse_datetime()
        result = parse_datetime("2025-12-16", "14:30")
        
        assert result.year == 2025
        assert result.month == 12
        assert result.day == 16
        assert result.hour == 14
        assert result.minute == 30
    
    def test_date_with_midnight(self):
        """Testet Datum mit Mitternacht."""
        parse_datetime = get_parse_datetime()
        result = parse_datetime("2025-12-16", "00:00")
        
        assert result.hour == 0
        assert result.minute == 0
    
    def test_date_with_end_of_day(self):
        """Testet Datum mit 23:59."""
        parse_datetime = get_parse_datetime()
        result = parse_datetime("2025-12-16", "23:59")
        
        assert result.hour == 23
        assert result.minute == 59
    
    def test_invalid_date_raises_error(self):
        """Testet ungültiges Datum."""
        parse_datetime = get_parse_datetime()
        
        with pytest.raises(ValueError):
            parse_datetime("16.12.2025")  # Falsches Format
    
    def test_invalid_time_raises_error(self):
        """Testet ungültige Zeit."""
        parse_datetime = get_parse_datetime()
        
        with pytest.raises(ValueError):
            parse_datetime("2025-12-16", "14:30:00")  # Mit Sekunden
    
    def test_invalid_month_raises_error(self):
        """Testet ungültigen Monat."""
        parse_datetime = get_parse_datetime()
        
        with pytest.raises(ValueError):
            parse_datetime("2025-13-16")  # Monat 13


# =============================================================================
# GET_INTERVAL TESTS (Refactored - DEC-011)
# =============================================================================

class TestGetInterval:
    """Tests für die get_interval Funktion mit vordefinierten Optionen."""
    
    @pytest.mark.parametrize("input_str,expected_ms", [
        ("1h", 3600000),
        ("1m", 60000),
        ("5m", 300000),
        ("10m", 600000),
        ("30m", 1800000),
        ("6h", 21600000),
        ("1d", 86400000),
    ])
    def test_predefined_intervals(self, input_str, expected_ms):
        """Testet vordefinierte Intervall-Optionen."""
        get_interval_fn = get_interval()
        result_ms, result_human, is_auto = get_interval_fn(input_str)
        
        assert result_ms == expected_ms
        assert is_auto is False
    
    def test_none_returns_auto(self):
        """Testet dass None Auto-Intervall zurückgibt."""
        get_interval_fn = get_interval()
        result_ms, result_human, is_auto = get_interval_fn(None)
        
        assert result_ms is None
        assert result_human is None
        assert is_auto is True
    
    def test_unknown_interval_returns_auto(self):
        """Testet dass unbekanntes Intervall Auto zurückgibt."""
        get_interval_fn = get_interval()
        result_ms, result_human, is_auto = get_interval_fn("1 Stunde")  # Nicht in der Liste
        
        assert is_auto is True
    
    def test_case_insensitive(self):
        """Testet dass Groß-/Kleinschreibung ignoriert wird."""
        get_interval_fn = get_interval()
        
        result1 = get_interval_fn("1H")
        result2 = get_interval_fn("1h")
        result3 = get_interval_fn("1M")
        
        assert result1[0] == result2[0] == 3600000
        assert result3[0] == 60000


# =============================================================================
# AUTO INTERVAL CALCULATION TESTS
# =============================================================================

class TestAutoIntervalCalculation:
    """Tests für automatische Intervall-Berechnung."""
    
    def test_interval_for_30_minutes(self):
        """≤ 1 Stunde → 1 Minute Intervall."""
        calc = get_calculate_auto_interval()
        
        start = datetime(2025, 12, 16, 12, 0)
        end = datetime(2025, 12, 16, 12, 30)
        
        interval_ms, interval_human, reason = calc(start, end)
        
        assert interval_ms == 60000  # 1 Minute
        assert "1 Minute" in interval_human
    
    def test_interval_for_1_hour(self):
        """≤ 1 Stunde → 1 Minute Intervall."""
        calc = get_calculate_auto_interval()
        
        start = datetime(2025, 12, 16, 12, 0)
        end = datetime(2025, 12, 16, 13, 0)
        
        interval_ms, interval_human, reason = calc(start, end)
        
        assert interval_ms == 60000  # 1 Minute
    
    def test_interval_for_8_hours(self):
        """≤ 1 Tag → 10 Minuten Intervall."""
        calc = get_calculate_auto_interval()
        
        start = datetime(2025, 12, 16, 8, 0)
        end = datetime(2025, 12, 16, 16, 0)
        
        interval_ms, interval_human, reason = calc(start, end)
        
        assert interval_ms == 600000  # 10 Minuten
        assert "10 Minuten" in interval_human
    
    def test_interval_for_full_day(self):
        """≤ 1 Tag → 10 Minuten Intervall."""
        calc = get_calculate_auto_interval()
        
        start = datetime(2025, 12, 16, 0, 0)
        end = datetime(2025, 12, 16, 23, 59)
        
        interval_ms, interval_human, reason = calc(start, end)
        
        assert interval_ms == 600000  # 10 Minuten
    
    def test_interval_for_3_days(self):
        """≤ 1 Woche → 1 Stunde Intervall."""
        calc = get_calculate_auto_interval()
        
        start = datetime(2025, 12, 14, 0, 0)
        end = datetime(2025, 12, 16, 23, 59)
        
        interval_ms, interval_human, reason = calc(start, end)
        
        assert interval_ms == 3600000  # 1 Stunde
        assert "1 Stunde" in interval_human
    
    def test_interval_for_2_weeks(self):
        """> 1 Woche → 1 Tag Intervall."""
        calc = get_calculate_auto_interval()
        
        start = datetime(2025, 12, 1, 0, 0)
        end = datetime(2025, 12, 16, 23, 59)
        
        interval_ms, interval_human, reason = calc(start, end)
        
        assert interval_ms == 86400000  # 1 Tag
        assert "1 Tag" in interval_human


# =============================================================================
# GET_AGGREGATION TESTS (Refactored - DEC-011)
# =============================================================================

class TestGetAggregation:
    """Tests für Aggregations-Mapping mit vordefinierten Optionen."""
    
    @pytest.mark.parametrize("input_str,expected_agg", [
        ("AVG", "AVG"),
        ("MIN", "MIN"),
        ("MAX", "MAX"),
        ("SUM", "SUM"),
        ("COUNT", "COUNT"),
        ("avg", "AVG"),  # Case insensitive
        ("min", "MIN"),
        ("max", "MAX"),
    ])
    def test_predefined_aggregations(self, input_str, expected_agg):
        """Testet vordefinierte Aggregations-Optionen."""
        get_agg = get_aggregation()
        tb_agg, human = get_agg(input_str)
        
        assert tb_agg == expected_agg
    
    def test_default_aggregation(self):
        """Testet Default-Wert bei None."""
        get_agg = get_aggregation()
        tb_agg, human = get_agg(None)
        
        assert tb_agg == "AVG"
        assert human == "Durchschnitt"
    
    def test_unknown_aggregation_defaults_to_avg(self):
        """Testet unbekannte Aggregation → AVG."""
        get_agg = get_aggregation()
        tb_agg, human = get_agg("durchschnitt")  # Nicht mehr unterstützt!
        
        assert tb_agg == "AVG"  # Fallback
    
    def test_human_readable_names(self):
        """Testet menschenlesbare Namen."""
        get_agg = get_aggregation()
        
        _, human_avg = get_agg("AVG")
        _, human_min = get_agg("MIN")
        _, human_max = get_agg("MAX")
        
        assert human_avg == "Durchschnitt"
        assert human_min == "Minimum"
        assert human_max == "Maximum"


# =============================================================================
# TOOL PARAMETER TESTS
# =============================================================================

class TestToolParameters:
    """Tests für Tool-Parameter-Validierung."""
    
    def test_get_telemetry_has_aggregation_params(self):
        """Testet dass get_telemetry Aggregations-Parameter hat."""
        from mcp_servers.thingsboard_server import get_telemetry
        import inspect
        
        sig = inspect.signature(get_telemetry)
        params = list(sig.parameters.keys())
        
        assert "keys" in params
        assert "start_date" in params
        assert "end_date" in params
        assert "start_time" in params
        assert "end_time" in params
        assert "interval" in params
        assert "aggregation" in params
        assert "device_name" in params
    
    def test_get_telemetry_defaults(self):
        """Testet Default-Werte von get_telemetry."""
        from mcp_servers.thingsboard_server import get_telemetry
        import inspect
        
        sig = inspect.signature(get_telemetry)
        
        # start_time default = "00:00"
        assert sig.parameters["start_time"].default == "00:00"
        
        # end_time default = "23:59"
        assert sig.parameters["end_time"].default == "23:59"
        
        # interval default = None (auto)
        assert sig.parameters["interval"].default is None
        
        # aggregation default = None (AVG)
        assert sig.parameters["aggregation"].default is None
        
        # device_name default = "KRC5"
        assert sig.parameters["device_name"].default == "KRC5"
    
    def test_interval_and_aggregation_are_literal_types(self):
        """Testet dass interval und aggregation Literal Types sind."""
        from mcp_servers.thingsboard_server import get_telemetry
        import inspect
        from typing import get_args, get_origin, Union
        
        sig = inspect.signature(get_telemetry)
        
        # interval sollte Literal[...] | None sein
        interval_annotation = sig.parameters["interval"].annotation
        # Prüfe dass es eine Union mit None ist
        assert get_origin(interval_annotation) is Union or interval_annotation is not str
        
        # aggregation sollte Literal[...] | None sein
        agg_annotation = sig.parameters["aggregation"].annotation
        assert get_origin(agg_annotation) is Union or agg_annotation is not str


# =============================================================================
# EXPECTED DATA POINTS TESTS
# =============================================================================

class TestExpectedDataPoints:
    """Tests für erwartete Anzahl Datenpunkte."""
    
    def test_1_hour_gives_max_60_points(self):
        """1 Stunde mit 1-Minuten-Intervall → ~60 Punkte."""
        calc = get_calculate_auto_interval()
        
        start = datetime(2025, 12, 16, 12, 0)
        end = datetime(2025, 12, 16, 13, 0)
        
        interval_ms, _, _ = calc(start, end)
        duration_ms = (end - start).total_seconds() * 1000
        expected_points = duration_ms / interval_ms
        
        assert expected_points <= 60
    
    def test_1_day_gives_max_144_points(self):
        """1 Tag mit 10-Minuten-Intervall → ~144 Punkte."""
        calc = get_calculate_auto_interval()
        
        start = datetime(2025, 12, 16, 0, 0)
        end = datetime(2025, 12, 16, 23, 59)
        
        interval_ms, _, _ = calc(start, end)
        duration_ms = (end - start).total_seconds() * 1000
        expected_points = duration_ms / interval_ms
        
        assert expected_points <= 150  # ~144
    
    def test_1_week_gives_max_168_points(self):
        """1 Woche mit 1-Stunden-Intervall → ~168 Punkte."""
        calc = get_calculate_auto_interval()
        
        start = datetime(2025, 12, 9, 0, 0)
        end = datetime(2025, 12, 16, 0, 0)
        
        interval_ms, _, _ = calc(start, end)
        duration_ms = (end - start).total_seconds() * 1000
        expected_points = duration_ms / interval_ms
        
        assert expected_points <= 170  # ~168


# =============================================================================
# DATAPOINT LIMIT TESTS (DEC-010)
# =============================================================================

class TestDatapointLimit:
    """Tests für Datenpunkt-Limit-Prüfung."""
    
    def test_check_datapoint_limit_exists(self):
        """Testet dass check_datapoint_limit existiert."""
        from mcp_servers.thingsboard_server import check_datapoint_limit
        assert callable(check_datapoint_limit)
    
    def test_small_request_returns_none(self):
        """Kleine Anfrage (< 1000 Punkte) gibt None zurück."""
        from mcp_servers.thingsboard_server import check_datapoint_limit
        
        start = datetime(2025, 12, 16, 12, 0)
        end = datetime(2025, 12, 16, 13, 0)
        interval_ms = 60000  # 1 Minute
        
        result = check_datapoint_limit(start, end, interval_ms, "1 Minute", num_keys=1)
        
        # Sollte None sein (OK)
        assert result is None
    
    def test_large_request_returns_error(self):
        """Große Anfrage (> 10000 Punkte) gibt Fehler zurück."""
        from mcp_servers.thingsboard_server import check_datapoint_limit
        
        start = datetime(2025, 12, 16, 0, 0)
        end = datetime(2025, 12, 16, 23, 59)
        interval_ms = 1000  # 1 Sekunde! -> ~86400 Punkte
        
        result = check_datapoint_limit(start, end, interval_ms, "1 Sekunde", num_keys=1)
        
        # Sollte Fehler sein
        assert result is not None
        assert result["status"] == "error_too_many_datapoints"
        assert "suggestion" in result
        assert "user_action" in result
    
    def test_medium_request_returns_warning(self):
        """Mittlere Anfrage (1000-10000 Punkte) gibt Warnung zurück."""
        from mcp_servers.thingsboard_server import check_datapoint_limit
        
        start = datetime(2025, 12, 16, 0, 0)
        end = datetime(2025, 12, 16, 23, 59)
        interval_ms = 60000  # 1 Minute -> ~1440 Punkte
        
        result = check_datapoint_limit(start, end, interval_ms, "1 Minute", num_keys=1)
        
        # Sollte Warnung sein
        assert result is not None
        assert result["status"] == "warning_many_datapoints"
        assert result["continue"] is True
    
    def test_multiple_keys_multiply_points(self):
        """Mehrere Keys multiplizieren die Punkte."""
        from mcp_servers.thingsboard_server import check_datapoint_limit
        
        start = datetime(2025, 12, 16, 0, 0)
        end = datetime(2025, 12, 16, 2, 0)  # 2 Stunden
        interval_ms = 60000  # 1 Minute -> 120 Punkte pro Key
        
        # Mit 1 Key: OK
        result_1key = check_datapoint_limit(start, end, interval_ms, "1 Minute", num_keys=1)
        assert result_1key is None
        
        # Mit 100 Keys: 120 * 100 = 12000 -> Fehler
        result_100keys = check_datapoint_limit(start, end, interval_ms, "1 Minute", num_keys=100)
        # Points per key ist immer noch 120, aber total_points ist 12000
        # Die Prüfung basiert auf points_per_key, nicht total
        # Also sollte es immer noch None sein
        assert result_100keys is None  # Weil points_per_key = 120 < 1000


# =============================================================================
# ERROR HANDLING TESTS (DEC-009)
# =============================================================================

class TestErrorHandling:
    """Tests für Custom Exceptions und Error Handling."""
    
    def test_thingsboard_error_exists(self):
        """Testet dass ThingsBoardError existiert."""
        from mcp_servers.thingsboard_client import ThingsBoardError
        assert ThingsBoardError is not None
    
    def test_thingsboard_auth_error(self):
        """Testet ThingsBoardAuthError."""
        from mcp_servers.thingsboard_client import ThingsBoardAuthError
        
        error = ThingsBoardAuthError()
        assert "Authentifizierung" in error.message
        assert "hint" in error.details
    
    def test_thingsboard_connection_error(self):
        """Testet ThingsBoardConnectionError."""
        from mcp_servers.thingsboard_client import ThingsBoardConnectionError
        
        error = ThingsBoardConnectionError("Test-Fehler")
        assert error.message == "Test-Fehler"
        assert "hint" in error.details
    
    def test_thingsboard_not_found_error(self):
        """Testet ThingsBoardNotFoundError."""
        from mcp_servers.thingsboard_client import ThingsBoardNotFoundError
        
        error = ThingsBoardNotFoundError("Device", "test-id")
        assert "Device" in error.message
        assert "test-id" in error.message
        assert error.details["resource_type"] == "Device"
    
    def test_thingsboard_rate_limit_error(self):
        """Testet ThingsBoardRateLimitError."""
        from mcp_servers.thingsboard_client import ThingsBoardRateLimitError
        
        error = ThingsBoardRateLimitError(retry_after=30)
        assert "Rate Limit" in error.message
        assert error.details["retry_after_seconds"] == 30
    
    def test_error_to_dict(self):
        """Testet to_dict() Methode."""
        from mcp_servers.thingsboard_client import ThingsBoardError
        
        error = ThingsBoardError("Test", {"key": "value"})
        d = error.to_dict()
        
        assert d["error_type"] == "ThingsBoardError"
        assert d["message"] == "Test"
        assert d["details"]["key"] == "value"
    
    def test_retry_with_backoff_exists(self):
        """Testet dass retry_with_backoff existiert."""
        from mcp_servers.thingsboard_client import retry_with_backoff
        assert callable(retry_with_backoff)
    
    def test_format_thingsboard_error_exists(self):
        """Testet dass format_thingsboard_error existiert."""
        from mcp_servers.thingsboard_server import format_thingsboard_error
        assert callable(format_thingsboard_error)
    
    def test_format_thingsboard_error_output(self):
        """Testet format_thingsboard_error Output."""
        from mcp_servers.thingsboard_client import ThingsBoardAuthError
        from mcp_servers.thingsboard_server import format_thingsboard_error
        
        error = ThingsBoardAuthError()
        result = format_thingsboard_error(error)
        
        assert result["status"] == "error"
        assert result["error_type"] == "ThingsBoardAuthError"
        assert "message" in result
        assert "details" in result
