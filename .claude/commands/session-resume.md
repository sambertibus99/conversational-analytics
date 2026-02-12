---
allowed-tools: Read, Glob, Bash(ls:*)
description: "Gespeicherten Session-Kontext laden und Arbeit fortsetzen"
argument-hint: "[dateiname oder thema]"
---

# Session-Kontext laden

Du lädst den Kontext einer früheren Session um die Arbeit nahtlos fortzusetzen.

## Argument: $ARGUMENTS

## Ablauf

### 1. Session-Datei finden

**Mit Argument:**
- Suche in `.claude/sessions/` nach einer Datei die `$ARGUMENTS` im Namen enthält (Glob-Pattern: `*$ARGUMENTS*`)
- Bei mehreren Treffern: Zeige die Optionen und frage den User welche er meint

**Ohne Argument:**
- Liste alle Dateien in `.claude/sessions/` auf (sortiert nach Datum, neueste zuerst)
- Zeige jede Datei mit: Dateiname, Datum, erste Zeile (= Titel)
- Frage den User welche Session geladen werden soll

### 2. Session-Datei lesen

Lies die ausgewählte Session-Datei vollständig.

### 3. Kontext-Briefing ausgeben

Fasse dem User kurz zusammen:

```
📋 Session geladen: <Titel>
📅 Vom: <Datum>
🔀 Branch: <branch>
📊 Status: <status>

Zusammenfassung:
<2-3 Sätze was gemacht wurde und wo es steht>

Nächste Schritte:
<Priorisierte Liste aus dem Dokument>
```

### 4. Bereitschaft signalisieren

Sage dem User dass du jetzt den vollen Kontext hast und frage womit weitergemacht werden soll. Beziehe dich dabei konkret auf die nächsten Schritte aus dem Dokument.

## Richtlinien

- Wenn `.claude/sessions/` leer ist oder nicht existiert: Sage dem User dass keine Sessions gespeichert sind und verweise auf `/session-save`
- Lies die Session-Datei aufmerksam — die gescheiterten Ansätze und Entscheidungen sind besonders wichtig um Fehler nicht zu wiederholen
- **Alles auf Deutsch**
