"""wx controls shared by the main window and the programme dialogs.

Imported by main.py and dialogs_misc.py; nothing here imports either, so the
main frame keeps owning their state.
"""
import logging
import re
from typing import Dict, List, Optional, Tuple

import wx

from i18n import gettext as _

LOG = logging.getLogger("EPG.ui")


class _AccessibleCategoryTree(wx.TreeCtrl):
    """Native, NVDA-friendly category tree with ListBox-compatible helpers.

    The surrounding application stores category selection as a stable integer
    into ``_group_keys``.  Keeping that small compatibility layer lets us use
    the native tree's hierarchy, expansion state and MSAA/UIA role without
    changing category identity to a display string.
    """

    _COUNT_SUFFIX = re.compile(r" \(\d+\)$")

    def __init__(self, parent):
        super().__init__(
            parent,
            style=wx.TR_HIDE_ROOT | wx.TR_HAS_BUTTONS | wx.TR_LINES_AT_ROOT | wx.TR_SINGLE,
            name="Categories",
        )
        self.SetName(_("Categories"))
        if hasattr(self, "SetAccessibleName"):
            self.SetAccessibleName(_("Categories"))
        self._labels: List[str] = []
        # An optional display path keeps a category's identity separate from
        # its position. In particular, two playlists may both have a "News"
        # category, but they must remain separate branches in All playlists.
        self._paths: Dict[int, List[object]] = {}
        self._selection = wx.NOT_FOUND
        self._batch_depth = 0
        self._rebuilding = False
        self._item_indexes: Dict[int, int] = {}
        self._index_items: Dict[int, object] = {}
        self.Bind(wx.EVT_TREE_SEL_CHANGED, self._on_tree_selection)
        self._rebuild()

    @classmethod
    def _path_parts(cls, label: str) -> List[str]:
        base = cls._COUNT_SUFFIX.sub("", label or "").strip()
        # IPTV providers commonly encode a hierarchy with either slash or a
        # spaced greater-than sign. Keep all other punctuation literal: it can
        # be part of a broadcaster's actual category name.
        if " > " in base:
            parts = base.split(" > ")
        else:
            parts = base.split("/")
        return [part.strip() for part in parts if part.strip()] or [base]

    def Freeze(self):
        self._batch_depth += 1
        return super().Freeze()

    def Thaw(self):
        result = super().Thaw()
        self._batch_depth = max(0, self._batch_depth - 1)
        if not self._batch_depth:
            self._rebuild()
        return result

    def _changed(self):
        if not self._batch_depth:
            self._rebuild()

    def Clear(self):
        self._labels = []
        self._paths = {}
        self._selection = wx.NOT_FOUND
        self._changed()

    def Append(self, label: str, tree_path: Optional[List[object]] = None):
        self._labels.append(str(label))
        if tree_path:
            self._paths[len(self._labels) - 1] = list(tree_path)
        self._changed()
        return len(self._labels) - 1

    def Insert(self, label: str, index: int, tree_path: Optional[List[object]] = None):
        index = max(0, min(int(index), len(self._labels)))
        self._labels.insert(index, str(label))
        self._paths = {
            existing + 1 if existing >= index else existing: path
            for existing, path in self._paths.items()
        }
        if tree_path:
            self._paths[index] = list(tree_path)
        if self._selection >= index:
            self._selection += 1
        self._changed()
        return index

    def Delete(self, index: int):
        if not 0 <= index < len(self._labels):
            return
        self._labels.pop(index)
        self._paths = {
            existing - 1 if existing > index else existing: path
            for existing, path in self._paths.items()
            if existing != index
        }
        if self._selection == index:
            self._selection = wx.NOT_FOUND
        elif self._selection > index:
            self._selection -= 1
        self._changed()

    def SetString(self, index: int, label: str):
        if 0 <= index < len(self._labels):
            self._labels[index] = str(label)
            self._changed()

    def GetString(self, index: int) -> str:
        return self._labels[index] if 0 <= index < len(self._labels) else ""

    def GetCount(self) -> int:
        return len(self._labels)

    def GetSelection(self) -> int:
        return self._selection

    def SetSelection(self, index: int):
        if not 0 <= index < len(self._labels):
            self._selection = wx.NOT_FOUND
            return
        self._selection = index
        if self._batch_depth:
            return
        item = self._index_items.get(index)
        if item is not None and item.IsOk():
            self.SelectItem(item)
            self.EnsureVisible(item)

    def ToggleSelectedBranch(self):
        item = super().GetSelection()
        if item is not None and item.IsOk() and self.ItemHasChildren(item):
            if self.IsExpanded(item):
                self.Collapse(item)
            else:
                self.Expand(item)

    def ExpandSelectedBranch(self):
        item = super().GetSelection()
        if item is not None and item.IsOk() and self.ItemHasChildren(item):
            self.Expand(item)

    def CollapseSelectedBranch(self):
        item = super().GetSelection()
        if item is not None and item.IsOk() and self.ItemHasChildren(item):
            self.Collapse(item)

    @classmethod
    def _leaf_text(cls, label: str, leaf: object) -> str:
        """Display just the last path segment, retaining its channel count."""
        suffix_match = cls._COUNT_SUFFIX.search(label or "")
        suffix = suffix_match.group(0) if suffix_match else ""
        if isinstance(leaf, tuple):
            leaf = leaf[-1]
        return str(leaf) + suffix

    def _on_tree_selection(self, event):
        if self._rebuilding:
            event.Skip()
            return
        item = event.GetItem()
        # wxMSW returns a fresh ``sip.voidptr`` wrapper from GetID() on each
        # call, so it is not a stable dictionary key. TreeItemId comparison is.
        self._selection = next(
            (index for index, known_item in self._index_items.items() if item == known_item),
            wx.NOT_FOUND,
        )
        event.Skip()

    def _rebuild(self):
        # Rebuild only when a batched category refresh is complete. TreeCtrl
        # exposes the hierarchy to NVDA, unlike an owner-drawn replacement.
        self._rebuilding = True
        try:
            self.DeleteAllItems()
            self._index_items = {}
            root = self.AddRoot(_("Categories"))
            path_items: Dict[Tuple[object, ...], object] = {}
            for index, label in enumerate(self._labels):
                parent = root
                path: List[object] = []
                parts = self._paths.get(index) or self._path_parts(label)
                for part_index, part in enumerate(parts):
                    path.append(part)
                    path_key = tuple(path)
                    item = path_items.get(path_key)
                    if item is None:
                        text = self._leaf_text(label, part) if part_index == len(parts) - 1 else (
                            str(part[-1]) if isinstance(part, tuple) else str(part)
                        )
                        item = self.AppendItem(parent, text)
                        path_items[path_key] = item
                    elif part_index == len(parts) - 1:
                        # The category itself may also be a branch. Its own label
                        # includes its channel count, while its children stay put.
                        self.SetItemText(item, self._leaf_text(label, part))
                    parent = item
                self._index_items[index] = parent
            # A source's categories are visible immediately under its branch.
            # The user can still collapse any branch with Left; this only sets
            # the useful initial state after a playlist/category refresh.
            for item in path_items.values():
                if item.IsOk() and self.ItemHasChildren(item):
                    self.Expand(item)
        finally:
            self._rebuilding = False
        if 0 <= self._selection < len(self._labels):
            item = self._index_items.get(self._selection)
            if item is not None and item.IsOk():
                self.SelectItem(item)


class _VirtualChannelList(wx.ListCtrl):
    """Virtual, single-column list for the main channel / search-results list.

    Backed by the frame's ``displayed`` model (a list of {"type","data"[, "label"]}
    entries); only visible rows are realized, so 50k-300k entries stay responsive for the
    UI and NVDA. Exposes a small wx.ListBox-compatible API (GetSelection / SetSelection /
    GetCount / Clear) so the existing selection code did not need to change when the control
    was switched from wx.ListBox to a virtual wx.ListCtrl. This same virtual-ListCtrl pattern
    is already used (and screen-reader tested) by _VirtualWhatsOnList below.
    """

    def __init__(self, parent, frame):
        super().__init__(
            parent,
            style=wx.LC_REPORT | wx.LC_NO_HEADER | wx.LC_SINGLE_SEL | wx.LC_VIRTUAL,
            name="Channels",
        )
        # The constructor's name= never reaches NVDA on SysListView32; the
        # explicit accessible name does, so the list is announced as a name
        # instead of a bare "list". Same rule as _AccessibleCategoryTree.
        self.SetName(_("Channels"))
        if hasattr(self, "SetAccessibleName"):
            self.SetAccessibleName(_("Channels"))
        self._frame = frame
        self.InsertColumn(0, "")
        self.SetItemCount(0)
        self.Bind(wx.EVT_SIZE, self._on_size)

    def _on_size(self, event):
        # Keep the single column as wide as the control so long names aren't clipped.
        width = self.GetClientSize().width
        if width > 0:
            self.SetColumnWidth(0, width)
        event.Skip()

    def OnGetItemText(self, item, column):
        disp = self._frame.displayed
        if 0 <= item < len(disp):
            entry = disp[item]
            label = entry.get("label")
            if label is not None:
                return label
            data = entry.get("data") or {}
            name = data.get("name", "")
            # getattr rather than a direct call: the non-GUI test doubles that stand
            # in for the frame only supply displayed.
            decorate = getattr(self._frame, "_decorate_channel_label", None)
            return decorate(name, data) if callable(decorate) else name
        return ""

    def announce_item(self, index: int):
        """Re-fire focus for one row so a screen reader reads its new text.

        Only the focus state is cycled. Cycling the selection too would re-run the
        EPG lookup for the row and re-enter ``on_highlight`` for no benefit.
        """
        if index is None or not (0 <= index < self.GetItemCount()):
            return
        try:
            self.RefreshItem(index)
            self.SetItemState(index, 0, wx.LIST_STATE_FOCUSED)
            self.SetItemState(index, wx.LIST_STATE_FOCUSED, wx.LIST_STATE_FOCUSED)
        except Exception:
            LOG.debug("_VirtualChannelList.announce_item: ignored exception", exc_info=True)

    def _clear_active_item_state(self, minimum_index: int = 0):
        """Clear selected/focused state for active rows at or after an index."""
        old = self.GetItemCount()
        for idx in {self.GetFirstSelected(), self.GetFocusedItem()}:
            if idx is not None and minimum_index <= idx < old:
                try:
                    self.SetItemState(
                        idx,
                        0,
                        wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED,
                    )
                except Exception:
                    LOG.debug("_VirtualChannelList._clear_active_item_state: ignored exception", exc_info=True)

    def _set_count_safe(self, count: int, *, active_state_cleared: bool = False):
        """Resync the native item count, dropping stale selection/focus first.

        Shrinking a virtual SysListView32 while its focused/selected item index
        is >= the new count leaves MSAA/UIA holding a stale index, which can
        crash NVDA. Clear those item states before the shrink.
        """
        old = self.GetItemCount()
        if count < old:
            if not active_state_cleared:
                self._clear_active_item_state(count)
            LOG.debug("channel list count %d -> %d", old, count)
        self.SetItemCount(count)

    def replace_contents(self, entries: List[Dict[str, str]]):
        """Replace the backing rows while keeping native indexes valid.

        ``SetItemCount`` can trigger synchronous MSAA/UIA item queries. On a
        shrink, reduce the native count while the old model still serves all
        remaining indexes, then swap to the new model. On a grow, install the
        new model first so every existing index remains valid. Clear active
        state for *every* replacement, even when the old index would fit the
        new count: it represents a different logical row after a search.
        """
        if not isinstance(entries, list):
            entries = list(entries)
        old_count = self.GetItemCount()
        new_count = len(entries)
        self._clear_active_item_state()

        if new_count < old_count:
            self._set_count_safe(new_count, active_state_cleared=True)
            self._frame.displayed = entries
        else:
            self._frame.displayed = entries
            self._set_count_safe(new_count, active_state_cleared=True)

        self.Refresh()

    def set_virtual_count(self):
        """Resync the control to the current length of frame.displayed."""
        self._set_count_safe(len(self._frame.displayed))
        width = self.GetClientSize().width
        if width > 0:
            self.SetColumnWidth(0, width)

    # --- wx.ListBox-compatible shims so existing call sites keep working ---
    def GetSelection(self):
        return self.GetFirstSelected()

    def SetSelection(self, index):
        if index is None or index < 0:
            return
        if index < self.GetItemCount():
            self.Select(index)
            self.Focus(index)
            self.EnsureVisible(index)

    def GetCount(self):
        return self.GetItemCount()

    def Clear(self):
        self._set_count_safe(0)


class _VirtualWhatsOnList(wx.ListCtrl):
    """Virtual list control for fast loading of What's on Now."""

    def __init__(self, parent, dialog):
        super().__init__(parent, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_VIRTUAL)
        self.dialog = dialog

    def OnGetItemText(self, item, column):
        if 0 <= item < len(self.dialog.filtered_programs):
            prog = self.dialog.filtered_programs[item]
            title = prog.get("title") or _("(No title)")
            channel = prog.get("channel_name") or _("Unknown")
            return f"{title} - {channel}"
        return ""
