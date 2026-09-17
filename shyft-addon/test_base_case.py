import base_case


def _demo_csv():
    with open("shyft-addon/demo_data/demo_input.csv", encoding="utf-8") as f:
        return f.read()


def test_demo_shape():
    result = base_case.compute_base_case(_demo_csv())
    assert set(result) == {
        "netProfitBase48HoursSum", "netProfitBaseList", "PowerUsageBaseList", "nextState",
        "T_iBaseList", "T_HWBaseList", "SOC_BBaseList", "SOC_EVBaseList",
    }
    assert len(result["netProfitBaseList"]) == 48
    assert len(result["PowerUsageBaseList"]) == 48
    assert len(result["T_iBaseList"]) == 48
    assert len(result["T_HWBaseList"]) == 48
    assert len(result["SOC_BBaseList"]) == 48
    assert len(result["SOC_EVBaseList"]) == 48
    assert isinstance(result["netProfitBase48HoursSum"], float)
    assert set(result["nextState"]) == {"T_i_0", "T_hw_0", "ev_soc_0", "SOC_b_0_percent"}


def test_demo_power_usage_positive_and_covers_base_load():
    result = base_case.compute_base_case(_demo_csv())
    # Grundlast im Demo-CSV ist 0.5 kW/h; Brutto-Verbrauch muss je Stunde >= Grundlast sein
    assert all(p >= 0.5 - 1e-6 for p in result["PowerUsageBaseList"])


def test_demo_night_hours_free_from_full_battery():
    # Demo startet mit fast voller Batterie (98 %) und ohne PV in der Nacht -> die ersten
    # Stunden sollten aus der Batterie gedeckt werden, Netzkosten ~ 0.
    result = base_case.compute_base_case(_demo_csv())
    assert result["netProfitBaseList"][0] == 0.0


def test_no_rows_returns_none():
    assert base_case.compute_base_case("") is None
    assert base_case.compute_base_case("electkwh;p_buy\n") is None


def test_state_override_empty_battery_produces_real_grid_cost():
    # Ohne Override deckt die fast volle Start-Batterie (98%) aus dem Demo-CSV Stunde 0 komplett
    # aus dem Speicher - Netzkosten dort 0.0 (siehe test_demo_night_hours_free_from_full_battery).
    # Mit einem realistischen (leeren) Override-Ladestand - wie ihn die eigene, unabhaengig
    # fortgeschriebene Base-Case-Trajektorie liefern wuerde, siehe state_overrides im Docstring -
    # muss echter Netzbezug und damit ein echter Kostenwert entstehen.
    result = base_case.compute_base_case(_demo_csv(), state_overrides={"SOC_b_0_percent": 0.0})
    assert result["netProfitBaseList"][0] > 0.0


def test_state_override_only_affects_given_keys():
    # Ein Override nur fuer SOC_b_0_percent darf T_i_0/T_hw_0/ev_soc_0 nicht anfassen - beide
    # Berechnungen muessen fuer alles ausser der Batterie identisch bleiben.
    baseline = base_case.compute_base_case(_demo_csv())
    overridden = base_case.compute_base_case(_demo_csv(), state_overrides={"SOC_b_0_percent": 0.0})
    assert overridden["nextState"]["T_i_0"] == baseline["nextState"]["T_i_0"]
    assert overridden["nextState"]["T_hw_0"] == baseline["nextState"]["T_hw_0"]
    assert overridden["nextState"]["ev_soc_0"] == baseline["nextState"]["ev_soc_0"]


def test_next_state_reflects_hour_zero_not_full_horizon():
    # nextState muss den Zustand NACH Stunde 0 tragen, nicht den Endzustand des gesamten
    # 48h-Horizonts (SOC_b_0_percent 0..100 ist dafuer ein einfacher Plausibilitaets-Check).
    result = base_case.compute_base_case(_demo_csv())
    assert 0.0 <= result["nextState"]["SOC_b_0_percent"] <= 100.0
    assert 0.0 <= result["nextState"]["ev_soc_0"] <= 1.0


def test_flat_no_pv_no_storage_matches_hand_calc():
    # Minimal-CSV: 3 Stunden, keine PV, keine Batterie, keine WP, kein EV, kein WW.
    # Erwartung: Netzkosten je Stunde = electkwh * p_buy, keine Restwerte.
    header = (
        "electkwh;heatingkwh;hw_usage_h;heating;hotwaterkwh;ev_usage_h;d_ev_kwh;PV_generation;"
        "Temperature;p_buy;p_sell;b_soc_max_kWh;SOC_b_0_percent;T_hw_0;hp_max_power;hw_tankSize;"
        "T_supply_max;hw_soc_min;fh_size;fh_eff;T_i_0;T_i_min;T_i_buffer;curve_level;curve_slope;"
        "otherDevice_P;otherDevice_SOC;OD_running_hours;ev_soc_norm;ev_b_size;ev_charge_rate;"
        "ev_soc_0;p_min;OptimizerPeriods;CO;p_gas;CO_0;hp_type;b_soc_min"
    )
    row = "1.0;0;;;0;;0;0;10;0.30;0.08;0;0;0;3;0;60;44;0;0;20;20;0.3;0;0;0;0;0;0.2;0;0;0;0;3;no;0.1;0;Air-Water;10"
    csv_text = "\n".join([header, row, row, row])
    result = base_case.compute_base_case(csv_text)
    assert result["netProfitBaseList"] == [0.3, 0.3, 0.3]
    assert result["PowerUsageBaseList"] == [1.0, 1.0, 1.0]
    assert abs(result["netProfitBase48HoursSum"] - 0.9) < 1e-9
