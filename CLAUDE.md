# CLAUDE.md - Kontext für Claude

## Projekt
**Conversational Analytics für IIoT** (Masterarbeit)
- Ziel: MCP-basiertes System für natürlichsprachliche Datenanalyse
- Abgabe: 31. März 2025

## Projektpfad
```
/home/sam/ma_ws/conversational-analytics
```

## Bei Session-Start (Claude Desktop)
1. `read_file` auf diese Datei (`CLAUDE.md`)
2. `read_file` auf `04_AKTUELLER_STAND.md` 
3. `list_directory` auf Projektroot für Überblick
4. Bei Bedarf weitere Dateien mit `read_file` laden

## Projektstruktur
```
conversational-analytics/
├── agents/                 # LLM Agents
│   ├── state.py           # AgentState Definition
│   ├── data_agent.py      # Holt Daten von ThingsBoard
│   ├── viz_agent.py       # Generiert Charts (TODO)
│   ├── stats_agent.py     # Berechnet Statistiken (TODO)
│   └── supervisor.py      # Orchestriert Agents (TODO)
├── mcp_servers/           # MCP Server
│   ├── thingsboard_client.py  # Async HTTP Client
│   ├── thingsboard_server.py  # MCP Server (8 Tools)
│   └── chart_server.py    # Chart MCP Server (TODO)
├── prompts/               # System Prompts für Agents
│   └── data_agent_prompt.py
├── config/
│   └── settings.py        # API Keys, Konstanten
├── tests/                 # Test-Dateien
├── evaluation/            # Evaluation (TODO)
├── .env                   # Secrets (nicht in Git!)
├── CLAUDE.md              # Diese Datei
└── 04_AKTUELLER_STAND.md  # Aktueller Fortschritt
```

## Referenz-Dateien (bei Bedarf lesen)

| Datei | Wann lesen? |
|-------|-------------|
| `02_PROJEKT_KONTEXT.md` | Bei Fragen zu MA-Kontext, Forschungsfrage, Gesamtüberblick |
| `03_ARBEITSPAKETE.md` | **VOR jedem neuen AP** - enthält Schritte, Tests, erwartete Outputs |
| `05_ARCHITEKTUR.md` | Bei Architektur-Entscheidungen, State-Design, Datenfluss |
| `06_PROMPT_PATTERNS.md` | **Bei Agent-Implementierung** - enthält optimierte System Prompts |
| `07_ERROR_HANDLING.md` | Bei Error Handling, Retry-Logik, Logging |
| `08_TESTFRAGEN.md` | **Bei AP8 Evaluation** - enthält 15 Test-Queries mit Ground Truth |
| `09_THINGSBOARD_SETUP.md` | Bei ThingsBoard API-Fragen, Telemetrie-Keys |
| `10_WOCHENPLAN.md` | Bei Zeitplanung |

### Regel: Vor jedem Arbeitspaket
```
1. read_file → 03_ARBEITSPAKETE.md (Abschnitt zum AP lesen)
2. read_file → Relevante Referenz-Datei (siehe Tabelle oben)
3. read_file → Bestehender Code als Referenz
4. Dann erst implementieren
```

## Workflow (Claude Desktop)
1. **Code ändern:** `edit_file` oder `write_file`
2. **Nach jeder Änderung:** User testet lokal
3. **Session Ende:** User macht `git add . && git commit -m "..." && git push`

## Konventionen
- Python 3.12, async/await
- LangGraph für Agent-Orchestrierung
- MCP für Tool-Integration
- LLM: Claude Sonnet (claude-sonnet-4-20250514)
- DEBUG = False (außer beim Debugging)

## Typische Befehle zum Testen
```bash
# Data Agent testen
python agents/data_agent.py

# Interaktiver Modus
python agents/data_agent.py --interactive

# MCP Server testen
python mcp_servers/thingsboard_server.py
```

## ThingsBoard
- URL: http://localhost:8080
- Device: KRC5 (KUKA Roboter)
- Device ID: in .env als KRC5_DEVICE_ID