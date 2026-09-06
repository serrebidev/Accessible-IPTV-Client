"""Tests for catch-up URL construction in main.IPTVClient.

Covers both catch-up styles found in the wild:

* path style (``catchup="default"``, ``catchup-source="/<stream-id>"``),
* EPG template style (``catchup="append"``, ``catchup-source="?utc=${start}&lutc=${timestamp}"``),
  as shipped by teleelevidenie.com, which the old builder mangled into a
  relative path and got 403 from.
"""

import datetime
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402


def _client():
    return SimpleNamespace(
        _extract_stream_id=lambda url: main.IPTVClient._extract_stream_id(None, url)
    )


def _utc(*args):
    return datetime.datetime(*args, tzinfo=datetime.timezone.utc)


START = _utc(2026, 9, 6, 12, 0, 0)
END = _utc(2026, 9, 6, 13, 0, 0)


class TestExpandCatchupTemplate:
    def test_template_style_is_detected(self):
        assert main._expand_catchup_template("?utc=${start}&lutc=${timestamp}", START, END) is not None

    def test_plain_path_is_not_a_template(self):
        assert main._expand_catchup_template("/1234", START, END) is None
        assert main._expand_catchup_template("", START, END) is None

    def test_epoch_tokens_render_utc_epochs(self):
        expanded = main._expand_catchup_template("?utc=${start}&lutc=${timestamp}", START, END)
        start_epoch = str(int(START.timestamp()))
        # ${timestamp} renders the real current time; only check its presence.
        assert expanded.startswith(f"?utc={start_epoch}&lutc=")
        assert expanded != f"?utc={start_epoch}&lutc="

    def test_kodi_brace_tokens(self):
        expanded = main._expand_catchup_template("?utc={utc}&lutc={lutc}", START, END)
        assert expanded.startswith(f"?utc={int(START.timestamp())}&lutc=")

    def test_offset_shifts_rendered_instants(self):
        expanded = main._expand_catchup_template("?b={utc}", START, END, offset_hours=2)
        assert expanded == f"?b={int(START.timestamp()) - 7200}"


class TestGenericCatchupUrl:
    def test_append_template_uses_channel_url(self):
        client = _client()
        channel = {
            "url": "https://host/live/1234/index.m3u8",
            "catchup": "append",
            "catchup-source": "?utc=${start}&lutc=${timestamp}",
        }
        url = main.IPTVClient._build_generic_catchup_url(client, channel, START, END)
        assert url.startswith("https://host/live/1234/index.m3u8?utc=")
        assert "lutc=" in url
        # The old broken form must not come back.
        assert f"/{int(START.timestamp())}/" not in url

    def test_append_template_keeps_existing_query(self):
        client = _client()
        channel = {
            "url": "https://host/live/1234?token=x",
            "catchup-source": "?utc=${start}",
        }
        url = main.IPTVClient._build_generic_catchup_url(client, channel, START, END)
        assert url == f"https://host/live/1234?token=x&utc={int(START.timestamp())}"

    def test_path_style_still_builds_segments(self):
        client = _client()
        channel = {
            "url": "http://host:8080/live/user/pass/1234.ts",
            "catchup": "default",
            "catchup-source": "http://host:8080",
        }
        url = main.IPTVClient._build_generic_catchup_url(client, channel, START, END)
        # start_token is rendered in the machine's local time; duration is UTC.
        assert url.startswith("http://host:8080/1234/")
        assert url.endswith("/60/")

    def test_url_pipe_modifier_not_duplicated(self):
        client = _client()
        channel = {
            "url": "https://host/live/1234.m3u8|User-Agent=Agent",
            "catchup-source": "?utc=${start}",
            "http-user-agent": "Other",
        }
        url = main.IPTVClient._build_generic_catchup_url(client, channel, START, END)
        assert url.count("|") == 1

    def test_offset_hours_applied(self):
        client = _client()
        channel = {
            "url": "https://host/live/1234",
            "catchup-source": "?utc=${start}",
            "catchup-offset": "2",
        }
        url = main.IPTVClient._build_generic_catchup_url(client, channel, START, END)
        assert url == f"https://host/live/1234?utc={int(START.timestamp()) - 7200}"
