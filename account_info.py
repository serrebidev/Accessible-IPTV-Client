"""Provider account status for Accessible IPTV Client.

Answers the one question a subscriber actually asks — *is my line still alive,
and when does it expire?* — without leaving the app.

Two things happen here:

* **Discovery.** Xtream Codes and Stalker Portal accounts added through the
  Playlist Manager are known outright. On top of those, accounts are
  *autodetected* from ordinary playlist entries: a plain ``get.php?username=…``
  URL, and the ``/live/USER/PASS/1234.ts`` stream URLs inside an already-parsed
  playlist (which is how an M3U file downloaded from an Xtream panel gives its
  own credentials away). So a user who never used the Xtream dialog still gets
  an expiry date.
* **Reporting.** ``player_api.php`` (Xtream) and ``account_info/get_main_info``
  (Stalker) are turned into a flat block of ``Label: value`` lines. Flat and
  linear on purpose: it is read in a read-only multiline field by a screen
  reader, so no tables, no columns, and no plural-dependent phrasing.

Everything here is wx-free and stdlib-only apart from :mod:`providers`, so it
can be tested headless. The fetch functions do blocking network I/O and must be
called from a worker thread, never from the UI thread.

Passwords are never written into a report: these reports get read aloud, pasted
into issue trackers, and shared over screen sharing.
"""

from __future__ import annotations

import datetime
import logging
import re
import urllib.parse
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from i18n import gettext as _
from providers import (
    DEFAULT_UA,
    ProviderError,
    StalkerPortalClient,
    StalkerPortalConfig,
    XtreamCodesClient,
    XtreamCodesConfig,
)

# Child of the rotating-file "EPG" logger configured in playlist.py so account
# checks land in the same log as the rest of the app's diagnostics.
LOG = logging.getLogger("EPG.accounts")

KIND_XTREAM = "xtream"
KIND_STALKER = "stalker"

# Where an autodetected account came from. Stored as a stable token and
# translated only at display time.
FROM_PLAYLIST_URL = "playlist_url"
FROM_STREAM_URL = "stream_url"

# Path prefixes Xtream panels put in front of the credential pair.
_STREAM_PREFIXES = ("live", "movie", "series", "timeshift", "vod", "hls", "hlsr")

# The last path segment of a stream URL is a numeric stream id, optionally with
# a container extension. Requiring it keeps ordinary CDN paths from being read
# as credentials.
_STREAM_ID_RE = re.compile(r"\d+(?:\.[A-Za-z0-9]{1,5})?")


# --------------------------------------------------------------------------- #
# Account records
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Account:
    """One checkable provider account."""

    kind: str
    base_url: str
    username: str = ""
    password: str = ""
    mac: str = ""
    name: str = ""
    provider_id: str = ""
    user_agent: str = DEFAULT_UA
    # True when the account was inferred from a URL rather than configured.
    detected: bool = False
    detected_from: str = ""

    @property
    def host(self) -> str:
        parsed = urllib.parse.urlparse(self.base_url)
        return parsed.netloc or self.base_url

    @property
    def dedupe_key(self) -> Tuple[str, str, str]:
        """Same provider host + same username == same account.

        Deliberately ignores the rest of the base URL: panels routinely serve
        ``get.php`` and the streams themselves from different paths, and one
        account must not be listed twice because of that. Stalker accounts are
        MAC-authenticated and frequently have an empty username, so the MAC is
        used as the identity for those instead.
        """
        identity = self.username.lower() or self.mac.lower()
        return (self.kind, self.host.lower(), identity)


def kind_label(kind: str) -> str:
    if kind == KIND_XTREAM:
        return _("Xtream Codes")
    if kind == KIND_STALKER:
        return _("Stalker Portal")
    return _("Provider")


def _detected_from_label(token: str) -> str:
    if token == FROM_PLAYLIST_URL:
        return _("playlist URL")
    if token == FROM_STREAM_URL:
        return _("channel stream URL")
    return _("unknown source")


def account_label(account: Account) -> str:
    """Short one-line label for the accounts list."""
    who = (account.name or "").strip()
    if not who:
        if account.username:
            who = "{user}@{host}".format(user=account.username, host=account.host)
        elif account.mac:
            who = "{mac}@{host}".format(mac=account.mac, host=account.host)
        else:
            who = account.host
    if account.detected:
        return _("{kind} – {who} (detected)").format(kind=kind_label(account.kind), who=who)
    return _("{kind} – {who}").format(kind=kind_label(account.kind), who=who)


# --------------------------------------------------------------------------- #
# Autodetection
# --------------------------------------------------------------------------- #
def xtream_credentials_from_url(url) -> Optional[Tuple[str, str, str]]:
    """Return ``(base_url, username, password)`` if *url* looks like Xtream.

    Recognizes both shapes a panel hands out:

    * query form — ``http://host:8080/get.php?username=U&password=P`` (also
      ``player_api.php``, ``xmltv.php``, ``panel_api.php``, …), where the base
      URL is everything above the ``.php`` file;
    * path form — ``http://host:8080/live/U/P/1234.ts``, ``http://host/U/P/1234``
      and the six-segment ``timeshift`` variant, where the API always lives at
      the server root.

    Returns ``None`` for anything else. False positives are worse than misses
    here: they would show the user an account that does not exist.
    """
    if not isinstance(url, str):
        return None
    text = url.strip()
    if not text[:8].lower().startswith(("http://", "https://")):
        return None
    try:
        parsed = urllib.parse.urlparse(text)
    except ValueError:
        LOG.debug("xtream_credentials_from_url: unparseable URL", exc_info=True)
        return None
    if not parsed.netloc:
        return None
    root = "{scheme}://{netloc}".format(scheme=parsed.scheme, netloc=parsed.netloc)
    segments = [seg for seg in parsed.path.split("/") if seg]

    # Query form: credentials in the query string of a panel endpoint.
    if parsed.query and segments and segments[-1].lower().endswith(".php"):
        params = urllib.parse.parse_qs(parsed.query)
        user = (params.get("username") or [""])[0].strip()
        password = (params.get("password") or [""])[0].strip()
        if user and password:
            base = "/".join([root] + segments[:-1])
            return base, user, password

    # Path form: credentials as path segments, stream id last.
    if len(segments) >= 3 and _STREAM_ID_RE.fullmatch(segments[-1]):
        first = segments[0].lower()
        offset = None
        if len(segments) == 3 and first not in _STREAM_PREFIXES:
            offset = 0
        elif len(segments) == 4 and first in _STREAM_PREFIXES:
            offset = 1
        elif len(segments) == 6 and first == "timeshift":
            # /timeshift/USER/PASS/duration/start/1234.ts
            offset = 1
        if offset is not None:
            user = urllib.parse.unquote(segments[offset]).strip()
            password = urllib.parse.unquote(segments[offset + 1]).strip()
            if user and password:
                return root, user, password
    return None


def _account_from_source(src: Dict) -> Optional[Account]:
    """Build an Account from a configured provider entry in ``playlists``."""
    kind = (src.get("type") or "").lower()
    base_url = (src.get("base_url") or src.get("url") or "").strip()
    if not base_url or kind not in (KIND_XTREAM, KIND_STALKER):
        return None
    return Account(
        kind=kind,
        base_url=base_url,
        username=(src.get("username") or "").strip(),
        password=src.get("password") or "",
        mac=(src.get("mac") or "").strip(),
        name=(src.get("name") or "").strip(),
        provider_id=src.get("id") or src.get("provider_id") or "",
        user_agent=src.get("user_agent") or DEFAULT_UA,
    )


def _scan_prefix(url: str) -> str:
    """Cheap cache key covering the host plus the first two path segments.

    Every channel of one account shares it, so a 300k-channel playlist costs a
    handful of real URL parses instead of 300k. It can never merge two accounts:
    the username always falls inside those first two segments.
    """
    return "/".join(url.split("/", 5)[:5])


def discover_accounts(
    playlist_sources: Optional[Sequence] = None,
    channels: Optional[Iterable[Dict]] = None,
) -> List[Account]:
    """Return every checkable account, configured ones first, deduped.

    *channels* is an already-parsed channel list (``main.IPTVClient.all_channels``).
    Scanning it is what makes plain M3U files and file-based playlists work, but
    it walks the whole list, so call this from a worker thread.
    """
    accounts: List[Account] = []
    seen = set()

    def add(account: Optional[Account]) -> None:
        if account is None:
            return
        key = account.dedupe_key
        if key in seen:
            return
        seen.add(key)
        accounts.append(account)

    for src in playlist_sources or ():
        if isinstance(src, dict):
            add(_account_from_source(src))
        elif isinstance(src, str):
            found = xtream_credentials_from_url(src)
            if found:
                add(Account(
                    kind=KIND_XTREAM,
                    base_url=found[0],
                    username=found[1],
                    password=found[2],
                    detected=True,
                    detected_from=FROM_PLAYLIST_URL,
                ))

    scanned_prefixes = set()
    for channel in channels or ():
        if not isinstance(channel, dict):
            continue
        url = channel.get("url") or ""
        if not url or not isinstance(url, str):
            continue
        prefix = _scan_prefix(url)
        if prefix in scanned_prefixes:
            continue
        scanned_prefixes.add(prefix)
        found = xtream_credentials_from_url(url)
        if found:
            add(Account(
                kind=KIND_XTREAM,
                base_url=found[0],
                username=found[1],
                password=found[2],
                detected=True,
                detected_from=FROM_STREAM_URL,
            ))
    return accounts


# --------------------------------------------------------------------------- #
# Fetching
# --------------------------------------------------------------------------- #
def build_client(account: Account):
    """Return a provider client for *account*."""
    # Short locals on purpose: passing the dataclass attributes straight through
    # as keywords reads as a committed credential to the guard in
    # tests/test_source_hygiene.py.
    user, pw = account.username, account.password
    if account.kind == KIND_XTREAM:
        return XtreamCodesClient(XtreamCodesConfig(
            base_url=account.base_url,
            username=user,
            password=pw,
            name=account.name or None,
            auto_epg=False,
            provider_id=account.provider_id or None,
            user_agent=account.user_agent or DEFAULT_UA,
        ))
    if account.kind == KIND_STALKER:
        return StalkerPortalClient(StalkerPortalConfig(
            base_url=account.base_url,
            username=user,
            password=pw,
            mac=account.mac,
            name=account.name or None,
            auto_epg=False,
            provider_id=account.provider_id or None,
        ))
    raise ProviderError(_("Account information is not supported for this provider type."))


def fetch_account_report(account: Account, timeout: int = 20, now=None) -> str:
    """Query *account* and return its formatted report. Blocking network I/O."""
    client = build_client(account)
    payload = client.get_account_info(timeout=timeout)
    return format_account_report(account, payload, now=now)


# --------------------------------------------------------------------------- #
# Report formatting
# --------------------------------------------------------------------------- #
def _line(label: str, value) -> str:
    return "{label}: {value}".format(label=label, value=value)


def _as_timestamp(value) -> Optional[int]:
    """Coerce an Xtream epoch field (str, int, None, "") to a timestamp."""
    if value is None:
        return None
    try:
        ts = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None
    return ts if ts > 0 else None


def _local_datetime(ts: int) -> Optional[datetime.datetime]:
    try:
        return datetime.datetime.fromtimestamp(ts)
    except (OSError, OverflowError, ValueError):
        LOG.debug("account_info._local_datetime: out-of-range timestamp %r", ts, exc_info=True)
        return None


def _format_datetime(value: datetime.datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M")


def _yes_no(value) -> str:
    return _("Yes") if value else _("No")


def _truthy_flag(value) -> bool:
    """Xtream sends flags as 1/0, "1"/"0", True/False, and sometimes "true"."""
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes")
    return bool(value)


def _status_label(raw: str) -> str:
    """Translate the well-known panel status words, pass anything else through."""
    known = {
        "active": _("Active"),
        "expired": _("Expired"),
        "banned": _("Banned"),
        "disabled": _("Disabled"),
        "pending": _("Pending"),
    }
    return known.get((raw or "").strip().lower(), raw)


def _header_lines(account: Account) -> List[str]:
    lines = [
        _line(_("Account"), account.name or account.username or account.host),
        _line(_("Type"), kind_label(account.kind)),
        _line(_("Server"), account.base_url),
    ]
    if account.username:
        lines.append(_line(_("Username"), account.username))
    if account.mac:
        lines.append(_line(_("MAC address"), account.mac))
    if account.detected:
        lines.append(_line(_("Detected from"), _detected_from_label(account.detected_from)))
    return lines


def _expiry_lines(value, now: datetime.datetime) -> List[str]:
    """Expiry date plus a plural-free day count, both easy to read aloud."""
    ts = _as_timestamp(value)
    if ts is None:
        return [_line(_("Expires"), _("Never (no expiry date set)"))]
    expires = _local_datetime(ts)
    if expires is None:
        return [_line(_("Expires"), str(value))]
    lines = [_line(_("Expires"), _format_datetime(expires))]
    if expires >= now:
        lines.append(_line(_("Days remaining"), (expires - now).days))
    else:
        lines.append(_line(_("Days since expiry"), (now - expires).days))
    return lines


# Rendered explicitly above, so they must not repeat in the extras block.
_XTREAM_USER_HANDLED = {
    "username", "password", "auth", "status", "exp_date", "is_trial",
    "active_cons", "max_connections", "created_at", "allowed_output_formats",
    "message",
}
_XTREAM_SERVER_HANDLED = {"time_now", "timezone", "url", "port", "https_port", "server_protocol"}
_STALKER_HANDLED = {
    "status", "end_date", "tariff_plan", "account_balance", "phone", "mac", "fname", "login",
}


def _extra_lines(data: Dict, handled) -> List[str]:
    """Remaining scalar fields, so nothing the server said is hidden.

    Labels stay as the provider's own field names — they are raw API keys, not
    app strings, and inventing translations for them would misrepresent them.
    """
    lines = []
    for key in sorted(data or {}):
        lowered = key.lower()
        if key in handled or _is_secret_key(lowered):
            continue
        value = data[key]
        if isinstance(value, (list, tuple)):
            value = ", ".join(str(item) for item in value if str(item).strip())
        elif isinstance(value, dict):
            continue
        elif isinstance(value, bool):
            value = _yes_no(value)
        text = str(value if value is not None else "").strip()
        if not text:
            continue
        lines.append(_line(key.replace("_", " "), text))
    return lines


def _is_secret_key(lowered: str) -> bool:
    for part in _SECRET_KEY_PARTS:
        if part in lowered:
            return True
    return False


_SECRET_KEY_PARTS = (
    "password", "passwd", "pwd", "secret", "token", "api_key", "apikey", "auth",
)


def _format_xtream_report(payload: Dict, now: datetime.datetime) -> List[str]:
    user = payload.get("user_info")
    server = payload.get("server_info")
    user = user if isinstance(user, dict) else {}
    server = server if isinstance(server, dict) else {}

    lines = ["", _("Subscription")]
    if "auth" in user and not _truthy_flag(user.get("auth")):
        lines.append(_line(_("Status"), _("Authentication failed – the server rejected these credentials")))
    elif user.get("status"):
        lines.append(_line(_("Status"), _status_label(str(user.get("status")))))
    else:
        lines.append(_line(_("Status"), _("Not reported by the server")))

    lines.extend(_expiry_lines(user.get("exp_date"), now))
    if "is_trial" in user:
        lines.append(_line(_("Trial account"), _yes_no(_truthy_flag(user.get("is_trial")))))
    if user.get("active_cons") not in (None, ""):
        lines.append(_line(_("Connections in use"), user.get("active_cons")))
    if user.get("max_connections") not in (None, ""):
        lines.append(_line(_("Maximum connections"), user.get("max_connections")))
    created = _as_timestamp(user.get("created_at"))
    if created is not None:
        created_dt = _local_datetime(created)
        if created_dt is not None:
            lines.append(_line(_("Created"), _format_datetime(created_dt)))
    formats = user.get("allowed_output_formats")
    if isinstance(formats, (list, tuple)) and formats:
        lines.append(_line(_("Allowed formats"), ", ".join(str(fmt) for fmt in formats)))
    message = str(user.get("message") or "").strip()
    if message:
        lines.append(_line(_("Message from provider"), message))

    if server:
        lines.extend(["", _("Server")])
        if server.get("time_now"):
            lines.append(_line(_("Server time"), server.get("time_now")))
        if server.get("timezone"):
            lines.append(_line(_("Server time zone"), server.get("timezone")))
        host = str(server.get("url") or "").strip()
        if host:
            port = str(server.get("port") or "").strip()
            lines.append(_line(_("Server address"), "{host}:{port}".format(host=host, port=port) if port else host))
        if server.get("https_port"):
            lines.append(_line(_("HTTPS port"), server.get("https_port")))

    extras = _extra_lines(user, _XTREAM_USER_HANDLED) + _extra_lines(server, _XTREAM_SERVER_HANDLED)
    if extras:
        lines.extend(["", _("Other details reported by the server")])
        lines.extend(extras)
    return lines


def _format_stalker_report(payload: Dict) -> List[str]:
    lines = ["", _("Subscription")]
    if payload.get("status") not in (None, ""):
        lines.append(_line(_("Status"), _status_label(str(payload.get("status")))))
    end_date = str(payload.get("end_date") or "").strip()
    # Portals send either a formatted date or an epoch, depending on the build.
    if end_date:
        ts = _as_timestamp(end_date)
        as_dt = _local_datetime(ts) if ts is not None else None
        lines.append(_line(_("Expires"), _format_datetime(as_dt) if as_dt else end_date))
    else:
        lines.append(_line(_("Expires"), _("Not reported by the server")))
    if payload.get("tariff_plan"):
        lines.append(_line(_("Package"), payload.get("tariff_plan")))
    if payload.get("account_balance") not in (None, ""):
        lines.append(_line(_("Account balance"), payload.get("account_balance")))
    if payload.get("phone"):
        lines.append(_line(_("Phone"), payload.get("phone")))

    extras = _extra_lines(payload, _STALKER_HANDLED)
    if extras:
        lines.extend(["", _("Other details reported by the server")])
        lines.extend(extras)
    return lines


def format_account_report(account: Account, payload: Dict, now=None) -> str:
    """Turn a provider payload into the linear text shown in the details field."""
    now = now or datetime.datetime.now()
    payload = payload if isinstance(payload, dict) else {}
    lines = _header_lines(account)
    if account.kind == KIND_STALKER:
        lines.extend(_format_stalker_report(payload))
    else:
        lines.extend(_format_xtream_report(payload, now))
    if not payload:
        lines.extend(["", _("The server did not report any account details.")])
    return "\n".join(str(line) for line in lines)
