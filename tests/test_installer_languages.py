"""The Windows installer follows the Windows UI language (English, Hungarian)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "installer" / "AccessibleIPTVClient.iss"


def test_installer_picks_its_language_from_windows():
    script = SCRIPT.read_text(encoding="utf-8-sig")
    assert "LanguageDetectionMethod=uilanguage" in script
    assert "ShowLanguageDialog=no" in script
    assert "UsePreviousLanguage=no" in script
    # English is listed first, so it is the fallback for other UI languages.
    english = script.index('Name: "english"; MessagesFile: "compiler:Default.isl"')
    hungarian = script.index('Name: "hungarian"; MessagesFile: "compiler:Languages\\Hungarian.isl"')
    assert english < hungarian


def test_installer_wizard_texts_are_localized():
    script = SCRIPT.read_text(encoding="utf-8-sig")
    assert "{cm:CreateDesktopIcon}" in script
    assert "{cm:AdditionalIcons}" in script
    assert "{cm:LaunchProgram,{#MyAppDisplayName}}" in script
    assert "hungarian.LaunchProgram=%1 indítása" in script
    for hard_coded in ("Create a desktop shortcut", "Additional shortcuts:",
                       'Description: "Launch {#MyAppDisplayName}"'):
        assert hard_coded not in script


def test_installer_script_declares_utf8():
    # The Hungarian override has accented letters; the BOM keeps the compiler
    # from reading the script in the machine's ANSI code page.
    assert SCRIPT.read_bytes().startswith(b"\xef\xbb\xbf")
