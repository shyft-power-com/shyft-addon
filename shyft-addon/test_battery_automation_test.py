"""Test der Variante "Per Home-Assistant-Automation" fuer die Batterie-Aktionen (siehe _test_battery_automation in app.py):
Automation vorhanden/aktiv, wirklich ausgefuehrt (last_triggered), target/phase im Trace angekommen."""
import pytest

import app

AUTOMATION = "automation.shyft_probe_netzladen"


@pytest.fixture
def env(monkeypatch):
    state = {"info": {"state": "on", "last_triggered": "t0", "config_id": "cfg1"},
             "trace": {"found": True, "error": None, "variables": {"target": 0.5, "phase": "start"}},
             "triggered": [], "advance_on_trigger": True}

    class FakeAdapter:
        def get_automation_run_info(self, entity_id):
            if state["info"] is None:
                raise Exception("Automation nicht gefunden")
            return dict(state["info"])

        def latest_automation_trace_variables(self, config_id, started_after_iso=None):
            if isinstance(state["trace"], Exception):
                raise state["trace"]
            return state["trace"]

    def fake_trigger(entity_id, phase, target):
        state["triggered"].append((entity_id, phase, target))
        if state["advance_on_trigger"]:
            state["info"]["last_triggered"] = "t1"

    monkeypatch.setattr(app, "homeassistant_adapter", FakeAdapter())
    monkeypatch.setattr(app, "trigger_ha_automation", fake_trigger)
    monkeypatch.setattr(app, "test_sleep", lambda seconds: None)
    monkeypatch.setattr(app, "BATTERY_AUTOMATION_TEST_WAIT_SECONDS", 0)
    return state


def _config(key="battery_grid_charge"):
    return {"actorMappings": {key: AUTOMATION}, "controlVariant": {key: "ha_automation"}}


def test_success_passes_target_and_phase(env):
    message = app._test_battery_automation("battery_grid_charge", _config())
    assert env["triggered"] == [(AUTOMATION, "start", app.BATTERY_DIRECT_TEST_TARGET_KW)]
    assert "angekommen" in message


def test_stop_action_sends_stop_without_target(env):
    env["trace"]["variables"] = {"target": None, "phase": "stop"}
    app._test_battery_automation("battery_action_stop", _config("battery_action_stop"))
    assert env["triggered"] == [(AUTOMATION, "stop", None)]


def test_no_automation_selected(env):
    with pytest.raises(Exception, match="Keine Automation"):
        app._test_battery_automation("battery_grid_charge", {"actorMappings": {}})
    assert env["triggered"] == []


@pytest.mark.parametrize("state", ["off", "unavailable"])
def test_disabled_or_unavailable_automation_is_not_triggered(env, state):
    env["info"]["state"] = state
    with pytest.raises(Exception):
        app._test_battery_automation("battery_grid_charge", _config())
    assert env["triggered"] == []


def test_missing_automation_fails(env):
    env["info"] = None
    with pytest.raises(Exception, match="nicht gefunden"):
        app._test_battery_automation("battery_grid_charge", _config())


def test_not_executed_when_last_triggered_does_not_change(env):
    env["advance_on_trigger"] = False
    with pytest.raises(Exception, match="nicht ausgeführt"):
        app._test_battery_automation("battery_grid_charge", _config())


def test_automation_error_in_trace_fails(env):
    env["trace"] = {"found": True, "error": "service not found", "variables": {}}
    with pytest.raises(Exception, match="service not found"):
        app._test_battery_automation("battery_grid_charge", _config())


def test_wrong_target_fails(env):
    env["trace"]["variables"]["target"] = 7
    with pytest.raises(Exception, match="target"):
        app._test_battery_automation("battery_grid_charge", _config())


def test_wrong_phase_fails(env):
    env["trace"]["variables"]["phase"] = "stop"
    with pytest.raises(Exception, match="phase"):
        app._test_battery_automation("battery_grid_charge", _config())


@pytest.mark.parametrize("trace", [{"found": False, "error": None, "variables": {}},
                                   {"found": True, "error": None, "variables": {}},
                                   Exception("ws down")])
def test_unreadable_trace_still_passes_if_it_ran(env, trace):
    env["trace"] = trace
    message = app._test_battery_automation("battery_grid_charge", _config())
    assert "nicht prüfbar" in message
