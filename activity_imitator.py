#!/usr/bin/env python3
"""
Activity Imitator
------------------
Keeps a remote/VDI desktop session (and the IDE running inside it) from
hitting an idle timeout during long, unattended automated test runs, by
emitting occasional randomized, non-destructive mouse/keyboard activity.

Input is injected through the kernel's uinput subsystem (two virtual
devices: an absolute pointer and a tiny keyboard). Unlike XTest via
XWayland this works natively on Wayland and never triggers the
"Allow remote control?" portal dialog.

Safety:
  * Auto-pause  -> as soon as YOU touch a real mouse/keyboard/touchpad the
                   imitation pauses, and resumes after a period of idleness.
  * Ctrl+Alt+S  -> pause / resume
  * Ctrl+Alt+Q  -> quit

Only navigation/non-modifying keys are used; nothing in SAFE_KEYS can
alter file contents.

Requirements: write access to /dev/uinput (granted to the logged-in user
by systemd-logind on most desktops) and read access to /dev/input/event*
(membership in the 'input' group) for hotkeys and auto-pause.
"""

import math
import random
import select
import sys
import threading
import time
from datetime import datetime

import evdev
from evdev import AbsInfo, UInput, ecodes

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MIN_DELAY_SECONDS = 5
MAX_DELAY_SECONDS = 45

# Keep cursor targets within the central 15%-85% of the screen in each axis
# so we never hit window controls, the taskbar, or the system tray.
BOUNDING_BOX_MARGIN = 0.15

# Auto-pause: resume only after the real user has been idle this long.
IDLE_RESUME_SECONDS = 60

ACTION_WEIGHTS = {
    "mouse": 0.5,
    "navigation": 0.4,
    "micro_pause": 0.1,
}

SAFE_KEYS = [
    "shift",
    "ctrl",
    ("alt", "left"),
    ("alt", "right"),
    "pageup",
    "pagedown",
    "up",
    "down",
    "esc",
]

# Global hotkeys (all Ctrl+Alt+<letter>) -> action id. Source of truth for the
# README hotkey table (checked by tests/unit/test_doc_sync_code.py).
HOTKEYS = {
    "Ctrl+Alt+S": "pause",
    "Ctrl+Alt+Q": "quit",
}

# Name prefix of our own virtual devices; the activity listener ignores them
# so the imitator never "sees" its own input as user activity.
VIRTUAL_DEVICE_PREFIX = "Activity Imitator virtual"


def log(message: str) -> None:
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)


# ---------------------------------------------------------------------------
# RandomizationEngine
# ---------------------------------------------------------------------------

class RandomizationEngine:
    """Non-deterministic timing and weighted action selection."""

    @staticmethod
    def next_delay() -> float:
        return random.uniform(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS)

    @staticmethod
    def choose_action() -> str:
        actions, weights = zip(*ACTION_WEIGHTS.items())
        return random.choices(actions, weights=weights, k=1)[0]

    @staticmethod
    def bounding_box():
        """Safe zone in normalized screen coordinates (0..1)."""
        lo, hi = BOUNDING_BOX_MARGIN, 1 - BOUNDING_BOX_MARGIN
        return lo, hi, lo, hi

    @staticmethod
    def random_point_in_box(box):
        x_min, x_max, y_min, y_max = box
        return random.uniform(x_min, x_max), random.uniform(y_min, y_max)


# ---------------------------------------------------------------------------
# UInputBackend
# ---------------------------------------------------------------------------

class UInputBackend:
    """
    Virtual input devices created through /dev/uinput.

    The pointer reports absolute coordinates (like a VM "tablet" mouse), so
    the compositor maps 0..ABS_MAX onto the screen and we can place the
    cursor precisely without knowing the resolution or reading the current
    position (which Wayland does not allow).
    """

    ABS_MAX = 32767
    KEYMAP = {
        "shift": ecodes.KEY_LEFTSHIFT,
        "ctrl": ecodes.KEY_LEFTCTRL,
        "alt": ecodes.KEY_LEFTALT,
        "left": ecodes.KEY_LEFT,
        "right": ecodes.KEY_RIGHT,
        "pageup": ecodes.KEY_PAGEUP,
        "pagedown": ecodes.KEY_PAGEDOWN,
        "up": ecodes.KEY_UP,
        "down": ecodes.KEY_DOWN,
        "esc": ecodes.KEY_ESC,
    }

    def __init__(self):
        axis = AbsInfo(value=0, min=0, max=self.ABS_MAX, fuzz=0, flat=0, resolution=0)
        try:
            self.pointer = UInput(
                {
                    ecodes.EV_KEY: [ecodes.BTN_LEFT, ecodes.BTN_RIGHT, ecodes.BTN_MIDDLE],
                    ecodes.EV_ABS: [(ecodes.ABS_X, axis), (ecodes.ABS_Y, axis)],
                    ecodes.EV_REL: [ecodes.REL_WHEEL],
                },
                name=f"{VIRTUAL_DEVICE_PREFIX} pointer",
                vendor=0x1209, product=0xA171, version=1,
            )
            self.keyboard = UInput(
                {ecodes.EV_KEY: sorted(set(self.KEYMAP.values()))},
                name=f"{VIRTUAL_DEVICE_PREFIX} keyboard",
                vendor=0x1209, product=0xA172, version=1,
            )
        except (OSError, evdev.uinput.UInputError) as exc:
            raise PermissionError(
                "Немає доступу до /dev/uinput. Перевірте: ls -l /dev/uinput "
                f"(потрібен запис для вашого користувача). Деталі: {exc}"
            ) from exc
        # give the compositor a moment to pick up the new devices
        time.sleep(0.4)
        self.x = self.y = 0.5  # last position we set, normalized

    def move_to(self, fx: float, fy: float) -> None:
        fx = min(1.0, max(0.0, fx))
        fy = min(1.0, max(0.0, fy))
        self.pointer.write(ecodes.EV_ABS, ecodes.ABS_X, int(fx * self.ABS_MAX))
        self.pointer.write(ecodes.EV_ABS, ecodes.ABS_Y, int(fy * self.ABS_MAX))
        self.pointer.syn()
        self.x, self.y = fx, fy

    def click(self, button=ecodes.BTN_LEFT) -> None:
        self.pointer.write(ecodes.EV_KEY, button, 1)
        self.pointer.syn()
        time.sleep(random.uniform(0.05, 0.12))
        self.pointer.write(ecodes.EV_KEY, button, 0)
        self.pointer.syn()

    def scroll(self, ticks: int) -> None:
        """Positive = scroll up, negative = down (one event per notch)."""
        step = 1 if ticks > 0 else -1
        for _ in range(abs(ticks)):
            self.pointer.write(ecodes.EV_REL, ecodes.REL_WHEEL, step)
            self.pointer.syn()
            time.sleep(random.uniform(0.04, 0.1))

    def press(self, *keys: str) -> None:
        codes = [self.KEYMAP[k] for k in keys]
        for code in codes:
            self.keyboard.write(ecodes.EV_KEY, code, 1)
            self.keyboard.syn()
            time.sleep(random.uniform(0.02, 0.05))
        time.sleep(random.uniform(0.04, 0.1))
        for code in reversed(codes):
            self.keyboard.write(ecodes.EV_KEY, code, 0)
            self.keyboard.syn()
            time.sleep(random.uniform(0.02, 0.05))

    def close(self) -> None:
        for dev in (self.pointer, self.keyboard):
            try:
                dev.close()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# InputSimulator
# ---------------------------------------------------------------------------

class InputSimulator:
    """Executes mouse/keyboard actions with smooth, eased cursor motion."""

    def __init__(self, engine: RandomizationEngine, backend: UInputBackend | None = None):
        self.engine = engine
        self.backend = backend or UInputBackend()
        self.box = engine.bounding_box()

    @staticmethod
    def _ease_in_out(t: float) -> float:
        return t * t * (3 - 2 * t)

    def _cubic_bezier_path(self, start, end, steps: int):
        x0, y0 = start
        x3, y3 = end
        dx, dy = x3 - x0, y3 - y0
        # bow the path off the straight line by a random perpendicular offset
        offset = random.uniform(-0.25, 0.25)
        x1 = x0 + dx * 0.33 - dy * offset
        y1 = y0 + dy * 0.33 + dx * offset
        x2 = x0 + dx * 0.66 - dy * offset
        y2 = y0 + dy * 0.66 + dx * offset

        path = []
        for i in range(steps + 1):
            t = self._ease_in_out(i / steps)
            mt = 1 - t
            x = mt**3 * x0 + 3 * mt**2 * t * x1 + 3 * mt * t**2 * x2 + t**3 * x3
            y = mt**3 * y0 + 3 * mt**2 * t * y1 + 3 * mt * t**2 * y2 + t**3 * y3
            path.append((x, y))
        return path

    def move_mouse(self, click_chance: float = 0.25, should_abort=None) -> str:
        """
        Glide to a random point in the safe zone (and sometimes click+scroll).
        `should_abort` is polled during the motion; if it returns True (e.g.
        the real user grabbed the mouse) the action stops immediately.
        """
        start = (self.backend.x, self.backend.y)
        end = self.engine.random_point_in_box(self.box)
        distance = math.hypot(end[0] - start[0], end[1] - start[1])
        steps = max(10, min(60, int(distance * 1000 / 8)))
        duration = random.uniform(0.4, 1.6)
        path = self._cubic_bezier_path(start, end, steps)
        step_delay = duration / max(1, len(path))

        for x, y in path:
            if should_abort and should_abort():
                return "move interrupted"
            self.backend.move_to(x, y)
            time.sleep(step_delay)

        detail = f"move to ({end[0] * 100:.0f}%, {end[1] * 100:.0f}%)"

        if random.random() < click_chance and not (should_abort and should_abort()):
            self.backend.click()
            time.sleep(random.uniform(0.1, 0.3))
            ticks = random.choice([-2, -1, 1, 2])
            self.backend.scroll(ticks)
            detail += f" + click + scroll({ticks})"

        return detail

    def navigation_keystroke(self) -> str:
        choice = random.choice(SAFE_KEYS)
        if isinstance(choice, tuple):
            self.backend.press(*choice)
            return "+".join(choice)
        self.backend.press(choice)
        return choice

    def micro_pause(self) -> str:
        extra = random.uniform(0.5, 2.5)
        time.sleep(extra)
        return f"idle {extra:.1f}s"

    def close(self) -> None:
        self.backend.close()


# ---------------------------------------------------------------------------
# SafetyListener
# ---------------------------------------------------------------------------

class SafetyListener:
    """
    Watches the real input devices (passively, via evdev) for two things:

      * global hotkeys: Ctrl+Alt+S pause/resume, Ctrl+Alt+Q quit;
      * user activity: the timestamp of the last real key press, mouse
        motion, click, scroll or touchpad touch -> used for auto-pause.

    Reads raw /dev/input event nodes instead of an X11 global key hook,
    because Wayland compositors do not expose global input to X11 clients.
    Devices are never grabbed, so input still reaches applications
    normally. Our own uinput devices are ignored. New devices (e.g. a
    Bluetooth mouse that reconnects) are picked up automatically.

    Requires the user to be in the 'input' group:
        sudo usermod -aG input $USER   (then log out/in)
    """

    RESCAN_SECONDS = 5.0
    HOTKEY_CODES = {getattr(ecodes, "KEY_" + combo.rsplit("+", 1)[1]): action
                    for combo, action in HOTKEYS.items()}

    def __init__(self, on_pause_toggle=None, on_quit=None):
        self.paused = False
        self.should_quit = False
        # Optional callbacks (used by the GUI); called from the listener thread.
        self.on_pause_toggle = on_pause_toggle
        self.on_quit = on_quit
        self.last_user_input = 0.0  # time.monotonic() of last real input
        self._pressed = set()
        self._hotkey_fired = False
        self._devices = {}  # path -> InputDevice
        self._rescan()
        self._stop_flag = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    # -- device discovery ------------------------------------------------------
    @staticmethod
    def _is_relevant(dev) -> bool:
        if dev.name.startswith(VIRTUAL_DEVICE_PREFIX):
            return False
        caps = dev.capabilities()
        keys = set(caps.get(ecodes.EV_KEY, []))
        rel = set(caps.get(ecodes.EV_REL, []))
        abs_codes = {c[0] if isinstance(c, tuple) else c for c in caps.get(ecodes.EV_ABS, [])}
        is_keyboard = ecodes.KEY_A in keys and ecodes.KEY_Z in keys
        is_mouse = ecodes.REL_X in rel and ecodes.REL_Y in rel
        is_touch = ecodes.ABS_X in abs_codes and bool(
            keys & {ecodes.BTN_TOUCH, ecodes.BTN_LEFT, ecodes.BTN_TOOL_FINGER, ecodes.BTN_TOOL_PEN})
        return is_keyboard or is_mouse or is_touch

    def _rescan(self):
        try:
            paths = set(evdev.list_devices())
        except OSError:
            paths = set()
        for path in list(self._devices):
            if path not in paths:
                self._close_dev(self._devices.pop(path))
        for path in paths - set(self._devices):
            try:
                dev = evdev.InputDevice(path)
            except OSError:
                continue
            if self._is_relevant(dev):
                self._devices[path] = dev
            else:
                dev.close()

    @staticmethod
    def _close_dev(dev):
        try:
            dev.close()
        except OSError:
            pass

    @property
    def has_devices(self) -> bool:
        return bool(self._devices)

    # kept for backwards compatibility
    has_keyboards = has_devices

    def idle_seconds(self) -> float:
        """Seconds since the last real user input (large if none yet)."""
        if not self.last_user_input:
            return float("inf")
        return time.monotonic() - self.last_user_input

    # -- lifecycle -----------------------------------------------------------------
    def start(self):
        if not self._devices:
            log("УВАГА: не знайдено пристроїв введення у /dev/input "
                "(додайте користувача до групи 'input' і перелогіньтесь) "
                "-- гарячі клавіші та автопаузу вимкнено, Ctrl+C працює.")
        self._thread.start()

    def stop(self):
        self._stop_flag.set()
        for dev in list(self._devices.values()):
            self._close_dev(dev)

    def _run(self):
        last_scan = time.monotonic()
        while not self._stop_flag.is_set():
            if time.monotonic() - last_scan > self.RESCAN_SECONDS:
                self._rescan()
                last_scan = time.monotonic()
            fd_to_dev = {dev.fd: dev for dev in self._devices.values()}
            if not fd_to_dev:
                self._stop_flag.wait(1.0)
                continue
            try:
                ready, _, _ = select.select(list(fd_to_dev), [], [], 0.5)
            except (OSError, ValueError):
                self._rescan()
                continue
            for fd in ready:
                dev = fd_to_dev[fd]
                try:
                    for event in dev.read():
                        self._handle(event)
                except (OSError, evdev.EvdevError):
                    continue

    def _handle(self, event):
        if event.type in (ecodes.EV_REL, ecodes.EV_ABS) or (
                event.type == ecodes.EV_KEY and event.value == 1):
            self.last_user_input = time.monotonic()
        if event.type != ecodes.EV_KEY:
            return

        if event.value == 1:  # key down
            self._pressed.add(event.code)
        elif event.value == 0:  # key up
            self._pressed.discard(event.code)
            if not self._pressed:
                self._hotkey_fired = False
            return
        else:  # autorepeat
            return

        ctrl = ecodes.KEY_LEFTCTRL in self._pressed or ecodes.KEY_RIGHTCTRL in self._pressed
        alt = ecodes.KEY_LEFTALT in self._pressed or ecodes.KEY_RIGHTALT in self._pressed

        if ctrl and alt and not self._hotkey_fired:
            action = next((a for code, a in self.HOTKEY_CODES.items() if code in self._pressed), None)
            if action == "pause":
                self._hotkey_fired = True
                self.paused = not self.paused
                log(f"Hotkey Ctrl+Alt+S -> {'PAUSED' if self.paused else 'RESUMED'}")
                if self.on_pause_toggle:
                    self.on_pause_toggle(self.paused)
            elif action == "quit":
                self._hotkey_fired = True
                log("Hotkey Ctrl+Alt+Q -> quit requested")
                self.should_quit = True
                if self.on_quit:
                    self.on_quit()


# ---------------------------------------------------------------------------
# MainLoop
# ---------------------------------------------------------------------------

class MainLoop:
    def __init__(self):
        self.engine = RandomizationEngine()
        self.simulator = InputSimulator(self.engine)
        self.safety = SafetyListener()

    def _user_active(self) -> bool:
        return self.safety.has_devices and self.safety.idle_seconds() < IDLE_RESUME_SECONDS

    def run(self):
        log("Activity Imitator started (uinput). Ctrl+Alt+S = pause/resume, Ctrl+Alt+Q = quit.")
        log(f"Safe zone: central {BOUNDING_BOX_MARGIN:.0%}-{1 - BOUNDING_BOX_MARGIN:.0%} of the screen | "
            f"auto-pause while you use mouse/keyboard (resume after {IDLE_RESUME_SECONDS}s idle)")
        self.safety.start()
        was_waiting = False

        try:
            while not self.safety.should_quit:
                if self.safety.paused:
                    time.sleep(0.5)
                    continue
                if self._user_active():
                    if not was_waiting:
                        log("User activity detected -> auto-pause")
                        was_waiting = True
                    time.sleep(0.5)
                    continue
                if was_waiting:
                    log("User idle -> resuming")
                    was_waiting = False

                action = self.engine.choose_action()
                if action == "mouse":
                    label, detail = "Mouse", self.simulator.move_mouse(should_abort=self._user_active)
                elif action == "navigation":
                    label, detail = "Keystroke", self.simulator.navigation_keystroke()
                else:
                    label, detail = "Micro-pause", self.simulator.micro_pause()

                delay = self.engine.next_delay()
                log(f"Action: {label} ({detail}) | Next delay: {delay:.0f}s")

                slept = 0.0
                while (slept < delay and not self.safety.should_quit
                       and not self.safety.paused and not self._user_active()):
                    step = min(0.5, delay - slept)
                    time.sleep(step)
                    slept += step
        finally:
            self.safety.stop()
            self.simulator.close()
            log("Activity Imitator stopped.")


if __name__ == "__main__":
    try:
        MainLoop().run()
    except KeyboardInterrupt:
        log("Interrupted by user (Ctrl+C). Exiting.")
        sys.exit(0)
    except PermissionError as exc:
        log(f"ПОМИЛКА: {exc}")
        sys.exit(1)
