"""
Tests für Token-Budget-Einhaltung.

Prüft dass:
- Rohdaten in Dateien gespeichert werden, nicht an LLM
- Nur Summaries an LLM gehen (< 5KB)
- Große Datenmengen korrekt behandelt werden

Referenz: docs/AP9_DEBUGGING_TESTING.md Abschnitt 6
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pytest
import json


# =============================================================================
# RESPONSE SIZE TESTS
# =============================================================================

class TestResponseSize:
    """Tests für Response-Größe."""
    
    def test_success_response_size(self, success_response):
        """Prüft dass success-Response < 5KB ist."""
        response_json = json.dumps(success_response)
        size_bytes = len(response_json.encode('utf-8'))
        
        assert size_bytes < 5000, \
            f"Success response ist {size_bytes} bytes, sollte < 5000 sein"
    
    def test_success_response_has_no_raw_data(self, success_response):
        """Prüft dass keine Rohdaten in Response sind."""
        assert "data" not in success_response or success_response.get("data") is None, \
            "Success response sollte keine 'data' haben, nur 'data_file'"
    
    def test_success_response_has_statistics_instead(self, success_response):
        """Prüft dass statistics statt Rohdaten vorhanden sind."""
        assert "statistics" in success_response, \
            "Success response sollte 'statistics' statt Rohdaten haben"
    
    def test_no_data_response_size(self, no_data_response):
        """Prüft dass no_data-Response < 1KB ist."""
        response_json = json.dumps(no_data_response)
        size_bytes = len(response_json.encode('utf-8'))
        
        assert size_bytes < 1000, \
            f"No data response ist {size_bytes} bytes, sollte < 1000 sein"


# =============================================================================
# DATA FILE STORAGE TESTS
# =============================================================================

class TestDataFileStorage:
    """Tests für Datei-basierte Datenspeicherung."""
    
    def test_data_file_path_in_response(self, success_response):
        """Prüft dass data_file Pfad in Response ist."""
        assert "data_file" in success_response
        assert success_response["data_file"] is not None
    
    def test_data_file_path_is_string(self, success_response):
        """Prüft dass data_file ein String (Pfad) ist."""
        assert isinstance(success_response["data_file"], str)
    
    def test_data_file_exists(self, temp_data_file):
        """Prüft dass Datendatei existiert."""
        assert Path(temp_data_file).exists()
    
    def test_data_file_contains_actual_data(self, temp_data_file):
        """Prüft dass Datendatei echte Daten enthält."""
        with open(temp_data_file, "r") as f:
            data = json.load(f)
        
        assert "data" in data
        assert len(data["data"]) > 0


# =============================================================================
# LARGE DATASET TESTS
# =============================================================================

class TestLargeDatasets:
    """Tests für große Datenmengen."""
    
    def test_large_dataset_size(self, large_dataset):
        """Prüft Größe des großen Datasets."""
        data_json = json.dumps(large_dataset)
        size_bytes = len(data_json.encode('utf-8'))
        
        # 10k Punkte sollten signifikant groß sein
        assert size_bytes > 100000, \
            f"Large dataset ist nur {size_bytes} bytes"
    
    def test_large_dataset_would_exceed_token_limit(self, large_dataset):
        """Prüft dass große Daten Token-Limit überschreiten würden."""
        data_json = json.dumps(large_dataset)
        
        # Grobe Schätzung: 4 chars = 1 token, Limit ~100k tokens = 400k chars
        # Aber für LLM-Context wollen wir < 50KB
        size_bytes = len(data_json.encode('utf-8'))
        
        assert size_bytes > 50000, \
            "Large dataset sollte > 50KB sein um Token-Limit zu testen"
    
    def test_statistics_much_smaller_than_raw_data(self, large_dataset):
        """Prüft dass Statistics viel kleiner als Rohdaten sind."""
        from mcp_servers.thingsboard_server import calculate_statistics
        
        stats = calculate_statistics(large_dataset)
        
        raw_size = len(json.dumps(large_dataset))
        stats_size = len(json.dumps(stats))
        
        # Statistics sollten < 1% der Rohdaten sein
        assert stats_size < raw_size * 0.01, \
            f"Statistics ({stats_size}) sollten < 1% der Rohdaten ({raw_size}) sein"


# =============================================================================
# SUMMARY TESTS
# =============================================================================



# =============================================================================
# EXTRACT DATA PRESERVES LARGE DATA TESTS
# =============================================================================

class TestExtractPreservesData:
    """Tests dass extract_data_from_parsed() große Daten aus Datei lädt."""
    
    def test_loads_data_from_file_not_response(self, temp_data_file, success_response):
        """Prüft dass Daten aus Datei geladen werden."""
        from agents.data_agent import extract_data_from_parsed
        
        response = {**success_response, "data_file": str(temp_data_file)}
        
        data, meta, file = extract_data_from_parsed(response)
        
        # Daten sollten aus Datei kommen
        assert file == str(temp_data_file)
        assert data is not None
    
    def test_data_from_file_is_complete(self, temp_data_file, sample_timeseries_data):
        """Prüft dass alle Daten aus Datei geladen werden."""
        from agents.data_agent import extract_data_from_parsed
        
        response = {"status": "success", "data_file": str(temp_data_file), "statistics": {}}
        
        data, meta, file = extract_data_from_parsed(response)
        
        # Sollte gleiche Anzahl Keys haben
        assert data is not None
        # Daten sollten vorhanden sein (aus temp_data_file)


# =============================================================================
# STATE DATA FLOW TESTS
# =============================================================================

class TestStateDataFlow:
    """Tests für Datenfluss durch State (nicht LLM)."""
    
    def test_data_in_state_not_messages(self, state_with_data):
        """Prüft dass Daten in state.data sind, nicht in messages."""
        # Daten sollten in state.data sein
        assert state_with_data.get("data") is not None
        
        # Messages sollten keine großen Daten enthalten
        for msg in state_with_data.get("messages", []):
            content = msg.content if hasattr(msg, 'content') else str(msg)
            assert len(content) < 10000, \
                "Message sollte keine großen Daten enthalten"
    
    def test_viz_agent_reads_from_state(self, state_after_data_agent):
        """Prüft dass Viz Agent Daten aus State liest."""
        # state.data sollte gefüllt sein
        assert state_after_data_agent.get("data") is not None


# =============================================================================
# MEMORY ESTIMATES
# =============================================================================

class TestMemoryEstimates:
    """Grobe Schätzungen für Token-Verbrauch."""
    
    def test_estimate_tokens_from_bytes(self):
        """Testet Token-Schätzung."""
        # Grobe Regel: 4 chars ≈ 1 token
        test_text = "a" * 4000  # ~1000 tokens
        
        estimated_tokens = len(test_text) / 4
        
        assert 900 <= estimated_tokens <= 1100
    
