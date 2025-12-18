"""
Stats Agent für statistische Analysen von IIoT-Daten.

Nutzt den Stats MCP Server für Berechnungen wie:
- Deskriptive Statistik (mean, std, min_max, percentiles)
- Korrelationsanalyse
- Trendanalyse
- Anomalieerkennung

WICHTIG: Der Stats Agent arbeitet mit Daten aus dem State (vom Data Agent).
Er ruft KEINE neuen Daten ab!
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
from prompts.stats_agent_prompt import STATS_AGENT_SYSTEM_PROMPT
from config.settings import ANTHROPIC_API_KEY, DEFAULT_MODEL, PROJECT_ROOT as CONFIG_PROJECT_ROOT


# Pfad zum Stats MCP Server
STATS_MCP_SERVER_PATH = PROJECT_ROOT / "mcp_servers" / "stats_server.py"

# Debug-Modus
DEBUG = False


def debug_print(msg: str):
    """Gibt Debug-Nachrichten aus wenn DEBUG=True."""
    if DEBUG:
        print(f"🔍 STATS DEBUG: {msg}")


@asynccontextmanager
async def stats_mcp_client_context():
    """Async Context Manager für Stats MCP Client."""
    server_params = StdioServerParameters(
        command="python",
        args=[str(STATS_MCP_SERVER_PATH)],
        env=None,
    )
    
    debug_print(f"Starte Stats MCP Server: {STATS_MCP_SERVER_PATH}")
    
    async with stdio_client(server_params) as (read_stream, write_stream):
        debug_print("stdio_client gestartet")
        async with ClientSession(read_stream, write_stream) as session:
            debug_print("ClientSession erstellt")
            await session.initialize()
            debug_print("Session initialisiert")
            tools = await load_mcp_tools(session)
            debug_print(f"Tools geladen: {[t.name for t in tools]}")
            yield tools


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


def extract_values_from_data(data: dict[str, Any], key: str | None = None) -> list[float]:
    """
    Extrahiert numerische Werte aus ThingsBoard-Datenformat.
    
    Input-Formate:
    1. {"key": [{"value": "25.3", "timestamp": 123}, ...]}  (Zeitreihe)
    2. {"key": {"value": "25.3", "timestamp": 123}}  (Latest)
    3. {"key": [25.3, 26.1, ...]}  (Einfache Liste)
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
    raw = data[key]
    
    # Format 1: Liste von Dicts mit value/timestamp
    if isinstance(raw, list):
        for point in raw:
            if isinstance(point, dict) and "value" in point:
                try:
                    values.append(float(point["value"]))
                except (ValueError, TypeError):
                    continue
            elif isinstance(point, (int, float)):
                values.append(float(point))
    
    # Format 2: Einzelner Dict (latest)
    elif isinstance(raw, dict) and "value" in raw:
        try:
            values.append(float(raw["value"]))
        except (ValueError, TypeError):
            pass
    
    debug_print(f"Extrahiert {len(values)} Werte aus key '{key}'")
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


async def run_stats_agent(state: AgentState) -> dict[str, Any]:
    """Führt den Stats Agent aus."""
    try:
        debug_print("Starte run_stats_agent")
        
        # Prüfe ob Daten vorhanden
        if not state.get("data"):
            return {
                "messages": [AIMessage(content="Keine Daten für statistische Analyse vorhanden. Bitte erst Daten laden.")],
                "error": "no_data",
            }
        
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
            result = await agent.ainvoke({"messages": messages_with_system})
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
    
    # Test 3: Trend
    print("\n--- Test 3: Trendanalyse ---")
    # Steigender Trend
    trend_values = [20 + i * 0.5 + random.gauss(0, 1) for i in range(30)]
    trend_data = {
        "temperature": [
            {"value": str(val), "timestamp": int((now - timedelta(minutes=30-i)).timestamp() * 1000)}
            for i, val in enumerate(trend_values)
        ]
    }
    
    state3 = AgentState(
        messages=[HumanMessage(content="Zeigt die Temperatur einen steigenden oder fallenden Trend?")],
        data=trend_data,
        data_summary="30 Temperaturwerte mit steigendem Trend",
    )
    
    result3 = await run_stats_agent(state3)
    print(f"📈 Statistics: {result3.get('statistics_summary', 'N/A')}")
    
    for msg in reversed(result3.get("messages", [])):
        if isinstance(msg, AIMessage) and isinstance(msg.content, str):
            print(f"🤖 Agent: {msg.content[:300]}...")
            break


async def test_with_real_data():
    """Test mit echten Daten vom Data Agent."""
    from agents.data_agent import run_data_agent
    
    print("\n" + "="*60)
    print("🧪 Stats Agent Test mit echten Daten")
    print("="*60)
    
    # Erst Daten laden
    print("\n1️⃣ Lade Daten vom Data Agent...")
    data_state = AgentState(
        messages=[HumanMessage(content="Hole das Drehmoment von Achse 1 der letzten 10 Minuten")]
    )
    data_result = await run_data_agent(data_state)
    
    print(f"   Summary: {data_result.get('data_summary', 'N/A')}")
    
    if not data_result.get("data"):
        print("   ❌ Keine Daten erhalten")
        return
    
    # Dann analysieren
    print("\n2️⃣ Statistische Analyse...")
    stats_state = AgentState(
        messages=[HumanMessage(content="Berechne Durchschnitt, Standardabweichung und finde Ausreißer")],
        data=data_result.get("data"),
        data_summary=data_result.get("data_summary"),
        data_meta=data_result.get("data_meta"),
    )
    
    stats_result = await run_stats_agent(stats_state)
    
    print(f"\n📈 Statistics Summary: {stats_result.get('statistics_summary', 'N/A')}")
    
    if stats_result.get("statistics"):
        print(f"📊 Raw Statistics: {json.dumps(stats_result['statistics'], indent=2)[:500]}")
    
    for msg in reversed(stats_result.get("messages", [])):
        if isinstance(msg, AIMessage) and isinstance(msg.content, str):
            print(f"\n🤖 Agent: {msg.content}")
            break


async def interactive_test():
    """Interaktiver Test mit eigenen Queries."""
    from agents.data_agent import run_data_agent
    
    print("\n" + "="*60)
    print("🤖 Stats Agent Interactive Test")
    print("="*60)
    print("Befehle:")
    print("  load <query>  - Daten laden (z.B. 'load Temperatur letzte Stunde')")
    print("  stats <query> - Statistik berechnen")
    print("  quit          - Beenden")
    print()
    
    current_data = None
    current_summary = None
    
    while True:
        user_input = input("📝 > ").strip()
        
        if user_input.lower() in ["quit", "exit", "q"]:
            break
        
        if not user_input:
            continue
        
        if user_input.lower().startswith("load "):
            query = user_input[5:].strip()
            print(f"\n⏳ Lade Daten: {query}")
            
            data_state = AgentState(messages=[HumanMessage(content=query)])
            data_result = await run_data_agent(data_state)
            
            current_data = data_result.get("data")
            current_summary = data_result.get("data_summary")
            
            print(f"✅ {current_summary}")
            
        elif user_input.lower().startswith("stats "):
            if not current_data:
                print("❌ Keine Daten geladen. Erst 'load <query>' ausführen.")
                continue
            
            query = user_input[6:].strip()
            print(f"\n⏳ Berechne: {query}")
            
            stats_state = AgentState(
                messages=[HumanMessage(content=query)],
                data=current_data,
                data_summary=current_summary,
            )
            
            result = await run_stats_agent(stats_state)
            
            print(f"📈 {result.get('statistics_summary', 'N/A')}")
            
            for msg in reversed(result.get("messages", [])):
                if isinstance(msg, AIMessage) and isinstance(msg.content, str):
                    print(f"\n🤖 {msg.content}")
                    break
        
        else:
            print("Unbekannter Befehl. Nutze 'load', 'stats' oder 'quit'.")
        
        print()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "--real":
            asyncio.run(test_with_real_data())
        elif sys.argv[1] == "--interactive":
            asyncio.run(interactive_test())
    else:
        asyncio.run(test_stats_agent())
