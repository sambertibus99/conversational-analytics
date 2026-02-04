# Claude Code Features

> **Eingerichtet:** 04. Februar 2026

---

## 1. Permissions

Claude Code darf folgende Befehle ohne Bestätigung ausführen:

| Befehl | Zweck |
|--------|-------|
| `python *` | Scripts, Agents standalone |
| `python -m pytest *` | Tests via pytest |
| `pip *` | Pakete installieren |
| `chainlit *` | App starten |
| `git add/commit/push/diff/log/status` | Git-Operationen |

Konfiguration: `.claude/settings.local.json`

---

## 2. Post-Edit Hook: XML-Prompt-Validierung (DEC-015)

Wenn eine Datei in `prompts/*.py` editiert wird, prüft ein Hook automatisch die XML-Tag-Struktur.

**Was wird geprüft:**

| Typ | Tags | Verhalten |
|-----|------|-----------|
| Pflicht | `<role>`, `<task>` | Fehler wenn fehlend |
| Empfohlen | `<tools>`, `<examples>` | Warnung wenn fehlend |
| Balance | alle strukturellen Tags | Fehler wenn nicht geschlossen |

**Beispiel-Output:**
```
DEC-015 OK: data_agent_prompt.py - Alle XML-Tags korrekt.
```

```
DEC-015 Validierung fuer respond_prompt.py:
  - FEHLER: Pflicht-Tag <task> fehlt (DEC-015)
  - WARNUNG: Empfohlener Tag <tools> fehlt
```

Dateien ausserhalb von `prompts/` und `__init__.py` werden ignoriert.

Konfiguration: `.claude/hooks.json` + `.claude/hooks/validate_xml_prompts.py`

---

## 3. Decisions Agent

Ein proaktiver Architektur-Berater der alle 24 DEC-Patterns kennt.

**Wann wird er genutzt:**
- Neuer Agent wird hinzugefuegt
- Prompt-Struktur aendert sich
- Datenfluss zwischen Agents wird angepasst
- Neues Tool oder MCP-Server wird integriert
- Neue Patterns entstehen

**Antwort-Format:**
1. Relevante DECs mit Erklaerung
2. Konkrete Empfehlung
3. Konsistenz-Pruefung gegen bestehende DECs
4. Ob eine neue DEC noetig ist

Konfiguration: `.claude/agents/decisions.md`

---

## 4. Slash Commands

### `/new-decision`

Dokumentiert eine neue Design-Entscheidung in `docs/DECISIONS.md`.

**Ablauf:**
1. Liest DECISIONS.md, findet die naechste DEC-Nummer
2. Fragt nach: Titel, Problem, Kontext, Entscheidung, Pattern, Begruendung
3. Fuegt den Eintrag ein (vor "IDEEN")
4. Aktualisiert die Schnell-Referenz-Tabelle
5. Aktualisiert die Aenderungshistorie
6. Prueft ob CLAUDE.md aktualisiert werden muss

**Beispiel:** `/new-decision`

---

### `/test-agent`

Fuehrt Tests fuer einzelne Agents oder das gesamte System aus.

| Argument | Was wird getestet |
|----------|-------------------|
| `data` | Data Agent |
| `viz` | Viz Agent |
| `stats` | Stats Agent |
| `graph` | Graph/Orchestrierung |
| `all` | Alle Unit Tests |
| `integration` | Alle Tests inkl. Integration |
| `coverage` | Unit Tests mit Coverage-Report |

**Beispiel:** `/test-agent stats`

Nutzt immer `run_tests.py` um ROS2-Pfad-Konflikte zu vermeiden.

---

### `/update-status`

Fuegt einen neuen Session-Eintrag in `docs/04_AKTUELLER_STAND.md` hinzu.

**Ablauf:**
1. Ermittelt die naechste Session-Nummer
2. Fragt nach: Thema, Problem, Loesung, Dateien, Test-Ergebnis
3. Fuegt Session-Eintrag ein (neueste zuerst)
4. Aktualisiert das "Letzte Aktualisierung" Datum

**Beispiel:** `/update-status`

---

## 5. Plugins

### context7 (MCP-Server)

Holt aktuelle Bibliotheks-Dokumentation in Echtzeit. Loest das Problem veralteter Trainingsdaten.

**Tools:**

| Tool | Funktion |
|------|----------|
| `resolve-library-id` | Findet Context7-ID einer Bibliothek |
| `query-docs` | Holt aktuelle Doku fuer eine Bibliothek |

**Nutzung:** "use context7" zur Frage hinzufuegen, oder Claude nutzt es automatisch.

**Beispiel:** "Wie funktioniert StateGraph in LangGraph? use context7"

---

### /code-review (eingebaut)

Automatisiertes PR-Review mit 4 parallelen Agents.

**Voraussetzung:** `gh` CLI installiert und authentifiziert.

**Agents:**
1. CLAUDE.md Compliance-Check
2. Bug-Erkennung im Diff
3. Git-History-Kontext-Analyse
4. Code-Comment-Pruefung

**Confidence-Scoring:** Nur Findings ab Score 80/100 werden gemeldet.

**Nutzung:**
- `/code-review` — Output im Terminal
- `/code-review --comment` — Postet Review als PR-Kommentar

---

## Dateistruktur

```
.claude/
  settings.local.json          # Permissions
  hooks.json                   # Hook-Konfiguration
  hooks/
    validate_xml_prompts.py    # XML-Validierungsskript
  agents/
    decisions.md               # Decisions Agent
  commands/
    new-decision.md            # /new-decision Skill
    test-agent.md              # /test-agent Skill
    update-status.md           # /update-status Skill
```
