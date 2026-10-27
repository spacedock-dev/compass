"""Claims the shipped skill and the reader-state record make, bound to the React sources.

The previous interface's tests read its own JavaScript for these. The page now lives in
`frontend/src`, and nothing else compares the prose to it, so a heading renamed in one place
and not the other ships green and tells a reader to look for a name the board never draws.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import ClassVar

ROOT = Path(__file__).resolve().parents[4]
SKILL = (ROOT / "compass/skills/compass/SKILL.md").read_text(encoding="utf-8")
STATE_DOC = (ROOT / "docs/design-reader-state.md").read_text(encoding="utf-8")
SRC = ROOT / "frontend/src"


def _sources(suffix: str) -> dict[Path, str]:
    return {
        path: path.read_text(encoding="utf-8")
        for path in sorted(SRC.rglob(f"*{suffix}"))
        if ".test." not in path.name
    }


class TheAttentionHeadingsTheSkillNamesAreTheOnesTheBoardDrawsTest(unittest.TestCase):
    def _skill_headings(self) -> set[str]:
        section = SKILL.split("\n## Attention\n", 1)[1].split("\n## ", 1)[0]
        return set(re.findall(r"\*\*([A-Z][A-Za-z ,]+?)\*\*", section))

    def _rendered_headings(self) -> set[str]:
        view = (SRC / "attention/AttentionView.tsx").read_text(encoding="utf-8")
        rendered = set(re.findall(r"<Heading section=\"[a-z-]+\">([^<]+)</Heading>", view))
        return rendered | set(re.findall(r'title="([A-Z][A-Za-z ,]+)"', view))

    def test_the_two_name_the_same_headings(self) -> None:
        self.assertEqual(
            self._rendered_headings(),
            self._skill_headings(),
            "the Attention headings moved; the skill body and `AttentionView.tsx` have to move together",
        )

    def test_the_headings_are_the_six_the_board_has_always_drawn(self) -> None:
        # Pinned by name so an empty derivation on both sides cannot pass the equality above.
        self.assertEqual(
            {
                "Needs you now",
                "At risk",
                "Close the loop",
                "Coming next",
                "Also at risk, off the session count",
                "Not on this board yet",
            },
            self._rendered_headings(),
        )

    def test_names_the_skill_once_carried_are_not_headings_the_board_draws(self) -> None:
        for dead in ("Safe to close", "What's next"):
            self.assertNotIn(dead, SKILL, f"{dead} is not a heading the board renders")


class TheReaderStateRecordCitesRealOwnersTest(unittest.TestCase):
    CITATION = re.compile(r"`(frontend/src/[\w/.\-]+)`: ((?:`[^`]+`(?:, )?)+)")

    def test_every_cited_file_exists_and_names_every_cited_symbol(self) -> None:
        cited = 0
        for match in self.CITATION.finditer(STATE_DOC):
            path = ROOT / match.group(1)
            with self.subTest(file=match.group(1)):
                self.assertTrue(path.is_file(), f"{match.group(1)} does not exist")
                text = path.read_text(encoding="utf-8")
                for symbol in re.findall(r"`([^`]+)`", match.group(2)):
                    cited += 1
                    # `STORAGE_KEYS.memoPrefix` is cited by the member the owner declares.
                    self.assertIn(symbol.rsplit(".", 1)[-1], text, f"{symbol} is not in the file")
        self.assertGreater(cited, 150, "the derivation found almost nothing to check")


class OnlyTheTerminalScrollsTest(unittest.TestCase):
    """A replaced scroll container needs its own restoration lane (`design-reader-state.md`)."""

    def test_overflow_forms_and_the_one_auto_scroller(self) -> None:
        forms: set[str] = set()
        scrollers: list[str] = []
        for text in _sources(".css").values():
            css = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
            forms |= {
                f"{prop.lower()}:{' '.join(value.split()).lower()}"
                for prop, value in re.findall(
                    r"(?<![a-z-])(overflow(?:-[a-z]+)?)\s*:\s*([^;}]+)", css, re.IGNORECASE
                )
            }
            scrollers += [
                rule.strip()
                for rule, _ in re.findall(
                    r"([^{}]+)\{([^{}]*overflow(?:-[xy])?\s*:\s*(?:auto|scroll)[^{}]*)\}", css
                )
            ]
        self.assertEqual(
            ["overflow-wrap:anywhere", "overflow:auto", "overflow:hidden"],
            sorted(forms),
        )
        self.assertEqual([".pc-terminal-viewport"], scrollers)
        for form in sorted(forms):
            with self.subTest(form=form):
                self.assertIn(f"`{form}`", STATE_DOC)


class TheDriftCardControlsTheDocsDescribeAreTheOnesTheCardDrawsTest(unittest.TestCase):
    """The card draws its re-run control once a reading exists and offers Steer back with a departure only.

    Three user-facing documents once said a current result has no re-run control and that a claim alone
    offers Steer back; the card stopped doing either, and no other check compares them to it.
    """

    DOCS: ClassVar[dict[str, str]] = {
        "README.md": (ROOT / "README.md").read_text(encoding="utf-8"),
        "docs/promise-map.md": (ROOT / "docs/promise-map.md").read_text(encoding="utf-8"),
        "SKILL.md": SKILL,
    }

    def _flat(self, text: str) -> str:
        return re.sub(r"\s+", " ", text)

    def test_no_document_says_a_current_result_has_no_rerun_control(self) -> None:
        for name, text in self.DOCS.items():
            flat = self._flat(text)
            for stale in (
                "has no rerun button",
                "offers no rerun button",
                "offers no second run control",
            ):
                with self.subTest(document=name, stale=stale):
                    self.assertNotIn(stale, flat)

    def test_no_document_says_a_claim_alone_offers_steer_back(self) -> None:
        for name, text in self.DOCS.items():
            with self.subTest(document=name):
                self.assertNotIn("A claim alone offers Steer back", self._flat(text))

    def test_each_document_names_both_header_controls(self) -> None:
        sentences = (SRC / "drift/sentences.ts").read_text(encoding="utf-8")
        self.assertIn("RERUN_STALE = 'Check again'", sentences)
        for name, text in self.DOCS.items():
            flat = self._flat(text)
            with self.subTest(document=name):
                self.assertIn("Check again", flat)
                self.assertIn("Analyze again", flat)


if __name__ == "__main__":
    unittest.main()
