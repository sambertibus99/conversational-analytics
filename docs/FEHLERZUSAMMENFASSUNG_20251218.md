# FEHLERZUSAMMENFASSUNG: Session 18.12.2025

## Gefundene Fehler und Fixes

### 🐛 FEHLER 1: Chainlit Config-Format
**Symptom:** `ValidationError` beim Start
**Ursache:** Neue Chainlit-Version erwartet Dictionary statt Boolean
**Fix:**
```toml
# ALT (falsch):
spontaneous_file_upload = false

# NEU (korrekt):
[features.spontaneous_file_upload]
enabled = false
```
**Kategorie:** Konfiguration / Breaking Change
**Potenzielle ähnliche Stellen:** Andere Chainlit-Config-Optionen

---

### 🐛 FEHLER 2: Zu große Datenmengen im LLM-Context
**Symptom:** `400 Bad Request` von Anthropic API
**Ursache:** 43.200 Datenpunkte (2h × 6 Keys) direkt an LLM → Token-Limit überschritten
**Fix:** 
1. Zeitfenster reduziert (±1h → ±5min)
2. Daten in Datei speichern, nur Zusammenfassung an LLM
**Kategorie:** Architektur / Token-Management
**Potenzielle ähnliche Stellen:** 
- Stats Agent (wenn er viele Daten berechnet)
- Aggregierte Abfragen über lange Zeiträume

---

### 🐛 FEHLER 3: "no_data" Response nicht erkannt
**Symptom:** Agent sagt "Daten geladen" obwohl keine Daten existieren
**Ursache:** `extract_data_from_parsed()` prüfte nicht auf `status="no_data"`
**Fix:** Explizite Prüfung auf Status-Feld als ERSTES in der Funktion
```python
if parsed.get("status") == "no_data":
    return None, {"type": "no_data", ...}, None
```
**Kategorie:** Response-Parsing / Error-Handling
**Potenzielle ähnliche Stellen:**
- Alle MCP-Response-Formate (success, no_data, error, data_available)
- Stats Agent Response-Parsing

---

### 🐛 FEHLER 4: "data_available" Response nicht erkannt
**Symptom:** "Daten mit 6 Feldern abgerufen" statt korrekter Zusammenfassung
**Ursache:** Neues Response-Format `status="data_available"` nicht behandelt
**Fix:** Eigener Handler für `data_available` Status
**Kategorie:** Response-Parsing / Schema-Evolution
**Potenzielle ähnliche Stellen:**
- Jedes neue Response-Format muss in `extract_data_from_parsed()` und `generate_data_summary()` behandelt werden

---

### 🐛 FEHLER 5: Multiple System Messages
**Symptom:** `ValueError: Received multiple non-consecutive system messages`
**Ursache:** Viz Agent übernahm alle Messages vom Data Agent (inkl. SystemMessage)
**Fix:** Nur HumanMessages übernehmen:
```python
human_messages = [msg for msg in state["messages"] if isinstance(msg, HumanMessage)]
messages_with_system = [SystemMessage(content=...), *human_messages]
```
**Kategorie:** LangChain/Anthropic Constraint
**Potenzielle ähnliche Stellen:**
- Stats Agent (gleiche Message-Übergabe)
- Respond Node
- Jeder Agent der Messages vom State übernimmt

---

## Fehler-Kategorien

| Kategorie | Anzahl | Risiko |
|-----------|--------|--------|
| Response-Parsing | 2 | HOCH - Neue Formate werden nicht erkannt |
| Token-Management | 1 | HOCH - API-Fehler bei großen Daten |
| Message-Handling | 1 | MITTEL - Anthropic-spezifisch |
| Konfiguration | 1 | NIEDRIG - Einmalig pro Update |

---

## Lessons Learned

### 1. Response-Format-Design
```
JEDE MCP-Tool-Response sollte haben:
- status: "success" | "no_data" | "error" | "data_available"
- message: Menschenlesbare Beschreibung
- Und dann erst die spezifischen Daten
```

### 2. Defensives Parsing
```
IMMER prüfen:
1. Ist parsed None?
2. Ist es das erwartete Format?
3. Hat es den erwarteten Status?
4. Erst dann Daten extrahieren
```

### 3. Message-Chain-Management
```
Bei Agent-zu-Agent-Übergabe:
- SystemMessages NICHT weitergeben
- Nur HumanMessages + relevante AIMessages
- Neuen SystemMessage für jeden Agent
```

### 4. Token-Budget im Auge behalten
```
Faustregel: Max ~50KB Daten an LLM
- Zeitreihen: Max 100-200 Datenpunkte direkt
- Größere Daten: In Datei, nur Summary an LLM
- Statistics statt Rohdaten wo möglich
```
