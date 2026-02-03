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

# Test individual agents
python agents/viz_agent.py
python agents/graph.py
```

## Architecture

```
User → Chainlit (app.py) → LangGraph (graph.py)
                                 │
              ┌──────────────────┼──────────────────┐
              ↓                  ↓                  ↓
        Supervisor         Data Agent          Viz Agent
       (plans route)    (ThingsBoard MCP)    (AntV MCP)
                                 │
                           Stats Agent
                                 ↓
                          Respond Node → User
```

**Data Flow:**
1. `supervisor.py` creates execution plan (`["data_agent", "viz_agent"]`)
2. Agents share state via `AgentState` (state.py) with custom reducers
3. Large data bypasses LLM: saved to `outputs/data/`, metadata passed via state
4. `respond_node` in graph.py generates final user response

## Key Patterns

All patterns documented in `docs/DECISIONS.md`. Critical ones:

| Pattern | What | When |
|---------|------|------|
| InjectedState (DEC-003) | Pass data via state, not prompt | Viz/Stats agent tools |
| Status-First (DEC-008) | Check `status` field first | All tool response parsing |
| XML-Tag Prompts (DEC-015) | `<role>`, `<task>`, `<instructions>` | All agent prompts |
| API Key Rotation (DEC-018) | Use `create_anthropic_client()` | All LLM clients |
| Telemetry Lookup (DEC-020) | `search_telemetry_keys` tool | Key resolution |
| Prompt Caching (DEC-021) | `cache_control` on system prompts | All LLM calls (planned) |

## Key Files

| File | Purpose |
|------|---------|
| `agents/graph.py` | LangGraph orchestration, routing, respond_node |
| `agents/state.py` | AgentState with reducers for datasets/summaries |
| `agents/data_agent.py` | Fetches data via ThingsBoard MCP |
| `agents/viz_agent.py` | Generates charts via AntV MCP (10 chart types) |
| `config/settings.py` | APIKeyRotator, create_anthropic_client() |
| `prompts/*.py` | System prompts with XML-tag structure |
| `mcp_servers/thingsboard_server.py` | 9 MCP tools (data, lookup, attributes) |
| `config/telemetry_lookup.json` | Compressed lookup index for key resolution |

## Code Style

- Use `logger` (not print) for debugging
- Use `create_anthropic_client()` from settings.py for LLM clients
- Prompts go in `prompts/` directory, imported into agents
- Mark integration tests with `@pytest.mark.integration`
- Use `cleanup_mcp_after_test` fixture for MCP tests

## Before Making Changes

1. Read `docs/DECISIONS.md` for existing patterns
2. Check `docs/04_AKTUELLER_STAND.md` for current status and open items
