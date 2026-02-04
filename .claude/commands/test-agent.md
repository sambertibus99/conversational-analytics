---
allowed-tools: Bash(python:*)
description: "Tests für einzelne Agents oder das gesamte System ausführen"
---

# Agent Tests ausführen

Führe Tests für den angegebenen Agent aus. Nutze IMMER `run_tests.py` (vermeidet ROS2-Pfad-Konflikte).

## Argument: $ARGUMENTS

## Mapping

| Argument | Befehl |
|----------|--------|
| `data` | `python run_tests.py tests/test_data_agent.py -v` |
| `viz` | `python run_tests.py tests/test_viz_agent.py -v` |
| `stats` | `python run_tests.py tests/test_stats_agent.py -v` |
| `graph` | `python run_tests.py tests/test_graph.py -v` |
| `all` | `python run_tests.py -v` |
| `integration` | `python run_tests.py --integration -v` |
| `coverage` | `python run_tests.py --coverage` |

## Ablauf

1. Ermittle aus dem Argument welcher Befehl ausgeführt werden soll
2. Falls kein Argument angegeben: führe `all` aus (Unit Tests)
3. Führe den Befehl aus dem Projektverzeichnis aus
4. Melde das Ergebnis: Anzahl bestanden/fehlgeschlagen, ggf. Fehlerdetails

## Hinweise

- `integration` Tests brauchen eine laufende ThingsBoard-Instanz
- Bei Fehlern: Zeige den relevanten Fehler-Output, nicht den gesamten Log
- Wenn ein unbekanntes Argument kommt, zeige die verfügbaren Optionen
