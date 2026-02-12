# ENTSCHEIDUNGS-DATENBANK

> **Zweck:** Wiederverwendbare Patterns aus Projekt-Entscheidungen
> **Für:** Claude erkennt ähnliche Probleme und schlägt bewährte Lösungen vor
> **Stand:** 11. Februar 2026

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
| DEC-018 | API Key Rotation | Rate Limit (429) Errors | Round-Robin + Auto-Rotate bei 429 | Alle LLM-Aufrufe |
| DEC-019 | Beispiel-basierte State-Awareness | Agent ignoriert geladene Daten | Beispiele im Prompt statt Tool | Multi-Turn Konversationen |
| DEC-020 | Komprimierter Telemetry Lookup | Catalog ~10k Tokens im LLM-Context | Substring-Match in MCP Tool | Telemetrie-Key-Auflösung |
| DEC-021 | Prompt Caching (Rate Limit) | 30k ITPM bei Multi-Agent Pipeline | cache_control auf System Prompts | Alle LLM-Aufrufe |
| DEC-022 | Dynamische Few-Shot Dates | Falsches Jahr in Beispielen | Datums-Beispiele dynamisch generieren | Prompts mit Datumsangaben |
| DEC-023 | Query-Typ-basierte Daten | Zu wenig Punkte für Statistik | Raw für Stats, Aggregated für Viz | Korrelation, Statistik-Queries |
| DEC-024 | Timeseries Korrelation | IoT-Sensoren mit unterschiedlichen Timestamps | pd.merge_asof für Alignment | Korrelation zwischen Sensoren |
| DEC-025 | DuckDB Reference-only State | Rohdaten im AgentState sprengen Token-Limits | In-Memory DuckDB pro Session, nur DatasetMeta im State | Alle Datenzugriffe in Stats/Viz Agent |
| DEC-028 | Data Agent als Daten-Gatekeeper | Supervisor hat zu viel Detail-Wissen über Datasets | Data Agent läuft immer, setzt active_dataset_keys | Alle Turns mit Viz/Stats Agent |
| DEC-029 | Supervisor als Kontext-Instanz | Follow-up-Queries scheitern weil Konversationskontext fehlt | Strukturierte turn_history + Telemetrie-Referenz im Prompt | Multi-Turn Konversationen |

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
| "NIEMALS alle Keys abrufen!" | ~~"Rufe maximal 6-10 Keys ab"~~ ENTFERNT (03.02.2026) | Key-Limit unnötig: Agent sieht nur Statistics, Rohdaten gehen via DEC-004 in Datei |
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

## DEC-018: API Key Rotation für Rate Limit Handling

**Datum:** 28.01.2026

### Problem
Bei intensiver Nutzung (Multi-Agent Pipeline mit vielen Tool-Calls) wird das Anthropic API Rate Limit erreicht (HTTP 429). Das führt zu Wartezeiten und unterbrochenen Anfragen.

### Kontext
- Anthropic Rate Limits sind pro API Key
- Ein Stats Agent Aufruf kann 5-10 API Requests erzeugen
- Das SDK hat eingebautes Retry mit Backoff, aber nur mit demselben Key
- Best Practice: Mehrere Keys mit Round-Robin Rotation

### Entscheidung
**API Key Rotation mit automatischem Wechsel bei 429-Errors**

### Pattern

```python
# config/settings.py

class APIKeyRotator:
    """
    Round-Robin Rotation durch mehrere API Keys.
    Thread-safe für parallele Requests.
    """
    
    def __init__(self):
        keys_str = os.getenv("ANTHROPIC_API_KEYS", "")
        self.keys = [k.strip() for k in keys_str.split(",") if k.strip()]
        self._index = 0
        self._lock = threading.Lock()
    
    def get_key(self) -> str:
        """Gibt den aktuellen API Key zurück."""
        with self._lock:
            return self.keys[self._index]
    
    def rotate(self) -> str:
        """Wechselt zum nächsten Key."""
        with self._lock:
            self._index = (self._index + 1) % len(self.keys)
            return self.keys[self._index]

# Globale Instanz
api_key_rotator = APIKeyRotator()

def create_anthropic_client(model=DEFAULT_MODEL, temperature=0, **kwargs):
    """Erstellt Client mit aktuellem Key."""
    return ChatAnthropic(
        model=model,
        api_key=api_key_rotator.get_key(),
        temperature=temperature,
        **kwargs
    )
```

```python
# In Agents (data_agent.py, viz_agent.py, etc.)

async def execute_agent_with_retry(agent, messages, tools, max_retries=3):
    for attempt in range(max_retries):
        try:
            return await agent.ainvoke({"messages": messages})
        except Exception as e:
            if "429" in str(e).lower() or "rate limit" in str(e).lower():
                # Key rotieren und neuen Agent erstellen
                api_key_rotator.rotate()
                agent = create_data_agent(tools)  # Mit neuem Key
                await asyncio.sleep(delay)
            else:
                raise
```

```env
# .env
ANTHROPIC_API_KEYS=sk-key1...,sk-key2...,sk-key3...
```

### Begründung
- **3 Keys = 3x Rate Limits**: Effektive Kapazitätserhöhung
- **Automatische Rotation**: Bei 429-Error wird sofort der nächste Key verwendet
- **Thread-safe**: Wichtig für parallele Requests im Multi-Agent System
- **Rückwärtskompatibel**: `ANTHROPIC_API_KEY` funktioniert weiterhin als Fallback
- **Quellen**: Anthropic Rate Limit Docs, Best Practices für Multi-Key Rotation

### Betroffene Komponenten
- `config/settings.py` - APIKeyRotator Klasse, create_anthropic_client()
- `agents/data_agent.py` - execute_agent_with_retry() mit Key-Rotation
- `agents/viz_agent.py` - create_anthropic_client() statt ChatAnthropic
- `agents/stats_agent.py` - create_anthropic_client() statt ChatAnthropic
- `agents/supervisor.py` - create_anthropic_client() statt ChatAnthropic
- `agents/graph.py` - create_anthropic_client() statt ChatAnthropic
- `.env` - ANTHROPIC_API_KEYS mit komma-getrennten Keys

### Anwenden bei
- Alle LLM-Aufrufe im System
- Zukünftige Agents
- Jede Stelle die ChatAnthropic direkt erstellt

---

## DEC-019: Beispiel-basierte State-Awareness statt dediziertes Tool

**Datum:** 28.01.2026

### Problem
Bei Multi-Turn-Konversationen lädt der Data Agent Daten doppelt:
- Turn 1: "Zeig kartesische Position" → lädt pos_act_x/y/z
- Turn 2: "Korreliert das mit Orientierung?" → lädt pos_act_x/y/z UND pos_act_a/b/c (obwohl Position schon da)

Der Agent nutzt die `<loaded_data>` Information im Prompt nicht effektiv.

### Kontext
- Ursprünglicher Plan (AP7.1): Dediziertes `inspect_loaded_data()` Tool mit InjectedState
- Alternative: Beispiel-basierter Ansatz im Prompt
- LangGraph Best Practice: "Context Engineering" - Agent bekommt Info im Prompt
- Research: InjectedState Pattern ist für Daten-Übergabe, nicht für Entscheidungshilfe

### Entscheidung
**Beispiele im Prompt statt dediziertes Tool**

### Pattern

#### 1. Reicherer Dataset-Hint mit XML-Format
```python
def format_existing_datasets_hint(datasets: dict[str, Any]) -> str:
    """Formatiert Hint mit reicheren Infos."""
    if not datasets:
        return ""
    
    lines = ["<loaded_data>"]
    
    for key, dataset in datasets.items():
        meta = dataset.get("meta", {})
        data = dataset.get("data", {})
        stats = meta.get("statistics", {})
        timerange = meta.get("timerange", {})
        settings = meta.get("settings", {})
        
        lines.append(f"")
        lines.append(f"## {key}")
        lines.append(f"keys: {', '.join(list(data.keys())[:6])}")
        
        if timerange:
            lines.append(f"zeitraum: {timerange.get('start')} - {timerange.get('end')}")
        
        if settings:
            lines.append(f"einstellungen: {settings.get('aggregation_human')} alle {settings.get('interval_human')}")
        
        # Statistik-Preview für ersten Key
        if stats:
            first_key = next(iter(stats.keys()), None)
            if first_key:
                s = stats[first_key]
                lines.append(f"preview ({first_key}): {s.get('count')} Punkte, min={s.get('min')}, max={s.get('max')}, avg={s.get('avg')}")
    
    lines.append("</loaded_data>")
    return "\n".join(lines)
```

#### 2. Multi-Turn Beispiele im Prompt
```xml
<examples>
## Multi-Turn Beispiele

Beispiel 1 - Daten schon geladen:
<loaded_data>
## torque
keys: torque_act_a1_nm, torque_act_a2_nm
zeitraum: 2025-01-22T08:00 - 2025-01-22T17:00
</loaded_data>

User: "Zeig die Drehmomente nochmal"
→ Keine API-Abfrage nötig! Daten sind bereits in <loaded_data>.

Beispiel 2 - Korrelation, eine Seite fehlt:
<loaded_data>
## torque
keys: torque_act_a1_nm, torque_act_a2_nm
zeitraum: 2025-01-22T08:00 - 2025-01-22T17:00
</loaded_data>

User: "Gibt es einen Zusammenhang zwischen Position und Moment?"
→ torque ist schon geladen (siehe <loaded_data>)
→ Lade NUR axis_act_* für denselben Zeitraum

Beispiel 3 - Beide Datentypen fehlen:
<loaded_data>
(leer)
</loaded_data>

User: "Vergleiche Position und Geschwindigkeit"
→ Keine Daten geladen, lade beide auf einmal
</examples>
```

### Vergleich der Ansätze

| Kriterium | Tool-Ansatz | Beispiel-Ansatz |
|-----------|-------------|------------------|
| Extra API-Call | Ja (Kosten, Latenz) | Nein |
| Skalierbarkeit | Neue Tools = neuer Code | Neue Beispiele = Prompt-Update |
| Agent muss lernen | Tool aufzurufen | Beispiele zu verstehen |
| Komplexität | Höher (InjectedState) | Niedriger (nur Prompt) |
| Debugging | Tool-Call sichtbar | Implizit im Verhalten |

### Begründung
- **Kein Extra-API-Call**: Tool-Ansatz hätte bei jedem Turn einen zusätzlichen LLM-Call erzeugt
- **Beispiele skalieren besser**: Hardcoded Instruktionen ("Prüfe IMMER ZUERST...") werden vom LLM oft ignoriert
- **Context Engineering**: LangGraph empfiehlt, relevante Info direkt im Prompt bereitzustellen
- **Konsistenz mit DEC-015**: XML-Tags für strukturierte Prompt-Sektionen
- **Getestet**: Agent lädt bei "Korreliert das mit Orientierung?" nur die fehlenden Daten

### Anwenden bei
- Alle Agents die auf vorhandene State-Daten reagieren sollen
- Multi-Turn Szenarien mit Daten-Akkumulation
- Query-Interpretation basierend auf Kontext

### Referenz
- `agents/data_agent.py` - format_existing_datasets_hint()
- `prompts/data_agent_prompt.py` - Multi-Turn Beispiele
- `docs/AP7_AGENT_INTELLIGENCE.md` - AP7.1

---

## DEC-020: Komprimierter Telemetry Lookup statt Catalog im LLM-Context

**Datum:** 02.02.2026

### Problem
Der vollständige Telemetrie-Catalog (~10.000 Tokens) wurde bei JEDER Anfrage komplett ins LLM-Context geladen:

```
User: "Zeig mir die Gelenkwinkel"
  → get_attributes(keys="telemetry_catalog")  → ~10.000 Tokens ins Context
  → LLM durchsucht Catalog, findet "Gelenkwinkel" → axis_act_*
  → get_telemetry(keys="axis_act_a1_deg,...")
```

Bei einem Rate Limit von 30k Tokens/Minute führte das zu 429-Errors nach nur 2-3 Calls.

### Kontext
- Catalog: 13 Gruppen, 54 Keys, reichhaltige Beschreibungen (Sparkplug B Schema)
- Pro Query: ~13.500 Tokens (System Prompt + Catalog + Tool-Response)
- 2 Calls × 13.500 = 27.000 Tokens → Rate Limit fast ausgeschöpft
- Drei Alternativen evaluiert: Neo4j Graph-DB, Embedding-Suche, Komprimierter JSON

| Kriterium | Neo4j | Embedding Search | Komprimierter JSON |
|-----------|-------|------------------|--------------------|
| Setup-Aufwand | 🔴 Hoch | 🟡 Mittel | 🟢 Gering |
| Token-Reduktion | 🟢 ~200 Tokens | 🟢 ~200 Tokens | 🟢 ~200-500 Tokens |
| Genauigkeit | 🟡 Exact Match | 🟢 Semantisch | 🟡 Substring-Match |
| Wartbarkeit | 🟡 Extra Service | 🟡 Extra Dependency | 🟢 Kein Extra |
| Thesis-Wert | 🟢 Innovativ | 🟡 Standard-RAG | 🔴 Trivial |

Neo4j als optionaler Ausblick für Evaluation notiert (bei >500 Keys sinnvoll).

### Entscheidung
**Komprimierter Lookup-Index + neues MCP-Tool `search_telemetry_keys` mit Substring-Matching**

### Pattern

#### 1. Lookup-Index (`config/telemetry_lookup.json`)
```json
{
  "groups": {
    "axis_position": {
      "name": "Achspositionen (Soll)",
      "aliases": ["position", "gelenkwinkel", "achswinkel", ...],
      "unit": "°",
      "keys": ["axis_act_a1_deg", "axis_act_a2_deg", ...],
      "description": "Soll-Achswinkel A1-A6 ($AXIS_ACT)"
    }
  }
}
```

#### 2. Neues MCP-Tool
```python
@mcp.tool()
async def search_telemetry_keys(query: str) -> str:
    """
    Findet passende Telemetrie-Keys basierend auf einem Suchbegriff.
    IMMER VOR get_telemetry, wenn der User natürlichsprachliche Begriffe verwendet.
    """
    matches = search_lookup(query)  # Substring-Match
    
    if matches:
        return {"status": "found", "matches": matches}     # ~200 Tokens
    else:
        return {"status": "no_match", "available_groups": overview}  # ~300 Tokens
```

#### 3. Substring-Match Strategie
```python
def search_lookup(query: str) -> list[dict]:
    query_lower = query.lower().strip()
    for group_id, group_data in _telemetry_lookup.items():
        aliases = group_data.get("aliases", [])
        # query in alias ODER alias in query (case-insensitive)
        matched = any(
            query_lower in alias or alias in query_lower
            for alias in aliases
        )
```

#### 4. Fallback bei keinem Match (3B-minimal)
```json
{
  "status": "no_match",
  "hint": "Kein direkter Treffer. Versuche es mit einem der Aliases.",
  "available_groups": [
    {"group": "axis_position", "aliases": ["position", "gelenkwinkel", ...], "unit": "°"},
    {"group": "torque_actual", "aliases": ["moment", "drehmoment", ...], "unit": "Nm"}
  ]
}
```
Enthält KEINE Keys — LLM soll mit besserem Alias nochmal suchen.

### Ergebnis (gemessen)

| Metrik | Vorher | Nachher | Reduktion |
|--------|--------|---------|----------|
| Tokens pro Key-Lookup | ~10.000 | ~200 | **98%** |
| Prompt-Sektion | ~600 Tokens (`<semantic_catalog>`) | ~300 Tokens (`<key_lookup>`) | 50% |
| LLM-Calls bis Rate Limit | 2-3 | 10+ | 3-5x mehr |
| Tool-Calls pro Query | 2 (catalog + telemetry) | 2 (search + telemetry) | gleich |

### Neuer Flow
```
User: "Zeig mir die Gelenkwinkel"
  → search_telemetry_keys(query="Gelenkwinkel")  → ~200 Tokens
  → Ergebnis: {"group": "axis_position", "keys": ["axis_act_a1_deg", ...]}
  → get_telemetry(keys="axis_act_a1_deg,...")
```

### Betroffene Komponenten
- `config/telemetry_lookup.json` — **NEU** — Komprimierter Lookup-Index
- `mcp_servers/thingsboard_server.py` — Neues Tool + Lookup-Funktionen
- `prompts/data_agent_prompt.py` — `<semantic_catalog>` → `<key_lookup>`
- `config/krc5_telemetry_catalog.json` — Unverändert (bleibt Source of Truth)

### Begründung
- **Pragmatisch**: Löst das Rate-Limit-Problem sofort ohne neue Infrastruktur
- **Konsistent mit DEC-001**: Tool-Description mit "WANN/NICHT BENUTZEN"
- **Konsistent mit DEC-004**: Große Daten nicht durch LLM-Prompt schleusen
- **Erweiterbar**: Neo4j oder Embedding-Suche können später den Substring-Match ersetzen
- **Single Source of Truth**: `krc5_telemetry_catalog.json` bleibt die Referenz

### Anwenden bei
- Alle Telemetrie-Anfragen mit natürlicher Sprache
- Zukünftige Erweiterung: Neue Roboter-Modelle mit eigenem Lookup
- Generell: Große Kataloge/Metadaten die das LLM durchsuchen müsste

### Referenz
- `config/telemetry_lookup.json`
- `mcp_servers/thingsboard_server.py` — Abschnitt "TELEMETRY LOOKUP INDEX"
- `prompts/data_agent_prompt.py` — Abschnitt `<key_lookup>`

---

## DEC-021: Prompt Caching für Rate-Limit-Optimierung

> **Status:** ✅ IMPLEMENTIERT (Alle Agents)
> **Datum:** 03. Februar 2026
> **Auslöser:** 429 Errors bei Multi-Agent Pipelines (data_agent + stats_agent)

### Problem/Kontext

Das System stößt bei komplexen Queries (z.B. Korrelationsanalyse mit Datenabruf + Statistik) trotz DEC-018 (Key Rotation, 3 Keys) und DEC-020 (Lookup-Optimierung) ans Rate Limit:

```
Organization rate limit: 30.000 Input Tokens per Minute (Tier 1)
3 Keys × 30k = 90k/min theoretisch, aber Token-Bucket pro Organisation
```

**Beobachteter Fehler-Flow (02.02.2026):**
```
Supervisor:   1 Call  (~3.000 Tokens) ✅
Data Agent:   3 Calls (~4.000-5.000 Tokens je) ✅
Stats Agent:  1. Call → 429 (Key 1) → 429 (Key 2) → ✅ (Key 3)
Stats Agent:  2. Call → 429 (Key 3, alle verbraucht) → Fallback lokal
Stats Agent:  3. Call → 429
```

**Ursache:** Jeder der 6-8 LLM-Calls einer Pipeline sendet den **vollen System Prompt + Tool-Definitionen** (~3.500 Tokens). Bei 7 Calls = ~24.500 Tokens allein für statische Inhalte.

### Alternativen-Bewertung

| Kriterium | A: Prompt Caching | B: Prompt-Komprimierung | C: Inter-Agent Delay |
|-----------|-------------------|--------------------------|----------------------|
| Rate-Limit-Reduktion | 🟢 ~80% (gecached zählt nicht) | 🟡 ~30-40% | 🟡 Zeitliche Verteilung |
| Implementierungsaufwand | 🟡 Moderat (Client anpassen) | 🟢 Gering (Prompts kürzen) | 🟢 Trivial (sleep) |
| Latenz-Auswirkung | 🟢 Schneller (Cache-Read) | 🟢 Neutral | 🔴 Langsamer (~3x) |
| Qualitäts-Risiko | 🟢 Keines | 🟡 Weniger Kontext | 🟢 Keines |
| Von Anthropic empfohlen | 🟢 Ja, offiziell | 🟡 Allgemeine Best Practice | 🟡 Workaround |
| Kosten-Auswirkung | 🟢 90% billiger für Reads | 🟢 Weniger Tokens = billiger | 🟢 Neutral |

### Entscheidung: Option A — Prompt Caching

Ergänzend Option B für niedrig hängende Früchte.

### Wie Prompt Caching funktioniert

**Anthropic Cache-Aware Rate Limits (seit 2025):**
- `cache_read_input_tokens` zählen **NICHT** gegen das ITPM-Limit
- Nur `input_tokens` (uncached) zählen
- Cache-TTL: 5 Minuten (Standard) oder 1 Stunde
- Minimum: 1.024 Tokens für Cache-Breakpoint
- Kosten: Cache-Write = 25% Aufpreis, Cache-Read = 90% Rabatt

**Prinzip:**
```
1. Call: System Prompt (3.500 Tokens) → Cache-Write → zählt als Input
2. Call: System Prompt → Cache-Read → zählt NICHT gegen ITPM!
3.-7. Call: Alle Cache-Read → zählen NICHT

Effektiv: Statt 7 × 3.500 = 24.500 Tokens → nur 1 × 3.500 = 3.500 Tokens
```

### Implementierung

**Umgesetzt (03.02.2026):**

```python
# config/settings.py - Hilfsfunktion für Prompt Caching

def create_cached_system_message(content: str):
    """
    SystemMessage mit cache_control für Prompt Caching (DEC-021).

    WICHTIG: content muss als list[dict] formatiert werden, damit LangChain
    das cache_control korrekt an die Anthropic API weitergibt.
    (Siehe: https://github.com/langchain-ai/langchain/issues/26701)
    """
    from langchain_core.messages import SystemMessage
    return SystemMessage(
        content=[{
            "type": "text",
            "text": content,
            "cache_control": {"type": "ephemeral"}
        }]
    )

# create_anthropic_client() mit Caching-Header
PROMPT_CACHING_HEADERS = {"anthropic-beta": "prompt-caching-2024-07-31"}

def create_anthropic_client(model=DEFAULT_MODEL, temperature=0, enable_caching=True, **kwargs):
    model_kwargs = kwargs.pop("model_kwargs", {})
    if enable_caching:
        existing_headers = model_kwargs.get("extra_headers", {})
        existing_headers.update(PROMPT_CACHING_HEADERS)
        model_kwargs["extra_headers"] = existing_headers

    return ChatAnthropic(
        model=model,
        api_key=api_key_rotator.get_key(),
        temperature=temperature,
        model_kwargs=model_kwargs if model_kwargs else None,
        **kwargs
    )
```

**Angepasste Komponenten:**
- ✅ `config/settings.py` — `create_cached_system_message()`, Header in `create_anthropic_client()`
- ✅ `agents/supervisor.py` — Nutzt `create_cached_system_message()`
- ✅ `agents/graph.py` (respond_node) — Nutzt `create_cached_system_message()`
- ✅ `agents/data_agent.py` — `prepare_messages()` nutzt `create_cached_system_message()`
- ✅ `agents/stats_agent.py` — Nutzt `create_cached_system_message()`
- ✅ `agents/viz_agent.py` — `select_and_execute_tool()` nutzt `create_cached_system_message()`

**Verifizierung:**
- Response-Headers prüfen: `cache_creation_input_tokens` vs `cache_read_input_tokens`
- Im Logging auf Cache-Hit-Rate achten

### Erwartete Auswirkung

| Metrik | Vorher (DEC-020) | Nachher (DEC-021) | Verbesserung |
|--------|------------------|-------------------|--------------|
| ITPM pro Pipeline | ~30.000 | ~6.000 | ~80% |
| Queries vor Rate Limit | 1-2 (komplex) | 5-10 (komplex) | 3-5x |
| Kosten pro Pipeline | ~100% | ~40% (Cache-Reads) | ~60% |
| Latenz | Baseline | Schneller (Cache) | ~15-20% |

### Betroffene Komponenten
- `config/settings.py` — `create_anthropic_client()` ggf. anpassen
- `agents/supervisor.py` — System Prompt mit cache_control
- `agents/data_agent.py` — System Prompt mit cache_control
- `agents/stats_agent.py` — System Prompt mit cache_control
- `agents/viz_agent.py` — System Prompt mit cache_control

### Begründung
- **Offiziell empfohlen**: Anthropic Blog "Token-saving updates" (Feb 2025)
- **Konsistent mit DEC-018**: Key Rotation bleibt als Fallback aktiv
- **Konsistent mit DEC-020**: Lookup-Optimierung reduziert die uncached Tokens weiter
- **LangChain-Support**: `ChatAnthropic` unterstützt `cache_control` in Messages nativ
- **Thesis-relevant**: Zeigt systematische Optimierungsstrategie über mehrere Ebenen

### Quellen
- https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
- https://www.anthropic.com/news/token-saving-updates
- https://docs.langchain.com/oss/python/integrations/chat/anthropic
- Anthropic Rate Limits Doku: Cache-Read Tokens zählen nicht gegen ITPM

### Anwenden bei
- Alle Agents mit statischen System Prompts
- Multi-Agent Pipelines mit sequentiellen LLM-Calls
- Generell: Wiederholte Calls mit gleichem Prompt-Präfix

---

## DEC-022: Dynamische Datumsangaben in Few-Shot Examples

> **Status:** ✅ IMPLEMENTIERT
> **Datum:** 03. Februar 2026
> **Auslöser:** LLM verwendete falsches Jahr (2025 statt 2026) bei Datumsberechnungen

### Problem/Kontext

Bei der Anfrage "Gibt es eine Korrelation zwischen Drehmoment und Position" verwendete der Data Agent das falsche Jahr:

```
Erster Versuch: 2025-01-29 12:00 → 0 Datenpunkte (falsches Jahr!)
Zweiter Versuch: 2026-01-29 12:00 → 72 Datenpunkte (korrekt)
```

**Ursache:** Der Prompt injizierte das aktuelle Datum korrekt in `<context>`, aber die Few-Shot Examples enthielten hardcoded Jahreszahlen von 2025. Das LLM folgte dem Muster aus den Beispielen statt dem aktuellen Jahr.

**Recherche-Ergebnisse:**

| Quelle | Empfehlung |
|--------|-----------|
| [OpenAI Community](https://community.openai.com/t/how-do-we-make-llm-understand-the-context-of-time/328978) | "Inject the current date into prompts programmatically" |
| [Anthropic Docs](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/multishot-prompting) | "Match **every detail** in examples to desired output - Claude replicates patterns" |
| [Lakera Guide](https://www.lakera.ai/blog/prompt-engineering-guide) | "Ambiguity is the most common cause of poor LLM output" |

### Entscheidung

**Alle Datumsangaben in Few-Shot Examples dynamisch generieren**

### Pattern

```python
def get_data_agent_prompt() -> str:
    now = datetime.now()
    current_year = now.year

    # "16. Dezember" → korrektes Jahr basierend auf aktuellem Datum
    if now.month >= 12 and now.day >= 16:
        example_dec_16 = f"{current_year}-12-16"
    else:
        example_dec_16 = f"{current_year - 1}-12-16"

    # Letzter Dienstag für Wochentag-Beispiel
    days_since_tuesday = (now.weekday() - 1) % 7
    if days_since_tuesday == 0:
        days_since_tuesday = 7
    last_tuesday = now - timedelta(days=days_since_tuesday)
    last_tuesday_date = last_tuesday.strftime('%Y-%m-%d')

    # Beispiel-Arbeitstag für Multi-Turn Examples
    example_workday = now - timedelta(days=5)
    example_workday_date = example_workday.strftime('%Y-%m-%d')

    return f"""
    ...
    | "16. Dezember" | {example_dec_16} | {example_dec_16} | 00:00 | 23:59 |
    | "Dienstag 13-16 Uhr" | {last_tuesday_date} | {last_tuesday_date} | 13:00 | 16:00 |
    ...
    zeitraum: {example_workday_date}T08:00 - {example_workday_date}T17:00
    """
```

### Geänderte Stellen

| Zeile (vorher) | Hardcoded | Dynamisch |
|----------------|-----------|-----------|
| "16. Dezember" Beispiel | `2025-12-16` | `{example_dec_16}` |
| Dienstag-Beispiel | `(letzter Di)` | `{last_tuesday_date}` |
| Multi-Turn zeitraum | `2025-01-22T08:00` | `{example_workday_date}T08:00` |
| Beispiel-Antwort Datum | `16.12.2025` | `{example_dec_16_human}` |

### Begründung

- **Anthropic Best Practice**: "Claude replicates naming conventions, code style, formatting" - das gilt auch für Datumsformate
- **Konsistenz**: Alle Beispiele zeigen nun das korrekte Jahr, das mit dem `<context>` übereinstimmt
- **Keine Ambiguität**: LLM muss nicht zwischen Context und Examples "wählen"
- **Robust**: Funktioniert auch am Jahreswechsel korrekt

### Anwenden bei

- Alle Prompts mit Few-Shot Examples die Datumsangaben enthalten
- Prompts mit temporalen Berechnungen
- Generell: Wenn Examples mit dynamischem Context konsistent sein müssen

### Referenz

- `prompts/data_agent_prompt.py` - Zeilen 37-55 (dynamische Variablen), Examples-Sektion
- [Anthropic Multishot Prompting Docs](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/multishot-prompting)

---

## DEC-023: Query-Typ-basierte Datenstrategie (Raw vs. Aggregated)

> **Status:** ✅ IMPLEMENTIERT
> **Datum:** 03. Februar 2026
> **Auslöser:** Korrelationsanalyse mit nur 24 Datenpunkten statistisch unzuverlässig

### Problem/Kontext

Bei einer 4-Stunden-Abfrage für Korrelationsanalyse werden nur **24 Datenpunkte** pro Key geliefert (10-Minuten-Aggregation). Das ist statistisch zu wenig:

```
Query: "Gibt es Korrelation zwischen Drehmoment und Position?"
Zeitraum: 4 Stunden (12:00 - 16:00)
Ergebnis: 24 Punkte pro Key → r=0.446 (unsicher!)
```

**Statistische Anforderungen (Forschung):**

| Ziel-Korrelation | Min. Sample Size (α=0.05, Power=80%) |
|------------------|--------------------------------------|
| r = 0.5 | 29-37 Punkte |
| r = 0.3 | **84 Punkte** |
| r = 0.1 | 782 Punkte |

**Quellen:**
- [PMC - Sample Size for Correlation Analysis](https://pmc.ncbi.nlm.nih.gov/articles/PMC11148401/)
- [ResearchGate - Sample Size Guideline](https://www.researchgate.net/publication/310735983_Sample_Size_Guideline_for_Correlation_Analysis)

### Recherche: Industry Best Practice

**InfluxDB/TimescaleDB Tiered Approach:**
> "Keep recent data in **high granularity** for detailed analysis, while storing older data in **aggregated form** to save space."

**Wann Raw vs. Aggregated:**

| Use Case | Empfehlung | Grund |
|----------|------------|-------|
| Korrelation/Statistik | **Raw** | Braucht echte Varianz, nicht geglättete Werte |
| Trend-Visualisierung | Aggregated | Glättet Noise, bessere Lesbarkeit |
| Anomalie-Erkennung | Raw | Details wichtig |
| Langzeit-Dashboard | Aggregated | Performance |

**Quellen:**
- [InfluxDB - Downsample and Retain](https://docs.influxdata.com/influxdb/v1/guides/downsample_and_retain/)
- [Quix - Downsampling Data Processing](https://quix.io/glossary/downsampling-data-processing)
- [TechTarget - IoT Data Collection](https://www.techtarget.com/iotagenda/post/IoT-data-collection-When-time-is-of-the-essence)

### Entscheidung

**Query-Typ-basierte Datenstrategie:**

```
┌─────────────────────────────────────────────────────────────┐
│                    Supervisor: Query-Typ                    │
│                                                             │
│  Stats-Query? (Korrelation, Statistik, Vergleich)           │
│     → data_retrieval_mode: "raw"                            │
│                                                             │
│  Viz-Query? (Chart, Trend, Verlauf)                         │
│     → data_retrieval_mode: "aggregated"                     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                 Data Agent: Strategie-Auswahl               │
│                                                             │
│  mode="raw" + Zeitraum ≤ 24h:                               │
│     → get_telemetry() mit limit=10000                       │
│                                                             │
│  mode="raw" + Zeitraum > 24h:                               │
│     → Feinere Aggregation (1m statt 10m)                    │
│                                                             │
│  mode="aggregated":                                         │
│     → Wie bisher (DEC-006 Auto-Aggregation)                 │
└─────────────────────────────────────────────────────────────┘
```

### Implementierungsplan

#### Task 1: State erweitern
**Datei:** `agents/state.py`

```python
class AgentState(MessagesState):
    # ... existing fields ...
    data_retrieval_mode: str = "aggregated"  # "raw" | "aggregated"
```

#### Task 2: Supervisor Query-Typ-Erkennung
**Datei:** `agents/supervisor.py` + `prompts/supervisor_prompt.py`

Supervisor setzt `data_retrieval_mode` basierend auf Query-Analyse:
- Keywords: "Korrelation", "Zusammenhang", "Statistik", "Vergleich" → `"raw"`
- Keywords: "zeig", "Chart", "Verlauf", "Trend" → `"aggregated"`
- Default: `"aggregated"`

#### Task 3: ThingsBoard Client - Raw Data Support
**Datei:** `mcp_servers/thingsboard_server.py`

Neuer Parameter `raw: bool = False` für `get_telemetry`:

```python
@mcp.tool()
async def get_telemetry(
    keys: str,
    start_date: str,
    end_date: str,
    # ... existing params ...
    raw: bool = False,  # NEU: Rohdaten ohne Aggregation
) -> str:
    if raw:
        # Berechne erwartete Punkte
        expected_points = calculate_raw_points(start_dt, end_dt, sampling_rate=1)

        if expected_points <= 10000:
            # Rohdaten holen
            data = await client.get_telemetry(device_id, key_list, start_ts, end_ts, limit=10000)
        else:
            # Fallback: Feinste mögliche Aggregation
            interval_ms = calculate_min_interval_for_limit(start_dt, end_dt, limit=10000)
            data = await client.get_telemetry_aggregated(...)
    else:
        # Wie bisher (DEC-006)
        data = await client.get_telemetry_aggregated(...)
```

#### Task 4: Data Agent - Mode-Awareness
**Datei:** `agents/data_agent.py` + `prompts/data_agent_prompt.py`

Data Agent liest `data_retrieval_mode` aus State und setzt `raw=True/False`:

```python
async def run_data_agent(state: AgentState):
    mode = state.get("data_retrieval_mode", "aggregated")
    # ... pass mode to tool selection logic ...
```

Prompt-Erweiterung:
```xml
<data_mode>
Aktueller Modus: {data_retrieval_mode}

Bei mode="raw":
- Setze raw=True bei get_telemetry
- Wichtig für statistische Analysen (Korrelation, Regression)
- Mehr Datenpunkte = genauere Ergebnisse

Bei mode="aggregated":
- Nutze Auto-Aggregation (Standard)
- Gut für Visualisierungen und Trends
</data_mode>
```

#### Task 5: Response-Anpassung
**Datei:** `mcp_servers/thingsboard_server.py`

Erweiterte Response mit Info über Datenmodus:

```python
summary = {
    "status": "success",
    "data_mode": "raw" if raw else "aggregated",
    "data_points": {...},
    "statistics": stats,
    # Bei raw: Info über tatsächliche Sampling-Rate
    "sampling_info": {
        "mode": "raw",
        "actual_points": total_points,
        "time_resolution": "~1 Sekunde" if raw else interval_human,
    },
}
```

### Erwartete Ergebnisse

| Metrik | Vorher | Nachher |
|--------|--------|---------|
| Punkte für 4h Stats-Query | 24 | **bis 10.000** |
| Korrelations-Zuverlässigkeit | Gering | **Hoch** |
| Viz-Query Performance | ✅ | ✅ (unverändert) |

### Betroffene Komponenten

| Datei | Änderung |
|-------|----------|
| `agents/state.py` | `data_retrieval_mode` Field |
| `agents/supervisor.py` | Query-Typ-Erkennung |
| `prompts/supervisor_prompt.py` | Mode-Selection Instructions |
| `mcp_servers/thingsboard_server.py` | `raw` Parameter + Logik |
| `agents/data_agent.py` | Mode aus State lesen |
| `prompts/data_agent_prompt.py` | Mode-Awareness |

### Rückwärtskompatibilität

- Default `data_retrieval_mode="aggregated"` → Verhalten wie bisher
- Bestehende Viz-Queries unverändert
- Nur Stats-Queries bekommen mehr Daten

### Anwenden bei

- Korrelationsanalysen
- Statistische Vergleiche
- Regressionsanalysen
- Anomalie-Erkennung (zukünftig)

---

## DEC-024: Timeseries Korrelation mit merge_asof

> **Status:** ✅ IMPLEMENTIERT
> **Datum:** 03. Februar 2026
> **Auslöser:** DEC-023 liefert nun >10k Datenpunkte, aber Arrays haben unterschiedliche Längen (x=100, y=98)

### Problem/Kontext

Nach Implementierung von DEC-023 (Raw Mode) liefert der Data Agent nun >10.000 Datenpunkte für Korrelationsanalysen. Allerdings haben IoT-Sensoren unterschiedliche Abtastfrequenzen und Timing-Jitter:

```
torque_act_a1_nm: 100 Datenpunkte bei t=[1000, 2001, 3002, ...]
axis_act_a1_deg:   98 Datenpunkte bei t=[1010, 2005, 3008, ...]
```

**Fehler:** `calculate_correlation()` erforderte gleiche Array-Längen:
```python
if len(x_values) != len(y_values):
    return {"error": f"Ungleiche Längen: x={len(x_values)}, y={len(y_values)}"}
```

### Recherche: Best Practice für IoT Time Series Alignment

**pandas merge_asof:**
> "Perform an asof merge. This is similar to a left-join except that we match on nearest key rather than equal keys."

**Warum ideal für IoT-Daten:**
1. **Toleranz-basiert** - Matcht nur wenn Timestamps innerhalb Schwelle
2. **Nearest Match** - Findet nächsten Zeitpunkt (vor oder nach)
3. **Kein Interpolieren** - Verwendet echte Sensorwerte
4. **Effizient** - O(n log n) für sortierte Daten

**Alternativen (verworfen):**
| Ansatz | Problem |
|--------|---------|
| Resample + Interpolation | Verändert echte Messwerte |
| Index-Alignment | Funktioniert nur bei gleicher Länge |
| Zeitbereich-Buckets | Verliert Präzision |

### Entscheidung

**Neue Funktion `calculate_correlation_timeseries()` mit pd.merge_asof:**

```python
def calculate_correlation_timeseries(
    x_timestamps: list[int], x_values: list[float],
    y_timestamps: list[int], y_values: list[float],
    tolerance_ms: int = 1000,
) -> dict[str, Any]:
    """
    Korrelation für Zeitreihen mit unterschiedlichen Timestamps.
    Nutzt pd.merge_asof für Alignment innerhalb tolerance_ms.
    """
    df_x = pd.DataFrame({"ts": x_timestamps, "x": x_values}).sort_values("ts")
    df_y = pd.DataFrame({"ts": y_timestamps, "y": y_values}).sort_values("ts")

    merged = pd.merge_asof(
        df_x, df_y, on="ts",
        tolerance=tolerance_ms,
        direction="nearest",
    )

    merged_clean = merged.dropna()  # Entferne ungematchte Punkte

    if len(merged_clean) < 3:
        return {"error": "Zu wenige überlappende Datenpunkte", ...}

    r, p = pearsonr(merged_clean["x"], merged_clean["y"])
    return {
        "r": r, "p_value": p,
        "n_matched": len(merged_clean),
        "n_dropped": len(df_x) - len(merged_clean),
        ...
    }
```

### Wie es funktioniert

```
Sensor X: ts=[1000, 2000, 3000, 4000]  → 4 Punkte
Sensor Y: ts=[1010, 2005, 3020]        → 3 Punkte (1 fehlt!)

merge_asof mit tolerance=1000ms:
- x@1000 → y@1010 (diff=10ms) ✓
- x@2000 → y@2005 (diff=5ms) ✓
- x@3000 → y@3020 (diff=20ms) ✓
- x@4000 → kein y in Nähe → NaN (wird entfernt)

Ergebnis: 3 gematchte Paare für Korrelation
```

### Implementierung

**Datei:** `tools/stats_functions.py`
- `calculate_correlation_timeseries()` ersetzt das alte `calculate_correlation()`
- Alte Funktion wurde entfernt (keine Rückwärtskompatibilität nötig)

**Datei:** `agents/stats_agent.py`
- Komplett umgebaut auf InjectedState Pattern (wie Viz Agent)
- `correlation_tool(key_x, key_y, state)` mit manuellem State-Injection
- MCP Server wird nicht mehr verwendet

### Parameter

| Parameter | Default | Beschreibung |
|-----------|---------|--------------|
| `tolerance_ms` | 1000 | Max. erlaubte Zeitdifferenz für Match |

### Response-Format

```python
{
    "r": 0.847,
    "r_squared": 0.717,
    "p_value": 0.0001,
    "interpretation": "stark positiv",
    "n_matched": 98,      # Erfolgreich gematchte Paare
    "n_dropped": 2,       # Punkte ohne Match
    "n_x": 100,           # Original X-Länge
    "n_y": 98,            # Original Y-Länge
    "match_rate": 98.0,   # Prozent erfolgreich
    "tolerance_ms": 1000,
}
```

### Anwenden bei

- Korrelation zwischen verschiedenen Sensor-Typen
- IoT-Daten mit unterschiedlichen Abtastraten
- Zeitreihen mit Timing-Jitter (±10-50ms)

---

## DEC-025: DuckDB Reference-only State

### Problem
Rohdaten (Tausende Datenpunkte als `[{value, timestamp}, ...]`) werden im `AgentState` gespeichert und bei jedem Agent-Hop kopiert. Das führt zu:
- Token-Limit-Problemen bei großen Zeitreihen
- Langsamer State-Serialisierung im Checkpointer
- Keine effiziente Aggregation oder Joins auf den Rohdaten möglich

### Kontext
- Bisheriger Ansatz: `datasets = {"torque": {"data": {"torque_a1": [{...}, ...]}, "meta": {...}}}`
- DEC-004 speichert bereits Rohdaten als Datei, aber Stats/Viz Agent lesen trotzdem aus State
- Alternativen: Redis, SQLite, Pandas DataFrames im State
- DuckDB bietet SQL-Analytik (AVG, ASOF JOIN, Window Functions) direkt in-memory

### Entscheidung
**In-Memory DuckDB pro Chat-Session als analytischer Datenspeicher. AgentState hält nur noch `DatasetMeta` (Metadaten + Referenz), keine Rohdaten mehr.**

### Pattern

**1. SessionStore (Singleton pro Session):**
```python
from config.duckdb_store import SessionStore

# Erstellen (in app.py bei Chat-Start)
store = SessionStore.get_instance(session_id)

# Daten speichern (in data_agent.py)
store.store_dataset(dataset_key, data_dict)
# data_dict = {"torque_a1_nm": [{"value": "25.3", "timestamp": 1703001234567}, ...]}

# Abfragen (in stats/viz tools)
values = store.get_values(dataset_key, signal_key)
ts, vals = store.get_timeseries(dataset_key, signal_key)
result = store.query("SELECT AVG(value) FROM telemetry WHERE signal_key = ?", [key])

# Aufräumen (Session-Ende)
SessionStore.destroy(session_id)
```

**2. DatasetMeta statt Rohdaten im State:**
```python
class DatasetMeta(TypedDict, total=False):
    dataset_key: str          # UNS-Key: "krc5/torque/timeseries/2h"
    device_id: str
    keys: list[str]           # ["torque_act_a1_nm", "torque_act_a2_nm"]
    point_count: int
    timerange: dict           # {"start": ..., "end": ...}
    retrieval_mode: str       # "raw" | "aggregated"
    unit: str
    created_at: str           # ISO 8601

# State enthält nur noch Meta:
datasets = {"torque": DatasetMeta}  # statt {"torque": {"data": {...}, "meta": {...}}}
```

**3. DuckDB-first Helpers (utils.py):**
```python
from agents.utils import get_data_from_state, get_values_for_key

# In allen Stats/Viz Tools:
data = get_data_from_state(state)          # DuckDB → Legacy Fallback
values = get_values_for_key(state, key)    # DuckDB → Legacy Fallback
ts, vals = get_timeseries_for_key(state, key)
keys = get_available_signal_keys(state)
```

**4. UNS-inspirierte Dataset-Keys:**
```python
from config.duckdb_store import generate_dataset_key

key = generate_dataset_key("krc5", "torque", "timeseries", "2h")
# → "krc5/torque/timeseries/2h"
```

### DuckDB Schema
```sql
CREATE TABLE telemetry (
    dataset_key TEXT,
    signal_key TEXT,
    ts BIGINT,        -- Unix Timestamp in ms
    value DOUBLE,
    unit TEXT
)
```

### Begründung
- **Keine Token-Kosten:** Rohdaten nie im LLM-Kontext, nur DatasetMeta (~200 Tokens vs. ~50k)
- **SQL-Analytik:** `AVG`, `PERCENTILE`, `ASOF JOIN` direkt auf DB statt Python-Loops
- **Session-Isolation:** Jede Chat-Session hat eigene `:memory:` DB, kein Crosstalk
- **Backward-kompatibel:** DuckDB-first Helpers fallen auf Legacy-Format zurück
- **UNS-Keys:** Vorbereitung für Multi-Device-Fähigkeit (`device/signal_type/data_type/temporal`)

### Implementierung

| Datei | Änderung |
|-------|----------|
| `config/duckdb_store.py` | NEU — SessionStore, generate_dataset_key, determine_signal_type |
| `agents/state.py` | DatasetMeta TypedDict, session_id in AgentState |
| `agents/data_agent.py` | build_result() schreibt DuckDB, gibt DatasetMeta zurück |
| `agents/stats_agent.py` | Alle 8 Tools nutzen DuckDB-first Helpers |
| `agents/viz_agent.py` | Alle 10 Chart-Tools nutzen get_data_from_state() |
| `agents/utils.py` | 4 neue DuckDB-first Helpers + Legacy-Fallback |
| `agents/graph.py` | respond_node + run_query() mit session_id |
| `app.py` | SessionStore Lifecycle (create bei Chat-Start) |
| `tests/test_duckdb_store.py` | 35 Tests für Store, Schema, UNS-Keys, ASOF JOIN |

### Anwenden bei

- Alle neuen Tools die auf Telemetrie-Daten zugreifen → `get_data_from_state(state)` verwenden
- Neue Agents die Daten laden → `SessionStore.store_dataset()` statt State-Dict
- Komplexe Aggregationen → SQL-Query statt Python-Loop
- Multi-Device-Erweiterungen → UNS-Key-Schema nutzen

### Referenz
- `config/duckdb_store.py` — SessionStore Implementation
- `agents/utils.py` — DuckDB-first Helpers
- `agents/state.py:DatasetMeta` — TypedDict Definition
- `tests/test_duckdb_store.py` — 35 Unit Tests

---

## DEC-028: Data Agent als Daten-Gatekeeper

### Problem
Der Supervisor setzt `active_dataset_keys` — dafür sieht er über `build_dataset_context()` die vollen Dataset-Keys mit Metadaten (Signals, Punkte, Zeitraum, Modus). Das ist dieselbe Art "zu viel Wissen" die beim Data Agent zu Bias führte (DEC-027). Der Supervisor trifft Detail-Entscheidungen über Datenbestände, obwohl er nur planen sollte.

### Kontext
- Orchestrator-Worker Pattern (LangGraph Best Practice): Supervisor entscheidet WAS, Worker entscheidet WIE
- Bisher: Supervisor wählt `active_dataset_keys` aus vollen Dataset-Metadaten → Bias-Gefahr
- Bisher: `validate_plan()` fügt `data_agent` nur ein wenn KEINE Datasets vorhanden → bei Folge-Turns fehlt Filterung
- `check_dataset` Tool im Data Agent kann DuckDB direkt abfragen

### Entscheidung
**Data Agent läuft IMMER wenn Downstream-Agents (viz/stats) Daten brauchen. Nur der Data Agent kennt die DuckDB-Datenbank und setzt `active_dataset_keys`.**

### Pattern

**1. Supervisor: Reset + kompakter Kontext**
```python
# Supervisor gibt IMMER active_dataset_keys=None zurück (Reset)
return {
    "plan": final_plan,
    "active_dataset_keys": None,  # Data Agent setzt neu
    ...
}

# build_dataset_context() zeigt nur Summary, keine Keys
def build_dataset_context(datasets, data_summary):
    return f"## VORHANDENE DATEN\n{data_summary}"
```

**2. validate_plan(): Data Agent immer einfügen**
```python
# Alt: if needs_data and not has_data_agent and not has_datasets
# Neu: has_datasets Check entfernt
if needs_data and not has_data_agent:
    repaired = ["data_agent"] + repaired
```

**3. Data Agent: active_dataset_keys setzen**
```python
# Neue Daten geladen → Keys der neuen Datasets
active_keys = [key for key in new_datasets]

# Keine neuen Daten (check_dataset: vorhanden) → found-Keys als Fallback
if not active_keys and check_dataset_keys:
    active_keys = check_dataset_keys
```

**4. Lifecycle pro Turn:**
```
Supervisor  → active_dataset_keys = None        (Reset)
Data Agent  → active_dataset_keys = [key1, ...]  (Neu gesetzt)
Viz Agent   → liest [key1, ...]                   (Gefiltert via get_data_from_state)
```

### Begründung
- **Separation of Concerns:** Supervisor plant, Data Agent entscheidet über Daten-Details
- **Kein Bias:** Supervisor sieht keine vollen Dataset-Keys, kann nicht falsch wählen
- **Robuster:** Data Agent prüft via `check_dataset` was wirklich in DuckDB liegt
- **Einfacher Prompt:** Supervisor-Prompt wird kürzer (keine `<dataset_matching>` 4-Dimensionen-Prüfung)

### Implementierung

| Datei | Änderung |
|-------|----------|
| `agents/supervisor.py` | `build_dataset_context()` vereinfacht, `active_dataset_keys` aus Parse/Return entfernt, `validate_plan()` fügt data_agent IMMER ein |
| `prompts/supervisor_prompt.py` | `active_dataset_keys` aus Examples/Output/Rules entfernt, `<dataset_matching>` vereinfacht |
| `agents/data_agent.py` | Neue `_extract_check_dataset_found_keys()`, `build_result()` mit `check_dataset_keys` Fallback |
| `agents/state.py` | Kommentar: "Data Agent setzt, Supervisor resettet" |
| `prompts/data_agent_prompt.py` | Fallback-Logik für fehlende `<supervisor_instructions>` |

### Anwenden bei
- Alle Turns mit Viz/Stats Agent → Data Agent muss immer im Plan sein
- Neue Agents die gefilterte Daten brauchen → `get_data_from_state(state)` nutzt `active_dataset_keys`
- Supervisor-Prompt-Änderungen → keine Dataset-Key-Details in den Supervisor-Kontext geben

### Referenz
- `agents/supervisor.py:build_dataset_context()` — Kompakter Kontext
- `agents/data_agent.py:_extract_check_dataset_found_keys()` — Fallback-Logik
- `agents/data_agent.py:build_result()` — active_dataset_keys Lifecycle
- `agents/state.py:active_dataset_keys` — Feld-Dokumentation

---

## DEC-029: Supervisor als zentrale Kontext-Instanz (turn_history)

### Problem
In Multi-Turn-Konversationen gehen Follow-up-Queries schief, weil der Supervisor nur die letzte User-Query + einen verlustbehafteten `data_summary`-Text sieht. Er weiß nicht was der User vorher gefragt hat, welche Daten geladen wurden oder welche Ergebnisse produziert wurden. Dadurch erzeugt er falsche `data_instructions` (falsche Keys, falsches Datum, falscher Zeitraum).

**Beispiel:** User fragt "Korrelation Moment/Position, 3 Achsen, 4.Feb 14:20-15:00", dann "zeig mir die Daten in einem Diagramm". Der Supervisor weiß nicht was "die Daten" bedeutet und holt komplett falsche Daten.

### Kontext
- Orchestrator-Worker Pattern: Supervisor muss genug Kontext haben um richtig zu planen
- `data_summary` ist verlustbehaftet: keine Keys, kein Zeitraum, kein Ergebnis-Typ
- Checkpointer persistiert State zwischen Turns — `turn_history` akkumuliert automatisch
- Supervisor-Prompt hatte keine Telemetrie-Referenz → konnte Keys nicht zuordnen

### Entscheidung
**Neues `turn_history` State-Feld mit strukturierten Turn-Zusammenfassungen. Supervisor bekommt vollen Konversationskontext inkl. geladener Keys, Zeiträume und Ergebnisse. Zusätzlich kompakte Telemetrie-Gruppen-Tabelle im Prompt. Supervisor-Modell auf Opus umgestellt.**

### Pattern

**1. TurnEntry-Struktur (State)**
```python
class TurnEntry(TypedDict, total=False):
    user_query: str             # "Korrelation Moment/Position, 3 Achsen..."
    plan: list[str]             # ["data_agent", "stats_agent"]
    data_mode: str              # "detail" | "overview"
    datasets: list[TurnDataset] # Gruppiert nach Zeitraum
    result_type: str            # "data" | "chart" | "statistics" | "error" | "abstention" | "clarification"
    result_summary: str         # "Korrelation: A1 r=0.012, A2 r=-0.617"
```

**2. Reducer (max 20 Einträge)**
```python
turn_history: Annotated[list[dict], append_turn_history] = []

def append_turn_history(existing, new):
    return (existing + new)[-20:]
```

**3. respond_node schreibt turn_history**
```python
# Am Ende jedes Turns:
turn_entry = _build_turn_entry(state)
return {"messages": [...], "turn_history": [turn_entry]}
```

**4. Supervisor liest turn_history**
```python
def build_turn_context(turn_history, datasets) -> str:
    # Zeigt max 15 Turns im Format:
    # Turn 1: "Korrelation Moment/Position..."
    #   Plan: ["data_agent", "stats_agent"]
    #   Daten: torque_act_a1_nm, axis_act_a1_deg (04.02. 14:20-15:00)
    #   Ergebnis (statistics): Korrelation A1 r=0.012
```

**5. Telemetrie-Referenz im Prompt**
```
<telemetry_reference>
| Gruppe | Keys | Einheit | Begriffe |
|--------|------|---------|----------|
| Ist-Drehmomente | torque_act_a1..a6_nm | Nm | Moment, Drehmoment, Kraft |
| ... (alle 13 Gruppen) |
</telemetry_reference>
```

### Begründung
- **Voller Kontext:** Supervisor sieht alle bisherigen Queries, geladene Daten und Ergebnisse
- **Korrekte Follow-ups:** "Zeig mir die Daten als Chart" wird richtig aufgelöst (Keys + Zeitraum aus vorherigem Turn)
- **Telemetrie-Referenz:** Supervisor kann User-Begriffe ("Drehmoment") auf Keys abbilden ohne extra Tool-Call
- **Opus-Modell:** Besseres Reasoning für komplexe Multi-Turn-Planung
- **Backward-kompatibel:** Alte Sessions ohne turn_history bekommen Fallback "Daten vorhanden"

### Implementierung

| Datei | Änderung |
|-------|----------|
| `agents/state.py` | `TurnEntry`, `TurnDataset` TypedDicts, `append_turn_history` Reducer, `turn_history` Feld, `data_summary` als DEPRECATED markiert |
| `agents/graph.py` | `_build_turn_entry()` + Helfer, alle respond_node Return-Pfade mit `turn_history` |
| `agents/supervisor.py` | `build_turn_context()` ersetzt `build_dataset_context()`, Opus-Modell |
| `prompts/supervisor_prompt.py` | `get_supervisor_prompt()` Funktion statt Konstante, `_build_telemetry_table()`, Multi-Turn-Beispiele mit turn_history Format |

### Anwenden bei
- Multi-Turn-Konversationen → Supervisor hat jetzt Kontext über bisherige Turns
- Follow-up-Queries ("zeig das als Chart", "nochmal für Achse 2") → Keys/Zeitraum aus turn_history
- Neue Agents die Konversationskontext brauchen → `state["turn_history"]` lesen

### Referenz
- `agents/state.py:TurnEntry` — Strukturierte Turn-Zusammenfassung
- `agents/graph.py:_build_turn_entry()` — Schreibt turn_history am Ende jedes Turns
- `agents/supervisor.py:build_turn_context()` — Liest turn_history für Supervisor-Kontext
- `prompts/supervisor_prompt.py:get_supervisor_prompt()` — Prompt mit Telemetrie-Referenz

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

---

## 🔄 Änderungshistorie

| Datum | Änderung |
|-------|---------|
| 2025-12-19 | Initiale Version mit 8 Patterns |
| 2025-12-20 | DEC-009 (Error Handling) + DEC-010 (Datenpunkt-Limit) hinzugefügt |
| 2025-12-20 | DEC-011 (Literal statt Regex) - Refactoring nach fehlgeschlagenem Test |
| 2025-12-20 | DEC-012 (Integration Testing) - MCP Cleanup + Rate Limit Best Practices |
| 2025-12-20 | DEC-013 (Multi-Turn Persistenz) - Checkpointer für State zwischen Turns |
| 2025-12-23 | DEC-014 (SystemMessage Filter) - Anthropic Multi-Turn Fix |
| 2025-12-23 | IDEE-001 (Dynamic Key Discovery) - Notiert für spätere Umsetzung |
| 2025-12-23 | DEC-015 (Prompt-Struktur mit XML-Tags) - Anthropic Best Practice |
| 2026-01-28 | DEC-019 (Beispiel-basierte State-Awareness) - AP7.1 abgeschlossen |
| 2026-02-02 | DEC-020 (Komprimierter Telemetry Lookup) - Token-Verbrauch von ~10k auf ~200 reduziert |
| 2026-02-03 | DEC-021 (Prompt Caching) - IMPLEMENTIERT: Alle Agents mit list[dict] content Format (LangChain Issue #26701) |
| 2026-02-03 | DEC-022 (Dynamische Few-Shot Dates) - Alle Datumsbeispiele im Prompt dynamisch generiert |
| 2026-02-03 | DEC-015 Update: Key-Limit (6-10) entfernt - unnötig da Agent nur Statistics sieht (DEC-004) |
| 2026-02-03 | DEC-020 Update: usage_hint in search_telemetry_keys Response - skalierbare Lösung statt hardcoded Limits |
| 2026-02-03 | DEC-023 (Query-Typ-basierte Datenstrategie) - IMPLEMENTIERT: Raw vs. Aggregated basierend auf Use Case |
| 2026-02-03 | DEC-024 (Timeseries Korrelation) - IMPLEMENTIERT: pd.merge_asof für IoT-Sensoren mit unterschiedlichen Timestamps |
| 2026-02-03 | Stats Agent Refactoring - Auf InjectedState Pattern umgebaut (wie Viz Agent), MCP Server entfernt |
| 2026-02-04 | DEC-025 (DuckDB Reference-only State) - IMPLEMENTIERT: In-Memory DuckDB pro Session, DatasetMeta statt Rohdaten im State, UNS-Keys |
| 2026-02-11 | DEC-028 (Data Agent als Daten-Gatekeeper) - IMPLEMENTIERT: Data Agent setzt active_dataset_keys, Supervisor bekommt nur Summary |
| 2026-02-11 | DEC-029 (Supervisor als Kontext-Instanz) - IMPLEMENTIERT: turn_history, Telemetrie-Referenz, Opus-Modell, build_turn_context() |
