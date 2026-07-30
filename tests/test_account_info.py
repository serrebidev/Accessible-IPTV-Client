"""Tests for provider account discovery and status reporting (account_info.py).

GUI-free: the module is deliberately wx-free so the detection heuristic and the
report text can be exercised headless. Every credential here is a dummy.
"""
import datetime
import json
import os
import sys
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import account_info  # noqa: E402
from account_info import (  # noqa: E402
    Account,
    KIND_STALKER,
    KIND_XTREAM,
    account_label,
    discover_accounts,
    format_account_report,
    xtream_credentials_from_url,
)
from providers import XtreamCodesClient, XtreamCodesConfig  # noqa: E402

NOW = datetime.datetime(2026, 7, 29, 12, 0, 0)


# --------------------------------------------------------------------------- #
# URL detection
# --------------------------------------------------------------------------- #
class TestXtreamCredentialsFromUrl:
    def test_get_php_url(self):
        found = xtream_credentials_from_url(
            "http://provider.example.com:8080/get.php?username=testuser&password=testpass&type=m3u_plus&output=ts"
        )
        assert found == ("http://provider.example.com:8080", "testuser", "testpass")

    def test_player_api_url_in_subdirectory(self):
        """The base URL keeps the panel's directory, only the .php file is dropped."""
        found = xtream_credentials_from_url(
            "http://host.example.com/panel/player_api.php?username=testuser&password=testpass"
        )
        assert found == ("http://host.example.com/panel", "testuser", "testpass")

    def test_xmltv_url(self):
        found = xtream_credentials_from_url(
            "https://host.example.com/xmltv.php?username=testuser&password=testpass"
        )
        assert found == ("https://host.example.com", "testuser", "testpass")

    def test_live_stream_url(self):
        found = xtream_credentials_from_url("http://host.example.com:8080/live/testuser/testpass/12345.ts")
        assert found == ("http://host.example.com:8080", "testuser", "testpass")

    def test_bare_stream_url(self):
        found = xtream_credentials_from_url("http://host.example.com/testuser/testpass/12345")
        assert found == ("http://host.example.com", "testuser", "testpass")

    def test_movie_and_series_urls(self):
        for url in (
            "http://host.example.com/movie/testuser/testpass/777.mkv",
            "http://host.example.com/series/testuser/testpass/888.mp4",
        ):
            assert xtream_credentials_from_url(url) == (
                "http://host.example.com", "testuser", "testpass",
            )

    def test_timeshift_url(self):
        found = xtream_credentials_from_url(
            "http://host.example.com/timeshift/testuser/testpass/120/2026-07-29:10-00/4321.ts"
        )
        assert found == ("http://host.example.com", "testuser", "testpass")

    def test_percent_encoded_path_credentials_are_decoded(self):
        found = xtream_credentials_from_url("http://host.example.com/live/user%40mail/p%20w/9.ts")
        assert found == ("http://host.example.com", "user@mail", "p w")

    @pytest.mark.parametrize("url", [
        None,
        "",
        "   ",
        "not a url",
        "/local/path/playlist.m3u",
        "file:///c:/playlists/mine.m3u",
        # A plain hosted playlist carries no credentials.
        "http://host.example.com/playlist.m3u8",
        # Query form needs BOTH fields.
        "http://host.example.com/get.php?username=testuser",
        "http://host.example.com/get.php?password=testpass",
        # Query form only applies to a panel .php endpoint.
        "http://host.example.com/api/list?username=testuser&password=testpass",
        # Last segment is not a stream id.
        "http://host.example.com/hls/channel/index.m3u8",
        # Unknown prefix with too many segments: refuse rather than guess.
        "http://host.example.com/xtream/live/testuser/testpass/1.ts",
        "http://host.example.com/a/b/c/d/1.ts",
        # Two segments cannot hold a credential pair plus an id.
        "http://host.example.com/testuser/12345",
    ])
    def test_non_xtream_urls_are_rejected(self, url):
        assert xtream_credentials_from_url(url) is None

    def test_non_string_input(self):
        assert xtream_credentials_from_url(12345) is None
        assert xtream_credentials_from_url({"url": "http://x/get.php"}) is None


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #
class TestDiscoverAccounts:
    def test_configured_providers(self):
        sources = [
            {
                "type": "xtream",
                "name": "My Provider",
                "base_url": "http://host.example.com:8080",
                "username": "testuser",
                "password": "testpass",
                "id": "abc123",
            },
            {
                "type": "stalker",
                "base_url": "http://portal.example.com/c",
                "username": "portaluser",
                "password": "testpass",
                "mac": "00:1A:79:00:00:01",
            },
        ]
        accounts = discover_accounts(sources)
        assert [a.kind for a in accounts] == [KIND_XTREAM, KIND_STALKER]
        assert accounts[0].name == "My Provider"
        assert accounts[0].provider_id == "abc123"
        assert accounts[0].detected is False
        assert accounts[1].mac == "00:1A:79:00:00:01"

    def test_plain_url_playlist_is_detected(self):
        sources = ["http://host.example.com/get.php?username=testuser&password=testpass"]
        accounts = discover_accounts(sources)
        assert len(accounts) == 1
        assert accounts[0].detected is True
        assert accounts[0].detected_from == account_info.FROM_PLAYLIST_URL
        assert accounts[0].username == "testuser"

    def test_plain_m3u_sources_are_ignored(self):
        sources = ["http://host.example.com/mylist.m3u", r"C:\playlists\local.m3u", 42, None]
        assert discover_accounts(sources) == []

    def test_channels_reveal_the_account(self):
        """An M3U file saved from an Xtream panel gives its credentials away."""
        channels = [
            {"name": "News", "url": "http://host.example.com:8080/live/testuser/testpass/1.ts"},
            {"name": "Sport", "url": "http://host.example.com:8080/live/testuser/testpass/2.ts"},
        ]
        accounts = discover_accounts([], channels)
        assert len(accounts) == 1
        assert accounts[0].detected_from == account_info.FROM_STREAM_URL
        assert accounts[0].base_url == "http://host.example.com:8080"

    def test_configured_account_wins_over_the_same_detected_one(self):
        sources = [{
            "type": "xtream",
            "name": "Configured",
            # Panels commonly serve get.php from a different path than the streams.
            "base_url": "http://host.example.com:8080/panel",
            "username": "testuser",
            "password": "testpass",
        }]
        channels = [{"url": "http://host.example.com:8080/live/testuser/testpass/1.ts"}]
        accounts = discover_accounts(sources, channels)
        assert len(accounts) == 1
        assert accounts[0].name == "Configured"
        assert accounts[0].detected is False

    def test_two_accounts_on_one_host_are_both_found(self):
        """The channel-scan prefix cache must not collapse distinct usernames."""
        channels = [
            {"url": "http://host.example.com/live/userone/testpass/1.ts"},
            {"url": "http://host.example.com/live/userone/testpass/2.ts"},
            {"url": "http://host.example.com/live/usertwo/testpass/3.ts"},
        ]
        accounts = discover_accounts([], channels)
        assert sorted(a.username for a in accounts) == ["userone", "usertwo"]

    def test_bare_form_accounts_on_one_host_are_both_found(self):
        channels = [
            {"url": "http://host.example.com/userone/testpass/1"},
            {"url": "http://host.example.com/usertwo/testpass/2"},
        ]
        accounts = discover_accounts([], channels)
        assert sorted(a.username for a in accounts) == ["userone", "usertwo"]

    def test_malformed_channel_entries_are_skipped(self):
        channels = [None, "string", {}, {"url": None}, {"url": ""}, {"name": "no url"}]
        assert discover_accounts([], channels) == []

    def test_no_sources_at_all(self):
        assert discover_accounts(None, None) == []


class TestAccountLabel:
    def test_configured_label_uses_name(self):
        acc = Account(kind=KIND_XTREAM, base_url="http://host.example.com", username="testuser", name="Fast TV")
        assert account_label(acc) == "Xtream Codes – Fast TV"

    def test_detected_label_is_marked(self):
        acc = Account(
            kind=KIND_XTREAM, base_url="http://host.example.com:8080",
            username="testuser", detected=True,
        )
        label = account_label(acc)
        assert "testuser@host.example.com:8080" in label
        assert "detected" in label

    def test_stalker_label_falls_back_to_mac(self):
        acc = Account(kind=KIND_STALKER, base_url="http://portal.example.com", mac="00:1A:79:00:00:01")
        assert account_label(acc) == "Stalker Portal – 00:1A:79:00:00:01@portal.example.com"


# --------------------------------------------------------------------------- #
# Report formatting
# --------------------------------------------------------------------------- #
def _xtream_account(**kwargs):
    defaults = dict(
        kind=KIND_XTREAM,
        base_url="http://host.example.com:8080",
        username="testuser",
        password="s3cr3tvalue",
        name="Fast TV",
    )
    defaults.update(kwargs)
    return Account(**defaults)


def _payload(**user_overrides):
    user = {
        "username": "testuser",
        "password": "s3cr3tvalue",
        "message": "",
        "auth": 1,
        "status": "Active",
        # 2026-09-01 12:00 UTC, comfortably after NOW.
        "exp_date": str(int(datetime.datetime(2026, 9, 1, 12, 0).timestamp())),
        "is_trial": "0",
        "active_cons": "1",
        "created_at": str(int(datetime.datetime(2025, 1, 15, 9, 30).timestamp())),
        "max_connections": "2",
        "allowed_output_formats": ["m3u8", "ts", "rtmp"],
    }
    user.update(user_overrides)
    return {
        "user_info": user,
        "server_info": {
            "url": "host.example.com",
            "port": "8080",
            "https_port": "8443",
            "server_protocol": "http",
            "timezone": "Europe/London",
            "time_now": "2026-07-29 12:00:00",
            "rtmp_port": "1935",
        },
    }


def _fields(report):
    out = {}
    for line in report.splitlines():
        if ": " in line:
            key, value = line.split(": ", 1)
            out[key] = value
    return out


class TestXtreamReport:
    def test_active_account(self):
        report = format_account_report(_xtream_account(), _payload(), now=NOW)
        fields = _fields(report)
        assert fields["Account"] == "Fast TV"
        assert fields["Type"] == "Xtream Codes"
        assert fields["Server"] == "http://host.example.com:8080"
        assert fields["Username"] == "testuser"
        assert fields["Status"] == "Active"
        assert fields["Expires"].startswith("2026-09-01")
        assert fields["Days remaining"] == "34"
        assert fields["Trial account"] == "No"
        assert fields["Connections in use"] == "1"
        assert fields["Maximum connections"] == "2"
        assert fields["Created"].startswith("2025-01-15")
        assert fields["Allowed formats"] == "m3u8, ts, rtmp"
        assert fields["Server time"] == "2026-07-29 12:00:00"
        assert fields["Server time zone"] == "Europe/London"
        assert fields["Server address"] == "host.example.com:8080"

    def test_password_never_appears(self):
        """These reports get read aloud, pasted into issues, and screen-shared."""
        report = format_account_report(_xtream_account(), _payload(), now=NOW)
        assert "s3cr3tvalue" not in report

    def test_expired_account_counts_days_since(self):
        expired = str(int(datetime.datetime(2026, 7, 19, 12, 0).timestamp()))
        report = format_account_report(
            _xtream_account(), _payload(status="Expired", exp_date=expired), now=NOW)
        fields = _fields(report)
        assert fields["Status"] == "Expired"
        assert fields["Days since expiry"] == "10"
        assert "Days remaining" not in fields

    @pytest.mark.parametrize("value", [None, "", "0", 0])
    def test_missing_expiry_reads_as_never(self, value):
        report = format_account_report(_xtream_account(), _payload(exp_date=value), now=NOW)
        assert _fields(report)["Expires"] == "Never (no expiry date set)"

    def test_failed_auth_is_stated_plainly(self):
        report = format_account_report(
            _xtream_account(), {"user_info": {"auth": 0}}, now=NOW)
        assert "rejected these credentials" in _fields(report)["Status"]

    def test_trial_flag_variants(self):
        for value in ("1", 1, True, "true"):
            report = format_account_report(_xtream_account(), _payload(is_trial=value), now=NOW)
            assert _fields(report)["Trial account"] == "Yes"

    def test_provider_message_is_shown(self):
        report = format_account_report(
            _xtream_account(), _payload(message="Renew before September"), now=NOW)
        assert _fields(report)["Message from provider"] == "Renew before September"

    def test_unknown_fields_are_not_hidden(self):
        """Whatever else the panel reports must still reach the user."""
        report = format_account_report(
            _xtream_account(), _payload(reseller_dns="panel.example.com"), now=NOW)
        fields = _fields(report)
        assert fields["reseller dns"] == "panel.example.com"
        # Server extras land in the same section.
        assert fields["rtmp port"] == "1935"

    def test_detected_accounts_say_where_they_came_from(self):
        account = _xtream_account(
            name="", detected=True, detected_from=account_info.FROM_STREAM_URL)
        fields = _fields(format_account_report(account, _payload(), now=NOW))
        assert fields["Detected from"] == "channel stream URL"
        assert fields["Account"] == "testuser"

    def test_empty_payload_says_so(self):
        report = format_account_report(_xtream_account(), {}, now=NOW)
        assert "did not report any account details" in report

    def test_non_dict_payload_does_not_raise(self):
        report = format_account_report(_xtream_account(), None, now=NOW)
        assert "Fast TV" in report

    def test_out_of_range_expiry_falls_back_to_raw_value(self):
        report = format_account_report(
            _xtream_account(), _payload(exp_date="99999999999999"), now=NOW)
        assert _fields(report)["Expires"] == "99999999999999"


class TestStalkerReport:
    def test_main_info_report(self):
        account = Account(
            kind=KIND_STALKER,
            base_url="http://portal.example.com/c",
            username="portaluser",
            mac="00:1A:79:00:00:01",
            name="My Portal",
        )
        payload = {
            "mac": "00:1A:79:00:00:01",
            "phone": "555-0100",
            "status": "active",
            "end_date": "October 25, 2026",
            "tariff_plan": "Full package",
            "account_balance": "0.00",
            "fname": "Test Account",
            "sn": "SN12345",
        }
        fields = _fields(format_account_report(account, payload, now=NOW))
        assert fields["Type"] == "Stalker Portal"
        assert fields["MAC address"] == "00:1A:79:00:00:01"
        assert fields["Status"] == "Active"
        assert fields["Expires"] == "October 25, 2026"
        assert fields["Package"] == "Full package"
        assert fields["Account balance"] == "0.00"
        assert fields["Phone"] == "555-0100"
        assert fields["sn"] == "SN12345"

    def test_epoch_end_date_is_formatted(self):
        account = Account(kind=KIND_STALKER, base_url="http://portal.example.com", mac="00:1A:79:00:00:01")
        end = str(int(datetime.datetime(2026, 10, 25, 8, 0).timestamp()))
        fields = _fields(format_account_report(account, {"end_date": end}, now=NOW))
        assert fields["Expires"] == "2026-10-25 08:00"

    def test_missing_end_date(self):
        account = Account(kind=KIND_STALKER, base_url="http://portal.example.com", mac="00:1A:79:00:00:01")
        fields = _fields(format_account_report(account, {"status": "active"}, now=NOW))
        assert fields["Expires"] == "Not reported by the server"


# --------------------------------------------------------------------------- #
# Client plumbing
# --------------------------------------------------------------------------- #
class TestFetching:
    def test_build_client_types(self):
        xtream = account_info.build_client(_xtream_account())
        assert isinstance(xtream, XtreamCodesClient)
        # Account checks must never drag the provider's XMLTV in as a side effect.
        assert xtream.cfg.auto_epg is False

    def test_build_client_rejects_unknown_kind(self):
        from providers import ProviderError

        with pytest.raises(ProviderError):
            account_info.build_client(Account(kind="carrier-pigeon", base_url="http://x"))

    def test_fetch_account_report_uses_the_client(self):
        client = Mock()
        client.get_account_info.return_value = _payload()
        with patch.object(account_info, "build_client", return_value=client):
            report = account_info.fetch_account_report(_xtream_account(), timeout=5, now=NOW)
        client.get_account_info.assert_called_once_with(timeout=5)
        assert "Days remaining: 34" in report

    @patch("urllib.request.urlopen")
    def test_xtream_get_account_info_calls_player_api_without_action(self, mock_urlopen):
        response = Mock()
        response.read.return_value = json.dumps(_payload()).encode("utf-8")
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        mock_urlopen.return_value = response

        client = XtreamCodesClient(XtreamCodesConfig(
            base_url="http://host.example.com:8080", username="testuser", password="testpass"))
        payload = client.get_account_info()

        assert payload["user_info"]["status"] == "Active"
        requested = mock_urlopen.call_args[0][0].full_url
        assert "player_api.php" in requested
        assert "action=" not in requested


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
