"""Pure operations over untrusted harness records."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
import re
import shlex
import string
import unicodedata
from bisect import bisect_left, bisect_right
from datetime import UTC, datetime
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Iterable

# Private goal-source metadata; never part of the Analyze words or their cache.
GOAL_SOURCE_CUT_FIELD: Final = "goal_source_cut"
# The closed goal-source tokens an adopted goal carries; `reading` re-exports them and the page
# mirrors them (`vocabulary.json`). `typed`, the fallback, is not one of them.
PROMPT_CHOSEN: Final = "chosen-prompt"
SESSION_GOAL: Final = "session-goal"
# The harnesses whose rows publish `session_goal`: Claude Code, Codex and Antigravity record a
# `/goal` the reader set; no other harness writes one Compass reads. The page holds the same three.
SESSION_GOAL_HARNESSES: Final = ("claude", "codex", "antigravity")
PROMPT_SOURCES: Final = ("latest-prompt", "first-prompt", PROMPT_CHOSEN, SESSION_GOAL)

# C0 and DEL, the zero-width space, the two directional marks, and the bidi
# embedding and isolate ranges. Listed one by one across U+200B to U+200F rather
# than as a range, because U+200C and U+200D are inside it and must survive:
# ZWNJ is orthographic in Persian and several Indic scripts, sitting inside
# words, and ZWJ is what composes an emoji sequence. Neither can reorder text,
# so keeping them costs no protection, and stripping them would break a title in
# those scripts anywhere in the product, not only on the row that prompted this.
_UNSAFE_CHARS = re.compile("[\\x00-\\x1f\\x7f\\u200b\\u200e\\u200f\\u202a-\\u202e\\u2066-\\u2069]+")


# ---------------------------------------------------------------------------
# Credential shapes
#
# A transcript records what the operator typed, verbatim, and sometimes what they
# typed was a key. Seven distinct live Anthropic credentials sit in the local
# Claude store in ordinary prompt history, and every prompt-derived surface on
# the dashboard — the instruction line, `last_prompt`, `prompt_title`, the
# observer goal, a Codex title — publishes that text. `127.0.0.1` is not the
# exposure; a screenshot is.
#
# The list below was derived rather than guessed, the way `injected_prompt` and
# `harness_control` were, and by COUNTING rather than by reading: every
# transcript file in the local Claude and Codex store, read end to end. Each
# entry carries its occurrence count and the number of files it appears in. Of
# the genuine operator prompts in that store — the gate the instruction line
# already uses — 20 carry one of these, and those 20 are what the dashboard
# publishes today: 18 of 21,116 on Claude and 2 of 1,004 on Codex, re-measured
# 2026-08-27 with the same figure before and after this branch widened the list.
#
# `docs/design-credential-redaction.md` holds the false-positive classification,
# the corpus figures, the two thresholds they set, and every alternative
# rejected here.
#
# Redacted **in place**, keeping the words around the match, because the words
# are the instruction and the point of the line. The marker is deliberately
# visible: an operator who sees `sk-ant-…REDACTED` on their own card learns their
# prompt history holds a live key, which is how a rotation ever happens. A silent
# scrub protects the screenshot and tells them nothing.

_SECRET_MARKER: Final = "…REDACTED"  # noqa: S105 - the marker replaces a secret, it is not one
SECRET_MARKER: Final = _SECRET_MARKER

# `(name, characters of the match kept in front of the marker, anchored, pattern)`.
#
# Every body is bounded above as well as below, and the upper bound is the
# vendor's own longest issued key with headroom rather than a round number. An
# open-ended `{n,}` body is greedy across `-` and `_`, so a key glued to the
# words behind it took the words with it: 85 characters matched and 71 of them
# instruction, on a probe. A run longer than any key that format issues is not
# that format, so the cap ends the match there and the rest of the line survives.
# `docs/design-credential-redaction.md` carries the per-shape lengths.
#
# `anchored` shapes must start a token: without it `dask-<40 chars>` reads as an
# OpenAI key and `mask-ant-…` as an Anthropic one. A hyphen counts as inside a
# token, and that one decision rejects 78 of the 177 `sk-` candidates in the
# local store.
#
# It is checked in the replacer rather than written as a lookbehind on each
# alternative, and that is a measured choice, not a style one: a leading
# lookbehind leaves no literal for `re` to build its first-character skip from,
# and the substitution cost on a 140-character line goes from 21.5 us to 36.5 us.
#
# `pem` and `urlcred` are unanchored because their own first character is the
# separator: a URL credential is always preceded by a scheme, and a PEM header by
# whatever line came before it.
_SECRET_SHAPES: Final = (
    # `sk-ant-api03-`, `sk-ant-oat01-`, `sk-ant-ort01-` are the three variants in
    # the store; the shared prefix is matched rather than the three, so the
    # fourth is covered before anyone notices it exists.
    ("anthropic", 7, True, r"sk-ant-[A-Za-z0-9_-]{16,110}"),  # 89 in 35 files
    # 32, not the 20 an OpenAI key's body needs. 20 was measured and rejected:
    # it alters 25 further genuine prompts, and every one is a hyphenated
    # identifier that merely opens a token with `sk-`.
    #
    # 32 does not clear that entirely. One 42-character all-lowercase identifier
    # still matches, in two prompts. Requiring an uppercase character in the body
    # would clear it, and was rejected too: OpenRouter spells its key `sk-or-v1-`
    # plus 64 lowercase hex, so the rule that fixes two prompts loses a vendor.
    ("openai", 3, True, r"sk-[A-Za-z0-9_-]{32,180}"),  # 99 in 14 files
    # Stripe's secret and restricted keys. `pk_live_` is deliberately absent: a
    # publishable key is published on purpose.
    ("stripe", 8, True, r"(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{20,120}"),  # 74 in 19 files
    ("aws", 4, True, r"(?:AKIA|ASIA)[0-9A-Z]{16}(?![A-Za-z0-9_-])"),  # 246 in 50 files
    # The other half of the AWS pair, which the marker beside `AKIA…REDACTED`
    # used to imply was covered and was not. A bare 40-character base64 run is
    # not distinguishable from a hash, a diff or a path segment, so this one is
    # cued instead of shaped: the key name has to sit in front of it. It keeps
    # the cue and the separator rather than a fixed count of leading characters,
    # which is what `_SECRET_KEEP_TO_BODY` exists for.
    (
        "aws_secret",  # 0 values; 431 cue mentions in 202 files (2026-08-27)
        0,
        False,
        (
            r"(?:aws_secret_access_key|AWS_SECRET_ACCESS_KEY|secretAccessKey)"
            r"[\"']?\s{0,4}[:=]\s{0,4}[\"']?"
            r"[A-Za-z0-9/+=]{40}(?![A-Za-z0-9/+=])"
        ),
    ),
    ("github", 4, True, r"gh[pousr]_[A-Za-z0-9]{36,255}"),  # 57 in 17 files
    # Zero in the store, and on the list anyway: `github_pat_` is the format
    # GitHub issues today and `ghp_` above is the one it replaced. A filter that
    # covers only the legacy spelling of a token still in circulation is the
    # false confidence this whole change exists to avoid.
    ("github_fine", 11, True, r"github_pat_[A-Za-z0-9_]{40,96}"),  # 0
    ("gitlab", 6, True, r"glpat-[A-Za-z0-9_-]{20,64}"),  # 16 in 3 files
    ("npm", 4, True, r"npm_[A-Za-z0-9]{36}"),  # 12 in 4 files
    # Linear's personal API key. Found by the same sweep that found `xapp-`:
    # 25 full-length occurrences across 16 files already inside the collector's
    # own glob, none of which reached a published head, which is the state
    # `github_pat_` was in the day before one did. 67 further lines carry the
    # bare prefix with nothing of the right length behind it.
    ("linear", 8, True, r"lin_api_[A-Za-z0-9]{40,64}"),  # 25 in 16 files (2026-08-27)
    # `xapp-` is the app-level token beside the four `xox` bot and user ones. It
    # was found by sweeping past the candidate list, which is the only reason it
    # is here: nothing about `xox` would have suggested it.
    ("slack", 5, True, r"(?:xox[baprs]|xapp)-[A-Za-z0-9-]{15,96}"),  # 22 in 3 files
    ("posthog", 4, True, r"phc_[A-Za-z0-9]{32,64}"),  # 507 in 343 files
    # Zero values, and 45 mentions of the bare prefix across 22 files — a
    # guidance list naming the shape, never a key of the right length behind it.
    # Kept for the reason `github_fine` is: absence today is not a contract.
    ("google", 4, True, r"AIza[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])"),  # 0
    # Three base64url segments, not one. A lone `eyJ…` run is base64 for `{"` and
    # turns up in any pasted payload; the two dots are what make it a token.
    # 1,024 and 4,096 are a JOSE header and a claim set with room to spare; the
    # signature half of RS512 is 342 characters.
    (
        "jwt",  # 852 in 126 files
        3,
        True,
        r"eyJ[A-Za-z0-9_-]{8,1024}\.[A-Za-z0-9_-]{8,4096}\.[A-Za-z0-9_-]{8,1024}",
    ),
    # The body is swallowed with the header, because redacting the header alone
    # leaves the key on the row one line further down.
    #
    # The body is base64 runs separated by whitespace, not a class holding the
    # separator: `safe_text` substitutes a space for every line break BEFORE the
    # filter runs, so a class of `[A-Za-z0-9+/=\r\n]` could not match one
    # character of a body on the path that publishes it, and the whole key went
    # out beside the header. Allowing a bare space into the class instead was
    # what the first spelling of this rejected, because it swallows the sentence
    # after a header that names the format and carries no key — which is all
    # 1,058 of the local occurrences. The 16-character minimum per run is the
    # distinction: a PEM line is 64 characters and an English word is not.
    #
    # The separator admits a tab and runs to 40 characters, not 4. A block pasted
    # inside a fenced example or a YAML value keeps its indent after the line
    # break becomes a space, so at an indent of 4 the run chain broke after the
    # header and 6 body lines published behind the marker: 468 characters, on
    # both the `safe_text` and `redact_clip` paths. Widening the separator is
    # behaviour-neutral on the real store rather than a trade: over 1,140 PEM
    # matches in 61 files, 0 matched spans grow and 0 extra characters are
    # swallowed. The 16-character run minimum is what still does the
    # false-positive work, so the wider gap costs nothing to the sentence after a
    # header that names the format and carries no key.
    (
        "pem",  # 1,058 in 46 files, every one header-only
        11,
        False,
        (
            r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----"
            r"(?:[ \t\r\n]{0,40}[A-Za-z0-9+/=]{16,76}){0,200}"
            r"(?:[ \t\r\n]{0,40}[A-Za-z0-9+/=]{1,15}(?=[ \t\r\n]{0,40}-----END))?"
            r"(?:[ \t\r\n]{0,40}-----END[^\n]*-----)?"
        ),
    ),
    # The username goes with the password. It is not itself a secret, but half a
    # pair is still a name someone can try, and `://…REDACTED@host` keeps the
    # host, which is the part that identifies the line.
    # The username half is `*` and not `+`: `redis://:password@host` is the form
    # Redis documents, and with `+` all 24 characters of the password published
    # unmarked on all seven schemes tried.
    #
    # Two ends, not one. `(?=@)` alone means a clip that lands between the
    # password and the `@` kills the match and publishes what it cut to — 6, 11
    # and 12 password characters at three measured clip points, with no marker,
    # and 2 corpus records sit at the 80-character title cap. The `$` arm
    # catches those, and `(?![0-9]+$)` is what keeps it from eating a bare
    # `host:port` that ends the line: the dashboard's own `http://127.0.0.1:4553`
    # is the false positive that would have cost the most instruction lines here.
    (
        "urlcred",  # 1,572 in 251 files
        3,
        False,
        r"://[^\s/:@]*:(?:[^\s/@]+(?=@)|(?![0-9]+$)[^\s/@]+$)",
    ),
    # gcloud's OAuth access token, which `gcloud auth print-access-token` writes
    # alone on a line. The `c.` second segment of the newer format carries dots,
    # so the body admits them. The vendor documents no maximum: 1,024 is a bound
    # chosen to be wider than any token seen, not a measured length.
    ("gcloud", 5, True, r"ya29\.[A-Za-z0-9_.-]{20,1024}"),
    # Secrets Manager's `get-secret-value` prints the secret as one JSON string,
    # which is itself JSON, so its quotes arrive escaped: the body is a run of
    # plain characters or backslash pairs, and a cued shape stopping at the first
    # `\"` published every key after it. Name and quote stay, only the value goes.
    # A Python repr spells the value in single quotes, so either quote opens it.
    # Unbounded, because a bound is a cliff: past it the closing quote falls
    # outside the window and the whole secret was returned (4,096, then 65,536;
    # review, 2026-10-27). The run is linear: its two alternatives cannot both
    # match a character, and a match always ends at the quote, the line or the text.
    (
        "secretstring",
        0,
        False,
        (
            r"(?i:\bsecretstring)[\"']?\s*:\s*(?P<ssq>[\"'])"
            r"(?P<ssval>(?:(?!(?P=ssq))[^\\\n]|\\.)+)(?:(?P=ssq)|(?=\n)|$)"
        ),
    ),
    # A `.netrc` entry: `machine <host>` or `default`, then `login <user>` and
    # `password <value>`. The login is what separates it from prose, so a
    # `machine` or `default` followed straight by `password` is taken only when
    # the value has a digit or a capital in it ("machine learning password
    # manager" and "default password reset" are sentences). A quoted value is
    # taken whole.
    (
        "netrc",
        0,
        False,
        (
            r"(?<![\w-])(?:machine\s+\S+|default)\s+"
            r"(?:login\s+\S+\s+password\s+|password\s+(?=[\"']?\S*[0-9A-Z]))"
            r"(?P<netrcval>\"[^\"\n]{1,512}\"|'[^'\n]{1,512}'|\S{1,512})"
        ),
    ),
    # A pre-signed URL's signature is the credential: whoever holds the URL holds
    # the access until it expires. Only inside a query string (`?` or `&` in
    # front, or the HTML and JSON spellings of `&`), because `sig=` and
    # `signature=` are also ordinary code and prose. The value has to look like a
    # signature: a digit, a base64 or percent character, or both cases of letter.
    # `sig=overview` and `sig=handler_function_name` are words.
    (
        "querysig",
        0,
        False,
        (
            r"(?:(?<=[?&])|(?<=&amp;)|(?<=\\u0026))"
            r"(?i:x-amz-signature|x-amz-security-token|x-goog-signature|signature|sig)"
            # Flat lookaheads, one condition each: nesting one bounded run inside
            # another cost about 2048 * 2048 steps per `sig=`, so repeated starts
            # stalled on 10,000 characters (review, 2026-10-27). `?` ends a value, so
            # one start's scan never runs on through the next `?sig=`.
            r"=(?P<sigval>(?:(?=[^\s&#?\"'<>]{0,2048}[0-9%+/])"
            r"|(?=[^\s&#?\"'<>]{0,2048}[A-Z])(?=[^\s&#?\"'<>]{0,2048}[a-z]))"
            r"[^\s&#?\"'<>]{6,2048})"
        ),
    ),
    # A credential with no shape of its own, known only by the cue in front of
    # it: an `Authorization: Bearer` value, a `--password` flag, or a name such
    # as `password`, `DB_PASSWORD`, `PGPASSWORD`, `GITHUB_API_TOKEN` or
    # `OPENAI_API_KEY` before `=` or `:`. Added when the agent's own messages
    # began reaching a reading model (review, 2026-10-03), because an agent
    # repeats what it read. Cued like `aws_secret`, so the cue and its separator
    # stay and only the value goes, a quoted value whole. The pattern finds a
    # candidate and `_cued_value_is_secret` decides: code that names a value
    # rather than holding one (`None`, `$VAR`, `os.environ[...]`, `next_token()`)
    # is left alone, and so is prose (`bearer auth`, `secret=staging`).
    (
        "cued",
        0,
        False,
        (
            r"(?:(?P<cueauth>(?i:\bauthorization)[\"']?\s*[:=]\s*[\"']?(?i:bearer)\s+)"
            r"|(?P<cuebearer>(?i:\bbearer)\s+)"
            r"|(?P<cueflag>(?<![\w-])--(?i:password|passwd|token|secret|api-key|apikey)(?:=|\s+))"
            r"|(?P<cuename>(?<![A-Za-z0-9_])[A-Za-z0-9_]*"
            r"(?i:password|passwd|passphrase|pwd|token|secret|api_key|apikey|key))"
            r"[\"']?\s*(?P<cuesep>[=:])\s*)"
            r"(?:(?P<cueq>[\"'])(?P<cuedquoted>[^\"'\n]{1,512})(?P=cueq)"
            r"|(?P<cuedvalue>[^\s\"'`,;&)]{1,512}))"
        ),
    ),
)

_SECRET_RE: Final = re.compile(
    "|".join(f"(?P<{name}>{pattern})" for name, _, _, pattern in _SECRET_SHAPES)
)
_SECRET_KEEP: Final = {name: keep for name, keep, _, _ in _SECRET_SHAPES}
_SECRET_ANCHORED: Final = frozenset(name for name, _, anchored, _ in _SECRET_SHAPES if anchored)
_TOKEN_CHARS: Final = frozenset(string.ascii_letters + string.digits + "_-")

# A cued shape keeps everything but the last N characters of its match, because
# what names the kind is the cue in front of the value rather than a fixed count
# of leading characters. `aws_secret_access_key = …REDACTED` says which
# credential to go and rotate; `…REDACTED` alone says nothing and takes the
# words of the instruction with it.
_SECRET_KEEP_TO_BODY: Final = {"aws_secret": 40}

# The shapes whose value is a named group inside the match: the words around it
# stay and only the group becomes the marker.
_SECRET_VALUE_GROUP: Final = {"secretstring": "ssval", "netrc": "netrcval", "querysig": "sigval"}

# The longest prefix any shape keeps in front of the marker, which is what the
# bound in `redact_clip` has to be able to step over.
_SECRET_MAX_KEEP: Final = max(_SECRET_KEEP.values())

# The match length at or above which a shape needs no anchor: `name -> length`.
#
# The anchor above fails OPEN, and that is a bypass rather than a rough edge. One
# character in front of a key — `x`, a digit, `_`, `-` — and `sk-ant-api03-` plus
# a hundred characters publishes verbatim, with the length unchanged and no
# marker. Anyone who has ever pasted a key at the end of a word has published it.
#
# Dropping the anchor outright is the wrong repair: it is what rejects 78 of the
# 177 `sk-` candidates in the local store, and those are hyphenated identifiers,
# not keys. So the anchor is kept and made conditional on the one thing that
# separates the two — length. A `sk-ant-` run of 90 characters, `AKIA`/`ASIA`
# plus exactly its 16 and nothing token-shaped behind, or `github_pat_` plus its
# 40 has no plausible innocent reading whatever sits in front of it. Below the
# threshold the anchor still applies and the measured rejection is unchanged.
#
# `openai` is deliberately absent. Its 32-character body is exactly the length
# class the false positives live in, so a threshold there would trade the
# rejection this list exists to keep.
_SECRET_UNAMBIGUOUS: Final = {
    "anthropic": 90,
    "aws": 20,  # `AKIA` plus 16 is the whole shape; it has no longer form.
    "github_fine": 51,  # `github_pat_` plus its 40.
    "linear": 48,  # `lin_api_` plus its 40, which is the only length it has.
    "gcloud": 25,  # `ya29.` plus 20; no innocent text opens a token with it.
}

# The literal every shape opens with, scanned with `in` before the alternation
# runs. `str.__contains__` is a C substring search and the alternation is not,
# and nearly all published text carries none of these: on a 140-character line
# the gated path adds 1.8 us to `safe_text` where the bare substitution adds
# 21.5 us, and on a 2,000-character observer blob 28 us against 302 us
# (measured before the `cued` shape widened the hints; `safe_text` has today's).
#
# An optimization in front of a security filter is a way to ship a shape
# switched off, so `RedactSecretsTest` asserts every alternative is still
# reachable through it.
#
# The five GitHub prefixes are spelled out rather than gated on `gh`, which
# appears inside "highlight" and "tonight" and put ordinary English on the slow
# path. `://` is absent for the same reason: alone it sends every prompt that
# mentions a URL through the alternation for nothing. It is paired below with a
# colon somewhere after it — what both halves of `urlcred` need, and what an
# ordinary `https://host/path` does not have. `@` alone is not enough, because
# the `@` is exactly what a clip at the title cap removes.
_SECRET_HINTS: Final = (
    "sk-",
    "sk_",
    "rk_",
    "AKIA",
    "ASIA",
    "ghp_",
    "gho_",
    "ghu_",
    "ghs_",
    "ghr_",
    "github_pat_",
    "glpat-",
    "npm_",
    "lin_api_",
    "xox",
    "xapp-",
    "phc_",
    "AIza",
    "eyJ",
    "-----BEGIN ",
    "ya29.",
    # A pre-signed URL's signature parameter, in the spellings the vendors use.
    "sig=",
    "Sig=",
    "SIG=",
    "ignature=",
    "IGNATURE=",
    # The AWS secret key's cue, in the three spellings the vendor's own tooling
    # writes: the CLI's config file, the environment variable, and the SDKs'
    # camel case. Both cases spelled out rather than one case-insensitive scan,
    # because the gate is `str.__contains__` and lowering the string first would
    # cost more than the extra scan.
    "secret_access_key",
    "SECRET_ACCESS_KEY",
    "secretAccessKey",
    # The `cued` shape's cues, each in both cases and cut to a tail every
    # capitalisation shares (`Password` holds `assw`). `key` is the broad one:
    # it sends any line naming a key through the alternation, which is the
    # price of catching `OPENAI_API_KEY=`.
    "earer",
    "EARER",
    "assw",
    "ASSW",
    "assph",
    "ASSPH",
    "wd",
    "WD",
    "ecret",
    "ECRET",
    "oken",
    "OKEN",
    "key",
    "Key",
    "KEY",
)

# The shortest thing any hinted shape can match: `pwd=` and a three-character
# value, the `cued` shape's floor. Below it the alternation cannot succeed, so
# the hint scan is skipped as well. `urlcred` is shorter than this and is why
# the scheme test comes first.
_SECRET_MIN_CHARS: Final = 7

# Transparent HTML formatting, rather than arbitrary <user>/<password> envelopes.
# Quoted attributes may contain >; the disjoint alternatives keep the scan linear.
_INLINE_MARKUP_START_RE: Final = re.compile(
    r"</?(?:a|abbr|b|code|del|em|i|ins|kbd|mark|s|samp|small|span|strong|sub|sup|time|u|var)"
    r"(?=[\s/>])",
    re.IGNORECASE,
)
_INLINE_MARKUP_RE: Final = re.compile(
    _INLINE_MARKUP_START_RE.pattern + r"(?:[^<>\"']|\"[^\"]*\"|'[^']*')*>",
    re.IGNORECASE,
)
# A second view is bounded independently of the caller's later clipping. An
# oversized string with formatting is withheld, never returned with an unchecked tail.
INLINE_MARKUP_MAX_CHARS: Final = 16_384


# What a `cued` value is when it names a value rather than holding one: code
# that reads a credential from somewhere else, or a literal that is not one.
_CODE_VALUE_RE: Final = re.compile(
    r"^(?:none|null|nil|true|false|undefined|\$.*|self\..*|os\..*|process\.env.*"
    r"|[A-Za-z_][\w.]*\(.*)$",
    re.IGNORECASE,
)
# A value that looks like a credential rather than a word: long, or holding a
# digit or a symbol a word does not. What `bearer`, a `:` and the `secret` and
# `token` cues need, because each also opens ordinary prose and config.
_CREDENTIAL_LIKE_RE: Final = re.compile(r"^(?:\S{16,}|\S*[0-9._~+/!@#%^*&=-]\S*)$")
# The name suffixes that mask any value after `=`; `secret` and `token` need a
# credential-like value, and a bare `key` needs a name before it (`STRIPE_KEY`),
# because "the key: value" and "sort_key=name" are prose and config.
_CUE_STRICT: Final = ("secret", "token")


def _cued_value_is_secret(match: re.Match[str]) -> bool:
    """Whether a `cued` candidate holds a credential, per the rules beside the shape."""
    quoted = match.group("cuedquoted")
    value = quoted if quoted is not None else match.group("cuedvalue") or ""
    if _CODE_VALUE_RE.match(value.strip()):
        return False
    credential_like = bool(_CREDENTIAL_LIKE_RE.match(value)) and len(value) >= 3
    if match.group("cueauth") is not None or match.group("cueflag") is not None:
        return True
    if match.group("cuebearer") is not None:
        return len(value) >= 16 and credential_like
    raw_name = match.group("cuename") or ""
    name = raw_name.lower()
    # A bare `key` only as an environment-style assignment: `STRIPE_KEY=`, never `sort_key=`.
    bare_key = name.endswith("key") and not name.endswith(("api_key", "apikey"))
    if bare_key and not (raw_name.isupper() and name.endswith("_key")):
        return False
    if name.endswith("pwd") and value.startswith(("/", "~", ".")):
        # The shell's working directory, `PWD=/home/…`, not a password.
        return False
    if quoted is not None:
        return True
    if match.group("cuesep") == ":" or name.endswith(_CUE_STRICT):
        return credential_like
    return len(value) >= 3


def _mark_secret(match: re.Match[str]) -> str | None:
    """The marked replacement for a match, or None if the anchor rejects it.

    None rather than the match text, because the caller has to tell the two
    apart: a rejected span must be re-entered one character in (see
    `_redact_scan`), and `re.sub` cannot express that.
    """
    name = match.lastgroup or ""
    body = match.group()
    unambiguous = _SECRET_UNAMBIGUOUS.get(name)
    anchored = name in _SECRET_ANCHORED and (unambiguous is None or len(body) < unambiguous)
    if anchored and match.start() and match.string[match.start() - 1] in _TOKEN_CHARS:
        return None
    if name == "cued":
        if not _cued_value_is_secret(match):
            return None
        quoted = match.group("cuedquoted") is not None
        start = match.start("cuedquoted" if quoted else "cuedvalue") - match.start()
        return body[:start] + _SECRET_MARKER + (match.group("cueq") if quoted else "")
    value_group = _SECRET_VALUE_GROUP.get(name)
    if value_group is not None:
        first, last = match.span(value_group)
        return body[: first - match.start()] + _SECRET_MARKER + body[last - match.start() :]
    from_body = _SECRET_KEEP_TO_BODY.get(name)
    if from_body is not None:
        return body[:-from_body] + _SECRET_MARKER
    return body[: _SECRET_KEEP.get(name, 0)] + _SECRET_MARKER


def _redact_scan(text: str) -> str:
    """Every shape on the list marked, scanning left to right.

    Hand-rolled instead of `re.sub` for one reason: `sub` resumes at
    `match.end()`, so a span the anchor rejects is both left unmarked and
    skipped over, and a valid key that starts inside it is never looked at. That
    is not theoretical — `x` plus a near-miss `sk-ant-` run plus a correctly
    anchored key published all 142 characters, where the same key one space
    later redacted to 45. This resumes at `match.start() + 1`.
    """
    out: list[str] = []
    pos = 0
    while (match := _SECRET_RE.search(text, pos)) is not None:
        marked = _mark_secret(match)
        if marked is None:
            resume = match.start() + 1
            out.append(text[pos:resume])
            pos = resume
            continue
        out.append(text[pos : match.start()])
        out.append(marked)
        pos = match.end()
    out.append(text[pos:])
    return "".join(out)


def _redact_inline_markup(text: str) -> str:
    """Map credentials in a formatting-free view back to their original spans.

    Real spaces/newlines stay in the view. Only a credential match changes the
    source; harmless formatting is retained. The normal raw scan still follows,
    because a credential in an attribute is absent from this second view.
    """
    if "<" not in text:
        return text
    if len(text) > INLINE_MARKUP_MAX_CHARS:
        return _SECRET_MARKER if _INLINE_MARKUP_START_RE.search(text) is not None else text
    if _INLINE_MARKUP_RE.search(text) is None:
        return text
    parts: list[str] = []
    cuts: list[int] = []
    removed: list[int] = []
    cursor = length = 0
    for tag in _INLINE_MARKUP_RE.finditer(text):
        part = text[cursor : tag.start()]
        parts.append(part)
        length += len(part)
        cuts.append(length)
        removed.append(tag.end() - length)
        cursor = tag.end()
    parts.append(text[cursor:])
    plain = "".join(parts)
    if not _needs_secret_scan(plain):
        return text
    out: list[str] = []
    cursor = pos = 0
    while (match := _SECRET_RE.search(plain, pos)) is not None:
        marked = _mark_secret(match)
        if marked is None:
            pos = match.start() + 1
            continue
        start_cut = bisect_right(cuts, match.start())
        end_cut = bisect_left(cuts, match.end())
        start = match.start() + (removed[start_cut - 1] if start_cut else 0)
        end = match.end() + (removed[end_cut - 1] if end_cut else 0)
        out.extend((text[cursor:start], marked))
        cursor = end
        pos = match.end()
    out.append(text[cursor:])
    return "".join(out)


def _needs_secret_scan(text: str) -> bool:
    scheme = text.find("://")
    if scheme != -1 and ("@" in text or ":" in text[scheme + 3 :]):
        return True
    return len(text) >= _SECRET_MIN_CHARS and any(hint in text for hint in _SECRET_HINTS)


def redact_secrets(text: str) -> str:
    """Credential-shaped runs replaced by a visible marker, everything else kept.

    One filter for every published surface rather than a guard per render site,
    because a guard per render site is a list that the next surface forgets to
    join. Called from `safe_text`, which is the layer nearly every untrusted
    string passes through on its way to the DOM — the ask question and its
    options included, since the HTTP ingress bounds those through it. An answer
    needs no cover: it is an index into the options, never text (see `asks`).

    The hand-built row fields are the exception and do not reach `safe_text` at
    all; the collectors slice `title`, `last_prompt`, `state_detail` and a
    subagent name straight out of the transcript. Those are caught by
    `aggregate._redact_published_text`, which calls this directly over the
    assembled rows and owns the list of them.
    """
    # Before hints too: a formatting tag can split the hint itself (AK<em>IA).
    text = _redact_inline_markup(text)
    return _redact_scan(text) if _needs_secret_scan(text) else text


def redact_clip(text: str, limit: int) -> str:
    """Credential shapes marked, and then the result bounded — in that order.

    The order is the whole point and it is why this is a function rather than
    two lines at each call site. A key cut at a 140-character cap is still a
    hundred usable characters of key, and a shape whose tail fell off no longer
    matches, so a caller that slices first publishes exactly the values the
    filter exists to catch. Ten collectors each remembering to do it in the
    right order is the list `redact_secrets` warns about; this is the one place
    that knows.

    The bound may overrun by up to `_SECRET_MAX_KEEP + len(_SECRET_MARKER)`
    characters, and only ever to finish a marker the cut landed inside. Measured
    on `last_prompt`: a key starting at lead 124 to 131 published a marker with
    its tail cut off, and one at 132 or beyond published the kept prefix and no
    marker at all — a row ending in `sk-ant-` that reads as a truncated key
    rather than a redacted one. No key body was published at any lead, so this
    is about what the operator can believe, not about a leak. `instruction_line`
    takes the same liberty with its cap plus one and for the same reason.

    A cued shape keeps more than `_SECRET_MAX_KEEP` characters in front of its
    marker, so a cut can still land inside `aws_secret_access_key = ` and leave
    it half written. What is lost there is the key's NAME, which is a word like
    any other word the cap cuts; the value is inside the marker either way.
    """
    marked = redact_secrets(text)
    if len(marked) <= limit:
        return marked
    # A marker that begins before the cut, or one whose kept prefix does, and so
    # straddles it either way. The search runs from the earliest offset a
    # straddling marker could start at to the latest, and the first hit is the
    # one the cut is inside.
    first = max(limit - len(_SECRET_MARKER) + 1, 0)
    last = limit + _SECRET_MAX_KEEP + len(_SECRET_MARKER) - 1
    start = marked.find(_SECRET_MARKER, first, last)
    if start != -1:
        return marked[: start + len(_SECRET_MARKER)]
    return marked[:limit]


# The command-line forms `redact_secrets` cannot recognise because the value has
# no shape: a short password is just a word. Masked by FORM instead, for the
# check lines item 5 of the ruling `mask_words` cites asks for, widened on
# review (2026-09-24) to the flags below. These named forms and no others:
# SECURITY.md says so. Over-masking is the accepted direction: `-p` is also
# `mkdir -p`, and losing that word costs a reader nothing. The one shown form
# is pytest's `-p no:<plugin>` (see `_PYTEST_PLUGIN_OFF`).
_MASK_FLAGS: Final = frozenset(
    {
        "--password",
        "--token",
        "--api-key",
        "--apikey",
        "--api_key",
        "--secret",
        "--auth",
        "--secret-string",
        "--passphrase",
        "--pass",
        "--pwd",
        "--credentials",
        "_authToken",
        "_auth",
        "_password",
        "--_authToken",
        "--_auth",
        "--_password",
        "-p",
        "-P",
    }
)
# openssl's `-passin pass:value`, read on a command line only: `pass:` opens a sentence word
# more often than a credential in prose. `env:` and `file:` sources name no value.
_NPM_SECRET_KEY_ENDS: Final = (":_authToken", ":_auth", ":_password")
_MASK_PASS_PREFIX: Final = (re.compile(r"^(['\"]?pass:).+$", re.DOTALL),)
# The two header names the ruling named. They mask as a bare word anywhere, which
# is what the check line has always done, and they are the only ones the prose
# path reads: a sentence that says "the Set-Cookie: header" or "password:" is not
# carrying a credential.
_MASK_HEADER_NARROW: Final = r"(?:authorization|x-api-key)"
# The wider set: the cookie and the vendor spellings a request carries
# (`DD-API-KEY`, `X-Vault-Token`, `Private-Token`, `Ocp-Apim-Subscription-Key`).
# Read only where a header is expected, after `-H`, `--header` or `extraheader=`,
# because `Cookie:` and `password:` are also ordinary words in a command or a
# sentence (`grep -n 'Authorization:' server.log` names no value).
_MASK_HEADER_WIDE: Final = (
    r"(?:authorization|proxy-authorization|cookie|set-cookie"
    r"|[\w-]*(?:token|key|secret|password|passwd|credential))"
)
_MASK_HEADER_OPENERS: Final = r"(?:--header=|--proxy-header=|-H)"
_MASK_HEADER_FLAGS: Final = frozenset({"-H", "--header", "--proxy-header"})
_MASK_WORD_FORMS: Final = (
    # `--password=value` and the other named flags, `=` joined.
    re.compile(
        r"^(['\"]?--(?:password|token|api[-_]?key|apikey|secret|auth|secret-string|passphrase"
        r"|pass|pwd|credentials)=).+$",
        re.DOTALL,
    ),
    # `--from-literal=key=value`: kubectl's pair, the key stays.
    re.compile(r"^(['\"]?--from-literal=[^=]*=).+$", re.DOTALL),
    # npm's `//registry/:_authToken=value`, `:_auth=` and `:_password=`, the bare `_auth=value`
    # and the flag spelling `--_auth=value`.
    re.compile(r"^(['\"]?[^\s=]*_(?:authToken|auth|password)=).+$", re.DOTALL),
    # `-pvalue` and `-Pvalue`.
    re.compile(r"^(['\"]?-[pP]).+$", re.DOTALL),
    # `NAME=value`: `PGPASSWORD=...`, `--env TOKEN=...`.
    re.compile(r"^(['\"]?[A-Za-z_][A-Za-z0-9_]*=).+$", re.DOTALL),
    # `Authorization: ...` and `X-Api-Key: ...` header values.
    re.compile(rf"^(['\"]?{_MASK_HEADER_NARROW}\s*:\s*).+$", re.IGNORECASE | re.DOTALL),
    # `--cookie=value`, joined.
    re.compile(r"^(['\"]?--cookie=).+$", re.DOTALL),
)
# The forms read only where a header is expected: the word after a header flag,
# a header flag with its value joined (`--header='Cookie: a=b'`, `-H'X-Token: v'`),
# and a git `extraheader` config key in any dotted spelling.
_MASK_HEADER_VALUE_FORMS: Final = (
    re.compile(rf"^(['\"]?{_MASK_HEADER_WIDE}\s*:\s*).+$", re.IGNORECASE | re.DOTALL),
    re.compile(
        rf"^({_MASK_HEADER_OPENERS}['\"]?{_MASK_HEADER_WIDE}\s*:\s*).+$", re.IGNORECASE | re.DOTALL
    ),
    re.compile(
        rf"^(['\"]?[^\s=]*extraheader=['\"]?{_MASK_HEADER_WIDE}\s*:\s*).+$",
        re.IGNORECASE | re.DOTALL,
    ),
)
# A header name that ends its word, with the value in the words after it, as an
# unquoted `-H Authorization: Bearer ...` or a split `extraheader=AUTHORIZATION:`
# leaves it.
_MASK_HEADER_ALONE: Final = re.compile(
    rf"^['\"]?(?:{_MASK_HEADER_OPENERS}['\"]?|[^\s=]*extraheader=['\"]?)?{_MASK_HEADER_WIDE}\s*:$",
    re.IGNORECASE,
)
# Segments exclude `.` so a run of dots cannot split many ways (exponential
# backtracking on `Loading.....`). A dotted config key (`http.extraheader=`,
# `credential.helper=`) whose last component names a credential. It starts with a
# letter, so `--max-tokens=4096`, `--password-file=/x` and `--secrets-dir=...` are
# flags and not keys. A `-D` or `--` prefix is allowed because the key must hold
# a dot: `-Dspring.datasource.password=` and `--spring.datasource.password=` are
# JVM and Spring properties, and no dot-free flag reaches this pattern.
_MASK_DOTTED_KEY: Final = re.compile(
    r"^(['\"]?(?:-D|--)?[A-Za-z][\w-]*(?:\.[^\s=.]+)+=).+$", re.DOTALL
)
_MASK_DOTTED_CREDENTIAL: Final = re.compile(
    r"(?:extraheader|password|passwd|token|secret|apikey|api-key)$", re.IGNORECASE
)
# `user:password@host`, scheme optional, the password running to the LAST `@`
# in the word so one holding `/`, `@` or whitespace is masked whole: a quoted
# password with a space in it stopped `\S*` short of the `@` (DRC-4703).
# The lookbehind starts a try only at the head of a run of user characters: without it every
# offset of a long word rescanned the rest of the run, measured at 0.4 s for an 8,000-character
# word and quadratic beyond that.
_MASK_USERINFO: Final = re.compile(
    r"((?<![^\s:/@'\"])(?:[A-Za-z][A-Za-z0-9+.-]*://)?[^\s:/@'\"]+:).*@", re.DOTALL
)

# `user:password` flags, owned by the HTTP clients that take them. `-u` is also
# `git push -u origin` and `docker run -u 1000:1000`, which name no credential,
# so the flag is a password only for the program that owns it.
_MASK_HTTP_PROGRAMS: Final = frozenset({"curl", "wget", "http", "https", "xh"})
_MASK_USER_FLAGS: Final = frozenset({"-u", "--user", "--proxy-user"})
_MASK_HTTPIE_PROGRAMS: Final = frozenset({"http", "https", "xh"})
# curl takes `-u` inside a cluster of short flags (`-sSu`, `-fsSLu`).
_MASK_CURL_USER_CLUSTER: Final = re.compile(r"^-[A-Za-z]*u$")
_MASK_COOKIE_FLAGS: Final = frozenset({"--cookie"})
# Joined spellings of the same flags, for the HTTP clients only.
_MASK_HTTP_WORD_FORMS: Final = (
    # `--user=name:value`; the user name stays.
    re.compile(r"^(['\"]?--(?:user|proxy-user)=[^:]*:).+$", re.DOTALL),
    # `-ualice:value`, curl's joined form.
    re.compile(r"^(-u[^\s:]+:).+$", re.DOTALL),
)
# Flags that are a password only for the command that owns them: `redis-cli -a`
# is a password and `ls -a` is not.
_MASK_LDAP_PROGRAMS: Final = (
    "ldapsearch", "ldapmodify", "ldapadd", "ldapdelete", "ldapwhoami", "ldapcompare",
    "ldapmodrdn", "ldappasswd",
)  # fmt: skip
_MASK_COMMAND_FLAGS: Final = {
    "redis-cli": frozenset({"-a", "--pass"}),
    "ssh-keygen": frozenset({"-N"}),
    **{name: frozenset({"-w"}) for name in _MASK_LDAP_PROGRAMS},
}
_MASK_COMMAND_WORD_FORMS: Final = {
    "redis-cli": (re.compile(r"^(-a).+$", re.DOTALL), re.compile(r"^(--pass=).+$", re.DOTALL)),
    "ssh-keygen": (re.compile(r"^(-N).+$", re.DOTALL),),
    **{name: (re.compile(r"^(-w).+$", re.DOTALL),) for name in _MASK_LDAP_PROGRAMS},
}
# `gh secret set NAME --body VALUE`: the body is a secret only under `gh secret`, since
# `gh pr create --body` is a sentence a reader wants to see.
_MASK_GH_SECRET_FLAGS: Final = frozenset({"--body", "-b"})
_MASK_GH_SECRET_FORM: Final = re.compile(r"^(--body=|-b=?).+$", re.DOTALL)
# `aws ssm put-parameter --value V`: `--value` is a secret only under that subcommand, since
# `aws cloudwatch put-metric-data --value 1` is a number a reader wants to see.
_MASK_AWS_VALUE_FLAGS: Final = frozenset({"--value"})
_MASK_AWS_VALUE_FORM: Final = re.compile(r"^(--value=).+$", re.DOTALL)
# The openssl flags that take a `pass:value` source.
_MASK_PASS_FLAGS: Final = frozenset({"-pass", "-passin", "-passout"})
# The flags that take a pair, `--from-literal key=value`: the key stays and the value goes.
_MASK_PAIR_FLAGS: Final = frozenset({"--from-literal"})
_MASK_AUTH_WORDS: Final = frozenset({"bearer", "basic", "token", "digest", "negotiate"})
# The words a command may open with before the program itself, each with the
# flags that take a value of their own (`sudo -u bob`, `env -u NAME`).
_MASK_WRAPPERS: Final = {
    "sudo": {"-u": 1, "-g": 1, "-h": 1, "-p": 1, "-C": 1, "-D": 1, "-R": 1, "-T": 1, "-U": 1},
    "env": {"-u": 1, "-S": 1, "-C": 1, "-P": 1},
    "command": {},
    "time": {"-f": 1, "-o": 1},
    "exec": {},
    "nohup": {},
    "rtk": {},
}
# `uv run`, `pnpm exec` and the like: the program follows the second word.
_MASK_RUNNERS: Final = {
    "uv": "run",
    "uvx": "",
    "npx": "",
    "bunx": "",
    "pipx": "run",
    "pnpm": "exec",
    "npm": "exec",
    "poetry": "run",
}
# A container runner takes a target before the program, with flags of its own.
# The program is the first word that is one this module knows.
_MASK_CONTAINER_RUNNERS: Final = frozenset({"docker", "podman", "kubectl", "nerdctl"})
_MASK_KNOWN_PROGRAMS: Final = (
    _MASK_HTTP_PROGRAMS | frozenset({"redis-cli", "vault", "aws", "cargo"}) | _MASK_HTTPIE_PROGRAMS
)
# The flags of the two positional-credential programs that take a value, so the
# value is not read as the name or the token.
_MASK_ARG_FLAGS: Final = {
    "vault": frozenset(
        {"-address", "-namespace", "-method", "-path", "-format", "-ca-cert", "-ca-path", "-mount"}
    ),
    "aws": frozenset(
        {
            "--profile",
            "--region",
            "--endpoint-url",
            "--output",
            "--query",
            "--ca-bundle",
            "--color",
            "--cli-read-timeout",
            "--cli-connect-timeout",
            "--cli-binary-format",
        }
    ),
    "cargo": frozenset(
        {"--registry", "--color", "--config", "--manifest-path", "--message-format"}
    ),
}
_MASK_CONFIG_SECRET: Final = re.compile(r"secret|token|password|passwd|key", re.IGNORECASE)


# Commands whose own exit status is always 0, or whose result is not the command's own: a pass of
# one proves nothing. `export`, `unset` and `set` only change the shell, `eval` runs text this
# reading cannot see, and `tee` exits 0 whatever the program feeding it did.
ALWAYS_ZERO_WORDS: Final = frozenset(
    {"true", ":", "printf", "echo", "export", "unset", "set", "eval", "tee"}
)
LAUNCH_WRAPPERS: Final = frozenset({"command", "builtin", "nohup", "exec", "time"})
_DIGITS: Final = re.compile(r"[0-9]+")


def launched_words(words: list[str]) -> list[str]:
    """The words of the program a segment launches: past `command`, `nohup`, `time` and their
    `-p`, with a path (`/bin/true`) reduced to its program name."""
    at = 0
    while at < len(words) and os.path.basename(words[at]) in LAUNCH_WRAPPERS:
        at += 1
        while at < len(words) and words[at] == "-p":
            at += 1
    rest = words[at:]
    return [os.path.basename(rest[0]) or rest[0], *rest[1:]] if rest else rest


def always_zero(words: list[str]) -> bool:
    """Whether a segment's exit status is 0 whatever it does, by any spelling of it."""
    rest = launched_words(words)
    if not rest:
        return False
    if rest[0] in ALWAYS_ZERO_WORDS:
        return True
    return rest[0] in {"exit", "return"} and (
        len(rest) == 1 or (_DIGITS.fullmatch(rest[1]) is not None and not rest[1].strip("0"))
    )


def _program(words: list[str]) -> int:
    """The index of the program a segment runs, past assignments and wrappers.

    The hook this owner runs rewrites ordinary commands to `rtk <cmd>`, so the
    recorded command carries the prefix; `uv run`, `pnpm exec` and a container's
    `exec` are looked through the same way, and `sudo -u bob` skips the user name.
    """
    index, count = 0, len(words)
    while index < count:
        word = words[index]
        base = os.path.basename(word)
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", word):
            index += 1
        elif base in _MASK_WRAPPERS:
            arity = _MASK_WRAPPERS[base]
            index += 1
            if base == "rtk" and index < count and words[index] in ("proxy", "bypass"):
                index += 1
            while index < count and words[index].startswith("-"):
                index += 1 + arity.get(words[index], 0)
        elif base in _MASK_RUNNERS:
            index += 1
            subword = _MASK_RUNNERS[base]
            if subword and index < count and words[index] == subword:
                index += 1
            while index < count and words[index].startswith("-"):
                index += 1
        elif base in _MASK_CONTAINER_RUNNERS:
            for inner in range(index + 1, count):
                if os.path.basename(words[inner]) in _MASK_KNOWN_PROGRAMS:
                    return inner
            return index
        else:
            return index
    return count


# Programs that run a script handed to them on the command line, with the flag that carries it.
# The script is code the reader wrote or the model did, and a literal credential inside it has no
# shape a mask could find, so a line that lists the command shows it as one opaque word.
_INLINE_SCRIPT_FLAG: Final = {
    "python": re.compile(r"^-[A-Za-z]*c$"),
    "node": re.compile(r"^(?:-[ep]|--eval|--print|-pe)$"),
    "ruby": re.compile(r"^-[A-Za-z0-9]*e$"),
    "perl": re.compile(r"^-[A-Za-z0-9]*[eE]$"),
    "bun": re.compile(r"^(?:-[ep]|--eval|--print)$"),
    "php": re.compile(r"^-r$"),
    "deno": re.compile(r"^$"),
}
# `python -c"..."`, `node --eval=...`: the script joined to its flag.
_INLINE_SCRIPT_JOINED: Final = {
    "python": re.compile(r"^(-c).+$", re.DOTALL),
    "node": re.compile(r"^(--eval=|--print=).+$", re.DOTALL),
    "ruby": re.compile(r"^(-e).+$", re.DOTALL),
    "perl": re.compile(r"^(-[eE]).+$", re.DOTALL),
    "bun": re.compile(r"^(--eval=|--print=).+$", re.DOTALL),
    "php": re.compile(r"^(-r).+$", re.DOTALL),
    "deno": re.compile(r"^$"),
}
# Flags that take a word of their own, so it is not read as the script file. One table per
# interpreter, because `-I` and `-i` take no value in python, node or perl and one shared set let
# them swallow the `-c` after them and print the script whole. An unknown flag takes no value, so
# the word after it is met next; a word counts as the script file only when it looks like one
# (`_looks_like_script_file`), and anything else keeps the scan going toward the script flag.
_INLINE_VALUE_FLAGS: Final = {
    "python": frozenset({"-W", "-X"}),
    "node": frozenset(
        {"-r", "--require", "--import", "--loader", "--experimental-loader", "--env-file",
         "--max-old-space-size", "--conditions", "-C", "--stack-size"}
    ),
    "ruby": frozenset({"-r", "-I", "-C"}),
    "perl": frozenset({"-I", "-M", "-m"}),
    "bun": frozenset({"-r", "--preload", "--import", "--env-file", "--cwd", "-c", "--config"}),
    "php": frozenset({"-c", "-d", "-z"}),
    "deno": frozenset({"--ext", "--env", "--env-file", "--import-map", "--config", "-c"}),
}  # fmt: skip
_INLINE_PROGRAMS: Final = re.compile(
    r"^(?:(?P<python>(?:python|pypy)(?:\d+(?:\.\d+)?)?)|(?P<node>node|nodejs)|(?P<ruby>ruby)"
    r"|(?P<perl>perl)|(?P<bun>bun)|(?P<php>php\d*(?:\.\d+)?)|(?P<deno>deno))$"
)


_SCRIPT_FILE: Final = re.compile(r"[/\\]|\.(?:py|pyw|js|mjs|cjs|rb|pl|pm|ts)$")


def _looks_like_script_file(word: str) -> bool:
    return _SCRIPT_FILE.search(word) is not None


def _inline_start(words: list[str]) -> tuple[int, str]:
    """The first word that names a script interpreter, with its kind, or (-1, "").

    Scanned rather than read from `_program`, so `docker exec c python3 -c ...`, `timeout 10
    python3 ...` and `uv run --python 3.12 python -c ...` are found behind their wrappers. A
    word that only looks like one (`echo python`) hides a following flag's value on a tier 3
    line, which is the safe side to err on.
    """
    for at, word in enumerate(words):
        match = _INLINE_PROGRAMS.match(os.path.basename(word))
        if match is not None:
            return at, match.lastgroup or ""
    return -1, ""


def inline_script_words(words: list[str]) -> dict[int, str]:
    """The words that are a script given on the command line, by index, each with the text
    of its own flag that stays visible (`-c`, `--eval=`, or empty for a separate word).

    Read only before the script file or `-m` module, so `python -m pytest -c conf.ini` and
    `node deploy.js -e prod` name a script's own flags and are left alone.
    """
    start, kind = _inline_start(words)
    if not kind:
        return {}
    value_flags = _INLINE_VALUE_FLAGS[kind]
    if kind == "deno":
        return _deno_eval_script(words, start, value_flags)
    found: dict[int, str] = {}
    index = start + 1
    while index < len(words):
        word = words[index]
        if word == "--" or (kind == "python" and word == "-m"):
            break
        if not word.startswith("-"):
            # A path-like word right after an unlisted flag is taken as that flag's value
            # (`node --diagnostic-dir /tmp/x -e ...`), because ending the scan there printed the
            # script whole. The cost is a script's own flag value hidden on a tier 3 line
            # (`node --strict deploy.js -e prod`), which is the safe side.
            if _looks_like_script_file(word) and not words[index - 1].startswith("-"):
                break
            index += 1
            continue
        if _INLINE_SCRIPT_FLAG[kind].match(word):
            if index + 1 < len(words):
                found[index + 1] = ""
            index += 2
            continue
        joined = _INLINE_SCRIPT_JOINED[kind].match(word)
        if joined is not None:
            found[index] = joined.group(1)
        index += 2 if word in value_flags else 1
    return found


def _deno_eval_script(words: list[str], start: int, value_flags: frozenset[str]) -> dict[int, str]:
    """`deno eval [flags] SCRIPT`: every plain word after the subcommand and the listed flags'
    values. An unlisted flag's value looks like the script, and the script follows it, so
    naming only the first plain word printed the real script."""
    if words[start + 1 : start + 2] != ["eval"]:
        return {}
    found: dict[int, str] = {}
    index = start + 2
    while index < len(words):
        word = words[index]
        if not word.startswith("-"):
            found[index] = ""
        index += 2 if word in value_flags else 1
    return found


def _plain_words(words: list[str], at: int, program: str, *, skip_assignments: bool) -> list[int]:
    """The indexes of the words after `at` that are neither a flag nor a flag's value."""
    arg_flags = _MASK_ARG_FLAGS.get(program, frozenset())
    found: list[int] = []
    index = at + 1
    while index < len(words):
        word = words[index]
        if word.startswith("-"):
            index += 2 if word in arg_flags else 1
            continue
        if not (skip_assignments and "=" in word):
            found.append(index)
        index += 1
    return found


def _positional_credential(words: list[str], start: int, program: str) -> int:
    """The index of a credential a program takes by position, or -1.

    `vault login <token>` and `aws configure set <name> <value>`, read past the
    flags that take a value of their own, so `--profile p` is not the name.
    """
    plain = _plain_words(words, start, program, skip_assignments=program != "aws")
    if program == "vault" and plain[:1] and words[plain[0]] == "login":
        return plain[1] if len(plain) > 1 else -1
    if program == "cargo" and plain[:1] and words[plain[0]] == "login":
        return plain[1] if len(plain) > 1 else -1
    if program == "aws" and [words[i] for i in plain[:2]] == ["configure", "set"]:
        # plain[2] is the name and plain[3] its value.
        name = words[plain[2]] if len(plain) > 2 else ""
        if name and _MASK_CONFIG_SECRET.search(name) and len(plain) > 3:
            return plain[3]
    return -1


# `pytest -p no:cacheprovider` names a plugin to disable; nothing else after
# `-p` is shown, since `-p hunter2` reads the same as `-p myplugin`.
_PYTEST_PLUGIN_OFF: Final = re.compile(r"no:[A-Za-z_][A-Za-z0-9_.]*")


def mask_words(  # noqa: PLR0915 - one branch per masked form, read in one pass
    words: list[str], *, prose: bool = False, pytest: bool = False
) -> list[str]:
    """Each word of a command with every value a named form carries replaced.

    Per word, before the words are joined and re-quoted, so a quoted value with
    whitespace in it is masked whole (review, 2026-09-24). A named flag masks
    the word after it, except that a pytest runner's `-p no:<name>` is shown.
    `prose` reads a person's sentence rather than a command: the forms that need
    a command around them (a header after `-H`, an HTTP client's `-u`) are left
    out, so ordinary words are not taken for values.
    [DEC-23](docs/design-reading-a-session.md#dec-23-a-claude-code-sessions-record-of-its-checks-may-show-the-work)
    """
    start = _program(words)
    program = os.path.basename(words[start]) if start < len(words) else ""
    flags = _MASK_FLAGS | _MASK_COMMAND_FLAGS.get(program, frozenset())
    http = program in _MASK_HTTP_PROGRAMS
    user_flags = _MASK_USER_FLAGS | {"-a"} if program in _MASK_HTTPIE_PROGRAMS else _MASK_USER_FLAGS
    word_forms = _MASK_WORD_FORMS + (_MASK_HTTP_WORD_FORMS if http else ())
    word_forms += _MASK_COMMAND_WORD_FORMS.get(program, ())
    if not prose and (program == "openssl" or _MASK_PASS_FLAGS.intersection(words)):
        word_forms += _MASK_PASS_PREFIX
    if program == "gh" and "secret" in words[start + 1 :]:
        flags |= _MASK_GH_SECRET_FLAGS
        word_forms += (_MASK_GH_SECRET_FORM,)
    if program == "aws":
        subcommand = [words[i] for i in _plain_words(words, start, program, skip_assignments=False)]
        if subcommand[:2] == ["ssm", "put-parameter"]:
            flags |= _MASK_AWS_VALUE_FLAGS
            word_forms += (_MASK_AWS_VALUE_FORM,)
    positional = _positional_credential(words, start, program)
    masked: list[str] = []
    mask_next = user_next = header_owed = scheme_next = plugin_flag = pair_next = False
    for index, word in enumerate(words):
        header_here = not prose and index > 0 and words[index - 1] in _MASK_HEADER_FLAGS
        if header_owed:
            if scheme_next and word.lower() in _MASK_AUTH_WORDS:
                masked.append(word)
                scheme_next = False
                continue
            masked.append(_SECRET_MARKER)
            header_owed = scheme_next = False
            continue
        if mask_next:
            shown = plugin_flag and _PYTEST_PLUGIN_OFF.fullmatch(word)
            masked.append(word if shown else _SECRET_MARKER)
            mask_next = False
            continue
        if pair_next:
            pair_next = False
            key, equals, _value = word.partition("=")
            masked.append(key + equals + _SECRET_MARKER if equals else _SECRET_MARKER)
            continue
        if user_next:
            user_next = False
            user, colon, _rest = word.partition(":")
            if colon:
                masked.append(user + colon + _SECRET_MARKER)
                continue
        if index == positional:
            masked.append(_SECRET_MARKER)
            continue
        if word in _MASK_PAIR_FLAGS:
            masked.append(word)
            pair_next = True
            continue
        if word in flags or word in _MASK_COOKIE_FLAGS or word.endswith(_NPM_SECRET_KEY_ENDS):
            masked.append(word)
            mask_next = True
            plugin_flag = pytest and word == "-p"
            continue
        if pytest and word.startswith("-p") and _PYTEST_PLUGIN_OFF.fullmatch(word[2:]):
            masked.append(word)
            continue
        if http and (
            word in user_flags or (program == "curl" and _MASK_CURL_USER_CLUSTER.match(word))
        ):
            masked.append(word)
            user_next = True
            continue
        if not prose and _MASK_HEADER_ALONE.match(word) and _is_header_word(word, header_here):
            masked.append(word)
            header_owed = scheme_next = True
            continue
        masked.append(_mask_one_word(word, word_forms, header_here=header_here, prose=prose))
    return masked


def _is_header_word(word: str, header_here: bool) -> bool:
    """Whether a word sits where a header is expected: after a header flag, joined
    to one, or carried by an `extraheader` key."""
    return (
        header_here
        or word.startswith(("--header=", "--proxy-header=", "-H"))
        or "extraheader=" in word
    )


def _mask_one_word(
    word: str, word_forms: tuple[re.Pattern[str], ...], *, header_here: bool, prose: bool
) -> str:
    """One word with the first named form it matches masked, and a userinfo password."""
    formed = word
    if not prose and _is_header_word(word, header_here):
        match = next((m for p in _MASK_HEADER_VALUE_FORMS if (m := p.match(word))), None)
        if match is not None:
            return match.group(1) + _SECRET_MARKER
    match = next((m for p in word_forms if (m := p.match(word))), None)
    if match is not None:
        formed = match.group(1) + _SECRET_MARKER
    else:
        dotted = _MASK_DOTTED_KEY.match(word)
        if dotted is not None and _MASK_DOTTED_CREDENTIAL.search(dotted.group(1).rstrip("=")):
            formed = dotted.group(1) + _SECRET_MARKER
    return _mask_userinfo(formed)


def _mask_userinfo(word: str) -> str:
    """`user:password@host` with the password masked, in time linear in the word.

    Only the text up to the last `@` can hold a password, and a match inside it always reaches
    that `@`, so the search never rescans the rest of the word once per colon.
    """
    last = word.rfind("@")
    if last < 0:
        return word
    head = _MASK_USERINFO.sub(lambda m: m.group(1) + _SECRET_MARKER + "@", word[: last + 1])
    return head + word[last + 1 :]


# A header name standing as its own word in prose, with the value in the words
# after it, and the schemes whose next word is the credential itself.
_MASK_HEADER_WORD: Final = re.compile(
    r"^['\"]?(?:authorization|x-api-key)\s*:(.*)$", re.IGNORECASE | re.DOTALL
)
_MASK_AUTH_SCHEMES: Final = frozenset({"bearer", "basic", "token", "digest", "negotiate"})
# `'user:password with spaces@host'`, quoted in prose, where whitespace splits
# the word `_MASK_USERINFO` would otherwise see whole.
_MASK_QUOTED_USERINFO: Final = re.compile(r"(['\"])([^\s:/@'\"]+:)[^'\"]*@")


# Zero-width space, word joiner, invisible operators, BOM, soft hyphen and
# the Mongolian vowel separator: invisible, and none of them spells a word.
_MASK_INVISIBLE: Final = frozenset("\u200b\u2060\u2061\u2062\u2063\u2064\ufeff\u00ad\u180e")
# The control characters `str.splitlines` breaks on, so a key split by any of
# them is still joined and masked.
_LINE_BREAKS: Final = frozenset("\n\r\x0b\x0c\x1c\x1d\x1e\x85")


def mask_prose(text: str) -> str:
    """A person's message with every value `mask_words` names masked, as one line.

    For a later direction's whole text (DRC-4682), which reaches further than
    any published summary: prose splits on whitespace where a check line is
    lexed, so three forms need a word more than `mask_words` reads. A header
    name standing alone masks the word after it, and the one after that when
    it is an auth scheme; a quoted `user:password@host` is masked across its
    spaces; and a credential shape wrapped by a line break is masked on both
    sides of the break, because joining the lines is what would publish its
    tail. Over-masking is the accepted direction, as for `_MASK_FLAGS`.
    """
    # Invisible characters first: a zero-width space after a flag hid it from
    # the match while the page, which strips it, showed the flag bare. Only
    # the ones that can hide a flag or split a key go; the joiners U+200C and
    # U+200D stay, because they spell Persian, Urdu and Kurdish words and join
    # emoji. Other controls become spaces, and every line break stays one.
    text = "".join(
        ""
        if ch in _MASK_INVISIBLE
        else " "
        if unicodedata.category(ch) == "Cc" and ch not in _LINE_BREAKS
        else ch
        for ch in text
    )
    text = redact_secrets(text)
    text = _MASK_QUOTED_USERINFO.sub(lambda m: m.group(1) + m.group(2) + _SECRET_MARKER + "@", text)
    lines = [line.split() for line in text.splitlines()]
    # Over the lines with words, so a blank line between the halves is no gap.
    for above, below in itertools.pairwise([line for line in lines if line]):
        if above and below and redact_secrets(above[-1] + below[0]) != above[-1] + below[0]:
            above[-1] = below[0] = _SECRET_MARKER
    words: list[str] = []
    header = scheme_next = False
    for word in (word for line in lines for word in line):
        if header and scheme_next and word.strip("'\"").lower() in _MASK_AUTH_SCHEMES:
            words.append(word)
            scheme_next = False
            continue
        words.append(_SECRET_MARKER if header else word)
        named = None if header else _MASK_HEADER_WORD.match(word)
        # `Authorization:` alone owes the next word, or two when the next is
        # a scheme; `authorization:Bearer` owes the one after it.
        header = named is not None
        scheme_next = named is not None and not named.group(1)
        if (
            named is not None
            and named.group(1)
            and (named.group(1).strip("'\"").lower() not in _MASK_AUTH_SCHEMES)
        ):
            header = False
    return " ".join(mask_words(words, prose=True))


def masked_values(words: list[str]) -> list[str]:
    """The raw text `mask_words` replaced in each word, so a caller can remove
    the same values from output that echoes the command.

    A `NAME=secret` value (a cookie, `session=abc`) also reports the part after
    each `=`, because an agent quotes the bare secret and not the pair.
    """
    found = []
    for word, masked in zip(words, mask_words(words), strict=True):
        if word == masked:
            continue
        start = len(os.path.commonprefix([word, masked]))
        rest, masked_rest = word[start:], masked[start:]
        if masked_rest.endswith(SECRET_MARKER):
            end = 0
        else:
            end = len(os.path.commonprefix([rest[::-1], masked_rest[::-1]]))
        found.append(rest[: len(rest) - end])
    values = [value for value in found if value]
    for value in list(values):
        for chunk in value.split(";"):
            name, equals, bare = chunk.strip().partition("=")
            if equals and re.fullmatch(r"[\w.-]+", name) and bare.strip("="):
                values.append(bare.strip())
    return values


def safe_text(value: Any, limit: int) -> str:
    """Untrusted text, safe to put on a row: no control characters, no
    credentials, bounded.

    The bidi and isolate ranges are stripped alongside the C0 set, and not for
    tidiness: those characters reorder how the text after them renders, so a
    harness record could make a row read as something it does not say. Legitimate
    right-to-left text does not need them, since bidi resolves implicitly.

    Redaction runs **before** the bound, and `redact_clip` is where that order
    lives. A key cut at the cap is still a hundred usable characters of key, and
    a shape whose tail fell off no longer matches, so bounding first would
    publish exactly the values this is here to catch.

    A control character struck through the middle of a key defeats the match on
    the whole key in either order, and the match is not all that is at stake.
    The substitution above turns that character into a space, so the head in
    front of it still matches on its own and redacts, while the TAIL behind it
    is a run with no prefix to match on and publishes beside the marker: 75
    characters of key on a probe that put the separator 40 characters in. That
    is a limit of shape matching rather than of the ordering, and `SECURITY.md`
    carries it with the rest of the residual.

    This is a hot path — a tool name, a model id and a title each pass through it
    on every collect — so the redaction is gated. Re-measured 2026-10-03, after
    the `cued` shape added its hints and dropped `_SECRET_MIN_CHARS` to 7, on
    one laptop with `timeit`: 0.49 us on a four-character tool name, 4.7 us on
    a 140-character prompt line, 48 us on a 140-character line naming a key or
    a token (the broad hints send it through the alternation), 68 us on a
    2,000-character observer blob. `_SECRET_HINTS` carries what the gate buys
    and why, and `docs/design-credential-redaction.md` has the inputs before
    the filter existed. End to end a whole collect measured 30.5 ms on
    `bench_collect --simulate balanced-five` the same day; the figures before
    the cued shape were taken on another day and are not compared with it.
    """
    text = str(value or "").encode("utf-8", "replace").decode("utf-8")
    text = _UNSAFE_CHARS.sub(" ", text)
    return redact_clip(text, limit)


def iso_epoch(value: Any) -> float | None:
    """One ISO-8601 string as epoch seconds, or nothing. **The repo-wide rule.**

    Every ISO timestamp Compass reads comes from outside it — a transcript, a
    SQLite column, a vendor's usage endpoint, a hook payload — and the one thing
    they do not agree on is whether the offset is there at all. So the rule is
    stated once, here, and the parsers that need it call this rather than
    `fromisoformat().timestamp()`:

    **An offset-less stamp is UTC.**

    That is a decision about which wrong answer is survivable, and it was made
    against measurement rather than taste (2026-08-06). Every source checked on a
    live machine sends an explicit offset, and every one of them sends `+00:00`:
    Claude and Pi transcript records, Copilot's `assistant_usage_events.created_at`,
    and all four `resets_at` fields on Anthropic's usage endpoint. So a naive stamp
    from any of them would be one of those same UTC values with the suffix dropped,
    and reading it as UTC recovers the right instant.

    `.timestamp()` on a naive datetime does the opposite: it reads the value as
    *server-local*. In UTC+8 that is an eight-hour error in the direction that
    matters most, making a stamp look older than it is — old enough to fall out of
    an activity window and hide a live session, which is the failure this codebase
    treats as the worst kind.

    Display is unaffected and stays local: `sessions.format_reset` and
    `lifecycle` both `.astimezone()` an epoch value for rendering. This function is
    about reading an instant, not about showing one.

    `Z` is normalized because `fromisoformat` rejected it before Python 3.11 and
    the floor is 3.11; keeping the substitution costs nothing and documents the
    spelling vendors actually send.
    """
    if not isinstance(value, str):
        return None
    text = value.replace("Z", "+00:00") if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def parse_ts(ts: Any) -> float | None:
    """One ISO-8601 record stamp as epoch seconds, or nothing.

    An offset-less stamp is read as **UTC**, which is the repo-wide rule for every
    ISO string arriving from outside (see `iso_epoch`). Without the explicit
    `tzinfo`, `.timestamp()` reads a naive value as *server-local*, so the same
    transcript produced a reading that moved with the reader's timezone — eight
    hours out in UTC+8, which is enough to place a live turn outside the activity
    window and hide the session.
    """
    return iso_epoch(ts)


def parse_utc_sql(value: Any) -> float:
    """One SQL datetime as epoch seconds, or 0.

    SQLite has no timestamp type, so these arrive as text and usually without an
    offset. Same rule as everywhere else: no offset means UTC. The space-for-T
    substitution is what makes `fromisoformat` accept SQLite's own default
    spelling; 0 rather than None because the callers window on this and treat 0 as
    "not in the window".
    """
    return iso_epoch(str(value).replace(" ", "T")) or 0


def norm_epoch(value: Any) -> float:
    """One record's timestamp in seconds, or 0 for "not observed".

    Bools and non-finite floats are refused alongside the obvious rubbish, and
    both were reachable. `isinstance(True, int)` is true and `True <= 0` is
    false, so a JSON `true` in a store file became the epoch 1. A NaN passes
    every comparison it is given, so it walked through both guards a reading
    uses to decide whether a session had settled and published a final verdict
    on a session that had not ended.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    if not math.isfinite(value) or value <= 0:
        return 0
    return value / 1000 if value > 1e12 else value


EXTRACT_TEXT_CAP_CHARS: Final = 2000


def extract_text(value: Any, depth: int = 0, *, cap: int = EXTRACT_TEXT_CAP_CHARS) -> str:
    """One record's text, bounded.

    The bound is on both branches, which it was not: a list of blocks was capped
    and a bare string was returned whole. A prompt is a bare string on most
    harnesses and there is no bound on how long one is, so `safe_text` scanned
    the entire pasted file to publish 140 characters of it, and the Codex
    instruction walk ran `states_work` and `injected_prompt` over the same. The
    default is 2,000 because that is what the list branch already used, and it is
    fourteen times the widest field anything downstream publishes.

    `cap` exists because a caller that reads the text for a SIGNAL rather than
    for publication needs a different bound, and the default silently took one
    away: the observer scans the newest assistant message for a block indicator
    anywhere in it, so a 2,000-character bound made an indicator past that offset
    unreachable and the block field came back empty. A caller passing its own cap
    has to be able to vouch for it, which is why this is keyword-only.
    """
    if depth > 4 or value is None:
        return ""
    if isinstance(value, str):
        return value[:cap]
    if isinstance(value, list):
        parts = (extract_text(item, depth + 1, cap=cap) for item in value)
        return " ".join(part for part in parts if part)[:cap]
    if isinstance(value, dict):
        for key in ("text", "content", "message", "prompt", "value"):
            if key in value:
                text = extract_text(value[key], depth + 1, cap=cap)
                if text:
                    return text
    return ""


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def message_dict(record: Any) -> dict[str, Any]:
    return as_dict(as_dict(record).get("message"))


def alnum(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def record_fingerprint(record: Any) -> bytes:
    raw = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8", "replace"
    )
    return hashlib.blake2b(raw, digest_size=16).digest()


def gemini_records(record: Any) -> tuple[Any, ...]:
    snapshot = record.get("$set")
    messages = snapshot.get("messages") if isinstance(snapshot, dict) else None
    if isinstance(messages, list):
        return tuple(message for message in messages if isinstance(message, dict))
    return (record,)


def incremental_gemini_records(
    record: Any,
    state: dict[str, Any],
) -> tuple[Any, ...]:
    snapshot = record.get("$set")
    messages = snapshot.get("messages") if isinstance(snapshot, dict) else None
    if not isinstance(messages, list):
        return (record,)
    messages = tuple(message for message in messages if isinstance(message, dict))
    previous_count = state["gemini_snapshot_count"]
    start = 0
    if (
        previous_count
        and len(messages) >= previous_count
        and record_fingerprint(messages[previous_count - 1]) == state["gemini_snapshot_tail"]
    ):
        start = previous_count
    state["gemini_snapshot_count"] = len(messages)
    state["gemini_snapshot_tail"] = record_fingerprint(messages[-1]) if messages else None
    return messages[start:]


def model_signal(record: dict[str, Any], harness: str, limit: int) -> str | None:
    """The model one transcript record declares, bounded, or nothing.

    Codex re-declares the model at the head of every turn, in a `turn_context`
    record written one to six lines after each `task_started`. The last such
    record a rollout carries is therefore the model the session is running on
    now, which is the only question this answers: it reports a value, not a
    history, so a caller keeps the newest hit and does not compare it to the
    ones before it.

    Gated on the harness for the reason `_turn_signal` is gated: `scan_turns`
    runs this over five harnesses' transcripts, and an ungated read would let
    any of them publish a model out of a record that merely shares a type name.

    Nothing is inferred. A harness with no such record, a payload with no
    `model`, a non-string value, and a string that bounds away to nothing all
    yield None, which every consumer reads as "not measured" rather than as a
    statement about which model ran.
    """
    if harness != "codex" or record.get("type") != "turn_context":
        return None
    value = as_dict(record.get("payload")).get("model")
    if not isinstance(value, str):
        return None
    # Untrusted vendor text on its way to the DOM: bounded here, escaped again
    # at the render site.
    return safe_text(value, limit).strip() or None


def usage_signal(record: dict[str, Any], harness: str) -> int | None:
    """The measured output tokens one transcript record reports, or nothing.

    Claude assistant records are the only scanner input with a reviewed usage
    shape. The harness gate is part of the contract: ``scan_turns`` feeds records
    from five harnesses through this function, and a coincidentally Claude-shaped
    record from another one must not turn an unmeasured session into a zero-token
    session.

    Zero is a real reading when the record explicitly reports it. Missing,
    negative, boolean, and non-integer values are unmeasured and return None.
    """
    if harness != "claude" or record.get("type") != "assistant":
        return None
    value = as_dict(message_dict(record).get("usage")).get("output_tokens")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def tool_outcome(
    record: dict[str, Any], harness: str, limit: int
) -> tuple[dict[str, str], list[tuple[str, bool]]]:
    """The tool calls a record issues and the outcomes a record reports, as
    ``({tool_use_id: tool name}, [(tool_use_id, failed)])``.

    Claude only. Every other harness gets two empty containers, which read as
    "not measured" rather than as "nothing failed": Codex's tool-output records
    carry no error field at all (measured over 15 local rollouts), Copilot's
    analyzer sees no tool-end record, and Droid's block shape looks the same as
    Claude's but no failing Droid call has ever been captured — unmeasured
    semantics do not ship here. Gated on the harness for the same reason
    `_turn_signal` and `model_signal` are: `scan_turns` runs this over five
    harnesses' transcripts, and it is also the cheap way to keep the cost of
    walking content blocks off the four that would learn nothing from it.

    The name and the outcome arrive on different records — the name on the
    `tool_use` block, `is_error` on the `tool_result` block that points back at
    its id — so the id is the only join between them and both halves are
    returned rather than one flattened answer.

    A tool NAME, never its input. The input is the user's command text, and
    nothing here needs it: the consumer counts a run and names the tool it ran
    (see docs/design-runtime-architecture.md for who owns that count).
    """
    if harness != "claude" or record.get("type") not in ("assistant", "user"):
        return ({}, [])
    content = message_dict(record).get("content")
    if not isinstance(content, list):
        return ({}, [])
    calls: dict[str, str] = {}
    results: list[tuple[str, bool]] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "tool_use":
            block_id, name = block.get("id"), block.get("name")
            if isinstance(block_id, str) and block_id and isinstance(name, str):
                # Untrusted vendor text on its way to the DOM: bounded here,
                # escaped again at the render site.
                bounded = safe_text(name, limit).strip()
                if bounded:
                    calls[block_id] = bounded
        elif block_type == "tool_result":
            block_id = block.get("tool_use_id")
            if isinstance(block_id, str) and block_id:
                results.append((block_id, bool(block.get("is_error"))))
    return (calls, results)


def _turn_signal(record: dict[str, Any], harness: str) -> tuple[str, Any] | None:
    record_type = record.get("type")
    if harness == "codex":
        if record_type != "event_msg":
            return None
        payload = as_dict(record.get("payload"))
        payload_type = payload.get("type")
        if payload_type == "task_started":
            return ("start", payload.get("started_at"))
        if payload_type in ("task_complete", "turn_aborted"):
            return ("end", None)
        return None
    if harness == "copilot":
        if record_type == "user.message":
            return ("prompt", None)
        if record_type in ("session.task_complete", "session.shutdown", "abort"):
            return ("end", None)
        return None
    if harness == "gemini":
        if record_type != "user":
            return None
        content = record.get("content")
        if isinstance(content, list) and any(
            isinstance(item, dict) and "functionResponse" in item for item in content
        ):
            return None
        return ("prompt", None)
    if harness == "droid":
        if record_type != "message":
            return None
        message = message_dict(record)
        if message.get("role") != "user":
            return None
        content = message.get("content")
        if isinstance(content, list) and any(
            isinstance(item, dict) and item.get("type") == "tool_result" for item in content
        ):
            return None
        return ("prompt", None)
    if record_type != "user" or record.get("isMeta"):
        return None
    content = message_dict(record).get("content")
    if isinstance(content, list) and any(
        isinstance(item, dict) and item.get("type") == "tool_result" for item in content
    ):
        return None
    # Both names are also in `_CLAUDE_USER_TAGS`, and the duplication is
    # deliberate: this is a RECORD rule and that is a TEXT rule. Here the whole
    # record is discarded before any turn is counted; there the leading tag
    # merely disqualifies the text from standing in for a person's intent. The
    # tag set covers seven further names this must NOT refuse, so it cannot be
    # read from there — but a name added here belongs in both.
    if isinstance(content, str) and content.lstrip().startswith(
        ("<local-command-stdout>", "<local-command-caveat>")
    ):
        return None
    return ("prompt", None)


# ---------------------------------------------------------------------------
# Harness-injected prompts
#
# A "user" record is not the same thing as an operator instruction. Every
# harness writes its own machinery into that channel — skill bodies, hook
# feedback, compaction summaries, subagent notifications — and a reader that
# treats those as things a person said reports the wrong goal, the wrong stage,
# and the wrong idea of who is waiting on whom.
#
# The lists below were derived rather than guessed, and
# `scripts/derive_prompt_shapes.py` is the code that derived them — kept, so a
# reviewer can re-run it against their own store rather than take these on
# trust. Every count below is one of its outputs, re-derived 2026-08-27; every
# entry carries one, and nothing without one is here.
#
# **Which records were counted**, because the two halves count different ones:
#
#   Codex   458 `rollout-*.jsonl` files. The user set counts LEADING tags over
#           the union of two populations — 1,007 `event_msg`/`user_message`
#           texts and 1,734 `response_item` message texts with `role: "user"`.
#           A union rather than a choice because the record shape moved mid-CLI,
#           and it DOUBLE-COUNTS: a build that writes both spells one prompt
#           twice, and 974 of the 1,007 `event_msg` prompts have a matching
#           `response_item`. So these are occurrences of a shape, not prompts.
#   Codex   1,826 `response_item` message texts with `role: "developer"`, for
#           the developer set below.
#   Claude  211,669 user-role texts across 3,774 transcripts matching the
#           collector's own glob.
#
# A live store only grows, so re-running the script produces slightly larger
# figures than these. What has to keep holding is the SHAPE of each claim — which
# tag leads, which never does, which population a count is over — not the digits.
#
# The two harnesses do not share a vocabulary, which is why there are two sets
# rather than one. Codex spells its injections with underscores
# (`<recommended_plugins>`) and Claude with hyphens (`<local-command-caveat>`);
# only five names appear in both. An unmeasured harness gets the union, because
# there is no evidence to narrow it and every name in either set is machinery no
# operator opens a prompt with.

# `<image>` is a WRAPPER, not a rejection. All 36 Codex records that open with
# one carry real operator text after it, so rejecting on the tag would drop
# genuine prompts. Claude spells the same thing in plain text, in three
# populations that behave differently and were once counted as one:
#
#   `[Image: source: /path/…]`  387 records, 387 of them nothing but markers
#   `[Image source: /path/…]`   9 records, all 9 nothing but markers
#   `[Image #1]`                135 records, 134 carrying operator text after it
#
# The first two reach the empty-after-stripping rejection; the third is why this
# is a wrapper at all, and why the separator is a character class rather than a
# literal colon — `#` follows a space, not a colon. The attribute matcher is
# loose because Codex writes `name=[Image #1]` unquoted, spaces and `#` and `]`
# included.
_PROMPT_IMAGE_WRAPPER_RE = re.compile(
    r"^\s*(?:<image\b[^>]*>\s*(?:</image>)?|\[Image[:\s][^\]]*\])\s*",
    re.IGNORECASE,
)

# Only a tag that opens the text, so prose merely containing markup later on is
# left alone. The trailing class separates `<skill>` from a sentence beginning
# "<3 this".
_PROMPT_LEADING_TAG_RE = re.compile(r"^</?([A-Za-z][A-Za-z0-9_-]*)[\s>/]")

# The slash-command tags — `<command-message>`, `<command-name>`,
# `<command-args>` — are deliberately absent from both sets. They WRAP the
# operator's intent rather than replacing it: a slash command is what the
# person asked for, spelled in the harness's own markup. `transcripts.prompt_title`
# already owns rendering them, through a dedicated `_COMMAND_NAME_RE` /
# `_COMMAND_ARGS_RE` path that reads the bytes back out as
# `/claude-code-review 1287 - with a fresh pair of eyes...`, so rejecting them
# here would have left two primitives in one runtime disagreeing about the same
# record. Measured before removal: 1,493 of 15,109 `_turn_signal`-reachable
# Claude prompts carried a `<command-name>` with non-empty `<command-args>` and
# every one was rejected, which left 213 of 3,100 collector-gated sessions with
# no recoverable operator intent at all.
#
# The observed record's event builder (`project_context._instruction_event`)
# reads them through `transcripts.command_direction`, which renders with
# `prompt_title` and refuses a local command and a `harness_control` name, so a
# skill command is a later direction and a person entry while `/clear` is
# neither. Before that it kept the record and published nothing from it, every
# line opening with `<` (DRC-4764).
#
# `<teammate-message>` stays listed, and the cost is accepted rather than
# overlooked: a message from another agent is not the operator's instruction,
# so the 563 sessions carrying one show nothing from it.

# Measured LEADING a Codex user-role record, over the union described above.
_CODEX_USER_TAGS = frozenset(
    {
        "recommended_plugins",  # 226
        "skill",  # 99
        "teammate-message",  # 90
        "environment_context",  # 42
        "subagent_notification",  # 36
        "task-notification",  # 34
        "local-command-stdout",  # 18
        "bash-input",  # 14
        "bash-stdout",  # 14
        "user_shell_command",  # 5
        "turn_aborted",  # 3 here, and 52 leading a developer-role record
        # 83 over a later local corpus (codex-cli 0.149 to 0.164), every one written by Codex:
        # 55 `source="user_goal"` lines restating a `/goal` action, 27 `source="goal"` goal
        # continuation instructions, 1 `source="daemon_recovery"`. The goal itself is published
        # as `session_goal` (`claude_data._codex_goal_event`).
        "codex_internal_context",
    }
)

# Measured in the same rollouts, but on a `developer`-role record rather than a
# user-role one. They are listed because the role a Codex build files an
# injection under has already moved once — `turn_aborted` appears under both —
# and the cost is asymmetric: an unlisted tag renders harness markup as a
# person's words, while a listed one that never arrives costs nothing.
#
# LEADING counts, which is the only kind that can make `injected_prompt` fire.
# These were containment counts before, and the difference is not cosmetic: two
# of the seven lead 0 records and can never fire at all, and reading a
# containment count as evidence for a leading rule is what hid
# `collaboration_mode` — 122 containments, 53 of them leading — until someone
# counted the two separately. The zero pair stays for the asymmetry above, but it
# is labelled rather than left looking measured.
_CODEX_DEVELOPER_TAGS = frozenset(
    {
        "permissions",  # 338
        "multi_agent_mode",  # 326
        "skills_instructions",  # 80
        "collaboration_mode",  # 53
        "app-context",  # 2
        "apps_instructions",  # 0 leading (281 contained) — defensive only
        "plugins_instructions",  # 0 leading (244 contained) — defensive only
    }
)

# Measured LEADING a Claude user-role record.
#
# Four of these nine — 1,917 of the 5,393 occurrences — sit on records
# `_turn_signal` already refuses, so they earn their place only on the readers
# that do not go through it (`observer._message_from` is the one that matters).
# The overlap is marked per entry rather than pruned: the two predicates answer
# different questions, and a name dropped here because one caller happens to
# reject it would silently un-reject it for the other.
_CLAUDE_USER_TAGS = frozenset(
    {
        "task-notification",  # 1804
        "teammate-message",  # 1184
        "local-command-caveat",  # 1065, all refused by `_turn_signal`
        "local-command-stdout",  # 621, all refused by `_turn_signal`
        "bash-input",  # 242
        "bash-stdout",  # 241
        "system-reminder",  # 227, 223 of them refused by `_turn_signal`
        # The fourth refused entry, and the header's total needs it: 1,065 + 621
        # + 223 + 8 = 1,917.
        "channel",  # 8, all refused by `_turn_signal` — a Slack-plugin envelope
        "local-command-stderr",  # 1
    }
)

_INJECTED_TAGS = {
    "codex": _CODEX_USER_TAGS | _CODEX_DEVELOPER_TAGS,
    "claude": _CLAUDE_USER_TAGS,
}
_ANY_INJECTED_TAG = frozenset[str]().union(*_INJECTED_TAGS.values())

# Injections no tag regex can reach, because the harness writes them as prose.
# Shared across harnesses rather than split: two were measured in both corpora,
# none of the rest is a phrase an operator opens a prompt with, so splitting
# would buy nothing and would make a harness that borrows another's wording
# silently wrong.
_INJECTED_PROMPT_PREFIXES = (
    "# AGENTS.md instructions",  # codex 165
    "Analyze this conversation and determine",  # claude 1084
    "Another Claude session sent a message:",  # codex 130, claude 645
    "Base directory for this skill:",  # claude 3057
    "Caveat: The messages below were generated by the user while running",  # claude 43
    "Stop hook feedback:",  # claude 581
    "This session is being continued from a previous conversation",  # claude 356
    "[Request interrupted by user",  # codex 4, claude 297
    "[external_agent_tool_result]",  # codex 4
)

# Matched whole rather than as a prefix. All 97 occurrences over the Claude
# population above are exactly this word, and as a prefix it would reject
# "Warmup the cache before the run", which is an operator saying something.
#
# Subagent-only: all 97 are `isSidechain` records, 0 arrive on a Codex rollout,
# and `_turn_signal` already refuses 12 of the 97. So the rule matters to the
# readers that see a subagent's own transcript and to nothing else.
_INJECTED_PROMPTS = frozenset({"Warmup"})


# Trimmed off both ends before anything is matched against the vocabularies.
# `str.strip()` removes whitespace and NONE of these is whitespace to Python, so
# a single U+FEFF in front of `<system-reminder>` defeated the leading-tag regex,
# the prose prefixes and the whole-body set — all three branches of
# `injected_prompt` at once, and it is the one degenerate class that fails OPEN:
# the answer becomes "the operator said this", and harness machinery is published
# as a goal. `safe_text` strips most of the same set, but it runs after this on
# every path that reads a prompt.
#
# The set is `_UNSAFE_CHARS` minus C0/DEL, plus U+2060 and U+FEFF: both are
# invisible joiners no prompt legitimately opens with. U+200C and U+200D stay out
# for the reason `_UNSAFE_CHARS` gives — they are orthographic.
_PROMPT_TRIM_CLASS = "\\s\\ufeff\\u200b\\u2060\\u200e\\u200f\\u202a-\\u202e\\u2066-\\u2069"
_PROMPT_TRIM_RE = re.compile(f"^[{_PROMPT_TRIM_CLASS}]+|[{_PROMPT_TRIM_CLASS}]+$")


def strip_prompt_wrappers(text: str) -> str:
    """Peel the harness's image markers off the front of a user prompt.

    Repeatedly, because one message can carry several screenshots and each
    arrives as its own marker. What is left is either the operator's own words
    or nothing at all.
    """
    stripped = _PROMPT_TRIM_RE.sub("", text)
    while True:
        shorter = _PROMPT_TRIM_RE.sub("", _PROMPT_IMAGE_WRAPPER_RE.sub("", stripped, count=1))
        if shorter == stripped:
            return stripped
        stripped = shorter


# Claude Code 2.1.305 stores a paste in the user record's content string as
# `\n\n<pasted_content id="N">\nTEXT\n</pasted_content>\n`, with whatever the reader typed around
# it. Only the two tags are the harness's; the text between them is the reader's, or Compass's for
# a correction pasted back. The attribute list is matched loosely because the shape is measured,
# not documented, and a tag name that only begins the same (`pasted_contents`) is another tag.
_PASTE_TAG_RE = re.compile(r"</?pasted_content(?:\s[^<>]*)?>")


def strip_paste_wrapper(text: str) -> str:
    """The text with the harness's paste tags taken off, trimmed as `strip_prompt_wrappers` does.

    Two readers hold the same rule: what the page quotes of a direction, and the digest that
    recognises a correction pasted back, so a wrapper never reaches either.
    """
    return _PROMPT_TRIM_RE.sub("", _PASTE_TAG_RE.sub("", text))


def injected_prompt(text: str, harness: str) -> bool:
    """Is this user-record text the harness talking, rather than the operator?

    True means the record is machinery: a skill body, a hook's feedback, a
    compaction summary, an envelope around something else. Callers use it to
    decide what may stand in for a person's intent, so a false positive costs a
    real prompt and a false negative reports markup as a goal.

    `observer._is_generic_opener` asks the same question of a different thing —
    a real user message that states no goal — and keeps its own short list. The
    two are deliberately disjoint and deliberately separate; that function's
    docstring owns why.
    """
    body = strip_prompt_wrappers(text)
    if not body:
        return True
    tag = _PROMPT_LEADING_TAG_RE.match(body)
    if tag:
        return tag.group(1).casefold() in _INJECTED_TAGS.get(harness, _ANY_INJECTED_TAG)
    return body in _INJECTED_PROMPTS or body.startswith(_INJECTED_PROMPT_PREFIXES)


# ---------------------------------------------------------------------------
# The instruction line
#
# Widths first, in one place, because they were in two and drifted: the 80 was
# applied inside `transcripts.analyze_codex_transcript` and the 140 at
# `collectors/codex.py`, so no reader could see both at once.
#
# 140 is the width `last_prompt` has always been clipped to and is kept rather
# than rederived; 80 is the width `transcripts.prompt_title` already defaults to.
PROMPT_TITLE_CAP_CHARS: Final = 80
LAST_PROMPT_CAP_CHARS: Final = 140
# The line-2 cap. It lives here rather than in `config` because the width is not
# a tuning knob — it is the same untrusted-text bound `last_prompt` carries, on a
# field published beside it — and `config.py` is a documented merge hotspot.
INSTRUCTION_CAP_CHARS: Final = 140

# Lexicon of low-content tokens that appear in prompts that carry no work.
# Extracted from 293 hand-reviewed distinct short prompts in a corpus of 3,774
# Claude transcripts and 458 Codex rollouts, measured 2026-08-27. Words that
# appeared ONLY in "bare continuations" — prompts where the operator told the
# agent to proceed without stating new work — were kept; words that appeared in
# ANY contentful short prompt were rejected, which eliminated false positives like
# "ready" (contentful: "ready to review PR #123") and "run" (contentful: "run the
# integration tests").
#
# A prompt reads as a bare continuation when ALL its tokens (first line only,
# lowercased, stripped of punctuation) appear in this set AND it contains ≤8
# tokens. Both conditions are required: "better" alone would reject prompts about
# code changes, and "better this way than that way" would accept a pasted quote
# that names a choice. The 8-token cap is the one threshold set by data: 924 of
# 925 mid-flight continuation prompts have ≤8 tokens; 402 contentful prompts
# exceed it, with the shortest at 9.
#
# Char counts and word counts alone were measured and rejected: <40 chars would
# replace 402 good lines to fix 81 bad ones. The vocabulary replaces 81 bad ones
# and 9 good ones (98.9% precision, 91.2% recall among the hand-reviewed set).
_CONTINUATION_VOCABULARY: Final = frozenset(
    {
        "yes",
        "yeah",
        "yep",
        "ya",
        "y",
        "no",
        "nope",
        "ok",
        "okay",
        "k",
        "sure",
        "fine",
        "cool",
        "great",
        "nice",
        "perfect",
        "awesome",
        "please",
        "thanks",
        "thank",
        "you",
        "thx",
        "continue",
        "continuing",
        "proceed",
        "proceeding",
        "execute",
        "executing",
        "go",
        "going",
        "ahead",
        "run",
        "start",
        "do",
        "doit",
        "it",
        "this",
        "that",
        "these",
        "those",
        "them",
        "all",
        "both",
        "again",
        "more",
        "next",
        "now",
        "then",
        "and",
        "or",
        "so",
        "approve",
        "approved",
        "approval",
        "accept",
        "accepted",
        "confirm",
        "confirmed",
        "confirmation",
        "looks",
        "look",
        "sounds",
        "sound",
        "good",
        "better",
        "right",
        "correct",
        "im",
        "i",
        "m",
        "am",
        "is",
        "are",
        "was",
        "were",
        "be",
        "lets",
        "let",
        "s",
        "us",
        "we",
        "keep",
        "carry",
        "on",
        "forward",
        "try",
        "retry",
        "rerun",
        "re",
        "same",
        "as",
        "before",
        "option",
        "a",
        "b",
        "c",
        "d",
        "e",
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
        "9",
        "0",
        "of",
        "course",
        "with",
        "the",
        "your",
        "my",
        "agree",
        "agreed",
        "send",
        "sent",
        "post",
        "posted",
        "push",
        "pushed",
        "ship",
        "shipped",
        "sequence",
        "subagent",
        "driven",
        "ultrathink",
        "ultracode",
        "hi",
        "hello",
        "hey",
    }
)

_CONTINUATION_PUNCT_RE: Final = re.compile(r"[^a-z0-9']+")


def bare_continuation(text: str) -> bool:
    """Does this prompt carry an instruction, or only tell the agent to go on?

    True for "proceed" and "yes, do that"; false for "resolve the blocker and
    create the pr". Callers use it to decide whether a labelled second line
    earns its space, never to replace what the operator actually said.

    Give it a RENDERED line, not a raw record. A slash command arrives as sixty
    characters of markup that counts as six words and reads as a continuation,
    while the line a person sees is `/burndown DRC-4266 and the board`.
    `transcripts.states_work` is the pairing that gets this right.

    Measured on 3,774 Claude transcripts and 458 Codex rollouts, 2026-08-27:
    the vocabulary-based approach rejects 81 bare continuations (91.2% recall) and
    9 contentful prompts (98.9% precision), against 58 contentful false negatives
    for a word-count threshold.
    """
    stripped = strip_prompt_wrappers(text)
    # First line only, because a multi-line continuation might have detail below
    # the headline — "yes\n details here" — and the count should ignore it.
    first_line = stripped.split("\n")[0]
    # Tokens are case-insensitive and stripped of non-alphanumeric chars (except
    # apostrophes, which are orthographic in contractions).
    tokens = [w for w in _CONTINUATION_PUNCT_RE.split(first_line.lower()) if w]
    if not tokens:
        return True
    # All tokens must be in the vocabulary AND count must be ≤8.
    return len(tokens) <= 8 and all(w in _CONTINUATION_VOCABULARY for w in tokens)


# A rendered directive that is one slash-command token and nothing else. The
# name is matched against the set below; the shape only isolates it.
_BARE_COMMAND_RE = re.compile(r"^/([A-Za-z0-9][A-Za-z0-9:._-]*)$")

# Slash commands that drive the harness rather than the work, with their
# occurrence counts as the last published goal in the local corpus. Shared
# across harnesses rather than split per harness, on the same reasoning as the
# injected-prose prefixes above: `clear` and `login` were measured in both, and
# none of the rest is a name one harness could mean differently.
_HARNESS_CONTROL_COMMANDS: Final = frozenset(
    {
        "add-dir",  # claude 2
        "clear",  # claude 72, codex 1
        "context",  # claude 2
        "exit",  # claude 7
        "insights",  # claude 1
        "login",  # claude 70, codex 3
        "mcp",  # claude 11
        "model",  # claude 5
        "plugin",  # claude 21
        "reload-plugins",  # claude 7
        "reload-skills",  # claude 1
        "stickers",  # claude 1
    }
)


def harness_control(rendered: str | None) -> bool:
    """Whether a *rendered* directive drives the harness rather than the work.

    Applied to what `transcripts.prompt_title` produces, not to the raw record:
    the raw spelling is `<command-name>/clear</command-name>` and the value
    actually published is `/clear`, so a predicate reading the raw text never
    meets the one the page shows.

    A measured name list and NOT the structural rule "a bare command carries no
    arguments, so it carries no goal". That rule was checked against the same
    corpus and is wrong: bare-command goals are also skill invocations —
    `/create-pr`, `/compass:compass`, `/security-review` — and a skill invoked
    with no arguments is exactly what the operator asked for. Argument-carrying
    commands are untouched either way; `prompt_title` renders those as
    `/code-review 1287 with fresh eyes`, which never matches here.

    Lives in `records` rather than in any caller because three surfaces publish
    the same reading of the same directive: `observer.py` picks a session goal,
    `transcripts.states_work` picks the instruction line beneath a session
    title, and `transcripts.command_direction` decides whether a command is a
    direction in the observed record. None of them calls this directly: they
    ask `transcripts.harness_control_prompt`, which reads the raw record for a
    local command first and comes here for the name (DRC-4764). Separate lists
    would be chances to disagree about whether `/clear` is an objective.
    """
    match = _BARE_COMMAND_RE.match(rendered or "")
    return match is not None and match.group(1).casefold() in _HARNESS_CONTROL_COMMANDS


def instruction_line(
    label: str,
    text: str | None,
    at: float | None,
    *,
    limit: int = INSTRUCTION_CAP_CHARS,
) -> dict[str, Any] | None:
    """One published line-2 reading, bounded, or nothing.

    ``label`` is what the page prefixes the line with — the reason a stale or
    second-hand line is survivable at all — so a reading with no label is not
    published. ``at`` is the record's own stamp; the page renders the age from
    it, and 0 means unstamped rather than "now".

    The bound is the cap plus one because `transcripts.clip` appends its ellipsis
    AFTER cutting to the cap, so a clipped title is cap + 1 characters and a
    scrub at the cap takes the `…` back off — 29 of 1,906 published Claude lines
    ended in an unmarked mid-token cut that way. `safe_text` only ever shortens,
    so this cannot truncate what rendering already bounded. The same reasoning,
    and the same `+ 1`, guards line 1 in `transcripts.codex_instruction`.
    """
    bounded = safe_text(text, limit + 1).strip()
    if not bounded or not label:
        return None
    return {"label": label, "text": bounded, "at": at if at and at > 0 else 0}


# Shorter pieces of a masked value are not scrubbed from text: a two-letter piece
# would wipe ordinary output, and the check line masks it anyway.
SCRUB_MIN_CHARS: Final = 4

# Words that name no credential even when a command line masked them: an
# environment literal (`CI=true`, `NODE_ENV=production`), a branch, an auth scheme.
_EXPLANATION_WORDS: Final = frozenset(
    {"true", "false", "none", "null", "test", "dev", "prod", "production", "main", "master"}
    | _MASK_AUTH_WORDS
)


def explanation_values(values: Iterable[str]) -> set[str]:
    """The masked values worth removing from prose a reader will read.

    A command line masks every `NAME=value`, so `CI=true` and `--env MODE=test`
    put `true` and `test` in the set, and removing those from an explanation
    would erase ordinary words. This keeps a value that can be a credential: not
    an environment literal, an auth scheme, a bare number or a lowercase word.
    A value with whitespace in it is cut into its words, and an auth scheme is
    never one of them, so `Bearer <token>` costs the token and not `Bearer`.
    The accepted loss is a lowercase-letters-only password, which the check
    line still masks and the output tail still scrubs.
    """
    keep: set[str] = set()
    for value in values:
        pieces = value.split()
        if len(pieces) > 1 and pieces[0].lower() not in _MASK_AUTH_WORDS:
            pieces = [value, *pieces]
        for piece in pieces:
            if (
                len(piece) >= SCRUB_MIN_CHARS
                and piece.lower() not in _EXPLANATION_WORDS
                and not piece.isdigit()
                and not (piece.isalpha() and piece.islower())
            ):
                keep.add(piece)
    return keep


def scrub_values(text: str, values: Iterable[str], *, prose: bool = False) -> str:
    """`text` with every value a command line masked replaced by the marker.

    A masked command line still leaves the value in two other places: an echoed
    command in the output, and the agent's own words about it. This removes it
    from either. Filename and path characters stay inside the word, so a password
    `test` does not turn `test_a.py`, `test-file.py` or `src/test` into a
    redacted name.

    `prose` is for a sentence: there a `.`, `:` or `,` that ends the sentence, or
    a bracket or quote around the word, does not make the value part of a longer
    word, while `.`, `:` or `/` followed by a word character still does. The
    output tail keeps the strict boundary because a filename ends in `.py`.
    """
    spellings = {
        spelling
        for value in values
        for piece in (value, *value.split())
        if len(piece) >= SCRUB_MIN_CHARS
        for spelling in (
            piece,
            shlex.quote(piece),
            "'" + piece.replace("'", "'\\''") + "'",
            piece.replace("'", "'\\''"),
            piece.replace("'", "'\"'\"'"),
        )
    }
    if not spellings:
        return text
    text = _scrub_pass(text, _scrub_patterns(tuple(sorted(spellings)), prose))
    # A later pass reads what the first left behind a marker: `V1:V2` in prose rejects V1 at
    # the `:` until V2 is a marker, so each pass can free one more value of a chain. It stops
    # when nothing changes; the cap bounds a long chain. A spelling the marker itself contains
    # (a value `REDACTED`) is done after the first pass, or it would match inside every marker.
    later = tuple(sorted(spelling for spelling in spellings if spelling not in _SECRET_MARKER))
    if not later:
        return text
    patterns = _scrub_patterns(later, prose)
    for _ in range(_SCRUB_PASSES - 1):
        scrubbed = _scrub_pass(text, patterns)
        if scrubbed == text:
            break
        text = scrubbed
    return text


_SCRUB_PASSES: Final = 16


def _scrub_pass(text: str, patterns: tuple[re.Pattern[str], ...]) -> str:
    plain, joined_flag, userinfo, touching, inner = patterns
    # Userinfo first: a plain pass would let a short spelling match inside `user:Fake99!@` in
    # prose and leave the `!` of the longer one, where the one-at-a-time loop took the longest.
    text = userinfo.sub(lambda match: match[1] + _SECRET_MARKER + match[2], text)
    text = joined_flag.sub(lambda match: match[1] + _SECRET_MARKER, text)
    # Two masked values with nothing between them reject each other at the word boundary, so a
    # run of them is read whole before the single-value pass sees either.
    text = touching.sub(lambda match: _mask_run(match[0], inner), text)
    return plain.sub(_SECRET_MARKER, text)


def _mask_run(run: str, inner: re.Pattern[str]) -> str:
    """One marker per value in a run of touching values, or one for the run where the values
    cannot be split back out of it."""
    split = inner.sub(_SECRET_MARKER, run)
    return split if split.replace(_SECRET_MARKER, "") == "" else _SECRET_MARKER


def _trie_alternation(spellings: tuple[str, ...]) -> str:
    """One regex alternation over `spellings`, shared prefixes factored out.

    A flat alternation tries every branch at every offset, and each value has a quote-wrapped
    spelling, so a quote-heavy result cost O(quotes x values): 3.5 s for 100,000 quotes at 4,096
    values. A prefix tree tries only the branches that start with the character in hand. Longer
    branches are tried before the end of a shorter one, so the longest value still wins.
    """
    root: dict[str, Any] = {}
    for spelling in spellings:
        node = root
        for char in spelling:
            node = node.setdefault(char, {})
        node[""] = {}
    if _trie_depth(root) > _TRIE_DEPTH_MAX:
        # Values that each extend the last nest one group per value, and about 400 of them
        # overflow the recursion limit here and the regex parser's own. A flat alternation,
        # longest first, reads the same set without nesting.
        return "|".join(re.escape(s) for s in sorted(spellings, key=lambda s: (-len(s), s)))
    return _trie_regex(root)


# Deeper than any real set of masked values: each level is a value that prefixes another.
_TRIE_DEPTH_MAX: Final = 40


def _trie_depth(root: dict[str, Any]) -> int:
    """How many groups `_trie_regex` would nest, counted without recursing."""
    deepest = 0
    pending = [(root, 0)]
    while pending:
        node, depth = pending.pop()
        deepest = max(deepest, depth)
        for char, child in node.items():
            if not char:
                continue
            below = child
            while len(below) == 1 and "" not in below:
                ((_, below),) = below.items()
            pending.append((below, depth + 1))
    return deepest


def _trie_regex(node: dict[str, Any]) -> str:
    ends = "" in node
    branches = []
    for char in sorted(node):
        if not char:
            continue
        label, child = char, node[char]
        while len(child) == 1 and "" not in child:
            ((next_char, grand),) = child.items()
            label += next_char
            child = grand
        branches.append(re.escape(label) + _trie_regex(child))
    if not branches:
        return ""
    body = branches[0] if len(branches) == 1 else "(?:" + "|".join(branches) + ")"
    return f"(?:{body})?" if ends else body


@lru_cache(maxsize=2)
def _scrub_patterns(
    spellings: tuple[str, ...], prose: bool
) -> tuple[re.Pattern[str], re.Pattern[str], re.Pattern[str], re.Pattern[str], re.Pattern[str]]:
    """The patterns a scrub applies, each one alternation over every spelling.

    Compiling three patterns per spelling cost 0.18 s at 512 values and 1.8 s for ten scrubs
    in a press. Longest first, so a value that is a prefix of another leaves no tail: the
    alternation takes the first branch that fits and the trailing boundary rejects a short
    branch that stops inside a longer word. The cache is keyed by the spellings, since a press
    scrubs several explanations and tails against the same set; two entries, because it holds
    real masked values. The userinfo pattern starts only at the head of a run, as
    `_MASK_USERINFO` does, or a long word rescans its rest at every offset. The run pattern is
    atomic, so a run of overlapping values such as `aaaa`, `aaaaa` and `aaaaaa` cannot be
    split in exponentially many ways when the boundary after it fails.
    """
    boundary = r"[\w./:@+\-]"
    after = r"(?![\w@+\-]|[./:][\w/])" if prose else rf"(?!{boundary})"
    # In prose a `:` after a word is how `user:password` is quoted, so it does not
    # make the value part of a longer word; a `/`, `.` or `@` still does.
    before = r"(?<![\w./@+\-])" if prose else rf"(?<!{boundary})"
    alternation = _trie_alternation(spellings)
    return (
        re.compile(rf"{before}(?:{alternation}){after}"),
        # A run after the flag is one password (`-pV1V2`), so the flag pass takes all of it.
        re.compile(rf"(?<!{boundary})(-[pP])(?>(?:{alternation})+){after}"),
        re.compile(
            rf"((?<![^\s:/@'\"])(?:[A-Za-z][A-Za-z0-9+.-]*://)?[^\s:/@'\"]+:)(?:{alternation})(@)"
        ),
        re.compile(rf"{before}(?>(?:{alternation}){{2,}}){after}"),
        re.compile(rf"(?:{alternation})"),
    )
