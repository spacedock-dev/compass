"""A person's authorization values never reach published or model-bound text.

Every credential below is made up for this test; no credential store is read.
"""

from __future__ import annotations

import unittest

from compass_runtime import records


class APersonSharingAuthorization(unittest.TestCase):
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
                    expected = raw.replace(value, records.SECRET_MARKER)
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
