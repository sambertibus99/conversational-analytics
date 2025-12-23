# CLAUDE.md - Projekt-Kontext

> **Letzte Aktualisierung:** 23.12.2025, DEC-017 Graph Best Practices

## Projekt

**Conversational Analytics für IIoT** (Masterarbeit)
- **Ziel:** MCP-basiertes System für natürlichsprachliche Datenanalyse
- **Abgabe:** 31. März 2025
- **Pfad:** `/home/sam/ma_ws/conversational-analytics`

---

## 🔄 SESSION-WORKFLOW

### Phase 1: Review (KEIN Code!)
```
1. Komponente lesen
2. ALLE Verbesserungen auflisten:
   - Bugs/Probleme
   - Veraltetes (passt nicht zu aktuellen DECs)
   - Fehlendes (neue DECs anwenden)
   - Redundantes
3. User priorisiert: "Diese Session machen wir X und Y"
```

### Phase 2: Änderungen (mit Ankündigung)
```
Ich: "Ich will Zeile 45-60 ändern weil [Grund].
     Vorher: [kurzer Ausschnitt]
     Nachher: [kurzer Ausschnitt]
     OK?"

Du: "Ja" oder "Nein, weil..."
```

### Phase 3: Abschluss
```
1. Tests ausführen
2. Entscheidungen dokumentieren (wenn neue)
3. CLAUDE.md aktualisieren für nächste Session
```

### Regeln
- **Eine Komponente pro Session** (eine Datei)
- **Scope vorher festlegen** - kein Scope Creep
- **Kleinere Edits** - reviewbar, nicht alles auf einmal

---

## 🎯 NÄCHSTE SESSION

**Optional: Rate Limiter einbauen**

Um 429 Too Many Requests proaktiv zu verhindern:
```python
from langchain_core.rate_limiters import InMemoryRateLimiter

rate_limiter = InMemoryRateLimiter(
    requests_per_second=0.5,  # 1 request per 2 seconds
)
```

---

## ✅ SESSION-LOG

### ✅ Session 23.12.2025 - Graph Best Practices (DEC-017)

**AP 2.3 - Graph Review gegen LangGraph Best Practices:**

| Issue | Fix | Status |
|-------|-----|--------|
| Keine Cycle Guard | `max_steps=10` im State + Router-Check | ✅ |
| Kein Error-Handler | `error_handler_node` hinzugefügt | ✅ |
| Keine State-Validierung | `respond_node` prüft Messages | ✅ |
| Code-Duplizierung | DRY Routing-Map + Agent Wrapper Factory | ✅ |
| `debug_print()` | Strukturiertes Logging | ✅ |
| Thread-Safety | `_graph_lock` für Singleton | ✅ |
| Prompt in Code | `prompts/respond_prompt.py` ausgelagert | ✅ |

**Geänderte Dateien:**
- `agents/graph.py` - Komplett refactored
- `agents/state.py` - `error_count`, `max_steps` hinzugefügt
- `prompts/respond_prompt.py` - **NEU**

**Test-Ergebnisse:**
```
✅ "Zeig mir die Drehmomente" → Plan: ['data_agent', 'viz_agent'] → Chart
✅ "Was ist der Durchschnitt?" → Plan: ['stats_agent'] → Multi-Turn!
✅ "Wie wird das Wetter?" → Plan: [] → Höflich abgelehnt
```

---

### ✅ Session 23.12.2025 - Production Code Quality (DEC-016)

**Alle Agents refactored für Production:**

| Agent | Änderungen |
|-------|------------|
| `data_agent.py` | Logging, SRP, Retry, MCPToolsProvider |
| `viz_agent.py` | Logging, SRP, Retry, AntVSessionProvider |
| `stats_agent.py` | Logging, SRP, Retry mit Fallback |
| `supervisor.py` | Logging, Retry, validate_plan aufgeteilt |
| `utils.py` | **NEU** - Gemeinsame Hilfsfunktionen (DRY) |

**Neue Datei `agents/utils.py`:**
- `extract_data_from_datasets()` - Aus viz_agent + stats_agent extrahiert
- `get_dataset_meta()` - Metadaten aus Datasets
- `is_valid_numeric_value()` - Wert-Validierung
- `extract_values_from_data()` - ThingsBoard-Format parsen
- `extract_user_query()` - Letzte HumanMessage
- `get_y_label()` - Y-Achsen-Label für Charts

---

### ✅ Session 23.12.2025 - Prompt-Optimierung (DEC-015)

**Prompt-Refactoring basierend auf Anthropic Best Practices:**
1. **XML-Tags für Struktur** - `<role>`, `<task>`, `<instructions>`, `<examples>`, etc.
2. **Positive Anweisungen** - "Rufe max 6-10 Keys ab" statt "NIEMALS alle Keys"
3. **Redundanzen entfernt** - ~28% kürzer
4. **Klare Sektionen** - Besser parsbar für Claude

**Geänderte Dateien:**
- `prompts/data_agent_prompt.py`: Komplettes Refactoring
- `prompts/supervisor_prompt.py`: XML-Tags + gestrafft
- `prompts/viz_agent_prompt.py`: XML-Tags + Unicode-Boxen entfernt
- `prompts/stats_agent_prompt.py`: XML-Tags + gestrafft

---

### ✅ Frühere Session 23.12.2025 - Multi-Turn Bug-Fixes

**Bugs gefixt:**
1. **current_step Persistenz** - Reset bei neuem Plan
2. **Multiple SystemMessages** - Filter (DEC-014)
3. **Respond zeigt keine Werte** - Datenwerte-Extraktion
4. **Unnötiger Viz-Agent** - Supervisor-Prompt für leeren Plan

---

### ✅ AP2.2 abgeschlossen (20.12.2025)

**Multi-Turn Daten-Persistenz vollständig gelöst (DEC-013):**
- Checkpointer mit `InMemorySaver`
- `datasets` mit Reducer `merge_datasets`
- `data_summary` mit Reducer `merge_summaries`

---

## 🧠 Entscheidungs-Katalog

**Bei ähnlichen Problemen → zuerst hier schauen!**

| Pattern | Problem | Lösung | ID |
|---------|---------|--------|-----|
| **Tool Selection** | Welches Tool bei <10 Tools? | Optimierte Descriptions | DEC-001 |
| **LLM-Parsing** | Komplexe User-Eingabe | LLM parst → strukturiert | DEC-002 |
| **InjectedState** | Große Daten an Tool | Via State, nicht Prompt | DEC-003 |
| **File-Storage** | Token-Limit | Rohdaten→Datei | DEC-004 |
| **MCP Warmup** | Langsame Requests | Globale Session | DEC-005 |
| **Auto-Aggregation** | Zu viele Punkte | Intervall auto | DEC-006 |
| **Message-Filtering** | Multiple SystemMessages | Nur HumanMessages | DEC-007 |
| **Status-First** | Response nicht erkannt | Status ZUERST | DEC-008 |
| **Error Handling** | HTTP-Fehler, Retries | Custom Exceptions + Retry | DEC-009 |
| **Datenpunkt-Limit** | User will zu viele Daten | Warnung/Fehler + Vorschlag | DEC-010 |
| **Literal statt Regex** | Param-Parsing fehleranfällig | Vordefinierte Optionen | DEC-011 |
| **Integration Testing** | MCP+LLM Tests instabil | Cleanup + Delays + Marker | DEC-012 |
| **Multi-Turn Persistenz** | State zwischen Turns verloren | Checkpointer + Reducer | DEC-013 |
| **SystemMessage Filter** | Multiple SystemMessages Fehler | Filter + frische SystemMessage | DEC-014 |
| **XML-Tag Prompt-Struktur** | Prompt unstrukturiert | XML-Tags für Sektionen | DEC-015 |
| **Production Code Quality** | print(), lange Funktionen | Logging, SRP, Retry | DEC-016 |
| **Graph Best Practices** | Endlosschleifen, kein Error-Handler | max_steps, error_handler | DEC-017 |

**Details:** `docs/DECISIONS.md`

---

## 📚 Dokumentations-Katalog

| Datei | Wann laden? |
|-------|-------------|
| `docs/DECISIONS.md` | Ähnliches Problem lösen |
| `docs/04_AKTUELLER_STAND.md` | Session-Start |
| `docs/design/[komponente].md` | Komponente reviewen |
| `docs/07_ERROR_HANDLING.md` | Bug auftritt |

---

## 📋 Review-Status

| Komponente | Status | Offen |
|------------|--------|-------|
| ThingsBoard MCP | ✅ Fertig | - |
| Data Agent Prompt | ✅ AP2.1 | - |
| Data Agent Code | ✅ AP2.2 | DEC-016 |
| Graph | ✅ AP2.3 | DEC-017 |
| Viz Agent | ✅ | DEC-016 |
| Stats Agent | ✅ | DEC-016 |
| Supervisor | ✅ | DEC-016 |

---

## ⚡ Befehle

```bash
cd ~/ma_ws/conversational-analytics
source venv/bin/activate
chainlit run app.py

# Tests
python -m pytest tests/ -m "not integration" -v  # Schnell (226 Tests)
python -m pytest tests/ -m integration -v          # Langsam (braucht ThingsBoard)
python -m pytest tests/test_mcp_server/ -v         # Nur MCP Server
```
