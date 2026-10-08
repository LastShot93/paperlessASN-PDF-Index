# Paperless ASN PDF Index

Ein kleines Tool für physische Paperless-ngx-Archive: ASN-Bereich auswählen, Dokumente gruppieren und ein A4-Inhaltsverzeichnis als PDF herunterladen. Python/FastAPI im Backend, React und Bootstrap 5.3.8 im Frontend. Alle Anwendungsaktionen einschließlich Einstellungen, Fortschritt und PDF-Download laufen über WebSockets. Die Paperless-API wird ausschließlich vom Backend angesprochen.

## Start mit Docker Compose

```bash
cp .env.example .env
# .env bearbeiten: PAPERLESS_URL und PAPERLESS_API_TOKEN setzen
docker compose up -d --build
```

Danach **http://localhost:8080** öffnen. Die URL kann in `.env` als Basis-URL oder mit `/api/` angegeben werden. Docker Compose stellt sie dem Container bereit. `PAPERLESS_API_TOKEN` enthält einen Paperless-API-Token, kein Benutzerpasswort. Details: [Paperless-ngx REST API](https://docs.paperless-ngx.com/api/).

Bleibt der Token leer, lässt er sich unter **Einstellungen** im Browser hinterlegen. Bei leerer URL ist auch diese dort editierbar. Nichtleere Umgebungsvariablen haben Vorrang und sperren das jeweilige Feld im Frontend. Ein leeres Key-Feld beim Speichern behält den vorhandenen Key bei; zum Löschen gibt es eine separate Checkbox. **Verbindung testen** prüft die bereits gespeicherte Konfiguration.

Web-Einstellungen bleiben im Docker-Volume `app_data` erhalten. Der API-Key wird dort in `/data/settings.json` mit Dateirechten `0600` gespeichert. Ein Key aus der Umgebung wird nicht in diese Datei geschrieben und niemals an das Frontend zurückgegeben. `.env` ist aus Git und dem Docker-Build ausgeschlossen.

### Zugriff auf Paperless

Paperless muss aus dem Container erreichbar sein. `localhost` in `PAPERLESS_URL` bezeichnet den Index-Container. Verwende eine erreichbare Domain/IP oder verbinde beide Compose-Projekte mit einem gemeinsamen externen Docker-Netzwerk und verwende den Paperless-Servicenamen, beispielsweise `http://paperless:8000`. Das Tool benötigt Leseberechtigungen für Dokumente, Tags und Korrespondenten. Es verändert keine Paperless-Daten. Nur für den Token sichtbare Dokumente werden berücksichtigt.

### HTTPS / WSS

Für lokale HTTPS-Nutzung enthält Compose ein optionales Caddy-Profil:

```bash
docker compose --profile https up -d --build
```

Öffne **https://localhost:8443**. Caddy verwendet eine eigene lokale CA; deren Stammzertifikat muss im Browser/OS als vertrauenswürdig importiert werden. Export:

```bash
docker compose cp https:/data/caddy/pki/authorities/local/root.crt ./caddy-root.crt
```

Das Zertifikat nur aus der eigenen Installation übernehmen. Alternativ kann ein bestehender HTTPS-Reverse-Proxy auf den App-Port weiterleiten. Er muss WebSocket-Upgrades unterstützen und den ursprünglichen `Host`-Header erhalten. Bei HTTPS verwendet die Oberfläche automatisch WSS. Cookies werden nicht benötigt: Der Paperless-Key bleibt im Backend.

Die Ports sind standardmäßig nur an `127.0.0.1` gebunden. Das Tool besitzt keine eigene Benutzeranmeldung; für Zugriff aus dem LAN oder Internet einen Reverse-Proxy mit Zugangsschutz und gültigem HTTPS verwenden. Damit sind auch Einstellungen und Dokumentmetadaten geschützt.

## Verzeichnis erstellen

1. Optional einen eigenen Titel vergeben.
2. **ASN von / bis** angeben; beide Grenzen sind inklusive. Dokumente ohne ASN werden ausgelassen.
3. Keine Gruppierung, Tags oder Korrespondenten wählen. Bei Bedarf die andere Gruppierung als zweite Ebene ergänzen.
4. Titel A–Z, ASN aufsteigend oder Datum aufsteigend wählen. Die Gruppen werden alphabetisch sortiert; Umlaute werden wie ae/oe/ue und ß wie ss eingeordnet.
5. **Verzeichnis erstellen**, Vorschau prüfen, **PDF herunterladen** und abheften.

Das PDF enthält ASN, Titel, Korrespondent und Dokumentdatum sowie Seitenzahlen. Mehrere Tags führen zu einem Eintrag je Tag; die Dokumentanzahl zählt jedes Dokument nur einmal. Fehlende Metadaten erscheinen als „Ohne Tag“, „Ohne Korrespondent“ bzw. „Ohne Titel“. A4-Seitenumbrüche entstehen beim Export. Nach Konfigurationsänderungen muss das Verzeichnis erneut erstellt werden. Ein Verbindungsabbruch verwirft die Vorschau; die WebSocket-Verbindung wird automatisch wiederhergestellt.

API-Ergebnisse werden vollständig paginiert. `MAX_DOCUMENTS` begrenzt die Anzahl geladener Einträge je API-Abfrage (Standard 50000). Sehr große Verzeichnisse benötigen entsprechend RAM im Backend und Browser; kleinere ASN-Bereiche verbessern die Handhabung. PDF-Dateien werden im Speicher erstellt und nicht dauerhaft gespeichert.

## Entwicklung und Tests

Python 3.13+ und Node.js 22 (ab 22.12) empfohlen.

```bash
python -m venv .venv
.venv/bin/pip install -r backend/requirements.txt pytest
PAPERLESS_URL=https://paperless.example.de PAPERLESS_API_TOKEN=TOKEN SETTINGS_FILE=/tmp/asn-settings.json .venv/bin/uvicorn app.main:app --app-dir backend --reload
```

In einem zweiten Terminal:

```bash
cd frontend
npm ci
npm run dev
```

Vite leitet `/ws` und `/api` an Port 8000 weiter. Entwicklungsoberfläche: `http://localhost:5173`.

```bash
PYTHONPATH=backend .venv/bin/pytest backend/tests -q
npm --prefix frontend run build
docker compose config --quiet
```

Die Tests prüfen ASN-Grenzen, Gruppierungen, Sortierung, mehrseitige PDFs, Einstellungen/Secret-Vorrang, Pagination, API-Fehler und den WebSocket-Ablauf bis zum PDF. Für einen Integrationstest mit einer echten Instanz URL/Token konfigurieren und Verbindung, Vorschau und PDF prüfen.

## Dateien

- `compose.yaml`: App, persistente Einstellungen, optionaler HTTPS-Proxy.
- `Dockerfile`: React-Build und Python-Runtime in einem Container, Ausführung ohne Root.
- `backend/app/main.py`: WebSocket-Protokoll, Einstellungen und Paperless-Client.
- `backend/app/index.py`: Gruppierung und PDF-Ausgabe.
- `frontend/src/`: deutsche React-Oberfläche.

Lizenz: GPL-3.0 gemäß [LICENSE](LICENSE).
