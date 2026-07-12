"""Dependency-free i18n tooling for Accessible IPTV Client.

Two jobs, both pure standard library so the maintainer never has to install GNU
gettext, Babel or polib to work on translations:

    python tools/i18n_tools.py extract   # rebuild locale/iptvclient.pot from _()/ngettext()
    python tools/i18n_tools.py compile   # compile every locale/<lang>/LC_MESSAGES/*.po -> *.mo
    python tools/i18n_tools.py update    # merge new POT strings into each existing .po
    python tools/i18n_tools.py all       # extract + update + compile

Extraction is AST-based: it finds calls to ``_( "literal" )`` and
``ngettext("singular", "plural", n)`` and records source locations. f-strings and
runtime-built strings are intentionally ignored (wrap a constant template and use
``.format()`` instead so the text is extractable).
"""

from __future__ import annotations

import argparse
import ast
import array
import os
import struct
import sys
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCALE_DIR = os.path.join(REPO_ROOT, "locale")
DOMAIN = "iptvclient"
POT_PATH = os.path.join(LOCALE_DIR, DOMAIN + ".pot")

# Application modules that contain user-facing text. Extra files are harmless
# (no marker calls = no strings), but listing them keeps extraction deterministic.
SOURCE_FILES = [
    "main.py",
    "internal_player.py",
    "playlist.py",
    "options.py",
    "providers.py",
    "vod.py",
    "updater.py",
    "external_player.py",
    "casting.py",
    "stream_proxy.py",
]

TRANSLATION_FUNCS = {"_", "gettext"}
PLURAL_FUNCS = {"ngettext"}


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #
class _Collector(ast.NodeVisitor):
    def __init__(self, relpath):
        self.relpath = relpath
        # key -> {"plural": str|None, "locations": set[(file, line)]}
        self.messages = {}

    def _record(self, msgid, line, plural=None):
        entry = self.messages.setdefault(msgid, {"plural": None, "locations": set()})
        if plural and not entry["plural"]:
            entry["plural"] = plural
        entry["locations"].add((self.relpath, line))

    @staticmethod
    def _func_name(node):
        func = node.func
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
        return None

    @staticmethod
    def _const_str(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        return None

    def visit_Call(self, node):
        name = self._func_name(node)
        if name in TRANSLATION_FUNCS and node.args:
            msgid = self._const_str(node.args[0])
            if msgid:
                self._record(msgid, node.lineno)
        elif name in PLURAL_FUNCS and len(node.args) >= 2:
            singular = self._const_str(node.args[0])
            plural = self._const_str(node.args[1])
            if singular and plural:
                self._record(singular, node.lineno, plural=plural)
        self.generic_visit(node)


def extract_messages(files):
    """Return ``{msgid: {"plural": str|None, "locations": [(file, line), ...]}}``."""
    merged = {}
    for rel in files:
        path = os.path.join(REPO_ROOT, rel)
        if not os.path.exists(path):
            continue
        # utf-8-sig transparently strips a leading BOM (some sources carry one),
        # which ast.parse rejects when handed a str.
        with open(path, "r", encoding="utf-8-sig") as fh:
            source = fh.read()
        tree = ast.parse(source, filename=rel)
        collector = _Collector(rel.replace(os.sep, "/"))
        collector.visit(tree)
        for msgid, info in collector.messages.items():
            entry = merged.setdefault(msgid, {"plural": None, "locations": set()})
            if info["plural"] and not entry["plural"]:
                entry["plural"] = info["plural"]
            entry["locations"].update(info["locations"])
    return merged


def _escape(text):
    return (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
        .replace("\r", "\\r")
    )


def _pot_header():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M%z")
    return (
        "# Translation template for Accessible IPTV Client.\n"
        "# Copyright (C) 2025-2026 Serrebi and contributors.\n"
        "# This file is distributed under the same license as the application.\n"
        "#\n"
        'msgid ""\n'
        'msgstr ""\n'
        '"Project-Id-Version: Accessible IPTV Client\\n"\n'
        '"Report-Msgid-Bugs-To: https://github.com/serrebidev/Accessible-IPTV-Client/issues\\n"\n'
        f'"POT-Creation-Date: {now}\\n"\n'
        '"MIME-Version: 1.0\\n"\n'
        '"Content-Type: text/plain; charset=UTF-8\\n"\n'
        '"Content-Transfer-Encoding: 8bit\\n"\n'
        '"Language: \\n"\n'
        '"Plural-Forms: nplurals=2; plural=(n != 1);\\n"\n'
    )


def write_pot(messages, pot_path=POT_PATH):
    os.makedirs(os.path.dirname(pot_path), exist_ok=True)
    chunks = [_pot_header()]
    for msgid in sorted(messages):
        info = messages[msgid]
        chunks.append("\n")
        for loc_file, loc_line in sorted(info["locations"]):
            chunks.append(f"#: {loc_file}:{loc_line}\n")
        chunks.append(f'msgid "{_escape(msgid)}"\n')
        if info["plural"]:
            chunks.append(f'msgid_plural "{_escape(info["plural"])}"\n')
            chunks.append('msgstr[0] ""\n')
            chunks.append('msgstr[1] ""\n')
        else:
            chunks.append('msgstr ""\n')
    with open(pot_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("".join(chunks))
    return pot_path


# --------------------------------------------------------------------------- #
# Minimal PO reader + .mo compiler (GNU .mo format, little-endian)
# --------------------------------------------------------------------------- #
def _unescape(text):
    out = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            out.append(
                {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "0": "\0"}.get(
                    nxt, nxt
                )
            )
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def parse_po(path):
    """Parse a .po file into a list of entries (dicts) plus the header msgstr."""
    entries = []
    cur = None
    state = None  # which field the continuation strings belong to

    def flush():
        nonlocal cur
        if cur is not None and "msgid" in cur:
            entries.append(cur)
        cur = None

    with open(path, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            stripped = line.strip()
            if not stripped:
                flush()
                state = None
                continue
            if stripped.startswith("#"):
                continue
            if stripped.startswith("msgctxt "):
                flush()
                cur = {"msgctxt": _unescape(stripped[8:].strip()[1:-1])}
                state = "msgctxt"
            elif stripped.startswith("msgid_plural "):
                cur = cur or {}
                cur["msgid_plural"] = _unescape(stripped[len("msgid_plural ") :].strip()[1:-1])
                state = "msgid_plural"
            elif stripped.startswith("msgid "):
                if cur is not None and "msgid" in cur and "msgctxt" not in cur:
                    flush()
                cur = cur or {}
                cur["msgid"] = _unescape(stripped[6:].strip()[1:-1])
                state = "msgid"
            elif stripped.startswith("msgstr["):
                idx = int(stripped[7 : stripped.index("]")])
                value = _unescape(stripped[stripped.index("]") + 1 :].strip()[1:-1])
                cur.setdefault("plurals", {})[idx] = value
                state = ("plural", idx)
            elif stripped.startswith("msgstr "):
                cur = cur or {}
                cur["msgstr"] = _unescape(stripped[7:].strip()[1:-1])
                state = "msgstr"
            elif stripped.startswith('"'):
                piece = _unescape(stripped[1:-1])
                if state == "msgid":
                    cur["msgid"] += piece
                elif state == "msgid_plural":
                    cur["msgid_plural"] += piece
                elif state == "msgstr":
                    cur["msgstr"] = cur.get("msgstr", "") + piece
                elif state == "msgctxt":
                    cur["msgctxt"] += piece
                elif isinstance(state, tuple):
                    cur["plurals"][state[1]] += piece
        flush()
    return entries


def _catalog_from_entries(entries):
    """Build {key: value} for the .mo, skipping untranslated entries (empty msgstr)."""
    catalog = {}
    for e in entries:
        msgid = e.get("msgid", "")
        ctx = e.get("msgctxt")
        key = (ctx + "\x04" + msgid) if ctx else msgid
        if "msgid_plural" in e:
            plurals = e.get("plurals", {})
            ordered = [plurals[i] for i in sorted(plurals)]
            if not any(ordered):
                continue  # untranslated -> let gettext fall back to source
            key = key + "\x00" + e["msgid_plural"]
            catalog[key] = "\x00".join(ordered)
        else:
            msgstr = e.get("msgstr", "")
            if msgid != "" and msgstr == "":
                continue  # untranslated -> source fallback
            catalog[key] = msgstr
    return catalog


def generate_mo_bytes(catalog):
    keys = sorted(catalog)
    ids = b""
    strs = b""
    offsets = []
    for key in keys:
        kb = key.encode("utf-8")
        vb = catalog[key].encode("utf-8")
        offsets.append((len(ids), len(kb), len(strs), len(vb)))
        ids += kb + b"\x00"
        strs += vb + b"\x00"
    keystart = 7 * 4 + 16 * len(keys)
    valuestart = keystart + len(ids)
    koffsets = []
    voffsets = []
    for o1, l1, o2, l2 in offsets:
        koffsets += [l1, o1 + keystart]
        voffsets += [l2, o2 + valuestart]
    output = struct.pack(
        "Iiiiiii",
        0x950412DE,          # magic
        0,                   # version
        len(keys),           # number of strings
        7 * 4,               # offset of key table
        7 * 4 + len(keys) * 8,  # offset of value table
        0, 0,                # hash table size/offset (unused)
    )
    output += array.array("i", koffsets + voffsets).tobytes()
    output += ids
    output += strs
    return output


def compile_po(po_path, mo_path=None):
    if mo_path is None:
        mo_path = os.path.splitext(po_path)[0] + ".mo"
    entries = parse_po(po_path)
    catalog = _catalog_from_entries(entries)
    data = generate_mo_bytes(catalog)
    with open(mo_path, "wb") as fh:
        fh.write(data)
    translated = sum(
        1
        for e in entries
        if e.get("msgid")
        and (e.get("msgstr") or any((e.get("plurals") or {}).values()))
    )
    return mo_path, translated


def find_po_files():
    found = []
    if not os.path.isdir(LOCALE_DIR):
        return found
    for lang in sorted(os.listdir(LOCALE_DIR)):
        messages_dir = os.path.join(LOCALE_DIR, lang, "LC_MESSAGES")
        if not os.path.isdir(messages_dir):
            continue
        for name in sorted(os.listdir(messages_dir)):
            if name.endswith(".po"):
                found.append(os.path.join(messages_dir, name))
    return found


# --------------------------------------------------------------------------- #
# update: fold freshly-extracted strings into an existing .po, keeping translations
# --------------------------------------------------------------------------- #
def update_po(po_path, messages):
    existing = {e["msgid"]: e for e in parse_po(po_path) if e.get("msgid")}
    header = next((e for e in parse_po(po_path) if e.get("msgid", "") == ""), None)
    chunks = []
    if header and header.get("msgstr"):
        chunks.append('msgid ""\n')
        chunks.append('msgstr ""\n')
        for piece in header["msgstr"].split("\\n"):
            if piece:
                chunks.append(f'"{_escape(piece)}\\n"\n')
        chunks.append("\n")
    for msgid in sorted(messages):
        info = messages[msgid]
        prev = existing.get(msgid, {})
        for loc_file, loc_line in sorted(info["locations"]):
            chunks.append(f"#: {loc_file}:{loc_line}\n")
        chunks.append(f'msgid "{_escape(msgid)}"\n')
        if info["plural"]:
            chunks.append(f'msgid_plural "{_escape(info["plural"])}"\n')
            plurals = prev.get("plurals", {0: "", 1: ""})
            chunks.append(f'msgstr[0] "{_escape(plurals.get(0, ""))}"\n')
            chunks.append(f'msgstr[1] "{_escape(plurals.get(1, ""))}"\n')
        else:
            chunks.append(f'msgstr "{_escape(prev.get("msgstr", ""))}"\n')
        chunks.append("\n")
    with open(po_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("".join(chunks))


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def cmd_extract():
    messages = extract_messages(SOURCE_FILES)
    write_pot(messages)
    print(f"Extracted {len(messages)} strings -> {os.path.relpath(POT_PATH, REPO_ROOT)}")
    return messages


def cmd_compile():
    po_files = find_po_files()
    if not po_files:
        print("No .po files found under locale/.")
        return
    for po in po_files:
        mo, n = compile_po(po)
        print(f"Compiled {os.path.relpath(po, REPO_ROOT)} -> "
              f"{os.path.relpath(mo, REPO_ROOT)} ({n} translated)")


def cmd_update(messages=None):
    if messages is None:
        messages = extract_messages(SOURCE_FILES)
    for po in find_po_files():
        update_po(po, messages)
        print(f"Updated {os.path.relpath(po, REPO_ROOT)}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="i18n tooling for Accessible IPTV Client")
    parser.add_argument("command", choices=["extract", "compile", "update", "all"])
    args = parser.parse_args(argv)
    if args.command == "extract":
        cmd_extract()
    elif args.command == "compile":
        cmd_compile()
    elif args.command == "update":
        cmd_update()
    elif args.command == "all":
        messages = cmd_extract()
        cmd_update(messages)
        cmd_compile()


if __name__ == "__main__":
    main()
