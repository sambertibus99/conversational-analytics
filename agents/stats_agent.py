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

VERFÜGBARE TOOLS (9):
- mean_tool: Durchschnitt
- std_tool: Standardabweichung
- min_max_tool: Minimum/Maximum
- correlation_tool: Korrelation zwischen zwei Keys (DEC-024)
- trend_tool: Linearer Trend
- percentiles_tool: Perzentile/Quartile
- anomaly_tool: Ausreißererkennung
- activity_tool: Aktivitätszeiträume erkennen
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
    get_dataset_meta_from_duckdb,
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
    detect_activity_windows,
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

def _resolve_existing_stats(session_id: str, signal_keys: list[str]) -> list[str]:
    """
    Prüft welche Stats-Ergebnisse bereits in DuckDB vorliegen.
    Analog zu check_dataset im Data Agent — aber deterministisch (kein LLM nötig).

    Args:
        session_id: DuckDB Session-ID
        signal_keys: Verfügbare Signal-Keys aus Telemetrie-Daten

    Returns:
        Liste der gefundenen stats_dataset_keys, oder leere Liste.
    """
    from config.duckdb_store import SessionStore

    if session_id not in SessionStore._instances:
        return []

    store = SessionStore.get_instance(session_id)
    existing = store.list_statistics()  # [{"dataset_key": ..., "analysis_type": ...}]

    if not existing:
        return []

    # Alle Stats-Keys zurückgeben (sie gehören zur Session, also sind sie relevant)
    return [entry["dataset_key"] for entry in existing]


def get_available_keys(state: dict) -> list[str]:
    """Extrahiert verfügbare Keys aus dem State (DEC-025: DuckDB-first)."""
    return get_available_signal_keys(state)


def format_result(result: dict, tool_name: str) -> str:
    """Formatiert ein Ergebnis als lesbaren String."""
    if "error" in result:
        return f"Fehler: {result['error']}"

    return json.dumps(result, indent=2, ensure_ascii=False)


def _filter_state_by_dataset_keys(state: dict, dataset_keys: list[str] | None) -> dict:
    """Filtert active_dataset_keys auf die angegebenen Keys.

    Wenn dataset_keys gesetzt ist, wird der State so gefiltert dass nur
    diese Keys für die DuckDB-Abfrage genutzt werden.
    """
    if not dataset_keys:
        return state
    return {**state, "active_dataset_keys": dataset_keys}


# =============================================================================
# STATS TOOLS MIT INJECTEDSTATE (DEC-003)
# =============================================================================

@tool
def mean_tool(
    key: str,
    dataset_keys: list[str] | None = None,
    state: Annotated[dict, InjectedState] = None,
) -> str:
    """
    Berechnet den Durchschnitt für einen Telemetrie-Key.

    WANN BENUTZEN:
    - "Durchschnitt", "Mittelwert", "average", "im Schnitt"
    - "durchschnittliche Temperatur/Drehmoment"

    Args:
        key: Der Telemetrie-Key, z.B. "torque_act_a1_nm"
        dataset_keys: Optional - Liste von Dataset-Keys um nur bestimmte Zeiträume zu analysieren.
    """
    state = _filter_state_by_dataset_keys(state, dataset_keys)
    logger.debug(f"mean_tool: key={key}, dataset_keys={dataset_keys}")

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
    dataset_keys: list[str] | None = None,
    state: Annotated[dict, InjectedState] = None,
) -> str:
    """
    Berechnet die Standardabweichung (Streuung) für einen Key.

    WANN BENUTZEN:
    - "Streuung", "Standardabweichung", "wie stark schwanken"
    - "Stabilität" der Messwerte

    Args:
        key: Der Telemetrie-Key
        dataset_keys: Optional - Liste von Dataset-Keys um nur bestimmte Zeiträume zu analysieren.
    """
    state = _filter_state_by_dataset_keys(state, dataset_keys)
    logger.debug(f"std_tool: key={key}, dataset_keys={dataset_keys}")

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
    dataset_keys: list[str] | None = None,
    state: Annotated[dict, InjectedState] = None,
) -> str:
    """
    Gibt Minimum, Maximum und Spannweite für einen Key.

    WANN BENUTZEN:
    - "Minimum", "Maximum", "höchster/niedrigster Wert"
    - "Bereich", "Spanne", "Extremwerte"

    Args:
        key: Der Telemetrie-Key
        dataset_keys: Optional - Liste von Dataset-Keys um nur bestimmte Zeiträume zu analysieren.
    """
    state = _filter_state_by_dataset_keys(state, dataset_keys)
    logger.debug(f"min_max_tool: key={key}, dataset_keys={dataset_keys}")

    available = get_available_signal_keys(state)
    if key not in available:
        return f"Key '{key}' nicht gefunden. Verfügbar: {available[:5]}"

    timestamps, values = get_timeseries_for_key(state, key)
    if not values:
        return f"Keine gültigen Werte für Key '{key}'"

    result = calculate_min_max(values, timestamps if timestamps else None)
    result["key"] = key
    return format_result(result, "min_max")


@tool
def correlation_tool(
    key_x: str,
    key_y: str,
    dataset_keys: list[str] | None = None,
    state: Annotated[dict, InjectedState] = None,
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
        dataset_keys: Optional - Liste von Dataset-Keys um nur bestimmte Zeiträume zu analysieren.
    """
    state = _filter_state_by_dataset_keys(state, dataset_keys)
    logger.debug(f"correlation_tool: key_x={key_x}, key_y={key_y}, dataset_keys={dataset_keys}")

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
    )

    result["key_x"] = key_x
    result["key_y"] = key_y

    logger.info(f"Korrelation {key_x} ↔ {key_y}: r={result.get('r')}, n_matched={result.get('n_matched')}")

    return format_result(result, "correlation")


@tool
def trend_tool(
    key: str,
    dataset_keys: list[str] | None = None,
    state: Annotated[dict, InjectedState] = None,
) -> str:
    """
    Berechnet den linearen Trend für einen Key.

    WANN BENUTZEN:
    - "Trend", "Tendenz", "Entwicklung"
    - "steigend/fallend/stabil?"

    Args:
        key: Der Telemetrie-Key
        dataset_keys: Optional - Liste von Dataset-Keys um nur bestimmte Zeiträume zu analysieren.
    """
    state = _filter_state_by_dataset_keys(state, dataset_keys)
    logger.debug(f"trend_tool: key={key}, dataset_keys={dataset_keys}")

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
    dataset_keys: list[str] | None = None,
    state: Annotated[dict, InjectedState] = None,
) -> str:
    """
    Berechnet Perzentile (Quartile: 25%, 50%, 75%) für einen Key.

    WANN BENUTZEN:
    - "Perzentil", "Median", "Quartil"
    - "Verteilung der Werte"

    Args:
        key: Der Telemetrie-Key
        dataset_keys: Optional - Liste von Dataset-Keys um nur bestimmte Zeiträume zu analysieren.
    """
    state = _filter_state_by_dataset_keys(state, dataset_keys)
    logger.debug(f"percentiles_tool: key={key}, dataset_keys={dataset_keys}")

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
    dataset_keys: list[str] | None = None,
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
        dataset_keys: Optional - Liste von Dataset-Keys um nur bestimmte Zeiträume zu analysieren.
    """
    state = _filter_state_by_dataset_keys(state, dataset_keys)
    logger.debug(f"anomaly_tool: key={key}, sigma={sigma_threshold}, dataset_keys={dataset_keys}")

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
def activity_tool(
    key: str,
    threshold: float = 5.0,
    min_duration_s: float = 10.0,
    dataset_keys: list[str] | None = None,
    state: Annotated[dict, InjectedState] = None,
) -> str:
    """
    Erkennt Aktivitaetszeitraeume — wann Werte ueber einem Schwellwert liegen.

    WANN BENUTZEN:
    - "wann war aktiv", "Betriebszeiten", "wann lief der Roboter"
    - "in welchen Zeitraeumen war die Belastung hoch"

    Args:
        key: Der Telemetrie-Key, z.B. "utilization_current"
        threshold: Ab welchem Wert gilt als "aktiv" (default: 5.0)
        min_duration_s: Minimale Fensterdauer in Sekunden (default: 10.0)
        dataset_keys: Optional - Liste von Dataset-Keys fuer bestimmte Zeitraeume
    """
    state = _filter_state_by_dataset_keys(state, dataset_keys)
    logger.debug(f"activity_tool: key={key}, threshold={threshold}, min_duration_s={min_duration_s}, dataset_keys={dataset_keys}")

    available = get_available_signal_keys(state)
    if key not in available:
        return f"Key '{key}' nicht gefunden. Verfügbar: {available[:5]}"

    timestamps, values = get_timeseries_for_key(state, key)
    if not values:
        return f"Keine gültigen Werte für Key '{key}'"

    result = detect_activity_windows(timestamps, values, threshold, int(min_duration_s * 1000))
    result["key"] = key
    return format_result(result, "activity")


@tool
def summary_tool(
    key: str,
    dataset_keys: list[str] | None = None,
    state: Annotated[dict, InjectedState] = None,
) -> str:
    """
    Gibt eine komplette Statistik-Übersicht für einen Key.

    Berechnet: Durchschnitt, Std, Min, Max, Median, Trend

    WANN BENUTZEN:
    - "Statistik-Übersicht", "alle Kennzahlen"
    - "Zusammenfassung der Daten"

    Args:
        key: Der Telemetrie-Key
        dataset_keys: Optional - Liste von Dataset-Keys um nur bestimmte Zeiträume zu analysieren.
    """
    state = _filter_state_by_dataset_keys(state, dataset_keys)
    logger.debug(f"summary_tool: key={key}, dataset_keys={dataset_keys}")

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
# STATS FINDINGS FÜR CROSS-TURN-REFERENZEN (DEC-034)
# =============================================================================

def _build_stats_findings(
    results: list[dict],
    active_dataset_keys: list[str] | None,
    session_id: str,
) -> list[dict]:
    """Baut strukturierte Erkenntnisse aus Stats-Ergebnissen für den Supervisor.

    Jedes Finding enthält:
    - type: Art der Erkenntnis (max, min, correlation, trend, anomaly, mean, std, percentiles)
    - key: Signal-Key(s) auf den sich die Erkenntnis bezieht
    - value: Hauptwert
    - timestamp: Zeitpunkt (optional, wenn verfügbar)
    - dataset_keys: Welche Datensatz-Keys analysiert wurden
    - timerange: Zeitraum des Datensatzes (human-readable)
    - Extra-Felder je nach Typ (interpretation, slope, etc.)
    """
    findings = []

    # Datensatz-Kontext aus DuckDB holen
    ds_context = ""
    if active_dataset_keys:
        try:
            metas = get_dataset_meta_from_duckdb(session_id, active_dataset_keys) or {}
            timeranges = set()
            for dk, meta in metas.items():
                if isinstance(meta, dict):
                    tr = meta.get("timerange", {})
                    start = tr.get("start_human") or tr.get("start", "")
                    end = tr.get("end_human") or tr.get("end", "")
                    if start and end:
                        timeranges.add(f"{start} - {end}")
            ds_context = ", ".join(timeranges) if timeranges else ""
        except Exception as e:
            logger.warning(f"DuckDB-Fehler beim Laden von Timeranges: {e}")

    for r in results:
        result_str = r["result"]
        try:
            parsed = json.loads(result_str)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(parsed, dict) or "error" in parsed:
            continue

        key = parsed.get("key", "?")
        base = {"dataset_keys": active_dataset_keys or [], "timerange": ds_context}

        # percentiles_tool: Vor min_max prüfen (Perzentile haben auch min/max!)
        if "p25" in parsed or "p50" in parsed or "p75" in parsed:
            findings.append({**base, "type": "percentiles", "key": key,
                             "value": {"p25": parsed.get("p25"), "p50": parsed.get("p50"),
                                       "p75": parsed.get("p75")},
                             "count": parsed.get("count")})

        # min_max_tool: min UND max als separate Findings
        elif "min" in parsed and "max" in parsed and "mean" not in parsed:
            findings.append({**base, "type": "max", "key": key,
                             "value": parsed["max"],
                             "timestamp": parsed.get("max_timestamp_human")})
            findings.append({**base, "type": "min", "key": key,
                             "value": parsed["min"],
                             "timestamp": parsed.get("min_timestamp_human")})

        # correlation_tool
        elif "r" in parsed and parsed["r"] is not None:
            findings.append({**base, "type": "correlation",
                             "key": f"{parsed.get('key_x', '?')} / {parsed.get('key_y', '?')}",
                             "value": round(parsed["r"], 4),
                             "interpretation": parsed.get("interpretation")})

        # trend_tool
        elif "slope" in parsed:
            findings.append({**base, "type": "trend", "key": key,
                             "value": parsed.get("trend"),
                             "slope": round(parsed.get("slope", 0), 4)})

        # anomaly_tool
        elif "anomalies_count" in parsed:
            findings.append({**base, "type": "anomaly", "key": key,
                             "value": parsed["anomalies_count"],
                             "percentage": parsed.get("anomaly_percentage")})

        # activity_tool
        elif "windows" in parsed and "window_count" in parsed:
            windows_summary = [
                {"start": w.get("start_human", "?"), "end": w.get("end_human", "?"),
                 "duration_s": w.get("duration_s", 0)}
                for w in parsed.get("windows", [])
            ]
            findings.append({**base, "type": "activity", "key": key,
                             "value": parsed["window_count"],
                             "active_ratio": parsed.get("active_ratio"),
                             "windows": windows_summary})

        # mean_tool
        elif "mean" in parsed and "min" not in parsed and "slope" not in parsed:
            findings.append({**base, "type": "mean", "key": key,
                             "value": round(parsed["mean"], 4)})

        # std_tool
        elif "std" in parsed and "mean" not in parsed:
            findings.append({**base, "type": "std", "key": key,
                             "value": round(parsed["std"], 4)})

        # percentiles_tool
        elif "p50" in parsed:
            findings.append({**base, "type": "percentiles", "key": key,
                             "p25": parsed.get("p25"), "p50": parsed.get("p50"),
                             "p75": parsed.get("p75")})

        # summary_tool (hat mean + min + max)
        elif "mean" in parsed and "min" in parsed:
            findings.append({**base, "type": "summary", "key": key,
                             "mean": round(parsed["mean"], 4),
                             "min": parsed["min"], "max": parsed["max"]})

    return findings[:15]  # Token-Budget


def _extract_agent_signals(results: list[dict]) -> list[dict]:
    """Extrahiert strukturierte Signale aus Stats-Tool-Ergebnissen."""
    signals = []
    for r in results:
        try:
            parsed = json.loads(r["result"])
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(parsed, dict) or "error" not in parsed:
            continue

        error_msg = parsed["error"]
        tool_name = r["tool"]

        if "überlappende Datenpunkte" in error_msg:
            signals.append({
                "agent": "stats_agent",
                "type": "error",
                "code": "insufficient_overlap",
                "message": (
                    f"Korrelation {parsed.get('key_x', '?')} ↔ {parsed.get('key_y', '?')} "
                    f"fehlgeschlagen: {error_msg}. "
                    f"n_x={parsed.get('n_x', '?')}, n_y={parsed.get('n_y', '?')}"
                ),
                "suggestion": (
                    "Beide Signale im gleichen Zeitraum mit gleicher Granularitaet laden. "
                    "Moegl. Ursache: Ein Signal wurde automatisch aggregiert (raw_downgraded)."
                ),
            })
        elif "nicht gefunden" in error_msg:
            signals.append({
                "agent": "stats_agent",
                "type": "error",
                "code": "key_not_found",
                "message": f"{tool_name}: {error_msg}",
                "suggestion": "Pruefen ob der richtige Dataset-Key geladen wurde",
            })
        else:
            signals.append({
                "agent": "stats_agent",
                "type": "error",
                "code": "stats_tool_error",
                "message": f"{tool_name}: {error_msg}",
                "suggestion": "",
            })
    return signals


# =============================================================================
# DUCKDB PERSISTIERUNG (DEC-030)
# =============================================================================

def _extract_time_range_from_state(state: dict) -> str:
    """Extrahiert den Zeitraum aus den aktiven Datasets im State."""
    # DuckDB-first (DEC-031)
    session_id = state.get("session_id", "default")
    active_keys = state.get("active_dataset_keys", [])
    datasets = get_dataset_meta_from_duckdb(session_id, active_keys)

    for dk in (active_keys or []):
        ds = datasets.get(dk)
        if isinstance(ds, dict):
            tr = ds.get("timerange", {})
            start = tr.get("start_human") or tr.get("start", "")
            end = tr.get("end_human") or tr.get("end", "")
            if start and end:
                # Format: "2026-02-11_15-55_17-55" (kompakt für Keys)
                s = str(start).replace(" ", "_").replace(":", "-")
                e = str(end).replace(" ", "_").replace(":", "-")
                return f"{s}_{e}"

    return ""


def _determine_analysis_type(tool_name: str) -> str:
    """Mappt Tool-Name auf analysis_type für DuckDB-Key."""
    mapping = {
        "mean_tool": "mean",
        "std_tool": "std",
        "min_max_tool": "min_max",
        "correlation_tool": "correlation",
        "trend_tool": "trend",
        "percentiles_tool": "percentiles",
        "anomaly_tool": "anomaly",
        "activity_tool": "activity",
        "summary_tool": "summary",
    }
    return mapping.get(tool_name, tool_name.replace("_tool", ""))


def _stats_to_chart_data(analysis_type: str, parsed_result: dict) -> dict[str, list[dict]]:
    """
    Konvertiert Stats-Ergebnisse in ThingsBoard-Format für DuckDB (DEC-030).

    Korrelation: {"axis_act_a1_deg": [{"value": "-0.664", "timestamp": 0}], ...}
    Mean:        {"torque_act_a1_nm": [{"value": "25.3", "timestamp": 0}]}
    """
    if analysis_type == "correlation" and "r" in parsed_result:
        key_y = parsed_result.get("key_y", "correlation")
        return {key_y: [{"value": str(parsed_result["r"]), "timestamp": 0}]}

    key = parsed_result.get("key", "value")

    if "mean" in parsed_result:
        return {key: [{"value": str(parsed_result["mean"]), "timestamp": 0}]}
    if "std" in parsed_result:
        return {key: [{"value": str(parsed_result["std"]), "timestamp": 0}]}
    if "p25" in parsed_result or "p50" in parsed_result:
        return {
            f"{key}_p25": [{"value": str(parsed_result.get("p25", 0)), "timestamp": 0}],
            f"{key}_p50": [{"value": str(parsed_result.get("p50", 0)), "timestamp": 0}],
            f"{key}_p75": [{"value": str(parsed_result.get("p75", 0)), "timestamp": 0}],
        }
    if "min" in parsed_result and "max" in parsed_result:
        return {
            f"{key}_min": [{"value": str(parsed_result["min"]), "timestamp": 0}],
            f"{key}_max": [{"value": str(parsed_result["max"]), "timestamp": 0}],
        }
    if "slope" in parsed_result:
        return {key: [{"value": str(parsed_result["slope"]), "timestamp": 0}]}
    if "window_count" in parsed_result:
        return {key: [{"value": str(parsed_result["window_count"]), "timestamp": 0}]}

    return {}


def _store_stats_in_duckdb(
    state: dict,
    results: list[dict],
    statistics: dict[str, Any],
) -> tuple[None, list[str]]:
    """
    Speichert Stats-Ergebnisse in DuckDB (DEC-030).

    Persistenz läuft NUR über DuckDB statistics-Tabelle + turn_history.
    Keine DatasetMeta in state.datasets (bleibt nur für Telemetrie).

    Returns:
        Tuple (None, active_stats_keys):
        - None (kein datasets_dict mehr)
        - active_stats_keys: Liste der erzeugten Stats-Keys
    """
    from config.duckdb_store import SessionStore, generate_stats_dataset_key

    session_id = state.get("session_id", "default")
    global_time_range = _extract_time_range_from_state(state)
    active_keys: list[str] = []

    try:
        store = SessionStore.get_instance(session_id)
    except Exception as e:
        logger.warning(f"DuckDB nicht verfügbar für Stats-Speicherung: {e}")
        return None, []

    for r in results:
        tool_name = r["tool"]
        result_str = r["result"]
        call_dataset_keys = r.get("dataset_keys")

        try:
            parsed = json.loads(result_str)
        except json.JSONDecodeError:
            continue

        if "error" in parsed:
            continue

        analysis_type = _determine_analysis_type(tool_name)

        # Reference-Key bestimmen
        if analysis_type == "correlation":
            key_x = parsed.get("key_x", "x")
            key_y = parsed.get("key_y", "y")
            reference_key = f"{key_x}-{key_y}"
        else:
            reference_key = parsed.get("key", "unknown")

        # Per-Result Zeitraum wenn dataset_keys im Tool-Call gesetzt
        if call_dataset_keys:
            # Zeitraum aus dem ersten dataset_key extrahieren (letztes Segment)
            first_key = call_dataset_keys[0]
            result_time_range = first_key.split("/")[-1] if "/" in first_key else global_time_range
        else:
            result_time_range = global_time_range

        dataset_key = generate_stats_dataset_key(
            device_id="krc5",
            analysis_type=analysis_type,
            reference_key=reference_key,
            time_range=result_time_range,
        )

        # In DuckDB speichern
        metadata = {
            "source_dataset_keys": call_dataset_keys or state.get("active_dataset_keys", []),
            "time_range": result_time_range,
        }
        store.store_statistics(dataset_key, analysis_type, parsed, metadata)
        active_keys.append(dataset_key)
        logger.debug(f"Stats in DuckDB: {dataset_key}")

    return None, active_keys


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
    activity_tool,
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

def _parse_timerange_from_dataset_key(dataset_key: str) -> str:
    """Extrahiert einen lesbaren Zeitraum aus einem Dataset-Key.

    z.B. 'krc5/utilization_current/timeseries/detail/2026-02-12_15-00_16-00'
    → '12.02. 15:00-16:00'

    z.B. 'krc5/torque_act_a1_nm/timeseries/detail/2026-02-10_00-00_2026-02-17_23-59'
    → '10.02.-17.02.'
    """
    parts = dataset_key.split("/")
    if len(parts) < 5:
        return dataset_key
    time_part = parts[-1]  # z.B. "2026-02-12_15-00_16-00" oder "2026-02-10_00-00_2026-02-17_23-59"
    segments = time_part.split("_")
    try:
        if len(segments) == 3:
            # Gleicher Tag: YYYY-MM-DD_HH-MM_HH-MM
            date = segments[0]  # 2026-02-12
            day_month = f"{date[8:10]}.{date[5:7]}."
            start_t = segments[1].replace("-", ":")
            end_t = segments[2].replace("-", ":")
            return f"{day_month} {start_t}-{end_t}"
        elif len(segments) >= 4:
            # Verschiedene Tage: YYYY-MM-DD_HH-MM_YYYY-MM-DD_HH-MM
            date1 = segments[0]
            date2 = segments[2]
            d1 = f"{date1[8:10]}.{date1[5:7]}."
            d2 = f"{date2[8:10]}.{date2[5:7]}."
            return f"{d1}-{d2}"
    except (IndexError, ValueError):
        pass
    return time_part


def prepare_stats_context(state: AgentState) -> str:
    """
    Bereitet den Daten-Kontext für den Stats Agent vor.

    WICHTIG: Nur Metadaten, KEINE Werte! (DEC-003/DEC-004)
    Das LLM soll nur wissen welche Keys verfügbar sind.

    Zeigt Datasets gruppiert nach Zeitraum, damit der Stats Agent
    erkennen kann welche Daten zu welchem Zeitfenster gehören.
    """
    active_keys = state.get("active_dataset_keys") or []

    if not active_keys:
        return "Keine Daten geladen."

    # Datasets nach Zeitraum gruppieren
    from collections import defaultdict
    timerange_groups: dict[str, list[tuple[str, str]]] = defaultdict(list)

    for dk in active_keys:
        parts = dk.split("/")
        if len(parts) >= 5:
            signal_key = parts[1]  # z.B. "utilization_current"
            timerange = _parse_timerange_from_dataset_key(dk)
        else:
            signal_key = dk
            timerange = "unbekannt"
        timerange_groups[timerange].append((signal_key, dk))

    # Punktzahlen pro Signal aus DuckDB holen
    session_id = state.get("session_id", "default")
    try:
        from config.duckdb_store import SessionStore
        store = SessionStore.get_instance(session_id)
    except Exception:
        store = None

    context_parts = ["\n## VERFÜGBARE DATEN"]

    for timerange, signals in timerange_groups.items():
        context_parts.append(f"\n### Zeitraum: {timerange}")
        for signal_key, dataset_key in signals:
            count = ""
            if store:
                rows = store.query(
                    "SELECT COUNT(*) FROM telemetry WHERE dataset_key = ?",
                    [dataset_key],
                )
                if rows:
                    count = f" ({rows[0][0]} Werte)"
            context_parts.append(f"- {dataset_key}{count}")

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

    # Stats Instructions vom Supervisor injizieren (analog zu data_instructions im Data Agent)
    stats_instructions = tool_state.get("stats_instructions")
    if stats_instructions:
        system_content += "\n\n<supervisor_instructions>\n" + stats_instructions + "\n</supervisor_instructions>"

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

        # dataset_keys aus Tool-Args merken (für DuckDB-Persistierung)
        call_dataset_keys = tool_args.get("dataset_keys")

        # State manuell injizieren (wie Viz Agent)
        tool_args["state"] = tool_state

        if tool_name in tool_map:
            result = tool_map[tool_name].invoke(tool_args)
            results.append({"tool": tool_name, "result": result, "dataset_keys": call_dataset_keys})
            _debug_log(f"\n  Tool-Ergebnis ({tool_name}): {str(result)[:500]}")
        else:
            results.append({"tool": tool_name, "result": f"Unbekanntes Tool: {tool_name}"})

    return results, response.content if hasattr(response, 'content') else ""


# =============================================================================
# HAUPTFUNKTION
# =============================================================================


def _extract_time_prefix(dataset_keys: list[str] | None) -> str:
    """Extrahiert einen lesbaren Zeitraum aus dataset_keys für Summaries.

    Beispiel: ['krc5/utilization_current/timeseries/detail/2026-02-11_16-30_16-40']
    → '11.02. 16:30-16:40'
    """
    if not dataset_keys:
        return ""
    # Nimm den ersten Key — alle Keys eines Tool-Calls haben denselben Zeitraum
    key = dataset_keys[0]
    parts = key.split("/")
    if len(parts) < 5:
        return ""
    time_part = parts[-1]  # z.B. "2026-02-11_16-30_16-40"
    segments = time_part.split("_")
    if len(segments) < 3:
        return ""
    # Date: "2026-02-11" → "11.02."
    date_parts = segments[0].split("-")
    if len(date_parts) == 3:
        date_str = f"{date_parts[2]}.{date_parts[1]}."
    else:
        date_str = segments[0]
    # Times: "16-30" → "16:30", "16-40" → "16:40"
    start_time = segments[1].replace("-", ":")
    end_time = segments[2].replace("-", ":")
    return f"{date_str} {start_time}-{end_time}"


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

        session_id = state.get("session_id", "default")

        # GATEKEEPER: Wenn active_dataset_keys is None → kein Data Agent lief → Resolve-Modus
        # active_stats_keys bleibt über Turns erhalten (nicht mehr resettet in _get_per_turn_reset).
        # Wenn Stats Agent nicht im Plan ist, bleiben die Keys vom letzten Turn.
        # Wenn Stats Agent IM Plan ist aber kein Data Agent lief → vorhandene Stats beibehalten.
        if state.get("active_dataset_keys") is None:
            # active_stats_keys schon vom vorherigen Turn gesetzt?
            existing_stats = state.get("active_stats_keys")
            if existing_stats:
                logger.info(f"Stats Gatekeeper: {len(existing_stats)} Stats aus vorherigem Turn übernommen")
                return {
                    "messages": [AIMessage(content="Statistiken aus vorheriger Berechnung übernommen.")],
                    "active_stats_keys": existing_stats,
                }
            # Fallback: DuckDB durchsuchen
            resolved = _resolve_existing_stats(session_id, [])
            if resolved:
                logger.info(f"Stats Gatekeeper: {len(resolved)} Stats aus DuckDB aufgelöst")
                return {
                    "messages": [AIMessage(content="Statistiken aus vorheriger Berechnung übernommen.")],
                    "active_stats_keys": resolved,
                }
            else:
                logger.warning("Stats Gatekeeper: Keine bestehenden Stats in DuckDB gefunden")
                return {
                    "messages": [AIMessage(content="Keine Statistik-Ergebnisse vorhanden. Bitte erst eine Analyse durchführen.")],
                    "error": "no_stats",
                }

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
            # Zeitraum-Prefix aus dataset_keys extrahieren (z.B. "11.02. 16:30-16:40")
            time_prefix = _extract_time_prefix(r.get("dataset_keys"))

            try:
                parsed = json.loads(result_str)
                statistics[tool_name] = parsed

                # Summary generieren (Reihenfolge wichtig: spezifische Keys vor generischen!)
                if "error" in parsed:
                    summaries.append(f"{tool_name}: {parsed['error']}")
                elif "windows" in parsed and "window_count" in parsed:
                    total = parsed.get("total_active_s", 0)
                    h, m = divmod(int(total), 3600)
                    m = m // 60
                    ratio_pct = (parsed.get("active_ratio", 0) * 100)
                    # Konkrete Zeitfenster auflisten damit Supervisor sie im Replan nutzen kann
                    window_parts = []
                    for w in parsed.get("windows", []):
                        start = w.get("start_human", "?")
                        end = w.get("end_human", "?")
                        dur = w.get("duration_s", 0)
                        dur_m = int(dur) // 60
                        window_parts.append(f"{start}-{end} ({dur_m}min)")
                    windows_str = "; ".join(window_parts) if window_parts else "keine"
                    summaries.append(
                        f"{parsed.get('key', '?')}: {parsed['window_count']} Aktivitaetsfenster, "
                        f"{h}h {m}min aktiv ({ratio_pct:.1f}%): {windows_str}"
                    )
                elif "anomalies_count" in parsed:
                    summaries.append(f"{parsed.get('key', '?')}: {parsed['anomalies_count']} Anomalien ({parsed.get('anomaly_percentage', '?')}%)")
                elif "r" in parsed:
                    key_info = f"{parsed.get('key_x', '?')} ↔ {parsed.get('key_y', '?')}"
                    tp = f" ({time_prefix})" if time_prefix else ""
                    summaries.append(f"Korrelation{tp} {key_info}: r={parsed['r']:.3f} ({parsed.get('interpretation', '')})")
                elif "p25" in parsed or "p50" in parsed or "p75" in parsed:
                    # percentiles_tool: Vor min_max prüfen (Perzentile haben auch min/max!)
                    key = parsed.get("key", "?")
                    tp = f" ({time_prefix})" if time_prefix else ""
                    parts = [f"{key}{tp}: P25={parsed.get('p25', '?')}, P50={parsed.get('p50', '?')}, P75={parsed.get('p75', '?')}"]
                    if parsed.get("count"):
                        parts.append(f" (n={parsed['count']})")
                    summaries.append("".join(parts))
                elif "min" in parsed and "max" in parsed and "mean" not in parsed:
                    # min_max_tool: Mit formatierten Timestamps wenn vorhanden
                    tp = f" ({time_prefix})" if time_prefix else ""
                    parts = [f"{parsed.get('key', '?')}{tp}: Min={parsed['min']:.4f}"]
                    if parsed.get("min_timestamp_human"):
                        parts.append(f"am {parsed['min_timestamp_human']}")
                    parts.append(f", Max={parsed['max']:.4f}")
                    if parsed.get("max_timestamp_human"):
                        parts.append(f"am {parsed['max_timestamp_human']}")
                    summaries.append("".join(parts))
                elif "slope" in parsed:
                    summaries.append(f"{parsed.get('key', '?')}: {parsed.get('trend', '')} (slope={parsed['slope']:.4f})")
                elif "mean" in parsed:
                    summaries.append(f"{parsed.get('key', '?')}: Durchschnitt = {parsed['mean']:.4f}")
            except json.JSONDecodeError:
                summaries.append(result_str)

        stats_summary = "; ".join(summaries)
        logger.info(f"Stats berechnet: {stats_summary[:100]}")

        # DEC-034: Strukturierte Findings für Cross-Turn-Referenzen
        stats_findings = _build_stats_findings(
            results, state.get("active_dataset_keys"), session_id
        )
        if stats_findings:
            logger.info(f"DEC-034: {len(stats_findings)} Findings erstellt")

        # Agent Signals extrahieren und mit vorherigen mergen (read-append)
        new_signals = _extract_agent_signals(results)
        existing_signals = list(state.get("agent_signals") or [])
        all_signals = existing_signals + new_signals if new_signals else existing_signals

        # DEC-030: Ergebnisse in DuckDB persistieren (nur DuckDB + active_stats_keys, nicht in datasets)
        _, active_stats_keys = _store_stats_in_duckdb(
            state, results, statistics
        )
        if active_stats_keys:
            logger.info(f"DEC-030: {len(active_stats_keys)} Stats-Datasets in DuckDB gespeichert")

        # Antwort generieren
        response_text = f"Statistische Analyse:\n\n{stats_summary}"

        result_state = {
            "messages": [AIMessage(content=response_text)],
            "statistics": statistics,
            "statistics_summary": stats_summary,
            "stats_findings": stats_findings,  # DEC-034
        }

        # Agent Signals (vorherige + neue) in State schreiben
        if all_signals:
            result_state["agent_signals"] = all_signals

        # DEC-030: active_stats_keys für Viz-Zugriff im Folge-Turn
        # Persistenz läuft über turn_history (stats_dataset_keys) + DuckDB statistics-Tabelle.
        # datasets bleibt nur für Telemetrie — Stats-DatasetMeta nicht in datasets.
        if active_stats_keys:
            result_state["active_stats_keys"] = active_stats_keys

        return result_state

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

    # DEC-031: Testdaten in DuckDB speichern statt in State
    from config.duckdb_store import SessionStore
    session_id = "test_stats_agent"
    store = SessionStore.get_instance(session_id)

    test_data = {
        "torque_a1": [
            {"value": str(25.0 + random.gauss(0, 2)), "timestamp": int((now - timedelta(minutes=50-i)).timestamp() * 1000)}
            for i in range(50)
        ],
        "position_a1": [
            {"value": str(45.0 + random.gauss(0, 3)), "timestamp": int((now - timedelta(minutes=50-i)).timestamp() * 1000 + random.randint(-100, 100))}
            for i in range(48)  # Absichtlich 2 weniger!
        ],
    }
    store.store_dataset(dataset_key="test/correlation", data=test_data)

    print(f"📊 Test-Daten: torque_a1 (50 Punkte), position_a1 (48 Punkte)")

    state = AgentState(
        messages=[HumanMessage(content="Gibt es eine Korrelation zwischen torque_a1 und position_a1?")],
        session_id=session_id,
        active_dataset_keys=["test/correlation"],
    )

    result = await run_stats_agent(state)

    print(f"\n📈 Statistics Summary: {result.get('statistics_summary', 'N/A')}")

    if result.get("statistics"):
        print(f"📊 Statistics: {json.dumps(result['statistics'], indent=2)}")


if __name__ == "__main__":
    asyncio.run(test_stats_agent())
