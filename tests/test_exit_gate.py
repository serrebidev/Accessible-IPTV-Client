"""The exit gate: what the app is still doing when the user quits.

The gate warns about the work that would be cut short. Every kind of work
needs its own warning: a scheduled recording hid the running download, and
the download was truncated without the user ever being asked.
"""

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402


class _Event:
    def __init__(self):
        self.vetoed = False

    def CanVeto(self):
        return True

    def Veto(self):
        self.vetoed = True


def _client(downloads=(), jobs=()):
    client = types.SimpleNamespace()
    client.minimize_to_tray = False
    client._update_install_pending = False
    client._exit_forced = False
    client._exit_requested = True
    client._catchup_downloads = dict(downloads)
    client.recorder = types.SimpleNamespace(has_active=lambda: False)
    client._upcoming_dvr_jobs = lambda: list(jobs)
    client._schedule_window_label = lambda job: "20:00 - 21:00"
    return client


def test_exit_warns_about_a_running_download_when_a_recording_is_scheduled(monkeypatch):
    boxes = []

    def _box(message, caption, style=0, **_kwargs):
        boxes.append((message, caption))
        # The download is refused, so the exit stops here and the app stays.
        return main.wx.NO if caption == "Download in progress" else main.wx.YES

    monkeypatch.setattr(main, "message_box", _box)
    client = _client(downloads={"d1": object()},
                     jobs=[{"display_title": "Evening News", "title": "Evening News",
                            "start_ts": 0, "stop_ts": 0}])
    event = _Event()

    main.IPTVClient.on_close(client, event)

    captions = [caption for _message, caption in boxes]
    assert "Scheduled recordings" in captions
    assert "Download in progress" in captions, \
        "the scheduled recording hid the running download"
    assert event.vetoed, "the exit went ahead although the answer was No"
    assert client._exit_requested is False


def test_a_running_download_alone_is_warned_about(monkeypatch):
    boxes = []
    monkeypatch.setattr(main, "message_box",
                        lambda message, caption, style=0, **kw: boxes.append(caption) or main.wx.NO)
    client = _client(downloads={"d1": object()})
    event = _Event()

    main.IPTVClient.on_close(client, event)

    assert boxes == ["Download in progress"]
    assert event.vetoed
