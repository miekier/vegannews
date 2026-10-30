"""Bepaalt of een bericht over België gaat (nationaal) of over het buitenland, en waar."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

DATA = Path(__file__).resolve().parent / "data"
MAX_WOORDEN = 4
BRON_GEWICHT = 1.5
# Na deze woorden is een dubbelzinnige plaatsnaam ("Boom", "Spa") zeker een plaats.
VOORZETSELS = {"in", "te", "uit", "naar", "nabij", "vanuit", "rond", "à", "au", "près", "vers", "dans",
               "aus", "nach", "bei", "near", "from"}
# Belgische termen die geen plaats zijn (gewesten, instellingen, bijvoeglijke naamwoorden).
BELGISCHE_TERMEN = [
    "België", "Belgique", "Belgien", "Belgium", "Vlaanderen", "Flandre", "Flandres", "Flanders", "Flandern",
    "Wallonië", "Wallonie", "Wallonia", "Wallonien", "Vlaams", "Vlaamse", "Flemish", "flamand", "flamande",
    "flamands", "flamandes", "Waals", "Waalse", "Walloon", "wallon", "wallonne", "wallons", "Brusselse",
    "bruxellois", "bruxelloise", "Oost-Vlaanderen", "West-Vlaanderen", "Vlaams-Brabant", "Waals-Brabant",
    "Brabant wallon", "Henegouwen", "Hainaut", "FAVV", "AFSCA", "Sciensano", "VRT", "RTBF", "Kempen",
    "Vlaams Parlement", "Vlaamse regering", "Kamer van volksvertegenwoordigers", "Fédération Wallonie-Bruxelles",
]
GENERIEKE_TLD = {"co", "io", "ai", "me", "tv", "fm", "ly", "to", "cc", "ws", "gg", "la", "eu"}
_TOKEN_RE = re.compile(r"[^\W\d_](?:[\w'’\-]*[^\W_])?")


@dataclass
class Treffer:
    naam: str
    land: str
    gewicht: float
    in_titel: bool
    positie: int
    gewest: str = ""
    is_plaats: bool = False


@dataclass
class GeoAnalyse:
    be: float = 0.0
    buitenland: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    plaats: str = ""
    gewest: str = ""
    buitenlandse_plaats: dict[str, str] = field(default_factory=dict)


@dataclass
class Regio:
    regio: str      # BE of INT
    land: str       # landcode of ""
    plaats: str
    gewest: str


def _tokens(tekst: str) -> list[tuple[str, int]]:
    tekst = tekst.replace("U.S.A.", "USA").replace("U.S.", "US").replace("U.K.", "UK")
    return [(m.group(0), m.start()) for m in _TOKEN_RE.finditer(tekst)]


def land_van_url(url: str) -> str:
    host = urlparse(url).netloc.lower().split(":")[0]
    if not host:
        return ""
    if host.endswith(".co.uk") or host.endswith(".uk"):
        return "GB"
    tld = host.rsplit(".", 1)[-1]
    if len(tld) == 2 and tld not in GENERIEKE_TLD:
        return tld.upper()
    return ""


class Geo:
    def __init__(self, map_: Path = DATA):
        plaatsen = json.loads((map_ / "plaatsen_be.json").read_text(encoding="utf-8"))
        self._plaatsen = plaatsen["plaatsen"]
        self._plaatsnamen: dict[str, tuple[int, int]] = {k: (v[0], v[1]) for k, v in plaatsen["namen"].items()}
        landen = json.loads((map_ / "landen.json").read_text(encoding="utf-8"))
        self.landnamen = {code: info["naam"] for code, info in landen["landen"].items()}
        self._exact: dict[str, tuple[str, float, bool]] = {}     # tekst -> (land, gewicht, is_stad)
        self._ongevoelig: dict[str, tuple[str, float, bool]] = {}
        for code, info in landen["landen"].items():
            for naam in info["namen"]:
                self._exact[naam] = (code, 1.0, False)
            for bijv in info["bijvoeglijk"]:
                doel = self._ongevoelig if bijv[:1].islower() else self._exact
                doel[bijv.casefold() if doel is self._ongevoelig else bijv] = (code, 0.5, False)
        for stad, code in landen["steden"].items():
            self._exact.setdefault(stad, (code, 1.0, True))
        for term in BELGISCHE_TERMEN:
            if term[:1].islower():
                self._ongevoelig[term.casefold()] = ("BE", 1.0, False)
            else:
                self._exact[term] = ("BE", 1.0, False)

    def gewest_van(self, plaats: str) -> str:
        info = self._plaatsnamen.get(plaats.strip().casefold())
        return self._plaatsen[info[0]]["gewest"] if info else ""

    def _zoek(self, tokens: list[tuple[str, int]], in_titel: bool) -> list[Treffer]:
        treffers: list[Treffer] = []
        i = 0
        while i < len(tokens):
            gevonden = False
            for n in range(min(MAX_WOORDEN, len(tokens) - i), 0, -1):
                woorden = [t for t, _ in tokens[i:i + n]]
                tekst = " ".join(woorden)
                positie = tokens[i][1]
                vorig = tokens[i - 1][0].casefold() if i > 0 else ""
                if tekst[:1].isupper():
                    sleutel = tekst.casefold()
                    if sleutel in self._plaatsnamen:
                        idx, vlag = self._plaatsnamen[sleutel]
                        if vlag & 1 and vorig not in VOORZETSELS:
                            pass  # gewoon woord: enkel na een voorzetsel als plaats aanvaarden
                        else:
                            plaats = self._plaatsen[idx]
                            treffers.append(Treffer(plaats["naam"], "BE", 1.0 if not vlag & 2 else 0.0,
                                                    in_titel, positie, plaats["gewest"], True))
                            if vlag & 2:
                                treffers[-1].land = "BE?"  # ook een buitenlandse stad: enkel met Belgische context
                                if tekst in self._exact:
                                    land, gewicht, is_stad = self._exact[tekst]
                                    treffers.append(Treffer(tekst, land, gewicht, in_titel, positie, is_plaats=is_stad))
                            i += n
                            gevonden = True
                            break
                    if tekst in self._exact:
                        land, gewicht, is_stad = self._exact[tekst]
                        treffers.append(Treffer(tekst, land, gewicht, in_titel, positie, is_plaats=is_stad))
                        i += n
                        gevonden = True
                        break
                if tekst.casefold() in self._ongevoelig:
                    land, gewicht, _ = self._ongevoelig[tekst.casefold()]
                    treffers.append(Treffer(tekst, land, gewicht, in_titel, positie))
                    i += n
                    gevonden = True
                    break
            if not gevonden:
                i += 1
        return treffers

    def analyseer(self, titel: str, rest: str) -> GeoAnalyse:
        treffers = self._zoek(_tokens(titel), True) + self._zoek(_tokens(rest), False)
        analyse = GeoAnalyse()
        be_context = any(t.land == "BE" for t in treffers)
        for t in treffers:
            factor = 2.0 if t.in_titel else 1.0
            if t.land == "BE?":
                if not be_context:
                    continue
                t.land, t.gewicht = "BE", 1.0
            if t.land == "BE":
                analyse.be += t.gewicht * factor
                if t.is_plaats and not analyse.plaats:
                    analyse.plaats, analyse.gewest = t.naam, t.gewest
            else:
                analyse.buitenland[t.land] += t.gewicht * factor
                if t.is_plaats and t.land not in analyse.buitenlandse_plaats:
                    analyse.buitenlandse_plaats[t.land] = t.naam
        return analyse

    def bepaal(self, titel: str, rest: str, bron_land: str = "", uitgever_url: str = "") -> Regio:
        analyse = self.analyseer(titel, rest)
        voorkeur = land_van_url(uitgever_url) or (bron_land if len(bron_land) == 2 else "")
        if voorkeur == "BE":
            analyse.be += BRON_GEWICHT
        elif voorkeur:
            analyse.buitenland[voorkeur] += BRON_GEWICHT
        beste_land, beste_score = "", 0.0
        for land, score in analyse.buitenland.items():
            if score > beste_score:
                beste_land, beste_score = land, score
        if analyse.be > 0 and analyse.be >= beste_score:
            return Regio("BE", "BE", analyse.plaats, analyse.gewest)
        if beste_score > 0:
            return Regio("INT", beste_land, analyse.buitenlandse_plaats.get(beste_land, ""), "")
        return Regio("INT", "", "", "")
