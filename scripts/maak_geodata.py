"""Genereert src/vegannieuws/data/plaatsen_be.json en landen.json.

Eenmalig uit te voeren door een ontwikkelaar; het resultaat staat in de repository.
Vereist: pip install geonamescache wordfreq pycountry

Bronnen:
- GeoNames (via geonamescache, CC BY 4.0): Belgische plaatsen met >= 500 inwoners,
  wereldsteden met >= 15 000 inwoners en Amerikaanse staten.
- pycountry (iso-codes): landnamen in het Nederlands, Frans, Duits en Engels.
- wordfreq: woordfrequenties om plaatsnamen te herkennen die ook gewone woorden zijn
  (bv. Boom, Geel, Halen, Spa). Zulke namen worden enkel herkend na een voorzetsel
  ("in Geel", "à Spa").
"""

from __future__ import annotations

import gettext
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

import geonamescache
import pycountry
from wordfreq import zipf_frequency

DOEL = Path(__file__).resolve().parents[1] / "src" / "vegannieuws" / "data"
TALEN = ("nl", "fr", "en", "de")
GEWONE_WOORD_DREMPEL = 3.5   # Zipf-frequentie vanaf wanneer een naam ook een gewoon woord is
GROTE_STAD = 100_000         # grote steden worden altijd herkend

# Steden die de woordfrequentie onterecht als gewoon woord aanduidt: hun frequentie
# komt van het gebruik als plaatsnaam zelf.
NIET_AMBIGU = {"aalst", "beveren", "deurne", "genk", "hasselt", "heusden", "ieper", "knokke", "kortrijk",
               "mechelen", "nieuwpoort", "oostende", "roeselare", "tienen", "turnhout", "waregem", "huy",
               "mons", "waterloo"}

# Plaatsen die in GeoNames ontbreken: fusiegemeenten (2019-2025) en Brusselse wijken.
EXTRA_PLAATSEN = [
    ("Pajottegem", "VLG", 40_000), ("Merelbeke-Melle", "VLG", 36_000), ("Nazareth-De Pinte", "VLG", 24_000),
    ("Beveren-Kruibeke-Zwijndrecht", "VLG", 70_000), ("Tongeren-Borgloon", "VLG", 42_000),
    ("Bilzen-Hoeselt", "VLG", 42_000), ("Tessenderlo-Ham", "VLG", 30_000), ("Lievegem", "VLG", 27_000),
    ("Oudsbergen", "VLG", 23_000), ("Pelt", "VLG", 33_000), ("Puurs-Sint-Amands", "VLG", 26_000),
    ("Kruisem", "VLG", 16_000), ("Laken", "BRU", 60_000), ("Laeken", "BRU", 60_000),
    ("Neder-Over-Heembeek", "BRU", 20_000), ("Haren", "BRU", 5_000), ("Sint-Pieters-Woluwe", "BRU", 42_000),
    ("Woluwe-Saint-Pierre", "BRU", 42_000), ("Molenbeek", "BRU", 97_000), ("Sankt Vith", "WAL", 9_000),
]

# Weergavenaam (Nederlands) voor plaatsen die GeoNames in het Engels noemt.
WEERGAVE = {"Brussels": "Brussel", "Antwerp": "Antwerpen", "Ostend": "Oostende"}

# Bekende anderstalige namen (exoniemen) van Belgische plaatsen.
EXONIEMEN_BE = {
    "Brussels": ["Brussel", "Bruxelles", "Brüssel"],
    "Antwerp": ["Antwerpen", "Anvers"],
    "Gent": ["Gand", "Ghent"],
    "Liège": ["Liege", "Luik", "Lüttich"],
    "Brugge": ["Bruges", "Brügge"],
    "Namur": ["Namen"],
    "Leuven": ["Louvain", "Löwen"],
    "Mechelen": ["Malines"],
    "Kortrijk": ["Courtrai"],
    "Tournai": ["Doornik"],
    "Ostend": ["Oostende", "Ostende"],
    "Aalst": ["Alost"],
    "Roeselare": ["Roulers"],
    "Mouscron": ["Moeskroen"],
    "Ieper": ["Ypres", "Ypern"],
    "Wavre": ["Waver"],
    "Dendermonde": ["Termonde"],
    "Oudenaarde": ["Audenarde"],
    "Ronse": ["Renaix"],
    "Geraardsbergen": ["Grammont"],
    "Tienen": ["Tirlemont"],
    "Sint-Truiden": ["Saint-Trond"],
    "Tongeren": ["Tongres"],
    "Arlon": ["Aarlen"],
    "Huy": ["Hoei"],
    "Nivelles": ["Nijvel"],
    "Halle": ["Hal"],
    "Vilvoorde": ["Vilvorde"],
    "Lier": ["Lierre"],
    "Menen": ["Menin"],
    "Veurne": ["Furnes"],
    "Diksmuide": ["Dixmude"],
    "Enghien": ["Edingen"],
    "Ath": ["Aat"],
    "Soignies": ["Zinnik"],
    "Jodoigne": ["Geldenaken"],
    "Waremme": ["Borgworm"],
    "Visé": ["Wezet"],
    "Lessines": ["Lessen"],
    "Braine-le-Comte": ["'s-Gravenbrakel"],
    "Braine-l'Alleud": ["Eigenbrakel"],
    "Mons": [],
    "Sankt Vith": ["Saint-Vith"],
}

# Bijvoeglijke naamwoorden per land. Kleine letters = hoofdletterongevoelig,
# beginhoofdletter = hoofdlettergevoelig (vermijdt bv. "polish" als werkwoord).
# Keukens die vaak een restaurant beschrijven (Thai, Italiaans, ...) staan er wel in,
# maar wegen bij de regiobepaling minder zwaar dan land- en plaatsnamen.
BIJVOEGLIJK = {
    "BE": ["Belgisch", "Belgische", "Belg", "Belgen", "belge", "belges", "Belgian", "Belgians", "belgischen", "belgischer"],
    "NL": ["Nederlands", "Nederlandse", "Hollandse", "néerlandais", "néerlandaise", "Dutch", "niederländische", "niederländischen"],
    "FR": ["Franse", "français", "française", "French", "französische", "französischen"],
    "DE": ["Duitse", "allemand", "allemande", "German", "deutsche", "deutschen"],
    "GB": ["Britse", "Engelse", "britannique", "anglais", "anglaise", "British", "britische", "britischen"],
    "US": ["Amerikaans", "Amerikaanse", "américain", "américaine", "American", "Americans", "amerikanische", "amerikanischen"],
    "IT": ["Italiaans", "Italiaanse", "italien", "italienne", "Italian", "italienische"],
    "ES": ["Spaans", "Spaanse", "espagnol", "espagnole", "Spanish", "spanische"],
    "CH": ["Zwitsers", "Zwitserse", "Swiss", "Schweizer"],
    "AT": ["Oostenrijks", "Oostenrijkse", "autrichien", "autrichienne", "Austrian", "österreichische"],
    "LU": ["Luxemburgs", "Luxemburgse", "luxembourgeois", "luxembourgeoise", "Luxembourgish"],
    "DK": ["Deens", "Deense", "danois", "danoise", "Danish", "dänische"],
    "SE": ["Zweeds", "Zweedse", "suédois", "suédoise", "Swedish", "schwedische"],
    "NO": ["Noors", "Noorse", "norvégien", "norvégienne", "Norwegian", "norwegische"],
    "FI": ["Fins", "Finse", "finlandais", "finlandaise", "Finnish", "finnische"],
    "IE": ["Iers", "Ierse", "irlandais", "irlandaise", "Irish", "irische"],
    "PL": ["Pools", "Poolse", "polonais", "polonaise", "Polish", "polnische"],
    "CZ": ["Tsjechisch", "Tsjechische", "tchèque", "Czech", "tschechische"],
    "PT": ["Portugees", "Portugese", "portugais", "portugaise", "Portuguese", "portugiesische"],
    "GR": ["Grieks", "Griekse", "grec", "grecque", "Greek", "griechische"],
    "CA": ["Canadees", "Canadese", "canadien", "canadienne", "Canadian", "kanadische"],
    "AU": ["Australisch", "Australische", "australien", "australienne", "Australian", "australische"],
    "NZ": ["Nieuw-Zeelands", "Nieuw-Zeelandse", "néo-zélandais", "néo-zélandaise", "neuseeländische"],
    "JP": ["Japans", "Japanse", "japonais", "japonaise", "Japanese", "japanische"],
    "CN": ["Chinees", "Chinese", "chinois", "chinoise", "chinesische"],
    "IN": ["Indiaas", "Indiase", "Indian", "indische"],
    "KR": ["Zuid-Koreaans", "Zuid-Koreaanse", "sud-coréen", "sud-coréenne", "South Korean", "südkoreanische"],
    "SG": ["Singaporees", "Singaporese", "singapourien", "singapourienne", "Singaporean"],
    "IL": ["Israëlisch", "Israëlische", "israélien", "israélienne", "Israeli", "israelische"],
    "BR": ["Braziliaans", "Braziliaanse", "brésilien", "brésilienne", "Brazilian", "brasilianische"],
    "MX": ["Mexicaans", "Mexicaanse", "mexicain", "mexicaine", "Mexican", "mexikanische"],
    "ZA": ["Zuid-Afrikaans", "Zuid-Afrikaanse", "sud-africain", "sud-africaine", "South African", "südafrikanische"],
    "TH": ["Thaise", "thaïlandais", "thaïlandaise", "Thai"],
    "TR": ["Turks", "Turkse", "turc", "turque", "Turkish", "türkische"],
    "EU": ["Europees", "Europese", "européen", "européenne", "européens", "européennes", "europäische", "europäischen"],
}

EXTRA_LANDNAMEN = {
    "NL": ["Holland"],
    "GB": ["UK", "U.K.", "Britain", "Great Britain", "Groot-Brittannië", "Grande-Bretagne", "Großbritannien",
           "England", "Engeland", "Angleterre", "Scotland", "Schotland", "Écosse", "Schottland", "Wales"],
    "US": ["USA", "U.S.", "U.S.A.", "VS", "Amerika", "America", "États-Unis", "Etats-Unis", "Vereinigte Staaten"],
    "KR": ["South Korea", "Zuid-Korea", "Corée du Sud", "Südkorea"],
    "RU": ["Russia", "Rusland", "Russie", "Russland"],
    "CZ": ["Czech Republic", "Tsjechië", "République tchèque"],
    "TR": ["Turkije", "Turquie", "Türkei"],
    "VN": ["Vietnam", "Viëtnam", "Viêt Nam"],
    "TW": ["Taiwan"],
    "IR": ["Iran"],
    "SY": ["Syrië", "Syrie", "Syrien", "Syria"],
    "BO": ["Bolivia", "Bolivie", "Bolivien"],
    "VE": ["Venezuela"],
    "TZ": ["Tanzania", "Tanzanie", "Tansania"],
    "EU": ["EU", "Europese Unie", "European Union", "Union européenne", "Europäische Union", "UE",
           "Europees Parlement", "European Parliament", "Parlement européen", "Europäisches Parlament",
           "Europese Commissie", "European Commission", "Commission européenne", "EU-Kommission"],
}

# Landnamen die ook een gewoon woord of een eigennaam zijn: niet opnemen.
NIET_ALS_LAND = {"Turkey", "Chad", "Jordan", "Georgia", "Guinea", "Niger", "Mali", "Oman", "Togo", "Jersey",
                 "Chile", "Malta", "China"}
# China en Chili kunnen toch: we voegen ze hieronder met de juiste schrijfwijze toe.
EXTRA_LANDNAMEN.setdefault("CN", []).extend(["China", "Chine"])
EXTRA_LANDNAMEN.setdefault("CL", []).extend(["Chili", "Chile"])
EXTRA_LANDNAMEN.setdefault("MT", []).extend(["Malta", "Malte"])

# Buitenlandse steden die ook een gewoon woord of een voornaam zijn: niet opnemen.
AMBIGUE_STEDEN = {
    "Nice", "Reading", "York", "Mitte", "Bath", "Derby", "Barking", "Sutton", "Brent", "Lincoln", "Bedford",
    "Preston", "Bolton", "Phoenix", "Salvador", "Jos", "Pest", "Palma", "Latina", "Favoriten", "Hamm", "Hagen",
    "Gera", "Siegen", "Kiel", "Essen", "Tours", "Nancy", "Queens", "Mobile", "Victoria", "Aurora", "Hamilton",
    "Columbus", "Kano", "Telde", "Altona", "Wedding", "Moers", "Marl", "Witten", "Hanau", "Worms", "Celle", "Lens",
    "Calais", "Orange", "Chester", "Dover", "Crawley", "Basildon", "Bury", "Wigan", "Slough", "Luton",
}

# Buitenlandse steden met Nederlandse/Franse/Duitse naam die GeoNames niet als hoofdnaam heeft.
STEDEN_EXTRA = {
    "FR": ["Parijs", "Rijsel", "Lille", "Straatsburg", "Duinkerke", "Dunkerque", "Kamerijk", "Atrecht", "Arras"],
    "GB": ["Londen", "Londres", "Edinburgh", "Édimbourg"],
    "DE": ["Berlijn", "Berlin", "Keulen", "Cologne", "Köln", "Aken", "Aix-la-Chapelle", "Aachen", "München", "Munich",
           "Hamburg", "Hambourg", "Frankfurt"],
    "NL": ["Den Haag", "La Haye", "The Hague", "Maastricht", "Amsterdam", "Rotterdam", "Utrecht"],
    "AT": ["Wenen", "Vienne", "Wien", "Vienna"],
    "DK": ["Kopenhagen", "Copenhague", "Copenhagen"],
    "PT": ["Lissabon", "Lisbonne", "Lisbon", "Lisboa"],
    "IT": ["Rome", "Roma", "Rom", "Milaan", "Milan", "Milano", "Mailand", "Napels", "Naples", "Napoli", "Florence",
           "Firenze", "Venetië", "Venise", "Venedig", "Venice", "Turijn", "Turin", "Torino"],
    "CH": ["Genève", "Genf", "Geneva", "Zürich", "Zurich", "Bazel", "Bâle", "Basel", "Lausanne", "Bern", "Berne"],
    "ES": ["Barcelona", "Barcelone", "Madrid", "Sevilla", "Séville", "Valencia", "Valence"],
    "CZ": ["Praag", "Prague", "Prag"],
    "PL": ["Warschau", "Varsovie", "Warsaw", "Krakau", "Cracovie", "Kraków"],
    "HU": ["Boedapest", "Budapest"],
    "GR": ["Athene", "Athènes", "Athen", "Athens"],
    "RU": ["Moskou", "Moscou", "Moskau", "Moscow"],
    "IE": ["Dublin"],
    "LU": ["Luxemburg-Stad", "Luxembourg-Ville"],
    "US": ["New York", "Los Angeles", "San Francisco", "Washington D.C."],
    "JP": ["Tokio", "Tokyo"],
    "CN": ["Peking", "Pékin", "Beijing", "Shanghai", "Hongkong", "Hong Kong"],
}


def _zonder_accenten(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _sleutel(naam: str) -> str:
    return naam.casefold()


def _gewoon_woord(naam: str) -> float:
    delen = re.split(r"[\s\-']+", naam.lower())
    if len(delen) > 1:
        return 0.0  # samengestelde namen (Sint-Niklaas, La Louvière) zijn eenduidig
    return max(zipf_frequency(naam.lower(), taal) for taal in TALEN)


def _latijns(naam: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-zÀ-ÿ'’ .\-]+", naam))


def _ambigu(naam: str, inwoners: int) -> bool:
    if inwoners >= GROTE_STAD or naam.casefold() in NIET_AMBIGU:
        return False
    freq = _gewoon_woord(naam)
    if len(naam) <= 3:
        return freq >= 3.0
    return freq >= GEWONE_WOORD_DREMPEL


def maak_plaatsen(data_dir: str) -> dict:
    steden500 = json.load(open(os.path.join(data_dir, "cities500.json"), encoding="utf-8"))
    steden15000 = json.load(open(os.path.join(data_dir, "cities15000.json"), encoding="utf-8"))

    buitenland: dict[str, int] = {}
    for v in steden15000.values():
        if v["countrycode"] != "BE":
            k = _sleutel(v["name"])
            buitenland[k] = max(buitenland.get(k, 0), v["population"])

    be = [v for v in steden500.values() if v["countrycode"] == "BE"]
    bekend = {_sleutel(v["name"]) for v in be}
    for naam, gewest, inwoners in EXTRA_PLAATSEN:
        if _sleutel(naam) not in bekend:
            be.append({"name": naam, "admin1code": gewest, "population": inwoners, "alternatenames": []})
    be.sort(key=lambda v: -v["population"])
    plaatsen: list[dict] = []
    namen: dict[str, list[int]] = {}
    for v in be:
        hoofdnaam = v["name"]
        idx = len(plaatsen)
        plaatsen.append({
            "naam": WEERGAVE.get(hoofdnaam, hoofdnaam),
            "gewest": {"VLG": "Vlaanderen", "WAL": "Wallonië", "BRU": "Brussel"}.get(v["admin1code"], ""),
            "inwoners": v["population"],
        })
        varianten = {hoofdnaam, WEERGAVE.get(hoofdnaam, hoofdnaam)}
        varianten.update(EXONIEMEN_BE.get(hoofdnaam, []))
        for alt in v.get("alternatenames") or []:
            # Tweetalige namen in Brussel: "Ixelles - Elsene", "Uccle/Ukkel"
            if " - " in alt or "/" in alt:
                for deel in re.split(r"\s+-\s+|/", alt):
                    deel = deel.strip()
                    if _latijns(deel) and len(deel) >= 3 and deel[0].isupper():
                        varianten.add(deel)
        for naam in varianten:
            if not _latijns(naam) or len(naam) < 2:
                continue
            k = _sleutel(naam)
            vlag = 0
            if _ambigu(naam, v["population"]):
                vlag |= 1
            if buitenland.get(k, 0) >= max(50_000, v["population"]):
                vlag |= 2
            bestaand = namen.get(k)
            if bestaand is None or plaatsen[bestaand[0]]["inwoners"] < v["population"]:
                namen[k] = [idx, vlag]
    return {
        "bron": "GeoNames (CC BY 4.0) via geonamescache; vlag 1 = ook gewoon woord, 2 = ook buitenlandse stad",
        "plaatsen": plaatsen,
        "namen": dict(sorted(namen.items())),
    }


def _landnamen(code: str, vertalers: dict) -> set[str]:
    land = pycountry.countries.get(alpha_2=code)
    namen: set[str] = set()
    if land is not None:
        basis = [land.name, getattr(land, "common_name", None)]
        for b in filter(None, basis):
            namen.add(b)
            for t in vertalers.values():
                namen.add(t.gettext(b))
    gezuiverd = set()
    for n in namen:
        if "," in n or "(" in n:
            continue  # formele namen als "Korea, Republic of"
        gezuiverd.add(n)
    gezuiverd.update(EXTRA_LANDNAMEN.get(code, []))
    return {n for n in gezuiverd if n not in NIET_ALS_LAND or n in EXTRA_LANDNAMEN.get(code, [])}


def maak_landen(data_dir: str) -> dict:
    vertalers = {
        taal: gettext.translation("iso3166-1", pycountry.LOCALES_DIR, languages=[taal])
        for taal in ("nl", "fr", "de")
    }
    nl = vertalers["nl"]
    landen: dict[str, dict] = {}
    for land in pycountry.countries:
        code = land.alpha_2
        landen[code] = {
            "naam": nl.gettext(getattr(land, "common_name", None) or land.name).split(",")[0],
            "namen": sorted(_landnamen(code, vertalers)),
            "bijvoeglijk": BIJVOEGLIJK.get(code, []),
        }
    landen["EU"] = {"naam": "Europese Unie", "namen": sorted(EXTRA_LANDNAMEN["EU"]), "bijvoeglijk": BIJVOEGLIJK["EU"]}
    for code, naam in (("GB", "Verenigd Koninkrijk"), ("US", "Verenigde Staten"), ("KR", "Zuid-Korea"),
                       ("RU", "Rusland"), ("CZ", "Tsjechië"), ("TR", "Turkije"), ("VN", "Vietnam")):
        landen[code]["naam"] = naam

    # Steden: >= 1 miljoen inwoners wereldwijd, >= 100 000 in buurlanden; hoofdlettergevoelig herkend.
    steden15000 = json.load(open(os.path.join(data_dir, "cities15000.json"), encoding="utf-8"))
    buren = {"NL", "FR", "DE", "GB", "LU", "CH", "AT", "IT", "ES"}
    steden: dict[str, str] = {}
    for v in sorted(steden15000.values(), key=lambda v: v["population"]):
        cc = v["countrycode"]
        if cc == "BE":
            continue
        drempel = 100_000 if cc in buren else 1_000_000
        naam = v["name"]
        if v["population"] < drempel or not _latijns(naam):
            continue
        if naam in AMBIGUE_STEDEN:
            continue
        steden[naam] = cc
    for staat in json.load(open(os.path.join(data_dir, "us_states.json"), encoding="utf-8")).values():
        if staat["name"] not in {"Georgia", "Washington"}:
            steden[staat["name"]] = "US"
    for cc, lijst in STEDEN_EXTRA.items():
        for naam in lijst:
            steden[naam] = cc
    return {
        "bron": "pycountry (iso-codes), GeoNames (CC BY 4.0) via geonamescache, aangevuld met handmatige lijsten",
        "landen": landen,
        "steden": dict(sorted(steden.items())),
    }


def main() -> int:
    data_dir = os.path.join(os.path.dirname(geonamescache.__file__), "data")
    DOEL.mkdir(parents=True, exist_ok=True)
    plaatsen = maak_plaatsen(data_dir)
    landen = maak_landen(data_dir)
    (DOEL / "plaatsen_be.json").write_text(json.dumps(plaatsen, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (DOEL / "landen.json").write_text(json.dumps(landen, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(plaatsen['plaatsen'])} Belgische plaatsen, {len(plaatsen['namen'])} namen; "
          f"{len(landen['landen'])} landen, {len(landen['steden'])} steden")
    return 0


if __name__ == "__main__":
    sys.exit(main())
