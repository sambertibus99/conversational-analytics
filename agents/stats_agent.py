"""
Stats Agent für statistische Analysen von IIoT-Daten.

Nutzt den Stats MCP Server für Berechnungen wie:
- Deskriptive Statistik (mean, std, min_max, percentiles)
- Korrelationsanalyse
- Trendanalyse
- Anomalieerkennung

WICHTIG: Der Stats Agent arbeitet mit Daten aus dem State (vom Data Agent).
Er ruft KEINE neuen Daten ab!

FALLBACK: Wenn MCP Server nicht erreichbar, werden die Stats direkt berechnet.
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

from agents.state import AgentState
from prompts.stats_agent_prompt import STATS_AGENT_SYSTEM_PROMPT
from config.settings import ANTHROPIC_API_KEY, DEFAULT_MODEL, PROJECT_ROOT as CONFIG_PROJECT_ROOT

# Direkte Stats-Funktionen als Fallback
from tools.stats_functions import (
    calculate_mean,
    calculate_std,
    calculate_min_max,
    calculate_correlation,
    calculate_linear_trend,
    calculate_moving_average,
    calculate_percentiles,
    detect_anomalies,
)


# Pfad zum Stats MCP Server
STATS_MCP_SERVER_PATH = PROJECT_ROOT / "mcp_servers" / "stats_server.py"

# Debug-Modus
DEBUG = False

# Timeout für MCP-Operationen (Sekunden)
MCP_TIMEOUT = 30


def debug_print(msg: str):
    """Gibt Debug-Nachrichten aus wenn DEBUG=True."""
    if DEBUG:
        print(f"🔍 STATS DEBUG: {msg}")


@asynccontextmanager
async def stats_mcp_client_context():
    """Async Context Manager für Stats MCP Client mit Timeout."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from langchain_mcp_adapters.tools import load_mcp_tools
    
    server_params = StdioServerParameters(
        command="python",
        args=[str(STATS_MCP_SERVER_PATH)],
        env=None,
    )
    
    debug_print(f"Starte Stats MCP Server: {STATS_MCP_SERVER_PATH}")
    
    try:
        async with stdio_client(server_params) as (read_stream, write_stream):
            debug_print("stdio_client gestartet")
            async with ClientSession(read_stream, write_stream) as session:
                debug_print("ClientSession erstellt")
                await asyncio.wait_for(session.initialize(), timeout=MCP_TIMEOUT)
                debug_print("Session initialisiert")
                tools = await asyncio.wait_for(load_mcp_tools(session), timeout=MCP_TIMEOUT)
                debug_print(f"Tools geladen: {[t.name for t in tools]}")
                yield tools
    except asyncio.TimeoutError:
        debug_print("MCP Client Timeout!")
        raise
    except Exception as e:
        debug_print(f"MCP Client Error: {e}")
        raise


def create_stats_agent(tools: list):
    """Erstellt den Stats Agent mit den gegebenen Tools."""
    debug_print(f"Erstelle Stats Agent mit Model: {DEFAULT_MODEL}")
    
    llm = ChatAnthropic(
        model=DEFAULT_MODEL,
        api_key=ANTHROPIC_API_KEY,
        temperature=0,
    )
    
    agent = create_react_agent(llm, tools)
    return agent


def is_valid_numeric_value(value: Any) -> bool:
    """
    Prüft ob ein Wert gültig numerisch ist (keine Fehlermeldung).
    
    Erkennt fehlerhafte Werte wie:
    - "Bad status code: ..."
    - "Error: ..."
    - "null", "None", "NaN"
    - Leere Strings
    """
    if value is None:
        return False
    
    # Bereits numerisch
    if isinstance(value, (int, float)):
        return True
    
    # String prüfen
    if isinstance(value, str):
        value_lower = value.lower().strip()
        
        # Leerer String
        if not value_lower:
            return False
        
        # Bekannte Fehlermuster
        error_patterns = [
            "bad status",
            "error",
            "unavailable",
            "null",
            "none",
            "nan",
            "invalid",
            "failed",
            "timeout",
            "exception",
            "not found",
            "no data",
        ]
        
        for pattern in error_patterns:
            if pattern in value_lower:
                return False
        
        # Versuche als float zu parsen
        try:
            float(value)
            return True
        except (ValueError, TypeError):
            return False
    
    return False


def extract_values_from_data(data: dict[str, Any], key: str | None = None) -> list[float]:
    """
    Extrahiert numerische Werte aus ThingsBoard-Datenformat.
    
    Input-Formate:
    1. {"key": [{"value": "25.3", "timestamp": 123}, ...]}  (Zeitreihe)
    2. {"key": {"value": "25.3", "timestamp": 123}}  (Latest)
    3. {"key": [25.3, 26.1, ...]}  (Einfache Liste)
    
    WICHTIG: Filtert fehlerhafte Werte wie "Bad status code..." automatisch!
    """
    if not data:
        return []
    
    # Key bestimmen
    if key is None:
        key = next(iter(data.keys()), None)
    
    if key not in data:
        debug_print(f"Key '{key}' nicht in data. Verfügbar: {list(data.keys())}")
        return []
    
    values = []
    skipped = 0
    raw = data[key]
    
    # Format 1: Liste von Dicts mit value/timestamp
    if isinstance(raw, list):
        for point in raw:
            if isinstance(point, dict) and "value" in point:
                val = point["value"]
                if is_valid_numeric_value(val):
                    try:
                        values.append(float(val))
                    except (ValueError, TypeError):
                        skipped += 1
                else:
                    skipped += 1
            elif isinstance(point, (int, float)):
                values.append(float(point))
            elif isinstance(point, str) and is_valid_numeric_value(point):
                try:
                    values.append(float(point))
                except (ValueError, TypeError):
                    skipped += 1
    
    # Format 2: Einzelner Dict (latest)
    elif isinstance(raw, dict) and "value" in raw:
        val = raw["value"]
        if is_valid_numeric_value(val):
            try:
                values.append(float(val))
            except (ValueError, TypeError):
                skipped += 1
        else:
            skipped += 1
    
    if skipped > 0:
        debug_print(f"Key '{key}': {skipped} fehlerhafte Werte übersprungen")
    
    debug_print(f"Extrahiert {len(values)} gültige Werte aus key '{key}'")
    return values


def extract_timestamps_from_data(data: dict[str, Any], key: str | None = None) -> list[int]:
    """Extrahiert Timestamps aus ThingsBoard-Datenformat."""
    if not data:
        return []
    
    if key is None:
        key = next(iter(data.keys()), None)
    
    if key not in data:
        return []
    
    timestamps = []
    raw = data[key]
    
    if isinstance(raw, list):
        for point in raw:
            if isinstance(point, dict) and "timestamp" in point:
                timestamps.append(int(point["timestamp"]))
    
    return timestamps


def prepare_stats_context(state: AgentState) -> str:
    """
    Bereitet den Daten-Kontext für den Stats Agent vor.
    
    Extrahiert die Werte aus state.data und stellt sie dem LLM zur Verfügung.
    """
    context_parts = []
    
    # Original-Query
    for msg in state["messages"]:
        if isinstance(msg, HumanMessage):
            context_parts.append(f"User-Anfrage: {msg.content}")
            break
    
    # Daten-Summary
    if state.get("data_summary"):
        context_parts.append(f"Geladene Daten: {state['data_summary']}")
    
    # Daten-Meta
    if state.get("data_meta"):
        meta = state["data_meta"]
        if meta.get("data_points"):
            context_parts.append(f"Datenpunkte pro Key: {meta['data_points']}")
    
    # Tatsächliche Daten aufbereiten
    if state.get("data"):
        data = state["data"]
        context_parts.append("\n## VERFÜGBARE DATEN")
        
        if isinstance(data, dict):
            for key in list(data.keys())[:5]:  # Max 5 Keys anzeigen
                values = extract_values_from_data(data, key)
                timestamps = extract_timestamps_from_data(data, key)
                
                if values:
                    context_parts.append(f"\n### {key}")
                    context_parts.append(f"- Anzahl Werte: {len(values)}")
                    context_parts.append(f"- Beispielwerte: {values[:5]}...")
                    # Limitiere auf max 100 Werte für den Context
                    context_parts.append(f"- Werte als Liste für Tools: {json.dumps(values[:100])}")
                    
                    if timestamps:
                        context_parts.append(f"- Timestamps vorhanden: Ja ({len(timestamps)} Stück)")
    
    return "\n".join(context_parts)


def extract_statistics_from_messages(messages: list) -> dict[str, Any] | None:
    """Extrahiert Statistik-Ergebnisse aus den Agent-Messages."""
    statistics = {}
    
    for msg in messages:
        if isinstance(msg, ToolMessage):
            content = msg.content
            
            # Content kann String oder Liste sein
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        content = block.get("text", "")
                        break
                    elif isinstance(block, str):
                        content = block
                        break
            
            if isinstance(content, str):
                try:
                    parsed = json.loads(content)
                    if isinstance(parsed, dict):
                        # Tool-Name aus msg.name oder msg.tool_call_id ableiten
                        tool_name = getattr(msg, 'name', 'unknown')
                        statistics[tool_name] = parsed
                except json.JSONDecodeError:
                    pass
    
    return statistics if statistics else None


def generate_statistics_summary(statistics: dict[str, Any] | None) -> str:
    """Generiert eine Zusammenfassung der berechneten Statistiken."""
    if not statistics:
        return "Keine Statistiken berechnet."
    
    summaries = []
    
    for tool_name, result in statistics.items():
        if isinstance(result, dict):
            if "error" in result:
                summaries.append(f"{tool_name}: Fehler - {result['error']}")
            elif "mean" in result:
                summaries.append(f"Durchschnitt: {result['mean']:.4f}")
            elif "r" in result:
                summaries.append(f"Korrelation: r={result['r']:.3f} ({result.get('interpretation', '')})")
            elif "slope" in result:
                summaries.append(f"Trend: {result.get('trend', '')} (slope={result['slope']:.4f})")
            elif "anomalies_count" in result:
                summaries.append(f"Anomalien: {result['anomalies_count']} gefunden")
    
    return "; ".join(summaries) if summaries else "Statistiken berechnet."


# =============================================================================
# FALLBACK: Direkte Stats-Berechnung ohne MCP
# =============================================================================

def compute_stats_directly(state: AgentState, query: str) -> dict[str, Any]:
    """
    Berechnet Statistiken direkt ohne MCP Server.
    
    FALLBACK wenn MCP nicht funktioniert.
    """
    debug_print("Fallback: Direkte Stats-Berechnung")
    
    data = state.get("data", {})
    if not data:
        debug_print("Keine Daten im State!")
        return {
            "statistics": None,
            "statistics_summary": "Keine Daten vorhanden.",
            "error": "no_data",
        }
    
    debug_print(f"Daten-Keys: {list(data.keys())}")
    
    query_lower = query.lower()
    statistics = {}
    summaries = []
    
    # Keywords erweitert (Wortstämme und Varianten)
    mean_keywords = ["durchschnitt", "mittelwert", "average", "mean", "schnitt"]
    sum_keywords = ["verbrauch", "summe", "gesamt", "total", "energie", "energy", "wieviel", "wie viel"]
    std_keywords = ["streuung", "standardabweichung", "std", "varianz", "schwank"]
    minmax_keywords = ["min", "max", "bereich", "spanne", "range", "extrem"]
    anomaly_keywords = ["anomalie", "ausreißer", "spitze", "ungewöhnlich", "auffällig"]
    trend_keywords = ["trend", "entwicklung", "steig", "fall", "verlauf"]
    
    # Prüfe welche Berechnungen gebraucht werden
    needs_mean = any(kw in query_lower for kw in mean_keywords)
    needs_sum = any(kw in query_lower for kw in sum_keywords)
    needs_std = any(kw in query_lower for kw in std_keywords)
    needs_minmax = any(kw in query_lower for kw in minmax_keywords)
    needs_anomaly = any(kw in query_lower for kw in anomaly_keywords)
    needs_trend = any(kw in query_lower for kw in trend_keywords)
    
    debug_print(f"Query-Analyse: mean={needs_mean}, sum={needs_sum}, std={needs_std}")
    
    # Für jeden Key in den Daten
    for key in data.keys():
        values = extract_values_from_data(data, key)
        if not values:
            debug_print(f"Keine Werte für Key: {key}")
            continue
        
        debug_print(f"Key {key}: {len(values)} Werte")
        is_energy_key = "energy" in key.lower() or "energie" in key.lower()
        
        # Summe für Energie IMMER berechnen wenn es um Verbrauch geht
        if needs_sum or is_energy_key:
            total = sum(values)
            statistics[f"sum_{key}"] = {"sum": total, "count": len(values)}
            
            # Einheit bestimmen
            unit = "kWh" if is_energy_key else ""
            summaries.append(f"{key}: Summe = {total:.4f} {unit}".strip())
            debug_print(f"Summe berechnet: {total}")
        
        # Durchschnitt
        if needs_mean or needs_sum:  # Bei Summe auch Mean zeigen
            result = calculate_mean(values)
            if "mean" in result:
                statistics[f"mean_{key}"] = result
                summaries.append(f"{key}: Durchschnitt = {result['mean']:.4f} (n={result['count']})")
        
        # Standardabweichung
        if needs_std:
            result = calculate_std(values)
            if "std" in result and result["std"] is not None:
                statistics[f"std_{key}"] = result
                summaries.append(f"{key}: Std = {result['std']:.4f}")
        
        # Min/Max
        if needs_minmax:
            result = calculate_min_max(values)
            if "min" in result and result["min"] is not None:
                statistics[f"minmax_{key}"] = result
                summaries.append(f"{key}: Min={result['min']:.2f}, Max={result['max']:.2f}")
        
        # Anomalien
        if needs_anomaly:
            result = detect_anomalies(values)
            statistics[f"anomalies_{key}"] = result
            summaries.append(f"{key}: {result['anomalies_count']} Anomalien ({result.get('anomaly_percentage', 0):.1f}%)")
        
        # Trend
        if needs_trend:
            timestamps = extract_timestamps_from_data(data, key)
            result = calculate_linear_trend(values, timestamps if timestamps else None)
            if "slope" in result and result["slope"] is not None:
                statistics[f"trend_{key}"] = result
                summaries.append(f"{key}: {result['trend']} (R²={result['r_squared']:.3f})")
    
    # ULTIMATIVER Fallback: Wenn IMMER NOCH keine Stats, berechne Basis-Stats für alle Keys
    if not statistics:
        debug_print("Kein Keyword-Match - berechne Basis-Stats für alle Keys")
        for key in list(data.keys())[:5]:  # Max 5 Keys
            values = extract_values_from_data(data, key)
            if not values:
                continue
            
            # Immer Mean und Sum berechnen
            mean_result = calculate_mean(values)
            total = sum(values)
            
            statistics[f"mean_{key}"] = mean_result
            statistics[f"sum_{key}"] = {"sum": total, "count": len(values)}
            
            is_energy = "energy" in key.lower()
            unit = " kWh" if is_energy else ""
            
            summaries.append(f"{key}: Summe = {total:.4f}{unit}, Durchschnitt = {mean_result['mean']:.4f}")
    
    debug_print(f"Ergebnis: {len(statistics)} Stats, Summaries: {summaries}")
    
    return {
        "statistics": statistics if statistics else None,
        "statistics_summary": "; ".join(summaries) if summaries else "Keine Statistiken berechnet.",
    }


# =============================================================================
# HAUPTFUNKTIONEN
# =============================================================================

async def run_stats_agent_with_mcp(state: AgentState) -> dict[str, Any]:
    """Führt den Stats Agent mit MCP Server aus."""
    async with stats_mcp_client_context() as tools:
        debug_print("Stats MCP Context aktiv")
        
        agent = create_stats_agent(tools)
        debug_print("Agent erstellt")
        
        # Kontext mit Daten vorbereiten
        data_context = prepare_stats_context(state)
        
        # System Prompt + Daten-Kontext
        system_content = f"{STATS_AGENT_SYSTEM_PROMPT}\n\n## AKTUELLE DATEN\n\n{data_context}"
        
        messages_with_system = [
            SystemMessage(content=system_content),
            *state["messages"]
        ]
        
        debug_print("Starte Agent-Ausführung...")
        result = await asyncio.wait_for(
            agent.ainvoke({"messages": messages_with_system}),
            timeout=60  # 60 Sekunden Timeout für Agent
        )
        debug_print(f"Agent fertig, {len(result.get('messages', []))} Messages")
        
        # Statistiken extrahieren
        statistics = extract_statistics_from_messages(result.get("messages", []))
        debug_print(f"Statistiken extrahiert: {list(statistics.keys()) if statistics else 'keine'}")
        
        # Summary generieren
        stats_summary = generate_statistics_summary(statistics)
        
        return {
            "messages": result.get("messages", []),
            "statistics": statistics,
            "statistics_summary": stats_summary,
        }


async def run_stats_agent(state: AgentState) -> dict[str, Any]:
    """
    Führt den Stats Agent aus.
    
    Versucht zuerst MCP, bei Fehler oder leeren Stats -> Fallback auf direkte Berechnung.
    """
    try:
        debug_print("Starte run_stats_agent")
        
        # Prüfe ob Daten vorhanden
        if not state.get("data"):
            return {
                "messages": [AIMessage(content="Keine Daten für statistische Analyse vorhanden. Bitte erst Daten laden.")],
                "error": "no_data",
            }
        
        # Extrahiere Query für Fallback
        query = ""
        for msg in state["messages"]:
            if isinstance(msg, HumanMessage):
                query = msg.content
                break
        
        debug_print(f"Query: {query}")
        
        mcp_result = None
        mcp_success = False
        
        # Versuche MCP-basierte Ausführung
        try:
            mcp_result = await run_stats_agent_with_mcp(state)
            # Prüfe ob MCP tatsächlich Stats berechnet hat
            if mcp_result.get("statistics"):
                mcp_success = True
                debug_print(f"MCP erfolgreich, Stats: {list(mcp_result['statistics'].keys())}")
            else:
                debug_print("MCP lief, aber keine Statistics berechnet")
        
        except (asyncio.TimeoutError, Exception) as mcp_error:
            debug_print(f"MCP Error: {mcp_error}")
        
        # Wenn MCP erfolgreich -> zurückgeben
        if mcp_success and mcp_result:
            return mcp_result
        
        # FALLBACK: Direkte Berechnung (wenn MCP fehlschlägt ODER keine Stats liefert)
        debug_print("Verwende Fallback: Direkte Berechnung")
        fallback_result = compute_stats_directly(state, query)
        
        # Generiere Response basierend auf Fallback-Ergebnis
        if fallback_result.get("statistics"):
            stats_summary = fallback_result['statistics_summary']
            response_text = f"Statistische Analyse:\n\n{stats_summary}"
            debug_print(f"Fallback erfolgreich: {stats_summary}")
        else:
            response_text = "Konnte keine Statistiken berechnen."
            debug_print("Fallback: Keine Stats berechnet")
        
        return {
            "messages": [AIMessage(content=response_text)],
            "statistics": fallback_result.get("statistics"),
            "statistics_summary": fallback_result.get("statistics_summary"),
        }
    
    except Exception as e:
        error_details = traceback.format_exc()
        if DEBUG:
            print(f"\n❌ FEHLER DETAILS:\n{error_details}")
        
        error_msg = f"Fehler bei der statistischen Analyse: {str(e)}"
        return {
            "messages": [AIMessage(content=error_msg)],
            "error": error_msg,
        }


async def stats_agent_node(state: AgentState) -> dict[str, Any]:
    """LangGraph Node für den Stats Agent."""
    return await run_stats_agent(state)


# =============================================================================
# STANDALONE TESTS
# =============================================================================

async def test_stats_agent():
    """Test des Stats Agents mit simulierten Daten."""
    from datetime import datetime, timedelta
    import random
    
    print("\n" + "="*60)
    print("🧪 Stats Agent Test")
    print("="*60)
    
    # Simulierte Daten (wie vom Data Agent)
    now = datetime.now()
    
    # Normale Werte mit ein paar Ausreißern
    base_values = [25.0 + random.gauss(0, 2) for _ in range(50)]
    base_values[10] = 45.0  # Ausreißer
    base_values[30] = 5.0   # Ausreißer
    
    test_data = {
        "temperature": [
            {"value": str(val), "timestamp": int((now - timedelta(minutes=50-i)).timestamp() * 1000)}
            for i, val in enumerate(base_values)
        ]
    }
    
    print(f"\n📊 Test-Daten: {len(test_data['temperature'])} Punkte")
    print(f"   (inkl. 2 Ausreißer bei Index 10 und 30)")
    
    # Test 1: Durchschnitt
    print("\n--- Test 1: Durchschnitt ---")
    state = AgentState(
        messages=[HumanMessage(content="Was ist die Durchschnittstemperatur?")],
        data=test_data,
        data_summary="50 Temperaturwerte der letzten 50 Minuten",
    )
    
    result = await run_stats_agent(state)
    print(f"📈 Statistics: {result.get('statistics_summary', 'N/A')}")
    
    # Letzte AI-Message
    for msg in reversed(result.get("messages", [])):
        if isinstance(msg, AIMessage) and isinstance(msg.content, str):
            print(f"🤖 Agent: {msg.content[:300]}...")
            break
    
    # Test 2: Anomalien
    print("\n--- Test 2: Anomalieerkennung ---")
    state2 = AgentState(
        messages=[HumanMessage(content="Gibt es ungewöhnliche Temperaturspitzen?")],
        data=test_data,
        data_summary="50 Temperaturwerte der letzten 50 Minuten",
    )
    
    result2 = await run_stats_agent(state2)
    print(f"📈 Statistics: {result2.get('statistics_summary', 'N/A')}")
    
    for msg in reversed(result2.get("messages", [])):
        if isinstance(msg, AIMessage) and isinstance(msg.content, str):
            print(f"🤖 Agent: {msg.content[:300]}...")
            break


async def test_fallback():
    """Test des Fallback-Modus."""
    print("\n" + "="*60)
    print("🧪 Stats Agent Fallback Test")
    print("="*60)
    
    # Simulierte Energie-Daten
    test_data = {
        "energy_period_kwh": [
            {"value": str(0.05 + i * 0.01), "timestamp": 1700000000000 + i * 60000}
            for i in range(100)
        ]
    }
    
    state = AgentState(
        messages=[HumanMessage(content="Wie viel Energie wurde verbraucht?")],
        data=test_data,
        data_summary="100 Energiewerte",
    )
    
    # Direkt Fallback testen
    result = compute_stats_directly(state, "Wie viel Energie wurde verbraucht?")
    print(f"📈 Statistics: {result.get('statistics_summary', 'N/A')}")
    print(f"📊 Raw: {json.dumps(result.get('statistics', {}), indent=2)}")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "--fallback":
            asyncio.run(test_fallback())
    else:
        asyncio.run(test_stats_agent())
