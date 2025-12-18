# PROJEKT-KONTEXT

## Grunddaten

| Feld | Wert |
|------|------|
| **Titel** | Conversational Analytics im IIoT: Konzeption und Evaluation eines agentenbasierten Systems zur dynamischen Generierung von Datenvisualisierungen mittels Model Context Protocol (MCP) |
| **Typ** | Masterarbeit |
| **Abgabe** | 31. März 2025 |
| **Ziel** | Note 1,0 |
| **Sprache** | Deutsch |

---

## Problemstellung

**Status Quo:**
- IIoT-Plattformen (ThingsBoard) haben statische Dashboards
- Nutzer müssen Dashboards manuell konfigurieren
- Ad-hoc-Analysen erfordern technisches Know-how
- Keine natürlichsprachliche Interaktion möglich

**Lösung:**
Ein MCP-basiertes System das:
- Natürlichsprachliche Anfragen versteht
- Automatisch die richtigen Daten abruft
- Dynamisch passende Visualisierungen generiert
- Statistiken berechnet wenn nötig

---

## Forschungslücke

```
EXISTIERT:                    EXISTIERT NICHT:
──────────────────────────────────────────────────
NL2Vis für BI-Tools           NL2Vis für IIoT
LLM-Agenten für Industrie     ...mit MCP-Standard
IIoT-Plattformen              ...mit NL-Interface
MCP als Standard              ...akademisch evaluiert
                              
→ DEINE ARBEIT: Erstes MCP-basiertes Conversational Analytics System für IIoT mit akademischer Evaluation
```

---

## Technisches Setup

```
┌─────────────────┐
│   KUKA Roboter  │
│   (2 Arme)      │
└────────┬────────┘
         │ MQTT / OPC UA
         ▼
┌─────────────────┐
│   ThingsBoard   │
│   (IoT Platform)│
└────────┬────────┘
         │ MCP
         ▼
┌─────────────────────────────────────┐
│         DEIN SYSTEM                  │
│                                      │
│  ┌───────────┐  ┌───────────┐       │
│  │Supervisor │→ │Data Agent │       │
│  └───────────┘  └─────┬─────┘       │
│        │              │              │
│        ▼              ▼              │
│  ┌───────────┐  ┌───────────┐       │
│  │Viz Agent  │← │Stats Agent│       │
│  └───────────┘  └───────────┘       │
│                                      │
└──────────────────┬───────────────────┘
                   │
                   ▼
            ┌─────────────┐
            │   Chainlit  │
            │  (Frontend) │
            └─────────────┘
```

---

## Tool-Situation (Das Kernproblem)

| MCP Server | Tools gesamt | Tools relevant | Reduktion |
|------------|--------------|----------------|-----------|
| ThingsBoard | 140 | ~15 | 89% |
| AntV | 25 | ~10 | 60% |
| Statistik | ~35 | ~8 | 77% |
| **Gesamt** | **~200** | **~33** | **83%** |

**Problem:** 200 Tools × ~500 Tokens = 100.000 Tokens nur für Tool-Definitionen

**Lösung:** 
1. Tool-Filterung nach Domänen
2. Supervisor wählt welche Agent-Toolsets geladen werden
3. Code-Execution-Pattern für Datentransport (Anthropic-Ansatz)

---

## Evaluation

### 15 Testfragen (3 Schwierigkeitsstufen)

| Stufe | Anzahl | Beispiel |
|-------|--------|----------|
| Leicht | 5 | "Zeig aktuelle Temperatur von Roboter 1" |
| Mittel | 5 | "Temperaturverlauf der letzten 24h als Liniendiagramm" |
| Schwer | 5 | "Korrelation Temperatur/Druck mit Scatter-Plot und Trendlinie" |

### Metriken

| Metrik | Beschreibung | Ziel |
|--------|--------------|------|
| **Execution Accuracy (EX)** | % fehlerfreie Skript-Ausführungen | >80% |
| **Tool Selection Accuracy (TSA)** | % korrekte Tool-Auswahl | >90% |
| **Data Faithfulness** | Keine Halluzinationen bei Daten | 100% |
| **Abstention Rate** | Korrekte Verweigerung bei ungültigen Anfragen | >80% |

---

## Tech Stack

| Komponente | Technologie | Begründung |
|------------|-------------|------------|
| **Framework** | LangGraph | MCP-Adapter, akademisch zitierbar |
| **LLM** | Claude (Anthropic) | MCP-Erfinder, beste Tool-Use |
| **Frontend** | Chainlit | Einfach, Chart-Support |
| **MCP Server** | Geforkte Versionen | Tool-Reduktion |
| **Datenquelle** | ThingsBoard | Open Source, REST API |
| **Visualisierung** | AntV / Plotly | Flexible Chart-Generierung |

---

## Zeitplan (grob)

| Phase | Zeitraum | Inhalt |
|-------|----------|--------|
| Implementierung | Dez 2024 - Jan 2025 | System bauen |
| Evaluation | Feb 2025 | 15 Testfragen durchführen |
| Schreiben | Feb - März 2025 | Kapitel 4-6 |
| Abgabe | 31. März 2025 | - |

---

## Wichtige Entscheidungen (bisher)

| Datum | Entscheidung | Begründung |
|-------|--------------|------------|
| Dez 2024 | LangGraph statt n8n | Akademisch besser dokumentierbar |
| Dez 2024 | Tool-Filterung statt RATS | Einfacher, transparenter |
| Dez 2024 | Supervisor + 3 Worker | Klare Trennung, einfach evaluierbar |
| Dez 2024 | Chainlit statt Custom UI | Zeitersparnis, Chart-Support |
