"""
Viz Agent für Chart-Generierung.

DESIGN:
- LLM wählt Chart-Typ und Parameter
- Daten kommen via InjectedState, NICHT durch LLM-Prompt
- Best Practice nach LangGraph Dokumentation

DESIGN-ENTSCHEIDUNGEN:
- DEC-003: InjectedState für Daten-Übergabe
- DEC-013: Multi-Turn Support mit datasets
- DEC-016: Strukturiertes Logging, Retry-Mechanismus

VERFÜGBARE CHARTS (10):
- Line, Area (Zeitreihen)
- Column, Bar (Vergleiche)
- Scatter (Korrelationen)
- Boxplot, Violin, Histogram (Verteilungen/Statistik)
- Pie (Anteile)
- Radar (Multidimensional)
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import asyncio
import logging
from contextlib import AsyncExitStack
from datetime import datetime
from typing import Any, Annotated, Tuple

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from agents.state import AgentState
from agents.utils import extract_data_from_datasets, get_dataset_meta, get_y_label, extract_user_query, get_data_from_state
from config.settings import DEFAULT_MODEL, api_key_rotator, create_anthropic_client, create_cached_system_message
from prompts.viz_agent_prompt import VIZ_AGENT_SYSTEM_PROMPT


# =============================================================================
# LOGGING KONFIGURATION (DEC-016)
# =============================================================================

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY_BASE = 2


# =============================================================================
# MCP SESSION PROVIDER (DEC-016)
# =============================================================================

class AntVSessionProvider:
    """Verwaltet AntV MCP Session mit Caching."""
    
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
# DATEN-TRANSFORMATION HELPERS
# =============================================================================

def timestamp_to_time_string(ts: int, include_date: bool = False) -> str:
    """Konvertiert Timestamp zu lesbarem Zeit-String.

    Args:
        ts: Unix-Timestamp in Millisekunden
        include_date: True für mehrtägige Daten (Format: "DD.MM. HH:MM")
    """
    try:
        dt = datetime.fromtimestamp(ts / 1000)
        if include_date:
            return dt.strftime("%d.%m. %H:%M")
        return dt.strftime("%H:%M:%S")
    except:
        return str(ts)


def shorten_key_name(key: str) -> str:
    """Kürzt Daten-Key für Chart-Legenden."""
    return (key
        .replace("torque_act_", "T")
        .replace("axis_act_", "A")
        .replace("pos_act_", "p")
        .replace("_deg", "°")
        .replace("_nm", "")
        .replace("_mm", "")
        .replace("vel_act_", "V")
        .replace("_m_per_s", "")
        .replace("acc_axis_", "Acc"))


def extract_numeric_values(values: list) -> list[float]:
    """Extrahiert numerische Werte aus ThingsBoard-Format."""
    result = []
    for point in values:
        if isinstance(point, dict):
            try:
                result.append(float(point.get("value", 0)))
            except (ValueError, TypeError):
                continue
        elif isinstance(point, (int, float)):
            result.append(float(point))
    return result


def sample_data(data: list, max_points: int = 500) -> list:
    """Reduziert Datenpunkte durch Sampling."""
    if len(data) <= max_points:
        return data
    step = len(data) // max_points
    return data[::step][:max_points]


# =============================================================================
# TRANSFORMATION FUNCTIONS (Für jeden Chart-Typ)
# =============================================================================

def transform_for_line_chart(data: dict[str, list], multi_key: bool = False) -> list[dict]:
    """Transformiert Daten für Line/Area Chart: [{time, value, group?}]"""
    # Zeitspanne ermitteln um passendes Format zu wählen
    all_timestamps = []
    for values in data.values():
        if isinstance(values, list):
            for point in values:
                if isinstance(point, dict) and "timestamp" in point:
                    all_timestamps.append(point["timestamp"])

    include_date = False
    if all_timestamps:
        span_hours = (max(all_timestamps) - min(all_timestamps)) / (1000 * 3600)
        include_date = span_hours > 24

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

                entry = {"time": timestamp_to_time_string(ts, include_date), "value": val}

                if multi_key:
                    entry["group"] = shorten_key_name(key)

                result.append(entry)

        if not multi_key:
            break

    result.sort(key=lambda x: (x["time"], x.get("group", "")))
    return sample_data(result)


def transform_for_category_chart(data: dict[str, list]) -> list[dict]:
    """Transformiert Daten für Column/Bar/Pie Chart: [{category, value}]"""
    result = []
    
    for key, values in data.items():
        if not isinstance(values, list) or not values:
            continue
        
        nums = extract_numeric_values(values)
        if nums:
            avg = sum(nums) / len(nums)
            result.append({"category": shorten_key_name(key), "value": round(avg, 2)})
    
    return result


def transform_for_scatter_chart(data: dict[str, list]) -> list[dict]:
    """Transformiert Daten für Scatter Chart: [{x, y}]"""
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
    
    result = [{"x": x_vals[ts], "y": y_vals[ts]} for ts in x_vals if ts in y_vals]
    return sample_data(result)


def transform_for_distribution_chart(data: dict[str, list]) -> list[dict]:
    """Transformiert Daten für Boxplot/Violin Chart: [{category, value}]"""
    result = []
    
    for key, values in data.items():
        if not isinstance(values, list) or not values:
            continue
        
        nums = extract_numeric_values(values)
        short_key = shorten_key_name(key)
        
        # Jeder Einzelwert wird ein Datenpunkt
        for val in nums:
            result.append({"category": short_key, "value": round(val, 4)})
    
    return sample_data(result, max_points=1000)


def transform_for_histogram_chart(data: dict[str, list]) -> list[float]:
    """Transformiert Daten für Histogram Chart: [number, number, ...]"""
    all_values = []
    
    for key, values in data.items():
        if not isinstance(values, list):
            continue
        nums = extract_numeric_values(values)
        all_values.extend(nums)
    
    return sample_data(all_values, max_points=1000)


def transform_for_radar_chart(data: dict[str, list]) -> list[dict]:
    """Transformiert Daten für Radar Chart: [{name, value}]"""
    result = []
    
    for key, values in data.items():
        if not isinstance(values, list) or not values:
            continue
        
        nums = extract_numeric_values(values)
        if nums:
            avg = sum(nums) / len(nums)
            result.append({"name": shorten_key_name(key), "value": round(avg, 2)})
    
    return result


# =============================================================================
# CHART URL EXTRACTION
# =============================================================================

def extract_chart_url(result) -> str:
    """Extrahiert URL aus MCP-Tool-Ergebnis."""
    if hasattr(result, 'content') and result.content:
        for block in result.content:
            if hasattr(block, 'text'):
                text = block.text.strip()
                if text.startswith("http"):
                    return text
                # Prüfe auf Fehler
                if "error" in text.lower():
                    logger.warning(f"Chart-Fehler: {text[:100]}")
                    return f"Fehler: {text[:200]}"
    return "Fehler: Keine URL vom Chart-Server"


# =============================================================================
# CHART TOOLS MIT INJECTEDSTATE
# =============================================================================

@tool
async def generate_line_chart_tool(
    title: str,
    state: Annotated[dict, InjectedState],
) -> str:
    """
    Erstellt ein Liniendiagramm für Zeitreihen-Daten.
    
    WANN BENUTZEN:
    - Verlauf über Zeit, Trends, Historie
    - Kontinuierliche Messwerte
    
    Args:
        title: Beschreibender Titel, z.B. "Drehmomente - 16.12.2025"
    """
    logger.debug(f"generate_line_chart_tool: title={title}")
    
    data = get_data_from_state(state)
    
    if not data:
        return "Fehler: Keine Daten im State"
    
    keys = list(data.keys())
    multi_key = len(keys) > 1
    transformed = transform_for_line_chart(data, multi_key)
    
    if not transformed:
        return "Fehler: Keine gültigen Datenpunkte"
    
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
async def generate_area_chart_tool(
    title: str,
    state: Annotated[dict, InjectedState],
) -> str:
    """
    Erstellt ein Flächendiagramm für kumulative Zeitreihen.
    
    WANN BENUTZEN:
    - Kumulative Daten über Zeit
    - Betonung der Gesamtmenge
    - Gestapelte Vergleiche mehrerer Serien
    
    Args:
        title: Beschreibender Titel
    """
    logger.debug(f"generate_area_chart_tool: title={title}")
    
    data = get_data_from_state(state)
    
    if not data:
        return "Fehler: Keine Daten im State"
    
    keys = list(data.keys())
    multi_key = len(keys) > 1
    transformed = transform_for_line_chart(data, multi_key)
    
    if not transformed:
        return "Fehler: Keine gültigen Datenpunkte"
    
    session = await get_antv_session()
    result = await session.call_tool(
        "generate_area_chart",
        arguments={
            "data": transformed,
            "title": title,
            "axisXTitle": "Zeit",
            "axisYTitle": get_y_label(keys),
            "stack": multi_key,
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
    Erstellt ein vertikales Säulendiagramm zum Vergleich.
    
    WANN BENUTZEN:
    - Vergleich zwischen Kategorien
    - Durchschnittswerte nebeneinander
    
    Args:
        title: Beschreibender Titel
    """
    logger.debug(f"generate_column_chart_tool: title={title}")
    
    data = get_data_from_state(state)
    
    if not data:
        return "Fehler: Keine Daten im State"
    
    transformed = transform_for_category_chart(data)
    
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
async def generate_bar_chart_tool(
    title: str,
    state: Annotated[dict, InjectedState],
) -> str:
    """
    Erstellt ein horizontales Balkendiagramm zum Vergleich.
    
    WANN BENUTZEN:
    - Horizontaler Vergleich
    - Lange Kategorie-Namen
    - Ranking-Darstellung
    
    Args:
        title: Beschreibender Titel
    """
    logger.debug(f"generate_bar_chart_tool: title={title}")
    
    data = get_data_from_state(state)
    
    if not data:
        return "Fehler: Keine Daten im State"
    
    transformed = transform_for_category_chart(data)
    
    if not transformed:
        return "Fehler: Keine gültigen Datenpunkte"
    
    session = await get_antv_session()
    result = await session.call_tool(
        "generate_bar_chart",
        arguments={
            "data": transformed,
            "title": title,
            "axisXTitle": get_y_label(list(data.keys())),
            "axisYTitle": "Kategorie",
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
    Erstellt ein Streudiagramm für Korrelationen.
    
    WANN BENUTZEN:
    - Korrelation zwischen zwei Variablen
    - Zusammenhang, Beziehung
    - Mindestens 2 Daten-Keys erforderlich
    
    Args:
        title: Beschreibender Titel
    """
    logger.debug(f"generate_scatter_chart_tool: title={title}")
    
    data = get_data_from_state(state)
    
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
            "axisXTitle": shorten_key_name(keys[0]),
            "axisYTitle": shorten_key_name(keys[1]),
            "width": 800,
            "height": 500,
        }
    )
    
    return extract_chart_url(result)


@tool
async def generate_boxplot_chart_tool(
    title: str,
    state: Annotated[dict, InjectedState],
) -> str:
    """
    Erstellt ein Boxplot für statistische Verteilung.
    
    WANN BENUTZEN:
    - Verteilung der Werte anzeigen
    - Median, Quartile, Ausreißer sichtbar
    - Vergleich mehrerer Kategorien
    
    Args:
        title: Beschreibender Titel
    """
    logger.debug(f"generate_boxplot_chart_tool: title={title}")
    
    data = get_data_from_state(state)
    
    if not data:
        return "Fehler: Keine Daten im State"
    
    transformed = transform_for_distribution_chart(data)
    
    if not transformed:
        return "Fehler: Keine gültigen Datenpunkte"
    
    session = await get_antv_session()
    result = await session.call_tool(
        "generate_boxplot_chart",
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
async def generate_violin_chart_tool(
    title: str,
    state: Annotated[dict, InjectedState],
) -> str:
    """
    Erstellt ein Violin-Chart für Dichteverteilung.
    
    WANN BENUTZEN:
    - Verteilung mit Dichtekurve
    - Detaillierter als Boxplot
    - Vergleich von Verteilungen
    
    Args:
        title: Beschreibender Titel
    """
    logger.debug(f"generate_violin_chart_tool: title={title}")
    
    data = get_data_from_state(state)
    
    if not data:
        return "Fehler: Keine Daten im State"
    
    transformed = transform_for_distribution_chart(data)
    
    if not transformed:
        return "Fehler: Keine gültigen Datenpunkte"
    
    session = await get_antv_session()
    result = await session.call_tool(
        "generate_violin_chart",
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
async def generate_histogram_chart_tool(
    title: str,
    state: Annotated[dict, InjectedState],
    bin_number: int = 10,
) -> str:
    """
    Erstellt ein Histogramm für Häufigkeitsverteilung.
    
    WANN BENUTZEN:
    - Wie oft kommen bestimmte Werte vor?
    - Normalverteilung prüfen
    - Datenkonzentration erkennen
    
    Args:
        title: Beschreibender Titel
        bin_number: Anzahl der Intervalle (default: 10)
    """
    logger.debug(f"generate_histogram_chart_tool: title={title}, bins={bin_number}")
    
    data = get_data_from_state(state)
    
    if not data:
        return "Fehler: Keine Daten im State"
    
    transformed = transform_for_histogram_chart(data)
    
    if not transformed:
        return "Fehler: Keine gültigen Datenpunkte"
    
    session = await get_antv_session()
    result = await session.call_tool(
        "generate_histogram_chart",
        arguments={
            "data": transformed,
            "title": title,
            "binNumber": bin_number,
            "axisXTitle": get_y_label(list(data.keys())),
            "axisYTitle": "Häufigkeit",
            "width": 800,
            "height": 500,
        }
    )
    
    return extract_chart_url(result)


@tool
async def generate_pie_chart_tool(
    title: str,
    state: Annotated[dict, InjectedState],
) -> str:
    """
    Erstellt ein Kreisdiagramm für Anteile.
    
    WANN BENUTZEN:
    - Anteil am Ganzen zeigen
    - Prozentuale Verteilung
    - Wenige Kategorien (max 6-8)
    
    Args:
        title: Beschreibender Titel
    """
    logger.debug(f"generate_pie_chart_tool: title={title}")
    
    data = get_data_from_state(state)
    
    if not data:
        return "Fehler: Keine Daten im State"
    
    transformed = transform_for_category_chart(data)
    
    if not transformed:
        return "Fehler: Keine gültigen Datenpunkte"
    
    session = await get_antv_session()
    result = await session.call_tool(
        "generate_pie_chart",
        arguments={
            "data": transformed,
            "title": title,
            "width": 600,
            "height": 500,
        }
    )
    
    return extract_chart_url(result)


@tool
async def generate_radar_chart_tool(
    title: str,
    state: Annotated[dict, InjectedState],
) -> str:
    """
    Erstellt ein Radar-/Spinnennetz-Diagramm für Mehrfachvergleich.
    
    WANN BENUTZEN:
    - Mehrere Dimensionen gleichzeitig vergleichen
    - Stärken/Schwächen-Profil
    - Mindestens 3 Kategorien sinnvoll
    
    Args:
        title: Beschreibender Titel
    """
    logger.debug(f"generate_radar_chart_tool: title={title}")
    
    data = get_data_from_state(state)
    
    if not data:
        return "Fehler: Keine Daten im State"
    
    transformed = transform_for_radar_chart(data)
    
    if len(transformed) < 3:
        return "Fehler: Radar-Chart braucht mindestens 3 Dimensionen"
    
    session = await get_antv_session()
    result = await session.call_tool(
        "generate_radar_chart",
        arguments={
            "data": transformed,
            "title": title,
            "width": 600,
            "height": 500,
        }
    )
    
    return extract_chart_url(result)


# =============================================================================
# TOOL-LISTE
# =============================================================================

CHART_TOOLS = [
    # Zeitreihen
    generate_line_chart_tool,
    generate_area_chart_tool,
    # Vergleiche
    generate_column_chart_tool,
    generate_bar_chart_tool,
    # Korrelationen
    generate_scatter_chart_tool,
    # Statistik/Verteilung
    generate_boxplot_chart_tool,
    generate_violin_chart_tool,
    generate_histogram_chart_tool,
    # Anteile/Dimensional
    generate_pie_chart_tool,
    generate_radar_chart_tool,
]


# =============================================================================
# HAUPTLOGIK (DEC-016: Aufgeteilt)
# =============================================================================

def prepare_viz_context(state: AgentState) -> Tuple[dict, str]:
    """Bereitet Kontext für LLM vor (DEC-025: DuckDB-first)."""
    data = get_data_from_state(state)

    if not data:
        return {}, ""

    keys = list(data.keys())
    datasets = state.get("datasets", {})
    meta_info = f"Verfügbare Daten: {len(keys)} Keys ({', '.join(keys[:5])}{'...' if len(keys) > 5 else ''})"
    meta_info += f"\nGeladene Datasets: {', '.join(datasets.keys())}"

    # Zeitraum: DuckDB als Source-of-Truth, Fallback auf Dataset-Meta
    timerange_str = _get_timerange_from_duckdb(state)
    if timerange_str:
        meta_info += f"\nZeitraum: {timerange_str}"
    else:
        dataset_meta = get_dataset_meta(datasets)
        if dataset_meta.get("timerange"):
            tr = dataset_meta["timerange"]
            meta_info += f"\nZeitraum: {tr.get('weekday', '')} {tr.get('start', '')} - {tr.get('end', '')}"

    return data, meta_info


def _get_timerange_from_duckdb(state: dict) -> str:
    """Berechnet den tatsächlichen Zeitraum aus DuckDB-Timestamps."""
    session_id = state.get("session_id", "default")
    try:
        from config.duckdb_store import SessionStore
        if session_id not in SessionStore._instances:
            return ""
        store = SessionStore.get_instance(session_id)
        rows = store.query("SELECT MIN(ts), MAX(ts) FROM telemetry WHERE ts > 0")
        if not rows or not rows[0][0]:
            return ""
        min_ts, max_ts = rows[0]
        start = datetime.fromtimestamp(min_ts / 1000)
        end = datetime.fromtimestamp(max_ts / 1000)
        weekdays = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
        weekday = weekdays[start.weekday()]
        return f"{weekday} {start.strftime('%d.%m.%Y %H:%M')} - {end.strftime('%H:%M')}"
    except Exception as e:
        logger.debug(f"Zeitraum aus DuckDB nicht ermittelbar: {e}")
        return ""


async def select_and_execute_tool(
    llm_with_tools,
    user_query: str,
    meta_info: str,
    tool_state: dict
) -> Tuple[str, str]:
    """Lässt LLM Tool auswählen und führt es aus."""
    # DEC-021: SystemMessage mit cache_control für Prompt Caching
    messages = [
        create_cached_system_message(VIZ_AGENT_SYSTEM_PROMPT),
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
    
    tool_map = {t.name: t for t in CHART_TOOLS}
    
    if tool_name in tool_map:
        chart_url = await tool_map[tool_name].ainvoke(tool_args)
    else:
        chart_url = f"Unbekanntes Tool: {tool_name}"
    
    return chart_url, tool_name


async def execute_viz_with_retry(
    user_query: str,
    meta_info: str,
    tool_state: dict,
    max_retries: int = MAX_RETRIES
) -> Tuple[str, str]:
    """
    Führt Visualisierung mit Retry aus.

    DEC-018: Bei Rate Limit (429) wird der API Key rotiert und
    ein neuer LLM-Client erstellt.
    """
    last_exception = None

    # LLM mit Tools erstellen (wird bei Key-Rotation neu erstellt)
    llm = create_anthropic_client()
    llm_with_tools = llm.bind_tools(CHART_TOOLS)

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
                logger.warning(f"Rate Limit mit {api_key_rotator.get_key_info()} (Versuch {attempt + 1}/{max_retries})")

                if attempt < max_retries - 1:
                    # Key rotieren und neuen Client erstellen (DEC-018)
                    api_key_rotator.rotate()
                    llm = create_anthropic_client()
                    llm_with_tools = llm.bind_tools(CHART_TOOLS)

                    delay = RETRY_DELAY_BASE * (2 ** attempt)
                    logger.info(f"Neuer Key: {api_key_rotator.get_key_info()}, warte {delay}s...")
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
    """Führt den Viz Agent aus."""
    try:
        logger.debug("Starte Viz Agent")
        
        data, meta_info = prepare_viz_context(state)
        
        if not data:
            return {
                "messages": [AIMessage(content="Keine Daten zum Visualisieren.")],
                "error": "no_data",
            }
        
        user_query = extract_user_query(state["messages"])

        tool_state = dict(state)
        tool_state["datasets"] = state.get("datasets", {})

        # DEC-018: LLM-Erstellung und Key-Rotation passiert in execute_viz_with_retry
        chart_url, tool_name = await execute_viz_with_retry(
            user_query, meta_info, tool_state
        )
        
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
    """Testet alle Chart-Typen."""
    import time
    from datetime import timedelta
    import random
    
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    
    print("\n" + "="*60)
    print("🧪 Viz Agent Test - Alle 10 Chart-Typen")
    print("="*60)
    
    now = datetime.now()
    
    # Test-Daten mit mehreren Keys
    test_datasets = {
        "roboter": {
            "data": {
                "torque_act_a1_nm": [
                    {"value": str(25 + random.gauss(0, 5)), "timestamp": int((now - timedelta(minutes=20-i)).timestamp() * 1000)}
                    for i in range(20)
                ],
                "torque_act_a2_nm": [
                    {"value": str(15 + random.gauss(0, 3)), "timestamp": int((now - timedelta(minutes=20-i)).timestamp() * 1000)}
                    for i in range(20)
                ],
                "torque_act_a3_nm": [
                    {"value": str(20 + random.gauss(0, 4)), "timestamp": int((now - timedelta(minutes=20-i)).timestamp() * 1000)}
                    for i in range(20)
                ],
            },
            "meta": {"timerange": {"weekday": "Montag", "start": "10:00", "end": "10:20"}},
        },
    }
    
    # Teste verschiedene Anfragen
    test_queries = [
        ("Zeig mir den Verlauf der Drehmomente", "line"),
        ("Vergleiche die Achsen", "column"),
        ("Zeig die Verteilung als Boxplot", "boxplot"),
        ("Erstelle ein Histogramm", "histogram"),
        ("Zeig alle Achsen im Radar-Chart", "radar"),
    ]
    
    for query, expected_type in test_queries:
        print(f"\n{'='*40}")
        print(f"📝 Query: {query}")
        print(f"   Erwarteter Typ: {expected_type}")
        
        state = AgentState(
            messages=[HumanMessage(content=query)],
            datasets=test_datasets,
        )
        
        start = time.time()
        result = await run_viz_agent(state)
        duration = time.time() - start
        
        print(f"⏱️ Dauer: {duration:.1f}s")
        print(f"📊 Typ: {result.get('chart_type', 'N/A')}")
        
        url = result.get('chart_url', '')
        if url.startswith("http"):
            print(f"✅ URL: {url[:60]}...")
        else:
            print(f"❌ Fehler: {url[:100]}")


if __name__ == "__main__":
    asyncio.run(test_viz_agent())
