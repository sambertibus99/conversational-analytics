"""
Zentrale Konfiguration für das Conversational Analytics System.
"""

import os
import logging
import threading
from pathlib import Path
from dotenv import load_dotenv

# .env laden
load_dotenv()

logger = logging.getLogger(__name__)

# Pfade
PROJECT_ROOT = Path(__file__).parent.parent
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
OUTPUTS_DIR.mkdir(exist_ok=True)

# ThingsBoard
THINGSBOARD_URL = os.getenv("THINGSBOARD_URL", "http://localhost:8080")
THINGSBOARD_USERNAME = os.getenv("THINGSBOARD_USERNAME")
THINGSBOARD_PASSWORD = os.getenv("THINGSBOARD_PASSWORD")
KRC5_DEVICE_ID = os.getenv("KRC5_DEVICE_ID")


# =============================================================================
# API KEY ROTATOR (Rate Limit Handling)
# =============================================================================

class APIKeyRotator:
    """
    Round-Robin Rotation durch mehrere API Keys.
    
    Vorteile:
    - 3 Keys = 3x Rate Limits
    - Bei 429-Error: rotate() aufrufen, nächster Key wird verwendet
    - Thread-safe für parallele Requests
    """
    
    def __init__(self):
        keys_str = os.getenv("ANTHROPIC_API_KEYS", "")
        self.keys = [k.strip() for k in keys_str.split(",") if k.strip()]
        
        # Fallback auf einzelnen Key
        if not self.keys:
            single_key = os.getenv("ANTHROPIC_API_KEY", "")
            if single_key:
                self.keys = [single_key]
        
        if not self.keys:
            raise ValueError("Keine API Keys gefunden! Setze ANTHROPIC_API_KEYS in .env")
        
        self._index = 0
        self._lock = threading.Lock()
        logger.info(f"APIKeyRotator initialisiert mit {len(self.keys)} Keys")
    
    def get_key(self) -> str:
        """Gibt den aktuellen API Key zurück."""
        with self._lock:
            return self.keys[self._index]
    
    def rotate(self) -> str:
        """Wechselt zum nächsten Key und gibt ihn zurück."""
        with self._lock:
            old_index = self._index
            self._index = (self._index + 1) % len(self.keys)
            logger.warning(f"API Key rotiert: Key {old_index + 1} → Key {self._index + 1}")
            return self.keys[self._index]
    
    def get_key_info(self) -> str:
        """Gibt Info über aktuellen Key zurück (für Logging)."""
        with self._lock:
            return f"Key {self._index + 1}/{len(self.keys)}"


# Globale Instanz
api_key_rotator = APIKeyRotator()

# Rückwärtskompatibilität: ANTHROPIC_API_KEY zeigt auf aktuellen Key
ANTHROPIC_API_KEY = api_key_rotator.get_key()
DEFAULT_MODEL = "claude-sonnet-4-20250514"


# =============================================================================
# ANTHROPIC CLIENT MIT AUTO-ROTATION (DEC-018) UND PROMPT CACHING (DEC-021)
# =============================================================================

# Prompt Caching Header (DEC-021)
PROMPT_CACHING_HEADERS = {"anthropic-beta": "prompt-caching-2024-07-31"}


def create_anthropic_client(
    model: str = DEFAULT_MODEL,
    temperature: float = 0,
    enable_caching: bool = True,
    **kwargs
):
    """
    Erstellt einen ChatAnthropic Client mit dem aktuellen API Key.

    Bei 429-Errors sollte rotate_and_retry() verwendet werden.

    WICHTIG: max_retries=0 deaktiviert SDK-interne Retries, damit unsere
    Key-Rotation in execute_agent_with_retry() sofort greifen kann.

    Args:
        model: Modell-Name (default: claude-sonnet-4-20250514)
        temperature: Temperatur für Sampling (default: 0)
        enable_caching: Prompt Caching aktivieren (default: True, DEC-021)
        **kwargs: Weitere Parameter für ChatAnthropic

    Returns:
        ChatAnthropic Client mit aktuellem Key
    """
    from langchain_anthropic import ChatAnthropic

    # Model kwargs für Prompt Caching Headers (DEC-021)
    model_kwargs = kwargs.pop("model_kwargs", {})
    if enable_caching:
        existing_headers = model_kwargs.get("extra_headers", {})
        existing_headers.update(PROMPT_CACHING_HEADERS)
        model_kwargs["extra_headers"] = existing_headers

    return ChatAnthropic(
        model=model,
        api_key=api_key_rotator.get_key(),
        temperature=temperature,
        max_retries=0,  # SDK-Retry aus, eigene Rotation übernimmt (DEC-018)
        model_kwargs=model_kwargs if model_kwargs else None,
        **kwargs
    )


def create_cached_system_message(content: str):
    """
    Erstellt eine SystemMessage mit cache_control für Prompt Caching (DEC-021).

    WICHTIG: content muss als list[dict] formatiert werden, damit LangChain
    das cache_control korrekt an die Anthropic API weitergibt.
    (Siehe: https://github.com/langchain-ai/langchain/issues/26701)

    Args:
        content: Der System Prompt Text

    Returns:
        LangChain SystemMessage mit cache_control im content-Block
    """
    from langchain_core.messages import SystemMessage

    return SystemMessage(
        content=[{
            "type": "text",
            "text": content,
            "cache_control": {"type": "ephemeral"}
        }]
    )


async def invoke_with_rotation(client_factory, messages: list, max_rotations: int = 3):
    """
    Führt einen LLM-Aufruf aus mit automatischer Key-Rotation bei 429.
    
    Args:
        client_factory: Funktion die einen neuen Client erstellt (z.B. create_anthropic_client)
        messages: Liste von Messages für den Aufruf
        max_rotations: Maximale Anzahl Key-Rotationen
    
    Returns:
        LLM Response
    
    Raises:
        Exception: Wenn alle Keys Rate-Limited sind
    """
    import asyncio
    
    last_error = None
    
    for rotation in range(max_rotations):
        try:
            client = client_factory()
            logger.debug(f"LLM-Aufruf mit {api_key_rotator.get_key_info()}")
            
            # Versuche den Aufruf
            response = await client.ainvoke(messages)
            return response
            
        except Exception as e:
            error_str = str(e).lower()
            
            # Prüfe ob es ein Rate Limit Error ist
            if "429" in error_str or "rate limit" in error_str or "too many requests" in error_str:
                last_error = e
                logger.warning(f"Rate Limit mit {api_key_rotator.get_key_info()}: {e}")
                
                # Rotiere zum nächsten Key
                if rotation < max_rotations - 1:
                    api_key_rotator.rotate()
                    # Kurze Pause vor nächstem Versuch
                    await asyncio.sleep(1)
                    continue
            else:
                # Anderer Fehler - sofort werfen
                raise
    
    # Alle Keys haben Rate Limit erreicht
    raise Exception(
        f"Alle {max_rotations} API Keys haben Rate Limit erreicht. "
        f"Warte einige Sekunden und versuche es erneut. "
        f"Letzter Fehler: {last_error}"
    )

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
