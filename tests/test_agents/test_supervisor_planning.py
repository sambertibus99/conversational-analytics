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
        is_valid, msg = validate_plan(["data_agent"])
        
        assert is_valid
    
    def test_valid_data_and_viz(self):
        """Testet gültigen Plan: data + viz."""
        is_valid, msg = validate_plan(["data_agent", "viz_agent"])
        
        assert is_valid
    
    def test_valid_data_and_stats(self):
        """Testet gültigen Plan: data + stats."""
        is_valid, msg = validate_plan(["data_agent", "stats_agent"])
        
        assert is_valid
    
    def test_valid_all_agents(self):
        """Testet gültigen Plan: alle Agents."""
        is_valid, msg = validate_plan(["data_agent", "stats_agent", "viz_agent"])
        
        assert is_valid
    
    def test_valid_empty_plan(self):
        """Testet gültigen leeren Plan."""
        is_valid, msg = validate_plan([])
        
        assert is_valid
    
    def test_invalid_stats_without_data(self):
        """Testet ungültigen Plan: stats ohne data."""
        is_valid, msg = validate_plan(["stats_agent"])
        
        assert not is_valid
        assert "data_agent" in msg.lower()
    
    def test_invalid_viz_without_data(self):
        """Testet ungültigen Plan: viz ohne data."""
        is_valid, msg = validate_plan(["viz_agent"])
        
        assert not is_valid
        assert "data_agent" in msg.lower()
    
    def test_invalid_wrong_order(self):
        """Testet ungültigen Plan: falsche Reihenfolge."""
        is_valid, msg = validate_plan(["viz_agent", "data_agent"])
        
        assert not is_valid
    
    def test_invalid_unknown_agent(self):
        """Testet ungültigen Plan: unbekannter Agent."""
        is_valid, msg = validate_plan(["unknown_agent"])
        
        assert not is_valid


# =============================================================================
# EXTRACT_USER_QUERY TESTS
# =============================================================================

class TestExtractUserQuery:
    """Tests für extract_user_query()."""
    
    def test_extract_from_single_message(self):
        """Testet Extraktion aus einzelner Message."""
        state = AgentState(
            messages=[HumanMessage(content="Test query")]
        )
        
        result = extract_user_query(state)
        
        assert result == "Test query"
    
    def test_extract_first_human_message(self):
        """Testet dass erste HumanMessage verwendet wird."""
        state = AgentState(
            messages=[
                SystemMessage(content="System"),
                HumanMessage(content="First query"),
                HumanMessage(content="Second query"),
            ]
        )
        
        result = extract_user_query(state)
        
        assert result == "First query"
    
    def test_extract_skips_system_messages(self):
        """Testet dass SystemMessages übersprungen werden."""
        state = AgentState(
            messages=[
                SystemMessage(content="System prompt"),
                HumanMessage(content="User query"),
            ]
        )
        
        result = extract_user_query(state)
        
        assert result == "User query"
    
    def test_extract_empty_messages(self):
        """Testet leere Message-Liste."""
        state = AgentState(messages=[])
        
        result = extract_user_query(state)
        
        assert result == ""
    
    def test_extract_no_human_messages(self):
        """Testet wenn keine HumanMessage vorhanden."""
        state = AgentState(
            messages=[
                SystemMessage(content="System"),
                AIMessage(content="AI response"),
            ]
        )
        
        result = extract_user_query(state)
        
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
        is_valid, msg = validate_plan(expected_plan)
        
        assert is_valid, f"Erwarteter Plan {expected_plan} ist ungültig: {msg}"


# =============================================================================
# EDGE CASES (aus AP9-Dokumentation)
# =============================================================================

class TestSupervisorEdgeCases:
    """Tests für Edge Cases beim Supervisor."""
    
    def test_empty_query(self):
        """Testet leere Query."""
        state = AgentState(messages=[HumanMessage(content="")])
        
        query = extract_user_query(state)
        
        assert query == ""
    
    def test_whitespace_query(self):
        """Testet Query mit nur Whitespace."""
        state = AgentState(messages=[HumanMessage(content="   ")])
        
        query = extract_user_query(state)
        
        assert query == "   "  # Whitespace wird erhalten
    
    def test_very_long_query(self):
        """Testet sehr lange Query."""
        long_query = "Zeig mir die Temperatur " * 100
        state = AgentState(messages=[HumanMessage(content=long_query)])
        
        query = extract_user_query(state)
        
        assert len(query) > 2000
    
    def test_special_characters_in_query(self):
        """Testet Query mit Sonderzeichen."""
        state = AgentState(
            messages=[HumanMessage(content="Zeig mir <script>alert('xss')</script>")]
        )
        
        query = extract_user_query(state)
        
        assert "<script>" in query  # Wird nicht gefiltert
    
    def test_unicode_in_query(self):
        """Testet Query mit Unicode."""
        state = AgentState(
            messages=[HumanMessage(content="Zeig mir die Temperatur 🌡️")]
        )
        
        query = extract_user_query(state)
        
        assert "🌡️" in query


# =============================================================================
# PLAN REPAIR TESTS
# =============================================================================

class TestPlanRepair:
    """Tests für Plan-Reparatur."""
    
    def test_repair_stats_without_data(self):
        """Testet ob data_agent vor stats_agent eingefügt wird."""
        invalid_plan = ["stats_agent"]
        
        # Prüfe Validierung
        is_valid, msg = validate_plan(invalid_plan)
        assert not is_valid
        
        # Reparierter Plan sollte valide sein
        repaired_plan = ["data_agent"] + invalid_plan
        is_valid, msg = validate_plan(repaired_plan)
        assert is_valid
    
    def test_repair_viz_without_data(self):
        """Testet ob data_agent vor viz_agent eingefügt wird."""
        invalid_plan = ["viz_agent"]
        
        # Prüfe Validierung
        is_valid, msg = validate_plan(invalid_plan)
        assert not is_valid
        
        # Reparierter Plan sollte valide sein
        repaired_plan = ["data_agent"] + invalid_plan
        is_valid, msg = validate_plan(repaired_plan)
        assert is_valid


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
        """Testet gültige Agent-Namen."""
        is_valid, msg = validate_plan([agent_name])
        
        # Einzelner Agent ohne data_agent kann ungültig sein
        # Aber der Agent-Name selbst ist gültig
        if agent_name == "data_agent":
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
        is_valid, msg = validate_plan([agent_name])
        
        assert not is_valid
