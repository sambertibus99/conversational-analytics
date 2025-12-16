"""
Zentraler State für das Multi-Agent System.

Der State wird zwischen allen Agents geteilt und enthält:
- messages: Chat-Verlauf
- plan: Ausführungsplan vom Supervisor
- data: Rohdaten von ThingsBoard (fließen NICHT durch LLM)
- data_summary: Kurze Zusammenfassung für LLM
- statistics: Berechnete Statistiken
- chart_url: URL/Pfad zum generierten Chart
"""

from typing import Any, Literal
from langgraph.graph import MessagesState


class AgentState(MessagesState):
    """
    Gemeinsamer State für alle Agents.
    
    Erbt von MessagesState, das bereits `messages: list[BaseMessage]` enthält.
    
    WICHTIG: Große Daten (data, statistics) fließen durch State,
    NICHT durch den LLM-Context. Das spart Tokens!
    """
    
    # === Planung (vom Supervisor) ===
    plan: list[str] | None = None
    current_step: int = 0
    
    # === Daten (vom Data Agent) ===
    # Rohdaten - werden DIREKT befüllt, gehen nicht durch LLM
    data: dict[str, Any] | None = None
    # Metadaten über die Daten
    data_meta: dict[str, Any] | None = None
    # Kurze Zusammenfassung für LLM-Context
    data_summary: str | None = None
    
    # === Statistiken (vom Stats Agent) ===
    statistics: dict[str, Any] | None = None
    statistics_summary: str | None = None
    
    # === Visualisierung (vom Viz Agent) ===
    chart_url: str | None = None
    chart_type: str | None = None
    
    # === Error Handling ===
    error: str | None = None
    should_abstain: bool = False
    abstain_reason: str | None = None
