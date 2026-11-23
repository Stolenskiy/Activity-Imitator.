"""MainWindow state machine with fake hardware and no worker thread (signals driven by hand)."""

import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import activity_imitator as core
import activity_imitator_gui as gui
from PySide6.QtGui import QCloseEvent, QIcon
from tests.fakes import FakeSafety, FakeSimulator, fake_hardware, qapp


class WindowCase(unittest.TestCase):
    safety_factory = FakeSafety
    simulator_factory = FakeSimulator

    def setUp(self):
        qapp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        hw = fake_hardware(self.simulator_factory, self.safety_factory)
        for patcher in (mock.patch.object(gui, "CONFIG_PATH", Path(tmp.name) / "settings.json"),
                        mock.patch.object(gui.ImitatorWorker, "_run", lambda *_a: None)):
            patcher.start()
            self.addCleanup(patcher.stop)
        hw.__enter__()
        self.addCleanup(hw.__exit__, None, None, None)
        self.win = gui.MainWindow(QIcon(str(gui.ICON_PATH)))
        self.addCleanup(self.win.quit)

    def logs(self):
        return [self.win.log_list.item(i).data(256)[2] for i in range(self.win.log_list.count())]


class LifecycleTest(WindowCase):
    def test_starts_stopped_and_ready(self):
        self.assertEqual(self.win.display_status(), "stopped")
        self.assertTrue(self.win.ring.isEnabled())
        self.assertIn("Готово до запуску", self.logs())
        self.assertIn("паузу", self.win.footer_hint.text())

    def test_start_pause_resume_stop(self):
        self.win.start()
        self.assertEqual((self.win.display_status(), self.win.worker.run_id), ("running", 1))
        self.assertTrue(self.win.pause_btn.isEnabled())
        self.win.toggle_pause()
        self.assertEqual(self.win.display_status(), "paused")
        self.assertTrue(self.win.worker.paused and self.win.worker.safety.paused)
        self.win.toggle_pause()
        self.assertEqual(self.win.display_status(), "running")
        self.win.toggle_run()
        self.assertEqual(self.win.display_status(), "stopped")
        self.assertIn("Імітацію зупинено", self.logs())

    def test_actions_are_counted_and_shown(self):
        self.win.start()
        rid = self.win.run_id
        self.win._on_action(rid, "mouse", "Рух миші → 1% × 2% екрана")
        self.win._on_action(rid, "auto", "Автопауза")
        self.win._on_action(rid + 99, "mouse", "stale run")
        self.assertEqual(self.win.action_count, 1)
        self.assertIn("Рух миші", self.win.last_label.text())
        self.win._on_scheduled(rid, 10.0)
        self.win._tick_anim()
        self.assertAlmostEqual(self.win.ring.remaining_s, 10.0, delta=0.5)

    def test_auto_pause_display_and_recovery(self):
        self.win.start()
        self.win._on_user_wait(self.win.run_id, 30.0)
        self.win._tick_anim()
        self.win._tick_slow()
        self.assertEqual(self.win.display_status(), "waiting")
        self.assertGreater(self.win.ring.wait_s, 25)
        self.assertIn("комп'ютером", self.win.last_label.text())
        self.win._on_user_wait(self.win.run_id, -1.0)
        self.assertEqual(self.win.display_status(), "running")

    def test_hotkeys(self):
        self.win._on_hotkey_toggle()
        self.assertEqual(self.win.status, "running")
        self.win._on_hotkey_toggle()
        self.assertEqual(self.win.status, "paused")
        self.win._on_hotkey_toggle()
        self.assertEqual(self.win.status, "running")
        self.win.worker.hotkey_stop.emit()
        self.assertEqual(self.win.status, "stopped")
        self.assertIn("Зупинено гарячою клавішею Ctrl+Alt+Q", self.logs())

    def test_duration_sets_deadline_and_timer_stops(self):
        self.win.start()
        self.win.dur_group.button(60).click()
        self.assertEqual(self.win.settings.duration_min, 60)
        self.assertGreater(self.win.deadline, datetime.now() + timedelta(minutes=59))
        self.win.deadline = datetime.now() - timedelta(seconds=1)
        self.win._tick_slow()
        self.assertEqual(self.win.status, "stopped")
        self.assertIn("Час вийшов — імітацію зупинено", self.logs())
        self.win.dur_group.button(0).click()
        self.assertEqual(self.win.stat_stop.value.text(), "∞")

    def test_worker_error_stops_and_is_logged(self):
        self.win.start()
        self.win._on_finished(self.win.run_id, "error:boom")
        self.assertEqual(self.win.status, "stopped")
        self.assertIn("Помилка: boom", self.logs())
        self.win._on_finished(self.win.run_id + 5, "error:ignored")

    def test_close_without_tray_shuts_down(self):
        self.win.tray = None
        event = QCloseEvent()
        self.win.closeEvent(event)
        self.assertTrue(event.isAccepted())
        self.assertTrue(self.win.worker.safety.stopped and self.win.worker.simulator.closed)


class SettingsUiTest(WindowCase):
    def test_interval_sliders_keep_a_gap(self):
        self.win.min_slider.setValue(50)
        self.assertGreaterEqual(self.win.max_slider.value(), 53)
        self.win.max_slider.setValue(10)
        self.assertLessEqual(self.win.min_slider.value(), 7)
        self.assertEqual(self.win.interval_value.text(),
                         f"{self.win.settings.min_delay}–{self.win.settings.max_delay} с")

    def test_toggles_update_settings_and_dependants(self):
        self.win.t_mouse.setChecked(False)
        self.assertFalse(self.win.settings.mouse or self.win.t_clicks.isEnabled())
        self.win.t_autopause.setChecked(False)
        self.assertIn("вимкнено", self.win.footer_hint.text())
        self.win.resume_slider.setValue(24)
        self.assertEqual(self.win.settings.resume_after, 120)
        self.assertEqual(self.win.resume_value.text(), "2 хв")
        self.assertTrue(gui.CONFIG_PATH.exists())


class NoInputDevicesTest(WindowCase):
    class safety_factory(FakeSafety):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.has_devices = False

    def test_hotkeys_and_auto_pause_are_disabled(self):
        self.assertFalse(self.win.t_autopause.isEnabled())
        self.assertIn("вимкнені", self.win.hotkey_state.text())
        self.win.start()
        self.win.worker.safety.last_user_input = time.monotonic()
        self.assertEqual(self.win.worker.user_wait_remaining(), 0.0)


class InitErrorTest(WindowCase):
    @staticmethod
    def simulator_factory(*_a, **_k):
        raise PermissionError("Немає доступу до /dev/uinput")

    def test_error_state_disables_start(self):
        self.assertEqual(self.win.status, "error")
        self.assertFalse(self.win.ring.isEnabled())
        self.win.start()
        self.assertEqual(self.win.status, "error")
        self.assertTrue(any("/dev/uinput" in line for line in self.logs()))


class WorkerLogicTest(WindowCase):
    def test_pick_respects_enabled_actions(self):
        worker = self.win.worker
        s = worker.settings
        s.mouse = s.keys = s.pauses = False
        self.assertIsNone(worker._pick(s))
        s.keys = True
        self.assertEqual({worker._pick(s) for _ in range(20)}, {"navigation"})

    def test_user_wait_ignores_input_before_start_grace(self):
        worker = self.win.worker
        worker.start()
        worker.safety.last_user_input = time.monotonic()
        self.assertEqual(worker.user_wait_remaining(), 0.0)
        worker.activity_baseline = 0.0
        self.assertGreater(worker.user_wait_remaining(), 50)
        worker.set_paused(True)
        worker.set_paused(False)
        self.assertGreater(worker.activity_baseline, time.monotonic())


class CoreMissingTest(unittest.TestCase):
    def test_hotkeys_unavailable_without_core(self):
        with mock.patch.object(gui, "core", None):
            worker = gui.ImitatorWorker(gui.Settings())
        self.assertFalse(worker.hotkeys_available)
        self.assertIsNone(worker.simulator)
        self.assertIs(core, gui.core)


if __name__ == "__main__":
    unittest.main()
