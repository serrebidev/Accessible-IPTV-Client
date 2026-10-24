"""Optional application-owned TTS backend (issue #37, stage 2).

The screen reader (JAWS/NVDA) stays the default speech path and keeps
ownership of its voice, volume and audio endpoint. This module is the
*separate* application-owned backend: the application owns the synthesis, so
it may legitimately expose its own 0-100 volume control and output-device
selector. Those settings apply only to this backend, never to the screen
reader.

Windows only, via SAPI.SpVoice driven through IDispatch (no new
dependencies). The IDispatch vtable is fixed, so no vtable-index guessing.
Failures are reported to the caller without implicitly changing the output.
Speech must never take playback down with it.
"""

import ctypes
import logging
import sys
import threading
from ctypes import wintypes
from dataclasses import dataclass
from enum import Enum

LOG = logging.getLogger(__name__)

_IS_WINDOWS = sys.platform == "win32"

# SAPI.SpVoice as IDispatch; the SpVoice coclass is scriptable.
_CLSID_SpVoice = "{96749377-3391-11D2-9EE3-00C04F797396}"
_IID_IDispatch = "{00020400-0000-0000-C000-000000000046}"

_CLSCTX_ALL = 23
_COINIT_APARTMENTTHREADED = 0x2
_DISPATCH_METHOD = 1
_DISPATCH_PROPERTYGET = 2
_DISPATCH_PROPERTYPUT = 4
_DISPATCH_PROPERTYPUTREF = 8
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
_SPF_IS_NOT_XML = 16


class _BStr(str):
    pass


class _ComError(Exception):
    pass


class _VariantData(ctypes.Union):
    # VARIANT's union also holds a BRECORD (two pointers), which makes VARIANT
    # 24 bytes on 64-bit and 16 on 32-bit. Declared as a bare int64 it was 16
    # on 64-bit: Invoke wrote past the result and the app died at startup
    # (v1.147.0/1, 0xC0000409).
    _fields_ = [("data", ctypes.c_int64),
                ("_record", ctypes.c_void_p * 2)]


class _Variant(ctypes.Structure):
    _anonymous_ = ("_u",)
    _fields_ = [("vt", wintypes.USHORT),
                ("wReserved1", wintypes.USHORT),
                ("wReserved2", wintypes.USHORT),
                ("wReserved3", wintypes.USHORT),
                ("_u", _VariantData)]


class _Dispatch:
    """Minimal IDispatch client: method calls, property get/put, BSTR/i4/bool."""

    class _GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD),
                    ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_ubyte * 8)]

    def __init__(self, punk, addref=True):
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
        elif addref:
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
        func = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)(
            ctypes.cast(punk, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents[1])
        func(punk)

    def release(self):
        if self._punk:
            func = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)(
                self._vtable.contents[2])
            func(self._punk)
            self._punk = 0

    # -- VARIANT helpers -----------------------------------------------------

    _Variant = _Variant

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
            # Borrowed for the call only; the callee AddRefs what it keeps.
            var.data = value._punk
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
            return bool(var.data & 0xFFFF)  # VARIANT_BOOL is 16 bits
        if var.vt == _VT_DISPATCH and var.data:
            # Invoke already handed us a reference; take it over.
            return _Dispatch(var.data, addref=False)
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
            ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.POINTER(wintypes.LPCWSTR), wintypes.UINT,
            wintypes.LCID, ctypes.POINTER(wintypes.DWORD))(
                self._vtable.contents[5])
        # GetIDsOfNames(this, riid, names, count, lcid, dispids); riid is IID_NULL.
        iid_null = ctypes.create_string_buffer(16)
        hr = func(self._punk, iid_null, wname, 1, _LOCALE_SYSTEM_DEFAULT,
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
        # Without arguments the name may be a method (GetAudioOutputs) or a
        # property (Count); IDispatch takes both flags, as VBScript sends.
        flags = _DISPATCH_PROPERTYGET | _DISPATCH_METHOD if not args else _DISPATCH_METHOD
        if prop_put:
            # Object properties (AudioOutput) only accept "Set" (PUTREF);
            # None means Nothing, a null IDispatch, not VT_EMPTY.
            putref = args[0] is None or isinstance(args[0], _Dispatch)
            flags = _DISPATCH_PROPERTYPUTREF if putref else _DISPATCH_PROPERTYPUT
            if args[0] is None:
                variants[0].vt = _VT_DISPATCH
                arr[0].vt = _VT_DISPATCH
        func = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p, wintypes.DWORD,
            ctypes.c_void_p, wintypes.LCID, wintypes.WORD,
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


@dataclass(frozen=True)
class AudioOutput:
    id: str
    name: str


class RoutingState(str, Enum):
    DEFAULT = "default"
    READY = "selected-ready"
    PAUSED = "selected-missing-paused"
    FALLBACK = "approved-default-fallback"


class SpeechResult(str, Enum):
    SPOKEN = "spoken"
    UNAVAILABLE = "unavailable"
    OUTPUT_MISSING = "output-missing"
    FAILED = "failed"
    EMPTY = "empty"


class AppTtsBackend:
    """SAPI owned by the constructing (UI/COM apartment) thread.

    Retain the requested endpoint across outages, including an approved
    temporary fallback. Never confuse a successful asynchronous Speak call
    with proof of physical delivery; device changes also need live testing.
    """

    def __init__(self):
        self._voice = None
        self._lock = threading.RLock()
        self._owner_thread = threading.get_ident()
        self._volume = 100
        self._rate = 0
        self._selected_output = ""
        self._route = RoutingState.DEFAULT
        self.last_result = SpeechResult.UNAVAILABLE
        self._speak_failed = False
        self._com_initialized = False
        if not _IS_WINDOWS:
            return
        try:
            init = ctypes.windll.ole32.CoInitializeEx
            init.argtypes = [ctypes.c_void_p, wintypes.DWORD]
            init.restype = ctypes.c_long
            self._com_initialized = init(None, _COINIT_APARTMENTTHREADED) in (0, 1)
            self._voice = _Dispatch(None)
        except Exception:
            LOG.warning("app_tts: SAPI.SpVoice unavailable", exc_info=True)

    def _check_thread(self):
        if threading.get_ident() != self._owner_thread:
            raise RuntimeError("SAPI must be used on its owning COM thread")

    @property
    def available(self):
        return self._voice is not None

    @property
    def routing_state(self):
        return self._route

    def speak(self, text, device_policy="pause"):
        self._check_thread()
        if not self._voice:
            self.last_result = SpeechResult.UNAVAILABLE
            return False
        if not (text or "").strip():
            self.last_result = SpeechResult.EMPTY
            return False
        if not self.validate_output(device_policy):
            self.last_result = SpeechResult.OUTPUT_MISSING
            return False
        try:
            with self._lock:
                self._voice.call("Speak", text,
                                 _SPF_ASYNC | _SPF_PURGEBEFORESPEAK | _SPF_IS_NOT_XML)
            self._speak_failed = False
            self.last_result = SpeechResult.SPOKEN
            return True
        except _ComError:
            self.stop()
            if not self._speak_failed:
                self._speak_failed = True
                LOG.warning("app_tts: Speak failed", exc_info=True)
            self.last_result = SpeechResult.FAILED
            return False

    def stop(self):
        self._check_thread()
        if self._voice:
            try:
                with self._lock:
                    self._voice.call("Speak", "",
                                     _SPF_ASYNC | _SPF_PURGEBEFORESPEAK | _SPF_IS_NOT_XML)
            except _ComError:
                LOG.debug("app_tts: purge failed", exc_info=True)

    @property
    def volume(self):
        return self._volume

    def set_volume(self, level):
        self._check_thread()
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

    @property
    def rate(self):
        return self._rate

    def set_rate(self, rate):
        """Set the private SAPI voice's rate; never modify screen-reader settings.

        SAPI accepts -10..10, with zero as normal. Invalid saved config falls
        back to normal; a failed COM write does not change the reported value.
        The engine applies a new rate at the next Speak stream boundary.
        """
        self._check_thread()
        try:
            value = int(rate) if not isinstance(rate, bool) else 0
        except (TypeError, ValueError, OverflowError):
            value = 0
        value = max(-10, min(10, value))
        if not self._voice:
            return False
        try:
            with self._lock:
                self._voice.put("Rate", value)
            self._rate = value
            return True
        except _ComError:
            LOG.warning("app_tts: SetRate failed", exc_info=True)
            return False

    def list_output_devices(self):
        """Return stable token IDs separately from display descriptions."""
        self._check_thread()
        if not self._voice:
            return []
        try:
            with self._lock:
                tokens = self._voice.call("GetAudioOutputs")
                result = []
                try:
                    for i in range(int(tokens.get("Count") or 0)):
                        item = tokens.call("Item", i)
                        try:
                            token_id = str(item.get("Id") or "")
                            name = str(item.call("GetDescription") or "")
                            if token_id:
                                result.append(AudioOutput(token_id, name or token_id))
                        finally:
                            item.release()
                finally:
                    tokens.release()
                return result
        except _ComError:
            LOG.debug("app_tts: enumeration failed", exc_info=True)
            return []

    def list_outputs(self):
        """Compatibility: friendly names. New UI code uses list_output_devices."""
        return [output.name for output in self.list_output_devices()]

    def _select_requested_output(self):
        wanted = self._selected_output
        devices = self.list_output_devices()
        matches = [d for d in devices if d.id.casefold() == wanted.casefold()]
        if not matches:
            # Migrate a legacy friendly name only if it is an exact, unique
            # match. Substrings and duplicate names cannot identify an output.
            matches = [d for d in devices if d.name.casefold() == wanted.casefold()]
        if len(matches) != 1:
            return False
        token_id = matches[0].id
        if self._route == RoutingState.READY and token_id == wanted:
            return True
        tokens = self._voice.call("GetAudioOutputs")
        try:
            for i in range(int(tokens.get("Count") or 0)):
                item = tokens.call("Item", i)
                try:
                    if str(item.get("Id") or "").casefold() == token_id.casefold():
                        self.stop()
                        self._voice.put("AudioOutput", item)
                        self._selected_output = token_id
                        self._route = RoutingState.READY
                        return True
                finally:
                    item.release()
        finally:
            tokens.release()
        return False

    def set_output(self, identity):
        """Select an ID, or migrate one unambiguous legacy description.

        A missing selection remains requested and blocks captions under pause,
        including at startup. Call reset_output for an explicit default.
        """
        self._check_thread()
        self.stop()
        self._selected_output = str(identity or "")
        self._route = RoutingState.PAUSED
        return self.validate_output("pause") if identity else self.reset_output()

    def validate_output(self, policy="pause"):
        self._check_thread()
        if not self._voice:
            return False
        with self._lock:
            try:
                if not self._selected_output:
                    if self._route != RoutingState.DEFAULT:
                        self._voice.put("AudioOutput", None)
                    self._route = RoutingState.DEFAULT
                    return True
                if self._select_requested_output():
                    return True
                if policy == "default":
                    if self._route != RoutingState.FALLBACK:
                        self.stop()
                        self._voice.put("AudioOutput", None)
                    self._route = RoutingState.FALLBACK
                    return True
            except _ComError:
                LOG.debug("app_tts: output selection failed", exc_info=True)
            if self._route != RoutingState.PAUSED:
                self.stop()
            self._route = RoutingState.PAUSED
            return False

    def reset_output(self):
        """Explicit user selection of system default; clear the saved target."""
        self._check_thread()
        self.stop()
        self._selected_output = ""
        self._route = RoutingState.PAUSED
        return self.validate_output()

    @property
    def selected_output(self):
        return self._selected_output

    def output_present(self):
        if not self._voice:
            return False
        if not self._selected_output:
            return True
        return any(d.id.casefold() == self._selected_output.casefold()
                   for d in self.list_output_devices())

    def close(self):
        self._check_thread()
        self.stop()
        voice, self._voice = self._voice, None
        if voice:
            voice.release()
        if self._com_initialized:
            self._com_initialized = False
            ctypes.windll.ole32.CoUninitialize()
