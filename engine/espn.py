"""Lettura dei dati pubblici ESPN (NBA e calcio).

Le API ESPN non sono documentate: il parsing e' volutamente difensivo e
qualsiasi campo mancante viene saltato invece di bloccare l'esecuzione.
"""
from .net import get_json

BASE = "https://site.api.espn.com/apis/site/v2/sports/"


def _num(v, default=0.0):
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if s in ("", "-", "--", "DNP"):
        return default
    if ":" in s:  # minuti "34:12"
        a, b = s.split(":", 1)
        try:
            return float(a) + float(b) / 60.0
        except ValueError:
            return default
    if "-" in s[1:]:  # "3-8" -> realizzati
        s = s.split("-")[0]
    try:
        return float(s)
    except ValueError:
        return default


def _team(c):
    t = c.get("team") or {}
    return {
        "id": str(t.get("id", "")),
        "abbr": t.get("abbreviation") or t.get("shortDisplayName") or t.get("displayName", "?"),
        "name": t.get("displayName") or t.get("name") or t.get("abbreviation", "?"),
    }


def scoreboard(path, dates):
    """Eventi per una data (YYYYMMDD) o un intervallo (YYYYMMDD-YYYYMMDD)."""
    data, _ = get_json(BASE + path + "/scoreboard", params={"dates": dates, "limit": 1000})
    if not data:
        return None
    out = []
    for ev in data.get("events", []) or []:
        comps = ev.get("competitions") or [{}]
        comp = comps[0]
        teams = comp.get("competitors") or []
        home = next((c for c in teams if c.get("homeAway") == "home"), None)
        away = next((c for c in teams if c.get("homeAway") == "away"), None)
        if not home or not away:
            continue
        st = ((ev.get("status") or comp.get("status") or {}).get("type") or {})
        season = ev.get("season") or {}
        out.append({
            "odds": _espn_odds(comp),
            "probables": {str((c.get("team") or {}).get("id", "")): str(((c.get("probables") or [{}])[0].get("athlete") or {}).get("id", "")) + "p"
                          for c in teams if c.get("probables")},
            "stype": int(_num(season.get("type"), 0) or 0),
            "slug": str(season.get("slug") or ""),
            "name": str(ev.get("name") or ev.get("shortName") or ""),
            "id": str(ev.get("id")),
            "date": ev.get("date") or comp.get("date", ""),
            "state": st.get("state", "pre"),
            "completed": bool(st.get("completed")),
            "home": _team(home),
            "away": _team(away),
            "hs": _num(home.get("score"), None) if st.get("completed") else None,
            "as": _num(away.get("score"), None) if st.get("completed") else None,
        })
    return out


def _american(v):
    x = _num(v, None)
    if x is None or x == 0:
        return None
    return round(1 + (x / 100.0 if x > 0 else 100.0 / -x), 3)


def _espn_odds(comp):
    """Quote pubblicate da ESPN nel calendario (un solo bookmaker): 1X2 / testa a testa."""
    try:
        o = (comp.get("odds") or [None])[0]
        if not o:
            return None
        h = _american((o.get("homeTeamOdds") or {}).get("moneyLine"))
        a = _american((o.get("awayTeamOdds") or {}).get("moneyLine"))
        d = _american((o.get("drawOdds") or {}).get("moneyLine"))
        if not h or not a:
            return None
        return {"h": h, "a": a, "d": d, "book": ((o.get("provider") or {}).get("name") or "ESPN"),
                "ou": _num(o.get("overUnder"), None), "spread": _num(o.get("spread"), None)}
    except (AttributeError, TypeError, IndexError):
        return None


def nba_counts(ev, sport="nba"):
    """True per stagione regolare, play-in e playoff; False per preseason e All-Star.

    ESPN: season.type 1 = preseason, 2 = regular season, 3 = postseason,
    4 = off-season, 5 = play-in.
    """
    if ev.get("stype") in (1, 4) or "pre" in ev.get("slug", ""):
        return False
    if not ev.get("stype") and sport == "nba":  # tipo assente: la preseason NBA si gioca a settembre e fino a meta' ottobre
        d = ev.get("date", "")[:10]
        if d[5:7] == "09" or (d[5:7] == "10" and d[8:10] <= "17"):
            return False
    name = ev.get("name", "").lower()
    if "all-star" in name or "all star" in name or "rising stars" in name or "pro bowl" in name:
        return False
    return True


def summary(path, event_id):
    data, _ = get_json(BASE + path + "/summary", params={"event": event_id})
    return data


# ---------------------------------------------------------------- NBA
NBA_FIELDS = {
    "min": ("MIN", "minutes"),
    "pts": ("PTS", "points"),
    "reb": ("REB", "rebounds", "totalRebounds"),
    "ast": ("AST", "assists"),
    "stl": ("STL", "steals"),
    "blk": ("BLK", "blocks"),
    "fg3m": ("3PT", "threePointFieldGoalsMade-threePointFieldGoalsAttempted", "3PM", "threePointFieldGoalsMade"),
    "tov": ("TO", "turnovers"),
}


def parse_nba_box(summ):
    rows = []
    box = (summ or {}).get("boxscore") or {}
    for team_block in box.get("players", []) or []:
        team_id = str((team_block.get("team") or {}).get("id", ""))
        for st in team_block.get("statistics", []) or []:
            labels = [str(x) for x in (st.get("labels") or st.get("names") or [])]
            keys = [str(x) for x in (st.get("keys") or [])]
            idx = {}
            for f, alts in NBA_FIELDS.items():
                for a in alts:
                    if a in labels:
                        idx[f] = labels.index(a)
                        break
                    if a in keys:
                        idx[f] = keys.index(a)
                        break
            if "pts" not in idx or "min" not in idx:
                continue
            for ath in st.get("athletes", []) or []:
                if ath.get("didNotPlay"):
                    continue
                vals = ath.get("stats") or []
                if not vals:
                    continue
                a = ath.get("athlete") or {}
                row = {
                    "pid": str(a.get("id", "")),
                    "name": a.get("displayName") or a.get("shortName", "?"),
                    "pos": ((a.get("position") or {}).get("abbreviation") or ""),
                    "team": team_id,
                    "starter": 1 if ath.get("starter") else 0,
                }
                for f in NBA_FIELDS:
                    i = idx.get(f)
                    row[f] = _num(vals[i]) if i is not None and i < len(vals) else 0.0
                if row["min"] <= 0 or not row["pid"]:
                    continue
                rows.append(row)
    return rows


def parse_injuries(summ):
    """{player_id: stato} per gli infortunati elencati nell'anteprima."""
    out = {}
    for team in (summ or {}).get("injuries", []) or []:
        for inj in team.get("injuries", []) or []:
            a = inj.get("athlete") or {}
            pid = str(a.get("id", ""))
            status = inj.get("status") or (inj.get("type") or {}).get("description") or ""
            if pid:
                out[pid] = status
    return out


# ---------------------------------------------------------------- Calcio
SOCCER_FIELDS = {
    "shots": ("totalShots", "SH"),
    "sot": ("shotsOnTarget", "ST"),
    "fc": ("foulsCommitted", "FC"),
    "fs": ("foulsSuffered", "FA", "FS"),
    "yc": ("yellowCards", "YC"),
    "rc": ("redCards", "RC"),
    "g": ("totalGoals", "G"),
    "a": ("goalAssists", "A"),
}


def _stat_map(stats):
    m = {}
    for s in stats or []:
        v = s.get("value")
        if v is None:
            v = s.get("displayValue")
        for k in ("name", "abbreviation", "shortDisplayName"):
            if s.get(k):
                m[str(s[k])] = _num(v)
    return m


def _flag(v):
    if isinstance(v, dict):
        return bool(v.get("didSub", v))
    return bool(v)


def parse_soccer_box(summ):
    rows = []
    for team in (summ or {}).get("rosters", []) or []:
        team_id = str((team.get("team") or {}).get("id", ""))
        for p in team.get("roster", []) or []:
            sm = _stat_map(p.get("stats"))
            starter = bool(p.get("starter"))
            sub_in = _flag(p.get("subbedIn"))
            sub_out = _flag(p.get("subbedOut"))
            appeared = starter or sub_in or sm.get("appearances", 0) > 0
            if not appeared:
                continue
            if starter:
                mins = 68.0 if sub_out else 90.0
            else:
                mins = 22.0
            a = p.get("athlete") or {}
            pos = (p.get("position") or a.get("position") or {})
            row = {
                "pid": str(a.get("id", "")),
                "name": a.get("displayName") or a.get("shortName", "?"),
                "pos": (pos.get("abbreviation") or "")[:2],
                "team": team_id,
                "starter": 1 if starter else 0,
                "min": mins,
            }
            for f, alts in SOCCER_FIELDS.items():
                row[f] = next((sm[x] for x in alts if x in sm), 0.0)
            if row["pid"]:
                rows.append(row)
    return rows


def parse_lineup(summ):
    """Titolari annunciati (se presenti) per una partita non ancora giocata."""
    starters = set()
    for team in (summ or {}).get("rosters", []) or []:
        for p in team.get("roster", []) or []:
            if p.get("starter"):
                pid = str((p.get("athlete") or {}).get("id", ""))
                if pid:
                    starters.add(pid)
    return starters


def parse_referee(summ):
    gi = (summ or {}).get("gameInfo") or {}
    officials = gi.get("officials", []) or []
    best = ""
    for o in officials:
        p = o.get("position")
        pos = str((p.get("name") or p.get("displayName") or "") if isinstance(p, dict) else (p or "")).lower()
        name = o.get("displayName") or o.get("fullName") or ""
        if not name:
            continue
        if pos in ("referee", "arbitro", "main referee"):
            return name
        if not best and "assistant" not in pos and "var" not in pos and "fourth" not in pos:
            best = name
    return best
