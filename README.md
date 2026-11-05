# Lap Compare & Race Data Converters

CLI-Tools + Web-Frontend rund um Race-Datenlogger-Dateien:

* `.ses` (AiM/Racelogic — älteres Format)
* `.xrk` / `.xrz` (AiM RaceStudio — proprietär, via libxrk)
* `.ld` (MoTeC i2)

Vier Tools:

1. **`lap_compare.py`** — Vergleicht schnellste Runden zweier Dateien (.ses,
   .ld, .xrk, .xrz; beliebig kombinierbar), erzeugt interaktiven HTML-Report.
2. **`ses2ld.py`** — Konvertiert `.SES` Dateien in MoTeC i2 Format (`.ld` + `.ldx`).
3. **`xrk2ld.py`** — Konvertiert `.xrk`/`.xrz` AiM-Dateien in MoTeC i2 Format
   (benötigt `libxrk`).
4. **`d22ld.py`** — Konvertiert 2D-Datenrecorder-Bundles (.MES/.zip, beide
   Varianten bmw_hp und race2025) in MoTeC i2 Format.
5. **`webserver.py`** — Standalone Web-Frontend für `lap_compare`. Pure
   Python-Stdlib, keine externen Web-Frameworks.

## Voraussetzungen

* Linux mit Python 3.7+
* `numpy`

```bash
sudo apt install python3 python3-numpy build-essential python3-dev
```

Für **xrk2ld** zusätzlich `libxrk` installieren:

```bash
pip3 install --user --break-system-packages libxrk
```

Oder in einem virtualenv:

```bash
python3 -m venv ~/lapcomp-venv
source ~/lapcomp-venv/bin/activate
pip install libxrk numpy
```

## Schnellstart

ZIP entpacken, dann direkt aus dem entpackten Verzeichnis:

```bash
python3 ses2ld.py datei.ses          # SES → MoTeC
python3 xrk2ld.py datei.xrk          # XRK → MoTeC (libxrk nötig)
python3 lap_compare.py a.ses b.ld    # Vergleich
```

## SES → MoTeC Konvertierung

```bash
# Eine Datei (output: session.ld + session.ldx neben der Eingabe)
python3 ses2ld.py session.ses

# Mehrere Dateien
python3 ses2ld.py *.ses

# Ziel-Verzeichnis
python3 ses2ld.py *.ses -o /tmp/output_dir/

# Mit Metadata-Override
python3 ses2ld.py datei.ses --driver "Stefan" --vehicle "CBR1000RR" \
    --venue "Catalunya" --session "FP1"
```

## XRK → MoTeC Konvertierung

```bash
# Eine Datei
python3 xrk2ld.py session.xrk

# Mehrere Dateien
python3 xrk2ld.py *.xrk -o /tmp/converted/

# Mit AiM → MoTeC Channel-Renaming (SpeedVeh→Ground Speed etc.)
python3 xrk2ld.py session.xrk --rename-channels

# Mit Metadata-Override
python3 xrk2ld.py session.xrk --driver "Stefan" --venue "Catalunya"
```

Die erzeugte `.ld` Datei enthält alle Channels aus der XRK-Datei plus
`Beacon` und `Running Lap Time` für i2's Lap-Splitting.

## 2D → MoTeC Konvertierung

Unterstützt beide 2D-Bundle-Varianten automatisch (Erkennung im Parser):

* **bmw_hp** — BMW HP / Werksrennteam-Bundles (80 Channels, 100 Hz Basis).
* **race2025** — BMW M1000RR Race2025-Track-Tool (81 Channels, multi-rate
  5..250 Hz, wird auf 100 Hz angeglichen).

```bash
# Eine ZIP (output: bundle.ld + bundle.ldx neben der ZIP)
python3 d22ld.py 2D_MUGELLO_20230701-1547-01_MES.zip

# Race2025-Wrapper-ZIP — Variante wird selbst erkannt
python3 d22ld.py 2D_Measurements_from_VALENCIA6D_26.zip

# Direkt ein .MES-Verzeichnis (statt ZIP)
python3 d22ld.py /pfad/zu/BUNDLE.MES

# Mehrere Bundles in ein Ziel-Verzeichnis
python3 d22ld.py *.zip -o /tmp/converted/

# Mit 2D/AiM → MoTeC Channel-Renaming (RPM → Engine RPM, VWheelFL → Wheel Speed FL …)
python3 d22ld.py session.zip --rename-channels

# Metadata überschreiben
python3 d22ld.py session.zip --driver "Stefan" --session "FP1"
```

Hinweise:

* Der Parser liest beide Varianten in dasselbe Schema und gleicht alle Channels
  auf 100 Hz an. Die `.ld` enthält am Ende GPS Latitude/Longitude/Speed plus
  alle weiteren Channels (RPM, Throttle, Brake, Lean, Wheel-Speeds usw.) plus
  `Beacon` und `Running Lap Time` für i2's Lap-Splitting.
* Die Lap-Marker im `.ldx` kommen primär aus der HED-[LAPTIMES]-Sektion
  (bereits Out-/In-Lap-gefiltert vom Parser); fehlt die, wird per Laptrigger-
  bzw. Laps-Counter-Channel detektiert.
* Race2025-`.line`-Start-Ziel-Linien werden nur informativ geloggt — MoTeC i2
  nutzt Beacons statt expliziter Linien.

## Lap-Vergleich

Vergleicht .ses, .ld, .xrk und .xrz Dateien — beliebige Kombinationen
funktionieren (z.B. SES gegen XRK).

```bash
# Schnellste Runden zweier Dateien
python3 lap_compare.py datei1.ses datei2.ld
python3 lap_compare.py datei1.xrk datei2.ld
python3 lap_compare.py datei1.xrk datei2.xrk

# Bestimmte Runden statt der schnellsten
python3 lap_compare.py a.ses b.ld --lap-a 5 --lap-b 7

# Zwei Runden innerhalb einer Datei
python3 lap_compare.py session.ld
python3 lap_compare.py session.xrk

# Alle Runden auflisten
python3 lap_compare.py session.ld --list

# Ziel-Datei vorgeben
python3 lap_compare.py a.ses b.ld --out report.html
```

Hinweis: Für .xrk/.xrz braucht es libxrk (siehe oben).

## Web-Frontend (`webserver.py`)

Standalone Web-Anwendung mit Session-Bibliothek — nutzt **ausschließlich
die Python-Standardbibliothek** (plus `sqlite3`), keine externen
Web-Frameworks oder Service-Manager.

### Konzept (ab v10)

Zwei getrennte Aufgabenbereiche:

**1. Session-Bibliothek (`/sessions`):**
   - User lädt Session-Dateien hoch mit Metadaten (Fahrer, Bike, Strecke,
     Datum, Notizen)
   - Im zweiten Schritt wählt der User aus den erkannten Runden aus,
     welche in der Bibliothek gespeichert werden sollen
   - Original-Datei bleibt unter `<data_dir>/originals/<session-id>/` als
     Backup; nur die ausgewählten Lap-Daten landen in SQLite

**2. Vergleichs-Seite (`/`):**
   - Für jeden der zwei Slots (A/B) kann der User wählen:
     - **Aus Bibliothek** → öffnet Modal-Dialog mit Filtern (Strecke,
       Bike, Fahrer, Zeit-Range, Volltextsuche), Auswahl per Klick
     - **Datei hochladen** → einmaliger Upload, wird NICHT in der
       Bibliothek gespeichert
   - Auch gemischter Modus: Slot A aus Bibliothek + Slot B direkt
     hochgeladen (oder umgekehrt) ist OK

### Start

**Entwicklung / Test (Single-HTTP auf High-Port):**

```bash
python3 webserver.py                          # 0.0.0.0:8000
python3 webserver.py --port 9000
python3 webserver.py --host 127.0.0.1         # nur localhost
python3 webserver.py --data /var/lap_compare  # Daten-Verzeichnis
```

**Produktion (Port 80 + 443 mit TLS):**

```bash
# Per sudo, da Ports < 1024 root brauchen
sudo python3 webserver.py \
  --http-port 80 \
  --https-port 443 \
  --cert /etc/letsencrypt/live/example.com/fullchain.pem \
  --key  /etc/letsencrypt/live/example.com/privkey.pem \
  --data /var/lap_compare
```

Beide Listener (HTTP + HTTPS) laufen parallel — jeder in seinem Thread,
beide bedienen denselben Handler. Wenn nur `--https-port` (ohne
`--http-port`) gesetzt ist, läuft der Server nur über TLS.

Mindest-TLS-Version: TLS 1.2. Zertifikat und Key werden im PEM-Format
erwartet (Standard bei Let's Encrypt / certbot).

Der Server läuft im Vordergrund. Beenden mit Ctrl-C. Dauerbetrieb:

```bash
sudo nohup python3 webserver.py \
  --http-port 80 --https-port 443 \
  --cert /etc/letsencrypt/live/example.com/fullchain.pem \
  --key  /etc/letsencrypt/live/example.com/privkey.pem \
  --data /var/lap_compare \
  > /var/log/racedat.log 2>&1 &
# oder via screen/tmux
```

### Daten-Verzeichnis-Layout

```
<data_dir>/
├── sessions.db          # SQLite, Metadaten + Lap-Blobs
├── originals/           # Original-Datei pro Session
│   └── <session-uuid>/
│       └── <filename>.{ses,ld,xrk,xrz}
├── reports/             # generierte HTML-Reports
│   └── <report-uuid>/
│       └── report.html
└── tmp/                 # transiente Direkt-Uploads (compare ohne Bibliothek)
```

### Endpoints

```
GET  /                          Vergleichs-Seite (Slot-Auswahl)
POST /compare                   Vergleich starten, Redirect zum Report
GET  /report/<uuid>             Interaktiver Report (mit Toolbar)
GET  /download/<uuid>           Report als Datei runterladen

GET  /sessions                  Bibliothek-Übersicht
GET  /sessions/upload           Session-Upload Schritt 1 (Datei + Meta)
POST /sessions/upload           Schritt 2 (Lap-Auswahl)
POST /sessions/save             Session persistieren
POST /sessions/<id>/delete      Session löschen

GET  /api/distinct              JSON: vorhandene Fahrer/Bike/Strecke-Werte
GET  /api/laps?...filters...    JSON: gefilterte Lap-Liste
```

### Bedienung

**Sessions hochladen:**
1. `/sessions/upload` öffnen
2. Datei + Metadaten eingeben (Felder optional)
3. Im Schritt 2 die zu speichernden Runden markieren (schnellste
   vorausgewählt) — oder `Top 3 schnellste` / `Alle` / `Keine` Buttons
4. Speichern → landet in der Bibliothek

**Vergleich starten:**
1. `/` öffnen
2. Für Slot A & B jeweils wählen:
   - `+ Aus Bibliothek` → Modal mit Filtern
   - `Datei hochladen` → direkter, nicht-persistenter Upload
3. Optional: GPS-Anker
4. `REPORT BAUEN` → interaktiver Report

### Limits / Verhalten

- **50 MB pro Datei** (sowohl Session-Upload als auch Direkt-Upload)
- **Datei-Endungs-Whitelist**: `.ses`, `.ld`, `.xrk`, `.xrz`
- **SQLite mit WAL-Mode** für gute Concurrent-Performance
- **Reports persistent** im Daten-Verzeichnis (überleben Server-Neustart)

## Hinweise

* **MoTeC i2 Kompatibilität:** Der LD-Writer basiert auf der bewährten
  GeekyDeaks/sim-to-motec Implementierung (`id=64`, `sig1=1000000`,
  `sig2=128`, `type="ADL"`, `version=420`).
* **Lap-Erkennung** (in `laps.py`):
  1. Vorher bekannte Lap-Times (z.B. von libxrk)
  2. Running-Lap-Time-Channel (LD-Format)
  3. Bekannter Finish-Line aus `*FL`-Feld (SES)
  4. Auto-Erkennung: dichteste Stelle auf der Strecke
* **GPS Speed in libxrk** ist in m/s — wird automatisch in km/h umgerechnet
* **XRK Sample-Raten** variieren stark pro Channel (1 Hz bis ~200 Hz);
  bleibt im LD-Output erhalten.

## Dateistruktur

```
lap_tool/
├── lap_compare.py            # Lap-Vergleich CLI
├── ses2ld.py                 # SES → MoTeC Konverter
├── xrk2ld.py                 # XRK → MoTeC Konverter (libxrk-basiert)
├── d22ld.py                  # 2D → MoTeC Konverter (bmw_hp + race2025)
├── webserver.py              # Standalone Web-Frontend (Stdlib-only)
├── db.py                     # SQLite-Schicht für Session-Bibliothek
├── webapp/
│   ├── upload.html           # Compare-Seite (Slot-Auswahl, Modal-Picker)
│   ├── sessions.html         # Session-Bibliothek (Liste)
│   └── session_upload.html   # Session-Upload (Schritt 1 + 2)
├── parsers/
│   ├── __init__.py
│   ├── ses_parser.py         # AiM/Racelogic .SES Parser
│   ├── ld_parser.py          # MoTeC .ld Parser
│   ├── ld_writer.py          # MoTeC .ld Writer
│   ├── ldx_writer.py         # MoTeC .ldx XML Writer
│   ├── xrk_reader.py         # AiM .xrk Reader (via libxrk)
│   └── channel_names.py      # AiM → MoTeC Channel-Namen Mapping
├── laps.py                   # Lap-Erkennung
├── compare.py                # Distanz-Alignment & Hot-Zones
├── report.py                 # HTML-Report-Generator
└── README.md
```
