"""Archivio dei dati scaricati: file CSV/JSON nella cartella data/."""
import csv
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.environ.get("VALORE_DATA") or os.path.join(ROOT, "data")

NBA_COLS = ["gid", "date", "team", "opp", "home", "pid", "name", "pos", "starter",
            "min", "pts", "reb", "ast", "stl", "blk", "fg3m", "tov"]
SOC_COLS = ["gid", "date", "league", "team", "opp", "home", "pid", "name", "pos", "starter",
            "min", "shots", "sot", "fc", "fs", "yc", "rc", "g", "a"]
MATCH_COLS = ["sport", "league", "gid", "date", "hid", "aid", "hs", "as", "referee",
              "hs1", "as1", "hc", "ac", "hk", "ak", "ts"]
# colonne di testo: tutte le altre sono numeriche
TEXT = {"gid", "date", "team", "opp", "pid", "name", "pos", "league", "sport", "referee", "hid", "aid",
        "p1", "p2", "tour", "winner", "round", "tname"}


def path(name):
    os.makedirs(DATA, exist_ok=True)
    return os.path.join(DATA, name)


def read_csv(name):
    p = path(name)
    if not os.path.exists(p):
        return []
    out = []
    with open(p, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            for k in list(r.keys()):
                if k not in TEXT and r[k] not in (None, ""):
                    try:
                        r[k] = float(r[k])
                    except ValueError:
                        r[k] = 0.0
            out.append(r)
    return out


def _fmt(v):
    if isinstance(v, float):
        return ("%.2f" % v).rstrip("0").rstrip(".") if v != int(v) else str(int(v))
    return v


def write_csv(name, rows, cols):
    p = path(name)
    tmp = p + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: _fmt(r.get(k, "")) for k in cols})
    os.replace(tmp, p)


def read_json(name, default):
    p = path(name)
    if not os.path.exists(p):
        return default
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(name, obj, target=None, compact=False):
    p = target or path(name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        if compact:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)
