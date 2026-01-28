"""
Stats Agent für statistische Analysen von IIoT-Daten.

Nutzt den Stats MCP Server für Berechnungen wie:
- Deskriptive Statistik (mean, std, min_max, percentiles)
- Korrelationsanalyse
- Trendanalyse
- Anomalieerkennung

DESIGN-ENTSCHEIDUNGEN:
- DEC-013: Multi-Turn Support mit datasets
- DEC-016: Strukturiertes Logging, Retry-Mechanismus

FALLBACK: Wenn MCP Server nicht erreichbar, werden die Stats direkt berechnet.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import json
import asyncio
import logging
from typing import Any, Optional
from contextlib import asynccontextmanager, AsyncExitStack

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
from langgraph.prebuilt import create_react_agent

from agents.state import AgentState
from agents.utils import (
    extract_data_from_datasets,
    extract_values_from_data,
    extract_timestamps_from_data,
    extract_user_query,
)
from prompts.stats_agent_prompt import STATS_AGENT_SYSTEM_PROMPT
from config.settings import DEFAULT_MODEL, PROJECT_ROOT as CONFIG_PROJECT_ROOT, api_key_rotator, create_anthropic_client

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


# =============================================================================
# LOGGING KONFIGURATION (DEC-016)
# =============================================================================

logger = logging.getLogger(__name__)

# Pfad zum Stats MCP Server
STATS_MCP_SERVER_PATH = PROJECT_ROOT / "mcp_servers" / "stats_server.py"

# Retry-Konfiguration
MAX_RETRIES = 3
RETRY_DELAY_BASE = 2
MCP_TIMEOUT = 30


# =============================================================================
# MCP TOOLS PROVIDER (DEC-005 - Persistent Session)
# =============================================================================

class StatsMCPToolsProvider:
    """
    Verwaltet Stats MCP Tools mit Caching und sauberem Lifecycle.

    Gleiche Pattern wie MCPToolsProvider in data_agent.py:
    - Server wird EINMAL gestartet und wiederverwendet
    - Spart 1-3 Sekunden pro Stats-Aufruf
    """

    def __init__(self, server_path: Path = STATS_MCP_SERVER_PATH):
        self._tools: list | None = None
        self._exit_stack: AsyncExitStack | None = None
        self._lock = asyncio.Lock()
        self._server_path = server_path

    async def get_tools(self) -> list:
        """Holt Stats MCP Tools - startet Server nur beim ersten Aufruf."""
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from langchain_mcp_adapters.tools import load_mcp_tools

        # Schneller Check ohne Lock
        if self._tools is not None:
            logger.debug("Stats MCP Tools aus Cache")
            return self._tools

        # Mit Lock für Thread-Safety
        async with self._lock:
            # Double-Check nach Lock
            if self._tools is not None:
                return self._tools

            logger.info("Starte Stats MCP Server (einmalig)...")

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
            await asyncio.wait_for(session.initialize(), timeout=MCP_TIMEOUT)

            self._tools = await asyncio.wait_for(load_mcp_tools(session), timeout=MCP_TIMEOUT)

            logger.info(f"Stats MCP Server gestartet, {len(self._tools)} Tools geladen")

            return self._tools

    async def cleanup(self):
        """Räumt MCP Session auf."""
        if self._exit_stack:
            await self._exit_stack.aclose()
            self._exit_stack = None
        self._tools = None
        logger.debug("Stats MCP Session aufgeräumt")

    def is_initialized(self) -> bool:
        """Prüft ob Tools geladen sind."""
        return self._tools is not None


# Globale Instanz (kann in Tests ersetzt werden)
_stats_mcp_provider = StatsMCPToolsProvider()


async def get_stats_mcp_tools() -> list:
    """Wrapper für Warmup und Rückwärtskompatibilität."""
    return await _stats_mcp_provider.get_tools()


async def cleanup_stats_mcp():
    """Wrapper für Cleanup."""
    await _stats_mcp_provider.cleanup()


# =============================================================================
# HILFSFUNKTIONEN
# =============================================================================

def create_stats_agent(tools: list):
    """Erstellt den Stats Agent mit aktuellem API Key (DEC-018)."""
    llm = create_anthropic_client()
    return create_react_agent(llm, tools)


def prepare_stats_context(state: AgentState) -> str:
    """Bereitet den Daten-Kontext für den Stats Agent vor."""
    context_parts = []
    
    # User-Query
    user_query = extract_user_query(state["messages"])
    if user_query:
        context_parts.append(f"User-Anfrage: {user_query}")
    
    # Data Summary
    if state.get("data_summary"):
        context_parts.append(f"Geladene Daten: {state['data_summary']}")
    
    # Daten aus datasets extrahieren
    datasets = state.get("datasets", {})
    data = extract_data_from_datasets(datasets)
    
    if data:
        context_parts.append("\n## VERFÜGBARE DATEN")
        context_parts.append(f"Datasets: {', '.join(datasets.keys())}")
        
        for key in list(data.keys())[:5]:  # Max 5 Keys
            values = extract_values_from_data(data, key)
            timestamps = extract_timestamps_from_data(data, key)
            
            if values:
                context_parts.append(f"\n### {key}")
                context_parts.append(f"- Anzahl Werte: {len(values)}")
                context_parts.append(f"- Beispielwerte: {values[:5]}...")
                context_parts.append(f"- Werte als Liste für Tools: {json.dumps(values[:100])}")
                
                if timestamps:
                    context_parts.append(f"- Timestamps vorhanden: Ja ({len(timestamps)} Stück)")
    
    return "\n".join(context_parts)


def extract_statistics_from_messages(messages: list) -> Optional[dict[str, Any]]:
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
                        tool_name = getattr(msg, 'name', 'unknown')
                        statistics[tool_name] = parsed
                except json.JSONDecodeError:
                    pass
    
    return statistics if statistics else None


def generate_statistics_summary(statistics: Optional[dict[str, Any]]) -> str:
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
# FALLBACK: Direkte Stats-Berechnung
# =============================================================================

def compute_stats_directly(state: AgentState, query: str) -> dict[str, Any]:
    """
    Berechnet Statistiken direkt ohne MCP Server.
    FALLBACK wenn MCP nicht funktioniert.
    """
    logger.debug("Fallback: Direkte Stats-Berechnung")
    
    datasets = state.get("datasets", {})
    data = extract_data_from_datasets(datasets)
    
    if not data:
        logger.debug("Keine Daten im State")
        return {
            "statistics": None,
            "statistics_summary": "Keine Daten vorhanden.",
            "error": "no_data",
        }
    
    logger.debug(f"Daten-Keys: {list(data.keys())}")
    
    query_lower = query.lower()
    statistics = {}
    summaries = []
    
    # Keyword-Gruppen
    keyword_groups = {
        "mean": ["durchschnitt", "mittelwert", "average", "mean", "schnitt"],
        "sum": ["verbrauch", "summe", "gesamt", "total", "energie", "energy", "wieviel", "wie viel"],
        "std": ["streuung", "standardabweichung", "std", "varianz", "schwank"],
        "minmax": ["min", "max", "bereich", "spanne", "range", "extrem"],
        "anomaly": ["anomalie", "ausreißer", "spitze", "ungewöhnlich", "auffällig"],
        "trend": ["trend", "entwicklung", "steig", "fall", "verlauf"],
    }
    
    # Prüfe welche Berechnungen gebraucht werden
    needs = {k: any(kw in query_lower for kw in kws) for k, kws in keyword_groups.items()}
    
    logger.debug(f"Query-Analyse: {needs}")
    
    # Für jeden Key in den Daten
    for key in data.keys():
        values = extract_values_from_data(data, key)
        if not values:
            continue
        
        logger.debug(f"Key {key}: {len(values)} Werte")
        is_energy_key = "energy" in key.lower() or "energie" in key.lower()
        
        # Summe
        if needs["sum"] or is_energy_key:
            total = sum(values)
            statistics[f"sum_{key}"] = {"sum": total, "count": len(values)}
            unit = "kWh" if is_energy_key else ""
            summaries.append(f"{key}: Summe = {total:.4f} {unit}".strip())
        
        # Durchschnitt
        if needs["mean"] or needs["sum"]:
            result = calculate_mean(values)
            if "mean" in result:
                statistics[f"mean_{key}"] = result
                summaries.append(f"{key}: Durchschnitt = {result['mean']:.4f} (n={result['count']})")
        
        # Standardabweichung
        if needs["std"]:
            result = calculate_std(values)
            if "std" in result and result["std"] is not None:
                statistics[f"std_{key}"] = result
                summaries.append(f"{key}: Std = {result['std']:.4f}")
        
        # Min/Max
        if needs["minmax"]:
            result = calculate_min_max(values)
            if "min" in result and result["min"] is not None:
                statistics[f"minmax_{key}"] = result
                summaries.append(f"{key}: Min={result['min']:.2f}, Max={result['max']:.2f}")
        
        # Anomalien
        if needs["anomaly"]:
            result = detect_anomalies(values)
            statistics[f"anomalies_{key}"] = result
            summaries.append(f"{key}: {result['anomalies_count']} Anomalien ({result.get('anomaly_percentage', 0):.1f}%)")
        
        # Trend
        if needs["trend"]:
            timestamps = extract_timestamps_from_data(data, key)
            result = calculate_linear_trend(values, timestamps if timestamps else None)
            if "slope" in result and result["slope"] is not None:
                statistics[f"trend_{key}"] = result
                summaries.append(f"{key}: {result['trend']} (R²={result['r_squared']:.3f})")
    
    # Fallback: Basis-Stats für alle Keys
    if not statistics:
        logger.debug("Kein Keyword-Match - berechne Basis-Stats")
        for key in list(data.keys())[:5]:
            values = extract_values_from_data(data, key)
            if not values:
                continue
            
            mean_result = calculate_mean(values)
            total = sum(values)
            
            statistics[f"mean_{key}"] = mean_result
            statistics[f"sum_{key}"] = {"sum": total, "count": len(values)}
            
            is_energy = "energy" in key.lower()
            unit = " kWh" if is_energy else ""
            summaries.append(f"{key}: Summe = {total:.4f}{unit}, Durchschnitt = {mean_result['mean']:.4f}")
    
    logger.debug(f"Ergebnis: {len(statistics)} Stats")
    
    return {
        "statistics": statistics if statistics else None,
        "statistics_summary": "; ".join(summaries) if summaries else "Keine Statistiken berechnet.",
    }


# =============================================================================
# MCP-BASIERTE AUSFÜHRUNG
# =============================================================================

async def run_stats_agent_with_mcp(state: AgentState) -> dict[str, Any]:
    """Führt den Stats Agent mit MCP Server aus (nutzt gecachte Session)."""
    tools = await get_stats_mcp_tools()
    logger.debug(f"Stats MCP Tools bereit: {len(tools)} Tools")

    agent = create_stats_agent(tools)
    data_context = prepare_stats_context(state)

    system_content = f"{STATS_AGENT_SYSTEM_PROMPT}\n\n## AKTUELLE DATEN\n\n{data_context}"

    # SystemMessages filtern (DEC-014)
    filtered_messages = [
        msg for msg in state["messages"]
        if not isinstance(msg, SystemMessage)
    ]

    messages_with_system = [
        SystemMessage(content=system_content),
        *filtered_messages
    ]

    logger.debug("Starte Agent-Ausführung...")
    result = await asyncio.wait_for(
        agent.ainvoke({"messages": messages_with_system}),
        timeout=60
    )
    logger.debug(f"Agent fertig, {len(result.get('messages', []))} Messages")

    statistics = extract_statistics_from_messages(result.get("messages", []))
    stats_summary = generate_statistics_summary(statistics)

    return {
        "messages": result.get("messages", []),
        "statistics": statistics,
        "statistics_summary": stats_summary,
    }


async def execute_stats_with_retry(state: AgentState, max_retries: int = MAX_RETRIES) -> Optional[dict]:
    """
    Versucht MCP-Ausführung mit Retry.
    Gibt None zurück wenn alle Versuche fehlschlagen.
    """
    for attempt in range(max_retries):
        try:
            result = await run_stats_agent_with_mcp(state)
            if result.get("statistics"):
                logger.debug(f"MCP erfolgreich (Versuch {attempt + 1})")
                return result
            else:
                logger.debug(f"MCP lief, aber keine Statistics (Versuch {attempt + 1})")
                return None
        
        except (asyncio.TimeoutError, ConnectionError) as e:
            delay = RETRY_DELAY_BASE * (2 ** attempt)
            logger.warning(f"MCP Fehler (Versuch {attempt + 1}/{max_retries}): {e}")
            
            if attempt < max_retries - 1:
                await asyncio.sleep(delay)
        
        except Exception as e:
            logger.warning(f"MCP unerwarteter Fehler: {e}")
            return None
    
    return None


# =============================================================================
# HAUPTFUNKTION
# =============================================================================

async def run_stats_agent(state: AgentState) -> dict[str, Any]:
    """
    Führt den Stats Agent aus.
    
    Strategie:
    1. Versuche MCP-basierte Ausführung
    2. Bei Fehler oder leeren Stats → Fallback auf direkte Berechnung
    """
    try:
        logger.debug("Starte Stats Agent")
        
        # Prüfe ob Daten vorhanden
        datasets = state.get("datasets", {})
        data = extract_data_from_datasets(datasets)
        
        if not data:
            return {
                "messages": [AIMessage(content="Keine Daten für statistische Analyse vorhanden. Bitte erst Daten laden.")],
                "error": "no_data",
            }
        
        # Query für Fallback extrahieren
        query = extract_user_query(state["messages"])
        logger.debug(f"Query: {query}")
        
        # 1. Versuche MCP
        mcp_result = await execute_stats_with_retry(state)
        
        if mcp_result:
            logger.info(f"Stats berechnet (MCP): {mcp_result.get('statistics_summary', '')[:100]}")
            return mcp_result
        
        # 2. Fallback: Direkte Berechnung
        logger.debug("Verwende Fallback: Direkte Berechnung")
        fallback_result = compute_stats_directly(state, query)
        
        if fallback_result.get("statistics"):
            stats_summary = fallback_result['statistics_summary']
            response_text = f"Statistische Analyse:\n\n{stats_summary}"
            logger.info(f"Stats berechnet (Fallback): {stats_summary[:100]}")
        else:
            response_text = "Konnte keine Statistiken berechnen."
            logger.warning("Keine Stats berechnet (weder MCP noch Fallback)")
        
        return {
            "messages": [AIMessage(content=response_text)],
            "statistics": fallback_result.get("statistics"),
            "statistics_summary": fallback_result.get("statistics_summary"),
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
# TESTS
# =============================================================================

async def test_stats_agent():
    """Test des Stats Agents."""
    from datetime import datetime, timedelta
    import random
    
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    
    print("\n" + "="*60)
    print("🧪 Stats Agent Test")
    print("="*60)
    
    now = datetime.now()
    base_values = [25.0 + random.gauss(0, 2) for _ in range(50)]
    base_values[10] = 45.0  # Ausreißer
    base_values[30] = 5.0   # Ausreißer
    
    test_datasets = {
        "temperature": {
            "data": {
                "temperature": [
                    {"value": str(val), "timestamp": int((now - timedelta(minutes=50-i)).timestamp() * 1000)}
                    for i, val in enumerate(base_values)
                ]
            },
            "meta": {},
        }
    }
    
    print(f"📊 Test-Daten: {len(base_values)} Punkte (inkl. 2 Ausreißer)")
    
    state = AgentState(
        messages=[HumanMessage(content="Was ist die Durchschnittstemperatur?")],
        datasets=test_datasets,
        data_summary="50 Temperaturwerte",
    )
    
    result = await run_stats_agent(state)
    print(f"📈 Statistics: {result.get('statistics_summary', 'N/A')}")


if __name__ == "__main__":
    asyncio.run(test_stats_agent())
