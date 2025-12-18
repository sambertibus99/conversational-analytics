#!/usr/bin/env python
"""
Test Runner für Conversational Analytics.

Entfernt ROS2-Pfade aus sys.path um Plugin-Konflikte zu vermeiden.

Verwendung:
    python run_tests.py                              # Alle Unit Tests
    python run_tests.py --integration                # Mit Integration Tests  
    python run_tests.py --coverage                   # Mit Coverage Report
    python run_tests.py tests/test_agents -v         # Spezifische Tests
"""

import sys
import os

# ROS-Pfade ENTFERNEN bevor pytest importiert wird!
ros_paths = [p for p in sys.path if '/opt/ros' in p or 'ros2' in p.lower()]
for p in ros_paths:
    sys.path.remove(p)

# Auch aus PYTHONPATH entfernen
if 'PYTHONPATH' in os.environ:
    paths = os.environ['PYTHONPATH'].split(':')
    paths = [p for p in paths if '/opt/ros' not in p and 'ros2' not in p.lower()]
    os.environ['PYTHONPATH'] = ':'.join(paths)

# Jetzt erst pytest importieren
import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent


def main():
    """Führt pytest ohne ROS-Plugins aus."""
    
    args = sys.argv[1:]
    
    # Wenn keine Argumente: Standard Unit Tests
    if not args or args == ['-v']:
        args = [
            "tests/test_mcp_server",
            "tests/test_agents",
            "tests/test_token_budget.py",
            "-v",
        ]
    
    # --integration Flag verarbeiten
    if "--integration" in args:
        args.remove("--integration")
        args = ["tests/", "-v"] + [a for a in args if a not in ["tests/", "-v"]]
    
    # --coverage Flag verarbeiten
    if "--coverage" in args:
        args.remove("--coverage")
        args.extend([
            "--cov=agents",
            "--cov=mcp_servers", 
            "--cov-report=html",
            "--cov-report=term-missing",
        ])
    
    print(f"🧪 Running pytest with args: {args}\n")
    
    # Pytest ausführen
    exit_code = pytest.main(args)
    
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
