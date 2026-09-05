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
            frame.channel_list, frame.epg_display, frame.url_display]
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
frame._exit_forced = True
frame.Close()
app.Yield()
print("Playlist choices, filtering and twelve Tab/Shift+Tab transitions including search and EPG: OK")
