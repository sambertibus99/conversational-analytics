"""
Zentraler State für das Multi-Agent System.

Der State wird zwischen allen Agents geteilt und enthält:
- messages: Chat-Verlauf (akkumuliert via add_messages)
- datasets: Geladene Datensätze (akkumuliert via merge_datasets)
- plan: Ausführungsplan vom Supervisor
- statistics: Berechnete Statistiken
- chart_url: URL/Pfad zum generierten Chart

WICHTIG (DEC-013): 
- Checkpointer persistiert State zwischen Turns
- Reducer sorgen dafür, dass Daten akkumuliert statt überschrieben werden

DEC-017: Graph Best Practices
- error_count: Zählt Fehler für Retry-Logik
- max_steps: Cycle Guard gegen Endlosschleifen
"""

from typing import Any, Annotated
from langgraph.graph import MessagesState


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
    
    # === Planung (vom Supervisor) ===
    # Wird pro Turn neu erstellt
    plan: list[str] | None = None
    current_step: int = 0
    reasoning: str | None = None
    
    # === Daten (vom Data Agent) ===
    # AKKUMULIERT über Turns via merge_datasets Reducer
    # Format: {"torque": {"data": [...], "meta": {...}}, "velocity": {...}}
    datasets: Annotated[dict[str, Any], merge_datasets] = {}
    
    # Kurze Zusammenfassung für LLM-Context - AKKUMULIERT
    data_summary: Annotated[str, merge_summaries] = ""
    
    # Pfad zur aktuellen Datendatei (für Viz/Stats Agent)
    # Wird pro Turn überschrieben
    current_data_file: str | None = None
    
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
    should_abstain: bool = False
    abstain_reason: str | None = None
    
    # === Cycle Guard (DEC-017) ===
    max_steps: int = 10  # Maximale Schritte bevor Notfall-Exit
