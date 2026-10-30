"""Paden en instellingen."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Paden:
    wortel: Path

    @property
    def bronnen(self) -> Path:
        return self.wortel / "bronnen.yml"

    @property
    def zoekopdrachten(self) -> Path:
        return self.wortel / "zoekopdrachten.yml"

    @property
    def categorieen(self) -> Path:
        return self.wortel / "categorieen.yml"

    @property
    def instellingen(self) -> Path:
        return self.wortel / "instellingen.yml"

    @property
    def site_data(self) -> Path:
        return self.wortel / "site" / "data"

    @property
    def staat(self) -> Path:
        return self.wortel / "staat" / "staat.json"


def standaard_paden() -> Paden:
    wortel = os.environ.get("VEGANNIEUWS_WORTEL")
    return Paden(Path(wortel) if wortel else Path(__file__).resolve().parents[2])


@dataclass
class Instellingen:
    doeltaal: str = "nl"
    talen_zonder_vertaling: list[str] = field(default_factory=lambda: ["nl", "en"])
    tijdzone: str = "Europe/Brussels"
    max_leeftijd_dagen: int = 60
    google_recentheid: str = "when:7d"
    google_pauze_s: float = 1.5
    gelijktijdig: int = 12
    llm_aan: bool = True
    llm_aanbieders: list[str] = field(default_factory=lambda: ["gemini", "groq"])
    llm_modellen_gemini: list[str] = field(default_factory=lambda: [
        "gemini-flash-lite-latest", "gemini-2.5-flash-lite", "gemini-flash-latest", "gemini-2.5-flash"])
    llm_modellen_groq: list[str] = field(default_factory=lambda: [
        "llama-3.3-70b-versatile", "openai/gpt-oss-120b", "llama-3.1-8b-instant"])
    llm_modellen: list[str] = field(default_factory=lambda: ["openai/gpt-4.1-mini", "openai/gpt-4o-mini"])
    llm_max_verzoeken_per_run: int = 80
    llm_max_verzoeken_per_dag: int = 240
    llm_batch: int = 12
    llm_pauze_s: float = 4.5
    llm_max_pogingen: int = 3
    llm_max_leeftijd_dagen: int = 21
    sociaal_enkel_land: str = "BE"
    verhalen_aan: bool = True
    verhalen_venster_dagen: int = 4
    verhalen_modellen_gemini: list[str] = field(default_factory=lambda: ["gemini-flash-latest", "gemini-2.5-flash"])
    verhalen_max_verzoeken_per_run: int = 4
    reserve_vertaling: bool = True
    reserve_max_tekens_per_dag: int = 4500
    mymemory_email: str = ""
    repo: str = ""

    @property
    def modellen_per_aanbieder(self) -> dict[str, list[str]]:
        return {"gemini": self.llm_modellen_gemini, "groq": self.llm_modellen_groq, "github": self.llm_modellen}

    @property
    def repository(self) -> str:
        return self.repo or os.environ.get("GITHUB_REPOSITORY", "")


def _als_bool(waarde: object) -> bool:
    if isinstance(waarde, bool):
        return waarde
    return str(waarde).strip().lower() in {"ja", "yes", "true", "waar", "1", "aan"}


def laad_instellingen(pad: Path) -> Instellingen:
    inst = Instellingen()
    if not pad.exists():
        return inst
    gegevens = yaml.safe_load(pad.read_text(encoding="utf-8")) or {}
    for veld in fields(Instellingen):
        if veld.name not in gegevens or gegevens[veld.name] is None:
            continue
        waarde = gegevens[veld.name]
        huidig = getattr(inst, veld.name)
        if isinstance(huidig, bool):
            waarde = _als_bool(waarde)
        elif isinstance(huidig, int):
            waarde = int(waarde)
        elif isinstance(huidig, float):
            waarde = float(waarde)
        elif isinstance(huidig, list):
            waarde = [str(w) for w in (waarde if isinstance(waarde, list) else [waarde])]
        else:
            waarde = str(waarde)
        setattr(inst, veld.name, waarde)
    return inst
