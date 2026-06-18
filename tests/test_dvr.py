import datetime
import functools
import http.server
import os
import socketserver
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import dvr
import recorder


def _epg_time(dt):
    return dt.astimezone(datetime.timezone.utc).strftime("%Y%m%d%H%M%S")


def _available_ffmpeg():
    path = recorder.get_ffmpeg_path()
    try:
        subprocess.run([path, "-version"], check=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=10)
    except Exception:
        return None
    return path


def _sample_program(start, end):
    return {
        "title": "Scheduled Test Program",
        "channel_name": "DVR Test Channel",
        "channel_id": "dvr-test",
        "start": _epg_time(start),
        "end": _epg_time(end),
    }


def test_build_job_uses_epg_times_and_padding():
    start = datetime.datetime(2026, 6, 18, 20, 0, tzinfo=datetime.timezone.utc)
    end = start + datetime.timedelta(hours=1)
    job = dvr.build_job(
        {"name": "DVR Test Channel", "url": "http://example/stream"},
        _sample_program(start, end),
        "provider_mkv",
        pre_padding_minutes=1,
        post_padding_minutes=3,
        created_at=start.timestamp() - 100,
        job_id="job1",
    )
    assert job["id"] == "job1"
    assert job["display_title"] == "Scheduled Test Program - DVR Test Channel"
    assert job["start_ts"] == start.timestamp() - 60
    assert job["stop_ts"] == end.timestamp() + 180
    assert job["status"] == dvr.STATUS_SCHEDULED


def test_scheduler_tick_starts_and_stops_jobs(tmp_path):
    now = [1000.0]
    events = []
    schedule_path = tmp_path / "schedule.json"

    def on_start(job):
        events.append(("start", job["id"]))
        return 42

    def on_stop(job):
        events.append(("stop", job["id"], job.get("recording_id")))

    scheduler = dvr.DVRScheduler(
        str(schedule_path),
        on_start=on_start,
        on_stop=on_stop,
        clock=lambda: now[0],
        poll_seconds=1,
    )
    start = datetime.datetime.fromtimestamp(1010, datetime.timezone.utc)
    end = datetime.datetime.fromtimestamp(1020, datetime.timezone.utc)
    job = dvr.build_job(
        {"name": "DVR Test Channel", "url": "http://example/stream"},
        _sample_program(start, end),
        "provider_mkv",
        job_id="job1",
    )
    scheduler.add_job(job)

    scheduler.tick()
    assert events == []

    now[0] = 1010
    scheduler.tick()
    assert events == [("start", "job1")]
    active = scheduler.get_job("job1")
    assert active["status"] == dvr.STATUS_RECORDING
    assert active["recording_id"] == 42

    now[0] = 1021 + dvr.DEFAULT_POST_PADDING_MINUTES * 60
    scheduler.tick()
    assert events[-1] == ("stop", "job1", 42)
    assert scheduler.get_job("job1")["status"] == dvr.STATUS_STOPPING


def test_scheduler_persists_jobs_and_resets_interrupted_recording(tmp_path):
    schedule_path = tmp_path / "schedule.json"
    scheduler = dvr.DVRScheduler(str(schedule_path), on_start=lambda job: 1, on_stop=lambda job: None)
    start = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=5)
    end = start + datetime.timedelta(minutes=30)
    job = dvr.build_job(
        {"name": "DVR Test Channel", "url": "http://example/stream"},
        _sample_program(start, end),
        "provider_mkv",
        job_id="job1",
    )
    job["status"] = dvr.STATUS_RECORDING
    job["recording_id"] = 99
    scheduler.add_job(job)

    reloaded = dvr.DVRScheduler(str(schedule_path), on_start=lambda job: 1, on_stop=lambda job: None)
    loaded = reloaded.get_job("job1")
    assert loaded["status"] == dvr.STATUS_SCHEDULED
    assert loaded["recording_id"] is None


def test_scheduled_recording_runs_end_to_end(tmp_path):
    ffmpeg = _available_ffmpeg()
    if not ffmpeg:
        pytest.skip("ffmpeg is not available")

    source = tmp_path / "source.ts"
    subprocess.run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=duration=7:size=96x54:rate=8",
        "-f", "lavfi", "-i", "sine=frequency=800:duration=7",
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", "-f", "mpegts", str(source),
    ], check=True, timeout=30)

    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, _format, *_args):
            pass

    class ReusableServer(socketserver.ThreadingTCPServer):
        allow_reuse_address = True

    handler = functools.partial(QuietHandler, directory=str(tmp_path))
    with ReusableServer(("127.0.0.1", 0), handler) as httpd:
        httpd.daemon_threads = True
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        url = "http://127.0.0.1:{port}/source.ts".format(port=httpd.server_address[1])

        manager = recorder.RecordingManager()
        scheduler = None
        completed = threading.Event()
        result = {}

        def on_finish(rec, rc):
            result["recording"] = rec
            result["returncode"] = rc
            scheduler.mark_finished(
                rec.metadata["dvr_job_id"],
                success=(rc == 0),
                output_path=rec.out_path,
                message="" if rc == 0 else "\n".join(rec.stderr_tail),
            )
            completed.set()

        def on_start(job):
            return manager.start(
                url,
                str(job["display_title"]),
                "provider_mkv",
                {},
                str(tmp_path),
                key="dvr:{id}".format(id=job["id"]),
                metadata={"dvr_job_id": job["id"]},
                on_finish=on_finish,
            )

        def on_stop(job):
            manager.stop(int(job["recording_id"]))

        scheduler = dvr.DVRScheduler(
            str(tmp_path / "schedule.json"),
            on_start=on_start,
            on_stop=on_stop,
            poll_seconds=0.2,
        )
        now = datetime.datetime.now(datetime.timezone.utc)
        start = now + datetime.timedelta(seconds=1)
        end = now + datetime.timedelta(seconds=3)
        job = dvr.build_job(
            {"name": "DVR Test Channel", "url": url},
            _sample_program(start, end),
            "provider_mkv",
            post_padding_minutes=0,
            job_id="job-e2e",
        )
        scheduler.add_job(job)
        scheduler.start()

        try:
            assert completed.wait(20)
            assert result["returncode"] == 0
            output = result["recording"].out_path
            assert os.path.exists(output)
            assert os.path.getsize(output) > 1024
            final_job = scheduler.get_job("job-e2e")
            assert final_job["status"] == dvr.STATUS_COMPLETED
            assert final_job["output_path"] == output
            assert not manager.list_active()
            subprocess.run([
                ffmpeg, "-hide_banner", "-loglevel", "error", "-i", output,
                "-f", "null", "-",
            ], check=True, timeout=30)
        finally:
            scheduler.stop(wait=True)
            manager.stop_all(wait=True)
            httpd.shutdown()
