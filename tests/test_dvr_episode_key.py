"""Rerun suppression for series recordings (dvr.program_episode_key).

The comfort review's open item: series rules matched titles only, so a
premiere and its two repeats were all recorded. Identity order is
episode number, then sub-title, then a description fingerprint; a
programme with none of them is never suppressed.
"""
import dvr


def test_xmltv_ns_is_zero_based_and_normalized():
    assert dvr.program_episode_key({"episode": "0.4."}) == "ep:1x5"
    assert dvr.program_episode_key({"episode": "2.0."}) == "ep:3x1"
    # The same episode in the other common spelling keys identically.
    assert dvr.program_episode_key({"episode": "S01E05"}) == \
        dvr.program_episode_key({"episode": "0.4."})


def test_onscreen_episode_text_is_compared_loosely():
    assert dvr.program_episode_key({"episode": "s2 e3"}) == \
        dvr.program_episode_key({"episode": "S02E03"})


def test_episode_beats_subtitle_and_description():
    program = {"episode": "0.4.", "subtitle": "Other", "description": "Text"}
    assert dvr.program_episode_key(program) == "ep:1x5"


def test_subtitle_fallback_ignores_case_and_spacing():
    a = dvr.program_episode_key({"subtitle": "The  Long Night"})
    b = dvr.program_episode_key({"subtitle": "the long night"})
    assert a == b and a.startswith("sub:")
    assert dvr.program_episode_key({"subtitle": "A Different One"}) != a


def test_description_fingerprint_fallback():
    a = dvr.program_episode_key({"description": "An episode about storms."})
    b = dvr.program_episode_key({"description": "  An episode about storms. "})
    assert a == b and a.startswith("desc:")
    assert dvr.program_episode_key({"description": "Another synopsis."}) != a


def test_no_identity_means_no_key():
    assert dvr.program_episode_key({}) is None
    assert dvr.program_episode_key({"title": "News Tonight"}) is None
    assert dvr.program_episode_key({"episode": " ", "subtitle": "", "description": ""}) is None


def _job(job_id, program, **extra):
    job = {"id": job_id, "status": dvr.STATUS_SCHEDULED, "program": program}
    job.update(extra)
    return job


def test_taken_keys_cover_rule_and_its_children_not_canceled():
    premiere = {"episode": "0.0.", "title": "Drama Hour"}
    repeat_child = {"episode": "0.1.", "title": "Drama Hour"}
    canceled = {"episode": "0.2.", "title": "Drama Hour"}
    other_rule = {"episode": "0.3.", "title": "Drama Hour"}
    jobs = [
        _job("rule", premiere, repeat="series"),
        _job("child", repeat_child, series_source="rule"),
        _job("gone", canceled, series_source="rule", status=dvr.STATUS_CANCELED),
        _job("done", {"episode": "0.4."}, series_source="rule",
             status=dvr.STATUS_COMPLETED),
        _job("stray", other_rule, series_source="another-rule"),
    ]
    taken = dvr.taken_episode_keys(jobs, "rule")
    assert taken == {"ep:1x1", "ep:1x2", "ep:1x5"}


def test_first_airing_wins_over_the_horizon():
    """The scan's chronological walk: keep the first of each episode."""
    schedule = [
        {"title": "Drama Hour", "episode": "0.4.", "start": "20270101190000"},
        {"title": "Drama Hour", "episode": "0.5.", "start": "20270101210000"},
        {"title": "Drama Hour", "episode": "0.4.", "start": "20270102030000"},
        {"title": "Drama Hour", "episode": "", "start": "20270102190000"},
        {"title": "Drama Hour", "episode": "0.4.", "start": "20270103190000"},
    ]
    taken = set()
    kept = []
    for program in schedule:
        key = dvr.program_episode_key(program)
        if key is not None and key in taken:
            continue
        kept.append(program["start"])
        if key is not None:
            taken.add(key)
    # Premiere kept once, the new episode kept, the unidentified airing
    # kept (no identity, no suppression), both repeats dropped.
    assert kept == ["20270101190000", "20270101210000", "20270102190000"]
