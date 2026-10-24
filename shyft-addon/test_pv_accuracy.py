"""PV-Prognose vs. Ist im Analyse-Tab (siehe record_pv_forecast_accuracy / readAnalysisPvForecast in app.py)."""
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

import app
import energy_archive
import pv_forecast
from homeassistant_adapter import PeriodElement

TZ = ZoneInfo("Europe/Berlin")


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(energy_archive, "DB_PATH", str(tmp_path / "archive.db"))
    monkeypatch.setattr(pv_forecast, "PV_SYNC_LOG_PATH", str(tmp_path / "sync.jsonl"))
    monkeypatch.setattr(app, "get_ha_timezone", lambda: TZ)
    monkeypatch.setattr(app, "is_demo_mode", lambda: False)
    monkeypatch.setattr(app, "_read_current_config", lambda: {"sensorMappings": {"photovoltaic_powerflow_pv": "sensor.pv"}})
    now_hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    state = {"snapshot": None, "events": []}
    monkeypatch.setattr(app, "_read_pv_forecast_snapshot", lambda: state["snapshot"])

    class FakeHA:
        def load_power_history(self, entity_id, start, end):
            return [e for e in state["events"] if start <= e.last_changed < end]

    monkeypatch.setattr(app, "homeassistant_adapter", FakeHA())
    return now_hour, state, tmp_path


def _bucket_events(hour, kw_values):
    "Drei 20-Minuten-Werte je Stunde wie load_power_history."
    return [PeriodElement(f"{v:.4f}", hour + timedelta(minutes=20 * i)) for i, v in enumerate(kw_values)]


def test_stunden_werden_mit_prognose_aus_snapshot_und_ist_aus_historie_gespeichert(env):
    now_hour, state, _ = env
    h1, h2 = now_hour - timedelta(hours=2), now_hour - timedelta(hours=1)
    state["snapshot"] = {"labels": [h1.isoformat(), h2.isoformat(), now_hour.isoformat()], "pv_generation": [2.0, 4.0, 5.0]}
    state["events"] = _bucket_events(h1, [2.0, 3.0, 4.0]) + _bucket_events(h2, [3.0, 3.0, 3.0])
    assert app.record_pv_forecast_accuracy() == 2  # laufende Stunde nicht
    rows = {r["hour_start_utc"]: r for r in energy_archive.query_pv_hours()}
    assert rows[energy_archive.hour_key(h1)]["actual_kw"] == pytest.approx(3.0)
    assert rows[energy_archive.hour_key(h2)]["forecast_kw"] == pytest.approx(4.0)
    assert app.record_pv_forecast_accuracy() == 0  # schon gespeichert


def test_sync_protokoll_liefert_letzte_prognose_vor_der_stunde(env):
    now_hour, state, tmp = env
    target = now_hour - timedelta(hours=30)
    start_ms = int((target - timedelta(hours=5)).timestamp() * 1000)
    with open(tmp / "sync.jsonl", "w") as f:
        # aelterer Sync: 1,0 kW; juengerer, aber noch vor der Stunde: 1,5 kW; einer NACH der Stunde (8 kW) zaehlt nicht
        for sent, value in ((target - timedelta(hours=5), 1.0), (target - timedelta(hours=1), 1.5), (target + timedelta(hours=2), 8.0)):
            pv = [value] * 12
            f.write(json.dumps({"sent_at": sent.isoformat(), "start_ms": start_ms, "pv": pv}) + "\n")
    forecasts = app._pv_forecast_by_hour_key()
    assert forecasts[energy_archive.hour_key(target)] == (1.5, "sync_log")


def test_stunde_ohne_messwert_nach_dem_ersten_messwert_zaehlt_als_null(env):
    now_hour, state, _ = env
    h1, h2 = now_hour - timedelta(hours=2), now_hour - timedelta(hours=1)
    state["snapshot"] = {"labels": [h1.isoformat(), h2.isoformat()], "pv_generation": [0.5, 0.2]}
    state["events"] = _bucket_events(h1, [0.3, 0.3, 0.3])
    app.record_pv_forecast_accuracy()
    rows = {r["hour_start_utc"]: r for r in energy_archive.query_pv_hours()}
    assert rows[energy_archive.hour_key(h2)]["actual_kw"] == 0.0


def test_endpoint_tagessumme_gleicht_vorzeichen_aus(env):
    now_hour, state, _ = env
    day = (datetime.now(TZ) - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    for hour, forecast, actual in ((10, 4.0, 5.0), (11, 4.0, 3.0), (12, 2.0, 2.5), (2, 0.0, 0.0)):
        start = day.replace(hour=hour).astimezone(timezone.utc)
        energy_archive.record_pv_hour(energy_archive.hour_key(start), forecast, actual, "snapshot")
    with app.app.test_client() as client:
        data = client.get("/analysis/pv-forecast?days=3").get_json()
    assert data["status"] == "success"
    entry = next(d for d in data["days"] if d["date"] == day.date().isoformat())
    assert entry["forecast_kwh"] == pytest.approx(10.0)
    assert entry["actual_kwh"] == pytest.approx(10.5)
    assert entry["error_kwh"] == pytest.approx(0.5)  # +1 - 1 + 0,5: plus und minus gleichen sich aus
    assert entry["error_pct"] == pytest.approx(5.0)
    hours = {h["hour"]: h for h in entry["hours"]}
    assert set(hours) == {"10:00", "11:00", "12:00"}  # Nachtstunde ohne Erzeugung ausgeblendet
    assert hours["10:00"]["error_pct"] == pytest.approx(25.0)
    assert hours["11:00"]["error_pct"] == pytest.approx(-25.0)
