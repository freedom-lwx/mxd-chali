"""本机输入自检：开一个小窗口当靶子，验证键盘、滚轮、点击真的送到了目标窗口。

不碰游戏：每次发送前都会校验目标窗口是否在前台，不在前台直接报错而不是乱发。
用法：python scripts/selftest_input.py

两个阶段：
  1. 坐标换算（不发任何按键，随时可跑）
  2. 实际输入（会把自检窗口切到前台，结束时把前台还给原来的窗口）
"""

from __future__ import annotations

import ctypes
import os
import sys
import time
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if os.name != "nt":
    print("只在 Windows 上自检")
    raise SystemExit(1)

from chali_macro.gui import enable_dpi_awareness  # noqa: E402
from chali_macro.winapi import (  # noqa: E402
    InputError,
    WindowsInput,
    list_windows,
    process_elevated,
    self_elevated,
    window_title,
)

TITLE = "chali 输入自检（跑完自动关）"
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.GetForegroundWindow.restype = ctypes.c_void_p
_user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_user32.GetWindowThreadProcessId.restype = ctypes.c_ulong


def _foreground() -> int:
    return int(_user32.GetForegroundWindow() or 0)


def _pid_of(hwnd: int) -> int:
    pid = ctypes.c_ulong(0)
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def force_foreground(hwnd: int) -> bool:
    """尽量把窗口切到前台（Windows 默认禁止后台程序抢焦点，这里用附加输入队列绕）。"""
    _user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    _user32.BringWindowToTop(hwnd)
    if _foreground() == hwnd:
        return True
    target_thread = _user32.GetWindowThreadProcessId(_foreground(), None)
    current_thread = ctypes.windll.kernel32.GetCurrentThreadId()
    attached = bool(_user32.AttachThreadInput(current_thread, target_thread, True))
    try:
        _user32.SetForegroundWindow(hwnd)
        _user32.BringWindowToTop(hwnd)
    finally:
        if attached:
            _user32.AttachThreadInput(current_thread, target_thread, False)
    return _foreground() == hwnd


def wait_foreground(backend: WindowsInput, seconds: float) -> bool:
    """先自己抢，抢不到就等用户点一下自检窗口。"""
    if backend.is_foreground():
        return True
    force_foreground(backend.hwnd)
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if backend.is_foreground():
            return True
        time.sleep(0.05)
    return False


def main() -> int:
    enable_dpi_awareness()
    previous = _foreground()
    my_admin = self_elevated()
    print(f"本工具权限：{'管理员' if my_admin else '普通'}；前台窗口：{window_title(previous)!r}"
          f"（{'管理员' if process_elevated(_pid_of(previous)) else '普通/未知'}）")
    root = tk.Tk()
    root.title(TITLE)
    root.geometry("380x260+140+140")
    text = tk.Text(root, height=10)
    text.pack(fill="both", expand=True)
    text.insert("end", "\n".join(f"第 {index} 行：滚轮和点击的靶子" for index in range(1, 201)))
    hits = {"key": 0, "arrow": 0, "click": 0}
    root.bind("<a>", lambda _event: hits.__setitem__("key", hits["key"] + 1))
    root.bind("<Up>", lambda _event: hits.__setitem__("arrow", hits["arrow"] + 1))
    text.bind("<Button-1>", lambda _event: hits.__setitem__("click", hits["click"] + 1))
    root.update()

    windows = [item for item in list_windows() if item.title == TITLE]
    if not windows:
        print("失败：找不到自检窗口")
        root.destroy()
        return 1
    window = windows[0]
    backend = WindowsInput(window.hwnd)
    width, height = backend.client_size()
    center = (width // 2, height // 2)
    failures = 0

    # ---- 阶段 1：坐标换算，不发任何输入 ----
    try:
        left_top = backend._absolute(0, 0)
        right_bottom = backend._absolute(width - 1, height - 1)
        inside = all(0 <= value <= 65535 for value in left_top + right_bottom)
        ordered = left_top[0] < right_bottom[0] and left_top[1] < right_bottom[1]
        if inside and ordered:
            print(f"坐标换算：通过（{width}×{height} 客户区，"
                  f"左上 {left_top} → 右下 {right_bottom}）")
        else:
            print(f"坐标换算：失败（左上 {left_top} → 右下 {right_bottom}）")
            failures += 1
    except InputError as exc:
        print(f"坐标换算：失败（{exc}）")
        failures += 1

    # ---- 阶段 2：实际输入，需要自检窗口在前台 ----
    if not wait_foreground(backend, 15.0):
        print("实际输入：跳过——自检窗口没拿到前台。")
        print(f"  当前前台是：{window_title(_foreground())!r}")
        if not my_admin:
            print("  本工具是普通权限；如果前台/游戏窗口是管理员权限，"
                  "Windows 不允许抢焦点。请用管理员权限重跑本自检。")
        print("  也可以手动点一下“chali 输入自检”窗口再重新运行。")
        root.destroy()
        return 1 if failures else 2

    results: list[tuple[str, bool, str]] = []
    before = text.yview()
    backend.wheel(center[0], center[1], -4)
    root.update()
    results.append(("滚轮", text.yview() > before, f"{before} → {text.yview()}"))

    backend.press_key("a", 0.06)
    root.update()
    results.append(("键盘", hits["key"] >= 1, f"收到 {hits['key']} 次"))

    backend.press_key("up", 0.06)
    root.update()
    results.append(("方向键", hits["arrow"] >= 1, f"收到 {hits['arrow']} 次"))

    backend.click(center[0], center[1], "left", 1)
    root.update()
    results.append(("点击", hits["click"] >= 1, f"收到 {hits['click']} 次"))

    for name, passed, detail in results:
        print(f"{name}：{'通过' if passed else '失败'}（{detail}）")
        if not passed:
            failures += 1

    root.destroy()
    if previous and previous != window.hwnd:
        _user32.SetForegroundWindow(previous)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
