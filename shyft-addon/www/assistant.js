// Hilfe-Assistent (KI-Chat) - schwebendes Icon unten rechts auf allen Seiten. Die Antworten kommen
// ueber Home Assistants ai_task.generate_data (siehe /assistant/ask in app.py); ohne eingerichtete
// KI zeigt das Eingabefeld stattdessen einen Einrichtungshinweis.

const PLACEHOLDER_AI_AVAILABLE = 'Frage die KI um Hilfe';
const PLACEHOLDER_AI_MISSING = 'Nutze deine KI, um nach Hilfe zu fragen. Binde hierfür die Integration "Google -> Google Gemini" in Home Assistant ein.';
const PRIVACY_NOTICE = 'Hinweis: Bei der Nutzung der Hilfe-Funktion teilst du deine Sensorzustände mit deinem KI-Anbieter.';
const TEAM_NOTICE_TEXT = 'Bei Fragen an das Shyft-Team schreibe bitte an ';
const TEAM_MAIL = 'info@shyft-power.com';
const MAX_HISTORY_SENT = 3;
// Oeffnet Home Assistants eigenen "Integration hinzufuegen"-Dialog fuer Google Gemini (dort wird auch der
// API-Schluessel eingegeben). Der Add-on-Ingress liegt auf derselben Origin wie Home Assistant, ein
// absoluter Pfad genuegt - dasselbe Ziel wie der My-Home-Assistant-Link "config_flow_start".
const GEMINI_SETUP_URL = '/config/integrations/dashboard/add?domain=google_generative_ai_conversation';
const GEMINI_API_KEY_URL = 'https://aistudio.google.com/app/apikey';

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

    panel.appendChild(header);
    panel.appendChild(messages);
    panel.appendChild(inputRow);
    panel.appendChild(setupBox);
    panel.appendChild(privacy);
    panel.appendChild(team);
    root.appendChild(panel);
    root.appendChild(launcher);
    document.body.appendChild(root);

    let aiAvailable = false;
    let busy = false;
    const history = [];

    function addMessage(text, kind) {
        const bubble = document.createElement('div');
        bubble.className = 'assistantMessage assistantMessage--' + kind;
        bubble.textContent = text;
        messages.appendChild(bubble);
        messages.scrollTop = messages.scrollHeight;
        return bubble;
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
            });
            pending.remove();
            if (result.status === 'success') {
                addMessage(result.answer, 'answer');
                history.push({question, answer: result.answer});
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
    input.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            send();
        }
    });
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && !panel.hidden) setOpen(false);
    });

    applyAvailability();
}
