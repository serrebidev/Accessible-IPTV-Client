"""Tests for the release/changelog workflow."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import release


def test_update_changelog_prepends_readable_release_notes(tmp_path):
    path = tmp_path / "CHANGELOG.md"
    path.write_text(
        "# Changelog\n\nExisting release history.\n",
        encoding="utf-8",
    )

    release.update_changelog(
        "1.2.3",
        "## Fixes\n- fix(accessibility): prevent stale focus\n\n## Other\n- docs: update help\n",
        release_date="2026-07-10",
        path=path,
    )

    content = path.read_text(encoding="utf-8")
    assert content.startswith("# Changelog\n\n")
    assert "## v1.2.3 - 2026-07-10\n\n- Prevent stale focus\n- Update help" in content
    assert content.index("## v1.2.3") < content.index("Existing release history.")


def test_update_changelog_refuses_duplicate_version(tmp_path):
    path = tmp_path / "CHANGELOG.md"
    path.write_text("# Changelog\n\n## v1.2.3 - 2026-07-10\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match=r"already contains v1\.2\.3"):
        release.update_changelog("1.2.3", "- fix: duplicate", path=path)


def test_release_commit_stages_changelog(monkeypatch):
    commands = []
    monkeypatch.setattr(release, "run", lambda command, **_kwargs: commands.append(command))

    release.git_commit_and_tag("1.2.3")

    assert commands[0] == ["git", "add", "app_meta.py", "CHANGELOG.md", "locale"]
    assert commands[1] == ["git", "commit", "-m", "chore(release): v1.2.3"]
    assert commands[2] == ["git", "tag", "v1.2.3"]
