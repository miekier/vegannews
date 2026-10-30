"""Indeling op basis van trefwoorden: relevantie, onderwerpen en soort gebeurtenis."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .tekst import normaliseer

TITEL_GEWICHT = 2
MAX_CATEGORIEEN = 3


@dataclass
class Categorie:
    code: str
    naam: str
    omschrijving: str
    patroon: re.Pattern | None


@dataclass
class Gebeurtenis:
    code: str
    naam: str
    geldt_voor: set[str]
    patroon: re.Pattern | None


@dataclass
class Lexicon:
    categorieen: list[Categorie]
    relevantie: re.Pattern | None
    gebeurtenissen: list[Gebeurtenis] = field(default_factory=list)

    @property
    def codes(self) -> list[str]:
        return [c.code for c in self.categorieen]

    def naam(self, code: str) -> str:
        return next((c.naam for c in self.categorieen if c.code == code), code)


def maak_patroon(trefwoorden: list[str]) -> re.Pattern | None:
    delen = []
    for trefwoord in trefwoorden:
        t = normaliseer(str(trefwoord))
        if not t.strip("*"):
            continue
        links = r"\w*" if t.startswith("*") else r"\b"
        rechts = r"\w*" if t.endswith("*") else r"\b"
        kern = r"\s+".join(re.escape(w) for w in t.strip("*").split())
        delen.append(f"{links}{kern}{rechts}")
    if not delen:
        return None
    return re.compile("|".join(sorted(set(delen), key=len, reverse=True)))


def _alle_trefwoorden(waarde: object) -> list[str]:
    if isinstance(waarde, dict):
        return [str(t) for lijst in waarde.values() for t in (lijst or [])]
    if isinstance(waarde, list):
        return [str(t) for t in waarde]
    return []


def laad_lexicon(pad: Path) -> Lexicon:
    gegevens = yaml.safe_load(pad.read_text(encoding="utf-8")) or {}
    categorieen = []
    for item in gegevens.get("categorieen") or []:
        code = str(item["code"]).strip()
        categorieen.append(Categorie(
            code=code,
            naam=str(item.get("naam") or code),
            omschrijving=str(item.get("omschrijving") or ""),
            patroon=maak_patroon(_alle_trefwoorden(item.get("trefwoorden"))),
        ))
    if not any(c.code == "overig" for c in categorieen):
        categorieen.append(Categorie("overig", "Overig", "Overige berichten", None))
    gebeurtenissen = [
        Gebeurtenis(
            code=str(code),
            naam=str(item.get("naam") or code),
            geldt_voor=set(item.get("geldt_voor") or []),
            patroon=maak_patroon(_alle_trefwoorden(item.get("trefwoorden"))),
        )
        for code, item in (gegevens.get("gebeurtenissen") or {}).items()
    ]
    return Lexicon(categorieen, maak_patroon(_alle_trefwoorden(gegevens.get("relevantie"))), gebeurtenissen)


def _score(patroon: re.Pattern | None, titel: str, rest: str) -> int:
    if patroon is None:
        return 0
    return TITEL_GEWICHT * len(patroon.findall(titel)) + len(patroon.findall(rest))


@dataclass
class Indeling:
    categorieen: list[str]
    gebeurtenis: str
    relevantie: int


def deel_in(lexicon: Lexicon, titel: str, samenvatting: str) -> Indeling:
    t = normaliseer(titel)
    r = normaliseer(samenvatting)
    scores = [(c.code, _score(c.patroon, t, r), i) for i, c in enumerate(lexicon.categorieen) if c.patroon]
    scores.sort(key=lambda s: (-s[1], s[2]))
    gekozen = [code for code, score, _ in scores if score >= TITEL_GEWICHT][:MAX_CATEGORIEEN]
    if not gekozen and scores and scores[0][1] > 0:
        gekozen = [scores[0][0]]
    if not gekozen:
        gekozen = ["overig"]
    return Indeling(gekozen, bepaal_gebeurtenis(lexicon, t, r, gekozen), _score(lexicon.relevantie, t, r))


def bepaal_gebeurtenis(lexicon: Lexicon, titel_n: str, rest_n: str, categorieen: list[str]) -> str:
    beste, beste_score = "", 0
    for g in lexicon.gebeurtenissen:
        if g.geldt_voor and not g.geldt_voor.intersection(categorieen):
            continue
        score = _score(g.patroon, titel_n, rest_n)
        if score > beste_score:
            beste, beste_score = g.code, score
    return beste


def relevantie(lexicon: Lexicon, titel: str, samenvatting: str) -> int:
    return _score(lexicon.relevantie, normaliseer(titel), normaliseer(samenvatting))
