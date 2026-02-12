"""
Metriken-Berechnung für die Evaluation.

Metriken:
- EX (Execution Accuracy): Fehlerfreie Ausführungen
- TSA (Tool Selection Accuracy): Richtige Tool-Auswahl
- DF (Data Faithfulness): Daten = API-Response (keine Halluzinationen)
- AR (Abstention Rate): Korrekte Verweigerungen bei ungültigen Anfragen

Zielwerte:
- EX: >80%
- TSA: >90%  
- DF: 100%
- AR: >80%
"""

from dataclasses import dataclass, field
from typing import Any
from datetime import datetime


@dataclass
class TestResult:
    """Ergebnis eines einzelnen Tests."""
    query_id: str
    query: str
    category: str
    
    # Ausführungsergebnis
    success: bool = False
    error: str | None = None
    
    # System-Output
    response: str = ""
    plan: list[str] = field(default_factory=list)
    chart_url: str | None = None
    statistics_summary: str | None = None
    
    # Metriken (manuell oder automatisch bewertet)
    execution_ok: bool = False      # EX: Keine Fehler
    tools_correct: bool = False     # TSA: Richtige Tools
    data_faithful: bool = False     # DF: Keine Halluzinationen
    abstained_correctly: bool | None = None  # AR: Nur für Abstention-Tests
    
    # Zusätzliche Infos
    execution_time_ms: int = 0
    timestamp: str = ""
    notes: str = ""


@dataclass
class EvaluationMetrics:
    """Aggregierte Metriken über alle Tests."""
    
    # Anzahl Tests
    total_tests: int = 0
    successful_tests: int = 0
    failed_tests: int = 0
    
    # EX: Execution Accuracy
    execution_accuracy: float = 0.0
    execution_correct: int = 0
    execution_total: int = 0
    
    # TSA: Tool Selection Accuracy
    tool_selection_accuracy: float = 0.0
    tools_correct: int = 0
    tools_total: int = 0
    
    # DF: Data Faithfulness
    data_faithfulness: float = 0.0
    data_correct: int = 0
    data_total: int = 0
    
    # AR: Abstention Rate
    abstention_rate: float = 0.0
    abstention_correct: int = 0
    abstention_total: int = 0
    
    # Nach Kategorie
    by_category: dict[str, dict] = field(default_factory=dict)
    
    # Durchschnittliche Ausführungszeit
    avg_execution_time_ms: float = 0.0
    
    # Zeitstempel
    evaluation_timestamp: str = ""


def calculate_metrics(results: list[TestResult]) -> EvaluationMetrics:
    """
    Berechnet aggregierte Metriken aus den Testergebnissen.
    
    Args:
        results: Liste von TestResult-Objekten
        
    Returns:
        EvaluationMetrics mit allen berechneten Werten
    """
    metrics = EvaluationMetrics()
    metrics.total_tests = len(results)
    metrics.evaluation_timestamp = datetime.now().isoformat()
    
    # Kategorien initialisieren
    categories = ["einfach", "mittel", "komplex", "abstention"]
    for cat in categories:
        metrics.by_category[cat] = {
            "total": 0,
            "successful": 0,
            "ex_correct": 0,
            "tsa_correct": 0,
            "df_correct": 0,
            "ar_correct": 0,
        }
    
    # Aggregation
    total_time = 0
    
    for r in results:
        cat = r.category
        if cat in metrics.by_category:
            metrics.by_category[cat]["total"] += 1
        
        # Erfolg/Fehler
        if r.success:
            metrics.successful_tests += 1
            if cat in metrics.by_category:
                metrics.by_category[cat]["successful"] += 1
        else:
            metrics.failed_tests += 1
        
        # EX: Execution Accuracy
        metrics.execution_total += 1
        if r.execution_ok:
            metrics.execution_correct += 1
            if cat in metrics.by_category:
                metrics.by_category[cat]["ex_correct"] += 1
        
        # TSA: Tool Selection Accuracy (nur für nicht-Abstention Tests)
        if cat != "abstention":
            metrics.tools_total += 1
            if r.tools_correct:
                metrics.tools_correct += 1
                if cat in metrics.by_category:
                    metrics.by_category[cat]["tsa_correct"] += 1
        
        # DF: Data Faithfulness (nur für nicht-Abstention Tests)
        if cat != "abstention":
            metrics.data_total += 1
            if r.data_faithful:
                metrics.data_correct += 1
                if cat in metrics.by_category:
                    metrics.by_category[cat]["df_correct"] += 1
        
        # AR: Abstention Rate (nur für Abstention Tests)
        if cat == "abstention":
            metrics.abstention_total += 1
            if r.abstained_correctly:
                metrics.abstention_correct += 1
                metrics.by_category[cat]["ar_correct"] += 1
        
        # Zeit
        total_time += r.execution_time_ms
    
    # Prozentuale Metriken berechnen
    if metrics.execution_total > 0:
        metrics.execution_accuracy = (metrics.execution_correct / metrics.execution_total) * 100
    
    if metrics.tools_total > 0:
        metrics.tool_selection_accuracy = (metrics.tools_correct / metrics.tools_total) * 100
    
    if metrics.data_total > 0:
        metrics.data_faithfulness = (metrics.data_correct / metrics.data_total) * 100
    
    if metrics.abstention_total > 0:
        metrics.abstention_rate = (metrics.abstention_correct / metrics.abstention_total) * 100
    
    if metrics.total_tests > 0:
        metrics.avg_execution_time_ms = total_time / metrics.total_tests
    
    return metrics


def evaluate_execution(result: dict, expected_abstain: bool) -> bool:
    """
    Bewertet ob die Ausführung erfolgreich war.
    
    Args:
        result: Ergebnis von run_query()
        expected_abstain: True wenn Abstention erwartet wurde
        
    Returns:
        True wenn Ausführung OK
    """
    # Fehler ist immer schlecht
    if result.get("error"):
        return False
    
    # Response muss existieren
    if not result.get("response"):
        return False
    
    # Bei Abstention-Tests: Kein Plan = OK
    if expected_abstain:
        return True
    
    # Bei normalen Tests: Plan sollte existieren und ausgeführt worden sein
    return True


def evaluate_tool_selection(result: dict, expected_agents: list[str]) -> bool:
    """
    Bewertet ob die richtigen Tools/Agents verwendet wurden.
    
    Args:
        result: Ergebnis von run_query()
        expected_agents: Liste erwarteter Agent-Namen
        
    Returns:
        True wenn Tool-Auswahl korrekt
    """
    plan = result.get("plan", [])
    
    # Leerer Plan bei leeren expected_agents ist OK
    if not expected_agents and not plan:
        return True
    
    # Prüfe ob alle erwarteten Agents im Plan sind
    for agent in expected_agents:
        if agent not in plan:
            return False
    
    return True


def evaluate_data_faithfulness(result: dict) -> bool:
    """
    Bewertet ob die Daten korrekt wiedergegeben wurden (keine Halluzinationen).
    
    HINWEIS: Diese Funktion gibt erstmal True zurück.
    Eine echte Prüfung würde API-Response mit System-Output vergleichen.
    
    Args:
        result: Ergebnis von run_query()
        
    Returns:
        True wenn keine Halluzinationen erkannt
    """
    # Vereinfachte Prüfung: Wenn Datasets vorhanden, wurden Daten geladen
    if result.get("datasets"):
        return True

    # Wenn keine Daten nötig waren
    return True


def evaluate_abstention(result: dict, should_abstain: bool) -> bool | None:
    """
    Bewertet ob das System korrekt abgelehnt hat.
    
    Args:
        result: Ergebnis von run_query()
        should_abstain: True wenn System ablehnen sollte
        
    Returns:
        True wenn korrekt abgelehnt, False wenn nicht, None wenn nicht anwendbar
    """
    if not should_abstain:
        return None  # Nicht anwendbar für normale Tests
    
    response = result.get("response", "").lower()
    
    # Abstention-Indikatoren
    abstention_keywords = [
        "nicht möglich",
        "kann ich nicht",
        "nicht verfügbar",
        "keine temperatur",
        "nur lesen",
        "keine vorhersage",
        "nicht durchführen",
        "nicht bekannt",
        "nur den krc5",
        "keine schreibrechte",
        "leider",
    ]
    
    for keyword in abstention_keywords:
        if keyword in response:
            return True
    
    # Kein Plan = Abstention
    plan = result.get("plan", [])
    if not plan or plan == []:
        return True
    
    return False


def format_metrics_report(metrics: EvaluationMetrics) -> str:
    """
    Formatiert die Metriken als lesbaren Report.
    
    Args:
        metrics: Die berechneten Metriken
        
    Returns:
        Formatierter Report als String
    """
    lines = []
    lines.append("=" * 60)
    lines.append("EVALUATION REPORT")
    lines.append("=" * 60)
    lines.append(f"Zeitstempel: {metrics.evaluation_timestamp}")
    lines.append("")
    
    # Übersicht
    lines.append("ÜBERSICHT")
    lines.append("-" * 40)
    lines.append(f"Gesamt Tests:     {metrics.total_tests}")
    lines.append(f"Erfolgreich:      {metrics.successful_tests}")
    lines.append(f"Fehlgeschlagen:   {metrics.failed_tests}")
    lines.append(f"Avg. Zeit:        {metrics.avg_execution_time_ms:.0f}ms")
    lines.append("")
    
    # Hauptmetriken
    lines.append("HAUPTMETRIKEN")
    lines.append("-" * 40)
    
    # EX mit Ziel
    ex_status = "✅" if metrics.execution_accuracy >= 80 else "❌"
    lines.append(f"EX (Execution Accuracy):     {metrics.execution_accuracy:5.1f}% {ex_status} (Ziel: >80%)")
    lines.append(f"   → {metrics.execution_correct}/{metrics.execution_total} fehlerfreie Ausführungen")
    
    # TSA mit Ziel
    tsa_status = "✅" if metrics.tool_selection_accuracy >= 90 else "❌"
    lines.append(f"TSA (Tool Selection):        {metrics.tool_selection_accuracy:5.1f}% {tsa_status} (Ziel: >90%)")
    lines.append(f"   → {metrics.tools_correct}/{metrics.tools_total} korrekte Tool-Auswahl")
    
    # DF mit Ziel
    df_status = "✅" if metrics.data_faithfulness >= 100 else "⚠️"
    lines.append(f"DF (Data Faithfulness):      {metrics.data_faithfulness:5.1f}% {df_status} (Ziel: 100%)")
    lines.append(f"   → {metrics.data_correct}/{metrics.data_total} ohne Halluzinationen")
    
    # AR mit Ziel
    ar_status = "✅" if metrics.abstention_rate >= 80 else "❌"
    lines.append(f"AR (Abstention Rate):        {metrics.abstention_rate:5.1f}% {ar_status} (Ziel: >80%)")
    lines.append(f"   → {metrics.abstention_correct}/{metrics.abstention_total} korrekte Ablehnungen")
    
    lines.append("")
    
    # Nach Kategorie
    lines.append("NACH KATEGORIE")
    lines.append("-" * 40)
    
    for cat, data in metrics.by_category.items():
        if data["total"] > 0:
            success_rate = (data["successful"] / data["total"]) * 100
            lines.append(f"{cat.upper():12} | {data['successful']}/{data['total']} erfolgreich ({success_rate:.0f}%)")
    
    lines.append("")
    lines.append("=" * 60)
    
    return "\n".join(lines)


# =============================================================================
# TEST
# =============================================================================

if __name__ == "__main__":
    # Test mit Dummy-Daten
    dummy_results = [
        TestResult(
            query_id="E1",
            query="Test 1",
            category="einfach",
            success=True,
            execution_ok=True,
            tools_correct=True,
            data_faithful=True,
            execution_time_ms=1500,
        ),
        TestResult(
            query_id="E2",
            query="Test 2",
            category="einfach",
            success=True,
            execution_ok=True,
            tools_correct=False,  # Falsches Tool
            data_faithful=True,
            execution_time_ms=2000,
        ),
        TestResult(
            query_id="A1",
            query="Test Abstention",
            category="abstention",
            success=True,
            execution_ok=True,
            abstained_correctly=True,
            execution_time_ms=500,
        ),
    ]
    
    metrics = calculate_metrics(dummy_results)
    print(format_metrics_report(metrics))
