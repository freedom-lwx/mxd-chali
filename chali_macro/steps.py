"""兑换动作序列的模型：步骤校验、显示文案、JSON 读写。

本模块不依赖 Windows，方便在任意机器上跑单元测试。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, replace
from pathlib import Path

KINDS = ("key", "wait", "move", "wheel", "click", "drag")

KIND_LABELS = {
    "key": "按键",
    "wait": "等待",
    "move": "移动鼠标",
    "wheel": "滚轮",
    "click": "点击",
    "drag": "拖动",
}

_NAMED_KEYS = (
    "space", "enter", "esc", "tab", "home", "end", "pageup", "pagedown",
    "insert", "delete",
) + tuple(f"f{i}" for i in range(1, 25)) + tuple(f"numpad{i}" for i in range(10))

MAX_COORD = 10000
MAX_HOLD_S = 2.0
MAX_SECONDS = 300.0
MAX_DELAY_S = 30.0
MAX_DRAG_S = 5.0


class StepError(ValueError):
    """步骤或整个动作序列不合法。"""


def _number(value, name: str, *, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise StepError(f"{name} 需要是数字")
    if not low <= float(value) <= high:
        raise StepError(f"{name} 需要在 {low}～{high} 之间")
    return float(value)


def _integer(value, name: str, *, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StepError(f"{name} 需要是整数")
    if not low <= value <= high:
        raise StepError(f"{name} 需要在 {low}～{high} 之间")
    return value


def normalize_key_name(key: str) -> str:
    """把小写/别名统一成标准键名；不允许 F9（F9 是停止键）。"""
    if not isinstance(key, str) or not key.strip():
        raise StepError("按键名不能为空")
    token = key.strip().lower()
    if token in ("回车", "确认", "确定"):
        token = "enter"
    elif token == "空格":
        token = "space"
    elif token in ("esc", "escape"):
        token = "esc"
    if len(token) == 1 and token.isascii() and token.isalnum():
        return token
    if token == "f9":
        raise StepError("F9 是停止键，不能作为动作键")
    if token in _NAMED_KEYS:
        return token
    raise StepError(f"不支持的按键名：{key}")


@dataclass(frozen=True)
class Step:
    """一个动作。不同 kind 只用到其中一部分字段，其余保持默认。"""

    kind: str
    key: str = "enter"
    hold_s: float = 0.08
    seconds: float = 0.5
    x: int = 0
    y: int = 0
    x2: int = 0
    y2: int = 0
    notches: int = -1
    button: str = "left"
    count: int = 1
    duration_s: float = 0.4
    delay_s: float = 0.3

    def validated(self) -> "Step":
        if not isinstance(self.kind, str) or self.kind not in KINDS:
            raise StepError(f"未知动作类型：{self.kind!r}；可选 {', '.join(KINDS)}")
        delay = _number(self.delay_s, "执行后间隔(秒)", low=0.0, high=MAX_DELAY_S)
        kind = self.kind
        if kind == "key":
            return replace(
                self,
                key=normalize_key_name(self.key),
                hold_s=_number(self.hold_s, "按住(秒)", low=0.02, high=MAX_HOLD_S),
                delay_s=delay,
            )
        if kind == "wait":
            return replace(self, seconds=_number(self.seconds, "等待(秒)", low=0.01,
                                                high=MAX_SECONDS), delay_s=delay)
        coords = dict(
            x=_integer(self.x, "X", low=0, high=MAX_COORD),
            y=_integer(self.y, "Y", low=0, high=MAX_COORD),
        )
        if kind == "move":
            return replace(self, delay_s=delay, **coords)
        if kind == "wheel":
            notches = _integer(self.notches, "滚轮格数", low=-50, high=50)
            if notches == 0:
                raise StepError("滚轮格数不能为 0；向下滚填负数")
            return replace(self, notches=notches, delay_s=delay, **coords)
        if kind == "click":
            if self.button not in ("left", "right"):
                raise StepError("鼠标键只能是 left 或 right")
            return replace(
                self,
                count=_integer(self.count, "点击次数", low=1, high=20),
                delay_s=delay,
                **coords,
            )
        if kind == "drag":
            if self.button not in ("left", "right"):
                raise StepError("鼠标键只能是 left 或 right")
            return replace(
                self,
                x2=_integer(self.x2, "终点 X", low=0, high=MAX_COORD),
                y2=_integer(self.y2, "终点 Y", low=0, high=MAX_COORD),
                duration_s=_number(self.duration_s, "拖动时长(秒)", low=0.05, high=MAX_DRAG_S),
                delay_s=delay,
                **coords,
            )
        raise StepError(f"未知动作类型：{kind}")  # pragma: no cover - KINDS 已覆盖

    def label(self) -> str:
        """给界面表格用的一句话说明。"""
        kind = self.kind
        if kind == "key":
            return f"按 {self.key}（{self.hold_s:.2f}s）"
        if kind == "wait":
            return f"等 {self.seconds:.2f}s"
        if kind == "move":
            return f"移到 ({self.x}, {self.y})"
        if kind == "wheel":
            direction = "上" if self.notches > 0 else "下"
            return f"滚轮 {direction} {abs(self.notches)} 格 @({self.x}, {self.y})"
        if kind == "click":
            side = "左" if self.button == "left" else "右"
            return f"{side}键 {self.count} 次 @({self.x}, {self.y})"
        if kind == "drag":
            side = "左" if self.button == "left" else "右"
            return f"{side}键拖 ({self.x}, {self.y})→({self.x2}, {self.y2}) {self.duration_s:.2f}s"
        return kind

    def to_dict(self) -> dict:
        data = {"kind": self.kind}
        if self.kind == "key":
            data.update(key=self.key, hold_s=self.hold_s)
        elif self.kind == "wait":
            data.update(seconds=self.seconds)
        elif self.kind in ("move", "wheel", "click"):
            data.update(x=self.x, y=self.y)
            if self.kind == "wheel":
                data.update(notches=self.notches)
            if self.kind == "click":
                data.update(button=self.button, count=self.count)
        elif self.kind == "drag":
            data.update(x=self.x, y=self.y, x2=self.x2, y2=self.y2,
                        button=self.button, duration_s=self.duration_s)
        data["delay_s"] = self.delay_s
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Step":
        if not isinstance(data, dict):
            raise StepError("每个步骤需要是一个对象")
        kind = data.get("kind")
        if kind not in KINDS:
            raise StepError(f"未知动作类型：{kind!r}")
        allowed = {
            "kind", "key", "hold_s", "seconds", "x", "y", "x2", "y2",
            "notches", "button", "count", "duration_s", "delay_s",
        }
        unknown = set(data) - allowed
        if unknown:
            raise StepError(f"步骤里有不认识的字段：{', '.join(sorted(unknown))}")
        step = cls(**{key: data[key] for key in data if key != "kind"}, kind=kind)
        return step.validated()


@dataclass(frozen=True)
class Macro:
    """一整轮兑换动作 + 循环设置。"""

    steps: tuple[Step, ...] = ()
    loops: int = 1
    interval_s: float = 1.0
    client_size: tuple[int, int] | None = None
    name: str = "查理中士兑换"
    note: str = field(default="", compare=False)

    def validated(self) -> "Macro":
        if not self.steps:
            raise StepError("至少要有一个动作")
        steps = tuple(step if isinstance(step, Step) else Step.from_dict(step)
                      for step in self.steps)
        steps = tuple(step.validated() for step in steps)
        loops = _integer(self.loops, "循环次数", low=0, high=100000)
        interval = _number(self.interval_s, "每轮间隔(秒)", low=0.0, high=MAX_SECONDS)
        size = self.client_size
        if size is not None:
            if (not isinstance(size, (tuple, list)) or len(size) != 2):
                raise StepError("client_size 需要是 (宽, 高)")
            width = _integer(size[0], "客户区宽", low=1, high=MAX_COORD)
            height = _integer(size[1], "客户区高", low=1, high=MAX_COORD)
            size = (width, height)
        if not isinstance(self.name, str):
            raise StepError("name 需要是字符串")
        return replace(self, steps=steps, loops=loops, interval_s=interval,
                       client_size=size, name=self.name.strip() or "未命名")

    def to_dict(self) -> dict:
        data: dict = {
            "name": self.name,
            "loops": self.loops,
            "interval_s": self.interval_s,
            "steps": [step.to_dict() for step in self.steps],
        }
        if self.client_size:
            data["client_size"] = list(self.client_size)
        if self.note:
            data["note"] = self.note
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Macro":
        if not isinstance(data, dict):
            raise StepError("配置文件需要一个对象")
        unknown = set(data) - {"name", "loops", "interval_s", "steps", "client_size", "note"}
        if unknown:
            raise StepError(f"配置里有不认识的字段：{', '.join(sorted(unknown))}")
        steps = data.get("steps")
        if not isinstance(steps, list):
            raise StepError("steps 需要是列表")
        size = data.get("client_size")
        return cls(
            steps=tuple(Step.from_dict(item) for item in steps),
            loops=data.get("loops", 1),
            interval_s=data.get("interval_s", 1.0),
            client_size=tuple(size) if size else None,
            name=data.get("name", "查理中士兑换"),
            note=data.get("note", ""),
        ).validated()


def load_macro(path: str | Path) -> Macro:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise StepError(f"找不到配置文件：{path}") from exc
    except json.JSONDecodeError as exc:
        raise StepError(f"{path.name} 不是合法 JSON：{exc}") from exc
    return Macro.from_dict(data)


def save_macro(macro: Macro, path: str | Path) -> Path:
    path = Path(path)
    data = macro.validated().to_dict()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
