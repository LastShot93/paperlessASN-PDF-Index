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
    index = build_index(DOCUMENTS, TAGS, CORRESPONDENTS, IndexRequest(start=10, end=12, groups=['tags', 'correspondent'], include_unmatched=True))
    assert index['count'] == 3
    assert [s['path'] for s in index['sections']] == [['Bank', 'Musterbank'], ['Ohne Tag', 'Ohne Korrespondent'], ['Versicherung', 'Musterbank']]
    assert [d['asn'] for d in index['sections'][0]['documents']] == [11, 10]
    assert sum(len(s['documents']) for s in index['sections']) == 4


@pytest.mark.parametrize('groups', [[], ['tags'], ['correspondent'], ['tags', 'correspondent'], ['correspondent', 'tags']])
def test_all_grouping_modes(groups):
    result = build_index(DOCUMENTS, TAGS, CORRESPONDENTS, IndexRequest(start=10, end=12, groups=groups, sort='asn', include_unmatched=True))
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
            ws.send_json({'type': 'index.generate', 'id': 'one', 'data': {'start': 10, 'end': 12, 'groups': ['tags', 'correspondent'], 'include_unmatched': True}})
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


def test_tag_selection_includes_unmatched_when_enabled():
    result = build_index(DOCUMENTS, TAGS, CORRESPONDENTS, IndexRequest(start=10, end=12, groups=['tags'], include_unmatched=True, selected_tags=[1]))
    assert result['count'] == 3
    assert [s['path'] for s in result['sections']] == [['Ohne passenden Tag'], ['Versicherung']]
    assert result['sections'][1]['documents'][0]['tags'] == ['Bank', 'Versicherung']
    none = build_index(DOCUMENTS, TAGS, CORRESPONDENTS, IndexRequest(start=10, end=12, groups=['tags'], include_unmatched=True, selected_tags=[]))
    assert len(none['sections']) == 1 and len(none['sections'][0]['documents']) == 3


def test_priority_assigns_each_document_once():
    result = build_index(DOCUMENTS, TAGS, CORRESPONDENTS, IndexRequest(start=10, end=12, groups=['tags'], include_unmatched=True, tag_mode='priority', tag_priority=[1,2]))
    assert sum(len(s['documents']) for s in result['sections']) == 3
    assert next(s for s in result['sections'] if s['path'] == ['Versicherung'])['documents'][0]['asn'] == 10
    limited = build_index(DOCUMENTS, TAGS, CORRESPONDENTS, IndexRequest(start=10, end=12, groups=['tags'], include_unmatched=True, tag_mode='priority', tag_priority=[1,2], selected_tags=[2]))
    assert sorted(d['asn'] for s in limited['sections'] if s['path'] == ['Bank'] for d in s['documents']) == [10,11]


def test_four_levels_year_order_and_latest_first():
    docs = [{**DOCUMENTS[0], 'created':'2024-01-01', 'document_type':1},
            {**DOCUMENTS[1], 'created':'2025-01-01', 'document_type':1}, DOCUMENTS[2]]
    result = build_index(docs, TAGS, CORRESPONDENTS, IndexRequest(start=10,end=12,groups=['year','tags','correspondent','document_type'], include_unmatched=True, year_desc=True), [{'id':1,'name':'Vertrag'}])
    assert [s['path'][0] for s in result['sections']] == ['2025','2024','2024','Ohne Jahr']
    assert result['sections'][0]['path'] == ['2025','Bank','Musterbank','Vertrag']
    flat = build_index(docs, TAGS, CORRESPONDENTS, IndexRequest(start=10,end=12,sort='date_desc'))
    assert [d['asn'] for d in flat['sections'][0]['documents']] == [11,10,12]


def test_location_fields_select_labels_and_range_fallback():
    docs = [{**DOCUMENTS[0], 'custom_fields':[{'field':7,'value':'Regal A'}]},
            {**DOCUMENTS[1], 'custom_fields':[{'field':7,'value':' '} ]}, DOCUMENTS[2]]
    request = IndexRequest(start=10,end=12,location_field=7,location_rules=[{'start':10,'end':11,'label':'Ordner 1'}, {'start':12,'end':12,'label':'Ordner 2'}])
    result = build_index(docs,TAGS,CORRESPONDENTS,request)
    locations = {d['asn']:d['location'] for d in result['sections'][0]['documents']}
    assert locations == {10:'Regal A',11:'Ordner 1',12:'Ordner 2'}
    select_doc = {**DOCUMENTS[0], 'custom_fields':[{'field':7,'value':'abc'}]}
    fields = [{'id':7,'data_type':'select','extra_data':{'select_options':[{'id':'abc','label':'Register Bank'}]}}]
    result = build_index([select_doc],TAGS,CORRESPONDENTS,request,custom_fields=fields)
    assert result['sections'][0]['documents'][0]['location'] == 'Register Bank'
    with pytest.raises(ValueError, match='überschneiden'):
        IndexRequest(start=0,end=20,location_rules=[{'start':1,'end':10,'label':'A'},{'start':10,'end':20,'label':'B'}])


def test_compressed_gaps_and_unique_correspondent_register():
    result = build_index(DOCUMENTS + [DOCUMENTS[0]],TAGS,CORRESPONDENTS,IndexRequest(start=0,end=2147483647,show_gaps=True,groups=['tags'],include_unmatched=True))
    assert result['count'] == 4
    assert result['gaps'] == [{'start':0,'end':9},{'start':13,'end':98},{'start':100,'end':2147483647}]
    assert result['gap_count'] == 2147483648-4
    assert next(r for r in result['register'] if r['name']=='Musterbank')['asns'] == [10,11]
    disabled = build_index(DOCUMENTS,TAGS,CORRESPONDENTS,IndexRequest(start=10,end=12,correspondent_register=False))
    assert not disabled['register'] and not disabled['gaps']


def test_pdf_navigation_pages_bookmarks_and_appendices():
    from io import BytesIO
    from pypdf import PdfReader
    request = IndexRequest(start=9,end=13,groups=['tags','correspondent'],include_unmatched=True,show_gaps=True,new_group_page=True,location_rules=[{'start':10,'end':12,'label':'Ordner 3 / Bank'}])
    result = build_index(DOCUMENTS,TAGS,CORRESPONDENTS,request)
    reader = PdfReader(BytesIO(render_pdf(result)))
    text = '\n'.join(page.extract_text() for page in reader.pages)
    assert 'Inhaltsverzeichnis' in reader.pages[0].extract_text()
    assert 'Ablage: Ordner 3 / Bank' in text
    assert 'Korrespondentenregister' in text and 'ASN-Abgleich' in text
    assert 'nicht im API-Ergebnis vorhanden' in text
    assert 'Änderung <2026> & Vertrag' in text
    outline = [entry for entry in reader.outline if isinstance(entry,dict)]
    assert [e.title for e in outline] == ['Bank','Ohne Tag','Versicherung','Korrespondentenregister','ASN-Abgleich']
    group_pages = [reader.get_destination_page_number(entry) for entry in outline[:3]]
    assert group_pages[0] > 0 and len(set(group_pages)) == 3
    # TOC references match destinations, including the second build pass.
    toc_text = reader.pages[0].extract_text()
    for entry in outline:
        assert str(reader.get_destination_page_number(entry)+1) in toc_text


def test_metadata_websocket_and_extended_generation(monkeypatch):
    docs = [{**DOCUMENTS[0], 'document_type':3, 'custom_fields':[{'field':7,'value':'Ordner A'}]}]
    payloads = {'tags':TAGS, 'correspondents':CORRESPONDENTS, 'document_types':[{'id':3,'name':'Rechnung'}],
                'custom_fields':[{'id':7,'name':'Ablage','data_type':'string'},{'id':8,'name':'Betrag','data_type':'monetary'}], 'documents':docs}
    def handler(request):
        rows = payloads[request.url.path.rstrip('/').split('/')[-1]]
        return httpx.Response(200,json={'results':rows,'count':len(rows),'next':None})
    monkeypatch.setattr(main,'api_client',lambda:('https://paperless.example/api',httpx.AsyncClient(transport=httpx.MockTransport(handler))))
    with TestClient(main.app) as client:
        with client.websocket_connect('/ws',headers={'origin':'http://testserver'}) as ws:
            ws.receive_json()
            ws.send_json({'type':'metadata.get','id':'meta'})
            metadata = ws.receive_json()
            assert metadata['type']=='metadata' and len(metadata['data']['custom_fields'])==1
            ws.send_json({'type':'index.generate','id':'generate','data':{'start':10,'end':12,'groups':['year','document_type'],'location_field':7,'show_gaps':True}})
            assert ws.receive_json()['type']=='progress'
            result = ws.receive_json()['data']
            assert result['sections'][0]['path']==['2026','Rechnung']
            assert result['sections'][0]['documents'][0]['location']=='Ordner A'
            assert result['gaps']==[{'start':11,'end':12}]


def test_tag_filter_affects_index_register_and_pdf_but_not_api_gaps():
    from io import BytesIO
    from pypdf import PdfReader
    result = build_index(DOCUMENTS,TAGS,CORRESPONDENTS,IndexRequest(start=10,end=12,groups=['tags'],selected_tags=[1],show_gaps=True))
    assert result['count'] == 1
    assert [s['path'] for s in result['sections']] == [['Versicherung']]
    assert result['register'] == [{'name':'Musterbank','asns':[10]}]
    assert result['gaps'] == [] and result['gap_count'] == 0
    text = '\n'.join(p.extract_text() for p in PdfReader(BytesIO(render_pdf(result))).pages)
    assert 'Zahlung' in text
    assert 'Änderung <2026> & Vertrag' not in text
    assert 'Ohne Gruppe' not in text
    assert 'Ohne passenden Tag' not in text


def test_empty_tag_selection_and_unmatched_option():
    empty = build_index(DOCUMENTS,TAGS,CORRESPONDENTS,IndexRequest(start=10,end=12,groups=['tags'],selected_tags=[]))
    assert empty['count'] == 0 and empty['sections'] == [] and empty['register'] == []
    included = build_index(DOCUMENTS,TAGS,CORRESPONDENTS,IndexRequest(start=10,end=12,groups=['tags'],selected_tags=[],include_unmatched=True))
    assert included['count'] == 3
    assert [s['path'] for s in included['sections']] == [['Ohne passenden Tag']]
    flat = build_index(DOCUMENTS,TAGS,CORRESPONDENTS,IndexRequest(start=10,end=12,groups=[],selected_tags=[]))
    assert flat['count'] == 3


def test_all_tags_exclude_untagged_by_default():
    result = build_index(DOCUMENTS,TAGS,CORRESPONDENTS,IndexRequest(start=10,end=12,groups=['tags']))
    assert result['count'] == 2
    assert all(d['asn'] != 12 for section in result['sections'] for d in section['documents'])
