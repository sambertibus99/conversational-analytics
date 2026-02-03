"""
Statistics MCP Server für IIoT-Zeitreihendaten.

Bietet 8 statistische Tools:
1. mean - Durchschnitt
2. std - Standardabweichung
3. min_max - Minimum/Maximum
4. correlation_timeseries - Korrelation für IoT-Zeitreihen (DEC-024)
5. linear_trend - Lineare Regression/Trend
6. moving_average - Gleitender Durchschnitt
7. percentiles - Perzentile (Quartile)
8. anomaly_detection - Ausreißererkennung (Z-Score)

Verwendet FastMCP für einfache MCP-Server-Erstellung.
"""

import sys
from pathlib import Path

# Projekt-Root zu sys.path hinzufügen
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from mcp.server.fastmcp import FastMCP

from tools.stats_functions import (
    calculate_mean,
    calculate_std,
    calculate_min_max,
    calculate_correlation_timeseries,  # DEC-024
    calculate_linear_trend,
    calculate_moving_average,
    calculate_percentiles,
    detect_anomalies,
)


# MCP Server initialisieren
mcp = FastMCP("IIoT Statistics Server")


# =============================================================================
# TOOL DEFINITIONEN
# =============================================================================

@mcp.tool()
def mean(values: list[float]) -> dict:
    """
    Berechnet den arithmetischen Durchschnitt einer Werteliste.
    
    WANN NUTZEN:
    - "Durchschnitt", "Mittelwert", "average", "im Schnitt"
    - "durchschnittliche Temperatur/Drehmoment/Auslastung"
    - "Was ist der Mittelwert von X?"
    
    Args:
        values: Liste von Zahlenwerten (z.B. Sensorwerte)
    
    Returns:
        {"mean": 25.3, "count": 100}
    
    BEISPIEL:
        mean([25.0, 26.5, 24.8, 27.1]) → {"mean": 25.85, "count": 4}
    """
    return calculate_mean(values)


@mcp.tool()
def std(values: list[float]) -> dict:
    """
    Berechnet die Standardabweichung (Streuung der Werte).
    
    WANN NUTZEN:
    - "Streuung", "Standardabweichung", "Varianz"
    - "wie stark schwanken die Werte?"
    - "Stabilität" der Messwerte
    
    INTERPRETATION:
    - Kleine std → Werte sind stabil/konstant
    - Große std → Werte schwanken stark
    
    Args:
        values: Liste von Zahlenwerten
    
    Returns:
        {"std": 2.1, "variance": 4.41, "mean": 25.3, "count": 100}
    
    BEISPIEL:
        std([25.0, 26.5, 24.8, 27.1]) → {"std": 1.03, "variance": 1.06, ...}
    """
    return calculate_std(values)


@mcp.tool()
def min_max(values: list[float]) -> dict:
    """
    Gibt Minimum, Maximum und Spannweite zurück.
    
    WANN NUTZEN:
    - "Minimum", "Maximum", "höchster/niedrigster Wert"
    - "Bereich", "Spanne", "Range"
    - "Extremwerte"
    
    Args:
        values: Liste von Zahlenwerten
    
    Returns:
        {"min": 22.0, "max": 29.5, "range": 7.5, "count": 100}
    
    BEISPIEL:
        min_max([25.0, 26.5, 24.8, 27.1]) → {"min": 24.8, "max": 27.1, "range": 2.3}
    """
    return calculate_min_max(values)


@mcp.tool()
def correlation_timeseries(
    x_timestamps: list[int],
    x_values: list[float],
    y_timestamps: list[int],
    y_values: list[float],
    tolerance_ms: int = 1000,
) -> dict:
    """
    Berechnet Korrelation für IoT-Zeitreihen mit UNTERSCHIEDLICHEN Timestamps (DEC-024).

    WANN NUTZEN:
    - IoT-Sensordaten mit unterschiedlichen Abtastraten
    - Wenn x und y UNTERSCHIEDLICHE LÄNGEN haben
    - Zeitreihen mit Timing-Jitter (±10-50ms)
    - "Korrelation zwischen Drehmoment und Position"

    NICHT NUTZEN:
    - Wenn beide Arrays bereits gleiche Länge haben → nutze correlation()

    METHODE:
    Nutzt pd.merge_asof um Datenpunkte anhand der nächsten Timestamps zu matchen.
    Nur Punkte innerhalb der Toleranz werden gematcht.

    INTERPRETATION:
    - r > 0.7: starker positiver Zusammenhang
    - r < -0.7: starker negativer Zusammenhang
    - n_matched: Anzahl erfolgreich gematchter Punktepaare
    - match_rate: Prozentsatz erfolgreicher Matches

    Args:
        x_timestamps: Timestamps der ersten Variable (Millisekunden)
        x_values: Werte der ersten Variable
        y_timestamps: Timestamps der zweiten Variable (Millisekunden)
        y_values: Werte der zweiten Variable
        tolerance_ms: Maximale erlaubte Zeitdifferenz für Match (default: 1000ms)

    Returns:
        {
            "r": 0.85, "p_value": 0.001, "interpretation": "stark positiv",
            "n_matched": 98, "n_dropped": 2, "n_x": 100, "n_y": 98,
            "match_rate": 98.0, "tolerance_ms": 1000
        }

    BEISPIEL:
        # Sensor X: 5 Punkte, Sensor Y: nur 4 Punkte (1 fehlt)
        correlation_timeseries(
            x_timestamps=[1000, 2000, 3000, 4000, 5000],
            x_values=[10.0, 20.0, 30.0, 40.0, 50.0],
            y_timestamps=[1010, 2005, 3020, 4002],  # leicht versetzt, 1 fehlt!
            y_values=[11.0, 19.0, 31.0, 39.0]
        ) → {"r": 0.96, "n_matched": 5, "interpretation": "stark positiv"}
    """
    return calculate_correlation_timeseries(
        x_timestamps, x_values,
        y_timestamps, y_values,
        tolerance_ms,
    )


@mcp.tool()
def linear_trend(values: list[float], timestamps: list[int] | None = None) -> dict:
    """
    Berechnet den linearen Trend (Steigung) mittels Regression.
    
    WANN NUTZEN:
    - "Trend", "Tendenz", "Entwicklung"
    - "steigend/fallend/stabil?"
    - "Wie entwickelt sich X über Zeit?"
    
    INTERPRETATION:
    - slope > 0: steigender Trend (Werte nehmen zu)
    - slope < 0: fallender Trend (Werte nehmen ab)
    - slope ≈ 0: stabil (keine Veränderung)
    - r_squared nahe 1: Trend ist sehr deutlich
    - r_squared nahe 0: kein klarer Trend (viel Streuung)
    
    Args:
        values: Messwerte (Y-Achse)
        timestamps: Optional: Zeitstempel in ms. Wenn None, wird Index verwendet.
    
    Returns:
        {"slope": 0.5, "r_squared": 0.92, "trend": "steigend", ...}
    
    BEISPIEL:
        linear_trend([10, 12, 14, 15, 18]) → {"slope": 1.9, "trend": "steigend", "r_squared": 0.98}
    """
    return calculate_linear_trend(values, timestamps)


@mcp.tool()
def moving_average(values: list[float], window: int = 5) -> dict:
    """
    Berechnet den gleitenden Durchschnitt zur Glättung von Zeitreihen.
    
    WANN NUTZEN:
    - "gleitender Durchschnitt", "geglättet", "smoothed"
    - "Rauschen entfernen", "Trend ohne Ausreißer"
    - Vorbereitung für Trendanalyse bei verrauschten Daten
    
    Args:
        values: Zeitreihenwerte
        window: Fenstergröße - wie viele Werte werden gemittelt (default: 5)
                Größeres Fenster = stärkere Glättung
    
    Returns:
        {"smoothed": [25.1, 25.3, ...], "window": 5, "smoothed_count": 96}
    
    HINWEIS: Die Ausgabe ist kürzer als die Eingabe (um window-1 Werte)
    
    BEISPIEL:
        moving_average([1,2,3,4,5,6,7], window=3) → {"smoothed": [2,3,4,5,6], ...}
    """
    return calculate_moving_average(values, window)


@mcp.tool()
def percentiles(values: list[float], p: list[int] | None = None) -> dict:
    """
    Berechnet Perzentile (standardmäßig Quartile: 25%, 50%, 75%).
    
    WANN NUTZEN:
    - "Perzentil", "Median", "Quartil"
    - "In welchem Bereich liegen die meisten Werte?"
    - "Verteilung der Werte"
    
    INTERPRETATION:
    - p25 (1. Quartil): 25% der Werte liegen darunter
    - p50 (Median): 50% darunter, 50% darüber - robuster als Mittelwert!
    - p75 (3. Quartil): 75% der Werte liegen darunter
    - IQR = p75 - p25: Interquartilsabstand, zeigt typische Streuung
    
    Args:
        values: Liste von Zahlenwerten
        p: Welche Perzentile (default: [25, 50, 75])
           Beispiel: [10, 50, 90] für 10., 50., 90. Perzentil
    
    Returns:
        {"p25": 23.0, "p50": 25.0, "p75": 27.5, "min": 20.0, "max": 30.0}
    
    BEISPIEL:
        percentiles([1,2,3,4,5,6,7,8,9,10]) → {"p25": 3.25, "p50": 5.5, "p75": 7.75}
    """
    return calculate_percentiles(values, p)


@mcp.tool()
def anomaly_detection(values: list[float], sigma_threshold: float = 2.0) -> dict:
    """
    Erkennt Ausreißer/Anomalien mittels Z-Score (Werte > N×σ vom Mittelwert).
    
    WANN NUTZEN:
    - "Ausreißer", "Anomalie", "ungewöhnlich"
    - "Spitzen", "extreme Werte", "auffällig"
    - "Gab es ungewöhnliche Werte?"
    
    METHODE:
    Ein Wert gilt als Anomalie wenn er mehr als sigma_threshold 
    Standardabweichungen vom Mittelwert entfernt ist.
    
    Args:
        values: Zeitreihenwerte
        sigma_threshold: Ab wieviel σ gilt als Ausreißer (default: 2.0)
                        - 2.0σ: ~5% der Normalverteilung sind Ausreißer
                        - 3.0σ: ~0.3% sind Ausreißer (strenger)
    
    Returns:
        {
            "anomalies_count": 3,
            "anomaly_indices": [12, 45, 78],
            "anomaly_values": [42.5, 45.1, 41.8],
            "mean": 25.0,
            "std": 2.1,
            "threshold_upper": 29.2,
            "threshold_lower": 20.8,
            "anomaly_percentage": 3.0
        }
    
    BEISPIEL:
        anomaly_detection([25, 26, 24, 50, 25, 26]) → erkennt 50 als Anomalie
    """
    return detect_anomalies(values, sigma_threshold)


# =============================================================================
# SERVER STARTEN
# =============================================================================

if __name__ == "__main__":
    print("🚀 Starting IIoT Statistics MCP Server...")
    print("   Tools: mean, std, min_max, correlation_timeseries,")
    print("          linear_trend, moving_average, percentiles, anomaly_detection")
    mcp.run()
