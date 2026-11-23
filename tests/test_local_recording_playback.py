"""Exercise real Matroska media, cancellable workers and accessible playback actions."""

import os
from pathlib import Path
from queue import Queue
import shutil
import subprocess
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import wx

import internal_player
import recording_library
import recording_media
import recording_queue
import subtitle_cues


@pytest.fixture(scope="module")
def native_ffmpeg():
    import recorder

    # Source checkouts may contain an LFS pointer instead of the Windows binary.
    for candidate in dict.fromkeys((recorder.get_ffmpeg_path(), shutil.which("ffmpeg"))):
        if not candidate:
            continue
        try:
            probe = subprocess.run([candidate, "-version"], capture_output=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if probe.returncode == 0 and b"ffmpeg version" in probe.stdout:
            with pytest.MonkeyPatch.context() as patch:
                patch.setattr(recorder, "get_ffmpeg_path", lambda: candidate)
                yield candidate
            return
    pytest.skip("No executable FFmpeg installation")


@pytest.fixture(scope="module")
def native_vlc():
    vlc = internal_player.vlc
    if vlc is None:
        pytest.skip("No native libVLC installation")
    try:
        version = vlc.libvlc_get_version()
    except (AttributeError, OSError, NameError):
        pytest.skip("No native libVLC installation")
    assert version
    return vlc


@pytest.fixture(scope="module")
def media(tmp_path_factory, native_ffmpeg):
    ffmpeg = native_ffmpeg
    root = tmp_path_factory.mktemp("chaptered")
    (root / "hu.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nSzól a zene.\n", encoding="utf-8")
    (root / "en.srt").write_text("1\n00:00:02,000 --> 00:00:03,000\nSecond track.\n", encoding="utf-8")
    (root / "meta").write_text(
        ";FFMETADATA1\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=2500\ntitle=Nyitány\n"
        "[CHAPTER]\nTIMEBASE=1/1000\nSTART=2500\nEND=5000\ntitle=Finálé\n",
        encoding="utf-8",
    )
    file = root / "Concert 01.mkv"
    subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=duration=5",
            "-i",
            str(root / "hu.srt"),
            "-i",
            str(root / "en.srt"),
            "-f",
            "ffmetadata",
            "-i",
            str(root / "meta"),
            "-map",
            "0:a",
            "-map",
            "1:s",
            "-map",
            "2:s",
            "-map_chapters",
            "3",
            "-metadata:s:s:0",
            "language=hun",
            "-metadata:s:s:0",
            "title=Magyar",
            "-metadata:s:s:1",
            "language=eng",
            "-c:a",
            "pcm_s16le",
            "-c:s",
            "srt",
            str(file),
        ],
        check=True,
        timeout=20,
    )
    return file


def test_embedded_tracks_use_exact_stream_language_and_time(media):
    tracks = recording_media.subtitle_tracks(media, lambda: False)
    assert [r["language"] for r in tracks] == ["hun", "eng"]
    assert tracks[0]["title"] == "Magyar"
    assert [recording_media.embedded_cues(media, t, lambda: False) for t in tracks] == [
        [subtitle_cues.Cue(1000, 2000, "Szól a zene.")],
        [subtitle_cues.Cue(2000, 3000, "Second track.")],
    ]
    assert recording_media.subtitle_tracks(media, lambda: True) == []
    with pytest.raises(ValueError):
        recording_media.embedded_cues(media, dict(tracks[0], readable=False), lambda: False)
    with pytest.raises(ValueError):
        recording_media.subtitle_tracks(media.with_suffix(".mp4"), lambda: False)


def test_replaced_recording_does_not_supply_another_files_subtitles(media, tmp_path):
    file = Path(shutil.copy(media, tmp_path / "Temporary.mkv"))
    with pytest.raises(ValueError):
        recording_media.subtitle_tracks(file, lambda: False, "local-recording:1:2")
    track = recording_media.subtitle_tracks(file, lambda: False)[0]
    with file.open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ValueError):
        recording_media.embedded_cues(file, track, lambda: False)


def test_real_vlc_chapter_titles_offsets_and_seek(media, native_vlc):
    vlc = native_vlc

    instance = vlc.Instance("--intf=dummy", "--aout=dummy", "--vout=dummy", "--no-video-title-show")
    if instance is None:
        pytest.skip("libVLC not installed")
    player = instance.media_player_new()
    source = instance.media_new_path(str(media))
    try:
        player.set_media(source)
        assert player.play() != -1
        deadline = time.monotonic() + 5
        while (player.get_chapter_count() < 2 or not player.is_seekable()) and time.monotonic() < deadline:
            time.sleep(0.02)
        rows = recording_media.chapters(player)
        assert rows == [(0, 0, "Nyitány"), (1, 2500, "Finálé")]
        player.set_chapter(1)
        deadline = time.monotonic() + 2
        while player.get_chapter() != 1 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert player.get_chapter() == 1
        assert recording_media.chapters(player) == rows  # native descriptors were copied before release
    finally:
        player.stop()
        source.release()
        player.release()
        instance.release()


def test_player_embedded_choice_publishes_prepared_text_and_cancels_on_stop(media, monkeypatch):
    app = wx.GetApp() or wx.App(False)
    host = wx.Frame(None)
    frame = SimpleNamespace(
        _episode_channel={"local-recording": str(media)},
        _manual_stop=False,
        _vlc_generation=3,
        _subtitle_generation=2,
        _destroyed=False,
        _subtitle_cues=[],
        _navigation_message=Mock(),
        _cue_timer=Mock(),
        subtitle_label=Mock(),
    )
    frame._set_subtitle_cues = lambda *args: internal_player.InternalPlayerFrame._set_subtitle_cues(frame, *args)
    choice = Mock()
    choice.GetSelection.return_value = 1
    monkeypatch.setattr(wx, "SingleChoiceDialog", lambda *a: choice)
    monkeypatch.setattr(internal_player, "show_modal", lambda dlg: wx.ID_OK)
    try:
        internal_player.InternalPlayerFrame._read_embedded_track(frame)
        deadline = time.monotonic() + 8
        while not frame._subtitle_cues and time.monotonic() < deadline:
            app.Yield()
            time.sleep(0.01)
        assert frame._embedded_speech and frame._subtitle_cues == (subtitle_cues.Cue(2000, 3000, "Second track."),)
        assert frame._subtitle_file_source.cues == tuple(frame._subtitle_cues)
        internal_player.InternalPlayerFrame._read_embedded_track(frame)
        frame._set_subtitle_cues([])
        app.Yield()
        assert not frame._embedded_speech and frame._subtitle_cues == [] and frame._embedded_worker is None
    finally:
        host.Destroy()


def test_cancelling_worker_kills_a_running_process():
    import sys

    canceled = threading.Event()
    threading.Timer(0.15, canceled.set).start()
    start = time.monotonic()
    out = recording_media._read_process(
        [sys.executable, "-c", "import time; time.sleep(30)"], canceled.is_set, listing=False
    )
    assert out == b"" and time.monotonic() - start < 5


def session(files):
    tasks = Queue()
    owner = SimpleNamespace(
        recorder=SimpleNamespace(list_active=lambda: []),
        _launch_stream=Mock(return_value=True),
        _show_or_queue_message_box=Mock(),
    )
    queue = recording_queue.RecordingQueue(owner, lambda fn, *args: tasks.put((fn, args)))
    owner._recording_queue = queue
    for file in files:
        stamp = file.stat()
        queue.add(
            [
                dict(
                    directory=str(file.parent),
                    path=str(file),
                    title=file.stem,
                    modified_ns=stamp.st_mtime_ns,
                    size=stamp.st_size,
                )
            ]
        )

    def deliver():
        fn, args = tasks.get(timeout=3)
        fn(*args)

    return owner, queue, deliver


def test_queue_opens_only_the_next_file_honours_order_manual_stop_and_stale_ends(tmp_path, monkeypatch):
    files = [tmp_path / f"{i}.mkv" for i in (1, 2, 3)]
    for file in files:
        file.write_bytes(b"media")
    owner, queue, deliver = session(files)
    checked = []
    original = recording_library.playback_channel

    def verify(folder, row, active):
        checked.append((row["title"], threading.get_ident()))
        return original(folder, row, active)

    monkeypatch.setattr(recording_library, "playback_channel", verify)
    queue.add([queue.pending[0]])  # duplicate selection
    assert len(queue.pending) == 3 and not checked
    queue.edit(1, -1)
    queue.start()
    deliver()
    assert [s for s, thread in checked] == ["2"] and checked[0][1] != threading.get_ident()
    assert [r["title"] for r in queue.pending] == ["1", "3"]
    frame = SimpleNamespace(_vlc_generation=4, _manual_stop=False, _destroyed=False)
    first = queue.ticket
    queue.ended(frame, 3, first)
    assert owner._launch_stream.call_count == 1
    queue.ended(frame, 4, first)
    deliver()
    assert [s for s, thread in checked] == ["2", "1"]
    assert not owner._launch_stream.call_args.kwargs["focus_player"]
    queue.stop()
    queue.ended(frame, 4, first)
    assert owner._launch_stream.call_count == 2 and len(queue.pending) == 1
    queue.start()
    deliver()
    assert owner._launch_stream.call_args.kwargs["force_internal"]
    queue.ended(frame, 4, queue.ticket)
    assert not queue.playing and not queue.pending


def test_edit_during_handoff_validates_only_the_new_first_item_and_keeps_focus(tmp_path):
    files = [tmp_path / f"{n}.mkv" for n in range(4)]
    for file in files:
        file.write_bytes(b"recording")
    owner, queue, deliver = session(files)
    queue.start()
    initial = queue.ticket
    queue.edit(2, 1)
    assert queue.ticket is initial
    queue.edit(0)
    assert queue.ticket is not initial
    for _ in range(2):
        deliver()
        if owner._launch_stream.called:
            break
    owner._launch_stream.assert_called_once()
    call = owner._launch_stream.call_args
    assert call.args[1] == "1" and not call.kwargs["focus_player"]
    assert [row["title"] for row in queue.pending] == ["3", "2"]
    queue.stop()


def test_changed_deleted_and_active_files_do_not_start_the_wrong_recording(tmp_path):
    file = tmp_path / "Original.mkv"
    file.write_bytes(b"original")
    owner, queue, deliver = session([file])
    for action in ("active", "changed", "deleted"):
        owner.recorder.list_active = lambda: [SimpleNamespace(written_path=str(file))] if action == "active" else []
        if action == "changed":
            file.write_bytes(b"changed version")
        if action == "deleted":
            os.remove(file)
        queue.start()
        deliver()
        owner._launch_stream.assert_not_called()
        assert not queue.playing and queue.pending[0]["title"] == "Original"
    assert owner._show_or_queue_message_box.call_count == 3


def test_queue_editor_keyboard_order_and_accessible_positions(tmp_path, monkeypatch):
    import modal_guard

    app = wx.GetApp() or wx.App(False)
    host = wx.Frame(None)
    files = [tmp_path / name for name in ("Koncert.mkv", "Hírek.mkv")]
    for file in files:
        file.touch()
    owner, queue, deliver = session(files)

    def visit(dialog):
        listing = next(c for c in dialog.panel.GetChildren() if isinstance(c, wx.ListBox))
        listing.SetSelection(1)
        down = wx.KeyEvent(wx.wxEVT_KEY_DOWN)
        down.SetKeyCode(wx.WXK_UP)
        down.SetControlDown(True)
        listing.GetEventHandler().ProcessEvent(down)
        assert "Hírek" in listing.GetString(0) and "1" in listing.GetString(0)
        assert listing.GetName()
        return wx.ID_CANCEL

    monkeypatch.setattr(modal_guard, "show_modal", visit)
    try:
        assert not recording_queue.show_editor(host, queue)
        assert [r["title"] for r in queue.pending] == ["Hírek", "Koncert"]
        assert queue.changed is None
    finally:
        host.Destroy()
        app.Yield()


def test_player_advances_queue_only_on_local_end_and_honours_stop(media, native_vlc):
    app = wx.GetApp() or wx.App(False)
    frame = internal_player.InternalPlayerFrame(None)
    queue = SimpleNamespace(ticket=object(), playing=True, ended=Mock(), stop=Mock())
    frame._recording_queue = queue
    frame._recording_queue_ticket = queue.ticket
    try:
        frame.play(media.as_uri(), "Concert", stream_kind="vod", video_visible=False, focus_controls=False)
        deadline = time.monotonic() + 12
        while not queue.ended.called and time.monotonic() < deadline:
            app.Yield()
            time.sleep(0.03)
        queue.ended.assert_called_once_with(frame, frame._vlc_generation, queue.ticket)
        queue.ended.reset_mock()
        frame.play(media.as_uri(), "Concert", stream_kind="vod", video_visible=False, focus_controls=False)
        frame.stop(manual=True)
        app.Yield()
        queue.stop.assert_called()
        queue.ended.assert_not_called()
    finally:
        frame.stop(manual=True)
        frame.Destroy()
        app.Yield()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="uses a local FIFO for a real-time broadcast")
def test_recording_keeps_every_audio_sample_while_reading_subtitles_and_searching(media, tmp_path):
    import playlist_index
    import recorder

    ffmpeg = recorder.get_ffmpeg_path()
    fifo = tmp_path / "local-broadcast.mkv"
    os.mkfifo(fifo)
    manager = recorder.RecordingManager()
    finished = threading.Event()
    result = []

    def done(rec, code):
        result.append(code)
        finished.set()

    rec = manager.start(str(fifo), "Concurrent recording", "provider_mkv", {}, str(tmp_path), on_finish=done)
    producer = subprocess.Popen(
        [
            ffmpeg,
            "-nostdin",
            "-loglevel",
            "error",
            "-y",
            "-re",
            "-i",
            str(media),
            "-map",
            "0",
            "-c",
            "copy",
            "-f",
            "matroska",
            str(fifo),
        ]
    )
    try:
        tracks = recording_media.subtitle_tracks(media, lambda: False)
        assert recording_media.embedded_cues(media, tracks[0], lambda: False)
        channels = [{"name": "Concert " + str(n)} for n in range(25000)]
        index = playlist_index.PlaylistIndex(channels, {})
        assert len(index.search(channels, "concert")) == len(channels)
        assert producer.wait(timeout=15) == 0
        assert finished.wait(10) and result == [0]

        def audio_hash(path):
            return subprocess.check_output(
                [
                    ffmpeg,
                    "-nostdin",
                    "-loglevel",
                    "error",
                    "-i",
                    str(path),
                    "-map",
                    "0:a:0",
                    "-c:a",
                    "pcm_s16le",
                    "-f",
                    "hash",
                    "-hash",
                    "sha256",
                    "-",
                ],
                timeout=10,
            )

        assert audio_hash(rec.out_path) == audio_hash(media)
    finally:
        if producer.poll() is None:
            producer.kill()
            producer.wait()
        manager.stop_all(wait=True)
