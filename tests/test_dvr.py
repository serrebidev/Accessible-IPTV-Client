import datetime
import http.server
import json
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


def test_daily_recording_schedules_one_next_occurrence(tmp_path):
    start = datetime.datetime(2026, 9, 24, 20, tzinfo=datetime.timezone.utc)
    end = start + datetime.timedelta(hours=1)
    now = [start.timestamp()]
    scheduler = dvr.DVRScheduler(str(tmp_path / "schedule.json"),
                                 on_start=lambda _job: 42, on_stop=lambda _job: None,
                                 clock=lambda: now[0])
    scheduler.add_job(dvr.build_job({"name": "News"}, _sample_program(start, end),
                                    "provider_mkv", job_id="daily", repeat="daily"))
    scheduler.tick()
    scheduler.mark_finished("daily", success=True)
    next_jobs = scheduler.list_jobs(include_done=False)
    assert len(next_jobs) == 1
    assert next_jobs[0]["repeat"] == "daily"
    assert next_jobs[0]["start_ts"] > start.timestamp()
    scheduler.mark_finished("daily", success=True)
    assert len(scheduler.list_jobs(include_done=False)) == 1


def test_canceling_series_rule_cancels_future_episodes(tmp_path):
    scheduler = dvr.DVRScheduler(str(tmp_path / "schedule.json"),
                                 on_start=lambda _job: None, on_stop=lambda _job: None)
    scheduler.add_job({"id": "series", "repeat": "series", "status": dvr.STATUS_COMPLETED})
    scheduler.add_job({"id": "episode", "series_source": "series",
                       "status": dvr.STATUS_SCHEDULED})
    assert scheduler.cancel_job("series")
    assert scheduler.get_job("episode")["status"] == dvr.STATUS_CANCELED


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


def test_a_schedule_file_with_a_bad_timestamp_does_not_break_startup(tmp_path):
    """The schedule file can be hand-edited or left half-written.

    One bad value must not take the scheduler - or the startup that loads
    it - down with it: the timestamp was read outside any try, so a
    non-numeric stop_ts raised out of the constructor.
    """
    schedule_path = tmp_path / "schedule.json"
    schedule_path.write_text(json.dumps({"jobs": [
        {"id": "job1", "status": dvr.STATUS_RECORDING, "start_ts": "later",
         "stop_ts": "soon", "recording_id": 7},
    ]}), encoding="utf-8")

    scheduler = dvr.DVRScheduler(str(schedule_path), on_start=lambda job: 1, on_stop=lambda job: None)

    job = scheduler.get_job("job1")
    assert job is not None
    assert job["status"] == dvr.STATUS_SCHEDULED
    # The tick must survive it too.
    scheduler.tick()


def test_scheduler_fails_interrupted_recording_whose_window_closed(tmp_path):
    """A restart after the stop time cannot resume, so the job must not re-arm."""
    schedule_path = tmp_path / "schedule.json"
    scheduler = dvr.DVRScheduler(str(schedule_path), on_start=lambda job: 1, on_stop=lambda job: None)
    start = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2)
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
    assert loaded["status"] == dvr.STATUS_FAILED
    assert loaded["recording_id"] is None
    assert loaded["message"]


def test_scheduled_recording_runs_end_to_end(tmp_path):
    ffmpeg = _available_ffmpeg()
    if not ffmpeg:
        pytest.skip("ffmpeg is not available")

    source = tmp_path / "source.ts"
    subprocess.run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=duration=3:size=96x54:rate=8",
        "-f", "lavfi", "-i", "sine=frequency=800:duration=3",
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", "-f", "mpegts", str(source),
    ], check=True, timeout=30)

    class LiveStreamHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, _format, *_args):
            pass

        def do_GET(self):
            if self.path != "/source.ts":
                self.send_error(404)
                return

            self.send_response(200)
            self.send_header("Content-Type", "video/MP2T")
            self.end_headers()
            bytes_sent = 0
            try:
                while True:
                    with open(source, "rb") as handle:
                        while True:
                            chunk = handle.read(2048)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            self.wfile.flush()
                            bytes_sent += len(chunk)
                            if bytes_sent > 32768:
                                time.sleep(0.05)
            except (BrokenPipeError, ConnectionResetError, OSError):
                return

    class ReusableServer(socketserver.ThreadingTCPServer):
        allow_reuse_address = True

    with ReusableServer(("127.0.0.1", 0), LiveStreamHandler) as httpd:
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


def test_stop_timeout_outlasts_the_recorder_finalize_budget():
    """The scheduler must not call a recording failed while ffmpeg is still writing it.

    A provider-quality MP4 finalizes by rewriting the whole file (+faststart), so the
    recorder grants a budget that scales with the capture. If the scheduler gave up
    first it would mark a perfectly good recording "Stop timed out."
    """
    assert dvr.STOP_TIMEOUT_SECONDS > recorder.FINALIZE_GRACE_SECONDS
    # A multi-gigabyte capture, which is exactly the case that used to break.
    assert dvr.STOP_TIMEOUT_SECONDS > 5 * 1024 ** 3 / recorder.FINALIZE_REWRITE_BYTES_PER_SECOND



def _job_scheduler(tmp_path, on_start, on_stop, now):
    scheduler = dvr.DVRScheduler(
        str(tmp_path / "schedule.json"),
        on_start=on_start,
        on_stop=on_stop,
        clock=lambda: now[0],
        poll_seconds=1,
    )
    start = datetime.datetime.fromtimestamp(1010, datetime.timezone.utc)
    end = datetime.datetime.fromtimestamp(1020, datetime.timezone.utc)
    scheduler.add_job(dvr.build_job(
        {"name": "DVR Test Channel", "url": "http://example/stream"},
        _sample_program(start, end), "provider_mkv", job_id="job1"))
    return scheduler


def test_cancel_while_starting_stops_the_recording(tmp_path):
    """on_start probes audio tracks for seconds; a cancel then found nothing to stop.

    The recording started anyway and, being canceled, was never stopped by the
    scheduler: it ran until the user noticed.
    """
    now = [1010.0]
    stopped = []
    holder = {}

    def on_start(job):
        # The user cancels while the start is still in progress.
        holder["scheduler"].cancel_job(job["id"])
        return 7

    def on_stop(job):
        stopped.append(job.get("recording_id"))

    holder["scheduler"] = scheduler = _job_scheduler(tmp_path, on_start, on_stop, now)
    scheduler.tick()

    assert stopped == [7]
    assert scheduler.get_job("job1")["status"] == dvr.STATUS_CANCELED


def test_finished_recording_of_a_canceled_job_stays_canceled(tmp_path):
    now = [1010.0]
    scheduler = _job_scheduler(tmp_path, lambda job: 3, lambda job: None, now)
    scheduler.tick()
    scheduler.cancel_job("job1")

    scheduler.mark_finished("job1", success=True, output_path="C:/rec.mkv", message="")

    job = scheduler.get_job("job1")
    assert job["status"] == dvr.STATUS_CANCELED
    assert job["message"] == "Canceled by user."
    assert job["output_path"] == "C:/rec.mkv"


def test_saves_from_several_threads_do_not_collide(tmp_path):
    """The scheduler thread and the UI both save; a shared .tmp broke os.replace."""
    now = [0.0]
    scheduler = _job_scheduler(tmp_path, lambda job: None, lambda job: None, now)
    errors = []

    def hammer():
        try:
            for _ in range(40):
                scheduler.save()
        except Exception as err:  # pragma: no cover - the failure being tested
            errors.append(err)

    threads = [threading.Thread(target=hammer) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    reloaded = dvr.DVRScheduler(str(tmp_path / "schedule.json"),
                                on_start=lambda job: None, on_stop=lambda job: None)
    assert reloaded.get_job("job1") is not None


def test_stopping_a_scheduled_recording_falls_back_to_the_key():
    """A recording id that no longer resolves must still stop the capture.

    The capture is already gone from the recorder, so stopping by id does
    nothing; without the fallback the job keeps recording past its scheduled
    end and is reported as a stop timeout.
    """
    import main as appmod

    stopped_ids = []
    stopped_keys = []

    class FakeRecorder:
        def stop(self, rec_id, **_kwargs):
            stopped_ids.append(rec_id)
            return False

        def stop_key(self, key, **_kwargs):
            stopped_keys.append(key)
            return 0

    client = appmod.IPTVClient.__new__(appmod.IPTVClient)
    client.recorder = FakeRecorder()

    appmod.IPTVClient._stop_scheduled_recording(client, {"id": 42, "recording_id": 7})

    assert stopped_ids == [7]
    assert stopped_keys == ["dvr:42"]


def test_stopping_a_scheduled_recording_stops_by_id_when_it_resolves():
    import main as appmod

    stopped_ids = []
    stopped_keys = []

    class FakeRecorder:
        def stop(self, rec_id, **_kwargs):
            stopped_ids.append(rec_id)
            return True

        def stop_key(self, key, **_kwargs):
            stopped_keys.append(key)
            return 0

    client = appmod.IPTVClient.__new__(appmod.IPTVClient)
    client.recorder = FakeRecorder()

    appmod.IPTVClient._stop_scheduled_recording(client, {"id": 42, "recording_id": 7})

    assert stopped_ids == [7]
    assert stopped_keys == []


def test_the_series_scan_does_not_block_the_scheduler(tmp_path):
    """The hourly series scan matches every rule against the guide.

    It used to run inside the scheduler tick, so the scheduler could not tick
    while it ran: a recording that came due in the meantime started late, and
    one whose window passed was marked as missed and never recorded.
    """
    import threading

    now = [5000.0]
    events = []
    release = threading.Event()
    scan_started = threading.Event()

    def on_start(job):
        events.append("start")
        return 42

    def on_stop(job):
        pass

    def on_series():
        scan_started.set()
        release.wait(10)

    scheduler = dvr.DVRScheduler(
        str(tmp_path / "schedule.json"),
        on_start=on_start,
        on_stop=on_stop,
        on_series=on_series,
        clock=lambda: now[0],
        poll_seconds=0.2,
    )
    start = datetime.datetime.fromtimestamp(5010, datetime.timezone.utc)
    end = datetime.datetime.fromtimestamp(5030, datetime.timezone.utc)
    job = dvr.build_job(
        {"name": "DVR Test Channel", "url": "http://example/stream"},
        _sample_program(start, end),
        "provider_mkv",
        job_id="job1",
    )
    scheduler.add_job(job)

    def move_the_clock():
        # The job comes due while the scan is still running.
        scan_started.wait(5)
        now[0] = 5015.0

    mover = threading.Thread(target=move_the_clock, daemon=True)
    mover.start()

    scheduler.start()
    try:
        # The scan runs for as long as the test holds it.
        assert scan_started.wait(5), "the series scan never started"
        # The scheduler keeps ticking while the scan is still running.
        deadline = time.time() + 5
        while not events and time.time() < deadline:
            time.sleep(0.05)
        assert events == ["start"], "the scheduler could not tick while the series scan ran"
    finally:
        release.set()
        scheduler.stop()
