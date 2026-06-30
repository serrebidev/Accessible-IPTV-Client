import hashlib
import json
import os

import pytest

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


class _DownloadResponse:
    """Minimal urlopen() stand-in that yields the payload in small chunks."""

    def __init__(self, data: bytes, chunk_size: int = 4, content_length: bool = True):
        self._data = data
        self._pos = 0
        self._chunk = chunk_size
        self.headers = {"Content-Length": str(len(data))} if content_length else {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size=-1):
        if self._pos >= len(self._data):
            return b""
        end = min(self._pos + self._chunk, len(self._data))
        chunk = self._data[self._pos:end]
        self._pos = end
        return chunk


def test_download_reports_progress_and_hashes(monkeypatch, tmp_path):
    payload = b"accessible-iptv-client update payload, streamed in small chunks"
    monkeypatch.setattr(
        updater.urllib.request, "urlopen",
        lambda req, timeout: _DownloadResponse(payload),
    )
    fractions = []

    def progress(fraction):
        fractions.append(fraction)
        return True

    dest = tmp_path / "update.zip"
    digest = updater.download_file_with_sha256(
        "https://example.test/update.zip", str(dest), progress_cb=progress
    )

    assert digest == hashlib.sha256(payload).hexdigest()
    assert dest.read_bytes() == payload
    assert fractions and fractions[-1] == 1.0
    assert all(0.0 <= f <= 1.0 for f in fractions)
    assert fractions == sorted(fractions)  # monotonic non-decreasing


def test_download_without_content_length_reports_none(monkeypatch, tmp_path):
    payload = b"no content-length header on this response"
    monkeypatch.setattr(
        updater.urllib.request, "urlopen",
        lambda req, timeout: _DownloadResponse(payload, content_length=False),
    )
    seen = []
    dest = tmp_path / "update.zip"
    updater.download_file_with_sha256(
        "https://example.test/update.zip", str(dest),
        progress_cb=lambda fraction: (seen.append(fraction), True)[1],
    )
    assert seen and all(f is None for f in seen)


def test_download_cancel_raises_update_cancelled(monkeypatch, tmp_path):
    monkeypatch.setattr(
        updater.urllib.request, "urlopen",
        lambda req, timeout: _DownloadResponse(b"x" * 64, chunk_size=4),
    )
    dest = tmp_path / "update.zip"
    with pytest.raises(updater.UpdateCancelled):
        updater.download_file_with_sha256(
            "https://example.test/update.zip", str(dest),
            progress_cb=lambda fraction: False,
        )


def test_run_hidden_hides_console_on_windows(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return "result"

    monkeypatch.setattr(updater.subprocess, "run", fake_run)
    result = updater.run_hidden(["whoami"], capture_output=True)

    assert result == "result"
    assert captured["cmd"] == ["whoami"]
    if os.name == "nt":
        assert captured["kwargs"]["creationflags"] & updater._CREATE_NO_WINDOW
        assert captured["kwargs"]["startupinfo"] is not None
    else:
        assert "creationflags" not in captured["kwargs"]


def test_popen_hidden_detaches_stdio(monkeypatch):
    captured = {}

    def fake_popen(cmd, **kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(updater.subprocess, "Popen", fake_popen)
    updater.popen_hidden(["cmd", "/c", "echo", "hi"])

    assert captured["stdin"] == updater.subprocess.DEVNULL
    assert captured["stdout"] == updater.subprocess.DEVNULL
    assert captured["stderr"] == updater.subprocess.DEVNULL
    assert captured["close_fds"] is True


@pytest.mark.skipif(os.name != "nt", reason="window-hiding flags are Windows-only")
def test_popen_hidden_falls_back_without_breakaway(monkeypatch):
    attempts = []

    class _FakeProc:
        pass

    def fake_popen(cmd, **kwargs):
        flags = kwargs.get("creationflags", 0)
        attempts.append(flags)
        if flags & updater._CREATE_BREAKAWAY_FROM_JOB:
            raise OSError("breakaway from job not permitted")
        return _FakeProc()

    monkeypatch.setattr(updater.subprocess, "Popen", fake_popen)
    proc = updater.popen_hidden(["cmd", "/c", "echo", "hi"])

    assert isinstance(proc, _FakeProc)
    assert len(attempts) == 2
    assert attempts[0] & updater._CREATE_BREAKAWAY_FROM_JOB
    assert not (attempts[1] & updater._CREATE_BREAKAWAY_FROM_JOB)
    assert attempts[1] & updater._CREATE_NO_WINDOW
    assert attempts[1] & updater._CREATE_NEW_PROCESS_GROUP
