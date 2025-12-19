# Evaluation Report: Conversational Analytics System

**Zeitstempel:** 2025-12-19T10:32:30.746945
**Anzahl Tests:** 5

## Zusammenfassung

| Metrik | Wert | Ziel | Status |
|--------|------|------|--------|
| Execution Accuracy (EX) | 100.0% | >80% | ✅ |
| Tool Selection (TSA) | 100.0% | >90% | ✅ |
| Data Faithfulness (DF) | 100.0% | 100% | ✅ |
| Abstention Rate (AR) | 0.0% | >80% | ❌ |

## Ergebnisse nach Kategorie

### Einfach

| ID | Query | Plan | EX | TSA | DF | AR | Zeit |
|----|-------|------|----|----|----|----|------|
| N-E1 | Wo befindet sich der TCP des Roboters ge... | data_agent | ✅ | ✅ | ✅ | - | 16944ms |
| N-E2 | Zeige die Geschwindigkeitswerte vom 15. ... | data_agent → viz_agent | ✅ | ✅ | ✅ | - | 12859ms |
| N-E3 | Welche Sensordaten kann ich abrufen? | data_agent | ✅ | ✅ | ✅ | - | 32655ms |
| N-E4 | Mit welcher Geschwindigkeit bewegt sich ... | data_agent | ✅ | ✅ | ✅ | - | 18334ms |
| N-E5 | Gib mir den Winkel von Achse 4 | data_agent | ✅ | ✅ | ✅ | - | 14834ms |

## Detaillierte Ergebnisse

### N-E1: Wo befindet sich der TCP des Roboters gerade?

**Kategorie:** einfach
**Plan:** ['data_agent']
**Zeit:** 16944ms

**Response:**
```
Die aktuelle Position des Roboter-TCP (Tool Center Point) ist:

**Kartesische Koordinaten:**
- X: 270,45 mm
- Y: 349,23 mm  
- Z: 641,98 mm

**Orientierung:**
- A-Achse: 104,96°
- B-Achse: 69,87°
- C-Achse: 122,20°

Diese Werte wurden am Dienstag, 16.12.2025 um 18:36:28 Uhr erfasst und zeigen die aktuelle Ist-Position des Roboters im Arbeitsraum.
```

---

### N-E2: Zeige die Geschwindigkeitswerte vom 15. Dezember

**Kategorie:** einfach
**Plan:** ['data_agent', 'viz_agent']
**Zeit:** 12859ms

**Response:**
```
Für den 15. Dezember 2025 sind keine Geschwindigkeitsdaten verfügbar.

Was möchten Sie tun?

1. **Verfügbare Zeiträume prüfen** - Ich kann schauen, wann Geschwindigkeitsdaten verfügbar sind
2. **Anderen Zeitraum wählen** - Sie können einen anderen Tag/Zeitraum angeben
3. **Aktuelle Geschwindigkeit anzeigen** - Die neuesten verfügbaren Geschwindigkeitswerte

Bitte wählen Sie eine Option oder geben Sie einen anderen Zeitraum an.
```

---

### N-E3: Welche Sensordaten kann ich abrufen?

**Kategorie:** einfach
**Plan:** ['data_agent']
**Zeit:** 32655ms

**Response:**
```
Leider kann ich Ihnen derzeit keine gültigen Sensordaten zeigen. 

**Das Problem:** Alle verfügbaren Sensordaten (44 Datenpunkte) von SERVER_SCOPE und CLIENT_SCOPE enthalten fehlerhafte Werte. Dies deutet auf ein technisches Problem hin - entweder mit den OPC-UA Verbindungen oder den Sensoren selbst.

**Was Sie tun können:**
1. Überprüfen Sie die OPC-UA Serververbindung
2. Kontrollieren Sie, ob die Sensoren ordnungsgemäß funktionieren
3. Prüfen Sie die Konfiguration der Datenquellen

Sobald die ...
```

---

### N-E4: Mit welcher Geschwindigkeit bewegt sich der Roboterarm momentan?

**Kategorie:** einfach
**Plan:** ['data_agent']
**Zeit:** 18334ms

**Response:**
```
Basierend auf den aktuellen Sensordaten bewegt sich der Roboterarm **momentan nicht** - die Geschwindigkeit beträgt 0,0 m/s.

Die Messung stammt von heute, Dienstag, 16.12.2025 um 18:36:28 Uhr. Der Roboterarm steht also gerade still oder befindet sich in einer Pausenposition.

Falls Sie die Geschwindigkeitsentwicklung über einen längeren Zeitraum analysieren möchten, kann ich gerne historische Daten laden und visualisieren.
```

---

### N-E5: Gib mir den Winkel von Achse 4

**Kategorie:** einfach
**Plan:** ['data_agent']
**Zeit:** 14834ms

**Response:**
```
Der aktuelle Winkel von Achse 4 beträgt **-66,61 Grad** (Stand: Dienstag, 16.12.2025 um 18:36:28).

Die negative Angabe bedeutet, dass sich die Achse in einer Position unterhalb der Nullstellung befindet.
```

---

## Fazit

⚠️ **Nicht alle Zielwerte wurden erreicht.**

- AR: 0.0% < 80% (Ziel verfehlt)