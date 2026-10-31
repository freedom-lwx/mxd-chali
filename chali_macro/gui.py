"""查理中士兑换 · 按键精灵（Tkinter 单页界面）。

界面顺序就是使用顺序：选窗口 → 排动作 → 开始 / F9 结束。
"""

from __future__ import annotations

import ctypes
import os
import queue
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .runner import StepRunner
from .steps import (
    KIND_LABELS,
    KINDS,
    Macro,
    Step,
    StepError,
    load_macro,
    save_macro,
)
from .winapi import (
    InputError,
    Window,
    WindowsInput,
    cursor_client,
    is_foreground,
    list_windows,
    process_elevated,
    self_elevated,
    window_pid,
)

APP_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = APP_DIR / "config.json"
EXAMPLE_PATH = APP_DIR / "config.example.json"

_COMMON_KEYS = ("enter", "space", "esc", "tab", "a", "s", "d", "f", "z", "x", "c", "q", "e", "1")


def enable_dpi_awareness() -> None:
    """让坐标按真实像素算，避免系统缩放把取点结果算歪。"""
    if os.name != "nt":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("查理中士兑换 · 按键精灵")
        root.geometry("880x700")
        self.steps: list[Step] = []
        self.windows: list[Window] = []
        self.window: Window | None = None
        self.runner: StepRunner | None = None
        self._backend: WindowsInput | None = None
        self._logs: queue.Queue[str] = queue.Queue()
        self._pending: str | None = None
        self._point_size: tuple[int, int] | None = None
        self._build()
        self.refresh_windows(quiet=True)
        self._load_default_config()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<F9>", lambda _event: self.stop())
        self.root.after(150, self._poll)

    # ---------- 界面 ----------

    def _build(self) -> None:
        pad = {"padx": 8, "pady": 5}

        top = ttk.LabelFrame(self.root, text="1. 游戏窗口（运行时必须是它在前台）", padding=6)
        top.pack(fill="x", **pad)
        self.window_box = ttk.Combobox(top, width=48, state="readonly")
        self.window_box.grid(row=0, column=0, sticky="we")
        ttk.Button(top, text="刷新", width=6, command=self.refresh_windows).grid(row=0, column=1, padx=3)
        ttk.Button(top, text="用这个窗口", width=11,
                   command=self.use_window).grid(row=0, column=2)
        self.window_state = ttk.Label(top, text="尚未选择窗口")
        self.window_state.grid(row=1, column=0, columnspan=3, sticky="w", pady=(5, 0))
        top.columnconfigure(0, weight=1)

        mid = ttk.LabelFrame(self.root, text="2. 动作（一轮的先后顺序，坐标相对窗口客户区）", padding=6)
        mid.pack(fill="both", expand=True, **pad)
        bar = ttk.Frame(mid)
        bar.pack(fill="x")
        add = ttk.Menubutton(bar, text="添加动作 ▾")
        menu = tk.Menu(add, tearoff=False)
        for kind in KINDS:
            menu.add_command(label=KIND_LABELS[kind],
                             command=lambda k=kind: self.add_step(k))
        add["menu"] = menu
        add.pack(side="left")
        ttk.Button(bar, text="编辑", width=6, command=self.edit_step).pack(side="left", padx=3)
        ttk.Button(bar, text="上移", width=6,
                   command=lambda: self.move_step(-1)).pack(side="left")
        ttk.Button(bar, text="下移", width=6,
                   command=lambda: self.move_step(1)).pack(side="left", padx=3)
        ttk.Button(bar, text="删除", width=6, command=self.remove_step).pack(side="left")

        self.loops_var = tk.StringVar(value="1")
        self.interval_var = tk.StringVar(value="1.0")
        ttk.Label(bar, text="循环次数").pack(side="left", padx=(18, 3))
        ttk.Spinbox(bar, from_=0, to=9999, width=6,
                    textvariable=self.loops_var).pack(side="left")
        ttk.Label(bar, text="（0=一直循环）").pack(side="left", padx=(3, 12))
        ttk.Label(bar, text="每轮间隔(秒)").pack(side="left")
        ttk.Spinbox(bar, from_=0, to=60, increment=0.5, width=6,
                    textvariable=self.interval_var).pack(side="left", padx=(3, 0))

        tree_wrap = ttk.Frame(mid)
        tree_wrap.pack(fill="both", expand=True, pady=(6, 0))
        self.tree = ttk.Treeview(tree_wrap, columns=("index", "label", "delay"),
                                 show="headings", height=11)
        self.tree.heading("index", text="#")
        self.tree.heading("label", text="动作")
        self.tree.heading("delay", text="之后等待(秒)")
        self.tree.column("index", width=44, anchor="center", stretch=False)
        self.tree.column("label", width=520)
        self.tree.column("delay", width=110, anchor="center", stretch=False)
        bar_scroll = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=bar_scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        bar_scroll.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda _event: self.edit_step())

        run = ttk.Frame(self.root)
        run.pack(fill="x", **pad)
        self.start_button = ttk.Button(run, text="3. 开始（3 秒后启动）", command=self.start)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(run, text="结束 / F9", command=self.stop, state="disabled")
        self.stop_button.pack(side="left", padx=6)
        self.status = ttk.Label(run, text="未运行")
        self.status.pack(side="left", padx=12)
        ttk.Button(run, text="读取配置", command=self.load_config).pack(side="right")
        ttk.Button(run, text="保存配置", command=self.save_config).pack(side="right", padx=6)

        log_box = ttk.LabelFrame(self.root, text="运行日志", padding=6)
        log_box.pack(fill="both", expand=True, **pad)
        self.log_text = tk.Text(log_box, height=9, wrap="word", state="disabled")
        log_scroll = ttk.Scrollbar(log_box, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

    # ---------- 日志 ----------

    def log(self, text: str) -> None:
        self._logs.put(f"{time.strftime('%H:%M:%S')}  {text}")

    def _append_log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _poll(self) -> None:
        while True:
            try:
                text = self._logs.get_nowait()
            except queue.Empty:
                break
            self._append_log(text)
        if self.runner is not None and not self.runner.is_running():
            result = self.runner.result()
            self.runner = None
            self._set_running(False)
            if result is not None:
                self.status.configure(text="空闲 · 上次：" + result.reason)
        self._update_window_state()
        self.root.after(150, self._poll)

    # ---------- 窗口 ----------

    def refresh_windows(self, quiet: bool = False) -> None:
        self.windows = list_windows()
        values = [f"{item.title}   [pid {item.pid}]" for item in self.windows]
        self.window_box.configure(values=values)
        if self.window is not None:
            for index, item in enumerate(self.windows):
                if item.hwnd == self.window.hwnd:
                    self.window_box.current(index)
                    break
        if not quiet:
            self.log(f"刷新到 {len(self.windows)} 个窗口")

    def use_window(self) -> None:
        index = self.window_box.current()
        if index < 0 or index >= len(self.windows):
            messagebox.showwarning("还没有选窗口", "先在下拉框里选游戏窗口。", parent=self.root)
            return
        self.window = self.windows[index]
        width, height = self.window.client_size()
        self.log(f"使用窗口：{self.window.title}（客户区 {width}×{height}）")
        my_admin = self_elevated()
        game_admin = process_elevated(window_pid(self.window.hwnd))
        if game_admin and not my_admin:
            self.log(
                "注意：游戏是管理员权限，本工具不是；Windows 会拦掉按键。"
                "关掉本窗口，双击 run.bat（会自动提权）重新打开。"
            )
        else:
            self.log(f"权限：本工具{'管理员' if my_admin else '普通'}，"
                     f"游戏{'管理员' if game_admin else '普通'}")
        if self._point_size and tuple(self._point_size) != (width, height):
            self.log(
                f"注意：现有坐标是在客户区 {self._point_size[0]}×{self._point_size[1]} 时取的，"
                "窗口大小变了要重新取点。"
            )
        self._update_window_state()

    def _update_window_state(self) -> None:
        if self.window is None:
            self.window_state.configure(text="尚未选择窗口")
            return
        try:
            width, height = self.window.client_size()
            front = "前台" if is_foreground(self.window.hwnd) else "不在前台"
        except InputError as exc:
            self.window_state.configure(text=f"窗口已不可用：{exc}")
            return
        game_admin = process_elevated(window_pid(self.window.hwnd))
        admin = " · 需以管理员运行" if (game_admin and not self_elevated()) else ""
        self.window_state.configure(
            text=f"{self.window.title} · 客户区 {width}×{height} · {front}{admin}"
        )

    # ---------- 动作表 ----------

    def _refresh_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for index, step in enumerate(self.steps):
            self.tree.insert("", "end", iid=str(index),
                             values=(index + 1, step.label(), f"{step.delay_s:g}"))

    def _selected_index(self) -> int | None:
        selection = self.tree.selection()
        if not selection:
            return None
        try:
            return int(selection[0])
        except ValueError:
            return None

    def _default_point(self) -> tuple[int, int]:
        if self.window is not None:
            width, height = self.window.client_size()
            return width // 2, height // 2
        return 400, 300

    def add_step(self, kind: str) -> None:
        x, y = self._default_point()
        defaults = {
            "key": Step(kind="key", key="enter"),
            "wait": Step(kind="wait", seconds=0.6),
            "move": Step(kind="move", x=x, y=y),
            "wheel": Step(kind="wheel", x=x, y=y, notches=-3),
            "click": Step(kind="click", x=x, y=y),
            "drag": Step(kind="drag", x=x, y=max(y - 80, 0), x2=x, y2=y + 80),
        }
        dialog = StepDialog(self, defaults[kind])
        self.root.wait_window(dialog.top)
        if dialog.result is not None:
            self.steps.append(dialog.result)
            self._refresh_tree()
            self.tree.selection_set(str(len(self.steps) - 1))
            self.log(f"添加动作：{dialog.result.label()}")

    def edit_step(self) -> None:
        index = self._selected_index()
        if index is None:
            return
        dialog = StepDialog(self, self.steps[index])
        self.root.wait_window(dialog.top)
        if dialog.result is not None:
            self.steps[index] = dialog.result
            self._refresh_tree()
            self.tree.selection_set(str(index))
            self.log(f"修改动作：{dialog.result.label()}")

    def move_step(self, delta: int) -> None:
        index = self._selected_index()
        if index is None:
            return
        target = index + delta
        if not 0 <= target < len(self.steps):
            return
        self.steps[index], self.steps[target] = self.steps[target], self.steps[index]
        self._refresh_tree()
        self.tree.selection_set(str(target))

    def remove_step(self) -> None:
        index = self._selected_index()
        if index is None:
            return
        removed = self.steps.pop(index)
        self._refresh_tree()
        self.log(f"删除动作：{removed.label()}")

    # ---------- 配置 ----------

    def _load_default_config(self) -> None:
        if CONFIG_PATH.exists():
            self._apply_config(CONFIG_PATH, quiet=False)
        elif EXAMPLE_PATH.exists():
            self._apply_config(EXAMPLE_PATH, quiet=False)
            self.log("以上是示例动作：按键和坐标都还没校准，先按你自己的操作改准再开始。")

    def _apply_config(self, path: Path, quiet: bool = False) -> None:
        try:
            macro = load_macro(path)
        except StepError as exc:
            messagebox.showerror("配置读取失败", str(exc), parent=self.root)
            return
        self.steps = list(macro.steps)
        self.loops_var.set(str(macro.loops))
        self.interval_var.set(f"{macro.interval_s:g}")
        self._point_size = tuple(macro.client_size) if macro.client_size else None
        self._refresh_tree()
        if not quiet:
            self.log(f"已载入配置：{path.name}（{len(macro.steps)} 个动作）")

    def load_config(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root, title="选择配置文件", initialdir=str(APP_DIR),
            filetypes=[("JSON 配置", "*.json"), ("所有文件", "*.*")],
        )
        if path:
            self._apply_config(Path(path))

    def _macro(self) -> Macro:
        try:
            loops = int(str(self.loops_var.get()).strip() or 0)
        except ValueError as exc:
            raise StepError("循环次数需要是整数") from exc
        try:
            interval = float(str(self.interval_var.get()).strip() or 0)
        except ValueError as exc:
            raise StepError("每轮间隔需要是数字") from exc
        return Macro(
            steps=tuple(self.steps),
            loops=loops,
            interval_s=interval,
            client_size=self._point_size,
        ).validated()

    def save_config(self) -> None:
        try:
            macro = self._macro()
            path = save_macro(macro, CONFIG_PATH)
        except (StepError, OSError) as exc:
            messagebox.showerror("保存失败", str(exc), parent=self.root)
            return
        self.log(f"已保存配置：{path.name}")

    # ---------- 运行 ----------

    def start(self) -> None:
        if self.runner is not None:
            return
        if self.window is None:
            messagebox.showwarning("还没有选窗口", "先在上方选游戏窗口并点“用这个窗口”。",
                                   parent=self.root)
            return
        if not self.steps:
            messagebox.showwarning("还没有动作", "先添加兑换要按的键和滚轮动作。",
                                   parent=self.root)
            return
        try:
            macro = self._macro()
        except StepError as exc:
            messagebox.showerror("动作有问题", str(exc), parent=self.root)
            return
        try:
            self._backend = WindowsInput(self.window.hwnd)
        except InputError as exc:
            messagebox.showerror("无法向游戏窗口发送输入", str(exc), parent=self.root)
            return
        size = self._backend.client_size()
        if macro.client_size and tuple(macro.client_size) != tuple(size):
            self.log(
                f"注意：坐标是在客户区 {macro.client_size[0]}×{macro.client_size[1]} 时取的，"
                f"现在是 {size[0]}×{size[1]}；可能需要重新取点。"
            )
        self._set_running(True)
        self._countdown(3, macro)

    def _countdown(self, remaining: int, macro: Macro) -> None:
        if remaining <= 0:
            self._launch(macro)
            return
        self.status.configure(text=f"{remaining} 秒后开始，请切到游戏窗口…")
        self._pending = self.root.after(1000, lambda: self._countdown(remaining - 1, macro))

    def _launch(self, macro: Macro) -> None:
        self._pending = None
        if self._backend is None:
            self._set_running(False)
            return
        self.runner = StepRunner(macro, self._backend, log=self.log)
        self.status.configure(text="运行中")
        self.runner.start()

    def stop(self) -> None:
        if self._pending is not None:
            self.root.after_cancel(self._pending)
            self._pending = None
            self._set_running(False)
            self.log("已取消启动")
            self.status.configure(text="未运行")
            return
        if self.runner is not None:
            self.runner.stop()
            self.log("已请求结束，等当前动作做完…")

    def _set_running(self, running: bool) -> None:
        self.start_button.configure(state="disabled" if running else "normal")
        self.stop_button.configure(state="normal" if running else "disabled")

    def close(self) -> None:
        if self._pending is not None:
            self.root.after_cancel(self._pending)
            self._pending = None
        if self.runner is not None:
            self.runner.stop()
            self.runner.join(2.0)
        self.root.destroy()


class StepDialog:
    """单个动作的编辑框；取点按钮会把鼠标当前位置换算成客户区坐标。"""

    def __init__(self, app: App, step: Step) -> None:
        self.app = app
        self.step = step
        self.result: Step | None = None
        self.vars: dict[str, tk.StringVar] = {}
        self.top = tk.Toplevel(app.root)
        self.top.title(KIND_LABELS[step.kind] + " 设置")
        self.top.transient(app.root)
        self.top.resizable(False, False)
        self.form = ttk.Frame(self.top, padding=10)
        self.form.pack(fill="both", expand=True)
        self._build()
        self.pick_label = ttk.Label(self.top, text="", foreground="#555")
        self.pick_label.pack(anchor="w", padx=10)
        actions = ttk.Frame(self.top, padding=(10, 6))
        actions.pack(fill="x")
        ttk.Button(actions, text="取消", command=self.top.destroy).pack(side="right")
        ttk.Button(actions, text="确定", command=self._confirm).pack(side="right", padx=6)
        self.top.grab_set()

    # --- 表单 ---

    def _var(self, name: str, value) -> tk.StringVar:
        var = tk.StringVar(value=str(value))
        self.vars[name] = var
        return var

    def _row(self, row: int, text: str, widget) -> None:
        ttk.Label(self.form, text=text).grid(row=row, column=0, sticky="e", pady=3)
        widget.grid(row=row, column=1, sticky="we", pady=3)

    def _spin(self, row: int, text: str, name: str, value, *, frm=None, to=None,
              increment=None, width=10) -> None:
        kwargs = {}
        if frm is not None:
            kwargs["from_"] = frm
        if to is not None:
            kwargs["to"] = to
        if increment is not None:
            kwargs["increment"] = increment
        self._row(row, text, ttk.Spinbox(self.form, width=width, textvariable=self._var(name, value),
                                         **kwargs))

    def _coords(self, row: int, step: Step) -> int:
        line = ttk.Frame(self.form)
        self._var("x", step.x)
        self._var("y", step.y)
        ttk.Label(line, text="X").pack(side="left")
        ttk.Spinbox(line, from_=0, to=10000, width=7, textvariable=self.vars["x"]).pack(side="left", padx=(2, 8))
        ttk.Label(line, text="Y").pack(side="left")
        ttk.Spinbox(line, from_=0, to=10000, width=7, textvariable=self.vars["y"]).pack(side="left", padx=(2, 8))
        ttk.Button(line, text="取点", width=6,
                   command=lambda: self._pick(("x", "y"))).pack(side="left")
        self._row(row, "位置（客户区）", line)
        return row + 1

    def _build(self) -> None:
        step = self.step
        kind = step.kind
        row = 0
        if kind == "key":
            self._row(row, "按键", ttk.Combobox(self.form, width=12, values=_COMMON_KEYS,
                                                textvariable=self._var("key", step.key)))
            row += 1
            self._spin(row, "按住(秒)", "hold_s", f"{step.hold_s:g}", frm=0.02, to=2.0,
                       increment=0.02)
            row += 1
        elif kind == "wait":
            self._spin(row, "等待(秒)", "seconds", f"{step.seconds:g}", frm=0.1, to=300,
                       increment=0.1)
            row += 1
        elif kind == "move":
            row = self._coords(row, step)
        elif kind == "wheel":
            row = self._coords(row, step)
            self._spin(row, "格数（正=上滚，负=下滚）", "notches", step.notches,
                       frm=-50, to=50, increment=1)
            row += 1
        elif kind == "click":
            row = self._coords(row, step)
            self._row(row, "鼠标键", ttk.Combobox(self.form, width=8, state="readonly",
                                                  values=("left", "right"),
                                                  textvariable=self._var("button", step.button)))
            row += 1
            self._spin(row, "点击次数", "count", step.count, frm=1, to=20, increment=1)
            row += 1
        elif kind == "drag":
            row = self._coords(row, step)
            line = ttk.Frame(self.form)
            self._var("x2", step.x2)
            self._var("y2", step.y2)
            ttk.Label(line, text="X").pack(side="left")
            ttk.Spinbox(line, from_=0, to=10000, width=7, textvariable=self.vars["x2"]).pack(side="left", padx=(2, 8))
            ttk.Label(line, text="Y").pack(side="left")
            ttk.Spinbox(line, from_=0, to=10000, width=7, textvariable=self.vars["y2"]).pack(side="left", padx=(2, 8))
            ttk.Button(line, text="取终点", width=7,
                       command=lambda: self._pick(("x2", "y2"))).pack(side="left")
            self._row(row, "终点（客户区）", line)
            row += 1
            self._row(row, "鼠标键", ttk.Combobox(self.form, width=8, state="readonly",
                                                  values=("left", "right"),
                                                  textvariable=self._var("button", step.button)))
            row += 1
            self._spin(row, "拖动时长(秒)", "duration_s", f"{step.duration_s:g}",
                       frm=0.05, to=5.0, increment=0.05)
            row += 1
        self._spin(row, "之后等待(秒)", "delay_s", f"{step.delay_s:g}", frm=0, to=30,
                   increment=0.05)
        self.form.columnconfigure(1, weight=1)

    # --- 取点 ---

    def _pick(self, targets: tuple[str, ...]) -> None:
        if self.app.window is None:
            self.pick_label.configure(text="主界面还没选游戏窗口，先点“用这个窗口”。")
            return
        self._countdown(targets, 3)

    def _countdown(self, targets: tuple[str, ...], remaining: int) -> None:
        if remaining <= 0:
            point = cursor_client(self.app.window.hwnd)
            if point is None:
                self.pick_label.configure(text="这次鼠标不在游戏窗口内，没取到点；再点一次“取点”。")
                return
            x, y = point
            if targets == ("x", "y"):
                self.vars["x"].set(str(x))
                self.vars["y"].set(str(y))
            else:
                self.vars["x2"].set(str(x))
                self.vars["y2"].set(str(y))
            self.app._point_size = tuple(self.app.window.client_size())
            self.pick_label.configure(text=f"已取点 ({x}, {y})")
            return
        self.pick_label.configure(text=f"把鼠标移到游戏里的目标位置，{remaining} 秒后读取…")
        self.top.after(1000, lambda: self._countdown(targets, remaining - 1))

    # --- 提交 ---

    def _num(self, name: str) -> float:
        text = self.vars[name].get().strip()
        try:
            return float(text)
        except ValueError as exc:
            raise StepError(f"{name} 需要数字") from exc

    def _int(self, name: str) -> int:
        value = self._num(name)
        if value != int(value):
            raise StepError(f"{name} 需要整数")
        return int(value)

    def _confirm(self) -> None:
        step = self.step
        kind = step.kind
        try:
            data: dict = {"kind": kind, "delay_s": self._num("delay_s")}
            if kind == "key":
                data.update(key=self.vars["key"].get(), hold_s=self._num("hold_s"))
            elif kind == "wait":
                data.update(seconds=self._num("seconds"))
            elif kind in ("move", "wheel", "click", "drag"):
                data.update(x=self._int("x"), y=self._int("y"))
                if kind in ("click", "drag"):
                    data.update(button=self.vars["button"].get())
                if kind == "wheel":
                    data.update(notches=self._int("notches"))
                if kind == "click":
                    data.update(count=self._int("count"))
                if kind == "drag":
                    data.update(x2=self._int("x2"), y2=self._int("y2"),
                                duration_s=self._num("duration_s"))
            self.result = Step(**data).validated()
        except StepError as exc:
            messagebox.showerror("这个动作有问题", str(exc), parent=self.top)
            return
        self.top.destroy()


def main() -> int:
    enable_dpi_awareness()
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    App(root)
    root.mainloop()
    return 0
