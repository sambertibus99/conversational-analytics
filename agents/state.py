"""
Zentraler State für das Multi-Agent System.

Der State wird zwischen allen Agents geteilt und enthält:
- messages: Chat-Verlauf (akkumuliert via add_messages)
- datasets: DatasetMeta-Referenzen (akkumuliert via merge_datasets)
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

DEC-025: Reference-only State — Rohdaten in DuckDB, nur Metadaten im State
- datasets enthält nur noch DatasetMeta (kein "data" Key mehr)
- Rohdaten werden über SessionStore (DuckDB) abgefragt
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


def merge_datasets(existing: dict[str, Any] | None, new: dict[str, Any] | None) -> dict[str, Any]:
    """
    Reducer für datasets: Merged neue Datensätze in bestehende.
    
    Beispiel:
        existing = {"torque": {...}, "velocity": {...}}
        new = {"position": {...}}
        result = {"torque": {...}, "velocity": {...}, "position": {...}}
    
    Bei gleichem Key wird der neue Wert genommen (Update).
    """
    if existing is None and new is None:
        return {}
    if existing is None:
        return new or {}
    if new is None:
        return existing
    
    # Merge: existing + new (new überschreibt bei Konflikt)
    return {**existing, **new}


def merge_summaries(existing: str | None, new: str | None) -> str:
    """
    Reducer für data_summary: Kombiniert Zusammenfassungen.
    
    Beispiel:
        existing = "Drehmomente: 210 Punkte"
        new = "Geschwindigkeit: 35 Punkte"
        result = "Drehmomente: 210 Punkte | Geschwindigkeit: 35 Punkte"
    """
    if existing is None and new is None:
        return ""
    if existing is None or existing == "":
        return new or ""
    if new is None or new == "":
        return existing
    
    # Kombiniere mit Separator, vermeide Duplikate
    existing_parts = set(existing.split(" | "))
    new_parts = set(new.split(" | "))
    combined = existing_parts | new_parts
    return " | ".join(sorted(combined))


class AgentState(MessagesState):
    """
    Gemeinsamer State für alle Agents.
    
    Erbt von MessagesState, das bereits `messages: list[BaseMessage]` enthält
    mit add_messages Reducer (akkumuliert automatisch).
    
    WICHTIG: 
    - datasets und data_summary haben Reducer → akkumulieren über Turns
    - Andere Felder werden überschrieben (plan, chart_url, etc.)
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
    
    # === Daten (vom Data Agent) ===
    # AKKUMULIERT über Turns via merge_datasets Reducer
    # DEC-025: Nur noch DatasetMeta (Referenzen), Rohdaten in DuckDB SessionStore
    # Format: {"krc5/torque/timeseries/2h": DatasetMeta, ...}
    datasets: Annotated[dict[str, Any], merge_datasets] = {}
    
    # DEPRECATED (DEC-029): Wird für Supervisor durch turn_history ersetzt.
    # Bleibt aktiv für respond_node und Backward-Compat.
    data_summary: Annotated[str, merge_summaries] = ""
    
    # === Turn History (DEC-029) ===
    # Strukturierte Zusammenfassungen vergangener Turns für Supervisor-Kontext
    turn_history: Annotated[list[dict], append_turn_history] = []

    # === Aktive Dataset-Keys für den aktuellen Turn (DEC-026/028) ===
    # Wird vom Data Agent gesetzt (basierend auf check_dataset + get_telemetry).
    # Supervisor resettet auf None am Turn-Anfang, Data Agent setzt neu.
    # Viz/Stats Agents lesen nur Daten für diese Keys.
    # None = alle Daten (Fallback)
    active_dataset_keys: list[str] | None = None
    
    # === Statistiken (vom Stats Agent) ===
    statistics: dict[str, Any] | None = None
    statistics_summary: str | None = None
    
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
