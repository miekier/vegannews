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
