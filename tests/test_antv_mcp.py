"""
Test des AntV MCP Servers (@antv/mcp-server-chart).

Testet:
1. Verbindung zum MCP Server
2. Verfügbare Tools auflisten
3. Einfachen Chart generieren

Voraussetzung: Node.js/npx muss installiert sein.

Ausführen:
    python tests/test_antv_mcp.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import asyncio
import json
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def list_antv_tools():
    """Listet alle verfügbaren Tools des AntV MCP Servers auf."""
    server_params = StdioServerParameters(
        command="npx",
        args=["-y", "@antv/mcp-server-chart"],
    )
    
    print("🔌 Verbinde mit @antv/mcp-server-chart...")
    print("   (Beim ersten Mal wird das Package heruntergeladen)\n")
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            
            print(f"✅ {len(tools.tools)} Tools gefunden:\n")
            
            # Gruppiere nach Typ
            chart_tools = []
            other_tools = []
            
            for tool in tools.tools:
                if "chart" in tool.name or "diagram" in tool.name or "map" in tool.name:
                    chart_tools.append(tool)
                else:
                    other_tools.append(tool)
            
            print("📊 Chart-Tools:")
            for tool in sorted(chart_tools, key=lambda t: t.name):
                print(f"   • {tool.name}")
            
            if other_tools:
                print("\n🔧 Andere Tools:")
                for tool in sorted(other_tools, key=lambda t: t.name):
                    print(f"   • {tool.name}")
            
            return tools.tools


async def test_simple_chart():
    """Testet die Generierung eines einfachen Line-Charts."""
    server_params = StdioServerParameters(
        command="npx",
        args=["-y", "@antv/mcp-server-chart"],
    )
    
    print("\n" + "="*60)
    print("🧪 Test: Einfaches Liniendiagramm generieren")
    print("="*60)
    
    # Test-Daten (simulierte Roboter-Telemetrie)
    test_data = [
        {"time": "10:00", "value": 25.3},
        {"time": "10:01", "value": 26.1},
        {"time": "10:02", "value": 25.8},
        {"time": "10:03", "value": 27.2},
        {"time": "10:04", "value": 26.5},
        {"time": "10:05", "value": 25.9},
    ]
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            # Finde das Line Chart Tool
            tools = await session.list_tools()
            line_tool = None
            for tool in tools.tools:
                if "line" in tool.name.lower():
                    line_tool = tool
                    break
            
            if not line_tool:
                print("❌ Kein Line Chart Tool gefunden!")
                return
            
            print(f"\n📈 Nutze Tool: {line_tool.name}")
            print(f"   Daten: {len(test_data)} Punkte")
            
            # Tool aufrufen
            # Die Parameter hängen vom Tool ab - wir probieren das Standard-Format
            try:
                result = await session.call_tool(
                    line_tool.name,
                    arguments={
                        "data": test_data,
                        "title": "Test: Achsposition über Zeit",
                        "xField": "time",
                        "yField": "value",
                    }
                )
                
                print(f"\n✅ Ergebnis:")
                
                # Result kann verschiedene Formate haben
                for content in result.content:
                    if hasattr(content, 'text'):
                        # Versuche JSON zu parsen
                        try:
                            parsed = json.loads(content.text)
                            print(json.dumps(parsed, indent=2)[:500])
                        except:
                            print(content.text[:500])
                    elif hasattr(content, 'data'):
                        print(f"   [Bild-Daten: {len(content.data)} bytes]")
                    else:
                        print(f"   {content}")
                
            except Exception as e:
                print(f"\n⚠️ Tool-Aufruf fehlgeschlagen: {e}")
                print("   Das ist OK - wir müssen die Parameter anpassen.")
                
                # Zeige die erwarteten Parameter
                print(f"\n📋 Erwartete Parameter für {line_tool.name}:")
                if line_tool.inputSchema:
                    schema = line_tool.inputSchema
                    if "properties" in schema:
                        for param, details in schema["properties"].items():
                            required = param in schema.get("required", [])
                            req_str = " (required)" if required else ""
                            print(f"   • {param}{req_str}: {details.get('description', details.get('type', '?'))}")


async def show_tool_details():
    """Zeigt Details zu ausgewählten Tools."""
    server_params = StdioServerParameters(
        command="npx",
        args=["-y", "@antv/mcp-server-chart"],
    )
    
    print("\n" + "="*60)
    print("📋 Tool-Details (für Viz Agent relevant)")
    print("="*60)
    
    # Tools die wir wahrscheinlich brauchen
    relevant_tools = [
        "generate_line_chart",
        "generate_area_chart", 
        "generate_bar_chart",
        "generate_column_chart",
        "generate_scatter_chart",
    ]
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            
            for tool in tools.tools:
                if tool.name in relevant_tools:
                    print(f"\n🔧 {tool.name}")
                    print(f"   {tool.description[:200] if tool.description else 'Keine Beschreibung'}...")
                    
                    if tool.inputSchema and "properties" in tool.inputSchema:
                        print("   Parameter:")
                        for param, details in tool.inputSchema["properties"].items():
                            desc = details.get("description", details.get("type", ""))
                            if len(desc) > 60:
                                desc = desc[:60] + "..."
                            print(f"     • {param}: {desc}")


async def main():
    """Hauptfunktion - führt alle Tests aus."""
    print("="*60)
    print("🤖 AntV MCP Server Test")
    print("="*60)
    
    try:
        # 1. Tools auflisten
        await list_antv_tools()
        
        # 2. Tool-Details zeigen
        await show_tool_details()
        
        # 3. Einfachen Chart testen
        await test_simple_chart()
        
        print("\n" + "="*60)
        print("✅ Tests abgeschlossen!")
        print("="*60)
        
    except FileNotFoundError:
        print("\n❌ FEHLER: 'npx' nicht gefunden!")
        print("   Bitte Node.js installieren: https://nodejs.org/")
    except Exception as e:
        print(f"\n❌ FEHLER: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
