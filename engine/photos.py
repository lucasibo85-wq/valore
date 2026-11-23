"""Foto dei calciatori che ESPN non ha.

Per ogni calciatore delle prossime partite si controlla una volta sola se ESPN ha la foto; se manca si cerca
su TheSportsDB (gratis, chiave pubblica "3") e poi su Wikipedia. Il risultato resta in archivio
(photos.json): l'app riceve solo l'indirizzo dell'immagine, il telefono non fa ricerche.
La ricerca e' per nome (con il controllo della squadra quando possibile): raramente puo' uscire un omonimo.
"""
import datetime as dt
import re
import unicodedata

import requests

from . import net, odds

ESPN = "https://a.espncdn.com/i/headshots/soccer/players/full/%s.png"
TSDB = "https://www.thesportsdb.com/api/v1/json/3/searchplayers.php"
WIKI = "https://%s.wikipedia.org/api/rest_v1/page/summary/%s"
UA = {"User-Agent": "ValoreApp/1.0 (uso personale; statistiche sportive)", "Accept": "application/json"}
FOOT = re.compile(r"footballer|soccer player|calciatore|futbolista|fußballspieler|footballeur|goalkeeper|defender|midfielder|forward", re.I)


def _plain(s):
    return "".join(c for c in unicodedata.normalize("NFD", str(s or "")) if unicodedata.category(c) != "Mn").lower().strip()


def _espn_has(pid):
    try:
        r = requests.head(ESPN % pid, timeout=10, allow_redirects=True, headers={"User-Agent": UA["User-Agent"]})
        net.STATS["requests"] += 1
        return r.status_code == 200 and int(r.headers.get("Content-Length", "1") or 1) > 2000
    except requests.RequestException:
        return None


def _tsdb(name, team):
    data, _ = net.get_json(TSDB, params={"p": name}, tries=2, pause=2.1)
    cands = [p for p in ((data or {}).get("player") or []) if str(p.get("strSport", "")).lower() == "soccer"]
    if not cands:
        return None
    best, score = None, 0.0
    for p in cands:
        img = p.get("strCutout") or p.get("strThumb") or p.get("strRender")
        if not img:
            continue
        sn = 1.0 if _plain(p.get("strPlayer")) == _plain(name) else 0.6
        st = odds.similar(team, p.get("strTeam") or "") if team else 0.0
        sc = sn + st
        if sc > score:
            best, score = img, sc
    # nome uguale e squadra simile, oppure un solo calciatore con quel nome
    if best and (score >= 1.45 or (len(cands) == 1 and score >= 1.0)):
        return best
    return None


def _wiki(name):
    for lang, title in (("en", name + " (footballer)"), ("en", name), ("it", name)):
        data, _ = net.get_json(WIKI % (lang, title.replace(" ", "_")), headers=UA, tries=1, pause=0.5)
        if not data or data.get("type") == "disambiguation":
            continue
        desc = (data.get("description") or "") + " " + (data.get("extract") or "")[:300]
        th = (data.get("thumbnail") or {}).get("source")
        if th and FOOT.search(desc):
            return th
    return None


def fill(players, cache, today, budget=80, log=print):
    """players: calciatori dell'app (dict con id, n = nome, t = squadra).
    Aggiunge p["ph"] quando c'e' una foto non ESPN. cache viene aggiornata (pid -> {s, u, d})."""
    t0 = today.isoformat()
    old = (today - dt.timedelta(days=30)).isoformat()
    done = found = 0
    for p in players:
        pid = str(p["id"])
        c = cache.get(pid)
        if c and (c.get("s") != "none" or c.get("d", "") >= old):
            continue
        if done >= budget:
            break
        done += 1
        has = _espn_has(pid)
        if has is None:
            continue
        if has:
            cache[pid] = {"s": "espn", "d": t0}
            continue
        url = _tsdb(p["n"], p.get("t") or "")
        src = "tsdb"
        if not url:
            url, src = _wiki(p["n"]), "wiki"
        cache[pid] = {"s": src if url else "none", "u": url or "", "d": t0}
        found += 1 if url else 0
    for p in players:
        c = cache.get(str(p["id"]))
        if c and c.get("u"):
            p["ph"] = c["u"]
    if done:
        log("Foto calciatori: controllati %d, trovate %d foto fuori da ESPN" % (done, found))
