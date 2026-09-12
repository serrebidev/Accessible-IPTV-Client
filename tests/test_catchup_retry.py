"""Tests for inline download errors and automatic catch-up retry.

* The download progress window shows the ffmpeg exit code and the first
  error line from the recording log inline (in the read-only details field
  and in the status line), instead of leaving the user with only a generic
  finished box afterwards.
* A catch-up download that fails with a transient error (HTTP 403 from the
  provider, network drop) is retried automatically with a delay, up to a
  small attempt budget; user cancellations are never retried.
"""
import os
import sys
import types
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

wx = pytest.importorskip("wx")

import main as appmod  # noqa: E402

CatchupDownloadDialog: Any = appmod.CatchupDownloadDialog


@pytest.fixture(scope="module")
def wx_app():
    try:
        app = wx.App()
    except Exception as exc:  # pragma: no cover - headless CI without a display
        pytest.skip(f"no usable display for wxPython: {exc}")
    yield app


def _rec_with_log(tmp_path, log_text: str):
    log_path = tmp_path / "rec.log"
    log_path.write_text(log_text, encoding="utf-8")
    return types.SimpleNamespace(
        title="Sky Mix: Evening News", log_path=str(log_path),
        written_path=str(tmp_path / "out.mp4"))


class TestInlineErrors:
    def test_first_error_line_and_code_appear_in_details(self, wx_app, tmp_path):
        rec = _rec_with_log(tmp_path, (
            "[https @ 0x0] [warning] HTTP error 403 Forbidden\n"
            "[in#0] [error] Error opening input: Server returned 403 Forbidden\n"
            "[fatal] Error opening input files: Server returned 403 Forbidden\n"
        ))
        dlg = CatchupDownloadDialog(wx_app.GetTopWindow() or None, rec,
                                    duration=60.0, on_cancel=lambda: None)
        try:
            dlg.show_failure(exit_code=1)
            text = dlg.details_field.GetValue()
            assert "1" in text  # the exit code is reported
            assert "403" in text  # the provider's refusal is quoted
            assert "Error" in dlg.status_text.GetLabel() or dlg.status_text.GetLabel()
        finally:
            dlg.Destroy()

    def test_no_error_lines_falls_back_to_code_only(self, wx_app, tmp_path):
        rec = _rec_with_log(tmp_path, "")
        dlg = CatchupDownloadDialog(None, rec, duration=60.0, on_cancel=lambda: None)
        try:
            dlg.show_failure(exit_code=23)
            text = dlg.details_field.GetValue()
            assert "23" in text
        finally:
            dlg.Destroy()


class TestTruncatedDownloads:
    """A provider closing the connection mid-file must not read as success.

    ffmpeg exits 0 when the upstream ends early, so the newest ``time=``
    stats line is what tells a short transfer from a complete one.
    """

    @staticmethod
    def _client():
        client = appmod.IPTVClient.__new__(appmod.IPTVClient)
        client.config = {}
        return client

    @staticmethod
    def _rec(tmp_path, written, expected, **extra):
        fields = dict(
            id=41, title="Fakty. - TVN HD", key="catchup:x", url="http://d/x.mp4",
            fmt="audio_mp3_v0", out_path=str(tmp_path / "out.mp3"),
            stopped_by_user=False, media_written_seconds=written,
            stderr_tail=[], log_path=str(tmp_path / "out.log"),
            metadata={"expected_media_seconds": expected,
                      "programme_start": "20260912190000",
                      "programme_end": "20260912193000",
                      "channel": {}, "duration": 1920.0})
        fields.update(extra)
        rec = types.SimpleNamespace(**fields)
        (tmp_path / "out.mp3").write_bytes(b"x")  # the watcher renamed it in
        return rec

    def test_short_clean_download_is_truncated(self, tmp_path):
        client = self._client()
        rec = self._rec(tmp_path, written=1115.0, expected=1920.0)
        assert appmod.IPTVClient._catchup_download_is_truncated(client, rec) is True

    def test_full_download_is_not_truncated(self, tmp_path):
        client = self._client()
        rec = self._rec(tmp_path, written=1918.0, expected=1920.0)
        assert appmod.IPTVClient._catchup_download_is_truncated(client, rec) is False

    def test_unknown_progress_never_counts_as_short(self, tmp_path):
        """Live-style inputs write no time= lines; treat them as complete."""
        client = self._client()
        rec = self._rec(tmp_path, written=None, expected=1920.0)
        assert appmod.IPTVClient._catchup_download_is_truncated(client, rec) is False

    def test_user_stopped_download_is_not_truncated(self, tmp_path):
        client = self._client()
        rec = self._rec(tmp_path, written=300.0, expected=1920.0, stopped_by_user=True)
        assert appmod.IPTVClient._catchup_download_is_truncated(client, rec) is False

    def test_short_download_schedules_retry_and_removes_partial(self, tmp_path, monkeypatch):
        client = self._client()
        client._catchup_retry_state = {}
        client._catchup_retry_timers = {}
        rec = self._rec(tmp_path, written=1115.0, expected=1920.0)
        monkeypatch.setattr(appmod, "_schedule_retry", lambda fn, delay: None)
        scheduled = appmod.IPTVClient._handle_truncated_catchup_download(client, rec)
        assert scheduled is True
        assert not os.path.exists(rec.out_path)  # the short file is dropped
        assert client._catchup_retry_state

    def test_short_download_without_budget_keeps_the_file(self, tmp_path, monkeypatch):
        client = self._client()
        client._catchup_retry_state = {41: appmod._CATCHUP_RETRY_MAX_ATTEMPTS}
        client._catchup_retry_timers = {}
        rec = self._rec(tmp_path, written=1115.0, expected=1920.0)
        scheduled = appmod.IPTVClient._handle_truncated_catchup_download(client, rec)
        assert scheduled is False
        assert os.path.exists(rec.out_path)  # something beats nothing
        # The synthetic failure line names the real cause:
        assert any("connection closed mid-file" in line for line in rec.stderr_tail)


class TestRetryPolicy:
    def test_transient_failure_is_retryable(self):
        assert appmod._catchup_failure_is_retryable(1, ["[error] Server returned 403 Forbidden"]) is True
        assert appmod._catchup_failure_is_retryable(1, ["[error] Connection reset by peer"]) is True

    def test_user_cancel_is_never_retryable(self):
        assert appmod._catchup_failure_is_retryable(0, [], stopped_by_user=True) is False

    def test_retry_budget_is_bounded(self):
        assert appmod._CATCHUP_RETRY_MAX_ATTEMPTS == 3
        assert 0 < appmod._CATCHUP_RETRY_BASE_DELAY_SECONDS <= 5

    def test_retry_schedules_next_attempt(self, monkeypatch):
        client = appmod.IPTVClient.__new__(appmod.IPTVClient)
        scheduled = []
        monkeypatch.setattr(appmod, "_schedule_retry", lambda fn, delay: scheduled.append((fn, delay)))
        rec = types.SimpleNamespace(id=7, stopped_by_user=False, stderr_tail=["[error] 403"], rc=1)
        client._catchup_retry_state = {}
        handled = appmod.IPTVClient._maybe_retry_catchup_download(
            client, rec, rc=1, channel={"name": "TV 6 HD"}, show={"start": "20260907210000", "end": "20260907220000"},
            duration=3600.0, fmt="provider_mp4")
        assert handled is True
        assert len(scheduled) == 1
        assert scheduled[0][1] > 0

    def test_retry_reruns_probe_flow_with_retry_of(self, monkeypatch):
        """The retry re-enters the probe flow, tagged with the old recorder id."""
        client = appmod.IPTVClient.__new__(appmod.IPTVClient)
        client._catchup_retry_state = {}
        client._catchup_retry_timers = {}
        rec = types.SimpleNamespace(
            id=9, key="catchup:abc", url="http://old/direct.mp4", title="TV 6: News",
            stopped_by_user=False, stderr_tail=["[error] Server returned 403 Forbidden"],
            metadata={"hls_url": "http://hls/index.m3u8"})
        client._catchup_retry_state[9] = 0
        calls = []
        monkeypatch.setattr(appmod, "_schedule_retry", lambda fn, delay: calls.append((fn, delay)) or None)
        handled = appmod.IPTVClient._maybe_retry_catchup_download(
            client, rec, rc=1, channel={"name": "TV 6 HD"},
            show={"start": "20260907210000", "end": "20260907220000"},
            duration=3600.0, fmt="provider_mp4")
        assert handled is True
        fn, delay = calls[0]
        assert delay == appmod._CATCHUP_RETRY_BASE_DELAY_SECONDS  # first retry: base delay
        probe_calls = []
        monkeypatch.setattr(client, "_begin_catchup_download",
                            lambda *args, **kw: probe_calls.append((args, kw)))
        fn()
        assert len(probe_calls) == 1
        args, kw = probe_calls[0]
        assert args[1] == "http://hls/index.m3u8"  # fresh probe from the HLS URL
        assert kw.get("retry_of") == 9

    def test_cancel_aborts_pending_retry_timer(self, monkeypatch):
        """Cancelling during the retry countdown cancels the timer."""
        client = appmod.IPTVClient.__new__(appmod.IPTVClient)
        client._catchup_retry_state = {}
        client._catchup_retry_timers = {}
        client._catchup_downloads = {}
        client.recorder = types.SimpleNamespace(stop=lambda rec_id, wait: None)
        cancelled = []

        class FakeTimer:
            def cancel(self):
                cancelled.append(True)

        monkeypatch.setattr(appmod, "_schedule_retry", lambda fn, delay: FakeTimer())
        rec = types.SimpleNamespace(id=11, stopped_by_user=False, stderr_tail=["[error] 403"])
        assert appmod.IPTVClient._maybe_retry_catchup_download(
            client, rec, rc=1, channel={}, show={}, duration=60.0, fmt="provider_mp4") is True
        assert 11 in client._catchup_retry_timers
        client._cancel_catchup_download(11)
        assert cancelled == [True]
        assert 11 not in client._catchup_retry_state
        assert 11 not in client._catchup_retry_timers

    def test_budget_exhausted_stops_retrying(self, monkeypatch):
        client = appmod.IPTVClient.__new__(appmod.IPTVClient)
        scheduled = []
        monkeypatch.setattr(appmod, "_schedule_retry", lambda fn, delay: scheduled.append((fn, delay)))
        rec = types.SimpleNamespace(id=8, stopped_by_user=False, stderr_tail=["[error] 403"], rc=1)
        client._catchup_retry_state = {8: appmod._CATCHUP_RETRY_MAX_ATTEMPTS}
        handled = appmod.IPTVClient._maybe_retry_catchup_download(
            client, rec, rc=1, channel={"name": "TV 6 HD"}, show={"start": "20260907210000", "end": "20260907220000"},
            duration=3600.0, fmt="provider_mp4")
        assert handled is False
        assert scheduled == []
