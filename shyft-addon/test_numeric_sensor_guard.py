import json
import sync_service
from sync_service import SyncService


class _State:
    def __init__(self, state, unit="%"):
        self.state, self.unit = state, unit


class _HA:
    def __init__(self, state, unit="%"):
        self.s = _State(state, unit)

    def load_entity_state(self, entity_id):
        return self.s


CONFIG = {"sensorMappings": {"electronicvehicle_state_of_charge": "sensor.car_soc", "battery_state_of_charge": "sensor.b"},
          "integrationMappings": {}}


def _service(ha, tmp_path, monkeypatch):
    monkeypatch.setattr(sync_service, "EV_SOC_LAST_VALUE_PATH", str(tmp_path / "ev.json"))
    return SyncService(ha, None, config_path=str(tmp_path / "c.json"))


def test_unavailable_numeric_sensor_is_skipped(tmp_path, monkeypatch):
    svc = _service(_HA("unavailable"), tmp_path, monkeypatch)
    assert svc._load_sensor_value("battery_state_of_charge", "B - SOC", CONFIG) == ""


def test_ev_soc_falls_back_to_last_valid_value(tmp_path, monkeypatch):
    svc = _service(_HA("12.4"), tmp_path, monkeypatch)
    assert svc._load_sensor_value("electronicvehicle_state_of_charge", "EV - SOC", CONFIG)["state"] == "12.4"
    svc.homeassistant_adapter = _HA("unavailable")
    entry = svc._load_sensor_value("electronicvehicle_state_of_charge", "EV - SOC", CONFIG)
    assert entry["state"] == "12.4" and entry["unit"] == "%"


def test_ev_soc_without_history_sends_nothing(tmp_path, monkeypatch):
    svc = _service(_HA("unknown"), tmp_path, monkeypatch)
    assert svc._load_sensor_value("electronicvehicle_state_of_charge", "EV - SOC", CONFIG) == ""
