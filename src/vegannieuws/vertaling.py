"""Reservevertaling van titels via de gratis MyMemory-API, als het taalmodel niet beschikbaar is.

Anoniem gebruik is beperkt tot ongeveer 5 000 tekens per dag; met een e-mailadres
(instelling mymemory_email) is dat 50 000 tekens per dag.
"""

from __future__ import annotations

import html

import requests

from .model import Bericht

URL = "https://api.mymemory.translated.net/get"
ONDERSTEUNDE_TALEN = {"nl", "fr", "en", "de", "es", "it", "pt"}


class QuotumOp(Exception):
    pass


def vertaal(sessie: requests.Session, tekst: str, van: str, naar: str, email: str = "") -> str:
    params = {"q": tekst[:480], "langpair": f"{van}|{naar}"}
    if email:
        params["de"] = email
    antwoord = sessie.get(URL, params=params, timeout=(10, 20))
    if antwoord.status_code == 429:
        raise QuotumOp("MyMemory: te veel verzoeken")
    antwoord.raise_for_status()
    gegevens = antwoord.json()
    vertaling = html.unescape((gegevens.get("responseData") or {}).get("translatedText") or "")
    if gegevens.get("quotaFinished") or "MYMEMORY WARNING" in vertaling.upper():
        raise QuotumOp("MyMemory: dagquotum bereikt")
    if str(gegevens.get("responseStatus")) != "200" or not vertaling.strip():
        return ""
    return vertaling.strip()


def vertaal_titels(berichten: list[Bericht], doeltaal: str, talen_zonder_vertaling: list[str], max_tekens: int,
                   email: str = "", sessie: requests.Session | None = None) -> tuple[int, int, str]:
    """Vertaalt titels van nog onvertaalde berichten. Geeft (aantal, verbruikte tekens, melding) terug."""
    sessie = sessie or requests.Session()
    aantal = tekens = 0
    for b in berichten:
        if b.vertaald or b.taal in talen_zonder_vertaling or b.taal not in ONDERSTEUNDE_TALEN or b.taal == doeltaal:
            continue
        if tekens + len(b.titel) > max_tekens:
            return aantal, tekens, "dagbudget voor reservevertaling bereikt"
        try:
            vertaling = vertaal(sessie, b.titel, b.taal, doeltaal, email)
        except QuotumOp as fout:
            return aantal, tekens, str(fout)
        except (requests.RequestException, ValueError) as fout:
            return aantal, tekens, f"MyMemory niet bereikbaar ({type(fout).__name__})"
        tekens += len(b.titel)
        if vertaling and vertaling.casefold() != b.titel.casefold():
            b.titel_orig = b.titel
            b.titel = vertaling
            b.vertaald = "mymemory"
            aantal += 1
    return aantal, tekens, ""
