# SYSTEM-ARCHITEKTUR: Datenfluss im Detail

## Übersicht: Was passiert im Hintergrund?

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              USER QUERY                                      │
│                   "Zeig TCP Position von Dienstag 12 Uhr"                   │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           1. CHAINLIT (app.py)                               │
│                                                                              │
│  • Empfängt User-Message                                                    │
│  • Erstellt AgentState mit messages=[HumanMessage]                          │
│  • Ruft graph.ainvoke(state) auf                                            │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        2. SUPERVISOR (graph.py)                              │
│                                                                              │
│  INPUT:  state.messages = [HumanMessage("Zeig TCP Position...")]            │
│                                                                              │
│  PROZESS:                                                                    │
│  • LLM analysiert Query                                                     │
│  • Erkennt: "Zeig" → Visualisierung, "TCP Position" → Daten                │
│  • Erstellt Plan: ["data_agent", "viz_agent"]                               │
│                                                                              │
│  OUTPUT: state.plan = ["data_agent", "viz_agent"]                           │
│          state.current_step = 0                                             │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        3. DATA AGENT (data_agent.py)                         │
│                                                                              │
│  INPUT:  state.messages, state.plan                                         │
│                                                                              │
│  PROZESS:                                                                    │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │ a) MCP Client startet ThingsBoard MCP Server als Subprocess        │     │
│  │    → python mcp_servers/thingsboard_server.py                      │     │
│  │                                                                    │     │
│  │ b) Tools werden geladen (9 Tools)                                  │     │
│  │    → list_devices, get_telemetry, get_data_availability, ...      │     │
│  │                                                                    │     │
│  │ c) LLM (Claude) entscheidet welches Tool zu nutzen                │     │
│  │    → Wählt: get_telemetry(keys="pos_act_x_mm,...",                │     │
│  │             timerange="Dienstag 12 Uhr")                          │     │
│  │                                                                    │     │
│  │ d) MCP Server führt Tool aus:                                      │     │
│  │    → parse_timerange("Dienstag 12 Uhr")                           │     │
│  │      → Berechnet: 16.12.2025 11:55 - 12:05                        │     │
│  │    → ThingsBoard REST API Call                                     │     │
│  │    → Speichert Daten in: outputs/data/telemetry_xxx.json          │     │
│  │    → Gibt NUR Zusammenfassung zurück (nicht Rohdaten!)            │     │
│  │                                                                    │     │
│  │ e) Data Agent extrahiert Ergebnis:                                │     │
│  │    → Liest data_file aus Response                                 │     │
│  │    → Lädt Rohdaten aus JSON-Datei                                 │     │
│  │    → Speichert in state.data                                      │     │
│  └────────────────────────────────────────────────────────────────────┘     │
│                                                                              │
│  OUTPUT: state.data = {                                                     │
│            "pos_act_x_mm": [{"value": "94.5", "timestamp": 123}, ...],      │
│            "pos_act_y_mm": [...], ...                                       │
│          }                                                                  │
│          state.data_summary = "627 Datenpunkte für pos_act_x_mm..."        │
│          state.data_meta = {statistics: {...}, timerange: {...}}           │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         4. VIZ AGENT (viz_agent.py)                          │
│                                                                              │
│  INPUT:  state.data (Rohdaten aus Datei!)                                   │
│          state.data_summary                                                 │
│          state.messages (nur HumanMessages!)                                │
│                                                                              │
│  PROZESS:                                                                    │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │ a) MCP Client startet AntV MCP Server als Subprocess               │     │
│  │    → npx -y @antv/mcp-server-chart                                 │     │
│  │                                                                    │     │
│  │ b) Tools werden geladen (25 Chart-Tools)                           │     │
│  │    → generate_line_chart, generate_bar_chart, ...                 │     │
│  │                                                                    │     │
│  │ c) Daten werden transformiert:                                     │     │
│  │    ThingsBoard-Format → AntV-Format                                │     │
│  │    {"value": "94.5", "timestamp": 123}                            │     │
│  │    → {"time": "11:55:00", "value": 94.5}                          │     │
│  │                                                                    │     │
│  │ d) LLM wählt Chart-Typ und ruft Tool auf:                         │     │
│  │    → generate_line_chart(data=[...], title="TCP Position X...")   │     │
│  │                                                                    │     │
│  │ e) AntV Server generiert Chart:                                    │     │
│  │    → Rendert SVG/PNG                                               │     │
│  │    → Lädt zu CDN hoch                                              │     │
│  │    → Gibt URL zurück                                               │     │
│  └────────────────────────────────────────────────────────────────────┘     │
│                                                                              │
│  OUTPUT: state.chart_url = "https://mdn.alipayobjects.com/..."              │
│          state.chart_type = "line"                                          │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        5. RESPOND NODE (graph.py)                            │
│                                                                              │
│  INPUT:  state.data_summary                                                 │
│          state.chart_url                                                    │
│          state.messages (alle bisherigen)                                   │
│                                                                              │
│  PROZESS:                                                                    │
│  • LLM generiert finale Antwort basierend auf allen Informationen          │
│  • Kombiniert Daten-Zusammenfassung + Chart-URL                            │
│                                                                              │
│  OUTPUT: Finale AIMessage für den User                                      │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           6. CHAINLIT (app.py)                               │
│                                                                              │
│  • Extrahiert chart_url aus State                                           │
│  • Zeigt Text-Antwort an                                                    │
│  • Zeigt Chart als Bild an (cl.Image)                                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Kritische Datenübergabe-Punkte

### 1. User → Supervisor
```
messages: [HumanMessage(content="...")]
```

### 2. Supervisor → Agents
```
plan: ["data_agent", "viz_agent"]
current_step: 0
```

### 3. MCP Server → Data Agent
```
Tool Response (JSON):
{
  "status": "success" | "no_data",
  "statistics": {...},
  "data_file": "/path/to/file.json"  ← Pfad zur Datei!
}
```

### 4. Data Agent → State
```
data: {...}              ← Rohdaten aus Datei geladen
data_summary: "..."      ← Kurze Beschreibung
data_meta: {...}         ← Statistiken, Zeitraum
```

### 5. State → Viz Agent
```
# KRITISCH: Viz Agent liest data aus State!
# Er holt NICHT nochmal von ThingsBoard!
data = state["data"]
```

### 6. Viz Agent → State
```
chart_url: "https://..."
chart_type: "line"
```

### 7. State → Respond Node
```
# Alle Infos zusammen:
data_summary + chart_url + messages
```

---

## Wichtige Design-Entscheidungen

### Warum Daten in Datei speichern?
```
PROBLEM:  627 Datenpunkte × 6 Keys × ~100 Bytes = ~375 KB
          → Würde LLM-Context sprengen (Token-Limit!)
          
LÖSUNG:   MCP Server speichert in Datei
          → Nur ~500 Bytes Zusammenfassung an LLM
          → Data Agent lädt Datei in state.data
          → Viz Agent liest aus state.data
```

### Warum separate MCP Server?
```
ThingsBoard MCP:  Läuft als Python-Subprocess
                  Hat Zugriff auf ThingsBoard API
                  Kennt Domain-spezifische Logik (Zeitraum-Parsing)

AntV MCP:         Läuft als Node.js-Subprocess (npx)
                  Generiert Charts
                  Lädt zu CDN hoch
```

---

## State-Objekt (Zentrale Datenstruktur)

```python
class AgentState(MessagesState):
    # Von LangGraph
    messages: list[BaseMessage]  # Chat-Historie
    
    # Vom Supervisor
    plan: list[str] | None       # z.B. ["data_agent", "viz_agent"]
    current_step: int = 0
    
    # Vom Data Agent
    data: dict | None            # Rohdaten (aus Datei geladen!)
    data_summary: str | None     # Kurze Beschreibung für LLM
    data_meta: dict | None       # Statistiken, Zeitraum
    
    # Vom Viz Agent
    chart_url: str | None        # URL zum generierten Chart
    chart_type: str | None       # "line", "bar", "scatter"
    
    # Vom Stats Agent
    statistics: dict | None      # Berechnete Statistiken
```
