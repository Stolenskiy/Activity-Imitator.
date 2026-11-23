#!/usr/bin/env python3
"""
Render every GUI state offscreen to PNG files (default: build/screenshots/).
No real devices, no real settings: hardware classes are stubbed and HOME
points to a temporary directory. Used by docs/runbooks/gui-state-or-visual.md.

  .venv/bin/python tools/screenshots.py [OUT_DIR]
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["HOME"] = tempfile.mkdtemp(prefix="ai-screens-")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(ROOT))

import activity_imitator as core  # noqa: E402  (after HOME is redirected)
import activity_imitator_gui as gui  # noqa: E402
from PySide6.QtGui import QIcon, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


class _StubSimulator:
    def __init__(self, *_a, **_k):
        pass

    def close(self):
        pass


class _StubSafety:
    def __init__(self, on_pause_toggle=None, on_quit=None):
        self.paused = self.should_quit = False
        self.has_devices = True
        self.last_user_input = 0.0

    def start(self):
        pass

    def stop(self):
        pass


def render(out: Path) -> list[Path]:
    """Render all states; the core's hardware classes are stubbed only meanwhile."""
    originals = core.InputSimulator, core.SafetyListener
    core.InputSimulator, core.SafetyListener = _StubSimulator, _StubSafety
    try:
        return _render(out)
    finally:
        core.InputSimulator, core.SafetyListener = originals


def _render(out: Path) -> list[Path]:
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    app.setPalette(gui.dark_palette())
    app.setFont(gui.pick_font())
    app.setStyleSheet(gui.QSS)
    win = gui.MainWindow(QIcon(str(gui.ICON_PATH)))
    win.worker.start = lambda: 1  # no background thread
    win.show()
    out.mkdir(parents=True, exist_ok=True)
    shots: list[Path] = []

    def snap(name: str) -> None:
        for _ in range(3):
            app.processEvents()
        win._tick_anim()
        win._tick_slow()
        path = out / f"{name}.png"
        win.grab().save(str(path))
        shots.append(path)

    snap("stopped")
    win.start()
    win.run_started -= 754
    for kind, text in [("mouse", "Рух миші → 42% × 61% екрана"), ("key", "Клавіша Page Down"),
                       ("click", "Рух → 40% × 38%, клік і прокрутка -1")]:
        win._on_action(1, kind, text)
    win._on_scheduled(1, 30.0)
    win.next_at = time.monotonic() + 18
    snap("running")
    win._on_user_wait(1, 37.0)
    snap("waiting")
    win._on_user_wait(1, -1.0)
    win.toggle_pause()
    snap("paused")
    win.tab_group.button(1).click()
    snap("settings")
    win.quit()

    images = [QImage(str(p)) for p in shots]
    sheet = QImage(sum(i.width() + 10 for i in images), max(i.height() for i in images),
                   QImage.Format.Format_RGB32)
    sheet.fill(0)
    painter = QPainter(sheet)
    x = 0
    for img in images:
        painter.drawImage(x, 0, img)
        x += img.width() + 10
    painter.end()
    sheet.save(str(out / "all.png"))
    return shots + [out / "all.png"]


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build" / "screenshots"
    for p in render(target):
        print(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p)
