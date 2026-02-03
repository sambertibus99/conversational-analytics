"""
Statistische Funktionen für IIoT-Zeitreihendaten.

Pure Python/NumPy Implementierungen - werden vom Stats MCP Server genutzt.

DESIGN-ENTSCHEIDUNGEN:
- DEC-024: merge_asof für Zeitreihen-Korrelation mit unterschiedlichen Timestamps
"""

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats
from typing import Any


def calculate_mean(values: list[float]) -> dict[str, Any]:
    """
    Berechnet den arithmetischen Durchschnitt.
    
    Args:
        values: Liste von Zahlenwerten
        
    Returns:
        dict mit mean und count
    """
    if not values:
        return {"error": "Keine Werte übergeben", "mean": None, "count": 0}
    
    arr = np.array(values, dtype=float)
    return {
        "mean": float(np.mean(arr)),
        "count": len(arr),
    }


def calculate_std(values: list[float]) -> dict[str, Any]:
    """
    Berechnet Standardabweichung und Varianz.
    
    Args:
        values: Liste von Zahlenwerten
        
    Returns:
        dict mit std, variance, mean und count
    """
    if not values:
        return {"error": "Keine Werte übergeben", "std": None}
    
    if len(values) < 2:
        return {"error": "Mindestens 2 Werte nötig", "std": None}
    
    arr = np.array(values, dtype=float)
    std_val = float(np.std(arr, ddof=1))  # Sample std (ddof=1)
    
    return {
        "std": std_val,
        "variance": std_val ** 2,
        "mean": float(np.mean(arr)),
        "count": len(arr),
    }


def calculate_min_max(values: list[float]) -> dict[str, Any]:
    """
    Berechnet Minimum, Maximum und Spannweite.
    
    Args:
        values: Liste von Zahlenwerten
        
    Returns:
        dict mit min, max, range
    """
    if not values:
        return {"error": "Keine Werte übergeben", "min": None, "max": None}
    
    arr = np.array(values, dtype=float)
    min_val = float(np.min(arr))
    max_val = float(np.max(arr))
    
    return {
        "min": min_val,
        "max": max_val,
        "range": max_val - min_val,
        "count": len(arr),
    }


def calculate_correlation_timeseries(
    x_timestamps: list[int],
    x_values: list[float],
    y_timestamps: list[int],
    y_values: list[float],
    tolerance_ms: int = 1000,
) -> dict[str, Any]:
    """
    Berechnet Pearson-Korrelation für Zeitreihen mit unterschiedlichen Timestamps.

    Nutzt pd.merge_asof um Datenpunkte anhand der nächsten Timestamps zu matchen.
    Dies ist ideal für IoT-Sensordaten die mit leicht unterschiedlichen Frequenzen
    oder Timing-Jitter aufgezeichnet werden (DEC-024).

    Args:
        x_timestamps: Timestamps der ersten Variable (Millisekunden)
        x_values: Werte der ersten Variable
        y_timestamps: Timestamps der zweiten Variable (Millisekunden)
        y_values: Werte der zweiten Variable
        tolerance_ms: Maximale erlaubte Zeitdifferenz für Match (default: 1000ms)

    Returns:
        dict mit r, p_value, Interpretation und Match-Statistiken
    """
    if not x_values or not y_values:
        return {"error": "Beide Variablen müssen Werte enthalten", "r": None}

    if not x_timestamps or not y_timestamps:
        return {"error": "Timestamps für beide Variablen erforderlich", "r": None}

    if len(x_timestamps) != len(x_values):
        return {"error": f"x: Timestamps ({len(x_timestamps)}) und Werte ({len(x_values)}) unterschiedlich", "r": None}

    if len(y_timestamps) != len(y_values):
        return {"error": f"y: Timestamps ({len(y_timestamps)}) und Werte ({len(y_values)}) unterschiedlich", "r": None}

    # DataFrames erstellen und sortieren
    df_x = pd.DataFrame({"ts": x_timestamps, "x": x_values}).sort_values("ts")
    df_y = pd.DataFrame({"ts": y_timestamps, "y": y_values}).sort_values("ts")

    # merge_asof: Für jeden x-Timestamp den nächsten y-Timestamp finden
    merged = pd.merge_asof(
        df_x,
        df_y,
        on="ts",
        tolerance=tolerance_ms,
        direction="nearest",
    )

    # NaN entfernen (Punkte ohne Match innerhalb der Toleranz)
    merged_clean = merged.dropna()
    n_matched = len(merged_clean)
    n_dropped = len(df_x) - n_matched

    if n_matched < 3:
        return {
            "error": f"Zu wenige überlappende Datenpunkte ({n_matched}). Benötigt: mindestens 3",
            "r": None,
            "n_matched": n_matched,
            "n_x": len(x_values),
            "n_y": len(y_values),
            "tolerance_ms": tolerance_ms,
        }

    x_matched = merged_clean["x"].values
    y_matched = merged_clean["y"].values

    # Prüfe auf konstante Werte
    if np.std(x_matched) == 0 or np.std(y_matched) == 0:
        return {"error": "Eine Variable ist konstant - keine Korrelation berechenbar", "r": None}

    r, p_value = scipy_stats.pearsonr(x_matched, y_matched)

    # Interpretation
    abs_r = abs(r)
    if abs_r >= 0.7:
        strength = "stark"
    elif abs_r >= 0.3:
        strength = "moderat"
    else:
        strength = "schwach"

    direction = "positiv" if r > 0 else "negativ" if r < 0 else "keine"

    return {
        "r": round(float(r), 4),
        "r_squared": round(float(r ** 2), 4),
        "p_value": round(float(p_value), 6),
        "strength": strength,
        "direction": direction,
        "interpretation": f"{strength} {direction}",
        "n_matched": n_matched,
        "n_dropped": n_dropped,
        "n_x": len(x_values),
        "n_y": len(y_values),
        "tolerance_ms": tolerance_ms,
        "match_rate": round(100 * n_matched / len(df_x), 1),
    }


def calculate_linear_trend(
    values: list[float], 
    timestamps: list[int] | None = None
) -> dict[str, Any]:
    """
    Berechnet linearen Trend mittels Regression.
    
    Args:
        values: Y-Werte (Messwerte)
        timestamps: X-Werte (optional, sonst Index 0,1,2,...)
        
    Returns:
        dict mit slope, intercept, r_squared und Trend-Interpretation
    """
    if not values:
        return {"error": "Keine Werte übergeben", "slope": None}
    
    if len(values) < 3:
        return {"error": "Mindestens 3 Werte nötig für Trendberechnung", "slope": None}
    
    y = np.array(values, dtype=float)
    
    if timestamps:
        if len(timestamps) != len(values):
            return {"error": "timestamps und values müssen gleich lang sein", "slope": None}
        x = np.array(timestamps, dtype=float)
        # Normalisiere Timestamps für numerische Stabilität
        x = (x - x[0]) / 1000  # In Sekunden ab Start
    else:
        x = np.arange(len(y), dtype=float)
    
    # Lineare Regression
    slope, intercept, r_value, p_value, std_err = scipy_stats.linregress(x, y)
    
    # Trend-Interpretation
    if abs(slope) < 0.001:  # Quasi-konstant
        trend = "stabil"
    elif slope > 0:
        trend = "steigend"
    else:
        trend = "fallend"
    
    return {
        "slope": float(slope),
        "intercept": float(intercept),
        "r_squared": float(r_value ** 2),
        "p_value": float(p_value),
        "std_error": float(std_err),
        "trend": trend,
        "count": len(y),
    }


def calculate_moving_average(
    values: list[float], 
    window: int = 5
) -> dict[str, Any]:
    """
    Berechnet gleitenden Durchschnitt.
    
    Args:
        values: Zeitreihenwerte
        window: Fenstergröße (default: 5)
        
    Returns:
        dict mit geglätteten Werten
    """
    if not values:
        return {"error": "Keine Werte übergeben", "smoothed": None}
    
    if window < 1:
        return {"error": "window muss >= 1 sein", "smoothed": None}
    
    if window > len(values):
        return {"error": f"window ({window}) größer als Datenlänge ({len(values)})", "smoothed": None}
    
    arr = np.array(values, dtype=float)
    
    # Convolution für gleitenden Durchschnitt
    kernel = np.ones(window) / window
    smoothed = np.convolve(arr, kernel, mode='valid')
    
    return {
        "smoothed": smoothed.tolist(),
        "window": window,
        "original_count": len(values),
        "smoothed_count": len(smoothed),
    }


def calculate_percentiles(
    values: list[float], 
    p: list[int] | None = None
) -> dict[str, Any]:
    """
    Berechnet Perzentile (default: Quartile 25/50/75).
    
    Args:
        values: Zahlenwerte
        p: Liste der Perzentile (default: [25, 50, 75])
        
    Returns:
        dict mit Perzentilwerten
    """
    if not values:
        return {"error": "Keine Werte übergeben", "percentiles": None}
    
    if p is None:
        p = [25, 50, 75]
    
    # Validiere Perzentile
    for percentile in p:
        if not 0 <= percentile <= 100:
            return {"error": f"Perzentil {percentile} ungültig (muss 0-100 sein)", "percentiles": None}
    
    arr = np.array(values, dtype=float)
    
    result = {
        f"p{percentile}": float(np.percentile(arr, percentile))
        for percentile in p
    }
    
    result["count"] = len(arr)
    result["min"] = float(np.min(arr))
    result["max"] = float(np.max(arr))
    
    return result


def detect_anomalies(
    values: list[float], 
    sigma_threshold: float = 2.0
) -> dict[str, Any]:
    """
    Erkennt Ausreißer mittels Z-Score (Werte > N×σ vom Mittelwert).
    
    Args:
        values: Zeitreihenwerte
        sigma_threshold: Ab wieviel σ gilt als Ausreißer (default: 2.0)
        
    Returns:
        dict mit Anomalie-Informationen
    """
    if not values:
        return {"error": "Keine Werte übergeben", "anomalies_count": 0}
    
    if len(values) < 3:
        return {"error": "Mindestens 3 Werte nötig für Anomalieerkennung", "anomalies_count": 0}
    
    if sigma_threshold <= 0:
        return {"error": "sigma_threshold muss > 0 sein", "anomalies_count": 0}
    
    arr = np.array(values, dtype=float)
    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=1))
    
    if std == 0:
        return {
            "anomalies_count": 0,
            "anomaly_indices": [],
            "anomaly_values": [],
            "mean": mean,
            "std": 0,
            "threshold_upper": mean,
            "threshold_lower": mean,
            "message": "Alle Werte sind identisch - keine Anomalien möglich",
        }
    
    # Z-Score berechnen
    z_scores = np.abs((arr - mean) / std)
    
    # Anomalien finden
    anomaly_mask = z_scores > sigma_threshold
    anomaly_indices = np.where(anomaly_mask)[0].tolist()
    anomaly_values = arr[anomaly_mask].tolist()
    
    # Nach Abweichung sortieren (größte zuerst)
    if anomaly_indices:
        sorted_pairs = sorted(
            zip(anomaly_indices, anomaly_values, z_scores[anomaly_mask]),
            key=lambda x: x[2],
            reverse=True
        )
        anomaly_indices = [p[0] for p in sorted_pairs]
        anomaly_values = [p[1] for p in sorted_pairs]
    
    threshold_upper = mean + sigma_threshold * std
    threshold_lower = mean - sigma_threshold * std
    
    return {
        "anomalies_count": len(anomaly_indices),
        "anomaly_indices": anomaly_indices[:20],  # Max 20 zurückgeben
        "anomaly_values": [round(v, 4) for v in anomaly_values[:20]],
        "mean": round(mean, 4),
        "std": round(std, 4),
        "threshold_upper": round(threshold_upper, 4),
        "threshold_lower": round(threshold_lower, 4),
        "sigma_threshold": sigma_threshold,
        "total_count": len(arr),
        "anomaly_percentage": round(100 * len(anomaly_indices) / len(arr), 2),
    }


# =============================================================================
# HILFSFUNKTIONEN
# =============================================================================

def extract_values_from_timeseries(data: dict[str, list], key: str | None = None) -> list[float]:
    """
    Extrahiert numerische Werte aus ThingsBoard-Zeitreihenformat.
    
    Args:
        data: ThingsBoard-Format {"key": [{"value": "25.3", "timestamp": 123}, ...]}
        key: Welcher Key (falls None, nimm ersten)
        
    Returns:
        Liste von float-Werten
    """
    if not data:
        return []
    
    # Key bestimmen
    if key is None:
        key = next(iter(data.keys()), None)
    
    if key not in data:
        return []
    
    values = []
    for point in data[key]:
        if isinstance(point, dict) and "value" in point:
            try:
                values.append(float(point["value"]))
            except (ValueError, TypeError):
                continue
        elif isinstance(point, (int, float)):
            values.append(float(point))
    
    return values


def extract_timestamps_from_timeseries(data: dict[str, list], key: str | None = None) -> list[int]:
    """
    Extrahiert Timestamps aus ThingsBoard-Zeitreihenformat.
    
    Args:
        data: ThingsBoard-Format
        key: Welcher Key
        
    Returns:
        Liste von Timestamps (ms)
    """
    if not data:
        return []
    
    if key is None:
        key = next(iter(data.keys()), None)
    
    if key not in data:
        return []
    
    timestamps = []
    for point in data[key]:
        if isinstance(point, dict) and "timestamp" in point:
            timestamps.append(int(point["timestamp"]))
    
    return timestamps


# =============================================================================
# TEST
# =============================================================================

if __name__ == "__main__":
    # Testdaten
    test_values = [25.0, 26.5, 24.8, 27.1, 25.5, 26.0, 50.0, 25.2, 26.8, 25.9]
    
    print("=== Stats Functions Test ===\n")
    
    print("1. Mean:")
    print(f"   {calculate_mean(test_values)}")
    
    print("\n2. Std:")
    print(f"   {calculate_std(test_values)}")
    
    print("\n3. Min/Max:")
    print(f"   {calculate_min_max(test_values)}")
    
    print("\n4. Percentiles:")
    print(f"   {calculate_percentiles(test_values)}")
    
    print("\n5. Moving Average (window=3):")
    result = calculate_moving_average(test_values, window=3)
    print(f"   smoothed_count: {result['smoothed_count']}")
    
    print("\n6. Linear Trend:")
    print(f"   {calculate_linear_trend(test_values)}")
    
    print("\n7. Anomaly Detection (2σ):")
    print(f"   {detect_anomalies(test_values, sigma_threshold=2.0)}")
    
    print("\n8. Correlation Timeseries (DEC-024):")
    # Sensor X: 5 Punkte bei t=1000, 2000, 3000, 4000, 5000
    x_ts = [1000, 2000, 3000, 4000, 5000]
    x_vals = [10.0, 20.0, 30.0, 40.0, 50.0]
    # Sensor Y: 4 Punkte bei leicht anderen Timestamps (jitter)
    y_ts = [1010, 2005, 3020, 4002]  # 4 Punkte statt 5!
    y_vals = [11.0, 19.0, 31.0, 39.0]
    result = calculate_correlation_timeseries(x_ts, x_vals, y_ts, y_vals)
    print(f"   n_x={result.get('n_x')}, n_y={result.get('n_y')}, n_matched={result.get('n_matched')}")
    print(f"   r={result.get('r')}, interpretation: {result.get('interpretation')}")

    print("\n✅ Alle Tests abgeschlossen!")
