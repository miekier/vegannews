"""Tekstbewerking: HTML opschonen, inkorten, normaliseren en taal herkennen."""

from __future__ import annotations

import html
import re
import unicodedata

_SCRIPT_RE = re.compile(r"(?is)<(script|style)\b.*?</\1>")
_BLOK_RE = re.compile(r"(?i)<br\s*/?>|</(p|div|li|h\d)>")
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_WOORD_RE = re.compile(r"[a-zà-öø-ÿ']+")


def zuiver_html(tekst: str | None) -> str:
    """Verwijdert HTML-tags en entiteiten; geeft één regel tekst terug."""
    if not tekst:
        return ""
    tekst = _SCRIPT_RE.sub(" ", tekst)
    tekst = _BLOK_RE.sub(" ", tekst)
    tekst = _TAG_RE.sub(" ", tekst)
    tekst = html.unescape(tekst).replace("\xa0", " ")
    return _WS_RE.sub(" ", tekst).strip()


def kort_in(tekst: str, max_tekens: int = 320) -> str:
    """Kort in tot max_tekens, bij voorkeur na een volledige zin."""
    tekst = tekst.strip()
    if len(tekst) <= max_tekens:
        return tekst
    stuk = tekst[:max_tekens]
    einde = max(stuk.rfind(". "), stuk.rfind("! "), stuk.rfind("? "))
    if einde >= max_tekens * 0.5:
        return stuk[: einde + 1]
    spatie = stuk.rfind(" ")
    stuk = stuk[:spatie] if spatie > 0 else stuk
    return stuk.rstrip(",;:-–— ") + "…"


def zonder_accenten(tekst: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", tekst) if not unicodedata.combining(c))


def normaliseer(tekst: str) -> str:
    """Kleine letters, zonder accenten, koppeltekens als spatie: voor trefwoordherkenning."""
    tekst = zonder_accenten(tekst.casefold()).replace("-", " ").replace("’", "'")
    return _WS_RE.sub(" ", tekst).strip()


def slug(tekst: str, max_lengte: int = 60) -> str:
    tekst = zonder_accenten(tekst.casefold())
    tekst = re.sub(r"[^a-z0-9]+", "-", tekst).strip("-")
    return tekst[:max_lengte].rstrip("-") or "bron"


# Veelvoorkomende functiewoorden per taal. Woorden die in meerdere talen voorkomen
# tellen voor elk van die talen; de onderscheidende woorden beslissen.
STOPWOORDEN: dict[str, frozenset[str]] = {
    "nl": frozenset("""de het een en van in is op te dat die niet met voor zijn er aan ook als bij
        nog naar uit om dan maar werd wordt worden door over meer heeft hebben deze dit wat wel geen
        zo hun haar hij zij ze we wij jullie onze uw tot nieuwe nieuw eerste jaar zegt kan moet""".split()),
    "fr": frozenset("""le la les un une des du de et en est pour dans sur avec par au aux ce cette
        qui que ne pas plus son sa ses leur leurs il elle ils nous vous sont été être a ont fait
        nouveau nouvelle comme mais ou où dont aussi entre selon sans chez""".split()),
    "en": frozenset("""the a an and of to in is for on with that this are was were be by as at from
        it its has have new first how why what who will can after about more than not their your
        our into over says said out up""".split()),
    "de": frozenset("""der die das ein eine und ist mit für auf den dem des nicht von zu im sich
        auch bei aus nach wie wird werden sind hat haben neue neuen erste einen einer noch über
        zum zur vom durch""".split()),
    "es": frozenset("""el la los las un una y de del en es por para con que se su sus al como
        más pero nuevo nueva este esta son""".split()),
    "it": frozenset("""il lo la gli le un una e di del della in è per con che si non al dei
        delle nuovo nuova sono come più""".split()),
    "pt": frozenset("""o a os as um uma e de do da dos das em no na é para com que se não ao
        mais novo nova são como""".split()),
}


def detecteer_taal(tekst: str, standaard: str = "") -> str:
    """Herkent de taal op basis van functiewoorden.

    Bij weinig of twijfelachtig bewijs wint de opgegeven standaardtaal (de taal van de bron).
    """
    woorden = _WOORD_RE.findall(tekst.casefold())
    if len(woorden) < 3:
        return standaard
    scores = {taal: sum(1 for w in woorden if w in lijst) for taal, lijst in STOPWOORDEN.items()}
    beste = max(scores, key=lambda t: scores[t])
    if scores[beste] == 0:
        return standaard
    if standaard and standaard in scores and scores[standaard] >= scores[beste] * 0.75:
        return standaard
    if scores[beste] < 2 and standaard:
        return standaard
    return beste
