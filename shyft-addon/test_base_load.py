from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

import base_load

UTC = timezone.utc
BERLIN = ZoneInfo("Europe/Berlin")


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(base_load, "DB_PATH", str(tmp_path / "base_load.db"))


def _const(start, end, value):
    "Konstante Historie: ein einziger Zustand ab start."
    return [(start, str(value))]


def test_measure_hour_valid_when_all_devices_off():
    h = datetime(2026, 7, 1, 10, tzinfo=UTC)
    load = base_load.step_segments(_const(h, h, 0.4), h, h + timedelta(hours=1), base_load.parse_float)
    wb = base_load.step_segments(_const(h, h, 0.0), h, h + timedelta(hours=1), base_load.parse_float)
    sw = base_load.step_segments(_const(h, h, "off"), h, h + timedelta(hours=1), lambda s: s)
    assert base_load.measure_hour(h, load, [wb], [sw]) == pytest.approx(0.4)


def test_measure_hour_invalid_when_heatpump_ran_briefly():
    h = datetime(2026, 7, 1, 10, tzinfo=UTC)
    end = h + timedelta(hours=1)
    load = base_load.step_segments([(h, "0.4")], h, end, base_load.parse_float)
    hp = base_load.step_segments([(h, "0"), (h + timedelta(minutes=20), "1.2"), (h + timedelta(minutes=25), "0")], h, end, base_load.parse_float)
    assert base_load.measure_hour(h, load, [hp], []) is None


def test_measure_hour_invalid_when_other_device_on_or_implausible_or_gap():
    h = datetime(2026, 7, 1, 10, tzinfo=UTC)
    end = h + timedelta(hours=1)
    load = base_load.step_segments([(h, "0.4")], h, end, base_load.parse_float)
    sw_on = base_load.step_segments([(h, "off"), (h + timedelta(minutes=30), "on")], h, end, lambda s: s)
    assert base_load.measure_hour(h, load, [], [sw_on]) is None
    for value in ("0.01", "3.5", "unavailable"):
        segs = base_load.step_segments([(h, value)], h, end, base_load.parse_float)
        assert base_load.measure_hour(h, segs, [], []) is None
    half = base_load.step_segments([(h + timedelta(minutes=30), "0.4")], h, end, base_load.parse_float)
    assert base_load.measure_hour(h, half, [], []) is None  # Historie deckt nur halbe Stunde


def test_profile_median_per_slot_and_fallbacks():
    assert base_load.hourly_kwh_array(datetime(2026, 7, 1, tzinfo=UTC), 3, BERLIN) == [0.5] * 3  # Default ohne Messung
    # Mittwoch 10:00 lokal (08:00 UTC, Sommerzeit): Median aus 0.3/0.5/0.9 = 0.5
    for day, kw in ((1, 0.3), (8, 0.5), (15, 0.9)):
        base_load.add_sample(datetime(2026, 7, day, 8, tzinfo=UTC), base_load.slot_for(datetime(2026, 7, day, 10, tzinfo=BERLIN)), kw)
    arr = base_load.hourly_kwh_array(datetime(2026, 7, 22, 8, tzinfo=UTC), 2, BERLIN)  # Mi 10:00, 11:00
    assert arr[0] == pytest.approx(0.5)
    assert arr[1] == pytest.approx(0.5)  # Slot leer -> Gesamtmedian


def test_weekend_slot_is_separate():
    sat = datetime(2026, 7, 4, 10, tzinfo=BERLIN)
    assert base_load.slot_for(sat) == "we:10"
    assert base_load.slot_for(sat + timedelta(days=2)) == "wd:10"


def test_slot_keeps_only_newest_samples():
    for day in range(1, 13):
        base_load.add_sample(datetime(2026, 7, day, 8, tzinfo=UTC), "wd:10", float(day))
    profile, _ = base_load.load_profile()
    # nur die letzten 8 (Tage 5..12) zählen -> Median 8.5
    assert profile["wd:10"] == pytest.approx(8.5)


def test_update_from_history_stores_valid_hours_and_is_incremental():
    now = datetime(2026, 7, 2, 12, 30, tzinfo=UTC)
    start = base_load.first_hour(now)
    load = [(start, "0.4")]
    hp = [(start, "0"), (datetime(2026, 7, 1, 6, tzinfo=UTC), "2.0"), (datetime(2026, 7, 1, 9, tzinfo=UTC), "0")]
    stored = base_load.update_from_history(now, BERLIN, load, [hp], [])
    assert stored == 9 * 24 - 3  # 9 Tage Lookback, minus 3 h WP-Lauf
    # zweiter Lauf in derselben Stunde: nichts mehr auszuwerten
    assert base_load.update_from_history(now, BERLIN, load, [hp], []) == 0
    assert base_load.first_hour(now + timedelta(hours=2)) == datetime(2026, 7, 2, 12, tzinfo=UTC)
