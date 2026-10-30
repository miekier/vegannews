"""Opdrachtregel: python -m vegannieuws <opdracht>."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .beheer import verwerk_aanvraag
from .bronnen import laad_register
from .config import laad_instellingen, standaard_paden
from .ophalen import Ophaler
from .staat import Staat
from .verzamelen import herindeel, rapport_markdown, verzamel


def _schrijf_samenvatting(tekst: str) -> None:
    pad = os.environ.get("GITHUB_STEP_SUMMARY")
    if pad:
        with open(pad, "a", encoding="utf-8") as f:
            f.write(tekst)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vegannieuws", description="Verzamelt nieuws over veganisme.")
    sub = parser.add_subparsers(dest="opdracht", required=True)
    v = sub.add_parser("verzamel", help="haal alle bronnen op en werk het archief en de website bij")
    v.add_argument("--terugvullen", type=int, default=0, help="zoek ook ouder nieuws op (aantal dagen)")
    v.add_argument("--zonder-llm", action="store_true", help="gebruik het taalmodel niet")
    v.add_argument("--bron", action="append", help="enkel deze bron-id's (herhaalbaar)")
    c = sub.add_parser("controleer", help="test bronnen zonder iets op te slaan")
    c.add_argument("bron", nargs="*", help="bron-id's (standaard: alle actieve bronnen)")
    h = sub.add_parser("herindeel", help="pas de trefwoorden opnieuw toe op bestaande berichten")
    h.add_argument("--dagen", type=int, default=90)
    a = sub.add_parser("bron-aanvraag", help="verwerk een ingevuld bronformulier (GitHub-issue)")
    a.add_argument("--tekst-env", default="ISSUE_BODY", help="omgevingsvariabele met de tekst van het issue")
    a.add_argument("--issue", default="")
    a.add_argument("--antwoord", default="antwoord.md")
    a.add_argument("--resultaat", default="aanvraag.json")
    args = parser.parse_args(argv)

    paden = standaard_paden()
    inst = laad_instellingen(paden.instellingen)

    if args.opdracht == "verzamel":
        rapport = verzamel(paden, inst, terugvullen_dagen=max(0, args.terugvullen), gebruik_llm=not args.zonder_llm,
                           alleen=set(args.bron) if args.bron else None)
        tekst = rapport_markdown(rapport)
        print(tekst)
        _schrijf_samenvatting(tekst)
        return 0

    if args.opdracht == "controleer":
        bronnen, waarschuwingen = laad_register(paden.bronnen, paden.zoekopdrachten)
        for w in waarschuwingen:
            print(f"WAARSCHUWING: {w}")
        gekozen = [b for b in bronnen if (b.id in args.bron if args.bron else b.actief)]
        ophaler = Ophaler(Staat(), inst)
        regels = ["| Bron | Soort | Status | Berichten | Feed / melding | Laatste titel |", "|---|---|---|---|---|---|"]
        fouten = 0
        for b in gekozen:
            res = ophaler.haal(b)
            fouten += res.status == "fout"
            titel = res.berichten[0].titel[:70] if res.berichten else ""
            regels.append(f"| {b.naam} (`{b.id}`) | {b.soort} | {res.status} | {len(res.berichten)} | "
                          f"{res.melding or res.feed} | {titel} |")
        tekst = "## Controle van bronnen\n\n" + "\n".join(regels) + f"\n\n{len(gekozen) - fouten} van {len(gekozen)} bronnen werken.\n"
        print(tekst)
        _schrijf_samenvatting(tekst)
        return 0

    if args.opdracht == "herindeel":
        herindeel(paden, inst, args.dagen)
        return 0

    if args.opdracht == "bron-aanvraag":
        uitkomst = verwerk_aanvraag(paden, inst, os.environ.get(args.tekst_env, ""), args.issue)
        Path(args.antwoord).write_text(uitkomst.antwoord + "\n", encoding="utf-8")
        Path(args.resultaat).write_text(json.dumps({"gewijzigd": uitkomst.gewijzigd, "sluiten": uitkomst.sluiten}),
                                        encoding="utf-8")
        print(uitkomst.antwoord)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
