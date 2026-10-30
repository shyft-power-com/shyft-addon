"""PV-Prognose vs. Ist im Analyse-Tab (siehe record_pv_forecast_accuracy / readAnalysisSummary in app.py)."""
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


def test_summary_tagessumme_gleicht_vorzeichen_aus(env):
    now_hour, state, _ = env
    day = (datetime.now(timezone.utc) - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    for hour, forecast, actual in ((10, 4.0, 5.0), (11, 4.0, 3.0), (12, 2.0, 2.5), (2, 0.0, 0.0)):
        key = energy_archive.hour_key(day.replace(hour=hour))
        start = day.replace(hour=hour)
        energy_archive.record_plan_contribution(key, 1.0, 1.0, 1.0, 1.0, at=start)
        energy_archive.finalize_hour(key, start + timedelta(hours=1), 1.0, 0.0, 1.0)
        energy_archive.record_pv_hour(key, forecast, actual, "snapshot")
    with app.app.test_client() as client:
        daily = client.get("/analysis/summary?granularity=daily").get_json()
        hourly = client.get("/analysis/summary?granularity=hourly").get_json()
    assert daily["status"] == "success"
    entry = next(r for r in daily["rows"] if r["period"] == day.date().isoformat())
    assert entry["pv_forecast_kwh"] == pytest.approx(10.0)
    assert entry["pv_actual_kwh"] == pytest.approx(10.5)
    assert entry["pv_error_kwh"] == pytest.approx(0.5)  # +1 - 1 + 0,5: plus und minus gleichen sich aus
    assert entry["pv_error_pct"] == pytest.approx(5.0)
    hours = {r["period"]: r for r in hourly["rows"]}
    assert hours[energy_archive.hour_key(day.replace(hour=10))]["pv_error_pct"] == pytest.approx(25.0)
    assert hours[energy_archive.hour_key(day.replace(hour=11))]["pv_error_pct"] == pytest.approx(-25.0)
    # Prognose unter 0,5 kWh: keine Abweichung ("-" im Frontend)
    night = hours[energy_archive.hour_key(day.replace(hour=2))]
    assert night["pv_error_kwh"] is None and night["pv_error_pct"] is None


def test_summary_ersparnis_wird_rueckwirkend_aus_stundenkosten_gerechnet(env):
    now_hour, _, _ = env
    start = now_hour - timedelta(hours=3)
    key = energy_archive.hour_key(start)
    energy_archive.record_plan_contribution(key, 1.0, 2.0, 1.0, 5.0, price_buy=1.0, price_sell=0.0, at=start)
    energy_archive.finalize_hour(key, start + timedelta(hours=1), 3.0, 0.0, 1.0)
    # alte gespeicherte Spalten (frueher Basisfall - Ist) duerfen nicht mehr einfliessen
    with energy_archive._connect() as conn:
        conn.execute("UPDATE hourly_archive SET savings_vs_base_eur = -99, savings_vs_planned_eur = -99")
        conn.commit()
    row = energy_archive.query_summary("hourly")[0]
    assert row["savings_vs_base_eur"] == pytest.approx(3.0)  # Basisfall 5 - geplant 2
    assert row["planned_minus_actual_eur"] == pytest.approx(-1.0)  # geplant 2 - Ist 3
