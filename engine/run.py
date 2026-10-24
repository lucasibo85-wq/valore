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

from . import calib, espn, models, net, odds, props, secure, store, teamus, tennis

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
    now = dt.datetime.utcnow()
    if os.environ.get("VALORE_TODAY"):  # solo per i test
        today = dt.date.fromisoformat(os.environ["VALORE_TODAY"])
        now = dt.datetime.combine(today, dt.time(8, 0))
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
            # ESPN accetta gli intervalli di date? Verifica una volta per lega confrontando con le singole giornate
            rok = state.setdefault("range_ok", {})
            if league not in rok:
                a_ = {e["id"] for e in scan_days(path, today - dt.timedelta(days=10), today, per_day=False)}
                b_ = {e["id"] for e in scan_days(path, today - dt.timedelta(days=10), today, per_day=True)}
                rok[league] = b_ <= a_
                if not rok[league]:
                    log("Calcio %s: gli intervalli di date non funzionano, scansione giorno per giorno" % league)
                    start = min(start, today - dt.timedelta(days=cfg["soccer"]["backfill_days"])) if league not in state["scan"] else start
            evs = scan_days(path, start, today, per_day=not rok[league])
            n_new = 0
            for ev in evs:
                remember("soccer", league, ev)
                if ev["completed"] and ev["id"] not in processed["soccer"]:
                    queue.append(("soccer", path, league, ev))
                    n_new += 1
            cnt = state.setdefault("scan_counts", {}).setdefault(league, {})
            cnt.clear()
            for ev in scan_days(path, today, today + dt.timedelta(days=ahead), per_day=True):
                remember("soccer", league, ev)
                k_ = "%s_%s" % ("oggi" if ev["date"][:10] == iso(today) else "poi", ev["state"])
                cnt[k_] = cnt.get(k_, 0) + 1
                if not ev["completed"] and ev["state"] in ("pre", "in"):
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

    # ---------------- Dati di squadra (angoli, cartellini, 1° tempo) per partite gia' lette in passato
    refetch = 0
    soc_paths = {lg: "soccer/" + lg for lg in cfg["soccer"].get("leagues", {})} if cfg["soccer"].get("enabled") else {}
    rf_since = iso(today - dt.timedelta(days=365))
    for m in sorted(matches, key=lambda m: m["date"], reverse=True):
        if refetch >= int(cfg.get("max_team_refetch_per_run", 600)):
            break
        if (m.get("sport") == "soccer" and m.get("ts") in (None, "") and m["gid"] in processed["soccer"]
                and m["date"] >= rf_since and m.get("league") in soc_paths):
            queue.append(("soccer", soc_paths[m["league"]], m["league"],
                          {"id": m["gid"], "date": m["date"], "home": {"id": m["hid"]}, "away": {"id": m["aid"]}, "refetch": True}))
            refetch += 1
    if refetch:
        log("Calcio: %d partite gia' in archivio da completare con angoli/cartellini/1° tempo" % refetch)

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
            if not ev.get("refetch"):
                soc_logs.extend(rows)
            mrow_ = match_by_gid.get(ev["id"])
            if mrow_ is not None:
                ref = espn.parse_referee(summ)
                if ref:
                    mrow_["referee"] = ref
                tdat = espn.parse_soccer_team(summ)
                th, ta = tdat["teams"].get(h, {}), tdat["teams"].get(a, {})
                if h in tdat["ht"] and a in tdat["ht"]:
                    mrow_["hs1"], mrow_["as1"] = tdat["ht"][h], tdat["ht"][a]
                if "corners" in th and "corners" in ta:
                    mrow_["hc"], mrow_["ac"] = th["corners"], ta["corners"]
                if "yc" in th and "yc" in ta:
                    mrow_["hk"] = th["yc"] + th.get("rc", 0)
                    mrow_["ak"] = ta["yc"] + ta.get("rc", 0)
                elif rows:  # cartellini dalla somma dei giocatori
                    mrow_["hk"] = sum(r["yc"] + r["rc"] for r in rows if r["team"] == h)
                    mrow_["ak"] = sum(r["yc"] + r["rc"] for r in rows if r["team"] == a)
                mrow_["ts"] = 1
            if ev.get("refetch"):
                processed[sport].add(ev["id"])
                done += 1
                continue
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
    soon = (now + dt.timedelta(hours=40)).isoformat()
    for sport, path, league, ev in upcoming:
        if ev["date"][:19] <= soon or sport == "nfl":
            summ = espn.summary(path, ev["id"])
            if summ:
                previews[ev["id"]] = {
                    "inj": espn.parse_injuries(summ),
                    "lineup": espn.parse_lineup(summ) if sport == "soccer" else set(),
                    "ref": espn.parse_referee(summ) if sport == "soccer" else "",
                    "probables": (props.probables(summ) or ev.get("probables") or {}) if sport == "mlb" else {},
                    "pick": espn.parse_pickcenter(summ),
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
        props.build(sp, app, us_logs[sp], upcoming, previews, teams, today, hist, matches, calib_factors(state, sp))
    if cfg.get("tennis", {}).get("enabled"):
        app["tennis"] = {"matches": []}
        tennis.build(app, t_matches, t_up)
    if cfg["nba"].get("enabled"):
        build_nba(app, nba_logs, upcoming, previews, teams, today, odds_cache, hist, calib_factors(state, "nba"), matches)
    if cfg["soccer"].get("enabled"):
        build_soccer(app, soc_logs, matches, upcoming, previews, teams, today, odds_cache, hist,
                     calib_factors(state, "soccer"))
    results = build_results(nba_logs, soc_logs, matches, today, us_logs, t_matches)
    # autocalibrazione: prima misura le previsioni passate, poi salva quelle nuove
    ev_logs = {"nba": nba_logs, "soccer": soc_logs}
    ev_logs.update(us_logs)
    calib.evaluate(state, ev_logs, results, today)
    calib.record(state, app, now, {sp: calib_factors(state, sp) for sp in ("nba", "soccer", "nfl", "mlb")})
    diag = build_diag(cfg, app, nba_logs, soc_logs, matches, upcoming, state, today)
    diag["calib"] = calib.report(state, today)
    secure.write_outputs(OUT_DIR, {"app": app, "hist": hist, "results": results, "diag": diag})
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
AVAIL = (("out", 0.0), ("doubtful", 0.25), ("questionable", 0.5), ("day-to-day", 0.75), ("game time", 0.6), ("probable", 0.9))


def availability(status):
    s = (status or "").lower()
    for k, v in AVAIL:
        if s.startswith(k):
            return v
    return 1.0


def spread_home(odds, home_abbr, away_abbr):
    """Handicap della squadra di casa (negativo = favorita) dalle quote ESPN."""
    if not odds:
        return None
    det = str(odds.get("details") or "")
    parts = det.replace("+", " +").split()
    if len(parts) >= 2:
        try:
            v = float(parts[-1])
            ab = parts[0].upper()
            if ab == str(home_abbr).upper():
                return v
            if ab == str(away_abbr).upper():
                return -v
        except ValueError:
            pass
    sp = odds.get("spread")
    return float(sp) if sp not in (None, "") else None


def build_nba(app, logs, upcoming, previews, teams, today, odds_cache, hist, calib=None, matches=None):
    """Proiezioni NBA.

    1. Tasso per minuto pesato sulle partite recenti, corretto verso la media del ruolo.
    2. Minuti attesi; poi i minuti lasciati liberi dagli assenti (Out / dubbi) vengono ridistribuiti
       ai compagni, fino a 240 minuti di squadra.
    3. Fattori di contesto: difesa avversaria per statistica, casa/trasferta, back-to-back,
       rischio di partita a senso unico (handicap ampio).
    4. Coerenza con la squadra: la somma delle proiezioni deve tornare con i punti attesi della squadra
       (dalle quote ESPN se presenti, altrimenti dalla media), lo stesso per rimbalzi e assist.
    5. Autocalibrazione: correzione per mercato in base agli errori delle ultime settimane.
    """
    if not logs:
        return
    calib = calib or {}
    markets = models.NBA_MARKETS
    base = models.NBA_BASE
    since_long = iso(today - dt.timedelta(days=365))
    priors = models.league_priors("nba", logs, markets, since_long)
    since_opp = iso(today - dt.timedelta(days=150))
    if len(set(r["gid"] for r in logs if r["date"] >= since_opp)) < 300:
        since_opp = since_long
    opp_f, home_f = models.opponent_factors(logs, markets, since_opp, k=15)
    season_start = dt.date(today.year if today.month >= 10 else today.year - 1, 10, 1).isoformat()

    by_player = defaultdict(list)
    tg_set = defaultdict(dict)
    tot = defaultdict(lambda: defaultdict(float))  # (gid, team) -> somme statistiche
    for r in logs:
        by_player[r["pid"]].append(r)
        tg_set[r["team"]][r["gid"]] = r["date"]
        t_ = tot[(r["gid"], r["team"])]
        for b in base:
            t_[b] += float(r[b])
        t_["_opp"] = r["opp"]
        t_["_date"] = r["date"]
    team_games = {t: sorted(d.items(), key=lambda x: x[1]) for t, d in tg_set.items()}
    for pid in by_player:
        by_player[pid].sort(key=lambda r: r["date"], reverse=True)
    current = defaultdict(list)
    for pid, games in by_player.items():
        current[games[0]["team"]].append(pid)
    # medie di squadra (ultime 15): statistiche fatte e punti subiti
    team_avg = {}
    for t, gl in team_games.items():
        last = [g for g, _ in gl[-15:]]
        if not last:
            continue
        rows = [tot[(g, t)] for g in last]
        allowed = [tot.get((g, rows[i]["_opp"]), {}).get("pts", 0.0) for i, g in enumerate(last)]
        team_avg[t] = {b: sum(r_[b] for r_ in rows) / len(rows) for b in base}
        team_avg[t]["allowed"] = sum(allowed) / len(allowed) if allowed else team_avg[t]["pts"]
    lg_pts = sum(v["pts"] for v in team_avg.values()) / max(1, len(team_avg))
    nba_m = [m for m in (matches or []) if m.get("sport") == "nba"]
    tstr = models.team_strengths(nba_m, iso(today), half_life_days=60, prior_games=6) if nba_m else None

    tabbr = lambda tid: teams["nba"].get(tid, {}).get("abbr", "?")
    for sport, path, league, ev in upcoming:
        if sport != "nba":
            continue
        pv = previews.get(ev["id"], {})
        inj = pv.get("inj", {})
        odds_ev = ev.get("odds") or {}
        habbr, aabbr = tabbr(ev["home"]["id"]), tabbr(ev["away"]["id"])
        total = odds_ev.get("ou")
        hsp = spread_home(odds_ev, habbr, aabbr)
        game = {"id": ev["id"], "t": ev["date"], "h": habbr, "a": aabbr,
                "hn": ev["home"]["name"], "an": ev["away"]["name"], "odds": ev.get("odds"), "tot": total, "sp": hsp}
        if ev.get("state") == "in":
            game["live"] = 1
        eo = pick_keys("nba", pv.get("pick"))
        if eo:
            game["eo"] = eo
            game["eob"] = pv["pick"].get("book")
        hid_, aid_ = ev["home"]["id"], ev["away"]["id"]
        if tstr and hid_ in tstr["att"] and aid_ in tstr["att"]:
            mh = tstr["avg_h"] * tstr["att"][hid_] * tstr["def"][aid_]
            ma = tstr["avg_a"] * tstr["att"][aid_] * tstr["def"][hid_]
            game.update({"mh": round(mh, 1), "ma": round(ma, 1), "mk": teamus.normal_markets("nba", mh, ma, hsp, total)})
        app["nba"]["games"].append(game)
        props = {}
        for row in odds_cache.get("nba", {}).get(ev["id"], []):
            props.setdefault(name_key(row[0]), {})[row[1]] = row[2:]
        for side, opp_side in (("home", "away"), ("away", "home")):
            tid, oid = ev[side]["id"], ev[opp_side]["id"]
            tg = team_games.get(tid, [])
            this_season = [g for g, d in tg if d >= season_start]
            # back-to-back: la squadra ha giocato nelle ultime ~30 ore
            ev_dt = dt.datetime.fromisoformat(ev["date"][:16].replace("Z", ""))
            b2b = bool(tg) and (ev_dt.date() - dt.date.fromisoformat(tg[-1][1])).days <= 1 and tg[-1][1] < ev["date"][:10]
            spread = None if hsp is None else (hsp if side == "home" else -hsp)
            cands = []
            missing = []  # giocatori di rotazione assenti
            for pid in current.get(tid, []):
                games = by_player[pid]
                if this_season and len(this_season) >= 2 and games[0]["date"] < season_start:
                    continue
                if games[0]["date"] < iso(today - dt.timedelta(days=200)):
                    continue
                status = inj.get(pid, "")
                last10 = games[:10]
                ws = models.decay_weights(len(last10), 4)
                mins = [float(r["min"]) for r in last10]
                exp_min = models.wmean(mins, ws)
                after = [g for g, d in tg if d > games[0]["date"]]
                av = availability(status)
                if av == 0.0 or len(after) >= 4:
                    if exp_min >= 12:
                        missing.append((games[0]["name"], exp_min, sum(float(r["pts"]) for r in last10) / len(last10)))
                    continue
                if exp_min < 8:
                    continue
                cands.append({"pid": pid, "games": games, "status": status, "av": av, "exp": exp_min,
                              "mins": mins, "ws": ws, "after": after})
            if not cands:
                continue
            # --- ridistribuzione dei minuti verso 240
            tot_min = sum(c["exp"] * c["av"] for c in cands)
            notes_team = []
            if tot_min < 236:
                free = 240 - tot_min
                room = {c["pid"]: max(0.0, 40 - c["exp"]) * (1 if c["exp"] >= 15 else 0.5) for c in cands}
                rs = sum(room.values()) or 1.0
                for c in cands:
                    c["add"] = min(room[c["pid"]], free * room[c["pid"]] / rs)
            elif tot_min > 250:
                k_ = 245 / tot_min
                for c in cands:
                    c["add"] = c["exp"] * (k_ - 1)
            for c in cands:
                c["exp2"] = max(4.0, c["exp"] + c.get("add", 0.0))
                if b2b and c["exp2"] >= 28:
                    c["exp2"] *= 0.97
                if spread is not None and abs(spread) >= 10:
                    c["exp2"] *= 0.96 if c["exp2"] >= 28 else 1.04
            if missing:
                notes_team.append("Assenti: " + ", ".join("%s (%.0f min)" % (n, m_) for n, m_, _ in sorted(missing, key=lambda x: -x[1])[:4]))
            if b2b:
                notes_team.append("Back-to-back (ha giocato ieri)")
            if spread is not None and abs(spread) >= 10:
                notes_team.append("Handicap %+.1f: rischio partita a senso unico, titolari un po' meno minuti" % spread)
            # --- proiezioni individuali
            for c in cands:
                fac = {}
                for m in markets:
                    fac[m] = opp_f.get(oid, {}).get(m, 1.0) * (home_f.get(m, 1.0) if side == "home" else (2 - home_f.get(m, 1.0)))
                var_min = min(36.0, models.wmean([(m_ - c["exp"]) ** 2 for m_ in c["mins"]], c["ws"]))
                c["proj"] = models.project(c["games"], "nba", markets, priors, c["exp2"], var_min, fac, 12, 60)
            # --- coerenza con i totali di squadra
            ta = team_avg.get(tid)
            k_base = {}
            if ta:
                exp_pts_team = ta["pts"] * opp_f.get(oid, {}).get("pts", 1.0)
                if total and hsp is not None:
                    implied = total / 2 - (hsp / 2 if side == "home" else -hsp / 2)
                    exp_pts_team = 0.35 * exp_pts_team + 0.65 * implied
                    pace = total / max(150.0, ta["pts"] + ta["allowed"]) if ta.get("allowed") else 1.0
                    notes_team.append("Punti attesi squadra %.0f (quote ESPN: totale %.1f, handicap %+.1f)" % (implied, total, spread or 0))
                else:
                    pace = 1.0
                targets = {"pts": exp_pts_team,
                           "reb": ta["reb"] * opp_f.get(oid, {}).get("reb", 1.0) * (pace ** 0.4),
                           "ast": ta["ast"] * opp_f.get(oid, {}).get("ast", 1.0) * (pace ** 0.6),
                           "fg3m": ta["fg3m"] * opp_f.get(oid, {}).get("fg3m", 1.0) * (pace ** 0.6)}
                for b, tgt in targets.items():
                    ssum = sum(c["proj"][b][0] * c["av"] for c in cands)
                    # la rotazione proiettata copre ~ il 97% della produzione di squadra
                    if ssum > 0:
                        k_base[b] = max(0.88, min(1.12, 1 + 0.6 * ((tgt * 0.97) / ssum - 1)))
            for c in cands:
                games = c["games"]
                proj = {}
                for m, comps in markets.items():
                    mu, r = c["proj"][m]
                    ks = [(k_base.get(b, 1.0), c["proj"][b][0]) for b in comps if b in c["proj"]]
                    wsum = sum(w for _, w in ks)
                    k = sum(kk * w for kk, w in ks) / wsum if wsum > 0 else 1.0
                    k *= calib.get(m, 1.0)
                    proj[m] = [round(mu * k, 3), r]
                status = c["status"]
                if c["after"] and not status:
                    status = "Assente ultime %d" % len(c["after"])
                mins = c["mins"]
                mmean = sum(mins) / len(mins)
                cv = (sum((x - mmean) ** 2 for x in mins) / len(mins)) ** 0.5 / mmean if mmean else 1
                rel = "A" if len(games) >= 20 and cv < 0.18 and not status else ("B" if len(games) >= 10 and cv < 0.3 else "C")
                adj = list(notes_team)
                if abs(c["exp2"] - c["exp"]) >= 1.0:
                    adj.insert(0, "Minuti %+.1f rispetto alla media recente" % (c["exp2"] - c["exp"]))
                p = {
                    "id": c["pid"], "n": games[0]["name"], "t": tabbr(tid), "o": tabbr(oid), "g": ev["id"],
                    "h": 1 if side == "home" else 0, "pos": games[0].get("pos", ""), "st": status,
                    "m": round(c["exp2"], 1), "m0": round(c["exp"], 1), "rel": rel, "cv": round(cv, 2),
                    "adj": adj, "mk": proj,
                    "of": {m: round(opp_f.get(oid, {}).get(m, 1.0), 3) for m in markets},
                    "a30": {m: round(sum(models.market_value(r, cc, m) for r in games[:30]) / len(games[:30]), 2)
                            for m, cc in markets.items()},
                    "l": [[r["date"], tabbr(r["opp"]), round(float(r["min"]))] + [int(float(r[b])) for b in base]
                          for r in games[:10]],
                }
                od = props.get(name_key(p["n"]))
                if od:
                    p["odds"] = od
                app["nba"]["players"].append(p)
                hist["nba"][c["pid"]] = [[r["date"], tabbr(r["opp"]), round(float(r["min"]))] + [int(float(r[b])) for b in base]
                                         for r in games[:100]]


# ====================================================================== Calcio
def pick_keys(sport, pk):
    """Trasforma le quote ESPN (pickcenter) nelle chiavi dei mercati di squadra."""
    if not pk:
        return {}
    out = {}
    if sport == "soccer":
        for k, v in (("1", pk.get("h")), ("X", pk.get("d")), ("2", pk.get("a"))):
            if v:
                out[k] = v
        if pk.get("ou") is not None:
            code = "%02d" % int(round(float(pk["ou"]) * 10))
            if pk.get("over"):
                out["o" + code] = pk["over"]
            if pk.get("under"):
                out["u" + code] = pk["under"]
        sp = pk.get("spread")
        if sp is not None and abs(abs(float(sp)) - 0.5) < 1e-6:
            # handicap asiatico +/-0.5 = doppia chance / vittoria secca
            if float(sp) > 0:
                if pk.get("hs"):
                    out["1X"] = pk["hs"]
            else:
                if pk.get("as"):
                    out["X2"] = pk["as"]
        return out
    if pk.get("h"):
        out["ml1"] = pk["h"]
    if pk.get("a"):
        out["ml2"] = pk["a"]
    if pk.get("ou") is not None:
        if pk.get("over"):
            out["o:%g" % float(pk["ou"])] = pk["over"]
        if pk.get("under"):
            out["u:%g" % float(pk["ou"])] = pk["under"]
    if pk.get("spread") is not None:
        L = float(pk["spread"])
        if pk.get("hs"):
            out["hsp:%g" % L] = pk["hs"]
        if pk.get("as"):
            out["asp:%g" % (-L)] = pk["as"]
    return out


def calib_factors(state, sport):
    return calib.factors(state, sport)


def build_diag(cfg, app, nba_logs, soc_logs, matches, upcoming, state, today):
    """Copertura dei dati per la pagina Stato dati dell'app."""
    gids_pl = set(r["gid"] for r in soc_logs)
    since = iso(today - dt.timedelta(days=60))
    lg = {}
    for code, name in cfg["soccer"].get("leagues", {}).items():
        ms = [m for m in matches if m.get("sport") == "soccer" and m.get("league") == code]
        rec = [m for m in ms if m["date"] >= since]
        up = [m for m in app.get("soccer", {}).get("matches", []) if m["lg"] == code]
        pl = [p for p in app.get("soccer", {}).get("players", []) if p.get("lg") == code]
        lg[code] = {"name": name, "partite": len(ms), "recenti": len(rec),
                    "con_giocatori": sum(1 for m in rec if m["gid"] in gids_pl),
                    "con_angoli": sum(1 for m in rec if m.get("hc") not in (None, "")),
                    "con_1t": sum(1 for m in rec if m.get("hs1") not in (None, "")),
                    "prossime": len(up), "con_modello": sum(1 for m in up if m.get("p1") is not None),
                    "giocatori": len(pl), "intervalli_ok": state.get("range_ok", {}).get(code),
                    "espn": state.get("scan_counts", {}).get(code, {})}
    nb = {"partite": len(set(r["gid"] for r in nba_logs)), "recenti": len(set(r["gid"] for r in nba_logs if r["date"] >= since)),
          "prossime": len(app.get("nba", {}).get("games", [])), "giocatori": len(app.get("nba", {}).get("players", [])),
          "con_quote_espn": sum(1 for g in app.get("nba", {}).get("games", []) if g.get("tot"))}
    return {"generated": app["generated"], "soccer": lg, "nba": nb, "queue": len(state.get("queue", []))}


def build_soccer(app, logs, matches, upcoming, previews, teams, today, odds_cache, hist, calib_f=None):
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
    soc_all = [m for m in matches if m.get("sport") == "soccer"]
    T = iso(today)
    # coppe europee (e in generale competizioni con squadre di leghe diverse): modello unico su tutte le partite
    joint = {"g": models.team_strengths(soc_all, T), "c": models.team_strengths(soc_all, T, hf="hc", af="ac", prior_games=6, min_rows=40),
             "k": models.team_strengths(soc_all, T, hf="hk", af="ak", prior_games=6, min_rows=40),
             "f1": models.first_half_share(soc_all), "rc": models.league_dispersion(soc_all, "hc", "ac"),
             "rk": models.league_dispersion(soc_all, "hk", "ak")}
    lg_models = {}
    for lg, ms in by_league.items():
        strengths[lg] = models.team_strengths(ms, T)
        lg_models[lg] = {"g": strengths[lg], "c": models.team_strengths(ms, T, hf="hc", af="ac", prior_games=6, min_rows=40),
                         "k": models.team_strengths(ms, T, hf="hk", af="ak", prior_games=6, min_rows=40),
                         "f1": models.first_half_share(ms, joint["f1"]),
                         "rc": models.league_dispersion(ms, "hc", "ac") or joint["rc"],
                         "rk": models.league_dispersion(ms, "hk", "ak") or joint["rk"]}
    is_cup = lambda lg: lg.startswith("uefa.") or "cup" in lg or "coppa" in lg or lg.endswith("_qual")
    # gol medi segnati da ogni squadra nelle ultime 10 partite (tutte le competizioni)
    goals_hist = defaultdict(list)
    for m in sorted(soc_all, key=lambda m: m["date"]):
        if m.get("hs") not in (None, "") and m.get("as") not in (None, ""):
            goals_hist[m["hid"]].append(float(m["hs"]))
            goals_hist[m["aid"]].append(float(m["as"]))
    goals_avg = {t: (sum(v[-10:]) + 1.35 * 3) / (len(v[-10:]) + 3) for t, v in goals_hist.items()}

    def pair(sm, h, a):
        if sm and h in sm["att"] and a in sm["att"]:
            return sm["avg_h"] * sm["att"][h] * sm["def"][a], sm["avg_a"] * sm["att"][a] * sm["def"][h]
        return None

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
        if ev.get("state") == "in":
            mrow["live"] = 1
        LM = joint if is_cup(league) or league not in lg_models else lg_models[league]
        gl = pair(LM["g"], h, a) or pair(joint["g"], h, a)
        exp_goals = {}
        if gl:
            lh, la = gl
            exp_goals = {h: lh, a: la}
            mrow.update({"lh": round(lh, 3), "la": round(la, 3)})
            mrow.update(models.match_probs(lh, la))
            cpair = pair(LM["c"], h, a) or pair(joint["c"], h, a)
            kpair = pair(LM["k"], h, a) or pair(joint["k"], h, a)
            corners = (sum(cpair), LM["rc"]) if cpair else None
            cards = None
            if kpair:
                kf = ref_f[ref]["card"] if ref and ref in ref_f else 1.0
                cards = (sum(kpair) * kf, LM["rk"])
                mrow["mk_k"] = round(cards[0], 2)
            if corners:
                mrow["mk_c"] = round(corners[0], 2)
            mrow["f1"] = round(LM["f1"], 3)
            mrow["mk"] = models.soccer_markets(lh, la, LM["f1"], corners, cards)
        oc = odds_cache.get("soccer", {}).get(ev["id"])
        eo = ev.get("odds")
        if oc:
            mrow["odds"] = oc
        elif eo and eo.get("d"):  # quote gratuite pubblicate da ESPN
            mrow["odds"] = [eo["h"], eo["d"], eo["a"], eo["book"]]
        if ref:
            mrow["ref"] = ref
        eo = pick_keys("soccer", pv.get("pick"))
        if eo:
            mrow["eo"] = eo
            mrow["eob"] = pv["pick"].get("book")
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
                if p_start < 0.15 and sum(apps) < 2:
                    continue
                st_games = [r for r in games[:10] if r["starter"]]
                if p_start >= 0.5 and st_games:
                    exp_min = sum(float(r["min"]) for r in st_games) / len(st_games)
                else:
                    exp_min = sum(float(r["min"]) for r in games[:10]) / len(games[:10])
                cands.append((p_start, pid, exp_min))
            cands.sort(reverse=True)
            for p_start, pid, exp_min in cands[:22]:
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
                for m_, f_ in (calib_f or {}).items():
                    if m_ in proj:
                        proj[m_] = (round(proj[m_][0] * f_, 4), proj[m_][1])
                # coerenza con i gol attesi della squadra in questa partita (modello di squadra)
                if tid in exp_goals and goals_avg.get(tid):
                    kg = max(0.7, min(1.45, exp_goals[tid] / goals_avg[tid]))
                    for m_, ex in (("g", 1.0), ("a", 1.0), ("ga", 1.0), ("goa", 0.9), ("shots", 0.5), ("sot", 0.6)):
                        if m_ in proj:
                            proj[m_] = (round(proj[m_][0] * kg ** ex, 4), proj[m_][1])
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
            sc = [m["hs"], m["as"]]
            if m["sport"] == "soccer":
                sc += [m.get(k) if m.get(k) not in (None, "") else None for k in ("hs1", "as1", "hc", "ac", "hk", "ak")]
            out[m["sport"]].setdefault(m["gid"], {"s": sc, "p": {}})
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
