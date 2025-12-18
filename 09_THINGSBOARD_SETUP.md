# THINGSBOARD SETUP

> Konkrete Konfiguration fÃ¼r KRC5
> Basierend auf OPC UA Connector Config

---

## Verbindungsdaten

| Parameter | Wert |
|-----------|------|
| ThingsBoard URL | `http://localhost:8080` (anpassen!) |
| Device Name | `KRC5` |
| Device Profile | `KUKA_Robot` |
| OPC UA Server | `opc.tcp://172.31.1.147:4840/` |
| Poll-Intervall | 1000ms (Position/Velocity) |

---

## Authentifizierung

ThingsBoard API braucht JWT Token:

```bash
# Token holen
curl -X POST http://localhost:8080/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"tenant@thingsboard.org","password":"tenant"}'

# Response enthÃ¤lt: {"token": "eyJhbGc...", "refreshToken": "..."}
```

**FÃ¼r das Projekt:** Token in `.env` speichern:
```
THINGSBOARD_URL=http://localhost:8080
THINGSBOARD_USERNAME=tenant@thingsboard.org
THINGSBOARD_PASSWORD=tenant
```

---

## Device ID finden

```bash
# Alle Devices auflisten
curl -X GET "http://localhost:8080/api/tenant/devices?pageSize=100&page=0" \
  -H "X-Authorization: Bearer $TOKEN"

# Device by Name
curl -X GET "http://localhost:8080/api/tenant/devices?deviceName=KRC5" \
  -H "X-Authorization: Bearer $TOKEN"
```

**Device ID notieren:** `________-____-____-____-____________`

---

## Telemetrie-Keys (Komplett)

### Hochfrequent (ON_CHANGE, ~1Hz)

#### Achspositionen
| Key | Beschreibung | Einheit | Bereich |
|-----|--------------|---------|---------|
| `axis_act_a1_deg` | Achse 1 Position | Grad | Â±185Â° |
| `axis_act_a2_deg` | Achse 2 Position | Grad | -140Â° bis +20Â° |
| `axis_act_a3_deg` | Achse 3 Position | Grad | -120Â° bis +156Â° |
| `axis_act_a4_deg` | Achse 4 Position | Grad | Â±350Â° |
| `axis_act_a5_deg` | Achse 5 Position | Grad | Â±130Â° |
| `axis_act_a6_deg` | Achse 6 Position | Grad | Â±350Â° |

#### Gemessene Achspositionen (Encoder)
| Key | Beschreibung | Einheit |
|-----|--------------|---------|
| `axis_meas_a1_deg` | Achse 1 gemessen | Grad |
| `axis_meas_a2_deg` | Achse 2 gemessen | Grad |
| `axis_meas_a3_deg` | Achse 3 gemessen | Grad |
| `axis_meas_a4_deg` | Achse 4 gemessen | Grad |
| `axis_meas_a5_deg` | Achse 5 gemessen | Grad |
| `axis_meas_a6_deg` | Achse 6 gemessen | Grad |

#### Kartesische Position (TCP)
| Key | Beschreibung | Einheit |
|-----|--------------|---------|
| `pos_act_x_mm` | X-Position | mm |
| `pos_act_y_mm` | Y-Position | mm |
| `pos_act_z_mm` | Z-Position | mm |
| `pos_act_a_deg` | A-Orientierung | Grad |
| `pos_act_b_deg` | B-Orientierung | Grad |
| `pos_act_c_deg` | C-Orientierung | Grad |

#### Geschwindigkeiten
| Key | Beschreibung | Einheit |
|-----|--------------|---------|
| `vel_act_m_per_s` | Bahngeschwindigkeit TCP | m/s |
| `vel_axis_a1_pct` | Achse 1 Geschwindigkeit | % von Max |
| `vel_axis_a2_pct` | Achse 2 Geschwindigkeit | % |
| `vel_axis_a3_pct` | Achse 3 Geschwindigkeit | % |
| `vel_axis_a4_pct` | Achse 4 Geschwindigkeit | % |
| `vel_axis_a5_pct` | Achse 5 Geschwindigkeit | % |
| `vel_axis_a6_pct` | Achse 6 Geschwindigkeit | % |

#### Beschleunigungen
| Key | Beschreibung | Einheit |
|-----|--------------|---------|
| `acc_cp_m_per_s2` | Bahnbeschleunigung | m/sÂ² |
| `acc_ori1_deg_per_s2` | Orientierungsbeschl. 1 | Â°/sÂ² |
| `acc_ori2_deg_per_s2` | Orientierungsbeschl. 2 | Â°/sÂ² |
| `acc_axis_a1_pct` | Achse 1 Beschleunigung | % |
| `acc_axis_a2_pct` | Achse 2 Beschleunigung | % |
| `acc_axis_a3_pct` | Achse 3 Beschleunigung | % |
| `acc_axis_a4_pct` | Achse 4 Beschleunigung | % |
| `acc_axis_a5_pct` | Achse 5 Beschleunigung | % |
| `acc_axis_a6_pct` | Achse 6 Beschleunigung | % |

#### Status
| Key | Beschreibung | Werte |
|-----|--------------|-------|
| `pro_state` | Programmstatus | 0=Stop, 1=Run, ... |
| `override_pct` | Override | 0-100% |

---

### Mittelfrequent (ON_CHANGE_OR_REPORT, 5s)

#### Drehmomente
| Key | Beschreibung | Einheit |
|-----|--------------|---------|
| `torque_act_a1_nm` | Achse 1 Ist-Moment | Nm |
| `torque_act_a2_nm` | Achse 2 Ist-Moment | Nm |
| `torque_act_a3_nm` | Achse 3 Ist-Moment | Nm |
| `torque_act_a4_nm` | Achse 4 Ist-Moment | Nm |
| `torque_act_a5_nm` | Achse 5 Ist-Moment | Nm |
| `torque_act_a6_nm` | Achse 6 Ist-Moment | Nm |
| `torque_cmd_a1_nm` | Achse 1 Soll-Moment | Nm |
| `torque_cmd_a2_nm` | Achse 2 Soll-Moment | Nm |
| `torque_cmd_a3_nm` | Achse 3 Soll-Moment | Nm |
| `torque_cmd_a4_nm` | Achse 4 Soll-Moment | Nm |
| `torque_cmd_a5_nm` | Achse 5 Soll-Moment | Nm |
| `torque_cmd_a6_nm` | Achse 6 Soll-Moment | Nm |

#### Auslastung
| Key | Beschreibung | Einheit |
|-----|--------------|---------|
| `utilization_current` | Aktuelle Auslastung | 0-1 |
| `utilization_moving_max` | Gleitender Max-Wert | 0-1 |

---

### Niederfrequent (ON_REPORT, 60s)

| Key | Beschreibung | Einheit |
|-----|--------------|---------|
| `energy_period_kwh` | Energie pro Minute | kWh |

---

## Attributes (Statisch)

| Key | Beschreibung | Einheit |
|-----|--------------|---------|
| `mode_op_raw` | Betriebsmodus | Enum |
| `could_start_motion` | Bewegung mÃ¶glich | Boolean |
| `collmon_active` | KollisionsÃ¼berwachung | Boolean |
| `load_mass_kg` | Lastmasse | kg |
| `load_com_x_mm` | Lastschwerpunkt X | mm |
| `load_com_y_mm` | Lastschwerpunkt Y | mm |
| `load_com_z_mm` | Lastschwerpunkt Z | mm |
| `tool_x_mm` - `tool_c_deg` | Werkzeugdaten | mm/Grad |
| `holding_torque_a1_nm` - `a6` | Haltemomente | Nm |
| `torqmon_a1_pct` - `a6` | MomentÃ¼berwachung | % |
| `energy_total_kwh` | Gesamtenergie | kWh |
| `energy_total_time_s` | Gesamtlaufzeit | s |
| `utilization_longterm_max` | Langzeit-Max | 0-1 |

---

## API-Beispiele

### Latest Telemetry (aktuellster Wert)
```bash
GET /api/plugins/telemetry/DEVICE/{deviceId}/values/timeseries?keys=axis_act_a1_deg,vel_act_m_per_s
```

### Telemetry Zeitreihe
```bash
GET /api/plugins/telemetry/DEVICE/{deviceId}/values/timeseries?keys=axis_act_a1_deg&startTs=1702800000000&endTs=1702886400000
```

### Aggregierte Telemetry
```bash
GET /api/plugins/telemetry/DEVICE/{deviceId}/values/timeseries?keys=axis_act_a1_deg&startTs=...&endTs=...&interval=3600000&agg=AVG
```

### Attributes
```bash
GET /api/plugins/telemetry/DEVICE/{deviceId}/values/attributes?keys=load_mass_kg,holding_torque_a1_nm
```

---

## Datenmenge-SchÃ¤tzung

| Frequenz | Keys | Datenpunkte/Stunde |
|----------|------|-------------------|
| 1 Hz | ~36 | 129.600 |
| 0.2 Hz (5s) | ~14 | 10.080 |
| 0.017 Hz (60s) | 1 | 60 |
| **Gesamt** | 51 | ~140.000/h |

**â†’ Bei Abfragen >1h: Aggregation nutzen!**

---

## Test-Befehle

Vor dem Programmieren testen:

```bash
# 1. Token holen
TOKEN=$(curl -s -X POST http://localhost:8080/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"tenant@thingsboard.org","password":"tenant"}' | jq -r '.token')

# 2. Device ID holen
DEVICE_ID=$(curl -s -X GET "http://localhost:8080/api/tenant/devices?deviceName=KRC5" \
  -H "X-Authorization: Bearer $TOKEN" | jq -r '.data[0].id.id')

# 3. Aktuelle Achse 1 Position
curl -s "http://localhost:8080/api/plugins/telemetry/DEVICE/$DEVICE_ID/values/timeseries?keys=axis_act_a1_deg" \
  -H "X-Authorization: Bearer $TOKEN" | jq

# 4. Letzte 10 Minuten Drehmoment
START_TS=$(($(date +%s)*1000 - 600000))
END_TS=$(($(date +%s)*1000))
curl -s "http://localhost:8080/api/plugins/telemetry/DEVICE/$DEVICE_ID/values/timeseries?keys=torque_act_a1_nm&startTs=$START_TS&endTs=$END_TS" \
  -H "X-Authorization: Bearer $TOKEN" | jq
```

---

## Checkliste vor Implementierung

- [ ] ThingsBoard lÃ¤uft und erreichbar
- [ ] OPC UA Connector aktiv
- [ ] KRC5 Device in ThingsBoard sichtbar
- [ ] Telemetrie-Daten flieÃŸen (Dashboard prÃ¼fen)
- [ ] API-Token funktioniert (curl Test)
- [ ] Device ID notiert
- [ ] `.env` Datei angelegt
