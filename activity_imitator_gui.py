#!/usr/bin/env python3
"""
Activity Imitator — desktop GUI
-------------------------------
A friendly front-end for activity_imitator.py: one big start/stop ring with a
countdown to the next action, live status, stats, an event log, an auto-stop
timer, settings and a system-tray icon.

The input-simulation core (uinput virtual devices, Bezier mouse motion, safe
keys, evdev hotkeys and user-activity detection) lives in activity_imitator.py;
the CLI still works on its own.
"""

from __future__ import annotations

import json
import math
import random
import re
import sys
import threading
import time
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import (
    Property, QEasingCurve, QEvent, QObject, QPointF, QPropertyAnimation,
    QRectF, QSize, Qt, QTimer, Signal,
)
from PySide6.QtGui import (
    QAction, QBrush, QColor, QConicalGradient, QFont, QFontDatabase, QIcon,
    QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPalette, QPen, QPixmap,
    QRadialGradient,
)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QButtonGroup, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu, QPushButton,
    QScrollArea, QSizePolicy, QSlider, QStackedWidget, QStyle,
    QStyledItemDelegate, QSystemTrayIcon, QVBoxLayout, QWidget,
)

APP_ID = "activity-imitator"
APP_NAME = "Activity Imitator"
HERE = Path(__file__).resolve().parent
ICON_PATH = HERE / "assets" / "activity-imitator.svg"
CONFIG_PATH = Path.home() / ".config" / APP_ID / "settings.json"

# Import the core defensively so the window can still explain what went wrong.
try:
    import activity_imitator as core
    CORE_ERROR = None
except Exception as exc:  # pragma: no cover - environment dependent
    core = None
    CORE_ERROR = f"{type(exc).__name__}: {exc}"

# ---------------------------------------------------------------------------
# Design tokens
# ---------------------------------------------------------------------------

BG = "#0b1020"
SURFACE = "#121a2e"
SURFACE_2 = "#18223b"
SURFACE_3 = "#24304f"
TEXT = "#e6eaf5"
MUTED = "#8b94ad"
FAINT = "#5b6480"
CYAN = "#22d3ee"
VIOLET = "#a78bfa"
AMBER = "#fbbf24"
ROSE = "#fb7185"
GREEN = "#34d399"
SLATE = "#64748b"
BLUE = "#60a5fa"

STATUS_COLORS = {"running": GREEN, "waiting": BLUE, "paused": AMBER, "stopped": SLATE, "error": ROSE}
STATUS_TEXT = {"running": "Активний", "waiting": "Автопауза", "paused": "Пауза",
               "stopped": "Зупинено", "error": "Недоступно"}

KIND_COLORS = {
    "mouse": CYAN, "click": VIOLET, "key": GREEN, "pause": SLATE,
    "info": "#94a3b8", "auto": BLUE, "warn": AMBER, "error": ROSE,
}

DURATIONS = [(0, "∞"), (30, "30 хв"), (60, "1 год"), (120, "2 год"), (240, "4 год"), (480, "8 год")]

# How long after a synthetic action our own window ignores clicks/keys, so the
# imitator can never press its own buttons (e.g. "Stop") by accident.
SYNTHETIC_GUARD_S = 0.6


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@dataclass
class Settings:
    min_delay: int = 5
    max_delay: int = 45
    mouse: bool = True
    clicks: bool = True
    keys: bool = True
    pauses: bool = True
    duration_min: int = 0
    auto_pause: bool = True
    resume_after: int = 60
    autostart: bool = False
    close_to_tray: bool = True
    tray_hint_shown: bool = False

    @classmethod
    def load(cls) -> "Settings":
        try:
            data = json.loads(CONFIG_PATH.read_text())
            known = {f.name for f in fields(cls)}
            return cls(**{k: v for k, v in data.items() if k in known})
        except Exception:
            return cls()

    def save(self) -> None:
        try:
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            CONFIG_PATH.write_text(json.dumps(asdict(self), indent=2))
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

KEY_NAMES = {
    "shift": "Shift", "ctrl": "Ctrl", "alt+left": "Alt+←", "alt+right": "Alt+→",
    "pageup": "Page Up", "pagedown": "Page Down", "up": "↑", "down": "↓", "esc": "Esc",
}


def fmt_duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def fmt_human(seconds: float) -> str:
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    if h and m:
        return f"{h} год {m} хв"
    if h:
        return f"{h} год"
    if m:
        return f"{m} хв"
    return f"{seconds} с"


def fmt_ago(seconds: float) -> str:
    seconds = int(max(0, seconds))
    if seconds < 5:
        return "щойно"
    if seconds < 60:
        return f"{seconds} с тому"
    return f"{seconds // 60} хв тому"


def describe_mouse(detail: str) -> tuple[str, str]:
    if detail == "move interrupted":
        return "auto", "Рух перервано — ви взялися за мишу"
    m = re.match(r"move to \((\d+)%, (\d+)%\)(?: \+ click \+ scroll\((-?\d+)\))?", detail)
    if not m:
        return "mouse", detail
    x, y, ticks = m.groups()
    if ticks is None:
        return "mouse", f"Рух миші → {x}% × {y}% екрана"
    return "click", f"Рух → {x}% × {y}%, клік і прокрутка {int(ticks):+d}"


def mix(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
        int(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


def with_alpha(color: str, alpha: int) -> QColor:
    c = QColor(color)
    c.setAlpha(alpha)
    return c


# ---------------------------------------------------------------------------
# Worker: runs the imitation loop in a background thread
# ---------------------------------------------------------------------------

class ImitatorWorker(QObject):
    action = Signal(int, str, str)      # run_id, kind, text
    scheduled = Signal(int, float)      # run_id, delay seconds (starts now)
    user_wait = Signal(int, float)      # run_id, seconds until resume (<0 = done)
    finished = Signal(int, str)         # run_id, reason
    hotkey_toggle = Signal()
    hotkey_stop = Signal()

    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.guard_until = 0.0
        self.run_id = 0
        self._stop_evt: threading.Event | None = None
        self.paused = False
        self.activity_baseline = 0.0
        self.init_error: str | None = None
        self.simulator = None
        self.safety = None
        if core:
            try:
                self.simulator = core.InputSimulator(core.RandomizationEngine())
            except Exception as exc:
                self.init_error = str(exc)
            self.safety = core.SafetyListener(
                on_pause_toggle=lambda _p: self.hotkey_toggle.emit(),
                on_quit=self.hotkey_stop.emit,
            )
            self.safety.start()

    @property
    def hotkeys_available(self) -> bool:
        return bool(self.safety and self.safety.has_devices)

    def user_wait_remaining(self) -> float:
        """Seconds left until auto-pause ends (0 = the user is idle enough)."""
        s = self.settings
        if not (s.auto_pause and self.hotkeys_available):
            return 0.0
        last = self.safety.last_user_input
        if last <= self.activity_baseline:
            return 0.0
        return max(0.0, s.resume_after - (time.monotonic() - last))

    def _ignore_input_until_now(self, grace: float = 1.0) -> None:
        # The click on "Start"/"Resume" itself must not trigger auto-pause.
        self.activity_baseline = time.monotonic() + grace

    # -- control (GUI thread) ------------------------------------------------
    def start(self) -> int:
        self.request_stop()
        self.run_id += 1
        self.paused = False
        self._ignore_input_until_now()
        self._stop_evt = threading.Event()
        threading.Thread(target=self._run, args=(self.run_id, self._stop_evt), daemon=True).start()
        return self.run_id

    def request_stop(self) -> None:
        if self._stop_evt:
            self._stop_evt.set()
            self._stop_evt = None

    def set_paused(self, paused: bool) -> None:
        if self.paused and not paused:
            self._ignore_input_until_now()
        self.paused = paused
        if self.safety:
            self.safety.paused = paused

    def shutdown(self) -> None:
        self.request_stop()
        if self.safety:
            self.safety.stop()
        if self.simulator:
            self.simulator.close()

    # -- loop (worker thread) --------------------------------------------------
    def _wait(self, run_id: int, stop: threading.Event, delay: float) -> str:
        self.scheduled.emit(run_id, delay)
        end = time.monotonic() + delay
        while time.monotonic() < end:
            if stop.is_set():
                return "stopped"
            if self.paused:
                return "paused"
            if self.user_wait_remaining() > 0:
                return "user"
            stop.wait(max(0.0, min(0.1, end - time.monotonic())))
        return "stopped" if stop.is_set() else "done"

    def _pick(self, s: Settings) -> str | None:
        weights = {}
        if s.mouse:
            weights["mouse"] = 0.5
        if s.keys:
            weights["navigation"] = 0.4
        if s.pauses:
            weights["micro_pause"] = 0.1
        if not weights:
            return None
        names, w = zip(*weights.items())
        return random.choices(names, weights=w, k=1)[0]

    def _run(self, run_id: int, stop: threading.Event) -> None:
        delay = random.uniform(2.0, 4.0)   # give the user a moment after Start
        reason = "stopped"
        try:
            while True:
                outcome = self._wait(run_id, stop, delay)
                if outcome == "stopped":
                    break
                if outcome == "paused":
                    while self.paused and not stop.is_set():
                        stop.wait(0.2)
                    if stop.is_set():
                        break
                    delay = random.uniform(2.0, 4.0)
                    continue
                if outcome == "user":
                    self.action.emit(run_id, "auto", "Автопауза: ви користуєтесь комп'ютером")
                    while not stop.is_set() and not self.paused:
                        rem = self.user_wait_remaining()
                        if rem <= 0:
                            break
                        self.user_wait.emit(run_id, rem)
                        stop.wait(0.25)
                    self.user_wait.emit(run_id, -1.0)
                    if stop.is_set():
                        break
                    if not self.paused:
                        self.action.emit(run_id, "auto", "Ви неактивні — продовжую")
                    delay = random.uniform(1.5, 3.0)
                    continue

                s = self.settings
                choice = self._pick(s)
                if choice is None:
                    self.action.emit(run_id, "warn", "Усі типи дій вимкнено в налаштуваннях")
                    delay = 5.0
                    continue

                self.guard_until = float("inf")
                try:
                    if choice == "mouse":
                        kind, text = describe_mouse(self.simulator.move_mouse(
                            click_chance=0.25 if s.clicks else 0.0,
                            should_abort=lambda: stop.is_set() or self.paused
                            or self.user_wait_remaining() > 0))
                    elif choice == "navigation":
                        key = self.simulator.navigation_keystroke()
                        kind, text = "key", f"Клавіша {KEY_NAMES.get(key, key)}"
                    else:
                        extra = random.uniform(0.5, 2.5)
                        stop.wait(extra)
                        kind, text = "pause", f"Мікропауза {extra:.1f} с"
                finally:
                    self.guard_until = time.monotonic() + SYNTHETIC_GUARD_S

                if stop.is_set():
                    break
                self.action.emit(run_id, kind, text)
                lo, hi = sorted((s.min_delay, s.max_delay))
                delay = random.uniform(lo, hi)
        except Exception as exc:
            reason = f"error:{exc}"
        finally:
            self.guard_until = time.monotonic() + SYNTHETIC_GUARD_S
            self.finished.emit(run_id, reason)


class SyntheticInputGuard(QObject):
    """Eats clicks/keys that arrive right after the imitator's own actions."""

    EATEN = {
        QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
        QEvent.Type.MouseButtonDblClick, QEvent.Type.Wheel,
        QEvent.Type.KeyPress, QEvent.Type.KeyRelease,
    }

    def __init__(self, worker: ImitatorWorker | None):
        super().__init__()
        self.worker = worker

    def eventFilter(self, obj, event):
        if self.worker and event.type() in self.EATEN and time.monotonic() < self.worker.guard_until:
            return True
        return False


# ---------------------------------------------------------------------------
# Custom widgets
# ---------------------------------------------------------------------------

class PowerRing(QAbstractButton):
    """Big circular start/stop button with a countdown arc."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(236, 236)
        self.status = "stopped"
        self.remaining_fraction = 0.0
        self.remaining_s: float | None = None
        self.wait_fraction = 0.0
        self.wait_s: float | None = None
        self.phase = 0.0
        self._hover = 0.0
        self._hover_anim = QPropertyAnimation(self, b"hover", self)
        self._hover_anim.setDuration(160)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _get_hover(self):
        return self._hover

    def _set_hover(self, v):
        self._hover = v
        self.update()

    hover = Property(float, _get_hover, _set_hover)

    def enterEvent(self, e):
        self._hover_anim.stop()
        self._hover_anim.setEndValue(1.0)
        self._hover_anim.start()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover_anim.stop()
        self._hover_anim.setEndValue(0.0)
        self._hover_anim.start()
        super().leaveEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        c = QPointF(w / 2, h / 2)
        status = self.status
        color = QColor(STATUS_COLORS.get(status, SLATE))

        # breathing glow
        if status in ("running", "paused", "waiting"):
            breath = 0.5 + 0.5 * math.sin(self.phase) if status == "running" else 0.35
            glow = QRadialGradient(c, w / 2)
            base = QColor({"running": CYAN, "paused": AMBER, "waiting": BLUE}[status])
            glow.setColorAt(0.55, with_alpha(base.name(), int(40 + 45 * breath)))
            glow.setColorAt(1.0, with_alpha(base.name(), 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(glow)
            p.drawEllipse(c, w / 2, h / 2)

        ring_r = 92
        ring = QRectF(c.x() - ring_r, c.y() - ring_r, ring_r * 2, ring_r * 2)

        # track
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 18), 9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawEllipse(ring)

        # progress arc
        if status == "running" and self.remaining_fraction > 0.002:
            grad = QConicalGradient(c, 90)
            grad.setColorAt(0.0, QColor(CYAN))
            grad.setColorAt(0.5, QColor(VIOLET))
            grad.setColorAt(1.0, QColor(CYAN))
            p.setPen(QPen(QBrush(grad), 9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(ring, 90 * 16, int(-self.remaining_fraction * 360 * 16))
        elif status == "paused":
            p.setPen(QPen(with_alpha(AMBER, 120), 9))
            p.drawEllipse(ring)
        elif status == "waiting" and self.wait_fraction > 0.002:
            p.setPen(QPen(QColor(BLUE), 9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(ring, 90 * 16, int(-self.wait_fraction * 360 * 16))

        # inner disc
        disc_r = 74 + 2 * self._hover
        disc = QRectF(c.x() - disc_r, c.y() - disc_r, disc_r * 2, disc_r * 2)
        fill = QLinearGradient(disc.topLeft(), disc.bottomRight())
        top = mix(QColor(SURFACE_3), QColor("#2d3a5f"), self._hover)
        fill.setColorAt(0, top)
        fill.setColorAt(1, QColor(SURFACE_2))
        p.setPen(QPen(QColor(255, 255, 255, 22 + int(20 * self._hover)), 1))
        p.setBrush(fill)
        p.drawEllipse(disc)

        # content
        if status in ("running", "waiting"):
            waiting = status == "waiting"
            value = self.wait_s if waiting else self.remaining_s
            big = "…" if value is None else str(max(0, int(math.ceil(value) if waiting else round(value))))
            f = QFont(self.font())
            f.setPixelSize(50)
            f.setWeight(QFont.Weight.DemiBold)
            p.setFont(f)
            p.setPen(QColor(BLUE if waiting else TEXT))
            p.drawText(QRectF(disc.x(), c.y() - 44, disc.width(), 56), Qt.AlignmentFlag.AlignCenter, big)
            f2 = QFont(self.font())
            f2.setPixelSize(12)
            p.setFont(f2)
            p.setPen(QColor(MUTED))
            p.drawText(QRectF(disc.x(), c.y() + 12, disc.width(), 18), Qt.AlignmentFlag.AlignCenter,
                       "с до продовження" if waiting else "с до наступної дії")
            p.setPen(with_alpha(MUTED, int(110 + 140 * self._hover)))
            f2.setPixelSize(11)
            p.setFont(f2)
            p.drawText(QRectF(disc.x(), c.y() + 34, disc.width(), 16), Qt.AlignmentFlag.AlignCenter,
                       "натисніть, щоб зупинити")
        elif status == "paused":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(AMBER))
            bw, bh = 11, 38
            p.drawRoundedRect(QRectF(c.x() - 15, c.y() - 30, bw, bh), 4, 4)
            p.drawRoundedRect(QRectF(c.x() + 4, c.y() - 30, bw, bh), 4, 4)
            f = QFont(self.font())
            f.setPixelSize(13)
            f.setWeight(QFont.Weight.DemiBold)
            p.setFont(f)
            p.setPen(QColor(AMBER))
            p.drawText(QRectF(disc.x(), c.y() + 18, disc.width(), 20), Qt.AlignmentFlag.AlignCenter, "Пауза")
        else:
            disabled = status == "error"
            glyph = QColor(FAINT if disabled else mix(QColor(MUTED), QColor(TEXT), self._hover))
            if not disabled and self._hover > 0:
                glyph = mix(glyph, QColor(CYAN), self._hover * 0.8)
            pen = QPen(glyph, 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            gr = 24
            gy = c.y() - 10
            p.drawArc(QRectF(c.x() - gr, gy - gr, gr * 2, gr * 2), 55 * 16, -290 * 16)
            p.drawLine(QPointF(c.x(), gy - gr - 4), QPointF(c.x(), gy - 2))
            f = QFont(self.font())
            f.setPixelSize(13)
            f.setWeight(QFont.Weight.DemiBold)
            p.setFont(f)
            p.setPen(glyph)
            p.drawText(QRectF(disc.x(), c.y() + 26, disc.width(), 20), Qt.AlignmentFlag.AlignCenter,
                       "Недоступно" if disabled else "Запустити")
        p.end()


class StatusPill(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.status = "stopped"
        self.phase = 0.0
        self.setFixedHeight(28)
        self._update_width()

    def set_status(self, status: str):
        self.status = status
        self._update_width()
        self.update()

    def _update_width(self):
        f = QFont(self.font())
        f.setPixelSize(12)
        f.setWeight(QFont.Weight.DemiBold)
        self.setFixedWidth(QFontMetrics(f).horizontalAdvance(STATUS_TEXT[self.status]) + 40)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = STATUS_COLORS[self.status]
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        p.setPen(QPen(with_alpha(color, 70), 1))
        p.setBrush(with_alpha(color, 28))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        cy = self.height() / 2
        if self.status == "running":
            t = (math.sin(self.phase) + 1) / 2
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(with_alpha(color, int(90 * (1 - t))))
            p.drawEllipse(QPointF(16, cy), 4 + 4 * t, 4 + 4 * t)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color))
        p.drawEllipse(QPointF(16, cy), 4, 4)
        f = QFont(self.font())
        f.setPixelSize(12)
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(QColor(color))
        p.drawText(QRectF(27, 0, self.width() - 30, self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, STATUS_TEXT[self.status])
        p.end()


class Toggle(QAbstractButton):
    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._knob = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(170)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def sizeHint(self):
        return QSize(42, 24)

    def _get_knob(self):
        return self._knob

    def _set_knob(self, v):
        self._knob = v
        self.update()

    knob = Property(float, _get_knob, _set_knob)

    def _animate(self, checked):
        self._anim.stop()
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            p.setOpacity(0.35)
        r = QRectF(1, 1, self.width() - 2, self.height() - 2)
        off = QColor(SURFACE_3)
        grad = QLinearGradient(r.topLeft(), r.topRight())
        grad.setColorAt(0, mix(off, QColor(CYAN), self._knob))
        grad.setColorAt(1, mix(off, QColor(VIOLET), self._knob))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        x = r.x() + 3 + (r.width() - d - 6) * self._knob
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRectF(x, r.y() + 3, d, d))
        p.end()


class NoWheelSlider(QSlider):
    def wheelEvent(self, e):
        e.ignore()


class LogDelegate(QStyledItemDelegate):
    def __init__(self, mono: QFont, parent=None):
        super().__init__(parent)
        self.mono = mono

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 30)

    def paint(self, p, option, index):
        ts, kind, text = index.data(Qt.ItemDataRole.UserRole)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = option.rect
        if option.state & QStyle.StateFlag.State_MouseOver:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 8))
            p.drawRoundedRect(QRectF(r).adjusted(2, 1, -2, -1), 8, 8)
        p.setFont(self.mono)
        p.setPen(QColor(FAINT))
        p.drawText(QRectF(r.x() + 12, r.y(), 64, r.height()), Qt.AlignmentFlag.AlignVCenter, ts)
        color = QColor(KIND_COLORS.get(kind, MUTED))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(with_alpha(color.name(), 45))
        p.drawEllipse(QPointF(r.x() + 84, r.center().y() + 0.5), 6, 6)
        p.setBrush(color)
        p.drawEllipse(QPointF(r.x() + 84, r.center().y() + 0.5), 3, 3)
        f = QFont(option.font)
        f.setPixelSize(13)
        p.setFont(f)
        p.setPen(QColor(TEXT if kind not in ("warn", "error") else color))
        tr = QRectF(r.x() + 98, r.y(), r.width() - 106, r.height())
        p.drawText(tr, Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, int(tr.width())))
        p.restore()


class LogList(QListWidget):
    def paintEvent(self, e):
        super().paintEvent(e)
        if self.count() == 0:
            p = QPainter(self.viewport())
            p.setPen(QColor(FAINT))
            f = QFont(self.font())
            f.setPixelSize(13)
            p.setFont(f)
            p.drawText(self.viewport().rect(), Qt.AlignmentFlag.AlignCenter,
                       "Тут з'являтимуться дії імітатора")
            p.end()


def make_card(obj_name="card") -> QFrame:
    f = QFrame()
    f.setObjectName(obj_name)
    return f


class StatCard(QFrame):
    def __init__(self, title: str):
        super().__init__()
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 11, 14, 11)
        lay.setSpacing(2)
        self.title = QLabel(title.upper())
        self.title.setObjectName("statTitle")
        self.value = QLabel("—")
        self.value.setObjectName("statValue")
        self.sub = QLabel(" ")
        self.sub.setObjectName("statSub")
        for w in (self.title, self.value, self.sub):
            lay.addWidget(w)


def icon_with_dot(base: QIcon, color: str | None, size=64) -> QIcon:
    pm = base.pixmap(size, size)
    if color:
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = size * 0.2
        cx, cy = size - r - 1, size - r - 1
        p.setPen(QPen(QColor(BG), size * 0.06))
        p.setBrush(QColor(color))
        p.drawEllipse(QPointF(cx, cy), r, r)
        p.end()
    return QIcon(pm)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QWidget):
    def __init__(self, app_icon: QIcon):
        super().__init__()
        self.settings = Settings.load()
        self.app_icon = app_icon
        self.status = "stopped" if core else "error"
        self.run_id = -1
        self.run_started: float | None = None
        self.paused_total = 0.0
        self.paused_since: float | None = None
        self.deadline: datetime | None = None
        self.action_count = 0
        self.last_action: tuple[float, str] | None = None
        self.next_at: float | None = None
        self.next_delay = 0.0
        self.user_wait_until: float | None = None
        self._quitting = False
        self._frozen_runtime = 0.0

        self.worker = ImitatorWorker(self.settings) if core else None
        self.init_error = CORE_ERROR or (self.worker.init_error if self.worker else None)
        if self.init_error:
            self.status = "error"
        if self.worker:
            self.worker.action.connect(self._on_action)
            self.worker.scheduled.connect(self._on_scheduled)
            self.worker.user_wait.connect(self._on_user_wait)
            self.worker.finished.connect(self._on_finished)
            self.worker.hotkey_toggle.connect(self._on_hotkey_toggle)
            self.worker.hotkey_stop.connect(lambda: self.stop("hotkey"))

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon)
        self.setObjectName("root")
        self.resize(460, 880)
        self.setMinimumSize(420, 760)
        self._build()
        self._build_tray()

        self.anim_timer = QTimer(self)
        self.anim_timer.setInterval(33)
        self.anim_timer.timeout.connect(self._tick_anim)
        self.anim_timer.start()
        self.slow_timer = QTimer(self)
        self.slow_timer.setInterval(500)
        self.slow_timer.timeout.connect(self._tick_slow)
        self.slow_timer.start()

        self._apply_status()
        self._tick_slow()

        if CORE_ERROR:
            self.log("error", f"Ядро не завантажилось: {CORE_ERROR}")
        elif self.init_error:
            self.log("error", self.init_error)
        else:
            self.log("info", "Готово до запуску")
            if self.worker and not self.worker.hotkeys_available:
                self.log("warn", "Гарячі клавіші й автопауза недоступні: немає доступу до /dev/input")
            if self.settings.autostart:
                QTimer.singleShot(600, self.start)

    # -- layout ----------------------------------------------------------------
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 14)
        root.setSpacing(14)

        # header
        header = QHBoxLayout()
        header.setSpacing(12)
        logo = QLabel()
        logo.setPixmap(self.app_icon.pixmap(40, 40))
        logo.setFixedSize(40, 40)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        t = QLabel(APP_NAME)
        t.setObjectName("title")
        st = QLabel("Тримає сесію активною, поки ви не поруч")
        st.setObjectName("subtitle")
        titles.addWidget(t)
        titles.addWidget(st)
        self.pill = StatusPill()
        header.addWidget(logo)
        header.addLayout(titles, 1)
        header.addWidget(self.pill, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(header)

        # hero
        hero = QVBoxLayout()
        hero.setSpacing(8)
        self.ring = PowerRing()
        self.ring.clicked.connect(self.toggle_run)
        self.ring.setEnabled(not self.init_error)
        hero.addWidget(self.ring, 0, Qt.AlignmentFlag.AlignHCenter)
        self.last_label = QLabel(" ")
        self.last_label.setObjectName("lastAction")
        self.last_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero.addWidget(self.last_label)
        btns = QHBoxLayout()
        btns.addStretch(1)
        self.pause_btn = QPushButton("Пауза")
        self.pause_btn.setObjectName("secondary")
        self.pause_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pause_btn.clicked.connect(self.toggle_pause)
        btns.addWidget(self.pause_btn)
        btns.addStretch(1)
        hero.addLayout(btns)
        root.addLayout(hero)

        # stats
        stats = QHBoxLayout()
        stats.setSpacing(10)
        self.stat_time = StatCard("Час роботи")
        self.stat_actions = StatCard("Дій")
        self.stat_stop = StatCard("Зупинка")
        for s in (self.stat_time, self.stat_actions, self.stat_stop):
            stats.addWidget(s, 1)
        root.addLayout(stats)

        # duration
        dur_row = QVBoxLayout()
        dur_row.setSpacing(6)
        dl = QLabel("ТРИВАЛІСТЬ")
        dl.setObjectName("section")
        dur_row.addWidget(dl)
        seg = make_card("segment")
        seg_l = QHBoxLayout(seg)
        seg_l.setContentsMargins(4, 4, 4, 4)
        seg_l.setSpacing(4)
        self.dur_group = QButtonGroup(self)
        for minutes, label in DURATIONS:
            b = QPushButton(label)
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setChecked(minutes == self.settings.duration_min)
            self.dur_group.addButton(b, minutes)
            seg_l.addWidget(b, 1)
        if self.dur_group.checkedButton() is None:
            self.dur_group.button(0).setChecked(True)
            self.settings.duration_min = 0
        self.dur_group.idClicked.connect(self._on_duration)
        dur_row.addWidget(seg)
        root.addLayout(dur_row)

        # tabs
        tabs = make_card("segment")
        tabs_l = QHBoxLayout(tabs)
        tabs_l.setContentsMargins(4, 4, 4, 4)
        tabs_l.setSpacing(4)
        self.tab_group = QButtonGroup(self)
        for i, label in enumerate(("Журнал", "Налаштування")):
            b = QPushButton(label)
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setChecked(i == 0)
            self.tab_group.addButton(b, i)
            tabs_l.addWidget(b, 1)
        root.addWidget(tabs)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_log())
        self.stack.addWidget(self._build_settings())
        self.tab_group.idClicked.connect(self.stack.setCurrentIndex)
        root.addWidget(self.stack, 1)

        # footer
        footer = QHBoxLayout()
        footer.setSpacing(6)
        for keys, what in (("Ctrl+Alt+S", "пауза"), ("Ctrl+Alt+Q", "стоп")):
            k = QLabel(keys)
            k.setObjectName("kbd")
            w = QLabel(what)
            w.setObjectName("footer")
            footer.addWidget(k)
            footer.addWidget(w)
            footer.addSpacing(6)
        footer.addStretch(1)
        self.hotkey_state = QLabel()
        self.hotkey_state.setObjectName("footer")
        ok = bool(self.worker and self.worker.hotkeys_available)
        self.hotkey_state.setText(("● " if ok else "▲ ") + ("клавіші й автопауза активні" if ok else "клавіші й автопауза вимкнені"))
        self.hotkey_state.setStyleSheet(f"color: {GREEN if ok else AMBER};")
        self.hotkey_state.setToolTip(
            "Клавіатура, миша й тачпад читаються з /dev/input (evdev) — для гарячих клавіш і автопаузи." if ok else
            "Немає доступу до /dev/input. Додайте користувача до групи input:\n"
            "sudo usermod -aG input $USER — і перезайдіть у сесію.")
        footer.addWidget(self.hotkey_state)
        root.addLayout(footer)
        self.footer_hint = QLabel()
        self.footer_hint.setObjectName("footerFaint")
        root.addWidget(self.footer_hint)
        self._sync_settings_ui()

    def _build_log(self) -> QWidget:
        card = make_card()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(4, 6, 4, 6)
        self.log_list = LogList()
        mono = QFont("Fira Mono")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPixelSize(12)
        self.log_list.setItemDelegate(LogDelegate(mono, self.log_list))
        self.log_list.setMouseTracking(True)
        self.log_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.log_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.log_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.log_list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        lay.addWidget(self.log_list)
        return card

    def _row(self, title: str, subtitle: str, widget: QWidget) -> QWidget:
        w = QWidget()
        l = QHBoxLayout(w)
        l.setContentsMargins(16, 10, 16, 10)
        l.setSpacing(12)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        a = QLabel(title)
        a.setObjectName("rowTitle")
        b = QLabel(subtitle)
        b.setObjectName("rowSub")
        b.setWordWrap(True)
        texts.addWidget(a)
        texts.addWidget(b)
        l.addLayout(texts, 1)
        l.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)
        return w

    def _divider(self) -> QFrame:
        d = QFrame()
        d.setObjectName("divider")
        d.setFixedHeight(1)
        return d

    def _build_settings(self) -> QWidget:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setObjectName("transparent")
        v = QVBoxLayout(inner)
        v.setContentsMargins(0, 0, 4, 0)
        v.setSpacing(10)

        # interval card
        ic = make_card()
        il = QVBoxLayout(ic)
        il.setContentsMargins(16, 12, 16, 14)
        il.setSpacing(8)
        head = QHBoxLayout()
        a = QLabel("Інтервал між діями")
        a.setObjectName("rowTitle")
        self.interval_value = QLabel()
        self.interval_value.setObjectName("accentValue")
        head.addWidget(a)
        head.addStretch(1)
        head.addWidget(self.interval_value)
        il.addLayout(head)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        self.min_slider = NoWheelSlider(Qt.Orientation.Horizontal)
        self.min_slider.setRange(2, 120)
        self.min_slider.setValue(self.settings.min_delay)
        self.max_slider = NoWheelSlider(Qt.Orientation.Horizontal)
        self.max_slider.setRange(5, 300)
        self.max_slider.setValue(self.settings.max_delay)
        for row, (label, slider) in enumerate((("від", self.min_slider), ("до", self.max_slider))):
            lab = QLabel(label)
            lab.setObjectName("rowSub")
            slider.setCursor(Qt.CursorShape.PointingHandCursor)
            grid.addWidget(lab, row, 0)
            grid.addWidget(slider, row, 1)
        il.addLayout(grid)
        hint = QLabel("Випадкова пауза в цих межах — без фіксованого ритму, як у живої людини.")
        hint.setObjectName("rowSub")
        hint.setWordWrap(True)
        il.addWidget(hint)
        self.min_slider.valueChanged.connect(self._on_min)
        self.max_slider.valueChanged.connect(self._on_max)
        v.addWidget(ic)

        # auto-pause card
        apc = make_card()
        apl = QVBoxLayout(apc)
        apl.setContentsMargins(0, 4, 0, 10)
        apl.setSpacing(0)
        self.t_autopause = Toggle(self.settings.auto_pause)
        apl.addWidget(self._row("Автопауза, коли ви працюєте",
                                "Рух миші, тачпад чи клавіші одразу ставлять імітацію на паузу", self.t_autopause))
        res = QWidget()
        rl = QHBoxLayout(res)
        rl.setContentsMargins(16, 0, 16, 0)
        rl.setSpacing(12)
        rlab = QLabel("продовжити через")
        rlab.setObjectName("rowSub")
        self.resume_slider = NoWheelSlider(Qt.Orientation.Horizontal)
        self.resume_slider.setRange(2, 60)   # x5 seconds -> 10..300 s
        self.resume_slider.setValue(max(2, min(60, round(self.settings.resume_after / 5))))
        self.resume_slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self.resume_value = QLabel()
        self.resume_value.setObjectName("accentValue")
        self.resume_value.setMinimumWidth(56)
        self.resume_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        rl.addWidget(rlab)
        rl.addWidget(self.resume_slider, 1)
        rl.addWidget(self.resume_value)
        apl.addWidget(res)
        self.t_autopause.toggled.connect(lambda c: self._set("auto_pause", c))
        self.resume_slider.valueChanged.connect(lambda v: self._set("resume_after", v * 5))
        if not (self.worker and self.worker.hotkeys_available):
            self.t_autopause.setEnabled(False)
            self.resume_slider.setEnabled(False)
        v.addWidget(apc)

        # actions card
        ac = make_card()
        al = QVBoxLayout(ac)
        al.setContentsMargins(0, 4, 0, 4)
        al.setSpacing(0)
        self.t_mouse = Toggle(self.settings.mouse)
        self.t_clicks = Toggle(self.settings.clicks)
        self.t_keys = Toggle(self.settings.keys)
        self.t_pauses = Toggle(self.settings.pauses)
        rows = [
            ("Рух миші", "Плавна траєкторія в центральній зоні екрана (15–85%)", self.t_mouse),
            ("Кліки та прокрутка", "Інколи після руху миші, лише в безпечній зоні", self.t_clicks),
            ("Навігаційні клавіші", "Shift, Ctrl, ↑ ↓, Page Up/Down, Esc — нічого не змінюють", self.t_keys),
            ("Мікропаузи", "Коротке «завмирання», щоб ритм був природнішим", self.t_pauses),
        ]
        for i, (title, sub, tog) in enumerate(rows):
            if i:
                al.addWidget(self._divider())
            al.addWidget(self._row(title, sub, tog))
        self.t_mouse.toggled.connect(lambda c: self._set("mouse", c))
        self.t_clicks.toggled.connect(lambda c: self._set("clicks", c))
        self.t_keys.toggled.connect(lambda c: self._set("keys", c))
        self.t_pauses.toggled.connect(lambda c: self._set("pauses", c))
        v.addWidget(ac)

        # app card
        pc = make_card()
        pl = QVBoxLayout(pc)
        pl.setContentsMargins(0, 4, 0, 4)
        pl.setSpacing(0)
        self.t_autostart = Toggle(self.settings.autostart)
        self.t_tray = Toggle(self.settings.close_to_tray)
        pl.addWidget(self._row("Запускати одразу", "Починати імітацію при відкритті програми", self.t_autostart))
        pl.addWidget(self._divider())
        pl.addWidget(self._row("Згортати в трей", "Закриття вікна не зупиняє роботу", self.t_tray))
        self.t_autostart.toggled.connect(lambda c: self._set("autostart", c))
        self.t_tray.toggled.connect(lambda c: self._set("close_to_tray", c))
        v.addWidget(pc)
        v.addStretch(1)

        area.setWidget(inner)
        self._sync_settings_ui()
        return area

    def _build_tray(self):
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.t_tray.setEnabled(False)
            return
        self.tray = QSystemTrayIcon(icon_with_dot(self.app_icon, None), self)
        self.tray_menu = QMenu()
        self.tray_status = QAction("", self.tray_menu)
        self.tray_status.setEnabled(False)
        self.tray_run = QAction("Запустити", self.tray_menu)
        self.tray_run.triggered.connect(self.toggle_run)
        self.tray_pause = QAction("Пауза", self.tray_menu)
        self.tray_pause.triggered.connect(self.toggle_pause)
        show = QAction("Показати вікно", self.tray_menu)
        show.triggered.connect(self.show_window)
        quit_ = QAction("Вийти", self.tray_menu)
        quit_.triggered.connect(self.quit)
        for a in (self.tray_status, None, self.tray_run, self.tray_pause, show, None, quit_):
            self.tray_menu.addSeparator() if a is None else self.tray_menu.addAction(a)
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    # -- settings handlers ---------------------------------------------------------
    def _set(self, key: str, value):
        setattr(self.settings, key, value)
        self.settings.save()
        self._sync_settings_ui()

    def _on_min(self, v: int):
        if self.max_slider.value() < v + 3:
            self.max_slider.setValue(v + 3)
        self._set("min_delay", v)

    def _on_max(self, v: int):
        if self.min_slider.value() > v - 3:
            self.min_slider.setValue(max(self.min_slider.minimum(), v - 3))
        self._set("max_delay", v)

    def _sync_settings_ui(self):
        self.interval_value.setText(f"{self.settings.min_delay}–{self.settings.max_delay} с")
        self.t_clicks.setEnabled(self.settings.mouse)
        self.resume_value.setText(fmt_human(self.settings.resume_after) if self.settings.resume_after >= 60
                                  and self.settings.resume_after % 60 == 0 else f"{self.settings.resume_after} с")
        ap = self.settings.auto_pause and bool(self.worker and self.worker.hotkeys_available)
        self.resume_slider.setEnabled(ap)
        if hasattr(self, "footer_hint"):
            self.footer_hint.setText(
                "Візьметеся за мишу чи клавіатуру — імітація сама стане на паузу" if ap
                else "Автопаузу вимкнено — зупиняйте кнопкою або Ctrl+Alt+Q")

    def _on_duration(self, minutes: int):
        self.settings.duration_min = minutes
        self.settings.save()
        if self.status in ("running", "paused"):
            self.deadline = datetime.now() + timedelta(minutes=minutes) if minutes else None
            self.log("info", f"Автозупинка через {fmt_human(minutes * 60)}" if minutes else "Автозупинку вимкнено")
        self._tick_slow()

    # -- control -------------------------------------------------------------------
    def toggle_run(self):
        if self.status in ("running", "paused"):
            self.stop("user")
        else:
            self.start()

    def start(self):
        if not self.worker or self.status in ("running", "paused"):
            return
        self.worker.set_paused(False)
        self.run_id = self.worker.start()
        self.run_started = time.monotonic()
        self.paused_total = 0.0
        self.paused_since = None
        self.action_count = 0
        self.last_action = None
        self.next_at = None
        self.user_wait_until = None
        m = self.settings.duration_min
        self.deadline = datetime.now() + timedelta(minutes=m) if m else None
        self.status = "running"
        self.log("info", "Імітацію запущено" + (f" на {fmt_human(m * 60)}" if m else ""))
        self._apply_status()

    def stop(self, reason: str = "user"):
        if not self.worker or self.status not in ("running", "paused"):
            return
        self.worker.request_stop()
        self.worker.set_paused(False)
        self._finish_run()
        messages = {
            "user": ("info", "Імітацію зупинено"),
            "hotkey": ("info", "Зупинено гарячою клавішею Ctrl+Alt+Q"),
            "timer": ("info", "Час вийшов — імітацію зупинено"),
        }
        kind, text = messages.get(reason, ("info", "Імітацію зупинено"))
        self.log(kind, text)
        if reason == "timer":
            self.notify("Час вийшов", "Імітацію активності зупинено за таймером.")

    def _finish_run(self):
        self.status = "stopped"
        self.next_at = None
        self.user_wait_until = None
        if self.paused_since is not None:
            self.paused_total += time.monotonic() - self.paused_since
            self.paused_since = None
        self._frozen_runtime = self._runtime()
        self.run_started = None
        self.deadline = None
        self._apply_status()

    def toggle_pause(self):
        if self.status == "running":
            self._set_paused(True)
        elif self.status == "paused":
            self._set_paused(False)

    def _set_paused(self, paused: bool, source: str = ""):
        if not self.worker:
            return
        self.worker.set_paused(paused)
        if paused and self.status == "running":
            self.status = "paused"
            self.paused_since = time.monotonic()
            self.next_at = None
            self.user_wait_until = None
            self.log("warn", "Пауза" + (f" ({source})" if source else ""))
        elif not paused and self.status == "paused":
            self.status = "running"
            if self.paused_since is not None:
                self.paused_total += time.monotonic() - self.paused_since
            self.paused_since = None
            self.log("info", "Продовжено" + (f" ({source})" if source else ""))
        self._apply_status()

    def _on_hotkey_toggle(self):
        # SafetyListener already flipped its own flag; we are the source of truth.
        if self.status == "stopped":
            self.start()
        elif self.status == "running":
            self._set_paused(True, "Ctrl+Alt+S")
        elif self.status == "paused":
            self._set_paused(False, "Ctrl+Alt+S")

    # -- worker signals -----------------------------------------------------------
    def _on_action(self, run_id: int, kind: str, text: str):
        if run_id != self.run_id or self.status == "stopped":
            return
        if kind not in ("warn", "error", "info", "auto"):
            self.action_count += 1
            self.last_action = (time.monotonic(), text)
        self.log(kind, text)
        self._tick_slow()

    def _on_scheduled(self, run_id: int, delay: float):
        if run_id != self.run_id or self.status != "running":
            return
        self.next_delay = delay
        self.next_at = time.monotonic() + delay

    def _on_user_wait(self, run_id: int, remaining: float):
        if run_id != self.run_id or self.status != "running":
            return
        was = self.user_wait_until is not None
        self.user_wait_until = None if remaining < 0 else time.monotonic() + remaining
        if remaining >= 0:
            self.next_at = None
        if was != (self.user_wait_until is not None):
            self._apply_status()

    def _on_finished(self, run_id: int, reason: str):
        if run_id != self.run_id:
            return
        if self.worker and self.worker.safety:
            self.worker.safety.should_quit = False
        if self.status == "stopped":
            return
        self._finish_run()
        if reason.startswith("error:"):
            self.log("error", f"Помилка: {reason[6:]}")
            self.notify("Помилка", reason[6:])

    # -- presentation ------------------------------------------------------------------
    def _runtime(self) -> float:
        if self.run_started is None:
            return self._frozen_runtime
        paused = self.paused_total
        if self.paused_since is not None:
            paused += time.monotonic() - self.paused_since
        return time.monotonic() - self.run_started - paused

    def display_status(self) -> str:
        if self.status == "running" and self.user_wait_until is not None:
            return "waiting"
        return self.status

    def _apply_status(self):
        s = self.display_status()
        self.pill.set_status(s)
        self.ring.status = s
        self.ring.setToolTip({"running": "Зупинити", "waiting": "Зупинити", "paused": "Зупинити",
                              "stopped": "Запустити"}.get(s, self.init_error or ""))
        self.pause_btn.setEnabled(s in ("running", "waiting", "paused"))
        self.pause_btn.setText("Продовжити" if s == "paused" else "Пауза")
        self.pause_btn.setProperty("accent", s == "paused")
        self.pause_btn.style().unpolish(self.pause_btn)
        self.pause_btn.style().polish(self.pause_btn)
        if self.tray:
            dot = {"running": GREEN, "waiting": BLUE, "paused": AMBER, "error": ROSE}.get(s)
            self.tray.setIcon(icon_with_dot(self.app_icon, dot))
            self.tray_status.setText(f"{APP_NAME}: {STATUS_TEXT[s].lower()}")
            self.tray_run.setText("Зупинити" if s in ("running", "waiting", "paused") else "Запустити")
            self.tray_run.setEnabled(s != "error")
            self.tray_pause.setText("Продовжити" if s == "paused" else "Пауза")
            self.tray_pause.setEnabled(s in ("running", "waiting", "paused"))
        self.setWindowTitle(f"{APP_NAME} — {STATUS_TEXT[s]}")
        self.ring.update()
        self._tick_slow()

    def _tick_anim(self):
        self.ring.phase += 0.08
        self.pill.phase += 0.08
        if self.status == "running" and self.next_at is not None and self.next_delay > 0:
            rem = max(0.0, self.next_at - time.monotonic())
            self.ring.remaining_s = rem
            self.ring.remaining_fraction = rem / self.next_delay
        else:
            self.ring.remaining_s = None
            self.ring.remaining_fraction = 0.0
        if self.user_wait_until is not None:
            rem = max(0.0, self.user_wait_until - time.monotonic())
            self.ring.wait_s = rem
            self.ring.wait_fraction = min(1.0, rem / max(1, self.settings.resume_after))
        else:
            self.ring.wait_s = None
            self.ring.wait_fraction = 0.0
        if self.status in ("running", "paused") or self.ring.underMouse():
            self.ring.update()
        if self.status == "running":
            self.pill.update()

    def _tick_slow(self):
        # auto-stop
        if self.deadline and self.status in ("running", "paused") and datetime.now() >= self.deadline:
            self.stop("timer")

        runtime = self._runtime()
        self.stat_time.value.setText(fmt_duration(runtime))
        self.stat_time.sub.setText({"running": "триває", "waiting": "автопауза", "paused": "на паузі"}.get(
            self.display_status(), "остання сесія" if runtime else " "))
        self.stat_actions.value.setText(str(self.action_count))
        self.stat_actions.sub.setText("за сесію")
        if self.status in ("running", "paused") and self.deadline:
            left = (self.deadline - datetime.now()).total_seconds()
            self.stat_stop.value.setText(self.deadline.strftime("%H:%M"))
            self.stat_stop.sub.setText(f"через {fmt_human(left)}")
        elif self.settings.duration_min:
            self.stat_stop.value.setText(fmt_human(self.settings.duration_min * 60))
            self.stat_stop.sub.setText("після запуску")
        else:
            self.stat_stop.value.setText("∞")
            self.stat_stop.sub.setText("вручну")

        if self.status == "error":
            self.last_label.setText("Імітація недоступна — див. журнал")
        elif self.display_status() == "waiting":
            self.last_label.setText("Ви за комп'ютером — продовжу, щойно відійдете")
        elif self.last_action and self.status != "stopped":
            at, text = self.last_action
            self.last_label.setText(f"{text}  ·  {fmt_ago(time.monotonic() - at)}")
        elif self.status == "running":
            self.last_label.setText("Перша дія за кілька секунд…")
        elif self.status == "paused":
            self.last_label.setText("Натисніть «Продовжити» або Ctrl+Alt+S")
        else:
            self.last_label.setText("Натисніть кнопку, щоб почати")

        if self.tray:
            tip = f"{APP_NAME} — {STATUS_TEXT[self.display_status()]}"
            if self.user_wait_until is not None:
                tip += f"\nПродовжу через {max(0, int(math.ceil(self.user_wait_until - time.monotonic())))} с бездіяльності"
            elif self.status == "running" and self.next_at:
                tip += f"\nНаступна дія через {max(0, int(self.next_at - time.monotonic()))} с"
            if self.status in ("running", "paused"):
                tip += f"\nДій: {self.action_count} · {fmt_duration(runtime)}"
            self.tray.setToolTip(tip)

    def log(self, kind: str, text: str):
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, (datetime.now().strftime("%H:%M:%S"), kind, text))
        item.setToolTip(text)
        self.log_list.insertItem(0, item)
        while self.log_list.count() > 300:
            self.log_list.takeItem(self.log_list.count() - 1)

    def notify(self, title: str, text: str):
        if self.tray:
            self.tray.showMessage(title, text, self.app_icon, 6000)

    # -- window / tray ----------------------------------------------------------------
    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self.show_window()

    def show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, e):
        if not self._quitting and self.tray and self.settings.close_to_tray:
            e.ignore()
            self.hide()
            if not self.settings.tray_hint_shown:
                self.notify(APP_NAME, "Програма працює у треї. Клацніть іконку, щоб відкрити вікно.")
                self.settings.tray_hint_shown = True
                self.settings.save()
            return
        self._shutdown()
        e.accept()
        QApplication.quit()

    def quit(self):
        self._quitting = True
        self._shutdown()
        QApplication.quit()

    def _shutdown(self):
        self.settings.save()
        if self.worker:
            self.worker.shutdown()
        if self.tray:
            self.tray.hide()


# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------

QSS = f"""
QWidget#root {{ background: {BG}; }}
QWidget {{ color: {TEXT}; }}
QWidget#transparent, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollArea {{ border: none; }}
QLabel {{ background: transparent; }}
QLabel#title {{ font-size: 17px; font-weight: 700; }}
QLabel#subtitle {{ color: {MUTED}; font-size: 12px; }}
QLabel#lastAction {{ color: {MUTED}; font-size: 12px; min-height: 18px; }}
QLabel#section {{ color: {FAINT}; font-size: 11px; font-weight: 700; letter-spacing: 1px; }}
QLabel#statTitle {{ color: {FAINT}; font-size: 10px; font-weight: 700; letter-spacing: 1px; }}
QLabel#statValue {{ font-size: 20px; font-weight: 600; }}
QLabel#statSub {{ color: {MUTED}; font-size: 11px; }}
QLabel#rowTitle {{ font-size: 14px; font-weight: 600; }}
QLabel#rowSub {{ color: {MUTED}; font-size: 12px; }}
QLabel#accentValue {{ color: {CYAN}; font-size: 14px; font-weight: 600; }}
QLabel#footer {{ color: {MUTED}; font-size: 11px; }}
QLabel#footerFaint {{ color: {FAINT}; font-size: 11px; }}
QLabel#kbd {{
    color: {TEXT}; font-size: 11px; font-weight: 600;
    background: {SURFACE_2}; border: 1px solid rgba(255,255,255,20);
    border-bottom: 2px solid rgba(0,0,0,120); border-radius: 5px; padding: 1px 6px;
}}
QFrame#card {{ background: {SURFACE}; border: 1px solid rgba(255,255,255,15); border-radius: 14px; }}
QFrame#segment {{ background: {SURFACE}; border: 1px solid rgba(255,255,255,15); border-radius: 12px; }}
QFrame#divider {{ background: rgba(255,255,255,12); margin: 0 16px; }}
QPushButton#chip {{
    background: transparent; color: {MUTED}; border: none; border-radius: 9px;
    padding: 7px 4px; font-size: 13px; font-weight: 600;
}}
QPushButton#chip:hover {{ color: {TEXT}; background: rgba(255,255,255,10); }}
QPushButton#chip:checked {{ color: {TEXT}; background: {SURFACE_3}; }}
QPushButton#secondary {{
    background: {SURFACE_2}; color: {TEXT}; border: 1px solid rgba(255,255,255,22);
    border-radius: 17px; padding: 8px 26px; font-size: 13px; font-weight: 600; min-width: 90px;
}}
QPushButton#secondary:hover {{ background: {SURFACE_3}; }}
QPushButton#secondary:disabled {{ color: {FAINT}; background: transparent; border-color: rgba(255,255,255,10); }}
QPushButton#secondary[accent="true"] {{ color: #1a1300; background: {AMBER}; border-color: {AMBER}; }}
QPushButton#secondary[accent="true"]:hover {{ background: #fcd34d; }}
QSlider::groove:horizontal {{ height: 6px; background: {SURFACE_3}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {CYAN}, stop:1 {VIOLET}); border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: #ffffff; width: 16px; height: 16px; margin: -5px 0; border-radius: 8px;
}}
QListWidget {{ background: transparent; border: none; outline: 0; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 4px 1px; }}
QScrollBar::handle:vertical {{ background: rgba(255,255,255,30); border-radius: 3px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: rgba(255,255,255,55); }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
QToolTip {{
    background: {SURFACE_2}; color: {TEXT}; border: 1px solid rgba(255,255,255,30);
    border-radius: 6px; padding: 6px 8px;
}}
QMenu {{ background: {SURFACE}; border: 1px solid rgba(255,255,255,25); border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 7px 18px; border-radius: 6px; color: {TEXT}; }}
QMenu::item:selected {{ background: {SURFACE_3}; }}
QMenu::item:disabled {{ color: {MUTED}; }}
QMenu::separator {{ height: 1px; background: rgba(255,255,255,15); margin: 5px 8px; }}
"""


def pick_font() -> QFont:
    families = set(QFontDatabase.families())
    for name in ("Inter", "Fira Sans", "Open Sans", "Noto Sans", "Ubuntu", "Cantarell"):
        if name in families:
            f = QFont(name)
            break
    else:
        f = QFont()
    f.setPixelSize(13)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return f


def dark_palette() -> QPalette:
    pal = QPalette()
    for role, color in (
        (QPalette.ColorRole.Window, BG), (QPalette.ColorRole.Base, SURFACE),
        (QPalette.ColorRole.AlternateBase, SURFACE_2), (QPalette.ColorRole.Text, TEXT),
        (QPalette.ColorRole.WindowText, TEXT), (QPalette.ColorRole.Button, SURFACE_2),
        (QPalette.ColorRole.ButtonText, TEXT), (QPalette.ColorRole.Highlight, CYAN),
        (QPalette.ColorRole.HighlightedText, BG), (QPalette.ColorRole.ToolTipBase, SURFACE_2),
        (QPalette.ColorRole.ToolTipText, TEXT), (QPalette.ColorRole.PlaceholderText, FAINT),
    ):
        pal.setColor(role, QColor(color))
    return pal


# ---------------------------------------------------------------------------
# Entry point (single instance)
# ---------------------------------------------------------------------------

def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName(APP_ID)
    app.setQuitOnLastWindowClosed(False)

    server_name = f"{APP_ID}-{Path.home().name}"
    probe = QLocalSocket()
    probe.connectToServer(server_name)
    if probe.waitForConnected(300):
        probe.write(b"show")
        probe.flush()
        probe.waitForBytesWritten(300)
        probe.disconnectFromServer()
        return 0

    QLocalServer.removeServer(server_name)
    server = QLocalServer()
    server.listen(server_name)

    app.setStyle("Fusion")
    app.setPalette(dark_palette())
    app.setFont(pick_font())
    app.setStyleSheet(QSS)

    icon = QIcon(str(ICON_PATH)) if ICON_PATH.exists() else app.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
    app.setWindowIcon(icon)

    win = MainWindow(icon)
    guard = SyntheticInputGuard(win.worker)
    app.installEventFilter(guard)

    def on_connection():
        sock = server.nextPendingConnection()
        if sock:
            sock.readyRead.connect(lambda: sock.readAll())
            sock.disconnected.connect(sock.deleteLater)
            win.show_window()

    server.newConnection.connect(on_connection)
    win.show()
    rc = app.exec()
    server.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
