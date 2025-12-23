# Conversational Analytics für IIoT

> MCP-basiertes LLM-Agenten-System für natürlichsprachliche Datenanalyse von KUKA Robotern

## 🎯 Projektziel

Masterarbeit: Entwicklung eines Conversational Analytics Systems das:
- ✅ Natürlichsprachliche Anfragen versteht ("Zeig mir die Drehmomente der letzten 5 Minuten")
- ✅ Automatisch Daten von ThingsBoard (IIoT-Plattform) abruft
- ✅ Dynamisch passende Visualisierungen generiert
- ✅ Statistiken berechnet wenn nötig
- ✅ Multi-Turn Konversationen unterstützt ("Was ist der Durchschnitt?")
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
- *"Zeig mir die Drehmomente aller 6 Achsen der letzten 5 Minuten"*
- *"Was ist der Durchschnitt?"* (Multi-Turn!)
- *"Wie ist die aktuelle TCP Position?"*

## 🏗️ Architektur

```
User Query ("Zeig Drehmomente der letzten 5 Min")
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│              Chainlit Frontend (app.py)                  │
└─────────────────────────┬───────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│         LangGraph Orchestrierung (graph.py)              │
│                                                          │
│  ┌──────────┐    ┌────────────┐    ┌──────────┐         │
│  │Supervisor│ →  │ Data Agent │ →  │Viz Agent │         │
│  │ (Planer) │    │  (Daten)   │    │ (Charts) │         │
│  └──────────┘    └─────┬──────┘    └────┬─────┘         │
│        │               │                 │               │
│        ▼               ▼                 ▼               │
│  ┌───────────┐  ┌────────────┐   ┌────────────┐         │
│  │Stats Agent│  │Error Handler│   │  Respond   │         │
│  │(Statistik)│  │ (Graceful) │   │  (Final)   │         │
│  └───────────┘  └────────────┘   └────────────┘         │
│                                                          │
│  Features: Checkpointer, max_steps Guard, Error Handler  │
└────────────────────────┬─────────────────┬──────────────┘
                         │                 │
                         ▼                 ▼
              ┌─────────────────┐  ┌─────────────────┐
              │ ThingsBoard MCP │  │ AntV MCP Server │
              │   (8 Tools)     │  │   (25 Tools)    │
              └────────┬────────┘  └────────┬────────┘
                       │                    │
                       ▼                    ▼
              ┌─────────────────┐  ┌─────────────────┐
              │   ThingsBoard   │  │  Chart-URLs     │
              │   (IIoT-Daten)  │  │  (AntV Cloud)   │
              └─────────────────┘  └─────────────────┘
```

## ✨ Features

### Multi-Turn Konversationen (DEC-013)
```
User: "Zeig mir die Drehmomente der letzten 5 Minuten"
Bot:  [Chart mit 6 Achsen]

User: "Was ist der Durchschnitt?"
Bot:  "Achse A1: -0.303 Nm, Achse A2: 0.635 Nm, ..."
      ↑ Erkennt: Daten sind schon da, nur Stats berechnen!
```

### Production-Ready (DEC-016, DEC-017)
- **Strukturiertes Logging** mit Timestamps und Levels
- **Retry-Mechanismus** mit exponential Backoff
- **Error Handler** für graceful Failure
- **Cycle Guard** (max_steps) gegen Endlosschleifen
- **Thread-Safe** Singleton Pattern

### Intelligente Abstention
```
User: "Wie wird das Wetter?"
Bot:  "Ich bin für IIoT-Datenanalyse zuständig. 
       Für Wetterinformationen kann ich leider nicht helfen."
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
│   ├── state.py           # AgentState mit Reducern (DEC-013)
│   ├── data_agent.py      # Holt Daten via MCP
│   ├── viz_agent.py       # Generiert Charts via AntV
│   ├── stats_agent.py     # Berechnet Statistiken
│   ├── supervisor.py      # Plant Agent-Reihenfolge
│   ├── graph.py           # LangGraph Orchestrierung (DEC-017)
│   └── utils.py           # Gemeinsame Hilfsfunktionen
├── prompts/               # System Prompts (DEC-015: XML-Tags)
│   ├── data_agent_prompt.py
│   ├── viz_agent_prompt.py
│   ├── stats_agent_prompt.py
│   ├── supervisor_prompt.py
│   └── respond_prompt.py
├── mcp_servers/
│   ├── thingsboard_client.py  # Async HTTP Client
│   └── thingsboard_server.py  # 8 Tools, Timerange-Parser
├── tests/                     # Unit + Integration Tests
├── docs/
│   ├── DECISIONS.md           # 17 Pattern-Entscheidungen
│   ├── 04_AKTUELLER_STAND.md
│   └── ...
├── outputs/data/              # Telemetrie-Dateien (JSON)
├── config/settings.py
├── app.py                     # Chainlit Frontend
└── CLAUDE.md                  # KI-Assistenten Kontext
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
# Relative Angaben
"letzte 5 Minuten", "letzte Stunde", "heute", "gestern"

# Wochentage
"Dienstag", "Dienstag 12 Uhr", "Dienstag um 13:30"

# Datum
"16."           → 16. des aktuellen Monats
"16. Dezember"  → 16. Dezember
"16.12.2025"    → Exaktes Datum
```

## 🧪 Tests

```bash
# Unit Tests (schnell)
python -m pytest tests/ -m "not integration" -v

# Integration Tests (braucht ThingsBoard)
python -m pytest tests/ -m integration -v

# Alle Tests
python -m pytest tests/ -v
```

## 📊 Entscheidungs-Patterns

Das Projekt dokumentiert 17 wiederverwendbare Patterns in `docs/DECISIONS.md`:

| ID | Pattern | Problem → Lösung |
|----|---------|------------------|
| DEC-013 | Multi-Turn Persistenz | State verloren → Checkpointer + Reducer |
| DEC-014 | SystemMessage Filter | API-Fehler → Filter + frische Message |
| DEC-015 | XML-Tag Prompts | Unstrukturiert → `<role>`, `<task>`, etc. |
| DEC-016 | Production Quality | print() → Logging, SRP, Retry |
| DEC-017 | Graph Best Practices | Endlosschleifen → max_steps, Error Handler |

## 📊 Status

| Komponente | Status | Letzte Änderung |
|------------|--------|-----------------|
| ThingsBoard MCP | ✅ Fertig | 8 Tools, Timerange-Parser |
| Data Agent | ✅ Fertig | DEC-016 |
| Viz Agent | ✅ Fertig | DEC-016 |
| Stats Agent | ✅ Fertig | DEC-016 |
| Supervisor | ✅ Fertig | DEC-016 |
| Graph | ✅ Fertig | DEC-017 |
| Multi-Turn | ✅ Fertig | DEC-013 |
| Frontend | ✅ Fertig | Chainlit |

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
