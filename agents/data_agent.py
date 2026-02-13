"""
Data Agent für ThingsBoard-Datenabfragen.

Nutzt MCP (Model Context Protocol) um mit dem ThingsBoard Server zu kommunizieren.

DESIGN-ENTSCHEIDUNGEN:
- DEC-005: MCP Session wird EINMAL beim Start erstellt und wiederverwendet
- DEC-013: Datasets werden über Turns akkumuliert (nicht überschrieben)
- DEC-014: SystemMessages aus State filtern
- DEC-016: Strukturiertes Logging, Retry-Mechanismus, Funktionsaufteilung
- DEC-023: Data Retrieval Mode (detail vs overview) aus State lesen
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import json
import asyncio
import logging
from contextlib import AsyncExitStack
from datetime import datetime
from typing import Any, Tuple, Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
from langgraph.prebuilt import create_react_agent

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_mcp_adapters.tools import load_mcp_tools

from langchain_core.tools import tool

from agents.state import AgentState, DatasetMeta
from agents.utils import extract_user_query, get_dataset_meta_from_duckdb
from prompts.data_agent_prompt import get_data_agent_prompt
from config.settings import DEFAULT_MODEL, PROJECT_ROOT, api_key_rotator, create_anthropic_client, create_cached_system_message
from config.duckdb_store import SessionStore, generate_dataset_key, determine_signal_type
from mcp_servers.thingsboard_server import (
    check_raw_datapoint_limit, parse_datetime as parse_dt, RAW_DATAPOINT_THRESHOLD,
    calculate_expected_datapoints, snap_to_interval, INTERVAL_OPTIONS,
)


# =============================================================================
# LOGGING KONFIGURATION (DEC-016)
# =============================================================================

logger = logging.getLogger(__name__)

# Pfad zum MCP Server
MCP_SERVER_PATH = PROJECT_ROOT / "mcp_servers" / "thingsboard_server.py"

# Retry-Konfiguration
MAX_RETRIES = 3
RETRY_DELAY_BASE = 2  # Sekunden


# =============================================================================
# MCP TOOLS PROVIDER (DEC-005, DEC-016)
# =============================================================================

class MCPToolsProvider:
    """
    Verwaltet MCP Tools mit Caching und sauberem Lifecycle.
    
    Vorteile gegenüber globalen Variablen:
    - Testbar (kann gemockt werden)
    - Klarer Lifecycle (init, cleanup)
    - Thread-safe durch Lock
    """
    
    def __init__(self, server_path: Path = MCP_SERVER_PATH):
        self._tools: list | None = None
        self._exit_stack: AsyncExitStack | None = None
        self._lock = asyncio.Lock()
        self._server_path = server_path
    
    async def get_tools(self) -> list:
        """Holt MCP Tools - startet Server nur beim ersten Aufruf."""
        # Schneller Check ohne Lock
        if self._tools is not None:
            logger.debug("MCP Tools aus Cache")
            return self._tools
        
        # Mit Lock für Thread-Safety
        async with self._lock:
            # Double-Check nach Lock
            if self._tools is not None:
                return self._tools
            
            logger.info("Starte MCP Server (einmalig)...")
            
            server_params = StdioServerParameters(
                command="python",
                args=[str(self._server_path)],
                env=None,
            )
            
            self._exit_stack = AsyncExitStack()
            
            streams = await self._exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            read_stream, write_stream = streams
            
            session = await self._exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await session.initialize()
            
            self._tools = await load_mcp_tools(session)
            
            logger.info(f"MCP Server gestartet, {len(self._tools)} Tools geladen")
            
            return self._tools
    
    async def cleanup(self):
        """Räumt MCP Session auf."""
        if self._exit_stack:
            await self._exit_stack.aclose()
            self._exit_stack = None
        self._tools = None
        logger.debug("MCP Session aufgeräumt")
    
    def is_initialized(self) -> bool:
        """Prüft ob Tools geladen sind."""
        return self._tools is not None


# Globale Instanz (kann in Tests ersetzt werden)
_mcp_provider = MCPToolsProvider()


async def get_mcp_tools() -> list:
    """Wrapper für Rückwärtskompatibilität."""
    return await _mcp_provider.get_tools()


async def cleanup_mcp():
    """Wrapper für Rückwärtskompatibilität."""
    await _mcp_provider.cleanup()


# =============================================================================
# HILFSFUNKTIONEN - DATENVALIDIERUNG
# =============================================================================

def is_error_value(value: Any) -> bool:
    """Prüft ob ein Wert eine Fehlermeldung ist."""
    if value is None:
        return True
    
    if isinstance(value, (int, float)):
        return False
    
    if isinstance(value, str):
        value_lower = value.lower().strip()
        
        if not value_lower:
            return True
        
        error_patterns = [
            "bad status", "error", "unavailable", "null", "nan",
            "invalid", "failed", "timeout", "exception", "not found",
            "no data", "bad_", "nodeid", "statuscode",
        ]
        
        for pattern in error_patterns:
            if pattern in value_lower:
                return True
        
        try:
            float(value)
            return False
        except (ValueError, TypeError):
            if len(value) > 50:
                return True
    
    return False


def validate_data_quality(data: dict) -> dict:
    """Validiert die Datenqualität und gibt Metriken zurück."""
    if not data or not isinstance(data, dict):
        return {
            "valid": False, "total_points": 0, "valid_points": 0,
            "error_points": 0, "error_keys": [], "error_sample": None,
        }
    
    total = 0
    valid = 0
    errors = 0
    error_keys = []
    error_sample = None
    
    for key, values in data.items():
        if not isinstance(values, list):
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


# =============================================================================
# HILFSFUNKTIONEN - PARSING
# =============================================================================

def extract_text_from_tool_content(content: Any) -> Optional[str]:
    """Extrahiert Text aus ToolMessage.content (verschiedene Formate)."""
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


def parse_json_safe(text: str) -> Optional[Any]:
    """Parst JSON sicher, gibt None bei Fehler zurück."""
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def load_data_from_file(filepath: str) -> Optional[dict]:
    """Lädt Daten aus einer JSON-Datei."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Fehler beim Laden von {filepath}: {e}")
        return None


def extract_data_from_parsed(
    parsed: Any
) -> Tuple[Optional[Any], Optional[dict], Optional[str]]:
    """
    Extrahiert Daten aus geparstem Tool-Response.
    
    Returns:
        Tuple von (data, meta, data_file)
    """
    if parsed is None:
        return None, None, None
    
    # ERROR Response (DEC-009)
    if isinstance(parsed, dict) and parsed.get("status") == "error":
        logger.debug(f"ERROR erkannt: {parsed.get('message')}")
        return None, {
            "type": "error",
            "message": parsed.get("message"),
            "error_type": parsed.get("error_type"),
            "details": parsed.get("details"),
        }, None
    
    # NO_DATA Response
    if isinstance(parsed, dict) and parsed.get("status") == "no_data":
        logger.debug(f"NO_DATA erkannt: {parsed.get('message')}")
        return None, {
            "type": "no_data",
            "message": parsed.get("message"),
            "requested_timerange": parsed.get("requested_timerange"),
            "hint": parsed.get("hint"),
            "settings": parsed.get("settings"),
        }, None
    
    # DATA_AVAILABILITY Response
    if isinstance(parsed, dict) and parsed.get("status") == "data_available":
        logger.debug(f"DATA_AVAILABLE erkannt: {parsed.get('message')}")
        return parsed, {
            "type": "data_availability",
            "data_range": parsed.get("data_range", {}),
            "message": parsed.get("message"),
            "total_points": parsed.get("total_points"),
        }, None
    
    # ERROR_TOO_MANY_DATAPOINTS Response (DEC-010)
    if isinstance(parsed, dict) and parsed.get("status") == "error_too_many_datapoints":
        logger.debug(f"TOO_MANY_DATAPOINTS: {parsed.get('message')}")
        return None, {
            "type": "error_datapoints",
            "message": parsed.get("message"),
            "suggestion": parsed.get("suggestion"),
            "user_action": parsed.get("user_action"),
        }, None
    
    # SUCCESS Response mit data_file
    if isinstance(parsed, dict) and parsed.get("status") == "success" and "data_file" in parsed:
        data_file = parsed.get("data_file")
        logger.debug(f"SUCCESS mit data_file: {data_file}")
        
        file_data = load_data_from_file(data_file)
        if file_data and "data" in file_data:
            data = file_data["data"]
            meta = {
                "type": "success",
                "timerange": parsed.get("timerange") or file_data.get("timerange"),
                "data_points": parsed.get("data_points"),
                "statistics": parsed.get("statistics"),
                "settings": parsed.get("settings"),
                "settings_text": parsed.get("settings_text"),
                "user_hint": parsed.get("user_hint"),
                "keys": list(data.keys()) if isinstance(data, dict) else [],
            }
            return data, meta, data_file
    
    # get_latest_telemetry Response
    if isinstance(parsed, dict) and parsed:
        first_key = next(iter(parsed.keys()), None)
        first_val = parsed.get(first_key) if first_key else None
        if isinstance(first_val, dict) and "value" in first_val:
            return parsed, {"type": "latest", "data_points": {k: 1 for k in parsed}}, None
    
    # Liste
    if isinstance(parsed, list):
        return parsed, {"type": "list", "count": len(parsed)}, None
    
    # Sonstiges dict
    if isinstance(parsed, dict):
        return parsed, {"type": "other", "keys": list(parsed.keys())}, None
    
    return None, None, None


# =============================================================================
# HILFSFUNKTIONEN - DATASET HANDLING
# =============================================================================

def determine_dataset_key_legacy(data: Optional[dict], meta: Optional[dict]) -> str:
    """
    Bestimmt einen UNS-inspirierten Dataset-Key (DEC-025).

    Nutzt generate_dataset_key() und determine_signal_type() aus duckdb_store.

    Beispiele:
    - Drehmomente → "krc5/torque/timeseries"
    - Aktuelle Geschwindigkeit → "krc5/velocity/latest"
    """
    if data is None:
        return "unknown"

    if not isinstance(data, dict):
        return "data"

    keys = list(data.keys())
    if not keys:
        return "empty"

    signal_type = determine_signal_type(keys)

    # Datentyp bestimmen
    data_type = "timeseries"
    if meta and meta.get("type") == "latest":
        data_type = "latest"
    elif meta and meta.get("type") == "data_availability":
        data_type = "availability"

    return generate_dataset_key("krc5", signal_type, data_type)


def determine_dataset_key_rich(
    data: dict,
    meta: dict | None,
    data_retrieval_mode: str = "overview",
) -> str:
    """
    Dataset-Key mit MCP-Metadaten: mode, time_range, interval_agg (DEC-026).

    Format: krc5/{signal_type}/{data_type}/{mode}/{time_range}/{interval_agg}

    Beispiel: krc5/torque_actual/timeseries/overview/2025-12-16_12-00_14-00/60s_avg
    """
    if data is None or not isinstance(data, dict) or not data:
        return "unknown"

    keys = list(data.keys())
    # Thema 2: ThingsBoard Key direkt verwenden statt Gruppenname
    # 1 Key (nach Hook-Split der Normalfall) → Key direkt
    # Mehrere Keys → Fallback auf Gruppenname
    signal_type = keys[0] if len(keys) == 1 else determine_signal_type(keys)

    data_type = "timeseries"
    if meta and meta.get("type") == "latest":
        data_type = "latest"
    elif meta and meta.get("type") == "data_availability":
        data_type = "availability"

    settings = (meta or {}).get("settings", {}) or {}
    timerange = (meta or {}).get("timerange", {}) or {}

    time_range = _extract_time_range(timerange)

    interval_agg = ""
    interval = settings.get("interval_human") or ""
    aggregation = (settings.get("aggregation") or "").lower()
    if interval and aggregation:
        interval_clean = interval.replace(" ", "")
        interval_agg = f"{interval_clean}_{aggregation}"

    return generate_dataset_key(
        "krc5", signal_type, data_type,
        data_mode=data_retrieval_mode,
        time_range=time_range,
        interval_agg=interval_agg,
    )


def _extract_time_range(timerange: dict) -> str:
    """
    Extrahiert Time-Range-String aus MCP timerange dict.

    Input:  {"start_human": "16.12.2025 12:00", "end_human": "16.12.2025 14:00"}
    Output: "2025-12-16_12-00_14-00"  (gleicher Tag)
    Output: "2025-12-16_12-00_2025-12-17_08-00"  (verschiedene Tage)
    """
    import re

    def parse_datetime(s: str) -> tuple[str, str]:
        """Returns (date_iso, time_hhmm) or ("", "")."""
        m = re.search(r'(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2})', s)
        if m:
            return f"{m.group(3)}-{m.group(2)}-{m.group(1)}", f"{m.group(4)}-{m.group(5)}"
        m = re.search(r'(\d{4}-\d{2}-\d{2})\s+(\d{2}):(\d{2})', s)
        if m:
            return m.group(1), f"{m.group(2)}-{m.group(3)}"
        return "", ""

    start_str = timerange.get("start_human") or timerange.get("start", "")
    end_str = timerange.get("end_human") or timerange.get("end", "")

    if not start_str:
        return ""

    start_date, start_time = parse_datetime(str(start_str))
    end_date, end_time = parse_datetime(str(end_str))

    if not start_date:
        return ""

    if start_date == end_date:
        # Gleicher Tag: "2025-12-16_12-00_14-00"
        parts = [start_date]
        if start_time:
            parts[0] += f"_{start_time}"
        if end_time:
            parts[0] += f"_{end_time}"
        return parts[0]
    else:
        # Verschiedene Tage
        start = start_date + (f"_{start_time}" if start_time else "")
        end = end_date + (f"_{end_time}" if end_time else "")
        return f"{start}_{end}"


# =============================================================================
# HILFSFUNKTIONEN - USER INPUT DETECTION
# =============================================================================

def detect_needs_user_input(messages: list) -> Tuple[bool, Optional[str]]:
    """Erkennt ob der Agent auf User-Eingabe wartet."""
    last_ai_content = ""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and isinstance(msg.content, str):
            last_ai_content = msg.content.lower()
            break
    
    if not last_ai_content:
        return False, None
    
    success_indicators = [
        "erfolgreich", "geladen", "datenpunkte", "hier ist",
        "hier sind", "zusammenfassung", "analyse", "statistik",
    ]
    
    has_success = any(ind in last_ai_content for ind in success_indicators)
    
    hard_stop_patterns = [
        "keine daten für den zeitraum", "keine daten gefunden",
        "nicht verfügbar", "konnte nicht gefunden werden",
        "fehlgeschlagen", "nicht möglich", "was möchtest du tun?",
        "bitte wähle",
        # Downsampling-Rückfrage bei zu vielen Rohdaten
        "zu viele datenpunkte", "zu viel für eine sinnvolle",
        "statt rohdaten", "durchschnitte verwenden",
        "soll ich stattdessen", "aggregierte daten",
        "kürzeren zeitraum",
    ]
    
    for pattern in hard_stop_patterns:
        if pattern in last_ai_content:
            if not has_success:
                return True, f"Agent stoppt wegen: '{pattern}'"
    
    # Option-Liste ohne Erfolg
    has_option_list = ("1." in last_ai_content and "2." in last_ai_content)
    if has_option_list and not has_success:
        option_words = ["verfügbar", "zeitraum", "prüfen", "angeben"]
        if any(word in last_ai_content for word in option_words):
            return True, "Agent bietet Optionen nach Problem"
    
    return False, None


# =============================================================================
# RAW ESTIMATION HOOK (automatisches Downsampling)
# =============================================================================

# Max Datenpunkte pro Tool-Call (äquidistant über Zeitraum verteilt)
# 20% Toleranz: 5000 Ziel, bis 6000 erlaubt → feineres Intervall möglich
MAX_TOTAL_DATAPOINTS = 6000

# ThingsBoard DATABASE_TS_MAX_INTERVALS (Server-Config, default 700).
# Muss mit dem Server-Wert übereinstimmen — Fallback-Absicherung falls
# MAX_TOTAL_DATAPOINTS > Server-Limit oder Server-Config sich ändert.
TS_MAX_INTERVALS = 10000


def raw_estimation_hook(state: dict) -> dict:
    """
    Post-Model Hook: Fängt get_telemetry(raw=True) Tool-Calls ab und
    berechnet automatisch das optimale Intervall, falls die geschätzte
    Datenpunktanzahl das Budget (MAX_TOTAL_DATAPOINTS) überschreitet.

    Splittet Multi-Key-Calls in Einzel-Key-Calls auf, damit jeder Key
    das volle Budget bekommt und das Intervall minimal bleibt.
    Beispiel: 6 Keys, 40min → 6× Einzel-Call mit 1s statt 1× mit 5s.
    """
    messages = state.get("messages", [])
    if not messages:
        return {}

    last_msg = messages[-1]
    if not isinstance(last_msg, AIMessage) or not last_msg.tool_calls:
        return {}

    new_tool_calls = []
    replaced_ids: dict[str, list[dict]] = {}  # original_id → list of split tool_calls
    modified = False

    for tc in last_msg.tool_calls:
        if tc["name"] != "get_telemetry":
            new_tool_calls.append(tc)
            continue
        args = tc.get("args", {})
        if not args.get("raw", False):
            new_tool_calls.append(tc)
            continue

        try:
            start_dt = parse_dt(args["start_date"], args.get("start_time", "00:00"))
            end_dt = parse_dt(args["end_date"], args.get("end_time", "23:59"))
            keys = [k.strip() for k in args["keys"].split(",")]
        except (KeyError, ValueError) as e:
            logger.warning(f"raw_estimation_hook: Parse-Fehler: {e}")
            new_tool_calls.append(tc)
            continue

        raw_check = check_raw_datapoint_limit(start_dt, end_dt, len(keys))
        if raw_check is None:
            # Unter Threshold — raw durchlassen
            new_tool_calls.append(tc)
            continue

        # Über Threshold: optimales Intervall für EINEN Key berechnen
        # Zwei Constraints: Budget (MAX_TOTAL_DATAPOINTS) und ThingsBoard
        # ts_max_intervals Limit (TS_MAX_INTERVALS) — der strengere gewinnt
        duration_ms = (end_dt - start_dt).total_seconds() * 1000
        budget_interval_ms = int(duration_ms / MAX_TOTAL_DATAPOINTS)
        ts_limit_interval_ms = int(duration_ms / TS_MAX_INTERVALS)
        min_interval_ms = max(budget_interval_ms, ts_limit_interval_ms)
        interval_key, _, interval_human = snap_to_interval(min_interval_ms)

        estimated = raw_check.get("estimated_total_points", 0)
        _, pts_per_call = calculate_expected_datapoints(
            start_dt, end_dt, INTERVAL_OPTIONS[interval_key][0], 1
        )

        # Pro Key einen eigenen Call — maximale Auflösung
        split_calls = []
        for i, key in enumerate(keys):
            split_tc = {
                "id": f"{tc['id']}_{i}",
                "name": "get_telemetry",
                "args": {
                    **args,
                    "keys": key,
                    "raw": False,
                    "interval": interval_key,
                    "aggregation": args.get("aggregation") or "AVG",
                },
            }
            new_tool_calls.append(split_tc)
            split_calls.append(split_tc)

        replaced_ids[tc["id"]] = split_calls
        modified = True
        logger.info(
            f"raw_estimation_hook: {estimated:,} Rohdaten → {len(keys)} Einzel-Calls "
            f"mit {interval_key} ({interval_human}), je ca. {pts_per_call:,} Punkte"
        )

    if modified:
        last_msg.tool_calls = new_tool_calls

        # Content synchronisieren: tool_use Blöcke müssen zu tool_calls passen,
        # sonst meldet die Anthropic API "tool_use ids without tool_result"
        if isinstance(last_msg.content, list):
            new_content = []
            for block in last_msg.content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    original_id = block.get("id")
                    if original_id in replaced_ids:
                        # Alten tool_use durch gesplittete ersetzen
                        for new_tc in replaced_ids[original_id]:
                            new_content.append({
                                "type": "tool_use",
                                "id": new_tc["id"],
                                "name": new_tc["name"],
                                "input": new_tc["args"],
                            })
                    else:
                        new_content.append(block)
                else:
                    new_content.append(block)
            last_msg.content = new_content

    return {}


# =============================================================================
# OVERVIEW GUARD HOOK (erzwingt Auto-Intervall im overview-Modus)
# =============================================================================

def _make_overview_guard_hook(data_mode: str):
    """
    Factory für einen Post-Model Hook der im overview-Modus LLM-Fehler korrigiert.

    Problem: Das LLM setzt manchmal raw=True oder interval=1s aus der
    Konversationshistorie, obwohl der Supervisor overview (niedrige Auflösung)
    angefordert hat. Das umgeht calculate_auto_interval und erzeugt ~2400
    statt ~40 Punkte pro Key.

    Lösung: Im overview-Modus werden get_telemetry-Calls korrigiert:
    - raw=True → raw=False (erzwingt Aggregation)
    - explizites interval → entfernt (erzwingt Auto-Intervall)

    Im detail-Modus wird stattdessen der raw_estimation_hook angewendet.
    """
    def hook(state: dict) -> dict:
        if data_mode in ("detail", "latest"):
            return raw_estimation_hook(state)

        # overview-Modus: Guard anwenden
        messages = state.get("messages", [])
        if not messages:
            return {}

        last_msg = messages[-1]
        if not isinstance(last_msg, AIMessage) or not last_msg.tool_calls:
            return {}

        modified = False
        for tc in last_msg.tool_calls:
            if tc["name"] != "get_telemetry":
                continue
            args = tc.get("args", {})

            # raw=True → raw=False
            if args.get("raw", False):
                args["raw"] = False
                modified = True
                logger.info(f"overview_guard: raw=True → False für {args.get('keys', '?')}")

            # Explizites interval entfernen → Auto-Intervall greift
            if "interval" in args and args["interval"] is not None:
                removed_interval = args.pop("interval")
                modified = True
                logger.info(f"overview_guard: interval={removed_interval} entfernt für {args.get('keys', '?')}")

        if modified:
            # Content synchronisieren (tool_use Blöcke → args)
            if isinstance(last_msg.content, list):
                for block in last_msg.content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        block_id = block.get("id")
                        matching_tc = next(
                            (tc for tc in last_msg.tool_calls if tc["id"] == block_id),
                            None,
                        )
                        if matching_tc:
                            block["input"] = matching_tc["args"]

        return {}

    return hook


# =============================================================================
# DEBUG LOGGING (Datei-basiert für Prompt-Analyse)
# =============================================================================

_DEBUG_LOG_PATH = PROJECT_ROOT / "logs" / "data_agent_debug.log"
_DEBUG_LOG_ENABLED = True  # Auf False setzen um Debug-Logging zu deaktivieren
_debug_step_counter = 0


def _debug_log(text: str) -> None:
    """Schreibt Debug-Text in die Log-Datei."""
    if not _DEBUG_LOG_ENABLED:
        return
    try:
        _DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except Exception as e:
        logger.warning(f"Debug-Log schreiben fehlgeschlagen: {e}")


def _debug_log_messages(label: str, messages: list) -> None:
    """Loggt eine Message-Liste menschenlesbar."""
    _debug_log(f"\n{'='*80}")
    _debug_log(f"  {label}")
    _debug_log(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    _debug_log(f"{'='*80}")
    _debug_log(f"Anzahl Messages: {len(messages)}\n")

    for i, msg in enumerate(messages):
        msg_type = type(msg).__name__
        _debug_log(f"--- [{i}] {msg_type} ---")

        if isinstance(msg, SystemMessage):
            content = msg.content
            # SystemMessage mit cache_control (list[dict] Format)
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block["text"]
                        # Prompt kürzen auf erste/letzte Zeilen für Übersicht
                        lines = text.split("\n")
                        if len(lines) > 60:
                            preview = "\n".join(lines[:30]) + f"\n\n... ({len(lines) - 60} Zeilen gekürzt) ...\n\n" + "\n".join(lines[-30:])
                        else:
                            preview = text
                        _debug_log(f"[SystemMessage/cached] ({len(text)} chars)\n{preview}")
            else:
                _debug_log(f"[SystemMessage] ({len(str(content))} chars)\n{str(content)[:2000]}")

        elif isinstance(msg, HumanMessage):
            _debug_log(f"[User] {msg.content}")

        elif isinstance(msg, AIMessage):
            if getattr(msg, "tool_calls", None):
                _debug_log(f"[AI → Tool Calls] {len(msg.tool_calls)} Calls:")
                for tc in msg.tool_calls:
                    args_str = json.dumps(tc.get("args", {}), ensure_ascii=False)
                    if len(args_str) > 300:
                        args_str = args_str[:300] + "..."
                    _debug_log(f"  - {tc['name']}({args_str})")
            if isinstance(msg.content, str) and msg.content.strip():
                _debug_log(f"[AI Text] {msg.content[:500]}")
            elif isinstance(msg.content, list):
                text_parts = [b.get("text", "") for b in msg.content if isinstance(b, dict) and b.get("type") == "text"]
                if text_parts:
                    _debug_log(f"[AI Text] {' '.join(text_parts)[:500]}")

        elif isinstance(msg, ToolMessage):
            content_str = str(msg.content)[:300]
            _debug_log(f"[ToolResult] tool_call_id={getattr(msg, 'tool_call_id', '?')}")
            _debug_log(f"  {content_str}")

        else:
            _debug_log(f"[{msg_type}] {str(msg.content)[:200]}")

        _debug_log("")


def _make_pre_model_logging_hook():
    """
    Pre-Model Hook: Loggt alle Messages die das LLM bei jedem
    React-Loop-Schritt sieht. Hilft zu verstehen warum das LLM
    bestimmte Entscheidungen trifft.
    """
    step = 0

    def hook(state: dict) -> dict:
        nonlocal step
        step += 1
        messages = state.get("messages", [])
        _debug_log_messages(
            f"PRE-MODEL (React-Loop Schritt {step}) — LLM sieht diese Messages:",
            messages,
        )
        return {}

    return hook


def _make_post_model_logging_hook(inner_hook):
    """
    Wrapper um den bestehenden post_model_hook der zusätzlich
    die LLM-Entscheidung loggt.
    """
    def hook(state: dict) -> dict:
        messages = state.get("messages", [])
        if messages:
            last_msg = messages[-1]
            if isinstance(last_msg, AIMessage):
                _debug_log(f"\n{'- '*40}")
                _debug_log(f"  POST-MODEL — LLM-Entscheidung:")
                _debug_log(f"{'- '*40}")
                if getattr(last_msg, "tool_calls", None):
                    _debug_log(f"Tool Calls: {len(last_msg.tool_calls)}")
                    for tc in last_msg.tool_calls:
                        args_str = json.dumps(tc.get("args", {}), ensure_ascii=False)
                        _debug_log(f"  → {tc['name']}({args_str[:200]})")
                elif isinstance(last_msg.content, str) and last_msg.content.strip():
                    _debug_log(f"Text-Antwort: {last_msg.content[:500]}")
                else:
                    _debug_log(f"Leere Antwort")
                _debug_log("")

        # Originalen Hook aufrufen (overview_guard / raw_estimation)
        return inner_hook(state)

    return hook


# =============================================================================
# CHECK DATASET TOOL (Prüft ob Daten bereits in DuckDB vorliegen)
# =============================================================================

def _create_check_dataset_tool(session_id: str):
    """
    Erstellt ein check_dataset Tool das an die aktuelle Session gebunden ist.

    Das LLM ruft dieses Tool VOR get_telemetry auf, um zu prüfen ob die
    gewünschten Daten bereits im richtigen Modus in DuckDB vorliegen.
    Verhindert unnötige Neu-Abfragen bei Mode-Wechseln (z.B. detail→overview).
    """

    @tool
    def check_dataset(
        keys: str,
        mode: str,
        start_date: str,
        start_time: str,
        end_date: str,
        end_time: str,
    ) -> str:
        """Prueft ob Datasets fuer die angegebenen Keys im gewuenschten Modus
        bereits in der Datenbank existieren. IMMER vor get_telemetry aufrufen!

        Args:
            keys: Komma-separierte Signal-Keys, z.B. "torque_act_a1_nm,torque_act_a2_nm"
            mode: Gewuenschter Modus — "overview" oder "detail"
            start_date: Startdatum YYYY-MM-DD
            start_time: Startzeit HH:MM
            end_date: Enddatum YYYY-MM-DD
            end_time: Endzeit HH:MM
        """
        key_list = [k.strip() for k in keys.split(",")]

        # Time-Range im gleichen Format wie _extract_time_range
        st = start_time.replace(":", "-")
        et = end_time.replace(":", "-")
        time_range = (
            f"{start_date}_{st}_{et}"
            if start_date == end_date
            else f"{start_date}_{st}_{end_date}_{et}"
        )

        store = SessionStore.get_instance(session_id)
        found, missing = [], []

        for key in key_list:
            prefix = generate_dataset_key(
                "krc5", key, "timeseries",
                data_mode=mode, time_range=time_range,
            )
            rows = store.query(
                "SELECT dataset_key, COUNT(*) FROM telemetry "
                "WHERE dataset_key LIKE ? GROUP BY dataset_key",
                [f"{prefix}%"],
            )
            if rows:
                found.append({"key": key, "dataset_key": rows[0][0],
                              "points": sum(r[1] for r in rows)})
            else:
                missing.append({"key": key, "expected_prefix": prefix})

        result = {"found": found, "missing": missing}
        if not missing:
            result["message"] = "Alle Daten vorhanden — kein get_telemetry noetig."
        else:
            mk = ", ".join(m["key"] for m in missing)
            result["message"] = f"Fehlende Daten: {mk} — bitte mit get_telemetry laden."

        logger.debug(f"check_dataset: {len(found)} found, {len(missing)} missing")
        return json.dumps(result, ensure_ascii=False)

    return check_dataset


# =============================================================================
# AGENT ERSTELLUNG (DEC-018: API Key Rotation)
# =============================================================================

def create_data_agent(tools: list, data_mode: str = "overview"):
    """Erstellt den Data Agent mit Claude und aktuellem API Key."""
    llm = create_anthropic_client()  # Nutzt api_key_rotator
    post_hook = _make_overview_guard_hook(data_mode)

    if _DEBUG_LOG_ENABLED:
        pre_hook = _make_pre_model_logging_hook()
        post_hook = _make_post_model_logging_hook(post_hook)
        return create_react_agent(llm, tools, pre_model_hook=pre_hook, post_model_hook=post_hook)

    return create_react_agent(llm, tools, post_model_hook=post_hook)


# =============================================================================
# HAUPTLOGIK - AUFGETEILT (DEC-016)
# =============================================================================

def prepare_messages(state: AgentState) -> list:
    """
    Bereitet Messages für den Agent vor (DEC-027 v2).

    Nur SystemMessage + letzte HumanMessage — keine Konversationshistorie.
    Verhindert dass AI-Text aus vorherigen Turns das LLM beeinflusst
    (z.B. "Daten erfolgreich geladen" → LLM überspringt check_dataset).

    Der Supervisor liefert den vollständigen Kontext über <supervisor_instructions>
    (welche Keys, welcher Zeitraum, welcher Modus). Das LLM braucht keine Historie.
    """
    # DEC-023: Data Mode aus State lesen
    data_mode = state.get("data_retrieval_mode", "overview")
    logger.debug(f"Data Retrieval Mode: {data_mode}")

    # Prompt generieren mit data_mode
    current_prompt = get_data_agent_prompt(data_mode=data_mode)

    # Data Instructions vom Supervisor injizieren
    data_instructions = state.get("data_instructions")
    if data_instructions:
        current_prompt += "\n\n<supervisor_instructions>\n" + data_instructions + "\n</supervisor_instructions>"
        logger.debug(f"Data Instructions injiziert: {data_instructions[:80]}...")

    # Nur letzte User-Query — kein Konversations-History
    user_query = extract_user_query(state["messages"])

    return [
        create_cached_system_message(current_prompt),
        HumanMessage(content=user_query),
    ]


async def execute_agent_with_retry(
    agent, messages: list, tools: list,
    max_retries: int = MAX_RETRIES,
    data_mode: str = "overview",
) -> dict:
    """
    Führt Agent aus mit Retry bei transienten Fehlern.

    DEC-018: Bei Rate Limit (429) wird der API Key rotiert.

    Retry bei:
    - ConnectionError
    - TimeoutError
    - Rate Limit (429) - mit Key-Rotation
    """
    last_exception = None
    current_agent = agent

    for attempt in range(max_retries):
        try:
            result = await current_agent.ainvoke(
                {"messages": messages},
                config={"recursion_limit": 40},
            )
            logger.debug(f"Agent erfolgreich (Versuch {attempt + 1}, {api_key_rotator.get_key_info()})")
            return result

        except (ConnectionError, TimeoutError) as e:
            last_exception = e
            delay = RETRY_DELAY_BASE * (2 ** attempt)  # Exponential backoff
            logger.warning(f"Transienter Fehler (Versuch {attempt + 1}/{max_retries}): {e}")

            if attempt < max_retries - 1:
                logger.info(f"Warte {delay}s vor Retry...")
                await asyncio.sleep(delay)

        except Exception as e:
            error_str = str(e).lower()

            # Rate Limit Error - Key rotieren (DEC-018)
            if "429" in error_str or "rate limit" in error_str or "too many requests" in error_str:
                last_exception = e
                logger.warning(f"Rate Limit mit {api_key_rotator.get_key_info()} (Versuch {attempt + 1}/{max_retries})")

                if attempt < max_retries - 1:
                    # Key rotieren und neuen Agent erstellen
                    api_key_rotator.rotate()
                    current_agent = create_data_agent(tools, data_mode)

                    delay = RETRY_DELAY_BASE * (2 ** attempt)
                    logger.info(f"Neuer Key: {api_key_rotator.get_key_info()}, warte {delay}s...")
                    await asyncio.sleep(delay)
            else:
                # Anderer Fehler - sofort werfen
                raise

    # Alle Retries fehlgeschlagen
    raise last_exception or Exception("Agent execution failed after retries")


def extract_tool_results(
    result: dict,
    skip_count: int = 0,
) -> Tuple[Optional[Any], Optional[dict], Optional[str], list]:
    """
    Extrahiert Daten aus Agent-Ergebnis.

    Durchsucht nur NEUE ToolMessages (nach skip_count) und extrahiert
    die relevantesten Daten. Gibt zusätzlich ALLE extrahierten Datasets
    zurück (für DuckDB-Speicherung).

    Args:
        result: Agent-Ergebnis mit "messages" Key
        skip_count: Anzahl Input-Messages die übersprungen werden sollen.
                    Verhindert, dass ToolMessages aus vorherigen Turns
                    erneut extrahiert werden.

    Returns:
        (primary_data, primary_meta, primary_file, all_datasets)
        all_datasets: Liste von (data, meta, file) Tupeln
    """
    data = None
    meta = None
    data_file = None
    all_datasets: list[Tuple[Any, Optional[dict], Optional[str]]] = []

    all_messages = result.get("messages", [])
    new_messages = all_messages[skip_count:] if skip_count > 0 else all_messages

    for msg in new_messages:
        if isinstance(msg, ToolMessage):
            text_content = extract_text_from_tool_content(msg.content)

            if text_content:
                parsed = parse_json_safe(text_content)

                if parsed is not None:
                    extracted_data, extracted_meta, extracted_file = extract_data_from_parsed(parsed)

                    # Error-Responses (error_datapoints etc.) haben höchste Priorität
                    if extracted_meta and extracted_meta.get("type") in ("error_datapoints", "error", "no_data"):
                        meta = extracted_meta
                        data = None
                        data_file = None
                        continue

                    if extracted_data is not None:
                        all_datasets.append((extracted_data, extracted_meta, extracted_file))

                        # Priorisiere Ergebnisse mit Statistiken
                        current_is_list = meta and meta.get("type") == "list"
                        new_has_stats = extracted_meta and extracted_meta.get("statistics")
                        new_is_not_list = extracted_meta and extracted_meta.get("type") != "list"

                        if data is None or (current_is_list and new_is_not_list) or new_has_stats:
                            data = extracted_data
                            meta = extracted_meta
                            data_file = extracted_file

    return data, meta, data_file, all_datasets


def _store_dataset_in_duckdb(
    data: dict,
    meta: Optional[dict],
    data_file: Optional[str],
    session_id: str,
    data_retrieval_mode: str,
) -> Tuple[str, DatasetMeta]:
    """
    DEC-025: Speichert ein Dataset in DuckDB und erstellt DatasetMeta.

    Returns:
        (dataset_key, DatasetMeta)
    """
    dataset_key = determine_dataset_key_rich(data, meta, data_retrieval_mode)
    signal_keys = list(data.keys())
    unit = _detect_unit(signal_keys)
    point_count = 0

    try:
        store = SessionStore.get_instance(session_id)
        point_count = store.store_dataset(dataset_key, data, unit=unit)
        logger.info(f"DuckDB: {point_count} Punkte gespeichert für '{dataset_key}'")
    except Exception as e:
        logger.warning(f"DuckDB store fehlgeschlagen: {e} — Daten nur in File")

    timerange = {}
    if meta and meta.get("timerange"):
        timerange = meta["timerange"]

    settings = (meta or {}).get("settings", {}) or {}

    dataset_meta = DatasetMeta(
        dataset_key=dataset_key,
        device_id="krc5",
        keys=signal_keys,
        point_count=point_count,
        timerange=timerange,
        retrieval_mode=data_retrieval_mode,
        unit=unit,
        created_at=datetime.now().isoformat(),
        data_file=data_file,
        meta={
            **(meta or {}),
            "data_mode": data_retrieval_mode,
            "interval": settings.get("interval_human", ""),
            "aggregation": settings.get("aggregation", ""),
        },
    )

    # DEC-031: Dual-Write — DatasetMeta auch in DuckDB speichern
    try:
        store = SessionStore.get_instance(session_id)
        store.store_dataset_meta(dict(dataset_meta))
    except Exception as e:
        logger.warning(f"DuckDB store_dataset_meta fehlgeschlagen: {e}")

    return dataset_key, dataset_meta


def build_result(
    result: dict,
    data: Optional[Any],
    meta: Optional[dict],
    data_file: Optional[str],
    quality: Optional[dict],
    needs_input: bool,
    input_reason: Optional[str],
    session_id: str = "default",
    data_retrieval_mode: str = "overview",
    all_datasets: Optional[list] = None,
    check_dataset_keys: Optional[list[str]] = None,
) -> dict[str, Any]:
    """
    Baut das Ergebnis-Dictionary zusammen.

    DEC-025/031: Rohdaten und DatasetMeta werden in DuckDB gespeichert.
    Kein datasets-Feld mehr im Return (DEC-031: DuckDB ist Single Source of Truth).
    Speichert ALLE Datasets aus allen Tool-Aufrufen, nicht nur das letzte.

    DEC-028: Setzt active_dataset_keys:
    - Neue Daten geladen → Keys der neuen Datasets
    - Keine neuen Daten (check_dataset: vorhanden) → found-Keys aus check_dataset
    """

    new_datasets: dict[str, DatasetMeta] = {}
    active_keys: list[str] = []  # DEC-026: Keys dieses Turns

    # ALLE Datasets in DuckDB speichern (nicht nur das primäre)
    # Multi-Group Split: Responses mit Keys aus mehreren Gruppen aufteilen
    if all_datasets:
        for ds_data, ds_meta, ds_file in all_datasets:
            if ds_data is not None and isinstance(ds_data, dict) and _is_telemetry_data(ds_data):
                split_datasets = _split_multi_group_data(ds_data, ds_meta, ds_file)
                for split_data, split_meta, split_file in split_datasets:
                    key, meta_entry = _store_dataset_in_duckdb(
                        split_data, split_meta, split_file, session_id, data_retrieval_mode,
                    )
                    if meta_entry.get("point_count", 0) > 0:
                        new_datasets[key] = meta_entry
                        active_keys.append(key)
        if new_datasets:
            logger.info(f"DuckDB: {len(new_datasets)} Datasets gespeichert")

    # Fallback: nur primäres Dataset (wenn all_datasets nicht übergeben)
    elif data is not None and isinstance(data, dict):
        key, meta_entry = _store_dataset_in_duckdb(
            data, meta, data_file, session_id, data_retrieval_mode,
        )
        new_datasets[key] = meta_entry
        active_keys.append(key)

    # DEC-028: check_dataset found-Keys IMMER mergen (nicht nur Fallback!)
    # Szenario: check_dataset findet Key A in DuckDB, Data Agent lädt Key B neu.
    # Ohne Merge fehlt Key A in active_dataset_keys → Stats/Viz Agent sieht ihn nicht.
    if check_dataset_keys:
        for ck in check_dataset_keys:
            if ck not in active_keys:
                active_keys.append(ck)
        logger.info(f"active_dataset_keys nach check_dataset merge: {active_keys}")

    return {
        "messages": result.get("messages", []),
        "active_dataset_keys": active_keys or None,  # DEC-028
        "needs_user_input": needs_input,
        "user_input_reason": input_reason,
    }


def _detect_unit(keys: list[str]) -> str:
    """Erkennt Einheit aus Signal-Keys."""
    if not keys:
        return ""
    first = keys[0].lower()
    unit_mapping = [
        ("_nm", "Nm"),
        ("_deg", "deg"),
        ("_mm", "mm"),
        ("_pct", "%"),
        ("_m_per_s", "m/s"),
        ("_a", "A"),
        ("_kwh", "kWh"),
    ]
    for suffix, unit in unit_mapping:
        if suffix in first:
            return unit
    return ""


def _split_multi_group_data(
    data: dict,
    meta: Optional[dict],
    data_file: Optional[str],
) -> list[Tuple[dict, Optional[dict], Optional[str]]]:
    """
    Splittet Tool-Response in einzelne Keys für granulare DuckDB-Speicherung.

    Jeder ThingsBoard-Key bekommt sein eigenes Dataset, damit der Supervisor
    einzelne Signale über active_dataset_keys auswählen kann.
    z.B. "nur Achse 1" → Supervisor wählt krc5/axis_act_a1_deg/... statt
    krc5/axis_position/... (das alle 6 Achsen enthält).

    Returns:
        Liste von (data_dict, meta, data_file) Tupeln — ein Eintrag pro Key
    """
    if not data or len(data) <= 1:
        return [(data, meta, data_file)]

    result = []
    for key in data:
        key_data = {key: data[key]}
        key_meta = dict(meta) if meta else {}
        if "keys" in key_meta:
            key_meta["keys"] = [key]
        result.append((key_data, key_meta, data_file))

    logger.debug(f"Per-Key Split: {len(data)} Keys → {len(result)} einzelne Datasets")
    return result


def _is_telemetry_data(data: dict) -> bool:
    """
    Prüft ob ein Dict tatsächlich Telemetrie-Daten enthält.

    Telemetrie-Daten haben das Format:
    - Timeseries: {"key": [{"value": "25.0", "timestamp": 1234}, ...]}
    - Latest: {"key": {"value": "25.0", "timestamp": 1234}}

    NICHT Telemetrie: search_telemetry_keys Responses, data_availability, etc.
    """
    if not data:
        return False
    first_val = next(iter(data.values()))
    # Timeseries: Wert ist Liste von {value, timestamp} Dicts
    if isinstance(first_val, list) and len(first_val) > 0:
        item = first_val[0]
        return isinstance(item, dict) and "value" in item
    # Latest: Wert ist einzelnes {value, timestamp} Dict
    if isinstance(first_val, dict) and "value" in first_val:
        return True
    return False


def _extract_check_dataset_found_keys(result: dict, skip_count: int) -> list[str]:
    """
    DEC-028: Extrahiert dataset_keys aus check_dataset Tool-Responses.

    Wenn der Data Agent nur check_dataset aufruft (Daten bereits vorhanden)
    und kein get_telemetry, liefern diese Keys den Fallback für
    active_dataset_keys.
    """
    found_keys = []
    messages = result.get("messages", [])[skip_count:]
    for msg in messages:
        if isinstance(msg, ToolMessage):
            try:
                content = msg.content if isinstance(msg.content, str) else ""
                parsed = json.loads(content)
                if isinstance(parsed, dict) and "found" in parsed:
                    for entry in parsed["found"]:
                        if isinstance(entry, dict) and "dataset_key" in entry:
                            found_keys.append(entry["dataset_key"])
            except (json.JSONDecodeError, TypeError):
                continue
    return found_keys


def build_error_result(error: Exception) -> dict[str, Any]:
    """Baut Fehler-Ergebnis."""
    error_msg = f"Fehler beim Datenabruf: {str(error)}"
    logger.error(error_msg, exc_info=True)
    
    return {
        "messages": [AIMessage(content=error_msg)],
        "error": error_msg,
    }


# =============================================================================
# HAUPTFUNKTION
# =============================================================================

async def run_data_agent(state: AgentState) -> dict[str, Any]:
    """
    Führt den Data Agent aus.
    
    Orchestriert die einzelnen Schritte:
    1. Vorbereitung (Tools, Messages)
    2. Ausführung (mit Retry)
    3. Verarbeitung (Parsing, Validierung)
    4. Ergebnis (Summary, Datasets)
    """
    try:
        logger.debug("Starte run_data_agent")

        # 1. Vorhandene Datasets aus DuckDB (DEC-031)
        session_id_pre = state.get("session_id", "default")
        existing_datasets = get_dataset_meta_from_duckdb(session_id_pre)
        logger.debug(f"Vorhandene Datasets (DuckDB): {list(existing_datasets.keys())}")

        # 2. MCP Tools holen
        tools = await get_mcp_tools()
        logger.debug(f"Tools bereit: {len(tools)}")

        # 3. Data Mode und Session-ID aus State lesen
        data_mode = state.get("data_retrieval_mode", "overview")
        session_id = state.get("session_id", "default")

        # 3b. check_dataset Tool erstellen und hinzufügen
        check_tool = _create_check_dataset_tool(session_id)
        all_tools = tools + [check_tool]

        # Debug: Kontext loggen
        _debug_log(f"\n{'#'*80}")
        _debug_log(f"  DATA AGENT START — Modus: {data_mode}")
        _debug_log(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        _debug_log(f"{'#'*80}")
        if existing_datasets:
            _debug_log(f"\nVorhandene Datasets ({len(existing_datasets)}):")
            for k, v in existing_datasets.items():
                mode = v.get("retrieval_mode", "?") if isinstance(v, dict) else "?"
                keys = v.get("keys", []) if isinstance(v, dict) else []
                _debug_log(f"  - {k}  (mode={mode}, keys={keys[:3]})")
        else:
            _debug_log(f"\nKeine vorhandenen Datasets.")

        # 4. Agent erstellen (mit mode-spezifischem Hook)
        agent = create_data_agent(all_tools, data_mode)

        # 5. Messages vorbereiten
        messages = prepare_messages(state)
        input_message_count = len(messages)

        # Debug: Input-Messages loggen
        _debug_log_messages(
            f"INPUT MESSAGES an Agent (data_mode={data_mode})",
            messages,
        )

        # 6. Agent ausführen (mit Retry und Key-Rotation bei 429)
        result = await execute_agent_with_retry(agent, messages, all_tools, data_mode=data_mode)
        logger.debug(f"Agent fertig, {len(result.get('messages', []))} Messages")

        # Debug: Neue Messages (Output) loggen
        all_result_msgs = result.get("messages", [])
        new_msgs = all_result_msgs[input_message_count:]
        _debug_log_messages(
            f"OUTPUT — {len(new_msgs)} neue Messages vom Agent (von {len(all_result_msgs)} gesamt)",
            new_msgs,
        )

        # 7. Tool-Ergebnisse extrahieren (nur NEUE Messages, nicht aus vorherigen Turns)
        data, meta, data_file, all_datasets = extract_tool_results(
            result, skip_count=input_message_count
        )
        telemetry_count = sum(1 for d, _, _ in all_datasets if isinstance(d, dict) and _is_telemetry_data(d))
        if telemetry_count > 0:
            logger.info(f"Data Agent hat {telemetry_count} Telemetrie-Datasets geladen")

        # 7b. DEC-028: check_dataset found-Keys als Fallback für active_dataset_keys
        check_dataset_keys = _extract_check_dataset_found_keys(result, input_message_count)

        # 8. Datenqualität prüfen (nur für echte Telemetrie, nicht check_dataset Responses)
        quality = None
        if data and isinstance(data, dict) and _is_telemetry_data(data):
            quality = validate_data_quality(data)
            if meta:
                meta["quality"] = quality

        # 9. User-Input-Bedarf prüfen
        needs_input, input_reason = detect_needs_user_input(result.get("messages", []))

        # Error-Responses direkt als User-Input markieren (robuster als LLM-Text-Matching)
        if not needs_input and meta and meta.get("type") == "error_datapoints":
            needs_input = True
            input_reason = "Zu viele Rohdaten — User muss über Downsampling entscheiden"
            logger.info(f"needs_user_input=True gesetzt (meta.type=error_datapoints)")

        # 10. Ergebnis zusammenstellen (speichert ALLE Datasets in DuckDB)
        # asyncio.to_thread: DuckDB-Inserts blockieren den Event Loop nicht mehr,
        # Socket.IO Heartbeats bleiben aktiv → kein Chainlit-Reconnect
        return await asyncio.to_thread(
            build_result,
            result, data, meta, data_file, quality, needs_input, input_reason,
            session_id, data_mode, all_datasets, check_dataset_keys,
        )
        
    except Exception as e:
        return build_error_result(e)


async def data_agent_node(state: AgentState) -> dict[str, Any]:
    """LangGraph Node für den Data Agent."""
    return await run_data_agent(state)


# =============================================================================
# STANDALONE TEST
# =============================================================================

async def test_data_agent():
    """Test des Data Agents."""
    
    # Logging für Test konfigurieren
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    test_queries = [
        "Wie ist die aktuelle Position von Achse 1?",
        "Zeig mir den Verlauf der Bahngeschwindigkeit der letzten 10 Minuten",
    ]
    
    for query in test_queries:
        print(f"\n{'='*60}")
        print(f"📝 Query: {query}")
        print("="*60)
        
        state = AgentState(
            messages=[HumanMessage(content=query)]
        )
        
        result = await run_data_agent(state)
        
        print(f"\n📊 Datasets: {list(result.get('datasets', {}).keys())}")
        print(f"📁 Datasets: {list(result.get('datasets', {}).keys())}")
        
        if result.get("error"):
            print(f"❌ Error: {result['error']}")
        
        for msg in reversed(result.get("messages", [])):
            if isinstance(msg, AIMessage) and isinstance(msg.content, str):
                print(f"\n🤖 Agent: {msg.content[:500]}")
                break
    
    # Cleanup
    await cleanup_mcp()


if __name__ == "__main__":
    asyncio.run(test_data_agent())
