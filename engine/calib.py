"""Autocalibrazione: confronta le previsioni con i risultati reali.

- Prima di ogni partita salva le proiezioni (giocatori NBA e calcio, mercati di squadra del calcio).
- Quando arriva il tabellino misura gli errori, giorno per giorno.
- Dagli ultimi 30 giorni ricava un fattore di correzione per mercato (es. "il modello sovrastima
  gli assist del 4%") applicato alle proiezioni successive, e un report per la pagina Stato dati.
"""
import datetime as dt
import math

from . import models

TEAM_KEYS = ["1", "X", "2", "o15", "o25", "o35", "gg", "1to05", "1to15", "co095", "ko45"]
WINDOW = 30


def eval_soccer_key(k, s):
    """Esito di un mercato di squadra. s = [gc, go, gc1T, go1T, angoli c, angoli o, cart. c, cart. o].
    Ritorna True / False, 'void' (rimborso) o None (dato mancante)."""
    if not s or s[0] is None or s[1] is None:
        return None
    h, a = float(s[0]), float(s[1])
    h1 = a1 = None
    if len(s) > 3 and s[2] is not None and s[3] is not None:
        h1, a1 = float(s[2]), float(s[3])

    def line(code):
        return int(code) / 10.0

    if k == "1":
        return h > a
    if k == "X":
        return h == a
    if k == "2":
        return h < a
    if k == "1X":
        return h >= a
    if k == "X2":
        return h <= a
    if k == "12":
        return h != a
    if k in ("dnb1", "dnb2"):
        return "void" if h == a else ((h > a) == (k == "dnb1"))
    if k == "gg":
        return h > 0 and a > 0
    if k == "ng":
        return not (h > 0 and a > 0)
    if k[:1] in ("o", "u") and k[1:].isdigit():
        return (h + a > line(k[1:])) == (k[0] == "o")
    if k.startswith("mg"):
        lo, hi = k[2:].split("-")
        return int(lo) <= h + a <= int(hi)
    if k[:2] in ("ho", "hu", "ao", "au"):
        v = h if k[0] == "h" else a
        return (v > line(k[2:])) == (k[1] == "o")
    combos = {"1+o15": h > a and h + a > 1.5, "1+o25": h > a and h + a > 2.5, "2+o15": h < a and h + a > 1.5,
              "2+o25": h < a and h + a > 2.5, "1+gg": h > a and a > 0, "2+gg": h < a and h > 0,
              "x+u25": h == a and h + a < 2.5, "1x+o15": h >= a and h + a > 1.5, "x2+o15": h <= a and h + a > 1.5,
              "1x+u35": h >= a and h + a < 3.5, "x2+u35": h <= a and h + a < 3.5,
              "gg+o25": h > 0 and a > 0 and h + a > 2.5, "ng+u25": (h == 0 or a == 0) and h + a < 2.5}
    if k in combos:
        return combos[k]
    if k.startswith("cs"):
        x, y = k[2:].split("-")
        return h == int(x) and a == int(y)
    if k.startswith("1t") or k.startswith("2t") or k.startswith("tpg"):
        if h1 is None:
            return None
        h2, a2 = h - h1, a - a1
        if k.startswith("tpg"):
            g1, g2 = h1 + a1, h2 + a2
            return {"tpg1": g1 > g2, "tpg2": g2 > g1, "tpgx": g1 == g2}[k]
        x, y = (h1, a1) if k.startswith("1t") else (h2, a2)
        r = k[2:]
        if r == "1":
            return x > y
        if r == "x":
            return x == y
        if r == "2":
            return x < y
        if r == "gg":
            return x > 0 and y > 0
        if r == "ng":
            return not (x > 0 and y > 0)
        if r in ("1x", "x2", "12"):
            return {"1x": x >= y, "x2": x <= y, "12": x != y}[r]
        if r[:2] in ("ho", "hu", "ao", "au"):
            v = x if r[0] == "h" else y
            return (v > line(r[2:])) == (r[1] == "o")
        if r[:1] in ("o", "u"):
            return (x + y > line(r[1:])) == (r[0] == "o")
        return None
    if k[:2] in ("co", "cu", "ko", "ku"):
        idx = 4 if k[0] == "c" else 6
        if len(s) <= idx + 1 or s[idx] is None or s[idx + 1] is None:
            return None
        v = float(s[idx]) + float(s[idx + 1])
        return (v > line(k[2:])) == (k[1] == "o")
    return None


def _start(t):
    try:
        return dt.datetime.fromisoformat(str(t)[:16].replace("Z", ""))
    except ValueError:
        return None


def record(state, app, now, factors):
    """Salva le proiezioni delle partite che iniziano entro 36 ore (senza la correzione gia' applicata)."""
    preds = state.setdefault("preds", {})
    limit = now + dt.timedelta(hours=36)
    for sport in ("nba", "soccer", "nfl", "mlb"):
        if sport not in app:
            continue
        times = {g["id"]: g["t"] for g in app[sport].get("games", []) + app[sport].get("matches", [])}
        f = factors.get(sport, {})
        P = preds.setdefault(sport, {})
        for p in app[sport].get("players", []):
            st = _start(times.get(p["g"]))
            if not st or st > limit or st < now - dt.timedelta(hours=1):
                continue
            if sport == "soccer" and p.get("ps", 1) < 0.6:
                continue
            P.setdefault(p["g"], {"t": times.get(p["g"]), "p": {}})["p"][p["id"]] = {
                m: [round(v[0] / f.get(m, 1.0), 4), v[1]] for m, v in p["mk"].items()}
    T = preds.setdefault("soccer_tm", {})
    for m in app.get("soccer", {}).get("matches", []):
        st = _start(m.get("t"))
        if not m.get("mk") or not st or st > limit:
            continue
        T[m["id"]] = {"t": m["t"], "k": {k: p for k, g, l, p in m["mk"] if k in TEAM_KEYS}}


def evaluate(state, logs_by_sport, results, today):
    """Confronta le previsioni salvate con i tabellini arrivati."""
    preds = state.setdefault("preds", {})
    cal = state.setdefault("calib", {})
    day = today.isoformat()
    for sport, logs in logs_by_sport.items():
        P = preds.get(sport, {})
        if not P:
            continue
        rows = {}
        for r in logs:
            if r["gid"] in P:
                rows[(r["gid"], r["pid"])] = r
        have = {g for g, _ in rows}
        if sport in ("nfl", "mlb"):
            from . import props
            markets = props.SPORTS[sport]["markets"]
        else:
            markets = models.NBA_MARKETS if sport == "nba" else models.SOC_MARKETS
        C = cal.setdefault(sport, {})
        for gid in list(P):
            if gid not in have:
                st = _start(P[gid].get("t"))
                if st and st.date() < today - dt.timedelta(days=7):
                    del P[gid]
                continue
            for pid, mk in P[gid]["p"].items():
                r = rows.get((gid, pid))
                if r is None:
                    continue  # non ha giocato
                for m, (mu, rr) in mk.items():
                    if m not in markets:
                        continue
                    x = models.market_value(r, markets[m], m)
                    L = 0.5 if m in models.BERNOULLI else math.floor(mu) + 0.5
                    p = models.prob_over(L, mu, rr)
                    y = 1.0 if x > L else 0.0
                    b = C.setdefault(m, {}).setdefault(day, [0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
                    b[0] += 1
                    b[1] += (1 - math.exp(-mu)) if m in models.BERNOULLI else mu
                    b[2] += x
                    b[3] += abs(x - ((1 - math.exp(-mu)) if m in models.BERNOULLI else mu))
                    b[4] += p
                    b[5] += y
                    b[6] += (p - y) ** 2
            del P[gid]
    # mercati di squadra del calcio
    T = preds.get("soccer_tm", {})
    RS = (results or {}).get("soccer", {})
    CT = cal.setdefault("soccer_tm", {})
    for gid in list(T):
        R = RS.get(gid)
        if not R:
            st = _start(T[gid].get("t"))
            if st and st.date() < today - dt.timedelta(days=7):
                del T[gid]
            continue
        for k, p in T[gid]["k"].items():
            y = eval_soccer_key(k, R["s"])
            if y is None or y == "void":
                continue
            y = 1.0 if y else 0.0
            b = CT.setdefault(k, {}).setdefault(day, [0, 0.0, 0.0, 0.0])
            b[0] += 1
            b[1] += p
            b[2] += y
            b[3] += (p - y) ** 2
        del T[gid]
    # tiene solo gli ultimi 60 giorni
    cut = (today - dt.timedelta(days=60)).isoformat()
    for sp in cal.values():
        for m in sp.values():
            for d in [d for d in m if d < cut]:
                del m[d]


def _agg(days, n_fields, today):
    cut = (today - dt.timedelta(days=WINDOW)).isoformat()
    tot = [0.0] * n_fields
    for d, b in days.items():
        if d >= cut:
            for i in range(n_fields):
                tot[i] += b[i]
    return tot


def factors(state, sport, today=None):
    """Fattori di correzione per mercato (1 = nessuna correzione)."""
    today = today or dt.datetime.utcnow().date()
    out = {}
    for m, days in state.get("calib", {}).get(sport, {}).items():
        n, smu, sact = _agg(days, 7, today)[:3]
        if n < 80 or smu <= 0:
            continue
        f = 1 + (sact / smu - 1) * (n / (n + 300))
        out[m] = round(max(0.9, min(1.1, f)), 4)
    return out


def report(state, today):
    rep = {}
    for sport in ("nba", "soccer", "nfl", "mlb"):
        rows = {}
        for m, days in state.get("calib", {}).get(sport, {}).items():
            n, smu, sact, sabs, sp, sy, sb = _agg(days, 7, today)
            if n <= 0:
                continue
            rows[m] = {"n": int(n), "bias": round(sact / smu - 1, 4) if smu else None, "mae": round(sabs / n, 3),
                       "p": round(sp / n, 4), "y": round(sy / n, 4), "brier": round(sb / n, 4)}
        rep[sport] = rows
    rows = {}
    for k, days in state.get("calib", {}).get("soccer_tm", {}).items():
        n, sp, sy, sb = _agg(days, 4, today)
        if n > 0:
            rows[k] = {"n": int(n), "p": round(sp / n, 4), "y": round(sy / n, 4), "brier": round(sb / n, 4)}
    rep["soccer_tm"] = rows
    rep["factors"] = {sp: factors(state, sp, today) for sp in ("nba", "soccer", "nfl", "mlb")}
    return rep
