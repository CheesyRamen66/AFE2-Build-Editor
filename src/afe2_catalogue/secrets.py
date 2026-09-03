"""Resolve the archive key without persisting or printing it.

The executable scanner mirrors the public technique used by AESDumpster and
AESDumpster-rs (https://github.com/yuhkix/aesdumpster-rs). Candidates are not
trusted merely because a byte pattern matched:
the caller must validate each candidate against an encrypted archive.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Callable, Iterable

from .errors import CatalogueError

_HEX_KEY = re.compile(r"^(?:0x)?([0-9a-fA-F]{64})$")

# Fixed bytes are integers; None is a wildcard. The offsets identify the eight
# little-endian 32-bit stores that make up a 256-bit AES key.
_PATTERNS: tuple[tuple[tuple[int | None, ...], tuple[int, ...]], ...] = (
    (
        (
            0xC7, None, None, None, None, None, None,
            0xC7, None, None, None, None, None, None,
            0xC7, None, None, None, None, None, None,
            0xC7, None, None, None, None, None, None,
            None, None, None, None,
            0xC7, None, None, None, None, None, None,
            0xC7, None, None, None, None, None, None,
            0xC7, None, None, None, None, None, None,
            0xC7, None, None, None, None, None, None,
        ),
        (3, 10, 17, 24, 35, 42, 49, 56),
    ),
    (
        (
            0xC7, None, None, None, None, None,
            0xC7, None, None, None, None, None, None,
            0xC7, None, None, None, None, None, None,
            0xC7, None, None, None, None, None, None,
            0xC7, None, None, None, None, None, None,
            0xC7, None, None, None, None, None, None,
            0xC7, None, None, None, None, None, None,
            0xC7, None, None, None, None, None, None,
        ),
        (2, 9, 16, 23, 30, 37, 44, 51),
    ),
    (
        (
            0xC7, None, None, None, None, None, None,
            0xC7, None, None, None, None, None, None,
            0x48, None, None, None,
            0xC7, None, None, None, None, None, None,
            0xC7, None, None, None, None, None, None,
            0xC7, None, None, None, None, None, None,
            0xC7, None, None, None, None, None, None,
            0xC7, None, None, None, None, None, None,
            0xC7, None, None, None, None, None, None,
        ),
        (3, 10, 21, 28, 35, 42, 49, 56),
    ),
    (
        (
            0xC7, None, None, None, None, None, None,
            0xC7, None, None, None, None, None, None,
            0xC7, None, None, None, None, None, None,
            0xC7, None, None, None, None, None, None,
            0xC7, None, None, None, None, None, None,
            0xC7, None, None, None, None, None, None,
            0xC7, None, None, None, None, None, None,
            0xC7, None, None, None, None, None, 0xC3,
        ),
        (51, 45, 38, 31, 24, 17, 10, 3),
    ),
)


def normalize_key(value: str) -> str:
    """Return a canonical hex key or raise without echoing the input."""

    match = _HEX_KEY.fullmatch(value.strip())
    if not match:
        raise CatalogueError("the configured AES key is not a 256-bit hexadecimal key")
    return match.group(1).lower()


def key_from_environment(name: str = "AFE2_AES_KEY") -> str | None:
    value = os.environ.get(name)
    return normalize_key(value) if value else None


def key_from_file(path: Path) -> str:
    try:
        if path.stat().st_mode & 0o077:
            raise CatalogueError("AES key file permissions are too broad; use mode 0600")
        return normalize_key(path.read_text(encoding="ascii"))
    except OSError as exc:
        raise CatalogueError(f"could not read AES key file: {path}") from exc


def _matches(data: bytes, start: int, pattern: tuple[int | None, ...]) -> bool:
    if start + len(pattern) > len(data):
        return False
    return all(expected is None or data[start + offset] == expected for offset, expected in enumerate(pattern))


def find_executable_key_candidates(data: bytes, limit: int = 4096) -> list[str]:
    """Find deduplicated key candidates in executable bytes.

    This function performs no archive validation and is public primarily so the
    pattern scan can be tested with synthetic input.
    """

    candidates: set[str] = set()
    for pattern, offsets in _PATTERNS:
        cursor = 0
        while len(candidates) < limit:
            start = data.find(b"\xc7", cursor)
            if start < 0:
                break
            cursor = start + 1
            if not _matches(data, start, pattern):
                continue
            raw = b"".join(data[start + offset : start + offset + 4] for offset in offsets)
            if len(raw) == 32 and any(raw):
                candidates.add(raw.hex())
    return sorted(candidates)


def resolve_key(
    *,
    executable: Path,
    validator: Callable[[str], bool],
    environment_name: str = "AFE2_AES_KEY",
    key_file: Path | None = None,
    allow_executable_scan: bool = True,
) -> tuple[str, str]:
    """Resolve and validate a key, returning ``(key, source)``.

    ``source`` is safe metadata (``environment``, ``file``, or ``executable``),
    never the key itself.
    """

    configured: Iterable[tuple[str, str]]
    environment_key = key_from_environment(environment_name)
    configured_values: list[tuple[str, str]] = []
    if environment_key:
        configured_values.append((environment_key, "environment"))
    if key_file:
        configured_values.append((key_from_file(key_file), "file"))
    configured = configured_values

    for key, source in configured:
        if validator(key):
            return key, source
        raise CatalogueError(f"the AES key supplied by {source} did not open the game archives")

    if allow_executable_scan:
        try:
            executable_bytes = executable.read_bytes()
        except OSError as exc:
            raise CatalogueError(f"could not read the shipping executable: {executable}") from exc
        for candidate in find_executable_key_candidates(executable_bytes):
            if validator(candidate):
                return candidate, "executable"

    raise CatalogueError(
        f"no working archive key was found; set {environment_name}, provide --key-file, "
        "or leave executable key discovery enabled"
    )
