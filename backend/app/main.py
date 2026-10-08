import asyncio
import base64
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from .index import IndexRequest, build_index, render_pdf

app = FastAPI(title='Paperless ASN Index')
SETTINGS_FILE = Path(os.getenv('SETTINGS_FILE', '/data/settings.json'))
MAX_DOCUMENTS = int(os.getenv('MAX_DOCUMENTS', '50000'))


def normalize_url(value):
    value = value.strip().rstrip('/')
    parts = urlsplit(value)
    if parts.scheme not in ('http', 'https') or not parts.netloc or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError('Bitte eine gültige HTTP(S)-URL ohne Zugangsdaten, Query oder Fragment eingeben.')
    return value if value.endswith('/api') else value + '/api'


def settings():
    try:
        stored = json.loads(SETTINGS_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        stored = {}
    return {
        'url': os.getenv('PAPERLESS_URL') or stored.get('url', ''),
        'token': os.getenv('PAPERLESS_API_TOKEN') or stored.get('token', ''),
    }


def public_settings():
    config = settings()
    return {'url': config['url'], 'has_token': bool(config['token']),
            'url_locked': bool(os.getenv('PAPERLESS_URL')),
            'token_locked': bool(os.getenv('PAPERLESS_API_TOKEN'))}


class SettingsUpdate(BaseModel):
    url: str = Field(max_length=2048)
    token: str | None = Field(default=None, max_length=4096)
    clear_token: bool = False


def save_settings(data):
    update = SettingsUpdate.model_validate(data)
    current = settings()
    if not os.getenv('PAPERLESS_URL'):
        current['url'] = normalize_url(update.url)
    if not os.getenv('PAPERLESS_API_TOKEN'):
        if update.clear_token:
            current['token'] = ''
        elif update.token and update.token.strip():
            token = update.token.strip()
            if any(c.isspace() for c in token):
                raise ValueError('Der API-Key darf keine Leerzeichen enthalten.')
            current['token'] = token
    # Environment secrets are never persisted.
    stored = {k: v for k, v in current.items()
              if not os.getenv('PAPERLESS_URL' if k == 'url' else 'PAPERLESS_API_TOKEN')}
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = SETTINGS_FILE.with_suffix('.tmp')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(stored, stream)
    temp.replace(SETTINGS_FILE)
    return public_settings()


async def fetch_all(client, url, params=None, progress=None):
    rows = []
    page = 1
    while True:
        response = await client.get(url, params={'page_size': 100, **(params or {}), 'page': page})
        if response.status_code in (401, 403):
            raise ValueError('Paperless verweigert den Zugriff. API-Key und Leseberechtigungen prüfen.')
        response.raise_for_status()
        payload = response.json()
        batch = payload.get('results')
        if not isinstance(batch, list):
            raise ValueError('Unerwartete API-Antwort. Bitte die Paperless-URL prüfen.')
        rows.extend(batch)
        if len(rows) > MAX_DOCUMENTS:
            raise ValueError(f'Limit von {MAX_DOCUMENTS} Einträgen überschritten. Bitte den ASN-Bereich verkleinern.')
        if progress:
            await progress(len(rows), payload.get('count', len(rows)))
        if not payload.get('next'):
            return rows
        # Do not follow arbitrary pagination URLs with the authorization header.
        page += 1
        if not batch:
            raise ValueError('Die API liefert eine leere Seite mit weiterer Pagination.')


def api_client():
    config = settings()
    if not config['url'] or not config['token']:
        raise ValueError('Bitte Paperless-URL und API-Key in den Einstellungen hinterlegen.')
    base = normalize_url(config['url'])
    return base, httpx.AsyncClient(headers={'Authorization': f"Token {config['token']}"}, timeout=45, follow_redirects=False)


@app.get('/api/health')
async def health():
    return {'status': 'ok'}


@app.websocket('/ws')
async def websocket(ws: WebSocket):
    # Browser clients must come from the same host, including forwarded HTTPS hosts.
    origin = ws.headers.get('origin')
    if not origin or urlsplit(origin).netloc != ws.headers.get('host'):
        await ws.close(code=1008)
        return
    await ws.accept()
    async def send(kind, data, request_id=None):
        await ws.send_json({'type': kind, 'data': data, 'id': request_id})
    await send('settings', public_settings())
    cached = None
    try:
        while True:
            message = await ws.receive_json()
            request_id = message.get('id')
            action = message.get('type')
            try:
                if action == 'settings.get':
                    await send('settings', public_settings(), request_id)
                elif action == 'settings.save':
                    await send('settings', save_settings(message.get('data', {})), request_id)
                    cached = None
                elif action == 'connection.test':
                    base, client = api_client()
                    async with client:
                        await fetch_all(client, base + '/documents/', {'page_size': 1, 'id': 0})
                    await send('connection', {'ok': True, 'message': 'Verbindung zu Paperless erfolgreich.'}, request_id)
                elif action == 'index.generate':
                    cached = None
                    request = IndexRequest.model_validate(message.get('data', {}))
                    base, client = api_client()
                    async def progress(loaded, total):
                        await send('progress', {'loaded': loaded, 'total': total}, request_id)
                    async with client:
                        documents, tags, correspondents = await asyncio.gather(
                            fetch_all(client, base + '/documents/', {
                                'archive_serial_number__gte': request.start,
                                'archive_serial_number__lte': request.end,
                                'ordering': 'archive_serial_number',
                                'fields': 'id,title,archive_serial_number,created,tags,correspondent',
                            }, progress),
                            fetch_all(client, base + '/tags/'),
                            fetch_all(client, base + '/correspondents/'))
                    cached = build_index(documents, tags, correspondents, request)
                    await send('index', cached, request_id)
                elif action == 'index.pdf':
                    if cached is None:
                        raise ValueError('Bitte zuerst ein Verzeichnis erstellen.')
                    pdf = await asyncio.to_thread(render_pdf, cached)
                    await send('pdf', {'filename': f"ASN-{cached['start']}-{cached['end']}.pdf",
                                       'content': base64.b64encode(pdf).decode()}, request_id)
                else:
                    raise ValueError('Unbekannte Aktion.')
            except ValidationError as exc:
                await send('error', '; '.join(e['msg'] for e in exc.errors()), request_id)
            except ValueError as exc:
                await send('error', str(exc), request_id)
            except httpx.HTTPStatusError as exc:
                await send('error', f'Paperless meldet HTTP {exc.response.status_code}. URL und API-Kompatibilität prüfen.', request_id)
            except httpx.RequestError:
                await send('error', 'Paperless ist nicht erreichbar. URL, Netzwerk und TLS-Zertifikat prüfen.', request_id)
            except (OSError, TypeError, KeyError):
                await send('error', 'Einstellungen konnten nicht gespeichert oder API-Daten nicht verarbeitet werden.', request_id)
    except (WebSocketDisconnect, RuntimeError):
        pass


static = Path(os.getenv('STATIC_DIR', '/app/static'))
if static.exists():
    app.mount('/', StaticFiles(directory=static, html=True), name='frontend')
