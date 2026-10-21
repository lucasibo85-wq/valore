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
    "g": ["g"], "a": ["a"], "ga": ["g", "a"],
}
BERNOULLI = {"card"}  # conta solo "almeno uno"


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
            out[m] = (round(mu, 4), None)
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
def team_strengths(matches, today, half_life_days=150, prior_games=4):
    """Forza d'attacco/difesa per squadra in una lega (rapporti con la media)."""
    import datetime as dt
    t0 = dt.date.fromisoformat(today)
    rows = []
    for m in matches:
        if m.get("hs") in (None, "") or m.get("as") in (None, ""):
            continue
        d = dt.date.fromisoformat(m["date"][:10])
        w = 0.5 ** ((t0 - d).days / half_life_days)
        rows.append((m["hid"], m["aid"], float(m["hs"]), float(m["as"]), w))
    if len(rows) < 10:
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
    def pmf(k, mu):
        return math.exp(-mu) * mu ** k / math.factorial(k)
    ph = [pmf(i, lh) for i in range(max_goals + 1)]
    pa = [pmf(i, la) for i in range(max_goals + 1)]
    p1 = px = p2 = o25 = btts = 0.0
    scores = []
    for i in range(max_goals + 1):
        for j in range(max_goals + 1):
            p = ph[i] * pa[j]
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
