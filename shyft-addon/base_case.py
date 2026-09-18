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
* "Sonstiger Verbraucher" (OD) war im Excel-Modell gar nicht enthalten, ist aber im aktuellen
  Julia-Modell aktiv: es laeuft (mit fixer Leistung ``otherDevice_P``) genau dann, wenn ``p_buy``
  unter dem in ``OD_running_hours`` hinterlegten Schwellenpreis liegt (Cent/kWh, /100 fuer EUR/kWh
  - der Name ist eine Altlast, siehe run_SHEMS.jl:137 "is now threshold price (didn't rename the
  variable)"; eine Mindestlaufzeit gibt es nicht (mehr), der einzige Julia-Codepfad dafuer ist
  auskommentiert). Base Case wendet dieselbe Schwelle an wie der Optimierer (Nutzer-Vorgabe) - fuer
  dieses Geraet selbst ergibt sich dadurch strukturell KEINE Ersparnis (beide Modelle treffen exakt
  dieselbe Ein/Aus-Entscheidung), sein Verbrauch steht aber, genau wie beim Optimierer, den anderen
  Verbrauchern nicht mehr aus PV/Batterie zur Verfuegung.

Rueckgabe (Excel-Referenzen in Klammern):
  netProfitBase48HoursSum : float   - Gesamtkosten Base Case inkl. Restwerte (O106);
                                      == sum(netProfitBaseList)
  netProfitBaseList        : [float] - Netto-Netzkosten je Stunde, + = Kosten (O58:O105);
                                      die Endwert-Korrektur steckt komplett in der letzten Stunde
  PowerUsageBaseList       : [float] - Brutto-Stromverbrauch je Stunde inkl. EV- und
                                       Batterieladung (P58:P105, neu definiert)
  T_iBaseList/T_HWBaseList/SOC_BBaseList/SOC_EVBaseList : [float] je Stunde - reine Debug-/
                                       Vergleichs-Traces, kein Excel-Aequivalent; direkt vergleichbar
                                       mit den gleichnamigen Optimierer-Output-Spalten T_i/T_HW/
                                       SOC_B/SOC_EV (SOC_EV normiert 0..1 wie beim Optimierer)
  ODLoadBaseList           : [float] - Leistung des "Sonstigen Verbrauchers" je Stunde (0 oder
                                       otherDevice_P) - Debug-Trace, vergleichbar mit der
                                       Optimierer-Output-Spalte OD_Power
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
    "otherDevice_P", "OD_running_hours",
)
# run_SHEMS.jl:137/227-230: OD_running_hours ist trotz des Namens (Altlast, siehe Julia-Kommentar
# "is now threshold price (didn't rename the variable)") LAENGST keine Mindestlaufzeit mehr, sondern
# ein Schwellenpreis in Cent/kWh, /100 fuer EUR/kWh - "Sonstiger Verbraucher" laeuft oekonomisch nur,
# wenn p_buy darunter liegt. Es gibt keine Mindestlaufzeit-Garantie (der einzige Julia-Codepfad dafuer
# ist auskommentiert). Nutzer-Vorgabe: Base Case wendet dieselbe Schwelle an wie der Optimierer - dann
# gibt es fuer dieses Geraet selbst strukturell keine Ersparnis (beide Modelle treffen dieselbe
# Ein/Aus-Entscheidung), was fuer diesen speziellen Aktionstyp korrekt ist. Wichtig bleibt aber, dass
# sein Verbrauch (wenn an) den anderen Verbrauchern nicht mehr zur Verfuegung steht - siehe "load" unten.
OD_CENT_TO_EUR = 100.0
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


def compute_base_case(input_csv, state_overrides=None):
    """Berechnet den Base Case aus dem Optimierer-``input_csv`` (``;``-getrennt).

    state_overrides (optional): {"T_i_0", "T_hw_0", "ev_soc_0", "SOC_b_0_percent"} - ersetzt die
    gleichnamigen Startwerte aus ``input_csv``, Nachfrage-/Wetter-/Preis-Reihen (_SERIES_KEYS/
    _HOURLIST_KEYS) kommen immer unveraendert aus dem aktuellsten input_csv. Ohne Override (None,
    oder ein einzelner Schluessel fehlt/ist None) faellt der jeweilige Startwert auf input_csv
    zurueck - so bei der allerersten Berechnung und wenn die Fortschreibungs-Kette abreisst (siehe
    Aufrufer in app.py, der das zurueckgegebene "nextState" fuer den naechsten Aufruf persistiert).

    Grund fuer die Overrides (Nutzer-Beobachtung): ohne sie startet JEDE stuendliche Neuberechnung
    mit dem ECHTEN, vom Optimierer bereits guenstig vorbereiteten Zustand (vorgeheiztes Haus, volle
    Batterie, warmes Wasser) - der Base Case wuerde sich so den Erfolg der Optimierung leihen, ohne
    je fuer eine eigene (schlechtere) Vorstunden-Entscheidung zu bezahlen. Mit den Overrides fuehrt
    der Base Case stattdessen seine EIGENE Zustands-Trajektorie fort, komplett unabhaengig vom
    tatsaechlichen/optimierten Zustand - dadurch wird eine einzelne Stunde weniger direkt mit dem
    Optimierer vergleichbar, aber der Vergleich ueber laengere Zeitraeume (siehe Analyse-Tab) korrekt.

    Gibt ein Dict mit ``netProfitBase48HoursSum`` / ``netProfitBaseList`` / ``PowerUsageBaseList`` /
    ``nextState`` (Zustand NACH Stunde 0 - Basis fuer den naechsten Aufruf) zurueck, oder ``None``,
    wenn das CSV nicht auswertbar ist (nie eine Exception nach aussen).
    """
    try:
        return _compute_base_case(input_csv, state_overrides)
    except Exception as exc:  # pragma: no cover - defensiv, Aufrufer soll nie brechen
        print("[Shyft] Base-Case-Berechnung fehlgeschlagen:", repr(exc))
        return None


_STATE_OVERRIDE_KEYS = ("T_i_0", "T_hw_0", "ev_soc_0", "SOC_b_0_percent")


def _compute_base_case(input_csv, state_overrides=None):
    rows = list(csv.DictReader(io.StringIO(input_csv or ""), delimiter=";"))
    if not rows:
        return None

    p = {key: _num(rows[0].get(key)) for key in _SCALAR_KEYS}
    if state_overrides:
        for key in _STATE_OVERRIDE_KEYS:
            value = state_overrides.get(key)
            if value is not None:
                p[key] = value
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

    # "Sonstiger Verbraucher" (OD) - siehe _SCALAR_KEYS-Kommentar oben: dieselbe Schwellenpreis-
    # Logik wie run_SHEMS.jl:227-230, damit beide Modelle fuer dieses Geraet dieselbe Ein/Aus-
    # Entscheidung treffen. otherDevice_P <= 0 bedeutet "kein Geraet konfiguriert" (run_SHEMS.jl:110).
    od_power = p["otherDevice_P"]
    od_active = od_power > 0.0
    od_threshold_eur = p["OD_running_hours"] / OD_CENT_TO_EUR

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
    t_i_list = [0.0] * horizon  # T_i ZU BEGINN jeder Stunde (wie T_i[1:h_end] im Optimierer-Output) - Debug-/Vergleichs-Trace ("T_iBaseList")
    t_i = t_i_0
    t_i_after_hour0 = None  # Zustand NACH Stunde 0 (siehe compute_base_case/state_overrides) - erfasst zu Beginn von Iteration 1, bevor die dortige Mutation greift
    for i in range(horizon):
        if i == 1:
            t_i_after_hour0 = t_i
        t_i_list[i] = t_i
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
    if t_i_after_hour0 is None:  # horizon == 1: die einzige Iteration war bereits Stunde 0
        t_i_after_hour0 = t_i_end

    # --- Warmwasser: Sofortbereitstellung; Tank kuehlt zwischen den Zapfungen weiter aus - und muss
    # am Horizont-Ende wieder auf T_hw_0 sein (Optimierer-Endbedingung run_SHEMS.jl:223
    # T_hw[h_end+1] >= T_hw_0): den Fehlbetrag heizt die WP in den LETZTEN Stunden nach (so spaet wie
    # moeglich, rueckwaerts von der letzten Stunde bis zur WP-Leistungsgrenze aufgefuellt).
    hp_dhw = [0.0] * horizon
    hw_extra = [0.0] * horizon  # zusaetzliche elektrische Nachheiz-Energie je Stunde (kWh)
    t_hw_starts = [t_hw] * (horizon + 1)
    cop_hw_last = COP_MIN

    def _simulate_hw():
        "Tank-Trajektorie mit der aktuellen Nachheiz-Belegung hw_extra (run_SHEMS.jl:219: T[h+1] = T - (T-20)*loss + c_hw*(cop*X10 - d_hw))."
        starts = [t_hw_0]
        base_el = [0.0] * horizon
        cop_last = COP_MIN
        t = t_hw_0
        for i in range(horizon):
            t_loss = t - (t - 20.0) * HW_LOSS  # Zufuhr == Zapfung -> reine Abkuehlung (Excel-Spalte S)
            t_next = t_loss
            cop = COP_MIN
            for _ in range(4):  # cop haengt von der mittleren Tanktemperatur ab (implizit) -> Fixpunkt
                cop = max(COP_MIN, 5.5 - ((t + t_next) / 2.0 - t_out[i]) / 20.0)
                t_next = t_loss + c_hw * cop * hw_extra[i]
            if d_hw[i] > 0.0:
                base_el[i] = d_hw[i] / cop
            cop_last = cop
            starts.append(t_next)
            t = t_next
        return starts, base_el, cop_last

    if hw_active:
        t_hw_starts, hp_dhw, cop_hw_last = _simulate_hw()
        if c_hw > 0.0:
            for _ in range(40):
                deficit = t_hw_0 - t_hw_starts[horizon]
                if deficit <= 1e-4:
                    break
                energy = deficit / (c_hw * cop_hw_last)
                for i in range(horizon - 1, -1, -1):
                    room = max(0.0, p["hp_max_power"] - hp_heat[i] - hp_dhw[i] - hw_extra[i])
                    add = min(room, energy)
                    hw_extra[i] += add
                    energy -= add
                    if energy <= 1e-9:
                        break
                if energy > 1e-9:
                    break  # WP-Leistung reicht nicht mehr - Rest bleibt als Fehlbetrag (siehe term_hw)
                t_hw_starts, hp_dhw, cop_hw_last = _simulate_hw()
        hp_dhw = [hp_dhw[i] + hw_extra[i] for i in range(horizon)]
    t_hw_list = t_hw_starts[:horizon]  # T_HW ZU BEGINN jeder Stunde (wie T_hw[1:h_end] im Optimierer-Output) - Debug-/Vergleichs-Trace ("T_HWBaseList")
    t_hw_end = t_hw_starts[horizon]
    t_hw_after_hour0 = t_hw_starts[1] if horizon > 1 else t_hw_end

    # --- E-Auto: sofort bis ev_soc_norm; Fahrten so spaet wie moeglich abdecken ---------
    ev_charge_gross = [0.0] * horizon
    soc_ev = soc_ev_0
    soc_ev_list = [soc_ev_0 / ev_b_size if ev_b_size > 0 else 0.0] * horizon  # SOC_EV ZU BEGINN jeder Stunde, normiert (0..1) - wie SOC_EV[1:h_end] im Optimierer-Output; Debug-/Vergleichs-Trace ("SOC_EVBaseList")
    soc_ev_after_hour0 = None
    if ev_active:
        eff_rate = max(0.0, ev_rate_max * EV_ETA - EV_FIXED_LOSS_KWH)  # Netto-SOC-Gewinn je voller Ladestunde
        # Mindest-SOC zu Beginn jeder Stunde, um alle kuenftigen Fahrten zu decken - rueckwaerts durch
        # dieselbe Bilanz wie der Optimierer (run_SHEMS.jl:232: SOC[h+1] = SOC[h]*(1-loss) + Ladung
        # - d_ev[h]), INKL. des variablen Verlusts; ohne ihn landete der SOC vor einer Fahrt knapp
        # unter 0 (Rundungs-Verletzung der Nebenbedingung SOC_EV >= 0 fuer eine erfuellbare Fahrt).
        required = [0.0] * (horizon + 1)
        for i in range(horizon - 1, -1, -1):
            plugged_i = (i + 1) not in ev_away_hours
            need = required[i + 1] + d_ev[i] - (eff_rate if plugged_i else 0.0)
            required[i] = min(max(0.0, need) / (1.0 - EV_LOSS), ev_b_size)
            if i == horizon - 1:
                # Endbedingung (Optimierer: SOC_EV[h] >= ev_soc_norm bis zur letzten Stunde, run_SHEMS.jl:236):
                # der Ladestand zu Beginn der letzten Stunde muss den Normwert erreichen - waere das Auto
                # in den Stunden davor unterwegs, wird das rueckwaerts bis in die letzten Ladestunden
                # durchgereicht (so spaet wie moeglich, aber rechtzeitig).
                required[i] = max(required[i], min(ev_soc_norm_kwh, ev_b_size))
        for i in range(horizon):
            if i == 1:
                soc_ev_after_hour0 = soc_ev
            soc_ev_list[i] = soc_ev / ev_b_size
            soc_no_charge = soc_ev * (1 - EV_LOSS) - d_ev[i]  # Ende der Stunde ohne Ladung
            plugged = (i + 1) not in ev_away_hours
            if plugged:
                # Pflicht: kuenftige Fahrten abdecken (keine Hysterese - sonst faellt der SOC vor der
                # Fahrt unter 0). Komfort: ev_soc_norm halten, dort mit Hysterese (0.2 kWh Fixverlust
                # je Ladestunde -> ein reales, ungeregeltes System jagt kein Mini-Defizit hinterher).
                need_trip = required[i + 1] - soc_no_charge
                need_norm = ev_soc_norm_kwh - soc_no_charge
                if need_trip > 1e-9 or need_norm > EV_FIXED_LOSS_KWH:
                    gain = min(max(need_trip, need_norm), eff_rate, ev_b_size - soc_no_charge)  # <= soc_max und <= rate_max
                    if gain > 1e-9:
                        ev_charge_gross[i] = (gain + EV_FIXED_LOSS_KWH) / EV_ETA
                        soc_ev = soc_no_charge + gain
                        continue
            soc_ev = soc_no_charge
    soc_ev_end = soc_ev
    if soc_ev_after_hour0 is None:
        soc_ev_after_hour0 = soc_ev_end

    # --- Sonstiger Verbraucher (OD): dieselbe Schwellenpreis-Entscheidung wie der Optimierer, siehe
    # od_active/od_threshold_eur oben - laeuft rein reaktiv je Stunde (kein Vorausplanen noetig, die
    # Entscheidung haengt nur vom jeweils AKTUELLEN p_buy ab, nicht von einem Mindestlaufzeit-Ziel).
    od_load = [0.0] * horizon
    if od_active:
        for i in range(horizon):
            if p_buy[i] < od_threshold_eur:
                od_load[i] = od_power

    # --- Batterie (Eigenverbrauch) + Netzsaldo + Kosten -------------------------------
    # Endbedingung wie beim Optimierer (run_SHEMS.jl:182: SOC_b[h_end+1] >= max(0.9*SOC_b_0, b.soc_min)):
    # Pflicht-SOC je Stunde rueckwaerts ("so spaet wie moeglich, aber rechtzeitig") - liegt der Speicher
    # darunter, wird der Fehlbetrag in den letzten Stunden aus dem Netz nachgeladen und darunter nicht mehr
    # entladen. Ladeleistung wie in der Schleife unten (charge_soc <= b_rate_max je Stunde).
    soc_b_start_kwh = soc_b
    soc_b_target = max(0.9 * soc_b_start_kwh, b_soc_min_kwh) if b_soc_max > 0 else 0.0
    required_b = [0.0] * (horizon + 1)
    required_b[horizon] = soc_b_target
    for i in range(horizon - 1, -1, -1):
        required_b[i] = min(b_soc_max, max(0.0, required_b[i + 1] - b_rate_max) / (1.0 - B_LOSS))
    net_cost_list = [0.0] * horizon
    power_usage_list = [0.0] * horizon
    soc_b_list = [0.0] * horizon  # SOC_B ZU BEGINN jeder Stunde in % (wie SOC_B im Optimierer-Output) - Debug-/Vergleichs-Trace ("SOC_BBaseList")
    soc_b_after_hour0 = None
    for i in range(horizon):
        if i == 1:
            soc_b_after_hour0 = soc_b
        soc_b_list[i] = soc_b / b_soc_max * 100.0 if b_soc_max > 0 else 0.0
        pv_avail = g_e[i] * PV_ETA
        # E-Auto laeuft im Base Case nie ueber PV/Batterie (Excel) - OD dagegen schon: sein Verbrauch
        # soll den anderen Verbrauchern (Nutzer-Vorgabe) nicht zusaetzlich zur Verfuegung stehen,
        # genau wie beim Optimierer, wo PV_OD/B_OD/GR_OD sich denselben PV-/Batterie-Fluss mit den
        # uebrigen Verbrauchern teilen.
        load = d_e[i] + hp_heat[i] + hp_dhw[i] + od_load[i]
        net = pv_avail - load
        batt_charge_gross = 0.0
        charge_soc = 0.0
        floor_b = max(b_soc_min_kwh, required_b[i + 1])  # nicht unter den Pflicht-SOC entladen
        if net > 1e-9:
            room = b_soc_max - soc_b * (1 - B_LOSS)
            charge_soc = max(0.0, min(net * B_ETA, b_rate_max, room))
            soc_b = soc_b * (1 - B_LOSS) + charge_soc
            batt_charge_gross = charge_soc / B_ETA
            grid = net - batt_charge_gross
        elif net < -1e-9:
            avail = soc_b * (1 - B_LOSS) - floor_b
            discharge_soc = max(0.0, min(-net / B_ETA, b_rate_max, avail))
            soc_b = soc_b * (1 - B_LOSS) - discharge_soc
            grid = net + discharge_soc * B_ETA
        else:
            soc_b = soc_b * (1 - B_LOSS)
            grid = 0.0
        if b_soc_max > 0 and soc_b < required_b[i + 1] - 1e-9:
            # Pflicht-Nachladung aus dem Netz (Endbedingung), begrenzt durch Ladeleistung und Kapazitaet
            extra = max(0.0, min(required_b[i + 1] - soc_b, b_rate_max - charge_soc, b_soc_max - soc_b))
            soc_b += extra
            extra_gross = extra / B_ETA
            batt_charge_gross += extra_gross
            grid -= extra_gross
        grid -= ev_charge_gross[i]  # E-Auto-Ladung immer aus dem Netz
        # grid > 0: Einspeisung (Ertrag, negative Kosten) | grid < 0: Bezug (Kosten)
        net_cost_list[i] = (-grid * (p_sell[i] if grid > 0 else p_buy[i])) or 0.0  # or 0.0: kein -0.0
        power_usage_list[i] = d_e[i] + hp_heat[i] + hp_dhw[i] + ev_charge_gross[i] + batt_charge_gross + od_load[i]
    soc_b_end = soc_b
    if soc_b_after_hour0 is None:
        soc_b_after_hour0 = soc_b_end

    # --- Restwerte am Horizont-Ende: Batterie/EV/Warmwasser erfuellen die Endbedingungen des Optimierers
    # jetzt durch Nachladen in den letzten Stunden (siehe oben) - eine zusaetzliche Bewertung der
    # Zustandsdifferenz (frueher: Endzustand vs. Startzustand zu p_min/Durchschnittspreis) entfaellt damit.
    # Uebrig bleiben nur FEHLBETRAEGE, falls die Endbedingung physikalisch nicht mehr erreichbar war
    # (z.B. Ladeleistung zu klein), sowie der Raumtemperatur-Term (dort kein Zwangsheizen - der Base Case
    # haelt T_i ohnehin so knapp wie moeglich, der Unterschied ist Rundungsgroesse).
    last_p_buy = p_buy[horizon - 1]
    mean_p_buy = statistics.fmean(p_buy) if p_buy else 0.0
    term_battery = -max(0.0, soc_b_target - soc_b_end) * mean_p_buy  # <= 0; residual = ... - term_battery
    term_ev = 0.0
    term_hw = 0.0
    if hw_active and c_hw > 0.0 and cop_hw_last > 0.0:
        term_hw = max(0.0, t_hw_0 - t_hw_end) / (c_hw * cop_hw_last) * last_p_buy
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
        # Physikalische Zustands-Traces je Stunde - fuers Debugging/den Vergleich gegen die
        # gleichnamigen Optimierer-Output-Spalten (T_i, T_HW, SOC_B, SOC_EV) gedacht, fliessen in
        # keine der obigen Kostenzahlen zusaetzlich ein (die stecken dort schon drin).
        "T_iBaseList": [round(v, 6) for v in t_i_list],
        "T_HWBaseList": [round(v, 6) for v in t_hw_list],
        "SOC_BBaseList": [round(v, 6) for v in soc_b_list],
        "SOC_EVBaseList": [round(v, 6) for v in soc_ev_list],
        "ODLoadBaseList": [round(v, 6) for v in od_load],
        # Aufschluesselung der Endwert-Korrektur (steckt komplett in der LETZTEN Stunde von
        # netProfitBaseList) - Debug: Positiv = Kosten. Start-/Endzustaende in den Einheiten der
        # jeweiligen Terme (kWh bzw. Grad), Preise in EUR/kWh.
        "endValue": {
            "residual": round(residual, 6),
            "term_hw": round(term_hw, 6),
            "term_battery": round(-term_battery, 6),
            "term_ev": round(-term_ev, 6),
            "term_i": round(-term_i, 6),
            "soc_b_kwh_start": round(soc_b_start_kwh, 4),
            "soc_b_kwh_target": round(soc_b_target, 4),
            "soc_b_kwh_end": round(soc_b_end, 4),
            "soc_ev_kwh_start": round(soc_ev_0, 4),
            "soc_ev_kwh_end": round(soc_ev_end, 4),
            "t_hw_start": round(t_hw_0, 3),
            "t_hw_end": round(t_hw_end, 3),
            "t_i_start": round(t_i_0, 3),
            "t_i_end": round(t_i_end, 3),
            "mean_p_buy": round(mean_p_buy, 5),
            "last_p_buy": round(last_p_buy, 5),
            "p_min": round(p_min, 5),
            "ev_b_size": round(ev_b_size, 3),
            "b_soc_max_kwh": round(b_soc_max, 3),
        },
        # Zustand NACH Stunde 0 (nicht der Endzustand des gesamten Horizonts) - Grundlage fuer den
        # naechsten Aufruf ueber state_overrides (siehe Docstring oben und Aufrufer in app.py).
        "nextState": {
            "T_i_0": round(t_i_after_hour0, 6),
            "T_hw_0": round(t_hw_after_hour0, 6),
            "ev_soc_0": round(soc_ev_after_hour0 / ev_b_size, 6) if ev_b_size > 0 else 0.0,
            "SOC_b_0_percent": round(soc_b_after_hour0 / b_soc_max * 100.0, 6) if b_soc_max > 0 else 0.0,
        },
    }
