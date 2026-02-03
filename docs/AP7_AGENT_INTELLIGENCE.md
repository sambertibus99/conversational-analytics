# AP7: Agent-Intelligenz (LLM-basierte Entscheidungen)

> **Erstellt:** 28. Januar 2026
> **Status:** 🟡 In Planung
> **Ziel:** Agents treffen eigenständige Entscheidungen basierend auf LLM-Intelligenz statt Hardcoding

---

## Motivation

### Problem
Bei der Anfrage "Gibt es einen Zusammenhang zwischen Achspositionen und Momenten?" passierte folgendes:
1. Data Agent holte nur Momente (Positionen waren schon geladen, wurden ignoriert)
2. Stats Agent nutzte Keyword-Mapping → "correlation" nicht erkannt
3. Ergebnis: Gleicher Chart zweimal, keine Korrelationsanalyse

### Ursachen
- **Data Agent:** Prüft nicht welche Daten bereits im State sind
- **Stats Agent:** Keyword-Mapping statt LLM-Intelligenz für Tool-Auswahl
- **Beide:** Hardcoded Logik statt flexible Interpretation

### Ziel
- Agents interpretieren Queries selbstständig
- Data Agent nutzt Multi-Turn State (lädt nur fehlende Daten)
- Stats Agent bekommt Metadaten und entscheidet selbst über Analyse
- Keine Keyword-Listen, nur Beispiele im Prompt

---

## Recherche-Ergebnisse (Best Practices)

### Single Responsibility für Spezialisten
> "Each agent should have a single, well-defined responsibility."
> — Multi-Agent Systems Best Practices

### Supervisor routet, Spezialist entscheidet
> "The supervisor agent analyzes incoming requests and determines which specialized agents should handle specific tasks."
> — LangGraph Multi-Agent Workflows

**Aber:** Der Supervisor sagt nicht WIE der Spezialist arbeiten soll.

### Context Engineering
> "Context engineering is providing the right information and tools in the right format so the LLM can accomplish a task."
> — LangChain Blog

**Anwendung:** Stats Agent bekommt Metadaten (nicht Rohdaten) für Entscheidungen.

---

## Arbeitspakete

### AP7.1: Data Agent State-Awareness ✅
**Ziel:** Data Agent prüft vor API-Call welche Daten bereits geladen sind.

**Lösung:** Beispiel-basierter Ansatz statt dediziertes Tool (nach Best Practices Recherche)

#### Implementierte Änderungen

1. **`format_existing_datasets_hint()` verbessert** (`agents/data_agent.py`)
   - XML-Format `<loaded_data>` statt Markdown
   - Reichere Infos: Keys, Zeitraum, Einstellungen, Statistik-Preview
   - Beispiel-Output:
   ```xml
   <loaded_data>
   ## torque
   keys: torque_act_a1_nm, torque_act_a2_nm, ...
   zeitraum: 2025-01-22T08:00 - 2025-01-22T17:00
   einstellungen: Durchschnitt alle 10 Minuten
   preview (torque_act_a1_nm): 54 Punkte, min=-2.5, max=12.3, avg=4.8
   </loaded_data>
   ```

2. **Multi-Turn Beispiele im Prompt** (`prompts/data_agent_prompt.py`)
   - 3 Beispiele hinzugefügt:
     - Beispiel 1: Daten schon geladen → keine API-Abfrage
     - Beispiel 2: Korrelation, eine Seite fehlt → nur fehlende laden
     - Beispiel 3: Beide fehlen → beide auf einmal laden

#### Designentscheidung: Beispiele statt Tool
- **Verworfen:** Dediziertes `inspect_loaded_data()` Tool
- **Gewählt:** Beispiel-basierter Ansatz im Prompt
- **Begründung:**
  - Kein Extra-API-Call (Kosten, Latenz)
  - Beispiele skalieren besser als hardcoded Instruktionen
  - LangGraph Best Practice: "Context Engineering" - Agent bekommt Info im Prompt

#### Akzeptanzkriterien
```
Turn 1: "Zeig Achspositionen vom 22. Januar"
→ Lädt axis_act_* ✓

Turn 2: "Gibt es Zusammenhang mit Momenten?"
→ Sieht in <loaded_data>: axis_act_* vorhanden ✓
→ Lädt NUR torque_act_* ✓
→ Kein erneuter Call für Positionen ✓
```

#### Betroffene Dateien
- `agents/data_agent.py` - format_existing_datasets_hint() verbessert
- `prompts/data_agent_prompt.py` - Multi-Turn Beispiele hinzugefügt

---

### AP7.2: Data Agent Query-Interpretation ⬜
**Ziel:** Data Agent versteht selbst welche Daten für eine Query benötigt werden.

#### Tasks
- [ ] Prompt überarbeiten: Beispiele statt Regeln
  ```xml
  <examples>
  Query: "Korrelation zwischen Position und Moment"
  → Benötigt: axis_act_*, torque_act_*
  
  Query: "Durchschnitt der Temperaturen"
  → Benötigt: temperature
  </examples>
  ```
- [ ] Multi-Key Erkennung für Korrelations-Anfragen
- [ ] Tests für verschiedene Query-Typen

#### Akzeptanzkriterien
```
"Zusammenhang zwischen X und Y" → Lädt beide Datensätze
"Vergleiche A mit B" → Lädt beide Datensätze
"Zeig mir X" → Lädt nur X
```

#### Betroffene Dateien
- `prompts/data_agent_prompt.py`
- `tests/test_data_agent.py`

---

### AP7.3: Stats Agent Metadaten-Schema ⬜
**Ziel:** Stats Agent bekommt strukturierte Metadaten statt Rohdaten für Entscheidungen.

#### Tasks
- [ ] Metadaten-Schema definieren:
  ```python
  {
      "available_datasets": [
          {
              "key": "axis_act_a1_deg",
              "type": "timeseries",
              "unit": "°",
              "count": 12,
              "time_range": "15:14 - 15:26",
              "interval": "60s",
              "stats_preview": {"min": -2.5, "max": 1.2, "mean": -0.8}
          }
      ],
      "relationships": [
          "axis_act_* und torque_act_* haben gleiche Timestamps (korrelierbar)"
      ]
  }
  ```
- [ ] Transformation-Funktion `create_metadata_summary(datasets)` 
- [ ] Stats Agent Prompt: Metadaten-Sektion
- [ ] Tests für Schema-Generierung

#### Akzeptanzkriterien
- Stats Agent sieht KEINE Rohdaten im Prompt
- Stats Agent sieht Metadaten mit allen relevanten Infos
- Token-Verbrauch signifikant reduziert

#### Betroffene Dateien
- `agents/stats_agent.py` (neue Funktion)
- `agents/utils.py` (Schema-Generierung)
- `prompts/stats_agent_prompt.py`

---

### AP7.4: Stats Agent LLM-Tool-Selection ⬜
**Ziel:** Stats Agent wählt Tools basierend auf LLM-Verständnis, nicht Keyword-Mapping.

#### Tasks
- [ ] `keyword_groups` Dictionary entfernen
- [ ] `compute_stats_directly()` Fallback überarbeiten oder entfernen
- [ ] Prompt mit Beispielen statt Regeln:
  ```xml
  <examples>
  Query: "Gibt es einen Zusammenhang zwischen X und Y?"
  → Prüfe: Haben X und Y gleiche Länge?
  → Tool: correlation(x_values, y_values)
  → Interpretiere: r > 0.7 = stark, r < 0.3 = schwach
  
  Query: "Wie ist der Durchschnitt?"
  → Tool: mean(values)
  </examples>
  ```
- [ ] MCP Tools haben gute Descriptions (DEC-001)
- [ ] Tests für verschiedene Analyse-Typen

#### Akzeptanzkriterien
```
"Zusammenhang zwischen Position und Moment"
→ Stats Agent ruft correlation() auf ✓
→ Interpretiert Ergebnis verständlich ✓

"Gibt es Ausreißer?"
→ Stats Agent ruft anomaly_detection() auf ✓
```

#### Betroffene Dateien
- `agents/stats_agent.py`
- `prompts/stats_agent_prompt.py`
- `mcp_servers/stats_server.py` (Tool Descriptions)
- `tests/test_stats_agent.py`

---

### AP7.5: Integration & Dokumentation ⬜
**Ziel:** Alles zusammen testen und dokumentieren.

#### Tasks
- [ ] End-to-End Test: Korrelations-Query komplett durchspielen
- [ ] Performance-Vergleich: Vorher/Nachher (Token, Zeit)
- [ ] DECISIONS.md aktualisieren (neue DECs falls nötig)
- [ ] 04_AKTUELLER_STAND.md aktualisieren
- [ ] Thesis-Abschnitt vorbereiten: "Intelligente Agent-Architektur"

#### Akzeptanzkriterien
- Korrelations-Query funktioniert End-to-End
- Dokumentation vollständig
- Keine Regression in bestehenden Tests

#### Betroffene Dateien
- `docs/DECISIONS.md`
- `docs/04_AKTUELLER_STAND.md`
- `tests/test_integration.py`

---

## Abhängigkeiten

```
AP7.1 ──┬──► AP7.2 ──┐
        │            ├──► AP7.5
AP7.3 ──┴──► AP7.4 ──┘
```

- AP7.1 und AP7.3 können parallel bearbeitet werden
- AP7.2 braucht AP7.1 (State-Awareness)
- AP7.4 braucht AP7.3 (Metadaten-Schema)
- AP7.5 braucht alle anderen

---

## Fortschritt

| AP | Status | Begonnen | Abgeschlossen | Notizen |
|----|--------|----------|---------------|---------|
| AP7.1 | ✅ | 28.01.2026 | 28.01.2026 | Beispiel-basiert statt Tool |
| AP7.2 | ⬜ | - | - | - |
| AP7.3 | ⬜ | - | - | - |
| AP7.4 | ⬜ | - | - | - |
| AP7.5 | ⬜ | - | - | - |

**Legende:** ⬜ Offen | 🟡 In Arbeit | ✅ Fertig | ❌ Blockiert

---

## Referenzen

- Best Practices Recherche: Session vom 28.01.2026
- Bestehendes Pattern: DEC-001 (Tool Selection), DEC-003 (InjectedState)
- LangGraph Docs: Context Engineering, Multi-Agent Workflows
