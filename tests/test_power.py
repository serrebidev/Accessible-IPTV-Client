"""Tests for the "shut down when recording is finished" decision (power.py).

Powering a machine off is not undoable, so the interesting cases here are all the
ones where it must NOT happen: nothing has recorded yet, a capture is still running,
or a scheduled job is still waiting its turn.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import power  # noqa: E402


class TestShouldShutdown:
    def test_shuts_down_once_everything_has_finished(self):
        assert power.should_shutdown(
            armed=True, recorded_something=True, active_recordings=0, pending_jobs=0) is True

    def test_not_armed(self):
        assert power.should_shutdown(
            armed=False, recorded_something=True, active_recordings=0, pending_jobs=0) is False

    def test_nothing_has_recorded_yet(self):
        # Arming the option on an idle machine must not power it off immediately.
        assert power.should_shutdown(
            armed=True, recorded_something=False, active_recordings=0, pending_jobs=0) is False

    def test_a_recording_is_still_running(self):
        assert power.should_shutdown(
            armed=True, recorded_something=True, active_recordings=1, pending_jobs=0) is False

    def test_a_scheduled_recording_is_still_waiting(self):
        assert power.should_shutdown(
            armed=True, recorded_something=True, active_recordings=0, pending_jobs=1) is False


class TestPendingJobCount:
    def test_counts_only_unfinished_jobs(self):
        jobs = [
            {"status": "scheduled"},
            {"status": "recording"},
            {"status": "stopping"},
            {"status": "completed"},
            {"status": "failed"},
            {"status": "missed"},
            {"status": "canceled"},
        ]
        assert power.pending_job_count(jobs) == 3

    def test_statuses_match_the_dvr_module(self):
        import dvr

        assert power.PENDING_JOB_STATUSES == dvr.ACTIVE_STATUSES

    def test_junk_is_ignored(self):
        assert power.pending_job_count(None) == 0
        assert power.pending_job_count([]) == 0
        assert power.pending_job_count(["not a job", {}, {"status": None}]) == 0


class TestShutdownCommands:
    def test_windows(self):
        assert power.shutdown_commands("Windows") == [["shutdown", "/s", "/t", "0"]]

    def test_windows_does_not_force_apps_closed(self):
        # /f would kill whatever else the user left open without letting it save.
        assert "/f" not in power.shutdown_commands("Windows")[0]

    def test_linux_falls_back_from_systemctl(self):
        cmds = power.shutdown_commands("Linux")
        assert cmds[0][0] == "systemctl"
        assert cmds[-1][:2] == ["shutdown", "-h"]

    def test_macos(self):
        assert power.shutdown_commands("Darwin")[0][0] == "osascript"

    def test_unknown_platform_gets_the_posix_commands(self):
        assert power.shutdown_commands("Plan9") == power.shutdown_commands("Linux")


class TestShutdownComputer:
    def test_returns_the_command_that_worked(self):
        calls = []
        used = power.shutdown_computer(system="Windows", runner=calls.append)
        assert calls == [["shutdown", "/s", "/t", "0"]]
        assert used == ["shutdown", "/s", "/t", "0"]

    def test_falls_through_to_the_next_candidate(self):
        calls = []

        def runner(cmd):
            calls.append(cmd)
            if cmd[0] == "systemctl":
                raise RuntimeError("no systemd here")

        used = power.shutdown_computer(system="Linux", runner=runner)
        assert used[0] == "shutdown"
        assert len(calls) == 2

    def test_every_failure_is_reported_to_the_caller(self):
        def runner(cmd):
            raise RuntimeError("access denied")

        with pytest.raises(RuntimeError) as err:
            power.shutdown_computer(system="Windows", runner=runner)
        # The user has to be told why nothing happened.
        assert "access denied" in str(err.value)
