"""Doc-sync, doc-structure surfaces: entry points, paths, commands, skills, runbooks,
ADRs, STATUS, gotchas, ROADMAP. Conventions are stated in AGENTS.md."""

import re
import unittest

from tools import docsync

ROOT = docsync.ROOT
DOCS = docsync.doc_files()
ADR_NAME = re.compile(r"^(\d{4})-[a-z0-9-]+\.md$")
AGENTS_SECTIONS = ["Project", "Verify budget", "Task map", "Hard boundaries", "Workflow rules",
                   "Parallel work"]
STATUS_SECTIONS = ["Done", "In progress", "Next", "Known limitations", "Decisions"]


def headings(md, level):
    return re.findall(rf"^{'#' * level} (.+?)\s*$", docsync.strip_fenced(md), re.M)


def adr_files():
    return sorted((ROOT / "docs" / "decisions").glob("*.md"))


def adr_title(path):
    return docsync.read(str(path.relative_to(ROOT))).splitlines()[0].lstrip("# ").strip()


class EntryPointTest(unittest.TestCase):
    def test_claude_md_only_points_to_agents_md(self):
        self.assertEqual(docsync.read("CLAUDE.md").strip(), "@AGENTS.md")

    def test_agents_md_structure_and_budget(self):
        md = docsync.read("AGENTS.md")
        self.assertLessEqual(len(md.splitlines()), 80, "AGENTS.md budget is 80 lines")
        self.assertEqual(headings(md, 2), AGENTS_SECTIONS)
        self.assertRegex(docsync.section(md, "Verify budget"), r"`make verify`: ~[\d.]+ s \(measured \d{4}-\d\d-\d\d\)")
        head, rows = docsync.table(docsync.section(md, "Task map"))
        self.assertEqual(head, ["Task", "Read"])
        boundaries = re.findall(r"^\d+\. ", docsync.section(md, "Hard boundaries"), re.M)
        self.assertGreaterEqual(len(boundaries), 5)

    def test_every_runbook_is_in_the_task_map(self):
        task_map = docsync.section(docsync.read("AGENTS.md"), "Task map")
        for rb in sorted((ROOT / "docs" / "runbooks").glob("*.md")):
            self.assertIn(f"`docs/runbooks/{rb.name}`", task_map)


class ReferencesTest(unittest.TestCase):
    def test_backticked_repo_paths_exist(self):
        broken = [f"{doc}: `{tok}`" for doc in DOCS for tok in docsync.backticks(docsync.read(doc))
                  if docsync.looks_like_repo_path(tok) and not docsync.repo_path_exists(tok)]
        self.assertEqual(broken, [], "backticked paths that do not exist (external paths must start with ~ or /)")

    def test_relative_markdown_links_exist(self):
        broken = []
        for doc in DOCS:
            for target in re.findall(r"\]\(([^)#\s]+)\)", docsync.strip_fenced(docsync.read(doc))):
                if "://" not in target and not (ROOT / doc).parent.joinpath(target).exists():
                    broken.append(f"{doc} -> {target}")
        self.assertEqual(broken, [])

    def test_make_targets_mentioned_anywhere_exist(self):
        targets = docsync.makefile_targets()
        missing = [f"{doc}: make {t}" for doc in DOCS for t in sorted(docsync.make_invocations(docsync.read(doc)))
                   if t not in targets]
        self.assertEqual(missing, [], "docs mention make targets that the Makefile lacks")

    def test_scripts_in_fenced_commands_exist(self):
        missing = [f"{doc}: {s}" for doc in DOCS for s in sorted(docsync.command_scripts(docsync.read(doc)))
                   if not (ROOT / s).exists()]
        self.assertEqual(missing, [])


class SkillsAndRunbooksTest(unittest.TestCase):
    def test_skills_are_thin_pointers_to_runbooks(self):
        skills = sorted((ROOT / ".claude" / "skills").glob("*/SKILL.md"))
        self.assertTrue(skills)
        pointed = set()
        for skill in skills:
            text = skill.read_text(encoding="utf-8")
            where = skill.relative_to(ROOT)
            self.assertLessEqual(len(text.splitlines()), 40, f"{where}: skills are <= 40 lines")
            front = re.match(r"^---\nname: (.+)\ndescription: (.+)\n---\n", text)
            self.assertIsNotNone(front, f"{where}: needs name/description front matter")
            self.assertEqual(front.group(1), skill.parent.name)
            self.assertRegex(front.group(2), r"^Use (when|before) ")
            self.assertNotRegex(text, r"(?m)^\d+\. ", f"{where}: steps belong in the runbook, not the skill")
            refs = re.findall(r"docs/runbooks/[\w-]+\.md", text)
            self.assertTrue(refs, f"{where}: must point to a runbook")
            pointed.update(refs)
        runbooks = {f"docs/runbooks/{p.name}" for p in (ROOT / "docs" / "runbooks").glob("*.md")}
        self.assertEqual(pointed, runbooks, "every runbook needs exactly the skills that point to it")

    def test_runbooks_are_numbered_recipes_with_docs_and_verify_steps(self):
        for rb in sorted((ROOT / "docs" / "runbooks").glob("*.md")):
            steps = re.findall(r"(?m)^\d+\. (.*)$", rb.read_text(encoding="utf-8"))
            self.assertGreaterEqual(len(steps), 3, rb.name)
            self.assertTrue(any(s.startswith("Update documentation") for s in steps),
                            f"{rb.name}: needs an 'Update documentation' step")
            self.assertTrue(any("make verify" in s for s in steps), f"{rb.name}: needs a `make verify` step")


class ContinuityDocsTest(unittest.TestCase):
    def test_adrs_are_numbered_short_and_have_a_status(self):
        numbers = []
        for adr in adr_files():
            m = ADR_NAME.match(adr.name)
            self.assertIsNotNone(m, f"{adr.name}: name must be NNNN-slug.md")
            numbers.append(int(m.group(1)))
            text = adr.read_text(encoding="utf-8")
            self.assertLessEqual(len(text.splitlines()), 25, f"{adr.name}: ADRs are <= 25 lines")
            self.assertRegex(text.splitlines()[0], rf"^# {m.group(1)} — \S")
            self.assertRegex(text, r"(?m)^Status: (Proposed|Accepted|Superseded)\b")
            for section in ("Context", "Decision", "Consequences"):
                self.assertRegex(text, rf"(?m)^## {section}", f"{adr.name}: missing '## {section}'")
        self.assertEqual(numbers, list(range(1, len(numbers) + 1)), "ADR numbers must be contiguous")

    def test_status_md_shape_and_decisions_mirror_adrs(self):
        md = docsync.read("docs/STATUS.md")
        self.assertLessEqual(len(md.splitlines()), 40, "docs/STATUS.md budget is 40 lines")
        self.assertEqual(headings(md, 2), STATUS_SECTIONS)
        lines = [ln for ln in docsync.section(md, "Decisions").splitlines() if ln.strip()]
        listed = []
        for ln in lines:
            m = re.fullmatch(r"- \[(.+)\]\(decisions/(\d{4}-[a-z0-9-]+\.md)\)", ln)
            self.assertIsNotNone(m, f"Decisions holds only one-line ADR links, got: {ln!r}")
            listed.append(m.group(2))
            self.assertEqual(m.group(1), adr_title(ROOT / "docs" / "decisions" / m.group(2)),
                             f"title of {m.group(2)} differs from the ADR heading")
        self.assertEqual(listed, [p.name for p in adr_files()])

    def test_gotchas_budget_and_housekeeping_rule(self):
        md = docsync.read("docs/gotchas.md")
        self.assertLessEqual(len(md.splitlines()), 40, "docs/gotchas.md budget is 40 lines")
        self.assertIn("re-read the file", md)

    def test_roadmap_items_have_priorities(self):
        items = re.findall(r"(?m)^- (.*)$", docsync.read("docs/ROADMAP.md"))
        self.assertTrue(items)
        for item in items:
            self.assertRegex(item, r"^\*\*P[0-3]\*\* ", f"ROADMAP item without priority: {item[:50]}")


if __name__ == "__main__":
    unittest.main()
