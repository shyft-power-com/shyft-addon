from datetime import datetime

from pv_forecast import _hourly_measured_kw


def _ts(iso):
    return datetime.fromisoformat(iso)


DAY = _ts("2026-09-28T00:00:00+02:00")


def test_hourly_measured_kw_ignores_millisecond_glitch():
    # PV-Template aus zwei Modbus-Quellen: pro Abfragezyklus ein Zwischenwert fuer 3 ms
    pairs = [
        (_ts("2026-09-28T12:00:00.000+02:00"), 4.0),
        (_ts("2026-09-28T12:30:00.000+02:00"), 9.9),  # Zwischenwert
        (_ts("2026-09-28T12:30:00.003+02:00"), 6.0),
    ]

    actual = _hourly_measured_kw(pairs, DAY, 12)

    assert abs(actual - 5.0) < 0.001  # (30 min * 4 + 30 min * 6) / 60 min


def test_hourly_measured_kw_unavailable_ends_previous_value():
    pairs = [
        (_ts("2026-09-28T12:00:00+02:00"), 3.0),
        (_ts("2026-09-28T12:15:00+02:00"), None),  # unavailable bis 12:45
        (_ts("2026-09-28T12:45:00+02:00"), 1.0),
    ]

    actual = _hourly_measured_kw(pairs, DAY, 12)

    assert abs(actual - 2.0) < 0.001  # (15 min * 3 + 15 min * 1) / 30 min


def test_hourly_measured_kw_only_points_inside_window():
    pairs = [
        (_ts("2026-09-28T11:50:00+02:00"), 8.0),  # vor dem Fenster, wird nicht uebertragen
        (_ts("2026-09-28T13:10:00+02:00"), 2.0),  # nach dem Fenster
    ]

    assert _hourly_measured_kw(pairs, DAY, 12) is None
