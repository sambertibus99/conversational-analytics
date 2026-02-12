"""
Tests für DuckDB SessionStore (DEC-025).

Testet:
1. Lifecycle (create, get, destroy)
2. Daten speichern (ThingsBoard-Formate)
3. Daten lesen (query, get_values, get_timeseries)
4. UNS-Key-Generator
5. Edge Cases
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pytest
from datetime import datetime, timedelta

from config.duckdb_store import (
    SessionStore,
    generate_dataset_key,
    determine_signal_type,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture(autouse=True)
def cleanup_stores():
    """Räumt alle SessionStore-Instanzen nach jedem Test auf."""
    yield
    SessionStore.destroy_all()


@pytest.fixture
def store():
    """Erstellt einen frischen SessionStore."""
    return SessionStore.get_instance("test-session")


@pytest.fixture
def sample_timeseries():
    """ThingsBoard Zeitreihen-Daten."""
    base_ts = int(datetime(2025, 12, 16, 12, 0, 0).timestamp() * 1000)
    return {
        "torque_act_a1_nm": [
            {"value": str(25.0 + i * 0.1), "timestamp": base_ts + i * 1000}
            for i in range(50)
        ],
        "torque_act_a2_nm": [
            {"value": str(15.0 + i * 0.05), "timestamp": base_ts + i * 1000}
            for i in range(50)
        ],
    }


@pytest.fixture
def sample_latest():
    """ThingsBoard Latest-Telemetry-Daten."""
    return {
        "axis_act_a1_deg": {
            "value": "25.34",
            "timestamp": 1734364596000,
        },
        "vel_act_m_per_s": {
            "value": "0.0",
            "timestamp": 1734364596000,
        },
    }


# =============================================================================
# LIFECYCLE TESTS
# =============================================================================

class TestSessionStoreLifecycle:
    """Tests für SessionStore Lifecycle."""

    def test_get_instance_creates_new(self):
        """Neue Instanz wird erstellt."""
        store = SessionStore.get_instance("session-1")
        assert store is not None
        assert store.session_id == "session-1"

    def test_get_instance_returns_same(self):
        """Gleiche Session-ID gibt gleiche Instanz zurück."""
        store1 = SessionStore.get_instance("session-1")
        store2 = SessionStore.get_instance("session-1")
        assert store1 is store2

    def test_different_sessions_are_isolated(self, sample_timeseries):
        """Verschiedene Sessions teilen keine Daten."""
        store1 = SessionStore.get_instance("session-1")
        store2 = SessionStore.get_instance("session-2")

        store1.store_dataset("test/data", sample_timeseries)

        assert store1.point_count() == 100  # 50 + 50
        assert store2.point_count() == 0

    def test_destroy_removes_instance(self):
        """Destroy entfernt die Instanz."""
        SessionStore.get_instance("session-1")
        assert "session-1" in SessionStore._instances

        SessionStore.destroy("session-1")
        assert "session-1" not in SessionStore._instances

    def test_destroy_all(self):
        """Destroy all räumt alles auf."""
        SessionStore.get_instance("s1")
        SessionStore.get_instance("s2")
        SessionStore.get_instance("s3")

        SessionStore.destroy_all()
        assert len(SessionStore._instances) == 0

    def test_destroy_nonexistent_no_error(self):
        """Destroy einer nicht existierenden Session wirft keinen Fehler."""
        SessionStore.destroy("nonexistent")  # Sollte nicht crashen


# =============================================================================
# STORE DATASET TESTS
# =============================================================================

class TestStoreDataset:
    """Tests für store_dataset()."""

    def test_store_timeseries(self, store, sample_timeseries):
        """Speichert Zeitreihen-Daten korrekt."""
        count = store.store_dataset("krc5/torque/timeseries/2h", sample_timeseries)
        assert count == 100  # 50 + 50 Punkte

    def test_store_latest(self, store, sample_latest):
        """Speichert Latest-Telemetry korrekt."""
        count = store.store_dataset("krc5/axis/latest", sample_latest)
        assert count == 2  # 2 Keys mit je 1 Wert

    def test_store_with_ts_key(self, store):
        """Unterstützt 'ts' statt 'timestamp' Key."""
        data = {
            "key1": [
                {"value": "10.0", "ts": 1000},
                {"value": "20.0", "ts": 2000},
            ]
        }
        count = store.store_dataset("test/ts", data)
        assert count == 2

    def test_store_upsert_accumulates(self, store, sample_timeseries):
        """UPSERT akkumuliert Daten bei gleichem dataset_key (DEC-026)."""
        store.store_dataset("test/data", sample_timeseries)
        assert store.point_count("test/data") == 100

        # Neues Dataset unter gleichem Key mit anderer signal_key → akkumuliert
        small_data = {"key1": [{"value": "1.0", "timestamp": 1000}]}
        store.store_dataset("test/data", small_data)
        assert store.point_count("test/data") == 101  # 100 + 1

    def test_store_upsert_replaces_same_pk(self, store):
        """UPSERT ersetzt bei gleichem PK (dataset_key, signal_key, ts)."""
        data1 = {"key1": [{"value": "10.0", "timestamp": 1000}]}
        store.store_dataset("test/data", data1)
        assert store.get_values("test/data", "key1") == [10.0]

        # Gleicher PK, neuer Wert → wird ersetzt
        data2 = {"key1": [{"value": "99.0", "timestamp": 1000}]}
        store.store_dataset("test/data", data2)
        assert store.point_count("test/data") == 1
        assert store.get_values("test/data", "key1") == [99.0]

    def test_clear_dataset_then_store(self, store, sample_timeseries):
        """clear_dataset + store ersetzt komplett (explizites Overwrite)."""
        store.store_dataset("test/data", sample_timeseries)
        assert store.point_count("test/data") == 100

        store.clear_dataset("test/data")
        small_data = {"key1": [{"value": "1.0", "timestamp": 1000}]}
        store.store_dataset("test/data", small_data)
        assert store.point_count("test/data") == 1

    def test_store_invalid_values_skipped(self, store):
        """Ungültige Werte werden übersprungen."""
        data = {
            "key1": [
                {"value": "25.0", "timestamp": 1000},   # valid
                {"value": "NaN", "timestamp": 2000},     # skipped (can't float)
                {"value": "error", "timestamp": 3000},   # skipped
                {"value": "30.0", "timestamp": 4000},    # valid
            ]
        }
        count = store.store_dataset("test/mixed", data)
        assert count == 2

    def test_store_empty_data(self, store):
        """Leere Daten geben 0 zurück."""
        count = store.store_dataset("test/empty", {})
        assert count == 0

    def test_store_with_unit(self, store, sample_timeseries):
        """Einheit wird korrekt gespeichert."""
        store.store_dataset("test/unit", sample_timeseries, unit="Nm")
        rows = store.query(
            "SELECT DISTINCT unit FROM telemetry WHERE dataset_key = ?",
            ["test/unit"],
        )
        assert rows[0][0] == "Nm"


# =============================================================================
# QUERY TESTS
# =============================================================================

class TestQueryMethods:
    """Tests für Abfrage-Methoden."""

    def test_get_values(self, store, sample_timeseries):
        """get_values gibt korrekte Werte zurück."""
        store.store_dataset("test/data", sample_timeseries)
        values = store.get_values("test/data", "torque_act_a1_nm")
        assert len(values) == 50
        assert values[0] == pytest.approx(25.0, abs=0.01)
        assert values[-1] == pytest.approx(25.0 + 49 * 0.1, abs=0.01)

    def test_get_values_sorted_by_timestamp(self, store):
        """Werte sind nach Timestamp sortiert."""
        data = {
            "key1": [
                {"value": "30.0", "timestamp": 3000},
                {"value": "10.0", "timestamp": 1000},
                {"value": "20.0", "timestamp": 2000},
            ]
        }
        store.store_dataset("test/sort", data)
        values = store.get_values("test/sort", "key1")
        assert values == [10.0, 20.0, 30.0]

    def test_get_values_nonexistent(self, store):
        """Nicht existierende Keys geben leere Liste."""
        values = store.get_values("nonexistent", "key")
        assert values == []

    def test_get_timeseries(self, store, sample_timeseries):
        """get_timeseries gibt Timestamps und Werte."""
        store.store_dataset("test/data", sample_timeseries)
        timestamps, values = store.get_timeseries("test/data", "torque_act_a1_nm")
        assert len(timestamps) == 50
        assert len(values) == 50
        # Timestamps steigen monoton
        for i in range(1, len(timestamps)):
            assert timestamps[i] > timestamps[i - 1]

    def test_get_signal_keys(self, store, sample_timeseries):
        """get_signal_keys gibt alle Signal-Keys zurück."""
        store.store_dataset("test/data", sample_timeseries)
        keys = store.get_signal_keys("test/data")
        assert sorted(keys) == ["torque_act_a1_nm", "torque_act_a2_nm"]

    def test_list_datasets(self, store, sample_timeseries, sample_latest):
        """list_datasets gibt Übersicht aller Datasets."""
        store.store_dataset("krc5/torque/timeseries", sample_timeseries)
        store.store_dataset("krc5/axis/latest", sample_latest)

        datasets = store.list_datasets()
        assert len(datasets) == 2

        # Finde das Timeseries-Dataset
        ts_ds = next(d for d in datasets if d["dataset_key"] == "krc5/torque/timeseries")
        assert ts_ds["signal_count"] == 2
        assert ts_ds["point_count"] == 100

    def test_get_all_signal_data(self, store, sample_timeseries):
        """get_all_signal_data gibt ThingsBoard-Format zurück."""
        store.store_dataset("test/data", sample_timeseries)
        data = store.get_all_signal_data("test/data")

        assert "torque_act_a1_nm" in data
        assert "torque_act_a2_nm" in data
        assert len(data["torque_act_a1_nm"]) == 50

        # Prüfe Format
        point = data["torque_act_a1_nm"][0]
        assert "value" in point
        assert "timestamp" in point

    def test_get_all_data_merged(self, store, sample_timeseries, sample_latest):
        """get_all_data_merged kombiniert alle Datasets."""
        store.store_dataset("ds1", sample_timeseries)
        store.store_dataset("ds2", sample_latest)

        merged = store.get_all_data_merged()
        assert "torque_act_a1_nm" in merged
        assert "axis_act_a1_deg" in merged

    def test_query_raw_sql(self, store, sample_timeseries):
        """Direkte SQL-Abfrage funktioniert."""
        store.store_dataset("test/data", sample_timeseries)

        result = store.query(
            "SELECT AVG(value) FROM telemetry WHERE signal_key = ?",
            ["torque_act_a1_nm"],
        )
        avg = result[0][0]
        assert avg == pytest.approx(25.0 + 24.5 * 0.1, abs=0.1)

    def test_query_df(self, store, sample_timeseries):
        """DataFrame-Abfrage funktioniert."""
        store.store_dataset("test/data", sample_timeseries)

        df = store.query_df(
            "SELECT signal_key, COUNT(*) as cnt FROM telemetry GROUP BY signal_key"
        )
        assert len(df) == 2
        assert "signal_key" in df.columns
        assert "cnt" in df.columns

    def test_point_count_all(self, store, sample_timeseries):
        """point_count() ohne Key gibt Gesamtzahl."""
        store.store_dataset("test/data", sample_timeseries)
        assert store.point_count() == 100

    def test_point_count_specific(self, store, sample_timeseries, sample_latest):
        """point_count() mit Key gibt Dataset-Zahl."""
        store.store_dataset("ds1", sample_timeseries)
        store.store_dataset("ds2", sample_latest)
        assert store.point_count("ds1") == 100
        assert store.point_count("ds2") == 2


# =============================================================================
# UNS-KEY GENERATOR TESTS
# =============================================================================

class TestUNSKeyGenerator:
    """Tests für generate_dataset_key()."""

    def test_basic_key(self):
        """Basis-Key-Generierung."""
        key = generate_dataset_key("krc5", "torque", "timeseries", "2h")
        assert key == "krc5/torque/timeseries/2h"

    def test_no_temporal(self):
        """Key ohne zeitliche Komponente."""
        key = generate_dataset_key("krc5", "position", "latest")
        assert key == "krc5/position/latest"

    def test_lowercase(self):
        """Keys werden automatisch kleingeschrieben."""
        key = generate_dataset_key("KRC5", "Torque", "TIMESERIES", "2H")
        assert key == "krc5/torque/timeseries/2h"

    def test_determine_signal_type_torque(self):
        """Erkennt Drehmoment-Keys via telemetry_lookup.json."""
        assert determine_signal_type(["torque_act_a1_nm"]) == "torque_actual"

    def test_determine_signal_type_torque_cmd(self):
        """Erkennt Soll-Drehmoment-Keys."""
        assert determine_signal_type(["torque_cmd_a1_nm"]) == "torque_commanded"

    def test_determine_signal_type_velocity(self):
        """Erkennt Geschwindigkeits-Keys."""
        assert determine_signal_type(["vel_act_m_per_s"]) == "velocity_tcp"

    def test_determine_signal_type_velocity_axis(self):
        """Erkennt Achsgeschwindigkeits-Keys."""
        assert determine_signal_type(["vel_axis_a1_pct"]) == "velocity_axis"

    def test_determine_signal_type_position(self):
        """Erkennt kartesische Position-Keys."""
        assert determine_signal_type(["pos_act_x_mm"]) == "cartesian_position"

    def test_determine_signal_type_axis(self):
        """Erkennt Achsposition-Keys."""
        assert determine_signal_type(["axis_act_a1_deg"]) == "axis_position"

    def test_determine_signal_type_torqmon(self):
        """Erkennt Momentenüberwachung-Keys."""
        assert determine_signal_type(["torqmon_a1_pct"]) == "torque_monitoring"

    def test_determine_signal_type_utilization(self):
        """Erkennt Auslastungs-Keys."""
        assert determine_signal_type(["utilization_current"]) == "utilization"

    def test_determine_signal_type_energy(self):
        """Erkennt Energie-Keys."""
        assert determine_signal_type(["energy_period_kwh"]) == "energy"

    def test_determine_signal_type_unknown(self):
        """Fallback für unbekannte Keys."""
        assert determine_signal_type(["custom_sensor_val"]) == "custom"

    def test_determine_signal_type_empty(self):
        """Leere Liste gibt 'unknown'."""
        assert determine_signal_type([]) == "unknown"

    # === DEC-026: Erweiterte Key-Generierung ===

    def test_key_with_data_mode(self):
        """Key mit data_mode (DEC-026)."""
        key = generate_dataset_key("krc5", "torque", "timeseries", data_mode="overview")
        assert key == "krc5/torque/timeseries/overview"

    def test_key_with_mode_and_time_range(self):
        """Key mit data_mode und time_range (DEC-026)."""
        key = generate_dataset_key(
            "krc5", "torque", "timeseries",
            data_mode="overview",
            time_range="2025-12-16_12-00_14-00",
        )
        assert key == "krc5/torque/timeseries/overview/2025-12-16_12-00_14-00"

    def test_key_full_rich(self):
        """Vollständiger Rich-Key (DEC-026)."""
        key = generate_dataset_key(
            "krc5", "torque", "timeseries",
            data_mode="overview",
            time_range="2025-12-16_12-00_14-00",
            interval_agg="60s_avg",
        )
        assert key == "krc5/torque/timeseries/overview/2025-12-16_12-00_14-00/60s_avg"

    def test_key_interval_agg_overrides_temporal(self):
        """interval_agg hat Vorrang vor temporal (DEC-026)."""
        key = generate_dataset_key(
            "krc5", "torque", "timeseries",
            temporal="2h",
            interval_agg="60s_avg",
        )
        assert key == "krc5/torque/timeseries/60s_avg"

    def test_key_detail_mode(self):
        """Key mit detail mode (DEC-026)."""
        key = generate_dataset_key(
            "krc5", "torque", "timeseries",
            data_mode="detail",
            time_range="2025-12-16_12-00_14-00",
        )
        assert key == "krc5/torque/timeseries/detail/2025-12-16_12-00_14-00"


# =============================================================================
# CLEAR_DATASET TESTS (DEC-026)
# =============================================================================

class TestClearDataset:
    """Tests für clear_dataset() (DEC-026)."""

    def test_clear_dataset_removes_only_target(self, store, sample_timeseries, sample_latest):
        """clear_dataset entfernt nur das Ziel-Dataset."""
        store.store_dataset("ds1", sample_timeseries)
        store.store_dataset("ds2", sample_latest)
        assert store.point_count() == 102

        store.clear_dataset("ds1")
        assert store.point_count("ds1") == 0
        assert store.point_count("ds2") == 2

    def test_clear_dataset_nonexistent_no_error(self, store):
        """clear_dataset auf nicht-existierenden Key wirft keinen Fehler."""
        store.clear_dataset("nonexistent")


# =============================================================================
# DUCKDB SQL FEATURES
# =============================================================================

class TestDuckDBFeatures:
    """Tests für DuckDB-spezifische Features (z.B. ASOF JOIN)."""

    def test_asof_join(self, store):
        """ASOF JOIN für Zeitreihen-Korrelation."""
        # Sensor X: Timestamps 1000, 2000, 3000, 4000, 5000
        data_x = {
            "sensor_x": [
                {"value": str(i * 10.0), "timestamp": i * 1000}
                for i in range(1, 6)
            ]
        }
        # Sensor Y: Leicht versetzte Timestamps
        data_y = {
            "sensor_y": [
                {"value": str(i * 5.0 + 2), "timestamp": i * 1000 + 50}
                for i in range(1, 5)  # Nur 4 Punkte
            ]
        }

        store.store_dataset("ds_x", data_x)
        store.store_dataset("ds_y", data_y)

        # ASOF JOIN mit Subqueries (nötig weil gleiche Tabelle)
        result = store.query("""
            SELECT
                x.ts AS ts_x,
                x.value AS val_x,
                y.ts AS ts_y,
                y.value AS val_y
            FROM (SELECT ts, value FROM telemetry WHERE signal_key = 'sensor_x') x
            ASOF JOIN (SELECT ts, value FROM telemetry WHERE signal_key = 'sensor_y') y
                ON x.ts >= y.ts
            ORDER BY x.ts
        """)

        assert len(result) >= 3  # Mindestens 3 Matches
