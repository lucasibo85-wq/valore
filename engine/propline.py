"""Prop dei giocatori NBA da PropLine (piano gratuito: 1.000 richieste al giorno, nessuna carta).

Una richiesta per partita restituisce tutti i mercati e tutti i bookmaker (tra cui Lottomatica e
William Hill Italia). Formato simile a The Odds API: bookmakers -> markets -> outcomes
(name "Over"/"Under", description = giocatore, point = linea, price = quota americana).
Chiave in GitHub: secret PROPLINE_API_KEY.
"""
import os
from collections import defaultdict

from . import odds
from .net import get_json

BASE = "https://api.prop-line.com/v1/sports/"
NBA = "basketball_nba"
# mercati richiesti (se il servizio ne rifiuta qualcuno si riprova con quelli principali)
NBA_MARKETS = ["player_points", "player_rebounds", "player_assists", "player_threes", "player_blocks", "player_steals",
               "player_turnovers", "player_points_rebounds_assists", "player_points_rebounds", "player_points_assists",
               "player_rebounds_assists", "player_blocks_steals", "double_double", "triple_double"]
NBA_CORE = ["player_points", "player_rebounds", "player_assists", "player_threes", "player_points_rebounds_assists"]
MAP = dict(odds.NBA_MARKET_MAP)
MAP.update({"double_double": "dd", "triple_double": "tdd"})
NFL = "americanfootball_nfl"
NFL_MAP = {"player_pass_yds": "pass_yds", "player_pass_tds": "pass_td", "player_pass_completions": "pass_cmp",
           "player_pass_attempts": "pass_att", "player_pass_interceptions": "int", "player_rush_yds": "rush_yds",
           "player_rush_attempts": "rush_att", "player_receptions": "rec", "player_reception_yds": "rec_yds",
           "player_rush_reception_yds": "rr_yds", "player_pass_rush_yds": "pr_yds", "player_anytime_td": "td"}
NFL_CORE = ["player_pass_yds", "player_rush_yds", "player_reception_yds", "player_receptions", "player_anytime_td"]
MLB = "baseball_mlb"
MLB_MAP = {"batter_hits": "h", "batter_hits_runs_rbis": "hrr", "batter_runs_scored": "r", "batter_rbis": "rbi",
           "batter_home_runs": "hr", "batter_walks": "bb", "batter_strikeouts": "so", "pitcher_strikeouts": "p_k",
           "pitcher_outs": "outs", "pitcher_earned_runs": "er", "pitcher_hits_allowed": "p_h", "pitcher_walks": "p_bb"}
MLB_CORE = ["batter_hits", "batter_home_runs", "batter_total_bases", "pitcher_strikeouts"]
SOC_MAP = dict(odds.SOCCER_PROP_MAP)
SOC_CORE = ["player_shots_on_target", "player_goal_scorer_anytime"]
# per sport: chiave PropLine, mercati richiesti, mercati di riserva, traduzione nei mercati dell'app
SPORTS = {"nba": (NBA, NBA_MARKETS, NBA_CORE, MAP), "nfl": (NFL, list(NFL_MAP), NFL_CORE, NFL_MAP),
          "mlb": (MLB, list(MLB_MAP), MLB_CORE, MLB_MAP)}
SOCCER = (list(SOC_MAP), SOC_CORE, SOC_MAP)
ITALIAN = ("lottomatica", "williamhill_it", "snai", "eurobet", "sisal", "goldbet", "bet365_it", "betflag", "planetwin365")
STATS = {"requests": 0, "used_today": None}


def key():
    return os.environ.get("PROPLINE_API_KEY", "").strip()


def _get(path, params=None):
    p = dict(params or {})
    p["apiKey"] = key()
    data, h = get_json(BASE + path, params=p, tries=2)
    STATS["requests"] += 1
    try:
        STATS["used_today"] = int((h or {}).get("X-Daily-Used") or (h or {}).get("x-daily-used"))
    except (TypeError, ValueError):
        pass
    return data


def events(sport=NBA):
    """Partite in programma: [{id, home_team, away_team, commence_time}]"""
    if not key():
        return []
    return _get(sport + "/events") or []


def _dec(price):
    """Quota americana -> decimale (accetta anche quote gia' decimali)."""
    try:
        x = float(price)
    except (TypeError, ValueError):
        return None
    if 1.0 < x < 30 and not float(x).is_integer():
        return round(x, 3)
    if x >= 100:
        return round(1 + x / 100, 3)
    if x <= -100:
        return round(1 + 100 / -x, 3)
    return None


def sports():
    """Elenco degli sport/campionati disponibili su PropLine (chiavi)."""
    if not key():
        return []
    d, h = get_json(BASE.rstrip("/"), params={"apiKey": key()}, tries=2)
    STATS["requests"] += 1
    if isinstance(d, list):
        return [x.get("key") for x in d if isinstance(x, dict) and x.get("key")]
    return []


def event_props(event_id, sport=NBA, markets=None, core=None, mapping=None):
    """Linee per giocatore e mercato: la linea con piu' bookmaker, la quota migliore, la quota di un
    bookmaker italiano se c'e', e la probabilita' "giusta" (media senza margine dei bookmaker)."""
    markets, core, mp = markets or NBA_MARKETS, core or NBA_CORE, mapping or MAP
    data = _get("%s/events/%s/odds" % (sport, event_id), {"markets": ",".join(markets), "includePregameOnly": "true"})
    if data is None:
        data = _get("%s/events/%s/odds" % (sport, event_id), {"markets": ",".join(core), "includePregameOnly": "true"})
    if not data:
        return []
    lines = defaultdict(lambda: {"over": (0, ""), "under": (0, ""), "books": set(), "pairs": defaultdict(dict), "it": None})
    for bk in data.get("bookmakers", []) or []:
        bkey = bk.get("key") or bk.get("title") or ""
        for mk in bk.get("markets", []) or []:
            m = mp.get(mk.get("key"))
            if not m:
                continue
            for o in mk.get("outcomes", []) or []:
                player = o.get("description") or ""
                name = (o.get("name") or "").lower()
                if not player:
                    continue
                pr = _dec(o.get("price"))
                if not pr:
                    continue
                point = o.get("point")
                point = 0.5 if point is None else float(point)
                side = "under" if name in ("under", "no") else "over"
                d = lines[(player, m, point)]
                if pr > d[side][0]:
                    d[side] = (pr, bk.get("title") or bkey)
                d["pairs"][bkey][side] = pr
                d["books"].add(bkey)
                if bkey in ITALIAN and side == "over":
                    d["it"] = (pr, bk.get("title") or bkey)
    best = {}
    for (player, m, point), d in lines.items():
        k = (player, m)
        score = (1 if d["it"] else 0, len(d["books"]))  # prima la linea dei bookmaker italiani, poi la piu' diffusa
        if k not in best or score > best[k][0]:
            best[k] = (score, point, d)
    out = []
    for (player, m), (_, point, d) in best.items():
        if not d["over"][0]:
            continue
        nv = []
        for pr in d["pairs"].values():
            if pr.get("over", 0) > 1 and pr.get("under", 0) > 1:
                a, b = 1 / pr["over"], 1 / pr["under"]
                nv.append(a / (a + b))
        fair = sorted(nv)[len(nv) // 2] if nv else None
        over, book = d["it"] if d["it"] else d["over"]
        out.append({"player": player, "m": m, "line": point, "over": over, "under": d["under"][0] or None,
                    "book": book, "fair": round(fair, 4) if fair is not None else None, "nb": len(nv)})
    return out
