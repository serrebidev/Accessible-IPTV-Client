import json
import time
import uuid
import urllib.parse
import urllib.request
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from i18n import gettext as _


DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"


class ProviderError(RuntimeError):
    """Raised when a provider fails to return a playlist."""


def _normalize_base_url(url: str) -> str:
    url = url.strip()
    if not url:
        return url
    parsed = urllib.parse.urlparse(url)
    if not parsed.scheme:
        url = "http://" + url
        parsed = urllib.parse.urlparse(url)
    if parsed.path and parsed.path != "/":
        # Remove trailing portal filename (common inputs like http://host/stalker_portal)
        # Keep the directory so we can append files below.
        if parsed.path.endswith("portal.php"):
            path = parsed.path.rsplit("/", 1)[0]
        else:
            path = parsed.path
    else:
        path = parsed.path or ""
    rebuilt = urllib.parse.urlunparse((
        parsed.scheme,
        parsed.netloc,
        path.rstrip('/'),
        '',
        '',
        ''
    ))
    return rebuilt.rstrip('/')


@dataclass
class XtreamCodesConfig:
    base_url: str
    username: str
    password: str
    stream_type: str = "m3u_plus"
    output: str = "ts"
    name: Optional[str] = None
    auto_epg: bool = True
    provider_id: Optional[str] = None
    user_agent: str = DEFAULT_UA


class XtreamCodesClient:
    def __init__(self, cfg: XtreamCodesConfig):
        self.cfg = cfg
        self._base = _normalize_base_url(cfg.base_url)

    def playlist_url(self) -> str:
        params = urllib.parse.urlencode({
            "username": self.cfg.username,
            "password": self.cfg.password,
            "type": self.cfg.stream_type or "m3u_plus",
            "output": self.cfg.output or "ts"
        })
        return f"{self._base}/get.php?{params}"

    def epg_urls(self) -> List[str]:
        if not self.cfg.auto_epg:
            return []
        params = urllib.parse.urlencode({
            "username": self.cfg.username,
            "password": self.cfg.password,
        })
        return [f"{self._base}/xmltv.php?{params}"]

    def fetch_playlist(self, timeout: int = 60) -> str:
        url = self.playlist_url()
        req = urllib.request.Request(url, headers={"User-Agent": self.cfg.user_agent})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("latin-1", "ignore")

    # ------------------------------------------------------------------ #
    # player_api.php (structured VOD / Series browsing)
    #
    # The get.php m3u_plus feed above returns a flat, mixed channel list. The
    # player_api endpoints instead expose movies and series as a browsable
    # catalogue with categories, and — crucially — let series episodes be
    # loaded lazily per series (get_series_info) so we never enumerate every
    # episode of every show up front.
    # ------------------------------------------------------------------ #
    def _player_api_url(self, action: Optional[str] = None, extra: Optional[Dict[str, str]] = None) -> str:
        params: Dict[str, str] = {
            "username": self.cfg.username,
            "password": self.cfg.password,
        }
        if action:
            params["action"] = action
        if extra:
            for k, v in extra.items():
                if v is not None:
                    params[k] = v
        return f"{self._base}/player_api.php?{urllib.parse.urlencode(params)}"

    def _player_api(self, action: Optional[str] = None, extra: Optional[Dict[str, str]] = None, timeout: int = 30):
        url = self._player_api_url(action, extra)
        req = urllib.request.Request(url, headers={"User-Agent": self.cfg.user_agent})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1", "ignore")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            raise ProviderError(_("Invalid response from Xtream player API"))

    def get_vod_categories(self, timeout: int = 30) -> List[Dict]:
        data = self._player_api("get_vod_categories", timeout=timeout)
        return data if isinstance(data, list) else []

    def get_vod_streams(self, category_id: Optional[str] = None, timeout: int = 60) -> List[Dict]:
        extra = {"category_id": str(category_id)} if category_id is not None else None
        data = self._player_api("get_vod_streams", extra, timeout=timeout)
        return data if isinstance(data, list) else []

    def get_series_categories(self, timeout: int = 30) -> List[Dict]:
        data = self._player_api("get_series_categories", timeout=timeout)
        return data if isinstance(data, list) else []

    def get_series(self, category_id: Optional[str] = None, timeout: int = 60) -> List[Dict]:
        extra = {"category_id": str(category_id)} if category_id is not None else None
        data = self._player_api("get_series", extra, timeout=timeout)
        return data if isinstance(data, list) else []

    def get_series_info(self, series_id, timeout: int = 30) -> Dict:
        extra = {"series_id": str(series_id)}
        data = self._player_api("get_series_info", extra, timeout=timeout)
        return data if isinstance(data, dict) else {}

    def vod_stream_url(self, stream_id, ext: str = "mp4") -> str:
        ext = (ext or "mp4").lstrip(".")
        user = urllib.parse.quote(self.cfg.username, safe="")
        pw = urllib.parse.quote(self.cfg.password, safe="")
        return f"{self._base}/movie/{user}/{pw}/{stream_id}.{ext}"

    def series_stream_url(self, episode_id, ext: str = "mp4") -> str:
        ext = (ext or "mp4").lstrip(".")
        user = urllib.parse.quote(self.cfg.username, safe="")
        pw = urllib.parse.quote(self.cfg.password, safe="")
        return f"{self._base}/series/{user}/{pw}/{episode_id}.{ext}"

    def describe(self) -> str:
        label = self.cfg.name or urllib.parse.urlparse(self._base).netloc
        return f"Xtream Codes ({label})"


@dataclass
class StalkerPortalConfig:
    base_url: str
    username: str
    password: str
    mac: str
    name: Optional[str] = None
    auto_epg: bool = True
    provider_id: Optional[str] = None
    user_agent: str = "Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/535.21 (KHTML, like Gecko) MAG250 stbapp Safari/535.21"
    profile_user_agent: str = "Model: MAG420; Link: WiFi"
    timezone: str = "UTC"


class StalkerPortalClient:
    """
    Minimal Stalker/Ministra portal client that performs the MAG-style handshake
    and exposes channel metadata for live/archived playback.
    """

    def __init__(self, cfg: StalkerPortalConfig):
        self.cfg = cfg
        self._base = _normalize_base_url(cfg.base_url)
        self._portal_endpoint = self._derive_portal_endpoint()
        self._token: Optional[str] = None
        self._token_issued: float = 0.0
        self._token_lock = threading.Lock()
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())

    def _derive_portal_endpoint(self) -> str:
        # Support either /portal.php or /server/load.php style deployments.
        if self.cfg.base_url.strip().lower().endswith("portal.php"):
            return self.cfg.base_url.strip()
        if self.cfg.base_url.strip().lower().endswith("load.php"):
            return self.cfg.base_url.strip()
        # default: append portal.php relative to base directory
        base = _normalize_base_url(self.cfg.base_url)
        return f"{base}/portal.php"

    def _headers(self, include_token: bool = True) -> Dict[str, str]:
        headers = {
            "User-Agent": self.cfg.user_agent,
            "Accept": "application/json",
            "Connection": "keep-alive",
            "X-User-Agent": self.cfg.profile_user_agent,
            "Referer": f"{self._base}/c/",
            "Cookie": f"stb_lang=en; timezone={self.cfg.timezone}; mac={self.cfg.mac}"
        }
        if include_token and self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _portal_call(self, params: Dict[str, str], include_token: bool = True, timeout: int = 30) -> Dict:
        query = urllib.parse.urlencode(params)
        url = f"{self._portal_endpoint}?{query}"
        req = urllib.request.Request(url, headers=self._headers(include_token=include_token))
        with self._opener.open(req, timeout=timeout) as resp:
            raw = resp.read()
        text = raw.decode("utf-8", "ignore")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            raise ProviderError(_("Invalid response from portal: {response}").format(response=repr(text)))

    def _ensure_token(self):
        # Serialize refreshes: this client is shared across background resolve threads,
        # and overlapping handshake/login round-trips can interleave token writes.
        with self._token_lock:
            now = time.time()
            if self._token and (now - self._token_issued) < 60 * 25:
                return
            # Step 1: handshake to get temporary token
            data = self._portal_call({
                "type": "stb",
                "action": "handshake",
                "token": "",
                "prehash": "0",
                "JsHttpRequest": "1-xml"
            }, include_token=False)
            token = data.get("token") or data.get("js", {}).get("token")
            if not token:
                raise ProviderError(_("Portal handshake failed: no token returned"))
            self._token = token
            self._token_issued = now
            # Step 2: authenticate with credentials to obtain session token
            auth = self._portal_call({
                "type": "stb",
                "action": "login",
                "login": self.cfg.username,
                "password": self.cfg.password,
                "JsHttpRequest": "1-xml"
            })
            new_token = auth.get("token") or auth.get("js", {}).get("token")
            if new_token:
                self._token = new_token
                self._token_issued = time.time()

    def fetch_channels(self) -> Tuple[List[Dict], List[str]]:
        self._ensure_token()
        payload = self._portal_call({
            "type": "itv",
            "action": "get_all_channels",
            "include": "genres",
            "force_ch_link_check": "1",
            "JsHttpRequest": "1-xml"
        })
        data = payload.get("js", {}).get("data") or []
        channels: List[Dict] = []
        for row in data:
            name = row.get("name") or row.get("tv_genre_title") or ""
            cmd = row.get("cmd") or ""
            if not name or not cmd:
                continue
            group = row.get("tv_genre_title") or row.get("tv_genre_id") or "Stalker"
            channel = {
                "name": name,
                "group": group,
                "url": "",  # resolved on demand
                "tvg-id": row.get("epg_id", ""),
                "tvg-name": row.get("display_name", name),
                "tvg-logo": row.get("logo", ""),
                "provider-type": "stalker",
                "provider-data": {
                    "cmd": cmd,
                    "use_http_tmp_link": row.get("use_http_tmp_link", 0),
                    "id": row.get("id"),
                    "number": row.get("number"),
                    "allow_timeshift": row.get("allow_timeshift", 0),
                    "archive": row.get("archive", 0)
                }
            }
            if self.cfg.provider_id:
                channel["provider-id"] = self.cfg.provider_id
            if row.get("tv_archive_duration"):
                channel["catchup-days"] = row.get("tv_archive_duration")
            if row.get("allow_timeshift") or row.get("archive"):
                channel["catchup"] = "stalker"
            channels.append(channel)
        epg_urls: List[str] = []
        if self.cfg.auto_epg:
            # Stalker portals expose XMLTV at /portal.php?type=itv&action=get_epg_info&period=...,
            # but many also host XMLTV at /xmltv.php. Provide best-effort default.
            epg_urls.append(f"{self._base}/xmltv.php")
        return channels, epg_urls

    def resolve_stream(self, provider_data: Dict, timeout: int = 30) -> str:
        self._ensure_token()
        cmd = provider_data.get("cmd")
        if not cmd:
            raise ProviderError(_("Channel missing command reference"))
        params = {
            "type": "itv",
            "action": "create_link",
            "cmd": cmd,
            "JsHttpRequest": "1-xml"
        }
        payload = self._portal_call(params, timeout=timeout)
        link = payload.get("js", {}).get("cmd") or payload.get("cmd")
        if not link:
            raise ProviderError(_("Portal did not return stream URL"))
        # Responses are usually prefixed with ffmpeg/auto tokens. Strip them while keeping the actual URL.
        for prefix in ("ffmpeg ", "auto "):
            if link.startswith(prefix):
                link = link[len(prefix):]
        return link

    def resolve_catchup(self, provider_data: Dict, start: str, duration: int) -> str:
        self._ensure_token()
        cmd = provider_data.get("cmd")
        if not cmd:
            raise ProviderError(_("Channel missing command reference"))
        params = {
            "type": "itv",
            "action": "create_link",
            "cmd": cmd,
            "JsHttpRequest": "1-xml",
            "download": "0",
            "save": "0",
            "series": "1",
            "forced_storage": "0",
            "start": start,
            "duration": str(duration)
        }
        payload = self._portal_call(params)
        link = payload.get("js", {}).get("cmd") or payload.get("cmd")
        if not link:
            raise ProviderError(_("Portal did not provide catch-up link"))
        for prefix in ("ffmpeg ", "auto "):
            if link.startswith(prefix):
                link = link[len(prefix):]
        return link

    def describe(self) -> str:
        label = self.cfg.name or urllib.parse.urlparse(self._base).netloc
        return f"Stalker Portal ({label})"


def generate_provider_id() -> str:
    return uuid.uuid4().hex
