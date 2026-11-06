"""Laderegel des E-Autos: Endwert-Stufen fuer den Optimierer.

Der Optimierer bewertet den Ladestand des Autos am Ende seines Planungsfensters mit einer konkaven,
stueckweise linearen Funktion: je Ladestandsbereich ("Stufe") ein Wert in EUR je kWh Netzbezug. Geladen
wird in einem Bereich nur, wenn der Strompreis unter dem Wert dieser Stufe liegt - und zwar in den
guenstigsten Stunden des Fensters. Die Werte sind (bei dynamischem Tarif) Quantile der Brutto-Preise der
letzten 35 Tage: wie ueblich guenstig ist ein Preis im Vergleich zu dem, was in den naechsten Tagen noch
zu erwarten ist. Hintergrund und Rueckblick (Simulation ueber 2 Jahre) siehe CHANGELOG 0.0.45.352.

Reine Funktionen ohne Dateizugriff, damit sie sich testen lassen; die Anbindung (Preis-Historie,
Cache der letzten input.csv) steht in app.py (compute_ev_tiers).
"""

# Laderegel -> (Ende der Reserve-Stufe, Komfort-Ladestand, Grenze fuers Laden mit PV-Ueberschuss), jeweils Anteil an der Batterie.
EV_CHARGE_RULES = {
    "sehr günstig": (0.25, 0.50, 0.70),
    "mittel": (0.35, 0.70, 0.80),
    "Komfort": (0.45, 0.90, 0.90),
}
EV_CHARGE_RULE_DEFAULT = "mittel"

EV_HARD_RESERVE = 0.10        # Endbedingung des Optimierers (Spalte ev_soc_norm, fest) - gilt nur fuer das Ende des Planungsfensters
EV_TIER_HARD_END = 0.30       # erste Endwert-Stufe (Wert EV_TIER_VALUE_HARD): bis hierhin soll das Auto am Ende des Fensters sicher stehen

# Notladung durch das Add-on selbst (unabhaengig vom Plan): faellt der Ladestand eines eingesteckten Autos unter
# EV_RESERVE_START_SOC, laedt das Add-on sofort mit voller Leistung bis EV_RESERVE_STOP_SOC (2 % Puffer gegen den
# Standverlust, damit das Auto nicht gleich wieder unter die Schwelle faellt). Der Optimierer kennt nur Endwerte und
# wuerde die Reserve sonst in die guenstigsten Stunden des Fensters schieben.
EV_RESERVE_START_SOC = 10.0
EV_RESERVE_STOP_SOC = 12.0
EV_RESERVE_RESTART_MS = 5 * 60 * 1000   # laedt die Wallbox nicht (z. B. nach dem Ende einer Optimierer-Aktion), Start erneut senden
EV_RESERVE_CHARGING_MIN_KW = 0.5
EV_WEAR_EDGE = 0.90           # darueber nur bei sehr billigem Strom (Akkuschonung)
EV_TIER_VALUE_HARD = 0.60     # EUR/kWh unterhalb der harten Reserve (praktisch "immer")
EV_TIER_VALUE_VERY_CHEAP = 0.05  # EUR/kWh: oberste Stufe hoechstens
EV_TIER_MARGIN = 0.03         # Aufschlag auf den guenstigsten bekannten Preis, wenn die Zukunft bekannt ist (Festpreis, HT/NT)
EV_PV_BELOW_MARGIN = 0.01     # Wert oberhalb der PV-Grenze: knapp unter der Einspeiseverguetung
Q_RESERVE, Q_COMFORT, Q_SAVING, Q_TOP = 0.70, 0.20, 0.10, 0.05
HISTORY_MIN_HOURS = 14 * 24
MAX_TIERS = 6                 # Spalten ev_tier_p1..p6 / ev_tier_soc1..soc5 im Optimierer-Input


def charge_rule_from_legacy_soc_normal(value):
    """Bestandsnutzer: bisheriger 'Mindestladestand' ('10 %' ... '80 %') -> Laderegel. Fehlt oder unlesbar: Standard."""
    try:
        pct = float(str(value).replace("%", "").replace(",", ".").strip())
    except (TypeError, ValueError):
        return EV_CHARGE_RULE_DEFAULT
    if pct <= 20:
        return "sehr günstig"
    if pct <= 50:
        return "mittel"
    return "Komfort"


def charge_rule(config):
    rule = config.get("evChargeRule")
    if rule in EV_CHARGE_RULES:
        return rule
    if config.get("evSocNormal") is not None:
        return charge_rule_from_legacy_soc_normal(config.get("evSocNormal"))
    return EV_CHARGE_RULE_DEFAULT


def pv_surplus_soc_cap_percent(config):
    "Ladestand (%), bis zu dem mit PV-Ueberschuss geladen wird - dieselbe Grenze, die der Optimierer in seinen Stufen verwendet."
    return round(EV_CHARGE_RULES[charge_rule(config)][2] * 100)


def quantile(values, q):
    "Lineare Interpolation wie numpy.quantile."
    data = sorted(values)
    if not data:
        raise ValueError("keine Werte")
    pos = q * (len(data) - 1)
    lower = int(pos)
    upper = min(lower + 1, len(data) - 1)
    return data[lower] + (data[upper] - data[lower]) * (pos - lower)


def build_tiers(rule, history, upcoming_buy, pv_mode, sell_ref=None):
    """Stufen fuer den Optimierer: {"p": [6 Werte EUR/kWh], "soc": [5 Grenzen als Anteil], "basis": Text, "values": {...}} oder None.

    history: Brutto-Einkaufspreise der letzten Tage je Stunde (dynamischer Tarif) oder None/zu kurz.
    upcoming_buy: noch bevorstehende Einkaufspreise des Planungsfensters (EUR/kWh), Rueckfall und Festpreis/HT-NT.
    pv_mode: PV-Ueberschuss erwartet (Schalter aus compute_wb_p_min) - dann deckelt die Einspeiseverguetung die Stufen
    oberhalb der Reserve; sell_ref: guenstigster kommender Einspeisepreis (EUR/kWh).
    """
    reserve_end, comfort_end, pv_cap = EV_CHARGE_RULES[rule]
    if history is not None and len(history) >= HISTORY_MIN_HOURS:
        reserve = quantile(history, Q_RESERVE)
        comfort = quantile(history, Q_COMFORT)
        saving = quantile(history, Q_SAVING)
        top = min(quantile(history, Q_TOP), EV_TIER_VALUE_VERY_CHEAP)
        basis = f"Quantile der letzten {len(history) // 24} Tage"
    elif upcoming_buy:
        # Zukunft bekannt (Festpreis, HT/NT) oder noch zu wenig Historie: guenstigster bekannter Preis + Marge bis zum Komfort-Ladestand,
        # darueber nur bei sehr billigem Strom. Die Reserve-Stufe liegt ueber allen bekannten Preisen (laedt in den guenstigsten Stunden).
        comfort = min(upcoming_buy) + EV_TIER_MARGIN
        reserve = max(max(upcoming_buy) + 0.05, comfort)
        saving = top = min(EV_TIER_VALUE_VERY_CHEAP, comfort)
        basis = "bekannte Preise (guenstigster + 3 ct)"
    else:
        return None
    comfort = min(comfort, reserve)
    saving = min(saving, comfort)
    top = min(top, saving)

    # (Obergrenze, Wert) je Zone aufsteigend; PV-Grenze als zusaetzliche Kante
    zones = [(EV_TIER_HARD_END, EV_TIER_VALUE_HARD, "hart"), (reserve_end, reserve, "reserve"),
             (comfort_end, comfort, "comfort"), (EV_WEAR_EDGE, saving, "saving"), (1.0, top, "top")]
    segments = []
    lower = 0.0
    for upper, value, kind in zones:
        if upper > lower + 1e-9:
            segments.append([lower, upper, value, kind])
            lower = upper
    if pv_mode and sell_ref is not None:
        split = []
        for lo, hi, value, kind in segments:
            if kind in ("hart", "reserve"):
                split.append([lo, hi, value, kind])  # die Reserve bleibt auch bei Sonne erhalten
            elif hi <= pv_cap + 1e-9:
                split.append([lo, hi, min(value, sell_ref + EV_TIER_MARGIN), kind])
            elif lo >= pv_cap - 1e-9:
                split.append([lo, hi, min(value, sell_ref - EV_PV_BELOW_MARGIN), kind])
            else:
                split.append([lo, pv_cap, min(value, sell_ref + EV_TIER_MARGIN), kind])
                split.append([pv_cap, hi, min(value, sell_ref - EV_PV_BELOW_MARGIN), kind])
        segments = split
    # nicht steigend (konkav) und gleiche Nachbarn zusammenfassen
    merged = []
    previous = None
    for lo, hi, value, kind in segments:
        value = value if previous is None else min(value, previous)
        previous = value
        if merged and abs(merged[-1][2] - value) < 1e-9:
            merged[-1][1] = hi
        else:
            merged.append([lo, hi, value])
    if len(merged) > MAX_TIERS:
        return None
    p = [round(v, 4) for _, _, v in merged]
    soc = [round(hi, 4) for _, hi, _ in merged[:-1]]
    while len(p) < MAX_TIERS:
        p.append(p[-1])
        soc.append(1.0)
    return {"p": p, "soc": soc, "basis": basis + (" / PV-Überschuss" if pv_mode and sell_ref is not None else ""),
            "values": {"reserve": reserve, "comfort": comfort, "saving": saving, "top": top}}


def reserve_charge_decision(active, car_ready, ev_soc, other_active, live_kw, now_ms, last_command_ms):
    """Notladung bis EV_RESERVE_STOP_SOC (siehe oben). Rueckgabe: "start" (neu starten), "restart" (Start erneut senden,
    Wallbox laedt nicht), "stop" (Ziel erreicht, Wallbox stoppen), "end" (Notladung ohne Stopp-Befehl beenden: Auto
    abgesteckt oder eine andere Ladung - Optimierer-Aktion/PV-Ueberschuss - steuert die Wallbox und laedt ohnehin weiter)
    oder None (nichts tun). other_active: eine Optimierer-'Auto laden'-Aktion oder PV-Ueberschuss-Session laeuft gerade."""
    if not active:
        if car_ready and ev_soc is not None and ev_soc < EV_RESERVE_START_SOC and not other_active:
            return "start"
        return None
    if not car_ready:
        return "end"
    if ev_soc is not None and ev_soc >= EV_RESERVE_STOP_SOC:
        return "end" if other_active else "stop"
    if other_active:
        return None  # die andere Ladung laeuft; endet sie vor 12 %, startet der naechste Tick neu
    charging = live_kw is not None and live_kw >= EV_RESERVE_CHARGING_MIN_KW
    if not charging and (last_command_ms is None or now_ms - last_command_ms >= EV_RESERVE_RESTART_MS):
        return "restart"
    return None
