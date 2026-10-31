"""Steuerungs-Schalter waehrend einer laufenden Aktion umlegen: Start bzw. Stopp muss nachtraeglich ans Geraet
(siehe reconcile_running_actions_with_toggles in app.py)."""
import time

import pytest

import app


class FakeDevice:
    "Ersetzt handle_shyft_action_start/end: setzt den Execution Status wie die echten Handler und zaehlt die Befehle."

    def __init__(self):
        self.starts = []
        self.ends = []
        self.fail_start = False
        self.fail_end = False

    def start(self, action, actions_enabled, config):
        if not actions_enabled:
            action["Execution Status"] = "no, deactivated"
            return
        self.starts.append(action["_id"])
        action["Execution Status"] = "no, error" if self.fail_start else "yes, started"

    def end(self, action, actions_enabled, config):
        if not actions_enabled:
            return
        self.ends.append(action["_id"])
        action["Execution Status"] = "yes, not finished" if self.fail_end else "yes, finished"


@pytest.fixture
def env(monkeypatch):
    store = {}
    device = FakeDevice()
    monkeypatch.setattr(app, "_read_computed_actions", lambda: [dict(a) for a in store.values()])
    monkeypatch.setattr(app, "_update_computed_action", lambda a: store.__setitem__(a["_id"], dict(a)))
    monkeypatch.setattr(app, "handle_shyft_action_start", device.start)
    monkeypatch.setattr(app, "handle_shyft_action_end", device.end)
    return store, device


def _running(store, exec_status, name="Warmwasser"):
    now = time.time() * 1000
    store["a1"] = {"_id": "a1", "Action Name": name, "Status": "aktiv", "Date Start": now - 600_000,
                   "Date End": now + 3_000_000, "Execution Status": exec_status}


def _config(enabled):
    return {"actionTypeEnabled": {"hot_water": enabled}, "startedShyftActionIds": ["a1"], "endedShyftActionIds": []}


def test_aktivieren_sendet_start_fuer_simuliert_laufende_aktion(env):
    store, device = env
    _running(store, "no, deactivated")
    config = _config(True)
    app.apply_action_type_toggle_changes({"hot_water": False}, {"hot_water": True}, config)
    assert device.starts == ["a1"]
    assert store["a1"]["Execution Status"] == "yes, started"
    assert "Startbefehl wird nachträglich" in store["a1"]["Log"]


def test_deaktivieren_sendet_stopp_und_wieder_aktivieren_startet_neu(env):
    store, device = env
    _running(store, "yes, started")
    config = _config(False)
    app.apply_action_type_toggle_changes({"hot_water": True}, {"hot_water": False}, config)
    assert device.ends == ["a1"]
    assert "a1" in config["endedShyftActionIds"]
    assert "Stoppbefehl wird ans Gerät gesendet" in store["a1"]["Log"]

    config["actionTypeEnabled"]["hot_water"] = True
    app.apply_action_type_toggle_changes({"hot_water": False}, {"hot_water": True}, config)
    assert device.starts == ["a1"]
    assert "a1" not in config["endedShyftActionIds"]  # regulaeres Ende zur Endzeit muss wieder greifen


def test_fehlgeschlagener_stopp_wird_beim_poll_wiederholt(env):
    store, device = env
    _running(store, "yes, started")
    device.fail_end = True
    config = _config(False)
    app.apply_action_type_toggle_changes({"hot_water": True}, {"hot_water": False}, config)
    assert store["a1"]["Execution Status"] == "yes, not finished"
    assert "fehlgeschlagen" in store["a1"]["Log"]

    device.fail_end = False
    app.reconcile_running_actions_with_toggles(config)  # naechster Poll
    assert device.ends == ["a1", "a1"]
    assert store["a1"]["Execution Status"] == "yes, finished"
    assert store["a1"]["Log"].count("fehlgeschlagen") == 1


def test_fehlgeschlagener_start_wird_beim_poll_wiederholt(env):
    store, device = env
    _running(store, "no, deactivated")
    device.fail_start = True
    config = _config(True)
    app.apply_action_type_toggle_changes({"hot_water": False}, {"hot_water": True}, config)
    assert store["a1"]["Execution Status"] == "no, error"

    device.fail_start = False
    app.reconcile_running_actions_with_toggles(config)
    assert device.starts == ["a1", "a1"]
    assert store["a1"]["Execution Status"] == "yes, started"
    assert "jetzt gelungen" in store["a1"]["Log"]


def test_poll_startet_regulaer_beendete_aktion_nicht_neu(env):
    store, device = env
    _running(store, "yes, finished")  # z.B. vorzeitig beendet, Schalter war die ganze Zeit an
    app.reconcile_running_actions_with_toggles(_config(True))
    assert device.starts == [] and device.ends == []


def test_poll_holt_verpassten_start_nach(env):
    store, device = env
    _running(store, "no, deactivated")  # Schalter ist an, Sofort-Abgleich hat aber nicht gegriffen
    app.reconcile_running_actions_with_toggles(_config(True))
    assert device.starts == ["a1"]


def test_andere_aktionstypen_bleiben_unberuehrt(env):
    store, device = env
    _running(store, "yes, started", name="Auto laden")
    config = _config(False)
    config["actionTypeEnabled"]["car_charge_start"] = True
    app.apply_action_type_toggle_changes({"hot_water": True}, {"hot_water": False}, config)
    assert device.ends == []
