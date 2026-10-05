import types

import internal_player


class Item:
    def __init__(self, label, submenu=None):
        self.label = label
        self.submenu = submenu

    def GetId(self):
        return id(self)

    def GetSubMenu(self):
        return self.submenu

    def Check(self, value):
        pass


class Menu:
    def __init__(self):
        self.items = []

    def Append(self, identifier, label):
        item = Item(label)
        self.items.append(item)
        return item

    AppendCheckItem = Append

    def AppendSubMenu(self, submenu, label):
        item = Item(label, submenu)
        self.items.append(item)
        return item

    def AppendSeparator(self):
        pass

    def GetMenuItems(self):
        return self.items


def test_player_menu_registers_specific_help_topics(monkeypatch):
    monkeypatch.setattr(internal_player.wx, "Menu", Menu)
    monkeypatch.setattr(internal_player.wx, "MenuBar", lambda: types.SimpleNamespace(Append=lambda *args: None))
    frame = types.SimpleNamespace(
        _speak_subtitles=False,
        _shortcut_label=lambda label, action: label,
        Bind=lambda *args: None,
        SetMenuBar=lambda *args: None,
        _on_any_menu_open=lambda *args: None,
        _on_audio_track_menu_select=lambda *args: None,
        _on_record=lambda *args: None,
        _on_audio_device_menu=lambda *args: None,
        _on_subtitle_menu_select=lambda *args: None,
        _load_subtitle_file=lambda *args: None,
    )
    internal_player.InternalPlayerFrame._build_menu_bar(frame)
    assert "audio-output-device" in frame.help_menu_topics.values()
    assert frame.help_menu_topics[frame.record_menu_item.GetId()] == "recordings"
    assert "casting" in frame.help_menu_topics.values()
