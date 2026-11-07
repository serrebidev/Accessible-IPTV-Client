"""Per-event announcement switches (options.announce_events).

Beside the global announcement level, each event category — playback,
subtitles, guide — can be turned off on its own. Anything missing or
malformed falls back to on: a config problem must never silence the app.
"""
import options


def test_defaults_have_every_category_on():
    cfg = {}
    options.normalize_announce_events(cfg)
    assert cfg["announce_events"] == {
        "playback": True, "subtitles": True, "guide": True}


def test_explicit_off_survives_normalization():
    cfg = {"announce_events": {"subtitles": False}}
    options.normalize_announce_events(cfg)
    assert cfg["announce_events"]["subtitles"] is False
    assert cfg["announce_events"]["playback"] is True
    assert options.announce_event_enabled(cfg, "subtitles") is False
    assert options.announce_event_enabled(cfg, "playback") is True


def test_malformed_values_fall_back_to_on():
    for bad in (None, "subtitles", 3, ["playback"]):
        cfg = {"announce_events": bad}
        options.normalize_announce_events(cfg)
        assert all(cfg["announce_events"].values())
    cfg = {"announce_events": {"guide": 0, "playback": "yes"}}
    options.normalize_announce_events(cfg)
    assert cfg["announce_events"]["guide"] is False
    assert cfg["announce_events"]["playback"] is True


def test_unknown_category_defaults_on_and_is_dropped_from_storage():
    cfg = {"announce_events": {"weather": False}}
    options.normalize_announce_events(cfg)
    assert "weather" not in cfg["announce_events"]
    assert options.announce_event_enabled(cfg, "weather") is True
    assert options.announce_event_enabled({}, "playback") is True
