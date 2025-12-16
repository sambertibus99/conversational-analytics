"""
ThingsBoard REST API Client.

Async HTTP Client für ThingsBoard Telemetrie- und Attribut-Abfragen.
"""

import sys
from pathlib import Path

# Projektroot zum Python-Pfad hinzufügen
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import asyncio
from datetime import datetime, timedelta
from typing import Any

import httpx

from config.settings import (
    THINGSBOARD_URL,
    THINGSBOARD_USERNAME,
    THINGSBOARD_PASSWORD,
    KRC5_DEVICE_ID,
)


class ThingsBoardClient:
    """Async Client für ThingsBoard REST API."""
    
    def __init__(self):
        self.base_url = THINGSBOARD_URL.rstrip("/")
        self.username = THINGSBOARD_USERNAME
        self.password = THINGSBOARD_PASSWORD
        self.token: str | None = None
        self.token_expires: datetime | None = None
        self._client: httpx.AsyncClient | None = None
    
    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=30.0)
        await self._ensure_token()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            await self._client.aclose()
    
    async def _ensure_token(self) -> None:
        """Holt oder erneuert JWT Token."""
        if self.token and self.token_expires and datetime.now() < self.token_expires:
            return
        
        response = await self._client.post(
            f"{self.base_url}/api/auth/login",
            json={"username": self.username, "password": self.password},
        )
        response.raise_for_status()
        data = response.json()
        self.token = data["token"]
        self.token_expires = datetime.now() + timedelta(hours=2)
    
    def _headers(self) -> dict[str, str]:
        """Auth Header für Requests."""
        return {"X-Authorization": f"Bearer {self.token}"}
    
    async def list_devices(self) -> list[dict[str, Any]]:
        """Listet alle verfügbaren Devices."""
        await self._ensure_token()
        response = await self._client.get(
            f"{self.base_url}/api/tenant/devices",
            params={"pageSize": 100, "page": 0},
            headers=self._headers(),
        )
        response.raise_for_status()
        data = response.json()
        
        return [
            {
                "id": device["id"]["id"],
                "name": device["name"],
                "type": device.get("type", ""),
                "label": device.get("label", ""),
            }
            for device in data.get("data", [])
        ]
    
    async def get_device_info(self, device_id: str) -> dict[str, Any]:
        """Gibt Detailinformationen zu einem Device zurück."""
        await self._ensure_token()
        response = await self._client.get(
            f"{self.base_url}/api/device/{device_id}",
            headers=self._headers(),
        )
        response.raise_for_status()
        device = response.json()
        
        return {
            "id": device["id"]["id"],
            "name": device["name"],
            "type": device.get("type", ""),
            "label": device.get("label", ""),
            "created_time": device.get("createdTime"),
        }
    
    async def get_telemetry_keys(self, device_id: str) -> list[str]:
        """Listet alle verfügbaren Telemetrie-Keys für ein Device."""
        await self._ensure_token()
        response = await self._client.get(
            f"{self.base_url}/api/plugins/telemetry/DEVICE/{device_id}/keys/timeseries",
            headers=self._headers(),
        )
        response.raise_for_status()
        return response.json()
    
    async def get_latest_telemetry(
        self,
        device_id: str,
        keys: list[str],
    ) -> dict[str, Any]:
        """Holt die aktuellsten Telemetrie-Werte."""
        await self._ensure_token()
        response = await self._client.get(
            f"{self.base_url}/api/plugins/telemetry/DEVICE/{device_id}/values/timeseries",
            params={"keys": ",".join(keys)},
            headers=self._headers(),
        )
        response.raise_for_status()
        data = response.json()
        
        result = {}
        for key, values in data.items():
            if values:
                result[key] = {
                    "value": values[0]["value"],
                    "timestamp": values[0]["ts"],
                }
        return result
    
    async def get_telemetry(
        self,
        device_id: str,
        keys: list[str],
        start_ts: int,
        end_ts: int,
        limit: int = 10000,
    ) -> dict[str, list[dict[str, Any]]]:
        """Holt Telemetrie-Zeitreihen für einen Zeitraum."""
        await self._ensure_token()
        response = await self._client.get(
            f"{self.base_url}/api/plugins/telemetry/DEVICE/{device_id}/values/timeseries",
            params={
                "keys": ",".join(keys),
                "startTs": start_ts,
                "endTs": end_ts,
                "limit": limit,
            },
            headers=self._headers(),
        )
        response.raise_for_status()
        data = response.json()
        
        result = {}
        for key, values in data.items():
            result[key] = [
                {"value": v["value"], "timestamp": v["ts"]}
                for v in values
            ]
        return result
    
    async def get_telemetry_aggregated(
        self,
        device_id: str,
        keys: list[str],
        start_ts: int,
        end_ts: int,
        interval: int,
        aggregation: str = "AVG",
    ) -> dict[str, list[dict[str, Any]]]:
        """Holt aggregierte Telemetrie-Daten."""
        await self._ensure_token()
        response = await self._client.get(
            f"{self.base_url}/api/plugins/telemetry/DEVICE/{device_id}/values/timeseries",
            params={
                "keys": ",".join(keys),
                "startTs": start_ts,
                "endTs": end_ts,
                "interval": interval,
                "agg": aggregation,
            },
            headers=self._headers(),
        )
        response.raise_for_status()
        data = response.json()
        
        result = {}
        for key, values in data.items():
            result[key] = [
                {"value": v["value"], "timestamp": v["ts"]}
                for v in values
            ]
        return result
    
    async def get_attribute_keys(self, device_id: str) -> dict[str, list[str]]:
        """Listet alle verfügbaren Attribut-Keys für ein Device."""
        await self._ensure_token()
        result = {}
        
        for scope in ["SERVER_SCOPE", "SHARED_SCOPE", "CLIENT_SCOPE"]:
            response = await self._client.get(
                f"{self.base_url}/api/plugins/telemetry/DEVICE/{device_id}/keys/attributes/{scope}",
                headers=self._headers(),
            )
            response.raise_for_status()
            keys = response.json()
            if keys:
                result[scope] = keys
        
        return result
    
    async def get_attributes(
        self,
        device_id: str,
        keys: list[str],
    ) -> dict[str, Any]:
        """Holt Attribut-Werte für ein Device."""
        await self._ensure_token()
        response = await self._client.get(
            f"{self.base_url}/api/plugins/telemetry/DEVICE/{device_id}/values/attributes",
            params={"keys": ",".join(keys)},
            headers=self._headers(),
        )
        response.raise_for_status()
        data = response.json()
        
        return {item["key"]: item["value"] for item in data}


async def test_client():
    """Schnelltest des Clients."""
    print(f"\n🔌 Verbinde mit ThingsBoard: {THINGSBOARD_URL}")
    print(f"📟 Device ID: {KRC5_DEVICE_ID}")
    
    async with ThingsBoardClient() as client:
        # Devices listen
        print("\n📋 Devices:")
        devices = await client.list_devices()
        for d in devices:
            print(f"   - {d['name']} ({d['id']})")
        
        # Telemetrie-Keys
        print("\n🔑 Telemetrie-Keys:")
        keys = await client.get_telemetry_keys(KRC5_DEVICE_ID)
        print(f"   {len(keys)} Keys verfügbar")
        if keys:
            print(f"   Beispiele: {keys[:5]}...")
        
        # Aktueller Wert
        print("\n📊 Aktuelle Werte:")
        test_keys = ["axis_act_a1_deg", "vel_act_m_per_s"]
        latest = await client.get_latest_telemetry(KRC5_DEVICE_ID, test_keys)
        for key, data in latest.items():
            print(f"   {key}: {data['value']}")
        
        print("\n✅ Client funktioniert!")


if __name__ == "__main__":
    asyncio.run(test_client())