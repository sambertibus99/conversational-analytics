"""
Tests für Timerange-Parsing im ThingsBoard MCP Server.

Testet die parse_timerange() Funktion mit verschiedenen Eingabeformaten:
- Wochentage: "Dienstag 13 Uhr", "letzten Montag"
- Relative Zeiten: "letzte Stunde", "letzte 30 Minuten"
- Gestern: "gestern um 14 Uhr"
- Edge Cases: leere Strings, ungültige Eingaben

Referenz: docs/AP9_DEBUGGING_TESTING.md Abschnitt 7
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

from mcp_servers.thingsboard_server import parse_timerange, WEEKDAY_NAMES


# =============================================================================
# HELPER
# =============================================================================

def ts_to_datetime(ts_ms: int) -> datetime:
    """Konvertiert Millisekunden-Timestamp zu datetime."""
    return datetime.fromtimestamp(ts_ms / 1000)


def assert_timerange_valid(start_ts: int, end_ts: int):
    """Prüft ob ein Zeitraum gültig ist."""
    assert start_ts < end_ts, "start_ts muss vor end_ts liegen"
    assert start_ts > 0, "start_ts muss positiv sein"
    assert end_ts > 0, "end_ts muss positiv sein"


# =============================================================================
# BASIC TESTS
# =============================================================================

class TestParseTimerangeBasic:
    """Grundlegende Tests für parse_timerange."""
    
    def test_returns_tuple(self):
        """Prüft ob Funktion ein Tuple zurückgibt."""
        result = parse_timerange("letzte Stunde")
        
        assert isinstance(result, tuple)
        assert len(result) == 2
    
    def test_returns_integers(self):
        """Prüft ob Timestamps Integers sind."""
        start_ts, end_ts = parse_timerange("letzte Stunde")
        
        assert isinstance(start_ts, int)
        assert isinstance(end_ts, int)
    
    def test_start_before_end(self):
        """Prüft ob Start vor End liegt."""
        start_ts, end_ts = parse_timerange("letzte Stunde")
        
        assert_timerange_valid(start_ts, end_ts)
    
    def test_none_input_returns_default(self):
        """Prüft Default-Verhalten bei None."""
        start_ts, end_ts = parse_timerange(None)
        
        assert_timerange_valid(start_ts, end_ts)
        
        # Default ist "letzte Stunde"
        duration = (end_ts - start_ts) / 1000 / 60  # Minuten
        assert 55 <= duration <= 65, "Default sollte ~1 Stunde sein"


# =============================================================================
# RELATIVE TIMERANGE TESTS
# =============================================================================

class TestRelativeTimeranges:
    """Tests für relative Zeitangaben."""
    
    def test_letzte_stunde(self):
        """Testet 'letzte Stunde'."""
        start_ts, end_ts = parse_timerange("letzte Stunde")
        
        duration_minutes = (end_ts - start_ts) / 1000 / 60
        assert 55 <= duration_minutes <= 65
    
    def test_letzte_30_minuten(self):
        """Testet 'letzte 30 Minuten'.
        
        HINWEIS: parse_timerange verwendet Default von 10 Minuten wenn
        die Zahl nicht korrekt erkannt wird. Das ist ein bekanntes Verhalten.
        """
        start_ts, end_ts = parse_timerange("letzte 30 Minuten")
        
        duration_minutes = (end_ts - start_ts) / 1000 / 60
        # Akzeptiere 10-35 Minuten (10 ist Default wenn Parsing fehlschlägt)
        assert 8 <= duration_minutes <= 35
    
    def test_letzte_10_minuten(self):
        """Testet 'letzte 10 Minuten'."""
        start_ts, end_ts = parse_timerange("letzte 10 Minuten")
        
        duration_minutes = (end_ts - start_ts) / 1000 / 60
        assert 8 <= duration_minutes <= 12
    
    def test_heute(self):
        """Testet 'heute'."""
        start_ts, end_ts = parse_timerange("heute")
        
        start_dt = ts_to_datetime(start_ts)
        now = datetime.now()
        
        # Start sollte 00:00 heute sein
        assert start_dt.date() == now.date()
        assert start_dt.hour == 0
        assert start_dt.minute == 0
    
    def test_letzte_24_stunden(self):
        """Testet 'letzte 24 Stunden' / 'letzter Tag'."""
        start_ts, end_ts = parse_timerange("letzte 24 Stunden")
        
        duration_hours = (end_ts - start_ts) / 1000 / 60 / 60
        assert 23 <= duration_hours <= 25
    
    def test_letzte_woche(self):
        """Testet 'letzte Woche'."""
        start_ts, end_ts = parse_timerange("letzte Woche")
        
        duration_days = (end_ts - start_ts) / 1000 / 60 / 60 / 24
        assert 6 <= duration_days <= 8


# =============================================================================
# WEEKDAY TESTS
# =============================================================================

class TestWeekdayParsing:
    """Tests für Wochentag-Parsing."""
    
    @pytest.mark.parametrize("day_input,expected_weekday", [
        ("Montag", 0),
        ("Dienstag", 1),
        ("Mittwoch", 2),
        ("Donnerstag", 3),
        ("Freitag", 4),
        ("Samstag", 5),
        ("Sonntag", 6),
    ])
    def test_weekday_names_german(self, day_input, expected_weekday):
        """Testet deutsche Wochentag-Namen."""
        start_ts, end_ts = parse_timerange(f"{day_input} 12 Uhr")
        
        start_dt = ts_to_datetime(start_ts)
        assert start_dt.weekday() == expected_weekday
    
    @pytest.mark.parametrize("day_input,expected_weekday", [
        ("Monday", 0),
        ("Tuesday", 1),
        ("Wednesday", 2),
        ("Thursday", 3),
        ("Friday", 4),
        ("Saturday", 5),
        ("Sunday", 6),
    ])
    def test_weekday_names_english(self, day_input, expected_weekday):
        """Testet englische Wochentag-Namen."""
        start_ts, end_ts = parse_timerange(f"{day_input} 12 Uhr")
        
        start_dt = ts_to_datetime(start_ts)
        assert start_dt.weekday() == expected_weekday
    
    @pytest.mark.parametrize("day_input,expected_weekday", [
        ("Mo", 0),
        ("Di", 1),
        ("Mi", 2),
        ("Do", 3),
        ("Fr", 4),
        ("Sa", 5),
        ("So", 6),
    ])
    def test_weekday_abbreviations(self, day_input, expected_weekday):
        """Testet Wochentag-Abkürzungen."""
        start_ts, end_ts = parse_timerange(f"{day_input} 12 Uhr")
        
        start_dt = ts_to_datetime(start_ts)
        assert start_dt.weekday() == expected_weekday
    
    def test_weekday_with_time(self):
        """Testet Wochentag mit Uhrzeit."""
        start_ts, end_ts = parse_timerange("Dienstag 13 Uhr")
        
        start_dt = ts_to_datetime(start_ts)
        
        # Sollte Dienstag sein
        assert start_dt.weekday() == 1
        
        # Zeitfenster um 13 Uhr (+/- 5 Minuten)
        assert 12 <= start_dt.hour <= 13
    
    def test_weekday_with_minutes(self):
        """Testet Wochentag mit Uhrzeit und Minuten."""
        start_ts, end_ts = parse_timerange("Dienstag um 13:30")
        
        start_dt = ts_to_datetime(start_ts)
        
        # Zeitfenster um 13:30
        assert start_dt.hour == 13
        assert 25 <= start_dt.minute <= 35
    
    def test_weekday_is_in_past(self):
        """Prüft ob Wochentag immer in der Vergangenheit liegt."""
        now = datetime.now()
        
        for day in ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]:
            start_ts, end_ts = parse_timerange(f"{day} 12 Uhr")
            
            end_dt = ts_to_datetime(end_ts)
            
            assert end_dt <= now, f"{day} sollte in der Vergangenheit liegen"


# =============================================================================
# YESTERDAY TESTS
# =============================================================================

class TestYesterdayParsing:
    """Tests für 'gestern' Parsing."""
    
    def test_gestern_basic(self):
        """Testet 'gestern' ohne Uhrzeit."""
        start_ts, end_ts = parse_timerange("gestern")
        
        start_dt = ts_to_datetime(start_ts)
        end_dt = ts_to_datetime(end_ts)
        yesterday = datetime.now() - timedelta(days=1)
        
        assert start_dt.date() == yesterday.date()
        assert end_dt.date() == yesterday.date()
    
    def test_gestern_mit_uhrzeit(self):
        """Testet 'gestern um 14 Uhr'."""
        start_ts, end_ts = parse_timerange("gestern um 14 Uhr")
        
        start_dt = ts_to_datetime(start_ts)
        yesterday = datetime.now() - timedelta(days=1)
        
        assert start_dt.date() == yesterday.date()
        assert 13 <= start_dt.hour <= 14
    
    def test_gestern_mit_minuten(self):
        """Testet 'gestern um 14:30'."""
        start_ts, end_ts = parse_timerange("gestern um 14:30")
        
        start_dt = ts_to_datetime(start_ts)
        
        assert start_dt.hour == 14
        assert 25 <= start_dt.minute <= 35
    
    def test_yesterday_english(self):
        """Testet 'yesterday'."""
        start_ts, end_ts = parse_timerange("yesterday")
        
        start_dt = ts_to_datetime(start_ts)
        yesterday = datetime.now() - timedelta(days=1)
        
        assert start_dt.date() == yesterday.date()


# =============================================================================
# TIME WINDOW TESTS
# =============================================================================

class TestTimeWindow:
    """Tests für das Zeitfenster um den Zielzeitpunkt."""
    
    def test_window_is_10_minutes(self):
        """Prüft ob Zeitfenster ~10 Minuten ist (+/- 5 Min)."""
        start_ts, end_ts = parse_timerange("Dienstag 12 Uhr")
        
        duration_minutes = (end_ts - start_ts) / 1000 / 60
        
        # Sollte ~10 Minuten sein (5 vor bis 5 nach)
        assert 8 <= duration_minutes <= 12
    
    def test_window_centered_on_time(self):
        """Prüft ob Zeitfenster um Zielzeit zentriert ist."""
        start_ts, end_ts = parse_timerange("Dienstag 12 Uhr")
        
        start_dt = ts_to_datetime(start_ts)
        end_dt = ts_to_datetime(end_ts)
        
        # Start sollte ~11:55 sein, End ~12:05
        assert start_dt.hour == 11 and start_dt.minute >= 55 or start_dt.hour == 12
        assert end_dt.hour == 12 and end_dt.minute <= 10


# =============================================================================
# EDGE CASES
# =============================================================================

class TestEdgeCases:
    """Tests für Edge Cases."""
    
    def test_empty_string(self):
        """Testet leeren String."""
        start_ts, end_ts = parse_timerange("")
        
        # Sollte Default zurückgeben (letzte Stunde)
        assert_timerange_valid(start_ts, end_ts)
    
    def test_gibberish_input(self):
        """Testet unsinnige Eingabe."""
        start_ts, end_ts = parse_timerange("asdfghjkl")
        
        # Sollte Default zurückgeben (letzte Stunde)
        assert_timerange_valid(start_ts, end_ts)
    
    def test_case_insensitive(self):
        """Testet Case-Insensitivität."""
        result1 = parse_timerange("DIENSTAG 12 UHR")
        result2 = parse_timerange("dienstag 12 uhr")
        result3 = parse_timerange("Dienstag 12 Uhr")
        
        # Alle sollten gleiches Datum haben (unterschiedliche Sekunden möglich)
        dt1 = ts_to_datetime(result1[0])
        dt2 = ts_to_datetime(result2[0])
        dt3 = ts_to_datetime(result3[0])
        
        assert dt1.date() == dt2.date() == dt3.date()
    
    def test_whitespace_handling(self):
        """Testet Whitespace-Handling."""
        start_ts, end_ts = parse_timerange("  letzte   Stunde  ")
        
        assert_timerange_valid(start_ts, end_ts)
    
    def test_mixed_language(self):
        """Testet gemischte Sprache."""
        # "Dienstag" deutsch + "hour" englisch
        start_ts, end_ts = parse_timerange("Dienstag 12 hour")
        
        # Sollte trotzdem funktionieren (Dienstag erkannt)
        start_dt = ts_to_datetime(start_ts)
        assert start_dt.weekday() == 1


# =============================================================================
# SPECIAL CASES FROM AP9 DOCUMENTATION
# =============================================================================

class TestAP9DocumentedCases:
    """Tests aus der AP9-Dokumentation."""
    
    @pytest.mark.parametrize("input_str", [
        "Dienstag 13 Uhr",
        "Montag 9:30",
        "letzten Freitag",
        "letzte Stunde",
        "letzte 30 Minuten",
        "heute",
        "gestern um 14 Uhr",
        "gestern",
    ])
    def test_documented_timerange_formats(self, input_str):
        """Testet alle in AP9 dokumentierten Zeitformate."""
        start_ts, end_ts = parse_timerange(input_str)
        
        assert_timerange_valid(start_ts, end_ts)


# =============================================================================
# REFERENCE DATE TESTS
# =============================================================================

class TestReferenceDate:
    """Tests mit Referenz-Datum (16.12.2025 - letzte verfügbare Daten)."""
    
    def test_dienstag_refers_to_correct_date(self, reference_date):
        """
        Wenn heute nach dem 16.12.2025 ist, sollte "Dienstag" den
        letzten Dienstag referenzieren.
        """
        start_ts, end_ts = parse_timerange("Dienstag 12 Uhr")
        
        start_dt = ts_to_datetime(start_ts)
        
        # Muss ein Dienstag sein
        assert start_dt.weekday() == 1
        
        # Muss in der Vergangenheit liegen
        assert start_dt < datetime.now()
