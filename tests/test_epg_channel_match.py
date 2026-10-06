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


def _programme_now(db, channel_id, title):
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    fmt = "%Y%m%d%H%M%S"
    db.insert_programme(channel_id, title, (now - datetime.timedelta(minutes=30)).strftime(fmt),
                        (now + datetime.timedelta(minutes=30)).strftime(fmt))


def test_own_tvg_id_beats_fuzzy_candidates_with_higher_scores(tmp_path):
    """Dispatcharr guides key channels by number; that number is the channel.

    A loose "CBS ... East" candidate collected brand, region and implicit-East
    bonuses and outscored CBS News Pittsburgh's own guide.
    """
    db = EPGDatabase(str(tmp_path / "epg.db"))
    try:
        db.insert_channel("3266", "CBS News Pittsburgh")
        db.insert_channel("2191", "CBS East Miami")
        _programme_now(db, "3266", "Local News")
        _programme_now(db, "2191", "Miami News")
        db.commit()
        channel = {"name": "CBS News Pittsburgh", "tvg-id": "3266", "group": "USA: News"}
        assert db.resolve_best_channel_id(channel) == "3266"
    finally:
        db.close()


def test_own_guide_with_nothing_on_does_not_borrow_an_unrelated_schedule(tmp_path):
    db = EPGDatabase(str(tmp_path / "epg.db"))
    try:
        db.insert_channel("7418", "Cheers United States")
        db.insert_channel("7561", "National Geographic United States HD East")
        _programme_now(db, "7561", "Wild")
        db.commit()
        channel = {"name": "Cheers United States", "tvg-id": "7418"}
        assert db.resolve_best_channel_id(channel) == "7418"
    finally:
        db.close()


def test_own_guide_with_nothing_on_may_use_a_same_named_guide(tmp_path):
    db = EPGDatabase(str(tmp_path / "epg.db"))
    try:
        db.insert_channel("4233", "Matlock")
        db.insert_channel("9831", "Matlock")
        _programme_now(db, "9831", "The Mistress")
        db.commit()
        assert db.resolve_best_channel_id({"name": "Matlock", "tvg-id": "4233"}) == "9831"
    finally:
        db.close()


def test_exact_name_number_bonus_does_not_hide_the_id_hit(tmp_path):
    db = EPGDatabase(str(tmp_path / "epg.db"))
    try:
        db.insert_channel("10367", "Telemundo 25 KUTU Tulsa")
        db.insert_channel("10306", "Telemundo East")
        _programme_now(db, "10367", "Noticias")
        _programme_now(db, "10306", "Novela")
        db.commit()
        channel = {"name": "Telemundo 25 KUTU Tulsa", "tvg-id": "10367"}
        assert db.resolve_best_channel_id(channel) == "10367"
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


def test_a_numeric_tvg_id_is_not_a_channel_number(tmp_path):
    """Dispatcharr/Xtream tvg-ids are row numbers ("2"), not channel numbers.

    Read as a number, tvg-id "2" sent "ESPN" to "ESPN 2" and "HBO" to "HBO 2"
    whenever the guide did not know the id.
    """
    db = EPGDatabase(str(tmp_path / "epg.db"))
    try:
        for cid, name in (("espn.us", "ESPN"), ("espn2.us", "ESPN 2"),
                          ("hbo.us", "HBO"), ("hbo2.us", "HBO 2")):
            db.insert_channel(cid, name)
        db.commit()
        assert db.resolve_best_channel_id({"name": "ESPN", "tvg-id": "2"}) == "espn.us"
        assert db.resolve_best_channel_id({"name": "HBO", "tvg-id": "2"}) == "hbo.us"
        # A number in the name still counts.
        assert db.resolve_best_channel_id({"name": "ESPN 2", "tvg-id": "7"}) == "espn2.us"
    finally:
        db.close()
