from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import favorites
import favorite_collections as lists
import main
import playback_resume
import playlist_index
import programme_reminders
import subtitle_cues
from client_m3u import M3uCacheMixin


def station(source, name="Concert", path="/regular"):
    return {"playlist-id": source, "name": name, "url": "https://example.invalid/" + source + path, "tvg-id": name}


def test_number_through_m3u_import_keyboard_and_fallback(monkeypatch):
    channels = M3uCacheMixin()._parse_m3u_return(
        '#EXTM3U\n#EXTINF:-1 tvg-chno="02",Koncert\nhttps://example.invalid/c\n'
        "#EXTINF:-1 TVG-CHNO=1,Hírek\nhttps://example.invalid/h\n#EXTINF:-1,Film\nhttps://example.invalid/f"
    )
    assert [ch.get("tvg-chno") for ch in channels] == ["02", "1", None]
    dlg = Mock()
    dlg.ShowModal.return_value = main.wx.ID_OK
    dlg.GetValue.side_effect = ["2", "03", "0", "9" * 4900, "٠٢"]
    monkeypatch.setattr(main.wx, "TextEntryDialog", lambda *args: dlg)
    monkeypatch.setattr(main, "message_box", Mock())
    owner = SimpleNamespace(scoped_all_channels=lambda: channels, _play_live_channel=Mock())
    for _ in range(5):
        main.IPTVClient._go_to_channel_number(owner)
    assert [args.args[0]["name"] for args in owner._play_live_channel.call_args_list] == ["Koncert", "Film", "Koncert"]
    assert main.message_box.call_count == 2


def test_previous_and_legacy_history_never_choose_another_source(monkeypatch):
    a, b, news = station("a"), station("b"), station("a", "News")
    owner = SimpleNamespace(config={}, all_channels=[a, b, news], recent_channel_keys=[], _play_live_channel=Mock())
    monkeypatch.setattr(main, "save_config", Mock())
    owner._recent_channels = lambda: main.IPTVClient._recent_channels(owner)
    for ch in (a, news):
        main.IPTVClient._remember_played_channel(owner, ch)
    main.IPTVClient._play_previous_channel(owner)
    owner._play_live_channel.assert_called_once_with(a)
    owner.all_channels = [a, b]  # The current channel disappeared on refresh.
    main.IPTVClient._play_previous_channel(owner)
    assert owner._play_live_channel.call_count == 2 and owner._play_live_channel.call_args.args == (a,)
    assert favorites.history_channels([favorites.channel_key(a)], [a, b]) == []
    assert favorites.history_channels([favorites.channel_key(a)], [a]) == [a]
    assert favorites.history_channels(owner.recent_channel_keys, [b, news]) == [news]
    assert favorites.history_labels([a, b], {"a": "First", "b": "Second"}) == ["Concert — First", "Concert — Second"]
    assert favorites.history_labels([a, b], {"a": "Home", "b": "Home"}) == [
        "Concert — Home (Source 1)",
        "Concert — Home (Source 2)",
    ]


def test_manual_variant_resolution_preserves_both_and_legacy_entries():
    a, b = station("a"), station("a", path="/hd")
    rows, id_ = lists.create([], "Concerts")
    for ch in [a, b, b]:
        rows = lists.edit(rows, id_, selection=lists.selected_entry(ch, [a, b]))
    entries = rows[0]["entries"]
    assert [ch for _, ch in lists.resolve(lists.normalize(rows)[0]["entries"], [b, a])] == [a, b]
    assert len(entries) == 2 and not any("http" in str(e) for e in entries)
    single = lists.selected_entry(a, [a])
    assert single["key"] == programme_reminders.channel_key(a)
    old = station("gone")
    rows = lists.edit(rows, id_, add=old)
    with pytest.raises(ValueError):
        lists.relink(rows, id_, programme_reminders.channel_key(old), a, selection=lists.selected_entry(a, [a, b]))
    rows = lists.edit(rows, id_, remove=entries[0]["key"])
    changed = lists.relink(
        rows, id_, programme_reminders.channel_key(old), a, selection=lists.selected_entry(a, [a, b])
    )
    assert [ch for _, ch in lists.resolve(changed[0]["entries"], [a, b])] == [b, a]
    with pytest.raises(ValueError):
        lists.selected_entry(a, [b])


@pytest.mark.parametrize(
    "text,result",
    [
        ("2 < 3, és 5 > 4.", "2 < 3, és 5 > 4."),
        ("x<y és z>0; <b>fény</b>", "x<y és z>0; fény"),
        ('<font color="red">2 < 3</font><i>!</i>', "2 < 3!"),
        ("<v Speaker>Így: &lt;adat&gt;</v>", "Így: <adat>"),
        ("<00:02.100><c.green>Halló</c>", "Halló"),
        ("<i " * 10000 + "<b>szó</b>", "<i " * 10000 + "szó"),
    ],
)
def test_subtitle_math_and_inline_markup(text, result):
    assert subtitle_cues.parse("1\n00:00:00,000 --> 00:00:02,000\n" + text)[0].text == result


def test_continue_watching_open_never_iterates_live_catalogue(monkeypatch):
    class Catalogue(list):
        def __iter__(self):
            raise AssertionError("GUI traversed the catalogue")

    owner = SimpleNamespace(
        all_channels=Catalogue([{"kind": "live"}] * 100000),
        vod_groups={},
        provider_clients={},
        config={},
        _playlist_load_token=1,
        displayed=[],
    )
    dialog = Mock()
    dialog.ShowModal.return_value = main.wx.ID_CANCEL
    monkeypatch.setattr(main, "ContinueWatchingDialog", Mock(return_value=dialog))
    main.IPTVClient._show_continue_watching(owner)
    assert dialog.Destroy.called
    resolve = main.ContinueWatchingDialog.call_args.args[-1]
    assert resolve("gone", {}) is None
    assert playback_resume.resolve_current("gone", {}, lambda: (_ for _ in () if False), {}) is None


def test_large_cached_search_counts_no_repeated_conversions():
    class Name(str):
        calls = 0

        def lower(self):
            Name.calls += 1
            return super().lower()

    rows = [{"name": Name("Próba " + str(i))} for i in range(25000)]
    idx = playlist_index.PlaylistIndex(rows, {})
    built = Name.calls
    for query in ("p", "pr", "pró"):
        assert len(idx.search(rows, query)) == 25000
    assert built == 25000 and Name.calls == built
    assert idx.normalized_name({"name": Name("Új")}) == "új"
    assert Name.calls == built + 1
