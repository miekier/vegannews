"""Bronnen toevoegen, uitschakelen of verwijderen via een GitHub-issueformulier.

De registerbestanden worden als tekst aangepast (niet opnieuw weggeschreven), zodat
uitleg en commentaar in het bestand behouden blijven.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from .bronnen import Bron, detecteer_soort, google_url, id_voor_url, laad_register, standaard_editie
from .config import Instellingen, Paden
from .ophalen import Ophaler
from .staat import Staat

TYPES = {
    "organisatie": "organisatie", "restaurant of horeca": "horeca", "bedrijf of merk": "bedrijf",
    "persoon": "persoon", "nieuwsmedium": "medium", "overheid of politiek": "overheid", "wetenschap": "wetenschap",
    "zoekopdracht in google nieuws": "zoekopdracht",
}
LANDEN = {
    "belgië": "BE",
    "internationaal": "INT",
    "nederland": "NL",
    "frankrijk": "FR",
    "duitsland": "DE",
    "luxemburg": "LU",
    "verenigd koninkrijk": "GB",
    "ierland": "IE",
    "oostenrijk": "AT",
    "zwitserland": "CH",
    "spanje": "ES",
    "portugal": "PT",
    "italië": "IT",
    "malta": "MT",
    "griekenland": "GR",
    "cyprus": "CY",
    "polen": "PL",
    "tsjechië": "CZ",
    "slowakije": "SK",
    "hongarije": "HU",
    "slovenië": "SI",
    "kroatië": "HR",
    "servië": "RS",
    "roemenië": "RO",
    "bulgarije": "BG",
    "denemarken": "DK",
    "zweden": "SE",
    "noorwegen": "NO",
    "finland": "FI",
    "ijsland": "IS",
    "estland": "EE",
    "letland": "LV",
    "litouwen": "LT",
    "oekraïne": "UA",
    "verenigde staten": "US",
    "ander land": "INT",
    "belgie": "BE",
}
TALEN = {
    "nederlands": "nl",
    "frans": "fr",
    "engels": "en",
    "duits": "de",
    "spaans": "es",
    "italiaans": "it",
    "portugees": "pt",
    "pools": "pl",
    "tsjechisch": "cs",
    "slowaaks": "sk",
    "hongaars": "hu",
    "sloveens": "sl",
    "kroatisch": "hr",
    "servisch": "sr",
    "roemeens": "ro",
    "bulgaars": "bg",
    "grieks": "el",
    "deens": "da",
    "zweeds": "sv",
    "noors": "no",
    "fins": "fi",
    "ijslands": "is",
    "estisch": "et",
    "lets": "lv",
    "litouws": "lt",
    "oekraïens": "uk",
}
GEEN_ANTWOORD = {"", "_no response_", "_geen antwoord_", "none"}


@dataclass
class Uitkomst:
    antwoord: str
    gewijzigd: bool = False
    sluiten: bool = True


def lees_formulier(tekst: str) -> dict[str, str]:
    """Leest de velden van een ingevuld issueformulier ('### Kop' gevolgd door de waarde)."""
    velden: dict[str, str] = {}
    kop = None
    waarde: list[str] = []
    for regel in (tekst or "").replace("\r\n", "\n").split("\n"):
        if regel.startswith("### "):
            if kop is not None:
                velden[kop] = "\n".join(waarde).strip()
            kop, waarde = regel[4:].strip().lower(), []
        elif kop is not None:
            waarde.append(regel)
    if kop is not None:
        velden[kop] = "\n".join(waarde).strip()
    return {k: ("" if v.strip().lower() in GEEN_ANTWOORD else v.strip()) for k, v in velden.items()}


def _veld(velden: dict[str, str], *begin: str) -> str:
    for kop, waarde in velden.items():
        if any(kop.startswith(b) for b in begin):
            return waarde
    return ""


def _yaml_tekst(waarde: str) -> str:
    return json.dumps(waarde, ensure_ascii=False)


def _blokken(regels: list[str]) -> list[tuple[int, int]]:
    starts = [i for i, r in enumerate(regels) if re.match(r"^  - ", r)]
    blokken = []
    for n, s in enumerate(starts):
        e = starts[n + 1] if n + 1 < len(starts) else len(regels)
        while e > s + 1 and (not regels[e - 1].strip() or regels[e - 1].lstrip().startswith("#")):
            e -= 1
        blokken.append((s, e))
    return blokken


def _voeg_blok_toe(pad: Path, blok: list[str]) -> None:
    tekst = pad.read_text(encoding="utf-8") if pad.exists() else ""
    if not tekst.endswith("\n"):
        tekst += "\n"
    pad.write_text(tekst + "\n" + "\n".join(blok) + "\n", encoding="utf-8")


def _normaliseer_url(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", url.strip().lower()).rstrip("/")


def _zoek_in_bestand(pad: Path, sleutel: str, zoek: str) -> tuple[list[str], list[tuple[int, int]], int]:
    """Zoekt de regel in een registerbestand waarvan naam, url of zoekterm overeenkomt."""
    if not pad.exists():
        return [], [], -1
    regels = pad.read_text(encoding="utf-8").split("\n")
    items = (yaml.safe_load("\n".join(regels)) or {}).get(sleutel) or []
    blokken = _blokken(regels)
    if len(blokken) != len(items):
        raise ValueError(f"{pad.name} heeft een onverwachte opbouw; pas het bestand handmatig aan")
    doel = zoek.strip().lower()
    for i, item in enumerate(items):
        kandidaten = [str(item.get(k) or "").strip().lower() for k in ("naam", "zoekterm", "id")]
        url = str(item.get("url") or "")
        if doel in kandidaten or (url and _normaliseer_url(url) == _normaliseer_url(doel)):
            return regels, blokken, i
    return regels, blokken, -1


def _zet_actief(regels: list[str], blok: tuple[int, int], actief: bool) -> list[str]:
    s, e = blok
    waarde = "ja" if actief else "nee"
    for i in range(s, e):
        if re.match(r"^    actief\s*:", regels[i]):
            regels[i] = f"    actief: {waarde}"
            return regels
    return regels[:e] + [f"    actief: {waarde}"] + regels[e:]


def verwerk_wijziging(paden: Paden, velden: dict[str, str]) -> Uitkomst:
    zoek = _veld(velden, "bron")
    actie = _veld(velden, "actie").lower()
    if not zoek or not actie:
        return Uitkomst("⚠️ Vul zowel de bron als de gewenste actie in.", sluiten=False)
    for pad, sleutel in ((paden.bronnen, "bronnen"), (paden.zoekopdrachten, "zoekopdrachten")):
        regels, blokken, i = _zoek_in_bestand(pad, sleutel, zoek)
        if i < 0:
            continue
        if actie.startswith("verwijder"):
            s, e = blokken[i]
            regels = regels[:s] + regels[e:]
            tekst = "verwijderd uit het register"
        else:
            regels = _zet_actief(regels, blokken[i], actie.startswith("opnieuw") or actie.startswith("inschakel"))
            tekst = "opnieuw ingeschakeld" if actie.startswith(("opnieuw", "inschakel")) else "uitgeschakeld"
        nieuwe_tekst = "\n".join(regels)
        yaml.safe_load(nieuwe_tekst)  # controle: het bestand moet geldig blijven
        pad.write_text(nieuwe_tekst, encoding="utf-8")
        return Uitkomst(f"✅ **{zoek}** is {tekst} ({pad.name}).", gewijzigd=True)
    return Uitkomst(f"⚠️ Geen bron gevonden met naam, adres of zoekterm **{zoek}**. Controleer de schrijfwijze "
                    "op de pagina *Bronnen* en pas het issue aan.", sluiten=False)


def verwerk_toevoeging(paden: Paden, inst: Instellingen, velden: dict[str, str], issue: str = "",
                       ophaler: Ophaler | None = None) -> Uitkomst:
    naam = _veld(velden, "naam")
    adres = _veld(velden, "adres", "url")
    type_ = TYPES.get(_veld(velden, "soort bron", "type").lower(), "medium")
    land = LANDEN.get(_veld(velden, "land").lower(), "INT")
    taal = TALEN.get(_veld(velden, "taal").lower(), "")
    alles = _veld(velden, "welke berichten").lower().startswith("alle")
    opmerking = _veld(velden, "opmerking")
    if not naam or not adres:
        return Uitkomst("⚠️ Naam en adres (of zoekterm) zijn verplicht.", sluiten=False)
    notitie = f"Toegevoegd via issue #{issue} op {date.today().isoformat()}" if issue else f"Toegevoegd op {date.today().isoformat()}"
    if opmerking:
        notitie += f". {opmerking}"
    bestaande, _ = laad_register(paden.bronnen, paden.zoekopdrachten)
    ophaler = ophaler or Ophaler(Staat(), inst)

    if type_ == "zoekopdracht":
        editie = standaard_editie(taal, land)
        if any(b.soort == "google" and b.zoekterm.lower() == adres.lower() and b.editie == editie for b in bestaande):
            return Uitkomst(f"ℹ️ De zoekopdracht **{adres}** ({editie}) staat al in het register.")
        bron = Bron("test", naam, "google", "zoekopdracht", zoekterm=adres, editie=editie, taal=taal, land=land)
        res = ophaler.haal(bron)
        if res.status == "fout":
            return Uitkomst(f"❌ Google Nieuws gaf een fout voor deze zoekopdracht: {res.melding}. "
                            "Heropen het issue om het later opnieuw te proberen.", sluiten=False)
        _voeg_blok_toe(paden.zoekopdrachten, [
            f"  - zoekterm: {_yaml_tekst(adres)}",
            f"    naam: {_yaml_tekst(naam)}",
            "    dienst: google",
            f"    taal: {taal or 'nl'}",
            f"    land: {land}",
            f"    alleen_vegan: {'nee' if alles else 'ja'}",
            f"    notitie: {_yaml_tekst(notitie)}",
        ])
        voorbeelden = "\n".join(f"- {r.titel}" for r in res.berichten[:5]) or "- (deze week nog geen resultaten)"
        return Uitkomst(f"✅ Zoekopdracht **{adres}** toegevoegd (Google Nieuws, editie {editie}).\n\n"
                        f"Recente resultaten:\n{voorbeelden}\n\n"
                        f"Zoekpagina: {google_url(adres, editie)}", gewijzigd=True)

    if not adres.startswith(("http://", "https://")):
        adres = "https://" + adres.lstrip("/")
    doel = _normaliseer_url(adres)
    if any(b.url and _normaliseer_url(b.url) == doel for b in bestaande):
        return Uitkomst(f"ℹ️ **{adres}** staat al in het register.")
    soort = detecteer_soort(adres)
    bron = Bron(id_voor_url(adres), naam, soort, type_, url=adres, taal=taal, land=land, alleen_vegan=not alles)
    res = ophaler.haal(bron)
    if res.status == "fout":
        tip = ""
        if soort == "website":
            tip = ("\n\nTip: deze website heeft geen (vindbare) RSS-feed. Instagram- en Facebook-pagina's kunnen "
                   "niet gratis gevolgd worden. Probeer het adres van de nieuws- of blogpagina, of een "
                   "Bluesky-, Mastodon- of YouTube-account van dezelfde organisatie.")
        return Uitkomst(f"❌ **{naam}** kon niet worden opgehaald: {res.melding}.{tip}\n\n"
                        "Pas het adres aan in het issue (bewerken) of heropen het om het opnieuw te proberen.",
                        sluiten=False)
    _voeg_blok_toe(paden.bronnen, [
        f"  - naam: {_yaml_tekst(naam)}",
        f"    url: {_yaml_tekst(adres)}",
        f"    type: {type_}",
        f"    land: {land}",
        *([f"    taal: {taal}"] if taal else []),
        f"    alleen_vegan: {'nee' if alles else 'ja'}",
        f"    notitie: {_yaml_tekst(notitie)}",
    ])
    voorbeelden = "\n".join(f"- {r.titel}" for r in res.berichten[:5]) or "- (de feed is momenteel leeg)"
    return Uitkomst(f"✅ **{naam}** toegevoegd aan het register ({soort}, {land}).\n\n"
                    f"Gevonden feed: {res.feed}\n\nLaatste berichten:\n{voorbeelden}\n\n"
                    "Het nieuws van deze bron verschijnt na de volgende verzamelrun; die wordt nu gestart.",
                    gewijzigd=True)


def verwerk_aanvraag(paden: Paden, inst: Instellingen, tekst: str, issue: str = "") -> Uitkomst:
    velden = lees_formulier(tekst)
    try:
        if "actie" in velden:
            return verwerk_wijziging(paden, velden)
        if any(k.startswith(("adres", "url")) for k in velden):
            return verwerk_toevoeging(paden, inst, velden, issue)
    except (ValueError, yaml.YAMLError) as fout:
        return Uitkomst(f"❌ Het register kon niet automatisch aangepast worden: {fout}", sluiten=False)
    return Uitkomst("⚠️ Dit issue is geen bronformulier; er is niets gewijzigd.", sluiten=False)
