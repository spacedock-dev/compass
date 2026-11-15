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

    def test_every_prefix_redacts_regardless_of_the_preceding_character(self) -> None:
        for prefix, body, kept in self.PREFIXED:
            for lead in self.LEADS:
                with self.subTest(prefix=prefix, body=body, lead=lead):
                    raw = lead + prefix + body + " then retry"
                    expected = lead + kept + "…REDACTED then retry"
                    self.assertEqual(expected, records.redact_secrets(raw))
                    self.assertEqual(expected, records.redact_secrets(expected))

    def test_published_and_model_bound_prose_redacts_before_a_cut(self) -> None:
        for prefix, body, kept in self.PREFIXED:
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
