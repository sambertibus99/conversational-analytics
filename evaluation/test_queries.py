"""
Testfragen für die Evaluation des Conversational Analytics Systems.

20 Testfragen:
- 5 Einfach (E1-E5): Einzelwerte, einfache Abfragen
- 5 Mittel (M1-M5): Mehrere Keys, Vergleiche, Charts
- 5 Komplex (K1-K5): Statistik, Korrelation, Multi-Step
- 5 Abstention (A1-A5): Ungültige Anfragen

Jede Testfrage enthält:
- id: Eindeutige ID
- query: Die Testfrage
- category: einfach/mittel/komplex/abstention
- expected_tools: Erwartete Tool-Aufrufe
- expected_behavior: Beschreibung des erwarteten Verhaltens
- should_abstain: True wenn System ablehnen soll

HINWEIS: 
- energy_period_kwh liefert oft fehlerhafte OPC-UA Daten ("Bad status code")
- Daher verwenden wir für Tests bevorzugt: torque, axis_act, pos_act, vel_act
"""

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class TestQuery:
    """Eine Testfrage für die Evaluation."""
    id: str
    query: str
    category: Literal["einfach", "mittel", "komplex", "abstention"]
    expected_tools: list[str]
    expected_behavior: str
    should_abstain: bool = False
    expected_agents: list[str] = field(default_factory=list)
    notes: str = ""


# =============================================================================
# EINFACHE TESTFRAGEN (E1-E5)
# =============================================================================

EINFACH = [
    TestQuery(
        id="E1",
        query="Wie ist die aktuelle Position von Achse 1?",
        category="einfach",
        expected_tools=["get_latest_telemetry"],
        expected_agents=["data_agent"],
        expected_behavior="Gibt aktuellen Wert von axis_act_a1_deg zurück",
        notes="Einzelwert, kein Chart nötig"
    ),
    TestQuery(
        id="E2",
        query="Zeig mir den Verlauf der Bahngeschwindigkeit der letzten Stunde als Liniendiagramm",
        category="einfach",
        expected_tools=["get_telemetry", "bindData", "bindAxis"],
        expected_agents=["data_agent", "viz_agent"],
        expected_behavior="Liniendiagramm mit vel_act_m_per_s über Zeit",
        notes="Zeitreihe + Chart"
    ),
    TestQuery(
        id="E3",
        query="Wie schwer ist die aktuelle Last am Roboter?",
        category="einfach",
        expected_tools=["get_attributes"],
        expected_agents=["data_agent"],
        expected_behavior="Gibt load_mass_kg Attribut zurück",
        notes="Attribut statt Telemetrie!"
    ),
    TestQuery(
        id="E4",
        query="Was ist das durchschnittliche Drehmoment von Achse 1 am 16. Dezember?",
        category="einfach",
        expected_tools=["get_telemetry"],
        expected_agents=["data_agent", "stats_agent"],
        expected_behavior="Durchschnitt von torque_act_a1_nm für den Tag berechnen",
        notes="Zeitraum: 16.12.2025, Durchschnittsberechnung. GEÄNDERT: war energy_period_kwh (defekte Daten)"
    ),
    TestQuery(
        id="E5",
        query="Läuft der Roboter gerade mit vollem Override?",
        category="einfach",
        expected_tools=["get_latest_telemetry"],
        expected_agents=["data_agent"],
        expected_behavior="Gibt override_pct zurück und interpretiert (100% = voll)",
        notes="Einzelwert mit Interpretation"
    ),
]


# =============================================================================
# MITTLERE TESTFRAGEN (M1-M5)
# =============================================================================

MITTEL = [
    TestQuery(
        id="M1",
        query="Vergleiche die Drehmomente aller 6 Achsen vom 16. Dezember als Diagramm",
        category="mittel",
        expected_tools=["get_telemetry", "bindData", "bindAxis", "bindColor"],
        expected_agents=["data_agent", "viz_agent"],
        expected_behavior="Liniendiagramm mit 6 Linien (torque_act_a1_nm bis a6_nm)",
        notes="Multi-Series Chart"
    ),
    TestQuery(
        id="M2",
        query="Zeig mir die durchschnittliche Achsposition 1 pro Stunde für den 16. Dezember",
        category="mittel",
        expected_tools=["get_telemetry_aggregated"],
        expected_agents=["data_agent", "viz_agent"],
        expected_behavior="Aggregierte Daten mit interval=HOUR, agg=AVG",
        notes="Aggregation statt Rohdaten!"
    ),
    TestQuery(
        id="M3",
        query="Vergleiche das kommandierte und tatsächliche Drehmoment von Achse 3 für den 16. Dezember",
        category="mittel",
        expected_tools=["get_telemetry", "bindData"],
        expected_agents=["data_agent", "viz_agent"],
        expected_behavior="2 Linien: torque_act_a3_nm vs torque_cmd_a3_nm",
        notes="Soll/Ist-Vergleich"
    ),
    TestQuery(
        id="M4",
        query="Zeig mir die Bewegungsbahn des Roboters am 16. Dezember von 10 bis 11 Uhr",
        category="mittel",
        expected_tools=["get_telemetry"],
        expected_agents=["data_agent", "viz_agent"],
        expected_behavior="pos_act_x_mm, pos_act_y_mm, pos_act_z_mm als Scatter/3D",
        notes="3D-Position, komplexe Visualisierung"
    ),
    TestQuery(
        id="M5",
        query="Wie hat sich die Auslastung am 16. Dezember entwickelt?",
        category="mittel",
        expected_tools=["get_telemetry"],
        expected_agents=["data_agent", "viz_agent"],
        expected_behavior="utilization_current über Zeit als Liniendiagramm",
        notes="Auslastungsverlauf"
    ),
]


# =============================================================================
# KOMPLEXE TESTFRAGEN (K1-K5)
# =============================================================================

KOMPLEX = [
    TestQuery(
        id="K1",
        query="Gibt es einen Zusammenhang zwischen Geschwindigkeit und Drehmoment bei Achse 1?",
        category="komplex",
        expected_tools=["get_telemetry", "correlation"],
        expected_agents=["data_agent", "stats_agent", "viz_agent"],
        expected_behavior="Korrelationskoeffizient berechnen, Scatter-Plot erstellen",
        notes="Korrelationsanalyse mit Visualisierung"
    ),
    TestQuery(
        id="K2",
        query="Gab es am 16. Dezember ungewöhnlich hohe Drehmomentspitzen bei Achse 2?",
        category="komplex",
        expected_tools=["get_telemetry", "mean", "std"],
        expected_agents=["data_agent", "stats_agent"],
        expected_behavior="Anomalie-Erkennung: Werte > 2σ über Mittelwert identifizieren",
        notes="Statistik + Interpretation"
    ),
    TestQuery(
        id="K3",
        query="Zeigt das Drehmoment von Achse 1 einen Trend über den 16. Dezember?",
        category="komplex",
        expected_tools=["get_telemetry", "trend"],
        expected_agents=["data_agent", "stats_agent", "viz_agent"],
        expected_behavior="Trendanalyse mit Steigung und Interpretation",
        notes="Zeitreihenanalyse. GEÄNDERT: war energy_period_kwh (defekte Daten)"
    ),
    TestQuery(
        id="K4",
        query="Welche Achse hatte am 16. Dezember die höchste durchschnittliche Belastung?",
        category="komplex",
        expected_tools=["get_telemetry", "mean"],
        expected_agents=["data_agent", "stats_agent"],
        expected_behavior="Mean pro Achse berechnen, Maximum finden",
        notes="Multi-Step: 6 Means berechnen, vergleichen"
    ),
    TestQuery(
        id="K5",
        query="Vergleiche die Roboter-Auslastung vom 12. Dezember mit dem 16. Dezember",
        category="komplex",
        expected_tools=["get_telemetry"],
        expected_agents=["data_agent", "stats_agent", "viz_agent"],
        expected_behavior="Zwei Zeiträume vergleichen, Differenz berechnen",
        notes="Zeitraum-Vergleich"
    ),
]


# =============================================================================
# ABSTENTION TESTFRAGEN (A1-A5)
# =============================================================================

ABSTENTION = [
    TestQuery(
        id="A1",
        query="Zeig mir Daten vom KRC6",
        category="abstention",
        expected_tools=[],
        expected_agents=[],
        expected_behavior="Ablehnung: Nur KRC5 bekannt",
        should_abstain=True,
        notes="Unbekanntes Gerät"
    ),
    TestQuery(
        id="A2",
        query="Wie ist die Temperatur von Motor 1?",
        category="abstention",
        expected_tools=[],
        expected_agents=["data_agent"],
        expected_behavior="Ablehnung: Keine Temperatur-Keys verfügbar",
        should_abstain=True,
        notes="Unbekannter Messwert"
    ),
    TestQuery(
        id="A3",
        query="Setze den Override auf 50%",
        category="abstention",
        expected_tools=[],
        expected_agents=[],
        expected_behavior="Ablehnung: Nur Lesezugriff möglich",
        should_abstain=True,
        notes="Schreibzugriff nicht erlaubt"
    ),
    TestQuery(
        id="A4",
        query="Wie wird sich das Drehmoment morgen entwickeln?",
        category="abstention",
        expected_tools=[],
        expected_agents=[],
        expected_behavior="Ablehnung: Keine Vorhersagen möglich",
        should_abstain=True,
        notes="Zukunftsvorhersage nicht möglich"
    ),
    TestQuery(
        id="A5",
        query="Berechne die Lebensdauer des Roboters",
        category="abstention",
        expected_tools=[],
        expected_agents=[],
        expected_behavior="Ablehnung: Diese Berechnung ist nicht möglich",
        should_abstain=True,
        notes="Unmögliche Berechnung"
    ),
]


# =============================================================================
# ALLE TESTFRAGEN
# =============================================================================

ALL_QUERIES = EINFACH + MITTEL + KOMPLEX + ABSTENTION


def get_queries_by_category(category: str) -> list[TestQuery]:
    """Gibt alle Testfragen einer Kategorie zurück."""
    return [q for q in ALL_QUERIES if q.category == category]


def get_query_by_id(query_id: str) -> TestQuery | None:
    """Gibt eine Testfrage anhand ihrer ID zurück."""
    for q in ALL_QUERIES:
        if q.id == query_id:
            return q
    return None


# =============================================================================
# TEST
# =============================================================================

if __name__ == "__main__":
    print("="*60)
    print("Testfragen für Evaluation")
    print("="*60)
    
    for category in ["einfach", "mittel", "komplex", "abstention"]:
        queries = get_queries_by_category(category)
        print(f"\n{category.upper()} ({len(queries)} Fragen):")
        for q in queries:
            abstain = " [ABSTAIN]" if q.should_abstain else ""
            print(f"  {q.id}: {q.query[:50]}...{abstain}")
    
    print(f"\nGesamt: {len(ALL_QUERIES)} Testfragen")
