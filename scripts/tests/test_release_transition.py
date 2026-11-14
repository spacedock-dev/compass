"""The release's decisions, rehearsed against temporary repositories.

The workflow's inline shell used to make these decisions where nothing could
exercise them, which is how a pipe closed early under `pipefail` once broke
resuming. Every figure below is read from a real temporary Git repository with a
bare origin; nothing reaches the real remote, a real tag or a version field.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bump_version
import release_transition as rt

if TYPE_CHECKING:
    from tests.release_fixture import MANIFESTS, WEB, Fixture, git
else:
    from release_fixture import MANIFESTS, WEB, Fixture, git

SHA = re.compile(r"^[0-9a-f]{40}$")
SCRIPT = Path(__file__).resolve().parents[1] / "release_transition.py"


class TagFormTest(unittest.TestCase):
    def test_strict_semver_with_either_prefix_is_accepted(self) -> None:
        self.assertEqual("1.2.3", rt.parse_tag("v1.2.3")[0])
        self.assertEqual("1.2.3", rt.parse_tag("1.2.3")[0])
        self.assertEqual((10, 0, 0), rt.parse_tag("v10.0.0")[1])

    def test_anything_else_is_refused_before_it_can_reach_a_command(self) -> None:
        for tag in (
            "v01.2.3",
            "v1.2",
            "1.2.3-rc1",
            "v1.2.3\n",
            " v1.2.3",
            "v1.2.3; touch x",
            "$(id)",
            "refs/tags/v1.2.3",
            "",
        ):
            with self.subTest(tag=tag), self.assertRaises(rt.ReleaseError):
                rt.parse_tag(tag)

    def test_the_tag_grammar_is_the_bump_scripts_own(self) -> None:
        # The workflow validates the tag with this module and bumps with the
        # other script; two grammars would let a tag pass one and fail the other
        # after the run had started.
        self.assertEqual(bump_version.SEMVER_RE.pattern, rt.SEMVER.pattern)


class MonotonicTest(unittest.TestCase):
    def test_a_greater_tag_passes_numerically_not_lexically(self) -> None:
        rt.check_monotonic("v0.10.0", ["v0.9.0", "0.2.0", "v0.1.0"])

    def test_an_equal_or_greater_existing_tag_refuses_back_tagging(self) -> None:
        for existing in ("0.2.0", "v0.3.0", "1.0.0"):
            with self.subTest(existing=existing), self.assertRaises(rt.ReleaseError) as caught:
                rt.check_monotonic("v0.2.0", [existing])
            self.assertIn("back-tagging", str(caught.exception))

    def test_the_tag_itself_and_non_release_names_are_ignored(self) -> None:
        rt.check_monotonic("v0.2.0", ["v0.2.0", "latest", "v0.1.0-rc1", ""])


class ReleaseCommitLookupTest(unittest.TestCase):
    LOG = (
        "ddd\tchore(release): v0.2.0-extra\n"
        "ccc\tfeat: later work\n"
        "bbb\tchore(release): v0.2.0\n"
        "aaa\tchore(release): v0.2.0"
    )

    def test_the_newest_exact_subject_wins(self) -> None:
        self.assertEqual("bbb", rt.find_release_commit(self.LOG, "v0.2.0"))

    def test_a_prefix_or_a_different_tag_does_not_match(self) -> None:
        self.assertIsNone(rt.find_release_commit(self.LOG, "v0.3.0"))
        self.assertIsNone(rt.find_release_commit(self.LOG, "0.2.0"))
        self.assertIsNone(rt.find_release_commit("", "v0.2.0"))


class ResolveTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = Fixture(self)

    def resolve(self, tag: str) -> rt.Resolution:
        self.fx.fetch()
        return rt.resolve(self.fx.work, tag)

    def test_a_fresh_release_targets_the_main_tip_as_a_full_sha(self) -> None:
        tip = self.fx.commit("feat: work")
        self.fx.tag("v0.2.0")
        result = self.resolve("v0.2.0")
        self.assertEqual("fresh", result.mode)
        self.assertEqual("0.2.0", result.version)
        self.assertEqual(tip, result.target)
        self.assertRegex(result.target, SHA)
        self.assertEqual("", result.release_commit)

    def test_the_target_is_main_at_resolution_not_the_tagged_commit(self) -> None:
        tagged = self.fx.commit("feat: tagged")
        self.fx.tag("v0.2.0")
        tip = self.fx.commit("feat: after the tag")
        result = self.resolve("v0.2.0")
        self.assertEqual(tip, result.target)
        self.assertNotEqual(tagged, result.target)

    def test_back_tagging_is_refused(self) -> None:
        self.fx.commit("feat: work")
        self.fx.tag("v0.0.9")
        with self.assertRaises(rt.ReleaseError) as caught:
            self.resolve("v0.0.9")
        self.assertIn("strictly greater", str(caught.exception))

    def test_a_tag_that_is_not_on_main_is_refused(self) -> None:
        git(self.fx.work, "checkout", "-q", "-b", "side")
        side = self.fx.commit("feat: off main", push=False, branch="side")
        git(self.fx.work, "checkout", "-q", "main")
        git(self.fx.work, "-c", "tag.gpgsign=false", "tag", "v0.2.0", side)
        git(self.fx.work, "push", "-q", "origin", "refs/tags/v0.2.0")
        with self.assertRaises(rt.ReleaseError) as caught:
            self.resolve("v0.2.0")
        self.assertIn("not on main", str(caught.exception))

    def release_commit(self, tag: str, version: str) -> str:
        return self.fx.release_commit(tag, version)

    def test_an_existing_release_commit_resumes_onto_itself(self) -> None:
        self.fx.commit("feat: work")
        self.fx.tag("v0.2.0")
        release = self.release_commit("v0.2.0", "0.2.0")
        self.fx.commit("feat: merged while the release was down")
        result = self.resolve("v0.2.0")
        self.assertEqual("resume", result.mode)
        self.assertEqual(release, result.target)
        self.assertEqual(release, result.release_commit)

    def test_resume_survives_a_later_release_and_skips_the_monotonic_check(self) -> None:
        self.fx.commit("feat: work")
        self.fx.tag("v0.2.0")
        release = self.release_commit("v0.2.0", "0.2.0")
        self.fx.commit("feat: more work")
        self.fx.tag("v0.3.0")
        self.release_commit("v0.3.0", "0.3.0")
        result = self.resolve("v0.2.0")
        self.assertEqual(("resume", release), (result.mode, result.target))

    def test_a_release_commit_carrying_the_wrong_version_is_not_resumed(self) -> None:
        self.fx.commit("feat: work")
        self.fx.tag("v0.2.0")
        self.release_commit("v0.2.0", "0.9.9")
        with self.assertRaises(rt.ReleaseError) as caught:
            self.resolve("v0.2.0")
        self.assertIn("refusing to resume", str(caught.exception))

    def test_a_release_commit_the_release_bot_did_not_commit_is_not_resumed(self) -> None:
        # A squash-merged pull request titled like a release commit lands with GitHub's
        # own committer, so its subject and manifests alone would otherwise be enough.
        self.fx.commit("feat: work")
        self.fx.tag("v0.2.0")
        self.fx.release_commit("v0.2.0", "0.2.0", committer=("Someone", "someone@example.invalid"))
        with self.assertRaises(rt.ReleaseError) as caught:
            self.resolve("v0.2.0")
        text = str(caught.exception)
        self.assertIn("refusing to resume", text)
        self.assertIn("someone@example.invalid", text)
        self.assertIn(rt.BOT_EMAIL, text)

    def test_a_release_commit_that_changes_more_than_the_version_is_not_resumed(self) -> None:
        manifest = json.loads((self.fx.work / MANIFESTS[1]).read_text(encoding="utf-8"))
        manifest["description"] = "changed alongside the version"
        for name, extra in {
            "another file": {"notes.txt": "rode along with the bump\n"},
            "another manifest field": {MANIFESTS[1]: json.dumps(manifest, indent=2) + "\n"},
        }.items():
            with self.subTest(name):
                fx = Fixture(self)
                fx.commit("feat: work")
                fx.tag("v0.2.0")
                fx.release_commit("v0.2.0", "0.2.0", extra=extra)
                fx.fetch()
                with self.assertRaises(rt.ReleaseError) as caught:
                    rt.resolve(fx.work, "v0.2.0")
                self.assertIn("refusing to resume", str(caught.exception))

    def test_a_merge_commit_titled_as_a_release_is_not_resumed(self) -> None:
        # Its diff against the first parent can be the version alone while the second
        # parent brings anything, so a release commit must have exactly one parent.
        self.fx.commit("feat: work")
        self.fx.tag("v0.2.0")
        base = git(self.fx.work, "rev-parse", "HEAD")
        git(self.fx.work, "checkout", "-q", "-b", "side", base)
        self.fx.commit("feat: from the side", push=False, branch="side")
        git(self.fx.work, "checkout", "-q", "main")
        self.fx.release_commit("v0.2.0", "0.2.0")
        git(
            self.fx.work, "-c", f"user.name={rt.BOT_NAME}", "-c", f"user.email={rt.BOT_EMAIL}",
            "merge", "-q", "--no-ff", "-m", "chore(release): v0.2.0", "side",
        )  # fmt: skip
        git(self.fx.work, "push", "-q", "origin", "main")
        with self.assertRaises(rt.ReleaseError) as caught:
            self.resolve("v0.2.0")
        self.assertIn("one parent", str(caught.exception))

    def test_a_bot_release_commit_of_the_version_alone_still_resumes(self) -> None:
        # The shape every release commit on the real main has: one parent, the release
        # bot as committer, and a diff of the owned manifests' version values only.
        self.fx.commit("feat: work")
        self.fx.tag("v0.2.0")
        release = self.release_commit("v0.2.0", "0.2.0")
        self.assertEqual(("resume", release), self.mode_and_target("v0.2.0"))

    def mode_and_target(self, tag: str) -> tuple[str, str]:
        result = self.resolve(tag)
        return result.mode, result.target

    def test_the_same_version_under_both_tag_spellings_is_refused_in_either_mode(self) -> None:
        self.fx.commit("feat: work")
        self.fx.tag("v0.2.0")
        self.fx.tag("0.2.0")
        with self.assertRaises(rt.ReleaseError) as fresh:
            self.resolve("v0.2.0")
        self.assertIn("0.2.0 and v0.2.0", str(fresh.exception))
        self.release_commit("v0.2.0", "0.2.0")
        for tag in ("v0.2.0", "0.2.0"):
            with self.subTest(tag=tag), self.assertRaises(rt.ReleaseError) as caught:
                self.resolve(tag)
            self.assertIn("0.2.0 and v0.2.0", str(caught.exception))

    def test_a_fresh_release_is_the_latest(self) -> None:
        self.fx.commit("feat: work")
        self.fx.tag("v0.2.0")
        result = self.resolve("v0.2.0")
        self.assertTrue(result.latest)
        self.assertEqual("true", result.outputs()["latest"])

    def test_a_resume_is_the_latest_only_while_no_higher_release_tag_exists(self) -> None:
        self.fx.commit("feat: work")
        self.fx.tag("v0.2.0")
        self.release_commit("v0.2.0", "0.2.0")
        self.assertTrue(self.resolve("v0.2.0").latest)
        self.fx.commit("feat: more work")
        self.fx.tag("v0.10.0")
        result = self.resolve("v0.2.0")
        self.assertEqual("resume", result.mode)
        self.assertFalse(result.latest)
        self.assertEqual("false", result.outputs()["latest"])


class ReleaseHoldTest(unittest.TestCase):
    """The recorded hold on cutting a release, as a guard rather than a sentence.

    The hold is a tracked `RELEASE_HOLD` file on main. `resolve` is the one step both a
    fresh release and a resume pass through, and it runs first in a job that holds no
    credentials, so refusing there stops the workflow before anything can be tagged,
    verified, pushed or published.
    """

    REASON = "Hold: the legacy frontend is not retired yet.\nLifted by deleting this file.\n"

    def setUp(self) -> None:
        self.fx = Fixture(self)

    def resolve(self, tag: str) -> rt.Resolution:
        self.fx.fetch()
        return rt.resolve(self.fx.work, tag)

    def hold(self) -> None:
        self.fx.commit("chore: record the release hold", files={rt.HOLD_FILE: self.REASON})

    def lift(self) -> None:
        self.fx.sync()
        git(self.fx.work, "rm", "-q", rt.HOLD_FILE)
        git(self.fx.work, "commit", "-q", "-m", "chore: lift the release hold")
        git(self.fx.work, "push", "-q", "origin", "main")

    def release_commit(self, tag: str, version: str) -> str:
        return self.fx.release_commit(tag, version)

    def test_the_marker_is_named_in_one_place_at_the_repository_root(self) -> None:
        self.assertEqual("RELEASE_HOLD", rt.HOLD_FILE)

    def test_a_fresh_release_is_refused_while_the_marker_is_on_main(self) -> None:
        self.fx.commit("feat: work")
        self.fx.tag("v0.2.0")
        self.hold()
        before = self.fx.origin_snapshot()
        with self.assertRaises(rt.ReleaseError) as caught:
            self.resolve("v0.2.0")
        text = str(caught.exception)
        self.assertIn("RELEASE_HOLD", text)
        self.assertIn("hold", text.lower())
        self.assertIn("Re-run all jobs", text)
        self.assertEqual(before, self.fx.origin_snapshot())

    def test_a_resume_is_refused_too(self) -> None:
        self.fx.commit("feat: work")
        self.fx.tag("v0.2.0")
        self.release_commit("v0.2.0", "0.2.0")
        self.assertEqual("resume", self.resolve("v0.2.0").mode)
        self.hold()
        with self.assertRaises(rt.ReleaseError) as caught:
            self.resolve("v0.2.0")
        self.assertIn("RELEASE_HOLD", str(caught.exception))

    def test_removing_the_marker_from_main_unblocks_both_modes(self) -> None:
        self.fx.commit("feat: work")
        self.fx.tag("v0.2.0")
        self.hold()
        with self.assertRaises(rt.ReleaseError):
            self.resolve("v0.2.0")
        self.lift()
        self.assertEqual("fresh", self.resolve("v0.2.0").mode)
        self.release_commit("v0.2.0", "0.2.0")
        self.assertEqual("resume", self.resolve("v0.2.0").mode)

    def test_the_hold_is_read_from_main_not_from_the_checkout(self) -> None:
        # A stray file in the working tree is not a recorded hold, and a hold that main
        # carries is not lifted by deleting the file from a checkout of it.
        self.fx.commit("feat: work")
        self.fx.tag("v0.2.0")
        (self.fx.work / rt.HOLD_FILE).write_text("local only\n", encoding="utf-8")
        self.assertEqual("fresh", self.resolve("v0.2.0").mode)
        (self.fx.work / rt.HOLD_FILE).unlink()
        self.hold()
        (self.fx.work / rt.HOLD_FILE).unlink()
        with self.assertRaises(rt.ReleaseError):
            self.resolve("v0.2.0")

    def test_the_hold_is_told_before_a_back_tagging_complaint(self) -> None:
        # Pins the one ordering that matters to an operator: told to wait, not told their
        # number is wrong. Other tag judgements (not on main, resume target) are not pinned
        # by this test.
        self.fx.commit("feat: work")
        self.fx.tag("v0.0.9")
        self.hold()
        with self.assertRaises(rt.ReleaseError) as caught:
            self.resolve("v0.0.9")
        self.assertIn("RELEASE_HOLD", str(caught.exception))

    def test_the_hold_is_read_from_the_main_ref_not_from_head(self) -> None:
        self.fx.commit("feat: work")
        self.fx.tag("v0.2.0")
        self.fx.fetch()
        # A local commit that carries the marker, never pushed: HEAD holds, main does not.
        (self.fx.work / rt.HOLD_FILE).write_text(self.REASON, encoding="utf-8")
        git(self.fx.work, "add", rt.HOLD_FILE)
        git(self.fx.work, "commit", "-q", "-m", "local only")
        self.assertEqual("fresh", rt.resolve(self.fx.work, "v0.2.0").mode)

    def test_a_hold_pushed_after_resolve_stops_a_resume_before_any_mutation(self) -> None:
        self.fx.commit("feat: work")
        self.fx.tag("v0.2.0")
        self.release_commit("v0.2.0", "0.2.0")
        self.fx.fetch()
        before = self.fx.origin_snapshot()
        with self.assertRaises(rt.ReleaseError) as caught:
            rt.rehearse(
                self.fx.work,
                "v0.2.0",
                after={"resolve": lambda _resolution: self.hold()},
            )
        self.assertIn("RELEASE_HOLD", str(caught.exception))
        # The only change on origin is the hold commit itself: no bump, tag move or stable.
        after = self.fx.origin_snapshot()
        changed = {ref for ref in after if before.get(ref) != after[ref]}
        self.assertEqual({"refs/heads/main"}, changed)
        self.assertIsNone(self.fx.origin_rev("refs/heads/stable"))

    def test_a_hold_pushed_after_resolve_stops_a_fresh_release_too(self) -> None:
        self.fx.commit("feat: work")
        self.fx.tag("v0.2.0")
        with self.assertRaises(rt.ReleaseError):
            rt.rehearse(
                self.fx.work,
                "v0.2.0",
                after={"resolve": lambda _resolution: self.hold()},
            )
        self.assertIsNone(self.fx.origin_rev("refs/heads/stable"))

    def test_assert_checkout_itself_refuses_a_hold(self) -> None:
        self.fx.commit("feat: work")
        self.fx.tag("v0.2.0")
        release = self.release_commit("v0.2.0", "0.2.0")
        self.hold()
        self.fx.fetch()
        git(self.fx.work, "checkout", "-q", "--detach", release)
        with self.assertRaises(rt.ReleaseError) as caught:
            rt.assert_checkout(self.fx.work, "resume", release, "v0.2.0", verified=release)
        self.assertIn("RELEASE_HOLD", str(caught.exception))

    def test_a_repository_that_cannot_answer_fails_closed_not_open(self) -> None:
        # An unreadable tree is not "no hold". `git ls-tree` exits nonzero on a tree it
        # cannot read, and `cat-file -e` could not tell that apart from an absent path.
        for ref in ("0" * 40, "refs/heads/does-not-exist"):
            with self.subTest(ref=ref), self.assertRaises(rt.ReleaseError) as caught:
                rt.assert_no_hold(self.fx.work, ref)
            self.assertIn("cannot read", str(caught.exception))
            self.assertNotIn("on hold", str(caught.exception))

    def test_the_command_exits_nonzero_with_one_annotation_line_and_writes_no_outputs(self) -> None:
        self.fx.commit("feat: work")
        self.fx.tag("v0.2.0")
        self.hold()
        self.fx.fetch()
        outputs = self.fx.root / "github-output"
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--repo",
                str(self.fx.work),
                "resolve",
                "--tag",
                "v0.2.0",
                "--github-output",
                str(outputs),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertEqual(1, len(result.stdout.splitlines()), result.stdout)
        self.assertTrue(result.stdout.startswith("::error::"))
        self.assertFalse(outputs.exists())

    def test_the_whole_rehearsal_stops_at_resolve_and_leaves_the_remote_untouched(self) -> None:
        self.fx.commit("feat: work")
        self.fx.tag("v0.2.0")
        self.hold()
        before = self.fx.origin_snapshot()
        with self.assertRaises(rt.ReleaseError):
            rt.rehearse(self.fx.work, "v0.2.0")
        self.assertEqual(before, self.fx.origin_snapshot())


class AssertCheckoutTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = Fixture(self)
        self.tip = self.fx.commit("feat: work")
        self.fx.tag("v0.2.0")

    def checkout_main(self) -> None:
        self.fx.fetch()
        git(self.fx.work, "checkout", "-q", "--detach", "origin/main")

    def test_fresh_passes_when_the_checkout_is_the_verified_target(self) -> None:
        self.checkout_main()
        rt.assert_checkout(self.fx.work, "fresh", self.tip, "v0.2.0", verified=self.tip)

    def test_fresh_fails_safely_when_main_moved_after_resolution(self) -> None:
        self.fx.commit("feat: landed during verification")
        self.checkout_main()
        before = self.fx.origin_snapshot()
        with self.assertRaises(rt.ReleaseError) as caught:
            rt.assert_checkout(self.fx.work, "fresh", self.tip, "v0.2.0", verified=self.tip)
        self.assertIn("Re-run all jobs", str(caught.exception))
        self.assertIn("re-run", str(caught.exception).lower())
        self.assertEqual(before, self.fx.origin_snapshot())

    def test_the_verification_job_must_have_checked_the_same_target(self) -> None:
        self.checkout_main()
        other = "0" * 40
        with self.assertRaises(rt.ReleaseError) as caught:
            rt.assert_checkout(self.fx.work, "fresh", self.tip, "v0.2.0", verified=other)
        self.assertIn("verified", str(caught.exception))
        with self.assertRaises(rt.ReleaseError):
            rt.assert_checkout(self.fx.work, "fresh", self.tip, "v0.2.0", verified="")

    def test_a_malformed_target_is_refused_before_any_git_command_uses_it(self) -> None:
        self.checkout_main()
        for bad in ("main", "HEAD", "--upload-pack=x", self.tip[:12], self.tip.upper(), ""):
            with self.subTest(bad=bad), self.assertRaises(rt.ReleaseError):
                rt.assert_checkout(self.fx.work, "fresh", bad, "v0.2.0", verified=bad)

    def test_an_unknown_mode_is_refused(self) -> None:
        self.checkout_main()
        with self.assertRaises(rt.ReleaseError):
            rt.assert_checkout(self.fx.work, "maybe", self.tip, "v0.2.0", verified=self.tip)

    def test_resume_accepts_a_release_commit_that_main_has_moved_past(self) -> None:
        release = self.fx.release_commit("v0.2.0", "0.2.0")
        self.fx.commit("feat: later")
        self.checkout_main()
        rt.assert_checkout(self.fx.work, "resume", release, "v0.2.0", verified=release)

    def test_resume_asks_again_who_committed_the_release_commit_and_what_it_changed(
        self,
    ) -> None:
        # `resolve` is the gate; the job that holds the key checks again rather than
        # trusting the target that resolve reported.
        for name, kwargs in {
            "committer": {"committer": ("Someone", "someone@example.invalid")},
            "diff": {"extra": {"notes.txt": "rode along\n"}},
        }.items():
            with self.subTest(name):
                fx = Fixture(self)
                fx.commit("feat: work")
                release = fx.release_commit("v0.2.0", "0.2.0", **kwargs)  # type: ignore[arg-type]
                fx.fetch()
                git(fx.work, "checkout", "-q", "--detach", release)
                with self.assertRaises(rt.ReleaseError):
                    rt.assert_checkout(fx.work, "resume", release, "v0.2.0", verified=release)

    def test_resume_refuses_a_target_main_does_not_contain(self) -> None:
        git(self.fx.work, "checkout", "-q", "-b", "side")
        side = self.fx.commit("feat: off main", push=False, branch="side")
        self.checkout_main()
        git(self.fx.work, "fetch", "-q", "--no-tags", ".", "side:refs/heads/side")
        with self.assertRaises(rt.ReleaseError) as caught:
            rt.assert_checkout(self.fx.work, "resume", side, "v0.2.0", verified=side)
        self.assertIn("not on main", str(caught.exception))

    def test_resume_refuses_a_target_whose_manifests_carry_another_version(self) -> None:
        self.checkout_main()
        with self.assertRaises(rt.ReleaseError):
            rt.assert_checkout(self.fx.work, "resume", self.tip, "v0.2.0", verified=self.tip)

    def test_assert_head_names_both_commits(self) -> None:
        rt.assert_head(self.fx.work, self.tip)
        with self.assertRaises(rt.ReleaseError) as caught:
            rt.assert_head(self.fx.work, "1" * 40)
        self.assertIn(self.tip, str(caught.exception))


class BumpTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = Fixture(self)
        self.fx.commit("feat: work")

    def versions(self) -> set[str]:
        return {
            json.loads((self.fx.work / relative).read_text(encoding="utf-8"))["version"]
            for relative in MANIFESTS
        }

    def test_a_greater_version_is_written_to_every_owned_field(self) -> None:
        self.assertTrue(rt.bump(self.fx.work, "0.2.0"))
        self.assertEqual({"0.2.0"}, self.versions())

    def test_the_current_version_needs_no_bump(self) -> None:
        self.assertFalse(rt.bump(self.fx.work, "0.1.0"))
        self.assertEqual({"0.1.0"}, self.versions())
        self.assertEqual("", git(self.fx.work, "status", "--porcelain"))

    def test_a_lower_version_is_refused_by_the_bump_script(self) -> None:
        self.fx.set_version("0.5.0")
        with self.assertRaises(rt.ReleaseError):
            rt.bump(self.fx.work, "0.4.0")

    def test_the_release_commit_is_signed_off_and_titled_by_tag(self) -> None:
        rt.bump(self.fx.work, "0.2.0")
        sha = rt.commit_bump(self.fx.work, "v0.2.0")
        self.assertEqual(sha, git(self.fx.work, "rev-parse", "HEAD"))
        message = git(self.fx.work, "log", "-1", "--format=%B")
        self.assertTrue(message.startswith("chore(release): v0.2.0"))
        self.assertIn("Signed-off-by:", message)
        self.assertIn("Bump plugin version to 0.2.0", message)
        changed = git(self.fx.work, "diff", "--name-only", "HEAD~1", "HEAD").splitlines()
        self.assertEqual(sorted(MANIFESTS), sorted(changed))

    def test_committing_with_nothing_to_commit_is_a_noop(self) -> None:
        head = git(self.fx.work, "rev-parse", "HEAD")
        self.assertEqual(head, rt.commit_bump(self.fx.work, "v0.1.0"))
        self.assertEqual(head, git(self.fx.work, "rev-parse", "HEAD"))

    def test_the_commit_takes_only_the_owned_paths(self) -> None:
        rt.bump(self.fx.work, "0.2.0")
        (self.fx.work / "stray.txt").write_text("not part of a release", encoding="utf-8")
        rt.commit_bump(self.fx.work, "v0.2.0")
        changed = git(self.fx.work, "diff", "--name-only", "HEAD~1", "HEAD").splitlines()
        self.assertNotIn("stray.txt", changed)


class PublishStepsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = Fixture(self)
        self.fx.commit("feat: work")
        self.fx.tag("v0.2.0")
        rt.bump(self.fx.work, "0.2.0")
        self.final = rt.commit_bump(self.fx.work, "v0.2.0")

    def test_the_bump_push_is_never_forced(self) -> None:
        self.fx.commit("feat: landed first")  # origin main is now not an ancestor
        before = self.fx.origin_snapshot()
        with self.assertRaises(rt.ReleaseError):
            rt.push_bump(self.fx.work, "origin", self.final)
        self.assertEqual(before, self.fx.origin_snapshot())

    def test_the_bump_push_fast_forwards_main(self) -> None:
        rt.push_bump(self.fx.work, "origin", self.final)
        self.assertEqual(self.final, self.fx.origin_rev("refs/heads/main"))

    def test_the_tag_moves_onto_the_release_commit_even_if_it_was_elsewhere(self) -> None:
        rt.push_bump(self.fx.work, "origin", self.final)
        rt.move_tag(self.fx.work, "origin", "v0.2.0", self.final)
        self.assertEqual(self.final, self.fx.origin_rev("refs/tags/v0.2.0"))
        rt.move_tag(self.fx.work, "origin", "v0.2.0", self.final)
        self.assertEqual(self.final, self.fx.origin_rev("refs/tags/v0.2.0"))

    def test_stable_is_force_advanced_and_idempotent(self) -> None:
        rt.advance_stable(self.fx.work, "origin", self.final)
        self.assertEqual(self.final, self.fx.origin_rev("refs/heads/stable"))
        rt.advance_stable(self.fx.work, "origin", self.final)
        self.assertEqual(self.final, self.fx.origin_rev("refs/heads/stable"))

    def test_a_final_commit_that_is_not_a_full_sha_is_refused(self) -> None:
        for bad in ("main", "HEAD", "--delete", self.final[:10]):
            with self.subTest(bad=bad):
                with self.assertRaises(rt.ReleaseError):
                    rt.move_tag(self.fx.work, "origin", "v0.2.0", bad)
                with self.assertRaises(rt.ReleaseError):
                    rt.advance_stable(self.fx.work, "origin", bad)
                with self.assertRaises(rt.ReleaseError):
                    rt.push_bump(self.fx.work, "origin", bad)


class FinalCommitTest(unittest.TestCase):
    def test_fresh_publishes_head_when_it_is_the_target_or_its_direct_child(self) -> None:
        fx = Fixture(self)
        target = fx.commit("feat: work")
        self.assertEqual(target, rt.final_commit(fx.work, "fresh", target))
        rt.bump(fx.work, "0.2.0")
        child = rt.commit_bump(fx.work, "v0.2.0")
        self.assertEqual(child, rt.final_commit(fx.work, "fresh", target))

    def test_fresh_refuses_a_head_that_is_not_built_on_the_target(self) -> None:
        fx = Fixture(self)
        fx.commit("feat: work")
        fx.commit("feat: more")
        with self.assertRaises(rt.ReleaseError):
            rt.final_commit(fx.work, "fresh", "f" * 40)

    def test_resume_publishes_the_target_whatever_head_is(self) -> None:
        fx = Fixture(self)
        fx.commit("feat: work")
        self.assertEqual("f" * 40, rt.final_commit(fx.work, "resume", "f" * 40))
        with self.assertRaises(rt.ReleaseError):
            rt.final_commit(fx.work, "resume", "main")


class CommandLineTest(unittest.TestCase):
    """The subcommands the workflow actually calls, through their real entry point."""

    def setUp(self) -> None:
        self.fx = Fixture(self)
        self.tip = self.fx.commit("feat: work")
        self.fx.tag("v0.2.0")
        self.fx.fetch()

    def cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--repo", str(self.fx.work), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def test_resolve_prints_and_writes_the_four_job_outputs(self) -> None:
        output = self.fx.root / "github-output"
        result = self.cli("resolve", "--tag", "v0.2.0", "--github-output", str(output))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            f"mode=fresh\nversion=0.2.0\ntarget={self.tip}\nlatest=true\n",
            output.read_text(encoding="utf-8"),
        )

    def test_a_hostile_tag_is_refused_before_it_reaches_any_command(self) -> None:
        marker = self.fx.root / "pwned"
        for tag in (f"v1.0.0; touch {marker}", f"$(touch {marker})", "v1.0.0\nmode=resume"):
            with self.subTest(tag=tag):
                result = self.cli("resolve", "--tag", tag)
                self.assertEqual(1, result.returncode)
                self.assertIn("::error::", result.stdout)
        self.assertFalse(marker.exists())

    def test_assert_checkout_exits_nonzero_with_an_annotation_when_main_moved(self) -> None:
        self.fx.commit("feat: landed during verification")
        self.fx.fetch()
        git(self.fx.work, "checkout", "-q", "--detach", "origin/main")
        result = self.cli(
            "assert-checkout",
            "--mode",
            "fresh",
            "--target",
            self.tip,
            "--tag",
            "v0.2.0",
            "--verified",
            self.tip,
            "--verified",
            self.tip,
        )
        self.assertEqual(1, result.returncode)
        self.assertIn("::error::main is at", result.stdout)

    def test_every_verifier_must_have_seen_the_target(self) -> None:
        git(self.fx.work, "checkout", "-q", "--detach", self.tip)
        result = self.cli(
            "assert-checkout",
            "--mode",
            "fresh",
            "--target",
            self.tip,
            "--tag",
            "v0.2.0",
            "--verified",
            self.tip,
            "--verified",
            "0" * 40,
        )
        self.assertEqual(1, result.returncode)

    def test_the_rehearsal_driver_refuses_a_remote_that_is_not_a_local_path(self) -> None:
        git(self.fx.work, "remote", "set-url", "origin", "https://example.invalid/compass.git")
        result = self.cli("rehearse", "--tag", "v0.2.0")
        self.assertEqual(1, result.returncode)
        self.assertIn("not a local path", result.stdout)


class RehearsalTest(unittest.TestCase):
    """The whole sequence against a bare origin, with failures injected."""

    def setUp(self) -> None:
        self.fx = Fixture(self)

    def drive(self, tag: str, **kwargs: object) -> rt.Outcome:
        return rt.rehearse(self.fx.work, tag, **kwargs)  # type: ignore[arg-type]

    def assert_published(self, tag: str, version: str) -> str:
        final = self.fx.origin_rev("refs/heads/stable")
        assert final is not None
        self.assertEqual(final, self.fx.origin_rev(f"refs/tags/{tag}"))
        manifest = git(self.fx.origin, "show", f"{final}:{MANIFESTS[0]}")
        self.assertEqual(version, json.loads(manifest)["version"])
        return final

    def test_a_fresh_release_bumps_pushes_tags_and_advances_stable(self) -> None:
        tip = self.fx.commit("feat: work")
        self.fx.tag("v0.2.0")
        outcome = self.drive("v0.2.0")
        self.assertEqual("fresh", outcome.mode)
        final = self.assert_published("v0.2.0", "0.2.0")
        self.assertEqual(final, self.fx.origin_rev("refs/heads/main"))
        self.assertEqual(tip, git(self.fx.origin, "rev-parse", f"{final}^"))
        self.assertEqual(
            "chore(release): v0.2.0", git(self.fx.origin, "log", "-1", "--format=%s", final)
        )

    def test_a_release_of_the_version_already_carried_makes_no_bump_commit(self) -> None:
        self.fx.tag("v0.1.0")
        self.drive("v0.1.0")
        final = self.assert_published("v0.1.0", "0.1.0")
        self.assertEqual(self.fx.origin_rev("refs/heads/main"), final)
        self.assertNotEqual(
            "chore(release): v0.1.0", git(self.fx.origin, "log", "-1", "--format=%s", final)
        )

    def test_dry_run_stops_before_anything_is_pushed(self) -> None:
        self.fx.commit("feat: work")
        self.fx.tag("v0.2.0")
        before = self.fx.origin_snapshot()
        outcome = self.drive("v0.2.0", dry_run=True)
        self.assertEqual(before, self.fx.origin_snapshot())
        self.assertEqual("archive", outcome.last_phase)

    def test_main_advancing_between_resolution_and_publication_changes_nothing(self) -> None:
        self.fx.commit("feat: work")
        self.fx.tag("v0.2.0")
        before_tag = self.fx.origin_rev("refs/tags/v0.2.0")

        def advance(_: rt.Resolution) -> None:
            self.fx.commit("feat: landed during verification")

        before = self.fx.origin_snapshot()
        with self.assertRaises(rt.ReleaseError) as caught:
            self.drive("v0.2.0", after={"verify": advance})
        self.assertIn("Re-run all jobs", str(caught.exception))
        after = self.fx.origin_snapshot()
        landed = after["refs/heads/main"]
        self.assertNotEqual(before["refs/heads/main"], landed)
        # Only the advance itself moved; the release published nothing.
        self.assertEqual(before_tag, self.fx.origin_rev("refs/tags/v0.2.0"))
        self.assertIsNone(self.fx.origin_rev("refs/heads/stable"))
        self.assertEqual(landed, after["refs/heads/main"])

    def test_a_newer_main_bundle_is_never_published_for_an_older_verified_target(self) -> None:
        self.fx.commit("feat: work")
        self.fx.tag("v0.2.0")
        bundle = f"{WEB}/react.html"

        def poison(_: rt.Resolution) -> None:
            self.fx.commit("feat: a bundle nobody verified", files={bundle: "<!doctype html>\n"})

        with self.assertRaises(rt.ReleaseError):
            self.drive("v0.2.0", after={"verify": poison})
        self.assertIsNone(self.fx.origin_rev("refs/heads/stable"))
        for ref in ("refs/tags/v0.2.0", "refs/heads/stable"):
            published = self.fx.origin_rev(ref)
            if published:
                self.assertNotEqual(
                    "<!doctype html>\n", git(self.fx.origin, "show", f"{published}:{bundle}")
                )

    def test_a_rerun_after_the_failed_race_resolves_and_publishes_the_new_tip(self) -> None:
        self.fx.commit("feat: work")
        self.fx.tag("v0.2.0")

        def advance(_: rt.Resolution) -> None:
            self.fx.commit("feat: landed during verification")

        with self.assertRaises(rt.ReleaseError):
            self.drive("v0.2.0", after={"verify": advance})
        self.drive("v0.2.0")
        self.assert_published("v0.2.0", "0.2.0")

    def test_every_partial_failure_is_finished_by_a_rerun(self) -> None:
        for phase, expected_mode in (
            ("archive", "fresh"),
            ("push-bump", "resume"),
            ("move-tag", "resume"),
            ("stable", "resume"),
        ):
            with self.subTest(failing_after=phase):
                self.fx = Fixture(self)
                self.fx.commit("feat: work")
                self.fx.tag("v0.2.0")

                def boom(_: rt.Resolution) -> None:
                    message = "injected failure"
                    raise rt.ReleaseError(message)

                with self.assertRaises(rt.ReleaseError):
                    self.drive("v0.2.0", after={phase: boom})
                if phase == "archive":
                    self.assertIsNone(self.fx.origin_rev("refs/heads/stable"))
                    self.assertEqual(
                        "feat: work", git(self.fx.origin, "log", "-1", "--format=%s", "main")
                    )
                outcome = self.drive("v0.2.0")
                self.assertEqual(expected_mode, outcome.mode)
                self.assert_published("v0.2.0", "0.2.0")

    def test_a_resumed_release_publishes_its_own_commit_after_a_later_release(self) -> None:
        self.fx.commit("feat: work")
        self.fx.tag("v0.2.0")
        self.drive("v0.2.0", stop_after="push-bump")
        first = self.fx.origin_rev("refs/heads/main")
        self.fx.commit("feat: next")
        self.fx.tag("v0.3.0")
        self.drive("v0.3.0")
        self.assertNotEqual(first, self.fx.origin_rev("refs/heads/main"))
        outcome = self.drive("v0.2.0")
        self.assertEqual("resume", outcome.mode)
        self.assertEqual(first, self.fx.origin_rev("refs/tags/v0.2.0"))
        # Resuming an older release must not drag the marketplace channel backwards.
        self.assertEqual(
            self.fx.origin_rev("refs/tags/v0.3.0"), self.fx.origin_rev("refs/heads/stable")
        )
        self.assertEqual(
            "0.3.0", json.loads(git(self.fx.origin, "show", f"v0.3.0:{MANIFESTS[0]}"))["version"]
        )

    def test_a_tampered_bundle_stops_the_release_before_anything_is_pushed(self) -> None:
        self.fx.commit("feat: work")
        self.fx.commit("fix: tamper", files={f"{WEB}/react.html": "<!doctype html>\n"})
        self.fx.tag("v0.2.0")
        before = self.fx.origin_snapshot()
        with self.assertRaises(rt.ReleaseError):
            self.drive("v0.2.0")
        self.assertEqual(before, self.fx.origin_snapshot())


class RecoveryWordingTest(unittest.TestCase):
    """What an operator reads when main moved, and the shape the workflow now runs."""

    def setUp(self) -> None:
        self.fx = Fixture(self)
        self.tip = self.fx.commit("feat: work")
        self.fx.tag("v0.2.0")
        self.fx.commit("feat: landed during verification")
        self.fx.fetch()
        git(self.fx.work, "checkout", "-q", "--detach", "origin/main")

    def test_the_moved_main_message_sends_the_operator_to_rerun_all_jobs(self) -> None:
        with self.assertRaises(rt.ReleaseError) as caught:
            rt.assert_checkout(self.fx.work, "fresh", self.tip, "v0.2.0", verified=self.tip)
        text = str(caught.exception)
        self.assertIn("Re-run all jobs", text)
        self.assertNotIn("failed jobs", text)
        # The bump commit may already be on main when this is a retry of a part-run
        # release, so the message must not claim nothing was published.
        self.assertNotIn("Nothing was published", text)

    def test_resume_checks_the_target_against_main_not_against_head(self) -> None:
        # The workflow detaches onto the target before any repository code runs, so
        # HEAD is the target and ancestry has to be asked of main's own ref.
        release = self.fx.release_commit("v0.2.0", "0.2.0")
        git(self.fx.work, "checkout", "-q", "--detach", release)
        rt.assert_checkout(self.fx.work, "resume", release, "v0.2.0", verified=release)

    def test_resume_refuses_a_detached_target_main_does_not_contain(self) -> None:
        git(self.fx.work, "checkout", "-q", "-b", "side", self.tip)
        side = self.fx.commit("feat: off main", push=False, branch="side")
        git(self.fx.work, "checkout", "-q", "--detach", side)
        with self.assertRaises(rt.ReleaseError) as caught:
            rt.assert_checkout(self.fx.work, "resume", side, "v0.2.0", verified=side)
        self.assertIn("not on main", str(caught.exception))


class AdvanceStableTest(unittest.TestCase):
    """`stable` only moves forward: the marketplace channel never regresses."""

    def setUp(self) -> None:
        self.fx = Fixture(self)
        self.first = self.fx.commit("feat: first")
        self.second = self.fx.commit("feat: second")

    def advance(self, final: str) -> str:
        return rt.advance_stable(self.fx.work, "origin", final)

    def test_an_absent_stable_is_created(self) -> None:
        self.assertIsNone(self.fx.origin_rev("refs/heads/stable"))
        self.advance(self.first)
        self.assertEqual(self.first, self.fx.origin_rev("refs/heads/stable"))

    def test_stable_moves_to_a_descendant(self) -> None:
        self.advance(self.first)
        self.advance(self.second)
        self.assertEqual(self.second, self.fx.origin_rev("refs/heads/stable"))

    def test_stable_ahead_of_the_release_is_left_alone_with_a_message(self) -> None:
        self.advance(self.second)
        outcome = self.advance(self.first)
        self.assertEqual(self.second, self.fx.origin_rev("refs/heads/stable"))
        self.assertIn("not moving stable backwards", outcome)

    def test_a_diverged_stable_is_left_alone(self) -> None:
        self.advance(self.second)
        git(self.fx.work, "checkout", "-q", "-b", "side", self.first)
        other = self.fx.commit("feat: sibling", push=False, branch="side")
        outcome = self.advance(other)
        self.assertEqual(self.second, self.fx.origin_rev("refs/heads/stable"))
        self.assertIn("not moving stable", outcome)

    def test_the_same_commit_is_an_idempotent_no_regression(self) -> None:
        self.advance(self.second)
        self.advance(self.second)
        self.assertEqual(self.second, self.fx.origin_rev("refs/heads/stable"))

    def test_a_stable_whose_history_cannot_be_read_is_not_overwritten(self) -> None:
        self.advance(self.second)
        # A clone that never fetched stable and cannot fetch it must fail closed.
        git(self.fx.work, "remote", "set-url", "origin", str(self.fx.root / "gone.git"))
        with self.assertRaises(rt.ReleaseError):
            self.advance(self.first)


class RemoteLocalityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = Fixture(self)

    def test_a_local_path_remote_is_local(self) -> None:
        self.assertTrue(rt.is_local_remote(self.fx.work, "origin"))

    def test_a_push_url_override_is_checked_too(self) -> None:
        git(self.fx.work, "config", "remote.origin.pushurl", "https://example.invalid/x.git")
        self.assertFalse(rt.is_local_remote(self.fx.work, "origin"))
        with self.assertRaises(rt.ReleaseError):
            rt.rehearse(self.fx.work, "v0.1.0")

    def test_every_url_of_a_multi_url_remote_is_checked(self) -> None:
        git(self.fx.work, "remote", "set-url", "--add", "--push", "origin", str(self.fx.origin))
        git(
            self.fx.work,
            "remote",
            "set-url",
            "--add",
            "--push",
            "origin",
            "git@example.invalid:x/y.git",
        )
        self.assertFalse(rt.is_local_remote(self.fx.work, "origin"))


class GuardTest(unittest.TestCase):
    """Guards whose removal used to leave every test green."""

    def test_a_non_ascii_digit_is_not_a_version_number(self) -> None:
        with self.assertRaises(rt.ReleaseError):
            rt.parse_tag("1.2.1\u0663")

    def test_the_output_file_refuses_a_value_that_would_forge_another_line(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            target = Path(scratch) / "out"
            for value in ("a\nmode=resume", "a\rb"):
                with self.subTest(value=value), self.assertRaises(rt.ReleaseError):
                    rt.github_output(target, {"mode": value})
            self.assertFalse(target.exists())

    def test_a_manifest_version_that_is_not_a_string_is_no_version(self) -> None:
        fx = Fixture(self)
        for body in ('{"version": 5}', "[]", "null", "not json", '{"version": null}'):
            with self.subTest(body=body):
                fx.commit("fix: odd manifest", files={rt.TRUTH_MANIFEST: body})
                self.assertIsNone(rt.manifest_version(fx.work, "HEAD"))

    def test_annotations_cannot_carry_workflow_commands_on_a_second_line(self) -> None:
        text = rt.annotation("bad\n::stop-commands::x\r%")
        self.assertNotIn("\n", text)
        self.assertNotIn("\r", text)
        self.assertTrue(text.startswith("::error::"))
        self.assertEqual(1, len(text.splitlines()))

    def test_a_release_commit_carrying_a_hostile_version_prints_one_line(self) -> None:
        fx = Fixture(self)
        fx.commit("feat: work")
        fx.tag("v0.2.0")
        hostile = '{"version": "0.2.0\\n::stop-commands::abc"}'
        fx.commit("chore(release): v0.2.0", files={rt.TRUTH_MANIFEST: hostile})
        fx.fetch()
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--repo", str(fx.work), "resolve", "--tag", "v0.2.0"],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        self.assertEqual(1, result.returncode)
        self.assertEqual(1, len(result.stdout.splitlines()), result.stdout)
        self.assertTrue(result.stdout.startswith("::error::"))


if __name__ == "__main__":
    unittest.main()
