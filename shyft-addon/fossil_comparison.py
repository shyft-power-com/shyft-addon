"""Vergleich "tatsaechliche Kosten vs. fossiler Haushalt" (Kachel im Dashboard).

Reine Rechenlogik ohne HA-/Netzzugriff. Der fossile Vergleichshaushalt ersetzt Waermepumpe und E-Auto durch Gaskessel und Benziner (E10):

    Ersparnis = fossile Kosten (Gas + Benzin) - Stromkosten von Waermepumpe + Wallbox

Alle Annahmen sind unten als Konstanten benannt und werden mit dem Ergebnis ausgeliefert, damit die UI sie anzeigen kann. Es sind
Naeherungswerte - das Archiv kennt keine Einzelverbraucher-Kosten, daher wird der durchschnittliche Netzbezugspreis des Zeitraums verwendet.
"""

HEATPUMP_COP = 3.5            # Jahresarbeitszahl der Waermepumpe (Waerme / Strom)
BOILER_EFFICIENCY = 0.92      # Nutzungsgrad Gas-Brennwertkessel
EV_KWH_PER_100KM = 18.0       # Verbrauch des E-Autos ab Wallbox
ICE_L_PER_100KM = 7.5         # Verbrauch des vergleichbaren Benziners (E10)
DEFAULT_DAYS = 30

ASSUMPTIONS = {
    "heatpump_cop": HEATPUMP_COP,
    "boiler_efficiency": BOILER_EFFICIENCY,
    "ev_kwh_per_100km": EV_KWH_PER_100KM,
    "ice_l_per_100km": ICE_L_PER_100KM,
}


def compute_fossil_savings(heatpump_kwh, wallbox_kwh, avg_power_price_eur_kwh, e10_eur_per_l, gas_ct_per_kwh):
    """Gibt ein dict mit Kosten/Ersparnis (EUR) fuer den Zeitraum zurueck oder None, wenn weder Waermepumpe noch Wallbox Daten haben
    bzw. der noetige Preis fehlt. Fehlt nur eine Seite (z.B. kein E-Auto), wird sie als 0 gerechnet."""
    heat = max(heatpump_kwh, 0.0) if heatpump_kwh is not None else None
    car = max(wallbox_kwh, 0.0) if wallbox_kwh is not None else None
    if heat is None and car is None:
        return None
    if avg_power_price_eur_kwh is None:
        return None
    heat_kwh = heat or 0.0
    car_kwh = car or 0.0
    if heat_kwh > 0 and gas_ct_per_kwh is None:
        return None
    if car_kwh > 0 and e10_eur_per_l is None:
        return None
    gas_cost = heat_kwh * HEATPUMP_COP / BOILER_EFFICIENCY * (gas_ct_per_kwh or 0.0) / 100.0
    km = car_kwh / EV_KWH_PER_100KM * 100.0
    fuel_cost = km * ICE_L_PER_100KM / 100.0 * (e10_eur_per_l or 0.0)
    electric_cost = (heat_kwh + car_kwh) * avg_power_price_eur_kwh
    fossil_cost = gas_cost + fuel_cost
    return {
        "heatpump_kwh": round(heat_kwh, 1),
        "wallbox_kwh": round(car_kwh, 1),
        "electric_cost_eur": round(electric_cost, 2),
        "fossil_gas_cost_eur": round(gas_cost, 2),
        "fossil_fuel_cost_eur": round(fuel_cost, 2),
        "fossil_cost_eur": round(fossil_cost, 2),
        "savings_eur": round(fossil_cost - electric_cost, 2),
        "km": round(km),
        "assumptions": dict(ASSUMPTIONS),
    }


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
