"""Structural validation for generated extractor outputs."""

from __future__ import annotations

from collections import Counter
import math
import re
from typing import Any

from .classify import CANDIDATE_KINDS
from .collection import IGNORED_COLLECTION_CATEGORIES, PLANNER_CATEGORY_KINDS
from .planner_catalogue import is_human_ui_text

_SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_ATTACHMENT_TAG_PREFIX = "Item.Attachment."
_ITEM_INVENTORY_TAG_BY_TIER = {
    "major": "Ability.Consumable.InventoryType.Major",
    "minor": "Ability.Consumable.InventoryType.Minor",
}
_PLAYER_ITEM_SLOT_TAG = "Slot.Consumable.Custom"


def _expected_slot_category(slot: dict[str, Any]) -> tuple[str, str] | None:
    kind = slot.get("kind")
    if kind in {"trait", "augment"}:
        return kind, kind.title()
    if kind != "component":
        return None
    raw_tags = slot.get("requiredModTags")
    suffixes = [
        value[len(_ATTACHMENT_TAG_PREFIX) :]
        for value in raw_tags
        if isinstance(value, str)
        and value.startswith(_ATTACHMENT_TAG_PREFIX)
        and value != _ATTACHMENT_TAG_PREFIX
    ] if isinstance(raw_tags, list) else []
    if len(suffixes) != 1:
        return None
    parts = [part for part in suffixes[0].split(".") if part]
    if not parts:
        return None
    return (
        ".".join(part.casefold() for part in parts),
        " ".join([*parts[1:], parts[0]]) if len(parts) > 1 else parts[0],
    )


def _is_decoded_png(value: Any, *, path_prefix: str) -> bool:
    if not isinstance(value, dict):
        return False
    path = value.get("path")
    return (
        isinstance(path, str)
        and path.startswith(path_prefix)
        and path.endswith(".png")
        and _SHA256_PATTERN.fullmatch(str(value.get("sha256"))) is not None
        and type(value.get("width")) is int
        and value["width"] > 0
        and type(value.get("height")) is int
        and value["height"] > 0
        and isinstance(value.get("pixelFormat"), str)
        and bool(value["pixelFormat"])
    )


def _valid_conditional_descriptions(
    value: Any,
    *,
    identities: tuple[Any, ...] = (),
) -> bool:
    """Validate the authored ConditionalModDescriptions projection."""

    if not isinstance(value, list) or not value:
        return False
    has_visible_text = False
    for group in value:
        if (
            not isinstance(group, dict)
            or "conditionText" not in group
            or not (
                group["conditionText"] is None
                or isinstance(group["conditionText"], str)
            )
            or not isinstance(group.get("statLines"), list)
            or not group["statLines"]
        ):
            return False
        condition_text = group["conditionText"]
        if (
            isinstance(condition_text, str)
            and condition_text.strip()
            and not is_human_ui_text(condition_text, identities=identities)
        ):
            return False
        has_visible_text = has_visible_text or bool(
            isinstance(condition_text, str) and condition_text.strip()
        )
        for line in group["statLines"]:
            if not isinstance(line, dict) or "statText" not in line:
                return False
            stat_text = line["statText"]
            stat_value = line.get("statValue")
            if (
                not (stat_text is None or isinstance(stat_text, str))
                or isinstance(stat_value, bool)
                or not isinstance(stat_value, (int, float))
                or not math.isfinite(float(stat_value))
                or not isinstance(line.get("displayType"), str)
                or not line["displayType"]
                or not isinstance(line.get("result"), str)
                or not line["result"]
                or (
                    isinstance(stat_text, str)
                    and stat_text.strip()
                    and not is_human_ui_text(stat_text, identities=identities)
                )
            ):
                return False
            has_visible_text = has_visible_text or bool(
                isinstance(stat_text, str) and stat_text.strip()
            )
    return has_visible_text


def _planner_kit_weapon_slot_matches(
    slot: dict[str, Any],
    weapon: dict[str, Any],
) -> bool:
    compatibility = weapon.get("compatibility")
    if not isinstance(compatibility, dict):
        return False
    slot_role = slot.get("slotType")
    weapon_role = compatibility.get("weaponRole")
    ignore_tags = compatibility.get("kitIgnoreTags")
    if (
        not isinstance(slot_role, str)
        or not isinstance(weapon_role, str)
        or not isinstance(ignore_tags, list)
    ):
        return False
    if slot_role != "any":
        kit_tag = slot.get("kitTag")
        return weapon_role == slot_role and (
            not isinstance(kit_tag, str) or kit_tag not in ignore_tags
        )
    slot_subtype = slot.get("weaponSubtype")
    if not isinstance(slot_subtype, str):
        return False
    if slot_subtype != "any":
        return compatibility.get("weaponSubType") == slot_subtype
    slot_type = slot.get("weaponType")
    return slot_type == "any" or compatibility.get("collectionCategory") == slot_type


def validate_outputs(
    *,
    source_manifest: dict[str, Any],
    package_index: dict[str, Any],
    candidates: dict[str, Any],
    strict: bool,
    collection_assets: dict[str, Any] | None = None,
    grid_assets: dict[str, Any] | None = None,
    planner_catalogue: dict[str, Any] | None = None,
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    planner_record_count = 0
    manifest_coverage = source_manifest.get("coverage")
    if (
        isinstance(manifest_coverage, dict)
        and "semanticAssets" in manifest_coverage
        and planner_catalogue is None
    ):
        errors.append({"code": "missing-planner-catalogue"})

    if grid_assets is not None:
        if grid_assets.get("schemaVersion") != 1:
            errors.append({"code": "unsupported-grid-assets-schema"})
        grid_fingerprint = grid_assets.get("sourceFingerprint")
        source_fingerprint = source_manifest.get("sourceFingerprint")
        if (
            isinstance(source_fingerprint, str)
            and grid_fingerprint != source_fingerprint
        ):
            errors.append({"code": "grid-assets-source-fingerprint-mismatch"})
        widgets = grid_assets.get("widgets")
        textures = grid_assets.get("textures")
        failures = grid_assets.get("failures")
        coverage = grid_assets.get("coverage")
        if not isinstance(widgets, list):
            errors.append({"code": "grid-assets-widgets-not-array"})
            widgets = []
        if not isinstance(textures, list):
            errors.append({"code": "grid-assets-textures-not-array"})
            textures = []
        if not isinstance(failures, list):
            errors.append({"code": "grid-assets-failures-not-array"})
            failures = []
        if not isinstance(coverage, dict):
            errors.append({"code": "grid-assets-coverage-not-object"})
            coverage = {}
        layout_metrics = grid_assets.get("layoutMetrics")
        if (
            not isinstance(layout_metrics, dict)
            or layout_metrics.get("status") not in {"parsed", "unresolved"}
        ):
            errors.append({"code": "invalid-grid-layout-metrics"})
        elif layout_metrics.get("status") == "parsed":
            board = layout_metrics.get("board")
            pitch = (layout_metrics.get("cell") or {}).get("pitchPixels")
            base = (board or {}).get("baseSizePixels")
            if (
                not isinstance(board, dict)
                or board.get("status") != "parsed"
                or type(board.get("columns")) is not int
                or board["columns"] <= 0
                or type(board.get("rows")) is not int
                or board["rows"] <= 0
                or not isinstance(pitch, dict)
                or type(pitch.get("x")) is not int
                or pitch["x"] <= 0
                or type(pitch.get("y")) is not int
                or pitch["y"] <= 0
                or not isinstance(base, dict)
                or base.get("width") != board["columns"] * pitch["x"]
                or base.get("height") != board["rows"] * pitch["y"]
            ):
                errors.append({"code": "invalid-grid-board-metrics"})
        perk_palette = grid_assets.get("perkColorPalette")
        if (
            not isinstance(perk_palette, dict)
            or perk_palette.get("status") not in {"parsed", "unresolved"}
            or (
                perk_palette.get("status") == "parsed"
                and not isinstance(perk_palette.get("colors"), list)
            )
        ):
            errors.append({"code": "invalid-grid-perk-color-palette"})
        if not isinstance(grid_assets.get("renderingContract"), dict):
            errors.append({"code": "invalid-grid-rendering-contract"})

        artifact_paths: list[str] = []
        widget_packages: list[str] = []
        texture_packages: list[str] = []
        hash_pattern = re.compile(r"sha256:[0-9a-f]{64}")
        for index, widget in enumerate(widgets):
            if not isinstance(widget, dict):
                errors.append({"code": "invalid-grid-widget", "index": index})
                continue
            package = widget.get("packagePath")
            path = widget.get("path")
            dependencies = widget.get("textureDependencies")
            if not isinstance(package, str) or not package.startswith("/Game/"):
                errors.append({"code": "invalid-grid-widget-package", "index": index})
            else:
                widget_packages.append(package)
            if not isinstance(path, str) or not path.startswith("grid-assets/widgets/"):
                errors.append({"code": "invalid-grid-widget-path", "index": index})
            else:
                artifact_paths.append(path)
            if hash_pattern.fullmatch(str(widget.get("sha256"))) is None:
                errors.append({"code": "invalid-grid-widget-hash", "index": index})
            if not isinstance(dependencies, list) or not all(
                isinstance(value, str) for value in dependencies
            ):
                errors.append({"code": "invalid-grid-widget-dependencies", "index": index})

        for index, texture in enumerate(textures):
            if not isinstance(texture, dict):
                errors.append({"code": "invalid-grid-texture", "index": index})
                continue
            package = texture.get("packagePath")
            path = texture.get("path")
            if not isinstance(package, str) or not package.startswith("/Game/"):
                errors.append({"code": "invalid-grid-texture-package", "index": index})
            else:
                texture_packages.append(package)
            if not isinstance(path, str) or not path.startswith("grid-assets/textures/"):
                errors.append({"code": "invalid-grid-texture-path", "index": index})
            else:
                artifact_paths.append(path)
            if hash_pattern.fullmatch(str(texture.get("sha256"))) is None:
                errors.append({"code": "invalid-grid-texture-hash", "index": index})
            if (
                type(texture.get("width")) is not int
                or texture["width"] <= 0
                or type(texture.get("height")) is not int
                or texture["height"] <= 0
                or not isinstance(texture.get("pixelFormat"), str)
                or not isinstance(texture.get("role"), str)
            ):
                errors.append({"code": "invalid-grid-texture-metadata", "index": index})

        for code, values in (
            ("duplicate-grid-widget-package", widget_packages),
            ("duplicate-grid-texture-package", texture_packages),
            ("duplicate-grid-artifact-path", artifact_paths),
        ):
            duplicates = sorted(value for value, count in Counter(values).items() if count > 1)
            if duplicates:
                errors.append({"code": code, "values": duplicates})
        known_textures = set(texture_packages)
        for widget in widgets:
            if not isinstance(widget, dict):
                continue
            dependencies = widget.get("textureDependencies")
            if isinstance(dependencies, list):
                missing = sorted(
                    value
                    for value in dependencies
                    if isinstance(value, str) and value not in known_textures
                )
                if missing:
                    errors.append(
                        {
                            "code": "dangling-grid-widget-texture",
                            "packagePath": widget.get("packagePath"),
                            "targets": missing,
                        }
                    )
        failed_widgets = sum(
            1
            for failure in failures
            if isinstance(failure, dict) and failure.get("stage") == "widget"
        )
        failed_textures = sum(
            1
            for failure in failures
            if isinstance(failure, dict) and failure.get("stage") == "texture"
        )
        malformed_failures = [
            index
            for index, failure in enumerate(failures)
            if not isinstance(failure, dict)
            or failure.get("stage") not in {"widget", "texture"}
            or not isinstance(failure.get("packagePath"), str)
            or not isinstance(failure.get("reason"), str)
        ]
        if malformed_failures:
            errors.append(
                {"code": "invalid-grid-asset-failures", "indexes": malformed_failures}
            )
        if coverage.get("widgetsParsed") != len(widgets):
            errors.append({"code": "grid-widget-coverage-mismatch"})
        if coverage.get("texturesDecoded") != len(textures):
            errors.append({"code": "grid-texture-coverage-mismatch"})
        if (
            coverage.get("widgetsFailed") != failed_widgets
            or coverage.get("widgetsRequested") != len(widgets) + failed_widgets
        ):
            errors.append({"code": "grid-widget-outcome-mismatch"})
        if (
            coverage.get("texturesFailed") != failed_textures
            or coverage.get("texturesRequested") != len(textures) + failed_textures
        ):
            errors.append({"code": "grid-texture-outcome-mismatch"})
        if failures:
            warnings.append({"code": "grid-asset-failures", "count": len(failures)})
        manifest_coverage = source_manifest.get("coverage")
        manifest_grid_coverage = (
            manifest_coverage.get("gridAssets")
            if isinstance(manifest_coverage, dict)
            else None
        )
        if manifest_grid_coverage is not None and manifest_grid_coverage != coverage:
            errors.append({"code": "grid-assets-manifest-coverage-mismatch"})

    packages = package_index.get("packages", [])
    package_ids = [item.get("packagePath") for item in packages if isinstance(item, dict)]
    duplicate_packages = sorted(value for value, count in Counter(package_ids).items() if count > 1)
    if duplicate_packages:
        errors.append({"code": "duplicate-package", "ids": duplicate_packages})

    candidate_records = candidates.get("records", [])
    candidate_ids = [item.get("id") for item in candidate_records if isinstance(item, dict)]
    candidate_by_id = {
        item["id"]: item
        for item in candidate_records
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    duplicate_candidates = sorted(value for value, count in Counter(candidate_ids).items() if count > 1)
    if duplicate_candidates:
        errors.append({"code": "duplicate-candidate", "ids": duplicate_candidates})

    collection_members_by_kind: dict[str, set[str]] = {
        kind: set() for kind in PLANNER_CATEGORY_KINDS.values()
    }
    collection_augment_concept_ids: set[str] = set()
    canonical_kit_member_ids: set[str] = set()
    if collection_assets is not None:
        if collection_assets.get("schemaVersion") != 1:
            errors.append({"code": "unsupported-collection-assets-schema"})
        if collection_assets.get("sourceFingerprint") != source_manifest.get("sourceFingerprint"):
            errors.append({"code": "collection-assets-source-fingerprint-mismatch"})
        if collection_assets.get("status") != "complete" or collection_assets.get("unresolved") != []:
            errors.append({"code": "collection-assets-incomplete"})
        collection_categories = collection_assets.get("categories")
        memberships = collection_assets.get("memberships")
        collection_coverage = collection_assets.get("coverage")
        if not isinstance(collection_categories, list):
            errors.append({"code": "collection-assets-categories-not-array"})
            collection_categories = []
        if not isinstance(memberships, dict):
            errors.append({"code": "collection-assets-memberships-not-object"})
            memberships = {}
        category_audit = collection_assets.get("categoryAudit")
        category_keys = sorted(
            {
                category.get("key")
                for category in collection_categories
                if isinstance(category, dict)
                and isinstance(category.get("key"), str)
            }
        )
        audit_valid = isinstance(category_audit, dict)
        audit_values: dict[str, list[str]] = {}
        if audit_valid:
            for field in (
                "ignoredKeys",
                "includedKeys",
                "observedKeys",
                "unknownKeys",
            ):
                values = category_audit.get(field)
                if (
                    not isinstance(values, list)
                    or not all(isinstance(value, str) and value for value in values)
                    or values != sorted(set(values))
                ):
                    audit_valid = False
                    break
                audit_values[field] = values
        if audit_valid:
            included = set(audit_values["includedKeys"])
            ignored = set(audit_values["ignoredKeys"])
            observed = set(audit_values["observedKeys"])
            unknown = set(audit_values["unknownKeys"])
            if (
                included != set(category_keys)
                or not included <= set(PLANNER_CATEGORY_KINDS)
                or ignored != observed & set(IGNORED_COLLECTION_CATEGORIES)
                or unknown
                != observed
                - set(PLANNER_CATEGORY_KINDS)
                - set(IGNORED_COLLECTION_CATEGORIES)
                or observed != included | ignored | unknown
                or bool(included & ignored)
                or bool(included & unknown)
                or bool(ignored & unknown)
            ):
                audit_valid = False
        if not audit_valid:
            errors.append({"code": "invalid-collection-category-audit"})
        else:
            if (
                not isinstance(collection_coverage, dict)
                or collection_coverage.get("ignoredCategories")
                != len(audit_values["ignoredKeys"])
                or collection_coverage.get("unknownCategories")
                != len(audit_values["unknownKeys"])
            ):
                errors.append({"code": "collection-category-audit-coverage-mismatch"})
            if audit_values["unknownKeys"]:
                warnings.append(
                    {
                        "code": "collection-unknown-category-keys",
                        "keys": audit_values["unknownKeys"],
                    }
                )
        for record_id, values in memberships.items():
            candidate = candidate_by_id.get(record_id)
            if candidate is None:
                errors.append({"code": "collection-member-not-candidate", "id": record_id})
                continue
            if not isinstance(values, list) or not values:
                errors.append({"code": "invalid-collection-membership", "id": record_id})
                continue
            expected = {
                PLANNER_CATEGORY_KINDS.get(value.get("categoryKey"))
                for value in values
                if isinstance(value, dict)
            }
            if expected != {candidate.get("kind")}:
                errors.append(
                    {
                        "actualKind": candidate.get("kind"),
                        "code": "collection-member-kind-mismatch",
                        "expectedKinds": sorted(value for value in expected if value is not None),
                        "id": record_id,
                    }
                )
            elif isinstance(candidate.get("kind"), str):
                collection_members_by_kind.setdefault(candidate["kind"], set()).add(
                    record_id
                )
        for category in collection_categories:
            if not isinstance(category, dict) or category.get("key") != "AugmentPacks":
                continue
            entries = category.get("entries")
            if not isinstance(entries, list):
                continue
            collection_augment_concept_ids.update(
                entry["id"]
                for entry in entries
                if isinstance(entry, dict)
                and entry.get("status") == "resolved"
                and isinstance(entry.get("id"), str)
            )
        if not isinstance(collection_coverage, dict) or (
            collection_coverage.get("uniqueTerminalRecords") != len(memberships)
        ):
            errors.append({"code": "collection-assets-coverage-mismatch"})
        kit_membership = collection_assets.get("kitMembership")
        if not isinstance(kit_membership, dict):
            errors.append({"code": "collection-kit-membership-not-object"})
        else:
            kit_status = kit_membership.get("status")
            kit_members = kit_membership.get("memberIds")
            kit_entries = kit_membership.get("entries")
            kit_unresolved = kit_membership.get("unresolved")
            kit_coverage = kit_membership.get("coverage")
            if kit_status not in {"complete", "incomplete"}:
                errors.append({"code": "invalid-collection-kit-membership-status"})
            if (
                not isinstance(kit_members, list)
                or not kit_members
                or not all(isinstance(value, str) for value in kit_members)
                or len(set(kit_members)) != len(kit_members)
            ):
                errors.append({"code": "invalid-collection-kit-members"})
                kit_members = []
            canonical_kit_member_ids = set(kit_members)
            if not isinstance(kit_entries, list):
                errors.append({"code": "collection-kit-entries-not-array"})
                kit_entries = []
            if not isinstance(kit_unresolved, list):
                errors.append({"code": "collection-kit-unresolved-not-array"})
                kit_unresolved = []
            entry_ids: list[str] = []
            entry_classes: list[str] = []
            malformed_entries: list[str] = []
            has_starting_source = False
            for index, entry in enumerate(kit_entries):
                if not isinstance(entry, dict):
                    malformed_entries.append(str(index))
                    continue
                entry_id = entry.get("id")
                class_package = entry.get("characterClassPackagePath")
                package_path = entry.get("packagePath")
                sources = entry.get("sources")
                candidate = candidate_by_id.get(entry_id, {})
                valid_sources = (
                    isinstance(sources, list)
                    and bool(sources)
                    and all(isinstance(source, dict) for source in sources)
                )
                if valid_sources and any(
                    source.get("sourceKind") == "default-starting-rewards"
                    for source in sources
                ):
                    has_starting_source = True
                if (
                    not isinstance(entry_id, str)
                    or entry.get("kind") != "kit"
                    or not isinstance(package_path, str)
                    or not isinstance(class_package, str)
                    or not valid_sources
                    or candidate.get("kind") != "kit"
                    or (
                        isinstance(candidate.get("packagePath"), str)
                        and candidate.get("packagePath") != package_path
                    )
                    or candidate.get("characterClassPackagePath") != class_package
                ):
                    malformed_entries.append(
                        entry_id if isinstance(entry_id, str) else str(index)
                    )
                    continue
                entry_ids.append(entry_id)
                entry_classes.append(class_package)
            if malformed_entries:
                errors.append(
                    {
                        "code": "invalid-collection-kit-entry",
                        "ids": sorted(malformed_entries),
                    }
                )
            if (
                len(entry_ids) != len(kit_entries)
                or len(set(entry_ids)) != len(entry_ids)
                or set(entry_ids) != canonical_kit_member_ids
                or len(set(entry_classes)) != len(entry_classes)
            ):
                errors.append({"code": "collection-kit-entry-membership-mismatch"})
            if not has_starting_source:
                errors.append({"code": "collection-kit-starting-source-missing"})
            invalid_kit_members = sorted(
                record_id
                for record_id in canonical_kit_member_ids
                if candidate_by_id.get(record_id, {}).get("kind") != "kit"
            )
            if invalid_kit_members:
                errors.append(
                    {
                        "code": "collection-kit-member-not-kit-candidate",
                        "ids": invalid_kit_members,
                    }
                )
            if (
                not isinstance(kit_coverage, dict)
                or kit_coverage.get("mappedKits") != len(canonical_kit_member_ids)
                or kit_coverage.get("unresolvedReferences") != len(kit_unresolved)
            ):
                errors.append({"code": "collection-kit-coverage-mismatch"})
            if isinstance(collection_coverage, dict) and (
                collection_coverage.get("kitMembership")
                != len(canonical_kit_member_ids)
                or collection_coverage.get("kitMembershipUnresolvedReferences")
                != len(kit_unresolved)
            ):
                errors.append({"code": "collection-kit-summary-coverage-mismatch"})
            if kit_status == "complete" and kit_unresolved:
                errors.append({"code": "complete-collection-kit-membership-has-unresolved"})
            elif kit_status == "incomplete":
                warnings.append(
                    {
                        "code": "collection-kit-membership-incomplete",
                        "count": len(kit_unresolved),
                    }
                )
        progression = collection_assets.get("progressionPerks")
        if not isinstance(progression, dict):
            errors.append({"code": "collection-progression-perks-not-object"})
        else:
            progression_status = progression.get("status")
            progression_members = progression.get("memberIds")
            progression_entries = progression.get("entries")
            progression_unresolved = progression.get("unresolved")
            progression_coverage = progression.get("coverage")
            if progression_status not in {"complete", "incomplete"}:
                errors.append({"code": "invalid-collection-progression-status"})
            if not isinstance(progression_members, list) or not all(
                isinstance(value, str) for value in progression_members
            ):
                errors.append({"code": "invalid-collection-progression-members"})
                progression_members = []
            if not isinstance(progression_entries, list):
                errors.append({"code": "collection-progression-entries-not-array"})
                progression_entries = []
            if not isinstance(progression_unresolved, list):
                errors.append({"code": "collection-progression-unresolved-not-array"})
                progression_unresolved = []
            progression_entry_ids = [
                entry.get("id")
                for entry in progression_entries
                if isinstance(entry, dict) and isinstance(entry.get("id"), str)
            ]
            if (
                len(progression_entry_ids) != len(progression_entries)
                or len(set(progression_entry_ids)) != len(progression_entry_ids)
                or sorted(progression_entry_ids) != sorted(set(progression_members))
            ):
                errors.append({"code": "collection-progression-entry-membership-mismatch"})
            invalid_progression_members = sorted(
                record_id
                for record_id in set(progression_members)
                if candidate_by_id.get(record_id, {}).get("kind") != "perk"
            )
            if invalid_progression_members:
                errors.append(
                    {
                        "code": "collection-progression-member-not-perk-candidate",
                        "ids": invalid_progression_members,
                    }
                )
            malformed_progression_entries = sorted(
                str(entry.get("id", index) if isinstance(entry, dict) else index)
                for index, entry in enumerate(progression_entries)
                if not isinstance(entry, dict)
                or entry.get("kind") != "perk"
                or not isinstance(entry.get("packagePath"), str)
                or not isinstance(entry.get("sources"), list)
                or not entry["sources"]
            )
            if malformed_progression_entries:
                errors.append(
                    {
                        "code": "invalid-collection-progression-entry",
                        "ids": malformed_progression_entries,
                    }
                )
            if (
                not isinstance(progression_coverage, dict)
                or progression_coverage.get("uniquePerks") != len(set(progression_members))
                or progression_coverage.get("unresolvedReferences")
                != len(progression_unresolved)
            ):
                errors.append({"code": "collection-progression-coverage-mismatch"})
            if progression_status == "complete" and progression_unresolved:
                errors.append({"code": "complete-collection-progression-has-unresolved"})
            elif progression_status == "incomplete":
                warnings.append(
                    {
                        "code": "collection-progression-incomplete",
                        "count": len(progression_unresolved),
                    }
                )
        manifest_coverage = source_manifest.get("coverage")
        if (
            isinstance(manifest_coverage, dict)
            and manifest_coverage.get("collectionAssets") is not None
            and manifest_coverage.get("collectionAssets") != collection_coverage
        ):
            errors.append({"code": "collection-assets-manifest-coverage-mismatch"})

    if planner_catalogue is not None:
        if planner_catalogue.get("schemaVersion") != 1:
            errors.append({"code": "unsupported-planner-catalogue-schema"})
        if planner_catalogue.get("sourceFingerprint") != source_manifest.get("sourceFingerprint"):
            errors.append({"code": "planner-catalogue-source-fingerprint-mismatch"})
        if planner_catalogue.get("game") != source_manifest.get("game"):
            errors.append({"code": "planner-catalogue-game-metadata-mismatch"})
        if planner_catalogue.get("extractor") != source_manifest.get("extractor"):
            errors.append({"code": "planner-catalogue-extractor-metadata-mismatch"})
        if planner_catalogue.get("textContract") != {
            "conditionalDescriptionField": "conditionalDescriptions",
            "descriptionField": "description",
            "displayNameField": "displayName",
            "packagePathIsDisplayText": False,
            "richTextFormat": "unreal-rich-text-subset",
        }:
            errors.append({"code": "invalid-planner-text-contract"})
        planner_records = planner_catalogue.get("records")
        if not isinstance(planner_records, list):
            errors.append({"code": "planner-catalogue-records-not-array"})
            planner_records = []
        planner_record_count = len(planner_records)
        planner_ids = [
            item["id"]
            for item in planner_records
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]
        duplicates = sorted(
            value for value, count in Counter(planner_ids).items() if count > 1
        )
        if duplicates:
            errors.append({"code": "duplicate-planner-record", "ids": duplicates})
        planner_by_id = {
            item["id"]: item
            for item in planner_records
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        planner_ids_by_kind = {
            kind: {
                record_id
                for record_id, record in planner_by_id.items()
                if record.get("kind") == kind
            }
            for kind in (
                "ability",
                "augment",
                "item",
                "kit",
                "mod",
                "perk",
                "trait",
                "weapon",
            )
        }
        planner_item_slots = planner_catalogue.get("itemSlots")
        invalid_item_slots: list[int | str] = []
        seen_item_slot_indexes: set[int] = set()
        seen_item_slot_tiers: list[str] = []
        if not isinstance(planner_item_slots, list) or not planner_item_slots:
            errors.append({"code": "planner-item-slots-not-array"})
            planner_item_slots = []
        for position, slot in enumerate(planner_item_slots):
            if not isinstance(slot, dict):
                invalid_item_slots.append(position)
                continue
            index = slot.get("index")
            tier = slot.get("itemTier")
            expected_tag = _ITEM_INVENTORY_TAG_BY_TIER.get(tier)
            compatible_ids = slot.get("compatibleItemIds")
            required_tags = slot.get("requiredModTags")
            slot_tags = slot.get("slotTags")
            evidence = slot.get("evidence")
            expected_compatible_ids = sorted(
                record_id
                for record_id in planner_ids_by_kind["item"]
                if planner_by_id[record_id].get("itemTier") == tier
            )
            if (
                type(index) is not int
                or index < 0
                or index in seen_item_slot_indexes
                or expected_tag is None
                or slot.get("inventoryTypeTag") != expected_tag
                or not isinstance(required_tags, list)
                or not all(isinstance(value, str) and value for value in required_tags)
                or expected_tag not in required_tags
                or not isinstance(slot_tags, list)
                or not all(isinstance(value, str) and value for value in slot_tags)
                or _PLAYER_ITEM_SLOT_TAG not in slot_tags
                or not isinstance(evidence, dict)
                or evidence.get("source") != "serialized-uasset"
                or slot.get("displayName") != f"{str(tier).title()} Item"
                or slot.get("displayNameSource") != "derived-inventory-type-tag"
                or compatible_ids != expected_compatible_ids
                or not expected_compatible_ids
            ):
                invalid_item_slots.append(
                    index if type(index) is int else position
                )
                continue
            seen_item_slot_indexes.add(index)
            seen_item_slot_tiers.append(tier)
        if (
            invalid_item_slots
            or len(planner_item_slots) != 2
            or sorted(seen_item_slot_tiers) != ["major", "minor"]
        ):
            errors.append(
                {
                    "code": "invalid-planner-item-slots",
                    "slots": sorted(set(invalid_item_slots), key=str),
                }
            )
        planner_coverage = planner_catalogue.get("coverage")
        if (
            not isinstance(planner_coverage, dict)
            or planner_coverage.get("itemSlots") != len(planner_item_slots)
        ):
            errors.append({"code": "planner-item-slot-coverage-mismatch"})
        if planner_ids_by_kind["kit"] != canonical_kit_member_ids:
            errors.append(
                {
                    "code": "planner-kit-membership-projection-mismatch",
                    "extraIds": sorted(
                        planner_ids_by_kind["kit"] - canonical_kit_member_ids
                    ),
                    "missingIds": sorted(
                        canonical_kit_member_ids - planner_ids_by_kind["kit"]
                    ),
                }
            )
        planner_source_coverage = planner_catalogue.get("sourceCoverage")
        expected_source_sections = {
            "kitMembership": (collection_assets or {}).get("kitMembership"),
            "progressionPerks": (collection_assets or {}).get("progressionPerks"),
        }
        if not isinstance(planner_source_coverage, dict):
            errors.append({"code": "planner-source-coverage-not-object"})
        else:
            for section, source in expected_source_sections.items():
                expected = (
                    {
                        "coverage": source.get("coverage", {}),
                        "status": source.get("status"),
                    }
                    if isinstance(source, dict)
                    else None
                )
                if planner_source_coverage.get(section) != expected:
                    errors.append(
                        {
                            "code": "planner-source-coverage-mismatch",
                            "section": section,
                        }
                    )
        raw_progression_member_ids = {
            value
            for value in ((collection_assets or {}).get("progressionPerks") or {}).get(
                "memberIds", []
            )
            if isinstance(value, str)
        }
        progression_member_ids: set[str] = set()
        for value in raw_progression_member_ids:
            candidate = candidate_by_id.get(value, {})
            ability = candidate.get("ability")
            alias = ability.get("aliasOf") if isinstance(ability, dict) else None
            progression_member_ids.add(alias if isinstance(alias, str) else value)
        store_perk_ids: set[str] = set()
        for value in collection_members_by_kind.get("perk", set()):
            candidate = candidate_by_id.get(value, {})
            ability = candidate.get("ability")
            alias = ability.get("aliasOf") if isinstance(ability, dict) else None
            store_perk_ids.add(alias if isinstance(alias, str) else value)

        entitlement_kits_by_perk: dict[str, set[str]] = {}
        for candidate in candidate_records:
            if not isinstance(candidate, dict) or candidate.get("kind") != "kit":
                continue
            kit_id = candidate.get("id")
            entitlements = candidate.get("chipEntitlements")
            if (
                not isinstance(kit_id, str)
                or kit_id not in canonical_kit_member_ids
                or not isinstance(entitlements, list)
            ):
                continue
            for entitlement in entitlements:
                raw_id = entitlement.get("perkId") if isinstance(entitlement, dict) else None
                if not isinstance(raw_id, str):
                    continue
                perk_candidate = candidate_by_id.get(raw_id, {})
                ability = perk_candidate.get("ability")
                alias = ability.get("aliasOf") if isinstance(ability, dict) else None
                perk_id = alias if isinstance(alias, str) else raw_id
                entitlement_kits_by_perk.setdefault(perk_id, set()).add(kit_id)
        for kind in ("weapon", "mod", "trait", "item"):
            expected_ids = collection_members_by_kind.get(kind, set())
            if planner_ids_by_kind[kind] != expected_ids:
                errors.append(
                    {
                        "code": "planner-collection-projection-mismatch",
                        "expectedKind": kind,
                        "extraIds": sorted(planner_ids_by_kind[kind] - expected_ids),
                        "missingIds": sorted(expected_ids - planner_ids_by_kind[kind]),
                    }
                )
        if planner_ids_by_kind["augment"] != collection_augment_concept_ids:
            errors.append(
                {
                    "code": "planner-collection-projection-mismatch",
                    "expectedKind": "augment",
                    "extraIds": sorted(
                        planner_ids_by_kind["augment"] - collection_augment_concept_ids
                    ),
                    "missingIds": sorted(
                        collection_augment_concept_ids - planner_ids_by_kind["augment"]
                    ),
                }
            )

        def validate_planner_compatibility_ids(
            *,
            field: str,
            owner_id: str,
            targets: Any,
            visible_kind: str,
        ) -> bool:
            if not isinstance(targets, list) or not all(
                isinstance(value, str) for value in targets
            ):
                errors.append(
                    {
                        "code": "invalid-planner-compatibility-reference-field",
                        "field": field,
                        "id": owner_id,
                    }
                )
                return False
            nonvisible = sorted(
                set(targets) - planner_ids_by_kind.get(visible_kind, set())
            )
            if nonvisible:
                errors.append(
                    {
                        "code": "nonvisible-planner-compatibility-reference",
                        "expectedKind": visible_kind,
                        "field": field,
                        "id": owner_id,
                        "targets": nonvisible,
                    }
                )
                return False
            return True

        def expected_perk_render_footprints(
            record: dict[str, Any],
        ) -> set[tuple[int, int]] | None:
            grid = record.get("grid")
            shapes = grid.get("shapes") if isinstance(grid, dict) else None
            rotations = (
                grid.get("allowedRotations") if isinstance(grid, dict) else None
            )
            if (
                not isinstance(shapes, list)
                or not shapes
                or not isinstance(rotations, list)
                or not all(isinstance(value, str) for value in rotations)
            ):
                return None
            quarter_turn = any(
                value in {"Clockwise90", "Clockwise270"} for value in rotations
            )
            footprints: set[tuple[int, int]] = set()
            for shape in shapes:
                if not isinstance(shape, dict):
                    return None
                width = shape.get("width")
                height = shape.get("height")
                if (
                    type(width) is not int
                    or width <= 0
                    or type(height) is not int
                    or height <= 0
                ):
                    return None
                footprints.add((width, height))
                if quarter_turn:
                    footprints.add((height, width))
            return footprints or None

        missing_names: list[str] = []
        missing_descriptions: list[str] = []
        unresolved_render: list[str] = []
        invalid_perk_render_bindings: list[str] = []
        unresolved_compatibility: list[str] = []
        invalid_item_tiers: list[str] = []
        undecoded_icons: list[str] = []
        invalid_weapon_slots: list[str] = []
        invalid_weapon_loadout_compatibility: list[str] = []
        invalid_conditional_descriptions: list[str] = []
        conditional_description_source_mismatches: list[str] = []
        unresolved_conditional_descriptions: list[str] = []
        forbidden_mechanics: list[str] = []
        invalid_ui_text: list[dict[str, str]] = []
        text_source_mismatches: list[dict[str, Any]] = []
        collection_concepts = {
            item.get("id"): item
            for item in (collection_assets or {}).get("conceptRecords", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        for record in planner_records:
            if not isinstance(record, dict) or not isinstance(record.get("id"), str):
                errors.append({"code": "invalid-planner-record"})
                continue
            source = candidate_by_id.get(record["id"])
            expected_source_kind = "perk" if record.get("kind") == "ability" else record.get("kind")
            concept_source = collection_concepts.get(record["id"])
            source_valid = source is not None and source.get("kind") == expected_source_kind
            if record.get("kind") == "augment" and concept_source is not None:
                source_valid = concept_source.get("kind") == "augment"
                implementations = record.get("implementationIds")
                if not isinstance(implementations, list) or not implementations:
                    source_valid = False
                elif any(
                    candidate_by_id.get(value, {}).get("kind") != "augment"
                    for value in implementations
                ):
                    source_valid = False
            if not source_valid:
                errors.append(
                    {
                        "code": "invalid-planner-record-source",
                        "id": record["id"],
                        "kind": record.get("kind"),
                    }
                )
            identities = (record["id"], record.get("packagePath"))
            display_name = record.get("displayName")
            if not isinstance(display_name, str) or not display_name.strip():
                missing_names.append(record["id"])
            elif not is_human_ui_text(display_name, identities=identities):
                invalid_ui_text.append(
                    {"field": "displayName", "id": record["id"]}
                )
            text_source = (
                concept_source
                if record.get("kind") == "augment" and concept_source is not None
                else source
            )
            if source_valid and isinstance(text_source, dict):
                mismatch_fields = [
                    field
                    for field in (
                        "displayName",
                        "description",
                        "conditionalDescriptions",
                    )
                    if (field in record) != (field in text_source)
                    or record.get(field) != text_source.get(field)
                ]
                if mismatch_fields:
                    text_source_mismatches.append(
                        {"fields": mismatch_fields, "id": record["id"]}
                    )
            conditional_descriptions = record.get("conditionalDescriptions")
            has_conditional_descriptions = _valid_conditional_descriptions(
                conditional_descriptions,
                identities=identities,
            )
            if (
                "conditionalDescriptions" in record
                and not has_conditional_descriptions
            ):
                invalid_conditional_descriptions.append(record["id"])
            if record.get("kind") in {"mod", "trait"}:
                source_conditional = (
                    source.get("conditionalDescriptions")
                    if isinstance(source, dict)
                    else None
                )
                source_resolution = (
                    source.get("conditionalDescriptionsResolution")
                    if isinstance(source, dict)
                    else None
                )
                if (
                    isinstance(source_resolution, dict)
                    and source_resolution.get("status") == "unresolved"
                ):
                    unresolved_conditional_descriptions.append(record["id"])
                if (
                    conditional_descriptions != source_conditional
                    or (
                        ("conditionalDescriptions" in record)
                        != (
                            isinstance(source, dict)
                            and "conditionalDescriptions" in source
                        )
                    )
                ):
                    conditional_description_source_mismatches.append(record["id"])
            description = record.get("description")
            if (
                isinstance(description, str)
                and description.strip()
                and not is_human_ui_text(description, identities=identities)
            ):
                invalid_ui_text.append(
                    {"field": "description", "id": record["id"]}
                )
            if not (
                isinstance(description, str)
                and description.strip()
                or has_conditional_descriptions
            ):
                missing_descriptions.append(record["id"])
            if any(field in record for field in ("effects", "stats")):
                forbidden_mechanics.append(record["id"])
            rendering = record.get("rendering")
            expected_render_status = (
                "slot-controlled" if record.get("kind") == "ability" else "resolved"
            )
            if record.get("kind") in {"ability", "perk"} and (
                not isinstance(rendering, dict)
                or rendering.get("status") != expected_render_status
            ):
                unresolved_render.append(record["id"])
            if record.get("kind") == "perk" and isinstance(rendering, dict) and (
                rendering.get("status") == "resolved"
            ):
                expected_footprints = expected_perk_render_footprints(record)
                bindings = rendering.get("chipBodyByFootprint")
                actual_footprints: list[tuple[int, int]] = []
                bindings_valid = isinstance(bindings, list) and bool(bindings)
                if isinstance(bindings, list):
                    for binding in bindings:
                        footprint = (
                            binding.get("footprint")
                            if isinstance(binding, dict)
                            else None
                        )
                        width = (
                            footprint.get("width")
                            if isinstance(footprint, dict)
                            else None
                        )
                        height = (
                            footprint.get("height")
                            if isinstance(footprint, dict)
                            else None
                        )
                        if (
                            not _is_decoded_png(
                                binding,
                                path_prefix="grid-assets/textures/",
                            )
                            or type(width) is not int
                            or width <= 0
                            or type(height) is not int
                            or height <= 0
                        ):
                            bindings_valid = False
                            continue
                        actual_footprints.append((width, height))
                if (
                    expected_footprints is None
                    or not bindings_valid
                    or len(actual_footprints) != len(set(actual_footprints))
                    or set(actual_footprints) != expected_footprints
                ):
                    invalid_perk_render_bindings.append(record["id"])

            kind = record.get("kind")
            if not _is_decoded_png(record.get("icon"), path_prefix="icons/"):
                undecoded_icons.append(record["id"])
            if kind == "kit":
                selectable_perks = record.get("selectablePerkIds")
                if not isinstance(selectable_perks, list) or any(
                    not isinstance(value, str)
                    or value not in planner_ids_by_kind["perk"]
                    for value in selectable_perks
                ):
                    errors.append(
                        {"code": "invalid-planner-kit-perk-choices", "id": record["id"]}
                    )
                choices_by_role = record.get("selectableAbilityIdsByRole")
                if not isinstance(choices_by_role, dict) or set(choices_by_role) != {
                    "primary",
                    "secondary",
                    "passive",
                }:
                    errors.append(
                        {"code": "invalid-planner-kit-ability-choices", "id": record["id"]}
                    )
                else:
                    for role, values in choices_by_role.items():
                        if not isinstance(values, list) or any(
                            not isinstance(value, str)
                            or value not in planner_ids_by_kind["ability"]
                            or planner_by_id[value].get("role") != role
                            or record["id"]
                            not in planner_by_id[value].get("availableToKitIds", [])
                            for value in values
                        ):
                            errors.append(
                                {
                                    "code": "invalid-planner-kit-ability-choices",
                                    "id": record["id"],
                                    "role": role,
                                }
                            )
                weapon_slots = record.get("weaponSlots")
                if not isinstance(weapon_slots, list) or not weapon_slots:
                    errors.append(
                        {"code": "invalid-planner-kit-weapon-slots", "id": record["id"]}
                    )
                else:
                    indexes: list[int] = []
                    malformed_slots: list[int] = []
                    for position, slot in enumerate(weapon_slots):
                        if not isinstance(slot, dict):
                            malformed_slots.append(position)
                            continue
                        index = slot.get("index")
                        kit_tag = slot.get("kitTag")
                        if (
                            type(index) is not int
                            or index < 0
                            or not all(
                                isinstance(slot.get(field), str) and slot.get(field)
                                for field in (
                                    "slotType",
                                    "weaponSubtype",
                                    "weaponType",
                                )
                            )
                            or (
                                "kitTag" in slot
                                and (not isinstance(kit_tag, str) or not kit_tag)
                            )
                        ):
                            malformed_slots.append(position)
                        else:
                            indexes.append(index)

                        compatible_weapon_ids = slot.get("compatibleWeaponIds")
                        if (
                            not isinstance(compatible_weapon_ids, list)
                            or not compatible_weapon_ids
                            or any(
                                not isinstance(value, str)
                                or value not in planner_ids_by_kind["weapon"]
                                for value in compatible_weapon_ids
                            )
                            or len(set(compatible_weapon_ids))
                            != len(compatible_weapon_ids)
                        ):
                            errors.append(
                                {
                                    "code": "invalid-planner-kit-weapon-choices",
                                    "id": record["id"],
                                    "slotIndex": index,
                                }
                            )
                        default_weapon_id = slot.get("defaultWeaponId")
                        if "defaultWeaponId" in slot and (
                            not isinstance(default_weapon_id, str)
                            or not isinstance(compatible_weapon_ids, list)
                            or default_weapon_id not in compatible_weapon_ids
                        ):
                            errors.append(
                                {
                                    "code": "planner-kit-default-weapon-mismatch",
                                    "id": record["id"],
                                    "slotIndex": index,
                                }
                            )
                    if malformed_slots or len(set(indexes)) != len(weapon_slots):
                        errors.append(
                            {
                                "code": "invalid-planner-kit-weapon-slots",
                                "id": record["id"],
                                "positions": sorted(set(malformed_slots)),
                            }
                        )
            elif kind == "ability":
                available = record.get("availableToKitIds")
                if (
                    record.get("role") not in {"primary", "secondary", "passive"}
                    or not isinstance(available, list)
                    or not available
                    or any(
                        not isinstance(value, str)
                        or value not in planner_ids_by_kind["kit"]
                        for value in available
                    )
                ):
                    errors.append(
                        {"code": "invalid-planner-ability-availability", "id": record["id"]}
                    )
            elif kind == "perk":
                available = record.get("availableToKitIds")
                selection_sources = record.get("selectionSources")
                if (
                    not isinstance(available, list)
                    or any(
                        not isinstance(value, str)
                        or value not in planner_ids_by_kind["kit"]
                        for value in available
                    )
                    or len(available) != len(set(available))
                    or set(available) != planner_ids_by_kind["kit"]
                ):
                    errors.append(
                        {"code": "invalid-planner-perk-availability", "id": record["id"]}
                    )
                if (
                    not isinstance(selection_sources, list)
                    or not selection_sources
                    or any(
                        value
                        not in {
                            "class-entitlement",
                            "progression-unlock",
                            "wrench-collection",
                        }
                        for value in selection_sources
                    )
                    or (
                        "progression-unlock" in selection_sources
                        and record["id"] not in progression_member_ids
                    )
                    or (
                        "wrench-collection" in selection_sources
                        and record["id"] not in store_perk_ids
                    )
                    or (
                        "class-entitlement" in selection_sources
                        and record["id"] not in entitlement_kits_by_perk
                    )
                ):
                    errors.append(
                        {"code": "invalid-planner-perk-selection-source", "id": record["id"]}
                    )

                perk_type = record.get("perkType")
                chip_visual = record.get("chipVisual")
                if perk_type not in {"core", "modifier"}:
                    errors.append(
                        {"code": "invalid-planner-perk-type", "id": record["id"]}
                    )
                elif (
                    not isinstance(chip_visual, dict)
                    or chip_visual.get("status") not in {"resolved", "inferred"}
                    or chip_visual.get("family") != perk_type
                ):
                    errors.append(
                        {
                            "code": "planner-perk-type-visual-mismatch",
                            "id": record["id"],
                        }
                    )

                dependencies = record.get("dependencies")
                is_modifier = perk_type == "modifier"
                if is_modifier and (
                    not isinstance(dependencies, dict)
                    or dependencies.get("requiresConnectedCompatibleTarget") is not True
                ):
                    errors.append(
                        {"code": "planner-modifier-missing-dependency", "id": record["id"]}
                    )
                if isinstance(dependencies, dict):
                    possible_targets = dependencies.get("possibleTargetPerkIds")
                    if isinstance(possible_targets, list) and any(
                        not isinstance(value, str)
                        or value
                        not in planner_ids_by_kind["perk"]
                        | planner_ids_by_kind["ability"]
                        for value in possible_targets
                    ):
                        errors.append(
                            {"code": "invalid-planner-perk-dependency", "id": record["id"]}
                        )
                    possible_modifiers = dependencies.get("possibleModifierPerkIds")
                    if isinstance(possible_modifiers, list) and any(
                        not isinstance(value, str)
                        or value not in planner_ids_by_kind["perk"]
                        for value in possible_modifiers
                    ):
                        errors.append(
                            {"code": "invalid-planner-perk-dependency", "id": record["id"]}
                        )
                    if dependencies.get("requiresConnectedCompatibleTarget") is True:
                        selection = dependencies.get("targetSelection")
                        if (
                            not isinstance(possible_targets, list)
                            or not possible_targets
                            or not isinstance(selection, dict)
                            or selection.get("required") is not True
                            or selection.get("recordField") != "targetId"
                            or selection.get("candidateIds") != possible_targets
                        ):
                            errors.append(
                                {
                                    "code": "invalid-planner-modifier-target-selection",
                                    "id": record["id"],
                                }
                            )
            elif kind == "item":
                if record.get("itemTier") not in {"major", "minor"}:
                    invalid_item_tiers.append(record["id"])
                item_kits = record.get("availableToKitIds")
                if (
                    not isinstance(item_kits, list)
                    or any(not isinstance(value, str) for value in item_kits)
                    or set(item_kits) != planner_ids_by_kind["kit"]
                ):
                    errors.append(
                        {"code": "invalid-planner-item-availability", "id": record["id"]}
                    )

            if kind == "weapon":
                compatibility = record.get("compatibility")
                if (
                    not isinstance(compatibility, dict)
                    or compatibility.get("status") != "resolved"
                ):
                    unresolved_compatibility.append(record["id"])
                    continue

                kit_tags = compatibility.get("kitTags")
                kit_ignore_tags = compatibility.get("kitIgnoreTags")
                if (
                    not isinstance(compatibility.get("weaponRole"), str)
                    or not compatibility["weaponRole"]
                    or not isinstance(compatibility.get("weaponSubType"), str)
                    or not compatibility["weaponSubType"]
                    or not isinstance(compatibility.get("collectionCategory"), str)
                    or not compatibility["collectionCategory"]
                    or not isinstance(kit_tags, list)
                    or any(
                        not isinstance(value, str) or not value
                        for value in kit_tags
                    )
                    or len(set(kit_tags)) != len(kit_tags)
                    or not isinstance(kit_ignore_tags, list)
                    or any(
                        not isinstance(value, str) or not value
                        for value in kit_ignore_tags
                    )
                    or len(set(kit_ignore_tags)) != len(kit_ignore_tags)
                ):
                    invalid_weapon_loadout_compatibility.append(record["id"])

                component_slots = compatibility.get("componentSlots")
                trait_slot = compatibility.get("traitSlot")
                augment_slot = compatibility.get("augmentSlot")
                slots_valid = (
                    isinstance(component_slots, list)
                    and len(component_slots) == 3
                    and all(isinstance(slot, dict) for slot in component_slots)
                    and isinstance(trait_slot, dict)
                    and isinstance(augment_slot, dict)
                    and record.get("componentSlots") == component_slots
                )
                all_slots = (
                    [*component_slots, trait_slot, augment_slot]
                    if slots_valid
                    else []
                )
                indexes = [slot.get("index") for slot in all_slots]
                expected_slot_kinds = (
                    [(slot, "component") for slot in component_slots]
                    + [(trait_slot, "trait"), (augment_slot, "augment")]
                    if slots_valid
                    else []
                )
                if slots_valid:
                    slots_valid = (
                        all(
                            slot.get("kind") == expected
                            for slot, expected in expected_slot_kinds
                        )
                        and all(type(index) is int for index in indexes)
                        and len(set(indexes)) == 5
                    )
                if slots_valid:
                    for slot in all_slots:
                        expected_presentation = _expected_slot_category(slot)
                        display_name = slot.get("displayName")
                        display_name_source = slot.get("displayNameSource")
                        if (
                            expected_presentation is None
                            or slot.get("slotCategory") != expected_presentation[0]
                            or slot.get("slotCategoryDisplayName")
                            != expected_presentation[1]
                            or not isinstance(display_name, str)
                            or not display_name.strip()
                            or display_name_source
                            not in {
                                "authored",
                                "derived-required-mod-tag",
                                "derived-slot-kind",
                            }
                            or (
                                display_name_source.startswith("derived-")
                                and display_name != expected_presentation[1]
                            )
                        ):
                            slots_valid = False
                            break
                if not slots_valid:
                    invalid_weapon_slots.append(record["id"])
                    continue

                slot_kinds = (
                    ("componentSlots", component_slots, "mod"),
                    ("traitSlot", [trait_slot], "trait"),
                    ("augmentSlot", [augment_slot], "augment"),
                )
                slot_ids_by_kind: dict[str, set[str]] = {}
                for field, slots, visible_kind in slot_kinds:
                    slot_ids: set[str] = set()
                    for index, slot in enumerate(slots):
                        compatible_ids = slot.get("compatibleIds")
                        valid_compatible_ids = validate_planner_compatibility_ids(
                            field=f"compatibility.{field}[{index}].compatibleIds",
                            owner_id=record["id"],
                            targets=compatible_ids,
                            visible_kind=visible_kind,
                        )
                        if valid_compatible_ids:
                            slot_ids.update(compatible_ids)
                            if not compatible_ids:
                                invalid_weapon_slots.append(record["id"])
                        if "defaultAttachmentId" in slot:
                            default_id = slot.get("defaultAttachmentId")
                            valid_default = validate_planner_compatibility_ids(
                                field=(
                                    f"compatibility.{field}[{index}]"
                                    ".defaultAttachmentId"
                                ),
                                owner_id=record["id"],
                                targets=[default_id] if isinstance(default_id, str) else None,
                                visible_kind=visible_kind,
                            )
                            if (
                                not valid_default
                                or not valid_compatible_ids
                                or default_id not in compatible_ids
                            ):
                                errors.append(
                                    {
                                        "code": "planner-weapon-default-attachment-mismatch",
                                        "field": (
                                            f"compatibility.{field}[{index}]"
                                            ".defaultAttachmentId"
                                        ),
                                        "id": record["id"],
                                    }
                                )
                    slot_ids_by_kind[visible_kind] = slot_ids

                aggregate_fields = (
                    ("compatibleModIds", "mod"),
                    ("compatibleTraitIds", "trait"),
                    ("compatibleAugmentIds", "augment"),
                )
                for field, visible_kind in aggregate_fields:
                    targets = compatibility.get(field)
                    valid_targets = validate_planner_compatibility_ids(
                        field=f"compatibility.{field}",
                        owner_id=record["id"],
                        targets=targets,
                        visible_kind=visible_kind,
                    )
                    if valid_targets and set(targets) != slot_ids_by_kind[visible_kind]:
                        errors.append(
                            {
                                "code": "planner-weapon-compatibility-slot-mismatch",
                                "field": f"compatibility.{field}",
                                "id": record["id"],
                            }
                        )

            elif kind in {"mod", "trait"}:
                compatibility = record.get("compatibility")
                if (
                    not isinstance(compatibility, dict)
                    or compatibility.get("status") != "resolved"
                ):
                    unresolved_compatibility.append(record["id"])
                else:
                    validate_planner_compatibility_ids(
                        field="compatibility.compatibleWeaponIds",
                        owner_id=record["id"],
                        targets=compatibility.get("compatibleWeaponIds"),
                        visible_kind="weapon",
                    )

            elif kind == "augment":
                compatible_weapon_ids = record.get("compatibleWeaponIds")
                valid_compatible_weapon_ids = validate_planner_compatibility_ids(
                    field="compatibleWeaponIds",
                    owner_id=record["id"],
                    targets=compatible_weapon_ids,
                    visible_kind="weapon",
                )
                implementation_ids = record.get("implementationIds")
                implementation_map = record.get("implementationByWeaponId")
                valid_implementation_ids = (
                    isinstance(implementation_ids, list)
                    and bool(implementation_ids)
                    and all(isinstance(value, str) for value in implementation_ids)
                )
                valid_implementation_map = (
                    isinstance(implementation_map, dict)
                    and all(
                        isinstance(weapon_id, str)
                        and weapon_id in planner_ids_by_kind["weapon"]
                        and isinstance(implementation_id, str)
                        and valid_implementation_ids
                        and implementation_id in implementation_ids
                        for weapon_id, implementation_id in implementation_map.items()
                    )
                    and valid_compatible_weapon_ids
                    and set(implementation_map) == set(compatible_weapon_ids)
                )
                if not valid_implementation_ids or not valid_implementation_map:
                    errors.append(
                        {
                            "code": "invalid-planner-augment-implementation-map",
                            "id": record["id"],
                        }
                    )
        for kit_id in sorted(planner_ids_by_kind["kit"]):
            kit = planner_by_id[kit_id]
            expected_perks = {
                record_id
                for record_id in planner_ids_by_kind["perk"]
                if kit_id in planner_by_id[record_id].get("availableToKitIds", [])
            }
            if set(kit.get("selectablePerkIds", [])) != expected_perks:
                errors.append(
                    {"code": "planner-kit-perk-coverage-mismatch", "id": kit_id}
                )
            choices_by_role = kit.get("selectableAbilityIdsByRole")
            if isinstance(choices_by_role, dict):
                for role in ("primary", "secondary", "passive"):
                    expected_abilities = {
                        record_id
                        for record_id in planner_ids_by_kind["ability"]
                        if planner_by_id[record_id].get("role") == role
                        and kit_id
                        in planner_by_id[record_id].get("availableToKitIds", [])
                    }
                    if set(choices_by_role.get(role, [])) != expected_abilities:
                        errors.append(
                            {
                                "code": "planner-kit-ability-coverage-mismatch",
                                "id": kit_id,
                                "role": role,
                            }
                        )
            ability_slots = kit.get("abilitySlots")
            if not isinstance(ability_slots, list) or any(
                not isinstance(slot, dict)
                or slot.get("role") not in {"primary", "secondary", "passive"}
                or not isinstance(slot.get("selectableAbilityIds"), list)
                or (
                    isinstance(choices_by_role, dict)
                    and slot.get("selectableAbilityIds")
                    != choices_by_role.get(slot.get("role"))
                )
                for slot in ability_slots
            ):
                errors.append(
                    {"code": "invalid-planner-kit-ability-slots", "id": kit_id}
                )
            elif isinstance(choices_by_role, dict):
                slotted_roles = {slot["role"] for slot in ability_slots}
                missing_nonempty_roles = sorted(
                    role
                    for role, values in choices_by_role.items()
                    if values and role not in slotted_roles
                )
                if missing_nonempty_roles:
                    errors.append(
                        {
                            "code": "planner-kit-ability-slot-coverage-mismatch",
                            "id": kit_id,
                            "roles": missing_nonempty_roles,
                        }
                    )

        expected_kit_weapon_ids: set[str] = set()
        for kit_id in sorted(planner_ids_by_kind["kit"]):
            kit = planner_by_id[kit_id]
            weapon_slots = kit.get("weaponSlots")
            source_slots = candidate_by_id.get(kit_id, {}).get("weaponSlots")
            source_by_index = {
                slot["index"]: slot
                for slot in source_slots
                if isinstance(slot, dict) and type(slot.get("index")) is int
            } if isinstance(source_slots, list) else {}
            planner_indexes = {
                slot["index"]
                for slot in weapon_slots
                if isinstance(slot, dict) and type(slot.get("index")) is int
            } if isinstance(weapon_slots, list) else set()
            if (
                not isinstance(source_slots, list)
                or len(source_by_index) != len(source_slots)
                or planner_indexes != set(source_by_index)
            ):
                errors.append(
                    {
                        "code": "planner-kit-weapon-slot-source-mismatch",
                        "id": kit_id,
                    }
                )
            if not isinstance(weapon_slots, list):
                continue
            for slot in weapon_slots:
                if not isinstance(slot, dict) or type(slot.get("index")) is not int:
                    continue
                index = slot["index"]
                source_slot = source_by_index.get(index)
                if isinstance(source_slot, dict) and any(
                    slot.get(field) != source_slot.get(field)
                    for field in (
                        "defaultWeaponId",
                        "kitTag",
                        "slotType",
                        "weaponSubtype",
                        "weaponType",
                    )
                ):
                    errors.append(
                        {
                            "code": "planner-kit-weapon-slot-source-mismatch",
                            "id": kit_id,
                            "slotIndex": index,
                        }
                    )
                expected = sorted(
                    weapon_id
                    for weapon_id in planner_ids_by_kind["weapon"]
                    if _planner_kit_weapon_slot_matches(
                        slot,
                        planner_by_id[weapon_id],
                    )
                )
                expected_kit_weapon_ids.update(expected)
                compatible_weapon_ids = slot.get("compatibleWeaponIds")
                if (
                    not isinstance(compatible_weapon_ids, list)
                    or not compatible_weapon_ids
                    or any(not isinstance(value, str) for value in compatible_weapon_ids)
                ):
                    continue
                if compatible_weapon_ids != expected:
                    errors.append(
                        {
                            "code": "planner-kit-weapon-compatibility-mismatch",
                            "extraIds": sorted(set(compatible_weapon_ids) - set(expected)),
                            "id": kit_id,
                            "missingIds": sorted(set(expected) - set(compatible_weapon_ids)),
                            "slotIndex": index,
                        }
                    )
        if expected_kit_weapon_ids != planner_ids_by_kind["weapon"]:
            errors.append(
                {
                    "code": "planner-weapon-kit-coverage-mismatch",
                    "ids": sorted(
                        planner_ids_by_kind["weapon"] - expected_kit_weapon_ids
                    ),
                }
            )

        reciprocal_failures: list[dict[str, str]] = []
        for kind, aggregate_field in (
            ("mod", "compatibleModIds"),
            ("trait", "compatibleTraitIds"),
        ):
            for attachment_id in sorted(planner_ids_by_kind[kind]):
                attachment = planner_by_id[attachment_id]
                reverse_ids = set(
                    (attachment.get("compatibility") or {}).get(
                        "compatibleWeaponIds", []
                    )
                )
                forward_ids = {
                    weapon_id
                    for weapon_id in planner_ids_by_kind["weapon"]
                    if attachment_id
                    in (planner_by_id[weapon_id].get("compatibility") or {}).get(
                        aggregate_field, []
                    )
                }
                if reverse_ids != forward_ids:
                    reciprocal_failures.append(
                        {"id": attachment_id, "kind": kind}
                    )
        for augment_id in sorted(planner_ids_by_kind["augment"]):
            augment = planner_by_id[augment_id]
            reverse_ids = set(augment.get("compatibleWeaponIds", []))
            forward_ids = {
                weapon_id
                for weapon_id in planner_ids_by_kind["weapon"]
                if augment_id
                in (planner_by_id[weapon_id].get("compatibility") or {}).get(
                    "compatibleAugmentIds", []
                )
            }
            if reverse_ids != forward_ids:
                reciprocal_failures.append({"id": augment_id, "kind": "augment"})
        if reciprocal_failures:
            errors.append(
                {
                    "code": "planner-compatibility-reciprocity-mismatch",
                    "records": reciprocal_failures,
                }
            )

        missing_store_perks = sorted(
            store_perk_ids
            - planner_ids_by_kind["perk"]
            - planner_ids_by_kind["ability"]
        )
        if missing_store_perks:
            errors.append(
                {"code": "planner-store-perk-coverage-mismatch", "ids": missing_store_perks}
            )
        unmarked_store_perks = sorted(
            record_id
            for record_id in store_perk_ids & planner_ids_by_kind["perk"]
            if "wrench-collection"
            not in planner_by_id[record_id].get("selectionSources", [])
        )
        if unmarked_store_perks:
            errors.append(
                {"code": "planner-store-perk-source-mismatch", "ids": unmarked_store_perks}
            )
        missing_entitlement_perks = sorted(
            set(entitlement_kits_by_perk)
            - planner_ids_by_kind["perk"]
            - planner_ids_by_kind["ability"]
        )
        if missing_entitlement_perks:
            errors.append(
                {
                    "code": "planner-entitlement-perk-coverage-mismatch",
                    "ids": missing_entitlement_perks,
                }
            )
        unmarked_entitlement_perks = sorted(
            record_id
            for record_id in set(entitlement_kits_by_perk) & planner_ids_by_kind["perk"]
            if "class-entitlement"
            not in planner_by_id[record_id].get("selectionSources", [])
        )
        if unmarked_entitlement_perks:
            errors.append(
                {
                    "code": "planner-entitlement-perk-source-mismatch",
                    "ids": unmarked_entitlement_perks,
                }
            )
        missing_progression_perks = sorted(
            progression_member_ids
            - planner_ids_by_kind["perk"]
            - planner_ids_by_kind["ability"]
        )
        if missing_progression_perks:
            errors.append(
                {
                    "code": "planner-progression-perk-coverage-mismatch",
                    "ids": missing_progression_perks,
                }
            )
        unmarked_progression_perks = sorted(
            record_id
            for record_id in progression_member_ids & planner_ids_by_kind["perk"]
            if "progression-unlock"
            not in planner_by_id[record_id].get("selectionSources", [])
        )
        if unmarked_progression_perks:
            errors.append(
                {
                    "code": "planner-progression-perk-source-mismatch",
                    "ids": unmarked_progression_perks,
                }
            )
        if missing_names:
            errors.append(
                {"code": "planner-records-missing-display-name", "ids": sorted(missing_names)}
            )
        if invalid_ui_text:
            errors.append(
                {
                    "code": "planner-records-invalid-ui-text",
                    "records": sorted(
                        invalid_ui_text,
                        key=lambda item: (item["id"], item["field"]),
                    ),
                }
            )
        if text_source_mismatches:
            errors.append(
                {
                    "code": "planner-record-text-source-mismatch",
                    "records": sorted(
                        text_source_mismatches,
                        key=lambda item: item["id"],
                    ),
                }
            )
        if invalid_conditional_descriptions:
            errors.append(
                {
                    "code": "invalid-planner-conditional-descriptions",
                    "ids": sorted(invalid_conditional_descriptions),
                }
            )
        if conditional_description_source_mismatches:
            errors.append(
                {
                    "code": "planner-conditional-description-source-mismatch",
                    "ids": sorted(conditional_description_source_mismatches),
                }
            )
        if unresolved_conditional_descriptions:
            errors.append(
                {
                    "code": "planner-conditional-descriptions-unresolved",
                    "ids": sorted(unresolved_conditional_descriptions),
                }
            )
        if forbidden_mechanics:
            errors.append(
                {"code": "planner-records-leaked-out-of-scope-mechanics", "ids": sorted(forbidden_mechanics)}
            )
        required_descriptions = sorted(
            record["id"]
            for record in planner_records
            if isinstance(record, dict)
            and record.get("id") in missing_descriptions
            and record.get("kind") in {"ability", "augment", "item", "perk"}
        )
        if required_descriptions:
            errors.append(
                {
                    "code": "planner-records-missing-required-description",
                    "ids": required_descriptions,
                }
            )
        optional_descriptions = sorted(set(missing_descriptions) - set(required_descriptions))
        if optional_descriptions:
            warnings.append(
                {
                    "code": "planner-records-missing-description",
                    "count": len(optional_descriptions),
                    "ids": optional_descriptions,
                }
            )
        if unresolved_render:
            errors.append(
                {"code": "planner-grid-records-unresolved-render", "ids": sorted(unresolved_render)}
            )
        if invalid_perk_render_bindings:
            errors.append(
                {
                    "code": "planner-perk-render-bindings-invalid",
                    "ids": sorted(invalid_perk_render_bindings),
                }
            )
        if unresolved_compatibility:
            errors.append(
                {
                    "code": "planner-records-unresolved-compatibility",
                    "ids": sorted(unresolved_compatibility),
                }
            )
        if invalid_item_tiers:
            errors.append(
                {
                    "code": "planner-items-invalid-tier",
                    "ids": sorted(invalid_item_tiers),
                }
            )
        if undecoded_icons:
            errors.append(
                {
                    "code": "planner-records-missing-decoded-icon",
                    "ids": sorted(undecoded_icons),
                }
            )
        if invalid_weapon_slots:
            errors.append(
                {
                    "code": "planner-weapons-invalid-slot-layout",
                    "ids": sorted(set(invalid_weapon_slots)),
                }
            )
        if invalid_weapon_loadout_compatibility:
            errors.append(
                {
                    "code": "planner-weapons-invalid-loadout-compatibility",
                    "ids": sorted(set(invalid_weapon_loadout_compatibility)),
                }
            )
        perk_grid = planner_catalogue.get("perkGrid")
        layouts = perk_grid.get("kitLayouts") if isinstance(perk_grid, dict) else None
        placement_rules = (
            perk_grid.get("placementRules") if isinstance(perk_grid, dict) else None
        )
        modifier_rule = (
            placement_rules.get("modifier")
            if isinstance(placement_rules, dict)
            else None
        )
        rotation_rule = (
            placement_rules.get("rotation")
            if isinstance(placement_rules, dict)
            else None
        )
        if (
            not isinstance(modifier_rule, dict)
            or modifier_rule.get("adjacency") != "orthogonal-only"
            or modifier_rule.get("diagonalAdjacencyCounts") is not False
            or modifier_rule.get("selectedTargetField") != "targetId"
            or modifier_rule.get("targetSelectionRequired") is not True
            or modifier_rule.get("targetTraversal") != "directed-and-acyclic"
            or modifier_rule.get("adjacencyOffsets")
            != [
                {"column": -1, "row": 0},
                {"column": 0, "row": -1},
                {"column": 0, "row": 1},
                {"column": 1, "row": 0},
            ]
            or not isinstance(rotation_rule, dict)
            or rotation_rule.get("allowed") is not True
            or rotation_rule.get("recordField") != "records[].grid.allowedRotations"
        ):
            errors.append({"code": "invalid-planner-placement-rules"})
        if not isinstance(layouts, list):
            errors.append({"code": "invalid-planner-perk-grid"})
        else:
            layout_ids = [
                layout.get("kitId") if isinstance(layout, dict) else None
                for layout in layouts
            ]
            if (
                any(not isinstance(layout_id, str) for layout_id in layout_ids)
                or len(set(layout_ids)) != len(layout_ids)
                or set(layout_ids) != planner_ids_by_kind["kit"]
            ):
                errors.append(
                    {
                        "code": "planner-kit-grid-coverage-mismatch",
                        "kitIds": sorted(
                            value for value in layout_ids if isinstance(value, str)
                        ),
                    }
                )
            for layout in layouts:
                if not isinstance(layout, dict):
                    errors.append({"code": "invalid-planner-kit-grid", "kitId": None})
                    continue
                layout_id = layout.get("kitId")
                cells = layout.get("placeableCells")
                count = layout.get("placeableCellCount")
                expected_cells = {
                    (column, 0, f"{chr(ord('A') + column)}1")
                    for column in range(10)
                } | {
                    (column, row, f"{chr(ord('A') + column)}{row + 1}")
                    for row in range(1, 5)
                    for column in range(1, 9)
                }
                identities = [
                    (cell.get("column"), cell.get("row"))
                    for cell in cells
                    if isinstance(cell, dict)
                ] if isinstance(cells, list) else []
                if (
                    not isinstance(cells, list)
                    or type(count) is not int
                    or count != len(cells)
                    or count != 42
                    or len(identities) != len(cells)
                    or any(
                        type(column) is not int or type(row) is not int
                        for column, row in identities
                    )
                    or len(set(identities)) != len(identities)
                    or {
                        (cell.get("column"), cell.get("row"), cell.get("label"))
                        for cell in cells
                        if isinstance(cell, dict)
                    }
                    != expected_cells
                    or layout.get("baseBoard") != {"columns": 10, "rows": 5}
                    or layout.get("renderExtent") != {"columns": 10, "rows": 6}
                ):
                    errors.append(
                        {"code": "invalid-planner-kit-grid", "kitId": layout_id}
                    )
                anchors = layout.get("anchors")
                anchor_values = anchors if isinstance(anchors, list) else []
                expected_anchor_cells = {
                    "primary": {(0, row) for row in range(1, 5)},
                    "secondary": {(9, row) for row in range(1, 5)},
                    "passive": {(column, 5) for column in range(3, 7)},
                }
                unresolved_anchors = [
                    index
                    for index, anchor in enumerate(anchor_values)
                    if not isinstance(anchor, dict)
                    or not isinstance(anchor.get("rendering"), dict)
                    or anchor["rendering"].get("status") != "resolved"
                    or not _is_decoded_png(
                        anchor["rendering"].get("chipBody"),
                        path_prefix="grid-assets/textures/",
                    )
                ]
                invalid_anchor_contract = (
                    not isinstance(anchors, list)
                    or len(anchor_values) != 3
                    or {anchor.get("role") for anchor in anchor_values if isinstance(anchor, dict)}
                    != set(expected_anchor_cells)
                    or any(
                        {
                            (cell.get("column"), cell.get("row"))
                            for cell in anchor.get("cells", [])
                            if isinstance(cell, dict)
                        }
                        != expected_anchor_cells.get(anchor.get("role"), set())
                        or not isinstance(anchor.get("selectableAbilityIds"), list)
                        or anchor.get("selectableAbilityIds")
                        != (
                            planner_by_id.get(layout_id, {}).get(
                                "selectableAbilityIdsByRole", {}
                            )
                            or {}
                        ).get(anchor.get("role"))
                        or any(
                            not isinstance(value, str)
                            or value not in planner_ids_by_kind["ability"]
                            or planner_by_id[value].get("role") != anchor.get("role")
                            or layout_id
                            not in planner_by_id[value].get("availableToKitIds", [])
                            for value in anchor.get("selectableAbilityIds", [])
                        )
                        for anchor in anchor_values
                        if isinstance(anchor, dict)
                    )
                )
                if not isinstance(anchors, list) or unresolved_anchors:
                    errors.append(
                        {
                            "code": "planner-ability-anchors-unresolved-render",
                            "indexes": unresolved_anchors,
                            "kitId": layout_id,
                        }
                    )
                if invalid_anchor_contract:
                    errors.append(
                        {
                            "code": "invalid-planner-ability-anchor-contract",
                            "kitId": layout_id,
                        }
                    )
        planner_coverage = planner_catalogue.get("coverage")
        if not isinstance(planner_coverage, dict) or planner_coverage.get("records") != len(planner_records):
            errors.append({"code": "planner-catalogue-coverage-mismatch"})
        elif (
            planner_coverage.get("recordsMissingDescription")
            != len(missing_descriptions)
            or planner_coverage.get("recordsMissingDisplayName")
            != len(missing_names)
            or planner_coverage.get("recordsWithConditionalDescriptions")
            != sum(
                1
                for record in planner_records
                if isinstance(record, dict)
                and _valid_conditional_descriptions(
                    record.get("conditionalDescriptions")
                )
            )
        ):
            errors.append(
                {"code": "planner-description-coverage-mismatch"}
            )
        manifest_coverage = source_manifest.get("coverage")
        if (
            isinstance(manifest_coverage, dict)
            and manifest_coverage.get("plannerCatalogue") is not None
            and manifest_coverage.get("plannerCatalogue") != planner_coverage
        ):
            errors.append({"code": "planner-catalogue-manifest-coverage-mismatch"})
    unresolved_chip_visual_ids: list[str] = []

    def validate_candidate_references(
        record: dict[str, Any],
        *,
        field: str,
        targets: Any,
        expected_kind: str,
    ) -> None:
        if not isinstance(targets, list) or not all(isinstance(value, str) for value in targets):
            errors.append({"code": "invalid-candidate-reference-field", "field": field, "id": record.get("id")})
            return
        for target in targets:
            resolved = candidate_by_id.get(target)
            if resolved is None:
                errors.append(
                    {"code": "dangling-candidate-reference", "field": field, "id": record.get("id"), "target": target}
                )
            elif resolved.get("kind") != expected_kind:
                errors.append(
                    {
                        "actualKind": resolved.get("kind"),
                        "code": "candidate-reference-kind-mismatch",
                        "expectedKind": expected_kind,
                        "field": field,
                        "id": record.get("id"),
                        "target": target,
                    }
                )

    for record in candidate_records:
        if not isinstance(record, dict):
            continue
        chip_visual = record.get("chipVisual")
        if chip_visual is not None:
            if not isinstance(chip_visual, dict):
                errors.append({"code": "invalid-candidate-chip-visual", "id": record.get("id")})
            else:
                status = chip_visual.get("status")
                family = chip_visual.get("family")
                if status not in {"inferred", "resolved", "unresolved-family"} or (
                    status == "unresolved-family" and family is not None
                ) or (
                    status != "unresolved-family" and family not in {"core", "modifier", "replacer"}
                ):
                    errors.append(
                        {"code": "invalid-candidate-chip-visual", "id": record.get("id")}
                    )
                elif status == "unresolved-family" and isinstance(record.get("id"), str):
                    unresolved_chip_visual_ids.append(record["id"])
        if record.get("kind") == "perk" and "grid" in record:
            grid = record.get("grid")
            if not isinstance(grid, dict) or grid.get("allowedRotations") != [
                "Default",
                "Clockwise90",
                "Clockwise180",
                "Clockwise270",
            ]:
                errors.append({"code": "invalid-perk-grid-rotations", "id": record.get("id")})
            else:
                shapes = grid.get("shapes")
                if not isinstance(shapes, list) or not shapes:
                    errors.append({"code": "invalid-perk-grid-shapes", "id": record.get("id")})
                else:
                    for index, shape in enumerate(shapes):
                        if not isinstance(shape, dict):
                            errors.append(
                                {"code": "invalid-perk-grid-shape", "id": record.get("id"), "index": index}
                            )
                            continue
                        width = shape.get("width")
                        height = shape.get("height")
                        mask = shape.get("collisionMask")
                        occupied = shape.get("occupiedCells")
                        valid_dimensions = (
                            isinstance(width, int)
                            and not isinstance(width, bool)
                            and width > 0
                            and isinstance(height, int)
                            and not isinstance(height, bool)
                            and height > 0
                        )
                        expected_occupied = (
                            [
                                {"column": offset % width, "row": offset // width}
                                for offset, value in enumerate(mask)
                                if value != 0
                            ]
                            if valid_dimensions
                            and isinstance(mask, list)
                            and len(mask) == width * height
                            and all(isinstance(value, int) and not isinstance(value, bool) for value in mask)
                            else None
                        )
                        if (
                            expected_occupied is None
                            or occupied != expected_occupied
                            or shape.get("cellCount") != len(expected_occupied)
                        ):
                            errors.append(
                                {"code": "invalid-perk-grid-shape", "id": record.get("id"), "index": index}
                            )

        dependencies = record.get("dependencies")
        if dependencies is not None and not isinstance(dependencies, dict):
            errors.append({"code": "invalid-candidate-dependencies", "id": record.get("id")})
        elif isinstance(dependencies, dict):
            for field in ("possibleTargetPerkIds", "possibleModifierPerkIds"):
                if field in dependencies:
                    validate_candidate_references(
                        record,
                        field=f"dependencies.{field}",
                        targets=dependencies[field],
                        expected_kind="perk",
                    )

        eligibility = record.get("kitEligibility")
        if eligibility is not None and not isinstance(eligibility, dict):
            errors.append({"code": "invalid-candidate-kit-eligibility", "id": record.get("id")})
        elif isinstance(eligibility, dict):
            for field in ("restrictedKitId", "originKitId"):
                if field in eligibility:
                    validate_candidate_references(
                        record,
                        field=f"kitEligibility.{field}",
                        targets=[eligibility[field]],
                        expected_kind="kit",
                    )
            if "alternativeKitIds" in eligibility:
                validate_candidate_references(
                    record,
                    field="kitEligibility.alternativeKitIds",
                    targets=eligibility["alternativeKitIds"],
                    expected_kind="kit",
                )

        ability = record.get("ability")
        if ability is not None and not isinstance(ability, dict):
            errors.append({"code": "invalid-candidate-ability", "id": record.get("id")})
        elif isinstance(ability, dict):
            if ability.get("status") == "unresolved-role":
                warnings.append(
                    {
                        "code": "unresolved-candidate-ability-role",
                        "id": record.get("id"),
                        "roleRaw": ability.get("roleRaw"),
                    }
                )
            for field in ("originKitId",):
                if field in ability:
                    validate_candidate_references(
                        record,
                        field=f"ability.{field}",
                        targets=[ability[field]],
                        expected_kind="kit",
                    )
            if "availableToKitIds" in ability:
                validate_candidate_references(
                    record,
                    field="ability.availableToKitIds",
                    targets=ability["availableToKitIds"],
                    expected_kind="kit",
                )
            if "sourceChipIds" in ability:
                validate_candidate_references(
                    record,
                    field="ability.sourceChipIds",
                    targets=ability["sourceChipIds"],
                    expected_kind="perk",
                )
            if "aliasOf" in ability:
                validate_candidate_references(
                    record,
                    field="ability.aliasOf",
                    targets=[ability["aliasOf"]],
                    expected_kind="perk",
                )

        ability_roles = record.get("abilityPerkIdsByRole")
        if ability_roles is not None and not isinstance(ability_roles, dict):
            errors.append({"code": "invalid-candidate-ability-roles", "id": record.get("id")})
        elif isinstance(ability_roles, dict):
            for role in ("primary", "secondary", "passive"):
                if role in ability_roles:
                    validate_candidate_references(
                        record,
                        field=f"abilityPerkIdsByRole.{role}",
                        targets=ability_roles[role],
                        expected_kind="perk",
                    )

        implementations = record.get("implementationForAbilityIds")
        if implementations is not None:
            validate_candidate_references(
                record,
                field="implementationForAbilityIds",
                targets=implementations,
                expected_kind="perk",
            )

        ability_slots = record.get("abilitySlots")
        if ability_slots is not None and not isinstance(ability_slots, list):
            errors.append({"code": "invalid-candidate-ability-slots", "id": record.get("id")})
        elif isinstance(ability_slots, list):
            for index, slot in enumerate(ability_slots):
                if not isinstance(slot, dict):
                    errors.append(
                        {
                            "code": "invalid-candidate-ability-slot",
                            "id": record.get("id"),
                            "index": index,
                        }
                    )
                    continue
                if "lockedChipId" in slot:
                    validate_candidate_references(
                        record,
                        field=f"abilitySlots[{index}].lockedChipId",
                        targets=[slot["lockedChipId"]],
                        expected_kind="perk",
                    )
                if "selectableAbilityPerkIds" in slot:
                    validate_candidate_references(
                        record,
                        field=f"abilitySlots[{index}].selectableAbilityPerkIds",
                        targets=slot["selectableAbilityPerkIds"],
                        expected_kind="perk",
                    )

        entitlements = record.get("chipEntitlements")
        if entitlements is not None and not isinstance(entitlements, list):
            errors.append({"code": "invalid-candidate-chip-entitlements", "id": record.get("id")})
        elif isinstance(entitlements, list):
            for index, entitlement in enumerate(entitlements):
                if not isinstance(entitlement, dict):
                    errors.append(
                        {
                            "code": "invalid-candidate-chip-entitlement",
                            "id": record.get("id"),
                            "index": index,
                        }
                    )
                    continue
                if "perkId" in entitlement:
                    validate_candidate_references(
                        record,
                        field=f"chipEntitlements[{index}].perkId",
                        targets=[entitlement["perkId"]],
                        expected_kind="perk",
                    )

        perk_board = record.get("perkBoard")
        if perk_board is not None and not isinstance(perk_board, dict):
            errors.append({"code": "invalid-candidate-perk-board", "id": record.get("id")})
        elif isinstance(perk_board, dict):
            if "recordId" in perk_board:
                validate_candidate_references(
                    record,
                    field="perkBoard.recordId",
                    targets=[perk_board["recordId"]],
                    expected_kind="gridShape",
                )
            placements = perk_board.get("lockedPlacements")
            if placements is not None and not isinstance(placements, list):
                errors.append(
                    {"code": "invalid-candidate-locked-placements", "id": record.get("id")}
                )
            elif isinstance(placements, list):
                for index, placement in enumerate(placements):
                    if not isinstance(placement, dict):
                        errors.append(
                            {
                                "code": "invalid-candidate-locked-placement",
                                "id": record.get("id"),
                                "index": index,
                            }
                        )
                        continue
                    if "chipId" in placement:
                        validate_candidate_references(
                            record,
                            field=f"perkBoard.lockedPlacements[{index}].chipId",
                            targets=[placement["chipId"]],
                            expected_kind="perk",
                        )

        weapon_slots = record.get("weaponSlots")
        if weapon_slots is not None and not isinstance(weapon_slots, list):
            errors.append({"code": "invalid-candidate-weapon-slots", "id": record.get("id")})
        elif isinstance(weapon_slots, list):
            for index, slot in enumerate(weapon_slots):
                if not isinstance(slot, dict):
                    errors.append(
                        {
                            "code": "invalid-candidate-weapon-slot",
                            "id": record.get("id"),
                            "index": index,
                        }
                    )
                    continue
                if "defaultWeaponId" in slot:
                    validate_candidate_references(
                        record,
                        field=f"weaponSlots[{index}].defaultWeaponId",
                        targets=[slot["defaultWeaponId"]],
                        expected_kind="weapon",
                    )

    counts = Counter(item.get("kind") for item in candidate_records if isinstance(item, dict))
    for kind in CANDIDATE_KINDS:
        if counts[kind] == 0:
            warnings.append({"code": "empty-candidate-kind", "kind": kind})

    archive_failures = [
        archive
        for archive in source_manifest.get("archives", [])
        if archive.get("scanStatus") in {"failed", "unscanned", "unverified"}
    ]
    for archive in archive_failures:
        warnings.append(
            {
                "archive": archive.get("relativePath"),
                "code": "archive-not-scanned",
                "status": archive.get("scanStatus"),
            }
        )

    for warning in source_manifest.get("adapterWarnings", []):
        if isinstance(warning, dict):
            warnings.append({"code": "adapter-warning", **warning})

    if unresolved_chip_visual_ids:
        warnings.append(
            {
                "code": "unresolved-perk-visual-families",
                "count": len(unresolved_chip_visual_ids),
                "ids": sorted(unresolved_chip_visual_ids),
            }
        )
    if strict and warnings:
        errors.extend({"code": "strict-warning", "warning": warning} for warning in warnings)

    return {
        "schemaVersion": 1,
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "candidateCounts": {kind: counts[kind] for kind in CANDIDATE_KINDS},
            "packages": len(packages),
            "plannerRecords": planner_record_count,
        },
    }
