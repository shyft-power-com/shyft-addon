"""Ungueltiger shyft_access_key (HTTP 401): das Dashboard zeigt eine klare Meldung samt Support-Link statt 'Noch keine Dashboard-Daten'."""
import app


def _chart_data(monkeypatch, tmp_path, problem_active):
    monkeypatch.setattr(app, "DASHBOARD_CACHE_PATH", str(tmp_path / "missing_cache.json"))
    monkeypatch.setattr(app.problem_registry, "is_active", lambda problem_id: problem_active and problem_id == app.ACCESS_KEY_PROBLEM_ID)
    return app.app.test_client().get("/dashboard/chart-data").get_json()


def test_access_key_problem_replaces_empty_dashboard_text(monkeypatch, tmp_path):
    data = _chart_data(monkeypatch, tmp_path, problem_active=True)
    assert data["status"] == "error"
    assert data["message"] == app.ACCESS_KEY_PROBLEM_MESSAGE
    assert "shyft_access_key" in data["message"] and "shyft-Service" in data["message"]
    assert data["supportLink"] is True


def test_without_problem_the_waiting_text_stays(monkeypatch, tmp_path):
    data = _chart_data(monkeypatch, tmp_path, problem_active=False)
    assert data["message"].startswith("Noch keine Dashboard-Daten")
    assert "supportLink" not in data
