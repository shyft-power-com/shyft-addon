"""Geplante Ladevorgaenge ankuendigen + Sensor "Auto - Zuhause?" (siehe announce_planned_charges / update_charge_announcements in app.py)."""
import time

import pytest

import app
from homeassistant_adapter import EntityState

HOUR_MS = 3600 * 1000


class Env:
    def __init__(self, monkeypatch, tmp_path):
        self.actions = []
        self.states = {"sensor.plug": "disconnected", "sensor.home": "Zuhause"}
        self.sent = []
        self.config = {
            "notificationsEnabled": {"charge_announcement": True},
            "notificationTargets": {"phone": "notify.mobile_app_test"},
            "sensorMappings": {"wallbox_plugged": "sensor.plug", "electronicvehicle_home": "sensor.home"},
            "wallboxConnectionStatusMapping": {"connected": True, "disconnected": False},
        }
        monkeypatch.setattr(app, "CHARGE_ANNOUNCEMENT_PATH", str(tmp_path / "announced.json"))
        monkeypatch.setattr(app, "is_demo_mode", lambda: False)
        monkeypatch.setattr(app, "_read_current_config", lambda: self.config)
        monkeypatch.setattr(app, "_read_computed_actions", lambda: [dict(a) for a in self.actions])
        monkeypatch.setattr(app.homeassistant_adapter, "load_entity_state", lambda entity_id: EntityState(self.states[entity_id], "", None))
        monkeypatch.setattr(app.homeassistant_adapter, "send_notification", lambda target, message: self.sent.append(message))
        monkeypatch.setitem(app._charge_announcement_arrival, "until", 0.0)

    def plan(self, hours_from_now, count=2, kwh=5.0, savings=1.25):
        "Plant 'count' aufeinanderfolgende Stunden 'Auto laden', beginnend hours_from_now Stunden nach jetzt."
        now_ms = int(time.time() * 1000)
        self.actions = [a for a in self.actions if a["Action Name"] != app.EV_CHARGE_ACTION_NAME]
        for i in range(count):
            start = now_ms + (hours_from_now + i) * HOUR_MS
            self.actions.append({
                "_id": f"ev_{i}", "Action Name": app.EV_CHARGE_ACTION_NAME, "Status": "geplant",
                "Date Start": start, "Date End": start + HOUR_MS, "Energy (electr)": kwh, "Savings": savings,
                "Execution Status": "yes, planned",
            })


@pytest.fixture
def env(monkeypatch, tmp_path):
    return Env(monkeypatch, tmp_path)


def test_classify_car_home_state():
    assert app.classify_car_home_state("Zuhause") is True
    assert app.classify_car_home_state("home") is True
    assert app.classify_car_home_state(" Abwesend ") is False
    assert app.classify_car_home_state("not_home") is False
    assert app.classify_car_home_state("unknown") is None
    assert app.classify_car_home_state("unavailable") is None
    assert app.classify_car_home_state(None) is None


def test_announces_once_with_summed_values(env):
    env.plan(3, count=2, kwh=5.0, savings=1.25)
    assert app.announce_planned_charges() is True
    assert len(env.sent) == 1
    assert "Verbinde dein Fahrzeug, geplante Ladung: 10,0 kWh um " in env.sent[0]
    assert "Ersparnis: 2,50 €" in env.sent[0]
    assert app.announce_planned_charges() is False  # nur einmal, keine Erinnerung
    assert len(env.sent) == 1


def test_no_announcement_when_plugged_or_unknown(env):
    env.plan(3)
    env.states["sensor.plug"] = "connected"
    assert app.announce_planned_charges() is False
    env.states["sensor.plug"] = "something_unmapped"
    assert app.announce_planned_charges() is False
    assert env.sent == []


def test_no_announcement_when_car_away_then_on_arrival(env):
    env.plan(3)
    env.states["sensor.home"] = "Abwesend"
    assert app.announce_planned_charges() is False
    env.states["sensor.home"] = "Zuhause"  # Ankunft
    assert app.announce_planned_charges(reason="Ankunft") is True
    assert len(env.sent) == 1


def test_unknown_home_sensor_does_not_block(env):
    env.plan(3)
    env.states["sensor.home"] = "unavailable"
    assert app.announce_planned_charges() is True


def test_no_announcement_beyond_horizon_or_when_disabled(env):
    env.plan(13)
    assert app.announce_planned_charges() is False
    env.plan(3)
    env.config["notificationsEnabled"]["charge_announcement"] = False
    assert app.announce_planned_charges() is False
    assert env.sent == []


def test_moved_and_cancelled_updates(env):
    env.plan(3)
    assert app.announce_planned_charges() is True
    env.sent.clear()

    env.plan(3)
    app.update_charge_announcements()
    assert env.sent == []  # unveraendert -> keine Update-Nachricht

    env.plan(6)
    app.update_charge_announcements()
    assert len(env.sent) == 1 and env.sent[0].startswith("Ladevorgang auf ") and env.sent[0].endswith(" Uhr verschoben")
    env.sent.clear()

    env.actions = []
    app.update_charge_announcements()
    assert env.sent == ["Ladevorgang abgesagt"]
    env.sent.clear()
    app.update_charge_announcements()
    assert env.sent == []  # nur einmal


def test_no_update_for_charge_that_was_never_announced(env):
    env.plan(3)
    env.actions = []
    app.update_charge_announcements()
    assert env.sent == []


def test_started_charge_gets_no_update(env):
    env.plan(3)
    assert app.announce_planned_charges() is True
    env.sent.clear()
    announced = app._read_announced_charges()
    announced[0]["startMs"] = int(time.time() * 1000) - HOUR_MS  # Ladung laeuft bereits
    app._write_announced_charges(announced)
    env.actions = []
    app.update_charge_announcements()
    assert env.sent == []


def test_new_charge_after_arrival_window_is_announced(env):
    env.states["sensor.home"] = "Abwesend"
    env.plan(3)
    assert app.announce_planned_charges() is False
    env.states["sensor.home"] = "Zuhause"
    app._charge_announcement_arrival["until"] = time.time() + 600
    app.update_charge_announcements()  # nach der Neu-Optimierung
    assert len(env.sent) == 1


def test_forecast_at_home_unplugged_counts_as_away_first_hour_then_can_charge(env, monkeypatch, tmp_path):
    monkeypatch.setattr(app, "CAR_PRESENCE_LOG_PATH", str(tmp_path / "no_log.json"))
    monkeypatch.setattr(app, "_apply_manual_absence_overrides", lambda *args, **kwargs: None)
    monkeypatch.setattr(app, "_apply_planned_car_trips", lambda *args, **kwargs: None)

    def probabilities(plug_state, home_state):
        env.states["sensor.plug"] = plug_state
        env.states["sensor.home"] = home_state
        return app.compute_car_presence_forecast(hours=6)[1]

    at_home = probabilities("disconnected", "Zuhause")
    away = probabilities("disconnected", "Abwesend")
    no_sensor_info = probabilities("disconnected", "unknown")
    plugged = probabilities("connected", "Zuhause")

    assert at_home[0] == 0.0                      # laufende Stunde: abwesend
    assert all(p > 0.5 for p in at_home[1:])      # danach: kann laden
    assert at_home[1] == plugged[1]               # wie bei eingestecktem Auto
    assert at_home[1:] != away[1:]                # Abwesend bleibt bei der alten Prognose
    assert no_sensor_info == away                 # unbekannter Sensorwert: Verhalten wie ohne Sensor
    assert plugged[0] == 1.0
