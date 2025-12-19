"""
Evaluation-Modul für das Conversational Analytics System.

Enthält:
- test_queries.py: 20 Original-Testfragen (15 funktional + 5 Abstention)
- test_queries_alternative.py: 20 Alternative Testfragen (Data Contamination frei)
- metrics.py: Metriken-Berechnung (EX, TSA, DF, AR)
- run_evaluation.py: Automatisierte Durchführung

Verwendung:
    # Original-Testfragen (wie in Prompts als Beispiele)
    python evaluation/run_evaluation.py
    
    # Alternative Testfragen (Data Contamination frei)
    python evaluation/run_evaluation.py --alternative
"""

from evaluation.test_queries import (
    TestQuery,
    ALL_QUERIES,
    EINFACH,
    MITTEL,
    KOMPLEX,
    ABSTENTION,
    get_queries_by_category,
    get_query_by_id,
)

from evaluation.test_queries_alternative import (
    ALL_QUERIES as ALT_ALL_QUERIES,
    EINFACH as ALT_EINFACH,
    MITTEL as ALT_MITTEL,
    KOMPLEX as ALT_KOMPLEX,
    ABSTENTION as ALT_ABSTENTION,
    get_queries_by_category as get_alt_queries_by_category,
    get_query_by_id as get_alt_query_by_id,
)

from evaluation.metrics import (
    TestResult,
    EvaluationMetrics,
    calculate_metrics,
    format_metrics_report,
)

__all__ = [
    # Original Testfragen
    "TestQuery",
    "ALL_QUERIES",
    "EINFACH",
    "MITTEL",
    "KOMPLEX",
    "ABSTENTION",
    "get_queries_by_category",
    "get_query_by_id",
    # Alternative Testfragen
    "ALT_ALL_QUERIES",
    "ALT_EINFACH",
    "ALT_MITTEL",
    "ALT_KOMPLEX",
    "ALT_ABSTENTION",
    "get_alt_queries_by_category",
    "get_alt_query_by_id",
    # Metriken
    "TestResult",
    "EvaluationMetrics",
    "calculate_metrics",
    "format_metrics_report",
]
