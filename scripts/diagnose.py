"""Tijdelijke diagnose: test kandidaat-bronnen en leest de huisstijl van een website uit.

Gebruik: python scripts/diagnose.py
"""

from __future__ import annotations

import collections
import re
import sys
from urllib.parse import urljoin

import requests

sys.path.insert(0, "src")

from vegannieuws.bronnen import Bron  # noqa: E402
from vegannieuws.config import laad_instellingen, standaard_paden  # noqa: E402
from vegannieuws.ophalen import Ophaler  # noqa: E402
from vegannieuws.staat import Staat  # noqa: E402

KANDIDATEN = [
    ("vegout-us", "VegOut Magazine", "https://vegoutmag.com", "medium", False),
    ("pcrm-us", "Physicians Committee for Responsible Medicine", "https://www.pcrm.org", "organisatie", True),
    ("aldf-us", "Animal Legal Defense Fund", "https://aldf.org", "organisatie", False),
    ("pbfa-us", "Plant Based Foods Association", "https://www.plantbasedfoods.org", "organisatie", False),
    ("eater-us", "Eater", "https://www.eater.com", "medium", True),
    ("foodnavigator-usa", "FoodNavigator-USA", "https://www.foodnavigator-usa.com", "medium", True),
    ("thebeet-us", "The Beet", "https://thebeet.com", "medium", False),
    ("civileats-us", "Civil Eats", "https://civileats.com", "medium", True),
]
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}


def test_bronnen() -> None:
    inst = laad_instellingen(standaard_paden().instellingen)
    ophaler = Ophaler(Staat(), inst)
    print("== Kandidaat-bronnen ==")
    for id_, naam, url, type_, alleen in KANDIDATEN:
        bron = Bron(id=id_, naam=naam, soort="website", type=type_, url=url, taal="en", land="US", alleen_vegan=alleen)
        res = ophaler.haal(bron)
        print(f"- {naam}: status={res.status} berichten={len(res.berichten)} feed={res.feed} melding={res.melding}")
        for r in res.berichten[:6]:
            print(f"    {r.gepubliceerd} | {r.titel[:90]}")


def huisstijl(url: str) -> None:
    print(f"\n== Huisstijl {url} ==")
    sessie = requests.Session()
    antwoord = sessie.get(url, headers=UA, timeout=30)
    html = antwoord.text
    print("HTTP", antwoord.status_code, "lengte", len(html))
    for m in re.finditer(r'<meta[^>]+(?:theme-color|og:image|og:site_name)[^>]*>', html, re.I):
        print("meta:", m.group(0)[:200])
    for m in re.finditer(r'<link[^>]+(?:icon|fonts\.googleapis|typekit|stylesheet)[^>]*>', html, re.I):
        print("link:", m.group(0)[:220])
    css_urls = [urljoin(url, h) for h in re.findall(r'<link[^>]+rel=["\']?stylesheet["\']?[^>]*href=["\']([^"\']+)', html, re.I)]
    css_urls += [urljoin(url, h) for h in re.findall(r'<link[^>]+href=["\']([^"\']+\.css[^"\']*)["\'][^>]*rel=["\']?stylesheet', html, re.I)]
    css = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", html, re.S | re.I))
    for css_url in dict.fromkeys(css_urls):
        try:
            r = sessie.get(css_url, headers=UA, timeout=30)
            print(f"css: {css_url[:160]} -> {r.status_code}, {len(r.text)} tekens")
            css += "\n" + r.text
        except requests.RequestException as fout:
            print(f"css: {css_url[:160]} -> {type(fout).__name__}")
    kleuren = collections.Counter(k.lower() for k in re.findall(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b", css))
    print("kleuren (hex, frequentie):", kleuren.most_common(40))
    rgb = collections.Counter(re.findall(r"rgba?\([^)]*\)", css))
    print("kleuren (rgb):", rgb.most_common(15))
    variabelen = collections.Counter(re.findall(r"(--[\w-]*colou?r[\w-]*)\s*:\s*([^;}{]+)", css))
    print("kleurvariabelen:", [f"{k}={v.strip()}" for (k, v), _ in variabelen.most_common(40)])
    fonts = collections.Counter(f.strip() for f in re.findall(r"font-family\s*:\s*([^;}{]+)", css))
    print("lettertypes:", fonts.most_common(20))
    for m in re.finditer(r"@font-face\s*{[^}]*}", css):
        print("font-face:", re.sub(r"\s+", " ", m.group(0))[:200])
    for selector in ("body", "h1", "h2", "h3", "a", "button", ".button", ".btn", "header", "footer", ".site-header"):
        for m in re.finditer(r"(?:^|})\s*" + re.escape(selector) + r"\s*{([^}]*)}", css):
            print(f"{selector} {{{re.sub(chr(10), ' ', m.group(1))[:220]}}}")
            break
    tekst = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
    tekst = re.sub(r"<[^>]+>", " ", tekst)
    print("tekst:", re.sub(r"\s+", " ", tekst)[:1200])
    for m in re.finditer(r'<img[^>]+(?:logo)[^>]*>', html, re.I):
        print("logo:", m.group(0)[:250])


def instagram_in_google_nieuws() -> None:
    print("\n== Instagram in Google Nieuws ==")
    for q, editie in (("site:instagram.com vegan", "BE:nl"), ("site:instagram.com vegan restaurant", "US:en"),
                      ("instagram.com vegan Gent", "BE:nl")):
        land, taal = editie.split(":")
        url = f"https://news.google.com/rss/search?q={requests.utils.quote(q)}&hl={taal}&gl={land}&ceid={editie}"
        r = requests.get(url, headers=UA, timeout=30)
        titels = re.findall(r"<item>.*?<title>(.*?)</title>.*?<source url=\"([^\"]*)\"", r.text, re.S)
        print(f"- {q} ({editie}): HTTP {r.status_code}, {len(titels)} resultaten; bronnen: "
              f"{collections.Counter(s for _, s in titels).most_common(5)}")


if __name__ == "__main__":
    test_bronnen()
    instagram_in_google_nieuws()
    for adres in sys.argv[1:] or ["https://www.bevegan.be/"]:
        try:
            huisstijl(adres)
        except requests.RequestException as fout:
            print(adres, "->", type(fout).__name__, fout)
