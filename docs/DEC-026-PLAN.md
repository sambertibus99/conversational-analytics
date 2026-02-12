# DEC-026: DuckDB als Session-Level Data Cache — Implementierungsplan

## Problem

1. **Overwrite-Bug:** `store_dataset` in `config/duckdb_store.py` macht `DELETE WHERE dataset_key = ?` vor jedem INSERT. Bei mehreren MCP-Calls im selben Turn (z.B. Retry nach `error_too_many_datapoints`) ueberlebt nur der letzte Call.

2. **Fehlende Daten-Differenzierung:** `determine_dataset_key_legacy` in `agents/data_agent.py` erzeugt Keys ohne Modus (raw/aggregated), Zeitraum, Intervall oder Aggregation. Verschiedene Abfragen desselben Signal-Typs ueberschreiben sich.

3. **Kein gefilterter Zugriff:** `get_data_from_state()` in `agents/utils.py` liest ALLE Daten aus DuckDB. Downstream Agents (viz/stats) sehen Daten aus vorherigen Turns die nicht relevant sind.

4. **Supervisor ist passiv:** Bei Turn 2 ohne data_agent hat der Supervisor keine Logik um intelligent zu entscheiden welche bestehenden Datasets relevant sind, ob Daten fehlen, oder ob Rueckfrage noetig ist.

## Loesung: 4 Phasen

---

## Phase 1: UPSERT + Reichere Keys (Bugfix + Foundation)

**Ziel:** Overwrite-Bug fixen, differenzierte Dataset-Keys einfuehren.
**Dateien:** `config/duckdb_store.py`, `agents/data_agent.py`
**Abhaengigkeiten:** Keine

### 1a. `config/duckdb_store.py` — Schema + UPSERT

**Schema aendern** (`_init_schema`, ca. Z.88-103):
```sql
-- Vorher:
CREATE TABLE IF NOT EXISTS telemetry (
    dataset_key TEXT NOT NULL,
    signal_key  TEXT NOT NULL,
    ts          BIGINT NOT NULL,
    value       DOUBLE NOT NULL,
    unit        TEXT DEFAULT ''
)
CREATE INDEX IF NOT EXISTS idx_telemetry_keys ON telemetry (dataset_key, signal_key)

-- Nachher:
CREATE TABLE IF NOT EXISTS telemetry (
    dataset_key TEXT NOT NULL,
    signal_key  TEXT NOT NULL,
    ts          BIGINT NOT NULL,
    value       DOUBLE NOT NULL,
    unit        TEXT DEFAULT '',
    PRIMARY KEY (dataset_key, signal_key, ts)
)
-- Kein separater Index noetig — PK erzeugt automatisch einen
```

**`store_dataset` aendern** (ca. Z.198-213):
- DELETE Statement entfernen (Z.202-205)
- `INSERT INTO` → `INSERT OR REPLACE INTO` (Z.208)

**Neue Methode `clear_dataset`** (nach `clear()`, ca. Z.145):
```python
def clear_dataset(self, dataset_key: str) -> None:
    """Loescht alle Daten fuer einen dataset_key."""
    self._conn.execute("DELETE FROM telemetry WHERE dataset_key = ?", [dataset_key])
```

**`generate_dataset_key` erweitern** (ca. Z.378-405):
```python
def generate_dataset_key(
    device_id: str,
    signal_type: str,
    data_type: str = "timeseries",
    temporal: str = "",
    data_mode: str = "",        # "raw" | "aggregated"
    time_range: str = "",       # "2025-12-16_12-00_14-00"
    interval_agg: str = "",     # "60s_avg" | "300s_max"
) -> str:
    parts = [device_id.lower(), signal_type.lower(), data_type.lower()]
    if data_mode:
        parts.append(data_mode.lower())
    if time_range:
        parts.append(time_range.lower())
    if interval_agg:
        parts.append(interval_agg.lower())
    elif temporal:
        parts.append(temporal.lower())
    return "/".join(parts)
```

Beispiel-Key: `krc5/torque/timeseries/aggregated/2025-12-16_12-00_14-00/60s_avg`

### 1b. `agents/data_agent.py` — Reichere Key-Generierung

**Neue Funktion `determine_dataset_key_rich`** (neben `determine_dataset_key_legacy`, Z.379):
```python
def determine_dataset_key_rich(
    data: dict,
    meta: dict | None,
    data_retrieval_mode: str = "aggregated",
) -> str:
    """
    Dataset-Key mit MCP-Metadaten: mode, time_range, interval_agg.
    Format: krc5/{signal_type}/{data_type}/{mode}/{time_range}/{interval_agg}
    """
    keys = list(data.keys())
    signal_type = determine_signal_type(keys)

    data_type = "timeseries"
    if meta and meta.get("type") == "latest":
        data_type = "latest"
    elif meta and meta.get("type") == "data_availability":
        data_type = "availability"

    settings = (meta or {}).get("settings", {})
    timerange = (meta or {}).get("timerange", {})

    # Time-Range: Start + End extrahieren
    time_range = _extract_time_range(timerange)

    # Interval + Aggregation
    interval_agg = ""
    interval = settings.get("interval_human") or ""
    aggregation = settings.get("aggregation", "").lower()
    if interval and aggregation:
        interval_clean = interval.replace(" ", "")
        interval_agg = f"{interval_clean}_{aggregation}"

    return generate_dataset_key(
        "krc5", signal_type, data_type,
        data_mode=data_retrieval_mode,
        time_range=time_range,
        interval_agg=interval_agg,
    )


def _extract_time_range(timerange: dict) -> str:
    """
    Extrahiert Time-Range-String aus MCP timerange dict.

    Input:  {"start_human": "16.12.2025 12:00", "end_human": "16.12.2025 14:00"}
    Output: "2025-12-16_12-00_14-00"  (gleicher Tag)
    Output: "2025-12-16_12-00_2025-12-17_08-00"  (verschiedene Tage)
    """
    import re

    def parse_datetime(s: str) -> tuple[str, str]:
        """Returns (date_iso, time_hhmm) or ("", "")."""
        m = re.search(r'(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2})', s)
        if m:
            return f"{m.group(3)}-{m.group(2)}-{m.group(1)}", f"{m.group(4)}-{m.group(5)}"
        m = re.search(r'(\d{4}-\d{2}-\d{2})\s+(\d{2}):(\d{2})', s)
        if m:
            return m.group(1), f"{m.group(2)}-{m.group(3)}"
        return "", ""

    start_str = timerange.get("start_human") or timerange.get("start", "")
    end_str = timerange.get("end_human") or timerange.get("end", "")

    if not start_str:
        return ""

    start_date, start_time = parse_datetime(str(start_str))
    end_date, end_time = parse_datetime(str(end_str))

    if not start_date:
        return ""

    if start_date == end_date:
        # Gleicher Tag: "2025-12-16_12-00_14-00"
        parts = [start_date]
        if start_time:
            parts[0] += f"_{start_time}"
        if end_time:
            parts[0] += f"_{end_time}"
        return parts[0]
    else:
        # Verschiedene Tage
        start = start_date + (f"_{start_time}" if start_time else "")
        end = end_date + (f"_{end_time}" if end_time else "")
        return f"{start}_{end}"
```

**`_store_dataset_in_duckdb` aendern** (Z.760-801):
- `determine_dataset_key_legacy(data, meta)` → `determine_dataset_key_rich(data, meta, data_retrieval_mode)`
- Meta-Felder ergaenzen:
```python
dataset_meta = DatasetMeta(
    ...,
    meta={
        **(meta or {}),
        "data_mode": data_retrieval_mode,
        "interval": settings.get("interval_human", ""),
        "aggregation": settings.get("aggregation", ""),
    },
)
```

### Phase 1 Tests

- `test_duckdb_store.py`: UPSERT statt DELETE+INSERT, PRIMARY KEY Schema
- `test_data_agent_parsing.py`: `determine_dataset_key_rich` mit verschiedenen Meta-Daten
- Manuell: Query die `error_too_many_datapoints` triggert → Chart zeigt vollen Zeitraum

### Phase 1 Verifikation

```bash
python -m pytest tests/test_duckdb_store.py -v
python -m pytest tests/test_agents/test_data_agent_parsing.py -v
```

---

## Phase 2: active_dataset_keys + gefilterter Read

**Ziel:** Downstream Agents lesen nur relevante Daten.
**Dateien:** `agents/state.py`, `agents/utils.py`, `agents/data_agent.py`
**Abhaengigkeit:** Phase 1

### 2a. `agents/state.py` — Neues Feld

```python
# Nach current_data_file (ca. Z.150):
# === Aktive Dataset-Keys fuer den aktuellen Turn ===
# Wird vom Data Agent oder Supervisor gesetzt.
# Viz/Stats Agents lesen nur Daten fuer diese Keys.
# None = alle Daten (Fallback)
active_dataset_keys: list[str] | None = None
```

Kein Reducer — wird pro Turn ueberschrieben (wie `plan`, `chart_url`).

### 2b. `config/duckdb_store.py` — Neue Methode `get_data_for_datasets`

```python
def get_data_for_datasets(self, dataset_keys: list[str]) -> dict[str, list[dict]]:
    """Gibt Daten NUR fuer die angegebenen dataset_keys zurueck."""
    if not dataset_keys:
        return self.get_all_data_merged()

    placeholders = ", ".join(["?"] * len(dataset_keys))
    rows = self._conn.execute(
        f"SELECT signal_key, ts, value FROM telemetry "
        f"WHERE dataset_key IN ({placeholders}) ORDER BY signal_key, ts",
        dataset_keys,
    ).fetchall()

    result: dict[str, list[dict]] = {}
    for signal_key, ts, value in rows:
        if signal_key not in result:
            result[signal_key] = []
        result[signal_key].append({"value": str(value), "timestamp": ts})
    return result
```

### 2c. `agents/utils.py` — `get_data_from_state` filtert

```python
def get_data_from_state(state: dict) -> dict[str, list]:
    session_id = state.get("session_id", "default")
    active_keys = state.get("active_dataset_keys")  # NEU

    try:
        from config.duckdb_store import SessionStore
        if session_id in SessionStore._instances:
            store = SessionStore.get_instance(session_id)
            if store.point_count() > 0:
                if active_keys:
                    data = store.get_data_for_datasets(active_keys)
                else:
                    data = store.get_all_data_merged()
                if data:
                    return data
    except Exception as e:
        logger.debug(f"DuckDB nicht verfuegbar: {e}")

    datasets = state.get("datasets", {})
    return extract_data_from_datasets(datasets)
```

### 2d. `agents/data_agent.py` — `build_result` gibt active_keys zurueck

In `build_result()` (Z.804-855):
```python
active_keys: list[str] = []

# Im Loop wo Datasets gespeichert werden:
if meta_entry.get("point_count", 0) > 0:
    new_datasets[key] = meta_entry
    active_keys.append(key)

# Im return:
return {
    ...,
    "active_dataset_keys": active_keys or None,
}
```

### Phase 2 Tests

- Test: `active_dataset_keys` im State → `get_data_from_state` gibt nur gefilterte Daten
- Test: `active_dataset_keys = None` → Fallback auf alle Daten

### Phase 2 Verifikation

```bash
python -m pytest tests/ -m "not integration" -v
```

---

## Phase 3: Intelligenter Supervisor

**Ziel:** Supervisor entscheidet intelligent ueber Dataset-Auswahl, kann fehlende Daten
anfordern oder User-Rueckfrage stellen.
**Dateien:** `agents/supervisor.py`, `prompts/supervisor_prompt.py`
**Abhaengigkeit:** Phase 2

### 3a. Supervisor-Logik: Dataset-Auswahl

Der Supervisor bekommt im Prompt die vorhandenen Datasets mit ihren reicheren Keys
(inkl. mode, time_range, interval_agg aus Phase 1). Er kann dann:

1. **Passende Datasets auswaehlen** → `active_dataset_keys = [matching_keys]`
   - Beispiel: User fragt "Zeig nochmal die Drehmomente" → Supervisor erkennt
     dass `krc5/torque/timeseries/aggregated/2025-12-16_12-00_14-00/60s_avg` passt

2. **Fehlende Daten erkennen** → `plan = ["data_agent", "viz_agent"]`
   - Beispiel: User fragt nach Geschwindigkeit, aber nur Drehmoment-Daten vorhanden
   - Supervisor setzt `data_instructions` fuer den Data Agent

3. **User-Rueckfrage stellen** → `needs_user_input = True`
   - Beispiel: Mehrere aehnliche Datasets vorhanden, unklar welches gemeint
   - Beispiel: "Die Drehmomente" — aber es gibt raw UND aggregated

### 3b. Supervisor Prompt erweitern

In `prompts/supervisor_prompt.py` die `<loaded_data>` Sektion erweitern:
- Zeige die vollen dataset_keys (mit mode, time_range, interval)
- Instruiere den Supervisor die Keys zu analysieren und zu entscheiden
- Neues Output-Feld: `"active_dataset_keys": ["key1", "key2"]` oder `null`

### 3c. Supervisor Return erweitern

```python
return {
    "plan": final_plan,
    "reasoning": result["reasoning"],
    "current_step": 0,
    "data_retrieval_mode": data_mode,
    "data_instructions": data_instructions,
    "active_dataset_keys": result.get("active_dataset_keys"),  # NEU: vom LLM gewaehlt
    "needs_user_input": result.get("needs_user_input", False),
    "user_input_reason": result.get("user_input_reason"),
}
```

### Phase 3 Tests

- Test: Supervisor waehlt passende Keys bei Folge-Turn
- Test: Supervisor erkennt fehlende Daten und plant data_agent ein
- Test: Supervisor stellt Rueckfrage bei Mehrdeutigkeit
- `test_supervisor_planning.py` erweitern

### Phase 3 Verifikation

```bash
python -m pytest tests/test_agents/test_supervisor_planning.py -v
```

---

## Phase 4: Tests + Dokumentation + DEC-026

**Ziel:** Alles absichern, DEC-026 in DECISIONS.md dokumentieren.
**Dateien:** `tests/`, `docs/DECISIONS.md`, `CLAUDE.md`
**Abhaengigkeit:** Phase 1-3

### 4a. Unit Tests

- `test_duckdb_store.py`: UPSERT, PRIMARY KEY, `get_data_for_datasets`, `clear_dataset`
- `test_data_agent_parsing.py`: `determine_dataset_key_rich`, `_extract_time_range`
- `test_supervisor_planning.py`: active_dataset_keys Auswahl, Rueckfrage-Logik
- `test_viz_agent_messages.py`: Gefilterte Daten via active_dataset_keys

### 4b. DEC-026 dokumentieren

In `docs/DECISIONS.md` neuen Eintrag mit:
- Problem, Loesung, Key-Format, Szenarien-Tabelle
- Verweise auf Phase 1-3

### 4c. CLAUDE.md aktualisieren

- DEC-026 in die Key Patterns Tabelle
- Gotcha: `determine_dataset_key_rich` statt `_legacy` verwenden
- Gotcha: `active_dataset_keys` muss gesetzt sein fuer gefilterte Reads

---

## Szenarien-Check (alle Phasen)

| Szenario | Vorher (Bug) | Phase 1 | Phase 2 | Phase 3 |
|----------|-------------|---------|---------|---------|
| 2 Tool Calls, gleicher Key, versch. Zeitfenster | Letzter gewinnt | UPSERT akkumuliert | — | — |
| Turn 1: torque raw, Turn 2: torque aggregated | Ueberschrieben | Versch. Keys | Viz sieht nur aktive | Supervisor waehlt richtig |
| Turn 2: "Zeig nochmal die Drehmomente" | Viz sieht alles | — | Supervisor setzt alle Keys | Supervisor waehlt passende |
| Turn 2: "Zeig Geschwindigkeit" (nicht geladen) | Fehler oder leer | — | — | Supervisor plant data_agent |
| Mehrdeutige Anfrage bei mehreren Datasets | Zufaellig | — | — | Supervisor fragt User |

## Bereits erledigt (vor diesem Plan)

- [x] `supervisor.py`: `build_dataset_context` DEC-025 Fix (keys statt data)
