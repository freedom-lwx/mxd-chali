import time
import unittest

from chali_macro.runner import StepRunner
from chali_macro.steps import Macro, Step


class FakeBackend:
    """记录被调用过的动作；不碰真实键盘鼠标。"""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.stop_flag = False
        self.foreground_error: str | None = None

    def ensure_ready(self, timeout_s: float) -> None:
        if self.foreground_error:
            raise RuntimeError(self.foreground_error)

    def stop_requested(self) -> bool:
        return self.stop_flag

    def press_key(self, key: str, hold_s: float) -> None:
        self.calls.append(("key", key))

    def move(self, x: int, y: int) -> None:
        self.calls.append(("move", x, y))

    def wheel(self, x: int, y: int, notches: int) -> None:
        self.calls.append(("wheel", x, y, notches))

    def click(self, x: int, y: int, button: str, count: int) -> None:
        self.calls.append(("click", x, y, button, count))

    def drag(self, x1: int, y1: int, x2: int, y2: int, button: str, duration_s: float) -> None:
        self.calls.append(("drag", x1, y1, x2, y2))


def make_macro(loops: int = 2) -> Macro:
    return Macro(
        steps=(
            Step(kind="key", key="space", delay_s=0),
            Step(kind="wheel", x=480, y=300, notches=-4, delay_s=0),
            Step(kind="key", key="enter", delay_s=0),
        ),
        loops=loops,
        interval_s=0,
    ).validated()


def run_to_end(runner: StepRunner, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while runner.is_running() and time.monotonic() < deadline:
        time.sleep(0.01)


class RunnerTest(unittest.TestCase):
    def test_runs_all_loops_in_order(self) -> None:
        backend = FakeBackend()
        logs: list[str] = []
        runner = StepRunner(make_macro(loops=2), backend, log=logs.append)
        runner.start()
        run_to_end(runner)
        runner.join(1.0)

        self.assertEqual(
            backend.calls,
            [("key", "space"), ("wheel", 480, 300, -4), ("key", "enter")] * 2,
        )
        result = runner.result()
        self.assertIsNotNone(result)
        self.assertTrue(result.ok)
        self.assertEqual(result.cycles, 2)
        self.assertIn("完成 2 轮", result.reason)
        self.assertTrue(any("第 1 轮完成" in line for line in logs))

    def test_repeat_runs_step_several_times(self) -> None:
        backend = FakeBackend()
        macro = Macro(
            steps=(
                Step(kind="key", key="y", repeat=3, gap_s=0, delay_s=0),
                Step(kind="wheel", x=480, y=300, notches=-2, delay_s=0),
                Step(kind="key", key="enter", repeat=2, gap_s=0, delay_s=0),
            ),
            loops=1,
            interval_s=0,
        ).validated()
        runner = StepRunner(macro, backend)
        runner.start()
        run_to_end(runner)
        runner.join(1.0)
        self.assertEqual(
            backend.calls,
            [("key", "y")] * 3 + [("wheel", 480, 300, -2)] + [("key", "enter")] * 2,
        )

    def test_f9_request_stops_cleanly(self) -> None:
        backend = FakeBackend()
        macro = Macro(steps=(Step(kind="key", key="space", delay_s=0.02),), loops=0,
                      interval_s=0.02).validated()
        runner = StepRunner(macro, backend)
        runner.start()
        time.sleep(0.1)
        backend.stop_flag = True
        run_to_end(runner)
        runner.join(1.0)

        result = runner.result()
        self.assertIsNotNone(result)
        self.assertFalse(result.ok)
        self.assertIn("已停止", result.reason)
        self.assertGreaterEqual(result.cycles, 1)

    def test_explicit_stop_cancels_loop(self) -> None:
        backend = FakeBackend()
        macro = Macro(steps=(Step(kind="key", key="space", delay_s=0.05),), loops=0,
                      interval_s=0.05).validated()
        runner = StepRunner(macro, backend)
        runner.start()
        time.sleep(0.12)
        runner.stop()
        run_to_end(runner)
        runner.join(1.0)
        self.assertFalse(runner.result().ok)
        self.assertIn("已停止", runner.result().reason)

    def test_foreground_problem_is_reported(self) -> None:
        backend = FakeBackend()
        backend.foreground_error = "游戏窗口不在前台"
        runner = StepRunner(make_macro(), backend)
        runner.start()
        run_to_end(runner)
        runner.join(1.0)

        result = runner.result()
        self.assertFalse(result.ok)
        self.assertIn("不在前台", result.reason)
        self.assertEqual(backend.calls, [])

    def test_backend_error_mid_sequence_is_reported(self) -> None:
        class Broken(FakeBackend):
            def wheel(self, x, y, notches):
                raise RuntimeError("没接上滚动条")

        backend = Broken()
        runner = StepRunner(make_macro(loops=1), backend)
        runner.start()
        run_to_end(runner)
        runner.join(1.0)

        result = runner.result()
        self.assertFalse(result.ok)
        self.assertIn("没接上滚动条", result.reason)


if __name__ == "__main__":
    unittest.main()
