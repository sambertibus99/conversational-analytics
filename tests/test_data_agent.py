"""
Tests für den Data Agent.

Testet verschiedene Query-Typen und prüft:
- Tool Selection Accuracy (TSA)
- Data Extraction
- Error Handling
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import asyncio
import pytest
from langchain_core.messages import HumanMessage, AIMessage

from agents.state import AgentState
from agents.data_agent import run_data_agent


# =============================================================================
# TEST CASES
# =============================================================================

@pytest.mark.asyncio
async def test_latest_telemetry():
    """Test: Aktueller Wert abfragen."""
    state = AgentState(
        messages=[HumanMessage(content="Wie ist die aktuelle Position von Achse 1?")]
    )
    
    result = await run_data_agent(state)
    
    # Keine Fehler
    assert result.get("error") is None, f"Fehler: {result.get('error')}"
    
    # Daten vorhanden
    assert result.get("data") is not None, "Keine Daten erhalten"
    
    # Summary vorhanden
    assert result.get("data_summary") is not None, "Keine Summary"
    
    print(f"✅ Latest Telemetry Test bestanden")
    print(f"   Summary: {result['data_summary']}")


@pytest.mark.asyncio
async def test_timeseries():
    """Test: Zeitreihe abfragen."""
    state = AgentState(
        messages=[HumanMessage(content="Zeig mir die Bahngeschwindigkeit der letzten 10 Minuten")]
    )
    
    result = await run_data_agent(state)
    
    assert result.get("error") is None, f"Fehler: {result.get('error')}"
    assert result.get("data") is not None, "Keine Daten erhalten"
    
    # Meta sollte data_points enthalten
    meta = result.get("data_meta", {})
    assert meta.get("data_points") is not None, "Keine Datenpunkt-Info"
    
    print(f"✅ Timeseries Test bestanden")
    print(f"   Summary: {result['data_summary']}")


@pytest.mark.asyncio  
async def test_list_keys():
    """Test: Verfügbare Keys auflisten."""
    state = AgentState(
        messages=[HumanMessage(content="Welche Telemetrie-Keys sind verfügbar?")]
    )
    
    result = await run_data_agent(state)
    
    assert result.get("error") is None, f"Fehler: {result.get('error')}"
    assert result.get("data") is not None, "Keine Daten erhalten"
    
    # Sollte eine Liste sein
    data = result.get("data")
    assert isinstance(data, list), f"Erwarte Liste, bekam {type(data)}"
    assert len(data) > 0, "Leere Liste"
    
    print(f"✅ List Keys Test bestanden")
    print(f"   {len(data)} Keys gefunden")


@pytest.mark.asyncio
async def test_multiple_keys():
    """Test: Mehrere Keys gleichzeitig."""
    state = AgentState(
        messages=[HumanMessage(content="Zeig mir Position und Geschwindigkeit von Achse 1 der letzten 5 Minuten")]
    )
    
    result = await run_data_agent(state)
    
    assert result.get("error") is None, f"Fehler: {result.get('error')}"
    
    print(f"✅ Multiple Keys Test bestanden")
    print(f"   Summary: {result.get('data_summary', 'N/A')}")


# =============================================================================
# MANUAL TEST
# =============================================================================

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
        
        print(f"\n📊 Summary: {result.get('data_summary', 'N/A')}")
        
        if result.get("error"):
            print(f"❌ Error: {result['error']}")
        
        if result.get("data_meta"):
            print(f"📈 Meta: {result['data_meta']}")
        
        # Letzte AI Message
        for msg in reversed(result.get("messages", [])):
            if isinstance(msg, AIMessage):
                content = msg.content
                if isinstance(content, str):
                    # Kürzen wenn zu lang
                    if len(content) > 500:
                        content = content[:500] + "..."
                    print(f"\n🤖 Agent:\n{content}")
                break
        
        print("\n" + "-"*40)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--interactive":
        asyncio.run(interactive_test())
    else:
        # Einzelnen Quick-Test ausführen
        print("🧪 Running quick test...")
        
        async def quick_test():
            state = AgentState(
                messages=[HumanMessage(content="Wie ist die aktuelle Position von Achse 1?")]
            )
            result = await run_data_agent(state)
            
            if result.get("error"):
                print(f"❌ Fehler: {result['error']}")
                return False
            
            print(f"✅ Test erfolgreich!")
            print(f"   Summary: {result.get('data_summary', 'N/A')}")
            return True
        
        success = asyncio.run(quick_test())
        sys.exit(0 if success else 1)
