# the following constants are required to nbe filled with useful values
BUBBLE_URI_TEST = "https://shyft-power.com/version-test/"
BUBBLE_URI_PRD = "https://shyft-power.com/"
BUBBLE_TOKEN ="sa"

# Ein shyft_access_key mit diesem Praefix routet an die shyft-power-Testumgebung statt an Prod -
# siehe ShyftAdapter.set_access_key. Analog zu z.B. Stripes "sk_test_..." vs. "sk_live_..."
# API-Keys: die Umgebung steckt im Schluessel selbst statt in einer eigenen, fuer jeden Nutzer
# sichtbaren Konfigurationsoption (die liesse sich versehentlich hin- und herschalten, ohne dass
# der Nutzer merkt, dass seine Daten dann gar nicht mehr in Prod ankommen). Wird ausschliesslich
# manuell vom Entwickler selbst gesetzt (eigene Test-HA-Instanz), nie ueber die Konfigurationsseite
# des Addons - ein normaler Nutzer bekommt seinen echten Key nie mit diesem Praefix.
DEV_ACCESS_KEY_PREFIX = "test_"

HOMEASSISTANT_URI="http://homeassistant.local:8123"
CONFIG_PATH = "/data/config.json"


# Detail-Logging (Option detailed_logging) schreibt komplette HA-/Bubble-Antworten ins Log - ein einzelner History-Abruf
# sind schnell 10-20 kB in EINER Zeile und verdraengen alles andere (die Diagnose- und Aktionszeilen sind nach wenigen
# Minuten aus dem Supervisor-Log-Fenster). Deshalb werden die Detail-Meldungen gekuerzt; die Laenge bleibt erkennbar.
LOG_DETAIL_MAX_CHARS = 600


def shorten_log_detail(message, limit=LOG_DETAIL_MAX_CHARS):
    message = str(message)
    if len(message) <= limit:
        return message
    return f"{message[:limit]} [... {len(message) - limit} Zeichen gekuerzt]"
