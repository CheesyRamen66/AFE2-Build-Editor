from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import traceback
import unittest
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from afe2_catalogue.errors import CatalogueError  # noqa: E402
from afe2_catalogue.secrets import (  # noqa: E402
    _PATTERNS,
    find_executable_key_candidates,
    normalize_key,
    resolve_key,
)
from afe2_catalogue.tools import run_secret_command  # noqa: E402


def synthetic_executable_match(payload: bytes, pattern_index: int = 0) -> bytes:
    """Build a fake instruction sequence; payload is deliberately not a game key."""

    pattern, offsets = _PATTERNS[pattern_index]
    data = bytearray(0x90 if value is None else value for value in pattern)
    for index, offset in enumerate(offsets):
        data[offset : offset + 4] = payload[index * 4 : (index + 1) * 4]
    return bytes(data)


class ExecutableKeyCandidateTests(unittest.TestCase):
    def test_finds_and_deduplicates_a_synthetic_candidate(self) -> None:
        payload = bytes(range(1, 33))
        match = synthetic_executable_match(payload)
        executable = b"synthetic-prefix" + match + b"noise" + match

        self.assertEqual(find_executable_key_candidates(executable), [payload.hex()])

    def test_does_not_treat_an_all_zero_payload_as_a_candidate(self) -> None:
        executable = synthetic_executable_match(bytes(32))

        self.assertEqual(find_executable_key_candidates(executable), [])

    def test_resolve_key_validates_executable_candidates(self) -> None:
        rejected = bytes(range(1, 33))
        accepted = bytes(range(33, 65))
        executable_bytes = (
            synthetic_executable_match(rejected)
            + b"gap"
            + synthetic_executable_match(accepted)
        )
        seen: list[str] = []

        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(
            os.environ, {}, clear=True
        ):
            executable = Path(temporary) / "Synthetic-Shipping.exe"
            executable.write_bytes(executable_bytes)

            key, source = resolve_key(
                executable=executable,
                validator=lambda candidate: seen.append(candidate) is None
                and candidate == accepted.hex(),
            )

        self.assertEqual(key, accepted.hex())
        self.assertEqual(source, "executable")
        self.assertIn(rejected.hex(), seen)
        self.assertIn(accepted.hex(), seen)


class SecretErrorTests(unittest.TestCase):
    def test_invalid_configured_key_is_not_echoed(self) -> None:
        invalid_value = "synthetic-secret-that-is-not-hex"

        with self.assertRaises(CatalogueError) as raised:
            normalize_key(invalid_value)

        self.assertNotIn(invalid_value, str(raised.exception))

    def test_rejected_environment_key_is_not_echoed(self) -> None:
        synthetic_key = "ab" * 32

        with mock.patch.dict(
            os.environ, {"AFE2_AES_KEY": synthetic_key}, clear=True
        ), self.assertRaises(CatalogueError) as raised:
            resolve_key(
                executable=Path("unused.exe"),
                validator=lambda _candidate: False,
                allow_executable_scan=False,
            )

        self.assertNotIn(synthetic_key, str(raised.exception))
        self.assertIn("environment", str(raised.exception))

    def test_timeout_exception_chain_does_not_leak_secret_argv(self) -> None:
        synthetic_key = "cd" * 32
        timeout = subprocess.TimeoutExpired(
            cmd=["synthetic-tool", "--aes-key", synthetic_key], timeout=1
        )

        with mock.patch(
            "afe2_catalogue.tools.subprocess.run", side_effect=timeout
        ), self.assertRaises(CatalogueError) as raised:
            run_secret_command(
                ["synthetic-tool", "--aes-key", synthetic_key],
                secret=synthetic_key,
            )

        rendered = "".join(
            traceback.format_exception(
                type(raised.exception), raised.exception, raised.exception.__traceback__
            )
        )
        self.assertNotIn(synthetic_key, rendered)
        self.assertIn("redacted", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
