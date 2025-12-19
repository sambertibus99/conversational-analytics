# Design-Dokumentation

> **Zweck:** Dokumentation aller Architektur- und Design-Entscheidungen
> **Nutzung:** Referenz für Masterarbeit (Kapitel 4: Architektur)
> **Stand:** Dezember 2025

---

## 📋 Übersicht

| Komponente | AP | Datei | Status |
|------------|-----|-------|--------|
| [ThingsBoard MCP Server](thingsboard_mcp_server.md) | AP1 | `mcp_servers/thingsboard_server.py` | ⏸️ Ausstehend |
| [Data Agent](data_agent.md) | AP2 | `agents/data_agent.py` | ⏸️ Ausstehend |
| [Chart MCP Server](chart_mcp_server.md) | AP3 | `@antv/mcp-server-chart` | ⏸️ Ausstehend |
| [Viz Agent](viz_agent.md) | AP4 | `agents/viz_agent.py` | ⏸️ Ausstehend |
| [Stats Agent](stats_agent.md) | AP5 | `agents/stats_agent.py` | ⏸️ Ausstehend |
| [Supervisor](supervisor.md) | AP6 | `agents/supervisor.py` | ⏸️ Ausstehend |

**Status-Legende:**
- ⏸️ Ausstehend - Noch nicht reviewt
- 🔄 In Bearbeitung - Review läuft
- ✅ Abgeschlossen - Review fertig, getestet

---

## 🔄 Review-Methodik

Für jede Komponente durchlaufen wir folgenden Prozess:

### 1. VERSTEHEN
- Was macht die Komponente?
- Input → Processing → Output
- Wie ist sie implementiert?

### 2. EINORDNEN
- Wo im Gesamtsystem?
- Abhängigkeiten zu anderen Komponenten?
- Welche Anforderungen erfüllt sie?

### 3. BEWERTEN
- Was funktioniert gut?
- Was sind bekannte Probleme?
- Was fehlt?

### 4. ALTERNATIVEN
- Option A mit Pro/Contra
- Option B mit Pro/Contra
- Empfehlung mit Begründung

### 5. ENTSCHEIDEN
- Auswahl treffen
- Begründung dokumentieren (wichtig für Masterarbeit!)

### 6. DOKUMENTIEREN
- Entscheidung in Design-Doc festhalten
- Format für Masterarbeit nutzbar

### 7. IMPLEMENTIEREN
- Nur was entschieden wurde
- Code-Änderungen dokumentieren

### 8. TESTEN
- Komponenten-Test: Funktioniert isoliert?
- Integrations-Test: Funktioniert im Gesamtsystem?
- Ergebnis dokumentieren

---

## 📁 Dateien

```
docs/design/
├── README.md                      # Diese Datei
├── _template.md                   # Vorlage für neue Komponenten
├── thingsboard_mcp_server.md      # AP1
├── data_agent.md                  # AP2
├── chart_mcp_server.md            # AP3
├── viz_agent.md                   # AP4
├── stats_agent.md                 # AP5
└── supervisor.md                  # AP6
```

---

## 🎯 Ziel

Diese Dokumentation dient drei Zwecken:

1. **Verständnis** - Jede Architekturentscheidung ist nachvollziehbar
2. **Masterarbeit** - Direkter Input für Kapitel "Architektur" und "Implementierung"
3. **Wartbarkeit** - Zukünftige Änderungen können auf dokumentierten Entscheidungen aufbauen

---

## 📚 Referenzen für Masterarbeit

Die Design-Entscheidungen können in der Masterarbeit wie folgt referenziert werden:

```latex
Die Entscheidung für [X] wurde aufgrund von [Y] getroffen. 
Alternative Ansätze wie [Z] wurden evaluiert, jedoch aufgrund 
von [Gründen] verworfen (siehe Anhang: Design-Dokumentation).
```

---

## ✏️ Änderungshistorie

| Datum | Änderung |
|-------|----------|
| 2025-12-19 | Initiale Struktur erstellt |
