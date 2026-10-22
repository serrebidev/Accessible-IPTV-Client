"""Channel-name normalization and country/group detection.

Single source of truth for the matching vocabulary shared by the playlist/EPG
layer and the options layer. This module is deliberately dependency-free (stdlib
only) so both `playlist` and `options` can import it without a cycle.

These functions run once per channel during EPG import and once per channel in
every UI matching scan, so the regexes are compiled once at module level rather
than rebuilt per call.
"""

import functools
import re
from typing import Dict, List, Optional, Set

STRIP_TAGS = [
    'hd', 'sd', 'hevc', 'fhd', 'uhd', '4k', '8k', 'hdr', 'dash', 'hq', 'st',
    'us', 'usa', 'ca', 'canada', 'uk', 'u.k.', 'u.k', 'uk.', 'u.s.', 'u.s', 'us.',
    'au', 'aus', 'nz', 'ukhd', 'uksd', 'fhd', 'uhd', 'h.265', 'h265', 'h.264', 'h264',
    '50fps', '60fps', 'eu'
]
# "car" is deliberately not a strip tag: it is an ordinary English word, and
# stripping it made "Car SOS" and "SOS" the same channel - the guide of one
# and the playlist of the other, matched to each other. The country is still
# recognised by the group synonyms ("CAR" is Canada there).

NOISE_WORDS = [
    'backup', 'alt', 'feed', 'main', 'extra', 'mirror', 'test', 'temp',
    '1', '2', '3', '4', '5', '6', '7', '8', '9', '0',
    'sd', 'hd', 'fhd', 'uhd', '4k', '8k', 'plus', 'live', 'network'
]

_GROUP_SYNONYMS_CACHE: Optional[Dict[str, List[str]]] = None


def group_synonyms() -> Dict[str, List[str]]:
    global _GROUP_SYNONYMS_CACHE
    cache = _GROUP_SYNONYMS_CACHE
    if cache is not None:
        return cache
    cache = {
        "us": ["us","usa","u.s.","u.s","us.","united states","united states of america","america"],
        "ca": ["ca","can","canada","car"],
        "mx": ["mx","mex","mexico","méxico"],
        "uk": ["uk","u.k.","gb","gbr","great britain","britain","united kingdom","england","scotland","wales","northern ireland"],
        "ie": ["ie","irl","ireland","eire","éire"],
        "de": ["de","ger","deu","germany","deutschland"],
        "at": ["at","aut","austria","österreich","oesterreich"],
        "ch": ["ch","che","switzerland","schweiz","suisse","svizzera"],
        "nl": ["nl","nld","netherlands","holland","nederland"],
        "be": ["be","bel","belgium","belgie","belgië","belgique"],
        "lu": ["lu","lux","luxembourg","letzebuerg","lëtzebuerg"],
        "se": ["se","swe","sweden","svenska","sverige"],
        "no": ["no","nor","norway","norge","noreg"],
        "dk": ["dk","dnk","denmark","danmark"],
        "fi": ["fi","fin","finland","suomi"],
        "is": ["is","isl","iceland","ísland"],
        "fr": ["fr","fra","france","français","française"],
        "it": ["it","ita","italy","italia"],
        "es": ["es","esp","spain","españa","espana","español"],
        "pt": ["pt","prt","portugal","português"],
        "gr": ["gr","grc","greece","ελλάδα","ellada"],
        "mt": ["mt","mlt","malta"],
        "cy": ["cy","cyp","cyprus"],
        "pl": ["pl","pol","poland","polska"],
        "cz": ["cz","cze","czech","czechia","cesko","česko"],
        "sk": ["sk","svk","slovakia","slovensko"],
        "hu": ["hu","hun","hungary","magyar"],
        "si": ["si","svn","slovenia","slovenija"],
        "hr": ["hr","hrv","croatia","hrvatska"],
        "rs": ["rs","srb","serbia","srbija"],
        "ba": ["ba","bih","bosnia","bosnia and herzegovina","bosna","hercegovina"],
        "mk": ["mk","mkd","north macedonia","macedonia"],
        "ro": ["ro","rou","romania","românia"],
        "bg": ["bg","bgr","bulgaria","българия","balgariya"],
        "ua": ["ua","ukr","ukraine","ukraina"],
        "by": ["by","blr","belarus"],
        "ru": ["ru","rus","russia","россия","rossiya"],
        "ee": ["ee","est","estonia","eesti"],
        "lv": ["lv","lva","latvia","latvija"],
        "lt": ["lt","ltu","lithuania","lietuva"],
        "al": ["al","alb","albania","shqipëri","shqiperia"],
        "me": ["me","mne","montenegro","crna gora"],
        "xk": ["xk","kosovo"],
        "tr": ["tr","tur","turkey","türkiye","turkiye"],
        "ma": ["ma","mar","morocco","maroc"],
        "dz": ["dz","dza","algeria","algérie"],
        "tn": ["tn","tun","tunisia","tunisie"],
        "eg": ["eg","egypt","misr"],
        "il": ["il","isr","israel"],
        "sa": ["sa","sau","saudi","saudi arabia"],
        "ae": ["ae","are","uae","united arab emirates"],
        "qa": ["qa","qat","qatar"],
        "kw": ["kw","kwt","kuwait"],
        "in": ["in","ind","india","bharat"],
        "pk": ["pk","pak","pakistan"],
        "bd": ["bd","bgd","bangladesh"],
        "lk": ["lk","lka","sri lanka"],
        "np": ["np","npl","nepal"],
        "cn": ["cn","chn","china"],
        "hk": ["hk","hkg","hong kong"],
        "tw": ["tw","twn","taiwan"],
        "jp": ["jp","jpn","japan","日本"],
        "kr": ["kr","kor","korea","south korea"],
        "sg": ["sg","sgp","singapore"],
        "my": ["my","mys","malaysia"],
        "th": ["th","tha","thailand"],
        "vn": ["vn","vnm","vietnam"],
        "ph": ["ph","phl","philippines"],
        "id": ["id","idn","indonesia"],
        "au": ["au","aus","australia"],
        "nz": ["nz","nzl","new zealand","aotearoa"],
        "br": ["br","bra","brazil","brasil"],
        "ar": ["ar","arg","argentina"],
        "cl": ["cl","chl","chile"],
        "co": ["co","col","colombia"],
        "pe": ["pe","per","peru","perú"],
        "uy": ["uy","ury","uruguay"],
        "py": ["py","pry","paraguay"],
        "bo": ["bo","bol","bolivia"],
        "ec": ["ec","ecu","ecuador"],
        "ve": ["ve","ven","venezuela"],
        "cr": ["cr","cri","costa rica"],
        "pr": ["pr","pri","puerto rico"],
        "ng": ["ng","nga","nigeria"],
        "za": ["za","zaf","south africa"],
        "ke": ["ke","ken","kenya"],
        "gh": ["gh","gha","ghana"],
        "et": ["et","eth","ethiopia"],
        "tz": ["tz","tza","tanzania"],
        "ug": ["ug","uga","uganda"],
        "ci": ["ci","civ","côte d’ivoire","côte d'ivoire","cote d'ivoire","cote divoire","ivory coast"],
        "sn": ["sn","sen","senegal"],
    }
    _GROUP_SYNONYMS_CACHE = cache
    return cache


# Precompiled, cached regex structures. canonicalize_name / strip_noise_words / extract_group
# run once per channel during EPG import and once per channel in every UI matching scan, so
# rebuilding+recompiling these patterns per call was a major cost on large playlists. These
# compile once and produce results identical to the previous per-call construction.
_STRIP_TAGS_ESCAPED = [re.escape(tag) for tag in STRIP_TAGS]
_CANON_STRIP_EDGE_RE = re.compile(
    r'^(?:' + '|'.join(_STRIP_TAGS_ESCAPED) + r')\b[\s\-:()\[\]]*|[\s\-:()\[\]]*\b(?:' + '|'.join(_STRIP_TAGS_ESCAPED) + r')$',
    re.I,
)
_CANON_STRIP_WORD_RE = re.compile(r'\b(?:' + '|'.join(_STRIP_TAGS_ESCAPED) + r')\b', re.I)
_CANON_EMPTY_BRACKETS_RE = re.compile(r'\(\s*\)|\[\s*\]')
_CANON_WS_RE = re.compile(r'\s+')
_NOISE_WORDS_RE = re.compile(r'\b(' + '|'.join(re.escape(w) for w in NOISE_WORDS) + r')\b', re.I)
_NOISE_SEP_RE = re.compile(r'[\s\-_]+')
_LEADING_CODE_RE = re.compile(r'([a-z]{2,3})\b')
_PAREN_CODE_RE = re.compile(r'\(([a-z]{2,3})\)')

_GROUP_SYNONYM_PATTERNS_CACHE = None


# Country-code variants that are ordinary English words. They are matched
# only where a code is meant - a leading or parenthesised code, written in
# capitals - never as a free word.
_WORD_VARIANTS = frozenset({"can", "car", "nor", "per", "ind"})

_VARIANT_TAGS_CACHE = None


def _variant_tags() -> Dict[str, str]:
    """Every country-code variant, mapped to the tag it means.

    A code can be written in more than one way ("CA", "CAN", "CANADA"), and
    a leading code in capitals is what the codes look like.
    """
    global _VARIANT_TAGS_CACHE
    if _VARIANT_TAGS_CACHE is None:
        mapping: Dict[str, str] = {}
        for tag, variants in group_synonyms().items():
            for variant in variants:
                mapping.setdefault(str(variant).strip().lower(), tag)
        _VARIANT_TAGS_CACHE = mapping
    return _VARIANT_TAGS_CACHE


def _group_synonym_patterns():
    """[(norm_tag, compiled \\b(?:variant|...)\\b regex)] in group_synonyms() order.

    Equivalent to the previous per-variant loop: returns the first tag whose any variant
    matches, and variant order within a tag does not affect which tag is returned.
    """
    global _GROUP_SYNONYM_PATTERNS_CACHE
    if _GROUP_SYNONYM_PATTERNS_CACHE is None:
        patterns = []
        for tag, variants in group_synonyms().items():
            # The bare code ("at", "no", "is", "de") is matched only as a
            # leading or parenthesised code. As a free word it hits ordinary
            # English: "News at Ten" is not Austrian and "No Limits" is not
            # Norwegian. The same holds for the variants that are words too:
            # "Car SOS" is not Canadian and "You Can Do It" is not either.
            words = [v for v in variants
                     if v != tag and v.lower() not in _WORD_VARIANTS]
            if not words:
                continue
            patterns.append((tag, re.compile(r'\b(?:' + '|'.join(re.escape(v) for v in words) + r')\b')))
        _GROUP_SYNONYM_PATTERNS_CACHE = patterns
    return _GROUP_SYNONYM_PATTERNS_CACHE


# The now-playing labels re-normalize every playlist and guide name each
# minute (about 200,000 strings on a large provider), and the regexes cost
# ~13 s of CPU per pass. Names barely change between passes, so a cache that
# holds the whole working set makes repeat passes nearly free. Bounded so a
# long session of playlist reloads cannot grow it without limit.
_NAME_CACHE_SIZE = 1 << 18


# The numbers in a channel name are the channel: "BBC 1" and "BBC 2" are
# different channels, and "BBC One" is "BBC 1". The noise-stripped name drops
# a standalone digit as noise, so these helpers are what tells the two apart.
# They live here, with the rest of the matching vocabulary, because both the
# database matcher and the playlist-side matcher need them.
_WORD_NUMBERS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
}
# Resolutions and frame rates are not channel numbers.
_IGNORED_NUMBERS = {
    "240", "360", "480", "540", "576", "720", "1080", "1440", "2160", "4320",
    "50", "60",
}


@functools.lru_cache(maxsize=_NAME_CACHE_SIZE)
def significant_channel_numbers(*texts: str) -> frozenset:
    """The channel numbers the given texts name.

    Cached like the other name helpers: the matcher asks for the numbers of
    every channel in the playlist, and the texts barely change.
    """
    numbers: Set[str] = set()
    for text in texts:
        s = (text or "").lower()
        if not s:
            continue
        s = re.sub(r'\b(?:au|ca|ie|uk|gb|us)\d+\b', ' ', s)
        for raw in re.findall(r'\d+', s):
            normalized = raw.lstrip("0") or "0"
            if normalized in _IGNORED_NUMBERS:
                continue
            if len(normalized) > 3:
                continue
            numbers.add(normalized)
        for word, value in _WORD_NUMBERS.items():
            if re.search(r'\b' + re.escape(word) + r'\b', s):
                numbers.add(value)
    return frozenset(numbers)


@functools.lru_cache(maxsize=_NAME_CACHE_SIZE)
def replace_word_numbers(text: str) -> str:
    """Write the word numbers in a name as digits: "BBC Two" -> "BBC 2".

    Lets one matcher's normalized name reach the other's: a guide that spells
    a channel out and a playlist that numbers it are the same channel.
    """
    text = (text or "").lower()
    for word, value in _WORD_NUMBERS.items():
        text = re.sub(r'\b' + re.escape(word) + r'\b', value, text)
    return text


def id_number_text(channel_id: str) -> str:
    """A channel id as text for :func:`significant_channel_numbers`.

    A purely numeric id (Dispatcharr/Xtream key guides by row number: "4",
    "151") is a database key, not a channel number. Counting it made "ESPN"
    with tvg-id "2" match "ESPN 2", and penalised every same-named guide
    channel that lacked the number.
    """
    text = (channel_id or "").strip()
    return "" if text.isdigit() else text


def numbers_disagree(first: Set[str], second: Set[str]) -> bool:
    """True when two names name different channels by their number.

    A name without a number says nothing about it, so only two names that
    both carry one can disagree.
    """
    if not first or not second:
        return False
    return not (first & second)


@functools.lru_cache(maxsize=_NAME_CACHE_SIZE)
def canonicalize_name(name: str) -> str:
    name = (name or "").strip().lower()
    while True:
        newname = _CANON_STRIP_EDGE_RE.sub('', name).strip()
        if newname == name:
            break
        name = newname
    name = _CANON_STRIP_WORD_RE.sub('', name)
    name = _CANON_EMPTY_BRACKETS_RE.sub('', name)
    name = _CANON_WS_RE.sub(' ', name)
    return name.strip()

@functools.lru_cache(maxsize=_NAME_CACHE_SIZE)
def strip_noise_words(text: str) -> str:
    if not text:
        return ""
    text = text.lower()
    text = _NOISE_WORDS_RE.sub('', text)
    text = _NOISE_SEP_RE.sub(' ', text)
    return text.strip()

def _looks_like_a_code(original: str) -> bool:
    """Whether the title's first token is written the way a code is.

    Providers name a channel "AT Sports 1" and "DE Film 2", in capitals. A
    title that starts with an ordinary word - "No Limits", "By Example" - is
    not a country code, whatever the two letters happen to be.
    """
    token = str(original or "").strip().split(" ", 1)[0]
    return len(token) >= 2 and token.isupper()


def extract_group(title: str) -> str:
    if not title:
        return ''
    original = title
    title = title.lower()
    for norm_tag, rx in _group_synonym_patterns():
        if rx.search(title):
            return norm_tag
    tags = _variant_tags()
    m = _LEADING_CODE_RE.match(title)
    if m:
        code = m.group(1)
        tag = tags.get(code)
        if tag and _looks_like_a_code(original):
            return tag
    m = _PAREN_CODE_RE.search(title)
    if m:
        tag = tags.get(m.group(1))
        if tag:
            return tag
    return ''
