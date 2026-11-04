import os
import unittest

if os.name != "nt":
    raise unittest.SkipTest("窗口消息只在 Windows 上有意义")

from chali_macro.winapi import pack_key_lparam, pack_point, pack_wheel_wparam


class PackTest(unittest.TestCase):
    def test_point_packs_x_low_y_high(self) -> None:
        self.assertEqual(pack_point(683, 384), (384 << 16) | 683)
        self.assertEqual(pack_point(0, 0), 0)

    def test_wheel_delta_in_high_word(self) -> None:
        self.assertEqual(pack_wheel_wparam(-1) >> 16, 0xFF88)   # -120 补码
        self.assertEqual(pack_wheel_wparam(1) >> 16, 120)
        self.assertEqual(pack_wheel_wparam(-3) >> 16, 0xFE98)   # -360 补码

    def test_key_lparam_carries_scan_code_and_state(self) -> None:
        down = pack_key_lparam(0x15, False, False)
        self.assertEqual(down & 0xFFFF, 1)                # 重复次数 1
        self.assertEqual((down >> 16) & 0xFF, 0x15)       # 扫描码
        self.assertEqual(down >> 31, 0)                   # 按下
        up = pack_key_lparam(0x15, True, True)
        self.assertEqual(up >> 31, 1)                     # 抬起
        self.assertEqual((up >> 30) & 1, 1)               # 之前是按下的
        self.assertEqual((up >> 24) & 1, 1)               # 扩展键


if __name__ == "__main__":
    unittest.main()
