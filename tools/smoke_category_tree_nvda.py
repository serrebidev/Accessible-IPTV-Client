"""Exercise native category-tree hierarchy and keyboard activation for NVDA.

Run: python tools/smoke_category_tree_nvda.py
"""
import wx

from smoke_favorites_shutdown import build_frame
import main


def find_child(tree, parent, wanted):
    child, cookie = tree.GetFirstChild(parent)
    while child and child.IsOk():
        if tree.GetItemText(child) == wanted:
            return child
        child, cookie = tree.GetNextChild(parent, cookie)
    return None


class TreeKey:
    """Small event stand-in for the frame's keyboard-only tree handler."""

    def __init__(self, key):
        self.key = key

    def GetKeyCode(self):
        return self.key

    def ShiftDown(self):
        return False

    def Skip(self):
        raise AssertionError("left/right should be handled by the category tree")


app = wx.App()
frame = build_frame()
frame.Show()
app.Yield()

channels = [
    {"name": "Football One", "group": "Sport/Football", "playlist-id": "alpha"},
    {"name": "Rugby One", "group": "Sport/Rugby", "playlist-id": "alpha"},
    {"name": "News One", "group": "News", "playlist-id": "beta"},
]
frame.playlist_sources = [
    {"id": "alpha", "type": "xtream", "name": "Alpha"},
    {"id": "beta", "type": "stalker", "name": "Beta"},
]
frame.all_channels = channels
frame.channels_by_group = {
    "Sport/Football": [channels[0]],
    "Sport/Rugby": [channels[1]],
    "News": [channels[2]],
}
frame._invalidate_favorites_cache()
frame._refresh_group_ui()
app.Yield()

tree = frame.group_list
assert isinstance(tree, main._AccessibleCategoryTree)
assert tree.GetName() == "Categories"
root = tree.GetRootItem()
alpha = find_child(tree, root, "Xtream Codes – Alpha")
assert alpha is not None and tree.ItemHasChildren(alpha) and tree.IsExpanded(alpha)
sport = find_child(tree, alpha, "Sport")
assert sport is not None and tree.ItemHasChildren(sport)
football = find_child(tree, sport, "Football (1)")
assert football is not None

# Left/right are dedicated expand/collapse commands, without activating a
# category or moving focus to the channel list.
tree.SelectItem(alpha)
frame.on_group_key(TreeKey(wx.WXK_LEFT))
assert not tree.IsExpanded(alpha)
frame.on_group_key(TreeKey(wx.WXK_RIGHT))
assert tree.IsExpanded(alpha)

# A hierarchy-only node can be selected and expanded without changing the
# playing category. Its state is presented natively to screen readers.
tree.SelectItem(sport)
app.Yield()
before = frame.current_group
assert tree.GetSelection() == wx.NOT_FOUND
frame._activate_selected_group()
assert frame.current_group == before

# A leaf maps back to its original group key, then activation shows its rows.
football_key = ("playlist-group", "alpha", "Sport/Football")
football_index = frame._group_keys.index(football_key)
tree.SetSelection(football_index)
frame._activate_selected_group()
app.Yield()
assert frame.current_group == football_key
assert tree.GetSelection() == football_index
assert frame.channel_list.GetCount() == 1
assert frame.channel_list.OnGetItemText(0, 0) == "Football One"

frame._exit_forced = True
frame.Close()
app.Yield()
print("Native category tree hierarchy, parent expansion and leaf activation: OK")
