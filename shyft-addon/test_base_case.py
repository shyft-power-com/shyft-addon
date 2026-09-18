import base_case


def _demo_csv():
    with open("shyft-addon/demo_data/demo_input.csv", encoding="utf-8") as f:
        return f.read()


def test_demo_shape():
    result = base_case.compute_base_case(_demo_csv())
    assert set(result) == {
        "netProfitBase48HoursSum", "netProfitBaseList", "PowerUsageBaseList", "nextState",
        "T_iBaseList", "T_HWBaseList", "SOC_BBaseList", "SOC_EVBaseList", "ODLoadBaseList", "endValue",
    }
    assert len(result["netProfitBaseList"]) == 48
    assert len(result["PowerUsageBaseList"]) == 48
    assert len(result["T_iBaseList"]) == 48
    assert len(result["T_HWBaseList"]) == 48
    assert len(result["SOC_BBaseList"]) == 48
    assert len(result["SOC_EVBaseList"]) == 48
    assert len(result["ODLoadBaseList"]) == 48
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


def test_od_runs_only_below_price_threshold():
    # otherDevice_P=2.0, OD_running_hours=10 -> Schwelle 0.10 EUR/kWh (Julia: /100). p_buy
    # unterschreitet die Schwelle in Stunde 0+2, nicht in Stunde 1 - OD darf nur dort laufen.
    header = (
        "electkwh;heatingkwh;hw_usage_h;heating;hotwaterkwh;ev_usage_h;d_ev_kwh;PV_generation;"
        "Temperature;p_buy;p_sell;b_soc_max_kWh;SOC_b_0_percent;T_hw_0;hp_max_power;hw_tankSize;"
        "T_supply_max;hw_soc_min;fh_size;fh_eff;T_i_0;T_i_min;T_i_buffer;curve_level;curve_slope;"
        "otherDevice_P;otherDevice_SOC;OD_running_hours;ev_soc_norm;ev_b_size;ev_charge_rate;"
        "ev_soc_0;p_min;OptimizerPeriods;CO;p_gas;CO_0;hp_type;b_soc_min"
    )
    rows = [
        "0.5;0;;;0;;0;0;10;0.05;0.08;0;0;0;3;0;60;44;0;0;20;20;0.3;0;0;2.0;0;10;0;0;0;0;0;3;no;0.1;0;Air-Water;10",
        "0.5;0;;;0;;0;0;10;0.15;0.08;0;0;0;3;0;60;44;0;0;20;20;0.3;0;0;2.0;0;10;0;0;0;0;0;3;no;0.1;0;Air-Water;10",
        "0.5;0;;;0;;0;0;10;0.05;0.08;0;0;0;3;0;60;44;0;0;20;20;0.3;0;0;2.0;0;10;0;0;0;0;0;3;no;0.1;0;Air-Water;10",
    ]
    result = base_case.compute_base_case("\n".join([header] + rows))
    assert result["ODLoadBaseList"] == [2.0, 0.0, 2.0]
    assert result["PowerUsageBaseList"] == [2.5, 0.5, 2.5]
    assert result["netProfitBaseList"] == [round(2.5 * 0.05, 6), round(0.5 * 0.15, 6), round(2.5 * 0.05, 6)]


def test_od_load_reduces_pv_surplus_available_to_other_consumers():
    # Ohne OD deckt die PV die Grundlast komplett und speist den Rest ein (Ertrag, negative
    # Kosten). Mit eingeschaltetem OD (gleiche Schwelle, gleicher p_buy) wird derselbe
    # PV-Ueberschuss zusaetzlich vom "Sonstigen Verbraucher" beansprucht - der Netzbezug (und
    # damit die Kosten) muessen dadurch steigen, nicht gleich bleiben (Nutzer-Vorgabe: OD-Verbrauch
    # steht anderen Verbrauchern nicht mehr zur Verfuegung, genau wie beim Optimierer).
    header = (
        "electkwh;heatingkwh;hw_usage_h;heating;hotwaterkwh;ev_usage_h;d_ev_kwh;PV_generation;"
        "Temperature;p_buy;p_sell;b_soc_max_kWh;SOC_b_0_percent;T_hw_0;hp_max_power;hw_tankSize;"
        "T_supply_max;hw_soc_min;fh_size;fh_eff;T_i_0;T_i_min;T_i_buffer;curve_level;curve_slope;"
        "otherDevice_P;otherDevice_SOC;OD_running_hours;ev_soc_norm;ev_b_size;ev_charge_rate;"
        "ev_soc_0;p_min;OptimizerPeriods;CO;p_gas;CO_0;hp_type;b_soc_min"
    )
    row_with_od = "0.5;0;;;0;;0;1.0;10;0.20;0.08;0;0;0;3;0;60;44;0;0;20;20;0.3;0;0;2.0;0;100;0;0;0;0;0;1;no;0.1;0;Air-Water;10"
    row_without_od = "0.5;0;;;0;;0;1.0;10;0.20;0.08;0;0;0;3;0;60;44;0;0;20;20;0.3;0;0;0;0;100;0;0;0;0;0;1;no;0.1;0;Air-Water;10"

    with_od = base_case.compute_base_case("\n".join([header, row_with_od]))
    without_od = base_case.compute_base_case("\n".join([header, row_without_od]))

    assert without_od["ODLoadBaseList"] == [0.0]
    assert with_od["ODLoadBaseList"] == [2.0]
    # ohne OD: PV-Ueberschuss wird eingespeist -> negative Kosten (Ertrag)
    assert without_od["netProfitBaseList"][0] < 0.0
    # mit OD: derselbe Ueberschuss reicht nicht mehr, echter Netzbezug -> positive Kosten
    assert with_od["netProfitBaseList"][0] > 0.0


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


def _ev_csv(soc0, trips, horizon=8, b_size=60.0, rate=11.0, norm=0.5):
    # trips: {1-basierte Stunde: Fahrverbrauch kWh} - in diesen Stunden ist das Auto unterwegs
    header = (
        "electkwh;heatingkwh;hw_usage_h;heating;hotwaterkwh;ev_usage_h;d_ev_kwh;PV_generation;"
        "Temperature;p_buy;p_sell;b_soc_max_kWh;SOC_b_0_percent;T_hw_0;hp_max_power;hw_tankSize;"
        "T_supply_max;hw_soc_min;fh_size;fh_eff;T_i_0;T_i_min;T_i_buffer;curve_level;curve_slope;"
        "otherDevice_P;otherDevice_SOC;OD_running_hours;ev_soc_norm;ev_b_size;ev_charge_rate;"
        "ev_soc_0;p_min;OptimizerPeriods;CO;p_gas;CO_0;hp_type;b_soc_min"
    )
    rows = []
    away = sorted(trips)
    for h in range(1, horizon + 1):
        usage_h = str(away[h - 1]) if h - 1 < len(away) else ""
        d_ev = trips.get(h, 0)
        rows.append(f"0.5;0;;;0;{usage_h};{d_ev};0;10;0.20;0.08;0;0;0;3;0;60;44;0;0;20;20;0.3;0;0;0;0;0;{norm};{b_size};{rate};{soc0};0.1;{horizon};no;0.1;0;Air-Water;10")
    return "\n".join([header] + rows)


def test_ev_soc_never_negative_for_coverable_trip():
    # Fahrt in Stunde 5 braucht 27 kWh (0.45 des 60-kWh-Akkus), Start bei 20 % -> muss vorher
    # nachgeladen werden. Der SOC (Optimierer-Nebenbedingung: SOC_EV >= 0 fuer erfuellbare Fahrten,
    # <= soc_max) darf nie unter 0 oder ueber die Kapazitaet gehen, auch nicht durch den variablen
    # Ladeverlust (frueher landete er knapp unter 0).
    result = base_case.compute_base_case(_ev_csv(soc0=0.2, trips={5: 27.0}))
    soc = result["SOC_EVBaseList"]
    assert min(soc) >= -1e-9
    assert max(soc) <= 1.0 + 1e-9
    assert result["endValue"]["soc_ev_kwh_end"] >= -1e-9


def test_ev_trace_is_start_of_hour_state():
    # Stunde 0 des Traces ist der Startzustand (wie SOC_EV[1] im Optimierer), nicht der Zustand nach Stunde 0.
    result = base_case.compute_base_case(_ev_csv(soc0=0.2, trips={5: 27.0}))
    assert abs(result["SOC_EVBaseList"][0] - 0.2) < 1e-9
