"""Audio-track matching shared by the built-in player and recordings.

Free of wx and libVLC, so a recording can pick the track the player would
play without loading the player.
"""

import logging
import re
from typing import List, Optional, Sequence, Tuple

LOG = logging.getLogger(__name__)


# Track names that mean "audio description" at the providers seen in the wild. The
# list is deliberately multilingual, because the user who needs this feature is the
# one who cannot see the track menu to work out what the provider called it, and
# German AD tracks are labelled "Hoerfilm" rather than anything containing
# "description". Users can add their own wording in Options > Preferred Audio Track.
AUDIO_DESCRIPTION_KEYWORDS = (
    "audio description",
    "audiodescription",
    "audio descriptive",
    "descriptive audio",
    "described video",
    "description",
    "descriptive",
    "described",
    "audiodeskription",
    "hoerfilm",
    "hörfilm",
    "audiodeskrypcja",
    "audiovision",
    "descripcion",
    "descripción",
    "descrizione",
    "descrição",
    "dvs",
    "ad",
    # DVB flags a described track "visual impaired", and ffmpeg reports it so.
    "visual impaired",
    "visually impaired",
)

# Lower-cased view of AUDIO_DESCRIPTION_KEYWORDS for membership tests; defined
# after the tuple itself.
_AD_KEYWORD_SET = {k.lower() for k in AUDIO_DESCRIPTION_KEYWORDS}
# Below this length a keyword only matches a whole word: "ad" must not fire on
# "Radio", and a two-letter language code must not fire on an unrelated track.
_COMPOUND_MATCH_MIN_CHARS = 6


def audio_track_tokens(text: Optional[str]) -> List[str]:
    """Lower-cased word tokens of a track name, punctuation dropped."""
    if not text:
        return []
    # \W is Unicode-aware for str patterns, so Cyrillic, Greek, Arabic and CJK track
    # names tokenize like Latin ones instead of collapsing to nothing.
    return [token for token in re.split(r"[\W_]+", str(text).lower()) if token]


def audio_track_matches(name: Optional[str], keyword: Optional[str]) -> bool:
    """Whether a libVLC track name satisfies one preference keyword.

    Matching is word-based so short keywords stay safe ("AD" matches "eng AD" and
    "AD (English)" but never "Radio"), with a substring fallback for keywords long
    enough that a compound word cannot be a coincidence ("audiodescription" inside
    "Audiodescription-Ton").
    """
    tokens = audio_track_tokens(name)
    wanted = audio_track_tokens(keyword)
    if not tokens or not wanted:
        return False
    span = len(wanted)
    for start in range(len(tokens) - span + 1):
        if tokens[start:start + span] == wanted:
            return True
    joined_wanted = "".join(wanted)
    if len(joined_wanted) < _COMPOUND_MATCH_MIN_CHARS:
        return False
    return joined_wanted in "".join(tokens)


def _dedupe_keywords(keywords: Sequence[str]) -> List[str]:
    """Strip blanks and case-insensitive repeats, keeping the first of each."""
    out: List[str] = []
    seen = set()
    for keyword in keywords:
        text = str(keyword or "").strip()
        folded = text.lower()
        if not text or folded in seen:
            continue
        seen.add(folded)
        out.append(text)
    return out


def preferred_audio_keywords(
    keywords: Optional[Sequence[str]] = None,
    *,
    prefer_audio_description: bool = False,
) -> List[str]:
    """The keyword list to match tracks against, in priority order.

    The user's own wording comes first: somebody who typed "German AD" wants that
    ahead of the generic audio-description guesses.
    """
    return _dedupe_keywords(
        list(keywords or [])
        + (list(AUDIO_DESCRIPTION_KEYWORDS) if prefer_audio_description else [])
    )


def select_preferred_audio_track(
    tracks: Sequence[Tuple[int, str]],
    keywords: Optional[Sequence[str]] = None,
    *,
    fallback_index: Optional[int] = None,
    prefer_ad: bool = False,
) -> Optional[int]:
    """The id of the first track matching the highest-priority keyword, if any.

    When no keyword matches, ``fallback_index`` restores a remembered track by
    its *position*: providers rename or renumber tracks between connections,
    so a stored name such as "Track 3" can miss a stream whose third slot is
    now called something else. The position still points at the same audio.
    ``None`` (no memory for this channel yet) skips the attempt.

    Last resort for streams with the audio-description preference on and more
    than one track: a track whose name advertises audio description wins, and
    among those the last one listed. When none is named, the last track of the
    stream is the best guess anyway, because providers append the description
    track after the ordinary ones - the highest number is where it lives.
    """
    if not tracks:
        return None
    for keyword in keywords or ():
        matches = [tid for tid, name in tracks
                   if audio_track_matches(name, keyword)]
        if not matches:
            continue
        if len(matches) > 1 and str(keyword).strip().lower() in _AD_KEYWORD_SET:
            # Providers append the audio description track after the ordinary
            # ones, so between several named description tracks the highest
            # number is the one to take.
            return matches[-1]
        return matches[0]
    if fallback_index is not None:
        try:
            index = int(fallback_index)
        except (TypeError, ValueError):
            index = -1
        if 0 <= index < len(tracks):
            return tracks[index][0]
    if prefer_ad and len(tracks) > 1:
        described = [
            (tid, name) for tid, name in tracks
            if audio_track_matches(name, "audio description")
        ]
        if described:
            return described[-1][0]
        return tracks[-1][0]
    return None


def active_audio_track_index(
    tracks: Sequence[Tuple[int, str]],
    current_id: Optional[int],
    wanted_name: Optional[str] = None,
) -> int:
    """Which track the audio-track control and menu should sit on.

    The track that was asked for wins over the one libVLC reports. libVLC keeps
    answering ``audio_get_track()`` with the previous id for a moment after a
    switch, and on some streams reports an id that is not in the description
    list at all - both of which used to leave the control parked on the first
    track. Tabbing to a control that says "Track 1" while the audio description
    is playing reads as "the preference was ignored", so the intent has to win.
    """
    if not tracks:
        return 0
    wanted = str(wanted_name or "").strip()
    if wanted:
        for index, (_track_id, name) in enumerate(tracks):
            if name == wanted:
                return index
    if current_id is not None:
        for index, (track_id, _name) in enumerate(tracks):
            if track_id == current_id:
                return index
        LOG.debug("libVLC reports audio track %s, which is not in %s",
                  current_id, [track_id for track_id, _name in tracks])
    return 0


def ordered_preference_keywords(
    channel_track: Optional[str],
    *,
    prefer_audio_description: bool = False,
    last_manual: Optional[str] = "",
    preferred: Optional[Sequence[str]] = None,
) -> List[str]:
    """The keywords a stream's tracks are matched against, in priority order.

    Most specific signal first. The track this channel was last watched with
    was picked by hand while listening to this very channel, so it beats every
    broader rule - including the audio-description preference, which is a
    default for channels the user has not decided about. After it: the
    audio-description guesses (when that preference is on), otherwise the
    track hand-picked on some other channel - chosen while listening, so it
    beats a saved keyword - and then the user's own wording.
    """
    keywords: List[str] = []
    channel_track = str(channel_track or "").strip()
    if channel_track:
        keywords.append(channel_track)
    if prefer_audio_description:
        keywords.extend(AUDIO_DESCRIPTION_KEYWORDS)
    else:
        manual = str(last_manual or "").strip()
        if manual:
            keywords.append(manual)
        keywords.extend(preferred_audio_keywords(preferred, prefer_audio_description=False))
    return _dedupe_keywords(keywords)


def names_audio_description(name: Optional[str]) -> bool:
    """Whether a track name advertises audio description."""
    return any(audio_track_matches(name, keyword) for keyword in AUDIO_DESCRIPTION_KEYWORDS)
