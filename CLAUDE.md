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
                       Supervisor      │
                      (plans route)    │
                           │           │
         ┌─────────────────┼───────────┼──────────────┐
         ▼                 ▼           │              ▼
    Data Agent         Viz Agent ◄────┘         Stats Agent
  (ThingsBoard MCP)   (AntV MCP)           (InjectedState tools)
         │                 │                       │
         └────────────────►│◄──────────────────────┘
                           ▼
                     Respond Node → User
```

**Agent Routing:** Supervisor creates plan like `["data_agent", "viz_agent"]` or `["data_agent", "stats_agent"]`. Agents execute sequentially, sharing data via `AgentState`. Supervisor also sets `data_retrieval_mode`: `"raw"` for stats/correlation queries, `"aggregated"` for visualization (DEC-023).

**Multi-Turn Persistence (DEC-013):** `app.py` generates a UUID `thread_id` per chat session and passes it as `config={"configurable": {"thread_id": ...}}` to `graph.ainvoke()`. The `InMemorySaver` checkpointer keeps `datasets` and `data_summary` across turns via custom reducers (`merge_datasets`, `merge_summaries`).

**State Flow (DEC-013):**
1. Agents write to `AgentState` (state.py) with reducers:
   - `datasets`: Dict keyed by type (e.g., `{"torque": {...}, "position": {...}}`) - **accumulates across turns**
   - `data_summary`: Short text for LLM context - **accumulates across turns**
   - `chart_url`, `statistics`: Per-turn outputs - **overwritten each turn**
2. Large data saved to `outputs/data/`, only metadata in state (DEC-004)
3. `respond_node` reads all state to generate final response

**MCP Sessions:** ThingsBoard and AntV MCP servers use global session caching (DEC-005). Sessions stay open while the app runs. For testing, use the `cleanup_mcp_after_test` fixture to reset between tests.

## Key Patterns

All 24 patterns documented in `docs/DECISIONS.md`. Critical ones for daily work:

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

**Gotcha (DEC-021):** LangChain does NOT propagate `additional_kwargs={"cache_control": ...}` to the Anthropic API. Format `content` as `list[dict]` with `cache_control` in the content block instead. See `create_cached_system_message()` in `config/settings.py`.

## Key Files

| File | Purpose |
|------|---------|
| `app.py` | Chainlit entry point, thread-ID management, MCP warmup |
| `agents/graph.py` | LangGraph orchestration, routing, respond_node, error_handler |
| `agents/state.py` | AgentState with reducers for datasets/summaries |
| `agents/supervisor.py` | Query analysis, plan creation, data_retrieval_mode selection |
| `agents/data_agent.py` | Fetches data via ThingsBoard MCP |
| `agents/viz_agent.py` | Generates charts via AntV MCP (10 chart types) |
| `agents/stats_agent.py` | Statistical analysis with InjectedState (DEC-003/024) |
| `agents/utils.py` | Shared helpers: `extract_data_from_datasets`, dataset hints |
| `tools/stats_functions.py` | Pure Python stats functions incl. `merge_asof` correlation |
| `config/settings.py` | `APIKeyRotator`, `create_anthropic_client()`, `create_cached_system_message()` |
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

## Before Making Changes

1. Read `docs/DECISIONS.md` for existing patterns (24 documented)
2. Check `docs/04_AKTUELLER_STAND.md` for current status and open items
