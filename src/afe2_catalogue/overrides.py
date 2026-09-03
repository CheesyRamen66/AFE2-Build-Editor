"""Auditable promotion and suppression of path-derived candidates."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from .errors import CatalogueError

KINDS = ("ability", "augment", "gridShape", "item", "kit", "mod", "perk", "trait", "weapon")
CATEGORY_BY_KIND = {
    "ability": "abilities",
    "augment": "augments",
    "gridShape": "gridShapes",
    "item": "items",
    "kit": "kits",
    "mod": "mods",
    "perk": "perks",
    "trait": "traits",
    "weapon": "weapons",
}


def _load(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogueError(f"could not read overrides: {path}") from exc
    if document.get("schemaVersion") != 1 or not isinstance(document.get("operations"), list):
        raise CatalogueError("override file must have schemaVersion 1 and an operations array")
    return document


def _replace_pointer(record: dict[str, Any], pointer: str, value: Any) -> None:
    if not pointer.startswith("/") or pointer == "/":
        raise CatalogueError(f"override has invalid JSON pointer: {pointer}")
    parts = [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]
    if any(part in {"id", "kind", "source"} for part in parts[:1]):
        raise CatalogueError(f"override cannot replace protected field: {pointer}")
    current: Any = record
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            raise CatalogueError(f"override replace target does not exist: {pointer}")
        current = current[part]
    if not isinstance(current, dict) or parts[-1] not in current:
        raise CatalogueError(f"override replace target does not exist: {pointer}")
    current[parts[-1]] = copy.deepcopy(value)


def apply_overrides(
    candidates: dict[str, Any],
    path: Path,
    *,
    build_id: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply explicit operations and return ``(catalogue, activity)``."""

    document = _load(path)
    candidate_map = {record["id"]: record for record in candidates.get("records", [])}
    promoted: dict[str, dict[str, Any]] = {}
    suppressed: set[str] = set()
    touched: set[tuple[str, str]] = set()
    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for index, operation in enumerate(document["operations"]):
        if not isinstance(operation, dict):
            raise CatalogueError(f"override operation {index} is not an object")
        op = operation.get("op")
        candidate_id = operation.get("candidateId")
        reason = operation.get("reason")
        builds = operation.get("buildIds")
        if not isinstance(candidate_id, str) or not isinstance(reason, str) or not reason.strip():
            raise CatalogueError(f"override operation {index} needs candidateId and reason")
        if builds is not None:
            if not isinstance(builds, list) or not all(isinstance(value, str) for value in builds):
                raise CatalogueError(f"override operation {index} has invalid buildIds")
            if build_id not in builds:
                skipped.append({"candidateId": candidate_id, "index": index, "reason": "build does not match"})
                continue
        candidate = candidate_map.get(candidate_id)
        if candidate is None:
            raise CatalogueError(f"override target is not a current candidate: {candidate_id}")

        if op == "promote":
            key = (candidate_id, "promote")
            if candidate_id in suppressed:
                raise CatalogueError(f"candidate cannot be both suppressed and promoted: {candidate_id}")
            if key in touched or candidate_id in promoted:
                raise CatalogueError(f"candidate is promoted more than once: {candidate_id}")
            fields = operation.get("record", {})
            if not isinstance(fields, dict):
                raise CatalogueError(f"promote record must be an object: {candidate_id}")
            if {"id", "kind", "source"}.intersection(fields):
                raise CatalogueError(f"promote record replaces a protected field: {candidate_id}")
            record = {
                "id": candidate_id,
                "kind": candidate["kind"],
                **copy.deepcopy(fields),
                "source": {
                    "candidateId": candidate_id,
                    "packagePath": candidate["packagePath"],
                    "resolution": "override",
                },
            }
            promoted[candidate_id] = record
            touched.add(key)
        elif op == "suppress":
            key = (candidate_id, "suppress")
            if candidate_id in promoted:
                raise CatalogueError(f"candidate cannot be both promoted and suppressed: {candidate_id}")
            if key in touched or candidate_id in suppressed:
                raise CatalogueError(f"candidate is suppressed more than once: {candidate_id}")
            suppressed.add(candidate_id)
            touched.add(key)
        elif op == "replace":
            pointer = operation.get("path")
            key = (candidate_id, str(pointer))
            if key in touched:
                raise CatalogueError(f"two overrides replace the same target: {candidate_id}{pointer}")
            if candidate_id not in promoted:
                raise CatalogueError(f"replace must follow promote for candidate: {candidate_id}")
            _replace_pointer(promoted[candidate_id], str(pointer), operation.get("value"))
            touched.add(key)
        else:
            raise CatalogueError(f"unsupported override operation: {op}")
        applied.append({"candidateId": candidate_id, "index": index, "op": op, "reason": reason})

    records = {category: [] for category in CATEGORY_BY_KIND.values()}
    for record in promoted.values():
        kind = record["kind"]
        if kind not in CATEGORY_BY_KIND:
            raise CatalogueError(f"candidate has unsupported kind: {kind}")
        records[CATEGORY_BY_KIND[kind]].append(record)
    for values in records.values():
        values.sort(key=lambda item: item["id"])

    catalogue = {
        "schemaVersion": 1,
        "game": {"steamAppId": "3448650", "buildId": build_id},
        "records": records,
    }
    activity = {
        "applied": applied,
        "skipped": skipped,
        "suppressedCandidateIds": sorted(suppressed),
        "promotedCandidateIds": sorted(promoted),
    }
    return catalogue, activity
