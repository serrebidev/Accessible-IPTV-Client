"""Check playlist choices, scope filtering and bidirectional native focus."""
import wx

from smoke_favorites_shutdown import build_frame
import main


app = wx.App()
frame = build_frame()
frame.Show()
app.Yield()
sources = ["https://example.com/one.m3u", "C:/lists/two.m3u"]
frame.playlist_sources = sources
frame._fill_playlist_scope_combo()
assert frame.playlist_scope_combo.GetCount() == 3
assert frame.playlist_scope_combo.GetName() == "Playlist view"
frame.all_channels = [
    {"name": "One", "group": "First", "playlist-id": main._source_scope_id(sources[0])},
    {"name": "Two", "group": "Second", "playlist-id": main._source_scope_id(sources[1])},
]
frame.channels_by_group = {ch["group"]: [ch] for ch in frame.all_channels}
for index, group in ((1, "First"), (2, "Second")):
    frame.playlist_scope_combo.SetSelection(index)
    frame.on_playlist_scope_changed(None)
    app.Yield()
    assert frame._group_keys == ["All Channels", group]
    assert frame.channel_list.GetCount() == 1
    assert wx.Window.FindFocus() == frame.playlist_scope_combo

controls = [frame.playlist_scope_combo, frame.group_list, frame.filter_box,
            frame.channel_list, frame.url_display]
for reverse in (False, True):
    for index, control in enumerate(controls):
        control.SetFocus()
        app.Yield()
        event = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
        event.SetKeyCode(wx.WXK_TAB)
        event.SetShiftDown(reverse)
        handled = control.GetEventHandler().ProcessEvent(event)
        if not handled or event.GetSkipped():
            control.Navigate(wx.NavigationKeyEvent.IsBackward if reverse
                             else wx.NavigationKeyEvent.IsForward)
        app.Yield()
        assert wx.Window.FindFocus() == controls[(index + (-1 if reverse else 1)) % len(controls)], (index, reverse, wx.Window.FindFocus())

# Tab with text in the search box must filter AND land on the channel list:
# the results install asynchronously, so yield until the worker catches up.
# "Two" is the only channel in the active playlist scope.
frame.filter_box.SetValue("Two")
frame.filter_box.SetFocus()
event = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
event.SetKeyCode(wx.WXK_TAB)
handled = frame.filter_box.GetEventHandler().ProcessEvent(event)
assert handled and not event.GetSkipped()
deadline = wx.StopWatch()
while wx.Window.FindFocus() != frame.channel_list and deadline.Time() < 2000:
    app.Yield()
assert wx.Window.FindFocus() == frame.channel_list, wx.Window.FindFocus()
assert frame.channel_list.GetCount() == 1

# Shift+Tab must keep navigating backwards: leave the field, no filter forced.
frame.filter_box.SetValue("Two")
frame.filter_box.SetFocus()
event = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
event.SetKeyCode(wx.WXK_TAB)
event.SetShiftDown(True)
frame.filter_box.GetEventHandler().ProcessEvent(event)
app.Yield()
# The manual focus ring routes Shift+Tab back to the group list (the group
# list's Tab rule sends focus here), and must not apply the filter.
assert wx.Window.FindFocus() == frame.group_list, wx.Window.FindFocus()
assert frame.channel_list.GetCount() == 1, "Shift+Tab must not apply the filter"

# Tab out of an empty search box: no results, so navigation moves on and the
# caret never gets stuck in the field.
frame.filter_box.SetValue("")
frame.filter_box.SetFocus()
event = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
event.SetKeyCode(wx.WXK_TAB)
handled = frame.filter_box.GetEventHandler().ProcessEvent(event)
assert handled and not event.GetSkipped()
app.Yield()
assert wx.Window.FindFocus() == frame.channel_list, wx.Window.FindFocus()
frame._exit_forced = True
frame.Close()
app.Yield()
print("Playlist choices, filtering and Tab/Shift+Tab transitions including search and EPG: OK")
