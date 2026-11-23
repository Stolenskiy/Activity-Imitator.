#!/usr/bin/env python3
"""
Activity Imitator
------------------
Keeps a remote/VDI desktop session (and the IDE running inside it) from
hitting an idle timeout during long, unattended automated test runs, by
emitting occasional randomized, non-destructive mouse/keyboard activity.

Safety:
  * Ctrl+Alt+S  -> pause / resume
  * Ctrl+Alt+Q  -> quit
  * Moving the mouse to any screen corner aborts pyautogui (built-in
    fail-safe) and the script exits cleanly.

Only navigation/non-modifying keys are used; nothing in SAFE_KEYS can
alter file contents.
"""

import math
import random
import select
import sys
import threading
import time
from datetime import datetime

import evdev
import pyautogui
from evdev import ecodes

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MIN_DELAY_SECONDS = 5
MAX_DELAY_SECONDS = 45

# Keep cursor targets within the central 15%-85% of the screen in each axis
# so we never hit window controls, the taskbar, or the system tray.
BOUNDING_BOX_MARGIN = 0.15

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

pyautogui.FAILSAFE = True  # corner-of-screen abort
pyautogui.PAUSE = 0        # we manage our own timing


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
    def bounding_box(screen_width: int, screen_height: int):
        x_min = int(screen_width * BOUNDING_BOX_MARGIN)
        x_max = int(screen_width * (1 - BOUNDING_BOX_MARGIN))
        y_min = int(screen_height * BOUNDING_BOX_MARGIN)
        y_max = int(screen_height * (1 - BOUNDING_BOX_MARGIN))
        return x_min, x_max, y_min, y_max

    @staticmethod
    def random_point_in_box(box):
        x_min, x_max, y_min, y_max = box
        return random.randint(x_min, x_max), random.randint(y_min, y_max)


# ---------------------------------------------------------------------------
# InputSimulator
# ---------------------------------------------------------------------------

class InputSimulator:
    """Executes mouse/keyboard actions with smooth, eased cursor motion."""

    def __init__(self, engine: RandomizationEngine):
        self.engine = engine
        self.screen_width, self.screen_height = pyautogui.size()
        self.box = engine.bounding_box(self.screen_width, self.screen_height)

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

    def move_mouse(self) -> str:
        start = pyautogui.position()
        end = self.engine.random_point_in_box(self.box)
        distance = math.hypot(end[0] - start[0], end[1] - start[1])
        steps = max(10, min(60, int(distance / 8)))
        duration = random.uniform(0.4, 1.6)
        path = self._cubic_bezier_path(start, end, steps)
        step_delay = duration / max(1, len(path))

        for x, y in path:
            pyautogui.moveTo(x, y)
            time.sleep(step_delay)

        detail = f"move to ({end[0]}, {end[1]})"

        if random.random() < 0.25:
            pyautogui.click()
            time.sleep(random.uniform(0.1, 0.3))
            ticks = random.choice([-2, -1, 1, 2])
            pyautogui.scroll(ticks)
            detail += f" + click + scroll({ticks})"

        return detail

    def navigation_keystroke(self) -> str:
        choice = random.choice(SAFE_KEYS)
        if isinstance(choice, tuple):
            pyautogui.hotkey(*choice)
            return "+".join(choice)
        pyautogui.press(choice)
        return choice

    def micro_pause(self) -> str:
        extra = random.uniform(0.5, 2.5)
        time.sleep(extra)
        return f"idle {extra:.1f}s"


# ---------------------------------------------------------------------------
# SafetyListener
# ---------------------------------------------------------------------------

class SafetyListener:
    """
    Global hotkeys: Ctrl+Alt+S pause/resume, Ctrl+Alt+Q quit.

    Reads raw /dev/input keyboard event nodes via evdev instead of an X11
    global key hook, because Wayland compositors (Mutter, Cosmic, ...) do
    not expose global key events to X11/XWayland clients for security
    reasons -- an X11-based listener (e.g. pynput's default backend)
    silently receives nothing on a Wayland session. Reading is passive
    (devices are never grabbed), so keystrokes still reach the focused
    application normally.

    Requires the user to be in the 'input' group:
        sudo usermod -aG input $USER   (then log out/in)
    """

    HOTKEY_MODS = (
        ecodes.KEY_LEFTCTRL, ecodes.KEY_RIGHTCTRL,
        ecodes.KEY_LEFTALT, ecodes.KEY_RIGHTALT,
    )

    def __init__(self):
        self.paused = False
        self.should_quit = False
        self._pressed = set()
        self._hotkey_fired = False
        self._devices = self._find_keyboards()
        self._stop_flag = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    @staticmethod
    def _find_keyboards():
        devices = []
        for path in evdev.list_devices():
            try:
                dev = evdev.InputDevice(path)
            except OSError:
                continue
            caps = dev.capabilities().get(ecodes.EV_KEY, [])
            # Real keyboards expose the full letter-key range; mice/
            # touchpads/power buttons etc. do not.
            if ecodes.KEY_A in caps and ecodes.KEY_Z in caps:
                devices.append(dev)
        return devices

    def start(self):
        if not self._devices:
            log("УВАГА: не знайдено клавіатурних пристроїв у /dev/input "
                "(додайте користувача до групи 'input' і перелогіньтесь) "
                "-- гарячі клавіші вимкнено, Ctrl+C і кут екрана "
                "залишаються робочими.")
            return
        self._thread.start()

    def stop(self):
        self._stop_flag.set()
        for dev in self._devices:
            try:
                dev.close()
            except OSError:
                pass

    def _run(self):
        fd_to_dev = {dev.fd: dev for dev in self._devices}
        while not self._stop_flag.is_set():
            try:
                ready, _, _ = select.select(fd_to_dev.keys(), [], [], 0.5)
            except (OSError, ValueError):
                return
            for fd in ready:
                dev = fd_to_dev[fd]
                try:
                    for event in dev.read():
                        if event.type == ecodes.EV_KEY:
                            self._handle(event)
                except (OSError, evdev.error.EvdevError):
                    continue

    def _handle(self, event):
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
            if ecodes.KEY_S in self._pressed:
                self._hotkey_fired = True
                self.paused = not self.paused
                log(f"Hotkey Ctrl+Alt+S -> {'PAUSED' if self.paused else 'RESUMED'}")
            elif ecodes.KEY_Q in self._pressed:
                self._hotkey_fired = True
                log("Hotkey Ctrl+Alt+Q -> quit requested")
                self.should_quit = True


# ---------------------------------------------------------------------------
# MainLoop
# ---------------------------------------------------------------------------

class MainLoop:
    def __init__(self):
        self.engine = RandomizationEngine()
        self.simulator = InputSimulator(self.engine)
        self.safety = SafetyListener()

    def run(self):
        log("Activity Imitator started. Ctrl+Alt+S = pause/resume, Ctrl+Alt+Q = quit.")
        log(f"Screen: {self.simulator.screen_width}x{self.simulator.screen_height} | "
            f"Safe zone (x_min,x_max,y_min,y_max): {self.simulator.box}")
        self.safety.start()

        try:
            while not self.safety.should_quit:
                if self.safety.paused:
                    time.sleep(0.5)
                    continue

                action = self.engine.choose_action()
                try:
                    if action == "mouse":
                        label, detail = "Mouse", self.simulator.move_mouse()
                    elif action == "navigation":
                        label, detail = "Keystroke", self.simulator.navigation_keystroke()
                    else:
                        label, detail = "Micro-pause", self.simulator.micro_pause()
                except pyautogui.FailSafeException:
                    log("Fail-safe triggered (cursor moved to screen corner). Exiting.")
                    break

                delay = self.engine.next_delay()
                log(f"Action: {label} ({detail}) | Next delay: {delay:.0f}s")

                slept = 0.0
                while slept < delay and not self.safety.should_quit and not self.safety.paused:
                    step = min(0.5, delay - slept)
                    time.sleep(step)
                    slept += step
        finally:
            self.safety.stop()
            log("Activity Imitator stopped.")


if __name__ == "__main__":
    try:
        MainLoop().run()
    except KeyboardInterrupt:
        log("Interrupted by user (Ctrl+C). Exiting.")
        sys.exit(0)
