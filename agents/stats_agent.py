"""
Stats Agent für statistische Analysen von IIoT-Daten.

DESIGN:
- LLM wählt Analyse-Typ und Parameter (welche Keys)
- Daten kommen via InjectedState, NICHT durch LLM-Prompt
- Konsistent mit Viz Agent Pattern (DEC-003)

DESIGN-ENTSCHEIDUNGEN:
- DEC-003: InjectedState für Daten-Übergabe
- DEC-013: Multi-Turn Support mit datasets
- DEC-016: Strukturiertes Logging
- DEC-024: Timeseries Korrelation mit merge_asof

VERFÜGBARE TOOLS (8):
- mean_tool: Durchschnitt
- std_tool: Standardabweichung
- min_max_tool: Minimum/Maximum
- correlation_tool: Korrelation zwischen zwei Keys (DEC-024)
- trend_tool: Linearer Trend
- percentiles_tool: Perzentile/Quartile
- anomaly_tool: Ausreißererkennung
- summary_tool: Komplette Statistik-Übersicht
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import json
import asyncio
import logging
from datetime import datetime
from typing import Any, Annotated

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from agents.state import AgentState
from agents.utils import (
    extract_data_from_datasets,
    extract_values_from_data,
    extract_timestamps_from_data,
    extract_user_query,
    get_data_from_state,
    get_values_for_key,
    get_timeseries_for_key,
    get_available_signal_keys,
)
from prompts.stats_agent_prompt import get_stats_agent_prompt
from config.settings import create_anthropic_client, create_cached_system_message

# Stats-Funktionen
from tools.stats_functions import (
    calculate_mean,
    calculate_std,
    calculate_min_max,
    calculate_correlation_timeseries,
    calculate_linear_trend,
    calculate_percentiles,
    detect_anomalies,
)


# =============================================================================
# LOGGING KONFIGURATION (DEC-016)
# =============================================================================

logger = logging.getLogger(__name__)


# =============================================================================
# DEBUG LOGGING (Datei-basiert für Prompt-Analyse)
# =============================================================================

_DEBUG_LOG_PATH = PROJECT_ROOT / "logs" / "stats_agent_debug.log"
_DEBUG_LOG_ENABLED = True


def _debug_log(text: str) -> None:
    """Schreibt Debug-Text in die Stats-Agent Log-Datei."""
    if not _DEBUG_LOG_ENABLED:
        return
    try:
        _DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except Exception:
        pass


# =============================================================================
# HILFSFUNKTIONEN
# =============================================================================

def get_available_keys(state: dict) -> list[str]:
    """Extrahiert verfügbare Keys aus dem State (DEC-025: DuckDB-first)."""
    return get_available_signal_keys(state)


def format_result(result: dict, tool_name: str) -> str:
    """Formatiert ein Ergebnis als lesbaren String."""
    if "error" in result:
        return f"Fehler: {result['error']}"

    return json.dumps(result, indent=2, ensure_ascii=False)


# =============================================================================
# STATS TOOLS MIT INJECTEDSTATE (DEC-003)
# =============================================================================

@tool
def mean_tool(
    key: str,
    state: Annotated[dict, InjectedState],
) -> str:
    """
    Berechnet den Durchschnitt für einen Telemetrie-Key.

    WANN BENUTZEN:
    - "Durchschnitt", "Mittelwert", "average", "im Schnitt"
    - "durchschnittliche Temperatur/Drehmoment"

    Args:
        key: Der Telemetrie-Key, z.B. "torque_act_a1_nm"
    """
    logger.debug(f"mean_tool: key={key}")

    available = get_available_signal_keys(state)
    if key not in available:
        return f"Key '{key}' nicht gefunden. Verfügbar: {available[:5]}"

    values = get_values_for_key(state, key)
    if not values:
        return f"Keine gültigen Werte für Key '{key}'"

    result = calculate_mean(values)
    result["key"] = key
    return format_result(result, "mean")


@tool
def std_tool(
    key: str,
    state: Annotated[dict, InjectedState],
) -> str:
    """
    Berechnet die Standardabweichung (Streuung) für einen Key.

    WANN BENUTZEN:
    - "Streuung", "Standardabweichung", "wie stark schwanken"
    - "Stabilität" der Messwerte

    Args:
        key: Der Telemetrie-Key
    """
    logger.debug(f"std_tool: key={key}")

    available = get_available_signal_keys(state)
    if key not in available:
        return f"Key '{key}' nicht gefunden. Verfügbar: {available[:5]}"

    values = get_values_for_key(state, key)
    if not values:
        return f"Keine gültigen Werte für Key '{key}'"

    result = calculate_std(values)
    result["key"] = key
    return format_result(result, "std")


@tool
def min_max_tool(
    key: str,
    state: Annotated[dict, InjectedState],
) -> str:
    """
    Gibt Minimum, Maximum und Spannweite für einen Key.

    WANN BENUTZEN:
    - "Minimum", "Maximum", "höchster/niedrigster Wert"
    - "Bereich", "Spanne", "Extremwerte"

    Args:
        key: Der Telemetrie-Key
    """
    logger.debug(f"min_max_tool: key={key}")

    available = get_available_signal_keys(state)
    if key not in available:
        return f"Key '{key}' nicht gefunden. Verfügbar: {available[:5]}"

    values = get_values_for_key(state, key)
    if not values:
        return f"Keine gültigen Werte für Key '{key}'"

    result = calculate_min_max(values)
    result["key"] = key
    return format_result(result, "min_max")


@tool
def correlation_tool(
    key_x: str,
    key_y: str,
    state: Annotated[dict, InjectedState],
) -> str:
    """
    Berechnet die Korrelation zwischen zwei Telemetrie-Keys (DEC-024).

    Nutzt merge_asof für Timestamp-Alignment - funktioniert auch bei
    unterschiedlichen Datenlängen (typisch für IoT-Sensoren).

    WANN BENUTZEN:
    - "Korrelation", "Zusammenhang", "Beziehung zwischen"
    - "hängt X mit Y zusammen?"

    INTERPRETATION:
    - r > 0.7: stark positiv
    - r < -0.7: stark negativ
    - |r| < 0.3: kein/schwacher Zusammenhang

    Args:
        key_x: Erster Telemetrie-Key, z.B. "torque_act_a1_nm"
        key_y: Zweiter Telemetrie-Key, z.B. "axis_act_a1_deg"
    """
    logger.debug(f"correlation_tool: key_x={key_x}, key_y={key_y}")

    available = get_available_signal_keys(state)
    if key_x not in available:
        return f"Key '{key_x}' nicht gefunden. Verfügbar: {available[:5]}"
    if key_y not in available:
        return f"Key '{key_y}' nicht gefunden. Verfügbar: {available[:5]}"

    # DEC-025: Timestamps und Werte über DuckDB-first Helper
    x_timestamps, x_values = get_timeseries_for_key(state, key_x)
    y_timestamps, y_values = get_timeseries_for_key(state, key_y)

    if not x_values or not y_values:
        return "Keine gültigen Werte für einen der Keys"

    if not x_timestamps or not y_timestamps:
        return "Keine Timestamps vorhanden - Korrelation benötigt Zeitreihen"

    # Berechne Korrelation mit Timestamp-Alignment (DEC-024)
    result = calculate_correlation_timeseries(
        x_timestamps, x_values,
        y_timestamps, y_values,
        tolerance_ms=1000,
    )

    result["key_x"] = key_x
    result["key_y"] = key_y

    logger.info(f"Korrelation {key_x} ↔ {key_y}: r={result.get('r')}, n_matched={result.get('n_matched')}")

    return format_result(result, "correlation")


@tool
def trend_tool(
    key: str,
    state: Annotated[dict, InjectedState],
) -> str:
    """
    Berechnet den linearen Trend für einen Key.

    WANN BENUTZEN:
    - "Trend", "Tendenz", "Entwicklung"
    - "steigend/fallend/stabil?"

    Args:
        key: Der Telemetrie-Key
    """
    logger.debug(f"trend_tool: key={key}")

    available = get_available_signal_keys(state)
    if key not in available:
        return f"Key '{key}' nicht gefunden. Verfügbar: {available[:5]}"

    timestamps, values = get_timeseries_for_key(state, key)

    if not values:
        return f"Keine gültigen Werte für Key '{key}'"

    result = calculate_linear_trend(values, timestamps if timestamps else None)
    result["key"] = key
    return format_result(result, "trend")


@tool
def percentiles_tool(
    key: str,
    state: Annotated[dict, InjectedState],
) -> str:
    """
    Berechnet Perzentile (Quartile: 25%, 50%, 75%) für einen Key.

    WANN BENUTZEN:
    - "Perzentil", "Median", "Quartil"
    - "Verteilung der Werte"

    Args:
        key: Der Telemetrie-Key
    """
    logger.debug(f"percentiles_tool: key={key}")

    available = get_available_signal_keys(state)
    if key not in available:
        return f"Key '{key}' nicht gefunden. Verfügbar: {available[:5]}"

    values = get_values_for_key(state, key)
    if not values:
        return f"Keine gültigen Werte für Key '{key}'"

    result = calculate_percentiles(values)
    result["key"] = key
    return format_result(result, "percentiles")


@tool
def anomaly_tool(
    key: str,
    sigma_threshold: float = 2.0,
    state: Annotated[dict, InjectedState] = None,
) -> str:
    """
    Erkennt Ausreißer/Anomalien mittels Z-Score.

    WANN BENUTZEN:
    - "Ausreißer", "Anomalie", "ungewöhnlich"
    - "Spitzen", "extreme Werte"

    Args:
        key: Der Telemetrie-Key
        sigma_threshold: Ab wieviel σ gilt als Ausreißer (default: 2.0)
    """
    logger.debug(f"anomaly_tool: key={key}, sigma={sigma_threshold}")

    available = get_available_signal_keys(state)
    if key not in available:
        return f"Key '{key}' nicht gefunden. Verfügbar: {available[:5]}"

    values = get_values_for_key(state, key)
    if not values:
        return f"Keine gültigen Werte für Key '{key}'"

    result = detect_anomalies(values, sigma_threshold)
    result["key"] = key
    return format_result(result, "anomaly")


@tool
def summary_tool(
    key: str,
    state: Annotated[dict, InjectedState],
) -> str:
    """
    Gibt eine komplette Statistik-Übersicht für einen Key.

    Berechnet: Durchschnitt, Std, Min, Max, Median, Trend

    WANN BENUTZEN:
    - "Statistik-Übersicht", "alle Kennzahlen"
    - "Zusammenfassung der Daten"

    Args:
        key: Der Telemetrie-Key
    """
    logger.debug(f"summary_tool: key={key}")

    available = get_available_signal_keys(state)
    if key not in available:
        return f"Key '{key}' nicht gefunden. Verfügbar: {available[:5]}"

    timestamps, values = get_timeseries_for_key(state, key)

    if not values:
        return f"Keine gültigen Werte für Key '{key}'"

    # Alle Statistiken berechnen
    mean_result = calculate_mean(values)
    std_result = calculate_std(values)
    minmax_result = calculate_min_max(values)
    percentiles_result = calculate_percentiles(values)
    trend_result = calculate_linear_trend(values, timestamps if timestamps else None)

    summary = {
        "key": key,
        "count": len(values),
        "mean": mean_result.get("mean"),
        "std": std_result.get("std"),
        "min": minmax_result.get("min"),
        "max": minmax_result.get("max"),
        "range": minmax_result.get("range"),
        "median": percentiles_result.get("p50"),
        "p25": percentiles_result.get("p25"),
        "p75": percentiles_result.get("p75"),
        "trend": trend_result.get("trend"),
        "trend_slope": trend_result.get("slope"),
    }

    return format_result(summary, "summary")


# =============================================================================
# TOOL LISTE
# =============================================================================

STATS_TOOLS = [
    mean_tool,
    std_tool,
    min_max_tool,
    correlation_tool,
    trend_tool,
    percentiles_tool,
    anomaly_tool,
    summary_tool,
]


async def get_stats_tools() -> list:
    """
    Gibt die Stats Tools zurück (für Warmup/Kompatibilität).

    Hinweis: Stats Agent nutzt kein MCP mehr (DEC-024 Refactoring).
    Diese Funktion existiert für Kompatibilität mit app.py Warmup.
    """
    logger.debug("Stats Tools bereit (kein MCP mehr)")
    return STATS_TOOLS


# =============================================================================
# CONTEXT VORBEREITUNG (NUR METADATEN!)
# =============================================================================

def prepare_stats_context(state: AgentState) -> str:
    """
    Bereitet den Daten-Kontext für den Stats Agent vor.

    WICHTIG: Nur Metadaten, KEINE Werte! (DEC-003/DEC-004)
    Das LLM soll nur wissen welche Keys verfügbar sind.

    DEC-025: Nutzt DuckDB-first Helpers für Key-Auflistung.
    """
    context_parts = []

    # Verfügbare Keys (DEC-025: DuckDB-first)
    available_keys = get_available_signal_keys(state)

    if available_keys:
        context_parts.append("\n## VERFÜGBARE KEYS")

        for key in available_keys:
            timestamps, values = get_timeseries_for_key(state, key)

            if values:
                context_parts.append(f"- {key}: {len(values)} Werte" +
                                   (" (mit Timestamps)" if timestamps else ""))
    else:
        context_parts.append("Keine Daten geladen.")

    return "\n".join(context_parts)


# =============================================================================
# TOOL AUSFÜHRUNG (wie Viz Agent)
# =============================================================================

async def select_and_execute_tool(
    llm_with_tools,
    user_query: str,
    data_context: str,
    tool_state: dict,
) -> tuple[dict | None, str]:
    """
    Lässt LLM Tool auswählen und führt es aus.
    Pattern: Wie Viz Agent - manuelles State-Injection.
    """
    system_prompt = get_stats_agent_prompt()
    system_content = f"{system_prompt}\n\n## AKTUELLE DATEN\n\n{data_context}"

    messages = [
        create_cached_system_message(system_content),
        HumanMessage(content=user_query),
    ]

    # Debug: Input loggen
    _debug_log(f"\n{'#'*80}")
    _debug_log(f"  STATS AGENT — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    _debug_log(f"{'#'*80}")
    _debug_log(f"\nUser Query: {user_query}")
    _debug_log(f"\nDaten-Kontext:\n{data_context}")
    _debug_log(f"\nSystem-Prompt Länge: {len(system_content)} Zeichen")

    logger.debug("LLM wählt Stats Tool...")
    response = await llm_with_tools.ainvoke(messages)

    # Debug: LLM Response loggen
    _debug_log(f"\n{'='*60}")
    _debug_log(f"LLM RESPONSE:")
    _debug_log(f"  Content: {response.content[:500] if response.content else '(leer)'}")
    _debug_log(f"  Tool-Calls: {len(response.tool_calls)}")
    for tc in response.tool_calls:
        args_without_state = {k: v for k, v in tc['args'].items() if k != 'state'}
        _debug_log(f"    → {tc['name']}({args_without_state})")

    if not response.tool_calls:
        _debug_log("  WARNUNG: Kein Tool gewählt!")
        logger.debug("Kein Tool-Call vom LLM")
        return None, "Keine Analyse angefordert"

    # Alle Tool-Calls ausführen
    results = []
    tool_map = {t.name: t for t in STATS_TOOLS}

    for tool_call in response.tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]

        logger.debug(f"Tool gewählt: {tool_name}, args={tool_args}")

        # State manuell injizieren (wie Viz Agent)
        tool_args["state"] = tool_state

        if tool_name in tool_map:
            result = tool_map[tool_name].invoke(tool_args)
            results.append({"tool": tool_name, "result": result})
            _debug_log(f"\n  Tool-Ergebnis ({tool_name}): {str(result)[:500]}")
        else:
            results.append({"tool": tool_name, "result": f"Unbekanntes Tool: {tool_name}"})

    return results, response.content if hasattr(response, 'content') else ""


# =============================================================================
# HAUPTFUNKTION
# =============================================================================

async def run_stats_agent(state: AgentState) -> dict[str, Any]:
    """
    Führt den Stats Agent aus.

    Pattern: InjectedState (DEC-003) - wie Viz Agent
    - LLM sieht nur Metadaten (welche Keys verfügbar)
    - LLM wählt Tool und Parameter (welche Keys analysieren)
    - State wird manuell in Tool-Args injiziert
    """
    try:
        logger.debug("Starte Stats Agent (InjectedState Pattern, DEC-025: DuckDB-first)")

        # Prüfe ob Daten vorhanden (DEC-025: DuckDB-first)
        available_keys = get_available_signal_keys(state)

        if not available_keys:
            return {
                "messages": [AIMessage(content="Keine Daten für statistische Analyse vorhanden. Bitte erst Daten laden.")],
                "error": "no_data",
            }

        # Context mit nur Metadaten
        data_context = prepare_stats_context(state)

        # User Query extrahieren
        user_query = extract_user_query(state["messages"])
        logger.debug(f"Query: {user_query}")
        logger.debug(f"Verfügbare Keys: {available_keys}")

        # LLM mit Tools
        llm = create_anthropic_client()
        llm_with_tools = llm.bind_tools(STATS_TOOLS)

        # Tool State vorbereiten (DEC-025: session_id durchreichen für DuckDB-Zugriff)
        tool_state = dict(state)
        tool_state["datasets"] = state.get("datasets", {})

        # Tool auswählen und ausführen
        results, llm_response = await select_and_execute_tool(
            llm_with_tools, user_query, data_context, tool_state
        )

        if not results:
            return {
                "messages": [AIMessage(content=llm_response or "Keine statistische Analyse durchgeführt.")],
                "statistics": None,
                "statistics_summary": "",
            }

        # Statistiken aus Ergebnissen extrahieren
        statistics = {}
        summaries = []

        for r in results:
            tool_name = r["tool"]
            result_str = r["result"]

            try:
                parsed = json.loads(result_str)
                statistics[tool_name] = parsed

                # Summary generieren (Reihenfolge wichtig: spezifische Keys vor generischen!)
                if "error" in parsed:
                    summaries.append(f"{tool_name}: {parsed['error']}")
                elif "anomalies_count" in parsed:
                    summaries.append(f"{parsed.get('key', '?')}: {parsed['anomalies_count']} Anomalien ({parsed.get('anomaly_percentage', '?')}%)")
                elif "r" in parsed:
                    key_info = f"{parsed.get('key_x', '?')} ↔ {parsed.get('key_y', '?')}"
                    summaries.append(f"Korrelation {key_info}: r={parsed['r']:.3f} ({parsed.get('interpretation', '')})")
                elif "slope" in parsed:
                    summaries.append(f"{parsed.get('key', '?')}: {parsed.get('trend', '')} (slope={parsed['slope']:.4f})")
                elif "mean" in parsed:
                    summaries.append(f"{parsed.get('key', '?')}: Durchschnitt = {parsed['mean']:.4f}")
            except json.JSONDecodeError:
                summaries.append(result_str)

        stats_summary = "; ".join(summaries)
        logger.info(f"Stats berechnet: {stats_summary[:100]}")

        # Antwort generieren
        response_text = f"Statistische Analyse:\n\n{stats_summary}"

        return {
            "messages": [AIMessage(content=response_text)],
            "statistics": statistics,
            "statistics_summary": stats_summary,
        }

    except Exception as e:
        error_msg = f"Fehler bei der statistischen Analyse: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {
            "messages": [AIMessage(content=error_msg)],
            "error": error_msg,
        }


async def stats_agent_node(state: AgentState) -> dict[str, Any]:
    """LangGraph Node für den Stats Agent."""
    return await run_stats_agent(state)


# =============================================================================
# TEST
# =============================================================================

async def test_stats_agent():
    """Test des Stats Agents."""
    from datetime import datetime, timedelta
    import random

    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    print("\n" + "="*60)
    print("🧪 Stats Agent Test (InjectedState Pattern)")
    print("="*60)

    now = datetime.now()

    # Testdaten: Zwei Keys mit leicht unterschiedlichen Timestamps
    test_datasets = {
        "test": {
            "data": {
                "torque_a1": [
                    {"value": str(25.0 + random.gauss(0, 2)), "timestamp": int((now - timedelta(minutes=50-i)).timestamp() * 1000)}
                    for i in range(50)
                ],
                "position_a1": [
                    {"value": str(45.0 + random.gauss(0, 3)), "timestamp": int((now - timedelta(minutes=50-i)).timestamp() * 1000 + random.randint(-100, 100))}
                    for i in range(48)  # Absichtlich 2 weniger!
                ],
            },
            "meta": {},
        }
    }

    print(f"📊 Test-Daten: torque_a1 (50 Punkte), position_a1 (48 Punkte)")

    state = AgentState(
        messages=[HumanMessage(content="Gibt es eine Korrelation zwischen torque_a1 und position_a1?")],
        datasets=test_datasets,
        data_summary="50 Drehmoment-Werte, 48 Position-Werte",
    )

    result = await run_stats_agent(state)

    print(f"\n📈 Statistics Summary: {result.get('statistics_summary', 'N/A')}")

    if result.get("statistics"):
        print(f"📊 Statistics: {json.dumps(result['statistics'], indent=2)}")


if __name__ == "__main__":
    asyncio.run(test_stats_agent())
