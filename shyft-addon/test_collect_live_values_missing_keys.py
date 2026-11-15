"""Regression: fehlt ein Schluessel in sensorMappings ganz, darf collect_live_values nicht mit KeyError abbrechen
(sonst bricht die stuendliche Uebertragung an shyft-power ab, siehe sync_site_data in app.py)."""
import json
from types import SimpleNamespace

from sync_service import SyncService


class FakeHomeAssistant:
    def load_entity_state(self, entity_id):
        if entity_id == "sensor.pv":
            return SimpleNamespace(state="1200", unit="W")
        raise RuntimeError("nicht lesbar")


def _service(tmp_path, config):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return SyncService(FakeHomeAssistant(), None, str(path))


def test_missing_sensor_mapping_key_is_skipped(tmp_path):
    # nur ein Teil der Schluessel vorhanden, heatpump_dhw_target_temp fehlt ganz; ein weiterer ist leer
    sut = _service(tmp_path, {"sensorMappings": {"photovoltaic_powerflow_pv": "sensor.pv", "heatpump_dhw_tank_temp": ""}})
    live_values = sut.collect_live_values()
    assert live_values["PV - PowerFlow PV"] == 1.2
    assert "HP - DHW Target Temp" not in live_values


def test_config_without_sensor_mappings_does_not_raise(tmp_path):
    assert _service(tmp_path, {}).collect_live_values() == {"HP - Heating Activated": "on"}
