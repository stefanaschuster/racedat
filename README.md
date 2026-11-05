# Racedat

Telemetrie-Rundenvergleich für Motorrad-/Auto-Logger (AiM, MoTeC, RaceBox, Starlane, I2M, 2D).
Läuft als nativeAI-App (FastAPI/uvicorn, SQLite, Vanilla-JS).

## Layout
```
code/app.py            Einstiegspunkt (uvicorn app:app), bindet webserver.WebHandler an FastAPI
code/webserver.py      Seiten, API, Auth (unverändert aus der Standalone-Version)
code/static/           ausgelieferte JS-Assets
code/webapp/           HTML-Templates
code/migrate_data.py   Datenübernahme vom alten Server
code/requirements.txt  gepinnte Abhängigkeiten
code/.env.example      Konfiguration (-> .env im App-Verzeichnis)
data/                  Laufzeitdaten ($APP_DATA, nicht im Repo)
legacy/                alte Deploy-Dateien (Caddy/systemd)
```

## Unterschiede zur Standalone-Version
- Upload-Limit **10 MB pro Anfrage** (nativeAI-Proxy; vorher 70 MB).
- Registrierungsmails über die **Brevo-HTTPS-API** (kein SMTP). Braucht freigeschaltetes Internet und `BREVO_API_KEY` (API-Key, nicht SMTP-Key).
- Konfiguration über `.env` statt `config.json`.

## Datenmigration
App einmal starten lassen, dann **stoppen**:
```
python3 code/migrate_data.py --src /var/lap_compare --dst <App>/data --dry-run
python3 code/migrate_data.py --src /var/lap_compare --dst <App>/data
```
Die DB wird WAL-sicher kopiert, Dateipfade umgeschrieben, `server_secret` bleibt erhalten (Logins gültig), nichts wird überschrieben.
