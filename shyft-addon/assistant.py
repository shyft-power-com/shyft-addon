"""Hilfe-Assistent (KI-Chat): baut den Prompt fuer Home Assistants ai_task.generate_data und liest
die Antwort aus. Rein funktional/ohne eigene HA-Aufrufe (die macht app.py), damit sich der
Prompt-Aufbau ohne laufendes Home Assistant testen laesst.

Kontext, den die KI bekommt (sie kennt shyft-power nicht und kann keine Webseiten abrufen):
1. eine feste Wissensbasis (Was ist shyft-power, Begriffe, Bedienung, typische Fehlerbilder),
2. die Feldbeschreibungen der Oberflaeche (uiHelp, aus den Tooltips des Frontends),
3. die aktuelle Konfiguration (ohne Zugangsdaten), aktive Probleme und die Live-Werte der
   zugeordneten Sensoren,
4. eine kompakte Kandidatenliste der HA-Entitaeten (fuer Fragen wie "welchen Sensor nehme ich?"),
5. ein Auszug der Fehler-/Warnzeilen aus dem Add-on-Log (zugangsdatenfrei, siehe extract_error_lines),
6. die letzten Frage/Antwort-Paare (ai_task.generate_data ist Einzelaufruf, kein Chat-Verlauf)."""
import json
import re
from datetime import datetime, timedelta

AI_TASK_DOMAIN = "ai_task"

MAX_QUESTION_CHARS = 1500
MAX_HISTORY_TURNS = 3
MAX_HISTORY_ANSWER_CHARS = 1200
MAX_UI_HELP_CHARS = 16000
MAX_CONFIG_CHARS = 9000
MAX_PROBLEMS = 20
MAX_MAPPED_STATES = 80
MAX_CANDIDATE_ENTITIES = 350

# Konfigurationsschluessel, die nie an die KI gehen (Zugangsdaten/persoenliche Ziele).
CONFIG_KEY_BLACKLIST = ("token", "key", "password", "secret", "notification")

KNOWLEDGE = """\
Du bist der Hilfe-Assistent des Home-Assistant-Add-ons "shyft-power" (Hersteller: shyft-power.com).
Antworte auf Deutsch, kurz und konkret (idealerweise unter 200 Woertern), mit nummerierten Schritten, wenn
etwas einzustellen ist. Nenne Bereiche und Felder genau so, wie sie in der Oberflaeche heissen. Erfinde keine
Felder, Menues oder Funktionen; wenn du etwas nicht sicher aus dem Kontext ableiten kannst, sag das offen.
Nutze die mitgelieferten Konfigurationsdaten, Probleme und Sensorwerte, um die Antwort auf die Situation des
Nutzers zuzuschneiden (z.B. "dein Sensor X liefert gerade 'unavailable'").

Was shyft-power macht:
- Ein Home-Energy-Management-System. Ein Optimierer (in der shyft-power-Cloud) berechnet stuendlich, wann
  Batterie, Waermepumpe (Heizung/Warmwasser), Auto (Wallbox) und ein "Sonstiger Verbraucher" laufen sollen,
  um Stromkosten zu senken (dynamischer/Hoch-Niedertarif, PV-Prognose, Anwesenheitsprognose des Autos).
- Das Add-on liest Sensoren aus Home Assistant (Konfiguration -> Geraetekacheln), schickt sie an die Cloud und
  fuehrt die zurueckgelieferten Aktionen aus (Gerätesteuerung-Tab). Aktionen sind z.B. "Auto laden",
  "Warmwasser", "Heizung Soll-Temperatur", "Batterie ...", "Verbraucher an".
- Tabs: Dashboard (Charts, Energiefluss), Gerätesteuerung (geplante/aktive/beendete Aktionen inkl. Log),
  Analyse (nur Testumgebung), Konfiguration.

Konfiguration:
- "Strom": Tarif (Fixer Tarif, Hoch-/Niedertarif, Dynamischer Tarif), Einspeisevergütung und optional
  "Netz: Aktuelle Leistung" (mehrere Sensoren moeglich, z.B. getrennte Sensoren fuer Bezug und Einspeisung:
  unter den Sensoren, die gerade aktuell melden - Aktualisierung hoechstens 1 Minute hinter dem aktuellsten -,
  gewinnt der mit dem groessten Betrag; ein zu traeger Sensor, etwa der des Wechselrichters, zaehlt dann nicht
  mit. Ein Sensor, dessen Name "Einspeise" enthaelt, wird automatisch mit umgekehrtem Vorzeichen behandelt).
- Geraetekacheln: Wechselrichter, Batterie, Waermepumpe, Auto, Wallbox, Raumtemperatur, Sonstiger Verbraucher.
  Pro Kachel waehlt man die Home-Assistant-Integration/das Geraet und ordnet dann Sensoren zu.
- Steuerung pro Aktionstyp: "Direkt steuern" (das Add-on schreibt die Entitaet selbst, ueber ein automatisch
  angelegtes Skript) oder "HA-Automation" (das Add-on loest eine eigene Automation des Nutzers aus).
- Jeder Steuerungsweg hat einen Testen-Button; erst nach erfolgreichem Test wird der Aktionstyp ausgefuehrt.
  Cloud-Waermepumpen (z.B. Viessmann/ViCare) melden geschriebene Werte oft erst nach 1-3 Minuten zurueck, der
  Test wartet entsprechend lange.
- Benachrichtigungen (Handy) fuer Aktionen bzw. nur Fehler sind einstellbar.

Haeufige Fehlerbilder:
- Aktionskarte rot / "Fehler beim Starten": das HA-Skript oder die Automation ist fehlgeschlagen; die genaue
  Ursache steht im Log der Karte (aufklappbar). Haeufig: Zielwert ausserhalb des erlaubten Bereichs der
  Entitaet (das Add-on begrenzt auf min/max der Entitaet), Geraet offline, falsche Entitaet zugeordnet.
- Sensor "unavailable"/veraltet: Integration in Home Assistant pruefen; solange rechnet shyft-power mit
  unvollstaendigen Daten.
- "Diagrammdaten konnten nicht geladen werden": kurzzeitig, Seite neu laden; bei Dauer Add-on-Log pruefen.
- Neue Version nicht sichtbar: Seite hart neu laden (Strg+F5) bzw. Panel/App neu oeffnen.

Add-on-Log: Du bekommst unten einen Auszug der Fehler- und Warnzeilen aus dem Add-on-Log (nicht das komplette
Log; Zeilen tragen das Praefix "[Shyft]"). Nutze ihn, um Ursachen zu erklaeren, und zitiere nur die relevanten
Zeilen. Steht dort nichts Passendes, sag das offen, statt eine Ursache zu raten.

Support-Angebot: Geht es um ein Integrationsproblem oder einen Fehler, den du mit den vorliegenden Angaben nicht
sicher loesen kannst (z.B. ein Sensor oder Geraet liefert dauerhaft keine Werte, eine Steuerung schlaegt auch nach
den beschriebenen Schritten weiter fehl, das Log zeigt einen unklaren Fehler), haenge als LETZTE Zeile deiner Antwort
genau einmal die Markierung [[SUPPORT_ANGEBOT: <ein bis zwei Saetze auf Deutsch: was ist das Problem, welches
Geraet/welche Integration, welche Fehlermeldung>]] an. Die Oberflaeche zeigt dem Nutzer daraufhin ein Formular, mit
dem er Log und Problembeschreibung an das Shyft-Team senden kann. Erwaehne die Markierung nicht im Text und biete das
Senden nicht selbst an. Lass sie bei reinen Bedienfragen, bei bereits geloesten Problemen und dann weg, wenn dir
mitgeteilt wird, dass das Angebot schon gemacht wurde.

Grenzen: Du kannst nichts am System aendern, nur erklaeren und anleiten. Bei Fragen an das Shyft-Team
verweise auf info@shyft-power.com. Verweise nicht auf GitHub oder den Quellcode.
"""


def _is_sensitive_key(key):
    lowered = str(key).lower()
    return any(part in lowered for part in CONFIG_KEY_BLACKLIST)


def summarize_config(config):
    """Kompakte, zugangsdatenfreie Sicht auf die Konfiguration: alle Top-Level-Eintraege (Skalare und
    Dicts/Listen) ausser sensiblen Schluesseln, als JSON, hart gekappt."""
    summary = {}
    for key, value in (config or {}).items():
        if _is_sensitive_key(key):
            continue
        if isinstance(value, dict):
            value = {k: v for k, v in value.items() if not _is_sensitive_key(k)}
        summary[key] = value
    text = json.dumps(summary, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(text) > MAX_CONFIG_CHARS:
        text = text[:MAX_CONFIG_CHARS] + " ...(gekuerzt)"
    return text


def _entity_ids_of_sensor_mappings(config):
    ids = []
    for value in ((config or {}).get("sensorMappings") or {}).values():
        if isinstance(value, list):
            ids.extend(v for v in value if v)
        elif value:
            ids.append(value)
    return list(dict.fromkeys(ids))


def _state_line(state):
    attributes = state.get("attributes") or {}
    unit = attributes.get("unit_of_measurement") or ""
    value = f"{state.get('state')} {unit}".strip()
    name = attributes.get("friendly_name") or ""
    return f"{state['entity_id']} | {name} | {value}"


def mapped_sensor_lines(config, states_by_id):
    lines = []
    for entity_id in _entity_ids_of_sensor_mappings(config)[:MAX_MAPPED_STATES]:
        state = states_by_id.get(entity_id)
        lines.append(_state_line(state) if state else f"{entity_id} | (in Home Assistant nicht gefunden)")
    return lines


CANDIDATE_DOMAINS = ("sensor", "binary_sensor", "number", "switch", "select", "climate", "input_number", "input_boolean")
CANDIDATE_UNITS = ("W", "kW", "kWh", "Wh", "°C", "%", "A", "V")
CANDIDATE_DEVICE_CLASSES = ("power", "energy", "battery", "temperature", "current", "voltage", "plug", "running")


def candidate_entity_lines(states):
    """Kompakte Liste plausibler Steuer-/Messentitaeten (Domaene + Einheit/Device-Class-Filter), nicht
    alle Entitaeten der Instanz - haelt den Prompt klein und teilt nichts Unnoetiges."""
    lines = []
    for state in states:
        entity_id = state.get("entity_id", "")
        if entity_id.split(".")[0] not in CANDIDATE_DOMAINS:
            continue
        attributes = state.get("attributes") or {}
        domain = entity_id.split(".")[0]
        relevant = (
            domain in ("number", "switch", "select", "climate", "input_number", "input_boolean")
            or attributes.get("unit_of_measurement") in CANDIDATE_UNITS
            or attributes.get("device_class") in CANDIDATE_DEVICE_CLASSES
        )
        if relevant:
            lines.append(_state_line(state))
        if len(lines) >= MAX_CANDIDATE_ENTITIES:
            break
    return lines


# --- Log-Auszug --------------------------------------------------------------------------------
# Nicht das ganze Add-on-Log (sehr gross, mit detailed_logging zehntausende Zeilen), sondern nur
# Fehler-/Warnzeilen, dedupliziert und hart gekappt; Zugangsdaten werden vor dem Versand geschwaerzt.
MAX_LOG_SOURCE_LINES = 2000
MAX_LOG_EXCERPT_ENTRIES = 40
MAX_LOG_LINE_CHARS = 400
MAX_LOG_EXCERPT_CHARS = 8000
MAX_TRACEBACK_LINES = 14

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
# Zeitstempel am Zeilenanfang (Supervisor-Format text/x-log) - fuers Zusammenfassen gleicher Zeilen ignoriert.
_LEADING_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\s+")
_ERROR_LINE_RE = re.compile(
    r"fehl|failed|error|exception|traceback|konnte nicht|nicht geladen|besch[aä]digt|unerwartet|warn|teurer als"
    r"|invalid|not found|nicht gefunden"
    r"|timeout|zeitueberschreitung|HTTP/\d(?:\.\d)?\"\s+5\d\d",
    re.IGNORECASE)
_EXCEPTION_LINE_RE = re.compile(r"^[\w.]+(?:Error|Exception|Exit|Interrupt|Warning)\b(?::.*)?$")
_SECRET_ASSIGNMENT_RE =re.compile(
    r"(?i)(token|api[_-]?key|access[_-]?key|password|passwort|secret|authorization)([\"']?\s*[:=]\s*[\"']?)[^\s,\"'}\]]+")
_BEARER_RE = re.compile(r"(?i)(bearer\s+)\S+")
MIN_SECRET_LENGTH = 6


def redact_secrets(text, secrets=()):
    """Schwaerzt Zugangsdaten in Log-Text: die uebergebenen bekannten Geheimnisse (samt ihrer mit '|'
    getrennten Teile - der shyft_access_key hat das Format <prefix>|<user_id>|<secret>), 'Bearer ...'
    und 'token=...'/'password: ...'-artige Zuweisungen."""
    text = str(text or "")
    parts = []
    for secret in secrets or ():
        if not secret:
            continue
        secret = str(secret)
        parts.append(secret)
        parts.extend(p for p in secret.split("|") if p != secret)
    for part in sorted(set(parts), key=len, reverse=True):
        if len(part) >= MIN_SECRET_LENGTH:
            text = text.replace(part, "***")
    text = _BEARER_RE.sub(r"\1***", text)
    return _SECRET_ASSIGNMENT_RE.sub(r"\1\2***", text)


def _normalize_log_line(line):
    return _LEADING_TIMESTAMP_RE.sub("", line).strip()


def extract_error_lines(log_text, secrets=()):
    """Fehler-/Warnzeilen aus einem Add-on-Log-Text: ANSI-Farbcodes entfernt, Traceback-Bloecke
    zusammenhaengend uebernommen, gleiche Zeilen (ohne Zeitstempel verglichen) zu einer mit Anzahl
    zusammengefasst, nur die MAX_LOG_EXCERPT_ENTRIES juengsten, jede Zeile auf MAX_LOG_LINE_CHARS
    gekappt, alles auf MAX_LOG_EXCERPT_CHARS begrenzt (aelteres faellt zuerst weg) und geschwaerzt
    (siehe redact_secrets). Leere Liste, wenn nichts Auffaelliges im Log steht."""
    lines = _ANSI_RE.sub("", str(log_text or "")).splitlines()
    lines = lines[-MAX_LOG_SOURCE_LINES:]
    entries = []  # [erste Zeile des Eintrags (mit Zeitstempel), normalisierter Schluessel, Anzahl]
    index = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        block = None
        if "Traceback (most recent call last)" in line:
            # Bis einschliesslich der abschliessenden Exception-Zeile ("ValueError: ..."), hoechstens
            # MAX_TRACEBACK_LINES Zeilen. Erkannt am normalisierten Zeilenanfang, denn im Supervisor-
            # Format text/x-log traegt jede Zeile einen Zeitstempel (Einrueckung ist daher unzuverlaessig).
            end = min(len(lines), i + MAX_TRACEBACK_LINES)
            for j in range(i + 1, end):
                if _EXCEPTION_LINE_RE.match(_normalize_log_line(lines[j])):
                    end = j + 1
                    break
            block = "\n".join(l.rstrip() for l in lines[i:end])
            i = end
        elif _ERROR_LINE_RE.search(line):
            block = line.rstrip()
            i += 1
        else:
            i += 1
            continue
        key = "\n".join(_normalize_log_line(l) for l in block.split("\n"))
        if key in index:
            entries[index[key]][2] += 1
            entries[index[key]][0] = block  # juengstes Vorkommen behalten
        else:
            index[key] = len(entries)
            entries.append([block, key, 1])
    result = []
    for block, _key, count in entries[-MAX_LOG_EXCERPT_ENTRIES:]:
        block = _clip_lines(block)
        result.append(f"{block} (x{count})" if count > 1 else block)
    # Gesamtlimit: von hinten (neueste zuerst) auffuellen, aelteres faellt weg.
    kept, total = [], 0
    for text in reversed(result):
        if total + len(text) + 1 > MAX_LOG_EXCERPT_CHARS:
            break
        kept.append(text)
        total += len(text) + 1
    kept.reverse()
    return [redact_secrets(text, secrets) for text in kept]


def _clip_lines(block):
    return "\n".join(_clip(line, MAX_LOG_LINE_CHARS) for line in block.split("\n"))


def find_ai_task_entity(states):
    "Erste verfuegbare ai_task-Entitaet (z.B. Google Gemini) oder None."
    for state in states:
        entity_id = state.get("entity_id", "")
        if entity_id.startswith(AI_TASK_DOMAIN + ".") and state.get("state") != "unavailable":
            return entity_id
    return None


def _clip(text, limit):
    text = str(text or "")
    return text if len(text) <= limit else text[:limit] + " ...(gekuerzt)"


def build_prompt(question, history, ui_help, config, problems, states, log_lines=None, support_offered=False):
    "log_lines: Fehler-/Warnzeilen aus dem Add-on-Log (siehe extract_error_lines) - None = Log nicht abrufbar, [] = nichts Auffaelliges. support_offered: das Support-Angebot (siehe KNOWLEDGE) wurde in diesem Chat schon gemacht."
    states_by_id = {s.get("entity_id"): s for s in states}
    problem_lines = [f"- {p.get('message')}" for p in (problems or [])[:MAX_PROBLEMS]] or ["(keine)"]
    history_blocks = []
    for turn in (history or [])[-MAX_HISTORY_TURNS:]:
        history_blocks.append(
            f"Frage: {_clip(turn.get('question'), MAX_QUESTION_CHARS)}\n"
            f"Antwort: {_clip(turn.get('answer'), MAX_HISTORY_ANSWER_CHARS)}")

    parts = [
        KNOWLEDGE,
        "=== Feldbeschreibungen der Oberflaeche (Tooltips) ===\n" + _clip(ui_help, MAX_UI_HELP_CHARS),
        "=== Aktuelle Konfiguration (JSON, ohne Zugangsdaten) ===\n" + summarize_config(config),
        "=== Aktuell aktive Probleme ===\n" + "\n".join(problem_lines),
        "=== Zugeordnete Sensoren: entity_id | Name | aktueller Wert ===\n"
        + "\n".join(mapped_sensor_lines(config, states_by_id)),
        "=== Weitere Home-Assistant-Entitaeten (Auswahl, entity_id | Name | Wert) ===\n"
        + "\n".join(candidate_entity_lines(states)),
        f"=== Auszug aus dem Add-on-Log (nur Fehler-/Warnzeilen der letzten ~{MAX_LOG_SOURCE_LINES} Logzeilen, aelteste zuerst; "
        "(xN) = N-mal aufgetreten) ===\n"
        + ("(Das Log konnte nicht abgerufen werden.)" if log_lines is None
           else "\n".join(log_lines) if log_lines else "(keine Fehler- oder Warnzeilen)"),
    ]
    if history_blocks:
        parts.append("=== Bisheriger Gespraechsverlauf ===\n" + "\n\n".join(history_blocks))
    if support_offered:
        parts.append("=== Hinweis ===\nDas Support-Angebot wurde in diesem Chat bereits gemacht - haenge KEINE Markierung [[SUPPORT_ANGEBOT: ...]] mehr an.")
    parts.append("=== Neue Frage des Nutzers ===\n" + _clip(question, MAX_QUESTION_CHARS))
    return "\n\n".join(parts)


def extract_answer(response):
    """Antwort-Text aus der Antwort von POST /api/services/ai_task/generate_data?return_response.
    Erwartet {"service_response": {"data": "...", ...}}; None, wenn kein Text enthalten ist."""
    service_response = (response or {}).get("service_response") or {}
    data = service_response.get("data")
    if isinstance(data, str) and data.strip():
        return data.strip()
    return None


# --- Support-Anfrage (Log + Problembeschreibung an shyft-power) --------------------------------
# Der Nutzer loest sie ueber das Formular unter einer KI-Antwort mit [[SUPPORT_ANGEBOT: ...]] aus (siehe KNOWLEDGE,
# www/assistant.js). Gesendet wird das Log der letzten SUPPORT_LOG_MINUTES Minuten, bei Bedarf auf
# MAX_SUPPORT_LOG_BYTES gekappt und ohne Zugangsdaten.
SUPPORT_LOG_MINUTES = 5
SUPPORT_LOG_SOURCE_LINES = 8000
MAX_SUPPORT_LOG_BYTES = 1_000_000
SUPPORT_LOG_MAX_LINE_CHARS = 2000
SUPPORT_LOG_FALLBACK_LINES = 3000
MAX_SUPPORT_SUMMARY_CHARS = 1000
SUPPORT_ERROR_TYPE = "service_request"

_LOG_TIMESTAMP_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})")
_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s.]{2,}$")


def _line_timestamp(line):
    match = _LOG_TIMESTAMP_RE.match(line)
    if not match:
        return None
    try:
        return datetime(*(int(g) for g in match.groups()))
    except ValueError:
        return None


def select_recent_log(log_text, minutes=SUPPORT_LOG_MINUTES, max_bytes=MAX_SUPPORT_LOG_BYTES,
                      max_line_chars=SUPPORT_LOG_MAX_LINE_CHARS, secrets=()):
    """Log der letzten `minutes` Minuten (gemessen am juengsten Zeitstempel im Log - der Supervisor stempelt jede Zeile
    im Format text/x-log, das Add-on loggt staendig, der juengste Zeitstempel entspricht also "jetzt" und die
    Zeitzone spielt keine Rolle). Zeilen ohne Zeitstempel (Traceback-Fortsetzungen) folgen der Entscheidung der
    Zeile davor. Ohne einen einzigen Zeitstempel: die letzten SUPPORT_LOG_FALLBACK_LINES Zeilen. Danach Zugangsdaten
    schwaerzen (siehe redact_secrets), einzelne Zeilen auf max_line_chars kuerzen und den Text auf max_bytes (UTF-8)
    begrenzen - dabei bleiben die NEUESTEN Zeilen erhalten, eine Kopfzeile nennt die Zahl der ausgelassenen.
    Rueckgabe: (Text, {"lines": Anzahl enthaltener Zeilen, "dropped": wegen der Groessenbegrenzung ausgelassen})."""
    lines = _ANSI_RE.sub("", str(log_text or "")).splitlines()
    stamps = [_line_timestamp(l) for l in lines]
    known = [t for t in stamps if t is not None]
    if not known:
        kept = lines[-SUPPORT_LOG_FALLBACK_LINES:]
    else:
        cutoff = known[-1] - timedelta(minutes=minutes)
        kept, keep = [], False
        for line, stamp in zip(lines, stamps):
            if stamp is not None:
                keep = stamp >= cutoff
            if keep:
                kept.append(line)
    kept = redact_secrets("\n".join(kept), secrets).split("\n") if kept else []
    kept = [l if len(l) <= max_line_chars else l[:max_line_chars] + " ...(gekürzt)" for l in kept]
    budget = max(0, max_bytes - 300)  # Platz fuer die Kopfzeile
    out, used = [], 0
    for line in reversed(kept):
        size = len(line.encode("utf-8")) + 1
        if used + size > budget:
            break
        out.append(line)
        used += size
    out.reverse()
    dropped = len(kept) - len(out)
    if dropped:
        out.insert(0, f"[... {dropped} ältere Zeilen wegen der Größenbegrenzung ({max_bytes // 1000} KB) ausgelassen ...]")
    return "\n".join(out), {"lines": len(out) - (1 if dropped else 0), "dropped": dropped}


def normalize_support_input(summary, email):
    """Prueft/bereinigt die Formulareingaben: Rueckgabe (summary, email, Fehlertext oder None). Die Zusammenfassung ist
    Pflicht (gekappt auf MAX_SUPPORT_SUMMARY_CHARS), die E-Mail-Adresse optional (leer -> ""), aber wenn angegeben
    syntaktisch plausibel."""
    summary = str(summary or "").strip()[:MAX_SUPPORT_SUMMARY_CHARS]
    email = str(email or "").strip()
    if not summary:
        return "", "", "Bitte beschreibe kurz das Problem."
    if email and not _EMAIL_RE.match(email):
        return summary, email, "Die E-Mail-Adresse ist nicht gültig - lass das Feld leer oder korrigiere sie."
    return summary, email, None


def build_support_payload(user_id, summary, email, version, log_text):
    """Struktur wie beim bestehenden Fehlerreport (ha_addon_error_logging): user, meta, error_type, error_message.
    meta = Zusammenfassung, Leerzeile, Add-on-Version, ggf. E-Mail-Adresse; error_message = das Log."""
    meta = f"{summary}\n\naddon_version={version}"
    if email:
        meta += f"\nemail={email}"
    return {"user": user_id, "meta": meta, "error_type": SUPPORT_ERROR_TYPE, "error_message": log_text}
