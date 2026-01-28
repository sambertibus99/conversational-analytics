# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MCP-based LLM multi-agent system for natural language IIoT data analysis of KUKA KRC5 robots. Uses LangGraph for orchestration, Chainlit for the frontend, ThingsBoard MCP for data access, and AntV MCP for chart generation.

## Commands

```bash
# Activate environment and run app
source venv/bin/activate
chainlit run app.py

# Tests
python -m pytest tests/ -m "not integration" -v   # Unit tests (fast, no external services)
python -m pytest tests/ -m integration -v          # Integration tests (needs ThingsBoard)
python -m pytest tests/test_data_agent.py::test_latest_telemetry -v  # Single test

# Test individual agents
python agents/viz_agent.py
python agents/graph.py
```

## Architecture

```
User Query → Chainlit (app.py) → LangGraph (graph.py)
                                       │
                    ┌──────────────────┼──────────────────┐
                    ↓                  ↓                  ↓
              Supervisor         Data Agent          Viz Agent
             (plans route)    (ThingsBoard MCP)    (AntV MCP)
                    │                  │                  │
                    └──────────────────┼──────────────────┘
                                       ↓
                                Stats Agent
                                       ↓
                              Respond Node → User
```

**Data Flow:**
1. `supervisor.py` analyzes query and creates execution plan (`["data_agent", "viz_agent"]`)
2. Agents execute in order, sharing state via `AgentState` (state.py)
3. Large data bypasses LLM: saved to `outputs/data/`, metadata/summary passed via state (DEC-003, DEC-004)
4. `respond_node` in graph.py generates final user response

**Key Patterns:**
- `InjectedState` for passing large datasets to tools without going through LLM prompts
- Checkpointer + custom reducers for multi-turn state persistence (DEC-013)
- API key rotation for rate limit handling (DEC-018)
- XML-tags in prompts for structure (DEC-015)

## Key Files

| File | Purpose |
|------|---------|
| `agents/graph.py` | LangGraph orchestration, routing logic, respond_node |
| `agents/state.py` | AgentState with reducers for datasets/summaries |
| `agents/data_agent.py` | Fetches data via ThingsBoard MCP |
| `agents/viz_agent.py` | Generates charts via AntV MCP (10 chart types) |
| `config/settings.py` | APIKeyRotator, create_anthropic_client() |
| `prompts/*.py` | System prompts with XML-tag structure |
| `mcp_servers/thingsboard_server.py` | 8 tools for ThingsBoard access |

## Decision Patterns

All patterns are documented in `docs/DECISIONS.md`. Key ones:

| DEC | Pattern | When to Apply |
|-----|---------|---------------|
| DEC-003 | InjectedState | Passing large data to tools |
| DEC-008 | Status-First Parsing | Always check `status` field first in tool responses |
| DEC-013 | Multi-Turn Persistence | Checkpointer + merge_datasets reducer |
| DEC-015 | XML-Tag Prompts | Use `<role>`, `<task>`, `<instructions>` in prompts |
| DEC-016 | Production Quality | Logging, SRP, retry with backoff |
| DEC-017 | Graph Safety | max_steps guard, error_handler node |
| DEC-018 | API Key Rotation | Use create_anthropic_client() not ChatAnthropic directly |

## Working in This Codebase

**Before making changes:**
1. Read `docs/DECISIONS.md` for existing patterns
2. Check `docs/04_AKTUELLER_STAND.md` for current status

**Code style:**
- Use `logger` (not print) for debugging
- Keep functions <50 lines (SRP)
- Use `create_anthropic_client()` from settings.py for LLM clients
- Prompts go in `prompts/` directory, imported into agents

**Testing:**
- Mark integration tests with `@pytest.mark.integration`
- Use `cleanup_mcp_after_test` fixture for MCP tests (see tests/conftest.py)
- Gracefully skip on rate limits (DEC-012)
