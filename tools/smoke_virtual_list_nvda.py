"""Smoke-test the NVDA-crash fixes against real native list controls.

Exercises the exact hazard patterns on SysListView32:
- shrinking SetItemCount while an item near the end is selected+focused
- replacing a large selected result set with smaller search results
- Clear() with a focused item
- rapid repeated refiltering of WhatsOnNowDialog (debounced path)
Run: python tools/smoke_virtual_list_nvda.py
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import wx
import main


def pump(app, seconds):
    end = time.time() + seconds
    while time.time() < end:
        app.Yield()
        time.sleep(0.02)


def test_virtual_channel_list(parent):
    class FakeFrame:
        displayed = []
    frame = FakeFrame()
    lst = main._VirtualChannelList(parent, frame)

    # Grow to 100k, select+focus near the end, then shrink hard.
    frame.displayed = [{"type": "channel", "data": {"name": f"ch {i}"}} for i in range(100_000)]
    lst.set_virtual_count()
    lst.SetSelection(99_998)
    assert lst.GetFocusedItem() == 99_998, lst.GetFocusedItem()

    frame.displayed = frame.displayed[:10]
    lst.set_virtual_count()
    assert lst.GetItemCount() == 10
    assert lst.GetFocusedItem() < 10, f"stale focused item {lst.GetFocusedItem()}"
    assert lst.GetFirstSelected() < 10, f"stale selection {lst.GetFirstSelected()}"

    # A real search replaces the row model, rather than merely shrinking it.
    # Exercise the transition with an active item that remains numerically in
    # range but refers to a different result after filtering.
    frame.displayed = [{"type": "channel", "data": {"name": f"before {i}"}} for i in range(10_000)]
    lst.set_virtual_count()
    lst.SetSelection(5)
    filtered = [{"type": "channel", "data": {"name": f"match {i}"}} for i in range(8)]
    lst.replace_contents(filtered)
    assert lst.GetItemCount() == len(filtered)
    assert lst.OnGetItemText(7, 0) == "match 7"
    assert lst.GetFocusedItem() == -1
    assert lst.GetFirstSelected() == -1

    # Clear() with a focused item present.
    lst.SetSelection(5)
    frame.displayed = []
    lst.Clear()
    assert lst.GetItemCount() == 0
    assert lst.GetFocusedItem() == -1
    print("virtual channel list: OK")


def test_whats_on_dialog(app, parent):
    programs = [{"title": f"Show {i}", "channel_name": f"Channel {i % 50}",
                 "start": "20260709120000", "end": "20260709130000"} for i in range(20_000)]
    dlg = main.WhatsOnNowDialog(parent, programs)
    dlg.Show()
    pump(app, 0.1)

    def flush_debounce(d):
        # wx.CallLater needs a running MainLoop to fire; drive it manually.
        if d._filter_timer:
            d._filter_timer.Stop()
        d._apply_search_filter()

    # Rapid typing: each SetValue fires EVT_TEXT; debounce should coalesce
    # (no filtering happens until the timer fires).
    for q in ["S", "Sh", "Sho", "Show 1", "Show 19", "Show 199"]:
        dlg.search_box.SetValue(q)
        pump(app, 0.03)
        assert len(dlg.filtered_programs) == len(programs), "filter ran per-keystroke"
    assert dlg._filter_timer is not None, "debounce timer not scheduled"
    flush_debounce(dlg)
    expect = len([p for p in programs if "show 199" in p["title"].lower()])
    assert len(dlg.filtered_programs) == expect, (len(dlg.filtered_programs), expect)
    assert dlg.listbox.GetItemCount() == expect

    # Shrink-to-zero while an item was selected, then back to empty query.
    dlg.listbox.Select(0); dlg.listbox.Focus(0)
    dlg.search_box.SetValue("zzz-no-match")
    flush_debounce(dlg)
    assert dlg.listbox.GetItemCount() == 0
    assert dlg.listbox.GetFocusedItem() == -1

    dlg.search_box.SetValue("")
    flush_debounce(dlg)
    assert dlg.listbox.GetItemCount() == len(programs)

    # Enter before the debounce fires must flush the filter and select item 0.
    dlg.search_box.SetValue("Show 42")
    evt = wx.CommandEvent(wx.wxEVT_TEXT_ENTER, dlg.search_box.GetId())
    dlg._on_search_enter(evt)
    expect = len([p for p in programs if "show 42" in p["title"].lower()])
    assert dlg.listbox.GetItemCount() == expect, (dlg.listbox.GetItemCount(), expect)
    assert dlg.listbox.GetFirstSelected() == 0

    # Destroy the dialog with a debounce still pending: the deadness guard in
    # _apply_search_filter must swallow the late callback.
    dlg.search_box.SetValue("pending")
    dlg.Destroy()
    pump(app, 0.1)
    dlg._apply_search_filter()  # simulate the timer firing after destroy
    print("whats-on-now dialog: OK")


if __name__ == "__main__":
    app = wx.App()
    parent = wx.Frame(None)
    test_virtual_channel_list(parent)
    test_whats_on_dialog(app, parent)
    parent.Destroy()
    print("ALL SMOKE TESTS PASSED")
