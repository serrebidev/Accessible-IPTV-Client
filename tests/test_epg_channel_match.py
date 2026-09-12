"""View EPG must find the same EPG channel as the channel list.

Reported on a playlist whose "TVN HD" carries only a tvg-id the guide does not
know (tvn-pl) and an epg.ovh guide that calls the channel "TVN": the channel
list, which matches by name, showed "Fakty" at 19:00, while View EPG showed
"Ukryta prawda" - TVN 7's programme. Every "TVN ..." guide channel tied on one
shared token, and the first in the guide won. The channel's own name has to
count as an exact match, the way the tvg-name already did.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playlist import EPGDatabase  # noqa: E402

# Guide order matters: TVN 7 comes first in epg.ovh's pltv.xml.
GUIDE = ("TVN 7", "TVN", "TVN Fabuła", "TVN Turbo", "TVN Style", "TVN 24 BiS", "TVN 24")


def _guide(tmp_path):
    db = EPGDatabase(str(tmp_path / "epg.db"))
    for name in GUIDE:
        db.insert_channel(name, name)
    db.commit()
    return db


def test_a_channel_is_found_by_its_own_name(tmp_path):
    db = _guide(tmp_path)
    try:
        assert db.resolve_best_channel_id({"name": "TVN HD", "tvg-id": "tvn-pl"}) == "TVN"
        assert db.resolve_best_channel_id({"name": "TVN HD"}) == "TVN"
    finally:
        db.close()


def test_numbered_and_named_siblings_still_find_themselves(tmp_path):
    db = _guide(tmp_path)
    try:
        assert db.resolve_best_channel_id({"name": "TVN 7 HD"}) == "TVN 7"
        assert db.resolve_best_channel_id({"name": "TVN Turbo HD"}) == "TVN Turbo"
        assert db.resolve_best_channel_id({"name": "TVN 24"}) == "TVN 24"
    finally:
        db.close()


def test_a_known_tvg_id_still_wins_over_the_name(tmp_path):
    db = _guide(tmp_path)
    try:
        db.insert_channel("tvn-pl", "TVN HD")
        db.commit()
        assert db.resolve_best_channel_id({"name": "TVN HD", "tvg-id": "tvn-pl"}) == "tvn-pl"
    finally:
        db.close()


def test_full_name_breaks_a_loose_match_tie_between_numbered_siblings(tmp_path):
    """Noise words must not make Sport 1 and Sport Extra 1 interchangeable."""
    db = EPGDatabase(str(tmp_path / "epg.db"))
    try:
        # Put Extra first to reproduce the order in the reported guide. Both
        # names collapse to "polsat sport" and both carry significant number 1.
        db.insert_channel("Polsat Sport Extra 1", "Polsat Sport Extra 1")
        db.insert_channel("Polsat Sport 1", "Polsat Sport 1")
        db.commit()

        common = {"tvg-id": "PolsatSport.pl", "group": "Sport"}
        assert db.resolve_best_channel_id({
            **common,
            "name": "Polsat Sport 1 HD",
            "tvg-name": "Polsat Sport 1 HD",
        }) == "Polsat Sport 1"
        assert db.resolve_best_channel_id({
            **common,
            "name": "Polsat Sport Extra 1 HD",
            "tvg-name": "Polsat Sport Extra 1 HD",
        }) == "Polsat Sport Extra 1"
    finally:
        db.close()


def test_full_name_tiebreak_does_not_override_a_higher_score(tmp_path):
    db = _guide(tmp_path)
    try:
        db.get_matching_channel_ids = lambda _channel: ([
            {"id": "loose", "display_name": "Other", "score": 49, "why": "fuzzy"},
            {"id": "exact", "display_name": "Wanted HD", "score": 48, "why": "exact-name"},
        ], "")
        db._has_any_schedule_from_now = lambda _channel_id: True
        assert db.resolve_best_channel_id({"name": "Wanted HD"}) == "loose"
    finally:
        db.close()


def test_full_name_tiebreak_does_not_override_schedule_availability(tmp_path):
    db = _guide(tmp_path)
    try:
        db.get_matching_channel_ids = lambda _channel: ([
            {"id": "loose", "display_name": "Other", "score": 48, "why": "fuzzy"},
            {"id": "exact", "display_name": "Wanted HD", "score": 48, "why": "exact-name"},
        ], "")
        db._has_any_schedule_from_now = lambda channel_id: channel_id == "loose"
        assert db.resolve_best_channel_id({"name": "Wanted HD"}) == "loose"
    finally:
        db.close()
