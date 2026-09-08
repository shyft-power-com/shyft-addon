#!/usr/bin/env node
// Regeneriert www/integrationDomainHints.json aus dem oeffentlichen HA-Kern-Integrationskatalog
// (https://www.home-assistant.io/integrations.json - ein File, keyed nach Integrations-Domain).
// Der Katalog listet nur Kern-Integrationen; verbreitete HACS-Integrationen deckt BRAND_HINTS ab.
//
// Ergebnis: { "<domain>": ["batterie", "wechselrichter", ...] } - je Integration die shyft-
// Geraetekacheln, zu denen Titel/Beschreibung passen. NUR ein weiches Ranking-Signal im
// Geraete-Dropdown (siehe scoreIntegrationForSection in www/app.js), NIE zum Ausblenden - fehlt
// eine Domain hier, landet die Integration halt unter "Weitere Geraete", bleibt waehlbar.
//
// Gelegentlich neu laufen lassen (z.B. pro HA-Minor-Release):
//   node shyft-addon/scripts/gen-integration-hints.mjs
import https from 'node:https';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const SRC = 'https://www.home-assistant.io/integrations.json';
const OUT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'www', 'integrationDomainHints.json');

// integration_type-Werte, die ueberhaupt ein echtes Geraet/eine echte Integration sein koennen -
// helper/service/system/hardware sowie die reinen Verweise virtual/brand fliegen raus.
const USABLE_TYPES = new Set(['device', 'hub', 'integration', 'entity', '']);

// Stichwoerter je shyft-Kachel, geprueft gegen (domain + " " + title + " " + description),
// kleingeschrieben. Bewusst konservativ - lieber ein paar Integrationen unter "Weitere Geraete"
// als Fehltreffer oben.
const KEYWORDS = {
    wechselrichter: [/\bsolar\b/, /photovolta/, /\binverter/, /\bpv system/],
    batterie: [/\bbatter(y|ies)\b/, /energy storage/, /home battery/, /solar battery/, /battery storage/, /powerwall/, /\bbess\b/],
    waermepumpe: [/heat ?pump/, /w(ä|ae)rmepumpe/, /\bhvac\b/, /thermostat/, /\bboiler\b/, /water heater/, /climate control/, /heating system/],
    auto: [/\bvehicles?\b/, /electric (car|vehicle)/, /\bcars?\b/],
    wallbox: [/wall ?box/, /ev charg/, /charging station/, /charge ?point/, /\bevse\b/, /\bcharger\b/],
};

// Bekannte Energie-Integrationen (Kern + verbreitete HACS), deren Katalog-Beschreibung nur
// "Instructions on how to integrate X within Home Assistant." sagt und daher von KEYWORDS nicht
// getroffen wird - bzw. die gar nicht im Kern-Katalog stehen. Werden immer emittiert. Das ist
// KEINE Hand-Pflege der Ausgabe, sondern eine seltene Ergaenzung im Generator fuer die grossen
// Namen - die Entitaets-Form-Heuristik im Frontend faengt den Rest.
const BRAND_HINTS = {
    // Wechselrichter / PV
    solaredge: ['wechselrichter'], fronius: ['wechselrichter'], enphase_envoy: ['wechselrichter'],
    solax: ['wechselrichter'], solarman: ['wechselrichter'], huawei_solar: ['batterie', 'wechselrichter'],
    sma_ennexos: ['wechselrichter'], sungrow: ['wechselrichter'], sunweg: ['wechselrichter'],
    foxess: ['batterie', 'wechselrichter'], deye: ['batterie', 'wechselrichter'],
    // Batterie / Hybrid
    victron: ['batterie', 'wechselrichter'], victron_ble: ['batterie', 'wechselrichter'],
    sonnen: ['batterie'], sonnenbatterie: ['batterie'], tesla_powerwall: ['batterie'],
    byd_battery_box: ['batterie'], senec: ['batterie', 'wechselrichter'], varta: ['batterie'],
    e3dc: ['batterie', 'wechselrichter'],
    // Waermepumpe / Klima
    viessmann: ['waermepumpe'], vicare: ['waermepumpe'], daikin: ['waermepumpe'],
    daikin_onecta: ['waermepumpe'], lambda_heat_pumps: ['waermepumpe'], tado: ['waermepumpe'],
    sg_ready: ['waermepumpe'], mill: ['waermepumpe'], panasonic_cc: ['waermepumpe'],
    melcloud: ['waermepumpe'],
    // Wallbox / Ladestation
    easee: ['wallbox'], goecharger: ['wallbox'], go_echarger: ['wallbox'], zaptec: ['wallbox'],
    wallbox_pulsar: ['wallbox'], evcc: ['wallbox'], openwb: ['wallbox'], senec_wallbox: ['wallbox'],
    // Fahrzeuge
    tesla_fleet: ['auto'], tesla_custom: ['auto'], teslemetry: ['auto'], tessie: ['auto'],
    bmw_connected_drive: ['auto'], volkswagen: ['auto'], volkswagen_we_connect_id: ['auto'],
    kia_uvo: ['auto'], hyundai_kia_connect: ['auto'], audiconnect: ['auto'], mercedesme: ['auto'],
    volvo: ['auto'], volvooncall: ['auto'], polestar_api: ['auto'], nissan_leaf: ['auto'],
    skodaconnect: ['auto'], smart_eq: ['auto'],
};

function fetchJson(url) {
    return new Promise((resolve, reject) => {
        https.get(url, { headers: { 'user-agent': 'shyft-addon-hint-generator' } }, (res) => {
            if (res.statusCode !== 200) { reject(new Error('HTTP ' + res.statusCode + ' for ' + url)); return; }
            let body = '';
            res.setEncoding('utf8');
            res.on('data', (c) => body += c);
            res.on('end', () => { try { resolve(JSON.parse(body)); } catch (e) { reject(e); } });
        }).on('error', reject);
    });
}

const catalog = await fetchJson(SRC);
const hints = {};

// 1) Kern-Katalog nach Stichwoertern durchsuchen.
for (const [domain, meta] of Object.entries(catalog)) {
    if (!USABLE_TYPES.has((meta.integration_type || '').toLowerCase())) continue;
    const hay = (domain + ' ' + (meta.title || '') + ' ' + (meta.description || '')).toLowerCase();
    const sections = new Set();
    for (const [section, patterns] of Object.entries(KEYWORDS)) {
        if (patterns.some((re) => re.test(hay))) sections.add(section);
    }
    if (sections.size) hints[domain] = [...sections];
}

// 2) Kuratierte Marken immer ergaenzen (auch wenn nicht im Kern-Katalog -> HACS).
for (const [domain, sections] of Object.entries(BRAND_HINTS)) {
    hints[domain] = [...new Set([...(hints[domain] || []), ...sections])];
}

const sorted = Object.fromEntries(
    Object.entries(hints).sort(([a], [b]) => a.localeCompare(b)).map(([d, s]) => [d, s.sort()])
);
fs.writeFileSync(OUT, JSON.stringify(sorted) + '\n');
console.log(`wrote ${Object.keys(sorted).length} domains -> ${path.relative(process.cwd(), OUT)}`);
