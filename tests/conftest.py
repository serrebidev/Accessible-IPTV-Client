"""Shared pytest setup.

Keeps wx's logging out of the GUI for the whole test session. Several tests exercise
error paths on purpose -- ``test_add_provider_source_survives_a_dialog_that_cannot_open``
feeds in a dialog class that raises -- and the production code answers by calling
``wx.LogError``. wx's default log target for an error is a *modal message box*, so
running the suite pops real dialogs onto the developer's screen ("_Boom could not be
opened: dialog exploded while building") and wx flushes whatever is still pending when
it tears down, with no event loop left to dismiss it. Routing the log to stderr keeps
those messages in the test output where they belong.

The target is installed once and never restored: ``wx.Log.SetActiveTarget`` takes
ownership of the target it is given and deletes the one it returns, so handing the old
pointer back at teardown is a use-after-free that crashes the interpreter with an
access violation on Windows.
"""

import pytest

try:
    import wx
except Exception:  # pragma: no cover - wx is absent on headless CI
    wx = None


@pytest.fixture(scope="session", autouse=True)
def _wx_log_to_stderr():
    if wx is not None and hasattr(wx, "LogStderr"):
        try:
            wx.Log.SetActiveTarget(wx.LogStderr())
        except Exception:
            pass
    yield
