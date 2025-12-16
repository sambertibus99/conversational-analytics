"""
ThingsBoard MCP Server.

Exponiert 8 Tools für ThingsBoard-Zugriff via MCP.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any

from mcp.server.fastmcp import FastMCP

from mcp_servers.thingsboard_client import ThingsBoardClient
from config.settings import KRC5_DEVICE_ID, VALID_DEVICES

# MCP Server erstellen
mcp = FastMCP("ThingsBoard")

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
    """
    Löst Device-Namen zu ID auf.
    
    Args:
        device_name: Name wie "KRC5" oder None für Default
        
    Returns:
        Device ID
        
    Raises:
        ValueError: Wenn Device unbekannt
    """
    if device_name is None or device_name.upper() == "KRC5":
        return KRC5_DEVICE_ID
    
    raise ValueError(
        f"Unbekanntes Device: '{device_name}'. "
        f"Verfügbare Devices: {', '.join(VALID_DEVICES)}"
    )


def parse_timerange(timerange: str | None) -> tuple[int, int]:
    """
    Parst Zeitraum-Angaben zu Timestamps.
    
    Args:
        timerange: z.B. "letzte Stunde", "letzte 24h", "heute", oder None
        
    Returns:
        (start_ts, end_ts) in Millisekunden
    """
    now = datetime.now()
    end_ts = int(now.timestamp() * 1000)
    
    if timerange is None:
        # Default: letzte Stunde
        start = now - timedelta(hours=1)
    elif "stunde" in timerange.lower() or "hour" in timerange.lower():
        hours = 1
        for word in timerange.split():
            if word.isdigit():
                hours = int(word)
                break
        start = now - timedelta(hours=hours)
    elif "tag" in timerange.lower() or "day" in timerange.lower() or "24h" in timerange:
        days = 1
        for word in timerange.split():
            if word.isdigit():
                days = int(word)
                break
        start = now - timedelta(days=days)
    elif "woche" in timerange.lower() or "week" in timerange.lower():
        start = now - timedelta(weeks=1)
    elif "heute" in timerange.lower() or "today" in timerange.lower():
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif "minute" in timerange.lower():
        minutes = 10
        for word in timerange.split():
            if word.isdigit():
                minutes = int(word)
                break
        start = now - timedelta(minutes=minutes)
    else:
        # Default fallback
        start = now - timedelta(hours=1)
    
    start_ts = int(start.timestamp() * 1000)
    return start_ts, end_ts


# =============================================================================
# MCP TOOLS
# =============================================================================

@mcp.tool()
async def list_devices() -> str:
    """
    Listet alle verfügbaren Geräte in ThingsBoard auf.
    
    Returns:
        JSON-Liste mit Device-Informationen (id, name, type)
    """
    client = await get_client()
    devices = await client.list_devices()
    return json.dumps(devices, indent=2)


@mcp.tool()
async def get_device_info(device_name: str = "KRC5") -> str:
    """
    Gibt Detailinformationen zu einem Gerät zurück.
    
    Args:
        device_name: Name des Geräts, z.B. "KRC5"
        
    Returns:
        JSON mit Device-Details
    """
    device_id = resolve_device_id(device_name)
    client = await get_client()
    info = await client.get_device_info(device_id)
    return json.dumps(info, indent=2)


@mcp.tool()
async def list_telemetry_keys(device_name: str = "KRC5") -> str:
    """
    Listet alle verfügbaren Telemetrie-Keys für ein Gerät auf.
    
    Args:
        device_name: Name des Geräts, z.B. "KRC5"
        
    Returns:
        JSON-Liste aller Telemetrie-Keys wie axis_act_a1_deg, vel_act_m_per_s, etc.
    """
    device_id = resolve_device_id(device_name)
    client = await get_client()
    keys = await client.get_telemetry_keys(device_id)
    return json.dumps(keys, indent=2)


@mcp.tool()
async def get_latest_telemetry(
    keys: str,
    device_name: str = "KRC5",
) -> str:
    """
    Holt die aktuellsten Telemetrie-Werte.
    
    Args:
        keys: Komma-separierte Liste von Keys, z.B. "axis_act_a1_deg,vel_act_m_per_s"
        device_name: Name des Geräts, z.B. "KRC5"
        
    Returns:
        JSON mit aktuellen Werten und Timestamps
    """
    device_id = resolve_device_id(device_name)
    key_list = [k.strip() for k in keys.split(",")]
    
    client = await get_client()
    data = await client.get_latest_telemetry(device_id, key_list)
    return json.dumps(data, indent=2)


@mcp.tool()
async def get_telemetry(
    keys: str,
    timerange: str = "letzte Stunde",
    device_name: str = "KRC5",
) -> str:
    """
    Holt Telemetrie-Zeitreihen für einen Zeitraum.
    
    WICHTIG: Bei Zeiträumen > 24 Stunden besser get_telemetry_aggregated verwenden!
    
    Args:
        keys: Komma-separierte Liste von Keys, z.B. "axis_act_a1_deg,torque_act_a1_nm"
        timerange: Zeitraum wie "letzte Stunde", "letzte 24h", "heute", "letzte 30 Minuten"
        device_name: Name des Geräts, z.B. "KRC5"
        
    Returns:
        JSON mit Zeitreihen-Daten (value, timestamp pro Datenpunkt)
    """
    device_id = resolve_device_id(device_name)
    key_list = [k.strip() for k in keys.split(",")]
    start_ts, end_ts = parse_timerange(timerange)
    
    client = await get_client()
    data = await client.get_telemetry(device_id, key_list, start_ts, end_ts)
    
    # Zusammenfassung hinzufügen
    summary = {
        "timerange": {"start_ts": start_ts, "end_ts": end_ts},
        "data_points": {key: len(values) for key, values in data.items()},
        "data": data,
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
        keys: Komma-separierte Liste von Keys, z.B. "axis_act_a1_deg,torque_act_a1_nm"
        timerange: Zeitraum wie "letzte 24 Stunden", "letzte Woche", "heute"
        interval: Aggregations-Intervall wie "1 Stunde", "30 Minuten", "1 Tag"
        aggregation: Aggregationsfunktion - AVG, MIN, MAX, SUM, COUNT
        device_name: Name des Geräts, z.B. "KRC5"
        
    Returns:
        JSON mit aggregierten Zeitreihen-Daten
    """
    device_id = resolve_device_id(device_name)
    key_list = [k.strip() for k in keys.split(",")]
    start_ts, end_ts = parse_timerange(timerange)
    
    # Interval in Millisekunden umrechnen
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
        interval_ms = 3600000  # Default: 1 Stunde
    
    client = await get_client()
    data = await client.get_telemetry_aggregated(
        device_id, key_list, start_ts, end_ts, interval_ms, aggregation.upper()
    )
    
    summary = {
        "timerange": {"start_ts": start_ts, "end_ts": end_ts},
        "interval_ms": interval_ms,
        "aggregation": aggregation.upper(),
        "data_points": {key: len(values) for key, values in data.items()},
        "data": data,
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
    
    Args:
        keys: Komma-separierte Liste von Attribut-Keys, z.B. "load_mass_kg,energy_total_kwh"
        device_name: Name des Geräts, z.B. "KRC5"
        
    Returns:
        JSON mit Attribut-Werten
    """
    device_id = resolve_device_id(device_name)
    key_list = [k.strip() for k in keys.split(",")]
    
    client = await get_client()
    data = await client.get_attributes(device_id, key_list)
    return json.dumps(data, indent=2)


@mcp.tool()
async def list_attribute_keys(device_name: str = "KRC5") -> str:
    """
    Listet alle verfügbaren Attribut-Keys für ein Gerät auf.
    
    Args:
        device_name: Name des Geräts, z.B. "KRC5"
        
    Returns:
        JSON mit Attribut-Keys gruppiert nach Scope
    """
    device_id = resolve_device_id(device_name)
    client = await get_client()
    keys = await client.get_attribute_keys(device_id)
    return json.dumps(keys, indent=2)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    mcp.run()