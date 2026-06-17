(function () {
  if (window.__FAQBOT_WIDGET_LOADED__) return;
  window.__FAQBOT_WIDGET_LOADED__ = true;

  // The widget calls back to whatever origin served this script.
  const me = document.currentScript || document.getElementsByTagName('script')[document.getElementsByTagName('script').length - 1];
  const API_BASE = new URL(me.src).origin;

  // Persistent per-browser session ID for conversation memory.
  let sessionId = localStorage.getItem('faqbot_session_id');
  if (!sessionId) {
    sessionId = (crypto.randomUUID && crypto.randomUUID()) || `s${Date.now()}${Math.random().toString(36).slice(2)}`;
    localStorage.setItem('faqbot_session_id', sessionId);
  }

  const styles = `
    .faqbot-btn { position: fixed; bottom: 24px; right: 24px; width: 56px; height: 56px; border-radius: 50%; background: #2563eb; color: white; border: none; box-shadow: 0 4px 14px rgba(0,0,0,0.18); cursor: pointer; z-index: 2147483646; display: flex; align-items: center; justify-content: center; transition: transform .15s, background .15s; }
    .faqbot-btn:hover { transform: translateY(-1px); background: #1d4ed8; }
    .faqbot-btn svg { width: 26px; height: 26px; }
    .faqbot-panel { position: fixed; bottom: 96px; right: 24px; width: 380px; max-width: calc(100vw - 32px); height: 540px; max-height: calc(100vh - 120px); background: white; border-radius: 14px; box-shadow: 0 12px 40px rgba(0,0,0,0.20); display: none; flex-direction: column; overflow: hidden; z-index: 2147483647; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; color: #111827; }
    .faqbot-panel.open { display: flex; }
    .faqbot-header { padding: 14px 16px; background: #2563eb; color: white; display: flex; align-items: center; justify-content: space-between; }
    .faqbot-header-name { font-weight: 600; font-size: 15px; }
    .faqbot-actions { display: flex; align-items: center; gap: 2px; }
    .faqbot-icon { background: transparent; border: none; color: white; cursor: pointer; opacity: .85; padding: 5px; display: flex; border-radius: 7px; }
    .faqbot-icon:hover { opacity: 1; background: rgba(255,255,255,.16); }
    .faqbot-icon svg { width: 18px; height: 18px; }
    .faqbot-close { background: transparent; border: none; color: white; cursor: pointer; font-size: 24px; line-height: 1; padding: 2px 6px; opacity: .85; border-radius: 7px; }
    .faqbot-close:hover { opacity: 1; background: rgba(255,255,255,.16); }
    .faqbot-messages { flex: 1; overflow-y: auto; padding: 16px; background: #f9fafb; display: flex; flex-direction: column; gap: 8px; }
    .faqbot-msg { padding: 10px 14px; border-radius: 14px; max-width: 82%; word-wrap: break-word; font-size: 14px; line-height: 1.45; white-space: pre-wrap; }
    .faqbot-msg-bot { background: white; color: #111827; border: 1px solid #e5e7eb; align-self: flex-start; border-bottom-left-radius: 4px; }
    .faqbot-msg-user { background: #2563eb; color: white; align-self: flex-end; border-bottom-right-radius: 4px; }
    .faqbot-typing { display: flex; gap: 4px; padding: 12px 14px; background: white; border: 1px solid #e5e7eb; align-self: flex-start; border-radius: 14px; border-bottom-left-radius: 4px; }
    .faqbot-typing span { width: 7px; height: 7px; background: #9ca3af; border-radius: 50%; animation: faqbot-bounce 1.4s infinite; }
    .faqbot-typing span:nth-child(2) { animation-delay: .18s; }
    .faqbot-typing span:nth-child(3) { animation-delay: .36s; }
    @keyframes faqbot-bounce { 0%, 80%, 100% { opacity: .3; transform: scale(.8); } 40% { opacity: 1; transform: scale(1); } }
    .faqbot-input-form { display: flex; padding: 12px; border-top: 1px solid #e5e7eb; gap: 8px; background: white; }
    .faqbot-input { flex: 1; border: 1px solid #d1d5db; border-radius: 8px; padding: 9px 12px; font-size: 14px; outline: none; font-family: inherit; color: #111827; }
    .faqbot-input:focus { border-color: #2563eb; box-shadow: 0 0 0 3px rgba(37,99,235,.15); }
    .faqbot-send { background: #2563eb; color: white; border: none; border-radius: 8px; padding: 9px 18px; font-weight: 500; cursor: pointer; font-family: inherit; font-size: 14px; }
    .faqbot-send:hover { background: #1d4ed8; }
    .faqbot-send:disabled { background: #93c5fd; cursor: not-allowed; }
    .faqbot-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 2px; align-self: stretch; }
    .faqbot-chip { background: #fff; border: 1px solid #c7d2fe; color: #2563eb; border-radius: 100px; padding: 7px 12px; font-size: 12.5px; line-height: 1.2; cursor: pointer; font-family: inherit; text-align: left; transition: background .15s, border-color .15s; }
    .faqbot-chip:hover { background: #eef2ff; border-color: #2563eb; }
    .faqbot-chip:disabled { opacity: .5; cursor: default; }
    .faqbot-footer { padding: 6px 12px; text-align: center; font-size: 11px; color: #9ca3af; background: white; border-top: 1px solid #f3f4f6; }
    @media (max-width: 480px) {
      .faqbot-panel { bottom: 0; right: 0; width: 100%; height: 100%; max-height: 100%; border-radius: 0; }
    }
  `;

  const styleEl = document.createElement('style');
  styleEl.textContent = styles;
  document.head.appendChild(styleEl);

  const btn = document.createElement('button');
  btn.className = 'faqbot-btn';
  btn.setAttribute('aria-label', 'Open chat');
  btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>';
  document.body.appendChild(btn);

  const panel = document.createElement('div');
  panel.className = 'faqbot-panel';
  panel.innerHTML = [
    '<div class="faqbot-header">',
    '  <span class="faqbot-header-name">Loading…</span>',
    '  <div class="faqbot-actions">',
    '    <button class="faqbot-icon faqbot-download" aria-label="Download chat as PDF" title="Download chat as PDF">',
    '      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/></svg>',
    '    </button>',
    '    <button class="faqbot-close" aria-label="Close chat">×</button>',
    '  </div>',
    '</div>',
    '<div class="faqbot-messages" role="log" aria-live="polite"></div>',
    '<form class="faqbot-input-form">',
    '  <input type="text" class="faqbot-input" placeholder="Ask anything…" autocomplete="off" maxlength="1000">',
    '  <button type="submit" class="faqbot-send">Send</button>',
    '</form>'
  ].join('');
  document.body.appendChild(panel);

  const headerName = panel.querySelector('.faqbot-header-name');
  const messages = panel.querySelector('.faqbot-messages');
  const form = panel.querySelector('.faqbot-input-form');
  const input = panel.querySelector('.faqbot-input');
  const sendBtn = panel.querySelector('.faqbot-send');

  let configLoaded = false;
  let botName = 'Assistant';
  const transcript = [];

  function nowTime() {
    return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  function addMessage(role, text) {
    const m = document.createElement('div');
    m.className = 'faqbot-msg faqbot-msg-' + role;
    m.textContent = text;
    messages.appendChild(m);
    messages.scrollTop = messages.scrollHeight;
    transcript.push({ role: role, text: text, time: nowTime() });
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  function downloadTranscript() {
    if (transcript.length === 0) {
      alert('No messages to download yet.');
      return;
    }
    const rows = transcript.map(function (m) {
      const who = m.role === 'user' ? 'You' : botName;
      const cls = m.role === 'user' ? 'u' : 'b';
      return '<div class="r ' + cls + '"><div class="bub"><div class="who">' +
        escapeHtml(who) + '</div><div class="tx">' + escapeHtml(m.text) +
        '</div><div class="ts">' + escapeHtml(m.time) + '</div></div></div>';
    }).join('');
    const exported = new Date().toLocaleString();
    const html =
      '<!doctype html><html><head><meta charset="utf-8">' +
      '<title>Chat with ' + escapeHtml(botName) + '</title><style>' +
      '*{box-sizing:border-box}' +
      'body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;color:#111827;margin:0;background:#fff;padding:32px 28px 48px;max-width:720px;}' +
      '.hd{border-bottom:2px solid #2563eb;padding-bottom:14px;margin-bottom:22px;}' +
      '.hd h1{font-size:20px;margin:0 0 4px;color:#1e3a8a;}' +
      '.hd p{margin:0;font-size:12px;color:#6b7280;}' +
      '.r{display:flex;margin:10px 0;}' +
      '.r.u{justify-content:flex-end;}' +
      '.bub{max-width:78%;padding:10px 14px;border-radius:14px;font-size:13.5px;line-height:1.5;white-space:pre-wrap;word-wrap:break-word;}' +
      '.r.b .bub{background:#f3f4f6;border:1px solid #e5e7eb;border-bottom-left-radius:4px;}' +
      '.r.u .bub{background:#2563eb;color:#fff;border-bottom-right-radius:4px;}' +
      '.who{font-size:10.5px;font-weight:700;opacity:.7;margin-bottom:3px;}' +
      '.ts{font-size:9.5px;opacity:.55;margin-top:5px;text-align:right;}' +
      '.ft{margin-top:30px;padding-top:14px;border-top:1px solid #eee;font-size:11px;color:#9ca3af;text-align:center;}' +
      '@media print{body{padding:0;}.r{break-inside:avoid;}}' +
      '</style></head><body>' +
      '<div class="hd"><h1>Conversation with ' + escapeHtml(botName) + '</h1>' +
      '<p>Exported ' + escapeHtml(exported) + '</p></div>' +
      rows +
      '<div class="ft">Generated by the FAQ Assistant — choose “Save as PDF” in the print dialog.</div>' +
      '<scr' + 'ipt>window.onload=function(){setTimeout(function(){window.print();},250);};</scr' + 'ipt>' +
      '</body></html>';
    const w = window.open('', '_blank');
    if (!w) {
      alert('Please allow pop-ups for this site to download the chat.');
      return;
    }
    w.document.open();
    w.document.write(html);
    w.document.close();
  }

  function showTyping() {
    const t = document.createElement('div');
    t.className = 'faqbot-typing';
    t.id = 'faqbot-typing-indicator';
    t.innerHTML = '<span></span><span></span><span></span>';
    messages.appendChild(t);
    messages.scrollTop = messages.scrollHeight;
  }

  function hideTyping() {
    const t = document.getElementById('faqbot-typing-indicator');
    if (t) t.remove();
  }

  function removeChips() {
    const c = messages.querySelector('.faqbot-chips');
    if (c) c.remove();
  }

  function renderChips(list) {
    removeChips();
    if (!list || !list.length) return;
    const wrap = document.createElement('div');
    wrap.className = 'faqbot-chips';
    list.forEach(function (q) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'faqbot-chip';
      b.textContent = q;
      b.addEventListener('click', function () { sendText(q); });
      wrap.appendChild(b);
    });
    messages.appendChild(wrap);
    messages.scrollTop = messages.scrollHeight;
  }

  async function loadConfig() {
    try {
      const res = await fetch(API_BASE + '/widget/config');
      const cfg = await res.json();
      botName = cfg.bot_name || 'Assistant';
      headerName.textContent = botName;
      if (messages.children.length === 0) {
        addMessage('bot', cfg.greeting || ('Hi! I\'m ' + (cfg.bot_name || 'your assistant') + '. How can I help?'));
        renderChips(cfg.suggestions);
      }
      configLoaded = true;
    } catch (err) {
      headerName.textContent = 'Assistant';
      if (messages.children.length === 0) addMessage('bot', 'Hi! How can I help?');
    }
  }

  btn.addEventListener('click', () => {
    panel.classList.add('open');
    if (!configLoaded) loadConfig();
    setTimeout(() => input.focus(), 100);
  });
  panel.querySelector('.faqbot-close').addEventListener('click', () => panel.classList.remove('open'));
  panel.querySelector('.faqbot-download').addEventListener('click', downloadTranscript);

  async function sendText(text) {
    text = (text || '').trim();
    if (!text) return;
    removeChips();
    input.value = '';
    sendBtn.disabled = true;
    addMessage('user', text);
    showTyping();
    try {
      const res = await fetch(API_BASE + '/widget/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, text: text }),
      });
      const data = await res.json();
      hideTyping();
      addMessage('bot', data.reply || 'Sorry, something went wrong. Please try again.');
      renderChips(data.followups);
    } catch (err) {
      hideTyping();
      addMessage('bot', 'Network error — please try again.');
    } finally {
      sendBtn.disabled = false;
      input.focus();
    }
  }

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    sendText(input.value);
  });
})();
