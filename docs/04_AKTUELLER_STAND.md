# AKTUELLER STAND

> **Letzte Aktualisierung:** 13. Februar 2026 (Reasoning-basierter EVAL Prompt)

---

## 🎯 Projekt-Status: Production-Ready + AP7 in Planung

Das System ist funktionsfähig und getestet:

```
✅ "Zeig mir die Drehmomente der letzten 5 Minuten" → Chart
✅ "Was ist der Durchschnitt?" → Multi-Turn Stats
✅ "Wie wird das Wetter?" → Höfliche Absage
✅ "Zeig die Verteilung als Boxplot" → Statistik-Chart
```

---

## ✅ Abgeschlossene Sessions

### Session 10: Reasoning-basierter EVAL Prompt (13.02.2026)

**Problem:** Hart-kodierte Regeln im Supervisor EVAL Prompt (DEC-032) verursachten eine endlose Replan-Schleife beim DEC-030 Stats-to-Viz Flow. Wenn der User nach einer Korrelationsanalyse "Zeig mir das Ergebnis in einem Diagramm" fragte, plante der Supervisor `["stats_agent", "viz_agent"]`. Die EVAL-Regel "Stats-vor-Viz Konflikt" erkannte den fehlenden `data_agent` als Fehler und löste einen Replan aus — obwohl der Gatekeeper-Modus (DEC-030) genau diesen Flow vorsieht. Ergebnis: viz_agent wurde nie ausgeführt.

**Lösung:** `get_supervisor_eval_prompt()` von hart-kodierten Wenn-Dann-Regeln auf reasoning-basierte Agent-Capability-Beschreibungen umgestellt. Neuer Prompt beschreibt:
- `<agents>`: Fähigkeiten, Inputs, Outputs und Modi jedes Agents (inkl. Gatekeeper-Modus)
- `<data_flow>`: 4 typische Datenflüsse durch das System (inkl. Flow 4: stats Gatekeeper → viz ohne data_agent)
- `<task>`: Evaluierungsauftrag ohne starre Regeln — LLM reasoned selbst ob der Plan valide ist

Ansatz basiert auf Anthropics Context Engineering Guide ("Goldilocks Zone"): Spezifisch genug um zu leiten, flexibel genug für Model-Reasoning.

**Änderungen:**
- `prompts/supervisor_prompt.py` — `get_supervisor_eval_prompt()` komplett neu geschrieben: 3 hart-kodierte Regeln → reasoning-basierte `<agents>` + `<data_flow>` + `<task>` Struktur

**Test-Ergebnis:**
- 351 Tests bestanden, 0 Fehler
- Pattern-Review: 0 Verstöße, 15 Patterns korrekt eingehalten (DEC-015, DEC-021, DEC-022, DEC-030, DEC-032 u.a.)

---

### Session 9: DuckDB Single Source of Truth + Supervisor-Replan-Loop (13.02.2026)

**Problem:** DatasetMeta wurde doppelt gehalten (AgentState `datasets` + DuckDB `dataset_meta`), was zu Sync-Problemen führte. Komplexe Multi-Goal-Queries ("Finde die stärkste Belastung und zeig den Zeitraum im Detail") erforderten mehrere manuelle User-Turns.

**Lösung (DEC-031):** Strangler-Fig-Migration in 3 Schritten: Dual-Write → DuckDB-first mit Fallback → `datasets`-Feld komplett entfernt. DuckDB ist jetzt einzige Source of Truth für DatasetMeta. `merge_datasets` Reducer gelöscht.

**Lösung (DEC-032):** Supervisor-Replan-Loop für Multi-Goal-Queries. `replan_bridge` Node erstellt Snapshot der Phase-Ergebnisse und routet zurück zum Supervisor. Max 2 Replans (3 Phasen total). Supervisor plant basierend auf `replan_context` die nächste Phase.

**Änderungen:**
- `config/duckdb_store.py` — `dataset_meta` Tabelle mit CRUD-Methoden (`store_dataset_meta`, `get_dataset_meta`, `get_dataset_metas`, `get_all_dataset_metas`)
- `agents/state.py` — `datasets`-Feld + `merge_datasets` Reducer entfernt. 3 neue Felder: `pending_goals`, `replan_count`, `replan_context`
- `agents/data_agent.py` — `"datasets"` aus Return entfernt, `existing_datasets` via DuckDB
- `agents/utils.py` — `get_dataset_meta_from_duckdb()` Helper, Legacy-Fallbacks entfernt
- `agents/graph.py` — `replan_bridge()` Node, Replan-Routing in `get_next_agent()`, `DEFAULT_MAX_STEPS=15`, `recursion_limit=30`, respond_node mit Vorherige-Phase-Kontext
- `agents/supervisor.py` — `_get_per_turn_reset()`, `_build_replan_context()`, `pending_goals` Extraktion
- `agents/viz_agent.py` — DuckDB-first für Meta, Legacy-Fallbacks entfernt
- `agents/stats_agent.py` — DuckDB-first für Meta, Legacy-Fallbacks entfernt, `calculate_min_max` temporal-aware
- `prompts/supervisor_prompt.py` — `<replan>` Sektion, `pending_goals` in Output-Format, Replan-Beispiele
- `tools/stats_functions.py` — `calculate_min_max(values, timestamps)` mit optionalen Timestamps
- `docs/DECISIONS.md` — DEC-031 + DEC-032 dokumentiert

**Test-Ergebnis:** 333 Tests bestanden (34 neue Tests für DuckDB dataset_meta, Replan-Loop, temporal-aware Stats)

---

### Session 8: DEC-025 DuckDB Reference-only State + Bugfixes + Re-Plan Konzept (04.02.2026)

**Problem:** Rohdaten im AgentState sprengten Token-Limits. Korrelationsanalyse scheiterte weil nur letztes Dataset gespeichert wurde. Data Agent lud teilweise nur Metadaten statt echte Zeitreihen.

**Lösung (DEC-025):** In-Memory DuckDB pro Chat-Session als analytischer Datenspeicher. State hält nur noch DatasetMeta-Referenzen. Mehrere Bugfixes für Multi-Dataset-Speicherung und SessionStore-Lifecycle.

**Änderungen:**
- `config/duckdb_store.py` — **NEU** — SessionStore Singleton mit DuckDB `:memory:`, Schema `telemetry(dataset_key, signal_key, ts, value, unit)`, Convenience-Methoden (get_values, get_timeseries, list_datasets, ASOF JOIN)
- `agents/state.py` — `DatasetMeta` TypedDict, `data_instructions` Feld für Supervisor→Data Agent Kommunikation
- `agents/data_agent.py` — `extract_tool_results()` gibt ALLE Datasets zurück (nicht nur letztes), `_store_dataset_in_duckdb()` Helper, `build_result()` speichert alle Datasets, 0-Punkt-Filter gegen Junk
- `agents/supervisor.py` — Parst `data_instructions` aus LLM-Response, gibt sie im State weiter
- `prompts/supervisor_prompt.py` — `data_instructions` Feld in Output-Format + Beispiele für Korrelation, Exploration
- `config/duckdb_store.py` — `determine_signal_type()` nutzt `telemetry_lookup.json` statt hardcoded Mapping
- `app.py` — SessionStore Lifecycle: `destroy_all()` bei `on_chat_start`, kein Destroy bei `on_chat_end` (Pipeline-Race-Condition)
- `tests/test_duckdb_store.py` — **NEU** — 40 Tests (Lifecycle, Store, Query, UNS-Keys, ASOF JOIN)
- `docs/DECISIONS.md` — DEC-025 dokumentiert

**Bugfixes:**
- Korrelation `n_matched=1` trotz 150k Punkten → nur letztes Dataset wurde in DuckDB gespeichert (jetzt alle)
- `on_chat_end` zerstörte SessionStore während Pipeline noch lief → kein Destroy mehr bei Chat-Ende
- Junk-Datasets (search_telemetry_keys Responses) mit 0 Punkten → gefiltert

**Noch offen (nächste Session):**
- **Re-Planning Loop (DEC-026):** Supervisor bewertet Data Agent Ergebnisse und plant dynamisch um. Plan erstellt, siehe `.claude/plans/nifty-mixing-quail.md`

**Test-Ergebnis:** 176 passed, 49 failed (pre-existing, nicht durch DEC-025 verursacht)

---

### Session 7: Prompt Caching DEC-021 (03.02.2026)

**Problem:** Trotz DEC-020 (Lookup-Optimierung) noch 429-Errors bei Multi-Agent Pipelines wegen wiederholter System Prompts.

**Lösung:** Anthropic Prompt Caching aktiviert für **alle Agents**.

**Wichtig (Gotcha):** LangChain propagiert `additional_kwargs={"cache_control": ...}` NICHT zur Anthropic API. Die Lösung ist, den `content` als `list[dict]` zu formatieren mit `cache_control` im Content-Block. Siehe [GitHub Issue #26701](https://github.com/langchain-ai/langchain/issues/26701).

**Änderungen:**
- `config/settings.py` — `create_cached_system_message()` Hilfsfunktion, `PROMPT_CACHING_HEADERS`
- `agents/supervisor.py` — Nutzt `create_cached_system_message()`
- `agents/graph.py` — respond_node nutzt `create_cached_system_message()`
- `agents/data_agent.py` — `prepare_messages()` nutzt `create_cached_system_message()`
- `agents/stats_agent.py` — Nutzt `create_cached_system_message()`
- `agents/viz_agent.py` — `select_and_execute_tool()` nutzt `create_cached_system_message()`

**Erwartete Auswirkung:**
- Cache-Read-Tokens zählen NICHT gegen ITPM Rate Limit
- ~80% Reduktion der effektiven Input-Tokens bei wiederholten Calls

---

### Session 6: Token-Optimierung DEC-020 (02.02.2026)

**Problem:** Telemetrie-Catalog (~10.000 Tokens) wurde bei jeder Anfrage komplett ins LLM-Context geladen. Bei 30k Tokens/Min Rate Limit führte das zu 429-Errors nach 2-3 Calls.

**Lösung:** Neues MCP-Tool `search_telemetry_keys` mit komprimiertem Lookup-Index.

| Metrik | Vorher | Nachher |
|--------|--------|--------|
| Tokens pro Key-Lookup | ~10.000 | ~200 |
| LLM-Calls bis Rate Limit | 2-3 | 10+ |
| Prompt `<semantic_catalog>` | ~600 Tokens | ~300 Tokens (`<key_lookup>`) |

**Evaluierte Alternativen:**
- Neo4j Graph-DB → Overkill für 54 Keys, als Ausblick notiert
- Embedding-Suche → Extra Dependency, nicht nötig bei 13 Gruppen
- Komprimierter JSON + Substring-Match → **Gewählt** (pragmatisch, sofort wirksam)

**Geänderte Dateien:**
- `config/telemetry_lookup.json` — **NEU** — Komprimierter Index (13 Gruppen, Aliases, Keys)
- `mcp_servers/thingsboard_server.py` — Neues Tool + Lookup-Funktionen
- `prompts/data_agent_prompt.py` — `<semantic_catalog>` → `<key_lookup>`
- `docs/DECISIONS.md` — DEC-020 dokumentiert

**Test-Ergebnis:**
```
✅ "Was sind die Drehmomente der letzten 30 min"
   → search_telemetry_keys(query=Drehmoment) → 1 Gruppe gefunden
   → get_telemetry(keys=torque_act_a1_nm,...) → 180 Punkte
✅ "Kannst du sie mir in einem Grafen anzeigen"
   → Supervisor plant nur viz_agent (kein erneuter Datenabruf)
   → Line Chart generiert
```

---

### Session 4: Viz Agent Erweiterung (AP3)

**Chart-Typen erweitert von 3 auf 10:**

| Kategorie | Charts | Status |
|-----------|--------|--------|
| Zeitreihen | Line, Area | ✅ |
| Vergleiche | Column, Bar | ✅ |
| Korrelationen | Scatter | ✅ |
| Statistik | Boxplot, Violin, Histogram | ✅ NEU |
| Anteile | Pie, Radar | ✅ NEU |

**Änderungen:**
- 7 neue Chart-Tools mit InjectedState (DEC-003)
- Transformations-Funktionen für jedes Datenformat
- Prompt aus `prompts/viz_agent_prompt.py` importiert (kein Inline-Prompt mehr)
- Tool-Descriptions mit "WANN BENUTZEN" (DEC-001)

**Test-Ergebnisse:**
```
✅ "Zeig mir den Verlauf" → Line Chart (19s cold, 5s warm)
✅ "Vergleiche die Achsen" → Column Chart
✅ "Zeig die Verteilung als Boxplot" → Boxplot
✅ "Erstelle ein Histogramm" → Histogram
✅ "Zeig alle Achsen im Radar-Chart" → Radar
```

**Geänderte Dateien:**
- `agents/viz_agent.py` - 7 neue Tools, Prompt-Import
- `prompts/viz_agent_prompt.py` - Synchronisiert, 10 Tools dokumentiert

---

### Session 3: Graph Best Practices (DEC-017)

**AP 2.3 - LangGraph Review:**

| Verbesserung | Beschreibung |
|--------------|--------------|
| `max_steps` Guard | Verhindert Endlosschleifen (default: 10) |
| `error_handler_node` | Graceful Failure bei Agent-Exceptions |
| State-Validierung | `respond_node` prüft auf fehlende Messages |
| DRY Routing | Eine Schleife statt 4x Copy-Paste |
| Agent Wrapper Factory | `make_agent_wrapper()` für Step-Increment |
| Thread-Safe Singleton | `_graph_lock` für Graph-Instanz |
| Strukturiertes Logging | `logger` statt `debug_print()` |
| Prompt ausgelagert | `prompts/respond_prompt.py` |

---

### Session 2: Production Code Quality (DEC-016)

**Alle Agents refactored:**

| Agent | Änderungen |
|-------|------------|
| `data_agent.py` | Logging, SRP, Retry, MCPToolsProvider |
| `viz_agent.py` | Logging, SRP, Retry, AntVSessionProvider |
| `stats_agent.py` | Logging, SRP, Retry mit Fallback |
| `supervisor.py` | Logging, Retry, validate_plan aufgeteilt |
| `utils.py` | **NEU** - Gemeinsame Hilfsfunktionen |

---

### Session 1: Prompt-Optimierung (DEC-015)

**Anthropic Best Practices angewendet:**
- XML-Tags für Struktur (`<role>`, `<task>`, `<instructions>`)
- Positive Anweisungen statt Verbote
- Redundanzen entfernt (~28% kürzer)

---

## 📋 Review-Status

| Komponente | Status | Letzte Änderung | Offen |
|------------|--------|-----------------|-------|
| ThingsBoard MCP | ✅ Fertig | AP1 | - |
| Data Agent | ✅ Fertig | DEC-016 | - |
| Viz Agent | ✅ Fertig | Session 4 | - |
| Stats Agent | ✅ Fertig | DEC-016 | - |
| Supervisor | ✅ Fertig | DEC-016 | - |
| Graph | ✅ Fertig | DEC-017 | - |
| Prompts | ✅ Fertig | DEC-015 | - |
| **CLAUDE.md** | ⚠️ Review | - | Siehe unten |

---

## 🔧 Offene Verbesserungen

### CLAUDE.md Refactoring (Prio: Hoch)

**Problem:** Aktuelle CLAUDE.md folgt nicht Best Practices:

| Best Practice | Aktuell | Soll |
|--------------|---------|------|
| Länge | ~200 Zeilen | ~60 Zeilen |
| Struktur | Gemischt | WHAT/WHY/HOW |
| Session-Log | Inline | → 04_AKTUELLER_STAND.md |
| Workflow | Narrativ | Nummerierte Schritte |

**Neuer Workflow (aus Best Practices Recherche):**

```
Session-Typ A: Review (KEIN Code)
1. AP-Komponenten identifizieren
2. DECISIONS.md lesen
3. Code analysieren (3 Perspektiven):
   - 🏗️ Senior Dev: Stabilität, Wartbarkeit
   - 🤖 KI-Experte: LLM-Umgang, Prompts, Tokens
   - 📋 DECs: Konsistenz mit Entscheidungen
4. Verbesserungen dokumentieren
5. User priorisiert für Phase B

Session-Typ B: Implementierung
1. Pro Änderung (max 50 Zeilen):
   - Ankündigen mit Vorher/Nachher
   - User bestätigt
   - Änderung machen
   - Testen
2. Am Ende: Dokumentation aktualisieren
```

### AP7: Agent-Intelligenz

**Siehe:** `docs/AP7_AGENT_INTELLIGENCE.md`

**Problem:** Bei Korrelations-Anfragen funktioniert die Agent-Pipeline nicht optimal:
- Data Agent lädt Daten doppelt (ignoriert State)
- Stats Agent nutzt Keyword-Mapping statt LLM-Intelligenz

**Lösung:** Agents treffen eigenständige Entscheidungen basierend auf LLM-Verständnis.

| AP | Beschreibung | Status |
|----|--------------|--------|
| AP7.1 | Data Agent State-Awareness | ✅ |
| AP7.2 | Data Agent Query-Interpretation | ⬜ |
| AP7.3 | Stats Agent Metadaten-Schema | ⬜ |
| AP7.4 | Stats Agent LLM-Tool-Selection | ⬜ |
| AP7.5 | Integration & Dokumentation | ⬜ |

**AP7.1 abgeschlossen (28.01.2026):**
- `format_existing_datasets_hint()` verbessert mit XML-Format und Statistik-Preview
- Multi-Turn Beispiele im Prompt statt hardcoded Instruktionen
- Designentscheidung: Beispiele skalieren besser als dedizierte Tools

---

### Kleinere offene Punkte

| Komponente | Issue | Prio |
|------------|-------|------|
| `viz_agent.py` | `extract_chart_url()` - Status-First fehlt (DEC-008) | 🟡 |
| Allgemein | ~~Rate Limiter einbauen~~ | ✅ DEC-020 |
| Allgemein | ~~Prompt Caching~~ | ✅ DEC-021 |
| Allgemein | Production Checkpointer (SQLite) | 🟢 |

---

## 🧠 Entscheidungs-Patterns (30 total)

| ID | Pattern | Anwenden bei | Status |
|----|---------|--------------|--------|
| DEC-001 | Tool-Descriptions | Alle Tools | ✅ |
| DEC-003 | InjectedState | Große Daten | ✅ |
| DEC-008 | Status-First | Response-Parsing | ✅ |
| DEC-013 | Multi-Turn Persistenz | Checkpointer | ✅ |
| DEC-015 | XML-Tag Prompts | Alle Prompts | ✅ |
| DEC-016 | Production Quality | Alle Agents | ✅ |
| DEC-017 | Graph Best Practices | LangGraph | ✅ |
| DEC-018 | API Key Rotation | Rate Limit Handling | ✅ |
| DEC-020 | Komprimierter Lookup | Telemetrie-Key-Auflösung | ✅ |
| DEC-021 | Prompt Caching | Alle Agents | ✅ |

**Vollständige Liste:** `docs/DECISIONS.md`

---

## ⚡ Befehle

```bash
cd ~/ma_ws/conversational-analytics
source venv/bin/activate
chainlit run app.py

# Tests
python -m pytest tests/ -m "not integration" -v  # Schnell
python -m pytest tests/ -m integration -v         # Mit ThingsBoard

# Viz Agent testen
python agents/viz_agent.py
```
