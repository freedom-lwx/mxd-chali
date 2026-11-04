import unittest

from chali_macro.steps import (
    Macro,
    Step,
    StepError,
    load_macro,
    save_macro,
)


class StepValidationTest(unittest.TestCase):
    def test_key_alias_is_normalized(self) -> None:
        self.assertEqual(Step(kind="key", key="回车").validated().key, "enter")
        self.assertEqual(Step(kind="key", key="Enter").validated().key, "enter")
        self.assertEqual(Step(kind="key", key="F1").validated().key, "f1")
        self.assertEqual(Step(kind="key", key="7").validated().key, "7")

    def test_stop_key_is_rejected(self) -> None:
        with self.assertRaises(StepError):
            Step(kind="key", key="f9").validated()

    def test_unknown_key_is_rejected(self) -> None:
        with self.assertRaises(StepError):
            Step(kind="key", key="hyper").validated()

    def test_unknown_kind_is_rejected(self) -> None:
        with self.assertRaises(StepError):
            Step(kind="teleport").validated()

    def test_wheel_needs_notches_in_range(self) -> None:
        self.assertEqual(Step(kind="wheel", x=10, y=20, notches=-3).validated().notches, -3)
        with self.assertRaises(StepError):
            Step(kind="wheel", x=10, y=20, notches=0).validated()
        with self.assertRaises(StepError):
            Step(kind="wheel", x=10, y=20, notches=51).validated()

    def test_coordinates_must_be_inside_window_pixels(self) -> None:
        self.assertEqual(Step(kind="click", x=0, y=0).validated().x, 0)
        with self.assertRaises(StepError):
            Step(kind="click", x=-5, y=10).validated()
        with self.assertRaises(StepError):
            Step(kind="move", x=10_001, y=10).validated()

    def test_click_and_drag_limits(self) -> None:
        with self.assertRaises(StepError):
            Step(kind="click", x=1, y=1, repeat=0).validated()
        with self.assertRaises(StepError):
            Step(kind="click", x=1, y=1, button="middle").validated()
        with self.assertRaises(StepError):
            Step(kind="drag", x=1, y=1, x2=2, y2=2, duration_s=9).validated()
        self.assertEqual(Step(kind="drag", x=1, y=1, x2=2, y2=2).validated().x2, 2)

    def test_repeat_defaults_to_once(self) -> None:
        self.assertEqual(Step(kind="key", key="y").validated().repeat, 1)

    def test_repeat_is_kept_and_limited(self) -> None:
        step = Step(kind="key", key="y", repeat=3, gap_s=0.3).validated()
        self.assertEqual((step.repeat, step.gap_s), (3, 0.3))
        with self.assertRaises(StepError):
            Step(kind="key", key="y", repeat=51).validated()
        with self.assertRaises(StepError):
            Step(kind="wheel", x=1, y=1, notches=-1, gap_s=11).validated()

    def test_wait_has_no_repeat(self) -> None:
        with self.assertRaises(StepError):
            Step(kind="wait", seconds=1.0, repeat=3).validated()

    def test_old_count_field_is_read_as_repeat(self) -> None:
        step = Step.from_dict({"kind": "click", "x": 5, "y": 6, "count": 4})
        self.assertEqual(step.repeat, 4)
        self.assertNotIn("count", step.to_dict())

    def test_label_shows_repeat(self) -> None:
        label = Step(kind="key", key="y", repeat=3, gap_s=0.3).validated().label()
        self.assertIn("×3", label)
        self.assertNotIn("×", Step(kind="wait", seconds=1.0).label())

    def test_delay_and_wait_bounds(self) -> None:
        with self.assertRaises(StepError):
            Step(kind="wait", seconds=0).validated()
        with self.assertRaises(StepError):
            Step(kind="wait", delay_s=31).validated()
        self.assertEqual(Step(kind="wait", seconds=0.5, delay_s=0).validated().delay_s, 0)

    def test_label_reads_like_an_instruction(self) -> None:
        self.assertEqual(Step(kind="wheel", x=480, y=300, notches=-3).label(),
                         "滚轮 下 3 格 @(480, 300)")
        self.assertIn("等待", Step(kind="wait", seconds=0.6).label().replace("等 ", "等待 "))
        self.assertIn("(480, 300)", Step(kind="click", x=480, y=300).label())


class MacroTest(unittest.TestCase):
    def test_empty_macro_is_rejected(self) -> None:
        with self.assertRaises(StepError):
            Macro(steps=()).validated()

    def test_zero_loops_means_forever(self) -> None:
        macro = Macro(steps=(Step(kind="wait", seconds=0.5),), loops=0).validated()
        self.assertEqual(macro.loops, 0)

    def test_negative_loops_is_rejected(self) -> None:
        with self.assertRaises(StepError):
            Macro(steps=(Step(kind="wait", seconds=0.5),), loops=-1).validated()

    def test_json_round_trip_keeps_steps(self) -> None:
        macro = Macro(
            steps=(
                Step(kind="key", key="space", delay_s=0.8),
                Step(kind="wheel", x=480, y=300, notches=-4, delay_s=0.5),
                Step(kind="drag", x=10, y=20, x2=30, y2=40, duration_s=0.6),
            ),
            loops=3,
            interval_s=1.25,
            client_size=(800, 600),
        ).validated()
        restored = Macro.from_dict(macro.to_dict()).validated()
        self.assertEqual(restored.steps, macro.steps)
        self.assertEqual(restored.loops, 3)
        self.assertEqual(restored.client_size, (800, 600))

    def test_unknown_field_is_rejected(self) -> None:
        with self.assertRaises(StepError):
            Macro.from_dict({"steps": [{"kind": "wait", "seconds": 0.5}], "surprise": 1})

    def test_save_and_load_file(self) -> None:
        macro = Macro(steps=(Step(kind="wait", seconds=0.5),), loops=2).validated()
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            path = save_macro(macro, Path(folder) / "config.json")
            self.assertEqual(load_macro(path).steps, macro.steps)

    def test_example_config_is_valid(self) -> None:
        from pathlib import Path

        example = Path(__file__).resolve().parents[1] / "config.example.json"
        macro = load_macro(example)
        self.assertGreaterEqual(len(macro.steps), 3)


if __name__ == "__main__":
    unittest.main()
