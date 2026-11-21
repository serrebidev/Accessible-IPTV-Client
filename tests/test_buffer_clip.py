"""Check media continuity and bounded file publication on a real local MPEG-TS stream."""

import errno
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import buffer_clip
from live_buffer import DiskWindow


def spool(directory, contents):
    window = DiskWindow(directory, max_bytes=max(1024 * 1024, 2 * sum(map(len, contents))), seconds=30)
    manifest = ["#EXTM3U", "#EXT-X-TARGETDURATION:2", "#EXT-X-MEDIA-SEQUENCE:0"]
    for i, data in enumerate(contents):
        name = f"seg-{i:09}.ts"
        window.begin(name)
        for j in range(0, len(data), 65536):
            window.append(data[j : j + 65536])
        window.finish()
        manifest.extend(["#EXTINF:2,", name])
    window.publish(("\n".join(manifest) + "\n").encode())
    return window


def test_cancel_expiration_and_existing_file_do_not_publish_partial_output(tmp_path):
    window = spool(tmp_path / "cache", [b"a" * 188, b"b" * 188])
    rows = buffer_clip.select_segments(window.snapshot(), 1)
    assert len(rows) == 1 and rows[0].sequence == 1
    target = tmp_path / "clip.ts"
    with pytest.raises(InterruptedError):
        buffer_clip.save(window, rows, target, "unused", 0, lambda: True)
    assert not target.exists()
    target.write_bytes(b"original")
    with pytest.raises(FileExistsError):
        buffer_clip.save(window, rows, target, "unused", 0)
    assert target.read_bytes() == b"original"
    target.unlink()
    window._remove(rows[0].name)
    with pytest.raises(ValueError):
        buffer_clip.save(window, rows, target, "unused", 0)
    assert not target.exists() and not list(tmp_path.glob(".iptv-clip-*"))


def test_slow_fallback_copy_allows_quota_eviction_and_cancellation(tmp_path, monkeypatch):
    from contextlib import contextmanager

    window = spool(tmp_path / "cache", [b"a" * 65536, b"b" * 65536])
    window.max_bytes = window.used
    rows = window.snapshot()
    opened, resume, canceled = (threading.Event() for _ in range(3))
    target = tmp_path / "clip.ts"
    original = buffer_clip._open_segment

    @contextmanager
    def slow(path):
        with original(path) as stream:
            opened.set()
            assert resume.wait(5)
            yield stream

    def no_links(*args):
        raise OSError(errno.EOPNOTSUPP, "no hard links")

    monkeypatch.setattr(buffer_clip, "_open_segment", slow)
    monkeypatch.setattr(buffer_clip.os, "link", no_links)

    def ingest():
        window.begin("seg-000000002.ts")
        window.append(b"c" * 65536)
        window.finish()

    with ThreadPoolExecutor(max_workers=2) as workers:
        task = workers.submit(buffer_clip.save, window, rows, target, "unused", 0, canceled.is_set)
        try:
            assert opened.wait(5)
            workers.submit(ingest).result(timeout=2)
            assert rows[0].name not in window.files
        finally:
            canceled.set()
            resume.set()
        with pytest.raises(InterruptedError):
            task.result(timeout=5)
    assert not target.exists() and not list(tmp_path.glob("iptv-clip-*"))


def test_quota_failure_reports_full_disk_before_publishing(tmp_path, monkeypatch):
    from types import SimpleNamespace

    window = spool(tmp_path / "cache", [b"x" * 188])
    monkeypatch.setattr(shutil, "disk_usage", lambda _: SimpleNamespace(free=1))
    target = tmp_path / "clip.ts"
    with pytest.raises(OSError):
        buffer_clip.save(window, window.snapshot(), target, "unused", 0)
    assert not target.exists() and len(window.snapshot()) == 1


@pytest.mark.parametrize("links", [True, False])
def test_export_decodes_the_same_audio_while_buffer_eviction_continues(tmp_path, monkeypatch, links):
    from recorder import get_ffmpeg_path

    for ffmpeg in dict.fromkeys((get_ffmpeg_path(), shutil.which("ffmpeg"))):
        if not ffmpeg:
            continue
        try:
            if subprocess.run([ffmpeg, "-version"], capture_output=True, timeout=10).returncode == 0:
                break
        except (OSError, subprocess.TimeoutExpired):
            continue
    else:
        pytest.skip("native ffmpeg unavailable")

    def run(*args):
        return subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", *map(str, args)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=25,
        ).stdout

    run(
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=377:sample_rate=48000:duration=6",
        "-c:a",
        "mp2",
        "-f",
        "segment",
        "-segment_time",
        "2",
        "-segment_format",
        "mpegts",
        tmp_path / "in%03d.ts",
    )
    contents = [p.read_bytes() for p in sorted(tmp_path.glob("in*.ts"))]
    window = spool(tmp_path / "cache", contents)
    selected = buffer_clip.select_segments(window.snapshot(), 3)
    assert len(selected) == 2
    reference = tmp_path / "reference.ts"
    reference.write_bytes(b"".join(contents[-2:]))
    if not links:
        original = buffer_clip.os.link

        def no_cache_link(a, b):
            if Path(a).parent == window.directory:
                raise OSError(errno.EOPNOTSUPP, "no hard links")
            return original(a, b)

        monkeypatch.setattr(buffer_clip.os, "link", no_cache_link)
    staged, proceed = threading.Event(), threading.Event()

    def paused():
        staged.set()
        assert proceed.wait(10)

    target = tmp_path / "export.ts"
    with ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(buffer_clip.save, window, selected, target, ffmpeg, 0, on_staged=paused)
        try:
            assert staged.wait(10)
            assert not target.exists()
            for row in selected:
                window._remove(row.name)
            window.begin("seg-000000020.ts")
            window.append(contents[-1][:188])
            window.finish()
        finally:
            proceed.set()
        task.result(timeout=20)

    def audio(path):
        return run("-i", path, "-map", "0:a:0", "-f", "s16le", "-")

    assert audio(target) == audio(reference) and len(audio(target)) > 10000
    assert not list(tmp_path.glob(".iptv-clip-*"))
