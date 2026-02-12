#!/usr/bin/env python3
"""
E2E Test für Korrelationsanfrage über Chainlit WebSocket API.
Nutzt httpx für HTTP-Requests und websockets für Chat-Interaktion.
"""
import asyncio
import json
import time
from pathlib import Path
import httpx
import websockets

CHAINLIT_URL = "http://localhost:8000"
WS_URL = "ws://localhost:8000/ws"
QUERY = "Kannst du mir sagen ob es eine Korrelation zwischen Position und Drehmoment der letzten 40 Minuten gibt?"
TIMEOUT = 120  # Sekunden


async def test_correlation_query():
    """
    Testet die Korrelationsanfrage über Chainlit WebSocket.

    Returns:
        dict: {"success": bool, "response": str, "errors": list, "duration": float}
    """
    result = {
        "success": False,
        "response": "",
        "errors": [],
        "duration": 0.0,
        "has_correlation_keywords": False,
        "has_error_keywords": False
    }

    start_time = time.time()

    try:
        # 1. HTTP Request für Session-Init (falls nötig)
        async with httpx.AsyncClient() as http_client:
            resp = await http_client.get(CHAINLIT_URL)
            if resp.status_code != 200:
                result["errors"].append(f"HTTP GET {CHAINLIT_URL} failed: {resp.status_code}")
                return result

        # 2. WebSocket Connection
        async with websockets.connect(WS_URL) as ws:
            print(f"WebSocket verbunden: {WS_URL}")

            # 3. Warte auf Init-Nachricht von Chainlit
            init_msg = await asyncio.wait_for(ws.recv(), timeout=10)
            print(f"Init-Nachricht erhalten: {init_msg[:200]}...")

            # 4. Sende Query
            query_msg = {
                "type": "user_message",
                "data": {
                    "content": QUERY
                }
            }
            await ws.send(json.dumps(query_msg))
            print(f"Query gesendet: {QUERY}")

            # 5. Sammle Antwort-Chunks
            response_parts = []
            done = False
            timeout_at = time.time() + TIMEOUT

            while not done and time.time() < timeout_at:
                try:
                    msg_raw = await asyncio.wait_for(ws.recv(), timeout=5)
                    msg = json.loads(msg_raw)

                    print(f"Nachricht empfangen: type={msg.get('type')}, keys={list(msg.keys())}")

                    # Prüfe verschiedene Chainlit-Message-Typen
                    if msg.get("type") == "message":
                        content = msg.get("data", {}).get("content", "")
                        if content:
                            response_parts.append(content)
                            print(f"Content-Chunk: {content[:100]}...")

                    elif msg.get("type") == "stream":
                        delta = msg.get("data", {}).get("delta", "")
                        if delta:
                            response_parts.append(delta)

                    elif msg.get("type") == "end_stream":
                        done = True
                        print("Stream beendet")

                    elif msg.get("type") == "error":
                        error_msg = msg.get("data", {}).get("message", "Unknown error")
                        result["errors"].append(f"Chainlit Error: {error_msg}")
                        done = True

                except asyncio.TimeoutError:
                    # Kein neues Chunk innerhalb 5s - prüfe ob wir schon eine Antwort haben
                    if response_parts:
                        print("Timeout beim Warten auf weitere Chunks, aber Antwort vorhanden")
                        done = True
                    continue
                except json.JSONDecodeError as e:
                    result["errors"].append(f"JSON decode error: {e}")
                    continue

            if time.time() >= timeout_at and not response_parts:
                result["errors"].append(f"Timeout nach {TIMEOUT}s ohne Antwort")
                return result

            # 6. Zusammensetzen der Antwort
            result["response"] = "".join(response_parts)
            result["duration"] = time.time() - start_time

            # 7. Validierung
            response_lower = result["response"].lower()

            # Fehler-Keywords
            error_keywords = ["fehler aufgetreten", "error", "traceback", "konnte nicht", "tool_use ids without tool_result"]
            result["has_error_keywords"] = any(kw in response_lower for kw in error_keywords)

            # Korrelations-Keywords
            corr_keywords = ["korrelation", "pearson", "spearman", "zusammenhang", "korreliert", "r =", "r=", "ρ =", "ρ="]
            result["has_correlation_keywords"] = any(kw in response_lower for kw in corr_keywords)

            # Success = keine Fehler UND Korrelations-Keywords vorhanden
            result["success"] = not result["has_error_keywords"] and result["has_correlation_keywords"] and len(result["response"]) > 50

            return result

    except Exception as e:
        result["errors"].append(f"Exception: {type(e).__name__}: {e}")
        result["duration"] = time.time() - start_time
        return result


async def main():
    print("=" * 80)
    print("E2E Test: Korrelationsanfrage")
    print("=" * 80)
    print(f"Query: {QUERY}")
    print(f"Timeout: {TIMEOUT}s\n")

    result = await test_correlation_query()

    print("\n" + "=" * 80)
    print("ERGEBNIS")
    print("=" * 80)
    print(f"Success: {result['success']}")
    print(f"Duration: {result['duration']:.1f}s")
    print(f"Response length: {len(result['response'])} characters")
    print(f"Has correlation keywords: {result['has_correlation_keywords']}")
    print(f"Has error keywords: {result['has_error_keywords']}")

    if result['errors']:
        print(f"\nErrors ({len(result['errors'])}):")
        for err in result['errors']:
            print(f"  - {err}")

    print(f"\nResponse:\n{'-' * 80}")
    print(result['response'])
    print('-' * 80)

    # Exit code
    exit(0 if result['success'] else 1)


if __name__ == "__main__":
    asyncio.run(main())
