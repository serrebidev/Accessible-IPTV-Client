"""Optional application-owned TTS backend (issue #37, stage 2).

The screen reader (JAWS/NVDA) stays the default speech path and keeps
ownership of its voice, volume and audio endpoint. This module is the
*separate* application-owned backend: the application owns the synthesis, so
it may legitimately expose its own 0-100 volume control and output-device
selector. Those settings apply only to this backend, never to the screen
reader.

Windows only, via SAPI.SpVoice driven through IDispatch (no new
dependencies). The IDispatch vtable is fixed, so no vtable-index guessing.
Every COM failure degrades to ``available == False``; the caller then falls
back to screen-reader speech. Speech must never take playback down with it.
"""

import ctypes
import logging
import platform
import threading
from ctypes import wintypes

LOG = logging.getLogger(__name__)

_IS_WINDOWS = platform.system() == "Windows"

# SAPI.SpVoice as IDispatch; the SpVoice coclass is scriptable.
_CLSID_SpVoice = "{96749377-3391-11D2-9EE3-00C04F797396}"
_IID_IDispatch = "{00020400-0000-0000-C000-000000000046}"

_CLSCTX_ALL = 23
_COINIT_APARTMENTTHREADED = 0x2
_DISPATCH_METHOD = 1
_DISPATCH_PROPERTYGET = 2
_DISPATCH_PROPERTYPUT = 4
_DISPID_PROPERTYPUT = -3
_LOCALE_SYSTEM_DEFAULT = 0x800

# VARIANT type tags we use.
_VT_EMPTY = 0
_VT_I4 = 3
_VT_BSTR = 8
_VT_DISPATCH = 9
_VT_BOOL = 11

# SAPI speak flags: async + purge anything still queued, so a fast run of
# cues never stacks up minutes of stale speech behind the live one.
_SPF_ASYNC = 1
_SPF_PURGEBEFORESPEAK = 2


class _BStr(str):
    pass


class _ComError(Exception):
    pass


class _Dispatch:
    """Minimal IDispatch client: method calls, property get/put, BSTR/i4/bool."""

    class _GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD),
                    ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_ubyte * 8)]

    def __init__(self, punk):
        self._ole32 = ctypes.windll.ole32
        self._oleaut32 = ctypes.windll.oleaut32
        # Pointer widths matter on 64-bit: declare every prototype.
        self._ole32.CLSIDFromString.argtypes = [
            wintypes.LPCWSTR, ctypes.POINTER(self._GUID)]
        self._ole32.CLSIDFromString.restype = ctypes.c_long
        self._ole32.CoCreateInstance.argtypes = [
            ctypes.POINTER(self._GUID), ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(self._GUID), ctypes.POINTER(ctypes.c_void_p)]
        self._ole32.CoCreateInstance.restype = ctypes.c_long
        self._oleaut32.SysAllocString.argtypes = [wintypes.LPCWSTR]
        self._oleaut32.SysAllocString.restype = ctypes.c_void_p
        self._oleaut32.SysFreeString.argtypes = [ctypes.c_void_p]
        self._oleaut32.SysFreeString.restype = None
        # QueryInterface for IDispatch on the raw pointer.
        iid = self._guid(_IID_IDispatch)
        ppv = ctypes.c_void_p()
        hr = self._ole32.CoCreateInstance(
            ctypes.byref(self._guid(_CLSID_SpVoice)), None, _CLSCTX_ALL,
            ctypes.byref(iid), ctypes.byref(ppv)) if punk is None else 0
        if punk is None:
            if hr != 0 or not ppv.value:
                raise _ComError(f"CoCreateInstance(SpVoice) failed: {hr:#x}")
            punk = ppv.value
        else:
            # punk is an IDispatch pointer obtained elsewhere; AddRef it.
            self._addref(punk)
        self._punk = punk
        self._vtable = ctypes.cast(
            punk, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))

    def _guid(self, text):
        guid = self._GUID()
        hr = self._ole32.CLSIDFromString(text, ctypes.byref(guid))
        if hr != 0:
            raise _ComError(f"CLSIDFromString failed for {text}")
        return guid

    def _addref(self, punk):
        func = ctypes.WINFUNCTYPE(wintypes.ULONG)(
            ctypes.cast(punk, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents[1])
        func(punk)

    def release(self):
        if self._punk:
            func = ctypes.WINFUNCTYPE(wintypes.ULONG)(
                self._vtable.contents[2])
            func(self._punk)
            self._punk = 0

    # -- VARIANT helpers -----------------------------------------------------

    class _Variant(ctypes.Structure):
        _fields_ = [("vt", wintypes.USHORT),
                    ("wReserved1", wintypes.USHORT),
                    ("wReserved2", wintypes.USHORT),
                    ("wReserved3", wintypes.USHORT),
                    ("data", ctypes.c_int64)]

    def _to_variant(self, value):
        var = self._Variant()
        if isinstance(value, bool):
            var.vt = _VT_BOOL
            var.data = -1 if value else 0
        elif isinstance(value, int):
            var.vt = _VT_I4
            var.data = value
        elif isinstance(value, _Dispatch):
            var.vt = _VT_DISPATCH
            var.data = value._punk
            value._addref(value._punk)
        elif isinstance(value, str):
            var.vt = _VT_BSTR
            bstr = self._oleaut32.SysAllocString(ctypes.c_wchar_p(value))
            if not bstr:
                raise _ComError("SysAllocString failed")
            var.data = bstr
        elif value is None:
            var.vt = _VT_EMPTY
        else:
            raise _ComError(f"unsupported variant type: {type(value)}")
        return var

    def _from_variant(self, var):
        if var.vt == _VT_BSTR and var.data:
            text = ctypes.wstring_at(var.data)
            self._oleaut32.SysFreeString(var.data)
            return text
        if var.vt == _VT_I4:
            return ctypes.c_int32(var.data & 0xFFFFFFFF).value
        if var.vt == _VT_BOOL:
            return bool(var.data)
        if var.vt == _VT_DISPATCH and var.data:
            return _Dispatch(var.data)
        if var.vt == _VT_EMPTY:
            return None
        return None

    def _clear_variant(self, var):
        # Only BSTR needs freeing here; IDispatch refs are owned by caller.
        if var.vt == _VT_BSTR and var.data:
            self._oleaut32.SysFreeString(var.data)

    # -- IDispatch --------------------------------------------------------------

    def _get_dispid(self, name):
        wname = (ctypes.c_wchar_p * 1)(name)
        dispid = wintypes.DWORD()
        # IDispatch vtable: 0 QI, 1 AddRef, 2 Release, 3 GetTypeInfoCount,
        # 4 GetTypeInfo, 5 GetIDsOfNames, 6 Invoke.
        func = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p,
            ctypes.POINTER(wintypes.LPCWSTR), wintypes.UINT,
            wintypes.LCID, ctypes.POINTER(wintypes.DWORD))(
                self._vtable.contents[5])
        hr = func(self._punk, wname, 1, _LOCALE_SYSTEM_DEFAULT,
                  ctypes.byref(dispid))
        if hr != 0:
            raise _ComError(f"GetIDsOfNames({name}) failed: {hr:#x}")
        return dispid.value

    def invoke(self, name, args=(), prop_put=False):
        dispid = self._get_dispid(name)
        # DISPPARAMS: args reversed (right-to-left).
        variants = [self._to_variant(a) for a in reversed(args)]
        arr = (self._Variant * len(variants))(*variants) if variants else None
        named = (wintypes.DWORD * 1)(_DISPID_PROPERTYPUT) if prop_put else None

        class DISPPARAMS(ctypes.Structure):
            _fields_ = [("rgvarg", ctypes.POINTER(self._Variant)),
                        ("rgdispidNamedArgs", ctypes.POINTER(wintypes.DWORD)),
                        ("cArgs", wintypes.UINT),
                        ("cNamedArgs", wintypes.UINT)]

        dp = DISPPARAMS(
            ctypes.cast(arr, ctypes.POINTER(self._Variant)) if arr else None,
            ctypes.cast(named, ctypes.POINTER(wintypes.DWORD)) if named else None,
            len(variants), 1 if prop_put else 0)
        result = self._Variant()
        flags = _DISPATCH_PROPERTYPUT if prop_put else (
            _DISPATCH_PROPERTYGET if not args else _DISPATCH_METHOD)
        func = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(wintypes.GUID), wintypes.LCID, wintypes.WORD,
            ctypes.POINTER(DISPPARAMS), ctypes.POINTER(self._Variant),
            ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT))(
                self._vtable.contents[6])
        iid_null = ctypes.c_buffer(16)
        hr = func(self._punk, dispid, iid_null, _LOCALE_SYSTEM_DEFAULT,
                  flags, ctypes.byref(dp), ctypes.byref(result), None, None)
        for var in variants:
            self._clear_variant(var)
        if hr != 0:
            self._clear_variant(result)
            raise _ComError(f"Invoke({name}) failed: {hr:#x}")
        value = self._from_variant(result)
        return value

    def call(self, name, *args):
        return self.invoke(name, args)

    def get(self, name):
        return self.invoke(name, (), prop_put=False)

    def put(self, name, value):
        self.invoke(name, (value,), prop_put=True)


class AppTtsBackend:
    """Application-owned TTS. Windows/SAPI only; unavailable elsewhere.

    Volume (0-100) and output-device selection apply only to this backend.
    """

    def __init__(self):
        self._voice = None
        self._lock = threading.Lock()
        self._volume = 100
        if not _IS_WINDOWS:
            return
        try:
            ctypes.windll.ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
        except Exception:
            LOG.debug("app_tts: CoInitializeEx failed", exc_info=True)
            return
        try:
            self._voice = _Dispatch(None)
        except _ComError:
            LOG.warning("app_tts: SAPI.SpVoice unavailable", exc_info=True)
            self._voice = None

    @property
    def available(self) -> bool:
        return self._voice is not None

    def speak(self, text: str) -> bool:
        """Speak asynchronously, purging queued speech first."""
        if not self._voice or not (text or "").strip():
            return False
        try:
            with self._lock:
                self._voice.call("Speak", text, _SPF_ASYNC | _SPF_PURGEBEFORESPEAK)
            return True
        except _ComError:
            LOG.warning("app_tts: Speak failed", exc_info=True)
            return False

    def stop(self) -> None:
        if not self._voice:
            return
        try:
            with self._lock:
                # Purge with empty text.
                self._voice.call("Speak", "", _SPF_ASYNC | _SPF_PURGEBEFORESPEAK)
        except _ComError:
            LOG.debug("app_tts: stop failed", exc_info=True)

    # -- volume ------------------------------------------------------------------

    @property
    def volume(self) -> int:
        return self._volume

    def set_volume(self, level: int) -> bool:
        """0-100. Applies only to this backend's speech."""
        level = max(0, min(100, int(level)))
        if not self._voice:
            return False
        try:
            with self._lock:
                self._voice.put("Volume", level)
            self._volume = level
            return True
        except _ComError:
            LOG.warning("app_tts: SetVolume failed", exc_info=True)
            return False

    # -- output devices ------------------------------------------------------------

    def list_outputs(self):
        """Friendly names of SAPI audio outputs; [] when unavailable."""
        if not self._voice:
            return []
        try:
            with self._lock:
                tokens = self._voice.call("GetAudioOutputs")
            names = []
            try:
                count = tokens.get("Count")
                for i in range(int(count or 0)):
                    item = tokens.call("Item", i)
                    try:
                        names.append(item.call("GetDescription"))
                    finally:
                        item.release()
            finally:
                tokens.release()
            return [n for n in names if n]
        except _ComError:
            LOG.debug("app_tts: output enumeration failed", exc_info=True)
            return []

    def set_output(self, name: str) -> bool:
        """Select a SAPI audio output by (sub)string of its friendly name."""
        if not self._voice or not name:
            return False
        try:
            with self._lock:
                tokens = self._voice.call("GetAudioOutputs")
                try:
                    count = int(tokens.get("Count") or 0)
                    for i in range(count):
                        item = tokens.call("Item", i)
                        try:
                            desc = item.call("GetDescription") or ""
                        finally:
                            pass
                        if name.lower() in desc.lower():
                            self._voice.put("AudioOutput", item)
                            item.release()
                            return True
                        item.release()
                finally:
                    tokens.release()
            return False
        except _ComError:
            LOG.warning("app_tts: SetOutput failed", exc_info=True)
            return False

    def close(self) -> None:
        voice, self._voice = self._voice, None
        if voice:
            try:
                voice.release()
            except Exception:
                LOG.debug("app_tts: release failed", exc_info=True)
            try:
                ctypes.windll.ole32.CoUninitialize()
            except Exception:
                LOG.debug("app_tts: CoUninitialize failed", exc_info=True)
