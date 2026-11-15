"""'Batterie-Aktion beenden' ist wie die drei anderen Batterie-Aktionen Pflicht-Test (siehe _READY_KEY_TO_LABEL_SECTION in app.py)."""
import app


def _config(**overrides):
    config = {
        "integrationMappings": {"batterie": ["entry1"]},
        "sensorMappings": {
            "battery_charge_limit_current_pv_surplus": "number.a",
            "battery_discharge_limit_current": "number.b",
            "battery_charge_limit_current": "number.c",
        },
        "controlVariant": {k: "direct" for k in app.BATTERY_DIRECT_REQUIRED_SENSOR_FIELDS} | {"battery_action_stop": "direct"},
        "actorMappings": {},
        "actionTestPassed": {},
    }
    config.update(overrides)
    return config


def _stop_warnings(config):
    return [w for w in app._action_not_ready_warnings(config) if w["key"].endswith("battery_action_stop")]


def test_stop_is_gated():
    assert "battery_action_stop" in app._READY_KEY_TO_LABEL_SECTION


def test_untested_stop_warns_once_other_actions_are_set_up():
    config = _config()
    assert len(_stop_warnings(config)) == 1
    config["actionTestPassed"]["battery_action_stop"] = app._action_type_fingerprint(config, "battery_action_stop")
    assert _stop_warnings(config) == []


def test_stop_not_required_before_other_actions_are_set_up():
    config = _config(sensorMappings={})
    assert _stop_warnings(config) == []


def test_stop_test_is_invalidated_by_variant_change():
    config = _config()
    config["actionTestPassed"]["battery_action_stop"] = app._action_type_fingerprint(config, "battery_action_stop")
    config["controlVariant"]["battery_action_stop"] = "ha_automation"
    config["actorMappings"]["battery_action_stop"] = "automation.stop"
    assert len(_stop_warnings(config)) == 1
