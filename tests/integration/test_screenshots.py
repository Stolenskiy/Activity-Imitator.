"""tools/screenshots.py renders every GUI state offscreen (no hardware, temp HOME)."""

import tempfile
import unittest
from pathlib import Path

import activity_imitator as core
from tools import screenshots


class ScreenshotsTest(unittest.TestCase):
    def test_renders_all_states_and_restores_the_core(self):
        before = core.InputSimulator, core.SafetyListener
        with tempfile.TemporaryDirectory() as tmp:
            paths = screenshots.render(Path(tmp))
            names = {p.name for p in paths}
            self.assertEqual(names, {"stopped.png", "running.png", "waiting.png", "paused.png",
                                     "settings.png", "all.png"})
            self.assertTrue(all(p.stat().st_size > 1000 for p in paths))
        self.assertEqual((core.InputSimulator, core.SafetyListener), before)


if __name__ == "__main__":
    unittest.main()
