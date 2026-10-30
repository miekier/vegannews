"""Het archief: één JSON-bestand per maand in site/data/berichten/, plus index.json."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from .model import Bericht
from .ontdubbelen import bericht_id, gelijkend, titel_sleutel

VENSTER_DAGEN = 3       # dubbele titels worden gezocht binnen ± 3 dagen
MAX_EXTRA = 12


def maanden_tussen(van: date, tot: date) -> list[str]:
    maanden, d = [], date(van.year, van.month, 1)
    while d <= tot:
        maanden.append(f"{d.year:04d}-{d.month:02d}")
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return maanden


class Archief:
    def __init__(self, map_: Path):
        self.map = map_
        self.berichten_map = map_ / "berichten"
        self._maanden: dict[str, dict[str, Bericht]] = {}
        self._gewijzigd: set[str] = set()
        self._id_naar_maand: dict[str, str] = {}
        self._tokens: dict[str, set[str]] = defaultdict(set)   # woord -> bericht-ids
        self._sleutels: dict[str, frozenset[str]] = {}

    # -- laden -----------------------------------------------------------------

    def beschikbare_maanden(self) -> list[str]:
        if not self.berichten_map.exists():
            return []
        return sorted(p.stem for p in self.berichten_map.glob("????-??.json"))

    def laad(self, maand: str) -> dict[str, Bericht]:
        if maand in self._maanden:
            return self._maanden[maand]
        pad = self.berichten_map / f"{maand}.json"
        berichten: dict[str, Bericht] = {}
        if pad.exists():
            for item in json.loads(pad.read_text(encoding="utf-8")).get("berichten", []):
                b = Bericht.van_dict(item)
                berichten[b.id] = b
        self._maanden[maand] = berichten
        for b in berichten.values():
            self._indexeer(b, maand)
        return berichten

    def laad_periode(self, van: date, tot: date) -> None:
        for maand in maanden_tussen(van, tot):
            self.laad(maand)

    def _indexeer(self, b: Bericht, maand: str) -> None:
        self._id_naar_maand[b.id] = maand
        for extra in b.extra:
            if extra.get("id"):
                self._id_naar_maand.setdefault(extra["id"], maand)
        sleutel = titel_sleutel(b.titel_orig or b.titel)
        self._sleutels[b.id] = sleutel
        for woord in sleutel:
            self._tokens[woord].add(b.id)

    def bericht(self, id_: str) -> Bericht | None:
        maand = self._id_naar_maand.get(id_)
        if not maand:
            return None
        berichten = self._maanden.get(maand, {})
        if id_ in berichten:
            return berichten[id_]
        return next((b for b in berichten.values() if any(e.get("id") == id_ for e in b.extra)), None)

    def geladen(self) -> list[Bericht]:
        return [b for berichten in self._maanden.values() for b in berichten.values()]

    def markeer_gewijzigd(self, b: Bericht) -> None:
        maand = self._id_naar_maand.get(b.id) or b.datum[:7]
        self._gewijzigd.add(maand)

    # -- toevoegen ---------------------------------------------------------------

    def _vind_gelijkend(self, sleutel: frozenset[str], datum: str) -> Bericht | None:
        if not sleutel:
            return None
        tellers: dict[str, int] = defaultdict(int)
        for woord in sleutel:
            for id_ in self._tokens.get(woord, ()):
                tellers[id_] += 1
        nodig = 2 if len(sleutel) >= 2 else 1
        dag = date.fromisoformat(datum)
        for id_, aantal in sorted(tellers.items(), key=lambda kv: -kv[1]):
            if aantal < nodig:
                break
            if not gelijkend(sleutel, self._sleutels.get(id_, frozenset())):
                continue
            kandidaat = self.bericht(id_)
            if kandidaat and abs((date.fromisoformat(kandidaat.datum) - dag).days) <= VENSTER_DAGEN:
                return kandidaat
        return None

    def voeg_toe(self, nieuwe: list[Bericht]) -> list[Bericht]:
        """Voegt nieuwe berichten toe; dubbels worden als extra bron bij het bestaande bericht gezet."""
        toegevoegd: list[Bericht] = []
        nieuwe = sorted(nieuwe, key=lambda b: (b.relatie != "primair", b.gepubliceerd or b.opgehaald))
        for b in nieuwe:
            dag = date.fromisoformat(b.datum)
            self.laad_periode(dag - timedelta(days=VENSTER_DAGEN), dag + timedelta(days=VENSTER_DAGEN))
            if b.id in self._id_naar_maand:
                self._ververs(b)
                continue
            bestaand = self._vind_gelijkend(titel_sleutel(b.titel_orig or b.titel), b.datum)
            if bestaand is not None:
                self._voeg_extra_toe(bestaand, b)
                continue
            maand = b.datum[:7]
            self.laad(maand)[b.id] = b
            self._indexeer(b, maand)
            self._gewijzigd.add(maand)
            toegevoegd.append(b)
        return toegevoegd

    def _ververs(self, nieuw: Bericht) -> None:
        """Een opnieuw opgehaald bericht: indeling volgens de huidige regels overnemen,
        tenzij het taalmodel het bericht al verwerkte."""
        bestaand = self.bericht(nieuw.id)
        if bestaand is None or bestaand.id != nieuw.id or bestaand.methode == "llm":
            return
        velden = ("categorieen", "gebeurtenis", "relevantie", "regio", "land", "plaats", "gewest")
        if any(getattr(bestaand, v) != getattr(nieuw, v) for v in velden):
            for v in velden:
                setattr(bestaand, v, getattr(nieuw, v))
            self._gewijzigd.add(self._id_naar_maand[bestaand.id])

    def _voeg_extra_toe(self, bestaand: Bericht, dubbel: Bericht) -> None:
        maand = self._id_naar_maand[bestaand.id]
        urls = {bestaand.url} | {e.get("url") for e in bestaand.extra}
        if dubbel.url in urls or len(bestaand.extra) >= MAX_EXTRA:
            self._id_naar_maand.setdefault(dubbel.id, maand)
            return
        if bestaand.kandidaat and not dubbel.kandidaat:
            # Een gewoon (relevant) bericht bevestigt een nog niet beoordeelde kandidaat.
            bestaand.kandidaat, bestaand.relevant, bestaand.zoekterm = False, True, ""
            bestaand.relevantie = max(bestaand.relevantie, dubbel.relevantie)
            bestaand.categorieen, bestaand.gebeurtenis = dubbel.categorieen, dubbel.gebeurtenis
        if dubbel.relatie == "primair" and bestaand.relatie != "primair":
            # De organisatie of het bedrijf zelf wordt de hoofdbron; het medium wordt extra bron.
            bestaand.extra.insert(0, {"naam": bestaand.uitgever or bestaand.bron_naam, "url": bestaand.url,
                                      "id": bericht_id(bestaand.url)})
            bestaand.url, bestaand.bron, bestaand.bron_naam = dubbel.url, dubbel.bron, dubbel.bron_naam
            bestaand.uitgever, bestaand.relatie, bestaand.brontype = dubbel.uitgever, "primair", dubbel.brontype
        else:
            bestaand.extra.append({"naam": dubbel.uitgever or dubbel.bron_naam, "url": dubbel.url, "id": dubbel.id})
        self._id_naar_maand.setdefault(dubbel.id, maand)
        self._gewijzigd.add(maand)

    def verwijder(self, id_: str) -> None:
        maand = self._id_naar_maand.get(id_)
        berichten = self._maanden.get(maand or "", {})
        b = berichten.pop(id_, None)
        if b is None:
            return
        for sleutel in [k for k, m in self._id_naar_maand.items() if m == maand and (k == id_ or any(
                e.get("id") == k for e in b.extra))]:
            del self._id_naar_maand[sleutel]
        for woord in self._sleutels.pop(id_, frozenset()):
            self._tokens.get(woord, set()).discard(id_)
        self._gewijzigd.add(maand)

    # -- bewaren -----------------------------------------------------------------

    def bewaar(self) -> list[str]:
        self.berichten_map.mkdir(parents=True, exist_ok=True)
        for maand in sorted(self._gewijzigd):
            berichten = sorted(self._maanden.get(maand, {}).values(),
                               key=lambda b: (b.datum, b.gepubliceerd or b.opgehaald, b.id), reverse=True)
            regels = [json.dumps(b.naar_dict(), ensure_ascii=False, separators=(",", ":")) for b in berichten]
            inhoud = '{"maand":"%s","aantal":%d,"berichten":[\n%s\n]}\n' % (maand, len(regels), ",\n".join(regels))
            (self.berichten_map / f"{maand}.json").write_text(inhoud, encoding="utf-8")
        bewaard = sorted(self._gewijzigd)
        self._gewijzigd.clear()
        return bewaard

    def tellingen(self, maanden: list[str]) -> tuple[dict[str, int], dict[str, list[int]]]:
        """Aantal berichten per maand en per dag ([totaal, nationaal, relevant])."""
        per_maand: dict[str, int] = {}
        per_dag: dict[str, list[int]] = {}
        for maand in maanden:
            berichten = self.laad(maand)
            per_maand[maand] = len(berichten)
            for b in berichten.values():
                dag = per_dag.setdefault(b.datum, [0, 0, 0])
                dag[0] += 1
                dag[1] += b.regio == "BE"
                dag[2] += b.relevant
        return per_maand, per_dag
