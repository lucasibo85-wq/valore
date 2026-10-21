"""Server ESPN finto per i test: genera calendari e tabellini sintetici ma realistici.

I giocatori hanno tassi "veri" noti, cosi' si puo' verificare che il modello li ritrovi.
"""
import datetime as dt
import hashlib
import math
import random
import re
from urllib.parse import urlparse

TODAY = dt.datetime.utcnow().date()


def stable(x):
    return int(hashlib.md5(str(x).encode()).hexdigest()[:8], 16)


def rng_for(*parts):
    h = hashlib.md5("|".join(map(str, parts)).encode()).hexdigest()
    return random.Random(int(h[:12], 16))


def nb_sample(r, mu, k=12.0):
    if mu <= 0:
        return 0
    lam = r.gammavariate(k, mu / k)
    # poisson
    L, p, n = math.exp(-lam), 1.0, 0
    if lam > 30:
        return max(0, int(round(r.gauss(lam, math.sqrt(lam)))))
    while True:
        p *= r.random()
        if p <= L:
            return n
        n += 1


# ------------------------------------------------------------------ NBA
NBA_TEAMS = [("%d" % (i + 1), abbr) for i, abbr in enumerate(
    "ATL BOS BKN CHA CHI CLE DAL DEN DET GSW HOU IND LAC LAL MEM MIA MIL MIN NOP NYK OKC ORL PHI PHX POR SAC SAS TOR UTA WAS".split())]
POS = ["PG", "SG", "SF", "PF", "C"]


def nba_roster(team_id):
    r = rng_for("roster", team_id)
    out = []
    for j in range(12):
        star = 1.6 if j == 0 else (1.25 if j < 3 else 1.0)
        mins = max(8.0, 36 - j * 2.6 + r.uniform(-2, 2))
        pos = POS[j % 5]
        out.append({
            "id": "%s%02d" % (team_id, j), "name": "Giocatore %s-%d" % (team_id, j), "pos": pos,
            "min": mins,
            "pts": 0.48 * star * r.uniform(0.8, 1.2), "reb": (0.28 if pos in ("PF", "C") else 0.14) * r.uniform(0.8, 1.2),
            "ast": (0.2 if pos in ("PG", "SG") else 0.07) * r.uniform(0.8, 1.3), "stl": 0.03 * r.uniform(0.6, 1.5),
            "blk": (0.05 if pos == "C" else 0.012) * r.uniform(0.6, 1.5), "fg3m": (0.07 if pos != "C" else 0.01) * r.uniform(0.5, 1.6),
            "tov": 0.05 * r.uniform(0.7, 1.3),
        })
    return out


TEAM_DEF = {tid: rng_for("def", tid).uniform(0.92, 1.08) for tid, _ in NBA_TEAMS}


def nba_events(date):
    r = rng_for("nbaday", date)
    if r.random() < 0.15:
        return []
    teams = NBA_TEAMS[:]
    r.shuffle(teams)
    n = r.randint(3, 7)
    evs = []
    for i in range(n):
        h, a = teams[2 * i], teams[2 * i + 1]
        evs.append(("401%s%02d" % (date.strftime("%y%m%d"), i), date, h, a))
    return evs


def nba_box(eid, date, h, a):
    r = rng_for("box", eid)
    blocks = []
    for (tid, abbr), (oid, _) in ((h, a), (a, h)):
        athletes = []
        for p in nba_roster(tid):
            if r.random() < 0.06:
                athletes.append({"athlete": {"id": p["id"], "displayName": p["name"], "position": {"abbreviation": p["pos"]}},
                                 "didNotPlay": True, "stats": []})
                continue
            mins = max(4, int(r.gauss(p["min"], 4)))
            f = TEAM_DEF[oid]
            v = {k: nb_sample(r, p[k] * mins * f) for k in ("pts", "reb", "ast", "stl", "blk", "fg3m", "tov")}
            stats = [str(mins), "%d-%d" % (v["pts"] // 2, v["pts"]), "%d-%d" % (v["fg3m"], v["fg3m"] + 3), "2-2", "1",
                     str(max(0, v["reb"] - 1)), str(v["reb"]), str(v["ast"]), str(v["stl"]), str(v["blk"]), str(v["tov"]), "2", "+3", str(v["pts"])]
            athletes.append({"athlete": {"id": p["id"], "displayName": p["name"], "position": {"abbreviation": p["pos"]}},
                             "starter": p["id"].endswith(("00", "01", "02", "03", "04")), "didNotPlay": False, "stats": stats})
        blocks.append({"team": {"id": tid, "abbreviation": abbr},
                       "statistics": [{"labels": ["MIN", "FG", "3PT", "FT", "OREB", "DREB", "REB", "AST", "STL", "BLK", "TO", "PF", "+/-", "PTS"],
                                       "athletes": athletes}]})
    return {"boxscore": {"players": blocks}}


# ------------------------------------------------------------------ calcio
LEAGUES = {}


def soccer_teams(lg):
    if lg not in LEAGUES:
        LEAGUES[lg] = [("%s%02d" % (stable(lg) % 900 + 100, i), "Squadra %s %d" % (lg, i)) for i in range(10)]
    return LEAGUES[lg]


def soccer_roster(tid):
    r = rng_for("sroster", tid)
    out = []
    for j in range(18):
        pos = "G" if j == 0 else "D" if j < 5 else "M" if j < 9 else "F" if j < 11 else ["D", "M", "F"][j % 3]
        start_p = 0.95 if j < 11 else 0.1
        sh = {"G": 0.0, "D": 0.4, "M": 1.0, "F": 2.6}[pos] * r.uniform(0.7, 1.4) / 90
        out.append({"id": "%s%02d" % (tid, j), "name": "Calciatore %s-%d" % (tid, j), "pos": pos, "start": start_p,
                    "shots": sh, "sot": sh * 0.38, "fc": r.uniform(0.6, 2.0) / 90, "fs": r.uniform(0.5, 1.8) / 90,
                    "yc": r.uniform(0.08, 0.3) / 90, "g": sh * 0.11, "a": sh * 0.08 + 0.05 / 90})
    return out


def soccer_events(lg, date):
    if date.weekday() not in (5, 6, 2):
        return []
    r = rng_for("sday", lg, date)
    teams = soccer_teams(lg)[:]
    r.shuffle(teams)
    return [("7%s%s%d" % (stable(lg) % 1000, date.strftime("%y%m%d"), i), date, teams[2 * i], teams[2 * i + 1]) for i in range(5)]


def soccer_box(eid, h, a):
    r = rng_for("sbox", eid)
    rosters = []
    goals = {}
    for (tid, name), (oid, _) in ((h, a), (a, h)):
        roster = []
        players = soccer_roster(tid)
        starters = [p for p in players if r.random() < p["start"]][:11]
        subs = [p for p in players if p not in starters]
        r.shuffle(subs)
        g_tot = 0
        for p in players:
            st = p in starters
            sub_in = (not st) and p in subs[:3]
            if not st and not sub_in:
                roster.append({"athlete": {"id": p["id"], "displayName": p["name"]}, "starter": False, "subbedIn": False, "stats": []})
                continue
            sub_out = st and r.random() < 0.25
            mins = 68 if sub_out else (90 if st else 22)
            v = {k: nb_sample(r, p[k] * mins, 50) for k in ("shots", "fc", "fs", "yc", "a")}
            v["sot"] = sum(1 for _ in range(v["shots"]) if r.random() < 0.38)
            v["g"] = sum(1 for _ in range(v["sot"]) if r.random() < 0.3)
            g_tot += v["g"]
            v["yc"] = min(1, v["yc"])
            stats = [{"name": "totalShots", "value": v["shots"]}, {"name": "shotsOnTarget", "value": v["sot"]},
                     {"name": "foulsCommitted", "value": v["fc"]}, {"name": "foulsSuffered", "value": v["fs"]},
                     {"name": "yellowCards", "value": v["yc"]}, {"name": "redCards", "value": 0},
                     {"name": "totalGoals", "value": v["g"]}, {"name": "goalAssists", "value": v["a"]},
                     {"name": "appearances", "value": 1}]
            roster.append({"athlete": {"id": p["id"], "displayName": p["name"]}, "position": {"abbreviation": p["pos"]},
                           "starter": st, "subbedIn": sub_in, "subbedOut": sub_out, "stats": stats})
        goals[tid] = g_tot
        rosters.append({"homeAway": "home" if tid == h[0] else "away", "team": {"id": tid, "displayName": name}, "roster": roster})
    return {"rosters": rosters, "gameInfo": {"officials": [{"displayName": "Arbitro %d" % (int(eid) % 7), "position": {"name": "Referee"}}]}}, goals


# ------------------------------------------------------------------ router
def ev_json(eid, date, h, a, completed, score=None):
    hs, as_ = score or (None, None)
    return {"id": eid, "date": date.isoformat() + "T19:00Z",
            "status": {"type": {"state": "post" if completed else "pre", "completed": completed}},
            "competitions": [{"competitors": [
                {"homeAway": "home", "team": {"id": h[0], "abbreviation": h[1][:3].upper() if len(h[1]) > 3 else h[1], "displayName": h[1]}, "score": str(hs) if hs is not None else "0"},
                {"homeAway": "away", "team": {"id": a[0], "abbreviation": a[1][:3].upper() if len(a[1]) > 3 else a[1], "displayName": a[1]}, "score": str(as_) if as_ is not None else "0"}]}]}


EVENT_INDEX = {}


def parse_dates(s):
    if "-" in s:
        a, b = s.split("-")
    else:
        a = b = s
    d0 = dt.datetime.strptime(a, "%Y%m%d").date()
    d1 = dt.datetime.strptime(b, "%Y%m%d").date()
    while d0 <= d1:
        yield d0
        d0 += dt.timedelta(days=1)


def fake_get_json(url, params=None, headers=None, tries=3, pause=None):
    params = params or {}
    path = urlparse(url).path
    m = re.search(r"/sports/(basketball/nba|soccer/[^/]+)/(scoreboard|summary)$", path)
    if not m:
        return None, {}
    sport, kind = m.group(1), m.group(2)
    if kind == "scoreboard":
        events = []
        for d in parse_dates(params["dates"]):
            completed = d < TODAY
            if sport == "basketball/nba":
                for eid, date, h, a in nba_events(d):
                    EVENT_INDEX[eid] = ("nba", date, h, a)
                    events.append(ev_json(eid, date, h, a, completed, (100, 98) if completed else None))
            else:
                lg = sport.split("/")[1]
                for eid, date, h, a in soccer_events(lg, d):
                    EVENT_INDEX[eid] = ("soccer", date, h, a)
                    sc = None
                    if completed:
                        _, goals = soccer_box(eid, h, a)
                        sc = (goals[h[0]], goals[a[0]])
                    events.append(ev_json(eid, date, h, a, completed, sc))
        return {"events": events}, {}
    eid = params["event"]
    info = EVENT_INDEX.get(eid)
    if not info:
        return None, {}
    s, date, h, a = info
    if date >= TODAY:
        if s == "nba":
            return {"injuries": [{"injuries": [{"athlete": {"id": "%s00" % h[0]}, "status": "Out"}]}]}, {}
        return {"rosters": [], "gameInfo": {"officials": [{"displayName": "Arbitro 3", "position": {"name": "Referee"}}]}}, {}
    if s == "nba":
        return nba_box(eid, date, h, a), {}
    return soccer_box(eid, h, a)[0], {}
