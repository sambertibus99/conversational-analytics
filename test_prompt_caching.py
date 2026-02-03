"""
Test-Skript für Prompt Caching (DEC-021).

Testet BEIDE Ansätze:
1. Direkte Anthropic SDK (funktioniert immer)
2. LangChain mit list[dict] content (neue Lösung)

Erwartung:
- 1. Call: cache_creation > 0, cache_read = 0
- 2. Call: cache_creation = 0, cache_read > 0
"""

import asyncio
from langchain_core.messages import HumanMessage
from config.settings import create_anthropic_client, create_cached_system_message

# Ein langer System Prompt (muss >1024 Tokens sein für Caching)
LONG_SYSTEM_PROMPT = """
Du bist ein hilfreicher Assistent für IIoT-Datenanalyse.

## Deine Aufgaben
- Analysiere Sensordaten von KUKA Robotern
- Beantworte Fragen zu Telemetriedaten
- Erkläre komplexe Zusammenhänge verständlich

## Verfügbare Datentypen
- Achspositionen (axis_act_a1_deg bis axis_act_a6_deg)
- Kartesische Position (pos_act_x_mm, pos_act_y_mm, pos_act_z_mm)
- Orientierung (pos_act_a_deg, pos_act_b_deg, pos_act_c_deg)
- Drehmomente (torque_act_a1_nm bis torque_act_a6_nm)
- Geschwindigkeiten (vel_act_m_per_s)
- Override und Status (override_pct, pro_state)

## Antwort-Stil
- Kurz und präzise
- Technisch korrekt
- Bei Unklarheit nachfragen

## Wichtige Regeln
1. Nur mit verfügbaren Daten arbeiten
2. Keine Annahmen über fehlende Werte
3. Bei Fehlern höflich informieren
""" * 10  # >1024 Tokens


async def test_langchain_caching():
    print("=" * 60)
    print("TEST: Prompt Caching mit LangChain (list[dict] content)")
    print("=" * 60)

    llm = create_anthropic_client()

    queries = [
        "Was ist 2+2?",
        "Was ist 3+3?",
        "Was ist 4+4?",
    ]

    for i, query in enumerate(queries, 1):
        print(f"\n--- Call {i}: '{query}' ---")

        messages = [
            create_cached_system_message(LONG_SYSTEM_PROMPT),
            HumanMessage(content=query),
        ]

        response = await llm.ainvoke(messages)

        # Response Metadata enthält die Token-Infos
        metadata = response.response_metadata
        usage = metadata.get("usage", {})

        cache_write = usage.get("cache_creation_input_tokens", 0)
        cache_read = usage.get("cache_read_input_tokens", 0)
        input_tokens = usage.get("input_tokens", 0)

        print(f"  Input Tokens:  {input_tokens}")
        print(f"  Cache Write:   {cache_write} {'<-- gecached!' if cache_write > 0 else ''}")
        print(f"  Cache Read:    {cache_read} {'<-- aus Cache!' if cache_read > 0 else ''}")
        print(f"  Antwort:       {response.content[:50]}...")

        await asyncio.sleep(0.5)

    print("\n" + "=" * 60)
    print("ERWARTUNG:")
    print("  Call 1: Cache Write > 0 (System Prompt gecached)")
    print("  Call 2+: Cache Read > 0 (aus Cache gelesen)")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_langchain_caching())
