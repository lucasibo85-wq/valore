"""Aggiornamento completo: scarica i dati, calcola le proiezioni, scrive docs/data/.

Uso:  python -m engine.run            (aggiornamento normale)
      python -m engine.run --no-odds  (senza quote automatiche)
"""
import argparse
import datetime as dt
import json
import math
import os
import sys
import time
from collections import defaultdict

from . import calib, espn, models, net, odds, propline, props, secure, store, teamus, tennis

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
    US = [sp for sp in ("nfl", "mlb", "nhl") if cfg.get(sp, {}).get("enabled")]
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
        deep = state.get("nba_deep") != 3  # una volta sola: storico di 3 stagioni (H2H piu' lunghi)
        if purge or deep or key not in state["scan"]:
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
        state["nba_deep"] = 3
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

    # ---------------- NFL, MLB e NHL (solo stagione regolare e playoff)
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

    # ---------------- 1° quarto (punti, rimbalzi, assist) per le partite NBA gia' in archivio
    if cfg["nba"].get("enabled") and nba_logs:
        q1_since = iso(today - dt.timedelta(days=int(cfg["nba"].get("q1_days", 400))))
        tried = set(state.get("q1_tried", []))
        by_gid = defaultdict(list)
        for r in nba_logs:
            if "q1p" not in r and r["date"] >= q1_since and r["gid"] not in tried:
                by_gid[r["gid"]].append(r)
        todo = sorted(by_gid, key=lambda g: by_gid[g][0]["date"], reverse=True)[:int(cfg["nba"].get("q1_per_run", 150))]
        ok_q1 = 0
        for gid in todo:
            summ = espn.summary("basketball/nba", gid)
            if summ is None:
                continue
            q1 = espn.parse_nba_q1(summ)
            if q1 is None:
                tried.add(gid)  # cronaca mancante o incompleta: non si riprova
                continue
            for r in by_gid[gid]:
                r.update(q1.get(r["pid"], {"q1p": 0, "q1r": 0, "q1a": 0}))
            ok_q1 += 1
        state["q1_tried"] = sorted(tried)[-3000:]
        if todo:
            log("NBA 1° quarto: %d partite completate su %d (ne restano %d)" % (ok_q1, len(todo), max(0, len(by_gid) - len(todo))))

    # ---------------- Pulizia storico
    cutoff = iso(today - dt.timedelta(days=int(cfg.get("history_days", 420))))
    cutoff_nba = iso(today - dt.timedelta(days=int(cfg["nba"].get("history_days", cfg.get("history_days", 420)))))
    nba_logs = [r for r in nba_logs if r["date"] >= cutoff_nba]
    soc_logs = [r for r in soc_logs if r["date"] >= cutoff]
    for sp in US:
        us_logs[sp] = [r for r in us_logs[sp] if r["date"] >= cutoff]
    t_matches = [m for m in t_matches if m["date"][:10] >= cutoff]
    matches = [m for m in matches if m["date"] >= (cutoff_nba if m.get("sport") == "nba" else cutoff)]
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
                    "h2h": espn.parse_h2h(summ) if sport == "soccer" else [],
                }

    # ---------------- Precedenti degli anni passati (calcio): calendari ESPN delle squadre, salvati una volta sola
    if cfg["soccer"].get("enabled"):
        hc = store.read_json("h2h_cache.json", {})
        budget = int(cfg["soccer"].get("h2h_requests_per_run", 150))
        n_seasons = int(cfg["soccer"].get("h2h_seasons", 5))
        cur = today.year if today.month >= 7 else today.year - 1
        soc_up = sorted([u for u in upcoming if u[0] == "soccer"], key=lambda u: u[3]["date"])
        for sport, path, league, ev in soc_up:
            hid, aid = ev["home"]["id"], ev["away"]["id"]
            rows = []
            for tid in (hid, aid):
                for y in range(cur, cur - n_seasons - 1, -1):
                    key = "%s|%s|%d" % (path, tid, y)
                    # stagioni passate: per sempre; stagione in corso: la copre gia' l'archivio
                    if key not in hc and y < cur and budget > 0:
                        sched = espn.team_schedule(path, tid, y)
                        budget -= 1
                        if sched is not None:
                            hc[key] = sched
                    rows += hc.get(key, [])
            ex = [{"date": r[0], "hid": r[1], "aid": r[2], "hs": r[3], "as": r[4], "comp": league}
                  for r in rows if {r[1], r[2]} == {hid, aid}]
            if ex:
                pv = previews.setdefault(ev["id"], {})
                pv["h2h"] = (pv.get("h2h") or []) + ex
        store.write_json("h2h_cache.json", hc, compact=True)
        log("Precedenti: %d calendari di squadra in archivio" % len(hc))

    # ---------------- Quote automatiche
    odds_cache = state.get("odds_cache", {})
    if not args.no_odds and cfg.get("odds", {}).get("enabled") and (odds.key() or propline.key()):
        odds_cache = fetch_odds(cfg, state, today, upcoming, teams, odds_cache)
        state["odds_cache"] = odds_cache
    else:
        log("Quote automatiche: nessuna chiave (ODDS_API_KEY / PROPLINE_API_KEY), salto (inserimento manuale nell'app).")

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
        # quote automatiche delle prop (PropLine), se ci sono
        by_g = {}
        for gid, rows_ in (odds_cache.get(sp) or {}).items():
            for row in rows_:
                by_g.setdefault(gid, {}).setdefault(name_key(row[0]), {})[row[1]] = row[2:]
        for p_ in app[sp]["players"]:
            od = by_g.get(p_["g"], {}).get(name_key(p_["n"]))
            if od:
                p_["odds"] = od
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
    calib.record(state, app, now, {sp: calib_factors(state, sp) for sp in ("nba", "soccer", "nfl", "mlb", "nhl")})
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
def q1_cols(r):
    """Punti, rimbalzi, assist del 1° quarto in coda alla riga (vuoto se il dato manca)."""
    return [int(r["q1p"]), int(r["q1r"]), int(r["q1a"])] if "q1p" in r else []


Q1_MAP = {"q1p": "pts", "q1r": "reb", "q1a": "ast"}


def pos_group(pos):
    """Ruolo NBA in tre gruppi: G (playmaker/guardie), F (ali), C (centri)."""
    p = str(pos or "").upper()
    if not p:
        return ""
    if p.startswith("C"):
        return "C"
    if p.startswith("G") or p in ("PG", "SG"):
        return "G"
    return "F"


def _match_event(events, hn, an, thr=0.34):
    best, score = None, 0.0
    for o in events:
        sh, sa = odds.similar(hn, o.get("home_team", o.get("home", ""))), odds.similar(an, o.get("away_team", o.get("away", "")))
        if sh >= thr and sa >= thr and sh + sa > score:
            best, score = o, sh + sa
    return best


def fetch_odds(cfg, state, today, upcoming, teams, cache):
    """Scarica le quote rispettando il budget giornaliero di crediti di The Odds API.

    NBA (prop giocatori): ogni partita si scarica quando mancano al massimo 14 ore all'inizio, perche' i
    bookmaker pubblicano le prop il giorno della partita. Se la prima volta non c'erano ancora quote,
    si riprova dopo 3 ore; se c'erano, si aggiornano dopo 10 ore. 1 credito per mercato a partita.
    Calcio (1X2): una volta ogni refresh_hours, con i crediti che avanzano.
    """
    oc = cfg["odds"]
    budget = int(oc.get("daily_credit_budget", 15))
    refresh_h = float(oc.get("refresh_hours", 24))
    st = state.get("odds_usage", {})
    now = dt.datetime.utcnow()
    if st.get("date") != iso(today):
        st = {"date": iso(today), "used": 0, "last": st.get("last", ""), "remaining": st.get("remaining")}
    evst = state.setdefault("odds_events", {})
    up_ids = {e["id"] for s_, p_, l_, e in upcoming}
    for gid in [g for g in evst if g not in up_ids]:
        del evst[gid]
    # si parte dalle quote gia' salvate delle partite ancora da giocare
    new = {k: {gid: v for gid, v in (cache.get(k) or {}).items() if gid in up_ids} for k in ("soccer", "nba", "soccer_props", "nfl", "mlb", "nhl")}

    def remember_rem(rem):
        if rem is not None:
            st["remaining"] = rem

    # ---- NBA prop giocatori
    markets = oc.get("nba_prop_markets", ["player_points"])
    nreg = oc.get("nba_regions", "us")
    cost = len(markets) * len(nreg.split(","))

    def hours_to(ev):
        try:
            return (dt.datetime.fromisoformat(ev["date"][:16].replace("Z", "")) - now).total_seconds() / 3600
        except ValueError:
            return 99

    def due(ev):
        h = hours_to(ev)
        if h > 14 or h < -0.25:
            return False
        rec = evst.get(ev["id"])
        if not rec:
            return True
        age = (now - dt.datetime.fromisoformat(rec["t"])).total_seconds() / 3600
        return age >= (3 if rec.get("n", 0) == 0 else 10)

    if propline.key():
        # PropLine (gratis, 1.000 richieste al giorno): tutti i mercati giocatore di NBA, NFL, MLB e calcio,
        # anche dei bookmaker italiani. Si scarica solo quando ci sono partite in programma (quindi solo in
        # stagione): ogni partita da 48 ore prima dell'inizio (i bookmaker come bet365 pubblicano presto),
        # aggiornata ogni 8 ore se manca piu' di un giorno, ogni 4 ore se mancano 14-24 ore, ogni 2 ore nelle
        # ultime 14. Massimo 200 richieste per giro e 950 al giorno (il limite gratuito e' 1.000).
        pst = state.setdefault("propline_events", {})
        if state.get("propline_ver") != 3:
            # versione corretta della lettura delle linee: via le quote scaricate prima, si riscarica tutto
            pst.clear()
            for k_ in ("nba", "nfl", "mlb", "nhl", "soccer_props"):
                new[k_] = {}
            state["propline_ver"] = 3
        for gid in [g for g in pst if g not in up_ids]:  # partite finite
            del pst[gid]

        def pl_due(e):
            h = hours_to(e)
            if not (-0.25 <= h <= 48):
                return False
            rec = pst.get(e["id"])
            if not rec:
                return True
            every = 2 if h <= 14 else 4 if h <= 24 else 8
            if not rec.get("n"):
                every = min(every, 3)  # niente linee la volta scorsa: si riprova prima
            return (now - dt.datetime.fromisoformat(rec["t"])).total_seconds() >= every * 3600

        evcache = state.setdefault("propline_evcache", {})

        def pl_events(skey, refresh=False):
            # elenco partite di PropLine, tenuto 4 ore (ogni elenco costa una richiesta)
            c = evcache.get(skey)
            if not refresh and c and (now - dt.datetime.fromisoformat(c["t"])).total_seconds() < 4 * 3600:
                return c["ev"]
            evs_ = propline.events(skey) or []
            evcache[skey] = {"t": now.replace(microsecond=0).isoformat(),
                             "ev": [{k: x.get(k) for k in ("id", "home_team", "away_team", "commence_time")} for x in evs_]}
            return evcache[skey]["ev"]

        def pl_cap():
            u = propline.STATS.get("used_today")
            return u is not None and u >= 950
        budget_pl = 200
        groups = []  # (cache key, sport key PropLine, eventi, mercati, riserva, mappa, squadre)
        for sp in ("nba", "nfl", "mlb", "nhl"):
            ev_due = [e for s_, p_, l_, e in upcoming if s_ == sp and pl_due(e)]
            if ev_due:
                skey, mk, core, mp = propline.SPORTS[sp]
                groups.append((sp, skey, ev_due, mk, core, mp, teams.get(sp, {})))
        soc_due = defaultdict(list)
        for s_, p_, l_, e in upcoming:
            if s_ == "soccer" and l_ in odds.SOCCER_KEYS and pl_due(e):
                soc_due[l_].append(e)
        if soc_due:
            avail = set(state.get("propline_sports", {}).get("keys") or [])
            if not avail or state.get("propline_sports", {}).get("date") != iso(today):
                avail = set(propline.sports())
                state["propline_sports"] = {"date": iso(today), "keys": sorted(avail)}
            for lg, evs_ in soc_due.items():
                sk = odds.SOCCER_KEYS[lg]
                if avail and sk not in avail:
                    continue
                mk, core, mp = propline.SOCCER
                groups.append(("soccer_props", sk, evs_, mk, core, mp, teams.get("soccer", {})))
        for ck, skey, ev_due, mk, core, mp, tnames in groups:
            if budget_pl <= 0 or pl_cap():
                break
            pevs = pl_events(skey)
            fresh_ev = False
            for ev in sorted(ev_due, key=lambda e: e["date"]):
                if budget_pl <= 0 or pl_cap():
                    break
                hn = tnames.get(ev["home"]["id"], {}).get("name", "") or ev["home"].get("name", "")
                an = tnames.get(ev["away"]["id"], {}).get("name", "") or ev["away"].get("name", "")
                thr = 0.5 if ck != "soccer_props" else 0.34
                match = _match_event(pevs, hn, an, thr) if pevs else None
                if not match and not fresh_ev:
                    pevs, fresh_ev = pl_events(skey, True), True  # partita nuova: elenco aggiornato
                    match = _match_event(pevs, hn, an, thr) if pevs else None
                if not match:
                    continue
                rows = propline.event_props(match["id"], skey, mk, core, mp)
                budget_pl -= 1
                pst[ev["id"]] = {"t": now.replace(microsecond=0).isoformat(), "n": len(rows)}
                if rows:
                    new.setdefault(ck, {})[ev["id"]] = [[r["player"], r["m"], r["line"], r["over"], r["under"], r["book"], r.get("fair"), r.get("nb", 0)] for r in rows]
                log("PropLine %s %s – %s: %d linee" % (ck, an, hn, len(rows)))
        st["propline_used"] = propline.STATS.get("used_today")
        if propline.STATS.get("sample") is not None:
            # campione piccolo in un file a parte dell'archivio, per controllare il formato delle risposte
            first = next(iter(new.get("nba", {}).items()), (None, []))
            store.write_json("propline_debug.json", {"t": now.replace(microsecond=0).isoformat(), "sample": propline.STATS["sample"],
                                                     "nba_game": first[0], "nba_rows": first[1][:40]})
    nba_due = sorted([e for s_, p_, l_, e in upcoming if s_ == "nba" and due(e) and not propline.key()], key=lambda e: e["date"])
    if odds.key() and markets and nba_due and st["used"] + cost <= budget:
        evs = odds.nba_events()
        for ev in nba_due:
            if st["used"] + cost > budget:
                break
            hn = teams["nba"].get(ev["home"]["id"], {}).get("name", "")
            an = teams["nba"].get(ev["away"]["id"], {}).get("name", "")
            match = _match_event(evs, hn, an, 0.5)
            if not match:
                continue
            odds.LAST["cost"] = None
            rows, rem = odds.nba_props(match["id"], markets, nreg)
            st["used"] += odds.LAST["cost"] if odds.LAST.get("cost") is not None else cost
            remember_rem(rem)
            evst[ev["id"]] = {"t": now.replace(microsecond=0).isoformat(), "n": len(rows)}
            if rows:
                new["nba"][ev["id"]] = [[r["player"], r["m"], r["line"], r["over"], r["under"], r["book"], r.get("fair"), r.get("nb", 0)] for r in rows]
            log("Quote NBA %s – %s: %d linee" % (an, hn, len(rows)))

    # ---- calcio 1X2 (con i crediti che avanzano, una volta ogni refresh_hours): solo i campionati
    # che The Odds API copre, prima quelli principali
    last = st.get("last") or ""
    fresh = last and (now - dt.datetime.fromisoformat(last)).total_seconds() < refresh_h * 3600
    region = oc.get("regions", "eu")
    cost_region = len(region.split(","))
    by_league = defaultdict(list)
    for s_, p_, l_, e_ in upcoming:
        if s_ == "soccer":
            by_league[l_].append(e_)
    if odds.key() and oc.get("soccer_h2h", True) and not fresh:
        prio = ["ita.1", "uefa.champions", "uefa.europa", "uefa.europa.conf", "eng.1", "esp.1", "ger.1", "fra.1", "ita.2"]
        lgs = [lg for lg in by_league if lg in odds.SOCCER_KEYS]
        lgs.sort(key=lambda lg: (prio.index(lg) if lg in prio else len(prio), lg))
        done = 0
        for lg in lgs:
            if st["used"] + cost_region > budget:
                break
            odds.LAST["cost"] = None
            rows, rem = odds.soccer_h2h(lg, region)
            st["used"] += odds.LAST["cost"] if odds.LAST.get("cost") is not None else cost_region
            remember_rem(rem)
            done += 1
            for ev in by_league[lg]:
                hn = teams["soccer"].get(ev["home"]["id"], {}).get("name", "")
                an = teams["soccer"].get(ev["away"]["id"], {}).get("name", "")
                best = _match_event(rows, hn, an)
                if best:
                    new["soccer"][ev["id"]] = [best["o1"], best["ox"], best["o2"], best["book"], best.get("f1"), best.get("fx"), best.get("f2"),
                                              best["b1"], best["bx"], best["b2"], best["ref"], best["nb"]]
        if done:
            st["last"] = now.replace(microsecond=0).isoformat()

    # ---- calcio prop giocatori (facoltative, consumano molti crediti)
    smarkets = oc.get("soccer_prop_markets", [])
    sreg = oc.get("soccer_prop_regions", "us")
    cost = len(smarkets) * len(sreg.split(","))
    if odds.key() and smarkets and not fresh:
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
                odds.LAST["cost"] = None
                rows, rem = odds.event_props(sk, match["id"], smarkets, sreg, odds.SOCCER_PROP_MAP)
                st["used"] += odds.LAST["cost"] if odds.LAST.get("cost") is not None else cost
                remember_rem(rem)
                new["soccer_props"][ev["id"]] = [[r["player"], r["m"], r["line"], r["over"], r["under"], r["book"], r.get("fair"), r.get("nb", 0)] for r in rows]
    log("Quote: %d crediti usati oggi su %d%s" % (st["used"], budget,
        "" if st.get("remaining") is None else ", %d rimasti nel mese" % st["remaining"]))
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
    # quanto concede ogni difesa per mercato (1 = media): serve alla classifica DvP nell'app
    # solo le 30 squadre vere (con almeno 10 partite nell'archivio): fuori All-Star e squadre di esibizione
    real_t = [t for t in opp_f if tabbr(t) != "?" and len(team_games.get(t, [])) >= 10]
    app["nba"]["dvp"] = {m: {tabbr(t): round(opp_f[t].get(m, 1.0), 3) for t in real_t} for m in markets}
    # storico della difesa per ruolo: cosa ha concesso ogni squadra a guardie, ali e centri nelle ultime 10 partite
    # [data, avversario, in casa, {G: [statistiche base], F: [...], C: [...]}] + media lega per partita per ruolo
    agg = defaultdict(lambda: defaultdict(lambda: [0.0] * len(base)))
    meta_d = {}
    who = defaultdict(lambda: defaultdict(list))
    for r in logs:
        if r["date"] < since_opp:
            continue
        pg = pos_group(r.get("pos", ""))
        if not pg:
            continue
        key = (r["opp"], r["gid"])
        meta_d[key] = (r["date"], r["team"], 1 - int(float(r.get("home") or 0)))
        v = agg[key][pg]
        for i, b_ in enumerate(base):
            v[i] += float(r[b_])
        if float(r.get("min") or 0) >= 8:
            # chi ha giocato in quel ruolo: cognome, minuti, titolare, statistiche
            who[key][pg].append([str(r.get("name", "?")).split(" ")[-1], round(float(r["min"])), int(float(r.get("starter") or 0))] + [int(float(r[b_])) for b_ in base])
    lg_sum = defaultdict(lambda: [0.0] * len(base))
    for key, d in agg.items():
        for pg, v in d.items():
            for i in range(len(base)):
                lg_sum[pg][i] += v[i]
    n_tg = max(1, len(agg))
    app["nba"]["dvpavg"] = {pg: [round(x / n_tg, 2) for x in v] for pg, v in lg_sum.items()}
    by_def = defaultdict(list)
    for (d_tid, gid), d in agg.items():
        by_def[d_tid].append((meta_d[(d_tid, gid)], d, gid))
    app["nba"]["dvph"] = {}
    for d_tid in real_t:
        rows_ = sorted(by_def.get(d_tid, []), key=lambda x: x[0][0], reverse=True)[:10]
        app["nba"]["dvph"][tabbr(d_tid)] = [[m_[0], tabbr(m_[1]), m_[2], {pg: [int(x) for x in v] for pg, v in d.items()},
                                             {pg: sorted(lst, key=lambda x: -x[1])[:4] for pg, lst in who[(d_tid, gid_)].items()}]
                                            for m_, d, gid_ in rows_]
    # quota del 1° quarto sul totale (lega): base per le proiezioni 1Q dei giocatori con pochi dati
    q1_league = {}
    rows_q1 = [r for r in logs if "q1p" in r and r["date"] >= since_long]
    for qk, b in Q1_MAP.items():
        tot_b = sum(float(r[b]) for r in rows_q1)
        q1_league[qk] = sum(float(r[qk]) for r in rows_q1) / tot_b if tot_b > 0 else None
    # DvP per ruolo (come Props.Cash): quanto concede ogni difesa a guardie, ali e centri
    since_d = since_opp
    by_pos = defaultdict(list)
    for r in logs:
        if r["date"] >= since_d:
            by_pos[pos_group(r.get("pos", ""))].append(r)
    app["nba"]["dvpp"] = {}
    for pg, rows_ in by_pos.items():
        if pg and len(rows_) > 500:
            pf, _ = models.opponent_factors(rows_, markets, since_d, k=15)
            app["nba"]["dvpp"][pg] = {m: {tabbr(t): round(pf[t].get(m, 1.0), 3) for t in real_t if t in pf} for m in markets}
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
        hh = models.h2h_rows(matches or [], "nba", ev["home"]["id"], ev["away"]["id"])
        if hh:
            game["hh"] = hh
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
                c["var_min"] = var_min
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
                # doppia doppia / tripla doppia: modello sulle proiezioni, corretto con la frequenza reale recente
                pdd, ptd = models.dd_td(proj, c["exp2"], c.get("var_min", 16.0))
                rec = games[:20]
                n_ = len(rec)
                kdd = sum(1 for r in rec if models.dd_count(r) >= 2)
                ktd = sum(1 for r in rec if models.dd_count(r) >= 3)
                pdd = (pdd * 15 + kdd) / (15 + n_)
                ptd = (ptd * 15 + ktd) / (15 + n_)
                if pdd >= 0.01:
                    proj["dd"] = [round(-math.log(1 - min(pdd, 0.97)), 4), None]
                if ptd >= 0.003:
                    proj["tdd"] = [round(-math.log(1 - min(ptd, 0.9)), 4), None]
                # 1° quarto: proiezione della partita x quota del giocatore nel 1° quarto (ultime 40 con il dato)
                gq = [r for r in games[:60] if "q1p" in r][:40]
                for qk, b in Q1_MAP.items():
                    Lq = q1_league.get(qk)
                    if Lq is None or b not in proj or len(gq) < 3:
                        continue
                    full = sum(float(r[b]) for r in gq)
                    part = sum(float(r[qk]) for r in gq)
                    n_q = len(gq)
                    sh = ((part / full) * n_q + Lq * 10) / (n_q + 10) if full > 0 else Lq
                    proj[qk] = [round(proj[b][0] * sh, 3), proj[b][1]]
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
                    "l": [[r["date"], tabbr(r["opp"]), round(float(r["min"]))] + [int(float(r[b])) for b in base] + [int(float(r.get("home") or 0))] + q1_cols(r)
                          for r in games[:10]],
                }
                p["a30"]["dd"] = round(sum(1 for r in games[:30] if models.dd_count(r) >= 2) / len(games[:30]), 3)
                p["a30"]["tdd"] = round(sum(1 for r in games[:30] if models.dd_count(r) >= 3) / len(games[:30]), 3)
                od = props.get(name_key(p["n"]))
                if od:
                    p["odds"] = od
                app["nba"]["players"].append(p)
                # ultime 100 partite + tutte le sfide piu' vecchie contro l'avversario di oggi (H2H su 3 stagioni)
                hist["nba"][c["pid"]] = [[r["date"], tabbr(r["opp"]), round(float(r["min"]))] + [int(float(r[b])) for b in base] + [int(float(r.get("home") or 0))] + q1_cols(r)
                                         for r in games[:100] + [g_ for g_ in games[100:] if g_["opp"] == oid]]
    # filtro "con / senza un compagno": per le squadre in programma, le date in cui ogni giocatore della
    # rotazione ha giocato CON QUELLA SQUADRA (cosi' nell'app si vedono le partite di uno senza l'altro)
    base_d = dt.date(2020, 1, 1)
    tm = {}
    inj_all = {}
    for sport, path, league, ev in upcoming:
        if sport != "nba":
            continue
        inj_all.update(previews.get(ev["id"], {}).get("inj", {}))
        for side in ("home", "away"):
            tid = ev[side]["id"]
            ab = tabbr(tid)
            if ab == "?" or ab in tm:
                continue
            rows_t = []
            for pid in current.get(tid, []):
                g_all = [r for r in by_player[pid] if r["team"] == tid and float(r.get("min") or 0) > 0]
                if not g_all:
                    continue
                avg_min = sum(float(r["min"]) for r in g_all[:20]) / len(g_all[:20])
                if avg_min < 12 and len(g_all) < 30:
                    continue
                days = sorted({(dt.date.fromisoformat(r["date"][:10]) - base_d).days for r in g_all[:150]})
                rows_t.append([pid, g_all[0].get("name", "?"), round(avg_min, 1), inj_all.get(pid, ""), days])
            rows_t.sort(key=lambda x: -x[2])
            tm[ab] = rows_t[:15]
    hist["nba_tm"] = tm


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
    ou = state.get("odds_usage", {})
    odds_info = {"key": bool(odds.key() or propline.key()), "propline": bool(propline.key()), "propline_used": ou.get("propline_used"), "used": ou.get("used", 0), "budget": int(cfg.get("odds", {}).get("daily_credit_budget", 15)),
                 "remaining": ou.get("remaining"), "date": ou.get("date"),
                 "nba_games": len(app.get("nba", {}).get("games", [])),
                 "nba_with_odds": len({p["g"] for p in app.get("nba", {}).get("players", []) if p.get("odds")}),
                 "props_games": {sp: [len({p["g"] for p in app.get(sp, {}).get("players", []) if p.get("odds")}),
                                      len(app.get(sp, {}).get("games" if sp != "soccer" else "matches", []))] for sp in ("nba", "nfl", "mlb", "nhl", "soccer")}}
    return {"generated": app["generated"], "soccer": lg, "nba": nb, "queue": len(state.get("queue", [])), "odds": odds_info}


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
    is_cup = lambda lg: lg.startswith(("uefa.", "afc.", "conmebol.", "caf.", "concacaf.", "fifa.")) or "cup" in lg or "coppa" in lg or "pokal" in lg or "copa" in lg or "coupe" in lg or lg in ("eng.fa",) or lg.endswith("_qual")
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
    # nazionali: un giocatore resta nella sua squadra di club anche dopo una partita con la nazionale (e viceversa)
    nat_comp = lambda lg: lg.startswith(("fifa.world", "fifa.friendly", "uefa.nations", "uefa.euro", "conmebol.america", "caf.nations", "afc.asian", "concacaf.gold", "concacaf.nations"))
    nat_teams = set()
    for m in soc_all:
        if nat_comp(m.get("league", "")):
            nat_teams.update((m["hid"], m["aid"]))
    for s_, p_, l_, e_ in upcoming:
        if s_ == "soccer" and nat_comp(l_):
            nat_teams.update((e_["home"]["id"], e_["away"]["id"]))
    current = defaultdict(list)
    for pid, games in by_player.items():
        club = next((r for r in games if r["team"] not in nat_teams), None)
        nat = next((r for r in games if r["team"] in nat_teams), None)
        if club and club["date"] >= iso(today - dt.timedelta(days=120)):
            current[club["team"]].append(pid)
        if nat and nat["date"] >= iso(today - dt.timedelta(days=430)):
            current[nat["team"]].append(pid)

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
        hh = models.h2h_rows(soc_all, "soccer", h, a, pv.get("h2h"))
        if hh:
            mrow["hh"] = hh
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
                                       [int(float(r[b])) for b in models.SOC_BASE] + [int(float(r.get("home") or 0))] for r in games[:60]]
                od = props.get(name_key(games[0]["name"]))
                app["soccer"]["players"].append({
                    "odds": od,
                    "id": pid, "n": games[0]["name"], "t": tname(tid), "o": tname(oid), "g": ev["id"],
                    "lg": league, "h": 1 if side == "home" else 0, "pos": games[0].get("pos", ""), "oa": tabbr(oid),
                    "ps": round(p_start, 2), "m": round(exp_min), "lu": 1 if lineup else 0,
                    "mk": {m: list(v) for m, v in proj.items()},
                    "of": {m: round(opp_f.get(oid, {}).get(m, 1.0), 3) for m in markets},
                    "rf": round(ref_f[ref]["card"], 3) if ref and ref in ref_f else None,
                    "a30": {m: round(sum(models.market_value(r, c, m) for r in games[:30]) / len(games[:30]), 3)
                            for m, c in markets.items()},
                    "l": [[r["date"], tabbr(r["opp"]), round(float(r["min"])), int(r["starter"])] +
                          [int(float(r[b])) for b in models.SOC_BASE] + [int(float(r.get("home") or 0))] for r in games[:10]],
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
