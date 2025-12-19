"""
ALTERNATIVE Testfragen für die Evaluation des Conversational Analytics Systems.

Diese Testfragen sind UNABHÄNGIG von den Beispielen in den System-Prompts,
um Data Contamination zu vermeiden.

20 Testfragen:
- 5 Einfach (N-E1 bis N-E5): Einzelwerte, einfache Abfragen
- 5 Mittel (N-M1 bis N-M5): Mehrere Keys, Vergleiche, Charts
- 5 Komplex (N-K1 bis N-K5): Statistik, Korrelation, Multi-Step
- 5 Abstention (N-A1 bis N-A5): Ungültige Anfragen

WICHTIG: Zeitangaben sind RELATIV formuliert ("letzten Dienstag", "vorgestern")
damit die Tests unabhängig vom aktuellen Datum funktionieren!
"""

from dataclasses import dataclass, field
from typing import Literal
from datetime import datetime, timedelta


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


def get_last_weekday(weekday: int) -> str:
    """
    Gibt das Datum des letzten Wochentags zurück.
    0=Montag, 1=Dienstag, ..., 6=Sonntag
    
    Returns:
        z.B. "Dienstag den 16. Dezember"
    """
    weekday_names = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
    month_names = ["", "Januar", "Februar", "März", "April", "Mai", "Juni", 
                   "Juli", "August", "September", "Oktober", "November", "Dezember"]
    
    today = datetime.now()
    days_ago = (today.weekday() - weekday) % 7
    if days_ago == 0:
        days_ago = 7  # Letzten gleichen Wochentag, nicht heute
    
    target = today - timedelta(days=days_ago)
    return f"{weekday_names[weekday]} den {target.day}. {month_names[target.month]}"


def get_date_days_ago(days: int) -> str:
    """Gibt ein Datum X Tage in der Vergangenheit zurück."""
    month_names = ["", "Januar", "Februar", "März", "April", "Mai", "Juni", 
                   "Juli", "August", "September", "Oktober", "November", "Dezember"]
    target = datetime.now() - timedelta(days=days)
    return f"{target.day}. {month_names[target.month]}"


# =============================================================================
# EINFACHE TESTFRAGEN (N-E1 bis N-E5)
# Verwenden "letzten Daten" statt "aktuell" wegen Datenalter
# =============================================================================

EINFACH = [
    TestQuery(
        id="N-E1",
        query="Wo befindet sich der TCP des Roboters laut den letzten Daten?",
        category="einfach",
        expected_tools=["get_latest_telemetry"],
        expected_agents=["data_agent"],
        expected_behavior="Gibt pos_act_x_mm, pos_act_y_mm, pos_act_z_mm zurück",
        notes="TCP statt Achse, 'letzten Daten' vermeidet Datums-Verwirrung"
    ),
    TestQuery(
        id="N-E2",
        query="Zeige die Geschwindigkeitswerte vom letzten Dienstag als Diagramm",
        category="einfach",
        expected_tools=["get_telemetry"],
        expected_agents=["data_agent", "viz_agent"],
        expected_behavior="vel_act_m_per_s für letzten Dienstag als Chart",
        notes="Relativer Wochentag statt hartkodiertes Datum"
    ),
    TestQuery(
        id="N-E3",
        query="Liste alle verfügbaren Telemetrie-Keys auf",
        category="einfach",
        expected_tools=["list_telemetry_keys"],
        expected_agents=["data_agent"],
        expected_behavior="Liste aller verfügbaren Telemetrie-Keys",
        notes="Explizit 'Telemetrie-Keys' um Verwechslung mit Attributen zu vermeiden"
    ),
    TestQuery(
        id="N-E4",
        query="Was war die letzte gemessene Bahngeschwindigkeit?",
        category="einfach",
        expected_tools=["get_latest_telemetry"],
        expected_agents=["data_agent"],
        expected_behavior="Letzter Wert von vel_act_m_per_s",
        notes="'letzte gemessene' statt 'momentan' - klar dass historisch"
    ),
    TestQuery(
        id="N-E5",
        query="Welchen Winkel hat Achse 4 laut den aktuellsten Daten?",
        category="einfach",
        expected_tools=["get_latest_telemetry"],
        expected_agents=["data_agent"],
        expected_behavior="Letzter Wert von axis_act_a4_deg",
        notes="Achse 4 statt 1, 'aktuellsten Daten' = get_latest"
    ),
]


# =============================================================================
# MITTLERE TESTFRAGEN (N-M1 bis N-M5)
# Relative Zeitangaben: "letzten Donnerstag", "letzten Freitag"
# =============================================================================

MITTEL = [
    TestQuery(
        id="N-M1",
        query="Erstelle ein Balkendiagramm mit den Maximalwerten der Drehmomente aller Achsen vom letzten Donnerstag",
        category="mittel",
        expected_tools=["get_telemetry", "bindData"],
        expected_agents=["data_agent", "stats_agent", "viz_agent"],
        expected_behavior="Balkendiagramm (nicht Linie!) mit Max-Werten pro Achse",
        notes="Balkendiagramm, relativer Wochentag"
    ),
    TestQuery(
        id="N-M2",
        query="Wie veränderte sich die X-Koordinate des TCP am letzten Freitag?",
        category="mittel",
        expected_tools=["get_telemetry"],
        expected_agents=["data_agent", "viz_agent"],
        expected_behavior="pos_act_x_mm über Zeit für letzten Freitag",
        notes="Relativer Wochentag, nur X-Koordinate"
    ),
    TestQuery(
        id="N-M3",
        query="Stelle die Roboterbewegung vom letzten Dienstag von 14 bis 15 Uhr als Scatter-Plot dar",
        category="mittel",
        expected_tools=["get_telemetry"],
        expected_agents=["data_agent", "viz_agent"],
        expected_behavior="Scatter-Plot mit X/Y oder X/Y/Z Koordinaten",
        notes="Scatter-Plot statt Liniendiagramm, spezifische Uhrzeit"
    ),
    TestQuery(
        id="N-M4",
        query="Zeige mir die Orientierung (A, B, C Winkel) des Roboters vom letzten Dienstag",
        category="mittel",
        expected_tools=["get_telemetry"],
        expected_agents=["data_agent", "viz_agent"],
        expected_behavior="pos_act_a_deg, pos_act_b_deg, pos_act_c_deg als Multi-Line Chart",
        notes="Orientierung statt Position, A/B/C statt X/Y/Z"
    ),
    TestQuery(
        id="N-M5",
        query="Vergleiche Achse 5 mit Achse 6 vom letzten Donnerstag in einem Diagramm",
        category="mittel",
        expected_tools=["get_telemetry"],
        expected_agents=["data_agent", "viz_agent"],
        expected_behavior="Zwei Linien für axis_act_a5_deg und axis_act_a6_deg",
        notes="Achsen 5+6 statt 1-6, relativer Wochentag"
    ),
]


# =============================================================================
# KOMPLEXE TESTFRAGEN (N-K1 bis N-K5)
# Statistische Analysen mit relativen Zeitangaben
# =============================================================================

KOMPLEX = [
    TestQuery(
        id="N-K1",
        query="Wie stark schwankt das Drehmoment von Achse 4 am letzten Dienstag?",
        category="komplex",
        expected_tools=["get_telemetry", "std"],
        expected_agents=["data_agent", "stats_agent"],
        expected_behavior="Standardabweichung von torque_act_a4_nm berechnen und interpretieren",
        notes="Standardabweichung statt Mean, Achse 4"
    ),
    TestQuery(
        id="N-K2",
        query="In welchem Wertebereich lag die Bahngeschwindigkeit am letzten Dienstag?",
        category="komplex",
        expected_tools=["get_telemetry", "min_max", "percentiles"],
        expected_agents=["data_agent", "stats_agent"],
        expected_behavior="Min, Max und evtl. Perzentile von vel_act_m_per_s",
        notes="Min/Max/Range statt Mean/Trend"
    ),
    TestQuery(
        id="N-K3",
        query="Bewegen sich Achse 2 und Achse 3 am letzten Dienstag synchron?",
        category="komplex",
        expected_tools=["get_telemetry", "correlation"],
        expected_agents=["data_agent", "stats_agent", "viz_agent"],
        expected_behavior="Korrelation zwischen axis_act_a2_deg und axis_act_a3_deg",
        notes="Korrelation zwischen Achsen"
    ),
    TestQuery(
        id="N-K4",
        query="Zu welcher Uhrzeit war die Geschwindigkeit am letzten Dienstag am höchsten?",
        category="komplex",
        expected_tools=["get_telemetry"],
        expected_agents=["data_agent", "stats_agent"],
        expected_behavior="Maximum von vel_act_m_per_s finden und Timestamp zurückgeben",
        notes="Zeitpunkt-Suche"
    ),
    TestQuery(
        id="N-K5",
        query="Welche der 6 Achsen zeigt am letzten Dienstag die größte Schwankung im Drehmoment?",
        category="komplex",
        expected_tools=["get_telemetry", "std"],
        expected_agents=["data_agent", "stats_agent"],
        expected_behavior="Std für alle 6 torque_act Werte berechnen, Maximum finden",
        notes="Multi-Achsen Vergleich mit Std"
    ),
]


# =============================================================================
# ABSTENTION TESTFRAGEN (N-A1 bis N-A5)
# Ungültige Anfragen - unabhängig vom Datum
# =============================================================================

ABSTENTION = [
    TestQuery(
        id="N-A1",
        query="Zeige mir die Daten von Roboter 2",
        category="abstention",
        expected_tools=[],
        expected_agents=[],
        expected_behavior="Ablehnung: Nur KRC5 (Roboter 1) verfügbar",
        should_abstain=True,
        notes="Falscher Roboter"
    ),
    TestQuery(
        id="N-A2",
        query="Lösche alle Messwerte von letzter Woche",
        category="abstention",
        expected_tools=[],
        expected_agents=[],
        expected_behavior="Ablehnung: Nur Lesezugriff, keine Löschung möglich",
        should_abstain=True,
        notes="Schreibzugriff (Löschen)"
    ),
    TestQuery(
        id="N-A3",
        query="Wie war die Position vor 3 Monaten?",
        category="abstention",
        expected_tools=[],
        expected_agents=["data_agent"],
        expected_behavior="Ablehnung: Daten nur für letzte Woche verfügbar",
        should_abstain=True,
        notes="Zeitraum außerhalb Datenverfügbarkeit"
    ),
    TestQuery(
        id="N-A4",
        query="Wann muss der Roboter gewartet werden?",
        category="abstention",
        expected_tools=[],
        expected_agents=[],
        expected_behavior="Ablehnung: Wartungsvorhersage nicht möglich",
        should_abstain=True,
        notes="Predictive Maintenance nicht implementiert"
    ),
    TestQuery(
        id="N-A5",
        query="Fahre den Roboter auf Position X=500mm",
        category="abstention",
        expected_tools=[],
        expected_agents=[],
        expected_behavior="Ablehnung: Keine Steuerung möglich, nur Lesezugriff",
        should_abstain=True,
        notes="Schreibzugriff (Roboter steuern)"
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
# INFO
# =============================================================================

INFO = """
WICHTIGE ÄNDERUNGEN:
- Alle Datumsangaben sind jetzt RELATIV ("letzten Dienstag" statt "16. Dezember")
- Das System interpretiert "letzten Dienstag" als den Dienstag vor dem aktuellen Tag
- Dadurch funktionieren die Tests unabhängig vom Ausführungsdatum
- "letzte Daten" statt "aktuell/momentan" vermeidet Verwirrung über Datenalter

BEKANNTE DATENVERFÜGBARKEIT (Stand Dezember 2025):
- ThingsBoard hat Daten ca. 11.12. bis 16.12.2025
- "Letzten Dienstag" = 16.12. (wenn Test am 19.12. läuft)
- "Letzten Donnerstag" = 12.12.
- "Letzten Freitag" = 13.12.
"""


# =============================================================================
# TEST
# =============================================================================

if __name__ == "__main__":
    print("="*60)
    print("ALTERNATIVE Testfragen für Evaluation")
    print("="*60)
    print(f"\nAktuelles Datum: {datetime.now().strftime('%d.%m.%Y (%A)')}")
    print(f"Letzter Dienstag: {get_last_weekday(1)}")
    print(f"Letzter Donnerstag: {get_last_weekday(3)}")
    print(f"Letzter Freitag: {get_last_weekday(4)}")
    
    for category in ["einfach", "mittel", "komplex", "abstention"]:
        queries = get_queries_by_category(category)
        print(f"\n{category.upper()} ({len(queries)} Fragen):")
        for q in queries:
            abstain = " [ABSTAIN]" if q.should_abstain else ""
            print(f"  {q.id}: {q.query[:55]}...{abstain}")
    
    print(f"\nGesamt: {len(ALL_QUERIES)} Testfragen")
