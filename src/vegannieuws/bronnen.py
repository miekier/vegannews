"""Het bronnenregister: bronnen.yml (websites, feeds, accounts) en zoekopdrachten.yml."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode, urlparse

import yaml

from .tekst import slug

TYPES = {
    "organisatie": "Organisatie",
    "horeca": "Restaurant of horeca",
    "bedrijf": "Bedrijf of merk",
    "persoon": "Persoon",
    "medium": "Nieuwsmedium",
    "overheid": "Overheid of politiek",
    "wetenschap": "Wetenschap",
    "zoekopdracht": "Zoekopdracht",
}
PRIMAIRE_TYPES = {"organisatie", "horeca", "bedrijf", "persoon", "overheid", "wetenschap"}
SOORTEN = {"website", "rss", "bluesky", "mastodon", "youtube", "reddit", "google", "bing", "pubmed"}
ZOEKDIENSTEN = {"google", "bing", "pubmed"}
SOORT_NAMEN = {
    "website": "Website", "rss": "RSS-feed", "bluesky": "Bluesky", "mastodon": "Mastodon",
    "youtube": "YouTube", "reddit": "Reddit", "google": "Google Nieuws", "bing": "Bing Nieuws",
    "pubmed": "PubMed",
}


class RegisterFout(Exception):
    pass


@dataclass
class Bron:
    id: str
    naam: str
    soort: str
    type: str
    url: str = ""
    zoekterm: str = ""
    editie: str = ""            # Google Nieuws-editie, bv. "BE:nl"
    taal: str = ""
    land: str = ""              # BE, NL, FR, ... of INT
    alleen_vegan: bool = True   # enkel berichten die over veganisme gaan behouden
    actief: bool = True
    notitie: str = ""

    @property
    def relatie(self) -> str:
        return "primair" if self.type in PRIMAIRE_TYPES else "secundair"

    @property
    def is_zoekopdracht(self) -> bool:
        return self.soort in ZOEKDIENSTEN


def als_bool(waarde: object, standaard: bool) -> bool:
    if waarde is None or waarde == "":
        return standaard
    if isinstance(waarde, bool):
        return waarde
    tekst = str(waarde).strip().lower()
    if tekst in {"ja", "yes", "true", "waar", "1", "aan", "y"}:
        return True
    if tekst in {"nee", "neen", "no", "false", "onwaar", "0", "uit", "n"}:
        return False
    return standaard


def _landcode(waarde: object) -> str:
    if waarde is False:  # YAML 1.1 leest "NO" (Noorwegen) als false
        return "NO"
    tekst = str(waarde or "").strip().upper()
    return {"INTERNATIONAAL": "INT", "BELGIE": "BE", "BELGIË": "BE"}.get(tekst, tekst)


def detecteer_soort(url: str) -> str:
    deel = urlparse(url)
    host = deel.netloc.lower().removeprefix("www.").removeprefix("m.")
    pad = deel.path
    if host == "bsky.app" and pad.startswith("/profile/"):
        return "bluesky"
    if host in {"youtube.com", "youtu.be"}:
        return "youtube"
    if host.endswith("reddit.com") and pad.startswith("/r/"):
        return "reddit"
    if host == "medium.com":
        return "rss"
    if re.fullmatch(r"/@[\w.]+/?", pad):
        return "mastodon"
    return "website"


def vaste_feed(bron: Bron) -> str:
    """Feedadres dat rechtstreeks uit de URL volgt; leeg als het ontdekt moet worden."""
    url = bron.url.strip()
    deel = urlparse(url)
    if bron.soort == "bluesky":
        handle = deel.path.split("/profile/", 1)[1].strip("/").split("/")[0]
        return f"https://bsky.app/profile/{handle}/rss"
    if bron.soort == "mastodon":
        return url.rstrip("/") + ".rss" if not url.endswith(".rss") else url
    if bron.soort == "reddit":
        sub = deel.path.split("/r/", 1)[1].strip("/").split("/")[0]
        return f"https://www.reddit.com/r/{sub}/new/.rss"
    if bron.soort == "youtube":
        if "feeds/videos.xml" in url:
            return url
        m = re.search(r"/channel/(UC[\w-]{22})", deel.path)
        if m:
            return f"https://www.youtube.com/feeds/videos.xml?channel_id={m.group(1)}"
        return ""
    if bron.soort == "rss":
        if deel.netloc.lower().endswith("medium.com") and deel.path.startswith("/@"):
            return f"https://medium.com/feed/{deel.path.strip('/')}"
        return url
    return ""


def standaard_editie(taal: str, land: str) -> str:
    if land == "BE":
        return f"BE:{taal if taal in ('nl', 'fr') else 'nl'}"
    per_land = {"NL": "NL:nl", "FR": "FR:fr", "DE": "DE:de", "GB": "GB:en", "US": "US:en", "AT": "AT:de",
                "CH": "CH:de", "IE": "IE:en", "CA": "CA:en", "AU": "AU:en", "ES": "ES:es", "IT": "IT:it"}
    if land in per_land:
        return per_land[land]
    return {"nl": "NL:nl", "fr": "FR:fr", "de": "DE:de", "es": "ES:es", "it": "IT:it"}.get(taal, "US:en")


def google_url(zoekterm: str, editie: str, extra: str = "") -> str:
    gl, _, taal = editie.partition(":")
    taal = taal or "en"
    hl = f"en-{gl}" if taal == "en" else taal
    q = f"{zoekterm} {extra}".strip()
    return "https://news.google.com/rss/search?" + urlencode({"q": q, "hl": hl, "gl": gl, "ceid": f"{gl}:{taal}"})


def bing_url(zoekterm: str, taal: str, land: str) -> str:
    land = land if len(land) == 2 else "US"
    taal = taal or "en"
    return "https://www.bing.com/news/search?" + urlencode({"q": zoekterm, "format": "rss", "mkt": f"{taal}-{land}"})


def _uniek(id_: str, gebruikt: set[str]) -> str:
    kandidaat, n = id_, 2
    while kandidaat in gebruikt:
        kandidaat = f"{id_}-{n}"
        n += 1
    gebruikt.add(kandidaat)
    return kandidaat


def id_voor_url(url: str) -> str:
    deel = urlparse(url)
    host = deel.netloc.lower().removeprefix("www.")
    return slug(f"{host}{deel.path}")


def id_voor_zoekopdracht(dienst: str, editie: str, zoekterm: str) -> str:
    return slug(f"{dienst}-{editie}-{zoekterm}", 80)


def _lees_lijst(pad: Path, sleutel: str) -> list:
    if not pad.exists():
        return []
    try:
        gegevens = yaml.safe_load(pad.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as fout:
        raise RegisterFout(f"{pad.name} bevat een opmaakfout: {fout}") from fout
    lijst = gegevens.get(sleutel) if isinstance(gegevens, dict) else None
    if lijst is None:
        return []
    if not isinstance(lijst, list):
        raise RegisterFout(f"{pad.name}: '{sleutel}' moet een lijst zijn")
    return lijst


def laad_register(pad_bronnen: Path, pad_zoek: Path) -> tuple[list[Bron], list[str]]:
    """Leest beide registerbestanden. Geeft (bronnen, waarschuwingen) terug.

    Een ongeldige regel wordt overgeslagen met een waarschuwing; een opmaakfout
    in het YAML-bestand zelf doet de verwerking stoppen.
    """
    bronnen: list[Bron] = []
    waarschuwingen: list[str] = []
    gebruikt: set[str] = set()

    for nr, item in enumerate(_lees_lijst(pad_bronnen, "bronnen"), start=1):
        if not isinstance(item, dict):
            waarschuwingen.append(f"bronnen.yml, bron {nr}: geen geldige invoer")
            continue
        naam = str(item.get("naam") or "").strip()
        url = str(item.get("url") or "").strip()
        if not naam or not url.startswith(("http://", "https://")):
            waarschuwingen.append(f"bronnen.yml, bron {nr} ({naam or 'zonder naam'}): naam en een volledig adres (https://...) zijn verplicht")
            continue
        type_ = str(item.get("type") or "medium").strip().lower()
        if type_ not in TYPES or type_ == "zoekopdracht":
            waarschuwingen.append(f"bronnen.yml, {naam}: onbekend type '{type_}', 'medium' gebruikt")
            type_ = "medium"
        soort = str(item.get("soort") or "").strip().lower() or detecteer_soort(url)
        if soort not in SOORTEN or soort in ZOEKDIENSTEN:
            waarschuwingen.append(f"bronnen.yml, {naam}: onbekende soort '{soort}', automatisch bepaald")
            soort = detecteer_soort(url)
        id_ = str(item.get("id") or "").strip() or id_voor_url(url)
        bronnen.append(Bron(
            id=_uniek(slug(id_, 80), gebruikt),
            naam=naam,
            soort=soort,
            type=type_,
            url=url,
            taal=str(item.get("taal") or "").strip().lower(),
            land=_landcode(item.get("land")) or "INT",
            alleen_vegan=als_bool(item.get("alleen_vegan"), standaard=type_ in {"medium", "overheid"}),
            actief=als_bool(item.get("actief"), standaard=True),
            notitie=str(item.get("notitie") or "").strip(),
        ))

    for nr, item in enumerate(_lees_lijst(pad_zoek, "zoekopdrachten"), start=1):
        if not isinstance(item, dict) or not str(item.get("zoekterm") or "").strip():
            waarschuwingen.append(f"zoekopdrachten.yml, zoekopdracht {nr}: zoekterm ontbreekt")
            continue
        zoekterm = str(item["zoekterm"]).strip()
        dienst = str(item.get("dienst") or "google").strip().lower()
        if dienst not in ZOEKDIENSTEN:
            waarschuwingen.append(f"zoekopdrachten.yml, '{zoekterm}': onbekende dienst '{dienst}', google gebruikt")
            dienst = "google"
        taal = str(item.get("taal") or "").strip().lower()
        land = _landcode(item.get("land")) or "INT"
        editie = str(item.get("editie") or "").strip() or standaard_editie(taal, land)
        if not taal and ":" in editie:
            taal = editie.split(":", 1)[1]
        naam = str(item.get("naam") or "").strip() or f"{SOORT_NAMEN[dienst]}: {zoekterm}"
        id_ = str(item.get("id") or "").strip() or id_voor_zoekopdracht(dienst, editie, zoekterm)
        bronnen.append(Bron(
            id=_uniek(slug(id_, 80), gebruikt),
            naam=naam,
            soort=dienst,
            type="wetenschap" if dienst == "pubmed" else "zoekopdracht",
            zoekterm=zoekterm,
            editie=editie,
            taal=taal,
            land=land,
            alleen_vegan=als_bool(item.get("alleen_vegan"), standaard=dienst != "pubmed"),
            actief=als_bool(item.get("actief"), standaard=True),
            notitie=str(item.get("notitie") or "").strip(),
        ))
    return bronnen, waarschuwingen
