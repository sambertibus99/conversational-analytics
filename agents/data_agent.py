"""
Data Agent für ThingsBoard-Datenabfragen.

Nutzt MCP (Model Context Protocol) um mit dem ThingsBoard Server zu kommunizieren.
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
from prompts.data_agent_prompt import DATA_AGENT_SYSTEM_PROMPT
from config.settings import ANTHROPIC_API_KEY, DEFAULT_MODEL, PROJECT_ROOT


# Pfad zum MCP Server
MCP_SERVER_PATH = PROJECT_ROOT / "mcp_servers" / "thingsboard_server.py"

# Debug-Modus
DEBUG = False


def debug_print(msg: str):
    """Gibt Debug-Nachrichten aus wenn DEBUG=True."""
    if DEBUG:
        print(f"🔍 DEBUG: {msg}")


@asynccontextmanager
async def mcp_client_context():
    """Async Context Manager für MCP Client."""
    server_params = StdioServerParameters(
        command="python",
        args=[str(MCP_SERVER_PATH)],
        env=None,
    )
    
    debug_print(f"Starte MCP Server: {MCP_SERVER_PATH}")
    
    async with stdio_client(server_params) as (read_stream, write_stream):
        debug_print("stdio_client gestartet")
        async with ClientSession(read_stream, write_stream) as session:
            debug_print("ClientSession erstellt")
            await session.initialize()
            debug_print("Session initialisiert")
            tools = await load_mcp_tools(session)
            debug_print(f"Tools geladen: {[t.name for t in tools]}")
            yield tools


def create_data_agent(tools: list):
    """Erstellt den Data Agent mit den gegebenen Tools."""
    debug_print(f"Erstelle Agent mit Model: {DEFAULT_MODEL}")
    
    llm = ChatAnthropic(
        model=DEFAULT_MODEL,
        api_key=ANTHROPIC_API_KEY,
        temperature=0,
    )
    
    agent = create_react_agent(llm, tools)
    
    return agent


def extract_text_from_tool_content(content: Any) -> str | None:
    """
    Extrahiert den Text aus ToolMessage.content.
    
    Content kann sein:
    - String (direkt)
    - Liste von Content-Blöcken: [{'type': 'text', 'text': '...'}]
    """
    if content is None:
        return None
    
    # Direkt ein String
    if isinstance(content, str):
        return content
    
    # Liste von Content-Blöcken (LangChain Format)
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get('type') == 'text':
                return block.get('text')
            # Falls der Block direkt ein String ist
            if isinstance(block, str):
                return block
    
    # Dict mit 'text' key
    if isinstance(content, dict) and 'text' in content:
        return content['text']
    
    return None


def parse_json_safe(text: str) -> Any:
    """Parst JSON sicher."""
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def extract_data_from_parsed(parsed: Any) -> tuple[Any, dict | None]:
    """Extrahiert Daten aus geparstem Content."""
    if parsed is None:
        return None, None
    
    # get_telemetry / get_telemetry_aggregated Response
    # Format: {"timerange": {...}, "data_points": {...}, "data": {...}}
    if isinstance(parsed, dict) and "data" in parsed and "data_points" in parsed:
        return parsed["data"], {
            "timerange": parsed.get("timerange"),
            "data_points": parsed.get("data_points"),
            "interval_ms": parsed.get("interval_ms"),
            "aggregation": parsed.get("aggregation"),
        }
    
    # get_latest_telemetry Response
    # Format: {"axis_act_a1_deg": {"value": "13.82", "timestamp": 123}}
    if isinstance(parsed, dict) and parsed:
        first_key = next(iter(parsed.keys()), None)
        first_val = parsed.get(first_key) if first_key else None
        if isinstance(first_val, dict) and "value" in first_val:
            return parsed, {"type": "latest", "data_points": {k: 1 for k in parsed}}
    
    # Liste (z.B. list_telemetry_keys, list_devices)
    if isinstance(parsed, list):
        return parsed, {"type": "list", "count": len(parsed)}
    
    # Sonstiges dict
    if isinstance(parsed, dict):
        return parsed, {"type": "other", "keys": list(parsed.keys())}
    
    return None, None


def generate_data_summary(data: Any, meta: dict | None) -> str:
    """Generiert eine kurze Zusammenfassung der Daten."""
    if data is None:
        return "Keine Daten erhalten."
    
    # Aktuellste Werte (get_latest_telemetry)
    if meta and meta.get("type") == "latest":
        summaries = []
        for key, val in data.items():
            if isinstance(val, dict) and "value" in val:
                summaries.append(f"{key}: {val.get('value')}")
        if summaries:
            return f"Aktuelle Werte: {', '.join(summaries)}"
    
    # Zeitreihen (get_telemetry, get_telemetry_aggregated)
    if meta and meta.get("data_points"):
        total_points = sum(meta["data_points"].values())
        keys = list(meta["data_points"].keys())
        agg = meta.get("aggregation", "")
        agg_str = f" ({agg})" if agg else ""
        return f"{total_points} Datenpunkte{agg_str} für {', '.join(keys)} geladen."
    
    # Listen (list_telemetry_keys, list_devices, etc.)
    if meta and meta.get("type") == "list":
        count = meta.get("count", len(data) if isinstance(data, list) else 0)
        return f"{count} Einträge geladen."
    
    if isinstance(data, list):
        return f"{len(data)} Einträge geladen."
    
    if isinstance(data, dict):
        return f"Daten mit {len(data)} Feldern abgerufen."
    
    return "Daten erfolgreich abgerufen."


async def run_data_agent(state: AgentState) -> dict[str, Any]:
    """Führt den Data Agent aus."""
    try:
        debug_print("Starte run_data_agent")
        
        async with mcp_client_context() as tools:
            debug_print("MCP Context aktiv")
            
            agent = create_data_agent(tools)
            debug_print("Agent erstellt, starte Ausführung...")
            
            # System Prompt als erste Message einfügen
            messages_with_system = [
                SystemMessage(content=DATA_AGENT_SYSTEM_PROMPT),
                *state["messages"]
            ]
            
            result = await agent.ainvoke({"messages": messages_with_system})
            debug_print(f"Agent fertig, {len(result.get('messages', []))} Messages")
            
            data = None
            meta = None
            
            # Durchsuche alle Messages nach Tool-Ergebnissen
            for msg in result.get("messages", []):
                msg_type = type(msg).__name__
                debug_print(f"Message type: {msg_type}")
                
                # ToolMessage enthält die Tool-Ausgabe
                if isinstance(msg, ToolMessage):
                    # WICHTIG: Content kann Liste von Blöcken sein!
                    text_content = extract_text_from_tool_content(msg.content)
                    debug_print(f"Extracted text: {text_content[:200] if text_content else 'None'}...")
                    
                    if text_content:
                        parsed = parse_json_safe(text_content)
                        debug_print(f"Parsed type: {type(parsed)}")
                        
                        if parsed is not None:
                            extracted_data, extracted_meta = extract_data_from_parsed(parsed)
                            
                            if extracted_data is not None:
                                # Priorisiere "echte" Daten über Listen
                                current_is_list = meta and meta.get("type") == "list"
                                new_is_not_list = extracted_meta and extracted_meta.get("type") != "list"
                                
                                if data is None or (current_is_list and new_is_not_list):
                                    data = extracted_data
                                    meta = extracted_meta
                                    debug_print(f"Daten extrahiert: meta={meta}")
            
            # Summary generieren
            summary = generate_data_summary(data, meta)
            debug_print(f"Summary: {summary}")
            
            return {
                "messages": result.get("messages", []),
                "data": data,
                "data_meta": meta,
                "data_summary": summary,
            }
        
    except Exception as e:
        error_details = traceback.format_exc()
        if DEBUG:
            print(f"\n❌ FEHLER DETAILS:\n{error_details}")
        
        error_msg = f"Fehler beim Datenabruf: {str(e)}"
        return {
            "messages": [AIMessage(content=error_msg)],
            "error": error_msg,
        }


async def data_agent_node(state: AgentState) -> dict[str, Any]:
    """LangGraph Node für den Data Agent."""
    return await run_data_agent(state)


# =============================================================================
# STANDALONE TEST
# =============================================================================

async def test_data_agent():
    """Test des Data Agents mit verschiedenen Queries."""
    
    test_queries = [
        "Wie ist die aktuelle Position von Achse 1?",
        "Zeig mir den Verlauf der Bahngeschwindigkeit der letzten 10 Minuten",
        "Welche Telemetrie-Keys sind verfügbar?",
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
        
        if result.get("data_meta"):
            print(f"📈 Meta: {result['data_meta']}")
        
        if result.get("error"):
            print(f"❌ Error: {result['error']}")
        
        # Letzte AI-Message anzeigen
        for msg in reversed(result.get("messages", [])):
            if isinstance(msg, AIMessage) and isinstance(msg.content, str):
                print(f"\n🤖 Agent: {msg.content[:500]}")
                break
        
        print()


async def interactive_test():
    """Interaktiver Test mit eigenen Queries."""
    print("\n" + "="*60)
    print("🤖 Data Agent Interactive Test")
    print("="*60)
    print("Gib eine Frage ein (oder 'quit' zum Beenden):\n")
    
    while True:
        query = input("📝 Query: ").strip()
        
        if query.lower() in ["quit", "exit", "q"]:
            break
        
        if not query:
            continue
        
        state = AgentState(
            messages=[HumanMessage(content=query)]
        )
        
        print("\n⏳ Verarbeite...")
        result = await run_data_agent(state)
        
        print(f"\n📊 Data Summary: {result.get('data_summary', 'N/A')}")
        
        if result.get("data_meta"):
            print(f"📈 Meta: {result['data_meta']}")
        
        if result.get("error"):
            print(f"❌ Error: {result['error']}")
        
        # Letzte AI Message
        for msg in reversed(result.get("messages", [])):
            if isinstance(msg, AIMessage) and isinstance(msg.content, str):
                print(f"\n🤖 Agent: {msg.content}")
                break
        
        print("\n" + "-"*40)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--interactive":
        asyncio.run(interactive_test())
    else:
        asyncio.run(test_data_agent())