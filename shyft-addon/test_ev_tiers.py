import ev_tiers


def _history(days=35):
    # 0.20 .. 0.60 EUR/kWh gleichmaessig verteilt
    n = days * 24
    return [0.20 + 0.40 * i / (n - 1) for i in range(n)]


def test_legacy_mapping():
    assert ev_tiers.charge_rule_from_legacy_soc_normal("10 %") == "sehr günstig"
    assert ev_tiers.charge_rule_from_legacy_soc_normal("20 %") == "sehr günstig"
    assert ev_tiers.charge_rule_from_legacy_soc_normal("30 %") == "mittel"
    assert ev_tiers.charge_rule_from_legacy_soc_normal("50 %") == "mittel"
    assert ev_tiers.charge_rule_from_legacy_soc_normal("60 %") == "Komfort"
    assert ev_tiers.charge_rule_from_legacy_soc_normal("80 %") == "Komfort"
    assert ev_tiers.charge_rule_from_legacy_soc_normal(None) == "mittel"
    assert ev_tiers.charge_rule_from_legacy_soc_normal("kaputt") == "mittel"


def test_charge_rule_prefers_new_key_then_legacy_then_default():
    assert ev_tiers.charge_rule({"evChargeRule": "Komfort", "evSocNormal": "10 %"}) == "Komfort"
    assert ev_tiers.charge_rule({"evSocNormal": "10 %"}) == "sehr günstig"
    assert ev_tiers.charge_rule({}) == "mittel"
    assert ev_tiers.charge_rule({"evChargeRule": "unbekannt"}) == "mittel"


def test_pv_cap_per_rule():
    assert ev_tiers.pv_surplus_soc_cap_percent({"evChargeRule": "sehr günstig"}) == 70
    assert ev_tiers.pv_surplus_soc_cap_percent({"evChargeRule": "mittel"}) == 80
    assert ev_tiers.pv_surplus_soc_cap_percent({"evChargeRule": "Komfort"}) == 90


def test_quantile_matches_numpy_style_interpolation():
    assert ev_tiers.quantile([1, 2, 3, 4], 0.5) == 2.5
    assert ev_tiers.quantile([1, 2, 3, 4], 0.0) == 1
    assert ev_tiers.quantile([1, 2, 3, 4], 1.0) == 4


def test_dynamic_tiers_mittel():
    t = ev_tiers.build_tiers("mittel", _history(), [0.3, 0.4], pv_mode=False)
    p, soc = t["p"], t["soc"]
    assert len(p) == 6 and len(soc) == 5
    # nicht steigend (konkav), Kanten aufsteigend
    assert all(a >= b for a, b in zip(p, p[1:]))
    assert all(a <= b for a, b in zip(soc, soc[1:]))
    assert p[0] == ev_tiers.EV_TIER_VALUE_HARD and soc[0] == 0.10
    # Reserve bis 35 %, Komfort bis 70 %, Sparzone bis 90 %, oben hoechstens 5 ct
    assert soc[1:4] == [0.35, 0.70, 0.90]
    assert p[1] > p[2] > p[3] > p[4]
    assert p[4] == 0.05 and p[5] == 0.05
    h = _history()
    assert abs(p[2] - round(ev_tiers.quantile(h, 0.20), 4)) < 1e-9
    assert abs(p[3] - round(ev_tiers.quantile(h, 0.10), 4)) < 1e-9


def test_dynamic_tiers_komfort_has_no_saving_zone():
    t = ev_tiers.build_tiers("Komfort", _history(), [0.3], pv_mode=False)
    # Reserve bis 45 %, Komfort bis 90 %, darueber 5 ct -> 4 verschiedene Stufen, Rest aufgefuellt
    assert t["soc"][:3] == [0.10, 0.45, 0.90]
    assert t["p"][3] == 0.05 and t["p"][4] == 0.05 and t["soc"][3:] == [1.0, 1.0]


def test_known_prices_without_history():
    t = ev_tiers.build_tiers("sehr günstig", None, [0.30, 0.25, 0.30], pv_mode=False)
    p = t["p"]
    assert t["basis"].startswith("bekannte Preise")
    assert abs(p[2] - 0.28) < 1e-9          # guenstigster + 3 ct bis zum Komfort-Ladestand
    assert p[1] > p[2]                      # Reserve ueber allen bekannten Preisen
    assert p[4] == 0.05                     # darueber nur bei sehr billigem Strom


def test_short_history_falls_back_to_known_prices():
    t = ev_tiers.build_tiers("mittel", _history(days=5), [0.30], pv_mode=False)
    assert t["basis"].startswith("bekannte Preise")


def test_no_prices_no_tiers():
    assert ev_tiers.build_tiers("mittel", None, [], pv_mode=False) is None


def test_pv_mode_caps_above_reserve_and_stops_at_pv_cap():
    t = ev_tiers.build_tiers("sehr günstig", _history(), [0.3], pv_mode=True, sell_ref=0.07)
    p, soc = t["p"], t["soc"]
    # Reserve (10-25 %) bleibt ungedeckelt; darueber hoechstens Einspeisepreis + 3 ct bis zur PV-Grenze 70 %, danach knapp unter dem Einspeisepreis
    assert soc[:4] == [0.10, 0.25, 0.50, 0.70] or soc[:3] == [0.10, 0.25, 0.70]
    assert p[1] > 0.10
    assert abs(p[2] - 0.10) < 1e-9
    below_cap = [v for v, hi in zip(p, soc + [1.0]) if hi > 0.70 + 1e-9 and v < 0.10]
    assert below_cap and all(v <= 0.06 + 1e-9 for v in below_cap) and abs(max(below_cap) - 0.06) < 1e-9
    assert all(a >= b for a, b in zip(p, p[1:]))


def test_pv_mode_negative_feed_in_allows_full_charge():
    t = ev_tiers.build_tiers("Komfort", _history(), [0.3], pv_mode=True, sell_ref=-0.02)
    # Einspeisung kostet: Stufen oberhalb der Reserve sind ueberall nicht teurer als sell_ref + 3 ct
    assert max(t["p"][2:]) <= 0.01 + 1e-9
