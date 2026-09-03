"""Deterministic catalogue diffs for game updates."""

from __future__ import annotations

from typing import Any

from .errors import CatalogueError


def _flatten(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    records = document.get("records", {})
    if not isinstance(records, dict):
        raise CatalogueError("catalogue has no records object")
    for kind, values in records.items():
        if not isinstance(values, list):
            raise CatalogueError(f"catalogue category is not an array: {kind}")
        for record in values:
            if not isinstance(record, dict) or not isinstance(record.get("id"), str):
                raise CatalogueError(f"catalogue category has an invalid record: {kind}")
            record_id = record["id"]
            if record_id in result:
                raise CatalogueError(f"catalogue contains duplicate ID: {record_id}")
            result[record_id] = record
    return result


def _field_changes(old: Any, new: Any, pointer: str = "") -> list[dict[str, Any]]:
    if old == new:
        return []
    if isinstance(old, dict) and isinstance(new, dict):
        changes: list[dict[str, Any]] = []
        for key in sorted(set(old) | set(new)):
            escaped = key.replace("~", "~0").replace("/", "~1")
            child = f"{pointer}/{escaped}"
            if key not in old:
                changes.append({"path": child, "before": None, "after": new[key]})
            elif key not in new:
                changes.append({"path": child, "before": old[key], "after": None})
            else:
                changes.extend(_field_changes(old[key], new[key], child))
        return changes
    return [{"path": pointer or "/", "before": old, "after": new}]


def diff_record_lists(
    old: list[dict[str, Any]] | None,
    new: list[dict[str, Any]],
) -> dict[str, Any]:
    def keyed(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for record in records:
            if not isinstance(record, dict) or not isinstance(record.get("id"), str):
                raise CatalogueError("record list contains an invalid record")
            if record["id"] in result:
                raise CatalogueError(f"record list contains duplicate ID: {record['id']}")
            result[record["id"]] = record
        return result

    old_records = keyed(old or [])
    new_records = keyed(new)
    old_ids = set(old_records)
    new_ids = set(new_records)
    return {
        "added": sorted(new_ids - old_ids),
        "changed": [
            {"id": record_id, "fields": _field_changes(old_records[record_id], new_records[record_id])}
            for record_id in sorted(old_ids & new_ids)
            if old_records[record_id] != new_records[record_id]
        ],
        "removed": sorted(old_ids - new_ids),
    }


def diff_catalogues(old: dict[str, Any] | None, new: dict[str, Any]) -> dict[str, Any]:
    old_records = _flatten(old) if old else {}
    new_records = _flatten(new)
    changes = diff_record_lists(list(old_records.values()), list(new_records.values()))
    return {
        "schemaVersion": 1,
        **changes,
    }
