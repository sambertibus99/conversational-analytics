"""Test: MCP Server Tools direkt aufrufen."""

import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import asyncio
import json


async def test_tools():
    """Testet die MCP Tools direkt (ohne MCP-Protokoll)."""
    
    # Importiere die Tool-Funktionen direkt
    from mcp_servers.thingsboard_server import (
        list_devices,
        list_telemetry_keys,
        get_latest_telemetry,
        get_telemetry,
    )
    
    print("\n🧪 MCP TOOLS TEST\n" + "="*50)
    
    # Test 1: Devices listen
    print("\n📋 Test: list_devices()")
    result = await list_devices()
    devices = json.loads(result)
    print(f"   ✅ {len(devices)} Devices gefunden")
    
    # Test 2: Telemetrie-Keys
    print("\n🔑 Test: list_telemetry_keys()")
    result = await list_telemetry_keys("KRC5")
    keys = json.loads(result)
    print(f"   ✅ {len(keys)} Keys verfügbar")
    
    # Test 3: Aktueller Wert
    print("\n📊 Test: get_latest_telemetry()")
    result = await get_latest_telemetry("axis_act_a1_deg,vel_act_m_per_s")
    data = json.loads(result)
    for key, val in data.items():
        print(f"   ✅ {key}: {val['value']}")
    
    # Test 4: Zeitreihe
    print("\n📈 Test: get_telemetry()")
    result = await get_telemetry("axis_act_a1_deg", "letzte 10 Minuten")
    data = json.loads(result)
    print(f"   ✅ {data['data_points']['axis_act_a1_deg']} Datenpunkte geholt")
    
    print("\n" + "="*50)
    print("✅ ALLE TOOLS FUNKTIONIEREN!")


if __name__ == "__main__":
    asyncio.run(test_tools())