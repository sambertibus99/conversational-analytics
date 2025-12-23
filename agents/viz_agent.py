"""
Viz Agent für Chart-Generierung.

DESIGN:
- LLM wählt Chart-Typ und Parameter
- Daten kommen via InjectedState, NICHT durch LLM-Prompt
- Best Practice nach LangGraph Dokumentation

DESIGN-ENTSCHEIDUNGEN:
- DEC-013: Multi-Turn Support mit datasets
- DEC-016: Strukturiertes Logging, Retry-Mechanismus
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
from typing import Any, Annotated, Optional, Tuple

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from agents.state import AgentState
from agents.utils import extract_data_from_datasets, get_dataset_meta, get_y_label, extract_user_query
from config.settings import ANTHROPIC_API_KEY, DEFAULT_MODEL


# =============================================================================
# LOGGING KONFIGURATION (DEC-016)
# =============================================================================

logger = logging.getLogger(__name__)

# Retry-Konfiguration
MAX_RETRIES = 3
RETRY_DELAY_BASE = 2


# =============================================================================
# MCP SESSION PROVIDER (DEC-016)
# =============================================================================

class AntVSessionProvider:
    """
    Verwaltet AntV MCP Session mit Caching.
    Analog zu MCPToolsProvider in data_agent.py
    """
    
    def __init__(self):
        self._session: ClientSession | None = None
        self._exit_stack: AsyncExitStack | None = None
        self._lock = asyncio.Lock()
    
    async def get_session(self) -> ClientSession:
        """Holt AntV Session - startet Server nur beim ersten Aufruf."""
        if self._session is not None:
            logger.debug("AntV Session aus Cache")
            return self._session
        
        async with self._lock:
            if self._session is not None:
                return self._session
            
            logger.info("Starte AntV MCP Server...")
            
            server_params = StdioServerParameters(
                command="npx",
                args=["-y", "@antv/mcp-server-chart"],
                env=None,
            )
            
            self._exit_stack = AsyncExitStack()
            streams = await self._exit_stack.enter_async_context(stdio_client(server_params))
            read_stream, write_stream = streams
            
            self._session = await self._exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await self._session.initialize()
            
            logger.info("AntV Server gestartet")
            return self._session
    
    async def cleanup(self):
        """Räumt Session auf."""
        if self._exit_stack:
            await self._exit_stack.aclose()
            self._exit_stack = None
        self._session = None
        logger.debug("AntV Session aufgeräumt")
    
    def is_initialized(self) -> bool:
        return self._session is not None


# Globale Instanz
_antv_provider = AntVSessionProvider()


async def get_antv_session() -> ClientSession:
    """Wrapper für Rückwärtskompatibilität."""
    return await _antv_provider.get_session()


async def get_antv_tools() -> list:
    """Kompatibilitäts-Wrapper für Warmup."""
    from langchain_mcp_adapters.tools import load_mcp_tools
    session = await get_antv_session()
    return await load_mcp_tools(session)


# =============================================================================
# DATEN-TRANSFORMATION
# =============================================================================

def timestamp_to_time_string(ts: int) -> str:
    """Konvertiert Timestamp zu lesbarem Zeit-String."""
    try:
        return datetime.fromtimestamp(ts / 1000).strftime("%H:%M:%S")
    except:
        return str(ts)


def shorten_key_name(key: str) -> str:
    """Kürzt Daten-Key für Chart-Legenden."""
    return (key
        .replace("torque_act_", "T")
        .replace("axis_act_", "A")
        .replace("_deg", "°")
        .replace("_nm", "")
        .replace("vel_act_", "V")
        .replace("_m_per_s", "")
        .replace("acc_axis_", "Acc"))


def transform_for_line_chart(data: dict[str, list], multi_key: bool = False) -> list[dict]:
    """Transformiert Daten für Line/Area Chart."""
    result = []
    
    for key, values in data.items():
        if not isinstance(values, list):
            continue
            
        for point in values:
            if isinstance(point, dict):
                ts = point.get("timestamp", 0)
                try:
                    val = float(point.get("value", 0))
                except (ValueError, TypeError):
                    continue
                
                entry = {"time": timestamp_to_time_string(ts), "value": val}
                
                if multi_key:
                    entry["group"] = shorten_key_name(key)
                
                result.append(entry)
        
        if not multi_key:
            break
    
    result.sort(key=lambda x: (x["time"], x.get("group", "")))
    return result


def transform_for_column_chart(data: dict[str, list]) -> list[dict]:
    """Transformiert Daten für Column/Bar Chart."""
    result = []
    
    for key, values in data.items():
        if not isinstance(values, list) or not values:
            continue
        
        nums = [float(p.get("value", 0)) for p in values if isinstance(p, dict)]
        if nums:
            avg = sum(nums) / len(nums)
            result.append({"category": shorten_key_name(key), "value": round(avg, 2)})
    
    return result


def transform_for_scatter_chart(data: dict[str, list]) -> list[dict]:
    """Transformiert Daten für Scatter Chart (Korrelation)."""
    keys = list(data.keys())
    if len(keys) < 2:
        return []
    
    x_key, y_key = keys[0], keys[1]
    x_vals = {}
    y_vals = {}
    
    for p in data.get(x_key, []):
        if isinstance(p, dict) and "timestamp" in p:
            try:
                x_vals[p["timestamp"]] = float(p["value"])
            except (ValueError, TypeError):
                pass
    
    for p in data.get(y_key, []):
        if isinstance(p, dict) and "timestamp" in p:
            try:
                y_vals[p["timestamp"]] = float(p["value"])
            except (ValueError, TypeError):
                pass
    
    return [{"x": x_vals[ts], "y": y_vals[ts]} for ts in x_vals if ts in y_vals]


# =============================================================================
# CHART-TOOLS MIT INJECTEDSTATE
# =============================================================================

@tool
async def generate_line_chart_tool(
    title: str,
    state: Annotated[dict, InjectedState],
) -> str:
    """
    Erstellt ein Liniendiagramm für Zeitreihen-Daten.
    Nutze dieses Tool für: Verlauf, Trend, Historie, Zeitreihen.
    
    Args:
        title: Titel des Charts, z.B. "Drehmomente - Dienstag 16.12."
    """
    logger.debug(f"generate_line_chart_tool: title={title}")
    
    datasets = state.get("datasets", {})
    data = extract_data_from_datasets(datasets)
    
    if not data:
        return "Fehler: Keine Daten im State"
    
    keys = list(data.keys())
    multi_key = len(keys) > 1
    transformed = transform_for_line_chart(data, multi_key)
    
    if not transformed:
        return "Fehler: Keine gültigen Datenpunkte"
    
    # Sampling bei zu vielen Punkten
    if len(transformed) > 500:
        step = len(transformed) // 500
        transformed = transformed[::step][:500]
    
    logger.debug(f"Daten transformiert: {len(transformed)} Punkte")
    
    session = await get_antv_session()
    result = await session.call_tool(
        "generate_line_chart",
        arguments={
            "data": transformed,
            "title": title,
            "axisXTitle": "Zeit",
            "axisYTitle": get_y_label(keys),
            "width": 800,
            "height": 500,
        }
    )
    
    return extract_chart_url(result)


@tool
async def generate_column_chart_tool(
    title: str,
    state: Annotated[dict, InjectedState],
) -> str:
    """
    Erstellt ein Säulendiagramm zum Vergleich von Durchschnittswerten.
    Nutze dieses Tool für: Vergleich, vs, gegenüberstellen.
    
    Args:
        title: Titel des Charts, z.B. "Vergleich der Achsen-Drehmomente"
    """
    logger.debug(f"generate_column_chart_tool: title={title}")
    
    datasets = state.get("datasets", {})
    data = extract_data_from_datasets(datasets)
    
    if not data:
        return "Fehler: Keine Daten im State"
    
    transformed = transform_for_column_chart(data)
    
    if not transformed:
        return "Fehler: Keine gültigen Datenpunkte"
    
    session = await get_antv_session()
    result = await session.call_tool(
        "generate_column_chart",
        arguments={
            "data": transformed,
            "title": title,
            "axisXTitle": "Kategorie",
            "axisYTitle": get_y_label(list(data.keys())),
            "width": 800,
            "height": 500,
        }
    )
    
    return extract_chart_url(result)


@tool
async def generate_scatter_chart_tool(
    title: str,
    state: Annotated[dict, InjectedState],
) -> str:
    """
    Erstellt ein Streudiagramm für Korrelationen zwischen zwei Variablen.
    Nutze dieses Tool für: Korrelation, Zusammenhang, Beziehung.
    
    Args:
        title: Titel des Charts, z.B. "Korrelation Achse 1 vs Achse 2"
    """
    logger.debug(f"generate_scatter_chart_tool: title={title}")
    
    datasets = state.get("datasets", {})
    data = extract_data_from_datasets(datasets)
    
    if not data or len(data) < 2:
        return "Fehler: Für Scatter brauche ich mindestens 2 Keys"
    
    transformed = transform_for_scatter_chart(data)
    
    if not transformed:
        return "Fehler: Keine überlappenden Zeitpunkte"
    
    keys = list(data.keys())
    session = await get_antv_session()
    result = await session.call_tool(
        "generate_scatter_chart",
        arguments={
            "data": transformed,
            "title": title,
            "axisXTitle": keys[0],
            "axisYTitle": keys[1],
            "width": 800,
            "height": 500,
        }
    )
    
    return extract_chart_url(result)


def extract_chart_url(result) -> str:
    """Extrahiert URL aus MCP-Tool-Ergebnis."""
    if hasattr(result, 'content') and result.content:
        for block in result.content:
            if hasattr(block, 'text') and block.text.startswith("http"):
                return block.text.strip()
    return "Fehler: Keine URL vom Chart-Server"


# Tool-Liste
CHART_TOOLS = [
    generate_line_chart_tool,
    generate_column_chart_tool,
    generate_scatter_chart_tool,
]


# =============================================================================
# VIZ AGENT PROMPT
# =============================================================================

VIZ_AGENT_PROMPT = """Du bist ein Visualisierungs-Agent für IIoT-Daten.

## VERFÜGBARE TOOLS

1. **generate_line_chart_tool** - Für Zeitreihen, Verläufe, Trends
2. **generate_column_chart_tool** - Für Vergleiche zwischen Kategorien
3. **generate_scatter_chart_tool** - Für Korrelationen zwischen 2 Variablen

## ENTSCHEIDUNGSREGELN

| User sagt | Tool |
|-----------|------|
| "Verlauf", "Trend", "Historie", "über Zeit" | generate_line_chart_tool |
| "Vergleich", "vs", "gegenüber" | generate_column_chart_tool |
| "Korrelation", "Zusammenhang" | generate_scatter_chart_tool |
| (Standard für Zeitreihen) | generate_line_chart_tool |

## WICHTIG

- Wähle EIN Tool und rufe es auf
- Der Titel sollte beschreibend sein (inkl. Zeitraum wenn bekannt)
- Die Daten werden automatisch aus dem System geladen
"""


# =============================================================================
# HAUPTLOGIK (DEC-016: Aufgeteilt)
# =============================================================================

def prepare_viz_context(state: AgentState) -> Tuple[dict, str]:
    """
    Bereitet Kontext für LLM vor.
    
    Returns:
        Tuple von (data, meta_info_string)
    """
    datasets = state.get("datasets", {})
    data = extract_data_from_datasets(datasets)
    
    if not data:
        return {}, ""
    
    keys = list(data.keys())
    meta_info = f"Verfügbare Daten: {len(keys)} Keys ({', '.join(keys[:5])}{'...' if len(keys) > 5 else ''})"
    meta_info += f"\nGeladene Datasets: {', '.join(datasets.keys())}"
    
    dataset_meta = get_dataset_meta(datasets)
    if dataset_meta.get("timerange"):
        tr = dataset_meta["timerange"]
        meta_info += f"\nZeitraum: {tr.get('weekday', '')} {tr.get('start', '')} - {tr.get('end', '')}"
    
    return data, meta_info


async def select_and_execute_tool(
    llm_with_tools,
    user_query: str,
    meta_info: str,
    tool_state: dict
) -> Tuple[str, str]:
    """
    Lässt LLM Tool auswählen und führt es aus.
    
    Returns:
        Tuple von (chart_url, tool_name)
    """
    messages = [
        SystemMessage(content=VIZ_AGENT_PROMPT),
        HumanMessage(content=f"User-Anfrage: {user_query}\n\n{meta_info}\n\nWähle das passende Chart-Tool und erstelle einen guten Titel."),
    ]
    
    logger.debug("LLM wählt Tool...")
    response = await llm_with_tools.ainvoke(messages)
    
    if not response.tool_calls:
        logger.debug("Kein Tool-Call, Fallback zu Line Chart")
        keys = list(tool_state.get("datasets", {}).keys())
        chart_url = await generate_line_chart_tool.ainvoke({
            "title": f"{', '.join(keys[:2])} - Verlauf",
            "state": tool_state,
        })
        return chart_url, "generate_line_chart_tool"
    
    tool_call = response.tool_calls[0]
    tool_name = tool_call["name"]
    tool_args = tool_call["args"]
    
    logger.debug(f"Tool gewählt: {tool_name}, args={tool_args}")
    
    tool_args["state"] = tool_state
    
    tool_map = {
        "generate_line_chart_tool": generate_line_chart_tool,
        "generate_column_chart_tool": generate_column_chart_tool,
        "generate_scatter_chart_tool": generate_scatter_chart_tool,
    }
    
    if tool_name in tool_map:
        chart_url = await tool_map[tool_name].ainvoke(tool_args)
    else:
        chart_url = f"Unbekanntes Tool: {tool_name}"
    
    return chart_url, tool_name


async def execute_viz_with_retry(
    llm_with_tools,
    user_query: str,
    meta_info: str,
    tool_state: dict,
    max_retries: int = MAX_RETRIES
) -> Tuple[str, str]:
    """
    Führt Visualisierung mit Retry aus.
    """
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            return await select_and_execute_tool(llm_with_tools, user_query, meta_info, tool_state)
        
        except (ConnectionError, TimeoutError) as e:
            last_exception = e
            delay = RETRY_DELAY_BASE * (2 ** attempt)
            logger.warning(f"Transienter Fehler (Versuch {attempt + 1}/{max_retries}): {e}")
            
            if attempt < max_retries - 1:
                await asyncio.sleep(delay)
        
        except Exception as e:
            error_str = str(e).lower()
            if "429" in error_str or "rate limit" in error_str:
                last_exception = e
                delay = RETRY_DELAY_BASE * (2 ** attempt)
                logger.warning(f"Rate Limit (Versuch {attempt + 1}/{max_retries})")
                
                if attempt < max_retries - 1:
                    await asyncio.sleep(delay)
            else:
                raise
    
    raise last_exception or Exception("Viz execution failed after retries")


def build_viz_result(chart_url: str, tool_name: str) -> dict[str, Any]:
    """Baut Erfolgs-Ergebnis."""
    logger.info(f"Chart erstellt: {chart_url[:80]}...")
    
    if chart_url.startswith("http"):
        return {
            "messages": [AIMessage(content=f"Chart erstellt: {chart_url}")],
            "chart_url": chart_url,
            "chart_type": tool_name.replace("generate_", "").replace("_chart_tool", ""),
        }
    else:
        return {
            "messages": [AIMessage(content=chart_url)],
            "error": "chart_failed",
        }


def build_viz_error_result(error: Exception) -> dict[str, Any]:
    """Baut Fehler-Ergebnis."""
    error_msg = f"Fehler bei Visualisierung: {str(error)}"
    logger.error(error_msg, exc_info=True)
    return {
        "messages": [AIMessage(content=error_msg)],
        "error": str(error),
    }


# =============================================================================
# HAUPTFUNKTION
# =============================================================================

async def run_viz_agent(state: AgentState) -> dict[str, Any]:
    """
    Führt den Viz Agent aus.
    
    Orchestriert:
    1. Daten-Extraktion
    2. Kontext-Vorbereitung
    3. Tool-Auswahl (LLM)
    4. Chart-Generierung (MCP)
    """
    try:
        logger.debug("Starte Viz Agent")
        
        # 1. Daten und Kontext vorbereiten
        data, meta_info = prepare_viz_context(state)
        
        if not data:
            return {
                "messages": [AIMessage(content="Keine Daten zum Visualisieren.")],
                "error": "no_data",
            }
        
        # 2. User-Query extrahieren
        user_query = extract_user_query(state["messages"])
        
        # 3. LLM vorbereiten
        llm = ChatAnthropic(
            model=DEFAULT_MODEL,
            api_key=ANTHROPIC_API_KEY,
            temperature=0,
        )
        llm_with_tools = llm.bind_tools(CHART_TOOLS)
        
        # 4. Tool-State vorbereiten
        tool_state = dict(state)
        tool_state["datasets"] = state.get("datasets", {})
        
        # 5. Ausführen mit Retry
        chart_url, tool_name = await execute_viz_with_retry(
            llm_with_tools, user_query, meta_info, tool_state
        )
        
        # 6. Ergebnis
        return build_viz_result(chart_url, tool_name)
    
    except Exception as e:
        return build_viz_error_result(e)


async def viz_agent_node(state: AgentState) -> dict[str, Any]:
    """LangGraph Node für den Viz Agent."""
    return await run_viz_agent(state)


# =============================================================================
# TEST
# =============================================================================

async def test_viz_agent():
    import time
    from datetime import timedelta
    
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    
    print("\n" + "="*60)
    print("🧪 Viz Agent Test")
    print("="*60)
    
    now = datetime.now()
    
    test_datasets = {
        "torque": {
            "data": {
                "torque_act_a1_nm": [
                    {"value": str(25 + i), "timestamp": int((now - timedelta(minutes=10-i)).timestamp() * 1000)}
                    for i in range(10)
                ],
                "torque_act_a2_nm": [
                    {"value": str(15 + i), "timestamp": int((now - timedelta(minutes=10-i)).timestamp() * 1000)}
                    for i in range(10)
                ],
            },
            "meta": {"timerange": {"weekday": "Dienstag", "start": "10:00", "end": "10:10"}},
        },
    }
    
    state = AgentState(
        messages=[HumanMessage(content="Zeig mir den Verlauf der Drehmomente")],
        datasets=test_datasets,
    )
    
    start = time.time()
    result = await run_viz_agent(state)
    duration = time.time() - start
    
    print(f"⏱️ Dauer: {duration:.1f}s")
    print(f"📊 Typ: {result.get('chart_type')}")
    print(f"🔗 URL: {result.get('chart_url', 'FEHLER')}")


if __name__ == "__main__":
    asyncio.run(test_viz_agent())
