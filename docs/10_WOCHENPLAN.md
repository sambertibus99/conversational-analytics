# WOCHENPLAN

> Diese Woche: 48 Stunden verfügbar
> Ziel: Funktionierender Prototyp

---

## Zeitbudget

| Tag | Stunden | 
|-----|---------|
| Tag 1 (heute) | 8h |
| Tag 2 | 8h |
| Tag 3 | 8h |
| Tag 4 | 8h |
| Samstag | 4h |
| Sonntag | 4h |
| Montag | 8h |
| **Gesamt** | **48h** |

---

## 📅 TAG 1 (8h): Setup & ThingsBoard erkunden

### Block 1: Projekt-Setup (2h)
```
09:00-11:00
├── Python 3.11+ installiert?
├── Projektordner anlegen
├── Virtual Environment erstellen
├── requirements.txt erstellen
├── .env anlegen (ThingsBoard Credentials)
└── Git initialisieren
```

**Output:**
```
conversational-analytics/
├── venv/
├── .env
├── .gitignore
├── requirements.txt
└── README.md
```

**requirements.txt (initial):**
```
python-dotenv
httpx
asyncio
```

---

### Block 2: ThingsBoard API testen (3h)
```
11:00-14:00 (mit Pause)
├── Token holen (curl)
├── Device ID finden
├── Latest Telemetry testen
├── Timeseries testen
├── Aggregation testen
├── Attributes testen
└── Alles in .env notieren
```

**Checkliste:**
- [ ] `THINGSBOARD_URL` funktioniert
- [ ] `THINGSBOARD_TOKEN` funktioniert
- [ ] `KRC5_DEVICE_ID` notiert
- [ ] Alle API-Calls getestet

---

### Block 3: Python ThingsBoard Client (3h)
```
14:00-17:00
├── thingsboard_client.py erstellen
├── Async HTTP Client (httpx)
├── Token-Handling
├── get_latest_telemetry()
├── get_telemetry()
├── get_telemetry_aggregated()
├── get_attributes()
└── Tests schreiben
```

**Output:**
```python
# thingsboard_client.py
class ThingsBoardClient:
    async def get_latest_telemetry(device_id, keys) -> dict
    async def get_telemetry(device_id, keys, start_ts, end_ts) -> dict
    async def get_telemetry_aggregated(device_id, keys, start_ts, end_ts, interval, agg) -> dict
    async def get_attributes(device_id, keys) -> dict
```

---

## 📅 TAG 2 (8h): ThingsBoard MCP Server

### Block 1: MCP Grundlagen (2h)
```
09:00-11:00
├── MCP Dokumentation lesen
├── mcp Python Package installieren
├── Beispiel-Server verstehen
└── Architektur planen
```

**Lesen:**
- https://modelcontextprotocol.io/docs/concepts/architecture
- https://modelcontextprotocol.io/docs/concepts/tools

---

### Block 2: MCP Server implementieren (4h)
```
11:00-15:00 (mit Pause)
├── mcp_servers/thingsboard_server.py
├── Tool: list_devices
├── Tool: get_device_info
├── Tool: get_latest_telemetry
├── Tool: get_telemetry
├── Tool: get_telemetry_aggregated
├── Tool: get_attributes
└── Error Handling
```

**15 Tools (gefiltert aus 140):**
1. `list_devices` - Verfügbare Geräte
2. `get_device_info` - Gerätedetails
3. `get_latest_telemetry` - Aktuellste Werte
4. `get_telemetry` - Zeitreihe
5. `get_telemetry_aggregated` - Aggregiert
6. `get_attributes` - Statische Attribute
7. `list_telemetry_keys` - Verfügbare Keys
8. `list_attribute_keys` - Verfügbare Attribute

---

### Block 3: MCP Server testen (2h)
```
15:00-17:00
├── MCP Inspector installieren
├── Server starten
├── Alle Tools manuell testen
├── Edge Cases testen
└── Fehler fixen
```

**Test-Befehle:**
```bash
# MCP Inspector
npx @anthropic/mcp-inspector

# Server starten
python -m mcp_servers.thingsboard_server
```

---

## 📅 TAG 3 (8h): Data Agent

### Block 1: LangGraph Setup (2h)
```
09:00-11:00
├── langgraph installieren
├── langchain-anthropic installieren
├── Anthropic API Key einrichten
├── Basis-Graph verstehen
└── State-Klasse definieren
```

**State:**
```python
from langgraph.graph import MessagesState

class AgentState(MessagesState):
    plan: list[str] | None = None
    current_step: int = 0
    data: dict | None = None
    data_summary: str | None = None
    chart_url: str | None = None
```

---

### Block 2: Data Agent implementieren (4h)
```
11:00-15:00 (mit Pause)
├── agents/data_agent.py
├── MCP Client Integration
├── Tool-Binding
├── Zeitraum-Logik (relativ → absolut)
├── Aggregations-Entscheidung (>1000 Punkte)
├── State.data befüllen
└── State.data_summary generieren
```

---

### Block 3: Data Agent testen (2h)
```
15:00-17:00
├── Einfache Queries testen
├── Zeitraum-Parsing testen
├── Aggregation testen
├── Edge Cases
└── Fehler fixen
```

**Test-Queries:**
- "Aktuelle Position Achse 1" → get_latest_telemetry
- "Drehmoment letzte Stunde" → get_telemetry
- "Durchschnitt heute pro Stunde" → get_telemetry_aggregated

---

## 📅 TAG 4 (8h): Viz Agent + AntV MCP

### Block 1: AntV MCP Server (3h)
```
09:00-12:00
├── Chart-Bibliothek evaluieren (Plotly vs AntV)
├── mcp_servers/chart_server.py
├── Tool: line_chart
├── Tool: bar_chart
├── Tool: scatter_chart
├── Tool: export_png
└── Testen
```

---

### Block 2: Viz Agent (3h)
```
13:00-16:00
├── agents/viz_agent.py
├── State.data lesen
├── Chart-Typ-Entscheidung
├── Chart generieren
├── State.chart_url setzen
└── Testen
```

---

### Block 3: Integration testen (2h)
```
16:00-18:00
├── Data Agent → Viz Agent Handoff
├── Ende-zu-Ende Test
├── Debugging
└── Dokumentation
```

---

## 📅 SAMSTAG (4h): Stats Agent

### Block 1: Stats Tools (2h)
```
├── tools/stats_tools.py
├── mean, std, min, max
├── correlation
├── trend (lineare Regression)
├── detect_outliers
└── Testen
```

---

### Block 2: Stats Agent (2h)
```
├── agents/stats_agent.py
├── State.data lesen
├── Statistik berechnen
├── Interpretation generieren
└── Testen
```

---

## 📅 SONNTAG (4h): Supervisor

### Block 1: Supervisor Agent (2h)
```
├── agents/supervisor.py
├── Intent-Klassifikation
├── Plan erstellen
├── Agent-Routing
└── Testen
```

---

### Block 2: LangGraph Orchestrierung (2h)
```
├── agents/graph.py
├── Nodes definieren
├── Edges definieren
├── Compile
└── Ende-zu-Ende testen
```

---

## 📅 MONTAG (8h): Frontend + Evaluation

### Block 1: Chainlit Frontend (3h)
```
09:00-12:00
├── chainlit installieren
├── app.py
├── Chat-Interface
├── Chart-Anzeige
├── Error-States
└── Styling
```

---

### Block 2: Evaluation Setup (3h)
```
13:00-16:00
├── evaluation/test_queries.py
├── evaluation/metrics.py
├── Ground Truth sammeln
├── 5 einfache Tests durchführen
└── Metriken berechnen
```

---

### Block 3: Feinschliff (2h)
```
16:00-18:00
├── Bugs fixen
├── Prompts optimieren
├── Dokumentation
├── Demo vorbereiten
└── 🎉 MVP fertig!
```

---

## Risiko-Puffer

| Risiko | Wahrscheinlichkeit | Puffer |
|--------|-------------------|--------|
| ThingsBoard API Probleme | Mittel | +2h (Tag 1) |
| MCP Integration komplex | Hoch | +3h (Tag 2-3) |
| LangGraph Lernkurve | Mittel | +2h (Tag 3) |
| Visualisierung buggy | Mittel | +2h (Tag 4) |

**Notfall-Plan:** Wenn bis Samstag Data Agent nicht funktioniert → Stats Agent skippen, Fokus auf Kernfunktionalität.

---

## Täglicher Check

Am Ende jedes Tages:

- [ ] Was ist fertig?
- [ ] Was hat länger gedauert als geplant?
- [ ] Was blockiert?
- [ ] Plan für morgen anpassen?
- [ ] `04_AKTUELLER_STAND.md` aktualisiert?

---

## Kontakt bei Problemen

Wenn du steckst:
1. Error-Message kopieren
2. Was hast du versucht?
3. Neuen Chat starten mit: "Ich stecke bei AP[X], hier ist das Problem: ..."
