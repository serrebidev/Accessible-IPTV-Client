"""Help > Report an issue on GitHub: the prefilled new-issue link."""
import app_meta
import dialogs_misc


def test_issue_url_carries_title_body_and_version():
    url = dialogs_misc.issue_url("Photo & video", "Line 1\nПривет")
    assert url.startswith(
        "https://github.com/serrebidev/Accessible-IPTV-Client/issues/new"
        "?title=Photo%20%26%20video&body=Line%201%0A%D0%9F"
    )
    assert "Accessible%20IPTV%20Client%20" + app_meta.APP_VERSION in url
    assert not any(c in url for c in " \n#")


def test_report_issue_opens_prefilled_page_and_cancel_opens_nothing(monkeypatch):
    opened = []
    monkeypatch.setattr(dialogs_misc.wx, "LaunchDefaultBrowser", opened.append)
    answers = iter([None])
    monkeypatch.setattr(dialogs_misc, "_ask_text", lambda *a: next(answers))
    dialogs_misc.report_issue(None)
    assert opened == []
    answers = iter(["Crash", "Steps"])
    dialogs_misc.report_issue(None)
    assert opened[0].startswith(
        "https://github.com/serrebidev/Accessible-IPTV-Client/issues/new?title=Crash&body=Steps")
