#!/usr/bin/env python3
"""
Direkter Test der Korrelationsanfrage ohne Browser.
Testet die Graph-Pipeline direkt.
"""
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agents.graph import run_query
from config.duckdb_store import SessionStore
import uuid


async def test_correlation_query():
    """Testet Korrelationsanfrage direkt über run_query()."""

    query = "Kannst du mir sagen ob es eine Korrelation zwischen Position und Drehmoment der letzten 40 Minuten gibt?"

    # Session initialisieren
    thread_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    SessionStore.get_instance(session_id)

    print("=" * 80)
    print("DIREKTER PIPELINE-TEST")
    print("=" * 80)
    print(f"Query: {query}")
    print(f"Thread-ID: {thread_id}")
    print(f"Session-ID: {session_id}")
    print("\nStarte Pipeline...\n")

    try:
        result = await run_query(query, thread_id=thread_id, session_id=session_id)

        print("\n" + "=" * 80)
        print("ERGEBNIS")
        print("=" * 80)

        # Response extrahieren (run_query gibt schon "response" Key zurück)
        response = result.get("response", "")

        print(f"Response length: {len(response)} characters")
        print(f"\nResponse:\n{'-' * 80}")
        print(response)
        print('-' * 80)

        # Validierung
        response_lower = response.lower()

        error_keywords = ["fehler aufgetreten", "error", "traceback", "konnte nicht", "tool_use ids without tool_result"]
        has_error = any(kw in response_lower for kw in error_keywords)

        corr_keywords = ["korrelation", "pearson", "spearman", "zusammenhang", "korreliert", "r =", "r=", "ρ =", "ρ="]
        has_correlation = any(kw in response_lower for kw in corr_keywords)

        print(f"\n✓ Checks:")
        print(f"  - Antwort vorhanden: {len(response) > 0}")
        print(f"  - Keine Fehler-Keywords: {not has_error}")
        print(f"  - Hat Korrelations-Keywords: {has_correlation}")

        success = len(response) > 50 and not has_error and has_correlation

        print(f"\n{'✅ TEST BESTANDEN' if success else '❌ TEST FEHLGESCHLAGEN'}")

        # State Details
        if "plan" in result:
            print(f"\nPlan: {result['plan']}")
        if "data_retrieval_mode" in result:
            print(f"Data Retrieval Mode: {result['data_retrieval_mode']}")
        if "datasets" in result:
            print(f"Datasets: {list(result['datasets'].keys())}")
        if "statistics" in result and result["statistics"]:
            print(f"Statistics: {result['statistics'][:200]}...")

        return 0 if success else 1

    except Exception as e:
        print(f"\n❌ FEHLER: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(test_correlation_query())
    sys.exit(exit_code)
