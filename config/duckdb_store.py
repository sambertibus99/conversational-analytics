"""
DuckDB-basierter In-Memory Datenspeicher für Session-Daten.

Ersetzt die direkte Speicherung von Rohdaten im AgentState.
Pro Chat-Session wird eine eigene DuckDB-Instanz erstellt.

DESIGN-ENTSCHEIDUNGEN:
- DEC-025: Reference-only State — Rohdaten in DuckDB, nur Metadaten im State
- Singleton pro Session via class-level Registry
- UNS-inspirierte Dataset-Keys für Multi-Device-Fähigkeit

Schema:
    telemetry(
        dataset_key TEXT,    -- UNS-Key: "krc5/torque/timeseries/2h"
        signal_key  TEXT,    -- ThingsBoard Key: "torque_act_a1_nm"
        ts          BIGINT,  -- Timestamp in Millisekunden
        value       DOUBLE,  -- Messwert
        unit        TEXT     -- Einheit: "Nm", "deg", etc.
    )
"""

import math
import logging
from typing import Any

import duckdb

logger = logging.getLogger(__name__)


def _is_finite(value: float) -> bool:
    """Prüft ob ein float-Wert endlich ist (kein NaN/Inf)."""
    return math.isfinite(value)


def _parse_numeric_value(raw: Any) -> float | None:
    """
    Parst einen Rohwert zu float, gibt None für ungültige Werte zurück.

    Filtert: NaN, Inf, Fehlermeldungen, leere Strings.
    """
    if raw is None:
        return None

    if isinstance(raw, (int, float)):
        return float(raw) if _is_finite(raw) else None

    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return None
        # Schneller Check auf bekannte Fehlermuster
        raw_lower = raw.lower()
        if raw_lower in ("nan", "inf", "-inf", "null", "none"):
            return None
        if any(p in raw_lower for p in ("error", "bad status", "unavailable")):
            return None
        try:
            val = float(raw)
            return val if _is_finite(val) else None
        except (ValueError, TypeError):
            return None

    return None


class SessionStore:
    """
    In-Memory DuckDB Store für eine Chat-Session.

    Verwendung:
        store = SessionStore.get_instance(session_id)
        store.store_dataset("krc5/torque/timeseries/2h", data_dict)
        df = store.query("SELECT AVG(value) FROM telemetry WHERE signal_key = 'torque_act_a1_nm'")
        values = store.get_values("krc5/torque/timeseries/2h", "torque_act_a1_nm")
    """

    # Registry: session_id -> SessionStore
    _instances: dict[str, "SessionStore"] = {}

    def __init__(self, session_id: str):
        self._session_id = session_id
        self._conn = duckdb.connect(":memory:")
        self._in_use = False  # Schutz gegen Destroy während Pipeline läuft
        self._init_schema()
        logger.info(f"SessionStore erstellt: {session_id}")

    def _init_schema(self) -> None:
        """Erstellt das Telemetrie- und Statistik-Schema."""
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS telemetry (
                dataset_key TEXT NOT NULL,
                signal_key  TEXT NOT NULL,
                ts          BIGINT NOT NULL,
                value       DOUBLE NOT NULL,
                unit        TEXT DEFAULT '',
                PRIMARY KEY (dataset_key, signal_key, ts)
            )
        """)
        # DEC-030: Eigene Tabelle für Stats-Ergebnisse (keine Zeitreihen, JSON-Struktur)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS statistics (
                dataset_key   TEXT PRIMARY KEY,
                analysis_type TEXT NOT NULL,
                result        TEXT NOT NULL,
                metadata      TEXT,
                created_at    BIGINT NOT NULL
            )
        """)

    # =================================================================
    # LIFECYCLE (Class-Level Registry)
    # =================================================================

    @classmethod
    def get_instance(cls, session_id: str = "default") -> "SessionStore":
        """Holt oder erstellt eine SessionStore-Instanz."""
        if session_id not in cls._instances:
            cls._instances[session_id] = cls(session_id)
        return cls._instances[session_id]

    @classmethod
    def destroy(cls, session_id: str) -> None:
        """Zerstört eine Session und gibt Speicher frei."""
        if session_id in cls._instances:
            store = cls._instances[session_id]
            if store._in_use:
                logger.warning(f"SessionStore {session_id} ist in Benutzung — überspringe Destroy")
                return
            cls._instances.pop(session_id)
            store.close()
            logger.info(f"SessionStore zerstört: {session_id}")

    @classmethod
    def destroy_all(cls) -> None:
        """Zerstört alle Sessions die nicht in Benutzung sind."""
        for session_id in list(cls._instances.keys()):
            cls.destroy(session_id)

    def acquire(self) -> None:
        """Markiert den Store als in Benutzung (Schutz gegen Destroy)."""
        self._in_use = True

    def release(self) -> None:
        """Gibt den Store wieder frei."""
        self._in_use = False

    def clear(self) -> None:
        """Löscht alle Daten, behält Schema und Instanz."""
        self._conn.execute("DELETE FROM telemetry")
        self._conn.execute("DELETE FROM statistics")
        logger.info(f"SessionStore geleert: {self._session_id}")

    def clear_dataset(self, dataset_key: str) -> None:
        """Löscht alle Daten für einen dataset_key."""
        self._conn.execute("DELETE FROM telemetry WHERE dataset_key = ?", [dataset_key])

    def close(self) -> None:
        """Schließt die DuckDB-Verbindung."""
        try:
            self._conn.close()
        except Exception:
            pass

    # =================================================================
    # DATEN SCHREIBEN
    # =================================================================

    def store_dataset(
        self,
        dataset_key: str,
        data: dict[str, list],
        unit: str = "",
    ) -> int:
        """
        Speichert ThingsBoard-Daten in DuckDB.

        Args:
            dataset_key: UNS-Key, z.B. "krc5/torque/timeseries/2h"
            data: ThingsBoard-Format:
                  {"torque_act_a1_nm": [{"value": "25.3", "ts": 123}, ...]}
                  oder {"key": [{"value": "25.3", "timestamp": 123}, ...]}
                  oder {"key": {"value": "25.3", "timestamp": 123}} (latest)
            unit: Einheit der Messwerte

        Returns:
            Anzahl eingefügter Zeilen
        """
        rows = []

        for signal_key, values in data.items():
            if isinstance(values, list):
                for point in values:
                    if isinstance(point, dict) and "value" in point:
                        ts = point.get("ts") or point.get("timestamp", 0)
                        val = _parse_numeric_value(point["value"])
                        if val is not None:
                            rows.append((dataset_key, signal_key, int(ts), val, unit))
                    elif isinstance(point, (int, float)) and _is_finite(point):
                        rows.append((dataset_key, signal_key, 0, float(point), unit))

            elif isinstance(values, dict) and "value" in values:
                # Latest-Telemetry: einzelner Wert
                ts = values.get("ts") or values.get("timestamp", 0)
                val = _parse_numeric_value(values["value"])
                if val is not None:
                    rows.append((dataset_key, signal_key, int(ts), val, unit))

        if not rows:
            logger.warning(f"Keine gültigen Daten für dataset_key={dataset_key}")
            return 0

        # UPSERT: Bei gleichem PK (dataset_key, signal_key, ts) wird value/unit aktualisiert
        self._conn.executemany(
            "INSERT OR REPLACE INTO telemetry (dataset_key, signal_key, ts, value, unit) VALUES (?, ?, ?, ?, ?)",
            rows,
        )

        logger.debug(f"store_dataset: {dataset_key} → {len(rows)} Zeilen, {len(data)} signals")
        return len(rows)

    # =================================================================
    # DATEN LESEN
    # =================================================================

    def query(self, sql: str, params: list | None = None) -> list[tuple]:
        """
        Führt ein read-only SQL-Query aus.

        Args:
            sql: SQL-Abfrage
            params: Optionale Parameter für Prepared Statements

        Returns:
            Liste von Tupeln
        """
        if params:
            return self._conn.execute(sql, params).fetchall()
        return self._conn.execute(sql).fetchall()

    def query_df(self, sql: str, params: list | None = None):
        """Führt SQL aus und gibt DataFrame zurück."""
        if params:
            return self._conn.execute(sql, params).fetchdf()
        return self._conn.execute(sql).fetchdf()

    def get_values(
        self,
        dataset_key: str,
        signal_key: str,
    ) -> list[float]:
        """
        Gibt Werte für einen bestimmten Signal-Key zurück.

        Args:
            dataset_key: UNS-Key des Datasets
            signal_key: ThingsBoard Signal-Key

        Returns:
            Liste von float-Werten (zeitlich sortiert)
        """
        rows = self._conn.execute(
            "SELECT value FROM telemetry WHERE dataset_key = ? AND signal_key = ? ORDER BY ts",
            [dataset_key, signal_key],
        ).fetchall()
        return [r[0] for r in rows]

    def get_timeseries(
        self,
        dataset_key: str,
        signal_key: str,
    ) -> tuple[list[int], list[float]]:
        """
        Gibt Timestamps und Werte für einen Signal-Key zurück.

        Returns:
            Tuple von (timestamps, values) — beide zeitlich sortiert
        """
        rows = self._conn.execute(
            "SELECT ts, value FROM telemetry WHERE dataset_key = ? AND signal_key = ? ORDER BY ts",
            [dataset_key, signal_key],
        ).fetchall()
        if not rows:
            return [], []
        timestamps = [r[0] for r in rows]
        values = [r[1] for r in rows]
        return timestamps, values

    def get_signal_keys(self, dataset_key: str) -> list[str]:
        """Gibt alle Signal-Keys für ein Dataset zurück."""
        rows = self._conn.execute(
            "SELECT DISTINCT signal_key FROM telemetry WHERE dataset_key = ?",
            [dataset_key],
        ).fetchall()
        return [r[0] for r in rows]

    def list_datasets(self) -> list[dict[str, Any]]:
        """
        Gibt eine Übersicht aller gespeicherten Datasets zurück.

        Returns:
            Liste von Dicts: [{"dataset_key": ..., "signal_count": ..., "point_count": ..., "timerange": {...}}]
        """
        rows = self._conn.execute("""
            SELECT
                dataset_key,
                COUNT(DISTINCT signal_key) AS signal_count,
                COUNT(*) AS point_count,
                MIN(ts) AS min_ts,
                MAX(ts) AS max_ts
            FROM telemetry
            GROUP BY dataset_key
        """).fetchall()

        result = []
        for row in rows:
            result.append({
                "dataset_key": row[0],
                "signal_count": row[1],
                "point_count": row[2],
                "timerange": {"start_ts": row[3], "end_ts": row[4]},
            })
        return result

    def get_all_signal_data(self, dataset_key: str) -> dict[str, list[dict]]:
        """
        Gibt alle Daten für ein Dataset im ThingsBoard-Format zurück.

        Nützlich für Viz Agent, der das Daten-Format für Chart-Transformationen braucht.

        Returns:
            {"signal_key": [{"value": ..., "timestamp": ...}, ...], ...}
        """
        rows = self._conn.execute(
            "SELECT signal_key, ts, value FROM telemetry WHERE dataset_key = ? ORDER BY signal_key, ts",
            [dataset_key],
        ).fetchall()

        result: dict[str, list[dict]] = {}
        for signal_key, ts, value in rows:
            if signal_key not in result:
                result[signal_key] = []
            result[signal_key].append({"value": str(value), "timestamp": ts})
        return result

    def get_data_for_datasets(self, dataset_keys: list[str]) -> dict[str, list[dict]]:
        """
        Gibt Daten NUR für die angegebenen dataset_keys zurück (DEC-026).

        Falls dataset_keys leer ist, Fallback auf alle Daten.

        Returns:
            {"signal_key": [{"value": ..., "timestamp": ...}, ...], ...}
        """
        if not dataset_keys:
            return self.get_all_data_merged()

        placeholders = ", ".join(["?"] * len(dataset_keys))
        rows = self._conn.execute(
            f"SELECT signal_key, ts, value FROM telemetry "
            f"WHERE dataset_key IN ({placeholders}) ORDER BY signal_key, ts",
            dataset_keys,
        ).fetchall()

        result: dict[str, list[dict]] = {}
        for signal_key, ts, value in rows:
            if signal_key not in result:
                result[signal_key] = []
            result[signal_key].append({"value": str(value), "timestamp": ts})
        return result

    def get_all_data_merged(self) -> dict[str, list[dict]]:
        """
        Gibt alle Daten über alle Datasets gemergt im ThingsBoard-Format zurück.

        Nützlich als Drop-in-Ersatz für extract_data_from_datasets().

        Returns:
            {"signal_key": [{"value": ..., "timestamp": ...}, ...], ...}
        """
        rows = self._conn.execute(
            "SELECT signal_key, ts, value FROM telemetry ORDER BY signal_key, ts"
        ).fetchall()

        result: dict[str, list[dict]] = {}
        for signal_key, ts, value in rows:
            if signal_key not in result:
                result[signal_key] = []
            result[signal_key].append({"value": str(value), "timestamp": ts})
        return result

    # =================================================================
    # STATISTIK-DATEN SCHREIBEN/LESEN (DEC-030)
    # =================================================================

    def store_statistics(
        self,
        dataset_key: str,
        analysis_type: str,
        result: dict,
        metadata: dict | None = None,
    ) -> None:
        """
        Speichert ein Stats-Ergebnis in DuckDB (DEC-030).

        Args:
            dataset_key: UNS-Key, z.B. "krc5/stats/correlation/pos_act_z_mm-axis_act_a1_deg/..."
            analysis_type: "correlation", "mean", "std", etc.
            result: Das Berechnungsergebnis als Dict
            metadata: Optionale Metadaten (Source-Keys, Zeitraum, etc.)
        """
        import json as _json
        import time

        self._conn.execute(
            "INSERT OR REPLACE INTO statistics (dataset_key, analysis_type, result, metadata, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                dataset_key,
                analysis_type,
                _json.dumps(result, ensure_ascii=False),
                _json.dumps(metadata, ensure_ascii=False) if metadata else None,
                int(time.time() * 1000),
            ],
        )
        logger.debug(f"store_statistics: {dataset_key} ({analysis_type})")

    def get_statistics(self, dataset_key: str) -> dict | None:
        """
        Liest ein Stats-Ergebnis aus DuckDB (DEC-030).

        Returns:
            Dict mit "analysis_type", "result", "metadata" oder None
        """
        import json as _json

        rows = self._conn.execute(
            "SELECT analysis_type, result, metadata FROM statistics WHERE dataset_key = ?",
            [dataset_key],
        ).fetchall()

        if not rows:
            return None

        row = rows[0]
        return {
            "analysis_type": row[0],
            "result": _json.loads(row[1]),
            "metadata": _json.loads(row[2]) if row[2] else None,
        }

    def get_statistics_as_chart_data(self, dataset_key: str) -> dict[str, list[dict]]:
        """
        Konvertiert ein Stats-Ergebnis zu ThingsBoard-Format für den Viz Agent (DEC-030).

        Korrelation: {"axis_act_a1_deg": [{"value": "-0.664", "timestamp": 0}], ...}
        Mean/Std/etc.: {"torque_act_a1_nm": [{"value": "25.3", "timestamp": 0}]}

        Returns:
            Dict im ThingsBoard-Format oder leeres Dict
        """
        entry = self.get_statistics(dataset_key)
        if not entry:
            return {}

        result = entry["result"]
        analysis_type = entry["analysis_type"]

        # Korrelation: result enthält key_x, key_y, r
        if analysis_type == "correlation" and "r" in result:
            key_y = result.get("key_y", "correlation")
            return {key_y: [{"value": str(result["r"]), "timestamp": 0}]}

        # Einzelwert-Stats (mean, std, min_max, trend, percentiles, anomaly, summary)
        key = result.get("key", "value")

        if "mean" in result:
            return {key: [{"value": str(result["mean"]), "timestamp": 0}]}
        if "std" in result:
            return {key: [{"value": str(result["std"]), "timestamp": 0}]}
        if "min" in result and "max" in result:
            return {
                f"{key}_min": [{"value": str(result["min"]), "timestamp": 0}],
                f"{key}_max": [{"value": str(result["max"]), "timestamp": 0}],
            }
        if "slope" in result:
            return {key: [{"value": str(result["slope"]), "timestamp": 0}]}

        return {}

    def get_multi_statistics_as_chart_data(self, dataset_keys: list[str]) -> dict[str, list[dict]]:
        """
        Konvertiert mehrere Stats-Ergebnisse zu einem kombinierten ThingsBoard-Format (DEC-030).

        Typisch für Korrelation: Mehrere Paare → ein Chart mit allen Werten.

        Returns:
            Kombiniertes Dict im ThingsBoard-Format
        """
        merged: dict[str, list[dict]] = {}
        for dk in dataset_keys:
            data = self.get_statistics_as_chart_data(dk)
            merged.update(data)
        return merged

    def list_statistics(self) -> list[dict]:
        """
        Gibt eine Übersicht aller gespeicherten Stats-Datasets zurück (DEC-030).

        Returns:
            Liste von Dicts: [{"dataset_key": ..., "analysis_type": ..., "created_at": ...}]
        """
        rows = self._conn.execute(
            "SELECT dataset_key, analysis_type, created_at FROM statistics ORDER BY created_at DESC"
        ).fetchall()

        return [
            {"dataset_key": row[0], "analysis_type": row[1], "created_at": row[2]}
            for row in rows
        ]

    def point_count(self, dataset_key: str | None = None) -> int:
        """Gibt die Anzahl der gespeicherten Datenpunkte zurück."""
        if dataset_key:
            return self._conn.execute(
                "SELECT COUNT(*) FROM telemetry WHERE dataset_key = ?",
                [dataset_key],
            ).fetchone()[0]
        return self._conn.execute("SELECT COUNT(*) FROM telemetry").fetchone()[0]

    @property
    def session_id(self) -> str:
        return self._session_id


# =============================================================================
# UNS-KEY GENERATOR
# =============================================================================

def generate_dataset_key(
    device_id: str,
    signal_type: str,
    data_type: str = "timeseries",
    temporal: str = "",
    data_mode: str = "",
    time_range: str = "",
    interval_agg: str = "",
) -> str:
    """
    Generiert einen UNS-inspirierten Dataset-Key.

    Format: "{device}/{signal_type}/{data_type}[/{data_mode}][/{time_range}][/{interval_agg|temporal}]"

    Beispiele:
        generate_dataset_key("krc5", "torque", "timeseries", "2h")
        → "krc5/torque/timeseries/2h"

        generate_dataset_key("krc5", "torque", "timeseries",
            data_mode="overview", time_range="2025-12-16_12-00_14-00", interval_agg="60s_avg")
        → "krc5/torque/timeseries/overview/2025-12-16_12-00_14-00/60s_avg"

        generate_dataset_key("krc5", "position", "latest")
        → "krc5/position/latest"

    Args:
        device_id: Geräte-ID (z.B. "krc5")
        signal_type: Art des Signals (z.B. "torque", "position", "velocity")
        data_type: "timeseries" | "latest" | "availability"
        temporal: Zeitlicher Hinweis (z.B. "2h", "24h", "dienstag") — Legacy, wird von interval_agg abgelöst
        data_mode: "detail" | "overview" (DEC-026)
        time_range: Zeitraum-String (z.B. "2025-12-16_12-00_14-00") (DEC-026)
        interval_agg: Intervall + Aggregation (z.B. "60s_avg", "300s_max") (DEC-026)
    """
    parts = [device_id.lower(), signal_type.lower(), data_type.lower()]
    if data_mode:
        parts.append(data_mode.lower())
    if time_range:
        parts.append(time_range.lower())
    if interval_agg:
        parts.append(interval_agg.lower())
    elif temporal:
        parts.append(temporal.lower())
    return "/".join(parts)


def generate_stats_dataset_key(
    device_id: str,
    analysis_type: str,
    reference_key: str,
    time_range: str = "",
) -> str:
    """
    Generiert einen UNS-Key für Stats-Ergebnisse (DEC-030).

    Format: "{device}/stats/{analysis_type}/{reference_key}[/{time_range}]"

    Beispiele:
        generate_stats_dataset_key("krc5", "correlation", "pos_act_z_mm-axis_act_a1_deg", "2026-02-11_15-55_17-55")
        → "krc5/stats/correlation/pos_act_z_mm-axis_act_a1_deg/2026-02-11_15-55_17-55"

        generate_stats_dataset_key("krc5", "mean", "torque_act_a1_nm", "2026-02-11_15-55_17-55")
        → "krc5/stats/mean/torque_act_a1_nm/2026-02-11_15-55_17-55"

    Args:
        device_id: Geräte-ID (z.B. "krc5")
        analysis_type: "correlation", "mean", "std", "min_max", "trend", "percentiles", "anomaly", "summary"
        reference_key: Einzelvariable oder Paar: "pos_act_z_mm-axis_act_a1_deg"
        time_range: Zeitraum-String (z.B. "2026-02-11_15-55_17-55")
    """
    parts = [device_id.lower(), "stats", analysis_type.lower(), reference_key.lower()]
    if time_range:
        parts.append(time_range.lower())
    return "/".join(parts)


def determine_signal_type(data_keys: list[str]) -> str:
    """
    Bestimmt den Signal-Typ basierend auf den Daten-Keys.

    Nutzt telemetry_lookup.json als Single Source of Truth:
    Sucht den ThingsBoard-Key in den Gruppen und gibt den Gruppennamen zurück.

    Beispiele:
        ["torque_act_a1_nm"] → "torque_actual"
        ["vel_act_m_per_s"]  → "velocity_tcp"
        ["axis_act_a1_deg"]  → "axis_position"
        ["unknown_key"]      → "unknown" (Fallback: erster _ -Segment)
    """
    if not data_keys:
        return "unknown"

    lookup = _get_telemetry_lookup()
    first_key = data_keys[0].lower()

    # Suche in welcher Gruppe der Key enthalten ist
    for group_name, group_info in lookup.items():
        if first_key in group_info.get("keys", []):
            return group_name

    # Fallback: erstes Segment des Keys
    return first_key.split("_")[0] if "_" in first_key else first_key[:10]


def _get_telemetry_lookup() -> dict:
    """Lädt und cached telemetry_lookup.json."""
    if not hasattr(_get_telemetry_lookup, "_cache"):
        import json
        from pathlib import Path

        lookup_path = Path(__file__).parent / "telemetry_lookup.json"
        try:
            with open(lookup_path) as f:
                data = json.load(f)
            _get_telemetry_lookup._cache = data.get("groups", {})
        except Exception as e:
            logger.warning(f"telemetry_lookup.json nicht ladbar: {e}")
            _get_telemetry_lookup._cache = {}

    return _get_telemetry_lookup._cache
