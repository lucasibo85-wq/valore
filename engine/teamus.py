"""Mercati di squadra per NBA, NFL e MLB: vincente, handicap, totali, totali di squadra.

Punti/run attesi per squadra dal modello attacco-difesa (con piu' peso alle partite recenti).
- NBA e NFL: margine e totale distribuiti in modo normale (deviazioni tipiche dello sport).
- MLB: run di ogni squadra con binomiale negativa, partita intera con supplementari ripartiti.
Chiavi: ml1/ml2 (vincente), hsp:L / asp:L (handicap casa/ospite), o:L / u:L (totale),
ho:L / hu:L / ao:L / au:L (totale casa/ospite).
"""
import math

from . import models

SD = {"nba": (12.5, 18.0, 11.0), "nfl": (13.5, 10.5, 7.5)}  # margine, totale, totale squadra


def _phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _half(x):
    """Linea .5 piu' vicina."""
    return math.floor(x) + 0.5


def _fmt(x):
    return ("%g" % x).replace(".0", "") if float(x).is_integer() else "%g" % x


def normal_markets(sport, mh, ma, home_line=None, total_line=None):
    sdm, sdt, sdtt = SD[sport]
    out = []

    def add(k, g, label, p):
        out.append([k, g, label, round(max(0.001, min(0.999, p)), 4)])

    margin = mh - ma
    ph = 1 - _phi(-margin / sdm)
    g = "Vincente"
    add("ml1", g, "1 · casa", ph)
    add("ml2", g, "2 · ospite", 1 - ph)
    g = "Handicap"
    center = home_line if home_line is not None else -margin
    center = _half(center) if float(center).is_integer() else center
    steps = (-7, -3, 0, 3, 7) if sport == "nfl" else (-8, -4, 0, 4, 8)
    for d in steps:
        L = center + d
        pc = 1 - _phi((-L - margin) / sdm)  # la casa copre: margine + L > 0
        add("hsp:%g" % L, g, "Casa %s%g" % ("+" if L > 0 else "", L), pc)
        add("asp:%g" % (-L), g, "Ospite %s%g" % ("+" if -L > 0 else "", -L), 1 - pc)
    g = "Totale punti"
    tot = mh + ma
    c = total_line if total_line is not None else _half(tot)
    c = _half(c) if float(c).is_integer() else c
    tsteps = (0, -3, 3, -6, 6) if sport == "nfl" else (0, -5, 5, -10, 10)
    for d in sorted(tsteps):
        L = c + d
        po = 1 - _phi((L - tot) / sdt)
        add("o:%g" % L, g, "Over %g" % L, po)
        add("u:%g" % L, g, "Under %g" % L, 1 - po)
    for side, mu, lab in (("h", mh, "Casa"), ("a", ma, "Ospite")):
        g = "Punti " + lab.lower()
        cc = _half(mu)
        for d in ((-3, 0, 3) if sport == "nfl" else (-5, 0, 5)):
            L = cc + d
            po = 1 - _phi((L - mu) / sdtt)
            add("%so:%g" % (side, L), g, "%s over %g" % (lab, L), po)
            add("%su:%g" % (side, L), g, "%s under %g" % (lab, L), 1 - po)
    return out


def _nb_pmf(mu, r, n=26):
    out = []
    prev = 0.0
    for k in range(n):
        c = models.nb_cdf(k, mu, r)
        out.append(c - prev)
        prev = c
    return out


def mlb_markets(mh, ma, total_line=None, r=4.0):
    ph_ = _nb_pmf(mh, r)
    pa_ = _nb_pmf(ma, r)
    out = []

    def add(k, g, label, p):
        out.append([k, g, label, round(max(0.001, min(0.999, p)), 4)])

    win = draw = 0.0
    diff = {}
    tot = {}
    for i, a in enumerate(ph_):
        for j, b in enumerate(pa_):
            p = a * b
            if i > j:
                win += p
            elif i == j:
                draw += p
            diff[i - j] = diff.get(i - j, 0) + p
            tot[i + j] = tot.get(i + j, 0) + p
    p_home = win + draw * (mh / (mh + ma) if mh + ma > 0 else 0.5) * 1.04  # extra inning, lieve vantaggio casa
    p_home = min(0.99, p_home)
    g = "Vincente"
    add("ml1", g, "1 · casa", p_home)
    add("ml2", g, "2 · ospite", 1 - p_home)
    g = "Run line"
    ge2 = sum(p for d, p in diff.items() if d >= 2)
    le_2 = sum(p for d, p in diff.items() if d <= -2)
    add("hsp:-1.5", g, "Casa -1.5", ge2)
    add("asp:1.5", g, "Ospite +1.5", 1 - ge2)
    add("asp:-1.5", g, "Ospite -1.5", le_2)
    add("hsp:1.5", g, "Casa +1.5", 1 - le_2)
    g = "Totale run"
    c = total_line if total_line is not None else _half(mh + ma)
    c = _half(c) if float(c).is_integer() else c
    for d in (-1, 0, 1):
        L = c + d
        po = sum(p for t, p in tot.items() if t > L)
        add("o:%g" % L, g, "Over %g" % L, po)
        add("u:%g" % L, g, "Under %g" % L, 1 - po)
    for side, arr, lab in (("h", ph_, "Casa"), ("a", pa_, "Ospite")):
        g = "Run " + lab.lower()
        mu = mh if side == "h" else ma
        for L in (_half(mu) - 1, _half(mu)):
            po = sum(p for k, p in enumerate(arr) if k > L)
            add("%so:%g" % (side, L), g, "%s over %g" % (lab, L), po)
            add("%su:%g" % (side, L), g, "%s under %g" % (lab, L), 1 - po)
    return out


def eval_key(k, s):
    """Esito per le chiavi sopra. s = [punti casa, punti ospite]."""
    if not s or s[0] in (None, "") or s[1] in (None, ""):
        return None
    h, a = float(s[0]), float(s[1])
    if k == "ml1":
        return "void" if h == a else h > a
    if k == "ml2":
        return "void" if h == a else a > h
    if ":" not in k:
        return None
    pre, L = k.split(":")
    L = float(L)

    def cmp(x, y):
        return "void" if x == y else x > y
    if pre == "hsp":
        return cmp(h + L, a)
    if pre == "asp":
        return cmp(a + L, h)
    if pre == "o":
        return cmp(h + a, L)
    if pre == "u":
        return cmp(L, h + a)
    if pre in ("ho", "hu", "ao", "au"):
        v = h if pre[0] == "h" else a
        return cmp(v, L) if pre[1] == "o" else cmp(L, v)
    return None
