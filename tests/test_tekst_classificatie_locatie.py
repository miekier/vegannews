from pathlib import Path

import pytest

from vegannieuws.classificatie import deel_in, laad_lexicon, maak_patroon
from vegannieuws.locatie import Geo, land_van_url
from vegannieuws.tekst import detecteer_taal, kort_in, normaliseer, slug, zuiver_html

WORTEL = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def lexicon():
    return laad_lexicon(WORTEL / "categorieen.yml")


@pytest.fixture(scope="module")
def geo():
    return Geo()


def test_zuiver_html():
    assert zuiver_html("<p>Een&nbsp;<b>vegan</b> zaak&amp;co</p><script>x()</script>") == "Een vegan zaak&co"
    assert zuiver_html(None) == ""


def test_kort_in_bij_zin():
    tekst = "Eerste zin is hier. Tweede zin is wat langer en loopt door tot voorbij de grens."
    assert kort_in(tekst, 35) == "Eerste zin is hier."
    assert kort_in("kort", 40) == "kort"
    assert kort_in("woord " * 30, 50).endswith("…")


def test_normaliseer_en_slug():
    assert normaliseer("Végétal-Plant  Based") == "vegetal plant based"
    assert slug("Gault&Millau België") == "gault-millau-belgie"


@pytest.mark.parametrize("tekst,taal", [
    ("Het nieuwe restaurant in de stad is een succes en wordt druk bezocht", "nl"),
    ("Le nouveau restaurant de la ville est un succès pour les végans", "fr"),
    ("The new restaurant in the city is a success for the vegan community", "en"),
    ("Das neue Restaurant in der Stadt ist ein Erfolg und wird gut besucht", "de"),
])
def test_detecteer_taal(tekst, taal):
    assert detecteer_taal(tekst) == taal


def test_detecteer_taal_kort_gebruikt_standaard():
    assert detecteer_taal("Vegan pizza", "fr") == "fr"


def test_patroon_meerdere_woorden_en_jokers():
    p = maak_patroon(["plant based", "*vegan*", "restaurant*", "law"])
    tekst = normaliseer("Plant-based veganisten openen restaurants; lawsuit")
    assert sorted(p.findall(tekst)) == ["plant based", "restaurants", "veganisten"]


@pytest.mark.parametrize("titel,tekst,categorie,gebeurtenis", [
    ("Nieuw vegan restaurant opent in Gent", "", "horeca", "opening"),
    ("Vegan bakkerij in Geel sluit de deuren", "", "horeca", "sluiting"),
    ("Supermarkt Colruyt breidt vegan assortiment uit", "Vleesvervangers krijgen meer plaats.", "retail", ""),
    ("EU Parliament votes to ban veggie burger names", "", "wetgeving", ""),
    ("Dutch startup raises €5M for precision fermentation", "", "innovatie", ""),
    ("New study links vegan diets to lower cholesterol", "Researchers found ...", "wetenschap", ""),
    ("GAIA lanceert campagne tegen legbatterijen", "", "dierenrechten", ""),
])
def test_indeling(lexicon, titel, tekst, categorie, gebeurtenis):
    indeling = deel_in(lexicon, titel, tekst)
    assert categorie in indeling.categorieen
    assert indeling.gebeurtenis == gebeurtenis
    assert len(indeling.categorieen) <= 3


def test_relevantie(lexicon):
    assert deel_in(lexicon, "Plant-based milk sales boom", "").relevantie > 0
    assert deel_in(lexicon, "Club Brugge wint opnieuw", "").relevantie == 0
    assert deel_in(lexicon, "Weerbericht voor morgen", "").categorieen == ["overig"]


@pytest.mark.parametrize("titel,tekst,bronland,regio,land,plaats", [
    ("Nieuw vegan restaurant opent in Gent", "", "BE", "BE", "BE", "Gent"),
    ("Un nouveau restaurant vegan ouvre ses portes à Ixelles", "", "", "BE", "BE", "Ixelles"),
    ("Vegan restaurant in Amsterdam wint prijs", "", "BE", "INT", "NL", "Amsterdam"),
    ("EU Parliament votes to ban veggie burger names", "", "BE", "INT", "EU", ""),
    ("Italiaanse vegan pizzeria opent", "", "BE", "BE", "BE", ""),
    ("Belgian startup raises funding", "", "INT", "BE", "BE", ""),
    ("Vegan bakkerij in Geel sluit", "", "BE", "BE", "BE", "Geel"),
    ("Geel licht voor nieuwe vleesvervangers", "", "BE", "BE", "BE", ""),
    ("Boom in plant-based milk sales", "", "INT", "INT", "", ""),
    ("Nieuwe vegan zaak in Lille", "", "BE", "INT", "FR", "Lille"),
])
def test_regio(geo, titel, tekst, bronland, regio, land, plaats):
    r = geo.bepaal(titel, tekst, bronland)
    assert (r.regio, r.land, r.plaats) == (regio, land, plaats)


def test_regio_via_uitgever(geo):
    r = geo.bepaal("Vegan slagerij opent", "", "BE", "https://www.ad.nl")
    assert (r.regio, r.land) == ("INT", "NL")
    r = geo.bepaal("Belgische recalls in oktober: vegan burger teruggeroepen", "", "NL", "https://www.vmt.nl")
    assert r.regio == "BE"
    assert land_van_url("https://www.bbc.co.uk/news") == "GB"
    assert land_van_url("https://agfundernews.com") == ""


def test_gewest(geo):
    assert geo.gewest_van("Luik") == "Wallonië"
    assert geo.gewest_van("Elsene") == "Brussel"
    assert geo.gewest_van("Nergensdorp") == ""
