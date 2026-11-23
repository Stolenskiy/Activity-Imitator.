"""Cross-module invariants between the core and the GUI (no I/O)."""

import re
import unittest

import activity_imitator as core
import activity_imitator_gui as gui
from evdev import ecodes


class ConsistencyTest(unittest.TestCase):
    SAFE_NAMES = {k if isinstance(k, str) else "+".join(k) for k in core.SAFE_KEYS}

    def test_every_safe_key_can_be_typed_by_the_virtual_keyboard(self):
        for entry in core.SAFE_KEYS:
            for name in (entry,) if isinstance(entry, str) else entry:
                self.assertIn(name, core.UInputBackend.KEYMAP)

    def test_gui_has_a_display_name_for_every_safe_key(self):
        self.assertEqual(set(gui.KEY_NAMES), self.SAFE_NAMES)

    def test_hotkeys_are_ctrl_alt_letters(self):
        for combo in core.HOTKEYS:
            m = re.fullmatch(r"Ctrl\+Alt\+([A-Z])", combo)
            self.assertIsNotNone(m, combo)
            self.assertTrue(hasattr(ecodes, f"KEY_{m.group(1)}"))
        self.assertEqual(set(core.HOTKEYS.values()), {"pause", "quit"})

    def test_status_maps_cover_the_same_states(self):
        self.assertEqual(set(gui.STATUS_COLORS), set(gui.STATUS_TEXT))

    def test_every_log_kind_has_a_colour(self):
        kinds = {"mouse", "click", "key", "pause", "info", "auto", "warn", "error"}
        self.assertTrue(kinds <= set(gui.KIND_COLORS))

    def test_action_weights_are_the_known_actions(self):
        self.assertEqual(set(core.ACTION_WEIGHTS), {"mouse", "navigation", "micro_pause"})
        self.assertAlmostEqual(sum(core.ACTION_WEIGHTS.values()), 1.0)

    def test_duration_choices_start_with_unlimited(self):
        self.assertEqual(gui.DURATIONS[0], (0, "∞"))
        minutes = [m for m, _ in gui.DURATIONS]
        self.assertEqual(minutes, sorted(minutes))


if __name__ == "__main__":
    unittest.main()
