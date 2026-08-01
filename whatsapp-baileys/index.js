/**
 * Minimal WhatsApp -> RAG adapter.
 *
 * A thin Baileys client that forwards each incoming text message to an existing
 * RAG HTTP API (POST {RAG_URL}/widget/chat) and sends the `reply` back to the
 * same chat. No database, no web server, one file. Meant to run long-lived on a
 * VPS with a THROWAWAY WhatsApp number (Baileys is an unofficial client).
 */
require('dotenv').config();

const makeWASocket = require('@whiskeysockets/baileys').default;
const {
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
} = require('@whiskeysockets/baileys');
const qrcode = require('qrcode-terminal');

// ---- config -------------------------------------------------------------
const RAG_URL = (process.env.RAG_URL || '').replace(/\/+$/, '');
const RAG_API_KEY = process.env.RAG_API_KEY || '';
const REQUEST_TIMEOUT_MS = 20000;
const FALLBACK_REPLY =
  "Sorry, I couldn't reach my brain just now — please try again in a moment.";

if (!RAG_URL) {
  console.error('[fatal] RAG_URL is not set. Copy .env.example to .env and fill it in.');
  process.exit(1);
}

// Baileys is chatty on its default (pino) logger; swap in a silent one so our
// own connection logs stay readable. Keeps the dependency list minimal too.
const silentLogger = {
  level: 'silent',
  trace() {}, debug() {}, info() {}, warn() {}, error() {}, fatal() {},
  child() { return silentLogger; },
};

// ---- RAG call -----------------------------------------------------------
async function askRag(sessionId, text) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const res = await fetch(`${RAG_URL}/widget/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': RAG_API_KEY,
      },
      body: JSON.stringify({ session_id: sessionId, text }),
      signal: controller.signal,
    });
    if (!res.ok) throw new Error(`RAG API responded ${res.status}`);
    const data = await res.json();
    const reply = data && typeof data.reply === 'string' ? data.reply.trim() : '';
    return reply || null; // `followups` is intentionally ignored
  } finally {
    clearTimeout(timer);
  }
}

// ---- message parsing ----------------------------------------------------
function extractText(msg) {
  const m = msg.message;
  if (!m) return null;
  // Only plain text: a bare `conversation` or the `extendedTextMessage` (text
  // with a reply/quote or link preview). Everything else (images, audio,
  // stickers, reactions, ...) is ignored per spec.
  return m.conversation || (m.extendedTextMessage && m.extendedTextMessage.text) || null;
}

// ---- socket lifecycle ---------------------------------------------------
async function start() {
  const { state, saveCreds } = await useMultiFileAuthState('auth');
  const { version } = await fetchLatestBaileysVersion();

  const sock = makeWASocket({
    version,
    auth: state,
    logger: silentLogger,
    printQRInTerminal: false, // we render the QR ourselves below
  });

  sock.ev.on('creds.update', saveCreds);

  sock.ev.on('connection.update', (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      console.log('[conn] scan this QR with WhatsApp (Linked Devices) on your THROWAWAY number:');
      qrcode.generate(qr, { small: true });
    }
    if (connection === 'connecting') {
      console.log('[conn] connecting...');
    } else if (connection === 'open') {
      console.log('[conn] connected ✓  listening for messages');
    } else if (connection === 'close') {
      const statusCode = lastDisconnect && lastDisconnect.error
        && lastDisconnect.error.output && lastDisconnect.error.output.statusCode;
      const loggedOut = statusCode === DisconnectReason.loggedOut;
      if (loggedOut) {
        console.log('[conn] closed: logged out. Delete the auth/ folder and restart to re-link.');
      } else {
        console.log(`[conn] closed (code=${statusCode}). Reconnecting...`);
        start();
      }
    }
  });

  sock.ev.on('messages.upsert', async ({ messages, type }) => {
    if (type !== 'notify') return; // ignore history/append syncs
    for (const msg of messages) {
      if (!msg.message || msg.key.fromMe) continue;
      const jid = msg.key.remoteJid;
      if (!jid || jid === 'status@broadcast') continue;

      const text = extractText(msg);
      if (!text) continue;

      console.log(`[msg] ${jid}: ${text}`);
      try {
        const reply = await askRag(jid, text);
        await sock.sendMessage(jid, { text: reply || FALLBACK_REPLY });
      } catch (err) {
        console.error(`[err] RAG call failed for ${jid}: ${err.message}`);
        try {
          await sock.sendMessage(jid, { text: FALLBACK_REPLY });
        } catch (sendErr) {
          console.error(`[err] also failed to send fallback: ${sendErr.message}`);
        }
      }
    }
  });
}

start().catch((err) => {
  console.error('[fatal] startup failed:', err);
  process.exit(1);
});
