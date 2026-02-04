---
allowed-tools: Read, Edit, Glob, Grep
description: "Neue Design-Entscheidung (DEC) in DECISIONS.md dokumentieren"
---

# Neue Design-Entscheidung anlegen

Du dokumentierst eine neue Design-Entscheidung im Projekt.

## Ablauf

1. **Lies `docs/DECISIONS.md`** und finde die höchste bestehende DEC-Nummer
2. Die neue Nummer ist: höchste + 1 (z.B. DEC-024 → DEC-025)
3. **Frage den User** nach folgenden Informationen (nutze AskUserQuestion oder frage direkt):
   - **Titel**: Kurzer Name des Patterns (z.B. "Timeseries Korrelation")
   - **Problem**: Was war das Problem?
   - **Kontext**: Relevanter Kontext (Alternativen, Rahmenbedingungen)
   - **Entscheidung**: Was wurde entschieden? (Fettgedruckt im Dokument)
   - **Pattern**: Code-Beispiel oder Beschreibung des Patterns
   - **Begründung**: Warum diese Lösung?
   - **Anwenden bei**: Wann soll dieses Pattern verwendet werden?
   - **Referenz**: Datei-Referenzen (optional)

4. **Füge den neuen Eintrag ein** in `docs/DECISIONS.md`:
   - Vor der Sektion `## 💡 IDEEN (noch nicht umgesetzt)`
   - Format: Wie die bestehenden DEC-Einträge (mit ### Überschrift, Problem, Kontext, Entscheidung, Pattern, Begründung, Anwenden bei, Referenz)
   - Trenne mit `---` vom vorherigen Eintrag

5. **Aktualisiere die Schnell-Referenz-Tabelle** am Anfang der Datei:
   - Füge eine neue Zeile in die Tabelle ein
   - Format: `| DEC-XXX | Pattern-Name | Problem (kurz) | Lösung (kurz) | Anwenden bei (kurz) |`

6. **Aktualisiere die Änderungshistorie** am Ende der Datei:
   - Füge eine neue Zeile hinzu mit aktuellem Datum
   - Format: `| YYYY-MM-DD | DEC-XXX (Titel) - Kurzbeschreibung |`

7. **Prüfe `CLAUDE.md`**: Wenn das neue Pattern für die tägliche Arbeit kritisch ist, schlage vor es in die "Key Patterns" Tabelle in CLAUDE.md aufzunehmen.

## Wichtig

- Schreibe alles auf Deutsch
- Halte dich an das bestehende Format der anderen DECs
- Frage nach wenn Informationen fehlen — rate nicht
