# AKTUELLER STAND

> **Letzte Aktualisierung:** 23. Dezember 2025, 10:30 Uhr

---

## 🎯 Aktuelle Session: Multi-Turn Bug-Fixes

### ✅ Erledigt (23.12.2025)

**Bug 1: current_step Persistenz**
- Problem: `current_step` wurde vom Checkpointer persistiert, aber bei neuem Plan nicht zurückgesetzt
- Turn 1 endete mit `current_step=2`, Turn 2 startete mit Step 2 statt 0
- Fix: `current_step: 0` im Supervisor-Return bei neuem Plan

**Bug 2: Multiple SystemMessages (Anthropic API)**
- Problem: Messages aus Checkpoint enthielten alte SystemMessages
- `ValueError: Received multiple non-consecutive system messages`
- Fix: SystemMessages filtern in `data_agent.py` und `stats_agent.py`

**Bug 3: Respond-Node zeigt keine Datenwerte**
- Problem: User fragte "zeig die Werte", aber Respond sah nur "6 Keys" nicht die Werte
- Fix: `respond_node` extrahiert jetzt tatsächliche Werte aus `datasets`

**Bug 4: Unnötiger Viz-Agent bei Textanfragen**
- Problem: "Zeig mir die Zahlenwerte" triggerte Viz-Agent statt direkte Antwort
- Fix: Supervisor-Prompt erweitert mit Beispiel für leeren Plan bei vorhandenen Daten

### Geänderte Dateien
```
agents/supervisor.py      # current_step Reset + Datasets-Kontext für LLM
agents/data_agent.py      # SystemMessage Filter
agents/stats_agent.py     # SystemMessage Filter  
agents/graph.py           # Respond-Node zeigt Datenwerte
prompts/supervisor_prompt.py  # Multi-Turn Beispiele
```

### Neue Entscheidung
**DEC-014: SystemMessage-Handling bei Multi-Turn**
- Anthropic erlaubt nur eine SystemMessage am Anfang
- Best Practice: Messages aus State filtern, frische SystemMessage prependen

---

## 📚 Best Practices aus Recherche (23.12.2025)

### LangGraph Multi-Turn mit Anthropic

**Problem:** Bei Multi-Turn akkumulieren SystemMessages im State → API-Fehler

**Lösung 1: Filter (unser Ansatz)**
```python
filtered_messages = [msg for msg in state["messages"] if not isinstance(msg, SystemMessage)]
messages = [SystemMessage(content=prompt), *filtered_messages]
```

**Lösung 2: create_react_agent mit prompt Parameter**
```python
agent = create_react_agent(model=llm, tools=tools, prompt="System prompt...")
```

**Lösung 3: Custom call_model Node (offizielle Docs)**
```python
def call_model(state, config):
    system_prompt = SystemMessage("...")
    return model.invoke([system_prompt] + state["messages"])
```

---

## 🧪 Test-Szenario für Multi-Turn

```
1. "Welche Position haben die Achsen des Roboters?"
   → Plan: ['data_agent']
   → Lädt axis Dataset (6 Keys)
   
2. "Zeig mir die Zahlenwerte"
   → Plan: [] (leerer Plan - Daten sind schon da!)
   → Respond zeigt: axis_act_a1_deg: 45.2, axis_act_a2_deg: -12.8, ...

3. "Gibt es einen Zusammenhang mit dem Drehmoment?"
   → Supervisor sieht: datasets=['axis'], keys nicht torque
   → Plan: ['data_agent', 'stats_agent']
   → Lädt torque, berechnet Korrelation
```

---

## 📋 Review-Status Gesamt

| Komponente | Status | Offene Punkte |
|------------|--------|---------------|
| ThingsBoard MCP | ✅ Fertig | - |
| Data Agent Prompt | ✅ AP2.1 | - |
| Data Agent Code | ✅ AP2.2 | Multi-Turn Fix (DEC-013, DEC-014) |
| Data Graph | ✅ AP2.3 | Respond-Node zeigt Werte |
| Viz Agent | 🔄 3/4 | Error Handling |
| Stats Agent | 🔄 | SystemMessage Fix |
| Supervisor | ✅ | Multi-Turn Kontext |

---

## 📁 Dokumentations-Struktur

```
docs/
├── DECISIONS.md              # ⭐ Entscheidungs-Datenbank (14 Patterns)
├── 04_AKTUELLER_STAND.md     # Diese Datei
├── 05_ARCHITEKTUR.md         # Systemübersicht
├── 07_ERROR_HANDLING.md      # Fehler & Fixes
├── 08_TESTFRAGEN.md          # Evaluation
├── 09_THINGSBOARD_SETUP.md   # Setup-Referenz
├── design/                   # Komponenten-Details
└── archive/                  # Alte Dokumente
```

---

## ⚡ Befehle

```bash
cd ~/ma_ws/conversational-analytics
source venv/bin/activate
chainlit run app.py

# Tests
python -m pytest tests/ -m "not integration" -v  # Schnell
python -m pytest tests/ -m integration -v         # Mit ThingsBoard
```
