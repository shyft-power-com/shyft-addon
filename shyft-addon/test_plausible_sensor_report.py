"""Sensor-Zuordnungen mit plausiblem Wert werden als Community-Vorschlag gemeldet - je Zuordnung nur einmal
(siehe report_plausible_sensor_suggestions in app.py)."""
import json

import app


class FakeHA:
    def get_integrations_and_entities(self):
        return {
            "integrations": [{"id": "entry1", "domain": "solaredge"}],
            "entityMap": {"entry1": ["sensor.grid"]},
            "entityInfo": {"sensor.grid": {"ref": "solaredge/ac_power"}},
        }

    def get_from_homeassistant(self, path, timeout=None):
        return [{"entity_id": "sensor.grid", "state": "800", "attributes": {"unit_of_measurement": "W"}}]


class FakeShyft:
    bubble_token = "x|123|y"

    def __init__(self):
        self.reported = []

    def report_suggestion(self, slot, domain, steps_json):
        self.reported.append((slot, domain, steps_json))


def _setup(monkeypatch, tmp_path, config):
    shyft = FakeShyft()
    monkeypatch.setattr(app, "shyft_adapter", shyft)
    monkeypatch.setattr(app, "homeassistant_adapter", FakeHA())
    monkeypatch.setattr(app, "is_demo_mode", lambda: False)
    monkeypatch.setattr(app, "_read_current_config", lambda: config)
    monkeypatch.setattr(app, "COMMUNITY_REPORTED_PATH", str(tmp_path / "reported.json"))
    return shyft


CONFIG = {"integrationMappings": {"wechselrichter": ["entry1"]},
          "sensorMappings": {"photovoltaic_powerflow_grid": "sensor.grid"}}


def test_reports_plausible_sensor_once(monkeypatch, tmp_path):
    shyft = _setup(monkeypatch, tmp_path, CONFIG)
    app.report_plausible_sensor_suggestions()
    assert shyft.reported == [("sensor:photovoltaic_powerflow_grid", "solaredge", json.dumps([{"e": "solaredge/ac_power"}], separators=(",", ":")))]
    app.report_plausible_sensor_suggestions()
    assert len(shyft.reported) == 1   # unveraendert: nicht noch einmal


def test_nothing_reported_in_demo_mode_or_without_real_device(monkeypatch, tmp_path):
    shyft = _setup(monkeypatch, tmp_path, {"integrationMappings": {"wechselrichter": ["demo"]}, "sensorMappings": CONFIG["sensorMappings"]})
    app.report_plausible_sensor_suggestions()
    monkeypatch.setattr(app, "is_demo_mode", lambda: True)
    monkeypatch.setattr(app, "_read_current_config", lambda: CONFIG)
    app.report_plausible_sensor_suggestions()
    assert shyft.reported == []


class FakeHABattery(FakeHA):
    def get_integrations_and_entities(self):
        return {
            "integrations": [{"id": "entry1", "domain": "solaredge"}],
            "entityMap": {"entry1": ["number.limit", "number.timeout"]},
            "entityInfo": {"number.limit": {"ref": "solaredge/storage discharge limit"},
                           "number.timeout": {"ref": "solaredge/storage command timeout"}},
        }


def test_passed_test_reports_once_even_if_config_unchanged(monkeypatch, tmp_path):
    shyft = _setup(monkeypatch, tmp_path, {
        "integrationMappings": {"batterie": ["entry1"]},
        "sensorMappings": {"battery_discharge_limit_current": "number.limit", "battery_command_timeout": "number.timeout"}})
    monkeypatch.setattr(app, "homeassistant_adapter", FakeHABattery())
    app.report_community_suggestions("battery_discharge_shift")
    assert [slot for slot, _, _ in shyft.reported] == ["sensor:battery_discharge_limit_current", "sensor:battery_command_timeout"]
    app.report_community_suggestions("battery_discharge_shift")   # zweiter bestandener Test: nichts Neues
    assert len(shyft.reported) == 2
