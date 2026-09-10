"""Base-Case-Simulation - was ohne Shyft-Optimierung passiert waere.

Sequentielle Stunden-Simulation ueber denselben ``input_csv``, den der Julia-Optimierer
bekommt (``optimizer/src/main/julia/run_SHEMS.jl`` im Repo ``shyft``). Keine
Vorausplanung: der Bedarf wird im Moment des Anfalls gedeckt, die Batterie faehrt reine
Eigenverbrauchsmaximierung, das E-Auto laedt sofort bis ``ev_soc_norm`` und ansonsten so
spaet wie moeglich vor einer Fahrt.

Formeln und Konstanten sind bewusst 1:1 aus ``run_SHEMS.jl`` / ``main.jl`` uebernommen
(COP, Wirkungsgrade, ``P_heatLoss``, ``c_hw``, ``c_store``, Restwert-Terme am Horizont-
Ende), damit ``netProfitBase48HoursSum`` und die spaeter identisch nachgerechnete
Optimierer-Zahl auf demselben Fundament stehen - nur dann gilt strukturell
"Base-Case-Kosten <= Optimierer-Kosten".

Nachbildung des Excel-Reiters ``BasePrice3`` (Shyft Middleware), mit diesen bewussten
Abweichungen Richtung aktuellem Julia-Modell (so mit dem Product Owner abgestimmt):

* COP: ``5.5 - dT/20`` (Excel: ``5.8 - dT/14``); DHW-COP tank-temperatur-basiert je Stunde.
* Batterie-Wirkungsgrad 0.92 je Richtung (Excel: 0.95).
* Batterie-Mindest-SOC aus Spalte ``b_soc_min`` (Excel: hart 10 %).
* Waermepumpen-Leistung deckt exakt den Stundenbedarf, keine 20-%-Modulationsuntergrenze,
  kein alternierendes Ueber-/Unterheizen (Excel-Spalte F).
* EV-Wirkungsgrad 0.93 / Verlust 0.00004 / Fixverlust 0.2 kWh je Ladestunde (Julia).

Rueckgabe (Excel-Referenzen in Klammern):
  netProfitBase48HoursSum : float   - Gesamtkosten Base Case inkl. Restwerte (O106);
                                      == sum(netProfitBaseList)
  netProfitBaseList        : [float] - Netto-Netzkosten je Stunde, + = Kosten (O58:O105);
                                      die Endwert-Korrektur steckt komplett in der letzten Stunde
  PowerUsageBaseList       : [float] - Brutto-Stromverbrauch je Stunde inkl. EV- und
                                       Batterieladung (P58:P105, neu definiert)
"""

import csv
import io
import statistics

# --- Konstanten 1:1 aus run_SHEMS.jl / main.jl -------------------------------------------
PV_ETA = 0.95            # pv = PV(0.95f0)
B_ETA = 0.92             # Battery(0.92f0, ...) - bewusst < 0.95 gegen Arbitrage-Grenzfaelle
B_LOSS = 0.00003         # Battery(..., 0.00003f0)
EV_ETA = 0.93            # EV(0.93f0, ...)
EV_LOSS = 0.00004        # EV(..., 0.00004f0)
EV_FIXED_LOSS_KWH = 0.2  # -0.2 * ev_plugged[h] je Ladestunde
HW_LOSS = 0.003          # hw = ThermalStorage(..., loss_hw=0.003, ...)
C_WATER = 4.184
P_WATER = 997.0
C_STORE = 0.486          # Heat storing capacity of building, kWh/K/m2
C_P_TH = 0.006           # fixe Heizleistung (Sonne/Personen/Elektro) kW/m2
C_HEAT_D = 5000 * 24     # Gradtagzahl K*h/a
COP_MIN = 0.5            # cop[1:h_end] >= 0.5

_SCALAR_KEYS = (
    "b_soc_max_kWh", "SOC_b_0_percent", "b_soc_min", "T_hw_0", "hp_max_power",
    "hw_tankSize", "T_supply_max", "hw_soc_min", "fh_size", "fh_eff", "T_i_0", "T_i_min",
    "T_i_buffer", "curve_level", "curve_slope", "ev_soc_norm", "ev_b_size",
    "ev_charge_rate", "ev_soc_0", "p_min", "OptimizerPeriods", "p_gas",
)
_SERIES_KEYS = ("electkwh", "hotwaterkwh", "PV_generation", "Temperature", "p_buy", "p_sell", "d_ev_kwh")
_HOURLIST_KEYS = ("heating", "hw_usage_h", "ev_usage_h")


def _num(value, default=0.0):
    if value is None:
        return default
    text = str(value).strip().replace(",", ".")
    if text == "":
        return default
    try:
        return float(text)
    except ValueError:
        return default


def _hour_set(rows, key):
    "Menge der 1-basierten Stundenindizes, in denen die Spalte einen Wert traegt (wie Julias skipmissing)."
    out = set()
    for row in rows:
        raw = (row.get(key) or "").strip()
        if raw == "":
            continue
        try:
            out.add(int(round(float(raw.replace(",", ".")))))
        except ValueError:
            continue
    return out


def _fh_heat_pump_power(q_thermal, heatdis, t_i_min, t_out_cap, hp_max_power):
    """Elektrische WP-Leistung x9 (kW), sodass x9 * COP_fh(x9) == q_thermal.

    COP_fh = 5.5 - (T_fh - t_out_cap) / 20  mit
    T_fh   = (20*t_i_min + x9*heatdis*(110 + t_out_cap)) / (20 + heatdis*x9)   (run_SHEMS.jl:244/246).
    x9 * COP_fh(x9) ist auf [0, hp_max_power] monoton steigend -> Bisektion.
    """
    if q_thermal <= 0.0:
        return 0.0

    def delivered(x9):
        if x9 <= 0.0:
            return 0.0
        t_fh = (20.0 * t_i_min + x9 * heatdis * (110.0 + t_out_cap)) / (20.0 + heatdis * x9)
        cop = max(COP_MIN, 5.5 - (t_fh - t_out_cap) / 20.0)
        return x9 * cop

    hi = max(hp_max_power, 1e-3)
    if delivered(hi) <= q_thermal:
        return hi  # WP am Anschlag - Gebaeude wuerde leicht auskuehlen (Normal-Auslegung trifft das nicht)
    lo = 0.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if delivered(mid) < q_thermal:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def compute_base_case(input_csv):
    """Berechnet den Base Case aus dem Optimierer-``input_csv`` (``;``-getrennt).

    Gibt ein Dict mit ``netProfitBase48HoursSum`` / ``netProfitBaseList`` /
    ``PowerUsageBaseList`` zurueck, oder ``None``, wenn das CSV nicht auswertbar ist
    (nie eine Exception nach aussen).
    """
    try:
        return _compute_base_case(input_csv)
    except Exception as exc:  # pragma: no cover - defensiv, Aufrufer soll nie brechen
        print("[Shyft] Base-Case-Berechnung fehlgeschlagen:", repr(exc))
        return None


def _compute_base_case(input_csv):
    rows = list(csv.DictReader(io.StringIO(input_csv or ""), delimiter=";"))
    if not rows:
        return None

    p = {key: _num(rows[0].get(key)) for key in _SCALAR_KEYS}
    horizon = int(round(p["OptimizerPeriods"])) if p["OptimizerPeriods"] else len(rows)
    horizon = max(1, min(horizon, len(rows)))
    rows = rows[:horizon]

    series = {key: [_num(row.get(key)) for row in rows] for key in _SERIES_KEYS}
    d_e = series["electkwh"]
    d_hw = series["hotwaterkwh"]
    g_e = series["PV_generation"]
    t_out = series["Temperature"]
    p_buy = series["p_buy"]
    p_sell = series["p_sell"]
    d_ev = series["d_ev_kwh"]

    heating_hours = _hour_set(rows, "heating")
    ev_away_hours = _hour_set(rows, "ev_usage_h")
    hw_active = bool(_hour_set(rows, "hw_usage_h")) or any(v > 0 for v in d_hw)  # run_SHEMS.jl: HW-Block nur wenn hw_usage_h nicht leer

    # --- abgeleitete Parameter (main.jl / run_SHEMS.jl) --------------------------------
    b_soc_max = p["b_soc_max_kWh"]
    b_soc_min_kwh = p["b_soc_min"] / 100.0 * b_soc_max
    soc_b = min(b_soc_max, p["SOC_b_0_percent"] / 100.0 * b_soc_max)
    b_rate_max = 0.5 * b_soc_max

    fh_size = p["fh_size"]
    p_heat_loss = 0.0
    if fh_size > 0 and p["fh_eff"] > 0:
        p_heat_loss = p["fh_eff"] / C_HEAT_D * ((fh_size / 2.5) ** 0.5 * 4 * 5.6 + fh_size / 2.5 * 2)
    t_i_min = p["T_i_min"]
    t_i_buffer_abs = p["T_i_buffer"] + t_i_min
    t_i_0 = min(p["T_i_0"], t_i_buffer_abs)
    if heating_hours:
        t_i_0 = max(t_i_0, t_i_min)

    c_hw = 3600.0 * 1000.0 / (C_WATER * p["hw_tankSize"] * P_WATER) if p["hw_tankSize"] > 0 else 0.0
    t_hw = max(min(p["T_hw_0"], p["T_supply_max"], 80.0), p["hw_soc_min"]) if hw_active else 0.0
    t_hw_0 = t_hw

    ev_b_size = p["ev_b_size"]
    ev_rate_max = p["ev_charge_rate"]
    ev_active = bool(ev_away_hours) and ev_b_size > 0 and ev_rate_max > 0
    ev_soc_norm_kwh = p["ev_soc_norm"] * ev_b_size
    soc_ev_0 = p["ev_soc_0"] * ev_b_size
    p_min = p["p_min"] if ev_active else 0.0  # run_SHEMS.jl: p_min = 0 ohne EV-Nutzung

    # --- Waermepumpe Heizung: exakt den Stundenbedarf decken, T_i auf T_i_min halten ---
    hp_heat = [0.0] * horizon
    t_i = t_i_0
    for i in range(horizon):
        if (i + 1) not in heating_hours or p_heat_loss <= 0.0:
            continue
        t_out_cap = min(t_out[i], t_i_min - C_P_TH * fh_size / p_heat_loss - 4.0)
        span = t_i_min - t_out_cap
        heatdis = (p["curve_level"] + p["curve_slope"] * span) / (p_heat_loss * span - C_P_TH * fh_size)
        # Waermebilanz (run_SHEMS.jl:176-185, Verlustterm linearisiert um T_i_min, CO aus):
        #   dT_i = (COP_fh*x9 + C_P_TH*fh_size - span*P_heatLoss) / (fh_size*C_STORE)
        loss_minus_gain = span * p_heat_loss - C_P_TH * fh_size  # thermischer Nettobedarf, um T_i zu halten
        drift_no_hp = -loss_minus_gain / (fh_size * C_STORE)
        if t_i + drift_no_hp >= t_i_min:
            # Raum ist noch warm genug -> nicht heizen, frei auf T_i_min zutreiben (max. Puffer)
            t_i = min(t_i + drift_no_hp, t_i_buffer_abs)
            continue
        q_thermal = loss_minus_gain + (t_i_min - t_i) * fh_size * C_STORE  # exakt auf T_i_min landen
        hp_heat[i] = _fh_heat_pump_power(q_thermal, heatdis, t_i_min, t_out_cap, p["hp_max_power"])
        t_i = t_i_min
    t_i_end = t_i

    # --- Warmwasser: Sofortbereitstellung; Tank kuehlt zwischen den Zapfungen weiter aus
    hp_dhw = [0.0] * horizon
    cop_hw_last = COP_MIN
    if hw_active:
        for i in range(horizon):
            t_hw_next = t_hw - (t_hw - 20.0) * HW_LOSS  # Zufuhr == Zapfung -> reine Abkuehlung (Excel-Spalte S)
            cop_hw = max(COP_MIN, 5.5 - ((t_hw + t_hw_next) / 2.0 - t_out[i]) / 20.0)
            if d_hw[i] > 0.0:
                hp_dhw[i] = d_hw[i] / cop_hw
            cop_hw_last = cop_hw
            t_hw = t_hw_next
    t_hw_end = t_hw

    # --- E-Auto: sofort bis ev_soc_norm; Fahrten so spaet wie moeglich abdecken ---------
    ev_charge_gross = [0.0] * horizon
    soc_ev = soc_ev_0
    if ev_active:
        eff_rate = max(0.0, ev_rate_max * EV_ETA - EV_FIXED_LOSS_KWH)  # Netto-SOC-Gewinn je voller Ladestunde
        required = [0.0] * (horizon + 1)  # Mindest-SOC zu Beginn jeder Stunde, um alle kuenftigen Fahrten zu decken
        for i in range(horizon - 1, -1, -1):
            if (i + 1) in ev_away_hours:
                required[i] = required[i + 1] + d_ev[i]
            else:
                required[i] = max(0.0, required[i + 1] - eff_rate)
            required[i] = min(required[i], ev_b_size)
        for i in range(horizon):
            plugged = (i + 1) not in ev_away_hours
            if plugged:
                target = max(ev_soc_norm_kwh, required[i + 1])
                # 0.2 kWh Fixverlust je Ladestunde -> ein reales, ungeregeltes System jagt kein
                # Mini-Defizit hinterher; erst ab spuerbarem Ruecktand nachladen (Hysterese).
                if target - soc_ev > EV_FIXED_LOSS_KWH:
                    gain = min(target - soc_ev, ev_rate_max * EV_ETA - EV_FIXED_LOSS_KWH, ev_b_size - soc_ev)
                    if gain > 1e-9:
                        ev_charge_gross[i] = (gain + EV_FIXED_LOSS_KWH) / EV_ETA
                        soc_ev = soc_ev * (1 - EV_LOSS) + ev_charge_gross[i] * EV_ETA - EV_FIXED_LOSS_KWH - d_ev[i]
                        continue
            soc_ev = soc_ev * (1 - EV_LOSS) - d_ev[i]
    soc_ev_end = soc_ev

    # --- Batterie (Eigenverbrauch) + Netzsaldo + Kosten -------------------------------
    net_cost_list = [0.0] * horizon
    power_usage_list = [0.0] * horizon
    for i in range(horizon):
        pv_avail = g_e[i] * PV_ETA
        load = d_e[i] + hp_heat[i] + hp_dhw[i]  # E-Auto laeuft im Base Case nie ueber PV/Batterie (Excel)
        net = pv_avail - load
        batt_charge_gross = 0.0
        if net > 1e-9:
            room = b_soc_max - soc_b * (1 - B_LOSS)
            charge_soc = max(0.0, min(net * B_ETA, b_rate_max, room))
            soc_b = soc_b * (1 - B_LOSS) + charge_soc
            batt_charge_gross = charge_soc / B_ETA
            grid = net - batt_charge_gross
        elif net < -1e-9:
            avail = soc_b * (1 - B_LOSS) - b_soc_min_kwh
            discharge_soc = max(0.0, min(-net / B_ETA, b_rate_max, avail))
            soc_b = soc_b * (1 - B_LOSS) - discharge_soc
            grid = net + discharge_soc * B_ETA
        else:
            soc_b = soc_b * (1 - B_LOSS)
            grid = 0.0
        grid -= ev_charge_gross[i]  # E-Auto-Ladung immer aus dem Netz
        # grid > 0: Einspeisung (Ertrag, negative Kosten) | grid < 0: Bezug (Kosten)
        net_cost_list[i] = (-grid * (p_sell[i] if grid > 0 else p_buy[i])) or 0.0  # or 0.0: kein -0.0
        power_usage_list[i] = d_e[i] + hp_heat[i] + hp_dhw[i] + ev_charge_gross[i] + batt_charge_gross
    soc_b_end = soc_b

    # --- Restwerte am Horizont-Ende (identisch spaeter auf die Optimierer-Ausgabe anwenden)
    last_p_buy = p_buy[horizon - 1]
    mean_p_buy = statistics.fmean(p_buy) if p_buy else 0.0
    term_battery = (soc_b_end - min(b_soc_max, p["SOC_b_0_percent"] / 100.0 * b_soc_max)) * mean_p_buy
    term_ev = (soc_ev_end - soc_ev_0) * p_min / EV_ETA
    term_hw = 0.0
    if hw_active and c_hw > 0.0 and cop_hw_last > 0.0:
        term_hw = (t_hw_0 - t_hw_end) / (c_hw * cop_hw_last) * last_p_buy
    term_i = 0.0
    if heating_hours and fh_size > 0:
        term_i = (t_i_end - t_i_0) / (C_STORE * fh_size) * last_p_buy

    # Endwert-Korrektur (Excel BasePrice3!O106: -AR8 + S108 - T109 - S110) wird komplett auf die
    # LETZTE Stunde des Optimierungszeitraums aufgeschlagen - so ist sum(netProfitBaseList) exakt
    # gleich netProfitBase48HoursSum und der Chart zeigt sie als Ausschlag am rechten Rand.
    residual = term_hw - term_battery - term_ev - term_i
    if net_cost_list:
        net_cost_list[-1] += residual

    return {
        "netProfitBase48HoursSum": round(sum(net_cost_list), 6),
        "netProfitBaseList": [round(v, 6) for v in net_cost_list],
        "PowerUsageBaseList": [round(v, 6) for v in power_usage_list],
    }
