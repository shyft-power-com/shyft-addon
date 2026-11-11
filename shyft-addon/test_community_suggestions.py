import json

import community_suggestions as cs

ENTITIES = [
    {"entity_id": "button.my_renamed_start", "platform": "easee", "translation_key": "start_charging"},
    {"entity_id": "number.second_charger_limit", "platform": "easee", "translation_key": "dynamic_limit"},
    {"entity_id": "number.charger_limit", "platform": "easee", "translation_key": "dynamic_limit"},
    {"entity_id": "sensor.legacy", "platform": "easee", "original_name": "Battery  SoC"},
    {"entity_id": "input_boolean.helper", "platform": "input_boolean"},  # kein stabiler Schluessel
]


def test_entity_info_uses_platform_and_stable_key_and_skips_helpers():
    info = cs.build_entity_info(ENTITIES)
    assert info["button.my_renamed_start"]["ref"] == "easee/start_charging"
    assert info["sensor.legacy"]["ref"] == "easee/battery soc"
    assert "input_boolean.helper" not in info


def test_ref_index_takes_first_of_several_equal_entities():
    index = cs.build_ref_index(cs.build_entity_info(ENTITIES))
    assert index["easee/dynamic_limit"] == "number.second_charger_limit"


def test_report_entity_slot_and_roundtrip_to_other_user():
    info = cs.build_entity_info(ENTITIES)
    config = {"sensorMappings": {"heating_rod_switch": "sensor.legacy"}}
    items = cs.build_report_items(config, "heating_rod", info)
    assert items == [("sensor:heating_rod_switch", '[{"e":"easee/battery soc"}]')]
    # anderer Nutzer: gleiche Entitaet unter anderer entity_id
    other = cs.build_ref_index(cs.build_entity_info([{"entity_id": "sensor.xyz", "platform": "easee", "original_name": "battery soc"}]))
    rows = [{"slot": items[0][0], "steps": json.loads(items[0][1]), "used": 1}]
    assert cs.resolve_suggestions(rows, other) == {"sensor:heating_rod_switch": [{"value": "sensor.xyz", "used": 1}]}


def test_suggestion_dropped_if_user_lacks_entity():
    rows = [{"slot": "sensor:x", "steps": [{"e": "easee/nope"}], "used": 5}]
    assert cs.resolve_suggestions(rows, cs.build_ref_index(cs.build_entity_info(ENTITIES))) == {}


def test_recipe_with_branches_numbers_dropped_and_device_replaced():
    info = cs.build_entity_info(ENTITIES)
    config = {"carChargeRecipe": {
        "type": "three_stage",
        "phaseCount": {"branches": {"1": {"service": "easee.set_phase", "sharedFields": {"device_id": "a" * 32, "mode": "one"}},
                                    "3": {"service": "easee.set_phase", "sharedFields": {"device_id": "a" * 32, "mode": "three"}}}},
        "amperage": {"service": "number.set_value", "sharedFields": {"entity_id": "number.charger_limit", "ttl": "300"}, "amountFields": ["value"]},
        "control": {"branches": {"start": {"service": "button.press", "sharedFields": {"entity_id": "button.my_renamed_start"}},
                                 "stop": {"service": "button.press", "sharedFields": {"entity_id": "button.my_renamed_start"}}}}}}
    # Zahlenwert "300" ist nutzerspezifisch -> ganzes Rezept nicht uebertragbar
    assert cs.build_report_items(config, "car_charge_start", info) == []
    del config["carChargeRecipe"]["amperage"]["sharedFields"]["ttl"]
    (slot, steps_json), = cs.build_report_items(config, "car_charge_start", info)
    assert slot == "recipe:car_charge" and "a" * 32 not in steps_json and "number.charger_limit" not in steps_json
    other_info = cs.build_entity_info(ENTITIES)
    resolved = cs.resolve_suggestions([{"slot": slot, "steps": json.loads(steps_json), "used": 2}],
                                      cs.build_ref_index(other_info), device_id="dev123")
    value = resolved[slot][0]["value"]
    assert value["phaseCount"]["branches"]["1"]["sharedFields"] == {"device_id": "dev123", "mode": "one"}
    assert value["amperage"] == {"service": "number.set_value", "sharedFields": {"entity_id": "number.second_charger_limit"}, "amountFields": ["value"]}
    assert value["control"]["branches"]["stop"]["service"] == "button.press"


def test_ha_automation_recipe_is_ignored():
    assert cs.build_report_items({"hotWaterRecipe": {"type": "ha_automation", "haAutomationEntityId": "automation.x"}}, "hot_water", {}) == []


def test_remaining_sensors_only_for_section_and_allowed_entities():
    info = cs.build_entity_info(ENTITIES)
    config = {"sensorMappings": {"wallbox_plugged": "sensor.legacy", "battery_state_of_charge": "sensor.legacy", "wallbox_other": "sensor.elsewhere"}}
    items = cs.build_report_items(config, "car_charge_start", info, include_remaining_sensors_for="wallbox", allowed_entity_ids={"sensor.legacy"})
    assert [slot for slot, _ in items] == ["sensor:wallbox_plugged"]


def test_top_three_per_slot_by_used():
    index = {f"p/k{i}": f"sensor.e{i}" for i in range(5)}
    rows = [{"slot": "sensor:a", "steps": [{"e": f"p/k{i}"}], "used": i} for i in range(5)]
    got = cs.resolve_suggestions(rows, index)["sensor:a"]
    assert [g["value"] for g in got] == ["sensor.e4", "sensor.e3", "sensor.e2"]


def test_parse_rows_tolerates_garbage():
    raw = json.dumps([{"slot": "sensor:a", "steps": "[{\"e\":\"p/k\"}]", "used": 2}, {"slot": "x"}, {"slot": "y", "steps": "{{"}])
    assert cs.parse_rows(raw) == [{"slot": "sensor:a", "steps": [{"e": "p/k"}], "used": 2}]
    assert cs.parse_rows("not json") == []


def test_hot_water_recipe_roundtrip_uses_main_stage():
    info = cs.build_entity_info(ENTITIES)
    config = {"hotWaterRecipe": {"type": "direct", "service": "button.press", "sharedFields": {"entity_id": "button.my_renamed_start"}}}
    (slot, steps_json), = cs.build_report_items(config, "hot_water", info)
    assert slot == "recipe:hot_water"
    resolved = cs.resolve_suggestions([{"slot": slot, "steps": json.loads(steps_json), "used": 1}],
                                      cs.build_ref_index(cs.build_entity_info([{"entity_id": "button.other", "platform": "easee", "translation_key": "start_charging"}])))
    assert resolved[slot][0]["value"] == {"main": {"service": "button.press", "sharedFields": {"entity_id": "button.other"}}}


def test_own_scripts_and_automations_are_never_reported_or_suggested():
    entities = ENTITIES + [
        {"entity_id": "script.shyft_heizung_soll_temperatur", "platform": "script", "original_name": "Shyft: Heizung Soll-Temperatur"},
        {"entity_id": "automation.mine", "platform": "automation", "original_name": "Meine Automation"},
    ]
    info = cs.build_entity_info(entities)
    assert "script.shyft_heizung_soll_temperatur" not in info and "automation.mine" not in info
    config = {"sensorMappings": {"heatpump_heating_target_temp_normal": "sensor.legacy"},
              "actorMappings": {"heating_target_temp": "script.shyft_heizung_soll_temperatur"}}
    slots = [slot for slot, _ in cs.build_report_items(config, "heating_target_temp", info)]
    assert slots == ["sensor:heatpump_heating_target_temp_normal"]


def test_plausible_sensor_values():
    p = cs.plausible_sensor_value
    assert p("photovoltaic_powerflow_grid", "-1.5", "kW") and p("photovoltaic_powerflow_grid", "1500", "W")
    assert p("photovoltaic_powerflow_pv", "0.0", "kW")  # nachts 0 ist plausibel
    assert not p("photovoltaic_powerflow_pv", "unavailable", "kW")
    assert not p("photovoltaic_powerflow_pv", "5000000", "W")  # 5000 kW
    assert not p("battery_state_of_charge", "120", "%") and p("battery_state_of_charge", "65", "%")
    assert p("heatpump_on_off", "on") and not p("heatpump_on_off", "unknown")
    assert p("battery_storage_command_mode", "Maximize Self Consumption") and not p("battery_storage_command_mode", "")
    assert not p("not_a_known_field", "1")


def test_sensor_items_only_plausible_allowed_and_stable_entities():
    info = cs.build_entity_info([
        {"entity_id": "sensor.grid_w", "platform": "solaredge", "translation_key": "ac_power"},
        {"entity_id": "sensor.pv_dead", "platform": "solaredge", "translation_key": "dc_power"},
        {"entity_id": "sensor.foreign", "platform": "other", "translation_key": "grid"},
    ])
    config = {"sensorMappings": {
        "photovoltaic_powerflow_grid": "sensor.grid_w", "photovoltaic_powerflow_pv": "sensor.pv_dead",
        "photovoltaic_powerflow_load": "sensor.foreign", "photovoltaic_powerflow_battery": "static_on",
        "heatpump_dhw_tank_temp": "sensor.grid_w"}}
    states = {"sensor.grid_w": {"state": "800", "unit": "W"}, "sensor.pv_dead": {"state": "unavailable"},
              "sensor.foreign": {"state": "1.0", "unit": "kW"}}
    items = cs.build_sensor_items(config, "wechselrichter", info, {"sensor.grid_w", "sensor.pv_dead"}, states)
    assert items == [("sensor:photovoltaic_powerflow_grid", json.dumps([{"e": "solaredge/ac_power"}], separators=(",", ":")))]
    assert cs.build_sensor_items(config, "kachel_ohne_sensoren", info, None, states) == []
