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

## Wichtige Referenz-Dateien
| Datei | Inhalt |
|-------|--------|
| `02_PROJEKT_KONTEXT.md` | MA-Kontext, Forschungsfrage, Tech-Stack |
| `03_ARBEITSPAKETE.md` | Detaillierte AP-Beschreibungen |
| `05_ARCHITEKTUR.md` | Technische Architektur, State-Design |
| `06_PROMPT_PATTERNS.md` | Optimierte Prompts für Agents |
| `07_ERROR_HANDLING.md` | Fehlerbehandlung |
| `08_TESTFRAGEN.md` | 15 Evaluations-Queries |
| `09_THINGSBOARD_SETUP.md` | ThingsBoard API, Keys |
| `10_WOCHENPLAN.md` | Zeitplan |

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
