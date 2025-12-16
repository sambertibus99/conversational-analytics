"""
Test: Projekt-Setup korrekt?
"""

import sys
from pathlib import Path

# Projektroot zum Python-Pfad hinzufügen
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def test_imports():
    """Teste ob alle wichtigen Packages importierbar sind."""
    import langgraph
    print(f"✅ LangGraph OK")
    
    import langchain_anthropic
    print(f"✅ LangChain Anthropic OK")
    
    import chainlit
    print(f"✅ Chainlit OK")
    
    import httpx
    print(f"✅ HTTPX {httpx.__version__}")
    
    import plotly
    print(f"✅ Plotly {plotly.__version__}")
    
    import numpy
    print(f"✅ NumPy {numpy.__version__}")
    
    import pandas
    print(f"✅ Pandas {pandas.__version__}")
    
    import mcp
    print(f"✅ MCP OK")


def test_config():
    """Teste ob Config geladen wird."""
    from config.settings import (
        THINGSBOARD_URL,
        ANTHROPIC_API_KEY,
        TELEMETRY_KEYS,
    )
    
    assert THINGSBOARD_URL is not None, "THINGSBOARD_URL nicht gesetzt"
    print(f"✅ ThingsBoard URL: {THINGSBOARD_URL}")
    
    if ANTHROPIC_API_KEY:
        print(f"✅ Anthropic API Key: {ANTHROPIC_API_KEY[:20]}...")
    else:
        print(f"⚠️  Anthropic API Key: NICHT GESETZT (später nachtragen)")
    
    assert len(TELEMETRY_KEYS) > 0, "Keine Telemetry Keys definiert"
    print(f"✅ {len(TELEMETRY_KEYS)} Telemetry Keys definiert")


def test_project_structure():
    """Teste ob alle Ordner existieren."""
    required_dirs = [
        "agents",
        "mcp_servers", 
        "tools",
        "prompts",
        "evaluation",
        "tests",
        "config",
    ]
    
    for dir_name in required_dirs:
        path = PROJECT_ROOT / dir_name
        assert path.exists(), f"Ordner {dir_name} fehlt"
        assert (path / "__init__.py").exists(), f"__init__.py in {dir_name} fehlt"
        print(f"✅ {dir_name}/ OK")


if __name__ == "__main__":
    print("\n🧪 SETUP-TESTS\n" + "="*40)
    
    print("\n📦 Package-Imports:")
    test_imports()
    
    print("\n⚙️ Konfiguration:")
    test_config()
    
    print("\n📁 Projektstruktur:")
    test_project_structure()
    
    print("\n" + "="*40)
    print("✅ ALLE TESTS BESTANDEN!")