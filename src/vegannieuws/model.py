"""Gegevensmodel van een nieuwsbericht."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields


@dataclass
class Bericht:
    id: str
    titel: str                      # in de doeltaal (of origineel als vertaling niet nodig/mogelijk was)
    url: str
    bron: str                       # id uit het bronnenregister
    bron_naam: str
    samenvatting: str = ""
    kernzin: str = ""               # één zin: wat gebeurde waar (door taalmodel)
    titel_orig: str = ""            # enkel ingevuld als de titel vertaald werd
    samenvatting_orig: str = ""
    taal: str = ""                  # brontaal
    vertaald: str = ""              # "", "llm" of "mymemory"
    uitgever: str = ""              # medium dat het bericht publiceerde (bij zoekopdrachten)
    relatie: str = "secundair"      # primair = de organisatie/het bedrijf zelf, secundair = media
    brontype: str = ""
    gepubliceerd: str = ""          # ISO 8601, UTC
    opgehaald: str = ""             # ISO 8601, UTC
    datum: str = ""                 # JJJJ-MM-DD in Belgische tijd; hierop wordt gefilterd
    categorieen: list[str] = field(default_factory=list)
    gebeurtenis: str = ""           # opening, sluiting, lancering
    regio: str = ""                 # BE of INT
    land: str = ""
    plaats: str = ""
    gewest: str = ""
    relevantie: int = 0             # aantal treffers op vegan-gerelateerde trefwoorden
    relevant: bool = True           # False als het taalmodel het bericht niet relevant vond
    kandidaat: bool = False         # zoekresultaat zonder vegan-woord in de titel: taalmodel beslist
    zoekterm: str = ""              # bij kandidaten: de zoekterm waarmee het artikel gevonden werd
    sociaal: str = ""               # post op een sociaal netwerk (Instagram, Facebook, ...), gevonden via Google Nieuws
    methode: str = "regels"         # regels of llm
    extra: list[dict] = field(default_factory=list)   # andere bronnen met (bijna) hetzelfde artikel
    verhaal: str = ""               # id van het verhaal: berichten van verschillende bronnen over hetzelfde nieuws
    verhaal_kop: str = ""           # Nederlandse kop van dat verhaal
    pogingen: int = 0               # mislukte pogingen tot verrijking door het taalmodel
    uitgever_url: str = field(default="", metadata={"tijdelijk": True})

    def naar_dict(self) -> dict:
        uit = {}
        for k, v in asdict(self).items():
            if k == "uitgever_url":
                continue
            if v in ("", [], None) or (k == "pogingen" and v == 0) or (k == "relevant" and v is True) \
                    or (k == "kandidaat" and v is False):
                continue
            uit[k] = v
        return uit

    @classmethod
    def van_dict(cls, gegevens: dict) -> "Bericht":
        namen = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in gegevens.items() if k in namen})
