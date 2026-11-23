"""SafetyListener: hotkeys, user-activity tracking and device discovery (fake devices)."""

import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

import activity_imitator as core
from evdev import ecodes
from tests.fakes import (KEYBOARD_CAPS, MOUSE_CAPS, POWER_BUTTON_CAPS, TOUCHPAD_CAPS,
                         FakeInputDevice, event, key)


class ListenerCase(unittest.TestCase):
    def setUp(self):
        self.devices = {}
        for patcher in (mock.patch.object(core.evdev, "list_devices", lambda: list(self.devices)),
                        mock.patch.object(core.evdev, "InputDevice", lambda path: self.devices[path])):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.toggles, self.quits = [], []
        with redirect_stdout(io.StringIO()):
            self.listener = core.SafetyListener(on_pause_toggle=self.toggles.append,
                                                on_quit=lambda: self.quits.append(True))

    def handle(self, *events):
        with redirect_stdout(io.StringIO()):
            for e in events:
                self.listener._handle(e)


class HotkeyTest(ListenerCase):
    CTRL, ALT = ecodes.KEY_LEFTCTRL, ecodes.KEY_LEFTALT

    def test_hotkey_codes_are_derived_from_HOTKEYS(self):
        self.assertEqual(core.SafetyListener.HOTKEY_CODES, {ecodes.KEY_S: "pause", ecodes.KEY_Q: "quit"})

    def test_ctrl_alt_s_toggles_pause_once_per_chord(self):
        self.handle(key(self.CTRL), key(self.ALT), key(ecodes.KEY_S), key(ecodes.KEY_S, 2))
        self.assertEqual((self.listener.paused, self.toggles), (True, [True]))
        self.handle(key(ecodes.KEY_S, 0), key(ecodes.KEY_S))  # still holding Ctrl+Alt
        self.assertEqual(self.toggles, [True])
        self.handle(key(ecodes.KEY_S, 0), key(self.ALT, 0), key(self.CTRL, 0),
                    key(ecodes.KEY_RIGHTCTRL), key(ecodes.KEY_RIGHTALT), key(ecodes.KEY_S))
        self.assertEqual((self.listener.paused, self.toggles), (False, [True, False]))

    def test_ctrl_alt_q_requests_quit(self):
        self.handle(key(self.CTRL), key(self.ALT), key(ecodes.KEY_Q))
        self.assertTrue(self.listener.should_quit)
        self.assertEqual(self.quits, [True])

    def test_letters_without_both_modifiers_do_nothing(self):
        self.handle(key(self.CTRL), key(ecodes.KEY_S), key(ecodes.KEY_Q))
        self.assertEqual((self.listener.paused, self.listener.should_quit, self.toggles), (False, False, []))

    def test_works_without_callbacks(self):
        self.listener.on_pause_toggle = self.listener.on_quit = None
        self.handle(key(self.CTRL), key(self.ALT), key(ecodes.KEY_S), key(ecodes.KEY_Q, 1))
        self.assertTrue(self.listener.paused)


class ActivityTest(ListenerCase):
    def test_idle_is_infinite_before_any_input(self):
        self.assertEqual(self.listener.idle_seconds(), float("inf"))

    def test_motion_scroll_touch_and_key_presses_count_as_activity(self):
        for e in (event(ecodes.EV_REL, ecodes.REL_X, 3), event(ecodes.EV_ABS, ecodes.ABS_X, 10),
                  key(ecodes.KEY_A)):
            self.listener.last_user_input = 0.0
            self.handle(e)
            self.assertLess(self.listener.idle_seconds(), 1.0)

    def test_key_release_autorepeat_and_sync_do_not_count(self):
        for e in (key(ecodes.KEY_A, 0), key(ecodes.KEY_A, 2), event(ecodes.EV_SYN, 0, 0)):
            self.handle(e)
        self.assertEqual(self.listener.last_user_input, 0.0)


class DiscoveryTest(ListenerCase):
    def test_classifies_real_input_devices(self):
        relevant = core.SafetyListener._is_relevant
        self.assertTrue(relevant(FakeInputDevice("kbd", KEYBOARD_CAPS)))
        self.assertTrue(relevant(FakeInputDevice("mouse", MOUSE_CAPS)))
        self.assertTrue(relevant(FakeInputDevice("touchpad", TOUCHPAD_CAPS)))
        self.assertFalse(relevant(FakeInputDevice("power", POWER_BUTTON_CAPS)))
        self.assertFalse(relevant(FakeInputDevice(core.VIRTUAL_DEVICE_PREFIX + " pointer", MOUSE_CAPS)))

    def test_rescan_adds_new_and_drops_removed_devices(self):
        self.assertFalse(self.listener.has_devices)
        kbd, power = FakeInputDevice("kbd", KEYBOARD_CAPS), FakeInputDevice("power", POWER_BUTTON_CAPS)
        self.devices.update({"/dev/input/event1": kbd, "/dev/input/event2": power})
        self.listener._rescan()
        self.assertTrue(self.listener.has_devices and self.listener.has_keyboards)
        self.assertTrue(power.closed)
        del self.devices["/dev/input/event1"]
        self.listener._rescan()
        self.assertFalse(self.listener.has_devices)
        self.assertTrue(kbd.closed)

    def test_rescan_survives_unreadable_devices_and_listing_errors(self):
        self.devices["/dev/input/event9"] = None
        with mock.patch.object(core.evdev, "InputDevice", side_effect=OSError("denied")):
            self.listener._rescan()
        with mock.patch.object(core.evdev, "list_devices", side_effect=OSError("no /dev/input")):
            self.listener._rescan()
        self.assertFalse(self.listener.has_devices)

    def test_start_without_devices_warns_and_stop_closes_devices(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.listener.start()
        self.assertIn("/dev/input", out.getvalue())
        dev = FakeInputDevice("kbd", KEYBOARD_CAPS)
        dev.close = mock.Mock(side_effect=OSError("busy"))
        self.listener._devices["x"] = dev
        self.listener.stop()
        self.listener._thread.join(timeout=3)
        self.assertFalse(self.listener._thread.is_alive())
        dev.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
