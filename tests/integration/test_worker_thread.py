"""ImitatorWorker's real background thread and MainWindow end-to-end (fake hardware,
shortened delays, Qt event loop pumped by tests.fakes.pump)."""

import time
import unittest
from unittest import mock

import activity_imitator_gui as gui
from PySide6.QtGui import QIcon
from tests.fakes import fake_hardware, pump, qapp


class WorkerThreadCase(unittest.TestCase):
    def setUp(self):
        qapp()
        hw = fake_hardware()
        hw.__enter__()
        self.addCleanup(hw.__exit__, None, None, None)
        patcher = mock.patch.object(gui.random, "uniform", lambda a, b: 0.03)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.settings = gui.Settings(resume_after=1)
        self.worker = gui.ImitatorWorker(self.settings)
        self.addCleanup(self.worker.shutdown)
        self.actions, self.waits, self.finished, self.schedules = [], [], [], []
        self.worker.action.connect(lambda rid, kind, text: self.actions.append((kind, text)))
        self.worker.user_wait.connect(lambda rid, rem: self.waits.append(rem))
        self.worker.finished.connect(lambda rid, reason: self.finished.append(reason))
        self.worker.scheduled.connect(lambda rid, delay: self.schedules.append(delay))

    def real_actions(self):
        return [a for a in self.actions if a[0] in ("mouse", "click", "key", "pause")]

    def stop_and_wait(self):
        self.worker.request_stop()
        self.assertTrue(pump(lambda: self.finished, timeout=3), "worker did not finish")


class WorkerThreadTest(WorkerThreadCase):
    def test_runs_actions_on_a_schedule_until_stopped(self):
        self.worker.start()
        self.assertTrue(pump(lambda: len(self.real_actions()) >= 4))
        self.stop_and_wait()
        self.assertEqual(self.finished, ["stopped"])
        self.assertTrue(self.schedules)

    def test_manual_pause_holds_actions(self):
        self.worker.start()
        self.assertTrue(pump(lambda: self.real_actions()))
        self.worker.set_paused(True)
        pump(timeout=0.2)
        held = len(self.real_actions())
        pump(timeout=0.4)
        self.assertLessEqual(len(self.real_actions()), held + 1)
        self.worker.set_paused(False)
        self.assertTrue(pump(lambda: len(self.real_actions()) > held + 1))
        self.stop_and_wait()

    def test_user_activity_auto_pauses_then_resumes(self):
        self.worker.start()
        self.assertTrue(pump(lambda: self.real_actions()))
        self.worker.activity_baseline = 0.0
        self.worker.safety.last_user_input = time.monotonic()
        self.assertTrue(pump(lambda: any(r >= 0 for r in self.waits)))
        self.assertIn(("auto", "Автопауза: ви користуєтесь комп'ютером"), self.actions)
        self.assertTrue(pump(lambda: -1.0 in self.waits, timeout=3))
        self.assertIn(("auto", "Ви неактивні — продовжую"), self.actions)
        self.stop_and_wait()

    def test_warns_when_every_action_is_disabled(self):
        self.settings.mouse = self.settings.keys = self.settings.pauses = False
        self.worker.start()
        self.assertTrue(pump(lambda: any(k == "warn" for k, _ in self.actions)))
        self.stop_and_wait()

    def test_simulator_crash_finishes_with_error(self):
        self.settings.keys = self.settings.pauses = False
        self.worker.simulator.fail = RuntimeError("boom")
        self.worker.start()
        self.assertTrue(pump(lambda: self.finished))
        self.assertEqual(self.finished, ["error:boom"])


class WindowEndToEndTest(unittest.TestCase):
    def test_window_runs_and_stops_with_a_real_worker_thread(self):
        qapp()
        with fake_hardware(), mock.patch.object(gui.random, "uniform", lambda a, b: 0.03), \
                mock.patch.object(gui.Settings, "save", lambda self: None):
            win = gui.MainWindow(QIcon(str(gui.ICON_PATH)))
            try:
                win.start()
                self.assertTrue(pump(lambda: win.action_count >= 3))
                self.assertEqual(win.display_status(), "running")
                win.stop()
                self.assertEqual(win.status, "stopped")
            finally:
                win.quit()


if __name__ == "__main__":
    unittest.main()
