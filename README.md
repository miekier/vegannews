# Vegannieuws

Een webpagina die nationaal (Belgisch) en internationaal nieuws over veganisme verzamelt, vertaalt, indeelt en met bronvermelding toont. De pagina werkt ook op een gsm. Alles draait gratis op GitHub: GitHub Actions verzamelt het nieuws drie keer per dag, en GitHub Pages toont de website.

**Website:** <https://miekier.github.io/vegannews/>

## Gebruik

1. Open de website en kies een periode: *Van* en *Tot en met*, of een snelkeuze zoals *Gisteren en vandaag* of *Afgelopen 7 dagen*.
2. Kies de regio: alles, nationaal (België) of internationaal.
3. Kies onderwerpen, of laat ze leeg voor alle onderwerpen.
4. Druk op **Geef mij het nieuws**.

Onder *Meer filters* staan:

- een zoekwoord;
- het soort gebeurtenis (opening, sluiting, nieuw product);
- het soort bron: primair, secundair of posts op Instagram en Facebook;
- de ordening: per dag, onderwerp of regio.

Elk bericht toont:

- een kernzin als kop (bv. "Vegan restaurant X opent een tweede zaak in Gent");
- de plaats, de datum, de onderwerpen en de bron;
- een link naar het oorspronkelijke bericht, plus de andere media die hetzelfde artikel brachten.

Brengen verschillende media, ook in verschillende talen, hetzelfde nieuws, dan staan hun berichten samen als één **verhaal**: een Nederlandse kop met alle bronnen eronder. Per dag opent de pagina met het verhaal dat de meeste bronnen heeft.

Een overzicht kun je kopiëren, downloaden als Markdown, of afdrukken en als PDF bewaren. De adresbalk bevat de gekozen filters; die link kun je als bladwijzer bewaren of delen.

## Bronnen beheren

Het bronnenregister bestaat uit twee bestanden:

- [`bronnen.yml`](bronnen.yml): websites, RSS-feeds, Bluesky-, Mastodon- en YouTube-accounts.
- [`zoekopdrachten.yml`](zoekopdrachten.yml): zoekopdrachten in Google Nieuws en Bing Nieuws, een PubMed-zoekopdracht voor nieuwe studies, en zoekopdrachten naar openbare Instagram- en Facebookposts.

Voor elk van 33 Europese landen volgt het register minstens één bron:

- een vegan organisatie of een vegan medium uit dat land, en/of
- een zoekopdracht in de nationale editie van Google Nieuws, in de landstaal.

Landen zonder bruikbare eigen website, zoals Bulgarije, Roemenië, Griekenland en Malta, worden enkel via Google Nieuws gevolgd.

Voor de Verenigde Staten volgt het register onder meer VegNews, Sentient Media, The Good Food Institute, Faunalytics, Mercy For Animals, PETA, Physicians Committee for Responsible Medicine, Animal Legal Defense Fund, Farm Sanctuary en Eater (enkel vegan restaurantnieuws).

### Instagram en Facebook

Instagram en Facebook bieden geen gratis toegang voor zo'n overzicht. Google Nieuws vindt wel openbare posts van zaken en organisaties. Zo werkt het:

- De zoekopdrachten `site:instagram.com vegan …` en `site:facebook.com vegan …` (Belgische edities) vinden posts.
- Elke post gaat langs het taalmodel. Enkel posts met nieuws over België blijven, zoals een opening, sluiting, nieuw product, evenement of actie. Recepten, maaltijdfoto's, wedstrijden en reclame vallen weg.
- De link loopt via news.google.com en stuurt door naar de post.

Een specifieke zaak of organisatie volgen kan met een eigen zoekopdracht, bijvoorbeeld `site:instagram.com "naam van de zaak"`.

Google vindt niet elke post. Posts van privé-accounts, stories en een deel van de reels ontbreken.

Zo voeg je een bron toe, ook op een gsm:

1. Op de website: tabblad **Bronnen** → **＋ Bron toevoegen**. Dat opent een formulier op GitHub.
2. Vul naam, adres, soort, land en taal in en dien het formulier in.
3. Binnen ongeveer een minuut test het programma de bron en antwoordt het in het issue.
   - Lukt de test: de bron staat in het register, het issue sluit en een verzamelrun start.
   - Lukt de test niet: de reden staat in het antwoord. Pas het issue aan, of heropen het om het opnieuw te proberen.

Uitschakelen of verwijderen gaat met de knop **uitschakelen of verwijderen** bij een bron, of met het formulier *Bron uitschakelen, inschakelen of verwijderen*.

Je kunt de bestanden ook rechtstreeks op GitHub bewerken (potloodicoon). Bovenaan elk bestand staat welke velden er zijn. Na het opslaan start automatisch een verzamelrun.

De pagina **Bronnen** toont per bron of ze werkt, wanneer ze laatst nieuws had en de foutmelding als ze faalt.

## Hoe het werkt

```
bronnenregister ──► ophalen (RSS, feed-ontdekking, Google/Bing Nieuws, Bluesky, Mastodon, YouTube, PubMed)
                ──► selectie (enkel vegan-gerelateerd bij algemene bronnen)
                ──► taal, onderwerp, regio en plaats via trefwoorden
                ──► ontdubbelen (zelfde URL of bijna dezelfde titel binnen 3 dagen)
                ──► archief (site/data/berichten/JJJJ-MM.json)
                ──► taalmodel: kernzin, vertaling, onderwerp, land, plaats, relevantie
                ──► verhalen: zelfde nieuws uit verschillende bronnen onder één Nederlandse kop
                ──► website (GitHub Pages)
```

- **Planning.** De workflow *Nieuws verzamelen* draait om 05:23, 11:23 en 17:23 Belgische wintertijd (zomertijd: een uur later). Je kunt hem ook zelf starten via Actions → *Nieuws verzamelen* → *Run workflow*.
- **Archief.** Elk bericht wordt bewaard, dus elke periode blijft opvraagbaar. Ouder nieuws (van vóór de start) haal je op via *Run workflow* met een getal bij *Ouder nieuws opzoeken*. Dat gebruikt Google Nieuws en is onvolledig.
- **Taalmodel.** Google Gemini of Groq, elk gratis met een eigen sleutel (zie *Eenmalige installatie*). Per run gaan maximaal 80 verzoeken van 12 berichten naar het model, en maximaal 240 per dag. Het verslag van elke run vermeldt het tokenverbruik.
  - Bij te veel berichten verwerkt een volgende run de rest.
  - Zonder sleutel, of als het taalmodel faalt, blijft de indeling op basis van trefwoorden en plaatsnamen staan. Zo'n bericht krijgt het label *ingedeeld via trefwoorden*.
  - Titels in andere talen dan Nederlands en Engels worden dan vertaald via MyMemory (gratis, ongeveer 60 titels per dag).
  - GitHub Models, het oorspronkelijke gratis taalmodel zonder sleutel, antwoordt sinds oktober 2026 niet meer.
- **Verhalen.** Berichten van de afgelopen 4 dagen worden vergeleken op gedeelde woorden in hun Nederlandse kernzin en titel (tf-idf, cosinusgelijkenis ≥ 0,2, hoogstens 3 dagen uit elkaar).
  - Gelijkaardige berichten vormen kandidaatgroepen.
  - Het taalmodel beslist welke berichten over hetzelfde nieuwsfeit gaan en schrijft een Nederlandse kop.
  - Een bericht blijft bij zijn verhaal; latere berichten kunnen aansluiten.
  - Hoogstens 4 verzoeken per run; instellingen onder `verhalen_` in [`instellingen.yml`](instellingen.yml).
- **Websites zonder feed.** Een website zonder bruikbare RSS-feed wordt automatisch gevolgd via Google Nieuws (`site:domein`). De pagina *Bronnen* vermeldt dat bij de bron.
- **Nationaal of internationaal.** De regio volgt uit de vermelde plaatsen en de vermelde instellingen en gewesten, en uit het land van de bron.
  - Plaatsen: 2 276 Belgische plaatsen in het Nederlands, Frans en Duits.
  - Plaatsnamen die ook gewone woorden zijn (Boom, Geel, Spa, Soy) tellen enkel na een voorzetsel ("in Geel").

## Kwaliteit en traceerbaarheid

- Elk bericht bewaart:
  - de originele URL en de bron;
  - de publicatiedatum en het moment van ophalen;
  - de originele titel en tekst als die vertaald werden;
  - de gebruikte methode (taalmodel of trefwoorden).
- Primaire bronnen (organisatie, bedrijf, persoon, onderzoekers zelf) worden onderscheiden van secundaire (media, zoekresultaten).
- Elke run schrijft een verslag:
  - in Actions, onder de run;
  - op de website, in het tabblad *Info*.
- De git-geschiedenis bewaart elke wijziging aan het register, de trefwoorden en het archief.
- [`tests/`](tests) bevat geautomatiseerde tests; ze draaien bij elke codewijziging (workflow *Tests*).

## Instellingen

[`instellingen.yml`](instellingen.yml) bevat onder meer:

- de doeltaal (Nederlands of Engels);
- de maximale leeftijd van berichten;
- de limieten voor het taalmodel.

[`categorieen.yml`](categorieen.yml) bevat de 20 onderwerpen en hun trefwoorden in vier talen. Na een wijziging kun je het archief opnieuw laten indelen: *Run workflow* → *Onderwerpen opnieuw bepalen*.

## Eenmalige installatie

1. **Settings → Pages → Build and deployment → Source:** kies **GitHub Actions**.
2. **Gratis sleutel voor het taalmodel** (aanbevolen, ongeveer 2 minuten):
   1. Ga naar <https://aistudio.google.com/apikey>, meld je aan met een Google-account en klik op **Create API key**. Kopieer de sleutel.
   2. In deze repository: **Settings → Secrets and variables → Actions → New repository secret**.
   3. Vul bij *Name* `GEMINI_API_KEY` in, plak de sleutel bij *Secret* en klik op **Add secret**.

   Alternatief: een gratis sleutel van Groq (<https://console.groq.com/keys>) als secret `GROQ_API_KEY`. Zijn beide ingesteld, dan is Groq de reserve.
3. **Actions:** start *Nieuws verzamelen* met *Run workflow*. Vul bij *Ouder nieuws opzoeken* bijvoorbeeld `30` in om meteen een archief van een maand te hebben.
4. Controle: *Run workflow* met *Enkel alle bronnen testen* toont per bron het resultaat en of het taalmodel werkt.

GitHub schakelt geplande workflows uit na 60 dagen zonder activiteit in de repository. De verzamelruns zelf zijn activiteit. Mocht GitHub de planning toch uitschakelen, dan krijg je een e-mail; *Enable workflow* in Actions zet ze weer aan.

## Zelf draaien op een pc

Dit is enkel nodig als je niet met GitHub Actions wilt werken.

```bash
pip install -r requirements.txt
set PYTHONPATH=src            # Linux/macOS: export PYTHONPATH=src
python -m vegannieuws verzamel
python -m http.server -d site 8000   # open http://localhost:8000
```

Voor het taalmodel zet je de sleutel in de omgevingsvariabele `GEMINI_API_KEY` of `GROQ_API_KEY`. `python -m vegannieuws controleer` test alle bronnen en het taalmodel zonder iets op te slaan.

## Beperkingen

- Instagram en Facebook worden enkel gevolgd via de posts die Google Nieuws vindt (zie hoger). X en TikTok worden niet gevolgd.
  - Restaurants die enkel daar posten, verschijnen enkel als media erover schrijven (via de zoekopdrachten).
  - Volg ze ook via Bluesky, Mastodon, YouTube of hun website als ze daar actief zijn.
- Websites zonder RSS-feed kunnen niet rechtstreeks gevolgd worden.
- Links uit Google Nieuws lopen via news.google.com en sturen door naar het artikel.
- Vertalingen, kernzinnen en indeling zijn automatisch. Controleer belangrijke informatie altijd in de bron.

## Structuur

| Pad | Inhoud |
|---|---|
| `bronnen.yml`, `zoekopdrachten.yml` | bronnenregister |
| `categorieen.yml` | onderwerpen, trefwoorden, relevantie en gebeurtenissen |
| `instellingen.yml` | instellingen |
| `src/vegannieuws/` | Python-programma (ophalen, indelen, ontdubbelen, taalmodel, archief) |
| `src/vegannieuws/data/` | lijsten van Belgische plaatsen, landen en steden |
| `scripts/maak_geodata.py` | maakt die lijsten opnieuw aan |
| `site/` | website; `site/data/` bevat het archief |
| `staat/` | toestand tussen runs (gevonden feeds, status per bron, dagbudgetten) |
| `.github/` | workflows en formulieren |

## Gegevens en licenties

- Plaatsnamen: [GeoNames](https://www.geonames.org) (CC BY 4.0), via geonamescache.
- Landnamen: iso-codes via pycountry.
- Nieuwsberichten blijven eigendom van de oorspronkelijke bronnen. Het overzicht toont enkel titels, korte samenvattingen en links.
