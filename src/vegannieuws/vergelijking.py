"""Blinde vergelijking van twee taalmodellen op dezelfde, echte berichten.

Beide modellen krijgen exact dezelfde invoer en dezelfde systeemprompt als in de gewone run:
berichten (kernzin, vertaling, indeling) en kandidaatgroepen voor verhalen (kop). Het resultaat
(een JSON-bestand) dient als invoer voor een beoordelingspagina waarop de uitvoer anoniem naast
elkaar staat.
"""

from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path

from .archief import Archief
from .classificatie import laad_lexicon
from .config import Instellingen, Paden
from .model import Bericht
from .verhalen import SCHEMA as VERHAAL_SCHEMA
from .verhalen import SYSTEEM as VERHAAL_SYSTEEM
from .verhalen import _invoer as verhaal_invoer
from .verhalen import kandidaatgroepen
from .verrijking import StopVerrijking, _invoer, antwoord_schema, lees_lijst, maak_taalmodellen, systeemprompt

PRIJZEN = {"anthropic": (0.10, 0.50), "gemini": (0.0, 0.0)}   # dollar per miljoen tokens (in, uit)


def kies_steekproef(berichten: list[Bericht], aantal: int, zaad: int) -> list[Bericht]:
    """Gelijke delen: andere talen (vertaling nodig), Nederlands en Engels."""
    kans = random.Random(zaad)
    per_soort: dict[str, list[Bericht]] = {"vertaling": [], "nl": [], "en": []}
    for b in berichten:
        soort = b.taal if b.taal in ("nl", "en") else "vertaling"
        per_soort[soort].append(b)
    deel = aantal // 3
    gekozen: list[Bericht] = []
    for lijst in per_soort.values():
        kans.shuffle(lijst)
        gekozen += lijst[:deel]
    return gekozen


def _vraag_berichten(client, systeem: str, schema: dict, berichten: list[Bericht], batch: int) -> dict[str, dict]:
    uit: dict[str, dict] = {}
    for start in range(0, len(berichten), batch):
        groep = berichten[start:start + batch]
        try:
            antwoord = client.vraag(systeem, json.dumps([_invoer(b) for b in groep], ensure_ascii=False), schema=schema)
            uit.update({str(r.get("id")): r for r in lees_lijst(antwoord, "berichten")})
        except (StopVerrijking, ValueError) as fout:
            for b in groep:
                uit[b.id] = {"fout": str(fout)[:200]}
    return uit


def _vraag_koppen(client, groepen: list[list[Bericht]]) -> list[dict]:
    korte: dict[str, Bericht] = {}
    invoer = []
    for groep in groepen:
        lijst = []
        for b in groep:
            kort = str(len(korte) + 1)
            korte[kort] = b
            kopie = Bericht.van_dict(b.naar_dict())
            kopie.verhaal_kop = ""             # geen bestaande kop meegeven: beide modellen starten gelijk
            lijst.append(verhaal_invoer(kopie, kort))
        invoer.append(lijst)
    try:
        antwoord = client.vraag(VERHAAL_SYSTEEM, json.dumps({"groepen": invoer}, ensure_ascii=False),
                                schema=VERHAAL_SCHEMA)
        verhalen = lees_lijst(antwoord, "verhalen")
    except (StopVerrijking, ValueError) as fout:
        return [{"fout": str(fout)[:200]}]
    return [{"ids": [korte[i].id for i in v.get("ids", []) if str(i) in korte], "kop": v.get("kop", "")}
            for v in verhalen if isinstance(v.get("ids"), list)]


def vergelijk(paden: Paden, inst: Instellingen, aantal: int = 36, groepen: int = 4, zaad: int = 20261030,
              log=print) -> dict:
    lexicon = laad_lexicon(paden.categorieen)
    archief = Archief(paden.site_data)
    vandaag = date.today()
    archief.laad_periode(vandaag - timedelta(days=4), vandaag)
    recent = sorted((b for b in archief.geladen()
                     if b.datum >= (vandaag - timedelta(days=3)).isoformat() and b.relevant and not b.kandidaat
                     and b.methode == "llm"), key=lambda b: b.id)
    steekproef = kies_steekproef(recent, aantal, zaad)
    kandidaten = [g for g in kandidaatgroepen(sorted(recent, key=lambda b: b.datum)) if 3 <= len(g) <= 10]
    random.Random(zaad).shuffle(kandidaten)
    kandidaten = kandidaten[:groepen]

    systeem = systeemprompt(lexicon, inst.doeltaal, inst.talen_zonder_vertaling)
    schema = antwoord_schema(lexicon)
    modellen = {}
    for code in ("anthropic", "gemini"):
        clients = maak_taalmodellen([code], inst.modellen_per_aanbieder, inst.llm_pauze_s)
        if not clients:
            log(f"Geen sleutel voor {code}: die aanbieder wordt overgeslagen")
            continue
        client = clients[0]
        log(f"{client.naam} ({client.model}): {len(steekproef)} berichten, {len(kandidaten)} kandidaatgroepen ...")
        berichten = _vraag_berichten(client, systeem, schema, steekproef, inst.llm_batch)
        koppen = _vraag_koppen(client, kandidaten) if kandidaten else []
        prijs_in, prijs_uit = PRIJZEN.get(code, (0.0, 0.0))
        modellen[code] = {
            "naam": client.naam, "model": client.model, "berichten": berichten, "verhalen": koppen,
            "invoer_tokens": client.invoer_tokens, "uitvoer_tokens": client.uitvoer_tokens,
            "kosten_dollar": round((client.invoer_tokens * prijs_in + client.uitvoer_tokens * prijs_uit) / 1e6, 5),
        }
    return {
        "datum": vandaag.isoformat(),
        "berichten": [{"id": b.id, "taal": b.taal, "bron": b.uitgever or b.bron_naam, "url": b.url,
                       "titel": b.titel_orig or b.titel, "tekst": (b.samenvatting_orig or b.samenvatting)[:500]}
                      for b in steekproef],
        "groepen": [[{"id": b.id, "taal": b.taal, "bron": b.uitgever or b.bron_naam, "titel": b.titel_orig or b.titel}
                     for b in g] for g in kandidaten],
        "modellen": modellen,
    }


def bewaar(resultaat: dict, pad: Path) -> None:
    pad.parent.mkdir(parents=True, exist_ok=True)
    pad.write_text(json.dumps(resultaat, ensure_ascii=False, indent=1), encoding="utf-8")
