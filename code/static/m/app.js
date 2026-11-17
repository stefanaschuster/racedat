// Racedat – Handy-Ansicht (/m). Vanilla JS, kein Build-Schritt.
// Lesen über /m/api/*, schreiben über die bestehenden Formular-Endpunkte.
(() => {
  "use strict";

  const view = document.getElementById("view");
  const topEl = document.getElementById("top");
  const backBtn = document.getElementById("back");
  const titleEl = document.getElementById("top-title");
  const rightEl = document.getElementById("top-right");
  const tabs = document.getElementById("tabs");
  const sheetWrap = document.getElementById("sheet-wrap");
  const sheet = document.getElementById("sheet");
  const toasts = document.getElementById("toasts");

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const MAX_MB = 50;

  let me = null;            // eingeloggter Nutzer oder null
  let lapsCache = null;     // Liste aller Runden
  const store = {
    get(k, d) { try { return JSON.parse(sessionStorage.getItem("rd_" + k)) ?? d; } catch { return d; } },
    set(k, v) { try { sessionStorage.setItem("rd_" + k, JSON.stringify(v)); } catch { /* egal */ } },
  };

  // ---------------------------------------------------------------- Netz

  async function api(path) {
    const res = await fetch(path, { credentials: "same-origin", headers: { Accept: "application/json" } });
    let data = {};
    try { data = await res.json(); } catch { /* keine JSON-Antwort */ }
    if (!res.ok) throw new Error(data.error || `Fehler ${res.status}`);
    return data;
  }

  // Bestehende Formular-Endpunkte: Antwort ist ein Redirect. fetch folgt ihm;
  // das Ziel verrät Erfolg (…?saved=…) oder Fehler (…?error=…).
  async function submit(url, body) {
    const res = await fetch(url, { method: "POST", body, credentials: "same-origin", redirect: "follow" });
    const final = new URL(res.url || url, location.href);
    const error = final.searchParams.get("error");
    if (error) throw new Error(error);
    if (!res.ok) {
      let t = "";
      try { t = (await res.text()).slice(0, 200); } catch { /* egal */ }
      throw new Error(t || `Fehler ${res.status}`);
    }
    return final;
  }

  function form(obj) {
    const p = new URLSearchParams();
    Object.entries(obj).forEach(([k, v]) => p.append(k, v ?? ""));
    return p;
  }

  async function loadMe() {
    try { me = (await api("/m/api/me")).user; } catch { me = null; }
    return me;
  }

  async function loadLaps(force = false) {
    if (!lapsCache || force) lapsCache = (await api("/m/api/laps")).laps;
    return lapsCache;
  }

  // ---------------------------------------------------------------- UI-Helfer

  function toast(text, bad = false) {
    const el = document.createElement("div");
    el.className = "toast" + (bad ? " bad" : "");
    el.textContent = text;
    toasts.append(el);
    setTimeout(() => el.remove(), bad ? 6000 : 3000);
  }

  async function busy(btn, fn) {
    const old = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spin"></span>';
    try { return await fn(); } finally { btn.disabled = false; btn.innerHTML = old; }
  }

  function setTop({ title = "", back = false, right = "" } = {}) {
    titleEl.textContent = title;
    backBtn.hidden = !back;
    topEl.classList.toggle("sub", back);
    rightEl.innerHTML = right;
  }

  function setTab(name) {
    tabs.querySelectorAll("a").forEach((a) => a.classList.toggle("active", a.dataset.tab === name));
  }

  function loading() { view.innerHTML = '<div class="empty"><span class="spin"></span></div>'; }

  function openSheet(html) {
    sheet.innerHTML = html;
    sheetWrap.hidden = false;
    return sheet;
  }
  function closeSheet() { sheetWrap.hidden = true; sheet.innerHTML = ""; }
  document.getElementById("sheet-bg").addEventListener("click", closeSheet);

  backBtn.addEventListener("click", () => {
    if (history.length > 1) history.back(); else location.hash = "#/runden";
  });

  const fmtDate = (d) => {
    if (!d) return "";
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(d);
    return m ? `${m[3]}.${m[2]}.${m[1]}` : d;
  };
  const medal = (r) => (r ? `<span class="medal m${r}">${r}</span>` : "");

  function lapCard(l, opts = {}) {
    const sub = [l.driver || l.owner, l.bike].filter(Boolean).join(" · ");
    return `<button class="lap${l.mine ? " mine" : ""}${opts.sel ? " sel" : ""}" type="button" data-lap="${l.lap_id}">
      <span class="t">${medal(l.medal)}${esc(l.time)}<small>${esc(fmtDate(l.date) || "—")}</small></span>
      <span class="l1">${esc(l.track || "Ohne Strecke")}</span>
      <span class="l2">${esc(sub || "—")}</span></button>`;
  }

  function needLogin(next) {
    view.innerHTML = `<div class="empty"><b>Anmelden</b>Dafür brauchst du ein Konto.</div>
      <div class="btns"><a class="btn primary" href="#/login?next=${encodeURIComponent(next)}">Anmelden</a>
      <a class="btn" href="#/registrieren">Konto anlegen</a></div>`;
  }

  // ---------------------------------------------------------------- Runde: Aktionen

  async function lapSheet(lapId) {
    const laps = await loadLaps();
    const l = laps.find((x) => x.lap_id === lapId);
    if (!l) { toast("Runde nicht gefunden", true); return; }
    const s = openSheet(`
      <div class="row"><div class="grow"><div class="sheet-time">${medal(l.medal)}${esc(l.time)}</div>
        <div class="muted">${esc(l.track || "Ohne Strecke")}</div></div></div>
      <dl class="kv">
        <dt>Fahrer</dt><dd>${l.user_id != null ? `<a href="#/fahrer/${l.user_id}" data-close>${esc(l.driver || l.owner || "—")}</a>` : esc(l.driver || "—")}</dd>
        <dt>Motorrad</dt><dd>${esc(l.bike || "—")}</dd>
        <dt>Datum</dt><dd>${esc(fmtDate(l.date) || "—")}</dd>
        <dt>Runde</dt><dd>#${esc(l.lap_number ?? "?")}</dd>
        <dt>Kanäle</dt><dd>${l.total_roles ? `${l.roles} von ${l.total_roles} zugeordnet` : "—"}</dd>
        ${l.notes ? `<dt>Notizen</dt><dd>${esc(l.notes)}</dd>` : ""}
      </dl>
      <div class="btns">
        <a class="btn primary" href="#/ansicht/datenviewer?lap=${l.lap_id}" data-close>Datenviewer</a>
        <a class="btn" href="#/ansicht/coach?lap=${l.lap_id}" data-close>AI-Coach</a>
        <div class="btns two">
          <button class="btn" type="button" data-slot="a">Als A vergleichen</button>
          <button class="btn" type="button" data-slot="b">Als B vergleichen</button>
        </div>
        ${l.can_edit ? `<div class="btns two">
          <button class="btn" type="button" data-act="edit">Bearbeiten</button>
          <button class="btn danger" type="button" data-act="delete">Löschen</button></div>` : ""}
      </div>`);
    s.querySelectorAll("[data-close]").forEach((a) => a.addEventListener("click", closeSheet));
    s.querySelectorAll("[data-slot]").forEach((b) => b.addEventListener("click", () => {
      const slots = store.get("cmp", {});
      slots[b.dataset.slot] = l.lap_id;
      store.set("cmp", slots);
      closeSheet();
      location.hash = "#/vergleich";
    }));
    const edit = s.querySelector('[data-act="edit"]');
    if (edit) edit.addEventListener("click", () => editSheet(l));
    const del = s.querySelector('[data-act="delete"]');
    if (del) del.addEventListener("click", async () => {
      if (!confirm(`Runde ${l.time} (${l.track || "ohne Strecke"}) unwiderruflich löschen?`)) return;
      try {
        await busy(del, () => submit(`/laps/${l.lap_id}/delete`, form({})));
        closeSheet();
        toast("Runde gelöscht");
        await loadLaps(true);
        route();
      } catch (ex) { toast(ex.message, true); }
    });
  }

  function editSheet(l) {
    const s = openSheet(`<h2>Runde bearbeiten</h2>
      ${l.session_laps > 1 ? `<p class="muted small">Änderung gilt für alle ${l.session_laps} Runden dieser Session.</p>` : ""}
      <form class="stack" id="edit-form">
        <label class="f"><span>Fahrer</span><input type="text" name="driver" value="${esc(l.driver)}"></label>
        <label class="f"><span>Motorrad</span><input type="text" name="bike" value="${esc(l.bike)}"></label>
        <label class="f"><span>Strecke</span><input type="text" name="track" value="${esc(l.track)}"></label>
        <label class="f"><span>Datum</span><input type="date" name="session_date" value="${esc(l.date)}"></label>
        <label class="f"><span>Notizen</span><textarea name="notes">${esc(l.notes)}</textarea></label>
        <div class="btns two"><button class="btn ghost" type="button" data-cancel>Abbrechen</button>
          <button class="btn primary">Speichern</button></div>
      </form>`);
    s.querySelector("[data-cancel]").addEventListener("click", closeSheet);
    const f = s.querySelector("#edit-form");
    f.addEventListener("submit", async (e) => {
      e.preventDefault();
      const btn = f.querySelector(".primary");
      try {
        await busy(btn, async () => {
          const res = await fetch(`/sessions/${encodeURIComponent(l.session_id)}/edit`, {
            method: "POST", body: new URLSearchParams(new FormData(f)), credentials: "same-origin" });
          let data = {};
          try { data = await res.json(); } catch { /* egal */ }
          if (!res.ok || data.ok === false) throw new Error(data.error || `Fehler ${res.status}`);
        });
        closeSheet();
        toast("Gespeichert");
        await loadLaps(true);
        route();
      } catch (ex) { toast(ex.message, true); }
    });
  }

  // ---------------------------------------------------------------- Ansicht: Runden

  async function renderRunden(params) {
    const pick = params.get("pick");   // "a" oder "b": Auswahl für den Vergleich
    setTab(pick ? "vergleich" : "runden");
    setTop(pick ? { title: `Runde für ${pick.toUpperCase()} wählen`, back: true } : { title: "" });
    loading();
    const laps = await loadLaps(params.get("reload") === "1");
    const st = store.get("filter", { who: "alle", track: "", q: "", sort: "zeit" });
    if (pick && st.who === "meine" && !me) st.who = "alle";
    const tracks = [...new Set(laps.map((l) => l.track).filter(Boolean))].sort((a, b) => a.localeCompare(b, "de"));
    const slots = store.get("cmp", {});
    let pickTrack = "";
    if (pick) {
      const other = laps.find((l) => l.lap_id === slots[pick === "a" ? "b" : "a"]);
      if (other && other.track && !st.track) pickTrack = other.track;
    }

    view.innerHTML = `
      ${pick ? "" : "<h1>Runden</h1>"}
      ${pick && pickTrack ? `<div class="banner small">Gleiche Strecke wie die andere Runde ist vorausgewählt.</div>` : ""}
      ${me ? `<div class="seg" id="who"><button type="button" data-who="alle">Alle</button><button type="button" data-who="meine">Meine</button></div>` : ""}
      <div class="filters">
        <input type="search" id="q" placeholder="Suchen: Fahrer, Motorrad, Notiz" value="${esc(st.q)}" enterkeyhint="search">
        <select id="track" aria-label="Strecke"><option value="">Alle Strecken</option>
          ${tracks.map((t) => `<option${t === (st.track || pickTrack) ? " selected" : ""}>${esc(t)}</option>`).join("")}</select>
      </div>
      <div class="row"><div class="count grow" id="count"></div>
        <div class="seg" id="sort" style="width:150px"><button type="button" data-sort="zeit">Zeit</button><button type="button" data-sort="datum">Datum</button></div></div>
      <div class="laps" id="list"></div>`;

    const list = view.querySelector("#list");
    const draw = () => {
      const q = st.q.trim().toLowerCase();
      const tr = view.querySelector("#track").value;
      let rows = laps.filter((l) =>
        (st.who !== "meine" || l.mine) &&
        (!tr || l.track === tr) &&
        (!q || [l.driver, l.bike, l.track, l.notes, l.owner].join(" ").toLowerCase().includes(q)));
      rows = rows.slice().sort(st.sort === "datum"
        ? (a, b) => (b.date || "").localeCompare(a.date || "") || a.duration_s - b.duration_s
        : (a, b) => a.duration_s - b.duration_s);
      view.querySelector("#count").textContent = `${rows.length} ${rows.length === 1 ? "Runde" : "Runden"}`;
      list.innerHTML = rows.length ? rows.slice(0, 300).map((l) => lapCard(l, { sel: pick && slots[pick] === l.lap_id })).join("")
        : `<div class="empty"><b>Keine Runden</b>${laps.length ? "Filter anpassen." : "Noch nichts hochgeladen."}</div>`;
      view.querySelectorAll("#who button").forEach((b) => b.classList.toggle("on", b.dataset.who === st.who));
      view.querySelectorAll("#sort button").forEach((b) => b.classList.toggle("on", b.dataset.sort === st.sort));
    };
    const save = () => { st.track = view.querySelector("#track").value; store.set("filter", st); };
    view.querySelectorAll("#who button").forEach((b) => b.addEventListener("click", () => { st.who = b.dataset.who; save(); draw(); }));
    view.querySelectorAll("#sort button").forEach((b) => b.addEventListener("click", () => { st.sort = b.dataset.sort; save(); draw(); }));
    view.querySelector("#q").addEventListener("input", (e) => { st.q = e.target.value; save(); draw(); });
    view.querySelector("#track").addEventListener("change", () => { save(); draw(); });
    list.addEventListener("click", (e) => {
      const b = e.target.closest("[data-lap]");
      if (!b) return;
      const id = Number(b.dataset.lap);
      if (pick) {
        slots[pick] = id;
        store.set("cmp", slots);
        history.back();
      } else lapSheet(id);
    });
    draw();
  }

  // ---------------------------------------------------------------- Ansicht: Vergleich

  async function renderVergleich() {
    setTab("vergleich");
    setTop({ title: "" });
    loading();
    const laps = await loadLaps();
    const slots = store.get("cmp", {});
    const get = (k) => laps.find((l) => l.lap_id === slots[k]);
    const a = get("a"), b = get("b");
    const slot = (k, l) => `<button class="slot ${k}" type="button" data-pick="${k}">
      <span class="tag">${k.toUpperCase()}</span>
      ${l ? `<span><span class="t">${esc(l.time)}</span><br><span class="muted small">${esc([l.track, l.driver || l.owner, l.bike].filter(Boolean).join(" · "))}</span></span>`
          : `<span class="ph">Runde wählen</span>`}
      <span class="muted">›</span></button>`;
    const diffTrack = a && b && a.track && b.track && a.track.toLowerCase() !== b.track.toLowerCase();
    view.innerHTML = `<h1>Vergleich</h1>
      <p class="lede">Zwei Runden übereinanderlegen: Zeitdifferenz, Geschwindigkeit und Ideallinie auf der Strecke.</p>
      <div class="stack">${slot("a", a)}
        <div class="swap"><button class="btn sm ghost" type="button" id="swap">⇅ Tauschen</button></div>
        ${slot("b", b)}</div>
      ${diffTrack ? `<div class="flash bad" style="margin-top:12px">Die Runden sind auf verschiedenen Strecken – der Vergleich ist dann wenig aussagekräftig.</div>` : ""}
      <div class="btns" style="margin-top:16px">
        <a class="btn primary" id="go" ${a && b ? `href="#/ansicht/vergleich?a=${a.lap_id}&b=${b.lap_id}"` : 'aria-disabled="true"'}>Vergleichen</a>
        ${a || b ? `<button class="btn ghost" type="button" id="clear">Auswahl leeren</button>` : ""}
      </div>`;
    if (!(a && b)) view.querySelector("#go").addEventListener("click", (e) => { e.preventDefault(); toast("Bitte zwei Runden wählen"); });
    view.querySelectorAll("[data-pick]").forEach((btn) => btn.addEventListener("click", () => {
      location.hash = `#/runden?pick=${btn.dataset.pick}`;
    }));
    view.querySelector("#swap").addEventListener("click", () => { store.set("cmp", { a: slots.b, b: slots.a }); renderVergleich(); });
    const clear = view.querySelector("#clear");
    if (clear) clear.addEventListener("click", () => { store.set("cmp", {}); renderVergleich(); });
  }

  // ---------------------------------------------------------------- Ansicht: Diagramme im Rahmen

  function renderFrame(kind, params) {
    let src = "", title = "";
    if (kind === "datenviewer") { src = `/analyze?lap_id=${Number(params.get("lap"))}&go=1`; title = "Datenviewer"; }
    else if (kind === "coach") { src = `/coach?lap_id=${Number(params.get("lap"))}`; title = "AI-Coach"; }
    else if (kind === "vergleich") { src = `/compare?a=${Number(params.get("a"))}&b=${Number(params.get("b"))}`; title = "Vergleich"; }
    else { location.hash = "#/runden"; return; }
    document.body.classList.add("frame");
    setTop({ title, back: true, right: `<span class="rot-hint">Querformat: mehr Details</span>` });
    view.innerHTML = `<div class="frame-wrap"><div class="frame-load"><span class="spin"></span></div>
      <iframe title="${esc(title)}" src="${esc(src)}"></iframe></div>`;
    const fr = view.querySelector("iframe");
    fr.addEventListener("load", () => {
      view.querySelector(".frame-load")?.remove();
      try {
        const d = fr.contentDocument;
        // Desktop-Navigation ausblenden; die Handy-Ansicht hat ihre eigene
        const st = d.createElement("style");
        st.textContent = ".rd-header{display:none!important}";
        d.head.append(st);
        // Links aus dem Rahmen heraus (z. B. auf Desktop-Seiten) im ganzen Fenster öffnen
        d.addEventListener("click", (e) => {
          const a = e.target.closest && e.target.closest("a[href]");
          if (!a) return;
          const u = new URL(a.getAttribute("href"), d.location.href);
          if (u.origin === location.origin && /^\/(sessions|records|profile|login|admin)/.test(u.pathname)) {
            e.preventDefault();
            location.href = "/m";
          }
        });
      } catch { /* andere Herkunft: nichts anpassen */ }
    });
  }

  // ---------------------------------------------------------------- Ansicht: Hochladen

  async function renderHochladen() {
    setTab("hochladen");
    setTop({ title: "" });
    if (!me) return needLogin("#/hochladen");
    const pending = store.get("pending", null);
    if (pending) return renderPicker(pending);
    let prof = { bikes: [] };
    try { prof = await api("/m/api/profile"); } catch { /* egal */ }
    const laps = await loadLaps().catch(() => []);
    const tracks = [...new Set(laps.map((l) => l.track).filter(Boolean))].sort((a, b) => a.localeCompare(b, "de"));
    const curBike = (prof.bikes.find((b) => b.is_current) || {}).name || "";
    view.innerHTML = `<h1>Session hochladen</h1>
      <p class="lede">Schritt 1 von 2: Datei wählen. Danach wählst du die Runde aus, die gespeichert wird.</p>
      <form class="stack" id="up" novalidate>
        <label class="file-pick" id="pick"><b>Datei wählen</b>
          <span class="muted small">.SES · .LD · .XRK · .XRZ · .CSV · .DAT · .ZIP – max. ${MAX_MB} MB</span>
          <input type="file" name="file" accept=".ses,.ld,.xrk,.xrz,.csv,.dat,.zip,.SES,.LD,.XRK,.XRZ,.CSV,.DAT,.ZIP"></label>
        <label class="f"><span>Fahrer${prof.driver_name ? "<em>aus Profil</em>" : ""}</span>
          <input type="text" name="driver" value="${esc(prof.driver_name || "")}" autocomplete="off"></label>
        <label class="f"><span>Motorrad${curBike ? "<em>aus Profil</em>" : ""}</span>
          <input type="text" name="bike" value="${esc(curBike)}" list="bikes" autocomplete="off"></label>
        <datalist id="bikes">${prof.bikes.map((b) => `<option value="${esc(b.name)}">`).join("")}</datalist>
        <label class="f"><span>Strecke</span><input type="text" name="track" list="tracks" placeholder="leer = aus der Datei" autocomplete="off"></label>
        <datalist id="tracks">${tracks.map((t) => `<option value="${esc(t)}">`).join("")}</datalist>
        <label class="f"><span>Datum</span><input type="date" name="session_date"></label>
        <label class="f"><span>Notizen</span><textarea name="notes" placeholder="Setup, Wetter, Reifen …"></textarea></label>
        <div class="progress" id="prog" hidden><i></i></div>
        <button class="btn primary" id="go">Weiter zur Rundenauswahl</button>
      </form>`;
    const f = view.querySelector("#up");
    const fileIn = f.querySelector('input[type="file"]');
    fileIn.addEventListener("change", () => {
      const file = fileIn.files[0];
      const pick = view.querySelector("#pick");
      pick.classList.toggle("has", !!file);
      pick.querySelector("b").textContent = file ? file.name : "Datei wählen";
      pick.querySelector("span").textContent = file ? `${(file.size / 1048576).toFixed(1)} MB – antippen zum Ändern` : "";
    });
    f.addEventListener("submit", (e) => {
      e.preventDefault();
      const file = fileIn.files[0];
      if (!file) { toast("Bitte eine Datei wählen", true); return; }
      if (file.size > MAX_MB * 1048576) { toast(`Datei zu groß (max. ${MAX_MB} MB)`, true); return; }
      const q = new URLSearchParams({ name: file.name });
      ["driver", "bike", "track", "session_date", "notes"].forEach((k) => q.set(k, f.elements[k].value.trim()));
      const btn = view.querySelector("#go");
      const prog = view.querySelector("#prog");
      const bar = prog.querySelector("i");
      btn.disabled = true;
      btn.innerHTML = '<span class="spin"></span> Wird hochgeladen …';
      prog.hidden = false;
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/m/api/upload?" + q.toString());
      xhr.upload.onprogress = (ev) => {
        if (!ev.lengthComputable) return;
        const p = ev.loaded / ev.total;
        bar.style.width = `${Math.round(p * 100)}%`;
        if (p >= 1) btn.innerHTML = '<span class="spin"></span> Datei wird ausgewertet …';
      };
      xhr.onload = () => {
        let data = {};
        try { data = JSON.parse(xhr.responseText); } catch { /* egal */ }
        if (xhr.status === 200 && data.pending_id) {
          store.set("pending", data);
          renderPicker(data);
        } else {
          toast(data.error || `Fehler ${xhr.status}`, true);
          btn.disabled = false; btn.textContent = "Weiter zur Rundenauswahl"; prog.hidden = true; bar.style.width = "0";
        }
      };
      xhr.onerror = () => {
        toast("Verbindung abgebrochen", true);
        btn.disabled = false; btn.textContent = "Weiter zur Rundenauswahl"; prog.hidden = true;
      };
      xhr.send(file);
    });
  }

  function renderPicker(p) {
    setTop({ title: "" });
    const hint = (k) => (p.auto && p.auto[k] ? "<em>aus Datei</em>" : "");
    const roleSel = (r) => `<label class="f"><span>${esc(r.label)}</span>
      <select name="role_${esc(r.id)}"><option value="">– nicht zugeordnet –</option>
      ${p.channels.map((c) => `<option value="${esc(c.id)}"${c.id === r.suggested ? " selected" : ""}>${esc(c.name)}${c.unit ? ` (${esc(c.unit)})` : ""}</option>`).join("")}
      </select></label>`;
    view.innerHTML = `<h1>Runde wählen</h1>
      <p class="lede">Schritt 2 von 2: <span class="mono small">${esc(p.filename)}</span> enthält ${p.laps.length} ${p.laps.length === 1 ? "Runde" : "Runden"}.
        Eine davon wird gespeichert.</p>
      <form class="stack" id="save" novalidate>
        <input type="hidden" name="pending_id" value="${esc(p.pending_id)}">
        <h2>Runde</h2>
        ${p.laps.map((l, i) => `<label class="radio"><input type="radio" name="lap" value="${esc(l.lap_number)}"${i === 0 ? " checked" : ""}>
          <span class="t">${esc(l.time)}</span><span class="muted small">Runde ${esc(l.lap_number)}${i === 0 ? " · schnellste" : ""}</span></label>`).join("")}
        <h2>Angaben</h2>
        <label class="f"><span>Fahrer${hint("driver")}</span><input type="text" name="driver" value="${esc(p.driver)}"></label>
        <label class="f"><span>Motorrad${hint("bike")}</span><input type="text" name="bike" value="${esc(p.bike)}"></label>
        <label class="f"><span>Strecke${hint("track")}</span><input type="text" name="track" value="${esc(p.track)}"></label>
        <label class="f"><span>Datum${hint("session_date")}</span><input type="date" name="session_date" value="${esc(p.session_date)}"></label>
        <label class="f"><span>Notizen</span><textarea name="notes">${esc(p.notes)}</textarea></label>
        ${p.channels.length ? `<details class="more"><summary>Kanal-Zuordnung (optional, für den AI-Coach)</summary>
          <div class="stack" style="margin-top:8px">${p.roles.map(roleSel).join("")}</div></details>` : ""}
        <div class="btns two" style="margin-top:16px"><button class="btn ghost" type="button" id="cancel">Abbrechen</button>
          <button class="btn primary">Speichern</button></div>
      </form>`;
    view.querySelector("#cancel").addEventListener("click", () => { store.set("pending", null); renderHochladen(); });
    const f = view.querySelector("#save");
    f.addEventListener("submit", async (e) => {
      e.preventDefault();
      const btn = f.querySelector(".primary");
      try {
        await busy(btn, () => submit("/sessions/save", new FormData(f)));
        store.set("pending", null);
        toast("Runde gespeichert");
        await loadLaps(true);
        store.set("filter", { ...store.get("filter", {}), who: "meine", sort: "datum", q: "", track: "" });
        location.hash = "#/runden";
      } catch (ex) {
        // Abgelaufen (Server neu gestartet): neu beginnen
        if (/abgelaufen|pending_id/i.test(ex.message)) store.set("pending", null);
        toast(ex.message, true);
      }
    });
  }

  // ---------------------------------------------------------------- Ansicht: Bestzeiten

  async function renderBestzeiten() {
    setTab("bestzeiten");
    setTop({ title: "" });
    loading();
    const { records } = await api("/m/api/records");
    view.innerHTML = `<h1>Bestzeiten</h1><p class="lede">Die drei schnellsten Fahrer je Strecke, jeder mit seiner besten Runde.</p>
      ${records.length ? `<div class="stack">${records.map((t) => `<section class="card track"><h3>${esc(t.track)}</h3>
        ${t.entries.map((e) => `<button class="rec r${e.rank}" type="button" data-lap="${e.lap_id}">
          <span class="n">${e.rank}</span><span class="who"><b>${esc(e.name)}</b><i>${esc([e.bike, fmtDate(e.date)].filter(Boolean).join(" · ") || "—")}</i></span>
          <span class="t">${esc(e.time)}</span></button>`).join("")}</section>`).join("")}</div>`
        : `<div class="empty"><b>Noch keine Bestzeiten</b>Sobald Runden mit Strecke hochgeladen sind, erscheinen sie hier.</div>`}`;
    view.querySelectorAll("[data-lap]").forEach((b) => b.addEventListener("click", () => lapSheet(Number(b.dataset.lap))));
  }

  // ---------------------------------------------------------------- Ansicht: Profil

  const img = (file, cls, alt, initial = "") => file
    ? `<img class="${cls}" src="/profile/image/${encodeURIComponent(file)}" alt="${esc(alt)}" loading="lazy">`
    : `<span class="${cls}">${esc(initial)}</span>`;

  async function renderProfil(params) {
    setTab("profil");
    setTop({ title: "" });
    if (!me) return needLogin("#/profil");
    loading();
    const p = await api("/m/api/profile");
    const flash = params.get("ok") ? `<div class="flash">${esc(params.get("ok"))}</div>` : "";
    view.innerHTML = `${flash}
      <div class="who-head">${img(p.image, "avatar", "Fahrerfoto", (p.driver_name || me.name || "?")[0].toUpperCase())}
        <div class="grow"><h1>${esc(p.driver_name || me.name)}</h1><div class="muted small">${esc(p.email)}</div>
          <a class="small" href="#/fahrer/${me.id}">Öffentliches Profil ansehen</a></div></div>

      <h2>Fahrer</h2>
      <form class="card stack" id="prof" novalidate>
        <label class="f"><span>Fahrername</span><input type="text" name="driver_name" value="${esc(p.driver_name)}" maxlength="200"></label>
        <label class="f"><span>Foto (optional)</span><input type="file" name="image" accept="image/*"></label>
        <button class="btn primary">Speichern</button>
      </form>

      <h2>Motorräder</h2>
      <div class="stack" id="bikes">
        ${p.bikes.map((b) => `<div class="card bike" data-bike="${b.id}">
          ${b.image ? `<img src="/profile/image/${encodeURIComponent(b.image)}" alt="" loading="lazy">` : `<span class="ph">🏍</span>`}
          <div class="grow"><b>${esc(b.name)}</b>${b.is_current ? '<span class="pill">AKTUELL</span>' : ""}</div>
          <button class="icon-btn" type="button" data-act="menu" aria-label="Aktionen für ${esc(b.name)}">⋯</button></div>`).join("")
          || '<p class="muted">Noch kein Motorrad eingetragen.</p>'}
        <button class="btn" type="button" id="add-bike">+ Motorrad hinzufügen</button>
      </div>

      <h2>Konto</h2>
      <div class="btns">
        ${me.is_admin ? `<a class="btn" href="/admin">Admin (Desktop-Ansicht)</a>` : ""}
        <button class="btn danger" type="button" id="logout">Abmelden</button>
      </div>
      ${footer()}`;

    const pf = view.querySelector("#prof");
    pf.addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        await busy(pf.querySelector(".primary"), () => submit("/profile/save", new FormData(pf)));
        await loadMe(); lapsCache = null;
        toast("Profil gespeichert");
        renderProfil(new URLSearchParams());
      } catch (ex) { toast(ex.message, true); }
    });
    view.querySelector("#add-bike").addEventListener("click", () => bikeSheet(null));
    view.querySelectorAll('[data-act="menu"]').forEach((btn) => btn.addEventListener("click", () => {
      const b = p.bikes.find((x) => x.id === Number(btn.closest("[data-bike]").dataset.bike));
      const s = openSheet(`<h2>${esc(b.name)}</h2><div class="btns">
        ${b.is_current ? "" : `<button class="btn primary" type="button" data-a="current">Als aktuelles Motorrad setzen</button>`}
        <button class="btn" type="button" data-a="edit">Umbenennen / Foto ändern</button>
        <button class="btn danger" type="button" data-a="delete">Löschen</button>
        <button class="btn ghost" type="button" data-a="close">Schließen</button></div>`);
      s.querySelector('[data-a="close"]').addEventListener("click", closeSheet);
      s.querySelector('[data-a="edit"]').addEventListener("click", () => bikeSheet(b));
      const cur = s.querySelector('[data-a="current"]');
      if (cur) cur.addEventListener("click", () => bikeAction(cur, `/profile/bike/${b.id}/set-current`, "Aktuelles Motorrad gesetzt"));
      const del = s.querySelector('[data-a="delete"]');
      del.addEventListener("click", () => {
        if (confirm(`${b.name} löschen?`)) bikeAction(del, `/profile/bike/${b.id}/delete`, "Motorrad gelöscht");
      });
    }));
    view.querySelector("#logout").addEventListener("click", async (e) => {
      try { await busy(e.currentTarget, () => submit("/logout", form({}))); } catch { /* Redirect auf / */ }
      me = null; lapsCache = null;
      toast("Abgemeldet");
      location.hash = "#/runden";
    });
  }

  async function bikeAction(btn, url, msg) {
    try {
      await busy(btn, () => submit(url, form({})));
      closeSheet();
      await loadMe();
      toast(msg);
      renderProfil(new URLSearchParams());
    } catch (ex) { toast(ex.message, true); }
  }

  function bikeSheet(b) {
    const s = openSheet(`<h2>${b ? "Motorrad bearbeiten" : "Motorrad hinzufügen"}</h2>
      <form class="stack" id="bike-form" novalidate>
        <label class="f"><span>Name</span><input type="text" name="name" value="${esc(b ? b.name : "")}" required maxlength="200"></label>
        <label class="f"><span>Foto (optional)</span><input type="file" name="image" accept="image/*"></label>
        ${b ? "" : `<label class="check"><input type="checkbox" name="is_current" value="1" checked> Als aktuelles Motorrad setzen</label>`}
        <div class="btns two"><button class="btn ghost" type="button" data-cancel>Abbrechen</button><button class="btn primary">Speichern</button></div>
      </form>`);
    s.querySelector("[data-cancel]").addEventListener("click", closeSheet);
    const f = s.querySelector("#bike-form");
    f.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!f.elements.name.value.trim()) { toast("Bitte einen Namen eingeben", true); return; }
      try {
        await busy(f.querySelector(".primary"), () => submit(b ? `/profile/bike/${b.id}/edit` : "/profile/bike/add", new FormData(f)));
        closeSheet();
        await loadMe();
        toast(b ? "Gespeichert" : "Motorrad hinzugefügt");
        renderProfil(new URLSearchParams());
      } catch (ex) { toast(ex.message, true); }
    });
  }

  async function renderFahrer(id) {
    setTab("");
    setTop({ title: "Fahrer", back: true });
    loading();
    const d = await api(`/m/api/driver/${Number(id)}`);
    view.innerHTML = `<div class="who-head">${img(d.image, "avatar", "Fahrerfoto", (d.name || "?")[0].toUpperCase())}
        <div class="grow"><h1>${esc(d.name)}</h1>${d.is_self ? '<a class="small" href="#/profil">Profil bearbeiten</a>' : ""}</div></div>
      ${d.bikes.length ? `<h2>Motorräder</h2><div class="stack">${d.bikes.map((b) => `<div class="card bike">
        ${b.image ? `<img src="/profile/image/${encodeURIComponent(b.image)}" alt="" loading="lazy">` : `<span class="ph">🏍</span>`}
        <div class="grow"><b>${esc(b.name)}</b>${b.is_current ? '<span class="pill">AKTUELL</span>' : ""}</div><span></span></div>`).join("")}</div>` : ""}
      <h2>Runden (${d.laps.length})</h2>
      <div class="laps">${d.laps.slice().sort((a, b) => a.duration_s - b.duration_s).map((l) => lapCard(l)).join("") || '<p class="muted">Keine Runden.</p>'}</div>`;
    view.querySelectorAll("[data-lap]").forEach((b) => b.addEventListener("click", () => lapSheet(Number(b.dataset.lap))));
  }

  // ---------------------------------------------------------------- Anmelden / Registrieren

  function renderLogin(params) {
    setTab("profil");
    setTop({ title: "Anmelden", back: true });
    const next = params.get("next") || "#/runden";
    view.innerHTML = `<h1>Anmelden</h1>
      <form class="stack" id="login" novalidate>
        <label class="f"><span>E-Mail</span><input type="email" name="email" autocomplete="email" required></label>
        <label class="f"><span>Passwort</span><input type="password" name="password" autocomplete="current-password" required></label>
        <button class="btn primary">Anmelden</button>
      </form>
      <p class="center muted" style="margin-top:18px">Noch kein Konto? <a href="#/registrieren">Konto anlegen</a></p>
      ${footer()}`;
    const f = view.querySelector("#login");
    f.addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        await busy(f.querySelector(".primary"), () => submit("/login", form({
          email: f.elements.email.value.trim(), password: f.elements.password.value, next: "/m" })));
        await loadMe();
        if (!me) throw new Error("Anmeldung fehlgeschlagen");
        lapsCache = null;
        toast(`Angemeldet als ${me.name}`);
        location.hash = next.startsWith("#/") ? next : "#/runden";
      } catch (ex) { toast(ex.message, true); }
    });
  }

  function renderRegister() {
    setTab("profil");
    setTop({ title: "Konto anlegen", back: true });
    view.innerHTML = `<h1>Konto anlegen</h1>
      <p class="lede">Du bekommst eine E-Mail mit einem Bestätigungslink.</p>
      <form class="stack" id="reg" novalidate>
        <label class="f"><span>E-Mail</span><input type="email" name="email" autocomplete="email" required></label>
        <label class="f"><span>Passwort (mind. 6 Zeichen)</span><input type="password" name="password" autocomplete="new-password" minlength="6" required></label>
        <label class="f"><span>Passwort wiederholen</span><input type="password" name="password2" autocomplete="new-password" minlength="6" required></label>
        <p class="muted small">Mit dem Anlegen akzeptierst du die <a href="/datenschutz">Datenschutzerklärung</a>.</p>
        <button class="btn primary">Konto anlegen</button>
      </form>${footer()}`;
    const f = view.querySelector("#reg");
    f.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (f.elements.password.value !== f.elements.password2.value) { toast("Die Passwörter sind verschieden", true); return; }
      try {
        await busy(f.querySelector(".primary"), () => submit("/register", form({
          email: f.elements.email.value.trim(), password: f.elements.password.value, password2: f.elements.password2.value })));
        view.innerHTML = `<div class="empty"><b>Fast geschafft</b>Wir haben dir eine E-Mail an
          <span class="mono">${esc(f.elements.email.value.trim())}</span> geschickt. Bestätige den Link darin, dann kannst du dich anmelden.</div>
          <a class="btn primary" href="#/login">Zur Anmeldung</a>`;
      } catch (ex) { toast(ex.message, true); }
    });
  }

  const footer = () => `<div class="links"><a href="/m/desktop">Desktop-Version</a><a href="/impressum">Impressum</a><a href="/datenschutz">Datenschutz</a></div>`;

  // ---------------------------------------------------------------- Router

  async function route() {
    closeSheet();
    document.body.classList.remove("frame");
    const raw = location.hash.replace(/^#/, "") || "/runden";
    const [pathPart, query = ""] = raw.split("?");
    const parts = pathPart.split("/").filter(Boolean);
    const params = new URLSearchParams(query);
    try {
      switch (parts[0]) {
        case "runden": return await renderRunden(params);
        case "vergleich": return await renderVergleich();
        case "hochladen": return await renderHochladen();
        case "bestzeiten": return await renderBestzeiten();
        case "profil": return await renderProfil(params);
        case "fahrer": return await renderFahrer(parts[1]);
        case "ansicht": return renderFrame(parts[1], params);
        case "login": return renderLogin(params);
        case "registrieren": return renderRegister();
        default: location.replace("#/runden");
      }
    } catch (ex) {
      view.innerHTML = `<div class="empty"><b>Fehler</b>${esc(ex.message)}</div>
        <button class="btn" type="button" id="retry">Erneut versuchen</button>`;
      view.querySelector("#retry").addEventListener("click", () => { lapsCache = null; route(); });
    } finally {
      if (!document.body.classList.contains("frame")) window.scrollTo(0, 0);
    }
  }

  window.addEventListener("hashchange", route);
  loadMe().then(route);
})();
