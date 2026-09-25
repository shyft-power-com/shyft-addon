// Hilfe-Assistent (KI-Chat) - schwebendes Icon unten rechts auf allen Seiten. Die Antworten kommen
// ueber Home Assistants ai_task.generate_data (siehe /assistant/ask in app.py); ohne eingerichtete
// KI zeigt das Eingabefeld stattdessen einen Einrichtungshinweis.

const PLACEHOLDER_AI_AVAILABLE = 'Frage die KI um Hilfe';
const PLACEHOLDER_AI_MISSING = 'Nutze deine KI, um nach Hilfe zu fragen. Binde hierfür die Integration "Google -> Google Gemini" in Home Assistant ein.';
const PRIVACY_NOTICE = 'Hinweis: Bei der Nutzung der Hilfe-Funktion teilst du deine Sensorzustände sowie einen Auszug aus dem Add-on-Log (nur Fehler- und Warnzeilen, ohne Zugangsdaten) mit deinem KI-Anbieter.';
const SUPPORT_LINK_INTRO = 'Du kannst uns bei einem Problem deine Log-Dateien senden. Wir schauen uns das Problem dann an und versuchen es zu beheben. ';
const TEAM_NOTICE_TEXT ='Bei Fragen an das Shyft-Team schreibe bitte an ';
const TEAM_MAIL = 'info@shyft-power.com';
const MAX_HISTORY_SENT = 3;
// Oeffnet Home Assistants eigenen "Integration hinzufuegen"-Dialog fuer Google Gemini (dort wird auch der
// API-Schluessel eingegeben). Der Add-on-Ingress liegt auf derselben Origin wie Home Assistant, ein
// absoluter Pfad genuegt - dasselbe Ziel wie der My-Home-Assistant-Link "config_flow_start".
const GEMINI_SETUP_URL = '/config/integrations/dashboard/add?domain=google_generative_ai_conversation';
const GEMINI_API_KEY_URL = 'https://aistudio.google.com/app/apikey';

// Support-Angebot: die KI haengt am Ende ihrer Antwort [[SUPPORT_ANGEBOT: kurze Problembeschreibung]] an (siehe
// KNOWLEDGE in assistant.py). Die Markierung wird nie angezeigt; stattdessen erscheint ein Formular, mit dem der Nutzer
// Log + Beschreibung an das Shyft-Team senden kann (siehe /assistant/support/* in app.py).
const SUPPORT_MARKER_RE = /\[\[SUPPORT_ANGEBOT:?([\s\S]*?)\]\]/;
const SUPPORT_MARKER_OPEN_RE = /\[\[SUPPORT_ANGEBOT[\s\S]*$/;
const SUPPORT_LOGGING_MINUTES_TEXT = '5';
const SUPPORT_STATUS_POLL_MS = 4000;

// Trennt die Markierung vom Antworttext: {text: Antwort ohne Markierung, summary: Beschreibung oder null}.
// Auch eine abgeschnittene Markierung (ohne schliessende Klammern) wird entfernt.
export function splitSupportOffer(answer) {
    const text = String(answer || '');
    const match = text.match(SUPPORT_MARKER_RE);
    if (match) {
        return {text: text.replace(SUPPORT_MARKER_RE, '').trim(), summary: match[1].trim()};
    }
    if (SUPPORT_MARKER_OPEN_RE.test(text)) {
        return {text: text.replace(SUPPORT_MARKER_OPEN_RE, '').trim(), summary: null, malformed: true};
    }
    return {text: text.trim(), summary: null};
}

function formatCountdown(ms) {
    const total = Math.max(0, Math.ceil(ms / 1000));
    return Math.floor(total / 60) + ':' + String(total % 60).padStart(2, '0');
}

const CHAT_ICON_SVG = '<svg viewBox="0 0 24 24" width="26" height="26" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20.5l1.4-4.6A8 8 0 1 1 21 12z"/></svg>';

// Anders als postJson in app.js wird der JSON-Body auch bei HTTP-Fehlerstatus gelesen - das Backend
// liefert dort eine nutzerlesbare "message".
async function postAsk(url, data) {
    const response = await fetch(url, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data),
    });
    try {
        return await response.json();
    } catch (err) {
        return {status: 'error', message: `HTTP-Fehler ${response.status}`};
    }
}

export function initAssistantWidget({getJson, baseUri, buildUiHelp}) {
    if (document.getElementById('assistantWidget')) return;

    const root = document.createElement('div');
    root.id = 'assistantWidget';
    root.className = 'assistantWidget';

    const launcher = document.createElement('button');
    launcher.type = 'button';
    launcher.className = 'assistantLauncher';
    launcher.setAttribute('aria-label', 'Hilfe-Assistent öffnen');
    launcher.setAttribute('aria-expanded', 'false');
    launcher.innerHTML = CHAT_ICON_SVG;

    const panel = document.createElement('div');
    panel.className = 'assistantPanel';
    panel.hidden = true;
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', 'Hilfe-Assistent');

    const header = document.createElement('div');
    header.className = 'assistantHeader';
    const title = document.createElement('span');
    title.textContent = 'Hilfe';
    const closeButton = document.createElement('button');
    closeButton.type = 'button';
    closeButton.className = 'assistantClose';
    closeButton.textContent = '×';
    closeButton.setAttribute('aria-label', 'Schließen');
    header.appendChild(title);
    header.appendChild(closeButton);

    const messages = document.createElement('div');
    messages.className = 'assistantMessages';

    const input = document.createElement('textarea');
    input.className = 'assistantInput';
    input.rows = 3;
    input.setAttribute('aria-label', 'Frage an die KI');

    const sendButton = document.createElement('button');
    sendButton.type = 'button';
    sendButton.className = 'assistantSend';
    sendButton.textContent = 'Fragen';

    const inputRow = document.createElement('div');
    inputRow.className = 'assistantInputRow';
    inputRow.appendChild(input);
    inputRow.appendChild(sendButton);

    const setupBox = document.createElement('div');
    setupBox.className = 'assistantSetup';
    setupBox.hidden = true;
    const setupButton = document.createElement('a');
    setupButton.className = 'assistantSetupButton';
    setupButton.href = GEMINI_SETUP_URL;
    setupButton.target = '_blank';
    setupButton.rel = 'noopener';
    setupButton.textContent = 'Google Gemini einrichten';
    const setupHint = document.createElement('div');
    setupHint.className = 'assistantNotice assistantSetupHint';
    setupHint.appendChild(document.createTextNode('Home Assistant fragt dort nach einem API-Schlüssel. Den erstellst du in '));
    const keyLink = document.createElement('a');
    keyLink.href = GEMINI_API_KEY_URL;
    keyLink.target = '_blank';
    keyLink.rel = 'noopener';
    keyLink.textContent = 'Google AI Studio';
    setupHint.appendChild(keyLink);
    setupHint.appendChild(document.createTextNode('. Danach kommst du hierher zurück.'));
    setupBox.appendChild(setupButton);
    setupBox.appendChild(setupHint);

    const privacy = document.createElement('div');
    privacy.className = 'assistantNotice';
    privacy.textContent = PRIVACY_NOTICE;

    const team = document.createElement('div');
    team.className = 'assistantNotice';
    team.appendChild(document.createTextNode(TEAM_NOTICE_TEXT));
    const mail = document.createElement('a');
    mail.href = 'mailto:' + TEAM_MAIL;
    mail.textContent = TEAM_MAIL;
    team.appendChild(mail);
    team.appendChild(document.createTextNode('.'));

    // Immer sichtbar, auch ohne eingerichtete KI: oeffnet dasselbe Support-Formular wie das Angebot der KI.
    const supportLinkRow = document.createElement('div');
    supportLinkRow.className = 'assistantNotice';
    supportLinkRow.appendChild(document.createTextNode(SUPPORT_LINK_INTRO));
    const supportLink = document.createElement('button');
    supportLink.type = 'button';
    supportLink.className = 'assistantSupportLink';
    supportLink.textContent = 'Log senden';
    supportLinkRow.appendChild(supportLink);

    // KI-Bereich (Eingabe, Einrichtungshinweis, Datenschutzhinweis) - wird ausgeblendet, sobald der Nutzer ueber den
    // Link das Support-Formular oeffnet, damit nur noch das Formular im Blick ist.
    const aiSection = document.createElement('div');
    aiSection.className = 'assistantAiSection';
    aiSection.appendChild(inputRow);
    aiSection.appendChild(setupBox);
    aiSection.appendChild(privacy);

    function divider() {
        const line = document.createElement('hr');
        line.className = 'assistantDivider';
        return line;
    }
    const aiDivider = divider();

    panel.appendChild(header);
    panel.appendChild(messages);
    panel.appendChild(aiSection);
    panel.appendChild(aiDivider);
    panel.appendChild(supportLinkRow);
    panel.appendChild(divider());
    panel.appendChild(team);
    root.appendChild(panel);
    root.appendChild(launcher);
    document.body.appendChild(root);

    let aiAvailable = false;
    let busy = false;
    let supportOffered = false;  // das Support-Angebot erscheint hoechstens einmal pro Chat
    let supportCard = null;
    const history = [];

    function addMessage(text, kind) {
        const bubble = document.createElement('div');
        bubble.className = 'assistantMessage assistantMessage--' + kind;
        bubble.textContent = text;
        messages.appendChild(bubble);
        messages.scrollTop = messages.scrollHeight;
        return bubble;
    }

    // Support-Formular unter einer KI-Antwort: Beschreibung (bearbeitbar), optionale E-Mail, Hinweis auf die gesendeten
    // Daten, Countdown des ausfuehrlichen Loggings und der Senden-Button. Beim Anzeigen wird das ausfuehrliche Logging
    // fuer 5 Minuten aktiviert (der Nutzer soll das Problem nachstellen); gesendet wird erst nach Ablauf.
    function addSupportForm(summaryText) {
        const card = document.createElement('div');
        card.className = 'assistantSupport';

        const heading = document.createElement('div');
        heading.className = 'assistantSupportHeading';
        heading.textContent = 'Problem an das Shyft-Team senden?';
        card.appendChild(heading);

        const summaryLabel = document.createElement('label');
        summaryLabel.textContent = 'Kurze Beschreibung des Problems';
        const summary = document.createElement('textarea');
        summary.className = 'assistantSupportField';
        summary.rows = 3;
        summary.maxLength = 1000;
        summary.value = summaryText || '';
        summaryLabel.appendChild(summary);
        card.appendChild(summaryLabel);

        const emailLabel = document.createElement('label');
        emailLabel.textContent = 'E-Mail-Adresse (optional, falls du eine Rückmeldung wünschst)';
        const email = document.createElement('input');
        email.type = 'email';
        email.className = 'assistantSupportField';
        email.autocomplete = 'email';
        email.maxLength = 254;
        emailLabel.appendChild(email);
        card.appendChild(emailLabel);

        const sentInfo = document.createElement('div');
        sentInfo.className = 'assistantNotice';
        sentInfo.textContent = 'Gesendet werden: deine Beschreibung, die Add-on-Version, deine E-Mail-Adresse (falls angegeben) und das '
            + 'Add-on-Log der letzten ' + SUPPORT_LOGGING_MINUTES_TEXT + ' Minuten (höchstens 1 MB). Zugangsdaten werden geschwärzt, '
            + 'das Log kann aber Entity-IDs, Gerätenamen und Sensorwerte enthalten.';
        card.appendChild(sentInfo);

        const loggingInfo = document.createElement('div');
        loggingInfo.className = 'assistantNotice assistantSupportLogging';
        loggingInfo.textContent = 'Detailliertes Logging wird aktiviert ...';
        card.appendChild(loggingInfo);

        const sendSupport = document.createElement('button');
        sendSupport.type = 'button';
        sendSupport.className = 'assistantSend assistantSupportSend';
        sendSupport.textContent = 'An shyft-power senden';
        card.appendChild(sendSupport);

        const result = document.createElement('div');
        result.className = 'assistantSupportResult';
        result.hidden = true;
        card.appendChild(result);

        let loggingUntilMs = 0;
        let sendAtMs = 0;
        let ticker = null;
        let poller = null;

        function showResult(text, isError) {
            result.hidden = false;
            result.textContent = text;
            result.classList.toggle('assistantSupportResult--error', !!isError);
        }

        function stopTimers() {
            clearInterval(ticker);
            clearInterval(poller);
        }

        function tick() {
            const now = Date.now();
            if (loggingUntilMs > now) {
                loggingInfo.textContent = 'Detailliertes Logging ist für die nächsten ' + SUPPORT_LOGGING_MINUTES_TEXT
                    + ' Minuten aktiviert (noch ' + formatCountdown(loggingUntilMs - now) + '). Bitte stelle das Problem jetzt noch einmal nach. '
                    + 'Das Log wird nach Ablauf der ' + SUPPORT_LOGGING_MINUTES_TEXT + ' Minuten gesendet.';
            } else if (loggingUntilMs) {
                loggingInfo.textContent = 'Das detaillierte Logging ist beendet.';
            }
            if (sendAtMs && sendAtMs > now) {
                showResult('Das Log wird automatisch gesendet, sobald die ' + SUPPORT_LOGGING_MINUTES_TEXT + ' Minuten um sind (in '
                    + formatCountdown(sendAtMs - now) + '). Du kannst den Chat schließen.', false);
            }
        }

        async function poll() {
            try {
                const status = await getJson(baseUri + '/assistant/support/status');
                if (status.state === 'done') {
                    stopTimers();
                    showResult(status.message, false);
                } else if (status.state === 'error') {
                    stopTimers();
                    sendSupport.disabled = false;
                    showResult(status.message, true);
                } else if (status.state === 'idle') {
                    // Add-on wurde inzwischen neu gestartet - der wartende Versand ist verloren
                    stopTimers();
                    sendSupport.disabled = false;
                    showResult('Die Anfrage ist nicht mehr aktiv (Add-on neu gestartet?). Bitte sende sie erneut.', true);
                } else if (status.state === 'sending') {
                    sendAtMs = 0;
                    showResult(status.message || 'Das Log wird gesendet ...', false);
                }
            } catch (err) {
                console.log(err);
            }
        }

        sendSupport.addEventListener('click', async () => {
            sendSupport.disabled = true;
            result.hidden = true;
            try {
                const response = await postAsk(baseUri + '/assistant/support/send', {summary: summary.value, email: email.value});
                if (response.status !== 'success') {
                    sendSupport.disabled = false;
                    showResult(response.message || 'Das Senden ist fehlgeschlagen.', true);
                    return;
                }
                sendAtMs = response.sendAtMs || 0;
                if (!sendAtMs) showResult('Das Log wird gesendet ...', false);
                tick();
                clearInterval(poller);
                poller = setInterval(poll, SUPPORT_STATUS_POLL_MS);
            } catch (err) {
                console.log(err);
                sendSupport.disabled = false;
                showResult('Das Senden ist fehlgeschlagen. Bitte versuche es später erneut.', true);
            }
        });

        messages.appendChild(card);
        messages.scrollTop = messages.scrollHeight;
        supportCard = card;

        postAsk(baseUri + '/assistant/support/start', {}).then(response => {
            if (response.loggingUntilMs) {
                loggingUntilMs = response.loggingUntilMs;
                tick();
                ticker = setInterval(tick, 1000);
            } else {
                loggingInfo.textContent = 'Das detaillierte Logging konnte nicht aktiviert werden - gesendet wird das normale Log.';
            }
        }).catch(err => {
            console.log(err);
            loggingInfo.textContent = 'Das detaillierte Logging konnte nicht aktiviert werden - gesendet wird das normale Log.';
        });
    }

    // Oeffnet das Support-Formular ueber den Link (ohne Angebot der KI): Beschreibung mit den aktuell aktiven Problemen
    // vorbelegt (bearbeitbar). Pro Chat gibt es nur ein Formular - ein zweiter Klick springt zu ihm.
    async function openSupportForm() {
        aiSection.hidden = true;
        aiDivider.hidden = true;
        if (supportCard) {
            messages.scrollTop = supportCard.offsetTop - messages.offsetTop;
            return;
        }
        supportOffered = true;
        let summary = '';
        try {
            const health = await getJson(baseUri + '/system-health');
            summary = (health.problems || []).slice(0, 3).map(p => p.message).join('\n');
        } catch (err) {
            console.log(err);
        }
        if (!supportCard) addSupportForm(summary);
    }

    function applyAvailability() {
        input.placeholder = aiAvailable ? PLACEHOLDER_AI_AVAILABLE : PLACEHOLDER_AI_MISSING;
        input.disabled = !aiAvailable;
        sendButton.disabled = !aiAvailable || busy;
        setupBox.hidden = aiAvailable;
    }

    async function refreshStatus() {
        try {
            const status = await getJson(baseUri + '/assistant/status');
            aiAvailable = !!status.aiAvailable;
        } catch (err) {
            console.log(err);
            aiAvailable = false;
        }
        applyAvailability();
    }

    function setOpen(open) {
        panel.hidden = !open;
        launcher.setAttribute('aria-expanded', String(open));
        if (open) {
            refreshStatus().then(() => { if (aiAvailable) input.focus(); });
        }
    }

    async function send() {
        const question = input.value.trim();
        if (!question || busy || !aiAvailable) return;
        busy = true;
        applyAvailability();
        input.value = '';
        addMessage(question, 'user');
        const pending = addMessage('Die KI denkt nach...', 'pending');
        try {
            const result = await postAsk(baseUri + '/assistant/ask', {
                question,
                history: history.slice(-MAX_HISTORY_SENT),
                uiHelp: buildUiHelp(),
                supportOffered,
            });
            pending.remove();
            if (result.status === 'success') {
                // Die Markierung wird nie angezeigt; das Formular erscheint nur beim ersten Angebot pro Chat.
                const offer = splitSupportOffer(result.answer);
                if (offer.text) addMessage(offer.text, 'answer');
                history.push({question, answer: offer.text || result.answer});
                if (offer.summary !== null && !supportOffered) {
                    supportOffered = true;
                    addSupportForm(offer.summary);
                }
            } else {
                addMessage(result.message || 'Die Anfrage ist fehlgeschlagen.', 'error');
            }
        } catch (err) {
            console.log(err);
            pending.remove();
            addMessage('Die Anfrage ist fehlgeschlagen. Bitte versuche es später erneut.', 'error');
        }
        busy = false;
        applyAvailability();
        if (aiAvailable) input.focus();
    }

    // Nach der Einrichtung in Home Assistant (anderer Tab) beim Zurueckkehren automatisch neu pruefen.
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible' && !panel.hidden && !aiAvailable) refreshStatus();
    });
    window.addEventListener('focus', () => {
        if (!panel.hidden && !aiAvailable) refreshStatus();
    });

    launcher.addEventListener('click', () => setOpen(panel.hidden));
    closeButton.addEventListener('click', () => { setOpen(false); launcher.focus(); });
    sendButton.addEventListener('click', send);
    supportLink.addEventListener('click', openSupportForm);
    input.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            send();
        }
    });
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && !panel.hidden) setOpen(false);
    });
    // Klick ausserhalb des Assistenten schliesst das Popup (Klicks auf Icon/Panel selbst nicht).
    document.addEventListener('pointerdown', (event) => {
        if (!panel.hidden && !root.contains(event.target)) setOpen(false);
    });

    applyAvailability();
}
