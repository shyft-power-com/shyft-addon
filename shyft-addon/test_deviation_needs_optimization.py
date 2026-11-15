"""Der Ruhezustand-Soll ("Shyft erwartet 'off'") im Geraeteverhalten-Abgleich gilt erst nach der ersten empfangenen Optimierung."""
import app


def _run(monkeypatch, optimization_received, actions=()):
    notified = []
    monkeypatch.setattr(app, "_has_received_optimization", lambda: optimization_received)
    monkeypatch.setattr(app, "_read_computed_actions", lambda: list(actions))
    monkeypatch.setattr(app, "resolve_control_variant", lambda *a, **k: "direct")
    monkeypatch.setattr(app, "is_action_type_enabled", lambda *a, **k: True)
    monkeypatch.setattr(app, "_sonstiger_verbraucher_status", lambda config: {"on": True})
    monkeypatch.setattr(app, "_notify_device_deviation", lambda key, message, config: notified.append(key))
    monkeypatch.setattr(app, "_clear_device_deviation", lambda key: None)
    app.check_device_status_deviation({"integrationMappings": {"sonstiger_verbraucher": ["entry1"]}})
    return notified


def test_no_rest_state_expectation_before_first_optimization(monkeypatch):
    assert _run(monkeypatch, optimization_received=False) == []


def test_rest_state_expectation_after_first_optimization(monkeypatch):
    assert _run(monkeypatch, optimization_received=True) == ["sonstiger_verbraucher"]
