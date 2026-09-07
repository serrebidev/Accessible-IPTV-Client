"""Tests for the fast direct-download URL derivation."""

import catchup_direct


def test_candidates_swap_a_dated_m3u8_for_its_mp4():
    url = "https://host/seg/index-1700000000-60.m3u8?token=abc"
    out = catchup_direct.candidate_direct_urls(url, 1700000099, 90)
    # The playlist's own numbers are the server's truth and come first.
    assert out[0] == "https://host/seg/index-1700000000-60.mp4?token=abc"
    assert "https://host/seg/index-1700000099-90.mp4?token=abc" in out


def test_candidates_keep_the_query_string():
    url = "https://host/dir/index.m3u8?token=abc"
    out = catchup_direct.candidate_direct_urls(url, 1000, 60)
    assert all("token=abc" in candidate for candidate in out)


def test_candidates_try_the_first_path_segment():
    url = "https://host/deep/dir/index.m3u8?utc=1000&dur=60"
    out = catchup_direct.candidate_direct_urls(url, 1000, 60)
    assert "https://host/deep/index-1000-60.mp4?utc=1000&dur=60" in out


def test_candidates_have_no_duplicates():
    url = "https://host/one/index-1000-60.m3u8?x=1"
    out = catchup_direct.candidate_direct_urls(url, 1000, 60)
    assert len(out) == len(set(out))


def test_candidates_reject_useless_urls():
    assert catchup_direct.candidate_direct_urls("", 1, 1) == []
    assert catchup_direct.candidate_direct_urls("not a url", 1, 1) == []


def test_media_header_check_rejects_html_fallbacks():
    class Headers:
        def __init__(self, content_type, length=None):
            self._ct = content_type
            self._len = length

        def get(self, name, default=None):
            if name == "Content-Type":
                return self._ct
            if name == "Content-Length":
                return self._len
            return default

    assert catchup_direct._headers_look_like_media(Headers("video/mp4"))
    assert catchup_direct._headers_look_like_media(Headers(""))
    assert not catchup_direct._headers_look_like_media(Headers("text/html"))
    assert not catchup_direct._headers_look_like_media(Headers("application/json"))
