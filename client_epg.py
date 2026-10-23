"""Guide rows and which stream a programme should play.

Split out of main.IPTVClient: the row keys, the on-air formatting and the
live/catch-up URL resolution. IPTVClient inherits EpgRoutingMixin, so every
call site and main.IPTVClient.<name> still resolves.
"""

import datetime
from typing import Dict, Optional

from catchup_urls import _implicit_catchup_source, _positive_timeshift_days
from channel_names import canonicalize_name
from i18n import gettext as _
from options import utc_to_local
from providers import ProviderError


def _now_playing_key(channel: Dict[str, str]) -> str:
    """Cache key for a channel's on-air row label and description.

    The normalized name alone is not enough: providers carry several channels
    of one name with different guides, and all of them showed the first one's
    programme. The tvg-id tells them apart.
    """
    raw_name = str(channel.get("name") or "")
    # Names made only of strip tags ("USA", "CAR") canonicalize to nothing.
    name_key = canonicalize_name(raw_name) or raw_name.strip().lower()
    tvg_id = str(channel.get("tvg-id") or "").strip().lower()
    if name_key and tvg_id:
        return f"{name_key}\x1f{tvg_id}"
    return name_key


class EpgRoutingMixin:

    def _fmt_time(self, s):
        # s: "YYYYMMDDHHMMSS" (UTC)
        try:
            dt = datetime.datetime.strptime(s, "%Y%m%d%H%M%S").replace(tzinfo=datetime.timezone.utc)
            local = utc_to_local(dt)
            return local.strftime("%H:%M")
        except Exception:
            return "?"

    def _utc_now(self) -> datetime.datetime:
        try:
            return datetime.datetime.now(datetime.timezone.utc)
        except Exception:
            return datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)

    def on_highlight(self):
        self._update_recording_menu_state()
        i = self.channel_list.GetSelection()
        if i < 0 or i >= len(self.displayed):
            self.url_display.SetValue("")
            self._set_episode_description("")
            return
        item = self.displayed[i]
        if item["type"] == "vod_series":
            self.url_display.SetValue("")
            self._set_episode_description("")
            return
        if item["type"] in ("vod_back", "vod_info"):
            self.url_display.SetValue("")
            self._set_episode_description("")
            return
        if item["type"] == "channel":
            ch = item["data"]
            self.url_display.SetValue(ch.get("url", ""))
            # The description field reads the on-air programme of the
            # highlighted channel from the bulk now-playing cache.
            self._set_episode_description(getattr(
                self, "_now_playing_descriptions", {}).get(
                _now_playing_key(ch), ""))
            # Warm the media-type cache (issue #33) once the selection
            # settles, so the Recording Format menu and recording paths know
            # audio-only streams before they are used.
            self._schedule_media_probe(ch)
        elif item["type"] == "epg":
            self.url_display.SetValue("")
            r = item["data"]
            # The same (memoized) match the recording menu just made, so the
            # URL shown is the channel that playing or recording this row uses.
            ch = self._find_channel_for_epg(r)
            self.url_display.SetValue(ch.get("url", "") if ch else "")
            self._set_episode_description(r.get("description") or "")

    def _epg_msg_from_tuple(self, now, nxt):
        def localfmt(dt):
            local = utc_to_local(dt)
            return local.strftime('%H:%M')
        def description(show):
            return (show.get('description') or "").strip() if show else ""
        msg = ""
        if now:
            msg += _("Now: {title} ({start} – {end})").format(
                title=now['title'], start=localfmt(now['start']), end=localfmt(now['end']))
            desc = description(now)
            if desc:
                msg += "\n" + desc
        elif nxt:
            msg += _("Starts at {start}: {title}").format(
                start=localfmt(nxt['start']), title=nxt['title'])
            desc = description(nxt)
            if desc:
                msg += "\n" + desc
        else:
            msg += _("No program currently airing.")
        if nxt:
            msg += "\n" + _("Next: {title} ({start} – {end})").format(
                title=nxt['title'], start=localfmt(nxt['start']), end=localfmt(nxt['end']))
            if now:
                # The description of the current show was already shown above.
                desc = description(nxt)
                if desc:
                    msg += "\n" + desc
        return msg

    def _find_channel_for_epg(self, show: Dict[str, str]) -> Optional[Dict[str, str]]:
        return self._find_matching_channel_for_program(show)

    def _channel_has_catchup(self, channel: Dict[str, str]) -> bool:
        if channel.get("catchup-source") or channel.get("catchup"):
            return True
        if _implicit_catchup_source(channel):
            return True
        if channel.get("provider-type") == "stalker":
            pdata = channel.get("provider-data") or {}
            return bool(pdata.get("allow_timeshift") or pdata.get("archive"))
        return False

    def _parse_epg_time(self, value: str) -> datetime.datetime:
        dt = datetime.datetime.strptime(value, "%Y%m%d%H%M%S")
        return dt.replace(tzinfo=datetime.timezone.utc)

    def _resolve_show_url(self, channel: Dict[str, str], show: Dict[str, str]) -> tuple:
        start_dt = self._parse_epg_time(show.get("start"))
        end_dt = self._parse_epg_time(show.get("end"))
        now = datetime.datetime.now(datetime.timezone.utc)

        if start_dt <= now <= end_dt:
            return self._resolve_live_url(channel), False

        if end_dt < now:
            if not self._channel_has_catchup(channel):
                raise ProviderError("This channel does not provide catch-up streaming.")
            if not self._within_catchup_window(channel, start_dt):
                raise ProviderError("This programme is older than the catch-up window allows.")
            url = self._resolve_catchup_url(channel, start_dt, end_dt)
            if not url:
                raise ProviderError("Unable to construct catch-up URL for this programme.")
            return url, True

        # Future programme: return live stream so playback starts when available.
        return self._resolve_live_url(channel), False

    def _within_catchup_window(self, channel: Dict[str, str], start_dt: datetime.datetime) -> bool:
        days = channel.get("catchup-days") or _positive_timeshift_days(channel)
        if not days:
            return True
        try:
            span = int(float(days))
        except (TypeError, ValueError):
            return True
        now = datetime.datetime.now(datetime.timezone.utc)
        return start_dt >= now - datetime.timedelta(days=span)

    def _resolve_live_url(self, channel: Dict[str, str]) -> str:
        url = channel.get("url", "")
        provider_type = channel.get("provider-type")
        provider_id = channel.get("provider-id")

        if provider_type == "stalker":
            if not provider_id:
                raise ProviderError("Stalker portal entry missing provider identifier.")
            client = self.provider_clients.get(provider_id)
            if not client:
                raise ProviderError("Stalker portal client is not initialized.")
            pdata = channel.get("provider-data") or {}
            url = client.resolve_stream(pdata)
            return url

        return url

    def _resolve_catchup_url(self, channel: Dict[str, str], start_dt: datetime.datetime, end_dt: datetime.datetime) -> str:
        # A guide row with its end before its start (or a zero length) made every
        # archive request ask for a window that cannot exist: the provider
        # answered 404 and the app retried a download that could never work.
        if end_dt <= start_dt:
            raise ProviderError(_("This programme's start and end times are invalid."))
        provider_type = channel.get("provider-type")
        provider_id = channel.get("provider-id")
        if provider_type == "stalker" and provider_id:
            client = self.provider_clients.get(provider_id)
            if not client:
                raise ProviderError("Stalker portal client is not initialized.")
            pdata = channel.get("provider-data") or {}
            start_local = utc_to_local(start_dt)
            duration = max(1, int((end_dt - start_dt).total_seconds() // 60))
            start_str = start_local.strftime("%Y-%m-%d:%H-%M")
            return client.resolve_catchup(pdata, start_str, duration)

        return self._build_generic_catchup_url(channel, start_dt, end_dt)
