"""Characterise five v1.142.1 subtitle behaviours without a GUI or network.

These are audit probes, not acceptance tests for a completed implementation.
They execute selected, unchanged source methods using explicit wx/libVLC stubs.
Passing means the documented current behaviour was reproduced.
Run from any directory: python /path/to/translation_package/subtitle_audit_probes.py
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "internal_player.py"
EVENTS = []


class Dialog:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def ShowModal(self):
        return 1

    def GetPath(self):
        return str((ROOT / "audit-fixture.srt").resolve())


WX = SimpleNamespace(
    Accessible=SimpleNamespace(NotifyEvent=lambda *args: EVENTS.append(args)),
    ACC_EVENT_SYSTEM_ALERT=1, OBJID_CLIENT=0,
    FileDialog=Dialog, ID_OK=1, FD_OPEN=1, FD_FILE_MUST_EXIST=2,
)


def original_method(name):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef)
               and n.name == "InternalPlayerFrame")
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef)
                  and n.name == name)
    method.decorator_list = []
    module = ast.Module(body=[
        ast.ImportFrom(module="__future__", names=[
            ast.alias(name="annotations")], level=0),
        method,
    ], type_ignores=[])
    ast.fix_missing_locations(module)
    scope = {
        "wx": WX, "Path": Path, "LOG": logging.getLogger("subtitle-audit"),
        "vlc": SimpleNamespace(MediaSlaveType=SimpleNamespace(subtitle=0)),
        "_": lambda text: {"Off": "Kikapcsolva"}.get(text, text),
    }
    exec(compile(module, str(SOURCE), "exec"), scope)
    return scope[name]


STATUS = original_method("_update_status_label")
SELECT = original_method("_select_subtitle")
LOAD = original_method("_load_subtitle_file")
MENU = original_method("_on_subtitle_menu_select")


def frame(level=2, select_result=0, load_result=0):
    label = SimpleNamespace(value="")
    label.GetLabel = lambda: label.value
    label.SetLabel = lambda value: setattr(label, "value", value)
    result = SimpleNamespace(
        _last_bitrate_mbps=None, _last_buffer_seconds=2.0, _volume_value=50,
        _last_status_prefix="", _audio_track_label="", status_label=label,
        announcement_level=level,
        player=SimpleNamespace(
            video_set_spu=lambda track_id: select_result,
            add_slave=lambda *args: load_result,
        ),
        _subtitle_tracks=lambda: [(-1, "Disable"), (2, "English")],
    )
    result._update_status_label = lambda *args, **kwargs: STATUS(result, *args, **kwargs)
    return result


class CurrentBehaviour(unittest.TestCase):
    def setUp(self):
        EVENTS.clear()

    def test_unowned_menu_event_is_not_skipped(self):
        event = SimpleNamespace(skipped=False, GetId=lambda: 17)
        event.Skip = lambda: setattr(event, "skipped", True)
        target = SimpleNamespace(_subtitle_menu_map={18: 2})
        target._select_subtitle = lambda track: self.fail("unexpected selection")
        MENU(target, event)
        self.assertFalse(event.skipped)

    def test_selection_failure_has_no_explicit_alert_at_levels_one_and_two(self):
        for level in (1, 2):
            target = frame(level, select_result=-1)
            SELECT(target, 2)
            self.assertIn("Subtitle track unavailable", target.status_label.value)
            self.assertEqual(EVENTS, [])

    def test_file_load_failure_has_no_explicit_alert_at_levels_one_and_two(self):
        for level in (1, 2):
            target = frame(level, load_result=-1)
            LOAD(target, None)
            self.assertIn("Could not load subtitle file.", target.status_label.value)
            self.assertEqual(EVENTS, [])

    def test_file_load_success_has_no_explicit_alert_at_default_level(self):
        target = frame()
        LOAD(target, None)
        self.assertIn("Subtitle file loaded:", target.status_label.value)
        self.assertEqual(EVENTS, [])

    def test_off_status_uses_libvlc_label_instead_of_localised_off(self):
        target = frame()
        SELECT(target, -1)
        self.assertIn("Subtitles: Disable", target.status_label.value)
        self.assertNotIn("Kikapcsolva", target.status_label.value)
        self.assertEqual(len(EVENTS), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
