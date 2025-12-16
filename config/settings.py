"""
Zentrale Konfiguration für das Conversational Analytics System.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# .env laden
load_dotenv()

# Pfade
PROJECT_ROOT = Path(__file__).parent.parent
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
OUTPUTS_DIR.mkdir(exist_ok=True)

# ThingsBoard
THINGSBOARD_URL = os.getenv("THINGSBOARD_URL", "http://localhost:8080")
THINGSBOARD_USERNAME = os.getenv("THINGSBOARD_USERNAME")
THINGSBOARD_PASSWORD = os.getenv("THINGSBOARD_PASSWORD")
KRC5_DEVICE_ID = os.getenv("KRC5_DEVICE_ID")

# Anthropic
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
DEFAULT_MODEL = "claude-sonnet-4-20250514"

# Verfügbare Telemetrie-Keys (für Validierung)
TELEMETRY_KEYS = {
    # Achspositionen
    "axis_act_a1_deg", "axis_act_a2_deg", "axis_act_a3_deg",
    "axis_act_a4_deg", "axis_act_a5_deg", "axis_act_a6_deg",
    # Kartesische Position
    "pos_act_x_mm", "pos_act_y_mm", "pos_act_z_mm",
    "pos_act_a_deg", "pos_act_b_deg", "pos_act_c_deg",
    # Geschwindigkeiten
    "vel_act_m_per_s",
    "vel_axis_a1_pct", "vel_axis_a2_pct", "vel_axis_a3_pct",
    "vel_axis_a4_pct", "vel_axis_a5_pct", "vel_axis_a6_pct",
    # Drehmomente
    "torque_act_a1_nm", "torque_act_a2_nm", "torque_act_a3_nm",
    "torque_act_a4_nm", "torque_act_a5_nm", "torque_act_a6_nm",
    # Status
    "override_pct", "pro_state",
    # Energie
    "energy_period_kwh",
    # Auslastung
    "utilization_current", "utilization_moving_max",
}

ATTRIBUTE_KEYS = {
    "load_mass_kg", "energy_total_kwh",
    "holding_torque_a1_nm", "holding_torque_a2_nm", "holding_torque_a3_nm",
    "holding_torque_a4_nm", "holding_torque_a5_nm", "holding_torque_a6_nm",
}

# Geräte
VALID_DEVICES = {"KRC5"}
