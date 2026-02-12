"""
Gemeinsame Hilfsfunktionen für alle Agents.

DEC-016: Ausgelagert für DRY-Prinzip und Wiederverwendbarkeit.
DEC-025: DuckDB-First Datenzugriff mit Legacy-Fallback.
"""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# DUCKDB-FIRST DATENZUGRIFF (DEC-025)
# =============================================================================

def get_data_from_state(state: dict) -> dict[str, list]:
    """
    DEC-025/026: Holt Daten aus DuckDB (primär) oder Legacy-State (Fallback).

    DEC-026: Wenn active_dataset_keys gesetzt ist, werden nur Daten für
    diese Keys geladen. Sonst alle Daten (Fallback).

    Returns:
        Daten im ThingsBoard-Format: {"signal_key": [{"value": ..., "timestamp": ...}, ...]}
    """
    session_id = state.get("session_id", "default")
    active_keys = state.get("active_dataset_keys")  # DEC-026

    # Versuch 1: DuckDB SessionStore
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

    # Versuch 2: Legacy-Format aus State
    datasets = state.get("datasets", {})
    return extract_data_from_datasets(datasets)


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

    # Versuch 2: Legacy
    datasets = state.get("datasets", {})
    data = extract_data_from_datasets(datasets)
    return extract_values_from_data(data, signal_key)


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

    # Versuch 2: Legacy
    datasets = state.get("datasets", {})
    data = extract_data_from_datasets(datasets)
    return extract_timestamps_from_data(data, signal_key), extract_values_from_data(data, signal_key)


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

    # Versuch 2: Legacy
    datasets = state.get("datasets", {})
    data = extract_data_from_datasets(datasets)
    return list(data.keys())


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
# Y-ACHSEN LABEL
# =============================================================================

def get_y_label(keys: list[str]) -> str:
    """Bestimmt das Y-Achsen-Label basierend auf den Daten-Keys."""
    if not keys:
        return "Wert"
    
    first_key = keys[0].lower()
    
    label_mapping = [
        ("_nm", "Drehmoment (Nm)"),
        ("_deg", "Position (°)"),
        ("_mm", "Position (mm)"),
        ("_pct", "Prozent (%)"),
        ("vel", "Geschwindigkeit (m/s)"),
        ("speed", "Geschwindigkeit (m/s)"),
        ("acc", "Beschleunigung (%)"),
        ("temp", "Temperatur (°C)"),
        ("energy", "Energie (kWh)"),
        ("current", "Strom (A)"),
    ]
    
    for pattern, label in label_mapping:
        if pattern in first_key:
            return label
    
    return "Wert"
