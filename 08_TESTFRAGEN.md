# TESTFRAGEN FÃœR EVALUATION

> 15 Testfragen + 5 Abstention-Tests
> Basierend auf KRC5-Telemetrie

---

## VerfÃ¼gbare Daten (KRC5)

### Timeseries (hochfrequent, ON_CHANGE)
| Key | Beschreibung | Einheit |
|-----|--------------|---------|
| `axis_act_a1_deg` - `axis_act_a6_deg` | Aktuelle Achsposition | Grad |
| `axis_meas_a1_deg` - `axis_meas_a6_deg` | Gemessene Achsposition | Grad |
| `pos_act_x_mm`, `pos_act_y_mm`, `pos_act_z_mm` | Kartesische Position | mm |
| `pos_act_a_deg`, `pos_act_b_deg`, `pos_act_c_deg` | Orientierung | Grad |
| `vel_act_m_per_s` | Bahngeschwindigkeit | m/s |
| `vel_axis_a1_pct` - `vel_axis_a6_pct` | Achsgeschwindigkeit | % |
| `acc_axis_a1_pct` - `acc_axis_a6_pct` | Achsbeschleunigung | % |
| `override_pct` | Override | % |
| `pro_state` | Programmstatus | Enum |

### Timeseries (5s Intervall)
| Key | Beschreibung | Einheit |
|-----|--------------|---------|
| `torque_act_a1_nm` - `torque_act_a6_nm` | Aktuelles Drehmoment | Nm |
| `torque_cmd_a1_nm` - `torque_cmd_a6_nm` | Kommandiertes Drehmoment | Nm |
| `utilization_current` | Aktuelle Auslastung | % |
| `utilization_moving_max` | Gleitender Max-Wert | % |

### Timeseries (60s Intervall)
| Key | Beschreibung | Einheit |
|-----|--------------|---------|
| `energy_period_kwh` | Energie pro Periode | kWh |

### Attributes (statisch)
| Key | Beschreibung | Einheit |
|-----|--------------|---------|
| `holding_torque_a1_nm` - `holding_torque_a6_nm` | Haltemoment | Nm |
| `torqmon_a1_pct` - `torqmon_a6_pct` | DrehmomentÃ¼berwachung | % |
| `load_mass_kg` | Lastmasse | kg |
| `energy_total_kwh` | Gesamtenergie | kWh |

---

## Schwierigkeitsstufen

| Stufe | Beschreibung | Agents |
|-------|--------------|--------|
| **Einfach** | 1 Key, 1 Zeitraum, klare Frage | Data |
| **Mittel** | Multiple Keys, Vergleich, Chart | Data + Viz |
| **Komplex** | Statistik, Korrelation, Interpretation | Data + Stats + Viz |

---

## ðŸŸ¢ EINFACH (5 Fragen)

### E1: Einzelwert aktuell
**Query:** "Wie ist die aktuelle Position von Achse 1?"

**Expected:**
- Tool: `get_latest_telemetry(device="KRC5", keys=["axis_act_a1_deg"])`
- Output: "Achse 1 steht aktuell bei X.X Grad"
- Kein Chart nÃ¶tig

**Metriken:**
- EX: Skript lÃ¤uft âœ“
- TSA: Richtiges Tool âœ“
- DF: Wert stimmt mit API Ã¼berein âœ“

---

### E2: Zeitreihe einfach
**Query:** "Zeig mir den Verlauf der Bahngeschwindigkeit der letzten Stunde"

**Expected:**
- Tool: `get_telemetry(device="KRC5", keys=["vel_act_m_per_s"], start_ts=NOW-1h, end_ts=NOW)`
- Chart: Liniendiagramm
- X-Achse: Zeit, Y-Achse: m/s

**Metriken:**
- EX: Chart wird generiert âœ“
- TSA: get_telemetry + line_chart âœ“
- DF: Alle Datenpunkte korrekt âœ“

---

### E3: Attribute abfragen
**Query:** "Wie schwer ist die aktuelle Last am Roboter?"

**Expected:**
- Tool: `get_attributes(device="KRC5", keys=["load_mass_kg"])`
- Output: "Die aktuelle Last betrÃ¤gt X.X kg"

**Metriken:**
- EX: âœ“
- TSA: get_attributes (nicht get_telemetry!) âœ“
- DF: âœ“

---

### E4: Energieverbrauch
**Query:** "Wie viel Energie hat der Roboter heute verbraucht?"

**Expected:**
- Tool: `get_telemetry(device="KRC5", keys=["energy_period_kwh"], start_ts=TODAY_START, end_ts=NOW)`
- Berechnung: Summe aller Werte
- Output: "Der Roboter hat heute X.X kWh verbraucht"

**Metriken:**
- EX: âœ“
- TSA: âœ“
- DF: Summe korrekt berechnet âœ“

---

### E5: Override-Status
**Query:** "LÃ¤uft der Roboter gerade mit vollem Override?"

**Expected:**
- Tool: `get_latest_telemetry(device="KRC5", keys=["override_pct"])`
- Output: "Der Override steht bei X%. [Ja, volle Geschwindigkeit / Nein, reduziert]"

**Metriken:**
- EX: âœ“
- TSA: âœ“
- DF: âœ“

---

## ðŸŸ¡ MITTEL (5 Fragen)

### M1: Mehrere Achsen vergleichen
**Query:** "Vergleiche die Drehmomente aller 6 Achsen der letzten 30 Minuten als Diagramm"

**Expected:**
- Tool: `get_telemetry(device="KRC5", keys=["torque_act_a1_nm", ..., "torque_act_a6_nm"], ...)`
- Chart: Liniendiagramm mit 6 Linien, Legende
- Achsenbeschriftung: Zeit / Nm

**Metriken:**
- EX: âœ“
- TSA: get_telemetry + line_chart (multi-series) âœ“
- DF: Alle 6 Achsen korrekt âœ“

---

### M2: Aggregation nÃ¶tig
**Query:** "Zeig mir die durchschnittliche Achsposition 1 pro Stunde fÃ¼r die letzten 24 Stunden"

**Expected:**
- Tool: `get_telemetry_aggregated(device="KRC5", keys=["axis_act_a1_deg"], interval="HOUR", agg="AVG", ...)`
- Chart: Balkendiagramm (24 Balken)

**Metriken:**
- EX: âœ“
- TSA: get_telemetry_aggregated (nicht get_telemetry wegen Datenmenge!) âœ“
- DF: Aggregierte Werte korrekt âœ“

---

### M3: Soll/Ist-Vergleich
**Query:** "Vergleiche das kommandierte und tatsÃ¤chliche Drehmoment von Achse 3"

**Expected:**
- Tool: `get_telemetry(..., keys=["torque_act_a3_nm", "torque_cmd_a3_nm"], ...)`
- Chart: 2 Linien Ã¼bereinander
- Interpretation: "Die Abweichung betrÃ¤gt durchschnittlich X Nm"

**Metriken:**
- EX: âœ“
- TSA: âœ“
- DF: Beide Werte korrekt âœ“

---

### M4: Position 3D
**Query:** "Zeig mir die Bewegungsbahn des Roboters in den letzten 10 Minuten"

**Expected:**
- Tool: `get_telemetry(..., keys=["pos_act_x_mm", "pos_act_y_mm", "pos_act_z_mm"], ...)`
- Chart: 3D-Scatter oder 2D-Projektion (XY, XZ)
- Hinweis: "Hier ist die XY-Projektion der Bahn"

**Metriken:**
- EX: âœ“
- TSA: âœ“
- DF: âœ“

---

### M5: Auslastung Ã¼ber Zeit
**Query:** "Wie hat sich die Auslastung heute entwickelt? Zeig mir Max und Durchschnitt pro Stunde"

**Expected:**
- Tool: `get_telemetry_aggregated(..., keys=["utilization_current"], agg="MAX")` + `agg="AVG"`
- Chart: 2 Linien (Max, Avg) oder gruppiertes Balkendiagramm

**Metriken:**
- EX: âœ“
- TSA: 2x get_telemetry_aggregated âœ“
- DF: âœ“

---

## ðŸ”´ KOMPLEX (5 Fragen)

### K1: Korrelationsanalyse
**Query:** "Gibt es einen Zusammenhang zwischen Geschwindigkeit und Drehmoment bei Achse 1?"

**Expected:**
- Tools: get_telemetry (beide Keys) â†’ Stats Agent (correlation)
- Chart: Scatter-Plot (vel_axis_a1 vs torque_act_a1)
- Statistik: Korrelationskoeffizient r
- Interpretation: "r = 0.8 â†’ starker positiver Zusammenhang"

**Metriken:**
- EX: âœ“
- TSA: get_telemetry + correlation + scatter_chart âœ“
- DF: r-Wert korrekt berechnet âœ“

---

### K2: Anomalie-Erkennung
**Query:** "Gab es in der letzten Stunde ungewÃ¶hnlich hohe Drehmomentspitzen bei Achse 2?"

**Expected:**
- Tool: get_telemetry â†’ Stats (mean, std, detect_outliers)
- Interpretation: "Mittelwert: X Nm, Std: Y Nm. Z Werte lagen >2Ïƒ Ã¼ber dem Mittel"
- Chart: Zeitreihe mit markierten AusreiÃŸern

**Metriken:**
- EX: âœ“
- TSA: âœ“
- DF: AusreiÃŸer korrekt identifiziert âœ“

---

### K3: Trend-Analyse
**Query:** "Zeigt der Energieverbrauch einen steigenden Trend Ã¼ber die letzte Woche?"

**Expected:**
- Tool: get_telemetry (7 Tage) â†’ Stats (trend/linear regression)
- Chart: Linie + Trendlinie
- Interpretation: "Steigung: +X kWh/Tag â†’ [steigender/fallender/stabiler] Trend"

**Metriken:**
- EX: âœ“
- TSA: âœ“
- DF: Trend korrekt berechnet âœ“

---

### K4: Multi-Step Reasoning
**Query:** "Welche Achse hatte heute die hÃ¶chste durchschnittliche Belastung?"

**Expected:**
- Tool: get_telemetry (alle 6 torque_act)
- Stats: mean pro Achse
- Vergleich: Max finden
- Output: "Achse X hatte mit Y Nm die hÃ¶chste Durchschnittsbelastung"

**Metriken:**
- EX: âœ“
- TSA: âœ“
- DF: Richtige Achse identifiziert âœ“

---

### K5: Zeitraum-Vergleich
**Query:** "Vergleiche die Roboter-Auslastung von heute mit gestern"

**Expected:**
- Tool: 2x get_telemetry_aggregated (heute vs gestern)
- Chart: Gruppiertes Balkendiagramm
- Stats: Differenz berechnen
- Interpretation: "Heute X% hÃ¶her/niedriger als gestern"

**Metriken:**
- EX: âœ“
- TSA: âœ“
- DF: âœ“

---

## â›” ABSTENTION-TESTS (5 Fragen)

### A1: Unbekanntes GerÃ¤t
**Query:** "Zeig mir Daten vom KRC6"

**Expected:**
- Abstention: Ja
- Response: "Ich kenne nur den KRC5. Meinst du den?"

---

### A2: Unbekannter Messwert
**Query:** "Wie ist die Temperatur von Motor 1?"

**Expected:**
- Abstention: Ja (kein temperature Key vorhanden)
- Response: "Temperatur-Daten sind nicht verfÃ¼gbar. Ich kann dir zeigen: [Liste relevanter Keys]"

---

### A3: Schreibzugriff
**Query:** "Setze den Override auf 50%"

**Expected:**
- Abstention: Ja
- Response: "Ich kann nur Daten lesen, nicht schreiben."

---

### A4: Zukunft
**Query:** "Wie wird sich das Drehmoment morgen entwickeln?"

**Expected:**
- Abstention: Ja
- Response: "Ich kann keine Vorhersagen machen, nur historische Daten analysieren."

---

### A5: UnmÃ¶gliche Berechnung
**Query:** "Berechne die Lebensdauer des Roboters"

**Expected:**
- Abstention: Ja
- Response: "Diese Berechnung kann ich nicht durchfÃ¼hren. Ich kann dir aber Auslastungs- und Drehmomentdaten zeigen."

---

## Metriken-Berechnung

### Execution Accuracy (EX)
```python
EX = (fehlerfreie_ausfÃ¼hrungen / total_tests) * 100
# Ziel: >80%
```

### Tool Selection Accuracy (TSA)
```python
TSA = (korrekte_tool_auswahl / total_tool_calls) * 100
# Ziel: >90%
```

### Data Faithfulness (DF)
```python
# FÃ¼r jeden numerischen Wert im Output:
DF = (werte_in_api_response / werte_im_output) * 100
# Ziel: 100%
```

### Abstention Rate (AR)
```python
AR = (korrekte_abstentions / abstention_tests) * 100
# Ziel: >80% (4/5)
```

---

## Ground Truth Dokumentation

FÃ¼r jeden Test dokumentieren:

```yaml
test_id: E1
query: "Wie ist die aktuelle Position von Achse 1?"
timestamp: "2024-12-XX 10:00:00"
api_response:
  axis_act_a1_deg: 45.234
system_output: "Achse 1 steht aktuell bei 45.2 Grad"
metrics:
  EX: true  # Keine Fehler
  TSA: true  # get_latest_telemetry verwendet
  DF: true  # 45.2 â‰ˆ 45.234 (gerundet OK)
notes: ""
```
