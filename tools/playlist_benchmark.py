"""Deterministic large-playlist benchmark used to choose publication thresholds.

This module intentionally has no wx dependency and does not alter production
playlist behavior.  It measures the real M3U parser plus the representative
in-memory work performed before rows are published to the virtual list.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List

# When invoked as ``python tools/playlist_benchmark.py``, Python puts the
# tools directory—not the repository root—on sys.path. Keep the benchmark
# directly runnable without requiring PYTHONPATH or package installation.
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from client_m3u import M3uCacheMixin  # noqa: E402


DEFAULT_SIZES = (50_000, 250_000, 500_000)
DEFAULT_BATCH_SIZE = 800


class _ParserHarness(M3uCacheMixin):
    pass


@dataclass(frozen=True)
class BenchmarkResult:
    channels: int
    text_bytes: int
    parse_seconds: float
    grouping_seconds: float
    serialization_seconds: float
    publication_seconds: float
    publication_batches: int

    def as_dict(self) -> Dict[str, object]:
        return {
            "channels": self.channels,
            "text_bytes": self.text_bytes,
            "parse_seconds": round(self.parse_seconds, 6),
            "grouping_seconds": round(self.grouping_seconds, 6),
            "serialization_seconds": round(self.serialization_seconds, 6),
            "publication_seconds": round(self.publication_seconds, 6),
            "publication_batches": self.publication_batches,
        }


def build_playlist_text(channel_count: int) -> str:
    """Build stable synthetic M3U data with realistic groups and attributes."""
    if channel_count < 0:
        raise ValueError("channel_count must be non-negative")
    lines = ["#EXTM3U"]
    for index in range(channel_count):
        lines.append(
            f'#EXTINF:-1 tvg-id="ch{index}.test" '
            f'group-title="Group {index % 1000}",Channel {index:06d}'
        )
        lines.append(f"https://stream.example/{index}.ts")
    return "\n".join(lines) + "\n"


def group_channels(channels: Iterable[Dict[str, str]]) -> Dict[str, List[Dict[str, str]]]:
    """Perform the grouping work used by playlist publication."""
    grouped: Dict[str, List[Dict[str, str]]] = {}
    for channel in channels:
        grouped.setdefault(channel.get("group") or "Uncategorized", []).append(channel)
    return grouped


def prepare_publication(channels: List[Dict[str, str]], batch_size: int) -> int:
    """Count bounded publication batches without creating UI controls."""
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    return (len(channels) + batch_size - 1) // batch_size


def benchmark(channel_count: int, batch_size: int = DEFAULT_BATCH_SIZE) -> BenchmarkResult:
    """Measure one deterministic playlist size through the real parser seam."""
    text = build_playlist_text(channel_count)
    parser = _ParserHarness()

    started = time.perf_counter()
    channels = parser._parse_m3u_return(text)
    parse_seconds = time.perf_counter() - started

    started = time.perf_counter()
    group_channels(channels)
    grouping_seconds = time.perf_counter() - started

    started = time.perf_counter()
    json.dumps({"hash": "benchmark", "channels": channels}, separators=(",", ":"))
    serialization_seconds = time.perf_counter() - started

    started = time.perf_counter()
    publication_batches = prepare_publication(channels, batch_size)
    publication_seconds = time.perf_counter() - started

    return BenchmarkResult(
        channels=channel_count,
        text_bytes=len(text.encode("utf-8")),
        parse_seconds=parse_seconds,
        grouping_seconds=grouping_seconds,
        serialization_seconds=serialization_seconds,
        publication_seconds=publication_seconds,
        publication_batches=publication_batches,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", type=int, default=DEFAULT_SIZES)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    args = parser.parse_args()
    for size in args.sizes:
        print(json.dumps(benchmark(size, args.batch_size).as_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
