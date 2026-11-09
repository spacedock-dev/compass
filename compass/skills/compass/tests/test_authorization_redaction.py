"""A person's authorization values never reach published or model-bound text.

Every credential below is made up for this test; no credential store is read.
"""

from __future__ import annotations

import unittest

from compass_runtime import records


class APersonSharingAuthorization(unittest.TestCase):
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
                ("Future-Scheme", "madeup"),
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
                'send Authorization: Basic "made up words" then retry',
                'send Authorization: Basic "…REDACTED" then retry',
            ),
            (
                "send Proxy-Authorization: Custom madeup then retry",
                "send Proxy-Authorization: Custom …REDACTED then retry",
            ),
            (
                "Authorization: Basic madeup\nnext line stays",
                "Authorization: Basic …REDACTED\nnext line stays",
            ),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(expected, records.redact_secrets(raw))
                self.assertNotIn("madeup", records.mask_prose(raw))
                self.assertNotIn("made up words", records.mask_prose(raw))
                self.assertIn("…REDACTED", records.mask_prose(raw))

    def test_a_person_can_share_either_langfuse_key_without_its_body(self) -> None:
        for prefix in ("sk-lf-", "pk-lf-"):
            for body in ("00000000-1111-2222-3333-444444444444", "MadeUpKey99" * 40):
                raw = f"rotate {prefix}{body} then retry"
                for mask in (records.redact_secrets, records.mask_prose):
                    with self.subTest(prefix=prefix, size=len(body), mask=mask.__name__):
                        self.assertEqual(f"rotate {prefix}…REDACTED then retry", mask(raw))

    def test_a_person_can_discuss_authentication_without_supplying_a_value(self) -> None:
        for raw in (
            "use basic auth",
            "the Authorization header",
            "Bearer tokens expire",
            "grep -n 'Authorization:' server.log",
            "grep -n 'Proxy-Authorization:' server.log",
            "Authorization: Basic",
            "Proxy-Authorization: Negotiate",
            "the prefixes sk-lf- and pk-lf- identify Langfuse keys",
            "Authorization: Basic\nnext line stays",
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
