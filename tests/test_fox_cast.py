"""Live repro: cast the failing Fox stream to RB Room (Chromecast).

Mirrors what the app does when the user picks the Fox channel and presses cast.
Run with:
    $env:IPTV_RUN_LIVE_CAST_TESTS = "1"
    python test_fox_cast.py
"""

import logging
import os
import time
import urllib.request

import pytest

from casting import CastingManager, CastProtocol, _detect_mime_type
from stream_proxy import get_proxy

pytestmark = pytest.mark.skipif(
    os.environ.get("IPTV_RUN_LIVE_CAST_TESTS") != "1",
    reason="live Fox stream cast regression test; set IPTV_RUN_LIVE_CAST_TESTS=1 to run",
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
LOG = logging.getLogger("FoxCastTest")

TARGET = "RB Room"
SOURCE_URL = "https://gohyperspeed.com/700462241/nb3KdUgE63/200168402"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    )
}


def probe_mime():
    LOG.info("--- MIME detection ---")
    detected = _detect_mime_type(SOURCE_URL)
    LOG.info("detected MIME: %s", detected)
    return detected


def probe_proxy_playlist():
    LOG.info("--- Proxy playlist warm-up ---")
    proxy = get_proxy()
    proxy.start()
    LOG.info("Proxy host=%s port=%s", proxy.host, proxy.port)

    proxied = proxy.get_transcoded_url(SOURCE_URL, HEADERS, transcode_profile="chromecast_h264")
    LOG.info("Proxied HLS URL: %s", proxied)

    # Poll the playlist until ready or we give up
    deadline = time.time() + 25
    last_status = None
    while time.time() < deadline:
        try:
            req = urllib.request.Request(proxied, headers={"User-Agent": "ChromecastTest"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                status = resp.status
                ctype = resp.headers.get("Content-Type")
                body = resp.read()
            text = body.decode("utf-8", errors="replace")
            LOG.info("playlist HTTP %s Content-Type=%s bytes=%d", status, ctype, len(body))
            for line in text.splitlines()[:30]:
                LOG.info("  | %s", line)
            return proxied, text
        except Exception as e:
            if str(e) != last_status:
                LOG.warning("playlist fetch error: %s", e)
                last_status = str(e)
            time.sleep(1.0)
    LOG.error("Playlist never became ready within 25s")
    return proxied, None


def cast_to_rb_room(proxied):
    LOG.info("--- Cast attempt to %s ---", TARGET)
    mgr = CastingManager()
    mgr.start()
    try:
        devices = mgr.discover_all(timeout=5.0)
        target = None
        for d in devices:
            if d.protocol == CastProtocol.CHROMECAST and TARGET.lower() in d.name.lower():
                target = d
                break
        if target is None:
            LOG.error("Chromecast %s not found. Discovered: %s",
                      TARGET, [d.display_name for d in devices])
            return False

        LOG.info("Connecting to %s ...", target.display_name)
        mgr.connect(target)
        assert mgr.is_connected()

        cast = mgr.casters[CastProtocol.CHROMECAST]._cast
        mc = cast.media_controller

        # Use the exact same flow as ChromecastCaster.play() so the failure is the real one.
        channel = {"name": "Fox", "http-user-agent": HEADERS["User-Agent"]}
        LOG.info("Issuing play() ...")
        try:
            mgr.play(SOURCE_URL, title="Fox (Live Test)", channel=channel)
        except Exception as exc:
            LOG.error("play() raised: %s", exc)
            return False

        LOG.info("Watching media controller for 25 seconds ...")
        for i in range(25):
            time.sleep(1)
            mc.update_status()
            status = mc.status
            LOG.info(
                "[t+%02ds] player_state=%s idle_reason=%s content=%s err=%s",
                i + 1,
                status.player_state,
                status.idle_reason,
                status.content_id or status.content_type,
                getattr(status, "last_error", None),
            )
            if status.idle_reason in ("ERROR",):
                LOG.error("Chromecast went to IDLE/ERROR — this is the failure mode")
                return False
        return True
    finally:
        try:
            mgr.disconnect()
        except Exception:
            pass
        mgr.stop()


def main():
    probe_mime()
    proxied, _ = probe_proxy_playlist()
    if not proxied:
        return
    ok = cast_to_rb_room(proxied)
    LOG.info("RESULT: %s", "ok" if ok else "FAILED")


if __name__ == "__main__":
    main()
