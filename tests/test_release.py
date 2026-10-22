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
    assert ("## v1.2.3 - 2026-07-10\n\n"
            "### Bug fixes\n\n- Prevent stale focus\n\n"
            "### Other changes\n\n- Update help\n\n") in content
    assert content.index("## v1.2.3") < content.index("Existing release history.")


def test_update_changelog_without_sections_or_notes(tmp_path):
    path = tmp_path / "CHANGELOG.md"
    path.write_text("# Changelog\n\nOld.\n", encoding="utf-8")
    release.update_changelog("1.0.1", "- fix: a\n- fix: a\n", release_date="2026-01-01", path=path)
    release.update_changelog("1.0.2", "", release_date="2026-01-02", path=path)
    content = path.read_text(encoding="utf-8")
    assert "## v1.0.1 - 2026-01-01\n\n- A\n\n" in content
    assert "## v1.0.2 - 2026-01-02\n\n- No notable changes.\n\n" in content


def test_release_notes_group_commits_under_labels():
    commits = [
        {"subject": "feat: record from the player", "body": ""},
        {"subject": "fix(accessibility): announce focus", "body": ""},
        {"subject": "fix: stop crash", "body": ""},
        {"subject": "fix: stop crash", "body": ""},
        {"subject": "docs(i18n): fix Hungarian guide", "body": ""},
        {"subject": "Merge pull request #1", "body": ""},
        {"subject": "Tidy things", "body": ""},
    ]
    assert release.build_release_notes(commits) == (
        "## Features\n- Record from the player\n\n"
        "## Accessibility\n- Announce focus\n\n"
        "## Bug fixes\n- Stop crash\n\n"
        "## Documentation\n- Fix Hungarian guide\n\n"
        "## Other changes\n- Tidy things"
    )
    assert release.determine_bump(commits) == "minor"
    assert release.build_release_notes([]) == "## Other changes\n- No notable changes."


def test_update_changelog_refuses_duplicate_version(tmp_path):
    path = tmp_path / "CHANGELOG.md"
    path.write_text("# Changelog\n\n## v1.2.3 - 2026-07-10\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match=r"already contains v1\.2\.3"):
        release.update_changelog("1.2.3", "- fix: duplicate", path=path)


def test_build_without_the_user_guide_is_refused(tmp_path):
    with pytest.raises(RuntimeError, match=r"help_datas"):
        release.validate_bundled_user_guide(str(tmp_path))
    guide = tmp_path / "_internal" / "docs" / "help" / "en.md"
    guide.parent.mkdir(parents=True)
    guide.write_text("# User Guide {#user-guide}\n", encoding="utf-8")
    release.validate_bundled_user_guide(str(tmp_path))


def test_build_without_the_changelog_is_refused(tmp_path):
    with pytest.raises(RuntimeError, match=r"main\.spec datas"):
        release.validate_bundled_changelog(str(tmp_path))
    changelog = tmp_path / "_internal" / "CHANGELOG.md"
    changelog.parent.mkdir(parents=True)
    changelog.write_text("# Changelog\n", encoding="utf-8")
    release.validate_bundled_changelog(str(tmp_path))


def test_release_commit_stages_changelog(monkeypatch):
    commands = []
    monkeypatch.setattr(release, "run", lambda command, **_kwargs: commands.append(command))

    release.git_commit_and_tag("1.2.3")

    assert commands[0] == ["git", "add", "app_meta.py", "CHANGELOG.md", "locale"]
    assert commands[1] == ["git", "commit", "-m", "chore(release): v1.2.3"]
    assert commands[2] == ["git", "tag", "v1.2.3"]


def test_body_prose_mentioning_a_section_label_is_not_breaking():
    """v2.0.0 regression: a translation commit whose body mentions the
    "Breaking changes" section label was substring-matched and bumped major.
    Classification must read the subject (and a real footer), not body prose.
    """
    commit = {
        "subject": "i18n(hu): finalize v1.136.0 release-note localization",
        "body": (
            "- two recurring-label corrections (Breaking changes, No notable "
            "changes.)\n- refresh What's New introduction\n"
        ),
    }
    assert release.classify_commit(commit) == "Other"
    assert release.determine_bump([commit]) == "patch"


def test_explicit_breaking_markers_still_classify_as_breaking():
    assert release.classify_commit({"subject": "feat!: drop old config", "body": ""}) == "Breaking"
    assert release.classify_commit({"subject": "chore: x", "body": "BREAKING CHANGE: removed key"}) == "Breaking"
    assert release.classify_commit({"subject": "docs: x", "body": "Breaking changes:\n- removed key"}) == "Breaking"
    assert release.determine_bump([{"subject": "fix!: y", "body": ""}]) == "major"


def test_classification_does_not_read_body_prose_for_other_sections():
    docs = {"subject": "i18n(hu): fix catalogues", "body": "keeps the feature wording intact and bug notes out"}
    assert release.classify_commit(docs) == "Other"
    assert release.classify_commit({"subject": "refactor: tidy", "body": "no feature or bug here"}) == "Other"


def test_release_note_translation_commits_stay_out_of_the_changelog():
    """Issue #27: translating What's New must not create a new bullet."""
    commits = [
        {"subject": "i18n(hu): finish the remaining What's New translations (#26)", "body": "",
         "files": ["locale/hu/LC_MESSAGES/release_notes.po",
                   "locale/hu/LC_MESSAGES/release_notes.mo"]},
        {"subject": "i18n(hu): fix a menu label", "body": "",
         "files": ["locale/hu/LC_MESSAGES/iptvclient.po",
                   "locale/hu/LC_MESSAGES/release_notes.po"]},
        {"subject": "chore: tidy the build", "body": "Changelog: skip", "files": ["build.bat"]},
        {"subject": "fix: label the Cancel buttons", "body": "", "files": ["playlist.py"]},
        {"subject": "docs: no file list", "body": ""},
    ]
    notes = release.build_release_notes(commits)
    assert "What's New translations" not in notes
    assert "Tidy the build" not in notes
    assert "fix a menu label" in notes
    assert "- Label the Cancel buttons" in notes
    assert "- No file list" in notes


def test_release_note_only_commits_alone_give_no_notable_changes():
    commits = [{"subject": "i18n(hu): translate What's New", "body": "",
                "files": ["locale/hu/LC_MESSAGES/release_notes.po"]}]
    assert release.build_release_notes(commits).endswith("No notable changes.")
    assert release.determine_bump(commits) == "patch"


# --------------------------------------------------------------------------- #
# The signature check
# --------------------------------------------------------------------------- #
def test_an_artifact_signed_with_another_certificate_is_refused(monkeypatch):
    """The updater pins one certificate.

    A release that ships an installer signed with another one is refused by
    every installed client, and a published release cannot be taken back.
    """
    monkeypatch.setattr(release, "read_signature", lambda path: ("OTHER0000", "Valid"))
    with pytest.raises(RuntimeError, match="signed with"):
        release.verify_signature("installer.exe", "MYPIN0000")


def test_an_artifact_with_a_broken_signature_is_refused(monkeypatch):
    """A signature that does not match its file (HashMismatch) is not good."""
    monkeypatch.setattr(release, "read_signature", lambda path: ("MYPIN0000", "HashMismatch"))
    with pytest.raises(RuntimeError, match="signature is"):
        release.verify_signature("installer.exe", "MYPIN0000")


def test_the_release_does_not_publish_what_it_has_not_verified(monkeypatch):
    """Nothing is committed, pushed or published before the check."""
    published = []
    calls = []

    monkeypatch.setattr(sys, "argv", ["release.py", "release"])
    monkeypatch.setattr(release, "compute_next_version",
                        lambda: ("v1.2.3", "1.2.3", [], "patch"))
    monkeypatch.setattr(release, "build_release_notes", lambda commits: "## Bug fixes\n- x\n")
    monkeypatch.setattr(release.translation_audit, "require_complete", lambda *a, **k: None)
    monkeypatch.setattr(release, "update_version_file", lambda version: None)
    monkeypatch.setattr(release, "update_changelog", lambda version, notes, **k: None)
    monkeypatch.setattr(release, "sync_translations", lambda: None)
    monkeypatch.setattr(release, "validate_ffmpeg_binary", lambda *a, **k: None)
    monkeypatch.setattr(release, "clean_build_artifacts", lambda: None)
    monkeypatch.setattr(release, "run_pyinstaller", lambda: None)
    monkeypatch.setattr(release, "validate_no_bundled_config", lambda: None)
    monkeypatch.setattr(release, "validate_bundled_user_guide", lambda *a, **k: None)
    monkeypatch.setattr(release, "validate_bundled_changelog", lambda *a, **k: None)
    monkeypatch.setattr(release, "sign_executable", lambda path: None)
    monkeypatch.setattr(release, "get_signing_thumbprint", lambda path: "MYPIN0000")
    monkeypatch.setattr(release, "build_installer", lambda version, **k: "installer.exe")
    monkeypatch.setattr(release, "build_assets", lambda *a, **k: {})
    monkeypatch.setattr(release, "git_commit_and_tag", lambda version: calls.append("commit"))
    monkeypatch.setattr(release, "git_push", lambda version: calls.append("push"))
    monkeypatch.setattr(release, "gh_release_create",
                        lambda version, assets: published.append(version))
    monkeypatch.setattr(release, "release_other_platforms", lambda version: None)
    # The installer was signed with another certificate than the app.
    monkeypatch.setattr(
        release, "read_signature",
        lambda path: ("OTHER0000", "Valid") if "installer" in path else ("MYPIN0000", "Valid"),
    )

    with pytest.raises(RuntimeError, match="signed with"):
        release.main()

    assert published == [], "the release was published without a verified signature"
    assert calls == [], "the release was committed or pushed before it was verified"
