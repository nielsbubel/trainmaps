import io
import json
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from fastapi.testclient import TestClient

from trainmaps_api.app import create_app
from trainmaps_api.documentation import DOCUMENTS, render_markdown

ROOT = Path(__file__).resolve().parents[1]


class PageLinks(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links, self.ids = [], set()
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            self.ids.add(attrs['id'])
        if tag in ('a', 'link') and 'href' in attrs:
            self.links.append(attrs['href'])
        if tag == 'script' and 'src' in attrs:
            self.links.append(attrs['src'])


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(data_dir=tmp_path, write_token='w' * 40,
                               read_token='r' * 40, mapping_token='m' * 40)) as instance:
        yield instance


def test_every_markdown_document_is_published_and_internal_links_work(client):
    files = {'README.md'} | {p.relative_to(ROOT).as_posix() for p in (ROOT / 'docs').glob('*.md')}
    assert {doc.file for doc in DOCUMENTS} == files
    pages = ['/', '/dokumentation'] + ['/dokumentation/' + doc.slug for doc in DOCUMENTS]
    for path in pages:
        response = client.get(path)
        assert response.status_code == 200, path
        assert "script-src 'self'" in response.headers['Content-Security-Policy']
        parsed = PageLinks(response.text)
        for href in parsed.links:
            url = urlsplit(href)
            if url.scheme or url.netloc:
                continue
            assert not url.path or url.path.startswith('/'), (path, href)
            destination = response if not url.path else client.get(url.path)
            assert destination.status_code == 200, (path, href)
            if url.fragment:
                assert unquote(url.fragment) in PageLinks(destination.text).ids, (path, href)
    api = client.get('/dokumentation/api').text
    assert '<table>' in api and '<pre><code class="language-powershell">' in api
    assert 'href="/openapi.json"' in api


def test_sources_and_bundle_contain_complete_docs_but_no_private_files(client):
    for doc in DOCUMENTS:
        response = client.get('/dokumentation/quellen/' + doc.slug + '.md')
        assert response.content == (ROOT / doc.file).read_bytes()
    response = client.get('/dokumentation/download.zip')
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
        expected = {doc.file for doc in DOCUMENTS} | {
            'api/openapi.json', 'docs/frontend-inspection.json',
            'examples/frontend-minimal.json', 'examples/frontend-v2-minimal.json',
            'examples/frontend-v3-minimal.json',
            'examples/line-reference.json', 'examples/line-reference-muenchen-s1.json',
            'examples/line-references-muenchen.json',
            'examples/line-references-germany.json', 'examples/monthly-line.json',
            'docs/line-candidates.json', 'docs/germany-first-pass-report.json',
        }
        assert set(bundle.namelist()) == expected
        assert json.loads(bundle.read('api/openapi.json')) == client.get('/openapi.json').json()
        assert b'w' * 40 not in b''.join(bundle.read(name) for name in bundle.namelist())


@pytest.mark.parametrize('path', [
    '/dokumentation/unbekannt', '/dokumentation/dateien/access.local.json',
    '/dokumentation/dateien/%2e%2e%2f.local%2faccess.local.json',
    '/dokumentation/dateien/..%5c..%5c.local%5caccess.local.json',
    '/dokumentation/quellen/..%5c.local%5caccess.local.json.md',
    '/dokumentation/assets/%2e%2e%2fapp.py', '/.local/access.local.json',
    '/daten/frontend.json', '/docs/API.md',
])
def test_only_allowlisted_documentation_files_are_public(client, path):
    response = client.get(path)
    assert response.status_code == 404
    assert 'write_token' not in response.text


def test_downloadable_example_passes_real_validator_without_storing(client):
    example = client.get('/dokumentation/dateien/frontend-minimal.json')
    assert example.status_code == 200
    response = client.post('/api/v1/imports/frontend?validate_only=true', content=example.content, headers={
        'Authorization': 'Bearer ' + 'w' * 40, 'Content-Type': 'application/json',
        'Idempotency-Key': '036fdb38-9881-4e50-9080-c75e14bc04b8', 'X-Dataset-Revision': '1',
    })
    assert response.status_code == 200, response.text
    assert response.json()['total_rows'] == 6 and response.json()['stored'] is False
    assert client.get('/api/v1/data/frontend', headers={'Authorization': 'Bearer ' + 'r' * 40}).status_code == 404


def test_downloadable_v2_example_matches_line_reference_example(client):
    mapping = client.get('/dokumentation/dateien/line-reference.json')
    assert mapping.status_code == 200
    created = client.put('/api/v1/reference/lines/de.test.s1', content=mapping.content,
                         headers={'Authorization': 'Bearer ' + 'm' * 40,
                                  'Content-Type': 'application/json'})
    assert created.status_code == 201
    example = client.get('/dokumentation/dateien/frontend-v2-minimal.json')
    response = client.post('/api/v2/imports/frontend?validate_only=true',
                           content=example.content, headers={
        'Authorization': 'Bearer ' + 'w' * 40,
        'Content-Type': 'application/json',
        'Idempotency-Key': 'b14e4192-6b98-4e54-9d9a-bc121728f37d',
        'X-Dataset-Revision': '1',
    })
    assert response.status_code == 200, response.text
    assert response.json()['contract_version'] == 'frontend-2'


def test_downloadable_v3_example_imports_and_reads_munich_station(client):
    mapping = client.get('/dokumentation/dateien/line-reference-muenchen-s1.json')
    created = client.put('/api/v1/reference/lines/de.muenchen.s1', content=mapping.content,
                         headers={'Authorization': 'Bearer ' + 'm' * 40,
                                  'Content-Type': 'application/json'})
    assert created.status_code == 201
    example = client.get('/dokumentation/dateien/frontend-v3-minimal.json')
    response = client.post('/api/v3/imports/frontend', content=example.content, headers={
        'Authorization': 'Bearer ' + 'w' * 40,
        'Content-Type': 'application/json',
        'Idempotency-Key': '307ed6ae-a822-48f6-a546-36f61dbfda7e',
        'X-Dataset-Revision': '1',
    })
    assert response.status_code == 201, response.text
    station = client.get('/api/v1/data/stops/8004128', headers={
        'Authorization': 'Bearer ' + 'r' * 40,
    })
    assert station.status_code == 200
    assert station.json()['station_id'] == 'de.eva.8004128'
    assert station.json()['values'][0]['line_id'] == 'de.muenchen.s1'


def test_renderer_escapes_html_and_keeps_distinct_section_anchors():
    rendered, headings = render_markdown('# Test\n\n<script>alert(1)</script>\n\n## Daten\n\n## Daten\n\n[x](javascript:alert(1))', 'docs/API.md')
    assert '<script>' not in rendered and 'href="javascript:' not in rendered
    assert headings == [('daten', 'Daten'), ('daten-1', 'Daten')]
