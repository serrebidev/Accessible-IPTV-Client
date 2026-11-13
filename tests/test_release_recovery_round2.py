import io
import json
from types import SimpleNamespace
from tools import release

import pytest


def test_lost_creation_response_is_reconciled_before_another_post(monkeypatch):
    payload = {'tag_name': 'v1.2.3', 'name': 'v1.2.3', 'body': 'notes', 'draft': True}
    calls = []
    def send(request, **kwargs):
        calls.append(request.get_method())
        if request.get_method() == 'POST':
            raise TimeoutError('response lost after commit')
        return io.BytesIO(json.dumps(dict(payload, id=42)).encode())
    monkeypatch.setenv('FORGEJO_TOKEN', 'fixture')
    monkeypatch.setattr(release.urllib.request, 'urlopen', send)
    result = release.forgejo_release_request('POST', '/releases', json.dumps(payload).encode())
    assert result['id'] == 42
    assert calls == ['POST', 'GET']


def test_lost_workflow_dispatch_is_not_repeated(monkeypatch):
    calls = []
    def send(*args, **kwargs):
        calls.append(1)
        raise TimeoutError('response lost')
    monkeypatch.setenv('FORGEJO_TOKEN', 'fixture')
    monkeypatch.setattr(release.urllib.request, 'urlopen', send)
    with pytest.raises(TimeoutError):
        release.forgejo_release_request('POST', '/actions/workflows/build/dispatches', b'{}')
    assert len(calls) == 1


@pytest.mark.parametrize('download,valid', [(b'package', True), (b'changed', False), (b'pack', False), (b'package extra', False)])
def test_recovered_asset_requires_matching_contents_not_only_size(monkeypatch, download, valid):
    payload = b'--fixture\r\nContent-Disposition: form-data; name="attachment"\r\n\r\npackage\r\n--fixture--\r\n'
    origin = release.urllib.parse.urlsplit(release.FORGEJO_API)
    asset = {'id': 42, 'name': 'app.zip', 'size': 7,
             'browser_download_url': origin.scheme + '://' + origin.netloc + '/attachments/fixture'}
    calls = []

    def request(req, **kwargs):
        calls.append(req.get_method())
        if req.get_method() == 'POST':
            raise TimeoutError('upload response lost')
        return io.BytesIO(json.dumps([asset]).encode())

    monkeypatch.setenv('FORGEJO_TOKEN', 'fixture')
    monkeypatch.setattr(release.urllib.request, 'urlopen', request)
    monkeypatch.setattr(release.urllib.request, 'build_opener', lambda *args:
                        SimpleNamespace(open=lambda *a, **kw: io.BytesIO(download)))
    if valid:
        assert release.forgejo_release_request('POST', '/releases/1/assets?name=app.zip', payload) == asset
    else:
        with pytest.raises(RuntimeError):
            release.forgejo_release_request('POST', '/releases/1/assets?name=app.zip', payload)
    assert calls == ['POST', 'GET']


def test_reconciliation_never_sends_credentials_to_a_redirected_origin(monkeypatch):
    payload = b'--fixture\r\nContent-Disposition: form-data; name="attachment"\r\n\r\npackage\r\n--fixture--\r\n'
    origin = release.urllib.parse.urlsplit(release.FORGEJO_API)
    url = origin.scheme + '://' + origin.netloc + '/attachments/fixture'
    monkeypatch.setenv('FORGEJO_TOKEN', 'fixture')
    monkeypatch.setattr(release, 'forgejo_release_request', lambda *a:
                        [{'name': 'app.zip', 'size': 7, 'browser_download_url': url}])

    def opener(handler):
        def open_request(request, **kwargs):
            return handler.redirect_request(request, None, 302, 'Found', {}, 'https://elsewhere.invalid/file')
        return SimpleNamespace(open=open_request)

    monkeypatch.setattr(release.urllib.request, 'build_opener', opener)
    with pytest.raises(RuntimeError, match='another origin'):
        release._reconcile_forgejo_post('/releases/1/assets?name=app.zip', payload)
