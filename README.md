# Conversational Analytics für IIoT

> MCP-basiertes System für natürlichsprachliche Datenanalyse von KUKA Robotern

## 🎯 Projektziel

Masterarbeit: Entwicklung eines Conversational Analytics Systems das:
- Natürlichsprachliche Anfragen versteht
- Automatisch Daten von ThingsBoard (IIoT-Plattform) abruft
- Dynamisch passende Visualisierungen generiert
- Statistiken berechnet wenn nötig

## 🏗️ Architektur

```
User Query
    │
    ▼
┌─────────────────────────────────────────────┐
│         LangGraph Orchestration              │
│                                              │
│   Supervisor → Data Agent → Viz Agent        │
│                    │            │            │
│                    ▼            ▼            │
│              MCP Client    MCP Client        │
└──────────────────┬─────────────┬────────────┘
                   │             │
                   ▼             ▼
          ┌────────────┐  ┌─────────────────┐
          │ ThingsBoard│  │ @antv/mcp-      │
          │ MCP Server │  │ server-chart    │
          │ (8 Tools)  │  │ (25 Tools)      │
          └────────────┘  └─────────────────┘
```

## 📦 Installation

```bash
# Repository klonen
git clone <repo-url>
cd conversational-analytics

# Virtual Environment erstellen
python -m venv venv
source venv/bin/activate  # Linux/Mac
# oder: venv\Scripts\activate  # Windows

# Dependencies installieren
pip install -r requirements.txt

# .env Datei erstellen
cp .env.example .env
# Dann ANTHROPIC_API_KEY und ThingsBoard-Credentials eintragen
```

## ⚙️ Konfiguration

`.env` Datei:
```
# Anthropic
ANTHROPIC_API_KEY=sk-ant-...

# ThingsBoard
THINGSBOARD_URL=http://localhost:8080
THINGSBOARD_USERNAME=tenant@thingsboard.org
THINGSBOARD_PASSWORD=tenant
KRC5_DEVICE_ID=<device-id>
```

## 🧪 Tests

```bash
# Data Agent testen
python agents/data_agent.py

# Viz Agent testen (simulierte Daten)
python agents/viz_agent.py

# End-to-End Pipeline
python tests/test_data_viz_pipeline.py

# AntV MCP Server testen
python tests/test_antv_mcp.py
```

## 📁 Projektstruktur

```
conversational-analytics/
├── agents/
│   ├── state.py           # Shared State
│   ├── data_agent.py      # ThingsBoard Daten holen
│   └── viz_agent.py       # Charts generieren
├── mcp_servers/
│   ├── thingsboard_client.py  # HTTP Client
│   └── thingsboard_server.py  # MCP Server (8 Tools)
├── prompts/
│   ├── data_agent_prompt.py
│   └── viz_agent_prompt.py
├── tests/
│   └── ...
├── config/
│   └── settings.py
└── requirements.txt
```

## 🔧 MCP Server

### ThingsBoard MCP (eigener Server)
- `list_devices` - Geräte auflisten
- `get_device_info` - Gerätedetails
- `list_telemetry_keys` - Verfügbare Messwerte
- `get_latest_telemetry` - Aktuellste Werte
- `get_telemetry` - Zeitreihen
- `get_telemetry_aggregated` - Aggregierte Daten
- `get_attributes` - Statische Attribute
- `list_attribute_keys` - Verfügbare Attribute

### AntV MCP (externer Server)
```bash
npx -y @antv/mcp-server-chart
```
- 25+ Chart-Tools (line, bar, scatter, area, boxplot, etc.)

## 📊 Status

| Komponente | Status |
|------------|--------|
| ThingsBoard MCP | ✅ Fertig |
| Data Agent | ✅ Fertig |
| AntV Integration | ✅ Fertig |
| Viz Agent | ✅ Fertig |
| Stats Agent | ⬜ Offen |
| Supervisor | ⬜ Offen |
| Frontend | ⬜ Offen |

## 📝 Lizenz

Masterarbeit - Alle Rechte vorbehalten
