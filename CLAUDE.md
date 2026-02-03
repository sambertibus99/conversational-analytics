# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MCP-based LLM multi-agent system for natural language IIoT data analysis of KUKA KRC5 robots. Uses LangGraph for orchestration, Chainlit for the frontend, ThingsBoard MCP for data access, and AntV MCP for chart generation.

## Commands

```bash
# Run app
source venv/bin/activate && chainlit run app.py

# Tests
python -m pytest tests/ -m "not integration" -v   # Unit tests (fast)
python -m pytest tests/ -m integration -v          # Integration tests (needs ThingsBoard)
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

**Agent Routing:** Supervisor creates plan like `["data_agent", "viz_agent"]` or `["data_agent", "stats_agent"]`. Agents execute sequentially, sharing data via `AgentState`.

**State Flow (DEC-013):**
1. Agents write to `AgentState` (state.py) with reducers:
   - `datasets`: Dict keyed by type (e.g., `{"torque": {...}, "position": {...}}`) - **accumulates across turns**
   - `data_summary`: Short text for LLM context - **accumulates across turns**
   - `chart_url`, `statistics`: Per-turn outputs - **overwritten each turn**
2. Large data saved to `outputs/data/`, only metadata in state (DEC-004)
3. `respond_node` reads all state to generate final response

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

## Key Files

| File | Purpose |
|------|---------|
| `agents/graph.py` | LangGraph orchestration, routing, respond_node |
| `agents/state.py` | AgentState with reducers for datasets/summaries |
| `agents/data_agent.py` | Fetches data via ThingsBoard MCP |
| `agents/viz_agent.py` | Generates charts via AntV MCP (10 chart types) |
| `agents/stats_agent.py` | Statistical analysis with InjectedState (DEC-003/024) |
| `tools/stats_functions.py` | Pure Python stats functions incl. `merge_asof` correlation |
| `config/settings.py` | `APIKeyRotator`, `create_anthropic_client()`, `create_cached_system_message()` |
| `prompts/*.py` | System prompts with XML-tag structure |
| `mcp_servers/thingsboard_server.py` | MCP tools: data, lookup, attributes (DEC-020) |
| `config/telemetry_lookup.json` | Compressed lookup index for key resolution |

## Code Style

- Use `logger` (not print) for debugging
- Use `create_anthropic_client()` from settings.py for LLM clients
- Use `create_cached_system_message()` for system prompts (DEC-021)
- Prompts go in `prompts/` directory, imported into agents
- Mark integration tests with `@pytest.mark.integration`
- Use `cleanup_mcp_after_test` fixture for MCP tests
- MCP sessions are cached globally (warmup at startup, reused across requests)

## MCP Session Management

MCP servers (ThingsBoard, AntV) use global session caching (DEC-005):
- First request: ~15s (server startup + warmup)
- Subsequent requests: ~5s (session reused)
- Sessions stay open while app runs
- For testing: use `cleanup_mcp_after_test` fixture to reset between tests

## Before Making Changes

1. Read `docs/DECISIONS.md` for existing patterns (24 documented)
2. Check `docs/04_AKTUELLER_STAND.md` for current status and open items
