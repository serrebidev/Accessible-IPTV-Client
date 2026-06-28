import json

import updater


class _Response:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._payload


def test_fetch_latest_release_uses_supplied_timeout(monkeypatch):
    calls = []

    def fake_urlopen(req, timeout):
        calls.append((req.full_url, timeout))
        return _Response({"tag_name": "v1.2.3"})

    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen)

    release = updater.fetch_latest_release("owner", "repo", timeout=4.5)

    assert release["tag_name"] == "v1.2.3"
    assert calls == [
        ("https://api.github.com/repos/owner/repo/releases/latest", 4.5)
    ]


def test_fetch_update_manifest_uses_supplied_timeout(monkeypatch):
    calls = []
    release = {
        "assets": [
            {
                "name": "manifest.json",
                "browser_download_url": "https://example.test/manifest.json",
            }
        ]
    }
    manifest_payload = {
        "version": "1.2.3",
        "asset_filename": "IPTVClient.zip",
        "download_url": "https://example.test/IPTVClient.zip",
        "sha256": "abc123",
    }

    def fake_urlopen(req, timeout):
        calls.append((req.full_url, timeout))
        return _Response(manifest_payload)

    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen)

    manifest = updater.fetch_update_manifest(
        release,
        "manifest.json",
        timeout=6.0,
    )

    assert manifest.version == "1.2.3"
    assert manifest.asset_filename == "IPTVClient.zip"
    assert calls == [("https://example.test/manifest.json", 6.0)]
