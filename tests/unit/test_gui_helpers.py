"""Pure GUI helpers and Settings persistence (temp files only)."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import activity_imitator_gui as gui
from PySide6.QtGui import QColor


class FormatTest(unittest.TestCase):
    def test_fmt_duration(self):
        self.assertEqual([gui.fmt_duration(s) for s in (-5, 0, 65, 3725)],
                         ["00:00", "00:00", "01:05", "1:02:05"])

    def test_fmt_human(self):
        self.assertEqual([gui.fmt_human(s) for s in (45, 120, 3600, 3660)],
                         ["45 с", "2 хв", "1 год", "1 год 1 хв"])

    def test_fmt_ago(self):
        self.assertEqual([gui.fmt_ago(s) for s in (2, 30, 125)], ["щойно", "30 с тому", "2 хв тому"])

    def test_describe_mouse(self):
        self.assertEqual(gui.describe_mouse("move to (42%, 61%)"), ("mouse", "Рух миші → 42% × 61% екрана"))
        kind, text = gui.describe_mouse("move to (1%, 2%) + click + scroll(-1)")
        self.assertEqual((kind, text), ("click", "Рух → 1% × 2%, клік і прокрутка -1"))
        self.assertEqual(gui.describe_mouse("move interrupted")[0], "auto")
        self.assertEqual(gui.describe_mouse("something else"), ("mouse", "something else"))

    def test_colour_helpers(self):
        self.assertEqual(gui.mix(QColor(0, 0, 0), QColor(200, 100, 50), 0.5).getRgb()[:3], (100, 50, 25))
        self.assertEqual(gui.with_alpha("#ffffff", 10).alpha(), 10)


class SettingsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "cfg" / "settings.json"
        patcher = mock.patch.object(gui, "CONFIG_PATH", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_missing_file_gives_defaults(self):
        self.assertEqual(gui.Settings.load(), gui.Settings())

    def test_save_and_load_round_trip(self):
        s = gui.Settings(min_delay=7, auto_pause=False, resume_after=120)
        s.save()
        self.assertEqual(gui.Settings.load(), s)

    def test_unknown_keys_are_ignored(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps({"min_delay": 9, "legacy_option": 1}))
        self.assertEqual(gui.Settings.load().min_delay, 9)

    def test_corrupt_file_gives_defaults(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{not json")
        self.assertEqual(gui.Settings.load(), gui.Settings())

    def test_save_failure_is_silent(self):
        self.path.parent.parent.mkdir(parents=True, exist_ok=True)
        self.path.parent.write_text("a file where a directory should be")
        gui.Settings().save()  # must not raise


if __name__ == "__main__":
    unittest.main()
