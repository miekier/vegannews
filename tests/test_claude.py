import json
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from vegannieuws.claude import ClaudeModel
from vegannieuws.verrijking import StopVerrijking, maak_taalmodellen

VERZOEK = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def fout(klasse, status, bericht):
    return klasse(bericht, response=httpx2.Response(status, request=VERZOEK), body=None)


def antwoord(tekst='{"ok": true}', stop="end_turn", invoer=100, uit=20, cache=0):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=tekst)], stop_reason=stop,
        usage=SimpleNamespace(input_tokens=invoer, output_tokens=uit, cache_creation_input_tokens=0,
                              cache_read_input_tokens=cache))


class NepBerichten:
    def __init__(self, uitkomsten):
        self.uitkomsten = list(uitkomsten)
        self.verzoeken = []

    def create(self, **parameters):
        self.verzoeken.append(parameters)
        uitkomst = self.uitkomsten.pop(0)
        if isinstance(uitkomst, Exception):
            raise uitkomst
        return uitkomst


def model(*uitkomsten, modellen=("claude-haiku-5-5",)):
    berichten = NepBerichten(uitkomsten)
    return ClaudeModel("sk-test", list(modellen), client=SimpleNamespace(messages=berichten)), berichten


def test_verzoek_zonder_denken_met_schema_en_cache():
    schema = {"type": "object", "properties": {}, "additionalProperties": False}
    claude, berichten = model(antwoord('{"berichten": []}', cache=900))
    assert claude.vraag("systeem", "gebruiker", schema) == '{"berichten": []}'
    p = berichten.verzoeken[0]
    assert p["model"] == "claude-haiku-5-5" and p["thinking"] == {"type": "disabled"}
    assert p["output_config"] == {"format": {"type": "json_schema", "schema": schema}}
    assert p["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "temperature" not in p                      # Haiku 5.5 weigert sampling-parameters
    assert (claude.invoer_tokens, claude.uitvoer_tokens) == (1000, 20)


def test_tegoed_op_stopt_het_model():
    claude, _ = model(fout(anthropic.BadRequestError, 400,
                           "Your credit balance is too low to access the Anthropic API."))
    with pytest.raises(StopVerrijking, match="tegoed"):
        claude.vraag("s", "g")
    claude, _ = model(fout(anthropic.APIStatusError, 402, "billing"))
    with pytest.raises(StopVerrijking, match="tegoed"):
        claude.vraag("s", "g")


def test_onbekend_model_valt_terug_op_volgend_model():
    claude, berichten = model(fout(anthropic.NotFoundError, 404, "model not found"), antwoord(),
                              modellen=("claude-bestaat-niet", "claude-haiku-5-5"))
    assert claude.vraag("s", "g") == '{"ok": true}'
    assert [p["model"] for p in berichten.verzoeken] == ["claude-bestaat-niet", "claude-haiku-5-5"]


def test_weigering_en_drie_fouten_op_rij():
    claude, _ = model(antwoord(stop="refusal"), antwoord(stop="max_tokens"), antwoord(stop="refusal"))
    with pytest.raises(ValueError, match="veiligheidsfilter"):
        claude.vraag("s", "g")
    with pytest.raises(ValueError, match="max_tokens"):
        claude.vraag("s", "g")
    with pytest.raises(StopVerrijking):
        claude.vraag("s", "g")


def test_sleutel_geweigerd_en_limiet():
    claude, _ = model(fout(anthropic.AuthenticationError, 401, "invalid x-api-key"))
    with pytest.raises(StopVerrijking, match="geweigerd"):
        claude.vraag("s", "g")
    claude, _ = model(fout(anthropic.RateLimitError, 429, "rate limited"))
    with pytest.raises(StopVerrijking, match="limiet"):
        claude.vraag("s", "g")


def test_claude_eerst_gemini_als_reserve():
    clients = maak_taalmodellen(["anthropic", "gemini"], {"anthropic": ["claude-haiku-5-5"], "gemini": ["g"]}, 0,
                                omgeving={"ANTHROPIC_API_KEY": "sk-test", "GEMINI_API_KEY": "x"})
    assert [type(c).__name__ for c in clients] == ["ClaudeModel", "Taalmodel"]
    assert maak_taalmodellen(["anthropic"], {"anthropic": ["m"]}, 0, omgeving={}) == []


def test_verrijk_stuurt_schema_mee():
    from pathlib import Path
    from vegannieuws.classificatie import laad_lexicon
    from vegannieuws.locatie import Geo
    from vegannieuws.model import Bericht
    from vegannieuws.verrijking import verrijk
    lexicon = laad_lexicon(Path(__file__).resolve().parents[1] / "categorieen.yml")
    b = Bericht(id="a1", titel="Nouveau restaurant vegan à Liège", url="https://x.be/1", bron="x", bron_naam="X",
                datum="2026-10-29", taal="fr")
    uit = {"berichten": [{"id": "a1", "relevant": True, "kernzin": "Een vegan restaurant opent in Luik.",
                          "titel": "Nieuw vegan restaurant in Luik", "samenvatting": "", "categorieen": ["horeca"],
                          "gebeurtenis": "opening", "land": "BE", "plaats": "Luik"}]}
    claude, berichten = model(antwoord(json.dumps(uit)))
    stat = verrijk([b], claude, lexicon, Geo(), "nl", ["nl", "en"], 12, 5, 3)
    schema = berichten.verzoeken[0]["output_config"]["format"]["schema"]
    assert "horeca" in schema["properties"]["berichten"]["items"]["properties"]["categorieen"]["items"]["enum"]
    assert stat.verrijkt == 1 and b.kernzin.startswith("Een vegan restaurant") and b.gebeurtenis == "opening"



def test_gemini_neemt_over_als_claude_tegoed_op_is(wortel, monkeypatch):
    from vegannieuws import verzamelen
    from vegannieuws.archief import Archief
    from vegannieuws.classificatie import laad_lexicon
    from vegannieuws.config import Instellingen
    from vegannieuws.locatie import Geo
    from vegannieuws.model import Bericht
    from vegannieuws.staat import Staat
    from datetime import date
    vandaag = date.today().isoformat()
    archief = Archief(wortel / "site" / "data")
    titels = ["Nieuw vegan restaurant opent in Gent", "Kweekvlees krijgt goedkeuring in Singapore",
              "Studie over plantaardige voeding bij kinderen"]
    archief.voeg_toe([Bericht(id=f"b{i}", titel=titel, url=f"https://x.be/{i}", bron="x", bron_naam="X",
                              datum=vandaag, taal="nl") for i, titel in enumerate(titels)])
    claude, berichten = model(fout(anthropic.BadRequestError, 400,
                                   "Your credit balance is too low to access the Anthropic API."))

    class Gemini:
        naam, model, token, invoer_tokens, uitvoer_tokens = "Google Gemini", "gemini-flash-lite-latest", "", 50, 30

        def vraag(self, systeem, gebruiker, schema=None):
            return json.dumps({"berichten": [{"id": i["id"], "relevant": True, "kernzin": f"Kern {i['titel']}",
                                              "categorieen": ["overig"]} for i in json.loads(gebruiker)]})

    monkeypatch.setattr(verzamelen, "maak_taalmodellen", lambda *a, **k: [claude, Gemini()])
    stat = verzamelen._verrijk_achterstand(archief, Instellingen(), laad_lexicon(wortel / "categorieen.yml"), Geo(),
                                           Staat(), vandaag, log=lambda *_: None)
    assert len(berichten.verzoeken) == 1                     # Claude: één geweigerd verzoek
    assert stat.verrijkt == 3 and stat.achterstand == 0      # Gemini deed de rest
    assert "tegoed" in stat.melding and stat.aanbieder == "Anthropic Claude → Google Gemini"
    assert all(b.kernzin.startswith("Kern ") for b in archief.geladen())
