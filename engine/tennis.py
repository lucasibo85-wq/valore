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


CLAY = ("roland", "french open", "monte", "madrid", "rome", "roma", "internazionali", "barcelona", "hamburg", "buenos aires",
        "rio", "santiago", "estoril", "geneva", "ginevra", "lyon", "bastad", "gstaad", "kitzbuhel", "umag", "bucharest",
        "marrakech", "houston", "munich", "charleston", "bogota", "rabat", "strasbourg", "palermo", "prague", "parma",
        "cagliari", "iasi", "lausanne", "budapest", "hamburg", "clay")
GRASS = ("wimbledon", "queen", "halle", "hertogenbosch", "eastbourne", "mallorca", "newport", "nottingham", "birmingham",
         "berlin", "bad homburg", "grass")
SLAM = ("australian open", "roland", "french open", "wimbledon", "us open")


def surface(tname):
    t = (tname or "").lower()
    if any(k in t for k in GRASS):
        return "grass"
    if any(k in t for k in CLAY):
        return "clay"
    return "hard"


def best_of(tour, tname):
    t = (tname or "").lower()
    return 5 if tour == "atp" and any(k in t for k in SLAM) else 3


def elo_ratings(matches):
    """Elo generale e per superficie, con fattore K decrescente col numero di partite (stile FiveThirtyEight)."""
    rating = defaultdict(lambda: 1500.0)
    n = defaultdict(int)
    rs = defaultdict(lambda: 1500.0)
    ns = defaultdict(int)
    for m in sorted(matches, key=lambda m: m["date"]):
        if not m.get("winner") or m.get("walkover"):
            continue
        a, b = m["p1"], m["p2"]
        sf = surface(m.get("tname"))
        sa = 1.0 if m["winner"] == a else 0.0
        for R, N, ka_, kb_ in ((rating, n, a, b), (rs, ns, (a, sf), (b, sf))):
            ea = 1 / (1 + 10 ** ((R[kb_] - R[ka_]) / 400))
            R[ka_] += 250 / ((N[ka_] + 5) ** 0.4) * (sa - ea)
            R[kb_] += 250 / ((N[kb_] + 5) ** 0.4) * ((1 - sa) - (1 - ea))
            N[ka_] += 1
            N[kb_] += 1
    return {"all": rating, "n": n, "surf": rs, "ns": ns}


def combined(E, pid, sf):
    ns = E["ns"].get((pid, sf), 0)
    w = 0.5 * ns / (ns + 10)
    return (1 - w) * E["all"].get(pid, 1500.0) + w * E["surf"].get((pid, sf), 1500.0)


def win_prob(ra, rb):
    return 1 / (1 + 10 ** ((rb - ra) / 400))


def set_prob(p_match, bo):
    """Probabilita' di vincere un set coerente con quella di vincere la partita."""
    lo, hi = 0.0, 1.0
    for _ in range(50):
        p = (lo + hi) / 2
        q = 1 - p
        f = p * p * (1 + 2 * q) if bo == 3 else p ** 3 * (1 + 3 * q + 6 * q * q)
        if f < p_match:
            lo = p
        else:
            hi = p
    return (lo + hi) / 2


def markets(p1, n1, n2, bo):
    """Vincente, risultato esatto in set, totale set, handicap set."""
    p = set_prob(p1, bo)
    q = 1 - p
    out = []

    def add(k, g, label, pr):
        out.append([k, g, label, round(max(0.001, min(0.999, pr)), 4)])
    add("w1", "Vincente", n1, p1)
    add("w2", "Vincente", n2, 1 - p1)
    if bo == 3:
        sc = {"2-0": p * p, "2-1": 2 * p * p * q, "1-2": 2 * p * q * q, "0-2": q * q}
        for k, v in sc.items():
            add("s" + k, "Risultato esatto (set)", k, v)
        add("ts:o2.5", "Totale set", "3 set (over 2.5)", sc["2-1"] + sc["1-2"])
        add("ts:u2.5", "Totale set", "2 set (under 2.5)", sc["2-0"] + sc["0-2"])
        add("hs1:-1.5", "Handicap set", "%s -1.5" % n1, sc["2-0"])
        add("hs2:+1.5", "Handicap set", "%s +1.5 (vince almeno un set)" % n2, 1 - sc["2-0"])
        add("hs2:-1.5", "Handicap set", "%s -1.5" % n2, sc["0-2"])
        add("hs1:+1.5", "Handicap set", "%s +1.5 (vince almeno un set)" % n1, 1 - sc["0-2"])
    else:
        sc = {"3-0": p ** 3, "3-1": 3 * p ** 3 * q, "3-2": 6 * p ** 3 * q * q,
              "2-3": 6 * q ** 3 * p * p, "1-3": 3 * q ** 3 * p, "0-3": q ** 3}
        for k, v in sc.items():
            add("s" + k, "Risultato esatto (set)", k, v)
        add("ts:o3.5", "Totale set", "Over 3.5 set", 1 - sc["3-0"] - sc["0-3"])
        add("ts:u3.5", "Totale set", "Under 3.5 set", sc["3-0"] + sc["0-3"])
        add("ts:o4.5", "Totale set", "Over 4.5 set (5 set)", sc["3-2"] + sc["2-3"])
        add("ts:u4.5", "Totale set", "Under 4.5 set", 1 - sc["3-2"] - sc["2-3"])
        add("hs1:-1.5", "Handicap set", "%s -1.5" % n1, sc["3-0"] + sc["3-1"])
        add("hs2:+1.5", "Handicap set", "%s +1.5" % n2, 1 - sc["3-0"] - sc["3-1"])
        add("hs2:-1.5", "Handicap set", "%s -1.5" % n2, sc["0-3"] + sc["1-3"])
        add("hs1:+1.5", "Handicap set", "%s +1.5" % n1, 1 - sc["0-3"] - sc["1-3"])
    return out


def build(app, matches, upcoming):
    """app['tennis']['matches'] con probabilita' Elo (superficie), set, forma e precedenti."""
    by_tour = defaultdict(list)
    for m in matches:
        by_tour[m["tour"]].append(m)
    ratings = {t: elo_ratings(ms) for t, ms in by_tour.items()}
    recent = defaultdict(list)
    h2h = defaultdict(lambda: [0, 0])
    for m in sorted(matches, key=lambda m: m["date"], reverse=True):
        if m.get("winner"):
            for pid in (m["p1"], m["p2"]):
                if len(recent[pid]) < 10:
                    recent[pid].append(1 if m["winner"] == pid else 0)
            key = tuple(sorted((m["p1"], m["p2"])))
            h2h[key][0 if m["winner"] == key[0] else 1] += 1
    for m in upcoming:
        E = ratings.get(m["tour"])
        sf = surface(m["tname"])
        bo = best_of(m["tour"], m["tname"])
        if E:
            ra, rb = combined(E, m["p1"], sf), combined(E, m["p2"], sf)
            na, nb = E["n"].get(m["p1"], 0), E["n"].get(m["p2"], 0)
        else:
            ra = rb = 1500.0
            na = nb = 0
        pr1 = win_prob(ra, rb)
        key = tuple(sorted((m["p1"], m["p2"])))
        hh = h2h.get(key, [0, 0])
        w1 = hh[0] if key[0] == m["p1"] else hh[1]
        app["tennis"]["matches"].append({
            "id": m["gid"], "t": m["date"], "tour": m["tour"].upper(), "tn": m["tname"],
            "p1": m["n1"], "p2": m["n2"], "id1": m["p1"], "id2": m["p2"],
            "e1": round(ra), "e2": round(rb), "n1": na, "n2": nb, "sf": sf, "bo": bo,
            "pr1": round(pr1, 4), "h2h": [w1, sum(hh) - w1],
            "f1": recent.get(m["p1"], []), "f2": recent.get(m["p2"], []),
            "mk": markets(pr1, m["n1"], m["n2"], bo),
        })
