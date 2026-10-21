"""Tests for the channel name normalisation (channel_names.py).

GUI-free and dependency-free, so they run headless and fast. The module is the
single source of truth for how a channel name is normalised and how a country or
group is detected - the playlist, the EPG database and the row labels all use
it, so a wrong answer here shows up everywhere.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from channel_names import (  # noqa: E402
    canonicalize_name,
    extract_group,
    strip_noise_words,
)


def test_a_country_name_is_found():
    assert extract_group("Sky Mix Austria") == "at"
    assert extract_group("Canal 13 Germany") == "de"
    assert extract_group("BBC One United Kingdom") == "uk"


def test_a_leading_code_is_still_a_country():
    """A channel that starts with its country code is how providers name them."""
    assert extract_group("AT Sports 1") == "at"
    assert extract_group("DE Film 2") == "de"
    assert extract_group("NO Sport 1") == "no"


def test_a_parenthesised_code_is_still_a_country():
    assert extract_group("Example TV (DE)") == "de"
    assert extract_group("Example TV (IT)") == "it"


def test_an_ordinary_english_word_is_not_a_country():
    """A bare country code is a country only as a code.

    Matched as a free word it hits ordinary English, and the guide then points
    at the wrong country: "News at Ten" is not Austrian, "No Limits" is not
    Norwegian and "It Always Sunny" is not Italian.
    """
    assert extract_group("News at Ten") == ""
    assert extract_group("No Limits") == ""
    assert extract_group("It Always Sunny") == ""
    assert extract_group("By Example") == ""
    assert extract_group("In the Loop") == ""
    assert extract_group("Is It Cool") == ""
    assert extract_group("Ma Home") == ""


def test_names_are_normalised_the_same_way_everywhere():
    assert canonicalize_name("  Sky   Mix  HD ") == canonicalize_name("Sky Mix HD")
    assert strip_noise_words("Sky Mix HD") == "sky mix"
