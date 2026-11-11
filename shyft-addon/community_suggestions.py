"""Community-Vorschlaege: erfolgreich getestete Konfigurationen anonym an shyft-power melden und fuer neue
Nutzer derselben Integration als Vorbelegung abrufen.

Bubble kennt nur den Typ ha-app_suggestion (slot, ha_integration, steps_json, used). Ein "Slot" ist ein
Konfigurationsfeld des Addons:
  sensor:<feld>   sensorMappings[feld]  (eine Entitaet)
  actor:<feld>    actorMappings[feld]   (eine Entitaet)
  recipe:hot_water / recipe:car_charge   (Service-Rezept, bis zu 3 Stufen)

Nichts Nutzerspezifisches wird gemeldet: statt der (umbenennbaren) entity_id steht dort ein stabiler
Entitaets-Schluessel "<Integrations-Domain>/<translation_key oder original_name>" aus der HA-Entity-Registry.
Schluessel, Service-Namen und feste Auswahlwerte (z.B. "eco") sind fuer alle Nutzer einer Integration gleich;
Zahlenwerte, Geraete-IDs und Entitaeten ohne stabilen Schluessel (HA-Helfer, Automationen) bleiben draussen.
"""
import json
import re

MAX_STAGES = 3
ENTITY_PREFIX = "@e:"
DEVICE_MARKER = "@dev"
_DEVICE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_NUMBER_RE = re.compile(r"^-?\d+([.,]\d+)?$")
_ENTITY_ID_RE = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")

# Section der Geraetekachel -> Praefixe ihrer sensorMappings-Schluessel (fuer die "uebrigen Sensoren")
SECTION_SENSOR_PREFIXES = {
    "waermepumpe": ("heatpump_",),
    "batterie": ("battery_",),
    "wallbox": ("wallbox_",),
    "auto": ("electronicvehicle_",),
    "wechselrichter": ("photovoltaic_",),
}

# Rezept-Slots: Config-Schluessel -> (Slot-Name, Stufen in fester Reihenfolge; None = die Rezept-Stufe selbst)
RECIPE_SLOTS = {
    "hotWaterRecipe": ("recipe:hot_water", (None,)),
    "carChargeRecipe": ("recipe:car_charge", ("phaseCount", "amperage", "control")),
}


def _clean(text):
    "Schluessel ohne Zeichen, die das JSON-Escaping der Bubble-Antwort stoeren koennten."
    text = re.sub(r"[\\\"\x00-\x1f]", "", str(text or ""))
    return re.sub(r"\s+", " ", text).strip().lower()


# Selbst gebaute Entitaeten eines Nutzers (u.a. das vom Add-on verwaltete Hilfsskript script.shyft_*): gibt es beim
# naechsten Nutzer nicht bzw. nur zufaellig - sie sind kein Teil einer Integrations-Konfiguration und werden weder gemeldet noch vorbelegt.
LOCAL_PLATFORMS = ("script", "automation", "scene", "group", "template")


def build_entity_info(entities):
    """Entity-Registry-Liste -> {entity_id: {"ref": "<platform>/<key>"}}; Eintraege ohne platform oder
    ohne stabilen Schluessel (translation_key bzw. original_name) sowie Skripte/Automationen/Szenen/Gruppen/Templates
    (LOCAL_PLATFORMS) und Helfer (input_*) fehlen."""
    info = {}
    for entity in entities or []:
        platform = _clean(entity.get("platform"))
        if platform in LOCAL_PLATFORMS or platform.startswith("input_"):
            continue
        key = _clean(entity.get("translation_key") or entity.get("original_name"))
        if platform and key and entity.get("entity_id"):
            info[entity["entity_id"]] = {"ref": f"{platform}/{key}"}
    return info


def build_ref_index(info):
    "ref -> erste entity_id des Nutzers mit diesem Schluessel (bei mehreren gleichen gilt die erste)."
    index = {}
    for entity_id, entry in (info or {}).items():
        index.setdefault(entry["ref"], entity_id)
    return index


def _ref_for(entity_id, info):
    return ((info or {}).get(entity_id) or {}).get("ref")


def _normalize_service_block(block, info):
    "{service, sharedFields, amountFields} -> kompakter Block, oder None wenn nicht uebertragbar."
    service = _clean((block or {}).get("service"))
    if not service:
        return None
    fields = {}
    for name, value in ((block or {}).get("sharedFields") or {}).items():
        if not isinstance(value, str) or not value:
            continue
        if _DEVICE_ID_RE.match(value):
            fields[name] = DEVICE_MARKER
        elif _ENTITY_ID_RE.match(value) and value in (info or {}):
            fields[name] = ENTITY_PREFIX + info[value]["ref"]
        elif _ENTITY_ID_RE.match(value) or _NUMBER_RE.match(value.strip()):
            return None  # Entitaet ohne stabilen Schluessel bzw. Zahlenwert: nicht uebertragbar / nutzerspezifisch
        else:
            if re.search(r'[\\"\x00-\x1f]', value):
                return None  # wuerde das JSON-Escaping der Bubble-Antwort stoeren
            fields[name] = value  # fester Auswahlwert unveraendert (Gross/Klein zaehlt in HA)
    block_out = {"s": service, "f": fields}
    amount = [name for name in ((block or {}).get("amountFields") or []) if isinstance(name, str)]
    if amount:
        block_out["a"] = amount
    return block_out


def _normalize_stage(stage, info):
    "Rezept-Stufe (ein Befehl oder Befehl je Zweig) -> Stufe fuer steps_json, oder None."
    stage = stage or {}
    if "branches" in stage:
        branches = {}
        for key, block in (stage["branches"] or {}).items():
            normalized = _normalize_service_block(block, info)
            if normalized is None:
                return None
            branches[key] = normalized
        return {"b": branches} if branches else None
    return _normalize_service_block(stage, info)


def _canonical(steps):
    return json.dumps(steps, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def build_report_items(config, ready_key, info, include_remaining_sensors_for=None, allowed_entity_ids=None):
    """Alles, was nach einem bestandenen Aktionstest zu melden ist: Liste von (slot, steps_json).
    ready_key: der Aktionstyp (siehe _READY_KEY_TO_LABEL_SECTION in app.py). include_remaining_sensors_for:
    section_key der Kachel, deren uebrige Sensoren mitgehen (nur beim letzten bestandenen Test der Kachel);
    allowed_entity_ids: nur Sensoren, die zur gewaehlten Integration gehoeren."""
    items = []
    sensors = config.get("sensorMappings") or {}
    actors = config.get("actorMappings") or {}

    def add_entity(slot_kind, field, entity_id):
        ref = _ref_for(entity_id, info) if isinstance(entity_id, str) else None
        if ref:
            items.append((f"{slot_kind}:{field}", _canonical([{"e": ref}])))

    for field in _required_entity_fields(config, ready_key):
        source, name = field
        add_entity("sensor" if source == "sensor" else "actor", name, (sensors if source == "sensor" else actors).get(name))

    recipe_key = {"hot_water": "hotWaterRecipe", "car_charge_start": "carChargeRecipe"}.get(ready_key)
    if recipe_key:
        recipe = config.get(recipe_key) or {}
        if recipe.get("type") != "ha_automation":
            slot, stage_keys = RECIPE_SLOTS[recipe_key]
            stages = [_normalize_stage(recipe if key is None else recipe.get(key), info) for key in stage_keys]
            if all(stages) and len(stages) <= MAX_STAGES:
                steps = [dict(stage, k=key) if key else stage for key, stage in zip(stage_keys, stages)]
                items.append((slot, _canonical(steps)))

    if include_remaining_sensors_for:
        prefixes = SECTION_SENSOR_PREFIXES.get(include_remaining_sensors_for, ())
        already = {slot for slot, _ in items}
        for field, entity_id in sensors.items():
            if not field.startswith(prefixes) or not isinstance(entity_id, str):
                continue
            if allowed_entity_ids is not None and entity_id not in allowed_entity_ids:
                continue
            if f"sensor:{field}" not in already:
                add_entity("sensor", field, entity_id)
    return items


def _required_entity_fields(config, ready_key):
    "Einzel-Entitaeten, die ein Aktionstyp zwingend braucht: [('sensor'|'actor', feldname)]."
    from_app = {
        "heating_rod": [("sensor", "heating_rod_switch")],
        "hot_water": [("sensor", "heatpump_dhw_target_temp")],
        "heating_target_temp": [("sensor", "heatpump_heating_target_temp_normal"), ("actor", "heating_target_temp")],
        "battery_charge_shift_pv_surplus": [("sensor", "battery_charge_limit_current_pv_surplus"), ("actor", "battery_charge_shift_pv_surplus")],
        "battery_discharge_shift": [("sensor", "battery_discharge_limit_current"), ("actor", "battery_discharge_shift")],
        "battery_grid_charge": [("sensor", "battery_charge_limit_current"), ("actor", "battery_grid_charge")],
    }
    return from_app.get(ready_key, [])


def parse_rows(raw):
    "Bubble-Antwort (JSON-Liste oder Text davon) -> [{slot, steps (Liste), used}]; kaputte Zeilen entfallen."
    try:
        rows = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    except ValueError:
        return []
    out = []
    for row in rows if isinstance(rows, list) else []:
        try:
            out.append({"slot": str(row["slot"]), "steps": json.loads(row["steps"]), "used": int(row.get("used") or 0)})
        except (KeyError, TypeError, ValueError):
            continue
    return out


def drop_own_reports(rows, reported, domain):
    """Eigene Meldungen sind kein Vorschlag fuer den Meldenden selbst: eine Zeile, die dieses Add-on genau so gemeldet hat
    (reported: {"<domain>|<slot>": steps_json}, siehe COMMUNITY_REPORTED_PATH in app.py), wird nicht zurueckgespielt. shyft-power
    liefert bewusst keinen Zaehler mit (er liesse Rueckschluesse auf die Nutzerzahl zu), nur die Reihenfolge nach Haeufigkeit - deshalb
    faellt eine eigene Zuordnung auch dann weg, wenn andere sie ebenfalls gemeldet haben; der Nutzer hat sie ja schon."""
    return [row for row in rows if (reported or {}).get(f"{domain}|{row['slot']}") != _canonical(row["steps"])]


def _resolve_block(block, index, device_id):
    "Block aus steps_json -> Config-Block {service, sharedFields, amountFields}; None, wenn der Nutzer eine Entitaet nicht hat."
    fields = {}
    for name, value in (block.get("f") or {}).items():
        if value == DEVICE_MARKER:
            if device_id:
                fields[name] = device_id
        elif isinstance(value, str) and value.startswith(ENTITY_PREFIX):
            entity_id = index.get(value[len(ENTITY_PREFIX):])
            if not entity_id:
                return None
            fields[name] = entity_id
        else:
            fields[name] = value
    out = {"service": block.get("s", ""), "sharedFields": fields}
    if block.get("a"):
        out["amountFields"] = list(block["a"])
    return out


def resolve_suggestions(rows, index, device_id=None, per_slot=3):
    """rows (parse_rows) + ref-Index des Nutzers -> {slot: [{"value": <Config-Fragment>, "used": n}, ...]},
    je Slot die haeufigsten per_slot, nur Vorschlaege, die auf Entitaeten des Nutzers passen.
    Sensor-/Actor-Slots liefern eine entity_id als value, Rezept-Slots ein Dict (Stufen-Schluessel -> Stufe)."""
    result = {}
    for row in sorted(rows, key=lambda r: -r["used"]):
        slot, steps = row["slot"], row["steps"]
        if not isinstance(steps, list) or not steps or len(steps) > MAX_STAGES:
            continue
        if slot.startswith(("sensor:", "actor:")):
            entity_id = index.get(steps[0].get("e")) if isinstance(steps[0], dict) else None
            value = entity_id
        else:
            value = {}
            for step in steps:
                stage_key = step.get("k") or "main"
                if "b" in step:
                    branches = {k: _resolve_block(b, index, device_id) for k, b in step["b"].items()}
                    block = {"branches": branches} if all(branches.values()) else None
                else:
                    block = _resolve_block(step, index, device_id)
                if block is None:
                    value = None
                    break
                value[stage_key] = block
        bucket = result.setdefault(slot, [])
        if value and len(bucket) < per_slot and all(entry["value"] != value for entry in bucket):
            bucket.append({"value": value, "used": row["used"]})
    return {slot: entries for slot, entries in result.items() if entries}


# ---- Sensor-Zuordnungen ohne Aktionstest ----------------------------------------------------------------------------
# Kacheln ohne Aktion (Wechselrichter, Netzsensor, ...) haben keinen Test, der eine Meldung ausloest. Dort gilt ein Sensor als
# brauchbar, wenn er gerade einen plausiblen Wert liefert (siehe plausible_sensor_value) - das Add-on meldet ihn dann einmal je
# Zuordnung (siehe report_plausible_sensor_suggestions in app.py).
AMBIGUOUS_STATES = {"", "unknown", "unavailable", "none", "null", "nan"}

# Feld -> ("num", min, max, einheit) | ("onoff",) | ("state",). Zahlen: Leistungen in kW (W wird umgerechnet), Temperaturen in °C, Ladestand in %.
SENSOR_RULES = {
    "photovoltaic_powerflow_pv": ("num", -0.1, 1000, "kw"),
    "photovoltaic_powerflow_load": ("num", -0.1, 1000, "kw"),
    "photovoltaic_powerflow_grid": ("num", -1000, 1000, "kw"),
    "photovoltaic_powerflow_battery": ("num", -1000, 1000, "kw"),
    "battery_state_of_charge": ("num", 0, 100, ""),
    "battery_charge_limit_current": ("num", 0, 1000, "kw"),
    "battery_charge_limit_current_pv_surplus": ("num", 0, 1000, "kw"),
    "battery_discharge_limit_current": ("num", 0, 1000, "kw"),
    "battery_storage_command_mode": ("state",),
    "heatpump_dhw_tank_temp": ("num", -30, 120, ""),
    "heatpump_dhw_target_temp": ("num", -30, 120, ""),
    "heatpump_heating_target_temp_normal": ("num", -30, 120, ""),
    "heatpump_supply_temp_hp": ("num", -30, 120, ""),
    "heatpump_temp_indoor_measured": ("num", -30, 60, ""),
    "heatpump_current_power_elect": ("num", -0.1, 100, "kw"),
    "heatpump_dhw_activated": ("onoff",),
    "heatpump_dhw_on_off": ("onoff",),
    "heatpump_heating_activated": ("onoff",),
    "heatpump_on_off": ("onoff",),
    "electronicvehicle_state_of_charge": ("num", 0, 100, ""),
    "wallbox_current_charging_power": ("num", -0.1, 1000, "kw"),
    "wallbox_plugged": ("state",),
}


def _finite_number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in (float("inf"), float("-inf")) else None


def plausible_sensor_value(field, state, unit=None):
    """Liefert der Sensor `field` mit Zustand `state` (und Einheit `unit`) gerade einen brauchbaren Wert? Unbekannte Felder: nein."""
    rule = SENSOR_RULES.get(field)
    if rule is None:
        return False
    text = str(state if state is not None else "").strip().lower()
    if rule[0] == "onoff":
        return text in ("on", "off")
    if rule[0] == "state":
        return text not in AMBIGUOUS_STATES
    number = _finite_number(state)
    if number is None:
        return False
    if rule[3] == "kw" and unit in ("W", "w"):
        number /= 1000
    return rule[1] <= number <= rule[2]


def build_sensor_items(config, section_key, info, allowed_entity_ids, states):
    """Sensor-Zuordnungen der Kachel section_key, die gerade einen plausiblen Wert liefern: Liste von (slot, steps_json).
    states: {entity_id: {"state": ..., "unit": ...}}; allowed_entity_ids: nur Entitaeten der gewaehlten Integration."""
    prefixes = SECTION_SENSOR_PREFIXES.get(section_key, ())
    items = []
    for field, entity_id in (config.get("sensorMappings") or {}).items():
        if not prefixes or not field.startswith(prefixes) or not isinstance(entity_id, str):
            continue
        if allowed_entity_ids is not None and entity_id not in allowed_entity_ids:
            continue
        current = (states or {}).get(entity_id)
        if not current or not plausible_sensor_value(field, current.get("state"), current.get("unit")):
            continue
        ref = _ref_for(entity_id, info)
        if ref:
            items.append((f"sensor:{field}", _canonical([{"e": ref}])))
    return items
