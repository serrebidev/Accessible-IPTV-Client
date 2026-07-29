"""Channel-name normalization and country/group detection.

Single source of truth for the matching vocabulary shared by the playlist/EPG
layer and the options layer. This module is deliberately dependency-free (stdlib
only) so both `playlist` and `options` can import it without a cycle.

These functions run once per channel during EPG import and once per channel in
every UI matching scan, so the regexes are compiled once at module level rather
than rebuilt per call.
"""

import re
from typing import Dict, List, Optional

STRIP_TAGS = [
    'hd', 'sd', 'hevc', 'fhd', 'uhd', '4k', '8k', 'hdr', 'dash', 'hq', 'st',
    'us', 'usa', 'ca', 'canada', 'car', 'uk', 'u.k.', 'u.k', 'uk.', 'u.s.', 'u.s', 'us.',
    'au', 'aus', 'nz', 'ukhd', 'uksd', 'fhd', 'uhd', 'h.265', 'h265', 'h.264', 'h264',
    '50fps', '60fps', 'eu'
]

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
_CANON_STRIP_EDGE_RE = re.compile(
    r'^(?:' + '|'.join(STRIP_TAGS) + r')\b[\s\-:()\[\]]*|[\s\-:()\[\]]*\b(?:' + '|'.join(STRIP_TAGS) + r')$',
    re.I,
)
_CANON_STRIP_WORD_RE = re.compile(r'\b(?:' + '|'.join(STRIP_TAGS) + r')\b', re.I)
_CANON_EMPTY_BRACKETS_RE = re.compile(r'\(\s*\)|\[\s*\]')
_CANON_WS_RE = re.compile(r'\s+')
_NOISE_WORDS_RE = re.compile(r'\b(' + '|'.join(re.escape(w) for w in NOISE_WORDS) + r')\b', re.I)
_NOISE_SEP_RE = re.compile(r'[\s\-_]+')
_LEADING_CODE_RE = re.compile(r'([a-z]{2,3})\b')
_PAREN_CODE_RE = re.compile(r'\(([a-z]{2,3})\)')

_GROUP_SYNONYM_PATTERNS_CACHE = None


def _group_synonym_patterns():
    """[(norm_tag, compiled \\b(?:variant|...)\\b regex)] in group_synonyms() order.

    Equivalent to the previous per-variant loop: returns the first tag whose any variant
    matches, and variant order within a tag does not affect which tag is returned.
    """
    global _GROUP_SYNONYM_PATTERNS_CACHE
    if _GROUP_SYNONYM_PATTERNS_CACHE is None:
        _GROUP_SYNONYM_PATTERNS_CACHE = [
            (tag, re.compile(r'\b(?:' + '|'.join(re.escape(v) for v in variants) + r')\b'))
            for tag, variants in group_synonyms().items()
        ]
    return _GROUP_SYNONYM_PATTERNS_CACHE


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

def strip_noise_words(text: str) -> str:
    if not text:
        return ""
    text = text.lower()
    text = _NOISE_WORDS_RE.sub('', text)
    text = _NOISE_SEP_RE.sub(' ', text)
    return text.strip()

def extract_group(title: str) -> str:
    if not title:
        return ''
    title = title.lower()
    for norm_tag, rx in _group_synonym_patterns():
        if rx.search(title):
            return norm_tag
    syn = group_synonyms()
    m = _LEADING_CODE_RE.match(title)
    if m:
        code = m.group(1)
        if code in syn:
            return code
    m = _PAREN_CODE_RE.search(title)
    if m:
        code = m.group(1)
        if code in syn:
            return code
    return ''
