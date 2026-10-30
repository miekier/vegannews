"""Herkennen van dubbele berichten: dezelfde URL of (bijna) dezelfde titel."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .tekst import STOPWOORDEN, normaliseer

VOLG_PARAMETERS = re.compile(
    r"^(utm_.*|fbclid|gclid|dclid|mc_cid|mc_eid|igshid|ref|ref_src|ocid|cmpid|xtor|at_medium|at_campaign|"
    r"_ga|yclid|wt_mc|s_cid|feature|rss)$",
    re.I,
)
_ALLE_STOPWOORDEN = frozenset().union(*STOPWOORDEN.values())
DREMPEL = 0.6
MIN_WOORDEN = 4


def canonieke_url(url: str) -> str:
    deel = urlparse(url.strip())
    host = deel.netloc.lower().removeprefix("www.")
    query = [(k, v) for k, v in parse_qsl(deel.query, keep_blank_values=True) if not VOLG_PARAMETERS.match(k)]
    pad = deel.path.rstrip("/") or "/"
    return urlunparse(("https", host, pad, "", urlencode(query), ""))


def bericht_id(url: str) -> str:
    return hashlib.sha1(canonieke_url(url).encode("utf-8")).hexdigest()[:16]


def titel_sleutel(titel: str) -> frozenset[str]:
    woorden = re.findall(r"\w+", normaliseer(titel))
    return frozenset(w for w in woorden if len(w) > 2 and w not in _ALLE_STOPWOORDEN)


def gelijkend(a: frozenset[str], b: frozenset[str]) -> bool:
    if len(a) < MIN_WOORDEN or len(b) < MIN_WOORDEN:
        return a == b and len(a) >= 2
    return len(a & b) / len(a | b) >= DREMPEL
