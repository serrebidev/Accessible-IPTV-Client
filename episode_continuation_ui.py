"""Optional episode continuation, with a cancellable native countdown."""
import copy
import threading
import time

import wx

import episode_continuation
import playback_resume
import user_guide
import vod
from i18n import gettext as _
from modal_guard import show_modal


def prepare(owner, frame, channel):
    frame._episode_channel = copy.deepcopy(channel or {})
    frame._episode_queue = copy.deepcopy(getattr(owner, "_vod_episode_queue", ()))


class NextEpisodeDialog(wx.Dialog):
    def __init__(self, player, title, valid):
        super().__init__(player, title=_("Next Episode"))
        self.valid = valid
        self.deadline = time.monotonic() + 10
        layout = wx.BoxSizer(wx.VERTICAL)
        self.label = wx.StaticText(self, label=_("The next episode starts in {seconds} seconds: {title}").format(seconds=10, title=title))
        self.label.Wrap(600)
        self.episode_title = title
        layout.Add(self.label, 0, wx.ALL, 12)
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        play = wx.Button(self, wx.ID_OK, label=_("Play Now"))
        cancel = wx.Button(self, wx.ID_CANCEL, label=_("Cancel"))
        cancel.SetDefault()
        buttons.Add(play, 0, wx.ALL, 8)
        buttons.Add(cancel, 0, wx.ALL, 8)
        layout.Add(buttons, 0, wx.ALIGN_RIGHT)
        self.SetSizerAndFit(layout)
        cancel.SetFocus()
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.tick, self.timer)
        self.timer.Start(250)
        user_guide.set_help_topic(self, "video-on-demand")

    def tick(self, _event):
        if not self.IsModal():
            return
        if not self.valid():
            self.EndModal(wx.ID_CANCEL)
        elif time.monotonic() >= self.deadline:
            self.EndModal(wx.ID_OK)
        else:
            seconds = max(1, int(self.deadline - time.monotonic()) + 1)
            self.label.SetLabel(_("The next episode starts in {seconds} seconds: {title}").format(
                seconds=seconds, title=self.episode_title))
            self.label.Wrap(600)
            self.Layout()


def finished(player, expected_generation):
    if getattr(player, "_destroyed", False) or expected_generation != getattr(player, "_vlc_generation", 0):
        return
    owner = player.GetParent()
    if owner.config.get("auto_next_episode") is not True:
        return
    channel = copy.deepcopy(getattr(player, "_episode_channel", {}))
    episodes = copy.deepcopy(getattr(player, "_episode_queue", ()))
    if channel.get("resume-type") != "episode" and not any(playback_resume.item_key(item) == playback_resume.item_key(channel) for item in episodes):
        return
    generation = getattr(player, "_vlc_generation", 0)
    request = getattr(owner, "_continuation_request", 0)
    source_generation = getattr(owner, "_playlist_load_token", 0)
    client = getattr(owner, "provider_clients", {}).get(channel.get("provider-id"))

    def valid():
        return (not getattr(player, "_destroyed", False)
                and generation == getattr(player, "_vlc_generation", 0)
                and request == getattr(owner, "_continuation_request", 0)
                and source_generation == getattr(owner, "_playlist_load_token", 0)
                and owner.config.get("auto_next_episode") is True)

    def ready(item, error):
        if not valid():
            return
        if error:
            owner._show_or_queue_message_box(_("Could not load episodes:\n{error}").format(error=error),
                                            _("Next Episode"), wx.OK | wx.ICON_WARNING)
            return
        if not item:
            return
        # Do not enter a second modal loop while another question owns input.
        if owner._modal_box_is_open():
            return
        dialog = NextEpisodeDialog(player, item.get("name") or _("Next Episode"), valid)
        try:
            accepted = show_modal(dialog) == wx.ID_OK
        finally:
            dialog.timer.Stop()
            dialog.Destroy()
        if accepted and valid():
            owner._launch_stream(item["url"], item.get("name"), stream_kind="vod", channel=item,
                                 show_internal_player=True, force_internal=True)

    def worker():
        try:
            current = episodes
            if channel.get("resume-type") == "episode" and client is not None:
                current = vod.xtream_series_episodes(client, channel["series_id"], channel.get("provider-id"), strict=True)
            item = episode_continuation.following_item(channel, current)
            wx.CallAfter(ready, item, "")
        except Exception as error:
            wx.CallAfter(ready, None, str(error))
    threading.Thread(target=worker, daemon=True, name="NextEpisode").start()
