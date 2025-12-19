# Evaluation Report: Conversational Analytics System

**Zeitstempel:** 2025-12-19T12:19:26.573843
**Anzahl Tests:** 5

## Zusammenfassung

| Metrik | Wert | Ziel | Status |
|--------|------|------|--------|
| Execution Accuracy (EX) | 80.0% | >80% | ✅ |
| Tool Selection (TSA) | 100.0% | >90% | ✅ |
| Data Faithfulness (DF) | 100.0% | 100% | ✅ |
| Abstention Rate (AR) | 0.0% | >80% | ❌ |

## Ergebnisse nach Kategorie

### Einfach

| ID | Query | Plan | EX | TSA | DF | AR | Zeit |
|----|-------|------|----|----|----|----|------|
| N-E1 | Wo befindet sich der TCP des Roboters la... | data_agent | ✅ | ✅ | ✅ | - | 19198ms |
| N-E2 | Zeige die Geschwindigkeitswerte vom letz... | data_agent → viz_agent | ❌ | ✅ | ✅ | - | 10632ms |
| N-E3 | Liste alle verfügbaren Telemetrie-Keys a... | data_agent | ✅ | ✅ | ✅ | - | 22714ms |
| N-E4 | Was war die letzte gemessene Bahngeschwi... | data_agent | ✅ | ✅ | ✅ | - | 17406ms |
| N-E5 | Welchen Winkel hat Achse 4 laut den aktu... | data_agent | ✅ | ✅ | ✅ | - | 14009ms |

## Detaillierte Ergebnisse

### N-E1: Wo befindet sich der TCP des Roboters laut den letzten Daten?

**Kategorie:** einfach
**Plan:** ['data_agent']
**Zeit:** 19198ms

**Response:**
```
Basierend auf den aktuellsten Sensordaten vom **Dienstag, 16.12.2025 um 18:36:28** befindet sich der TCP (Tool Center Point) des Roboters an folgender Position:

**Kartesische Koordinaten:**
- X: 270,45 mm
- Y: 349,23 mm  
- Z: 641,98 mm

**Rotationswinkel:**
- A: 104,96°
- B: 69,87°
- C: 122,20°

Der Roboter steht also etwa 27 cm rechts, 35 cm nach vorne und 64 cm hoch von seinem Koordinatenursprung entfernt, mit einer spezifischen Orientierung des Werkzeugs entsprechend den angegebenen Rotatio...
```

---

### N-E2: Zeige die Geschwindigkeitswerte vom letzten Dienstag als Diagramm

**Kategorie:** einfach
**Plan:** ['data_agent', 'viz_agent']
**Zeit:** 10632ms

**Fehler:** no_data

**Response:**
```
Leider konnte ich keine Geschwindigkeitsdaten vom letzten Dienstag finden. 

**Mögliche Gründe:**
- Es wurden keine Daten für diesen Zeitraum aufgezeichnet
- Die Sensoren waren möglicherweise offline
- Der Zeitraum liegt außerhalb des verfügbaren Datenbereichs

**Was Sie tun können:**
- Überprüfen Sie einen anderen Zeitraum (z.B. "Zeige Geschwindigkeitswerte von gestern")
- Fragen Sie nach verfügbaren Datenzeiträumen
- Kontaktieren Sie den Administrator, falls Sensordaten fehlen sollten

Kann ic...
```

---

### N-E3: Liste alle verfügbaren Telemetrie-Keys auf

**Kategorie:** einfach
**Plan:** ['data_agent']
**Zeit:** 22714ms

**Response:**
```
Basierend auf den geladenen Daten habe ich **51 Telemetrie-Einträge** gefunden. 

Die verfügbaren Telemetrie-Keys sind:
- **Temperatur-Sensoren**: temperature_sensor_1, temperature_sensor_2, temperature_sensor_3
- **Druck-Sensoren**: pressure_sensor_1, pressure_sensor_2  
- **Vibrations-Sensoren**: vibration_sensor_1, vibration_sensor_2, vibration_sensor_3
- **Durchfluss-Sensoren**: flow_sensor_1, flow_sensor_2
- **Energie-Metriken**: power_consumption, energy_total
- **System-Status**: system_s...
```

---

### N-E4: Was war die letzte gemessene Bahngeschwindigkeit?

**Kategorie:** einfach
**Plan:** ['data_agent']
**Zeit:** 17406ms

**Response:**
```
Die letzte gemessene Bahngeschwindigkeit beträgt **0,0 m/s**, gemessen am Dienstag, 16.12.2025 um 18:36:28 Uhr.

Das bedeutet, dass die Bahn zum Zeitpunkt der letzten Messung stillstand. Falls Sie erwarten würden, dass sich die Bahn bewegt, könnte dies darauf hindeuten, dass:
- Die Anlage gerade stillsteht
- Ein geplanter Stopp vorliegt
- Möglicherweise ein technisches Problem vorliegt

Benötigen Sie weitere Informationen zur Bahngeschwindigkeit oder möchten Sie den Verlauf über einen längeren Z...
```

---

### N-E5: Welchen Winkel hat Achse 4 laut den aktuellsten Daten?

**Kategorie:** einfach
**Plan:** ['data_agent']
**Zeit:** 14009ms

**Response:**
```
Basierend auf den aktuellsten Daten hat **Achse 4** einen Winkel von **-66,61 Grad**.

Diese Messung stammt vom Dienstag, 16.12.2025 um 18:36:28 Uhr und zeigt, dass sich die Achse in einer negativen Position befindet, also entgegen der positiven Drehrichtung ausgerichtet ist.
```

---

## Fazit

⚠️ **Nicht alle Zielwerte wurden erreicht.**

- AR: 0.0% < 80% (Ziel verfehlt)