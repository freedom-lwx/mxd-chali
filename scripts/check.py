"""跑单元测试，并检查界面/输入模块能否导入（只在 Windows 上检查后者）。"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def check_imports() -> list[str]:
    errors: list[str] = []
    if os.name != "nt":
        print("非 Windows：跳过界面与输入模块的导入检查")
        return errors
    for module in ("chali_macro.winapi", "chali_macro.gui"):
        try:
            __import__(module)
        except Exception as exc:  # pragma: no cover - 只在导入失败时触发
            errors.append(f"{module} 导入失败：{exc}")
    if errors:
        return errors
    # SendInput 的结构体布局错一位，Windows 就会直接拒收输入；这里便宜地瞥一眼。
    import ctypes

    from chali_macro.winapi import _INPUT

    expected = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
    size = ctypes.sizeof(_INPUT)
    if size != expected:
        errors.append(f"INPUT 结构体大小是 {size}，应为 {expected}；按键会发不出去")
    else:
        print(f"INPUT 结构体：{size} 字节（正确）")
    return errors


def main() -> int:
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    if suite.countTestCases() == 0:
        print("ERROR: 没有发现测试", file=sys.stderr)
        return 1
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    errors = check_imports()
    for error in errors:
        print(error, file=sys.stderr)
    print(f"导入检查：{'失败' if errors else '通过'}")
    return 0 if result.wasSuccessful() and not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
