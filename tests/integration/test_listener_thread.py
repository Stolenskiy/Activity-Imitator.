"""SafetyListener's real select() thread over pipe-backed fake devices."""

import io
import time
import unittest
from contextlib import redirect_stdout
from unittest import mock

import activity_imitator as core
from evdev import ecodes
from tests.fakes import KEYBOARD_CAPS, MOUSE_CAPS, FakeInputDevice, event, key


def wait_for(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class ListenerThreadTest(unittest.TestCase):
    def setUp(self):
        self.devices = {}
        for patcher in (mock.patch.object(core.evdev, "list_devices", lambda: list(self.devices)),
                        mock.patch.object(core.evdev, "InputDevice", lambda path: self.devices[path]),
                        mock.patch.object(core.SafetyListener, "RESCAN_SECONDS", 0.05)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.toggles = []

    def start(self):
        with redirect_stdout(io.StringIO()):
            listener = core.SafetyListener(on_pause_toggle=self.toggles.append)
            listener.start()
        self.addCleanup(self._stop, listener)
        return listener

    @staticmethod
    def _stop(listener):
        listener.stop()
        listener._thread.join(timeout=3)

    def test_hotkeys_and_activity_arrive_through_the_thread(self):
        kbd = FakeInputDevice("kbd", KEYBOARD_CAPS, pipe=True)
        mouse = FakeInputDevice("mouse", MOUSE_CAPS, pipe=True)
        self.devices.update({"/dev/input/event1": kbd, "/dev/input/event2": mouse})
        listener = self.start()
        with redirect_stdout(io.StringIO()):
            kbd.feed(key(ecodes.KEY_LEFTCTRL), key(ecodes.KEY_LEFTALT), key(ecodes.KEY_S))
            self.assertTrue(wait_for(lambda: self.toggles == [True]))
        listener.last_user_input = 0.0
        mouse.feed(event(ecodes.EV_REL, ecodes.REL_X, 5))
        self.assertTrue(wait_for(lambda: listener.idle_seconds() < 1))

    def test_hot_plugged_devices_are_picked_up(self):
        listener = self.start()
        self.devices["/dev/input/event7"] = FakeInputDevice("late kbd", KEYBOARD_CAPS, pipe=True)
        self.assertTrue(wait_for(lambda: listener.has_devices))

    def test_read_errors_are_ignored(self):
        kbd = FakeInputDevice("kbd", KEYBOARD_CAPS, pipe=True)
        self.devices["/dev/input/event1"] = kbd
        original_read = kbd.read
        calls = []

        def flaky_read():
            calls.append(1)
            original_read()
            raise OSError("device unplugged mid-read")
        kbd.read = flaky_read
        listener = self.start()
        kbd.feed(key(ecodes.KEY_A))
        self.assertTrue(wait_for(lambda: calls))
        self.assertTrue(listener._thread.is_alive())

    def test_broken_descriptor_triggers_a_rescan(self):
        broken = FakeInputDevice("kbd", KEYBOARD_CAPS)  # fd is not a real descriptor
        self.devices["/dev/input/event3"] = broken
        with redirect_stdout(io.StringIO()):
            listener = core.SafetyListener()
        self.addCleanup(self._stop, listener)
        del self.devices["/dev/input/event3"]
        listener.start()
        self.assertTrue(wait_for(lambda: not listener.has_devices))
        self.assertTrue(broken.closed)


if __name__ == "__main__":
    unittest.main()
