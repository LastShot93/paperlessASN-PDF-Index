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

Paperless muss aus dem Container erreichbar sein. `localhost` in `PAPERLESS_URL` bezeichnet den Index-Container. Verwende eine erreichbare Domain/IP oder verbinde beide Compose-Projekte mit einem gemeinsamen externen Docker-Netzwerk und verwende den Paperless-Servicenamen, beispielsweise `http://paperless:8000`. Das Tool benötigt Leseberechtigungen für Dokumente, Tags, Korrespondenten und Dokumenttypen; für Ablagefelder zusätzlich für benutzerdefinierte Felder. Es verändert keine Paperless-Daten. Nur für den Token sichtbare Dokumente werden berücksichtigt.

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
3. Bis zu vier unterschiedliche Gruppierungen kombinieren: **Tags**, **Korrespondenten**, **Jahr** und **Dokumenttyp**. Jahresgruppen lassen sich auch absteigend anzeigen.
4. Titel A–Z, ASN aufsteigend oder Datum (älteste/neueste zuerst) wählen.
5. Unter **Register, Ablageorte und PDF-Optionen** die zusätzlichen Suchhilfen einstellen.
6. **Verzeichnis erstellen**, Vorschau prüfen, **PDF herunterladen** und abheften.

### Gruppierungs-Tags und Priorität

Mit **Tags und Ablagefelder laden** werden die verfügbaren Tags und benutzerdefinierten Text-/Auswahlfelder über WebSockets abgefragt. Standardmäßig werden alle Tags für Register verwendet. Die Auswahl einzelner Tags blendet beispielsweise technische Inbox-Tags aus der Gruppierung aus; sie filtert keine Dokumente. Dokumente ohne passenden Gruppierungs-Tag bleiben unter „Ohne passenden Tag“ enthalten. Die ursprünglichen Tags werden weiterhin als Suchhinweise angezeigt.

Bei **Unter jedem passenden Tag aufführen** erscheint ein Dokument in jeder passenden Tag-Gruppe. Bei **Einmal nach Tag-Priorität zuordnen** gewinnt der oberste passende Tag; die Priorität ist über Pfeiltasten änderbar. Nicht ausdrücklich priorisierte Tags folgen alphabetisch. Die Dokumentanzahl und das Korrespondentenregister zählen Dokumente unabhängig von Mehrfachgruppierungen nur einmal.

### Physischer Ablageort

Ein benutzerdefiniertes Paperless-Feld kann den Ablageort enthalten, beispielsweise „Ordner 3 / Register Bank“. Text- und Auswahlfelder werden unterstützt; Auswahlwerte werden als Beschriftung angezeigt. Alternativ lassen sich ASN-Bereiche einem Ordner/Register zuordnen. Ein vorhandener Feldwert hat Vorrang, andernfalls gilt die ASN-Zuordnung. Überschneidungen zwischen Zuordnungsbereichen werden abgelehnt. Nicht zugeordnete Dokumente bleiben enthalten. Paperless-Daten werden dabei nicht verändert.

### Register, ASN-Abgleich und PDF-Navigation

Das optionale **alphabetische Korrespondentenregister** listet am Ende des Verzeichnisses die zugehörigen ASN auf. Der optionale **ASN-Abgleich** zeigt Nummern, die nicht im API-Ergebnis vorhanden sind, kompakt als Einzelnummern oder Bereiche. Diese können unbenutzt sein oder dem API-Benutzer fehlen; die Anzeige belegt keine fehlenden Papierdokumente.

Das PDF enthält ASN, Titel, Korrespondent, Dokumenttyp, Tags, gegebenenfalls Ablageort und Dokumentdatum. Fehlende Metadaten werden gekennzeichnet. Die Gruppen werden alphabetisch sortiert; Umlaute werden wie ae/oe/ue und ß wie ss eingeordnet. Das optionale PDF-Inhaltsverzeichnis verweist mit Seitenzahlen auf Gruppen und Anhänge. PDF-Lesezeichen bilden alle Gruppierungsebenen ab; Seitenköpfe zeigen den Gruppenpfad und Fußzeilen die Seitenzahl. Jede Hauptgruppe kann auf einer neuen Seite beginnen. Bei mehreren Gruppen auf einer Seite benennt der Seitenkopf die letzte Gruppe dieser Seite.

A4-Seitenumbrüche und die Seitenzahlen im Inhaltsverzeichnis entstehen beim Export. Nach Konfigurationsänderungen muss das Verzeichnis erneut erstellt werden. Ein Verbindungsabbruch verwirft die Vorschau; die WebSocket-Verbindung wird automatisch wiederhergestellt. Verzeichniseinstellungen einschließlich Tag-Prioritäten und ASN-Ablageorten bleiben im lokalen Speicher dieses Browsers erhalten; API-Keys werden dort nicht gespeichert.

API-Ergebnisse werden vollständig paginiert. `MAX_DOCUMENTS` begrenzt die Anzahl geladener Einträge je API-Abfrage (Standard 50000). Sehr große Verzeichnisse benötigen entsprechend RAM im Backend und Browser; kleinere ASN-Bereiche verbessern die Handhabung. PDF-Dateien werden im Speicher erstellt und nicht dauerhaft gespeichert.

## Entwicklung und Tests

Python 3.13+ und Node.js 22 (ab 22.12) empfohlen.

```bash
python -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.txt
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

Die Tests prüfen ASN-Grenzen, Tag-Auswahl/Priorität, vier Gruppierungsebenen, Jahres-/Datumssortierung, Ablagefelder und ASN-Zuordnungen, komprimierte Lücken, eindeutige Korrespondentenregister, PDF-Seiten/Lesezeichen/Inhaltsverzeichnis, Einstellungen/Secret-Vorrang, Pagination, API-Fehler und den WebSocket-Ablauf bis zum PDF. Für einen Integrationstest mit einer echten Instanz URL/Token konfigurieren und Verbindung, Vorschau und PDF prüfen.

## Dateien

- `compose.yaml`: App, persistente Einstellungen, optionaler HTTPS-Proxy.
- `Dockerfile`: React-Build und Python-Runtime in einem Container, Ausführung ohne Root.
- `backend/app/main.py`: WebSocket-Protokoll, Einstellungen und Paperless-Client.
- `backend/app/index.py`: Gruppierung und PDF-Ausgabe.
- `frontend/src/`: deutsche React-Oberfläche.

Lizenz: GPL-3.0 gemäß [LICENSE](LICENSE).
