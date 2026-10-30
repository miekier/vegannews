from datetime import datetime, timezone

from conftest import FakeSessie, fixture

from vegannieuws.bronnen import Bron, bing_url, detecteer_soort, google_url, laad_register, vaste_feed
from vegannieuws.config import Instellingen
from vegannieuws.ophalen import Ophaler, lees_feed, lees_pubmed, ontdek_feedlinks
from vegannieuws.staat import Staat


def test_register(tmp_path):
    (tmp_path / "bronnen.yml").write_text("""
bronnen:
  - naam: EVA vzw
    url: https://www.evavzw.be
    type: organisatie
    land: BE
    taal: nl
  - naam: Bluesky-account
    url: https://bsky.app/profile/voorbeeld.bsky.social
    type: persoon
    land: NO
  - naam: Krant
    url: https://www.krant.be
    type: medium
    actief: nee
  - naam: Zonder adres
  - naam: Onbekend type
    url: https://www.voorbeeld.org
    type: raar
""", encoding="utf-8")
    (tmp_path / "zoekopdrachten.yml").write_text("""
zoekopdrachten:
  - zoekterm: vegan
    land: BE
    taal: fr
  - zoekterm: vegan*[tiab]
    dienst: pubmed
""", encoding="utf-8")
    bronnen, waarschuwingen = laad_register(tmp_path / "bronnen.yml", tmp_path / "zoekopdrachten.yml")
    per_naam = {b.naam: b for b in bronnen}
    assert per_naam["EVA vzw"].soort == "website"
    assert per_naam["EVA vzw"].alleen_vegan is False      # organisatie: standaard alles bewaren
    assert per_naam["EVA vzw"].relatie == "primair"
    assert per_naam["Bluesky-account"].soort == "bluesky"
    assert per_naam["Bluesky-account"].land == "NO"        # YAML leest NO als false
    assert per_naam["Krant"].actief is False
    assert per_naam["Krant"].alleen_vegan is True          # medium: standaard filteren
    assert per_naam["Onbekend type"].type == "medium"
    google = per_naam["Google Nieuws: vegan"]
    assert (google.soort, google.editie, google.taal, google.relatie) == ("google", "BE:fr", "fr", "secundair")
    pubmed = per_naam["PubMed: vegan*[tiab]"]
    assert pubmed.type == "wetenschap" and pubmed.alleen_vegan is False
    assert len({b.id for b in bronnen}) == len(bronnen)
    assert len(waarschuwingen) == 2


def test_soort_en_vaste_feed():
    assert detecteer_soort("https://www.youtube.com/@EarthlingEd") == "youtube"
    assert detecteer_soort("https://mastodon.social/@iemand") == "mastodon"
    assert detecteer_soort("https://www.reddit.com/r/vegan/") == "reddit"
    assert detecteer_soort("https://www.evavzw.be/nieuws") == "website"
    assert vaste_feed(Bron("a", "a", "bluesky", "persoon", url="https://bsky.app/profile/x.bsky.social")) == \
        "https://bsky.app/profile/x.bsky.social/rss"
    assert vaste_feed(Bron("a", "a", "mastodon", "persoon", url="https://mastodon.social/@iemand")) == \
        "https://mastodon.social/@iemand.rss"
    assert vaste_feed(Bron("a", "a", "reddit", "medium", url="https://www.reddit.com/r/vegan/")) == \
        "https://www.reddit.com/r/vegan/new/.rss"
    kanaal = "https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv"
    assert vaste_feed(Bron("a", "a", "youtube", "persoon", url=kanaal)).endswith("channel_id=UCabcdefghijklmnopqrstuv")
    assert vaste_feed(Bron("a", "a", "youtube", "persoon", url="https://www.youtube.com/@iemand")) == ""


def test_zoek_urls():
    url = google_url("vegan restaurant", "BE:nl", "when:7d")
    assert "q=vegan+restaurant+when%3A7d" in url and "hl=nl" in url and "gl=BE" in url and "ceid=BE%3Anl" in url
    assert "hl=en-US" in google_url("vegan", "US:en")
    assert "mkt=fr-BE" in bing_url("vegan", "fr", "BE")


def test_google_nieuws_feed():
    bron = Bron("g", "Google", "google", "zoekopdracht", zoekterm="vegan", editie="BE:nl")
    berichten = lees_feed(fixture("google_nieuws.xml"), bron)
    assert len(berichten) == 4
    eerste = berichten[0]
    assert eerste.titel == "Nieuw vegan restaurant opent in Gent"
    assert eerste.uitgever == "Het Nieuwsblad"
    assert eerste.uitgever_url == "https://www.nieuwsblad.be"
    assert eerste.samenvatting == ""
    assert eerste.gepubliceerd == datetime(2026, 10, 29, 8, 12, tzinfo=timezone.utc)


def test_wordpress_feed_zonder_standaardtekst():
    berichten = lees_feed(fixture("wordpress.xml"), Bron("v", "vegconomist", "rss", "medium"))
    assert berichten[0].samenvatting.startswith("Ghent-based Those Vegan Cowboys")
    assert "appeared first" not in berichten[0].samenvatting
    assert "utm_source" in berichten[0].url  # opkuis gebeurt bij het bepalen van de id


def test_bluesky_feed_titel_uit_tekst():
    berichten = lees_feed(fixture("bluesky.xml"), Bron("b", "b", "bluesky", "persoon"))
    assert berichten[0].titel.startswith("Grote dag voor de dieren")
    assert berichten[0].url.startswith("https://bsky.app/profile/")


def test_youtube_feed():
    berichten = lees_feed(fixture("youtube.xml"), Bron("y", "y", "youtube", "persoon"))
    assert berichten[0].titel == "Why I Went Vegan"
    assert "animal rights" in berichten[0].samenvatting


def test_pubmed():
    berichten = lees_pubmed(fixture("pubmed.xml"))
    assert berichten[0].titel == "Vitamin B12 status in vegan children: a cross-sectional study"
    assert berichten[0].url == "https://pubmed.ncbi.nlm.nih.gov/41234567/"
    assert berichten[0].uitgever == "Nutrients"
    assert "B12 status was adequate" in berichten[0].samenvatting
    assert berichten[0].gepubliceerd.date().isoformat() == "2026-10-28"


def test_ontdek_feedlinks_slaat_reacties_over():
    links = ontdek_feedlinks(fixture("website.html").decode(), "https://www.evavzw.be/")
    assert links == ["https://www.evavzw.be/feed/"]


def test_website_ontdekking_cache_en_304():
    def feed(url, headers):
        from conftest import maak_antwoord
        if headers.get("If-None-Match") == '"v1"':
            return maak_antwoord(url, 304)
        return maak_antwoord(url, 200, fixture("wordpress.xml"), {"ETag": '"v1"'})

    sessie = FakeSessie({"evavzw.be/feed/": feed, "evavzw.be": (200, fixture("website.html"), {})})
    staat = Staat()
    ophaler = Ophaler(staat, Instellingen(), sessie)
    bron = Bron("eva", "EVA", "website", "organisatie", url="https://www.evavzw.be")
    eerste = ophaler.haal(bron)
    assert eerste.status == "ok" and len(eerste.berichten) == 2
    assert staat.feeds["eva"]["feed"] == "https://www.evavzw.be/feed/"
    tweede = ophaler.haal(bron)
    assert tweede.status == "ongewijzigd"
    assert sum(1 for url, _ in sessie.verzoeken if url == "https://www.evavzw.be") == 1  # feed uit cache


def test_fouten_worden_status():
    sessie = FakeSessie({"kapot.be/feed": (500, b"", {}), "geenfeed.be": (200, b"<html>geen feed</html>", {})})
    ophaler = Ophaler(Staat(), Instellingen(), sessie)
    res = ophaler.haal(Bron("x", "x", "rss", "medium", url="https://kapot.be/feed"))
    assert res.status == "fout" and "HTTP 500" in res.melding
    res = ophaler.haal(Bron("y", "y", "website", "medium", url="https://geenfeed.be"))
    assert res.status == "fout" and "geen RSS-feed" in res.melding


def test_bing_link_naar_bron():
    xml = b"""<?xml version="1.0"?><rss version="2.0" xmlns:News="https://www.bing.com/news/search?q=vegan&amp;format=rss">
    <channel><title>Bing</title><item><title>Vegan zaak opent</title>
    <link>http://www.bing.com/news/apiclick.aspx?ref=FexRss&amp;aid=&amp;tid=1&amp;url=https%3a%2f%2fwww.hln.be%2fartikel&amp;c=1</link>
    <description>Een nieuwe vegan zaak.</description><pubDate>Thu, 29 Oct 2026 08:00:00 GMT</pubDate>
    <News:Source>HLN</News:Source></item></channel></rss>"""
    berichten = lees_feed(xml, Bron("b", "Bing", "bing", "zoekopdracht"))
    assert berichten[0].url == "https://www.hln.be/artikel"
    assert berichten[0].uitgever == "HLN"


def test_ontdekking_via_rss_overzichtspagina():
    from conftest import maak_antwoord
    startpagina = b'<html><body><footer><a href="/nl/rss">RSS</a></footer></body></html>'
    overzicht = b'<html><body><a href="https://rss.krant.be/nieuws.xml">Alle nieuws</a></body></html>'

    def overzichtspagina(url, headers):
        return maak_antwoord(url, 200, overzicht, {"Content-Type": "text/html; charset=utf-8"})

    sessie = FakeSessie({
        "rss.krant.be/nieuws.xml": (200, fixture("wordpress.xml"), {}),
        "krant.be/nl/rss": overzichtspagina,
        "https://www.krant.be/": (200, startpagina, {"Content-Type": "text/html"}),
    })
    ophaler = Ophaler(Staat(), Instellingen(), sessie)
    assert ophaler.ontdek_feed("https://www.krant.be/") == "https://rss.krant.be/nieuws.xml"


def test_ontdekking_na_403_op_startpagina():
    sessie = FakeSessie({
        "https://www.slot.be/feed/": (200, fixture("wordpress.xml"), {}),
        "https://www.slot.be/": (403, b"geweigerd", {}),
    })
    ophaler = Ophaler(Staat(), Instellingen(), sessie)
    assert ophaler.ontdek_feed("https://www.slot.be/") == "https://www.slot.be/feed/"
    dicht = Ophaler(Staat(), Instellingen(), FakeSessie({"dicht.be": (403, b"", {})}))
    res = dicht.haal(Bron("d", "d", "website", "medium", url="https://www.dicht.be/"))
    assert res.status == "fout" and res.melding.startswith("HTTP 403")
