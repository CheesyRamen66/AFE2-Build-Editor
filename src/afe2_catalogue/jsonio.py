"""Canonical JSON hashing and atomic output publication."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .errors import CatalogueError


PUBLICATION_MANIFEST = "publication.json"
PUBLICATION_PRODUCER = "afe2-catalogue"


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def digest_value(value: Any) -> str:
    return f"sha256:{hashlib.sha256(canonical_bytes(value)).hexdigest()}"


def digest_file(path: Path) -> str:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise CatalogueError(f"could not hash input file: {path}") from exc
    return f"sha256:{digest.hexdigest()}"


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogueError(f"could not read JSON: {path}") from exc


def write_json_atomic(path: Path, document: Any) -> None:
    """Atomically write one explicit JSON file without replacing its directory."""

    original_path = path.expanduser()
    if original_path.is_symlink():
        raise CatalogueError(f"JSON output is not a regular file: {original_path}")
    path = original_path.resolve()
    if path.suffix.casefold() != ".json":
        raise CatalogueError("JSON output filename must end in .json")
    if path.exists() and (path.is_dir() or path.is_symlink()):
        raise CatalogueError(f"JSON output is not a regular file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_bytes(document))
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _publication_document(payloads: Mapping[str, bytes]) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "producer": PUBLICATION_PRODUCER,
        "files": [
            {
                "name": name,
                "sha256": f"sha256:{hashlib.sha256(payload).hexdigest()}",
                "sizeBytes": len(payload),
            }
            for name, payload in sorted(payloads.items())
        ],
    }


def _safe_publication_name(name: str) -> str:
    """Validate and return one canonical, POSIX-style publication path."""

    if not isinstance(name, str) or not name or "\\" in name or "\0" in name:
        raise CatalogueError(f"unsafe generated filename: {name}")
    try:
        name.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise CatalogueError("unsafe generated filename contained invalid Unicode") from exc
    relative = PurePosixPath(name)
    if (
        relative.is_absolute()
        or relative == PurePosixPath(".")
        or not relative.parts
        or relative.as_posix() != name
        or any(part in {"", ".", ".."} for part in relative.parts)
        or relative.parts[0] == PUBLICATION_MANIFEST
    ):
        raise CatalogueError(f"unsafe generated filename: {name}")
    return name


def _tree_entries(root: Path) -> tuple[dict[str, Path], set[str]]:
    """Return regular files and directories without following any symlinks."""

    files: dict[str, Path] = {}
    directories: set[str] = set()
    pending: list[tuple[Path, PurePosixPath | None]] = [(root, None)]
    while pending:
        directory, relative_directory = pending.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name)
        except OSError as exc:
            raise CatalogueError(f"could not inspect generated publication: {root}") from exc
        for entry in entries:
            relative = (
                PurePosixPath(entry.name)
                if relative_directory is None
                else relative_directory / entry.name
            )
            name = relative.as_posix()
            try:
                mode = entry.stat(follow_symlinks=False).st_mode
            except OSError as exc:
                raise CatalogueError(
                    f"could not inspect generated publication entry: {name}"
                ) from exc
            if stat.S_ISLNK(mode):
                raise CatalogueError(f"generated publication contains a symlink: {name}")
            if stat.S_ISDIR(mode):
                directories.add(name)
                pending.append((Path(entry.path), relative))
            elif stat.S_ISREG(mode):
                files[name] = Path(entry.path)
            else:
                raise CatalogueError(
                    f"generated publication contains an unsafe entry: {name}"
                )
    return files, directories


def _expected_directories(filenames: set[str]) -> set[str]:
    expected: set[str] = set()
    for name in filenames:
        parent = PurePosixPath(name).parent
        while parent != PurePosixPath("."):
            expected.add(parent.as_posix())
            parent = parent.parent
    return expected


def _managed_filenames(output: Path) -> set[str]:
    """Validate that an existing directory is wholly owned by this publisher."""

    entries, directories = _tree_entries(output)

    marker = entries.get(PUBLICATION_MANIFEST)
    if marker is None:
        raise CatalogueError(
            "refusing to replace output without an afe2-catalogue publication marker"
        )

    publication = read_json(marker)
    if (
        not isinstance(publication, dict)
        or set(publication) != {"schemaVersion", "producer", "files"}
        or type(publication.get("schemaVersion")) is not int
        or publication.get("schemaVersion") != 1
        or publication.get("producer") != PUBLICATION_PRODUCER
    ):
        raise CatalogueError("generated publication marker was malformed")
    files = publication.get("files")
    if not isinstance(files, list):
        raise CatalogueError("generated publication marker was malformed")

    declared: set[str] = set()
    for record in files:
        if not isinstance(record, dict) or set(record) != {"name", "sha256", "sizeBytes"}:
            raise CatalogueError("generated publication marker was malformed")
        try:
            name = _safe_publication_name(record.get("name"))
        except CatalogueError as exc:
            raise CatalogueError("generated publication marker was malformed") from exc
        size = record.get("sizeBytes")
        expected_hash = record.get("sha256")
        if (
            name in declared
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or not isinstance(expected_hash, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", expected_hash) is None
        ):
            raise CatalogueError("generated publication marker was malformed")
        declared.add(name)
        path = entries.get(name)
        if path is None:
            raise CatalogueError("generated publication does not match its marker")
        try:
            actual_size = path.stat().st_size
        except OSError as exc:
            raise CatalogueError(f"could not inspect generated file: {name}") from exc
        if actual_size != size or digest_file(path) != expected_hash:
            raise CatalogueError(f"generated file failed publication integrity check: {name}")

    expected = declared | {PUBLICATION_MANIFEST}
    expected_directories = _expected_directories(expected)
    if set(entries) != expected or directories != expected_directories:
        unexpected = (
            sorted((set(entries) - expected) | (directories - expected_directories))
            or sorted((expected - set(entries)) | (expected_directories - directories))
        )
        raise CatalogueError(
            f"refusing to replace output containing unexpected entries: {', '.join(unexpected)}"
        )
    return expected


def _snapshot_digest(root: Path) -> str:
    files, directories = _tree_entries(root)
    if directories != _expected_directories(set(files)):
        raise CatalogueError("archive snapshot contains unexpected directories")
    digest = hashlib.sha256()
    digest.update(b"afe2-catalogue-snapshot-v2\0")
    digest.update(len(files).to_bytes(8, "big"))
    for relative_name, path in sorted(files.items()):
        name = relative_name.encode("utf-8")
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise CatalogueError(f"could not inspect archive entry: {relative_name}") from exc
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(size.to_bytes(8, "big"))
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    return digest.hexdigest()


def _archive_build_label(output: Path) -> str:
    try:
        manifest = read_json(output / "source-manifest.json")
    except CatalogueError:
        return "unknown-build"
    game = manifest.get("game") if isinstance(manifest, dict) else None
    build_id = game.get("buildId") if isinstance(game, dict) else None
    value = str(build_id) if build_id is not None and build_id != "" else "unknown-build"
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return normalized[:64] or "unknown-build"


def _archive_destination(archive_root: Path, output: Path) -> tuple[Path, bool]:
    """Return a collision-safe content-addressed archive path and reuse status."""

    snapshot_digest = _snapshot_digest(output)
    base = f"build-{_archive_build_label(output)}--sha256-{snapshot_digest}"
    suffix = 0
    while True:
        name = base if suffix == 0 else f"{base}-{suffix:02d}"
        candidate = archive_root / name
        if not candidate.exists() and not candidate.is_symlink():
            return candidate, False
        if candidate.is_dir() and not candidate.is_symlink():
            try:
                _managed_filenames(candidate)
                if _snapshot_digest(candidate) == snapshot_digest:
                    return candidate, True
            except CatalogueError:
                pass
        suffix += 1


def _temporary_previous(output: Path) -> tuple[Path, Path]:
    root = Path(tempfile.mkdtemp(prefix=f".{output.name}.previous-", dir=output.parent))
    return root, root / "output"


def publish_documents(
    output: Path,
    documents: Mapping[str, Any],
    *,
    archive_root: Path | None = None,
    binary_files: Mapping[str, bytes] | None = None,
) -> Path | None:
    """Replace a managed output directory and optionally retain its prior snapshot.

    All new bytes are staged before the previous publication is moved. A handled
    install failure restores the previous directory. The returned path identifies
    the retained previous snapshot, or is ``None`` on a first publication or when
    archiving is disabled.
    """

    original_output = output.expanduser()
    if original_output.is_symlink():
        raise CatalogueError(f"refusing symlink output directory: {original_output}")
    output = original_output.resolve()
    filesystem_root = Path(output.anchor)
    if output in {filesystem_root, Path.home().resolve()} or (output / ".git").exists():
        raise CatalogueError(f"refusing unsafe output directory: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    resolved_archive_root: Path | None = None
    if archive_root is not None:
        original_archive_root = archive_root.expanduser()
        if original_archive_root.is_symlink():
            raise CatalogueError(f"refusing symlink archive directory: {original_archive_root}")
        resolved_archive_root = original_archive_root.resolve()
        archive_filesystem_root = Path(resolved_archive_root.anchor)
        if resolved_archive_root in {archive_filesystem_root, Path.home().resolve()}:
            raise CatalogueError(f"refusing unsafe archive directory: {resolved_archive_root}")
        if (
            resolved_archive_root == output
            or resolved_archive_root.is_relative_to(output)
            or output.is_relative_to(resolved_archive_root)
        ):
            raise CatalogueError("archive directory and output directory must not contain each other")

    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent))
    temporary_previous_root: Path | None = None
    previous: Path | None = None
    archived: Path | None = None
    try:
        payloads: dict[str, bytes] = {}
        for name, document in sorted(documents.items()):
            name = _safe_publication_name(name)
            if not name.endswith(".json"):
                raise CatalogueError(f"JSON generated filename must end in .json: {name}")
            payloads[name] = canonical_bytes(document)
        for name, payload in sorted((binary_files or {}).items()):
            name = _safe_publication_name(name)
            if name in payloads:
                raise CatalogueError(f"duplicate generated filename: {name}")
            if not isinstance(payload, bytes):
                raise CatalogueError(f"binary generated payload must be bytes: {name}")
            payloads[name] = payload
        filenames = set(payloads)
        for name in filenames:
            parts = PurePosixPath(name).parts
            for index in range(1, len(parts)):
                if PurePosixPath(*parts[:index]).as_posix() in filenames:
                    raise CatalogueError(f"generated file and directory paths collide: {name}")
        for name, payload in sorted(payloads.items()):
            destination = staging.joinpath(*PurePosixPath(name).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
        (staging / PUBLICATION_MANIFEST).write_bytes(
            canonical_bytes(_publication_document(payloads))
        )

        if output.exists():
            if output.is_symlink() or not output.is_dir():
                raise CatalogueError(f"output exists and is not a directory: {output}")
            _managed_filenames(output)
            if resolved_archive_root is not None:
                resolved_archive_root.mkdir(parents=True, exist_ok=True)
                if resolved_archive_root.stat().st_dev != output.parent.stat().st_dev:
                    raise CatalogueError(
                        "archive directory must be on the same filesystem as the output"
                    )
                archive_destination, already_archived = _archive_destination(
                    resolved_archive_root, output
                )
                archived = archive_destination
                if already_archived:
                    temporary_previous_root, previous = _temporary_previous(output)
                else:
                    previous = archive_destination
            else:
                temporary_previous_root, previous = _temporary_previous(output)
            os.replace(output, previous)

        try:
            os.replace(staging, output)
        except Exception as install_error:
            if previous is not None and previous.exists() and not output.exists():
                try:
                    os.replace(previous, output)
                except Exception as rollback_error:
                    raise CatalogueError(
                        "could not install or restore the catalogue; "
                        f"the previous publication remains at {previous}"
                    ) from rollback_error
            raise install_error

        if temporary_previous_root is not None and temporary_previous_root.exists():
            try:
                shutil.rmtree(temporary_previous_root)
            except OSError:
                # Publication already succeeded. A uniquely named recoverable
                # old-output copy is preferable to reporting a false failure.
                pass
        return archived
    except Exception:
        if staging.exists():
            try:
                shutil.rmtree(staging)
            except OSError:
                pass
        if (
            temporary_previous_root is not None
            and temporary_previous_root.exists()
            and previous is not None
            and not previous.exists()
        ):
            try:
                shutil.rmtree(temporary_previous_root)
            except OSError:
                pass
        raise
