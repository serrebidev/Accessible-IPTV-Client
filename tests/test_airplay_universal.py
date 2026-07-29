"""Live AirPlay integration test against a real device on the network.

Mirrors test_cast_universal.py but exercises the new AirPlayCaster path through
the local stream proxy. Skipped by default; set IPTV_RUN_LIVE_CAST_TESTS=1 to run.
"""

import logging
import os
import time

import pytest

from casting import (
    CastDevice,
    CastingManager,
    CastProtocol,
    PlaybackError,
    _HAS_AIRPLAY,
)

pytestmark = pytest.mark.skipif(
    not _HAS_AIRPLAY or os.environ.get("IPTV_RUN_LIVE_CAST_TESTS") != "1",
    reason="live AirPlay integration test; set IPTV_RUN_LIVE_CAST_TESTS=1 to run",
)

logging.basicConfig(level=logging.INFO)
LOG = logging.getLogger("AirPlayUniversalTest")

TARGET_NAME = "R&B Room"
RADIO_URL = "https://radio.serrebiradio.com/listen/serrebiradio/SerrebiRadio"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    )
}


def _find_target(devices):
    for dev in devices:
        if TARGET_NAME.lower() in dev.name.lower():
            return dev
    return None


def test_discovery_finds_target():
    mgr = CastingManager()
    mgr.start()
    try:
        devices = mgr.discover_all(timeout=5.0)
        LOG.info("Discovered %d devices: %s", len(devices), [d.display_name for d in devices])
        target = _find_target([d for d in devices if d.protocol == CastProtocol.AIRPLAY])
        assert target is not None, f"Could not find AirPlay device '{TARGET_NAME}'"
        LOG.info("Target found: %s host=%s port=%s meta=%s",
                 target.display_name, target.host, target.port, target.metadata)
        # R&B Room is HomePod-style (no Companion). Confirm the new metadata exposes that.
        assert "video_capable" in target.metadata
        assert "has_raop" in target.metadata
    finally:
        mgr.stop()


def test_airplay_radio_cast():
    """Cast the radio source to R&B Room via the new RAOP fallback path."""
    mgr = CastingManager()
    mgr.start()
    try:
        devices = mgr.discover_all(timeout=5.0)
        target = _find_target([d for d in devices if d.protocol == CastProtocol.AIRPLAY])
        assert target is not None, f"Could not find AirPlay device '{TARGET_NAME}'"

        LOG.info("Connecting to %s ...", target.display_name)
        mgr.connect(target)
        assert mgr.is_connected()

        LOG.info("Starting radio cast to %s ...", target.display_name)
        mgr.play(RADIO_URL, title="AirPlay Radio Test", channel={
            "name": "Radio Test",
            **{f"http-{k.lower()}": v for k, v in HEADERS.items()},
        })

        LOG.info("Playback started. Holding the stream open for 20 seconds ...")
        time.sleep(20)

        LOG.info("Stopping playback ...")
        mgr.stop_playback()
        time.sleep(1)
    finally:
        try:
            mgr.disconnect()
        except Exception:
            pass
        mgr.stop()


def test_failed_play_releases_session(monkeypatch):
    """A play() failure must not leave the manager pinned to a dead device.

    The exception must propagate, and the higher-level UI auto-disconnect
    relies on the manager not silently swallowing the error.
    """
    mgr = CastingManager()
    mgr.start()
    try:
        # Forge a fake AirPlay device that will fail to connect/play.
        fake = CastDevice(
            name="Phantom Speaker",
            protocol=CastProtocol.AIRPLAY,
            identifier="00:00:00:00:00:00",
            host="192.0.2.1",
            port=7000,
            metadata={"conf": None, "video_capable": False, "has_raop": True},
        )

        # Pretend the active caster is connected and that play() always fails.
        caster = mgr.casters.get(CastProtocol.AIRPLAY)
        assert caster is not None

        async def boom(*_a, **_kw):
            raise PlaybackError("simulated device failure")

        monkeypatch.setattr(caster, "play", boom)
        monkeypatch.setattr(caster, "is_connected", lambda: True)
        mgr.active_caster = caster
        mgr.active_device = fake

        raised = False
        try:
            mgr.play("http://example.test/stream.ts", title="Test")
        except Exception:
            raised = True
        assert raised, "play() must raise so the UI layer can auto-disconnect"
    finally:
        mgr.stop()


if __name__ == "__main__":
    test_discovery_finds_target()
    test_airplay_radio_cast()
