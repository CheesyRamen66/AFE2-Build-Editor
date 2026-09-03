"""Deterministic flat-record diffs for game updates."""

from __future__ import annotations

from typing import Any

from .errors import CatalogueError


def document_records(document: dict[str, Any], *, label: str = "document") -> list[dict[str, Any]]:
    """Return a document's canonical flat record array."""

    records = document.get("records")
    if not isinstance(records, list):
        raise CatalogueError(f"{label} has no flat records array")
    # Validate eagerly so callers cannot accidentally publish a misleading diff.
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("id"), str):
            raise CatalogueError(f"{label} contains an invalid record")
        if record["id"] in seen:
            raise CatalogueError(f"{label} contains duplicate ID: {record['id']}")
        seen.add(record["id"])
    return records


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


def diff_documents(old: dict[str, Any] | None, new: dict[str, Any]) -> dict[str, Any]:
    """Diff two planner or candidate documents with flat ``records`` arrays."""

    old_records = (
        document_records(old, label="old record document")
        if old is not None
        else None
    )
    new_records = document_records(new, label="new record document")
    changes = diff_record_lists(old_records, new_records)
    return {
        "schemaVersion": 1,
        **changes,
    }
