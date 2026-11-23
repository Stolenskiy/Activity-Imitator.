"""MainLoop (console mode) driven by fakes and a fake clock."""

import io
import time
import unittest
from contextlib import redirect_stdout
from unittest import mock

import activity_imitator as core
from tests.fakes import FakeSafety, FakeSimulator


class MainLoopTest(unittest.TestCase):
    def setUp(self):
        for patcher in (mock.patch.object(core, "InputSimulator", FakeSimulator),
                        mock.patch.object(core, "SafetyListener", FakeSafety),
                        mock.patch.object(core.RandomizationEngine, "next_delay", return_value=1.0)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.loop = core.MainLoop()
        self.sleeps = 0

    def run_loop(self, max_sleeps=40, on_sleep=None):
        def fake_sleep(_seconds):
            self.sleeps += 1
            if on_sleep:
                on_sleep(self.sleeps)
            if self.sleeps >= max_sleeps:
                self.loop.safety.should_quit = True
        out = io.StringIO()
        with mock.patch.object(core.time, "sleep", fake_sleep), redirect_stdout(out):
            self.loop.run()
        return out.getvalue()

    def test_performs_actions_and_cleans_up(self):
        log = self.run_loop()
        self.assertIn("Action:", log)
        self.assertIn("Activity Imitator stopped.", log)
        self.assertTrue(self.loop.simulator.closed and self.loop.safety.stopped and self.loop.safety.started)

    def test_auto_pauses_while_the_user_is_active_then_resumes(self):
        self.loop.safety.last_user_input = time.monotonic()

        def user_leaves(n):
            if n == 5:
                self.loop.safety.last_user_input = 0.0
        log = self.run_loop(on_sleep=user_leaves)
        self.assertIn("auto-pause", log)
        self.assertIn("resuming", log)
        self.assertLess(log.index("auto-pause"), log.index("Action:"))

    def test_manual_pause_performs_no_actions(self):
        self.loop.safety.paused = True
        self.run_loop(max_sleeps=10)
        self.assertEqual(self.loop.simulator.calls, [])

    def test_user_activity_check_needs_input_devices(self):
        self.loop.safety.last_user_input = time.monotonic()
        self.assertTrue(self.loop._user_active())
        self.loop.safety.has_devices = False
        self.assertFalse(self.loop._user_active())


if __name__ == "__main__":
    unittest.main()
