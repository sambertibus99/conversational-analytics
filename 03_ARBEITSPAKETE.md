# ARBEITSPAKETE

> Jedes Arbeitspaket ist in sich abgeschlossen und testbar.
> Status: ⬜ Offen | 🔄 In Arbeit | ✅ Fertig

---

## AP0: Projekt-Setup
**Status:** ⬜ Offen
**Dauer:** ~2 Stunden
**Abhängigkeiten:** Keine

### Ziel
Lauffähige Entwicklungsumgebung mit allen Dependencies.

### Schritte
1. Projektordner + venv erstellen
2. Dependencies installieren (requirements.txt)
3. .env Datei mit API Keys
4. Projektstruktur anlegen
5. Git initialisieren + .gitignore

### Ergebnis
```
conversational-analytics/
├── venv/
├── .env
├── .gitignore
├── requirements.txt
├── README.md
└── [leere Ordnerstruktur]
```

### Test
```bash
source venv/bin/activate
python -c "import langgraph; print('✅ LangGraph OK')"
python -c "import langchain_anthropic; print('✅ Anthropic OK')"
python -c "import chainlit; print('✅ Chainlit OK')"
```

---

## AP1: ThingsBoard MCP Server (gefiltert)
**Status:** ⬜ Offen
**Dauer:** ~4 Stunden
**Abhängigkeiten:** AP0

### Ziel
Eigener MCP Server der nur die 15 relevanten ThingsBoard-Tools exponiert.

### Schritte
1. Original ThingsBoard MCP analysieren (140 Tools)
2. Relevante Tools identifizieren (15)
3. Eigenen MCP Server schreiben (Python + FastMCP)
4. Tool-Beschreibungen für LLM optimieren
5. Verbindung zu ThingsBoard testen

### Relevante Tools
```python
CORE_TOOLS = [
    "list_devices",
    "get_device",
    "get_device_attributes",
    "get_telemetry",
    "get_latest_telemetry",
    "get_telemetry_keys",
    "get_telemetry_aggregated",  # Wichtig für große Zeiträume!
]

EXTENDED_TOOLS = [
    "get_alarms",
    "get_alarm_count",
    "search_devices",
    "get_device_relations",
]
```

### Ergebnis
```
mcp_servers/
├── __init__.py
├── thingsboard_server.py    # Der gefilterte MCP Server
└── thingsboard_tools.py     # Tool-Definitionen
```

### Test
```bash
# MCP Server starten
python mcp_servers/thingsboard_server.py

# In anderem Terminal: Tools auflisten
python -c "
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import asyncio

async def test():
    params = StdioServerParameters(command='python', args=['mcp_servers/thingsboard_server.py'])
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            tools = await session.list_tools()
            print(f'✅ {len(tools.tools)} Tools gefunden')
            for t in tools.tools:
                print(f'  - {t.name}')

asyncio.run(test())
"
```

---

## AP2: Data Agent
**Status:** ⬜ Offen
**Dauer:** ~3 Stunden
**Abhängigkeiten:** AP1

### Ziel
Agent der ThingsBoard-Daten holen kann und im State speichert.

### Schritte
1. Agent-State definieren
2. System-Prompt für Data Agent schreiben
3. MCP-Tools laden und binden
4. Daten-Extraktion aus Tool-Responses
5. Aggregations-Logik (wenn >1000 Punkte)

### Ergebnis
```
agents/
├── __init__.py
├── state.py           # AgentState Definition
└── data_agent.py      # Data Agent

prompts/
└── data_agent_prompt.py
```

### Test
```python
# tests/test_data_agent.py
import asyncio
from agents.data_agent import data_agent_node
from agents.state import AgentState

async def test_data_agent():
    state = AgentState(
        messages=[{"role": "user", "content": "Hole Temperatur von Roboter 1"}]
    )
    result = await data_agent_node(state)
    assert result.get("data") is not None
    print(f"✅ Daten erhalten: {len(result['data'])} Einträge")

asyncio.run(test_data_agent())
```

---

## AP3: AntV MCP Server (gefiltert)
**Status:** ⬜ Offen
**Dauer:** ~3 Stunden
**Abhängigkeiten:** AP0

### Ziel
MCP Server für Chart-Generierung mit 10 relevanten Tools.

### Schritte
1. AntV/Plotly API analysieren
2. Relevante Chart-Typen auswählen
3. MCP Server implementieren
4. Chart-Output als URL/Base64
5. Tool-Beschreibungen optimieren

### Relevante Tools
```python
CHART_TOOLS = [
    "line_chart",      # Zeitreihen
    "bar_chart",       # Vergleiche
    "scatter_chart",   # Korrelationen
    "area_chart",      # Kumulative Daten
    "bindData",        # Daten binden
    "bindAxis",        # Achsen konfigurieren
    "bindColor",       # Farbkodierung
    "setTitle",        # Titel setzen
    "export_png",      # Als Bild exportieren
    "export_html",     # Als interaktives HTML
]
```

### Ergebnis
```
mcp_servers/
├── antv_server.py
└── antv_tools.py
```

### Test
```python
# Einfacher Chart-Test
async def test_line_chart():
    data = [{"time": "10:00", "value": 25}, {"time": "11:00", "value": 27}]
    result = await antv.line_chart(data, x="time", y="value")
    assert result.get("chart_url") is not None
    print(f"✅ Chart erstellt: {result['chart_url']}")
```

---

## AP4: Viz Agent
**Status:** ⬜ Offen
**Dauer:** ~3 Stunden
**Abhängigkeiten:** AP2, AP3

### Ziel
Agent der aus Daten im State passende Charts generiert.

### Schritte
1. System-Prompt für Chart-Auswahl
2. Daten aus State lesen (nicht neu holen!)
3. Chart-Typ basierend auf Query + Daten wählen
4. AntV MCP Tools aufrufen
5. Chart-URL in State speichern

### Ergebnis
```
agents/
└── viz_agent.py

prompts/
└── viz_agent_prompt.py
```

### Test
```python
async def test_viz_agent():
    state = AgentState(
        messages=[{"role": "user", "content": "Zeig als Liniendiagramm"}],
        data={"temperature": [25, 27, 26, 28]}  # Aus AP2
    )
    result = await viz_agent_node(state)
    assert result.get("chart_url") is not None
```

---

## AP5: Stats Agent
**Status:** ⬜ Offen
**Dauer:** ~3 Stunden
**Abhängigkeiten:** AP2

### Ziel
Agent für statistische Berechnungen.

### Schritte
1. Stats MCP Server (oder Python direkt)
2. Relevante Funktionen: mean, std, correlation, trend
3. System-Prompt für Stats-Interpretation
4. Ergebnisse human-readable formatieren

### Tools
```python
STATS_TOOLS = [
    "mean",
    "std",
    "min_max",
    "correlation",
    "linear_trend",
    "moving_average",
    "percentiles",
    "anomaly_detection",
]
```

### Ergebnis
```
agents/
└── stats_agent.py

mcp_servers/
└── stats_server.py  # Optional, kann auch native Python sein
```

---

## AP6: Supervisor + Graph
**Status:** ⬜ Offen
**Dauer:** ~4 Stunden
**Abhängigkeiten:** AP2, AP4, AP5

### Ziel
Orchestrierung: Supervisor plant, Graph führt aus.

### Schritte
1. Supervisor-Prompt für Planung
2. Intent-Klassifikation (data/viz/stats)
3. LangGraph StateGraph bauen
4. Routing-Logik implementieren
5. Response-Generierung am Ende

### Ergebnis
```
agents/
├── supervisor.py
└── graph.py          # Haupt-Orchestrierung
```

### Test
```python
# Verschiedene Query-Typen testen
queries = [
    ("Zeig Temperatur", ["data_agent", "viz_agent"]),
    ("Durchschnittstemperatur", ["data_agent", "stats_agent"]),
    ("Korrelation mit Chart", ["data_agent", "stats_agent", "viz_agent"]),
]
for query, expected in queries:
    result = await graph.ainvoke({"messages": [{"role": "user", "content": query}]})
    assert result["plan"] == expected
```

---

## AP7: Frontend (Chainlit)
**Status:** ⬜ Offen
**Dauer:** ~2 Stunden
**Abhängigkeiten:** AP6

### Ziel
Chat-Interface das Charts anzeigen kann.

### Schritte
1. Chainlit App erstellen
2. Graph einbinden
3. Chart-Anzeige implementieren
4. Error-Handling
5. Loading-States

### Ergebnis
```
app.py                # Chainlit Hauptdatei
chainlit.md           # Willkommensnachricht
```

### Test
```bash
chainlit run app.py
# Browser öffnet sich automatisch
# Test-Queries eingeben
```

---

## AP8: Evaluation
**Status:** ⬜ Offen
**Dauer:** ~6 Stunden
**Abhängigkeiten:** AP7

### Ziel
Systematische Evaluation mit 15 Testfragen.

### Schritte
1. Testfragen finalisieren (15 + 5 ungültige)
2. Automatisierte Test-Pipeline
3. Metriken berechnen
4. Ergebnisse dokumentieren
5. Fehleranalyse

### Ergebnis
```
evaluation/
├── test_queries.py      # Die 15+5 Testfragen
├── metrics.py           # Metrik-Berechnung
├── run_evaluation.py    # Evaluation durchführen
└── results/
    ├── results.json     # Rohdaten
    └── analysis.md      # Auswertung
```

### Metriken-Berechnung
```python
def calculate_metrics(results):
    return {
        "execution_accuracy": successful / total,
        "tool_selection_accuracy": correct_tools / total,
        "data_faithfulness": no_hallucinations / data_queries,
        "abstention_rate": correct_abstentions / invalid_queries,
    }
```

---

## Abhängigkeits-Graph

```
AP0 (Setup)
 │
 ├──→ AP1 (ThingsBoard MCP)
 │     │
 │     └──→ AP2 (Data Agent)
 │           │
 │           ├──→ AP4 (Viz Agent) ←── AP3 (AntV MCP)
 │           │
 │           └──→ AP5 (Stats Agent)
 │                 │
 │                 ▼
 │           AP6 (Supervisor + Graph)
 │                 │
 │                 ▼
 │           AP7 (Frontend)
 │                 │
 │                 ▼
 └───────────→ AP8 (Evaluation)
```

---

## Geschätzter Gesamtaufwand

| AP | Dauer | Kumulativ |
|----|-------|-----------|
| AP0 | 2h | 2h |
| AP1 | 4h | 6h |
| AP2 | 3h | 9h |
| AP3 | 3h | 12h |
| AP4 | 3h | 15h |
| AP5 | 3h | 18h |
| AP6 | 4h | 22h |
| AP7 | 2h | 24h |
| AP8 | 6h | 30h |

**Gesamt: ~30 Stunden Implementierung**
(+ Puffer für Debugging, Iteration, Dokumentation)
