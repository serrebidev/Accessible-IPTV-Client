import copy
import datetime
import json
from types import SimpleNamespace

import pytest

import programme_reminders as reminders
from tests.test_subtitle_integration import extract_class

NOW = 2000000000.0
CHANNEL = {'name': 'TV', 'url': 'https://user:secret@example.invalid/1', 'playlist-id': 'source-A', 'tvg-id': 'tv'}


def program(start=NOW+600,end=NOW+1200):
    stamp=lambda t: datetime.datetime.fromtimestamp(t,datetime.timezone.utc).strftime('%Y%m%d%H%M%S')
    return {'title':'Programme','start':stamp(start),'end':stamp(end)}


def test_lead_time_due_acknowledgement_restart_and_no_credentials(tmp_path):
    store=reminders.ReminderStore(str(tmp_path/'reminders.json'))
    row=reminders.build(CHANNEL,program(),5,now=NOW)
    store.add(row)
    assert not store.due(NOW+299)
    assert store.due(NOW+300)[0]['status']=='ready'
    restarted=reminders.ReminderStore(store.path)
    assert restarted.due(NOW+400)[0]['id']==row['id']
    restarted.acknowledge(row['id'])
    assert not restarted.due(NOW+500)
    assert 'secret' not in (tmp_path/'reminders.json').read_text()
    assert not reminders.ReminderStore(store.path).due(NOW+1000)


def test_restart_during_program_delivers_but_expired_never_does(tmp_path):
    store=reminders.ReminderStore(str(tmp_path/'r.json'))
    store.add(reminders.build(CHANNEL,program(),0,now=NOW))
    assert store.due(NOW+601)
    assert not store.due(NOW+1200)
    assert store.list()[0]['status']=='expired'


def test_duplicate_update_delete_and_early_clock_changes(tmp_path):
    store=reminders.ReminderStore(str(tmp_path/'r.json'))
    row=reminders.build(CHANNEL,program(),5,now=NOW);store.add(row);store.add(row)
    assert len(store.list())==1
    assert store.due(NOW+301)
    assert not store.due(NOW+1)  # clock moved back; no premature repeat
    store.set_lead(row['id'],0,now=NOW)
    assert store.list()[0]['status']=='scheduled' and not store.due(NOW+301)
    store.remove(row['id']);assert store.list()==[]


def test_account_scoped_resolution_and_ambiguous_current_channels():
    row=reminders.build(CHANNEL,program(),now=NOW)
    assert reminders.resolve_channel(row,[dict(CHANNEL,url='rotated')])['url']=='rotated'
    assert reminders.resolve_channel(row,[dict(CHANNEL,**{'playlist-id':'B'})]) is None
    assert reminders.resolve_channel(row,[CHANNEL,dict(CHANNEL,url='different')]) is None


@pytest.mark.parametrize('bad',[None,{}, {'start':'bad','end':'bad'},program(NOW-1),program(NOW+1000,NOW+500)])
def test_invalid_or_started_programmes_are_rejected(bad):
    with pytest.raises((TypeError,ValueError)):reminders.build(CHANNEL,bad,now=NOW)


def test_failed_atomic_save_keeps_both_memory_and_previous_file(tmp_path,monkeypatch):
    store=reminders.ReminderStore(str(tmp_path/'r.json'));row=reminders.build(CHANNEL,program(),now=NOW)
    store.add(row);before=copy.deepcopy(store.list());raw=(tmp_path/'r.json').read_bytes()
    def fail(*args):raise OSError('disk full')
    monkeypatch.setattr(reminders.os,'replace',fail)
    with pytest.raises(OSError):store.remove()
    assert store.list()==before and (tmp_path/'r.json').read_bytes()==raw
    assert len(list(tmp_path.iterdir()))==1


def test_corrupt_file_is_preserved(tmp_path):
    path=tmp_path/'r.json';path.write_text('{bad')
    with pytest.raises(ValueError):reminders.ReminderStore(str(path))
    assert path.read_text()=='{bad'


def test_malformed_rows_and_bounded_history_do_not_displace_active_reminders(tmp_path):
    store=reminders.ReminderStore(str(tmp_path/'r.json'))
    rows=[]
    for i in range(510):
        row=reminders.build(CHANNEL,program(NOW+100+i,NOW+1000+i),now=NOW)
        row['status']='notified';rows.append(row)
    pending=reminders.build(dict(CHANNEL,name='Different'),program(),now=NOW)
    normalized=reminders.normalize([*rows,{},dict(pending,lead=True),pending])
    assert len(normalized)==500 and normalized[0]['id']==pending['id']
    store._commit(normalized)
    assert len(json.loads((tmp_path/'r.json').read_text())['reminders'])==500


def test_existing_native_modal_blocks_due_delivery_without_claiming_store():
    cls,_=extract_class('planning_ui.py','PlanningMixin',['_reminder_modal_open','_poll_reminders'],{
        'wx':SimpleNamespace(GetTopLevelWindows=lambda:[SimpleNamespace(IsModal=lambda:True)]),
        'time':SimpleNamespace(monotonic=lambda:1),
    })
    obj=cls();obj._modal_box_is_open=lambda:False
    obj._ensure_reminders=lambda:pytest.fail('must wait behind the native EPG dialog')
    obj._poll_reminders()


def planning_fixture(store,*,play=False,save_fails=False):
    spoken=[];opened=[];dialogs=[]
    class Dialog:
        def __init__(self,*args):dialogs.append(args)
        def SetYesNoLabels(self,*args):pass
        def Destroy(self):pass
    wx=SimpleNamespace(MessageDialog=Dialog,YES_NO=1,NO_DEFAULT=2,ICON_INFORMATION=4,
                       ICON_ERROR=8,ICON_WARNING=16,ID_YES=42,YES=42,OK=1)
    cls,env=extract_class('planning_ui.py','PlanningMixin',['_poll_reminders','_confirm_reminder_exit'],{
        'wx':wx,'reminders':reminders,'show_modal':lambda dialog:42 if play else 43,
        'datetime':datetime,'time':SimpleNamespace(time=lambda:NOW+500,monotonic=lambda:100),
        'message_box':lambda *args,**kwargs:43,
    })
    obj=cls();obj._reminders_stopped=False;obj._reminder_seen=set();obj._reminder_store=store
    obj._reminder_modal_open=lambda:False
    obj._ensure_reminders=lambda:store
    obj._show_or_queue_message_box=lambda *args:spoken.append(args)
    obj._play_live_channel=opened.append
    obj.all_channels=[dict(CHANNEL,url='new-resolved-input')]
    return obj,dialogs,opened,spoken


def test_notification_does_not_open_a_channel_without_explicit_choice(tmp_path):
    store=reminders.ReminderStore(str(tmp_path/'r.json'));store.add(reminders.build(CHANNEL,program(),5,now=NOW))
    # Align the store clock with the test's app clock without replacing its due/ack implementation.
    original=store.due;store.due=lambda:original(NOW+500)
    obj,dialogs,opened,_=planning_fixture(store)
    obj._poll_reminders();obj._poll_reminders()
    assert len(dialogs)==1 and not opened and store.list()[0]['status']=='notified'


def test_user_can_open_only_a_uniquely_resolved_current_channel(tmp_path):
    store=reminders.ReminderStore(str(tmp_path/'r.json'));store.add(reminders.build(CHANNEL,program(),5,now=NOW))
    original=store.due;store.due=lambda:original(NOW+500)
    obj,_,opened,_=planning_fixture(store,play=True)
    obj._poll_reminders()
    assert opened[0]['url']=='new-resolved-input'


def test_ack_failure_keeps_durable_ready_state_without_repeating_popup_in_process(tmp_path,monkeypatch):
    store=reminders.ReminderStore(str(tmp_path/'r.json'));store.add(reminders.build(CHANNEL,program(),5,now=NOW))
    original=store.due;store.due=lambda:original(NOW+500)
    def fail(key):raise OSError('readonly')
    monkeypatch.setattr(store,'acknowledge',fail)
    obj,dialogs,_,errors=planning_fixture(store)
    obj._poll_reminders();obj._poll_reminders()
    assert len(dialogs)==1 and len(errors)==1 and store.list()[0]['status']=='ready'
    assert reminders.ReminderStore(store.path).due(NOW+500)


def test_exit_warning_counts_pending_and_can_cancel_exit(tmp_path):
    store=reminders.ReminderStore(str(tmp_path/'r.json'));store.add(reminders.build(CHANNEL,program(),5,now=NOW))
    obj,_,_,_=planning_fixture(store)
    assert not obj._confirm_reminder_exit()
    store.remove()
    assert obj._confirm_reminder_exit()


def test_capacity_refuses_a_new_pending_reminder_instead_of_losing_an_existing_one(tmp_path):
    store=reminders.ReminderStore(str(tmp_path/'r.json'))
    rows=[reminders.build(CHANNEL,program(NOW+100+i,NOW+1100+i),now=NOW) for i in range(500)]
    store._commit(rows)
    before=store.list()
    extra=reminders.build(CHANNEL,program(NOW+10000,NOW+11000),now=NOW)
    with pytest.raises(ValueError):store.add(extra)
    assert store.list()==before
