"""RandomizationEngine and UInputBackend (with FakeUInput instead of /dev/uinput)."""

import random
import unittest
from unittest import mock

import activity_imitator as core
from evdev import ecodes
from tests.fakes import FakeUInput


class RandomizationEngineTest(unittest.TestCase):
    def test_bounding_box_is_the_central_safe_zone(self):
        m = core.BOUNDING_BOX_MARGIN
        self.assertEqual(core.RandomizationEngine.bounding_box(), (m, 1 - m, m, 1 - m))

    def test_random_points_stay_inside_the_box(self):
        random.seed(1)
        box = core.RandomizationEngine.bounding_box()
        for _ in range(500):
            x, y = core.RandomizationEngine.random_point_in_box(box)
            self.assertTrue(box[0] <= x <= box[1] and box[2] <= y <= box[3])

    def test_next_delay_within_configured_range(self):
        random.seed(2)
        for _ in range(200):
            self.assertTrue(core.MIN_DELAY_SECONDS <= core.RandomizationEngine.next_delay()
                            <= core.MAX_DELAY_SECONDS)

    def test_choose_action_covers_all_weighted_actions(self):
        random.seed(3)
        seen = {core.RandomizationEngine.choose_action() for _ in range(500)}
        self.assertEqual(seen, set(core.ACTION_WEIGHTS))


class UInputBackendTest(unittest.TestCase):
    def setUp(self):
        FakeUInput.created.clear()
        for patcher in (mock.patch.object(core, "UInput", FakeUInput),
                        mock.patch.object(core.time, "sleep")):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.backend = core.UInputBackend()
        self.pointer, self.keyboard = FakeUInput.created

    def test_creates_named_virtual_pointer_and_keyboard(self):
        for dev in (self.pointer, self.keyboard):
            self.assertTrue(dev.name.startswith(core.VIRTUAL_DEVICE_PREFIX))
        abs_codes = [code for code, _info in self.pointer.caps[ecodes.EV_ABS]]
        self.assertEqual(abs_codes, [ecodes.ABS_X, ecodes.ABS_Y])
        self.assertIn(ecodes.BTN_LEFT, self.pointer.caps[ecodes.EV_KEY])
        self.assertEqual(set(self.keyboard.caps[ecodes.EV_KEY]), set(core.UInputBackend.KEYMAP.values()))

    def test_move_to_scales_and_clamps_coordinates(self):
        self.backend.move_to(0.5, 2.0)
        mx = core.UInputBackend.ABS_MAX
        self.assertEqual(self.pointer.written, [(ecodes.EV_ABS, ecodes.ABS_X, int(0.5 * mx)),
                                                (ecodes.EV_ABS, ecodes.ABS_Y, mx), "syn"])
        self.assertEqual((self.backend.x, self.backend.y), (0.5, 1.0))
        self.backend.move_to(-1, 0)
        self.assertEqual(self.backend.x, 0.0)

    def test_click_presses_then_releases(self):
        self.backend.click()
        self.assertEqual(self.pointer.written, [(ecodes.EV_KEY, ecodes.BTN_LEFT, 1), "syn",
                                                (ecodes.EV_KEY, ecodes.BTN_LEFT, 0), "syn"])

    def test_scroll_sends_one_wheel_event_per_notch(self):
        self.backend.scroll(-2)
        wheel = [w for w in self.pointer.written if w != "syn"]
        self.assertEqual(wheel, [(ecodes.EV_REL, ecodes.REL_WHEEL, -1)] * 2)
        self.pointer.written.clear()
        self.backend.scroll(1)
        self.assertEqual(self.pointer.written[0], (ecodes.EV_REL, ecodes.REL_WHEEL, 1))

    def test_press_releases_keys_in_reverse_order(self):
        self.backend.press("alt", "left")
        keys = [(code, value) for item in self.keyboard.written if item != "syn" for _t, code, value in [item]]
        self.assertEqual(keys, [(ecodes.KEY_LEFTALT, 1), (ecodes.KEY_LEFT, 1),
                                (ecodes.KEY_LEFT, 0), (ecodes.KEY_LEFTALT, 0)])

    def test_close_closes_both_devices_even_if_one_fails(self):
        self.pointer.close = mock.Mock(side_effect=OSError("gone"))
        self.backend.close()
        self.assertTrue(self.keyboard.closed)


class UInputBackendPermissionTest(unittest.TestCase):
    def test_missing_uinput_access_raises_clear_permission_error(self):
        with mock.patch.object(core, "UInput", side_effect=OSError(13, "Permission denied")):
            with self.assertRaises(PermissionError) as ctx:
                core.UInputBackend()
        self.assertIn("/dev/uinput", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
