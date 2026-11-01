from __future__ import annotations

import json

import pytest

from tools.playlist_benchmark import (
    DEFAULT_BATCH_SIZE,
    benchmark,
    build_playlist_text,
    group_channels,
    prepare_publication,
)


def test_synthetic_playlist_is_deterministic_and_realistic():
    text = build_playlist_text(3)

    assert text == build_playlist_text(3)
    assert text.count("#EXTINF") == 3
    assert 'group-title="Group 0"' in text
    assert "https://stream.example/2.ts" in text


def test_publication_batches_are_bounded_and_cover_all_channels():
    channels = [{"name": str(index), "group": "Group"} for index in range(17)]

    assert prepare_publication(channels, 8) == 3
    assert prepare_publication([], DEFAULT_BATCH_SIZE) == 0


@pytest.mark.parametrize("bad_batch_size", [0, -1])
def test_publication_rejects_invalid_batch_size(bad_batch_size):
    with pytest.raises(ValueError):
        prepare_publication([], bad_batch_size)


def test_benchmark_reports_separate_measurement_phases():
    result = benchmark(25, batch_size=8)

    assert result.channels == 25
    assert result.text_bytes > 0
    assert result.publication_batches == 4
    assert result.parse_seconds >= 0
    assert result.grouping_seconds >= 0
    assert result.serialization_seconds >= 0
    assert result.publication_seconds >= 0
    assert json.loads(json.dumps(result.as_dict()))["channels"] == 25


def test_grouping_preserves_playlist_order():
    channels = [
        {"name": "first", "group": "A"},
        {"name": "second", "group": "B"},
        {"name": "third", "group": "A"},
    ]

    grouped = group_channels(channels)

    assert [channel["name"] for channel in grouped["A"]] == ["first", "third"]
