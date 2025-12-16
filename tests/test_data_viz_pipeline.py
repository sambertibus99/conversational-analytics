"""
Test: Data Agent → Viz Agent Pipeline

Testet die komplette Pipeline:
1. Data Agent holt Daten von ThingsBoard
2. Viz Agent erstellt Visualisierung

Ausführen:
    python tests/test_data_viz_pipeline.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import asyncio
from langchain_core.messages import HumanMessage, AIMessage

from agents.state import AgentState
from agents.data_agent import run_data_agent
from agents.viz_agent import run_viz_agent


async def test_pipeline(query: str, viz_instruction: str = "Zeig das als Liniendiagramm"):
    """
    Testet die Data → Viz Pipeline.
    
    Args:
        query: Datenanfrage an Data Agent
        viz_instruction: Visualisierungsanweisung an Viz Agent
    """
    print("\n" + "="*70)
    print(f"📝 Query: {query}")
    print("="*70)
    
    # === SCHRITT 1: Daten laden ===
    print("\n1️⃣  DATA AGENT")
    print("-"*40)
    
    data_state = AgentState(
        messages=[HumanMessage(content=query)]
    )
    
    data_result = await run_data_agent(data_state)
    
    print(f"   Summary: {data_result.get('data_summary', 'N/A')}")
    print(f"   Meta: {data_result.get('data_meta', 'N/A')}")
    
    if data_result.get("error"):
        print(f"   ❌ Error: {data_result['error']}")
        return None
    
    if not data_result.get("data"):
        print("   ❌ Keine Daten erhalten")
        return None
    
    # Daten-Vorschau
    data = data_result["data"]
    if isinstance(data, dict):
        for key in list(data.keys())[:2]:
            values = data[key]
            if isinstance(values, list):
                print(f"   {key}: {len(values)} Punkte")
                if values:
                    print(f"      Beispiel: {values[0]}")
    
    # === SCHRITT 2: Visualisieren ===
    print(f"\n2️⃣  VIZ AGENT")
    print("-"*40)
    print(f"   Anweisung: {viz_instruction}")
    
    viz_state = AgentState(
        messages=[
            HumanMessage(content=query),
            AIMessage(content=data_result.get("data_summary", "Daten geladen")),
            HumanMessage(content=viz_instruction),
        ],
        data=data_result.get("data"),
        data_summary=data_result.get("data_summary"),
        data_meta=data_result.get("data_meta"),
    )
    
    viz_result = await run_viz_agent(viz_state)
    
    if viz_result.get("chart_url"):
        print(f"\n   ✅ Chart generiert!")
        print(f"   📊 Typ: {viz_result.get('chart_type', 'unbekannt')}")
        print(f"   🔗 URL: {viz_result['chart_url']}")
        return viz_result["chart_url"]
    else:
        print(f"\n   ❌ Kein Chart generiert")
        if viz_result.get("error"):
            print(f"   Error: {viz_result['error']}")
        return None


async def main():
    """Führt verschiedene Pipeline-Tests durch."""
    
    print("="*70)
    print("🤖 Data → Viz Pipeline Test")
    print("="*70)
    
    test_cases = [
        # (Data Query, Viz Instruction)
        (
            "Hole die Achsposition 1 der letzten 5 Minuten",
            "Zeig das als Liniendiagramm"
        ),
        (
            "Hole die Bahngeschwindigkeit der letzten 10 Minuten",
            "Erstelle ein Liniendiagramm mit Titel 'Roboter-Geschwindigkeit'"
        ),
        # Dieser Test braucht zwei Keys für Scatter
        # (
        #     "Hole Achsposition 1 und 2 der letzten 5 Minuten",
        #     "Zeig die Korrelation als Scatter-Plot"
        # ),
    ]
    
    results = []
    
    for query, viz_instruction in test_cases:
        try:
            url = await test_pipeline(query, viz_instruction)
            results.append(("✅" if url else "❌", query[:40], url or "Fehler"))
        except Exception as e:
            print(f"\n❌ Exception: {e}")
            import traceback
            traceback.print_exc()
            results.append(("❌", query[:40], str(e)))
    
    # Zusammenfassung
    print("\n" + "="*70)
    print("📋 ZUSAMMENFASSUNG")
    print("="*70)
    
    for status, query, result in results:
        print(f"\n{status} {query}...")
        if result.startswith("http"):
            print(f"   {result}")
        else:
            print(f"   {result[:60]}")


if __name__ == "__main__":
    asyncio.run(main())
