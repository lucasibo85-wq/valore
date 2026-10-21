"""Quote automatiche da The Odds API (facoltative, piano gratuito 500 crediti/mese)."""
import os
import re
import unicodedata
from collections import defaultdict

from .net import get_json

BASE = "https://api.the-odds-api.com/v4/sports/"
SOCCER_KEYS = {
    "ita.1": "soccer_italy_serie_a", "ita.2": "soccer_italy_serie_b", "eng.1": "soccer_epl",
    "eng.2": "soccer_efl_champ", "esp.1": "soccer_spain_la_liga", "ger.1": "soccer_germany_bundesliga",
    "fra.1": "soccer_france_ligue_one", "por.1": "soccer_portugal_primeira_liga",
    "ned.1": "soccer_netherlands_eredivisie", "bel.1": "soccer_belgium_first_div",
    "tur.1": "soccer_turkey_super_league", "sco.1": "soccer_spl",
    "uefa.champions": "soccer_uefa_champs_league", "uefa.europa": "soccer_uefa_europa_league",
    "uefa.europa.conf": "soccer_uefa_europa_conference_league", "usa.1": "soccer_usa_mls",
    "bra.1": "soccer_brazil_campeonato", "arg.1": "soccer_argentina_primera_division",
    "mex.1": "soccer_mexico_ligamx",
}
NBA_MARKET_MAP = {
    "player_points": "pts", "player_rebounds": "reb", "player_assists": "ast",
    "player_steals": "stl", "player_blocks": "blk", "player_threes": "fg3m",
    "player_turnovers": "tov", "player_points_rebounds_assists": "pra",
    "player_points_rebounds": "pr", "player_points_assists": "pa",
    "player_rebounds_assists": "ra", "player_blocks_steals": "sb",
}
STOP = {"fc", "cf", "ac", "as", "ssc", "afc", "sc", "calcio", "club", "de", "the", "cd", "sd",
        "ud", "rc", "rcd", "fk", "sk", "bk", "if", "us", "1"}


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return [t for t in s.split() if t and t not in STOP]


def similar(a, b):
    ta, tb = set(norm(a)), set(norm(b))
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    if inter == 0:
        # prefissi (es. "inter" / "internazionale")
        inter = sum(1 for x in ta for y in tb if len(x) >= 4 and (x.startswith(y) or y.startswith(x)))
    return inter / max(len(ta), len(tb))


def key():
    return os.environ.get("ODDS_API_KEY", "").strip()


def _remaining(headers):
    try:
        return int(float(headers.get("x-requests-remaining", "")))
    except (TypeError, ValueError):
        return None


def soccer_h2h(league, region):
    """Migliori quote 1X2 per le partite di una lega. Costo: 1 credito per regione."""
    sk = SOCCER_KEYS.get(league)
    if not sk or not key():
        return [], None
    data, h = get_json(BASE + sk + "/odds", params={
        "apiKey": key(), "regions": region, "markets": "h2h", "oddsFormat": "decimal"})
    out = []
    for ev in data or []:
        best = {"1": (0, ""), "X": (0, ""), "2": (0, "")}
        for bk in ev.get("bookmakers", []):
            for mk in bk.get("markets", []):
                if mk.get("key") != "h2h":
                    continue
                for o in mk.get("outcomes", []):
                    side = "X" if o["name"] == "Draw" else ("1" if o["name"] == ev["home_team"] else "2")
                    if o["price"] > best[side][0]:
                        best[side] = (o["price"], bk.get("title", ""))
        out.append({"home": ev["home_team"], "away": ev["away_team"], "time": ev.get("commence_time", ""),
                    "o1": best["1"][0], "ox": best["X"][0], "o2": best["2"][0],
                    "book": best["1"][1]})
    return out, _remaining(h)


def nba_events():
    if not key():
        return []
    data, _ = get_json(BASE + "basketball_nba/events", params={"apiKey": key()})
    return data or []


def nba_props(event_id, markets, region):
    """Linee e migliori quote over/under per giocatore. Costo: mercati x regioni."""
    data, h = get_json(BASE + "basketball_nba/events/%s/odds" % event_id, params={
        "apiKey": key(), "regions": region, "markets": ",".join(markets), "oddsFormat": "decimal"})
    if not data:
        return [], _remaining(h)
    lines = defaultdict(lambda: {"over": (0, ""), "under": (0, ""), "books": 0})
    for bk in data.get("bookmakers", []):
        for mk in bk.get("markets", []):
            m = NBA_MARKET_MAP.get(mk.get("key"))
            if not m:
                continue
            for o in mk.get("outcomes", []):
                player = o.get("description") or ""
                point = o.get("point")
                if point is None or not player:
                    continue
                d = lines[(player, m, float(point))]
                side = "over" if o.get("name", "").lower() == "over" else "under"
                if o["price"] > d[side][0]:
                    d[side] = (o["price"], bk.get("title", ""))
                if side == "over":
                    d["books"] += 1
    # per ogni giocatore/mercato tiene la linea quotata da piu' bookmaker
    best = {}
    for (player, m, point), d in lines.items():
        k = (player, m)
        if k not in best or d["books"] > best[k][1]["books"]:
            best[k] = (point, d)
    out = []
    for (player, m), (point, d) in best.items():
        if d["over"][0] and d["under"][0]:
            out.append({"player": player, "m": m, "line": point, "over": d["over"][0],
                        "under": d["under"][0], "book": d["over"][1]})
    return out, _remaining(h)
