import functools
import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

WEB_DIR = Path(__file__).resolve().parent

# The page is one self-contained response, so the packaged font subsets travel inside it as
# base64 rather than behind a second HTTP asset surface. Python never reads this table: the
# build (`frontend/build/package.mjs`, `readFonts`) parses it and the `@font-face` rows of
# `styles.css`, pairing each file with its slot, and embeds the decoded subsets in `react.html`.
FONT_ASSETS: tuple[tuple[str, str], ...] = (
    ("fonts/inter-v20-vietnamese.woff2.b64", "{{COMPASS_FONT_INTER_V20_VIETNAMESE}}"),
    ("fonts/inter-v20-latin-ext.woff2.b64", "{{COMPASS_FONT_INTER_V20_LATIN_EXT}}"),
    ("fonts/inter-v20-latin.woff2.b64", "{{COMPASS_FONT_INTER_V20_LATIN}}"),
)


def asset_path(name: str) -> Path:
    return WEB_DIR / name


def _object(value: Any, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise RuntimeError("react integrity metadata has an invalid schema")
    return value


def _digest(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _relative(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and not value.startswith("/")
        and "\\" not in value
        and ":" not in value
        and all(part not in {"", ".", ".."} for part in value.split("/"))
    )


def _verified_file(record: Any, name: str) -> bytes:
    entry = _object(record, {"file", "bytes", "sha256"})
    size = entry["bytes"]
    if (
        entry["file"] != name
        or type(size) is not int
        or not 0 < size <= 8 * 1024 * 1024
        or not _digest(entry["sha256"])
    ):
        raise RuntimeError(f"react integrity metadata has an invalid {name} binding")
    with asset_path(name).open("rb") as handle:
        content = handle.read(size + 1)
    if len(content) != size or hashlib.sha256(content).hexdigest() != entry["sha256"]:
        raise RuntimeError(f"react asset {name} does not match its integrity metadata")
    return content


def _validate_provenance(value: Any) -> None:
    provenance = _object(value, {"sources", "fonts", "packages"})
    shapes = {
        "sources": {"file", "sha256"},
        "fonts": {"file", "bytes", "sha256", "face"},
        "packages": {"name", "version", "license", "licenseFile", "sha256"},
    }
    for name, shape in shapes.items():
        entries = provenance[name]
        if not isinstance(entries, list) or len(entries) > 1024:
            raise RuntimeError("react integrity metadata has invalid provenance")
        seen: set[str] = set()
        for item in entries:
            entry = _object(item, shape)
            identity = entry["name"] if name == "packages" else entry["file"]
            if (
                not isinstance(identity, str)
                or not identity
                or identity in seen
                or not _digest(entry["sha256"])
            ):
                raise RuntimeError("react integrity metadata has invalid provenance identity")
            seen.add(identity)
            if name != "packages" and not _relative(identity):
                raise RuntimeError("react integrity metadata has an invalid source path")
            if name == "fonts" and (
                type(entry["bytes"]) is not int
                or entry["bytes"] <= 0
                or not isinstance(entry["face"], str)
            ):
                raise RuntimeError("react integrity metadata has invalid font provenance")
            if name == "packages" and (
                not _relative(entry["licenseFile"])
                or any(
                    not isinstance(entry[key], str) or not entry[key]
                    for key in ("version", "license")
                )
            ):
                raise RuntimeError("react integrity metadata has invalid package provenance")


class _DocumentShape(HTMLParser):
    def __init__(self, document: str) -> None:
        super().__init__()
        # HTMLParser reports Unicode character columns, not UTF-8 byte offsets.
        # Retain the source line starts so the injector's literal marker must
        # coincide with the actual parsed head close, including multiline text.
        self.line_starts = [0] + [index + 1 for index, char in enumerate(document) if char == "\n"]
        self.heads = 0
        self.head_end_positions: list[int] = []
        self.roots = 0
        self.focus = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.heads += tag == "head"
        self.roots += any(key == "id" and value == "root" for key, value in attrs)
        if tag == "meta":
            self.focus |= any(
                key == "name" and (value or "").lower() == "compass-focus" for key, value in attrs
            )

    def handle_endtag(self, tag: str) -> None:
        if tag == "head":
            line, column = self.getpos()
            self.head_end_positions.append(self.line_starts[line - 1] + column)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RuntimeError("react integrity metadata contains duplicate keys")
        result[key] = value
    return result


def load_frontend_page() -> bytes:
    """Load fixed installed bytes; contributor tools are never invoked here."""
    try:
        content = _load_react_page()
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise RuntimeError("react assets or integrity metadata are malformed") from exc
    return content


def _load_react_page() -> bytes:
    with asset_path("react.integrity.json").open("rb") as handle:
        raw = handle.read(128 * 1024 + 1)
    if len(raw) > 128 * 1024:
        raise RuntimeError("react integrity metadata exceeds its read bound")
    metadata = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    keys = {"format", "frontend", "document", "licenses", "provenance"}
    if isinstance(metadata, dict) and "optionalTerminal" in metadata:
        keys.add("optionalTerminal")
    metadata = _object(metadata, keys)
    if (
        type(metadata["format"]) is not int
        or metadata["format"] != 1
        or metadata["frontend"] != "react"
    ):
        raise RuntimeError("react integrity metadata has an unsupported format")
    _validate_provenance(metadata["provenance"])
    content = _verified_file(metadata["document"], "react.html")
    licenses = _verified_file(metadata["licenses"], "react-licenses.txt")
    for payload in (content, licenses):
        text = payload.decode("utf-8")
        if "\r" in text:
            raise RuntimeError("react assets must use UTF-8 and LF line endings")
    if "optionalTerminal" in metadata:
        terminal = _object(metadata["optionalTerminal"], {"javascript", "stylesheet"})
        _verified_file(terminal["javascript"], "vendor/xterm.js")
        _verified_file(terminal["stylesheet"], "vendor/xterm.css")
    document = content.decode("utf-8")
    shape = _DocumentShape(document)
    shape.feed(document)
    if (
        content.count(b"</head>") != 1
        or shape.heads != 1
        or len(shape.head_end_positions) != 1
        or document.find("</head>") != shape.head_end_positions[0]
        or shape.roots != 1
        or shape.focus
    ):
        raise RuntimeError("react.html must have one head, root, and no existing focus capability")
    return content


@functools.cache
def build_id() -> str:
    """A short digest of the page this process serves, or "" if it cannot load.

    Published on the board (regressions major 1, ui5) so a tab left open across
    an upgrade can tell that the server now serves another page, and say so,
    rather than send what the new server refuses. Once per process: the page
    is assembled once at start and served unchanged.
    """
    try:
        return "react-" + hashlib.sha256(load_frontend_page()).hexdigest()[:16]
    except (OSError, UnicodeError, RuntimeError):
        return ""
