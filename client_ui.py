"""Main-window construction: the one big ``_build_ui`` method.

Split out of main.IPTVClient so the frame class stops carrying 500 lines of
widget wiring. IPTVClient inherits UiMixin, so every call site and
main.IPTVClient.<name> still resolves.
"""

import platform

import wx

import i18n
import shortcuts
import user_guide
from channel_widgets import _AccessibleCategoryTree, _VirtualChannelList
from i18n import gettext as _

# Fixed command id shared by the Player menu item and the explicit accelerator
# table. Keeping the shortcut in the table makes it work consistently on both
# menu-bar and button-menu platforms; the menu label remains its visible hint.
_MAIN_ACCEL_SHOW_PLAYER_ID = 4021


def _main_window_accelerator_entries(config=None):
    """Return the main-window shortcuts as one duplicate-checkable mapping."""
    return shortcuts.main_entries(config or {})


class UiMixin:

    def _build_ui(self):
        p = wx.Panel(self)
        hs = wx.BoxSizer(wx.HORIZONTAL)
        vs_l = wx.BoxSizer(wx.VERTICAL)
        vs_r = wx.BoxSizer(wx.VERTICAL)
        # Playlist scope picker, one Shift+Tab before the categories list. The
        # categories and channels show only the chosen playlist's entries (or
        # everything for "All playlists"). wx.Choice gets an MSAA name through
        # SetName/SetAccessibleName so screen readers announce a label.
        vs_l.Add(wx.StaticText(p, label=_("Playlist view")), 0, wx.LEFT | wx.TOP, 5)
        self.playlist_scope_combo = wx.Choice(p, choices=[])
        self.playlist_scope_combo.SetName(_("Playlist view"))
        if hasattr(self.playlist_scope_combo, "SetAccessibleName"):
            self.playlist_scope_combo.SetAccessibleName(_("Playlist view"))
        self.playlist_scope_combo.Bind(wx.EVT_CHAR_HOOK, self.on_playlist_scope_key)
        # Screen-reader names on MSW come from the static label created
        # immediately before each control: the tree/list/edit accessibles
        # ignore SetName/SetAccessibleName, but a wx.StaticText whose auto id
        # is exactly control id - 1 is announced. Verified with real MSAA/UIA
        # reads in tools/smoke_accessible_names_nvda.py; keep the pair
        # adjacent with no other window created in between.
        self.categories_label = wx.StaticText(p, label=_("Categories"))
        self.group_list = _AccessibleCategoryTree(p)
        self.group_list.Bind(wx.EVT_CHAR_HOOK, self.on_group_key)
        self.group_list.Bind(wx.EVT_TREE_ITEM_ACTIVATED, self._on_group_activated)
        self.playlist_scope_combo.Bind(wx.EVT_CHOICE, self.on_playlist_scope_changed)
        self._fill_playlist_scope_combo()
        vs_l.Add(self.playlist_scope_combo, 0, wx.EXPAND | wx.ALL, 5)
        vs_l.Add(self.categories_label, 0, wx.LEFT, 5)
        vs_l.Add(self.group_list, 1, wx.EXPAND | wx.ALL, 5)
        self.search_label = wx.StaticText(p, label=_("Search"))
        self.filter_box = wx.TextCtrl(p, style=wx.TE_PROCESS_ENTER)
        # Name the field for screen readers as well: harmless on MSW and it is
        # what GTK honors for the accessible name.
        self.filter_box.SetName(_("Search"))
        if hasattr(self.filter_box, "SetAccessibleName"):
            self.filter_box.SetAccessibleName(_("Search"))
        # Virtual list control (native SysListView32) so 50k-300k channels stay responsive
        # for the UI and NVDA alike — only visible rows are realized. Backed by self.displayed.
        self.channels_label = wx.StaticText(p, label=_("Channels"))
        self.channel_list = _VirtualChannelList(p, self)
        # Key bindings (original + added robust handlers)
        self.channel_list.Bind(wx.EVT_CHAR_HOOK, self.on_channel_key)  # original
        self.channel_list.Bind(wx.EVT_KEY_DOWN, self._on_channel_key_down)  # reliable Enter on all platforms
        # Selection change (keyboard arrows + mouse) -> refresh EPG/URL panel.
        self.channel_list.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda _evt: self.on_highlight())
        # Activation: Enter is consumed by the key handlers above, so this fires on double-click.
        self.channel_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda _evt: self.play_selected())
        self.channel_list.Bind(wx.EVT_CONTEXT_MENU, self._on_channel_context_menu)

        # Tab order after the channel list is episode description -> stream
        # URL. The description comes first because it is what a viewer
        # actually wants after hearing a channel row; the URL is a diagnostic
        # that most users keep switched off entirely. wx builds tab order from
        # creation order, so the description control is created first and the
        # sizer follows the same sequence.
        self.episode_description_field = wx.TextCtrl(
            p, size=(-1, 70), style=wx.TE_READONLY | wx.TE_MULTILINE)
        self.episode_description_field.SetName(_("Episode description"))
        if hasattr(self.episode_description_field, "SetAccessibleName"):
            self.episode_description_field.SetAccessibleName(_("Episode description"))
        self.episode_description_field.Bind(
            wx.EVT_CHAR_HOOK, self._on_episode_description_key)
        self.url_display = wx.TextCtrl(p, style=wx.TE_READONLY | wx.TE_MULTILINE)
        self.url_display.SetName(_("Stream URL"))
        if hasattr(self.url_display, "SetAccessibleName"):
            self.url_display.SetAccessibleName(_("Stream URL"))
        self.url_display.Bind(wx.EVT_CHAR_HOOK, self._on_url_display_key)
        # F1 opens the User Guide at the section about the focused control.
        user_guide.set_help_topic(self, "main-window")
        user_guide.set_help_topic(self.playlist_scope_combo, "playlist-view")
        user_guide.set_help_topic(self.group_list, lambda: self._list_help_topic("categories"))
        user_guide.set_help_topic(self.filter_box, "search")
        user_guide.set_help_topic(self.channel_list, lambda: self._list_help_topic("channel-list"))
        user_guide.set_help_topic(self.episode_description_field, "episode-description")
        user_guide.set_help_topic(self.url_display, "episode-description")
        vs_r.Add(self.search_label, 0, wx.LEFT | wx.TOP, 5)
        vs_r.Add(self.filter_box, 0, wx.EXPAND | wx.ALL, 5)
        vs_r.Add(self.channels_label, 0, wx.LEFT | wx.TOP, 5)
        vs_r.Add(self.channel_list, 1, wx.EXPAND | wx.ALL, 5)
        vs_r.Add(self.episode_description_field, 0, wx.EXPAND | wx.ALL, 5)
        vs_r.Add(self.url_display, 0, wx.EXPAND | wx.ALL, 5)
        self._apply_channel_url_visibility()
        hs.Add(vs_l, 1, wx.EXPAND)
        hs.Add(vs_r, 2, wx.EXPAND)

        if platform.system() == "Linux":
            self.menu_button = wx.Button(p, label=_("Menu"))
            self._player_radio_items = {}
            def on_menu_btn(evt):
                menu = wx.Menu()
                menu.Append(1001, self._shortcut_label(_("Playlist Manager"), "playlist_manager"))
                menu.Append(1002, self._shortcut_label(_("EPG Manager"), "epg_manager"))
                menu.Append(1003, self._shortcut_label(_("Import EPG to DB"), "import_epg"))
                menu.Append(1333, self._shortcut_label(_("What Is Playing"), "what_is_playing"))
                self.Bind(wx.EVT_MENU, self._announce_what_is_playing, id=1333)
                menu.Append(1007, self._shortcut_label(_("Account Info"), "account"))
                menu.AppendSeparator()
                player_ctrl_menu = wx.Menu()
                player_ctrl_menu.Append(1201, _("Show Built-in Player"))
                player_ctrl_menu.Append(1202, _("Play/Pause"))
                player_ctrl_menu.Append(1203, _("Stop"))
                player_ctrl_menu.Append(1204, _("Cast / Connect..."))
                menu.AppendSubMenu(player_ctrl_menu, _("Player"))
                self.Bind(wx.EVT_MENU, self._menu_show_player, id=1201)
                self.Bind(wx.EVT_MENU, self._menu_toggle_player, id=1202)
                self.Bind(wx.EVT_MENU, self._menu_stop_player, id=1203)
                self.Bind(wx.EVT_MENU, self._menu_cast_from_player, id=1204)
                # View submenu: Live TV / catch-up vs Video on Demand.
                view_menu = wx.Menu()
                view_live = view_menu.AppendRadioItem(1301, _("Live TV && Catch-up"))
                view_vod = view_menu.AppendRadioItem(1302, _("Video on Demand (Movies && Series)"))
                view_live.Check(self.view_mode == "live")
                view_vod.Check(self.view_mode == "vod")
                self.Bind(wx.EVT_MENU, lambda _evt: self._set_view_mode("live"), id=1301)
                self.Bind(wx.EVT_MENU, lambda _evt: self._set_view_mode("vod"), id=1302)
                view_menu.AppendSeparator()
                view_menu.Append(1310, self._shortcut_label(self._favorite_action_label(), "favorite"))
                view_menu.Append(1311, _("Go to Favorites"))
                view_menu.Append(1320, self._shortcut_label(_("Previous Channel"), "previous_channel"))
                view_menu.Append(1321, self._shortcut_label(_("Recently Watched..."), "recent_channels"))
                view_menu.Append(1322, self._shortcut_label(_("Go to Channel Number..."), "channel_number"))
                self.Bind(wx.EVT_MENU, self._toggle_favorite_selected, id=1310)
                self.Bind(wx.EVT_MENU, self._go_to_favorites, id=1311)
                self.Bind(wx.EVT_MENU, self._play_previous_channel, id=1320)
                self.Bind(wx.EVT_MENU, self._show_recent_channels, id=1321)
                self.Bind(wx.EVT_MENU, self._go_to_channel_number, id=1322)
                menu.AppendSubMenu(view_menu, _("View"))
                menu.AppendSeparator()
                player_menu = wx.Menu()
                for idx, (label, attr) in enumerate(self.PLAYER_KEYS):
                    itemid = 2000 + idx
                    item = player_menu.AppendRadioItem(itemid, _(label))
                    self._player_radio_items[label] = item
                    self.Bind(wx.EVT_MENU, lambda evt, pl=label: self._select_player(pl), id=itemid)
                    if self.default_player == label:
                        item.Check(True)
                customid = 2999
                customitem = player_menu.AppendRadioItem(customid, _("Custom Player..."))
                self.Bind(wx.EVT_MENU, self._select_custom_player, id=customid)
                if self.default_player == "Custom":
                    customitem.Check(True)
                menu.AppendSubMenu(player_menu, _("Media Player to Use"))
                menu.Append(1312, _("Preferred Audio Track..."))
                self.Bind(wx.EVT_MENU, self._show_audio_preference_dialog, id=1312)
                # Recordings submenu (Linux)
                rec_menu = wx.Menu()
                self._populate_recordings_menu(rec_menu)
                menu.AppendSubMenu(rec_menu, _("Recordings"))
                # Language submenu (Linux)
                lang_menu = wx.Menu()
                self._lang_menu_items = {}
                for code, label in i18n.available_languages():
                    disp = _("Automatic") if code == "auto" else label
                    li = lang_menu.AppendRadioItem(wx.ID_ANY, disp)
                    if i18n.get_language() == code:
                        li.Check(True)
                    self._lang_menu_items[li.GetId()] = code
                    self.Bind(wx.EVT_MENU, lambda evt, c=code: self._on_select_language(c), li)
                menu.AppendSubMenu(lang_menu, _("Language"))
                min_to_tray_id = 1101
                min_item = menu.AppendCheckItem(min_to_tray_id, _("Minimize to System Tray"))
                min_item.Check(self.minimize_to_tray)
                self.Bind(wx.EVT_MENU, self.on_toggle_min_to_tray, id=min_to_tray_id)
                menu.AppendSeparator()
                show_enter_id = 1102
                show_enter_item = menu.AppendCheckItem(show_enter_id, _("Show Player on Enter"))
                show_enter_item.Check(self.show_player_on_enter)
                self.Bind(wx.EVT_MENU, self.on_toggle_show_player_on_enter, id=show_enter_id)
                show_url_id = 1104
                show_url_item = menu.AppendCheckItem(show_url_id, _("Show Stream URL"))
                show_url_item.Check(self.show_channel_url)
                self.Bind(wx.EVT_MENU, self.on_toggle_show_channel_url, id=show_url_id)
                menu.AppendSeparator()

                auto_update_id = 1103
                auto_update_item = menu.AppendCheckItem(auto_update_id, _("Auto-check for Updates"))
                auto_update_item.Check(self.auto_check_updates)
                self.Bind(wx.EVT_MENU, self.on_toggle_auto_check_updates, id=auto_update_id)
                menu.Append(1330, _("Export Settings..."))
                menu.Append(1331, _("Import Settings..."))
                self.Bind(wx.EVT_MENU, self._export_settings, id=1330)
                self.Bind(wx.EVT_MENU, self._import_settings, id=1331)
                announcement_menu = wx.Menu()
                for level, label in enumerate((_("None"), _("Errors only"),
                                               _("Important events"), _("Detailed status"))):
                    item = announcement_menu.AppendRadioItem(1340 + level, label)
                    item.Check(level == self.config.get("announcement_level", 2))
                    self.Bind(wx.EVT_MENU, lambda _evt, value=level: self._set_announcement_level(value), id=1340 + level)
                menu.AppendSubMenu(announcement_menu, _("Automatic Announcements"))
                menu.Append(1332, _("Keyboard Shortcuts..."))
                self.Bind(wx.EVT_MENU, self._customize_shortcuts, id=1332)
                menu.Append(1006, _("Check for Updates"))
                self.Bind(wx.EVT_MENU, self.on_check_updates, id=1006)
                menu.AppendSeparator()

                help_menu = wx.Menu()
                guide_item = help_menu.Append(wx.ID_ANY, _("User Guide") + "\tF1")
                help_menu.Bind(wx.EVT_MENU, self._on_user_guide_menu, guide_item)
                whats_new_item = help_menu.Append(wx.ID_ANY, _("What's New"))
                logs_item = help_menu.Append(wx.ID_ANY, _("Open Logs Folder"))
                copy_debug_item = help_menu.Append(wx.ID_ANY, _("Copy Log and Debug Information"))
                about_item = help_menu.Append(wx.ID_ABOUT, _("About..."))
                help_menu.Bind(wx.EVT_MENU, self._open_logs_folder, logs_item)
                help_menu.Bind(wx.EVT_MENU, self._show_changelog_dialog, whats_new_item)
                help_menu.Bind(wx.EVT_MENU, self._copy_diagnostic_information, copy_debug_item)
                help_menu.Bind(wx.EVT_MENU, self._show_about_dialog, about_item)
                menu.AppendSubMenu(help_menu, _("Help"))

                # Casting Menu Item (Linux)
                menu.Append(1005, _("Cast To..."))
                self.Bind(wx.EVT_MENU, self.show_cast_dialog, id=1005)

                menu.Append(1004, self._shortcut_label(_("Exit"), "exit"))
                self.Bind(wx.EVT_MENU, self.show_manager, id=1001)
                self.Bind(wx.EVT_MENU, self.show_epg_manager, id=1002)
                self.Bind(wx.EVT_MENU, self.import_epg, id=1003)
                self.Bind(wx.EVT_MENU, self.show_account_info, id=1007)
                self.Bind(wx.EVT_MENU, self.request_exit, id=1004)
                self.menu_button.PopupMenu(menu)
            self.menu_button.Bind(wx.EVT_BUTTON, on_menu_btn)
            sizer_with_menu = wx.BoxSizer(wx.VERTICAL)
            sizer_with_menu.Add(self.menu_button, 0, wx.EXPAND | wx.ALL, 5)
            sizer_with_menu.Add(hs, 1, wx.EXPAND)
            p.SetSizerAndFit(sizer_with_menu)
        else:
            p.SetSizerAndFit(hs)
            mb = wx.MenuBar()
            fm = wx.Menu()
            m_mgr = fm.Append(wx.ID_ANY, self._shortcut_label(_("Playlist Manager"), "playlist_manager"))
            m_epg = fm.Append(wx.ID_ANY, self._shortcut_label(_("EPG Manager"), "epg_manager"))
            m_imp = fm.Append(wx.ID_ANY, self._shortcut_label(_("Import EPG to DB"), "import_epg"))
            m_now = fm.Append(wx.ID_ANY, self._shortcut_label(_("What's on Now"), "whats_on_now"))
            m_playing = fm.Append(wx.ID_ANY, self._shortcut_label(_("What Is Playing"), "what_is_playing"))
            m_acct = fm.Append(wx.ID_ANY, self._shortcut_label(_("Account Info"), "account"))
            fm.AppendSeparator()
            # Casting Menu Item (Windows/Mac)
            m_cast = fm.Append(wx.ID_ANY, _("Cast To..."))
            fm.AppendSeparator()
            m_exit = fm.Append(wx.ID_EXIT, self._shortcut_label(_("Exit"), "exit"))
            mb.Append(fm, _("File"))
            pm = wx.Menu()
            pm_show = pm.Append(_MAIN_ACCEL_SHOW_PLAYER_ID,
                                self._shortcut_label(_("Show Built-in Player"), "show_player"))
            pm_toggle = pm.Append(wx.ID_ANY, self._shortcut_label(_("Play/Pause"), "play_pause"))
            pm_stop = pm.Append(wx.ID_ANY, self._shortcut_label(_("Stop"), "stop"))
            pm_cast = pm.Append(wx.ID_ANY, self._shortcut_label(_("Cast / Connect..."), "cast"))
            self._player_control_items = (pm_show, pm_toggle, pm_stop, pm_cast)
            mb.Append(pm, _("Player"))
            # View menu: switch between Live TV / catch-up and Video on Demand.
            vm = wx.Menu()
            self.view_live_item = vm.AppendRadioItem(wx.ID_ANY, _("Live TV && Catch-up"))
            self.view_vod_item = vm.AppendRadioItem(wx.ID_ANY, _("Video on Demand (Movies && Series)"))
            self.view_live_item.Check(self.view_mode == "live")
            self.view_vod_item.Check(self.view_mode == "vod")
            vm.AppendSeparator()
            # The label follows the selected channel, so it always says what
            # activating it will do (see _sync_favorite_menu_item).
            self.favorite_menu_item = vm.Append(wx.ID_ANY, self._shortcut_label(_("Add to Favorites"), "favorite"))
            self.goto_favorites_item = vm.Append(wx.ID_ANY, _("Go to Favorites"))
            previous_item = vm.Append(wx.ID_ANY, self._shortcut_label(_("Previous Channel"), "previous_channel"))
            recent_item = vm.Append(wx.ID_ANY, self._shortcut_label(_("Recently Watched..."), "recent_channels"))
            number_item = vm.Append(wx.ID_ANY, self._shortcut_label(_("Go to Channel Number..."), "channel_number"))
            vm.AppendSeparator()
            # Escape hides a download window without stopping the download,
            # and a modeless window is easy to lose behind this one: this is
            # the way back to it.
            self.show_downloads_item = vm.Append(wx.ID_ANY, self._shortcut_label(_("Show Downloads"), "downloads"))
            mb.Append(vm, _("View"))
            self.Bind(wx.EVT_MENU, self._show_catchup_downloads, self.show_downloads_item)
            self.Bind(wx.EVT_MENU, lambda _evt: self._set_view_mode("live"), self.view_live_item)
            self.Bind(wx.EVT_MENU, lambda _evt: self._set_view_mode("vod"), self.view_vod_item)
            self.Bind(wx.EVT_MENU, self._toggle_favorite_selected, self.favorite_menu_item)
            self.Bind(wx.EVT_MENU, self._go_to_favorites, self.goto_favorites_item)
            self.Bind(wx.EVT_MENU, self._play_previous_channel, previous_item)
            self.Bind(wx.EVT_MENU, self._show_recent_channels, recent_item)
            self.Bind(wx.EVT_MENU, self._go_to_channel_number, number_item)
            om = wx.Menu()
            player_menu = wx.Menu()
            self.player_menu_items = []
            for label, attr in self.PLAYER_KEYS:
                item = player_menu.AppendRadioItem(wx.ID_ANY, _(label))
                setattr(self, attr, item)
                self.player_menu_items.append((item, label))
            self.player_Custom = player_menu.AppendRadioItem(wx.ID_ANY, _("Custom Player..."))
            om.AppendSubMenu(player_menu, _("Media Player to Use"))
            self.audio_preference_item = om.Append(wx.ID_ANY, _("Preferred Audio Track..."))
            self.Bind(wx.EVT_MENU, self._show_audio_preference_dialog, self.audio_preference_item)
            # Language submenu (Windows/macOS)
            lang_menu = wx.Menu()
            self._lang_menu_items = {}
            for code, lbl in i18n.available_languages():
                disp = _("Automatic") if code == "auto" else lbl
                li = lang_menu.AppendRadioItem(wx.ID_ANY, disp)
                if i18n.get_language() == code:
                    li.Check(True)
                self._lang_menu_items[li.GetId()] = code
                self.Bind(wx.EVT_MENU, lambda evt, c=code: self._on_select_language(c), li)
            om.AppendSubMenu(lang_menu, _("Language"))
            self.min_to_tray_item = om.AppendCheckItem(wx.ID_ANY, _("Minimize to System Tray"))
            self.show_player_on_enter_item = om.AppendCheckItem(wx.ID_ANY, _("Show Player on Enter"))
            self.show_channel_url_item = om.AppendCheckItem(wx.ID_ANY, _("Show Stream URL"))
            self.auto_check_updates_item = om.AppendCheckItem(wx.ID_ANY, _("Auto-check for Updates"))
            export_item = om.Append(wx.ID_ANY, _("Export Settings..."))
            import_item = om.Append(wx.ID_ANY, _("Import Settings..."))
            self.Bind(wx.EVT_MENU, self._export_settings, export_item)
            self.Bind(wx.EVT_MENU, self._import_settings, import_item)
            announcement_menu = wx.Menu()
            self._announcement_items = []
            for level, label in enumerate((_("None"), _("Errors only"),
                                           _("Important events"), _("Detailed status"))):
                item = announcement_menu.AppendRadioItem(wx.ID_ANY, label)
                item.Check(level == self.config.get("announcement_level", 2))
                self._announcement_items.append(item)
                self.Bind(wx.EVT_MENU, lambda _evt, value=level: self._set_announcement_level(value), item)
            om.AppendSubMenu(announcement_menu, _("Automatic Announcements"))
            # Subtitle speech (issue #37): backend choice, app-voice settings,
            # and the honest per-player capability report.
            speech_menu = wx.Menu()
            self._subtitle_backend_items = []
            backend = self._subtitle_backend()
            for value, label in (("screen_reader", _("Speak through screen reader")),
                                 ("app_tts", _("Speak through application voice"))):
                item = speech_menu.AppendRadioItem(wx.ID_ANY, label)
                item.Check(value == backend)
                self.Bind(wx.EVT_MENU, lambda _evt, v=value: self._set_subtitle_backend(v), item)
                self._subtitle_backend_items.append((item, value))
            speech_menu.AppendSeparator()
            # Player-independent subtitle commands (issue #45, item 1):
            # these work without the built-in player window existing, and
            # route through the active session controller.
            toggle_item = speech_menu.AppendCheckItem(wx.ID_ANY, _("Speak subtitles"))
            toggle_item.Check(bool(self.config.get("speak_subtitles", False)))
            self.Bind(wx.EVT_MENU,
                      lambda _evt: self._on_toggle_subtitle_speech(),
                      toggle_item)
            self._subtitle_toggle_item = toggle_item
            read_current_item = speech_menu.Append(wx.ID_ANY, _("Read current subtitle"))
            self.Bind(wx.EVT_MENU,
                      lambda _evt: self._on_read_current_subtitle(),
                      read_current_item)
            read_prev_item = speech_menu.Append(wx.ID_ANY, _("Read previous subtitle"))
            self.Bind(wx.EVT_MENU,
                      lambda _evt: self._on_read_previous_subtitle(),
                      read_prev_item)
            review_item = speech_menu.Append(wx.ID_ANY, _("Review recent subtitles..."))
            self.Bind(wx.EVT_MENU,
                      lambda _evt: self._on_review_recent_subtitles(),
                      review_item)
            speech_menu.AppendSeparator()
            self._subtitle_app_tts_items = []
            vol_item = speech_menu.Append(wx.ID_ANY, _("Application voice volume..."))
            self.Bind(wx.EVT_MENU, lambda _evt: self._set_app_tts_volume(), vol_item)
            self._subtitle_app_tts_items.append(vol_item)
            out_item = speech_menu.Append(wx.ID_ANY, _("Application voice output..."))
            self.Bind(wx.EVT_MENU, lambda _evt: self._choose_app_tts_output(), out_item)
            self._subtitle_app_tts_items.append(out_item)
            rate_item = speech_menu.Append(wx.ID_ANY, _("Application voice speed..."))
            self.Bind(wx.EVT_MENU, lambda _evt: self._set_app_tts_rate(), rate_item)
            self._subtitle_app_tts_items.append(rate_item)
            # Device-loss policy (issue #37): what the application voice does
            # when its selected output disappears (unplugged USB/Bluetooth).
            # "pause" is the privacy-preserving default: never silently
            # reroute previously private captions to another device.
            self._subtitle_device_policy_items = []
            policy = self.config.get("subtitle_app_device_policy", "pause")
            for value, label in (
                    ("pause", _("On device loss: pause until the device returns")),
                    ("default", _("On device loss: use the system default"))):
                item = speech_menu.AppendRadioItem(wx.ID_ANY, label)
                item.Check(value == policy)
                self.Bind(wx.EVT_MENU,
                          lambda _evt, v=value: self._set_app_tts_device_policy(v),
                          item)
                self._subtitle_device_policy_items.append((item, value))
                self._subtitle_app_tts_items.append(item)
            speech_menu.AppendSeparator()
            cap_item = speech_menu.Append(wx.ID_ANY, _("Subtitle capabilities..."))
            self.Bind(wx.EVT_MENU, lambda _evt: self._show_subtitle_capabilities(), cap_item)
            om.AppendSubMenu(speech_menu, _("Subtitle Speech"))
            user_guide.set_menu_help(self, speech_menu, "subtitle-speech")
            self._sync_subtitle_speech_menu()
            shortcut_item = om.Append(wx.ID_ANY, _("Keyboard Shortcuts..."))
            self.Bind(wx.EVT_MENU, self._customize_shortcuts, shortcut_item)
            mb.Append(om, _("Options"))
            # Recordings menu
            rm = wx.Menu()
            self._populate_recordings_menu(rm)
            mb.Append(rm, _("Recordings"))
            # Help menu
            hm = wx.Menu()
            # F1 is shown as the shortcut, but the app-wide char hook answers
            # F1 before this accelerator can, with the context topic; choosing
            # the item itself opens the guide at its beginning.
            self.user_guide_item = hm.Append(wx.ID_ANY, _("User Guide") + "\tF1")
            self.whats_new_item = hm.Append(wx.ID_ANY, _("What's New"))
            hm.AppendSeparator()
            self.check_updates_item = hm.Append(wx.ID_ANY, _("Check for Updates..."))
            self.open_logs_item = hm.Append(wx.ID_ANY, _("Open Logs Folder"))
            self.copy_diagnostic_item = hm.Append(wx.ID_ANY, _("Copy Log and Debug Information"))
            hm.AppendSeparator()
            m_about = hm.Append(wx.ID_ABOUT, _("About..."))
            mb.Append(hm, _("Help"))
            self.SetMenuBar(mb)
            # F1 on an open menu item opens the guide section about that item.
            # Whole menus first, then the items that have a section of their own.
            user_guide.set_menu_help(self, fm, "main-window")
            user_guide.set_menu_help(self, pm, "player-from-main-window")
            user_guide.set_menu_help(self, vm, "video-on-demand")
            user_guide.set_menu_help(self, om, "options")
            user_guide.set_menu_help(self, hm, "troubleshooting")
            user_guide.set_menu_help(self, m_mgr, "playlist-manager")
            user_guide.set_menu_help(self, m_epg, "epg-manager")
            user_guide.set_menu_help(self, m_imp, "import-epg")
            user_guide.set_menu_help(self, m_now, "whats-on-now")
            user_guide.set_menu_help(self, m_acct, "account-info")
            user_guide.set_menu_help(self, m_cast, "casting")
            user_guide.set_menu_help(self, pm_cast, "casting")
            user_guide.set_menu_help(self, self.favorite_menu_item, "favorites")
            user_guide.set_menu_help(self, self.goto_favorites_item, "favorites")
            user_guide.set_menu_help(self, self.show_downloads_item, "catch-up-downloads")
            user_guide.set_menu_help(self, player_menu, "media-player")
            user_guide.set_menu_help(self, self.audio_preference_item, "preferred-audio-track")
            user_guide.set_menu_help(self, lang_menu, "language")
            user_guide.set_menu_help(self, self.min_to_tray_item, "system-tray")
            user_guide.set_menu_help(self, self.auto_check_updates_item, "updates")
            user_guide.set_menu_help(self, self.user_guide_item, "using-help")
            user_guide.set_menu_help(self, self.check_updates_item, "updates")
            user_guide.set_menu_help(self, m_about, "support")
            self.Bind(wx.EVT_MENU, self.show_manager, m_mgr)
            self.Bind(wx.EVT_MENU, self.show_epg_manager, m_epg)
            self.Bind(wx.EVT_MENU, self.import_epg, m_imp)
            self.Bind(wx.EVT_MENU, self.show_whats_on_now, m_now)
            self.Bind(wx.EVT_MENU, self._announce_what_is_playing, m_playing)
            self.Bind(wx.EVT_MENU, self.show_account_info, m_acct)
            self.Bind(wx.EVT_MENU, self.show_cast_dialog, m_cast)
            self.Bind(wx.EVT_MENU, self.request_exit, m_exit)
            self.Bind(wx.EVT_MENU, self._menu_toggle_player, pm_toggle)
            self.Bind(wx.EVT_MENU, self._menu_stop_player, pm_stop)
            self.Bind(wx.EVT_MENU, self._menu_cast_from_player, pm_cast)
            for item, key in self.player_menu_items:
                self.Bind(wx.EVT_MENU, lambda evt, attr=key: self._select_player(attr), item)
            self.Bind(wx.EVT_MENU, self._select_custom_player, self.player_Custom)
            self.Bind(wx.EVT_MENU, self.on_toggle_min_to_tray, self.min_to_tray_item)
            self.Bind(wx.EVT_MENU, self.on_toggle_show_player_on_enter, self.show_player_on_enter_item)
            self.Bind(wx.EVT_MENU, self.on_toggle_show_channel_url, self.show_channel_url_item)
            self.Bind(wx.EVT_MENU, self.on_toggle_auto_check_updates, self.auto_check_updates_item)
            self.Bind(wx.EVT_MENU, self.on_check_updates, self.check_updates_item)
            self.Bind(wx.EVT_MENU, self._open_logs_folder, self.open_logs_item)
            self.Bind(wx.EVT_MENU, self._copy_diagnostic_information, self.copy_diagnostic_item)
            self.Bind(wx.EVT_MENU, self._show_about_dialog, m_about)
            self.Bind(wx.EVT_MENU, self._on_user_guide_menu, self.user_guide_item)
            self.Bind(wx.EVT_MENU, self._show_changelog_dialog, self.whats_new_item)
            self.Bind(wx.EVT_MENU_OPEN, self.on_menu_open)
            self._sync_player_menu_from_config()
            self.min_to_tray_item.Check(self.minimize_to_tray)
            self.show_player_on_enter_item.Check(self.show_player_on_enter)
            self.show_channel_url_item.Check(self.show_channel_url)
            self.auto_check_updates_item.Check(self.auto_check_updates)

        self.group_list.Bind(wx.EVT_LEFT_UP, self._on_group_activated)
        self.filter_box.Bind(wx.EVT_TEXT_ENTER, lambda _: self.apply_filter())
        # Track re-focuses of the search box: stale async search results must
        # not yank focus back to the channel list while the user is editing a
        # new query (see the generation guard in apply_results).
        self._filter_focus_gen = 0
        self.filter_box.Bind(wx.EVT_SET_FOCUS, self._on_filter_focus)
        # Tab in the search box applies the filter, exactly like Enter, so a
        # screen-reader user can filter and move on without hunting for Enter.
        self.filter_box.Bind(wx.EVT_CHAR_HOOK, self._on_filter_char_hook)

        entries = _main_window_accelerator_entries(self.config)
        atable = wx.AcceleratorTable(entries)
        self.SetAcceleratorTable(atable)
        self.Bind(wx.EVT_MENU, self.show_manager, id=4001)
        self.Bind(wx.EVT_MENU, self.show_epg_manager, id=4002)
        self.Bind(wx.EVT_MENU, self.import_epg, id=4003)
        self.Bind(wx.EVT_MENU, self.request_exit, id=4004)
        self.Bind(wx.EVT_MENU, self._menu_toggle_player, id=4010)
        self.Bind(wx.EVT_MENU, self._menu_stop_player, id=4011)
        self.Bind(wx.EVT_MENU, self._menu_cast_from_player, id=4012)
        self.Bind(wx.EVT_MENU, lambda _: self._adjust_internal_volume(+2), id=4015)
        self.Bind(wx.EVT_MENU, lambda _: self._adjust_internal_volume(-2), id=4016)
        self.Bind(wx.EVT_MENU, self._record_selected, id=4017)
        self.Bind(wx.EVT_MENU, self.show_account_info, id=4018)
        self.Bind(wx.EVT_MENU, self._toggle_favorite_selected, id=4019)
        self.Bind(wx.EVT_MENU, self._play_previous_channel, id=4022)
        self.Bind(wx.EVT_MENU, self._go_to_channel_number, id=4023)
        self.Bind(wx.EVT_MENU, self._show_recent_channels, id=4024)
        self.Bind(wx.EVT_MENU, self.show_whats_on_now, id=4025)
        self.Bind(wx.EVT_MENU, self._announce_what_is_playing, id=4026)
        self.Bind(wx.EVT_MENU, self._show_catchup_downloads, id=4020)
        self.Bind(wx.EVT_MENU, self._menu_show_player,
                  id=_MAIN_ACCEL_SHOW_PLAYER_ID)
