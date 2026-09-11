"""Check the screen-reader names of the main-window controls.

Run: python tools/smoke_accessible_names_nvda.py

wx's SetName/SetAccessibleName is ignored by the MSW accessibles of the
category tree, the search edit and the virtual channels list, so the name has
to come from a wx.StaticText created immediately before the control (auto id =
control id - 1). This smoke tool pins that contract two ways:

* wx level: the label controls exist and sit immediately before their target.
* MSAA level: the control's real IAccessible reports the expected accName,
  read the way NVDA reads it (the same call the earlier probe used).

The MSAA read needs pywinauto + comtypes, which the app already requires for
the smoke tools on this machine; the wx-level assertions run everywhere.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import wx

from smoke_favorites_shutdown import build_frame

app = wx.App()
frame = build_frame()
frame.Show()
app.Yield()

pairs = (
    ("Categories", frame.categories_label, frame.group_list),
    ("Search", frame.search_label, frame.filter_box),
    ("Channels", frame.channels_label, frame.channel_list),
)

print("wx-level label association:")
for expected, label, ctrl in pairs:
    assert label.GetLabel() == expected, label.GetLabel()
    assert label.GetId() == ctrl.GetId() - 1, (label.GetId(), ctrl.GetId())
    print(f"  {expected}: label id {label.GetId()} -> control id {ctrl.GetId()} OK")

msaa = None
try:
    import comtypes.client
    from comtypes import GUID
    import ctypes
    from ctypes import POINTER, Structure, byref, c_long, c_short, c_void_p, windll

    oleacc = comtypes.client.GetModule("oleacc.dll")
    IID_IAccessible = GUID("{618736E0-3C3D-11CF-810C-00AA00389B71}")
    OBJID_CLIENT = 0xFFFFFFFC

    class _VARIANT(Structure):
        _fields_ = [
            ("vt", c_short),
            ("reserved1", c_long),
            ("reserved2", c_long),
            ("reserved3", c_long),
            ("data", c_void_p),
        ]

    def msaa_name(ctrl):
        """accName of the control's client accessible, via the raw vtable.

        comtypes' generated get_accName wrapper mis-declares the out-param, so
        call IAccessible::get_accName (vtable slot 10) through ctypes.
        """
        acc = POINTER(oleacc.IAccessible)()
        hr = windll.oleacc.AccessibleObjectFromWindow(
            ctrl.GetHandle(), OBJID_CLIENT, byref(IID_IAccessible), byref(acc))
        if hr != 0:
            raise OSError(f"AccessibleObjectFromWindow hr=0x{hr & 0xffffffff:08x}")
        vt = _VARIANT()
        vt.vt = 3  # VT_I4, CHILDID_SELF
        name = c_void_p()
        ptr = ctypes.cast(acc, c_void_p).value
        vtable = ctypes.cast(ptr, POINTER(c_void_p)).contents.value
        fn = ctypes.cast(vtable, POINTER(c_void_p))[10]
        proto = ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, _VARIANT, POINTER(c_void_p))
        rc = proto(fn)(acc, vt, byref(name))
        if rc != 0:
            return None  # S_FALSE / DISP_E_MEMBERNOTFOUND: no name exposed
        if not name.value:
            return None
        try:
            return ctypes.wstring_at(name.value)
        finally:
            try:
                windll.oleaut32.SysFreeString(name.value)
            except Exception:
                pass

    msaa = msaa_name
except Exception as exc:
    print(f"MSAA check unavailable ({exc}); wx-level assertions only.")

if msaa is not None:
    print("MSAA accName (what NVDA reads):")
    for expected, _label, ctrl in pairs:
        name = msaa(ctrl)
        assert name == expected, f"expected {expected!r}, got {name!r}"
        print(f"  {expected}: OK")
    print("All accessible names verified at the MSAA level.")

frame._exit_forced = True
frame.Close()
app.Yield()
print("Accessible names: OK")
