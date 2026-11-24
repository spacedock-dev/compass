"""The release's decisions, rehearsed against temporary repositories.

The workflow's inline shell used to make these decisions where nothing could
exercise them, which is how a pipe closed early under `pipefail` once broke
resuming. Every figure below is read from a real temporary Git repository with a
bare origin; nothing reaches the real remote, a real tag or a version field.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import TYPE_CHECKING
from unittest import mock

import yaml

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

    def test_a_release_with_repeated_keys_or_changed_modes_cannot_be_resumed(self) -> None:
        for tamper in ("duplicate key", "executable mode"):
            with self.subTest(tamper=tamper):
                fx = Fixture(self)
                fx.commit("feat: work")
                fx.tag("v0.2.0")
                rt.bump(fx.work, "0.2.0")
                path = fx.work / MANIFESTS[1]
                if tamper == "duplicate key":
                    body = path.read_text(encoding="utf-8")
                    description = json.loads(body)["description"]
                    path.write_text(
                        '{"description": ' + json.dumps(description) + "," + body[1:],
                        encoding="utf-8",
                    )
                git(fx.work, "add", "-A")
                if tamper == "executable mode":
                    git(fx.work, "update-index", "--chmod=+x", MANIFESTS[1])
                git(
                    fx.work, "-c", f"user.name={rt.BOT_NAME}", "-c", f"user.email={rt.BOT_EMAIL}",
                    "commit", "-q", "-m", "chore(release): v0.2.0",
                )  # fmt: skip
                git(fx.work, "push", "-q", "origin", "main")
                fx.fetch()
                with self.assertRaises(rt.ReleaseError) as caught:
                    rt.resolve(fx.work, "v0.2.0")
                self.assertIn(MANIFESTS[1], str(caught.exception))
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

    def test_resolve_prints_and_writes_the_three_job_outputs(self) -> None:
        output = self.fx.root / "github-output"
        result = self.cli("resolve", "--tag", "v0.2.0", "--github-output", str(output))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            f"mode=fresh\nversion=0.2.0\ntarget={self.tip}\n",
            output.read_text(encoding="utf-8"),
        )

    def test_a_higher_tag_pushed_after_resolve_keeps_the_older_release_from_latest(self) -> None:
        resolved = self.cli("resolve", "--tag", "v0.2.0")
        self.assertEqual(0, resolved.returncode, resolved.stderr)
        current = self.cli("latest", "--tag", "v0.2.0")
        self.assertEqual(0, current.returncode, current.stderr)
        self.assertEqual("true", current.stdout.strip())
        git(self.fx.origin, "tag", "v0.10.0", "main")
        self.fx.fetch()
        published = self.cli("latest", "--tag", "v0.2.0")
        self.assertEqual(0, published.returncode, published.stderr)
        self.assertEqual("false", published.stdout.strip())

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


@unittest.skipUnless(shutil.which("bash") and sys.platform != "win32", "requires a POSIX gh shim")
class PublishedReleaseTest(unittest.TestCase):
    """Rehearse the tag move, then drive the publishing workflow against fake GitHub."""

    ARCHIVES = (
        "compass_0.2.0_darwin_arm64.tar.gz",
        "compass_0.2.0_darwin_amd64.tar.gz",
        "compass_0.2.0_linux_arm64.tar.gz",
        "compass_0.2.0_linux_amd64.tar.gz",
    )

    def setUp(self) -> None:
        self.fx = Fixture(self)

    def write_checksums(self, destination: Path) -> bytes:
        manifest = "".join(
            f"{hashlib.sha256((destination / name).read_bytes()).hexdigest()}  {name}\n"
            for name in self.ARCHIVES
        ).encode()
        (destination / "checksums.txt").write_bytes(manifest)
        return manifest

    def github_release(
        self, *, drop: str = "", empty: str = "", draft: bool = False, stop_after: str = "stable"
    ) -> None:
        tag = "v0.2.0"
        self.fx.commit("feat: work", files={"program.txt": "old build"})
        self.fx.tag(tag)
        self.published = self.fx.root / "published"
        self.published.mkdir()
        for name in self.ARCHIVES:
            (self.published / name).write_text(f"old build: {name}\n", encoding="utf-8")
        self.write_checksums(self.published)
        if stop_after == "push-bump":
            self.fx.commit("feat: rebuild", files={"program.txt": "new build"})
        rt.rehearse(self.fx.work, tag, stop_after=stop_after)
        payload = {
            "tag_name": tag,
            "draft": draft,
            "prerelease": False,
            "published_at": None if draft else "2026-11-24T10:50:00Z",
            "assets": [
                {
                    "id": asset_id,
                    "url": f"https://api.github.com/repos/fixture/compass/releases/assets/{asset_id}",
                    "name": name,
                    "state": "uploaded",
                    "size": 0 if name == empty else (self.published / name).stat().st_size,
                    "digest": f"sha256:{hashlib.sha256((self.published / name).read_bytes()).hexdigest()}",
                }
                for asset_id, name in enumerate((*self.ARCHIVES, "checksums.txt"), start=1)
                if name != drop
            ],
        }
        self.response = self.fx.root / "release-response"
        self.response.write_text(json.dumps(payload), encoding="utf-8")
        self.gh_calls = self.fx.root / "gh-calls"
        gh = self.fx.root / "gh"
        gh.write_text(
            r"""#!/bin/sh
set -eu
printf '%s\n' "$*" >> "$FAKE_CALLS"
case "$*" in
    'api --include repos/{owner}/{repo}/releases/tags/v0.2.0')
        status=${FAKE_GH_STATUS:-200}
        printf 'HTTP/2.0 %s\r\nContent-Type: application/json\r\n\r\n' "$status"
        if [ "$status" = 200 ]; then
            cat "$FAKE_RESPONSE"
        else
            if [ "${FAKE_ERROR_BODY+x}" = x ]; then
                printf '%s' "$FAKE_ERROR_BODY"
            else
                printf '%s' '{"message":"Not Found"}'
            fi
            exit "${FAKE_GH_EXIT:-1}"
        fi ;;
    'api graphql --include -f query=query($owner: String!, $repo: String!, $tag: String!) { repository(owner: $owner, name: $repo) { release(tagName: $tag) { isDraft } } } -f owner=fixture -f repo=compass -f tag=v0.2.0')
        if [ "${FAKE_LOOKUP_FAIL:-0}" = 1 ]; then
            printf 'HTTP 503\n' >&2
            exit 1
        fi
        printf 'HTTP/2.0 200 OK\nContent-Type: application/json\r\n\r\n%s' "$FAKE_PUBLISH_RESPONSE" ;;
    'release create v0.2.0 '*) ;;
    'release download v0.2.0 --pattern checksums.txt --output '*)
        cp "$FAKE_ASSETS/checksums.txt" "$7" ;;
    'release delete-asset v0.2.0 checksums.txt --yes')
        rm "$FAKE_ASSETS/checksums.txt" ;;
    'release upload v0.2.0 '*)
        shift 3
        clobber=false
        for arg do
            if [ "$arg" = --clobber ]; then clobber=true; fi
        done
        [ "${FAKE_UPLOAD_FAIL:-0}" = 0 ] || exit 1
        for arg do
            [ "$arg" != --clobber ] || continue
            destination="$FAKE_ASSETS/${arg##*/}"
            if [ -e "$destination" ] && ! "$clobber"; then
                printf 'already_exists: %s\n' "${arg##*/}" >&2
                exit 1
            fi
            cp "$arg" "$destination"
        done ;;
    *) printf 'unexpected gh command: %s\n' "$*" >&2; exit 2 ;;
esac
""",
            encoding="utf-8",
        )
        gh.chmod(0o755)
        curl = self.fx.root / "curl"
        curl.write_text(
            r"""#!/bin/sh
set -eu
printf 'curl %s\n' "$*" >> "$FAKE_CALLS"
[ "$(cat)" = 'Authorization: Bearer fixture-only' ]
[ -z "${GH_TOKEN+x}" ]
if [ "${FAKE_ASSET_REPLY+x}" = x ]; then
    printf '%s' "$FAKE_ASSET_REPLY"
    exit "${FAKE_ASSET_EXIT:-0}"
fi
if [ "${FAKE_DOWNLOAD_FAIL:-0}" = 1 ]; then
    printf 'HTTP 403\n' >&2
    exit 1
fi
printf 'HTTP/2.0 200 OK\nContent-Type: application/octet-stream\r\n\r\n'
if [ "${FAKE_DOWNLOAD_OVERFLOW:-0}" = 1 ]; then
    dd if=/dev/zero bs=1024 count=1024 2>/dev/null
    touch "$FAKE_ASSETS/download-exhausted"
    exit 0
fi
cat "$FAKE_ASSETS/checksums.txt"
""",
            encoding="utf-8",
        )
        curl.chmod(0o755)
        patch = mock.patch.dict(
            os.environ,
            {
                "PATH": f"{self.fx.root}{os.pathsep}{os.environ['PATH']}",
                "GH_TOKEN": "fixture-only",
                "GITHUB_API_URL": "https://api.github.com",
                "FAKE_RESPONSE": str(self.response),
                "FAKE_ASSETS": str(self.published),
                "FAKE_CALLS": str(self.gh_calls),
            },
        )
        patch.start()
        self.addCleanup(patch.stop)

    def release_command(self, *args: str) -> subprocess.CompletedProcess[str]:
        self.fx.fetch()
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--repo", str(self.fx.work), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def resolve_attempt(self, attempt: str = "1") -> subprocess.CompletedProcess[str]:
        return self.release_command("resolve", "--tag", "v0.2.0", "--run-attempt", attempt)

    def test_the_tag_move_of_a_fully_published_release_stops_at_resolve(self) -> None:
        self.github_release()
        original = self.fx.origin_rev("refs/tags/v0.2.0")
        result = self.resolve_attempt()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(f"mode=complete\nversion=0.2.0\ntarget={original}\n", result.stdout)
        self.assertEqual(original, self.fx.origin_rev("refs/tags/v0.2.0"))
        self.assertEqual(
            [
                "api --include repos/{owner}/{repo}/releases/tags/v0.2.0",
                (
                    "curl --disable --include --no-buffer --silent --show-error --location "
                    "--max-redirs 5 --suppress-connect-headers --proto =https --proto-redir =https "
                    "--tlsv1.2 --header @- --header Accept: application/octet-stream --url "
                    "https://api.github.com/repos/fixture/compass/releases/assets/5"
                ),
            ],
            self.gh_calls.read_text(encoding="utf-8").splitlines(),
        )

    def test_a_missing_or_empty_release_asset_still_resumes(self) -> None:
        for drop, empty in (("checksums.txt", ""), ("", "compass_0.2.0_linux_amd64.tar.gz")):
            with self.subTest(drop=drop, empty=empty):
                self.fx = Fixture(self)
                self.github_release(drop=drop, empty=empty)
                result = self.resolve_attempt()
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertIn("mode=resume\n", result.stdout)

    def test_a_draft_or_missing_github_release_still_resumes(self) -> None:
        self.github_release(draft=True)
        payload = json.loads(self.response.read_bytes())
        payload["published_at"] = "2026-11-24T10:50:00Z"
        self.response.write_text(json.dumps(payload), encoding="utf-8")
        for status in ("200", "404"):
            with (
                self.subTest(status=status),
                mock.patch.dict(os.environ, {"FAKE_GH_STATUS": status}),
            ):
                result = self.resolve_attempt()
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertIn("mode=resume\n", result.stdout)

    def test_a_prerelease_or_invalid_publication_date_still_resumes(self) -> None:
        self.github_release()
        payload = json.loads(self.response.read_text(encoding="utf-8"))
        for fields in ({"prerelease": True}, {"published_at": 123}, {"published_at": ""}):
            with self.subTest(fields=fields):
                self.response.write_text(json.dumps(payload | fields), encoding="utf-8")
                result = self.resolve_attempt()
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertIn("mode=resume\n", result.stdout)

    def test_expected_uploaded_asset_names_must_be_unique(self) -> None:
        self.github_release()
        payload = json.loads(self.response.read_text(encoding="utf-8"))
        duplicate = payload["assets"][0] | {"id": 6}
        payload["assets"].append(duplicate)
        self.response.write_text(json.dumps(payload), encoding="utf-8")
        result = self.resolve_attempt()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("mode=resume\n", result.stdout)

    def test_a_malformed_asset_fails_before_or_after_a_partial_asset(self) -> None:
        self.github_release()
        payload = json.loads(self.response.read_bytes())
        payload["assets"][0].update(state="starter", size=0)
        assets = payload["assets"]
        for records in ([*assets, None], [None, *assets]):
            with self.subTest(malformed_first=records[0] is None):
                self.response.write_text(
                    json.dumps(payload | {"assets": records}), encoding="utf-8"
                )
                result = self.resolve_attempt()
                self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                self.assertIn("unexpected GitHub asset response", result.stderr)
                self.assertEqual("", result.stdout)

    def test_an_unrelated_asset_does_not_prevent_completion(self) -> None:
        self.github_release()
        payload = json.loads(self.response.read_text(encoding="utf-8"))
        payload["assets"].append(payload["assets"][0] | {"name": "notes.pdf", "id": 6})
        self.response.write_text(json.dumps(payload), encoding="utf-8")
        result = self.resolve_attempt()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("mode=complete\n", result.stdout)

    def test_archive_digests_must_exist_and_match_the_published_checksums(self) -> None:
        self.github_release()
        payload = json.loads(self.response.read_text(encoding="utf-8"))
        asset = payload["assets"][0]
        for digest in ("sha256:" + "0" * 64, None, "sha256:too-short"):
            with self.subTest(digest=digest):
                asset["digest"] = digest
                self.response.write_text(json.dumps(payload), encoding="utf-8")
                result = self.resolve_attempt()
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertIn("mode=resume\n", result.stdout)

    def test_a_duplicate_or_missing_checksum_line_still_resumes(self) -> None:
        self.github_release()
        manifest = self.published / "checksums.txt"
        lines = manifest.read_bytes().splitlines(keepends=True)
        for new_lines in (lines[:-1], [*lines[:-1], lines[0]], [*lines, lines[0]]):
            with self.subTest(lines=new_lines):
                manifest.write_bytes(b"".join(new_lines))
                result = self.resolve_attempt()
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertIn("mode=resume\n", result.stdout)

    def test_a_non_utf8_checksum_response_still_resumes(self) -> None:
        self.github_release()
        manifest = self.published / "checksums.txt"
        utf16 = b"\xff\xfe" + manifest.read_text(encoding="ascii").encode("utf-16-le")
        for body in (utf16, b"\xff\xfea\x00\n\x00\n"):
            with self.subTest(length=len(body)):
                manifest.write_bytes(body)

                result = self.resolve_attempt()
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertIn("mode=resume\n", result.stdout)
        self.assertEqual(2, self.gh_calls.read_text(encoding="utf-8").count("releases/assets/5"))

    def test_the_completion_check_requires_lf_delimited_checksums(self) -> None:
        self.github_release()
        manifest = self.published / "checksums.txt"
        good = manifest.read_bytes()
        invalid_bodies = [
            (ending, good.replace(b"\n", ending)) for ending in (b"\r\n", b"\r", "\u2028".encode())
        ]
        for ending, body in [*invalid_bodies, (b"", good[:-1])]:
            with self.subTest(ending=ending):
                manifest.write_bytes(body)
                result = self.resolve_attempt()
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                self.assertIn("mode=resume\n", result.stdout)

    def test_an_oversized_checksum_asset_resumes_without_downloading(self) -> None:
        self.github_release()
        payload = json.loads(self.response.read_bytes())
        payload["assets"][-1]["size"] += 1
        self.response.write_text(json.dumps(payload), encoding="utf-8")

        result = self.resolve_attempt()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("mode=resume\n", result.stdout)
        self.assertEqual(
            ["api --include repos/{owner}/{repo}/releases/tags/v0.2.0"],
            self.gh_calls.read_text(encoding="utf-8").splitlines(),
        )

    def test_an_oversized_checksum_response_resumes_without_reading_to_eof(self) -> None:
        self.github_release()
        with mock.patch.dict(os.environ, {"FAKE_DOWNLOAD_OVERFLOW": "1"}):
            result = self.resolve_attempt()

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("mode=resume\n", result.stdout)
        self.assertIn("releases/assets/5", self.gh_calls.read_text(encoding="utf-8"))
        self.assertFalse((self.published / "download-exhausted").exists())

    def test_oversized_checksum_metadata_still_requires_a_valid_asset_id(self) -> None:
        self.github_release()
        payload = json.loads(self.response.read_bytes())
        checksums = payload["assets"][-1]
        checksums.update(id=None, size=checksums["size"] + 1)
        for assets in (payload["assets"], payload["assets"][::-1]):
            with self.subTest(first_asset=assets[0]["name"]):
                self.response.write_text(json.dumps(payload | {"assets": assets}), encoding="utf-8")
                result = self.resolve_attempt()
                self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                self.assertIn("invalid GitHub asset ID", result.stderr)
                self.assertEqual("", result.stdout)
        self.assertNotIn("releases/assets/", self.gh_calls.read_text(encoding="utf-8"))

    def test_partial_archives_do_not_hide_a_malformed_checksum_asset_id(self) -> None:
        self.github_release()
        payload = json.loads(self.response.read_bytes())
        payload["assets"][0]["state"] = "starter"
        payload["assets"][-1]["id"] = None
        for assets in (payload["assets"], payload["assets"][::-1]):
            with self.subTest(first_asset=assets[0]["name"]):
                self.response.write_text(json.dumps(payload | {"assets": assets}), encoding="utf-8")
                result = self.resolve_attempt()
                self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                self.assertIn("invalid GitHub asset ID", result.stderr)
                self.assertEqual("", result.stdout)
        self.assertNotIn("releases/assets/", self.gh_calls.read_text(encoding="utf-8"))

    def test_the_checksum_url_must_match_the_api_and_asset_id_before_download(self) -> None:
        self.github_release()
        payload = json.loads(self.response.read_bytes())
        url = payload["assets"][-1]["url"]
        for invalid in (url.replace("api.github.com", "elsewhere.invalid"), url[:-1] + "4"):
            with self.subTest(url=invalid):
                payload["assets"][-1]["url"] = invalid
                self.response.write_text(json.dumps(payload), encoding="utf-8")
                result = self.resolve_attempt()
                self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                self.assertIn("invalid GitHub asset URL", result.stderr)
        self.assertNotIn("curl ", self.gh_calls.read_text(encoding="utf-8"))

    def local_gh_env(self, socket: str) -> dict[str, str]:
        config = self.fx.root / "gh-config"
        config.mkdir()
        (config / "config.yml").write_text(
            f"version: 1\nhttp_unix_socket: {socket}\n", encoding="utf-8"
        )
        return {
            "GH_HOST": "github.com",
            "GH_REPO": "github.com/fixture/compass",
            "GH_TOKEN": "fixture-only",
            "GH_CONFIG_DIR": str(config),
            "GH_NO_UPDATE_NOTIFIER": "1",
            "GH_TELEMETRY": "false",
            "HTTP_PROXY": "http://127.0.0.1:1",
            "HTTPS_PROXY": "http://127.0.0.1:1",
            "NO_PROXY": "",
        }

    def resolve_while_checksum_is_open(
        self, workers: ThreadPoolExecutor, requested: threading.Event, finish: threading.Event
    ) -> subprocess.CompletedProcess[str]:
        result = workers.submit(self.resolve_attempt)
        try:
            if not requested.wait(10):
                resolved = result.result(timeout=5)
                self.fail(f"checksum request never reached GitHub: {resolved.stderr}")
            return result.result(timeout=5)
        except TimeoutError:
            self.fail("resolve waited for the final byte of an oversized response")
        finally:
            finish.set()

    @unittest.skipUnless(shutil.which("gh") and shutil.which("curl"), "requires gh and curl")
    def test_real_checksum_download_completes_or_rejects_overflow_before_eof(self) -> None:
        from socketserver import UnixStreamServer  # noqa: PLC0415 -- unavailable on Windows

        real_curl = shlex.quote(shutil.which("curl") or "curl")
        self.github_release()
        (self.fx.root / "gh").unlink()
        socket = "fixture.sock"
        # The fixture serves HTTP over a private socket. Only the test wrapper
        # relaxes the protocol restriction for that local transport.
        (self.fx.root / "curl").write_text(
            "#!/bin/sh\n"
            f'exec {real_curl} "$@" --unix-socket {socket} --noproxy "*" '
            "--proto =http --proto-redir =http\n",
            encoding="utf-8",
        )
        metadata = self.response.read_bytes().replace(
            b"https://api.github.com", b"http://github.fixture"
        )
        checksums = (self.published / "checksums.txt").read_bytes()
        overflow = b'{"payload":"' + b"a" * 2048 + b'"}'
        asset_requests: list[tuple[str, str | None]] = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format: str, *args: object) -> None:
                pass

            def do_GET(self) -> None:
                is_api_asset = self.path.endswith("/releases/assets/5")
                is_asset = is_api_asset or self.path == "/redirected"
                if is_asset:
                    asset_requests.append((self.path, self.headers.get("Authorization")))
                if is_api_asset and redirect:
                    self.send_response(302)
                    self.send_header("Location", "http://download.fixture/redirected")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                body = asset_body if is_asset else metadata
                self.send_response(200)
                self.send_header("Content-Type", mime if is_asset else "application/json")
                if not is_asset or with_length:
                    self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if is_asset:
                    requested.set()
                with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                    if is_asset and hold_open:
                        self.wfile.write(body[:-1])
                        finish.wait()
                        self.wfile.write(body[-1:])
                    else:
                        self.wfile.write(body)

        # A relative socket path also works when TMPDIR exceeds the Unix socket path limit.
        with contextlib.chdir(self.fx.work):
            server = UnixStreamServer(socket, Handler)
        with (
            server,
            ThreadPoolExecutor(max_workers=2) as workers,
            mock.patch.dict(
                os.environ, self.local_gh_env(socket) | {"GITHUB_API_URL": "http://github.fixture"}
            ),
        ):
            workers.submit(server.serve_forever)
            try:
                for mime, asset_body, with_length, hold_open, redirect, mode in (
                    ("application/octet-stream", checksums, True, False, False, "complete"),
                    ("application/octet-stream", checksums, True, False, True, "complete"),
                    ("application/octet-stream", overflow, True, True, False, "resume"),
                    ("application/json", overflow, True, True, False, "resume"),
                    ("application/json", overflow, False, True, False, "resume"),
                ):
                    with self.subTest(
                        mime=mime, with_length=with_length, redirect=redirect, hold_open=hold_open
                    ):
                        requested, finish = threading.Event(), threading.Event()
                        asset_requests.clear()
                        resolved = self.resolve_while_checksum_is_open(workers, requested, finish)
                        self.assertEqual(0, resolved.returncode, resolved.stderr)
                        self.assertIn(
                            f"mode={mode}\n", resolved.stdout, f"body size {len(asset_body)}"
                        )
                        expected: list[tuple[str, str | None]] = [
                            ("/repos/fixture/compass/releases/assets/5", "Bearer fixture-only")
                        ]
                        if redirect:
                            expected.append(("/redirected", None))
                        self.assertEqual(expected, asset_requests)
            finally:
                server.shutdown()

    def test_a_checksum_response_needs_complete_headers_and_a_successful_exit(self) -> None:
        self.github_release()
        for reply, exit_code, diagnostic in (
            ("", "0", "missing GitHub response headers"),
            ("", "1", "curl exited 1"),
            (
                "HTTP/2.0 200\nContent-Type: application/octet-stream\r\n",
                "0",
                "invalid or oversized",
            ),
            (f"HTTP/2.0 200\nX-Padding: {'a' * (32 * 1024)}\r\n\r\n", "0", "invalid or oversized"),
            ("HTTP/2.0 200\n\nshort response", "1", "curl exited 1"),
            (
                "HTTP/2.0 302\n\nHTTP/2.0 200\n\n",
                "0",
                "HTTP 302 without Location",
            ),
        ):
            with (
                self.subTest(reply_length=len(reply), exit_code=exit_code),
                mock.patch.dict(
                    os.environ, {"FAKE_ASSET_REPLY": reply, "FAKE_ASSET_EXIT": exit_code}
                ),
            ):
                result = self.resolve_attempt()
                self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                self.assertIn(diagnostic, result.stderr)
                self.assertEqual("", result.stdout)

    def test_an_explicit_rerun_can_recover_distribution_after_the_assets_were_uploaded(
        self,
    ) -> None:
        self.github_release()
        with mock.patch.dict(os.environ, {"FAKE_GH_STATUS": "403"}):
            result = self.resolve_attempt("2")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("mode=resume\n", result.stdout)
        self.assertFalse(self.gh_calls.exists())

    def test_the_release_still_resumes_before_the_tag_has_moved(self) -> None:
        self.github_release(stop_after="push-bump")
        with mock.patch.dict(os.environ, {"FAKE_GH_STATUS": "503"}):
            result = self.resolve_attempt()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("mode=resume\n", result.stdout)

    def test_an_unproven_release_lookup_fails_closed_with_a_stderr_diagnostic(self) -> None:
        self.github_release()
        for status, body, exit_code in (
            ("404", "<html>proxy 404</html>", "1"),
            ("404", "", "1"),
            ("404", "{}", "1"),
            ("404", '{"message":"Not Found"}', "0"),
            ("403", '{"message":"API rate limit exceeded"}', "1"),
            ("429", '{"message":"Too Many Requests"}', "1"),
            ("503", "{}", "1"),
        ):
            with (
                self.subTest(status=status, body=body, exit_code=exit_code),
                mock.patch.dict(
                    os.environ,
                    {"FAKE_GH_STATUS": status, "FAKE_ERROR_BODY": body, "FAKE_GH_EXIT": exit_code},
                ),
            ):
                result = self.resolve_attempt()
                self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                self.assertIn("could not read published assets", result.stderr)
                self.assertEqual("", result.stdout)

    def test_a_non_json_or_malformed_success_response_fails_closed(self) -> None:
        self.github_release()
        payload = json.loads(self.response.read_text(encoding="utf-8"))
        for invalid in (
            "<html>proxy</html>",
            json.dumps(payload | {"prerelease": "false"}),
            json.dumps(payload | {"draft": 0}),
        ):
            with self.subTest(response=invalid):
                self.response.write_text(invalid, encoding="utf-8")
                result = self.resolve_attempt()
                self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                self.assertIn("could not read published assets", result.stderr)
                self.assertEqual("", result.stdout)

    def test_a_failed_checksum_download_names_the_operation_on_stderr(self) -> None:
        self.github_release()
        with mock.patch.dict(os.environ, {"FAKE_DOWNLOAD_FAIL": "1"}):
            result = self.resolve_attempt()
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("could not download published checksums", result.stderr)
        self.assertIn("HTTP 403", result.stderr)
        self.assertEqual("", result.stdout)

    def test_an_oversized_http_error_does_not_resume(self) -> None:
        self.github_release()
        limit = (self.published / "checksums.txt").stat().st_size
        headers = "HTTP/2.0 503 Service Unavailable\nContent-Type: text/html\r\n\r\n"
        reply = headers + "x" * (limit + 1)
        with mock.patch.dict(os.environ, {"FAKE_ASSET_REPLY": reply, "FAKE_ASSET_EXIT": "1"}):
            result = self.resolve_attempt()

        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("could not download published checksums", result.stderr)
        self.assertIn("HTTP 503", result.stderr)
        self.assertEqual("", result.stdout)

    def run_publish(self, **env: str) -> subprocess.CompletedProcess[str]:
        release = SCRIPT.parents[1] / ".github/workflows/release.yml"
        workflow = yaml.safe_load(release.read_text(encoding="utf-8"))
        publish = next(
            step["run"]
            for step in workflow["jobs"]["release"]["steps"]
            if step["name"] == "Publish the GitHub Release"
        )
        return subprocess.run(
            [shutil.which("bash") or "bash", "-c", publish],
            cwd=self.fx.work,
            env={
                **os.environ,
                "TAG": "v0.2.0",
                "VERSION": "0.2.0",
                "NOTES_FILE": "fixture",
                "GITHUB_REPOSITORY": "fixture/compass",
                **env,
            },
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def test_the_publish_step_stops_for_a_draft_and_accepts_a_public_release(self) -> None:
        self.github_release(draft=True)
        for repository, exit_code, message in (
            ({"release": {"isDraft": True}}, 1, "exists as a draft"),
            ({"release": {"isDraft": False}}, 0, "already exists"),
            ({"release": {"isDraft": None}}, 1, "Could not determine whether release"),
            ({}, 1, "Could not determine whether release"),
            (None, 1, "Could not determine whether release"),
        ):
            with self.subTest(repository=repository):
                result = self.run_publish(
                    FAKE_PUBLISH_RESPONSE=json.dumps({"data": {"repository": repository}})
                )
                self.assertEqual(exit_code, result.returncode, result.stdout + result.stderr)
                self.assertIn(message, result.stdout + result.stderr)
        self.assertNotIn("release create", self.gh_calls.read_text(encoding="utf-8"))

    def test_the_publish_step_does_not_create_after_an_unproven_lookup(self) -> None:
        self.github_release()
        result = self.run_publish(FAKE_LOOKUP_FAIL="1")
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("HTTP 503", result.stderr)
        self.assertNotIn("release create", self.gh_calls.read_text(encoding="utf-8"))

    def test_the_publish_step_refuses_partial_graphql_data(self) -> None:
        self.github_release()
        data = {"repository": {"release": None}}
        for response in (
            {"data": data, "errors": [{"message": "", "path": ["repository", "release"]}]},
            {"errors": [{"message": "retry", "path": ["repository", "release"]}], "data": data},
        ):
            with self.subTest(response=response):
                result = self.run_publish(FAKE_PUBLISH_RESPONSE=json.dumps(response))
                self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                self.assertIn("Could not", result.stderr)
                self.assertNotIn("release create", self.gh_calls.read_text(encoding="utf-8"))

    def test_the_publish_step_refuses_ambiguous_graphql_absence(self) -> None:
        self.github_release()
        absence = '{"data":{"repository":{"release":null}}}'
        for response in (
            '{"data":{"repository":{"release":{"isDraft":false},"release":null}}}',
            f"{absence}\n{absence}",
            '{"data":{"repository":{"release":null}},"errors":[]}',
        ):
            with self.subTest(response=response):
                self.gh_calls.unlink(missing_ok=True)
                result = self.run_publish(FAKE_PUBLISH_RESPONSE=response)
                self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                self.assertIn("Could not", result.stderr)
                self.assertNotIn("release create", self.gh_calls.read_text(encoding="utf-8"))

    def assert_real_gh_publish_refuses(self, *responses: tuple[int, str, bytes]) -> None:
        from socketserver import UnixStreamServer  # noqa: PLC0415 -- unavailable on Windows

        real_gh = shlex.quote(shutil.which("gh") or "gh")
        self.github_release()
        (self.fx.root / "gh").write_text(
            "#!/bin/sh\n"
            'printf "%s %s\\n" "$1" "$2" >> "$FAKE_CALLS"\n'
            f'if [ "$1 $2" = "api graphql" ]; then exec {real_gh} "$@"; fi\n'
            '[ "$1 $2" = "release create" ]\n',
            encoding="utf-8",
        )
        socket = "fixture.sock"
        posts: list[str] = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format: str, *args: object) -> None:
                pass

            def do_POST(self) -> None:
                self.rfile.read(int(self.headers["Content-Length"]))
                posts.append(self.path)
                self.send_response(status)
                if status == 206:
                    self.send_header("Content-Range", f"bytes 0-{len(body) - 1}/{len(body) + 1}")
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        with contextlib.chdir(self.fx.work):
            server = UnixStreamServer(socket, Handler)
        env = self.local_gh_env(socket)
        with server, ThreadPoolExecutor(max_workers=1) as worker:
            worker.submit(server.serve_forever)
            try:
                for status, mime, body in responses:
                    with self.subTest(status=status, mime=mime, body=body):
                        self.gh_calls.unlink(missing_ok=True)
                        result = self.run_publish(**env)
                        created = "release create" in self.gh_calls.read_text(encoding="utf-8")
                        self.assertEqual((1, False), (result.returncode, created), result.stderr)
                        self.assertIn("Could not", result.stderr)
            finally:
                server.shutdown()
        self.assertEqual(["/graphql"] * len(responses), posts)

    @unittest.skipUnless(shutil.which("gh"), "requires the GitHub CLI")
    def test_real_gh_publish_refuses_both_partial_error_responses(self) -> None:
        self.assert_real_gh_publish_refuses(
            (
                200,
                "application/json",
                (
                    b'{"data":{"repository":{"release":null}},'
                    b'"errors":[{"message":"","path":["repository","release"]}]}'
                ),
            ),
            (
                200,
                "text/plain",
                (
                    b'{"errors":[{"message":"retry","path":["repository","release"]}],'
                    b'"data":{"repository":{"release":null}}}'
                ),
            ),
        )

    @unittest.skipUnless(shutil.which("gh"), "requires the GitHub CLI")
    def test_real_gh_publish_refuses_partial_http_content(self) -> None:
        self.assert_real_gh_publish_refuses(
            (206, "application/json", b'{"data":{"repository":{"release":null}}}'),
        )

    @unittest.skipUnless(shutil.which("gh"), "requires the GitHub CLI")
    def test_real_gh_publish_refuses_non_json_numeric_constants(self) -> None:
        self.assert_real_gh_publish_refuses(
            *(
                (
                    200,
                    "text/plain",
                    b'{"data":{"repository":{"release":null}},"extensions":{"duration":'
                    + constant
                    + b"}}",
                )
                for constant in (b"NaN", b"Infinity", b"-Infinity")
            ),
        )

    def test_the_publish_step_creates_after_github_confirms_the_release_is_absent(self) -> None:
        self.github_release()
        result = self.run_publish(FAKE_PUBLISH_RESPONSE='{"data":{"repository":{"release":null}}}')
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("release create v0.2.0", self.gh_calls.read_text(encoding="utf-8"))

    def run_attach(self) -> tuple[subprocess.CompletedProcess[str], dict[str, bytes], Path]:
        release = SCRIPT.parents[1] / ".github/workflows/release.yml"
        workflow = yaml.safe_load(release.read_text(encoding="utf-8"))
        step = next(
            step for step in workflow["jobs"]["attach-cli"]["steps"] if step.get("id") == "attach"
        )
        scratch = self.fx.root / "cli"
        scratch.mkdir(exist_ok=True)
        archives = {name: f"new build: {name}\n".encode() for name in self.ARCHIVES}
        for name, content in archives.items():
            (scratch / name).write_bytes(content)
        shutil.copy2(SCRIPT.with_name("publish-cli.sh"), self.fx.work / "scripts")
        output = self.fx.root / "github-output"
        result = subprocess.run(
            [shutil.which("bash") or "bash", "-c", step["run"]],
            cwd=self.fx.work,
            env={
                **os.environ,
                "TAG": "v0.2.0",
                "RUNNER_TEMP": str(self.fx.root),
                "GITHUB_OUTPUT": str(output),
            },
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        return result, archives, output

    def assert_attach_replaced_all_assets(self) -> None:
        result, archives, output = self.run_attach()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        for name, content in archives.items():
            self.assertEqual(content, (self.published / name).read_bytes(), name)
        manifest = b"".join(
            f"{hashlib.sha256(content).hexdigest()}  {name}\n".encode()
            for name, content in archives.items()
        )
        self.assertEqual(manifest, (self.published / "checksums.txt").read_bytes())
        digest = hashlib.sha256(manifest).hexdigest()
        self.assertEqual(f"checksums_sha256={digest}\n", output.read_text(encoding="utf-8"))
        calls = self.gh_calls.read_text(encoding="utf-8").splitlines()
        self.assertEqual(1, len(calls), calls)
        (call,) = calls
        self.assertTrue(call.startswith("release upload v0.2.0 "), call)
        self.assertTrue(call.endswith("/checksums.txt --clobber"), call)

    @unittest.skipUnless(shutil.which("sha256sum"), "the attach job uses sha256sum")
    def test_a_full_rerun_repairs_mismatched_published_archives_and_checksums(self) -> None:
        self.github_release()
        interrupted = b"an interrupted build"
        (self.published / self.ARCHIVES[0]).write_bytes(interrupted)
        payload = json.loads(self.response.read_text(encoding="utf-8"))
        payload["assets"][0]["digest"] = f"sha256:{hashlib.sha256(interrupted).hexdigest()}"
        self.response.write_text(json.dumps(payload), encoding="utf-8")
        result = self.resolve_attempt()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("mode=resume\n", result.stdout)
        self.gh_calls.unlink()
        result = self.resolve_attempt("2")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("mode=resume\n", result.stdout)
        self.assert_attach_replaced_all_assets()

    @unittest.skipUnless(shutil.which("sha256sum"), "the attach job uses sha256sum")
    def test_attachment_replaces_assets_from_before_the_tag_move(self) -> None:
        self.github_release(stop_after="push-bump")
        original = git(self.fx.origin, "rev-parse", "refs/tags/v0.2.0")
        moved = git(self.fx.origin, "rev-parse", "refs/heads/main")
        self.assertNotEqual(original, moved)
        rt.move_tag(self.fx.work, "origin", "v0.2.0", moved)
        self.assertEqual(moved, self.fx.origin_rev("refs/tags/v0.2.0"))
        self.assertEqual("old build", git(self.fx.work, "show", f"{original}:program.txt"))
        self.assertEqual("new build", git(self.fx.work, "show", f"{moved}:program.txt"))
        self.assert_attach_replaced_all_assets()

    @unittest.skipUnless(shutil.which("sha256sum"), "the attach job uses sha256sum")
    def test_attachment_replaces_draft_assets_independently_of_the_lookup(self) -> None:
        for status, body in (
            ("200", ""),
            ("404", '{"message":"Not Found"}'),
            ("404", "<html>proxy</html>"),
        ):
            with (
                self.subTest(status=status, body=body),
                mock.patch.dict(os.environ, {"FAKE_GH_STATUS": status, "FAKE_ERROR_BODY": body}),
            ):
                self.fx = Fixture(self)
                self.github_release(draft=True)
                self.assert_attach_replaced_all_assets()

    @unittest.skipUnless(shutil.which("sha256sum"), "the attach job uses sha256sum")
    def test_attachment_does_not_delete_checksums_before_upload(self) -> None:
        self.github_release(draft=True)
        before = (self.published / "checksums.txt").read_bytes()
        with mock.patch.dict(os.environ, {"FAKE_UPLOAD_FAIL": "1"}):
            result, _, output = self.run_attach()
        self.assertNotEqual(0, result.returncode)
        self.assertFalse(output.exists())
        self.assertTrue((self.published / "checksums.txt").exists())
        self.assertEqual(before, (self.published / "checksums.txt").read_bytes())


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
