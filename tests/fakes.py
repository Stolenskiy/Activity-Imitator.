"""Synthetic fixtures that replace real devices and hardware classes (ADR 0008)."""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from types import SimpleNamespace
from unittest import mock

from evdev import AbsInfo, ecodes


def event(etype: int, code: int, value: int) -> SimpleNamespace:
    return SimpleNamespace(type=etype, code=code, value=value)


def key(code: int, value: int = 1) -> SimpleNamespace:
    return event(ecodes.EV_KEY, code, value)


_AXIS = AbsInfo(value=0, min=0, max=1000, fuzz=0, flat=0, resolution=10)
KEYBOARD_CAPS = {ecodes.EV_KEY: [ecodes.KEY_A, ecodes.KEY_Z, ecodes.KEY_S, ecodes.KEY_Q,
                                 ecodes.KEY_LEFTCTRL, ecodes.KEY_LEFTALT]}
MOUSE_CAPS = {ecodes.EV_REL: [ecodes.REL_X, ecodes.REL_Y], ecodes.EV_KEY: [ecodes.BTN_LEFT]}
TOUCHPAD_CAPS = {ecodes.EV_ABS: [(ecodes.ABS_X, _AXIS), (ecodes.ABS_Y, _AXIS)],
                 ecodes.EV_KEY: [ecodes.BTN_TOUCH, ecodes.BTN_TOOL_FINGER]}
POWER_BUTTON_CAPS = {ecodes.EV_KEY: [ecodes.KEY_POWER]}


class FakeUInput:
    """Stands in for evdev.UInput and records everything written."""

    created: list["FakeUInput"] = []

    def __init__(self, events=None, name="py-evdev-uinput", vendor=0, product=0, version=0, **_kw):
        self.caps, self.name = events or {}, name
        self.written: list = []
        self.closed = False
        FakeUInput.created.append(self)

    def write(self, etype, code, value):
        self.written.append((etype, code, value))

    def syn(self):
        self.written.append("syn")

    def close(self):
        self.closed = True


class FakeBackend:
    """Stands in for activity_imitator.UInputBackend."""

    def __init__(self):
        self.x = self.y = 0.5
        self.moves: list = []
        self.clicks = 0
        self.scrolls: list = []
        self.presses: list = []
        self.closed = False

    def move_to(self, fx, fy):
        self.x, self.y = fx, fy
        self.moves.append((fx, fy))

    def click(self, *_a):
        self.clicks += 1

    def scroll(self, ticks):
        self.scrolls.append(ticks)

    def press(self, *keys):
        self.presses.append(keys)

    def close(self):
        self.closed = True


class FakeInputDevice:
    """Stands in for evdev.InputDevice. With `pipe=True` it owns a real pipe fd,
    so select() works; `feed()` queues events and makes the fd readable."""

    def __init__(self, name, caps, pipe=False):
        self.name, self.caps = name, caps
        self.queue: list = []
        self.closed = False
        self._r = self._w = None
        if pipe:
            self._r, self._w = os.pipe()
        self.fd = self._r if pipe else -1  # -1: select() rejects it

    def capabilities(self):
        return self.caps

    def feed(self, *events):
        self.queue.extend(events)
        os.write(self._w, b"x")

    def read(self):
        if self._r is not None:
            os.read(self._r, 1024)
        events, self.queue = self.queue, []
        return events

    def close(self):
        self.closed = True
        for fd in (self._r, self._w):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
        self._r = self._w = None


class FakeSimulator:
    """Stands in for activity_imitator.InputSimulator (GUI and MainLoop tests)."""

    def __init__(self, *_a, **_k):
        self.calls: list = []
        self.closed = False
        self.fail: BaseException | None = None

    def move_mouse(self, click_chance=0.25, should_abort=None):
        self.calls.append("mouse")
        if self.fail:
            raise self.fail
        if should_abort and should_abort():
            return "move interrupted"
        return "move to (42%, 61%) + click + scroll(-1)" if click_chance else "move to (42%, 61%)"

    def navigation_keystroke(self):
        self.calls.append("key")
        return "alt+left"

    def micro_pause(self):
        self.calls.append("pause")
        return "idle 0.1s"

    def close(self):
        self.closed = True


class FakeSafety:
    """Stands in for activity_imitator.SafetyListener."""

    def __init__(self, on_pause_toggle=None, on_quit=None):
        self.on_pause_toggle, self.on_quit = on_pause_toggle, on_quit
        self.paused = self.should_quit = False
        self.has_devices = True
        self.last_user_input = 0.0
        self.started = self.stopped = False

    def idle_seconds(self):
        return float("inf") if not self.last_user_input else time.monotonic() - self.last_user_input

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


@contextmanager
def fake_hardware(simulator_factory=FakeSimulator, safety_factory=FakeSafety):
    """Patch the core's hardware classes for GUI tests."""
    import activity_imitator as core
    with mock.patch.object(core, "InputSimulator", simulator_factory), \
            mock.patch.object(core, "SafetyListener", safety_factory):
        yield


def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def pump(until=None, timeout=3.0) -> bool:
    """Process Qt events until `until()` is true (or just once if None)."""
    app = qapp()
    deadline = time.monotonic() + timeout
    while True:
        app.processEvents()
        if until is None or until():
            return True
        if time.monotonic() > deadline:
            return False
        time.sleep(0.005)
