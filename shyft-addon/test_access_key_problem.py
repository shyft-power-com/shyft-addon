"""Ungueltiger shyft_access_key (HTTP 401): das Dashboard zeigt eine klare Meldung (nur E-Mail, kein Log-Versand) statt 'Noch keine Dashboard-Daten'.
Der Log-Versand (Support-Formular) wird im Demomodus nicht angeboten."""
import app


def _chart_data(monkeypatch, tmp_path, problem_active):
    monkeypatch.setattr(app, "DASHBOARD_CACHE_PATH", str(tmp_path / "missing_cache.json"))
    monkeypatch.setattr(app.problem_registry, "is_active", lambda problem_id: problem_active and problem_id == app.ACCESS_KEY_PROBLEM_ID)
    return app.app.test_client().get("/dashboard/chart-data").get_json()


def test_access_key_problem_replaces_empty_dashboard_text(monkeypatch, tmp_path):
    data = _chart_data(monkeypatch, tmp_path, problem_active=True)
    assert data["status"] == "error"
    assert data["message"] == app.ACCESS_KEY_PROBLEM_MESSAGE
    assert "shyft_access_key" in data["message"] and "info@shyft-power.com" in data["message"]
    assert "Log" not in data["message"]
    assert "supportLink" not in data


def test_without_problem_the_waiting_text_stays(monkeypatch, tmp_path):
    data = _chart_data(monkeypatch, tmp_path, problem_active=False)
    assert data["message"].startswith("Noch keine Dashboard-Daten")


def _assistant_status(monkeypatch, demo):
    monkeypatch.setattr(app, "is_demo_mode", lambda: demo)
    monkeypatch.setattr(app.homeassistant_adapter, "get_from_homeassistant", lambda *a, **k: [])
    return app.app.test_client().get("/assistant/status").get_json()


def test_support_not_offered_in_demo_mode(monkeypatch):
    assert _assistant_status(monkeypatch, demo=True)["supportAvailable"] is False


def test_support_offered_with_real_account(monkeypatch):
    assert _assistant_status(monkeypatch, demo=False)["supportAvailable"] is True


def test_support_send_refused_in_demo_mode(monkeypatch):
    monkeypatch.setattr(app, "is_demo_mode", lambda: True)
    response = app.app.test_client().post("/assistant/support/send", json={"summary": "Hallo, ich habe folgendes Problem: es geht nicht"})
    assert response.status_code == 400
