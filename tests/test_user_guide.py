"""Tests for the in-app User Guide (user_guide.py) and its F1 context help.

The guide files and the topic ids the program asks for must stay in step: a
typo on either side silently turns context help into "the start of the
manual", which is exactly the failure nobody notices by reading the code.
"""
import os
import re
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import i18n  # noqa: E402
import user_guide  # noqa: E402

HELP_DIR = os.path.join(ROOT, "docs", "help")
APP_SOURCES = ("main.py", "internal_player.py", "playlist.py", "options.py")
_ANCHOR = re.compile(r"\{#([a-z0-9-]+)\}")
_TOPIC_PATTERNS = (
    re.compile(r'help_topic\s*=\s*"([a-z0-9-]+)"'),
    re.compile(r'set_help_topic\(\s*[^,()]+,\s*"([a-z0-9-]+)"'),
    re.compile(r'set_menu_help\(\s*[^,()]+,\s*[^,()]+,\s*"([a-z0-9-]+)"'),
    re.compile(r'_list_help_topic\("([a-z0-9-]+)"\)'),
)


def teardown_function(_func):
    i18n.set_language("en")


def _english():
    return user_guide.load_guide("en", HELP_DIR)


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _topics_used_by_the_program():
    found = set()
    for name in APP_SOURCES:
        text = _read(os.path.join(ROOT, name))
        for pattern in _TOPIC_PATTERNS:
            found.update(pattern.findall(text))
    return found


# --------------------------------------------------------------------------- #
# The shipped guides
# --------------------------------------------------------------------------- #
def test_every_topic_the_program_opens_exists_in_the_english_guide():
    used = _topics_used_by_the_program() | {user_guide.DEFAULT_TOPIC, user_guide.HELP_TOPIC}
    missing = sorted(used - set(_english().topics()))
    assert not missing, f"F1 topics with no section in docs/help/en.md: {missing}"


def test_the_examples_from_the_feature_request_are_wired():
    # Issue #14: EPG Manager, Import EPG, Preferred Audio Track, catch-up,
    # the recording scheduler and the built-in player each open their own section.
    used = _topics_used_by_the_program()
    for topic in ("epg-manager", "import-epg", "preferred-audio-track", "catch-up",
                  "scheduled-recordings", "built-in-player"):
        assert topic in used, topic


@pytest.mark.parametrize("language", user_guide.available_languages(HELP_DIR))
def test_topic_ids_are_unique(language):
    anchors = _ANCHOR.findall(_read(os.path.join(HELP_DIR, f"{language}.md")))
    duplicates = sorted({a for a in anchors if anchors.count(a) > 1})
    assert not duplicates, f"{language}.md repeats topic ids: {duplicates}"


@pytest.mark.parametrize(
    "language", [code for code in user_guide.available_languages(HELP_DIR) if code != "en"])
def test_translated_guides_only_use_english_topic_ids(language):
    english = set(_english().topics())
    translated = set(_ANCHOR.findall(_read(os.path.join(HELP_DIR, f"{language}.md"))))
    unknown = sorted(translated - english)
    assert not unknown, f"{language}.md has topic ids en.md does not: {unknown}"


def test_english_guide_opens_on_its_title():
    guide = _english()
    assert guide.language == "en"
    assert guide.sections[0].topic == user_guide.DEFAULT_TOPIC
    assert guide.sections[0].start == 0


def test_section_offsets_point_at_their_headings():
    guide = _english()
    for section in guide.sections:
        assert guide.text[section.start:].startswith(section.title), section.topic
        assert section.start == 0 or guide.text[section.start - 1] == "\n", section.topic


def test_rendered_guide_has_no_markdown_left():
    text = _english().text
    assert "**" not in text
    assert "{#" not in text
    assert "<!--" not in text
    assert not re.search(r"^#+ ", text, re.MULTILINE)


def test_pyinstaller_spec_bundles_the_guide():
    spec = _read(os.path.join(ROOT, "main.spec"))
    assert "help_datas" in spec
    assert "locale_datas + help_datas" in spec


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def test_render_supports_the_documented_markdown_subset():
    source = (
        "<!-- a note for translators -->\n"
        "# Title {#top}\n"
        "\n"
        "First line\n"
        "second line.\n"
        "\n"
        "- **Bold** item\n"
        "  continued here\n"
        "- `code` and [a link](https://example.com)\n"
        "1. Step one\n"
        "\n"
        "## Next {#next}\n"
        "Text with *emphasis* and a [local link](#top).\n"
        "### Untitled heading\n"
    )
    guide = user_guide.render(source)
    assert guide.text == (
        "Title\n"
        "\n"
        "First line second line.\n"
        "\n"
        "Bold item continued here\n"
        "code and a link (https://example.com)\n"
        "1. Step one\n"
        "\n"
        "Next\n"
        "\n"
        "Text with emphasis and a local link.\n"
        "\n"
        "Untitled heading"
    )
    assert [(s.topic, s.level) for s in guide.sections] == [
        ("top", 1), ("next", 2), ("section-3", 3)]


def test_render_keeps_lone_asterisks_and_crlf_sources():
    guide = user_guide.render("# T {#t}\r\n\r\nA * B * C\r\n")
    assert guide.text == "T\n\nA * B * C"


def test_section_at_finds_the_enclosing_section():
    guide = user_guide.render("# A {#a}\n\ntext\n\n## B {#b}\n\nmore text\n")
    b = guide.find("b")
    assert guide.section_at(0).topic == "a"
    assert guide.section_at(b.start - 1).topic == "a"
    assert guide.section_at(b.start).topic == "b"
    assert guide.section_at(len(guide.text)).topic == "b"


# --------------------------------------------------------------------------- #
# Language choice and fallbacks
# --------------------------------------------------------------------------- #
def _write_guides(folder, **guides):
    for language, text in guides.items():
        (folder / f"{language}.md").write_text(text, encoding="utf-8")
    return str(folder)


_EN = "# Guide {#user-guide}\n\n## Search {#search}\n\nEnglish search.\n\n## EPG Manager {#epg-manager}\n\nEPG.\n"
_HU = "# Útmutató {#user-guide}\n\n## Keresés {#search}\n\nMagyar keresés.\n"


def test_a_language_without_a_guide_falls_back_to_english(tmp_path):
    folder = _write_guides(tmp_path, en=_EN)
    assert user_guide.load_guide("hu", folder).language == "en"
    assert user_guide.load_guide("", folder).language == "en"


def test_a_translated_guide_is_used(tmp_path):
    folder = _write_guides(tmp_path, en=_EN, hu=_HU)
    assert user_guide.load_guide("hu", folder).language == "hu"
    assert user_guide.load_guide("hu_HU", folder).language == "hu"
    assert user_guide.available_languages(folder) == ["en", "hu"]


def test_a_topic_the_translation_lacks_opens_the_english_section(tmp_path):
    folder = _write_guides(tmp_path, en=_EN, hu=_HU)
    guide, section = user_guide.open_topic("hu", "epg-manager", folder)
    assert (guide.language, section.topic) == ("en", "epg-manager")
    guide, section = user_guide.open_topic("hu", "search", folder)
    assert (guide.language, section.title) == ("hu", "Keresés")


def test_the_start_of_the_manual_never_falls_back(tmp_path):
    # A translation that forgot the anchor on its title still opens itself.
    folder = _write_guides(tmp_path, en=_EN, hu="# Útmutató\n\nSzöveg.\n")
    guide, section = user_guide.open_topic("hu", "", folder)
    assert guide.language == "hu"
    assert section is guide.sections[0]


def test_an_unknown_topic_opens_the_start(tmp_path):
    folder = _write_guides(tmp_path, en=_EN, hu=_HU)
    guide, section = user_guide.open_topic("hu", "no-such-topic", folder)
    assert guide.language == "hu"
    assert section.topic == "user-guide"


def test_no_guide_at_all_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        user_guide.load_guide("en", str(tmp_path))


def test_resolved_language_follows_the_setting():
    i18n.set_language("hu")
    assert i18n.resolved_language() == "hu"
    i18n.set_language("en")
    assert i18n.resolved_language() == "en"


# --------------------------------------------------------------------------- #
# Context topics
# --------------------------------------------------------------------------- #
class _Window:
    help_menu_topics: dict

    def __init__(self, parent=None, topic=None):
        self._parent = parent
        if topic is not None:
            self.help_topic = topic

    def GetParent(self):
        return self._parent


class _Item:
    def __init__(self, item_id, submenu=None):
        self._id = item_id
        self._submenu = submenu

    def GetId(self):
        return self._id

    def GetSubMenu(self):
        return self._submenu


class _Menu:
    def __init__(self, items):
        self._items = items

    def GetMenuItems(self):
        return list(self._items)


def test_topic_comes_from_the_nearest_window_that_has_one():
    dialog = _Window(topic="epg-manager")
    button = _Window(_Window(dialog))
    assert user_guide.topic_for_window(button) == "epg-manager"
    assert user_guide.topic_for_window(_Window()) == user_guide.DEFAULT_TOPIC
    assert user_guide.topic_for_window(None) == user_guide.DEFAULT_TOPIC


def test_a_callable_topic_is_asked_each_time():
    mode = {"topic": "channel-list"}
    channel_list = _Window(topic=lambda: mode["topic"])
    assert user_guide.topic_for_window(channel_list) == "channel-list"
    mode["topic"] = "video-on-demand"
    assert user_guide.topic_for_window(channel_list) == "video-on-demand"


def test_a_failing_callable_topic_falls_back_to_the_parent():
    def broken():
        raise RuntimeError("wrapped C/C++ object has been deleted")

    child = _Window(_Window(topic="main-window"), topic=broken)
    assert user_guide.topic_for_window(child) == "main-window"


def test_menu_topics_cover_submenus_and_allow_overrides():
    owner = _Window()
    language = _Item(1)
    nested = _Menu([_Item(3)])
    options = _Menu([language, _Item(2, nested)])
    user_guide.set_menu_help(owner, options, "options")
    user_guide.set_menu_help(owner, language, "language")
    assert owner.help_menu_topics == {1: "language", 2: "options", 3: "options"}
    assert user_guide.topic_for_menu_item(_Window(owner), 3) == "options"
    assert user_guide.topic_for_menu_item(owner, 99) is None


def test_menu_ids_from_wm_help_match_negative_wx_ids():
    # WM_HELP reports the command id as an unsigned 16-bit number; wx's
    # automatic menu ids are negative. Found by tools/smoke_user_guide_f1.py.
    owner = _Window()
    user_guide.set_menu_help(owner, _Item(-31992), "epg-manager")
    user_guide.set_menu_help(owner, _Item(1003), "import-epg")
    assert user_guide.topic_for_menu_item(owner, 65536 - 31992) == "epg-manager"
    assert user_guide.topic_for_menu_item(owner, -31992) == "epg-manager"
    assert user_guide.topic_for_menu_item(owner, 1003) == "import-epg"


# --------------------------------------------------------------------------- #
# The help window (real wx)
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def wx_app():
    wx = pytest.importorskip("wx")
    try:
        app = wx.GetApp() or wx.App()
    except Exception as exc:  # pragma: no cover - headless CI without a display
        pytest.skip(f"no usable display for wxPython: {exc}")
    # Held for the whole module: an unreferenced wx.App is collected at once.
    yield app


@pytest.fixture(scope="module")
def appmod(wx_app):
    import main

    return main


@pytest.fixture
def host(appmod):
    wx = appmod.wx

    frame = wx.Frame(None, title="user guide host")
    yield frame
    frame.Destroy()


@pytest.fixture
def guide_dialog(appmod, host):
    dlg = appmod.UserGuideDialog(host, "epg-manager", language="en")
    yield dlg
    dlg.Destroy()


def test_dialog_opens_at_the_requested_topic(guide_dialog):
    section = guide_dialog.guide.find("epg-manager")
    assert guide_dialog.text.GetInsertionPoint() == section.start
    assert guide_dialog.text.GetRange(section.start, section.start + len(section.title)) == section.title
    assert guide_dialog.topics_list.GetStringSelection() == section.title


def test_arrowing_through_topics_moves_the_text(guide_dialog):
    target = guide_dialog.guide.find("catch-up")
    guide_dialog.topics_list.SetSelection(guide_dialog.guide.sections.index(target))
    guide_dialog._on_topic_highlighted(None)
    assert guide_dialog.text.GetInsertionPoint() == target.start


def test_find_selects_each_match_and_follows_its_section(guide_dialog):
    guide_dialog.find_box.SetValue("SCHEDULE PADDING")
    assert guide_dialog.find(forward=True)
    first = guide_dialog.text.GetSelection()
    assert guide_dialog.text.GetStringSelection().lower() == "schedule padding"
    section = guide_dialog.guide.section_at(first[0])
    assert guide_dialog.topics_list.GetStringSelection() == section.title
    assert guide_dialog.find(forward=True)
    second = guide_dialog.text.GetSelection()
    assert second != first
    assert guide_dialog.find(forward=False)
    assert guide_dialog.text.GetSelection() == first


def test_find_says_when_there_is_no_match(guide_dialog, appmod, monkeypatch):
    shown = []
    monkeypatch.setattr(appmod, "message_box", lambda *args, **_kwargs: shown.append(args))
    guide_dialog.find_box.SetValue("qwertyuiop-not-in-the-guide")
    assert not guide_dialog.find()
    assert shown and "qwertyuiop-not-in-the-guide" in shown[0][0]


def test_show_topic_moves_an_open_guide(guide_dialog):
    guide_dialog.show_topic(user_guide.HELP_TOPIC)
    section = guide_dialog.guide.find(user_guide.HELP_TOPIC)
    assert guide_dialog.text.GetInsertionPoint() == section.start


def test_f1_resolves_the_topic_and_ignores_the_echo(appmod, monkeypatch):
    calls = []
    monkeypatch.setattr(appmod.wx, "CallAfter", lambda func, *args: calls.append((func, args)))
    monkeypatch.setattr(appmod, "_help_parent", lambda _window: None)
    monkeypatch.setattr(appmod, "_LAST_HELP_REQUEST", 0.0)
    dialog = _Window(topic="epg-manager")
    assert appmod.request_context_help(_Window(dialog))
    # The WM_HELP half of the same key press.
    assert not appmod.request_context_help(_Window(dialog))
    assert calls == [(appmod.show_user_guide, (None, "epg-manager"))]


def test_f1_on_a_menu_item_uses_the_item_topic(appmod, monkeypatch):
    calls = []
    monkeypatch.setattr(appmod.wx, "CallAfter", lambda func, *args: calls.append((func, args)))
    monkeypatch.setattr(appmod, "_help_parent", lambda _window: None)
    monkeypatch.setattr(appmod, "_LAST_HELP_REQUEST", 0.0)
    frame = _Window(topic="main-window")
    frame.help_menu_topics = {42: "language"}
    assert appmod.request_context_help(frame, menu_item_id=42)
    monkeypatch.setattr(appmod, "_LAST_HELP_REQUEST", 0.0)
    assert appmod.request_context_help(frame, menu_item_id=7)  # unmapped: the window's topic
    # The menu is ended only after the WM_HELP handler has returned.
    assert calls == [(appmod._end_menu_then_show, (None, "language")),
                     (appmod._end_menu_then_show, (None, "main-window"))]


def test_guide_waits_for_the_menu_loop_to_end(appmod, monkeypatch):
    opened, later = [], []
    monkeypatch.setattr(appmod, "show_user_guide", lambda _parent, topic: opened.append(topic))
    monkeypatch.setattr(appmod.wx, "CallLater", lambda _ms, func, *args: later.append((func, args)))
    monkeypatch.setattr(appmod, "_menu_mode_active", lambda: True)
    appmod._show_when_menus_closed(None, "casting")
    assert not opened and later[0][0] is appmod._show_when_menus_closed
    monkeypatch.setattr(appmod, "_menu_mode_active", lambda: False)
    func, args = later[0]
    func(*args)
    assert opened == ["casting"]
    # A menu that never closes cannot hold the guide back for ever.
    monkeypatch.setattr(appmod, "_menu_mode_active", lambda: True)
    appmod._show_when_menus_closed(None, "casting", tries=appmod._MENU_WAIT_TRIES)
    assert opened == ["casting", "casting"]


def test_f1_waits_while_a_message_box_is_up(appmod, monkeypatch):
    calls = []
    monkeypatch.setattr(appmod.wx, "CallAfter", lambda *args: calls.append(args))
    monkeypatch.setattr(appmod, "modal_box_is_open", lambda: True)
    monkeypatch.setattr(appmod, "_LAST_HELP_REQUEST", 0.0)
    assert not appmod.request_context_help(_Window(topic="search"))
    assert not calls


def test_menu_click_opens_the_start_of_the_guide(appmod, monkeypatch):
    opened = []
    monkeypatch.setattr(appmod, "show_user_guide", lambda _parent, topic: opened.append(topic))
    monkeypatch.setattr(appmod.wx, "GetKeyState", lambda _key: False)
    frame = types.SimpleNamespace()
    appmod.IPTVClient._on_user_guide_menu(frame)
    assert opened == [user_guide.DEFAULT_TOPIC]


def test_channel_lists_switch_to_the_vod_topic(appmod):
    frame = types.SimpleNamespace(view_mode="vod")
    assert appmod.IPTVClient._list_help_topic(frame, "channel-list") == "video-on-demand"
    frame.view_mode = "live"
    assert appmod.IPTVClient._list_help_topic(frame, "channel-list") == "channel-list"
