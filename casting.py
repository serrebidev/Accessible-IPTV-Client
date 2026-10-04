"""Casting: Chromecast, AirPlay, UPnP/DLNA, Sonos, Roku and Kodi.

The protocol clients and the streaming engine are Caster's (see
tools/sync_caster.py): caster_engine for media probing, the HLS relay that
keeps live IPTV smooth on a receiver, and the replay-dropping TS reader;
caster_devices and caster_extras for discovery and each protocol's own
control calls. This module is the part Caster keeps inside its wx window: it
decides, per receiver, how a channel gets there, and it is GUI-free so the
IPTV window can drive it from worker threads.

What this adds for an IPTV app:

* Channel HTTP headers. The engine and the receivers fetch URLs with their
  own headers, so a channel that needs a User-Agent or Referer is served
  through the stream proxy's header gateway instead.
* One-stream providers. Probing, codec detection and the relay each open the
  stream; such a provider refuses a request made while it still holds the
  previous one, so for them the steps run one after another with a pause.
* Speakers get sound. A TV channel sent to a Sonos or an audio-only renderer
  goes through the proxy's MP3 path, instead of an MPEG-TS it cannot decode.

All calls block until the receiver is playing or has failed, and raise
CastError with a reason; call them from a worker thread.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
import time
import uuid as uuidlib
from typing import Any, Dict, List, Optional

LOG = logging.getLogger(__name__)

#: How long discovery listens. SSDP and mDNS answer over several seconds; the
#: protocols run in parallel, so this is very nearly the whole cost of a scan.
DISCOVER_SECONDS = 5
#: How long AirPlay may take to begin streaming before play() gives up on it.
AIRPLAY_START_TIMEOUT = 25.0
#: Live Cast recovery: how often to look, and how long a frozen position counts
#: as a stall (Caster's measured values).
WATCHDOG_SECONDS = 5.0
CAST_STALL_TIMEOUT = 20.0
CAST_RECOVERY_INTERVAL = 30.0
#: Cast receiver app id (Default Media Receiver).
CAST_APP_ID = "CC1AD845"
LOAD_TIMEOUT = 12.0
LOAD_POLL = 0.15
#: Idle reasons that describe the END of a previous playback, not a rejection.
STALE_IDLE_REASONS = ("INTERRUPTED", "CANCELLED")
#: Caster's quality preset for the relay: 2 s segments, a 16 s start cushion
#: and 45 s of history, deep enough for IPTV sources that stutter.
RELAY_PRESET = "balanced"


class CastError(Exception):
    """Casting failed; the message says why."""


class DeviceNotFoundError(CastError):
    pass


class ConnectionError(CastError):  # noqa: A001 - kept for existing callers
    pass


class PlaybackError(CastError):
    pass


def _engine():
    """caster_engine, with ffmpeg resolved the way this app bundles it."""
    import caster_engine
    import caster_extras
    from stream_proxy import get_ffmpeg_path

    # Caster looks for ffmpeg beside its own exe; this app ships it in
    # _internal (or relies on the system one on Linux).
    caster_engine._find_ffmpeg = get_ffmpeg_path
    caster_extras._find_ffmpeg = get_ffmpeg_path
    return caster_engine


class CastDevice:
    """One receiver found on the network."""

    def __init__(self, device: Any) -> None:
        self.device = device            # caster_engine.Device

    @property
    def kind(self) -> str:
        return self.device.kind

    @property
    def name(self) -> str:
        return self.device.name

    @property
    def protocol(self) -> str:
        from caster_engine import KIND_LABELS
        return KIND_LABELS.get(self.kind, self.kind)

    @property
    def display_name(self) -> str:
        return self.device.label

    @property
    def identifier(self) -> str:
        return f"{self.kind}:{self.name}"

    @property
    def supports_video(self) -> bool:
        return bool(self.device.supports_video)

    def __repr__(self) -> str:
        return f"CastDevice({self.kind}, {self.name!r})"


class CastingManager:
    """Discovers receivers and plays channels on the one the user picked."""

    def __init__(self) -> None:
        self.active_device: Optional[CastDevice] = None
        self._loop_thread = None
        self._lock = threading.RLock()
        # Every play and stop bumps this. Work belonging to an older
        # generation - a probe still running when the user switched channel -
        # sees the change and backs out instead of loading a stale stream.
        self._generation = 0
        self._cast = None
        self._cast_zc = None
        self._relays: list = []
        self._live_load = None          # (generation, cast, url, mime, stream_type)
        self._cast_progress = None
        self._cast_retry_at = 0.0
        self._recovering = False
        self._air_future = None
        self._air_shutdown = None
        self._air_proc = None
        self._running = False
        self._watchdog: Optional[threading.Thread] = None
        self._watchdog_stop = threading.Event()

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        if self._running:
            return
        engine = _engine()
        self._loop_thread = engine.LoopThread()
        self._loop_thread.start()
        self._loop_thread.ready.wait(5)
        self._running = True
        self._watchdog_stop.clear()
        self._watchdog = threading.Thread(target=self._watchdog_loop, daemon=True,
                                          name="cast-watchdog")
        self._watchdog.start()

    def stop(self) -> None:
        """Stop casting and shut the manager down (app exit)."""
        if not self._running:
            return
        self._running = False
        self._watchdog_stop.set()
        try:
            self.stop_playback()
        except Exception:
            LOG.debug("CastingManager.stop: ignored exception", exc_info=True)
        future = self._air_future
        if future is not None:
            try:
                # Let the RAOP session close properly on the receiver.
                future.result(timeout=5)
            except Exception:
                LOG.debug("CastingManager.stop: AirPlay runner", exc_info=True)
        zc, self._cast_zc = self._cast_zc, None
        if zc is not None:
            try:
                zc.close()
            except Exception:
                LOG.debug("CastingManager.stop: ignored exception", exc_info=True)
        loop_thread = self._loop_thread
        if loop_thread is not None:
            loop_thread.loop.call_soon_threadsafe(loop_thread.loop.stop)
            loop_thread.join(timeout=2)

    def _require_running(self) -> None:
        if not self._running:
            raise RuntimeError("CastingManager is not running. Call start() first.")

    # ------------------------------------------------------------------ #
    # Discovery
    # ------------------------------------------------------------------ #
    def discover_all(self, timeout: float = DISCOVER_SECONDS) -> List[CastDevice]:
        """Every receiver on the network, across all protocols, in parallel."""
        self._require_running()
        _engine()
        timeout = max(1, int(round(timeout)))
        try:
            import zeroconf
            zc = zeroconf.Zeroconf()
        except Exception:
            LOG.info("Casting: mDNS unavailable; Chromecast and Kodi will not be found",
                     exc_info=True)
            zc = None
        scans = [
            ("chromecast", lambda: self._scan_chromecast(zc, timeout)),
            ("airplay", lambda: self._scan_airplay(timeout)),
            ("upnp", lambda: self._scan_upnp(timeout)),
            ("sonos", lambda: self._scan_sonos(timeout)),
            ("roku", lambda: self._scan_roku(timeout)),
            ("kodi", lambda: self._scan_kodi(zc, timeout)),
        ]

        def run(scan):
            try:
                return scan() or {}
            except Exception:
                # One missing protocol costs its own devices and nothing else.
                LOG.info("Casting: a discovery scan failed", exc_info=True)
                return {}

        results: Dict[str, dict] = {}
        try:
            with concurrent.futures.ThreadPoolExecutor(
                    max_workers=len(scans), thread_name_prefix="cast-discover") as pool:
                futures = {pool.submit(run, scan): key for key, scan in scans}
                for future in concurrent.futures.as_completed(futures):
                    results[futures[future]] = future.result()
        finally:
            if zc is not None:
                try:
                    zc.close()
                except Exception:
                    LOG.debug("CastingManager.discover_all: ignored exception", exc_info=True)

        # Caster's merge: a fixed order, so which protocol answered first
        # cannot change the list. One box answering two protocols keeps the
        # entry that can show a picture, when its renderer said so. Sonos
        # goes last and wins: it answers AirPlay and UPnP too, and only its
        # own protocol plays.
        found: Dict[str, Any] = {}
        for key in ("chromecast", "airplay", "upnp", "roku", "kodi"):
            for name, device in results.get(key, {}).items():
                seen = found.get(name)
                if seen is None:
                    found[name] = device
                elif device.sinks and device.supports_video and not seen.supports_video:
                    found[name] = device
        found.update(results.get("sonos", {}))
        return sorted((CastDevice(d) for d in found.values()),
                      key=lambda d: d.display_name.lower())

    def _scan_chromecast(self, zc, timeout: int) -> dict:
        """Cast devices, by browsing _googlecast._tcp directly.

        pychromecast's own browser misses some Cast devices (FFM smart TVs),
        so the TXT records are read here, each service resolved as soon as
        it is announced.
        """
        if zc is None:
            return {}
        import zeroconf
        from caster_engine import Device
        from caster_extras import mdns_host

        found: Dict[str, Any] = {}
        seen: set = set()
        lock = threading.Lock()
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=8,
                                                     thread_name_prefix="cast-resolve")

        def resolve(type_: str, name: str) -> None:
            try:
                info = zc.get_service_info(type_, name, 3000)
            except Exception:
                return
            if not info or not info.addresses:
                return
            props = {}
            for k, v in info.properties.items():
                kd = k.decode() if isinstance(k, bytes) else k
                props[kd] = v.decode(errors="replace") if isinstance(v, bytes) else (v or "")
            host = mdns_host(info)
            if not host:
                return
            fn = props.get("fn") or name.split(".")[0]
            device = Device("chromecast", fn, {
                "host": host,
                "port": info.port or 8009,
                "uuid": props.get("id") or uuidlib.uuid4().hex,
                "model": props.get("md") or "Chromecast",
            })
            with lock:
                key = fn if fn not in found else f"{fn} ({host})"
                found[key] = device

        class _Listener:
            def add_service(self, zc_, type_, name):
                with lock:
                    if name in seen:
                        return
                    seen.add(name)
                pool.submit(resolve, type_, name)

            def update_service(self, zc_, type_, name):
                pass

            def remove_service(self, zc_, type_, name):
                pass

        browser = None
        try:
            browser = zeroconf.ServiceBrowser(zc, "_googlecast._tcp.local.", _Listener())
            time.sleep(timeout)
        finally:
            if browser is not None:
                try:
                    browser.cancel()
                except Exception:
                    LOG.debug("CastingManager._scan_chromecast: ignored exception", exc_info=True)
            pool.shutdown(wait=True)
        return found

    def _scan_airplay(self, timeout: int) -> dict:
        try:
            import pyatv
            from pyatv.const import PairingRequirement, Protocol
        except ImportError:
            LOG.info("Casting: pyatv is not installed; AirPlay devices will not be found")
            return {}
        from caster_devices import looks_like_sonos
        from caster_engine import Device

        loop = self._loop_thread.loop
        future = asyncio.run_coroutine_threadsafe(
            pyatv.scan(loop, timeout=timeout, protocol={Protocol.RAOP, Protocol.AirPlay}), loop)
        found: Dict[str, Any] = {}
        for cfg in future.result(timeout + 15):
            if not cfg.name:
                continue
            # AirPlay here is RAOP audio, with no pairing flow. A device that
            # has no RAOP service, or wants pairing for it, can only fail.
            raop = next((s for s in cfg.services if s.protocol == Protocol.RAOP), None)
            if raop is None or raop.pairing != PairingRequirement.NotNeeded:
                continue
            # A Sonos over AirPlay 2 demands MFi authentication; it is found
            # through its own protocol instead.
            if looks_like_sonos(cfg.name, str(getattr(cfg, "device_info", ""))):
                continue
            found.setdefault(cfg.name, Device("airplay", cfg.name, cfg))
        return found

    @staticmethod
    def _scan_upnp(timeout: int) -> dict:
        from caster_devices import looks_like_sonos
        from caster_engine import Device
        from caster_extras import upnp_discover

        found: Dict[str, Any] = {}
        for name, url, maker, sinks in upnp_discover(timeout=timeout):
            if looks_like_sonos(name, maker):
                continue
            found.setdefault(name, Device("upnp", name,
                                          {"control_url": url.replace("&amp;", "&")},
                                          sinks=sinks))
        return found

    @staticmethod
    def _scan_sonos(timeout: int) -> dict:
        from caster_devices import sonos_discover
        from caster_engine import Device
        return {name: Device("sonos", name, {"ip": ip})
                for name, ip in sonos_discover(timeout=timeout, seed_ips=[])}

    @staticmethod
    def _scan_roku(timeout: int) -> dict:
        from caster_devices import roku_discover
        from caster_engine import Device
        return {name: Device("roku", name, {"base": base})
                for name, base in roku_discover(timeout=timeout)}

    @staticmethod
    def _scan_kodi(zc, timeout: int) -> dict:
        from caster_devices import kodi_discover
        from caster_engine import Device
        return {name: Device("kodi", name, {"base": base})
                for name, base in kodi_discover(timeout=timeout, zc=zc)}

    # ------------------------------------------------------------------ #
    # Session
    # ------------------------------------------------------------------ #
    def connect(self, device: CastDevice, credentials: Optional[str] = None) -> None:
        """Choose the receiver later plays go to. Nothing is sent yet."""
        del credentials  # AirPlay here needs no pairing
        self._require_running()
        if self.active_device is not None and self.active_device.device is not device.device:
            self.stop_playback()
        self.active_device = device

    def is_connected(self) -> bool:
        return self.active_device is not None

    def disconnect(self) -> None:
        self.stop_playback()
        self.active_device = None

    def play(self, url: str, title: str = "IPTV Stream",
             channel: Optional[Dict[str, str]] = None,
             headers: Optional[Dict[str, object]] = None,
             *, exclusive: bool = False, is_live: Optional[bool] = None) -> None:
        """Play ``url`` on the chosen receiver; returns once it is playing.

        ``exclusive`` marks a provider that allows one connection at a time.
        """
        self._require_running()
        device = self.active_device
        if device is None:
            raise ConnectionError("No cast device is selected.")
        from http_headers import channel_http_headers, merge_headers, split_stream_modifiers

        fetch_url, pipe_headers = split_stream_modifiers(url)
        request_headers = merge_headers(
            headers if headers is not None else channel_http_headers(channel), pipe_headers)
        source = self._source_url(fetch_url, request_headers)
        self.stop_playback()
        with self._lock:
            generation = self._generation
        kind = device.kind
        LOG.info("Casting %s to %s", title, device.display_name)
        if kind == "chromecast":
            self._play_chromecast(device, source, generation, exclusive, is_live)
        elif kind == "airplay":
            self._play_airplay(device, source, generation, exclusive, is_live)
        elif kind == "upnp":
            self._play_upnp(device, source, title, generation, exclusive, request_headers,
                            fetch_url)
        elif kind == "sonos":
            self._play_sonos(device, source, title, exclusive, request_headers, fetch_url)
        elif kind == "roku":
            self._play_roku(device, source, title, generation, exclusive)
        elif kind == "kodi":
            self._play_kodi(device, source)
        else:
            raise CastError(f"{device.display_name} cannot be cast to.")

    def stop_playback(self) -> None:
        """Stop whatever is playing on the receiver; keep it selected."""
        with self._lock:
            self._generation += 1
            relays, self._relays = list(self._relays), []
            cast, self._cast = self._cast, None
            self._live_load = None
            self._cast_progress = None
            shutdown, self._air_shutdown = self._air_shutdown, None
            proc, self._air_proc = self._air_proc, None
        for relay in relays:
            try:
                relay.stop()
            except Exception:
                LOG.debug("CastingManager.stop_playback: relay", exc_info=True)
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                LOG.debug("CastingManager.stop_playback: ffmpeg", exc_info=True)
        if shutdown is not None and self._loop_thread is not None:
            self._loop_thread.loop.call_soon_threadsafe(shutdown.set)
        if cast is not None:
            self._release_cast(cast)
        device = self.active_device
        if device is None:
            return
        try:
            key = device.device.key
            if device.kind == "upnp":
                from caster_extras import upnp_stop
                upnp_stop(key["control_url"])
            elif device.kind == "sonos":
                from caster_devices import sonos_stop
                sonos_stop(key["ip"])
            elif device.kind == "roku":
                from caster_devices import roku_stop
                roku_stop(key["base"])
            elif device.kind == "kodi":
                from caster_devices import kodi_stop
                kodi_stop(key["base"])
        except Exception:
            LOG.debug("CastingManager.stop_playback: receiver stop", exc_info=True)

    # ------------------------------------------------------------------ #
    # Shared helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _source_url(url: str, headers: Dict[str, object]) -> str:
        """The URL the engine and the receiver should fetch.

        A channel with its own request headers is served through the stream
        proxy's header gateway; everything else goes to the provider directly.
        """
        if not headers or not url.lower().startswith(("http://", "https://")):
            return url
        from stream_proxy import get_proxy
        proxy = get_proxy()
        proxy.start()
        return proxy.get_gateway_url(url, headers)

    def _abandoned(self, generation: int) -> bool:
        return not self._running or generation != self._generation

    def _keep_relay(self, relay, generation: int) -> None:
        with self._lock:
            if generation != self._generation:
                stale = True
            else:
                self._relays.append(relay)
                stale = False
        if stale:
            relay.stop()
            raise PlaybackError("Casting was stopped.")

    def _drop_relay(self, relay) -> None:
        if relay is None:
            return
        with self._lock:
            if relay in self._relays:
                self._relays.remove(relay)
        try:
            relay.stop()
        except Exception:
            LOG.debug("CastingManager._drop_relay: ignored exception", exc_info=True)

    @staticmethod
    def _make_relay(url: str, codecs=None, live: Optional[bool] = None):
        engine = _engine()
        from caster_config import preset
        chosen = preset(RELAY_PRESET)
        if codecs is None:
            codecs = engine._probe_codecs(url)
        return engine.HlsRelay(url,
                               hls_time=chosen["hls_time"],
                               prime_segments=chosen["hls_prime"],
                               trail_keep=chosen["hls_trail"],
                               trail_seconds=chosen["hls_trail_seconds"],
                               startup_seconds=chosen["hls_start_seconds"],
                               codecs=codecs, live=live)

    def _start_relay(self, url: str, generation: int, codecs=None,
                     live: Optional[bool] = None) -> tuple:
        relay = self._make_relay(url, codecs=codecs, live=live)
        self._keep_relay(relay, generation)
        try:
            return relay, relay.start()
        except Exception:
            self._drop_relay(relay)
            raise

    @staticmethod
    def _settle(exclusive: bool) -> None:
        """Let a one-stream provider release the connection just closed."""
        if exclusive:
            from catchup_direct import settle_media_session
            settle_media_session()

    @staticmethod
    def _speaker_url(fetch_url: str, headers: Dict[str, object]) -> str:
        """A TV channel as an MP3 stream, for receivers that are speakers."""
        from stream_proxy import get_proxy
        proxy = get_proxy()
        proxy.start()
        return proxy.get_audio_url(fetch_url, headers)

    # ------------------------------------------------------------------ #
    # Chromecast
    # ------------------------------------------------------------------ #
    def _cast_zeroconf(self):
        if self._cast_zc is None:
            import zeroconf
            self._cast_zc = zeroconf.Zeroconf()
        return self._cast_zc

    @staticmethod
    def _ensure_receiver(cast, timeout: float = 8.0) -> None:
        """Make sure the media receiver app is running, and no more than that.

        Relaunching an app that is already up costs a teardown and launch; so
        the launch is forced only when another app holds the screen.
        """
        try:
            app_id = cast.app_id
            if app_id is None:
                deadline = time.monotonic() + 1.5
                while app_id is None and time.monotonic() < deadline:
                    time.sleep(0.05)
                    app_id = cast.app_id
            if app_id == CAST_APP_ID:
                return
            cast.start_app(CAST_APP_ID, force_launch=app_id is not None)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if cast.app_id == CAST_APP_ID:
                    time.sleep(0.25)
                    return
                time.sleep(0.05)
        except Exception:
            LOG.debug("CastingManager._ensure_receiver: play_media reports the failure",
                      exc_info=True)

    def _await_playing(self, mc, previous_session=None) -> bool:
        """True once the receiver plays; False if it rejected the load.

        A status still carrying the previous session id belongs to the last
        thing played and is ignored.
        """
        deadline = time.monotonic() + LOAD_TIMEOUT
        while time.monotonic() < deadline:
            status = mc.status
            if status is not None:
                session = getattr(status, "media_session_id", None)
                stale = previous_session is not None and session == previous_session
                if not stale:
                    if status.player_state == "PLAYING":
                        return True
                    if (status.player_state == "IDLE" and status.idle_reason
                            and status.idle_reason not in STALE_IDLE_REASONS):
                        return False
            time.sleep(LOAD_POLL)
        return False

    def _load_options(self, url: str) -> dict:
        """Start a live relay at its buffered beginning; Cast clamps to its window."""
        with self._lock:
            relays = list(self._relays)
        for relay in relays:
            if getattr(relay, "play_url", None) == url and relay.live:
                return {"current_time": 0}
        return {}

    def _load(self, mc, url: str, mime: str, stream_type: str) -> bool:
        before = getattr(mc.status, "media_session_id", None)
        mc.play_media(url, mime, stream_type=stream_type, **self._load_options(url))
        return self._await_playing(mc, before)

    @staticmethod
    def _release_cast(cast) -> None:
        """Stop the receiver's media (not its app) and close the connection."""
        def release() -> None:
            try:
                mc = cast.media_controller
                status = mc.status
                if status is not None and status.media_session_id is not None:
                    mc.stop(timeout=3)
            except Exception:
                LOG.debug("CastingManager._release_cast: stop", exc_info=True)
            try:
                cast.disconnect(timeout=3)
            except Exception:
                LOG.debug("CastingManager._release_cast: disconnect", exc_info=True)
        threading.Thread(target=release, daemon=True, name="cast-release").start()

    def _play_chromecast(self, device: CastDevice, url: str, generation: int,
                         exclusive: bool, is_live: Optional[bool]) -> None:
        try:
            import pychromecast
            from pychromecast.const import CAST_TYPE_CHROMECAST
            from pychromecast.models import CastInfo, HostServiceInfo
        except ImportError as err:
            raise CastError("Chromecast support is not installed (pychromecast).") from err
        engine = _engine()
        key = device.device.key
        host, port = key["host"], key.get("port", 8009)
        info = CastInfo(
            uuid=uuidlib.UUID(key["uuid"]), host=host, port=port,
            cast_type=CAST_TYPE_CHROMECAST, manufacturer="",
            model_name=key.get("model") or "Chromecast", friendly_name=device.name,
            # Mandatory: with no HostServiceInfo the socket client never connects.
            services={HostServiceInfo(host, port)},
        )
        cast = pychromecast.Chromecast(info, zconf=self._cast_zeroconf(), tries=3, timeout=15)
        cast.wait(20)
        with self._lock:
            if generation != self._generation:
                stale = True
            else:
                self._cast = cast
                stale = False
        if stale:
            self._release_cast(cast)
            raise PlaybackError("Casting was stopped.")

        relay = None
        try:
            mc = cast.media_controller
            # Bring the receiver app up now, alongside the probe and the relay
            # prime, instead of after them.
            warm = threading.Thread(target=self._ensure_receiver, args=(cast,),
                                    daemon=True, name="cast-warm")
            warm.start()
            is_playlist = url.lower().split("?")[0].endswith(".m3u8")
            codecs_box: list = []
            codecs_thread = None
            if (not exclusive and url.lower().startswith(("http://", "https://"))
                    and not is_playlist):
                # Codecs cost a connection of their own; ask alongside the probe.
                codecs_thread = threading.Thread(
                    target=lambda: codecs_box.append(engine._probe_codecs(url)),
                    daemon=True, name="cast-codecs")
                codecs_thread.start()

            probe = engine.probe_media(url)
            if is_live is not None:
                probe["is_live"] = is_live
            self._settle(exclusive)

            def codecs():
                if codecs_thread is not None:
                    codecs_thread.join()
                    return codecs_box[0] if codecs_box else None
                if exclusive and not is_playlist:
                    found = engine._probe_codecs(url)
                    self._settle(True)
                    return found
                return None

            load_mime = probe["mime"]
            native_url = (engine._native_hls_url(url)
                          if probe["mime"] == "video/mp2t" and probe["is_live"] else None)
            if native_url:
                play_url, load_mime = native_url, "application/vnd.apple.mpegurl"
            elif probe["mime"] == "video/mp2t" and not is_playlist:
                # Cast receivers reject raw MPEG-TS: remux through the relay.
                relay, play_url = self._start_relay(url, generation, codecs=codecs(),
                                                    live=bool(probe["is_live"]))
                load_mime = "application/vnd.apple.mpegurl"
            else:
                play_url = url
            stream_type = "LIVE" if probe["is_live"] else "BUFFERED"
            warm.join(timeout=10)
            self._ensure_receiver(cast)
            if self._abandoned(generation):
                raise PlaybackError("Casting was stopped.")

            settled = self._load(mc, play_url, load_mime, stream_type)
            if not settled and native_url and not self._abandoned(generation):
                # A valid provider playlist can still be incompatible here.
                relay, play_url = self._start_relay(url, generation, codecs=codecs(), live=True)
                settled = self._load(mc, play_url, load_mime, stream_type)
            if not settled and not self._abandoned(generation):
                # Live vs buffered wrong means the load is rejected; flip once.
                stream_type = "BUFFERED" if stream_type == "LIVE" else "LIVE"
                settled = self._load(mc, play_url, load_mime, stream_type)
            if (not settled and relay is None and play_url == url
                    and not probe["is_live"] and not self._abandoned(generation)):
                # A container or codec this receiver cannot play: re-encode.
                relay, play_url = self._start_relay(url, generation, live=False)
                load_mime, stream_type = "application/vnd.apple.mpegurl", "BUFFERED"
                settled = self._load(mc, play_url, load_mime, stream_type)
            if self._abandoned(generation):
                raise PlaybackError("Casting was stopped.")
            if not settled:
                reason = getattr(mc.status, "idle_reason", None) or "no answer"
                raise PlaybackError(
                    f"{device.name} did not start playing the stream ({reason}).")
            if probe["is_live"]:
                with self._lock:
                    if generation == self._generation:
                        self._live_load = (generation, cast, play_url, load_mime, stream_type)
                        self._cast_progress = None
        except Exception:
            self._drop_relay(relay)
            raise

    def _watchdog_loop(self) -> None:
        while not self._watchdog_stop.wait(WATCHDOG_SECONDS):
            try:
                self._recover_live_cast()
            except Exception:
                LOG.debug("CastingManager watchdog: ignored exception", exc_info=True)

    def _recover_live_cast(self) -> None:
        """Reload a live cast that ended or froze on the receiver (Caster's rules)."""
        with self._lock:
            load = self._live_load
        if load is None or self._recovering:
            return
        generation, cast, url, mime, stream_type = load
        now = time.monotonic()
        status = cast.media_controller.status
        if status is None:
            return
        state = status.player_state
        if state in ("PLAYING", "BUFFERING"):
            # The receiver does not push its position while playing steadily;
            # ask, or healthy playback reads as frozen.
            try:
                cast.media_controller.update_status()
            except Exception:
                LOG.debug("CastingManager._recover_live_cast: update_status", exc_info=True)
            position = getattr(status, "current_time", None)
            session = getattr(status, "media_session_id", None)
            updated = getattr(status, "last_updated", None)
            if position is None:
                return
            previous = self._cast_progress
            if previous is None or previous[0] is not load or previous[1:3] != (session, position):
                self._cast_progress = (load, session, position, now, updated)
                return
            if updated is None or updated == previous[4]:
                return          # no newer report: silence, not a stall
            if now - previous[3] < CAST_STALL_TIMEOUT:
                return
        elif state != "IDLE":
            self._cast_progress = None      # a deliberate pause is left alone
            return
        if now < self._cast_retry_at:
            return
        self._cast_retry_at = now + CAST_RECOVERY_INTERVAL
        self._recovering = True
        try:
            self._ensure_receiver(cast)
            if self._abandoned(generation) or self._live_load is not load:
                return
            LOG.info("Casting: live stream stalled on the receiver; reloading it")
            self._load(cast.media_controller, url, mime, stream_type)
        finally:
            self._recovering = False

    # ------------------------------------------------------------------ #
    # AirPlay (RAOP audio)
    # ------------------------------------------------------------------ #
    def _play_airplay(self, device: CastDevice, url: str, generation: int,
                      exclusive: bool, is_live: Optional[bool]) -> None:
        try:
            import pyatv
            from pyatv.const import Protocol
        except ImportError as err:
            raise CastError("AirPlay support is not installed (pyatv).") from err
        engine = _engine()
        loop = self._loop_thread.loop
        started = threading.Event()
        failure: list = []
        shutdown_box: list = []

        async def runner() -> None:
            atv = None
            stream_task = None
            shutdown = asyncio.Event()
            shutdown_box.append(shutdown)
            with self._lock:
                if generation == self._generation:
                    self._air_shutdown = shutdown
                else:
                    shutdown.set()
            try:
                probe_job = loop.run_in_executor(None, engine.probe_media, url)
                atv = await pyatv.connect(device.device.key, loop, protocol=Protocol.RAOP)
                probe = await probe_job
                if is_live is not None:
                    probe["is_live"] = is_live
                live = bool(probe["is_live"]) and not probe["is_audio"]
                if exclusive:
                    await loop.run_in_executor(None, self._settle, True)
                while not shutdown.is_set():
                    proc, reader = await self._raop_source(url, live)
                    stream_task = asyncio.create_task(atv.stream.stream_file(reader))
                    started.set()
                    stop_wait = asyncio.create_task(shutdown.wait())
                    try:
                        await asyncio.wait([stream_task, stop_wait],
                                           return_when=asyncio.FIRST_COMPLETED)
                        error = None
                        if not stream_task.done():
                            stream_task.cancel()
                        try:
                            await stream_task
                        except asyncio.CancelledError:
                            LOG.debug("Casting: AirPlay stream task canceled", exc_info=True)
                        except Exception as exc:
                            error = exc
                        stream_task = None
                        if shutdown.is_set():
                            break
                        if live:
                            # Live sources drop every few seconds; ffmpeg exits
                            # and the stream reopens at the live edge on the
                            # same RAOP session.
                            await asyncio.sleep(1)
                            continue
                        code = proc.poll()
                        if error is None and code not in (None, 0):
                            error = RuntimeError(f"ffmpeg could not read the stream (exit code {code})")
                        if error is not None:
                            raise error
                        break           # a finite stream ended
                    finally:
                        stop_wait.cancel()
                        if proc.poll() is None:
                            proc.kill()
            except asyncio.CancelledError:
                LOG.debug("Casting: AirPlay runner canceled", exc_info=True)
            except Exception as exc:
                failure.append(exc)
                LOG.info("Casting: AirPlay stream ended: %s", exc)
            finally:
                started.set()
                if stream_task is not None and not stream_task.done():
                    stream_task.cancel()
                    try:
                        await stream_task
                    except (asyncio.CancelledError, Exception):
                        LOG.debug("Casting: AirPlay stream task ended while stopping", exc_info=True)
                if atv is not None:
                    await engine._close_atv(atv)

        future = asyncio.run_coroutine_threadsafe(runner(), loop)
        self._air_future = future
        if not started.wait(AIRPLAY_START_TIMEOUT):
            if shutdown_box:
                loop.call_soon_threadsafe(shutdown_box[0].set)
            raise PlaybackError(f"{device.name} did not start playing in time.")
        try:
            # A receiver that refuses the audio does so at once; catch that
            # here rather than reporting success and going quiet.
            future.result(timeout=1.5)
        except concurrent.futures.TimeoutError:
            # Still streaming, as a live channel should be.
            LOG.debug("Casting: AirPlay stream running on %s", device.name)
        except Exception:
            LOG.debug("CastingManager._play_airplay: runner", exc_info=True)
        if failure:
            raise PlaybackError(f"AirPlay could not play the stream: {failure[0]}")
        if self._abandoned(generation):
            raise PlaybackError("Casting was stopped.")

    async def _raop_source(self, url: str, live: bool):
        """ffmpeg extracting the stream's audio as WAV for pyatv (Caster's pipe)."""
        engine = _engine()
        import subprocess

        cmd = [engine._find_ffmpeg(), "-hide_banner", "-loglevel", "error"]
        if url.lower().startswith(("http://", "https://")):
            if live:
                # No reconnect flags: a byte-offset resume splices replayed
                # media in. A drop ends the pipe and the runner reopens it.
                cmd += ["-seekable", "0"]
            cmd += ["-rw_timeout", "5000000"]
        cmd += [
            "-analyzeduration", "1000000", "-probesize", "1000000",
            "-fflags", "+genpts+nobuffer", "-flags", "+low_delay",
            "-i", url,
            "-vn", "-map", "a:0?",
            # Absorb the receiver's clock drifting from the source's.
            "-af", "aresample=44100:async=1000:first_pts=0",
            # Lossless streaming FLAC avoids miniaudio's unknown-length WAV scan.
            "-ac", "2", "-f", "flac", "-c:a", "flac", "-flush_packets", "1", "-",
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                stdin=subprocess.DEVNULL, **engine._no_window_kwargs())
        with self._lock:
            self._air_proc = proc
        reader = engine.SeekablePipeReader(proc.stdout.read1, proc.stdout.close)
        await asyncio.get_running_loop().run_in_executor(None, reader.prefill)
        return proc, reader

    # ------------------------------------------------------------------ #
    # UPnP / DLNA, Sonos, Roku, Kodi
    # ------------------------------------------------------------------ #
    def _play_upnp(self, device: CastDevice, url: str, title: str, generation: int,
                   exclusive: bool, headers: Dict[str, object], fetch_url: str) -> None:
        engine = _engine()
        probe = engine.probe_media(url)
        self._settle(exclusive)
        relay = None
        try:
            if probe["mime"] == "video/mp2t" and not device.supports_video:
                # An amplifier or speaker renderer: send the sound only.
                play_url, mime = self._speaker_url(fetch_url, headers), "audio/mpeg"
            elif probe["mime"] == "video/mp2t":
                relay, play_url = self._start_relay(url, generation, live=bool(probe["is_live"]))
                mime = "application/vnd.apple.mpegurl"
            elif url.lower().startswith(("http://", "https://")):
                play_url, mime = url, probe["mime"]
            else:
                relay, play_url = self._start_relay(url, generation)
                mime = "application/vnd.apple.mpegurl"
            if self._abandoned(generation):
                raise PlaybackError("Casting was stopped.")
            self._upnp_push(device, play_url, mime, title)
        except Exception:
            self._drop_relay(relay)
            raise

    @staticmethod
    def _upnp_push(device: CastDevice, play_url: str, mime: str, title: str) -> None:
        from caster_devices import yxc_available, yxc_set_input
        from caster_extras import upnp_host, upnp_play

        control_url = device.device.key["control_url"]
        # A MusicCast receiver ignores a pushed URL unless it is already on
        # its network input, and says nothing.
        host = upnp_host(control_url)
        try:
            if host and yxc_available(host):
                yxc_set_input(host, "server")
        except Exception:
            LOG.debug("CastingManager._upnp_push: MusicCast input", exc_info=True)
        try:
            upnp_play(control_url, play_url, title, mime,
                      "object.item.audioItem.musicTrack" if mime.startswith("audio/")
                      else "object.item.videoItem")
        except Exception as err:
            raise PlaybackError(f"{device.name} refused the stream: {err}") from err

    def _play_sonos(self, device: CastDevice, url: str, title: str, exclusive: bool,
                    headers: Dict[str, object], fetch_url: str) -> None:
        from caster_devices import sonos_play
        engine = _engine()
        probe = engine.probe_media(url)
        self._settle(exclusive)
        if probe["is_audio"]:
            play_url, mime = url, probe["mime"]
        else:
            # Sonos is speakers: a TV channel goes as its sound.
            play_url, mime = self._speaker_url(fetch_url, headers), "audio/mpeg"
        try:
            sonos_play(device.device.key["ip"], play_url, title, mime)
        except Exception as err:
            raise PlaybackError(f"Sonos error: {err}") from err

    def _play_roku(self, device: CastDevice, url: str, title: str, generation: int,
                   exclusive: bool) -> None:
        from caster_devices import roku_play
        engine = _engine()
        probe = engine.probe_media(url)
        self._settle(exclusive)
        relay = None
        try:
            if probe["mime"] == "video/mp2t":
                # Roku Media Player has no MPEG-TS: MP4 or HLS only.
                relay, play_url = self._start_relay(url, generation, live=bool(probe["is_live"]))
                mime = "application/vnd.apple.mpegurl"
            else:
                play_url, mime = url, engine.roku_mime(url)
            if self._abandoned(generation):
                raise PlaybackError("Casting was stopped.")
            roku_play(device.device.key["base"], play_url, mime, title)
        except PlaybackError:
            self._drop_relay(relay)
            raise
        except Exception as err:
            self._drop_relay(relay)
            raise PlaybackError(f"Roku error: {err}") from err

    @staticmethod
    def _play_kodi(device: CastDevice, url: str) -> None:
        import urllib.error
        from caster_devices import kodi_play
        # Kodi plays anything ffmpeg does, MPEG-TS included.
        try:
            kodi_play(device.device.key["base"], url)
        except urllib.error.HTTPError as err:
            if err.code == 401:
                raise PlaybackError(
                    "Kodi refused the request. In Kodi, allow remote control over "
                    "HTTP without a password.") from err
            raise PlaybackError(f"Kodi error: {err}") from err
        except Exception as err:
            raise PlaybackError(f"Kodi error: {err}") from err
