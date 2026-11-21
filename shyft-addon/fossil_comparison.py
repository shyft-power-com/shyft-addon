"""Vergleich "tatsaechliche Kosten vs. fossiler Haushalt" (Kachel im Dashboard, Spalte im Analyse-Tab).

Reine Rechenlogik ohne HA-/Netzzugriff. Der fossile Vergleichshaushalt ersetzt Waermepumpe und E-Auto durch Gaskessel und Benziner (E10):

    Ersparnis = fossile Kosten (Gas + Benzin) - Stromkosten von Waermepumpe + Auto

Die Verbrauchswerte kommen aus dem Optimierer-Ergebnis (HP_FH/HP_HW/EV_sum), siehe app._compute_fossil_summary. Alle Annahmen sind unten als
Konstanten benannt und werden mit dem Ergebnis ausgeliefert. Es sind Naeherungswerte: das Archiv kennt keine Einzelverbraucher-Kosten, daher
wird der durchschnittliche Netzstrompreis (ø Netzstrom der Einsatzplan-Kachel) verwendet.
"""

BOILER_EFFICIENCY = 0.92        # Nutzungsgrad Gas-Brennwertkessel (Waerme / Gas)
COP_MIN = 0.5                   # wie im Optimierer (base_case.COP_MIN)
FLOOR_HEATING_FLOW_TEMP_C = 35.0  # angenommene Vorlauftemperatur der Fussbodenheizung fuer den COP (HP_FH)
DHW_DEFAULT_TANK_TEMP_C = 50.0    # Speichertemperatur fuer den COP der Warmwasserbereitung, falls T_HW fehlt
# Benzin-Aequivalent des E-Auto-Verbrauchs: Radenergie = Ladestrom x Lade-/Antriebswirkungsgrad; ein Benziner braucht dafuer
# Radenergie / Tank-to-Wheel-Wirkungsgrad als Kraftstoffenergie, E10 hat ~8,7 kWh/l.
EV_CHARGE_TO_WHEEL_EFFICIENCY = 0.81   # 0,9 Laden x 0,9 Antrieb
ICE_TANK_TO_WHEEL_EFFICIENCY = 0.25
E10_KWH_PER_LITER = 8.7
ICE_LITERS_PER_EV_KWH = EV_CHARGE_TO_WHEEL_EFFICIENCY / ICE_TANK_TO_WHEEL_EFFICIENCY / E10_KWH_PER_LITER


def hp_cop(flow_temp_c, outdoor_temp_c):
    "COP der Waermepumpe wie im Optimierer: 5,5 - (Vorlauf - Aussen) / 20, mindestens COP_MIN."
    return max(COP_MIN, 5.5 - (flow_temp_c - outdoor_temp_c) / 20.0)


def compute_fossil_savings(heatpump_el_kwh, heat_kwh, ev_kwh, avg_power_price_eur_kwh, e10_eur_per_l, gas_ct_per_kwh, ev_kwh_per_100km):
    """dict mit Kosten/Ersparnis (EUR) fuer den Zeitraum oder None, wenn weder Waermepumpe noch Auto Verbrauch haben bzw. ein noetiger Preis
    fehlt. heat_kwh = von der Waermepumpe gelieferte Waerme (thermisch), die der Gaskessel stattdessen liefern muesste."""
    hp_el = max(heatpump_el_kwh or 0.0, 0.0)
    heat = max(heat_kwh or 0.0, 0.0)
    ev = max(ev_kwh or 0.0, 0.0)
    if avg_power_price_eur_kwh is None or (hp_el <= 0 and ev <= 0):
        return None
    if heat > 0 and gas_ct_per_kwh is None:
        return None
    if ev > 0 and e10_eur_per_l is None:
        return None
    gas_kwh = heat / BOILER_EFFICIENCY
    gas_cost = gas_kwh * (gas_ct_per_kwh or 0.0) / 100.0
    liters = ev * ICE_LITERS_PER_EV_KWH
    fuel_cost = liters * (e10_eur_per_l or 0.0)
    electric_cost = (hp_el + ev) * avg_power_price_eur_kwh
    fossil_cost = gas_cost + fuel_cost
    return {
        "heatpump_el_kwh": round(hp_el, 1), "heat_kwh": round(heat, 1), "ev_kwh": round(ev, 1),
        "gas_kwh": round(gas_kwh, 1), "fuel_liters": round(liters, 1),
        "electric_cost_eur": round(electric_cost, 2),
        "fossil_gas_cost_eur": round(gas_cost, 2),
        "fossil_fuel_cost_eur": round(fuel_cost, 2),
        "fossil_cost_eur": round(fossil_cost, 2),
        "savings_eur": round(fossil_cost - electric_cost, 2),
        "ice_l_per_100km": round((ev_kwh_per_100km or 0.0) * ICE_LITERS_PER_EV_KWH, 1),
        "assumptions": {"boiler_efficiency": BOILER_EFFICIENCY, "ev_kwh_per_100km": ev_kwh_per_100km,
                        "ice_l_per_100km": round((ev_kwh_per_100km or 0.0) * ICE_LITERS_PER_EV_KWH, 1)},
    }


def demo_result():
    "Beispielwerte fuer den Demomodus (noch kein Zugangsschluessel): 5,21 EUR Ersparnis."
    return {"heatpump_el_kwh": 20.0, "heat_kwh": 70.0, "ev_kwh": 15.0, "gas_kwh": 76.1, "fuel_liters": 5.6,
            "electric_cost_eur": 10.5, "fossil_gas_cost_eur": 8.81, "fossil_fuel_cost_eur": 6.9, "fossil_cost_eur": 15.71,
            "savings_eur": 5.21, "ice_l_per_100km": 6.7,
            "assumptions": {"boiler_efficiency": BOILER_EFFICIENCY, "ev_kwh_per_100km": 18, "ice_l_per_100km": 6.7},
            "demo": True}


def parse_fossil_prices_response(body):
    """Normalisiert die Antwort von fossil_prices_get (Bubble liefert {"status":"success","response":{...}}) zu
    {e10_eur_per_l, gas_ct_per_kwh, e10_updated, gas_updated} oder None."""
    if not isinstance(body, dict):
        return None
    data = body.get("response", body)
    if not isinstance(data, dict):
        return None

    def num(v):
        try:
            return float(v) if v is not None and v != "" else None
        except (TypeError, ValueError):
            return None
    out = {"e10_eur_per_l": num(data.get("e10_eur_per_l")), "gas_ct_per_kwh": num(data.get("gas_ct_per_kwh")),
           "e10_updated": data.get("e10_updated"), "gas_updated": data.get("gas_updated")}
    if out["e10_eur_per_l"] is None and out["gas_ct_per_kwh"] is None:
        return None
    return out
