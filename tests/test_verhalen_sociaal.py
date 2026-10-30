import json
from datetime import date

from vegannieuws.bronnen import sociaal_platform
from vegannieuws.model import Bericht
from vegannieuws.ontdubbelen import bericht_id
from vegannieuws.ophalen import lees_feed
from vegannieuws.bronnen import Bron
from vegannieuws.verhalen import bundel, kandidaatgroepen
from vegannieuws.verrijking import StopVerrijking


def maak(nr, kernzin, datum="2026-10-29", taal="en", bron="medium", **extra):
    url = f"https://{bron}.example/{nr}"
    return Bericht(id=bericht_id(url), titel=kernzin, url=url, bron=bron, bron_naam=bron, datum=datum,
                   opgehaald=f"{datum}T10:00:00Z", kernzin=kernzin, taal=taal, methode="llm", **extra)


def opvulling():
    # Gewone berichten zodat algemene woorden (vegan, restaurant ...) een laag gewicht krijgen.
    onderwerpen = ["opent een vegan restaurant in Lyon", "lanceert een plantaardige burger",
                   "publiceert een studie over vegan voeding", "opent een vegan bakkerij in Madrid",
                   "start een campagne voor dierenwelzijn", "verkoopt vegan kaas in Berlijn"]
    return [maak(100 + i, f"Bedrijf{i} {onderwerpen[i % len(onderwerpen)]}.", bron=f"vul{i}") for i in range(40)]


# Kernzinnen zoals het taalmodel ze schreef (archief, 29-30 oktober 2026), uit drie talen.
TOBLERONE = [
    maak(1, "Toblerone spant een proces aan tegen een Brits veganistisch chocolademerk vanwege een vergelijkbare vorm.",
         taal="sr", bron="glas"),
    maak(2, "De fabrikant van Toblerone spant een proces aan tegen een veganistisch chocolademerk vanwege de reepvorm.",
         taal="pt", bron="investnews"),
    maak(3, "Toblerone sleept een klein Brits veganistisch chocolademerk voor de rechter.", taal="nl", bron="nu"),
]


def test_kandidaatgroepen_over_talen_heen():
    groepen = kandidaatgroepen(TOBLERONE + opvulling())
    toblerone = [g for g in groepen if TOBLERONE[0] in g]
    assert len(toblerone) == 1 and {b.id for b in toblerone[0]} >= {b.id for b in TOBLERONE}
    # Verschillende opvulberichten vormen geen groep met Toblerone.
    assert all(b.bron in ("glas", "investnews", "nu") for b in toblerone[0])


def test_kandidaatgroepen_respecteren_datumafstand():
    oud = maak(9, "Toblerone sleept een klein Brits veganistisch chocolademerk voor de rechter.", datum="2026-10-20")
    groepen = kandidaatgroepen([oud, TOBLERONE[2]] + opvulling())
    assert not any(oud in g for g in groepen)


class NepModel:
    def __init__(self, antwoord=None, fout=None):
        self.antwoord, self.fout, self.vragen = antwoord, fout, []

    def vraag(self, systeem, gebruiker, schema=None):
        self.vragen.append(json.loads(gebruiker))
        if self.fout:
            raise self.fout
        return self.antwoord(self.vragen[-1]) if callable(self.antwoord) else self.antwoord


def alle_ids(invoer):
    return [b["id"] for groep in invoer["groepen"] for b in groep]


def test_bundel_kent_verhaal_en_nederlandse_kop_toe():
    berichten = [maak(i + 1, b.kernzin, taal=b.taal, bron=b.bron) for i, b in enumerate(TOBLERONE)] + opvulling()
    model = NepModel(lambda invoer: json.dumps({"verhalen": [
        {"ids": alle_ids(invoer)[:3], "kop": "Mondelez daagt Brits vegan chocolademerk voor de rechter."}]}))
    gecontroleerd = {}
    stat = bundel(berichten, model, date(2026, 10, 30), 4, 4, gecontroleerd)
    leden = [b for b in berichten if b.verhaal]
    assert stat.nieuwe_verhalen == 1 and len(leden) == 3
    assert {b.verhaal_kop for b in leden} == {"Mondelez daagt Brits vegan chocolademerk voor de rechter"}
    assert len({b.verhaal for b in leden}) == 1
    assert all(b.id in gecontroleerd for b in berichten)
    # Een tweede run stuurt niets opnieuw.
    stat2 = bundel(berichten, model, date(2026, 10, 30), 4, 4, gecontroleerd)
    assert stat2.verzoeken == 0 and len(model.vragen) == 1


def test_nieuw_bericht_sluit_aan_bij_bestaand_verhaal():
    berichten = [maak(i + 1, b.kernzin, taal=b.taal, bron=b.bron) for i, b in enumerate(TOBLERONE[:2])] + opvulling()
    gecontroleerd = {}
    eerste = NepModel(lambda invoer: json.dumps({"verhalen": [{"ids": alle_ids(invoer)[:2], "kop": "Kop een"}]}))
    bundel(berichten, eerste, date(2026, 10, 30), 4, 4, gecontroleerd)
    verhaal = berichten[0].verhaal
    assert verhaal and berichten[1].verhaal == verhaal
    nieuw = maak(3, TOBLERONE[2].kernzin, taal="nl", bron="nu")
    berichten.append(nieuw)
    tweede = NepModel(lambda invoer: json.dumps({"verhalen": [{"ids": alle_ids(invoer)[:3], "kop": "Kop twee"}]}))
    bundel(berichten, tweede, date(2026, 10, 30), 4, 4, gecontroleerd)
    assert nieuw.verhaal == verhaal
    assert {b.verhaal_kop for b in berichten if b.verhaal} == {"Kop twee"}
    assert any("kop" in b for groep in tweede.vragen[0]["groepen"] for b in groep)   # bestaande kop meegestuurd


def test_bundel_negeert_ongeldige_antwoorden_en_stopt_bij_limiet():
    berichten = [maak(i + 1, b.kernzin, taal=b.taal, bron=b.bron) for i, b in enumerate(TOBLERONE)] + opvulling()
    model = NepModel(json.dumps({"verhalen": [{"ids": ["1"], "kop": "Te klein"}, {"ids": ["1", "999"], "kop": "x"},
                                              {"ids": ["1", "2"], "kop": ""}]}))
    stat = bundel(berichten, model, date(2026, 10, 30), 4, 4, {})
    assert stat.nieuwe_verhalen == 0 and not any(b.verhaal for b in berichten)
    gestopt = bundel(berichten, NepModel(fout=StopVerrijking("limiet")), date(2026, 10, 30), 4, 4, {})
    assert gestopt.verzoeken == 0 and "limiet" in gestopt.melding


def test_sociaal_platform():
    assert sociaal_platform("https://www.instagram.com") == "Instagram"
    assert sociaal_platform("https://m.facebook.com/x") == "Facebook"
    assert sociaal_platform("https://www.hln.be") == ""


def test_google_nieuws_instagram_post_behoudt_bijschrift():
    feed = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>
<item><title>Vegan comfort food in Antwerp? @bardhenri is your place - Instagram</title>
<link>https://news.google.com/rss/articles/abc</link><pubDate>Fri, 16 Oct 2026 07:00:00 GMT</pubDate>
<description>&lt;a href="https://news.google.com/rss/articles/abc"&gt;Vegan comfort food in Antwerp? @bardhenri is your place to be. Nieuw: elke zondag brunch vanaf 1 november&lt;/a&gt;&amp;nbsp;&amp;nbsp;&lt;font color="#6f6f6f"&gt;Instagram&lt;/font&gt;</description>
<source url="https://www.instagram.com">Instagram</source></item>
<item><title>Gewoon artikel - De Standaard</title><link>https://news.google.com/rss/articles/def</link>
<description>&lt;a href="x"&gt;Gewoon artikel&lt;/a&gt;</description><source url="https://www.standaard.be">De Standaard</source></item>
</channel></rss>"""
    bron = Bron(id="g", naam="Instagram via Google Nieuws", soort="google", type="zoekopdracht", zoekterm="site:instagram.com vegan")
    post, artikel = lees_feed(feed, bron)
    assert post.titel == "Vegan comfort food in Antwerp? @bardhenri is your place" and post.uitgever == "Instagram"
    assert "elke zondag brunch" in post.samenvatting and not post.samenvatting.endswith("Instagram")
    assert artikel.samenvatting == ""


def test_koppen_vallen_terug_op_tweede_model(tmp_path, monkeypatch):
    from vegannieuws import verzamelen
    from vegannieuws.archief import Archief
    from vegannieuws.config import Instellingen
    from vegannieuws.staat import Staat
    archief = Archief(tmp_path)
    berichten = [maak(i + 1, b.kernzin, taal=b.taal, bron=b.bron, datum="2026-10-29") for i, b in enumerate(TOBLERONE)]
    archief.voeg_toe(berichten + opvulling())
    sterk = NepModel(fout=StopVerrijking("limiet van Google Gemini bereikt"))
    sterk.model = "gemini-flash-latest"
    gewoon = NepModel(lambda invoer: json.dumps({"verhalen": [{"ids": alle_ids(invoer)[:3], "kop": "Kop"}]}))
    gewoon.model = "gemini-flash-lite-latest"
    aanroepen = iter([[sterk], [gewoon]])
    monkeypatch.setattr(verzamelen, "maak_taalmodellen", lambda *a, **k: next(aanroepen))
    staat = Staat()
    stat = verzamelen._bundel_verhalen(archief, Instellingen(), staat, date(2026, 10, 30), log=lambda *_: None)
    assert len(sterk.vragen) == 1 and len(gewoon.vragen) == 1
    assert stat.nieuwe_verhalen == 1 and stat.model == "gemini-flash-lite-latest"
    assert staat.budget["llm"]["gebruikt"] == 1
