"""The in-app User Guide: localized Markdown files split into named sections.

wx-free on purpose, like ``account_info.py``: loading, rendering and topic
lookup are plain functions the tests drive directly, and the help window in
``main.py`` only displays what this module hands it.

Guides live in ``docs/help/<language>.md``. English (``en.md``) is the
reference. Every other language is optional and falls back to English, both
as a whole (no file for the language yet) and per topic (a context topic the
translation does not cover yet opens the English guide at that section, which
is more useful than the top of a manual in the right language).

The Markdown understood here is a small, predictable subset, because the
result is shown in a plain read-only text box that a screen reader reads line
by line:

- ``#``, ``##`` and ``###`` headings. A heading may end in ``{#topic-id}``,
  the stable English id that context-sensitive F1 help opens. Translations
  keep the ids exactly as they are and translate only the title.
- Paragraphs. Consecutive lines are joined, so the source can be wrapped
  freely; a blank line starts a new paragraph.
- ``-`` and ``*`` bullet items and ``1.`` numbered items, one per line. An
  indented line continues the item above it.
- ``**bold**``, ``*emphasis*`` and code spans lose their markers, and
  ``[text](url)`` becomes ``text (url)``.
- ``<!-- comments -->`` are dropped, for notes to translators.

Context help works by walking from the focused window up through its parents
until one carries a ``help_topic`` attribute (see :func:`topic_for_window`).
Menu items are mapped separately with :func:`set_menu_help`, because Windows
reports F1 on an open menu as the item's command id, not as a window.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

GUIDE_DIR_PARTS = ("docs", "help")
FALLBACK_LANGUAGE = "en"
# The guide's title section, i.e. the start of the manual.
DEFAULT_TOPIC = "user-guide"
# How the help window itself works: what F1 inside the guide opens.
HELP_TOPIC = "using-help"

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.*?)\s*$")
_ANCHOR_RE = re.compile(r"\s*\{#([a-z0-9][a-z0-9-]*)\}\s*$")
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.*)$")
_NUMBERED_RE = re.compile(r"^\s*(\d+[.)])\s+(.*)$")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_EMPHASIS_RE = re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])")
_CODE_RE = re.compile(r"`([^`]+)`")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


@dataclass
class Section:
    """One heading of the guide and where it starts in the rendered text."""

    topic: str
    title: str
    level: int
    start: int


@dataclass
class Guide:
    """A rendered guide: the plain text shown to the user and its sections."""

    language: str
    text: str
    sections: List[Section] = field(default_factory=list)

    def find(self, topic: str) -> Optional[Section]:
        for section in self.sections:
            if section.topic == topic:
                return section
        return None

    def section_at(self, position: int) -> Optional[Section]:
        """The section the text offset ``position`` falls in (the first one before any heading)."""
        current = self.sections[0] if self.sections else None
        for section in self.sections:
            if section.start > position:
                break
            current = section
        return current

    def topics(self) -> List[str]:
        return [section.topic for section in self.sections]


def _inline(text: str) -> str:
    """Strip the inline Markdown markers, keeping the words."""

    def link(match: "re.Match[str]") -> str:
        label, url = match.group(1), match.group(2)
        if url.startswith("#"):
            return label
        return "{label} ({url})".format(label=label, url=url)

    text = _CODE_RE.sub(r"\1", text)
    text = _LINK_RE.sub(link, text)
    text = _BOLD_RE.sub(r"\1", text)
    text = _EMPHASIS_RE.sub(r"\1", text)
    return text


class _TextBuilder:
    """Accumulates rendered blocks, separated by one blank line."""

    def __init__(self) -> None:
        self.parts: List[str] = []
        self.length = 0

    def add_block(self, lines: List[str]) -> int:
        """Append a block and return the offset its first line starts at."""
        separator = "\n\n" if self.parts else ""
        offset = self.length + len(separator)
        chunk = separator + "\n".join(lines)
        self.parts.append(chunk)
        self.length += len(chunk)
        return offset

    def text(self) -> str:
        return "".join(self.parts)


def render(markdown: str, language: str = FALLBACK_LANGUAGE) -> Guide:
    """Turn guide Markdown into the plain text shown in the help window."""
    source = markdown.replace("\r\n", "\n").replace("\r", "\n")
    source = _COMMENT_RE.sub("", source)
    builder = _TextBuilder()
    sections: List[Section] = []
    block: List[str] = []
    block_kind = ""  # "paragraph" or "list"

    def flush() -> None:
        nonlocal block, block_kind
        if block:
            if block_kind == "list":
                builder.add_block(block)
            else:
                builder.add_block([" ".join(block)])
        block = []
        block_kind = ""

    for raw in source.split("\n"):
        line = raw.rstrip()
        if not line.strip():
            flush()
            continue
        heading = _HEADING_RE.match(line)
        if heading:
            flush()
            title_source = heading.group(2)
            anchor = _ANCHOR_RE.search(title_source)
            title = _inline(_ANCHOR_RE.sub("", title_source)).strip()
            topic = anchor.group(1) if anchor else "section-{n}".format(n=len(sections) + 1)
            offset = builder.add_block([title])
            sections.append(Section(topic=topic, title=title, level=len(heading.group(1)), start=offset))
            continue
        bullet = _BULLET_RE.match(line)
        numbered = None if bullet else _NUMBERED_RE.match(line)
        if bullet or numbered:
            if block_kind != "list":
                flush()
                block_kind = "list"
            if bullet:
                block.append(_inline(bullet.group(1).strip()))
            else:
                assert numbered is not None
                block.append("{marker} {text}".format(
                    marker=numbered.group(1), text=_inline(numbered.group(2).strip())))
            continue
        if block_kind == "list" and raw[:1] in (" ", "\t"):
            block[-1] = block[-1] + " " + _inline(line.strip())
            continue
        if block_kind == "list":
            flush()
        block_kind = "paragraph"
        block.append(_inline(line.strip()))
    flush()
    return Guide(language=language, text=builder.text(), sections=sections)


def guide_dir() -> str:
    """Absolute path of ``docs/help`` (next to the modules, or inside the frozen bundle)."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", None) or os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, *GUIDE_DIR_PARTS)


def _language_candidates(language: Optional[str]) -> List[str]:
    code = (language or "").strip().lower().replace("-", "_").split("_")[0]
    candidates = []
    if code and code != FALLBACK_LANGUAGE:
        candidates.append(code)
    candidates.append(FALLBACK_LANGUAGE)
    return candidates


def guide_path(language: str, directory: Optional[str] = None) -> Optional[str]:
    """The guide file for exactly ``language``, or None when there is none."""
    path = os.path.join(directory or guide_dir(), "{code}.md".format(code=language))
    return path if os.path.isfile(path) else None


def available_languages(directory: Optional[str] = None) -> List[str]:
    """Language codes that have a guide file, English first."""
    folder = directory or guide_dir()
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    codes = sorted(name[:-3] for name in names if name.endswith(".md"))
    if FALLBACK_LANGUAGE in codes:
        codes.remove(FALLBACK_LANGUAGE)
        codes.insert(0, FALLBACK_LANGUAGE)
    return codes


def load_guide(language: Optional[str], directory: Optional[str] = None) -> Guide:
    """The guide for ``language``, or the English one when that language has none.

    Raises ``FileNotFoundError`` when not even the English guide is present.
    """
    for code in _language_candidates(language):
        path = guide_path(code, directory)
        if path:
            with open(path, encoding="utf-8") as handle:
                return render(handle.read(), code)
    raise FileNotFoundError(
        os.path.join(directory or guide_dir(), "{code}.md".format(code=FALLBACK_LANGUAGE)))


def open_topic(language: Optional[str], topic: Optional[str],
               directory: Optional[str] = None) -> Tuple[Guide, Optional[Section]]:
    """The guide and the section to show for context ``topic`` in ``language``.

    A topic the translation does not have yet opens the English guide at that
    section. The start of the manual never falls back: every translation has a
    beginning, anchored or not.
    """
    topic = topic or DEFAULT_TOPIC
    guide = load_guide(language, directory)
    section = guide.find(topic)
    if section is None and topic != DEFAULT_TOPIC and guide.language != FALLBACK_LANGUAGE:
        english = load_guide(FALLBACK_LANGUAGE, directory)
        english_section = english.find(topic)
        if english_section is not None:
            return english, english_section
    if section is None and guide.sections:
        section = guide.sections[0]
    return guide, section


def set_help_topic(window, topic) -> None:
    """Give ``window`` a help topic: an id, or a callable returning one.

    A callable suits a control whose meaning changes, such as the channel list
    that also browses video on demand.
    """
    setattr(window, "help_topic", topic)


def topic_for_window(window, default: str = DEFAULT_TOPIC) -> str:
    """The ``help_topic`` of ``window`` or its nearest parent that has one."""
    hops = 0
    while window is not None and hops < 64:
        topic = getattr(window, "help_topic", None)
        if callable(topic):
            try:
                topic = topic()
            except Exception:
                topic = None
        if isinstance(topic, str) and topic:
            return topic
        try:
            window = window.GetParent()
        except Exception:
            break
        hops += 1
    return default


def _menu_id_forms(item_id: int) -> Tuple[int, ...]:
    """``item_id`` as registered, whichever way Windows reported it.

    WM_HELP carries a menu item's command id as an unsigned 16-bit number and
    wx passes it on unchanged. wx's automatic ids are negative (-31992, say),
    so they arrive as 65536 minus that (33544) and would never match.
    """
    if 0x8000 <= item_id <= 0xFFFF:
        return (item_id, item_id - 0x10000)
    return (item_id,)


def topic_for_menu_item(window, item_id: int) -> Optional[str]:
    """The topic registered for menu item ``item_id`` on ``window`` or a parent."""
    forms = _menu_id_forms(item_id)
    hops = 0
    while window is not None and hops < 64:
        topics = getattr(window, "help_menu_topics", None)
        if isinstance(topics, dict):
            for form in forms:
                if form in topics:
                    return topics[form]
        try:
            window = window.GetParent()
        except Exception:
            break
        hops += 1
    return None


def set_menu_help(owner, target, topic: str) -> None:
    """Map a menu item, or every item of a menu and its submenus, to ``topic``.

    ``owner`` is the window the menu belongs to (the frame with the menu bar):
    that is where Windows sends F1 pressed on an open menu. The map lives on
    the window, so it goes away with it and a recycled item id can never point
    at a stale topic. Register a whole menu first, then override single items.
    """
    topics: Optional[Dict[int, str]] = getattr(owner, "help_menu_topics", None)
    if not isinstance(topics, dict):
        topics = {}
        setattr(owner, "help_menu_topics", topics)
    items = list(target.GetMenuItems()) if hasattr(target, "GetMenuItems") else [target]
    for item in items:
        if not hasattr(item, "GetId"):
            continue
        topics[item.GetId()] = topic
        submenu = item.GetSubMenu() if hasattr(item, "GetSubMenu") else None
        if submenu is not None:
            set_menu_help(owner, submenu, topic)
