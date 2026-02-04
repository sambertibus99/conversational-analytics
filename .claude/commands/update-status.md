---
allowed-tools: Read, Edit, Grep
description: "Neuen Session-Eintrag in docs/04_AKTUELLER_STAND.md hinzufügen"
---

# Status-Dokument aktualisieren

Füge einen neuen Session-Eintrag in `docs/04_AKTUELLER_STAND.md` hinzu.

## Ablauf

1. **Lies `docs/04_AKTUELLER_STAND.md`** vollständig
2. **Ermittle die nächste Session-Nummer**: Finde die höchste bestehende Session-Nummer und addiere 1
3. **Frage den User** nach folgenden Informationen:
   - **Thema**: Was wurde in dieser Session gemacht? (z.B. "Prompt Caching DEC-021")
   - **Problem**: Was war das Ausgangsproblem?
   - **Lösung**: Was wurde implementiert?
   - **Geänderte Dateien**: Liste der geänderten Dateien mit kurzer Beschreibung
   - **Test-Ergebnis**: Tests bestanden? Metriken?
   - **Optionale Details**: Erwartete Auswirkung, Gotchas, etc.

4. **Füge den neuen Session-Eintrag ein**:
   - Direkt nach der `## ✅ Abgeschlossene Sessions` Überschrift (neueste zuerst)
   - Format wie die bestehenden Einträge:
     ```
     ### Session N: Thema (DD.MM.YYYY)

     **Problem:** ...

     **Lösung:** ...

     **Änderungen:**
     - `datei.py` — Beschreibung
     - ...

     **Test-Ergebnis / Erwartete Auswirkung:**
     - ...

     ---
     ```

5. **Aktualisiere das Datum** in der Kopfzeile:
   - Ändere `> **Letzte Aktualisierung:** ...` auf das aktuelle Datum
   - Format: `DD. Monat YYYY (Thema)` — z.B. `04. Februar 2026 (Claude Code Setup)`

## Wichtig

- Schreibe alles auf Deutsch
- Halte dich an das bestehende Format
- Neueste Session immer zuerst (nach der Überschrift)
