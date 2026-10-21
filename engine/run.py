"""Aggiornamento completo: scarica i dati, calcola le proiezioni, scrive docs/data/.

Uso:  python -m engine.run            (aggiornamento normale)
      python -m engine.run --no-odds  (senza quote automatiche)
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
from collections import defaultdict

from . import espn, models, net, odds, props, store, tennis

ROOT = store.ROOT
OUT_DIR = os.environ.get("VALORE_OUT") or os.path.join(ROOT, "docs", "data")


def log(*a):
    print(*a, flush=True)


def d2s(d):
    return d.strftime("%Y%m%d")


def iso(d):
    return d.isoformat()


# ====================================================================== scansione
def scan_days(path, start, end, per_day):
    """Eventi tra start ed end (date). per_day=True: una chiamata per giorno."""
    events = []
    if per_day:
        d = start
        while d <= end:
            evs = espn.scoreboard(path, d2s(d))
            events.extend(evs or [])
            d += dt.timedelta(days=1)
        return events
    d = start
    while d <= end:
        e = min(end, d + dt.timedelta(days=27))
        evs = espn.scoreboard(path, "%s-%s" % (d2s(d), d2s(e)))
        if evs is None:  # intervallo non supportato: giorno per giorno
            evs = scan_days(path, d, e, True)
        events.extend(evs)
        d = e + dt.timedelta(days=1)
    return events


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-odds", action="store_true")
    ap.add_argument("--max-summaries", type=int, default=None)
    args = ap.parse_args()

    t_start = time.time()
    with open(os.environ.get("VALORE_CONFIG") or os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    net.PAUSE = float(cfg.get("request_pause_seconds", 0.3))
    max_summ = args.max_summaries or int(cfg.get("max_summaries_per_run", 1500))

    today = dt.datetime.utcnow().date()
    ahead = int(cfg.get("days_ahead", 2))
    state = store.read_json("state.json", {})
    state.setdefault("processed", {"nba": [], "soccer": []})
    state.setdefault("scan", {})
    processed = {k: set(v) for k, v in state["processed"].items()}
    teams = store.read_json("teams.json", {"nba": {}, "soccer": {}})
    US = [sp for sp in ("nfl", "mlb") if cfg.get(sp, {}).get("enabled")]
    us_logs = {sp: store.read_csv(sp + "_logs.csv") for sp in US}
    for sp in US:
        teams.setdefault(sp, {})
        processed.setdefault(sp, set())

    nba_logs = store.read_csv("nba_logs.csv")
    soc_logs = store.read_csv("soccer_logs.csv")
    matches = store.read_csv("matches.csv")
    match_by_gid = {m["gid"]: m for m in matches}

    queue = []       # (sport, path, league, event)
    upcoming = []    # (sport, path, league, event)

    def remember(sport, league, ev):
        for side in ("home", "away"):
            t = ev[side]
            teams[sport][t["id"]] = {"abbr": t["abbr"], "name": t["name"]}
        if ev["completed"]:
            row = match_by_gid.get(ev["id"]) or {"referee": ""}
            row.update({"sport": sport, "league": league, "gid": ev["id"], "date": ev["date"][:10],
                        "hid": ev["home"]["id"], "aid": ev["away"]["id"], "hs": ev["hs"], "as": ev["as"]})
            if ev["id"] not in match_by_gid:
                matches.append(row)
                match_by_gid[ev["id"]] = row

    # ---------------- NBA (solo stagione regolare, play-in e playoff)
    nba_excluded = set()
    if cfg["nba"].get("enabled"):
        key = "nba"
        purge = not state.get("nba_solo_stagione")
        if purge or key not in state["scan"]:
            start = today - dt.timedelta(days=cfg["nba"]["backfill_days"])
        else:
            start = dt.date.fromisoformat(state["scan"][key])
        log("NBA: scansione dal", start, "(controllo preseason sull'intero storico)" if purge else "")
        no_type = 0
        for ev in scan_days("basketball/nba", start, today, per_day=True):
            if not espn.nba_counts(ev):
                nba_excluded.add(ev["id"])
                continue
            no_type += 1 if not ev.get("stype") else 0
            remember("nba", "nba", ev)
            if ev["completed"] and ev["id"] not in processed["nba"]:
                queue.append(("nba", "basketball/nba", "nba", ev))
        for ev in scan_days("basketball/nba", today, today + dt.timedelta(days=ahead), per_day=True):
            if not espn.nba_counts(ev):
                continue
            remember("nba", "nba", ev)
            if not ev["completed"]:
                upcoming.append(("nba", "basketball/nba", "nba", ev))
        if nba_excluded:
            before = len(nba_logs)
            nba_logs = [r for r in nba_logs if r["gid"] not in nba_excluded]
            matches = [m for m in matches if not (m.get("sport") == "nba" and m["gid"] in nba_excluded)]
            for g in nba_excluded:
                match_by_gid.pop(g, None)
            processed["nba"] -= nba_excluded
            log("NBA: escluse %d partite di preseason/All-Star (%d righe tolte dall'archivio)" % (
                len(nba_excluded), before - len(nba_logs)))
        if no_type:
            log("NBA: %d partite senza tipo di stagione (tenute)" % no_type)
        state["nba_solo_stagione"] = True
        state["scan"][key] = iso(today - dt.timedelta(days=2))

    # ---------------- Calcio
    if cfg["soccer"].get("enabled"):
        for league in cfg["soccer"]["leagues"]:
            path = "soccer/" + league
            start = dt.date.fromisoformat(state["scan"][league]) if league in state["scan"] else today - dt.timedelta(days=cfg["soccer"]["backfill_days"])
            evs = scan_days(path, start, today, per_day=False)
            n_new = 0
            for ev in evs:
                remember("soccer", league, ev)
                if ev["completed"] and ev["id"] not in processed["soccer"]:
                    queue.append(("soccer", path, league, ev))
                    n_new += 1
            for ev in scan_days(path, today, today + dt.timedelta(days=ahead), per_day=False):
                remember("soccer", league, ev)
                if not ev["completed"] and ev["state"] == "pre":
                    upcoming.append(("soccer", path, league, ev))
            state["scan"][league] = iso(today - dt.timedelta(days=3))
            log("Calcio %s: %d partite trovate, %d nuove" % (league, len(evs), n_new))

    # ---------------- NFL e MLB (solo stagione regolare e playoff)
    for sp in US:
        path = props.SPORTS[sp]["path"]
        start = dt.date.fromisoformat(state["scan"][sp]) if sp in state["scan"] else today - dt.timedelta(days=cfg[sp].get("backfill_days", 400))
        n_new = 0
        for ev in scan_days(path, start, today, per_day=True):
            if not espn.nba_counts(ev, sp):
                continue
            remember(sp, sp, ev)
            if ev["completed"] and ev["id"] not in processed[sp]:
                queue.append((sp, path, sp, ev))
                n_new += 1
        for ev in scan_days(path, today, today + dt.timedelta(days=int(cfg[sp].get("days_ahead", ahead))), per_day=True):
            if espn.nba_counts(ev, sp) and not ev["completed"]:
                remember(sp, sp, ev)
                upcoming.append((sp, path, sp, ev))
        state["scan"][sp] = iso(today - dt.timedelta(days=2))
        log("%s: %d partite nuove da leggere" % (sp.upper(), n_new))

    # ---------------- Tennis (risultati per il modello Elo)
    t_matches, t_up = [], []
    if cfg.get("tennis", {}).get("enabled"):
        t_all = {m["gid"]: m for m in store.read_csv("tennis.csv")}
        up = {}
        for tour in cfg["tennis"].get("tours", ["atp", "wta"]):
            k = "tennis_" + tour
            d = dt.date.fromisoformat(state["scan"][k]) if k in state["scan"] else today - dt.timedelta(days=cfg["tennis"].get("backfill_days", 400))
            while d <= today + dt.timedelta(days=ahead):
                for m in tennis.scoreboard(tour, d) or []:
                    if m["completed"] and m["winner"] and not m["walkover"]:
                        t_all[m["gid"]] = {c: m[c] for c in tennis.COLS}
                    elif not m["completed"] and m["state"] == "pre" and m["date"][:10] >= iso(today):
                        up[m["gid"]] = m
                d += dt.timedelta(days=1)
            state["scan"][k] = iso(today - dt.timedelta(days=2))
        t_matches = list(t_all.values())
        t_up = list(up.values())
        log("Tennis: %d partite in archivio, %d in programma" % (len(t_matches), len(t_up)))

    # ---------------- Tabellini delle partite concluse (prima le piu' recenti)
    for q in state.get("queue", []):  # rimasti dalle esecuzioni precedenti
        if q[3]["id"] not in processed[q[0]] and q[3]["id"] not in nba_excluded:
            queue.append(tuple(q))
    seen = set()
    queue = [q for q in queue if not (q[3]["id"] in seen or seen.add(q[3]["id"]))]
    queue.sort(key=lambda q: q[3]["date"], reverse=True)
    log("Tabellini da scaricare: %d (massimo %d in questa esecuzione)" % (len(queue), max_summ))
    done = 0
    empty = 0
    for sport, path, league, ev in queue[:max_summ]:
        summ = espn.summary(path, ev["id"])
        if summ is None:
            continue
        date = ev["date"][:10]
        h, a = ev["home"]["id"], ev["away"]["id"]
        if sport == "nba":
            rows = espn.parse_nba_box(summ)
        elif sport == "soccer":
            rows = espn.parse_soccer_box(summ)
        else:
            rows = props.parse_box(sport, summ)
        for r in rows:
            r.update({"gid": ev["id"], "date": date, "home": 1 if r["team"] == h else 0,
                      "opp": a if r["team"] == h else h})
            if sport == "soccer":
                r["league"] = league
        if sport == "nba":
            nba_logs.extend(rows)
        elif sport in us_logs:
            us_logs[sport].extend(rows)
        else:
            soc_logs.extend(rows)
            ref = espn.parse_referee(summ)
            if ref and ev["id"] in match_by_gid:
                match_by_gid[ev["id"]]["referee"] = ref
        if not rows:
            empty += 1
        processed[sport].add(ev["id"])
        done += 1
        if done % 100 == 0:
            log("  ... %d tabellini" % done)
    log("Tabellini scaricati: %d (senza statistiche giocatori: %d)" % (done, empty))
    if done and empty == done:
        log("ATTENZIONE: nessuna statistica letta. Il formato ESPN potrebbe essere cambiato.")

    # ---------------- Pulizia storico
    cutoff = iso(today - dt.timedelta(days=int(cfg.get("history_days", 420))))
    nba_logs = [r for r in nba_logs if r["date"] >= cutoff]
    soc_logs = [r for r in soc_logs if r["date"] >= cutoff]
    for sp in US:
        us_logs[sp] = [r for r in us_logs[sp] if r["date"] >= cutoff]
    t_matches = [m for m in t_matches if m["date"][:10] >= cutoff]
    matches = [m for m in matches if m["date"] >= cutoff]
    keep = set(r["gid"] for r in nba_logs) | set(r["gid"] for r in soc_logs) | set(m["gid"] for m in matches)
    for sp in US:
        keep |= set(r["gid"] for r in us_logs[sp])
    for k in processed:
        processed[k] = set(g for g in processed[k] if g in keep)

    # ---------------- Anteprime: infortuni, formazioni, arbitro
    previews = {}
    soon = (dt.datetime.utcnow() + dt.timedelta(hours=40)).isoformat()
    for sport, path, league, ev in upcoming:
        if ev["date"][:19] <= soon or sport == "nfl":
            summ = espn.summary(path, ev["id"])
            if summ:
                previews[ev["id"]] = {
                    "inj": espn.parse_injuries(summ),
                    "lineup": espn.parse_lineup(summ) if sport == "soccer" else set(),
                    "ref": espn.parse_referee(summ) if sport == "soccer" else "",
                    "probables": (props.probables(summ) or ev.get("probables") or {}) if sport == "mlb" else {},
                }

    # ---------------- Quote automatiche
    odds_cache = state.get("odds_cache", {})
    if not args.no_odds and cfg.get("odds", {}).get("enabled") and odds.key():
        odds_cache = fetch_odds(cfg, state, today, upcoming, teams, odds_cache)
        state["odds_cache"] = odds_cache
    elif not odds.key():
        log("Quote automatiche: nessuna chiave ODDS_API_KEY, salto (inserimento manuale nell'app).")

    # ---------------- Salvataggio archivio
    store.write_csv("nba_logs.csv", sorted(nba_logs, key=lambda r: (r["date"], r["gid"])), store.NBA_COLS)
    store.write_csv("soccer_logs.csv", sorted(soc_logs, key=lambda r: (r["date"], r["gid"])), store.SOC_COLS)
    store.write_csv("matches.csv", sorted(matches, key=lambda m: (m["date"], m["gid"])), store.MATCH_COLS)
    for sp in US:
        store.write_csv(sp + "_logs.csv", sorted(us_logs[sp], key=lambda r: (r["date"], r["gid"])), props.cols(sp))
    if cfg.get("tennis", {}).get("enabled"):
        store.write_csv("tennis.csv", sorted(t_matches, key=lambda m: (m["date"], m["gid"])), tennis.COLS)
    state["processed"] = {k: sorted(v) for k, v in processed.items()}
    store.write_json("teams.json", teams)

    # ---------------- Output per l'app
    app = {"generated": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
           "leagues": cfg["soccer"]["leagues"], "nba": {"games": [], "players": []},
           "soccer": {"matches": [], "players": []}}
    hist = {"nba": {}, "soccer": {}}
    for sp in US:
        app[sp] = {"games": [], "players": []}
        hist[sp] = {}
        props.build(sp, app, us_logs[sp], upcoming, previews, teams, today, hist)
    if cfg.get("tennis", {}).get("enabled"):
        app["tennis"] = {"matches": []}
        tennis.build(app, t_matches, t_up)
    if cfg["nba"].get("enabled"):
        build_nba(app, nba_logs, upcoming, previews, teams, today, odds_cache, hist)
    if cfg["soccer"].get("enabled"):
        build_soccer(app, soc_logs, matches, upcoming, previews, teams, today, odds_cache, hist)
    store.write_json("hist.json", hist, target=os.path.join(OUT_DIR, "hist.json"), compact=True)
    store.write_json("app.json", app, target=os.path.join(OUT_DIR, "app.json"), compact=True)
    store.write_json("results.json", build_results(nba_logs, soc_logs, matches, today, us_logs, t_matches),
                     target=os.path.join(OUT_DIR, "results.json"), compact=True)
    state["queue"] = [list(q) for q in queue if q[3]["id"] not in processed[q[0]] and q[3]["date"][:10] >= cutoff]
    state["last_run"] = app["generated"]
    store.write_json("state.json", state)
    for sp in US:
        log("%s: %d giocatori nelle prossime partite" % (sp.upper(), len(app[sp]["players"])))
    log("Fatto in %.0fs. Richieste: %d, errori: %d. Giocatori NBA: %d, calcio: %d, partite calcio: %d" % (
        time.time() - t_start, net.STATS["requests"], net.STATS["errors"],
        len(app["nba"]["players"]), len(app["soccer"]["players"]), len(app["soccer"]["matches"])))
    remaining = len([q for q in queue if q[3]["id"] not in processed[q[0]]])
    if remaining > 0:
        log("Restano %d tabellini: verranno scaricati nelle prossime esecuzioni." % remaining)


# ====================================================================== quote
def _match_event(events, hn, an, thr=0.34):
    best, score = None, 0.0
    for o in events:
        sh, sa = odds.similar(hn, o.get("home_team", o.get("home", ""))), odds.similar(an, o.get("away_team", o.get("away", "")))
        if sh >= thr and sa >= thr and sh + sa > score:
            best, score = o, sh + sa
    return best


def fetch_odds(cfg, state, today, upcoming, teams, cache):
    """Scarica le quote rispettando il budget giornaliero di crediti.

    Con il piano gratuito: un solo aggiornamento al giorno. Con un piano a pagamento
    basta alzare daily_credit_budget e abbassare refresh_hours in config.json.
    """
    oc = cfg["odds"]
    budget = int(oc.get("daily_credit_budget", 15))
    refresh_h = float(oc.get("refresh_hours", 24))
    st = state.get("odds_usage", {})
    now = dt.datetime.utcnow()
    if st.get("date") != iso(today):
        st = {"date": iso(today), "used": 0, "last": st.get("last", "")}
    last = st.get("last") or ""
    fresh = last and (now - dt.datetime.fromisoformat(last)).total_seconds() < refresh_h * 3600
    if fresh or st["used"] >= budget:
        log("Quote: riuso quelle salvate (%d crediti usati oggi su %d)." % (st["used"], budget))
        state["odds_usage"] = st
        return cache
    region = oc.get("regions", "eu")
    cost_region = len(region.split(","))
    new = {"soccer": {}, "nba": {}, "soccer_props": {}}
    by_league = defaultdict(list)
    for s_, p_, l_, e_ in upcoming:
        if s_ == "soccer":
            by_league[l_].append(e_)
    # calcio 1X2
    if oc.get("soccer_h2h", True):
        for lg in sorted(by_league):
            if st["used"] + cost_region > budget:
                break
            rows, rem = odds.soccer_h2h(lg, region)
            st["used"] += cost_region
            for ev in by_league[lg]:
                hn = teams["soccer"].get(ev["home"]["id"], {}).get("name", "")
                an = teams["soccer"].get(ev["away"]["id"], {}).get("name", "")
                best = _match_event(rows, hn, an)
                if best:
                    new["soccer"][ev["id"]] = [best["o1"], best["ox"], best["o2"], best["book"], best.get("f1"), best.get("fx"), best.get("f2"),
                                              best["b1"], best["bx"], best["b2"], best["ref"], best["nb"]]
    # NBA prop giocatori
    markets = oc.get("nba_prop_markets", ["player_points"])
    nreg = oc.get("nba_regions", "us")
    cost = len(markets) * len(nreg.split(","))
    nba_up = sorted([e for s_, p_, l_, e in upcoming if s_ == "nba"], key=lambda e: e["date"])
    if markets and nba_up and st["used"] + cost <= budget:
        evs = odds.nba_events()
        for ev in nba_up:
            if st["used"] + cost > budget:
                break
            hn = teams["nba"].get(ev["home"]["id"], {}).get("name", "")
            an = teams["nba"].get(ev["away"]["id"], {}).get("name", "")
            match = _match_event(evs, hn, an, 0.5)
            if not match:
                continue
            rows, rem = odds.nba_props(match["id"], markets, nreg)
            st["used"] += cost
            for r in rows:
                new["nba"].setdefault(ev["id"], []).append([r["player"], r["m"], r["line"], r["over"], r["under"], r["book"], r.get("fair"), r.get("nb", 0)])
    # calcio prop giocatori (facoltative, consumano molti crediti)
    smarkets = oc.get("soccer_prop_markets", [])
    sreg = oc.get("soccer_prop_regions", "us")
    cost = len(smarkets) * len(sreg.split(","))
    if smarkets:
        for lg in sorted(by_league):
            sk = odds.SOCCER_KEYS.get(lg)
            if not sk or st["used"] + cost > budget:
                continue
            evs = odds.events(sk)
            for ev in sorted(by_league[lg], key=lambda e: e["date"]):
                if st["used"] + cost > budget:
                    break
                hn = teams["soccer"].get(ev["home"]["id"], {}).get("name", "")
                an = teams["soccer"].get(ev["away"]["id"], {}).get("name", "")
                match = _match_event(evs, hn, an)
                if not match:
                    continue
                rows, rem = odds.event_props(sk, match["id"], smarkets, sreg, odds.SOCCER_PROP_MAP)
                st["used"] += cost
                for r in rows:
                    new["soccer_props"].setdefault(ev["id"], []).append([r["player"], r["m"], r["line"], r["over"], r["under"], r["book"], r.get("fair"), r.get("nb", 0)])
    st["last"] = now.replace(microsecond=0).isoformat()
    log("Quote: %d crediti usati oggi su %d" % (st["used"], budget))
    state["odds_usage"] = st
    return new


def name_key(n):
    t = odds.norm(n)
    return " ".join(x for x in t if x not in ("jr", "sr", "ii", "iii", "iv"))


# ====================================================================== NBA
def build_nba(app, logs, upcoming, previews, teams, today, odds_cache, hist):
    if not logs:
        return
    markets = models.NBA_MARKETS
    since_long = iso(today - dt.timedelta(days=365))
    priors = models.league_priors("nba", logs, markets, since_long)
    since_opp = iso(today - dt.timedelta(days=150))
    if len(set(r["gid"] for r in logs if r["date"] >= since_opp)) < 300:
        since_opp = since_long
    opp_f, home_f = models.opponent_factors(logs, markets, since_opp, k=15)
    season_start = dt.date(today.year if today.month >= 10 else today.year - 1, 10, 1).isoformat()

    by_player = defaultdict(list)
    tg_set = defaultdict(dict)
    for r in logs:
        by_player[r["pid"]].append(r)
        tg_set[r["team"]][r["gid"]] = r["date"]
    team_games = {t: sorted(d.items(), key=lambda x: x[1]) for t, d in tg_set.items()}
    for pid in by_player:
        by_player[pid].sort(key=lambda r: r["date"], reverse=True)
    current = defaultdict(list)
    for pid, games in by_player.items():
        current[games[0]["team"]].append(pid)

    tabbr = lambda tid: teams["nba"].get(tid, {}).get("abbr", "?")
    for sport, path, league, ev in upcoming:
        if sport != "nba":
            continue
        pv = previews.get(ev["id"], {})
        inj = pv.get("inj", {})
        app["nba"]["games"].append({"id": ev["id"], "t": ev["date"], "h": tabbr(ev["home"]["id"]),
                                    "a": tabbr(ev["away"]["id"]), "hn": ev["home"]["name"], "an": ev["away"]["name"],
                                    "odds": ev.get("odds")})
        props = {}
        for row in odds_cache.get("nba", {}).get(ev["id"], []):
            props.setdefault(name_key(row[0]), {})[row[1]] = row[2:]
        for side, opp_side in (("home", "away"), ("away", "home")):
            tid, oid = ev[side]["id"], ev[opp_side]["id"]
            tg = team_games.get(tid, [])
            this_season = [g for g, d in tg if d >= season_start]
            for pid in current.get(tid, []):
                games = by_player[pid]
                if this_season and len(this_season) >= 2 and games[0]["date"] < season_start:
                    continue
                if games[0]["date"] < iso(today - dt.timedelta(days=200)):
                    continue
                status = inj.get(pid, "")
                if status.lower().startswith("out"):
                    continue
                # partite di squadra saltate di recente
                after = [g for g, d in tg if d > games[0]["date"]]
                if len(after) >= 4:
                    continue
                last10 = games[:10]
                ws = models.decay_weights(len(last10), 4)
                mins = [float(r["min"]) for r in last10]
                exp_min = models.wmean(mins, ws)
                if exp_min < 10:
                    continue
                var_min = min(36.0, models.wmean([(m - exp_min) ** 2 for m in mins], ws))
                fac = {}
                for m in markets:
                    fac[m] = opp_f.get(oid, {}).get(m, 1.0) * (home_f.get(m, 1.0) if side == "home" else (2 - home_f.get(m, 1.0)))
                proj = models.project(games, "nba", markets, priors, exp_min, var_min, fac, 12, 60)
                if after and not status:
                    status = "Assente ultime %d" % len(after)
                p = {
                    "id": pid, "n": games[0]["name"], "t": tabbr(tid), "o": tabbr(oid), "g": ev["id"],
                    "h": 1 if side == "home" else 0, "pos": games[0].get("pos", ""), "st": status,
                    "m": round(exp_min, 1),
                    "mk": {m: list(v) for m, v in proj.items()},
                    "of": {m: round(opp_f.get(oid, {}).get(m, 1.0), 3) for m in markets},
                    "a30": {m: round(sum(models.market_value(r, c, m) for r in games[:30]) / len(games[:30]), 2)
                            for m, c in markets.items()},
                    "l": [[r["date"], tabbr(r["opp"]), round(float(r["min"]))] + [int(float(r[b])) for b in models.NBA_BASE]
                          for r in games[:10]],
                }
                od = props.get(name_key(p["n"]))
                if od:
                    p["odds"] = od
                app["nba"]["players"].append(p)
                hist["nba"][pid] = [[r["date"], tabbr(r["opp"]), round(float(r["min"]))] + [int(float(r[b])) for b in models.NBA_BASE]
                                    for r in games[:100]]


# ====================================================================== Calcio
def build_soccer(app, logs, matches, upcoming, previews, teams, today, odds_cache, hist):
    markets = models.SOC_MARKETS
    since_long = iso(today - dt.timedelta(days=365))
    tname = lambda tid: teams["soccer"].get(tid, {}).get("name", "?")
    tabbr = lambda tid: teams["soccer"].get(tid, {}).get("abbr", "?")
    priors = models.league_priors("soccer", logs, markets, since_long) if logs else ({}, {})
    opp_f, home_f = models.opponent_factors(logs, markets, since_long, k=8) if logs else ({}, {})
    ref_f = models.referee_factors(matches, logs)

    strengths = {}
    by_league = defaultdict(list)
    for m in matches:
        if m.get("sport") == "soccer":
            by_league[m["league"]].append(m)
    for lg, ms in by_league.items():
        strengths[lg] = models.team_strengths(ms, iso(today))

    by_player = defaultdict(list)
    team_games = defaultdict(list)
    for r in sorted(logs, key=lambda r: r["date"]):
        by_player[r["pid"]].append(r)
        tg = team_games[r["team"]]
        if r["gid"] not in tg[-40:]:
            tg.append(r["gid"])
    for pid in by_player:
        by_player[pid].sort(key=lambda r: r["date"], reverse=True)
    current = defaultdict(list)
    for pid, games in by_player.items():
        if games[0]["date"] >= iso(today - dt.timedelta(days=120)):
            current[games[0]["team"]].append(pid)

    for sport, path, league, ev in upcoming:
        if sport != "soccer":
            continue
        h, a = ev["home"]["id"], ev["away"]["id"]
        pv = previews.get(ev["id"], {})
        ref = pv.get("ref", "")
        mrow = {"id": ev["id"], "lg": league, "t": ev["date"], "h": tname(h), "a": tname(a),
                "ha": tabbr(h), "aa": tabbr(a)}
        s = strengths.get(league)
        if s and h in s["att"] and a in s["att"]:
            lh = s["avg_h"] * s["att"][h] * s["def"][a]
            la = s["avg_a"] * s["att"][a] * s["def"][h]
            mrow.update({"lh": round(lh, 3), "la": round(la, 3)})
            mrow.update(models.match_probs(lh, la))
        oc = odds_cache.get("soccer", {}).get(ev["id"])
        eo = ev.get("odds")
        if oc:
            mrow["odds"] = oc
        elif eo and eo.get("d"):  # quote gratuite pubblicate da ESPN
            mrow["odds"] = [eo["h"], eo["d"], eo["a"], eo["book"]]
        if ref:
            mrow["ref"] = ref
        app["soccer"]["matches"].append(mrow)

        props = {}
        for row in odds_cache.get("soccer_props", {}).get(ev["id"], []):
            props.setdefault(name_key(row[0]), {})[row[1]] = row[2:]
        lineup = pv.get("lineup") or set()
        for side, tid, oid in (("home", h, a), ("away", a, h)):
            tg = team_games.get(tid, [])[-6:][::-1]
            cands = []
            for pid in current.get(tid, []):
                games = by_player[pid]
                played = {r["gid"]: r for r in games[:12]}
                ws = models.decay_weights(len(tg), 3)
                starts = [1.0 if g in played and played[g]["starter"] else 0.0 for g in tg]
                apps = [1.0 if g in played else 0.0 for g in tg]
                p_start = models.wmean(starts, ws) if tg else 0.0
                if lineup:
                    p_start = 1.0 if pid in lineup else 0.1
                if p_start < 0.25 and sum(apps) < 3:
                    continue
                st_games = [r for r in games[:10] if r["starter"]]
                if p_start >= 0.5 and st_games:
                    exp_min = sum(float(r["min"]) for r in st_games) / len(st_games)
                else:
                    exp_min = sum(float(r["min"]) for r in games[:10]) / len(games[:10])
                cands.append((p_start, pid, exp_min))
            cands.sort(reverse=True)
            for p_start, pid, exp_min in cands[:18]:
                games = by_player[pid]
                fac = {}
                for m in markets:
                    f = opp_f.get(oid, {}).get(m, 1.0)
                    hf = home_f.get(m, 1.0)
                    f *= hf if side == "home" else max(0.5, 2 - hf)
                    if ref and ref in ref_f and m in ("card", "fc"):
                        f *= ref_f[ref][m]
                    fac[m] = f
                proj = models.project(games, "soccer", markets, priors, exp_min, 0.0, fac, 10, 270)
                hist["soccer"][pid] = [[r["date"], tabbr(r["opp"]), round(float(r["min"])), int(r["starter"])] +
                                       [int(float(r[b])) for b in models.SOC_BASE] for r in games[:60]]
                od = props.get(name_key(games[0]["name"]))
                app["soccer"]["players"].append({
                    "odds": od,
                    "id": pid, "n": games[0]["name"], "t": tname(tid), "o": tname(oid), "g": ev["id"],
                    "lg": league, "h": 1 if side == "home" else 0, "pos": games[0].get("pos", ""),
                    "ps": round(p_start, 2), "m": round(exp_min), "lu": 1 if lineup else 0,
                    "mk": {m: list(v) for m, v in proj.items()},
                    "of": {m: round(opp_f.get(oid, {}).get(m, 1.0), 3) for m in markets},
                    "rf": round(ref_f[ref]["card"], 3) if ref and ref in ref_f else None,
                    "a30": {m: round(sum(models.market_value(r, c, m) for r in games[:30]) / len(games[:30]), 3)
                            for m, c in markets.items()},
                    "l": [[r["date"], tabbr(r["opp"]), round(float(r["min"])), int(r["starter"])] +
                          [int(float(r[b])) for b in models.SOC_BASE] for r in games[:10]],
                })


# ====================================================================== risultati
def build_results(nba_logs, soc_logs, matches, today, us_logs=None, t_matches=None):
    since = iso(today - dt.timedelta(days=21))
    us_logs = us_logs or {}
    out = {"nba": {}, "soccer": {}, "tennis": {}}
    for sp in us_logs:
        out[sp] = {}
    for m in matches:
        if m["date"] >= since and m.get("hs") not in (None, "") and m.get("sport") in out:
            out[m["sport"]].setdefault(m["gid"], {"s": [m["hs"], m["as"]], "p": {}})
    for r in nba_logs:
        if r["date"] >= since and r["gid"] in out["nba"]:
            out["nba"][r["gid"]]["p"][r["pid"]] = [round(float(r["min"]))] + [int(float(r[b])) for b in models.NBA_BASE]
    for r in soc_logs:
        if r["date"] >= since and r["gid"] in out["soccer"]:
            out["soccer"][r["gid"]]["p"][r["pid"]] = [round(float(r["min"]))] + [int(float(r[b])) for b in models.SOC_BASE]
    for sp, logs in us_logs.items():
        base = props.SPORTS[sp]["base"]
        for r in logs:
            if r["date"] >= since and r["gid"] in out[sp]:
                out[sp][r["gid"]]["p"][r["pid"]] = [round(float(r["min"]), 1)] + [round(float(r[b]), 1) for b in base]
    for m in t_matches or []:
        if m["date"][:10] >= since and m.get("winner"):
            out["tennis"][m["gid"]] = {"w": m["winner"], "s": [m.get("sets1"), m.get("sets2")], "p": {}}
    # "b": 1 se il tabellino e' disponibile (giocatore assente = scommessa annullata)
    for sport in out:
        for g in out[sport].values():
            g["b"] = 1 if g.get("p") else 0
    return out


if __name__ == "__main__":
    sys.exit(main())
