"""
Data Agent für ThingsBoard-Datenabfragen.

Nutzt MCP (Model Context Protocol) um mit dem ThingsBoard Server zu kommunizieren.

WICHTIG: Der MCP Server speichert große Datenmengen in Dateien.
Der Data Agent liest diese Dateien und lädt die Daten in den State.
So landen die Rohdaten NICHT im LLM-Context!
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import json
import asyncio
import traceback
from typing import Any
from contextlib import asynccontextmanager

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
from langgraph.prebuilt import create_react_agent

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_mcp_adapters.tools import load_mcp_tools

from agents.state import AgentState
from prompts.data_agent_prompt import DATA_AGENT_SYSTEM_PROMPT
from config.settings import ANTHROPIC_API_KEY, DEFAULT_MODEL, PROJECT_ROOT


# Pfad zum MCP Server
MCP_SERVER_PATH = PROJECT_ROOT / "mcp_servers" / "thingsboard_server.py"

# Debug-Modus
DEBUG = False


# =============================================================================
# DATENVALIDIERUNG
# =============================================================================

def is_error_value(value: Any) -> bool:
    """
    Prüft ob ein Wert eine Fehlermeldung ist statt eines gültigen Messwerts.
    
    Erkennt verschiedene Fehlermuster:
    - "Bad status code: ..."
    - "Error: ..."
    - "null", "None", "NaN"
    - OPC-UA Fehler
    - Leere Strings
    """
    if value is None:
        return True
    
    if isinstance(value, (int, float)):
        return False  # Numerisch = gültig
    
    if isinstance(value, str):
        value_lower = value.lower().strip()
        
        if not value_lower:
            return True  # Leerer String
        
        # Bekannte Fehlermuster
        error_patterns = [
            "bad status",
            "error",
            "unavailable",
            "null",
            "nan",
            "invalid",
            "failed",
            "timeout",
            "exception",
            "not found",
            "no data",
            "bad_",  # OPC-UA Status codes
            "nodeid",
            "statuscode",
        ]
        
        for pattern in error_patterns:
            if pattern in value_lower:
                return True
        
        # Versuche als Zahl zu parsen
        try:
            float(value)
            return False  # Ist eine Zahl
        except (ValueError, TypeError):
            # Kein Fehlermuster, aber auch keine Zahl - verdächtig
            if len(value) > 50:  # Lange Strings sind meist Fehlermeldungen
                return True
    
    return False


def validate_data_quality(data: dict) -> dict:
    """
    Validiert die Datenqualität und gibt einen Report zurück.
    
    Args:
        data: Dict mit Keys und Werten im ThingsBoard-Format
        
    Returns:
        {
            "valid": bool,
            "total_points": int,
            "valid_points": int,
            "error_points": int,
            "error_keys": ["key1", ...],
            "error_sample": "Bad status code..."
        }
    """
    if not data or not isinstance(data, dict):
        return {
            "valid": False,
            "total_points": 0,
            "valid_points": 0,
            "error_points": 0,
            "error_keys": [],
            "error_sample": None,
        }
    
    total = 0
    valid = 0
    errors = 0
    error_keys = []
    error_sample = None
    
    for key, values in data.items():
        if not isinstance(values, list):
            # Einzelwert (latest)
            if isinstance(values, dict) and "value" in values:
                total += 1
                if is_error_value(values["value"]):
                    errors += 1
                    if key not in error_keys:
                        error_keys.append(key)
                    if error_sample is None:
                        error_sample = str(values["value"])[:100]
                else:
                    valid += 1
            continue
        
        # Liste von Werten
        key_errors = 0
        for point in values:
            total += 1
            if isinstance(point, dict) and "value" in point:
                if is_error_value(point["value"]):
                    key_errors += 1
                    if error_sample is None:
                        error_sample = str(point["value"])[:100]
                else:
                    valid += 1
            elif isinstance(point, (int, float)):
                valid += 1
            else:
                key_errors += 1
        
        errors += key_errors
        if key_errors > 0:
            error_keys.append(key)
    
    # Daten sind gültig wenn mindestens 50% der Punkte ok sind
    is_valid = valid > 0 and (valid / max(total, 1)) >= 0.5
    
    return {
        "valid": is_valid,
        "total_points": total,
        "valid_points": valid,
        "error_points": errors,
        "error_percentage": round(100 * errors / max(total, 1), 1),
        "error_keys": error_keys,
        "error_sample": error_sample,
    }


def debug_print(msg: str):
    """Gibt Debug-Nachrichten aus wenn DEBUG=True."""
    if DEBUG:
        print(f"🔍 DEBUG: {msg}")


@asynccontextmanager
async def mcp_client_context():
    """Async Context Manager für MCP Client."""
    server_params = StdioServerParameters(
        command="python",
        args=[str(MCP_SERVER_PATH)],
        env=None,
    )
    
    debug_print(f"Starte MCP Server: {MCP_SERVER_PATH}")
    
    async with stdio_client(server_params) as (read_stream, write_stream):
        debug_print("stdio_client gestartet")
        async with ClientSession(read_stream, write_stream) as session:
            debug_print("ClientSession erstellt")
            await session.initialize()
            debug_print("Session initialisiert")
            tools = await load_mcp_tools(session)
            debug_print(f"Tools geladen: {[t.name for t in tools]}")
            yield tools


def create_data_agent(tools: list):
    """Erstellt den Data Agent mit den gegebenen Tools."""
    debug_print(f"Erstelle Agent mit Model: {DEFAULT_MODEL}")
    
    llm = ChatAnthropic(
        model=DEFAULT_MODEL,
        api_key=ANTHROPIC_API_KEY,
        temperature=0,
    )
    
    agent = create_react_agent(llm, tools)
    
    return agent


def extract_text_from_tool_content(content: Any) -> str | None:
    """
    Extrahiert den Text aus ToolMessage.content.
    
    Content kann sein:
    - String (direkt)
    - Liste von Content-Blöcken: [{'type': 'text', 'text': '...'}]
    """
    if content is None:
        return None
    
    if isinstance(content, str):
        return content
    
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get('type') == 'text':
                return block.get('text')
            if isinstance(block, str):
                return block
    
    if isinstance(content, dict) and 'text' in content:
        return content['text']
    
    return None


def parse_json_safe(text: str) -> Any:
    """Parst JSON sicher."""
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def load_data_from_file(filepath: str) -> dict | None:
    """
    Lädt Daten aus einer JSON-Datei.
    
    Args:
        filepath: Pfad zur JSON-Datei
        
    Returns:
        Die geladenen Daten oder None bei Fehler
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        debug_print(f"Fehler beim Laden von {filepath}: {e}")
        return None


def extract_data_from_parsed(parsed: Any) -> tuple[Any, dict | None, str | None]:
    """
    Extrahiert Daten aus geparstem Content.
    
    Returns:
        (data, meta, data_file_path)
    """
    if parsed is None:
        return None, None, None
    
    # NO_DATA Response - WICHTIG: Muss zuerst geprüft werden!
    # Format: {"status": "no_data", "message": "...", "requested_timerange": {...}}
    if isinstance(parsed, dict) and parsed.get("status") == "no_data":
        debug_print(f"NO_DATA erkannt: {parsed.get('message')}")
        return None, {
            "type": "no_data",
            "message": parsed.get("message"),
            "requested_timerange": parsed.get("requested_timerange"),
            "hint": parsed.get("hint"),
        }, None
    
    # DATA_AVAILABILITY Response
    # Format: {"status": "data_available", "data_range": {...}, "message": "..."}
    if isinstance(parsed, dict) and parsed.get("status") == "data_available":
        debug_print(f"DATA_AVAILABLE erkannt: {parsed.get('message')}")
        data_range = parsed.get("data_range", {})
        return parsed, {
            "type": "data_availability",
            "data_range": data_range,
            "message": parsed.get("message"),
            "total_points": parsed.get("total_points"),
        }, None
    
    # SUCCESS Response mit data_file
    # Format: {"status": "success", "statistics": {...}, "data_file": "/path/to/file.json", ...}
    if isinstance(parsed, dict) and parsed.get("status") == "success" and "data_file" in parsed:
        data_file = parsed.get("data_file")
        debug_print(f"SUCCESS mit data_file: {data_file}")
        
        # Lade die echten Daten aus der Datei
        file_data = load_data_from_file(data_file)
        if file_data and "data" in file_data:
            data = file_data["data"]
            meta = {
                "type": "success",
                "timerange": parsed.get("timerange") or file_data.get("timerange"),
                "data_points": parsed.get("data_points"),
                "statistics": parsed.get("statistics"),
                "interval_ms": file_data.get("interval_ms"),
                "aggregation": file_data.get("aggregation"),
            }
            return data, meta, data_file
    
    # ALTES FORMAT (Fallback): Daten direkt in der Response
    if isinstance(parsed, dict) and "data" in parsed and "data_points" in parsed:
        return parsed["data"], {
            "type": "success",
            "timerange": parsed.get("timerange"),
            "data_points": parsed.get("data_points"),
            "interval_ms": parsed.get("interval_ms"),
            "aggregation": parsed.get("aggregation"),
        }, None
    
    # get_latest_telemetry Response
    # Format: {"axis_act_a1_deg": {"value": "13.82", "timestamp": 123}}
    if isinstance(parsed, dict) and parsed:
        first_key = next(iter(parsed.keys()), None)
        first_val = parsed.get(first_key) if first_key else None
        if isinstance(first_val, dict) and "value" in first_val:
            return parsed, {"type": "latest", "data_points": {k: 1 for k in parsed}}, None
    
    # Liste (z.B. list_telemetry_keys, list_devices)
    if isinstance(parsed, list):
        return parsed, {"type": "list", "count": len(parsed)}, None
    
    # Sonstiges dict
    if isinstance(parsed, dict):
        return parsed, {"type": "other", "keys": list(parsed.keys())}, None
    
    return None, None, None


def generate_data_summary(data: Any, meta: dict | None, quality: dict | None = None) -> str:
    """Generiert eine kurze Zusammenfassung der Daten inkl. Qualitätswarnung."""
    
    # ZUERST: Qualitätsproblem melden!
    if quality and not quality.get("valid", True):
        error_pct = quality.get("error_percentage", 100)
        error_keys = quality.get("error_keys", [])
        valid_pts = quality.get("valid_points", 0)
        total_pts = quality.get("total_points", 0)
        
        if error_pct >= 95:
            # Fast alle Daten fehlerhaft
            keys_str = ", ".join(error_keys[:3])
            return f"FEHLERHAFTE DATEN: Die Messwerte für {keys_str} enthalten ungültige Werte (OPC-UA/Sensor-Fehler). {error_pct:.0f}% der {total_pts} Datenpunkte sind fehlerhaft. Der Sensor liefert möglicherweise keine gültigen Daten."
        elif error_pct > 50:
            # Mehr als die Hälfte fehlerhaft
            return f"DATENQUALITÄT EINGESCHRÄNKT: {error_pct:.0f}% der Daten sind fehlerhaft. Nur {valid_pts} von {total_pts} Messwerten sind gültig."
    
    # NO_DATA - Klare Fehlermeldung!
    if meta and meta.get("type") == "no_data":
        message = meta.get("message", "Keine Daten gefunden.")
        timerange = meta.get("requested_timerange", {})
        weekday = timerange.get("weekday", "")
        start = timerange.get("start", "")
        end = timerange.get("end", "")
        
        if weekday and start:
            return f"KEINE DATEN: Für {weekday}, {start} bis {end} sind keine Daten verfügbar. Der Roboter war zu diesem Zeitpunkt möglicherweise nicht aktiv."
        return f"KEINE DATEN: {message}"
    
    # DATA_AVAILABILITY - Zeige verfügbaren Zeitraum
    if meta and meta.get("type") == "data_availability":
        data_range = meta.get("data_range", {})
        first_data = data_range.get("first_data", "?")
        first_weekday = data_range.get("first_weekday", "")
        last_data = data_range.get("last_data", "?")
        last_weekday = data_range.get("last_weekday", "")
        total_points = meta.get("total_points", "?")
        
        return f"DATEN VERFÜGBAR: Von {first_weekday}, {first_data} bis {last_weekday}, {last_data} ({total_points} Datenpunkte in der letzten Woche)"
    
    if data is None:
        return "Keine Daten erhalten."
    
    # Statistiken vorhanden? Dann nutze diese für die Zusammenfassung
    if meta and meta.get("statistics"):
        stats = meta["statistics"]
        summaries = []
        for key, stat in stats.items():
            if isinstance(stat, dict):
                avg = stat.get("avg", "?")
                min_val = stat.get("min", "?")
                max_val = stat.get("max", "?")
                count = stat.get("count", "?")
                summaries.append(f"{key}: Ø {avg} (min: {min_val}, max: {max_val}, {count} Punkte)")
        if summaries:
            timerange = meta.get("timerange", {})
            time_str = ""
            weekday = ""
            if isinstance(timerange, dict):
                weekday = timerange.get("weekday", "")
                start = timerange.get("start", "?")
                end = timerange.get("end", "?")
                time_str = f" am {weekday}, {start} bis {end}" if weekday else f" von {start} bis {end}"
            return f"Daten{time_str}: " + "; ".join(summaries)
    
    # Aktuellste Werte (get_latest_telemetry)
    if meta and meta.get("type") == "latest":
        summaries = []
        for key, val in data.items():
            if isinstance(val, dict) and "value" in val:
                value = val.get('value')
                weekday = val.get('weekday', '')
                timestamp = val.get('timestamp_human', '')
                if weekday and timestamp:
                    summaries.append(f"{key}: {value} ({weekday}, {timestamp})")
                else:
                    summaries.append(f"{key}: {value}")
        if summaries:
            return f"Aktuelle Werte: {', '.join(summaries)}"
    
    # Zeitreihen (get_telemetry, get_telemetry_aggregated)
    if meta and meta.get("data_points"):
        total_points = sum(meta["data_points"].values())
        keys = list(meta["data_points"].keys())
        agg = meta.get("aggregation", "")
        agg_str = f" ({agg})" if agg else ""
        return f"{total_points} Datenpunkte{agg_str} für {', '.join(keys)} geladen."
    
    # Listen
    if meta and meta.get("type") == "list":
        count = meta.get("count", len(data) if isinstance(data, list) else 0)
        return f"{count} Einträge geladen."
    
    if isinstance(data, list):
        return f"{len(data)} Einträge geladen."
    
    if isinstance(data, dict):
        return f"Daten mit {len(data)} Feldern abgerufen."
    
    return "Daten erfolgreich abgerufen."


def detect_needs_user_input(messages: list) -> tuple[bool, str | None]:
    """
    Erkennt ob der Agent User-Input benötigt BEVOR er weitermachen kann.
    
    WICHTIG: 
    - Nur bei ECHTEN Stopp-Situationen True zurückgeben
    - Höfliche Nachfragen am Ende erfolgreicher Analysen sind KEIN Stopp!
    - False Positives vermeiden (z.B. Auflistungen in Analysen)
    
    Returns:
        (needs_input, reason)
    """
    # Finde letzte AI-Message
    last_ai_content = ""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and isinstance(msg.content, str):
            last_ai_content = msg.content.lower()
            break
    
    if not last_ai_content:
        return False, None
    
    # Wenn Daten erfolgreich geladen wurden, ist es KEIN Stopp
    success_indicators = [
        "erfolgreich",
        "geladen",
        "datenpunkte",
        "hier ist",
        "hier sind",
        "zusammenfassung",
        "analyse",
        "statistik",
    ]
    
    has_success = any(ind in last_ai_content for ind in success_indicators)
    
    # Patterns die auf ECHTEN Stopp hindeuten (User MUSS entscheiden)
    hard_stop_patterns = [
        "keine daten für den zeitraum",
        "keine daten gefunden",
        "nicht verfügbar",
        "konnte nicht gefunden werden",
        "fehlgeschlagen",
        "nicht möglich",
        "was möchtest du tun?",  # Explizite Aufforderung zur Entscheidung
        "bitte wähle",
    ]
    
    # Prüfe auf harten Stopp
    for pattern in hard_stop_patterns:
        if pattern in last_ai_content:
            # Aber nur wenn es NICHT erfolgreich war!
            if not has_success:
                return True, f"Agent stoppt wegen: '{pattern}'"
    
    # Prüfe auf explizite Optionsliste MIT Stopp-Grund
    has_option_list = ("1." in last_ai_content and "2." in last_ai_content and "3." in last_ai_content)
    
    if has_option_list and not has_success:
        # Checke ob es wirklich Entscheidungs-Optionen sind
        option_words = ["verfügbar", "zeitraum", "prüfen", "angeben", "anzeigen"]
        if any(word in last_ai_content for word in option_words):
            return True, "Agent bietet Optionen nach Problem"
    
    return False, None


async def run_data_agent(state: AgentState) -> dict[str, Any]:
    """Führt den Data Agent aus."""
    try:
        debug_print("Starte run_data_agent")
        
        async with mcp_client_context() as tools:
            debug_print("MCP Context aktiv")
            
            agent = create_data_agent(tools)
            debug_print("Agent erstellt, starte Ausführung...")
            
            messages_with_system = [
                SystemMessage(content=DATA_AGENT_SYSTEM_PROMPT),
                *state["messages"]
            ]
            
            result = await agent.ainvoke({"messages": messages_with_system})
            debug_print(f"Agent fertig, {len(result.get('messages', []))} Messages")
            
            data = None
            meta = None
            data_file = None
            
            # Durchsuche alle Messages nach Tool-Ergebnissen
            for msg in result.get("messages", []):
                msg_type = type(msg).__name__
                debug_print(f"Message type: {msg_type}")
                
                if isinstance(msg, ToolMessage):
                    text_content = extract_text_from_tool_content(msg.content)
                    debug_print(f"Extracted text: {text_content[:300] if text_content else 'None'}...")
                    
                    if text_content:
                        parsed = parse_json_safe(text_content)
                        debug_print(f"Parsed type: {type(parsed)}")
                        
                        if parsed is not None:
                            extracted_data, extracted_meta, extracted_file = extract_data_from_parsed(parsed)
                            
                            if extracted_data is not None:
                                # Priorisiere Daten mit Statistiken über Listen
                                current_is_list = meta and meta.get("type") == "list"
                                new_has_stats = extracted_meta and extracted_meta.get("statistics")
                                new_is_not_list = extracted_meta and extracted_meta.get("type") != "list"
                                
                                if data is None or (current_is_list and new_is_not_list) or new_has_stats:
                                    data = extracted_data
                                    meta = extracted_meta
                                    data_file = extracted_file
                                    debug_print(f"Daten extrahiert: meta keys={list(meta.keys()) if meta else None}, file={data_file}")
            
            # Datenqualität prüfen
            quality = None
            if data and isinstance(data, dict):
                quality = validate_data_quality(data)
                debug_print(f"Datenqualität: valid={quality['valid']}, errors={quality['error_percentage']}%")
                
                # Qualitätsdaten in meta speichern
                if meta:
                    meta["quality"] = quality
            
            # Summary generieren (mit Qualitätsinfo)
            summary = generate_data_summary(data, meta, quality)
            debug_print(f"Summary: {summary}")
            
            # Prüfen ob User-Input benötigt wird
            needs_input, input_reason = detect_needs_user_input(result.get("messages", []))
            debug_print(f"needs_user_input: {needs_input}, reason: {input_reason}")
            
            return {
                "messages": result.get("messages", []),
                "data": data,
                "data_meta": meta,
                "data_summary": summary,
                "needs_user_input": needs_input,
                "user_input_reason": input_reason,
            }
        
    except Exception as e:
        error_details = traceback.format_exc()
        if DEBUG:
            print(f"\n❌ FEHLER DETAILS:\n{error_details}")
        
        error_msg = f"Fehler beim Datenabruf: {str(e)}"
        return {
            "messages": [AIMessage(content=error_msg)],
            "error": error_msg,
        }


async def data_agent_node(state: AgentState) -> dict[str, Any]:
    """LangGraph Node für den Data Agent."""
    return await run_data_agent(state)


# =============================================================================
# STANDALONE TEST
# =============================================================================

async def test_data_agent():
    """Test des Data Agents mit verschiedenen Queries."""
    
    test_queries = [
        "Wie ist die aktuelle Position von Achse 1?",
        "Zeig mir den Verlauf der Bahngeschwindigkeit der letzten 10 Minuten",
        "Welche Telemetrie-Keys sind verfügbar?",
    ]
    
    for query in test_queries:
        print(f"\n{'='*60}")
        print(f"📝 Query: {query}")
        print("="*60)
        
        state = AgentState(
            messages=[HumanMessage(content=query)]
        )
        
        result = await run_data_agent(state)
        
        print(f"\n📊 Data Summary: {result.get('data_summary', 'N/A')}")
        
        if result.get("data_meta"):
            print(f"📈 Meta: {result['data_meta']}")
        
        if result.get("data"):
            data = result["data"]
            if isinstance(data, dict):
                print(f"📁 Data keys: {list(data.keys())}")
                for key in list(data.keys())[:2]:
                    vals = data[key]
                    if isinstance(vals, list) and len(vals) > 0:
                        print(f"   {key}: {len(vals)} Einträge, erster: {vals[0]}")
        
        if result.get("error"):
            print(f"❌ Error: {result['error']}")
        
        # Letzte AI-Message anzeigen
        for msg in reversed(result.get("messages", [])):
            if isinstance(msg, AIMessage) and isinstance(msg.content, str):
                print(f"\n🤖 Agent: {msg.content[:500]}")
                break
        
        print()


async def interactive_test():
    """Interaktiver Test mit eigenen Queries."""
    print("\n" + "="*60)
    print("🤖 Data Agent Interactive Test")
    print("="*60)
    print("Gib eine Frage ein (oder 'quit' zum Beenden):\n")
    
    while True:
        query = input("📝 Query: ").strip()
        
        if query.lower() in ["quit", "exit", "q"]:
            break
        
        if not query:
            continue
        
        state = AgentState(
            messages=[HumanMessage(content=query)]
        )
        
        print("\n⏳ Verarbeite...")
        result = await run_data_agent(state)
        
        print(f"\n📊 Data Summary: {result.get('data_summary', 'N/A')}")
        
        if result.get("data_meta"):
            print(f"📈 Meta: {result['data_meta']}")
        
        if result.get("error"):
            print(f"❌ Error: {result['error']}")
        
        for msg in reversed(result.get("messages", [])):
            if isinstance(msg, AIMessage) and isinstance(msg.content, str):
                print(f"\n🤖 Agent: {msg.content}")
                break
        
        print("\n" + "-"*40)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--interactive":
        asyncio.run(interactive_test())
    else:
        asyncio.run(test_data_agent())
