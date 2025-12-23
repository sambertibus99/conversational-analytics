"""
Gemeinsame Hilfsfunktionen für alle Agents.

DEC-016: Ausgelagert für DRY-Prinzip und Wiederverwendbarkeit.
"""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# DATEN-EXTRAKTION AUS DATASETS (DEC-013)
# =============================================================================

def extract_data_from_datasets(datasets: dict[str, Any]) -> dict[str, list]:
    """
    Extrahiert und merged Daten aus allen Datasets.
    
    Beispiel:
        datasets = {
            "torque": {"data": {"torque_a1": [...], "torque_a2": [...]}, ...},
            "velocity": {"data": {"vel_a1": [...], ...}, ...}
        }
        
    Returns:
        {"torque_a1": [...], "torque_a2": [...], "vel_a1": [...], ...}
    """
    if not datasets:
        return {}
    
    merged = {}
    for dataset_key, dataset_value in datasets.items():
        if not isinstance(dataset_value, dict):
            continue
        
        data = dataset_value.get("data", {})
        if isinstance(data, dict):
            for key, values in data.items():
                # Bei Duplikaten: letzteres gewinnt
                merged[key] = values
    
    return merged


def get_dataset_meta(datasets: dict[str, Any]) -> dict:
    """
    Extrahiert Metadaten aus Datasets.
    Gibt die erste Meta mit Zeitraum zurück.
    """
    if not datasets:
        return {}
    
    for dataset_value in datasets.values():
        if isinstance(dataset_value, dict):
            meta = dataset_value.get("meta", {})
            if meta.get("timerange"):
                return meta
    
    # Fallback: erste Meta
    first_dataset = next(iter(datasets.values()), {})
    return first_dataset.get("meta", {}) if isinstance(first_dataset, dict) else {}


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
