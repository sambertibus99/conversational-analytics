"""
Tests für Stats Agent und Stats MCP Server.

Testet:
1. Stats Functions (pure Python)
2. Stats MCP Server (Tool-Aufrufe)
3. Stats Agent (End-to-End)
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import asyncio
import pytest
from datetime import datetime, timedelta
import random

from tools.stats_functions import (
    calculate_mean,
    calculate_std,
    calculate_min_max,
    calculate_correlation_timeseries,  # DEC-024
    calculate_linear_trend,
    calculate_moving_average,
    calculate_percentiles,
    detect_anomalies,
)


# =============================================================================
# UNIT TESTS: Stats Functions
# =============================================================================

class TestStatsFunctions:
    """Tests für die reinen Python-Statistikfunktionen."""
    
    def test_mean_basic(self):
        """Durchschnitt einfacher Werte."""
        result = calculate_mean([1, 2, 3, 4, 5])
        assert result["mean"] == 3.0
        assert result["count"] == 5
    
    def test_mean_empty(self):
        """Durchschnitt leerer Liste."""
        result = calculate_mean([])
        assert "error" in result
        assert result["mean"] is None
    
    def test_std_basic(self):
        """Standardabweichung berechnen."""
        result = calculate_std([2, 4, 4, 4, 5, 5, 7, 9])
        assert "std" in result
        assert result["std"] > 0
        assert "variance" in result
    
    def test_std_single_value(self):
        """Std mit nur einem Wert."""
        result = calculate_std([5])
        assert "error" in result
    
    def test_min_max(self):
        """Min/Max/Range berechnen."""
        result = calculate_min_max([5, 2, 8, 1, 9])
        assert result["min"] == 1
        assert result["max"] == 9
        assert result["range"] == 8
    
    def test_correlation_positive(self):
        """Positive Korrelation (DEC-024: mit Timestamps)."""
        x_ts = [1000, 2000, 3000, 4000, 5000]
        x = [1, 2, 3, 4, 5]
        y_ts = [1000, 2000, 3000, 4000, 5000]
        y = [2, 4, 6, 8, 10]  # Perfekt korreliert
        result = calculate_correlation_timeseries(x_ts, x, y_ts, y)
        assert result["r"] == pytest.approx(1.0, abs=0.001)
        assert result["strength"] == "stark"
        assert result["direction"] == "positiv"

    def test_correlation_negative(self):
        """Negative Korrelation (DEC-024: mit Timestamps)."""
        x_ts = [1000, 2000, 3000, 4000, 5000]
        x = [1, 2, 3, 4, 5]
        y_ts = [1000, 2000, 3000, 4000, 5000]
        y = [10, 8, 6, 4, 2]  # Perfekt negativ korreliert
        result = calculate_correlation_timeseries(x_ts, x, y_ts, y)
        assert result["r"] == pytest.approx(-1.0, abs=0.001)
        assert result["direction"] == "negativ"

    def test_correlation_no_correlation(self):
        """Keine Korrelation (DEC-024: mit Timestamps)."""
        x_ts = [1000, 2000, 3000, 4000, 5000]
        x = [1, 2, 3, 4, 5]
        y_ts = [1000, 2000, 3000, 4000, 5000]
        y = [5, 2, 8, 1, 9]  # Zufällig
        result = calculate_correlation_timeseries(x_ts, x, y_ts, y)
        assert abs(result["r"]) < 0.7  # Nicht stark korreliert

    def test_correlation_unequal_length(self):
        """Korrelation mit ungleichen Längen - DEC-024 merge_asof macht das möglich!"""
        x_ts = [1000, 2000, 3000]
        x = [1, 2, 3]
        y_ts = [1010, 2005]  # Nur 2 Punkte, leicht versetzt
        y = [1.1, 2.0]
        result = calculate_correlation_timeseries(x_ts, x, y_ts, y, tolerance_ms=100)
        # Sollte 3 Matches finden (alle x-Punkte matchen zu nächstem y)
        assert result.get("n_matched") >= 2
        assert result.get("r") is not None  # Kein Error mehr!
    
    def test_linear_trend_rising(self):
        """Steigender Trend."""
        values = [10, 12, 14, 16, 18, 20]
        result = calculate_linear_trend(values)
        assert result["slope"] > 0
        assert result["trend"] == "steigend"
    
    def test_linear_trend_falling(self):
        """Fallender Trend."""
        values = [20, 18, 16, 14, 12, 10]
        result = calculate_linear_trend(values)
        assert result["slope"] < 0
        assert result["trend"] == "fallend"
    
    def test_linear_trend_stable(self):
        """Stabiler Trend."""
        values = [10, 10.001, 9.999, 10, 10.0005]
        result = calculate_linear_trend(values)
        assert result["trend"] == "stabil"
    
    def test_moving_average(self):
        """Gleitender Durchschnitt."""
        values = [1, 2, 3, 4, 5, 6, 7]
        result = calculate_moving_average(values, window=3)
        expected = [2, 3, 4, 5, 6]
        # Floating-Point-Vergleich mit Toleranz
        for actual, exp in zip(result["smoothed"], expected):
            assert actual == pytest.approx(exp, abs=0.0001)
        assert result["smoothed_count"] == 5
    
    def test_moving_average_window_too_large(self):
        """Window größer als Daten."""
        result = calculate_moving_average([1, 2, 3], window=5)
        assert "error" in result
    
    def test_percentiles_default(self):
        """Quartile (default)."""
        values = list(range(1, 101))  # 1-100
        result = calculate_percentiles(values)
        assert result["p25"] == pytest.approx(25.75, abs=1)
        assert result["p50"] == pytest.approx(50.5, abs=1)
        assert result["p75"] == pytest.approx(75.25, abs=1)
    
    def test_percentiles_custom(self):
        """Benutzerdefinierte Perzentile."""
        values = list(range(1, 101))
        result = calculate_percentiles(values, p=[10, 90])
        assert "p10" in result
        assert "p90" in result
    
    def test_anomaly_detection_with_outliers(self):
        """Ausreißererkennung."""
        # Normale Werte + 2 Ausreißer
        values = [25 + random.gauss(0, 1) for _ in range(50)]
        values[10] = 50  # Ausreißer (weit über Mittelwert)
        values[30] = 0   # Ausreißer (weit unter Mittelwert)
        
        result = detect_anomalies(values, sigma_threshold=2.0)
        assert result["anomalies_count"] >= 2
        assert 10 in result["anomaly_indices"]
        assert 30 in result["anomaly_indices"]
    
    def test_anomaly_detection_no_outliers(self):
        """Keine Ausreißer."""
        values = [25.0] * 50  # Alle identisch
        result = detect_anomalies(values)
        assert result["anomalies_count"] == 0


# =============================================================================
# INTEGRATION TEST: Stats MCP Server
# =============================================================================

class TestStatsMCPServer:
    """Tests für den Stats MCP Server."""
    
    @pytest.mark.asyncio
    async def test_mcp_server_tools_available(self):
        """Prüft ob alle 8 Tools verfügbar sind."""
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        
        server_path = PROJECT_ROOT / "mcp_servers" / "stats_server.py"
        server_params = StdioServerParameters(
            command="python",
            args=[str(server_path)],
        )
        
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                
                tool_names = [t.name for t in tools.tools]
                print(f"Verfügbare Tools: {tool_names}")
                
                expected_tools = [
                    "mean", "std", "min_max", "correlation_timeseries",
                    "linear_trend", "moving_average", "percentiles", "anomaly_detection"
                ]

                for tool in expected_tools:
                    assert tool in tool_names, f"Tool '{tool}' fehlt!"

                assert len(tool_names) == 8, f"Erwartet 8 Tools, gefunden: {len(tool_names)}"
    
    @pytest.mark.asyncio
    async def test_mcp_mean_tool(self):
        """Test des mean Tools über MCP."""
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        import json
        
        server_path = PROJECT_ROOT / "mcp_servers" / "stats_server.py"
        server_params = StdioServerParameters(
            command="python",
            args=[str(server_path)],
        )
        
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                
                result = await session.call_tool(
                    "mean",
                    arguments={"values": [1, 2, 3, 4, 5]}
                )
                
                # Result ist eine Liste von Content-Blöcken
                assert len(result.content) > 0
                text_content = result.content[0].text
                parsed = json.loads(text_content)
                
                assert parsed["mean"] == 3.0
                assert parsed["count"] == 5


# =============================================================================
# END-TO-END TEST: Stats Agent
# =============================================================================

class TestStatsAgent:
    """End-to-End Tests für den Stats Agent."""
    
    @pytest.mark.asyncio
    async def test_agent_mean_calculation(self):
        """Agent berechnet Durchschnitt."""
        from agents.stats_agent import run_stats_agent
        from agents.state import AgentState
        from langchain_core.messages import HumanMessage, AIMessage
        
        # Simulierte Daten
        test_data = {
            "temperature": [
                {"value": "25.0", "timestamp": 1000},
                {"value": "26.0", "timestamp": 2000},
                {"value": "27.0", "timestamp": 3000},
            ]
        }
        
        state = AgentState(
            messages=[HumanMessage(content="Was ist die Durchschnittstemperatur?")],
            data=test_data,
            data_summary="3 Temperaturwerte",
        )
        
        result = await run_stats_agent(state)
        
        # Prüfe dass keine Fehler
        assert result.get("error") is None
        
        # Prüfe dass Statistiken berechnet wurden
        assert result.get("statistics") is not None or result.get("statistics_summary")
        
        # Prüfe dass Agent geantwortet hat
        ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
        assert len(ai_messages) > 0
    
    @pytest.mark.asyncio
    async def test_agent_no_data_error(self):
        """Agent ohne Daten gibt Fehler."""
        from agents.stats_agent import run_stats_agent
        from agents.state import AgentState
        from langchain_core.messages import HumanMessage
        
        state = AgentState(
            messages=[HumanMessage(content="Berechne Statistik")],
            data=None,  # Keine Daten!
        )
        
        result = await run_stats_agent(state)
        
        assert result.get("error") == "no_data"


# =============================================================================
# RUN TESTS
# =============================================================================

def run_unit_tests():
    """Führt nur die schnellen Unit-Tests aus."""
    print("\n" + "="*60)
    print("🧪 Stats Functions Unit Tests")
    print("="*60)
    
    test = TestStatsFunctions()
    
    tests = [
        ("mean_basic", test.test_mean_basic),
        ("mean_empty", test.test_mean_empty),
        ("std_basic", test.test_std_basic),
        ("min_max", test.test_min_max),
        ("correlation_positive", test.test_correlation_positive),
        ("correlation_negative", test.test_correlation_negative),
        ("linear_trend_rising", test.test_linear_trend_rising),
        ("linear_trend_falling", test.test_linear_trend_falling),
        ("moving_average", test.test_moving_average),
        ("percentiles_default", test.test_percentiles_default),
        ("anomaly_detection", test.test_anomaly_detection_with_outliers),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        try:
            test_func()
            print(f"  ✅ {name}")
            passed += 1
        except Exception as e:
            print(f"  ❌ {name}: {e}")
            failed += 1
    
    print(f"\n📊 Ergebnis: {passed}/{passed+failed} Tests bestanden")
    return failed == 0


async def run_integration_tests():
    """Führt die Integration Tests aus (MCP Server)."""
    print("\n" + "="*60)
    print("🔌 Stats MCP Server Integration Tests")
    print("="*60)
    
    test = TestStatsMCPServer()
    
    try:
        print("  Testing MCP Server tools...")
        await test.test_mcp_server_tools_available()
        print("  ✅ 8 Tools verfügbar")
        
        print("  Testing mean tool...")
        await test.test_mcp_mean_tool()
        print("  ✅ mean Tool funktioniert")
        
        return True
    except Exception as e:
        print(f"  ❌ Fehler: {e}")
        return False


if __name__ == "__main__":
    import sys
    
    # Unit Tests (schnell)
    unit_ok = run_unit_tests()
    
    # Integration Tests (braucht MCP Server)
    if "--integration" in sys.argv or "--all" in sys.argv:
        integration_ok = asyncio.run(run_integration_tests())
    else:
        print("\n💡 Für Integration Tests: python test_stats_agent.py --integration")
        integration_ok = True
    
    # End-to-End Tests (braucht Anthropic API)
    if "--e2e" in sys.argv or "--all" in sys.argv:
        print("\n" + "="*60)
        print("🤖 Stats Agent E2E Tests")
        print("="*60)
        
        async def run_e2e():
            test = TestStatsAgent()
            try:
                await test.test_agent_mean_calculation()
                print("  ✅ Agent Mean Calculation")
                await test.test_agent_no_data_error()
                print("  ✅ Agent No Data Error Handling")
                return True
            except Exception as e:
                print(f"  ❌ E2E Fehler: {e}")
                return False
        
        e2e_ok = asyncio.run(run_e2e())
    else:
        print("\n💡 Für E2E Tests: python test_stats_agent.py --e2e")
        e2e_ok = True
    
    # Summary
    print("\n" + "="*60)
    if unit_ok and integration_ok and e2e_ok:
        print("✅ Alle Tests bestanden!")
    else:
        print("❌ Einige Tests fehlgeschlagen")
        sys.exit(1)
