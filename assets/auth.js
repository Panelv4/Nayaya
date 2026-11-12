/* NYAYA-RAC — shared session + UI helpers (injected into every page by the server).
 *
 * WHY THIS FILE IS DEFENSIVE
 * --------------------------
 * The portal is often viewed inside a cross-origin preview iframe, where a
 * document may have NO usable session channel at all:
 *   • the session cookie is third-party and gets dropped by the browser,
 *   • localStorage / sessionStorage throw or are partitioned per top-level site,
 *   • a full page load is the only thing that reliably keeps working.
 *
 * The session therefore travels through FIVE complementary channels, and every
 * page navigation re-injects whichever one is available:
 *   1. Authorization: Bearer <token> on every fetch (primary),
 *   2. ?st=<token> relay — now attached to ALL internal links and form targets,
 *      because a plain <a href="/cases"> otherwise loses the token entirely,
 *   3. the non-HttpOnly relay cookie (SameSite=Lax: survives top-level
 *      navigation, readable by JS for bootstrap),
 *   4. localStorage / sessionStorage, when the context allows them,
 *   5. window.name — survives navigation and reload even with an opaque origin.
 *
 * Every page boots through apiFetch('/api/session'), never straight to a 401,
 * and re-seeds storage + cookies whenever the server hands the token back.
 */
const TOK_KEY = 'nyaya_token';

/* ------------------------------------------------------------------ storage */
/* NOTE: reading window.localStorage can itself throw (blocked / partitioned /
 * sandboxed iframe). The access must be guarded, not just the getItem call. */
function _ls() { try { return window.localStorage || null; } catch (e) { return null; } }
function _ss() { try { return window.sessionStorage || null; } catch (e) { return null; } }
function _safeGet(store) {
  if (!store) return null;
  try {
    const v = store.getItem(TOK_KEY);
    return v || null;
  } catch (e) { return null; }
}
function _safeSet(store, v) {
  if (!store) return false;
  try { store.setItem(TOK_KEY, v); return true; } catch (e) { return false; }
}
function _safeDel(store) {
  if (!store) return;
  try { store.removeItem(TOK_KEY); } catch (e) { /* ignore */ }
}

function storeToken(t) {
  if (!t) return;
  window.__tok = t;
  setNameToken(t);
  _safeSet(_ls(), t);
  _safeSet(_ss(), t);
}
function clearToken() {
  window.__tok = null;
  setNameToken(null);
  _safeDel(_ls());
  _safeDel(_ss());
}

/* Read the relay cookie without touching document.cookie if it is blocked. */
function relayCookieToken() {
  try {
    const m = document.cookie.match(/(?:^|;\s*)nyaya_relay=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : null;
  } catch (e) { return null; }
}

/* The window.name channel: the ONE per-frame store that survives a full page
 * load even when the document has an opaque origin (sandboxed iframe), cookies
 * are blocked and web storage throws. It is namespaced and scrubbed on logout. */
function nameToken() {
  try {
    const n = String(window.name || '');
    if (n.indexOf('nyaya:') !== 0) return null;
    const t = n.slice(6);
    return t || null;
  } catch (e) { return null; }
}
function setNameToken(t) {
  try { window.name = t ? 'nyaya:' + t : ''; } catch (e) { /* ignore */ }
}

/* The ?st= relay.
 *
 * The token is deliberately LEFT in the address bar. Stripping it would break the
 * one case that has no other channel at all: reload / back / forward inside a
 * sandboxed iframe where cookies are third-party (dropped) and web storage is
 * blocked. Responses are served with `Referrer-Policy: no-referrer`, so the
 * token is never leaked to a third party, and every link re-sets (never appends)
 * the parameter, so the query cannot grow. */
function tokenFromUrl() {
  try {
    return new URL(location.href).searchParams.get('st') || null;
  } catch (e) { return null; }
}

function getToken() {
  if (window.__tok) return window.__tok;
  const fromUrl = tokenFromUrl();
  if (fromUrl) { storeToken(fromUrl); return fromUrl; }
  const fromLocal = _safeGet(_ls());
  if (fromLocal) { window.__tok = fromLocal; return fromLocal; }
  const fromSession = _safeGet(_ss());
  if (fromSession) { window.__tok = fromSession; return fromSession; }
  const fromCookie = relayCookieToken();
  if (fromCookie) { window.__tok = fromCookie; return fromCookie; }
  const fromName = nameToken();
  if (fromName) { window.__tok = fromName; return fromName; }
  return null;
}

/* --------------------------------------------------------------- navigation
 * Internal links must carry the session when no cookie/storage channel is
 * available. addToken() is the single place that decides.
 */
function addToken(url) {
  let t = null;
  try { t = getToken(); } catch (e) { t = null; }
  if (!t) return url;
  try {
    const u = new URL(url, location.href);
    if (u.origin !== location.origin) return url;      // never leak across origins
    if (u.pathname.startsWith('/api/') || u.pathname.startsWith('/assets/')) return url;
    u.searchParams.set('st', t);
    return u.pathname + '?' + u.searchParams.toString() + u.hash;
  } catch (e) { return url; }
}

function go(url) { location.href = addToken(url); }
window.go = go;

/* Delegated so links injected later (tables, admin nav) are covered too. */
function installLinkRelay() {
  if (window.__relayInstalled) return;
  window.__relayInstalled = true;
  document.addEventListener('click', (ev) => {
    const a = ev.target.closest && ev.target.closest('a[href]');
    if (!a) return;
    if (a.target === '_blank' || a.hasAttribute('download') || ev.metaKey || ev.ctrlKey || ev.shiftKey) return;
    const href = a.getAttribute('href') || '';
    if (!href || href.startsWith('#') || /^(mailto|tel|javascript):/i.test(href)) return;
    const target = addToken(a.href);
    if (target && target !== a.href) a.setAttribute('href', target);
    /* let the browser follow the patched href */
  }, true);
}

/* --------------------------------------------------------------- fetch */
function authHeaders(h) {
  h = h || {};
  const t = getToken();
  if (t) h['Authorization'] = 'Bearer ' + t;
  return h;
}
async function authFetch(url, opts) {
  opts = opts || {};
  opts.headers = authHeaders(opts.headers);
  opts.credentials = 'include';
  return fetch(url, opts);
}

/* --------------------------------------------------------------- session */
let _session = null;

/* Boot the page: restore/repair the session, then report who we are. */
async function bootstrapSession(force) {
  if (_session && !force) return _session;
  let t = null;
  try { t = getToken(); } catch (e) { t = null; }
  const headers = t ? { 'Authorization': 'Bearer ' + t } : {};
  try {
    const r = await fetch('/api/session', { headers, credentials: 'include' });
    const j = await r.json();
    if (j && j.authenticated) {
      if (j.token) storeToken(j.token);           // re-seed whatever works here
      else if (t) storeToken(t);                  // else re-seed with what we used
      _session = j.user;
      return _session;
    }
  } catch (e) { /* fall through to the legacy check */ }
  _session = null;
  return null;
}

function goLogin(next) {
  const target = next || (location.pathname + location.search);
  let t = null;
  try { t = getToken(); } catch (e) { t = null; }
  let url = '/login?next=' + encodeURIComponent(target);
  if (t) url += '&st=' + encodeURIComponent(t);     // keep the branch alive
  location.href = url;
}
window.goLogin = goLogin;

async function requireAuth() {
  const s = await bootstrapSession();
  if (s) return s;
  /* Last attempt with the classic endpoint (covers odd cookie-only setups). */
  try {
    const r = await authFetch('/api/me');
    if (r.ok) { _session = await r.json(); return _session; }
  } catch (e) { /* ignore */ }
  goLogin();
  throw new Error('auth');
}

async function requireAdmin() {
  const me = await requireAuth();
  if (!me.is_admin) {
    document.body.innerHTML = '<div style="max-width:640px;margin:80px auto;padding:24px;text-align:center;'
      + 'font-family:ui-sans-serif,sans-serif"><h1>403 — Administrators only</h1>'
      + '<p style="color:#6b7280">This area of NYAYA-RAC is restricted to administrators.</p>'
      + '<p><a href="/dashboard"><svg class="ic sm" aria-hidden="true"><use href="#i-arrow-left"></use></svg>'
      + ' Back to dashboard</a></p></div>';
    throw new Error('not-admin');
  }
  return me;
}

async function doLogout() {
  try { await authFetch('/api/logout', { method: 'POST' }); } catch (e) { /* ignore */ }
  clearToken();
  _session = null;
  location.href = '/';
}

/* After login: make sure cookies exist too, then hand the token to the target. */
async function proceedWithToken(token) {
  try { storeToken(token); } catch (e) { window.__tok = token; }
  try { await fetch('/api/renew', { method: 'POST', headers: authHeaders(), credentials: 'include' }); }
  catch (e) { /* cookies unavailable — the ?st= relay covers us */ }
  let nx = new URLSearchParams(location.search).get('next');
  if (!nx || !nx.startsWith('/') || nx.startsWith('//')) nx = '/dashboard';
  let dest;
  try {
    const u = new URL(nx, location.origin);
    u.searchParams.set('st', token);           // set, never append
    dest = u.pathname + '?' + u.searchParams.toString();
  } catch (e) { dest = '/dashboard?st=' + encodeURIComponent(token); }
  location.href = dest;
}

/* ---------------------------------------------------------------- icons
 * Inline SVG sprite, injected once per document so pages can use
 * <svg class="ic" aria-hidden="true"><use href="#i-shield"></use></svg>.
 * Keeps every glyph vector-only (no emoji) and works in a sandboxed preview.
 */
/* ------------------------------------------------------------------- i18n
 * The header chip ("हिन्दी / English") was decoration: clicking it did nothing.
 * This is a small dictionary layer, not a translation of the legal record —
 * statute names, engine output and case data stay in the language the server
 * produced them. It translates the interface chrome: navigation, buttons,
 * labels and the static help text marked with data-i18n.
 *
 * Scope is deliberately honest: anything the engine generated is untouched, and
 * `data-i18n-skip` marks regions that must never be machine-swapped.
 */
const NYAYA_I18N = {
  hi: {
    /* nav + chrome */
    'Submit a report': 'रिपोर्ट दर्ज करें',
    'My cases': 'मेरे मामले',
    'Public register': 'सार्वजनिक रजिस्टर',
    'Dashboard': 'डैशबोर्ड',
    'Statutory database': 'वैधानिक डेटाबेस',
    'Engine analysis': 'इंजन विश्लेषण',
    'Admin': 'प्रशासन',
    'Legal KB': 'विधि ज्ञानकोष',
    'Logout': 'लॉग आउट',
    'Login': 'लॉग इन',
    'Home': 'मुख्य पृष्ठ',
    'Accessibility': 'सुगम्यता',
    'Search': 'खोजें',
    'Clear': 'साफ़ करें',
    'Next': 'आगे',
    'Previous': 'पीछे',
    'Download': 'डाउनलोड',
    /* page headings */
    'My cases.': 'मेरे मामले।',
    'Welcome back': 'पुनः स्वागत है',
    'Create your account': 'अपना खाता बनाएँ',
    'Reset your password': 'अपना पासवर्ड रीसेट करें',
    'Choose a new password': 'नया पासवर्ड चुनें',
    'Disclosed cases': 'प्रकट किए गए मामले',
    /* form labels used across pages */
    'Full name': 'पूरा नाम',
    'Email': 'ईमेल',
    'Password': 'पासवर्ड',
    'Confirm password': 'पासवर्ड की पुष्टि करें',
    'New password': 'नया पासवर्ड',
    'Confirm new password': 'नए पासवर्ड की पुष्टि करें',
    'Incident date': 'घटना की तारीख',
    'Incident end date': 'घटना समाप्ति तिथि',
    'Location': 'स्थान',
    'Domain': 'श्रेणी',
    'Narrative': 'विवरण',
    'Are you under 18?': 'क्या आप 18 वर्ष से कम हैं?',
    'Woman or girl?': 'महिला या बालिका?',
    'Sexual offence?': 'यौन अपराध?',
    'Lawyer / legal aid?': 'वकील / विधिक सहायता?',
    'Section cited': 'उद्धृत धारा',
    'Statute': 'अधिनियम',
    /* buttons */
    'Send reset link': 'रीसेट लिंक भेजें',
    'Update password': 'पासवर्ड अपडेट करें',
    'Create account': 'खाता बनाएँ',
    'Save correction & re-evaluate': 'सुधार सहेजें और पुनर्मूल्यांकन करें',
    'Request disclosure': 'प्रकटीकरण का अनुरोध करें',
    'Forgot your password?': 'पासवर्ड भूल गए?',
    'Back to login': 'लॉग इन पर लौटें',
    'Details': 'विवरण',
    'Reminder:': 'स्मरण:',
  }
};

const LANG_KEY = 'nyaya_lang';

function getLang() {
  try {
    const store = _ls();
    const v = store ? store.getItem(LANG_KEY) : null;
    return v === 'hi' ? 'hi' : 'en';
  } catch (e) { return 'en'; }
}

function setLang(lang) {
  const l = lang === 'hi' ? 'hi' : 'en';
  try { const store = _ls(); if (store) { store.setItem(LANG_KEY, l); } }
  catch (e) { /* storage blocked: the toggle still works for this page view */ }
  applyLang(l);
}

/* Swap text in place, remembering the English original so toggling back is
 * lossless even though we never touched the markup. */
function applyLang(lang) {
  const dict = NYAYA_I18N[lang] || null;
  document.documentElement.lang = lang === 'hi' ? 'hi' : 'en';
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
    acceptNode: function (n) {
      var p = n.parentElement;
      if (!p) { return NodeFilter.FILTER_REJECT; }
      if (p.closest('[data-i18n-skip]')) { return NodeFilter.FILTER_REJECT; }
      if (p.tagName === 'SCRIPT' || p.tagName === 'STYLE') { return NodeFilter.FILTER_REJECT; }
      return n.nodeValue && n.nodeValue.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
    }
  });
  const nodes = [];
  while (walker.nextNode()) { nodes.push(walker.currentNode); }
  nodes.forEach(function (n) {
    if (n.__en == null) { n.__en = n.nodeValue; }
    const raw = n.__en;
    const key = raw.trim();
    const target = dict && dict[key];
    if (target) {
      const lead = raw.match(/^\s*/)[0];
      const trail = raw.match(/\s*$/)[0];
      n.nodeValue = lead + target + trail;
    } else {
      n.nodeValue = raw;     // back to English
    }
  });
  /* attributes too (placeholders, aria-labels, input buttons) */
  document.querySelectorAll('input[placeholder], [aria-label], input[type=submit]').forEach(function (el) {
    if (el.closest('[data-i18n-skip]')) { return; }
    ['placeholder', 'aria-label', 'value'].forEach(function (attr) {
      if (!el.hasAttribute(attr)) { return; }
      const storeAttr = '__i18n_' + attr.replace('-', '');
      if (el[storeAttr] == null) { el[storeAttr] = el.getAttribute(attr); }
      const raw = el[storeAttr];
      const target = dict && dict[raw.trim()];
      el.setAttribute(attr, target || raw);
    });
  });
  document.querySelectorAll('[data-lang-label]').forEach(function (el) {
    el.textContent = lang === 'hi' ? 'हिन्दी' : 'हिन्दी / English';
    el.title = lang === 'hi' ? 'Switch to English' : 'हिन्दी में देखें';
  });
  document.documentElement.setAttribute('data-lang', lang);
}

/* Every page ships the same inert chip; turn it into the control. */
function installLangToggle() {
  document.querySelectorAll('.utility .lang').forEach(function (chip) {
    chip.setAttribute('data-lang-label', '');
    chip.setAttribute('role', 'button');
    chip.setAttribute('tabindex', '0');
    chip.style.cursor = 'pointer';
    chip.style.textDecoration = 'underline';
    chip.style.textUnderlineOffset = '2px';
    chip.addEventListener('click', function () { setLang(getLang() === 'hi' ? 'en' : 'hi'); });
    chip.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setLang(getLang() === 'hi' ? 'en' : 'hi'); }
    });
  });
  applyLang(getLang());
}

window.NYAYA_I18N = NYAYA_I18N;
window.getLang = getLang;
window.setLang = setLang;
window.applyLang = applyLang;
window.NYAYA_SPRITE = `{{SPRITE}}`;
/* The toast element is styled as `#toast{opacity:0;display:none}` and only
 * becomes visible under `#toast.show`. Pages used to just set display:block,
 * which left it fully transparent — every notification was invisible. Toggle
 * the class (and the display) together, and always hide on the timeout. */
function toast(msg, ms) {
  var t = document.getElementById('toast');
  if (!t) { return; }
  ms = ms || 3600;
  t.textContent = msg;
  t.classList.add('show');
  t.style.display = 'flex';
  clearTimeout(t._h);
  t._h = setTimeout(function () {
    t.classList.remove('show');
    t.style.display = 'none';
  }, ms);
}
window.toast = toast;

function injectIcons() {
  if (document.getElementById('nyaya-sprite-host')) return;
  const host = document.createElement('div');
  host.id = 'nyaya-sprite-host';
  host.setAttribute('aria-hidden', 'true');
  host.style.cssText = 'position:absolute;width:0;height:0;overflow:hidden';
  host.innerHTML = window.NYAYA_SPRITE || '';
  document.body.insertBefore(host, document.body.firstChild);
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', injectIcons);
else injectIcons();
installLinkRelay();
/* Turn the header language chip into a working toggle once the DOM is ready. */
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', installLangToggle);
else installLangToggle();

/* ---------------------------------------------------------------- DigiLocker panel
 * One shared renderer for the identity-verification flow so the dashboard and the
 * intake page cannot drift apart. Everything is vector + CSS animation; the panel
 * always states that the issuer response is simulated.
 */
const DLPanel = (function () {
  const STEPS = [
    ['authorise', 'Authorise'], ['consent', 'Consent'], ['callback', 'Callback'],
    ['verify', 'Verify'], ['attested', 'Attested']
  ];
  function esc(s) { return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
  function ic(name, cls) { return '<svg class="ic ' + (cls || '') + '" aria-hidden="true"><use href="#i-' + name + '"></use></svg>'; }
  function stepper(active) {
    const idx = Math.max(0, STEPS.findIndex(s => s[0] === active));
    return '<div class="dl-steps">' + STEPS.map((s, i) => {
      const state = i < idx ? 'done' : (i === idx ? 'active' : '');
      return '<div class="dl-step ' + state + '"><span class="sd">' + (i < idx ? ic('check-circle', 'sm') : (i + 1)) + '</span>' + esc(s[1]) + '</div>'
        + (i < STEPS.length - 1 ? '<span class="bar"></span>' : '');
    }).join('') + '</div>';
  }
  function badge(st) {
    const m = { LINKED: 'b-green', EXPIRED: 'b-amber', PENDING: 'b-blue', FAILED: 'b-red', REVOKED: 'b-gray', NOT_LINKED: 'b-amber' };
    return '<span class="badge ' + (m[st] || 'b-gray') + '" id="dl-badge">' + esc((st || '').replace('_', ' ')) + '</span>';
  }
  function docCard(st) {
    const d = st.document || {};
    return '<div class="dl-consent" style="background:#fff;border-color:var(--green-line)">'
      + '<h4>' + ic('seal', 'sm') + ' Verified identity artefact</h4>'
      + '<div class="kv"><b>Holder:</b> ' + esc(d.name || '—') + ' &nbsp;·&nbsp; <b>Date of birth:</b> ' + esc(d.dob || '—') + '</div>'
      + '<div class="kv"><b>Issuer:</b> ' + esc(st.issuer || d.issuer || '—') + ' &nbsp;·&nbsp; <b>Reference:</b> <span class="mono">' + esc(st.issuer_ref_masked || d.issuer_ref_masked || '••••') + '</span></div>'
      + '<div class="kv"><b>Verified:</b> ' + esc((st.verified_at || '').slice(0, 10)) + ' &nbsp;·&nbsp; <b>Valid till:</b> ' + esc(st.expires_on || '—') + '</div>'
      + '<div class="kv"><b>Artefact id:</b> <span class="mono">' + esc(st.artefact_id || '—') + '</span></div>'
      + '<div class="kv"><b>Seal (sha-256):</b> <span class="mono">' + esc((st.doc_sha256 || '').slice(0, 32)) + '…</span></div>'
      + '<div class="btn-row"><button class="btn secondary small" onclick="DLPanel.integrity(this)">' + ic('shield', 'sm') + ' Check integrity</button>'
      + '<button class="btn secondary small" onclick="DLPanel.revoke()">' + ic('x-circle', 'sm') + ' Withdraw verification</button></div>'
      + '<div id="dl-integrity" class="small" style="margin-top:8px"></div>'
      + '</div>';
  }
  function consentScreen(req) {
    const rid = req.request_id || '';
    return '<div class="dl-consent">'
      + '<h4>' + ic('idcard', 'sm') + ' DigiLocker consent · request ' + esc(rid.slice(0, 12)) + '…</h4>'
      + '<div class="small">Purpose: ' + esc(req.purpose || 'Identity verification') + '</div>'
      + '<div class="small">Validity: 30 minutes · PKCE S256 · one-time code</div>'
      + '<div class="small" style="margin-top:6px"><b>Requested access</b></div>'
      + '<ul>' + (req.scope || '').split(' ').filter(Boolean).map(s => '<li class="mono">' + esc(s) + '</li>').join('') + '</ul>'
      + '<div class="dl-doc">' + ic('doc') + '<div><div class="dn">Aadhaar / issued identity document</div>'
      + '<div class="dc">Name, date of birth, gender, photograph flag · issuer attestation</div></div></div>'
      + '<div class="banner amber" style="margin:12px 0 0"><svg class="ic"><use href="#i-alert"></use></svg><div class="b-body">'
      + '<b>Simulated consent screen</b>No request reaches digilocker.gov.in. Approving exercises the real flow’s '
      + 'state machine locally; the resulting artefact is watermarked as simulated.</div></div>'
      + '<div class="btn-row"><button class="btn success small" data-req="' + esc(rid) + '" onclick="DLPanel.approve(this)">' + ic('check-circle', 'sm') + ' Approve &amp; fetch</button>'
      + '<button class="btn secondary small" data-req="' + esc(rid) + '" onclick="DLPanel.deny(this)">' + ic('x-circle', 'sm') + ' Deny</button></div>'
      + '<div id="dl-log" class="small mono" style="margin-top:8px"></div>'
      + '</div>';
  }
  function render(el, st, opts) {
    opts = opts || {};
    el = typeof el === 'string' ? document.getElementById(el) : el;
    if (!el) return;
    el._st = st;
    const status = st.status || 'NOT_LINKED';
    const linked = status === 'LINKED';
    const pending = st.pending;
    let body;
    if (linked) {
      body = stepper('attested') + docCard(st);
    } else if (status === 'EXPIRED') {
      body = stepper('verify') + '<div class="banner amber" style="margin-top:10px">' + ic('clock')
        + '<div class="b-body"><b>Verification lapsed</b>The artefact expired on ' + esc(st.expires_on || '—')
        + '. Start a fresh consent request to re-verify.</div></div>'
        + '<div class="btn-row"><button class="btn primary small" onclick="DLPanel.start(this)">' + ic('refresh', 'sm') + ' Re-verify</button></div>';
    } else if (pending) {
      body = stepper(pending.status === 'CONSENT_GIVEN' ? 'callback' : 'consent')
        + '<div class="small" style="margin:8px 0">Consent request <span class="mono">' + esc(pending.request_id) + '</span> open until ' + esc((pending.expires_at || '').slice(0, 19).replace('T', ' ')) + ' UTC.</div>'
        + consentScreen(pending);
    } else {
      body = stepper('authorise')
        + '<p class="small" style="margin:8px 0 0">Verifying identity raises the evidential weight of a report and '
        + 'reduces duplicate or malicious filings. It is never a precondition for filing: an unverified report is '
        + 'accepted and marked as unverified for the registry.</p>';
      if (opts.compact !== true) {
        body += '<div class="dl-doc">' + ic('doc') + '<div><div class="dn">What is fetched</div>'
          + '<div class="dc">Name, date of birth, gender and a photograph flag from an issuer-attested document. '
          + 'No document copy is stored on the case file; only a hash-sealed verification artefact.</div></div></div>';
      }
      body += '<div class="btn-row"><button class="btn primary small" onclick="DLPanel.start(this)">' + ic('idcard', 'sm') + ' Start DigiLocker verification</button>'
        + '<span class="small">' + esc((st.quota && st.quota.remaining != null) ? (st.quota.remaining + ' of ' + st.quota.limit + ' requests left today') : '') + '</span></div>';
    }
    const lastEvent = st.last_event
      ? '<div class="small" style="margin-top:8px">Last event: <span class="mono">' + esc(st.last_event.event) + '</span>'
      + (st.last_event.reason_code ? ' · ' + esc(st.last_event.reason_code) : '') + '</div>' : '';
    el.innerHTML = '<div class="dl-card ' + (linked ? 'is-linked' : (pending ? 'is-pending' : '')) + '">'
      + '<div class="card-head" style="margin-bottom:10px;border:0;padding:0">'
      + '<h3>' + ic('idcard') + ' DigiLocker identity verification ' + badge(status)
      + ' <span class="sim-tag" title="No request leaves this machine">simulated</span></h3>'
      + '<span class="small">model ' + (window.__dlVersion || 'digilocker-model-1.0.0') + '</span></div>'
      + body + lastEvent
      + '<div class="disclaimer" style="margin-top:12px">' + ic('shield')
      + '<div><b>Honesty note.</b> This portal implements the DigiLocker consent-and-artefact flow as a calibrated '
      + 'model: the states, scopes, PKCE challenge, single-use codes, consent expiry and issuer allow-list match the '
      + 'real integration, but the issuer response is generated locally and watermarked <b>simulated</b>. '
      + 'No data is sent to or received from digilocker.gov.in.</div></div>'
      + '</div>';
  }
  async function load(el, opts) {
    el = typeof el === 'string' ? document.getElementById(el) : el;
    if (!el) return null;
    try {
      const r = await authFetch('/api/digilocker/status');
      if (!r.ok) throw new Error('status unavailable');
      const st = await r.json();
      window.__dlVersion = st.implementation;
      render(el, st, opts);
      return st;
    } catch (e) {
      el.innerHTML = '<div class="dl-card"><div class="small">DigiLocker status could not be loaded.</div></div>';
      return null;
    }
  }
  function busy(btn, on, label) {
    if (!btn) return;
    btn.disabled = !!on;
    if (on) {
      btn._html = btn.innerHTML;
      btn.innerHTML = ic('spinner') + ' ' + (label || 'Working…');
      const s = btn.querySelector('svg');
      if (s) s.classList.add('ic-spin');
    } else if (btn._html) { btn.innerHTML = btn._html; }
  }
  async function start(btn) {
    busy(btn, true, 'Opening consent…');
    try {
      const r = await authFetch('/api/digilocker/consent', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || 'Could not open a consent request.');
      await reloadAll();
    } catch (e) { busy(btn, false); alert(e.message); }
  }
  function reqId(el) {
    const btn = el.closest('[data-req]');
    if (btn) return btn.getAttribute('data-req');
    const st = (document.getElementById('dl-panel') || {})._st || {};
    return (st.pending && st.pending.request_id) || null;
  }
  function reloadAll() { return load(document.getElementById('dl-panel'), { compact: true }); }
  async function approve(btn) {
    const rid = reqId(btn); if (!rid) return;
    busy(btn, true, 'Granting consent…');
    const log = document.getElementById('dl-log');
    try {
      const g = await authFetch('/api/digilocker/grant', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ request_id: rid, consent: true })
      });
      const gj = await g.json();
      if (!g.ok) throw new Error(gj.error || 'Consent failed.');
      if (log) log.innerHTML = 'consent granted · code issued (single use)';
      const c = await authFetch('/api/digilocker/callback', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ request_id: rid, code: gj.code, state: gj.state })
      });
      const cj = await c.json();
      if (log) log.innerHTML += cj.ok ? '<br>artefact attested · sealed' : '<br>rejected: ' + esc(cj.reason_code || '');
      await reloadAll();
    } catch (e) { busy(btn, false); alert(e.message); }
  }
  async function deny(btn) {
    const rid = reqId(btn); if (!rid) return;
    busy(btn, true, 'Withholding consent…');
    try {
      await authFetch('/api/digilocker/grant', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ request_id: rid, consent: false })
      });
      await reloadAll();
    } catch (e) { busy(btn, false); }
  }
  async function integrity(btn) {
    const st = (document.getElementById('dl-panel') || {})._st || {};
    busy(btn, true, 'Checking…');
    try {
      const r = await authFetch('/api/digilocker/verify?artefact=' + encodeURIComponent(st.artefact_id || ''));
      const j = await r.json();
      const out = document.getElementById('dl-integrity');
      if (out) out.innerHTML = j.valid
        ? '<span class="badge b-green">' + ic('shield', 'sm') + ' INTACT</span> seal matches · state ' + esc(j.state)
        : '<span class="badge b-red">' + ic('alert', 'sm') + ' ' + esc(j.integrity || j.state || 'INVALID') + '</span> ' + esc(j.message || '');
    } finally { busy(btn, false); }
  }
  async function revoke() {
    if (!confirm('Withdraw identity verification? Reports already filed keep their recorded state, but future reports will be marked unverified.')) return;
    await authFetch('/api/digilocker/revoke', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: 'withdrawn by account holder' })
    });
    await reloadAll();
  }
  return { load, render, start, approve, deny, integrity, revoke };
})();
window.DLPanel = DLPanel;
