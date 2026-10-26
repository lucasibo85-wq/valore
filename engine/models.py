"""Modelli statistici: proiezioni giocatori (NBA e calcio) e Poisson squadre."""
import math
from collections import defaultdict

NBA_BASE = ["pts", "reb", "ast", "stl", "blk", "fg3m", "tov"]
NBA_MARKETS = {
    "pts": ["pts"], "reb": ["reb"], "ast": ["ast"], "stl": ["stl"], "blk": ["blk"],
    "fg3m": ["fg3m"], "tov": ["tov"], "pra": ["pts", "reb", "ast"], "pr": ["pts", "reb"],
    "pa": ["pts", "ast"], "ra": ["reb", "ast"], "sb": ["stl", "blk"],
}
SOC_BASE = ["shots", "sot", "fc", "fs", "yc", "rc", "g", "a"]
SOC_MARKETS = {
    "shots": ["shots"], "sot": ["sot"], "fc": ["fc"], "fs": ["fs"], "card": ["yc", "rc"],
    "g": ["g"], "a": ["a"], "ga": ["g", "a"], "goa": ["g", "a"],
}
BERNOULLI = {"card", "goa", "td", "hr"}  # conta solo "almeno uno"


def market_value(row, comps, market):
    v = sum(float(row.get(c, 0) or 0) for c in comps)
    return min(v, 1.0) if market in BERNOULLI else v


def pos_group(sport, pos):
    p = (pos or "").upper()
    if sport == "nfl":
        return p if p in ("QB", "RB", "WR", "TE") else "X"
    if sport == "mlb":
        return "P" if p == "P" else "B"
    if sport == "nba":
        if "C" in p:
            return "C"
        if "G" in p:
            return "G"
        return "F"
    if p.startswith("G"):
        return "G"
    if p.startswith("D") or p in ("CB", "LB", "RB"):
        return "D"
    if p.startswith("F") or p in ("ST", "CF", "LW", "RW"):
        return "F"
    return "M"


# ------------------------------------------------------------ distribuzioni
def poisson_cdf(k, mu):
    if k < 0:
        return 0.0
    if mu <= 0:
        return 1.0
    term = math.exp(-mu)
    s = term
    for i in range(1, int(k) + 1):
        term *= mu / i
        s += term
    return min(1.0, s)


def nb_cdf(k, mu, r):
    """Binomiale negativa con media mu e parametro di dimensione r."""
    if r is None or r <= 0 or r > 1e6:
        return poisson_cdf(k, mu)
    if k < 0:
        return 0.0
    p = r / (r + mu)
    term = math.exp(r * math.log(p))
    s = term
    for i in range(1, int(k) + 1):
        term *= (i - 1 + r) / i * (1 - p)
        s += term
    return min(1.0, s)


def prob_over(line, mu, r):
    """P(X > line). Con linee .5 non ci sono rimborsi."""
    return max(0.0, 1.0 - nb_cdf(math.floor(line), mu, r))


# ------------------------------------------------------------ utilita'
def wmean(vals, ws):
    sw = sum(ws)
    return sum(v * w for v, w in zip(vals, ws)) / sw if sw > 0 else 0.0


def decay_weights(n, half_life):
    return [0.5 ** (i / half_life) for i in range(n)]


def shrink(value, n, k, prior=1.0):
    return prior + (value - prior) * (n / (n + k))


# ------------------------------------------------------------ fattori contesto
def team_game_totals(logs, markets):
    """Somma per (partita, squadra) di ogni mercato."""
    tot = defaultdict(lambda: defaultdict(float))
    meta = {}
    for r in logs:
        key = (r["gid"], r["team"])
        meta[key] = (r["opp"], r["date"], int(r.get("home") or 0))
        for m, comps in markets.items():
            tot[key][m] += sum(float(r.get(c, 0) or 0) for c in comps)
    return tot, meta


def opponent_factors(logs, markets, since_date, k):
    """Quanto concede ogni squadra rispetto alla media, per mercato."""
    tot, meta = team_game_totals([r for r in logs if r["date"] >= since_date], markets)
    allowed = defaultdict(lambda: defaultdict(list))
    league = defaultdict(list)
    home_vals = defaultdict(list)
    for key, vals in tot.items():
        opp, _, home = meta[key]
        for m, v in vals.items():
            allowed[opp][m].append(v)
            league[m].append(v)
            if home:
                home_vals[m].append(v)
    avg = {m: (sum(v) / len(v) if v else 0.0) for m, v in league.items()}
    fac = {}
    for team, d in allowed.items():
        fac[team] = {}
        for m, v in d.items():
            if avg.get(m, 0) > 0 and v:
                fac[team][m] = shrink((sum(v) / len(v)) / avg[m], len(v), k)
    home = {}
    for m, v in home_vals.items():
        if avg.get(m, 0) > 0 and v:
            home[m] = (sum(v) / len(v)) / avg[m]
    return fac, home


def referee_factors(matches, soc_logs, k=10):
    """Cartellini e falli per partita diretta da ogni arbitro, rispetto alla media."""
    per_game = defaultdict(lambda: [0.0, 0.0])
    for r in soc_logs:
        g = per_game[r["gid"]]
        g[0] += float(r.get("yc", 0) or 0) + float(r.get("rc", 0) or 0)
        g[1] += float(r.get("fc", 0) or 0)
    by_ref = defaultdict(list)
    for m in matches:
        if m.get("sport") == "soccer" and m.get("referee") and m["gid"] in per_game:
            by_ref[m["referee"]].append(per_game[m["gid"]])
    allg = [v for v in per_game.values()]
    if not allg:
        return {}
    avg_c = sum(v[0] for v in allg) / len(allg)
    avg_f = sum(v[1] for v in allg) / len(allg)
    out = {}
    for ref, games in by_ref.items():
        n = len(games)
        c = sum(g[0] for g in games) / n
        f = sum(g[1] for g in games) / n
        out[ref] = {
            "card": shrink(c / avg_c, n, k) if avg_c else 1.0,
            "fc": shrink(f / avg_f, n, k) if avg_f else 1.0,
            "n": n,
        }
    return out


# ------------------------------------------------------------ priori di lega
def league_priors(sport, logs, markets, since_date):
    """Tasso per minuto per gruppo di ruolo e sovradispersione media per mercato."""
    by_player = defaultdict(list)
    for r in logs:
        if r["date"] >= since_date:
            by_player[r["pid"]].append(r)
    num = defaultdict(float)
    den = defaultdict(float)
    for pid, games in by_player.items():
        g = pos_group(sport, games[-1].get("pos"))
        for r in games:
            for m, comps in markets.items():
                num[(g, m)] += market_value(r, comps, m)
                den[(g, m)] += float(r["min"])
    rate = {key: (num[key] / den[key] if den[key] else 0.0) for key in num}
    # sovradispersione: varianza/media dei residui, con il tasso del giocatore
    phi_num = defaultdict(float)
    phi_den = defaultdict(float)
    for pid, games in by_player.items():
        if len(games) < 8:
            continue
        mins = sum(float(r["min"]) for r in games)
        if mins <= 0:
            continue
        for m, comps in markets.items():
            if m in BERNOULLI:
                continue
            pm = sum(market_value(r, comps, m) for r in games) / mins
            for r in games:
                e = pm * float(r["min"])
                x = market_value(r, comps, m)
                phi_num[m] += (x - e) ** 2
                phi_den[m] += e
    phi = {m: max(1.0, phi_num[m] / phi_den[m]) if phi_den[m] else 1.2 for m in markets}
    return rate, phi


# ------------------------------------------------------------ proiezione giocatore
def project(games, sport, markets, priors, exp_min, min_var, factors, half_life, prior_minutes):
    """games: partite del giocatore, dalla piu' recente. Ritorna {mercato: (mu, r)}."""
    rate_prior, phi_prior = priors
    g = pos_group(sport, games[0].get("pos") if games else "")
    games = games[:40]
    ws = decay_weights(len(games), half_life)
    sw = sum(ws)
    mins = [float(r["min"]) for r in games]
    out = {}
    for m, comps in markets.items():
        xs = [market_value(r, comps, m) for r in games]
        pr = rate_prior.get((g, m), 0.0)
        num = sum(w * x for w, x in zip(ws, xs)) + pr * prior_minutes
        den = sum(w * mn for w, mn in zip(ws, mins)) + prior_minutes
        pm = num / den if den > 0 else pr
        mu = pm * exp_min * factors.get(m, 1.0)
        if m in BERNOULLI:
            # mu qui e' la probabilita' di "almeno uno": la converto nel parametro di Poisson equivalente
            p_ = min(max(mu, 0.0), 0.95)
            out[m] = (round(-math.log(1 - p_), 4), None)
            continue
        e_num = sum(w * (x - pm * mn) ** 2 for w, x, mn in zip(ws, xs, mins))
        e_den = sum(w * pm * mn for w, mn in zip(ws, mins))
        phi_emp = e_num / e_den if e_den > 0 else phi_prior.get(m, 1.2)
        phi = (phi_emp * sw + phi_prior.get(m, 1.2) * 8) / (sw + 8)
        var = max(phi, 1.0) * mu + (pm ** 2) * min_var
        r = (mu * mu / (var - mu)) if var > mu * 1.02 and mu > 0 else None
        out[m] = (round(mu, 3), round(r, 3) if r else None)
    return out


# ------------------------------------------------------------ squadre calcio
def team_strengths(matches, today, half_life_days=150, prior_games=4, hf="hs", af="as", min_rows=10):
    """Forza "d'attacco" e "di difesa" per squadra (rapporti con la media) per una statistica
    di squadra: gol (hs/as), angoli (hc/ac), cartellini (hk/ak)..."""
    import datetime as dt
    t0 = dt.date.fromisoformat(today)
    rows = []
    for m in matches:
        if m.get(hf) in (None, "") or m.get(af) in (None, ""):
            continue
        d = dt.date.fromisoformat(m["date"][:10])
        w = 0.5 ** ((t0 - d).days / half_life_days)
        rows.append((m["hid"], m["aid"], float(m[hf]), float(m[af]), w))
    if len(rows) < min_rows:
        return None
    sw = sum(r[4] for r in rows)
    avg_h = sum(r[2] * r[4] for r in rows) / sw
    avg_a = sum(r[3] * r[4] for r in rows) / sw
    avg_h, avg_a = max(avg_h, 0.3), max(avg_a, 0.3)
    att = defaultdict(lambda: 1.0)
    dfn = defaultdict(lambda: 1.0)
    for _ in range(12):
        an = defaultdict(float)
        ad = defaultdict(float)
        dn = defaultdict(float)
        dd = defaultdict(float)
        for h, a, hs, as_, w in rows:
            an[h] += w * hs
            ad[h] += w * avg_h * dfn[a]
            an[a] += w * as_
            ad[a] += w * avg_a * dfn[h]
            dn[h] += w * as_
            dd[h] += w * avg_a * att[a]
            dn[a] += w * hs
            dd[a] += w * avg_h * att[h]
        for t in set(list(an.keys()) + list(dn.keys())):
            att[t] = (an[t] + prior_games) / (ad[t] + prior_games)
            dfn[t] = (dn[t] + prior_games) / (dd[t] + prior_games)
    return {"avg_h": avg_h, "avg_a": avg_a, "att": dict(att), "def": dict(dfn)}


def match_probs(lh, la, max_goals=10):
    M = dc_matrix(lh, la, -0.05, max_goals)
    p1 = px = p2 = o25 = btts = 0.0
    scores = []
    for i in range(max_goals + 1):
        for j in range(max_goals + 1):
            p = M[i][j]
            if i > j:
                p1 += p
            elif i == j:
                px += p
            else:
                p2 += p
            if i + j >= 3:
                o25 += p
            if i > 0 and j > 0:
                btts += p
            scores.append((p, "%d-%d" % (i, j)))
    scores.sort(reverse=True)
    return {
        "p1": round(p1, 4), "px": round(px, 4), "p2": round(p2, 4),
        "o25": round(o25, 4), "btts": round(btts, 4),
        "top": [[s, round(p, 4)] for p, s in scores[:6]],
    }


# ------------------------------------------------------------ mercati di squadra (calcio)
def _pois(k, mu):
    return math.exp(-mu) * mu ** k / math.factorial(k)


def dc_matrix(lh, la, rho=-0.05, max_goals=10):
    """Matrice dei risultati con la correzione Dixon-Coles sui punteggi bassi
    (rende piu' realistici 0-0, 1-0, 0-1 e 1-1)."""
    M = [[_pois(i, lh) * _pois(j, la) for j in range(max_goals + 1)] for i in range(max_goals + 1)]
    if rho:
        M[0][0] *= max(0.0, 1 - lh * la * rho)
        M[0][1] *= max(0.0, 1 + lh * rho)
        M[1][0] *= max(0.0, 1 + la * rho)
        M[1][1] *= max(0.0, 1 - rho)
    tot = sum(sum(r) for r in M)
    return [[v / tot for v in r] for r in M]


def _sum(M, cond):
    return sum(M[i][j] for i in range(len(M)) for j in range(len(M)) if cond(i, j))


def nb_over(line, mu, r):
    return prob_over(line, mu, r)


def soccer_markets(lh, la, f1=0.445, corners=None, cards=None, rho=-0.05):
    """Tutti i mercati di squadra: lista di [chiave, gruppo, etichetta, probabilita']."""
    M = dc_matrix(lh, la, rho)
    M1 = dc_matrix(lh * f1, la * f1, rho * 0.5)
    M2 = dc_matrix(lh * (1 - f1), la * (1 - f1), rho * 0.5)
    out = []

    def add(k, g, label, p):
        out.append([k, g, label, round(max(0.0, min(1.0, p)), 4)])

    p1, px, p2 = _sum(M, lambda i, j: i > j), _sum(M, lambda i, j: i == j), _sum(M, lambda i, j: i < j)
    g = "Esito finale"
    add("1", g, "1 (casa)", p1); add("X", g, "X (pareggio)", px); add("2", g, "2 (ospite)", p2)
    add("1X", g, "1X", p1 + px); add("X2", g, "X2", px + p2); add("12", g, "12", p1 + p2)
    add("dnb1", g, "Draw no bet 1", p1 / (p1 + p2)); add("dnb2", g, "Draw no bet 2", p2 / (p1 + p2))
    g = "Gol / No gol"
    gg = _sum(M, lambda i, j: i > 0 and j > 0)
    add("gg", g, "Goal (segnano entrambe)", gg); add("ng", g, "No goal", 1 - gg)
    g = "Under / Over"
    for n in (0.5, 1.5, 2.5, 3.5, 4.5, 5.5):
        k = "%02d" % int(n * 10)
        po = _sum(M, lambda i, j: i + j > n)
        add("o" + k, g, "Over %.1f" % n, po); add("u" + k, g, "Under %.1f" % n, 1 - po)
    g = "Multigol"
    for a, b in ((1, 2), (1, 3), (2, 3), (2, 4), (3, 5), (4, 6), (0, 2)):
        add("mg%d-%d" % (a, b), g, "Multigol %d-%d" % (a, b), _sum(M, lambda i, j: a <= i + j <= b))
    for side, lab in (("h", "Casa"), ("a", "Ospite")):
        g = "Gol " + lab.lower()
        for n in (0.5, 1.5, 2.5):
            k = "%02d" % int(n * 10)
            po = _sum(M, (lambda i, j: i > n) if side == "h" else (lambda i, j: j > n))
            add(side + "o" + k, g, "%s over %.1f" % (lab, n), po); add(side + "u" + k, g, "%s under %.1f" % (lab, n), 1 - po)
    g = "Combo"
    combos = [("1+o15", lambda i, j: i > j and i + j > 1.5), ("1+o25", lambda i, j: i > j and i + j > 2.5),
              ("2+o15", lambda i, j: i < j and i + j > 1.5), ("2+o25", lambda i, j: i < j and i + j > 2.5),
              ("1+gg", lambda i, j: i > j and j > 0), ("2+gg", lambda i, j: i < j and i > 0),
              ("x+u25", lambda i, j: i == j and i + j < 2.5), ("1x+o15", lambda i, j: i >= j and i + j > 1.5),
              ("x2+o15", lambda i, j: i <= j and i + j > 1.5), ("1x+u35", lambda i, j: i >= j and i + j < 3.5),
              ("x2+u35", lambda i, j: i <= j and i + j < 3.5), ("gg+o25", lambda i, j: i > 0 and j > 0 and i + j > 2.5),
              ("ng+u25", lambda i, j: (i == 0 or j == 0) and i + j < 2.5)]
    names = {"1+o15": "1 + Over 1.5", "1+o25": "1 + Over 2.5", "2+o15": "2 + Over 1.5", "2+o25": "2 + Over 2.5",
             "1+gg": "1 + Goal", "2+gg": "2 + Goal", "x+u25": "X + Under 2.5", "1x+o15": "1X + Over 1.5",
             "x2+o15": "X2 + Over 1.5", "1x+u35": "1X + Under 3.5", "x2+u35": "X2 + Under 3.5",
             "gg+o25": "Goal + Over 2.5", "ng+u25": "No goal + Under 2.5"}
    for k, f in combos:
        add(k, g, names[k], _sum(M, f))
    g = "1° tempo"
    a1, ax, a2 = _sum(M1, lambda i, j: i > j), _sum(M1, lambda i, j: i == j), _sum(M1, lambda i, j: i < j)
    add("1t1", g, "1° tempo: 1", a1); add("1tx", g, "1° tempo: X", ax); add("1t2", g, "1° tempo: 2", a2)
    for n in (0.5, 1.5, 2.5):
        k = "%02d" % int(n * 10)
        po = _sum(M1, lambda i, j: i + j > n)
        add("1to" + k, g, "1° tempo over %.1f" % n, po); add("1tu" + k, g, "1° tempo under %.1f" % n, 1 - po)
    add("1t1x", g, "1° tempo: 1X", a1 + ax); add("1tx2", g, "1° tempo: X2", ax + a2); add("1t12", g, "1° tempo: 12", a1 + a2)
    gg1 = _sum(M1, lambda i, j: i > 0 and j > 0)
    add("1tgg", g, "1° tempo: Goal", gg1); add("1tng", g, "1° tempo: No goal", 1 - gg1)
    h1 = _sum(M1, lambda i, j: i > 0)
    a1s = _sum(M1, lambda i, j: j > 0)
    add("1tho05", g, "1° tempo: segna la casa", h1); add("1thu05", g, "1° tempo: casa non segna", 1 - h1)
    add("1tao05", g, "1° tempo: segna l'ospite", a1s); add("1tau05", g, "1° tempo: ospite non segna", 1 - a1s)
    g = "2° tempo"
    b1, bx, b2 = _sum(M2, lambda i, j: i > j), _sum(M2, lambda i, j: i == j), _sum(M2, lambda i, j: i < j)
    add("2t1", g, "2° tempo: 1", b1); add("2tx", g, "2° tempo: X", bx); add("2t2", g, "2° tempo: 2", b2)
    for n in (0.5, 1.5, 2.5):
        k = "%02d" % int(n * 10)
        po = _sum(M2, lambda i, j: i + j > n)
        add("2to" + k, g, "2° tempo over %.1f" % n, po); add("2tu" + k, g, "2° tempo under %.1f" % n, 1 - po)
    gg2 = _sum(M2, lambda i, j: i > 0 and j > 0)
    add("2tgg", g, "2° tempo: Goal", gg2); add("2tng", g, "2° tempo: No goal", 1 - gg2)
    h2 = _sum(M2, lambda i, j: i > 0)
    a2s = _sum(M2, lambda i, j: j > 0)
    add("2tho05", g, "2° tempo: segna la casa", h2); add("2tao05", g, "2° tempo: segna l'ospite", a2s)
    # tempo con piu' gol (1T, 2T o uguale), con i due tempi indipendenti
    t1 = [sum(M1[i][j] for i in range(len(M1)) for j in range(len(M1)) if i + j == n) for n in range(21)]
    t2 = [sum(M2[i][j] for i in range(len(M2)) for j in range(len(M2)) if i + j == n) for n in range(21)]
    more1 = sum(t1[a] * t2[b] for a in range(21) for b in range(21) if a > b)
    more2 = sum(t1[a] * t2[b] for a in range(21) for b in range(21) if a < b)
    add("tpg1", g, "Tempo con più gol: 1°", more1); add("tpg2", g, "Tempo con più gol: 2°", more2)
    add("tpgx", g, "Tempo con più gol: uguale", 1 - more1 - more2)
    # entrambi i tempi (i due tempi trattati come indipendenti)
    g = "Entrambi i tempi"
    o1 = [_sum(M1, lambda i, j: i + j > n) for n in (0.5, 1.5)]
    o2 = [_sum(M2, lambda i, j: i + j > n) for n in (0.5, 1.5)]
    add("btgg", g, "Goal 1° tempo + Goal 2° tempo", gg1 * gg2)
    add("btgo", g, "Goal in almeno un tempo", 1 - (1 - gg1) * (1 - gg2))
    add("bto05", g, "Over 0.5 in entrambi i tempi", o1[0] * o2[0])
    add("bto15", g, "Over 1.5 in entrambi i tempi", o1[1] * o2[1])
    add("btu15", g, "Under 1.5 in entrambi i tempi", (1 - o1[1]) * (1 - o2[1]))
    add("bt1o05+2o15", g, "Over 0.5 1° tempo + Over 1.5 2° tempo", o1[0] * o2[1])
    add("bth", g, "Casa segna in entrambi i tempi", h1 * h2)
    add("bta", g, "Ospite segna in entrambi i tempi", a1s * a2s)
    if corners:
        mu, r = corners
        g = "Calci d'angolo"
        for n in (7.5, 8.5, 9.5, 10.5, 11.5):
            k = "%03d" % int(n * 10)
            po = prob_over(n, mu, r)
            add("co" + k, g, "Angoli over %.1f" % n, po); add("cu" + k, g, "Angoli under %.1f" % n, 1 - po)
    if cards:
        mu, r = cards
        g = "Cartellini"
        for n in (2.5, 3.5, 4.5, 5.5):
            k = "%02d" % int(n * 10)
            po = prob_over(n, mu, r)
            add("ko" + k, g, "Cartellini over %.1f" % n, po); add("ku" + k, g, "Cartellini under %.1f" % n, 1 - po)
    g = "Risultato esatto"
    sc = sorted(((M[i][j], i, j) for i in range(7) for j in range(7)), reverse=True)[:10]
    for p, i, j in sc:
        add("cs%d-%d" % (i, j), g, "%d-%d" % (i, j), p)
    return out


def league_dispersion(matches, hf, af):
    """Parametro r della binomiale negativa per il totale di una statistica di squadra."""
    tots = [float(m[hf]) + float(m[af]) for m in matches if m.get(hf) not in (None, "") and m.get(af) not in (None, "")]
    if len(tots) < 30:
        return None
    mean = sum(tots) / len(tots)
    var = sum((t - mean) ** 2 for t in tots) / (len(tots) - 1)
    return round(mean * mean / (var - mean), 2) if var > mean * 1.02 else None


def first_half_share(matches, default=0.445):
    num = den = 0.0
    for m in matches:
        if m.get("hs1") in (None, "") or m.get("hs") in (None, ""):
            continue
        num += float(m["hs1"]) + float(m["as1"])
        den += float(m["hs"]) + float(m["as"])
    if den <= 0:
        return default
    n = den / 2.7
    return default + (num / den - default) * (n / (n + 100))


# ------------------------------------------------------------ doppia doppia / tripla doppia (NBA)
DD_STATS = ["pts", "reb", "ast", "stl", "blk"]
# nodi e pesi di Gauss-Hermite (probabilisti, 9 punti) per integrare sulla variabilita' dei minuti
_GH = [(-4.512745863399783, 2.2345844007746e-05), (-3.205429002856470, 0.002789141321231769),
       (-2.076847978677830, 0.04991640676521788), (-1.023255663789133, 0.24409750289493910),
       (0.0, 0.4063492063492063), (1.023255663789133, 0.24409750289493910),
       (2.076847978677830, 0.04991640676521788), (3.205429002856470, 0.002789141321231769),
       (4.512745863399783, 2.2345844007746e-05)]


def dd_td(proj, exp_min, var_min):
    """Probabilita' di doppia doppia e tripla doppia.

    Le statistiche sono legate tra loro soprattutto dai minuti giocati: condiziono su un fattore
    minuti comune (lognormale, dalla variabilita' dei minuti), con cui le statistiche diventano
    indipendenti (binomiale negativa con la dispersione restante); poi conto quante arrivano a 10."""
    cv2 = max(0.0, var_min) / (exp_min * exp_min) if exp_min > 0 else 0.0
    sig2 = math.log(1 + cv2)
    sig = math.sqrt(sig2)
    stats = [(proj[s][0], proj[s][1]) for s in DD_STATS if s in proj and proj[s][0] > 0]
    if len(stats) < 2:
        return 0.0, 0.0
    pdd = ptd = 0.0
    for x, w in _GH:
        z = math.exp(sig * x - sig2 / 2)
        qs = []
        for mu, r in stats:
            inv = (1.0 / r - cv2) if r else 0.0
            rr = 1.0 / inv if inv > 0.01 else None
            qs.append(1.0 - nb_cdf(9, mu * z, rr))
        # distribuzione del numero di statistiche >= 10
        dist = [1.0]
        for q in qs:
            nd = [0.0] * (len(dist) + 1)
            for k, pk in enumerate(dist):
                nd[k] += pk * (1 - q)
                nd[k + 1] += pk * q
            dist = nd
        pdd += w * sum(dist[2:])
        ptd += w * sum(dist[3:])
    return min(0.97, pdd), min(0.9, ptd)


def dd_count(row):
    return sum(1 for s in DD_STATS if float(row.get(s, 0) or 0) >= 10)


# ------------------------------------------------------------ precedenti (H2H)
def h2h_rows(matches, sport, hid, aid, extra=None, limit=12):
    """Scontri diretti dal punto di vista della squadra di casa di oggi.
    Riga: [data, 'h'/'a' (dove giocava la squadra di casa di oggi), gol/punti casa-oggi, gol/punti ospite-oggi,
           1T casa, 1T ospite, angoli casa, angoli ospite, cartellini casa, cartellini ospite, competizione]."""
    def val(x):
        return None if x in (None, "") else int(float(x))
    seen = set()
    out = []
    for m in matches:
        if m.get("sport") != sport or {m.get("hid"), m.get("aid")} != {hid, aid}:
            continue
        if m.get("hs") in (None, "") or m.get("as") in (None, ""):
            continue
        flip = m["hid"] != hid
        pair = lambda a, b: (val(m.get(b)), val(m.get(a))) if flip else (val(m.get(a)), val(m.get(b)))
        row = [m["date"][:10], "a" if flip else "h", *pair("hs", "as")]
        if sport == "soccer":
            row += [*pair("hs1", "as1"), *pair("hc", "ac"), *pair("hk", "ak"), m.get("league", "")]
        seen.add(m["date"][:10])
        out.append(row)
    for e in extra or []:
        d = str(e.get("date", ""))[:10]
        if not d or d in seen or {e.get("hid"), e.get("aid")} != {hid, aid}:
            continue
        flip = e["hid"] != hid
        hs, as_ = (e["as"], e["hs"]) if flip else (e["hs"], e["as"])
        row = [d, "a" if flip else "h", hs, as_]
        if sport == "soccer":
            row += [None, None, None, None, None, None, e.get("comp", "")]
        seen.add(d)
        out.append(row)
    out.sort(key=lambda r: r[0], reverse=True)
    return out[:limit]
