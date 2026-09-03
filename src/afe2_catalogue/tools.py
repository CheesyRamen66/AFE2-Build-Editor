"""External tool resolution and redaction-safe subprocess helpers."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Mapping, Sequence

from .errors import CatalogueError

_VERSION = re.compile(
    r"^(?P<name>[A-Za-z0-9_-]+)[ \t]+(?P<version>\d+(?:\.\d+)+)[ \t]*$",
    re.MULTILINE,
)


def tool_identity(
    path: Path,
    *,
    environment: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    try:
        result = subprocess.run(
            [str(path), "--version"],
            env=dict(environment) if environment is not None else None,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CatalogueError(f"could not run external tool: {path}") from exc
    output = f"{result.stdout}\n{result.stderr}".strip()
    match = _VERSION.search(output)
    if result.returncode or not match:
        raise CatalogueError(f"could not determine version for external tool: {path}")
    return match.group("name"), match.group("version")


def tool_version(
    path: Path,
    *,
    environment: Mapping[str, str] | None = None,
) -> str:
    return tool_identity(path, environment=environment)[1]


def run_secret_command(
    arguments: Sequence[str],
    *,
    secret: str,
    cwd: Path | None = None,
    timeout: int = 180,
) -> subprocess.CompletedProcess[str]:
    """Run a command whose argv includes a secret, without leaking its output.

    Tool output is returned to the trusted parser but is deliberately omitted
    from raised errors because some tools echo invocation details on failure.
    """

    if any(secret in argument for argument in arguments if argument != secret):
        raise CatalogueError("refusing to run a command with secret material embedded in another argument")
    try:
        return subprocess.run(
            list(arguments),
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        # TimeoutExpired carries the full argv, including the key. Suppress the
        # exception chain so even a caller traceback remains redacted.
        raise CatalogueError("an archive tool failed to execute; its command was redacted") from None
