"""InputSimulator with a FakeBackend (no real devices)."""

import random
import re
import unittest
from unittest import mock

import activity_imitator as core
from tests.fakes import FakeBackend

DETAIL = re.compile(r"^move to \((\d+)%, (\d+)%\)( \+ click \+ scroll\((-?\d+)\))?$")


class InputSimulatorTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(core.time, "sleep")
        patcher.start()
        self.addCleanup(patcher.stop)
        random.seed(7)
        self.backend = FakeBackend()
        self.sim = core.InputSimulator(core.RandomizationEngine(), self.backend)

    def test_move_mouse_glides_into_the_safe_zone_without_clicking(self):
        detail = self.sim.move_mouse(click_chance=0.0)
        m = DETAIL.match(detail)
        self.assertIsNotNone(m, detail)
        self.assertIsNone(m.group(3))
        x_min, x_max, y_min, y_max = core.RandomizationEngine.bounding_box()
        x, y = self.backend.moves[-1]
        self.assertTrue(x_min <= x <= x_max and y_min <= y <= y_max)
        self.assertGreaterEqual(len(self.backend.moves), 10)
        self.assertEqual(self.backend.clicks, 0)

    def test_move_mouse_can_click_and_scroll(self):
        detail = self.sim.move_mouse(click_chance=1.0)
        self.assertRegex(detail, r"\+ click \+ scroll\(-?\d\)$")
        self.assertEqual(self.backend.clicks, 1)
        self.assertEqual(len(self.backend.scrolls), 1)

    def test_move_mouse_stops_immediately_when_user_takes_over(self):
        self.assertEqual(self.sim.move_mouse(click_chance=1.0, should_abort=lambda: True),
                         "move interrupted")
        self.assertEqual((self.backend.moves, self.backend.clicks), ([], 0))

    def test_move_mouse_aborts_midway(self):
        checks = iter([False, False, False] + [True] * 100)
        self.assertEqual(self.sim.move_mouse(should_abort=lambda: next(checks)), "move interrupted")
        self.assertEqual(len(self.backend.moves), 3)

    def test_bezier_path_starts_and_ends_exactly(self):
        path = self.sim._cubic_bezier_path((0.2, 0.3), (0.7, 0.6), 20)
        self.assertEqual(len(path), 21)
        self.assertAlmostEqual(path[0][0], 0.2)
        self.assertAlmostEqual(path[-1][1], 0.6)

    def test_ease_in_out_is_monotonic_from_0_to_1(self):
        values = [core.InputSimulator._ease_in_out(i / 10) for i in range(11)]
        self.assertEqual((values[0], values[-1]), (0.0, 1.0))
        self.assertEqual(values, sorted(values))

    def test_navigation_keystroke_only_presses_safe_keys(self):
        allowed = {k if isinstance(k, str) else "+".join(k) for k in core.SAFE_KEYS}
        for _ in range(100):
            name = self.sim.navigation_keystroke()
            self.assertIn(name, allowed)
            self.assertEqual("+".join(self.backend.presses[-1]), name)

    def test_micro_pause_reports_its_duration(self):
        self.assertRegex(self.sim.micro_pause(), r"^idle \d\.\ds$")

    def test_close_closes_the_backend(self):
        self.sim.close()
        self.assertTrue(self.backend.closed)

    def test_default_backend_is_uinput(self):
        with mock.patch.object(core, "UInputBackend", return_value="backend") as factory:
            sim = core.InputSimulator(core.RandomizationEngine())
        factory.assert_called_once_with()
        self.assertEqual(sim.backend, "backend")


if __name__ == "__main__":
    unittest.main()
