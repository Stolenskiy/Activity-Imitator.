"""Offscreen render smoke tests for custom widgets (exercise every paint branch)."""

import time
import unittest

import activity_imitator_gui as gui
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QEnterEvent, QIcon, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QListWidgetItem
from tests.fakes import pump, qapp


def rendered(widget):
    widget.resize(widget.sizeHint().expandedTo(widget.minimumSize()))
    image = widget.grab().toImage()
    return not image.isNull() and image.width() > 0


class WidgetRenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qapp()

    def test_power_ring_renders_every_state(self):
        ring = gui.PowerRing()
        cases = [("stopped", {}), ("error", {}), ("paused", {}),
                 ("running", {"remaining_s": None}), ("running", {"remaining_s": 12.4, "remaining_fraction": 0.4}),
                 ("waiting", {"wait_s": 30.0, "wait_fraction": 0.5})]
        for status, attrs in cases:
            ring.status = status
            for name, value in attrs.items():
                setattr(ring, name, value)
            for hover in (0.0, 1.0):
                ring.hover = hover
                self.assertTrue(rendered(ring), status)

    def test_power_ring_hover_animation(self):
        ring = gui.PowerRing()
        ring.enterEvent(QEnterEvent(QPointF(5, 5), QPointF(5, 5), QPointF(5, 5)))
        ring.leaveEvent(QEvent(QEvent.Type.Leave))
        self.assertGreaterEqual(ring.hover, 0.0)

    def test_status_pill_renders_and_resizes_per_status(self):
        pill = gui.StatusPill()
        widths = set()
        for status in gui.STATUS_TEXT:
            pill.set_status(status)
            pill.phase += 1.0
            self.assertTrue(rendered(pill))
            widths.add(pill.width())
        self.assertGreater(len(widths), 1)

    def test_toggle_animates_and_renders_disabled(self):
        toggle = gui.Toggle(checked=False)
        toggle.setChecked(True)
        self.assertTrue(pump(lambda: toggle.knob == 1.0, timeout=2))
        toggle.setEnabled(False)
        self.assertTrue(rendered(toggle))
        self.assertEqual(toggle.sizeHint().width(), 42)

    def test_log_list_empty_state_and_rows(self):
        log = gui.LogList()
        log.setItemDelegate(gui.LogDelegate(log.font(), log))
        log.resize(400, 200)
        self.assertTrue(rendered(log))
        for kind in ("mouse", "warn", "error", "unknown-kind"):
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, ("12:00:00", kind, f"{kind} text " * 10))
            log.addItem(item)
        self.assertTrue(rendered(log))

    def test_stat_card_icon_font_palette(self):
        card = gui.StatCard("Дій")
        self.assertEqual(card.title.text(), "ДІЙ")
        icon = gui.icon_with_dot(QIcon(str(gui.ICON_PATH)), gui.GREEN)
        self.assertFalse(icon.isNull())
        self.assertFalse(gui.icon_with_dot(QIcon(str(gui.ICON_PATH)), None).isNull())
        self.assertEqual(gui.pick_font().pixelSize(), 13)
        self.assertEqual(gui.dark_palette().window().color().name(), gui.BG)

    def test_slider_ignores_mouse_wheel(self):
        slider = gui.NoWheelSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 10)
        slider.setValue(5)
        wheel = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, 120),
                            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                            Qt.ScrollPhase.NoScrollPhase, False)
        slider.wheelEvent(wheel)
        self.assertEqual(slider.value(), 5)


class SyntheticInputGuardTest(unittest.TestCase):
    def test_eats_clicks_right_after_synthetic_actions_only(self):
        worker = type("W", (), {"guard_until": time.monotonic() + 10})()
        guard = gui.SyntheticInputGuard(worker)
        press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(1, 1), QPointF(1, 1),
                            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self.assertTrue(guard.eventFilter(None, press))
        self.assertFalse(guard.eventFilter(None, QEvent(QEvent.Type.Paint)))
        worker.guard_until = 0.0
        self.assertFalse(guard.eventFilter(None, press))
        self.assertFalse(gui.SyntheticInputGuard(None).eventFilter(None, press))


if __name__ == "__main__":
    unittest.main()
