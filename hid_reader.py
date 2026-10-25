"""Minimal Windows HID reader; uses only the Python standard library."""

import ctypes as C
from ctypes import wintypes as W


VID = 0x188A
PID = 0x1102
INVALID_HANDLE_VALUE = C.c_void_p(-1).value
DIGCF_PRESENT = 0x02
DIGCF_DEVICEINTERFACE = 0x10
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x01
FILE_SHARE_WRITE = 0x02
OPEN_EXISTING = 3


class GUID(C.Structure):
    _fields_ = [
        ("Data1", W.DWORD), ("Data2", W.WORD), ("Data3", W.WORD),
        ("Data4", C.c_ubyte * 8),
    ]


class InterfaceData(C.Structure):
    _fields_ = [
        ("cbSize", W.DWORD), ("InterfaceClassGuid", GUID),
        ("Flags", W.DWORD), ("Reserved", C.c_void_p),
    ]


class HidCaps(C.Structure):
    _fields_ = [
        ("Usage", W.WORD), ("UsagePage", W.WORD),
        ("InputReportByteLength", W.WORD),
        ("OutputReportByteLength", W.WORD),
        ("FeatureReportByteLength", W.WORD),
        ("Reserved", W.WORD * 17),
        ("NumberLinkCollectionNodes", W.WORD),
        ("NumberInputButtonCaps", W.WORD),
        ("NumberInputValueCaps", W.WORD),
        ("NumberInputDataIndices", W.WORD),
        ("NumberOutputButtonCaps", W.WORD),
        ("NumberOutputValueCaps", W.WORD),
        ("NumberOutputDataIndices", W.WORD),
        ("NumberFeatureButtonCaps", W.WORD),
        ("NumberFeatureValueCaps", W.WORD),
        ("NumberFeatureDataIndices", W.WORD),
    ]


setupapi = C.WinDLL("setupapi", use_last_error=True)
hid = C.WinDLL("hid", use_last_error=True)
kernel32 = C.WinDLL("kernel32", use_last_error=True)

hid.HidD_GetHidGuid.argtypes = [C.POINTER(GUID)]
setupapi.SetupDiGetClassDevsW.argtypes = [C.POINTER(GUID), W.LPCWSTR, W.HWND, W.DWORD]
setupapi.SetupDiGetClassDevsW.restype = W.HANDLE
setupapi.SetupDiEnumDeviceInterfaces.argtypes = [W.HANDLE, C.c_void_p, C.POINTER(GUID), W.DWORD, C.POINTER(InterfaceData)]
setupapi.SetupDiEnumDeviceInterfaces.restype = W.BOOL
setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [W.HANDLE, C.POINTER(InterfaceData), C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.c_void_p]
setupapi.SetupDiGetDeviceInterfaceDetailW.restype = W.BOOL
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [W.HANDLE]
kernel32.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, C.c_void_p, W.DWORD, W.DWORD, W.HANDLE]
kernel32.CreateFileW.restype = W.HANDLE
kernel32.ReadFile.argtypes = [W.HANDLE, C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.c_void_p]
kernel32.ReadFile.restype = W.BOOL
kernel32.WriteFile.argtypes = [W.HANDLE, C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.c_void_p]
kernel32.WriteFile.restype = W.BOOL
kernel32.CloseHandle.argtypes = [W.HANDLE]
kernel32.CancelIoEx.argtypes = [W.HANDLE, C.c_void_p]
hid.HidD_GetPreparsedData.argtypes = [W.HANDLE, C.POINTER(C.c_void_p)]
hid.HidD_GetPreparsedData.restype = W.BOOL
hid.HidD_FreePreparsedData.argtypes = [C.c_void_p]
hid.HidP_GetCaps.argtypes = [C.c_void_p, C.POINTER(HidCaps)]
hid.HidP_GetCaps.restype = C.c_long


def device_paths():
    guid = GUID()
    hid.HidD_GetHidGuid(C.byref(guid))
    info_set = setupapi.SetupDiGetClassDevsW(C.byref(guid), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    if info_set == INVALID_HANDLE_VALUE:
        raise C.WinError(C.get_last_error())
    try:
        index = 0
        while True:
            entry = InterfaceData()
            entry.cbSize = C.sizeof(InterfaceData)
            if not setupapi.SetupDiEnumDeviceInterfaces(info_set, None, C.byref(guid), index, C.byref(entry)):
                break
            index += 1
            needed = W.DWORD()
            setupapi.SetupDiGetDeviceInterfaceDetailW(info_set, C.byref(entry), None, 0, C.byref(needed), None)
            detail = C.create_string_buffer(needed.value)
            C.cast(detail, C.POINTER(W.DWORD))[0] = 8 if C.sizeof(C.c_void_p) == 8 else 6
            if not setupapi.SetupDiGetDeviceInterfaceDetailW(info_set, C.byref(entry), detail, needed.value, C.byref(needed), None):
                raise C.WinError(C.get_last_error())
            path = C.wstring_at(C.addressof(detail) + 4)
            if f"vid_{VID:04x}&pid_{PID:04x}" in path.lower():
                yield path
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(info_set)


class Reader:
    def __init__(self):
        paths = list(device_paths())
        if not paths:
            raise RuntimeError("CKOZ-00/13 (USB 188A:1102) wurde nicht gefunden.")
        self.handle = kernel32.CreateFileW(paths[0], GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, 0, None)
        if self.handle == INVALID_HANDLE_VALUE:
            raise RuntimeError("Der Stick lässt sich nicht öffnen. Bitte MRF schließen und erneut versuchen.")
        preparsed = C.c_void_p()
        if not hid.HidD_GetPreparsedData(self.handle, C.byref(preparsed)):
            self.close()
            raise C.WinError(C.get_last_error())
        try:
            caps = HidCaps()
            if hid.HidP_GetCaps(preparsed, C.byref(caps)) < 0:
                raise RuntimeError("HID-Berichtslänge konnte nicht ermittelt werden.")
            self.report_length = caps.InputReportByteLength
            self.output_length = caps.OutputReportByteLength
        finally:
            hid.HidD_FreePreparsedData(preparsed)

    def enable_reception(self):
        # MRF sends this command during startup before radio reports begin.
        command = bytes.fromhex("5a 05 1a 01 a5")
        if len(command) + 1 > self.output_length:
            raise RuntimeError("Der USB-Ausgabebericht ist für den Startbefehl zu kurz.")
        report = C.create_string_buffer(self.output_length)
        report.raw = (b"\x00" + command).ljust(self.output_length, b"\x00")
        count = W.DWORD()
        if not kernel32.WriteFile(self.handle, report, self.output_length, C.byref(count), None):
            raise C.WinError(C.get_last_error())
        if count.value != self.output_length:
            raise RuntimeError("Der Startbefehl wurde nicht vollständig an den Stick gesendet.")

    def read(self):
        data = C.create_string_buffer(self.report_length)
        count = W.DWORD()
        if not kernel32.ReadFile(self.handle, data, self.report_length, C.byref(count), None):
            raise C.WinError(C.get_last_error())
        return data.raw[:count.value]

    def close(self):
        if getattr(self, "handle", None) not in (None, INVALID_HANDLE_VALUE):
            kernel32.CancelIoEx(self.handle, None)
            kernel32.CloseHandle(self.handle)
            self.handle = None
