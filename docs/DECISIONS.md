# ENTSCHEIDUNGS-DATENBANK

> **Zweck:** Wiederverwendbare Patterns aus Projekt-Entscheidungen
> **Für:** Claude erkennt ähnliche Probleme und schlägt bewährte Lösungen vor
> **Stand:** 19. Dezember 2025

---

## 🔍 Schnell-Referenz

| ID | Pattern | Problem | Lösung | Anwenden bei |
|----|---------|---------|--------|--------------|
| DEC-001 | Tool Selection (<10) | Welches Tool wählen? | Optimierte Descriptions | Agents mit <10 Tools |
| DEC-002 | LLM-Parsing | Komplexe User-Eingabe | LLM parst → Tool bekommt strukturiert | Zeitangaben, Filter |
| DEC-003 | InjectedState | Große Daten an Tool | Via State, nicht Prompt | Viz, Stats Agent |
| DEC-004 | File-Storage | Token-Limit bei Daten | Rohdaten→Datei, Summary→LLM | Alle Datenabfragen |
| DEC-005 | MCP Warmup | Langsame Requests | Globale Session + Startup | Alle MCP Server |
| DEC-006 | Auto-Aggregation | Zu viele Datenpunkte | Intervall automatisch berechnen | Zeitreihen-Abfragen |
| DEC-007 | Message-Filtering | Multiple SystemMessages | Nur HumanMessages weitergeben | Agent-zu-Agent |
| DEC-008 | Status-First-Parsing | Response nicht erkannt | Status ZUERST prüfen | Alle Tool-Responses |
| DEC-009 | Error Handling | HTTP-Fehler, Retries | Custom Exceptions + Retry | MCP Server, API Clients |
| DEC-010 | Datenpunkt-Limit | User will zu viele Daten | Warnung/Fehler + Vorschlag | Zeitreihen-Abfragen |
| DEC-011 | Literal statt Regex | Param-Parsing fehleranfällig | Vordefinierte Optionen | Tool-Parameter |
| DEC-012 | Integration Testing | MCP+LLM Tests instabil | Cleanup + Delays + Marker | Alle Integration-Tests |
| DEC-013 | Multi-Turn Persistenz | State zwischen Turns verloren | Checkpointer + Reducer | Multi-Turn Konversationen |
| DEC-014 | SystemMessage Filter | Multiple SystemMessages Fehler | Filter + frische SystemMessage | Multi-Turn mit Anthropic |
| DEC-015 | XML-Tag Prompt-Struktur | Prompt unstrukturiert | XML-Tags für Sektionen | Alle Agent-Prompts |
| DEC-016 | Production Code Quality | print(), lange Funktionen, kein Retry | Logging, SRP, Retry | Alle Agents |
| DEC-017 | Graph Best Practices | Endlosschleifen, kein Error-Handler | max_steps, error_handler, Validierung | LangGraph Orchestrierung |

---

## DEC-001: Tool Selection bei wenigen Tools

### Problem
Wie wählt der Agent das richtige Tool aus mehreren Optionen?

### Kontext
- Anzahl Tools: < 10
- Alternative: RAG über Tool-Descriptions (bei 20+ Tools)

### Entscheidung
**Direkte LLM-Auswahl mit optimierten Descriptions**

### Pattern
```python
@mcp.tool()
async def get_telemetry(...):
    """
    Kurzbeschreibung.
    
    WANN BENUTZEN:
    - User fragt nach Verlauf/Trend
    - User nennt Zeitraum
    
    NICHT BENUTZEN:
    - User fragt nur nach aktuellem Wert → get_latest_telemetry
    """
```

### Begründung
- Bei <10 Tools ist direkte Auswahl performanter als RAG
- Kein zusätzlicher Retrieval-Schritt (Latenz)
- Transparenter für Debugging
- Quellen: LangGraph Docs 2025, "How to handle large numbers of tools"

### Anwenden bei
- Data Agent (8 Tools)
- Viz Agent (25 Tools, aber gruppiert)
- Stats Agent (8 Tools)

### Referenz
`docs/design/thingsboard_mcp_server.md` Abschnitt 2

---

## DEC-002: LLM-basiertes Parsing

### Problem
User gibt komplexe natürlichsprachliche Eingaben (z.B. "Dienstag 13 Uhr") die in strukturierte Parameter umgewandelt werden müssen.

### Kontext
- Regex-Parser: ~200 LOC, wartungsaufwändig
- Neue Formate = neuer Code

### Entscheidung
**LLM parst im Prompt, Tool bekommt ISO-Format**

### Pattern
```python
# Im Agent-Prompt:
"""
## AKTUELLES DATUM
Heute ist: {weekday}, {date}

## ZEITANGABEN BERECHNEN
| User sagt | start_date | end_date |
| "gestern" | {yesterday} | {yesterday} |
"""

# Tool-Signatur:
def get_telemetry(
    keys: str,
    start_date: str,  # YYYY-MM-DD
    end_date: str,    # YYYY-MM-DD
    ...
)
```

### Begründung
- ~200 LOC Regex entfernt
- Neue Formate funktionieren automatisch
- LLM kann bei Unklarheit nachfragen
- Quellen: LangChain "Pydantic Schema als Prompt" Prinzip

### Anwenden bei
- Zeitraum-Parsing (Data Agent)
- Filter-Parsing (z.B. "nur Achse 1-3")
- Jede komplexe User-Eingabe → strukturierte Parameter

### Referenz
`docs/design/thingsboard_mcp_server.md` Abschnitt 3

---

## DEC-003: InjectedState für Daten-Übergabe

### Problem
Große Datenmengen (z.B. 72.000 Punkte) müssen an Tool übergeben werden, ohne durch LLM-Prompt zu gehen.

### Kontext
- Daten im Prompt: Langsam, teuer, Token-Limit
- Alternative: Direkter Tool-Call ohne LLM

### Entscheidung
**InjectedState + direkter Tool-Call**

### Pattern
```python
from langgraph.prebuilt import InjectedState
from typing import Annotated

async def create_chart(
    chart_type: str,                           # LLM wählt
    state: Annotated[dict, InjectedState()]    # Automatisch injiziert
):
    data = state["data"]  # Nicht vom LLM!
```

### Begründung
- LangGraph Best Practice
- Performance: ~100s → ~5s
- LLM wählt nur Tool-Typ, nicht Daten
- Quellen: LangGraph GitHub Issues #3564, #1916

### Anwenden bei
- Viz Agent (Chart-Daten)
- Stats Agent (Berechnungs-Daten)
- Jeder Agent der große Daten verarbeitet

### Referenz
`docs/design/viz_agent.md` Abschnitt 1

---

## DEC-004: File-Storage für große Daten

### Problem
Token-Limit überschritten bei vielen Datenpunkten im LLM-Context.

### Kontext
- 627 Punkte × 6 Keys × ~100 Bytes = ~375 KB
- Anthropic: 400 Bad Request

### Entscheidung
**Rohdaten in Datei, nur Summary an LLM**

### Pattern
```python
# MCP Server:
data_file = save_data_to_file(raw_data)  # → outputs/data/telemetry_xxx.json
return {
    "status": "success",
    "statistics": calculate_statistics(raw_data),  # ~500 Bytes
    "data_file": data_file
}

# Agent:
file_data = load_from_file(response["data_file"])
state["data"] = file_data  # Für nächsten Agent
```

### Begründung
- Max ~50KB direkt im LLM-Context
- Rohdaten werden nicht "gelesen", nur weitergereicht
- Statistiken reichen für LLM-Entscheidungen

### Anwenden bei
- Alle Telemetrie-Abfragen >100 Punkte
- Stats Agent Ergebnisse
- Jede große API-Response

### Referenz
`docs/07_ERROR_HANDLING.md`, `docs/05_ARCHITEKTUR.md`

---

## DEC-005: MCP Server Warmup

### Problem
MCP Server werden bei jedem Request neu gestartet (~30 Sekunden).

### Kontext
- Python-Subprocess: ~5 Sek
- Node.js (npx): ~10-15 Sek

### Entscheidung
**Globale Session mit AsyncExitStack + Warmup beim Start**

### Pattern
```python
# Global
_mcp_tools: list | None = None
_mcp_exit_stack: AsyncExitStack | None = None

async def get_mcp_tools():
    global _mcp_tools, _mcp_exit_stack
    if _mcp_tools is not None:
        return _mcp_tools  # Aus Cache!
    
    _mcp_exit_stack = AsyncExitStack()
    # Server starten und Session offen halten...

# App-Start
@cl.on_chat_start
async def on_chat_start():
    await asyncio.gather(get_mcp_tools(), get_antv_tools())
```

### Begründung
- 1. Request: ~15 Sek (Warmup)
- Folge-Requests: ~5 Sek
- Session bleibt offen solange App läuft

### Anwenden bei
- Alle MCP Server
- Externe API-Clients mit Auth

### Referenz
`docs/design/thingsboard_mcp_server.md` Abschnitt 5

---

## DEC-006: Automatische Aggregation

### Problem
Zu viele Rohdatenpunkte bei längeren Zeiträumen (Rate-Limit, Token-Limit).

### Kontext
- 24h × 6 Achsen × 1Hz = 518.400 Punkte
- API Rate Limit (429)

### Entscheidung
**Intervall automatisch berechnen basierend auf Zeitraum**

### Pattern
```python
def calculate_auto_interval(start_dt, end_dt):
    duration_hours = (end_dt - start_dt).total_seconds() / 3600
    
    if duration_hours <= 1:     return 60000,    "1 Minute"
    elif duration_hours <= 24:  return 600000,   "10 Minuten"
    elif duration_hours <= 168: return 3600000,  "1 Stunde"
    else:                       return 86400000, "1 Tag"
```

### Begründung
- Max ~150 Punkte pro Key
- User wird über Einstellungen informiert
- User kann anpassen ("zeig Maximum", "mit 5-Minuten-Intervall")

### Anwenden bei
- Alle Zeitreihen-Abfragen
- Export-Funktionen
- Batch-Analysen

### Referenz
`docs/design/thingsboard_mcp_server.md` Abschnitt 4

---

## DEC-007: Message-Filtering bei Agent-Übergabe

### Problem
`ValueError: Received multiple non-consecutive system messages`

### Kontext
- Agent B übernimmt alle Messages von Agent A
- Anthropic erlaubt nur 1 SystemMessage

### Entscheidung
**Nur HumanMessages weitergeben, neuen SystemMessage erstellen**

### Pattern
```python
# FALSCH:
messages = state["messages"]  # Enthält SystemMessage von Data Agent!

# RICHTIG:
human_messages = [m for m in state["messages"] if isinstance(m, HumanMessage)]
messages_with_system = [
    SystemMessage(content=VIZ_AGENT_PROMPT),  # Neu!
    *human_messages
]
```

### Begründung
- Anthropic API Constraint
- Jeder Agent braucht eigenen System-Prompt
- AIMessages und ToolMessages können optional übernommen werden

### Anwenden bei
- Viz Agent (nach Data Agent)
- Stats Agent (nach Data Agent)
- Respond Node (nach allen Agents)

### Referenz
`docs/07_ERROR_HANDLING.md` Fehler #5

---

## DEC-008: Status-First-Parsing

### Problem
Agent erkennt "no_data" Response nicht, sagt trotzdem "Daten geladen".

### Kontext
- MCP Response hat verschiedene Status-Typen
- Parser extrahiert Daten ohne Status zu prüfen

### Entscheidung
**Status-Feld IMMER ZUERST prüfen**

### Pattern
```python
def extract_data_from_parsed(parsed):
    # 1. STATUS ZUERST!
    if parsed.get("status") == "no_data":
        return None, {"type": "no_data", ...}, None
    if parsed.get("status") == "error":
        return None, {"type": "error", ...}, None
    if parsed.get("status") == "data_available":
        return parsed, {"type": "data_availability", ...}, None
    
    # 2. Erst dann Daten verarbeiten
    if parsed.get("status") == "success":
        # ...
```

### Begründung
- Defensives Parsing
- Keine "silent failures"
- Klare Fehlermeldungen an User

### Anwenden bei
- Alle Tool-Response-Parser
- API-Response-Handler
- Jede externe Datenquelle

### Referenz
`docs/07_ERROR_HANDLING.md` Fehler #3, #4

---

## DEC-009: Error Handling mit Custom Exceptions und Retry

### Problem
HTTP-Fehler bei API-Calls (Netzwerk, Timeout, Auth, Rate Limit) werden nicht sauber behandelt. LLM bekommt keine hilfreichen Fehlermeldungen.

### Kontext
- Verschiedene Fehlertypen brauchen unterschiedliche Behandlung
- Transiente Fehler (Netzwerk) sollten automatisch wiederholt werden
- User-behebbare Fehler sollten klare Anweisungen geben
- LangGraph Best Practice: Fehlertypen kategorisieren
- FastMCP Best Practice: ToolError für erwartete Fehler

### Entscheidung
**Custom Exceptions + Retry mit Exponential Backoff + strukturierte Fehler-Responses**

### Pattern
```python
# 1. Custom Exceptions im Client
class ThingsBoardError(Exception):
    def __init__(self, message: str, details: dict | None = None):
        self.message = message
        self.details = details or {}

class ThingsBoardAuthError(ThingsBoardError): ...      # 401, 403
class ThingsBoardConnectionError(ThingsBoardError): ...  # Netzwerk
class ThingsBoardRateLimitError(ThingsBoardError): ...  # 429

# 2. Retry mit Exponential Backoff
async def retry_with_backoff(operation, max_attempts=3):
    for attempt in range(max_attempts):
        try:
            return await operation()
        except retryable_exceptions as e:
            delay = min(initial_delay * (2 ** attempt), max_delay)
            jitter = random.uniform(0, delay * 0.1)
            await asyncio.sleep(delay + jitter)
    raise last_exception

# 3. Strukturierte Fehler im MCP Server
def format_thingsboard_error(error: ThingsBoardError) -> dict:
    return {
        "status": "error",
        "error_type": error.__class__.__name__,
        "message": error.message,
        "details": error.details,
    }
```

### Begründung
- LangGraph empfiehlt: Transient → Retry, LLM-recoverable → Zurück mit Context
- FastMCP empfiehlt: ToolError für client-visible errors, mask_error_details für interne
- Exponential Backoff verhindert "Thundering Herd" bei Rate Limits
- Jitter verhindert synchronisierte Retries
- Quellen: LangGraph Docs "Thinking in LangGraph", FastMCP Docs

### Anwenden bei
- ThingsBoard Client (HTTP-Calls)
- Alle MCP Server (Tool-Responses)
- Zukünftige externe API-Integrationen

### Referenz
`mcp_servers/thingsboard_client.py`, `mcp_servers/thingsboard_server.py`

---

## DEC-010: Datenpunkt-Limit mit User-Feedback

### Problem
User kann manuell sehr kleine Intervalle wählen (z.B. "1 Sekunde"), was bei langen Zeiträumen zu Hunderttausenden Datenpunkten führt.

### Kontext
- 1 Tag × 1 Sekunde = 86.400 Punkte pro Key
- Bei 6 Keys = 518.400 Punkte
- API Rate Limits, Token-Limits, Performance-Probleme
- Auto-Aggregation (DEC-006) schützt nur bei Standard-Settings
- LangGraph: "User-fixable errors" sollten mit `interrupt()` behandelt werden

### Entscheidung
**Datenpunkt-Berechnung VOR API-Call + Warnung/Fehler mit Korrekturvorschlag**

### Pattern
```python
# Limits
DATAPOINT_WARNING_THRESHOLD = 1000   # Ab hier: Warnung
DATAPOINT_ERROR_THRESHOLD = 10000    # Ab hier: Fehler

def check_datapoint_limit(start_dt, end_dt, interval_ms, num_keys):
    duration_ms = (end_dt - start_dt).total_seconds() * 1000
    points_per_key = int(duration_ms / interval_ms) + 1
    
    if points_per_key > DATAPOINT_ERROR_THRESHOLD:
        # Fehler - User muss anpassen
        return {
            "status": "error_too_many_datapoints",
            "message": f"Das würde {points_per_key:,} Punkte pro Key erzeugen.",
            "suggestion": {"interval": "10 Minuten", "expected_points": 144},
            "user_action": "Bitte wähle ein größeres Intervall.",
            "hint": "Frage den User: 'Soll ich stattdessen 10-Minuten-Durchschnitte verwenden?'"
        }
    
    if points_per_key > DATAPOINT_WARNING_THRESHOLD:
        # Warnung - funktioniert, aber User sollte es wissen
        return {
            "status": "warning_many_datapoints",
            "message": f"{points_per_key:,} Punkte - kann länger dauern.",
            "continue": True
        }
    
    return None  # OK
```

### Begründung
- Berechnung BEVOR API-Call spart Zeit und Resourcen
- User bekommt konkreten Vorschlag (nicht nur "Fehler")
- Agent kann Vorschlag direkt übernehmen oder User fragen
- Warnung bei mittleren Mengen: User weiß Bescheid, aber es funktioniert
- Quellen: LangGraph "User-fixable errors", UX Best Practices

### Anwenden bei
- `get_telemetry()` mit manuellem Intervall
- Zukünftige Batch-Export-Funktionen
- Jede Abfrage mit user-definierbarer Granularität

### Referenz
`mcp_servers/thingsboard_server.py` Funktion `check_datapoint_limit()`

---

## DEC-011: Literal Types statt Regex-Parsing

### Problem
Regex-Parsing für Tool-Parameter (interval, aggregation) ist fehleranfällig:
- "1 Stunde" wurde als "1 Tag" geparst (weil "Stunde" ein "t" enthält)
- Viele Aliases müssen gepflegt werden
- Redundant: LLM parst bereits natürliche Sprache

### Kontext
- LangChain Best Practice: "LLMs support structured output natively"
- DEC-002 sagt bereits: LLM parst → Tool bekommt strukturiert
- Regex-Parser war ~30 LOC mit vielen Edge Cases

### Entscheidung
**Vordefinierte Optionen mit Literal Types statt Regex-Parsing**

### Pattern
```python
from typing import Literal

# Vordefinierte Optionen
INTERVAL_OPTIONS = {
    "1m": (60000, "1 Minute"),
    "5m": (300000, "5 Minuten"),
    "10m": (600000, "10 Minuten"),
    "1h": (3600000, "1 Stunde"),
    "1d": (86400000, "1 Tag"),
}

# Tool-Signatur mit Literal
@mcp.tool()
async def get_telemetry(
    ...,
    interval: Literal["1m", "5m", "10m", "30m", "1h", "6h", "1d"] | None = None,
    aggregation: Literal["AVG", "MIN", "MAX", "SUM", "COUNT"] | None = None,
):
    """..."""

# Einfaches Mapping statt Regex
def get_interval(interval: str | None) -> tuple[int, str, bool]:
    if interval is None:
        return None, None, True  # Auto
    if interval.lower() in INTERVAL_OPTIONS:
        ms, human = INTERVAL_OPTIONS[interval.lower()]
        return ms, human, False
    return None, None, True  # Fallback: Auto
```

### Begründung
- Kein Regex = keine Edge Cases
- LLM wählt direkt aus gültigen Werten
- Klare Optionen in Tool-Description
- ~30 LOC → ~10 LOC
- Best Practice: "Structured Output" statt "Output Parsing"

### Anwenden bei
- Alle Tool-Parameter mit begrenzten Optionen
- Enums/Kategorien in API-Parametern
- Nicht bei Freitext-Eingaben

### Referenz
`mcp_servers/thingsboard_server.py` Funktionen `get_interval()`, `get_aggregation()`

---

## DEC-012: Integration Testing mit MCP + LLM

### Problem
Integration-Tests mit MCP-Servern und LLM-Aufrufen sind instabil:
1. **MCP Session Race Conditions**: Async Context Manager wird nicht sauber aufgeräumt
2. **Rate Limits**: Anthropic API hat 30k tokens/minute Limit
3. **Flaky Tests**: Manchmal PASSED, manchmal FAILED ohne Code-Änderung

### Kontext
- MCP nutzt `stdio_client` mit subprocess
- Jeder LLM-Call verbraucht ~2-3k Tokens (System Prompt + Tools)
- 4 Tests in 1 Minute = schnell über Rate Limit
- FastMCP Docs: "Use `Client(transport=mcp)` for testing"
- Anthropic Docs: "Use exponential backoff for 429 errors"

### Entscheidung
**Dreifache Absicherung: Cleanup Fixture + Rate Limit Delays + Test-Marker**

### Pattern
```python
# 1. Cleanup Fixture in conftest.py
@pytest.fixture(scope="function")
async def cleanup_mcp_after_test():
    """Räumt MCP Session nach jedem Test auf."""
    yield
    try:
        import agents.data_agent as da
        
        # Session schließen
        if da._mcp_exit_stack is not None:
            await da._mcp_exit_stack.aclose()
        
        # Globale Variablen zurücksetzen
        da._mcp_tools = None
        da._mcp_exit_stack = None
        
        # Rate Limit Pause (2 Sekunden)
        await asyncio.sleep(2)
    except Exception:
        pass

# 2. Test-Marker für Trennung
@pytest.mark.integration  # Braucht externe Services
@pytest.mark.slow          # Dauert >5 Sekunden
@pytest.mark.asyncio
async def test_data_agent(cleanup_mcp_after_test):
    ...

# 3. Rate Limit Graceful Skip
error = result.get("error")
if error and "429" in str(error):
    pytest.skip("Rate Limit erreicht")
```

### Test-Ausführung
```bash
# Schnell: Nur Unit-Tests (kein Server nötig)
python -m pytest tests/ -m "not integration" -v

# Langsam: Nur Integration-Tests
python -m pytest tests/ -m integration -v

# Einzeln bei Rate Limit Problemen
python -m pytest tests/test_data_agent.py::test_latest_telemetry -v
```

### Begründung
- **Cleanup**: Verhindert "Attempted to exit cancel scope in different task"
- **2s Delay**: 30k tokens/min ÷ ~3k tokens/test = ~10 tests/min, mit Buffer
- **Marker**: CI kann Unit-Tests schnell, Integration-Tests nachts laufen
- **Graceful Skip**: Test ist nicht FAILED bei temporärem Rate Limit
- Quellen: FastMCP Testing Docs, Anthropic Rate Limits, pytest-asyncio Best Practices

### Anwenden bei
- Alle Tests die MCP Server starten
- Alle Tests die LLM-Calls machen
- Alle Tests die externe APIs aufrufen

### Referenz
`tests/conftest.py`, `tests/test_data_agent.py`

---

## DEC-013: Multi-Turn State-Persistenz mit Checkpointer und Reducern

### Problem
Bei Multi-Turn-Konversationen gingen Daten zwischen Turns verloren:
- Turn 1: "Zeig Drehmomente vom 16.12" → 210 Punkte geladen
- Turn 2: "Gibt es Zusammenhang mit Geschwindigkeit?" → "Keine Drehmoment-Daten" (obwohl gerade geladen!)

Ursache: Jeder `run_query()` Aufruf erstellte neuen State und die State-Felder wurden überschrieben statt akkumuliert.

### Kontext
- LangGraph Best Practice: Checkpointer für State-Persistenz
- Zwei Memory-Typen: Short-term (thread-scoped), Long-term (cross-thread)
- Problem: Checkpointer allein reicht nicht - Reducer müssen Daten akkumulieren
- Alternativen: Eigene Persistenz in app.py, Daten in Chainlit-Session

### Entscheidung
**Zweistufige Lösung: Checkpointer + Custom Reducer für datasets**

### Pattern
```python
# 1. state.py - Reducer für Daten-Akkumulation
def merge_datasets(existing: dict | None, new: dict | None) -> dict:
    if existing is None: return new or {}
    if new is None: return existing
    return {**existing, **new}  # Merge: alte + neue Datasets

def merge_summaries(existing: str | None, new: str | None) -> str:
    if not existing: return new or ""
    if not new: return existing
    return f"{existing} | {new}"  # Kombiniere Summaries

class AgentState(MessagesState):
    datasets: Annotated[dict[str, Any], merge_datasets] = {}
    data_summary: Annotated[str, merge_summaries] = ""

# 2. graph.py - Checkpointer
from langgraph.checkpoint.memory import InMemorySaver

def compile_graph():
    checkpointer = InMemorySaver()
    return graph.compile(checkpointer=checkpointer)

async def run_query(query: str, thread_id: str = "default"):
    config = {"configurable": {"thread_id": thread_id}}
    result = await graph.ainvoke({"messages": [HumanMessage(content=query)]}, config)

# 3. data_agent.py - Datasets speichern
def run_data_agent(state):
    # Prüfe vorhandene Datasets
    if state.get("datasets"):
        prompt += format_existing_datasets_hint(state["datasets"])
    
    # Neue Daten unter Key speichern
    dataset_key = determine_dataset_key(data)  # z.B. "torque", "velocity"
    return {
        "datasets": {dataset_key: {"data": data, "meta": meta}},
        "data_summary": summary,
    }

# 4. viz_agent.py / stats_agent.py - Alle Datasets nutzen
def extract_data_from_datasets(datasets: dict) -> dict:
    merged = {}
    for dataset in datasets.values():
        merged.update(dataset.get("data", {}))
    return merged
```

### Begründung
- **Checkpointer allein reicht nicht**: Persistiert State, aber ohne Reducer werden Werte überschrieben
- **Custom Reducer**: `merge_datasets` akkumuliert Datensätze, `merge_summaries` kombiniert Texte
- **Dataset-Keys**: Ermöglichen gezielte Nutzung ("torque", "velocity") statt anonymer Daten
- **Prompt-Hint**: Agent weiß welche Daten schon da sind, lädt nur Fehlende
- Quellen: LangGraph Docs "Reducers", "Memory", LangChain Blog "Long-Term Memory"

### Betroffene Komponenten
- `agents/state.py`: Reducer für datasets und data_summary
- `agents/data_agent.py`: Dataset-Key + Prompt-Hint für vorhandene Daten
- `agents/viz_agent.py`: `extract_data_from_datasets()` für Chart-Generierung
- `agents/stats_agent.py`: `extract_data_from_datasets()` für Statistiken
- `agents/graph.py`: Checkpointer + Datasets-Info im Respond Node
- `agents/supervisor.py`: Letzte HumanMessage statt erste
- `app.py`: thread_id Generierung und Übergabe

### Anwenden bei
- Alle Multi-Turn Szenarien
- Korrelationsanalysen ("vergleiche X mit Y")
- Follow-up Fragen ("zeig das als Balkendiagramm")
- Konversationen mit mehreren Datenabfragen

### Production-Upgrade
```python
# Statt InMemorySaver:
from langgraph.checkpoint.postgres import PostgresSaver
DB_URI = "postgresql://..."
with PostgresSaver.from_conn_string(DB_URI) as checkpointer:
    graph = builder.compile(checkpointer=checkpointer)
```

### Referenz
`agents/state.py`, `agents/graph.py`, https://docs.langchain.com/oss/python/langgraph/add-memory

---

## DEC-014: SystemMessage-Handling bei Multi-Turn (Anthropic)

### Problem
Bei Multi-Turn-Konversationen akkumulieren SystemMessages im State:
```
ValueError: Received multiple non-consecutive system messages.
```

Anthropics API erlaubt nur **eine SystemMessage am Anfang** der Message-Liste.

### Kontext
- LangGraph `add_messages` Reducer akkumuliert ALLE Message-Typen
- Checkpointer persistiert den gesamten State inkl. SystemMessages
- Jeder Agent fügt eigene SystemMessage hinzu → Fehler bei Turn 2+
- Offizielles LangGraph-Beispiel zeigt Lösung in `call_model` Node

### Entscheidung
**SystemMessages aus State filtern, frische SystemMessage bei jedem Agent-Aufruf prependen**

### Pattern
```python
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

async def run_agent(state: AgentState):
    # 1. FILTER: Nur Human/AI/Tool Messages aus State
    filtered_messages = [
        msg for msg in state["messages"]
        if not isinstance(msg, SystemMessage)
    ]
    
    # 2. PREPEND: Frische SystemMessage für diesen Agent
    messages = [
        SystemMessage(content=AGENT_SYSTEM_PROMPT),
        *filtered_messages
    ]
    
    # 3. LLM aufrufen
    response = await llm.ainvoke(messages)
    return {"messages": [response]}
```

### Alternative: create_react_agent
```python
# LangGraph handled SystemMessage intern korrekt
agent = create_react_agent(
    model=llm,
    tools=tools,
    prompt="Du bist ein hilfreicher Assistent..."  # String als system_prompt
)
```

### Begründung
- Anthropic API Constraint (nicht umgehbar)
- Offizielle LangGraph Best Practice (siehe "How to create a ReAct agent from scratch")
- Jeder Agent braucht eigenen System-Prompt für seine Rolle
- AIMessages und ToolMessages können/sollten übernommen werden (Kontext)
- Quellen: LangGraph Docs, GitHub Issue langchainjs#7807, Anthropic API Docs

### Anwenden bei
- Alle Agents die nach anderem Agent ausgeführt werden
- Multi-Turn Konversationen mit Checkpointer
- Jeder LLM-Aufruf in einem LangGraph Node

### Referenz
`agents/data_agent.py`, `agents/stats_agent.py`, LangGraph Docs "How to create a ReAct agent from scratch"

---

## 📝 Neue Entscheidung hinzufügen

Template für neue Entscheidungen:

```markdown
## DEC-XXX: [Titel]

### Problem
Was ist das Problem?

### Kontext
Rahmenbedingungen, Alternativen

### Entscheidung
**Gewählte Lösung in einem Satz**

### Pattern
\`\`\`python
# Code-Beispiel
\`\`\`

### Begründung
Warum diese Lösung?

### Anwenden bei
Wo sonst noch relevant?

### Referenz
Link zu Detail-Dokumentation
```

---

## 🔄 Änderungshistorie

| Datum | Änderung |
|-------|----------|
| 2025-12-19 | Initiale Version mit 8 Patterns |
| 2025-12-20 | DEC-009 (Error Handling) + DEC-010 (Datenpunkt-Limit) hinzugefügt |
| 2025-12-20 | DEC-011 (Literal statt Regex) - Refactoring nach fehlgeschlagenem Test |
| 2025-12-20 | DEC-012 (Integration Testing) - MCP Cleanup + Rate Limit Best Practices |
| 2025-12-20 | DEC-013 (Multi-Turn Persistenz) - Checkpointer für State zwischen Turns |
| 2025-12-23 | DEC-014 (SystemMessage Filter) - Anthropic Multi-Turn Fix |
| 2025-12-23 | IDEE-001 (Dynamic Key Discovery) - Notiert für spätere Umsetzung |
| 2025-12-23 | DEC-015 (Prompt-Struktur mit XML-Tags) - Anthropic Best Practice |

---

## DEC-015: Prompt-Struktur mit XML-Tags

### Problem
Agent-Prompts waren unstrukturiert mit Unicode-Boxen und gemischten Formatierungen. Negative Anweisungen ("NIEMALS", "NICHT") können kontraproduktiv wirken.

### Kontext
- Anthropic empfiehlt XML-Tags für Prompt-Struktur
- Claude wurde mit XML-Tags im Training trainiert
- Positive Anweisungen funktionieren besser als negative
- Lange Prompts profitieren von klaren Sektionen

### Entscheidung
**XML-Tags für Sektionen + positive Formulierungen + Redundanzen entfernen**

### Pattern
```python
return f"""<role>
Du bist ein IIoT-Datenexperte der Sensordaten von einem KUKA KRC5 Roboter abruft.
</role>

<context>
Heute ist {current_weekday}, {current_date}. Aktuelle Uhrzeit: {current_time}.
</context>

<task>
Analysiere die Nutzeranfrage und hole passende Daten.
</task>

<instructions>
## Zeitangaben berechnen
...
</instructions>

<tools>
| Tool | Wann benutzen |
...
</tools>

<examples>
...
</examples>

<error_handling>
...
</error_handling>

<critical_rules>
STOP-REGEL 1: Bei status="no_data"
→ Sofort stoppen, User informieren
→ Nur auf User-Anweisung anderen Zeitraum versuchen
</critical_rules>
"""
```

### Änderungen gegenüber vorheriger Version

| Vorher | Nachher | Grund |
|--------|---------|-------|
| Unicode-Boxen `╔═══╗` | `<critical_rules>` | Claude versteht XML besser |
| "NIEMALS alle Keys abrufen!" | "Rufe maximal 6-10 Keys ab" | Positive Anweisung |
| Redundante Aggregations-Erklärungen | Einmal erklärt | Kürzer, klarer |
| ~180 Zeilen | ~130 Zeilen | ~28% kürzer |
| Gemischte Struktur | Klare Sektionen | Besser parsbar |

### Begründung
- **XML-Tags**: "Claude was trained with XML tags in the training data" (Anthropic Docs)
- **Positive Anweisungen**: "Tell it what to do, not what to avoid" (LangChain Best Practice)
- **Struktur**: "Wrap sections in <task>, <rules>, <examples> tags" (Anthropic Prompt Engineering)
- **Kürze**: Weniger Tokens = schneller + billiger

### Quellen
- Anthropic Docs: System Prompts
- Anthropic: Generate better prompts in developer console
- Medium: Prompt Engineering with Anthropic Claude (Zack Witten Talk)
- FreeCodeCamp: How to Write Effective Prompts for AI Agents

### Anwenden bei
- Alle Agent-Prompts (Data, Viz, Stats, Supervisor)
- Zukünftige neue Agents
- Lange System-Prompts generell

### Referenz
- `prompts/data_agent_prompt.py`
- `prompts/supervisor_prompt.py`
- `prompts/viz_agent_prompt.py`
- `prompts/stats_agent_prompt.py`

---

## DEC-016: Production Code Quality

**Datum:** 23.12.2025

### Problem
Der Data Agent Code hatte mehrere Qualitätsprobleme:
- `print()` statt strukturiertem Logging
- `run_data_agent()` mit ~100 Zeilen (zu viele Verantwortlichkeiten)
- Kein Retry-Mechanismus bei transienten Fehlern
- Globale Variablen erschweren Testing

### Kontext
Best Practices aus:
- LangGraph Production Patterns (DEV.to, LangChain Blog)
- Python Logging Best Practices (SigNoz, SuperFastPython)
- Clean Code / Single Responsibility Principle (Martin Fowler, GitHub clean-code-python)

### Entscheidung

#### 1. Strukturiertes Logging statt print()
```python
# Vorher
def debug_print(msg: str):
    if DEBUG:
        print(f"🔍 DEBUG: {msg}")

# Nachher
import logging
logger = logging.getLogger(__name__)
logger.info("MCP Server gestartet")
logger.debug("Tool-Ergebnis verarbeitet")
logger.error("Fehler", exc_info=True)
```

#### 2. Funktionsaufteilung (SRP)
```python
# run_data_agent orchestriert nur noch:
async def run_data_agent(state):
    tools = await get_mcp_tools()
    agent = create_data_agent(tools)
    messages = prepare_messages(state, existing_datasets)  # Neue Funktion
    result = await execute_agent_with_retry(agent, messages)  # Neue Funktion
    data, meta, data_file = extract_tool_results(result)  # Neue Funktion
    return build_result(...)  # Neue Funktion
```

#### 3. Retry-Mechanismus
```python
async def execute_agent_with_retry(agent, messages, max_retries=3):
    for attempt in range(max_retries):
        try:
            return await agent.ainvoke({"messages": messages})
        except (ConnectionError, TimeoutError) as e:
            delay = 2 * (2 ** attempt)  # Exponential backoff
            await asyncio.sleep(delay)
    raise last_exception
```

#### 4. MCPToolsProvider Klasse
```python
class MCPToolsProvider:
    """Verwaltet MCP Tools mit Caching - testbar durch Dependency Injection."""
    
    async def get_tools(self) -> list:
        ...
    
    async def cleanup(self):
        ...
```

### Ergebnis
- Logging zeigt Timestamps, Level, Module
- Hauptfunktion von ~100 auf ~30 Zeilen reduziert
- Automatisches Retry bei Netzwerk-/Rate-Limit-Fehlern
- MCPToolsProvider kann in Tests gemockt werden

### Referenz
- `agents/data_agent.py`
- `agents/viz_agent.py`
- `agents/stats_agent.py`
- `agents/supervisor.py`
- `agents/utils.py` (NEU)

---

## 💡 IDEEN (noch nicht umgesetzt)

### IDEE-001: Dynamic Telemetry Key Discovery

**Problem:** Neue Keys in ThingsBoard werden vom Agent nicht verstanden.

**Recherche-Ergebnis (23.12.2025):**

| Ansatz | Pro | Contra |
|--------|-----|--------|
| **A: Discovery Tool** | Automatisch synchron, kein Prompt-Update | Zusätzlicher API-Call, LLM muss Key-Namen interpretieren |
| **B: Semantic Catalog** | LLM versteht Bedeutung, +27% Genauigkeit | Muss manuell gepflegt werden |
| **C: Dynamisches Prompt** | Immer aktuell, kein Extra-Call | Startup-Latenz, ThingsBoard-Abhängigkeit |

**Empfehlung:** Kombination A + B
- Discovery Tool für unbekannte Keys (existiert: `list_telemetry_keys`)
- Semantic Catalog (JSON) für bekannte Keys mit Beschreibungen

**Prompt-Erweiterung (Entwurf):**
```
## UNBEKANNTE KEYS
Wenn der User nach Daten fragt, die du nicht in TELEMETRIE-KEYS findest:
1. Rufe list_telemetry_keys auf
2. Suche semantisch passende Keys
3. Frage bei Unsicherheit nach: "Meinst du 'gripper_force_n' (Greiferkraft)?"
```

**Status:** Notiert, Umsetzung später
