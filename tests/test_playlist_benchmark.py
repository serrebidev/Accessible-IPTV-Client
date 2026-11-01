from __future__ import annotations

import json
from dataclasses import replace

import pytest

from tools.playlist_benchmark import (
    DEFAULT_BATCH_SIZE,
    BenchmarkResult,
    benchmark,
    build_playlist_text,
    group_channels,
    performance_budget_failures,
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

    batches = prepare_publication(channels, 8)

    assert [len(batch) for batch in batches] == [8, 8, 1]
    assert prepare_publication([], DEFAULT_BATCH_SIZE) == []


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
    assert result.deserialization_seconds >= 0
    assert result.publication_seconds >= 0
    serialized = json.loads(json.dumps(result.as_dict()))
    assert serialized["channels"] == 25
    assert serialized["index_seconds"] >= 0
    assert serialized["indexed_search_seconds"] >= 0


def test_large_playlist_performance_budget_rejects_regressions():
    baseline = BenchmarkResult(
        channels=50_000,
        text_bytes=1,
        parse_seconds=0,
        grouping_seconds=0,
        serialization_seconds=0,
        deserialization_seconds=0,
        publication_seconds=0,
        publication_batches=1,
        index_seconds=0.9,
        indexed_search_seconds=0.4,
    )
    assert performance_budget_failures(baseline) == []

    regressed = replace(baseline, index_seconds=1.1)
    failures = performance_budget_failures(regressed)
    assert failures and "index_seconds" in failures[0]


def test_grouping_preserves_playlist_order():
    channels = [
        {"name": "first", "group": "A"},
        {"name": "second", "group": "B"},
        {"name": "third", "group": "A"},
    ]

    grouped = group_channels(channels)

    assert [channel["name"] for channel in grouped["A"]] == ["first", "third"]
