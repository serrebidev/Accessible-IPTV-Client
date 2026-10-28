"""Dialogs that do not own the modal message queue.

The dialogs that call ``message_box`` stay in main.py: the app patches that
name there. These are self-contained wx.Dialog subclasses.
"""
import datetime
import logging
import os
import sys
import threading
from typing import Dict, List, Optional, Tuple

import wx
import wx.adv

import account_info
import app_meta
import release_notes
from app_links import PROJECT_GITHUB_URL, SERREBI_GITHUB_URL, TELEGRAM_SUPPORT_URL
from channel_widgets import _VirtualWhatsOnList
from dialog_utils import _context_row_index
from i18n import gettext as _
from options import utc_to_local

LOG = logging.getLogger("EPG.ui")


class AccessibleAboutDialog(wx.Dialog):
    """A keyboard-first About dialog whose support links are real tab stops."""

    help_topic = "support"

    def __init__(self, parent):
        from app_meta import APP_DISPLAY_NAME, APP_VERSION

        super().__init__(
            parent,
            title=_("About {name}").format(name=APP_DISPLAY_NAME),
            style=wx.DEFAULT_DIALOG_STYLE,
        )
        panel = wx.Panel(self)
        layout = wx.BoxSizer(wx.VERTICAL)

        heading = wx.StaticText(
            panel,
            label=_("{name} {version}").format(name=APP_DISPLAY_NAME, version=APP_VERSION),
        )
        heading.SetFont(heading.GetFont().Bold())
        layout.Add(heading, 0, wx.ALL, 12)

        description = wx.StaticText(
            panel,
            label=_("A screen reader accessible IPTV client for Windows and Linux.\n\n"
                    "Supports M3U/M3U Plus playlists, Stalker Portal, Xtream Codes, "
                    "built-in VLC playback, casting, and XMLTV EPG."),
        )
        description.Wrap(500)
        layout.Add(description, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        support = wx.StaticText(panel, label=_("Community and support"))
        support.SetFont(support.GetFont().Bold())
        layout.Add(support, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        for label, url in (
            (_("Join the SerrebiProjects Telegram group"), TELEGRAM_SUPPORT_URL),
            (_("Open the Accessible IPTV Client project on GitHub"), PROJECT_GITHUB_URL),
            (_("Follow Serrebi on GitHub"), SERREBI_GITHUB_URL),
        ):
            link = wx.adv.HyperlinkCtrl(panel, label=label, url=url)
            link.SetName(label)
            # wxMSW's HyperlinkCtrl has no key handling of its own: with the
            # dialog's default OK button present, Enter and Space closed the
            # About dialog instead of opening the link. Route those two keys
            # (and the click) to the browser -- and *only* those two. The
            # handler used to open the link for every key, so Tab (and every
            # arrow key) launched a browser window while merely moving through
            # the dialog; a few presses buried the screen in windows.
            def _open_link(_event=None, _url=url):
                wx.LaunchDefaultBrowser(_url)

            def _on_link_key(event, _open=_open_link):
                if event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER, wx.WXK_SPACE):
                    _open()
                    return
                event.Skip()

            link.Bind(wx.EVT_CHAR_HOOK, _on_link_key)
            link.Bind(wx.adv.EVT_HYPERLINK, _open_link)
            link.Bind(wx.EVT_LEFT_DCLICK, _open_link)
            layout.Add(link, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Create buttons on the panel and handle both exit paths explicitly.
        # ``CreateButtonSizer`` creates children of the dialog itself; placing
        # those children in a panel sizer leaves wxMSW without a usable command
        # route, which made the original About dialog impossible to dismiss.
        button_sizer = wx.StdDialogButtonSizer()
        self.ok_btn = wx.Button(panel, id=wx.ID_OK, label=_("OK"))
        self.close_btn = wx.Button(panel, id=wx.ID_CANCEL, label=_("Close"))
        button_sizer.AddButton(self.ok_btn)
        button_sizer.AddButton(self.close_btn)
        button_sizer.Realize()
        layout.Add(button_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 12)
        panel.SetSizerAndFit(layout)
        self.SetMinSize((540, -1))
        self.Fit()
        self.CentreOnParent()
        self.ok_btn.Bind(wx.EVT_BUTTON, lambda _event: self._finish(wx.ID_OK))
        self.close_btn.Bind(wx.EVT_BUTTON, lambda _event: self._finish(wx.ID_CANCEL))
        self.Bind(wx.EVT_CLOSE, lambda _event: self._finish(wx.ID_CANCEL))
        self.SetEscapeId(wx.ID_CANCEL)
        self.ok_btn.SetDefault()

    def _finish(self, result):
        if self.IsModal():
            self.EndModal(result)
        else:
            self.Destroy()


def changelog_path() -> str:
    """Absolute path of the release history shipped with this application."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", None) or os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "CHANGELOG.md")


class ChangelogDialog(wx.Dialog):
    # F1 inside this window opens the guide at its own section.
    help_topic = "updates"
    """A read-only, copyable view of the complete bundled release history.

    Section labels and the notes of the newest releases are shown in the
    interface language when translated (see release_notes.py); the rest stays
    English.
    """

    def __init__(self, parent, path: Optional[str] = None):
        super().__init__(parent, title=_("What's New"), size=(820, 580),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX)
        try:
            with open(path or changelog_path(), "r", encoding="utf-8") as handle:
                history = release_notes.localize_changelog(
                    handle.read(), app_meta.APP_DISPLAY_NAME)
        except OSError:
            LOG.exception("Could not read the bundled changelog")
            history = _("No release history is available.")

        panel = wx.Panel(self)
        layout = wx.BoxSizer(wx.VERTICAL)
        recent_history, older_history = release_notes.split_changelog_window(history)
        self._recent_history = recent_history
        self._older_history = older_history
        self._older_shown = False
        self.text = wx.TextCtrl(panel, value=recent_history,
                                style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        self.text.SetName(_("Release history"))
        # The full history stays one screen-reader document: the toggle only
        # appends the older English entries below a labelled separator, so
        # nothing is ever unloaded from the text control (issue #28).
        self.toggle_btn = None
        if older_history.strip():
            self.toggle_btn = wx.Button(panel, label=_("Show older releases (English)"))
            self.toggle_btn.Bind(wx.EVT_BUTTON, self._on_toggle_older)
        close_btn = wx.Button(panel, id=wx.ID_CANCEL, label=_("Close"))
        layout.Add(self.text, 1, wx.EXPAND | wx.ALL, 10)
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        if self.toggle_btn is not None:
            btn_sizer.Add(self.toggle_btn, 0, wx.LEFT | wx.BOTTOM, 10)
        btn_sizer.AddStretchSpacer(1)
        btn_sizer.Add(close_btn, 0, wx.RIGHT | wx.BOTTOM, 10)
        layout.Add(btn_sizer, 0, wx.EXPAND)
        panel.SetSizer(layout)
        self.SetMinSize((520, 380))
        self.CentreOnParent()
        close_btn.Bind(wx.EVT_BUTTON, lambda _event: self._finish())
        self.Bind(wx.EVT_CLOSE, lambda _event: self._finish())
        self.SetEscapeId(wx.ID_CANCEL)
        wx.CallAfter(self.text.SetFocus)

    def _on_toggle_older(self, _event) -> None:
        """Show or hide the older English release entries in place."""
        if self.toggle_btn is None:
            return
        if self._older_shown:
            self.text.SetValue(self._recent_history)
            self.text.SetInsertionPoint(0)
            self.toggle_btn.SetLabel(_("Show older releases (English)"))
            self._older_shown = False
        else:
            separator = _("Older releases (English)")
            self.text.SetValue(
                self._recent_history.rstrip() + "\n\n" + separator + "\n\n"
                + self._older_history.lstrip())
            # Land the caret at the separator so screen readers announce the
            # newly revealed section; the toggle keeps focus for a quick hide.
            self.text.SetInsertionPoint(len(self._recent_history.rstrip()) + 2)
            self.toggle_btn.SetLabel(_("Hide older releases"))
            self._older_shown = True
        self.toggle_btn.SetFocus()

    def _finish(self) -> None:
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)
        else:
            self.Destroy()


class CastDiscoveryDialog(wx.Dialog):
    help_topic = "casting"

    def __init__(self, parent, caster):
        super().__init__(parent, title=_("Select Device to Cast"), size=(450, 350))
        self.parent_frame = parent
        self.caster = caster
        self.devices: List[object] = []

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.status_lbl = wx.StaticText(panel, label=_("Searching for devices..."))
        self.devices_label = wx.StaticText(panel, label=_("Select Device to Cast"))
        self.listbox = wx.ListBox(panel, style=wx.LB_SINGLE)
        self.listbox.SetName(_("Select Device to Cast"))

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.ok_btn = wx.Button(panel, id=wx.ID_OK, label=_("Connect"))
        self.ok_btn.Disable()
        cancel_btn = wx.Button(panel, id=wx.ID_CANCEL, label=_("Cancel"))

        btn_sizer.AddStretchSpacer(1)
        btn_sizer.Add(self.ok_btn, 0, wx.ALL, 5)
        btn_sizer.Add(cancel_btn, 0, wx.ALL, 5)

        sizer.Add(self.status_lbl, 0, wx.ALL, 10)
        sizer.Add(self.devices_label, 0, wx.LEFT | wx.RIGHT, 10)
        sizer.Add(self.listbox, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        sizer.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 10)

        panel.SetSizer(sizer)

        self.listbox.Bind(wx.EVT_LISTBOX, self._on_select)
        self.listbox.Bind(wx.EVT_LISTBOX_DCLICK, self._on_dclick)

        self.CenterOnParent()

        # Start discovery
        self._start_discovery()

    def _start_discovery(self):
        def do_scan():
            try:
                # caster.discover_all() is synchronous and thread-safe (uses internal loop)
                devices = self.caster.discover_all()
                wx.CallAfter(self._update_list, devices)
            except Exception as e:
                wx.CallAfter(self._show_scan_error, e)

        threading.Thread(target=do_scan, daemon=True).start()

    def _show_scan_error(self, error):
        # The scan outlives the dialog when it is cancelled mid-search.
        if not self:
            return
        self.status_lbl.SetLabel(_("Error: {error}").format(error=error))

    def _update_list(self, devices: List[object]):
        if not self:
            return
        self.devices = devices
        self.listbox.Clear()
        if not devices:
            self.status_lbl.SetLabel(_("No devices found."))
            return

        self.status_lbl.SetLabel(_("Found {count} devices:").format(count=len(devices)))
        for dev in devices:
            self.listbox.Append(dev.display_name)

        # Select the first device so Connect works straight from the keyboard.
        self.listbox.SetSelection(0)
        self.ok_btn.Enable()

    def _on_select(self, event):
        sel = self.listbox.GetSelection()
        if sel != wx.NOT_FOUND and 0 <= sel < len(self.devices):
            self.ok_btn.Enable()
        else:
            self.ok_btn.Disable()

    def _on_dclick(self, event):
        if self.listbox.GetSelection() != wx.NOT_FOUND:
            self.EndModal(wx.ID_OK)

    def get_selected_device(self) -> Optional[object]:
        sel = self.listbox.GetSelection()
        if sel != wx.NOT_FOUND and 0 <= sel < len(self.devices):
            return self.devices[sel]
        return None


class AccountInfoDialog(wx.Dialog):
    # F1 inside this window opens the guide at its own section.
    help_topic = "account-info"
    """Subscription status for every provider account the app can find.

    Deliberately two controls: a list of accounts and one read-only multiline
    field holding the whole report. That is the shape a screen reader handles
    best - arrow through the accounts, tab once, read the details top to bottom.
    Each lookup is a blocking HTTP request, so it runs on a worker thread and
    results are matched against a request token before being displayed.
    """

    help_topic = "account-info"

    def __init__(self, parent, accounts: List[account_info.Account]):
        super().__init__(
            parent,
            title=_("Account Info"),
            size=(700, 520),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.accounts = accounts
        self._reports: Dict[int, str] = {}
        self._request_token = 0
        self._alive = True

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        intro = wx.StaticText(panel, label=_("Select an account to check its status:"))
        list_label = wx.StaticText(panel, label=_("Accounts") + ":")
        self.listbox = wx.ListBox(panel, style=wx.LB_SINGLE)
        self._label_control(self.listbox, _("Accounts"))
        for account in accounts:
            self.listbox.Append(account_info.account_label(account))

        details_label = wx.StaticText(panel, label=_("Account details") + ":")
        self.details = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY)
        self._label_control(self.details, _("Account details"))

        self.status_lbl = wx.StaticText(panel, label="")

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.refresh_btn = wx.Button(panel, label=_("Refresh"))
        self.copy_btn = wx.Button(panel, label=_("Copy Details"))
        close_btn = wx.Button(panel, id=wx.ID_CANCEL, label=_("Close"))
        btn_sizer.Add(self.refresh_btn, 0, wx.ALL, 5)
        btn_sizer.Add(self.copy_btn, 0, wx.ALL, 5)
        btn_sizer.AddStretchSpacer(1)
        btn_sizer.Add(close_btn, 0, wx.ALL, 5)

        sizer.Add(intro, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        sizer.Add(list_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        sizer.Add(self.listbox, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        sizer.Add(details_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        sizer.Add(self.details, 2, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        sizer.Add(self.status_lbl, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        sizer.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 5)
        panel.SetSizer(sizer)

        self.listbox.Bind(wx.EVT_LISTBOX, self._on_select)
        self.refresh_btn.Bind(wx.EVT_BUTTON, self._on_refresh)
        self.copy_btn.Bind(wx.EVT_BUTTON, self._on_copy)
        close_btn.Bind(wx.EVT_BUTTON, self._on_close_button)
        self.Bind(wx.EVT_CLOSE, self._on_close_window)
        self.SetEscapeId(wx.ID_CANCEL)

        self.SetMinSize((520, 420))
        self.Layout()
        self.CenterOnParent()

        if accounts:
            self.listbox.SetSelection(0)
            self.listbox.SetFocus()
            self._start_lookup(0)

    @staticmethod
    def _label_control(ctrl, label):
        ctrl.SetName(label)
        if hasattr(ctrl, "SetAccessibleName"):
            ctrl.SetAccessibleName(label)

    # ------------------------------------------------------------------ #
    # Lookups
    # ------------------------------------------------------------------ #
    def _start_lookup(self, index: int, force: bool = False):
        if not (0 <= index < len(self.accounts)):
            return
        self._request_token += 1
        token = self._request_token
        if not force and index in self._reports:
            self._apply_report(token, index, self._reports[index])
            return
        account = self.accounts[index]
        self.details.SetValue(_("Checking account, please wait..."))
        self.status_lbl.SetLabel(_("Checking {account}...").format(
            account=account_info.account_label(account)))
        self.refresh_btn.Disable()

        def worker():
            try:
                report = account_info.fetch_account_report(account)
            except Exception as e:
                LOG.debug("AccountInfoDialog: account lookup failed", exc_info=True)
                wx.CallAfter(self._lookup_failed, token, index, str(e))
                return
            wx.CallAfter(self._lookup_finished, token, index, report)

        threading.Thread(target=worker, daemon=True).start()

    def _lookup_finished(self, token: int, index: int, report: str):
        self._reports[index] = report
        self._apply_report(token, index, report)

    def _lookup_failed(self, token: int, index: int, error: str):
        # Errors are not cached: re-selecting the account should retry it.
        self._apply_report(
            token,
            index,
            _("Could not check this account.\n\n{error}").format(error=error),
            ok=False,
        )

    def _apply_report(self, token: int, index: int, report: str, ok: bool = True):
        if not self._alive or token != self._request_token:
            return
        try:
            self.details.SetValue(report)
            # Reading starts at the top, not wherever the previous report ended.
            self.details.SetInsertionPoint(0)
            self.status_lbl.SetLabel(_("Ready.") if ok else _("Check failed."))
            self.refresh_btn.Enable()
        except RuntimeError:
            LOG.debug("AccountInfoDialog._apply_report: dialog already gone", exc_info=True)

    # ------------------------------------------------------------------ #
    # Events
    # ------------------------------------------------------------------ #
    def _on_select(self, _event):
        self._start_lookup(self.listbox.GetSelection())

    def _on_refresh(self, _event):
        self._start_lookup(self.listbox.GetSelection(), force=True)

    def _on_copy(self, _event):
        text = self.details.GetValue()
        if not text:
            return
        if not wx.TheClipboard.Open():
            self.status_lbl.SetLabel(_("Could not open the clipboard."))
            return
        try:
            wx.TheClipboard.SetData(wx.TextDataObject(text))
            wx.TheClipboard.Flush()
        finally:
            wx.TheClipboard.Close()
        self.status_lbl.SetLabel(_("Account details copied to the clipboard."))

    def _on_close_button(self, _event):
        self._alive = False
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)
        else:
            self.Destroy()

    def _on_close_window(self, event):
        self._alive = False
        event.Skip()


class CatchupDialog(wx.Dialog):
    """Choose one catch-up programme, then open or download it.

    The two actions live only in the list's context menu (right-click / Apps
    key) and on Enter (open): no buttons at all sit in the Tab chain. Tab from
    the list reaches a read-only description of the highlighted programme, and
    Tab again comes straight back to the list. Escape closes the dialog.
    """

    help_topic = "catch-up"

    def __init__(self, parent, channel_name: str, programmes: List[Dict[str, str]],
                 initial_start: str = ""):
        title = channel_name or _("Catch-up")
        super().__init__(parent, title=_("Catch-up: {name}").format(name=title), size=(520, 360))
        self.programmes = programmes
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        intro = wx.StaticText(panel, label=_(
            "Select a programme, then press Enter to open it, or use the "
            "context menu to download it. Press Escape to close."))
        self.listbox = wx.ListBox(panel, style=wx.LB_SINGLE)
        for prog in programmes:
            self.listbox.Append(self._format_programme(prog))
        if programmes:
            # Back from the player, the list opens on the programme that was
            # playing rather than at the top.
            initial = next((i for i, prog in enumerate(programmes)
                            if initial_start and prog.get("start") == initial_start), 0)
            self.listbox.SetSelection(initial)
        # Tab from the list lands here: the description of the highlighted
        # programme, read-only, updated as the selection moves. Same pattern
        # as the EPG dialog, and one less reason to open the EPG by hand.
        self.description_label = wx.StaticText(panel, label=_("Description"))
        self.description_field = wx.TextCtrl(
            panel, size=(-1, 90), style=wx.TE_READONLY | wx.TE_MULTILINE)
        self.description_field.SetName(_("Episode description"))

        # There is no Close button. It was the third stop in a three-control
        # Tab ring and did nothing Escape does not already do, so Tab from the
        # description landed on a button whose only job was to be tabbed past
        # on the way back to the list. Escape is handled below, for every
        # control in the dialog.
        sizer.Add(intro, 0, wx.ALL, 10)
        sizer.Add(self.listbox, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        sizer.Add(self.description_label, 0, wx.LEFT | wx.RIGHT, 10)
        sizer.Add(self.description_field, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        panel.SetSizer(sizer)
        self.listbox.SetName(_("Catch-up programmes"))
        self.listbox.Bind(wx.EVT_LISTBOX, lambda _evt: self._update_description())
        self.listbox.Bind(wx.EVT_LISTBOX_DCLICK, self._on_listbox_activate)
        # EVT_CHAR_HOOK, not EVT_KEY_DOWN: a dialog consumes Enter before the
        # focused control ever sees a key-down, which is why pressing Enter on
        # a catch-up programme used to do nothing at all.
        self.listbox.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        self.listbox.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)
        self.description_field.Bind(wx.EVT_CHAR_HOOK, self._on_description_key)
        # With no wxID_CANCEL button left, wx has nothing to click for Escape,
        # so close the dialog here. The bind is on the dialog: an unhandled
        # char hook from any child bubbles up to it.
        self.Bind(wx.EVT_CHAR_HOOK, self._on_dialog_key)
        self.SetEscapeId(wx.ID_CANCEL)
        self.SetMinSize((420, 380))
        self.Layout()
        self.CenterOnParent()
        self._update_description()

    def _on_dialog_key(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CANCEL)
            return
        event.Skip()

    def _format_programme(self, prog: Dict[str, str]) -> str:
        try:
            start = datetime.datetime.strptime(prog.get("start", ""), "%Y%m%d%H%M%S").replace(tzinfo=datetime.timezone.utc)
            end = datetime.datetime.strptime(prog.get("end", ""), "%Y%m%d%H%M%S").replace(tzinfo=datetime.timezone.utc)
            start_local = utc_to_local(start)
            end_local = utc_to_local(end)
            window = f"{start_local.strftime('%Y-%m-%d %H:%M')} – {end_local.strftime('%H:%M')}"
        except Exception:
            window = prog.get("start", "")
        title = prog.get("title", "") or _("(No title)")
        return f"{window}  |  {title}"

    def _on_listbox_activate(self, _):
        if self.programmes:
            self.EndModal(wx.ID_OK)

    def _on_description_key(self, event):
        # Both directions go back to the list: it and the description are the
        # only two controls, so Tab is a two-stop ring, not a walk past a
        # button on the way round.
        if event.GetKeyCode() == wx.WXK_TAB:
            self.listbox.SetFocus()
            return
        event.Skip()

    def _update_description(self):
        idx = self.listbox.GetSelection()
        prog = self.programmes[idx] if 0 <= idx < len(self.programmes) else None
        description = (prog.get("description") or "").strip() if prog else ""
        text = description or _("No description available for this programme.")
        if self.description_field.GetValue() != text:
            self.description_field.SetValue(text)

    def _on_key(self, event):
        key = event.GetKeyCode()
        if key == wx.WXK_TAB:
            # Forwards to the description, backwards to it as well: the ring
            # holds two controls, so either Tab direction reaches the same
            # place and the pair stays reversible.
            self.description_field.SetFocus()
        elif key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self._on_listbox_activate(None)
        elif key == wx.WXK_WINDOWS_MENU:
            # The keyboard's context-menu key must work without a mouse.
            # WXK_MENU is Alt, not the Applications key; on a char hook that
            # would pop the menu open every time the user reached for Alt.
            self._show_context_menu(keyboard=True)
        else:
            event.Skip()

    def _on_context_menu(self, _event):
        self._show_context_menu(keyboard=False)

    def _show_context_menu(self, keyboard: bool):
        if self.listbox.GetSelection() == wx.NOT_FOUND and self.programmes:
            self.listbox.SetSelection(0)
        menu = wx.Menu()
        open_item = menu.Append(wx.ID_ANY, _("Open"))
        menu.Bind(wx.EVT_MENU, lambda _evt: self.EndModal(wx.ID_OK), open_item)
        download_item = menu.Append(wx.ID_ANY, _("Download"))
        menu.Bind(wx.EVT_MENU, lambda _evt: self.EndModal(wx.ID_SAVE), download_item)
        pos = wx.DefaultPosition
        if keyboard:
            selection = self.listbox.GetSelection()
            if selection != wx.NOT_FOUND:
                try:
                    rect = self.listbox.GetItemRect(selection)
                    if rect.width or rect.height:
                        pos = self.listbox.ClientToScreen(rect.GetBottomLeft())
                except Exception:
                    LOG.debug("CatchupDialog._show_context_menu: ignored exception", exc_info=True)
        try:
            self.listbox.PopupMenu(menu, pos)
        finally:
            menu.Destroy()

    def get_selection(self) -> Optional[Dict[str, str]]:
        idx = self.listbox.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(self.programmes):
            return None
        return self.programmes[idx]


class AudioTrackPreferenceDialog(wx.Dialog):
    """Which audio track the built-in player should choose by itself.

    Channels that carry an audio description track put it beside the ordinary one
    and start on the ordinary one, so a viewer who needs the description has had to
    switch by hand on every single channel. This is the setting that stops that.
    """

    _WRAP_WIDTH = 430
    help_topic = "preferred-audio-track"

    def __init__(self, parent, keywords=None, prefer_audio_description: bool = False):
        super().__init__(parent, title=_("Preferred Audio Track"))
        sizer = wx.BoxSizer(wx.VERTICAL)

        intro = wx.StaticText(self, label=_(
            "When a channel offers more than one audio track, the built-in player can "
            "switch to the track you want on its own."))
        intro.Wrap(self._WRAP_WIDTH)
        sizer.Add(intro, 0, wx.ALL, 10)

        self.ad_check = wx.CheckBox(self, label=_(
            "Prefer an audio description track when the channel has one"))
        self.ad_check.SetValue(bool(prefer_audio_description))
        self._label_control(self.ad_check, _("Prefer an audio description track when the channel has one"))
        sizer.Add(self.ad_check, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        keywords_label = _("Preferred track names or languages, most wanted first:")
        sizer.Add(wx.StaticText(self, label=keywords_label), 0, wx.LEFT | wx.RIGHT, 10)
        self.keywords_txt = wx.TextCtrl(self, value=", ".join(str(k) for k in (keywords or [])))
        self._label_control(self.keywords_txt, keywords_label)
        sizer.Add(self.keywords_txt, 0, wx.EXPAND | wx.ALL, 10)

        hint = wx.StaticText(self, label=_(
            "Separate them with commas, for example: audio description, English. A "
            "track is used when its name contains one of these words. Leave this empty "
            "to keep whatever track the channel starts on."))
        hint.Wrap(self._WRAP_WIDTH)
        sizer.Add(hint, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        sizer.Add(self.CreateButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALL | wx.ALIGN_RIGHT, 10)
        # Stock buttons take wxWidgets' own captions; use the app's (issue #29).
        for button_id, label in ((wx.ID_OK, _("OK")), (wx.ID_CANCEL, _("Cancel"))):
            button = self.FindWindowById(button_id)
            if button:
                button.SetLabel(label)
        self.SetSizerAndFit(sizer)
        self.CenterOnParent()
        wx.CallAfter(self.ad_check.SetFocus)

    @staticmethod
    def _label_control(ctrl, label):
        ctrl.SetName(label)
        if hasattr(ctrl, "SetAccessibleName"):
            ctrl.SetAccessibleName(label)

    def get_keywords(self) -> List[str]:
        from options import coerce_string_list

        return coerce_string_list(self.keywords_txt.GetValue())

    def get_prefer_audio_description(self) -> bool:
        return bool(self.ad_check.GetValue())


class RecordingPaddingDialog(wx.Dialog):
    """Accessible settings for scheduled-recording lead-in and lead-out."""

    MAX_PADDING_MINUTES = 180
    help_topic = "schedule-padding"

    def __init__(self, parent, before_minutes=0, after_minutes=2):
        super().__init__(parent, title=_("Schedule Padding"), style=wx.DEFAULT_DIALOG_STYLE)
        sizer = wx.BoxSizer(wx.VERTICAL)

        intro = wx.StaticText(self, label=_(
            "Start scheduled recordings early or keep recording after the programme ends. "
            "Manual recordings are not changed."))
        intro.Wrap(430)
        sizer.Add(intro, 0, wx.ALL, 12)

        grid = wx.FlexGridSizer(2, 2, 8, 10)
        before_label = _("Minutes before programme:")
        after_label = _("Minutes after programme:")
        self.before_ctrl = wx.SpinCtrl(
            self, min=0, max=self.MAX_PADDING_MINUTES,
            initial=self._coerce_minutes(before_minutes),
        )
        self.after_ctrl = wx.SpinCtrl(
            self, min=0, max=self.MAX_PADDING_MINUTES,
            initial=self._coerce_minutes(after_minutes),
        )
        for label, control in ((before_label, self.before_ctrl), (after_label, self.after_ctrl)):
            grid.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            control.SetName(label)
            if hasattr(control, "SetAccessibleName"):
                control.SetAccessibleName(label)
            grid.Add(control, 0, wx.EXPAND)
        grid.AddGrowableCol(1, 1)
        sizer.Add(grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        buttons = wx.StdDialogButtonSizer()
        self.ok_btn = wx.Button(self, id=wx.ID_OK, label=_("OK"))
        self.cancel_btn = wx.Button(self, id=wx.ID_CANCEL, label=_("Cancel"))
        buttons.AddButton(self.ok_btn)
        buttons.AddButton(self.cancel_btn)
        buttons.Realize()
        sizer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.ALL, 12)

        self.SetSizerAndFit(sizer)
        self.CentreOnParent()
        self.ok_btn.Bind(wx.EVT_BUTTON, lambda _event: self._finish(wx.ID_OK))
        self.cancel_btn.Bind(wx.EVT_BUTTON, lambda _event: self._finish(wx.ID_CANCEL))
        self.Bind(wx.EVT_CLOSE, lambda _event: self._finish(wx.ID_CANCEL))
        self.SetEscapeId(wx.ID_CANCEL)
        self.ok_btn.SetDefault()
        self.before_ctrl.SetFocus()

    @classmethod
    def _coerce_minutes(cls, value) -> int:
        try:
            return max(0, min(int(float(value)), cls.MAX_PADDING_MINUTES))
        except Exception:
            return 0

    def get_padding(self) -> Tuple[int, int]:
        return self.before_ctrl.GetValue(), self.after_ctrl.GetValue()

    def _finish(self, result):
        if self.IsModal():
            self.EndModal(result)
        else:
            self.Destroy()


class ShutdownCountdownDialog(wx.Dialog):
    """The last chance to stop the computer powering off after a recording.

    Modeless and parentless on purpose: it has to appear even when the main window
    is minimized to the tray, which is exactly where it will be at 3am.
    """

    COUNTDOWN_SECONDS = 60
    help_topic = "shutdown-after-recordings"
    # Closes itself when the countdown ends, so F1 help opens over the main window.
    can_host_help = False

    def __init__(self, parent, on_cancel, on_shutdown, seconds: Optional[int] = None):
        super().__init__(parent, title=_("Shut Down After Recordings"),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.STAY_ON_TOP)
        self._on_cancel_cb = on_cancel
        self._on_shutdown_cb = on_shutdown
        self._remaining = int(self.COUNTDOWN_SECONDS if seconds is None else seconds)
        self._finished = False

        sizer = wx.BoxSizer(wx.VERTICAL)
        self.message = wx.StaticText(self, label=self._message_text())
        self.message.Wrap(400)
        sizer.Add(self.message, 0, wx.ALL, 12)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.cancel_btn = wx.Button(self, id=wx.ID_CANCEL, label=_("Cancel Shutdown"))
        self.shutdown_btn = wx.Button(self, label=_("Shut Down Now"))
        buttons.Add(self.cancel_btn, 0, wx.RIGHT, 8)
        buttons.Add(self.shutdown_btn, 0)
        sizer.Add(buttons, 0, wx.ALL | wx.ALIGN_RIGHT, 12)
        self.SetSizerAndFit(sizer)

        self.cancel_btn.Bind(wx.EVT_BUTTON, lambda _evt: self._cancel())
        self.shutdown_btn.Bind(wx.EVT_BUTTON, lambda _evt: self._shutdown())
        self.Bind(wx.EVT_CLOSE, lambda _evt: self._cancel())
        # Cancel is both the default and focused: a dialog that appeared on its own
        # must not power the machine off because Enter or Escape was already on its
        # way to something else.
        self.cancel_btn.SetDefault()
        self.cancel_btn.SetFocus()
        self.Centre()

        self._timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_tick, self._timer)
        self._timer.Start(1000)

    def _message_text(self) -> str:
        # Phrased so the number never needs a plural form: the app ships no plural
        # catalogues, so "1 seconds" would be unfixable in translation.
        return _("All recordings have finished.\n\n"
                 "The computer will shut down by itself. Seconds remaining: {seconds}").format(
                     seconds=max(0, self._remaining))

    def _on_tick(self, _event):
        self._remaining -= 1
        if self._remaining <= 0:
            self._shutdown()
            return
        try:
            self.message.SetLabel(self._message_text())
        except Exception:
            LOG.debug("ShutdownCountdownDialog._on_tick: ignored exception", exc_info=True)

    def _stop_timer(self):
        try:
            self._timer.Stop()
        except Exception:
            LOG.debug("ShutdownCountdownDialog._stop_timer: ignored exception", exc_info=True)

    def _cancel(self):
        if self._finished:
            return
        self._finished = True
        self._stop_timer()
        self._on_cancel_cb()

    def _shutdown(self):
        if self._finished:
            return
        self._finished = True
        self._stop_timer()
        self._on_shutdown_cb()


class WhatsOnNowDialog(wx.Dialog):
    """Dialog showing all currently airing programs across all channels."""

    help_topic = "whats-on-now"

    def __init__(self, parent, programs: List[Dict[str, str]], schedule_callback=None, reminder_callback=None):
        super().__init__(parent, title=_("What's on Now"), size=(700, 500))
        self.programs = programs
        self.filtered_programs = programs[:]
        self.schedule_callback = schedule_callback
        self.reminder_callback = reminder_callback
        self._type_ahead_buffer = ""
        self._type_ahead_timer = None
        self._filter_timer = None

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Search box (for filtering, Tab to access)
        search_sizer = wx.BoxSizer(wx.HORIZONTAL)
        search_label = wx.StaticText(panel, label=_("Filter (Tab):"))
        self.search_box = wx.TextCtrl(panel, style=wx.TE_PROCESS_ENTER)
        self.search_box.SetName(_("Filter programs"))
        search_sizer.Add(search_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        search_sizer.Add(self.search_box, 1, wx.EXPAND)
        sizer.Add(search_sizer, 0, wx.EXPAND | wx.ALL, 10)

        # Info label
        self.count_label = wx.StaticText(panel, label=_("{count} programs").format(count=len(programs)))
        sizer.Add(self.count_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Use virtual ListCtrl for fast loading with many items
        self.listbox = _VirtualWhatsOnList(panel, self)
        self.listbox.SetName(_("Currently airing programs"))
        self.listbox.InsertColumn(0, _("Program - Channel"), width=650)
        self.listbox.SetItemCount(len(self.filtered_programs))

        # Buttons
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        play_btn = wx.Button(panel, id=wx.ID_OK, label=_("Play"))
        schedule_btn = wx.Button(panel, label=_("Schedule Recording"))
        close_btn = wx.Button(panel, id=wx.ID_CANCEL, label=_("Close"))
        btn_sizer.Add(play_btn, 0, wx.RIGHT, 5)
        btn_sizer.Add(schedule_btn, 0, wx.RIGHT, 5)
        btn_sizer.Add(close_btn, 0)

        sizer.Add(self.listbox, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        sizer.Add(btn_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 10)

        panel.SetSizer(sizer)

        self.Layout()
        self.CenterOnParent()

        # Bind events - use KEY_DOWN to intercept space before ListCtrl handles it
        self.listbox.Bind(wx.EVT_KEY_DOWN, self._on_key_down)
        # Enter, though, has to come from the char hook: a dialog consumes Enter
        # before the focused control ever sees a key-down, and this dialog has
        # no default button for wx to press instead (the Play button is not
        # one), so pressing Enter on a programme did nothing at all.
        self.listbox.Bind(wx.EVT_CHAR_HOOK, self._on_list_char_hook)
        self.listbox.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_activate)
        # Right-click / Shift+F10 / Applications key on a programme row.
        self.listbox.Bind(wx.EVT_CONTEXT_MENU, lambda _evt: self._show_context_menu(_evt))
        play_btn.Bind(wx.EVT_BUTTON, self._on_play)
        schedule_btn.Bind(wx.EVT_BUTTON, self._on_schedule)
        self.search_box.Bind(wx.EVT_TEXT, self._on_search)
        self.search_box.Bind(wx.EVT_TEXT_ENTER, self._on_search_enter)

        # Focus the list initially
        if self.filtered_programs:
            self.listbox.Select(0)
            self.listbox.Focus(0)
        self.listbox.SetFocus()

    def _on_list_char_hook(self, event):
        """Enter on a programme, before the list ever sees a key-down."""
        if event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            if self.listbox.GetSelectedItemCount() > 0:
                self.EndModal(wx.ID_OK)
            return
        event.Skip()

    def _on_key_down(self, event):
        """Handle key input for type-ahead search - intercept before ListCtrl."""
        key = event.GetKeyCode()

        # Handle Tab to go to search box (plain Tab only: Shift+Tab keeps the
        # normal dialog traversal, issue #3)
        if key == wx.WXK_TAB and not event.ShiftDown():
            self.search_box.SetFocus()
            return

        # Handle Enter to play
        if key == wx.WXK_RETURN or key == wx.WXK_NUMPAD_ENTER:
            if self.listbox.GetSelectedItemCount() > 0:
                self.EndModal(wx.ID_OK)
            return

        # Handle Escape to close
        if key == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CANCEL)
            return

        # Handle Space - add to type-ahead buffer (don't activate)
        if key == wx.WXK_SPACE or key == ord(' '):
            if self._type_ahead_timer:
                self._type_ahead_timer.Stop()
            self._type_ahead_buffer += " "
            self._find_match(self._type_ahead_buffer)
            self._type_ahead_timer = wx.CallLater(1000, self._reset_type_ahead)
            return

        # Unicode-aware type-ahead (issue #3): GetUnicodeKey() reports the
        # character the key press actually produces, so accented letters
        # (á, é, ü, ...) match programme titles instead of being ignored as
        # non-ASCII key codes. Space (32) stays handled above; anything that
        # is not a printable character keeps the default behaviour.
        uni_key = event.GetUnicodeKey()
        if uni_key and uni_key > 32 and chr(uni_key).isprintable():
            char = chr(uni_key).lower()

            # Reset buffer if too much time passed
            if self._type_ahead_timer:
                self._type_ahead_timer.Stop()

            self._type_ahead_buffer += char
            self._find_match(self._type_ahead_buffer)

            # Reset buffer after 1 second of no typing
            self._type_ahead_timer = wx.CallLater(1000, self._reset_type_ahead)
            return

        # Backspace clears type-ahead buffer
        if key == wx.WXK_BACK:
            if self._type_ahead_buffer:
                self._type_ahead_buffer = self._type_ahead_buffer[:-1]
                if self._type_ahead_buffer:
                    self._find_match(self._type_ahead_buffer)
            return

        event.Skip()

    def _reset_type_ahead(self):
        """Reset the type-ahead buffer."""
        self._type_ahead_buffer = ""

    def _find_match(self, prefix: str):
        """Find and select the first item starting with prefix."""
        prefix_lower = prefix.lower()
        for idx, prog in enumerate(self.filtered_programs):
            title = prog.get("title", "").lower()
            if title.startswith(prefix_lower):
                self.listbox.Select(idx)
                self.listbox.Focus(idx)
                self.listbox.EnsureVisible(idx)
                return

    def _on_search(self, event):
        """Debounce filtering so NVDA isn't hit with a list rebuild per keystroke."""
        if self._filter_timer:
            self._filter_timer.Stop()
        self._filter_timer = wx.CallLater(200, self._apply_search_filter)

    def _apply_search_filter(self):
        self._filter_timer = None
        try:
            if not self:  # dialog already destroyed while the timer was pending
                return
            query = self.search_box.GetValue().lower().strip()
        except RuntimeError:
            return
        if not query:
            self.filtered_programs = self.programs[:]
        else:
            self.filtered_programs = [
                p for p in self.programs
                if query in p.get("title", "").lower() or query in p.get("channel_name", "").lower()
            ]
        new_count = len(self.filtered_programs)
        # The old selection's index maps to a different program after refiltering,
        # and a focused item past the new count leaves NVDA holding a stale index.
        # Drop selection/focus state entirely before changing the count.
        old_count = self.listbox.GetItemCount()
        for idx in {self.listbox.GetFirstSelected(), self.listbox.GetFocusedItem()}:
            if idx is not None and 0 <= idx < old_count:
                try:
                    self.listbox.SetItemState(idx, 0, wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED)
                except Exception:
                    LOG.debug("WhatsOnNowDialog._apply_search_filter: ignored exception", exc_info=True)
        self.listbox.SetItemCount(new_count)
        self.listbox.Refresh()
        self.count_label.SetLabel(_("{count} programs").format(count=new_count))
        # Only auto-select while the user is actually in the list; forcing
        # Select/Focus while they type in the search box fires focus events at NVDA.
        if self.filtered_programs and self.FindFocus() is self.listbox:
            self.listbox.Select(0)
            self.listbox.Focus(0)
        LOG.debug("whats-on filter %r: %d/%d programs", query, new_count, len(self.programs))

    def _on_search_enter(self, event):
        """Move focus to list when Enter is pressed in search box."""
        # Flush a pending debounced filter so the list matches the query.
        if self._filter_timer:
            self._filter_timer.Stop()
            self._apply_search_filter()
        if self.filtered_programs:
            self.listbox.SetFocus()
            self.listbox.Select(0)
            self.listbox.Focus(0)

    def _on_activate(self, event):
        """Handle double-click/Enter to play."""
        if self.listbox.GetSelectedItemCount() > 0:
            self.EndModal(wx.ID_OK)

    def _on_play(self, event):
        """Handle Play button click."""
        if self.listbox.GetSelectedItemCount() > 0:
            self.EndModal(wx.ID_OK)
        event.Skip()

    def _on_schedule(self, _event):
        if not self.schedule_callback:
            return
        selection = self.get_selection()
        if selection:
            self.schedule_callback(selection)

    def _on_schedule_repeat(self, repeat: str) -> None:
        selection = self.get_selection()
        if selection and self.schedule_callback:
            self.schedule_callback(selection, repeat=repeat)

    def _show_context_menu(self, event=None):
        """Row actions for the highlighted programme, keyboard reachable."""
        if not self.filtered_programs:
            return
        index = _context_row_index(self.listbox, event)
        if index < 0:
            self.listbox.Select(0)
            self.listbox.Focus(0)
        menu = wx.Menu()
        play_item = menu.Append(wx.ID_ANY, _("Play"))
        menu.Bind(wx.EVT_MENU, lambda _evt: self.EndModal(wx.ID_OK), play_item)
        if callable(getattr(self, "reminder_callback", None)):
            reminder_item = menu.Append(wx.ID_ANY, _("Set Reminder..."))
            menu.Bind(wx.EVT_MENU, lambda event: self.reminder_callback(self.get_selection()), reminder_item)
        schedule_item = menu.Append(wx.ID_ANY, _("Schedule Recording"))
        schedule_item.Enable(self.schedule_callback is not None)
        menu.Bind(wx.EVT_MENU, self._on_schedule, schedule_item)
        for repeat, label in (("daily", _("Record Daily")),
                              ("weekly", _("Record Weekly")),
                              ("series", _("Record Series"))):
            item = menu.Append(wx.ID_ANY, label)
            item.Enable(self.schedule_callback is not None)
            menu.Bind(wx.EVT_MENU, lambda _evt, value=repeat: self._on_schedule_repeat(value), item)
        pos = wx.DefaultPosition
        index = self.listbox.GetFirstSelected()
        if index != -1:
            try:
                rect = self.listbox.GetItemRect(index)
                if rect.width or rect.height:
                    pos = self.listbox.ClientToScreen(rect.GetBottomLeft())
            except Exception:
                LOG.debug("WhatsOnNowDialog._show_context_menu: ignored exception", exc_info=True)
        try:
            self.listbox.PopupMenu(menu, pos)
        finally:
            menu.Destroy()


    def get_selection(self) -> Optional[Dict[str, str]]:
        """Get the selected program dict."""
        idx = self.listbox.GetFirstSelected()
        if idx == -1 or idx >= len(self.filtered_programs):
            return None
        return self.filtered_programs[idx]
