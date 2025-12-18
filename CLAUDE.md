# CLAUDE.md - Kontext für Claude

## Projekt
**Conversational Analytics für IIoT** (Masterarbeit)
- Ziel: MCP-basiertes System für natürlichsprachliche Datenanalyse
- Abgabe: 31. März 2025
- **Status: System funktioniert! AP8 (Evaluation) als nächstes.**

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

## Aktueller Status (18.12.2025)

### Was funktioniert ✅
- Daten laden für beliebige Zeiträume ("16.", "Dienstag 12 Uhr", "letzte Stunde")
- Charts erstellen (Line, Bar, Scatter über AntV)
- Statistiken berechnen
- Bei fehlenden Daten: Stoppt und fragt User
- Bei Erfolg: Weiter zum nächsten Agent

### Was offen ist
- **AP8: Evaluation** - 15 Testfragen aus `08_TESTFRAGEN.md` durchgehen
- Integration Tests (optional)

---

## Referenz-Dateien

| Situation | Datei |
|-----------|-------|
| **Vor jedem Arbeitspaket** | `03_ARBEITSPAKETE.md` |
| **Agent-Implementierung** | `06_PROMPT_PATTERNS.md` + `05_ARCHITEKTUR.md` |
| **Fehler/Bug** | `07_ERROR_HANDLING.md` ZUERST! |
| **Evaluation** | `08_TESTFRAGEN.md` |

---

## Kritische Regeln (aus Erfahrung!)

### 1. MCP-Response-Parsing
```python
# IMMER Status ZUERST prüfen!
if parsed.get("status") == "no_data":
    return None, {"type": "no_data", ...}, None
if parsed.get("status") == "success":
    # Dann Daten verarbeiten
```

### 2. Pipeline-Steuerung (NEU!)
```python
# In data_agent.py: detect_needs_user_input()
# Stoppt Pipeline NUR bei echten Fehlern, NICHT bei höflichen Nachfragen

# Success-Indicators → KEIN STOPP
if "erfolgreich" in content or "geladen" in content:
    return False, None  # Weiter zum nächsten Agent!

# Hard-Stop-Patterns → STOPP
if "keine daten für den zeitraum" in content:
    return True, "Agent stoppt"
```

### 3. Agent-zu-Agent-Übergabe
```python
# NIEMALS SystemMessages übernehmen!
human_messages = [m for m in state["messages"] if isinstance(m, HumanMessage)]
messages = [SystemMessage(content=PROMPT), *human_messages]
```

### 4. Große Datenmengen
- Rohdaten → `outputs/data/telemetry_xxx.json`
- Nur Summary (~500 Bytes) an LLM
- Max ~50KB direkt im Context

---

## Timerange-Parser (unterstützte Formate)

```python
# Wochentage
"Dienstag", "Dienstag 12 Uhr", "Dienstag um 13:30"

# Relative
"letzte Stunde", "letzte 10 Minuten", "heute", "gestern"

# Datum (NEU!)
"16."           → 16. des aktuellen Monats (ganzer Tag)
"am 16."        → 16. des aktuellen Monats
"16. Dezember"  → 16. Dezember
"16.12."        → 16. Dezember
"16.12.2025"    → Exaktes Datum
```

---

## Debugging-Workflow

```bash
# 1. DEBUG aktivieren
# In agents/data_agent.py oder viz_agent.py:
DEBUG = True

# 2. App starten
chainlit run app.py

# 3. Logs beobachten (🔍 DEBUG: ...)

# 4. Fix implementieren

# 5. DEBUG = False setzen!
```

---

## Projektstruktur
```
conversational-analytics/
├── agents/
│   ├── state.py           # AgentState (needs_user_input, user_input_reason)
│   ├── data_agent.py      # Mit detect_needs_user_input()
│   ├── viz_agent.py       # Message-Filtering
│   ├── stats_agent.py     
│   └── graph.py           # Router prüft needs_user_input
├── mcp_servers/
│   └── thingsboard_server.py  # 9 Tools, erweiterter Timerange-Parser
├── prompts/               # System Prompts
├── outputs/data/          # Telemetrie-Dateien (JSON)
├── tests/                 # 243 Unit Tests
├── app.py                 # Chainlit (mit pending_query für Follow-ups)
└── [Dokumentation]
```

---

## Typische Befehle

```bash
# App starten
cd ~/ma_ws/conversational-analytics
source venv/bin/activate
chainlit run app.py

# Tests ausführen (umgeht ROS2-Konflikt)
python run_tests.py

# Git
git add -A && git commit -m "message" && git push
```

---

## ThingsBoard
- URL: http://localhost:8080
- Device: KRC5 (KUKA Roboter)
- Verfügbare Daten: 11.12. - 16.12.2025 (Arbeitszeit)
- **Keine Temperatur-Keys!** (nur Drehmomente, Position, etc.)
