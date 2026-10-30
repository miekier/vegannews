"use strict";

(() => {
  const TIJDZONE = "Europe/Brussels";
  const TAALNAMEN = {
    fr: "het Frans", de: "het Duits", es: "het Spaans", it: "het Italiaans", pt: "het Portugees", en: "het Engels",
    nl: "het Nederlands", pl: "het Pools", cs: "het Tsjechisch", sk: "het Slowaaks", sl: "het Sloveens",
    hr: "het Kroatisch", sr: "het Servisch", hu: "het Hongaars", ro: "het Roemeens", bg: "het Bulgaars",
    el: "het Grieks", sv: "het Zweeds", da: "het Deens", no: "het Noors", fi: "het Fins", is: "het IJslands",
    et: "het Estisch", lv: "het Lets", lt: "het Litouws", uk: "het Oekraïens", ru: "het Russisch", tr: "het Turks",
    mt: "het Maltees",
  };
  const PER_KEER = 150;
  const toestand = { index: null, maanden: new Map(), bronnen: null, resultaat: [], eenheden: [], filters: null, limiet: PER_KEER, gezocht: false, beheer: false };

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  function el(tag, attrs, ...kinderen) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v === true ? "" : v);
    }
    for (const kind of kinderen.flat()) {
      if (kind === null || kind === undefined || kind === false) continue;
      node.append(kind instanceof Node ? kind : document.createTextNode(String(kind)));
    }
    return node;
  }

  const veiligeUrl = (url) => (typeof url === "string" && /^https?:\/\//i.test(url) ? url : null);

  // --- datums ---------------------------------------------------------------------------
  const isoFmt = new Intl.DateTimeFormat("en-CA", { timeZone: TIJDZONE, year: "numeric", month: "2-digit", day: "2-digit" });
  const vandaag = () => isoFmt.format(new Date());
  function plusDagen(iso, n) {
    const d = new Date(`${iso}T12:00:00Z`);
    d.setUTCDate(d.getUTCDate() + n);
    return d.toISOString().slice(0, 10);
  }
  const fmtDag = new Intl.DateTimeFormat("nl-BE", { weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
  const fmtKort = new Intl.DateTimeFormat("nl-BE", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
  const fmtMoment = new Intl.DateTimeFormat("nl-BE", { dateStyle: "medium", timeStyle: "short", timeZone: TIJDZONE });
  const dagTekst = (iso) => fmtDag.format(new Date(`${iso}T12:00:00Z`));
  const kortTekst = (iso) => fmtKort.format(new Date(`${iso}T12:00:00Z`));
  const momentTekst = (iso) => (iso ? fmtMoment.format(new Date(iso)) : "–");

  function maandenTussen(van, tot) {
    const uit = [];
    let [j, m] = van.slice(0, 7).split("-").map(Number);
    const [jt, mt] = tot.slice(0, 7).split("-").map(Number);
    while (j < jt || (j === jt && m <= mt)) {
      uit.push(`${j}-${String(m).padStart(2, "0")}`);
      m += 1;
      if (m > 12) { m = 1; j += 1; }
    }
    return uit;
  }

  function snelPeriode(soort) {
    const v = vandaag();
    const maandBegin = `${v.slice(0, 7)}-01`;
    switch (soort) {
      case "vandaag": return [v, v];
      case "gisteren": return [plusDagen(v, -1), plusDagen(v, -1)];
      case "2d": return [plusDagen(v, -1), v];
      case "7d": return [plusDagen(v, -6), v];
      case "30d": return [plusDagen(v, -29), v];
      case "maand": return [maandBegin, v];
      case "vorigemaand": {
        const einde = plusDagen(maandBegin, -1);
        return [`${einde.slice(0, 7)}-01`, einde];
      }
      default: return [plusDagen(v, -1), v];
    }
  }

  // --- opslag ---------------------------------------------------------------------------
  function bewaar(sleutel, waarde) { try { localStorage.setItem(sleutel, JSON.stringify(waarde)); } catch (e) { /* privévenster */ } }
  function lees(sleutel) { try { return JSON.parse(localStorage.getItem(sleutel)); } catch (e) { return null; } }

  async function haalJSON(pad) {
    const antwoord = await fetch(pad, { cache: "no-cache" });
    if (!antwoord.ok) throw new Error(`${pad}: HTTP ${antwoord.status}`);
    return antwoord.json();
  }

  function laadMaand(maand) {
    if (!toestand.maanden.has(maand)) {
      toestand.maanden.set(maand, haalJSON(`data/berichten/${maand}.json`)
        .then((d) => d.berichten || [])
        .catch(() => { toestand.maanden.delete(maand); return []; }));
    }
    return toestand.maanden.get(maand);
  }

  // --- hulpfuncties voor teksten -----------------------------------------------------------
  const normaliseer = (s) => (s || "").normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const categorieNaam = (code) => (toestand.index?.categorieen || []).find((c) => c.code === code)?.naam || code;
  const gebeurtenisNaam = (code) => (toestand.index?.gebeurtenissen || []).find((g) => g.code === code)?.naam || code;
  const landNaam = (code) => (code === "EU" ? "Europese Unie" : toestand.index?.landen?.[code] || code);

  function bronTekst(b) {
    if (b.sociaal) return `${b.sociaal} (via Google Nieuws)`;
    const zoek = b.brontype === "zoekopdracht";
    const dienst = zoek ? (b.bron_naam || "").split(":")[0] : "";
    if (b.uitgever) return zoek ? `${b.uitgever} (via ${dienst})` : `${b.uitgever} (${b.bron_naam})`;
    return b.bron_naam || "onbekende bron";
  }

  const bronNaam = (b) => b.sociaal ? `${b.sociaal}-post` : (b.uitgever || b.bron_naam || "onbekende bron");
  // Een kop eindigt niet op een punt.
  const alsKop = (s) => (s || "").trim().replace(/([^.!?…])\.$/, "$1");
  const woorden = (s) => new Set(normaliseer(s).split(/[^a-z0-9]+/).filter((w) => w.length > 2));
  function lijktOp(a, b) {
    const x = woorden(a), y = woorden(b);
    if (!x.size || !y.size) return false;
    let gedeeld = 0;
    for (const w of x) if (y.has(w)) gedeeld += 1;
    return gedeeld / Math.min(x.size, y.size) >= 0.6;
  }
  const hoofdletter = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);
  const moment = (b) => b.datum + (b.gepubliceerd || b.opgehaald || "");

  function plaatsTekst(b) {
    if (b.regio === "BE") return [b.plaats, b.plaats ? null : "België"].filter(Boolean).join(", ");
    const land = b.land ? landNaam(b.land) : "";
    return [b.plaats, land].filter(Boolean).join(", ") || "Internationaal";
  }

  // --- filters ----------------------------------------------------------------------------
  function leesFilters() {
    let van = $("#van").value;
    let tot = $("#tot").value;
    if (van && tot && van > tot) [van, tot] = [tot, van];
    return {
      van, tot,
      regio: document.querySelector('input[name="regio"]:checked')?.value || "",
      cat: $$("#onderwerpen .chip[aria-pressed='true']").map((c) => c.dataset.code),
      q: $("#zoek").value.trim(),
      gebeurtenis: $("#gebeurtenis").value,
      relatie: $("#relatie").value,
      groep: $("#groep").value,
      irrelevant: $("#ook-irrelevant").checked,
    };
  }

  function zetFilters(f) {
    $("#van").value = f.van || "";
    $("#tot").value = f.tot || "";
    for (const radio of $$('input[name="regio"]')) radio.checked = radio.value === (f.regio || "");
    for (const chip of $$("#onderwerpen .chip")) chip.setAttribute("aria-pressed", String((f.cat || []).includes(chip.dataset.code)));
    $("#zoek").value = f.q || "";
    $("#gebeurtenis").value = f.gebeurtenis || "";
    $("#relatie").value = f.relatie || "";
    $("#groep").value = f.groep || "dag";
    $("#ook-irrelevant").checked = Boolean(f.irrelevant);
    markeerSnelkeuze();
    werkOnderwerpSamenvattingBij();
  }

  function naarHash(f) {
    const p = new URLSearchParams();
    p.set("van", f.van);
    p.set("tot", f.tot);
    if (f.regio) p.set("regio", f.regio);
    if (f.cat.length) p.set("onderwerp", f.cat.join(","));
    if (f.q) p.set("zoek", f.q);
    if (f.gebeurtenis) p.set("gebeurtenis", f.gebeurtenis);
    if (f.relatie) p.set("bron", f.relatie);
    if (f.groep && f.groep !== "dag") p.set("groep", f.groep);
    if (f.irrelevant) p.set("alles", "1");
    history.replaceState(null, "", `#${p.toString()}`);
  }

  function vanHash() {
    const p = new URLSearchParams(location.hash.slice(1));
    if (!p.get("van") || !p.get("tot")) return null;
    return {
      van: p.get("van"), tot: p.get("tot"), regio: p.get("regio") || "",
      cat: (p.get("onderwerp") || "").split(",").filter(Boolean), q: p.get("zoek") || "",
      gebeurtenis: p.get("gebeurtenis") || "", relatie: p.get("bron") || "", groep: p.get("groep") || "dag",
      irrelevant: p.get("alles") === "1",
    };
  }

  function werkOnderwerpSamenvattingBij() {
    const gekozen = $$("#onderwerpen .chip[aria-pressed='true']").map((c) => categorieNaam(c.dataset.code));
    $("#onderwerp-samenvatting").textContent = gekozen.length ? gekozen.join(", ") : "alle onderwerpen";
  }

  function markeerSnelkeuze() {
    const van = $("#van").value;
    const tot = $("#tot").value;
    for (const knop of $$("#snelkeuze button")) {
      const [v, t] = snelPeriode(knop.dataset.snel);
      knop.classList.toggle("actief", v === van && t === tot);
    }
  }

  function voldoetBasis(b, f) {
    if (f.regio === "BE" && b.regio !== "BE") return false;
    if (f.regio === "INT" && b.regio === "BE") return false;
    if (!f.irrelevant && b.relevant === false) return false;
    if (f.gebeurtenis && b.gebeurtenis !== f.gebeurtenis) return false;
    if (f.relatie === "sociaal" && !b.sociaal) return false;
    if (f.relatie && f.relatie !== "sociaal" && (b.relatie || "secundair") !== f.relatie) return false;
    if (f.q) {
      const hooiberg = normaliseer([b.verhaal_kop, b.kernzin, b.titel, b.titel_orig, b.samenvatting, b.samenvatting_orig,
        b.plaats, b.uitgever, b.bron_naam, b.sociaal, ...(b.extra || []).map((e) => e.naam)].join(" "));
      if (!normaliseer(f.q).split(/\s+/).every((w) => hooiberg.includes(w))) return false;
    }
    return true;
  }

  // --- zoeken en tonen --------------------------------------------------------------------------
  async function zoek() {
    if (!toestand.index) return;
    const f = leesFilters();
    if (!f.van || !f.tot) return;
    toestand.filters = f;
    toestand.limiet = PER_KEER;
    naarHash(f);
    bewaar("vegannieuws-filters", { ...f, van: undefined, tot: undefined, snel: huidigeSnelkeuze() });
    const doel = $("#resultaat");
    doel.replaceChildren(el("p", { class: "melding", text: "Nieuws ophalen…" }));
    const maanden = maandenTussen(f.van, f.tot).filter((m) => toestand.index.maanden?.[m]);
    const lijsten = await Promise.all(maanden.map(laadMaand));
    const inPeriode = lijsten.flat().filter((b) => b.datum >= f.van && b.datum <= f.tot);
    const basis = inPeriode.filter((b) => voldoetBasis(b, f));
    werkTellersBij(basis);
    toestand.resultaat = basis
      .filter((b) => !f.cat.length || (b.categorieen || []).some((c) => f.cat.includes(c)))
      .sort((a, b) => moment(b).localeCompare(moment(a)));
    toestand.eenheden = eenheden(toestand.resultaat);
    toestand.gezocht = true;
    toon();
  }

  function huidigeSnelkeuze() {
    return $$("#snelkeuze button.actief").map((k) => k.dataset.snel)[0] || null;
  }

  function werkTellersBij(berichten) {
    const tellers = {};
    for (const b of berichten) for (const c of b.categorieen || []) tellers[c] = (tellers[c] || 0) + 1;
    for (const chip of $$("#onderwerpen .chip")) {
      chip.querySelector(".aantal").textContent = tellers[chip.dataset.code] ? ` ${tellers[chip.dataset.code]}` : " 0";
    }
  }

  // Een eenheid is een los bericht of een verhaal: berichten van verschillende bronnen over hetzelfde nieuws.
  function eenheden(berichten) {
    const verhalen = new Map();
    for (const b of berichten) {
      if (!b.verhaal) continue;
      if (!verhalen.has(b.verhaal)) verhalen.set(b.verhaal, []);
      verhalen.get(b.verhaal).push(b);
    }
    const uit = [];
    const gezien = new Set();
    for (const b of berichten) {
      const leden = b.verhaal ? verhalen.get(b.verhaal) : null;
      if (!leden || leden.length < 2) { uit.push({ soort: "bericht", b, leden: [b], bronnen: 1 + (b.extra || []).length }); continue; }
      if (gezien.has(b.verhaal)) continue;
      gezien.add(b.verhaal);
      const geordend = [...leden].sort((x, y) => (x.relatie === "primair" ? 0 : 1) - (y.relatie === "primair" ? 0 : 1)
        || moment(x).localeCompare(moment(y)));
      // De kop van het recentste bericht is de meest recente versie van de kop.
      const recentste = [...leden].sort((x, y) => moment(y).localeCompare(moment(x)))[0];
      uit.push({
        soort: "verhaal", b: geordend[0], leden: geordend, kop: recentste.verhaal_kop || geordend[0].kernzin || geordend[0].titel,
        bronnen: leden.reduce((n, x) => n + 1 + (x.extra || []).length, 0),
      });
    }
    return uit;
  }

  const datumVan = (e) => e.leden.reduce((m, b) => (b.datum > m ? b.datum : m), "");
  const momentVan = (e) => e.leden.reduce((m, b) => (moment(b) > m ? moment(b) : m), "");

  function hoofdcategorie(e) {
    const tellers = {};
    for (const b of e.leden) { const c = (b.categorieen || [])[0] || "overig"; tellers[c] = (tellers[c] || 0) + 1; }
    return Object.entries(tellers).sort((a, b) => b[1] - a[1])[0][0];
  }

  function groepeer(lijst, groep) {
    const groepen = new Map();
    const voegToe = (sleutel, titel, e) => {
      if (!groepen.has(sleutel)) groepen.set(sleutel, { titel, eenheden: [] });
      groepen.get(sleutel).eenheden.push(e);
    };
    for (const e of lijst) {
      if (groep === "dag") voegToe(datumVan(e), dagTekst(datumVan(e)), e);
      else if (groep === "onderwerp") {
        const code = hoofdcategorie(e);
        voegToe(code, categorieNaam(code), e);
      } else if (groep === "regio") {
        const be = e.b.regio === "BE";
        voegToe(be ? "1" : "2", be ? "België" : "Internationaal", e);
      } else voegToe("alles", "", e);
    }
    let uit = Array.from(groepen.entries());
    if (groep === "dag") uit.sort((a, b) => b[0].localeCompare(a[0]));
    else if (groep === "onderwerp") {
      const volgorde = (toestand.index.categorieen || []).map((c) => c.code);
      uit.sort((a, b) => volgorde.indexOf(a[0]) - volgorde.indexOf(b[0]));
    } else if (groep === "regio") uit.sort((a, b) => a[0].localeCompare(b[0]));
    return uit.map(([, g]) => {
      g.eenheden.sort((a, b) => momentVan(b).localeCompare(momentVan(a)));
      if (groep !== "geen") {
        // Opening: het verhaal met de meeste bronnen, anders het recentste bericht.
        const opening = g.eenheden.reduce((best, e) => (e.bronnen > best.bronnen ? e : best), g.eenheden[0]);
        g.eenheden = [opening, ...g.eenheden.filter((e) => e !== opening)];
      }
      return g;
    });
  }

  function periodeTekst(f) {
    return f.van === f.tot ? dagTekst(f.van) : `${kortTekst(f.van)} – ${kortTekst(f.tot)}`;
  }

  function filterTekst(f) {
    const delen = [periodeTekst(f)];
    delen.push(f.regio === "BE" ? "België" : f.regio === "INT" ? "internationaal" : "België en internationaal");
    if (f.cat.length) delen.push(f.cat.map(categorieNaam).join(", "));
    if (f.gebeurtenis) delen.push(gebeurtenisNaam(f.gebeurtenis));
    if (f.relatie === "sociaal") delen.push("posts op sociale media");
    if (f.q) delen.push(`“${f.q}”`);
    return delen.join(" · ");
  }

  function toon() {
    const f = toestand.filters;
    const doel = $("#resultaat");
    const res = toestand.resultaat;
    if (!res.length) {
      const nogNiets = !Object.keys(toestand.index.maanden || {}).length;
      doel.replaceChildren(el("p", { class: "leeg", text: nogNiets
        ? "Er zijn nog geen berichten verzameld. Na de eerste verzamelrun verschijnt hier het nieuws."
        : `Geen berichten gevonden voor ${filterTekst(f)}. Kies een langere periode of minder filters.` }));
      return;
    }
    const lijst = toestand.eenheden;
    const verhalen = lijst.filter((e) => e.soort === "verhaal").length;
    const balk = el("div", { class: "samenvatting-balk" },
      el("p", {}, el("strong", {}, `${res.length} ${res.length === 1 ? "bericht" : "berichten"}`),
        verhalen ? ` · ${verhalen} ${verhalen === 1 ? "verhaal" : "verhalen"} met meerdere bronnen` : "", ` · ${filterTekst(f)}`),
      el("div", { class: "acties" },
        el("button", { type: "button", onclick: kopieer }, "Kopieer"),
        el("button", { type: "button", onclick: download }, "Download (.md)"),
        el("button", { type: "button", onclick: () => window.print() }, "Afdrukken / PDF")));
    const fragment = document.createDocumentFragment();
    fragment.append(balk);
    let getoond = 0;
    for (const groep of groepeer(lijst, f.groep)) {
      if (getoond >= toestand.limiet) break;
      const sectie = el("section", { class: "groep" });
      const aantal = groep.eenheden.reduce((n, e) => n + e.leden.length, 0);
      if (groep.titel) sectie.append(el("h2", {}, el("span", {}, groep.titel), el("span", { class: "aantal" }, `${aantal} ${aantal === 1 ? "bericht" : "berichten"}`)));
      const artikelen = el("div", { class: "artikelen" });
      groep.eenheden.forEach((e, i) => {
        if (getoond >= toestand.limiet) return;
        const node = e.soort === "verhaal" ? verhaalKaart(e) : kaart(e.b);
        if (i === 0 && groep.eenheden.length > 1) node.classList.add("opening");
        artikelen.append(node);
        getoond += 1;
      });
      sectie.append(artikelen);
      fragment.append(sectie);
    }
    if (getoond < lijst.length) {
      fragment.append(el("button", { type: "button", class: "link meer-tonen", onclick: () => { toestand.limiet += PER_KEER; toon(); } },
        `Toon meer (${lijst.length - getoond} resterend)`));
    }
    doel.replaceChildren(fragment);
  }

  function extLink(url, tekst, cls) {
    const veilig = veiligeUrl(url);
    return veilig ? el("a", { href: veilig, target: "_blank", rel: "noopener noreferrer", class: cls || null }, tekst) : null;
  }

  function kickerVan(leden, extra) {
    const k = [];
    const gebeurtenis = leden.map((b) => b.gebeurtenis).find(Boolean);
    if (gebeurtenis) k.push(el("span", { class: `gebeurtenis ${gebeurtenis}` }, gebeurtenisNaam(gebeurtenis)));
    const tellers = {};
    for (const b of leden) for (const c of b.categorieen || []) tellers[c] = (tellers[c] || 0) + 1;
    for (const [c] of Object.entries(tellers).sort((a, b) => b[1] - a[1]).slice(0, 2)) k.push(el("span", {}, categorieNaam(c)));
    k.push(el("span", { class: "plaats" }, plaatsTekst(leden[0])));
    return [...k, ...extra];
  }

  function kaart(b) {
    const node = $("#tpl-bericht").content.firstElementChild.cloneNode(true);
    if (b.relevant === false) node.classList.add("irrelevant");
    const extra = [];
    if (b.sociaal) extra.push(el("span", { class: "sociaal" }, `${b.sociaal}-post`));
    if (b.kandidaat) extra.push(el("span", { class: "twijfel" }, "nog niet beoordeeld"));
    else if (b.relevant === false) extra.push(el("span", { class: "twijfel" }, "mogelijk niet relevant"));
    node.querySelector(".kicker").append(...kickerVan([b], extra));

    const kop = node.querySelector(".kop-artikel");
    const kopTekst = alsKop(b.kernzin || b.titel);
    kop.append(extLink(b.url, kopTekst) || kopTekst);

    const inleiding = node.querySelector(".inleiding");
    if (b.samenvatting && !lijktOp(b.samenvatting, kopTekst)) inleiding.append(b.samenvatting);
    if (b.kernzin && b.titel && !lijktOp(b.titel, b.kernzin) && !(b.samenvatting && lijktOp(b.titel, b.samenvatting))) {
      inleiding.append(el("span", { class: "orig" }, b.titel));
    }
    if (!inleiding.childNodes.length) inleiding.remove();

    const meta = [el("strong", {}, bronNaam(b)), ` · ${kortTekst(b.datum)}`];
    if (b.relatie === "primair") meta.push(" · primaire bron");
    if (b.vertaald && b.taal) meta.push(` · vertaald uit ${TAALNAMEN[b.taal] || b.taal}`);
    if (b.methode !== "llm") meta.push(" · ingedeeld via trefwoorden");
    node.querySelector(".bronregel").append(...meta);

    const links = node.querySelector(".links");
    links.append(extLink(b.url, b.sociaal ? `Bekijk de post op ${b.sociaal} ↗` : `Lees bij ${bronNaam(b)} ↗`));
    const andere = (b.extra || []).filter((e) => veiligeUrl(e.url));
    if (andere.length) {
      links.append(el("details", {},
        el("summary", {}, `+${andere.length} ${andere.length === 1 ? "andere bron" : "andere bronnen"}`),
        el("ul", { class: "bronnenlijst" }, andere.map((e) => el("li", {}, extLink(e.url, e.naam || e.url))))));
    }
    if (b.titel_orig || b.samenvatting_orig) {
      links.append(el("details", {},
        el("summary", {}, "Originele tekst"),
        el("p", {}, b.titel_orig || b.titel),
        b.samenvatting_orig ? el("p", { class: "gedempt" }, b.samenvatting_orig) : null));
    }
    return node;
  }

  function verhaalKaart(e) {
    const node = $("#tpl-bericht").content.firstElementChild.cloneNode(true);
    node.classList.add("verhaal");
    const talen = new Set(e.leden.map((b) => b.taal).filter(Boolean));
    node.querySelector(".kicker").append(...kickerVan(e.leden, [el("span", { class: "sociaal" }, `${e.bronnen} bronnen`)]));
    node.querySelector(".kop-artikel").textContent = alsKop(e.kop);
    const inleiding = node.querySelector(".inleiding");
    if (e.b.kernzin && !lijktOp(e.b.kernzin, e.kop)) inleiding.textContent = e.b.kernzin;
    else if (e.b.samenvatting) inleiding.textContent = e.b.samenvatting;
    else inleiding.remove();

    const lijst = el("ul", { class: "bronnenlijst" });
    const ZICHTBAAR = 5;
    let rest = null;
    e.leden.forEach((b, i) => {
      if (i === ZICHTBAAR && e.leden.length > ZICHTBAAR + 1) {
        rest = el("ul", { class: "bronnenlijst rest" });
        lijst.after(rest);
      }
      const meta = [kortTekst(b.datum), b.taal ? hoofdletter((TAALNAMEN[b.taal] || b.taal).replace(/^het /, "")) : null,
        b.relatie === "primair" ? "primaire bron" : null].filter(Boolean).join(" · ");
      (rest || lijst).append(el("li", {},
        el("span", { class: "naam" }, bronNaam(b)), el("span", { class: "meta" }, ` · ${meta}`),
        extLink(b.url, b.titel || b.kernzin),
        (b.extra || []).length ? el("span", { class: "meer-bronnen" }, "ook bij: ",
          ...(b.extra || []).filter((x) => veiligeUrl(x.url)).flatMap((x, j) => [j ? ", " : "", extLink(x.url, x.naam || "bron")])) : null));
    });
    const bronregel = node.querySelector(".bronregel");
    bronregel.replaceWith(lijst);
    if (rest) {
      const uitklap = el("details", { class: "alle-bronnen" }, el("summary", {}, `Alle ${e.leden.length} bronnen tonen`));
      lijst.after(uitklap);
      uitklap.append(rest);
    }
    node.querySelector(".links").append(el("span", { class: "gedempt" },
      `${e.leden.length} berichten${talen.size > 1 ? ` in ${talen.size} talen` : ""} · kop en indeling automatisch gemaakt`));
    return node;
  }

  // --- export ----------------------------------------------------------------------------------
  function alsTekst() {
    const f = toestand.filters;
    const regels = [`# Vegannieuws: ${filterTekst(f)}`, "", `${toestand.resultaat.length} berichten. Bron: ${location.href}`, ""];
    for (const groep of groepeer(toestand.eenheden, f.groep)) {
      if (groep.titel) regels.push(`## ${groep.titel}`, "");
      for (const e of groep.eenheden) {
        if (e.soort === "verhaal") {
          regels.push(`- **${e.kop}** (${plaatsTekst(e.b)})`);
          for (const b of e.leden) {
            regels.push(`  - ${bronNaam(b)}, ${kortTekst(b.datum)}: ${b.titel || b.kernzin} — ${b.url}`);
            for (const x of b.extra || []) regels.push(`    - ook: ${x.naam}: ${x.url}`);
          }
          continue;
        }
        const b = e.b;
        regels.push(`- **${b.kernzin || b.titel}** (${plaatsTekst(b)}, ${kortTekst(b.datum)}) — ${bronTekst(b)}: ${b.url}`);
        for (const x of b.extra || []) regels.push(`  - ook: ${x.naam}: ${x.url}`);
      }
      regels.push("");
    }
    return regels.join("\n");
  }

  async function kopieer(ev) {
    const knop = ev.currentTarget;
    try {
      await navigator.clipboard.writeText(alsTekst());
      knop.textContent = "Gekopieerd ✓";
    } catch (e) {
      knop.textContent = "Kopiëren lukt niet in deze browser";
    }
    setTimeout(() => { knop.textContent = "Kopieer"; }, 2500);
  }

  function download() {
    const f = toestand.filters;
    const blob = new Blob([alsTekst()], { type: "text/markdown;charset=utf-8" });
    const a = el("a", { href: URL.createObjectURL(blob), download: `vegannieuws_${f.van}_${f.tot}.md` });
    document.body.append(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  }

  // --- bronnen -----------------------------------------------------------------------------------
  function githubLinks() {
    const repo = toestand.index?.repo;
    if (!repo) return null;
    const basis = `https://github.com/${repo}`;
    return {
      toevoegen: `${basis}/issues/new?template=bron-toevoegen.yml`,
      wijzigen: (naam) => `${basis}/issues/new?template=bron-wijzigen.yml&title=${encodeURIComponent(`Bron wijzigen: ${naam || ""}`)}&bron=${encodeURIComponent(naam || "")}`,
      register: `${basis}/edit/main/bronnen.yml`,
      zoekopdrachten: `${basis}/edit/main/zoekopdrachten.yml`,
      categorieen: `${basis}/edit/main/categorieen.yml`,
      instellingen: `${basis}/edit/main/instellingen.yml`,
      bijwerken: `${basis}/actions/workflows/verzamel.yml`,
      inloggen: `https://github.com/login?return_to=${encodeURIComponent(`/${repo}/issues`)}`,
      repo: basis,
    };
  }

  // Beheer: de knoppen verschijnen pas na "Inloggen als beheerder". De eigenlijke toegangscontrole
  // gebeurt op GitHub: enkel het account van de eigenaar kan het register wijzigen.
  function zetBeheer(aan) {
    toestand.beheer = aan;
    bewaar("vegannieuws-beheer", aan);
    $("#beheer-uit").hidden = aan;
    $("#beheer-in").hidden = !aan;
    $("#info-knoppen").hidden = !aan;
    $("#info-beheer-uit").hidden = aan;
    if (toestand.bronnen) toonBronnen();
  }

  function knop(href, tekst) {
    return el("a", { href, target: "_blank", rel: "noopener noreferrer" }, tekst);
  }

  async function toonBronnen() {
    const lijst = $("#bronnen-lijst");
    if (!toestand.bronnen) {
      lijst.replaceChildren(el("p", { class: "melding", text: "Bronnen laden…" }));
      try {
        toestand.bronnen = await haalJSON("data/bronnen.json");
      } catch (e) {
        lijst.replaceChildren(el("p", { class: "melding fout", text: "Het bronnenoverzicht is nog niet beschikbaar (na de eerste verzamelrun)." }));
        return;
      }
    }
    const links = githubLinks();
    if (links && !$("#bronnen-knoppen").children.length) {
      $("#bronnen-knoppen").append(
        knop(links.inloggen, "Inloggen bij GitHub ↗"),
        knop(links.toevoegen, "＋ Bron toevoegen"),
        knop(links.wijzigen(""), "Bron uitschakelen of verwijderen"),
        knop(links.register, "Register bewerken"),
        knop(links.zoekopdrachten, "Zoekopdrachten bewerken"));
    }
    const bronnen = toestand.bronnen.bronnen || [];
    const actief = bronnen.filter((b) => b.actief);
    const fout = actief.filter((b) => b.status === "fout");
    $("#bronnen-samenvatting").textContent =
      `${bronnen.length} bronnen in het register: ${actief.length - fout.length} werken, ${fout.length} met een fout, ${bronnen.length - actief.length} uitgeschakeld.`;
    const zoekterm = normaliseer($("#bronnen-zoek").value);
    const volgorde = { fout: 0, leeg: 1, ok: 2, ongewijzigd: 2 };
    const gefilterd = bronnen
      .filter((b) => !zoekterm || normaliseer([b.naam, b.url, b.zoekterm, b.land, b.taal, b.type_naam, b.soort_naam].join(" ")).includes(zoekterm))
      .sort((a, b) => (a.actief === b.actief ? 0 : a.actief ? -1 : 1)
        || (volgorde[a.status] ?? 3) - (volgorde[b.status] ?? 3)
        || a.naam.localeCompare(b.naam, "nl"));
    const fragment = document.createDocumentFragment();
    if ((toestand.bronnen.waarschuwingen || []).length) {
      fragment.append(el("div", { class: "waarschuwingen kaart" }, el("strong", {}, "Waarschuwingen in het register"),
        el("ul", {}, toestand.bronnen.waarschuwingen.map((w) => el("li", {}, w)))));
    }
    for (const b of gefilterd) fragment.append(bronKaart(b, links));
    lijst.replaceChildren(fragment);
  }

  function bronKaart(b, links) {
    const statusInfo = !b.actief ? ["uit", "uitgeschakeld"]
      : b.status === "fout" ? ["fout", "fout"]
        : b.status === "leeg" ? ["leeg", "leeg"]
          : b.status ? ["ok", "werkt"] : ["onbekend", "nog niet opgehaald"];
    const adres = veiligeUrl(b.url) || (b.soort === "google" ? `https://news.google.com/search?q=${encodeURIComponent(b.zoekterm)}` : null);
    const eigenschappen = [b.soort_naam, b.type_naam, b.land, b.taal, b.alleen_vegan ? "enkel vegan-gerelateerd" : "alle berichten"].filter(Boolean);
    const cijfers = [];
    if (b.laatst_nieuw) cijfers.push(`laatst nieuw: ${momentTekst(b.laatst_nieuw)}`);
    if (b.totaal !== undefined) cijfers.push(`${b.totaal} berichten bewaard`);
    if (b.gecontroleerd) cijfers.push(`gecontroleerd: ${momentTekst(b.gecontroleerd)}`);
    return el("div", { class: "bron" },
      el("div", { class: "bron-kop" },
        adres ? el("a", { href: adres, target: "_blank", rel: "noopener noreferrer" }, el("strong", {}, b.naam)) : el("strong", {}, b.naam),
        el("span", { class: `status ${statusInfo[0]}` }, statusInfo[1])),
      el("p", {}, eigenschappen.join(" · ")),
      b.zoekterm ? el("p", {}, `Zoekterm: ${b.zoekterm}${b.editie ? ` (editie ${b.editie})` : ""}`) : null,
      cijfers.length ? el("p", {}, cijfers.join(" · ")) : null,
      b.status === "fout" && b.melding ? el("p", { class: "melding-fout" }, `Melding: ${b.melding}${b.fouten_op_rij > 1 ? ` (${b.fouten_op_rij} keer na elkaar)` : ""}`) : null,
      b.status !== "fout" && b.melding ? el("p", {}, `Info: ${b.melding}`) : null,
      b.notitie ? el("p", {}, b.notitie) : null,
      el("div", { class: "bron-acties" },
        b.feed && veiligeUrl(b.feed) ? el("a", { href: b.feed, target: "_blank", rel: "noopener noreferrer" }, "feed") : null,
        links && toestand.beheer ? el("a", { href: links.wijzigen(b.naam), target: "_blank", rel: "noopener noreferrer" },
          b.actief ? "uitschakelen of verwijderen" : "opnieuw inschakelen") : null));
  }

  // --- info ---------------------------------------------------------------------------------------
  function toonInfo() {
    const run = toestand.index?.laatste_run;
    const doel = $("#run-info");
    if (run) {
      const llm = run.llm || {};
      const regels = [
        `Gestart: ${momentTekst(run.start)} (duur ${Math.round(run.duur_s || 0)} s)`,
        `Bronnen: ${run.bronnen_actief} actief, ${run.bronnen_ok} gelukt, ${run.bronnen_fout} met een fout`,
        `Berichten: ${run.opgehaald} opgehaald, ${run.behouden} relevant, ${run.nieuw} nieuw`,
      ];
      if (llm.verzoeken !== undefined) {
        regels.push(`Taalmodel${llm.model ? ` (${llm.model})` : ""}: ${llm.verrijkt || 0} berichten verwerkt, nog ${llm.achterstand || 0} in de wachtrij${llm.melding ? `. ${llm.melding}` : ""}`);
      }
      const vh = run.verhalen || {};
      if (vh.groepen !== undefined) {
        regels.push(`Verhalen: ${vh.groepen || 0} kandidaatgroepen gecontroleerd, ${vh.nieuwe_verhalen || 0} nieuwe verhalen${vh.melding ? `. ${vh.melding}` : ""}`);
      }
      if (run.reservevertaling?.vertaald !== undefined) regels.push(`Reservevertaling: ${run.reservevertaling.vertaald} titels`);
      const totaal = Object.values(toestand.index.maanden || {}).reduce((a, b) => a + b, 0);
      regels.push(`Archief: ${totaal} berichten sinds ${Object.keys(toestand.index.maanden || {})[0] || "–"}`);
      doel.replaceChildren(el("ul", {}, regels.map((r) => el("li", {}, r))));
    }
    const links = githubLinks();
    if (links && !$("#info-knoppen").children.length) {
      $("#info-knoppen").append(
        knop(links.bijwerken, "Nu bijwerken (Actions → Run workflow)"),
        knop(links.categorieen, "Onderwerpen en trefwoorden"),
        knop(links.instellingen, "Instellingen"),
        knop(links.repo, "Broncode en geschiedenis"));
    }
  }

  // --- start -----------------------------------------------------------------------------------------
  function kiesTab(naam) {
    for (const tab of $$(".tab")) tab.setAttribute("aria-selected", String(tab.dataset.tab === naam));
    for (const paneel of $$(".paneel")) paneel.hidden = paneel.id !== `paneel-${naam}`;
    if (naam === "bronnen") toonBronnen();
    if (naam === "info") toonInfo();
  }

  function bouwFilters() {
    const chips = $("#onderwerpen");
    chips.replaceChildren(...(toestand.index.categorieen || []).map((c) =>
      el("button", { type: "button", class: "chip", "data-code": c.code, "aria-pressed": "false", title: c.omschrijving },
        c.naam, el("span", { class: "aantal" }))));
    const select = $("#gebeurtenis");
    for (const g of toestand.index.gebeurtenissen || []) select.append(el("option", { value: g.code }, `Enkel: ${g.naam}`));
  }

  function opnieuwAlsGezocht() {
    if (toestand.gezocht) zoek();
  }

  function koppelGebeurtenissen() {
    for (const tab of $$(".tab")) tab.addEventListener("click", () => kiesTab(tab.dataset.tab));
    $("#filters").addEventListener("submit", async (ev) => {
      ev.preventDefault();
      await zoek();
      if (window.matchMedia("(max-width: 999px)").matches) $("#resultaat").scrollIntoView({ behavior: "smooth", block: "start" });
    });
    $("#snelkeuze").addEventListener("click", (ev) => {
      const knopje = ev.target.closest("button[data-snel]");
      if (!knopje) return;
      const [van, tot] = snelPeriode(knopje.dataset.snel);
      $("#van").value = van;
      $("#tot").value = tot;
      markeerSnelkeuze();
      zoek();
    });
    for (const id of ["#van", "#tot"]) $(id).addEventListener("change", markeerSnelkeuze);
    $("#onderwerpen").addEventListener("click", (ev) => {
      const chip = ev.target.closest(".chip");
      if (!chip) return;
      chip.setAttribute("aria-pressed", String(chip.getAttribute("aria-pressed") !== "true"));
      werkOnderwerpSamenvattingBij();
      opnieuwAlsGezocht();
    });
    $("#alle-onderwerpen").addEventListener("click", () => {
      for (const chip of $$("#onderwerpen .chip")) chip.setAttribute("aria-pressed", "false");
      werkOnderwerpSamenvattingBij();
      opnieuwAlsGezocht();
    });
    for (const radio of $$('input[name="regio"]')) radio.addEventListener("change", opnieuwAlsGezocht);
    for (const id of ["#gebeurtenis", "#relatie", "#groep", "#ook-irrelevant"]) $(id).addEventListener("change", opnieuwAlsGezocht);
    $("#bronnen-zoek").addEventListener("input", () => toonBronnen());
    $("#beheer-aan").addEventListener("click", () => zetBeheer(true));
    $("#beheer-af").addEventListener("click", () => zetBeheer(false));
  }

  async function start() {
    $("#datumregel").textContent = hoofdletter(dagTekst(vandaag()));
    koppelGebeurtenissen();
    zetBeheer(Boolean(lees("vegannieuws-beheer")));
    try {
      toestand.index = await haalJSON("data/index.json");
    } catch (e) {
      $("#bijgewerkt").textContent = "Nog geen gegevens";
      $("#resultaat").replaceChildren(el("p", { class: "leeg", text: "Er zijn nog geen berichten verzameld. Na de eerste verzamelrun verschijnt hier het nieuws." }));
      return;
    }
    $("#bijgewerkt").textContent = `Bijgewerkt ${momentTekst(toestand.index.bijgewerkt)}`;
    bouwFilters();
    if (window.matchMedia("(min-width: 1000px)").matches) $("#onderwerpen-blok").open = true;
    const uitHash = vanHash();
    const bewaard = lees("vegannieuws-filters") || {};
    if (uitHash) zetFilters(uitHash);
    else {
      const [van, tot] = snelPeriode(bewaard.snel || "2d");
      zetFilters({ ...bewaard, van, tot });
    }
    zoek();
  }

  start();
})();
