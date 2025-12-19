# TESTFRAGEN FÜR EVALUATION

> 15 Testfragen + 5 Abstention-Tests
> Basierend auf KRC5-Telemetrie

---

## Verfügbare Daten (KRC5)

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
| `torqmon_a1_pct` - `torqmon_a6_pct` | Drehmomentüberwachung | % |
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

## 🟢 EINFACH (5 Fragen)

### E1: Einzelwert aktuell
**Query:** "Wie ist die aktuelle Position von Achse 1?"

**Expected:**
- Tool: `get_latest_telemetry(device="KRC5", keys=["axis_act_a1_deg"])`
- Output: "Achse 1 steht aktuell bei X.X Grad"
- Kein Chart nötig

---

### E2: Zeitreihe einfach
**Query:** "Zeig mir den Verlauf der Bahngeschwindigkeit der letzten Stunde als Liniendiagramm"

**Expected:**
- Tool: `get_telemetry(device="KRC5", keys=["vel_act_m_per_s"], start_ts=NOW-1h, end_ts=NOW)`
- Chart: Liniendiagramm
- X-Achse: Zeit, Y-Achse: m/s

---

### E3: Attribute abfragen
**Query:** "Wie schwer ist die aktuelle Last am Roboter?"

**Expected:**
- Tool: `get_attributes(device="KRC5", keys=["load_mass_kg"])`
- Output: "Die aktuelle Last beträgt X.X kg"

---

### E4: Energieverbrauch
**Query:** "Wie viel Energie hat der Roboter am 16. Dezember verbraucht?"

**Expected:**
- Tool: `get_telemetry(device="KRC5", keys=["energy_period_kwh"], start_ts=16.12, end_ts=16.12)`
- Berechnung: Summe aller Werte
- Output: "Der Roboter hat am 16.12. X.X kWh verbraucht"

---

### E5: Override-Status
**Query:** "Läuft der Roboter gerade mit vollem Override?"

**Expected:**
- Tool: `get_latest_telemetry(device="KRC5", keys=["override_pct"])`
- Output: "Der Override steht bei X%. [Ja, volle Geschwindigkeit / Nein, reduziert]"

---

## 🟡 MITTEL (5 Fragen)

### M1: Mehrere Achsen vergleichen
**Query:** "Vergleiche die Drehmomente aller 6 Achsen vom 16. Dezember als Diagramm"

**Expected:**
- Tool: `get_telemetry(device="KRC5", keys=["torque_act_a1_nm", ..., "torque_act_a6_nm"], ...)`
- Chart: Liniendiagramm mit 6 Linien, Legende
- Achsenbeschriftung: Zeit / Nm

---

### M2: Aggregation nötig
**Query:** "Zeig mir die durchschnittliche Achsposition 1 pro Stunde für den 16. Dezember"

**Expected:**
- Tool: `get_telemetry_aggregated(device="KRC5", keys=["axis_act_a1_deg"], interval="HOUR", agg="AVG", ...)`
- Chart: Balkendiagramm

---

### M3: Soll/Ist-Vergleich
**Query:** "Vergleiche das kommandierte und tatsächliche Drehmoment von Achse 3 für den 16. Dezember"

**Expected:**
- Tool: `get_telemetry(..., keys=["torque_act_a3_nm", "torque_cmd_a3_nm"], ...)`
- Chart: 2 Linien übereinander
- Interpretation: "Die Abweichung beträgt durchschnittlich X Nm"

---

### M4: Position 3D
**Query:** "Zeig mir die Bewegungsbahn des Roboters am 16. Dezember von 10 bis 11 Uhr"

**Expected:**
- Tool: `get_telemetry(..., keys=["pos_act_x_mm", "pos_act_y_mm", "pos_act_z_mm"], ...)`
- Chart: 3D-Scatter oder 2D-Projektion (XY, XZ)
- Hinweis: "Hier ist die XY-Projektion der Bahn"

---

### M5: Auslastung über Zeit
**Query:** "Wie hat sich die Auslastung am 16. Dezember entwickelt?"

**Expected:**
- Tool: `get_telemetry(..., keys=["utilization_current"], ...)`
- Chart: Liniendiagramm

---

## 🔴 KOMPLEX (5 Fragen)

### K1: Korrelationsanalyse
**Query:** "Gibt es einen Zusammenhang zwischen Geschwindigkeit und Drehmoment bei Achse 1?"

**Expected:**
- Tools: get_telemetry (beide Keys) → Stats Agent (correlation)
- Chart: Scatter-Plot (vel_axis_a1 vs torque_act_a1)
- Statistik: Korrelationskoeffizient r
- Interpretation: "r = 0.8 → starker positiver Zusammenhang"

---

### K2: Anomalie-Erkennung
**Query:** "Gab es am 16. Dezember ungewöhnlich hohe Drehmomentspitzen bei Achse 2?"

**Expected:**
- Tool: get_telemetry → Stats (mean, std, detect_outliers)
- Interpretation: "Mittelwert: X Nm, Std: Y Nm. Z Werte lagen >2σ über dem Mittel"
- Chart: Zeitreihe mit markierten Ausreißern

---

### K3: Trend-Analyse
**Query:** "Zeigt der Energieverbrauch einen Trend über die verfügbaren Daten?"

**Expected:**
- Tool: get_telemetry (7 Tage) → Stats (trend/linear regression)
- Chart: Linie + Trendlinie
- Interpretation: "Steigung: +X kWh/Tag → [steigender/fallender/stabiler] Trend"

---

### K4: Multi-Step Reasoning
**Query:** "Welche Achse hatte am 16. Dezember die höchste durchschnittliche Belastung?"

**Expected:**
- Tool: get_telemetry (alle 6 torque_act)
- Stats: mean pro Achse
- Vergleich: Max finden
- Output: "Achse X hatte mit Y Nm die höchste Durchschnittsbelastung"

---

### K5: Zeitraum-Vergleich
**Query:** "Vergleiche die Roboter-Auslastung vom 12. Dezember mit dem 16. Dezember"

**Expected:**
- Tool: 2x get_telemetry (12.12 vs 16.12)
- Chart: Gruppiertes Balkendiagramm
- Stats: Differenz berechnen
- Interpretation: "Am 16.12. war die Auslastung X% höher/niedriger als am 12.12."

---

## ⛔ ABSTENTION-TESTS (5 Fragen)

### A1: Unbekanntes Gerät
**Query:** "Zeig mir Daten vom KRC6"

**Expected:**
- Abstention: Ja
- Response: "Ich kenne nur den KRC5. Meinst du den?"

---

### A2: Unbekannter Messwert
**Query:** "Wie ist die Temperatur von Motor 1?"

**Expected:**
- Abstention: Ja (kein temperature Key vorhanden)
- Response: "Temperatur-Daten sind nicht verfügbar. Ich kann dir zeigen: [Liste relevanter Keys]"

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

### A5: Unmögliche Berechnung
**Query:** "Berechne die Lebensdauer des Roboters"

**Expected:**
- Abstention: Ja
- Response: "Diese Berechnung kann ich nicht durchführen. Ich kann dir aber Auslastungs- und Drehmomentdaten zeigen."

---

## Metriken

### Execution Accuracy (EX)
```
EX = (fehlerfreie_ausführungen / total_tests) * 100
Ziel: >80%
```

### Tool Selection Accuracy (TSA)
```
TSA = (korrekte_tool_auswahl / total_tool_calls) * 100
Ziel: >90%
```

### Data Faithfulness (DF)
```
DF = (werte_in_api_response / werte_im_output) * 100
Ziel: 100%
```

### Abstention Rate (AR)
```
AR = (korrekte_abstentions / abstention_tests) * 100
Ziel: >80% (4/5)
```

---

## Automatische Evaluation

```bash
# Alle Tests ausführen
python evaluation/run_evaluation.py

# Nur eine Kategorie
python evaluation/run_evaluation.py --category einfach

# Einzelner Test
python evaluation/run_evaluation.py --query-id E1

# Weniger Output
python evaluation/run_evaluation.py --quiet
```

Ergebnisse werden gespeichert in:
- `evaluation/results/results_TIMESTAMP.json` (Rohdaten)
- `evaluation/results/analysis_TIMESTAMP.md` (Report für Masterarbeit)
