"""Toestand tussen twee runs: HTTP-validators, ontdekte feeds, bronstatus en dagbudgetten."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Staat:
    http: dict[str, dict] = field(default_factory=dict)        # url -> {etag, gewijzigd}
    feeds: dict[str, dict] = field(default_factory=dict)       # bron-id -> {feed, gevonden}
    bronnen: dict[str, dict] = field(default_factory=dict)     # bron-id -> status
    budget: dict[str, dict] = field(default_factory=dict)      # naam -> {datum, gebruikt}
    geweigerd: dict[str, str] = field(default_factory=dict)    # bericht-id -> datum (kandidaat afgewezen)

    @classmethod
    def laad(cls, pad: Path) -> "Staat":
        if not pad.exists():
            return cls()
        gegevens = json.loads(pad.read_text(encoding="utf-8") or "{}")
        return cls(
            http=gegevens.get("http", {}),
            feeds=gegevens.get("feeds", {}),
            bronnen=gegevens.get("bronnen", {}),
            budget=gegevens.get("budget", {}),
            geweigerd=gegevens.get("geweigerd", {}),
        )

    def bewaar(self, pad: Path) -> None:
        pad.parent.mkdir(parents=True, exist_ok=True)
        gegevens = {"http": self.http, "feeds": self.feeds, "bronnen": self.bronnen, "budget": self.budget,
                    "geweigerd": self.geweigerd}
        pad.write_text(json.dumps(gegevens, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")

    def resterend(self, naam: str, datum: str, limiet: int) -> int:
        b = self.budget.get(naam)
        if not b or b.get("datum") != datum:
            return limiet
        return max(0, limiet - int(b.get("gebruikt", 0)))

    def verbruik(self, naam: str, datum: str, hoeveelheid: int) -> None:
        b = self.budget.get(naam)
        if not b or b.get("datum") != datum:
            b = {"datum": datum, "gebruikt": 0}
        b["gebruikt"] = int(b.get("gebruikt", 0)) + hoeveelheid
        self.budget[naam] = b
