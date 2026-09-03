"""Pinned, repository-local retoc and repak source builds."""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Mapping, Sequence

from .errors import CatalogueError
from .jsonio import digest_file, read_json, write_json_atomic
from .tools import tool_identity

try:  # The extractor targets Linux, but keep imports usable on other hosts.
    import fcntl
except ImportError:  # pragma: no cover - exercised only on non-POSIX hosts
    fcntl = None  # type: ignore[assignment]


@dataclass(frozen=True)
class ToolSpec:
    """Immutable upstream source and build details for one archive tool."""

    name: str
    repository: str
    tag: str
    revision: str
    version: str
    cargo_package: str
    binary_name: str


@dataclass(frozen=True)
class ManagedTool:
    """A verified managed checkout and executable."""

    spec: ToolSpec
    checkout: Path
    binary: Path
    reused: bool

    def adapter_provenance(self) -> dict[str, str]:
        return {
            "repository": self.spec.repository,
            "revision": self.spec.revision,
            "tag": self.spec.tag,
        }


RETOC_SPEC = ToolSpec(
    name="retoc",
    repository="https://github.com/trumank/retoc.git",
    tag="v0.1.5",
    revision="d034ade1ae8117d4786eaf6b0418d4cf48474d7f",
    version="0.1.5",
    cargo_package="retoc_cli",
    binary_name="retoc",
)

REPAK_SPEC = ToolSpec(
    name="repak",
    repository="https://github.com/trumank/repak.git",
    tag="v0.2.3",
    revision="e215472c51db69328b1ce77be2db24d24c1d646b",
    version="0.2.3",
    cargo_package="repak_cli",
    binary_name="repak",
)

TOOL_SPECS: Mapping[str, ToolSpec] = {
    RETOC_SPEC.name: RETOC_SPEC,
    REPAK_SPEC.name: REPAK_SPEC,
}

Progress = Callable[[str], None]
_MARKER_NAME = ".afe2-managed-tool.json"
_CARGO_HOST = re.compile(
    r"^host:[ \t]*(?P<host>[A-Za-z0-9][A-Za-z0-9_.-]*)[ \t]*$",
    re.MULTILINE,
)


def _program(name: str, explicit: Path | str | None) -> Path:
    candidate = str(explicit) if explicit is not None else shutil.which(name)
    if not candidate:
        raise CatalogueError(
            f"{name} is required to prepare the managed archive tools; install it and retry"
        )
    path = Path(candidate).expanduser().resolve()
    if not path.is_file():
        raise CatalogueError(f"{name} executable does not exist: {path}")
    return path


def _run(
    arguments: Sequence[str],
    *,
    description: str,
    cwd: Path | None = None,
    environment: Mapping[str, str] | None = None,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            list(arguments),
            cwd=cwd,
            env=dict(environment) if environment is not None else None,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except OSError as exc:
        raise CatalogueError(f"could not {description}: {exc}") from None
    except subprocess.TimeoutExpired:
        raise CatalogueError(f"timed out while trying to {description}") from None
    if result.returncode:
        combined = "\n".join(part for part in (result.stdout, result.stderr) if part)
        lines = [line.rstrip() for line in combined.splitlines() if line.strip()]
        detail = "\n".join(lines[-20:])
        suffix = f"\n{detail[-4000:]}" if detail else ""
        raise CatalogueError(f"failed to {description}{suffix}")
    return result


def _managed_environment(
    secret_environment_names: Sequence[str],
    *,
    for_git: bool = False,
) -> dict[str, str]:
    environment = os.environ.copy()
    for name in {"AFE2_AES_KEY", *secret_environment_names}:
        if name:
            environment.pop(name, None)
    if not for_git:
        return environment
    for name in {
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_DIR",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_WORK_TREE",
    }:
        environment.pop(name, None)
    return environment


def _cargo_host(cargo: Path, environment: Mapping[str, str]) -> str:
    result = _run(
        [str(cargo), "-Vv"],
        description="determine Cargo's host target",
        environment=environment,
        timeout=30,
    )
    match = _CARGO_HOST.search(f"{result.stdout}\n{result.stderr}")
    if not match:
        raise CatalogueError("could not determine Cargo's host target from cargo -Vv")
    return match.group("host")


@contextmanager
def _bootstrap_lock(tools_root: Path) -> Iterator[None]:
    lock_path = tools_root / ".bootstrap.lock"
    if lock_path.is_symlink():
        raise CatalogueError(f"managed-tools lock must not be a symlink: {lock_path}")
    try:
        handle = lock_path.open("a+b")
    except OSError as exc:
        raise CatalogueError(f"could not open managed-tools lock {lock_path}: {exc}") from None
    with handle:
        if fcntl is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            except OSError as exc:
                raise CatalogueError(f"could not lock managed tools: {exc}") from None
        try:
            yield
        finally:
            if fcntl is not None:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass


def _git_value(
    git: Path,
    checkout: Path,
    arguments: Sequence[str],
    *,
    description: str,
    environment: Mapping[str, str],
) -> str:
    result = _run(
        [str(git), "-C", str(checkout), *arguments],
        description=description,
        environment=environment,
        timeout=30,
    )
    return result.stdout.strip()


def _validate_checkout(
    git: Path,
    checkout: Path,
    spec: ToolSpec,
    environment: Mapping[str, str],
) -> None:
    if checkout.is_symlink():
        raise CatalogueError(f"managed {spec.name} checkout must not be a symlink: {checkout}")
    git_directory = checkout / ".git"
    if (
        not checkout.is_dir()
        or git_directory.is_symlink()
        or not git_directory.is_dir()
    ):
        raise CatalogueError(
            f"managed {spec.name} path is not the expected Git checkout: {checkout}; "
            "move or remove it, then retry"
        )

    remote = _git_value(
        git,
        checkout,
        ["remote", "get-url", "origin"],
        description=f"read the {spec.name} checkout remote",
        environment=environment,
    )
    if remote != spec.repository:
        raise CatalogueError(
            f"managed {spec.name} checkout has an unexpected origin ({remote!r}): {checkout}; "
            "it was left unchanged"
        )

    revision = _git_value(
        git,
        checkout,
        ["rev-parse", "--verify", "HEAD^{commit}"],
        description=f"read the {spec.name} checkout revision",
        environment=environment,
    ).lower()
    if revision != spec.revision:
        raise CatalogueError(
            f"managed {spec.name} checkout is at {revision}, expected {spec.revision}: {checkout}; "
            "it was left unchanged"
        )

    status = _git_value(
        git,
        checkout,
        ["status", "--porcelain=v1", "--untracked-files=all"],
        description=f"inspect the {spec.name} checkout",
        environment=environment,
    )
    if status:
        raise CatalogueError(
            f"managed {spec.name} checkout has local changes: {checkout}; it was left unchanged"
        )


def _clone_checkout(
    git: Path,
    tools_root: Path,
    checkout: Path,
    spec: ToolSpec,
    progress: Progress,
    environment: Mapping[str, str],
) -> None:
    progress(f"Cloning {spec.name} {spec.tag} into {checkout}")
    try:
        with tempfile.TemporaryDirectory(
            prefix=f".{spec.name}-clone-", dir=tools_root
        ) as temporary:
            staged = Path(temporary) / "checkout"
            _run(
                [
                    str(git),
                    "clone",
                    "--depth",
                    "1",
                    "--single-branch",
                    "--branch",
                    spec.tag,
                    spec.repository,
                    str(staged),
                ],
                description=f"clone {spec.name} {spec.tag}",
                environment=environment,
                timeout=300,
            )
            _validate_checkout(git, staged, spec, environment)
            if checkout.exists() or checkout.is_symlink():
                raise CatalogueError(
                    f"managed {spec.name} checkout appeared while cloning: {checkout}; "
                    "it was left unchanged"
                )
            staged.replace(checkout)
    except CatalogueError:
        raise
    except OSError as exc:
        raise CatalogueError(f"could not publish managed {spec.name} checkout: {exc}") from None


def _validate_build_layout(checkout: Path, spec: ToolSpec) -> tuple[Path, Path, Path]:
    target = checkout / "target"
    release = target / "release"
    binary = release / spec.binary_name
    for label, path in (("target", target), ("release", release)):
        if path.is_symlink():
            raise CatalogueError(
                f"managed {spec.name} {label} directory must not be a symlink: {path}"
            )
        if path.exists() and not path.is_dir():
            raise CatalogueError(
                f"managed {spec.name} {label} path is not a directory: {path}"
            )
    return binary, release / _MARKER_NAME, target


def _binary_reports_expected(
    binary: Path,
    spec: ToolSpec,
    environment: Mapping[str, str],
) -> bool:
    if binary.is_symlink():
        raise CatalogueError(f"managed {spec.name} executable must not be a symlink: {binary}")
    if not binary.exists():
        return False
    if not binary.is_file():
        raise CatalogueError(f"managed {spec.name} executable is not a file: {binary}")
    try:
        return tool_identity(binary, environment=environment) == (
            spec.cargo_package,
            spec.version,
        )
    except CatalogueError:
        return False


def _marker_document(binary: Path, spec: ToolSpec) -> dict[str, object]:
    return {
        "binaryDigest": digest_file(binary),
        "binaryName": spec.binary_name,
        "cargoPackage": spec.cargo_package,
        "repository": spec.repository,
        "revision": spec.revision,
        "schemaVersion": 2,
        "tag": spec.tag,
        "version": spec.version,
    }


def _binary_is_current(
    binary: Path,
    marker: Path,
    spec: ToolSpec,
    environment: Mapping[str, str],
) -> bool:
    if marker.is_symlink():
        raise CatalogueError(f"managed {spec.name} build marker must not be a symlink: {marker}")
    if not marker.exists():
        return False
    if not marker.is_file():
        raise CatalogueError(f"managed {spec.name} build marker is not a file: {marker}")
    try:
        recorded = read_json(marker)
    except CatalogueError:
        return False
    if binary.is_symlink():
        raise CatalogueError(f"managed {spec.name} executable must not be a symlink: {binary}")
    if not binary.exists():
        return False
    if not binary.is_file():
        raise CatalogueError(f"managed {spec.name} executable is not a file: {binary}")
    try:
        expected_marker = _marker_document(binary, spec)
    except CatalogueError:
        return False
    if recorded != expected_marker:
        return False
    return _binary_reports_expected(binary, spec, environment)


def _built_artifact(target: Path, host: str, spec: ToolSpec) -> Path:
    platform = target / host
    release = platform / "release"
    for label, path in (("target platform", platform), ("artifact release", release)):
        if path.is_symlink():
            raise CatalogueError(f"managed {spec.name} {label} must not be a symlink: {path}")
        if not path.is_dir():
            raise CatalogueError(f"managed {spec.name} {label} is not a directory: {path}")
    artifact = release / spec.binary_name
    if artifact.is_symlink() or not artifact.is_file():
        raise CatalogueError(f"managed {spec.name} build artifact is not a regular file: {artifact}")
    return artifact


def _clear_host_target(target: Path, host: str, spec: ToolSpec) -> None:
    platform = target / host
    if platform.is_symlink():
        raise CatalogueError(f"managed {spec.name} target platform must not be a symlink: {platform}")
    if not platform.exists():
        return
    if not platform.is_dir():
        raise CatalogueError(f"managed {spec.name} target platform is not a directory: {platform}")
    try:
        shutil.rmtree(platform)
    except OSError as exc:
        raise CatalogueError(f"could not clear stale managed {spec.name} build cache: {exc}") from None


def _promote_built_binary(artifact: Path, binary: Path, spec: ToolSpec) -> None:
    temporary: Path | None = None
    descriptor: int | None = None
    try:
        binary.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{spec.binary_name}.bootstrap-",
            dir=binary.parent,
        )
        temporary = Path(temporary_name)
        artifact_mode = stat.S_IMODE(artifact.stat().st_mode)
        with artifact.open("rb") as source, os.fdopen(descriptor, "wb") as destination:
            descriptor = None
            shutil.copyfileobj(source, destination, length=1024 * 1024)
            os.fchmod(destination.fileno(), artifact_mode)
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary, binary)
    except OSError as exc:
        raise CatalogueError(f"could not publish managed {spec.name} executable: {exc}") from None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _build_tool(
    cargo: Path,
    checkout: Path,
    binary: Path,
    marker: Path,
    target: Path,
    spec: ToolSpec,
    progress: Progress,
    environment: Mapping[str, str],
    host: str,
) -> None:
    if marker.is_symlink():
        raise CatalogueError(f"managed {spec.name} build marker must not be a symlink: {marker}")
    if marker.exists():
        if not marker.is_file():
            raise CatalogueError(f"managed {spec.name} build marker is not a file: {marker}")
        try:
            marker.unlink()
        except OSError as exc:
            raise CatalogueError(f"could not replace managed {spec.name} build marker: {exc}") from None
    if binary.is_symlink():
        raise CatalogueError(f"managed {spec.name} executable must not be a symlink: {binary}")
    if binary.exists():
        if not binary.is_file():
            raise CatalogueError(f"managed {spec.name} executable is not a file: {binary}")
        try:
            binary.unlink()
        except OSError as exc:
            raise CatalogueError(f"could not replace managed {spec.name} executable: {exc}") from None

    progress(f"Building {spec.name} {spec.tag} (the first build may take several minutes)")
    environment = dict(environment)
    environment["CARGO_TERM_COLOR"] = "never"
    environment.pop("CARGO_BUILD_TARGET", None)
    _clear_host_target(target, host, spec)
    _run(
        [
            str(cargo),
            "build",
            "--manifest-path",
            str(checkout / "Cargo.toml"),
            "--target-dir",
            str(target),
            "--release",
            "--locked",
            "--target",
            host,
            "--package",
            spec.cargo_package,
            "--bin",
            spec.binary_name,
        ],
        description=f"build {spec.name} {spec.tag} with Cargo",
        cwd=checkout,
        environment=environment,
        timeout=3600,
    )
    validated_binary, validated_marker, _ = _validate_build_layout(checkout, spec)
    if validated_binary != binary or validated_marker != marker:
        raise CatalogueError(f"managed {spec.name} build layout changed unexpectedly")
    artifact = _built_artifact(target, host, spec)
    if not _binary_reports_expected(artifact, spec, environment):
        raise CatalogueError(
            f"managed {spec.name} build did not produce {spec.cargo_package} {spec.version}: {artifact}"
        )
    _promote_built_binary(artifact, binary, spec)
    validated_binary, validated_marker, _ = _validate_build_layout(checkout, spec)
    if validated_binary != binary or validated_marker != marker:
        raise CatalogueError(f"managed {spec.name} canonical build layout changed unexpectedly")
    if not _binary_reports_expected(binary, spec, environment):
        raise CatalogueError(f"could not verify the published managed {spec.name} executable")


def _ensure_one(
    *,
    tools_root: Path,
    spec: ToolSpec,
    git: Path,
    cargo_executable: Path | str | None,
    progress: Progress,
    git_environment: Mapping[str, str],
    build_environment: Mapping[str, str],
) -> ManagedTool:
    checkout = tools_root / spec.name
    if not checkout.exists() and not checkout.is_symlink():
        _clone_checkout(git, tools_root, checkout, spec, progress, git_environment)
    _validate_checkout(git, checkout, spec, git_environment)

    binary, marker, target = _validate_build_layout(checkout, spec)
    if _binary_is_current(binary, marker, spec, build_environment):
        progress(f"Using cached {spec.name} {spec.version} from {binary}")
        return ManagedTool(spec=spec, checkout=checkout, binary=binary, reused=True)

    cargo = _program("cargo", cargo_executable)
    host = _cargo_host(cargo, build_environment)
    _build_tool(
        cargo,
        checkout,
        binary,
        marker,
        target,
        spec,
        progress,
        build_environment,
        host,
    )
    _validate_checkout(git, checkout, spec, git_environment)
    try:
        write_json_atomic(marker, _marker_document(binary, spec))
    except OSError as exc:
        raise CatalogueError(f"could not record managed {spec.name} build: {exc}") from None
    if not _binary_is_current(binary, marker, spec, build_environment):
        raise CatalogueError(f"could not verify the managed {spec.name} build cache")
    progress(f"Prepared {spec.name} {spec.version} at {binary}")
    return ManagedTool(spec=spec, checkout=checkout, binary=binary, reused=False)


def ensure_managed_tools(
    project_root: Path,
    names: Sequence[str] = ("retoc", "repak"),
    *,
    progress: Progress | None = None,
    specs: Mapping[str, ToolSpec] = TOOL_SPECS,
    git_executable: Path | str | None = None,
    cargo_executable: Path | str | None = None,
    secret_environment_names: Sequence[str] = (),
) -> dict[str, ManagedTool]:
    """Clone, verify, build, and return the requested pinned archive tools."""

    requested = tuple(dict.fromkeys(names))
    unknown = sorted(set(requested) - set(specs))
    if unknown:
        raise CatalogueError(f"unknown managed archive tool(s): {', '.join(unknown)}")
    if not requested:
        return {}

    root = project_root.expanduser().resolve()
    tools_root = root / ".tools"
    if tools_root.is_symlink():
        raise CatalogueError(f"managed tools directory must not be a symlink: {tools_root}")
    try:
        tools_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise CatalogueError(f"could not create managed tools directory {tools_root}: {exc}") from None
    if not tools_root.is_dir():
        raise CatalogueError(f"managed tools path is not a directory: {tools_root}")

    report = progress or (lambda _message: None)
    git = _program("git", git_executable)
    git_environment = _managed_environment(secret_environment_names, for_git=True)
    build_environment = _managed_environment(secret_environment_names)
    managed: dict[str, ManagedTool] = {}
    with _bootstrap_lock(tools_root):
        for name in requested:
            managed[name] = _ensure_one(
                tools_root=tools_root,
                spec=specs[name],
                git=git,
                cargo_executable=cargo_executable,
                progress=report,
                git_environment=git_environment,
                build_environment=build_environment,
            )
    return managed


__all__ = [
    "ManagedTool",
    "REPAK_SPEC",
    "RETOC_SPEC",
    "TOOL_SPECS",
    "ToolSpec",
    "ensure_managed_tools",
]
