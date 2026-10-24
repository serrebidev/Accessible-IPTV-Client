"""Tests for the EPG-program -> playlist-channel matcher.

This scorer used to exist twice in main.py (once for the EPG dialog, once for
"What's on now"), and the copies had drifted: the duplicate lost the guard on an
empty channel name, so a program carrying only a channel_id scored 40 against
every channel and played an arbitrary one. Both call sites now share
_find_matching_channel_for_program, and these tests pin its behavior.
"""

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import IPTVClient  # noqa: E402


def _match(channels, program):
    """Call the scorer against a stub holding only what it reads."""
    stub = SimpleNamespace(all_channels=channels)
    return IPTVClient._find_matching_channel_for_program(stub, program)


CHANNELS = [
    {"name": "BBC One HD", "tvg-name": "BBC One", "tvg-id": "bbc.one.uk", "url": "u1"},
    {"name": "BBC Two", "tvg-name": "BBC Two", "tvg-id": "bbc.two.uk", "url": "u2"},
    {"name": "CNN International", "tvg-name": "CNN Intl", "tvg-id": "cnn.int", "url": "u3"},
    {"name": "Sky Sports Main Event", "tvg-name": "", "tvg-id": "", "url": "u4"},
]


def test_exact_tvg_id_wins():
    got = _match(CHANNELS, {"channel_name": "Something Else", "channel_id": "bbc.two.uk"})
    assert got is not None and got["url"] == "u2"


def test_exact_name_match():
    got = _match(CHANNELS, {"channel_name": "CNN International", "channel_id": ""})
    assert got is not None and got["url"] == "u3"


def test_normalized_match_ignores_quality_tag():
    """'BBC One' should reach 'BBC One HD' via canonicalization."""
    got = _match(CHANNELS, {"channel_name": "BBC One", "channel_id": ""})
    assert got is not None and got["url"] == "u1"


def test_no_match_below_threshold_returns_none():
    got = _match(CHANNELS, {"channel_name": "Al Jazeera Arabic", "channel_id": ""})
    assert got is None


def test_empty_program_returns_none():
    assert _match(CHANNELS, {"channel_name": "", "channel_id": ""}) is None


def test_unknown_channel_id_with_empty_name_does_not_match_everything():
    """Regression: the drifted copy scored 40 for every channel here.

    An empty channel_name is a substring of every channel name, so an unguarded
    `channel_name_lower in ch_name_lower` test matched all of them and the first
    channel won by arbitrary iteration order.
    """
    got = _match(CHANNELS, {"channel_name": "", "channel_id": "totally.unknown.id"})
    assert got is None


def test_empty_playlist_returns_none():
    assert _match([], {"channel_name": "BBC One", "channel_id": "bbc.one.uk"}) is None


def test_both_call_sites_share_one_implementation():
    """Guards against the scorer being copy-pasted apart again."""
    import inspect

    source = inspect.getsource(IPTVClient._play_from_whats_on_now)
    assert "_find_matching_channel_for_program" in source
    # The scoring constants should appear in exactly one method.
    assert "score = max(score, 70)" not in source


def test_lookup_is_memoized_per_playlist_and_dropped_on_reload():
    """Highlighting EPG rows reuses one index; a new channel list rebuilds it.

    The scan normalized every channel name per highlight and froze the GUI for
    2.5 s on a 50,000-channel playlist, so features and answers are cached
    against the identity of ``all_channels``.
    """
    stub = SimpleNamespace(all_channels=list(CHANNELS))
    program = {"channel_name": "BBC Two", "channel_id": ""}
    first = IPTVClient._find_matching_channel_for_program(stub, program)
    assert first["url"] == "u2"
    assert IPTVClient._find_matching_channel_for_program(stub, program) is first

    stub.all_channels = [{"name": "BBC Two", "tvg-id": "", "url": "new"}]
    assert IPTVClient._find_matching_channel_for_program(stub, program)["url"] == "new"


def test_first_exact_tvg_id_wins_over_later_duplicates():
    channels = [
        {"name": "Feed A", "tvg-id": "Same.Id", "url": "a"},
        {"name": "Feed B", "tvg-id": "same.id", "url": "b"},
    ]
    got = _match(channels, {"channel_name": "Feed B", "channel_id": "SAME.ID"})
    assert got["url"] == "a"


def test_a_different_channel_number_is_not_a_match():
    """The guide says BBC 1; the playlist has BBC One and BBC 2.

    The canonical name drops a standalone digit as a noise word, so BBC 1 and
    BBC 2 looked the same and the guide's programme landed on the wrong
    channel.
    """
    channels = [
        {"name": "BBC One", "url": "u1"},
        {"name": "BBC 2", "url": "u2"},
    ]
    got = _match(channels, {"channel_name": "BBC 1", "channel_id": ""})
    assert not got or got["url"] == "u1", got


def test_a_name_without_a_number_still_guesses():
    """The guide says ESPN; the playlist has ESPN 2 and ESPN 3.

    Nothing in the guide's name rules the numbered channels out, so the
    matcher still offers one of them - the same guess it made before.
    """
    channels = [
        {"name": "ESPN 2", "url": "u2"},
        {"name": "ESPN 3", "url": "u3"},
    ]
    got = _match(channels, {"channel_name": "ESPN", "channel_id": ""})
    assert got is not None and got["url"] == "u2"
