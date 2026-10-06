"""Guides a playlist names in its #EXTM3U header (x-tvg-url / url-tvg).

Dispatcharr, Xtream panels and iptv-org playlists name their XMLTV guide in
the header; the app ignored it, so a user had to find and add the guide URL
by hand in EPG Manager.
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402

GUIDE = "https://tv.example/xmltv.php?username=u&password=p"


def test_dispatcharr_header_names_its_guide():
    text = (f'#EXTM3U x-tvg-url="{GUIDE}" url-tvg="{GUIDE}" catchup-timezone="UTC"\n'
            '#EXTINF:-1 tvg-id="1",CNN\nhttps://tv.example/live/u/p/1\n')
    assert main._playlist_header_epg_urls(text) == [GUIDE]


def test_several_guides_and_the_url_tvg_alias():
    text = '\ufeff#EXTM3U url-tvg="https://a.example/1.xml.gz, https://b.example/2.xml"\n'
    assert main._playlist_header_epg_urls(text) == [
        "https://a.example/1.xml.gz", "https://b.example/2.xml"]


def test_only_web_guides_from_the_first_line_are_used():
    assert main._playlist_header_epg_urls('#EXTM3U x-tvg-url="C:\\guides\\local.xml"\n') == []
    assert main._playlist_header_epg_urls('#EXTM3U\n#EXTINF:-1 x-tvg-url="https://x/1.xml",A\n') == []
    assert main._playlist_header_epg_urls('#EXTINF:-1,A\nhttp://x/1\n') == []
    assert main._playlist_header_epg_urls("") == []


def _client(config, provider=(), playlist=()):
    client = SimpleNamespace(config=config, provider_epg_sources=list(provider),
                             playlist_epg_sources=list(playlist))
    main.IPTVClient.reload_epg_sources(client)
    return client.epg_sources


def test_playlist_guides_join_the_configured_ones_without_duplicates():
    sources = _client({"epgs": [GUIDE + " "]}, provider=["https://prov/epg.xml"],
                      playlist=[GUIDE, "https://other/guide.xml"])
    assert sources == [GUIDE + " ", "https://prov/epg.xml", "https://other/guide.xml"]


def test_the_epg_manager_checkbox_turns_playlist_guides_off():
    sources = _client({"epgs": ["a.xml"], "use_playlist_epg": False},
                      provider=["https://prov/epg.xml"], playlist=["https://other/guide.xml"])
    assert sources == ["a.xml", "https://prov/epg.xml"]



def test_refreshing_one_playlist_replaces_only_its_own_guides():
    previous = {"a.m3u": ["https://a/old.xml"], "b.m3u": ["https://b/guide.xml"]}
    by_source, flat = main._merge_playlist_header_guides(
        previous, {"a.m3u": ["https://a/new.xml"]}, ["a.m3u", "b.m3u"])
    assert by_source == {"a.m3u": ["https://a/new.xml"], "b.m3u": ["https://b/guide.xml"]}
    assert flat == ["https://a/new.xml", "https://b/guide.xml"]


def test_a_header_that_drops_its_guide_and_a_removed_playlist_lose_it():
    previous = {"a.m3u": ["https://a/old.xml"], "gone.m3u": ["https://gone/guide.xml"]}
    by_source, flat = main._merge_playlist_header_guides(previous, {"a.m3u": []}, ["a.m3u"])
    assert by_source == {"a.m3u": []}
    assert flat == []


def test_an_uppercase_scheme_is_normalized_for_the_importer():
    text = '#EXTM3U x-tvg-url="HTTP://Guide.example/EPG.xml,Https://b.example/x.xml"\n'
    assert main._playlist_header_epg_urls(text) == [
        "http://Guide.example/EPG.xml", "https://b.example/x.xml"]


def test_an_unquoted_guide_list_keeps_every_guide():
    text = '#EXTM3U x-tvg-url=https://a.example/1.xml,https://b.example/2.xml?x=1 tvg-shift=0\n'
    assert main._playlist_header_epg_urls(text) == [
        "https://a.example/1.xml", "https://b.example/2.xml?x=1"]
