# ERROR HANDLING

> Fehlerbehandlung für alle Systemkomponenten
> **Aktualisiert:** 18.12.2025 mit Lessons Learned aus Debugging-Session

---

## Bekannte Fehler & Fixes (Lessons Learned)

### 🐛 FEHLER 1: Token-Limit bei großen Datenmengen
**Symptom:** `400 Bad Request` von Anthropic API
**Ursache:** Zu viele Datenpunkte direkt an LLM (>50KB)
**Fix:** 
```python
# MCP Server speichert Rohdaten in Datei
data_file = save_data_to_file(data)  # → outputs/data/telemetry_xxx.json
# Nur Zusammenfassung an LLM
return {"status": "success", "statistics": {...}, "data_file": data_file}
```
**Regel:** Max ~50KB direkt im LLM-Context. Größere Daten → Datei + Summary.

---

### 🐛 FEHLER 2: Response-Status nicht erkannt
**Symptom:** Agent sagt "Daten geladen" obwohl `status="no_data"`
**Ursache:** `extract_data_from_parsed()` prüfte Status nicht zuerst
**Fix:**
```python
def extract_data_from_parsed(parsed):
    # IMMER Status zuerst prüfen!
    if parsed.get("status") == "no_data":
        return None, {"type": "no_data", ...}, None
    if parsed.get("status") == "data_available":
        return parsed, {"type": "data_availability", ...}, None
    if parsed.get("status") == "success":
        # Dann erst Daten verarbeiten
```
**Regel:** Jede MCP-Response MUSS `status` Feld haben. Parser MUSS Status ZUERST prüfen.

---

### 🐛 FEHLER 3: Multiple System Messages
**Symptom:** `ValueError: Received multiple non-consecutive system messages`
**Ursache:** Viz Agent übernahm alle Messages inkl. SystemMessage vom Data Agent
**Fix:**
```python
# NUR HumanMessages übernehmen!
human_messages = [msg for msg in state["messages"] if isinstance(msg, HumanMessage)]
messages_with_system = [SystemMessage(content=VIZ_PROMPT), *human_messages]
```
**Regel:** Bei Agent-zu-Agent-Übergabe: Nur HumanMessages weitergeben, neuen SystemMessage erstellen.

---

### 🐛 FEHLER 4: Agent macht bei partiellen Daten automatisch weiter
**Symptom:** User fragt nach "Drehmomente UND Energieverbrauch", Agent zeigt nur Drehmomente
**Ursache:** Agent hat nur teilweise Daten gefunden und trotzdem weitergemacht
**Fix:**
```python
# Im Data Agent Prompt:
# Regel 2: Bei TEILWEISEN Daten - SEHR WICHTIG!
# 1. Prüfe ob ALLE angefragten Datentypen verfügbar sind
# 2. Wenn NICHT ALLE verfügbar:
#    - STOPP! Nicht einfach mit den verfügbaren Daten weitermachen!
#    - FRAGE den Nutzer: "Soll ich trotzdem nur X anzeigen?"
```
**Regel:** Wenn nur TEILWEISE Daten für eine Anfrage gefunden werden: 
- STOPPEN und User FRAGEN
- NIEMALS automatisch nur mit den gefundenen Daten weitermachen
- Der User entscheidet, nicht der Agent!

**Beispiel - RICHTIG:**
```
User: "Vergleiche Drehmomente und Energieverbrauch"
Agent: "Ich konnte Drehmomentdaten laden, aber Energieverbrauchsdaten 
        sind nicht verfügbar. Möchtest du:
        1. Nur die Drehmomente anzeigen?
        2. Einen anderen Zeitraum versuchen?"
```

**Beispiel - FALSCH:**
```
User: "Vergleiche Drehmomente und Energieverbrauch"
Agent: *zeigt nur Drehmomente als Chart ohne zu fragen*
```

---

## MCP Response-Format Standard

**JEDE Tool-Response MUSS dieses Format haben:**

```python
# Erfolg mit Daten
{
    "status": "success",
    "data_file": "/path/to/file.json",  # Rohdaten in Datei!
    "statistics": {...},                 # Zusammenfassung für LLM
    "timerange": {"start": "...", "end": "...", "weekday": "..."}
}

# Keine Daten gefunden
{
    "status": "no_data",
    "message": "Keine Daten für Zeitraum...",
    "requested_timerange": {...},
    "hint": "Nutze get_data_availability..."
}

# Daten-Verfügbarkeit
{
    "status": "data_available",
    "data_range": {"first_data": "...", "last_data": "..."},
    "message": "Daten verfügbar von ... bis ..."
}

# Fehler
{
    "status": "error",
    "error_type": "connection" | "auth" | "not_found" | "timeout",
    "message": "Benutzerfreundliche Fehlermeldung"
}
```

---

## Fehlertypen & Reaktionen

### 1. ThingsBoard-Fehler

| Fehler | Ursache | Reaktion |
|--------|---------|----------|
| `ConnectionError` | TB nicht erreichbar | Retry 3x, dann User informieren |
| `401 Unauthorized` | Token abgelaufen | Token refreshen, Retry |
| `404 Device not found` | Falsche Device-ID | User fragen: "Welches Gerät meinst du?" |
| `Empty Response` | Keine Daten im Zeitraum | `status: "no_data"` zurückgeben |
| `Timeout` | Zu viele Daten | Zeitraum einschränken, Aggregation nutzen |

---

### 2. LLM-Fehler

| Fehler | Ursache | Reaktion |
|--------|---------|----------|
| Halluzination | LLM erfindet Daten | Data Faithfulness Check |
| Falsches Tool | Intent falsch erkannt | Supervisor-Prompt verbessern |
| Endlosschleife | Agent kommt nicht weiter | Max 5 Tool-Calls, dann abbrechen |
| Rate Limit | Zu viele Requests | Exponential Backoff (automatisch) |
| Token Limit | Zu große Daten | Daten in Datei, nur Summary an LLM |

---

### 3. Agent-Übergabe-Fehler

| Fehler | Ursache | Reaktion |
|--------|---------|----------|
| Multiple SystemMessages | Messages nicht gefiltert | Nur HumanMessages weitergeben |
| Daten nicht im State | Data Agent hat nicht gespeichert | Prüfen ob `state.data` gefüllt |
| Falsches Datenformat | Transformation fehlt | ThingsBoard → AntV Format konvertieren |

---

### 4. User-Input-Fehler

| Fehler | Beispiel | Reaktion |
|--------|----------|----------|
| Unbekanntes Gerät | "Zeig Daten vom KRC6" | "Ich kenne nur KRC5. Meinst du den?" |
| Unbekannter Key | "Zeig mir die Temperatur" | "Welche Temperatur? Achse 1-6?" |
| Ungültiger Zeitraum | "Daten von morgen" | "Ich kann nur historische Daten zeigen" |
| Keine Daten | "Daten von Dienstag 13 Uhr" | **STOPP** - nicht automatisch anderen Zeitraum probieren! |

---

## Kritische Regeln

### Bei MCP-Response-Parsing:
```
1. IMMER `status` Feld zuerst prüfen
2. Bei "no_data" → STOPP, nicht automatisch retry
3. Neue Formate in extract_data_from_parsed() UND generate_data_summary() behandeln
```

### Bei Agent-zu-Agent-Übergabe:
```
1. NIEMALS SystemMessages von vorherigen Agents übernehmen
2. Nur HumanMessages filtern und weitergeben
3. Neuen SystemMessage für jeden Agent erstellen
```

### Bei großen Datenmengen:
```
1. Rohdaten in Datei speichern (outputs/data/)
2. Nur Zusammenfassung (~500 Bytes) an LLM
3. Agent lädt Datei in state.data
4. Nächster Agent liest aus state.data (nicht nochmal von API!)
```

---

## Debugging-Workflow

```python
# 1. Debug-Modus aktivieren
DEBUG = True  # in agents/data_agent.py oder viz_agent.py

# 2. Chainlit neu starten
chainlit run app.py

# 3. Logs beobachten für:
# 🔍 DEBUG: ... zeigt jeden Schritt

# 4. Nach Fix: Debug wieder aus
DEBUG = False
```

### Was die Debug-Logs zeigen:
- `Starte run_data_agent` - Agent startet
- `Tools geladen: [...]` - MCP-Verbindung OK
- `Extracted text: {...}` - Tool-Response
- `Parsed type: <class 'dict'>` - Parsing OK
- `NO_DATA erkannt` / `SUCCESS mit data_file` - Status erkannt
- `Summary: ...` - Generierte Zusammenfassung

---

## Retry-Strategien

### Exponential Backoff (für API-Calls)
```python
async def with_retry(func, max_retries=3, base_delay=1.0):
    for attempt in range(max_retries):
        try:
            return await func()
        except (ConnectionError, TimeoutError) as e:
            if attempt == max_retries - 1:
                raise
            delay = base_delay * (2 ** attempt)  # 1s, 2s, 4s
            await asyncio.sleep(delay)
```

### KEIN Retry bei:
- `status: "no_data"` → User informieren, nicht anderen Zeitraum probieren!
- `status: "error"` mit `error_type: "not_found"` → Gerät/Key existiert nicht

---

## User-Feedback bei Fehlern

### Freundliche Fehlermeldungen
```python
ERROR_MESSAGES = {
    "connection": "ThingsBoard ist gerade nicht erreichbar. Versuch es in einer Minute nochmal.",
    "no_data": "Für diesen Zeitraum habe ich keine Daten gefunden. Der Roboter war möglicherweise nicht aktiv.",
    "unknown_device": "Ich kenne das Gerät '{device}' nicht. Ich habe Zugriff auf: {available}",
    "unknown_key": "'{key}' kenne ich nicht. Verfügbare Messwerte sind: {available}",
    "rate_limit": "Zu viele Anfragen. Warte kurz...",
    "token_limit": "Die Datenmenge ist zu groß. Ich versuche einen kürzeren Zeitraum.",
}
```

---

## Checkliste für jeden Agent

- [ ] Alle Tool-Calls in try/except
- [ ] `status` Feld in Response ZUERST prüfen
- [ ] Bei `no_data`: STOPP, User informieren
- [ ] Nur HumanMessages an nächsten Agent weitergeben
- [ ] Große Daten in Datei, nicht an LLM
- [ ] Timeout für externe Calls (10s default)
- [ ] Max Tool-Calls pro Request (5)
- [ ] Saubere Fehlermeldung an User (kein Stacktrace!)
