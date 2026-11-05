// legal_data.js — Zentrale Angaben für Impressum & Datenschutzerklärung.
//
// HIER die Platzhalter füllen (Werte können 1:1 aus der reifenbild.de
// legal_data.js übernommen werden — gleiches Muster). Die Seiten
// /impressum und /datenschutz lesen ausschließlich aus dieser Datei;
// an den HTML-Dateien selbst muss nichts geändert werden.
//
// Nach Änderungen: kein Server-Neustart nötig, nur Browser-Reload
// (Cache-TTL der statischen Dateien: 5 Minuten).

const LEGAL_DATA = {
  // --- Verantwortlicher (Impressum + Datenschutz) ---
  name: "VORNAME NACHNAME",              // TODO
  strasse: "STRASSE HAUSNUMMER",         // TODO
  plzOrt: "PLZ ORT",                     // TODO
  email: "KONTAKT@EXAMPLE.COM",          // TODO
  telefon: "",                           // optional, leer = Zeile wird ausgeblendet

  // --- Hosting ---
  // Name + Anschrift des Hosters, oder "Eigener Server" wenn die Maschine
  // bei dir selbst steht.
  hosterName: "HOSTER GMBH",             // TODO
  hosterAnschrift: "HOSTER-STRASSE 1, 12345 STADT",  // TODO

  // --- Betriebsart ---
  // Wird im Impressum als Zusatz angezeigt, z.B.:
  // "Privat betriebenes, nichtkommerzielles Projekt."
  betriebsart: "Privat betriebenes, nichtkommerzielles Projekt.",

  // --- Datum der letzten Aktualisierung der Datenschutzerklärung ---
  stand: "August 2026",
};

// Füllt alle Elemente mit data-legal="<key>" mit dem jeweiligen Wert.
// Elemente mit data-legal-row werden komplett ausgeblendet, wenn der
// Wert leer ist (z.B. Telefon).
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-legal]").forEach((el) => {
    const key = el.getAttribute("data-legal");
    const val = LEGAL_DATA[key];
    if (val === undefined) return;
    if (!val && el.hasAttribute("data-legal-row")) {
      el.style.display = "none";
      return;
    }
    el.textContent = val;
  });
  // mailto-Links
  document.querySelectorAll("[data-legal-mailto]").forEach((el) => {
    el.setAttribute("href", "mailto:" + LEGAL_DATA.email);
    el.textContent = LEGAL_DATA.email;
  });
});
