"""Calibrazione: probabilita' previste vs frequenze reali sulle ultime settimane."""
import datetime as dt, math, os, random, sys
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import models, store

def backtest(sport, market_list, days=21, sample=2500):
    logs = store.read_csv("nba_logs.csv" if sport == "nba" else "soccer_logs.csv")
    markets = models.NBA_MARKETS if sport == "nba" else models.SOC_MARKETS
    last = max(r["date"] for r in logs)
    cut = (dt.date.fromisoformat(last) - dt.timedelta(days=days)).isoformat()
    train = [r for r in logs if r["date"] < cut]
    priors = models.league_priors(sport, train, markets, "0000")
    opp_f, home_f = models.opponent_factors(train, markets, "0000", 15 if sport == "nba" else 8)
    byp = defaultdict(list)
    for r in sorted(logs, key=lambda r: r["date"], reverse=True):
        byp[r["pid"]].append(r)
    tests = [r for r in logs if r["date"] >= cut]
    random.seed(1); random.shuffle(tests)
    out = {m: [] for m in market_list}
    for r in tests[:sample]:
        hist = [g for g in byp[r["pid"]] if g["date"] < r["date"]]
        if len(hist) < 5:
            continue
        if sport == "nba":
            l10 = hist[:10]; ws = models.decay_weights(len(l10), 4)
            em = models.wmean([float(g["min"]) for g in l10], ws)
            vm = min(36, models.wmean([(float(g["min"]) - em) ** 2 for g in l10], ws))
            hl, pm = 12, 60
        else:
            if not r["starter"]:
                continue
            st = [g for g in hist[:10] if g["starter"]] or hist[:10]
            em = sum(float(g["min"]) for g in st) / len(st); vm = 0; hl, pm = 10, 270
        fac = {m: opp_f.get(r["opp"], {}).get(m, 1.0) for m in markets}
        proj = models.project(hist, sport, markets, priors, em, vm, fac, hl, pm)
        for m in market_list:
            mu, rr = proj[m]
            line = 0.5 if m in ("card", "g", "a", "sot") and mu < 1 else math.floor(mu) + 0.5
            p = models.prob_over(line, mu, rr)
            x = models.market_value(r, markets[m], m)
            out[m].append((p, 1 if x > line else 0))
    for m, v in out.items():
        if not v: continue
        n = len(v); pm_ = sum(p for p, _ in v) / n; fr = sum(y for _, y in v) / n
        brier = sum((p - y) ** 2 for p, y in v) / n
        bins = defaultdict(list)
        for p, y in v: bins[min(9, int(p * 10))].append(y)
        cal = " ".join("%d0%%:%.0f%%(%d)" % (b, 100 * sum(ys) / len(ys), len(ys)) for b, ys in sorted(bins.items()) if len(ys) >= 30)
        print("%s %-5s n=%d prev=%.3f reale=%.3f brier=%.3f | %s" % (sport, m, n, pm_, fr, brier, cal))

if __name__ == "__main__":
    backtest("nba", ["pts", "reb", "ast", "blk", "fg3m", "pra"])
    backtest("soccer", ["shots", "sot", "fc", "card"])
