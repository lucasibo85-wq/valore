"""Richieste HTTP con pause e tentativi ripetuti."""
import time
import requests

_session = requests.Session()
_session.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json",
})
PAUSE = 0.3
_last = [0.0]
STATS = {"requests": 0, "errors": 0}


def get_json(url, params=None, headers=None, tries=3, pause=None):
    """GET che restituisce JSON oppure None. Non solleva eccezioni."""
    p = PAUSE if pause is None else pause
    for attempt in range(tries):
        wait = p - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        STATS["requests"] += 1
        try:
            r = _session.get(url, params=params, headers=headers, timeout=25)
            if r.status_code == 200:
                return r.json(), r.headers
            if r.status_code in (400, 401, 403, 404, 422):
                STATS["errors"] += 1
                return None, r.headers
        except (requests.RequestException, ValueError):
            pass
        time.sleep(2 * (attempt + 1))
    STATS["errors"] += 1
    return None, {}
