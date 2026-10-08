import asyncio
import base64
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.index import IndexRequest, build_index, render_pdf
from app import main

TAGS = [{'id': 1, 'name': 'Versicherung'}, {'id': 2, 'name': 'Bank'}]
CORRESPONDENTS = [{'id': 1, 'name': 'Musterbank'}]
DOCUMENTS = [
    {'id': 1, 'archive_serial_number': 10, 'title': 'Zahlung', 'tags': [1, 2], 'correspondent': 1, 'created': '2026-01-02'},
    {'id': 2, 'archive_serial_number': 11, 'title': 'Änderung <2026> & Vertrag', 'tags': [2], 'correspondent': 1, 'created': '2026-02-03'},
    {'id': 3, 'archive_serial_number': 12, 'title': 'Ohne Gruppe', 'tags': [], 'correspondent': None},
    {'id': 4, 'archive_serial_number': None, 'title': 'Kein ASN'},
    {'id': 5, 'archive_serial_number': 99, 'title': 'Außerhalb'},
]


def test_inclusive_range_and_nested_grouping():
    index = build_index(DOCUMENTS, TAGS, CORRESPONDENTS, IndexRequest(start=10, end=12, groups=['tags', 'correspondent']))
    assert index['count'] == 3
    assert [s['path'] for s in index['sections']] == [['Bank', 'Musterbank'], ['Ohne Tag', 'Ohne Korrespondent'], ['Versicherung', 'Musterbank']]
    assert [d['asn'] for d in index['sections'][0]['documents']] == [11, 10]
    assert sum(len(s['documents']) for s in index['sections']) == 4


@pytest.mark.parametrize('groups', [[], ['tags'], ['correspondent'], ['tags', 'correspondent'], ['correspondent', 'tags']])
def test_all_grouping_modes(groups):
    result = build_index(DOCUMENTS, TAGS, CORRESPONDENTS, IndexRequest(start=10, end=12, groups=groups, sort='asn'))
    assert result['count'] == 3
    assert all([d['asn'] for d in s['documents']] == sorted(d['asn'] for d in s['documents']) for s in result['sections'])


def test_validation_and_empty_pdf():
    with pytest.raises(ValueError):
        IndexRequest(start=12, end=10)
    with pytest.raises(ValueError):
        IndexRequest(start=1, end=10, groups=['tags', 'tags'])
    index = build_index([], [], [], IndexRequest(start=1, end=2))
    assert render_pdf(index).startswith(b'%PDF-')


def test_pdf_many_pages_with_escaped_titles():
    documents = [{**DOCUMENTS[1], 'id': n, 'archive_serial_number': n} for n in range(250)]
    index = build_index(documents, TAGS, CORRESPONDENTS, IndexRequest(start=0, end=250, groups=['tags']))
    pdf = render_pdf(index)
    assert pdf.startswith(b'%PDF-') and len(pdf) > 5000


def test_settings_environment_precedence_and_secret_file(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'SETTINGS_FILE', tmp_path / 'settings.json')
    monkeypatch.setenv('PAPERLESS_URL', 'https://locked.example')
    monkeypatch.setenv('PAPERLESS_API_TOKEN', 'env-secret')
    response = main.save_settings({'url': 'https://other.example', 'token': 'new-token'})
    assert response['url'] == 'https://locked.example'
    assert 'env-secret' not in json.dumps(response)
    assert json.loads(main.SETTINGS_FILE.read_text()) == {}
    monkeypatch.delenv('PAPERLESS_URL')
    monkeypatch.delenv('PAPERLESS_API_TOKEN')
    main.save_settings({'url': 'https://paperless.example/api/', 'token': 'saved-token'})
    assert main.settings() == {'url': 'https://paperless.example/api', 'token': 'saved-token'}
    assert main.SETTINGS_FILE.stat().st_mode & 0o777 == 0o600
    main.save_settings({'url': 'https://paperless.example', 'token': None})
    assert main.settings()['token'] == 'saved-token'
    main.save_settings({'url': 'https://paperless.example', 'clear_token': True})
    assert not main.settings()['token']


def test_pagination_never_follows_external_next_url():
    urls = []
    def handler(request):
        urls.append(str(request.url))
        page = int(request.url.params['page'])
        return httpx.Response(200, json={'results': [{'id': page}], 'next': 'https://attacker.example/' if page == 1 else None})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await main.fetch_all(client, 'https://paperless.example/api/tags/')
    assert asyncio.run(run()) == [{'id': 1}, {'id': 2}]
    assert all(url.startswith('https://paperless.example/') for url in urls)


def test_websocket_generation_and_pdf(monkeypatch):
    def handler(request):
        assert request.headers['authorization'] == 'Token private-key'
        path = request.url.path
        if path.endswith('/documents/'):
            assert request.url.params['archive_serial_number__gte'] == '10'
            assert request.url.params['archive_serial_number__lte'] == '12'
            data = DOCUMENTS
        elif path.endswith('/tags/'):
            data = TAGS
        else:
            data = CORRESPONDENTS
        return httpx.Response(200, json={'results': data, 'count': len(data), 'next': None})
    monkeypatch.setattr(main, 'api_client', lambda: ('https://paperless.example/api', httpx.AsyncClient(transport=httpx.MockTransport(handler), headers={'Authorization': 'Token private-key'})))
    with TestClient(main.app) as client:
        assert client.get('/api/health').json()['status'] == 'ok'
        with client.websocket_connect('/ws', headers={'origin': 'http://testserver'}) as ws:
            assert ws.receive_json()['type'] == 'settings'
            ws.send_json({'type': 'index.generate', 'id': 'one', 'data': {'start': 10, 'end': 12, 'groups': ['tags', 'correspondent']}})
            assert ws.receive_json()['type'] == 'progress'
            result = ws.receive_json()
            assert result['type'] == 'index' and result['data']['count'] == 3
            ws.send_json({'type': 'index.pdf', 'id': 'two'})
            result = ws.receive_json()
            assert base64.b64decode(result['data']['content']).startswith(b'%PDF-')
            assert result['data']['filename'] == 'ASN-10-12.pdf'
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/ws', headers={'origin': 'https://attacker.example'}):
                pass


def test_authentication_error():
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(401))) as client:
            await main.fetch_all(client, 'https://paperless.example/api/documents/')
    with pytest.raises(ValueError, match='API-Key'):
        asyncio.run(run())
