"""A hand-started EPG import has to say when it has finished.

The import runs for anything from seconds to the better part of an hour on a
worker thread with no window of its own. Before this, ``File > Import EPG to
DB`` said "will start in the background" and then never spoke again, so the
only way to know it had ended was to go looking for new programme data --
useless with a screen reader. The automatic refresh must stay silent, though:
it fires on its own schedule and a box popping up unasked would steal focus.
"""

import os
import sys
import threading
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402

C = main.IPTVClient

BOUND = (
    "start_epg_import_background",
    "finish_import_background",
    "_report_epg_import_finished",
    "import_epg",
    "_offer_epg_schema_repair",
    "_hash_epg_sources",
    "_should_auto_import_epg",
)


def _client(monkeypatch, sources=("http://example.invalid/epg.xml",), epg_enabled=True):
    """An IPTVClient stub carrying the real import/notify methods."""
    client = types.SimpleNamespace()
    client.epg_importing = False
    client._epg_import_notify = False
    client.epg_sources = list(sources)
    client.config = {"epg_enabled": epg_enabled}
    client._epg_match_lock = threading.Lock()
    client._epg_match_cache = {}
    client.boxes = []
    client.queued = []
    client.highlighted = []
    client.threads = []
    client.on_highlight = lambda: client.highlighted.append(True)
    client._refresh_now_playing_labels = lambda: None
    client._show_or_queue_message_box = lambda m, c, s: client.queued.append((m, c, s))
    for name in BOUND:
        setattr(client, name, types.MethodType(getattr(C, name), client))

    monkeypatch.setattr(main, "save_config", lambda cfg: None)
    monkeypatch.setattr(main, "message_box",
                        lambda msg, cap, style=0, **kw: client.boxes.append((msg, cap)) or 0)

    class _Thread:
        """Records the worker instead of running it."""

        def __init__(self, target=None, daemon=None, name=None, args=(), kwargs=None):
            self.target = target
            self.args = args

        def start(self):
            client.threads.append(self.target)

    monkeypatch.setattr(main.threading, "Thread", _Thread)
    return client


class TestManualImportReportsCompletion:
    def test_manual_import_arms_the_completion_notice(self, monkeypatch):
        client = _client(monkeypatch)

        client.import_epg(None)

        assert client.epg_importing is True
        assert client._epg_import_notify is True
        assert [cap for _msg, cap in client.boxes] == ["Import Started"]

    def test_finishing_a_manual_import_says_so(self, monkeypatch):
        client = _client(monkeypatch)
        client.import_epg(None)

        client.finish_import_background(True)

        assert client.epg_importing is False
        assert [cap for _msg, cap, _style in client.queued] == ["Import Complete"]
        # The notice does not survive into the next, automatic import.
        assert client._epg_import_notify is False

    def test_a_failed_manual_import_says_that_instead(self, monkeypatch):
        client = _client(monkeypatch)
        client.import_epg(None)

        client.finish_import_background(False)

        assert [cap for _msg, cap, _style in client.queued] == ["Import Failed"]
        # A failure must not be recorded as a successful refresh, or the
        # automatic import would skip its next run.
        assert "epg_last_import_epoch" not in client.config

    def test_the_guide_is_reloaded_before_the_box_appears(self, monkeypatch):
        """The box is modal; the refresh must already be under way behind it."""
        client = _client(monkeypatch)
        client.import_epg(None)
        client.threads.clear()
        order = []
        client.on_highlight = lambda: order.append("highlight")
        client._show_or_queue_message_box = lambda *a: order.append("box")

        client.finish_import_background(True)

        assert order == ["highlight", "box"]


class TestAutomaticImportStaysSilent:
    def test_background_refresh_shows_no_box(self, monkeypatch):
        client = _client(monkeypatch)

        assert client.start_epg_import_background(force=True) is True
        client.finish_import_background(True)

        assert client.queued == []
        assert client.boxes == []


class TestImportThatNeverStarts:
    def test_no_sources_warns_and_promises_nothing(self, monkeypatch):
        client = _client(monkeypatch, sources=())

        client.import_epg(None)

        assert [cap for _msg, cap in client.boxes] == ["No Sources"]
        assert client.epg_importing is False
        assert client._epg_import_notify is False

    def test_epg_turned_off_warns_instead_of_promising_a_result(self, monkeypatch):
        """Otherwise "will start in the background" was shown for an import
        that start_epg_import_background silently declined to run."""
        client = _client(monkeypatch, epg_enabled=False)

        client.import_epg(None)

        assert [cap for _msg, cap in client.boxes] == ["EPG Not Available"]
        assert client.epg_importing is False

    def test_a_second_import_is_refused_while_one_runs(self, monkeypatch):
        client = _client(monkeypatch)
        client.import_epg(None)
        client.boxes.clear()

        client.import_epg(None)

        assert [cap for _msg, cap in client.boxes] == ["In Progress"]

    def test_start_reports_whether_it_actually_started(self, monkeypatch):
        client = _client(monkeypatch)
        assert client.start_epg_import_background(force=True, notify=True) is True
        assert client.start_epg_import_background(force=True, notify=True) is False


def test_schema_repair_starts_a_real_import(monkeypatch):
    """Accepting the "database is from an older version" repair must import.

    It used to launch ``self._refresh_epg`` on a thread - a method that has
    never existed on IPTVClient - so saying Yes raised AttributeError and the
    database stayed broken with no sign that anything had gone wrong.
    """
    client = _client(monkeypatch)
    monkeypatch.setattr(main, "message_box",
                        lambda msg, cap, style=0, **kw: client.boxes.append((msg, cap)) or main.wx.YES)

    client._offer_epg_schema_repair()

    assert client.epg_importing is True
    assert client._epg_import_notify is True
    assert client.threads, "no import worker was started"


def test_schema_repair_declined_starts_nothing(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr(main, "message_box",
                        lambda msg, cap, style=0, **kw: main.wx.NO)

    client._offer_epg_schema_repair()

    assert client.epg_importing is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
