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
    ['a', 'Assist', ['a']], ['ga', 'Gol+Assist', ['g', 'a']],
  ],
};
const BERNOULLI = new Set(['card']);
const mkInfo = (sport, m) => MARKETS[sport].find(x => x[0] === m) || MARKETS[sport][0];
const mkLabel = (sport, m) => mkInfo(sport, m)[1];
// posizione delle statistiche base negli array "l" (ultime partite) e nei risultati
const L_OFF = { nba: 3, soccer: 4 };
const BASE = { nba: NBA_BASE, soccer: SOC_BASE };

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
const defaultLine = (m, mu) => (BERNOULLI.has(m) || m === 'g' || m === 'a') ? 0.5 : Math.max(0.5, Math.floor(mu) + 0.5);

// ------------------------------------------------------------------ stato e archivio
const LS = {
  get(k, d) { try { const v = localStorage.getItem('valore.' + k); return v ? JSON.parse(v) : d; } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem('valore.' + k, JSON.stringify(v)); } catch (e) { /* archivio non disponibile */ } },
};
const S = {
  data: null, results: null, error: null,
  sport: LS.get('sport', 'nba'),
  market: LS.get('market', { nba: 'pts', soccer: 'sot' }),
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
  LS.set('kellyFrac', S.kellyFrac); LS.set('slip', S.slip); LS.set('bets', S.bets); LS.set('manual', S.manual);
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
async function load() {
  try {
    const bust = '?t=' + Math.floor(Date.now() / 300000);
    const [a, r] = await Promise.all([
      fetch('data/app.json' + bust).then(x => { if (!x.ok) throw new Error(x.status); return x.json(); }),
      fetch('data/results.json' + bust).then(x => x.ok ? x.json() : { nba: {}, soccer: {} }).catch(() => ({ nba: {}, soccer: {} })),
    ]);
    S.data = a; S.results = r;
    settleBets();
  } catch (e) {
    S.error = 'Dati non ancora disponibili. Il primo aggiornamento automatico crea il file data/app.json: controlla la scheda Actions su GitHub.';
  }
  render();
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
  S.slip.push({ ...sel, id, stake: null });
  save(); updateBadge(); toast('Aggiunta alla schedina');
}
function suggestedStake(sel) {
  const f = kelly(sel.p, sel.odds, sel.push || 0) * S.kellyFrac;
  return Math.min(S.bankroll * f, S.bankroll * 0.05);
}

function settleBets() {
  if (!S.results) return;
  let changed = false;
  for (const b of S.bets) {
    if (b.status !== 'pending') continue;
    const R = (S.results[b.sport] || {})[b.g];
    if (!R) continue;
    let outcome = null;
    if (!b.pid) {
      const [hs, as] = R.s;
      const res = hs > as ? '1' : hs < as ? '2' : 'X';
      outcome = res === b.side ? 'won' : 'lost';
    } else {
      if (!R.b) continue;
      const row = R.p[b.pid];
      if (!row) outcome = 'void';
      else {
        const v = marketValue(b.sport, b.m, row, 1);
        if (v === b.line) outcome = 'void';
        else outcome = ((v > b.line) === (b.side === 'over')) ? 'won' : 'lost';
        b.actual = v;
      }
    }
    if (outcome) { setOutcome(b, outcome); changed = true; }
  }
  if (changed) save();
}
function setOutcome(b, outcome) {
  b.status = outcome;
  b.profit = outcome === 'won' ? b.stake * (b.odds - 1) : outcome === 'lost' ? -b.stake : 0;
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
  const tab = parts[0] === 'giocatori' || parts[0] === 'g' ? 'giocatori' : parts[0] === 'schedina' ? 'schedina' : parts[0] === 'roi' ? 'roi' : 'partite';
  document.querySelectorAll('nav.tabs a').forEach(a => a.classList.toggle('on', a.dataset.tab === tab));
  updateBadge();
  const v = $('#view');
  let html;
  if (parts[0] === 'schedina') html = viewSlip();
  else if (parts[0] === 'roi') html = viewRoi();
  else if (S.error) html = header('Valore', 'Statistiche → probabilità') + `</header><main><div class="empty">${esc(S.error)}</div></main>`;
  else if (!S.data) html = `<main style="padding-top:40px"><div class="empty">Caricamento…</div></main>`;
  else if (parts[0] === 'giocatori') html = viewPlayers(q);
  else if (parts[0] === 'g') html = viewPlayer(parts[1], parts[2], parts[3], q.m);
  else if (parts[0] === 'partita') html = viewMatch(parts[1]);
  else html = viewGames();
  v.innerHTML = html;
  bind();
}
window.addEventListener('hashchange', () => { render(); window.scrollTo(0, 0); });

function header(title, kicker, back) {
  return `<header class="top"><div class="row">${back ? `<a class="iconbtn" href="${back}" aria-label="Indietro">${ICON_BACK}</a>` : ''}
    <div style="display:flex;flex-direction:column;gap:2px;min-width:0"><span class="kicker">${esc(kicker)}</span><h1>${esc(title)}</h1></div></div>`;
}
function sportSeg() {
  return `<div class="seg" role="tablist" aria-label="Sport">${[['nba', 'NBA'], ['soccer', 'Calcio']].map(([k, l]) =>
    `<button role="tab" aria-selected="${S.sport === k}" class="${S.sport === k ? 'on' : ''}" data-act="sport" data-v="${k}">${l}</button>`).join('')}</div>`;
}
function updatedLine() {
  if (!S.data) return '';
  return `<p class="note">Dati aggiornati: ${esc(new Date(S.data.generated).toLocaleString('it-IT', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }))}. Le probabilità sono stime, non certezze. Il gioco è vietato ai minori di 18 anni e può causare dipendenza.</p>`;
}

// ------------------------------------------------------------------ vista: partite
function viewGames() {
  let body = '';
  if (S.sport === 'nba') {
    const games = (S.data.nba.games || []).slice().sort((a, b) => a.t.localeCompare(b.t));
    if (!games.length) body = '<div class="empty">Nessuna partita NBA nei prossimi giorni.</div>';
    for (const g of games) {
      const ps = players('nba').filter(p => p.g === g.id);
      const vals = ps.flatMap(p => MARKETS.nba.map(m => evaluate('nba', p, m[0]))).filter(e => e.ev !== null && e.ev > 0);
      body += `<a class="card" href="#/giocatori?g=${esc(g.id)}">
        <div class="row between small muted"><span>NBA · ${esc(fmtTime(g.t))}</span>${vals.length ? `<span class="badge val">${vals.length} con valore</span>` : ''}</div>
        <div class="row between"><span style="font-size:16px;font-weight:600">${esc(g.an)} @ ${esc(g.hn)}</span></div>
        <div class="small muted">${ps.length} giocatori analizzati · tocca per le prop</div></a>`;
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
  return header('Partite', 'Prossimi giorni') + `<div style="padding:0 16px;display:flex;flex-direction:column;gap:10px">${sportSeg()}
    ${S.sport === 'soccer' ? `<div class="chips"><button class="chip ${!S.onlyValue ? 'on' : ''}" data-act="onlyValue" data-v="0">Tutte</button><button class="chip ${S.onlyValue ? 'on' : ''}" data-act="onlyValue" data-v="1">Solo valore</button></div>` : ''}</div></header>
    <main>${body}${updatedLine()}</main>`;
}
function matchOdds(m) {
  const man = S.manual['soccer|match|' + m.id];
  if (man) return man;
  if (m.odds) return { o1: m.odds[0], ox: m.odds[1], o2: m.odds[2], book: m.odds[3] };
  return null;
}
function matchValue(m) {
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
    ${cells}</a>`;
}

// ------------------------------------------------------------------ vista: partita (calcio)
function viewMatch(id) {
  const m = (S.data.soccer.matches || []).find(x => x.id === id);
  if (!m) return header('Partita', 'Calcio', '#/') + '<main><div class="empty">Partita non trovata.</div></main>';
  const o = matchOdds(m) || {};
  const lg = (S.data.leagues || {})[m.lg] || m.lg;
  let body = '';
  if (m.p1 != null) {
    body += `<div class="card"><h2>Quote del tuo bookmaker</h2>
      <div class="grid3">${[['1', 'o1'], ['X', 'ox'], ['2', 'o2']].map(([s, k]) =>
        `<div class="field"><label for="mo-${k}">Quota ${s}</label><input id="mo-${k}" inputmode="decimal" data-act="matchOdds" data-k="${k}" data-id="${esc(m.id)}" value="${o[k] ? o[k] : ''}" placeholder="—"></div>`).join('')}</div>
      ${o.book && o.book !== 'manuale' ? `<p class="note">Quote automatiche: migliore tra i bookmaker (${esc(o.book)}). Puoi sovrascriverle.</p>` : ''}
      ${[['1', m.p1, o.o1, m.h], ['X', m.px, o.ox, 'Pareggio'], ['2', m.p2, o.o2, m.a]].map(([s, p, q, name]) => {
        const e = q ? ev(p, q) : null;
        return `<div class="list-row"><div style="display:flex;flex-direction:column;gap:2px"><span class="b">${s} · ${esc(name)}</span>
          <span class="tiny muted">Modello ${pct(p, 1)} · quota giusta ${(1 / p).toFixed(2)}${q ? ' · implicita ' + pct(1 / q, 1) : ''}</span></div>
          <div class="row">${e !== null ? `<span class="mono b ${e > 0 ? 'acc' : 'muted'}">${sgn(e)}</span>` : ''}
          ${q ? `<button class="btn small ${e > 0 ? '' : 'ghost'}" data-act="addMatch" data-id="${esc(m.id)}" data-side="${s}">+</button>` : ''}</div></div>`;
      }).join('')}</div>
      <div class="card"><h2>Gol attesi e mercati</h2>
        <div class="grid3"><div class="kv"><span>Gol attesi</span><span class="model">${m.lh.toFixed(2)} – ${m.la.toFixed(2)}</span></div>
        <div class="kv"><span>Over 2.5</span><span class="model">${pct(m.o25, 1)}</span></div><div class="kv"><span>Goal (entrambe)</span><span class="model">${pct(m.btts, 1)}</span></div></div>
        <div style="display:flex;flex-direction:column;gap:8px">${m.top.map(([s, p]) => `<div style="display:grid;grid-template-columns:44px 1fr 52px;align-items:center;gap:10px">
          <span class="mono b">${s}</span><div class="bar" style="height:10px"><div style="width:${Math.min(100, p / m.top[0][1] * 100).toFixed(0)}%;background:var(--model)"></div></div>
          <span class="mono small" style="text-align:right">${pct(p, 1)}</span></div>`).join('')}</div>
        <p class="note">Modello di Poisson su attacco e difesa delle squadre, con più peso alle partite recenti.${m.ref ? ' Arbitro: ' + esc(m.ref) + '.' : ''}</p></div>`;
  } else body += '<div class="card"><p class="note">Storico insufficiente per stimare il risultato: restano disponibili le statistiche dei giocatori.</p></div>';
  const ps = players('soccer').filter(p => p.g === m.id);
  body += `<a class="btn ghost" href="#/giocatori?g=${esc(m.id)}">Statistiche giocatori (${ps.length})</a>`;
  return header(`${m.h} – ${m.a}`, `${lg} · ${fmtTime(m.t)}`, '#/') + '</header><main>' + body + '</main>';
}

// ------------------------------------------------------------------ vista: giocatori
function viewPlayers(q) {
  const sport = S.sport;
  if (q.g !== undefined) S.game = q.g;
  const m = S.market[sport];
  const all = players(sport);
  const games = sport === 'nba' ? (S.data.nba.games || []).map(g => [g.id, `${g.a} @ ${g.h}`, g.t])
    : (S.data.soccer.matches || []).map(g => [g.id, `${g.h} – ${g.a}`, g.t]);
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
  return header('Prop giocatori', 'Statistiche giocatori') + `<div style="padding:0 16px;display:flex;flex-direction:column;gap:10px">
    ${sportSeg()}
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
  const badge = e.ev === null ? status : val ? `<span class="badge val">EV ${sgn(e.ev)}</span>` : '<span class="badge no">Nessun valore</span>';
  const sideLbl = BERNOULLI.has(m) ? (e.side === 'over' ? 'Sì' : 'No') : (e.side === 'over' ? 'O' : 'U');
  const sub = sport === 'soccer' ? ` · titolare ${pct(p.ps)}${p.lu ? ' (formazione ufficiale)' : ''}` : ` · ${p.m.toFixed(0)} min`;
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
  const m = MARKETS[sport].some(x => x[0] === mq) ? mq : S.market[sport];
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
  const sideBox = (side, label, pp, q, e2, k) => {
    const good = e2 !== null && e2 > 0;
    return `<div class="cell ${good ? 'value' : ''}"><div class="row between"><span class="b">${label}</span><span class="mono model b">${pct(pp, 1)}</span></div>
      <span class="tiny muted">Quota giusta ${pp > 0 ? (1 / pp).toFixed(2) : '—'}</span>
      ${q ? `<span class="mono b ${good ? 'acc' : 'muted'}">EV ${sgn(e2)}${good ? ' · Kelly ' + pct(k, 1) : ''}</span>
        <button class="btn small ${good ? '' : 'ghost'}" data-act="addProp" data-side="${side}">Aggiungi</button>` : '<span class="tiny muted">Inserisci la quota</span>'}</div>`;
  };
  const factors = [];
  factors.push(['Minuti attesi', sport === 'nba' ? p.m.toFixed(1) : p.m + "'"]);
  if (sport === 'soccer') factors.push(['Probabilità da titolare', pct(p.ps) + (p.lu ? ' (formazione ufficiale)' : '')]);
  factors.push(['Media ultime ' + vals.length, bern ? pct(avg10) : avg10.toFixed(1)]);
  factors.push(['Media ultime 30', bern ? pct(p.a30[m]) : Number(p.a30[m]).toFixed(1)]);
  const of = p.of[m] || 1;
  factors.push([`Avversario (${p.o}) concede`, (of >= 1 ? '+' : '−') + Math.abs((of - 1) * 100).toFixed(0) + '% vs media']);
  if (sport === 'soccer' && p.rf && (m === 'card' || m === 'fc')) factors.push(['Arbitro', (p.rf >= 1 ? '+' : '−') + Math.abs((p.rf - 1) * 100).toFixed(0) + '% cartellini']);
  factors.push([p.h ? 'In casa' : 'In trasferta', '']);
  if (p.st) factors.push(['Stato', p.st]);
  return header(p.n + ' · ' + mkLabel(sport, m), `${sport === 'nba' ? 'NBA' : ((S.data.leagues || {})[p.lg] || 'Calcio')} · ${p.t} vs ${p.o}`, '#/giocatori') + `
    <div style="padding:0 16px"><div class="chips">${MARKETS[sport].map(([k, l]) => `<a class="chip ${k === m ? 'on' : ''}" style="display:flex;align-items:center" href="#/g/${sport}/${esc(p.id)}/${esc(p.g)}?m=${k}">${l}</a>`).join('')}</div></div></header>
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
      <div class="card"><div class="row between"><h2>Ultime ${vals.length} partite</h2><span class="mono small">linea ${e.line}</span></div>
        <div class="chart"><div class="line" style="bottom:${(e.line / max * H).toFixed(0)}px"></div>
          ${vals.slice().reverse().map(v => `<div class="col"><b>${v}</b><div class="${v > e.line ? 'y' : ''}" style="height:${Math.max(2, v / max * H).toFixed(0)}px"></div></div>`).join('')}</div>
        <div class="xlabels">${p.l.slice().reverse().map(x => `<span title="${esc(x[0])}">${esc(x[1])}</span>`).join('')}</div></div>
      <div class="card"><h2>Da dove arriva la proiezione</h2>
        <div>${factors.map(([k, v]) => `<div class="list-row"><span style="color:var(--text2)">${esc(k)}</span><span class="mono b">${esc(v)}</span></div>`).join('')}</div>
        <p class="note">Tasso per minuto pesato sulle partite recenti (con correzione verso la media del ruolo), moltiplicato per i minuti attesi e per i fattori avversario${sport === 'soccer' ? ', casa/trasferta e arbitro' : ' e casa/trasferta'}. La distribuzione tiene conto della variabilità del giocatore.</p></div>
      ${updatedLine()}
    </main>`;
}

// ------------------------------------------------------------------ vista: schedina
function viewSlip() {
  const items = S.slip;
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
  return header('Schedina', items.length + (items.length === 1 ? ' selezione' : ' selezioni')) + `</header><main>
    <div class="card"><div class="row between"><label class="muted small" for="bankroll">Bankroll €</label>
      <input id="bankroll" class="search mono" style="max-width:150px;text-align:right;font-weight:700" inputmode="decimal" data-act="bankroll" value="${S.bankroll}"></div>
      <div style="display:flex;flex-direction:column;gap:8px"><span class="small muted">Frazione di Kelly</span>
      <div class="seg">${[[0.25, 'Kelly ¼'], [0.5, 'Kelly ½'], [1, 'Kelly pieno']].map(([v, l]) => `<button class="${S.kellyFrac === v ? 'on' : ''}" data-act="kelly" data-v="${v}">${l}</button>`).join('')}</div></div></div>
    ${rows || '<div class="empty">Nessuna selezione. Aggiungile dalla scheda di un giocatore o di una partita.</div>'}
    ${items.length ? `<div class="card">
      <div class="row between"><span class="muted">Puntata totale</span><span class="mono b">${eur(total)}</span></div>
      <div class="row between"><span class="muted">Esposizione sul bankroll</span><span class="mono b">${S.bankroll ? pct(total / S.bankroll, 1) : '—'}</span></div>
      <div class="row between"><span class="muted">Guadagno atteso (EV)</span><span class="mono b ${evTot >= 0 ? 'acc' : 'book'}">${evTot >= 0 ? '+' : '−'}${eur(Math.abs(evTot))}</span></div>
      <p class="note">Puntate singole: in una multipla il margine del bookmaker si moltiplica.</p></div>
      <button class="btn" data-act="register">Registra le scommesse</button>
      <button class="btn ghost" data-act="clearSlip">Svuota schedina</button>` : ''}
    <div class="warnbox"><span>Le probabilità sono stime, non certezze. Imposta un limite di spesa e rispettalo. Il gioco è vietato ai minori di 18 anni e può causare dipendenza.</span></div>
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
    const k = (b.sport === 'nba' ? 'NBA · ' : 'Calcio · ') + (b.pid ? mkLabel(b.sport, b.m) : '1X2');
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
      <div class="row between"><span class="tiny muted">${esc(b.ctx)} · @${b.odds.toFixed(2)} · ${eur(b.stake)}${b.actual != null ? ' · risultato ' + b.actual : ''}</span></div>
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
    <div class="card"><h2>Backup</h2><p class="note">Il registro è salvato su questo dispositivo. Esporta un file di backup per spostarlo su un altro telefono o PC.</p>
      <div class="row"><button class="btn ghost small" data-act="export">Esporta</button><label class="btn ghost small" style="cursor:pointer">Importa<input type="file" accept="application/json" data-act="import" hidden></label></div></div>
  </main>`;
}

// ------------------------------------------------------------------ eventi
function bind() {
  document.querySelectorAll('[data-act]').forEach(el => {
    const act = el.dataset.act;
    const evName = el.tagName === 'INPUT' ? (el.type === 'file' ? 'change' : 'change') : el.tagName === 'SELECT' ? 'change' : 'click';
    el.addEventListener(evName, ev => handle(act, el, ev));
    if (act === 'search') el.addEventListener('input', () => { S.search = el.value; clearTimeout(bind._t); bind._t = setTimeout(() => { render(); const s = document.querySelector('[data-act=search]'); if (s) { s.focus(); s.setSelectionRange(s.value.length, s.value.length); } }, 250); });
  });
}
function currentPlayer() {
  const { parts, q } = route();
  if (parts[0] !== 'g') return null;
  const p = findPlayer(parts[1], parts[2], parts[3]);
  const m = MARKETS[parts[1]].some(x => x[0] === q.m) ? q.m : S.market[parts[1]];
  return p ? { sport: parts[1], p, m } : null;
}
function handle(act, el) {
  const v = el.dataset.v;
  switch (act) {
    case 'sport': S.sport = v; S.game = ''; if (location.hash.includes('g=')) location.hash = '#/giocatori'; break;
    case 'market': S.market[S.sport] = v; break;
    case 'onlyValue': S.onlyValue = v === '1'; break;
    case 'sort': S.sort = S.sort === 'valore' ? 'proiezione' : 'valore'; break;
    case 'game': S.game = el.value; if (location.hash.includes('g=')) { history.replaceState(null, '', '#/giocatori'); } break;
    case 'search': S.search = el.value; break;
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
        ctx: `${c.sport === 'nba' ? 'NBA' : 'Calcio'} · ${c.p.t} vs ${c.p.o}` });
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
  save(); render();
}

load();
