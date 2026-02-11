"""
Tests für Supervisor Agent Planung.

Testet:
- Plan-Generierung für verschiedene Query-Typen
- Parsing von LLM-Responses
- Plan-Validierung
- Edge Cases

Referenz: docs/AP9_DEBUGGING_TESTING.md Abschnitt 4
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pytest
import json

from agents.supervisor import (
    parse_supervisor_response,
    validate_plan,
    extract_user_query,
    build_dataset_context,
)
from agents.state import AgentState
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage


# =============================================================================
# PARSE_SUPERVISOR_RESPONSE TESTS
# =============================================================================

class TestParseSupervisorResponse:
    """Tests für parse_supervisor_response()."""
    
    def test_parse_valid_json(self):
        """Testet Parsing von gültigem JSON."""
        response = '{"plan": ["data_agent"], "reasoning": "Test"}'
        
        result = parse_supervisor_response(response)
        
        assert result["plan"] == ["data_agent"]
        assert result["reasoning"] == "Test"
    
    def test_parse_json_with_markdown_codeblock(self):
        """Testet Parsing von JSON in Markdown-Codeblock."""
        response = '''```json
{"plan": ["data_agent", "viz_agent"], "reasoning": "Braucht Daten und Chart"}
```'''
        
        result = parse_supervisor_response(response)
        
        assert result["plan"] == ["data_agent", "viz_agent"]
    
    def test_parse_json_with_backticks_only(self):
        """Testet Parsing mit nur Backticks (ohne json)."""
        response = '''```
{"plan": ["data_agent"], "reasoning": "Test"}
```'''
        
        result = parse_supervisor_response(response)
        
        assert result["plan"] == ["data_agent"]
    
    def test_parse_empty_plan(self):
        """Testet Parsing von leerem Plan."""
        response = '{"plan": [], "reasoning": "Keine IIoT-Anfrage"}'
        
        result = parse_supervisor_response(response)
        
        assert result["plan"] == []
    
    def test_parse_invalid_json(self):
        """Testet Parsing von ungültigem JSON."""
        response = 'This is not JSON'
        
        result = parse_supervisor_response(response)
        
        assert result["plan"] == []
        assert "error" in result["reasoning"].lower() or "parse" in result["reasoning"].lower()
    
    def test_parse_missing_plan_field(self):
        """Testet Parsing ohne plan-Feld."""
        response = '{"reasoning": "Test"}'
        
        result = parse_supervisor_response(response)
        
        assert result["plan"] == []
    
    def test_parse_plan_not_list(self):
        """Testet Parsing wenn plan kein Array ist."""
        response = '{"plan": "data_agent", "reasoning": "Test"}'
        
        result = parse_supervisor_response(response)
        
        assert result["plan"] == []
    
    def test_parse_with_whitespace(self):
        """Testet Parsing mit Extra-Whitespace."""
        response = '''   
        {"plan": ["data_agent"], "reasoning": "Test"}
        '''
        
        result = parse_supervisor_response(response)
        
        assert result["plan"] == ["data_agent"]
    
    def test_parse_empty_response(self):
        """Testet Parsing von leerer Response."""
        result = parse_supervisor_response("")
        
        assert result["plan"] == []
    
    def test_parse_none_response(self):
        """Testet Parsing von None."""
        result = parse_supervisor_response(None)
        
        assert result["plan"] == []


# =============================================================================
# VALIDATE_PLAN TESTS
# =============================================================================

class TestValidatePlan:
    """Tests für validate_plan()."""
    
    def test_valid_data_only(self):
        """Testet gültigen Plan: nur data_agent."""
        is_valid, msg, repaired = validate_plan(["data_agent"], has_datasets=False)

        assert is_valid

    def test_valid_data_and_viz(self):
        """Testet gültigen Plan: data + viz."""
        is_valid, msg, repaired = validate_plan(["data_agent", "viz_agent"], has_datasets=False)

        assert is_valid

    def test_valid_data_and_stats(self):
        """Testet gültigen Plan: data + stats."""
        is_valid, msg, repaired = validate_plan(["data_agent", "stats_agent"], has_datasets=False)

        assert is_valid

    def test_valid_all_agents(self):
        """Testet gültigen Plan: alle Agents."""
        is_valid, msg, repaired = validate_plan(["data_agent", "stats_agent", "viz_agent"], has_datasets=False)

        assert is_valid

    def test_valid_empty_plan(self):
        """Testet gültigen leeren Plan."""
        is_valid, msg, repaired = validate_plan([], has_datasets=False)

        assert is_valid

    def test_repair_stats_without_data_no_datasets(self):
        """Testet dass stats ohne data repariert wird (data_agent wird eingefügt)."""
        is_valid, msg, repaired = validate_plan(["stats_agent"], has_datasets=False)

        assert is_valid
        assert "repariert" in msg.lower()
        assert repaired == ["data_agent", "stats_agent"]

    def test_repair_stats_without_data_with_datasets(self):
        """DEC-028: data_agent wird IMMER eingefügt, auch wenn Datasets vorhanden."""
        is_valid, msg, repaired = validate_plan(["stats_agent"], has_datasets=True)

        assert is_valid
        assert repaired == ["data_agent", "stats_agent"]

    def test_repair_viz_without_data_no_datasets(self):
        """Testet dass viz ohne data repariert wird (data_agent wird eingefügt)."""
        is_valid, msg, repaired = validate_plan(["viz_agent"], has_datasets=False)

        assert is_valid
        assert "repariert" in msg.lower()
        assert repaired == ["data_agent", "viz_agent"]

    def test_repair_viz_without_data_with_datasets(self):
        """DEC-028: data_agent wird IMMER eingefügt, auch wenn Datasets vorhanden."""
        is_valid, msg, repaired = validate_plan(["viz_agent"], has_datasets=True)

        assert is_valid
        assert repaired == ["data_agent", "viz_agent"]

    def test_invalid_wrong_order(self):
        """Testet ungültigen Plan: falsche Reihenfolge."""
        is_valid, msg, repaired = validate_plan(["viz_agent", "data_agent"], has_datasets=False)

        assert not is_valid

    def test_invalid_unknown_agent(self):
        """Testet ungültigen Plan: unbekannter Agent."""
        is_valid, msg, repaired = validate_plan(["unknown_agent"], has_datasets=False)

        assert not is_valid


# =============================================================================
# EXTRACT_USER_QUERY TESTS
# =============================================================================

class TestExtractUserQuery:
    """Tests für extract_user_query()."""
    
    def test_extract_from_single_message(self):
        """Testet Extraktion aus einzelner Message."""
        messages = [HumanMessage(content="Test query")]

        result = extract_user_query(messages)

        assert result == "Test query"

    def test_extract_last_human_message(self):
        """Testet dass letzte HumanMessage verwendet wird."""
        messages = [
            SystemMessage(content="System"),
            HumanMessage(content="First query"),
            HumanMessage(content="Second query"),
        ]

        result = extract_user_query(messages)

        assert result == "Second query"

    def test_extract_skips_system_messages(self):
        """Testet dass SystemMessages übersprungen werden."""
        messages = [
            SystemMessage(content="System prompt"),
            HumanMessage(content="User query"),
        ]

        result = extract_user_query(messages)

        assert result == "User query"

    def test_extract_empty_messages(self):
        """Testet leere Message-Liste."""
        result = extract_user_query([])

        assert result == ""

    def test_extract_no_human_messages(self):
        """Testet wenn keine HumanMessage vorhanden."""
        messages = [
            SystemMessage(content="System"),
            AIMessage(content="AI response"),
        ]

        result = extract_user_query(messages)

        assert result == ""


# =============================================================================
# EXPECTED PLAN TESTS (aus AP9-Dokumentation)
# =============================================================================

class TestExpectedPlans:
    """
    Tests für erwartete Pläne basierend auf Query-Typen.
    
    Diese Tests prüfen die Plan-Logik, nicht den LLM-Output!
    """
    
    @pytest.mark.parametrize("query,expected_plan", [
        # Nur Daten
        ("Wie ist die aktuelle Position von Achse 1?", ["data_agent"]),
        ("Liste alle Geräte auf", ["data_agent"]),
        ("Welche Telemetrie-Keys sind verfügbar?", ["data_agent"]),
        ("Wann gibt es Daten?", ["data_agent"]),
        
        # Daten + Visualisierung
        ("Zeig mir die Temperatur", ["data_agent", "viz_agent"]),
        ("TCP Position als Liniendiagramm", ["data_agent", "viz_agent"]),
        ("Zeig den Verlauf als Chart", ["data_agent", "viz_agent"]),
        
        # Daten + Statistik
        ("Was ist die Durchschnittstemperatur?", ["data_agent", "stats_agent"]),
        ("Gab es Anomalien?", ["data_agent", "stats_agent"]),
        ("Berechne die Standardabweichung", ["data_agent", "stats_agent"]),
        
        # Daten + Statistik + Visualisierung
        ("Korrelation als Chart", ["data_agent", "stats_agent", "viz_agent"]),
        
        # Keine IIoT-Anfrage
        ("Wie wird das Wetter morgen?", []),
        ("Erzähl mir einen Witz", []),
    ])
    def test_query_to_plan_mapping(self, query, expected_plan):
        """
        Testet dass Queries zu den richtigen Plan-Typen führen würden.
        
        HINWEIS: Dies testet nur die erwarteten Pläne, nicht den LLM!
        """
        # Validiere dass der erwartete Plan gültig ist
        is_valid, msg, repaired = validate_plan(expected_plan, has_datasets=False)

        assert is_valid, f"Erwarteter Plan {expected_plan} ist ungültig: {msg}"


# =============================================================================
# EDGE CASES (aus AP9-Dokumentation)
# =============================================================================

class TestSupervisorEdgeCases:
    """Tests für Edge Cases beim Supervisor."""
    
    def test_empty_query(self):
        """Testet leere Query."""
        messages = [HumanMessage(content="")]

        query = extract_user_query(messages)

        assert query == ""

    def test_whitespace_query(self):
        """Testet Query mit nur Whitespace."""
        messages = [HumanMessage(content="   ")]

        query = extract_user_query(messages)

        assert query == "   "  # Whitespace wird erhalten

    def test_very_long_query(self):
        """Testet sehr lange Query."""
        long_query = "Zeig mir die Temperatur " * 100
        messages = [HumanMessage(content=long_query)]

        query = extract_user_query(messages)

        assert len(query) > 2000

    def test_special_characters_in_query(self):
        """Testet Query mit Sonderzeichen."""
        messages = [HumanMessage(content="Zeig mir <script>alert('xss')</script>")]

        query = extract_user_query(messages)

        assert "<script>" in query  # Wird nicht gefiltert

    def test_unicode_in_query(self):
        """Testet Query mit Unicode."""
        messages = [HumanMessage(content="Zeig mir die Temperatur \U0001f321\ufe0f")]

        query = extract_user_query(messages)

        assert "\U0001f321\ufe0f" in query


# =============================================================================
# PLAN REPAIR TESTS
# =============================================================================

class TestPlanRepair:
    """Tests für Plan-Reparatur (validate_plan repariert automatisch)."""

    def test_repair_stats_without_data(self):
        """Testet ob data_agent vor stats_agent automatisch eingefügt wird."""
        is_valid, msg, repaired = validate_plan(["stats_agent"], has_datasets=False)

        assert is_valid
        assert repaired == ["data_agent", "stats_agent"]
        assert "repariert" in msg.lower()

    def test_repair_viz_without_data(self):
        """Testet ob data_agent vor viz_agent automatisch eingefügt wird."""
        is_valid, msg, repaired = validate_plan(["viz_agent"], has_datasets=False)

        assert is_valid
        assert repaired == ["data_agent", "viz_agent"]
        assert "repariert" in msg.lower()

    def test_repair_even_when_datasets_exist(self):
        """DEC-028: data_agent wird IMMER eingefügt wenn stats/viz geplant."""
        is_valid, msg, repaired = validate_plan(["stats_agent"], has_datasets=True)

        assert is_valid
        assert repaired == ["data_agent", "stats_agent"]


# =============================================================================
# AGENT NAME VALIDATION TESTS
# =============================================================================

class TestAgentNameValidation:
    """Tests für Agent-Namen-Validierung."""
    
    @pytest.mark.parametrize("agent_name", [
        "data_agent",
        "stats_agent",
        "viz_agent",
    ])
    def test_valid_agent_names(self, agent_name):
        """Testet gültige Agent-Namen (werden ggf. repariert)."""
        is_valid, msg, repaired = validate_plan([agent_name], has_datasets=False)

        # Alle gültigen Agent-Namen ergeben valide Pläne
        # (stats/viz werden repariert mit data_agent davor)
        assert is_valid

    @pytest.mark.parametrize("agent_name", [
        "unknown_agent",
        "DATA_AGENT",  # Case-sensitive
        "data",
        "supervisor",
        "respond",
        "",
        " ",
    ])
    def test_invalid_agent_names(self, agent_name):
        """Testet ungültige Agent-Namen."""
        is_valid, msg, repaired = validate_plan([agent_name], has_datasets=False)

        assert not is_valid


# =============================================================================
# DEC-028: SUPERVISOR GIBT KEIN active_dataset_keys MEHR ZURÜCK
# =============================================================================

class TestParseNoActiveDatasetKeys:
    """Tests für DEC-028: Supervisor gibt kein active_dataset_keys mehr zurück."""

    def test_parse_ignores_active_keys(self):
        """DEC-028: active_dataset_keys vom LLM wird ignoriert."""
        response = json.dumps({
            "plan": ["data_agent", "viz_agent"],
            "reasoning": "Daten vorhanden",
            "data_mode": "overview",
            "active_dataset_keys": ["krc5/torque_actual/timeseries/overview"],
        })

        result = parse_supervisor_response(response)

        assert result["plan"] == ["data_agent", "viz_agent"]
        assert "active_dataset_keys" not in result

    def test_parse_no_active_keys_field(self):
        """DEC-028: Kein active_dataset_keys Feld im Result."""
        response = json.dumps({
            "plan": ["data_agent"],
            "reasoning": "Daten laden",
            "data_mode": "overview",
        })

        result = parse_supervisor_response(response)

        assert "active_dataset_keys" not in result


class TestParseNeedsUserInput:
    """Tests für DEC-026: needs_user_input Parsing."""

    def test_parse_needs_user_input(self):
        """Testet Parsing mit needs_user_input."""
        response = json.dumps({
            "plan": [],
            "reasoning": "Mehrdeutig",
            "data_mode": "overview",
            "needs_user_input": True,
            "user_input_reason": "Es gibt detail und overview Drehmomente. Welche soll ich verwenden?",
        })

        result = parse_supervisor_response(response)

        assert result["needs_user_input"] is True
        assert "detail und overview" in result["user_input_reason"]

    def test_parse_no_user_input_needed(self):
        """Testet Parsing ohne needs_user_input."""
        response = json.dumps({
            "plan": ["viz_agent"],
            "reasoning": "Klar",
            "data_mode": "overview",
        })

        result = parse_supervisor_response(response)

        assert result["needs_user_input"] is False
        assert result["user_input_reason"] is None


# =============================================================================
# DEC-028: BUILD_DATASET_CONTEXT (kompakt, nur Summary)
# =============================================================================

class TestBuildDatasetContext:
    """Tests für build_dataset_context — DEC-028: nur kompakter Summary."""

    def test_empty_datasets_and_summary(self):
        """Testet leere Datasets und leeren Summary."""
        result = build_dataset_context({}, "")

        assert result == ""

    def test_shows_summary_only(self):
        """DEC-028: Zeigt nur data_summary, keine Dataset-Keys."""
        datasets = {
            "krc5/torque_actual/timeseries/overview": {
                "dataset_key": "krc5/torque_actual/timeseries/overview",
                "keys": ["torque_act_a1_nm"],
                "point_count": 240,
            }
        }

        result = build_dataset_context(datasets, "Drehmomente: 240 Punkte")

        assert "Drehmomente: 240 Punkte" in result
        assert "data_agent" in result  # Hinweis dass data_agent entscheidet
        # Keine detaillierten Keys mehr:
        assert "torque_act_a1_nm" not in result

    def test_with_datasets_no_summary(self):
        """Testet mit Datasets aber ohne Summary."""
        datasets = {"some_key": {"dataset_key": "some_key"}}

        result = build_dataset_context(datasets, "")

        assert "Daten vorhanden" in result
        assert "data_agent" in result

    def test_no_datasets_with_summary(self):
        """Testet ohne Datasets aber mit Summary (aus vorherigem Turn)."""
        result = build_dataset_context({}, "Torque: 120 Punkte")

        assert result == ""  # Kein Kontext wenn keine Datasets
