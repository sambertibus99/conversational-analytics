"""
ThingsBoard REST API Client.

Async HTTP Client für ThingsBoard Telemetrie- und Attribut-Abfragen.

DESIGN-ENTSCHEIDUNGEN (20.12.2025):
- Error Handling: Custom Exceptions + Retry mit Exponential Backoff
- Logging: Strukturiertes Logging für Debugging
- Best Practice: LangGraph + FastMCP Error Handling Patterns
"""

import sys
from pathlib import Path

# Projektroot zum Python-Pfad hinzufügen
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import asyncio
import logging
import random
from datetime import datetime, timedelta
from typing import Any

import httpx

from config.settings import (
    THINGSBOARD_URL,
    THINGSBOARD_USERNAME,
    THINGSBOARD_PASSWORD,
    KRC5_DEVICE_ID,
)

# =============================================================================
# LOGGING SETUP
# =============================================================================

logger = logging.getLogger("thingsboard_client")
logger.setLevel(logging.DEBUG)

# Handler nur hinzufügen wenn noch keiner existiert
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)


# =============================================================================
# CUSTOM EXCEPTIONS
# =============================================================================

class ThingsBoardError(Exception):
    """Basis-Exception für ThingsBoard-Fehler."""
    
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}
    
    def to_dict(self) -> dict:
        """Für strukturierte Error-Responses."""
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "details": self.details,
        }


class ThingsBoardAuthError(ThingsBoardError):
    """Authentifizierungsfehler (401, 403)."""
    
    def __init__(self, message: str = "Authentifizierung fehlgeschlagen"):
        super().__init__(
            message,
            {"hint": "Prüfe THINGSBOARD_USERNAME und THINGSBOARD_PASSWORD in .env"}
        )


class ThingsBoardConnectionError(ThingsBoardError):
    """Verbindungsfehler (Netzwerk, Timeout)."""
    
    def __init__(self, message: str, original_error: Exception | None = None):
        details = {"hint": "ThingsBoard-Server möglicherweise nicht erreichbar"}
        if original_error:
            details["original_error"] = str(original_error)
        super().__init__(message, details)


class ThingsBoardNotFoundError(ThingsBoardError):
    """Resource nicht gefunden (404)."""
    
    def __init__(self, resource_type: str, resource_id: str):
        super().__init__(
            f"{resource_type} nicht gefunden: {resource_id}",
            {"resource_type": resource_type, "resource_id": resource_id}
        )


class ThingsBoardRateLimitError(ThingsBoardError):
    """Rate Limit erreicht (429)."""
    
    def __init__(self, retry_after: int | None = None):
        details = {"hint": "Zu viele Anfragen, bitte warten"}
        if retry_after:
            details["retry_after_seconds"] = retry_after
        super().__init__("Rate Limit erreicht", details)


class ThingsBoardServerError(ThingsBoardError):
    """Server-Fehler (5xx)."""
    
    def __init__(self, status_code: int, message: str = "Server-Fehler"):
        super().__init__(
            message,
            {"status_code": status_code, "hint": "ThingsBoard-Server hat einen Fehler"}
        )


# =============================================================================
# RETRY DECORATOR
# =============================================================================

async def retry_with_backoff(
    operation,
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 30.0,
    retryable_exceptions: tuple = (
        httpx.ConnectError,
        httpx.TimeoutException,
        ThingsBoardConnectionError,
        ThingsBoardRateLimitError,
    ),
):
    """
    Retry mit Exponential Backoff und Jitter.
    
    Args:
        operation: Async-Funktion die ausgeführt werden soll
        max_attempts: Maximale Versuche
        initial_delay: Initiale Wartezeit in Sekunden
        max_delay: Maximale Wartezeit in Sekunden
        retryable_exceptions: Exceptions die einen Retry auslösen
    
    Returns:
        Ergebnis der Operation
        
    Raises:
        Letzte Exception wenn alle Versuche fehlschlagen
    """
    last_exception = None
    
    for attempt in range(max_attempts):
        try:
            return await operation()
        except retryable_exceptions as e:
            last_exception = e
            
            if attempt == max_attempts - 1:
                logger.error(f"Alle {max_attempts} Versuche fehlgeschlagen: {e}")
                raise
            
            # Exponential Backoff mit Jitter
            delay = min(initial_delay * (2 ** attempt), max_delay)
            jitter = random.uniform(0, delay * 0.1)  # 10% Jitter
            wait_time = delay + jitter
            
            logger.warning(
                f"Versuch {attempt + 1}/{max_attempts} fehlgeschlagen: {e}. "
                f"Warte {wait_time:.2f}s vor erneutem Versuch."
            )
            await asyncio.sleep(wait_time)
    
    raise last_exception


# =============================================================================
# THINGSBOARD CLIENT
# =============================================================================

class ThingsBoardClient:
    """Async Client für ThingsBoard REST API."""
    
    def __init__(self):
        self.base_url = THINGSBOARD_URL.rstrip("/")
        self.username = THINGSBOARD_USERNAME
        self.password = THINGSBOARD_PASSWORD
        self.token: str | None = None
        self.token_expires: datetime | None = None
        self._client: httpx.AsyncClient | None = None
        
        logger.info(f"ThingsBoardClient initialisiert für {self.base_url}")
    
    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=30.0)
        await self._ensure_token()
        logger.info("ThingsBoardClient verbunden")
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            await self._client.aclose()
            logger.info("ThingsBoardClient Verbindung geschlossen")
    
    async def _ensure_token(self) -> None:
        """Holt oder erneuert JWT Token."""
        if self.token and self.token_expires and datetime.now() < self.token_expires:
            return
        
        logger.debug("Hole neuen Auth-Token...")
        
        async def _do_auth():
            response = await self._client.post(
                f"{self.base_url}/api/auth/login",
                json={"username": self.username, "password": self.password},
            )
            self._handle_response_errors(response, "Auth")
            return response.json()
        
        try:
            data = await retry_with_backoff(_do_auth)
            self.token = data["token"]
            self.token_expires = datetime.now() + timedelta(hours=2)
            logger.info("Auth-Token erfolgreich geholt")
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403):
                raise ThingsBoardAuthError()
            raise
    
    def _headers(self) -> dict[str, str]:
        """Auth Header für Requests."""
        return {"X-Authorization": f"Bearer {self.token}"}
    
    def _handle_response_errors(self, response: httpx.Response, operation: str) -> None:
        """
        Zentrale Fehlerbehandlung für HTTP-Responses.
        
        Raises:
            ThingsBoardAuthError: Bei 401/403
            ThingsBoardNotFoundError: Bei 404
            ThingsBoardRateLimitError: Bei 429
            ThingsBoardServerError: Bei 5xx
        """
        status = response.status_code
        
        if status == 401 or status == 403:
            logger.error(f"{operation}: Auth-Fehler ({status})")
            raise ThingsBoardAuthError()
        
        if status == 404:
            logger.warning(f"{operation}: Resource nicht gefunden")
            raise ThingsBoardNotFoundError(operation, "unknown")
        
        if status == 429:
            retry_after = response.headers.get("Retry-After")
            logger.warning(f"{operation}: Rate Limit erreicht")
            raise ThingsBoardRateLimitError(
                int(retry_after) if retry_after else None
            )
        
        if status >= 500:
            logger.error(f"{operation}: Server-Fehler ({status})")
            raise ThingsBoardServerError(status)
        
        # Standard raise_for_status für andere Fehler
        response.raise_for_status()
    
    async def _request(
        self,
        method: str,
        endpoint: str,
        operation_name: str,
        **kwargs
    ) -> Any:
        """
        Zentrale Request-Methode mit Error Handling und Retry.
        
        Args:
            method: HTTP Methode (GET, POST, etc.)
            endpoint: API Endpoint (ohne Base URL)
            operation_name: Name für Logging
            **kwargs: Weitere httpx-Parameter
        
        Returns:
            JSON Response
        """
        await self._ensure_token()
        
        url = f"{self.base_url}{endpoint}"
        
        async def _do_request():
            logger.debug(f"{operation_name}: {method} {endpoint}")
            
            response = await self._client.request(
                method,
                url,
                headers=self._headers(),
                **kwargs
            )
            self._handle_response_errors(response, operation_name)
            return response.json()
        
        try:
            return await retry_with_backoff(_do_request)
        except httpx.ConnectError as e:
            raise ThingsBoardConnectionError(
                f"Verbindung zu {self.base_url} fehlgeschlagen",
                e
            )
        except httpx.TimeoutException as e:
            raise ThingsBoardConnectionError(
                f"Timeout bei Anfrage an {endpoint}",
                e
            )
    
    # =========================================================================
    # API METHODS
    # =========================================================================
    
    async def list_devices(self) -> list[dict[str, Any]]:
        """Listet alle verfügbaren Devices."""
        data = await self._request(
            "GET",
            "/api/tenant/devices",
            "list_devices",
            params={"pageSize": 100, "page": 0}
        )
        
        devices = [
            {
                "id": device["id"]["id"],
                "name": device["name"],
                "type": device.get("type", ""),
                "label": device.get("label", ""),
            }
            for device in data.get("data", [])
        ]
        
        logger.info(f"list_devices: {len(devices)} Devices gefunden")
        return devices
    
    async def get_device_info(self, device_id: str) -> dict[str, Any]:
        """Gibt Detailinformationen zu einem Device zurück."""
        try:
            device = await self._request(
                "GET",
                f"/api/device/{device_id}",
                "get_device_info"
            )
        except ThingsBoardNotFoundError:
            raise ThingsBoardNotFoundError("Device", device_id)
        
        result = {
            "id": device["id"]["id"],
            "name": device["name"],
            "type": device.get("type", ""),
            "label": device.get("label", ""),
            "created_time": device.get("createdTime"),
        }
        
        logger.info(f"get_device_info: {result['name']}")
        return result
    
    async def get_telemetry_keys(self, device_id: str) -> list[str]:
        """Listet alle verfügbaren Telemetrie-Keys für ein Device."""
        keys = await self._request(
            "GET",
            f"/api/plugins/telemetry/DEVICE/{device_id}/keys/timeseries",
            "get_telemetry_keys"
        )
        
        logger.info(f"get_telemetry_keys: {len(keys)} Keys gefunden")
        return keys
    
    async def get_latest_telemetry(
        self,
        device_id: str,
        keys: list[str],
    ) -> dict[str, Any]:
        """Holt die aktuellsten Telemetrie-Werte."""
        data = await self._request(
            "GET",
            f"/api/plugins/telemetry/DEVICE/{device_id}/values/timeseries",
            "get_latest_telemetry",
            params={"keys": ",".join(keys)}
        )
        
        result = {}
        for key, values in data.items():
            if values:
                result[key] = {
                    "value": values[0]["value"],
                    "timestamp": values[0]["ts"],
                }
        
        logger.info(f"get_latest_telemetry: {len(result)} Werte geholt")
        return result
    
    async def get_telemetry(
        self,
        device_id: str,
        keys: list[str],
        start_ts: int,
        end_ts: int,
        limit: int = 50000,
    ) -> dict[str, list[dict[str, Any]]]:
        """Holt Telemetrie-Zeitreihen für einen Zeitraum."""
        data = await self._request(
            "GET",
            f"/api/plugins/telemetry/DEVICE/{device_id}/values/timeseries",
            "get_telemetry",
            params={
                "keys": ",".join(keys),
                "startTs": start_ts,
                "endTs": end_ts,
                "limit": limit,
            }
        )
        
        result = {}
        total_points = 0
        for key, values in data.items():
            result[key] = [
                {"value": v["value"], "timestamp": v["ts"]}
                for v in values
            ]
            total_points += len(result[key])
        
        logger.info(f"get_telemetry: {total_points} Punkte für {len(keys)} Keys")
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
        data = await self._request(
            "GET",
            f"/api/plugins/telemetry/DEVICE/{device_id}/values/timeseries",
            "get_telemetry_aggregated",
            params={
                "keys": ",".join(keys),
                "startTs": start_ts,
                "endTs": end_ts,
                "interval": interval,
                "agg": aggregation,
            }
        )
        
        result = {}
        total_points = 0
        for key, values in data.items():
            result[key] = [
                {"value": v["value"], "timestamp": v["ts"]}
                for v in values
            ]
            total_points += len(result[key])
        
        logger.info(
            f"get_telemetry_aggregated: {total_points} Punkte "
            f"(interval={interval}ms, agg={aggregation})"
        )
        return result
    
    async def get_attribute_keys(self, device_id: str) -> dict[str, list[str]]:
        """Listet alle verfügbaren Attribut-Keys für ein Device."""
        result = {}
        
        for scope in ["SERVER_SCOPE", "SHARED_SCOPE", "CLIENT_SCOPE"]:
            try:
                keys = await self._request(
                    "GET",
                    f"/api/plugins/telemetry/DEVICE/{device_id}/keys/attributes/{scope}",
                    f"get_attribute_keys_{scope}"
                )
                if keys:
                    result[scope] = keys
            except ThingsBoardNotFoundError:
                # Scope existiert nicht - ignorieren
                pass
        
        total_keys = sum(len(v) for v in result.values())
        logger.info(f"get_attribute_keys: {total_keys} Keys in {len(result)} Scopes")
        return result
    
    async def get_attributes(
        self,
        device_id: str,
        keys: list[str],
    ) -> dict[str, Any]:
        """Holt Attribut-Werte für ein Device."""
        data = await self._request(
            "GET",
            f"/api/plugins/telemetry/DEVICE/{device_id}/values/attributes",
            "get_attributes",
            params={"keys": ",".join(keys)}
        )
        
        result = {item["key"]: item["value"] for item in data}
        
        logger.info(f"get_attributes: {len(result)} Attribute geholt")
        return result


# =============================================================================
# TEST
# =============================================================================

async def test_client():
    """Schnelltest des Clients."""
    print(f"\n🔌 Verbinde mit ThingsBoard: {THINGSBOARD_URL}")
    print(f"📟 Device ID: {KRC5_DEVICE_ID}")
    
    try:
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
            
    except ThingsBoardAuthError as e:
        print(f"\n❌ Auth-Fehler: {e.message}")
        print(f"   Hint: {e.details.get('hint')}")
    except ThingsBoardConnectionError as e:
        print(f"\n❌ Verbindungsfehler: {e.message}")
        print(f"   Hint: {e.details.get('hint')}")
    except ThingsBoardError as e:
        print(f"\n❌ ThingsBoard-Fehler: {e.message}")


if __name__ == "__main__":
    asyncio.run(test_client())
