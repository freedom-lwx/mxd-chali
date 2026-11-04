"""循环执行兑换动作。不依赖 Windows：后端由调用方注入，方便单元测试。"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from .steps import Macro, Step


class RunnerError(RuntimeError):
    """动作执行中出现不可继续的错误。"""


@dataclass(frozen=True)
class RunResult:
    cycles: int
    reason: str
    ok: bool


class StepRunner:
    """后台线程按顺序执行一轮动作，再按循环设置重复。

    停止条件：调用 ``stop()``、后端报告停止键（游戏里按 F9）、出错、跑满轮数。
    """

    def __init__(self, macro: Macro, backend, *, log=None,
                 ready_timeout_s: float = 8.0, poll_s: float = 0.02) -> None:
        self.macro = macro.validated()
        self._backend = backend
        self._log = log or (lambda text: None)
        self._ready_timeout_s = ready_timeout_s
        self._poll_s = max(0.005, float(poll_s))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._result: RunResult | None = None
        self._cycles = 0

    # ---- 生命周期 ----

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            raise RunnerError("已经在运行")
        self._thread = threading.Thread(target=self._run, name="chali-macro", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def result(self) -> RunResult | None:
        return self._result

    # ---- 内部 ----

    def _should_stop(self) -> bool:
        if self._stop.is_set():
            return True
        try:
            return bool(self._backend.stop_requested())
        except Exception:  # 后端读停止键失败不应让线程崩溃
            return False

    def _sleep(self, seconds: float) -> bool:
        """可中断等待；被要求停止时返回 False。"""
        deadline = time.monotonic() + max(0.0, seconds)
        while True:
            if self._should_stop():
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True
            time.sleep(min(self._poll_s, remaining))

    def _apply(self, step: Step) -> None:
        """按“次数”重复执行；每两次之间等 gap_s，全部做完才进下一步。"""
        for index in range(step.repeat):
            self._apply_once(step)
            if index + 1 < step.repeat and not self._sleep(step.gap_s):
                raise RunnerError("停止")

    def _apply_once(self, step: Step) -> None:
        backend = self._backend
        kind = step.kind
        if kind == "key":
            backend.press_key(step.key, step.hold_s)
        elif kind == "wait":
            if not self._sleep(step.seconds):
                raise RunnerError("停止")
        elif kind == "move":
            backend.move(step.x, step.y)
        elif kind == "wheel":
            backend.wheel(step.x, step.y, step.notches)
        elif kind == "click":
            backend.click(step.x, step.y, step.button, 1)
        elif kind == "drag":
            backend.drag(step.x, step.y, step.x2, step.y2, step.button, step.duration_s)
        else:  # pragma: no cover - 校验已挡住
            raise RunnerError(f"未知动作类型：{kind}")

    def _run(self) -> None:
        loop_count = self.macro.loops
        total = len(self.macro.steps)
        try:
            if getattr(self._backend, "requires_foreground", True):
                self._log("等待游戏窗口切到前台…")
            else:
                self._log("后台模式：不用切前台，直接往游戏窗口发消息")
            self._backend.ensure_ready(self._ready_timeout_s)
            self._log(
                f"开始：{total} 个动作，"
                + ("一直循环" if loop_count == 0 else f"循环 {loop_count} 轮")
                + "；游戏中按 F9 可停止"
            )
            while True:
                if self._should_stop():
                    self._finish(RunResult(self._cycles, "已停止（F9 或点结束）", False))
                    return
                self._cycles += 1
                for index, step in enumerate(self.macro.steps, 1):
                    if self._should_stop():
                        self._finish(RunResult(self._cycles, "已停止（F9 或点结束）", False))
                        return
                    self._apply(step)
                    self._log(f"第 {self._cycles} 轮 · {index}/{total} {step.label()}")
                    if not self._sleep(step.delay_s):
                        self._finish(RunResult(self._cycles, "已停止（F9 或点结束）", False))
                        return
                self._log(f"第 {self._cycles} 轮完成")
                if loop_count and self._cycles >= loop_count:
                    self._finish(RunResult(self._cycles, f"完成 {self._cycles} 轮", True))
                    return
                if not self._sleep(self.macro.interval_s):
                    self._finish(RunResult(self._cycles, "已停止（F9 或点结束）", False))
                    return
        except RunnerError as exc:
            if str(exc) == "停止":
                self._finish(RunResult(self._cycles, "已停止（F9 或点结束）", False))
            else:
                self._finish(RunResult(self._cycles, f"出错：{exc}", False))
        except Exception as exc:  # 后端抛出的任何输入错误都转成可读原因
            self._finish(RunResult(self._cycles, f"出错：{exc}", False))

    def _finish(self, result: RunResult) -> None:
        self._result = result
        self._log(result.reason)
