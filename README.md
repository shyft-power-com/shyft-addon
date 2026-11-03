# shyft-power – HEMS für Home Assistant

**Home-Energy-Management-System (HEMS) als Home-Assistant-Add-on.** shyft-power plant und steuert deine großen Stromverbraucher – Wärmepumpe, Warmwasser, Batteriespeicher, Wallbox/E-Auto und weitere Verbraucher – so, dass deine Stromkosten über die nächsten Stunden und Tage minimal werden. Mit lernenden Prognosen (PV, Hausverbrauch, Elektroautoverbrauch), dynamischen Stromtarifen, zeitvariablen Netzentgelten nach §14a EnWG (Modul 3) und einem thermischen Gebäudemodell für die Wärmepumpe. Auch Limit-Power-Production-Usecases können optimiert werden.

[![Add-on-Repository zu Home Assistant hinzufügen](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fshyft-power-com%2Fshyft-addon)

🌐 Website: <https://www.shyft-power.com>

---

## Warum shyft-power?

| | |
|---|---|
| **Optimieren statt Regeln** | Statt „Wenn Preis < X, dann laden“ berechnet ein mathematischer Optimierer einen Einsatzplan für alle Geräte gemeinsam – unter Berücksichtigung von PV-Prognose, Strompreisen, Wetter, Komfortgrenzen und Gerätezuständen. |
| **Herstellerübergreifend** | Alles, was in Home Assistant steckt, lässt sich anbinden: Wechselrichter, Batterie, Wärmepumpe (z. B. Nibe, Viessmann), Wallbox (z. B. Easee, go-e), E-Auto, Schaltaktoren (Shelly …). |
| **Wärmepumpe richtig steuern** | Heizleistung wird über Soll-/Vorlauftemperatur in günstige und warme Stunden verschoben – das Gebäude dient als Wärmespeicher, ohne Komfortverlust. |
| **Ohne YAML** | Eigene Oberfläche in der Home-Assistant-Seitenleiste: Geräte zuordnen, testen, fertig. Fertige [Blueprints](./blueprints) für Spezialfälle. |
| **Sofort ausprobieren** | Das Add-on startet im **Demomodus** mit Beispieldaten – ganz ohne Account. |

## Funktionen

- ☀️ **PV-Prognose**, die sich jede Nacht an den echten Erträgen deiner Anlage neu kalibriert (auch bei mehreren Dachflächen und Verschattung)
- 🔋 **Batteriesteuerung**: Netzladen in günstigen Stunden, Entladen verschieben, PV-Überschuss schonend laden
- 🌡️ **Wärmepumpe & Warmwasser**: preis- und temperaturoptimierte Heizkurve, Warmwasserbereitung zum günstigsten Zeitpunkt
- 🚗 **E-Auto & Wallbox**: Ladeplanung mit Anwesenheitsprognose
- 🔌 **Sonstige Verbraucher** (Heizstab, Pool, …) über Schalter
- 💶 **Dynamische Tarife** (Tibber, aWATTar, EPEX-Spot) sowie Hoch-/Niedertarif-Fenster und **§14a EnWG Modul 3**
- 📊 Dashboard mit Energiefluss, Einsatzplan und Ersparnis, Push-Benachrichtigungen aufs Handy

## Installation

1. Auf den Button oben klicken – oder in Home Assistant unter **Einstellungen → Add-ons → Add-on Store → ⋮ → Repositories** diese URL eintragen:
   ```
   https://github.com/shyft-power-com/shyft-addon
   ```
2. Add-on **shyft-power** installieren und starten.
3. In der Seitenleiste **shyft-power** öffnen, Geräte zuordnen – nach wenigen Minuten steht der erste optimierte Einsatzplan.

Voraussetzung: Home Assistant OS oder Supervised (Add-on-Store), Architektur `amd64` oder `aarch64`. Details: [DOCS.md](./shyft-addon/DOCS.md) · Änderungen: [CHANGELOG.md](./shyft-addon/CHANGELOG.md)

## Wie unterscheidet sich shyft-power von EMHASS und evcc?

Kurz: **evcc** ist hervorragend für PV-Überschussladen von E-Autos und arbeitet überwiegend regelbasiert. **EMHASS** ist ein sehr flexibler Open-Source-Optimierer, dessen Ergebnisse du aber selbst per YAML/Automationen in Steuerbefehle übersetzen musst. **shyft-power** kombiniert eine Optimierung über alle Geräte (inkl. Wärmepumpe mit Gebäudemodell) mit einer geführten Oberfläche, die die Steuerung direkt übernimmt.

## Datenschutz

Das Add-on läuft lokal in deinem Home Assistant und liest/schreibt dort die zugeordneten Entitäten. Für die Optimierung werden die dafür nötigen Messwerte und Einstellungen an den shyft-power-Dienst übertragen; der berechnete Einsatzplan wird lokal vom Add-on ausgeführt.

## Support

info@shyft-power.com · <https://www.shyft-power.com>

---

### English

**shyft-power is a Home Energy Management System (HEMS) add-on for Home Assistant.** It optimizes heat pumps, domestic hot water, home batteries, EV charging and other loads against dynamic electricity prices (Tibber, aWATTar, EPEX spot), a self-learning PV forecast and a thermal building model – configured through its own UI, no YAML required. Add the repository URL above to your Home Assistant add-on store to try it in demo mode. The UI is currently in German.
