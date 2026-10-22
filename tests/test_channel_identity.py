"""Which guide channel is this playlist channel?

The rule: names say whether two channels are the same, numbers say when they
are not. "BBC 2" must never land on the guide's "BBC 3".
"""

from channel_identity import guide_indexes, match_guide_channel


def _guide(**channels):
    """A guide: channel id -> entry with a display name."""
    return {cid: {"display_name": name} for cid, name in channels.items()}


class TestMatchGuideChannel:
    def test_a_numbered_channel_keeps_its_own_guide(self):
        """The guide's "BBC 2" is the playlist's "BBC 2"."""
        guide = _guide(**{"bbc-1": "BBC 1", "bbc-2": "BBC 2", "bbc-3": "BBC 3"})
        indexes = guide_indexes(guide)
        hit = match_guide_channel({"name": "BBC 2", "tvg-id": "", "tvg-name": ""}, indexes)
        assert hit and hit["display_name"] == "BBC 2"

    def test_a_numbered_channel_does_not_take_its_siblings_guide(self):
        """A name that only fits after the noise is stripped is not enough.

        The guide spells some channels out - "BBC One", "BBC Two" - and
        numbers others - "BBC 3". The noise stripped names of "BBC Two" and
        "BBC 3" are both "bbc", so a playlist channel with no guide of its
        own used to land on whichever sibling the guide listed first.
        """
        guide = _guide(**{"bbc-one": "BBC One", "bbc-two": "BBC Two", "bbc3": "BBC 3"})
        indexes = guide_indexes(guide)
        hit = match_guide_channel({"name": "BBC 2", "tvg-id": "", "tvg-name": ""}, indexes)
        assert hit is None or hit["display_name"] == "BBC 2"

    def test_a_word_number_counts_as_the_number(self):
        """"BBC Two" and "BBC 2" are the same channel."""
        guide = _guide(**{"bbc-1": "BBC One", "bbc-2": "BBC Two"})
        indexes = guide_indexes(guide)
        hit = match_guide_channel({"name": "BBC Two", "tvg-id": "", "tvg-name": ""}, indexes)
        assert hit and hit["display_name"] == "BBC Two"

    def test_a_channel_without_a_number_still_matches(self):
        """Only two names that both carry a number can disagree."""
        guide = _guide(**{"cnn": "CNN", "cnn-int": "CNN International"})
        indexes = guide_indexes(guide)
        hit = match_guide_channel({"name": "CNN", "tvg-id": "", "tvg-name": ""}, indexes)
        assert hit and hit["display_name"] == "CNN"

    def test_the_tvg_id_wins_over_the_name(self):
        """An id is the channel's identity, so it is not second-guessed."""
        guide = _guide(**{"epg-1": "Totally Different"})
        indexes = guide_indexes(guide)
        hit = match_guide_channel(
            {"name": "BBC 2", "tvg-id": "EPG-1", "tvg-name": ""}, indexes)
        assert hit and hit["display_name"] == "Totally Different"

    def test_a_known_guide_with_nothing_on_does_not_borrow_a_namesake(self):
        """A channel with its own (currently empty) guide gets nothing."""
        guide = _guide(hours="Hours")
        indexes = guide_indexes(guide)
        hit = match_guide_channel(
            {"name": "Hours HD", "tvg-id": "4717", "tvg-name": ""}, indexes,
            known_ids={"4717", "hours"})
        assert hit is None

    def test_an_unknown_id_still_falls_back_to_the_name(self):
        guide = _guide(hours="Hours")
        indexes = guide_indexes(guide)
        hit = match_guide_channel(
            {"name": "Hours HD", "tvg-id": "4717", "tvg-name": ""}, indexes,
            known_ids={"hours"})
        assert hit and hit["display_name"] == "Hours"
