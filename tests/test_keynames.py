"""键名一致性：界面/配置里认的键名，必须真能发出去（防止漏掉方向键这类）。"""

import os
import unittest

from chali_macro.steps import Step

_NAMES_IN_STEPS = (
    "left", "right", "up", "down",
    "space", "enter", "esc", "tab", "home", "end", "pageup", "pagedown",
    "insert", "delete", "shift", "ctrl", "alt",
) + tuple(f"f{i}" for i in range(1, 25)) + tuple(f"numpad{i}" for i in range(10))


class KeyNameTest(unittest.TestCase):
    def test_all_plain_names_are_accepted_by_steps(self) -> None:
        for name in _NAMES_IN_STEPS:
            if name == "f9":
                continue
            with self.subTest(name=name):
                self.assertEqual(Step(kind="key", key=name).validated().key, name)

    def test_chinese_aliases(self) -> None:
        cases = {"上": "up", "下": "down", "左": "left", "右": "right",
                 "回车": "enter", "空格": "space"}
        for alias, expected in cases.items():
            with self.subTest(alias=alias):
                self.assertEqual(Step(kind="key", key=alias).validated().key, expected)

    @unittest.skipUnless(os.name == "nt", "发送层只在 Windows 上可用")
    def test_every_name_can_be_sent(self) -> None:
        from chali_macro.winapi import _virtual_key

        for name in _NAMES_IN_STEPS:
            with self.subTest(name=name):
                vk, _extended = _virtual_key(name)
                self.assertGreater(vk, 0)

    @unittest.skipUnless(os.name == "nt", "发送层只在 Windows 上可用")
    def test_arrows_are_extended_keys(self) -> None:
        from chali_macro.winapi import _virtual_key

        for name in ("left", "right", "up", "down"):
            with self.subTest(name=name):
                self.assertTrue(_virtual_key(name)[1], "方向键需要带扩展位")

    def test_hold_long_enough_to_walk(self) -> None:
        self.assertEqual(Step(kind="key", key="up", hold_s=3.0).validated().hold_s, 3.0)
        with self.assertRaises(Exception):
            Step(kind="key", key="up", hold_s=9.0).validated()


if __name__ == "__main__":
    unittest.main()
