"""Synthetic prefix-shaped credentials remain private when glued to other text."""

from __future__ import annotations

import unittest

from compass_runtime import records


class GluedCredentialTest(unittest.TestCase):
    def test_separated_lowercase_hyphenated_generic_keeps_baseline_protection(self) -> None:
        fake = "sk-alpha-bravo-charlie-delta-echo-foxtrot"
        for lead, tail in (
            ("", ""),
            ("use ", ""),
            ("use\t", ""),
            ("use=", ""),
            ("use:", ""),
            ('"', '"'),
            ("'", "'"),
            ("[", "]"),
            ("(", ")"),
            (".", ""),
            ("/", ""),
            (";", ""),
            ("!", ""),
        ):
            with self.subTest(lead=lead, tail=tail):
                self.assertEqual(
                    lead + "sk-…REDACTED" + tail, records.redact_secrets(lead + fake + tail)
                )

    def test_unconditional_lowercase_families_keep_baseline_protection(self) -> None:
        for prefix, length in (
            ("github_pat_", 40),
            ("lin_api_", 40),
            ("ya29.", 20),
            ("sk-ant-", 83),
        ):
            for lead in ("use ", "use=", "cfg_", "abc", "-"):
                with self.subTest(prefix=prefix, lead=lead):
                    self.assertEqual(
                        lead + prefix + "…REDACTED",
                        records.redact_secrets(lead + prefix + "a" * length),
                    )

    def test_separated_invalid_langfuse_body_still_matches_generic_shape(self) -> None:
        for lead in ("use ", "use=", "界"):
            with self.subTest(lead=lead):
                self.assertEqual(
                    lead + "sk-…REDACTED", records.redact_secrets(lead + "sk-lf-" + "g" * 36)
                )

    # Minimum accepted bodies catch a length-dependent leading-boundary bypass.
    PREFIXED = (
        ("sk-ant-", "A" * 16, "sk-ant-"),
        ("sk-ant-api03-", "A" * 95, "sk-ant-"),
        ("sk-ant-oat01-", "B" * 95, "sk-ant-"),
        ("sk-ant-ort01-", "C" * 95, "sk-ant-"),
        ("sk-lf-", "00000000-1111-2222-3333-444444444444", "sk-lf-"),
        ("pk-lf-", "abcdef01-2345-6789-abcd-ef0123456789", "pk-lf-"),
        ("sk-", "C" * 32, "sk-"),
        ("sk-", "c" * 32, "sk-"),
        ("sk-proj-", "C" * 156, "sk-"),
        ("sk-proj-", "c" * 156, "sk-"),
        ("sk-or-v1-", "c" * 64, "sk-"),
        ("sk_live_", "U" * 20, "sk_live_"),
        ("sk_test_", "U" * 20, "sk_test_"),
        ("rk_live_", "U" * 20, "rk_live_"),
        ("rk_test_", "U" * 20, "rk_test_"),
        ("AKIA", "A" * 16, "AKIA"),
        ("ASIA", "A" * 16, "ASIA"),
        ("ghp_", "D" * 36, "ghp_"),
        ("gho_", "D" * 36, "gho_"),
        ("ghu_", "D" * 36, "ghu_"),
        ("ghs_", "D" * 36, "ghs_"),
        ("ghr_", "D" * 36, "ghr_"),
        ("github_pat_", "V" * 40, "github_pat_"),
        ("glpat-", "W" * 20, "glpat-"),
        ("npm_", "X" * 36, "npm_"),
        ("lin_api_", "Z" * 40, "lin_api_"),
        ("xoxb-", "0" * 15, "xoxb-"),
        ("xoxa-", "0" * 15, "xoxa-"),
        ("xoxp-", "0" * 15, "xoxp-"),
        ("xoxr-", "0" * 15, "xoxr-"),
        ("xoxs-", "0" * 15, "xoxs-"),
        ("xapp-", "0" * 15, "xapp-"),
        ("phc_", "G" * 32, "phc_"),
        ("AIza", "H" * 35, "AIza"),
        ("eyJ", "I" * 8 + "." + "J" * 8 + "." + "K" * 8, "eyJ"),
        ("ya29.", "F" * 20, "ya29."),
    )
    LEADS = ("use ", "use=", "cfg_", "abc", "1", "_", "-", "界")

    def test_prefix_admission_preserves_baseline_and_checks_glued_evidence(self) -> None:
        for prefix, body, kept in self.PREFIXED:
            for lead in self.LEADS:
                with self.subTest(prefix=prefix, body=body, lead=lead):
                    raw = lead + prefix + body + " then retry"
                    expected = lead + kept + "…REDACTED then retry"
                    if (prefix, body) in (("sk-", "c" * 32), ("sk-proj-", "c" * 156)) and lead in (
                        "cfg_",
                        "abc",
                        "1",
                        "_",
                        "-",
                    ):
                        expected = raw
                    if lead == "-" and prefix not in (
                        "sk-ant-api03-",
                        "sk-ant-oat01-",
                        "sk-ant-ort01-",
                        "AKIA",
                        "ASIA",
                        "AIza",
                        "github_pat_",
                        "lin_api_",
                        "ya29.",
                    ):
                        expected = raw
                    self.assertEqual(expected, records.redact_secrets(raw))
                    self.assertEqual(expected, records.redact_secrets(expected))

    def test_long_glued_identifiers_remain_readable(self) -> None:
        for raw in (
            "task-ant-colony-optimization",
            "linuxapp-configuration-defaults",
            "task_test_configurationhandler",
            "dask-" + "word-" * 36 + "end",
            "dask-" + "word-" * 40 + "end",
            "dask-v2-scheduler-configuration-defaults-file",
            "flask-oauth2-client-configuration-defaults",
            "dask-v2-" + "word-" * 40 + "end",
        ):
            with self.subTest(raw=raw):
                self.assertEqual(raw, records.redact_secrets(raw))

    def test_distinctive_glued_shapes_need_no_character_mixture(self) -> None:
        for prefix, body, kept in (
            ("sk-lf-", "abcdefab-cdef-abcd-efab-cdefabcdefab", "sk-lf-"),
            ("pk-lf-", "abcdefab-cdef-abcd-efab-cdefabcdefab", "pk-lf-"),
            ("ghp_", "a" * 36, "ghp_"),
            ("gho_", "a" * 36, "gho_"),
            ("ghu_", "a" * 36, "ghu_"),
            ("ghs_", "a" * 36, "ghs_"),
            ("ghr_", "a" * 36, "ghr_"),
            ("glpat-", "a" * 20, "glpat-"),
            ("npm_", "a" * 36, "npm_"),
            ("phc_", "a" * 32, "phc_"),
            ("AIza", "a" * 35, "AIza"),
            ("eyJ", "a" * 8 + "." + "b" * 8 + "." + "c" * 8, "eyJ"),
        ):
            for lead in ("use ", "use=", "cfg_", "abc"):
                with self.subTest(prefix=prefix, lead=lead):
                    self.assertEqual(
                        lead + kept + "…REDACTED", records.redact_secrets(lead + prefix + body)
                    )

    def test_collision_prone_glued_shapes_need_ascii_character_evidence(self) -> None:
        for prefix, kept, length in (
            ("sk-ant-", "sk-ant-", 16),
            ("sk_live_", "sk_live_", 20),
            ("xoxb-", "xoxb-", 15),
            ("sk-", "sk-", 32),
        ):
            for lead in ("use ", "use=", "cfg_", "abc"):
                for last in ("a", "A", "0"):
                    body = "a" * (length - 1) + last
                    raw = lead + prefix + body
                    expected = (
                        raw
                        if lead in ("cfg_", "abc") and last == "a"
                        else lead + kept + "…REDACTED"
                    )
                    with self.subTest(prefix=prefix, lead=lead, last=last):
                        self.assertEqual(expected, records.redact_secrets(raw))

    def test_anthropic_variant_digits_are_evidence_after_the_retained_prefix(self) -> None:
        for variant in ("api03-", "oat01-", "ort01-"):
            with self.subTest(variant=variant):
                self.assertEqual(
                    "abcsk-ant-…REDACTED", records.redact_secrets("abcsk-ant-" + variant + "a" * 16)
                )

    def test_published_and_model_bound_prose_redacts_before_a_cut(self) -> None:
        for prefix, body, kept in self.PREFIXED:
            if (prefix, body) in (("sk-", "c" * 32), ("sk-proj-", "c" * 156)):
                continue
            for lead in ("cfg_", "abc"):
                with self.subTest(prefix=prefix, lead=lead):
                    raw = "Fix " + lead + prefix + body + " then retry"
                    for clean in (records.safe_text, records.redact_clip):
                        cut = len("Fix " + lead + kept) + 1
                        self.assertEqual("Fix " + lead + kept + "…REDACTED", clean(raw, cut))
                    self.assertEqual(
                        "Fix " + lead + kept + "…REDACTED then retry", records.mask_prose(raw)
                    )

    def test_short_or_wrong_alphabet_bodies_are_ordinary_identifiers(self) -> None:
        for prefix, body in (
            ("sk-ant-", "hill"),
            ("sk-", "top"),
            ("sk-lf-", "g" * 28),
            ("pk-lf-", "g" * 36),
            ("sk_live_", "a" * 19),
            ("rk_test_", "_" * 24),
            ("AKIA", "a" * 16),
            ("ASIA", "0" * 15),
            ("ghp_", "identifier"),
            ("gho_", "_" * 36),
            ("ghu_", "D" * 35),
            ("ghs_", "-" * 36),
            ("ghr_", "D" * 35),
            ("github_pat_", "v" * 39),
            ("glpat-", "w" * 19),
            ("npm_", "_" * 36),
            ("lin_api_", "z" * 39),
            ("xoxb-", "f" * 14),
            ("xapp-", "_" * 15),
            ("phc_", "g" * 31),
            ("AIza", "h" * 34),
            ("eyJ", "i" * 30),
            ("ya29.", "f" * 19),
        ):
            for lead in self.LEADS:
                raw = lead + prefix + body + " then retry"
                with self.subTest(raw=raw):
                    self.assertEqual(raw, records.redact_secrets(raw))
        for raw in (
            "task-ant-hill",
            "desk-top",
            "dask-scheduler-configuration-defaults-file-name",
        ):
            with self.subTest(raw=raw):
                self.assertEqual(raw, records.redact_secrets(raw))
