"""NFL e MLB: lettura dei tabellini ESPN e proiezioni dei giocatori.

Stesso metodo dell'NBA: tasso per unita' di "esposizione" pesato sulle partite recenti,
corretto verso la media del ruolo, per l'esposizione attesa e per l'avversario.
- NFL: esposizione = 1 partita (statistiche per partita).
- MLB battitori: esposizione = turni in battuta (AB + BB); lanciatori: eliminazioni (outs).
"""
import datetime as dt
from collections import defaultdict

from . import espn, models

# --------------------------------------------------------------------------- definizioni
SPORTS = {
    "nfl": {
        "path": "football/nfl",
        "base": ["pass_yds", "pass_td", "pass_cmp", "pass_att", "int", "rush_yds", "rush_att",
                 "rush_td", "rec", "rec_yds", "rec_td", "tgt"],
        "markets": {
            "pass_yds": ["pass_yds"], "pass_td": ["pass_td"], "pass_cmp": ["pass_cmp"],
            "pass_att": ["pass_att"], "int": ["int"], "rush_yds": ["rush_yds"],
            "rush_att": ["rush_att"], "rec": ["rec"], "rec_yds": ["rec_yds"],
            "rr_yds": ["rush_yds", "rec_yds"], "pr_yds": ["pass_yds", "rush_yds"],
            "td": ["rush_td", "rec_td"],
        },
        "bernoulli": {"td"},
        "categories": {
            "pass": {"C/ATT": ("pass_cmp", "pass_att"), "YDS": "pass_yds", "TD": "pass_td", "INT": "int"},
            "rush": {"CAR": "rush_att", "YDS": "rush_yds", "TD": "rush_td"},
            "receiv": {"REC": "rec", "YDS": "rec_yds", "TD": "rec_td", "TGTS": "tgt"},
        },
        "half_life": 6, "prior_exposure": 2.0, "season_month": 9,
    },
    "mlb": {
        "path": "baseball/mlb",
        "base": ["h", "r", "rbi", "hr", "bb", "so", "outs", "p_k", "er", "p_h", "p_bb"],
        "markets": {
            "h": ["h"], "r": ["r"], "rbi": ["rbi"], "hr": ["hr"], "hrr": ["h", "r", "rbi"],
            "bb": ["bb"], "so": ["so"],
            "p_k": ["p_k"], "outs": ["outs"], "er": ["er"], "p_h": ["p_h"], "p_bb": ["p_bb"],
        },
        "bernoulli": {"hr"},
        "categories": {
            "batting": {"AB": "ab", "R": "r", "H": "h", "RBI": "rbi", "HR": "hr", "BB": "bb", "K": "so"},
            "pitching": {"IP": "ip", "H": "p_h", "ER": "er", "BB": "p_bb", "K": "p_k"},
        },
        "half_life": 25, "prior_exposure": 40.0, "season_month": 3,
    },
}
PITCH = ["outs", "p_k", "er", "p_h", "p_bb"]
BAT = ["h", "r", "rbi", "hr", "bb", "so"]


def cols(sport):
    return ["gid", "date", "team", "opp", "home", "pid", "name", "pos", "starter", "min"] + SPORTS[sport]["base"]


def _innings_to_outs(v):
    s = str(v or "0")
    try:
        if "." in s:
            a, b = s.split(".", 1)
            return int(a) * 3 + int(b[:1] or 0)
        return int(float(s)) * 3
    except ValueError:
        return 0


# --------------------------------------------------------------------------- tabellini
def parse_box(sport, summ):
    """Righe per giocatore. In MLB un lanciatore ha una riga separata con pid + 'p'."""
    spec = SPORTS[sport]
    rows = {}
    box = (summ or {}).get("boxscore") or {}
    for team_block in box.get("players", []) or []:
        team_id = str((team_block.get("team") or {}).get("id", ""))
        for st in team_block.get("statistics", []) or []:
            cname = str(st.get("name") or st.get("type") or st.get("text") or "").lower()
            cat = next((c for c in spec["categories"] if c in cname), None)
            if not cat:
                continue
            fmap = spec["categories"][cat]
            labels = [str(x).upper() for x in (st.get("labels") or st.get("names") or [])]
            for i_ath, ath in enumerate(st.get("athletes", []) or []):
                if ath.get("didNotPlay"):
                    continue
                vals = ath.get("stats") or []
                a = ath.get("athlete") or {}
                pid = str(a.get("id", ""))
                if not pid or not vals:
                    continue
                pitcher = sport == "mlb" and cat == "pitching"
                key = pid + ("p" if pitcher else "")
                row = rows.get(key)
                if row is None:
                    row = {"pid": key, "name": a.get("displayName") or a.get("shortName", "?"),
                           "pos": "P" if pitcher else ((a.get("position") or {}).get("abbreviation") or ""),
                           "team": team_id, "starter": 1 if (ath.get("starter") or (pitcher and i_ath == 0)) else 0,
                           "min": 0.0}
                    for b in spec["base"]:
                        row[b] = 0.0
                    rows[key] = row
                for lab, field in fmap.items():
                    if lab not in labels:
                        continue
                    i = labels.index(lab)
                    if i >= len(vals):
                        continue
                    raw = vals[i]
                    if isinstance(field, tuple):  # "C/ATT" -> "22/34"
                        parts = str(raw).replace("-", "/").split("/")
                        if len(parts) == 2:
                            row[field[0]] = espn._num(parts[0])
                            row[field[1]] = espn._num(parts[1])
                    elif field == "ip":
                        row["outs"] = float(_innings_to_outs(raw))
                    elif field == "ab":
                        row["_ab"] = espn._num(raw)
                    else:
                        row[field] = espn._num(raw)
    out = []
    for key, r in rows.items():
        if sport == "nfl":
            if r["pass_att"] + r["rush_att"] + r["rec"] + r["tgt"] <= 0:
                continue
            r["min"] = 1.0
        else:
            if key.endswith("p"):
                r["min"] = r["outs"]
                if r["outs"] <= 0:
                    continue
            else:
                r["min"] = r.pop("_ab", 0.0) + r["bb"]
                if r["min"] <= 0:
                    continue
        r.pop("_ab", None)
        out.append(r)
    return out


def probables(summ_or_event):
    """Lanciatori partenti annunciati (MLB): {team_id: pid}."""
    out = {}
    comp = None
    if isinstance(summ_or_event, dict):
        hdr = summ_or_event.get("header") or {}
        comps = hdr.get("competitions") or summ_or_event.get("competitions") or []
        comp = comps[0] if comps else None
    for c in (comp or {}).get("competitors", []) or []:
        for pr in c.get("probables", []) or []:
            a = pr.get("athlete") or {}
            if a.get("id"):
                out[str((c.get("team") or {}).get("id", c.get("id", "")))] = str(a["id"]) + "p"
    return out


# --------------------------------------------------------------------------- proiezioni
def _implied(odds, side, home_abbr, away_abbr):
    """Punti attesi della squadra da totale e handicap pubblicati da ESPN (None se mancano)."""
    if not odds or odds.get("ou") in (None, ""):
        return None
    from .run import spread_home
    hsp = spread_home(odds, home_abbr, away_abbr)
    if hsp is None:
        return None
    tot = float(odds["ou"])
    return tot / 2 - hsp / 2 if side == "home" else tot / 2 + hsp / 2


def build(sport, app, logs, upcoming, previews, teams, today, hist, matches=None, calib=None):
    """Proiezioni NFL / MLB e mercati di squadra.

    Rispetto alla versione base:
    - mercati di squadra (vincente, handicap / run line, totali) dal modello punti/run;
    - NFL: bersagli e corse dei giocatori assenti ridistribuiti ai compagni; yard e touchdown
      legati ai punti attesi della squadra (quote ESPN se presenti, altrimenti modello);
    - MLB: run attesi corretti per il lanciatore partente; prop dei battitori legate ai run attesi
      e alla qualita' del lanciatore avversario (strikeout e punti concessi);
    - autocalibrazione per mercato.
    """
    from . import teamus
    spec = SPORTS[sport]
    markets = spec["markets"]
    bern = spec["bernoulli"]
    calib = calib or {}
    if not logs:
        return
    since = (today - dt.timedelta(days=400)).isoformat()
    priors = models.league_priors(sport, logs, markets, since)
    opp_f, home_f = models.opponent_factors(logs, markets, since, k=8 if sport == "nfl" else 20)
    yr = today.year if today.month >= spec["season_month"] else today.year - 1
    season_start = dt.date(yr, spec["season_month"], 1).isoformat()
    tabbr = lambda tid: teams.get(sport, {}).get(tid, {}).get("abbr", "?")
    T = today.isoformat()
    sm = [m for m in (matches or []) if m.get("sport") == sport]
    strengths = models.team_strengths(sm, T, half_life_days=200 if sport == "nfl" else 90,
                                      prior_games=3 if sport == "nfl" else 10)

    by_player = defaultdict(list)
    tg = defaultdict(dict)
    tsum = defaultdict(lambda: defaultdict(float))
    for r in logs:
        by_player[r["pid"]].append(r)
        tg[r["team"]][r["gid"]] = r["date"]
        if not str(r["pid"]).endswith("p"):
            for b in spec["base"]:
                tsum[(r["gid"], r["team"])][b] += float(r[b])
    team_games = {t: [g for g, _ in sorted(d.items(), key=lambda x: x[1], reverse=True)] for t, d in tg.items()}
    for pid in by_player:
        by_player[pid].sort(key=lambda r: r["date"], reverse=True)
    current = defaultdict(list)
    for pid, games in by_player.items():
        if games[0]["date"] >= (today - dt.timedelta(days=270)).isoformat():
            current[games[0]["team"]].append(pid)
    # punti/run medi per squadra (ultime 10 partite)
    pts_avg = {}
    for m in sorted(sm, key=lambda m: m["date"]):
        for t, v in ((m["hid"], m["hs"]), (m["aid"], m["as"])):
            if v not in (None, ""):
                pts_avg.setdefault(t, []).append(float(v))
    pts_avg = {t: sum(v[-10:]) / len(v[-10:]) for t, v in pts_avg.items() if v}
    # lanciatori: punti concessi e strikeout per eliminazione, rispetto alla media
    lg_er = lg_k = None
    pit = {}
    if sport == "mlb":
        prow = [r for r in logs if str(r["pid"]).endswith("p") and r["date"] >= since]
        outs = sum(float(r["outs"]) for r in prow) or 1.0
        lg_er = sum(float(r["er"]) for r in prow) / outs
        lg_k = sum(float(r["p_k"]) for r in prow) / outs
        for pid in {r["pid"] for r in prow}:
            g_ = [r for r in by_player[pid] if r["starter"]][:12] or by_player[pid][:12]
            o_ = sum(float(r["outs"]) for r in g_)
            er_ = (sum(float(r["er"]) for r in g_) + lg_er * 60) / (o_ + 60)
            k_ = (sum(float(r["p_k"]) for r in g_) + lg_k * 60) / (o_ + 60)
            exp_o = sum(float(r["outs"]) for r in g_) / len(g_) if g_ else 15.0
            pit[pid] = {"er": er_ / lg_er if lg_er else 1, "k": k_ / lg_k if lg_k else 1, "outs": exp_o}

    for s_, path, league, ev in upcoming:
        if s_ != sport:
            continue
        pv = previews.get(ev["id"], {})
        inj = pv.get("inj", {})
        probs_sp = pv.get("probables") or ev.get("probables") or {}
        h_id, a_id = ev["home"]["id"], ev["away"]["id"]
        habbr, aabbr = tabbr(h_id), tabbr(a_id)
        odds_ev = ev.get("odds") or {}
        game = {"id": ev["id"], "t": ev["date"], "h": habbr, "a": aabbr, "hn": ev["home"]["name"],
                "an": ev["away"]["name"], "odds": ev.get("odds")}
        if ev.get("state") == "in":
            game["live"] = 1
        hh = models.h2h_rows(matches or [], sport, h_id, a_id)
        if hh:
            game["hh"] = hh
        from .run import pick_keys
        eo = pick_keys(sport, pv.get("pick"))
        if eo:
            game["eo"] = eo
            game["eob"] = pv["pick"].get("book")
        # --- punti/run attesi delle due squadre
        exp_team = {}
        if strengths and h_id in strengths["att"] and a_id in strengths["att"]:
            mh = strengths["avg_h"] * strengths["att"][h_id] * strengths["def"][a_id]
            ma = strengths["avg_a"] * strengths["att"][a_id] * strengths["def"][h_id]
            notes = []
            if sport == "mlb":
                for tid_, opp_key in ((h_id, "a"), (a_id, "h")):
                    sp_ = probs_sp.get(tid_)
                    if sp_ and sp_ in pit:
                        f = pit[sp_]
                        share = min(1.0, f["outs"] / 27.0)
                        mult = 1 + (f["er"] - 1) * share
                        if opp_key == "a":
                            ma *= mult
                        else:
                            mh *= mult
                        nm = by_player[sp_][0]["name"] if by_player.get(sp_) else "?"
                        notes.append("%s: lanciatore %s (punti concessi %+.0f%% vs media)" % (tabbr(tid_), nm, (f["er"] - 1) * 100))
            hl = teamus_line = None
            if odds_ev.get("ou") not in (None, ""):
                from .run import spread_home
                hl = spread_home(odds_ev, habbr, aabbr)
            game.update({"mh": round(mh, 2), "ma": round(ma, 2), "notes": notes})
            if sport == "mlb":
                game["mk"] = teamus.mlb_markets(mh, ma, odds_ev.get("ou"))
            else:
                game["mk"] = teamus.normal_markets(sport, mh, ma, hl, odds_ev.get("ou"))
            exp_team = {h_id: mh, a_id: ma}
        app[sport]["games"].append(game)

        for side, opp_side in (("home", "away"), ("away", "home")):
            tid, oid = ev[side]["id"], ev[opp_side]["id"]
            recent = team_games.get(tid, [])[:6]
            cands = []
            missing = defaultdict(float)
            for pid in current.get(tid, []):
                games = by_player[pid]
                status = inj.get(pid.rstrip("p"), "")
                played = {r["gid"] for r in games[:10]}
                apps = sum(1 for g in recent if g in played)
                pitcher = pid.endswith("p")
                last4 = games[:4]
                if status.lower().startswith("out"):
                    if sport == "nfl" and apps >= 1:
                        for b in ("tgt", "rush_att"):
                            missing[b] += sum(float(r[b]) for r in last4) / max(1, len(last4))
                    continue
                if sport == "mlb":
                    if pitcher:
                        if probs_sp.get(tid) != pid:
                            continue
                        rel = [r for r in games[:10] if r["starter"]] or games[:10]
                    else:
                        if apps < 3:
                            continue
                        rel = games[:10]
                else:
                    if apps < 1:
                        continue
                    rel = games[:8]
                ws = models.decay_weights(len(rel), 4)
                exp = models.wmean([float(r["min"]) for r in rel], ws)
                if exp <= 0:
                    continue
                use = [m for m in markets if (m in PITCH) == pitcher or sport != "mlb"]
                avg = {m: sum(models.market_value(r, markets[m], m) for r in games[:12]) / len(games[:12]) for m in use}
                mk_ok = {m: markets[m] for m in use if avg[m] > (0.05 if m in bern else 0.4)}
                if sport == "nfl":
                    if avg.get("pass_att", 0) < 8:
                        for m in ("pass_yds", "pass_td", "pass_cmp", "pass_att", "int", "pr_yds"):
                            mk_ok.pop(m, None)
                    if avg.get("rush_att", 0) < 3:
                        mk_ok.pop("rush_att", None)
                        mk_ok.pop("rush_yds", None)
                    if avg.get("rec", 0) < 1.0:
                        mk_ok.pop("rec", None)
                        mk_ok.pop("rec_yds", None)
                if not mk_ok:
                    continue
                cands.append({"pid": pid, "games": games, "status": status, "exp": exp, "mk": mk_ok, "pitcher": pitcher,
                              "tgt": sum(float(r["tgt"]) for r in last4) / len(last4) if sport == "nfl" else 0,
                              "ra": sum(float(r["rush_att"]) for r in last4) / len(last4) if sport == "nfl" else 0})
            # --- fattori di squadra
            kb = {}
            notes_t = []
            ip = _implied(odds_ev, side, habbr, aabbr)
            exp_pts = ip if ip is not None else exp_team.get(tid)
            avg_pts = pts_avg.get(tid)
            if exp_pts and avg_pts:
                k = max(0.75, min(1.3, exp_pts / avg_pts))
                notes_t.append("%s attesi %.1f (media %.1f)%s" % ("Punti" if sport == "nfl" else "Run", exp_pts, avg_pts,
                                                                  " da quote ESPN" if ip is not None else ""))
                if sport == "nfl":
                    kb.update({"pass_yds": k ** 0.5, "rec_yds": k ** 0.5, "rush_yds": k ** 0.5, "pass_td": k, "rush_td": k,
                               "rec_td": k, "rec": k ** 0.3, "pass_cmp": k ** 0.3, "pass_att": k ** 0.2, "tgt": k ** 0.3})
                else:
                    kb.update({"h": k ** 0.5, "r": k, "rbi": k, "hr": k ** 0.8, "bb": k ** 0.3})
            if sport == "nfl":
                for b, key in (("tgt", "tgt"), ("rush_att", "ra")):
                    tot_ = sum(c[key] for c in cands)
                    if missing[b] > 0 and tot_ > 0:
                        f = 1 + 0.8 * missing[b] / tot_
                        notes_t.append("%s di compagni assenti ridistribuiti (+%.0f%%)" % ("Bersagli" if b == "tgt" else "Corse", (f - 1) * 100))
                        comps = ("rec", "rec_yds", "rec_td", "tgt") if b == "tgt" else ("rush_att", "rush_yds", "rush_td")
                        for c_ in comps:
                            kb[c_] = kb.get(c_, 1.0) * f
            opp_sp = probs_sp.get(oid) if sport == "mlb" else None
            if opp_sp and opp_sp in pit:
                f = pit[opp_sp]
                share = min(1.0, f["outs"] / 27.0)
                kb["so"] = kb.get("so", 1.0) * (1 + (f["k"] - 1) * share)
                for b in ("h", "r", "rbi"):
                    kb[b] = kb.get(b, 1.0) * (1 + (f["er"] - 1) * share * 0.7)
                notes_t.append("Lanciatore avversario: strikeout %+.0f%%, punti concessi %+.0f%% vs media" % ((f["k"] - 1) * 100, (f["er"] - 1) * 100))
            for c in cands:
                games = c["games"]
                mk_ok = c["mk"]
                fac = {m: opp_f.get(oid, {}).get(m, 1.0) * (home_f.get(m, 1.0) if side == "home" else max(0.6, 2 - home_f.get(m, 1.0)))
                       for m in mk_ok}
                proj = models.project(games, sport, mk_ok, priors, c["exp"], 0.0, fac, spec["half_life"], spec["prior_exposure"])
                out = {}
                for m, comps in mk_ok.items():
                    mu, r = proj[m]
                    k_ = [(kb.get(b, 1.0), max(0.01, avg_c)) for b in comps
                          for avg_c in [sum(float(rr[b]) for rr in games[:8]) / len(games[:8])]]
                    w = sum(x[1] for x in k_)
                    k = sum(a * b for a, b in k_) / w if w else 1.0
                    k *= calib.get(m, 1.0)
                    out[m] = [round(mu * k, 4), None if m in bern else r]
                base = spec["base"]
                n_g = len(games)
                rel = "A" if n_g >= 12 and not c["status"] else ("B" if n_g >= 6 else "C")
                p = {
                    "id": c["pid"], "n": games[0]["name"], "t": tabbr(tid), "o": tabbr(oid), "g": ev["id"],
                    "h": 1 if side == "home" else 0, "pos": games[0].get("pos", ""), "st": c["status"],
                    "m": round(c["exp"], 1), "mk": out, "rel": rel, "adj": notes_t,
                    "of": {m: round(opp_f.get(oid, {}).get(m, 1.0), 3) for m in mk_ok},
                    "a30": {m: round(sum(models.market_value(r, cc, m) for r in games[:30]) / len(games[:30]), 2)
                            for m, cc in mk_ok.items()},
                    "l": [[r["date"], tabbr(r["opp"]), round(float(r["min"]), 1)] + [round(float(r[b]), 1) for b in base]
                          for r in games[:10]],
                }
                app[sport]["players"].append(p)
                hist[sport][c["pid"]] = [[r["date"], tabbr(r["opp"]), round(float(r["min"]), 1)] + [round(float(r[b]), 1) for b in base]
                                         for r in games[:60]]
