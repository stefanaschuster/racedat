# Racedat — Kontext (v23.7 stable)

## Stand: v23.7 — AIM CSV Importer Fix (Beacon-Liste 1:1, Distance-Boundaries)

[DOCUMENT] Code: /home/claude/lap_tool/
[DOCUMENT] Output ZIP: /mnt/user-data/outputs/lap_compare.zip
[DOCUMENT] Setup: siehe unten
[DOCUMENT] Tests gesamt: **832 grün** (708 Python + 124 JS, davon
v22.7 neu: 26 Python + 38 JS; v22.8 neu: 10 Python; v22.9 neu: 25 JS;
v22.10 neu: 21 Python — thresholds-Loader + Coach-Integration-Check;
v22.11 neu: 28 Python — IP-Klassifizierung, Render-Cell, fetch_ip_geo
mit stub, Render-Page-Branches;
v22.12 neu: 54 Python — Profile-CRUD, Image-Helper mit Whitelist und
Path-Traversal-Schutz, HTTP-Endpoints, Upload-Pre-Fill-Integration,
Sessions-Mine-Filter, Header- und Landing-Tile-Regressionsschutz;
v23.0 neu: 20 Python — Public-Profile-Route, Self-Hint-Branch, E-Mail-
Localpart-Fallback, Owner-Link in Sessions-Liste, XSS-Defense im
Read-Only-Renderer;
v23.1 neu: 26 Python — best_lap_per_track_for_user (10 DB-Tests +
canonical-Spelling), render_best_laps_html (5 Helper-Tests inkl. XSS),
4 Bugfix-Tests "EIGENE RUNDEN ausblenden bei Fremd-Profil", 7
Integration-Tests Bestzeiten auf Public + Edit-Seite;
v23.2 neu: 45 Python — global_top_n_per_track (11 DB-Tests inkl.
ex-aequo + case-insensitivity + alphabetische Sortierung), Medal-
Helper (9 Tests inkl. render_medal_html und medal_map_from_top_n),
3 Tests für render_best_laps_html mit Medals, /records-Seite (13
Route-Tests inkl. XSS + Empty-State + Privacy + Landing-Tile),
Pokal-Icons in Sessions-Liste (2) und auf Profil (4) inkl. cross-
user-Sichtbarkeit, Bugfix "Datum raus" mit Regression-Test
gegen jeden Date-String im Output;
v23.3 neu: 6 Python — Test2DRijekaQ1_400Hz: meta + time_axis_matches_
time2d (4×-Stretch-Regression) + hex_rate_divisor + laps_within_
recording + fastest_lap_closes_loop (Stefans "kein Rundkurs"-Symptom)
+ gps_at_rijeka;
v23.4 neu: 13 Python — TestListAllProfilesDB (6 Tests: empty/lookup
mit users-JOIN/bike-count+current/admin-flag/sort-by-updated_at/
count_users) + TestAdminProfilesRoute (6 Tests: anon→login + non-
admin→404 + admin sieht Tab + /profile/<id>-Direktlinks + Bike-Info
mit Singular/Plural + Default-Tab unchanged) + TestAdminProfiles
EmptyState (1 Test mit isoliertem 2. Server, weil AppState-Singleton
sonst leakt);
v23.6 neu: 48 Python — AIM CSV Importer (siehe Detail-Block unten);
v23.7 neu: 1 Python netto (Tests umgebaut nach Bug-Report:
test_no_speed_filter_regression + test_lap_distances_consistency +
test_lap_distances_export (Jerez + Aragon) + test_lap_distances_
monotone (Jerez) + test_lap_22_is_206_runde + test_lap_22_distance_
matches_rs3_screenshot; entfernt: test_filter_drops_stillstand_
phantoms + test_every_lap_has_real_motion (Jerez+Aragon) +
test_no_phantom_after_session_end + test_speed_filter_drops_low_
speed_lap + test_speed_filter_threshold_exact))

## Versionsverlauf (gekürzt: v21.32 → v22.1)

### v21.32–v21.38 — Sessions/Datenviewer-Links, Channel-Roles-Registry, Admin-Edit-Modal, Badges, Owner-Edit-Permission
- v21.32: VERGLEICH-Sublink in Sessions-Liste (`/compare?a=<lap_id>`)
- v21.33: VERGLEICH-Link im Datenviewer-Header
- v21.34: `parsers/channel_roles.py` als Single-Source-of-Truth für Channel-Rollen
- v21.35: `GET/POST /api/laps/<id>/channel-roles` + Admin-Edit-Modal
- v21.36: Channel-Status-Badge in Rundenliste (derived, nicht persistiert)
- v21.37: Owner-or-Admin Edit-Permission
- v21.38: Channel-Badge im Coach-Rundenpicker

### v21.39 — Elektronik-Setup-Analyse
4 neue Rollen (`wheel_speed_front`/`rear`, `tc_status`, `wc_status`).
Panel `panel-electronics` mit 6-Slot Picker + 4 Detektoren:
- Slip-/Lockup: `|V_rear - V_front| / max(V) > 10%` für ≥100ms
- Spike: `dV_rear/dt > 30/s` mit 150ms Fenster
- Oszillation: rolling stdev/|mean| > 5% für ≥300ms
- Status-Events (TC/WC): Mode-Detection + Abweichung > 0.5 für ≥50ms

### v21.40 — Sparkline pro Event + Multi-Channel-Chart + Cursor-Sync
1. Sparkline rechts pro Event-Zeile mit Multi-Scale-Logik.
2. Multi-Channel-Chart unter Trackmap. [NOTE: entfernt in v21.46]
3. Cursor-Sync beidseitig Trackmap ↔ Chart.

### v21.41 — Analyse-UI als Tabs (statt 2×2-Karten-Grid)

### v21.42 — 2D → MoTeC LD Konverter (`d22ld.py`)
CLI analog zu `ses2ld.py`/`xrk2ld.py`. Beide 2D-Bundle-Varianten (bmw_hp +
race2025) transparent. 37 Tests grün + 3 skipped.
[NOTE] VERSION-Bump initial vergessen, in v21.43 nachgeholt.

### v21.43 — UI-Rename: Throttle → Gasgriff
Durchgängig "GASGRIFF" statt "THROTTLE" in der UI; Internal IDs/Patterns
unangetastet (Pickle/DB-Backward-Compat).

### v21.44 — Vorschlag direkt vorausgewählt + Coach-Channel-Liste raus
- Upload + Edit-Modal: Pattern-Vorschlag im `<select>` selected, Hint weg.
  Im Modal Logik-Fix: `effectiveId = persistedId || suggested`.
- Coach-Empty-State Channel-Kästchen-Liste entfernt (3 Stellen).

### v21.45 — Marker ↔ Row Verlinkung
Geteilter Helper `setupMarkerRowLink(host, mapHost, mapWrap)`. Sticky,
Toggle-aus bei Re-Klick. `.is-selected` CSS-Klasse + `.mk-bubble` Outline-
Ring auf SVG-Markern.

### v21.46 — Drei Änderungen in allen Analysen
**Teil 1: Beidseitiger Autoscroll**: Helper-Erweiterung um `lastSource`
('row'/'map'/'api') — Marker-Klick scrollt Row, Row-Klick scrollt mapWrap.

**Teil 2: v21.40-Multi-Channel-Chart raus**: HTML/CSS/JS für `elec-chart-*`
und `setupChannelChart`/`renderChannelChart` etc. entfernt (~290 Zeilen).
`_mapCache`/`_cursorListeners`/`setMapCursor` für späteren Re-Use behalten.

**Teil 3: Datenviewer-Chart als letzter Abschnitt jeder Analyse**: Factory
`webapp/speed_chart.js` extrahiert. Statische-File-Route `/static/<file>`
in webserver.py mit Extension-Whitelist + Path-Traversal-Schutz. Datenviewer
nutzt Factory (`cursorMode: 'external'`), Coach hat drei Instanzen
(Prefix `csb-`/`csa-`/`cse-`) mit Vorselektion aus `channelRoles`.

### v22.0 — Version-Bump + UI-Sichtbarkeit + Selection→Chart + Banner
Vier Änderungen: Bump auf v22.0, hellere `.tm-bg-btn`/`.seg-switch` Buttons
(Border `#262626→#4a4a4a`, Text `#a0a0a0→#c8c8c8`), Event-Selektion setzt
Sticky-Cursor im Datenviewer-Chart unten (`speed_chart.js` um
`setStickyCursor`/`clearStickyCursor` erweitert, `setupMarkerRowLink` um
vierten Parameter `onSelect(eventIdx|null, source)`, Coach-Module setzen
`window._coachCharts = {brake, accel, electronics}`), Banner zeigt Version.

### v22.1 — Debug-Logging via --debug-log flag

[DECISION] Stefan: `--debug-log` Flag soll viel mehr Logging einschalten.
Jede Anfrage, jede Aktion mit User und Kontext, in einem einfach zu
analysierenden Format.

[DECISION] Format: **logfmt** (key=value, lesbar im Terminal,
grep/awk-freundlich) auf stderr. Nicht JSONL (weil im Terminal beim
Live-Anschauen zu sperrig) und nicht in eine Datei (Stefan hat den
bisherigen Server-Log-Output auch immer auf stderr).

[DECISION] Was rein: Requests (Methode/Pfad/Status/Dauer/User/IP),
Auth-Events (Login OK/fail, Logout), Aktionen mit Kontext (Upload, Delete,
Edit, Compare, Analyze, Coach, Admin-Delete, Channel-Roles-Edit).
DB-Schreibvorgänge nicht — wären redundant zu den Aktions-Logs.

**Teil 1: Neues Modul `debuglog.py`**
- Globaler `_enabled`-Flag. Wenn aus, ist `log()` ein no-op (kostengünstig).
- `configure(enabled, stream=None)` — wird einmal aus `main()` aufgerufen.
  Tests redirecten via StringIO.
- `log(event, *, level='info', **fields)` — formatiert eine Zeile:
  `ts=2026-05-19T13:12:47Z lvl=info ev=req method=GET path=/sessions status=200 ...`
- logfmt-Quoting: Werte mit Whitespace, `=` oder `"` werden in
  Doppel-Quotes gepackt; `\`, `\n`, `\r` und `"` werden escaped. None und
  leere Strings werden gedroppt (sonst rauscht der Log).
- Reihenfolge: ts, lvl, ev kommen zuerst, dann Felder in
  insertion-order — sodass User/IP früh kommt wenn die Caller sie früh
  übergeben.
- Threadsicher via Lock (mehrere Listener-Threads schreiben gleichzeitig).
- `fields_from_ctx(ctx)` Helper projiziert request_ctx → {user, ip}.
- `try/except` um den `stream.write()` — Logging darf nie crashen.

**Teil 2: Request-Wrapper in `WebHandler`**
- `handle_one_request` überschrieben. Wrappt mit Timer + Status-Capture.
  Wenn `is_enabled() == False`, einfach `super().handle_one_request()` —
  null Overhead.
- `send_response_only(code, msg=None)` überschrieben um Status-Code
  mitzuschneiden in `self._req_status`. Das ist der unterste Punkt der
  von allen Variants (`send_response`, `send_error`) aufgerufen wird.
- Edge-Case: keep-alive idle close → keine Command, status=0 → wird
  gefiltert (keine Phantom-Zeile).
- `dur_ms` = Wall-Clock von "Request-Line gelesen" bis "Handler returned".

**Teil 3: Aktions-Logs in Handlern**
- Auth: `_handle_login` (OK + Fail), `_handle_logout`.
- Compare: `action.compare.upload.{ok,error}`, `action.compare.{ok,error}`.
- Analyze: `action.analyze.{library,upload.ok,upload.error}`.
- Coach: `action.coach.{library,upload.ok,upload.error}`.
- Session upload: `action.session.upload.step{1,2}.{ok,error}`.
- Session edit: `action.session.edit.{ok,denied,notfound}` mit
  `changed=k1,k2,...` (komma-joined → bare token, keine Quotes nötig).
- Lap delete: `action.lap.delete.{ok,denied,notfound,error}` mit
  `as_admin` und `session_purged`.
- Admin: `action.admin.delete.{ok,error,denied}`,
  `action.admin.event_delete.{ok,denied,notfound}`.
- Channel-Roles: `action.lap.channel_roles.edit.ok` mit
  `changed=role1,role2`.

Konvention: `.ok` = info, `.denied`/`.notfound` = warn,
`.error` = error. Bei jeder `denied`-Variante steht `reason=…` dabei
(`not_logged_in`, `not_owner_not_admin`, `not_admin`, `bad_credentials`).

**Teil 4: CLI + Banner**
- `--debug-log` (store_true) in `main()`. Default aus.
- `debuglog.configure(enabled=args.debug_log)` GANZ am Anfang von `main()`
  — bevor irgendwas anderes Logging-Calls macht.
- Wenn an: Banner zeigt `║  Debug log  ON (stderr, logfmt)            ║`
  (zwischen "Max upload" und "Stop with Ctrl-C").
- VERSION = "v22.1" → Banner zeigt "RACEDAT · WEB · v22.1".

**Tests:**
- `tests/test_debug_log.py`: 24 grün — enabled-Flag, logfmt-Quoting
  (space/equals/quote/backslash/newline/cr), None/empty drop,
  Key-Sanitisation, Level, fields_from_ctx, write-failure-safety.

**E2E verifiziert:**
```
ts=2026-05-19T13:12:47Z lvl=info ev=auth.login.ok user=testuser@example.com ip=127.0.0.1 admin=false next=/sessions
ts=2026-05-19T13:12:47Z lvl=info ev=req method=POST path=/login status=303 dur_ms=418 ip=127.0.0.1
ts=2026-05-19T13:12:47Z lvl=info ev=req method=GET path=/sessions status=200 dur_ms=3 user=testuser@example.com ip=127.0.0.1
ts=2026-05-19T13:12:47Z lvl=warn ev=action.lap.delete.notfound user=testuser@example.com ip=127.0.0.1 lap_id=999
ts=2026-05-19T13:12:47Z lvl=info ev=auth.logout user=testuser@example.com ip=127.0.0.1
```

Ohne `--debug-log`: kein logfmt-Output, nur der bisherige Apache-Style
Server-Log (über `log_message`). Banner sagt nichts von Debug. Komplett
opt-in.

### v22.2 — Track-Name case-insensitive (Filter + Auto-Canonicalize) 

[DECISION] Stefan: (1) Streckenfilter case-insensitive, (2) Upload mit
abweichender Case soll bestehende Schreibweise übernehmen.

[DECISION] Implementierung auf DB-Schicht — eine zentrale Stelle
(`db.canonical_track_name`) statt verteilte Normalisierung in jedem
Handler. SQL-Filter wechselt auf `LOWER(track) = LOWER(?)`.

**Teil 1: `db.canonical_track_name(track)`**
- Strippt Input. Leer → `""` (kein DB-Hit).
- Sonst: `SELECT track FROM sessions WHERE LOWER(track) = LOWER(?)
  AND track != '' ORDER BY created_at ASC LIMIT 1`.
- Match → DB-Spelling zurück (deterministisch erste je nach Insert-Zeit).
- Kein Match → Input zurück (strip applied).
- Idempotent: exakt-passende Case → unverändert.

**Teil 2: `query_laps(track=…)` case-insensitive**
- `sessions.track = ?` → `LOWER(sessions.track) = LOWER(?)`.
- `LIKE`-Search (`search`-Param) war schon case-insensitive in SQLite-ASCII;
  bleibt unverändert.

**Teil 3: Aufrufstellen in `webserver.py`**
- `step2_save_session`: `track_name = canonical_track_name(track_name)`
  direkt nach `(form.get("track") or pending["track"]).strip()`.
- `update_session_meta`-Handler (`POST /api/sessions/<id>/edit`): gleich
  vor dem `update_session_meta`-Call. Sonst wäre Edit ein Schlupfloch um
  abweichende Case wieder einzuschleusen.
- Coach/Compare-Adhoc-Uploads: NICHT canonicalisiert — der Track-Name
  kommt dort aus den Parser-Metadaten und wird nicht persistiert (nur
  temporär für die Anzeige).

**Teil 4: VERSION-Bump auf v22.2**

**Tests:** `tests/test_track_case_insensitive.py` — 13 grün
- `canonical_track_name`: empty/whitespace, no-match, snap zu existing
  spelling (3 casings), unrelated track unverändert, first-inserted wins,
  empty track in DB ignoriert.
- `query_laps`: lower/upper/title alle matchen alle Casings, schließt
  unrelated track aus, no-match → leer.
- End-to-end DB-only: subsequent uploads erben erste Schreibweise,
  `distinct_values()["track"]` collapsed auf einen Eintrag.

[NOTE] Frontend-JS-Filter (`sessions.html` Zeile 353, `track !== wTrack`)
ist case-sensitive. Egal — durch Punkt 2 gibt's in der DB künftig nur
noch eine kanonische Schreibweise pro Track. Für Legacy-Daten mit
inkonsistenter Case greift Punkt 1 auf API-Ebene.

[NOTE] `distinct_values()` selbst wurde nicht angefasst — gibt nach wie
vor DISTINCT zurück. Nach Migration neuer Uploads konsolidiert sich
das automatisch. Falls Stefan später für Legacy-Daten konsolidieren will:
SQL-Migration `UPDATE sessions SET track = (SELECT track FROM sessions s2
WHERE LOWER(s2.track)=LOWER(sessions.track) ORDER BY s2.created_at LIMIT 1)`.

### v22.3 — Channel-Status-Dots in allen Pickern + Rundenansicht

[DECISION] Stefan: Pro Kanal-Rolle ein **kleines graues Symbol** mit
Mouseover-Label ("BREMSDRUCK" etc.); wenn die Rolle für diese Runde
zugeordnet ist → grün. Ersetzt die v21.36/v21.38 Aggregat-Badge
("X von Y zugeordnet"). Gilt für alle vier Picker (Rundenansicht,
Coach, Datenviewer, Compare).

[DECISION] Symbol = `●` (U+25CF), Grau `#6a6a6a` / Grün `#3aff7a`
(identisch zur Coach-Palette). Tooltip nutzt das `label` aus der
Registry direkt — "BREMSDRUCK" etc. (konsistent mit dem Rest der App,
die durchgehend CAPS-Labels verwendet).

[DECISION] Alle 8 Rollen werden immer angezeigt — deterministisch,
macht Picker-Vergleich zwischen Laps trivial. Wenn die Runde keine
Zusatz-Kanäle hat (extras_count=0), wird die Dot-Zeile komplett
weggelassen (= bisheriges "absent"-Verhalten).

**Teil 1: `db.get_channel_summary` um `assigned_role_ids` erweitert**
- Bisher: `{extras_count, roles_count, total_roles}`.
- Neu: zusätzlich `assigned_role_ids: List[str]` — sortierte Liste der
  role_ids, die in diesem Lap eine Channel-Zuordnung haben.
- Sortiert für Determinismus (tests / cache-friendly).
- Leere Liste wenn keine Zuordnungen.

**Teil 2: Neuer Endpoint `GET /api/channel-roles-registry`**
- Statische Liste der Registry: `[{id, label, description}, ...]`
- Reihenfolge identisch zu `parsers.channel_roles.ROLES`
- Wird von allen 3 Frontend-Pickern (Coach, Datenviewer, Compare)
  einmal pro Modal-Open gefetcht und gecacht. Server-rendered
  Rundenansicht hat direkt Zugriff auf `CHANNEL_ROLES`.

**Teil 3: `/api/laps`-Response enriched**
- Jeder Lap kriegt `assigned_role_ids: List[str]` zusätzlich zu den
  bestehenden counts.

**Teil 4: Sessions-Liste (server-rendered)**
- `_channel_badge(lap_id)` → `_channel_dots(lap_id)`. Render 8
  `<span class="ch-dot {on|off}" title="LABEL">●</span>`-Spans.
- CSS in `sessions.html`: alte `.ch-badge`-Klassen raus, `.ch-dots`
  + `.ch-dot.on`/`.ch-dot.off` rein.
- Aggregat-Counter "X von Y zugeordnet" entfernt.

**Teil 5: Coach-Picker**
- `lp-ch-badge`-CSS → `lp-ch-dots`-CSS.
- JS: neue Funktion `loadRolesRegistry()` mit Cache (`rolesRegistry`-
  Variable), wird vor `loadLaps()` gerufen.
- `chBadge(lp)` → `chDots(lp)` — Iteriert `rolesRegistry`, vergleicht
  mit `lp.assigned_role_ids` Set.

**Teil 6: Datenviewer-Picker (`webapp/analyze.html`)**
- CSS für `.ch-dots`/`.ch-dot` hinzugefügt.
- Lazy-load `rolesRegistry` in `openModal()` zusammen mit `distinctValues`.
- `chDots(lap)` in `renderResults()` integriert.

**Teil 7: Compare-Picker (`webapp/upload.html`)**
- Gleiche Behandlung wie analyze.html.

**Teil 8: VERSION-Bump auf v22.3**

**Tests:**
- `test_channel_summary.py`: +6 Assertions für `assigned_role_ids`
  (empty, single, sorted multi, after-clear) → 33 grün (vorher 27).
- `test_api_laps_summary.py`: +21 Assertions (8 für `assigned_role_ids`
  pro Row über alle 4 Lap-States, 13 für den neuen
  `/api/channel-roles-registry`-Endpoint) → 51 grün (vorher 30).

[NOTE] Bewusst nicht angetastet:
- `roles_count` / `total_roles` / `extras_count` bleiben im Response —
  könnte ein zukünftiger Konsument noch brauchen, und sie sind eh frei
  abzuleiten. Kein Konsument im Repo nutzt sie noch (Sessions-HTML
  und Coach-JS sind beide auf Dots umgestellt).
- `lap_data['channel_roles']`-Format unverändert (Dict role_id→channel_id).

### v22.4 — Channel-Icons statt Punkte

[DECISION] Stefan: "Kannst Du mir statt der punkte kleine symbole erzeugen,
die den Kanal-Namen widerspiegeln? Also eine kleine Bremsscheibe für den
Bremsdruck, einen gasgriff für Gasgriff etc?"

[DECISION] Inline-SVG-Icons pro Rolle, 14×14, alle mit `currentColor` für
Strokes/Fills — so flippt die grau/grün-Logik (die wir bereits hatten)
unverändert weiter, ohne dass Icon-Code irgendwas von Farbe wissen muss.
CSS auf dem Wrapper (`color:#6a6a6a` bzw. `#3aff7a`) cascadet rein.

[DECISION] Single source of truth: neues Modul `webapp/role_icons.py`
mit `ROLE_ICONS: Dict[str, str]` (role_id → SVG-String). Sessions-Liste
(server-rendered Python) importiert direkt; alle 3 JS-Picker holen die
SVGs als zusätzliches Feld `icon` aus `/api/channel-roles-registry`.
So gibt's nur eine Stelle für alle 4 Picker.

**Die 8 Icons:**
- `brake_pressure` → **Bremsscheibe** (Außenring + Nabe + 6 Lüftungslöcher)
- `lean` → **Schräglage** (Bodenlinie + geneigter Bike-Körper + Winkel-Arc)
- `throttle` → **Gasgriff** (Lenker + Griff-Zylinder mit 4 Ridges)
- `throttle_butterfly` → **Drosselklappe** (Bohrung mit gekippter Ellipse + Welle)
- `wheel_speed_front` → **Vorderrad** (Reifen mit Innenring + V-Chevron nach oben)
- `wheel_speed_rear` → **Hinterrad** (Reifen mit Innenring + H-Chevron nach unten)
- `tc_status` → **TC-Badge** (Pill mit Text "TC")
- `wc_status` → **WC-Badge** (Pill mit Text "WC")

**Teil 1: Neues Modul `webapp/role_icons.py`**
- `ROLE_ICONS: Dict[str, str]` mit allen 8 SVGs.
- `icon_for(role_id)` mit Fallback (kleiner Punkt) für unbekannte Rollen
  → graceful degradation falls jemand `channel_roles.py` erweitert
  ohne Icon nachzuziehen.
- Alle SVGs benutzen `currentColor`, keine Hex/Named-Colors hartcodiert
  (sonst ginge das grau/grün-Switching kaputt).
- viewBox 14×14, `class="ch-icon"` auf jedem `<svg>` als CSS-Hook.

**Teil 2: `/api/channel-roles-registry` liefert `icon`-Feld**
- Bisher: `[{id, label, description}, ...]`.
- Neu: zusätzlich `icon: "<svg ...>...</svg>"` pro Eintrag.
- Trust-Boundary: Server-eigene Strings, kein User-Input → JS rendert
  via `innerHTML` ohne extra Sanitisation.

**Teil 3: Sessions-Liste (`webserver.py:_channel_dots`)**
- `<span class="ch-dot {on|off}">●</span>` → `<span class="ch-icon-wrap
  {on|off}" title="LABEL">{SVG}</span>`.
- Import `from webapp.role_icons import ROLE_ICONS, icon_for`.
- `webapp/` hat kein `__init__.py` aber Python 3.3+ behandelt es als
  Namespace-Package — funktioniert.

**Teil 4: CSS in allen 4 Picker-Stellen**
- `sessions.html`, `analyze.html`, `upload.html`, `coach.py`
- `.ch-icon-wrap { width:14px; height:14px; display:inline-flex }`
- `.ch-icon-wrap .ch-icon { width:14px; height:14px; display:block }`
- `.ch-icon-wrap.off { color:#6a6a6a }` / `.on { color:#3aff7a }`
- gap zwischen Icons auf 5px erhöht (vorher 4px für Punkte — Icons
  brauchen etwas mehr Luft).

**Teil 5: JS-`chDots`-Funktionen (3 Stellen)**
- Coach (`coach.py`), Datenviewer (`analyze.html`), Compare (`upload.html`)
- Aus dem Registry-Eintrag wird jetzt `role.icon` ausgelesen statt `●`.
- Iteration sonst unverändert.

**Teil 6: VERSION-Bump auf v22.4**

**Tests:**
- `test_role_icons.py` NEU (7 Assertions): jede Rolle hat ein Icon,
  keine Orphan-Icons ohne Rolle, jedes Icon ist well-formed SVG mit
  viewBox + class=ch-icon, keine hartcodierten Farben (Disziplin-Check),
  icon_for() known/unknown/fallback.
- `test_api_laps_summary.py`: +1 Assertion → 52 grün (`icon`-Feld im
  Registry-Endpoint).

[NOTE] Icon-Design ist absichtlich flat/iconic, nicht photorealistisch.
Bei 14×14 Pixel zählt Silhouette-Lesbarkeit, nicht Detail. TC/WC sind
Text-Badges, weil "Traction Control" als Piktogramm bei der Größe nicht
funktioniert — wer's mal versucht hat weiß das.

[NOTE] Falls Stefan ein Icon nicht gefällt: nur `webapp/role_icons.py`
anfassen, alles andere bleibt. Die SVGs sind keine Assets-Files, leben
als Strings — kein Build-Step, keine Cache-Invalidierung.

### v22.5 — Bugfix: Icons in Datenviewer- + Compare-Picker

[BUG] Stefan: "Ich sehe da weder Punkte noch icons. Schau nochmal nach."

Diagnose: in v22.3/v22.4 hatte ich die Picker-Anpassungen in
`webapp/analyze.html` und `webapp/upload.html` gemacht — beide sind aber
**tote Prototyp-Dateien**, vom Server gar nicht ausgeliefert. Die echten
Picker-Templates sind:
- **Datenviewer-Picker**: `report_single.py:_PAGE_TEMPLATE`
  (gerendert via `build_single_lap_empty_html`)
- **Compare-Picker**: `report.py:_TEMPLATE`
  (gerendert via `build_compare_empty_html`)

Coach und Sessions-Liste waren von Anfang an richtig (Coach hat JS
direkt in `coach.py`, Sessions-Liste ist server-rendered in
`webserver.py`).

**Teil 1: `report_single.py` Picker fixen**
- `.lp-ch-icon-wrap`/`.lp-ch-dots`-CSS unter `.lp-row` ergänzt.
- `let rolesRegistry = null` + `loadRolesRegistry()` Loader hinzugefügt.
- `loadLaps()` ruft `await loadRolesRegistry()` vor dem `/api/laps`-Fetch.
- Lokale `function chDots(lp)` in `loadLaps()` eingebaut, rendert
  `<span class="lp-ch-icon-wrap {on|off}" title="LABEL">{role.icon}</span>`
  pro Registry-Eintrag.
- `${chDots(lp)}` in den SESSION-Meta-Block der Row eingebaut.

**Teil 2: `report.py` Compare-Picker fixen** (identische Änderungen)

**Teil 3: Tote Dateien entfernt**
- `webapp/analyze.html` und `webapp/upload.html` gelöscht. Keinerlei
  Code referenziert sie. Damit ist die Verwirrung weg.

**Teil 4: Regressions-Test**
- `tests/test_picker_icons_wired.py` NEU (17 Assertions):
  Lädt `/analyze`, `/compare`, `/coach`, `/sessions` als eingeloggter
  Admin und prüft je, dass CSS-Wrapper (`.lp-ch-icon-wrap` oder
  `.ch-icon-wrap`), `loadRolesRegistry`, `function chDots` und
  `role.icon` im gerenderten HTML stehen.
- **Genau diese Fehlerklasse** ("Icons in falscher Datei eingebaut")
  fängt der Test ab — beim nächsten Mal kein 2-Runden-Bug mehr.

**Teil 5: Kommentar in `role_icons.py` korrigiert**
- Liste der Konsumenten zeigt jetzt die echten Dateien
  (`report_single.py`, `report.py`) statt der toten HTML-Dateien.

**Teil 6: VERSION-Bump auf v22.5**

**Tests:** alle bestehenden grün + 17 neue → **494 grün** (vorher 477).

[NOTE] Lehre für künftige UI-Änderungen: **vor** dem Code-Edit prüfen,
ob die Datei tatsächlich vom Server ausgeliefert wird:
`grep -n "webapp/<datei>" *.py` muss mindestens einen Treffer haben.
Bei UI-Templates die in Python-Strings leben (`_PAGE_TEMPLATE`,
`_TEMPLATE`), gibt's keine separate HTML-Datei — `grep "loadLaps\|api/laps"
*.py` zeigt zuverlässig wo die echte Quelle ist.

### v22.6 — Standardkanal/Datenkanal-Terminologie + Bulk-Migrations-Skript

[DECISION] Stefan: "Ab sofort nennen wir den Kanal in der Analyse immer
'Standardkanal' und die Kanäle in den Runden 'Datenkanal'." Plus:
neue Mapping-Datei `parsers/channel_map.txt` ist die Wahrheit für die
`pattern_hints` (vorher: regex-Heuristik in `channel_roles.py`
hardcoded). Plus: Bulk-Migration-Skript für bestehende Laps.

[DECISION] Rename nur in der UI (User-sichtbare Strings). Interne
IDs (`role_id`, `channel_roles`-Dict-Keys, DB-Spalten) bleiben gleich —
Backward-Kompatibilität für Pickle-Blobs, Tests und persistierte Daten.

[DECISION] Bestehende Zuordnungen werden **respektiert** — das Skript
füllt nur leere Slots. Stefan-manuelle Edits oder bereits funktionierende
Upload-Suggestions bleiben unangetastet.

**Teil 1: `parsers/channel_map.txt`** (neue Datei, vom User gepflegt)
- TSV-Format: `Standardkanal\tDatenkanal1, Datenkanal2, ...` pro Zeile.
- Header-Zeile (`Standardkanal\tDatenkanal`) wird übersprungen.
- 8 Zeilen für die 8 existierenden Rollen.
- Stefan editiert nur diese Datei wenn neue Channel-Namen aus
  Datenquellen auftauchen — kein Python-Edit mehr nötig.

**Teil 2: `parsers/channel_roles.py` erweitert**
- `parse_channel_map(text) -> Dict[str, List[str]]`: defensiv geparst
  (Tabs, Multi-Space, BOM, Trailing-Komma, Blanks).
- `STANDARDKANAL_TO_ROLE_ID`: Mapping Deutsch-Label → role_id.
- `_apply_channel_map_to_roles(mapping)`: überschreibt `pattern_hints`
  jeder Rolle mit `^name$` (re.escape, case-insensitive via IGNORECASE
  in `suggest_channel`).
- Beim Modul-Import wird die Datei einmalig geladen + angewendet.
  Fehlt die Datei oder Parse-Fehler: still bleiben, Fallback auf
  hardcoded `pattern_hints` in `ROLES`. `CHANNEL_MAP` ist dann `{}`.
- Pattern-Semantik geändert: exakt+case-insensitiv (vorher Regex-
  Substring). Liefert klarere Vorhersagen für vom User gepflegte Liste.

**Teil 3: Neues Bulk-Skript `assign_channels.py`**
- Analog zu `reparse_laps.py`: `--data /path --dry-run` default,
  `--apply` schreibt, `--only-lap-id N` für Debugging, `--verbose`.
- Helper `build_lookup_table(channel_map)` → flat list `(name_lower,
  role_id, original_name)` in Datei-Reihenfolge.
- Helper `find_matches(extras, lookup)` → `{role_id: channel_id}`,
  case-insensitiver Exakt-Match auf `name`-Feld, First-In-File-Order
  gewinnt bei mehreren Matches.
- Main-Loop iteriert `db.list_all_laps_flat()`, lädt jedes Lap-Blob,
  merged nur leere Slots (respect existing), schreibt zurück via
  `db.update_lap_blob`.
- Idempotent — zweites Apply ändert nichts.
- Report-Output: zeigt pro Lap was hinzugefügt würde, am Ende Summe.

**Teil 4: UI-Terminologie-Rename**
- `KANAL-ZUORDNUNG` → `STANDARDKANAL-ZUORDNUNG` (Coach 3 Stellen,
  Upload-Page, Sessions-Edit-Modal)
- `Zusatz-Kanäle` → `Datenkanäle` (Hilfetexte beim Upload + Modal)
- "Klick oben auf die Rolle und wähle den passenden Kanal aus" →
  "Klick oben auf den Standardkanal und wähle den passenden Datenkanal aus"
- `aria-label="Kanal-Zuordnung"` → `aria-label="Standardkanal-Zuordnung"`
- Interne Kommentare/Code-Identifier (`channel_roles`-Dict,
  `role_id`-Strings) **unangetastet** für Backward-Kompatibilität.

**Teil 5: Stefan's neue Pattern-Werte semantisch ≠ alte Hardcodes**
- `tpd` ist jetzt **Gasgriff** (war Drosselklappe) — Stefan bestätigt.
- `tp_2` ist gar nicht mehr in der Datei.
- `DWCwork` ist nicht mehr in WC-Liste (statt: `md_tgt_whly`,
  `Wheely_active`).
- `p_brake_fr` bleibt, dazu kommt `BrakePressureFr`, `Brake_Front`,
  `FBrakeDriverPres`.
- Drei alte Tests in `test_channel_roles.py` und `test_electronics_roles.py`
  und `test_lap_channel_roles_api.py` mussten an die neue Wahrheit
  angepasst werden — keine Funktionsbug, semantisch neue Erwartung.

**Teil 6: VERSION-Bump auf v22.6**

**Tests:**
- `test_channel_map.py` NEU (23 Assertions): parse_channel_map mit
  diversen Format-Varianten, CHANNEL_MAP-Vollständigkeit,
  STANDARDKANAL_TO_ROLE_ID-Konsistenz, pattern_hints sind
  case-insensitiv exakt, kein Substring-Match mehr,
  build_lookup_table preserve-order, find_matches mit
  case-insensitive/file-order/unbekannt/leer.
- `test_assign_channels_script.py` NEU (8 Tests): E2E mit synthetischer
  DB — leerer Lap wird gefüllt, case-insensitive, bestehende Zuordnung
  respektiert, andere Rollen trotzdem gefüllt, kein Match → keine
  Änderung, leere Extras überspringen, Idempotenz, Dry-Run schreibt
  nicht.
- Anpassungen bestehender Tests (3 Stellen) an Stefan's neue Datei-
  Semantik.

**Bedienung der Migration:**
```bash
# Erst Dry-Run um zu sehen was passieren würde
python3 assign_channels.py --data /var/lap_compare

# Dann wirklich migrieren
python3 assign_channels.py --data /var/lap_compare --apply

# Verbose um auch unveränderte Laps zu sehen
python3 assign_channels.py --data /var/lap_compare --apply --verbose

# Einzelnen Lap testen
python3 assign_channels.py --data /var/lap_compare --only-lap-id 42 --apply
```

[NOTE] **Datei-Wartung:** Wenn ein neues Bike-Format oder neue Datenkanal-
Namen aufschlagen, Stefan editiert NUR `parsers/channel_map.txt`. Nach
Server-Restart greift's automatisch für neue Uploads (Suggest) **und**
kann via `assign_channels.py --apply` für bestehende Laps nachgezogen
werden.

[NOTE] **Backward-Kompatibilität:** Falls `parsers/channel_map.txt`
fehlt (z.B. älterer Server-Stand), greifen die hardcoded `pattern_hints`
in der ROLES-Liste als Fallback. Niemand kracht, kein Auto-Suggest geht
verloren.

### v22.7 — Fahrwerks-Setup-Analyse (Block-Erkennung + Federweg-Histogramme)

[DECISION] Stefan: Neue Coach-Analyse für Federweg. Aufbau analog zu
den anderen (Trackmap + Eventliste + Kanal-View). Zwei Pflicht-Standardkanäle
"Federweg Gabel" und "Federweg Federbein". Ein Event-Typ: **auf Block** —
flache Linie am maximalen Federweg mit scharfer Kante davor.

[DECISION] Zwischen Eventliste und Kanal-View ein neuer Abschnitt mit
zwei Histogrammen (Side-by-Side, Gabel | Federbein). Histogramm zeigt
Anteil der Zeit pro Federweg-Geschwindigkeit, symmetrisch um 0 (links
Ausfedern, rechts Einfedern). Achsen-Range auto-skaliert.

[DECISION] Tab-Name "FAHRWERKS-SETUP" (konsistent mit
"ELEKTRONIK-SETUP"). Tab-Icon "↕".

**Teil 1: `parsers/channel_map.txt` + `parsers/channel_roles.py`**
- 2 neue Zeilen in channel_map.txt: `Federweg Gabel` / `Federweg Federbein`.
  Datenkanal-Namen kuratiert von Stefan: für Gabel `s_susp_fr`,
  `ACC_SuspTravel_F`, `SUSF`, `Travel_Front`, `Susp_fr_ddc`; analog für
  Federbein mit `_rr_`/`_R`/`SUSR`/`_Rear`/`_rr_ddc`.
- 2 neue Rollen in ROLES: `suspension_fork`, `suspension_shock`. Beide
  haben `analyses: ["suspension"]` — keine Mehrfachnutzung.
- `ANALYSIS_TAB_IDS` um `"suspension"` erweitert.
- `STANDARDKANAL_TO_ROLE_ID` um die beiden Mappings ergänzt.

**Teil 2: `webapp/role_icons.py`**
- `suspension_fork`: Teleskop-Gabel (Doppelklemmplatte oben + zwei parallele
  Rohre + Achs-Linie unten).
- `suspension_shock`: Federbein (oberes Auge, Dämpferzylinder, Spiralfeder
  als Zickzack, unteres Auge).
- Wie alle Icons currentColor + 14×14 viewBox + class="ch-icon" → grau/grün-
  Logik kommt frei vom Wrapper.

**Teil 3: `coach.py` — neuer Tab + Panel + Analyse-Modul**
- Tab-Button mit `data-an="suspension"` und Label `↕ FAHRWERKS-SETUP`,
  eingefügt nach Elektronik-Tab vor "BALD"-Tabs.
- Panel `panel-suspension`: Slot-Picker (`suspension-slots`), Trackmap
  (`susp-trackmap`), Analyse-Container (`suspension-analysis`),
  **Histogramm-Section** (`susp-hist-section` mit `susp-hist-fork` +
  `susp-hist-shock`), Daten-vs-Distanz-Chart (`css-`-Prefix).
- `channelRoles.SPECS['suspension']` mit beiden Rollen, `state['suspension']
  = {}`, `ROLE_TO_SLOTS` erweitert, `renderTab('suspension')` aufgerufen.
- Neues IIFE `suspensionAnalysis`:
  - **`detectBlock`**: flache Linie wenn (a) Wert ≥ top 1% der Spannweite,
    (b) Werte-Range im Plateau ≤ 0.5% der Spannweite, (c) Plateau ≥ 40ms,
    (d) Anstieg in den 60ms davor ≥ 20% der Spannweite ("scharfe Kante").
    Kleine Lücken bis 20ms werden gemerged.
  - **`travelVelocity`**: zentrale Differenzen `(x[i+1]-x[i-1])/(t[i+1]-t[i-1])`,
    Boundary mit Repeat. Sample-Rate-agnostisch. dt=0-Schutz.
  - **`buildHistogram`**: 41 symmetrische Bins um 0. Range = max(q99.5, 10%
    von absMax) — der safety floor verhindert dass die Skala bei
    fast-konstanten Daten auf Mikrobereiche schrumpft. Werte außerhalb
    Range werden in den Rand-Bin geclamped.
  - **`renderHistogram`**: SVG mit Achsen, Ticks (-range, -range/2, 0,
    +range/2, +range), Mittellinie (gestrichelt) bei v=0. Linke Hälfte
    orange (Ausfedern), rechte grün (Einfedern). Y-Achse in % Zeitanteil.
  - Trackmap mit zwei Event-Farben: Gabel-Block #ff3d3d, Federbein-Block
    #ff9933. Cursor-Sync analog electronicsAnalysis (eigener `__suspBound`-
    Guard).
  - Chart-Marker-Row-Link wie alle anderen Module über
    `window._coachCharts.suspension`.
- MAPVIEW-Toggle und Speed-Chart-SPECS um `wire('susp', suspensionAnalysis)`
  bzw. `{tab: 'suspension', roles: ['suspension_fork', 'suspension_shock'],
  ids: {svg: 'css-svg', ...}}` erweitert.
- CSS: `.susp-trackmap-wrap` in die `[hidden]/head/phase-h`-Listen
  aufgenommen. `.susp-analysis`/`.ba-empty`/`.ba-summary`/`.ba-note-warn`
  in die geteilten Selektoren. Neue Klassen `.susp-event-table` /
  `.susp-event-row.block-fork|.block-shock` analog `.elec-event-*`.
  Neue Histogramm-Klassen `.susp-hist-section/-hint/-grid/-card/-title/
  -svg` + Inner: `.hb-bar-out` (orange), `.hb-bar-in` (grün), `.hb-axis`,
  `.hb-tick`, `.hb-zero-line` (gestrichelt). Responsive: Grid kollabiert
  bei `max-width:780px` auf eine Spalte.

**Teil 4: `webserver.py`**
- VERSION = "v22.7"

**Teil 5: Bugfix beim Histogramm-Outlier-Trimming**
- Beim Schreiben des JS-Tests aufgefallen: `sortedAbs[Math.min(n-1,
  Math.floor(n * 0.995))]` ist bei n=101 = `sortedAbs[100]` = das Maximum
  selbst → keinerlei Trimming. Korrekt: `Math.floor((n-1) * 0.995)` →
  bei n=101 Index 99 = zweitgrößtes. Der safety floor `absMax * 0.1`
  bleibt drin als Schutz gegen Auto-Skala-auf-Mikrobereich bei
  fast-konstanten Daten.

**Teil 6: Tests**
- `tests/test_suspension_roles.py` NEU (26 Assertions): Tab-ID-Präsenz,
  ROLES-Einträge mit korrektem `analyses`-Feld, `roles_for_analyses
  (['suspension'])` liefert genau die zwei erwarteten IDs, Standardkanal-
  Labels in CHANNEL_MAP, `suggest_channel` mit Stefans Datenkanal-Namen
  (`s_susp_fr`/`s_susp_rr`), Aliase aus der gleichen Datei
  (`ACC_SuspTravel_F`/`SUSF`/…), case-insensitive, substring darf NICHT
  matchen (v22.6-Anker-Semantik), no-channels → None.
- `tests/test_suspension_analysis.mjs` NEU (38 Assertions): JS-Test mit
  1:1-Reimplementierung der Algorithmen aus suspensionAnalysis (Pattern
  von test_chart_cursor_sync.mjs übernommen).
  - detectBlock: Input-Validierung, scharf-kantiger Block erkannt, langsames
    Driften ignoriert/akzeptiert, kurze Plateaus (< 40ms) verworfen,
    verrauschtes-aber-flaches Plateau erkannt, mehrere Blöcke sortiert
    zurückgegeben.
  - travelVelocity: Input-Validierung, Linear-Rampe → konstante
    Geschwindigkeit, dt=0-Schutz, Sinus-Bewegung → Peak ≈ A·ω.
  - buildHistogram: Input-Validierung, symmetrische Daten → linke=rechte
    Hälfte, asymmetrische Daten (compression-heavy) → Massenverhältnis
    25:75, Outlier-Trimming via Quantil, alle Samples summieren zu 100%,
    Bin-Layout zusammenhängend ohne Lücken.
- Bestehende Tests die "8 Rollen" oder "5 Tabs" prüfen mussten nichts
  ändern *außer* `test_channel_map.py::test_eight_standardkanäle` (8 →
  10, Methodenname aus Backward-Compat-Gründen unverändert) und
  `test_analysis_tabs.py::expected_tabs` (suspension-Eintrag).
  `test_api_laps_summary.py` und `test_role_icons.py` iterieren über
  ROLES und haben automatisch mitgegrünt. Andere Tests (`test_channel_
  roles.py`, `test_channel_summary.py`, `test_electronics_roles.py`,
  `test_lap_channel_roles_api.py`, `test_assign_channels_script.py`)
  haben ihren Scope auf konkrete Rollen verengt und brauchten nicht
  angepasst zu werden.

[NOTE] Block-Detektor-Schwellen sind absichtlich konservativ — wir wollen
keine False-Positives bei "fast auf Block" oder "Federweg an der oberen
Grenze für ein paar Samples". Falls Stefan in Praxis-Daten feststellt
dass echte Block-Events durchrutschen, kann er die Konstanten in
`detectBlock` justieren: `maxThreshold` (1% Spannweite), `flatTol` (0.5%),
`minSamples` (40ms), `edgeSamples` (60ms), `edgeRiseFrac` (20% Spannweite).

[NOTE] Auto-Skala beim Histogramm: bei sehr unterschiedlichen Federwegs-
Geschwindigkeiten zwischen Gabel und Federbein können die x-Achsen
unterschiedliche Bereiche zeigen. Das ist gewollt — jede Achse zeigt
relativ ihren eigenen 99.5%-Quantilbereich. Für direkten Vergleich der
Geschwindigkeit zwischen den beiden müsste man eine gemeinsame Achse
nehmen; das wäre Teil einer späteren Iteration falls gewünscht.

[NOTE] Die Histogramm-Geschwindigkeit hat die Einheit "Datenkanal-Einheit/s".
Wenn der Federweg in mm geliefert wird, ist die Achse mm/s. Bei % oder
cm würde die Beschriftung "mm/s" technisch nicht stimmen — wir zeigen sie
trotzdem als Label-Text weil mm der mit Abstand häufigste Fall ist. Falls
das stört, kann das Modul später die Channel-Unit übernehmen und im
Label dynamisch einsetzen.

### v22.8 — Fahrwerks-Analyse: Histogramm über Trackmap

[DECISION] Stefan: "Wir verschieben den Histogramm-View über die Trackmap
in der Fahrwerksanalyse."

[DECISION] Konkret: Histogramm-Section steht jetzt direkt nach der
Kanal-Zuordnung, **vor** der Trackmap. Die Event-Liste bleibt unter der
Trackmap weil Marker und Zeilen interaktiv verlinkt sind (setupMarkerRow
Link) — sie müssen nahe beieinander sein.

Neue Reihenfolge im `panel-suspension`:
1. Slot-Picker (Standardkanal-Zuordnung)
2. **Histogramm-Section** ← verschoben hier hoch
3. Trackmap (TRACK · FEDERWEG-EREIGNISSE)
4. Analyse-Container (Summary + Event-Tabelle)
5. Daten-vs-Distanz Chart

**Teil 1: `coach.py`**
- HTML-Block der `<section class="susp-hist-section">` aus seiner alten
  Position (nach `suspension-analysis`) entfernt und vor
  `<div class="susp-trackmap-wrap">` einsortiert.
- Kommentar im HTML aktualisiert: erklärt warum Histogramm oben steht
  (Setup-Eindruck) und Event-Liste unten bleibt (Marker-Row-Verlinkung).
- Keine Logik-Änderung. IDs, CSS-Klassen, JS-Selektoren, render-Aufrufe
  und die `histSection.hidden`-Steuerung im `suspensionAnalysis`-IIFE
  bleiben unverändert.

**Teil 2: `webserver.py`**
- VERSION = "v22.8"

**Teil 3: Tests**
- `test_analysis_tabs.py` erweitert um eine "v22.8 — Suspension panel
  layout order"-Sektion (10 zusätzliche Assertions): findet die fünf
  Anker (Slot-Picker, hist-section, trackmap, analyse-container, chart)
  im Panel-HTML und prüft per Substring-Position dass die Reihenfolge
  korrekt ist. Schützt gegen versehentliches Zurückkippen der Reihenfolge
  bei zukünftigen Edits.

[NOTE] Die Histogramm-Section wird vom `suspensionAnalysis`-Modul mit
`histSection.hidden = false` aktiviert sobald beide Pflicht-Kanäle
zugeordnet sind. Vorher bleibt sie versteckt — der Übergang vom leeren
Picker zur gefüllten Analyse springt also nicht zwischen "Picker
unmittelbar gefolgt von Trackmap" und "Picker → Histogramm → Trackmap"
hin und her, sondern öffnet sich sauber von oben nach unten.

### v22.9 — Fahrwerks-Analyse: Top-Out + Bump-Detektoren

[DECISION] Stefan: Zwei neue Event-Typen in der Fahrwerks-Analyse:
**Top-Out** (Federung komplett ausgefedert) und **Bump** (harter einzelner
Schlag wie Curb-Hit). Beide pro Element separat (Gabel + Federbein).
Bumps werden in allen Streckenbereichen erkannt — auch in Brems- und
Beschleunigungszonen.

[DECISION] Top-Out = Spiegelbild des bestehenden Block-Detektors: flache
Linie am MINIMUM mit steilem ABFALL davor. Gleiche Schwellen wie der
Block-Detektor (1% Spannweite am unteren Band, 0.5% Plateau-Streuung,
40ms Mindestdauer, 60ms Edge-Fenster, 20% Drop-Anforderung).

[DECISION] Bump = einzelner kurzer Geschwindigkeits-Spike (kein
oszillierendes Wellen-Pattern). MAD-basierte Outlier-Schwelle (Median
Absolute Deviation × 6) statt fixer Schwelle, damit der Detektor sich
an die Federweg-Charakteristik der jeweiligen Maschine anpasst. Dazu
ein Safety-Floor von 200 mm/s, sonst würden bei sehr ruhigen Sessions
auch normale Federbewegungen als Bumps gelten. Spike-Dauer max 100ms
(längere Bewegung = gewollte Federung, nicht Schlag). Spikes unter 50ms
Abstand werden zu einem Event gemerged (Curb-Folge ist ein Event).

**Teil 1: `coach.py` — neue Detektor-Funktionen**
- `detectTopout(arr, time)`: spiegelverkehrte Variante von `detectBlock`.
  Liefert `{from, to, minVal, rangeMin, drop}` pro Event.
- `detectBump(velocities, time)`: arbeitet auf der vorberechneten
  Federweg-Geschwindigkeit (nicht auf dem Federweg selbst — wir nutzen
  die Reihe ohnehin schon fürs Histogramm wieder). Liefert
  `{from, to, peakAbs, peakIdx, peakSigned, threshold}`. `peakSigned`
  > 0 = Einfedern, < 0 = Ausfedern in dem Moment.
- `renderInner` ruft `travelVelocity` einmal pro Element auf und
  reicht die Reihe an Histogramm UND Bump-Detektor weiter. 6 Event-Typen
  insgesamt: `block-fork`, `block-shock`, `topping-fork`, `topping-shock`,
  `bump-fork`, `bump-shock`. Alle gemerged, sortiert nach `from`,
  indiziert ab 1.

**Teil 2: `coach.py` — Summary, Counts, Event-Tabelle, Trackmap, Legende**
- Summary-Headline priorisiert nach Severity: Block > Top-Out > Bump.
  Kein Event → "OK — Fahrwerk arbeitet im erwarteten Bereich."
- 6 Count-Spans im Summary, jeder mit eigener Farbe (rot/orange = Block,
  cyan/grün = Top-Out, gelb/lila = Bump; gabel/federbein-Trennung
  konsistent über die Severities).
- `renderEventRow` erweitert um 4 neue `if`-Zweige mit jeweils
  passendem Type-Label (`↓ GABEL TOP-OUT`, `⚡ FEDERBEIN BUMP` etc.),
  setup-spezifischer Beschreibungs-Text (Top-Out → Rebound /
  Vorspannung; Bump → Druckstufe / Highspeed-Compression), und
  Sparkline-Farbe.
- Trackmap-`typeColor`-Map um 4 Einträge erweitert; Event-Trace und
  Marker bekommen die gleichen Farben.
- HTML-Legende der Trackmap-Section um 4 Einträge erweitert (6 Marker
  insgesamt in einer Zeile mit Flex-Wrap).
- CSS: 4 neue `.susp-event-row.<type> .eer-type`-Regeln für die
  Type-Badge-Farbe.

**Teil 3: `webserver.py`**
- VERSION = "v22.9"

**Teil 4: Tests**
- `test_suspension_analysis.mjs` erweitert um 25 Assertions in zwei
  Sektionen:
  - **detectTopout** (15): Input-Validierung, scharf-abfallendes
    Plateau erkannt, kurze Plateaus verworfen, langsamer Abstieg
    crashed nicht, mehrere Top-Outs sortiert zurückgegeben,
    verrauschtes-aber-flaches Plateau erkannt. Eigene `makeTraceTopout`-
    Helper-Funktion (Mirror von `makeTrace`).
  - **detectBump** (10): Input-Validierung, glatte Bewegung → 0 Events,
    einzelner scharfer Spike erkannt, langsame Rampe unter Safety-Floor
    → 0 Events, zwei nahe Spikes (< 50ms) gemerged, asymmetrischer
    Puls hat eindeutiges `peakSigned`-Vorzeichen (Einfedern → +,
    Ausfedern → −).
- Bestehende detectBlock/travelVelocity/buildHistogram-Tests unverändert
  (38 → bleibt unverändert grün).

[NOTE] **Asymmetrische Bumps vs. symmetrische**: Ein physikalischer
Bump (Federweg kurz hoch, dann zurück) hat im Geschwindigkeits-Signal
beide Vorzeichen — erst positiv (Einfedern), dann negativ (Ausfedern).
Der Detektor merged die per `mergeGap` zu einem Event, und `peakSigned`
zeigt dann je nach Floating-Point-Reihenfolge das eine oder andere
Vorzeichen. Das ist okay für UI ("⚡ BUMP"), aber für deterministische
Tests muss man entweder rein einseitige Pulse synthetisieren oder den
absoluten Peak prüfen. Der Test-File macht beides.

[NOTE] **Bump-Schwelle in Bremszonen**: Stefan hat explizit "egal wo"
gewählt. Wenn sich herausstellt dass beim harten Bremsen False-Positives
durch die Last-Welle entstehen (Federweg geht schnell rein → hohe
Geschwindigkeit), können wir in einer Folge-Iteration einen
Bremsdruck-Gate einbauen ("Bump nur wenn Bremsdruck < X bar"). Aktuell
nicht nötig: der `maxDurSamples`-Filter (100ms) wirft Brems-Eintaucher
raus, weil die typisch 200-500ms dauern.

### v22.10 — Detector-Thresholds als externe Konfigurationsdatei

[DECISION] Stefan: "Kannst du bitte für alle Analysen die Thresholds in
einer Konfigurationsdatei ablegen, so dass ich diese selbst einfach
anpassen kann."

[DECISION] Format JSON (analog `config.json`-Pattern), Lage im Repo-Root
(mit-versioniert), Server-Restart greift Änderungen. JS-Detektoren
bekommen die Schwellen ins HTML embedded, damit kein zusätzlicher
HTTP-Roundtrip nötig ist.

[DECISION] Defensive Architektur: alle hardcoded Werte bleiben als
Fallback im JS (`cfg.foo ?? 0.5`) und im Python-Modul (`FALLBACK`-Dict).
Fehlende Datei, malformed JSON, falsche Top-Level-Shape oder Typ-
Mismatch auf einzelnen Keys → Fallback greift. Kein Crash-Pfad.

**Teil 1: `thresholds.json` (Repo-Root, NEU)**
- 7 Sektionen: `brake`, `accel`, `electronics`, `suspension_block`,
  `suspension_topout`, `suspension_bump`, `suspension_histogram`.
- Jeder numerische Schwellwert hat einen `_<key>`-Kommentar daneben
  ("Bremsdruck > X * peakAll = innerhalb einer Bremszone"). Stefan
  editiert direkt im Klartext.
- Convention: Keys ohne führendes `_` sind echte Werte, Keys mit `_`
  sind Dokumentation und werden vor Auslieferung an den Browser
  gestrippt.

**Teil 2: `thresholds.py` (Repo-Root, NEU)**
- Modul-Loader analog zu `parsers/channel_roles.py`. Beim Import wird
  die JSON-Datei geladen und mit `FALLBACK` gemerged.
- `FALLBACK: Dict[str, Dict[str, Any]]` enthält die Defaults
  byte-identisch zur JSON. Wenn ein Default in der JSON geändert wird,
  muss auch FALLBACK angepasst werden (sonst driften "Datei da" und
  "Datei fehlt" auseinander — der Test `test_file_values_match_fallback_
  for_known_keys` fängt das ab).
- `merge_with_fallback(loaded, fallback)`: per Sektion und per Key.
  Forward-kompatibel: extra Keys und extra Sektionen in der JSON werden
  durchgereicht (User kann neue Schwellen definieren bevor das Modul
  davon weiß). Type-Mismatch auf einem Leaf → Fallback (gegen
  versehentliche Tippfehler in der JSON wie String statt Zahl).
- Python-Quirk: `bool` is-a `int`. `_types_compatible` weist Bool
  explizit zurück, damit `"x": true` nicht als legaler `1`-Wert
  durchgeht.
- `strip_comments(node)` entfernt `_`-Keys rekursiv. Wird vor dem
  Versenden an den Browser angewendet.
- `load(path)` ist best-effort: `FileNotFoundError`, `JSONDecodeError`,
  `OSError` → `_deepcopy(FALLBACK)`. Niemals Exception nach außen.
- `get_thresholds()` ist die public API für `webserver.py`/`coach.py`:
  liefert die geladenen + komment-bereinigten Daten.

**Teil 3: `coach.py` — Detektoren konsumieren THRESHOLDS**
- `build_coach_html` und `build_coach_empty_html` embedden via
  `{{THRESHOLDS_JSON}}`-Placeholder den Loader-Output als
  `const THRESHOLDS = {...}; window.THRESHOLDS = THRESHOLDS;` direkt
  ins HTML, neben `{{DATA_JSON}}`.
- Detektoren lesen ihre Schwellen oben in der Funktion mit dem
  `cfg = (window.THRESHOLDS && window.THRESHOLDS.SECTION) || {};`-
  Pattern, dann `const x = cfg.key ?? FALLBACK_VALUE`. Beide Schichten
  Fallback (window.THRESHOLDS undefined und section-key missing) sind
  abgedeckt.
- Konsumierte Sektionen: `brake` (8 Detektor-Submodule), `accel`
  (Phase-Detection, Smooth, Straight, Error-Marker), `electronics`
  (Slip, Spike, Oszillation, TC/WC-Status), `suspension_block` /
  `suspension_topout` (Plateau-Schwellen + Edge-Fenster),
  `suspension_bump` (MAD-Faktor, Safety-Floor, MaxDur, MergeGap),
  `suspension_histogram` (Bins, Outlier-Quantil, Safety-Floor).
- KEINE numerischen Magic-Numbers mehr in den Detektoren — jede
  Schwelle wurde in die Config gezogen. (Display-Konstanten wie
  Trackmap-Padding bleiben hardcoded, weil sie nichts mit
  Detektor-Verhalten zu tun haben.)

**Teil 4: `webserver.py`**
- VERSION = "v22.10"
- Keine neue Route nötig: Thresholds werden ins HTML embedded, nicht
  als API ausgeliefert. Vorteil: keine zweite HTTP-Roundtrip im
  Browser, kein Cache-Inkonsistenz-Risiko (HTML und Config sind
  byte-konsistent in einem Response).

**Teil 5: Tests**
- `test_thresholds.py` NEU (21 Tests):
  - `TestShippedFile` (3): geladene Datei enthält alle FALLBACK-
    Sektionen, alle Keys, Werte stimmen byte-exakt.
  - `TestMergeBehaviour` (8): vollständiges Override, fehlende Sektion
    → fallback, fehlender Key → fallback, leere Datei → fallback,
    extra Sektion durchgereicht, extra Key durchgereicht, Typ-Mismatch
    → fallback, int↔float toleriert, bool ≠ int.
  - `TestStripComments` (5): top-level strip, rekursiv, normale Keys
    behalten, Listen-Inhalte rekursiv, Scalar unberührt.
  - `TestLoad` (4): missing file, malformed JSON, non-dict top-level,
    partielle Datei merged korrekt.
  - `TestGetThresholds` (1): comment-keys gestrippt.
  - `TestCoachIntegration` (2):
    - **`test_no_orphan_cfg_keys`**: scannt das gerenderte HTML nach
      `cfg.NAME ??`-Patterns und prüft dass jeder NAME in einer
      FALLBACK-Sektion existiert. Fängt den silently-wrong-Fall ab,
      wo das JS einen Key liest der nirgendwo in der Config steht
      (dann würde `??` immer greifen und der JSON-Wert hätte keinen
      Effekt).
    - `test_html_contains_thresholds_blob`: Placeholder ersetzt,
      `const THRESHOLDS` + `window.THRESHOLDS` im HTML.

[NOTE] **Bedienung der Konfiguration:**
```bash
# Datei editieren (im Repo-Root, neben webserver.py)
vim thresholds.json

# Server neustarten — der Loader liest beim Import
sudo systemctl restart lap_compare
# bzw. lokal: Ctrl-C + Neustart
```
Falsche Eingabe (z.B. String statt Zahl, fehlende Sektion, defektes
JSON) → der Loader greift auf Fallback zurück. Es gibt keine "still
borked"-Pfade — entweder die Eingabe wird übernommen oder der
Default greift.

[NOTE] **Drift-Schutz**: Die FALLBACK-Werte in `thresholds.py` MÜSSEN
byte-identisch zur JSON sein, sonst tickt das System je nach "Datei da
oder fehlt"-Status unterschiedlich. Der Test
`TestShippedFile::test_file_values_match_fallback_for_known_keys`
fängt das ab — wer einen Default in der JSON ändert ohne FALLBACK
anzupassen, kriegt einen sofortigen Testfehler.

[NOTE] **Forward-Kompatibilität**: `merge_with_fallback` behält extra
Sektionen und extra Keys aus der JSON. Stefan kann also neue Schwellen
definieren (z.B. für eine spätere Custom-Analyse) ohne dass thresholds.py
oder coach.py vorab editiert werden müssen. Erst wenn ein JS-Detektor
diesen Key liest und FALLBACK ihn nicht kennt, schlägt
`test_no_orphan_cfg_keys` an — was korrekt ist (FALLBACK soll ja die
Wahrheit darüber sein, was an Schwellen existiert).

### v22.11 — Reverse-IP-Lookup in der Admin-View

[DECISION] Stefan: "Jede Zeile in der Admin-View mit einer IP Adresse
bekommt einen Link, der zu einem reverse-ip lookup führt (nimm einen
freien der Infos über Land und Stadt bietet)." Alle drei Tabs
(Activity/Logins/Uploads), nicht nur Activity — konsistente UI.

[DECISION] Dienst: **ip-api.com** (free, kein API-Key, 45 req/min,
liefert country/region/city/zip/lat/lon/timezone/isp/org/as).
Alternativen ipinfo.io (50k/mo limit, account-gebunden) und
whatismyipaddress.com (alte UI) verworfen.

[DECISION] Server-side Lookup statt clientside `fetch()` aus folgenden
Gründen:
- ip-api.com Free ist **HTTP-only** (HTTPS nur Pro). Browser-Fetch von
  einer HTTPS-Admin-Seite würde mixed-content-block triggern.
- Admin-Gating: würde der Browser direkt rufen, könnte jeder mit der
  Server-URL den Endpoint als offenen Proxy missbrauchen und das
  45/min-Limit verbrennen. Server-side mit `_current_user()` Check
  verhindert das.
- Kein Drittanbieter-JS in der Admin-Seite, kein Referrer-Leak.

**Teil 1: Modul-Level Helper (`webserver.py`)**
- `is_private_or_loopback_ip(ip)` — True für loopback/private/link-local/
  reserved/multicast/unspecified. Loopback+RFC1918 sind die häufigen,
  der Rest aus Vollständigkeit (z.B. 169.254.x bei DHCP-Failures).
- `is_valid_public_ip(ip)` — syntaktisch gültige IP **und** nicht
  privat. Gate vor dem Upstream-Call.
- `fetch_ip_geo(ip, timeout=4.0)` — `urllib.request.urlopen` gegen
  `http://ip-api.com/json/<ip>?fields=status,message,country,...`.
  **Alle** Exceptions (`URLError`, `OSError`, `TimeoutError`,
  `ValueError`, `JSONDecodeError`) werden gefangen und zu
  `{"status":"error","message":<str>}` umgewandelt — der Caller darf
  nie eine Exception sehen. 4s Timeout, sonst hängt der Endpoint bei
  Netz-Ausfall ewig.
- `render_ip_cell(ip)` — **Single Source of Truth** für die `.col-ip`-
  Zelle. Empty → '—', private → bare text + `(lokal)` Marker (kein
  Link), invalid → bare HTML-escaped text, public → `<a class="ip-link"
  target="_blank" rel="noopener" href="/admin/ip-lookup?ip=<url-enc>">`.
  IPv6-Doppelpunkte werden per `quote(ip, safe="")` URL-encodiert
  (sonst zerlegen manche Proxies die Query-Strings).

**Teil 2: Drei Render-Stellen ersetzt**
- Logins-Tab (`_page_admin_artefacts`, line ~2540): `ip_display = render_ip_cell(ev["ip_address"] or "")`
- Uploads-Tab (~2570): identisch
- Activity-Tab (~2638): identisch — `ip_display` Variable bleibt der
  HTML-Snippet, der in `{ip_display}` der f-string-Row eingesetzt wird.
  Keine andere Änderung an der Row-Struktur nötig.

**Teil 3: Endpoint `/admin/ip-lookup?ip=<ip>`**
- Routing in URL-Dispatcher direkt nach `/admin/event/<id>/file`.
- `_handle_admin_ip_lookup(qs)`:
  - Auth: nicht-eingeloggt → 303 zur Login. Eingeloggt-aber-nicht-admin
    → 404 (so wie alle anderen admin-Endpoints, leakt keine Existenz).
    `debuglog.log("action.admin.ip_lookup.denied", reason="not_admin")`.
  - Input-Validierung: `ip` fehlt → 400 "Parameter 'ip' fehlt".
    `len(ip) > 64` → 400 (defence gegen forged absurd-lange Werte).
    `ipaddress.ip_address(ip)` raised → 400 "Ungültige IP-Adresse".
  - Loopback/Private → `geo = {"status": "local"}`, kein Upstream-Call.
  - Sonst `fetch_ip_geo(ip)` → vier Branches in `_render_ip_lookup_page`:
    - **local**: "Lokale / private Adresse" + Hinweis "RFC 1918 /
      Loopback / Link-Local. Geo-Lookup nicht möglich".
    - **success**: 9 Zeilen Land/Region/Stadt/Koordinaten/Zeitzone/
      ISP/Org/AS/Karte (OpenStreetMap-Link mit `mlat/mlon` und
      `#map=10/lat/lon`-Zoom). Fehlende Felder → '—' Placeholder.
    - **fail**: "Lookup fehlgeschlagen" + `message` aus der Response
      ("reserved range" o.ä.).
    - **error**: "Netzwerk-/Parse-Fehler" + Detail.
- Render-Page in eigener Methode `_render_ip_lookup_page(ip, geo)` —
  inline-CSS, gleiche Farb-Palette wie admin.html (`--bg`, `--bg-2`,
  `--ink`, `--accent`, `--fail`). Keine JS-Logik. Footer hat einen
  "Tab schließen ×" Link (`javascript:window.close()`), weil die
  Seite per `target="_blank"` geöffnet wird.
- `debuglog.log("action.admin.ip_lookup.ok", lookup_ip=ip, result=…)`
  loggt jeden erfolgreichen Aufruf inkl. Upstream-Status.

**Teil 4: CSS (`webapp/admin.html`)**
- `.event-row .col-ip a.ip-link` — `color:inherit`, `text-decoration:none`,
  `border-bottom:1px dotted var(--ink-faint)`. Subtle by default; die
  IP sieht aus wie normal Text, nur der dotted underline verrät den
  Link. Hover → `color:var(--accent)`, durchgängige Border-Farbe.
  Passt zur etablierten "dunkle Borders für inaktive Elemente,
  hellere für aktive" Konvention.

**Teil 5: Tests (`tests/test_ip_lookup.py`, 28 grün)**
- `TestPrivateLoopbackClassification` (7): loopback v4/v6, RFC1918
  (alle 3 Bereiche), link-local, public v4 (8.8.8.8, 1.1.1.1), public
  v6 (Cloudflare), invalid input (empty, "not-an-ip", "999.999.999.999"),
  `is_valid_public_ip` true/false-Pfade.
- `TestRenderIpCell` (8): empty → '—' kein Link, private → bare +
  '(lokal)', loopback → bare + '(lokal)', public → `<a class="ip-link"
  target="_blank" rel="noopener">` mit korrektem href, IPv6 →
  Doppelpunkte als `%3A` URL-encodiert, invalid → plain text kein Link,
  XSS-Defense (HTML-escape auf invalid input).
- `TestFetchIpGeo` (6): success-Response, upstream-fail-status
  (durchgereicht), `URLError` → status=error (nicht raise),
  Parse-Error → status=error, non-dict-Response (Array statt Object)
  → status=error, `timeout`-kwarg wird tatsächlich an `urlopen`
  weitergegeben (sonst hängt der Endpoint bei Netzausfall ewig).
  `urllib.request.urlopen` wird gestubbed → Tests laufen offline,
  verbrennen keine ip-api.com-Quota.
- `TestRenderIpLookupPage` (6): local-Branch, success-Branch mit allen
  Feldern, success-ohne-Koordinaten (kein OSM-Link, kein Crash),
  fail-Branch zeigt `message`, error-Branch zeigt Detail, XSS-Defense
  im H1 (`<script>` wird zu `&lt;script&gt;`).

**Manueller E2E-Smoketest verifiziert:**
- 8.8.8.8 (public) → Link mit href=/admin/ip-lookup?ip=8.8.8.8
- 127.0.0.1 (loopback) → bare text + (lokal)
- 192.168.1.42 (RFC1918) → bare text + (lokal)
- 2606:4700:4700::1111 (IPv6 public) → Link, Doppelpunkte %3A-encoded
- /admin/ip-lookup?ip=192.168.1.1 → "Lokale" Seite (kein Upstream-Call)
- /admin/ip-lookup?ip=garbage → HTTP 400
- /admin/ip-lookup ohne ip-Param → HTTP 400
- /admin/ip-lookup als anonymer User → HTTP 303 (redirect zur Login)
- Activity/Logins/Uploads-Tab: alle drei rendern die Links konsistent.

[NOTE] **Rate-Limit-Strategie**: ip-api.com Free erlaubt 45 Requests
pro Minute pro Source-IP. Da der Lookup nur on-demand per Klick
passiert (nicht im Render-Loop), ist das in der Praxis irrelevant
— selbst bei einem Admin der durchklickt sind das vielleicht 10
Aufrufe in einer Session. Falls jemals nötig, wäre ein 5-Minuten-
Cache (`{ip: (geo, ts)}` im AppState) eine einfache Erweiterung,
aber für v22.11 YAGNI.

[NOTE] **Kein Caching der Geo-Daten**: jeder Klick ruft frisch ab.
Vorteil: ISP/Org-Wechsel werden sofort sichtbar (z.B. Mobil-IPs).
Nachteil: bei wiederholtem Klick auf dieselbe IP 1-2s Latenz pro
Aufruf. Vertretbar weil interaktiv vom Admin getriggert, nicht im
Render-Pfad der Listen.

### v22.12 — Profilverwaltung (Fahrer + Motorräder)

[DECISION] Stefan: Neues Modul **Profilverwaltung** für eingeloggte
User. Fahrername + n Motorräder (jeweils Name + optionales Bild, eines
"aktuell"). Beim Upload werden Driver + aktuelles Bike als Defaults in
Step 1 eingesetzt. Profile-Tile auf der Landing, PROFIL im Header,
Link "Eigene Runden" auf der Profilseite filtert die Rundenliste auf
`owner=user_id`.

[DECISION] Drei UI-/Storage-Fragen vorab geklärt:
- **Fahrerbild ja oder nein**: ja (zusätzlich zu Bike-Bildern).
- **"Eigene Runden"-Filter**: per `user_id` (echte Ownership, präzise) —
  NICHT Fahrernamen-Match. Alte verwaiste Uploads ohne user_id matchen
  bewusst nicht; die sind eh nur über Admin bearbeitbar.
- **Bilder-Storage**: auf Disk unter `<data_dir>/profile_images/`,
  DB hält nur den Dateinamen. UUID-Schema sowohl als Dedup-Schutz als
  auch als Path-Traversal-Hardening (read-path validiert Regex).

**Teil 1: DB-Schema (`db.py`)**

Zwei neue Tabellen, beide via `CREATE TABLE IF NOT EXISTS` migrationsfrei:
```sql
profiles (user_id PK, driver_name, image_path, created_at, updated_at)
bikes    (id PK, user_id FK, name, image_path, is_current, created_at)
```
- 1:1 für `profiles` (PK = FK auf users), `ON DELETE CASCADE`.
- `bikes`: n:1, `idx_bikes_user`, "highchanger one bike is current" als
  Convention (kein partial unique index — SQLite bräuchte dafür NULLs;
  die Convention wird in `set_current_bike` enforced via UPDATE).
- `get_profile()` liefert immer ein dict (synthetisch leer für nie-
  gespeichert) — Callers haben keinen None-Branch.
- `add_bike()`: erstes Bike wird automatisch current, auch wenn der
  User die Checkbox nicht gesetzt hat. Sonst hätte ein neuer User
  in der Upload-Pre-Fill leeres Bike-Feld.
- `delete_bike()`: wenn das current war und andere bleiben, promotiet
  das jüngste verbleibende zum current. Returns image_path zur Cleanup.
- Owner-Checks (`update_bike`, `delete_bike`, `set_current_bike`) prüfen
  `user_id` aus der Row gegen den Caller-`user_id` — kein Auth auf
  HTTP-Layer allein, Defense in Depth.

**Teil 2: Image-Storage (`webserver.py`)**

- `PROFILE_IMAGE_EXTS = {.jpg, .jpeg, .png, .webp}` — GIF/SVG bewusst
  raus (SVG: XSS-Risiko; GIF: überflüssig).
- `PROFILE_IMAGE_MAX_BYTES = 5 MB` (Profilbilder sind klein, nicht
  Telemetrie).
- `save_profile_image(data, original_filename)`: validiert + speichert
  als `<uuid>.<ext>`, normalisiert `.jpeg → .jpg`. Filename-only zurück.
- `delete_profile_image(filename)`: still-safe (gibt False zurück bei
  ungültig/missing). Validiert Filename gegen `_PROFILE_IMG_NAME_RE`
  vor jedem Disk-Touch.
- `_PROFILE_IMG_NAME_RE`: strikter Regex `^<uuid>\.(jpg|png|webp)$`.
  Read-path (Serve + Delete) checkt das **zusätzlich** zu `_path_is_inside`,
  weil das Schema Garbage-Input frühzeitig ablehnt ohne Disk-IO.

**Teil 3: HTTP-Endpoints**

Routes (GET/POST):
```
GET  /profile                       Seite (anon → 303 /login?next=/profile)
GET  /profile/image/<filename>      öffentlich (UUID-Regex match Pflicht)
POST /profile/save                  Fahrername + optionales Foto
POST /profile/bike/add              Neues Bike
POST /profile/bike/<id>/edit        Name und/oder Bild
POST /profile/bike/<id>/delete
POST /profile/bike/<id>/set-current
```
Alle POST-Handler:
- Anon → 303 nach `/login?next=/profile`
- Bei Foreign-Bike (Owner-Check failed): `denied` + reason in Logs,
  Redirect auf `/profile?error=...` (niemals 403, würde nur den User
  verwirren — kann eh nichts Schlimmes anrichten).
- `parse_multipart` für alle (auch ohne File-Upload), wegen
  einheitlichem Error-Handling.
- File-Field leer = "Bild nicht ändern" (None), gefüllt = ersetzen.
  Bei Erfolg wird das alte Bild auf Disk geräumt (idempotent, errors
  swallowed).

Logging-Konvention v22.1 strikt eingehalten:
- `action.profile.save.{ok,error}`
- `action.profile.bike.add.{ok,error}`
- `action.profile.bike.edit.{ok,denied}` mit `reason=notfound|not_owner`
- `action.profile.bike.delete.{ok,denied}`
- `action.profile.bike.set_current.{ok,denied}`

**Teil 4: Pre-Fill der Upload-Maske**

`_page_session_upload_form` zieht jetzt Profil + Current-Bike beim
Render-Time aus der DB und setzt sie als `value=` in die Inputs. Wenn
ein Default da ist, kommt eine `✓ Aus Profil vorbelegt`-Hint dazu
(akzent-cyan, dezent — nicht raus-knallend wie der `_hint()` für
auto-extract aus der Datei in Step 2).

Priorität in `step1_upload_session` bleibt unverändert
(form-value > auto-extract). Der User-typed-blank lässt also weiterhin
auf auto-extract fallen — kein server-side Profil-Fallback, weil das
gegen das "user cleared = user meant blank"-Prinzip verstösst.

**Teil 5: Landing-Page + Header**

- `landing.html`: PROFIL-Tile mit `accent-2` (`#c77dff`, Lila) zwischen
  VERGLEICHEN und ADMIN_CARD-Slot. Tile-Geometrie etwas flacher pro
  Stefans Wunsch: `min-height 200→130px`, `gap 20→16`, `padding
  32/28→20/22`, `font-size 36/14→28/13` — alle Werte konservativ, das
  Layout bleibt visuell konsistent, scroll-Last reduziert.
- `build_header_html`: PROFIL-Link **immer** sichtbar (auch anon),
  weil Stefans Spec sagt "Link/Kacheln sind immer sichtbar aber wenn
  nicht eingeloggt weiterleitung auf login". Der Redirect kommt vom
  `_page_profile`-Handler, nicht vom Header.
- Active-Marker: PROFIL wird highlighted wenn `current_path` mit
  `/profile` startet.

**Teil 6: "Eigene Runden"-Filter (`sessions.html`)**

Mine-Filter komplett clientseitig — passt zur existierenden Architektur
(Filter ist JS auf gerenderten Rows, kein Round-Trip pro Filter-Change).
Server-side:
- `_page_sessions_list` liest `?mine=1` und zusammen mit dem aktuellen
  `user_id` rendert es drei `data-*`-Attribute auf `.filter-bar`:
  `data-logged-in`, `data-cur-user-id`, `data-mine-default`.
- Anonyme User: `data-logged-in="0"` → CSS-Regel `.filter-bar[data-logged-in="0"] .mine-toggle{display:none}`. Stefans Spec ("Link immer
  sichtbar, Redirect"): hier ist der Toggle versteckt weil ohne
  user_id gar kein Filter-Kriterium da ist; der direkte
  `/sessions?mine=1`-Aufruf wird vom Server lautlos ignoriert (kein
  Redirect — die Rundenliste IST ohne Login lesbar).
- Jede Row trägt jetzt `data-user-id` (leer für verwaiste Sessions).

Clientseitig: `applyFilter()` erweitert um Mine-Bedingung, Initial-Pass
wird beim Page-Load ausgeführt damit der mine=1-Default schon greift.
URL-Sync via `history.replaceState` (nicht `pushState` — sonst sammeln
sich Filter-Toggle-Einträge im Back-Stack an).

**Teil 7: Useradmin-Hygiene**

`useradmin.py delete` räumt jetzt Profil- und Bike-Bilder auf Disk vor
dem DB-Cascade-Delete: erst Filenames sammeln, dann `delete_user()`,
dann `unlink()`. Reihenfolge wichtig: bei DB-Crash dazwischen sind die
Bilder noch da (referenziert von der noch-existierenden Row); kein
Orphan-Risiko.

**Tests:** `tests/test_profile.py` — 54 grün:
- `TestProfileCRUD` (15): Empty-Profile, Upsert/Update/Image-None,
  First-Bike-Forced-Current, At-Most-One-Current, Owner-Checks für
  set/update/delete, Promotion-on-Delete-of-Current, Cascade-Delete
  mit User.
- `TestImageHelpers` (15): JPG/JPEG-Normalisierung, PNG/WEBP-Ext,
  Reject von .gif/.svg/noext/empty/oversize, Unique-Filenames-
  Even-Same-Input, Delete-Existing/Missing/Empty/Traversal,
  Regex-Strict gegen Garbage-Input.
- `TestProfileEndpoints` (12): Anon-Redirect, Logged-In-Renders,
  Save-Driver-Name, Save-Image, Bike-Add-with-Image, Empty-Name-
  Error, Owner-Gate-bei-Fremd-Bike, Anon-POST-Redirect, Serve-
  Image-Public, Invalid-Filename-404, Path-Traversal-404,
  Unknown-UUID-404.
- `TestProfileIntegration` (8): Upload-Form-empty-Profile-no-Prefill,
  Upload-Form-prefills-Driver-and-Current-Bike, Upload-Form-uses-
  Current-Bike-after-Switch, Sessions-Liste-data-Attrs, Mine-Param-
  setzt-Default, Anon-ignoriert-Mine-Param, Landing-hat-Profile-
  Tile, Landing-Tile-flatter (min-height-Regression).
- `TestProfileLinkInHeader` (4): Anon-Header, User-Header, Active-on-
  Profile-Path, Inactive-on-other-Path.

**E2E verifiziert:**
- Anonymer Klick auf PROFIL im Header / auf der Landing → 303 zur
  Login-Seite mit `next=/profile`.
- Login + /profile zeigt Fahrer-Card + leere Bike-Liste mit
  Empty-State.
- "Stefan Müller" als Driver + 2 Bikes ("CBR 1000 RR", "R6") angelegt,
  CBR auto-current → Upload-Form: `value="Stefan Müller"` +
  `value="CBR 1000 RR"` + "✓ Aus Profil vorbelegt"-Hint.
- Switch current auf R6 → Upload-Form pre-fillt jetzt "R6".
- Bild-Upload (PNG) auf Bike-Edit → File landet in
  `profile_images/<uuid>.png`, `/profile/image/<uuid>.png` rendert
  korrekt mit `Content-Type: image/png`, anonymer Zugriff geht durch.
- `/profile/image/../sessions.db` → 404 (Regex-Mismatch im Router).
- `/sessions?mine=1` als anon: `data-mine-default=""` (ignoriert).
  Als Logged-In: `data-mine-default="1"`, Checkbox initial gesetzt,
  Liste sofort gefiltert.
- `useradmin.py delete a@x.de -y` mit 2 Bildern → DB-Row + 2 Files
  weg, Output "2/2 Profil-/Bike-Bild(er) entfernt."

[NOTE] **Warum Mine-Filter clientseitig** statt einer
`/api/laps?owner=me`-Erweiterung: die Sessions-Liste ist
server-rendered und der Filter ist von Anfang an JS-only. Eine
zweite Code-Path würde nur Komplexität bringen. Performance ist
unkritisch — die Liste wird sowieso komplett geladen, Filter ist
nur Display-Toggle.

[NOTE] **Warum keine Profile-Page mit edit-modal** wie bei Sessions:
zu viel auf einer Seite. Stefan-Stil bevorzugt direktes Editieren mit
sichtbaren Inputs. Bike-Edit ist daher inline in jeder Card (Name +
Image-Input + Submit nebeneinander); Add ist ein separates kleineres
Form unter der Bike-Liste.

[NOTE] **Tile-Geometrie als Regression-Test** (`test_landing_tile_
flatter`): der Stefan-Wunsch "flacher" ist subjektiv, aber ich habe
`min-height:130px` als konkreten Wert eingebaut und ein
assertIn/assertNotIn auf den HTML-Output — wenn jemand das Layout in
v22.13 wieder höher dreht ohne den Test anzupassen, fällt's auf.

### v23.0 — Klickbare Owner-Profile (read-only)

[DECISION] Stefan: Major-Bump auf **v23.0** — User (eingeloggt oder
nicht) können in der Auswahl von Runden auf den Usernamen des
Besitzers klicken und sehen dessen Profilseite **read-only**.

[DECISION] Drei UI-Entscheidungen im Vorhinein getroffen statt
nachzufragen (alle drei sind aus Stefans bisherigem Stil ableitbar):
- **404 bei unbekanntem User** (kein Redirect zu Login), weil die Seite
  selbst kein-Login-Pfad ist — ein Redirect würde Anon nur verwirren.
- **Privacy: E-Mail-Adresse wird nicht angezeigt**. Display-Name ist
  primär der `driver_name`; fehlt der, fallen wir auf den Local-Part
  der E-Mail zurück (vor dem `@`) — die Domain bleibt intern. Stefan-
  Stil "UI-Disziplin: keine redundante Information" passt hier perfekt:
  Owner-Link in der Rundenliste zeigt die E-Mail (wer eingeloggt ist
  sieht das eh), aber das öffentliche Profil dahinter ist
  pseudonymisiert.
- **Self-Hint-Banner** für den eingeloggten Owner, der sein eigenes
  öffentliches Profil anschaut — kleine Cyan-Box oben mit Link
  "→ EIGENES PROFIL EDITIEREN". Verhindert die Verwirrung "warum kann
  ich hier nichts editieren". Stefan-Stil: explizit > implizit.

**Teil 1: Neue Route `GET /profile/<user_id>` (`webserver.py`)**

Router-Ordnung wichtig: `/profile/image/<filename>` kommt **vor**
`/profile/<id>`, weil das Image-Regex Punkte erlaubt und reine Ziffern
nicht matched — so landet `/profile/42` immer beim User-Handler.
404 vom Router fallthrough bei `/profile/abc`, `/profile/-1`.

`_page_public_profile(target_user_id)`:
- `db.get_user(id)` → None → HTTP 404
- Display-Name: `driver_name` oder Local-Part der E-Mail
- Lap-Count: `list_all_laps_flat()` mit user_id-Match
- `is_self` Branch: aktueller Viewer hat dieselbe `user_id`
- Bikes: read-only Cards mit Aktuell-Badge (lila), keine Edit-Forms
- Runden-Link unten:
  - Self → `/sessions?mine=1` (v22.12-Filter)
  - Fremd + driver_name gesetzt → `/sessions?driver=<name>` (v22.2
    case-insensitive Filter greift)
  - Fremd ohne driver_name → kein Link, nur Hinweis "Runden nicht
    filterbar"

**Teil 2: Neues Template `webapp/profile_public.html`**

Komplett neue Datei statt einer "edit-Modus weggegated"-Variante des
v22.12-Templates. Begründung: das Edit-Template hat 8+ Forms; jede
einzeln zu gaten wäre fragiler als ein neues schlankes Template. Die
zwei Templates teilen sich `_page_profile`-Optik per copy-paste-CSS —
absichtlich nicht über shared CSS-File, weil sonst Änderungen an einer
Seite die andere ungewollt verschieben würden.

Differenzen zum v22.12 `profile.html`:
- Kein FAHRER-Edit-Form (kein `action="/profile/save"`)
- Keine BIKE-Edit-Inline-Forms (kein `action="/profile/bike/<id>/edit"`)
- Keine Add-Bike-Form unter der Liste
- Kein Delete-/Set-Current-Button pro Bike
- Self-Hint-Banner-Slot oben (`{{SELF_HINT}}`)
- Profile-Card hat zusätzlich Display-Name H1 + Lap-Count-Stats
- Empty-State für Bike-Liste personalisiert ("X hat noch keine
  Motorräder eingetragen")

**Teil 3: Owner-Link in der Rundenliste (`webserver.py` +
`webapp/sessions.html`)**

Rendering in `_page_sessions_list`:
```python
if owner_email and owner_uid is not None:
    owner_display = f'<a href="/profile/{int(owner_uid)}" class="owner-link" ...>{escape(email)}</a>'
elif owner_email:
    owner_display = escape(owner_email)        # Owner deleted, FK SET NULL → kein /profile/<id>-Target
else:
    owner_display = '<span...>(verwaist)</span>'
```
Drei Branches statt zwei: zwischen "verwaist" (gar kein User-FK) und
"E-Mail noch da, User-Record aber weg" liegt der edge-case eines
gelöschten Users (FK ON DELETE SET NULL). Letzteres kommt unverlinkt
raus — sonst würde der Klick ein 404 produzieren.

CSS-Stil dezent (`.owner-link`): inherit-Color (Sub-Text grau), kein
Default-Blau-Link; Underline-on-Hover. Hält die Sessions-Zeilen ruhig.

**Teil 4: Tests (`tests/test_public_profile.py`, 20 grün)**

Drei Test-Klassen:

- `TestPublicProfileRoute` (13): Anon-Render, No-Self-Hint-für-Anon,
  Self-View-zeigt-Hint, Other-User-no-Hint, Unknown-User-404,
  Non-Integer-404 (für `abc` und negative Zahlen),
  Email-not-leaked-when-driver-name-set (Privacy),
  Email-Localpart-Fallback (Privacy), Empty-User-rendert-mit-
  Placeholder, Page-Title-uses-display-name, No-Edit-Forms-Anywhere
  (read-only Garantie via grep auf `action="/profile/save"`),
  Bike-Image-rendert-wenn-vorhanden, Lap-Count-Zero-no-Link,
  XSS-in-Driver-Name-escaped (Defense gegen `<script>`-Payload in
  Fahrername UND Bike-Namen).
- `TestOwnerLinkInSessionsList` (4): Owner-Email-ist-klickbarer-
  Anchor, Orphan-Session-kein-Link (kein `/profile/None` oder
  `/profile/null` Garbage in der URL), Title-Tooltip auf Owner-
  Link, Anon-kann-Owner-Link-folgen (Roundtrip Sessions → Profile).
- `TestRouteDisambiguation` (3): `/profile` ohne id redirected immer
  noch zu Login, `/profile/image/garbage.jpg` gibt 404 vom Image-
  Handler (nicht "User #garbage"), `/profile/1` gibt 200 wenn User
  existiert.

**E2E verifiziert:**
- Anon klickt in `/sessions` auf `stefan@racedat.example` →
  `/profile/1` rendert read-only ohne Login-Redirect.
- Eingeloggter Stefan klickt auf seinen eigenen Link → sieht oben
  Self-Hint-Banner mit "→ EIGENES PROFIL EDITIEREN" zum
  Wechsel auf `/profile` (Edit-Modus).
- User ohne Fahrernamen → Display-Name = E-Mail-Local-Part, volle
  Adresse NICHT im Body (`@example.com` grep schlägt fehl).
- Verwaiste Session (`user_id=NULL`) → "(verwaist)" ohne Link, kein
  `/profile/None`-Garbage in der URL.
- Gelöschter User mit `user_email` in events: kommt unverlinkt raus
  (would-be `/profile/<id>` würde 404 geben).
- `<script>alert(1)</script>` als Fahrername → `&lt;script&gt;` im
  Body, kein executable Script.

[NOTE] **Warum nicht das v22.12-Template wiederverwenden** mit
`{{IS_READONLY}}`-Gates: 8 Edit-Forms × jede einzeln gaten = 8 Chancen
für einen Bug. Ein neues Template ist 70 Zeilen HTML mehr aber 100%
explizit. Stefan-Stil "explizit > implizit".

[NOTE] **Self-Hint statt automatischer Redirect zu /profile**: wenn
ein eingeloggter Owner auf seinen eigenen `/profile/<id>`-Link klickt,
könnte der Server ihn auf `/profile` (Edit-Modus) redirecten. Macht
er aber nicht, weil:
  (1) "Sehe wie andere mich sehen" ist ein legitimer Use-Case.
  (2) Stefan-Stil "kein impliziter Redirect bei Information-Pages".
  (3) Der Self-Hint-Banner ist eh sichtbar genug.

[NOTE] **Lap-Count ist O(N_total_laps)** weil `list_all_laps_flat()`
keinen WHERE-Filter hat. Für die jetzige Datenmenge (~hundert Laps)
kein Problem; falls Stefan jemals 100k+ Laps hat: ein
`db.count_laps_by_user(user_id)` mit SQL-COUNT wäre die Erweiterung.
YAGNI für jetzt.

### v23.1 — Bestzeiten pro Strecke + Laps-Link-Bugfix

[DECISION] Stefan: zwei Änderungen in einem Patch.
- **Feature**: Auf der Profilseite (eigene + öffentliche Sicht) für
  jeden User eine Liste der Bestzeiten auf den Strecken anzeigen, für
  die er Runden hochgeladen hat. Sichtbar für alle.
- **Bugfix**: Wenn die Profilseite eines anderen Users angezeigt wird,
  blenden wir den Runden-Selektions-Link ganz aus.

**Teil 1: Neue DB-Methode (`db.py`)**

`best_lap_per_track_for_user(user_id) -> List[{track, duration_s,
lap_id, session_date}]`. Sortiert nach `duration_s` aufsteigend
(schnellste zuerst). Excludes leere Track-Felder.

Track-Bucket-Logik: `LOWER(track)` als Group-Key (case-insensitive,
matched v22.2-Konvention). Display-Name pro Bucket = die früheste
gesehene Schreibweise (gleicher Algorithmus wie `canonical_track_
name()` in v22.2). So bleibt `Aragon` als Anzeige stabil, auch wenn
die schnellste Runde mit `aragon` (lowercase) hochgeladen wurde.

Implementierung in zwei Aggregations-Pässen statt einem big
JOIN-Subquery: SQLite hat kein `FIRST_VALUE()` ohne Window-Functions,
und ein Self-Join mit dreifach genesteten Subqueries war fragiler als
zwei klare Pässe. Performance ist unkritisch — der erste Pass ist ein
einziges `GROUP BY LOWER(track)`, der zweite läuft N-mal für N
Buckets (typisch <10).

Ex-aequo MIN-Times werden deterministisch aufgelöst über `ORDER BY
laps.id ASC LIMIT 1` — die älteste Lap-Row gewinnt.

**Teil 2: Render-Helper (`webserver.py`)**

`render_best_laps_html(best_laps)` — pure function, html-escapes alles
durch, baut entweder ein `.best-laps` Container mit `.bl-row` Anchors
(je `<a href="/analyze?lap_id=X&go=1">`) oder einen Empty-State-
Placeholder. Empty-State ist explizit ein anderer DOM-Knoten als der
Container — das macht den Test einfacher (`assertNotIn 'class=
"best-laps"'`) und das CSS sauberer (kein Container ohne Inhalt).

XSS-safe: alle Track-Namen und Datums-Strings durch `html.escape()`.
Lap-Id ist `int(...)`-coerced → keine Injection im URL-Pfad.

**Teil 3: Wiring in beide Profile-Seiten (`webserver.py`)**

- `_page_profile` (Edit-Modus): `BEST_LAPS_HTML`-Variable in
  `render_template`. Bestzeiten erscheinen unter dem "EIGENE RUNDEN"-
  Quicklink, mit eigener `<h2>BESTZEITEN</h2>` Section.
- `_page_public_profile` (Read-Only): selbe `BEST_LAPS_HTML`-Variable,
  zwischen MOTORRÄDER und `{{LAPS_LINK}}`.

Beide Seiten teilen sich Helper + CSS-Klassen-Namen, **aber** das CSS
ist in beiden HTML-Templates dupliziert (kein shared file). Begründung
identisch zur v23.0-Wahl: Stefan-Stil "zwei kleine Templates
eigenständig statt shared-Dependency die ungewollt mitverschiebt".

**Teil 4: Bugfix Laps-Link in fremder Profilansicht**

Vorher in `_page_public_profile`:
```
if is_self:        → /sessions?mine=1 Link
elif lap_count > 0:
  if driver_q:     → "RUNDEN VON X" Link (/sessions?driver=X)
  else:            → "N HOCHGELADENE RUNDEN" Info-Box
else:              → leer
```

Nachher:
```
if is_self:        → /sessions?mine=1 Link
else:              → leer  (immer, kein Link, keine Info-Box)
```

Begründung: Stefans Spec sagt "Link für Selektion der eigenen Runden
ganz ausblenden bei fremden Profilen". Die vorherige "RUNDEN VON X"-
Variante war konzeptionell ein Selektions-Link, nur mit anderem Filter
— der Bugfix entfernt sie konsequenterweise mit. Die Bestzeiten-
Tabelle (Teil 1-3) übernimmt das Info-Bedürfnis "was hat dieser User
hochgeladen". Click-Through auf die schnellste Runde pro Strecke ist
sogar präziser als der frühere ungefilterte Fahrer-Link.

**Tests:** 26 neu, alle grün. Aufgeteilt auf zwei bestehende Dateien
(keine neue Datei — Bestzeiten gehören thematisch zu Profile-Tests):

- `tests/test_profile.py` +15 in zwei neuen Klassen:
  - `TestBestLapPerTrackDB` (10): unknown-user-empty, user-without-
    laps-empty, one-track-one-lap, picks-fastest-per-track, excludes-
    empty-track, case-insensitive-grouping (Aragon/aragon/ARAGON in
    einem Bucket mit canonical Spelling = first-seen), multiple-tracks-
    sorted-fastest-first, does-not-bleed-across-users (zwei User,
    selber Track, beide Bestzeiten getrennt), returns-lap-id-for-
    click-through, includes-session-date.
  - `TestRenderBestLapsHelper` (5): empty-input-placeholder, single-
    row-link-and-time-format, XSS-in-track-name-escaped, empty-date-
    no-date-span, multiple-rows-rendered-in-input-order (Helper
    sortiert NICHT, das macht die DB-Methode).
- `tests/test_public_profile.py` +11 in zwei neuen Klassen:
  - `TestLapsLinkBugfix` (4): anon-viewing-alice-no-laps-link,
    bob-viewing-alice-no-laps-link, alice-self-view-still-has-laps-
    link (Self bleibt unverändert!), bob-viewing-bob-self-has-laps-
    link (Konsistenz auch ohne Runden).
  - `TestBestLapsOnPublicProfile` (7): bestzeiten-section-present-
    for-anon, tracks-listed-fastest-first (DOM-Position-Check),
    formatted-times-displayed (M:SS.sss), click-through-links-to-
    datenviewer, empty-state-when-no-laps, self-view-also-shows-
    bestzeiten, edit-profile-also-shows-bestzeiten (Konsistenz
    zwischen `/profile` und `/profile/<id>`).

**E2E verifiziert:**
- Anon `/profile/1` (Stefan, 3 Runden auf 2 Strecken) → BESTZEITEN-
  Section zeigt Mugello (1:28.500) vor Aragon (1:31.800). Kein
  Laps-Link. Beide Zeilen sind anklickbar auf `/analyze?lap_id=<n>
  &go=1`.
- Stefan eingeloggt schaut sein eigenes `/profile/1` an → Self-Hint
  Banner sichtbar, `EIGENE RUNDEN`-Link da, BESTZEITEN sichtbar.
- Stefan schaut Renate `/profile/2` an → keine `RUNDEN VON`, keine
  `EIGENE RUNDEN`, kein `class="my-laps-link"`. Aber Renates
  Bestzeiten (Hockenheim 1:35.000) sind sichtbar.
- Stefans `/profile` (Edit-Modus) zeigt auch die BESTZEITEN-Section
  — Konsistenz mit der Public-Seite.
- Case-Insensitive Grouping: `Aragon`/`aragon`/`ARAGON` Sessions
  kollabieren zu einem Bucket; angezeigt wird die erste Schreibweise.
- XSS: `<script>` als Track-Name escaped; im Body `&lt;script&gt;`,
  niemals executable.

[NOTE] **Warum die Bestzeiten-Section auch im Edit-Profil** (statt
nur in `/profile/<id>`): Stefans Spec sagt "Profilseite für jeden
User", was beide Sichten meint. Plus: der Owner will sehen was andere
sehen — gleiche Information am gleichen Ort spart Kontext-Switches.
Die Edit-Profilseite zeigt jetzt: Fahrer (editierbar) → Motorräder
(editierbar) → EIGENE RUNDEN (Quicklink) → BESTZEITEN (read-only
Auswertung).

[NOTE] **Keine "/api/best-laps"-Route**: die Bestzeiten werden direkt
in den Profile-Renderer eingebettet, kein separater JSON-Endpunkt.
Grund: kein Client braucht sie unabhängig vom Profil. Wenn jemals ein
Coach-Widget "deine Bestzeit auf dieser Strecke" anzeigt, kann
`db.best_lap_per_track_for_user()` direkt im Coach-Renderer
aufgerufen werden — kein API-Detour.

[NOTE] **Bugfix bewusst auch die "HOCHGELADENE RUNDEN"-Info-Box
entfernt** (vorher: bei fremd + leerer driver_name kam ein nicht-
klickbarer Info-Block "N HOCHGELADENE RUNDEN, KEIN FAHRERNAME GESETZT
— RUNDEN NICHT FILTERBAR"). Stefan-Spec sagt "Link ganz ausblenden",
und der Info-Block war optisch das gleiche Element — wäre inkonsistent
gewesen, nur den `<a>` zu entfernen. Die Lap-Count-Info bleibt
sichtbar in der Stats-Zeile unter dem Fahrernamen (`{{LAP_COUNT}}
hochgeladene Runde(n)`).

### v23.2 — Globale Bestzeiten + Pokal-Icons + Datum-Bugfix ✓ AKTUELL

[DECISION] Stefan: drei Änderungen in einem Patch.
- **Bugfix**: Datum aus der Bestzeiten-Tabelle (Profilseite) entfernen.
- **Feature 1**: Neue Kachel + Seite **BESTZEITEN** mit Top-3 pro
  Strecke über alle Fahrer hinweg.
- **Feature 2**: Pokal-Icons (Gold/Silber/Bronze) für die globalen
  Top-3 pro Strecke — in der Rundenauswahl und auf der Profilseite,
  wo die Bestzeit eines Users gleichzeitig im globalen Top-3 ist.

[DECISION] Drei Klärungsfragen vor dem Coden (Stefan-Stil "UI-
Entscheidungen besser fragen"):
- Kachelname: **BESTZEITEN** (gleicher Begriff wie auf der Profilseite —
  Kontext disambiguiert: Profil-Bestzeiten = pro User, Seite-Bestzeiten
  = global).
- Inhalt der Seite: **Top 3 pro Strecke** (Podium-Layout, Pokal-Icons
  inline).
- Pokal-Scope: **Top-3 pro Strecke über alle Fahrer** (global). Ein
  Pokal bedeutet überall dasselbe; Stefan auf seinem Profil sieht
  einen 🥈 wenn er global Zweiter auf der Strecke ist.

**Teil 1: Bugfix — Datum raus aus der Bestzeiten-Tabelle**

In `webserver.render_best_laps_html()` wird das `session_date`-Feld
im Input ignoriert; der Helper rendert keine `.bl-date` Span mehr.
Bewusst rückwärtskompatibel: das Feld bleibt im Function-Signature
und im DB-Output, falls jemand später einen API-Konsumenten baut der
das Datum will. Im HTML kommt's nicht mehr raus.

CSS in beiden Profile-Templates (`profile.html`, `profile_public.html`)
aufgeräumt: das 4-Spalten-Grid `medal | track | time | arrow` ersetzt
das alte 3-Spalten-Grid mit Datum. `.bl-date`-Regeln und die `@media
(max-width:600px) .bl-date{display:none}`-Mobile-Hack rausgeflogen.

Regressions-Test (`test_date_not_in_output`): assertet auf zwei
konkrete Datums-Strings im Output und auf das Fehlen der CSS-Klasse
`.bl-date`. Wenn jemand das Datum versehentlich wieder einbaut, fällt
der Test auf zwei Wegen.

**Teil 2: Neue DB-Methode `global_top_n_per_track(n=3)` (`db.py`)**

Returns `[{track, entries: [{rank, lap_id, duration_s, user_id,
owner_email, driver_name}, ...]}, ...]` — pro Strecke maximal n
Einträge (Default 3), sortiert nach `duration_s` aufsteigend.

Strecken-Bucketing: `LOWER(track)` als Group-Key (v22.2-Konvention
case-insensitive). Canonical Display-Name = first-seen Spelling
(via `ORDER BY created_at ASC LIMIT 1`), gleicher Algorithmus wie
in `best_lap_per_track_for_user` v23.1.

Track-Sortierung der äusseren Liste: **alphabetisch** (case-
insensitive), NICHT nach "schnellste Bestzeit zuerst". Begründung:
Stabilität > Ranking — ein User der die Seite öfter besucht findet
seine bevorzugte Strecke immer am selben Platz. Eine Highscore-
Sortierung wäre nicht stabil (wenn jemand auf Aragon einen neuen
Rekord macht, würde Aragon plötzlich nach oben springen).

Ex-aequo bei `duration_s` deterministisch via `ORDER BY laps.id ASC` —
die ältere Lap-Row gewinnt. Verhindert flackernde Reihenfolgen bei
identischen Zeiten.

**Designfrage geklärt**: Was ist "Top 3" — die 3 schnellsten Laps
oder die 3 schnellsten Fahrer (eine Runde pro User)? Stefans Spec
sagt "Top 3 pro Strecke (Podium pro Strecke)", was nach Top-3-Laps
liest, nicht Top-3-Drivers. Implementiert als Top-Laps: wenn ein
User die 3 schnellsten Runden hält, gehören alle Pokale ihm. Test
`test_one_user_can_hold_multiple_top_slots` sichert das ab.

**Teil 3: Pokal-Icons als Inline-SVG (`webserver.py`)**

Drei feste SVG-Glyphen `_MEDAL_SVG_GOLD/SILVER/BRONZE` — Trophy-Cup
mit Henkeln, 16×16 viewBox 20×20, mit den Standardfarben:
- Gold #FFD700 (Stroke #B8860B)
- Silver #C0C0C0 (Stroke #7A7A7A)
- Bronze #CD7F32 (Stroke #7A4A1F)

Stefan-Stil "echte Icons statt Punkte" wie bei den v22.4-Channel-
Icons. Inline-SVG statt externer Datei: keine zusätzlichen HTTP-
Requests, kein Asset-Pipeline, sofort verfügbar in `webserver.py`-
Strings.

Zwei Helper:
- `render_medal_html(rank)` — None → "", 1/2/3 → SVG, alles andere → "".
  Single source of truth, benutzt von Sessions-Liste, Profil-Bestzeiten,
  und `/records`-Seite.
- `medal_map_from_top_n(top_n)` — flacht die DB-Output-Struktur in
  einen `{lap_id: rank}`-Dict ab. Stable single hop von DB zu UI.
  Filtert ungültige Einträge (rank=0, lap_id=0) raus.

**Teil 4: Neue `/records`-Route (`webserver.py`)**

`GET /records` → `_page_records()` Handler. Funktioniert ohne Login
(die Information ist sowieso aus Sessions + Profile ableitbar; die
Seite ist nur eine bequemere Sicht).

Pro Strecke ein `.rec-track`-Block mit Header (Strecken-Name) und
Podium darunter (1-3 `.rec-entry` Anchors). Jeder Eintrag:
- Pokal-Icon (Gold/Silber/Bronze)
- Rank (`#1`/`#2`/`#3`)
- Driver-Name (Link auf das Profil — `<a href="/profile/<id>">`)
- Lap-Time (formatiert M:SS.sss)
- Border-Left-Akzent in der Pokal-Farbe (.rec-rank-1/2/3)
- Click auf die ganze Row → `/analyze?lap_id=X&go=1`

Privacy: Display-Name = `session.driver` wenn vorhanden, sonst
E-Mail-Local-Part. Volle E-Mail nie geleakt (gleiche Regel wie
v23.0 Public-Profile).

Empty-State separater DOM-Knoten (nicht ein leerer `.rec-grid`-
Container) — Stefan-Stil aus v23.1 "separate Node statt Container
ohne Inhalt".

**Teil 5: Pokal-Icons in der Sessions-Liste**

In `_page_sessions_list`: eine zusätzliche DB-Query
`global_top_n_per_track(3)` am Anfang, gefolgt von
`medal_map_from_top_n()`. Pro Row dann ein O(1) Lookup mit
`medals_map.get(lap_id)` → `render_medal_html(rank)`.

Der Pokal kommt **links neben der Lap-Time** im selben Anchor:
```html
<a href="/analyze?lap_id=N&go=1" class="lap-time-link">
  <span class="lap-medal"><svg .../></span>
  <span class="lap-time">1:31.500</span>
</a>
```

CSS: `.lap-medal` ist `inline-flex` mit `vertical-align:middle`, und
`:empty{display:none}` kollabiert den Container wenn kein Pokal — so
hat die Lap-Time bei normalen Laps kein extra-Spacing, bei Top-3-Laps
nur den Icon-Breite vorgeschoben.

**Teil 6: Pokal-Icons auf der Profilseite**

`render_best_laps_html(best_laps, medals=None)` extended mit optionalem
`medals`-Parameter. Beide Profile-Renderer (`_page_profile`,
`_page_public_profile`) berechnen jetzt `medal_map_from_top_n(
global_top_n_per_track(3))` und übergeben das Dict an den Helper.

Sichtbarkeit: ein User sieht den Pokal für seine eigene Bestzeit pro
Strecke wenn diese Bestzeit GLOBAL Top-3 ist. Beispiel: Stefan hat
auf Aragon 91.8s; Renate hat 90.5s (Gold), Mike hat 92.0s (Bronze).
Stefan sieht **Silber** für Aragon auf seinem Profil. Renate sieht
**Gold** auf ihrem. Mike sieht **Bronze** auf seinem. Wenn Stefan
Renates Profil besucht, sieht er dort wieder Renates Gold — die
Sicht ist nicht User-zentriert sondern Strecken-zentriert.

CSS: das 4-Spalten-Grid `medal(28px) | track(1fr) | time(auto) |
arrow(24px)`. Eine leere Pokal-Spalte (`.bl-medal:empty`) wird
`visibility:hidden` (nicht `display:none`, damit das Grid-Alignment
zwischen Pokal- und Nicht-Pokal-Zeilen identisch bleibt — sonst würde
der Track-Name in zwei Zeilen unterschiedlich weit links anfangen).

**Teil 7: Landing-Tile + Header-Link (`landing.html`, `webserver.py`)**

Neue Tile `<a href="/records" class="hub-card records">` mit Gold-
Accent (#FFD700) als ::before-Border und Arrow-Color. Eyebrow "Top 3
pro Strecke", Titel "BESTZEITEN", Desc "Wer ist am schnellsten —
Gold, Silber, Bronze pro Strecke über alle Fahrer hinweg."

Header in `build_header_html`: zusätzlicher Link `/records` zwischen
RUNDEN und PROFIL, `is_records = current_path.startswith("/records")`
für den Active-State.

**Tests:** 45 neu, alle grün. Verteilt auf zwei Dateien:

- `tests/test_profile.py` +23 in drei neuen Klassen:
  - `TestGlobalTopNPerTrack` (11): no-laps-empty, single-track-single-
    lap, aggregates-across-users (Renate ist global #1 obwohl sie nur
    eine Runde hat), one-user-can-hold-multiple-top-slots (Designfrage),
    excludes-empty-track, case-insensitive-grouping (Aragon/aragon/
    ARAGON canonical-Spelling), tracks-sorted-alphabetically (nicht
    nach Speed!), n-limits-entries-per-track (Top-1, Top-3, Top-99),
    invalid-n-returns-empty, ex-aequo-deterministic, includes-owner-
    email-and-driver-name.
  - `TestMedalHelpers` (9): render_medal_html_none, render_medal_html
    für jeden Rank (1/2/3) inkl. Farb-Check, render_medal_html_out_
    of_range (0/4/99), medal_map_from_top_n_empty (None und []),
    medal_map_from_top_n_basic, multiple_tracks, skips_invalid_entries
    (rank=0 oder lap_id=0).
  - `TestRenderBestLapsWithMedals` (3): medals-appear-when-lap-in-top3,
    no-medal-when-lap-not-in-map, medals-None-renders-without-medals
    (aber .bl-medal Spalte bleibt vorhanden für Grid-Alignment).
  - Plus Update: `test_single_row_has_link_and_time` jetzt mit
    assertNotIn auf das Datum (v23.2-Bugfix-Regression).
  - Plus neu: `test_date_not_in_output` als stärkere v23.2-Regression
    über mehrere Datums-Strings.

- `tests/test_records.py` +22 in fünf neuen Klassen:
  - `TestRecordsPage` (13): records-anon-renders, three-tracks-visible,
    tracks-alphabetically-sorted (DOM-Position-Check), top1-has-gold-
    medal (Count = 3 Gold für 3 Strecken), top3-medal-counts (2 Silver
    + 2 Bronze, weil Hockenheim nur 1 Eintrag hat), owner-links-to-
    profile, driver-name-preferred-over-email, no-driver-name-fallback-
    to-localpart (Mike ohne profile.driver_name aber mit session.driver),
    lap-link-to-analyze, times-formatted (M:SS.sss), logged-in-user-
    can-view, header-marks-records-active, xss-in-track-name-escaped.
  - `TestRecordsEmptyState` (1): NOCH KEINE BESTZEITEN + KEIN .rec-grid
    Container bei leerer DB.
  - `TestMedalsInSessionsList` (2): medals-render-in-sessions,
    lap-medal-span-present.
  - `TestMedalsOnProfile` (4): silver-appears-for-2nd-place, gold-
    appears-for-1st-place, only-user-specific-bestzeiten-shown (Stefan
    sieht NICHT Renates Pokale auf seinem Profil), no-medal-for-user-
    without-top3 (Renate hat Gold auf Aragon aber kein Silber).
  - `TestLandingTile` (2): landing-has-records-tile, header-has-
    bestzeiten-link.

**E2E verifiziert (3 User × 3 Strecken Szenario):**
- `/records` zeigt Aragon (3 Einträge), Hockenheim (1 Eintrag),
  Mugello (3 Einträge) alphabetisch sortiert.
- Gold: 3× (eine pro Strecke). Silber + Bronze: je 2× (Aragon +
  Mugello haben Top-3, Hockenheim nur 1).
- Stefan-Profil: 1× Silber (Aragon, seine Bestzeit 91.8 = #2 global)
  + 1× Bronze (Mugello, 88.5 = #3 global).
- Sessions-Liste: 7 Pokal-Icons gesamt (3 Gold + 2 Silber + 2 Bronze).
- Click auf einen `.rec-owner-link` führt zum Public-Profile.
- Click auf eine Bestzeit-Zeile führt zum Datenviewer.
- Volle E-Mail-Adresse nie im HTML — `assertNotIn 'renate@x.de'`
  geht durch.

[NOTE] **Pokal-Map als single DB-Query**: in `_page_sessions_list`
brauchen wir nicht pro Lap einzeln "ist diese Runde Top-3?" zu
fragen. Eine einzige Query `global_top_n_per_track(3)` liefert das
gesamte Mapping; pro Row danach ein O(1) Dict-Lookup. Bei 200 Laps
und ~10 Strecken bewegt sich der Overhead im einstelligen
Millisekundenbereich.

[NOTE] **Warum Border-Left-Akzent zusätzlich zum Pokal-Icon**: das
SVG ist klein (16×16), und in einer Zeile mit Rank-Number + Driver-
Name + Time will man auf Anhieb erkennen, ob's Gold, Silber oder
Bronze ist. Der farbige Streifen links vom `.rec-entry` Container ist
eine zweite visuelle Schiene — Stefan-Stil "Information zweimal
kodiert wenn's nicht störend ist".

[NOTE] **Track-Sortierung alphabetisch statt nach Speed**: das
würde manch ein User intuitiv anders erwarten ("Hot Laps zuerst"),
aber Stabilität gewinnt: wenn die Reihenfolge bei jedem Page-Load
anders sein könnte, ist das schlechter für Wiederfinden. Bei vielen
Strecken kann man die Liste mit Cmd-F durchsuchen — alphabetisch
hilft dabei.

[NOTE] **`.lap-medal:empty{display:none}` in der Sessions-Liste,
aber `:empty{visibility:hidden}` auf der Profilseite**: in der
Sessions-Liste ist die Lap-Time mit ihrem Anchor flexbox/inline,
und der Pokal sitzt auf der gleichen Zeile — `display:none` reduziert
den Pokal-Slot auf 0px, perfekt. Auf der Profilseite ist die Bestzeit-
Tabelle ein CSS-Grid mit fester Pokal-Spalte (28px); dort würde
`display:none` das ganze Grid-Layout zerreissen. Beide Wahlen sind
absichtlich.

[NOTE] **Datum bleibt im DB-Output, nur HTML wird gefiltert**:
`best_lap_per_track_for_user()` returniert `session_date` weiterhin
im Dict. Wenn jemand später einen JSON-API-Endpoint baut der die
Bestzeiten auswirft, ist das Datum noch da. `render_best_laps_html()`
ignoriert es bewusst — Bugfix nur in der Render-Schicht.

## Architektur (kompletter Stand)

```
lap_tool/
├── webserver.py                 VERSION='v23.2'; --debug-log Flag;
│                                v22.2: canonical_track_name-Call in
│                                step2_save_session + session-edit-Handler;
│                                v22.3: /api/channel-roles-registry-Route;
│                                /api/laps liefert assigned_role_ids;
│                                _channel_dots() statt _channel_badge();
│                                v22.4: _channel_dots() rendert SVG-Icons
│                                via webapp/role_icons.py;
│                                v22.6: UI-Strings auf "Standardkanal-
│                                Zuordnung" / "Datenkanäle" umbenannt;
│                                v22.7: nur VERSION-Bump;
│                                v22.8: nur VERSION-Bump;
│                                v22.9: nur VERSION-Bump;
│                                v22.10: nur VERSION-Bump (Thresholds
│                                werden direkt in coach.py geladen
│                                und ins HTML embedded);
│                                v22.11: is_private_or_loopback_ip,
│                                is_valid_public_ip, fetch_ip_geo,
│                                render_ip_cell als Modul-Helper;
│                                /admin/ip-lookup Route +
│                                _handle_admin_ip_lookup +
│                                _render_ip_lookup_page
│                                handle_one_request + send_response_only
│                                überschrieben für req-Logging;
│                                debuglog.log()-Calls in allen Aktions-Handlern;
│                                v22.12: PROFILE_IMAGE_EXTS,
│                                PROFILE_IMAGE_MAX_BYTES,
│                                _PROFILE_IMG_NAME_RE,
│                                save_profile_image(), delete_profile_image();
│                                AppState.profile_images_dir;
│                                Routes /profile, /profile/image/<f>,
│                                /profile/save, /profile/bike/{add,edit,
│                                delete,set-current};
│                                _page_profile, _serve_profile_image,
│                                _handle_profile_save, _handle_bike_*;
│                                build_header_html: PROFIL-Link immer
│                                sichtbar (active-state via /profile-
│                                prefix);
│                                _page_session_upload_form pre-fillt
│                                Driver + Current-Bike aus DB;
│                                _page_sessions_list rendert
│                                data-logged-in / data-cur-user-id /
│                                data-mine-default + data-user-id auf
│                                jeder .session-row;
│                                v23.0: Route GET /profile/<int>
│                                (read-only) — _page_public_profile
│                                mit Display-Name-Fallback auf
│                                E-Mail-Local-Part, is_self-Branch,
│                                lap_count-Stats; Owner-Email in
│                                _page_sessions_list wird zu
│                                <a href="/profile/<id>" class=
│                                "owner-link"> (mit Edge-Case für
│                                gelöschten Owner: kein Link);
│                                v23.1: render_best_laps_html()
│                                Helper (pure function, XSS-safe);
│                                _page_profile + _page_public_profile
│                                rendern BESTZEITEN-Section über
│                                BEST_LAPS_HTML; BUGFIX in
│                                _page_public_profile: fremde
│                                Profile zeigen keinen Runden-
│                                Selektions-Link mehr (vorher
│                                "RUNDEN VON X" oder Info-Box —
│                                jetzt nur noch self → /sessions?mine=1);
│                                v23.2: render_medal_html() +
│                                medal_map_from_top_n() Helper +
│                                3 Inline-SVG-Pokale (Gold/Silver/
│                                Bronze); render_best_laps_html
│                                erweitert um medals-Parameter;
│                                _page_records() neuer Handler für
│                                GET /records; _page_sessions_list
│                                berechnet medals_map und injiziert
│                                <span class="lap-medal"> in jede
│                                Row; _page_profile + _page_public_
│                                profile holen medals_map gleich;
│                                BUGFIX render_best_laps_html
│                                ignoriert session_date im Output
├── debuglog.py                  v22.1: NEU — logfmt-Logger, opt-in
├── db.py                        v22.2: + canonical_track_name();
│                                query_laps track-filter case-insensitive;
│                                v22.3: get_channel_summary liefert
│                                zusätzlich assigned_role_ids: List[str];
│                                v22.12: + profiles- und bikes-Tabellen
│                                im SCHEMA (idempotent CREATE IF NOT
│                                EXISTS); CRUD-Methoden get_profile,
│                                upsert_profile, list_bikes, get_bike,
│                                get_current_bike, add_bike, update_bike,
│                                delete_bike, set_current_bike — alle
│                                Bike-Schreibvorgänge mit user_id-
│                                Owner-Check; first-bike-forced-current
│                                und delete-promotes-next-Logik;
│                                v23.1: + best_lap_per_track_for_user
│                                (LOWER-Track-Bucketing, canonical-
│                                Spelling = first-seen, ex-aequo
│                                deterministisch via ORDER BY laps.id);
│                                v23.2: + global_top_n_per_track(n)
│                                — Top-N pro Strecke über alle User
│                                (gleiche Bucketing-Logik), alphabetische
│                                Track-Sortierung, ex-aequo via ORDER
│                                BY laps.id ASC LIMIT n
├── useradmin.py                 v22.12: cmd_delete räumt jetzt Profil-
│                                und Bike-Bilder auf Disk vor dem
│                                User-Delete (DB-Cascade lässt Files
│                                sonst stehen)
├── assign_channels.py           v22.6: NEU — Bulk-Migration leerer
│                                Standardkanal-Slots aus channel_map.txt
├── trackmap_helpers.py          v22.0: hellere .tm-bg-btn (Border/Text)
├── report.py                    Compare-Template; v22.5: Picker-JS um
│                                chDots() + role.icon + rolesRegistry-Loader;
│                                v22.6: UI-Strings umbenannt
├── report_single.py             Datenviewer-Template; v22.0: hellere
│                                .seg-switch; v22.5: Picker-JS um chDots()
│                                + role.icon + rolesRegistry-Loader;
│                                v22.6: UI-Strings umbenannt
├── coach.py                     Coach SPA; v22.0: Selection→Chart-Cursor;
│                                v22.3: chDots() + rolesRegistry-Loader;
│                                v22.4: chDots rendert role.icon (SVG);
│                                v22.6: UI-Strings umbenannt;
│                                v22.7: neuer Tab FAHRWERKS-SETUP +
│                                suspensionAnalysis IIFE mit detectBlock /
│                                travelVelocity / buildHistogram /
│                                renderHistogram; channelRoles.SPECS um
│                                'suspension'; Chart-SPECS um css-Prefix;
│                                CSS für .susp-* (event-table, hist-section,
│                                hb-bar-out/-in, hb-zero-line, …);
│                                v22.8: Histogramm-Section im
│                                panel-suspension-DOM nach oben verschoben
│                                (vor susp-trackmap-wrap statt nach
│                                suspension-analysis);
│                                v22.9: + detectTopout (Mirror von
│                                detectBlock) + detectBump (MAD-based
│                                outlier auf Federweg-Geschwindigkeit,
│                                100ms maxDur, 50ms merge); 6 Event-Typen
│                                statt 2; renderEventRow + Trackmap-
│                                typeColor + HTML-Legende + CSS-Klassen
│                                für topping-fork/-shock und bump-fork/
│                                -shock;
│                                v22.10: build_coach_*_html embedden
│                                THRESHOLDS-JSON ins HTML; alle 4 Analyse-
│                                IIFEs (brake, accel, electronics,
│                                suspension) ziehen ihre numerischen
│                                Konstanten via `cfg.key ?? fallback` aus
│                                window.THRESHOLDS.<section>
├── thresholds.json              v22.10: NEU — User-editierbare Detector-
│                                Schwellen (7 Sektionen, mit _-Kommentaren)
├── thresholds.py                v22.10: NEU — Loader mit Fallback-Dict,
│                                Merge-Logik, strip_comments,
│                                get_thresholds() als public API
├── laps.py
├── ses2ld.py, xrk2ld.py, d22ld.py
├── parsers/
│   ├── channel_roles.py           v22.6: + parse_channel_map(),
│   │                              STANDARDKANAL_TO_ROLE_ID, CHANNEL_MAP;
│   │                              pattern_hints jeder Rolle wird beim
│   │                              Import aus channel_map.txt überschrieben;
│   │                              v22.7: ANALYSIS_TAB_IDS um 'suspension';
│   │                              2 neue Rollen suspension_fork/_shock
│   ├── channel_map.txt            v22.6: NEU — Stefan-gepflegte Liste
│   │                              Standardkanal ↔ Datenkanal-Namen;
│   │                              v22.7: + 2 Zeilen für Federweg
│   ├── d2_parser.py, xrk_reader.py, ses_parser.py, ld_parser.py,
│   ├── racebox_parser.py, i2m_parser.py
│   └── ld_writer.py, ldx_writer.py, channel_names.py
├── webapp/
│   ├── role_icons.py              v22.4: NEU — ROLE_ICONS SVG-Strings;
│   │                              v22.7: + suspension_fork (Teleskop-Gabel),
│   │                              suspension_shock (Federbein mit Spirale)
│   ├── landing.html               v22.12: + Profile-Tile (.hub-card.profile,
│   │                              accent-2 #c77dff); Tile-Geometrie
│   │                              flacher (min-height 200→130px,
│   │                              gap 20→16, padding/font-sizes reduziert);
│   │                              v23.2: + BESTZEITEN-Tile
│   │                              (.hub-card.records, Gold-Akzent #FFD700)
│   ├── sessions.html              v22.3: .ch-dots CSS, .ch-badge raus;
│   │                              v22.4: .ch-icon-wrap statt .ch-dot;
│   │                              v22.6: UI-Strings umbenannt;
│   │                              v22.12: .mine-toggle in Filter-Bar
│   │                              (CSS-gated via .filter-bar[data-
│   │                              logged-in="0"]); applyFilter() honors
│   │                              data-mine-default beim Initial-Load;
│   │                              data-user-id auf .session-row;
│   │                              v23.0: + .owner-link CSS (inherit
│   │                              color, underline-on-hover) für
│   │                              klickbare Owner-Anchor in Sub-Text;
│   │                              v23.2: + .lap-medal CSS (inline-flex,
│   │                              :empty{display:none} kollabiert
│   │                              leeren Slot)
│   ├── session_upload.html
│   ├── profile.html               v22.12: NEU — Fahrer-Card + Bikes-
│   │                              Grid; inline Edit pro Bike (Name +
│   │                              Image-Input nebeneinander); Add-
│   │                              Form unter der Liste; Empty-State;
│   │                              "EIGENE RUNDEN (N)"-Link zu
│   │                              /sessions?mine=1;
│   │                              v23.1: + BESTZEITEN-Section
│   │                              (Tabelle .best-laps + .bl-row mit
│   │                              Click-Through auf /analyze);
│   │                              v23.2: Grid 4-spaltig mit
│   │                              medal-Spalte (28px); .bl-date raus
│   │                              (Bugfix Datum)
│   ├── profile_public.html        v23.0: NEU — Read-Only-Profilansicht
│   │                              (kein Edit-Form, keine Action-Buttons);
│   │                              Display-Name H1 + Lap-Count-Stats;
│   │                              Self-Hint-Banner-Slot (cyan, mit
│   │                              "→ EIGENES PROFIL EDITIEREN"-Link);
│   │                              Bikes als read-only Cards mit
│   │                              Aktuell-Badge; Empty-State
│   │                              personalisiert mit Display-Name;
│   │                              v23.1: + BESTZEITEN-Section
│   │                              (selbes CSS wie profile.html,
│   │                              bewusst dupliziert); BUGFIX —
│   │                              Laps-Link nur noch im self-Branch;
│   │                              v23.2: Grid + medal-Spalte
│   │                              gleichgeführt mit profile.html
│   ├── records.html               v23.2: NEU — Globale Bestzeiten-Seite
│   │                              (Top 3 pro Strecke). Auto-Fit-Grid
│   │                              .rec-grid mit .rec-track Blöcken;
│   │                              jeder Block: Track-Name + .rec-podium
│   │                              mit 1-3 .rec-entry Anchors; .rec-
│   │                              rank-1/2/3 setzen border-left in
│   │                              Gold/Silber/Bronze-Farben; .rec-
│   │                              owner-link verlinkt zum Profil;
│   │                              Empty-State separater Node
│   ├── speed_chart.js             v22.0: + setStickyCursor/clearStickyCursor
│   └── ...
└── tests/
    ├── test_2d_parser.py
    ├── test_channel_roles.py            110 grün (v22.6: 3 angepasst)
    ├── test_channel_summary.py          33 grün
    ├── test_lap_channel_roles_api.py    49 grün (v22.6: 1 angepasst)
    ├── test_api_laps_summary.py         54 grün (v22.7: +2 von ROLES-Loop)
    ├── test_electronics_roles.py        23 grün (v22.6: 1 angepasst)
    ├── test_analysis_tabs.py            59 grün (v22.7: +6 für FAHRWERKS-Tab;
    │                                    v22.8: +10 DOM-Reihenfolge im
    │                                    Suspension-Panel)
    ├── test_d22ld.py                    37 grün (3 skipped)
    ├── test_debug_log.py                24 grün
    ├── test_profile.py                  92 grün (v22.12: NEU 54 —
    │                                    CRUD, Image-Helper, Endpoints,
    │                                    Upload-Pre-Fill, Mine-Filter,
    │                                    Landing-Tile-Regression;
    │                                    v23.1: +15 — BestLapPerTrackDB
    │                                    (10) + RenderBestLapsHelper (5);
    │                                    v23.2: +23 — GlobalTopNPerTrack
    │                                    (11) + MedalHelpers (9) +
    │                                    RenderBestLapsWithMedals (3))
    ├── test_public_profile.py           31 grün (v23.0: NEU 20 — Route +
    │                                    Rendering, Self-Hint, Privacy
    │                                    via Local-Part-Fallback,
    │                                    Owner-Link in Sessions,
    │                                    XSS-Defense;
    │                                    v23.1: +11 — LapsLinkBugfix (4)
    │                                    + BestLapsOnPublicProfile (7))
    ├── test_records.py                  22 grün (v23.2: NEU — Records-
    │                                    Page (13) + EmptyState (1) +
    │                                    MedalsInSessionsList (2) +
    │                                    MedalsOnProfile (4) +
    │                                    LandingTile (2))
    ├── test_track_case_insensitive.py   13 grün
    ├── test_role_icons.py                7 grün (v22.7: +2 Rollen
    │                                    automatisch via ROLES-Loop)
    ├── test_picker_icons_wired.py       17 grün
    ├── test_channel_map.py              23 grün (v22.6: NEU; v22.7:
    │                                    test_eight_standardkanäle 8→10)
    ├── test_assign_channels_script.py    8 grün (v22.6: NEU)
    ├── test_suspension_roles.py         26 grün (v22.7: NEU)
    ├── test_thresholds.py               21 grün (v22.10: NEU — Loader,
    │                                    Merge-Logik, Strip-Comments,
    │                                    Coach-Integration-Check)
    ├── test_ip_lookup.py                28 grün (v22.11: NEU — Private/
    │                                    Public-Klassifizierung,
    │                                    render_ip_cell, fetch_ip_geo mit
    │                                    urlopen-Stub, Render-Page-Branches)
    ├── test_chart_cursor_sync.mjs       22 grün
    ├── test_marker_row_link.mjs         26 grün
    ├── test_speed_chart.mjs             13 grün
    └── test_suspension_analysis.mjs     63 grün (v22.7: NEU 38 — detectBlock,
                                         travelVelocity, buildHistogram;
                                         v22.9: +25 — detectTopout +
                                         detectBump)
```

Plus JS test in /tmp: `v21_39_electronics_detectors_test.mjs` (31 grün) — TODO.

Tests im Repo (v23.2): **640 Python + 124 JS = 764 grün.**

## ⚠️ SICHERHEIT
MapTiler-Key (`wedcF1FKos0F1157KQXH`) wurde von Stefan in v21.26 im Chat geteilt.
Empfehlung: revoken + neu erzeugen, neuer Key nur in `/var/lap_compare/config.json`.

## Setup
```bash
sudo apt install python3 python3-numpy build-essential python3-dev
pip3 install --user --break-system-packages libxrk
unzip lap_compare.zip && cd lap_tool
echo '{"maptiler_key": "DEIN_KEY"}' | sudo tee /var/lap_compare/config.json
python3 webserver.py --data /var/lap_compare
# Mit verbose Logging:
python3 webserver.py --data /var/lap_compare --debug-log 2>&1 | grep "^ts="
# Konverter:
python3 d22ld.py /pfad/zu/2D_BUNDLE.zip
python3 ses2ld.py session.ses
python3 xrk2ld.py session.xrk    # wine + libxrk
# Tests:
for t in tests/test_channel_roles.py tests/test_channel_summary.py \
         tests/test_lap_channel_roles_api.py tests/test_api_laps_summary.py \
         tests/test_electronics_roles.py tests/test_analysis_tabs.py \
         tests/test_d22ld.py tests/test_debug_log.py \
         tests/test_track_case_insensitive.py \
         tests/test_role_icons.py \
         tests/test_picker_icons_wired.py \
         tests/test_channel_map.py \
         tests/test_assign_channels_script.py \
         tests/test_suspension_roles.py \
         tests/test_thresholds.py \
         tests/test_ip_lookup.py \
         tests/test_profile.py \
         tests/test_public_profile.py \
         tests/test_records.py; do
  python3 $t
done
# v22.6 Bulk-Migration: bestehende Laps mit channel_map.txt nachziehen
python3 assign_channels.py --data /var/lap_compare              # dry-run
python3 assign_channels.py --data /var/lap_compare --apply      # writes
node tests/test_chart_cursor_sync.mjs
node tests/test_marker_row_link.mjs
node tests/test_speed_chart.mjs
node tests/test_suspension_analysis.mjs
```

## Action Items

### COMPLETED v21.32 → v23.1
- v21.32–v21.38: Sessions/Datenviewer-Links, Channel-Roles-Registry, Admin-Edit-Modal, Badges, Edit-Permission
- v21.39: Elektronik-Setup-Analyse
- v21.40: Sparkline pro Event + Multi-Channel-Chart + Cursor-Sync
- v21.41: Analyse-UI auf Tabs
- v21.42: 2D → MoTeC LD Konverter
- v21.43: UI-Rename Throttle → Gasgriff
- v21.44: Vorschlag vorauswählen + Coach-Empty-State raus
- v21.45: Marker ↔ Row Verlinkung
- v21.46: Autoscroll beidseitig + v21.40-Chart raus + Datenviewer-Chart pro Analyse
- v22.0: Bump + hellere Buttons + Selection→Chart-Cursor + Banner mit Version
- v22.1: Debug-Logging via --debug-log flag (logfmt auf stderr)
- v22.2: Track-Name case-insensitive (Filter + Auto-Canonicalize)
- v22.3: Channel-Status-Dots (pro Rolle ein graues/grünes Symbol) statt
  Aggregat-Badge, in allen 4 Pickern (Sessions, Coach, Datenviewer, Compare)
- v22.4: Echte Icons (Bremsscheibe, Gasgriff, …) statt Punkte; single
  source of truth `webapp/role_icons.py`
- v22.5: Bugfix — Icons im Datenviewer- und Compare-Picker (v22.3/22.4
  hatten sie in toten HTML-Dateien gelandet); Regressions-Test gegen
  diese Fehlerklasse
- v22.6: Standardkanal/Datenkanal-Terminologie + parsers/channel_map.txt
  als Pattern-Quelle + Bulk-Migrations-Skript assign_channels.py
- v22.7: Fahrwerks-Setup-Analyse — neuer Coach-Tab "FAHRWERKS-SETUP" mit
  Block-Erkennung pro Gabel/Federbein und Side-by-Side Federweg-
  Geschwindigkeits-Histogrammen
- v22.8: Fahrwerks-Analyse Layout-Umstellung — Histogramm-View über die
  Trackmap verschoben (Slot-Picker → Histogramm → Trackmap → Eventliste
  → Daten-Chart)
- v22.9: Fahrwerks-Analyse — Top-Out- und Bump-Detektoren pro Element
  separat; Severity-Hierarchie Block > Top-Out > Bump in Summary;
  6 Trackmap-Farben + Legende; MAD-basierte Bump-Schwelle
- v22.10: Detector-Thresholds aus JSON-Konfigurationsdatei. `thresholds.
  json` + `thresholds.py`-Loader, ins HTML embedded, alle Coach-
  Detektoren konsumieren `window.THRESHOLDS.<section>.<key>` mit
  Fallback. Type-Safe Merge, Forward-Compat, Drift-Schutz via Test.
- v22.11: Reverse-IP-Lookup in der Admin-View. Jede IP in den drei
  Admin-Tabs (Activity/Logins/Uploads) wird zum klickbaren Link auf
  `/admin/ip-lookup?ip=<ip>`, der server-side ip-api.com befragt und
  Stadt/Land/Region/ISP/AS/Koordinaten rendert. Private/Loopback ohne
  Upstream-Call, admin-only enforced, alle Exception-Pfade gefangen.
- v22.12: Profilverwaltung — Fahrername + n Motorräder pro User
  (jeweils Name + optionales Bild, eines "aktuell"), neue DB-Tabellen
  `profiles` + `bikes`, /profile-Routes, Bilder auf Disk mit
  UUID-Schema + Whitelist-Extensions + 5 MB Limit + Path-Traversal-
  Schutz, Upload-Maske pre-fillt Driver + Current-Bike automatisch,
  PROFIL-Tile auf Landing (Tiles etwas flacher) + Header-Link
  (immer sichtbar, anon → Login-Redirect), "Eigene Runden"-Filter
  in der Rundenliste via `?mine=1` (owner=user_id, clientseitig).
  Useradmin räumt Profil-/Bike-Bilder auf User-Delete.
- v23.0: Klickbare Owner-Profile (read-only). Owner-E-Mail in der
  Rundenliste wird zum `<a>` auf `/profile/<user_id>` — neue
  Read-Only-Profilansicht funktioniert ohne Login. Display-Name aus
  `driver_name`, Fallback auf E-Mail-Local-Part (Privacy: volle
  Adresse leakt nicht). Self-Hint-Banner mit Edit-Link wenn ein
  eingeloggter User sein eigenes öffentliches Profil anschaut.
  Eigenes Template `profile_public.html` (kein gegateetes Edit-
  Template, weil 8 Forms gaten fragiler wäre). XSS-safe gegen
  HTML-Payloads in Fahrer-/Bike-Namen.
- v23.1: Bestzeiten pro Strecke + Laps-Link-Bugfix. Neue DB-Methode
  `best_lap_per_track_for_user()` mit case-insensitivem Track-Bucketing
  und canonical-Spelling = first-seen (v22.2-Konvention).
  `render_best_laps_html()` als pure Helper-Function (XSS-safe).
  BESTZEITEN-Section auf eigener (`/profile`) und öffentlicher
  (`/profile/<id>`) Profilseite, jede Zeile klickbar auf
  `/analyze?lap_id=X&go=1`. Bugfix: bei Anzeige fremder Profilseite
  wird der Runden-Selektions-Link komplett ausgeblendet (vorher gab's
  "RUNDEN VON X" oder eine "N HOCHGELADENE RUNDEN"-Info-Box — beides
  weg, weil die Bestzeiten-Tabelle das Info-Bedürfnis besser deckt).
- v23.2: Globale BESTZEITEN-Seite + Pokal-Icons + Datum-Bugfix.
  Neue DB-Methode `global_top_n_per_track(n=3)` mit alphabetischer
  Track-Sortierung und ex-aequo-deterministischer Reihenfolge. Drei
  Inline-SVG-Pokale (Gold/Silver/Bronze) als Trophy-Cup-Glyphen, plus
  Helper `render_medal_html()` und `medal_map_from_top_n()`. Neue
  Route `/records` mit Podium-Layout pro Strecke (Top-3, jede Reihe
  klickbar). Pokal-Icons jetzt auch in der Sessions-Liste (eine DB-
  Query, O(1) Lookup pro Row) und auf beiden Profilseiten (wenn die
  User-Bestzeit gleichzeitig im globalen Top-3 ist). Landing-Tile +
  Header-Link "BESTZEITEN". Bugfix: Datum aus der User-Bestzeiten-
  Tabelle entfernt (im DB-Output erhalten, nur im HTML ausgeblendet).
- v23.3: 2D-Parser Bugfix für `MainSamplingRate=400` (BMW M1000RR
  2025er Logger, bmw_hp-Dialekt). Diagnose von Stefan getriggert
  ("nicht alle Runden gefunden, kein Rundkurs im Viewer"). Zwei
  zusammenhängende Bugs:
  1. `base_rate_hz = 100.0` hardcodiert in `_parse_bundle` —
     ignorierte das HED-`[DOWNLOAD]/MainSamplingRate`-Feld, das
     beim 2025er Logger 400 angibt.
  2. `_parse_channel_def` bmw_hp-Branch las `line1[4]` als
     dezimalen Divisor (`int(rate_str)`), tatsächlich ist es ein
     Hex-Wert (analog zur race2025-Variante, die es schon richtig
     macht). Z.B. `"28"` → dezimal 28 → 100/28=3.57 Hz, korrekt
     wäre 0x28=40 → 400/40=10 Hz.
  Effekt war konsistenter 4×-Stretch der Time-Axis: 2201 s statt
  echter 550 s (siehe Time2D-Channel als Ground-Truth). Lap-
  Boundaries aus der HED zeigten dadurch auf falsche Sample-
  Indizes, GPS-Trace pro Runde wurde ein offener Bogen statt
  geschlossener Loop. Fix: HED-Lookup für MainSamplingRate (Fallback
  auf 100 für alte Mugello/Hockenheim-Bundles, dort rate_str-Werte
  1/2/4/8 wo hex==dec — Back-Compat garantiert), Hex-Parsing für
  bmw_hp-Rate-Divisor, neue ChannelDef-Signatur mit `main_rate_hz`
  Parameter. Docstring-Update am Modul-Header und an
  `_parse_channel_def`. Output-base bleibt bei 100 Hz (keine
  Pickle-Schema-Änderung, kein Downstream-Bloat).
- v23.4: Admin-Tab "Profile". Neue DB-Methoden `list_all_profiles()`
  (JOIN profiles + users + Aggregat bike_count + current_bike_name,
  sortiert nach `updated_at DESC`) und `count_users()` (für die
  "X von Y Usern"-Info-Zeile). Neuer Tab-Slug `profiles` in
  `/admin?tab=profiles` zwischen "Logins" und "Legacy". Jede Row
  zeigt: PROFIL-Pill (+ ADMIN-Tag wenn `is_admin=1`), updated_at,
  E-Mail als klickbarer Link auf `/profile/<user_id>` (v23.0
  Public-Route), Fahrername (Em-Dash wenn leer), Bike-Zähler mit
  Current-Bike-Name (Singular/Plural korrekt), Foto-Indikator,
  Öffnen-Button. User ohne Profil tauchen NICHT in der Liste auf
  (bewusst — `[DECISION]`: "die angelegt sind" wörtlich genommen),
  die Anzahl-Lücke wird in der Info-Zeile transparent gemacht.
  Empty-State-Hinweis wenn 0 Profile. Berechtigung: anon →
  /login-Redirect, non-admin → 404 (gleiches Pattern wie alle
  /admin-Routen).
- v23.5: Podium-Refactor auf der `/records`-Seite (Treppchen-Layout,
  Motorrad unter Namen, Höhenstaffelung über padding-top am Sockel).
  [NOTE] Diese Notiz wurde in v23.6 nachgetragen — der eigentliche
  Code-Change ist im VERSION-Bump und in `webapp/records.html` /
  `tests/test_records.py` (`# v23.5`-Markierungen) bereits committet.
- v23.6: AIM CSV Importer + Upload-Limit 50 → 70 MB.

  [DECISION] Stefan: AIM-Logger-Exports (Andrea fährt RSV4, AIM hat
  eigenes CSV-Format) sollen direkt importierbar sein. Beispiele:
  Jerez 2025-12-31 (54 MB, mit RSV4-ECU-Kanälen) und Aragon
  2026-03-23 (63 MB, nur GPS). Beide >50 MB → Upload-Limit anheben.

  [DECISION] `<60s`-Beacon-Markers werden im Parser strikt verworfen
  (Split-Trigger oder Box-Stops, keine echten Runden). `detect_laps`
  würde mit `30 < dur < 600` lockerer filtern, aber bei den AIM-
  Beispielen haben wir Boxenstopps mit z.B. 19s/10s/16s drin — die
  wollen wir definitiv nicht als "Lap" sehen.

  [DECISION] ~~**Zusätzlich Spitzen-Speed-Filter** (`max_speed < 30 km/h`
  → verwerfen)~~ ZURÜCKGENOMMEN IN v23.7. Diese Decision basierte auf
  einer Fehl-Diagnose: ich hatte angenommen der Logger lief nach dem
  letzten echten Outlap im Stillstand weiter und der GPS-Beacon-Trigger
  feuerte Phantom-Beacons. Stefan hat mit RS3-Screenshot widerlegt:
  die Beacons sind echt, die GPS-Antenne war ab Lap 6 tot (Aragon).
  Siehe v23.7-Block für korrekten Fix mit Distance-basiertem Hybrid.

  [DECISION] Datums-Parsing: AIM exportiert "Wednesday, December 31,
  2025". Wir parsen das mit eigener Monatsnamen-Lookup-Table statt
  `strptime(..., '%A, %B %d, %Y')`, weil letzteres Locale-abhängig
  ist (auf einem deutschen System würde es crashen). Bei
  Parse-Failure bleibt DATE leer — kein Crash.

  **Teil 1: Neuer Parser `parsers/aim_csv_parser.py`**
  - `parse_aim_csv(filepath)` → Standard-Track-Dict (meta, time, lat,
    lon, speed, channels, lap_times, finish_line, source_format).
  - Header-Phase: alle quoted Key/Value-Zeilen einsammeln bis zur
    Daten-Tabelle (erkannt an "Time" + >2 Spalten — das diskriminiert
    sauber gegen die "Time, HH:MM AM/PM"-Meta-Zeile, die nur 2
    Spalten hat).
  - Beacon Markers: alle Werte einlesen, dann **Duration-Sentinel
    droppen** (letzter Beacon == Duration aus dem Header → kein
    Trigger einer echten Runde, sondern Session-Ende-Marker).
    Toleranz 0.5s gegen Floating-Point-Schiefe. Sonst entsteht ein
    Phantom-Lap mit mehreren tausend Sekunden Länge "weil man nicht
    sofort den Logger ausschaltet wenn man in die Box rollt".
  - Daten-Phase: Spaltenweise floats, jede Zeile mit `<n_cols` wird
    übersprungen (defensive, damit eine kaputte Zeile mitten drin
    den Parse nicht killt). Time-Wert muss parsebar sein, sonst
    Zeile skippen.
  - **Lap-Filter (zweistufig)**: erst `dur >= 60s` prüfen, dann
    `peak_speed >= 30 km/h` im Intervall (via `np.searchsorted` auf
    `time_arr` → Slice von `speed_arr`). Beide Schwellen als Modul-
    Konstanten `MIN_LAP_DURATION_S` und `MIN_LAP_PEAK_SPEED_KMH`
    exportiert.
  - Channels-Dict: alles außer Time/GPS-Speed/GPS-Latitude/GPS-
    Longitude (die gehen ins Top-Level wie bei racebox_parser).
    Inklusive Einheiten aus der Units-Zeile (zweite Header-Zeile).

  **Teil 2: Format-Diskriminierung `is_aim_csv(filepath)`**
  - `.csv` ist schon an `parse_racebox_csv` vergeben. Sniffer liest
    die erste nicht-leere Zeile und matcht `"Format","AiM CSV File"`
    (defensiv auch unquoted akzeptiert). Returnt `False` bei
    Read-Error oder leerer Datei — kein Crash.
  - Wird in `webserver.py::parse_track` aufgerufen: bei `.csv` zuerst
    sniffen → wenn AIM, parse_aim_csv; sonst Default
    parse_racebox_csv (Backward-Compat).

  **Teil 3: Upload-Limit 50 → 70 MB**
  - `MAX_UPLOAD_BYTES = 70 * 1024 * 1024` (webserver.py Zeile 143).
  - UI-Hint im Upload-Template: "MAX 50MB" → "MAX 70MB".
  - Banner zeigt automatisch "Max upload 70 MB / file".
  - Aragon-Sample (63 MB) liegt damit innerhalb des Limits. Sollte
    irgendwann noch größer werden (>70 MB), neu hochschrauben — kein
    architektonisches Issue.

  **Teil 4: VERSION-Bump auf v23.6**

  **Teil 5: Tests `tests/test_aim_csv_parser.py` — 42 grün**
  - `TestParseAimDate` (6): Standard, andere Monate, case-insensitive,
    leer, garbage, ungültiger Monatsname.
  - `TestIsAimCsvSniffer` (6): quoted-Header, unquoted-Header,
    RaceBox-Header → False (Diskriminierung), leere Datei, leading-
    blanks-Toleranz, nonexistent → False (kein Crash).
  - `TestJerezSample` (15): Meta inkl. RACER/VEHICLE/DATE, time-Achse
    20 Hz / 281k samples, GPS bei Jerez (36.7°N -6.0°E), Speed
    realistisch (>200 <300 km/h), `LAP_COUNT == 13` nach kombiniertem
    Dauer+Speed-Filter, `FASTEST_LAP == "1:46.405"`, keine Phantom-Laps
    (alle <600s), Box-Trigger gefiltert (alle ≥60s),
    `drop_stillstand_phantoms` (keine Lap-Start-Zeit ≥1800s — danach
    war's nur noch Stillstand), `every_lap_has_real_motion` (Speed-
    Filter-Regression: jede Lap hat ≥30 km/h Spitze), Bike-Channels
    präsent (RSV4 RPM/GEAR/ENG TEMP/THRT HAND), Channel-Shape
    konsistent mit time-Achse, Channel-Units korrekt, Top-Level-Spalten
    nicht in channels-Dict.
  - `TestAragonSample` (8): Meta, GPS bei Aragon (41.08°N -0.20°E),
    `LAP_COUNT == 5` (nach Speed-Filter; ab Lap 6 war's reine
    Standzeit), fastest 1:13.405, KEINE Bike-Channels (Aragon-Sample
    hat nur GPS-Block), Distance-Channel präsent,
    `every_lap_has_real_motion`, `no_phantom_after_session_end`
    (keine Lap-Start-Zeit ≥700s).
  - `TestEdgeCases` (12): Min-Duration-Filter mit synthetischem
    Mini-CSV, Duration-Sentinel-Drop, Sentinel-Toleranz (0.5s),
    no-beacons → leer + kein LAP_COUNT, Bike-Channel-im-Dict,
    Top-Level-Arrays vollständig, sample-rate propagation auf alle
    Channels, missing-header → ValueError, missing-required-column
    → ValueError (mit Spaltennamen in Message), malformed-row
    übersprungen aber nicht crashed,
    `speed_filter_drops_low_speed_lap` (zwei Laps gleicher Dauer,
    eine mit Speed 150 km/h eine mit 5 km/h — nur die fahrende
    überlebt), `speed_filter_threshold_exact` (Speed == 30 km/h
    Schwelle → bleibt drin, weil Filter `<` ist nicht `<=`).
  - `TestLapsIntegration` (1): `laps.detect_laps()` mit AIM-Track
    nutzt Strategie 0 (pre-computed) und liefert exakt die gleiche
    Anzahl Laps wie der Parser (Parser-Filter ist strikter als
    detect_laps' `30 < dur < 600`).

- v23.7: AIM CSV Importer Fix nach Bug-Report. Stefan: "test mit
  runde 29 in jerez und 22 aragon. trackmap zeigt keine fahrlinie in
  aragon und nur eine treppe in jerez" → eine echte Lap 27 in Aragon
  (2:06.974 in RS3) hatte aus dem Importer keine Daten.

  **Diagnose-Verlauf** (wichtig für späteres Debugging anderer
  AIM-Datensätze):
  1. Erste Analyse: GPS Speed in Aragon Lap 6..30 konstant 0, GPS
     Lat/Lon konstant. Annahme: "Logger lief im Stillstand weiter
     nach letzter echter Runde" → Speed-Filter eingeführt
     (`max_speed < 30 km/h → verwerfen`). FALSCH.
  2. Stefan widerspricht und schickt RS3-Screenshot der Lap 27.
     Trackmap zeigt eine **echte komplette Aragon-Linie**, GPS Speed
     im Chart hat echtes Profil 40–220 km/h. Aber RSV4 RPM ist 0
     (Hinweis: ECU-Verbindung war tot).
  3. Schlüssel-Erkenntnis: die **`Distance on GPS Speed`-Spalte
     wächst monoton von 103000m auf 107000m** in dem Bereich wo
     GPS Speed = 0 ist. Das Distance-Delta = ~138 km/h
     Durchschnittsgeschwindigkeit, also echte Fahrt. Nur die GPS-
     Spalten (Speed, Lat, Lon) sind eingefroren, die Distance
     läuft korrekt (vermutlich aus Inertial-Sensoren oder
     Wheel-Speed berechnet).
  4. RS3 kann die Trackmap aus internem Streckenwissen + Distance
     rekonstruieren — wir nicht (da wir die echte GPS-Spur brauchen
     fürs Plot). Aber **Lap-Boundaries sind in der Beacon-Liste
     korrekt**, RS3 zeigt sie auch alle.

  [DECISION] Beacon-Liste aus Header ist Source of Truth für
  Lap-Boundaries. Speed-Filter komplett raus. 60s-Dauer-Filter
  bleibt (Pit-Stops mit 7s/10s/19s sollen nicht als "Lap" gelten,
  passt Stefans Erwartung "nur echte Runden").

  [DECISION] Zusätzlich zu `lap_times` (in Time-Spalten-Einheiten,
  Sekunden ab Session-Start) auch **`lap_distances`** exportieren
  als Liste von `(d_start_m, d_dur_m)`-Tupeln. Damit kann der
  Datenviewer für Hybrid-Trackmap fallback: Lap-Slices über die
  Distance-Spalte definieren wenn GPS tot ist. Distance-Spalte
  in AIM CSV ist `Distance on GPS Speed` (es gibt auch generisch
  `Distance`, wir suchen beide in dieser Reihenfolge).

  **Resultat:**
  - Jerez: 30 echte Runden (war 13 in v23.6), Lap-Distanzen alle
    ~4300..4500m (Strecke 4423m).
  - Aragon: 23 echte Runden (war 5 in v23.6), Lap 22 entspricht
    Stefans "RS3-Lap-27" (2:06.974, dist=4998m, Aragon ist 5077m).
  - FASTEST_LAP unverändert (1:46.405 Jerez, 1:13.405 Aragon).

  **Geänderte Files:**
  - `parsers/aim_csv_parser.py`: `MIN_LAP_PEAK_SPEED_KMH`-Konstante
    + Speed-Filter-Code entfernt. Distance-Spalte wird gesucht
    (`Distance on GPS Speed` oder `Distance`), pro Lap werden
    `(d_start, d_dur)` in `lap_distances` exportiert.
  - `webserver.py`: VERSION v23.6 → v23.7.
  - `tests/test_aim_csv_parser.py`: alle Tests die den Speed-Filter
    geprüft haben weg/ersetzt. 6 neue Tests dazu: Regression gegen
    Wieder-Einbau Speed-Filter (`test_no_speed_filter_regression`),
    Distance-Boundaries-Export für beide Beispieldateien,
    Distance-Monotonie, RS3-Regression
    (`test_lap_22_is_206_runde` und `test_lap_22_distance_matches_
    rs3_screenshot`).
  - `context.md`: dieser Block.

  **Tests:** 49 Python im AIM-Modul (war 48 in v23.6, +1 netto;
  unter der Haube wurden 6 Tests gegen den Speed-Filter durch
  6 Tests gegen den neuen Mechanismus ersetzt + 1 Distance-
  Konsistenz-Test).

  [NOTE] **Datenviewer-Side**: der `lap_distances`-Output ist
  vorbereitet, aber der Datenviewer/Trackmap nutzt ihn noch nicht.
  Wenn jemand mit "Aragon-mit-toter-GPS"-ähnlichem Datensatz
  arbeitet, sieht er weiterhin keine Trackmap-Linie für die
  defekten Laps — das ist OK, weil RS3 das nur über internes
  Streckenwissen kompensiert (siehe Diagnose-Punkt 4 oben). Für
  v23.8 könnte man eine separate Trackmap-Komponente bauen die
  bei tot-GPS auf `lap_distances` zurückfällt und eine generische
  "Distance-vs-Channel"-View statt einer "Lat/Lon"-View zeigt.

  [NOTE] **AIM-Datensätze mit GPS-Ausfall**: Aragon ist nicht die
  einzige solche Datei. Wenn die GPS-Antenne kurz oder lange
  ausfällt, schreibt der AIM-Logger trotzdem weiter — mit
  eingefrorenen GPS-Werten und 0 Speed. Die Daten sind dann zwar
  zeitlich kontinuierlich (Time-Spalte läuft sauber, Distance auch),
  aber GPS Speed/Lat/Lon sind kaputt. Importer akzeptiert das jetzt
  ohne Crash und ohne Datenverlust.

[NOTE] **Channel-Map**: Stefans `parsers/channel_map.txt` hat aktuell
keine Patterns für die AIM-Datenkanal-Namen (`RSV4 RPM`, `RSV4 GEAR`
etc.). `assign_channels.py` matcht daher nicht automatisch. Wenn
gewünscht, Zeilen wie `Drehzahl\tRSV4 RPM, RPM` und `Gang\tRSV4 GEAR,
GEAR` in `channel_map.txt` ergänzen — greift dann für neue Uploads
(Suggest) UND via `assign_channels.py --apply` für bestehende Laps.

### TODO — Kandidaten für nächste Iterationen
- **Coach-Chart Cursor-Sync zur Trackmap pro Analyse**: aktuell kann der
  Chart einen Sticky-Cursor SETZEN (über Marker/Row-Klick, v22.0), aber
  der Chart-Hover triggert nicht den Trackmap-Cursor und umgekehrt. Für
  Datenviewer-Parität wäre das die nächste Iteration. Anknüpfpunkte:
  `_cursorListeners` Bus und `setMapCursor` in jedem Analyse-Modul,
  `onCursor` Callback an die Factory weitergeben.
- **Debug-Log Rotation**: Wenn `--debug-log` länger läuft kann stderr
  groß werden. `logrotate` extern ist wahrscheinlich genug, aber falls
  nicht: `--debug-log-file PATH` mit `RotatingFileHandler`-Pattern wäre
  drin (verworfen für v22.1 wegen YAGNI).
- Channel-Picker bei vielen Channels: 2D hat 80-81 Channels, Filter
  ist drin, im Coach mit echten 2D-Bundles testen
- Zoom-Stufen-Refresh bei eingezoomter Trackmap
- FAHRFEHLER-Algorithmus (BALD-Tab)
- TECHNIK-Algorithmus (BALD-Tab)
- Trackmap-Code-Pfad Brems+Beschl+Elektronik teilen (~140 Zeilen Duplikat pro Map)
- Adhoc-Cleanup-Cron-Job
- CSS-Refactor
- Compare-Chart Zoom (Multi-Channel)
- Server-Proxy für Tiles
- Channel-Aliase auf gemeinsamen Standard
- 2D + andere Formate in Compare mischen
- `finish_line`-Marker im Frontend
- /tmp/v21_39_electronics_detectors_test.mjs nach tests/ migrieren
- Coach-Side Persistence der Channel-Role-Änderungen (verworfen)
- d22ld in den Web-Upload-Flow
- d22ld auf race2025-Multirate-Output

## Stefan's Stil / Wichtige Constraints
- Linux/Python3/numpy/libxrk
- Stdlib only (kein Flask/FastAPI)
- SQLite via `db.py`
- Persistierte lap_data ist ein Pickle-Blob — alle Erweiterungen backward-compatible
- Stefan teilt manchmal Sicherheitssensible Daten im Chat (MapTiler-Key)
- Stefan testet Touch-only auf Mobile — Touch-Sync wichtig
- Stefan korrigiert iterativ; bei UI-Entscheidungen besser fragen
  (`ask_user_input_v0`) bevor coden — gilt auch für Ops-Entscheidungen mit
  Konsequenzen (z.B. Logformat → spätere Analyse)
- Konverter-Pattern (ses2ld/xrk2ld/d22ld): convert_X + _build_channels +
  _pick_dtype + CLI
- Deutsches Vokabular im UI bevorzugt: "GASGRIFF" statt "Throttle"
- UI-Disziplin: keine redundante Information
- Sichtbarkeit: dunkle Borders (`#262626` ≈ unsichtbar auf `#0a0a0a` Background);
  hellere Borders (`#4a4a4a`) und Text (`#c8c8c8`) für inaktive UI-Elemente
- Geteilte Funktionalität via Helper-Funktionen oder geteilte Module
  (`_mapCache`/`_cursorListeners` v21.40, `setupMarkerRowLink` v21.45/46/22.0,
   `/static/speed_chart.js` v21.46/22.0, `debuglog.py` v22.1)
- Idempotenz bei DOM-Bindings: Re-Renders überleben Container-Listener
- Geteilte JS-Module unter `webapp/*.js`, ausgeliefert via `/static/<file>`-Route
- Cross-Module-Communication via `window._coachCharts` Dictionary (v22.0).
  Sauberer als globaler Singleton-Patch, weil eindeutig was wo greift.
- Opt-in Features (debug-log) — kein Verhalten ändern wenn Flag nicht
  gesetzt. Banner zeigt aktive Flags, sonst still.
- Logging-Konvention v22.1: `ev=<bereich>.<subjekt>.<aktion>.<outcome>` mit
  `outcome ∈ {ok, error, denied, notfound}`; bei `denied` immer `reason=…`.
- CSV-Format-Discrimination (v23.6): `.csv`-Endung ist sowohl bei AIM als
  auch RaceBox üblich. Diskriminierung erfolgt im Dispatcher per
  Header-Sniff (`is_aim_csv()`). Falls weitere CSV-Formate dazukommen,
  gleicher Pattern: Sniff-Funktion in Parser-Modul, Dispatcher-Branch
  in `parse_track`.
