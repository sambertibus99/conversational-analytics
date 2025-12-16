"""
Viz Agent für Chart-Generierung.

Nutzt den AntV MCP Server (@antv/mcp-server-chart) um Visualisierungen zu erstellen.
Liest Daten aus dem State (vom Data Agent) und transformiert sie für AntV.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import json
import asyncio
import traceback
from datetime import datetime
from typing import Any
from contextlib import asynccontextmanager

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
from langgraph.prebuilt import create_react_agent

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_mcp_adapters.tools import load_mcp_tools

from agents.state import AgentState
from prompts.viz_agent_prompt import VIZ_AGENT_SYSTEM_PROMPT
from config.settings import ANTHROPIC_API_KEY, DEFAULT_MODEL

# Debug-Modus
DEBUG = False


def debug_print(msg: str):
    """Gibt Debug-Nachrichten aus wenn DEBUG=True."""
    if DEBUG:
        print(f"🔍 VIZ DEBUG: {msg}")


@asynccontextmanager
async def antv_mcp_client_context():
    """Async Context Manager für AntV MCP Client."""
    server_params = StdioServerParameters(
        command="npx",
        args=["-y", "@antv/mcp-server-chart"],
        env=None,
    )
    
    debug_print("Starte AntV MCP Server...")
    
    async with stdio_client(server_params) as (read_stream, write_stream):
        debug_print("stdio_client gestartet")
        async with ClientSession(read_stream, write_stream) as session:
            debug_print("ClientSession erstellt")
            await session.initialize()
            debug_print("Session initialisiert")
            tools = await load_mcp_tools(session)
            debug_print(f"Tools geladen: {[t.name for t in tools]}")
            yield tools


def create_viz_agent(tools: list):
    """Erstellt den Viz Agent mit den gegebenen Tools."""
    debug_print(f"Erstelle Viz Agent mit Model: {DEFAULT_MODEL}")
    
    llm = ChatAnthropic(
        model=DEFAULT_MODEL,
        api_key=ANTHROPIC_API_KEY,
        temperature=0,
    )
    
    agent = create_react_agent(llm, tools)
    return agent


def timestamp_to_time_string(ts: int) -> str:
    """Konvertiert Unix-Timestamp (ms) zu lesbarer Zeit."""
    try:
        dt = datetime.fromtimestamp(ts / 1000)
        return dt.strftime("%H:%M:%S")
    except:
        return str(ts)


def transform_timeseries_for_antv(data: dict[str, list]) -> list[dict]:
    """
    Transformiert ThingsBoard-Zeitreihen zu AntV Line Chart Format.
    
    Input (ThingsBoard):
    {
        "axis_act_a1_deg": [
            {"value": "25.3", "timestamp": 1702900000000},
            {"value": "26.1", "timestamp": 1702900001000}
        ]
    }
    
    Output (AntV):
    [
        {"time": "10:00:00", "value": 25.3},
        {"time": "10:00:01", "value": 26.1}
    ]
    """
    result = []
    
    # Falls mehrere Keys, nehmen wir den ersten (oder alle für Multi-Line)
    for key, values in data.items():
        if not isinstance(values, list):
            continue
            
        for point in values:
            if isinstance(point, dict):
                ts = point.get("timestamp", 0)
                val = point.get("value", 0)
                
                # Value zu Float konvertieren
                try:
                    val = float(val)
                except (ValueError, TypeError):
                    continue
                
                result.append({
                    "time": timestamp_to_time_string(ts),
                    "value": val,
                })
        
        # Nur ersten Key verarbeiten für einfache Line Charts
        break
    
    # Nach Zeit sortieren
    result.sort(key=lambda x: x["time"])
    return result


def transform_multikey_for_antv(data: dict[str, list]) -> list[dict]:
    """
    Transformiert mehrere Keys zu Multi-Line Chart Format.
    
    Output (AntV mit category):
    [
        {"time": "10:00:00", "value": 25.3, "category": "axis_act_a1_deg"},
        {"time": "10:00:00", "value": 12.1, "category": "axis_act_a2_deg"},
    ]
    """
    result = []
    
    for key, values in data.items():
        if not isinstance(values, list):
            continue
            
        for point in values:
            if isinstance(point, dict):
                ts = point.get("timestamp", 0)
                val = point.get("value", 0)
                
                try:
                    val = float(val)
                except (ValueError, TypeError):
                    continue
                
                # Key-Namen kürzen für Lesbarkeit
                short_key = key.replace("axis_act_", "A").replace("_deg", "°")
                
                result.append({
                    "time": timestamp_to_time_string(ts),
                    "value": val,
                    "category": short_key,
                })
    
    result.sort(key=lambda x: (x["time"], x.get("category", "")))
    return result


def transform_for_scatter(data: dict[str, list]) -> list[dict]:
    """
    Transformiert zwei Keys zu Scatter Chart Format.
    
    Output (AntV):
    [{"x": 25.3, "y": 12.1}, ...]
    """
    keys = list(data.keys())
    if len(keys) < 2:
        return []
    
    x_key, y_key = keys[0], keys[1]
    x_values = {p["timestamp"]: float(p["value"]) for p in data[x_key] if isinstance(p, dict)}
    y_values = {p["timestamp"]: float(p["value"]) for p in data[y_key] if isinstance(p, dict)}
    
    result = []
    for ts in x_values:
        if ts in y_values:
            result.append({"x": x_values[ts], "y": y_values[ts]})
    
    return result


def transform_for_comparison(data: dict[str, list]) -> list[dict]:
    """
    Transformiert Daten für Balken/Säulendiagramm (Vergleich).
    Berechnet Durchschnitt pro Key.
    
    Output (AntV):
    [{"category": "Achse 1", "value": 25.3}, ...]
    """
    result = []
    
    for key, values in data.items():
        if not isinstance(values, list) or not values:
            continue
        
        # Durchschnitt berechnen
        nums = []
        for p in values:
            if isinstance(p, dict):
                try:
                    nums.append(float(p.get("value", 0)))
                except:
                    pass
        
        if nums:
            avg = sum(nums) / len(nums)
            # Key-Namen aufhübschen
            nice_name = key.replace("axis_act_", "Achse ").replace("_deg", "").replace("a", "")
            result.append({"category": nice_name, "value": round(avg, 2)})
    
    return result


def transform_latest_values(data: dict[str, Any]) -> list[dict]:
    """
    Transformiert get_latest_telemetry Daten für Column Chart.
    
    Input:
    {"axis_act_a1_deg": {"value": "25.3", "timestamp": 123}}
    
    Output:
    [{"category": "Achse 1", "value": 25.3}]
    """
    result = []
    
    for key, val in data.items():
        if isinstance(val, dict) and "value" in val:
            try:
                value = float(val["value"])
                nice_name = key.replace("axis_act_", "Achse ").replace("_deg", "").replace("a", "")
                result.append({"category": nice_name, "value": round(value, 2)})
            except:
                pass
    
    return result


def get_unit_for_key(key: str) -> str:
    """Gibt die Einheit für einen Key zurück."""
    if "_deg" in key:
        return "°"
    elif "_mm" in key:
        return "mm"
    elif "_nm" in key:
        return "Nm"
    elif "_pct" in key:
        return "%"
    elif "_m_per_s" in key:
        return "m/s"
    elif "_kwh" in key:
        return "kWh"
    else:
        return ""


def extract_chart_url(messages: list) -> str | None:
    """Extrahiert die Chart-URL aus den Agent-Messages."""
    for msg in reversed(messages):
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
                # URL extrahieren (beginnt mit http)
                if content.startswith("http"):
                    return content.strip()
                
                # Oder aus JSON
                try:
                    parsed = json.loads(content)
                    if isinstance(parsed, dict):
                        return parsed.get("url") or parsed.get("chart_url")
                except:
                    pass
    
    return None


def prepare_viz_context(state: AgentState) -> str:
    """Bereitet den Daten-Kontext für den Viz Agent vor."""
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
            context_parts.append(f"Datenpunkte: {meta['data_points']}")
    
    # Tatsächliche Daten (gekürzt für Context)
    if state.get("data"):
        data = state["data"]
        
        # Zeige Struktur und erste Werte
        if isinstance(data, dict):
            keys = list(data.keys())
            context_parts.append(f"Verfügbare Keys: {keys}")
            
            # Erste Werte als Beispiel
            for key in keys[:2]:
                values = data[key]
                if isinstance(values, list) and values:
                    context_parts.append(f"Beispiel {key}: {values[:3]}...")
        
        # Transformierte Daten für einfachen Zugriff
        if isinstance(data, dict) and data:
            first_key = list(data.keys())[0]
            unit = get_unit_for_key(first_key)
            
            # Für Line Chart transformieren
            transformed = transform_timeseries_for_antv(data)
            if transformed:
                context_parts.append(f"\nFür Line Chart transformiert ({len(transformed)} Punkte):")
                context_parts.append(f"data={json.dumps(transformed[:5])}...")
                context_parts.append(f"Empfohlener axisYTitle: 'Wert ({unit})'")
    
    return "\n".join(context_parts)


async def run_viz_agent(state: AgentState) -> dict[str, Any]:
    """Führt den Viz Agent aus."""
    try:
        debug_print("Starte run_viz_agent")
        
        # Prüfe ob Daten vorhanden
        if not state.get("data"):
            return {
                "messages": [AIMessage(content="Keine Daten zum Visualisieren vorhanden. Bitte erst Daten laden.")],
                "error": "no_data",
            }
        
        async with antv_mcp_client_context() as tools:
            debug_print("AntV MCP Context aktiv")
            
            agent = create_viz_agent(tools)
            debug_print("Agent erstellt")
            
            # Kontext mit Daten vorbereiten
            data_context = prepare_viz_context(state)
            
            # System Prompt + Daten-Kontext
            system_content = f"{VIZ_AGENT_SYSTEM_PROMPT}\n\n## AKTUELLE DATEN\n\n{data_context}"
            
            # Transformierte Daten direkt in den Prompt (damit LLM sie nutzen kann)
            data = state["data"]
            if isinstance(data, dict) and data:
                transformed = transform_timeseries_for_antv(data)
                if transformed:
                    # Nur erste 100 Punkte für den Kontext
                    limited = transformed[:100]
                    system_content += f"\n\nTRANSFORMIERTE DATEN (bereit für generate_line_chart):\n{json.dumps(limited)}"
            
            messages_with_system = [
                SystemMessage(content=system_content),
                *state["messages"]
            ]
            
            debug_print("Starte Agent-Ausführung...")
            result = await agent.ainvoke({"messages": messages_with_system})
            debug_print(f"Agent fertig, {len(result.get('messages', []))} Messages")
            
            # Chart-URL extrahieren
            chart_url = extract_chart_url(result.get("messages", []))
            debug_print(f"Chart URL: {chart_url}")
            
            # Chart-Typ aus Tool-Call extrahieren
            chart_type = None
            for msg in result.get("messages", []):
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    for tc in msg.tool_calls:
                        if "chart" in tc.get("name", ""):
                            chart_type = tc["name"].replace("generate_", "").replace("_chart", "")
                            break
            
            return {
                "messages": result.get("messages", []),
                "chart_url": chart_url,
                "chart_type": chart_type,
            }
    
    except Exception as e:
        error_details = traceback.format_exc()
        if DEBUG:
            print(f"\n❌ FEHLER DETAILS:\n{error_details}")
        
        error_msg = f"Fehler bei der Visualisierung: {str(e)}"
        return {
            "messages": [AIMessage(content=error_msg)],
            "error": error_msg,
        }


async def viz_agent_node(state: AgentState) -> dict[str, Any]:
    """LangGraph Node für den Viz Agent."""
    return await run_viz_agent(state)


# =============================================================================
# STANDALONE TEST
# =============================================================================

async def test_viz_agent():
    """Test des Viz Agents mit simulierten Daten."""
    from datetime import datetime, timedelta
    
    print("\n" + "="*60)
    print("🧪 Viz Agent Test")
    print("="*60)
    
    # Simulierte Daten (wie vom Data Agent)
    now = datetime.now()
    test_data = {
        "axis_act_a1_deg": [
            {"value": str(25.3 + i * 0.5), "timestamp": int((now - timedelta(minutes=10-i)).timestamp() * 1000)}
            for i in range(10)
        ]
    }
    
    print(f"\n📊 Test-Daten: {len(test_data['axis_act_a1_deg'])} Punkte")
    
    # State mit Daten vorbereiten
    state = AgentState(
        messages=[HumanMessage(content="Zeig mir den Verlauf als Liniendiagramm")],
        data=test_data,
        data_summary="10 Datenpunkte für axis_act_a1_deg der letzten 10 Minuten",
        data_meta={"data_points": {"axis_act_a1_deg": 10}},
    )
    
    print("⏳ Generiere Chart...")
    result = await run_viz_agent(state)
    
    if result.get("chart_url"):
        print(f"\n✅ Chart generiert!")
        print(f"   URL: {result['chart_url']}")
        print(f"   Typ: {result.get('chart_type', 'unbekannt')}")
    else:
        print(f"\n❌ Kein Chart generiert")
        if result.get("error"):
            print(f"   Fehler: {result['error']}")
    
    # Letzte AI-Message
    for msg in reversed(result.get("messages", [])):
        if isinstance(msg, AIMessage) and isinstance(msg.content, str):
            print(f"\n🤖 Agent: {msg.content[:300]}")
            break


async def test_with_real_data():
    """Test mit echten Daten vom Data Agent."""
    from agents.data_agent import run_data_agent
    
    print("\n" + "="*60)
    print("🧪 Viz Agent Test mit echten Daten")
    print("="*60)
    
    # Erst Daten laden
    print("\n1️⃣ Lade Daten vom Data Agent...")
    data_state = AgentState(
        messages=[HumanMessage(content="Hole die Achsposition 1 der letzten 5 Minuten")]
    )
    data_result = await run_data_agent(data_state)
    
    print(f"   Summary: {data_result.get('data_summary', 'N/A')}")
    
    if not data_result.get("data"):
        print("   ❌ Keine Daten erhalten")
        return
    
    # Dann visualisieren
    print("\n2️⃣ Generiere Visualisierung...")
    viz_state = AgentState(
        messages=[HumanMessage(content="Zeig das als Liniendiagramm")],
        data=data_result.get("data"),
        data_summary=data_result.get("data_summary"),
        data_meta=data_result.get("data_meta"),
    )
    
    viz_result = await run_viz_agent(viz_state)
    
    if viz_result.get("chart_url"):
        print(f"\n✅ Chart generiert!")
        print(f"   URL: {viz_result['chart_url']}")
    else:
        print(f"\n❌ Kein Chart generiert")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--real":
        asyncio.run(test_with_real_data())
    else:
        asyncio.run(test_viz_agent())
