# ThingsBoard MCP Server

> **Arbeitspaket:** AP1
> **Datei(en):** `mcp_servers/thingsboard_server.py`, `mcp_servers/thingsboard_client.py`
> **Status:** ✅ Abgeschlossen (20.12.2025)

---

## 1. Aktueller Stand

- **8 MCP Tools** implementiert (vorher 9, `get_telemetry_aggregated` entfernt)
- HTTP Client für ThingsBoard REST API
- File-Storage für große Datenmengen (Token-Limit Workaround)
- **LLM-basiertes Zeitraum-Parsing** (seit 19.12.2025)
- **Automatische Aggregation** mit Intervall-Berechnung (seit 19.12.2025)
- **Performance-Optimierung:** MCP Server Warmup beim App-Start
- **Optimierte Tool-Descriptions** für LLM-Auswahl (seit 19.12.2025)
- **Error Handling:** Custom Exceptions + Retry mit Exponential Backoff (seit 20.12.2025)
- **Datenpunkt-Limit:** Warnung/Fehler bei zu vielen Datenpunkten mit Korrekturvorschlag (seit 20.12.2025)
- **Logging:** Strukturiertes Logging in Client und Server (seit 20.12.2025)

---

## 2. Design-Entscheidung: Tool Selection via LLM

### Kontext

Bei der Tool-Auswahl in LLM-Agenten gibt es verschiedene Ansätze:

| Anzahl Tools | Empfohlener Ansatz | Begründung |
|--------------|-------------------|------------|
| **< 10 Tools** | LLM wählt direkt | Geringe Komplexität, kein Overhead |
| 10-50 Tools | Dynamische Auswahl (RAG über Tool-Descriptions) | Token-Effizienz |
| 50+ Tools | Tool-Gruppen + Routing + Hierarchie | Skalierbarkeit |

**Quellen:**
- LangGraph Docs: "How to handle large numbers of tools" (2025)
- LangChain Blog: "Top 5 LangGraph Agents in Production 2024"
- Swarnendu De: "LangGraph Best Practices" (Sept 2025)

### Entscheidung: Direkte LLM-Auswahl mit optimierten Descriptions

Mit **8 Tools** liegt dieses Projekt im Bereich, wo direkte LLM-Auswahl via `create_react_agent` die Best Practice ist. Der Fokus liegt daher auf **qualitativ hochwertigen Tool-Descriptions**.

### Implementierung: Strukturierte Tool-Descriptions

Jede Tool-Description folgt einem einheitlichen Schema:

```python
@mcp.tool()
async def get_telemetry(...) -> str:
    """
    Kurzbeschreibung der Funktion.
    
    WANN BENUTZEN:
    - Konkreter Use-Case 1
    - Konkreter Use-Case 2
    - Trigger-Wörter aus User-Anfragen
    
    NICHT BENUTZEN:
    - Abgrenzung zu anderem Tool → alternatives_tool
    - Weiterer Ausschluss-Fall
    
    Args:
        param1: Beschreibung mit Beispiel
    """
```

### Beispiel: get_telemetry vs get_latest_telemetry

**Vorher (unklar):**
```python
async def get_telemetry(...):
    """Holt Telemetrie-Zeitreihen für einen Zeitraum."""

async def get_latest_telemetry(...):
    """Holt die aktuellsten Telemetrie-Werte."""
```

**Nachher (eindeutig):**
```python
async def get_telemetry(...):
    """
    Holt Telemetrie-ZEITREIHEN für einen definierten Zeitraum.
    
    WANN BENUTZEN:
    - User fragt nach VERLAUF/TREND: "Zeig Position von gestern"
    - User nennt ZEITRAUM: "Drehmomente vom Dienstag"
    - User will VISUALISIEREN
    
    NICHT BENUTZEN:
    - User fragt nur nach AKTUELLEM Wert → get_latest_telemetry
    """

async def get_latest_telemetry(...):
    """
    Holt die aktuellsten Telemetrie-Werte (genau 1 Wert pro Key).
    
    WANN BENUTZEN:
    - User fragt nach AKTUELLEM Wert: "Wie ist die Position jetzt?"
    - Schnelle Statusabfrage ohne Zeitreihe
    
    NICHT BENUTZEN:
    - User fragt nach Verlauf/Trend über Zeit → get_telemetry
    - User nennt einen Zeitraum → get_telemetry
    """
```

### Wissenschaftliche Einordnung

Diese Optimierung folgt dem Prinzip **"Tool Description as Prompt Engineering"**:

1. **Explizite Abgrenzung:** Durch "NICHT BENUTZEN" wird dem LLM klar, wann ein anderes Tool besser passt
2. **Trigger-Wörter:** Konkrete Phrasen aus User-Anfragen helfen dem LLM bei der Zuordnung
3. **Alternatives-Verweis:** Direkte Nennung des alternativen Tools reduziert Fehlentscheidungen

**Vorteil gegenüber dynamischer Tool-Auswahl:**
- Kein zusätzlicher Retrieval-Schritt (Latenz)
- Keine Vector-DB für Tool-Embeddings nötig
- Transparenter für Debugging

**Trade-off:**
- Bei >20 Tools würde dieser Ansatz zu viele Tokens verbrauchen
- Tool-Descriptions müssen manuell gepflegt werden

### Ergebnis

Die Tool-Descriptions wurden für alle 8 Tools optimiert:

| Tool | Vorher | Nachher |
|------|--------|---------|
| `list_devices` | 1 Zeile | 8 Zeilen mit Use-Cases |
| `get_device_info` | 1 Zeile | 10 Zeilen mit Abgrenzung |
| `list_telemetry_keys` | 1 Zeile | 9 Zeilen mit Trigger-Wörtern |
| `get_data_availability` | 5 Zeilen | 12 Zeilen mit Workflow-Hinweis |
| `get_latest_telemetry` | 3 Zeilen | 14 Zeilen mit klarer Abgrenzung |
| `get_telemetry` | 15 Zeilen | 22 Zeilen als "HAUPTTOOL" markiert |
| `get_attributes` | 3 Zeilen | 13 Zeilen mit Telemetrie-Abgrenzung |
| `list_attribute_keys` | 1 Zeile | 11 Zeilen mit Scope-Erklärung |

---

## 3. Design-Entscheidung: LLM-basiertes Zeitraum-Parsing

### Problem

~200 Zeilen Regex-Parser für Zeitangaben war:
- Wartungsaufwändig (neue Formate = neuer Code)
- Nicht erweiterbar für unbekannte Formate
- Silent fallback bei Parse-Fehlern
- Order-dependent Pattern-Matching

### Lösung: LLM übernimmt Parsing

**Vorher (Tool parst):**
```python
get_telemetry(keys="...", timerange="Dienstag zwischen 13 und 16 Uhr")
# 200 LOC Regex-Parser im Tool
```

**Nachher (LLM parst):**
```python
get_telemetry(
    keys="...",
    start_date="2025-12-16",  # LLM berechnet aus "Dienstag"
    end_date="2025-12-16",
    start_time="13:00",
    end_time="16:00"
)
```

### Implementierung

**Data Agent Prompt (`prompts/data_agent_prompt.py`):**
```python
def get_data_agent_prompt() -> str:
    now = datetime.now()
    current_date = now.strftime("%Y-%m-%d")
    current_weekday = WEEKDAY_NAMES[now.weekday()]
    
    return f"""
    ## AKTUELLES DATUM
    Heute ist: {current_weekday}, {current_date}
    
    ## ZEITANGABEN BERECHNEN
    | User sagt | start_date | end_date | ... |
    | "gestern" | {yesterday} | {yesterday} | ... |
    | "Dienstag" | (letzter Di) | ... |
    """
```

### Vorteile

| Aspekt | Vorher | Nachher |
|--------|--------|---------|
| Code | ~200 LOC | ~10 LOC |
| Neue Formate | Code ändern | Funktioniert automatisch |
| Fehlerbehandlung | Silent fallback | LLM kann nachfragen |
| Wartung | Hoch | Minimal |

---

## 4. Design-Entscheidung: Automatische Aggregation

### Problem

Bei "Zeig Drehmomente vom 16. Dezember" wurden ~72.000 Rohdatenpunkte geladen:
- 6 Achsen × ~12.000 Punkte/Tag = 72.000 Datenpunkte
- Diese gingen durch den LLM-Context → API Rate Limit (429)

### Lösung: Intelligente Auto-Aggregation

**Regeln:**
| Zeitraum | Intervall | Max Punkte/Key | Begründung |
|----------|-----------|----------------|------------|
| ≤ 1 Stunde | 1 Minute | ~60 | Hohe Auflösung für kurze Zeiträume |
| ≤ 1 Tag | 10 Minuten | ~144 | Guter Kompromiss |
| ≤ 1 Woche | 1 Stunde | ~168 | Übersicht über Woche |
| > 1 Woche | 1 Tag | ~30-90 | Langzeit-Trends |

### Implementierung

```python
def calculate_auto_interval(start_dt: datetime, end_dt: datetime) -> tuple[int, str, str]:
    duration_hours = (end_dt - start_dt).total_seconds() / 3600
    
    if duration_hours <= 1:
        return 60000, "1 Minute", f"Zeitraum {duration_hours:.1f}h → 1-Minuten-Intervall"
    elif duration_hours <= 24:
        return 600000, "10 Minuten", f"Zeitraum {duration_hours:.1f}h → 10-Minuten-Intervall"
    elif duration_hours <= 168:  # 7 Tage
        return 3600000, "1 Stunde", f"Zeitraum {duration_hours/24:.1f} Tage → 1-Stunden-Intervall"
    else:
        return 86400000, "1 Tag", f"Zeitraum {duration_hours/24:.0f} Tage → 1-Tages-Intervall"
```

### User-Interaktion

**Response enthält Settings-Info:**
```json
{
  "settings": {
    "interval": "10 Minuten",
    "aggregation": "Durchschnitt",
    "auto_interval": true,
    "reason": "Zeitraum 24.0h → 10-Minuten-Intervall"
  },
  "settings_text": "Automatisch: Durchschnitt alle 10 Minuten",
  "user_hint": "Du kannst anpassen: 'zeig Maximum' oder 'mit 5-Minuten-Intervall'"
}
```

**User kann anpassen:**
| User sagt | Parameter |
|-----------|-----------|
| "zeig Maximum" | `aggregation="maximum"` |
| "zeig Minimum" | `aggregation="minimum"` |
| "mit 5-Minuten-Intervall" | `interval="5m"` |
| "genauer" | kleineres Intervall |
| "gröber" | größeres Intervall |

---

## 5. Design-Entscheidung: Performance-Optimierung

### Problem

MCP Server wurden bei **jedem Request** neu gestartet:
- Python-Prozess für ThingsBoard Server: ~5 Sek
- npx-Prozess für AntV Server: ~10-15 Sek
- **Jeder Request dauerte >30 Sekunden!**

### Lösung: MCP Server Warmup

**Globale Sessions mit AsyncExitStack:**
```python
# agents/data_agent.py
_mcp_tools: list | None = None
_mcp_exit_stack: AsyncExitStack | None = None
_mcp_lock = asyncio.Lock()

async def get_mcp_tools() -> list:
    global _mcp_tools, _mcp_exit_stack
    
    if _mcp_tools is not None:
        return _mcp_tools  # Aus Cache!
    
    async with _mcp_lock:
        # Server einmal starten, Session offen halten
        _mcp_exit_stack = AsyncExitStack()
        streams = await _mcp_exit_stack.enter_async_context(stdio_client(server_params))
        # ...
```

**Warmup beim App-Start (`app.py`):**
```python
@cl.on_chat_start
async def on_chat_start():
    # Beide MCP Server parallel vorwärmen
    await asyncio.gather(
        get_mcp_tools(),      # ThingsBoard
        get_antv_tools(),     # AntV Chart
    )
```

### Ergebnis

| Request | Vorher | Nachher |
|---------|--------|---------|
| 1. Request | ~30 Sek | ~15 Sek (Warmup) |
| 2. Request | ~30 Sek | **~5 Sek** |
| 3. Request | ~30 Sek | **~5 Sek** |

---

## 6. Architektur-Kontext

```
User: "Zeig Drehmomente vom Dienstag"
                    ↓
    ┌─────────────────────────────────────┐
    │ Data Agent (LLM)                    │
    │ - Prompt enthält: "Heute ist Fr 19" │
    │ - Berechnet: "Dienstag = 16.12."    │
    │ - Wählt Keys: torque_act_a1-6_nm    │
    └─────────────────────────────────────┘
                    ↓
    ┌─────────────────────────────────────┐
    │ Tool-Call: get_telemetry(           │
    │   keys="torque_act_a1_nm,...",      │
    │   start_date="2025-12-16",          │
    │   end_date="2025-12-16"             │
    │ )                                   │
    └─────────────────────────────────────┘
                    ↓
    ┌─────────────────────────────────────┐
    │ ThingsBoard MCP Server              │
    │ - calculate_auto_interval()         │
    │ - 24h → 10-Minuten-Intervall        │
    │ - Aggregation: AVG (default)        │
    └─────────────────────────────────────┘
                    ↓
    ┌─────────────────────────────────────┐
    │ ThingsBoard API                     │
    │ - ~144 aggregierte Punkte/Key       │
    │ - 6 Keys × 144 = 864 Punkte total   │
    └─────────────────────────────────────┘
                    ↓
    ┌─────────────────────────────────────┐
    │ Response mit settings_text:         │
    │ "Durchschnitt alle 10 Minuten"      │
    │ + user_hint für Anpassungen         │
    └─────────────────────────────────────┘
```

---

## 7. Tools (8 insgesamt)

| Tool | Parameter | Beschreibung |
|------|-----------|--------------|
| `list_devices` | - | Alle Geräte auflisten |
| `get_device_info` | device_name | Gerätedetails |
| `list_telemetry_keys` | device_name | Verfügbare Messwert-Keys |
| `list_attribute_keys` | device_name | Verfügbare Attribut-Keys |
| `get_data_availability` | keys, device_name | Prüft ob/wann Daten existieren (letzte 7 Tage) |
| `get_latest_telemetry` | keys, device_name | Aktuellster Wert (1 pro Key) |
| **`get_telemetry`** | keys, start_date, end_date, start_time, end_time, interval, aggregation, device_name | **Haupttool** - Aggregierte Zeitreihen |
| `get_attributes` | keys, device_name | Statische Attribute |

### get_telemetry - Parameter

| Parameter | Typ | Default | Beschreibung |
|-----------|-----|---------|--------------|
| `keys` | str | - | Komma-separierte Keys |
| `start_date` | str | - | YYYY-MM-DD (Pflicht) |
| `end_date` | str | - | YYYY-MM-DD (Pflicht) |
| `start_time` | str | "00:00" | HH:MM |
| `end_time` | str | "23:59" | HH:MM |
| `interval` | str | None | "5m", "1h", "1d" (auto wenn None) |
| `aggregation` | str | None | "durchschnitt", "maximum", "minimum" (AVG wenn None) |
| `device_name` | str | "KRC5" | Gerätename |

---

## 8. Tests

| Bereich | Datei | Tests |
|---------|-------|-------|
| ISO Datum-Parsing | `test_timerange_parsing.py` | 7 |
| Intervall-Parsing | `test_timerange_parsing.py` | 11 |
| Auto-Intervall | `test_timerange_parsing.py` | 6 |
| Aggregations-Parsing | `test_timerange_parsing.py` | 12 |
| Tool-Parameter | `test_timerange_parsing.py` | 2 |
| Datenpunkt-Limits | `test_timerange_parsing.py` | 3 |
| Response-Formate | `test_thingsboard_responses.py` | ~30 |

```bash
# Tests ausführen
python -m pytest tests/test_mcp_server/ -v
```

---

## 9. Offene Punkte

| Task | Priorität | Aufwand | Status |
|------|-----------|---------|--------|
| Error Handling im Client | Mittel | 30 min | ✅ Erledigt (20.12.2025) |
| Logging hinzufügen | Niedrig | 20 min | ✅ Erledigt (20.12.2025) |
| Datenpunkt-Limit Check | Mittel | 20 min | ✅ Erledigt (20.12.2025) |
| File Cleanup (alte Dateien) | Niedrig | 30 min | ⬜ Nice-to-have |
| Multi-Device Support | Niedrig | 1h | ⬜ Nicht geplant |
| Weitere Tools (Alarms?) | Niedrig | 2h+ | ⬜ Nicht für MVP |

---

## 10. Änderungshistorie

| Datum | Änderung | Begründung |
|-------|----------|------------|
| 2025-12-16 | Initiale Implementierung | AP1 |
| 2025-12-18 | File-Storage für große Daten | Token-Limit (400 Bad Request) |
| 2025-12-19 | LLM-basiertes Zeitraum-Parsing | LangChain Best Practice, ~200 LOC entfernt |
| 2025-12-19 | Automatische Aggregation | Rate-Limit durch zu viele Datenpunkte |
| 2025-12-19 | `get_telemetry_aggregated` entfernt | Redundant |
| 2025-12-19 | Performance: MCP Server Warmup | Requests von 30s auf 5s reduziert |
| 2025-12-19 | User-Info über Einstellungen | Transparenz, Anpassbarkeit |
| 2025-12-19 | **Tool-Descriptions optimiert** | LangGraph Best Practice für <10 Tools |
| 2025-12-20 | **Error Handling komplett** | Custom Exceptions, Retry, Logging - DEC-009 |
| 2025-12-20 | **Datenpunkt-Limit** | Warnung bei >1000, Fehler bei >10000 Punkten - DEC-010 |
| 2025-12-20 | **AP1 abgeschlossen** | Alle Core-Features implementiert |
