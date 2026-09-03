"""Read-only adapters for AFE2's IoStore and PAK archive indexes."""

from __future__ import annotations

import json
import tempfile
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .errors import CatalogueError
from .tools import run_secret_command, tool_version


def _normal_path(value: str) -> str:
    value = unicodedata.normalize("NFC", value.replace("\\", "/"))
    while value.startswith("../"):
        value = value[3:]
    return str(PurePosixPath(value))


def validate_retoc_key(retoc: Path, encrypted_utoc: Path, key: str) -> bool:
    result = run_secret_command(
        [str(retoc), "--aes-key", key, "info", str(encrypted_utoc)],
        secret=key,
        timeout=45,
    )
    output = f"{result.stdout}\n{result.stderr}".lower()
    return result.returncode == 0 and "container_id" in output


def validate_repak_key(repak: Path, encrypted_pak: Path, key: str) -> bool:
    result = run_secret_command(
        [str(repak), "--aes-key", key, "info", str(encrypted_pak)],
        secret=key,
        timeout=45,
    )
    output = f"{result.stdout}\n{result.stderr}".lower()
    return result.returncode == 0 and "version" in output


def parse_retoc_manifest(document: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """Normalize retoc's ``pakstore.json`` into a stable package index."""

    entries = document.get("oplog", {}).get("entries")
    if not isinstance(entries, list):
        raise CatalogueError("retoc manifest did not contain oplog.entries")

    merged: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            warnings.append(f"manifest entry {index} was not an object")
            continue
        store = entry.get("packagestoreentry")
        package_path = store.get("packagename") if isinstance(store, dict) else None
        if not isinstance(package_path, str) or not package_path.startswith("/"):
            warnings.append(f"manifest entry {index} had no absolute package name")
            continue
        package_path = unicodedata.normalize("NFC", package_path.replace("\\", "/"))
        chunks: list[dict[str, str]] = []
        for field, kind in (("packagedata", "package"), ("bulkdata", "bulk")):
            values = entry.get(field, [])
            if not isinstance(values, list):
                warnings.append(f"{package_path} had malformed {field}")
                continue
            for chunk in values:
                if not isinstance(chunk, dict):
                    continue
                chunk_id = chunk.get("id")
                filename = chunk.get("filename")
                if isinstance(chunk_id, str) and isinstance(filename, str):
                    chunks.append(
                        {
                            "chunkId": chunk_id.lower(),
                            "kind": kind,
                            "memberPath": _normal_path(filename),
                        }
                    )
        chunks.sort(key=lambda item: (item["kind"], item["memberPath"], item["chunkId"]))
        current = merged.get(package_path)
        if current:
            current_chunks = {json.dumps(value, sort_keys=True): value for value in current["chunks"]}
            for chunk in chunks:
                current_chunks[json.dumps(chunk, sort_keys=True)] = chunk
            current["chunks"] = sorted(
                current_chunks.values(),
                key=lambda item: (item["kind"], item["memberPath"], item["chunkId"]),
            )
            current["occurrences"] += 1
        else:
            merged[package_path] = {
                "packagePath": package_path,
                "chunks": chunks,
                "occurrences": 1,
            }

    return sorted(merged.values(), key=lambda item: item["packagePath"]), sorted(warnings)


def scan_iostore(paks_dir: Path, retoc: Path, key: str) -> dict[str, Any]:
    """Run retoc's directory manifest export in a disposable directory."""

    with tempfile.TemporaryDirectory(prefix="afe2-catalogue-retoc-") as temporary:
        work = Path(temporary)
        result = run_secret_command(
            [str(retoc), "--aes-key", key, "manifest", str(paks_dir)],
            secret=key,
            cwd=work,
            timeout=300,
        )
        manifest = work / "pakstore.json"
        if result.returncode or not manifest.is_file():
            raise CatalogueError("retoc could not export the IoStore package manifest")
        try:
            document = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CatalogueError("retoc produced an unreadable package manifest") from exc
        packages, warnings = parse_retoc_manifest(document)
    return {
        "adapter": {"name": "retoc", "version": tool_version(retoc)},
        "packages": packages,
        "warnings": warnings,
    }


def parse_repak_list(output: str) -> list[str]:
    paths: set[str] = set()
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        normalized = line.replace("\\", "/")
        parsed = PurePosixPath(normalized)
        if parsed.is_absolute() or ".." in parsed.parts or parsed.parts[:1] in {(".",), ()}:
            raise CatalogueError("repak emitted an unsafe archive member path")
        path = unicodedata.normalize("NFC", str(parsed))
        paths.add(path)
    return sorted(paths)


def scan_paks(pak_paths: Iterable[Path], repak: Path, key: str, game_dir: Path) -> dict[str, Any]:
    members: list[dict[str, str]] = []
    failures: list[dict[str, str]] = []
    for pak in sorted(pak_paths, key=lambda value: value.name.casefold()):
        result = run_secret_command(
            [str(repak), "--aes-key", key, "list", str(pak)],
            secret=key,
            timeout=300,
        )
        relative = pak.relative_to(game_dir).as_posix()
        if result.returncode:
            failures.append({"archive": relative, "reason": "repak list failed"})
            continue
        try:
            listed = parse_repak_list(result.stdout)
        except CatalogueError:
            failures.append({"archive": relative, "reason": "repak list was malformed"})
            continue
        members.extend({"archive": relative, "memberPath": path} for path in listed)
    members.sort(key=lambda item: (item["archive"], item["memberPath"]))
    return {
        "adapter": {"name": "repak", "version": tool_version(repak)},
        "members": members,
        "failures": failures,
    }
