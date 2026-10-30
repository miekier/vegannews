import json
import shutil

import yaml

from conftest import WORTEL, FakeSessie, fixture

from vegannieuws import ophalen
from vegannieuws.beheer import lees_formulier, verwerk_aanvraag
from vegannieuws.bronnen import laad_register
from vegannieuws.config import Instellingen, Paden
from vegannieuws.ophalen import Ophaler, Resultaat, RuwBericht
from vegannieuws.staat import Staat
from vegannieuws.verzamelen import rapport_markdown, verzamel

FORMULIER = """### Naam

{naam}

### Adres (URL) of zoekterm

{adres}

### Soort bron

{soort}

### Land

België

### Taal

Nederlands

### Welke berichten bewaren?

Alle berichten van deze bron

### Opmerking

_No response_
"""


def test_lees_formulier():
    velden = lees_formulier(FORMULIER.format(naam="EVA", adres="https://x.be", soort="Organisatie"))
    assert velden["naam"] == "EVA" and velden["opmerking"] == ""


def test_formulier_europees_land_en_taal(wortel, monkeypatch):
    paden = _register(wortel)
    monkeypatch.setattr(Ophaler, "haal", lambda self, bron, extra="": Resultaat(bron, [RuwBericht("Wiadomość", "https://p.pl/1")], feed="https://p.pl/feed/"))
    tekst = FORMULIER.format(naam="Polskie Weganie", adres="https://weganie.pl", soort="Organisatie")
    tekst = tekst.replace("België", "Polen").replace("Nederlands", "Pools")
    assert verwerk_aanvraag(paden, Instellingen(), tekst).gewijzigd
    bron = next(b for b in laad_register(paden.bronnen, paden.zoekopdrachten)[0] if b.naam == "Polskie Weganie")
    assert (bron.land, bron.taal) == ("PL", "pl")


def _register(wortel):
    shutil.copy(WORTEL / "bronnen.yml", wortel / "bronnen.yml")
    shutil.copy(WORTEL / "zoekopdrachten.yml", wortel / "zoekopdrachten.yml")
    return Paden(wortel)


def test_bron_toevoegen_en_wijzigen(wortel, monkeypatch):
    paden = _register(wortel)
    aantal = len(laad_register(paden.bronnen, paden.zoekopdrachten)[0])

    def nep_haal(self, bron, extra=""):
        if "kapot" in bron.url:
            return Resultaat(bron, status="fout", melding="geen RSS-feed gevonden op deze website")
        return Resultaat(bron, [RuwBericht("Eerste bericht", "https://nieuw.be/1")], feed="https://nieuw.be/feed/")

    monkeypatch.setattr(Ophaler, "haal", nep_haal)
    uit = verwerk_aanvraag(paden, Instellingen(), FORMULIER.format(naam="Nieuwe Zaak", adres="nieuw.be", soort="Restaurant of horeca"), "7")
    assert uit.gewijzigd and uit.sluiten and "Eerste bericht" in uit.antwoord
    bronnen, waarschuwingen = laad_register(paden.bronnen, paden.zoekopdrachten)
    nieuw = next(b for b in bronnen if b.naam == "Nieuwe Zaak")
    assert (nieuw.url, nieuw.type, nieuw.land, nieuw.alleen_vegan) == ("https://nieuw.be", "horeca", "BE", False)
    assert len(bronnen) == aantal + 1 and not waarschuwingen
    assert "# Bronnenregister" in paden.bronnen.read_text(encoding="utf-8")  # commentaar blijft staan

    dubbel = verwerk_aanvraag(paden, Instellingen(), FORMULIER.format(naam="X", adres="https://www.nieuw.be/", soort="Persoon"))
    assert not dubbel.gewijzigd and "staat al" in dubbel.antwoord

    kapot = verwerk_aanvraag(paden, Instellingen(), FORMULIER.format(naam="K", adres="https://kapot.be", soort="Organisatie"))
    assert not kapot.gewijzigd and not kapot.sluiten and "Instagram" in kapot.antwoord

    zoek = verwerk_aanvraag(paden, Instellingen(), FORMULIER.format(naam="Vegan Gent", adres="vegan Gent", soort="Zoekopdracht in Google Nieuws"))
    assert zoek.gewijzigd
    assert any(b.zoekterm == "vegan Gent" and b.editie == "BE:nl" for b in laad_register(paden.bronnen, paden.zoekopdrachten)[0])

    uitschakelen = "### Bron\n\nNieuwe Zaak\n\n### Actie\n\nUitschakelen (tijdelijk niet meer ophalen)\n\n### Reden\n\n_No response_\n"
    assert verwerk_aanvraag(paden, Instellingen(), uitschakelen).gewijzigd
    assert next(b for b in laad_register(paden.bronnen, paden.zoekopdrachten)[0] if b.naam == "Nieuwe Zaak").actief is False

    inschakelen = uitschakelen.replace("Uitschakelen (tijdelijk niet meer ophalen)", "Opnieuw inschakelen")
    assert verwerk_aanvraag(paden, Instellingen(), inschakelen).gewijzigd
    assert next(b for b in laad_register(paden.bronnen, paden.zoekopdrachten)[0] if b.naam == "Nieuwe Zaak").actief is True

    verwijderen = uitschakelen.replace("Uitschakelen (tijdelijk niet meer ophalen)", "Verwijderen uit het register")
    assert verwerk_aanvraag(paden, Instellingen(), verwijderen.replace("Nieuwe Zaak", "https://www.vegetik.org")).gewijzigd
    namen = {b.naam for b in laad_register(paden.bronnen, paden.zoekopdrachten)[0]}
    assert "Végétik" not in namen and "Nieuwe Zaak" in namen and "ProVeg België (voorheen EVA vzw)" in namen
    yaml.safe_load(paden.bronnen.read_text(encoding="utf-8"))

    onbekend = verwerk_aanvraag(paden, Instellingen(), verwijderen.replace("Nieuwe Zaak", "Bestaat niet"))
    assert not onbekend.gewijzigd and not onbekend.sluiten


def test_verzamel_volledige_run(wortel, monkeypatch):
    (wortel / "bronnen.yml").write_text("""bronnen:
  - naam: vegconomist
    url: https://vegconomist.com/feed/
    type: medium
    land: INT
    taal: en
    alleen_vegan: nee
  - naam: Kapotte bron
    url: https://kapot.be/feed
    soort: rss
    type: medium
""", encoding="utf-8")
    (wortel / "zoekopdrachten.yml").write_text("zoekopdrachten:\n  - zoekterm: vegan\n    land: BE\n    taal: nl\n",
                                              encoding="utf-8")
    sessie = FakeSessie({
        "vegconomist.com/feed": (200, fixture("wordpress.xml"), {}),
        "news.google.com": (200, fixture("google_nieuws.xml"), {}),
    })
    monkeypatch.setattr(Ophaler, "_maak_sessie", staticmethod(lambda repo: sessie))
    monkeypatch.setattr(ophalen.time, "sleep", lambda s: None)
    inst = Instellingen(reserve_vertaling=False, max_leeftijd_dagen=36500, repo="iemand/vegannieuws")
    paden = Paden(wortel)

    rapport = verzamel(paden, inst, gebruik_llm=False, log=lambda *_: None)
    assert rapport.bronnen_actief == 3 and rapport.bronnen_fout == 1
    assert rapport.opgehaald == 6
    assert rapport.nieuw == 4   # Club Brugge weg (niet vegan), twee Gentse berichten samengevoegd
    index = json.loads((wortel / "site/data/index.json").read_text(encoding="utf-8"))
    assert index["repo"] == "iemand/vegannieuws" and index["maanden"] == {"2026-10": 4}
    assert {c["code"] for c in index["categorieen"]} >= {"horeca", "overig"}
    maand = json.loads((wortel / "site/data/berichten/2026-10.json").read_text(encoding="utf-8"))
    gent = next(b for b in maand["berichten"] if "Gent" in b["titel"])
    assert gent["regio"] == "BE" and gent["plaats"] == "Gent" and len(gent["extra"]) == 1
    utrecht = next(b for b in maand["berichten"] if "Utrecht" in b["titel"])
    assert utrecht["regio"] == "INT" and utrecht["land"] == "NL"
    cowboys = next(b for b in maand["berichten"] if "Cowboys" in b["titel"])
    assert cowboys["regio"] == "BE" and "bedrijven" in cowboys["categorieen"]
    bronnen = json.loads((wortel / "site/data/bronnen.json").read_text(encoding="utf-8"))["bronnen"]
    kapot = next(b for b in bronnen if b["naam"] == "Kapotte bron")
    assert kapot["status"] == "fout" and kapot["fouten_op_rij"] == 1
    assert "Kapotte bron" in rapport_markdown(rapport)

    tweede = verzamel(paden, inst, gebruik_llm=False, log=lambda *_: None)
    assert tweede.nieuw == 0
    staat = Staat.laad(paden.staat)
    assert staat.bronnen["kapot-be-feed"]["fouten_op_rij"] == 2


def test_regio_zoekresultaat_volgt_domein_van_medium():
    from datetime import datetime, timedelta, timezone
    from zoneinfo import ZoneInfo

    from vegannieuws.bronnen import Bron
    from vegannieuws.classificatie import laad_lexicon
    from vegannieuws.locatie import Geo
    from vegannieuws.verzamelen import maak_bericht

    nu = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
    lexicon, geo, tz = laad_lexicon(WORTEL / "categorieen.yml"), Geo(), ZoneInfo("Europe/Brussels")
    google = Bron("g", "Google Nieuws: vegan", "google", "zoekopdracht", zoekterm="vegan", editie="BE:nl", land="BE")
    eigen = Bron("e", "Bruzz", "website", "medium", url="https://www.bruzz.be", land="BE")

    def regio(bron, uitgever_url):
        ruw = RuwBericht("Vegan koekjes: het recept van de week", "https://x.com/1", gepubliceerd=nu,
                         uitgever="Medium", uitgever_url=uitgever_url)
        b = maak_bericht(ruw, bron, nu, tz, nu - timedelta(days=60), lexicon, geo)
        return b.regio, b.land

    assert regio(google, "https://www.cuisineaz.com") == ("INT", "")   # Franse site, generiek domein
    assert regio(google, "https://www.nieuwsblad.be") == ("BE", "BE")  # Belgisch domein
    assert regio(eigen, "") == ("BE", "BE")                           # eigen feed van een Belgisch medium


def test_opnieuw_gezien_bericht_krijgt_nieuwe_indeling(tmp_path):
    from vegannieuws.archief import Archief
    from vegannieuws.model import Bericht

    archief = Archief(tmp_path)
    oud = Bericht(id="a1", titel="Vegan bakkerij opent", url="https://x.be/1", bron="b", bron_naam="b",
                  datum="2026-10-29", regio="BE", land="BE", categorieen=["overig"])
    llm = Bericht(id="a2", titel="Iets helemaal anders", url="https://x.be/2", bron="b", bron_naam="b",
                  datum="2026-10-29", regio="BE", land="BE", categorieen=["horeca"], methode="llm")
    archief.voeg_toe([oud, llm])
    archief.bewaar()
    archief = Archief(tmp_path)
    nieuw1 = Bericht(id="a1", titel="Vegan bakkerij opent", url="https://x.be/1", bron="b", bron_naam="b",
                     datum="2026-10-29", regio="INT", land="FR", categorieen=["horeca"], gebeurtenis="opening")
    nieuw2 = Bericht(id="a2", titel="Iets helemaal anders", url="https://x.be/2", bron="b", bron_naam="b",
                     datum="2026-10-29", regio="INT", land="FR", categorieen=["overig"])
    assert archief.voeg_toe([nieuw1, nieuw2]) == []
    assert archief.bewaar() == ["2026-10"]
    archief = Archief(tmp_path)
    archief.laad("2026-10")
    a1, a2 = archief.bericht("a1"), archief.bericht("a2")
    assert (a1.regio, a1.land, a1.categorieen, a1.gebeurtenis) == ("INT", "FR", ["horeca"], "opening")
    assert (a2.regio, a2.categorieen) == ("BE", ["horeca"])  # door het taalmodel ingedeeld: ongewijzigd


class NepTaalmodel:
    naam, model, token = "Nep", "nep-model", "x"

    def vraag(self, systeem, gebruiker):
        uit = []
        for item in json.loads(gebruiker):
            relevant = "Voetbal" not in item["titel"]
            uit.append({"id": item["id"], "relevant": relevant, "kernzin": f"Kern: {item['titel'][:40]}",
                        "categorieen": ["horeca"], "land": "", "plaats": "", "zoekterm_gezien": "zoekterm" in item})
        return json.dumps({"berichten": uit})


def test_kandidaten_met_taalmodel(wortel, monkeypatch):
    from vegannieuws import verzamelen
    (wortel / "bronnen.yml").write_text("bronnen: []\n", encoding="utf-8")
    (wortel / "zoekopdrachten.yml").write_text("zoekopdrachten:\n  - zoekterm: vegan\n    land: BE\n    taal: nl\n",
                                              encoding="utf-8")
    sessie = FakeSessie({"news.google.com": (200, fixture("google_nieuws.xml"), {})})
    monkeypatch.setattr(Ophaler, "_maak_sessie", staticmethod(lambda repo: sessie))
    monkeypatch.setattr(ophalen.time, "sleep", lambda s: None)
    monkeypatch.setattr(verzamelen, "maak_taalmodellen", lambda *a, **k: [NepTaalmodel()])
    inst = Instellingen(reserve_vertaling=False, max_leeftijd_dagen=36500, llm_max_leeftijd_dagen=36500, llm_pauze_s=0)
    paden = Paden(wortel)

    rapport = verzamel(paden, inst, log=lambda *_: None)
    assert rapport.kandidaten == 1 and rapport.kandidaten_afgewezen == 1   # "Voetbal: Club Brugge wint"
    maand = json.loads((wortel / "site/data/berichten/2026-10.json").read_text(encoding="utf-8"))
    assert not any("Voetbal" in b["titel"] for b in maand["berichten"])
    assert all(b.get("methode") == "llm" and b["kernzin"].startswith("Kern:") for b in maand["berichten"])
    staat = Staat.laad(paden.staat)
    assert len(staat.geweigerd) == 1

    tweede = verzamel(paden, inst, log=lambda *_: None)
    assert tweede.kandidaten == 0 and tweede.nieuw == 0  # afgewezen kandidaat komt niet terug


def test_kandidaat_bevestigd_door_gewoon_bericht(tmp_path):
    from vegannieuws.archief import Archief
    from vegannieuws.model import Bericht
    archief = Archief(tmp_path)
    kandidaat = Bericht(id="k1", titel="Komkommertijd opent tweede zaak in Gent", url="https://news.google.com/a",
                        bron="g", bron_naam="Google", datum="2026-10-29", kandidaat=True, relevant=False,
                        zoekterm="vegan", categorieen=["overig"])
    archief.voeg_toe([kandidaat])
    bevestiging = Bericht(id="k2", titel="Komkommertijd opent tweede zaak in Gent", url="https://hln.be/b",
                          bron="h", bron_naam="HLN", datum="2026-10-29", relevantie=2, categorieen=["horeca"],
                          gebeurtenis="opening")
    assert archief.voeg_toe([bevestiging]) == []
    b = archief.bericht("k1")
    assert (b.kandidaat, b.relevant, b.categorieen, b.gebeurtenis) == (False, True, ["horeca"], "opening")


INSTAGRAM_FEED = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Google Nieuws</title>
<item><title>Nieuw in Gent: onze tweede zaak opent op 5 november aan de Vlasmarkt - Instagram</title>
<link>https://news.google.com/rss/articles/gent</link><pubDate>Thu, 29 Oct 2026 07:00:00 GMT</pubDate>
<description>&lt;a href="x"&gt;Nieuw in Gent: onze tweede zaak opent op 5 november aan de Vlasmarkt&lt;/a&gt;&amp;nbsp;&lt;font&gt;Instagram&lt;/font&gt;</description>
<source url="https://www.instagram.com">Instagram</source></item>
<item><title>Notre nouveau restaurant ouvre ses portes rue Oberkampf - Instagram</title>
<link>https://news.google.com/rss/articles/parijs</link><pubDate>Thu, 29 Oct 2026 08:00:00 GMT</pubDate>
<description>&lt;a href="x"&gt;Notre nouveau restaurant ouvre ses portes rue Oberkampf&lt;/a&gt;</description>
<source url="https://www.instagram.com">Instagram</source></item>
<item><title>Mijn lunch vandaag #vegan - Instagram</title>
<link>https://news.google.com/rss/articles/lunch</link><pubDate>Thu, 29 Oct 2026 09:00:00 GMT</pubDate>
<description>&lt;a href="x"&gt;Mijn lunch vandaag #vegan&lt;/a&gt;</description>
<source url="https://www.instagram.com">Instagram</source></item>
</channel></rss>"""


class NepSociaalModel:
    naam, model, token = "Nep", "nep-model", "x"

    def __init__(self):
        self.gezien = []

    def vraag(self, systeem, gebruiker):
        invoer = json.loads(gebruiker)
        if isinstance(invoer, dict):          # verzoek van de bundeling
            return json.dumps({"verhalen": []})
        uit = []
        for item in invoer:
            self.gezien.append(item)
            nieuws = "lunch" not in item["titel"]
            land = "FR" if "Oberkampf" in item["titel"] else "BE"
            uit.append({"id": item["id"], "relevant": nieuws, "kernzin": f"Kern: {item['titel'][:30]}",
                        "categorieen": ["horeca"], "gebeurtenis": "opening", "land": land, "plaats": ""})
        return json.dumps({"berichten": uit})


def test_instagram_posts_via_google_nieuws(wortel, monkeypatch):
    from vegannieuws import verzamelen
    (wortel / "bronnen.yml").write_text("bronnen: []\n", encoding="utf-8")
    (wortel / "zoekopdrachten.yml").write_text(
        "zoekopdrachten:\n  - zoekterm: site:instagram.com vegan\n    land: BE\n    taal: nl\n    enkel_land: BE\n",
        encoding="utf-8")
    sessie = FakeSessie({"news.google.com": (200, INSTAGRAM_FEED, {})})
    model = NepSociaalModel()
    monkeypatch.setattr(Ophaler, "_maak_sessie", staticmethod(lambda repo: sessie))
    monkeypatch.setattr(ophalen.time, "sleep", lambda s: None)
    monkeypatch.setattr(verzamelen, "maak_taalmodellen", lambda *a, **k: [model])
    inst = Instellingen(reserve_vertaling=False, max_leeftijd_dagen=36500, llm_max_leeftijd_dagen=36500, llm_pauze_s=0)
    paden = Paden(wortel)

    rapport = verzamel(paden, inst, log=lambda *_: None)
    # Elke post gaat als kandidaat naar het taalmodel, ook zonder vegan-woord in de titel.
    assert rapport.kandidaten == 3 and all(item.get("sociaal") == "Instagram" for item in model.gezien)
    assert all("zoekterm" not in item for item in model.gezien)
    maand = json.loads((wortel / "site/data/berichten/2026-10.json").read_text(encoding="utf-8"))
    over = maand["berichten"]
    # Enkel de Gentse opening blijft: de lunchfoto is geen nieuws, Parijs ligt niet in België.
    assert [b["sociaal"] for b in over] == ["Instagram"] and "Vlasmarkt" in over[0]["titel"]
    assert over[0]["land"] == "BE" and "kandidaat" not in over[0]
    assert rapport.kandidaten_afgewezen == 2 and len(Staat.laad(paden.staat).geweigerd) == 2


def test_zonder_taalmodel_geen_sociale_media(wortel, monkeypatch):
    from vegannieuws import verzamelen
    (wortel / "bronnen.yml").write_text("bronnen: []\n", encoding="utf-8")
    (wortel / "zoekopdrachten.yml").write_text(
        "zoekopdrachten:\n  - zoekterm: site:instagram.com vegan\n    land: BE\n    taal: nl\n", encoding="utf-8")
    sessie = FakeSessie({"news.google.com": (200, INSTAGRAM_FEED, {})})
    monkeypatch.setattr(Ophaler, "_maak_sessie", staticmethod(lambda repo: sessie))
    monkeypatch.setattr(ophalen.time, "sleep", lambda s: None)
    monkeypatch.setattr(verzamelen, "maak_taalmodellen", lambda *a, **k: [])
    inst = Instellingen(reserve_vertaling=False, max_leeftijd_dagen=36500, llm_pauze_s=0)
    rapport = verzamel(Paden(wortel), inst, log=lambda *_: None)
    assert rapport.nieuw == 0 and rapport.kandidaten == 0


def test_sociale_post_uit_gewone_zoekopdracht_enkel_belgie(wortel, monkeypatch):
    from vegannieuws import verzamelen
    (wortel / "bronnen.yml").write_text("bronnen: []\n", encoding="utf-8")
    (wortel / "zoekopdrachten.yml").write_text("zoekopdrachten:\n  - zoekterm: vegan\n    land: BE\n    taal: nl\n",
                                              encoding="utf-8")
    sessie = FakeSessie({"news.google.com": (200, INSTAGRAM_FEED, {})})
    monkeypatch.setattr(Ophaler, "_maak_sessie", staticmethod(lambda repo: sessie))
    monkeypatch.setattr(ophalen.time, "sleep", lambda s: None)
    monkeypatch.setattr(verzamelen, "maak_taalmodellen", lambda *a, **k: [NepSociaalModel()])
    inst = Instellingen(reserve_vertaling=False, max_leeftijd_dagen=36500, llm_max_leeftijd_dagen=36500, llm_pauze_s=0)
    verzamel(Paden(wortel), inst, log=lambda *_: None)
    over = json.loads((wortel / "site/data/berichten/2026-10.json").read_text(encoding="utf-8"))["berichten"]
    assert [b["land"] for b in over] == ["BE"]          # de Parijse post valt weg (sociaal_enkel_land: BE)


def test_sociale_post_met_kopie_wordt_ook_geweigerd(tmp_path):
    from datetime import date
    from vegannieuws.archief import Archief
    from vegannieuws.model import Bericht
    from vegannieuws.verzamelen import _ruim_kandidaten_op
    archief = Archief(tmp_path)
    post = Bericht(id="p1", titel="Recept voor vegan scones", url="https://news.google.com/a", bron="g",
                   bron_naam="Facebook via Google Nieuws", datum="2026-10-27", sociaal="Facebook", methode="llm",
                   brontype="zoekopdracht", land="",
                   extra=[{"naam": "Facebook", "url": "https://news.google.com/b", "id": "p2"}])
    bevestigd = Bericht(id="p3", titel="Nieuwe vegan zaak opent", url="https://news.google.com/c", bron="g",
                        bron_naam="Instagram via Google Nieuws", datum="2026-10-27", sociaal="Instagram",
                        methode="llm", brontype="zoekopdracht", land="",
                        extra=[{"naam": "Het Nieuwsblad", "url": "https://nieuwsblad.be/x", "id": "p4"}])
    gevolgd = Bericht(id="p5", titel="Wij openen een tweede zaak", url="https://www.instagram.com/p/abc/", bron="kt",
                      bron_naam="Komkommertijd", datum="2026-10-27", sociaal="Instagram", methode="llm",
                      brontype="horeca", land="")
    archief.voeg_toe([post, bevestigd, gevolgd])
    staat = Staat()
    assert _ruim_kandidaten_op(archief, staat, date(2026, 10, 30), 21, {}, "BE") == 1
    assert archief.bericht("p1") is None and archief.bericht("p3") is not None   # door een medium bevestigd
    assert archief.bericht("p5") is not None          # zelf gevolgd account: geen landregel
    assert set(staat.geweigerd) == {"p1", "p2"}


def test_gevolgd_instagram_account_in_verzamelrun(wortel, monkeypatch):
    from vegannieuws import verzamelen
    (wortel / "bronnen.yml").write_text(
        "bronnen:\n  - naam: Komkommertijd\n    url: https://www.instagram.com/komkommertijd/\n    type: horeca\n"
        "    land: BE\n    taal: nl\n    alleen_vegan: nee\n", encoding="utf-8")
    (wortel / "zoekopdrachten.yml").write_text("zoekopdrachten: []\n", encoding="utf-8")
    posts = json.dumps({"business_discovery": {"name": "Komkommertijd", "media": {"data": [
        {"caption": "Ons pop-up in Parijs opent aan de rue Oberkampf", "permalink": "https://www.instagram.com/p/A1/",
         "timestamp": "2026-10-29T09:00:00+0000"},
        {"caption": "Mijn lunch vandaag #vegan", "permalink": "https://www.instagram.com/p/A2/",
         "timestamp": "2026-10-29T12:00:00+0000"}]}}}).encode()
    sessie = FakeSessie({"me/accounts": (200, b'{"data": [{"instagram_business_account": {"id": "1784"}}]}', {}),
                         "debug_token": (200, b'{"data": {"expires_at": 0}}', {}),
                         "graph.facebook.com/v26.0/1784?": (200, posts, {})})
    monkeypatch.setenv("INSTAGRAM_TOKEN", "EAAGgeheim1234567890")
    monkeypatch.delenv("INSTAGRAM_USER_ID", raising=False)
    monkeypatch.setattr(Ophaler, "_maak_sessie", staticmethod(lambda repo: sessie))
    monkeypatch.setattr(verzamelen, "maak_taalmodellen", lambda *a, **k: [NepSociaalModel()])
    inst = Instellingen(reserve_vertaling=False, max_leeftijd_dagen=36500, llm_max_leeftijd_dagen=36500, llm_pauze_s=0)
    rapport = verzamel(Paden(wortel), inst, log=lambda *_: None)
    assert rapport.bronnen_fout == 0 and rapport.kandidaten == 2
    over = json.loads((wortel / "site/data/berichten/2026-10.json").read_text(encoding="utf-8"))["berichten"]
    # De lunchpost is geen nieuws; de pop-up in Parijs blijft: een zelf gevolgd account valt niet onder de landregel.
    assert [(b["url"], b["sociaal"], b["relatie"], b["land"]) for b in over] == \
        [("https://www.instagram.com/p/A1/", "Instagram", "primair", "FR")]
    bronnen = json.loads((wortel / "site/data/bronnen.json").read_text(encoding="utf-8"))["bronnen"]
    assert bronnen[0]["soort"] == "instagram" and "EAAG" not in json.dumps(bronnen)
