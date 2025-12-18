# CLAUDE.md - Kontext für Claude

## Projekt
**Conversational Analytics für IIoT** (Masterarbeit)
- Ziel: MCP-basiertes System für natürlichsprachliche Datenanalyse
- Abgabe: 31. März 2025

## Projektpfad
```
/home/sam/ma_ws/conversational-analytics
```

---

## Bei Session-Start
1. Diese Datei lesen (`CLAUDE.md`)
2. `04_AKTUELLER_STAND.md` lesen
3. Bei Bedarf weitere Dateien laden

---

## Referenz-Dateien

### Wann welche Datei lesen?

| Situation | Datei |
|-----------|-------|
| **Vor jedem Arbeitspaket** | `03_ARBEITSPAKETE.md` (Abschnitt zum AP) |
| **Agent-Implementierung** | `06_PROMPT_PATTERNS.md` + `05_ARCHITEKTUR.md` |
| **MCP Server Arbeit** | `05_ARCHITEKTUR.md` (Datenfluss-Diagramm) |
| **Fehler/Bug tritt auf** | `07_ERROR_HANDLING.md` ZUERST! |
| **Evaluation** | `08_TESTFRAGEN.md` |
| **ThingsBoard API** | `09_THINGSBOARD_SETUP.md` |

### Regel: Vor jedem Arbeitspaket
```
1. read_file → 03_ARBEITSPAKETE.md (Abschnitt zum AP)
2. read_file → Relevante Referenz-Datei (siehe Tabelle)
3. read_file → Bestehender Code als Referenz
4. Dann erst implementieren
```

---

## Kritische Regeln (aus Erfahrung!)

### Bei MCP-Response-Parsing:
```
1. IMMER `status` Feld ZUERST prüfen (success/no_data/error/data_available)
2. Bei "no_data" → STOPP, nicht automatisch anderen Zeitraum probieren!
3. Neue Response-Formate in BEIDEN Funktionen behandeln:
   - extract_data_from_parsed()
   - generate_data_summary()
```

### Bei Agent-zu-Agent-Übergabe:
```
1. NIEMALS SystemMessages von vorherigen Agents übernehmen
2. Nur HumanMessages filtern und weitergeben:
   human_messages = [m for m in state["messages"] if isinstance(m, HumanMessage)]
3. Neuen SystemMessage für jeden Agent erstellen
```

### Bei großen Datenmengen:
```
1. Rohdaten in Datei speichern (outputs/data/), NICHT an LLM
2. Nur Zusammenfassung (~500 Bytes) an LLM
3. Max ~50KB direkt im LLM-Context
4. Agent lädt Datei in state.data, nächster Agent liest aus State
```

---

## Debugging-Workflow

Wenn ein Fehler auftritt:

```
1. 07_ERROR_HANDLING.md lesen → Bekannter Fehler?
2. 05_ARCHITEKTUR.md lesen → Wo im Datenfluss tritt er auf?
3. DEBUG=True setzen im betroffenen Agent
4. Logs analysieren (🔍 DEBUG: ...)
5. Fix implementieren
6. DEBUG=False setzen
7. Fehler in 07_ERROR_HANDLING.md dokumentieren
```

### Debug-Modus aktivieren:
```python
# In agents/data_agent.py oder agents/viz_agent.py:
DEBUG = True
```

---

## Projektstruktur
```
conversational-analytics/
├── agents/                 # LLM Agents
│   ├── state.py           # AgentState Definition
│   ├── data_agent.py      # Holt Daten von ThingsBoard
│   ├── viz_agent.py       # Generiert Charts
│   ├── stats_agent.py     # Berechnet Statistiken (TODO)
│   └── graph.py           # LangGraph Orchestrierung
├── mcp_servers/           # MCP Server
│   └── thingsboard_server.py  # 9 Tools, File-Storage
├── prompts/               # System Prompts
├── outputs/
│   └── data/              # Telemetrie-Dateien (JSON)
├── config/
│   └── settings.py        # API Keys, Konstanten
├── docs/                  # Zusätzliche Dokumentation
├── tests/                 # Tests
├── app.py                 # Chainlit Frontend
├── CLAUDE.md              # Diese Datei
├── 02_PROJEKT_KONTEXT.md  # MA-Kontext
├── 03_ARBEITSPAKETE.md    # Arbeitspakete
├── 04_AKTUELLER_STAND.md  # Fortschritt
├── 05_ARCHITEKTUR.md      # System-Architektur + Datenfluss
├── 06_PROMPT_PATTERNS.md  # Agent Prompts
├── 07_ERROR_HANDLING.md   # Fehlerbehandlung + Bekannte Fehler
├── 08_TESTFRAGEN.md       # Evaluation
├── 09_THINGSBOARD_SETUP.md
└── 10_WOCHENPLAN.md
```

---

## Workflow
1. **Code ändern:** `edit_file` oder `write_file`
2. **Nach jeder Änderung:** User testet lokal
3. **Session Ende:** `git add . && git commit -m "..." && git push`

## Konventionen
- Python 3.12, async/await
- LangGraph für Agent-Orchestrierung
- MCP für Tool-Integration
- LLM: Claude Sonnet (claude-sonnet-4-20250514)
- DEBUG = False (außer beim Debugging)

## Typische Test-Befehle
```bash
# Chainlit starten
chainlit run app.py

# Data Agent direkt testen
python agents/data_agent.py --interactive

# MCP Server testen
python mcp_servers/thingsboard_server.py
```

## ThingsBoard
- URL: http://localhost:8080
- Device: KRC5 (KUKA Roboter)
- Daten verfügbar: Dienstag 16.12.2025, 11:56 - 18:36
