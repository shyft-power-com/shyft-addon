from sync_service import (heating_rod_active, heating_rod_power_kw, legacy_hp_power_label, dhw_max_temp_c,
                          HEATING_ROD_MAX_POWER_KW_LIMIT)


def _config(**extra):
    config = {"integrationMappings": {"heizstab": ["rod-1"]}}
    config.update(extra)
    return config


def test_toggle_needs_a_device():
    assert not heating_rod_active({"integrationMappings": {}, "heatingRodControl": True})
    assert heating_rod_active(_config(heatingRodControl=True))
    assert not heating_rod_active(_config(heatingRodControl=False))


def test_legacy_toggle_key_is_used_without_new_key():
    assert heating_rod_active(_config())                              # früher: Standard an
    assert not heating_rod_active(_config(heatingRodEnabled=False))
    assert not heating_rod_active(_config(heatingRodEnabled=True, heatingRodControl=False))


def test_power_is_a_free_number_clamped_to_0_30_kw():
    assert heating_rod_power_kw({"heatingRodMaxPowerKw": 2.5}) == 2.5
    assert heating_rod_power_kw({"heatingRodMaxPowerKw": "7,5".replace(",", ".")}) == 7.5
    assert heating_rod_power_kw({"heatingRodMaxPowerKw": 99}) == HEATING_ROD_MAX_POWER_KW_LIMIT
    assert heating_rod_power_kw({"heatingRodMaxPowerKw": -3}) == 0.0
    assert heating_rod_power_kw({}) is None


def test_power_falls_back_to_the_old_stage_selection():
    assert heating_rod_power_kw({"heatingRodMaxPower": "mittel (6 kW)"}) == 6.0
    assert heating_rod_power_kw({"heatingRodMaxPower": "klein (4 kW)", "heatingRodMaxPowerKw": 3}) == 3.0


def test_legacy_label_is_the_nearest_electric_stage():
    assert legacy_hp_power_label(2) == "klein (4 kW)"
    assert legacy_hp_power_label(3.4) == "mittel (6 kW)"
    assert legacy_hp_power_label(4) == "groß (8 kW)"
    assert legacy_hp_power_label(30) == "sehr groß (12 kW)"


def test_temperature_limit_belongs_to_the_active_device():
    config = _config(hpMaxSupplyTempC=60, heatingRodMaxTempC=90)
    assert dhw_max_temp_c({**config, "heatingRodControl": True}) == 90.0
    assert dhw_max_temp_c({**config, "heatingRodControl": False}) == 60.0
    assert dhw_max_temp_c(_config(heatingRodControl=True)) == 95.0     # Heizstab-Standard
    assert dhw_max_temp_c({"integrationMappings": {}}) == 55.0         # Wärmepumpen-Standard


def test_electric_power_is_sent_one_to_one_for_the_rod_and_halved_thermal_power_for_the_heat_pump():
    from sync_service import hp_max_power_electric_kw
    rod = _config(heatingRodControl=True, heatingRodMaxPowerKw=7.5, hpMaxPower="mittel (6 kW)")
    assert hp_max_power_electric_kw(rod) == 7.5                       # Heizstab: 1:1
    heat_pump = _config(heatingRodControl=False, heatingRodMaxPowerKw=7.5, hpMaxPower="mittel (6 kW)")
    assert hp_max_power_electric_kw(heat_pump) == 3.0                 # Wärmepumpe: Hälfte der thermischen Leistung
    assert hp_max_power_electric_kw({"integrationMappings": {}, "hpMaxPower": "groß (8 kW)"}) == 4.0
    assert hp_max_power_electric_kw({"integrationMappings": {}}) is None


def test_rod_status_comes_from_the_control_switch_not_from_a_sensor_field():
    from sync_service import mapped_entity_id
    mappings = {"heatpump_dhw_on_off": "binary_sensor.waermepumpe_ww", "heating_rod_switch": "switch.heizstab"}
    rod = _config(heatingRodControl=True, sensorMappings=mappings)
    assert mapped_entity_id(rod, "heatpump_dhw_on_off") == "switch.heizstab"
    heat_pump = _config(heatingRodControl=False, sensorMappings=mappings)
    assert mapped_entity_id(heat_pump, "heatpump_dhw_on_off") == "binary_sensor.waermepumpe_ww"
    # ohne zugeordneten Schalter bleibt es bei der bisherigen Zuordnung; andere Sensoren sind nie betroffen
    assert mapped_entity_id(_config(heatingRodControl=True, sensorMappings={"heatpump_dhw_on_off": "x"}), "heatpump_dhw_on_off") == "x"
    assert mapped_entity_id(rod, "heatpump_dhw_tank_temp") == ""
