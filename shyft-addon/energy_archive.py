"""Persistentes Stunden-Archiv fuer den Analyse-Tab (siehe app.py) - haelt je abgeschlossener
Stunde Verbrauch/Kosten fuer geplant-optimal, Basisfall und tatsaechlich, plus eine komprimierte
Liste erfolgreich ausgefuehrter Aktionen. Anders als die uebrigen /data/*.json-Dateien (komplett
eingelesen/neu geschrieben, siehe problem_registry.py) SQLite, weil das ueber Monate/Jahre
stuendlicher Daten nicht mehr sinnvoll skaliert.

Ablauf je Stunde:
  1. record_plan_contribution() bei JEDEM frischen Optimierungslauf (siehe app._write_dashboard_cache)
     mit Zeile 0 von output_csv/input_csv - "geplant"/"Basisfall" fuer die GERADE LAUFENDE Stunde.
     Landen mehrere Laeufe in derselben Stunde (Nutzer-Vorgabe), wird zeitanteilig gemittelt: jeder
     Lauf zaehlt fuer die Zeitspanne, die er tatsaechlich "der aktuelle Plan" war (siehe
     hour_plan_state/_close_open_segment).
  2. finalize_hour() kurz nach Stundenwechsel (siehe app.finalize_completed_hour_periodically) fuer
     die GERADE ABGELAUFENE Stunde: schliesst den letzten offenen Planungs-Abschnitt, bildet daraus
     den zeitgewichteten Mittelwert, verrechnet den tatsaechlichen Netzbezug/die Einspeisung mit dem
     zuletzt bekannten Strompreis dieser Stunde und schreibt das Ergebnis nach hourly_archive.

Absichtlich noch KEINE Mehrfach-Horizont-Nachverfolgung (Nutzer-Wunsch: "spaeter, jetzt noch
nicht" - geplanter Verbrauch in 12/24/36/48h Vorlauf gegen das spaetere IST, um zu zeigen, dass die
Planung mit zunehmendem Horizont schlechter wird). Dafuer waere eine eigene Tabelle
("plan_horizon_snapshots", Spalten hour_start_utc/horizon_hours/usage_kwh/cost_eur) vorgesehen -
unabhaengig von hourly_archive befuellbar und ueber hour_start_utc dagegen joinbar, ohne dieses
Schema zu aendern.
"""

import sqlite3
import threading
from datetime import datetime, timezone, timedelta

DB_PATH = "/data/energy_archive.db"

_lock = threading.RLock()


def hour_key(dt):
    "Kanonischer Primaerschluessel-String fuer eine volle Stunde (UTC, ohne Offset-Suffix) - laesst SQLite beim Aggregieren (query_summary) direkt mit strftime/date() darauf arbeiten."
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS hour_plan_state (
            hour_start_utc TEXT PRIMARY KEY,
            segment_start_at TEXT NOT NULL,
            planned_usage_kwh REAL,
            planned_cost_eur REAL,
            base_usage_kwh REAL,
            base_cost_eur REAL,
            price_buy_eur_per_kwh REAL,
            price_sell_eur_per_kwh REAL,
            acc_weight_seconds REAL NOT NULL DEFAULT 0,
            acc_planned_usage_ws REAL NOT NULL DEFAULT 0,
            acc_planned_cost_ws REAL NOT NULL DEFAULT 0,
            acc_base_usage_ws REAL NOT NULL DEFAULT 0,
            acc_base_cost_ws REAL NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS hourly_archive (
            hour_start_utc TEXT PRIMARY KEY,
            planned_usage_kwh REAL,
            planned_cost_eur REAL,
            base_usage_kwh REAL,
            base_cost_eur REAL,
            actual_usage_kwh REAL,
            actual_import_kwh REAL,
            actual_export_kwh REAL,
            actual_cost_eur REAL,
            savings_vs_base_eur REAL,
            savings_vs_planned_eur REAL,
            recorded_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS completed_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_type TEXT NOT NULL,
            savings_eur REAL,
            power_kw REAL,
            date_start_ms INTEGER NOT NULL,
            date_end_ms INTEGER,
            recorded_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_completed_actions_date_start ON completed_actions(date_start_ms)")
    # "Ersparnis Haushaltsstrom" (siehe app._household_savings_action) ist anders als die uebrigen
    # Aktionstypen kein diskretes Start/Ende-Ereignis, sondern eine bei jedem frischen
    # Optimierungslauf frisch berechnete Tages-Momentaufnahme - je Kalendertag EINE Zeile, die per
    # Upsert immer wieder ueberschrieben wird (record_household_savings_snapshot), bis der Tag
    # vorbei ist und die naechste Momentaufnahme unter einem neuen Datum landet. Dadurch haelt der
    # letzte Aufruf vor Mitternacht automatisch den finalen Tageswert fest, ohne eigene
    # Tageswechsel-Erkennung.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS household_savings_daily (
            date TEXT PRIMARY KEY,
            costsbase_eur REAL,
            costsopt_eur REAL,
            savings_eur REAL,
            updated_at TEXT NOT NULL
        )
    """)


def _accumulate_open_segment(row, at):
    "Gewichtet den in 'row' (hour_plan_state) offenen Abschnitt bis 'at' nach - gemeinsame Rechnung fuer record_plan_contribution (neuer Lauf loest den bisherigen ab) und finalize_hour (Stundenende schliesst den letzten Lauf)."
    segment_start = datetime.fromisoformat(row["segment_start_at"])
    weight = max(0.0, (at - segment_start).total_seconds())
    return (
        row["acc_weight_seconds"] + weight,
        row["acc_planned_usage_ws"] + weight * (row["planned_usage_kwh"] or 0.0),
        row["acc_planned_cost_ws"] + weight * (row["planned_cost_eur"] or 0.0),
        row["acc_base_usage_ws"] + weight * (row["base_usage_kwh"] or 0.0),
        row["acc_base_cost_ws"] + weight * (row["base_cost_eur"] or 0.0),
    )


def record_plan_contribution(hour_start_utc, planned_usage_kwh, planned_cost_eur, base_usage_kwh, base_cost_eur, price_buy=None, price_sell=None, at=None):
    """Neuer Optimierungslauf: schliesst einen evtl. bereits offenen Abschnitt fuer diese Stunde
    zeitanteilig ab und eroeffnet einen neuen mit den frischen Werten (Zeile 0 von output_csv/
    input_csv). price_buy/price_sell werden NICHT zeitgewichtet, sondern einfach vom jeweils
    letzten Lauf uebernommen - das ist ein Marktpreis, keine Planungsguete-Groesse."""
    at = at or datetime.now(timezone.utc)
    with _lock, _connect() as conn:
        _ensure_schema(conn)
        row = conn.execute("SELECT * FROM hour_plan_state WHERE hour_start_utc = ?", (hour_start_utc,)).fetchone()
        if row is not None:
            acc_weight, acc_pu, acc_pc, acc_bu, acc_bc = _accumulate_open_segment(row, at)
        else:
            acc_weight = acc_pu = acc_pc = acc_bu = acc_bc = 0.0
        conn.execute("""
            INSERT INTO hour_plan_state (hour_start_utc, segment_start_at, planned_usage_kwh, planned_cost_eur,
                base_usage_kwh, base_cost_eur, price_buy_eur_per_kwh, price_sell_eur_per_kwh,
                acc_weight_seconds, acc_planned_usage_ws, acc_planned_cost_ws, acc_base_usage_ws, acc_base_cost_ws)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(hour_start_utc) DO UPDATE SET
                segment_start_at=excluded.segment_start_at,
                planned_usage_kwh=excluded.planned_usage_kwh, planned_cost_eur=excluded.planned_cost_eur,
                base_usage_kwh=excluded.base_usage_kwh, base_cost_eur=excluded.base_cost_eur,
                price_buy_eur_per_kwh=excluded.price_buy_eur_per_kwh, price_sell_eur_per_kwh=excluded.price_sell_eur_per_kwh,
                acc_weight_seconds=excluded.acc_weight_seconds,
                acc_planned_usage_ws=excluded.acc_planned_usage_ws, acc_planned_cost_ws=excluded.acc_planned_cost_ws,
                acc_base_usage_ws=excluded.acc_base_usage_ws, acc_base_cost_ws=excluded.acc_base_cost_ws
        """, (hour_start_utc, at.isoformat(), planned_usage_kwh, planned_cost_eur, base_usage_kwh, base_cost_eur,
              price_buy, price_sell, acc_weight, acc_pu, acc_pc, acc_bu, acc_bc))
        conn.commit()


def finalize_hour(hour_start_utc, hour_end_at, actual_import_kwh, actual_export_kwh):
    """Schliesst eine abgelaufene Stunde ab: gewichtet den zuletzt offenen Planungs-Abschnitt bis
    hour_end_at nach, bildet geplant/Basisfall als zeitgewichteten Mittelwert ueber ALLE Laeufe
    dieser Stunde, verrechnet actual_import_kwh/actual_export_kwh mit dem zuletzt bekannten
    Strompreis dieser Stunde und schreibt das Ergebnis nach hourly_archive.

    Gibt False zurueck (und schreibt nichts), wenn fuer diese Stunde nie ein Optimierungslauf
    aufgezeichnet wurde (z.B. Demo-Modus, oder das Feature war zu Stundenbeginn noch nicht aktiv) -
    ohne geplant/Basisfall waere die Zeile ohnehin nur eine IST-Zahl ohne Vergleichswert."""
    with _lock, _connect() as conn:
        _ensure_schema(conn)
        row = conn.execute("SELECT * FROM hour_plan_state WHERE hour_start_utc = ?", (hour_start_utc,)).fetchone()
        if row is None:
            return False
        acc_weight, acc_pu, acc_pc, acc_bu, acc_bc = _accumulate_open_segment(row, hour_end_at)
        if acc_weight > 0:
            planned_usage, planned_cost = acc_pu / acc_weight, acc_pc / acc_weight
            base_usage, base_cost = acc_bu / acc_weight, acc_bc / acc_weight
        else:
            planned_usage, planned_cost = row["planned_usage_kwh"], row["planned_cost_eur"]
            base_usage, base_cost = row["base_usage_kwh"], row["base_cost_eur"]

        price_buy = row["price_buy_eur_per_kwh"] or 0.0
        price_sell = row["price_sell_eur_per_kwh"] or 0.0
        actual_import_kwh = actual_import_kwh or 0.0
        actual_export_kwh = actual_export_kwh or 0.0
        actual_usage = actual_import_kwh - actual_export_kwh  # netto, wie GR_sum im Optimierer
        actual_cost = actual_import_kwh * price_buy - actual_export_kwh * price_sell

        savings_vs_base = None if base_cost is None else base_cost - actual_cost
        savings_vs_planned = None if planned_cost is None else planned_cost - actual_cost

        conn.execute("""
            INSERT INTO hourly_archive (hour_start_utc, planned_usage_kwh, planned_cost_eur, base_usage_kwh,
                base_cost_eur, actual_usage_kwh, actual_import_kwh, actual_export_kwh, actual_cost_eur,
                savings_vs_base_eur, savings_vs_planned_eur, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(hour_start_utc) DO UPDATE SET
                planned_usage_kwh=excluded.planned_usage_kwh, planned_cost_eur=excluded.planned_cost_eur,
                base_usage_kwh=excluded.base_usage_kwh, base_cost_eur=excluded.base_cost_eur,
                actual_usage_kwh=excluded.actual_usage_kwh, actual_import_kwh=excluded.actual_import_kwh,
                actual_export_kwh=excluded.actual_export_kwh, actual_cost_eur=excluded.actual_cost_eur,
                savings_vs_base_eur=excluded.savings_vs_base_eur, savings_vs_planned_eur=excluded.savings_vs_planned_eur,
                recorded_at=excluded.recorded_at
        """, (hour_start_utc, planned_usage, planned_cost, base_usage, base_cost, actual_usage,
              actual_import_kwh, actual_export_kwh, actual_cost, savings_vs_base, savings_vs_planned,
              datetime.now(timezone.utc).isoformat()))
        conn.execute("DELETE FROM hour_plan_state WHERE hour_start_utc = ?", (hour_start_utc,))
        conn.commit()
        return True


def archive_completed_action(action):
    "Haengt eine kompakte Zeile (Aktionstyp, Ersparnis, Leistung, Datum von-bis) an completed_actions an - nur fuer tatsaechlich erfolgreich ausgefuehrte Aktionen, siehe Aufrufer (run_hourly_action_transition/stop_pv_surplus_charging in app.py). No-op ohne 'Action Name' oder 'Date Start' (unvollstaendige Aktion)."
    action_type = action.get("Action Name")
    date_start_ms = action.get("Date Start")
    if not action_type or not date_start_ms:
        return
    with _lock, _connect() as conn:
        _ensure_schema(conn)
        conn.execute("""
            INSERT INTO completed_actions (action_type, savings_eur, power_kw, date_start_ms, date_end_ms, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (action_type, action.get("Savings"), action.get("Target Value"), date_start_ms,
              action.get("Date End"), datetime.now(timezone.utc).isoformat()))
        conn.commit()


# Gruppierungs-Ausdruck je Granularitaet - hourly_archive.hour_start_utc ist ueber hour_key() immer
# UTC ohne Offset-Suffix, damit SQLites date()/strftime() direkt darauf arbeiten koennen.
# "weekly" gruppiert auf den Montag der jeweiligen Woche (ISO-aehnlich, ohne Jahresgrenzen-Sonderfaelle).
_GROUP_EXPR_BY_GRANULARITY = {
    "hourly": "hour_start_utc",
    "daily": "date(hour_start_utc)",
    "weekly": "date(hour_start_utc, 'weekday 0', '-6 days')",
    "monthly": "strftime('%Y-%m', hour_start_utc)",
    "yearly": "strftime('%Y', hour_start_utc)",
}


def query_summary(granularity, start_iso=None, end_iso=None):
    "Je Periode (siehe _GROUP_EXPR_BY_GRANULARITY) aufsummierte Verbrauchs-/Kosten-/Ersparnis-Werte, neuestes zuerst (Nutzer-Vorgabe). start_iso/end_iso (siehe hour_key) grenzen optional auf hour_start_utc >= start_iso bzw. < end_iso ein."
    group_expr = _GROUP_EXPR_BY_GRANULARITY.get(granularity, _GROUP_EXPR_BY_GRANULARITY["daily"])
    where, params = [], []
    if start_iso:
        where.append("hour_start_utc >= ?")
        params.append(start_iso)
    if end_iso:
        where.append("hour_start_utc < ?")
        params.append(end_iso)
    where_clause = ("WHERE " + " AND ".join(where)) if where else ""
    with _lock, _connect() as conn:
        _ensure_schema(conn)
        rows = conn.execute(f"""
            SELECT {group_expr} AS period,
                   SUM(planned_usage_kwh) AS planned_usage_kwh, SUM(planned_cost_eur) AS planned_cost_eur,
                   SUM(base_usage_kwh) AS base_usage_kwh, SUM(base_cost_eur) AS base_cost_eur,
                   SUM(actual_usage_kwh) AS actual_usage_kwh, SUM(actual_cost_eur) AS actual_cost_eur,
                   SUM(savings_vs_base_eur) AS savings_vs_base_eur, SUM(savings_vs_planned_eur) AS savings_vs_planned_eur,
                   COUNT(*) AS hours_recorded
            FROM hourly_archive
            {where_clause}
            GROUP BY period
            ORDER BY period DESC
        """, params).fetchall()
        return [dict(r) for r in rows]


def query_day_actions(date_str):
    "Kompakte Liste erfolgreich ausgefuehrter Aktionen fuer einen Kalendertag (lokale Addon-Zeitzone, wie ueberall sonst im Addon, siehe _local_day_offset in app.py). date_str im Format YYYY-MM-DD. Haengt am Ende die archivierte 'Ersparnis Haushaltsstrom'-Tageszeile (siehe household_savings_daily) an, falls fuer diesen Tag vorhanden - dieselbe Zeilenform wie completed_actions, damit das Frontend sie identisch behandeln kann."
    day_start_local = datetime.strptime(date_str, "%Y-%m-%d").astimezone()
    day_end_local = day_start_local + timedelta(days=1)
    start_ms = int(day_start_local.timestamp() * 1000)
    end_ms = int(day_end_local.timestamp() * 1000)
    with _lock, _connect() as conn:
        _ensure_schema(conn)
        rows = conn.execute("""
            SELECT action_type, savings_eur, power_kw, date_start_ms, date_end_ms
            FROM completed_actions
            WHERE date_start_ms >= ? AND date_start_ms < ?
            ORDER BY date_start_ms
        """, (start_ms, end_ms)).fetchall()
        result = [dict(r) for r in rows]
    household = query_household_savings_for_day(date_str)
    if household:
        result.append({
            "action_type": "Ersparnis Haushaltsstrom",
            "savings_eur": household["savings_eur"],
            "power_kw": None,
            "date_start_ms": start_ms,
            "date_end_ms": end_ms,
        })
    return result


def record_household_savings_snapshot(date_str, costsbase, costsopt, savings):
    "Schreibt/aktualisiert die tagesaktuelle 'Ersparnis Haushaltsstrom'-Momentaufnahme (siehe app._household_savings_action) unter ihrem lokalen Kalendertag - wird bei JEDEM frischen Optimierungslauf neu aufgerufen (siehe app._write_dashboard_cache), aehnlich record_plan_contribution. Der letzte Aufruf vor Mitternacht haelt so automatisch den finalen Tageswert fest, danach landet die naechste Momentaufnahme unter einem neuen Datum und laesst diese Zeile unveraendert stehen."
    with _lock, _connect() as conn:
        _ensure_schema(conn)
        conn.execute("""
            INSERT INTO household_savings_daily (date, costsbase_eur, costsopt_eur, savings_eur, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                costsbase_eur=excluded.costsbase_eur, costsopt_eur=excluded.costsopt_eur,
                savings_eur=excluded.savings_eur, updated_at=excluded.updated_at
        """, (date_str, costsbase, costsopt, savings, datetime.now(timezone.utc).isoformat()))
        conn.commit()


def query_household_savings_for_day(date_str):
    "Archivierter 'Ersparnis Haushaltsstrom'-Tageswert (oder None) fuer genau diesen Kalendertag - fuer die Tages-Detailansicht im Analyse-Tab (query_day_actions)."
    with _lock, _connect() as conn:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT date, costsbase_eur, costsopt_eur, savings_eur FROM household_savings_daily WHERE date = ?",
            (date_str,)).fetchone()
        return dict(row) if row else None


def query_household_savings_since(cutoff_date_str):
    "Archivierte 'Ersparnis Haushaltsstrom'-Tageswerte ab (einschliesslich) cutoff_date_str, neuestes zuerst - Basis fuer die Gerätesteuerung-Historie (siehe app._historical_household_savings_actions)."
    with _lock, _connect() as conn:
        _ensure_schema(conn)
        rows = conn.execute("""
            SELECT date, costsbase_eur, costsopt_eur, savings_eur
            FROM household_savings_daily
            WHERE date >= ?
            ORDER BY date DESC
        """, (cutoff_date_str,)).fetchall()
        return [dict(r) for r in rows]
