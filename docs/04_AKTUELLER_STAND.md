# AKTUELLER STAND

> **Letzte Aktualisierung:** 03. Februar 2026 (DEC-021 Prompt Caching)

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

## 🧠 Entscheidungs-Patterns (21 total)

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
