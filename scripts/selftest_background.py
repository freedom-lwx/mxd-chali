"""后台模式自检：自己建一个 Win32 窗口当探针，检查 PostMessage 发过去的键鼠消息对不对。

不碰游戏、不需要任何窗口在前台：
    python scripts/selftest_background.py

几项都"通过"说明后台发送的打包和投递是对的；游戏客户端认不认这些消息只能到游戏里试。
"""

from __future__ import annotations

import ctypes
import os
import sys
import time
from ctypes import wintypes as wt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if os.name != "nt":
    print("只在 Windows 上自检")
    raise SystemExit(1)

from chali_macro.winapi import MessageInput, pack_point  # noqa: E402

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_void_p, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
CW_USEDEFAULT = -2147483648
WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_EX_NOACTIVATE = 0x08000000
SW_SHOWNOACTIVATE = 4
PM_REMOVE = 0x0001


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wt.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wt.HINSTANCE),
        ("hIcon", wt.HICON),
        ("hCursor", wt.HANDLE),
        ("hbrBackground", wt.HBRUSH),
        ("lpszMenuName", wt.LPCWSTR),
        ("lpszClassName", wt.LPCWSTR),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wt.HWND), ("message", wt.UINT), ("wParam", wt.WPARAM),
        ("lParam", wt.LPARAM), ("time", wt.DWORD), ("pt", wt.POINT),
    ]


_user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
_user32.CreateWindowExW.restype = wt.HWND
_user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
_user32.DefWindowProcW.restype = ctypes.c_void_p
_user32.PeekMessageW.argtypes = [ctypes.POINTER(MSG), wt.HWND, wt.UINT, wt.UINT, wt.UINT]
_user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
_user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
_user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]

received: list[tuple[int, int, int]] = []


def _wndproc(hwnd, message, wparam, lparam):
    received.append((int(message), int(wparam), int(lparam)))
    return _user32.DefWindowProcW(hwnd, message, wparam, lparam)


def make_probe_window() -> tuple[int, object]:
    instance = _kernel32.GetModuleHandleW(None)
    proc = WNDPROC(_wndproc)  # 必须保持引用，否则回调会被回收
    wndclass = WNDCLASSW()
    wndclass.lpfnWndProc = proc
    wndclass.hInstance = instance
    wndclass.lpszClassName = "ChaliMsgProbe"
    if not _user32.RegisterClassW(ctypes.byref(wndclass)):
        raise OSError(ctypes.get_last_error(), "注册窗口类失败")
    hwnd = _user32.CreateWindowExW(
        WS_EX_NOACTIVATE, "ChaliMsgProbe", "chali msg probe", WS_OVERLAPPEDWINDOW,
        CW_USEDEFAULT, CW_USEDEFAULT, 320, 240, None, None, instance, None,
    )
    if not hwnd:
        raise OSError(ctypes.get_last_error(), "创建窗口失败")
    _user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
    return int(hwnd), proc


def pump(seconds: float) -> None:
    msg = MSG()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        while _user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.01)


def find(message: int) -> list[tuple[int, int, int]]:
    return [item for item in received if item[0] == message]


def main() -> int:
    hwnd, _proc = make_probe_window()
    input_backend = MessageInput(hwnd)
    failures = 0

    input_backend.press_key("y", 0.05)
    input_backend.wheel(100, 50, -3)
    input_backend.click(120, 60, "left", 1)
    pump(0.6)

    scan = int(_user32.MapVirtualKeyW(ord("Y"), 0))
    checks: list[tuple[str, bool, str]] = []

    downs = [item for item in find(0x0100) if (item[2] >> 16) & 0xFF == scan]
    ups = [item for item in find(0x0101) if (item[2] >> 16) & 0xFF == scan]
    checks.append(("按键 y", bool(downs and ups), f"down {len(downs)} / up {len(ups)}"))

    moves = [item for item in find(0x0200) if item[2] == pack_point(100, 50)]
    checks.append(("鼠标移动", bool(moves), f"{len(moves)} 次落在 (100,50)"))

    wheels = find(0x020A)
    wheel_delta = 0
    if wheels:
        raw = (wheels[0][1] >> 16) & 0xFFFF
        wheel_delta = raw - 65536 if raw & 0x8000 else raw
    checks.append(("滚轮 3 格", wheel_delta == -360, f"收到 {len(wheels)} 次，delta={wheel_delta}"))

    clicks = [item for item in find(0x0201) if item[2] == pack_point(120, 60)]
    releases = [item for item in find(0x0202) if item[2] == pack_point(120, 60)]
    checks.append(("点击", bool(clicks and releases), f"down {len(clicks)} / up {len(releases)}"))

    for name, passed, detail in checks:
        print(f"{name}：{'通过' if passed else '失败'}（{detail}）")
        failures += 0 if passed else 1

    _user32.DestroyWindow(hwnd)
    if failures:
        return 1
    print("后台发送的消息格式正确；游戏客户端认不认，还需要到游戏里点一次开始确认。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
