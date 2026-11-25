"""A person's authorization values never reach published or model-bound text.

Every credential below is made up for this test; no credential store is read.
"""

from __future__ import annotations

import unittest

from compass_runtime import records


class APersonSharingAuthorization(unittest.TestCase):
    def assert_shared_text(self, raw: str, expected: str) -> None:
        for surface, shown in (
            ("redact_secrets", records.redact_secrets(raw)),
            ("mask_prose", records.mask_prose(raw)),
            ("safe_text", records.safe_text(raw, 4_000)),
        ):
            with self.subTest(raw=raw, surface=surface):
                self.assertEqual(expected, shown)

    def assert_private(self, raw: str, value: str) -> None:
        for mask in (records.redact_secrets, records.mask_prose):
            with self.subTest(raw=raw, mask=mask.__name__):
                masked = mask(raw)
                self.assertNotIn(value, masked)
                self.assertIn(records.SECRET_MARKER, masked)

    def test_a_person_can_escape_a_curl_header_without_publishing_its_value(self) -> None:
        for scheme in ("Basic", "Token", "Bearer", "Negotiate"):
            value = "dXNlcjpwYXNz"
            self.assert_private(
                f"curl -H Authorization:{scheme}\\ {value} https://example.test", value
            )

    def test_escaped_header_masks_the_token_across_surfaces(self) -> None:
        value = "dXNlcjpzM2NyZXRwYXNzd29yZA=="
        for raw in (
            rf"Authorization:\ Basic\ {value}",
            rf"curl -H Authorization:\ Basic\ {value} https://example.test",
        ):
            expected = raw.replace(value, "…REDACTED")
            self.assertEqual(expected, records.redact_secrets(raw))
            self.assertEqual(expected, records.safe_text(raw, 4_000))
            self.assertEqual(
                expected.replace("Authorization:\\", "Authorization:…REDACTED"),
                records.mask_prose(raw),
            )

    def test_curl_executable_case_does_not_expose_the_password(self) -> None:
        for command in ("CURL", "CuRl"):
            self.assert_shared_text(
                f"{command} -u user:MadeUpPass99 https://example.test",
                f"{command} -u user:…REDACTED https://example.test",
            )

    def test_curl_masks_the_entire_login_in_direct_user_options(self) -> None:
        for option in ("-u ", "--user ", "--user=", "-u"):
            for quote in ("", "'", '"'):
                raw = f"curl {option}{quote}alice:MadeUpPass99{quote} https://example.test"
                expected = f"curl {option}{quote}…REDACTED{quote} https://example.test"
                self.assertEqual(expected, records.redact_secrets(raw))
                self.assertEqual(expected, records.safe_text(raw, 4_000))
                self.assertEqual(
                    f"curl {option}{quote}…REDACTED https://example.test", records.mask_prose(raw)
                )

    def test_curl_keeps_literal_example_pairs_and_empty_passwords(self) -> None:
        for option in ("-u ", "--user="):
            for value in ("user:password", "USER:PASS", "admin:", '"user:password"'):
                raw = f"curl {option}{value} https://example.test"
                self.assert_shared_text(raw, raw)
        raw = "curl '--user=user:password' https://example.test"
        self.assert_shared_text(raw, raw)

    def test_curl_masks_a_login_with_an_empty_password_except_the_admin_example(self) -> None:
        for option in ("-u ", "--user=", "-u"):
            for password in ("", "''", '""'):
                self.assert_shared_text(
                    f"curl {option}reader:{password}", f"curl {option}…REDACTED"
                )
            self.assert_shared_text(f"curl {option}admin:", f"curl {option}admin:")
        self.assert_shared_text(
            "curl -u admin:\x00 https://e.test", "curl -u …REDACTED https://e.test"
        )
        self.assert_shared_text(
            "CURL -u admin:\x00 https://e.test", "CURL -u …REDACTED https://e.test"
        )
        self.assert_shared_text("CURL -u reader:''", "CURL -u …REDACTED")

    def test_curl_keeps_base_masking_for_executable_prefixes(self) -> None:
        for program in (r"\curl", r".\curl", r"C:\bin\curl", "!curl", "*curl"):
            self.assert_shared_text(
                f"{program} -u alice:MadeUpPass99 https://e.test",
                f"{program} -u …REDACTED https://e.test",
            )
        for block in ("pre", "p"):
            self.assert_shared_text(
                f"<{block}>curl -u alice:MadeUpPass99</{block}>", f"<{block}>curl -u …REDACTED"
            )
        raw = "CMD=curl -u alice:MadeUpPass99 https://e.test"
        expected = "CMD=curl -u …REDACTED https://e.test"
        self.assertEqual(expected, records.redact_secrets(raw))
        self.assertEqual(expected, records.safe_text(raw, 4_000))
        self.assertEqual("CMD=…REDACTED -u …REDACTED https://e.test", records.mask_prose(raw))

    def test_curl_url_does_not_start_a_command(self) -> None:
        raw = "The page https://example.test/curl documents --proxy-user format:field"
        self.assert_shared_text(raw, raw)

    def test_curl_keeps_legacy_user_masking_in_dotted_and_url_tokens(self) -> None:
        for program in ("foo.curl", "https://example.test/curl"):
            for flag in ("-u ", "--user="):
                self.assert_shared_text(
                    f"{program} {flag}alice:MadeUpPass99", f"{program} {flag}…REDACTED"
                )

    def test_curl_examples_require_an_unmodified_command_and_word(self) -> None:
        for command in ("cu<!-- note -->rl -u", "curl -\u200bu"):
            raw = f"{command} user:password https://example.test"
            for shown in (
                records.redact_secrets(raw),
                records.mask_prose(raw),
                records.safe_text(raw, 4_000),
            ):
                self.assertNotIn("user:password", shown)
                self.assertIn("…REDACTED", shown)
        self.assertEqual(
            "curl -u user:…REDACTED", records.mask_prose("curl\n-u u\u200bser:password")
        )

    def test_curl_short_option_arguments_do_not_start_user_flags(self) -> None:
        for flag in ("-dmenu", "-omenu", "-sdmenu"):
            raw = f"curl {flag} https://example.test/guide"
            self.assertEqual(raw, records.redact_secrets(raw))
            self.assertEqual(raw, records.safe_text(raw, 4_000))
            self.assertEqual(f"curl {flag} https:…REDACTED", records.mask_prose(raw))

    def test_curl_prose_keeps_the_base_word_fallback(self) -> None:
        for raw, expected in (
            ("curl -u 'alice:$MadeUpPass99'", "curl -u 'alice:…REDACTED"),
            ("curl -u 'alice:pw(MadeUpPass99)'", "curl -u 'alice:…REDACTED"),
            ("curl -u 'alice:{MadeUpPass99}'", "curl -u 'alice:…REDACTED"),
            (r"curl -u alice:abc\;MadeUpPass99", "curl -u …REDACTED"),
            ('curl -u alice:abc"MadeUpPass99', "curl -u …REDACTED"),
            ("curl\n-u alice:MadeUpPass99", "curl -u alice:…REDACTED"),
            ("curl -u\nalice:MadeUpPass99", "curl -u alice:…REDACTED"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(expected, records.mask_prose(raw))
        self.assertEqual(
            ["curl", "--proxy-user", "alice:…REDACTED"],
            records.mask_words(["curl", "--proxy-user", "alice:MadeUpPass99"], prose=True),
        )

    def test_curl_masks_an_escaped_quote_inside_a_double_quoted_argument(self) -> None:
        for option in ('-u "', '"--user=', '"--proxy-user='):
            raw = rf'curl {option}alice:abc\"MadeUpPass99" https://example.test'
            for mask in (
                records.redact_secrets,
                records.mask_prose,
                lambda s: records.safe_text(s, 4_000),
            ):
                with self.subTest(raw=raw, mask=mask):
                    self.assertNotIn("MadeUpPass99", mask(raw))
                    self.assertIn("…REDACTED", mask(raw))

    def test_curl_masks_an_unclosed_double_quoted_argument_ending_in_a_backslash(self) -> None:
        self.assert_shared_text('curl -u "alice:MadeUpPass99\\', 'curl -u "…REDACTED')

    def test_curl_cannot_extend_a_previously_masked_value_into_a_template_exception(self) -> None:
        for raw in (
            r'curl -u "alice:<abc\"MadeUpPass99>" https://example.test',
            "curl '--user=alice:<abc MadeUpPass99>' https://example.test",
        ):
            for shown in (
                records.redact_secrets(raw),
                records.mask_prose(raw),
                records.safe_text(raw, 4_000),
            ):
                self.assertNotIn("alice:", shown)
                self.assertNotIn("MadeUpPass99", shown)
                self.assertIn("…REDACTED", shown)

    def test_curl_masks_base_credentials_with_non_example_markdown_delimiters(self) -> None:
        for raw, expected in (
            ("[curl -u user:password]", "[curl -u …REDACTED"),
            ("(curl -u user:password)", "(curl -u …REDACTED"),
            ("Use ``curl -u user:password`` here", "Use ``curl -u …REDACTED here"),
            ("curl -u user:password`.", "curl -u …REDACTED"),
            ("Run `curl -u alice:MadeUpPass99`.", "Run `curl -u …REDACTED"),
            ("curl -u read<wbr>er:MadeUpPass99", "curl -u …REDACTED"),
        ):
            self.assert_shared_text(raw, expected)

    def test_curl_must_be_the_full_executable_basename(self) -> None:
        for program in ("docs.CURL", "libcurl", "curly", "my-curl"):
            raw = f"{program} -u label:value"
            self.assert_shared_text(raw, raw)
        self.assert_shared_text("/bin/CuRl -u label:value", "/bin/CuRl -u label:…REDACTED")

    def test_curl_masks_a_password_quoted_on_its_own(self) -> None:
        for quote in ("'", '"'):
            self.assert_shared_text(
                f"curl -u alice:{quote}MadeUp Pass99{quote} https://example.test",
                "curl -u …REDACTED https://example.test",
            )

    def test_curl_masks_a_password_with_no_username(self) -> None:
        for option in ("-u ", "--user=", "-u"):
            self.assert_shared_text(
                f"curl {option}:MadeUpPass99 https://example.test",
                f"curl {option}:…REDACTED https://example.test",
            )

    def test_uppercase_curl_masks_clustered_and_lexed_user_options(self) -> None:
        self.assert_shared_text("CURL -sSu alice:MadeUpPass99", "CURL -sSu alice:…REDACTED")
        self.assert_shared_text("curl -nu alice:MadeUpPass99", "curl -nu alice:…REDACTED")
        self.assertEqual(
            ["CURL", "-u", "alice:…REDACTED"],
            records.mask_words(["CURL", "-u", "alice:MadeUpPass99"], prose=False),
        )

    def test_curl_proxy_user_masks_separate_and_joined_passwords(self) -> None:
        for program in ("curl", "CURL"):
            for option in ("--proxy-user ", "--proxy-user="):
                self.assert_shared_text(
                    f"{program} {option}alice:MadeUpPass99 https://example.test",
                    f"{program} {option}alice:…REDACTED https://example.test",
                )
        self.assert_shared_text(
            "curl --proxy-user user:password https://example.test",
            "curl --proxy-user user:…REDACTED https://example.test",
        )
        self.assert_shared_text(
            "curl --proxy-user user:<token>", "curl --proxy-user user:…REDACTED"
        )

    def test_curl_keeps_the_outer_quote_on_a_joined_option(self) -> None:
        raw = """curl '--user=alice:MadeUpPass99"quote' https://example.test"""
        self.assertEqual(
            "curl '--user=…REDACTED' https://example.test", records.redact_secrets(raw)
        )
        self.assertEqual(
            "curl '--user=…REDACTED' https://example.test", records.safe_text(raw, 4_000)
        )
        self.assertEqual("curl '--user=…REDACTED https://example.test", records.mask_prose(raw))
        for flag in ("-u", "--proxy-user="):
            raw = f"curl '{flag}alice:MadeUpPass99\"quote' https://example.test"
            for shown in (records.redact_secrets(raw), records.safe_text(raw, 4_000)):
                self.assertNotIn('"quote', shown)
                self.assertTrue(shown.endswith("…REDACTED' https://example.test"), shown)

    def test_curl_joined_option_mask_is_stable_after_the_word_fallback_drops_the_quote(
        self,
    ) -> None:
        for flag, masked in (("--user=", "…REDACTED"), ("--proxy-user=", "alice:…REDACTED")):
            raw = f"curl '{flag}alice:MadeUpPass99\"quote' https://example.test"
            expected = f"curl '{flag}{masked} https://example.test"
            self.assertEqual(expected, records.mask_prose(raw))
            self.assertEqual(expected, records.mask_prose(expected))

    def test_curl_examples_keep_shell_and_markdown_delimiters(self) -> None:
        for raw in (
            "curl -u user:password; echo hi",
            "curl -u admin:; echo hi",
            "`curl -u user:password`",
            "Run `curl -u user:password`, then retry",
        ):
            self.assert_shared_text(raw, raw)
        raw = "curl -u alice:MadeUpPass99; echo hi"
        self.assertEqual("curl -u …REDACTED; echo hi", records.redact_secrets(raw))
        self.assertEqual("curl -u …REDACTED; echo hi", records.safe_text(raw, 4_000))
        self.assertEqual("curl -u …REDACTED echo hi", records.mask_prose(raw))
        self.assert_shared_text("curl -u alice:MadeUp`Pass99", "curl -u …REDACTED")

    def test_curl_masks_markup_between_the_username_and_password(self) -> None:
        for raw, expected in (
            (
                "curl -u alice:<!-- note -->MadeUpPass99 https://example.test",
                "curl -u …REDACTED https://example.test",
            ),
            (
                "curl -u user:p<!-- note -->assword https://example.test",
                "curl -u …REDACTED https://example.test",
            ),
            (
                "curl -u user:password<!-- note --> https://example.test",
                "curl -u …REDACTED https://example.test",
            ),
            (
                "curl -u admin:<!-- note --> https://example.test",
                "curl -u …REDACTED https://example.test",
            ),
        ):
            self.assert_shared_text(raw, expected)
        raw = 'curl -u alice:<a href="https://example.test">MadeUpPass99</a> https://example.test'
        self.assertEqual("curl -u …REDACTED</a> https://example.test", records.redact_secrets(raw))
        self.assertEqual(
            "curl -u …REDACTED</a> https://example.test", records.safe_text(raw, 4_000)
        )
        self.assertEqual("curl -u …REDACTED https://example.test", records.mask_prose(raw))

    def test_bearer_placeholders_stay_visible_in_literal_and_encoded_form(self) -> None:
        for placeholder in ("<token>", "%3Ctoken%3E", "%3ctoken%3e"):
            raw = f"Authorization: Bearer {placeholder} then retry"
            self.assert_shared_text(raw, raw)
        raw = "Authorization%3A%20Bearer%20%3Ctoken%3E"
        self.assert_shared_text(raw, raw)

    def test_bearer_placeholder_must_appear_literally_in_the_source(self) -> None:
        for value in (
            "%3Ct<!-- MadeUpPass99 -->oken%3E",
            "<t<!-- MadeUpPass99 -->oken>",
            '%3Ct<a href="https://example.test/MadeUpPass99">o</a>ken%3E',
            "%3Cto\u200bken%3E",
            "\u200b%3Ctoken%3E",
            "<em>%3Ctoken%3E</em>",
        ):
            self.assert_shared_text(
                f"Authorization: Bearer {value}", "Authorization: Bearer …REDACTED"
            )
        value = "%3Ct<!-- MadeUpPass99 -->oken%3E"
        raw = f"Authorization: Bearer\n{value}"
        self.assertEqual("Authorization: Bearer\n…REDACTED", records.redact_secrets(raw))
        self.assertEqual("Authorization: Bearer …REDACTED", records.mask_prose(raw))
        self.assertEqual("Authorization: Bearer …REDACTED", records.safe_text(raw, 4_000))
        self.assert_shared_text(
            f"Authorization%3A%20Bearer%20{value}", "Authorization%3A%20Bearer%20…REDACTED"
        )

    def test_bearer_example_is_exact_and_local_to_the_scheme(self) -> None:
        for scheme, value in (
            ("Token", "%3Ctoken%3E"),
            ("Bearer", "<TOKEN>"),
            ("Bearer", "%3cTOKEN%3e"),
        ):
            self.assert_shared_text(
                f"Authorization: {scheme} {value}", f"Authorization: {scheme} …REDACTED"
            )
        raw = "Authorization: Bearer\n%3Ctoken%3E9x"
        self.assertEqual("Authorization: Bearer\n…REDACTED", records.redact_secrets(raw))
        self.assertEqual("Authorization: Bearer …REDACTED", records.mask_prose(raw))
        self.assertEqual("Authorization: Bearer …REDACTED", records.safe_text(raw, 4_000))

    def test_escaped_basic_keeps_unpadded_brackets(self) -> None:
        for value in ("dXNlcjpwYXNz", "dXNlcjpzM2Ny"):
            self.assert_shared_text(
                rf"[Authorization:\ Basic\ {value}]", r"[Authorization:\ Basic\ …REDACTED]"
            )

    def test_basic_keeps_existing_masks_for_an_escaped_scheme_and_bracketed_value(self) -> None:
        self.assert_shared_text(
            r"Authorization: Basic\ dXNlcjpwYXNz https://example.test",
            r"Authorization: Basic\ …REDACTED https://example.test",
        )
        self.assert_shared_text("[Authorization: Basic x9]", "[Authorization: Basic …REDACTED")

    def test_padded_basic_keeps_delimiters_where_the_base_kept_them(self) -> None:
        value = "dXNlcjpzM2NyZXRwYXNzd29yZA=="
        for separator in ("\\ ", "\\ \\ "):
            raw = f"[Authorization:{separator}Basic{separator}{value}]"
            expected = f"[Authorization:{separator}Basic{separator}…REDACTED]"
            self.assertEqual(expected, records.redact_secrets(raw))
            self.assertEqual(expected, records.safe_text(raw, 4_000))
            self.assertEqual(expected[:-1], records.mask_prose(raw))
        for separator in (" ", "\\ ", "\\ \\ "):
            raw = f'"Authorization:{separator}Basic{separator}{value}"'
            expected = f'"Authorization:{separator}Basic{separator}…REDACTED"'
            self.assertEqual(expected, records.redact_secrets(raw))
            self.assertEqual(expected, records.safe_text(raw, 4_000))
            self.assertEqual(
                expected[:-1].replace("Authorization:\\", "Authorization:…REDACTED"),
                records.mask_prose(raw),
            )
        self.assert_shared_text(
            f"[Authorization: Basic {value}]", "[Authorization: Basic …REDACTED"
        )

    def test_basic_with_escaped_spaces_keeps_prose(self) -> None:
        raw = r"Authorization:\ Basic\ JavaScript clients"
        self.assertEqual(raw, records.redact_secrets(raw))
        self.assertEqual(raw, records.safe_text(raw, 4_000))
        self.assertEqual(
            r"Authorization:…REDACTED Basic\ JavaScript clients", records.mask_prose(raw)
        )

    def test_escaped_authorization_masks_bare_joined_and_extra_spaces(self) -> None:
        for raw, expected in (
            (r"Authorization:\ MadeUpToken99", r"Authorization:\ …REDACTED"),
            (
                r"Authorization:\ \ Basic\ \ dXNlcjpzM2NyZXRwYXNzd29yZA==",
                r"Authorization:\ \ Basic\ \ …REDACTED",
            ),
            (
                r"curl -HAuthorization:\ Basic\ dXNlcjpwYXNz https://example.test",
                r"curl -HAuthorization:\ Basic\ …REDACTED https://example.test",
            ),
        ):
            self.assertEqual(expected, records.redact_secrets(raw))
            self.assertEqual(expected, records.safe_text(raw, 4_000))
            self.assertEqual(
                expected.replace("Authorization:\\", "Authorization:…REDACTED")
                if raw.startswith("Authorization:")
                else expected,
                records.mask_prose(raw),
            )

    def test_escaped_authorization_masks_each_digest_and_aws_parameter(self) -> None:
        for scheme, parameters in (
            ("Digest", r'username="alice",\ response="MadeUp99"'),
            ("AWS4-HMAC-SHA256", r"Credential=MadeUp99,\ Signature=MadeUpPass99"),
        ):
            raw = rf"Authorization:\ {scheme}\ {parameters}"
            expected = rf"Authorization:\ {scheme}\ …REDACTED"
            self.assertEqual(expected, records.redact_secrets(raw))
            self.assertEqual(expected, records.safe_text(raw, 4_000))
            self.assertEqual(
                rf"Authorization:…REDACTED {scheme}\ …REDACTED", records.mask_prose(raw)
            )

    def test_a_trailing_powershell_reference_after_token_stays_visible(self) -> None:
        raw = "use the Token PowerShell"
        self.assert_shared_text(raw, raw)

    def test_powershell_example_requires_exact_source_spelling_at_line_end(self) -> None:
        for value in ("Power<!--wrap-->Shell", "Power\u200bShell"):
            self.assert_shared_text(f"use the Token {value}", "use the Token …REDACTED")
        self.assert_shared_text(
            "use the Token PowerShell, then retry", "use the Token …REDACTED, then retry"
        )
        self.assert_shared_text("use the Basic PowerShell", "use the Basic …REDACTED")
        raw = "use the Token PowerShell\nthen retry"
        self.assertEqual(raw, records.redact_secrets(raw))
        self.assertEqual("use the Token PowerShell then retry", records.mask_prose(raw))
        self.assertEqual("use the Token PowerShell then retry", records.safe_text(raw, 4_000))
        for newline in ("\r\n", "\n"):
            raw = f"use the Token PowerShell{newline}"
            self.assertEqual(raw, records.redact_secrets(raw))
            self.assertEqual("use the Token PowerShell", records.mask_prose(raw))
            self.assertEqual("use the Token PowerShell ", records.safe_text(raw, 4_000))
        for separator in ("\n", "\t"):
            raw = f"use the Token{separator}PowerShell"
            self.assertEqual(f"use the Token{separator}…REDACTED", records.redact_secrets(raw))
            self.assertEqual("use the Token …REDACTED", records.mask_prose(raw))
            self.assertEqual("use the Token …REDACTED", records.safe_text(raw, 4_000))
        raw = "use the Token\x00PowerShell"
        self.assertEqual(raw, records.redact_secrets(raw))
        self.assertEqual("use the Token …REDACTED", records.mask_prose(raw))
        self.assertEqual("use the Token …REDACTED", records.safe_text(raw, 4_000))
        raw = "use the Token PowerShell\n\x00\x00"
        self.assertEqual(raw, records.redact_secrets(raw))
        self.assertEqual("use the Token PowerShell", records.mask_prose(raw))
        self.assertEqual("use the Token PowerShell  ", records.safe_text(raw, 4_000))
        self.assertEqual(
            "  use the Token PowerShell",
            records.safe_text("\x00\x00 use the Token PowerShell", 4_000),
        )
        self.assertEqual(
            "First line. use the Token …REDACTED, then retry",
            records.safe_text("First line.\nuse the Token PowerShell, then retry", 4_000),
        )

    def test_explicit_wrapped_token_header_masks_powershell(self) -> None:
        for name in ("Authorization", "Proxy-Authorization"):
            for raw in (f"{name}: Token\nPowerShell", f"{name}:\nToken PowerShell"):
                self.assertEqual(
                    raw.replace("PowerShell", "…REDACTED"), records.redact_secrets(raw)
                )
                self.assertEqual(f"{name}: Token …REDACTED", records.mask_prose(raw))
                self.assertEqual(f"{name}: Token …REDACTED", records.safe_text(raw, 4_000))

    def test_explicit_wrapped_token_header_accepts_escaped_spaces(self) -> None:
        raw = "Authorization:\\ \nToken PowerShell"
        self.assertEqual("Authorization:\\ \nToken …REDACTED", records.redact_secrets(raw))
        self.assertEqual("Authorization:…REDACTED Token …REDACTED", records.mask_prose(raw))
        self.assertEqual("Authorization:\\  Token …REDACTED", records.safe_text(raw, 4_000))

    def test_credentials_close_to_placeholder_spellings_still_mask(self) -> None:
        for user, password in (("user", "password9zD8rU5m"), ("admin", "MadeUpPass99")):
            self.assert_shared_text(
                f"curl -u {user}:{password} https://example.test",
                "curl -u …REDACTED https://example.test",
            )
        for raw, expected in (
            ("Authorization: Bearer %3Ctoken%3E9x", "Authorization: Bearer …REDACTED"),
            ("Authorization: Bearer %3Ctoken%3EMadeUp99", "Authorization: Bearer …REDACTED"),
            ("Authorization: Token PowerShell", "Authorization: Token …REDACTED"),
            ("Authorization: Token abcdefghijklmnop", "Authorization: Token …REDACTED"),
            ("('Authorization', 'Token abcdefghijklmnop')", "('Authorization', 'Token …REDACTED')"),
        ):
            self.assert_shared_text(raw, expected)
        self.assert_shared_text(
            "Authorization: Basic JavaScript clients", "Authorization: Basic JavaScript clients"
        )

    def test_a_person_can_share_a_schemeless_header_without_publishing_its_token(self) -> None:
        for header in ("Authorization", "Proxy-Authorization"):
            for template in ("{header}: {value} then retry", '{{"{header}": "{value}"}}'):
                value = "MadeUpToken99"
                raw = template.format(header=header, value=value)
                self.assert_private(raw, value)
                self.assertEqual(
                    raw.replace(value, records.SECRET_MARKER), records.redact_secrets(raw)
                )

    def test_a_person_can_pass_any_authorization_scheme_as_a_call_argument(self) -> None:
        for scheme, value in (
            ("Basic", "dXNlcjpwYXNz"),
            ("Bearer", "MadeUpToken99"),
            ("Token", "dXNlcjpwYXNz"),
            ("Negotiate", "dXNlcjpwYXNz"),
            ("NTLM", "dXNlcjpwYXNz"),
            ("Digest", 'username="MadeUpUser", response="MadeUpResponse"'),
            (
                "AWS4-HMAC-SHA256",
                "Credential=MadeUp/scope, SignedHeaders=host;x-date, Signature=MadeUpSig",
            ),
            ("Future-Scheme", "MadeUpToken99"),
        ):
            for header in ("Authorization", "Proxy-Authorization"):
                for template in (
                    "Header.Set(\"{header}\", '{scheme} {value}')",
                    "headers.append('{header}', '{scheme} {value}')",
                    "('{header}', '{scheme} {value}')",
                ):
                    raw = template.format(header=header, scheme=scheme, value=value)
                    self.assert_private(raw, value)
                    self.assertEqual(
                        raw.replace(value, records.SECRET_MARKER), records.redact_secrets(raw)
                    )

    def test_a_person_can_share_curl_user_credentials_without_publishing_them(self) -> None:
        for flag, space in (("-u", " "), ("--user", " "), ("--user=", ""), ("-u", "")):
            for value in ("madeup:password", "madeup:pass99"):
                for quote in ("", "'", '"'):
                    raw = f"curl {flag}{space}{quote}{value}{quote} https://example.test"
                    self.assert_private(raw, value)
                    self.assert_private(raw, value.split(":", 1)[1])

    def test_a_person_can_share_a_percent_encoded_header_without_its_value(self) -> None:
        for scheme, value in (
            ("Basic", "dXNlcjpwYXNz"),
            ("Token", "MadeUpToken99"),
            ("Basic", "YTpi"),
        ):
            self.assert_private(f"Authorization%3A%20{scheme}%20{value}", value)

    def test_a_person_can_wrap_a_short_letters_only_scheme_value_in_code(self) -> None:
        for value in ("dXNlcjpwYXNz", "VXNlcjpw"):
            for scheme in ("Basic", "Token", "Negotiate", "NTLM"):
                for template in (
                    "Authorization: {scheme}\n{value}",
                    'f"{scheme} {value}"',
                    'Header.Set("Authorization", "{scheme} {value}")',
                    r"{{\"Authorization\": \"{scheme} {value}\"}}",
                    "HTTP_AUTHORIZATION={scheme} {value}",
                ):
                    self.assert_private(template.format(scheme=scheme, value=value), value)

    def test_a_person_can_keep_even_a_tiny_basic_header_credential_private(self) -> None:
        for value in ("YTpi", "eA==", "abcd"):
            raw = f"Authorization: Basic {value}"
            self.assert_private(raw, value)
            self.assertEqual(raw.replace(value, records.SECRET_MARKER), records.redact_secrets(raw))

    def test_a_person_can_assign_either_langfuse_key_with_uppercase_hex_privately(self) -> None:
        value = "ABCDEF01-2345-6789-ABCD-EF0123456789"
        for prefix in ("pk-lf-", "sk-lf-"):
            for name in ("PK", "LANGFUSE_PUBLIC_KEY"):
                raw = f"{name}={prefix}{value}"
                self.assert_private(raw, value)
            self.assertEqual(f"PK={prefix}…REDACTED", records.redact_secrets(f"PK={prefix}{value}"))

    def test_a_person_can_share_any_authorization_scheme_without_its_value(self) -> None:
        for header in ("Authorization", "Proxy-Authorization", "aUtHoRiZaTiOn"):
            for scheme, value in (
                ("Bearer", "MadeUpBearer99"),
                ("Basic", "ZmFrZTpmYWtlOTk="),
                ("Digest", 'username="MadeUpUser99", realm="MadeUpRealm99", response="MadeUp99"'),
                ("Token", "MadeUpToken99"),
                (
                    "AWS4-HMAC-SHA256",
                    "Credential=MadeUp99/scope, SignedHeaders=host, Signature=MadeUpSig99",
                ),
                ("Negotiate", "MadeUpTicket99=="),
                ("Future-Scheme", "MadeUpValue99"),
            ):
                for template in (
                    "{header}: {scheme} {value}",
                    '{{"{header}": "{scheme} {value}"}}',
                    "{header}: '{scheme} {value}'",
                    "curl -H '{header}: {scheme} {value}' https://example.test",
                    'curl --header "{header}: {scheme} {value}" https://example.test',
                    "curl --header='{header}: {scheme} {value}' https://example.test",
                    "{header}='{scheme} {value}' run",
                    '{header}="{scheme} {value}" run',
                    "{header}={scheme} {value}",
                ):
                    # JSON and a double-quoted shell header escape inner parameter quotes.
                    escaped = (
                        value.replace('"', '\\"')
                        if '"{scheme}' in template or ': "{scheme}' in template
                        else value
                    )
                    raw = template.format(header=header, scheme=scheme, value=escaped)
                    expected = template.format(
                        header=header, scheme=scheme, value=records.SECRET_MARKER
                    )
                    with self.subTest(header=header, scheme=scheme, template=template):
                        self.assertEqual(expected, records.redact_secrets(raw))
                        if template == "{header}: {scheme} {value}":
                            self.assertEqual(expected, records.mask_prose(raw))
                        for mask in (records.redact_secrets, records.mask_prose):
                            masked = mask(raw)
                            self.assertNotIn("MadeUp", masked)
                            self.assertNotIn("ZmFrZTpmYWtlOTk=", masked)
                            self.assertNotIn("madeup", masked)
                            self.assertIn(records.SECRET_MARKER, masked)

    def test_a_person_can_share_quoted_authorization_values_and_keep_nearby_words(self) -> None:
        for raw, expected in (
            (
                'send Authorization: Basic "MadeUpValue99" then retry',
                'send Authorization: Basic "…REDACTED" then retry',
            ),
            (
                "send Proxy-Authorization: Custom MadeUpValue99 then retry",
                "send Proxy-Authorization: Custom …REDACTED then retry",
            ),
            (
                "Authorization: Basic MadeUpValue99\nnext line stays",
                "Authorization: Basic …REDACTED\nnext line stays",
            ),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(expected, records.redact_secrets(raw))
                self.assertNotIn("MadeUpValue99", records.mask_prose(raw))
                self.assertIn("…REDACTED", records.mask_prose(raw))

    def test_a_person_can_share_either_langfuse_key_without_its_body(self) -> None:
        for prefix in ("sk-lf-", "pk-lf-"):
            for body in (
                "00000000-1111-2222-3333-444444444444",
                "abcdef01-2345-6789-abcd-ef0123456789",
            ):
                raw = f"rotate {prefix}{body} then retry"
                for mask in (records.redact_secrets, records.mask_prose):
                    with self.subTest(prefix=prefix, size=len(body), mask=mask.__name__):
                        self.assertEqual(f"rotate {prefix}…REDACTED then retry", mask(raw))

    def test_a_person_can_discuss_authentication_without_supplying_a_value(self) -> None:
        for raw in (
            "Basic Authentication is deprecated",
            "use basic auth for the staging proxy",
            "Authorization: Bearer ${TOKEN}",
            "Authorization: none, the route is public",
            "auth = request.headers.get('Authorization', 'Basic default')",
            'self.authorization = "Basic " + encoded',
            "git push -u origin main",
            "docker run -u 1000:1000 image",
            "curl -u madeup https://example.test",
            "Authorization%3A%20Basic%20<base64>",
            "Authorization%3A%20Custom%20SomeWords",
            "use basic auth",
            "the Authorization header",
            "Bearer tokens expire",
            "grep -n 'Authorization:' server.log",
            "grep -n 'Proxy-Authorization:' server.log",
            "Authorization: Basic",
            "Proxy-Authorization: Negotiate",
            "the prefixes sk-lf- and pk-lf- identify Langfuse keys",
            'headers["Authorization"] = make_header()',
            "X-Authorization: Custom madeup",
            "Authorization: Custom",
            "use sk-lf-identifier and pk-lf-label as example prefixes",
        ):
            for mask in (records.redact_secrets, records.mask_prose):
                with self.subTest(raw=raw, mask=mask.__name__):
                    self.assertEqual(
                        " ".join(raw.split()) if mask is records.mask_prose else raw, mask(raw)
                    )

    def test_a_person_can_wrap_a_header_without_publishing_its_credential(self) -> None:
        value = "ZmFrZXVzZXI6ZmFrZXBhc3M+/w=="
        for header in ("Authorization", "Proxy-Authorization"):
            for scheme in ("Basic", "Token", "Negotiate", "NTLM", "Bearer"):
                for raw in (
                    f"{header}: {scheme}\n{value}",
                    f"{header}:\n  {scheme} {value}",
                ):
                    for mask in (records.redact_secrets, records.mask_prose):
                        with self.subTest(raw=raw, mask=mask.__name__):
                            expected = raw.replace(value, records.SECRET_MARKER)
                            if mask is records.mask_prose:
                                expected = " ".join(expected.split())
                            self.assertEqual(expected, mask(raw))
            with self.subTest(header=header):
                self.assertEqual(
                    f"{header}: …REDACTED",
                    records.mask_prose(f"{header}:\n{value}"),
                )
                for raw in (
                    f"{header}: Basic\nnext line stays",
                    f"{header}:\nordinary words",
                    f"{header}: Basic\nshort99",
                    f"{header}:\nauthenticationrequirements",
                ):
                    self.assertEqual(" ".join(raw.split()), records.mask_prose(raw))

    def test_a_person_can_share_a_scheme_in_code_without_publishing_its_credential(self) -> None:
        value = "ZmFrZXVzZXI6ZmFrZXBhc3M+/w=="
        for scheme in ("Basic", "Token", "Negotiate", "NTLM", "bAsIc"):
            for raw in (
                f'f"{scheme} {value}"',
                r"{\"Authorization\": \"" + f"{scheme} {value}" + r"\"}",
                f"HTTP_AUTHORIZATION={scheme} {value}",
                f'Header.Set("Authorization", "{scheme} {value}")',
                f"headers.append('Authorization', '{scheme} {value}')",
                f"('Authorization','{scheme} {value}')",
                f"Authorization: {scheme}\n{value}",
                f"{{Authorization: `{scheme} {value}`}}",
            ):
                for mask in (records.redact_secrets, records.mask_prose):
                    with self.subTest(raw=raw, mask=mask.__name__):
                        expected = raw.replace(value, records.SECRET_MARKER)
                        if mask is records.mask_prose:
                            expected = " ".join(expected.split())
                            if raw.startswith("HTTP_AUTHORIZATION="):
                                expected = "HTTP_AUTHORIZATION=…REDACTED …REDACTED"
                        self.assertEqual(expected, mask(raw))

    def test_a_person_can_publish_authentication_instructions_and_placeholders(self) -> None:
        for raw in (
            "authorization: required for all routes",
            "check Authorization= in the config",
            "set the Authorization: Basic header and retry",
            "Authorization: Basic auth is weak, use OAuth",
            "Proxy-Authorization: Basic and Authorization: Basic both fail",
            "pk-lf-chart-component-renders-the-legend",
            *(
                f"Authorization: {scheme} {value}"
                for scheme in (
                    "Basic",
                    "Token",
                    "Negotiate",
                    "Digest",
                    "AWS4-HMAC-SHA256",
                    "Future-Scheme",
                )
                for value in ("<base64>", "{token}", "...", "$CREDS", "os.environ['X']")
            ),
            *(
                f"{scheme} {value}"
                for scheme in ("Basic", "Token", "Negotiate", "NTLM")
                for value in (
                    "authentication",
                    "abcdefghijklmnop",
                    "short99",
                    "<base64>",
                    "{token}",
                    "...",
                )
            ),
        ):
            for mask in (records.redact_secrets, records.mask_prose):
                with self.subTest(raw=raw, mask=mask.__name__):
                    self.assertEqual(raw, mask(raw))

    def test_a_person_still_keeps_an_api_key_header_value_private(self) -> None:
        self.assertEqual(
            "X-Api-Key: …REDACTED then retry", records.mask_prose("X-Api-Key: madeup then retry")
        )

    def test_a_person_can_show_code_that_reads_an_authorization_value(self) -> None:
        for value in ("None", "null", "$MADE_UP_TOKEN", "${MADE_UP_TOKEN}", "make_header()"):
            raw = f"Authorization: Custom {value}"
            with self.subTest(value=value):
                self.assertEqual(raw, records.redact_secrets(raw))

    def test_a_person_can_share_long_or_unclosed_quoted_values_without_a_tail(self) -> None:
        for header in ("Authorization", "Proxy-Authorization"):
            for ending in ('"}', "", "\r\nnext line stays"):
                raw = f'{{"{header}": "Custom ' + "MadeUp99" * 1000 + ending
                with self.subTest(header=header, ending=ending):
                    for mask in (records.redact_secrets, records.mask_prose):
                        masked = mask(raw)
                        self.assertNotIn("MadeUp", masked)
                        self.assertIn("…REDACTED", masked)
                        if mask is records.redact_secrets or ending != "\r\nnext line stays":
                            self.assertEqual(masked, mask(masked))

    def test_a_person_can_share_digest_parameters_with_escaped_quotes(self) -> None:
        raw = 'Authorization: Digest username="MadeUp\\"User99", response="MadeUpResponse99"'
        for mask in (records.redact_secrets, records.mask_prose):
            with self.subTest(mask=mask.__name__):
                self.assertEqual("Authorization: Digest …REDACTED", mask(raw))

    def test_a_person_does_not_publish_the_tail_of_a_truncated_authorization_value(self) -> None:
        for header in ("Authorization", "Proxy-Authorization"):
            for raw, expected in (
                ('"{header}": "Basic MadeUp99\\', '"{header}": "Basic …REDACTED'),
                ('{header}: Digest username="MadeUp99', "{header}: Digest …REDACTED"),
                ('{header}: Basic "MadeUp99\\', '{header}: Basic "…REDACTED'),
            ):
                with self.subTest(header=header, raw=raw):
                    for mask in (records.redact_secrets, records.mask_prose):
                        masked = mask(raw.format(header=header))
                        if mask is records.redact_secrets:
                            self.assertEqual(expected.format(header=header), masked)
                        self.assertNotIn("MadeUp", masked)
                        self.assertIn("…REDACTED", masked)

    def test_a_person_can_share_a_short_letters_only_basic_value_without_it(self) -> None:
        # Base64 of a short user:pass can be letters only with no padding (made up here).
        value = "dXNlcjpwYXNz"
        for raw in (
            f"Authorization: Basic {value}",
            f"curl -H 'authorization: basic {value}' https://example.test",
            f'{{"Authorization": "Basic {value}"}}',
        ):
            for mask in (records.redact_secrets, records.mask_prose):
                with self.subTest(raw=raw, mask=mask.__name__):
                    masked = mask(raw)
                    self.assertNotIn(value, masked)
                    self.assertIn("…REDACTED", masked)

    def test_a_person_can_name_basic_authentication_in_prose(self) -> None:
        for raw in ("Authorization: Basic Authentication is deprecated here",):
            for mask in (records.redact_secrets, records.mask_prose):
                with self.subTest(mask=mask.__name__):
                    self.assertIn("Authentication", mask(raw))

    def test_a_person_can_share_encoded_basic_padding_without_publishing_the_value(self) -> None:
        for value in (
            "YWxpY2U6czNjcmV0%3D",
            "YWxpY2U6czNjcmV0MTI%3d",
            "dXNlcjpwYXNzd29yZA%3D%3D",
            "ZmFrZXVzZXI6ZmFrZXBhc3M%2B%2Fw%3D%3D",
            "ZmFrZXVzZXI6ZmFrZXBhc3M%2b%2fw%3d%3d",
        ):
            for template in (
                "Authorization%3A%20Basic%20{value}",
                "?h=Authorization%3a+Basic+{value}&x=1",
            ):
                raw = template.format(value=value)
                self.assert_private(raw, value)
                for mask in (records.redact_secrets, records.mask_prose):
                    with self.subTest(raw=raw, mask=mask.__name__):
                        self.assertEqual(raw.replace(value, records.SECRET_MARKER), mask(raw))

    def test_a_person_can_continue_a_curl_command_without_publishing_the_password(self) -> None:
        value = "alice:MadeUpPass99"
        for newline in ("\n", "\r\n"):
            continuation = "\\" + newline
            for flag in ("-u ", "--user ", "--user=", "-u"):
                for prefix in ("curl -X POST https://example.test", "curl -H 'A: b'"):
                    raw = f"{prefix} {continuation}  {flag}{value}"
                    self.assert_private(raw, "MadeUpPass99")
                    expected = raw.replace(value, "…REDACTED")
                    self.assertEqual(expected, records.redact_secrets(raw))
                    self.assertEqual(" ".join(expected.split()), records.mask_prose(raw))
            raw = f"curl {continuation} -H 'A: b' {continuation} -u '{value}' {continuation} https://example.test"
            self.assert_private(raw, "MadeUpPass99")

    def test_a_person_can_run_another_command_after_curl_without_hiding_its_arguments(self) -> None:
        for boundary in ("\n", "\r\n", ";", "|", "&"):
            raw = f"curl https://example.test{boundary} other -u alice:MadeUpPass99"
            self.assertEqual(raw, records.redact_secrets(raw))

    def test_a_person_can_discuss_basic_headers_without_losing_prose_words(self) -> None:
        for words in (
            "or Bearer",
            "then Digest",
            "with a password",
            "is fine",
            "test",
            "Credentials needed",
            "Auth",
            "Base",
            "none",
            "YES",
            "user",
            "JavaScript tutorial",
            "McDonald menu",
        ):
            for header in ("Authorization", "Proxy-Authorization"):
                raw = f"{header}: Basic {words}"
                for mask in (records.redact_secrets, records.mask_prose):
                    with self.subTest(raw=raw, mask=mask.__name__):
                        self.assertEqual(raw, mask(raw))

    def test_a_person_can_discuss_camelcase_technologies_after_a_scheme(self) -> None:
        for raw in (
            "Basic JavaScript tutorial",
            "Token PostgreSQL connection",
            "Basic McDonald menu",
            "Basic JavaScript tutorial and Token PostgreSQL connection",
        ):
            for mask in (records.redact_secrets, records.mask_prose):
                with self.subTest(raw=raw, mask=mask.__name__):
                    self.assertEqual(raw, mask(raw))

    def test_a_person_keeps_scheme_values_private_at_header_and_token_boundaries(self) -> None:
        for ending in ("", "\nnext line stays", "'", '"', "`", ", next", "; next", "}"):
            self.assert_private(f"Authorization: Basic YTpi{ending}", "YTpi")
        for scheme in ("Basic", "Token", "Negotiate", "NTLM"):
            for ending in ("", "'", '"', "`", ")", ", next", "; next", "}"):
                self.assert_private(f"{scheme} dXNlcjpwYXNz{ending}", "dXNlcjpwYXNz")
            self.assert_private(f"{scheme} MadeUpToken99 then retry", "MadeUpToken99")
        for scheme in ("Token", "Negotiate", "NTLM"):
            self.assert_private(f"Authorization: {scheme} dXNlcjpwYXNz then retry", "dXNlcjpwYXNz")

    def test_a_person_can_share_a_bare_scheme_value_inside_markup_or_a_query(self) -> None:
        value = "dXNlcjpwYXNz"  # made up: base64 of a short user:pass, letters only
        for raw in (
            f"<Authorization>Basic {value}</Authorization>",
            f"<td>Token {value}</td>",
            f"[Basic {value}]",
            f"x=Basic {value}&y=1",
        ):
            for mask in (records.redact_secrets, records.mask_prose):
                with self.subTest(raw=raw, mask=mask.__name__):
                    self.assertNotIn(value, mask(raw))

    def test_a_person_can_end_a_sentence_on_a_product_name_after_a_scheme(self) -> None:
        for mask in (records.redact_secrets, records.mask_prose):
            with self.subTest(mask=mask.__name__):
                self.assertIn("JavaScript", mask("We teach Basic JavaScript."))
