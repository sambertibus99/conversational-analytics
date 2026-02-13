# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MCP-based LLM multi-agent system for natural language IIoT data analysis of KUKA KRC5 robots. Uses LangGraph for orchestration, Chainlit for the frontend, ThingsBoard MCP for data access, and AntV MCP for chart generation. Python 3.12, dependencies in `requirements.txt`.

Documentation and code comments are in German. User-facing interactions are in German.

## Commands

```bash
# Run app
source venv/bin/activate && chainlit run app.py

# Tests (prefer run_tests.py if ROS2 is installed — removes ROS path conflicts)
python run_tests.py                              # Unit tests (default)
python run_tests.py --integration                # All tests incl. integration
python run_tests.py --coverage                   # With coverage report
python -m pytest tests/ -m "not integration" -v  # Unit tests (direct pytest)
python -m pytest tests/ -m integration -v        # Integration tests (needs ThingsBoard)
python -m pytest tests/test_data_agent.py::test_latest_telemetry -v  # Single test

# Test individual agents (standalone mode)
python agents/viz_agent.py
python agents/graph.py

# Git (uses SSH)
git push origin master
```

## Environment Setup

```env
# .env file - copy from .env.example
ANTHROPIC_API_KEYS=sk-key1,sk-key2,sk-key3  # Multiple keys for rotation (DEC-018)
THINGSBOARD_URL=http://localhost:8080
THINGSBOARD_USERNAME=tenant@thingsboard.org
THINGSBOARD_PASSWORD=tenant
KRC5_DEVICE_ID=<device-uuid>
```

## Architecture

```
User → Chainlit (app.py) → LangGraph (graph.py)
                                 │
                           ┌─────┴─────┐
                           ▼           │
                   ┌→ Supervisor       │
                   │  (plans route)    │
                   │       │           │
                   │  ┌────┼───────────┼──────────────┐
                   │  ▼    ▼           │              ▼
                   │ Data Agent    Viz Agent ◄────┘  Stats Agent
                   │ (TB MCP)     (AntV MCP)     (InjectedState)
                   │  │               │                │
                   │  └──────────────►│◄───────────────┘
                   │                  ▼
                   │            get_next_agent
                   │              │         │
                   │   pending_goals?    no goals
                   │              │         │
                   │       replan_bridge    ▼
                   │          │        Respond Node → User
                   └──────────┘
```

**Agent Routing:** Supervisor creates plan like `["data_agent", "viz_agent"]` or `["data_agent", "stats_agent"]`. Agents execute sequentially, sharing data via `AgentState`. Supervisor sets `data_retrieval_mode`: `"raw"` for stats/correlation queries, `"aggregated"` for visualization (DEC-023). Data Agent always runs when viz/stats are planned (DEC-028). For multi-goal queries, `replan_bridge` routes back to Supervisor with a snapshot of phase results (DEC-032, max 2 replans).

**Multi-Turn Persistence (DEC-013):** `app.py` generates a UUID `thread_id` per chat session and passes it as `config={"configurable": {"thread_id": ...}}` to `graph.ainvoke()`. The `InMemorySaver` checkpointer keeps `turn_history` across turns via the `append_turn_history` reducer. DatasetMeta is persisted exclusively in DuckDB (DEC-031).

**State Flow (DEC-013, DEC-025, DEC-031):**
1. Agents write to `AgentState` (state.py) with reducers:
   - `turn_history`: Structured turn summaries for supervisor context - **accumulates across turns**
   - `chart_url`, `statistics`: Per-turn outputs - **overwritten each turn**
   - `session_id`: DuckDB SessionStore ID (set by app.py, matches thread_id)
   - `pending_goals`, `replan_count`, `replan_context`: Replan-Loop state (DEC-032) - **per-turn**
2. Raw data + DatasetMeta stored in DuckDB `SessionStore` (in-memory, per session) — DuckDB is sole source of truth (DEC-031)
3. Stats/Viz agents read data via `get_data_from_state()` helper (DuckDB only)
4. `respond_node` reads `DatasetMeta` from DuckDB via `get_dataset_meta_from_duckdb()` to generate final response

**MCP Sessions:** ThingsBoard and AntV MCP servers use global session caching (DEC-005). Sessions stay open while the app runs. For testing, use the `cleanup_mcp_after_test` fixture to reset between tests.

## Key Patterns

All 30 patterns documented in `docs/DECISIONS.md`. Critical ones for daily work:

| Pattern | What | When |
|---------|------|------|
| InjectedState (DEC-003) | Pass data via state, not prompt | Viz/Stats agent tools |
| File-Storage (DEC-004) | Raw data → file, summary → LLM | Large data responses |
| MCP Warmup (DEC-005) | Global session + startup warmup | MCP server initialization |
| Status-First (DEC-008) | Check `status` field first | All tool response parsing |
| XML-Tag Prompts (DEC-015) | `<role>`, `<task>`, `<instructions>` | All agent prompts |
| API Key Rotation (DEC-018) | Use `create_anthropic_client()` | All LLM clients |
| Telemetry Lookup (DEC-020) | `search_telemetry_keys` tool | Key resolution |
| Prompt Caching (DEC-021) | Use `create_cached_system_message()` | All system prompts |
| Dynamic Few-Shot Dates (DEC-022) | Generate example dates dynamically | Prompts with date examples |
| Query-Type Data Mode (DEC-023) | `raw` for stats, `aggregated` for viz | Correlation/statistics queries |
| Timeseries Correlation (DEC-024) | `pd.merge_asof` for timestamp alignment | IoT sensor correlation |
| DuckDB Reference State (DEC-025) | Raw data in DuckDB, only `DatasetMeta` in State | All data storage/retrieval |
| Data Agent Gatekeeper (DEC-028) | Data Agent always runs, sets `active_dataset_keys` | All turns with viz/stats agents |
| Stats DuckDB Persistence (DEC-030) | Stats in DuckDB `statistics` table, `active_stats_keys` for Viz | Stats-to-Viz multi-turn flow |
| DuckDB Single SoT (DEC-031) | DatasetMeta only in DuckDB, no `state["datasets"]` | All DatasetMeta access |
| Supervisor Replan-Loop (DEC-032) | `replan_bridge` + `pending_goals`, max 2 replans | Multi-goal queries |
| Reasoning-based EVAL (DEC-033) | Agent capabilities + data flows instead of rules | Supervisor EVAL prompt, agent orchestration |

**Gotcha (DEC-021):** LangChain does NOT propagate `additional_kwargs={"cache_control": ...}` to the Anthropic API. Format `content` as `list[dict]` with `cache_control` in the content block instead. See `create_cached_system_message()` in `config/settings.py`.

**Gotcha (DEC-025/031):** When accessing data in tools/agents, always use `get_data_from_state(state)` from `agents/utils.py`. For DatasetMeta, use `get_dataset_meta_from_duckdb(session_id)` from `agents/utils.py`. There is no `state["datasets"]` — DuckDB is the sole source of truth (DEC-031). The `state` dict must contain `session_id` for DuckDB lookups.

## Key Files

| File | Purpose |
|------|---------|
| `app.py` | Chainlit entry point, thread-ID management, MCP warmup |
| `agents/graph.py` | LangGraph orchestration, routing, respond_node, replan_bridge, error_handler |
| `agents/state.py` | AgentState with turn_history reducer, DatasetMeta TypedDict |
| `agents/supervisor.py` | Query analysis, plan creation, data_retrieval_mode selection, replan context |
| `agents/data_agent.py` | Fetches data via ThingsBoard MCP |
| `agents/viz_agent.py` | Generates charts via AntV MCP (10 chart types) |
| `agents/stats_agent.py` | Statistical analysis with InjectedState (DEC-003/024) |
| `agents/utils.py` | Shared helpers: `get_data_from_state`, `get_dataset_meta_from_duckdb`, dataset hints |
| `tools/stats_functions.py` | Pure Python stats functions incl. `merge_asof` correlation |
| `config/settings.py` | `APIKeyRotator`, `create_anthropic_client()`, `create_cached_system_message()` |
| `config/duckdb_store.py` | `SessionStore` (DuckDB), `generate_dataset_key()`, UNS-Keys, `dataset_meta` + `statistics` tables (DEC-025/031) |
| `prompts/*.py` | System prompts with XML-tag structure (DEC-015) |
| `mcp_servers/thingsboard_server.py` | MCP tools: data, lookup, attributes (DEC-020) |
| `mcp_servers/thingsboard_client.py` | Async HTTP client with retry, custom exceptions (DEC-009) |
| `config/telemetry_lookup.json` | Compressed lookup index for key resolution |
| `tests/conftest.py` | Test fixtures: `cleanup_mcp_after_test`, session event loop |
| `evaluation/run_evaluation.py` | Benchmark runner against `test_queries.py` |

## Code Style

- Use `logger` (not print) for debugging
- Prompts go in `prompts/` directory as functions (support dynamic content like DEC-022 dates), imported into agents
- Mark integration tests with `@pytest.mark.integration`
- Async tests: `asyncio_mode = auto` in pytest.ini, no `@pytest.mark.asyncio` needed
- Custom exception hierarchy in `mcp_servers/thingsboard_client.py`: `ThingsBoardError` → `AuthError`, `ConnectionError`, `RateLimitError`, `NotFoundError`

## Claude Code Workflow

### Subagents (`.claude/agents/`)

| Agent | Modell | Wann aufrufen |
|-------|--------|---------------|
| `decisions` | sonnet | Architektonische Änderungen, neue Agents/Prompts, Datenfluss-Änderungen, neue Patterns |
| `prompt-engineer` | sonnet | Prompts erstellen, ändern oder erweitern (kennt DEC-015, DEC-022) |
| `pattern-reviewer` | haiku | Nach Code-Änderungen: prüft Code gegen alle 29 DEC-Patterns (read-only) |
| `test-runner` | haiku | Nach Code-Änderungen: Tests ausführen und Ergebnisse zusammenfassen |
| `e2e-tester` | sonnet | E2E-Tests: Startet Chainlit-App, testet via Playwright-Browser gegen test_queries.py |

**Empfohlener Workflow nach Code-Änderungen:**
1. `test-runner` — Tests ausführen
2. `pattern-reviewer` — DEC-Compliance prüfen

**Empfohlener Workflow bei neuen Features:**
1. `decisions` — Relevante DECs und Architektur-Empfehlung holen
2. Implementieren
3. `prompt-engineer` — Falls Prompts betroffen
4. `test-runner` + `pattern-reviewer` — Validierung

### Slash Commands (`.claude/commands/`)

| Command | Zweck |
|---------|-------|
| `/test-agent <name>` | Tests ausführen (`data`, `viz`, `stats`, `graph`, `all`, `integration`, `coverage`) |
| `/new-decision` | Neue DEC in `docs/DECISIONS.md` dokumentieren |
| `/update-status` | Session-Eintrag in `docs/04_AKTUELLER_STAND.md` hinzufügen |
| `/e2e-test <arg>` | E2E-Tests via Playwright (`einfach`, `mittel`, `komplex`, `abstention`, `all`, `E1`...) |
| `/session-save` | Session-Kontext sichern für Wiederaufnahme (vor Kompaktierung/Sessionwechsel) |
| `/session-resume [thema]` | Gespeicherten Session-Kontext laden und Arbeit fortsetzen |
| `/plan-prepare [name]` | Plan aus Kontext in sessionbasierte Phasen umstrukturieren (nach Plan Mode) |
| `/plan <name> <phase>` | Eine Phase eines Plans laden und ausführen (z.B. `/plan refactor 3`) |

**Multi-Session Plan-Workflow:**
1. Plan erstellen (normal mit Claude / Plan Mode)
2. `/plan-prepare` — Plan in Phasen aufteilen, Vorab-Entscheidungen + Akzeptanzkriterien definieren, Context7-Validierung
3. `/clear` → `/plan <name> 1` → Phase 1 abarbeiten → `/clear` → `/plan <name> 2` → ...
- Pläne werden in `.claude/plans/` gespeichert
- Jede Phase schreibt ein Handoff für die Folge-Session
- Agent fragt bei JEDER nicht vorab geklärten Entscheidung (keine Eigenmächtigkeit)
- Context7 Pre-Check pro Phase fängt veraltete Vorab-Entscheidungen ab

### MCP-Server

| Server | Transport | Zweck |
|--------|-----------|-------|
| `context7` | HTTP | Aktuelle Bibliotheks-Dokumentation (LangGraph, Chainlit, MCP etc.) |
| `playwright` | stdio | Browser-Automatisierung für E2E-Tests (Playwright MCP) |

### Post-Edit Hook

Edits an `prompts/*.py` werden automatisch auf DEC-015 XML-Tag-Struktur validiert (Pflicht: `<role>`, `<task>`).

## Before Making Changes

1. Read `docs/DECISIONS.md` for existing patterns (29 documented)
2. Check `docs/04_AKTUELLER_STAND.md` for current status and open items
