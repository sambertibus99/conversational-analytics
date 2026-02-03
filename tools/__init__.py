"""
Tools Package.

Enthält Hilfsfunktionen und Tool-Implementierungen.
"""

from tools.stats_functions import (
    calculate_mean,
    calculate_std,
    calculate_min_max,
    calculate_correlation_timeseries,  # DEC-024
    calculate_linear_trend,
    calculate_moving_average,
    calculate_percentiles,
    detect_anomalies,
    extract_values_from_timeseries,
    extract_timestamps_from_timeseries,
)

__all__ = [
    "calculate_mean",
    "calculate_std",
    "calculate_min_max",
    "calculate_correlation_timeseries",
    "calculate_linear_trend",
    "calculate_moving_average",
    "calculate_percentiles",
    "detect_anomalies",
    "extract_values_from_timeseries",
    "extract_timestamps_from_timeseries",
]
