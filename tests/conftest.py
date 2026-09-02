"""Shared pytest setup.

Keeps wx's error logging out of modal dialogs for the whole test session.

Several tests exercise failure paths on purpose -- ``test_add_provider_source_survives_a_
dialog_that_cannot_open`` feeds in a dialog class that raises -- and the production code
answers by calling ``wx.LogError``. wx's default target for an error under a GUI app is a
*modal message box*, so running the suite threw real dialogs onto the developer's screen
("_Boom could not be opened: dialog exploded while building") and then blocked at exit
until somebody clicked OK, with no event loop and no visible window to find. That reads
as a hung test run rather than as a dialog waiting for input, and with a screen reader it
is worse than merely annoying.

Setting the target once at session start is not enough: constructing ``wx.App`` installs
wx's own GUI log target and discards ours. So the target is re-checked immediately before
every test body, by which point any ``wx.App`` built by a fixture already exists.

The target is never restored afterwards. ``wx.Log.SetActiveTarget`` takes ownership of the
target it is given and deletes the one it returns, so handing an old pointer back is a
use-after-free that kills the interpreter with a Windows access violation.
"""

import pytest

try:
    import wx
except Exception:  # pragma: no cover - wx is absent on headless CI
    wx = None


def _ensure_stderr_log_target():
    """Point wx's logging at stderr unless it is already there."""
    if wx is None or not hasattr(wx, "LogStderr"):
        return
    try:
        if isinstance(wx.Log.GetActiveTarget(), wx.LogStderr):
            return
        wx.Log.SetActiveTarget(wx.LogStderr())
    except Exception:  # pragma: no cover - never fail a run over logging
        pass


@pytest.fixture(scope="session", autouse=True)
def _wx_log_to_stderr():
    # Covers anything logged before the first test body runs.
    _ensure_stderr_log_target()
    yield


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    # Fixtures have finished, so a wx.App created by one is already up and has had its
    # chance to install the GUI log target over ours.
    if wx is not None and wx.GetApp() is not None:
        _ensure_stderr_log_target()
    return (yield)
