"""Grundlast des Haushalts (kW bzw. kWh je Stunde) aus der Sensor-Historie - ersetzt das frühere
feste Dropdown "Grundlast (Ø Dauerleistung)". Das Ergebnis wandert als stündliche Liste "electkwh"
in die liveValues, der Server schreibt sie je Zeile in die optimizer-input.csv.

Gemessen wird am Sensor "Haushalt: Aktuelle Leistung" (photovoltaic_powerflow_load) - aber NUR in
Stunden, in denen kein steuerbares Gerät lief, sonst wäre die Grundlast verzerrt: Wallbox und
Wärmepumpe (Leistung unter OFF_THRESHOLD_KW) sowie alle 'Sonstiger Verbraucher'-Schalter
(durchgehend 'off'). Ein nicht zugeordnetes Gerät gilt als aus. Unplausible Stundenmittel
(< MIN_KW oder > MAX_KW) werden verworfen.

Ablage: je (Werktag/Wochenende, Stunde der lokalen Zeit) die letzten SAMPLES_PER_SLOT gültigen
Messwerte; das Profil ist deren Median. Weil die HA-Historie nur ~10 Tage reicht (Winter: die WP
läuft oft tagelang durch und es gibt gar keine gültige Stunde), bleibt ein älteres Profil (z.B. aus dem
Sommer) gültig, bis neue gültige Stunden einen Slot Stück für Stück überschreiben. Ohne jede
Messung gilt DEFAULT_KW.
"""

import sqlite3
import statistics
import threading
from datetime import datetime, timedelta, timezone

DB_PATH = "/data/base_load.db"

DEFAULT_KW = 0.5
MIN_KW = 0.05
MAX_KW = 3.0
OFF_THRESHOLD_KW = 0.05
SAMPLES_PER_SLOT = 8
MAX_LOOKBACK_DAYS = 9  # HA-Recorder-Standard: 10 Tage

_lock = threading.RLock()


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS base_load_samples ("
                 "hour_start_utc TEXT PRIMARY KEY, slot TEXT NOT NULL, kw REAL NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS base_load_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    return conn


def hour_key(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def slot_for(local_dt):
    "Slot-Schlüssel 'wd:<Stunde>' (Mo-Fr) bzw. 'we:<Stunde>' (Sa/So) der lokalen Zeit."
    return f"{'we' if local_dt.weekday() >= 5 else 'wd'}:{local_dt.hour}"


def step_segments(raw, start, end, parse):
    """Rohe HA-Historie (last_changed, state) als Treppenfunktion auf [start, end) zugeschnitten:
    Liste (seg_start, seg_end, parse(state)). Zustände, die parse() ablehnt (None), liefern None
    als Wert - der Aufrufer behandelt sie als 'unbekannt'."""
    segments = []
    for i, (last_changed, state) in enumerate(raw):
        seg_start = max(last_changed, start)
        seg_end = min(raw[i + 1][0] if i + 1 < len(raw) else end, end)
        if seg_end > seg_start:
            segments.append((seg_start, seg_end, parse(state)))
    return segments


def parse_float(state):
    try:
        return float(state)
    except (TypeError, ValueError):
        return None


def _overlapping(segments, hour_start, hour_end):
    return [(max(s, hour_start), min(e, hour_end), v) for s, e, v in segments if e > hour_start and s < hour_end]


def _covered_seconds(segs):
    return sum((e - s).total_seconds() for s, e, _ in segs)


def measure_hour(hour_start, load_segments, power_segments_list, switch_segments_list):
    """Mittlere Haushaltsleistung (kW) der Stunde, falls sie eine gültige Grundlast-Messung ist,
    sonst None. power_segments_list: Segmente (Wert in kW) von Wallbox/Wärmepumpe; switch_segments_list:
    Segmente (Wert 'on'/'off'/...) der 'Sonstiger Verbraucher'-Schalter. Fehlende Historie einer
    zugeordneten Quelle (Lücke in der Stunde) macht die Stunde ungültig."""
    hour_end = hour_start + timedelta(hours=1)
    load = _overlapping(load_segments, hour_start, hour_end)
    if _covered_seconds([x for x in load if x[2] is not None]) < 3590:
        return None
    mean_kw = sum((e - s).total_seconds() * v for s, e, v in load) / 3600.0
    for segments in power_segments_list:
        segs = _overlapping(segments, hour_start, hour_end)
        if _covered_seconds([x for x in segs if x[2] is not None]) < 3590:
            return None
        if any(v > OFF_THRESHOLD_KW for _, _, v in segs if v is not None):
            return None
    for segments in switch_segments_list:
        segs = _overlapping(segments, hour_start, hour_end)
        if _covered_seconds(segs) < 3590:
            return None
        if any(str(v).lower() == "on" for _, _, v in segs):
            return None
    if not (MIN_KW <= mean_kw <= MAX_KW):
        return None
    return mean_kw


def get_last_processed_hour():
    with _lock, _connect() as conn:
        row = conn.execute("SELECT value FROM base_load_meta WHERE key='last_hour'").fetchone()
    return datetime.strptime(row[0], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc) if row else None


def set_last_processed_hour(hour_start):
    with _lock, _connect() as conn:
        conn.execute("INSERT OR REPLACE INTO base_load_meta (key, value) VALUES ('last_hour', ?)", (hour_key(hour_start),))


def add_sample(hour_start, slot, kw):
    "Legt die Messung ab und hält je Slot nur die neuesten SAMPLES_PER_SLOT."
    with _lock, _connect() as conn:
        conn.execute("INSERT OR REPLACE INTO base_load_samples (hour_start_utc, slot, kw) VALUES (?,?,?)",
                     (hour_key(hour_start), slot, kw))
        conn.execute("DELETE FROM base_load_samples WHERE slot=? AND hour_start_utc NOT IN "
                     "(SELECT hour_start_utc FROM base_load_samples WHERE slot=? ORDER BY hour_start_utc DESC LIMIT ?)",
                     (slot, slot, SAMPLES_PER_SLOT))


def load_profile():
    "({slot: Median kW}, Gesamtmedian kW oder None) aus den gespeicherten Messungen."
    with _lock, _connect() as conn:
        rows = conn.execute("SELECT slot, kw FROM base_load_samples").fetchall()
    by_slot = {}
    for slot, kw in rows:
        by_slot.setdefault(slot, []).append(kw)
    profile = {slot: statistics.median(values) for slot, values in by_slot.items()}
    overall = statistics.median([kw for _, kw in rows]) if rows else None
    return profile, overall


def hourly_kwh_array(base_utc, hours, tz):
    """Grundlast (kWh je Stunde = kW) für die 'hours' Stunden ab base_utc: Median des Slots (Werktag/
    Wochenende + lokale Stunde), ersatzweise der Gesamtmedian, ersatzweise DEFAULT_KW."""
    profile, overall = load_profile()
    fallback = overall if overall is not None else DEFAULT_KW
    return [profile.get(slot_for((base_utc + timedelta(hours=i)).astimezone(tz)), fallback) for i in range(hours)]


def update_from_history(now, tz, load_raw, power_raws, switch_raws):
    """Wertet alle seit dem letzten Lauf abgeschlossenen Stunden aus (höchstens MAX_LOOKBACK_DAYS
    zurück) und legt gültige Messungen ab. load_raw/power_raws/switch_raws sind rohe HA-Historien
    (last_changed, state), die den ganzen Zeitraum ab first_hour(now) abdecken; power_raws in kW.
    Gibt die Anzahl neu abgelegter Stunden zurück."""
    end = now.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = first_hour(now)
    if start >= end:
        return 0
    load_segments = step_segments(load_raw, start, end, parse_float)
    power_segments = [step_segments(raw, start, end, parse_float) for raw in power_raws]
    switch_segments = [step_segments(raw, start, end, lambda s: s) for raw in switch_raws]
    stored = 0
    hour = start
    while hour < end:
        kw = measure_hour(hour, load_segments, power_segments, switch_segments)
        if kw is not None:
            add_sample(hour, slot_for(hour.astimezone(tz)), kw)
            stored += 1
        hour += timedelta(hours=1)
    set_last_processed_hour(end)
    return stored


def first_hour(now):
    "Erste noch auszuwertende Stunde: direkt nach dem letzten Lauf, höchstens MAX_LOOKBACK_DAYS zurück."
    end = now.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    earliest = end - timedelta(days=MAX_LOOKBACK_DAYS)
    last = get_last_processed_hour()
    return max(last, earliest) if last else earliest
