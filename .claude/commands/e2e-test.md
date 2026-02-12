---
allowed-tools: Bash(python:*), Bash(npx:*), Bash(curl:*), Bash(kill:*), Bash(lsof:*), Bash(cat:*), Bash(tail:*)
description: "E2E-Tests über Playwright-Browser gegen die Chainlit-App ausführen"
---

# E2E-Tests ausführen

Führe End-to-End Tests gegen die laufende Chainlit-App aus. Nutzt Playwright MCP für Browser-Interaktion.

## Argument: $ARGUMENTS

## Mapping

| Argument | Tests | Beschreibung |
|----------|-------|--------------|
| `einfach` (default) | E1-E5 | Einzelwerte, einfache Abfragen |
| `mittel` | M1-M5 | Mehrere Keys, Vergleiche, Charts |
| `komplex` | K1-K5 | Statistik, Korrelation, Multi-Step |
| `abstention` | A1-A5 | Ungültige Anfragen (System soll ablehnen) |
| `all` | Alle 20 | Komplette Testsuite |
| `E1`, `M3`, `K5` etc. | Einzelner Test | Spezifischer Test per ID |

## Ablauf

1. Ermittle aus dem Argument welche Tests ausgeführt werden sollen
2. Falls kein Argument angegeben: führe `einfach` aus
3. Delegiere die Ausführung an den **e2e-tester** Agent mit folgender Anweisung:

> Führe E2E-Tests für `<argument>` aus. Folge dem kompletten Ablauf in deiner Anleitung:
> 1. App starten via `python evaluation/e2e_runner.py start`
> 2. Health-Check via `python evaluation/e2e_runner.py health-check`
> 3. Tests laden via `python evaluation/e2e_runner.py list-tests <argument>`
> 4. Jeden Test im Browser ausführen (Playwright MCP)
> 5. Assertions prüfen und Report erstellen
> 6. App stoppen via `python evaluation/e2e_runner.py stop`

4. Melde das Ergebnis: Anzahl bestanden/fehlgeschlagen, Report-Pfad

## Hinweise

- **Voraussetzung:** ThingsBoard muss laufen (`http://localhost:8080`)
- **Voraussetzung:** Playwright Chromium muss installiert sein (`npx playwright install chromium`)
- **Timeout:** 120 Sekunden pro Test, Gesamtlaufzeit kann bei `all` bis zu 40 Minuten betragen
- **Reports:** Werden in `evaluation/results/` gespeichert
- Bei Fehlern: App-Log unter `/tmp/chainlit_e2e.log` prüfen
