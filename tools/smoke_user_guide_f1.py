"""Smoke-test F1 context help and the User Guide window with real key presses.

``tests/test_user_guide.py`` covers topic resolution and the guide window's
methods. What it cannot cover is how F1 actually reaches the app: through the
app-wide char hook for a focused control, through WM_HELP for an item of an
open menu, from inside a modal dialog, and inside the guide itself. This drives
the real main window with ``wx.UIActionSimulator`` and checks where each F1
lands and where focus returns afterwards.

Config load/save and the deferred startup work are stubbed, so this touches
neither the user's iptvclient.conf nor the network. Windows only (menus and
WM_HELP are what is being tested). Keep the window in the foreground while it
runs; it takes about half a minute.

Run: python tools/smoke_user_guide_f1.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import wx

import main
import user_guide

CONFIG = {
    "playlists": [], "epgs": [], "media_player": "Built-in Player", "custom_player_path": "",
    "minimize_to_tray": False, "auto_check_updates": False, "epg_enabled": False,
    "show_player_on_enter": True, "language": "en", "recordings_dir": tempfile.gettempdir(),
    "recording_format": "provider_mkv", "recording_pre_padding_minutes": 0,
    "recording_post_padding_minutes": 2, "favorites": [], "preferred_audio_tracks": [],
    "prefer_audio_description": False, "shutdown_after_recordings": False,
    "internal_player_buffer_seconds": 2.0, "internal_player_max_buffer_seconds": 18.0,
    "internal_player_variant_max_mbps": 0.0,
}

CHANNELS = [
    {"name": "BBC One", "group": "UK", "tvg-id": "bbc1.uk"},
    {"name": "Sky News", "group": "UK"},
    {"name": "CNN", "group": "US"},
]

STEP_MS = 700
RESULTS = []
EXIT = {"code": 1}


def build_frame():
    main.load_config = lambda: dict(CONFIG)
    main.save_config = lambda _cfg: None
    main.IPTVClient._run_deferred_startup_tasks = lambda self: None  # noqa: ARG005
    frame = main.IPTVClient()
    frame.all_channels = CHANNELS
    frame.channels_by_group = {"UK": CHANNELS[:2], "US": CHANNELS[2:]}
    frame._invalidate_favorites_cache()
    frame._refresh_group_ui()
    frame.current_group = "All Channels"
    frame._populate_channel_list_chunked(CHANNELS)
    frame.channel_list.SetSelection(0)
    return frame


def check(name, condition, detail=None):
    RESULTS.append((name, bool(condition)))
    suffix = "" if condition or detail is None else f"  (got {detail!r})"
    print(("PASS " if condition else "FAIL ") + name + suffix, flush=True)


# ---- what the guide window is showing ------------------------------------ #
def guide_open():
    return main._OPEN_USER_GUIDE is not None


def guide_topic():
    dlg = main._OPEN_USER_GUIDE
    if dlg is None:
        return None
    section = dlg.guide.section_at(dlg.text.GetSelection()[0])
    return section.topic if section else None


def guide_focus_is(attribute):
    dlg = main._OPEN_USER_GUIDE
    return dlg is not None and wx.Window.FindFocus() is getattr(dlg, attribute)


def guide_selected_text():
    dlg = main._OPEN_USER_GUIDE
    return dlg.text.GetStringSelection() if dlg is not None else ""


def guide_topic_row():
    dlg = main._OPEN_USER_GUIDE
    return dlg.topics_list.GetStringSelection() if dlg is not None else ""


def caret_on_heading(topic):
    dlg = main._OPEN_USER_GUIDE
    if dlg is None:
        return False
    start, end = dlg.text.GetSelection()
    section = dlg.guide.find(topic)
    return section is not None and start == end == section.start


def focus_name():
    focus = wx.Window.FindFocus()
    return type(focus).__name__ if focus is not None else "None"


def modal_titles():
    return [w.GetTitle() for w in wx.GetTopLevelWindows() if isinstance(w, wx.Dialog) and w.IsModal()]


# ---- the key script ------------------------------------------------------- #
class Script:
    def __init__(self, frame):
        self.frame = frame
        self.sim = wx.UIActionSimulator()
        self.steps = []

    def key(self, key, mods=wx.MOD_NONE):
        self.steps.append(lambda: (self.sim.KeyDown(key, mods), self.sim.KeyUp(key, mods)))

    def text(self, value):
        # wxPython's UIActionSimulator.Text takes bytes, not str.
        self.steps.append(lambda: self.sim.Text(value.encode("ascii")))

    def do(self, func):
        self.steps.append(func)

    def run(self):
        def next_step(index=0):
            if index >= len(self.steps):
                finish(self.frame)
                return
            try:
                self.steps[index]()
            except Exception as exc:  # keep going; report it
                check(f"step {index} raised", False, repr(exc))
            wx.CallLater(STEP_MS, next_step, index + 1)

        wx.CallLater(1200, next_step)


def finish(frame):
    failed = [name for name, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)} passed, {len(failed)} failed", flush=True)
    EXIT["code"] = 1 if failed else 0
    frame._exit_forced = True
    for window in wx.GetTopLevelWindows():
        if isinstance(window, wx.Dialog) and window.IsModal():
            window.EndModal(wx.ID_CANCEL)
    wx.CallLater(300, frame.Destroy)

    def stop():
        app = wx.GetApp()
        if isinstance(app, wx.App):
            app.ExitMainLoop()

    wx.CallLater(600, stop)


def build_script(frame):
    s = Script(frame)
    s.do(lambda: (frame.Raise(), frame.channel_list.SetFocus()))

    # 1. F1 on the channel list opens its section, focus in the guide text.
    s.key(wx.WXK_F1)
    s.do(lambda: check("F1 on channel list opens channel-list", guide_topic() == "channel-list", guide_topic()))
    s.do(lambda: check("guide text has focus", guide_focus_is("text"), focus_name()))
    s.do(lambda: check("caret on the heading, nothing selected", caret_on_heading("channel-list")))
    # Shift+Tab reaches Topics, which shows the same section.
    s.key(wx.WXK_TAB, wx.MOD_SHIFT)
    s.do(lambda: check("Shift+Tab from text reaches Topics", guide_focus_is("topics_list"), focus_name()))
    s.do(lambda: check("Topics highlights The channel list", guide_topic_row() == "The channel list",
                       guide_topic_row()))
    # Down in Topics moves the text but keeps focus; Enter enters it.
    s.key(wx.WXK_DOWN)
    s.do(lambda: check("Down in Topics keeps focus in Topics", guide_focus_is("topics_list"), focus_name()))
    s.do(lambda: check("Down in Topics moved the text", guide_topic() == "episode-description", guide_topic()))
    s.key(wx.WXK_RETURN)
    s.do(lambda: check("Enter in Topics focuses the text", guide_focus_is("text"), focus_name()))
    # Tab order after the text: Find, Find Next, Close.
    s.key(wx.WXK_TAB)
    s.do(lambda: check("Tab from text reaches Find", guide_focus_is("find_box"), focus_name()))
    s.key(wx.WXK_TAB)
    s.do(lambda: check("Tab from Find reaches Find Next", guide_focus_is("find_btn"), focus_name()))
    s.key(wx.WXK_TAB)
    s.do(lambda: check("Tab from Find Next reaches Close", guide_focus_is("close_btn"), focus_name()))
    # Ctrl+F, type, Enter: the match is selected in the text.
    s.key(ord("F"), wx.MOD_CONTROL)
    s.do(lambda: check("Ctrl+F focuses Find", guide_focus_is("find_box"), focus_name()))
    s.text("padding")
    s.key(wx.WXK_RETURN)
    s.do(lambda: check("Enter in Find selects a match in the text",
                       guide_focus_is("text") and guide_selected_text().lower() == "padding",
                       guide_selected_text()))
    s.key(wx.WXK_F3)
    s.do(lambda: check("F3 keeps finding", guide_selected_text().lower() == "padding", guide_selected_text()))
    # F1 inside the guide goes to "Using this guide".
    s.key(wx.WXK_F1)
    s.do(lambda: check("F1 in the guide opens using-help", guide_topic() == user_guide.HELP_TOPIC,
                       guide_topic()))
    s.key(wx.WXK_ESCAPE)
    s.do(lambda: check("Escape closes the guide", not guide_open()))
    s.do(lambda: check("focus returns to the channel list", wx.Window.FindFocus() is frame.channel_list,
                       focus_name()))

    # 2. F1 in the search field.
    s.do(lambda: frame.filter_box.SetFocus())
    s.key(wx.WXK_F1)
    s.do(lambda: check("F1 in Search opens search", guide_topic() == "search", guide_topic()))
    s.key(wx.WXK_ESCAPE)
    s.do(lambda: check("focus returns to Search", wx.Window.FindFocus() is frame.filter_box, focus_name()))

    # 3. F1 on an item of an open menu: File > EPG Manager.
    s.do(lambda: frame.channel_list.SetFocus())
    s.key(wx.WXK_F10)          # menu bar mode, File highlighted
    s.key(wx.WXK_DOWN)         # open File: Playlist Manager
    s.key(wx.WXK_DOWN)         # EPG Manager
    s.key(wx.WXK_F1)
    s.do(lambda: check("F1 on File > EPG Manager opens epg-manager", guide_topic() == "epg-manager",
                       guide_topic()))
    s.key(wx.WXK_ESCAPE)
    s.do(lambda: check("menu and guide both closed", not guide_open() and not modal_titles(), modal_titles()))
    s.do(lambda: check("focus back on the channel list after menu help",
                       wx.Window.FindFocus() is frame.channel_list, focus_name()))

    # 3b. F1 on an item of the channel's context menu: WM_HELP goes to the
    # list the popup was shown on, and the list's own topic answers.
    s.do(lambda: frame.channel_list.SetFocus())
    s.key(wx.WXK_WINDOWS_MENU)
    s.key(wx.WXK_DOWN)
    s.key(wx.WXK_F1)
    s.do(lambda: check("F1 in the channel context menu opens channel-list", guide_topic() == "channel-list",
                       guide_topic()))
    s.key(wx.WXK_ESCAPE)
    s.do(lambda: check("context menu and guide both closed", not guide_open() and not modal_titles(),
                       modal_titles()))
    s.do(lambda: check("focus back on the channel list after context menu help",
                       wx.Window.FindFocus() is frame.channel_list, focus_name()))

    # 4. Help > User Guide chosen from the menu opens the start. Left from
    # File would go to the window's system menu, so walk right to Help.
    s.key(wx.WXK_F10)
    for _step in range(5):     # Player, View, Options, Recordings, Help
        s.key(wx.WXK_RIGHT)
    s.key(wx.WXK_DOWN)         # open Help: User Guide
    s.key(wx.WXK_RETURN)
    s.do(lambda: check("Help > User Guide opens the start", guide_topic() == user_guide.DEFAULT_TOPIC,
                       guide_topic()))
    s.key(wx.WXK_ESCAPE)

    # 5. F1 inside a modal dialog: the EPG Manager (Ctrl+E).
    s.key(ord("E"), wx.MOD_CONTROL)
    s.do(lambda: check("EPG Manager is open", "EPG Manager" in modal_titles(), modal_titles()))
    s.key(wx.WXK_F1)
    s.do(lambda: check("F1 in EPG Manager opens epg-manager", guide_topic() == "epg-manager", guide_topic()))
    s.key(wx.WXK_ESCAPE)
    s.do(lambda: check("guide closed, EPG Manager still open",
                       not guide_open() and "EPG Manager" in modal_titles(), modal_titles()))
    s.key(wx.WXK_ESCAPE)
    s.do(lambda: check("EPG Manager closed", not modal_titles(), modal_titles()))
    s.run()


if __name__ == "__main__":
    if not sys.platform.startswith("win"):
        print("skipped: Windows only")
        sys.exit(0)
    app = wx.App()
    main_frame = build_frame()
    build_script(main_frame)
    app.MainLoop()
    sys.exit(EXIT["code"])
