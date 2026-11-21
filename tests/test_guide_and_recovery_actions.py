"""Exercise the same guide, archive, favourites and seek actions as the native UI."""
import datetime as dt
from pathlib import Path
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import wx

import dvr
import favorite_collections as lists
import favorites
from internal_player import InternalPlayerFrame
import main
import personal_tools_ui as ui
import playlist
import programme_reminders as reminders
import recorder
import recording_library as library
from recording_library_ui import RecordingLibraryDialog


def channel(cid, name="Régió TV"):
    return {"tvg-id": cid, "name": name, "playlist-id": "source", "url": "https://example.invalid/" + cid}


def create_guide(path, when):
    db = playlist.EPGDatabase(str(path))
    start = when.strftime("%Y%m%d%H%M%S")
    end = (when + dt.timedelta(hours=1)).strftime("%Y%m%d%H%M%S")
    for cid, name in [("north", "Régió TV"), ("south", "Régió TV"), ("idle", "Régió TV"), ("long", "Kultúra")]:
        db.insert_channel(cid, name)
        if cid in ("north", "south"):
            db.insert_programme(cid, "Őszi koncert", start, end)
    db.insert_programme("north", "Korábbi műsor", (when - dt.timedelta(hours=1)).strftime("%Y%m%d%H%M%S"), start)
    db.insert_programme("long", "Maraton", (when - dt.timedelta(hours=30)).strftime("%Y%m%d%H%M%S"), end)
    db.commit()
    return db


def test_single_indexed_snapshot_disambiguates_names_and_favourites(tmp_path):
    when = dt.datetime.now(dt.timezone.utc).replace(second=0, microsecond=0)
    db = create_guide(tmp_path / "epg.db", when)
    try:
        db._utcnow = lambda: when
        for rows in [db.programmes_at(when), db.get_all_now_playing()]:
            same_name = [row for row in rows if row["channel_name"] == "Régió TV"]
            assert {r["channel_id"] for r in same_name} == {"north", "south"}
            assert len({r["channel_label"] for r in same_name}) == 2
        assert {r["channel_id"] for r in db.programmes_at(when)} == {"north", "south", "long"}
        assert db.programmes_at(when + dt.timedelta(hours=1)) == []
        sql = []
        db.conn.set_trace_callback(sql.append)
        south, north = channel("south"), channel("north")
        rows = db.programmes_at(when, [south, channel("idle"), north])
        assert len([s for s in sql if s.lstrip().upper().startswith("SELECT")]) == 1
        assert [row["playlist_channel"] for row in rows] == [south, north]
        assert rows[0]["channel_label"] != rows[1]["channel_label"]
        assert db.get_channels_with_show("őszi", include_title_search=True)
        assert db.get_channels_with_show("őszi", include_title_search=False) == []
    finally:
        db.close()


def test_relink_replaces_only_one_position_and_rejects_conflicts():
    old, new, a, b = (channel(i) for i in ("old", "new", "a", "b"))
    values, one = lists.create([], "Első")
    values, two = lists.create(values, "Második")
    for ch in [a, old, b]:
        values = lists.edit(values, one, add=ch)
    values = lists.edit(values, two, add=old)
    missing_key = reminders.channel_key(old)
    assert lists.resolve(values[0]["entries"], [a, new, b])[1][1] is None
    with pytest.raises(ValueError):
        lists.relink(values, one, missing_key, b)
    changed = lists.relink(values, one, missing_key, new)
    assert [ch for e, ch in lists.resolve(changed[0]["entries"], [a, b, new])] == [a, new, b]
    assert changed[1] == values[1]
    assert values[0]["entries"][1]["key"] == missing_key
    with pytest.raises(ValueError) as removed_entry:
        lists.relink(changed, one, missing_key, new)
    assert str(removed_entry.value) == lists._("The channel list changed. Try again.")
    with pytest.raises(ValueError) as removed_list:
        lists.relink(changed, "deleted", missing_key, new)
    assert str(removed_list.value) == lists._("The selected list no longer exists.")


@pytest.fixture(scope="session")
def guide_wx_app():
    return wx.GetApp() or wx.App(False)


@pytest.fixture
def gui(guide_wx_app):
    app = guide_wx_app
    wx.Log.SetActiveTarget(wx.LogStderr())
    frame = wx.Frame(None)
    yield app, frame
    frame.Destroy()
    app.Yield()


def until(app, predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        app.Yield()
        time.sleep(.005)
    assert predicate()


def activate_button(button):
    event = wx.CommandEvent(wx.EVT_BUTTON.typeId, button.GetId())
    event.SetEventObject(button)
    button.GetEventHandler().ProcessEvent(event)


def test_guide_details_reads_selected_long_text_and_escape_keeps_selection(gui, tmp_path, monkeypatch):
    app, owner = gui
    when = dt.datetime.now(dt.timezone.utc).replace(second=0, microsecond=0)
    path = tmp_path / "guide.db"
    db = create_guide(path, when)
    text = "Árvíztűrő tükörfúrógép. " * 120
    db.conn.execute("UPDATE programmes SET description=?, episode='S01E03', subtitle='Finálé' WHERE channel_id='south'", (text,))
    db.commit()
    db.close()
    owner.config, owner.all_channels = {}, []
    owner._program_match_index = Mock()
    monkeypatch.setattr(ui.options, 'get_db_path', lambda: str(path))
    dlg = ui.GuideAtDialog(owner, owner)
    captured = []
    def modal(details):
        field = next(w for w in details.panel.GetChildren() if isinstance(w, wx.TextCtrl))
        captured.append((field.GetValue(), field.GetName(), field.IsEditable(), field.IsMultiLine()))
        wx.CallLater(100, wx.UIActionSimulator().Char, wx.WXK_ESCAPE)
        # Ensure a broken native Escape path fails the test without stranding the suite.
        fallback = wx.CallLater(1500, lambda: details.EndModal(wx.ID_ABORT) if details.IsModal() else None)
        result = details.ShowModal()
        fallback.Stop()
        captured.append(result)
        return result
    monkeypatch.setattr(ui, 'show_modal', modal)
    try:
        owner.Show()
        dlg.Show()
        dlg.search(None)
        until(app, lambda: any(row['channel_id'] == 'south' for row in dlg.filtered_programs))
        index = next(i for i, row in enumerate(dlg.filtered_programs) if row['channel_id'] == 'south')
        dlg.listbox.Select(index)
        button = next(w for w in dlg.panel.GetChildren() if isinstance(w, wx.Button) and w.GetLabel() == ui._('Programme Details...'))
        assert button.AcceptsFocusFromKeyboard()
        activate_button(button)
        until(app, lambda: len(captured) == 2)
        value, name, editable, multiline = captured[0]
        assert text in value and 'S01E03' in value and 'Finálé' in value
        assert name == ui._('Details') and multiline and not editable
        assert captured[1] == wx.ID_CANCEL and dlg.listbox.GetFirstSelected() == index
        assert wx.Window.FindFocus() is dlg.listbox
    finally:
        dlg.Destroy()


def test_native_recording_edits_select_airing_and_preserve_padding(gui, tmp_path, monkeypatch):
    import recording_edits_ui as editing
    app, owner = gui
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0) + dt.timedelta(days=1)
    fmt = '%Y%m%d%H%M%S'
    programme = dict(title='Concert', start=now.strftime(fmt), end=(now + dt.timedelta(hours=1)).strftime(fmt),
                     episode='S01E01')
    ch = channel('radio')
    db = playlist.EPGDatabase(str(tmp_path / 'epg'))
    db.insert_channel('radio', ch['name'])
    for hours in (0, 3, 6):
        db.insert_programme('radio', 'Concert', (now + dt.timedelta(hours=hours)).strftime(fmt),
                            (now + dt.timedelta(hours=hours+1)).strftime(fmt), episode=programme['episode'])
    db.commit()
    db.close()
    scheduler = dvr.DVRScheduler(str(tmp_path / 'dvr'), on_start=Mock(), on_stop=Mock())
    initial = scheduler.add_job(dvr.build_job(ch, programme, 'provider_mkv', repeat='weekly'))
    competing = dict(programme, start=(now + dt.timedelta(hours=3)).strftime(fmt),
                     end=(now + dt.timedelta(hours=4)).strftime(fmt))
    scheduler.add_job(dvr.build_job(channel('other'), competing, 'provider_mkv'))
    owner.config, owner.all_channels = {}, [ch]
    owner._ensure_dvr_scheduler = lambda **kw: scheduler
    monkeypatch.setattr(editing.options, 'get_db_path', lambda: str(tmp_path / 'epg'))
    changed, labels = [], []
    def modal(dialog):
        if hasattr(dialog, 'before_ctrl'):
            assert dialog.before_ctrl.GetName() and dialog.after_ctrl.GetName()
            assert dialog.future.GetLabel() and not dialog.future.GetValue()
            dialog.before_ctrl.SetValue(3)
            dialog.after_ctrl.SetValue(19)
        else:
            listing = next(w for w in dialog.panel.GetChildren() if isinstance(w, wx.ListBox))
            labels.extend(listing.GetStrings())
            listing.SetSelection(1)
        return wx.ID_OK
    monkeypatch.setattr(editing, 'show_modal', modal)
    monkeypatch.setattr(editing, 'confirm', lambda *_: True)
    monkeypatch.setattr(editing, 'error_box', lambda _, error: changed.append(str(error)))
    editing.padding_dialog(owner, owner, initial, lambda: changed.append(True))
    until(app, lambda: bool(changed))
    assert changed == [True]
    updated = scheduler.get_job(initial['id'])
    assert updated['program'] == initial['program'] and updated['post_padding_minutes'] == 19
    editing.find_airing(owner, owner, updated, lambda: changed.append(True))
    until(app, lambda: len(changed) == 2)
    assert changed == [True, True] and len(labels) == 2
    assert editing._('Recording Conflicts') in labels[0] and editing._('Recording Conflicts') not in labels[1]
    new = next(j for j in scheduler.list_jobs(include_done=False) if j['channel'] == ch and not j.get('repeat'))
    assert new['program']['start'] == (now + dt.timedelta(hours=6)).strftime(fmt)
    assert (new['pre_padding_minutes'], new['post_padding_minutes']) == (3, 19)


def test_favourite_import_preview_respects_explicit_unresolved(gui, monkeypatch):
    import favourite_transfer as transfer
    import favourite_transfer_ui as portable
    import user_guide
    app, owner = gui
    owner.config = {}
    ch = channel('concert')
    entry = dict(name=ch['name'], key=reminders.channel_key(ch), guide=transfer.guide_key(ch))
    parent = ui.ToolDialog(owner, 'Favourites')
    parent.rows = []
    dialog = portable.ImportDialog(parent, 'Rádiók', transfer.match([entry], [ch]))
    try:
        assert dialog.channels.GetName() and dialog.name_field.GetName()
        assert user_guide.topic_for_window(dialog.channels) == "favorites"
        row = dialog.channels.GetString(0)
        assert row.casefold().count(ch['name'].casefold()) == 1
        assert portable._("Source {number}").format(number=1) in row
        other_name = dict(ch, name='Másik adónév')
        assert other_name['name'] in dialog.channel_label(other_name, 0, shown_name=ch['name'])
        def unresolved(choice):
            choice.SetSelection(0)
            return wx.ID_OK
        monkeypatch.setattr(portable, 'show_modal', unresolved)
        dialog.choose(None)
        assert dialog.choices == [None]
        assert portable._('Leave unresolved') in dialog.channels.GetString(0)
        wx.CallAfter(activate_button, dialog.FindWindowById(wx.ID_OK, dialog))
        assert dialog.ShowModal() == wx.ID_OK
        assert dialog.list_name == 'Rádiók' and lists.resolve(dialog.entries, [ch])[0][1] is None
        assert dialog.entries[0]['guide'] == entry['guide']
    finally:
        dialog.Destroy()
        parent.Destroy()


def test_native_guide_actions_use_the_selected_playlist_channel(gui, tmp_path, monkeypatch):
    app, owner = gui
    when = dt.datetime.now(dt.timezone.utc).replace(second=0, microsecond=0) + dt.timedelta(days=1)
    path = tmp_path / "guide.db"
    db = create_guide(path, when)
    db.insert_channel("bad", "Broken date")
    db.insert_programme("bad", "Bad timestamp", when.strftime("%Y%m%d%H%M%S"), "unparseable")
    db.commit()
    db.close()
    south, north = channel("south"), channel("north")
    values, identity = lists.create([], "Otthoni")
    values = lists.edit(values, identity, add=south)
    owner.config = {"favorites": favorites.toggle([], north)[0], "favorite_collections": values}
    owner.all_channels = [north, south]
    owner._program_match_index = Mock()
    owner._schedule_program_recording, owner._set_programme_reminder = Mock(), Mock()
    monkeypatch.setattr(ui.options, "get_db_path", lambda: str(path))
    dlg = ui.GuideAtDialog(owner, owner)
    try:
        assert dlg.time.GetName() and dlg.scope.GetName() and dlg.listbox.GetName()
        dlg.time.SetValue(when.astimezone().strftime("%Y-%m-%d %H:%M"))
        dlg.search(None)
        until(app, lambda: dlg.listbox.GetItemCount() == 3)
        assert "bad" not in {row["channel_id"] for row in dlg.filtered_programs}
        for selection, ch in [(2, south), (1, north)]:
            dlg.scope.SetSelection(selection)
            dlg.search(None)
            until(app, lambda: dlg.listbox.GetItemCount() == 1)
            assert "Őszi koncert" in dlg.listbox.OnGetItemText(0, 0)
            assert dlg.filtered_programs[0]["time_label"]
            dlg.schedule(None)
            assert owner._schedule_program_recording.call_args.args[0] is ch
            assert "playlist_channel" not in owner._schedule_program_recording.call_args.args[1]
            dlg.remind(None)
            assert owner._set_programme_reminder.call_args.args[0] is ch
        owner.all_channels = [north]
        monkeypatch.setattr(ui, "error_box", Mock())
        assert dlg.selected() == (None, None) and dlg.listbox.GetItemCount() == 0
    finally:
        dlg.Destroy()


def test_epg_schedule_durable_write_and_success_are_on_correct_threads(gui, tmp_path, monkeypatch):
    app, owner = gui
    channel_row = channel("news")
    sched = dvr.DVRScheduler(str(tmp_path / "schedule.json"), on_start=lambda j: 1, on_stop=lambda j: None)
    now = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)
    show = dict(title="Hírek", start=now.strftime("%Y%m%d%H%M%S"),
                end=(now + dt.timedelta(hours=1)).strftime("%Y%m%d%H%M%S"))
    owner.config = {}
    owner._recording_format_for_channel = lambda ch: ("provider_mkv", "video", "test")
    owner._channel_record_key = reminders.channel_key
    owner._find_duplicate_scheduled_job = lambda row: None
    owner._ensure_dvr_scheduler = lambda **kw: sched
    owner._epg_guide_is_usable = lambda: True
    success = []
    owner._report_scheduled_program = lambda job, usable: success.append((wx.IsMainThread(), usable))
    entered, release = threading.Event(), threading.Event()
    fsync = dvr.os.fsync
    def slow(fd):
        assert not wx.IsMainThread()
        entered.set()
        assert release.wait(5)
        fsync(fd)
    monkeypatch.setattr(dvr.os, "fsync", slow)
    try:
        main.IPTVClient._schedule_program_recording(owner, channel_row, show)
        until(app, entered.is_set)
        assert not success and not sched.list_jobs()
    finally:
        release.set()
    until(app, lambda: bool(success))
    assert success == [(True, True)]
    assert len(sched.list_jobs()) == 1


@pytest.mark.parametrize(("state", "available", "limited", "downloads"), [
    ("missed", True, False, 1), ("partial", True, False, 1), ("failed", False, False, 0),
    ("failed", True, True, 0), ("completed", True, False, 0)])
def test_archive_recovery_uses_the_original_window_and_checks_limits(gui, monkeypatch, state, available, limited, downloads):
    app, owner = gui
    ch = channel("regional", "Duna")
    end = dt.datetime.now(dt.timezone.utc).replace(microsecond=0) - dt.timedelta(hours=2)
    start = end - dt.timedelta(hours=1)
    show = dict(title="Példa", start=start.strftime("%Y%m%d%H%M%S"), end=end.strftime("%Y%m%d%H%M%S"))
    job = dvr.build_job(ch, show, "provider_mkv", pre_padding_minutes=5, post_padding_minutes=3)
    job.update(status=state, output_path="original-part.mkv")
    owner.config, owner.all_channels = {}, [ch]
    owner.recorder = SimpleNamespace(list_active=lambda: [])
    owner._channel_has_catchup = lambda current: available
    owner._within_catchup_window = lambda current, stamp: stamp == start
    owner._prepare_archive_download = Mock(return_value=("prepared",))
    owner._download_catchup_programme = Mock()
    message = Mock()
    monkeypatch.setattr(main, "message_box", message)
    if limited:
        import recording_limits
        monkeypatch.setattr(recording_limits, "check_start", Mock(side_effect=RuntimeError("limit")))
    dlg = SimpleNamespace(parent_frame=owner, scheduler=SimpleNamespace(get_job=lambda key: job),
                          _selected_jobs=lambda: [job])
    main.ScheduledRecordingsDialog._recover_archive(dlg, None)
    until(app, lambda: owner._download_catchup_programme.called or message.called)
    assert owner._download_catchup_programme.call_count == downloads
    assert job["output_path"] == "original-part.mkv"
    if downloads:
        args, kwargs = owner._download_catchup_programme.call_args
        assert args[0] is ch and args[1] == dict(show, from_schedule=True, schedule_padding=(5, 3))
        assert kwargs == {"prepared": ("prepared",)}
    else:
        assert not owner._prepare_archive_download.called


def test_library_enter_uses_the_selected_files_estimated_position(gui, tmp_path):
    app, owner = gui
    selected = tmp_path / "selected.mkv"
    selected.write_bytes(b"media")
    row, = library.scan(tmp_path)
    log = Path(recorder.recording_log_path(str(tmp_path), str(selected)))
    log.parent.mkdir()
    log.write_text("\n".join(["2026-11-17 20:00:00.000 [info] Output #0 to file selected.mkv",
                              "2026-11-17 20:00:09.000 [warning] packet error", recorder._SUMMARY_MARKER,
                              f"# File: {selected}", f"# Media signature: {row['size']} {row['modified_ns']}"]))
    (log.parent / "a-newer-unrelated.log").write_text("irrelevant")
    owner._launch_stream = Mock()
    def choose(parent, title, problems):
        dlg = main.RecordingProblemTimesDialog(owner, title, problems, seek=True)
        try:
            assert dlg.list_box.GetName() and "0:00:09" in dlg.list_box.GetString(0)
            assert "estimated" in dlg.list_box.GetString(0).lower()
            wx.CallAfter(dlg._position_key, SimpleNamespace(GetKeyCode=lambda: wx.WXK_RETURN))
            assert dlg.ShowModal() == wx.ID_OK
            return dlg.position_ms
        finally:
            dlg.Destroy()
    owner._choose_recording_position = choose
    box = SimpleNamespace(owner=owner, selected=lambda: row, busy=False, filter_busy=False,
                          deleted=SimpleNamespace(GetValue=lambda: False), active_paths=lambda: [])
    RecordingLibraryDialog.show_problems(box, None)
    until(app, lambda: owner._launch_stream.called)
    args, kwargs = owner._launch_stream.call_args
    assert args[0] == library.playback_channel(tmp_path, row)["url"]
    assert kwargs["force_internal"] and kwargs["initial_position_ms"] == 9000


def test_opening_seek_waits_for_the_correct_media_and_clamps_to_duration():
    player = Mock()
    player.is_seekable.return_value = False
    player.get_length.return_value = 50000
    obj = SimpleNamespace(_vlc_generation=5, _manual_stop=False, player=player,
                          _seek_media=Mock(), _navigation_message=Mock())
    request = (5, 80000, time.monotonic() + 5)
    obj._recording_seek_when_ready = request
    InternalPlayerFrame._apply_recording_seek(obj, request)
    assert obj._recording_seek_when_ready == request and not obj._seek_media.called
    player.is_seekable.return_value = True
    InternalPlayerFrame._apply_recording_seek(obj, request)
    obj._seek_media.assert_called_once_with(target=49999)
    obj._seek_media.reset_mock()
    obj._vlc_generation += 1
    InternalPlayerFrame._apply_recording_seek(obj, request)
    assert not obj._seek_media.called and obj._recording_seek_when_ready is None


def test_invalid_guide_times_report_the_localized_reason():
    channel_data = channel("guide")
    with pytest.raises(ValueError) as malformed:
        dvr.build_job(channel_data, {"start": "missing", "end": ""}, "provider_mkv")
    assert str(malformed.value) == dvr._("Invalid programme times.")
    same_time = {"start": "20261116120000", "end": "20261116120000"}
    with pytest.raises(ValueError) as empty_window:
        dvr.build_job(channel_data, same_time, "provider_mkv")
    assert str(empty_window.value) == dvr._("Program end time must be after the start time.")


def test_original_archive_padding_survives_configuration_change():
    owner = SimpleNamespace(config={"recording_pre_padding_minutes": 30, "recording_post_padding_minutes": 40},
                            _parse_epg_time=dvr.parse_epg_utc)
    show = dict(start="20261116120000", end="20261116130000", from_schedule=True, schedule_padding=(4, 3))
    window = main.IPTVClient._padded_catchup_window(owner, show)
    assert [v.strftime("%H:%M") for v in window] == ["11:56", "13:03"]
    owner._padded_catchup_window = lambda _show: None
    with pytest.raises(ValueError) as invalid:
        main.IPTVClient._prepare_archive_download(owner, {}, {})
    assert str(invalid.value) == main._("Invalid programme times.")


def test_relink_native_dialog_reports_source_and_keeps_focus_on_updated_favourite(gui, monkeypatch):
    app, owner = gui
    old = channel("old")
    replacement = channel("fresh")
    other = dict(replacement, **{"playlist-id": "other", "url": "https://example.invalid/second"})
    values, identity = lists.create([], "Esti adók")
    owner.config = {"favorite_collections": lists.edit(values, identity, add=old)}
    owner.all_channels = [other, replacement]
    owner._selected_channel = lambda: None
    owner._scoped_sources = lambda: [{"id": "source", "name": "Első csomag"}, {"id": "other", "name": "Második csomag"}]
    owner._scope_choice_label = lambda src: src["name"]
    def persist(key, transform):
        owner.config[key] = transform(owner.config[key])
    owner._save_tool_setting = persist
    monkeypatch.setattr(ui, "text_entry", lambda *args: "régió")
    choices = []
    def choose_channel(parent, prompt, title, labels):
        choices.extend(labels)
        return SimpleNamespace(GetSelection=lambda: 1, Destroy=lambda: None)
    monkeypatch.setattr(ui.wx, "SingleChoiceDialog", choose_channel)
    monkeypatch.setattr(ui, "show_modal", lambda dialog: wx.ID_OK)
    dlg = ui.FavouriteListsDialog(owner)
    try:
        dlg._relink(None)
        until(app, lambda: dlg.entry()["key"] == reminders.channel_key(replacement))
        assert choices == ["Régió TV – fresh – Második csomag", "Régió TV – fresh – Első csomag"]
        assert len(dlg.selected()["entries"]) == 1 and dlg.entries.GetSelection() == 0
    finally:
        dlg.Destroy()
