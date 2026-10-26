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
            ou = _num(o.get("overUnder"), None)
            if ou is None:
                return None
            return {"h": None, "a": None, "d": None, "book": ((o.get("provider") or {}).get("name") or "ESPN"),
                    "details": o.get("details"), "ou": ou, "spread": _num(o.get("spread"), None)}
        return {"h": h, "a": a, "d": d, "book": ((o.get("provider") or {}).get("name") or "ESPN"),
                "details": o.get("details"),
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


def _sub_minutes(summ):
    """Minuti di entrata/uscita dai keyEvents: sostituzioni (participants[0] entra, [1] esce) ed espulsioni."""
    t_in, t_out = {}, {}
    for e in (summ or {}).get("keyEvents", []) or []:
        txt = str(((e.get("type") or {}).get("text")) or "").lower()
        sec = (e.get("clock") or {}).get("value")
        if sec is None:
            continue
        minute = max(1.0, min(120.0, float(sec) / 60.0))
        parts = [str(((p.get("athlete") or {}).get("id")) or "") for p in (e.get("participants") or [])]
        if "substitution" in txt and len(parts) >= 2:
            t_in[parts[0]] = minute
            t_out[parts[1]] = minute
        elif "red card" in txt and parts:
            t_out[parts[0]] = minute
    return t_in, t_out


def parse_soccer_box(summ):
    rows = []
    t_in, t_out = _sub_minutes(summ)
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
            a = p.get("athlete") or {}
            pid_ = str(a.get("id", ""))
            # minuti esatti dalle sostituzioni, altrimenti stima
            if starter:
                mins = t_out.get(pid_, 68.0 if sub_out else 90.0) if (sub_out or pid_ in t_out) else 90.0
            elif pid_ in t_in:
                mins = max(1.0, t_out.get(pid_, 90.0) - t_in[pid_])
            else:
                mins = 22.0
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


# ---------------------------------------------------------------- calcio: dati di squadra
TEAM_FIELDS = {
    "corners": ("wonCorners", "cornerKicks", "corners", "Corner Kicks", "Corners"),
    "yc": ("yellowCards", "Yellow Cards"),
    "rc": ("redCards", "Red Cards"),
    "fouls": ("foulsCommitted", "Fouls"),
    "shots": ("totalShots", "Shots"),
    "sot": ("shotsOnTarget", "On Target", "Shots on Target"),
}


def parse_soccer_team(summ):
    """Statistiche di squadra (angoli, cartellini, tiri) e gol del primo tempo.

    Ritorna {"teams": {team_id: {...}}, "ht": {team_id: gol 1T}}; campi assenti = non presenti.
    """
    out = {"teams": {}, "ht": {}}
    box = (summ or {}).get("boxscore") or {}
    for t in box.get("teams", []) or []:
        tid = str((t.get("team") or {}).get("id", ""))
        if not tid:
            continue
        sm = {}
        for st in t.get("statistics", []) or []:
            v = st.get("value")
            if v is None:
                v = st.get("displayValue")
            for k in ("name", "label", "abbreviation", "displayName"):
                if st.get(k):
                    sm[str(st[k])] = _num(v, None)
        row = {}
        for f, alts in TEAM_FIELDS.items():
            for a in alts:
                if sm.get(a) is not None:
                    row[f] = sm[a]
                    break
        if row:
            out["teams"][tid] = row
    # gol del primo tempo: linescores dell'intestazione, altrimenti eventi "scoringPlay" del 1° periodo
    hdr = ((summ or {}).get("header") or {}).get("competitions") or [{}]
    for c in hdr[0].get("competitors", []) or []:
        ls = c.get("linescores") or []
        tid = str(c.get("id") or (c.get("team") or {}).get("id", ""))
        if ls and tid:
            v = ls[0].get("displayValue", ls[0].get("value"))
            if v not in (None, ""):
                out["ht"][tid] = _num(v)
    if not out["ht"]:
        goals = {}
        found = False
        for e in (summ or {}).get("keyEvents", []) or []:
            if not e.get("scoringPlay"):
                continue
            found = True
            per = (e.get("period") or {}).get("number")
            tid = str((e.get("team") or {}).get("id", ""))
            if per == 1 and tid:
                goals[tid] = goals.get(tid, 0) + 1
        if found or goals:
            for c in hdr[0].get("competitors", []) or []:
                tid = str(c.get("id") or (c.get("team") or {}).get("id", ""))
                if tid:
                    out["ht"][tid] = float(goals.get(tid, 0))
    return out


def parse_pickcenter(summ):
    """Quote pubblicate da ESPN nel riepilogo (di solito DraftKings): vincente, handicap, totale."""
    pcs = (summ or {}).get("pickcenter") or []
    if not pcs:
        return None
    pc = pcs[0]
    h = pc.get("homeTeamOdds") or {}
    a = pc.get("awayTeamOdds") or {}
    out = {"book": ((pc.get("provider") or {}).get("name") or "ESPN"),
           "h": _american(h.get("moneyLine")), "a": _american(a.get("moneyLine")),
           "d": _american((pc.get("drawOdds") or {}).get("moneyLine")),
           "ou": _num(pc.get("overUnder"), None), "over": _american(pc.get("overOdds")), "under": _american(pc.get("underOdds")),
           "spread": _num(pc.get("spread"), None), "hs": _american(h.get("spreadOdds")), "as": _american(a.get("spreadOdds")),
           "details": pc.get("details")}
    return out


def parse_h2h(summ):
    """Scontri diretti pubblicati da ESPN nel riepilogo (calcio: 'headToHeadGames').
    Lettura difensiva: se il formato cambia ritorna una lista vuota."""
    out = []
    try:
        for blk in summ.get("headToHeadGames") or []:
            for e in blk.get("events") or []:
                hid, aid = e.get("homeTeamId"), e.get("awayTeamId")
                hs, as_ = e.get("homeTeamScore"), e.get("awayTeamScore")
                if (hs is None or as_ is None) and isinstance(e.get("score"), str) and "-" in e["score"]:
                    hs, as_ = e["score"].split("-")[:2]
                if hid is None or aid is None or hs is None or as_ is None:
                    continue
                try:
                    hs, as_ = int(float(str(hs).strip())), int(float(str(as_).strip()))
                except ValueError:
                    continue
                out.append({"date": str(e.get("gameDate") or e.get("date") or "")[:10], "hid": str(hid), "aid": str(aid),
                            "hs": hs, "as": as_, "comp": e.get("leagueName") or e.get("competitionName") or ""})
    except (AttributeError, TypeError):
        return []
    return out


def team_schedule(path, team_id, season):
    """Partite concluse di una squadra in una stagione (calendario ESPN della squadra in quella competizione).
    Serve per i precedenti degli anni passati. Riga: [data, id casa, id ospite, gol casa, gol ospite]."""
    data, _ = get_json(BASE + path + "/teams/%s/schedule" % team_id, params={"season": season})
    if not data:
        return None
    out = []
    for e in data.get("events") or []:
        try:
            c = (e.get("competitions") or [{}])[0]
            if ((c.get("status") or e.get("status") or {}).get("type") or {}).get("state") != "post":
                continue
            cs = c.get("competitors") or []
            h = next(x for x in cs if x.get("homeAway") == "home")
            a = next(x for x in cs if x.get("homeAway") == "away")
            sc = lambda x: x.get("score", {}).get("value") if isinstance(x.get("score"), dict) else x.get("score")
            hs, as_ = sc(h), sc(a)
            if hs is None or as_ is None:
                continue
            out.append([str(e.get("date") or c.get("date") or "")[:10], str(h.get("id")), str(a.get("id")), int(float(hs)), int(float(as_))])
        except (StopIteration, TypeError, ValueError, AttributeError):
            continue
    return out
