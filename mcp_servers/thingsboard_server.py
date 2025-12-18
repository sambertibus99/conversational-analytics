"""
ThingsBoard MCP Server.

Exponiert Tools für ThingsBoard-Zugriff via MCP.

WICHTIG: Große Datenmengen werden in Dateien gespeichert,
nur Zusammenfassungen gehen an den LLM-Context!
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import asyncio
import json
import re
import uuid
from datetime import datetime, timedelta
from typing import Any

from mcp.server.fastmcp import FastMCP

from mcp_servers.thingsboard_client import ThingsBoardClient
from config.settings import KRC5_DEVICE_ID, VALID_DEVICES, OUTPUTS_DIR

# MCP Server erstellen
mcp = FastMCP("ThingsBoard")

# Daten-Verzeichnis für temporäre Dateien
DATA_DIR = OUTPUTS_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Globaler Client (wird bei Bedarf initialisiert)
_client: ThingsBoardClient | None = None
_client_context = None


async def get_client() -> ThingsBoardClient:
    """Lazy initialization des ThingsBoard Clients."""
    global _client, _client_context
    if _client is None:
        _client = ThingsBoardClient()
        _client_context = await _client.__aenter__()
    return _client


def resolve_device_id(device_name: str | None) -> str:
    """Löst Device-Namen zu ID auf."""
    if device_name is None or device_name.upper() == "KRC5":
        return KRC5_DEVICE_ID
    
    raise ValueError(
        f"Unbekanntes Device: '{device_name}'. "
        f"Verfügbare Devices: {', '.join(VALID_DEVICES)}"
    )


def save_data_to_file(data: dict, prefix: str = "telemetry") -> str:
    """Speichert Daten in eine JSON-Datei."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{prefix}_{timestamp}_{uuid.uuid4().hex[:8]}.json"
    filepath = DATA_DIR / filename
    
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    return str(filepath)


def calculate_statistics(data: dict) -> dict:
    """Berechnet Basis-Statistiken für die Daten."""
    stats = {}
    for key, values in data.items():
        if not values:
            continue
        
        numeric_values = []
        timestamps = []
        for v in values:
            if isinstance(v, dict) and "value" in v:
                try:
                    numeric_values.append(float(v["value"]))
                    if "timestamp" in v:
                        timestamps.append(v["timestamp"])
                except (ValueError, TypeError):
                    pass
            elif isinstance(v, (int, float)):
                numeric_values.append(float(v))
        
        if numeric_values:
            stats[key] = {
                "count": len(numeric_values),
                "min": round(min(numeric_values), 3),
                "max": round(max(numeric_values), 3),
                "avg": round(sum(numeric_values) / len(numeric_values), 3),
                "first": round(numeric_values[0], 3),
                "last": round(numeric_values[-1], 3),
            }
            # Zeitbereich der tatsächlichen Daten
            if timestamps:
                stats[key]["first_timestamp"] = datetime.fromtimestamp(min(timestamps) / 1000).strftime("%d.%m.%Y %H:%M:%S")
                stats[key]["last_timestamp"] = datetime.fromtimestamp(max(timestamps) / 1000).strftime("%d.%m.%Y %H:%M:%S")
    
    return stats


# Wochentag-Mapping (Deutsch und Englisch)
WEEKDAY_MAP = {
    "montag": 0, "monday": 0, "mo": 0,
    "dienstag": 1, "tuesday": 1, "di": 1,
    "mittwoch": 2, "wednesday": 2, "mi": 2,
    "donnerstag": 3, "thursday": 3, "do": 3,
    "freitag": 4, "friday": 4, "fr": 4,
    "samstag": 5, "saturday": 5, "sa": 5,
    "sonntag": 6, "sunday": 6, "so": 6,
}

WEEKDAY_NAMES = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def parse_timerange(timerange: str | None) -> tuple[int, int]:
    """
    Parst Zeitraum-Angaben zu Timestamps.
    
    Unterstützt:
    - Relative: "letzte Stunde", "letzte 24h", "heute", "letzte 30 Minuten"
    - Wochentage: "Dienstag", "Dienstag um 13 Uhr", "letzten Montag"
    - Datum: "16.", "am 16.", "16. Dezember", "16.12.", "16.12.2025"
    - Spezifisch: "gestern um 14:30"
    """
    now = datetime.now()
    end_ts = int(now.timestamp() * 1000)
    
    if timerange is None:
        start = now - timedelta(hours=1)
        start_ts = int(start.timestamp() * 1000)
        return start_ts, end_ts
    
    timerange_lower = timerange.lower()
    
    # === Explizite Datumsangaben (16., am 16., 16. Dezember, 16.12.) ===
    # Pattern für Tag mit optionalem Monat und Jahr
    date_patterns = [
        # "16.12.2025" oder "16.12."
        r'(\d{1,2})\.(\d{1,2})\.(\d{4})?',
        # "am 16." oder "den 16." oder "für den 16." oder einfach "16."
        r'(?:am|den|für den|vom)?\s*(\d{1,2})\.',
    ]
    
    for pattern in date_patterns:
        match = re.search(pattern, timerange_lower)
        if match:
            groups = match.groups()
            day = int(groups[0])
            
            # Monat bestimmen
            if len(groups) > 1 and groups[1] and groups[1].isdigit():
                month = int(groups[1])
            else:
                # Monat aus Text extrahieren oder aktuellen Monat nehmen
                month_map = {
                    "januar": 1, "february": 2, "märz": 3, "april": 4,
                    "mai": 5, "juni": 6, "juli": 7, "august": 8,
                    "september": 9, "oktober": 10, "november": 11, "dezember": 12,
                    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
                }
                month = now.month
                for m_name, m_num in month_map.items():
                    if m_name in timerange_lower:
                        month = m_num
                        break
            
            # Jahr bestimmen
            if len(groups) > 2 and groups[2]:
                year = int(groups[2])
            else:
                year = now.year
            
            # Datum erstellen
            try:
                target_date = datetime(year, month, day)
                
                # Wenn Datum in Zukunft liegt, letztes Jahr nehmen
                if target_date > now:
                    target_date = target_date.replace(year=year - 1)
                
                # Ganzen Tag abfragen
                start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
                end = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)
                
                start_ts = int(start.timestamp() * 1000)
                end_ts = int(end.timestamp() * 1000)
                return start_ts, end_ts
            except ValueError:
                pass  # Ungültiges Datum, weiter mit anderen Patterns
    
    # === Spezifische Wochentage erkennen ===
    found_weekday = None
    for day_name, day_num in WEEKDAY_MAP.items():
        if day_name in timerange_lower:
            found_weekday = day_num
            break
    
    if found_weekday is not None:
        current_weekday = now.weekday()
        days_ago = (current_weekday - found_weekday) % 7
        if days_ago == 0:
            days_ago = 7
        
        target_date = now - timedelta(days=days_ago)
        
        hour = 12
        minute = 0
        
        time_patterns = [
            r'(\d{1,2}):(\d{2})',
            r'(\d{1,2})\s*uhr',
            r'um\s*(\d{1,2})',
        ]
        
        for pattern in time_patterns:
            match = re.search(pattern, timerange_lower)
            if match:
                groups = match.groups()
                hour = int(groups[0])
                if len(groups) > 1 and groups[1]:
                    minute = int(groups[1])
                break
        
        target_time = target_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
        start = target_time - timedelta(minutes=5)
        end = target_time + timedelta(minutes=5)
        
        start_ts = int(start.timestamp() * 1000)
        end_ts = int(end.timestamp() * 1000)
        return start_ts, end_ts
    
    # === "gestern" ===
    if "gestern" in timerange_lower or "yesterday" in timerange_lower:
        yesterday = now - timedelta(days=1)
        
        hour_match = re.search(r'(\d{1,2}):?(\d{2})?\s*(uhr)?', timerange_lower)
        if hour_match:
            hour = int(hour_match.group(1))
            minute = int(hour_match.group(2)) if hour_match.group(2) else 0
            target_time = yesterday.replace(hour=hour, minute=minute, second=0, microsecond=0)
            start = target_time - timedelta(minutes=5)
            end = target_time + timedelta(minutes=5)
        else:
            start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
            end = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        start_ts = int(start.timestamp() * 1000)
        end_ts = int(end.timestamp() * 1000)
        return start_ts, end_ts
    
    # === Relative Zeiträume ===
    if "stunde" in timerange_lower or "hour" in timerange_lower:
        hours = 1
        for word in timerange.split():
            if word.isdigit():
                hours = int(word)
                break
        start = now - timedelta(hours=hours)
    elif "tag" in timerange_lower or "day" in timerange_lower or "24h" in timerange_lower:
        days = 1
        for word in timerange.split():
            if word.isdigit():
                days = int(word)
                break
        start = now - timedelta(days=days)
    elif "woche" in timerange_lower or "week" in timerange_lower:
        start = now - timedelta(weeks=1)
    elif "heute" in timerange_lower or "today" in timerange_lower:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif "minute" in timerange_lower:
        minutes = 10
        for word in timerange.split():
            if word.isdigit():
                minutes = int(word)
                break
        start = now - timedelta(minutes=minutes)
    else:
        start = now - timedelta(hours=1)
    
    start_ts = int(start.timestamp() * 1000)
    return start_ts, end_ts


# =============================================================================
# MCP TOOLS
# =============================================================================

@mcp.tool()
async def list_devices() -> str:
    """Listet alle verfügbaren Geräte in ThingsBoard auf."""
    client = await get_client()
    devices = await client.list_devices()
    return json.dumps(devices, indent=2)


@mcp.tool()
async def get_device_info(device_name: str = "KRC5") -> str:
    """Gibt Detailinformationen zu einem Gerät zurück."""
    device_id = resolve_device_id(device_name)
    client = await get_client()
    info = await client.get_device_info(device_id)
    return json.dumps(info, indent=2)


@mcp.tool()
async def list_telemetry_keys(device_name: str = "KRC5") -> str:
    """Listet alle verfügbaren Telemetrie-Keys für ein Gerät auf."""
    device_id = resolve_device_id(device_name)
    client = await get_client()
    keys = await client.get_telemetry_keys(device_id)
    return json.dumps(keys, indent=2)


@mcp.tool()
async def get_data_availability(
    keys: str = "pos_act_x_mm",
    device_name: str = "KRC5",
) -> str:
    """
    Zeigt an, für welchen Zeitraum Daten verfügbar sind.
    
    WICHTIG: Rufe dieses Tool ZUERST auf, wenn du unsicher bist ob Daten existieren!
    
    Args:
        keys: Ein Key zum Prüfen, z.B. "pos_act_x_mm" oder "axis_act_a1_deg"
        device_name: Name des Geräts
        
    Returns:
        Zeitraum der verfügbaren Daten (erstes und letztes Datum)
    """
    device_id = resolve_device_id(device_name)
    key_list = [k.strip() for k in keys.split(",")][:1]  # Nur ersten Key
    
    client = await get_client()
    
    # Hole die neuesten Daten (um zu sehen wann zuletzt Daten kamen)
    latest = await client.get_latest_telemetry(device_id, key_list)
    
    # Hole Daten der letzten Woche um den Bereich zu finden
    now = datetime.now()
    week_ago = now - timedelta(days=7)
    start_ts = int(week_ago.timestamp() * 1000)
    end_ts = int(now.timestamp() * 1000)
    
    data = await client.get_telemetry(device_id, key_list, start_ts, end_ts)
    
    result = {
        "device": device_name,
        "key_checked": key_list[0],
    }
    
    if not data or not data.get(key_list[0]):
        result["status"] = "no_data"
        result["message"] = "Keine Daten in der letzten Woche gefunden."
        result["hint"] = "Der Roboter war möglicherweise nicht aktiv."
    else:
        values = data[key_list[0]]
        timestamps = [v["timestamp"] for v in values if "timestamp" in v]
        
        if timestamps:
            first_ts = min(timestamps)
            last_ts = max(timestamps)
            first_dt = datetime.fromtimestamp(first_ts / 1000)
            last_dt = datetime.fromtimestamp(last_ts / 1000)
            
            result["status"] = "data_available"
            result["data_range"] = {
                "first_data": first_dt.strftime("%d.%m.%Y %H:%M:%S"),
                "first_weekday": WEEKDAY_NAMES[first_dt.weekday()],
                "last_data": last_dt.strftime("%d.%m.%Y %H:%M:%S"),
                "last_weekday": WEEKDAY_NAMES[last_dt.weekday()],
            }
            result["total_points"] = len(values)
            result["message"] = f"Daten verfügbar von {first_dt.strftime('%d.%m.%Y %H:%M')} bis {last_dt.strftime('%d.%m.%Y %H:%M')}"
    
    return json.dumps(result, indent=2)


@mcp.tool()
async def get_latest_telemetry(
    keys: str,
    device_name: str = "KRC5",
) -> str:
    """
    Holt die aktuellsten Telemetrie-Werte (1 Wert pro Key).
    
    Args:
        keys: Komma-separierte Liste von Keys, z.B. "axis_act_a1_deg,vel_act_m_per_s"
        device_name: Name des Geräts, z.B. "KRC5"
    """
    device_id = resolve_device_id(device_name)
    key_list = [k.strip() for k in keys.split(",")]
    
    client = await get_client()
    data = await client.get_latest_telemetry(device_id, key_list)
    
    # Füge Zeitinfo hinzu
    result = {}
    for key, value in data.items():
        if isinstance(value, dict) and "timestamp" in value:
            ts = value["timestamp"]
            dt = datetime.fromtimestamp(ts / 1000)
            result[key] = {
                **value,
                "timestamp_human": dt.strftime("%d.%m.%Y %H:%M:%S"),
                "weekday": WEEKDAY_NAMES[dt.weekday()],
            }
        else:
            result[key] = value
    
    return json.dumps(result, indent=2)


@mcp.tool()
async def get_telemetry(
    keys: str,
    timerange: str = "letzte Stunde",
    device_name: str = "KRC5",
) -> str:
    """
    Holt Telemetrie-Zeitreihen für einen Zeitraum.
    
    WICHTIG: 
    - Wenn keine Daten gefunden werden, wird status="no_data" zurückgegeben
    - Versuche NICHT einen anderen Zeitraum, sondern informiere den Nutzer!
    - Nutze get_data_availability um zu prüfen wann Daten existieren
    
    Args:
        keys: Komma-separierte Liste von Keys, z.B. "axis_act_a1_deg,torque_act_a1_nm"
        timerange: Zeitraum wie "letzte Stunde", "Dienstag 13 Uhr", "gestern um 14:30"
        device_name: Name des Geräts
        
    Returns:
        Zusammenfassung mit Statistiken (oder Fehlermeldung wenn keine Daten)
    """
    device_id = resolve_device_id(device_name)
    key_list = [k.strip() for k in keys.split(",")]
    start_ts, end_ts = parse_timerange(timerange)
    
    client = await get_client()
    data = await client.get_telemetry(device_id, key_list, start_ts, end_ts)
    
    # Menschenlesbare Zeit
    start_dt = datetime.fromtimestamp(start_ts / 1000)
    end_dt = datetime.fromtimestamp(end_ts / 1000)
    start_human = start_dt.strftime("%d.%m.%Y %H:%M")
    end_human = end_dt.strftime("%d.%m.%Y %H:%M")
    start_weekday = WEEKDAY_NAMES[start_dt.weekday()]
    
    # Prüfe ob Daten vorhanden
    total_points = sum(len(values) for values in data.values())
    
    if total_points == 0:
        # KEINE DATEN - klare Fehlermeldung!
        return json.dumps({
            "status": "no_data",
            "requested_timerange": {
                "start": start_human,
                "end": end_human,
                "weekday": start_weekday,
            },
            "message": f"Keine Daten für den Zeitraum {start_weekday}, {start_human} bis {end_human} gefunden.",
            "hint": "Nutze get_data_availability um zu prüfen, wann Daten verfügbar sind.",
            "action": "Informiere den Nutzer, dass keine Daten für diesen Zeitraum existieren. Versuche NICHT automatisch andere Zeiträume!",
        }, indent=2)
    
    # Daten vorhanden - normal verarbeiten
    stats = calculate_statistics(data)
    
    full_data = {
        "timerange": {
            "start_ts": start_ts,
            "end_ts": end_ts,
            "start_human": start_human,
            "end_human": end_human,
            "weekday": start_weekday,
        },
        "keys": key_list,
        "data": data,
    }
    data_file = save_data_to_file(full_data, "telemetry")
    
    summary = {
        "status": "success",
        "timerange": {
            "start": start_human,
            "end": end_human,
            "weekday": start_weekday,
        },
        "data_points": {key: len(values) for key, values in data.items()},
        "statistics": stats,
        "data_file": data_file,
    }
    
    return json.dumps(summary, indent=2)


@mcp.tool()
async def get_telemetry_aggregated(
    keys: str,
    timerange: str = "letzte 24 Stunden",
    interval: str = "1 Stunde",
    aggregation: str = "AVG",
    device_name: str = "KRC5",
) -> str:
    """
    Holt aggregierte Telemetrie-Daten. Ideal für längere Zeiträume!
    
    Args:
        keys: Komma-separierte Liste von Keys
        timerange: Zeitraum wie "letzte 24 Stunden", "letzte Woche"
        interval: Aggregations-Intervall wie "1 Stunde", "30 Minuten"
        aggregation: AVG, MIN, MAX, SUM, COUNT
        device_name: Name des Geräts
    """
    device_id = resolve_device_id(device_name)
    key_list = [k.strip() for k in keys.split(",")]
    start_ts, end_ts = parse_timerange(timerange)
    
    # Interval in Millisekunden
    interval_lower = interval.lower()
    if "tag" in interval_lower or "day" in interval_lower:
        interval_ms = 86400000
    elif "stunde" in interval_lower or "hour" in interval_lower:
        interval_ms = 3600000
    elif "minute" in interval_lower:
        minutes = 30
        for word in interval.split():
            if word.isdigit():
                minutes = int(word)
                break
        interval_ms = minutes * 60000
    else:
        interval_ms = 3600000
    
    client = await get_client()
    data = await client.get_telemetry_aggregated(
        device_id, key_list, start_ts, end_ts, interval_ms, aggregation.upper()
    )
    
    start_dt = datetime.fromtimestamp(start_ts / 1000)
    end_dt = datetime.fromtimestamp(end_ts / 1000)
    start_human = start_dt.strftime("%d.%m.%Y %H:%M")
    end_human = end_dt.strftime("%d.%m.%Y %H:%M")
    start_weekday = WEEKDAY_NAMES[start_dt.weekday()]
    
    # Prüfe ob Daten vorhanden
    total_points = sum(len(values) for values in data.values())
    
    if total_points == 0:
        return json.dumps({
            "status": "no_data",
            "requested_timerange": {
                "start": start_human,
                "end": end_human,
                "weekday": start_weekday,
            },
            "message": f"Keine Daten für den Zeitraum {start_weekday}, {start_human} bis {end_human} gefunden.",
            "hint": "Nutze get_data_availability um zu prüfen, wann Daten verfügbar sind.",
        }, indent=2)
    
    stats = calculate_statistics(data)
    
    full_data = {
        "timerange": {
            "start_ts": start_ts,
            "end_ts": end_ts,
            "start_human": start_human,
            "end_human": end_human,
            "weekday": start_weekday,
        },
        "interval_ms": interval_ms,
        "aggregation": aggregation.upper(),
        "keys": key_list,
        "data": data,
    }
    data_file = save_data_to_file(full_data, "telemetry_agg")
    
    summary = {
        "status": "success",
        "timerange": {
            "start": start_human,
            "end": end_human,
            "weekday": start_weekday,
        },
        "interval": interval,
        "aggregation": aggregation.upper(),
        "data_points": {key: len(values) for key, values in data.items()},
        "statistics": stats,
        "data_file": data_file,
    }
    
    return json.dumps(summary, indent=2)


@mcp.tool()
async def get_attributes(
    keys: str,
    device_name: str = "KRC5",
) -> str:
    """
    Holt statische Attribute eines Geräts.
    
    Attribute sind Werte die sich selten ändern, z.B. load_mass_kg, energy_total_kwh.
    """
    device_id = resolve_device_id(device_name)
    key_list = [k.strip() for k in keys.split(",")]
    
    client = await get_client()
    data = await client.get_attributes(device_id, key_list)
    return json.dumps(data, indent=2)


@mcp.tool()
async def list_attribute_keys(device_name: str = "KRC5") -> str:
    """Listet alle verfügbaren Attribut-Keys für ein Gerät auf."""
    device_id = resolve_device_id(device_name)
    client = await get_client()
    keys = await client.get_attribute_keys(device_id)
    return json.dumps(keys, indent=2)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    mcp.run()
