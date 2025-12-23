"""
Data Agent für ThingsBoard-Datenabfragen.

Nutzt MCP (Model Context Protocol) um mit dem ThingsBoard Server zu kommunizieren.

DESIGN-ENTSCHEIDUNGEN:
- DEC-005: MCP Session wird EINMAL beim Start erstellt und wiederverwendet
- DEC-013: Datasets werden über Turns akkumuliert (nicht überschrieben)
- DEC-014: SystemMessages aus State filtern
- DEC-016: Strukturiertes Logging, Retry-Mechanismus, Funktionsaufteilung
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import json
import asyncio
import logging
from contextlib import AsyncExitStack
from typing import Any, Tuple, Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
from langgraph.prebuilt import create_react_agent

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_mcp_adapters.tools import load_mcp_tools

from agents.state import AgentState
from prompts.data_agent_prompt import get_data_agent_prompt
from config.settings import ANTHROPIC_API_KEY, DEFAULT_MODEL, PROJECT_ROOT


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

def determine_dataset_key(data: Optional[dict], meta: Optional[dict]) -> str:
    """
    Bestimmt einen eindeutigen Key für den Datensatz.
    
    Beispiele:
    - Drehmomente → "torque"
    - Geschwindigkeit → "velocity"
    """
    if data is None:
        return "unknown"
    
    if not isinstance(data, dict):
        return "data"
    
    keys = list(data.keys())
    if not keys:
        return "empty"
    
    first_key = keys[0].lower()
    
    key_mapping = {
        "torque": "torque",
        "vel": "velocity",
        "speed": "velocity",
        "pos": "position",
        "acc": "acceleration",
        "temp": "temperature",
        "current": "current",
        "amp": "current",
        "axis": "axis",
        "energy": "energy",
    }
    
    for pattern, name in key_mapping.items():
        if pattern in first_key:
            return name
    
    # Fallback: Ersten Key-Teil als Basis
    return first_key.split("_")[0] if "_" in first_key else first_key[:10]


def generate_data_summary(
    data: Any, 
    meta: Optional[dict], 
    quality: Optional[dict] = None
) -> str:
    """Generiert eine kurze Zusammenfassung der Daten."""
    
    # Qualitätsproblem melden
    if quality and not quality.get("valid", True):
        error_pct = quality.get("error_percentage", 100)
        error_keys = quality.get("error_keys", [])
        valid_pts = quality.get("valid_points", 0)
        total_pts = quality.get("total_points", 0)
        
        if error_pct >= 95:
            keys_str = ", ".join(error_keys[:3])
            return f"FEHLERHAFTE DATEN: {keys_str} ({error_pct:.0f}% fehlerhaft)"
        elif error_pct > 50:
            return f"DATENQUALITÄT EINGESCHRÄNKT: {valid_pts}/{total_pts} gültig"
    
    # ERROR
    if meta and meta.get("type") == "error":
        return f"FEHLER: {meta.get('message', 'Unbekannter Fehler')}"
    
    # NO_DATA
    if meta and meta.get("type") == "no_data":
        return f"KEINE DATEN: {meta.get('message', 'Keine Daten gefunden')}"
    
    # DATA_AVAILABILITY
    if meta and meta.get("type") == "data_availability":
        data_range = meta.get("data_range", {})
        return f"VERFÜGBAR: {data_range.get('first_data', '?')} bis {data_range.get('last_data', '?')}"
    
    # ERROR_DATAPOINTS
    if meta and meta.get("type") == "error_datapoints":
        return f"ZU VIELE PUNKTE: {meta.get('message', '')}"
    
    if data is None:
        return "Keine Daten"
    
    # Statistiken vorhanden
    if meta and meta.get("statistics"):
        stats = meta["statistics"]
        keys = meta.get("keys", list(stats.keys())[:3])
        
        summaries = []
        for key in keys[:3]:
            stat = stats.get(key, {})
            if isinstance(stat, dict):
                count = stat.get("count", "?")
                summaries.append(f"{key}: {count} Punkte")
        
        if summaries:
            return "; ".join(summaries)
    
    # Aktuellste Werte
    if meta and meta.get("type") == "latest":
        return f"Aktuelle Werte: {len(data)} Keys"
    
    # Fallback
    if isinstance(data, dict):
        return f"{len(data)} Keys geladen"
    
    return "Daten geladen"


def format_existing_datasets_hint(datasets: dict[str, Any]) -> str:
    """Formatiert einen Hinweis über bereits geladene Datasets für den Prompt."""
    if not datasets:
        return ""
    
    lines = ["## BEREITS GELADENE DATEN", ""]
    lines.append("Folgende Datensätze sind bereits im State verfügbar:")
    
    for key, dataset in datasets.items():
        meta = dataset.get("meta", {})
        data = dataset.get("data", {})
        
        num_keys = len(data) if isinstance(data, dict) else 0
        data_keys = list(data.keys())[:5] if isinstance(data, dict) else []
        timerange = meta.get("timerange", {})
        
        lines.append(f"")
        lines.append(f"### {key}")
        lines.append(f"- Keys: {', '.join(data_keys)}")
        if timerange:
            lines.append(f"- Zeitraum: {timerange.get('start', '?')} bis {timerange.get('end', '?')}")
        if meta.get("statistics"):
            stats = meta["statistics"]
            first_stat = next(iter(stats.values()), {})
            if isinstance(first_stat, dict):
                lines.append(f"- Punkte pro Key: {first_stat.get('count', '?')}")
    
    lines.append("")
    lines.append("Diese Daten müssen NICHT erneut geladen werden.")
    lines.append("Für Vergleiche/Korrelationen: Lade nur die FEHLENDEN Daten.")
    lines.append("")
    
    return "\n".join(lines)


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
# AGENT ERSTELLUNG
# =============================================================================

def create_data_agent(tools: list):
    """Erstellt den Data Agent mit Claude."""
    llm = ChatAnthropic(
        model=DEFAULT_MODEL,
        api_key=ANTHROPIC_API_KEY,
        temperature=0,
    )
    return create_react_agent(llm, tools)


# =============================================================================
# HAUPTLOGIK - AUFGETEILT (DEC-016)
# =============================================================================

def prepare_messages(state: AgentState, existing_datasets: dict) -> list:
    """
    Bereitet Messages für den Agent vor.
    
    - Filtert SystemMessages (DEC-014)
    - Fügt aktuellen Prompt hinzu
    - Fügt Dataset-Hint hinzu wenn vorhanden
    """
    # Prompt generieren
    current_prompt = get_data_agent_prompt()
    
    # Dataset-Hint hinzufügen wenn Daten vorhanden
    if existing_datasets:
        datasets_hint = format_existing_datasets_hint(existing_datasets)
        current_prompt = current_prompt + "\n\n" + datasets_hint
        logger.debug("Datasets-Hint zum Prompt hinzugefügt")
    
    # SystemMessages filtern (DEC-014)
    filtered_messages = [
        msg for msg in state["messages"]
        if not isinstance(msg, SystemMessage)
    ]
    
    return [SystemMessage(content=current_prompt), *filtered_messages]


async def execute_agent_with_retry(agent, messages: list, max_retries: int = MAX_RETRIES) -> dict:
    """
    Führt Agent aus mit Retry bei transienten Fehlern.
    
    Retry bei:
    - ConnectionError
    - TimeoutError
    - Rate Limit (429)
    """
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            result = await agent.ainvoke({"messages": messages})
            logger.debug(f"Agent erfolgreich (Versuch {attempt + 1})")
            return result
            
        except (ConnectionError, TimeoutError) as e:
            last_exception = e
            delay = RETRY_DELAY_BASE * (2 ** attempt)  # Exponential backoff
            logger.warning(f"Transienter Fehler (Versuch {attempt + 1}/{max_retries}): {e}")
            
            if attempt < max_retries - 1:
                logger.info(f"Warte {delay}s vor Retry...")
                await asyncio.sleep(delay)
        
        except Exception as e:
            # Nicht-transiente Fehler sofort werfen
            error_str = str(e).lower()
            if "429" in error_str or "rate limit" in error_str:
                last_exception = e
                delay = RETRY_DELAY_BASE * (2 ** attempt)
                logger.warning(f"Rate Limit (Versuch {attempt + 1}/{max_retries})")
                
                if attempt < max_retries - 1:
                    await asyncio.sleep(delay)
            else:
                raise
    
    # Alle Retries fehlgeschlagen
    raise last_exception or Exception("Agent execution failed after retries")


def extract_tool_results(
    result: dict
) -> Tuple[Optional[Any], Optional[dict], Optional[str]]:
    """
    Extrahiert Daten aus Agent-Ergebnis.
    
    Durchsucht alle ToolMessages und extrahiert die relevantesten Daten.
    """
    data = None
    meta = None
    data_file = None
    
    for msg in result.get("messages", []):
        if isinstance(msg, ToolMessage):
            text_content = extract_text_from_tool_content(msg.content)
            
            if text_content:
                parsed = parse_json_safe(text_content)
                
                if parsed is not None:
                    extracted_data, extracted_meta, extracted_file = extract_data_from_parsed(parsed)
                    
                    if extracted_data is not None:
                        # Priorisiere Ergebnisse mit Statistiken
                        current_is_list = meta and meta.get("type") == "list"
                        new_has_stats = extracted_meta and extracted_meta.get("statistics")
                        new_is_not_list = extracted_meta and extracted_meta.get("type") != "list"
                        
                        if data is None or (current_is_list and new_is_not_list) or new_has_stats:
                            data = extracted_data
                            meta = extracted_meta
                            data_file = extracted_file
    
    return data, meta, data_file


def build_result(
    result: dict,
    data: Optional[Any],
    meta: Optional[dict],
    data_file: Optional[str],
    quality: Optional[dict],
    needs_input: bool,
    input_reason: Optional[str]
) -> dict[str, Any]:
    """Baut das Ergebnis-Dictionary zusammen."""
    
    summary = generate_data_summary(data, meta, quality)
    logger.info(f"Summary: {summary}")
    
    # Dataset unter Key speichern
    new_datasets = {}
    if data is not None and isinstance(data, dict):
        dataset_key = determine_dataset_key(data, meta)
        new_datasets[dataset_key] = {
            "data": data,
            "meta": meta,
            "data_file": data_file,
        }
        logger.debug(f"Neuer Datensatz unter Key '{dataset_key}'")
    
    return {
        "messages": result.get("messages", []),
        "datasets": new_datasets,
        "data_summary": summary,
        "current_data_file": data_file,
        "needs_user_input": needs_input,
        "user_input_reason": input_reason,
    }


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
        
        # 1. Vorhandene Datasets aus State
        existing_datasets = state.get("datasets", {}) or {}
        logger.debug(f"Vorhandene Datasets: {list(existing_datasets.keys())}")
        
        # 2. MCP Tools holen
        tools = await get_mcp_tools()
        logger.debug(f"Tools bereit: {len(tools)}")
        
        # 3. Agent erstellen
        agent = create_data_agent(tools)
        
        # 4. Messages vorbereiten
        messages = prepare_messages(state, existing_datasets)
        
        # 5. Agent ausführen (mit Retry)
        result = await execute_agent_with_retry(agent, messages)
        logger.debug(f"Agent fertig, {len(result.get('messages', []))} Messages")
        
        # 6. Tool-Ergebnisse extrahieren
        data, meta, data_file = extract_tool_results(result)
        
        # 7. Datenqualität prüfen
        quality = None
        if data and isinstance(data, dict):
            quality = validate_data_quality(data)
            if meta:
                meta["quality"] = quality
        
        # 8. User-Input-Bedarf prüfen
        needs_input, input_reason = detect_needs_user_input(result.get("messages", []))
        
        # 9. Ergebnis zusammenstellen
        return build_result(result, data, meta, data_file, quality, needs_input, input_reason)
        
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
        
        print(f"\n📊 Data Summary: {result.get('data_summary', 'N/A')}")
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
