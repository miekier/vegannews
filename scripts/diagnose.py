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
    ("vegout-us", "VegOut Magazine", "https://vegoutmag.com/feed/", "medium", False),
    ("onegreenplanet-us", "One Green Planet", "https://www.onegreenplanet.org", "medium", False),
    ("worldanimalnews-us", "World Animal News", "https://worldanimalnews.com", "medium", False),
    ("farmsanctuary-us", "Farm Sanctuary", "https://www.farmsanctuary.org", "organisatie", False),
    ("thehumaneleague-us", "The Humane League", "https://thehumaneleague.org", "organisatie", False),
    ("happycow", "HappyCow", "https://www.happycow.net/blog/", "medium", False),
    ("foodnavigator-usa", "FoodNavigator-USA", "https://www.foodnavigator-usa.com/", "medium", True),
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


def sociale_media_in_google_nieuws() -> None:
    print("\n== Sociale media in Google Nieuws ==")
    vragen = [
        ("site:instagram.com vegan when:7d", "BE:nl"),
        ("site:instagram.com vegan Gent when:30d", "BE:nl"),
        ("site:instagram.com vegan Antwerpen when:30d", "BE:nl"),
        ("site:instagram.com vegan Brussel OR Bruxelles when:30d", "BE:nl"),
        ("site:instagram.com veganistisch OR plantaardig when:30d", "BE:nl"),
        ("site:instagram.com vegan when:7d", "BE:fr"),
        ("site:instagram.com/bevegan.be", "BE:nl"),
        ("site:instagram.com bevegan", "BE:nl"),
        ("site:facebook.com vegan Gent when:30d", "BE:nl"),
        ("site:tiktok.com vegan België when:30d", "BE:nl"),
        ("site:threads.net vegan when:30d", "BE:nl"),
    ]
    for q, editie in vragen:
        land, taal = editie.split(":")
        url = f"https://news.google.com/rss/search?q={requests.utils.quote(q)}&hl={taal}&gl={land}&ceid={editie}"
        r = requests.get(url, headers=UA, timeout=30)
        items = re.findall(r"<item>(.*?)</item>", r.text, re.S)
        print(f"\n- {q} ({editie}): HTTP {r.status_code}, {len(items)} resultaten")
        for item in items[:12]:
            titel = re.search(r"<title>(.*?)</title>", item, re.S)
            datum = re.search(r"<pubDate>(.*?)</pubDate>", item)
            link = re.search(r"<link>(.*?)</link>", item)
            bron = re.search(r'<source url="([^"]*)"[^>]*>(.*?)</source>', item)
            beschrijving = re.search(r"<description>(.*?)</description>", item, re.S)
            print(f"    {datum.group(1) if datum else '-'} | {(titel.group(1) if titel else '')[:110]}")
            print(f"        bron={bron.groups() if bron else '-'} link={(link.group(1) if link else '')[:90]}")
            if beschrijving:
                print(f"        beschrijving={re.sub(r'<[^>]+>|&lt;[^&]*&gt;', ' ', beschrijving.group(1))[:160]}")


def logo_kleuren(url: str) -> None:
    print(f"\n== Logo {url} ==")
    try:
        from io import BytesIO

        from PIL import Image
    except ImportError:
        print("Pillow ontbreekt")
        return
    r = requests.get(url, headers=UA, timeout=30)
    beeld = Image.open(BytesIO(r.content)).convert("RGB").resize((150, 150))
    tellers = collections.Counter()
    for kleur in beeld.getdata():
        tellers[tuple(c // 8 * 8 for c in kleur)] += 1
    print("dominante kleuren:", [("#%02x%02x%02x" % k, n) for k, n in tellers.most_common(14)])


def enfold_variabelen(url: str) -> None:
    print(f"\n== Enfold-kleurvariabelen {url} ==")
    r = requests.get(url, headers=UA, timeout=60)
    gezien = set()
    for naam, waarde in re.findall(r"(--enfold-[\w-]+)\s*:\s*([^;}{]+)", r.text):
        if naam not in gezien:
            gezien.add(naam)
            if any(d in naam for d in ("header", "main", "alternate", "socket-color-primary", "footer-color-primary")):
                print(f"{naam}: {waarde.strip()}")
    for selector in (".main_color", "#header", ".header_color", "#top .av-main-nav", ".av-special-heading-tag",
                     "h1", "h2", "h3", "body", "a"):
        for m in re.finditer(r"(?:^|})\s*([^{}]*" + re.escape(selector) + r"[^{}]*){([^}]*)}", r.text):
            if "color" in m.group(2) or "font" in m.group(2):
                print(f"{m.group(1).strip()[:120]} {{{m.group(2).strip()[:200]}}}")
                break



if __name__ == "__main__":
    test_bronnen()
    sociale_media_in_google_nieuws()
    for adres in ("https://bevegan.be/wp-content/uploads/2017/04/bevegan-450x450.png",
                  "https://bevegan.be/wp-content/uploads/2024/11/BE-Vegan-logo-300x300.jpeg"):
        try:
            logo_kleuren(adres)
        except Exception as fout:  # noqa: BLE001
            print(adres, "->", type(fout).__name__, fout)
    for adres in ("https://bevegan.be/wp-content/uploads/dynamic_avia/enfold_child.css",
                  "https://bevegan.be/wp-content/themes/enfold-child/style.css",
                  "https://bevegan.be/wp-content/plugins/bevegan_zonapro/bevegan_zonapro.css"):
        try:
            enfold_variabelen(adres)
        except requests.RequestException as fout:
            print(adres, "->", type(fout).__name__, fout)
