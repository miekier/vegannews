"""Ophalen van feeds: RSS/Atom, websites (feed-ontdekking), Google/Bing Nieuws, sociale media en PubMed."""

from __future__ import annotations

import html
import re
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urljoin, urlparse

import feedparser
import requests
import urllib3

from .bronnen import Bron, bing_url, google_url, sociaal_platform, standaard_editie, vaste_feed
from .config import Instellingen
from .staat import Staat
from .tekst import kort_in, zuiver_html

MAX_GROOTTE = 6 * 1024 * 1024
HERONTDEK_NA_DAGEN = 30
HERPROBEER_EIGEN_FEED_NA_DAGEN = 3   # na een terugval op Google Nieuws: eigen feed snel opnieuw proberen
VEELGEBRUIKTE_FEEDPADEN = (
    "feed/", "rss", "rss.xml", "feed.xml", "atom.xml", "index.xml", "rss/", "feed",
    "arc/outboundfeeds/rss/?outputType=xml", "?feed=rss2", "?format=feed&type=rss", "blog/feed/",
    "nieuws/feed/", "news/feed/", "actualites/feed/", "nieuws/rss", "news/rss", "nl/rss", "fr/rss",
    "blog?format=rss", "blog-feed.xml", "feeds/posts/default",
)
MAX_ONTDEKKINGSPOGINGEN = 18


class OphaalFout(Exception):
    pass


@dataclass
class RuwBericht:
    titel: str
    url: str
    samenvatting: str = ""
    gepubliceerd: datetime | None = None
    uitgever: str = ""
    uitgever_url: str = ""


@dataclass
class Resultaat:
    bron: Bron
    berichten: list[RuwBericht] = field(default_factory=list)
    status: str = "ok"          # ok, ongewijzigd, leeg, fout
    melding: str = ""
    feed: str = ""


def is_feed(inhoud: bytes) -> bool:
    kop = inhoud[:4000].lstrip().lower()
    return any(teken in kop for teken in (b"<rss", b"<feed", b"<rdf:rdf"))


_LINK_RE = re.compile(r"<link\b[^>]*>", re.I)
_ATTR_RE = re.compile(r"([\w:-]+)\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)")


def ontdek_feedlinks(pagina: str, basis_url: str) -> list[str]:
    """Zoekt <link rel="alternate" type="application/rss+xml"> in een HTML-pagina."""
    gevonden: list[str] = []
    for tag in _LINK_RE.findall(pagina):
        attrs = {k.lower(): v.strip("\"'") for k, v in _ATTR_RE.findall(tag)}
        rel = attrs.get("rel", "").lower()
        soort = attrs.get("type", "").lower()
        href = attrs.get("href")
        if "alternate" not in rel or not href or not ("rss" in soort or "atom" in soort):
            continue
        url = urljoin(basis_url, html.unescape(href))
        if "comment" in url.lower() or "reacties" in url.lower():
            continue
        if url not in gevonden:
            gevonden.append(url)
    return gevonden


def _domein(url: str) -> str:
    host = urlparse(url).netloc.lower().split(":")[0].removeprefix("www.")
    delen = host.split(".")
    if len(delen) > 2 and delen[-2] in {"co", "com", "org", "net", "ac", "gov"} and len(delen[-1]) == 2:
        return ".".join(delen[-3:])
    return ".".join(delen[-2:])


def zelfde_website(url: str, *basissen: str) -> bool:
    """Ligt url op hetzelfde domein als een van de basisadressen (subdomeinen inbegrepen)?"""
    return any(_domein(url) == _domein(b) for b in basissen if b)


_A_RE = re.compile(r"<a\b[^>]*?href\s*=\s*(\"[^\"]*\"|'[^']*')[^>]*>(.*?)</a>", re.I | re.S)
_RSS_LABELS = {"rss", "rss feed", "rss-feed", "rss feeds", "rss-feeds", "flux rss", "feeds", "feed"}


def ontdek_rsslinks(pagina: str, basis_url: str) -> list[str]:
    """Zoekt <a>-links naar een feed of een RSS-overzichtspagina op dezelfde website."""
    host = urlparse(basis_url).netloc.lower().removeprefix("www.")
    gevonden: list[str] = []
    for href, label in _A_RE.findall(pagina):
        url = urljoin(basis_url, html.unescape(href.strip("\"'")))
        doel = urlparse(url)
        doelhost = doel.netloc.lower().removeprefix("www.")
        if doel.scheme not in ("http", "https") or not (doelhost == host or doelhost.endswith("." + host)):
            continue
        pad = f"{doel.path}?{doel.query}".lower()
        if "comment" in pad or "sitemap" in pad:
            continue
        feedachtig = (re.search(r"rss|atom|/feeds?(/|\.|\?|$)", pad) or doel.path.lower().endswith((".xml", ".rss", ".atom"))
                      or doelhost.startswith(("rss.", "feeds.", "feed.")) or zuiver_html(label).lower() in _RSS_LABELS)
        if not feedachtig:
            continue
        if url not in gevonden:
            gevonden.append(url)
    gevonden.sort(key=lambda u: (urlparse(u).path.count("/"), len(u)))
    return gevonden[:8]


_STANDAARDTEKST = re.compile(
    r"\s*(The post .{0,300}? appeared first on|Het bericht .{0,300}? verscheen eerst op|"
    r"L[’']article .{0,300}? est apparu en premier sur|Der Beitrag .{0,300}? erschien zuerst auf)\b.*$"
    r"|\s*\b(Continue reading|Read more|Lees meer|Lees verder|Lire la suite|Weiterlesen)\b.*$",
    re.S,
)


def schoon_samenvatting(tekst: str) -> str:
    tekst = _STANDAARDTEKST.sub("", tekst)
    return re.sub(r"\s*\[(…|\.\.\.)\]\s*$", "…", tekst).strip()


def _datum(struct) -> datetime | None:
    if not struct:
        return None
    try:
        return datetime(*struct[:6], tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _bing_doel(link: str) -> str:
    if "bing.com/news/apiclick" in link:
        doel = parse_qs(urlparse(link).query).get("url")
        if doel:
            return doel[0]
    return link


def lees_feed(inhoud: bytes, bron: Bron) -> list[RuwBericht]:
    feed = feedparser.parse(inhoud)
    if not feed.entries and (feed.bozo or not is_feed(inhoud)):
        raise OphaalFout("geen geldige RSS- of Atom-feed")
    berichten: list[RuwBericht] = []
    for e in feed.entries:
        titel = zuiver_html(e.get("title", ""))
        inhoud_tekst = e.get("summary", "") or ""
        if not inhoud_tekst and e.get("content"):
            inhoud_tekst = e["content"][0].get("value", "")
        if not inhoud_tekst and e.get("media_description"):
            inhoud_tekst = e.get("media_description", "")
        samenvatting = schoon_samenvatting(zuiver_html(inhoud_tekst))
        link = (e.get("link") or "").strip()
        uitgever = ""
        uitgever_url = ""
        bron_info = e.get("source") or {}
        if bron.soort == "google":
            uitgever = (bron_info.get("title") or "").strip()
            uitgever_url = (bron_info.get("href") or "").strip()
            if uitgever and titel.endswith(f" - {uitgever}"):
                titel = titel[: -len(uitgever) - 3].strip()
            if sociaal_platform(uitgever_url) and uitgever and samenvatting.endswith(uitgever):
                # Bij een post op sociale media bevat de beschrijving het (volledigere) bijschrift.
                samenvatting = samenvatting[: -len(uitgever)].strip()
                if len(samenvatting) <= len(titel) + 10:
                    samenvatting = ""
            else:
                samenvatting = ""  # Google geeft enkel de titel en een lijst links
        elif bron.soort == "bing":
            link = _bing_doel(link)
            uitgever = (e.get("news_source") or "").strip()
        if not titel and samenvatting:  # Bluesky en Mastodon: berichten zonder titel
            titel = kort_in(samenvatting, 140)
            if titel == samenvatting:
                samenvatting = ""
        if not titel or not link.startswith("http"):
            continue
        if samenvatting and samenvatting.casefold().startswith(titel.casefold().rstrip("…")):
            rest = samenvatting[len(titel):].strip(" -–—:|")
            samenvatting = rest if len(rest) > 30 else ""
        berichten.append(RuwBericht(
            titel=titel,
            url=link,
            samenvatting=kort_in(samenvatting, 420),
            gepubliceerd=_datum(e.get("published_parsed") or e.get("updated_parsed")),
            uitgever=uitgever,
            uitgever_url=uitgever_url,
        ))
    return berichten


class Ophaler:
    def __init__(self, staat: Staat, inst: Instellingen, sessie: requests.Session | None = None):
        self.staat = staat
        self.inst = inst
        self.sessie = sessie or self._maak_sessie(inst.repository)
        self._slot = threading.Lock()
        self._google_slot = threading.Lock()
        self._laatste_google = 0.0

    @staticmethod
    def _maak_sessie(repo: str) -> requests.Session:
        sessie = requests.Session()
        adres = f"https://github.com/{repo}" if repo else "https://github.com"
        sessie.headers.update({
            "User-Agent": f"Mozilla/5.0 (compatible; Vegannieuws/1.0; +{adres})",
            "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/html;q=0.8, */*;q=0.5",
            "Accept-Language": "nl-BE,nl;q=0.9,fr;q=0.8,en;q=0.7",
        })
        adapter = requests.adapters.HTTPAdapter(pool_connections=32, pool_maxsize=32)
        sessie.mount("https://", adapter)
        sessie.mount("http://", adapter)
        return sessie

    # -- HTTP ---------------------------------------------------------------

    def _wacht_op_google(self) -> None:
        with self._google_slot:
            wachten = self._laatste_google + self.inst.google_pauze_s - time.monotonic()
            if wachten > 0:
                time.sleep(wachten)
            self._laatste_google = time.monotonic()

    def get(self, url: str, conditioneel: bool = False, extra_headers: dict | None = None,
            snel: bool = False) -> requests.Response:
        """HTTP GET. Met snel=True (feed-ontdekking): korte time-outs en geen tweede poging."""
        headers = dict(extra_headers or {})
        if conditioneel:
            validators = self.staat.http.get(url) or {}
            if validators.get("etag"):
                headers["If-None-Match"] = validators["etag"]
            if validators.get("gewijzigd"):
                headers["If-Modified-Since"] = validators["gewijzigd"]
        is_google = urlparse(url).netloc.endswith("news.google.com")
        laatste_fout: Exception | None = None
        for poging in range(1 if snel else 2):
            if is_google:
                self._wacht_op_google()
            try:
                antwoord = self.sessie.get(url, headers=headers, timeout=(5, 10) if snel else (10, 25),
                                           allow_redirects=True, stream=True)
                try:
                    inhoud = antwoord.raw.read(MAX_GROOTTE + 1, decode_content=True)
                finally:
                    antwoord.close()
                if len(inhoud) > MAX_GROOTTE:
                    raise OphaalFout("antwoord groter dan 6 MB")
                antwoord._content = inhoud
                antwoord._content_consumed = True
            except (requests.ConnectionError, requests.Timeout, urllib3.exceptions.HTTPError) as fout:
                laatste_fout = fout
                if not snel:
                    time.sleep(3)
                continue
            if antwoord.status_code in (429, 503) and poging == 0 and not snel:
                time.sleep(20 if is_google else 5)
                continue
            if conditioneel and antwoord.status_code == 200:
                self._onthoud_validators(url, antwoord)
            return antwoord
        if isinstance(laatste_fout, (requests.Timeout, urllib3.exceptions.TimeoutError)):
            raise OphaalFout("time-out: de server antwoordde niet op tijd")
        raise OphaalFout(f"verbinding mislukt ({type(laatste_fout).__name__})")

    def _onthoud_validators(self, url: str, antwoord: requests.Response) -> None:
        etag = antwoord.headers.get("ETag", "")
        gewijzigd = antwoord.headers.get("Last-Modified", "")
        with self._slot:
            if etag or gewijzigd:
                self.staat.http[url] = {"etag": etag, "gewijzigd": gewijzigd}
            else:
                self.staat.http.pop(url, None)

    @staticmethod
    def _controleer(antwoord: requests.Response) -> None:
        if antwoord.status_code >= 400:
            raise OphaalFout(f"HTTP {antwoord.status_code}")

    # -- per soort ----------------------------------------------------------

    def haal(self, bron: Bron, extra_zoekterm: str = "") -> Resultaat:
        try:
            if bron.soort == "pubmed":
                return Resultaat(bron, self._pubmed(bron), feed="PubMed E-utilities")
            if bron.soort == "google":
                extra = extra_zoekterm or bron.recentheid or self.inst.google_recentheid
                return self._haal_feed(bron, google_url(bron.zoekterm, bron.editie, extra), conditioneel=False)
            if bron.soort == "bing":
                return self._haal_feed(bron, bing_url(bron.zoekterm, bron.taal, bron.land), conditioneel=False)
            if bron.soort == "youtube":
                return self._haal_feed(bron, self._youtube_feed(bron))
            if bron.soort == "website":
                return self._haal_website(bron)
            feed = vaste_feed(bron)
            if not feed:
                raise OphaalFout("geen feedadres af te leiden uit de URL")
            return self._haal_feed(bron, feed)
        except OphaalFout as fout:
            return Resultaat(bron, status="fout", melding=str(fout))
        except Exception as fout:  # een kapotte bron mag de rest niet tegenhouden
            return Resultaat(bron, status="fout", melding=f"onverwachte fout: {type(fout).__name__}: {fout}"[:300])

    def _haal_feed(self, bron: Bron, feed: str, conditioneel: bool = True) -> Resultaat:
        antwoord = self.get(feed, conditioneel=conditioneel)
        if antwoord.status_code == 304:
            return Resultaat(bron, status="ongewijzigd", feed=feed)
        self._controleer(antwoord)
        berichten = lees_feed(antwoord.content, bron)
        return Resultaat(bron, berichten, status="ok" if berichten else "leeg", feed=feed)

    def _haal_website(self, bron: Bron) -> Resultaat:
        bewaard = self.staat.feeds.get(bron.id) or {}
        feed = bewaard.get("feed")
        if feed and bewaard.get("url") == bron.url and zelfde_website(feed, bron.url, bewaard.get("basis", "")):
            gevonden = datetime.fromisoformat(bewaard.get("gevonden", "2000-01-01T00:00:00+00:00"))
            if datetime.now(timezone.utc) - gevonden < timedelta(days=HERONTDEK_NA_DAGEN):
                try:
                    return self._haal_feed(bron, feed)
                except OphaalFout:
                    pass  # opnieuw zoeken
        elif bewaard.get("via_google") and bewaard.get("url") == bron.url:
            gevonden = datetime.fromisoformat(bewaard.get("gevonden", "2000-01-01T00:00:00+00:00"))
            if datetime.now(timezone.utc) - gevonden < timedelta(days=HERPROBEER_EIGEN_FEED_NA_DAGEN):
                return self._via_google(bron, bewaard.get("reden", "geen eigen feed"))
        nu = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            feed, basis = self.zoek_feed(bron.url)
        except OphaalFout as fout:
            with self._slot:
                self.staat.feeds[bron.id] = {"url": bron.url, "via_google": True, "reden": str(fout), "gevonden": nu}
            return self._via_google(bron, str(fout))
        with self._slot:
            self.staat.feeds[bron.id] = {"url": bron.url, "feed": feed, "basis": basis, "gevonden": nu}
        return self._haal_feed(bron, feed)

    def _via_google(self, bron: Bron, reden: str) -> Resultaat:
        """Website zonder bruikbare feed: volg ze via Google Nieuws met site:domein."""
        domein = urlparse(bron.url).netloc.lower().removeprefix("www.")
        editie = standaard_editie(bron.taal, bron.land if bron.land != "INT" else "")
        feed = google_url(f"site:{domein}", editie, self.inst.google_recentheid)
        res = self._haal_feed(replace(bron, soort="google"), feed, conditioneel=False)
        res.bron = bron
        res.melding = f"geen eigen feed ({reden}); gevolgd via Google Nieuws"
        return res

    def ontdek_feed(self, url: str) -> str:
        return self.zoek_feed(url)[0]

    def zoek_feed(self, url: str) -> tuple[str, str]:
        """Zoekt het feedadres van een website; geeft (feed, adres van de startpagina na omleiding) terug.

        Volgorde: de pagina zelf, <link>-tags, RSS-links in de pagina, gangbare paden. Een
        RSS-overzichtspagina (HTML met links naar feeds) wordt één niveau diep doorzocht.
        """
        fout_startpagina = ""
        try:
            antwoord = self.get(url)
        except OphaalFout as fout:
            antwoord, fout_startpagina = None, str(fout)
        kandidaten: list[str] = []
        basis_url = url
        if antwoord is not None and antwoord.status_code < 400:
            if is_feed(antwoord.content):
                return antwoord.url, antwoord.url
            basis_url = antwoord.url
            kandidaten = ontdek_feedlinks(antwoord.text, basis_url) + ontdek_rsslinks(antwoord.text, basis_url)
        elif antwoord is not None:
            fout_startpagina = f"HTTP {antwoord.status_code}"
        deel = urlparse(basis_url)
        wortel = f"{deel.scheme}://{deel.netloc}/"
        basis = basis_url if basis_url.endswith("/") else basis_url + "/"
        for pad in VEELGEBRUIKTE_FEEDPADEN:
            kandidaten += [urljoin(b, pad) for b in dict.fromkeys((basis, wortel))]
        kandidaten = list(dict.fromkeys(kandidaten))
        overzicht_doorzocht = False
        i = pogingen = 0
        while i < len(kandidaten) and pogingen < MAX_ONTDEKKINGSPOGINGEN:
            kandidaat = kandidaten[i]
            i += 1
            pogingen += 1
            try:
                poging = self.get(kandidaat, snel=True)
            except OphaalFout:
                continue
            if poging.status_code != 200:
                continue
            if is_feed(poging.content):
                if not zelfde_website(poging.url, url, basis_url):
                    continue  # omgeleid naar een andere website (bv. een zustertitel)
                try:
                    if lees_feed(poging.content, Bron("x", "x", "rss", "medium")):
                        return poging.url, basis_url
                except OphaalFout:
                    pass
                continue
            if not overzicht_doorzocht and "html" in poging.headers.get("Content-Type", "") and poging.url.rstrip("/") != basis_url.rstrip("/"):
                extra = [k for k in ontdek_feedlinks(poging.text, poging.url) + ontdek_rsslinks(poging.text, poging.url)
                         if k not in kandidaten]
                if extra:
                    overzicht_doorzocht = True
                    kandidaten[i:i] = extra[:6]
        if fout_startpagina:
            raise OphaalFout(f"{fout_startpagina}: de website blokkeert automatische toegang of is onbereikbaar")
        raise OphaalFout("geen RSS-feed gevonden op deze website")

    def _youtube_feed(self, bron: Bron) -> str:
        feed = vaste_feed(bron)
        if feed:
            return feed
        bewaard = self.staat.feeds.get(bron.id) or {}
        if bewaard.get("url") == bron.url and bewaard.get("feed"):
            return bewaard["feed"]
        antwoord = self.get(bron.url, extra_headers={"Cookie": "CONSENT=YES+cb; SOCS=CAI"})
        self._controleer(antwoord)
        m = re.search(r"feeds/videos\.xml\?channel_id=(UC[\w-]{22})", antwoord.text) or \
            re.search(r'"(?:channelId|externalId)":"(UC[\w-]{22})"', antwoord.text)
        if not m:
            raise OphaalFout("YouTube-kanaal niet gevonden")
        feed = f"https://www.youtube.com/feeds/videos.xml?channel_id={m.group(1)}"
        with self._slot:
            self.staat.feeds[bron.id] = {
                "url": bron.url, "feed": feed, "gevonden": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        return feed

    def _pubmed(self, bron: Bron, dagen: int = 7) -> list[RuwBericht]:
        basis = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
        zoek = self.sessie.get(basis + "esearch.fcgi", timeout=(10, 30), params={
            "db": "pubmed", "term": bron.zoekterm, "reldate": dagen, "datetype": "edat",
            "retmax": 60, "retmode": "json", "tool": "vegannieuws",
        })
        self._controleer(zoek)
        ids = zoek.json().get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []
        time.sleep(0.4)  # NCBI: max. 3 verzoeken per seconde zonder sleutel
        detail = self.sessie.get(basis + "efetch.fcgi", timeout=(10, 60), params={
            "db": "pubmed", "id": ",".join(ids), "retmode": "xml", "tool": "vegannieuws",
        })
        self._controleer(detail)
        return lees_pubmed(detail.content)


def lees_pubmed(inhoud: bytes) -> list[RuwBericht]:
    berichten: list[RuwBericht] = []
    wortel = ET.fromstring(inhoud)
    for artikel in wortel.iter("PubmedArticle"):
        pmid = artikel.findtext(".//MedlineCitation/PMID") or ""
        titel_el = artikel.find(".//ArticleTitle")
        titel = zuiver_html("".join(titel_el.itertext())) if titel_el is not None else ""
        delen = ["".join(a.itertext()) for a in artikel.findall(".//Abstract/AbstractText")]
        samenvatting = zuiver_html(" ".join(delen))
        tijdschrift = artikel.findtext(".//Journal/Title") or ""
        datum = None
        for d in artikel.findall(".//PubmedData/History/PubMedPubDate"):
            if d.get("PubStatus") == "entrez":
                try:
                    datum = datetime(int(d.findtext("Year")), int(d.findtext("Month")), int(d.findtext("Day")),
                                     tzinfo=timezone.utc)
                except (TypeError, ValueError):
                    datum = None
        if not pmid or not titel:
            continue
        berichten.append(RuwBericht(
            titel=titel.rstrip("."),
            url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            samenvatting=kort_in(samenvatting, 600),
            gepubliceerd=datum,
            uitgever=tijdschrift,
        ))
    return berichten
