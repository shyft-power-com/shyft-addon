import json
from datetime import datetime, timedelta, timezone

import pytest

import app

UTC = timezone.utc
VAT = app.AWATTAR_VAT_FACTOR


def _api_body(first_local_iso, market_prices, forecast_prices):
    start = datetime.fromisoformat(first_local_iso)
    rows = []
    for i, (price, origin) in enumerate([(p, "market") for p in market_prices] + [(p, "forecast") for p in forecast_prices]):
        s = start + timedelta(hours=i)
        rows.append({"start": s.isoformat(timespec="milliseconds"), "end": (s + timedelta(hours=1)).isoformat(timespec="milliseconds"), "price": price, "price_origin": origin})
    return json.dumps(rows)


def test_parse_energyforecast_body_finds_last_market_hour():
    body = _api_body("2026-11-07T22:00:00.000+01:00", [0.25, 0.2377], [0.2347, 0.2318])
    prices, last_market_ms = app._parse_energyforecast_body(body)
    assert len(prices) == 4
    assert datetime.fromtimestamp(last_market_ms / 1000, tz=UTC) == datetime(2026, 11, 7, 22, tzinfo=UTC)
    assert prices[last_market_ms] == pytest.approx(0.2377)


def test_parse_energyforecast_body_unreadable_returns_empty():
    assert app._parse_energyforecast_body("kein json") == ({}, None)
    assert app._parse_energyforecast_body(None) == ({}, None)


def test_bias_continues_from_last_market_price(monkeypatch):
    last = datetime(2026, 11, 4, 22, tzinfo=UTC)
    monkeypatch.setattr(app, "_bubble_last_market_hour", lambda: last)
    by_hour = {last: 0.21115 * VAT}
    bubble = {last: 0.21115, last + timedelta(hours=1): 0.14819, last + timedelta(hours=2): 0.15}
    bias = app._bubble_bias(by_hour, bubble)
    assert bias[0] == last
    assert bias[1] == pytest.approx(0.21115 - 0.14819)
    first = bubble[last + timedelta(hours=1)] + app._bubble_bias_offset(last + timedelta(hours=1), bias)
    assert first == pytest.approx(0.21115 - app.BUBBLE_BIAS_MELT_PER_HOUR_EUR)
    # nach genug Stunden ist der Aufschlag abgeschmolzen
    assert app._bubble_bias_offset(last + timedelta(hours=100), bias) == 0.0


def test_bias_uses_forecast_error_when_awattar_is_ahead_of_bubble_market(monkeypatch):
    market_end = datetime(2026, 11, 4, 22, tzinfo=UTC)
    awattar_last = market_end + timedelta(hours=24)
    monkeypatch.setattr(app, "_bubble_last_market_hour", lambda: market_end)
    by_hour = {awattar_last: 0.20 * VAT}
    bubble = {awattar_last: 0.17}
    assert app._bubble_bias(by_hour, bubble) == (awattar_last, pytest.approx(0.03))


def test_bias_without_market_info_falls_back_to_awattar_boundary(monkeypatch):
    monkeypatch.setattr(app, "_bubble_last_market_hour", lambda: None)
    last = datetime(2026, 11, 4, 22, tzinfo=UTC)
    assert app._bubble_bias({last: 0.2 * VAT}, {last: 0.2}) == (last, pytest.approx(0.0))
    assert app._bubble_bias({}, {last: 0.2}) is None
