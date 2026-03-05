"""
Zentraler State für das Multi-Agent System.

Der State wird zwischen allen Agents geteilt und enthält:
- messages: Chat-Verlauf (akkumuliert via add_messages)
- plan: Ausführungsplan vom Supervisor
- statistics: Berechnete Statistiken
- chart_url: URL/Pfad zum generierten Chart

WICHTIG (DEC-013):
- Checkpointer persistiert State zwischen Turns
- Reducer sorgen dafür, dass Daten akkumuliert statt überschrieben werden

DEC-017: Graph Best Practices
- error_count: Zählt Fehler für Retry-Logik
- max_steps: Cycle Guard gegen Endlosschleifen

DEC-023: Query-Typ-basierte Datenstrategie
- data_retrieval_mode: "detail" für Stats, "overview" für Viz

DEC-025/031: DuckDB als Single Source of Truth
- DatasetMeta liegt ausschließlich in DuckDB dataset_meta Tabelle
- Rohdaten in DuckDB telemetry Tabelle
- Zugriff über get_dataset_meta_from_duckdb() in agents/utils.py

DEC-030: Stats-Ergebnisse als persistente DuckDB-Datasets
- active_stats_keys: Analog zu active_dataset_keys, aber für Stats-Ergebnisse
- Stats Agent speichert Ergebnisse in DuckDB statistics-Tabelle
"""

from typing import Any, Annotated, TypedDict
from langgraph.graph import MessagesState


class TurnDataset(TypedDict, total=False):
    """Ein Dataset-Block im TurnEntry, gruppiert nach Zeitraum (DEC-029)."""
    keys: list[str]             # ["torque_act_a1_nm", "torque_act_a2_nm"]
    timerange: str              # "04.02.2026 14:20 - 15:00"


class TurnEntry(TypedDict, total=False):
    """Strukturierte Zusammenfassung eines Turns für den Supervisor-Kontext (DEC-029)."""
    user_query: str             # "Korrelation Moment/Position, 3 Achsen..."
    plan: list[str]             # ["data_agent", "stats_agent"]
    data_mode: str              # "detail" | "overview"
    datasets: list[TurnDataset] # Gruppiert nach Zeitraum
    result_type: str            # "data" | "chart" | "statistics" | "error" | "abstention" | "clarification"
    result_summary: str         # "Korrelation: A1 r=0.012, A2 r=-0.617"
    key_facts: list[dict]       # DEC-034: Strukturierte Stats-Findings für Cross-Turn-Referenzen


def append_turn_history(existing: list | None, new: list | None) -> list:
    """Reducer für turn_history: Hängt neue Einträge an, max 20 behalten (DEC-029)."""
    existing = existing or []
    if new is None:
        return existing
    return (existing + new)[-20:]


class DatasetMeta(TypedDict, total=False):
    """
    Metadaten-Referenz für ein Dataset in DuckDB (DEC-025).

    Ersetzt das bisherige {"data": {...}, "meta": {...}} Format.
    Rohdaten liegen in SessionStore, der State hält nur Referenzen.

    Beispiel:
        {
            "dataset_key": "krc5/torque/timeseries/2h",
            "device_id": "krc5",
            "keys": ["torque_act_a1_nm", "torque_act_a2_nm"],
            "point_count": 627,
            "timerange": {"start": "12:00", "end": "14:00"},
            "retrieval_mode": "overview",
            "unit": "Nm",
            "created_at": "2025-12-16T12:00:00",
            "data_file": "/tmp/telemetry_xxx.json",
            "meta": {"type": "success", "statistics": {...}},
        }
    """
    dataset_key: str          # UNS-Key: "krc5/torque/timeseries/2h"
    device_id: str
    keys: list[str]           # Signal-Keys: ["torque_act_a1_nm", ...]
    point_count: int
    timerange: dict           # {"start": ..., "end": ...}
    retrieval_mode: str       # "detail" | "overview"
    unit: str
    created_at: str           # ISO 8601
    data_file: str | None     # Backup-Pfad (optional, DEC-004)
    meta: dict                # Originale Meta-Daten vom MCP Server



class AgentState(MessagesState):
    """
    Gemeinsamer State für alle Agents.
    
    Erbt von MessagesState, das bereits `messages: list[BaseMessage]` enthält
    mit add_messages Reducer (akkumuliert automatisch).
    
    WICHTIG:
    - turn_history hat Reducer → akkumuliert über Turns
    - Andere Felder werden überschrieben (plan, chart_url, etc.)
    - DEC-031: DatasetMeta liegt in DuckDB, nicht mehr im State
    """
    
    # === DuckDB Session (DEC-025) ===
    # Wird von app.py gesetzt, korrespondiert zur Chat-Session
    session_id: str = "default"

    # === Planung (vom Supervisor) ===
    # Wird pro Turn neu erstellt
    plan: list[str] | None = None
    current_step: int = 0
    reasoning: str | None = None

    # === Daten-Retrieval-Modus (DEC-023) ===
    # "detail" für Stats/Korrelation (mehr Punkte), "overview" für Viz (Standard)
    data_retrieval_mode: str = "overview"

    # === Data Instructions (vom Supervisor an Data Agent) ===
    # Konkrete Anweisungen was der Data Agent laden soll
    data_instructions: str | None = None

    # === Viz Instructions (vom Supervisor an Viz Agent) ===
    # Konkrete Anweisungen was der Viz Agent visualisieren soll (Chart-Typ, Achsen, Keys)
    viz_instructions: str | None = None

    # === Viz Data Source (Supervisor → Viz Agent) ===
    # "timeseries" = Zeitreihen aus telemetry-Tabelle (active_dataset_keys)
    # "stats" = Statistik-Ergebnisse aus statistics-Tabelle (active_stats_keys)
    # "auto" = Bisheriges Verhalten (Stats > Timeseries)
    viz_data_source: str = "auto"

    # === Stats Instructions (vom Supervisor an Stats Agent) ===
    # Konkrete Anweisungen welche Analysen der Stats Agent durchführen soll
    stats_instructions: str | None = None

    # === Turn History (DEC-029) ===
    # Strukturierte Zusammenfassungen vergangener Turns für Supervisor-Kontext
    turn_history: Annotated[list[dict], append_turn_history] = []

    # === Aktive Dataset-Keys für den aktuellen Turn (DEC-026/028) ===
    # Wird vom Data Agent gesetzt (basierend auf check_dataset + get_telemetry).
    # Supervisor resettet auf None am Turn-Anfang, Data Agent setzt neu.
    # Viz/Stats Agents lesen nur Daten für diese Keys.
    # None = alle Daten (Fallback)
    active_dataset_keys: list[str] | None = None
    
    # === Aktive Stats-Dataset-Keys für den aktuellen Turn (DEC-030) ===
    # Getrennt von active_dataset_keys (nur Telemetrie).
    # Stats Agent setzt nach Berechnung, Supervisor kann im Folge-Turn setzen.
    # None = keine Stats-Daten aktiv
    active_stats_keys: list[str] | None = None

    # === Data Agent Text-Antwort (für nicht-DuckDB Ergebnisse) ===
    # Gesetzt wenn der Data Agent Text-Ergebnisse liefert die nicht in DuckDB landen:
    # Attribute (get_attributes, list_attribute_keys), Key-Listings, Geräte-Infos etc.
    data_response: str | None = None

    # === Statistiken (vom Stats Agent) ===
    statistics: dict[str, Any] | None = None
    statistics_summary: str | None = None

    # === Stats Findings für Cross-Turn-Referenzen (DEC-034) ===
    # Strukturierte Erkenntnisse vom Stats Agent mit Datensatz-Kontext.
    # Wird pro Turn überschrieben, wandert dann in turn_history.
    stats_findings: list[dict] | None = None

    # === Agent Signals (strukturiertes Feedback für Supervisor EVAL/Replan) ===
    # Agents schreiben Warnungen/Fehler mit Kontext und Handlungsempfehlung.
    # Pro Turn überschrieben (kein Reducer — manuelle Akkumulation via read-append).
    agent_signals: list[dict] | None = None
    
    # === Visualisierung (vom Viz Agent) ===
    chart_url: str | None = None
    chart_type: str | None = None
    
    # === Pipeline-Control ===
    # Wenn True: Pipeline STOPPEN und auf User-Input warten
    needs_user_input: bool = False
    # Grund warum User-Input benötigt wird
    user_input_reason: str | None = None
    
    # === Error Handling (DEC-017) ===
    error: str | None = None
    error_count: int = 0  # Anzahl aufgetretener Fehler
    # === Cycle Guard (DEC-017) ===
    max_steps: int = 10  # Maximale Schritte bevor Notfall-Exit

    # === Replan-Loop (DEC-032) ===
    pending_goals: list[str] | None = None   # Offene Ziele nach Phase
    replan_count: int = 0                     # Anzahl bisheriger Replans
    replan_context: dict | None = None        # Snapshot der vorherigen Phase
