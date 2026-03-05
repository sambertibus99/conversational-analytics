"""
Supervisor Agent für die Planung von Agent-Ausführungen.

Der Supervisor analysiert User-Anfragen und erstellt einen Plan,
welche Agents in welcher Reihenfolge ausgeführt werden sollen.

Er führt selbst KEINE Aktionen aus – er plant nur!

DESIGN-ENTSCHEIDUNGEN:
- DEC-013: Multi-Turn Support (berücksichtigt vorhandene Datasets)
- DEC-016: Strukturiertes Logging
- DEC-023: Query-Typ-basierte Datenstrategie (detail vs overview)
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import json
import asyncio
import logging
import re
from datetime import datetime
from typing import Any, Literal, Tuple, Optional

from pydantic import BaseModel, Field

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from agents.state import AgentState
from agents.utils import extract_user_query, describe_active_data
from prompts.supervisor_prompt import get_supervisor_prompt, get_supervisor_eval_prompt
from config.settings import DEFAULT_MODEL, api_key_rotator, create_anthropic_client, create_cached_system_message


# =============================================================================
# LOGGING KONFIGURATION (DEC-016)
# =============================================================================

logger = logging.getLogger(__name__)

# Retry-Konfiguration
MAX_RETRIES = 3
RETRY_DELAY_BASE = 2

# Gültige Agents
VALID_AGENTS = {"data_agent", "stats_agent", "viz_agent"}

# Debug-Logging für Supervisor-Prompts
SUPERVISOR_DEBUG_LOG = PROJECT_ROOT / "logs" / "supervisor_debug.log"
_supervisor_call_counter = 0


def _log_supervisor_call(
    mode: str,
    system_prompt: str,
    user_message: str,
    response: str,
    state_snapshot: dict | None = None,
    result: dict | None = None,
) -> None:
    """Schreibt den vollständigen Supervisor-Aufruf in eine Debug-Datei.

    Args:
        mode: "PLAN" oder "EVAL"
        system_prompt: Der komplette System-Prompt
        user_message: Die User-/Kontext-Nachricht
        response: Die LLM-Antwort (roh)
        state_snapshot: Relevante State-Felder
        result: Das geparste/verarbeitete Ergebnis
    """
    global _supervisor_call_counter
    _supervisor_call_counter += 1

    SUPERVISOR_DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep = "=" * 80

    lines = [
        "",
        sep,
        f"  SUPERVISOR CALL #{_supervisor_call_counter}  |  {mode}  |  {timestamp}",
        sep,
        "",
        "--- SYSTEM PROMPT ---",
        system_prompt,
        "",
        "--- USER MESSAGE ---",
        user_message,
        "",
        "--- LLM RESPONSE ---",
        response,
        "",
    ]

    if state_snapshot:
        lines.append("--- STATE SNAPSHOT ---")
        for key, value in state_snapshot.items():
            lines.append(f"  {key}: {value}")
        lines.append("")

    if result:
        lines.append("--- PARSED RESULT ---")
        for key, value in result.items():
            lines.append(f"  {key}: {value}")
        lines.append("")

    lines.append(sep)
    lines.append("")

    with open(SUPERVISOR_DEBUG_LOG, "a", encoding="utf-8") as f:
        f.write("\n".join(lines))


class EvalDecision(BaseModel):
    """Strukturierte Entscheidung des Supervisor-LLM nach Agent-Ausführung (DEC-032)."""
    action: Literal["continue", "replan", "respond"] = Field(
        description="'continue' = nächster Agent ausführen. "
                    "'replan' = Plan anpassen (Datenkonflikt etc.). "
                    "'respond' = alle Ziele erfüllt, direkt zur Antwort."
    )
    reasoning: str = Field(description="Kurze Begründung (1 Satz).")
    pending_goals: list[str] | None = Field(
        default=None,
        description="Nur bei action='replan': Offene Ziele für die nächste Phase."
    )
    viz_data_source: Literal["timeseries", "stats"] | None = Field(
        default=None,
        description="Nur setzen wenn viz_agent der nächste Schritt ist. "
                    "'timeseries' = Zeitreihen-Chart, 'stats' = Stats-Aggregate-Chart."
    )


# =============================================================================
# HILFSFUNKTIONEN
# =============================================================================

SUPERVISOR_MODEL = "claude-opus-4-20250514"  # DEC-029: Opus für besseres Reasoning


def _build_replan_context(replan_context: dict) -> str:
    """Baut Kontext-String aus dem Replan-Snapshot für den Supervisor (DEC-032).

    Wird an den enhanced_prompt angehängt wenn replan_count > 0.
    """
    parts = [f"\n## REPLAN (Phase {replan_context.get('phase', '?')})"]
    if replan_context.get("plan"):
        parts.append(f"Vorheriger Plan: {replan_context['plan']}")
    if replan_context.get("active_dataset_keys"):
        parts.append(f"Geladene Daten: {', '.join(replan_context['active_dataset_keys'])}")
    if replan_context.get("statistics_summary"):
        parts.append(f"Statistik: {replan_context['statistics_summary']}")
    if replan_context.get("data_retrieval_mode"):
        parts.append(f"Daten-Modus: {replan_context['data_retrieval_mode']}")
    if replan_context.get("agent_signals"):
        parts.append("Agent-Signale:")
        for s in replan_context["agent_signals"]:
            parts.append(f"  [{s.get('type', '?').upper()}] {s.get('code', '?')}: {s.get('message', '')}")
            if s.get("suggestion"):
                parts.append(f"    → {s['suggestion']}")
    return "\n".join(parts)


def _is_eval_mode(state: dict) -> bool:
    """Prüft ob der Supervisor im EVAL-Modus laufen soll (DEC-032).

    EVAL: Plan existiert, mindestens ein Agent hat bereits ausgeführt (step > 0),
          und wir sind NICHT in einer Replan-Phase.
    PLAN: Alle anderen Fälle (erster Aufruf, Replan, leerer Plan).
    """
    plan = state.get("plan")
    if plan is None or plan == []:
        return False
    if state.get("replan_context") is not None:
        return False
    if state.get("current_step", 0) > 0:
        return True
    return False


def _get_per_turn_reset(replan_mode: bool = False) -> dict:
    """Gibt alle per-turn Reset-Felder als Dict zurück.

    Wird in run_supervisor() per **_get_per_turn_reset() gespreizt,
    sodass spezifische Werte danach überschreiben können.

    Args:
        replan_mode: Bei True wird replan_count NICHT resettet (bleibt im
                     State erhalten für das Max-2-Limit). replan_context wird
                     IMMER resettet, da der Supervisor ihn beim Replan-PLAN
                     bereits verbraucht hat. statistics/statistics_summary
                     werden bei Replan bewahrt (Ergebnisse aus Phase 1 für respond).
                     active_dataset_keys wird IMMER resettet —
                     der Supervisor muss data_agent im Replan-Plan einplanen.
                     active_stats_keys bleibt erhalten (Stats Agent überschreibt wenn er läuft).
    """
    reset = {
        "active_dataset_keys": None,
        # active_stats_keys wird NICHT resettet — bleibt vom vorherigen Turn erhalten
        # (analog zu DEC-028: Stats Agent überschreibt wenn er läuft, sonst bleibt der Wert)
        "chart_url": None,
        "chart_type": None,
        "error": None,
        "error_count": 0,
        "needs_user_input": False,
        "user_input_reason": None,
        "viz_data_source": "auto",  # Viz-Datenquelle pro Turn zurücksetzen
        "stats_findings": None,     # DEC-034: Pro Turn überschrieben
        "agent_signals": None,      # Agent-Signale pro Turn zurücksetzen
        "pending_goals": None,      # Neu für Phase 6 (Replan-Loop)
        "replan_context": None,     # Immer zurücksetzen (nach Verbrauch durch Supervisor)
    }
    if not replan_mode:
        reset["replan_count"] = 0
        reset["statistics"] = None
        reset["statistics_summary"] = None
    return reset


def create_supervisor_llm():
    """Erstellt das LLM für den Supervisor mit aktuellem API Key (DEC-018, DEC-029: Opus)."""
    return create_anthropic_client(model=SUPERVISOR_MODEL)


def parse_supervisor_response(response: str) -> dict[str, Any]:
    """
    Parst die Supervisor-Antwort zu einem Plan-Dict.

    Erwartet JSON: {"plan": [...], "reasoning": "...", "data_mode": "..."}
    Ist robust gegen Markdown-Codeblöcke.
    """
    if not response:
        return {"plan": [], "reasoning": "Keine Antwort vom Supervisor", "data_mode": "overview"}

    cleaned = response.strip()

    # Markdown Codeblöcke entfernen
    if "```" in cleaned:
        match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', cleaned, re.DOTALL)
        if match:
            cleaned = match.group(1)
        else:
            cleaned = re.sub(r'```(?:json)?', '', cleaned).strip()

    try:
        result = json.loads(cleaned)

        if not isinstance(result, dict):
            return {"plan": [], "reasoning": f"Ungültiges Format: {type(result)}", "data_mode": "overview"}

        if "plan" not in result:
            return {"plan": [], "reasoning": "Kein 'plan' Feld in Antwort", "data_mode": "overview"}

        if not isinstance(result["plan"], list):
            return {"plan": [], "reasoning": f"'plan' ist keine Liste: {type(result['plan'])}", "data_mode": "overview"}

        # Validiere Agent-Namen
        for agent in result["plan"]:
            if agent not in VALID_AGENTS:
                logger.warning(f"Unbekannter Agent '{agent}' im Plan")

        # DEC-023: Data Mode validieren
        data_mode = result.get("data_mode", "overview")
        if data_mode not in ("detail", "overview"):
            logger.warning(f"Ungültiger data_mode '{data_mode}', verwende 'overview'")
            data_mode = "overview"

        return {
            "plan": result["plan"],
            "reasoning": result.get("reasoning", "Keine Begründung"),
            "data_mode": data_mode,
            "data_instructions": result.get("data_instructions"),
            "viz_instructions": result.get("viz_instructions"),
            "viz_data_source": result.get("viz_data_source", "auto"),
            "stats_instructions": result.get("stats_instructions"),
            "needs_user_input": result.get("needs_user_input", False),
            "user_input_reason": result.get("user_input_reason"),
            "pending_goals": result.get("pending_goals"),  # DEC-032: Replan-Loop
        }

    except json.JSONDecodeError as e:
        logger.warning(f"JSON Parse Error: {e}")
        logger.debug(f"Response war: {cleaned[:200]}")
        return {"plan": [], "reasoning": f"JSON Parse Error: {str(e)}", "data_mode": "overview"}


def validate_plan(
    plan: list[str],
    has_datasets: bool = False,  # Deprecated: DEC-031 — nicht mehr verwendet, bleibt für Test-Kompatibilität
) -> Tuple[bool, str, list[str]]:
    """
    Validiert den Plan auf logische Konsistenz.

    DEC-028: data_agent wird eingefügt wenn viz_agent ohne data_agent und ohne
    stats_agent geplant ist. Der Data Agent entscheidet selbst über active_dataset_keys.

    Stats Agent als Gatekeeper: stats_agent darf ohne data_agent laufen (Resolve-Modus).
    stats_agent + viz_agent ohne data_agent ist ebenfalls valide (Stats löst aus DuckDB auf).

    Returns:
        Tuple von (is_valid, message, repaired_plan)
    """
    if not plan:
        return True, "Leerer Plan ist valide", plan

    repaired = plan.copy()

    # Prüfe auf ungültige Agents
    for agent in plan:
        if agent not in VALID_AGENTS:
            return False, f"Ungültiger Agent: {agent}", []

    has_data_agent = "data_agent" in plan
    has_stats_agent = "stats_agent" in plan
    has_viz_agent = "viz_agent" in plan

    # Stats Agent darf allein laufen (Resolve bestehender Stats) → OK
    # Stats + Viz ohne Data → Stats löst aus DuckDB auf, Viz visualisiert → OK
    if has_stats_agent and not has_data_agent:
        if has_viz_agent:
            logger.debug("Plan valide: Stats-Resolve + Viz (kein Data Agent nötig)")
        else:
            logger.debug("Plan valide: Stats-Resolve (kein Data Agent nötig)")
        return True, "Plan ist valide (Stats-Resolve)", repaired

    # DEC-028: viz_agent allein ohne stats_agent und ohne data_agent → data_agent einfügen
    if has_viz_agent and not has_data_agent and not has_stats_agent:
        repaired = ["data_agent"] + repaired
        logger.debug("Plan repariert: data_agent hinzugefügt (DEC-028: Viz braucht Daten)")
        return True, "Plan repariert", repaired

    # Prüfe Reihenfolge
    if has_data_agent:
        data_idx = repaired.index("data_agent")

        if has_stats_agent and repaired.index("stats_agent") < data_idx:
            return False, "stats_agent muss nach data_agent kommen", []

        if has_viz_agent and repaired.index("viz_agent") < data_idx:
            return False, "viz_agent muss nach data_agent kommen", []

    return True, "Plan ist valide", repaired


def build_turn_context(turn_history: list, datasets: dict = None, session_id: str = "default") -> str:
    """
    Baut Kontext aus turn_history für den Supervisor (DEC-029).

    Ersetzt build_dataset_context(). Der Supervisor bekommt nun den
    strukturierten Konversationsverlauf statt nur data_summary.

    DEC-031: DuckDB-Check wenn kein turn_history vorhanden.
    Parameter datasets ist deprecated (bleibt für Test-Kompatibilität).
    """
    if not turn_history:
        # DuckDB-Check (DEC-031): Metas direkt aus DuckDB prüfen
        from agents.utils import get_dataset_meta_from_duckdb
        duckdb_metas = get_dataset_meta_from_duckdb(session_id)
        if duckdb_metas:
            return "\n## VORHANDENE DATEN\n\nDaten vorhanden (Details beim Data Agent)."
        return ""

    parts = []

    parts.append("\n## BISHERIGER VERLAUF\n")
    for i, turn in enumerate(turn_history[-15:], 1):  # Max 15 Turns
        query = turn.get("user_query", "?")
        plan = turn.get("plan", [])
        turn_datasets = turn.get("datasets", [])
        result_type = turn.get("result_type", "?")
        result_summary = turn.get("result_summary", "")

        parts.append(f"Turn {i}: \"{query}\"")
        if plan:
            parts.append(f"  Plan: {plan}")
        for ds in turn_datasets:
            keys = ds.get("keys", [])
            tr = ds.get("timerange", "")
            if keys:
                parts.append(f"  Daten: {', '.join(keys[:8])} ({tr})")
        if result_summary:
            parts.append(f"  Ergebnis ({result_type}): {result_summary}")
        # DEC-030: Stats-Dataset-Keys anzeigen
        stats_keys = turn.get("stats_dataset_keys", [])
        if stats_keys:
            parts.append(f"  Stats-Datasets: {', '.join(stats_keys[:5])}")

        # DEC-034: Strukturierte Erkenntnisse für Cross-Turn-Referenzen
        key_facts = turn.get("key_facts", [])
        for fact in key_facts:
            ftype = fact.get("type", "?")
            key = fact.get("key", "?")
            val = fact.get("value")
            ts = fact.get("timestamp")
            tr = fact.get("timerange", "")
            ds_suffix = f" [{tr}]" if tr else ""

            if ftype in ("max", "min"):
                line = f"  >> {ftype.upper()}: {key} = {val}"
                if ts:
                    line += f" (bei {ts})"
                parts.append(line + ds_suffix)
            elif ftype == "correlation":
                parts.append(f"  >> Korrelation: {key} r={val} ({fact.get('interpretation', '')}){ds_suffix}")
            elif ftype == "trend":
                parts.append(f"  >> Trend: {key} = {val} (slope={fact.get('slope')}){ds_suffix}")
            elif ftype == "anomaly":
                parts.append(f"  >> Anomalien: {key} = {val} Stück ({fact.get('percentage', '?')}%){ds_suffix}")
            elif ftype == "activity":
                windows = fact.get("windows", [])
                win_strs = [f"{w['start']}-{w['end']} ({w['duration_s']}s)" for w in windows]
                parts.append(f"  >> Aktivität: {key} = {val} Fenster ({fact.get('active_ratio', 0)*100:.0f}% aktiv): {', '.join(win_strs)}{ds_suffix}")
            elif ftype == "mean":
                parts.append(f"  >> Durchschnitt: {key} = {val}{ds_suffix}")
            elif ftype == "std":
                parts.append(f"  >> Std.Abweichung: {key} = {val}{ds_suffix}")
            elif ftype == "summary":
                parts.append(f"  >> Übersicht: {key} mean={fact.get('mean')} min={fact.get('min')} max={fact.get('max')}{ds_suffix}")
            else:
                parts.append(f"  >> {ftype}: {key} = {val}{ds_suffix}")

        parts.append("")

    return "\n".join(parts)


# =============================================================================
# HAUPTLOGIK
# =============================================================================

async def invoke_llm_with_retry(
    llm,
    messages: list,
    max_retries: int = MAX_RETRIES
) -> str:
    """
    Ruft LLM auf mit Retry bei transienten Fehlern.
    """
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            response = await llm.ainvoke(messages)
            return response.content
        
        except (ConnectionError, TimeoutError) as e:
            last_exception = e
            delay = RETRY_DELAY_BASE * (2 ** attempt)
            logger.warning(f"LLM Fehler (Versuch {attempt + 1}/{max_retries}): {e}")
            
            if attempt < max_retries - 1:
                await asyncio.sleep(delay)
        
        except Exception as e:
            error_str = str(e).lower()
            if "429" in error_str or "rate limit" in error_str:
                last_exception = e
                delay = RETRY_DELAY_BASE * (2 ** attempt)
                logger.warning(f"Rate Limit (Versuch {attempt + 1}/{max_retries})")
                
                if attempt < max_retries - 1:
                    await asyncio.sleep(delay)
            else:
                raise
    
    raise last_exception or Exception("LLM invocation failed after retries")


async def run_supervisor(state: AgentState) -> dict[str, Any]:
    """
    Führt den Supervisor aus und erstellt einen Plan.
    
    Orchestriert:
    1. User-Query extrahieren
    2. Dataset-Kontext aufbauen
    3. LLM aufrufen
    4. Response parsen und validieren
    """
    try:
        logger.debug("Starte Supervisor (PLAN-Modus)")
        is_replan = state.get("replan_count", 0) > 0

        # 1. User-Query extrahieren
        user_query = extract_user_query(state["messages"])
        logger.debug(f"User Query: {user_query}")
        
        if not user_query:
            return {
                "plan": [],
                "reasoning": "Keine User-Anfrage gefunden",
                "needs_user_input": False,
                "user_input_reason": None,
            }
        
        # 2. Turn-Kontext (DEC-029: turn_history statt data_summary)
        turn_history = state.get("turn_history", [])
        session_id = state.get("session_id", "default")
        context_info = build_turn_context(turn_history, session_id=session_id)

        if turn_history:
            logger.debug(f"Turn History: {len(turn_history)} Turns")
        
        # 3. LLM aufrufen (DEC-021: Prompt Caching via list[dict] content)
        llm = create_supervisor_llm()
        enhanced_prompt = get_supervisor_prompt() + context_info

        # DEC-032: Replan-Kontext anhängen wenn in Replan-Phase
        if state.get("replan_count", 0) > 0 and state.get("replan_context"):
            replan_info = _build_replan_context(state["replan_context"])
            enhanced_prompt += replan_info

        messages = [
            create_cached_system_message(enhanced_prompt),
            HumanMessage(content=user_query),
        ]

        logger.debug("Rufe LLM auf mit Prompt Caching...")
        response_content = await invoke_llm_with_retry(llm, messages)
        logger.debug(f"LLM Response: {response_content[:200]}...")

        # 4. Response parsen
        result = parse_supervisor_response(response_content)
        logger.debug(f"Parsed Plan: {result['plan']}")

        # Debug-Log: Vollständiger Supervisor-Aufruf
        _log_supervisor_call(
            mode="PLAN",
            system_prompt=enhanced_prompt,
            user_message=user_query,
            response=response_content,
            state_snapshot={
                "turn_history_len": len(turn_history),
                "replan_count": state.get("replan_count", 0),
                "replan_context": state.get("replan_context"),
                "session_id": session_id,
            },
            result=result,
        )
        
        # 5. Plan validieren und ggf. reparieren
        is_valid, validation_msg, repaired_plan = validate_plan(
            result["plan"],
        )
        
        if not is_valid:
            logger.warning(f"Plan ungültig: {validation_msg}")
            return {
                "plan": [],
                "reasoning": f"Plan ungültig: {validation_msg}",
                "current_step": 0,
                "needs_user_input": False,
                "user_input_reason": None,
            }
        
        final_plan = repaired_plan if repaired_plan != result["plan"] else result["plan"]
        data_mode = result.get("data_mode", "overview")

        data_instructions = result.get("data_instructions")
        viz_instructions = result.get("viz_instructions")
        stats_instructions = result.get("stats_instructions")
        needs_input = result.get("needs_user_input", False)
        input_reason = result.get("user_input_reason")

        # viz_data_source extrahieren und validieren
        viz_data_source = result.get("viz_data_source", "auto")
        if viz_data_source not in ("timeseries", "stats", "auto"):
            logger.warning(f"Ungültiger viz_data_source '{viz_data_source}', verwende 'auto'")
            viz_data_source = "auto"

        logger.info(f"Plan erstellt: {final_plan}, data_mode: {data_mode}")
        if data_instructions:
            logger.info(f"Data Instructions: {data_instructions[:80]}...")
        if viz_instructions:
            logger.info(f"Viz Instructions: {viz_instructions[:80]}...")
        if viz_data_source != "auto":
            logger.info(f"Viz Data Source: {viz_data_source}")
        if stats_instructions:
            logger.info(f"Stats Instructions: {stats_instructions[:80]}...")
        if needs_input:
            logger.info(f"Rückfrage nötig: {input_reason}")

        # Bei Rückfrage → leerer Plan, respond zeigt Frage
        if needs_input and input_reason:
            return {
                **_get_per_turn_reset(replan_mode=is_replan),
                "plan": [],
                "reasoning": result["reasoning"],
                "current_step": 0,
                "needs_user_input": True,
                "user_input_reason": input_reason,
                "messages": [AIMessage(content=input_reason)],
            }

        result_dict = {
            **_get_per_turn_reset(replan_mode=is_replan),
            "plan": final_plan,
            "reasoning": result["reasoning"],
            "current_step": 0,
            "data_retrieval_mode": data_mode,  # DEC-023
            "data_instructions": data_instructions,
            "viz_instructions": viz_instructions,
            "viz_data_source": viz_data_source,
            "stats_instructions": stats_instructions,
            "pending_goals": result.get("pending_goals"),  # DEC-032: Replan-Loop
            "messages": [AIMessage(content=f"Plan erstellt: {final_plan}")],
        }

        # Replan ohne data_agent: active_dataset_keys aus replan_context übernehmen
        # damit Stats/Viz Agents auf bereits geladene Daten zugreifen können
        replan_ctx = state.get("replan_context")
        if is_replan and "data_agent" not in final_plan and replan_ctx:
            prev_keys = replan_ctx.get("active_dataset_keys")
            if prev_keys:
                result_dict["active_dataset_keys"] = prev_keys
                logger.info(f"Replan: active_dataset_keys aus Phase übernommen: {prev_keys}")

        return result_dict
    
    except Exception as e:
        error_msg = f"Fehler bei der Planung: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {
            "plan": [],
            "reasoning": error_msg,
            "error": str(e),
            "needs_user_input": False,
            "user_input_reason": None,
        }


async def run_supervisor_eval(state: AgentState) -> dict[str, Any]:
    """Evaluiert den aktuellen Plan nach Agent-Ausführung (DEC-032).

    Ruft LLM mit Structured Output (EvalDecision) auf um zu entscheiden:
    - continue: Nächster Agent ausführen
    - replan: Plan anpassen (Datenkonflikt etc.)
    - respond: Alle Ziele erfüllt, direkt zur Antwort

    Bei LLM-Fehler: Graceful Degradation → {} (continue als Fallback).
    Bei Plan fertig (step >= len(plan)): {} ohne LLM-Call.
    """
    plan = state.get("plan") or []
    current_step = state.get("current_step", 0)

    # Plan fertig → EVAL trotzdem ausführen um Endergebnis zu prüfen
    # Der EVAL kann "replan" auslösen wenn das Ergebnis nicht zur User-Frage passt
    if current_step >= len(plan):
        logger.debug("Supervisor EVAL: Plan fertig, prüfe Endergebnis")

    try:
        # User-Query extrahieren
        user_query = extract_user_query(state["messages"])

        # Agent Signals aufbereiten
        signals = state.get("agent_signals") or []
        if signals:
            signals_lines = []
            for s in signals:
                signals_lines.append(
                    f"  [{s.get('type', '?').upper()}] {s.get('agent', '?')}/{s.get('code', '?')}: "
                    f"{s.get('message', '')}"
                )
                if s.get("suggestion"):
                    signals_lines.append(f"    → Vorschlag: {s['suggestion']}")
            signals_text = "\n".join(signals_lines)
        else:
            signals_text = "keine"

        # Letzte Agent-Antwort extrahieren (letztes AIMessage ohne Tool-Calls)
        last_agent_response = "keine"
        for msg in reversed(state.get("messages", [])):
            if isinstance(msg, AIMessage) and not msg.tool_calls:
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                if content.strip():
                    last_agent_response = content.strip()[:500]
                    break

        # Verfügbare Daten lesbar beschreiben (statt roher UNS-Keys)
        session_id = state.get("session_id", "default")
        dataset_keys = state.get("active_dataset_keys")
        stats_keys = state.get("active_stats_keys")
        data_description = describe_active_data(session_id, dataset_keys, stats_keys)

        # Geplante Instruktionen für verbleibende Agents
        remaining_instructions = []
        remaining = plan[current_step:]
        if "stats_agent" in remaining and state.get("stats_instructions"):
            remaining_instructions.append(f"stats_agent soll: {state['stats_instructions']}")
        if "viz_agent" in remaining and state.get("viz_instructions"):
            remaining_instructions.append(f"viz_agent soll: {state['viz_instructions']}")
        instructions_text = "\n".join(remaining_instructions) if remaining_instructions else "keine"

        # Eval-Kontext aus State aufbauen
        eval_context = (
            f"User-Anfrage: {user_query}\n"
            f"Ursprünglicher Plan: {plan}\n"
            f"Ausgeführt: {plan[:current_step]}\n"
            f"Verbleibend: {plan[current_step:]}\n"
            f"Letzter Agent: {plan[current_step - 1]}\n\n"
            f"Antwort des letzten Agents:\n{last_agent_response}\n\n"
            f"Geplante Aufgaben der verbleibenden Agents:\n{instructions_text}\n\n"
            f"Aktueller State:\n"
            f"- Verfügbare Daten:\n{data_description}\n"
            f"- statistics_summary: {state.get('statistics_summary', 'keine')}\n"
            f"- chart_url: {state.get('chart_url', 'kein')}\n"
            f"- error: {state.get('error', 'kein')}\n"
            f"- agent_signals:\n{signals_text}"
        )

        # LLM mit Structured Output (DEC-021: Prompt Caching)
        llm = create_anthropic_client()  # DEFAULT_MODEL (Sonnet) für EVAL
        structured_llm = llm.with_structured_output(EvalDecision)

        messages = [
            create_cached_system_message(get_supervisor_eval_prompt()),
            HumanMessage(content=eval_context),
        ]

        logger.debug(f"Supervisor EVAL: LLM-Call nach {plan[current_step - 1]}")
        decision = await structured_llm.ainvoke(messages)
        if decision.viz_data_source:
            logger.info(f"Supervisor EVAL: {decision.action} — {decision.reasoning} (viz_data_source: {decision.viz_data_source})")
        else:
            logger.info(f"Supervisor EVAL: {decision.action} — {decision.reasoning}")

        # Debug-Log: Vollständiger EVAL-Aufruf
        _log_supervisor_call(
            mode="EVAL",
            system_prompt=get_supervisor_eval_prompt(),
            user_message=eval_context,
            response=f"action={decision.action}, reasoning={decision.reasoning}, pending_goals={decision.pending_goals}, viz_data_source={decision.viz_data_source}",
            state_snapshot={
                "plan": plan,
                "current_step": current_step,
                "data_description": data_description,
                "statistics_summary": state.get("statistics_summary", "keine"),
                "chart_url": state.get("chart_url", "kein"),
                "error": state.get("error", "kein"),
                "replan_count": state.get("replan_count", 0),
            },
        )

        if decision.action == "replan":
            return {
                "pending_goals": decision.pending_goals or ["Plan anpassen"],
                "current_step": len(plan),
            }

        if decision.action == "respond":
            return {
                "current_step": len(plan),
                "pending_goals": None,
            }

        # action == "continue": viz_data_source weiterreichen wenn gesetzt
        result = {}
        if decision.viz_data_source:
            result["viz_data_source"] = decision.viz_data_source
        return result

    except Exception as e:
        logger.warning(f"Supervisor EVAL: LLM-Fehler, Fallback auf continue — {e}")
        return {}


async def supervisor_node(state: AgentState) -> dict[str, Any]:
    """LangGraph Node für den Supervisor (Dual-Mode: PLAN oder EVAL)."""
    global _supervisor_call_counter
    # Erste Call pro Turn (step=0, kein Replan) → Log-Datei neu starten
    if state.get("current_step", 0) == 0 and state.get("replan_count", 0) == 0:
        _supervisor_call_counter = 0
        if SUPERVISOR_DEBUG_LOG.exists():
            SUPERVISOR_DEBUG_LOG.unlink()
        logger.debug(f"Supervisor Debug-Log zurückgesetzt: {SUPERVISOR_DEBUG_LOG}")

    if _is_eval_mode(state):
        return await run_supervisor_eval(state)
    return await run_supervisor(state)


# =============================================================================
# TESTS
# =============================================================================

async def test_supervisor():
    """Test des Supervisors mit verschiedenen Queries."""
    
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    
    test_cases = [
        ("Zeig mir die Temperatur von Roboter 1", ["data_agent", "viz_agent"]),
        ("Wie ist die aktuelle Position von Achse 1?", ["data_agent"]),
        ("Was ist die Durchschnittstemperatur?", ["data_agent", "stats_agent"]),
        ("Wie wird das Wetter morgen?", []),
    ]
    
    print("\n" + "="*70)
    print("🧪 Supervisor Test")
    print("="*70)
    
    passed = 0
    
    for query, expected in test_cases:
        print(f"\n📝 Query: {query}")
        print(f"   Erwartet: {expected}")
        
        state = AgentState(messages=[HumanMessage(content=query)])
        result = await run_supervisor(state)
        
        actual = result.get("plan", [])
        print(f"   Erhalten: {actual}")
        
        if actual == expected:
            print("   ✅ PASS")
            passed += 1
        else:
            print("   ❌ FAIL")
    
    print(f"\n{'='*70}")
    print(f"Ergebnis: {passed}/{len(test_cases)} Tests bestanden")


if __name__ == "__main__":
    asyncio.run(test_supervisor())
