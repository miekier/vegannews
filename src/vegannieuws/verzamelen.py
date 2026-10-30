"""De volledige verzamelrun: ophalen, verwerken, ontdubbelen, verrijken en publiceren."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import __version__
from .archief import Archief
from .bronnen import SOORT_NAMEN, TYPES, Bron, laad_register
from .classificatie import Lexicon, deel_in, laad_lexicon
from .config import Instellingen, Paden
from .locatie import Geo
from .model import Bericht
from .ontdubbelen import bericht_id
from .ophalen import Ophaler, Resultaat, RuwBericht
from .staat import Staat
from .tekst import detecteer_taal
from .verrijking import LlmStatistiek, achterstand, diagnose_taalmodel, maak_taalmodellen, verrijk
from .vertaling import vertaal_titels


def iso(moment: datetime | None) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z") if moment else ""


@dataclass
class Rapport:
    start: str = ""
    duur_s: float = 0.0
    versie: str = __version__
    bronnen_actief: int = 0
    bronnen_ok: int = 0
    bronnen_fout: int = 0
    opgehaald: int = 0
    behouden: int = 0
    nieuw: int = 0
    terugvullen_dagen: int = 0
    llm: dict = field(default_factory=dict)
    reservevertaling: dict = field(default_factory=dict)
    waarschuwingen: list[str] = field(default_factory=list)
    fouten: list[dict] = field(default_factory=list)


def maak_bericht(ruw: RuwBericht, bron: Bron, nu: datetime, tz: ZoneInfo, grens: datetime,
                 lexicon: Lexicon, geo: Geo) -> Bericht | None:
    gepubliceerd = ruw.gepubliceerd
    if gepubliceerd and gepubliceerd > nu + timedelta(hours=3):
        gepubliceerd = None  # datum in de toekomst: onbetrouwbaar
    if gepubliceerd and gepubliceerd < grens:
        return None
    moment = gepubliceerd or nu
    taal = detecteer_taal(f"{ruw.titel}. {ruw.samenvatting}", bron.taal)
    indeling = deel_in(lexicon, ruw.titel, ruw.samenvatting)
    categorieen = indeling.categorieen
    if bron.type == "wetenschap" and "wetenschap" not in categorieen:
        categorieen = ["wetenschap"] + [c for c in categorieen if c != "overig"][:2]
    # Bij zoekresultaten zegt de editie (bv. Google Nieuws België) niets over het artikel zelf;
    # enkel het domein van het medium telt dan als aanwijzing.
    regio = geo.bepaal(ruw.titel, ruw.samenvatting, "" if bron.is_zoekopdracht else bron.land, ruw.uitgever_url)
    return Bericht(
        id=bericht_id(ruw.url),
        titel=ruw.titel,
        url=ruw.url,
        bron=bron.id,
        bron_naam=bron.naam,
        samenvatting=ruw.samenvatting,
        taal=taal,
        uitgever=ruw.uitgever if ruw.uitgever and ruw.uitgever != bron.naam else "",
        relatie=bron.relatie,
        brontype=bron.type,
        gepubliceerd=iso(gepubliceerd),
        opgehaald=iso(nu),
        datum=moment.astimezone(tz).date().isoformat(),
        categorieen=categorieen,
        gebeurtenis=indeling.gebeurtenis,
        regio=regio.regio,
        land=regio.land,
        plaats=regio.plaats,
        gewest=regio.gewest,
        relevantie=indeling.relevantie,
        uitgever_url=ruw.uitgever_url,
    )


def _haal_alles(ophaler: Ophaler, bronnen: list[Bron], gelijktijdig: int) -> list[Resultaat]:
    with ThreadPoolExecutor(max_workers=max(1, gelijktijdig)) as pool:
        return list(pool.map(ophaler.haal, bronnen))


def _terugvullen(ophaler: Ophaler, bronnen: list[Bron], dagen: int, vandaag: date, gelijktijdig: int) -> list[Resultaat]:
    """Zoekt ouder nieuws op via Google Nieuws, in vensters van een week."""
    taken = []
    einde = vandaag + timedelta(days=1)
    while dagen > 0:
        begin = einde - timedelta(days=min(7, dagen))
        taken.extend((bron, f"after:{begin.isoformat()} before:{einde.isoformat()}")
                     for bron in bronnen if bron.soort == "google")
        dagen -= 7
        einde = begin
    with ThreadPoolExecutor(max_workers=max(1, gelijktijdig)) as pool:
        return list(pool.map(lambda taak: ophaler.haal(taak[0], taak[1]), taken))


def _werk_status_bij(staat: Staat, resultaten: list[Resultaat], nieuw_per_bron: dict[str, int], nu: str) -> None:
    per_bron: dict[str, list[Resultaat]] = {}
    for res in resultaten:
        per_bron.setdefault(res.bron.id, []).append(res)
    for bron_id, lijst in per_bron.items():
        oud = staat.bronnen.get(bron_id, {})
        fout = all(r.status == "fout" for r in lijst)
        res = next((r for r in lijst if r.status != "fout"), lijst[0])
        nieuw = nieuw_per_bron.get(bron_id, 0)
        staat.bronnen[bron_id] = {
            "status": res.status,
            "melding": res.melding,
            "feed": res.feed or oud.get("feed", ""),
            "gecontroleerd": nu,
            "laatst_ok": oud.get("laatst_ok", "") if fout else nu,
            "laatst_nieuw": nu if nieuw else oud.get("laatst_nieuw", ""),
            "berichten_in_feed": sum(len(r.berichten) for r in lijst),
            "nieuw": nieuw,
            "totaal": int(oud.get("totaal", 0)) + nieuw,
            "fouten_op_rij": int(oud.get("fouten_op_rij", 0)) + 1 if fout else 0,
        }


def schrijf_bronnen_json(pad: Path, bronnen: list[Bron], staat: Staat, waarschuwingen: list[str]) -> None:
    lijst = []
    for b in bronnen:
        status = staat.bronnen.get(b.id, {})
        lijst.append({
            "id": b.id, "naam": b.naam, "type": b.type, "type_naam": TYPES.get(b.type, b.type),
            "soort": b.soort, "soort_naam": SOORT_NAMEN.get(b.soort, b.soort), "url": b.url,
            "zoekterm": b.zoekterm, "editie": b.editie, "taal": b.taal, "land": b.land,
            "alleen_vegan": b.alleen_vegan, "actief": b.actief, "notitie": b.notitie,
            **{k: status.get(k) for k in ("status", "melding", "feed", "gecontroleerd", "laatst_ok", "laatst_nieuw",
                                           "berichten_in_feed", "nieuw", "totaal", "fouten_op_rij") if k in status},
        })
    pad.write_text(json.dumps({"bronnen": lijst, "waarschuwingen": waarschuwingen}, ensure_ascii=False, indent=1),
                   encoding="utf-8")


def schrijf_index(paden: Paden, archief: Archief, lexicon: Lexicon, geo: Geo, inst: Instellingen,
                  rapport: Rapport, gewijzigde_maanden: list[str]) -> None:
    pad = paden.site_data / "index.json"
    oud = json.loads(pad.read_text(encoding="utf-8")) if pad.exists() else {}
    maanden = dict(oud.get("maanden", {}))
    dagen = dict(oud.get("dagen", {}))
    per_maand, per_dag = archief.tellingen(gewijzigde_maanden)
    for maand in gewijzigde_maanden:
        dagen = {d: v for d, v in dagen.items() if not d.startswith(maand)}
    maanden.update(per_maand)
    dagen.update(per_dag)
    bestaande = set(archief.beschikbare_maanden())
    maanden = {m: n for m, n in maanden.items() if m in bestaande}
    index = {
        "versie": 1,
        "bijgewerkt": rapport.start,
        "doeltaal": inst.doeltaal,
        "repo": inst.repository,
        "categorieen": [{"code": c.code, "naam": c.naam, "omschrijving": c.omschrijving} for c in lexicon.categorieen],
        "gebeurtenissen": [{"code": g.code, "naam": g.naam} for g in lexicon.gebeurtenissen],
        "landen": geo.landnamen,
        "maanden": dict(sorted(maanden.items())),
        "dagen": dict(sorted(dagen.items())),
        "laatste_run": asdict(rapport),
    }
    pad.write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _verrijk_achterstand(archief: Archief, inst: Instellingen, lexicon: Lexicon, geo: Geo, staat: Staat,
                         vandaag: str, log) -> LlmStatistiek:
    clients = maak_taalmodellen(inst.llm_aanbieders, inst.modellen_per_aanbieder, inst.llm_pauze_s)
    if not clients:
        return LlmStatistiek(melding="geen sleutel voor een taalmodel ingesteld (GEMINI_API_KEY of GROQ_API_KEY): "
                                     "indeling op basis van trefwoorden")
    resterend = min(inst.llm_max_verzoeken_per_run, staat.resterend("llm", vandaag, inst.llm_max_verzoeken_per_dag))
    sinds = (date.fromisoformat(vandaag) - timedelta(days=inst.llm_max_leeftijd_dagen)).isoformat()
    lijst = achterstand(archief.geladen(), sinds, inst.llm_max_pogingen)
    if not lijst:
        return LlmStatistiek(aanbieder=clients[0].naam, melding="niets te verwerken")
    if resterend <= 0:
        return LlmStatistiek(aanbieder=clients[0].naam, melding="dagbudget voor het taalmodel is op",
                             achterstand=len(lijst))
    stat = LlmStatistiek()
    for client in clients:
        stat = verrijk(lijst, client, lexicon, geo, inst.doeltaal, inst.talen_zonder_vertaling, inst.llm_batch,
                       resterend, inst.llm_max_pogingen, log=log)
        staat.verbruik("llm", vandaag, stat.verzoeken)
        if stat.verrijkt or not stat.melding.startswith("geen werkend eindpunt"):
            break
        if client.naam == "GitHub Models":
            log("Diagnose taalmodel:")
            for regel in diagnose_taalmodel(client.token, inst.llm_modellen):
                log(f"  {regel}")
        lijst = achterstand(archief.geladen(), sinds, inst.llm_max_pogingen)
    for b in archief.geladen():
        if b.methode == "llm" or b.pogingen:
            archief.markeer_gewijzigd(b)
    return stat


def verzamel(paden: Paden, inst: Instellingen, terugvullen_dagen: int = 0, gebruik_llm: bool = True,
             alleen: set[str] | None = None, log=print) -> Rapport:
    t0 = time.monotonic()
    nu = datetime.now(timezone.utc).replace(microsecond=0)
    tz = ZoneInfo(inst.tijdzone)
    vandaag = nu.astimezone(tz).date()
    rapport = Rapport(start=iso(nu), terugvullen_dagen=terugvullen_dagen)

    bronnen, rapport.waarschuwingen = laad_register(paden.bronnen, paden.zoekopdrachten)
    lexicon = laad_lexicon(paden.categorieen)
    geo = Geo()
    staat = Staat.laad(paden.staat)
    archief = Archief(paden.site_data)
    max_leeftijd = max(inst.max_leeftijd_dagen, terugvullen_dagen + 7)
    grens = nu - timedelta(days=max_leeftijd)
    archief.laad_periode((grens - timedelta(days=7)).date(), vandaag)

    actief = [b for b in bronnen if b.actief and (not alleen or b.id in alleen)]
    rapport.bronnen_actief = len(actief)
    ophaler = Ophaler(staat, inst)
    log(f"{len(actief)} bronnen ophalen ...")
    resultaten = _haal_alles(ophaler, actief, inst.gelijktijdig)
    if terugvullen_dagen > 0:
        log(f"Ouder nieuws opzoeken ({terugvullen_dagen} dagen) ...")
        resultaten += _terugvullen(ophaler, actief, terugvullen_dagen, vandaag, inst.gelijktijdig)

    kandidaten: list[Bericht] = []
    for res in resultaten:
        if res.status == "fout":
            continue
        for ruw in res.berichten:
            rapport.opgehaald += 1
            b = maak_bericht(ruw, res.bron, nu, tz, grens, lexicon, geo)
            if b is None or (res.bron.alleen_vegan and b.relevantie < 1):
                continue
            kandidaten.append(b)
    rapport.behouden = len(kandidaten)
    nieuw = archief.voeg_toe(kandidaten)
    rapport.nieuw = len(nieuw)
    nieuw_per_bron: dict[str, int] = {}
    for b in nieuw:
        nieuw_per_bron[b.bron] = nieuw_per_bron.get(b.bron, 0) + 1
    log(f"{rapport.opgehaald} berichten opgehaald, {rapport.behouden} relevant, {rapport.nieuw} nieuw")

    if gebruik_llm and inst.llm_aan:
        stat = _verrijk_achterstand(archief, inst, lexicon, geo, staat, vandaag.isoformat(), log)
        rapport.llm = asdict(stat)
        log(f"Taalmodel: {stat.verrijkt} berichten verwerkt in {stat.verzoeken} verzoeken. {stat.melding}")
    if inst.reserve_vertaling:
        budget = staat.resterend("mymemory", vandaag.isoformat(), inst.reserve_max_tekens_per_dag)
        sinds = (vandaag - timedelta(days=7)).isoformat()
        onvertaald = sorted((b for b in archief.geladen() if b.datum >= sinds and not b.vertaald and b.methode != "llm"),
                            key=lambda b: b.datum, reverse=True)
        if budget > 0 and onvertaald:
            aantal, tekens, melding = vertaal_titels(onvertaald, inst.doeltaal, inst.talen_zonder_vertaling, budget,
                                                     inst.mymemory_email, ophaler.sessie)
            staat.verbruik("mymemory", vandaag.isoformat(), tekens)
            for b in onvertaald:
                if b.vertaald == "mymemory":
                    archief.markeer_gewijzigd(b)
            rapport.reservevertaling = {"vertaald": aantal, "tekens": tekens, "melding": melding}

    gewijzigd = archief.bewaar()
    _werk_status_bij(staat, resultaten, nieuw_per_bron, iso(nu))
    rapport.bronnen_ok = sum(1 for b in actief if staat.bronnen.get(b.id, {}).get("status") != "fout")
    rapport.bronnen_fout = rapport.bronnen_actief - rapport.bronnen_ok
    rapport.fouten = [
        {"bron": b.naam, "melding": staat.bronnen[b.id].get("melding", "")}
        for b in actief if staat.bronnen.get(b.id, {}).get("status") == "fout"
    ]
    rapport.duur_s = round(time.monotonic() - t0, 1)
    paden.site_data.mkdir(parents=True, exist_ok=True)
    schrijf_bronnen_json(paden.site_data / "bronnen.json", bronnen, staat, rapport.waarschuwingen)
    schrijf_index(paden, archief, lexicon, geo, inst, rapport, gewijzigd)
    staat.bewaar(paden.staat)
    return rapport


def herindeel(paden: Paden, inst: Instellingen, dagen: int, log=print) -> int:
    """Past de trefwoorden opnieuw toe op berichten die niet door het taalmodel werden ingedeeld."""
    lexicon = laad_lexicon(paden.categorieen)
    geo = Geo()
    archief = Archief(paden.site_data)
    vandaag = datetime.now(ZoneInfo(inst.tijdzone)).date()
    archief.laad_periode(vandaag - timedelta(days=dagen), vandaag)
    aantal = 0
    for b in archief.geladen():
        if b.methode == "llm":
            continue
        indeling = deel_in(lexicon, b.titel_orig or b.titel, b.samenvatting_orig or b.samenvatting)
        categorieen = indeling.categorieen
        if b.brontype == "wetenschap" and "wetenschap" not in categorieen:
            categorieen = ["wetenschap"] + [c for c in categorieen if c != "overig"][:2]
        b.categorieen, b.gebeurtenis, b.relevantie = categorieen, indeling.gebeurtenis, indeling.relevantie
        archief.markeer_gewijzigd(b)
        aantal += 1
    gewijzigd = archief.bewaar()
    rapport = Rapport(start=iso(datetime.now(timezone.utc).replace(microsecond=0)))
    index_pad = paden.site_data / "index.json"
    if index_pad.exists():
        rapport = Rapport(**{k: v for k, v in json.loads(index_pad.read_text(encoding="utf-8")).get("laatste_run", {}).items()
                             if k in Rapport.__dataclass_fields__})
    schrijf_index(paden, archief, lexicon, geo, inst, rapport, gewijzigd)
    log(f"{aantal} berichten opnieuw ingedeeld")
    return aantal


def rapport_markdown(rapport: Rapport) -> str:
    regels = [
        "## Nieuws verzameld",
        "",
        f"- Start: {rapport.start} (duur {rapport.duur_s:.0f} s)",
        f"- Bronnen: {rapport.bronnen_actief} actief, {rapport.bronnen_ok} gelukt, {rapport.bronnen_fout} met fout",
        f"- Berichten: {rapport.opgehaald} opgehaald, {rapport.behouden} relevant, **{rapport.nieuw} nieuw**",
    ]
    if rapport.llm:
        llm = rapport.llm
        regels.append(f"- Taalmodel ({llm.get('aanbieder') or '-'}, {llm.get('model') or '-'}): {llm.get('verrijkt', 0)} verwerkt in "
                      f"{llm.get('verzoeken', 0)} verzoeken, achterstand {llm.get('achterstand', 0)}. {llm.get('melding', '')}")
    if rapport.reservevertaling:
        rv = rapport.reservevertaling
        regels.append(f"- Reservevertaling: {rv.get('vertaald', 0)} titels ({rv.get('tekens', 0)} tekens). {rv.get('melding', '')}")
    if rapport.waarschuwingen:
        regels += ["", "### Waarschuwingen in het register", ""] + [f"- {w}" for w in rapport.waarschuwingen]
    if rapport.fouten:
        regels += ["", "### Bronnen met een fout", "", "| Bron | Melding |", "|---|---|"]
        regels += [f"| {f['bron']} | {f['melding']} |" for f in rapport.fouten]
    return "\n".join(regels) + "\n"
