"""Windows 输入层：SendInput 键盘/鼠标、窗口枚举、客户区坐标、前台校验。

只依赖标准库。键盘按扫描码发送（DirectInput 游戏才认），鼠标坐标一律用
"窗口客户区像素"，由本模块换算成屏幕绝对坐标后再发送。
"""

from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes as wt
from dataclasses import dataclass

if os.name != "nt":
    raise ImportError("chali_macro.winapi 只在 Windows 上可用")


class InputError(RuntimeError):
    """输入被拒绝，或当前状态不允许继续发送。"""


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wt.LONG),
        ("dy", wt.LONG),
        ("mouseData", wt.DWORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wt.WORD),
        ("wScan", wt.WORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("union", _INPUTUNION)]


_ENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

for _name, _args, _result in (
    ("SendInput", [wt.UINT, ctypes.POINTER(_INPUT), ctypes.c_int], wt.UINT),
    ("MapVirtualKeyW", [wt.UINT, wt.UINT], wt.UINT),
    ("GetAsyncKeyState", [ctypes.c_int], ctypes.c_short),
    ("GetForegroundWindow", [], wt.HWND),
    ("GetWindowTextLengthW", [wt.HWND], ctypes.c_int),
    ("GetWindowTextW", [wt.HWND, wt.LPWSTR, ctypes.c_int], ctypes.c_int),
    ("IsWindowVisible", [wt.HWND], wt.BOOL),
    ("GetClientRect", [wt.HWND, ctypes.POINTER(wt.RECT)], wt.BOOL),
    ("ClientToScreen", [wt.HWND, ctypes.POINTER(wt.POINT)], wt.BOOL),
    ("ScreenToClient", [wt.HWND, ctypes.POINTER(wt.POINT)], wt.BOOL),
    ("GetCursorPos", [ctypes.POINTER(wt.POINT)], wt.BOOL),
    ("GetSystemMetrics", [ctypes.c_int], ctypes.c_int),
    ("GetWindowThreadProcessId", [wt.HWND, ctypes.POINTER(wt.DWORD)], wt.DWORD),
    ("EnumWindows", [_ENUMPROC, wt.LPARAM], wt.BOOL),
):
    _fn = getattr(_user32, _name)
    _fn.argtypes, _fn.restype = _args, _result

_INPUT_MOUSE = 0
_INPUT_KEYBOARD = 1

_MOUSEEVENTF_MOVE = 0x0001
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_MOUSEEVENTF_RIGHTDOWN = 0x0008
_MOUSEEVENTF_RIGHTUP = 0x0010
_MOUSEEVENTF_WHEEL = 0x0800
_MOUSEEVENTF_ABSOLUTE = 0x8000
_MOUSEEVENTF_VIRTUALDESK = 0x4000
_WHEEL_DELTA = 120

_KEYEVENTF_EXTENDEDKEY = 0x0001
_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_SCANCODE = 0x0008

_SM_XVIRTUALSCREEN = 76
_SM_YVIRTUALSCREEN = 77
_SM_CXVIRTUALSCREEN = 78
_SM_CYVIRTUALSCREEN = 79

_STOP_VK = 0x78  # F9

_NAMED_KEYS: dict[str, tuple[int, bool]] = {
    "left": (0x25, True),
    "right": (0x27, True),
    "up": (0x26, True),
    "down": (0x28, True),
    "space": (0x20, False),
    "enter": (0x0D, False),
    "return": (0x0D, False),
    "esc": (0x1B, False),
    "escape": (0x1B, False),
    "tab": (0x09, False),
    "home": (0x24, True),
    "end": (0x23, True),
    "pageup": (0x21, True),
    "pagedown": (0x22, True),
    "insert": (0x2D, True),
    "delete": (0x2E, True),
    "shift": (0x10, False),
    "ctrl": (0x11, False),
    "alt": (0x12, False),
}
for _index in range(1, 25):
    _NAMED_KEYS[f"f{_index}"] = (0x6F + _index, False)
for _index in range(10):
    _NAMED_KEYS[f"numpad{_index}"] = (0x60 + _index, False)


def normalize_key(key: str) -> str:
    """把用户输入的键名统一成小写标准名；非法名字抛 InputError。"""
    if not isinstance(key, str) or not key.strip():
        raise InputError("按键名不能为空")
    token = key.strip().lower()
    if len(token) == 1 and token.isascii() and token.isalnum():
        return token
    if token.startswith("f") and token[1:].isdigit():
        number = int(token[1:])
        if 1 <= number <= 24:
            return f"f{number}"
    if token in ("回车", "确认", "确定"):
        return "enter"
    if token in ("空格",):
        return "space"
    if token in ("上", "上方向", "上键"):
        return "up"
    if token in ("下", "下方向", "下键"):
        return "down"
    if token in ("左", "左方向", "左键"):
        return "left"
    if token in ("右", "右方向", "右键"):
        return "right"
    if token in _NAMED_KEYS:
        return token
    raise InputError(f"不支持的按键名：{key}")


def _virtual_key(key: str) -> tuple[int, bool]:
    token = normalize_key(key)
    if len(token) == 1:
        return ord(token.upper()), False
    return _NAMED_KEYS[token]


@dataclass(frozen=True)
class Window:
    hwnd: int
    title: str
    pid: int

    def client_size(self) -> tuple[int, int]:
        return client_size(self.hwnd)


def window_title(hwnd: int) -> str:
    length = _user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    _user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def list_windows() -> list[Window]:
    """列出所有可见、有标题的顶层窗口；游戏窗口在列表里自行挑。"""
    found: list[Window] = []

    def collect(hwnd, _param):
        if not _user32.IsWindowVisible(hwnd):
            return True
        title = window_title(hwnd)
        if not title.strip():
            return True
        pid = wt.DWORD(0)
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        found.append(Window(int(hwnd), title, int(pid.value)))
        return True

    _user32.EnumWindows(_ENUMPROC(collect), 0)
    found.sort(key=lambda item: item.title)
    return found


def client_size(hwnd: int) -> tuple[int, int]:
    rect = wt.RECT()
    if not _user32.GetClientRect(hwnd, ctypes.byref(rect)):
        raise InputError("读不到窗口客户区大小")
    return int(rect.right - rect.left), int(rect.bottom - rect.top)


def is_foreground(hwnd: int) -> bool:
    return int(_user32.GetForegroundWindow()) == int(hwnd)


def _client_to_screen(hwnd: int, x: int, y: int) -> tuple[int, int]:
    point = wt.POINT(int(x), int(y))
    if not _user32.ClientToScreen(hwnd, ctypes.byref(point)):
        raise InputError("客户区坐标换算屏幕坐标失败")
    return int(point.x), int(point.y)


def cursor_client(hwnd: int) -> tuple[int, int] | None:
    """当前鼠标所在的客户区坐标；不在窗口内返回 None。"""
    point = wt.POINT()
    if not _user32.GetCursorPos(ctypes.byref(point)):
        raise InputError("读不到鼠标位置")
    if not _user32.ScreenToClient(hwnd, ctypes.byref(point)):
        raise InputError("鼠标坐标换算失败")
    x, y = int(point.x), int(point.y)
    width, height = client_size(hwnd)
    if 0 <= x < width and 0 <= y < height:
        return x, y
    return None


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
_kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
_kernel32.OpenProcess.restype = wt.HANDLE
_kernel32.CloseHandle.argtypes = [wt.HANDLE]
_advapi32.OpenProcessToken.argtypes = [wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE)]
_advapi32.OpenProcessToken.restype = wt.BOOL
_advapi32.GetTokenInformation.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                         wt.DWORD, ctypes.POINTER(wt.DWORD)]
_advapi32.GetTokenInformation.restype = wt.BOOL


def process_elevated(pid: int) -> bool | None:
    """目标进程是否以管理员权限运行；读不到时返回 None。"""
    handle = _kernel32.OpenProcess(0x1000, False, int(pid))  # QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    token = wt.HANDLE()
    try:
        if not _advapi32.OpenProcessToken(handle, 0x0008, ctypes.byref(token)):
            return None
        size = wt.DWORD(0)
        _advapi32.GetTokenInformation(token, 20, None, 0, ctypes.byref(size))
        if size.value < ctypes.sizeof(wt.DWORD):
            return None
        buffer = ctypes.create_string_buffer(size.value)
        if not _advapi32.GetTokenInformation(token, 20, buffer, size.value,
                                            ctypes.byref(size)):
            return None
        return bool(ctypes.cast(buffer, ctypes.POINTER(wt.DWORD)).contents.value)
    finally:
        if token:
            _kernel32.CloseHandle(token)
        _kernel32.CloseHandle(handle)


def window_pid(hwnd: int) -> int:
    pid = wt.DWORD(0)
    _user32.GetWindowThreadProcessId(int(hwnd), ctypes.byref(pid))
    return int(pid.value)


def self_elevated() -> bool | None:
    return process_elevated(os.getpid())


def _send(command: _INPUT) -> None:
    sent = _user32.SendInput(1, ctypes.byref(command), ctypes.sizeof(command))
    if sent != 1:
        raise InputError("Windows 没有接受这次输入；请确认游戏窗口在前台且权限一致")


class WindowsInput:
    """面向一个游戏窗口的输入后端；所有操作都要求该窗口在前台。"""

    name = "win32"

    def __init__(self, hwnd: int, *, stop_vk: int = _STOP_VK) -> None:
        self.hwnd = int(hwnd)
        self._stop_vk = int(stop_vk)
        self.my_elevated = self_elevated()
        self.target_elevated = process_elevated(window_pid(self.hwnd))
        if self.target_elevated and not self.my_elevated:
            raise InputError(
                "游戏以管理员权限运行，Windows 会拦掉本工具的按键；"
                "请关掉本工具，双击 run.bat（会自动申请管理员权限）再试"
            )
        # 清掉启动前按下的 F9，避免把上一次的按键当成这次停止请求。
        _user32.GetAsyncKeyState(self._stop_vk)
        width, height = client_size(self.hwnd)
        if width <= 0 or height <= 0:
            raise InputError("游戏窗口客户区为空；请把游戏窗口恢复出来")

    # ---- 状态 ----

    def client_size(self) -> tuple[int, int]:
        return client_size(self.hwnd)

    def is_foreground(self) -> bool:
        return is_foreground(self.hwnd)

    def stop_requested(self) -> bool:
        """F9 是否被按过（自上次查询以来）。"""
        return bool(_user32.GetAsyncKeyState(self._stop_vk) & 0x0001)

    requires_foreground = True

    def ensure_ready(self, timeout_s: float = 8.0) -> None:
        """前台模式下必须等到游戏窗口在前台。"""
        deadline = time.monotonic() + max(0.0, timeout_s)
        while True:
            if self.is_foreground():
                return
            if self.stop_requested():
                raise InputError("等待游戏窗口时收到 F9 停止")
            if time.monotonic() >= deadline:
                raise InputError("游戏窗口不在前台；请切到游戏窗口后重新开始")
            time.sleep(0.05)

    def _require_foreground(self) -> None:
        if not self.is_foreground():
            raise InputError("游戏窗口不在前台，已停止；请切回游戏后重新开始")

    # ---- 键盘 ----

    def _send_key(self, key: str, *, release: bool) -> None:
        if not release:
            self._require_foreground()
        vk, extended = _virtual_key(key)
        scan = int(_user32.MapVirtualKeyW(vk, 0))
        if scan:
            virtual, flags = 0, _KEYEVENTF_SCANCODE
            if extended:
                flags |= _KEYEVENTF_EXTENDEDKEY
        else:
            virtual, flags = vk, 0
        if release:
            flags |= _KEYEVENTF_KEYUP
        command = _INPUT(type=_INPUT_KEYBOARD,
                         union=_INPUTUNION(ki=_KEYBDINPUT(virtual, scan, flags, 0, 0)))
        _send(command)

    def key_down(self, key: str) -> None:
        self._send_key(key, release=False)

    def key_up(self, key: str) -> None:
        self._send_key(key, release=True)

    def press_key(self, key: str, hold_s: float = 0.08) -> None:
        self.key_down(key)
        try:
            time.sleep(max(0.0, hold_s))
        finally:
            self.key_up(key)

    # ---- 鼠标 ----

    def _absolute(self, x: int, y: int) -> tuple[int, int]:
        screen_x, screen_y = _client_to_screen(self.hwnd, x, y)
        left = _user32.GetSystemMetrics(_SM_XVIRTUALSCREEN)
        top = _user32.GetSystemMetrics(_SM_YVIRTUALSCREEN)
        width = max(_user32.GetSystemMetrics(_SM_CXVIRTUALSCREEN), 1)
        height = max(_user32.GetSystemMetrics(_SM_CYVIRTUALSCREEN), 1)
        return (
            int(round((screen_x - left) * 65535 / max(width - 1, 1))),
            int(round((screen_y - top) * 65535 / max(height - 1, 1))),
        )

    def _send_mouse(self, flags: int, *, dx: int = 0, dy: int = 0, data: int = 0) -> None:
        command = _INPUT(type=_INPUT_MOUSE,
                         union=_INPUTUNION(mi=_MOUSEINPUT(dx, dy, data & 0xFFFFFFFF, flags, 0, 0)))
        _send(command)

    def move(self, x: int, y: int, *, settle_s: float = 0.03) -> None:
        self._require_foreground()
        dx, dy = self._absolute(int(x), int(y))
        self._send_mouse(_MOUSEEVENTF_MOVE | _MOUSEEVENTF_ABSOLUTE | _MOUSEEVENTF_VIRTUALDESK,
                         dx=dx, dy=dy)
        if settle_s > 0:
            time.sleep(settle_s)

    def wheel(self, x: int, y: int, notches: int) -> None:
        """notches > 0 向上滚（列表往上翻），< 0 向下滚。"""
        if not notches:
            raise InputError("滚轮格数不能为 0")
        self.move(x, y)
        self._send_mouse(_MOUSEEVENTF_WHEEL, data=int(notches) * _WHEEL_DELTA)

    def click(self, x: int, y: int, button: str = "left", count: int = 1) -> None:
        if button == "left":
            down, up = _MOUSEEVENTF_LEFTDOWN, _MOUSEEVENTF_LEFTUP
        elif button == "right":
            down, up = _MOUSEEVENTF_RIGHTDOWN, _MOUSEEVENTF_RIGHTUP
        else:
            raise InputError(f"不支持的鼠标键：{button}")
        self.move(x, y)
        for _ in range(max(1, int(count))):
            self._send_mouse(down)
            time.sleep(0.03)
            self._send_mouse(up)
            time.sleep(0.06)

    def drag(self, x1: int, y1: int, x2: int, y2: int, *,
             button: str = "left", duration_s: float = 0.4, steps: int = 12) -> None:
        if button == "left":
            down, up = _MOUSEEVENTF_LEFTDOWN, _MOUSEEVENTF_LEFTUP
        elif button == "right":
            down, up = _MOUSEEVENTF_RIGHTDOWN, _MOUSEEVENTF_RIGHTUP
        else:
            raise InputError(f"不支持的鼠标键：{button}")
        self.move(x1, y1)
        self._send_mouse(down)
        try:
            steps = max(2, int(steps))
            pause = max(0.0, duration_s) / steps
            start_x, start_y = self._absolute(int(x1), int(y1))
            end_x, end_y = self._absolute(int(x2), int(y2))
            for index in range(1, steps + 1):
                ratio = index / steps
                self._send_mouse(
                    _MOUSEEVENTF_MOVE | _MOUSEEVENTF_ABSOLUTE | _MOUSEEVENTF_VIRTUALDESK,
                    dx=int(round(start_x + (end_x - start_x) * ratio)),
                    dy=int(round(start_y + (end_y - start_y) * ratio)),
                )
                time.sleep(pause)
        finally:
            self._send_mouse(up)


# ---------- 后台模式：用 PostMessage 把键鼠消息发进窗口，不需要它在前台 ----------

_WM_KEYDOWN = 0x0100
_WM_KEYUP = 0x0101
_WM_SYSKEYDOWN = 0x0104
_WM_SYSKEYUP = 0x0105
_WM_MOUSEMOVE = 0x0200
_WM_LBUTTONDOWN = 0x0201
_WM_LBUTTONUP = 0x0202
_WM_RBUTTONDOWN = 0x0204
_WM_RBUTTONUP = 0x0205
_WM_MOUSEWHEEL = 0x020A
_MK_LBUTTON = 0x0001
_MK_RBUTTON = 0x0002

_user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
_user32.PostMessageW.restype = wt.BOOL
_user32.IsWindow.argtypes = [wt.HWND]
_user32.IsWindow.restype = wt.BOOL


def pack_point(x: int, y: int) -> int:
    """窗口消息里的坐标：低 16 位 X、高 16 位 Y（有符号）。"""
    return ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)


def pack_key_lparam(scan: int, extended: bool, up: bool) -> int:
    """WM_KEYDOWN / WM_KEYUP 的 lParam：扫描码 + 扩展位 + 抬起标志。"""
    value = 1 | ((int(scan) & 0xFF) << 16)
    if extended:
        value |= 1 << 24
    if up:
        value |= (1 << 30) | (1 << 31)
    return value


def pack_wheel_wparam(notches: int) -> int:
    """WM_MOUSEWHEEL 的 wParam：高 16 位是滚动量（每格 120）。"""
    return ((int(notches) * _WHEEL_DELTA) & 0xFFFF) << 16


class MessageInput:
    """后台模式：不要求游戏窗口在前台，直接往窗口发键鼠消息。

    能不能生效取决于客户端认不认窗口消息：很多私服客户端能认，也有的只读底层输入、
    这时游戏会毫无反应——那就改回前台模式。窗口最小化时通常不生效。
    """

    name = "postMessage"
    sends_input = True
    requires_foreground = False

    def __init__(self, hwnd: int, *, stop_vk: int = _STOP_VK) -> None:
        self.hwnd = int(hwnd)
        self._stop_vk = int(stop_vk)
        self.my_elevated = self_elevated()
        self.target_elevated = process_elevated(window_pid(self.hwnd))
        if self.target_elevated and not self.my_elevated:
            raise InputError(
                "游戏以管理员权限运行，Windows 会拦掉本工具的输入；"
                "请关掉本工具，双击 run.bat（会自动申请管理员权限）再试"
            )
        if not _user32.IsWindow(self.hwnd):
            raise InputError("游戏窗口句柄无效；请点“刷新”重新选窗口")
        # 清掉启动前按下的 F9。
        _user32.GetAsyncKeyState(self._stop_vk)
        width, height = client_size(self.hwnd)
        if width <= 0 or height <= 0:
            raise InputError("游戏窗口客户区为空；请把游戏窗口恢复出来")

    # ---- 状态 ----

    def client_size(self) -> tuple[int, int]:
        return client_size(self.hwnd)

    def is_foreground(self) -> bool:
        return is_foreground(self.hwnd)

    def stop_requested(self) -> bool:
        return bool(_user32.GetAsyncKeyState(self._stop_vk) & 0x0001)

    def ensure_ready(self, timeout_s: float = 8.0) -> None:
        deadline = time.monotonic() + max(0.0, timeout_s)
        while True:
            if _user32.IsWindow(self.hwnd):
                return
            if self.stop_requested():
                raise InputError("等游戏窗口时收到 F9 停止")
            if time.monotonic() >= deadline:
                raise InputError("游戏窗口不见了；请重新刷新窗口列表")
            time.sleep(0.05)

    def _post(self, message: int, wparam: int = 0, lparam: int = 0) -> None:
        if not _user32.PostMessageW(self.hwnd, message, wparam, lparam):
            raise InputError("发不进游戏窗口（窗口可能已关闭，或权限不足）")

    # ---- 键盘 ----

    def press_key(self, key: str, hold_s: float = 0.08) -> None:
        vk, extended = _virtual_key(key)
        scan = int(_user32.MapVirtualKeyW(vk, 0)) or vk
        # 方向键等扩展键用 WM_KEYDOWN + lParam 里的扩展位表示，不是 WM_SYSKEYDOWN。
        self._post(_WM_KEYDOWN, vk, pack_key_lparam(scan, extended, False))
        try:
            time.sleep(max(0.02, hold_s))
        finally:
            self._post(_WM_KEYUP, vk, pack_key_lparam(scan, extended, True))

    # ---- 鼠标 ----

    def move(self, x: int, y: int, *, settle_s: float = 0.02) -> None:
        self._post(_WM_MOUSEMOVE, 0, pack_point(x, y))
        if settle_s > 0:
            time.sleep(settle_s)

    def wheel(self, x: int, y: int, notches: int) -> None:
        if not notches:
            raise InputError("滚轮格数不能为 0")
        self.move(x, y)
        screen_x, screen_y = _client_to_screen(self.hwnd, int(x), int(y))
        self._post(_WM_MOUSEWHEEL, pack_wheel_wparam(notches),
                   pack_point(screen_x, screen_y))

    def click(self, x: int, y: int, button: str = "left", count: int = 1) -> None:
        if button == "left":
            down, up = _WM_LBUTTONDOWN, _WM_LBUTTONUP
        elif button == "right":
            down, up = _WM_RBUTTONDOWN, _WM_RBUTTONUP
        else:
            raise InputError(f"不支持的鼠标键：{button}")
        self.move(x, y)
        for _ in range(max(1, int(count))):
            self._post(down, _MK_LBUTTON if button == "left" else _MK_RBUTTON,
                       pack_point(x, y))
            time.sleep(0.03)
            self._post(up, 0, pack_point(x, y))
            time.sleep(0.06)

    def drag(self, x1: int, y1: int, x2: int, y2: int, *,
             button: str = "left", duration_s: float = 0.4, steps: int = 12) -> None:
        if button == "left":
            down, up = _WM_LBUTTONDOWN, _WM_LBUTTONUP
        elif button == "right":
            down, up = _WM_RBUTTONDOWN, _WM_RBUTTONUP
        else:
            raise InputError(f"不支持的鼠标键：{button}")
        self.move(x1, y1)
        self._post(down, _MK_LBUTTON if button == "left" else _MK_RBUTTON,
                   pack_point(x1, y1))
        try:
            steps = max(2, int(steps))
            pause = max(0.0, duration_s) / steps
            for index in range(1, steps + 1):
                ratio = index / steps
                self._post(_WM_MOUSEMOVE, 0, pack_point(
                    int(round(x1 + (x2 - x1) * ratio)),
                    int(round(y1 + (y2 - y1) * ratio)),
                ))
                time.sleep(pause)
        finally:
            self._post(up, 0, pack_point(round(x2), round(y2)))
