"""Public playback commands and native dialog behaviour for the recording changes."""
import datetime as dt
import threading
import time
from unittest.mock import Mock

import pytest
import wx

import dialogs_misc
import dvr
import media_navigation_ui as navigation
import options
import recording_library
import recording_library_ui
import recording_power
from subtitle_cues import Cue, parse
from subtitle_pipeline import TimedTextSource


def pump(predicate):
    deadline = time.monotonic() + 4
    while not predicate() and time.monotonic() < deadline:
        wx.GetApp().Yield()
        time.sleep(.002)
    assert predicate()


@pytest.fixture
def frame():
    app = wx.GetApp() or wx.App(False)

    class Player(navigation.MediaNavigationMixin, wx.Frame):
        pass

    window = Player(None)
    window.player = Mock()
    window.player.set_rate.return_value = 0
    window.player.video_get_spu_delay.return_value = 500_000
    window._current_stream_kind = "vod"
    window._episode_channel = {"local-recording": "recording.mkv"}
    window._vlc_generation = 1
    window._destroyed = False
    window._navigation_message = Mock()
    window._seek_media = Mock()
    yield window
    window.Destroy()
    app.Yield()


def test_rate_command_direct_reset_and_live_protection(frame, monkeypatch):
    def faster(dialog):
        dialog.SetSelection(3)
        return wx.ID_OK
    monkeypatch.setattr(navigation, "show_modal", faster)
    frame._choose_recording_speed()
    frame.player.set_rate.assert_called_once_with(1.5)
    assert frame._local_playback_rate == 1.5
    frame._restore_normal_speed()
    assert frame._local_playback_rate == 1
    frame._choose_recording_speed()
    frame._reset_recording_speed()
    frame.player.set_rate.assert_called_with(1.0)
    for kind, channel in (("live", {}), ("vod", {"url": "https://example.invalid/video"})):
        frame._current_stream_kind, frame._episode_channel = kind, channel
        frame.player.set_rate.reset_mock()
        frame._choose_recording_speed()
        frame._restore_normal_speed()
        frame.player.set_rate.assert_not_called()


def test_rate_change_checks_result_and_same_stream(frame, monkeypatch):
    frame.player.set_rate.return_value = -1
    def choose(dialog):
        dialog.SetSelection(4)
        return wx.ID_OK
    monkeypatch.setattr(navigation, "show_modal", choose)
    frame._choose_recording_speed()
    assert not hasattr(frame, "_local_playback_rate")
    frame.player.set_rate.reset_mock()
    def switched(dialog):
        frame._vlc_generation += 1
        return choose(dialog)
    monkeypatch.setattr(navigation, "show_modal", switched)
    frame._choose_recording_speed()
    frame.player.set_rate.assert_not_called()


@pytest.mark.parametrize("change_track", [False, True])
def test_find_future_subtitle_native_list_then_seek_with_delay(frame, monkeypatch, change_track):
    frame._subtitle_file_source = TimedTextSource((Cue(100, 400, "Első sor"),
        Cue(1300, 1700, "Jó ESTÉT!"), Cue(5000, 7000, "Megint jó estét!")))
    seen = []
    def modal(dialog):
        if isinstance(dialog, wx.TextEntryDialog):
            dialog.SetValue("  EsTéT  ")
        else:
            listing, = [child for child in dialog.GetChildren() if isinstance(child, navigation.SubtitleMatches)]
            assert listing.GetItemCount() == 2
            assert listing.GetItemText(1, 1) == "Megint jó estét!"
            listing.Select(0, False)
            listing.Select(1)
            seen.append(listing.GetItemText(1, 0))
            if change_track:
                frame._subtitle_file_source = TimedTextSource(())
        return wx.ID_OK
    monkeypatch.setattr(navigation, "show_modal", modal)
    frame._find_subtitle_text()
    pump(lambda: not frame._background_operations)
    assert seen == [navigation.clock_text(5000)]
    if change_track:
        frame._seek_media.assert_not_called()
    else:
        frame._seek_media.assert_called_once_with(target=5500)


@pytest.mark.parametrize("markup", ["<br>", "<BR />", "<br/>", "\n"])
def test_spoken_line_break_without_breaking_inline_word(markup):
    cues = parse("1\n00:00:00,100 --> 00:00:02,000\nJ<i>ó</i>" + markup + "es<b>té</b>t!\n")
    assert [cue.text for cue in cues] == ["Jó estét!"]


@pytest.mark.parametrize("choice", [wx.ID_YES, wx.ID_NO, wx.ID_CANCEL])
def test_issue_browser_failure_preserves_title_and_body(frame, monkeypatch, choice):
    title, body = "Guide", "Őszi műsor\nMásodik sor."
    asks = Mock(side_effect=[title, body])
    launch = Mock(side_effect=[False, True])
    dialog = Mock()
    dialog.ShowModal.return_value = choice
    clipboard = Mock()
    monkeypatch.setattr(dialogs_misc, "_ask_text", asks)
    monkeypatch.setattr(wx, "LaunchDefaultBrowser", launch)
    monkeypatch.setattr(wx, "MessageDialog", lambda *a: dialog)
    monkeypatch.setattr(wx, "TheClipboard", clipboard)
    dialogs_misc.report_issue(frame)
    assert asks.call_count == 2
    dialog.Destroy.assert_called_once()
    if choice == wx.ID_YES:
        assert launch.call_count == 2 and launch.call_args_list[0] == launch.call_args_list[1]
    elif choice == wx.ID_NO:
        assert clipboard.SetData.call_args.args[0].GetText() == title + "\n\n" + body
        clipboard.Close.assert_called_once()
    else:
        clipboard.Open.assert_not_called()


def test_folder_switch_while_default_drive_is_blocked(frame, monkeypatch, tmp_path):
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    slow, other = tmp_path / "slow", tmp_path / "other"
    blocked = threading.Event()
    for path in (slow, other):
        path.mkdir()
    frame.config = {"recordings_dir": str(tmp_path), "recording_library_folders": [str(slow), str(other)]}
    frame.recorder = Mock()
    frame.recorder.list_active.return_value = []
    def default(_config):
        assert not wx.IsMainThread()
        entered.set()
        assert release.wait(6)
        return str(tmp_path)
    def scan(path, *args, **kwargs):
        assert not wx.IsMainThread()
        if path == str(slow):
            blocked.set()
            assert release.wait(6)
        if path == str(other):
            finished.set()
        return []
    monkeypatch.setattr(options, "get_recordings_dir", default)
    monkeypatch.setattr(recording_library, "scan", scan)
    dialog = recording_library_ui.RecordingLibraryDialog(frame)
    try:
        pump(entered.is_set)
        assert dialog.folder.IsEnabled()
        dialog.folder.SetSelection(1)
        dialog.change_folder(None)
        pump(blocked.is_set)
        assert dialog.folder.IsEnabled()
        dialog.folder.SetSelection(2)
        dialog.change_folder(None)
        pump(lambda: finished.is_set() and not dialog.busy)
        assert not release.is_set() and dialog.directory == str(other)
    finally:
        release.set()
        dialog.Destroy()
        wx.GetApp().Yield()


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="Requires a per-process test time zone")
@pytest.mark.parametrize("march", [True, False])
def test_pause_covers_local_dates_and_preserves_wall_clock_across_dst(monkeypatch, march):
    import os
    original = os.environ.get("TZ")
    monkeypatch.setenv("TZ", "Europe/Budapest")
    time.tzset()
    try:
        dates = (dt.date(2026, 3, 28), dt.date(2026, 3, 29)) if march else (dt.date(2026, 10, 24), dt.date(2026, 10, 25))
        start = dt.datetime.combine(dates[0], dt.time(0, 5))
        end = start + dt.timedelta(minutes=35)
        stamp = lambda value: dt.datetime.fromtimestamp(value.timestamp(), dt.timezone.utc).strftime("%Y%m%d%H%M%S")
        row = dvr.build_job({"name": "TV", "url": "file:///recording"},
                            {"title": "Evening", "start": stamp(start), "end": stamp(end)},
                            "provider_mkv", repeat="daily", pre_padding_minutes=10)
        row["pause_dates"] = [day.isoformat() for day in dates]
        assert dvr.paused_occurrence(row)
        now = start.timestamp() - 7200
        _awake, alarm = recording_power.desired_state({"wake_for_recordings": True}, False, [row], now)
        after = dates[1] + dt.timedelta(days=1)
        assert alarm == dt.datetime.combine(after, dt.time(0, 5)).timestamp() - 11 * 60
    finally:
        if original is None:
            monkeypatch.delenv("TZ")
        else:
            monkeypatch.setenv("TZ", original)
        time.tzset()


def test_calendar_export_revalidates_jobs_before_replacing_file(frame, tmp_path, monkeypatch):
    import planning_tools_ui
    first = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=2)
    def booking(when):
        return dvr.build_job({"name": "TV", "url": "file:///unused"},
                             {"title": "Film", "start": when.strftime("%Y%m%d%H%M%S"),
                              "end": (when + dt.timedelta(minutes=30)).strftime("%Y%m%d%H%M%S")},
                             "provider_mkv")
    jobs = [booking(first), booking(first + dt.timedelta(days=1))]
    frame.scheduler = dvr.DVRScheduler(str(tmp_path / "schedule.json"), on_start=Mock(), on_stop=Mock())
    for job in jobs:
        frame.scheduler.add_job(job)
    rows = [frame.scheduler.get_job(job["id"]) for job in jobs]
    path = tmp_path / "recordings.ics"
    def modal(dialog):
        dialog.GetPath = lambda: str(path)
        return wx.ID_OK
    messages = Mock()
    monkeypatch.setattr(planning_tools_ui, "show_modal", modal)
    monkeypatch.setattr(planning_tools_ui, "message_box", messages)
    planning_tools_ui.export_recordings(frame, rows)
    pump(lambda: messages.called)
    assert path.is_file(), messages.call_args
    data = path.read_bytes()
    assert data.count(b"BEGIN:VEVENT") == 2
    frame.scheduler.cancel_job(rows[0]["id"])
    messages.reset_mock()
    planning_tools_ui.export_recordings(frame, rows)
    pump(lambda: messages.called)
    assert "changed" in messages.call_args.args[0] and path.read_bytes() == data


def test_shutdown_does_not_wait_for_scheduler_on_event_thread(frame, monkeypatch):
    import main
    entered, release = threading.Event(), threading.Event()
    frame.recorder = Mock()
    frame.recorder.begin_shutdown.return_value = False
    frame.dvr_scheduler = Mock()
    frame._finish_application_exit = Mock()
    def stop(*, wait=False, timeout=5):
        if wait:
            assert not wx.IsMainThread() and timeout is None
            entered.set()
            assert release.wait(5)
    frame.dvr_scheduler.stop.side_effect = stop
    try:
        assert main.IPTVClient._release_recordings_on_exit(frame)
        pump(entered.is_set)
        frame._finish_application_exit.assert_not_called()
    finally:
        release.set()
    pump(lambda: frame._finish_application_exit.called)


@pytest.mark.parametrize("repeat", ["daily", "series"])
def test_pause_preview_uses_padding_and_only_bookings_from_this_rule(repeat):
    import planning_tools
    when = dt.datetime.now().replace(hour=0, minute=5, second=0, microsecond=0) + dt.timedelta(days=2)
    now = (when - dt.timedelta(days=1)).timestamp()
    def booking(day):
        stamp = lambda val: dt.datetime.fromtimestamp(val.timestamp(), dt.timezone.utc).strftime("%Y%m%d%H%M%S")
        return dvr.build_job({"name": "TV", "url": "file:///unused"},
                             {"title": "Episode", "start": stamp(day), "end": stamp(day + dt.timedelta(minutes=30))},
                             "provider_mkv", pre_padding_minutes=15, repeat=repeat)
    rule = booking(when)
    following = when + dt.timedelta(days=2)
    child = dict(booking(following), series_source=rule["id"])
    unrelated = dict(booking(following - dt.timedelta(hours=3)), series_source="other")
    period = [when.date().isoformat(), (when.date() + dt.timedelta(days=1)).isoformat()]
    assert planning_tools.pause_preview(rule, period, [rule, unrelated, child], now=now) == (when, following)


@pytest.mark.parametrize("switch_away", [False, True])
def test_all_folders_publish_healthy_results_while_share_is_still_scanning(
        frame, monkeypatch, tmp_path, switch_away):
    offline, healthy = tmp_path / "offline", tmp_path / "healthy"
    offline.mkdir()
    healthy.mkdir()
    (offline / "stale.mkv").write_bytes(b"fixture")
    (healthy / "available.mkv").write_bytes(b"fixture")
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    frame.config = {"recordings_dir": str(offline), "recording_library_folders": [str(healthy)]}
    frame.recorder = Mock()
    frame.recorder.list_active.return_value = []
    scan = recording_library.scan
    def folder_scan(path, *args, **kwargs):
        if path != str(offline):
            return scan(path, *args, **kwargs)
        entered.set()
        assert release.wait(8)
        try:
            return scan(path, *args, **kwargs)
        finally:
            finished.set()
    monkeypatch.setattr(recording_library, "scan", folder_scan)
    dialog = recording_library_ui.RecordingLibraryDialog(frame)
    try:
        pump(entered.is_set)
        dialog.folder.SetSelection(len(dialog.directories))
        dialog.change_folder(None)
        pump(lambda: len(dialog.rows) == 1 and not dialog.filter_busy)
        assert dialog.rows[0]["path"] == str(healthy / "available.mkv")
        assert dialog.play.IsEnabled() and dialog._scanning
        if switch_away:
            dialog.folder.SetSelection(1)
            dialog.change_folder(None)
            pump(lambda: not dialog.busy and not dialog.filter_busy)
        release.set()
        pump(finished.is_set)
        pump(lambda: not dialog._scanning and not dialog.filter_busy)
        assert len(dialog.rows) == (1 if switch_away else 2)
        assert dialog.selected()["path"] == str(healthy / "available.mkv")
    finally:
        release.set()
        dialog.closed = True
        dialog.worker.close()
        for worker in dialog._scan_workers.values():
            worker.close()
        dialog.Destroy()
        wx.GetApp().Yield()
