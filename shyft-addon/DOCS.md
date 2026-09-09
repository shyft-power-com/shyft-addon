# shyft-power HEMS

Energy Management System für Home Assistant. Das Add-on liest die Sensorwerte deiner
Geräte (PV, Batterie, Wärmepumpe, Wallbox, Auto, sonstige Verbraucher) aus Home
Assistant aus, lässt sie von shyft-power optimieren und steuert deine Geräte so, dass
deine Stromkosten sinken.

## Installation

1. Dieses Repository zum Add-on-Store hinzufügen:
   **Einstellungen → Add-ons → Add-on Store → ⋮ (oben rechts) → Repositories** und
   `https://github.com/shyft-power-com/shyft-addon` eintragen.
2. Add-on **shyft-power** installieren und starten.
3. Das Add-on erscheint als eigener Menüpunkt in der Seitenleiste. Dort die Geräte
   zuordnen und konfigurieren.

## Konfiguration

| Option | Beschreibung |
| --- | --- |
| `shyft_access_key` | Dein persönlicher Zugangs-Key von shyft-power. Ohne gültigen Key läuft das Add-on im Demomodus mit Beispieldaten. |
| `detailed_logging` | Ausführliche Logausgabe für die Fehlersuche. Standard: aus. |

Die eigentliche Geräte- und Optimierungs-Konfiguration erfolgt vollständig über die
Oberfläche des Add-ons, nicht über diese Optionen.

## Support

info@shyft-power.com · <https://www.shyft-power.com/>
