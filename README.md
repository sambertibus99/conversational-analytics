# Conversational Analytics für IIoT

> MCP-basiertes LLM-Agenten-System für natürlichsprachliche Datenanalyse von KUKA Robotern

## 🎯 Projektziel

Masterarbeit: Entwicklung eines Conversational Analytics Systems das:
- ✅ Natürlichsprachliche Anfragen versteht ("Zeig mir die Drehmomente vom 16. Dezember")
- ✅ Automatisch Daten von ThingsBoard (IIoT-Plattform) abruft
- ✅ Dynamisch passende Visualisierungen generiert
- ✅ Statistiken berechnet wenn nötig
- ✅ Bei fehlenden Daten nachfragt statt zu raten

## 🚀 Quick Start

```bash
# 1. Repository klonen
git clone <repo-url>
cd conversational-analytics

# 2. Virtual Environment
python -m venv venv
source venv/bin/activate

# 3. Dependencies
pip install -r requirements.txt

# 4. .env Datei (siehe Konfiguration)
cp .env.example .env

# 5. App starten
chainlit run app.py
```

Dann öffne http://localhost:8000 und frag z.B.:
- *"Zeig mir die Drehmomente aller 6 Achsen für den 16. Dezember"*
- *"Wie ist die aktuelle TCP Position?"*
- *"Vergleiche die Achspositionen als Balkendiagramm"*

## 🏗️ Architektur

```
User Query ("Zeig Drehmomente vom 16.")
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│              Chainlit Frontend (app.py)                  │
└─────────────────────────┬───────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│              LangGraph Orchestrierung                    │
│                                                          │
│  ┌──────────┐    ┌────────────┐    ┌──────────┐         │
│  │Supervisor│ →  │ Data Agent │ →  │Viz Agent │         │
│  │ (Planer) │    │  (Daten)   │    │ (Charts) │         │
│  └──────────┘    └─────┬──────┘    └────┬─────┘         │
│                        │                 │               │
│         needs_user_input? ──→ STOPP & Fragen            │
│                        │                 │               │
└────────────────────────┼─────────────────┼──────────────┘
                         │                 │
                         ▼                 ▼
              ┌─────────────────┐  ┌─────────────────┐
              │ ThingsBoard MCP │  │ AntV MCP Server │
              │   (9 Tools)     │  │   (25 Tools)    │
              └────────┬────────┘  └────────┬────────┘
                       │                    │
                       ▼                    ▼
              ┌─────────────────┐  ┌─────────────────┐
              │   ThingsBoard   │  │  Chart-URLs     │
              │   (IIoT-Daten)  │  │  (AntV Cloud)   │
              └─────────────────┘  └─────────────────┘
```

## ⚙️ Konfiguration

`.env` Datei erstellen:
```env
# Anthropic API
ANTHROPIC_API_KEY=sk-ant-...

# ThingsBoard
THINGSBOARD_URL=http://localhost:8080
THINGSBOARD_USERNAME=tenant@thingsboard.org
THINGSBOARD_PASSWORD=tenant
KRC5_DEVICE_ID=b8121f40-d446-11f0-866d-41534d350312
```

## 📁 Projektstruktur

```
conversational-analytics/
├── agents/
│   ├── state.py           # AgentState (needs_user_input, data, chart_url, ...)
│   ├── data_agent.py      # Holt Daten, erkennt Stopp-Situationen
│   ├── viz_agent.py       # Generiert Charts via AntV MCP
│   ├── stats_agent.py     # Berechnet Statistiken
│   └── graph.py           # LangGraph Orchestrierung + Router
├── mcp_servers/
│   ├── thingsboard_client.py  # Async HTTP Client
│   └── thingsboard_server.py  # 9 Tools, Timerange-Parser
├── prompts/                   # System Prompts für Agents
├── tests/                     # 243 Unit Tests
│   ├── conftest.py            # Fixtures
│   ├── run_tests.py           # Test-Runner (ROS2-kompatibel)
│   └── test_*/                # Test-Module
├── outputs/data/              # Telemetrie-Dateien (JSON)
├── config/settings.py         # Konstanten
├── app.py                     # Chainlit Frontend
├── CLAUDE.md                  # KI-Assistenten Kontext
├── 04_AKTUELLER_STAND.md      # Projekt-Status
├── 05_ARCHITEKTUR.md          # Detaillierte Architektur
├── 07_ERROR_HANDLING.md       # Bekannte Fehler & Fixes
└── 08_TESTFRAGEN.md           # Evaluation
```

## 🔧 MCP Tools

### ThingsBoard MCP Server (eigener)
| Tool | Beschreibung |
|------|-------------|
| `list_devices` | Geräte auflisten |
| `get_device_info` | Gerätedetails |
| `list_telemetry_keys` | Verfügbare Messwerte |
| `get_latest_telemetry` | Aktuellste Werte |
| `get_telemetry` | Zeitreihen-Daten |
| `get_telemetry_aggregated` | Aggregierte Daten |
| `get_data_availability` | Verfügbarer Datenbereich |
| `get_attributes` | Statische Attribute |
| `list_attribute_keys` | Verfügbare Attribute |

### AntV MCP Server (extern)
```bash
npx -y @antv/mcp-server-chart
```
25+ Chart-Tools: `generate_line_chart`, `generate_bar_chart`, `generate_scatter_chart`, etc.

## 📅 Unterstützte Zeitangaben

Der Timerange-Parser versteht:
```
# Wochentage
"Dienstag", "Dienstag 12 Uhr", "Dienstag um 13:30"

# Relative Angaben
"letzte Stunde", "letzte 10 Minuten", "heute", "gestern"

# Datum
"16."           → 16. des aktuellen Monats
"am 16."        → 16. des aktuellen Monats  
"16. Dezember"  → 16. Dezember
"16.12."        → 16. Dezember
"16.12.2025"    → Exaktes Datum
```

## 🧪 Tests

```bash
# Unit Tests ausführen (243 Tests)
python run_tests.py

# Mit Verbose Output
python run_tests.py -v

# Nur bestimmte Tests
python run_tests.py tests/test_agents -v

# Mit Coverage
python run_tests.py --coverage
```

## 📊 Status

| Komponente | Status | Beschreibung |
|------------|--------|--------------|
| ThingsBoard MCP | ✅ Fertig | 9 Tools, File-Storage, Timerange-Parser |
| Data Agent | ✅ Fertig | Response-Parsing, Pipeline-Steuerung |
| AntV Integration | ✅ Fertig | 25 Chart-Tools |
| Viz Agent | ✅ Fertig | Message-Filtering, Daten-Transformation |
| Stats Agent | ✅ Fertig | 8 Statistik-Tools |
| Supervisor | ✅ Fertig | Plan-Erstellung, Abstention |
| LangGraph | ✅ Fertig | Orchestrierung, needs_user_input Router |
| Frontend | ✅ Fertig | Chainlit, Follow-up Kontext |
| Tests | ✅ Fertig | 243 Unit Tests |
| Evaluation | ⬜ Offen | 15 Testfragen |

## 🐛 Bekannte Issues & Lösungen

| Problem | Lösung |
|---------|--------|
| Token-Limit (400 Bad Request) | Rohdaten in `outputs/data/` speichern, nur Summary an LLM |
| Multiple SystemMessages | Nur HumanMessages zwischen Agents weitergeben |
| Agent macht bei Fehlern weiter | `detect_needs_user_input()` erkennt Stopp-Situationen |
| ROS2 pytest-Konflikt | `run_tests.py` statt direktem `pytest` |

Siehe `07_ERROR_HANDLING.md` für Details.

## 🤖 Verfügbare Telemetrie-Keys (KRC5)

```
# Position (TCP)
pos_act_x_mm, pos_act_y_mm, pos_act_z_mm
pos_act_a_deg, pos_act_b_deg, pos_act_c_deg

# Achspositionen
axis_act_a1_deg ... axis_act_a6_deg

# Drehmomente
torque_act_a1_nm ... torque_act_a6_nm

# Geschwindigkeit
vel_act_m_per_s

# Status
override_pct, pro_state
```

## 📝 Lizenz

Masterarbeit - Hochschule Aachen - 2025
