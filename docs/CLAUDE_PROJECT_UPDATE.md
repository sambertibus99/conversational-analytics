# AKTUALISIERUNG FÜR CLAUDE PROJECT KNOWLEDGE

## Für `CLAUDE.md` oder System Prompt - Neuer Abschnitt:

```markdown
## REFERENZ-DATEIEN

### Wann welche Datei lesen?

| Situation | Datei lesen |
|-----------|-------------|
| **Vor jedem Arbeitspaket** | `03_ARBEITSPAKETE.md` (relevanter Abschnitt) |
| **Agent-Implementierung** | `06_PROMPT_PATTERNS.md` + `11_DATENFLUSS.md` |
| **MCP Server Arbeit** | `05_ARCHITEKTUR.md` + `11_DATENFLUSS.md` |
| **Fehler/Bug tritt auf** | `12_BEKANNTE_FEHLER.md` ZUERST! |
| **Evaluation** | `08_TESTFRAGEN.md` |
| **Testing/Debugging** | `AP9` in `03_ARBEITSPAKETE.md` |

### Kritische Regeln aus Erfahrung

#### Bei MCP-Response-Parsing:
1. **IMMER** `status` Feld zuerst prüfen (`success`, `no_data`, `error`, `data_available`)
2. Neue Response-Formate in `extract_data_from_parsed()` UND `generate_data_summary()` behandeln
3. Siehe `12_BEKANNTE_FEHLER.md` Fehler #3 und #4

#### Bei Agent-zu-Agent-Übergabe:
1. **NIEMALS** SystemMessages von vorherigen Agents übernehmen
2. Nur HumanMessages filtern und weitergeben
3. Neuen SystemMessage für jeden Agent erstellen
4. Siehe `12_BEKANNTE_FEHLER.md` Fehler #5

#### Bei großen Datenmengen:
1. Rohdaten in Datei speichern, NICHT an LLM
2. Nur Zusammenfassung (~500 Bytes) an LLM
3. Max ~50KB direkt im LLM-Context
4. Siehe `12_BEKANNTE_FEHLER.md` Fehler #2

### Debugging-Workflow

Wenn ein Fehler auftritt:
1. `12_BEKANNTE_FEHLER.md` lesen - ist es ein bekannter Fehler?
2. `11_DATENFLUSS.md` lesen - an welcher Stelle im Flow tritt er auf?
3. DEBUG=True setzen im betroffenen Agent
4. Logs analysieren
5. Fix dokumentieren in `12_BEKANNTE_FEHLER.md`
```

---

## Neue Dateien für Project Knowledge:

### `11_DATENFLUSS.md`
(Kopiere aus: `/home/sam/ma_ws/conversational-analytics/docs/DATENFLUSS.md`)

### `12_BEKANNTE_FEHLER.md`
(Kopiere aus: `/home/sam/ma_ws/conversational-analytics/docs/FEHLERZUSAMMENFASSUNG_20251218.md`)

### In `03_ARBEITSPAKETE.md` hinzufügen:
(Kopiere AP9 aus: `/home/sam/ma_ws/conversational-analytics/docs/AP9_DEBUGGING_TESTING.md`)

---

## Aktualisiertes Datei-Übersicht für Project Knowledge:

```
Claude Project Knowledge/
├── 01_CLAUDE.md              # System Prompt (aktualisieren mit obigem!)
├── 02_PROJEKT_KONTEXT.md     # Grundlagen
├── 03_ARBEITSPAKETE.md       # + AP9 hinzufügen
├── 05_ARCHITEKTUR.md         # Systemaufbau
├── 06_PROMPT_PATTERNS.md     # Agent Prompts
├── 07_ERROR_HANDLING.md      # Fehlerbehandlung
├── 08_TESTFRAGEN.md          # Evaluation
├── 09_THINGSBOARD_SETUP.md   # ThingsBoard Config
├── 10_WOCHENPLAN.md          # Zeitplan
├── 11_DATENFLUSS.md          # NEU: Wie Daten durch System fließen
└── 12_BEKANNTE_FEHLER.md     # NEU: Lessons Learned
```
