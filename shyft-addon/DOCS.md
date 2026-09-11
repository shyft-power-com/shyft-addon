# shyft-power HEMS

Home-Energy-Management-System für Home Assistant. Mit dem du deine großen
Stromverbraucher optimal steuern und so Stromkosten minimieren kannst. Inkl.
PV-Prognose, Auto-Anwesenheitsprognose, Wärmepumpensteuerung über die Vorlauftemperatur
und Batteriesteuerung. Dank der Integration in Home Assistant können quasi alle
Hersteller angebunden werden. Die Steuerungen können zudem individualisiert werden.

## Installation

1. Dieses Repository zum Add-on-Store hinzufügen:
   **Einstellungen → Add-ons → Add-on Store → ⋮ (oben rechts) → Repositories** und
   `https://github.com/shyft-power-com/shyft-addon` eintragen.
2. Add-on **shyft-power** installieren und starten.
3. Das Add-on erscheint als eigener Menüpunkt in der Seitenleiste. Dort die Geräte
   zuordnen und konfigurieren.

## Konfiguration

Das Add-on startet im Demomodus. Hinterlege auf dem Reiter "Konfiguration" deine
Geräte, nach wenigen Minuten wird der erste optimale Einsatzplan berechnet.

| Option | Beschreibung |
| --- | --- |
| `shyft_access_key` | Dein persönlicher Zugangs-Key von shyft-power. Ohne gültigen Key läuft das Add-on im Demomodus mit Beispieldaten. |
| `detailed_logging` | Ausführliche Logausgabe für die Fehlersuche. Standard: aus. |

Die eigentliche Geräte- und Optimierungs-Konfiguration erfolgt vollständig über die
Oberfläche des Add-ons, nicht über diese Optionen.

## Support

info@shyft-power.com · <https://www.shyft-power.com/>
