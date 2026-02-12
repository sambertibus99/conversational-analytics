---
allowed-tools: Read, Write, Glob, Grep, Bash(git status:*), Bash(git log:*), Bash(git diff:*), Bash(git branch:*), Bash(date:*), Bash(mkdir:*)
description: "Session-Kontext sichern für spätere Wiederaufnahme (vor Kompaktierung oder Sessionwechsel)"
---

# Session-Kontext sichern

Du erstellst ein strukturiertes Handoff-Dokument das den aktuellen Arbeitskontext konserviert. Das Dokument soll einer neuen Session ermöglichen, nahtlos weiterzuarbeiten.

## Ablauf

### 1. Git-State automatisch sammeln

Führe folgende Befehle aus und merke dir die Ergebnisse:

```bash
git branch --show-current
git log --oneline -5
git diff --stat
git status --short
```

### 2. User nach Kontext fragen

Frage den User nach folgenden Informationen (nutze AskUserQuestion mit Freitext-Optionen):

- **Thema/Titel**: Kurzer Name für die Session (z.B. "DEC-028 Data Agent Gatekeeper")
- **Was war das Ziel?**: Was sollte erreicht werden?
- **Was hat funktioniert / was nicht?**: Gescheiterte Ansätze sind besonders wertvoll
- **Nächste Schritte**: Was muss als nächstes passiert?

### 3. Aus dem Gesprächskontext extrahieren

Analysiere die bisherige Conversation und extrahiere:

- **Getroffene Entscheidungen** mit Begründung (warum X statt Y)
- **Geänderte Code-Stellen** mit kurzem Kontext (was und warum)
- **Offene Probleme / Blocker** die noch nicht gelöst sind
- **Erkenntnisse** die für die Weiterarbeit wichtig sind

### 4. Handoff-Dokument generieren

Erstelle die Datei `.claude/sessions/<DATUM>-<thema>.md` mit folgendem Format:

- `<DATUM>`: Aktuelles Datum/Uhrzeit im Format `YYYY-MM-DD-HHMM` (via `date +%Y-%m-%d-%H%M`)
- `<thema>`: Thema in Kleinbuchstaben, Bindestriche statt Leerzeichen, keine Sonderzeichen

```markdown
# Session: <Titel>
> <Datum> <Uhrzeit> | Branch: <branch> | Model: <model>

## Ziel
<Was sollte erreicht werden?>

## Status: <in_progress | completed | blocked>

## Entscheidungen
- <Entscheidung 1>: <Begründung>
- <Entscheidung 2>: <Begründung>

## Geänderte Dateien
- `<pfad>` — <was und warum>
- `<pfad>` — <was und warum>

## Gescheiterte Ansätze
- ❌ <Ansatz>: <Warum gescheitert>

## Erkenntnisse
- <Wichtige Erkenntnis für Weiterarbeit>

## Nächste Schritte
1. [ ] <Priorität HIGH> <Aktion>
2. [ ] <Priorität MED> <Aktion>
3. [ ] <Priorität LOW> <Aktion>

## Blocker
- <Blocker falls vorhanden, sonst Sektion weglassen>

## Git-State
Branch: <branch>
Letzte Commits:
- <hash> <message>
- <hash> <message>

Uncommitted:
- <git status output>
```

### 5. Bestätigung

Melde dem User:
- Dateipfad der gespeicherten Session
- Geschätzte Token-Größe des Dokuments
- Hinweis: `Nächste Session starten mit: /session-resume <dateiname>`

## Richtlinien

- **Kompakt halten**: Ziel sind 500–1500 Tokens. Fokus auf "Warum" statt "Was"
- **Keine Datei-Inhalte**: Nur Pfade + Kontext-Beschreibung, nie ganzen Code kopieren
- **Gescheiterte Ansätze sind Gold**: Verhindert dass die nächste Session dieselben Fehler macht
- **Entscheidungen mit Begründung**: Nicht nur "wir nutzen X" sondern "wir nutzen X weil Y, nicht Z wegen W"
- **Alles auf Deutsch**
- Leere Sektionen (z.B. Blocker wenn keine vorhanden) weglassen
