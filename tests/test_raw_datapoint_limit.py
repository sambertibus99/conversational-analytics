"""
Tests für Raw-Datenpunkt-Estimation und Downsampling-Rückfrage.

Testet check_raw_datapoint_limit(), snap_to_interval() und den
raw_estimation_hook (interrupt-basiert).
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pytest
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch, MagicMock

from langchain_core.messages import AIMessage

from mcp_servers.thingsboard_server import (
    check_raw_datapoint_limit,
    snap_to_interval,
    RAW_DATAPOINT_THRESHOLD,
    RAW_DEFAULT_SAMPLING_HZ,
    INTERVAL_OPTIONS,
)


# =============================================================================
# SNAP_TO_INTERVAL TESTS
# =============================================================================

class TestSnapToInterval:
    """Tests für snap_to_interval()."""

    def test_snap_to_exact_match(self):
        """Exakter Match: 1000ms → 1s."""
        key, ms, human = snap_to_interval(1000)
        assert key == "1s"
        assert ms == 1000
        assert human == "1 Sekunde"

    def test_snap_to_next_larger(self):
        """2500ms liegt zwischen 2s und 3s → snap zu 3s."""
        key, ms, human = snap_to_interval(2500)
        assert key == "3s"
        assert ms == 3000

    def test_snap_small_value(self):
        """Sehr kleiner Wert → kleinstes Intervall (1s)."""
        key, ms, human = snap_to_interval(100)
        assert key == "1s"
        assert ms == 1000

    def test_snap_large_value(self):
        """Sehr großer Wert → größtes Intervall (1d)."""
        key, ms, human = snap_to_interval(100_000_000)
        assert key == "1d"
        assert ms == 86400000

    def test_snap_to_1m(self):
        """45000ms → nächstes ist 1m (60000ms)."""
        key, ms, human = snap_to_interval(45000)
        assert key == "1m"
        assert ms == 60000

    def test_snap_to_10s(self):
        """7000ms → nächstes ist 10s (10000ms)."""
        key, ms, human = snap_to_interval(7000)
        assert key == "10s"
        assert ms == 10000


# =============================================================================
# CHECK_RAW_DATAPOINT_LIMIT TESTS
# =============================================================================

class TestCheckRawDatapointLimit:
    """Tests für check_raw_datapoint_limit()."""

    def test_under_threshold_returns_none(self):
        """Kurzer Zeitraum mit wenig Keys → None (OK)."""
        start = datetime(2025, 12, 16, 12, 0)
        end = datetime(2025, 12, 16, 12, 1)  # 1 Minute
        # 60s × 10Hz × 1 Key = 600 Punkte < 5000
        result = check_raw_datapoint_limit(start, end, num_keys=1)
        assert result is None

    def test_5min_1key_under_threshold(self):
        """5 Minuten, 1 Key → 3000 Punkte < 5000."""
        start = datetime(2025, 12, 16, 12, 0)
        end = datetime(2025, 12, 16, 12, 5)
        result = check_raw_datapoint_limit(start, end, num_keys=1)
        assert result is None

    def test_over_threshold_returns_error_dict(self):
        """Langer Zeitraum → error_too_many_datapoints."""
        start = datetime(2025, 12, 16, 12, 0)
        end = datetime(2025, 12, 16, 13, 0)  # 1 Stunde
        # 3600s × 10Hz × 2 Keys = 72.000 Punkte > 5000
        result = check_raw_datapoint_limit(start, end, num_keys=2)
        assert result is not None
        assert result["status"] == "error_too_many_datapoints"
        assert result["estimated_total_points"] == 72000
        assert result["estimated_per_key"] == 36000
        assert result["threshold"] == RAW_DATAPOINT_THRESHOLD

    def test_over_threshold_has_suggestion(self):
        """Error-Dict enthält Intervall-Vorschlag."""
        start = datetime(2025, 12, 16, 12, 0)
        end = datetime(2025, 12, 16, 13, 0)
        result = check_raw_datapoint_limit(start, end, num_keys=1)
        assert result is not None
        assert "suggestion" in result
        assert "interval" in result["suggestion"]
        assert "interval_human" in result["suggestion"]
        assert "expected_points" in result["suggestion"]

    def test_over_threshold_has_options(self):
        """Error-Dict enthält mehrere Intervall-Optionen."""
        start = datetime(2025, 12, 16, 12, 0)
        end = datetime(2025, 12, 16, 13, 0)
        result = check_raw_datapoint_limit(start, end, num_keys=1)
        assert result is not None
        assert "options" in result
        assert len(result["options"]) >= 1
        for opt in result["options"]:
            assert "interval" in opt
            assert "interval_human" in opt
            assert "estimated_points" in opt

    def test_over_threshold_has_hint(self):
        """Error-Dict enthält Hint-Text."""
        start = datetime(2025, 12, 16, 12, 0)
        end = datetime(2025, 12, 16, 13, 0)
        result = check_raw_datapoint_limit(start, end, num_keys=1)
        assert result is not None
        assert "hint" in result
        assert "user_action" in result

    def test_multiple_keys_multiply(self):
        """Mehrere Keys multiplizieren die geschätzte Punktzahl."""
        start = datetime(2025, 12, 16, 12, 0)
        end = datetime(2025, 12, 16, 12, 5)  # 5 Minuten

        result_1key = check_raw_datapoint_limit(start, end, num_keys=1)
        # 300s × 10Hz × 1 = 3000 → None
        assert result_1key is None

        result_6keys = check_raw_datapoint_limit(start, end, num_keys=6)
        # 300s × 10Hz × 6 = 18.000 → Error
        assert result_6keys is not None
        assert result_6keys["status"] == "error_too_many_datapoints"
        assert result_6keys["estimated_total_points"] == 18000

    def test_exact_threshold_returns_none(self):
        """Genau am Threshold → None (OK, <=)."""
        # 5000 / 10Hz / 1 Key = 500s = 8min 20s
        start = datetime(2025, 12, 16, 12, 0, 0)
        end = datetime(2025, 12, 16, 12, 8, 20)  # 500 Sekunden
        result = check_raw_datapoint_limit(start, end, num_keys=1)
        assert result is None

    def test_custom_sampling_hz(self):
        """Custom Sampling-Rate wird berücksichtigt."""
        start = datetime(2025, 12, 16, 12, 0)
        end = datetime(2025, 12, 16, 12, 1)  # 1 Minute
        # 60s × 100Hz × 1 = 6000 > 5000
        result = check_raw_datapoint_limit(start, end, num_keys=1, sampling_hz=100)
        assert result is not None
        assert result["estimated_total_points"] == 6000


# =============================================================================
# INTEGRATION: RAW MODE IN GET_TELEMETRY (MCP-Tool)
# =============================================================================

class TestRawModeIntegration:
    """Tests für Raw-Modus in get_telemetry (nach Hook-Refactoring).

    Hinweis: Die Datenpunkt-Estimation erfolgt jetzt im post_model_hook
    (raw_estimation_hook) des Data Agents, nicht mehr im MCP-Tool.
    Das MCP-Tool führt den API-Call direkt aus.
    """

    @pytest.mark.asyncio
    async def test_raw_mode_calls_api_directly(self):
        """MCP-Tool führt Raw-API-Call aus (Estimation ist jetzt im Hook)."""
        from mcp_servers.thingsboard_server import get_telemetry

        with patch("mcp_servers.thingsboard_server.get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get_telemetry.return_value = {
                "key1": [{"value": "1.0", "timestamp": 1000}]
            }
            mock_get_client.return_value = mock_client

            # Auch bei langem Zeitraum: MCP-Tool ruft API auf
            result = await get_telemetry(
                keys="key1",
                start_date="2025-12-16",
                end_date="2025-12-16",
                start_time="12:00",
                end_time="13:00",
                raw=True,
            )

            parsed = json.loads(result)
            assert parsed["status"] == "success"
            mock_client.get_telemetry.assert_called_once()

    @pytest.mark.asyncio
    async def test_raw_mode_passes_short_timeframe(self):
        """Kurzer Zeitraum: API-Call wird normal ausgeführt."""
        from mcp_servers.thingsboard_server import get_telemetry

        with patch("mcp_servers.thingsboard_server.get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get_telemetry.return_value = {
                "key1": [{"value": "1.0", "timestamp": 1000}]
            }
            mock_get_client.return_value = mock_client

            # 1 Minute, 1 Key → 600 geschätzte Punkte < 5000
            result = await get_telemetry(
                keys="key1",
                start_date="2025-12-16",
                end_date="2025-12-16",
                start_time="12:00",
                end_time="12:01",
                raw=True,
            )

            parsed = json.loads(result)
            assert parsed["status"] == "success"
            # API-Call MUSS stattgefunden haben
            mock_client.get_telemetry.assert_called_once()


# =============================================================================
# RAW ESTIMATION HOOK TESTS (automatisches Downsampling)
# =============================================================================

class TestRawEstimationHook:
    """Tests für raw_estimation_hook() — automatisches Downsampling mit Key-Splitting."""

    def test_hook_ignores_non_raw_tool_calls(self):
        """Hook greift nicht bei raw=False Tool-Calls ein."""
        from agents.data_agent import raw_estimation_hook

        ai_msg = AIMessage(
            content="",
            tool_calls=[{
                "id": "tc_1",
                "name": "get_telemetry",
                "args": {
                    "keys": "key1",
                    "start_date": "2025-12-16",
                    "end_date": "2025-12-16",
                    "start_time": "12:00",
                    "end_time": "13:00",
                    "raw": False,
                },
            }],
        )
        state = {"messages": [ai_msg]}
        result = raw_estimation_hook(state)
        assert result == {}
        assert len(ai_msg.tool_calls) == 1
        assert ai_msg.tool_calls[0]["args"]["raw"] is False

    def test_hook_ignores_non_get_telemetry(self):
        """Hook greift nicht bei anderen Tools ein."""
        from agents.data_agent import raw_estimation_hook

        ai_msg = AIMessage(
            content="",
            tool_calls=[{
                "id": "tc_1",
                "name": "search_telemetry_keys",
                "args": {"query": "drehmoment"},
            }],
        )
        state = {"messages": [ai_msg]}
        result = raw_estimation_hook(state)
        assert result == {}
        assert len(ai_msg.tool_calls) == 1

    def test_hook_passes_under_threshold(self):
        """Hook lässt kurze Zeiträume als raw durch."""
        from agents.data_agent import raw_estimation_hook

        # 1 Minute, 1 Key → 600 Punkte < 5000
        ai_msg = AIMessage(
            content="",
            tool_calls=[{
                "id": "tc_1",
                "name": "get_telemetry",
                "args": {
                    "keys": "key1",
                    "start_date": "2025-12-16",
                    "end_date": "2025-12-16",
                    "start_time": "12:00",
                    "end_time": "12:01",
                    "raw": True,
                },
            }],
        )
        state = {"messages": [ai_msg]}
        result = raw_estimation_hook(state)
        assert result == {}
        assert len(ai_msg.tool_calls) == 1
        assert ai_msg.tool_calls[0]["args"]["raw"] is True

    def test_hook_splits_6_keys_into_6_calls(self):
        """6 Keys über Threshold → 6 Einzel-Calls mit feinerem Intervall."""
        from agents.data_agent import raw_estimation_hook

        # 1h, 6 Keys → 216.000 Rohdaten > 5000
        # Pro Key: Budget 6000, interval = 3600000/6000 = 600ms → snap to 1s
        ai_msg = AIMessage(
            content="",
            tool_calls=[{
                "id": "tc_1",
                "name": "get_telemetry",
                "args": {
                    "keys": "key1,key2,key3,key4,key5,key6",
                    "start_date": "2025-12-16",
                    "end_date": "2025-12-16",
                    "start_time": "12:00",
                    "end_time": "13:00",
                    "raw": True,
                },
            }],
        )
        state = {"messages": [ai_msg]}
        raw_estimation_hook(state)

        # 1 Multi-Key-Call → 6 Einzel-Key-Calls
        assert len(ai_msg.tool_calls) == 6
        expected_keys = ["key1", "key2", "key3", "key4", "key5", "key6"]
        for i, tc in enumerate(ai_msg.tool_calls):
            assert tc["args"]["keys"] == expected_keys[i]
            assert tc["args"]["raw"] is False
            assert tc["args"]["interval"] == "1s"
            assert tc["args"]["aggregation"] == "AVG"
            assert tc["id"] == f"tc_1_{i}"

    def test_hook_single_key_gets_finest_interval(self):
        """1 Key über Threshold → 1 Call mit feinstem Intervall (1s)."""
        from agents.data_agent import raw_estimation_hook

        # 1h, 1 Key → 36.000 Rohdaten > 5000
        # Budget 6000, interval = 3600000/6000 = 600ms → snap to 1s
        ai_msg = AIMessage(
            content="",
            tool_calls=[{
                "id": "tc_1",
                "name": "get_telemetry",
                "args": {
                    "keys": "key1",
                    "start_date": "2025-12-16",
                    "end_date": "2025-12-16",
                    "start_time": "12:00",
                    "end_time": "13:00",
                    "raw": True,
                },
            }],
        )
        state = {"messages": [ai_msg]}
        raw_estimation_hook(state)

        assert len(ai_msg.tool_calls) == 1
        tc = ai_msg.tool_calls[0]
        assert tc["args"]["raw"] is False
        assert tc["args"]["interval"] == "1s"

    def test_hook_preserves_other_tool_calls(self):
        """Nicht-betroffene Tool-Calls bleiben erhalten."""
        from agents.data_agent import raw_estimation_hook

        ai_msg = AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "tc_search",
                    "name": "search_telemetry_keys",
                    "args": {"query": "test"},
                },
                {
                    "id": "tc_raw",
                    "name": "get_telemetry",
                    "args": {
                        "keys": "key1,key2,key3",
                        "start_date": "2025-12-16",
                        "end_date": "2025-12-16",
                        "start_time": "12:00",
                        "end_time": "13:00",
                        "raw": True,
                    },
                },
                {
                    "id": "tc_agg",
                    "name": "get_telemetry",
                    "args": {
                        "keys": "keyA",
                        "start_date": "2025-12-16",
                        "end_date": "2025-12-16",
                        "start_time": "12:00",
                        "end_time": "13:00",
                        "raw": False,
                        "interval": "10m",
                    },
                },
            ],
        )
        state = {"messages": [ai_msg]}
        raw_estimation_hook(state)

        # search_telemetry_keys + 3 gesplittete + 1 aggregated = 5
        assert len(ai_msg.tool_calls) == 5
        # Erster bleibt search
        assert ai_msg.tool_calls[0]["name"] == "search_telemetry_keys"
        # 3 gesplittete Calls
        for i in range(1, 4):
            assert ai_msg.tool_calls[i]["args"]["raw"] is False
            assert ai_msg.tool_calls[i]["args"]["interval"] == "1s"
        # Letzter bleibt aggregated
        assert ai_msg.tool_calls[4]["id"] == "tc_agg"
        assert ai_msg.tool_calls[4]["args"]["interval"] == "10m"

    def test_hook_long_timerange_coarser_interval(self):
        """Längerer Zeitraum → gröberes Intervall (aber immer noch pro Key)."""
        from agents.data_agent import raw_estimation_hook

        # 12h, 2 Keys → interval = 43200000/6000 = 7200ms → snap to 10s
        ai_msg = AIMessage(
            content="",
            tool_calls=[{
                "id": "tc_1",
                "name": "get_telemetry",
                "args": {
                    "keys": "key1,key2",
                    "start_date": "2025-12-16",
                    "end_date": "2025-12-16",
                    "start_time": "06:00",
                    "end_time": "18:00",
                    "raw": True,
                },
            }],
        )
        state = {"messages": [ai_msg]}
        raw_estimation_hook(state)

        assert len(ai_msg.tool_calls) == 2
        for tc in ai_msg.tool_calls:
            assert tc["args"]["interval"] == "10s"

    def test_hook_syncs_content_with_tool_calls(self):
        """Hook synchronisiert AIMessage.content mit gesplitteten tool_calls."""
        from agents.data_agent import raw_estimation_hook

        # AIMessage mit content-Blöcken wie Anthropic sie liefert
        original_id = "toolu_abc123"
        ai_msg = AIMessage(
            content=[
                {"type": "text", "text": "Ich hole die Daten..."},
                {
                    "type": "tool_use",
                    "id": original_id,
                    "name": "get_telemetry",
                    "input": {
                        "keys": "key1,key2,key3",
                        "start_date": "2025-12-16",
                        "end_date": "2025-12-16",
                        "start_time": "12:00",
                        "end_time": "13:00",
                        "raw": True,
                    },
                },
            ],
            tool_calls=[{
                "id": original_id,
                "name": "get_telemetry",
                "args": {
                    "keys": "key1,key2,key3",
                    "start_date": "2025-12-16",
                    "end_date": "2025-12-16",
                    "start_time": "12:00",
                    "end_time": "13:00",
                    "raw": True,
                },
            }],
        )
        state = {"messages": [ai_msg]}
        raw_estimation_hook(state)

        # tool_calls gesplittet
        assert len(ai_msg.tool_calls) == 3

        # content muss auch 3 tool_use Blöcke haben (+ 1 text Block)
        tool_use_blocks = [b for b in ai_msg.content if isinstance(b, dict) and b.get("type") == "tool_use"]
        assert len(tool_use_blocks) == 3

        # IDs müssen matchen
        content_ids = {b["id"] for b in tool_use_blocks}
        tc_ids = {tc["id"] for tc in ai_msg.tool_calls}
        assert content_ids == tc_ids

        # Original-ID darf nicht mehr in content sein
        assert original_id not in content_ids

        # Text-Block bleibt erhalten
        text_blocks = [b for b in ai_msg.content if isinstance(b, dict) and b.get("type") == "text"]
        assert len(text_blocks) == 1

    def test_hook_empty_state(self):
        """Hook gibt {} zurück bei leerem State."""
        from agents.data_agent import raw_estimation_hook

        assert raw_estimation_hook({}) == {}
        assert raw_estimation_hook({"messages": []}) == {}
