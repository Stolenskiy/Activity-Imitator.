"""Doc-sync, code-derived surfaces: README tables vs the AST of the product code.

Source of truth -> documented surface (fixed table columns):
  Settings dataclass          -> README "Налаштування"
  numeric core constants      -> README "Параметри ядра"
  SAFE_KEYS + GUI KEY_NAMES   -> README "Безпека"
  HOTKEYS                     -> README "Гарячі клавіші"
  top-level classes           -> README "Структура коду" (one table per module)
  CONFIG_PATH                 -> README mentions it in backticks
  git tags v*                 -> README "Версії й відкат"
"""

import json
import unittest

from tools import docsync

README = docsync.read("README.md")
CORE = docsync.module("activity_imitator.py")
GUI = docsync.module("activity_imitator_gui.py")


class ReadmeTablesTest(unittest.TestCase):
    def rows(self, title, header, text=README):
        try:
            head, rows = docsync.table(docsync.section(text, title))
        except (KeyError, ValueError) as exc:
            self.fail(f"README.md: section «{title}» with a table is required ({exc})")
        self.assertEqual(head, header, f"README.md «{title}»: columns must be exactly {header}")
        return rows

    def assertDocumented(self, documented, expected, where):
        missing = {k: v for k, v in expected.items() if documented.get(k) != v}
        extra = sorted(set(documented) - set(expected))
        self.assertFalse(missing or extra,
                         f"README.md «{where}» out of sync with code.\n"
                         f"  expected (from code) but missing/different: {missing}\n"
                         f"  documented but not in code: {extra}")

    def test_settings_table_matches_settings_dataclass(self):
        rows = self.rows("Налаштування", ["Ключ", "За замовчуванням", "Опис"])
        documented = {docsync.unbacktick(r[0]): docsync.unbacktick(r[1]) for r in rows}
        expected = {k: json.dumps(v) for k, v in docsync.dataclass_fields(GUI, "Settings").items()}
        self.assertDocumented(documented, expected, "Налаштування")

    def test_core_parameters_table_matches_numeric_constants(self):
        rows = self.rows("Параметри ядра", ["Константа", "Значення", "Опис"])
        documented = {docsync.unbacktick(r[0]): docsync.unbacktick(r[1]) for r in rows}
        expected = {k: repr(v) for k, v in docsync.constants(CORE).items()
                    if isinstance(v, (int, float)) and not isinstance(v, bool)}
        self.assertDocumented(documented, expected, "Параметри ядра")

    def test_safe_keys_table_matches_core_and_gui_names(self):
        rows = self.rows("Безпека", ["Код у `SAFE_KEYS`", "Клавіші"])
        documented = {docsync.unbacktick(r[0]): r[1] for r in rows}
        key_names = docsync.constants(GUI)["KEY_NAMES"]
        codes = [k if isinstance(k, str) else "+".join(k) for k in docsync.constants(CORE)["SAFE_KEYS"]]
        self.assertDocumented(documented, {c: key_names.get(c, "?") for c in codes}, "Безпека")

    def test_hotkeys_table_matches_HOTKEYS(self):
        rows = self.rows("Гарячі клавіші", ["Комбінація", "Дія", "Опис"])
        documented = {docsync.unbacktick(r[0]): docsync.unbacktick(r[1]) for r in rows}
        self.assertDocumented(documented, docsync.constants(CORE)["HOTKEYS"], "Гарячі клавіші")

    def test_structure_tables_list_every_class(self):
        structure = docsync.section(README, "Структура коду")
        for rel, tree in (("activity_imitator.py", CORE), ("activity_imitator_gui.py", GUI)):
            rows = self.rows(f"`{rel}`", ["Клас", "Призначення"], text=structure)
            documented = {docsync.unbacktick(r[0]): "class" for r in rows}
            expected = {name: "class" for name in docsync.top_level_classes(tree)}
            self.assertDocumented(documented, expected, f"Структура коду / {rel}")

    def test_config_path_is_documented(self):
        path = docsync.home_path_expr(GUI, "CONFIG_PATH")
        self.assertIn(path, docsync.backticks(README), f"README.md must mention `{path}`")

    def test_versions_table_matches_git_tags(self):
        rows = self.rows("Версії й відкат", ["Тег", "Що це"])
        documented = {docsync.unbacktick(r[0]): "tag" for r in rows}
        tags = (docsync.git("tag", "--list", "v*") or "").split()
        if not tags:
            self.skipTest("no tags in this clone (CI must fetch with fetch-depth: 0)")
        self.assertDocumented(documented, {t: "tag" for t in tags}, "Версії й відкат")


if __name__ == "__main__":
    unittest.main()
