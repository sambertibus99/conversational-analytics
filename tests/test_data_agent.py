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

@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_latest_telemetry(cleanup_mcp_after_test):
    """Test: Aktueller Wert abfragen (Integration - braucht ThingsBoard)."""
    state = AgentState(
        messages=[HumanMessage(content="Wie ist die aktuelle Position von Achse 1?")]
    )
    
    result = await run_data_agent(state)
    
    # Keine Fehler
    assert result.get("error") is None, f"Fehler: {result.get('error')}"
    
    # Daten vorhanden
    assert result.get("data") is not None, "Keine Daten erhalten"
    
    # DEC-031: active_dataset_keys statt datasets (DuckDB ist Source of Truth)
    assert result.get("active_dataset_keys"), "Keine active_dataset_keys"

    print(f"✅ Latest Telemetry Test bestanden")
    print(f"   Active Keys: {result.get('active_dataset_keys', [])}")


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_timeseries(cleanup_mcp_after_test):
    """Test: Zeitreihe abfragen - prüft ob Agent korrekt arbeitet (Integration)."""
    state = AgentState(
        messages=[HumanMessage(content="Zeig mir die Bahngeschwindigkeit der letzten 10 Minuten")]
    )
    
    result = await run_data_agent(state)
    
    # Kein Exception-Fehler
    error = result.get("error")
    if error and "429" in str(error):
        pytest.skip("Rate Limit erreicht")
    assert error is None, f"Fehler: {error}"
    
    # Agent muss IRGENDEINE sinnvolle Response geben
    # - Entweder Daten
    # - Oder no_data in meta
    # - Oder "keine" im Summary
    meta = result.get("data_meta") or {}

    has_data = result.get("data") is not None or result.get("active_dataset_keys")
    is_no_data = meta.get("type") == "no_data"

    assert has_data or is_no_data, f"Weder Daten noch no_data. Meta: {meta}"

    print(f"✅ Timeseries Test bestanden")
    print(f"   Active Keys: {result.get('active_dataset_keys', [])}")
    if is_no_data:
        print(f"   (no_data - Roboter war nicht aktiv)")


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio  
async def test_list_keys(cleanup_mcp_after_test):
    """Test: Verfügbare Keys auflisten (Integration - braucht ThingsBoard)."""
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


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_multiple_keys(cleanup_mcp_after_test):
    """Test: Mehrere Keys gleichzeitig (Integration - braucht ThingsBoard)."""
    state = AgentState(
        messages=[HumanMessage(content="Zeig mir Position und Geschwindigkeit von Achse 1 der letzten 5 Minuten")]
    )
    
    result = await run_data_agent(state)
    
    # Rate Limit überspringen
    error = result.get("error")
    if error and "429" in str(error):
        pytest.skip("Rate Limit erreicht")
    assert error is None, f"Fehler: {error}"
    
    # Agent muss IRGENDEINE sinnvolle Response geben
    meta = result.get("data_meta") or {}

    has_data = result.get("data") is not None or result.get("active_dataset_keys")
    is_no_data = meta.get("type") == "no_data"

    assert has_data or is_no_data, f"Weder Daten noch no_data. Meta: {meta}"

    print(f"✅ Multiple Keys Test bestanden")
    print(f"   Active Keys: {result.get('active_dataset_keys', [])}")
    if is_no_data:
        print(f"   (no_data - Roboter war nicht aktiv)")


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
        
        print(f"\n📊 Active Keys: {result.get('active_dataset_keys', [])}")
        
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
            print(f"   Active Keys: {result.get('active_dataset_keys', [])}")
            return True
        
        success = asyncio.run(quick_test())
        sys.exit(0 if success else 1)
