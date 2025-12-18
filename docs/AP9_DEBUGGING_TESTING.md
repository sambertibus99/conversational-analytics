# ARBEITSPAKET 9: Systematisches Debugging & Testing

> **Status:** ⬜ Offen
> **Dauer:** ~6 Stunden
> **Abhängigkeiten:** AP7 (Frontend)
> **Priorität:** HOCH - Vor Evaluation durchführen!

---

## Ziel

Systematisches Testen aller Agents und Schnittstellen, um Fehler wie in Session 18.12.2025 zu vermeiden.
Perspektiven: Prompt Engineer, KI-Entwickler, Software-Entwickler, Schnittstellen-Entwickler.

---

## 1. Response-Format-Tests (Schnittstellen-Perspektive)

### 1.1 MCP Server Response-Formate prüfen

Jedes Tool muss alle Status-Typen korrekt zurückgeben:

```python
# tests/test_mcp_responses.py

EXPECTED_RESPONSE_FORMATS = {
    "get_telemetry": {
        "success": ["status", "timerange", "data_points", "statistics", "data_file"],
        "no_data": ["status", "message", "requested_timerange", "hint"],
    },
    "get_data_availability": {
        "data_available": ["status", "data_range", "message", "total_points"],
        "no_data": ["status", "message"],
    },
    "get_latest_telemetry": {
        "success": ["<key>", "value", "timestamp", "timestamp_human", "weekday"],
    },
}

def test_response_has_required_fields():
    """Prüft ob alle Response-Formate die erwarteten Felder haben."""
    pass

def test_no_data_response():
    """Prüft ob 'no_data' korrekt zurückgegeben wird bei leerem Zeitraum."""
    pass

def test_error_response():
    """Prüft ob Fehler sauber behandelt werden."""
    pass
```

### 1.2 Testfragen für Response-Formate

| # | Query | Erwartetes Format | Kritische Felder |
|---|-------|-------------------|------------------|
| R1 | "TCP Position Dienstag 13 Uhr" (keine Daten) | `no_data` | status, message, requested_timerange |
| R2 | "TCP Position Dienstag 12 Uhr" (Daten vorhanden) | `success` | status, statistics, data_file |
| R3 | "Wann gibt es Daten?" | `data_available` | status, data_range |
| R4 | "Daten vom KRC6" (falsches Device) | `error` | status, message |
| R5 | "Temperatur Achse 1" (falscher Key) | `error` oder leeres Ergebnis | status |

---

## 2. Data Agent Tests (KI-Entwickler-Perspektive)

### 2.1 extract_data_from_parsed() vollständig testen

```python
# tests/test_data_agent_parsing.py

TEST_RESPONSES = [
    # SUCCESS mit data_file
    {
        "input": {"status": "success", "data_file": "/path/to/file.json", "statistics": {...}},
        "expected_type": "success",
        "expected_data": "loaded_from_file",
    },
    # NO_DATA
    {
        "input": {"status": "no_data", "message": "Keine Daten", "requested_timerange": {...}},
        "expected_type": "no_data",
        "expected_data": None,
    },
    # DATA_AVAILABLE
    {
        "input": {"status": "data_available", "data_range": {...}},
        "expected_type": "data_availability",
        "expected_data": "original_dict",
    },
    # LATEST TELEMETRY
    {
        "input": {"axis_act_a1_deg": {"value": "25.3", "timestamp": 123}},
        "expected_type": "latest",
        "expected_data": "original_dict",
    },
    # LIST (Keys, Devices)
    {
        "input": ["key1", "key2", "key3"],
        "expected_type": "list",
        "expected_data": "original_list",
    },
]

def test_all_response_formats():
    """Testet alle bekannten Response-Formate."""
    for test in TEST_RESPONSES:
        data, meta, file = extract_data_from_parsed(test["input"])
        assert meta["type"] == test["expected_type"]
```

### 2.2 generate_data_summary() testen

```python
def test_summary_for_no_data():
    """Summary muss 'KEINE DATEN' enthalten."""
    meta = {"type": "no_data", "message": "...", "requested_timerange": {...}}
    summary = generate_data_summary(None, meta)
    assert "KEINE DATEN" in summary

def test_summary_for_data_availability():
    """Summary muss Zeitraum enthalten."""
    meta = {"type": "data_availability", "data_range": {"first_data": "...", "last_data": "..."}}
    summary = generate_data_summary({}, meta)
    assert "VERFÜGBAR" in summary
```

---

## 3. Viz Agent Tests (KI-Entwickler-Perspektive)

### 3.1 Message-Filtering testen

```python
# tests/test_viz_agent.py

def test_only_human_messages_passed():
    """Viz Agent darf keine SystemMessages aus vorherigen Agents übernehmen."""
    state = AgentState(
        messages=[
            SystemMessage(content="System Prompt Data Agent"),  # MUSS gefiltert werden!
            HumanMessage(content="Zeig als Chart"),
            AIMessage(content="Daten geladen"),  # Optional
            ToolMessage(content="..."),  # Optional
        ],
        data={...},
    )
    
    # Nach Filterung sollten nur HumanMessages übrig sein
    human_messages = [m for m in state["messages"] if isinstance(m, HumanMessage)]
    assert len(human_messages) == 1
```

### 3.2 Daten-Transformation testen

```python
def test_transform_timeseries():
    """ThingsBoard → AntV Format."""
    tb_data = {
        "pos_act_x_mm": [
            {"value": "94.5", "timestamp": 1702900000000},
            {"value": "95.0", "timestamp": 1702900001000},
        ]
    }
    antv_data = transform_timeseries_for_antv(tb_data)
    
    assert antv_data[0]["time"] == "10:00:00"  # oder ähnlich
    assert antv_data[0]["value"] == 94.5
    assert isinstance(antv_data[0]["value"], float)  # Nicht String!
```

---

## 4. Supervisor Tests (Prompt-Engineer-Perspektive)

### 4.1 Plan-Generierung testen

| # | Query | Erwarteter Plan | Begründung |
|---|-------|-----------------|------------|
| S1 | "Zeig Temperatur" | `["data_agent", "viz_agent"]` | Daten + Visualisierung |
| S2 | "Aktuelle Position Achse 1" | `["data_agent"]` | Nur Daten, kein Chart |
| S3 | "Durchschnittstemperatur berechnen" | `["data_agent", "stats_agent"]` | Daten + Statistik |
| S4 | "Korrelation mit Chart" | `["data_agent", "stats_agent", "viz_agent"]` | Alle drei |
| S5 | "Wie wird das Wetter?" | `[]` | Keine IIoT-Anfrage |
| S6 | "Welche Geräte gibt es?" | `["data_agent"]` | Nur Daten |

### 4.2 Edge Cases

| # | Query | Erwartetes Verhalten |
|---|-------|---------------------|
| S7 | "" (leer) | Höfliche Nachfrage |
| S8 | "asdfghjkl" | Kann nicht interpretiert werden |
| S9 | "Zeig" (ohne Objekt) | Nachfrage was gezeigt werden soll |
| S10 | Sehr langer Text (>500 Wörter) | Trotzdem korrekte Erkennung |

---

## 5. End-to-End Tests (Software-Entwickler-Perspektive)

### 5.1 Happy Path Tests

| # | Query | Schritte | Erwartetes Ergebnis |
|---|-------|----------|---------------------|
| E1 | "TCP Position Dienstag 12 Uhr als Liniendiagramm" | Supervisor → Data → Viz → Respond | Chart-URL in Response |
| E2 | "Wann gibt es Daten?" | Supervisor → Data → Respond | Zeitraum in Response |
| E3 | "Aktuelle Achsposition" | Supervisor → Data → Respond | Werte in Response |

### 5.2 Error Path Tests

| # | Query | Erwartetes Verhalten |
|---|-------|---------------------|
| E4 | "TCP Position gestern 3 Uhr" (keine Daten) | Klare "Keine Daten" Meldung, KEIN zweiter Versuch |
| E5 | "Daten vom KRC6" | Klare "Unbekanntes Gerät" Meldung |
| E6 | "Setze Override auf 50%" | Ablehnung (nur Lese-Zugriff) |

### 5.3 Grenzfälle

| # | Query | Erwartetes Verhalten |
|---|-------|---------------------|
| E7 | "Daten der letzten Woche" | Aggregation statt Rohdaten (zu viele Punkte!) |
| E8 | "Alle Achsen gleichzeitig als Chart" | Multi-Line oder Ablehnung |
| E9 | Zwei Anfragen schnell hintereinander | Rate-Limit graceful handling |

---

## 6. Token-Budget Tests (Architektur-Perspektive)

### 6.1 Datenmenge messen

```python
def test_data_not_in_llm_context():
    """Rohdaten dürfen NICHT an LLM gehen."""
    # Simuliere 1000 Datenpunkte
    large_data = generate_test_data(1000)
    
    # Nach MCP-Call: Prüfe was an LLM geht
    response = mcp_server.get_telemetry(...)
    
    # Response sollte < 5KB sein (nur Summary)
    assert len(json.dumps(response)) < 5000
    
    # data_file sollte existieren
    assert "data_file" in response
    
    # Rohdaten sollten NICHT in Response sein
    assert "data" not in response or len(response["data"]) == 0
```

### 6.2 Zeitraum-Limits testen

| Zeitraum | Erwartetes Verhalten |
|----------|---------------------|
| 10 Minuten | Rohdaten OK |
| 1 Stunde | Rohdaten OK (mit Warnung?) |
| 24 Stunden | Aggregation empfehlen |
| 1 Woche | Aggregation erzwingen |

---

## 7. Timerange-Parsing Tests (Schnittstellen-Perspektive)

```python
# tests/test_timerange_parsing.py

TIMERANGE_TESTS = [
    # Wochentage
    ("Dienstag 13 Uhr", "16.12.2025 12:55", "16.12.2025 13:05"),
    ("Montag 9:30", "15.12.2025 09:25", "15.12.2025 09:35"),
    ("letzten Freitag", "12.12.2025 11:55", "12.12.2025 12:05"),
    
    # Relative
    ("letzte Stunde", "NOW-1h", "NOW"),
    ("letzte 30 Minuten", "NOW-30m", "NOW"),
    ("heute", "TODAY 00:00", "NOW"),
    
    # Gestern
    ("gestern um 14 Uhr", "YESTERDAY 13:55", "YESTERDAY 14:05"),
    ("gestern", "YESTERDAY 00:00", "YESTERDAY 23:59"),
    
    # Edge Cases
    ("", "NOW-1h", "NOW"),  # Default
    ("blabla", "NOW-1h", "NOW"),  # Fallback
]

def test_all_timeranges():
    """Testet alle Zeitraum-Formate."""
    for query, expected_start, expected_end in TIMERANGE_TESTS:
        start_ts, end_ts = parse_timerange(query)
        # Assertions...
```

---

## 8. Implementierung

### 8.1 Test-Struktur erstellen

```
tests/
├── __init__.py
├── conftest.py                    # Pytest Fixtures
├── test_mcp_server/
│   ├── test_thingsboard_responses.py
│   ├── test_timerange_parsing.py
│   └── test_data_file_storage.py
├── test_agents/
│   ├── test_data_agent_parsing.py
│   ├── test_viz_agent_messages.py
│   ├── test_supervisor_planning.py
│   └── test_stats_agent.py
├── test_integration/
│   ├── test_happy_paths.py
│   ├── test_error_paths.py
│   └── test_edge_cases.py
└── test_token_budget.py
```

### 8.2 Test-Runner

```bash
# Alle Tests
pytest tests/ -v

# Nur Unit Tests (schnell)
pytest tests/test_mcp_server tests/test_agents -v

# Nur Integration Tests (langsam, braucht ThingsBoard)
pytest tests/test_integration -v --slow

# Mit Coverage
pytest tests/ --cov=agents --cov=mcp_servers --cov-report=html
```

---

## 9. Checkliste

### Unit Tests
- [ ] `extract_data_from_parsed()` alle Formate
- [ ] `generate_data_summary()` alle Typen
- [ ] `parse_timerange()` alle Varianten
- [ ] `transform_timeseries_for_antv()` Konvertierung
- [ ] Message-Filtering in Viz Agent

### Integration Tests
- [ ] Happy Path: Data → Viz → Chart
- [ ] Error Path: No Data → Klare Meldung
- [ ] Error Path: Falsches Device
- [ ] Edge Case: Große Datenmengen

### Manuell testen
- [ ] Chart wird in Chainlit angezeigt
- [ ] Fehler werden benutzerfreundlich dargestellt
- [ ] Rate Limiting wird graceful behandelt

---

## 10. Geschätzter Aufwand

| Task | Dauer |
|------|-------|
| Test-Struktur aufsetzen | 30 min |
| MCP Response Tests | 1h |
| Data Agent Tests | 1h |
| Viz Agent Tests | 45 min |
| Supervisor Tests | 45 min |
| Integration Tests | 1.5h |
| Dokumentation | 30 min |
| **Gesamt** | **~6h** |

---

## 11. Erfolgskriterien

- [ ] Alle Unit Tests grün
- [ ] Alle Integration Tests grün (mit laufendem ThingsBoard)
- [ ] Code Coverage > 80% für kritische Funktionen
- [ ] Keine "silent failures" - jeder Fehler wird erkannt und behandelt
- [ ] Dokumentation aktuell
