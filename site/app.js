"use strict";

(() => {
  const TIJDZONE = "Europe/Brussels";
  const TAALNAMEN = { fr: "het Frans", de: "het Duits", es: "het Spaans", it: "het Italiaans", pt: "het Portugees", en: "het Engels", nl: "het Nederlands" };
  const PER_KEER = 300;
  const toestand = { index: null, maanden: new Map(), bronnen: null, resultaat: [], filters: null, limiet: PER_KEER, gezocht: false };

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
    const zoek = b.brontype === "zoekopdracht";
    const dienst = zoek ? (b.bron_naam || "").split(":")[0] : "";
    if (b.uitgever) return zoek ? `${b.uitgever} (via ${dienst})` : `${b.uitgever} (${b.bron_naam})`;
    return b.bron_naam || "onbekende bron";
  }

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
    if (f.relatie && (b.relatie || "secundair") !== f.relatie) return false;
    if (f.q) {
      const hooiberg = normaliseer([b.kernzin, b.titel, b.titel_orig, b.samenvatting, b.samenvatting_orig, b.plaats,
        b.uitgever, b.bron_naam, ...(b.extra || []).map((e) => e.naam)].join(" "));
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
      .sort((a, b) => (b.datum + (b.gepubliceerd || b.opgehaald || "")).localeCompare(a.datum + (a.gepubliceerd || a.opgehaald || "")));
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

  function groepeer(berichten, groep) {
    const groepen = new Map();
    const voegToe = (sleutel, titel, b) => {
      if (!groepen.has(sleutel)) groepen.set(sleutel, { titel, berichten: [] });
      groepen.get(sleutel).berichten.push(b);
    };
    for (const b of berichten) {
      if (groep === "dag") voegToe(b.datum, dagTekst(b.datum), b);
      else if (groep === "onderwerp") {
        const code = (b.categorieen || [])[0] || "overig";
        voegToe(code, categorieNaam(code), b);
      } else if (groep === "regio") voegToe(b.regio === "BE" ? "1" : "2", b.regio === "BE" ? "Nationaal (België)" : "Internationaal", b);
      else voegToe("alles", "", b);
    }
    let lijst = Array.from(groepen.entries());
    if (groep === "onderwerp") {
      const volgorde = (toestand.index.categorieen || []).map((c) => c.code);
      lijst.sort((a, b) => volgorde.indexOf(a[0]) - volgorde.indexOf(b[0]));
    } else if (groep === "regio") lijst.sort((a, b) => a[0].localeCompare(b[0]));
    return lijst.map(([, g]) => g);
  }

  function periodeTekst(f) {
    return f.van === f.tot ? dagTekst(f.van) : `${kortTekst(f.van)} – ${kortTekst(f.tot)}`;
  }

  function filterTekst(f) {
    const delen = [periodeTekst(f)];
    delen.push(f.regio === "BE" ? "nationaal (België)" : f.regio === "INT" ? "internationaal" : "nationaal en internationaal");
    if (f.cat.length) delen.push(f.cat.map(categorieNaam).join(", "));
    if (f.gebeurtenis) delen.push(gebeurtenisNaam(f.gebeurtenis));
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
    const balk = el("div", { class: "samenvatting-balk" },
      el("p", {}, `${res.length} ${res.length === 1 ? "bericht" : "berichten"} · ${filterTekst(f)}`),
      el("div", { class: "knoppen" },
        el("button", { type: "button", onclick: kopieer }, "Kopieer"),
        el("button", { type: "button", onclick: download }, "Download (.md)"),
        el("button", { type: "button", onclick: () => window.print() }, "Afdrukken / PDF")));
    const fragment = document.createDocumentFragment();
    fragment.append(balk);
    let getoond = 0;
    for (const groep of groepeer(res, f.groep)) {
      if (getoond >= toestand.limiet) break;
      const sectie = el("section", { class: "groep" });
      if (groep.titel) sectie.append(el("h2", {}, el("span", {}, groep.titel), el("span", { class: "aantal" }, String(groep.berichten.length))));
      for (const b of groep.berichten) {
        if (getoond >= toestand.limiet) break;
        sectie.append(kaart(b));
        getoond += 1;
      }
      fragment.append(sectie);
    }
    if (getoond < res.length) {
      fragment.append(el("button", { type: "button", class: "link meer-tonen", onclick: () => { toestand.limiet += PER_KEER; toon(); } },
        `Toon meer (${res.length - getoond} resterend)`));
    }
    doel.replaceChildren(fragment);
  }

  function kaart(b) {
    const node = $("#tpl-bericht").content.firstElementChild.cloneNode(true);
    if (b.relevant === false) node.classList.add("irrelevant");
    const labels = node.querySelector(".labels");
    if (b.gebeurtenis) labels.append(el("span", { class: `label ${b.gebeurtenis}` }, gebeurtenisNaam(b.gebeurtenis)));
    labels.append(el("span", { class: "label plaats" }, `📍 ${plaatsTekst(b)}`));
    for (const c of b.categorieen || []) labels.append(el("span", { class: "label" }, categorieNaam(c)));
    if (b.relevant === false) labels.append(el("span", { class: "label" }, "mogelijk niet relevant"));

    node.querySelector(".kern").textContent = b.kernzin || b.titel;
    const titel = node.querySelector(".titel-orig");
    if (b.kernzin && b.titel && b.kernzin !== b.titel) titel.textContent = b.titel;
    else titel.remove();
    const samenvatting = node.querySelector(".samenvatting");
    if (b.samenvatting) samenvatting.textContent = b.samenvatting;
    else samenvatting.remove();

    const meta = [kortTekst(b.datum), bronTekst(b)];
    if (b.relatie === "primair") meta.push("primaire bron");
    if (b.vertaald && b.taal) meta.push(`vertaald uit ${TAALNAMEN[b.taal] || b.taal}`);
    if (b.methode !== "llm") meta.push("ingedeeld via trefwoorden");
    node.querySelector(".meta").textContent = meta.join(" · ");

    const links = node.querySelector(".links");
    const url = veiligeUrl(b.url);
    if (url) links.append(el("a", { href: url, target: "_blank", rel: "noopener noreferrer" }, `Lees bij de bron ↗`));
    const extra = (b.extra || []).filter((e) => veiligeUrl(e.url));
    if (extra.length) {
      links.append(el("details", {},
        el("summary", {}, `+${extra.length} ${extra.length === 1 ? "andere bron" : "andere bronnen"}`),
        el("ul", {}, extra.map((e) => el("li", {}, el("a", { href: e.url, target: "_blank", rel: "noopener noreferrer" }, e.naam || e.url))))));
    }
    if (b.titel_orig || b.samenvatting_orig) {
      links.append(el("details", {},
        el("summary", {}, "Originele tekst"),
        el("p", {}, b.titel_orig || b.titel),
        b.samenvatting_orig ? el("p", { class: "gedempt" }, b.samenvatting_orig) : null));
    }
    return node;
  }

  // --- export ----------------------------------------------------------------------------------
  function alsTekst() {
    const f = toestand.filters;
    const regels = [`# Vegannieuws: ${filterTekst(f)}`, "", `${toestand.resultaat.length} berichten. Bron: ${location.href}`, ""];
    for (const groep of groepeer(toestand.resultaat, f.groep)) {
      if (groep.titel) regels.push(`## ${groep.titel}`, "");
      for (const b of groep.berichten) {
        const delen = [`- **${b.kernzin || b.titel}**`];
        delen.push(` (${plaatsTekst(b)}, ${kortTekst(b.datum)})`);
        delen.push(` — ${bronTekst(b)}: ${b.url}`);
        regels.push(delen.join(""));
        for (const e of b.extra || []) regels.push(`  - ook: ${e.naam}: ${e.url}`);
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
      repo: basis,
    };
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
      links ? el("div", { class: "bron-acties" },
        b.feed && veiligeUrl(b.feed) ? el("a", { href: b.feed, target: "_blank", rel: "noopener noreferrer" }, "feed") : null,
        el("a", { href: links.wijzigen(b.naam), target: "_blank", rel: "noopener noreferrer" }, b.actief ? "uitschakelen of verwijderen" : "opnieuw inschakelen")) : null);
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
      if (window.matchMedia("(max-width: 700px)").matches) $("#resultaat").scrollIntoView({ behavior: "smooth", block: "start" });
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
  }

  async function start() {
    koppelGebeurtenissen();
    try {
      toestand.index = await haalJSON("data/index.json");
    } catch (e) {
      $("#bijgewerkt").textContent = "Nog geen gegevens";
      $("#resultaat").replaceChildren(el("p", { class: "leeg", text: "Er zijn nog geen berichten verzameld. Na de eerste verzamelrun verschijnt hier het nieuws." }));
      return;
    }
    $("#bijgewerkt").textContent = `Bijgewerkt: ${momentTekst(toestand.index.bijgewerkt)}`;
    bouwFilters();
    if (window.matchMedia("(min-width: 701px)").matches) $("#onderwerpen-blok").open = true;
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
