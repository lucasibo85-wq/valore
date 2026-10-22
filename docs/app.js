/* Valore – app web. Legge data/app.json e data/results.json generati dal motore. */
'use strict';

// ------------------------------------------------------------------ mercati
const NBA_BASE = ['pts', 'reb', 'ast', 'stl', 'blk', 'fg3m', 'tov'];
const SOC_BASE = ['shots', 'sot', 'fc', 'fs', 'yc', 'rc', 'g', 'a'];
const MARKETS = {
  nba: [
    ['pts', 'Punti', ['pts']], ['reb', 'Rimbalzi', ['reb']], ['ast', 'Assist', ['ast']],
    ['fg3m', 'Triple', ['fg3m']], ['blk', 'Stoppate', ['blk']], ['stl', 'Rubate', ['stl']],
    ['pra', 'P+R+A', ['pts', 'reb', 'ast']], ['pr', 'P+R', ['pts', 'reb']], ['pa', 'P+A', ['pts', 'ast']],
    ['ra', 'R+A', ['reb', 'ast']], ['sb', 'Rub+Stop', ['stl', 'blk']], ['tov', 'Palle perse', ['tov']],
  ],
  soccer: [
    ['shots', 'Tiri', ['shots']], ['sot', 'Tiri in porta', ['sot']], ['fc', 'Falli commessi', ['fc']],
    ['fs', 'Falli subiti', ['fs']], ['card', 'Cartellino', ['yc', 'rc']], ['g', 'Gol', ['g']],
    ['a', 'Assist', ['a']], ['goa', 'Gol o assist', ['g', 'a']], ['ga', 'Gol+Assist (somma)', ['g', 'a']],
  ],
};
MARKETS.nfl = [
  ['pass_yds', 'Yard passate', ['pass_yds']], ['pass_td', 'TD passati', ['pass_td']], ['pass_cmp', 'Passaggi completati', ['pass_cmp']],
  ['pass_att', 'Passaggi tentati', ['pass_att']], ['int', 'Intercetti', ['int']], ['rush_yds', 'Yard corse', ['rush_yds']],
  ['rush_att', 'Corse', ['rush_att']], ['rec', 'Ricezioni', ['rec']], ['rec_yds', 'Yard ricevute', ['rec_yds']],
  ['rr_yds', 'Yard corse+ricevute', ['rush_yds', 'rec_yds']], ['pr_yds', 'Yard passate+corse', ['pass_yds', 'rush_yds']],
  ['td', 'Touchdown (marcatore)', ['rush_td', 'rec_td']],
];
MARKETS.mlb = [
  ['h', 'Valide', ['h']], ['hrr', 'H+R+RBI', ['h', 'r', 'rbi']], ['r', 'Punti segnati', ['r']], ['rbi', 'RBI', ['rbi']],
  ['hr', 'Fuoricampo', ['hr']], ['bb', 'Basi su ball', ['bb']], ['so', 'Strikeout subiti', ['so']],
  ['p_k', 'Strikeout lanciatore', ['p_k']], ['outs', 'Eliminazioni', ['outs']], ['er', 'Punti concessi', ['er']],
  ['p_h', 'Valide concesse', ['p_h']], ['p_bb', 'Basi su ball concesse', ['p_bb']],
];
const REL = { A: 'alta', B: 'media', C: 'bassa' };
const SPORT_LABEL = { nba: 'NBA', soccer: 'Calcio', nfl: 'NFL', mlb: 'MLB', tennis: 'Tennis' };
const PROP_SPORTS = ['nba', 'soccer', 'nfl', 'mlb'];
const DEFAULT_MK = { nba: 'pts', soccer: 'sot', nfl: 'rec_yds', mlb: 'h' };
const BERNOULLI = new Set(['card', 'td', 'hr', 'goa']);
const mkInfo = (sport, m) => MARKETS[sport].find(x => x[0] === m) || MARKETS[sport][0];
const mkLabel = (sport, m) => mkInfo(sport, m)[1];
// posizione delle statistiche base negli array "l" (ultime partite) e nei risultati
const L_OFF = { nba: 3, soccer: 4, nfl: 3, mlb: 3 };
const BASE = {
  nba: NBA_BASE, soccer: SOC_BASE,
  nfl: ['pass_yds', 'pass_td', 'pass_cmp', 'pass_att', 'int', 'rush_yds', 'rush_att', 'rush_td', 'rec', 'rec_yds', 'rec_td', 'tgt'],
  mlb: ['h', 'r', 'rbi', 'hr', 'bb', 'so', 'outs', 'p_k', 'er', 'p_h', 'p_bb'],
};
/** Sport presenti nei dati; withTennis: includi il tennis (solo partite, niente giocatori) */
function availSports(withTennis) {
  const all = ['nba', 'soccer', 'nfl', 'mlb'].concat(withTennis ? ['tennis'] : []);
  return all.filter(s => S.data && S.data[s] && ((S.data[s].players && S.data[s].players.length) || (S.data[s].matches && S.data[s].matches.length) || (S.data[s].games && S.data[s].games.length) || s === 'nba' || s === 'soccer'));
}
const mkOf = sport => (S.market && S.market[sport]) || DEFAULT_MK[sport];
const mkList = (sport, p) => MARKETS[sport].filter(x => !p || (p.mk && p.mk[x[0]]));
const gamesList = sport => sport === 'soccer' ? ((S.data.soccer || {}).matches || []) : ((S.data[sport] || {}).games || []);
const sportCtx = (sport, p) => sport === 'soccer' ? ((S.data.leagues || {})[p.lg] || 'Calcio') : SPORT_LABEL[sport];
/** Esposizione attesa: minuti (NBA, calcio), turni in battuta / eliminazioni (MLB) */
function expInfo(sport, p) {
  if (sport === 'nba') return ['Minuti attesi', p.m.toFixed(1)];
  if (sport === 'soccer') return ['Minuti attesi', p.m + "'"];
  if (sport === 'mlb') return String(p.id).endsWith('p') ? ['Eliminazioni attese', p.m.toFixed(1)] : ['Turni in battuta attesi', p.m.toFixed(1)];
  return null;
}

function marketValue(sport, m, arr, off) {
  const comps = mkInfo(sport, m)[2];
  let v = 0;
  for (const c of comps) v += Number(arr[off + BASE[sport].indexOf(c)] || 0);
  return BERNOULLI.has(m) ? Math.min(v, 1) : v;
}

// ------------------------------------------------------------------ probabilita'
function poissonCdf(k, mu) {
  if (k < 0) return 0;
  if (mu <= 0) return 1;
  let term = Math.exp(-mu), s = term;
  for (let i = 1; i <= k; i++) { term *= mu / i; s += term; }
  return Math.min(1, s);
}
function nbCdf(k, mu, r) {
  if (!r || r <= 0 || r > 1e6) return poissonCdf(k, mu);
  if (k < 0) return 0;
  const p = r / (r + mu);
  let term = Math.exp(r * Math.log(p)), s = term;
  for (let i = 1; i <= k; i++) { term *= (i - 1 + r) / i * (1 - p); s += term; }
  return Math.min(1, s);
}
function nbPmf(k, mu, r) { return nbCdf(k, mu, r) - nbCdf(k - 1, mu, r); }
/** Probabilita' di over, under e rimborso (linee intere) */
function probs(line, mu, r) {
  const L = Number(line);
  if (Number.isInteger(L)) {
    const push = nbPmf(L, mu, r);
    const under = nbCdf(L - 1, mu, r);
    return { over: Math.max(0, 1 - under - push), under, push };
  }
  const under = nbCdf(Math.floor(L), mu, r);
  return { over: Math.max(0, 1 - under), under, push: 0 };
}
function ev(p, odds, push = 0) { return p * odds + push - 1; }
function kelly(p, odds, push = 0) {
  const b = odds - 1;
  if (b <= 0) return 0;
  const q = 1 - p - push;
  return Math.max(0, (b * p - q) / b);
}
const defaultLine = (m, mu) => (BERNOULLI.has(m) || m === 'g' || m === 'a' || m === 'ga') ? 0.5 : Math.max(0.5, Math.floor(mu) + 0.5);

// ------------------------------------------------------------------ stato e archivio
const LS = {
  get(k, d) { try { const v = localStorage.getItem('valore.' + k); return v ? JSON.parse(v) : d; } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem('valore.' + k, JSON.stringify(v)); } catch (e) { /* archivio non disponibile */ } },
};
const S = {
  data: null, results: null, error: null,
  sport: LS.get('sport', 'nba'),
  market: LS.get('market', { nba: 'pts', soccer: 'sot', nfl: 'rec_yds', mlb: 'h' }),
  slipMode: LS.get('slipMode', 'single'), multiStake: null, chTab: 'valore',
  onlyValue: false, search: '', game: '', sort: 'valore',
  bankroll: LS.get('bankroll', 1000),
  kellyFrac: LS.get('kellyFrac', 0.25),
  slip: LS.get('slip', []),
  bets: LS.get('bets', []),
  manual: LS.get('manual', {}),
  roiPeriod: 'all',
};
const save = () => {
  LS.set('sport', S.sport); LS.set('market', S.market); LS.set('bankroll', S.bankroll);
  LS.set('kellyFrac', S.kellyFrac); LS.set('slipMode', S.slipMode); LS.set('slip', S.slip); LS.set('bets', S.bets); LS.set('manual', S.manual);
};

// ------------------------------------------------------------------ utilita'
const $ = sel => document.querySelector(sel);
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const pct = (p, d = 0) => (p * 100).toFixed(d) + '%';
const sgn = (x, d = 1) => (x >= 0 ? '+' : '−') + Math.abs(x * 100).toFixed(d) + '%';
const eur = v => '€ ' + Number(v).toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const num = v => { const x = parseFloat(String(v).replace(',', '.')); return isFinite(x) ? x : null; };
const initials = n => n.split(' ').map(w => w[0]).slice(0, 2).join('');
const fmtTime = iso => {
  const d = new Date(iso);
  if (isNaN(d)) return '';
  const today = new Date(); const tom = new Date(); tom.setDate(today.getDate() + 1);
  const hm = d.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' });
  if (d.toDateString() === today.toDateString()) return 'Oggi ' + hm;
  if (d.toDateString() === tom.toDateString()) return 'Domani ' + hm;
  return d.toLocaleDateString('it-IT', { weekday: 'short', day: 'numeric', month: 'short' }) + ' ' + hm;
};
const fmtDate = s => { const d = new Date(s); return isNaN(d) ? s : d.toLocaleDateString('it-IT', { day: 'numeric', month: 'short' }); };
function toast(msg) {
  const t = $('#toast'); t.textContent = msg; t.classList.add('show');
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove('show'), 1800);
}
const ICON_BACK = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 18l-6-6 6-6"></path></svg>';
const ICON_X = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"></path></svg>';

// ------------------------------------------------------------------ dati
// ------------------------------------------------------------------ codice d'accesso (dati cifrati)
const b64 = t => Uint8Array.from(atob(t), c => c.charCodeAt(0));
async function deriveKey(code, saltB64, iter) {
  const ck = (S.keys = S.keys || {});
  const id = saltB64 + '|' + iter;
  if (ck[id]) return ck[id];
  const base = await crypto.subtle.importKey('raw', new TextEncoder().encode(code), 'PBKDF2', false, ['deriveKey']);
  ck[id] = await crypto.subtle.deriveKey({ name: 'PBKDF2', salt: b64(saltB64), iterations: iter, hash: 'SHA-256' }, base,
    { name: 'AES-GCM', length: 256 }, false, ['decrypt']);
  return ck[id];
}
async function decryptEnv(env) {
  const key = await deriveKey(S.code, env.salt, env.iter);
  const pt = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: b64(env.iv) }, key, b64(env.ct));
  return JSON.parse(new TextDecoder().decode(pt));
}
const bustQ = () => '?t=' + Math.floor(Date.now() / 300000);
/** Legge un file di dati (cifrato se e' attivo il codice d'accesso) */
async function fetchData(name) {
  if (S.locked) {
    const env = await fetch('data/' + name + '.enc' + bustQ()).then(r => r.ok ? r.json() : null).catch(() => null);
    return env ? decryptEnv(env) : null;
  }
  return fetch('data/' + name + '.json' + bustQ()).then(r => r.ok ? r.json() : null).catch(() => null);
}
async function load() {
  try {
    const lock = await fetch('data/lock.json' + bustQ()).then(x => x.ok ? x.json() : null).catch(() => null);
    S.locked = !!(lock && lock.locked);
    if (S.locked && !S.code) {
      S.code = LS.get('code', null);
      if (!S.code) { S.needCode = true; render(); return; }
    }
    let a;
    try { a = await fetchData('app'); } catch (e) {
      // codice sbagliato o cambiato
      S.code = null; LS.set('code', null); S.needCode = true; S.codeErr = 'Codice non valido.'; render(); return;
    }
    if (!a) throw new Error('no data');
    const r = await fetchData('results').catch(() => null);
    S.needCode = false; S.codeErr = '';
    S.data = a; S.results = r || { nba: {}, soccer: {} };
    settleBets();
  } catch (e) {
    S.error = 'Dati non ancora disponibili. Il primo aggiornamento automatico crea i dati dell\'app: controlla la scheda Actions su GitHub.';
  }
  render();
}
function viewLock() {
  return `<header class="top"><div class="row"><div style="display:flex;flex-direction:column;gap:2px"><span class="kicker">Accesso riservato</span><h1>Valore</h1></div></div></header>
    <main><div class="card">
      <label class="small muted" for="codeIn">Inserisci il codice d'accesso</label>
      <input id="codeIn" class="search" type="password" autocomplete="current-password" data-act="codeIn">
      <label class="row small" style="gap:8px"><input type="checkbox" id="codeRem" checked style="width:20px;height:20px"> Ricorda su questo dispositivo</label>
      ${S.codeErr ? `<span class="badge warn" style="align-self:flex-start">${esc(S.codeErr)}</span>` : ''}
      <button class="btn" data-act="unlock">Entra</button>
      <p class="note">I dati sono cifrati: senza il codice non si possono leggere.</p></div></main>`;
}

const players = sport => (S.data && S.data[sport] && S.data[sport].players) || [];
const findPlayer = (sport, id, g) => players(sport).find(p => p.id === id && (!g || p.g === g));
const oddsKey = (sport, p, m) => sport + '|' + p.id + '|' + p.g + '|' + m;

/** Linea e quote per giocatore/mercato: manuali, poi automatiche, poi linea di default */
function lineFor(sport, p, m) {
  const man = S.manual[oddsKey(sport, p, m)];
  if (man) return { line: man.line, over: man.over, under: man.under, src: 'manuale' };
  const auto = p.odds && p.odds[m];
  if (auto) return { line: auto[0], over: auto[1], under: auto[2], src: auto[3] || 'auto' };
  const [mu] = p.mk[m] || [0];
  return { line: defaultLine(m, mu), over: null, under: null, src: null };
}

/** Valutazione: probabilita' modello, EV del lato migliore */
function evaluate(sport, p, m) {
  const [mu, r] = p.mk[m] || [0, null];
  const L = lineFor(sport, p, m);
  const pr = probs(L.line, mu, r);
  const res = { mu, r, ...L, pOver: pr.over, pUnder: pr.under, push: pr.push, side: null, ev: null, odds: null, p: null };
  const cands = [];
  if (L.over) cands.push(['over', pr.over, L.over]);
  if (L.under) cands.push(['under', pr.under, L.under]);
  for (const [side, pp, o] of cands) {
    const e = ev(pp, o, pr.push);
    if (res.ev === null || e > res.ev) Object.assign(res, { side, ev: e, odds: o, p: pp });
  }
  if (!cands.length) Object.assign(res, { side: 'over', p: pr.over });
  return res;
}

function hitRate(sport, p, m, line, side) {
  const off = L_OFF[sport];
  return p.l.map(g => {
    const v = marketValue(sport, m, g, off);
    return side === 'under' ? v < line : v > line;
  });
}

// ------------------------------------------------------------------ schedina e scommesse
function addToSlip(sel) {
  const id = [sel.sport, sel.g, sel.pid || 'match', sel.m, sel.side, sel.line].join('|');
  if (S.slip.some(s => s.id === id)) { toast('Già nella schedina'); return; }
  if (sel.m !== 'tm' && S.slip.some(s => s.g === sel.g && s.m === sel.m && (s.pid || null) === (sel.pid || null))) { toast('C\'è già un esito di questo mercato in schedina'); return; }
  S.slip.push({ ...sel, id, stake: null });
  save(); updateBadge(); toast('Aggiunta alla schedina');
}
function suggestedStake(sel) {
  const f = kelly(sel.p, sel.odds, sel.push || 0) * S.kellyFrac;
  // EV sopra il 15%: quasi sempre un dato mancante (infortunio, minuti, linea sbagliata) -> massimo 1%
  const cap = ev(sel.p, sel.odds, sel.push || 0) > 0.15 ? 0.01 : 0.05;
  return Math.min(S.bankroll * f, S.bankroll * cap);
}
/** Multipla: quota totale, probabilita' combinata (esiti considerati indipendenti), EV */
function multiInfo(legs) {
  const odds = legs.reduce((a, l) => a * l.odds, 1);
  const p = legs.reduce((a, l) => a * l.p, 1);
  const games = {};
  for (const l of legs) games[l.g] = (games[l.g] || 0) + 1;
  const sameGame = Object.values(games).some(n => n > 1);
  return { odds, p, ev: p * odds - 1, sameGame };
}

/** Mercati di squadra del calcio: true/false, 'void' o null (dato mancante). s = [gc, go, gc1T, go1T, angoli c, angoli o, cart. c, cart. o] */
function evalSoccerKey(k, s) {
  if (!s || s[0] == null || s[1] == null) return null;
  const h = +s[0], a = +s[1];
  const hasHT = s.length > 3 && s[2] != null && s[3] != null;
  const h1 = hasHT ? +s[2] : null, a1 = hasHT ? +s[3] : null;
  const line = c => parseInt(c, 10) / 10;
  const simple = { '1': h > a, 'X': h === a, '2': h < a, '1X': h >= a, 'X2': h <= a, '12': h !== a, gg: h > 0 && a > 0, ng: !(h > 0 && a > 0),
    '1+o15': h > a && h + a > 1.5, '1+o25': h > a && h + a > 2.5, '2+o15': h < a && h + a > 1.5, '2+o25': h < a && h + a > 2.5,
    '1+gg': h > a && a > 0, '2+gg': h < a && h > 0, 'x+u25': h === a && h + a < 2.5, '1x+o15': h >= a && h + a > 1.5,
    'x2+o15': h <= a && h + a > 1.5, '1x+u35': h >= a && h + a < 3.5, 'x2+u35': h <= a && h + a < 3.5,
    'gg+o25': h > 0 && a > 0 && h + a > 2.5, 'ng+u25': (h === 0 || a === 0) && h + a < 2.5 };
  if (k in simple) return simple[k];
  if (k === 'dnb1' || k === 'dnb2') return h === a ? 'void' : ((h > a) === (k === 'dnb1'));
  if (/^[ou]\d+$/.test(k)) return (h + a > line(k.slice(1))) === (k[0] === 'o');
  if (k.startsWith('mg')) { const [lo, hi] = k.slice(2).split('-').map(Number); return h + a >= lo && h + a <= hi; }
  if (/^[ha][ou]\d+$/.test(k)) { const v = k[0] === 'h' ? h : a; return (v > line(k.slice(2))) === (k[1] === 'o'); }
  if (k.startsWith('cs')) { const [x, y] = k.slice(2).split('-').map(Number); return h === x && a === y; }
  if (/^(1t|2t|tpg)/.test(k)) {
    if (!hasHT) return null;
    const h2 = h - h1, a2 = a - a1;
    if (k.startsWith('tpg')) { const g1 = h1 + a1, g2 = h2 + a2; return { tpg1: g1 > g2, tpg2: g2 > g1, tpgx: g1 === g2 }[k]; }
    const [x, y] = k.startsWith('1t') ? [h1, a1] : [h2, a2];
    const r = k.slice(2);
    if (r === '1') return x > y; if (r === 'x') return x === y; if (r === '2') return x < y; if (r === 'gg') return x > 0 && y > 0;
    if (/^[ou]\d+$/.test(r)) return (x + y > line(r.slice(1))) === (r[0] === 'o');
    return null;
  }
  if (/^[ck][ou]\d+$/.test(k)) {
    const i = k[0] === 'c' ? 4 : 6;
    if (s.length <= i + 1 || s[i] == null || s[i + 1] == null) return null;
    return (+s[i] + +s[i + 1] > line(k.slice(2))) === (k[1] === 'o');
  }
  return null;
}
/** Esito di una singola selezione: 'won' | 'lost' | 'void' | null (non ancora disponibile) */
function legOutcome(b) {
  const R = ((S.results || {})[b.sport] || {})[b.g];
  if (!R) return null;
  if (b.sport === 'tennis') return R.w ? (R.w === b.win ? 'won' : 'lost') : null;
  if (b.m === 'tm') { const r = evalSoccerKey(b.side, R.s); return r === null ? null : r === 'void' ? 'void' : (r ? 'won' : 'lost'); }
  if (!b.pid) {
    const [hs, as] = R.s;
    const res = hs > as ? '1' : hs < as ? '2' : 'X';
    return res === b.side ? 'won' : 'lost';
  }
  if (!R.b) return null;
  const row = R.p[b.pid];
  if (!row) return 'void';
  const v = marketValue(b.sport, b.m, row, 1);
  b.actual = v;
  if (v === b.line) return 'void';
  return ((v > b.line) === (b.side === 'over')) ? 'won' : 'lost';
}
function settleBets() {
  if (!S.results) return;
  let changed = false;
  for (const b of S.bets) {
    if (b.status !== 'pending') continue;
    if (b.type === 'multi') {
      for (const l of b.legs) if (!l.status || l.status === 'pending') l.status = legOutcome(l) || 'pending';
      if (b.legs.some(l => l.status === 'lost')) { setOutcome(b, 'lost'); changed = true; }
      else if (b.legs.every(l => l.status !== 'pending')) {
        const won = b.legs.filter(l => l.status === 'won');
        b.oddsEff = won.reduce((a, l) => a * l.odds, 1);
        setOutcome(b, won.length ? 'won' : 'void'); changed = true;
      }
      continue;
    }
    const outcome = legOutcome(b);
    if (outcome) { setOutcome(b, outcome); changed = true; }
  }
  if (changed) save();
}
function setOutcome(b, outcome) {
  b.status = outcome;
  const o = b.oddsEff || b.odds;
  b.profit = outcome === 'won' ? b.stake * (o - 1) : outcome === 'lost' ? -b.stake : 0;
  b.settled = new Date().toISOString();
}
function updateBadge() {
  const c = $('#slipCount');
  if (!c) return;
  c.hidden = !S.slip.length; c.textContent = S.slip.length;
}

// ------------------------------------------------------------------ router
function route() {
  const h = location.hash.replace(/^#/, '') || '/';
  const [path, qs] = h.split('?');
  const parts = path.split('/').filter(Boolean);
  const q = Object.fromEntries(new URLSearchParams(qs || ''));
  return { parts, q };
}
function render() {
  const { parts, q } = route();
  const tab = ['giocatori', 'g', 'p', 'cerca', 'incolla'].includes(parts[0]) ? 'giocatori' : ['schedina', 'roi', 'chicche'].includes(parts[0]) ? parts[0] : 'partite';
  document.querySelectorAll('nav.tabs a').forEach(a => a.classList.toggle('on', a.dataset.tab === tab));
  updateBadge();
  const v = $('#view');
  let html;
  if (parts[0] === 'schedina') html = viewSlip();
  else if (parts[0] === 'roi') html = viewRoi();
  else if (S.needCode) html = viewLock();
  else if (S.error) html = header('Valore', 'Statistiche → probabilità') + `</header><main><div class="empty">${esc(S.error)}</div></main>`;
  else if (!S.data) html = `<main style="padding-top:40px"><div class="empty">Caricamento…</div></main>`;
  else if (parts[0] === 'giocatori') html = viewPlayers(q);
  else if (parts[0] === 'g') html = viewPlayer(parts[1], parts[2], parts[3], q.m);
  else if (parts[0] === 'p') html = viewCard(parts[1], parts[2], parts[3]);
  else if (parts[0] === 'cerca') html = viewSearch();
  else if (parts[0] === 'incolla') html = viewPaste();
  else if (parts[0] === 'partita') html = viewMatch(parts[1]);
  else if (parts[0] === 'tennis') html = viewTennis(parts[1]);
  else if (parts[0] === 'chicche') html = viewChicche();
  else if (parts[0] === 'stato') html = viewStato();
  else html = viewGames();
  v.innerHTML = html;
  bind();
  if (parts[0] === 'cerca') { const i = document.querySelector('[data-act=gsearch]'); if (i) { i.focus(); i.setSelectionRange(i.value.length, i.value.length); } }
}
window.addEventListener('hashchange', () => { render(); window.scrollTo(0, 0); });

const ICON_SEARCH = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"></circle><path d="M20 20l-3.5-3.5"></path></svg>';
const ICON_PASTE = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="8" y="3" width="8" height="4" rx="1"></rect><path d="M16 5h2a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h2"></path><path d="M9 13h6M9 17h4"></path></svg>';
const searchBtn = () => `<a class="iconbtn" href="#/cerca" aria-label="Cerca giocatore">${ICON_SEARCH}</a>`;
function header(title, kicker, back, right) {
  return `<header class="top"><div class="row">${back ? `<a class="iconbtn" href="${back}" aria-label="Indietro">${ICON_BACK}</a>` : ''}
    <div style="display:flex;flex-direction:column;gap:2px;min-width:0;flex:1"><span class="kicker">${esc(kicker)}</span><h1>${esc(title)}</h1></div>${right || ''}</div>`;
}
function sportSeg(withTennis) {
  const list = availSports(withTennis);
  if (!list.includes(S.sport)) S.sport = list[0] || 'nba';
  return `<div class="seg" role="tablist" aria-label="Sport">${list.map(k =>
    `<button role="tab" aria-selected="${S.sport === k}" class="${S.sport === k ? 'on' : ''}" data-act="sport" data-v="${k}">${SPORT_LABEL[k]}</button>`).join('')}</div>`;
}
function updatedLine() {
  if (!S.data) return '';
  return `<p class="note">Dati aggiornati: ${esc(new Date(S.data.generated).toLocaleString('it-IT', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }))}. Le probabilità sono stime, non certezze. Il gioco è vietato ai minori di 18 anni e può causare dipendenza.</p>`;
}

// ------------------------------------------------------------------ vista: partite
function viewGames() {
  let body = '';
  const segHtml = sportSeg(true);
  if (S.sport === 'tennis') {
    const ms = ((S.data.tennis || {}).matches || []).slice().sort((a, b) => a.t.localeCompare(b.t));
    if (!ms.length) body = '<div class="empty">Nessuna partita di tennis in programma.</div>';
    const groups = {};
    for (const m of ms) (groups[m.tour + ' · ' + m.tn] = groups[m.tour + ' · ' + m.tn] || []).push(m);
    for (const [k, list] of Object.entries(groups)) {
      const l2 = list.filter(m => !S.onlyValue || tennisValue(m).best > 0);
      if (!l2.length) continue;
      body += `<div class="league">${esc(k)}</div>` + l2.map(tennisCard).join('');
    }
  } else if (S.sport !== 'soccer') {
    const sp = S.sport;
    const games = gamesList(sp).slice().sort((a, b) => a.t.localeCompare(b.t));
    if (!games.length) body = `<div class="empty">Nessuna partita ${SPORT_LABEL[sp]} nei prossimi giorni${sp === 'mlb' ? ' (la stagione MLB riparte ad aprile)' : ''}.</div>`;
    for (const g of games) {
      const ps = players(sp).filter(p => p.g === g.id);
      const vals = ps.flatMap(p => mkList(sp, p).map(m => evaluate(sp, p, m[0]))).filter(e => e.ev !== null && e.ev > 0);
      const ml = g.odds && g.odds.h ? `<span class="mono small muted">${esc(g.a)} ${g.odds.a.toFixed(2)} · ${esc(g.h)} ${g.odds.h.toFixed(2)}${g.odds.ou ? ' · tot ' + g.odds.ou : ''}</span>` : '';
      body += `<a class="card" href="#/giocatori?g=${esc(g.id)}">
        <div class="row between small muted"><span>${SPORT_LABEL[sp]} · ${esc(fmtTime(g.t))}</span>${vals.length ? `<span class="badge val">${vals.length} con valore</span>` : ''}</div>
        <div class="row between"><span style="font-size:16px;font-weight:600">${esc(g.an)} @ ${esc(g.hn)}</span></div>
        ${ml}<div class="small muted">${ps.length} giocatori analizzati · tocca per le prop</div></a>`;
    }
  } else {
    const ms = (S.data.soccer.matches || []).slice().sort((a, b) => a.t.localeCompare(b.t));
    if (!ms.length) body = '<div class="empty">Nessuna partita di calcio nei prossimi giorni per i campionati scelti.</div>';
    const leagues = S.data.leagues || {};
    const order = Object.keys(leagues);
    const groups = {};
    for (const m of ms) (groups[m.lg] = groups[m.lg] || []).push(m);
    for (const lg of order.concat(Object.keys(groups).filter(x => !order.includes(x)))) {
      if (!groups[lg]) continue;
      const list = groups[lg].filter(m => !S.onlyValue || matchValue(m).best > 0);
      if (!list.length) continue;
      body += `<div class="league">${esc(leagues[lg] || lg)}</div>`;
      for (const m of list) body += matchCard(m);
    }
  }
  return header('Partite', 'Prossimi giorni', null, `<div class="row"><a class="iconbtn" href="#/stato" aria-label="Stato dati e affidabilità"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9"></circle><path d="M12 11v6M12 7.5h.01"></path></svg></a>${searchBtn()}</div>`) + `<div style="padding:0 16px;display:flex;flex-direction:column;gap:10px">${segHtml}
    ${S.sport === 'soccer' || S.sport === 'tennis' ? `<div class="chips"><button class="chip ${!S.onlyValue ? 'on' : ''}" data-act="onlyValue" data-v="0">Tutte</button><button class="chip ${S.onlyValue ? 'on' : ''}" data-act="onlyValue" data-v="1">Solo valore</button></div>` : ''}</div></header>
    <main>${body}${updatedLine()}</main>`;
}
function matchOdds(m) {
  const man = S.manual['soccer|match|' + m.id];
  if (man) return man;
  if (m.odds) {
    const o = m.odds;
    return { o1: o[0], ox: o[1], o2: o[2], book: o[3], f1: o[4], fx: o[5], f2: o[6], b1: o[7] || o[3], bx: o[8] || o[3], b2: o[9] || o[3], ref: o[10], nb: o[11] };
  }
  return null;
}
function matchValue(m) {
  if (m.mk) {
    const od = tmOdds(m);
    const out = { best: null, side: null };
    for (const [k, g, l, p] of m.mk) {
      const q = od[k];
      if (!q) continue;
      const e = ev(p, q);
      if (out.best === null || e > out.best) Object.assign(out, { best: e, side: l });
    }
    return out;
  }
  const o = matchOdds(m);
  const out = { best: null, side: null };
  if (!o || m.p1 == null) return out;
  for (const [side, p, q] of [['1', m.p1, o.o1], ['X', m.px, o.ox], ['2', m.p2, o.o2]]) {
    if (!q) continue;
    const e = ev(p, q);
    if (out.best === null || e > out.best) Object.assign(out, { best: e, side });
  }
  return out;
}
function matchCard(m) {
  const o = matchOdds(m);
  const v = matchValue(m);
  const cells = m.p1 == null ? '<div class="small muted">Storico insufficiente per il modello squadre.</div>' :
    `<div class="grid3">${[['1', m.p1, o && o.o1], ['X', m.px, o && o.ox], ['2', m.p2, o && o.o2]].map(([s, p, q]) => {
      const val = q && ev(p, q) > 0;
      return `<div class="cell ${val ? 'value' : ''}"><div class="row between tiny muted"><span>${s}</span><span>${q ? pct(1 / q) : ''}</span></div>
        <span class="mono b" style="font-size:18px">${q ? q.toFixed(2) : '—'}</span>
        <div class="bar"><div style="width:${(p * 100).toFixed(0)}%;background:${val ? 'var(--accent)' : 'var(--model)'}"></div></div>
        <span class="tiny model b">Modello ${pct(p)}</span></div>`;
    }).join('')}</div>`;
  return `<a class="card" href="#/partita/${esc(m.id)}">
    <div class="row between small muted"><span>${esc(fmtTime(m.t))}</span>${v.best !== null ? (v.best > 0 ? `<span class="badge val">VALORE ${sgn(v.best)}</span>` : '<span class="badge no">Nessun valore</span>') : ''}</div>
    <div class="row between"><span style="font-size:16px;font-weight:600">${esc(m.h)} – ${esc(m.a)}</span>${m.lh ? `<span class="mono small muted" style="white-space:nowrap">xG ${m.lh.toFixed(2)}–${m.la.toFixed(2)}</span>` : ''}</div>
    ${cells}
    ${m.mk ? (() => { const d = Object.fromEntries(m.mk.map(x => [x[0], x[3]])); return `<div class="small muted">Over 2.5 <b class="model">${pct(d.o25)}</b> · Goal <b class="model">${pct(d.gg)}</b> · 1T over 0.5 <b class="model">${pct(d['1to05'])}</b>${m.mk_c ? ` · angoli ${m.mk_c.toFixed(1)}` : ''}</div>`; })() : ''}
    ${v.best !== null && v.side ? `<div class="small" style="color:var(--text2)">Miglior valore: ${esc(v.side)}</div>` : ''}</a>`;
}

// ------------------------------------------------------------------ vista: partita (calcio)
/** Quote dei mercati di squadra: inserite a mano, oppure 1X2 automatiche */
function tmOdds(m) {
  const man = S.manual['soccer|mk|' + m.id] || {};
  const out = {};
  const o = matchOdds(m);
  if (o) { if (o.o1) out['1'] = o.o1; if (o.ox) out['X'] = o.ox; if (o.o2) out['2'] = o.o2; }
  for (const [k, v] of Object.entries(man)) if (v) out[k] = v; else delete out[k];
  return out;
}
const TM_GROUPS = ['Principali', 'Multigol', 'Squadre', 'Combo', '1° tempo', '2° tempo', "Calci d'angolo", 'Cartellini', 'Risultato esatto'];
const tmGroupOf = g => (['Esito finale', 'Gol / No gol', 'Under / Over'].includes(g) ? 'Principali' : g.startsWith('Gol ') ? 'Squadre' : g);
function viewMatch(id) {
  const m = (S.data.soccer.matches || []).find(x => x.id === id);
  if (!m) return header('Partita', 'Calcio', '#/') + '</header><main><div class="empty">Partita non trovata.</div></main>';
  const lg = (S.data.leagues || {})[m.lg] || m.lg;
  const ps = players('soccer').filter(p => p.g === m.id);
  if (!m.mk) {
    return header(`${m.h} – ${m.a}`, `${lg} · ${fmtTime(m.t)}`, '#/') + `</header><main>
      <div class="card"><p class="note">Storico insufficiente per stimare il risultato (squadre con poche partite nell'archivio): restano disponibili le statistiche dei giocatori.</p></div>
      <a class="btn ghost" href="#/giocatori?g=${esc(m.id)}">Statistiche giocatori (${ps.length})</a></main>`;
  }
  const odds = tmOdds(m);
  const groups = TM_GROUPS.filter(g => m.mk.some(x => tmGroupOf(x[1]) === g));
  const grp = groups.includes(S.mGroup) ? S.mGroup : groups[0];
  const rows = m.mk.filter(x => tmGroupOf(x[1]) === grp);
  let lastSub = '';
  const list = rows.map(([k, g, label, p]) => {
    const q = odds[k];
    const e = q ? ev(p, q) : null;
    const sub = g !== lastSub && grp === 'Principali' ? `<div class="league" style="margin-top:10px">${esc(g)}</div>` : '';
    lastSub = g;
    return `${sub}<div style="display:grid;grid-template-columns:minmax(0,1.6fr) 0.8fr 0.9fr 44px;gap:8px;align-items:center;padding:8px 0;border-top:1px solid var(--line)">
      <div style="display:flex;flex-direction:column;gap:2px;min-width:0"><span class="b" style="font-size:14px">${esc(label)}</span>
        <span class="tiny muted">${pct(p, 1)} · giusta ${p > 0.001 ? (1 / p).toFixed(2) : '—'}${e !== null ? ` · <b style="color:${e > 0 ? 'var(--accent)' : 'var(--book)'}">EV ${sgn(e)}</b>` : ''}</span></div>
      <div class="bar" style="height:8px"><div style="width:${(p * 100).toFixed(0)}%;background:${e !== null && e > 0 ? 'var(--accent)' : 'var(--model)'}"></div></div>
      <input inputmode="decimal" aria-label="Quota ${esc(label)}" placeholder="quota" data-act="tmOdds" data-id="${esc(m.id)}" data-k="${esc(k)}" value="${q || ''}"
        style="height:38px;border-radius:9px;border:1px solid var(--line);background:var(--bg);padding:0 8px;font:700 14px var(--mono);width:100%;color:var(--text)">
      <button class="iconbtn" style="width:44px;height:38px;${e !== null && e > 0 ? 'background:var(--accent);color:var(--accent-ink);border-color:var(--accent)' : ''}" aria-label="Aggiungi ${esc(label)}" data-act="addTm" data-id="${esc(m.id)}" data-k="${esc(k)}" ${q ? '' : 'disabled'}>+</button></div>`;
  }).join('');
  const info = `<div class="grid3">
      <div class="kv"><span>Gol attesi</span><span class="model">${m.lh.toFixed(2)} – ${m.la.toFixed(2)}</span></div>
      <div class="kv"><span>Angoli attesi</span><span class="model">${m.mk_c ? m.mk_c.toFixed(1) : '—'}</span></div>
      <div class="kv"><span>Cartellini attesi</span><span class="model">${m.mk_k ? m.mk_k.toFixed(1) : '—'}</span></div></div>`;
  return header(`${m.h} – ${m.a}`, `${lg} · ${fmtTime(m.t)}`, '#/') + `<div style="padding:0 16px"><div class="chips">${groups.map(g =>
    `<button class="chip ${g === grp ? 'on' : ''}" data-act="mGroup" data-v="${esc(g)}">${esc(g)}</button>`).join('')}</div></div></header><main>
    <div class="card" style="gap:10px">${info}
      <p class="note">Scrivi la quota del tuo bookmaker accanto al mercato: l'app calcola il valore (EV). Il + aggiunge la giocata alla schedina.${m.odds && m.odds[3] ? ' Quote 1X2 automatiche: ' + esc(m.odds[3]) + '.' : ''}</p></div>
    <div class="card" style="gap:0">${list}</div>
    <div class="card"><p class="note">Gol: modello di Poisson con correzione Dixon-Coles su attacco e difesa delle squadre${/^uefa\./.test(m.lg) ? ' (per le coppe europee un modello unico su tutti i campionati)' : ''}, più peso alle partite recenti. Primo tempo: ${pct(m.f1 || 0.445)} dei gol della lega. Angoli e cartellini: stesso metodo sulle statistiche di squadra${m.ref ? ', con l\'arbitro ' + esc(m.ref) : ''}.</p></div>
    <a class="btn ghost" href="#/giocatori?g=${esc(m.id)}">Statistiche giocatori (${ps.length})</a>
    ${updatedLine()}</main>`;
}

// ------------------------------------------------------------------ tennis
function tennisOdds(m) { return S.manual['tennis|match|' + m.id] || null; }
function tennisValue(m) {
  const o = tennisOdds(m);
  const out = { best: null, side: null };
  if (!o) return out;
  for (const [side, p, q] of [['1', m.pr1, o.o1], ['2', 1 - m.pr1, o.o2]]) {
    if (!q) continue;
    const e = ev(p, q);
    if (out.best === null || e > out.best) Object.assign(out, { best: e, side });
  }
  return out;
}
const formDots = f => (f || []).map(x => `<span style="width:10px;height:10px;border-radius:50%;display:inline-block;background:${x ? 'var(--model)' : 'var(--line2)'}"></span>`).join('');
function tennisCard(m) {
  const o = tennisOdds(m) || {};
  const v = tennisValue(m);
  const cell = (name, p, q, f) => {
    const val = q && ev(p, q) > 0;
    return `<div class="cell ${val ? 'value' : ''}"><div class="row between"><span class="b" style="font-size:14px">${esc(name)}</span><span class="mono b">${q ? q.toFixed(2) : '—'}</span></div>
      <div class="bar"><div style="width:${(p * 100).toFixed(0)}%;background:${val ? 'var(--accent)' : 'var(--model)'}"></div></div>
      <div class="row between"><span class="tiny model b">Elo ${pct(p)}</span><span style="display:flex;gap:2px">${formDots((f || []).slice(0, 5))}</span></div></div>`;
  };
  return `<a class="card" href="#/tennis/${esc(m.id)}">
    <div class="row between small muted"><span>${esc(fmtTime(m.t))}</span>${v.best !== null ? (v.best > 0 ? `<span class="badge val">VALORE ${sgn(v.best)}</span>` : '<span class="badge no">Nessun valore</span>') : ''}</div>
    <div class="grid2">${cell(m.p1, m.pr1, o.o1, m.f1)}${cell(m.p2, 1 - m.pr1, o.o2, m.f2)}</div></a>`;
}
function viewTennis(id) {
  const m = ((S.data.tennis || {}).matches || []).find(x => x.id === id);
  if (!m) return header('Partita', 'Tennis', '#/') + '</header><main><div class="empty">Partita non trovata.</div></main>';
  const o = tennisOdds(m) || {};
  const few = m.n1 < 15 || m.n2 < 15;
  const side = (k, name, p, q, elo, n, f) => {
    const e = q ? ev(p, q) : null;
    return `<div class="list-row"><div style="display:flex;flex-direction:column;gap:4px;min-width:0"><span class="b">${esc(name)}</span>
      <span class="tiny muted">Elo ${elo} · ${n} partite nello storico · quota giusta ${(1 / p).toFixed(2)}</span><span style="display:flex;gap:3px">${formDots(f)}</span></div>
      <div class="row"><span class="mono b model">${pct(p, 1)}</span>${e !== null ? `<span class="mono b ${e > 0 ? 'acc' : 'muted'}">${sgn(e)}</span>` : ''}
      ${q ? `<button class="btn small ${e > 0 ? '' : 'ghost'}" data-act="addTennis" data-id="${esc(m.id)}" data-side="${k}">+</button>` : ''}</div></div>`;
  };
  return header(`${m.p1} – ${m.p2}`, `${m.tour} · ${m.tn} · ${fmtTime(m.t)}`, '#/') + `</header><main>
    <div class="card"><h2>Quote del tuo bookmaker</h2>
      <div class="grid2">${[['o1', m.p1], ['o2', m.p2]].map(([k, n]) => `<div class="field"><label for="to-${k}">${esc(n)}</label><input id="to-${k}" inputmode="decimal" data-act="tennisOdds" data-k="${k}" data-id="${esc(m.id)}" value="${o[k] || ''}" placeholder="—"></div>`).join('')}</div>
      ${side('1', m.p1, m.pr1, o.o1, m.e1, m.n1, m.f1)}${side('2', m.p2, 1 - m.pr1, o.o2, m.e2, m.n2, m.f2)}
      ${few ? '<div class="warnbox"><span>Uno dei due giocatori ha poche partite nello storico: la stima Elo è meno affidabile.</span></div>' : ''}
      <p class="note">Modello Elo sui risultati ATP/WTA degli ultimi 12 mesi, con aggiornamenti più forti per chi ha giocato poco. Non tiene conto della superficie né degli infortuni. I pallini mostrano le ultime 10 partite (azzurro = vinta).</p></div>
    ${updatedLine()}</main>`;
}

// ------------------------------------------------------------------ stato dati e affidabilita'
function viewStato() {
  if (!S.diag && !S.diagLoading) {
    S.diagLoading = true;
    fetchData('diag').catch(() => null).then(d => { S.diag = d || { missing: true }; S.diagLoading = false; render(); });
  }
  const D = S.diag;
  if (!D) return header('Stato dati', 'Copertura e affidabilità', '#/') + '</header><main><div class="empty">Caricamento…</div></main>';
  if (D.missing) return header('Stato dati', 'Copertura e affidabilità', '#/') + '</header><main><div class="empty">Il report arriva con il prossimo aggiornamento automatico.</div></main>';
  const pc = (a, b) => b ? Math.round(a / b * 100) + '%' : '—';
  const col = (a, b) => !b ? 'var(--muted)' : a / b >= 0.8 ? 'var(--model)' : a / b >= 0.4 ? 'var(--text2)' : 'var(--book)';
  const lgRows = Object.values(D.soccer || {}).map(l => `<div style="display:grid;grid-template-columns:minmax(0,1.4fr) repeat(5,minmax(0,0.7fr));gap:4px;padding:8px 0;border-top:1px solid var(--line);font-size:12px;align-items:center">
      <span class="b">${esc(l.name)}</span>
      <span class="mono">${l.recenti}</span>
      <span class="mono" style="color:${col(l.con_giocatori, l.recenti)}">${pc(l.con_giocatori, l.recenti)}</span>
      <span class="mono" style="color:${col(l.con_angoli, l.recenti)}">${pc(l.con_angoli, l.recenti)}</span>
      <span class="mono">${l.prossime}${l.prossime ? ' (' + l.con_modello + ')' : ''}</span>
      <span class="mono">${l.giocatori}</span></div>`).join('');
  const C = D.calib || {};
  const F = C.factors || {};
  const calRows = (sport) => Object.entries(C[sport] || {}).sort((a, b) => b[1].n - a[1].n).map(([m, r]) => `<div style="display:grid;grid-template-columns:minmax(0,1.3fr) repeat(4,minmax(0,0.7fr));gap:4px;padding:8px 0;border-top:1px solid var(--line);font-size:12px">
      <span class="b">${esc(mkLabel(sport, m))}</span><span class="mono">${r.n}</span>
      <span class="mono" style="color:${Math.abs(r.bias || 0) <= 0.04 ? 'var(--model)' : 'var(--book)'}">${r.bias == null ? '—' : sgn(r.bias)}</span>
      <span class="mono">${pct(r.p)} / ${pct(r.y)}</span><span class="mono">${F[sport] && F[sport][m] ? '×' + F[sport][m].toFixed(3) : '—'}</span></div>`).join('');
  const tmLabel = k => ({ '1': '1', X: 'X', '2': '2', o15: 'Over 1.5', o25: 'Over 2.5', o35: 'Over 3.5', gg: 'Goal', '1to05': '1T over 0.5', '1to15': '1T over 1.5', co095: 'Angoli over 9.5', ko45: 'Cartellini over 4.5' }[k] || k);
  const tmRows = Object.entries(C.soccer_tm || {}).map(([k, r]) => `<div style="display:grid;grid-template-columns:minmax(0,1.3fr) repeat(3,minmax(0,0.8fr));gap:4px;padding:8px 0;border-top:1px solid var(--line);font-size:12px">
      <span class="b">${esc(tmLabel(k))}</span><span class="mono">${r.n}</span><span class="mono">${pct(r.p)}</span>
      <span class="mono" style="color:${Math.abs(r.p - r.y) <= 0.04 ? 'var(--model)' : 'var(--book)'}">${pct(r.y)}</span></div>`).join('');
  const nb = D.nba || {};
  return header('Stato dati', 'Copertura e affidabilità', '#/') + `</header><main>
    <div class="card"><h2>Aggiornamento</h2>
      <div class="list-row"><span>Ultimo aggiornamento</span><span class="mono">${esc(new Date(D.generated).toLocaleString('it-IT', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }))}</span></div>
      <div class="list-row"><span>Tabellini ancora da scaricare</span><span class="mono">${D.queue}</span></div>
      <p class="note">Se il numero è alto lo storico si sta ancora completando: le proiezioni miglioreranno nei prossimi aggiornamenti.</p></div>
    <div class="card" style="gap:0"><h2 style="padding-bottom:8px">Calcio: copertura ultimi 60 giorni</h2>
      <div style="display:grid;grid-template-columns:minmax(0,1.4fr) repeat(5,minmax(0,0.7fr));gap:4px;font-size:11px" class="muted"><span>Lega</span><span>Part.</span><span>Gioc.</span><span>Angoli</span><span>Pross.</span><span>Anal.</span></div>
      ${lgRows}
      <p class="note" style="margin-top:8px">Part. = partite giocate; Gioc. = di queste, quante hanno le statistiche dei giocatori; Angoli = quante hanno angoli, cartellini e primo tempo; Pross. = partite in programma (tra parentesi quelle con il modello completo); Anal. = giocatori analizzati. Percentuali basse indicano che ESPN non pubblica quei dati per quella lega o che l'archivio è ancora incompleto.</p></div>
    <div class="card"><h2>NBA</h2>
      <div class="list-row"><span>Partite in archivio (ultimi 60 giorni)</span><span class="mono">${nb.partite || 0} (${nb.recenti || 0})</span></div>
      <div class="list-row"><span>Prossime partite / con totale e handicap ESPN</span><span class="mono">${nb.prossime || 0} / ${nb.con_quote_espn || 0}</span></div>
      <div class="list-row"><span>Giocatori analizzati</span><span class="mono">${nb.giocatori || 0}</span></div></div>
    <div class="card" style="gap:0"><h2 style="padding-bottom:8px">Affidabilità del modello (ultimi 30 giorni)</h2>
      <p class="note" style="padding-bottom:8px">Confronto tra le proiezioni fatte prima delle partite e i risultati veri. Errore = di quanto il modello ha sbagliato in media (positivo: risultati più alti delle proiezioni). Prev./Reale = probabilità media prevista di superare la linea vs frequenza reale: più sono vicine, più il modello è affidabile. Correzione = fattore applicato in automatico alle nuove proiezioni.</p>
      ${calRows('nba') ? `<div class="league">NBA</div><div style="display:grid;grid-template-columns:minmax(0,1.3fr) repeat(4,minmax(0,0.7fr));gap:4px;font-size:11px" class="muted"><span>Mercato</span><span>N</span><span>Errore</span><span>Prev./Reale</span><span>Correz.</span></div>${calRows('nba')}` : '<p class="note">NBA: servono alcuni giorni di partite per misurare l\'affidabilità.</p>'}
      ${calRows('soccer') ? `<div class="league">Calcio · giocatori</div>${calRows('soccer')}` : ''}
      ${tmRows ? `<div class="league">Calcio · mercati di squadra</div><div style="display:grid;grid-template-columns:minmax(0,1.3fr) repeat(3,minmax(0,0.8fr));gap:4px;font-size:11px" class="muted"><span>Mercato</span><span>N</span><span>Previsto</span><span>Reale</span></div>${tmRows}` : ''}
    </div>
    ${updatedLine()}</main>`;
}

// ------------------------------------------------------------------ chicche
const sideTxt = (m, side, line) => (BERNOULLI.has(m) ? (side === 'over' ? 'Sì' : 'No') : (side === 'over' ? 'Over ' : 'Under ') + line);
function buildChicche() {
  const val = [], err = [], chk = [];
  for (const sp of PROP_SPORTS) {
    for (const p of players(sp)) {
      const out = p.st && /^(out|assente)/i.test(p.st);
      for (const [m, label] of mkList(sp, p)) {
        const e = evaluate(sp, p, m);
        const ctx = `${sportCtx(sp, p)} · ${p.t} vs ${p.o}`;
        const href = `#/g/${sp}/${p.id}/${p.g}?m=${m}`;
        const mkSel = (side, odds, pp) => ({ sport: sp, g: p.g, pid: p.id, m, side, line: e.line, odds, p: pp, push: e.push,
          label: `${p.n} ${sideTxt(m, side, e.line)} ${label.toLowerCase()}`, ctx });
        if (!out && e.ev !== null && e.ev >= 0.02 && e.p >= 0.15 && e.p <= 0.92) {
          val.push({ score: e.ev, title: p.n, sub: `${label} · ${sideTxt(m, e.side, e.line)} @${e.odds.toFixed(2)} · modello ${pct(e.p)}`, ctx, href,
            badge: e.ev > 0.15 ? `<span class="badge warn">Da verificare ${sgn(e.ev, 0)}</span>` : `<span class="badge val">EV ${sgn(e.ev)}</span>`,
            sel: mkSel(e.side, e.odds, e.p) });
        }
        const auto = p.odds && p.odds[m];
        if (auto && auto[4] != null && !out) {
          const fair = auto[4];
          for (const [side, q, fp] of [['over', auto[1], fair], ['under', auto[2], 1 - fair]]) {
            if (!q) continue;
            const edge = q * fp - 1;
            if (edge >= 0.03) err.push({ score: edge, title: p.n, sub: `${label} · ${sideTxt(m, side, auto[0])} @${q.toFixed(2)} (${esc(auto[3] || '')}) · giusta ${(1 / fp).toFixed(2)}`, ctx, href,
              badge: `<span class="badge val">${sgn(edge)} sul mercato</span>`, sel: mkSel(side, q, side === 'over' ? e.pOver : e.pUnder) });
          }
        }
        const a = Number((p.a30 || {})[m]);
        if (!out && !BERNOULLI.has(m) && a >= 2 && e.mu > 0) {
          const d = e.mu / a - 1;
          if (Math.abs(d) >= 0.15) {
            const of = (p.of || {})[m] || 1;
            chk.push({ score: Math.abs(d), title: p.n, sub: `${label} · proiezione ${e.mu.toFixed(1)} vs media ${a.toFixed(1)} (${d > 0 ? '+' : '−'}${Math.abs(d * 100).toFixed(0)}%) · avversario ${of >= 1 ? '+' : '−'}${Math.abs((of - 1) * 100).toFixed(0)}%`,
              ctx, href, badge: `<span class="badge ${d > 0 ? 'val' : 'warn'}">${d > 0 ? 'Più alta' : 'Più bassa'}</span>`, sel: null });
          }
        }
      }
    }
  }
  for (const m of (S.data.soccer || {}).matches || []) {
    const ctx = `${(S.data.leagues || {})[m.lg] || 'Calcio'} · ${fmtTime(m.t)}`;
    const title = `${m.h} – ${m.a}`;
    const od = tmOdds(m);
    for (const [k, g, label, pm] of m.mk || []) {
      const q = od[k];
      if (!q) continue;
      const e = ev(pm, q);
      if (e >= 0.02 && pm >= 0.1) val.push({ score: e, title, sub: `${label} @${q.toFixed(2)} · modello ${pct(pm)}`, ctx, href: `#/partita/${m.id}`,
        badge: e > 0.15 ? `<span class="badge warn">Da verificare ${sgn(e, 0)}</span>` : `<span class="badge val">EV ${sgn(e)}</span>`,
        sel: { sport: 'soccer', g: m.id, pid: null, m: 'tm', side: k, line: null, odds: q, p: pm, push: 0, label, ctx: title } });
    }
    const o = matchOdds(m);
    if (!o) continue;
    const names = { '1': m.h, 'X': 'Pareggio', '2': m.a };
    for (const [side, pm, q, fair, bk] of [['1', m.p1, o.o1, o.f1, o.b1], ['X', m.px, o.ox, o.fx, o.bx], ['2', m.p2, o.o2, o.f2, o.b2]]) {
      if (!q || !fair) continue;
      const edge = q * fair - 1;
      const row = (m.mk || []).find(x => x[0] === side);
      if (edge >= 0.03) err.push({ score: edge, title, sub: `1X2 · ${side} ${names[side]} @${q.toFixed(2)} (${bk || ''}) · giusta ${(1 / fair).toFixed(2)} (${o.ref || 'mercato'})`, ctx, href: `#/partita/${m.id}`,
        badge: `<span class="badge val">${sgn(edge)} sul mercato</span>`,
        sel: row ? { sport: 'soccer', g: m.id, pid: null, m: 'tm', side, line: null, odds: q, p: row[3], push: 0, label: row[2], ctx: title } : null });
    }
  }
  for (const m of (S.data.tennis || {}).matches || []) {
    const o = tennisOdds(m);
    if (!o) continue;
    for (const [side, pm, q, name] of [['1', m.pr1, o.o1, m.p1], ['2', 1 - m.pr1, o.o2, m.p2]]) {
      if (!q) continue;
      const e = ev(pm, q);
      if (e >= 0.02) val.push({ score: e, title: `${m.p1} – ${m.p2}`, sub: `Vincente · ${name} @${q.toFixed(2)} · Elo ${pct(pm)}`, ctx: `${m.tour} · ${fmtTime(m.t)}`, href: `#/tennis/${m.id}`,
        badge: `<span class="badge val">EV ${sgn(e)}</span>`, sel: { sport: 'tennis', g: m.id, pid: null, m: 'win', side, win: side === '1' ? m.id1 : m.id2, line: null, odds: q, p: pm, push: 0, label: `${name} vincente`, ctx: `${m.tour} · ${m.p1} – ${m.p2}` } });
    }
  }
  const by = (a, b) => b.score - a.score;
  return { valore: val.sort(by).slice(0, 40), errori: err.sort(by).slice(0, 40), controllo: chk.sort(by).slice(0, 30) };
}
function viewChicche() {
  const C = buildChicche();
  const tab = S.chTab;
  const list = C[tab] || [];
  S.chicche = list.map(x => x);
  const intro = {
    valore: 'Le occasioni in cui la probabilità del modello supera quella della quota (quote automatiche o inserite da te). Le voci «Da verificare» hanno un valore così alto che quasi sempre manca un dato: controlla prima di giocare.',
    errori: 'Quote di un bookmaker più alte della quota «giusta» del mercato (Pinnacle senza margine, o la media dei bookmaker). Non dipende dal modello: è il segnale più affidabile. Richiede le quote automatiche (chiave ODDS_API_KEY).',
    controllo: 'Nessuna quota necessaria: giocatori la cui proiezione per stasera è molto diversa dalla media recente, per l\'avversario, i minuti o il contesto. Le linee dei bookmaker spesso seguono la media: confrontale con queste proiezioni.',
  }[tab];
  const rows = list.map((c, i) => `<div class="card" style="gap:8px">
      <div class="row between" style="align-items:flex-start"><a href="${c.href}" style="display:flex;flex-direction:column;gap:2px;min-width:0"><span class="b" style="font-size:15px">${esc(c.title)}</span>
        <span class="small" style="color:var(--text2)">${c.sub}</span><span class="tiny muted">${esc(c.ctx)}</span></a>${c.badge}</div>
      ${c.sel && c.sel.odds ? `<button class="btn small ghost" data-act="addChicca" data-i="${i}">Aggiungi alla schedina</button>` : ''}</div>`).join('');
  const empty = {
    valore: 'Nessuna occasione al momento. Inserisci le quote del tuo bookmaker (anche con «Incolla quote») e torna qui.',
    errori: 'Nessun errore di quota trovato. Servono le quote automatiche: aggiungi la chiave ODDS_API_KEY su GitHub (vedi README).',
    controllo: 'Nessuna differenza rilevante nelle prossime partite.',
  }[tab];
  return header('Chicche', 'Le occasioni del giorno') + `<div style="padding:0 16px"><div class="seg">${[['valore', 'Valore'], ['errori', 'Errori quota'], ['controllo', 'Controlla']].map(([k, l]) =>
    `<button class="${tab === k ? 'on' : ''}" data-act="chTab" data-v="${k}">${l} (${C[k].length})</button>`).join('')}</div></div></header>
    <main><p class="note">${intro}</p>${rows || `<div class="empty">${empty}</div>`}${updatedLine()}</main>`;
}

// ------------------------------------------------------------------ vista: giocatori
function viewPlayers(q) {
  const segHtml = sportSeg(false);
  const sport = S.sport;
  if (q.g !== undefined) {
    S.game = q.g;
    for (const sp of PROP_SPORTS) if (gamesList(sp).some(x => x.id === q.g)) { S.sport = sp; return viewPlayers({}); }
  }
  const m = mkOf(sport);
  const all = players(sport).filter(p => p.mk && p.mk[m]);
  const games = gamesList(sport).map(g => sport === 'soccer' ? [g.id, `${g.h} – ${g.a}`, g.t] : [g.id, `${g.a} @ ${g.h}`, g.t]);
  games.sort((a, b) => a[2].localeCompare(b[2]));
  if (S.game && !games.some(g => g[0] === S.game)) S.game = '';
  const term = S.search.trim().toLowerCase();
  let rows = all.filter(p => (!S.game || p.g === S.game) && (!term || p.n.toLowerCase().includes(term) || p.t.toLowerCase().includes(term)))
    .map(p => ({ p, e: evaluate(sport, p, m) }));
  if (S.onlyValue) rows = rows.filter(r => r.e.ev !== null && r.e.ev > 0);
  rows.sort((a, b) => {
    if (S.sort === 'valore') {
      const av = a.e.ev === null ? -9 : a.e.ev, bv = b.e.ev === null ? -9 : b.e.ev;
      if (av !== bv) return bv - av;
    }
    return b.e.mu - a.e.mu;
  });
  const shown = rows.slice(0, 120);
  const list = shown.map(({ p, e }) => playerRow(sport, p, m, e)).join('') ||
    '<div class="empty">Nessun giocatore per questi filtri.</div>';
  return header('Prop giocatori', 'Statistiche giocatori', null, `<div class="row"><a class="iconbtn" href="#/incolla" aria-label="Incolla quote">${ICON_PASTE}</a>${searchBtn()}</div>`) + `<div style="padding:0 16px;display:flex;flex-direction:column;gap:10px">
    ${segHtml}
    <div class="chips">${MARKETS[sport].map(([k, l]) => `<button class="chip ${k === m ? 'on' : ''}" data-act="market" data-v="${k}">${l}</button>`).join('')}</div>
    <div class="row">
      <input class="search" type="search" placeholder="Cerca giocatore o squadra" aria-label="Cerca giocatore o squadra" data-act="search" value="${esc(S.search)}">
    </div>
    <div class="row wrap">
      <select class="sel" aria-label="Partita" data-act="game"><option value="">Tutte le partite</option>${games.map(([id, l, t]) => `<option value="${esc(id)}" ${id === S.game ? 'selected' : ''}>${esc(l)} · ${esc(fmtTime(t))}</option>`).join('')}</select>
      <button class="chip ${S.onlyValue ? 'on' : ''}" data-act="onlyValue" data-v="${S.onlyValue ? 0 : 1}">Solo valore</button>
      <button class="chip" data-act="sort">${S.sort === 'valore' ? 'Ordina: valore' : 'Ordina: proiezione'}</button>
    </div></div></header>
    <main>${list}${rows.length > 120 ? `<p class="note">Mostrati 120 di ${rows.length}: usa i filtri.</p>` : ''}
    <p class="note">Senza quote la linea mostrata è quella più vicina alla proiezione. Inserisci linea e quota del tuo bookmaker nella scheda del giocatore per vedere il valore.</p>${updatedLine()}</main>`;
}
function playerRow(sport, p, m, e) {
  const hits = hitRate(sport, p, m, e.line, e.side);
  const nh = hits.filter(Boolean).length;
  const val = e.ev !== null && e.ev > 0;
  const status = p.st ? `<span class="badge warn">${esc(p.st)}</span>` : '';
  const badge = e.ev === null ? status : (e.ev > 0.15 ? `<span class="badge warn">Da verificare ${sgn(e.ev, 0)}</span>` : val ? `<span class="badge val">EV ${sgn(e.ev)}</span>` : '<span class="badge no">Nessun valore</span>');
  const sideLbl = BERNOULLI.has(m) ? (e.side === 'over' ? 'Sì' : 'No') : (e.side === 'over' ? 'O' : 'U');
  const xi = expInfo(sport, p);
  const sub = sport === 'soccer' ? ` · titolare ${pct(p.ps)}${p.lu ? ' (formazione ufficiale)' : ''}` : sport === 'nba' ? ` · ${p.m.toFixed(0)} min${p.rel ? ' · affidabilità ' + REL[p.rel] : ''}` : (p.pos ? ' · ' + p.pos : '');
  const warn = e.ev !== null && e.ev > 0.15;
  return `<a class="card ${val ? 'value' : ''}" href="#/g/${sport}/${esc(p.id)}/${esc(p.g)}?m=${m}">
    <div class="row between" style="align-items:flex-start">
      <div class="row" style="min-width:0"><span class="avatar">${esc(initials(p.n))}</span>
        <div style="display:flex;flex-direction:column;gap:2px;min-width:0"><span style="font-size:15px;font-weight:600">${esc(p.n)}</span>
        <span class="small muted">${esc(p.t)} vs ${esc(p.o)}${sub}</span></div></div>${badge}</div>
    <div class="grid4">
      <div class="kv"><span>Linea${e.src ? '' : ' (stima)'}</span><span>${sideLbl} ${e.line}</span></div>
      <div class="kv"><span>Quota</span><span>${e.odds ? e.odds.toFixed(2) : '—'}</span></div>
      <div class="kv"><span>Proiezione</span><span class="model">${BERNOULLI.has(m) ? pct(1 - Math.exp(-e.mu)) : e.mu.toFixed(1)}</span></div>
      <div class="kv"><span>Prob.</span><span class="model">${pct(e.p)}</span></div>
    </div>
    <div class="row"><span class="tiny muted" style="width:64px">Ultime ${hits.length}</span>
      <div class="hits">${hits.map(h => `<span class="${h ? 'y' : ''}"></span>`).join('')}</div>
      <span class="mono small" style="color:var(--text2)">${nh}/${hits.length}</span></div></a>`;
}

// ------------------------------------------------------------------ vista: giocatore
function viewPlayer(sport, id, g, mq) {
  const p = findPlayer(sport, id, g);
  if (!p) return header('Giocatore', '', '#/giocatori') + '</header><main><div class="empty">Giocatore non presente nelle prossime partite.</div></main>';
  if (sport !== S.sport) { S.sport = sport; }
  const m = p.mk[mq] ? mq : (p.mk[mkOf(sport)] ? mkOf(sport) : mkList(sport, p)[0][0]);
  const e = evaluate(sport, p, m);
  const key = oddsKey(sport, p, m);
  const off = L_OFF[sport];
  const vals = p.l.map(x => marketValue(sport, m, x, off));
  const max = Math.max(e.line * 1.25, ...vals, 1);
  const H = 120;
  const hitsO = vals.filter(v => v > e.line).length;
  const bern = BERNOULLI.has(m);
  const kO = e.over ? kelly(e.pOver, e.over, e.push) * S.kellyFrac : 0;
  const kU = e.under ? kelly(e.pUnder, e.under, e.push) * S.kellyFrac : 0;
  const evO = e.over ? ev(e.pOver, e.over, e.push) : null;
  const evU = e.under ? ev(e.pUnder, e.under, e.push) : null;
  const avg10 = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 0;
  ensureHist();
  const ht = hitTable(sport, p, m, e.line, 'over');
  let altHtml = '';
  if (!bern) {
    const step = 1;
    let lo = Math.max(0.5, e.line - 3 * step);
    const lines = [];
    for (let L = lo; lines.length < 7; L += step) lines.push(L);
    altHtml = `<div class="card" style="gap:0"><h2 style="padding-bottom:8px">Linee alternative</h2>
      <div style="display:grid;grid-template-columns:0.8fr 1fr 1fr 1fr 1fr 0.8fr;gap:4px;padding-bottom:6px" class="tiny muted"><span>Linea</span><span>P over</span><span>Quota giusta</span><span>P under</span><span>Quota giusta</span><span>U10</span></div>
      ${lines.map(L => {
        const pr = probs(L, e.mu, e.r);
        const h10 = hitTable(sport, p, m, L, 'over').l10;
        const cur = L === Number(e.line);
        return `<div style="display:grid;grid-template-columns:0.8fr 1fr 1fr 1fr 1fr 0.8fr;gap:4px;padding:8px 0;border-top:1px solid var(--line);${cur ? 'background:var(--bg);' : ''}" class="mono small">
          <span class="b">${L}</span><span class="model b">${pct(pr.over, 1)}</span><span>${pr.over > 0 ? (1 / pr.over).toFixed(2) : '—'}</span>
          <span class="book b">${pct(pr.under, 1)}</span><span>${pr.under > 0 ? (1 / pr.under).toFixed(2) : '—'}</span>${fracCell(h10)}</div>`;
      }).join('')}
      <p class="note" style="margin-top:8px">Se il tuo bookmaker paga più della quota giusta, quella linea ha valore.</p></div>`;
  }
  const sideBox = (side, label, pp, q, e2, k) => {
    const good = e2 !== null && e2 > 0;
    return `<div class="cell ${good ? 'value' : ''}"><div class="row between"><span class="b">${label}</span><span class="mono model b">${pct(pp, 1)}</span></div>
      <span class="tiny muted">Quota giusta ${pp > 0 ? (1 / pp).toFixed(2) : '—'}</span>
      ${q ? `<span class="mono b ${good ? 'acc' : 'muted'}">EV ${sgn(e2)}${good ? ' · Kelly ' + pct(k, 1) : ''}</span>
        <button class="btn small ${good ? '' : 'ghost'}" data-act="addProp" data-side="${side}">Aggiungi</button>` : '<span class="tiny muted">Inserisci la quota</span>'}</div>`;
  };
  const factors = [];
  const xi = expInfo(sport, p);
  if (xi) factors.push(sport === 'nba' && p.m0 != null && Math.abs(p.m - p.m0) >= 0.5 ? [xi[0], `${p.m0.toFixed(1)} → ${p.m.toFixed(1)}`] : xi);
  if (sport === 'nba' && p.rel) factors.push(['Affidabilità (partite e stabilità minuti)', REL[p.rel]]);
  for (const a of p.adj || []) factors.push([a, '']);
  if (sport === 'soccer') factors.push(['Probabilità da titolare', pct(p.ps) + (p.lu ? ' (formazione ufficiale)' : '')]);
  factors.push(['Media ultime ' + vals.length, bern ? pct(avg10) : avg10.toFixed(1)]);
  factors.push(['Media ultime 30', bern ? pct(p.a30[m]) : Number(p.a30[m]).toFixed(1)]);
  const of = p.of[m] || 1;
  factors.push([`Avversario (${p.o}) concede`, (of >= 1 ? '+' : '−') + Math.abs((of - 1) * 100).toFixed(0) + '% vs media']);
  if (sport === 'soccer' && p.rf && (m === 'card' || m === 'fc')) factors.push(['Arbitro', (p.rf >= 1 ? '+' : '−') + Math.abs((p.rf - 1) * 100).toFixed(0) + '% cartellini']);
  factors.push([p.h ? 'In casa' : 'In trasferta', '']);
  if (p.st) factors.push(['Stato', p.st]);
  return header(p.n + ' · ' + mkLabel(sport, m), `${sportCtx(sport, p)} · ${p.t} vs ${p.o}`, '#/giocatori', `<a class="chip" style="display:flex;align-items:center;flex-shrink:0" href="#/p/${sport}/${esc(p.id)}/${esc(p.g)}">Tutti</a>`) + `
    <div style="padding:0 16px"><div class="chips">${mkList(sport, p).map(([k, l]) => `<a class="chip ${k === m ? 'on' : ''}" style="display:flex;align-items:center" href="#/g/${sport}/${esc(p.id)}/${esc(p.g)}?m=${k}">${l}</a>`).join('')}</div></div></header>
    <main>
      <div class="card">
        <div class="grid3">
          <div class="kv"><span>Proiezione</span><span class="model big">${bern ? pct(1 - Math.exp(-e.mu)) : e.mu.toFixed(1)}</span></div>
          <div class="kv"><span>Sopra la linea</span><span class="big">${hitsO}/${vals.length}</span></div>
          <div class="kv"><span>Fonte quote</span><span style="font-size:13px">${esc(e.src || '—')}</span></div>
        </div>
        <div class="grid3">
          <div class="field"><label for="in-line">Linea</label><input id="in-line" inputmode="decimal" data-act="odds" data-k="line" value="${e.line}"></div>
          <div class="field"><label for="in-over">Quota ${bern ? 'Sì' : 'Over'}</label><input id="in-over" inputmode="decimal" data-act="odds" data-k="over" value="${e.over || ''}" placeholder="—"></div>
          <div class="field"><label for="in-under">Quota ${bern ? 'No' : 'Under'}</label><input id="in-under" inputmode="decimal" data-act="odds" data-k="under" value="${e.under || ''}" placeholder="—"></div>
        </div>
        <div class="grid2">${sideBox('over', bern ? 'Sì' : 'Over ' + e.line, e.pOver, e.over, evO, kO)}${sideBox('under', bern ? 'No' : 'Under ' + e.line, e.pUnder, e.under, evU, kU)}</div>
        ${S.manual[key] ? '<button class="chip" data-act="clearOdds" style="align-self:flex-start">Ripristina quote automatiche</button>' : ''}
      </div>
      <div class="card" style="gap:8px"><h2>Sopra ${e.line}: frequenza</h2>
        <div class="grid4">${[['Ultime 5', ht.l5], ['Ultime 10', ht.l10], ['Ultime 20', ht.l20], ['Stagione', ht.sea]].map(([k, x]) =>
          `<div class="kv"><span>${k}</span>${fracCell(x)}</div>`).join('')}</div></div>
      <div class="card"><div class="row between"><h2>Ultime ${vals.length} partite</h2><span class="mono small">linea ${e.line}</span></div>
        <div class="chart"><div class="line" style="bottom:${(e.line / max * H).toFixed(0)}px"></div>
          ${vals.slice().reverse().map(v => `<div class="col"><b>${v}</b><div class="${v > e.line ? 'y' : ''}" style="height:${Math.max(2, v / max * H).toFixed(0)}px"></div></div>`).join('')}</div>
        <div class="xlabels">${p.l.slice().reverse().map(x => `<span title="${esc(x[0])}">${esc(x[1])}</span>`).join('')}</div></div>
      ${altHtml}
      <div class="card"><h2>Da dove arriva la proiezione</h2>
        <div>${factors.map(([k, v]) => `<div class="list-row"><span style="color:var(--text2)">${esc(k)}</span><span class="mono b">${esc(v)}</span></div>`).join('')}</div>
        ${e.ev !== null && e.ev > 0.15 ? '<div class="warnbox"><span>Valore molto alto: prima di giocare controlla minuti/ruolo, infortuni e che linea e quota siano giuste. I vantaggi reali di solito sono tra +2% e +8%. La puntata consigliata viene ridotta.</span></div>' : ''}
        <p class="note">Tasso per unità di gioco (minuti, turni in battuta, eliminazioni o partite) pesato sulle partite recenti e corretto verso la media del ruolo, moltiplicato per quanto giocherà e per i fattori avversario${sport === 'soccer' ? ', casa/trasferta e arbitro' : ' e casa/trasferta'}. La distribuzione tiene conto della variabilità del giocatore.</p></div>
      ${updatedLine()}
    </main>`;
}

// ------------------------------------------------------------------ storico lungo (caricato su richiesta)
function ensureHist() {
  if (S.hist || S.histLoading) return;
  S.histLoading = true;
  fetchData('hist').catch(() => null)
    .then(h => { S.hist = h || { nba: {}, soccer: {} }; S.histLoading = false; render(); });
}
const seasonStart = sport => {
  const d = new Date();
  const y = d.getFullYear(), mo = d.getMonth() + 1;
  if (sport === 'nba') return `${mo >= 10 ? y : y - 1}-10-01`;
  if (sport === 'nfl') return `${mo >= 8 ? y : y - 1}-08-01`;
  if (sport === 'mlb') return `${mo >= 3 ? y : y - 1}-03-01`;
  return `${mo >= 7 ? y : y - 1}-07-01`;
};
function gamesOf(sport, p) { return (S.hist && S.hist[sport] && S.hist[sport][p.id]) || p.l; }
/** Frazioni sopra la linea su ultime 5/10/20 e stagione */
function hitTable(sport, p, m, line, side) {
  const rows = gamesOf(sport, p), off = L_OFF[sport];
  const ok = g => { const v = marketValue(sport, m, g, off); return side === 'under' ? v < line : v > line; };
  const ss = seasonStart(sport);
  const seas = rows.filter(g => g[0] >= ss);
  const f = list => list.length ? [list.filter(ok).length, list.length] : null;
  return { l5: f(rows.slice(0, 5)), l10: f(rows.slice(0, 10)), l20: rows.length >= 11 ? f(rows.slice(0, 20)) : null, sea: f(seas) };
}
function fracCell(x) {
  if (!x) return '<span class="muted mono small">—</span>';
  const r = x[0] / x[1];
  const col = r >= 0.6 ? 'var(--model)' : r <= 0.4 ? 'var(--book)' : 'var(--text2)';
  return `<span class="mono small b" style="color:${col}">${x[0]}/${x[1]}</span>`;
}

// ------------------------------------------------------------------ vista: ricerca globale
function normTxt(t) { return String(t || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase(); }
function viewSearch() {
  const term = normTxt(S.gsearch || '').trim();
  let res = [];
  if (term.length >= 2) {
    const toks = term.split(/\s+/);
    for (const sport of PROP_SPORTS) {
      for (const p of players(sport)) {
        const hay = normTxt(p.n + ' ' + p.t);
        if (toks.every(t => hay.includes(t))) res.push({ sport, p });
      }
    }
  }
  res.sort((a, b) => a.p.n.localeCompare(b.p.n));
  const list = res.slice(0, 60).map(({ sport, p }) => {
    const gm = gamesList(sport).find(g => g.id === p.g);
    const lg = sportCtx(sport, p);
    return `<a class="card" style="flex-direction:row;align-items:center;gap:12px" href="#/p/${sport}/${esc(p.id)}/${esc(p.g)}">
      <span class="avatar">${esc(initials(p.n))}</span>
      <div style="display:flex;flex-direction:column;gap:2px;min-width:0;flex:1"><span style="font-size:15px;font-weight:600">${esc(p.n)}</span>
      <span class="small muted">${esc(lg)} · ${esc(p.t)} vs ${esc(p.o)}${gm ? ' · ' + esc(fmtTime(gm.t)) : ''}</span></div>
      ${p.st ? `<span class="badge warn">${esc(p.st)}</span>` : ''}</a>`;
  }).join('');
  return header('Cerca', 'Tutti gli sport', '#/giocatori') + `<div style="padding:0 16px">
    <input class="search" type="search" placeholder="Nome del giocatore o squadra" aria-label="Cerca giocatore o squadra" data-act="gsearch" value="${esc(S.gsearch || '')}"></div></header>
    <main>${term.length < 2 ? '<p class="note">Scrivi almeno 2 lettere. Trovi i giocatori delle partite dei prossimi giorni.</p>' : (list || '<div class="empty">Nessun giocatore trovato nelle prossime partite.</div>')}</main>`;
}

// ------------------------------------------------------------------ vista: scheda completa del giocatore
function viewCard(sport, id, g) {
  const p = findPlayer(sport, id, g);
  if (!p) return header('Giocatore', '', '#/cerca') + '</header><main><div class="empty">Giocatore non presente nelle prossime partite.</div></main>';
  ensureHist();
  const rows = mkList(sport, p).map(([m, label]) => {
    const e = evaluate(sport, p, m);
    const ht = hitTable(sport, p, m, e.line, e.side);
    const bern = BERNOULLI.has(m);
    const val = e.ev !== null && e.ev > 0;
    const sideLbl = bern ? (e.side === 'over' ? 'Sì' : 'No') : (e.side === 'over' ? 'O' : 'U');
    return `<a href="#/g/${sport}/${esc(p.id)}/${esc(p.g)}?m=${m}" style="display:grid;grid-template-columns:minmax(0,1.3fr) 0.9fr 0.8fr repeat(4,0.62fr);gap:4px;align-items:center;padding:10px 0;border-top:1px solid var(--line)">
      <span style="font-size:13px;font-weight:600">${label}${val ? ` <span class="badge val" style="font-size:10px;padding:1px 6px">${sgn(e.ev, 0)}</span>` : ''}</span>
      <span class="mono small b" style="white-space:nowrap;font-size:12px">${sideLbl} ${e.line}${e.odds ? `<span class="tiny muted" style="display:block">@${e.odds.toFixed(2)}</span>` : ''}</span>
      <span class="mono small b model">${pct(e.p)}<span class="tiny muted" style="display:block">${bern ? '' : 'proj ' + e.mu.toFixed(1)}</span></span>
      ${fracCell(ht.l5)}${fracCell(ht.l10)}${fracCell(ht.l20)}${fracCell(ht.sea)}</a>`;
  }).join('');
  const vs = gamesOf(sport, p).filter(x => x[1] === p.o).slice(0, 6);
  const COLS = {
    nba: [['PTS', 'pts'], ['REB', 'reb'], ['AST', 'ast'], ['3PT', 'fg3m'], ['STL', 'stl'], ['BLK', 'blk']],
    soccer: [['Tiri', 'shots'], ['In porta', 'sot'], ['Falli', 'fc'], ['Subiti', 'fs'], ['Gialli', 'card'], ['Gol', 'g']],
    nfl: [['P.YD', 'pass_yds'], ['P.TD', 'pass_td'], ['CORSE', 'rush_att'], ['C.YD', 'rush_yds'], ['REC', 'rec'], ['R.YD', 'rec_yds']],
    mlb: String(p.id).endsWith('p') ? [['OUT', 'outs'], ['K', 'p_k'], ['ER', 'er'], ['H', 'p_h'], ['BB', 'p_bb'], ['', 'p_bb']]
      : [['H', 'h'], ['R', 'r'], ['RBI', 'rbi'], ['HR', 'hr'], ['BB', 'bb'], ['K', 'so']],
  };
  const cols = COLS[sport];
  const off = L_OFF[sport];
  const vsHtml = vs.length ? `<div style="display:grid;grid-template-columns:1.2fr repeat(7,1fr);gap:4px;font-size:11px" class="muted"><span>Data</span><span>${sport === 'nfl' ? '' : sport === 'mlb' ? (String(p.id).endsWith('p') ? 'OUT' : 'PA') : 'Min'}</span>${cols.map(c => `<span>${c[0]}</span>`).join('')}</div>` +
    vs.map(x => `<div style="display:grid;grid-template-columns:1.2fr repeat(7,1fr);gap:4px;padding:6px 0;border-top:1px solid var(--line)" class="mono small">
      <span>${esc(fmtDate(x[0]))}</span><span>${sport === 'nfl' ? '' : x[2]}</span>${cols.map(c => `<span class="b">${marketValue(sport, c[1], x, off)}</span>`).join('')}</div>`).join('')
    : `<p class="note">Nessuna partita contro ${esc(p.o)} nello storico disponibile.</p>`;
  const lg = sportCtx(sport, p);
  const xi = expInfo(sport, p);
  return header(p.n, `${lg} · ${p.t} vs ${p.o}`, 'javascript:history.back()') + `</header><main>
    <div class="grid3">
      <div class="card" style="padding:12px;gap:2px"><span class="tiny muted">${xi ? xi[0] : 'Partite recenti'}</span><span class="mono b">${xi ? xi[1] : p.l.length}</span></div>
      <div class="card" style="padding:12px;gap:2px"><span class="tiny muted">${sport === 'soccer' ? 'Titolare' : 'Ruolo'}</span><span class="mono b">${sport === 'soccer' ? pct(p.ps) + (p.lu ? ' ✓' : '') : esc(p.pos || '—')}</span></div>
      <div class="card" style="padding:12px;gap:2px"><span class="tiny muted">${p.h ? 'In casa' : 'Trasferta'}</span><span class="mono b" style="font-size:13px">${p.st ? esc(p.st) : 'Disponibile'}</span></div>
    </div>
    ${(p.adj && p.adj.length) || p.rel ? `<div class="card" style="gap:4px">${p.rel ? `<div class="list-row" style="border-top:0"><span>Affidabilità</span><span class="mono b">${REL[p.rel]}</span></div>` : ''}${(p.adj || []).map(a => `<div class="list-row"><span style="color:var(--text2)">${esc(a)}</span></div>`).join('')}</div>` : ''}
    <div class="card" style="gap:0">
      <div style="display:grid;grid-template-columns:minmax(0,1.3fr) 0.9fr 0.8fr repeat(4,0.62fr);gap:4px;padding-bottom:8px" class="tiny muted">
        <span>Mercato</span><span>Linea</span><span>Prob.</span><span>U5</span><span>U10</span><span>U20</span><span>Stag.</span></div>
      ${rows}
      <p class="note" style="margin-top:10px">U5/U10/U20 = volte sopra la linea nelle ultime 5, 10, 20 partite; Stag. = stagione in corso.${S.hist ? '' : ' Carico lo storico completo…'} Tocca un mercato per inserire le quote.</p>
    </div>
    <div class="card"><h2>Contro ${esc(p.o)}</h2>${vsHtml}</div>
    ${updatedLine()}</main>`;
}

// ------------------------------------------------------------------ vista: incolla quote
const MK_WORDS = {
  nba: [['p+r+a', 'pra'], ['pra', 'pra'], ['punti+rimbalzi+assist', 'pra'], ['punti rimbalzi assist', 'pra'], ['p+r', 'pr'], ['punti+rimbalzi', 'pr'], ['p+a', 'pa'], ['punti+assist', 'pa'],
    ['r+a', 'ra'], ['rimbalzi+assist', 'ra'], ['rub+stop', 'sb'], ['stocks', 'sb'], ['palle perse', 'tov'], ['turnovers', 'tov'], ['tov', 'tov'],
    ['tiri da tre', 'fg3m'], ['triple', 'fg3m'], ['tripla', 'fg3m'], ['threes', 'fg3m'], ['3pt', 'fg3m'], ['3pm', 'fg3m'],
    ['stoppate', 'blk'], ['stoppata', 'blk'], ['blocks', 'blk'], ['blk', 'blk'], ['rubate', 'stl'], ['rubata', 'stl'], ['steals', 'stl'], ['stl', 'stl'],
    ['rimbalzi', 'reb'], ['rebounds', 'reb'], ['reb', 'reb'], ['punti', 'pts'], ['points', 'pts'], ['pts', 'pts'], ['assist', 'ast'], ['ast', 'ast'], ['pr', 'pr'], ['pa', 'pa'], ['ra', 'ra']],
  nfl: [['yard passate', 'pass_yds'], ['passing yards', 'pass_yds'], ['pass yds', 'pass_yds'], ['td passati', 'pass_td'], ['passing td', 'pass_td'],
    ['passaggi completati', 'pass_cmp'], ['completions', 'pass_cmp'], ['passaggi tentati', 'pass_att'], ['intercetti', 'int'], ['interceptions', 'int'],
    ['yard corse+ricevute', 'rr_yds'], ['rush+rec', 'rr_yds'], ['yard corse', 'rush_yds'], ['rushing yards', 'rush_yds'], ['rush yds', 'rush_yds'],
    ['corse', 'rush_att'], ['ricezioni', 'rec'], ['receptions', 'rec'], ['yard ricevute', 'rec_yds'], ['receiving yards', 'rec_yds'], ['rec yds', 'rec_yds'],
    ['touchdown', 'td'], ['anytime td', 'td'], ['td', 'td']],
  mlb: [['h+r+rbi', 'hrr'], ['hrr', 'hrr'], ['valide', 'h'], ['hits', 'h'], ['rbi', 'rbi'], ['fuoricampo', 'hr'], ['home run', 'hr'], ['homer', 'hr'],
    ['strikeout lanciatore', 'p_k'], ['strikeouts', 'p_k'], ['strikeout', 'p_k'], ['eliminazioni', 'outs'], ['outs', 'outs'], ['punti concessi', 'er'],
    ['earned runs', 'er'], ['basi su ball', 'bb'], ['walks', 'bb'], ['runs', 'r']],
  soccer: [['tiri in porta', 'sot'], ['tiro in porta', 'sot'], ['shots on target', 'sot'], ['sot', 'sot'], ['tip', 'sot'], ['falli subiti', 'fs'], ['falli commessi', 'fc'], ['falli', 'fc'], ['fouls', 'fc'],
    ['cartellino', 'card'], ['ammonito', 'card'], ['ammonizione', 'card'], ['giallo', 'card'], ['card', 'card'], ['gol o assist', 'goa'], ['segna o assist', 'goa'], ['gol+assist', 'ga'], ['g+a', 'ga'],
    ['marcatore', 'g'], ['segna', 'g'], ['gol', 'g'], ['goal', 'g'], ['tiri', 'shots'], ['tiro', 'shots'], ['shots', 'shots'], ['assist', 'a']],
};
function parseLine(raw) {
  let t = ' ' + normTxt(raw).replace(/(\d),(\d)/g, '$1.$2').replace(/[;|\t'-]/g, ' ') + ' ';
  let side = 'over';
  const sideRe = [[/\s(under|sotto|meno|no|u)\s/, 'under'], [/\s(over|sopra|piu|si|yes|o)\s/, 'over']];
  for (const [re, sd] of sideRe) { const m = t.match(re); if (m) { side = sd; t = t.replace(re, ' '); break; } }
  const found = {};
  for (const sp of PROP_SPORTS) {
    for (const [w, m] of MK_WORDS[sp]) {
      const re = new RegExp('(^|\\s)' + w.replace(/[+]/g, '\\+') + '(\\s|$)');
      if (re.test(t)) { found[sp] = { m, w }; break; }
    }
  }
  let nums = (t.match(/\d+(?:\.\d+)?/g) || []).map(Number);
  let words = t;
  for (const sp in found) words = words.replace(new RegExp('(^|\\s)' + found[sp].w.replace(/[+]/g, '\\+') + '(?=\\s|$)'), ' ');
  words = words.replace(/\d+(?:\.\d+)?/g, ' ').replace(/[@+]/g, ' ').split(/\s+/).filter(x => x.length >= 2);
  // giocatore
  let best = null;
  for (const sp of PROP_SPORTS) {
    if (Object.keys(found).length && !found[sp]) continue;
    for (const p of players(sp)) {
      const nt = normTxt(p.n).split(/[\s'-]+/);
      let sc = 0;
      for (const w of words) if (nt.some(x => x === w || (w.length >= 4 && (x.startsWith(w) || w.startsWith(x)) && x.length >= 4))) sc++;
      if (!sc && nt.length >= 2 && words.some(w => w.length >= 2 && w === nt.map(x => x[0]).join(''))) sc = words.length; // sigle: SGA, KAT
      if (!sc) continue;
      const score = sc / Math.max(words.length, 1) + (nt.includes(words[words.length - 1]) ? 0.01 : 0);
      if (!best || score > best.score) best = { score, sport: sp, p };
    }
  }
  const r = { raw, side, line: null, odds: null, p: null, sport: null, m: null, err: '' };
  if (!best || best.score < 0.5) { r.err = 'giocatore non trovato'; return r; }
  r.p = best.p; r.sport = best.sport;
  r.m = found[r.sport] ? found[r.sport].m : null;
  if (!r.m) { r.err = 'mercato non riconosciuto'; return r; }
  const bern = BERNOULLI.has(r.m) || r.m === 'g' || r.m === 'a';
  // i numeri vanno letti dopo aver tolto il nome del giocatore
  let rest = t;
  for (const x of normTxt(r.p.n).split(/[\s'-]+/).filter(Boolean)) rest = rest.replace(new RegExp('(^|\\s)' + x.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(?=\\s|$)', 'g'), ' ');
  nums = (rest.match(/\d+(?:\.\d+)?/g) || []).map(Number);
  if (nums.length >= 2) { r.line = nums[0]; r.odds = nums[nums.length - 1]; }
  else if (nums.length === 1) { if (bern && nums[0] > 1) { r.line = 0.5; r.odds = nums[0]; } else r.line = nums[0]; }
  else if (bern) r.line = 0.5;
  if (r.line === null) r.err = 'linea mancante';
  if (r.odds !== null && !(r.odds > 1 && r.odds < 100)) { r.odds = null; }
  return r;
}
function parsePaste(text) { return String(text || '').split(/\n+/).map(x => x.trim()).filter(Boolean).slice(0, 60).map(parseLine); }
function savePasteOdds(r) {
  const k = oddsKey(r.sport, r.p, r.m);
  const cur = S.manual[k] && S.manual[k].line === r.line ? S.manual[k] : { line: r.line, over: null, under: null };
  cur.line = r.line;
  if (r.odds) cur[r.side] = r.odds;
  S.manual[k] = cur;
}
function viewPaste() {
  const rows = (S.pasteRows || []).map((r, i) => {
    if (r.err) return `<div class="list-row"><span class="small">${esc(r.raw)}</span><span class="badge warn">${esc(r.err)}</span></div>`;
    const [mu, rr] = r.p.mk[r.m] || [0, null];
    const pr = probs(r.line, mu, rr);
    const pp = r.side === 'over' ? pr.over : pr.under;
    const e = r.odds ? ev(pp, r.odds, pr.push) : null;
    const bern = BERNOULLI.has(r.m);
    return `<div style="display:flex;flex-direction:column;gap:6px;padding:10px 0;border-top:1px solid var(--line)">
      <div class="row between"><a href="#/g/${r.sport}/${esc(r.p.id)}/${esc(r.p.g)}?m=${r.m}" class="b" style="font-size:14px">${esc(r.p.n)}</a>
        ${e !== null ? `<span class="badge ${e > 0 ? 'val' : 'no'}">EV ${sgn(e)}</span>` : '<span class="badge no">senza quota</span>'}</div>
      <div class="row between"><span class="small muted">${esc(mkLabel(r.sport, r.m))} · ${bern ? (r.side === 'over' ? 'Sì' : 'No') : (r.side === 'over' ? 'Over' : 'Under') + ' ' + r.line}${r.odds ? ' @' + r.odds.toFixed(2) : ''} · ${esc(r.p.t)} vs ${esc(r.p.o)}</span>
        <span class="mono small b model">${pct(pp, 1)}</span></div>
      ${r.odds ? `<button class="btn small ${e > 0 ? '' : 'ghost'}" data-act="pasteAdd" data-i="${i}">Aggiungi alla schedina</button>` : ''}</div>`;
  }).join('');
  return header('Incolla quote', 'Più prop in una volta', '#/giocatori') + `</header><main>
    <div class="card">
      <label class="small muted" for="pasteBox">Una prop per riga: giocatore, over/under, linea, mercato, quota</label>
      <textarea id="pasteBox" data-act="paste" rows="6" style="width:100%;border-radius:10px;border:1px solid var(--line);background:var(--bg);padding:10px;font:500 15px var(--mono);color:var(--text);resize:vertical" placeholder="Tatum over 27.5 punti 1.87&#10;Jokic u 10.5 assist 1.95&#10;Lautaro over 1.5 tiri in porta 2.05&#10;Barella cartellino 3.75">${esc(S.pasteText || '')}</textarea>
      <button class="btn" data-act="parse">Valuta</button>
    </div>
    ${rows ? `<div class="card" style="gap:0"><div class="row between" style="padding-bottom:8px"><h2>Risultato</h2><button class="chip" data-act="pasteSave">Salva quote nelle schede</button></div>${rows}</div>` : ''}
    <p class="note">Funziona con i giocatori delle partite dei prossimi giorni. Abbreviazioni accettate: o/u, pts, reb, ast, 3pt, blk, stl, pra, p+r, p+a, r+a, sot, tiri, falli, cartellino, gol.</p>
  </main>`;
}

// ------------------------------------------------------------------ vista: schedina
function viewSlip() {
  const items = S.slip;
  if (S.slipMode === 'multi' && items.length >= 2) return viewSlipMulti();
  let total = 0, evTot = 0;
  const rows = items.map((s, i) => {
    const sug = suggestedStake(s);
    const stake = s.stake != null ? s.stake : Math.round(sug * 100) / 100;
    const e = ev(s.p, s.odds, s.push || 0);
    total += stake; evTot += stake * e;
    return `<div class="card"><div class="row between" style="align-items:flex-start">
      <div style="display:flex;flex-direction:column;gap:2px;min-width:0"><span class="small muted">${esc(s.ctx)}</span><span style="font-size:15px;font-weight:600">${esc(s.label)}</span></div>
      <div class="row"><span class="mono big">${s.odds.toFixed(2)}</span><button class="iconbtn" style="width:36px;height:36px" aria-label="Rimuovi" data-act="rmSlip" data-i="${i}">${ICON_X}</button></div></div>
      <div class="grid3"><div class="kv"><span>Modello</span><span class="model">${pct(s.p, 1)}</span></div>
        <div class="kv"><span>EV</span><span class="${e > 0 ? 'acc' : 'book'}">${sgn(e)}</span></div>
        <div class="field"><label for="st-${i}">Puntata €</label><input id="st-${i}" inputmode="decimal" data-act="stake" data-i="${i}" value="${stake.toFixed(2)}"></div></div>
      <span class="tiny muted">${sug > 0 ? 'Suggerita (Kelly): ' + eur(sug) : 'Valore atteso negativo: il modello suggerisce di non giocarla.'}</span></div>`;
  }).join('');
  return header('Schedina', items.length + (items.length === 1 ? ' selezione' : ' selezioni')) + slipModeSeg() + `</header><main>
    ${bankrollCard()}
    ${rows || '<div class="empty">Nessuna selezione. Aggiungile dalla scheda di un giocatore o di una partita, o dalla pagina Chicche.</div>'}
    ${items.length ? `<div class="card">
      <div class="row between"><span class="muted">Puntata totale</span><span class="mono b">${eur(total)}</span></div>
      <div class="row between"><span class="muted">Esposizione sul bankroll</span><span class="mono b">${S.bankroll ? pct(total / S.bankroll, 1) : '—'}</span></div>
      <div class="row between"><span class="muted">Guadagno atteso (EV)</span><span class="mono b ${evTot >= 0 ? 'acc' : 'book'}">${evTot >= 0 ? '+' : '−'}${eur(Math.abs(evTot))}</span></div>
      <p class="note">Puntate singole: ogni selezione è una scommessa separata.</p></div>
      <button class="btn" data-act="register">Registra le scommesse</button>
      <button class="btn ghost" data-act="clearSlip">Svuota schedina</button>` : ''}
    ${slipWarn()}
  </main>`;
}
function slipModeSeg() {
  return `<div style="padding:0 16px"><div class="seg">${[['single', 'Singole'], ['multi', 'Multipla']].map(([k, l]) =>
    `<button class="${S.slipMode === k ? 'on' : ''}" data-act="slipMode" data-v="${k}">${l}</button>`).join('')}</div>
    ${S.slipMode === 'multi' && S.slip.length < 2 ? '<p class="note" style="margin-top:8px">Per una multipla servono almeno 2 selezioni.</p>' : ''}</div>`;
}
const slipWarn = () => '<div class="warnbox"><span>Le probabilità sono stime, non certezze. Imposta un limite di spesa e rispettalo. Il gioco è vietato ai minori di 18 anni e può causare dipendenza.</span></div>';
function bankrollCard() {
  return `<div class="card"><div class="row between"><label class="muted small" for="bankroll">Bankroll €</label>
      <input id="bankroll" class="search mono" style="max-width:150px;text-align:right;font-weight:700" inputmode="decimal" data-act="bankroll" value="${S.bankroll}"></div>
      <div style="display:flex;flex-direction:column;gap:8px"><span class="small muted">Frazione di Kelly</span>
      <div class="seg">${[[0.25, 'Kelly ¼'], [0.5, 'Kelly ½'], [1, 'Kelly pieno']].map(([v, l]) => `<button class="${S.kellyFrac === v ? 'on' : ''}" data-act="kelly" data-v="${v}">${l}</button>`).join('')}</div></div></div>`;
}
function viewSlipMulti() {
  const legs = S.slip;
  const mi = multiInfo(legs);
  const sug = suggestedStake({ p: mi.p, odds: mi.odds, push: 0 });
  const stake = S.multiStake != null ? S.multiStake : Math.round(sug * 100) / 100;
  const rows = legs.map((s, i) => `<div class="list-row"><div style="display:flex;flex-direction:column;gap:2px;min-width:0">
      <span class="b" style="font-size:14px">${esc(s.label)}</span><span class="tiny muted">${esc(s.ctx)} · modello ${pct(s.p)} · EV ${sgn(ev(s.p, s.odds, s.push || 0))}</span></div>
      <div class="row"><span class="mono b">${s.odds.toFixed(2)}</span><button class="iconbtn" style="width:36px;height:36px" aria-label="Rimuovi" data-act="rmSlip" data-i="${i}">${ICON_X}</button></div></div>`).join('');
  return header('Multipla', legs.length + ' selezioni') + slipModeSeg() + `</header><main>
    ${bankrollCard()}
    <div class="card" style="gap:0">${rows}</div>
    <div class="card">
      <div class="grid3"><div class="kv"><span>Quota totale</span><span class="big">${mi.odds.toFixed(2)}</span></div>
        <div class="kv"><span>Probabilità</span><span class="model big">${pct(mi.p, 1)}</span></div>
        <div class="kv"><span>EV</span><span class="big ${mi.ev > 0 ? 'acc' : 'book'}">${sgn(mi.ev)}</span></div></div>
      <div class="row between"><label class="muted" for="mstake">Puntata €</label><input id="mstake" class="search mono" style="max-width:150px;text-align:right;font-weight:700" inputmode="decimal" data-act="multiStake" value="${stake.toFixed(2)}"></div>
      <div class="row between"><span class="muted">Vincita potenziale</span><span class="mono b">${eur(stake * mi.odds)}</span></div>
      <div class="row between"><span class="muted">Guadagno atteso (EV)</span><span class="mono b ${mi.ev >= 0 ? 'acc' : 'book'}">${mi.ev >= 0 ? '+' : '−'}${eur(Math.abs(stake * mi.ev))}</span></div>
      <span class="tiny muted">${sug > 0 ? 'Suggerita (Kelly): ' + eur(sug) : 'Valore atteso negativo: il modello suggerisce di non giocarla.'}</span>
      ${mi.sameGame ? '<div class="warnbox"><span>Ci sono più selezioni della stessa partita: gli esiti sono collegati (ad esempio punti e assist dello stesso giocatore) e la probabilità reale può essere diversa da quella calcolata. Molti bookmaker non accettano queste combinazioni.</span></div>' : ''}
      <p class="note">La probabilità della multipla è il prodotto delle probabilità delle singole selezioni. Il margine del bookmaker si moltiplica a ogni selezione: conviene solo se ogni selezione ha valore. Se una selezione viene annullata, la multipla prosegue con le altre.</p>
    </div>
    <button class="btn" data-act="registerMulti">Registra la multipla</button>
    <button class="btn ghost" data-act="clearSlip">Svuota schedina</button>
    ${slipWarn()}
  </main>`;
}
// ------------------------------------------------------------------ vista: ROI
function viewRoi() {
  const now = Date.now();
  const days = { d30: 30, d90: 90, all: 1e5 }[S.roiPeriod];
  const inPeriod = b => (now - new Date(b.ts).getTime()) / 864e5 <= days;
  const bets = S.bets.filter(inPeriod);
  const settled = bets.filter(b => b.status !== 'pending').sort((a, b) => (a.settled || a.ts).localeCompare(b.settled || b.ts));
  const graded = settled.filter(b => b.status !== 'void');
  const staked = graded.reduce((a, b) => a + b.stake, 0);
  const profit = settled.reduce((a, b) => a + (b.profit || 0), 0);
  const won = graded.filter(b => b.status === 'won').length;
  const evSum = graded.reduce((a, b) => a + b.stake * ev(b.p, b.odds), 0);
  const avgOdds = graded.length ? graded.reduce((a, b) => a + b.odds, 0) / graded.length : 0;
  // curva
  let cum = 0; const pts = [0];
  for (const b of settled) { cum += b.profit || 0; pts.push(cum); }
  const lo = Math.min(...pts), hi = Math.max(...pts), span = (hi - lo) || 1;
  const W = 326, H = 120;
  const poly = pts.map((v, i) => `${(i / Math.max(1, pts.length - 1) * W).toFixed(1)},${(H - 6 - (v - lo) / span * (H - 12)).toFixed(1)}`).join(' ');
  const zeroY = (H - 6 - (0 - lo) / span * (H - 12)).toFixed(1);
  // per mercato
  const byM = {};
  for (const b of graded) {
    const k = b.type === 'multi' ? 'Multiple' : (SPORT_LABEL[b.sport] || b.sport) + ' · ' + (b.pid ? mkLabel(b.sport, b.m) : (b.sport === 'tennis' ? 'Vincente' : '1X2'));
    const d = byM[k] = byM[k] || { n: 0, st: 0, pr: 0 };
    d.n++; d.st += b.stake; d.pr += b.profit || 0;
  }
  const mrows = Object.entries(byM).sort((a, b) => b[1].n - a[1].n).map(([k, d]) => {
    const r = d.st ? d.pr / d.st : 0;
    const w = Math.min(50, Math.abs(r) / 0.2 * 50);
    return `<div style="display:grid;grid-template-columns:130px 1fr 56px;align-items:center;gap:8px">
      <div style="display:flex;flex-direction:column"><span style="font-size:13px">${esc(k)}</span><span class="tiny muted">${d.n} scommesse</span></div>
      <div style="position:relative;height:10px;background:var(--line);border-radius:5px"><div style="position:absolute;left:50%;top:-3px;bottom:-3px;width:1px;background:var(--muted)"></div>
      <div style="position:absolute;top:0;bottom:0;border-radius:5px;width:${w}%;${r >= 0 ? 'left:50%;background:var(--model)' : 'right:50%;background:var(--book)'}"></div></div>
      <span class="mono small b" style="text-align:right;color:${r >= 0 ? 'var(--model)' : 'var(--book)'}">${sgn(r)}</span></div>`;
  }).join('');
  const pending = S.bets.filter(b => b.status === 'pending');
  const lbl = { won: 'Vinta', lost: 'Persa', void: 'Annullata', pending: 'In attesa' };
  const list = S.bets.slice().sort((a, b) => b.ts.localeCompare(a.ts)).slice(0, 40).map(b => {
    const i = S.bets.indexOf(b);
    const res = b.status === 'pending' ? `<span class="small muted">In attesa</span>`
      : `<span class="mono b" style="color:${b.status === 'won' ? 'var(--accent)' : b.status === 'lost' ? 'var(--book)' : 'var(--muted)'}">${b.status === 'void' ? 'Annullata' : (b.profit >= 0 ? '+' : '−') + eur(Math.abs(b.profit))}</span>`;
    return `<div style="display:flex;flex-direction:column;gap:6px;padding:10px 0;border-top:1px solid var(--line)">
      <div class="row between"><span class="b" style="font-size:13px">${esc(b.label)}</span>${res}</div>
      <div class="row between"><span class="tiny muted">${b.type === 'multi' ? '' : esc(b.ctx) + ' · '}@${b.odds.toFixed(2)} · ${eur(b.stake)}${b.actual != null ? ' · risultato ' + b.actual : ''}</span></div>
      ${b.type === 'multi' ? `<div style="display:flex;flex-direction:column;gap:2px">${b.legs.map(l => `<span class="tiny" style="color:${l.status === 'won' ? 'var(--accent)' : l.status === 'lost' ? 'var(--book)' : 'var(--muted)'}">${l.status === 'won' ? '✓' : l.status === 'lost' ? '✗' : l.status === 'void' ? '–' : '·'} ${esc(l.label)} @${l.odds.toFixed(2)}${l.actual != null ? ' (' + l.actual + ')' : ''}</span>`).join('')}</div>` : ''}
      ${b.status === 'pending' ? `<div class="row wrap">${['won', 'lost', 'void'].map(o => `<button class="chip" data-act="settle" data-i="${i}" data-v="${o}">${lbl[o]}</button>`).join('')}<button class="chip" data-act="delBet" data-i="${i}">Elimina</button></div>` : ''}</div>`;
  }).join('');
  return header('ROI', 'Registro scommesse') + `<div style="padding:0 16px"><div class="seg">${[['d30', '30 giorni'], ['d90', '90 giorni'], ['all', 'Tutto']].map(([k, l]) =>
    `<button class="${S.roiPeriod === k ? 'on' : ''}" data-act="period" data-v="${k}">${l}</button>`).join('')}</div></div></header><main>
    <div class="card"><div class="row between" style="align-items:flex-end">
      <div class="kv"><span>ROI (profitto / puntato)</span><span class="acc" style="font-size:34px">${staked ? sgn(profit / staked) : '—'}</span></div>
      <div class="kv" style="align-items:flex-end"><span>Profitto</span><span style="font-size:18px">${profit >= 0 ? '+' : '−'}${eur(Math.abs(profit))}</span></div></div>
      <svg class="curve" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Andamento del profitto">
        <line x1="0" y1="${zeroY}" x2="${W}" y2="${zeroY}" stroke="#3A4552" stroke-dasharray="4 4"></line>
        <polyline points="${poly}" fill="none" stroke="#C8F25A" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"></polyline></svg>
    </div>
    <div class="grid3">${[['Scommesse', String(graded.length)], ['Puntato', eur(staked)], ['Vinte', graded.length ? pct(won / graded.length, 1) : '—'],
      ['Quota media', avgOdds ? avgOdds.toFixed(2) : '—'], ['EV atteso', (evSum >= 0 ? '+' : '−') + eur(Math.abs(evSum))], ['In attesa', String(pending.length)]]
      .map(([k, v]) => `<div class="card" style="padding:12px;gap:2px"><span class="tiny muted">${k}</span><span class="mono b">${v}</span></div>`).join('')}</div>
    ${mrows ? `<div class="card"><h2>ROI per mercato</h2>${mrows}</div>` : ''}
    <div class="card"><h2>Scommesse</h2>${list || '<p class="note">Ancora nessuna scommessa registrata.</p>'}
      <p class="note">Le scommesse sui giocatori si chiudono da sole quando arriva il tabellino. Se il giocatore non scende in campo la scommessa risulta annullata.</p></div>
    <a class="btn ghost" href="#/stato">Stato dati e affidabilità del modello</a>
    ${S.locked ? '<button class="btn ghost" data-act="logout">Esci (dimentica il codice)</button>' : ''}
    <div class="card"><h2>Backup</h2><p class="note">Il registro è salvato su questo dispositivo. Esporta un file di backup per spostarlo su un altro telefono o PC.</p>
      <div class="row"><button class="btn ghost small" data-act="export">Esporta</button><label class="btn ghost small" style="cursor:pointer">Importa<input type="file" accept="application/json" data-act="import" hidden></label></div></div>
  </main>`;
}

// ------------------------------------------------------------------ eventi
function bind() {
  document.querySelectorAll('[data-act]').forEach(el => {
    const act = el.dataset.act;
    const evName = ['INPUT', 'SELECT', 'TEXTAREA'].includes(el.tagName) ? 'change' : 'click';
    el.addEventListener(evName, ev => handle(act, el, ev));
    if (act === 'search' || act === 'gsearch') el.addEventListener('input', () => {
      S[act] = el.value; clearTimeout(bind._t);
      bind._t = setTimeout(() => { render(); const s = document.querySelector('[data-act=' + act + ']'); if (s) { s.focus(); s.setSelectionRange(s.value.length, s.value.length); } }, 250);
    });
  });
}
function currentPlayer() {
  const { parts, q } = route();
  if (parts[0] !== 'g') return null;
  const p = findPlayer(parts[1], parts[2], parts[3]);
  const m = p && p.mk[q.m] ? q.m : (p && p.mk[mkOf(parts[1])] ? mkOf(parts[1]) : (p ? mkList(parts[1], p)[0][0] : null));
  return p ? { sport: parts[1], p, m } : null;
}
function handle(act, el) {
  const v = el.dataset.v;
  switch (act) {
    case 'sport': S.sport = v; S.game = ''; if (location.hash.includes('g=')) location.hash = '#/giocatori'; break;
    case 'market': S.market[S.sport] = v; break;
    case 'slipMode': S.slipMode = v; break;
    case 'multiStake': { const x = num(el.value); S.multiStake = x !== null && x >= 0 ? x : null; break; }
    case 'chTab': S.chTab = v; break;
    case 'onlyValue': S.onlyValue = v === '1'; break;
    case 'sort': S.sort = S.sort === 'valore' ? 'proiezione' : 'valore'; break;
    case 'game': S.game = el.value; if (location.hash.includes('g=')) { history.replaceState(null, '', '#/giocatori'); } break;
    case 'search': S.search = el.value; break;
    case 'gsearch': S.gsearch = el.value; break;
    case 'paste': S.pasteText = el.value; return;
    case 'parse': { const t = document.querySelector('[data-act=paste]'); S.pasteText = t ? t.value : S.pasteText; S.pasteRows = parsePaste(S.pasteText); break; }
    case 'pasteSave': {
      let n = 0;
      for (const r of S.pasteRows || []) { if (r.p && r.odds) { savePasteOdds(r); n++; } }
      save(); toast(n + ' quote salvate nelle schede'); break;
    }
    case 'pasteAdd': {
      const r = (S.pasteRows || [])[+el.dataset.i]; if (!r || !r.p) return;
      savePasteOdds(r);
      const e = evaluate(r.sport, r.p, r.m);
      const odds = r.side === 'over' ? e.over : e.under;
      const pp = r.side === 'over' ? e.pOver : e.pUnder;
      const bern = BERNOULLI.has(r.m);
      addToSlip({ sport: r.sport, g: r.p.g, pid: r.p.id, m: r.m, side: r.side, line: e.line, odds, p: pp, push: e.push,
        label: `${r.p.n} ${bern ? (r.side === 'over' ? 'Sì' : 'No') : (r.side === 'over' ? 'Over' : 'Under') + ' ' + e.line} ${mkLabel(r.sport, r.m).toLowerCase()}`,
        ctx: `${SPORT_LABEL[r.sport]} · ${r.p.t} vs ${r.p.o}` });
      break;
    }
    case 'odds': {
      const c = currentPlayer(); if (!c) return;
      const k = oddsKey(c.sport, c.p, c.m);
      const cur = lineFor(c.sport, c.p, c.m);
      const man = { line: cur.line, over: cur.over, under: cur.under };
      const x = num(el.value);
      if (el.dataset.k === 'line') { if (x === null || x < 0) return render(); man.line = x; }
      else man[el.dataset.k] = x && x > 1 ? x : null;
      S.manual[k] = man; break;
    }
    case 'clearOdds': { const c = currentPlayer(); if (c) delete S.manual[oddsKey(c.sport, c.p, c.m)]; break; }
    case 'addProp': {
      const c = currentPlayer(); if (!c) return;
      const e = evaluate(c.sport, c.p, c.m);
      const side = el.dataset.side;
      const odds = side === 'over' ? e.over : e.under;
      const p = side === 'over' ? e.pOver : e.pUnder;
      const bern = BERNOULLI.has(c.m);
      const lbl = `${c.p.n} ${bern ? (side === 'over' ? 'Sì' : 'No') : (side === 'over' ? 'Over' : 'Under') + ' ' + e.line} ${mkLabel(c.sport, c.m).toLowerCase()}`;
      addToSlip({ sport: c.sport, g: c.p.g, pid: c.p.id, m: c.m, side, line: e.line, odds, p, push: e.push, label: lbl,
        ctx: `${SPORT_LABEL[c.sport]} · ${c.p.t} vs ${c.p.o}` });
      break;
    }
    case 'mGroup': S.mGroup = v; break;
    case 'codeIn': return;
    case 'unlock': {
      const c = (document.getElementById('codeIn') || {}).value || '';
      if (!c) return;
      S.code = c;
      if ((document.getElementById('codeRem') || {}).checked) LS.set('code', c);
      S.needCode = false; S.codeErr = ''; S.keys = {};
      load(); return;
    }
    case 'logout': S.code = null; LS.set('code', null); S.data = null; load(); return;
    case 'tmOdds': {
      const k = 'soccer|mk|' + el.dataset.id;
      const cur = S.manual[k] || {};
      const x = num(el.value);
      cur[el.dataset.k] = x && x > 1 ? x : 0;
      S.manual[k] = cur; break;
    }
    case 'addTm': {
      const m = S.data.soccer.matches.find(x => x.id === el.dataset.id);
      const row = (m.mk || []).find(x => x[0] === el.dataset.k);
      const q = tmOdds(m)[el.dataset.k];
      if (!row || !q) return;
      addToSlip({ sport: 'soccer', g: m.id, pid: null, m: 'tm', side: row[0], line: null, odds: q, p: row[3], push: 0,
        label: row[2], ctx: `${m.h} – ${m.a}` });
      break;
    }
    case 'matchOdds': {
      const m = S.data.soccer.matches.find(x => x.id === el.dataset.id);
      const k = 'soccer|match|' + m.id;
      const cur = matchOdds(m) || {};
      const man = { o1: cur.o1 || null, ox: cur.ox || null, o2: cur.o2 || null, book: 'manuale' };
      const x = num(el.value); man[el.dataset.k] = x && x > 1 ? x : null;
      S.manual[k] = man; break;
    }
    case 'addMatch': {
      const m = S.data.soccer.matches.find(x => x.id === el.dataset.id);
      const o = matchOdds(m); const side = el.dataset.side;
      const odds = side === '1' ? o.o1 : side === 'X' ? o.ox : o.o2;
      const p = side === '1' ? m.p1 : side === 'X' ? m.px : m.p2;
      addToSlip({ sport: 'soccer', g: m.id, pid: null, m: '1x2', side, line: null, odds, p, push: 0,
        label: `${side === '1' ? m.h : side === '2' ? m.a : 'Pareggio'} (${side})`, ctx: `${m.h} – ${m.a}` });
      break;
    }
    case 'rmSlip': S.slip.splice(+el.dataset.i, 1); break;
    case 'clearSlip': S.slip = []; break;
    case 'stake': { const x = num(el.value); S.slip[+el.dataset.i].stake = x !== null && x >= 0 ? x : null; break; }
    case 'bankroll': { const x = num(el.value); if (x !== null && x > 0) S.bankroll = x; break; }
    case 'kelly': S.kellyFrac = +v; S.slip.forEach(s => { s.stake = null; }); break;
    case 'register': {
      const ts = new Date().toISOString();
      const keep = [];
      let n = 0;
      for (const s of S.slip) {
        const stake = s.stake != null ? s.stake : Math.round(suggestedStake(s) * 100) / 100;
        if (stake <= 0) { keep.push(s); continue; }
        S.bets.push({ ...s, stake, ts, status: 'pending' }); n++;
      }
      S.slip = keep; save(); settleBets();
      if (keep.length) { toast(n + ' registrate. ' + keep.length + ' con puntata 0: inserisci tu l\'importo.'); render(); return; }
      toast('Scommesse registrate'); location.hash = '#/roi'; return;
    }
    case 'registerMulti': {
      const mi = multiInfo(S.slip);
      const sug = suggestedStake({ p: mi.p, odds: mi.odds, push: 0 });
      const stake = S.multiStake != null ? S.multiStake : Math.round(sug * 100) / 100;
      if (!(stake > 0)) { toast('Inserisci la puntata della multipla'); return; }
      const ts = new Date().toISOString();
      S.bets.push({ type: 'multi', sport: 'multi', id: 'multi|' + ts, legs: S.slip.map(l => ({ ...l, status: 'pending' })),
        odds: mi.odds, p: mi.p, stake, ts, status: 'pending', label: `Multipla (${S.slip.length})`,
        ctx: S.slip.map(l => l.label).join(' + ') });
      S.slip = []; S.multiStake = null; save(); settleBets(); toast('Multipla registrata'); location.hash = '#/roi'; return;
    }
    case 'tennisOdds': {
      const m = S.data.tennis.matches.find(x => x.id === el.dataset.id);
      const k = 'tennis|match|' + m.id;
      const cur = S.manual[k] || {};
      const x = num(el.value);
      S.manual[k] = { o1: cur.o1 || null, o2: cur.o2 || null, [el.dataset.k]: x && x > 1 ? x : null };
      break;
    }
    case 'addTennis': {
      const m = S.data.tennis.matches.find(x => x.id === el.dataset.id);
      const o = tennisOdds(m) || {};
      const side = el.dataset.side;
      const odds = side === '1' ? o.o1 : o.o2;
      if (!odds) return;
      addToSlip({ sport: 'tennis', g: m.id, pid: null, m: 'win', side, win: side === '1' ? m.id1 : m.id2, line: null, odds,
        p: side === '1' ? m.pr1 : 1 - m.pr1, push: 0, label: `${side === '1' ? m.p1 : m.p2} vincente`, ctx: `${m.tour} · ${m.p1} – ${m.p2}` });
      break;
    }
    case 'addChicca': {
      const c = (S.chicche || [])[+el.dataset.i]; if (!c) return;
      addToSlip(c.sel); break;
    }
    case 'settle': setOutcome(S.bets[+el.dataset.i], v); break;
    case 'delBet': S.bets.splice(+el.dataset.i, 1); break;
    case 'period': S.roiPeriod = v; break;
    case 'export': {
      const blob = new Blob([JSON.stringify({ bets: S.bets, bankroll: S.bankroll, manual: S.manual }, null, 1)], { type: 'application/json' });
      const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'valore-backup.json'; a.click();
      return;
    }
    case 'import': {
      const f = el.files && el.files[0]; if (!f) return;
      f.text().then(t => {
        try {
          const d = JSON.parse(t);
          const ids = new Set(S.bets.map(b => b.id + b.ts));
          for (const b of d.bets || []) if (!ids.has(b.id + b.ts)) S.bets.push(b);
          if (d.bankroll) S.bankroll = d.bankroll;
          save(); toast('Backup importato'); render();
        } catch (e) { toast('File non valido'); }
      });
      return;
    }
    default: return;
  }
  save();
  // dopo una modifica in un campo il rendering e' ritardato: cosi' un tocco su un pulsante
  // (che fa perdere il fuoco al campo) arriva comunque al pulsante giusto
  if (['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName)) { clearTimeout(handle._r); handle._r = setTimeout(render, 180); }
  else { clearTimeout(handle._r); render(); }
}

load();
