"""Claude (Anthropic) als taalmodel, via de officiële Anthropic-SDK.

Zelfde interface als verrijking.Taalmodel: vraag(systeem, gebruiker, schema) geeft JSON-tekst terug.
- Denken staat uit: de taken (vertalen, kernzin, indeling) vragen geen redenering, en denktokens kosten geld.
- Met een schema garandeert de API geldige JSON (structured outputs).
- De systeemprompt wordt gecachet: volgende verzoeken binnen 5 minuten lezen hem aan 0,1x de prijs.
Is het tegoed op of de sleutel ongeldig, dan stopt dit model voor de rest van de run en neemt de
volgende aanbieder (Gemini) het over.
"""

from __future__ import annotations

import anthropic

from .verrijking import StopVerrijking


class ClaudeModel:
    def __init__(self, sleutel: str, modellen: list[str], naam: str = "Anthropic Claude", max_tokens: int = 8000,
                 client: anthropic.Anthropic | None = None):
        self.naam = naam
        self.token = ""
        self.modellen = list(modellen)
        self.max_tokens = max_tokens
        self.client = client or anthropic.Anthropic(api_key=sleutel, max_retries=2, timeout=180.0)
        self.diagnoses: list[str] = []
        self.invoer_tokens = 0
        self.uitvoer_tokens = 0
        self._fouten_op_rij = 0

    @property
    def model(self) -> str:
        return self.modellen[0] if self.modellen else ""

    def _fout(self, melding: str) -> ValueError:
        """Een mislukt verzoek; na drie op rij is het model voor deze run onbruikbaar."""
        self._fouten_op_rij += 1
        if self._fouten_op_rij >= 3:
            raise StopVerrijking(f"{self.naam}: drie mislukte verzoeken na elkaar ({melding})")
        return ValueError(melding)

    def vraag(self, systeem: str, gebruiker: str, schema: dict | None = None) -> str:
        while self.modellen:
            parameters: dict = {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "system": [{"type": "text", "text": systeem, "cache_control": {"type": "ephemeral"}}],
                "messages": [{"role": "user", "content": gebruiker}],
                "thinking": {"type": "disabled"},
            }
            if schema:
                parameters["output_config"] = {"format": {"type": "json_schema", "schema": schema}}
            try:
                antwoord = self.client.messages.create(**parameters)
            except anthropic.NotFoundError:
                self.diagnoses.append(f"model {self.model} niet beschikbaar")
                self.modellen.pop(0)
                continue
            except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as fout:
                raise StopVerrijking(f"sleutel van {self.naam} geweigerd (HTTP {fout.status_code})") from None
            except anthropic.RateLimitError:
                raise StopVerrijking(f"limiet van {self.naam} bereikt (HTTP 429); de volgende run gaat verder") from None
            except anthropic.APIConnectionError as fout:
                raise StopVerrijking(f"{self.naam} onbereikbaar ({type(fout).__name__})") from None
            except anthropic.APIStatusError as fout:
                bericht = str(getattr(fout, "message", "") or "")
                if fout.status_code == 402 or "credit balance" in bericht.lower():
                    raise StopVerrijking(f"het tegoed bij {self.naam} is op; de reserve-aanbieder neemt over") from None
                raise self._fout(f"HTTP {fout.status_code}: {bericht[:200]}") from None
            gebruik = antwoord.usage
            self.invoer_tokens += (gebruik.input_tokens or 0) + (gebruik.cache_creation_input_tokens or 0) \
                + (gebruik.cache_read_input_tokens or 0)
            self.uitvoer_tokens += gebruik.output_tokens or 0
            if antwoord.stop_reason == "refusal":
                raise self._fout("verzoek geweigerd door de veiligheidsfilter van het model")
            if antwoord.stop_reason == "max_tokens":
                raise self._fout("antwoord afgebroken: max_tokens bereikt")
            self._fouten_op_rij = 0
            return "".join(blok.text for blok in antwoord.content if blok.type == "text")
        raise StopVerrijking(f"geen werkend model bij {self.naam}. " + " | ".join(self.diagnoses[-3:]))

    def test(self) -> str:
        """Eén klein verzoek om te controleren of het model bereikbaar is."""
        schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"],
                  "additionalProperties": False}
        try:
            antwoord = self.vraag("Antwoord uitsluitend met een JSON-object.", 'Geef {"ok": true} terug.', schema)
        except StopVerrijking as fout:
            return f"werkt niet: {fout}"
        except ValueError as fout:
            return f"fout: {fout}"
        return f"werkt: model {self.model} (antwoord {antwoord.strip()[:60]!r})"
