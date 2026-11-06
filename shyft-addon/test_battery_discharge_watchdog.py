"""Watchdog fuer "Batterie-Entladen verschieben" (siehe check_battery_discharge_shift_watchdog in app.py):
weicht die Entladeleistung waehrend einer laufenden Aktion von 0 W ab, werden die Startbefehle erneut gesendet."""
import time

import pytest

import app

NAME = app.BATTERY_DISCHARGE_SHIFT_ACTION_NAME


@pytest.fixture
def env(monkeypatch):
    store = {}
    state = {"live_kw": 5.0, "fail": None, "calls": [], "pushes": []}
    config = {"controlVariant": {"battery_discharge_shift": "direct"}}

    def fake_execute(action_key, phase, target_kw, cfg, **kwargs):
        state["calls"].append((action_key, phase, target_kw, kwargs))
        if state["fail"]:
            raise Exception(state["fail"])
        state["live_kw"] = 0.0

    monkeypatch.setattr(app, "is_demo_mode", lambda: False)
    monkeypatch.setattr(app, "_read_current_config", lambda: config)
    monkeypatch.setattr(app, "is_action_type_enabled", lambda cfg, name: True)
    monkeypatch.setattr(app, "_read_computed_actions", lambda: [dict(a) for a in store.values()])
    monkeypatch.setattr(app, "_update_computed_action", lambda a: store.__setitem__(a["_id"], dict(a)))
    monkeypatch.setattr(app, "_read_mapped_numeric", lambda cfg, key: state["live_kw"])
    monkeypatch.setattr(app, "_execute_battery_direct_unguarded", fake_execute)
    monkeypatch.setattr(app, "notify_action_event",
                        lambda cfg, action, verb, is_error=False: state["pushes"].append((verb, is_error)))
    monkeypatch.setitem(app._battery_write_activity, "busy", 0)
    monkeypatch.setitem(app._battery_write_activity, "last_end", 0.0)
    return store, state


def _running(store, started_ago_s=900, ends_in_s=2400, exec_status="yes, started"):
    now = time.time() * 1000
    store["d1"] = {"_id": "d1", "Action Name": NAME, "Status": "aktiv", "Execution Status": exec_status,
                   "Date Start": now - started_ago_s * 1000, "Date End": now + ends_in_s * 1000}


def test_abweichung_sendet_befehle_erneut_und_bleibt_erfolgreich(env):
    store, state = env
    _running(store)
    assert app.check_battery_discharge_shift_watchdog() is True
    assert state["calls"][0][:3] == ("battery_discharge_shift", "Watchdog", 0)
    assert state["calls"][0][3]["notify_on_failure"] is False
    action = store["d1"]
    assert "Watchdog: Entladeleistung stand auf 5000 W statt 0 W" in action["Log"]
    assert "Wert wieder übernommen" in action["Log"]
    assert not action.get("Had Error")
    assert action["Execution Status"] == "yes, started"
    assert state["pushes"] == [("Abweichung erkannt, Befehle erneut gesendet", True)]


def test_fehlschlag_markiert_aktion_als_fehlerhaft(env):
    store, state = env
    state["fail"] = "Die Entität number.x ist in Home Assistant nicht verfügbar."
    _running(store)
    assert app.check_battery_discharge_shift_watchdog() is True
    action = store["d1"]
    assert action["Had Error"] is True
    assert "erneutes Senden fehlgeschlagen. Grund: Die Entität number.x ist in Home Assistant nicht verfügbar." in action["Log"]
    assert state["pushes"] == [("Abweichung erkannt, erneutes Senden fehlgeschlagen", True)]


def test_keine_abweichung_nichts_tun(env):
    store, state = env
    state["live_kw"] = 0.0
    _running(store)
    assert app.check_battery_discharge_shift_watchdog() is False
    assert state["calls"] == [] and "Log" not in store["d1"]


@pytest.mark.parametrize("kwargs", [
    {"started_ago_s": 10},            # gerade erst gestartet
    {"ends_in_s": 30},                # kurz vor dem Stundenwechsel (Ende setzt den Ruhewert)
    {"exec_status": "no, deactivated"},  # nur simuliert
])
def test_keine_ueberwachung_ausserhalb_der_laufzeit(env, kwargs):
    store, state = env
    _running(store, **kwargs)
    assert app.check_battery_discharge_shift_watchdog() is False
    assert state["calls"] == []


def test_nicht_waehrend_oder_kurz_nach_eigenem_schreibvorgang(env, monkeypatch):
    store, state = env
    _running(store)
    monkeypatch.setitem(app._battery_write_activity, "last_end", time.time() - 5)
    assert app.check_battery_discharge_shift_watchdog() is False
    monkeypatch.setitem(app._battery_write_activity, "last_end", 0.0)
    monkeypatch.setitem(app._battery_write_activity, "busy", 1)
    assert app.check_battery_discharge_shift_watchdog() is False
    assert state["calls"] == []


def test_wiederholt_hoechstens_alle_fuenf_minuten(env):
    store, state = env
    _running(store)
    assert app.check_battery_discharge_shift_watchdog() is True
    state["live_kw"] = 5.0  # erneut zurueckgesprungen
    app._battery_write_activity["last_end"] = 0.0
    assert app.check_battery_discharge_shift_watchdog() is False
    assert len(state["calls"]) == 1


def test_ohne_direkte_steuerung_kein_watchdog(env, monkeypatch):
    store, state = env
    monkeypatch.setattr(app, "_read_current_config", lambda: {"controlVariant": {}})
    _running(store)
    assert app.check_battery_discharge_shift_watchdog() is False


def test_netzladen_timeout_jetzt_zehn_stunden():
    assert app.BATTERY_COMMAND_TIMEOUT_SECONDS["battery_grid_charge"] == 36000
    assert app.BATTERY_COMMAND_TIMEOUT_SECONDS["battery_discharge_shift"] == 36000
