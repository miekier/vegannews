import json

import pytest

from vegannieuws.archief import Archief
from vegannieuws.classificatie import laad_lexicon
from vegannieuws.locatie import Geo
from vegannieuws.model import Bericht
from vegannieuws.ontdubbelen import bericht_id, canonieke_url
from vegannieuws.verrijking import StopVerrijking, achterstand, lees_antwoord, pas_toe, verrijk

from conftest import WORTEL


def maak(url, titel, datum="2026-10-29", relatie="secundair", bron="b", **extra):
    return Bericht(id=bericht_id(url), titel=titel, url=url, bron=bron, bron_naam=bron, datum=datum,
                   opgehaald=f"{datum}T10:00:00Z", relatie=relatie, **extra)


def test_canonieke_url():
    assert canonieke_url("http://www.Voorbeeld.be/artikel/?utm_source=rss&id=5#top") == \
        "https://voorbeeld.be/artikel?id=5"
    assert bericht_id("https://voorbeeld.be/a?utm_medium=x") == bericht_id("https://www.voorbeeld.be/a/")


def test_ontdubbelen_en_primaire_bron(tmp_path):
    archief = Archief(tmp_path)
    a = maak("https://hln.be/1", "Nieuw vegan restaurant opent zijn deuren in Gent", uitgever="HLN")
    b = maak("https://nieuwsblad.be/2", "Nieuw vegan restaurant opent deuren in Gent", uitgever="Het Nieuwsblad")
    c = maak("https://eva.be/3", "Nieuw vegan restaurant opent zijn deuren in Gent!", relatie="primair", bron="eva")
    d = maak("https://hln.be/4", "Iets totaal anders over kweekvlees in Nederland")
    toegevoegd = archief.voeg_toe([a, b, d])
    assert len(toegevoegd) == 2
    hoofd = archief.bericht(a.id)
    assert [e["naam"] for e in hoofd.extra] == ["Het Nieuwsblad"]
    assert archief.voeg_toe([c]) == []
    assert hoofd.url == "https://eva.be/3" and hoofd.relatie == "primair"
    assert {e["naam"] for e in hoofd.extra} == {"HLN", "Het Nieuwsblad"}
    assert archief.voeg_toe([maak("https://hln.be/1", "Nieuw vegan restaurant")]) == []  # bekende URL


def test_dubbel_buiten_venster_is_nieuw(tmp_path):
    archief = Archief(tmp_path)
    archief.voeg_toe([maak("https://a.be/1", "Vegan festival in Antwerpen trekt duizenden bezoekers", "2026-10-01")])
    nieuw = archief.voeg_toe([maak("https://a.be/2", "Vegan festival in Antwerpen trekt duizenden bezoekers", "2026-10-20")])
    assert len(nieuw) == 1


def test_bewaren_en_laden(tmp_path):
    archief = Archief(tmp_path)
    archief.voeg_toe([maak("https://a.be/1", "Bericht een over vegan kaas", "2026-09-30"),
                      maak("https://a.be/2", "Bericht twee over plantaardige melk", "2026-10-02", regio="BE")])
    assert archief.bewaar() == ["2026-09", "2026-10"]
    inhoud = json.loads((tmp_path / "berichten" / "2026-10.json").read_text(encoding="utf-8"))
    assert inhoud["aantal"] == 1 and inhoud["berichten"][0]["titel"] == "Bericht twee over plantaardige melk"
    assert "pogingen" not in inhoud["berichten"][0]  # standaardwaarden worden niet bewaard
    opnieuw = Archief(tmp_path)
    per_maand, per_dag = opnieuw.tellingen(["2026-09", "2026-10"])
    assert per_maand == {"2026-09": 1, "2026-10": 1}
    assert per_dag["2026-10-02"] == [1, 1, 1]


@pytest.fixture(scope="module")
def lexicon():
    return laad_lexicon(WORTEL / "categorieen.yml")


def test_lees_antwoord_met_codeblok():
    tekst = '```json\n{"berichten": [{"id": "a", "relevant": true}, "rommel"]}\n```'
    assert lees_antwoord(tekst) == [{"id": "a", "relevant": True}]
    with pytest.raises(ValueError):
        lees_antwoord("geen json")


def test_pas_toe_vertaalt_franse_titel(lexicon):
    b = maak("https://lesoir.be/1", "Un restaurant vegan ouvre à Liège", taal="fr", samenvatting="Texte en français.")
    pas_toe(b, {"relevant": True, "kernzin": "Vegan restaurant opent in Luik.", "titel": "Vegan restaurant opent in Luik",
                "samenvatting": "Tekst in het Nederlands.", "categorieen": ["horeca", "bestaat-niet"],
                "gebeurtenis": "opening", "land": "be", "plaats": "Luik"}, lexicon, Geo(), ["nl", "en"])
    assert b.titel == "Vegan restaurant opent in Luik" and b.titel_orig == "Un restaurant vegan ouvre à Liège"
    assert b.samenvatting_orig == "Texte en français." and b.vertaald == "llm"
    assert b.categorieen == ["horeca"] and b.gebeurtenis == "opening"
    assert (b.regio, b.land, b.plaats, b.gewest, b.methode) == ("BE", "BE", "Luik", "Wallonië", "llm")


def test_pas_toe_laat_engelse_titel(lexicon):
    b = maak("https://x.com/1", "Oatly launches new range", taal="en")
    pas_toe(b, {"relevant": False, "kernzin": "Oatly lanceert een nieuw gamma.", "titel": "Oatly lanceert nieuw gamma",
                "categorieen": [], "land": "", "plaats": ""}, lexicon, Geo(), ["nl", "en"])
    assert b.titel == "Oatly launches new range" and b.titel_orig == "" and b.vertaald == ""
    assert b.kernzin == "Oatly lanceert een nieuw gamma." and b.relevant is False


class FakeClient:
    model = "test/model"

    def __init__(self, antwoorden):
        self.antwoorden = list(antwoorden)
        self.vragen = 0

    def vraag(self, systeem, gebruiker):
        self.vragen += 1
        antwoord = self.antwoorden.pop(0)
        if isinstance(antwoord, Exception):
            raise antwoord
        if antwoord == "echo":
            ids = [x["id"] for x in json.loads(gebruiker)]
            return json.dumps({"berichten": [{"id": i, "relevant": True, "kernzin": "Zin.", "categorieen": ["media"]}
                                             for i in ids]})
        return antwoord


def test_verrijk_batches_fouten_en_stop(lexicon):
    berichten = [maak(f"https://a.be/{i}", f"Titel {i}", taal="nl") for i in range(5)]
    client = FakeClient(["echo", ValueError("kapot"), StopVerrijking("daglimiet")])
    stat = verrijk(berichten, client, lexicon, Geo(), "nl", ["nl", "en"], batch=2, max_verzoeken=10, max_pogingen=3,
                   log=lambda *_: None)
    assert stat.verrijkt == 2 and stat.mislukt == 2 and stat.verzoeken == 2
    assert "daglimiet" in stat.melding
    assert [b.methode for b in berichten] == ["llm", "llm", "regels", "regels", "regels"]
    assert [b.pogingen for b in berichten] == [0, 0, 1, 1, 0]


def test_achterstand_nieuwste_eerst():
    lijst = [maak("https://a.be/1", "a", "2026-10-01"), maak("https://a.be/2", "b", "2026-10-20"),
             maak("https://a.be/3", "c", "2026-10-25", methode="llm"), maak("https://a.be/4", "d", "2026-10-22", pogingen=3)]
    assert [b.titel for b in achterstand(lijst, "2026-10-10", 3)] == ["b"]


class PostSessie:
    """Nep-sessie voor het taalmodel: lijst van (status, inhoud, headers) per POST."""

    def __init__(self, antwoorden):
        self.antwoorden = list(antwoorden)
        self.verzoeken = []

    def post(self, url, json=None, timeout=None, allow_redirects=True, headers=None):
        from conftest import maak_antwoord
        self.verzoeken.append((url, json["model"]))
        status, inhoud, kop = self.antwoorden.pop(0)
        return maak_antwoord(url, status, inhoud.encode(), kop)


def test_taalmodel_volgt_omleiding_en_valt_terug_op_tweede_eindpunt(monkeypatch):
    from vegannieuws import verrijking
    from vegannieuws.verrijking import GitHubModels
    monkeypatch.setattr(verrijking.time, "sleep", lambda s: None)
    goed = '{"choices": [{"message": {"content": "{\\"ok\\": true}"}}]}'
    sessie = PostSessie([
        (301, "", {"Location": "https://models.github.ai/v2/chat"}),
        (200, "OK\r\n", {"Content-Type": "text/plain"}),
        (200, goed, {"Content-Type": "application/json"}),
    ])
    client = GitHubModels("token", ["openai/gpt-4o-mini"], 0, sessie=sessie)
    assert client.vraag("s", "g") == '{"ok": true}'
    assert sessie.verzoeken == [
        ("https://models.github.ai/inference/chat/completions", "openai/gpt-4o-mini"),
        ("https://models.github.ai/v2/chat", "openai/gpt-4o-mini"),
        ("https://models.inference.ai.azure.com/chat/completions", "gpt-4o-mini"),
    ]
    assert "omgeleid: 301" in client.diagnoses[0] and "'OK\\r\\n'" in client.diagnoses[0]


def test_taalmodel_geeft_diagnose_als_niets_werkt(monkeypatch):
    from vegannieuws import verrijking
    from vegannieuws.verrijking import GitHubModels
    monkeypatch.setattr(verrijking.time, "sleep", lambda s: None)
    sessie = PostSessie([(200, "OK", {}), (401, "Bad credentials", {})])
    client = GitHubModels("token", ["openai/gpt-4o-mini"], 0, sessie=sessie)
    assert client.test().startswith("werkt niet: geen werkend eindpunt")
    assert "HTTP 401" in client.diagnoses[1]


def test_aanbieders_volgens_sleutels():
    from vegannieuws.config import Instellingen
    from vegannieuws.verrijking import maak_taalmodellen
    inst = Instellingen()
    clients = maak_taalmodellen(inst.llm_aanbieders, inst.modellen_per_aanbieder, 0, {"GROQ_API_KEY": "g"})
    assert [c.naam for c in clients] == ["Groq"]
    clients = maak_taalmodellen(inst.llm_aanbieders, inst.modellen_per_aanbieder, 0,
                                {"GROQ_API_KEY": "g", "GEMINI_API_KEY": "k", "GITHUB_TOKEN": "t"})
    assert [c.naam for c in clients] == ["Google Gemini", "Groq"]
    assert clients[0].eindpunt.startswith("https://generativelanguage.googleapis.com/")
    assert maak_taalmodellen(inst.llm_aanbieders, inst.modellen_per_aanbieder, 0, {"GITHUB_TOKEN": "t"}) == []


def test_gemini_model_terugval_en_limiet(monkeypatch):
    from vegannieuws import verrijking
    from vegannieuws.verrijking import Taalmodel
    monkeypatch.setattr(verrijking.time, "sleep", lambda s: None)
    goed = '{"choices": [{"message": {"content": "{}"}}]}'
    sessie = PostSessie([
        (404, '{"error": {"message": "models/gemini-flash-lite-latest is not found for API version v1beta"}}', {}),
        (200, goed, {}),
    ])
    client = Taalmodel("k", ["gemini-flash-lite-latest", "gemini-2.5-flash-lite"], 0, sessie=sessie,
                       eindpunten=("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",),
                       naam="Google Gemini")
    assert client.vraag("s", "g") == "{}"
    assert [m for _, m in sessie.verzoeken] == ["gemini-flash-lite-latest", "gemini-2.5-flash-lite"]
    vol = Taalmodel("k", ["m"], 0, sessie=PostSessie([(429, "", {"Retry-After": "1"})] * 3), naam="Groq")
    with pytest.raises(StopVerrijking, match="limiet van Groq"):
        vol.vraag("s", "g")
