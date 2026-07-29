"""Static guards against defect classes that have bitten this codebase before.

These tests read the source tree rather than importing it, so they stay cheap and
work without wx/VLC present.
"""

import ast
import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

SOURCE_DIRS = (REPO_ROOT, REPO_ROOT / "tools", REPO_ROOT / "tests")


def _python_sources():
    seen = {}
    for directory in SOURCE_DIRS:
        for path in sorted(directory.glob("*.py")):
            seen[path.resolve()] = path
    return sorted(seen.values())


def _read(path: pathlib.Path) -> str:
    raw = path.read_bytes()
    encoding = "utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8"
    return raw.decode(encoding)


@pytest.mark.parametrize("path", _python_sources(), ids=lambda p: p.name)
def test_source_is_utf8_without_bom(path):
    """A stray BOM breaks plain ast.parse() and confuses diff tools."""
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), f"{path.name} starts with a UTF-8 BOM"
    raw.decode("utf-8")  # raises if the file is not valid UTF-8


# Signature of UTF-8 bytes that were decoded as cp1252/latin-1 and re-encoded:
# a Latin-1 lead byte immediately followed by another high character. Built from
# escape sequences so this file does not trip its own check.
# Any UTF-8 lead byte (0xC2-0xF4) seen through latin-1/cp1252, followed by a
# continuation byte (0x80-0xBF) seen the same way.
_MOJIBAKE_RE = re.compile(
    "[" + chr(0xC2) + "-" + chr(0xF4) + "][" + chr(0x80) + "-" + chr(0xBF) + "]"
)


@pytest.mark.parametrize("path", _python_sources(), ids=lambda p: p.name)
def test_no_mojibake_in_source(path):
    """Guards the country/affiliate alias tables against cp1252 round-trip damage.

    A corrupted alias silently stops matching, which looks like a matching bug
    rather than an encoding bug and is very hard to trace back.
    """
    offenders = [
        (num, line.strip())
        for num, line in enumerate(_read(path).splitlines(), 1)
        if _MOJIBAKE_RE.search(line)
    ]
    assert not offenders, f"{path.name} contains mojibake: {offenders[:5]}"


@pytest.mark.parametrize("path", _python_sources(), ids=lambda p: p.name)
def test_no_deferred_lambda_over_dead_except_name(path):
    """`except E as err:` + a bare `lambda:` using `err` is a latent NameError.

    Python unbinds the exception name when the handler exits, so a lambda handed
    to wx.CallAfter/CallLater raises NameError instead of showing the error to the
    user. Binding it as a default argument (`lambda err=e:`) captures it safely.
    """
    tree = ast.parse(_read(path))
    offenders = []
    for handler in ast.walk(tree):
        if not isinstance(handler, ast.ExceptHandler) or not handler.name:
            continue
        for node in ast.walk(handler):
            if not isinstance(node, ast.Lambda):
                continue
            # Default values are evaluated eagerly at lambda-creation time, so
            # `lambda err=e:` is the safe form. Only the body is deferred.
            used = {n.id for n in ast.walk(node.body) if isinstance(n, ast.Name)}
            if handler.name in used:
                offenders.append(
                    f"line {node.lineno}: lambda closes over '{handler.name}' "
                    f"from except at line {handler.lineno}"
                )
    assert not offenders, f"{path.name}: {offenders}"


APP_MODULES = [p for p in _python_sources() if p.parent == REPO_ROOT]


@pytest.mark.parametrize("path", APP_MODULES, ids=lambda p: p.name)
def test_no_silently_swallowed_exceptions(path):
    """`except ...: pass` discards the only evidence of what went wrong.

    In an app whose failure mode is "the stream just doesn't play and the screen
    reader says nothing", a swallowed traceback is the difference between a
    five-minute diagnosis and an unreproducible bug report. Handlers that really
    should do nothing belong in build tooling, not in the shipped modules.
    """
    tree = ast.parse(_read(path))
    offenders = [
        handler.lineno
        for handler in ast.walk(tree)
        if isinstance(handler, ast.ExceptHandler)
        and len(handler.body) == 1
        and isinstance(handler.body[0], ast.Pass)
    ]
    assert not offenders, (
        f"{path.name} swallows exceptions silently at line(s) {offenders}; "
        f"log at debug level with exc_info=True instead"
    )


# Provider credentials appear as user:pass in Xtream-style URLs.
_CREDENTIAL_RE = re.compile(
    r"(?:username|password)=(?!\{|%s|<|\$|your|USER|PASS|test|demo|fake)[A-Za-z0-9]{6,}",
    re.IGNORECASE,
)


@pytest.mark.parametrize("path", _python_sources(), ids=lambda p: p.name)
def test_no_hardcoded_provider_credentials(path):
    """Live subscription credentials must never be committed."""
    offenders = [
        num
        for num, line in enumerate(_read(path).splitlines(), 1)
        if _CREDENTIAL_RE.search(line)
    ]
    assert not offenders, (
        f"{path.name} looks like it contains real provider credentials "
        f"on line(s) {offenders}"
    )
