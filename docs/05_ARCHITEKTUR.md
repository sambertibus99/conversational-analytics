# ARCHITEKTUR

## Übersicht

```
┌─────────────────────────────────────────────────────────────────────┐
│                           USER                                       │
│                      (Chat-Interface)                                │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     CHAINLIT FRONTEND                                │
│                        (app.py)                                      │
│   • Chat-UI                                                          │
│   • Chart-Anzeige                                                    │
│   • Session-Management                                               │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     LANGGRAPH ORCHESTRATION                          │
│                       (agents/graph.py)                              │
│                                                                      │
│   ┌───────────────────────────────────────────────────────────┐     │
│   │                     SUPERVISOR                             │     │
│   │   • Analysiert User-Query                                  │     │
│   │   • Erstellt Plan: ["data_agent", "viz_agent", ...]       │     │
│   │   • Entscheidet welche Tools geladen werden               │     │
│   └─────────────────────────┬─────────────────────────────────┘     │
│                             │                                        │
│              ┌──────────────┼──────────────┐                        │
│              ▼              ▼              ▼                        │
│   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐             │
│   │  DATA AGENT  │  │ STATS AGENT  │  │  VIZ AGENT   │             │
│   │              │  │              │  │              │             │
│   │ ThingsBoard  │  │ Statistik    │  │ AntV/Plotly  │             │
│   │ MCP Tools    │  │ Funktionen   │  │ MCP Tools    │             │
│   │ (9 Tools)    │  │ (8 Tools)    │  │ (25 Tools)   │             │
│   └──────┬───────┘  └──────┬───────┘  └──────┬───────┘             │
│          │                 │                 │                      │
│          └─────────────────┴─────────────────┘                      │
│                            │                                        │
│                            ▼                                        │
│   ┌───────────────────────────────────────────────────────────┐     │
│   │                    SHARED STATE                            │     │
│   │   • messages: List[Message]                               │     │
│   │   • plan: List[str]                                       │     │
│   │   • data: dict | None        ← Daten aus Datei geladen    │     │
│   │   • data_summary: str        ← Kurz für LLM               │     │
│   │   • data_meta: dict          ← Statistiken, Zeitraum      │     │
│   │   • chart_url: str | None    ← Generiertes Chart          │     │
│   └───────────────────────────────────────────────────────────┘     │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Detaillierter Datenfluss

### Beispiel: "Zeig TCP Position von Dienstag 12 Uhr"

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. CHAINLIT (app.py)                                                         │
│    • Empfängt User-Message                                                  │
│    • Erstellt AgentState mit messages=[HumanMessage]                        │
│    • Ruft graph.ainvoke(state) auf                                          │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 2. SUPERVISOR                                                                │
│    INPUT:  state.messages = [HumanMessage("Zeig TCP Position...")]          │
│                                                                              │
│    PROZESS: LLM analysiert → "Zeig" = Viz, "TCP Position" = Daten          │
│                                                                              │
│    OUTPUT: state.plan = ["data_agent", "viz_agent"]                         │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 3. DATA AGENT                                                                │
│                                                                              │
│    ┌──────────────────────────────────────────────────────────────────┐     │
│    │ a) MCP Client startet ThingsBoard Server als Subprocess          │     │
│    │    → python mcp_servers/thingsboard_server.py                    │     │
│    │                                                                  │     │
│    │ b) LLM wählt Tool:                                               │     │
│    │    → get_telemetry(keys="pos_act_x_mm,...", timerange="Di 12h") │     │
│    │                                                                  │     │
│    │ c) MCP Server:                                                   │     │
│    │    → parse_timerange("Dienstag 12 Uhr") → 16.12.2025 11:55-12:05│     │
│    │    → ThingsBoard REST API Call                                   │     │
│    │    → SPEICHERT Rohdaten in: outputs/data/telemetry_xxx.json     │     │
│    │    → Gibt NUR Zusammenfassung zurück (NICHT Rohdaten!)          │     │
│    │                                                                  │     │
│    │ d) Data Agent:                                                   │     │
│    │    → Liest data_file Pfad aus Response                          │     │
│    │    → Lädt Rohdaten aus JSON-Datei                               │     │
│    │    → Speichert in state.data                                    │     │
│    └──────────────────────────────────────────────────────────────────┘     │
│                                                                              │
│    OUTPUT: state.data = {"pos_act_x_mm": [...627 Punkte...], ...}           │
│            state.data_summary = "627 Punkte, Ø 94.5mm, ..."                 │
│            state.data_meta = {statistics: {...}, timerange: {...}}          │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 4. VIZ AGENT                                                                 │
│                                                                              │
│    INPUT: state.data (aus Datei geladen, NICHT nochmal von API!)            │
│           state.messages (NUR HumanMessages! Keine SystemMessages!)         │
│                                                                              │
│    ┌──────────────────────────────────────────────────────────────────┐     │
│    │ a) MCP Client startet AntV Server                                │     │
│    │    → npx -y @antv/mcp-server-chart                               │     │
│    │                                                                  │     │
│    │ b) Daten transformieren:                                         │     │
│    │    ThingsBoard: {"value": "94.5", "timestamp": 123}             │     │
│    │    → AntV:      {"time": "11:55:00", "value": 94.5}             │     │
│    │                                                                  │     │
│    │ c) LLM wählt Chart + ruft Tool auf:                             │     │
│    │    → generate_line_chart(data=[...], title="TCP Position X")    │     │
│    │                                                                  │     │
│    │ d) AntV Server generiert Chart → lädt zu CDN hoch               │     │
│    └──────────────────────────────────────────────────────────────────┘     │
│                                                                              │
│    OUTPUT: state.chart_url = "https://mdn.alipayobjects.com/..."            │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 5. RESPOND NODE → Finale Antwort generieren                                  │
│ 6. CHAINLIT → Text + Chart anzeigen                                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Kritische Datenübergabe-Punkte

### MCP Server → Data Agent (Token-Sparend!)
```python
# MCP Server Response (klein, ~500 Bytes):
{
    "status": "success",
    "statistics": {"pos_act_x_mm": {"avg": 94.5, "min": 94.5, "max": 94.5}},
    "data_file": "/path/to/telemetry_xxx.json",  # ← Pfad zur Datei!
    "timerange": {"start": "16.12.2025 11:55", "end": "16.12.2025 12:05"}
}

# Rohdaten in Datei (groß, ~375KB):
# outputs/data/telemetry_xxx.json
```

### Data Agent → State
```python
# Data Agent lädt Datei und speichert in State:
state.data = load_from_file(response["data_file"])  # Rohdaten
state.data_summary = "627 Punkte, Ø 94.5mm"         # Kurz für LLM
state.data_meta = {"statistics": {...}}             # Metadaten
```

### State → Viz Agent (WICHTIG!)
```python
# Viz Agent liest aus State - NICHT nochmal von API!
data = state["data"]  # ← Bereits geladen!

# NUR HumanMessages übernehmen (keine SystemMessages!)
human_messages = [m for m in state["messages"] if isinstance(m, HumanMessage)]
```

---

## State-Design

```python
class AgentState(MessagesState):
    """Zentraler State zwischen allen Agents."""
    
    # Von LangGraph
    messages: list[BaseMessage]      # Chat-Historie
    
    # Vom Supervisor
    plan: list[str] | None = None    # z.B. ["data_agent", "viz_agent"]
    current_step: int = 0
    
    # Vom Data Agent
    data: dict | None = None         # Rohdaten (aus Datei geladen!)
    data_summary: str | None = None  # Kurze Beschreibung für LLM
    data_meta: dict | None = None    # Statistiken, Zeitraum, Typ
    
    # Vom Viz Agent
    chart_url: str | None = None     # URL zum generierten Chart
    chart_type: str | None = None    # "line", "bar", "scatter"
    
    # Vom Stats Agent
    statistics: dict | None = None   # Berechnete Statistiken
```

---

## Warum diese Architektur?

### Problem: Token-Limit
```
627 Datenpunkte × 6 Keys × ~100 Bytes = ~375 KB
→ Würde LLM-Context sprengen!
```

### Lösung: File-Based Data Storage
```
1. MCP Server speichert Rohdaten in Datei
2. Nur ~500 Bytes Summary an LLM
3. Data Agent lädt Datei in state.data
4. Viz Agent liest aus state.data (nicht nochmal API!)
```

### Warum separate MCP Server?
```
ThingsBoard MCP:  Python-Subprocess, ThingsBoard API, Zeitraum-Parsing
AntV MCP:         Node.js-Subprocess (npx), Chart-Generierung, CDN-Upload
```

---

## Tool-Reduktion

### ThingsBoard: Implementiert 9 von 140 Tools

| Tool | Funktion |
|------|----------|
| `list_devices` | Alle Geräte auflisten |
| `get_device_info` | Gerätedetails |
| `list_telemetry_keys` | Verfügbare Telemetrie-Keys |
| `get_data_availability` | Wann gibt es Daten? |
| `get_latest_telemetry` | Aktuellste Werte |
| `get_telemetry` | Zeitreihe (mit File-Storage!) |
| `get_telemetry_aggregated` | Aggregierte Zeitreihe |
| `get_attributes` | Statische Attribute |
| `list_attribute_keys` | Verfügbare Attribute |

### AntV: Nutzt @antv/mcp-server-chart (25 Tools)

Wichtigste: `generate_line_chart`, `generate_bar_chart`, `generate_scatter_chart`

---

## Error Handling

Siehe `07_ERROR_HANDLING.md` für:
- Bekannte Fehler & Fixes
- MCP Response-Format Standard
- Debugging-Workflow
- Kritische Regeln

---

## Sicherheit

### API Keys
- Alle Keys in `.env`
- Nie im Code, nie in Git

### ThingsBoard
- Nur Lese-Zugriff
- Keine Admin-Tools exponiert

### LLM
- Rohdaten nicht an LLM (Token-Limit + Kosten)
- Data Faithfulness durch Grounding
