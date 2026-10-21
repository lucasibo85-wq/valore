"""Tennis (ATP e WTA): risultati da ESPN e modello Elo per il vincente della partita."""
import datetime as dt
import math
from collections import defaultdict

from .espn import BASE, _num
from .net import get_json

TOURS = {"atp": "tennis/atp", "wta": "tennis/wta"}
COLS = ["gid", "date", "tour", "p1", "p2", "n1", "n2", "winner", "sets1", "sets2", "tname"]


def _athlete(c):
    a = c.get("athlete") or {}
    if not a and c.get("roster"):
        a = (c["roster"].get("athletes") or [{}])[0] if isinstance(c["roster"], dict) else {}
    return str(a.get("id") or c.get("id") or ""), a.get("displayName") or a.get("shortName") or c.get("displayName") or "?"


def scoreboard(tour, date):
    """Partite di singolare (concluse e in programma) di una giornata."""
    data, _ = get_json(BASE + TOURS[tour] + "/scoreboard", params={"dates": date.strftime("%Y%m%d")})
    if not data:
        return None
    out = []
    for ev in data.get("events", []) or []:
        tname = ev.get("name") or ev.get("shortName") or ""
        groups = ev.get("groupings") or [{"grouping": {"displayName": "Singles"}, "competitions": ev.get("competitions") or []}]
        for g in groups:
            gname = str(((g.get("grouping") or {}).get("displayName") or (g.get("grouping") or {}).get("slug") or "")).lower()
            if "double" in gname or "mixed" in gname:
                continue
            for comp in g.get("competitions", []) or []:
                cs = comp.get("competitors") or []
                if len(cs) != 2:
                    continue
                if any((c.get("type") == "team") or ("/" in str((c.get("athlete") or {}).get("displayName", ""))) for c in cs):
                    continue
                st = ((comp.get("status") or {}).get("type") or {})
                (id1, n1), (id2, n2) = _athlete(cs[0]), _athlete(cs[1])
                if not id1 or not id2:
                    continue
                winner = ""
                if st.get("completed"):
                    if cs[0].get("winner"):
                        winner = id1
                    elif cs[1].get("winner"):
                        winner = id2
                sets = [sum(1 for ls in (c.get("linescores") or []) if ls.get("winner")) for c in cs]
                out.append({
                    "gid": str(comp.get("id")), "date": (comp.get("date") or comp.get("startDate") or ev.get("date") or "")[:16],
                    "tour": tour, "p1": id1, "p2": id2, "n1": n1, "n2": n2, "winner": winner,
                    "sets1": sets[0], "sets2": sets[1], "tname": tname,
                    "state": st.get("state", "pre"), "completed": bool(st.get("completed")),
                    "walkover": "walkover" in str(st.get("description", "")).lower() or "w/o" in str(st.get("detail", "")).lower(),
                })
    return out


def elo_ratings(matches):
    """Elo con fattore K decrescente col numero di partite (stile FiveThirtyEight)."""
    rating = defaultdict(lambda: 1500.0)
    n = defaultdict(int)
    for m in sorted(matches, key=lambda m: m["date"]):
        if not m.get("winner") or m.get("walkover"):
            continue
        a, b = m["p1"], m["p2"]
        ea = 1 / (1 + 10 ** ((rating[b] - rating[a]) / 400))
        sa = 1.0 if m["winner"] == a else 0.0
        ka = 250 / ((n[a] + 5) ** 0.4)
        kb = 250 / ((n[b] + 5) ** 0.4)
        rating[a] += ka * (sa - ea)
        rating[b] += kb * ((1 - sa) - (1 - ea))
        n[a] += 1
        n[b] += 1
    return rating, n


def win_prob(ra, rb):
    return 1 / (1 + 10 ** ((rb - ra) / 400))


def build(app, matches, upcoming):
    """app['tennis']['matches'] con probabilita' Elo e forma recente."""
    by_tour = defaultdict(list)
    for m in matches:
        by_tour[m["tour"]].append(m)
    ratings = {t: elo_ratings(ms) for t, ms in by_tour.items()}
    recent = defaultdict(list)
    for m in sorted(matches, key=lambda m: m["date"], reverse=True):
        if m.get("winner"):
            for pid in (m["p1"], m["p2"]):
                if len(recent[pid]) < 10:
                    recent[pid].append(1 if m["winner"] == pid else 0)
    for m in upcoming:
        r, n = ratings.get(m["tour"], ({}, {}))
        ra, rb = r.get(m["p1"], 1500.0), r.get(m["p2"], 1500.0)
        na, nb = n.get(m["p1"], 0), n.get(m["p2"], 0)
        app["tennis"]["matches"].append({
            "id": m["gid"], "t": m["date"], "tour": m["tour"].upper(), "tn": m["tname"],
            "p1": m["n1"], "p2": m["n2"], "id1": m["p1"], "id2": m["p2"],
            "e1": round(ra), "e2": round(rb), "n1": na, "n2": nb,
            "pr1": round(win_prob(ra, rb), 4),
            "f1": recent.get(m["p1"], []), "f2": recent.get(m["p2"], []),
        })
