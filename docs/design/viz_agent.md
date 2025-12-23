# Viz Agent - Design-Entscheidungen

> **Arbeitspaket:** AP4
> **Datei:** `agents/viz_agent.py`
> **Status:** 🔄 Review läuft (3/4 Aspekte abgeschlossen)

---

## Aspekt-Übersicht

| # | Aspekt | Kernfrage | Status |
|---|--------|-----------|--------|
| 1 | Daten-Übergabe | Wie kommen Daten ans Tool ohne LLM-Prompt? | ✅ |
| 2 | Tool-Auswahl | Soll LLM oder Regeln den Chart-Typ wählen? | ✅ |
| 3 | MCP-Aufruf | Wie rufen wir AntV MCP Tools auf? | ✅ |
| 4 | Error Handling | Was wenn Chart-Generierung fehlschlägt? | ⬜ |

---

## Aspekt 1: Daten-Übergabe ✅

### Kernfrage
Die Daten (z.B. 72.000 Datenpunkte) dürfen nicht durch den LLM-Prompt gehen (zu langsam, zu teuer), aber das Tool braucht sie.

### Recherche

| Quelle | Typ | Erkenntnis |
|--------|-----|------------|
| [dragonforest.in/injectedstate-in-langgraph](https://dragonforest.in/injectedstate-in-langgraph/) | Blog | InjectedState versteckt Parameter vor LLM-Schema |
| [GitHub Issue #3564](https://github.com/langchain-ai/langgraph/issues/3564) | GitHub | State-Injection funktioniert nicht mit ToolNode in manchen Fällen |
| [Medium: Handling State in LangGraph](https://medium.com/@rhrafistudent/handling-state-in-langgraph-tool-calls-avoiding-auto-generated-parameters-90acc117f423) | Blog | Annotated[dict, InjectedState] ist die Lösung |

### Optionen

| Option | Beschreibung | Pro | Contra |
|--------|--------------|-----|--------|
| A: Daten im Prompt | Daten als JSON in System-Prompt packen | Einfach | ~100s Latenz, Token-Limit, teuer |
| B: InjectedState | `state: Annotated[dict, InjectedState]` | Best Practice, schnell | Etwas komplexer |
| C: Direkter Tool-Call | Kein LLM, Tool direkt aufrufen | Sehr schnell | Keine flexible Tool-Auswahl |
| D: Hybrid B+C | LLM wählt Tool, Daten via InjectedState | Flexibel + schnell | Komplexität |

### Entscheidung: Option D (Hybrid)

### Begründung
- LLM kann intelligent zwischen Line/Column/Scatter wählen
- Daten gehen nicht durch LLM-Prompt
- Performance: ~100s → ~5s
- LangGraph Best Practice

### Implementation

```python
@tool
async def generate_line_chart_tool(
    title: str,  # ← LLM sieht nur das
    state: Annotated[dict, InjectedState],  # ← LLM sieht NICHT, wird injiziert
) -> str:
    data = state.get("data", {})  # ← Daten aus State
    # ... Chart generieren
```

---

## Aspekt 2: Tool-Auswahl ✅

### Kernfrage
Soll ein LLM oder einfache Regeln entscheiden, welcher Chart-Typ (Line/Column/Scatter) verwendet wird?

### Recherche

| Quelle | Typ | Erkenntnis |
|--------|-----|------------|
| Eigene Überlegung | - | Regeln sind schneller, aber weniger flexibel |
| LangChain Docs | Docs | bind_tools() für Tool-Auswahl durch LLM |

### Optionen

| Option | Beschreibung | Pro | Contra |
|--------|--------------|-----|--------|
| A: Regeln | `if "vergleich" in query → column` | Schnell, vorhersagbar | Nicht flexibel |
| B: LLM | LLM wählt basierend auf Query | Flexibel, natürlicher | LLM-Call nötig |

### Entscheidung: Option B (LLM)

### Begründung
- User kann natürlich formulieren ("Korrelation", "Vergleich", etc.)
- LLM-Call ist schnell wenn keine Daten im Prompt
- Mehr Flexibilität für Zukunft

### Implementation

```python
llm_with_tools = llm.bind_tools(CHART_TOOLS)
response = await llm_with_tools.ainvoke(messages)
tool_call = response.tool_calls[0]  # LLM hat gewählt
```

---

## Aspekt 3: MCP-Aufruf ✅

### Kernfrage
Wie rufen wir die AntV MCP Tools auf? Via LangChain Adapter oder direkt?

### Recherche

| Quelle | Typ | Erkenntnis |
|--------|-----|------------|
| MCP SDK Docs | Docs | `session.call_tool()` für direkten Aufruf |
| langchain-mcp-adapters | Code | Wrapper für LangChain-Kompatibilität |

### Optionen

| Option | Beschreibung | Pro | Contra |
|--------|--------------|-----|--------|
| A: LangChain Adapter | `load_mcp_tools()` + Agent | Integriert | Langsam, Daten durch LLM |
| B: Direkter Aufruf | `session.call_tool()` | Schnell, Kontrolle | Mehr Code |

### Entscheidung: Option B (Direkt)

### Begründung
- Daten müssen direkt ans Tool (nicht durch LLM)
- Mehr Kontrolle über Parameter
- Performance

### Implementation

```python
session = await get_antv_session()
result = await session.call_tool(
    "generate_line_chart",
    arguments={
        "data": transformed_data,  # Direkt, nicht durch LLM!
        "title": title,
        ...
    }
)
```

---

## Aspekt 4: Error Handling ⬜

### Kernfrage
Was passiert wenn die Chart-Generierung fehlschlägt? (MCP Server nicht erreichbar, ungültige Daten, etc.)

### Recherche
*Noch nicht durchgeführt*

### Such-Queries für Recherche
- `LangGraph tool error handling best practice`
- `MCP server error retry python`
- `LangChain tool failure recovery`

---

## Änderungshistorie

| Datum | Aspekt | Änderung |
|-------|--------|----------|
| 19.12.2025 | 1-3 | Initiale Recherche und Implementation |
| 19.12.2025 | 4 | Als offen markiert |
