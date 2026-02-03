"""
ThingsBoard MCP Server.

Exponiert Tools für ThingsBoard-Zugriff via MCP.

WICHTIG: Große Datenmengen werden in Dateien gespeichert,
nur Zusammenfassungen gehen an den LLM-Context!

DESIGN-ENTSCHEIDUNGEN:
1. Zeitraum-Parsing wird vom LLM übernommen (nicht mehr vom Tool) [19.12.2025]
2. Tools erwarten strukturierte Datum/Zeit-Parameter (ISO-Format) [19.12.2025]
3. IMMER Aggregation nutzen - Intervall wird automatisch berechnet [19.12.2025]
4. User wird über verwendete Einstellungen informiert [19.12.2025]
5. Tool-Descriptions optimiert für LLM-Auswahl [19.12.2025]
6. Error Handling: Custom Exceptions + ToolError für User-Feedback [20.12.2025]
7. Datenpunkt-Limit: Warnung bei >1000, Fehler bei >10000 Punkten [20.12.2025]
8. DEC-020: Komprimierter Lookup statt vollständigem Catalog im LLM-Context [02.02.2026]
9. DEC-023: Raw-Modus für Statistik/Korrelation (ohne Aggregation) [03.02.2026]
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from mcp_servers.thingsboard_client import (
    ThingsBoardClient,
    ThingsBoardError,
    ThingsBoardAuthError,
    ThingsBoardConnectionError,
    ThingsBoardNotFoundError,
    ThingsBoardRateLimitError,
)
from config.settings import KRC5_DEVICE_ID, VALID_DEVICES, OUTPUTS_DIR

# =============================================================================
# LOGGING SETUP
# =============================================================================

logger = logging.getLogger("thingsboard_server")
logger.setLevel(logging.DEBUG)

if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

# =============================================================================
# CONSTANTS
# =============================================================================

# MCP Server erstellen
mcp = FastMCP("ThingsBoard")

# Daten-Verzeichnis für temporäre Dateien
DATA_DIR = OUTPUTS_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Globaler Client (wird bei Bedarf initialisiert)
_client: ThingsBoardClient | None = None
_client_context = None

# Wochentag-Namen für Ausgabe
WEEKDAY_NAMES = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]

# Aggregations-Mapping: Nur noch Literal-Werte
AGGREGATION_OPTIONS = {
    "AVG": ("AVG", "Durchschnitt"),
    "MIN": ("MIN", "Minimum"),
    "MAX": ("MAX", "Maximum"),
    "SUM": ("SUM", "Summe"),
    "COUNT": ("COUNT", "Anzahl"),
}

# Intervall-Mapping: Vordefinierte Optionen statt Regex-Parsing
# Format: "key" -> (milliseconds, human_readable)
INTERVAL_OPTIONS = {
    "1m": (60000, "1 Minute"),
    "5m": (300000, "5 Minuten"),
    "10m": (600000, "10 Minuten"),
    "30m": (1800000, "30 Minuten"),
    "1h": (3600000, "1 Stunde"),
    "6h": (21600000, "6 Stunden"),
    "1d": (86400000, "1 Tag"),
}

# Datenpunkt-Limits
DATAPOINT_WARNING_THRESHOLD = 1000   # Ab hier: Warnung
DATAPOINT_ERROR_THRESHOLD = 10000    # Ab hier: Fehler, User muss anpassen


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

async def get_client() -> ThingsBoardClient:
    """Lazy initialization des ThingsBoard Clients."""
    global _client, _client_context
    if _client is None:
        logger.info("Initialisiere ThingsBoard Client...")
        _client = ThingsBoardClient()
        _client_context = await _client.__aenter__()
    return _client


def resolve_device_id(device_name: str | None) -> str:
    """Löst Device-Namen zu ID auf."""
    if device_name is None or device_name.upper() == "KRC5":
        return KRC5_DEVICE_ID
    
    raise ValueError(
        f"Unbekanntes Device: '{device_name}'. "
        f"Verfügbare Devices: {', '.join(VALID_DEVICES)}"
    )


def save_data_to_file(data: dict, prefix: str = "telemetry") -> str:
    """Speichert Daten in eine JSON-Datei."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{prefix}_{timestamp}_{uuid.uuid4().hex[:8]}.json"
    filepath = DATA_DIR / filename
    
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    logger.debug(f"Daten gespeichert: {filepath}")
    return str(filepath)


def calculate_statistics(data: dict) -> dict:
    """Berechnet Basis-Statistiken für die Daten."""
    stats = {}
    for key, values in data.items():
        if not values:
            continue
        
        numeric_values = []
        timestamps = []
        for v in values:
            if isinstance(v, dict) and "value" in v:
                try:
                    numeric_values.append(float(v["value"]))
                    if "timestamp" in v:
                        timestamps.append(v["timestamp"])
                except (ValueError, TypeError):
                    pass
            elif isinstance(v, (int, float)):
                numeric_values.append(float(v))
        
        if numeric_values:
            stats[key] = {
                "count": len(numeric_values),
                "min": round(min(numeric_values), 3),
                "max": round(max(numeric_values), 3),
                "avg": round(sum(numeric_values) / len(numeric_values), 3),
                "first": round(numeric_values[0], 3),
                "last": round(numeric_values[-1], 3),
            }
            if timestamps:
                stats[key]["first_timestamp"] = datetime.fromtimestamp(min(timestamps) / 1000).strftime("%d.%m.%Y %H:%M:%S")
                stats[key]["last_timestamp"] = datetime.fromtimestamp(max(timestamps) / 1000).strftime("%d.%m.%Y %H:%M:%S")
    
    return stats


def parse_datetime(date_str: str, time_str: str = "00:00") -> datetime:
    """
    Parst Datum und Zeit zu datetime.
    
    Args:
        date_str: Datum im Format YYYY-MM-DD (ISO 8601)
        time_str: Zeit im Format HH:MM (default: 00:00)
    
    Returns:
        datetime Objekt
    
    Raises:
        ValueError: Bei ungültigem Format
    """
    try:
        return datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    except ValueError as e:
        raise ValueError(
            f"Ungültiges Datum/Zeit-Format: date='{date_str}', time='{time_str}'. "
            f"Erwartet: date='YYYY-MM-DD', time='HH:MM'. Fehler: {e}"
        )


def get_interval(interval: str | None) -> tuple[int, str, bool]:
    """
    Holt Intervall aus vordefinierten Optionen.
    
    Args:
        interval: Vordefinierter Key wie "1m", "5m", "1h" oder None für Auto
    
    Returns:
        (interval_ms, human_readable, is_auto)
        
    Design-Entscheidung (DEC-011):
    Statt Regex-Parsing nutzen wir vordefinierte Optionen.
    Das LLM wählt direkt aus den gültigen Werten.
    """
    if interval is None:
        return None, None, True  # Auto-Intervall wird später berechnet
    
    interval_key = interval.lower().strip()
    
    if interval_key in INTERVAL_OPTIONS:
        ms, human = INTERVAL_OPTIONS[interval_key]
        return ms, human, False
    
    # Fallback: Unbekanntes Intervall -> Auto
    logger.warning(f"Unbekanntes Intervall '{interval}', verwende Auto-Intervall")
    return None, None, True


def get_aggregation(aggregation: str | None) -> tuple[str, str]:
    """
    Holt Aggregation aus vordefinierten Optionen.
    
    Args:
        aggregation: "AVG", "MIN", "MAX", "SUM", "COUNT" oder None
    
    Returns:
        (tb_aggregation, human_readable)
        
    Design-Entscheidung (DEC-011):
    Statt Multi-Alias-Mapping nutzen wir nur die API-Werte.
    Das LLM übersetzt "Maximum" -> "MAX" selbst.
    """
    if aggregation is None:
        return "AVG", "Durchschnitt"
    
    agg_upper = aggregation.upper().strip()
    
    if agg_upper in AGGREGATION_OPTIONS:
        return AGGREGATION_OPTIONS[agg_upper]
    
    # Fallback: Unbekannte Aggregation -> AVG
    logger.warning(f"Unbekannte Aggregation '{aggregation}', verwende AVG")
    return "AVG", "Durchschnitt"


def calculate_auto_interval(start_dt: datetime, end_dt: datetime) -> tuple[int, str, str]:
    """
    Berechnet automatisch das optimale Aggregations-Intervall.
    
    Args:
        start_dt: Startzeitpunkt
        end_dt: Endzeitpunkt
    
    Returns:
        (interval_ms, interval_human, reason)
    """
    duration = end_dt - start_dt
    duration_hours = duration.total_seconds() / 3600
    
    if duration_hours <= 1:
        # ≤ 1 Stunde → 1 Minute Intervall (~60 Punkte)
        return 60000, "1 Minute", f"Zeitraum {duration_hours:.1f}h → 1-Minuten-Intervall"
    elif duration_hours <= 24:
        # ≤ 1 Tag → 10 Minuten Intervall (~144 Punkte max)
        return 600000, "10 Minuten", f"Zeitraum {duration_hours:.1f}h → 10-Minuten-Intervall"
    elif duration_hours <= 168:  # 7 Tage
        # ≤ 1 Woche → 1 Stunde Intervall (~168 Punkte max)
        return 3600000, "1 Stunde", f"Zeitraum {duration_hours/24:.1f} Tage → 1-Stunden-Intervall"
    else:
        # > 1 Woche → 1 Tag Intervall
        days = duration_hours / 24
        return 86400000, "1 Tag", f"Zeitraum {days:.0f} Tage → 1-Tages-Intervall"


def calculate_expected_datapoints(
    start_dt: datetime,
    end_dt: datetime,
    interval_ms: int,
    num_keys: int
) -> tuple[int, int]:
    """
    Berechnet die erwartete Anzahl an Datenpunkten.
    
    Args:
        start_dt: Startzeitpunkt
        end_dt: Endzeitpunkt
        interval_ms: Intervall in Millisekunden
        num_keys: Anzahl der abgefragten Keys
    
    Returns:
        (points_per_key, total_points)
    """
    duration_ms = (end_dt - start_dt).total_seconds() * 1000
    points_per_key = int(duration_ms / interval_ms) + 1
    total_points = points_per_key * num_keys
    return points_per_key, total_points


def check_datapoint_limit(
    start_dt: datetime,
    end_dt: datetime,
    interval_ms: int,
    interval_human: str,
    num_keys: int
) -> dict | None:
    """
    Prüft ob die erwartete Datenmenge akzeptabel ist.
    
    Args:
        start_dt: Startzeitpunkt
        end_dt: Endzeitpunkt
        interval_ms: Intervall in Millisekunden
        interval_human: Menschenlesbares Intervall
        num_keys: Anzahl der Keys
    
    Returns:
        None wenn OK, sonst Error-Dict mit Korrekturvorschlag
    """
    points_per_key, total_points = calculate_expected_datapoints(
        start_dt, end_dt, interval_ms, num_keys
    )
    
    logger.debug(
        f"Erwartete Datenpunkte: {points_per_key} pro Key × {num_keys} Keys = {total_points}"
    )
    
    # Berechne empfohlenes Intervall
    auto_interval_ms, auto_interval_human, _ = calculate_auto_interval(start_dt, end_dt)
    
    if points_per_key > DATAPOINT_ERROR_THRESHOLD:
        # Zu viele Punkte - User muss anpassen
        logger.warning(
            f"Datenpunkt-Limit überschritten: {points_per_key} pro Key "
            f"(Limit: {DATAPOINT_ERROR_THRESHOLD})"
        )
        return {
            "status": "error_too_many_datapoints",
            "message": (
                f"Das gewählte Intervall ({interval_human}) würde ca. {points_per_key:,} "
                f"Datenpunkte pro Key erzeugen. Das ist zu viel für eine sinnvolle Verarbeitung."
            ),
            "expected_points_per_key": points_per_key,
            "expected_total_points": total_points,
            "limit": DATAPOINT_ERROR_THRESHOLD,
            "suggestion": {
                "interval": auto_interval_human,
                "expected_points": calculate_expected_datapoints(
                    start_dt, end_dt, auto_interval_ms, num_keys
                )[0],
            },
            "user_action": (
                f"Bitte wähle ein größeres Intervall (z.B. '{auto_interval_human}') "
                f"oder einen kürzeren Zeitraum."
            ),
            "hint": (
                "Frage den User: 'Das würde sehr viele Datenpunkte erzeugen. "
                f"Soll ich stattdessen {auto_interval_human}-Durchschnitte verwenden?'"
            ),
        }
    
    if points_per_key > DATAPOINT_WARNING_THRESHOLD:
        # Warnung - funktioniert, aber User sollte es wissen
        logger.info(
            f"Datenpunkt-Warnung: {points_per_key} pro Key "
            f"(Warnschwelle: {DATAPOINT_WARNING_THRESHOLD})"
        )
        return {
            "status": "warning_many_datapoints",
            "message": (
                f"Das gewählte Intervall ({interval_human}) erzeugt ca. {points_per_key:,} "
                f"Datenpunkte pro Key. Das ist viel, aber machbar."
            ),
            "expected_points_per_key": points_per_key,
            "expected_total_points": total_points,
            "warning_threshold": DATAPOINT_WARNING_THRESHOLD,
            "continue": True,  # Trotzdem weitermachen
            "user_info": (
                f"Hinweis: Bei {points_per_key:,} Datenpunkten kann die Verarbeitung "
                f"etwas länger dauern."
            ),
        }
    
    return None  # Alles OK


def format_thingsboard_error(error: ThingsBoardError) -> dict:
    """Formatiert ThingsBoard-Fehler für MCP-Response."""
    return {
        "status": "error",
        "error_type": error.__class__.__name__,
        "message": error.message,
        "details": error.details,
    }


# =============================================================================
# TELEMETRY LOOKUP INDEX (DEC-020)
# =============================================================================

# Pfad zur Lookup-Datei
LOOKUP_FILE = PROJECT_ROOT / "config" / "telemetry_lookup.json"


def load_telemetry_lookup() -> dict:
    """Lädt den komprimierten Telemetrie-Lookup-Index.
    
    DEC-020: Statt den vollen Catalog (~10.000 Tokens) ins LLM-Context zu laden,
    wird ein komprimierter Index für Substring-Matching verwendet.
    """
    try:
        with open(LOOKUP_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.info(f"Telemetry Lookup geladen: {len(data.get('groups', {}))} Gruppen")
        return data.get("groups", {})
    except Exception as e:
        logger.error(f"Fehler beim Laden des Telemetry Lookup: {e}")
        return {}


# Lookup beim Server-Start einmalig laden
_telemetry_lookup: dict = load_telemetry_lookup()


def search_lookup(query: str) -> list[dict]:
    """Durchsucht den Lookup-Index per Substring-Match.
    
    Matching-Strategie (DEC-020, Option B: Substring-Match):
    - query in alias ODER alias in query (case-insensitive)
    - Ermöglicht: "Gelenkwinkel" matcht "gelenkwinkel"
    - Ermöglicht: "gelenk" matcht "gelenkwinkel" (Substring)
    
    Returns:
        Liste von Matches mit group, name, keys, unit, description
    """
    query_lower = query.lower().strip()
    
    if not query_lower:
        return []
    
    matches = []
    
    for group_id, group_data in _telemetry_lookup.items():
        aliases = group_data.get("aliases", [])
        
        # Substring-Match: query in alias ODER alias in query
        matched = any(
            query_lower in alias or alias in query_lower
            for alias in aliases
        )
        
        if matched:
            matches.append({
                "group": group_id,
                "name": group_data.get("name", group_id),
                "keys": group_data.get("keys", []),
                "unit": group_data.get("unit", ""),
                "description": group_data.get("description", ""),
            })
    
    return matches


def get_available_groups_overview() -> list[dict]:
    """Gibt eine kompakte Übersicht aller Gruppen zurück (Fallback bei kein Match).
    
    DEC-020, Option 3B-minimal: Nur Gruppen + Aliases + Unit.
    Enthält KEINE Keys - der LLM soll nochmal mit besserem Begriff suchen.
    """
    overview = []
    for group_id, group_data in _telemetry_lookup.items():
        overview.append({
            "group": group_id,
            "aliases": group_data.get("aliases", []),
            "unit": group_data.get("unit", ""),
        })
    return overview


# =============================================================================
# MCP TOOLS
# =============================================================================

@mcp.tool()
async def search_telemetry_keys(query: str) -> str:
    """
    Findet passende Telemetrie-Keys basierend auf einem Suchbegriff.
    
    WANN BENUTZEN:
    - IMMER VOR get_telemetry, wenn der User natürlichsprachliche Begriffe verwendet
    - User sagt "Gelenkwinkel", "Drehmoment", "Geschwindigkeit" etc.
    - Du brauchst die exakten Key-Namen für get_telemetry
    
    NICHT BENUTZEN:
    - Du hast die Keys bereits aus einem früheren search_telemetry_keys Aufruf
    - Du kennst die exakten Key-Namen bereits
    
    Args:
        query: Suchbegriff, z.B. "Gelenkwinkel", "Drehmoment", "Geschwindigkeit", "Energie"
               Kann deutsch oder englisch sein. Einzelne Begriffe funktionieren am besten.
    
    Returns:
        Bei Match: Liste passender Gruppen mit Keys zum direkten Verwenden in get_telemetry
        Kein Match: Übersicht aller verfügbaren Gruppen mit Aliases zur Orientierung
    """
    logger.info(f"Tool aufgerufen: search_telemetry_keys(query={query})")
    
    matches = search_lookup(query)
    
    if matches:
        # Zähle alle Keys über alle Matches
        total_keys = sum(len(m.get("keys", [])) for m in matches)
        logger.info(f"Gefunden: {len(matches)} Gruppen, {total_keys} Keys für '{query}'")
        return json.dumps({
            "status": "found",
            "query": query,
            "matches": matches,
            "total_keys": total_keys,
            "usage_hint": "Verwende ALLE Keys aus den Matches für vollständige Analyse - keine Teilmenge auswählen.",
        }, indent=2, ensure_ascii=False)
    else:
        logger.info(f"Kein Match für '{query}', sende Übersicht")
        return json.dumps({
            "status": "no_match",
            "query": query,
            "hint": "Kein direkter Treffer. Hier sind alle verfügbaren Gruppen - versuche es mit einem der Aliases.",
            "available_groups": get_available_groups_overview(),
        }, indent=2, ensure_ascii=False)


@mcp.tool()
async def list_devices() -> str:
    """
    Listet alle verfügbaren Geräte/Roboter in ThingsBoard auf.
    
    WANN BENUTZEN:
    - User fragt "Welche Geräte gibt es?" oder "Welche Roboter sind verfügbar?"
    - User ist unsicher welches Gerät er abfragen soll
    - Erste Orientierung im System
    
    NICHT BENUTZEN:
    - User kennt bereits das Gerät (z.B. "KRC5") → direkt andere Tools nutzen
    - User fragt nach Messwerten → get_telemetry oder get_latest_telemetry
    """
    logger.info("Tool aufgerufen: list_devices")
    
    try:
        client = await get_client()
        devices = await client.list_devices()
        return json.dumps(devices, indent=2)
    except ThingsBoardError as e:
        logger.error(f"list_devices Fehler: {e.message}")
        return json.dumps(format_thingsboard_error(e), indent=2)


@mcp.tool()
async def get_device_info(device_name: str = "KRC5") -> str:
    """
    Gibt Detailinformationen zu einem spezifischen Gerät zurück (Name, Typ, ID, Erstelldatum).
    
    WANN BENUTZEN:
    - User fragt nach Geräte-Details: "Was ist das für ein Roboter?"
    - User will Metadaten wie Erstelldatum oder Gerätetyp wissen
    
    NICHT BENUTZEN:
    - User fragt nach Messwerten → get_telemetry oder get_latest_telemetry
    - User fragt welche Messwerte verfügbar sind → list_telemetry_keys
    - User fragt nach Attributen wie Masse → get_attributes
    
    Args:
        device_name: Name des Geräts, z.B. "KRC5" (default)
    """
    logger.info(f"Tool aufgerufen: get_device_info(device_name={device_name})")
    
    try:
        device_id = resolve_device_id(device_name)
        client = await get_client()
        info = await client.get_device_info(device_id)
        return json.dumps(info, indent=2)
    except ThingsBoardError as e:
        logger.error(f"get_device_info Fehler: {e.message}")
        return json.dumps(format_thingsboard_error(e), indent=2)
    except ValueError as e:
        return json.dumps({
            "status": "error",
            "message": str(e),
        }, indent=2)


@mcp.tool()
async def list_telemetry_keys(device_name: str = "KRC5") -> str:
    """
    Listet alle verfügbaren Telemetrie-Keys (Messwert-Namen) für ein Gerät auf.
    
    WANN BENUTZEN:
    - User fragt "Welche Messwerte gibt es?" oder "Was kann ich abfragen?"
    - User ist unsicher welchen Key er für eine Abfrage nutzen soll
    - User fragt nach "allen Daten" → erst Keys auflisten, dann nachfragen
    
    NICHT BENUTZEN:
    - User nennt bereits konkrete Messwerte (z.B. "Position", "Drehmoment")
    - User fragt nach konkreten Werten → get_telemetry oder get_latest_telemetry
    
    Args:
        device_name: Name des Geräts, z.B. "KRC5" (default)
    """
    logger.info(f"Tool aufgerufen: list_telemetry_keys(device_name={device_name})")
    
    try:
        device_id = resolve_device_id(device_name)
        client = await get_client()
        keys = await client.get_telemetry_keys(device_id)
        return json.dumps(keys, indent=2)
    except ThingsBoardError as e:
        logger.error(f"list_telemetry_keys Fehler: {e.message}")
        return json.dumps(format_thingsboard_error(e), indent=2)
    except ValueError as e:
        return json.dumps({"status": "error", "message": str(e)}, indent=2)


@mcp.tool()
async def get_data_availability(
    keys: str = "pos_act_x_mm",
    device_name: str = "KRC5",
) -> str:
    """
    Prüft, ob und wann Daten für einen Key verfügbar sind (letzte 7 Tage).
    
    WANN BENUTZEN:
    - BEVOR get_telemetry aufgerufen wird, wenn unklar ist ob Daten existieren
    - User fragt "Gibt es Daten für gestern?" oder "Wann war der Roboter aktiv?"
    - Nach einem no_data-Fehler um verfügbare Zeiträume zu finden
    
    NICHT BENUTZEN:
    - User nennt einen konkreten Zeitraum und will Daten sehen → get_telemetry
    - User fragt nach aktuellem Wert → get_latest_telemetry
    
    Args:
        keys: Ein Key zum Prüfen, z.B. "pos_act_x_mm" (nur einer wird geprüft)
        device_name: Name des Geräts (default: "KRC5")
        
    Returns:
        Zeitraum der verfügbaren Daten mit erstem und letztem Datum
    """
    logger.info(f"Tool aufgerufen: get_data_availability(keys={keys})")
    
    try:
        device_id = resolve_device_id(device_name)
        key_list = [k.strip() for k in keys.split(",")][:1]
        
        client = await get_client()
        
        # Hole Daten der letzten Woche um den Bereich zu finden
        now = datetime.now()
        week_ago = now - timedelta(days=7)
        start_ts = int(week_ago.timestamp() * 1000)
        end_ts = int(now.timestamp() * 1000)
        
        data = await client.get_telemetry(device_id, key_list, start_ts, end_ts)
        
        result = {
            "device": device_name,
            "key_checked": key_list[0],
        }
        
        if not data or not data.get(key_list[0]):
            result["status"] = "no_data"
            result["message"] = "Keine Daten in der letzten Woche gefunden."
            result["hint"] = "Der Roboter war möglicherweise nicht aktiv."
        else:
            values = data[key_list[0]]
            timestamps = [v["timestamp"] for v in values if "timestamp" in v]
            
            if timestamps:
                first_ts = min(timestamps)
                last_ts = max(timestamps)
                first_dt = datetime.fromtimestamp(first_ts / 1000)
                last_dt = datetime.fromtimestamp(last_ts / 1000)
                
                result["status"] = "data_available"
                result["data_range"] = {
                    "first_data": first_dt.strftime("%Y-%m-%d"),
                    "first_time": first_dt.strftime("%H:%M"),
                    "first_weekday": WEEKDAY_NAMES[first_dt.weekday()],
                    "last_data": last_dt.strftime("%Y-%m-%d"),
                    "last_time": last_dt.strftime("%H:%M"),
                    "last_weekday": WEEKDAY_NAMES[last_dt.weekday()],
                }
                result["total_points"] = len(values)
                result["message"] = f"Daten verfügbar von {first_dt.strftime('%d.%m.%Y %H:%M')} bis {last_dt.strftime('%d.%m.%Y %H:%M')}"
        
        return json.dumps(result, indent=2)
        
    except ThingsBoardError as e:
        logger.error(f"get_data_availability Fehler: {e.message}")
        return json.dumps(format_thingsboard_error(e), indent=2)
    except ValueError as e:
        return json.dumps({"status": "error", "message": str(e)}, indent=2)


@mcp.tool()
async def get_latest_telemetry(
    keys: str,
    device_name: str = "KRC5",
) -> str:
    """
    Holt die aktuellsten Telemetrie-Werte (genau 1 Wert pro Key, der neueste).
    
    WANN BENUTZEN:
    - User fragt nach AKTUELLEM Wert: "Wie ist die Position jetzt?"
    - User will EINEN Momentanwert: "Aktueller Drehmoment?"
    - Schnelle Statusabfrage ohne Zeitreihe
    
    NICHT BENUTZEN:
    - User fragt nach Verlauf/Trend über Zeit → get_telemetry
    - User nennt einen Zeitraum (gestern, letzte Stunde) → get_telemetry
    - User will Daten visualisieren → get_telemetry
    
    Args:
        keys: Komma-separierte Liste von Keys, z.B. "axis_act_a1_deg,vel_act_m_per_s"
        device_name: Name des Geräts (default: "KRC5")
        
    Returns:
        Aktuellster Wert pro Key mit Timestamp
    """
    logger.info(f"Tool aufgerufen: get_latest_telemetry(keys={keys})")
    
    try:
        device_id = resolve_device_id(device_name)
        key_list = [k.strip() for k in keys.split(",")]
        
        client = await get_client()
        data = await client.get_latest_telemetry(device_id, key_list)
        
        result = {}
        for key, value in data.items():
            if isinstance(value, dict) and "timestamp" in value:
                ts = value["timestamp"]
                dt = datetime.fromtimestamp(ts / 1000)
                result[key] = {
                    **value,
                    "timestamp_human": dt.strftime("%d.%m.%Y %H:%M:%S"),
                    "weekday": WEEKDAY_NAMES[dt.weekday()],
                }
            else:
                result[key] = value
        
        return json.dumps(result, indent=2)
        
    except ThingsBoardError as e:
        logger.error(f"get_latest_telemetry Fehler: {e.message}")
        return json.dumps(format_thingsboard_error(e), indent=2)
    except ValueError as e:
        return json.dumps({"status": "error", "message": str(e)}, indent=2)


@mcp.tool()
async def get_telemetry(
    keys: str,
    start_date: str,
    end_date: str,
    start_time: str = "00:00",
    end_time: str = "23:59",
    interval: Literal["1m", "5m", "10m", "30m", "1h", "6h", "1d"] | None = None,
    aggregation: Literal["AVG", "MIN", "MAX", "SUM", "COUNT"] | None = None,
    device_name: str = "KRC5",
    raw: bool = False,
) -> str:
    """
    Holt Telemetrie-ZEITREIHEN für einen definierten Zeitraum. Das HAUPTTOOL für Datenabfragen!

    WANN BENUTZEN:
    - User fragt nach VERLAUF/TREND: "Zeig Position von gestern"
    - User nennt ZEITRAUM: "Drehmomente vom Dienstag", "letzte Stunde"
    - User will VISUALISIEREN: "Zeig mir ein Diagramm der Geschwindigkeit"
    - User will MEHRERE DATENPUNKTE über Zeit analysieren

    NICHT BENUTZEN:
    - User fragt nur nach AKTUELLEM Wert → get_latest_telemetry
    - User fragt ob Daten existieren → get_data_availability
    - User fragt nach statischen Attributen (Masse, Energie gesamt) → get_attributes

    AUTOMATISCHE AGGREGATION (wenn raw=False):
    Wenn interval=None, wird automatisch berechnet:
    - ≤ 1 Stunde → 1m (1 Minute)
    - ≤ 1 Tag → 10m (10 Minuten)
    - ≤ 1 Woche → 1h (1 Stunde)
    - > 1 Woche → 1d (1 Tag)

    RAW MODUS (DEC-023):
    Bei raw=True werden Rohdaten OHNE Aggregation geholt - wichtig für:
    - Korrelationsanalysen (braucht echte Varianz)
    - Statistische Berechnungen (braucht viele Punkte)
    - Zeitreihen ≤24h: Max 10.000 Punkte
    - Zeitreihen >24h: Fallback auf feinste Aggregation (1m)

    Args:
        keys: Komma-separierte Keys, z.B. "axis_act_a1_deg,torque_act_a1_nm"
        start_date: Startdatum YYYY-MM-DD (z.B. "2025-12-16") - PFLICHT
        end_date: Enddatum YYYY-MM-DD (z.B. "2025-12-16") - PFLICHT
        start_time: Startzeit HH:MM (default: "00:00")
        end_time: Endzeit HH:MM (default: "23:59")
        interval: OPTIONAL - "1m", "5m", "10m", "30m", "1h", "6h", "1d" (sonst auto)
        aggregation: OPTIONAL - "AVG", "MIN", "MAX", "SUM", "COUNT" (default: AVG)
        device_name: Gerätename (default: "KRC5")
        raw: OPTIONAL - True für Rohdaten ohne Aggregation (für Statistik/Korrelation)

    Returns:
        Zusammenfassung mit Statistiken + Dateipfad zu den Rohdaten
    """
    logger.info(
        f"Tool aufgerufen: get_telemetry(keys={keys}, "
        f"start={start_date} {start_time}, end={end_date} {end_time}, "
        f"interval={interval}, aggregation={aggregation}, raw={raw})"
    )
    
    try:
        device_id = resolve_device_id(device_name)
        key_list = [k.strip() for k in keys.split(",")]
        
        # Datum/Zeit parsen
        try:
            start_dt = parse_datetime(start_date, start_time)
            end_dt = parse_datetime(end_date, end_time)
        except ValueError as e:
            return json.dumps({
                "status": "error",
                "message": str(e),
                "hint": "Datum muss im Format YYYY-MM-DD sein, Zeit im Format HH:MM"
            }, indent=2)
        
        start_ts = int(start_dt.timestamp() * 1000)
        end_ts = int(end_dt.timestamp() * 1000)
        
        # Intervall berechnen oder übernehmen
        interval_ms, interval_human, auto_interval = get_interval(interval)
        
        if auto_interval:
            # Auto-Intervall basierend auf Zeitraum
            interval_ms, interval_human, interval_reason = calculate_auto_interval(start_dt, end_dt)
        else:
            interval_reason = f"Vom User angegeben: {interval}"
        
        # =====================================================================
        # DATENPUNKT-LIMIT CHECK (DEC-009) - nicht im Raw-Modus (DEC-023)
        # =====================================================================
        limit_check = None
        if not raw:
            limit_check = check_datapoint_limit(
                start_dt, end_dt, interval_ms, interval_human, len(key_list)
            )

            if limit_check:
                if limit_check.get("status") == "error_too_many_datapoints":
                    # Fehler - User muss anpassen
                    logger.warning(f"Datenpunkt-Limit erreicht: {limit_check}")
                    return json.dumps(limit_check, indent=2)

                elif limit_check.get("status") == "warning_many_datapoints":
                    # Warnung - trotzdem weitermachen, aber User informieren
                    logger.info(f"Datenpunkt-Warnung: {limit_check}")
        
        # Aggregation holen
        tb_aggregation, aggregation_human = get_aggregation(aggregation)

        # Menschenlesbare Zeit
        start_human = start_dt.strftime("%d.%m.%Y %H:%M")
        end_human = end_dt.strftime("%d.%m.%Y %H:%M")
        start_weekday = WEEKDAY_NAMES[start_dt.weekday()]

        # DEC-023: Raw vs Aggregated Modus
        client = await get_client()
        data_mode_used = "aggregated"
        sampling_info = None

        if raw:
            # Raw-Modus: Rohdaten ohne Aggregation
            duration_hours = (end_dt - start_dt).total_seconds() / 3600

            if duration_hours <= 24:
                # ≤24h: Echte Rohdaten mit Limit
                logger.info(f"Raw-Modus: Hole Rohdaten für {duration_hours:.1f}h Zeitraum")
                data = await client.get_telemetry(
                    device_id, key_list, start_ts, end_ts, limit=10000
                )
                data_mode_used = "raw"
                sampling_info = {
                    "mode": "raw",
                    "limit": 10000,
                    "time_resolution": "Original-Sampling (~1s)",
                }
            else:
                # >24h: Fallback auf feinste Aggregation (1 Minute)
                logger.info(f"Raw-Modus mit Fallback: {duration_hours:.1f}h > 24h, verwende 1m Aggregation")
                data = await client.get_telemetry_aggregated(
                    device_id, key_list, start_ts, end_ts, 60000, tb_aggregation  # 1 Minute
                )
                data_mode_used = "raw_fallback"
                sampling_info = {
                    "mode": "raw_fallback",
                    "reason": f"Zeitraum {duration_hours:.0f}h zu lang für echte Rohdaten",
                    "time_resolution": "1 Minute Aggregation",
                }
                interval_human = "1 Minute"
        else:
            # Standard: Aggregierte Daten
            data = await client.get_telemetry_aggregated(
                device_id, key_list, start_ts, end_ts, interval_ms, tb_aggregation
            )
        
        # Prüfe ob Daten vorhanden
        total_points = sum(len(values) for values in data.values())
        
        if total_points == 0:
            return json.dumps({
                "status": "no_data",
                "requested_timerange": {
                    "start": start_human,
                    "end": end_human,
                    "weekday": start_weekday,
                },
                "settings": {
                    "interval": interval_human,
                    "aggregation": aggregation_human,
                    "auto_interval": auto_interval,
                },
                "message": f"Keine Daten für den Zeitraum {start_weekday}, {start_human} bis {end_human} gefunden.",
                "hint": "Nutze get_data_availability um zu prüfen, wann Daten verfügbar sind.",
                "action": "Informiere den Nutzer, dass keine Daten für diesen Zeitraum existieren. Versuche NICHT automatisch andere Zeiträume!",
            }, indent=2)
        
        # Daten vorhanden - normal verarbeiten
        stats = calculate_statistics(data)
        
        full_data = {
            "timerange": {
                "start_ts": start_ts,
                "end_ts": end_ts,
                "start_human": start_human,
                "end_human": end_human,
                "weekday": start_weekday,
            },
            "settings": {
                "interval_ms": interval_ms if not raw else None,
                "interval_human": interval_human if not raw else None,
                "aggregation": tb_aggregation if not raw else None,
                "aggregation_human": aggregation_human if not raw else None,
                "auto_interval": auto_interval,
                "data_mode": data_mode_used,  # DEC-023
            },
            "keys": key_list,
            "data": data,
        }
        # DEC-023: Sampling-Info für Raw-Modus
        if sampling_info:
            full_data["sampling_info"] = sampling_info
        data_file = save_data_to_file(full_data, "telemetry")
        
        # Settings für User-Info aufbereiten
        settings_info = {
            "interval": interval_human,
            "aggregation": aggregation_human,
            "auto_interval": auto_interval,
            "reason": interval_reason,
        }
        
        # Info-Text für den User
        if auto_interval:
            settings_text = f"Automatisch: {aggregation_human} alle {interval_human} ({interval_reason})"
        else:
            settings_text = f"Benutzerdefiniert: {aggregation_human} alle {interval_human}"
        
        summary = {
            "status": "success",
            "timerange": {
                "start": start_human,
                "end": end_human,
                "weekday": start_weekday,
            },
            "settings": settings_info,
            "settings_text": settings_text,
            "data_mode": data_mode_used,  # DEC-023
            "data_points": {key: len(values) for key, values in data.items()},
            "statistics": stats,
            "data_file": data_file,
            "user_hint": "Du kannst die Einstellungen anpassen: 'zeig Maximum statt Durchschnitt' oder 'mit 5-Minuten-Intervall'",
        }

        # DEC-023: Sampling-Info für Raw-Modus
        if sampling_info:
            summary["sampling_info"] = sampling_info
        
        # Warnung hinzufügen falls vorhanden
        if limit_check and limit_check.get("status") == "warning_many_datapoints":
            summary["warning"] = limit_check.get("user_info")
        
        return json.dumps(summary, indent=2)
        
    except ThingsBoardError as e:
        logger.error(f"get_telemetry Fehler: {e.message}")
        return json.dumps(format_thingsboard_error(e), indent=2)
    except ValueError as e:
        return json.dumps({"status": "error", "message": str(e)}, indent=2)


@mcp.tool()
async def get_attributes(
    keys: str,
    device_name: str = "KRC5",
) -> str:
    """
    Holt statische Attribute eines Geräts (Werte die sich selten oder nie ändern).
    
    WANN BENUTZEN:
    - User fragt nach STATISCHEN Eigenschaften: "Wie schwer ist die Last?", "Gesamtenergie?"
    - Typische Attribute: load_mass_kg, energy_total_kwh, Konfigurationswerte
    - Werte die sich nicht sekündlich ändern
    
    NICHT BENUTZEN:
    - User fragt nach Messwerten die sich ständig ändern → get_telemetry
    - User fragt nach aktuellem Sensorwert → get_latest_telemetry
    - User fragt nach Verlauf/Trend → get_telemetry
    
    Args:
        keys: Komma-separierte Attribut-Keys, z.B. "load_mass_kg,energy_total_kwh"
        device_name: Name des Geräts (default: "KRC5")
        
    Returns:
        Attribut-Werte (ohne Zeitreihe, nur aktuelle Werte)
    """
    logger.info(f"Tool aufgerufen: get_attributes(keys={keys})")
    
    try:
        device_id = resolve_device_id(device_name)
        key_list = [k.strip() for k in keys.split(",")]
        
        client = await get_client()
        data = await client.get_attributes(device_id, key_list)
        return json.dumps(data, indent=2)
        
    except ThingsBoardError as e:
        logger.error(f"get_attributes Fehler: {e.message}")
        return json.dumps(format_thingsboard_error(e), indent=2)
    except ValueError as e:
        return json.dumps({"status": "error", "message": str(e)}, indent=2)


@mcp.tool()
async def list_attribute_keys(device_name: str = "KRC5") -> str:
    """
    Listet alle verfügbaren Attribut-Keys (statische Eigenschaften) für ein Gerät auf.
    
    WANN BENUTZEN:
    - User fragt "Welche Attribute gibt es?" oder "Was sind die Eigenschaften?"
    - User ist unsicher welche statischen Werte verfügbar sind
    - Unterscheidung: Attribute = statisch, Telemetrie = dynamische Zeitreihen
    
    NICHT BENUTZEN:
    - User fragt nach Messwerten/Sensordaten → list_telemetry_keys
    - User kennt bereits das Attribut → get_attributes direkt aufrufen
    
    Args:
        device_name: Name des Geräts (default: "KRC5")
        
    Returns:
        Liste aller Attribut-Keys gruppiert nach Scope (SERVER, SHARED, CLIENT)
    """
    logger.info(f"Tool aufgerufen: list_attribute_keys(device_name={device_name})")
    
    try:
        device_id = resolve_device_id(device_name)
        client = await get_client()
        keys = await client.get_attribute_keys(device_id)
        return json.dumps(keys, indent=2)
        
    except ThingsBoardError as e:
        logger.error(f"list_attribute_keys Fehler: {e.message}")
        return json.dumps(format_thingsboard_error(e), indent=2)
    except ValueError as e:
        return json.dumps({"status": "error", "message": str(e)}, indent=2)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    mcp.run()
