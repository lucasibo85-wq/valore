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
def build(sport, app, logs, upcoming, previews, teams, today, hist):
    spec = SPORTS[sport]
    markets = spec["markets"]
    bern = spec["bernoulli"]
    if not logs:
        return
    since = (today - dt.timedelta(days=400)).isoformat()
    priors = models.league_priors(sport, logs, markets, since)
    opp_f, home_f = models.opponent_factors(logs, markets, since, k=8 if sport == "nfl" else 20)
    yr = today.year if today.month >= spec["season_month"] else today.year - 1
    season_start = dt.date(yr, spec["season_month"], 1).isoformat()
    tabbr = lambda tid: teams.get(sport, {}).get(tid, {}).get("abbr", "?")

    by_player = defaultdict(list)
    tg = defaultdict(dict)
    for r in logs:
        by_player[r["pid"]].append(r)
        tg[r["team"]][r["gid"]] = r["date"]
    team_games = {t: [g for g, _ in sorted(d.items(), key=lambda x: x[1], reverse=True)] for t, d in tg.items()}
    for pid in by_player:
        by_player[pid].sort(key=lambda r: r["date"], reverse=True)
    current = defaultdict(list)
    for pid, games in by_player.items():
        if games[0]["date"] >= (today - dt.timedelta(days=270)).isoformat():
            current[games[0]["team"]].append(pid)

    for s_, path, league, ev in upcoming:
        if s_ != sport:
            continue
        pv = previews.get(ev["id"], {})
        inj = pv.get("inj", {})
        probs_sp = pv.get("probables", {})
        app[sport]["games"].append({"id": ev["id"], "t": ev["date"], "h": tabbr(ev["home"]["id"]),
                                    "a": tabbr(ev["away"]["id"]), "hn": ev["home"]["name"], "an": ev["away"]["name"],
                                    "odds": ev.get("odds")})
        for side, opp_side in (("home", "away"), ("away", "home")):
            tid, oid = ev[side]["id"], ev[opp_side]["id"]
            recent = team_games.get(tid, [])[:6]
            for pid in current.get(tid, []):
                games = by_player[pid]
                status = inj.get(pid.rstrip("p"), "")
                if status.lower().startswith("out"):
                    continue
                played = {r["gid"] for r in games[:10]}
                apps = sum(1 for g in recent if g in played)
                pitcher = pid.endswith("p")
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
                # solo mercati in cui il giocatore produce qualcosa
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
                fac = {m: opp_f.get(oid, {}).get(m, 1.0) * (home_f.get(m, 1.0) if side == "home" else max(0.6, 2 - home_f.get(m, 1.0)))
                       for m in mk_ok}
                proj = models.project(games, sport, mk_ok, priors, exp, 0.0, fac, spec["half_life"], spec["prior_exposure"])
                for m in list(proj):
                    if m in bern:
                        proj[m] = (proj[m][0], None)
                base = spec["base"]
                p = {
                    "id": pid, "n": games[0]["name"], "t": tabbr(tid), "o": tabbr(oid), "g": ev["id"],
                    "h": 1 if side == "home" else 0, "pos": games[0].get("pos", ""), "st": status,
                    "m": round(exp, 1), "mk": {m: list(v) for m, v in proj.items()},
                    "of": {m: round(opp_f.get(oid, {}).get(m, 1.0), 3) for m in mk_ok},
                    "a30": {m: round(sum(models.market_value(r, c, m) for r in games[:30]) / len(games[:30]), 2)
                            for m, c in mk_ok.items()},
                    "l": [[r["date"], tabbr(r["opp"]), round(float(r["min"]), 1)] + [round(float(r[b]), 1) for b in base]
                          for r in games[:10]],
                }
                app[sport]["players"].append(p)
                hist[sport][pid] = [[r["date"], tabbr(r["opp"]), round(float(r["min"]), 1)] + [round(float(r[b]), 1) for b in base]
                                    for r in games[:60]]
