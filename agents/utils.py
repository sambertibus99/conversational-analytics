"""
Gemeinsame Hilfsfunktionen für alle Agents.

DEC-016: Ausgelagert für DRY-Prinzip und Wiederverwendbarkeit.
DEC-025: DuckDB-First Datenzugriff mit Legacy-Fallback.
"""

import json as _json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# ACTIVE-DATA BESCHREIBUNG FÜR SUPERVISOR EVAL
# =============================================================================

def describe_active_data(
    session_id: str,
    dataset_keys: list[str] | None,
    stats_keys: list[str] | None,
) -> str:
    """Beschreibt aktive Datenquellen für den Supervisor EVAL.

    Parst UNS-Keys und reichert mit DuckDB-Metadaten (Punktanzahl) an.

    Beispiel-Output:
        Zeitreihen (active_dataset_keys):
        - torque_act_a1_nm: 2684 Punkte (14:00-16:00, detail)
        Stats (active_stats_keys):
        - Korrelation pos_act_z_mm / axis_act_a1_deg: r=-0.664
    """
    parts = []

    if dataset_keys:
        parts.append("Zeitreihen (active_dataset_keys):")
        for dk in dataset_keys:
            parts.append(f"  - {_describe_dataset_key(session_id, dk)}")

    if stats_keys:
        parts.append("Stats (active_stats_keys):")
        for sk in stats_keys:
            parts.append(f"  - {_describe_stats_key(session_id, sk)}")

    if not parts:
        return "Keine aktiven Datenquellen."

    return "\n".join(parts)


def _describe_dataset_key(session_id: str, dataset_key: str) -> str:
    """Beschreibt einen Telemetrie-Dataset-Key lesbar.

    Parst UNS-Key: krc5/{signal_type}/{data_type}/{mode}/{timerange}[/{agg}]
    Reichert mit point_count aus DuckDB dataset_meta an.
    """
    parts = dataset_key.split("/")
    signal_type = parts[1] if len(parts) > 1 else dataset_key
    mode = parts[3] if len(parts) > 3 else "?"
    time_range = parts[4] if len(parts) > 4 else ""

    # Zeitraum lesbar machen: 2026-02-13_14-00_16-00 → 14:00-16:00
    time_str = _format_time_range(time_range)

    # Punktanzahl aus DuckDB dataset_meta
    point_count = _get_point_count(session_id, dataset_key)
    count_str = f"{point_count} Punkte" if point_count else "? Punkte"

    detail = f"{count_str}, {time_str}" if time_str else count_str
    if mode and mode != "?":
        detail += f", {mode}"

    return f"{signal_type}: {detail}"


def _describe_stats_key(session_id: str, stats_key: str) -> str:
    """Beschreibt einen Stats-Dataset-Key lesbar.

    Parst UNS-Key: krc5/stats/{analysis_type}/{reference}/{timerange}
    Reichert mit Kurzfassung aus DuckDB statistics-Tabelle an.
    """
    parts = stats_key.split("/")
    analysis_type = parts[2] if len(parts) > 2 else "?"
    reference = parts[3] if len(parts) > 3 else "?"

    # Stats-Ergebnis Kurzfassung aus DuckDB
    summary = _get_stats_summary(session_id, stats_key, analysis_type)

    label = _ANALYSIS_LABELS.get(analysis_type, analysis_type)
    ref_readable = reference.replace("-", " / ")

    if summary:
        return f"{label} {ref_readable}: {summary}"
    return f"{label} {ref_readable}"


_ANALYSIS_LABELS = {
    "correlation": "Korrelation",
    "mean": "Durchschnitt",
    "std": "Standardabweichung",
    "min_max": "Min/Max",
    "trend": "Trend",
    "percentiles": "Perzentile",
    "anomaly": "Anomalie",
    "summary": "Übersicht",
}


def _format_time_range(time_range: str) -> str:
    """Konvertiert UNS-Zeitraum-String zu lesbarem Format.

    Formate:
      YYYY-MM-DD_HH-MM_HH-MM          → HH:MM-HH:MM (gleicher Tag)
      YYYY-MM-DD_HH-MM_YYYY-MM-DD_HH-MM → DD.MM. HH:MM - DD.MM. HH:MM (mehrtägig)
    """
    if not time_range:
        return ""
    parts = time_range.split("_")
    if len(parts) == 4:
        # Mehrtägig: 2026-02-11_00-00_2026-02-13_23-59
        start_date = parts[0][5:]  # MM-DD
        start_time = parts[1].replace("-", ":")
        end_date = parts[2][5:]  # MM-DD
        end_time = parts[3].replace("-", ":")
        sd = start_date.replace("-", ".")
        ed = end_date.replace("-", ".")
        return f"{sd} {start_time} - {ed} {end_time}"
    if len(parts) >= 3:
        # Gleicher Tag: 2026-02-13_14-00_16-00
        start = parts[1].replace("-", ":")
        end = parts[2].replace("-", ":")
        return f"{start}-{end}"
    return time_range


def _get_point_count(session_id: str, dataset_key: str) -> int | None:
    """Liest point_count aus DuckDB dataset_meta Tabelle."""
    try:
        from config.duckdb_store import SessionStore
        if session_id in SessionStore._instances:
            store = SessionStore.get_instance(session_id)
            rows = store.query(
                "SELECT point_count FROM dataset_meta WHERE dataset_key = ?",
                [dataset_key],
            )
            if rows:
                return rows[0][0]
    except Exception:
        pass
    return None


def _get_stats_summary(session_id: str, stats_key: str, analysis_type: str) -> str:
    """Liest Kurzfassung eines Stats-Ergebnisses aus DuckDB."""
    try:
        from config.duckdb_store import SessionStore
        if session_id in SessionStore._instances:
            store = SessionStore.get_instance(session_id)
            entry = store.get_statistics(stats_key)
            if entry and entry.get("result"):
                result = entry["result"]
                if analysis_type == "correlation" and "r" in result:
                    return f"r={result['r']}"
                if "slope" in result:
                    return f"slope={result['slope']}"
                if "mean" in result:
                    return f"mean={result['mean']}"
                if "min" in result and "max" in result:
                    return f"min={result['min']}, max={result['max']}"
                if "count" in result:
                    return f"{result['count']} Ergebnisse"
    except Exception:
        pass
    return ""


# =============================================================================
# DUCKDB-FIRST DATENZUGRIFF (DEC-025)
# =============================================================================

def _get_stats_data(session_id: str, active_stats: list[str] | None) -> dict[str, list]:
    """Holt Stats-Daten aus DuckDB statistics-Tabelle (DEC-030)."""
    if not active_stats:
        return {}
    try:
        from config.duckdb_store import SessionStore
        if session_id in SessionStore._instances:
            store = SessionStore.get_instance(session_id)
            data = store.get_multi_statistics_as_chart_data(active_stats)
            if data:
                logger.debug(f"DEC-030: Stats-Daten geladen: {len(data)} keys aus {len(active_stats)} stats datasets")
                return data
    except Exception as e:
        logger.debug(f"DEC-030: Stats-Daten nicht verfügbar: {e}")
    return {}


def _get_telemetry_data(session_id: str, active_keys: list[str] | None) -> dict[str, list]:
    """Holt Telemetrie-Daten aus DuckDB telemetry-Tabelle (DEC-025/026)."""
    try:
        from config.duckdb_store import SessionStore
        if session_id in SessionStore._instances:
            store = SessionStore.get_instance(session_id)
            if store.point_count() > 0:
                if active_keys:
                    data = store.get_data_for_datasets(active_keys)
                    logger.debug(f"DuckDB gefiltert: {len(data)} signal keys für {len(active_keys)} dataset keys")
                else:
                    data = store.get_all_data_merged()
                    logger.debug(f"DuckDB: {len(data)} signal keys, {store.point_count()} Punkte")
                if data:
                    return data
    except Exception as e:
        logger.debug(f"DuckDB nicht verfügbar: {e}")
    return {}


def get_data_from_state(state: dict) -> dict[str, list]:
    """
    DEC-025/026/030: Holt Daten aus DuckDB.

    Priorität: Stats > Timeseries (wenn active_stats_keys vorhanden).
    Routing-Verantwortung (welche Datenquelle) liegt beim Viz Agent,
    der via viz_data_source die Keys im State filtert bevor diese
    Funktion aufgerufen wird.

    Returns:
        Daten im ThingsBoard-Format: {"signal_key": [{"value": ..., "timestamp": ...}, ...]}
    """
    session_id = state.get("session_id", "default")
    active_stats = state.get("active_stats_keys")  # DEC-030
    active_keys = state.get("active_dataset_keys")  # DEC-026

    if active_stats:
        data = _get_stats_data(session_id, active_stats)
        if data:
            return data
    return _get_telemetry_data(session_id, active_keys)


def get_values_for_key(state: dict, signal_key: str) -> list[float]:
    """
    DEC-025: Holt Werte für einen Signal-Key (DuckDB-first).
    DEC-026: Filtert nach active_dataset_keys wenn gesetzt.

    Returns:
        Liste von float-Werten, zeitlich sortiert.
    """
    session_id = state.get("session_id", "default")
    active_keys = state.get("active_dataset_keys")  # DEC-026

    # Versuch 1: DuckDB
    try:
        from config.duckdb_store import SessionStore
        if session_id in SessionStore._instances:
            store = SessionStore.get_instance(session_id)
            if active_keys:
                placeholders = ", ".join(["?"] * len(active_keys))
                values = store.query(
                    f"SELECT value FROM telemetry WHERE signal_key = ? AND dataset_key IN ({placeholders}) ORDER BY ts",
                    [signal_key] + active_keys,
                )
            else:
                values = store.query(
                    "SELECT value FROM telemetry WHERE signal_key = ? ORDER BY ts",
                    [signal_key],
                )
            if values:
                return [r[0] for r in values]
    except Exception as e:
        logger.debug(f"DuckDB Lookup fehlgeschlagen: {e}")

    # DEC-031: Kein Legacy-Fallback mehr
    return []


def get_timeseries_for_key(state: dict, signal_key: str) -> tuple[list[int], list[float]]:
    """
    DEC-025: Holt Timestamps und Werte für einen Signal-Key (DuckDB-first).
    DEC-026: Filtert nach active_dataset_keys wenn gesetzt.

    Returns:
        Tuple (timestamps, values), beide zeitlich sortiert.
    """
    session_id = state.get("session_id", "default")
    active_keys = state.get("active_dataset_keys")  # DEC-026

    # Versuch 1: DuckDB
    try:
        from config.duckdb_store import SessionStore
        if session_id in SessionStore._instances:
            store = SessionStore.get_instance(session_id)
            if active_keys:
                placeholders = ", ".join(["?"] * len(active_keys))
                rows = store.query(
                    f"SELECT ts, value FROM telemetry WHERE signal_key = ? AND dataset_key IN ({placeholders}) ORDER BY ts",
                    [signal_key] + active_keys,
                )
            else:
                rows = store.query(
                    "SELECT ts, value FROM telemetry WHERE signal_key = ? ORDER BY ts",
                    [signal_key],
                )
            if rows:
                return [r[0] for r in rows], [r[1] for r in rows]
    except Exception as e:
        logger.debug(f"DuckDB Lookup fehlgeschlagen: {e}")

    # DEC-031: Kein Legacy-Fallback mehr
    return [], []


def get_available_signal_keys(state: dict) -> list[str]:
    """
    DEC-025: Gibt verfügbare Signal-Keys zurück (DuckDB-first).
    DEC-026: Filtert nach active_dataset_keys wenn gesetzt.
    """
    session_id = state.get("session_id", "default")
    active_keys = state.get("active_dataset_keys")  # DEC-026

    # Versuch 1: DuckDB
    try:
        from config.duckdb_store import SessionStore
        if session_id in SessionStore._instances:
            store = SessionStore.get_instance(session_id)
            if active_keys:
                placeholders = ", ".join(["?"] * len(active_keys))
                rows = store.query(
                    f"SELECT DISTINCT signal_key FROM telemetry WHERE dataset_key IN ({placeholders})",
                    active_keys,
                )
            else:
                rows = store.query("SELECT DISTINCT signal_key FROM telemetry")
            if rows:
                return [r[0] for r in rows]
    except Exception as e:
        logger.debug(f"DuckDB Lookup fehlgeschlagen: {e}")

    # DEC-031: Kein Legacy-Fallback mehr
    return []


# =============================================================================
# DUCKDB DATASET-META ZUGRIFF (DEC-031)
# =============================================================================

def get_dataset_meta_from_duckdb(
    session_id: str,
    dataset_keys: list[str] | None = None,
) -> dict[str, dict]:
    """
    DEC-031: Liest DatasetMeta aus DuckDB.

    Args:
        session_id: DuckDB Session-ID
        dataset_keys: Optionale Liste von Keys (None = alle)

    Returns:
        Dict: dataset_key -> DatasetMeta dict, leeres Dict bei Fehler
    """
    try:
        from config.duckdb_store import SessionStore
        if session_id not in SessionStore._instances:
            return {}
        store = SessionStore.get_instance(session_id)
        if dataset_keys:
            return store.get_dataset_metas(dataset_keys)
        return store.get_all_dataset_metas()
    except Exception as e:
        logger.debug(f"get_dataset_meta_from_duckdb fehlgeschlagen: {e}")
        return {}


# =============================================================================
# LEGACY: DATEN-EXTRAKTION AUS DATASETS (DEC-013)
# =============================================================================

def extract_data_from_datasets(datasets: dict[str, Any]) -> dict[str, list]:
    """
    Extrahiert und merged Daten aus allen Datasets.

    DEC-025: Unterstützt sowohl Legacy-Format (mit "data" Key) als auch
    das neue DatasetMeta-Format (ohne "data" Key, Daten in DuckDB).
    Bei DatasetMeta-Format wird versucht, Daten aus DuckDB zu laden.

    Beispiel Legacy:
        datasets = {
            "torque": {"data": {"torque_a1": [...], "torque_a2": [...]}, ...},
        }

    Returns:
        {"torque_a1": [...], "torque_a2": [...], ...}
    """
    if not datasets:
        return {}

    merged = {}
    duckdb_keys = []

    for dataset_key, dataset_value in datasets.items():
        if not isinstance(dataset_value, dict):
            continue

        # DEC-025: DatasetMeta-Format (hat "dataset_key" statt "data")
        if "dataset_key" in dataset_value and "data" not in dataset_value:
            duckdb_keys.append(dataset_value["dataset_key"])
            continue

        # Legacy-Format: hat "data" Key
        data = dataset_value.get("data", {})
        if isinstance(data, dict):
            for key, values in data.items():
                merged[key] = values

    # DuckDB-Daten nachladen wenn nötig
    if duckdb_keys and not merged:
        try:
            from config.duckdb_store import SessionStore
            # Prüfe ob eine Session existiert
            for sid, store_inst in SessionStore._instances.items():
                for dk in duckdb_keys:
                    data = store_inst.get_all_signal_data(dk)
                    merged.update(data)
                if merged:
                    break
        except Exception as e:
            logger.debug(f"DuckDB Fallback in extract_data_from_datasets: {e}")

    return merged


def get_dataset_meta(datasets: dict[str, Any]) -> dict:
    """
    Extrahiert Metadaten aus Datasets.
    Gibt die erste Meta mit Zeitraum zurück.

    DEC-025: Unterstützt sowohl Legacy- als auch DatasetMeta-Format.
    """
    if not datasets:
        return {}

    for dataset_value in datasets.values():
        if isinstance(dataset_value, dict):
            # DEC-025: DatasetMeta hat "meta" direkt und "timerange"
            if "dataset_key" in dataset_value:
                meta = dataset_value.get("meta", {})
                if meta.get("timerange"):
                    return meta
                if dataset_value.get("timerange"):
                    return {"timerange": dataset_value["timerange"]}
            else:
                # Legacy-Format
                meta = dataset_value.get("meta", {})
                if meta.get("timerange"):
                    return meta

    # Fallback: erste Meta
    first_dataset = next(iter(datasets.values()), {})
    if isinstance(first_dataset, dict):
        if "dataset_key" in first_dataset:
            return first_dataset.get("meta", {})
        return first_dataset.get("meta", {})
    return {}


# =============================================================================
# WERT-VALIDIERUNG
# =============================================================================

def is_valid_numeric_value(value: Any) -> bool:
    """
    Prüft ob ein Wert gültig numerisch ist (keine Fehlermeldung).
    
    Erkennt fehlerhafte Werte wie:
    - "Bad status code: ..."
    - "Error: ..."
    - "null", "None", "NaN"
    - Leere Strings
    """
    if value is None:
        return False
    
    if isinstance(value, (int, float)):
        return True
    
    if isinstance(value, str):
        value_lower = value.lower().strip()
        
        if not value_lower:
            return False
        
        error_patterns = [
            "bad status", "error", "unavailable", "null", "none",
            "nan", "invalid", "failed", "timeout", "exception",
            "not found", "no data",
        ]
        
        for pattern in error_patterns:
            if pattern in value_lower:
                return False
        
        try:
            float(value)
            return True
        except (ValueError, TypeError):
            return False
    
    return False


def extract_values_from_data(data: dict[str, Any], key: Optional[str] = None) -> list[float]:
    """
    Extrahiert numerische Werte aus ThingsBoard-Datenformat.
    
    Input-Formate:
    1. {"key": [{"value": "25.3", "timestamp": 123}, ...]}  (Zeitreihe)
    2. {"key": {"value": "25.3", "timestamp": 123}}  (Latest)
    3. {"key": [25.3, 26.1, ...]}  (Einfache Liste)
    
    Filtert fehlerhafte Werte automatisch!
    """
    if not data:
        return []
    
    if key is None:
        key = next(iter(data.keys()), None)
    
    if key not in data:
        logger.debug(f"Key '{key}' nicht in data. Verfügbar: {list(data.keys())}")
        return []
    
    values = []
    skipped = 0
    raw = data[key]
    
    if isinstance(raw, list):
        for point in raw:
            if isinstance(point, dict) and "value" in point:
                val = point["value"]
                if is_valid_numeric_value(val):
                    try:
                        values.append(float(val))
                    except (ValueError, TypeError):
                        skipped += 1
                else:
                    skipped += 1
            elif isinstance(point, (int, float)):
                values.append(float(point))
            elif isinstance(point, str) and is_valid_numeric_value(point):
                try:
                    values.append(float(point))
                except (ValueError, TypeError):
                    skipped += 1
    
    elif isinstance(raw, dict) and "value" in raw:
        val = raw["value"]
        if is_valid_numeric_value(val):
            try:
                values.append(float(val))
            except (ValueError, TypeError):
                skipped += 1
        else:
            skipped += 1
    
    if skipped > 0:
        logger.debug(f"Key '{key}': {skipped} fehlerhafte Werte übersprungen")
    
    return values


def extract_timestamps_from_data(data: dict[str, Any], key: Optional[str] = None) -> list[int]:
    """Extrahiert Timestamps aus ThingsBoard-Datenformat."""
    if not data:
        return []
    
    if key is None:
        key = next(iter(data.keys()), None)
    
    if key not in data:
        return []
    
    timestamps = []
    raw = data[key]
    
    if isinstance(raw, list):
        for point in raw:
            if isinstance(point, dict) and "timestamp" in point:
                timestamps.append(int(point["timestamp"]))
    
    return timestamps


# =============================================================================
# USER QUERY EXTRAKTION
# =============================================================================

def extract_user_query(messages: list) -> str:
    """Extrahiert die letzte User-Query aus den Messages."""
    from langchain_core.messages import HumanMessage
    
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            return msg.content
    return ""


# =============================================================================
# STATS LABEL (für Stats-Viz-Flow)
# =============================================================================

STATS_LABEL_MAP = {
    "correlation": "Korrelationskoeffizient (r)",
    "mean": "Durchschnitt",
    "std": "Standardabweichung",
    "min_max": "Min/Max",
    "trend": "Trend (Steigung)",
    "percentiles": "Perzentile",
    "anomaly": "Anomalie-Score",
    "summary": "Statistik-Übersicht",
}


def get_stats_label(active_stats_keys: list[str]) -> str:
    """Bestimmt Y-Achsen-Label aus Stats-Dataset-Keys.

    Leitet aus dem UNS-Key den Analyse-Typ ab:
    "krc5/stats/correlation/..." → "Korrelationskoeffizient (r)"
    "krc5/stats/mean/..." → "Durchschnitt"
    """
    if not active_stats_keys:
        return ""
    first_key = active_stats_keys[0]
    parts = first_key.split("/")
    if len(parts) >= 3 and parts[1] == "stats":
        analysis_type = parts[2]
        return STATS_LABEL_MAP.get(analysis_type, analysis_type)
    return ""


# =============================================================================
# Y-ACHSEN LABEL
# =============================================================================

_telemetry_lookup_cache: dict | None = None


def _get_telemetry_lookup() -> dict:
    """Lädt telemetry_lookup.json (einmalig gecacht)."""
    global _telemetry_lookup_cache
    if _telemetry_lookup_cache is not None:
        return _telemetry_lookup_cache
    lookup_path = Path(__file__).parent.parent / "config" / "telemetry_lookup.json"
    try:
        with open(lookup_path) as f:
            _telemetry_lookup_cache = _json.load(f)
    except Exception:
        _telemetry_lookup_cache = {}
    return _telemetry_lookup_cache


def get_y_label(keys: list[str]) -> str:
    """Bestimmt das Y-Achsen-Label aus telemetry_lookup.json."""
    if not keys:
        return "Wert"

    lookup = _get_telemetry_lookup()
    groups = lookup.get("groups", {})

    # Ersten Key in der Lookup-Tabelle finden
    first_key = keys[0]
    for group_data in groups.values():
        if first_key in group_data.get("keys", []):
            name = group_data.get("name", "")
            unit = group_data.get("unit", "")
            if unit:
                return f"{name} ({unit})"
            return name

    return "Wert"
