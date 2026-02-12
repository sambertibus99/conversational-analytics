"""
Tests für DEC-029: turn_history State-Infrastruktur und Supervisor-Prompt.

AP1: TurnEntry, TurnDataset, append_turn_history Reducer
AP2: _build_turn_entry und Hilfsfunktionen in graph.py
AP3: get_supervisor_prompt() mit Telemetrie-Referenz
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pytest
from langchain_core.messages import HumanMessage, AIMessage

from agents.state import (
    AgentState,
    TurnDataset,
    TurnEntry,
    append_turn_history,
)
from agents.graph import (
    _build_turn_entry,
    _group_datasets_by_timerange,
    _format_timerange,
    _determine_result_type,
    _determine_result_summary,
)


# =============================================================================
# AP1: APPEND_TURN_HISTORY REDUCER
# =============================================================================

class TestAppendTurnHistory:
    """Tests für den append_turn_history Reducer."""

    def test_empty_plus_new(self):
        """Leere History + neue Einträge."""
        result = append_turn_history([], [{"user_query": "Test"}])

        assert len(result) == 1
        assert result[0]["user_query"] == "Test"

    def test_none_plus_new(self):
        """None existing + neue Einträge."""
        result = append_turn_history(None, [{"user_query": "Test"}])

        assert len(result) == 1

    def test_existing_plus_new(self):
        """Bestehende + neue Einträge werden kombiniert."""
        existing = [{"user_query": "Turn 1"}]
        new = [{"user_query": "Turn 2"}]

        result = append_turn_history(existing, new)

        assert len(result) == 2
        assert result[0]["user_query"] == "Turn 1"
        assert result[1]["user_query"] == "Turn 2"

    def test_existing_plus_none(self):
        """Bestehende + None → bestehende bleiben."""
        existing = [{"user_query": "Turn 1"}]

        result = append_turn_history(existing, None)

        assert len(result) == 1
        assert result[0]["user_query"] == "Turn 1"

    def test_none_plus_none(self):
        """None + None → leere Liste."""
        result = append_turn_history(None, None)

        assert result == []

    def test_max_20_limit(self):
        """Maximal 20 Einträge behalten."""
        existing = [{"user_query": f"Turn {i}"} for i in range(18)]
        new = [{"user_query": f"New {i}"} for i in range(5)]

        result = append_turn_history(existing, new)

        assert len(result) == 20
        # Älteste Einträge werden abgeschnitten
        assert result[0]["user_query"] == "Turn 3"
        assert result[-1]["user_query"] == "New 4"

    def test_exactly_20(self):
        """Genau 20 Einträge: kein Abschneiden."""
        existing = [{"user_query": f"Turn {i}"} for i in range(19)]
        new = [{"user_query": "Turn 19"}]

        result = append_turn_history(existing, new)

        assert len(result) == 20
        assert result[0]["user_query"] == "Turn 0"


# =============================================================================
# AP1: TURN_ENTRY TYPDEFINITIONEN
# =============================================================================

class TestTurnEntry:
    """Tests für TurnEntry TypedDict."""

    def test_full_construction(self):
        """TurnEntry mit allen Feldern."""
        entry: TurnEntry = {
            "user_query": "Korrelation Moment/Position",
            "plan": ["data_agent", "stats_agent"],
            "data_mode": "detail",
            "datasets": [{"keys": ["torque_act_a1_nm"], "timerange": "04.02. 14:20-15:00"}],
            "result_type": "statistics",
            "result_summary": "Korrelation A1 r=0.012",
        }

        assert entry["user_query"] == "Korrelation Moment/Position"
        assert entry["plan"] == ["data_agent", "stats_agent"]
        assert entry["result_type"] == "statistics"

    def test_minimal_construction(self):
        """TurnEntry mit nur Pflichtfeldern (total=False → alle optional)."""
        entry: TurnEntry = {"user_query": "Test"}

        assert entry["user_query"] == "Test"

    def test_datasets_list(self):
        """Datasets ist eine Liste von TurnDataset."""
        entry: TurnEntry = {
            "datasets": [
                {"keys": ["torque_act_a1_nm"], "timerange": "04.02. 14:20-15:00"},
                {"keys": ["vel_act_m_per_s"], "timerange": "03.02. 12:00-14:00"},
            ]
        }

        assert len(entry["datasets"]) == 2


class TestTurnDataset:
    """Tests für TurnDataset TypedDict."""

    def test_construction(self):
        """TurnDataset mit keys und timerange."""
        ds: TurnDataset = {
            "keys": ["torque_act_a1_nm", "torque_act_a2_nm"],
            "timerange": "04.02.2026 14:20 - 15:00",
        }

        assert len(ds["keys"]) == 2
        assert "14:20" in ds["timerange"]


# =============================================================================
# AP1: AGENT_STATE HAT TURN_HISTORY
# =============================================================================

class TestAgentStateHasTurnHistory:
    """Tests für turn_history Feld im AgentState."""

    def test_default_empty(self):
        """Default-Wert ist leere Liste."""
        # AgentState ist ein TypedDict, Default-Werte gelten nur in LangGraph
        # Hier testen wir dass das Feld definiert ist
        assert "turn_history" in AgentState.__annotations__

    def test_field_type(self):
        """turn_history hat Annotated Typ mit Reducer."""
        import typing
        annotation = AgentState.__annotations__["turn_history"]
        # Annotated type check
        origin = typing.get_origin(annotation)
        assert origin is typing.Annotated


# =============================================================================
# AP3: GET_SUPERVISOR_PROMPT
# =============================================================================

class TestGetSupervisorPrompt:
    """Tests für get_supervisor_prompt() (DEC-029)."""

    def test_returns_string(self):
        """Funktion gibt String zurück."""
        from prompts.supervisor_prompt import get_supervisor_prompt

        result = get_supervisor_prompt()

        assert isinstance(result, str)
        assert len(result) > 100

    def test_contains_xml_tags(self):
        """Prompt enthält DEC-015 XML-Tags."""
        from prompts.supervisor_prompt import get_supervisor_prompt

        result = get_supervisor_prompt()

        assert "<role>" in result
        assert "<task>" in result
        assert "<agents>" in result
        assert "<rules>" in result

    def test_contains_telemetry_reference(self):
        """Prompt enthält Telemetrie-Referenz-Tabelle."""
        from prompts.supervisor_prompt import get_supervisor_prompt

        result = get_supervisor_prompt()

        assert "<telemetry_reference>" in result

    def test_contains_turn_history_references(self):
        """Prompt referenziert BISHERIGEN VERLAUF für Multi-Turn."""
        from prompts.supervisor_prompt import get_supervisor_prompt

        result = get_supervisor_prompt()

        assert "BISHERIGER VERLAUF" in result
        assert "BISHERIGEN VERLAUF" in result

    def test_contains_current_date(self):
        """Prompt enthält aktuelles Datum für korrekte Zeitangaben (DEC-022)."""
        from prompts.supervisor_prompt import get_supervisor_prompt
        from datetime import datetime

        result = get_supervisor_prompt()
        current_year = str(datetime.now().year)

        assert "<context>" in result
        assert current_year in result


class TestTelemetryTableContent:
    """Tests für Telemetrie-Tabelle im Prompt."""

    def test_all_groups_present(self):
        """Alle 13 Gruppen-Namen in der Tabelle vorhanden."""
        from prompts.supervisor_prompt import _build_telemetry_table

        table = _build_telemetry_table()

        expected_groups = [
            "Achspositionen (Soll)",
            "Achspositionen (Ist/Gemessen)",
            "Kartesische TCP-Position",
            "Ist-Drehmomente",
            "Soll-Drehmomente",
            "Momentenüberwachung",
            "Bahngeschwindigkeit TCP",
            "Achsgeschwindigkeiten",
            "TCP-Beschleunigung",
            "Achsbeschleunigungen",
            "Energieverbrauch",
            "Momentanbelastung",
            "Programmzustand",
        ]

        for group in expected_groups:
            assert group in table, f"Gruppe '{group}' fehlt in Tabelle"

    def test_table_has_header(self):
        """Tabelle hat Markdown-Header."""
        from prompts.supervisor_prompt import _build_telemetry_table

        table = _build_telemetry_table()

        assert "| Gruppe | Keys | Einheit | Begriffe |" in table

    def test_table_contains_key_patterns(self):
        """Tabelle enthält Key-Muster."""
        from prompts.supervisor_prompt import _build_telemetry_table

        table = _build_telemetry_table()

        assert "torque_act" in table
        assert "axis_act" in table
        assert "vel_act" in table


class TestPromptTokenBudget:
    """Tests für Token-Budget des Supervisor-Prompts."""

    def test_prompt_under_4000_tokens(self):
        """Gesamtprompt < 4000 Tokens (chars/4 Schätzung)."""
        from prompts.supervisor_prompt import get_supervisor_prompt

        prompt = get_supervisor_prompt()
        estimated_tokens = len(prompt) / 4

        assert estimated_tokens < 4000, f"Prompt zu groß: ~{estimated_tokens:.0f} Tokens"


class TestBackwardCompatibility:
    """Tests für Backward-Kompatibilität."""

    def test_constant_still_importable(self):
        """SUPERVISOR_SYSTEM_PROMPT Konstante existiert noch."""
        from prompts.supervisor_prompt import SUPERVISOR_SYSTEM_PROMPT

        assert isinstance(SUPERVISOR_SYSTEM_PROMPT, str)
        assert len(SUPERVISOR_SYSTEM_PROMPT) > 100

    def test_constant_has_same_structure(self):
        """Konstante hat gleiche Struktur wie Funktion (beide dynamisch mit Datum)."""
        from prompts.supervisor_prompt import SUPERVISOR_SYSTEM_PROMPT, get_supervisor_prompt

        prompt = get_supervisor_prompt()
        # Beide enthalten die Kernstrukturen
        for tag in ["<role>", "<task>", "<context>", "<agents>", "<rules>"]:
            assert tag in SUPERVISOR_SYSTEM_PROMPT, f"{tag} fehlt in Konstante"
            assert tag in prompt, f"{tag} fehlt in Funktion"


# =============================================================================
# AP2: _BUILD_TURN_ENTRY UND HILFSFUNKTIONEN
# =============================================================================

def _make_state(**overrides) -> dict:
    """Erstellt einen minimalen State-Dict für Tests."""
    base = {
        "messages": [HumanMessage(content="Test-Anfrage")],
        "plan": ["data_agent"],
        "data_retrieval_mode": "overview",
        "datasets": {},
    }
    base.update(overrides)
    return base


class TestBuildTurnEntry:
    """Tests für _build_turn_entry (DEC-029 AP2)."""

    def test_basic_data_turn(self):
        """Basis-Turn mit data_agent Plan."""
        state = _make_state(
            messages=[HumanMessage(content="Zeige aktuelle Drehmomente")],
            plan=["data_agent"],
            data_retrieval_mode="overview",
        )

        entry = _build_turn_entry(state)

        assert entry["user_query"] == "Zeige aktuelle Drehmomente"
        assert entry["plan"] == ["data_agent"]
        assert entry["data_mode"] == "overview"
        assert entry["result_type"] == "data"
        assert "Drehmomente" in entry["result_summary"]

    def test_chart_turn(self):
        """Chart-Turn: result_type='chart', chart_type als Summary."""
        state = _make_state(
            chart_url="http://example.com/chart.png",
            chart_type="line",
            plan=["data_agent", "viz_agent"],
        )

        entry = _build_turn_entry(state)

        assert entry["result_type"] == "chart"
        assert entry["result_summary"] == "line"

    def test_stats_turn(self):
        """Stats-Turn: result_type='statistics', statistics_summary als Summary."""
        state = _make_state(
            statistics_summary="Korrelation A1 r=0.012, A2 r=-0.617",
            plan=["data_agent", "stats_agent"],
            data_retrieval_mode="detail",
        )

        entry = _build_turn_entry(state)

        assert entry["result_type"] == "statistics"
        assert "Korrelation" in entry["result_summary"]
        assert entry["data_mode"] == "detail"

    def test_abstention_turn(self):
        """Abstention: leerer Plan → result_type='abstention'."""
        state = _make_state(
            plan=[],
            reasoning="Anfrage betrifft keine Roboterdaten",
        )

        entry = _build_turn_entry(state)

        assert entry["result_type"] == "abstention"
        assert entry["plan"] == []
        assert "Roboterdaten" in entry["result_summary"]

    def test_clarification_turn(self):
        """Clarification: needs_user_input → result_type='clarification'."""
        state = _make_state(
            needs_user_input=True,
            user_input_reason="Welche Achse meinst du?",
        )

        entry = _build_turn_entry(state)

        assert entry["result_type"] == "clarification"
        assert "Achse" in entry["result_summary"]

    def test_error_turn(self):
        """Error-Turn: error gesetzt → result_type='error'."""
        state = _make_state(
            error="ThingsBoard nicht erreichbar",
        )

        entry = _build_turn_entry(state)

        assert entry["result_type"] == "error"
        assert "ThingsBoard" in entry["result_summary"]

    def test_truncation_long_query(self):
        """User-Query wird auf 200 Zeichen gekürzt."""
        long_query = "A" * 300
        state = _make_state(
            messages=[HumanMessage(content=long_query)],
        )

        entry = _build_turn_entry(state)

        assert len(entry["user_query"]) == 200

    def test_only_active_dataset_keys(self):
        """Nur active_dataset_keys erscheinen in datasets."""
        state = _make_state(
            datasets={
                "krc5/torque/ts": {
                    "dataset_key": "krc5/torque/ts",
                    "keys": ["torque_a1"],
                    "timerange": {"start_human": "14:00", "end_human": "15:00"},
                },
                "krc5/velocity/ts": {
                    "dataset_key": "krc5/velocity/ts",
                    "keys": ["vel_a1"],
                    "timerange": {"start_human": "14:00", "end_human": "15:00"},
                },
            },
            active_dataset_keys=["krc5/torque/ts"],
        )

        entry = _build_turn_entry(state)

        assert "datasets" in entry
        all_keys = []
        for ds in entry["datasets"]:
            all_keys.extend(ds["keys"])
        assert "torque_a1" in all_keys
        assert "vel_a1" not in all_keys

    def test_grouping_same_timerange(self):
        """Gleicher Zeitraum → ein Eintrag mit kombinierten Keys."""
        state = _make_state(
            datasets={
                "krc5/torque/ts": {
                    "dataset_key": "krc5/torque/ts",
                    "keys": ["torque_a1"],
                    "timerange": {"start_human": "14:00", "end_human": "15:00"},
                },
                "krc5/velocity/ts": {
                    "dataset_key": "krc5/velocity/ts",
                    "keys": ["vel_a1"],
                    "timerange": {"start_human": "14:00", "end_human": "15:00"},
                },
            },
        )

        entry = _build_turn_entry(state)

        assert "datasets" in entry
        assert len(entry["datasets"]) == 1
        ds = entry["datasets"][0]
        assert "torque_a1" in ds["keys"]
        assert "vel_a1" in ds["keys"]
        assert ds["timerange"] == "14:00 - 15:00"

    def test_grouping_different_timeranges(self):
        """Verschiedene Zeiträume → separate Einträge."""
        state = _make_state(
            datasets={
                "krc5/torque/ts": {
                    "dataset_key": "krc5/torque/ts",
                    "keys": ["torque_a1"],
                    "timerange": {"start_human": "14:00", "end_human": "15:00"},
                },
                "krc5/velocity/ts": {
                    "dataset_key": "krc5/velocity/ts",
                    "keys": ["vel_a1"],
                    "timerange": {"start_human": "10:00", "end_human": "12:00"},
                },
            },
        )

        entry = _build_turn_entry(state)

        assert "datasets" in entry
        assert len(entry["datasets"]) == 2


class TestFormatTimerange:
    """Tests für _format_timerange."""

    def test_with_human_readable(self):
        assert _format_timerange({"start_human": "14:00", "end_human": "15:00"}) == "14:00 - 15:00"

    def test_with_raw_timestamps(self):
        assert _format_timerange({"start": "1700000000", "end": "1700003600"}) == "1700000000 - 1700003600"

    def test_human_preferred_over_raw(self):
        tr = {"start": "1700000000", "end": "1700003600", "start_human": "14:00", "end_human": "15:00"}
        assert _format_timerange(tr) == "14:00 - 15:00"

    def test_empty_dict(self):
        assert _format_timerange({}) == ""

    def test_none_input(self):
        """None wird als falsy behandelt (leerer String)."""
        assert _format_timerange(None) == ""


class TestDetermineResultType:
    """Tests für _determine_result_type."""

    def test_chart(self):
        assert _determine_result_type({"chart_url": "http://x"}) == "chart"

    def test_statistics(self):
        assert _determine_result_type({"statistics_summary": "r=0.5"}) == "statistics"

    def test_clarification(self):
        assert _determine_result_type({"needs_user_input": True}) == "clarification"

    def test_error(self):
        assert _determine_result_type({"error": "Fehler"}) == "error"

    def test_abstention(self):
        assert _determine_result_type({"plan": []}) == "abstention"

    def test_data_default(self):
        assert _determine_result_type({"plan": ["data_agent"]}) == "data"

    def test_priority_chart_over_stats(self):
        """Chart hat Priorität über Statistics."""
        assert _determine_result_type({"chart_url": "http://x", "statistics_summary": "r=0.5"}) == "chart"


class TestGroupDatasetsByTimerange:
    """Tests für _group_datasets_by_timerange."""

    def test_empty_datasets(self):
        result = _group_datasets_by_timerange({"datasets": {}})
        assert result == []

    def test_non_dict_values_skipped(self):
        result = _group_datasets_by_timerange({"datasets": {"key": "not_a_dict"}})
        assert result == []

    def test_no_keys_skipped(self):
        """Dataset ohne keys wird nicht aufgenommen."""
        result = _group_datasets_by_timerange({
            "datasets": {"key": {"timerange": {"start": "a", "end": "b"}, "keys": []}},
        })
        assert result == []


# =============================================================================
# AP5: INTEGRATION-TESTS (voller Flow)
# =============================================================================

class TestTurnHistoryIntegration:
    """Integration-Tests: _build_turn_entry → turn_history → build_turn_context."""

    def test_full_flow_data_turn(self):
        """Voller Flow: State → _build_turn_entry → build_turn_context."""
        from agents.supervisor import build_turn_context

        # 1. State nach einem Data-Turn
        state = _make_state(
            messages=[HumanMessage(content="Zeige Drehmomente A1 vom 4. Februar 14:20-15:00")],
            plan=["data_agent"],
            data_retrieval_mode="overview",
            datasets={
                "krc5/torque/ts": {
                    "dataset_key": "krc5/torque/ts",
                    "keys": ["torque_act_a1_nm"],
                    "timerange": {"start_human": "04.02. 14:20", "end_human": "04.02. 15:00"},
                },
            },
        )

        # 2. _build_turn_entry erzeugt TurnEntry
        entry = _build_turn_entry(state)

        assert entry["user_query"] == "Zeige Drehmomente A1 vom 4. Februar 14:20-15:00"
        assert entry["plan"] == ["data_agent"]
        assert entry["result_type"] == "data"
        assert "datasets" in entry
        assert entry["datasets"][0]["keys"] == ["torque_act_a1_nm"]

        # 3. build_turn_context formatiert für Supervisor
        context = build_turn_context([entry], {})

        assert "BISHERIGER VERLAUF" in context
        assert "torque_act_a1_nm" in context
        assert "04.02. 14:20 - 04.02. 15:00" in context

    def test_full_flow_multi_turn(self):
        """Voller Flow über 2 Turns: Korrelation → dann als Chart."""
        from agents.supervisor import build_turn_context

        # Turn 1: Korrelation
        state_t1 = _make_state(
            messages=[HumanMessage(content="Korrelation Moment/Position, A1-A3, 4.Feb 14:20-15:00")],
            plan=["data_agent", "stats_agent"],
            data_retrieval_mode="detail",
            statistics_summary="Korrelation A1 r=0.012, A2 r=-0.617, A3 r=0.303",
            datasets={
                "krc5/torque/ts": {
                    "dataset_key": "krc5/torque/ts",
                    "keys": ["torque_act_a1_nm", "torque_act_a2_nm", "torque_act_a3_nm"],
                    "timerange": {"start_human": "04.02. 14:20", "end_human": "04.02. 15:00"},
                },
                "krc5/axis/ts": {
                    "dataset_key": "krc5/axis/ts",
                    "keys": ["axis_act_a1_deg", "axis_act_a2_deg", "axis_act_a3_deg"],
                    "timerange": {"start_human": "04.02. 14:20", "end_human": "04.02. 15:00"},
                },
            },
        )
        entry_t1 = _build_turn_entry(state_t1)

        # Turn 2: Chart
        state_t2 = _make_state(
            messages=[HumanMessage(content="Zeig mir die Daten in einem Diagramm")],
            plan=["data_agent", "viz_agent"],
            data_retrieval_mode="overview",
            chart_url="http://example.com/chart.png",
            chart_type="multi_line",
        )
        entry_t2 = _build_turn_entry(state_t2)

        # Supervisor sieht beide Turns
        context = build_turn_context([entry_t1, entry_t2], {})

        assert "Turn 1" in context
        assert "Turn 2" in context
        assert "Korrelation" in context
        assert "Diagramm" in context
        assert "torque_act_a1_nm" in context

    def test_backward_compat_datasets_without_history(self):
        """Backward-Compat: State mit Datasets aber ohne turn_history."""
        from agents.supervisor import build_turn_context

        # Alte Session: Datasets vorhanden, aber kein turn_history
        datasets = {
            "krc5/torque/ts": {
                "dataset_key": "krc5/torque/ts",
                "keys": ["torque_act_a1_nm"],
            },
        }

        context = build_turn_context([], datasets)

        assert "VORHANDENE DATEN" in context
        assert "Daten vorhanden" in context
        assert "BISHERIGER VERLAUF" not in context

    def test_reducer_accumulates_across_turns(self):
        """Reducer akkumuliert TurnEntries über mehrere Turns."""
        entry1 = {"user_query": "Zeige Drehmomente", "plan": ["data_agent"], "result_type": "data"}
        entry2 = {"user_query": "Als Chart", "plan": ["data_agent", "viz_agent"], "result_type": "chart"}

        # Simuliert 2 Turn-Updates über den Reducer
        history = append_turn_history([], [entry1])
        history = append_turn_history(history, [entry2])

        assert len(history) == 2
        assert history[0]["user_query"] == "Zeige Drehmomente"
        assert history[1]["user_query"] == "Als Chart"
