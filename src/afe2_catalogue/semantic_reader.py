"""Pinned, repository-local .NET reader for Unreal exports and textures."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Mapping, Sequence

from .errors import CatalogueError
from .jsonio import digest_file, digest_value, read_json, write_json_atomic

try:  # The extractor itself is Linux-oriented, but imports should remain portable.
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX hosts
    fcntl = None  # type: ignore[assignment]


READER_NAME = "afe2-semantic-reader"
READER_VERSION = "0.3.2"
TARGET_FRAMEWORK = "net9.0"
PACKAGE_VERSIONS: Mapping[str, str] = {
    "CUE4Parse": "1.2.2",
    "CUE4Parse-Conversion": "1.2.1",
    "Microsoft.Bcl.Memory": "9.0.19",
    "SkiaSharp.NativeAssets.Linux.NoDependencies": "2.88.9",
    "UAssetAPI": "1.1.0",
}
SOURCE_FILENAMES = (
    "Afe2.SemanticReader.csproj",
    "Program.cs",
    "TexturePackageNormalizer.cs",
    "packages.lock.json",
)
MARKER_NAME = ".afe2-managed-semantic-reader.json"
Progress = Callable[[str], None]


@dataclass(frozen=True)
class ManagedSemanticReader:
    """A verified framework-dependent semantic-reader publication."""

    dotnet: Path
    dll: Path
    source_digest: str
    lock_digest: str
    reused: bool

    @property
    def command(self) -> tuple[str, str]:
        return str(self.dotnet), str(self.dll)

    def adapter_provenance(self) -> dict[str, object]:
        return {
            "lockDigest": self.lock_digest,
            "name": READER_NAME,
            "packages": dict(sorted(PACKAGE_VERSIONS.items())),
            "sourceDigest": self.source_digest,
            "targetFramework": TARGET_FRAMEWORK,
            "version": READER_VERSION,
        }


def _program(explicit: Path | str | None) -> Path:
    candidate = str(explicit) if explicit is not None else shutil.which("dotnet")
    if not candidate:
        raise CatalogueError(
            ".NET 9 SDK and runtime are required for semantic asset extraction; "
            "install dotnet and retry"
        )
    path = Path(candidate).expanduser().resolve()
    if not path.is_file():
        raise CatalogueError(f"dotnet executable does not exist: {path}")
    return path


def _environment(
    tools_root: Path,
    secret_environment_names: Sequence[str],
) -> dict[str, str]:
    environment = os.environ.copy()
    for name in {"AFE2_AES_KEY", *secret_environment_names}:
        if name:
            environment.pop(name, None)
    environment["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1"
    environment["DOTNET_NOLOGO"] = "1"
    environment["NUGET_PACKAGES"] = str(tools_root / "nuget-packages")
    return environment


def _run(
    arguments: Sequence[str],
    *,
    description: str,
    environment: Mapping[str, str],
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            list(arguments),
            env=dict(environment),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        # Do not propagate a TimeoutExpired repr containing command arguments.
        raise CatalogueError(f"could not {description}; command details were suppressed") from None
    if result.returncode:
        # The reader/build never needs the key, but suppress child output anyway:
        # build tools are allowed to echo their environment or full invocation.
        raise CatalogueError(f"failed to {description}; child output was suppressed")
    return result


def _check_runtime(dotnet: Path, environment: Mapping[str, str]) -> None:
    version = _run(
        [str(dotnet), "--version"],
        description="query the dotnet SDK",
        environment=environment,
        timeout=30,
    ).stdout.strip()
    match = re.match(r"^(\d+)\.", version)
    if not match or int(match.group(1)) < 9:
        raise CatalogueError(
            f"semantic extraction requires .NET SDK 9 or newer (found {version or 'unknown'})"
        )
    runtimes = _run(
        [str(dotnet), "--list-runtimes"],
        description="query installed dotnet runtimes",
        environment=environment,
        timeout=30,
    ).stdout
    if not re.search(r"^Microsoft\.NETCore\.App 9\.", runtimes, re.MULTILINE):
        raise CatalogueError(
            "semantic extraction requires the Microsoft.NETCore.App 9 runtime"
        )


def _source_metadata(project_dir: Path) -> tuple[str, str]:
    missing = [name for name in SOURCE_FILENAMES if not (project_dir / name).is_file()]
    if missing:
        raise CatalogueError(
            "semantic-reader source is incomplete: " + ", ".join(sorted(missing))
        )
    digests = {name: digest_file(project_dir / name) for name in SOURCE_FILENAMES}
    return digest_value(digests), digests["packages.lock.json"]


def _marker_document(
    dll: Path,
    *,
    source_digest: str,
    lock_digest: str,
) -> dict[str, object]:
    return {
        "dllDigest": digest_file(dll),
        "lockDigest": lock_digest,
        "name": READER_NAME,
        "packages": dict(sorted(PACKAGE_VERSIONS.items())),
        "schemaVersion": 1,
        "sourceDigest": source_digest,
        "targetFramework": TARGET_FRAMEWORK,
        "version": READER_VERSION,
    }


def _verify_reader(
    dotnet: Path,
    dll: Path,
    environment: Mapping[str, str],
) -> bool:
    if dll.is_symlink() or not dll.is_file():
        return False
    try:
        result = _run(
            [str(dotnet), str(dll), "--version"],
            description="verify the semantic reader",
            environment=environment,
            timeout=30,
        )
    except CatalogueError:
        return False
    return result.stdout.strip() == f"{READER_NAME} {READER_VERSION}"


def _assert_safe_tree(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_dir():
        raise CatalogueError(f"{label} must be a normal directory: {path}")
    for child in path.rglob("*"):
        if child.is_symlink():
            raise CatalogueError(f"{label} contains a symlink: {child.relative_to(path)}")


def _cache_is_current(
    cache: Path,
    dotnet: Path,
    environment: Mapping[str, str],
    *,
    source_digest: str,
    lock_digest: str,
) -> bool:
    if not cache.exists() and not cache.is_symlink():
        return False
    _assert_safe_tree(cache, "semantic-reader cache")
    marker = cache / MARKER_NAME
    dll = cache / "Afe2.SemanticReader.dll"
    if not marker.is_file() or marker.is_symlink():
        raise CatalogueError(
            f"semantic-reader cache is not managed by this repository: {cache}"
        )
    try:
        recorded = read_json(marker)
    except CatalogueError:
        return False
    if not isinstance(recorded, dict) or recorded.get("name") != READER_NAME:
        raise CatalogueError(
            f"semantic-reader cache is not managed by this repository: {cache}"
        )
    if not dll.is_file() or dll.is_symlink():
        return False
    try:
        expected = _marker_document(
            dll,
            source_digest=source_digest,
            lock_digest=lock_digest,
        )
    except CatalogueError:
        return False
    return recorded == expected and _verify_reader(dotnet, dll, environment)


@contextmanager
def _reader_lock(tools_root: Path) -> Iterator[None]:
    lock = tools_root / ".semantic-reader.lock"
    if lock.is_symlink():
        raise CatalogueError(f"semantic-reader lock must not be a symlink: {lock}")
    try:
        handle = lock.open("a+b")
    except OSError as exc:
        raise CatalogueError(f"could not open semantic-reader lock: {exc}") from None
    with handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _publish_cache(cache: Path, staged: Path) -> None:
    previous_root: Path | None = None
    previous: Path | None = None
    try:
        if cache.exists() or cache.is_symlink():
            _assert_safe_tree(cache, "semantic-reader cache")
            previous_root = Path(
                tempfile.mkdtemp(prefix=".semantic-reader-previous-", dir=cache.parent)
            )
            previous = previous_root / "cache"
            os.replace(cache, previous)
        try:
            os.replace(staged, cache)
        except Exception:
            if previous is not None and previous.exists() and not cache.exists():
                os.replace(previous, cache)
            raise
        if previous_root is not None:
            shutil.rmtree(previous_root)
    except OSError as exc:
        raise CatalogueError(f"could not publish semantic-reader cache: {exc}") from None


def ensure_semantic_reader(
    project_root: Path,
    *,
    progress: Progress | None = None,
    dotnet_executable: Path | str | None = None,
    secret_environment_names: Sequence[str] = (),
) -> ManagedSemanticReader:
    """Restore locked packages, build, verify, and cache the local reader."""

    root = project_root.expanduser().resolve()
    project_dir = root / "tools" / "semantic-reader"
    project = project_dir / "Afe2.SemanticReader.csproj"
    source_digest, lock_digest = _source_metadata(project_dir)
    tools_root = root / ".tools"
    if tools_root.is_symlink():
        raise CatalogueError(f"managed tools directory must not be a symlink: {tools_root}")
    try:
        tools_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise CatalogueError(f"could not create managed tools directory: {exc}") from None
    if not tools_root.is_dir():
        raise CatalogueError(f"managed tools path is not a directory: {tools_root}")

    dotnet = _program(dotnet_executable)
    environment = _environment(tools_root, secret_environment_names)
    _check_runtime(dotnet, environment)
    cache = tools_root / "semantic-reader"
    report = progress or (lambda _message: None)

    with _reader_lock(tools_root):
        if _cache_is_current(
            cache,
            dotnet,
            environment,
            source_digest=source_digest,
            lock_digest=lock_digest,
        ):
            report(f"Using cached {READER_NAME} {READER_VERSION} from {cache}")
            return ManagedSemanticReader(
                dotnet=dotnet,
                dll=cache / "Afe2.SemanticReader.dll",
                source_digest=source_digest,
                lock_digest=lock_digest,
                reused=True,
            )

        report(f"Building {READER_NAME} {READER_VERSION} from locked packages")
        with tempfile.TemporaryDirectory(
            prefix=".semantic-reader-staging-", dir=tools_root
        ) as temporary:
            staged = Path(temporary) / "publication"
            staged.mkdir()
            intermediate = Path(temporary) / "obj"
            base_output = Path(temporary) / "bin"
            package_cache = Path(temporary) / "packages"
            msbuild_paths = [
                "--property:BaseIntermediateOutputPath=" + str(intermediate) + os.sep,
                "--property:MSBuildProjectExtensionsPath=" + str(intermediate) + os.sep,
                "--property:BaseOutputPath=" + str(base_output) + os.sep,
            ]
            build_environment = dict(environment)
            build_environment["NUGET_PACKAGES"] = str(package_cache)
            _run(
                [
                    str(dotnet),
                    "restore",
                    str(project),
                    "--locked-mode",
                    "--packages",
                    str(package_cache),
                    *msbuild_paths,
                ],
                description="restore locked semantic-reader packages",
                environment=build_environment,
                timeout=900,
            )
            _run(
                [
                    str(dotnet),
                    "publish",
                    str(project),
                    "--configuration",
                    "Release",
                    "--no-restore",
                    "--no-self-contained",
                    "--output",
                    str(staged),
                    *msbuild_paths,
                ],
                description="build the semantic reader",
                environment=build_environment,
                timeout=900,
            )
            dll = staged / "Afe2.SemanticReader.dll"
            if not _verify_reader(dotnet, dll, environment):
                raise CatalogueError("built semantic reader did not report its pinned version")
            write_json_atomic(
                staged / MARKER_NAME,
                _marker_document(
                    dll,
                    source_digest=source_digest,
                    lock_digest=lock_digest,
                ),
            )
            _assert_safe_tree(staged, "staged semantic-reader cache")
            _publish_cache(cache, staged)

        if not _cache_is_current(
            cache,
            dotnet,
            environment,
            source_digest=source_digest,
            lock_digest=lock_digest,
        ):
            raise CatalogueError("could not verify the managed semantic-reader cache")
        report(f"Prepared {READER_NAME} {READER_VERSION} at {cache}")
        return ManagedSemanticReader(
            dotnet=dotnet,
            dll=cache / "Afe2.SemanticReader.dll",
            source_digest=source_digest,
            lock_digest=lock_digest,
            reused=False,
        )


__all__ = [
    "ManagedSemanticReader",
    "PACKAGE_VERSIONS",
    "READER_NAME",
    "READER_VERSION",
    "TARGET_FRAMEWORK",
    "ensure_semantic_reader",
]
