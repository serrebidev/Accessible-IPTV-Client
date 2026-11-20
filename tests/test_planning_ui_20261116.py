import copy
import datetime as dt
import threading
import time
from types import SimpleNamespace

import pytest
import wx

import dvr
import options
import personal_tools_ui
import planning_ui
import planning_tools_ui
import programme_reminders
import recording_library_ui


def pump(predicate, seconds=4):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        wx.GetApp().Yield()
        if predicate():
            return
        time.sleep(.002)
    assert predicate()


@pytest.fixture
def owner(tmp_path, monkeypatch):
    app = wx.GetApp() or wx.App(False)
    class Owner(planning_ui.PlanningMixin, personal_tools_ui.PersonalToolsMixin, wx.Frame):
        pass
    frame = Owner(None)
    frame.config = {'playlists': [], 'epgs': [], 'recordings_dir': str(tmp_path), 'saved_programme_searches': []}
    frame.recorder = SimpleNamespace(list_active=lambda: [], has_active=lambda: False)
    frame._reminder_seen = set()
    frame._reminders_stopped = False
    frame._reminder_store = programme_reminders.ReminderStore(str(tmp_path / 'reminders.json'))
    frame._reminder_modal_open = lambda: False
    frame._tool_status = lambda text: None
    frame._show_or_queue_message_box = lambda *args: None
    frame._play_live_channel = lambda channel: None
    frame.all_channels = []
    monkeypatch.setattr(options, 'get_recordings_dir', lambda config: str(tmp_path))
    monkeypatch.setattr(options, 'load_config', lambda: copy.deepcopy(frame.config))
    monkeypatch.setattr(options, 'save_config', lambda config: True)
    frame.Show()
    app.Yield()
    yield frame
    writer = getattr(frame, '_library_view_writer', None)
    if writer:
        writer.close()
    frame._reminders_stopped = True
    frame.Destroy()
    app.Yield()


def test_native_manual_weekday_selection_reaches_durable_scheduler(owner, tmp_path, monkeypatch):
    scheduler = dvr.DVRScheduler(str(tmp_path / 'dvr.json'), on_start=lambda job: 1, on_stop=lambda job: None)
    channel = {'name': 'TV', 'url': 'https://example.invalid', 'playlist-id': 'test'}
    owner._selected_channel = lambda: channel
    owner._ensure_dvr_scheduler = lambda **kwargs: scheduler
    owner._recording_format_for_channel = lambda channel: ('provider_mkv', '', '')
    def modal(dialog):
        day = (dt.datetime.now() + dt.timedelta(days=1)).replace(hour=20, minute=0, second=0, microsecond=0)
        dialog.start.SetValue(day.strftime('%Y-%m-%d %H:%M'))
        dialog.end.SetValue((day + dt.timedelta(hours=1)).strftime('%Y-%m-%d %H:%M'))
        dialog.days.SetCheckedItems([day.weekday()])
        dialog.EndModal = lambda result: None
        dialog._accept(None)
        return wx.ID_OK
    monkeypatch.setattr(personal_tools_ui, 'show_modal', modal)
    owner._schedule_by_time()
    pump(lambda: bool(scheduler.list_jobs()))
    jobs = scheduler.list_jobs()
    assert len(jobs) == 1 and jobs[0]['repeat'] == 'weekdays'
    reloaded = dvr.DVRScheduler(scheduler.path, on_start=lambda job: 1, on_stop=lambda job: None)
    assert reloaded.list_jobs()[0]['weekdays'] == jobs[0]['weekdays']


def test_reminder_edit_does_not_block_native_window(owner, monkeypatch):
    row = programme_reminders.build({'name': 'TV', 'url': 'https://example.invalid'},
        {'title': 'Film', 'start': dt.datetime.fromtimestamp(time.time()+600, dt.timezone.utc).strftime('%Y%m%d%H%M%S'),
         'end': dt.datetime.fromtimestamp(time.time()+3600, dt.timezone.utc).strftime('%Y%m%d%H%M%S')})
    owner._reminder_store.add(row)
    dialog = planning_ui.RemindersDialog(owner, owner._reminder_store)
    entered, release = threading.Event(), threading.Event()
    original = owner._reminder_store._commit
    def slow(rows):
        entered.set()
        assert release.wait(3)
        original(rows)
    monkeypatch.setattr(owner._reminder_store, '_commit', slow)
    try:
        before = time.monotonic()
        dialog._change(lambda: owner._reminder_store.set_lead(row['id'], 1))
        assert time.monotonic() - before < .2 and entered.wait(1)
        wx.GetApp().Yield()
        assert dialog.busy and dialog.list.GetItemCount() == 1
        assert owner._reminder_store.list()[0]['lead'] == 5
        release.set()
        pump(lambda: not dialog.busy)
        assert owner._reminder_store.list()[0]['lead'] == 1
    finally:
        release.set()
        dialog.Destroy()


def test_library_reopens_saved_view_but_never_reopens_trash(owner, tmp_path):
    (tmp_path / 'film.mkv').write_bytes(b'media')
    owner.config['recording_library_view'] = {'folder': '*', 'query': 'film', 'sort': 'size',
                                              'status': 'unknown', 'descending': False, 'deleted': True}
    dialog = recording_library_ui.RecordingLibraryDialog(owner)
    try:
        pump(lambda: not dialog.busy and not dialog.filter_busy)
        assert dialog.folder.GetSelection() == len(dialog.directories)
        assert dialog.search.GetValue() == 'film' and dialog.sort.GetSelection() == 3
        assert not dialog.deleted.GetValue() and not dialog.descending.GetValue()
        assert dialog.export.IsEnabled()
        dialog.close()
        pump(lambda: not getattr(owner._library_view_writer, 'pending', None))
    finally:
        if not dialog.closed:
            dialog.Destroy()


def test_reminder_popup_snoozes_instead_of_acknowledging(owner, monkeypatch):
    now = int(time.time())
    stamp = lambda x: dt.datetime.fromtimestamp(x, dt.timezone.utc).strftime('%Y%m%d%H%M%S')
    row = programme_reminders.build({'name': 'TV', 'url': 'https://example.invalid'},
                                  {'title': 'Film', 'start': stamp(now+100), 'end': stamp(now+3600)}, now=now)
    owner._reminder_store.add(row)
    def modal(dialog):
        assert isinstance(dialog, planning_tools_ui.ReminderAlert)
        dialog.action = 'snooze'
        return wx.ID_OK
    monkeypatch.setattr(planning_ui, 'show_modal', modal)
    owner._poll_reminders()
    pump(lambda: 'notify_at' in owner._reminder_store.list()[0])
    assert owner._reminder_store.list()[0]['status'] == 'scheduled'
    pump(lambda: row['id'] not in owner._reminder_seen)


def test_backup_encryption_runs_off_ui_thread(owner, tmp_path, monkeypatch):
    owner._backup_password = lambda **kwargs: 'secret'
    scheduler = SimpleNamespace(list_jobs=lambda: [])
    owner._ensure_dvr_scheduler = lambda: scheduler
    class FileDialog:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def GetPath(self):
            return str(tmp_path / 'backup.aiptv')
    monkeypatch.setattr(wx, 'FileDialog', FileDialog)
    monkeypatch.setattr(personal_tools_ui, 'show_modal', lambda dialog: wx.ID_OK)
    monkeypatch.setattr(personal_tools_ui.full_backup, 'paths', lambda: {'search_seen': str(tmp_path / 'seen.json')})
    threads = []
    monkeypatch.setattr(personal_tools_ui.full_backup, 'export_bundle', lambda *args: threads.append(threading.get_ident()))
    monkeypatch.setattr(personal_tools_ui, 'message_box', lambda *args, **kwargs: None)
    owner._export_full_settings()
    pump(lambda: bool(threads) and 'backup' not in owner._background_operations)
    assert threads == [threads[0]] and threads[0] != threading.get_ident()


def test_closing_reminder_editor_during_save_still_rearms_future_alert(owner, monkeypatch):
    now = int(time.time())
    stamp = lambda x: dt.datetime.fromtimestamp(x, dt.timezone.utc).strftime('%Y%m%d%H%M%S')
    row = programme_reminders.build({'name': 'TV', 'url': 'https://example.invalid'},
                                  {'title': 'Film', 'start': stamp(now+600), 'end': stamp(now+3600)}, now=now)
    owner._reminder_store.add(row)
    owner._reminder_seen.add(row['id'])
    dialog = planning_ui.RemindersDialog(owner, owner._reminder_store)
    entered, release = threading.Event(), threading.Event()
    original = owner._reminder_store._commit
    def slow(rows):
        entered.set()
        assert release.wait(3)
        original(rows)
    monkeypatch.setattr(owner._reminder_store, '_commit', slow)
    dialog._change(lambda: owner._reminder_store.set_lead(row['id'], 1), rearm=row['id'])
    try:
        assert entered.wait(1)
        dialog.Destroy()
        wx.GetApp().Yield()
        release.set()
        pump(lambda: row['id'] not in owner._reminder_seen)
        assert owner._reminder_store.list()[0]['lead'] == 1
    finally:
        release.set()


def test_reminder_poll_waits_for_pending_acknowledgement(owner, monkeypatch):
    owner._background_operations = {'reminder-ack'}
    monkeypatch.setattr(owner._reminder_store, 'due', lambda: pytest.fail('must wait for acknowledgement'))
    owner._poll_reminders()
    assert owner._background_operations == {'reminder-ack'}


def test_stopped_and_restarted_reminder_service_discards_old_poll(owner, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    def slow_due():
        entered.set()
        assert release.wait(3)
        return []
    called = []
    monkeypatch.setattr(owner._reminder_store, 'due', slow_due)
    owner._reminders_ready = lambda *args: called.append(args)
    owner._poll_reminders()
    try:
        assert entered.wait(1)
        owner._stop_reminders()
        owner._reminders_stopped = False
        release.set()
        pump(lambda: 'reminder-poll' not in owner._background_operations)
        assert called == []
    finally:
        release.set()


def test_weekday_controls_do_not_clip_native_accept_cancel_buttons(owner):
    dialog = personal_tools_ui.RecordingTimesDialog(owner, {'name': 'TV'})
    try:
        dialog.Show()
        wx.GetApp().Yield()
        buttons = [child for child in dialog.panel.GetChildren() if isinstance(child, wx.Button)]
        assert len(buttons) == 2
        for button in buttons:
            assert button.GetSize().height > 0
            assert button.GetRect().GetBottom() <= dialog.panel.GetClientSize().height
    finally:
        dialog.Destroy()
