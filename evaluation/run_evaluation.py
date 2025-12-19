"""
Automatisierte Evaluation des Conversational Analytics Systems.

Führt alle 20 Testfragen durch und berechnet Metriken.

Verwendung:
    python evaluation/run_evaluation.py [--category CATEGORY] [--query-id ID] [--alternative]
    
Beispiele:
    python evaluation/run_evaluation.py                    # Alle Tests (Original)
    python evaluation/run_evaluation.py --alternative      # Alternative Tests (Data Contamination frei)
    python evaluation/run_evaluation.py --category einfach # Nur einfache Tests
    python evaluation/run_evaluation.py --query-id E1      # Nur Test E1
    python evaluation/run_evaluation.py --query-id N-E1 --alternative  # Alternativer Test N-E1
"""

import sys
from pathlib import Path

# Projekt-Root zu sys.path hinzufügen
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import asyncio
import json
import argparse
from datetime import datetime
from typing import Any

# Import wird dynamisch basierend auf --alternative gemacht
from evaluation.metrics import (
    TestResult,
    EvaluationMetrics,
    calculate_metrics,
    format_metrics_report,
    evaluate_execution,
    evaluate_tool_selection,
    evaluate_data_faithfulness,
    evaluate_abstention,
)
from agents.graph import run_query


# =============================================================================
# KONFIGURATION
# =============================================================================

# Ausgabe-Verzeichnis
RESULTS_DIR = PROJECT_ROOT / "evaluation" / "results"

# Timeout pro Test (Sekunden)
TEST_TIMEOUT = 120


# =============================================================================
# EVALUATION FUNCTIONS
# =============================================================================

async def run_single_test(query, verbose: bool = True) -> TestResult:
    """
    Führt einen einzelnen Test durch.
    
    Args:
        query: Die Testfrage (TestQuery Objekt)
        verbose: Debug-Ausgaben
        
    Returns:
        TestResult mit allen Ergebnissen
    """
    result = TestResult(
        query_id=query.id,
        query=query.query,
        category=query.category,
        timestamp=datetime.now().isoformat(),
    )
    
    if verbose:
        print(f"\n{'='*60}")
        print(f"Test {query.id}: {query.query[:50]}...")
        print(f"Kategorie: {query.category}")
        print(f"{'='*60}")
    
    start_time = datetime.now()
    
    try:
        # Query ausführen mit Timeout
        graph_result = await asyncio.wait_for(
            run_query(query.query),
            timeout=TEST_TIMEOUT
        )
        
        end_time = datetime.now()
        result.execution_time_ms = int((end_time - start_time).total_seconds() * 1000)
        
        # Ergebnis speichern
        result.success = True
        result.response = graph_result.get("response", "")
        result.plan = graph_result.get("plan", [])
        result.chart_url = graph_result.get("chart_url")
        result.data_summary = graph_result.get("data_summary")
        result.statistics_summary = graph_result.get("statistics_summary")
        result.error = graph_result.get("error")
        
        if verbose:
            print(f"\n📋 Plan: {result.plan}")
            if result.data_summary:
                print(f"📊 Daten: {result.data_summary[:100]}...")
            if result.chart_url:
                print(f"🖼️  Chart: {result.chart_url}")
            print(f"\n🤖 Response:\n{result.response[:300]}...")
        
        # Metriken berechnen
        result.execution_ok = evaluate_execution(graph_result, query.should_abstain)
        result.tools_correct = evaluate_tool_selection(graph_result, query.expected_agents)
        result.data_faithful = evaluate_data_faithfulness(graph_result)
        result.abstained_correctly = evaluate_abstention(graph_result, query.should_abstain)
        
        if verbose:
            print(f"\n📈 Metriken:")
            print(f"   EX (Execution):  {'✅' if result.execution_ok else '❌'}")
            print(f"   TSA (Tools):     {'✅' if result.tools_correct else '❌'}")
            print(f"   DF (Data):       {'✅' if result.data_faithful else '❌'}")
            if query.should_abstain:
                print(f"   AR (Abstention): {'✅' if result.abstained_correctly else '❌'}")
        
    except asyncio.TimeoutError:
        result.success = False
        result.error = f"Timeout nach {TEST_TIMEOUT}s"
        result.execution_ok = False
        if verbose:
            print(f"\n❌ Timeout nach {TEST_TIMEOUT}s")
    
    except Exception as e:
        result.success = False
        result.error = str(e)
        result.execution_ok = False
        if verbose:
            print(f"\n❌ Fehler: {str(e)}")
            import traceback
            traceback.print_exc()
    
    if verbose:
        print(f"\n⏱️  Zeit: {result.execution_time_ms}ms")
    
    return result


async def run_evaluation(
    queries: list,  # TestQuery Liste
    verbose: bool = True,
    save_results: bool = True,
    test_set_name: str = "original",
) -> tuple[list[TestResult], EvaluationMetrics]:
    """
    Führt die komplette Evaluation durch.
    
    Args:
        queries: Liste der Testfragen
        verbose: Debug-Ausgaben
        save_results: Ergebnisse speichern
        test_set_name: Name des Testsets (für Dateinamen)
        
    Returns:
        Tuple aus (Einzelergebnisse, Aggregierte Metriken)
    """
    print("\n" + "="*70)
    print("🧪 CONVERSATIONAL ANALYTICS - AUTOMATISCHE EVALUATION")
    print("="*70)
    print(f"Testset: {test_set_name}")
    print(f"Anzahl Tests: {len(queries)}")
    print(f"Zeitstempel: {datetime.now().isoformat()}")
    print("="*70)
    
    results = []
    
    for i, query in enumerate(queries, 1):
        print(f"\n[{i}/{len(queries)}] Starte Test {query.id}...")
        
        result = await run_single_test(query, verbose=verbose)
        results.append(result)
        
        # Kurze Pause zwischen Tests
        await asyncio.sleep(1)
    
    # Metriken berechnen
    metrics = calculate_metrics(results)
    
    # Report ausgeben
    print("\n" + format_metrics_report(metrics))
    
    # Ergebnisse speichern
    if save_results:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # JSON-Ergebnisse
        results_file = RESULTS_DIR / f"results_{test_set_name}_{timestamp}.json"
        results_data = {
            "timestamp": datetime.now().isoformat(),
            "total_tests": len(results),
            "metrics": {
                "execution_accuracy": metrics.execution_accuracy,
                "tool_selection_accuracy": metrics.tool_selection_accuracy,
                "data_faithfulness": metrics.data_faithfulness,
                "abstention_rate": metrics.abstention_rate,
            },
            "results": [
                {
                    "query_id": r.query_id,
                    "query": r.query,
                    "category": r.category,
                    "success": r.success,
                    "error": r.error,
                    "response": r.response,
                    "plan": r.plan,
                    "chart_url": r.chart_url,
                    "execution_ok": r.execution_ok,
                    "tools_correct": r.tools_correct,
                    "data_faithful": r.data_faithful,
                    "abstained_correctly": r.abstained_correctly,
                    "execution_time_ms": r.execution_time_ms,
                }
                for r in results
            ],
        }
        
        with open(results_file, "w", encoding="utf-8") as f:
            json.dump(results_data, f, indent=2, ensure_ascii=False)
        print(f"\n📁 Ergebnisse gespeichert: {results_file}")
        
        # Markdown-Report
        report_file = RESULTS_DIR / f"analysis_{test_set_name}_{timestamp}.md"
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(generate_markdown_report(results, metrics))
        print(f"📄 Report gespeichert: {report_file}")
    
    return results, metrics


def generate_markdown_report(results: list[TestResult], metrics: EvaluationMetrics) -> str:
    """
    Generiert einen Markdown-Report für die Masterarbeit.
    
    Args:
        results: Liste der Testergebnisse
        metrics: Aggregierte Metriken
        
    Returns:
        Markdown-formatierter Report
    """
    lines = []
    
    # Header
    lines.append("# Evaluation Report: Conversational Analytics System")
    lines.append("")
    lines.append(f"**Zeitstempel:** {metrics.evaluation_timestamp}")
    lines.append(f"**Anzahl Tests:** {metrics.total_tests}")
    lines.append("")
    
    # Zusammenfassung
    lines.append("## Zusammenfassung")
    lines.append("")
    lines.append("| Metrik | Wert | Ziel | Status |")
    lines.append("|--------|------|------|--------|")
    
    ex_status = "✅" if metrics.execution_accuracy >= 80 else "❌"
    lines.append(f"| Execution Accuracy (EX) | {metrics.execution_accuracy:.1f}% | >80% | {ex_status} |")
    
    tsa_status = "✅" if metrics.tool_selection_accuracy >= 90 else "❌"
    lines.append(f"| Tool Selection (TSA) | {metrics.tool_selection_accuracy:.1f}% | >90% | {tsa_status} |")
    
    df_status = "✅" if metrics.data_faithfulness >= 100 else "⚠️"
    lines.append(f"| Data Faithfulness (DF) | {metrics.data_faithfulness:.1f}% | 100% | {df_status} |")
    
    ar_status = "✅" if metrics.abstention_rate >= 80 else "❌"
    lines.append(f"| Abstention Rate (AR) | {metrics.abstention_rate:.1f}% | >80% | {ar_status} |")
    
    lines.append("")
    
    # Nach Kategorie
    lines.append("## Ergebnisse nach Kategorie")
    lines.append("")
    
    for category in ["einfach", "mittel", "komplex", "abstention"]:
        cat_results = [r for r in results if r.category == category]
        if not cat_results:
            continue
        
        lines.append(f"### {category.capitalize()}")
        lines.append("")
        lines.append("| ID | Query | Plan | EX | TSA | DF | AR | Zeit |")
        lines.append("|----|-------|------|----|----|----|----|------|")
        
        for r in cat_results:
            plan_str = " → ".join(r.plan) if r.plan else "-"
            ex = "✅" if r.execution_ok else "❌"
            tsa = "✅" if r.tools_correct else "❌"
            df = "✅" if r.data_faithful else "❌"
            ar = "✅" if r.abstained_correctly else ("❌" if r.abstained_correctly is False else "-")
            
            query_short = r.query[:40] + "..." if len(r.query) > 40 else r.query
            lines.append(f"| {r.query_id} | {query_short} | {plan_str[:30]} | {ex} | {tsa} | {df} | {ar} | {r.execution_time_ms}ms |")
        
        lines.append("")
    
    # Detaillierte Ergebnisse
    lines.append("## Detaillierte Ergebnisse")
    lines.append("")
    
    for r in results:
        lines.append(f"### {r.query_id}: {r.query}")
        lines.append("")
        lines.append(f"**Kategorie:** {r.category}")
        lines.append(f"**Plan:** {r.plan}")
        lines.append(f"**Zeit:** {r.execution_time_ms}ms")
        lines.append("")
        
        if r.error:
            lines.append(f"**Fehler:** {r.error}")
            lines.append("")
        
        lines.append("**Response:**")
        lines.append(f"```")
        lines.append(r.response[:500] + ("..." if len(r.response) > 500 else ""))
        lines.append(f"```")
        lines.append("")
        
        if r.chart_url:
            lines.append(f"**Chart:** {r.chart_url}")
            lines.append("")
        
        lines.append("---")
        lines.append("")
    
    # Fazit
    lines.append("## Fazit")
    lines.append("")
    
    all_passed = (
        metrics.execution_accuracy >= 80 and
        metrics.tool_selection_accuracy >= 90 and
        metrics.data_faithfulness >= 100 and
        metrics.abstention_rate >= 80
    )
    
    if all_passed:
        lines.append("✅ **Alle Zielwerte wurden erreicht!**")
    else:
        lines.append("⚠️ **Nicht alle Zielwerte wurden erreicht.**")
        lines.append("")
        if metrics.execution_accuracy < 80:
            lines.append(f"- EX: {metrics.execution_accuracy:.1f}% < 80% (Ziel verfehlt)")
        if metrics.tool_selection_accuracy < 90:
            lines.append(f"- TSA: {metrics.tool_selection_accuracy:.1f}% < 90% (Ziel verfehlt)")
        if metrics.data_faithfulness < 100:
            lines.append(f"- DF: {metrics.data_faithfulness:.1f}% < 100% (Ziel verfehlt)")
        if metrics.abstention_rate < 80:
            lines.append(f"- AR: {metrics.abstention_rate:.1f}% < 80% (Ziel verfehlt)")
    
    return "\n".join(lines)


# =============================================================================
# MAIN
# =============================================================================

async def main():
    """Hauptfunktion für CLI-Ausführung."""
    parser = argparse.ArgumentParser(
        description="Automatische Evaluation des Conversational Analytics Systems"
    )
    parser.add_argument(
        "--category",
        choices=["einfach", "mittel", "komplex", "abstention"],
        help="Nur Tests einer bestimmten Kategorie ausführen"
    )
    parser.add_argument(
        "--query-id",
        help="Nur einen bestimmten Test ausführen (z.B. E1, M3, K5, N-E1)"
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Weniger Ausgaben"
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Ergebnisse nicht speichern"
    )
    parser.add_argument(
        "--alternative",
        action="store_true",
        help="Alternative Testfragen verwenden (Data Contamination frei)"
    )
    
    args = parser.parse_args()
    
    # Testfragen-Modul dynamisch laden
    if args.alternative:
        from evaluation.test_queries_alternative import (
            ALL_QUERIES,
            get_queries_by_category,
            get_query_by_id,
        )
        print("\n🔄 Verwende ALTERNATIVE Testfragen (Data Contamination frei)")
    else:
        from evaluation.test_queries import (
            ALL_QUERIES,
            get_queries_by_category,
            get_query_by_id,
        )
        print("\n📝 Verwende ORIGINAL Testfragen")
    
    # Queries auswählen
    if args.query_id:
        query = get_query_by_id(args.query_id)
        if not query:
            print(f"❌ Unbekannte Query-ID: {args.query_id}")
            print(f"   Verfügbar: {[q.id for q in ALL_QUERIES]}")
            return
        queries = [query]
    elif args.category:
        queries = get_queries_by_category(args.category)
    else:
        queries = ALL_QUERIES
    
    # Evaluation starten
    test_set_name = "alternative" if args.alternative else "original"
    await run_evaluation(
        queries=queries,
        verbose=not args.quiet,
        save_results=not args.no_save,
        test_set_name=test_set_name,
    )


if __name__ == "__main__":
    asyncio.run(main())
