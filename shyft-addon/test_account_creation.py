"""Automatische Konto-Erstellung (maybe_create_real_account in app.py): nur nach erfolgreichem Test eines
steuerbaren echten Geraets, hoechstens ein Versuch pro Stunde, nie ein zweites Konto."""
import pytest

import app


class FakeAdapter:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def create_user(self, test_environment=False):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def env(monkeypatch):
    cfg = {"integrationMappings": {"batterie": ["sma"], "wechselrichter": ["sma"], "wallbox": ["demo"]}}
    saved = {}
    monkeypatch.setattr(app, "_read_current_config", lambda: dict(cfg))
    monkeypatch.setattr(app, "_write_current_config", lambda c: (cfg.clear(), cfg.update(c)))
    monkeypatch.setattr(app, "is_demo_mode", lambda: "key" not in saved)
    monkeypatch.setattr(app, "_persist_shyft_access_key", lambda k: saved.__setitem__("key", k))
    monkeypatch.setattr(app, "fetch_weather_forecast", lambda: None)
    monkeypatch.setattr(app, "BUILD_BRANCH", "main")

    def use(result):
        adapter = FakeAdapter(result)
        monkeypatch.setattr(app, "shyft_adapter", adapter)
        return adapter

    return cfg, saved, use


OK = {"status": "success", "response": {"has_account": True, "access_key": "bus|u1|secret"}}


def test_creates_account_after_controllable_device_test(env):
    cfg, saved, use = env
    adapter = use(OK)
    app.maybe_create_real_account("battery_grid_charge")
    assert adapter.calls == 1
    assert saved["key"] == "bus|u1|secret"
    assert cfg["shyftAccountCreated"] is True
    app.maybe_create_real_account("battery_grid_charge")
    assert adapter.calls == 1


def test_token_key_accepted(env):
    _, saved, use = env
    use({"response": {"token": "bus|u2|s"}})
    app.maybe_create_real_account("battery_grid_charge")
    assert saved["key"] == "bus|u2|s"


def test_demo_device_or_unknown_key_does_nothing(env):
    _, _, use = env
    adapter = use(OK)
    app.maybe_create_real_account("car_charge_start")  # Wallbox ist Demo
    app.maybe_create_real_account("photovoltaic")  # kein steuerbares Geraet
    assert adapter.calls == 0


def test_failed_response_is_not_retried_within_an_hour(env):
    cfg, saved, use = env
    adapter = use({"response": {"has_account": True, "access_key": ""}})
    for _ in range(5):
        app.maybe_create_real_account("battery_grid_charge")
    assert adapter.calls == 1
    assert "key" not in saved
    assert not cfg.get("shyftAccountCreated")

    cfg["shyftAccountCreateAttemptAt"] -= app.ACCOUNT_CREATION_RETRY_SECONDS + 1
    adapter = use(OK)
    app.maybe_create_real_account("battery_grid_charge")
    assert adapter.calls == 1
    assert saved["key"] == "bus|u1|secret"


def test_network_error_counts_as_attempt(env):
    _, _, use = env
    adapter = use(RuntimeError("offline"))
    app.maybe_create_real_account("battery_grid_charge")
    app.maybe_create_real_account("battery_grid_charge")
    assert adapter.calls == 1
