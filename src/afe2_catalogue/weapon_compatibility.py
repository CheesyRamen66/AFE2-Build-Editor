"""Resolve AFE2 weapon slots and attachment compatibility from UE exports.

The game stores the player-facing sockets in ``CoreGun.PartSlots`` and stores
the second half of compatibility on each ``GunModDef`` in ``GunEquipRules``.
Both properties obey normal Blueprint CDO inheritance: an omitted property is
inherited, while an authored array replaces the inherited array.

This module intentionally has no extractor or catalogue I/O.  It accepts the
raw assets returned by the semantic reader plus already-normalized catalogue
records and returns deep-copied, enriched records.  That keeps the rule engine
testable independently of the archive and publication pipeline.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


_ATTACHMENT_KINDS = frozenset({"mod", "trait", "augment"})
_KNOWN_RULE_TYPES = frozenset(
    {
        "Default",
        "GunType",
        "GunSubType",
        "GunTypeAndSubType",
        "SpecificChassis",
        "SpecificChassisList",
        "ForbiddenChassisList",
        "ChassisTags",
        "ComplexChassisTags",
        "ComplexAttachmentTags",
    }
)
_NATIVE_ENUM_DEFAULTS = {
    "GunAvoType": "EGunAvoType::Any",
    "GunType": "EGunType::Handgun",
    "GunSubType": "EGunSubType::Any",
}


@dataclass(frozen=True)
class WeaponCompatibilityBuild:
    """Pure result returned by :func:`build_weapon_compatibility`."""

    records: list[dict[str, Any]]
    coverage: dict[str, int]
    diagnostics: dict[str, list[dict[str, Any]]]


@dataclass(frozen=True)
class _PropertySource:
    prop: Mapping[str, Any]
    owner: Mapping[str, Any]
    export_name: str


@dataclass(frozen=True)
class _MaterializedAsset:
    properties: dict[str, _PropertySource]
    complete: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class _Weapon:
    record_id: str
    package_path: str
    complete: bool
    reasons: tuple[str, ...]
    gun_avo_type_raw: str
    gun_type_raw: str
    gun_sub_type_raw: str
    kit_tags: tuple[str, ...]
    kit_ignore_tags: tuple[str, ...]
    chassis_tags: tuple[str, ...]
    all_slots: tuple[dict[str, Any], ...]
    visible_slots: tuple[dict[str, Any], ...]
    property_owners: dict[str, str]


@dataclass(frozen=True)
class _Attachment:
    record_id: str
    package_path: str
    kind: str
    complete: bool
    reasons: tuple[str, ...]
    tags: tuple[str, ...]
    rules: tuple[dict[str, Any], ...]
    property_owners: dict[str, str]


def _properties(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _property_map(value: Any) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for item in _properties(value):
        name = item.get("Name")
        if isinstance(name, str) and name not in result:
            result[name] = item
    return result


def _default_export(asset: Mapping[str, Any]) -> Mapping[str, Any] | None:
    exports = asset.get("exports")
    if not isinstance(exports, list):
        return None
    candidates = [item for item in exports if isinstance(item, Mapping)]
    for item in candidates:
        if str(item.get("objectName", "")).startswith("Default__"):
            return item
    return candidates[0] if candidates else None


def _import_parent_identity(asset: Mapping[str, Any], index: Any) -> str | None:
    imports = asset.get("imports")
    if not isinstance(imports, list) or not isinstance(index, int) or index >= 0:
        return None
    position = -index - 1
    if position >= len(imports) or not isinstance(imports[position], Mapping):
        return None
    leaf = imports[position].get("objectName")
    if not isinstance(leaf, str):
        return None
    seen: set[int] = set()
    current = index
    while current < 0 and current not in seen:
        seen.add(current)
        position = -current - 1
        if position >= len(imports) or not isinstance(imports[position], Mapping):
            return None
        item = imports[position]
        name = item.get("objectName")
        if isinstance(name, str) and name.startswith("/Game/"):
            return name.split(".", 1)[0]
        if isinstance(name, str) and name.startswith("/Script/"):
            return name if leaf == name else f"{name}.{leaf}"
        outer = item.get("outerIndex")
        if not isinstance(outer, int):
            return None
        current = outer
    return None


def _parent_identity(asset: Mapping[str, Any]) -> str | None:
    exports = asset.get("exports")
    if not isinstance(exports, list):
        return None
    generated_class = next(
        (
            item
            for item in exports
            if isinstance(item, Mapping)
            and str(item.get("objectName", "")).endswith("_C")
            and not str(item.get("objectName", "")).startswith("Default__")
        ),
        None,
    )
    if generated_class is None:
        return None
    return _import_parent_identity(asset, generated_class.get("superIndex"))


def _import_package(asset: Mapping[str, Any], index: Any) -> str | None:
    imports = asset.get("imports")
    if not isinstance(imports, list) or not isinstance(index, int) or index >= 0:
        return None
    current = index
    seen: set[int] = set()
    while current < 0 and current not in seen:
        seen.add(current)
        position = -current - 1
        if position >= len(imports) or not isinstance(imports[position], Mapping):
            return None
        item = imports[position]
        name = item.get("objectName")
        if isinstance(name, str) and name.startswith("/Game/"):
            return name.split(".", 1)[0]
        outer = item.get("outerIndex")
        if not isinstance(outer, int):
            return None
        current = outer
    return None


def _materialize_assets(
    assets_by_package: Mapping[str, Mapping[str, Any]],
) -> dict[str, _MaterializedAsset]:
    cache: dict[str, _MaterializedAsset] = {}
    visiting: set[str] = set()

    def resolve(package_path: str) -> _MaterializedAsset:
        cached = cache.get(package_path)
        if cached is not None:
            return cached
        asset = assets_by_package[package_path]
        if package_path in visiting:
            return _MaterializedAsset(
                properties={},
                complete=False,
                reasons=("Blueprint parent graph contained a cycle",),
            )
        visiting.add(package_path)
        parent = _parent_identity(asset)
        properties: dict[str, _PropertySource] = {}
        complete = True
        reasons: list[str] = []
        if isinstance(parent, str) and parent.startswith("/Game/"):
            if parent in assets_by_package:
                inherited = resolve(parent)
                properties.update(inherited.properties)
                complete = inherited.complete
                reasons.extend(inherited.reasons)
            else:
                complete = False
                reasons.append(f"Blueprint parent asset was unavailable: {parent}")
        elif not isinstance(parent, str) or not parent.startswith("/Script/"):
            complete = False
            reasons.append("generated class parent could not be resolved")
        export = _default_export(asset)
        if export is None:
            complete = False
            reasons.append("asset had no default-object export")
        else:
            export_name = str(export.get("objectName", ""))
            for name, prop in _property_map(export.get("data")).items():
                properties[name] = _PropertySource(prop, asset, export_name)
        visiting.discard(package_path)
        result = _MaterializedAsset(
            properties=properties,
            complete=complete,
            reasons=tuple(dict.fromkeys(reasons)),
        )
        cache[package_path] = result
        return result

    for package_path in assets_by_package:
        resolve(package_path)
    return cache


def _enum(prop: Mapping[str, Any] | None) -> str | None:
    if prop is None:
        return None
    for key in ("EnumValue", "Value"):
        value = prop.get(key)
        if isinstance(value, str):
            return value
    return None


def _enum_tail(value: str | None) -> str | None:
    return value.rsplit("::", 1)[-1] if value else None


def _normalized_enum(value: str) -> str:
    tail = _enum_tail(value) or value
    special = {
        "CQW": "cqw",
        "DMR": "dmr",
        "MAX": "max",
        "SMG": "smg",
    }
    return special.get(tail, tail[:1].lower() + tail[1:])


def _gameplay_tags(value: Any) -> list[str]:
    tags: list[str] = []
    if isinstance(value, list):
        for child in value:
            tags.extend(_gameplay_tags(child))
    elif isinstance(value, Mapping):
        type_name = str(value.get("$type", ""))
        raw = value.get("Value")
        if "GameplayTagContainerPropertyData" in type_name and isinstance(raw, list):
            tags.extend(item for item in raw if isinstance(item, str) and item)
        elif value.get("Name") == "TagName" and isinstance(raw, str) and raw:
            tags.append(raw)
        else:
            for child in value.values():
                if isinstance(child, (Mapping, list)):
                    tags.extend(_gameplay_tags(child))
    return sorted(set(tags))


def _soft_object_packages(value: Any) -> list[str]:
    packages: list[str] = []
    if isinstance(value, list):
        for child in value:
            packages.extend(_soft_object_packages(child))
    elif isinstance(value, Mapping):
        asset_path = value.get("AssetPath")
        if isinstance(asset_path, Mapping):
            for key in ("PackageName", "AssetName"):
                raw = asset_path.get(key)
                if isinstance(raw, str) and raw.startswith("/Game/"):
                    packages.append(raw.split(".", 1)[0])
                    break
        for key, child in value.items():
            if key != "AssetPath" and isinstance(child, (Mapping, list)):
                packages.extend(_soft_object_packages(child))
    return list(dict.fromkeys(packages))


def _object_package(source: _PropertySource | None) -> str | None:
    if source is None:
        return None
    value = source.prop.get("Value")
    packages = _soft_object_packages(value)
    if packages:
        return packages[0]
    return _import_package(source.owner, value)


def _bool(prop: Mapping[str, Any] | None) -> bool:
    return bool((prop or {}).get("Value"))


def _integer(prop: Mapping[str, Any] | None) -> int | None:
    value = (prop or {}).get("Value")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _text(prop: Mapping[str, Any] | None) -> str | None:
    if prop is None:
        return None
    for key in ("CultureInvariantString", "SourceValue"):
        value = prop.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _tag_matches(candidate: str, required: str) -> bool:
    """Mirror GameplayTag ``HasTag`` using serialized tag names."""

    return candidate == required or candidate.startswith(f"{required}.")


def _has_tag(tags: Sequence[str], required: str) -> bool:
    return any(_tag_matches(candidate, required) for candidate in tags)


def _has_all_tags(tags: Sequence[str], required: Sequence[str]) -> bool:
    return all(_has_tag(tags, tag) for tag in required)


def _has_any_tag(tags: Sequence[str], queried: Sequence[str]) -> bool:
    return any(_has_tag(tags, tag) for tag in queried)


def _slot_kind(required_tags: Sequence[str]) -> str:
    if _has_tag(required_tags, "Item.Attachment.Overclock"):
        return "augment"
    if _has_tag(required_tags, "Item.Attachment.Mod"):
        return "trait"
    if _has_tag(required_tags, "Item.Attachment"):
        return "component"
    return "other"


def _normalize_slot(
    item: Mapping[str, Any],
    *,
    index: int,
    owner: Mapping[str, Any],
) -> dict[str, Any]:
    fields = _property_map(item.get("Value"))
    required_tags = _gameplay_tags(fields.get("RequiredModTags"))
    slot_tags = _gameplay_tags(fields.get("SlotTags"))
    default_source = (
        _PropertySource(fields["DefaultSlottedMod"], owner, "")
        if "DefaultSlottedMod" in fields
        else None
    )
    result: dict[str, Any] = {
        "appearanceOnly": _bool(fields.get("bIsAppearanceOnlySlot")),
        "hidden": _bool(fields.get("bHideFromUI")),
        "index": index,
        "kind": _slot_kind(required_tags),
        "requiredModTags": required_tags,
        "slotTags": slot_tags,
    }
    default_id = _object_package(default_source)
    display_name = _text(fields.get("SlotDisplayName"))
    required_level = _integer(fields.get("RequiredLevel"))
    if default_id is not None:
        result["defaultAttachmentId"] = default_id
    if display_name is not None:
        result["displayName"] = display_name
    if required_level is not None:
        result["requiredLevel"] = required_level
    return result


def _normalize_rule(item: Mapping[str, Any], *, index: int) -> dict[str, Any]:
    fields = _property_map(item.get("Value"))
    type_raw = _enum(fields.get("RuleType"))
    rule_type = _enum_tail(type_raw)
    chassis = _soft_object_packages((fields.get("Chassis") or {}).get("Value"))
    chassis_list = _soft_object_packages((fields.get("ChassisList") or {}).get("Value"))
    gun_type_raw = _enum(fields.get("GunType"))
    gun_sub_type_raw = _enum(fields.get("GunSubType"))
    result: dict[str, Any] = {
        "chassisIds": chassis_list,
        "forbiddenTags": _gameplay_tags(fields.get("ForbiddenChassisTags")),
        "index": index,
        "requiredTags": _gameplay_tags(fields.get("RequiredChassisTags")),
        "type": rule_type,
        "typeRaw": type_raw,
    }
    if chassis:
        result["chassisId"] = chassis[0]
    if gun_type_raw is not None:
        result["gunType"] = _enum_tail(gun_type_raw)
        result["gunTypeRaw"] = gun_type_raw
    if gun_sub_type_raw is not None:
        result["gunSubType"] = _enum_tail(gun_sub_type_raw)
        result["gunSubTypeRaw"] = gun_sub_type_raw
    return result


def evaluate_equip_rules(
    rules: Sequence[Mapping[str, Any]],
    *,
    weapon_package_path: str,
    gun_type: str,
    gun_sub_type: str,
    chassis_tags: Sequence[str],
    part_slot_required_tags: Sequence[Sequence[str]],
) -> bool:
    """Evaluate normalized ``GunModEquipRule`` entries in native order.

    Positive rule types are alternatives and return on their first match.
    ``ForbiddenChassisList`` is different: membership returns false
    immediately, while non-membership merely advances to the next rule.  This
    ordered behavior mirrors the shipped native switch, rather than treating
    every rule as an unordered allow/deny set.

    ``ComplexAttachmentTags`` is also static.  Despite its name, the game
    compares its tags with each weapon ``PartSlots.RequiredModTags`` container,
    not with the player's currently equipped attachment instances.
    """

    for rule in rules:
        rule_type = rule.get("type")
        if rule_type == "Default":
            return True
        if rule_type == "GunType":
            if gun_type == rule.get("gunType"):
                return True
            continue
        if rule_type == "GunSubType":
            if gun_sub_type == rule.get("gunSubType"):
                return True
            continue
        if rule_type == "GunTypeAndSubType":
            if gun_type == rule.get("gunType") and gun_sub_type == rule.get("gunSubType"):
                return True
            continue
        if rule_type == "SpecificChassis":
            if weapon_package_path == rule.get("chassisId"):
                return True
            continue
        if rule_type == "SpecificChassisList":
            if weapon_package_path in rule.get("chassisIds", ()):
                return True
            continue
        if rule_type == "ForbiddenChassisList":
            if weapon_package_path in rule.get("chassisIds", ()):
                return False
            continue
        if rule_type == "ChassisTags":
            if _has_all_tags(chassis_tags, rule.get("requiredTags", ())):
                return True
            continue
        if rule_type == "ComplexChassisTags":
            if _has_all_tags(chassis_tags, rule.get("requiredTags", ())) and not _has_any_tag(
                chassis_tags, rule.get("forbiddenTags", ())
            ):
                return True
            continue
        if rule_type == "ComplexAttachmentTags":
            forbidden = rule.get("forbiddenTags", ())
            if any(_has_any_tag(slot_tags, forbidden) for slot_tags in part_slot_required_tags):
                return False
            required = rule.get("requiredTags", ())
            if any(_has_all_tags(slot_tags, required) for slot_tags in part_slot_required_tags):
                return True
            continue
        # Unknown rule types cannot positively prove compatibility.
    return False


def _source_owner(source: _PropertySource | None) -> str | None:
    package = (source.owner if source else {}).get("packagePath")
    return package if isinstance(package, str) else None


def _weapon_from_asset(
    record: Mapping[str, Any],
    asset: Mapping[str, Any],
    materialized: _MaterializedAsset,
) -> _Weapon:
    reasons = list(materialized.reasons)
    properties = materialized.properties
    enum_values: dict[str, str] = {}
    owners: dict[str, str] = {}
    for name, native_default in _NATIVE_ENUM_DEFAULTS.items():
        source = properties.get(name)
        value = _enum(source.prop if source else None)
        enum_values[name] = value or native_default
        owner = _source_owner(source)
        owners[name] = owner or "native-default"
    kit_tags_source = properties.get("GunKitTags")
    kit_ignore_tags_source = properties.get("GunKitIgnoreTags")
    chassis_source = properties.get("ChassisTags")
    part_slots_source = properties.get("PartSlots")
    owners["GunKitTags"] = _source_owner(kit_tags_source) or "native-default"
    owners["GunKitIgnoreTags"] = (
        _source_owner(kit_ignore_tags_source) or "native-default"
    )
    owners["ChassisTags"] = _source_owner(chassis_source) or "native-default"
    if part_slots_source is None:
        reasons.append("effective PartSlots property was unavailable")
        all_slots: list[dict[str, Any]] = []
    else:
        owners["PartSlots"] = _source_owner(part_slots_source) or "unknown"
        all_slots = [
            _normalize_slot(item, index=index, owner=part_slots_source.owner)
            for index, item in enumerate(_properties(part_slots_source.prop.get("Value")))
        ]
    visible_slots = [
        slot for slot in all_slots if not slot["hidden"] and not slot["appearanceOnly"]
    ]
    record_id = record.get("id")
    package_path = record.get("packagePath")
    return _Weapon(
        record_id=record_id if isinstance(record_id, str) else str(package_path),
        package_path=str(package_path),
        complete=materialized.complete and part_slots_source is not None,
        reasons=tuple(dict.fromkeys(reasons)),
        gun_avo_type_raw=enum_values["GunAvoType"],
        gun_type_raw=enum_values["GunType"],
        gun_sub_type_raw=enum_values["GunSubType"],
        kit_tags=tuple(_gameplay_tags(kit_tags_source.prop if kit_tags_source else None)),
        kit_ignore_tags=tuple(
            _gameplay_tags(
                kit_ignore_tags_source.prop if kit_ignore_tags_source else None
            )
        ),
        chassis_tags=tuple(_gameplay_tags(chassis_source.prop if chassis_source else None)),
        all_slots=tuple(all_slots),
        visible_slots=tuple(visible_slots),
        property_owners=owners,
    )


def _attachment_from_asset(
    record: Mapping[str, Any],
    materialized: _MaterializedAsset,
) -> _Attachment:
    properties = materialized.properties
    tags_source = properties.get("Tags")
    rules_source = properties.get("GunEquipRules")
    reasons = list(materialized.reasons)
    rules = [
        _normalize_rule(item, index=index)
        for index, item in enumerate(
            _properties(rules_source.prop.get("Value") if rules_source else None)
        )
    ]
    unknown = sorted(
        {
            str(rule.get("type"))
            for rule in rules
            if rule.get("type") not in _KNOWN_RULE_TYPES
        }
    )
    if unknown:
        reasons.append(f"unknown GunModEquipRule type(s): {', '.join(unknown)}")
    record_id = record.get("id")
    package_path = record.get("packagePath")
    return _Attachment(
        record_id=record_id if isinstance(record_id, str) else str(package_path),
        package_path=str(package_path),
        kind=str(record.get("kind")),
        complete=materialized.complete and not unknown,
        reasons=tuple(dict.fromkeys(reasons)),
        tags=tuple(_gameplay_tags(tags_source.prop if tags_source else None)),
        rules=tuple(rules),
        property_owners={
            "GunEquipRules": _source_owner(rules_source) or "native-default",
            "Tags": _source_owner(tags_source) or "native-default",
        },
    )


def _attachment_fits_slot(attachment: _Attachment, slot: Mapping[str, Any]) -> bool:
    expected_kind = {
        "augment": "augment",
        "component": "mod",
        "trait": "trait",
    }.get(slot.get("kind"))
    if expected_kind is None or attachment.kind != expected_kind:
        return False
    required = slot.get("requiredModTags")
    return (
        isinstance(required, list)
        and bool(required)
        and _has_all_tags(attachment.tags, required)
    )


def _attachment_fits_weapon(attachment: _Attachment, weapon: _Weapon) -> bool:
    return evaluate_equip_rules(
        attachment.rules,
        weapon_package_path=weapon.package_path,
        gun_type=_enum_tail(weapon.gun_type_raw) or "",
        gun_sub_type=_enum_tail(weapon.gun_sub_type_raw) or "",
        chassis_tags=weapon.chassis_tags,
        part_slot_required_tags=tuple(
            tuple(slot["requiredModTags"]) for slot in weapon.all_slots
        ),
    )


def _record_assets(
    candidate_assets: Sequence[Mapping[str, Any]],
    parent_assets: Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    assets: dict[str, Mapping[str, Any]] = {}
    for asset in (*parent_assets, *candidate_assets):
        package = asset.get("packagePath") if isinstance(asset, Mapping) else None
        if not isinstance(package, str):
            raise ValueError("semantic asset was missing packagePath")
        previous = assets.get(package)
        if previous is not None and previous != asset:
            raise ValueError(
                f"semantic asset package was duplicated with different data: {package}"
            )
        assets[package] = asset
    return assets


def build_weapon_compatibility(
    *,
    records: Sequence[Mapping[str, Any]],
    candidate_assets: Sequence[Mapping[str, Any]],
    parent_assets: Sequence[Mapping[str, Any]] = (),
) -> WeaponCompatibilityBuild:
    """Deep-copy and enrich normalized weapon/attachment records.

    The returned ``compatibility`` object is deliberately self-contained:

    * weapons expose serialized category/role/subtype, chassis tags, every
      player-visible slot, and compatible IDs per slot and per record kind;
    * mods, traits, and augments expose their effective tags, effective ordered
      equip rules, and compatible weapon IDs;
    * incomplete parent chains or unknown rules are reported as unresolved and
      never receive guessed compatibility lists.
    """

    assets_by_package = _record_assets(candidate_assets, parent_assets)
    materialized = _materialize_assets(assets_by_package)
    output = copy.deepcopy(list(records))
    records_by_package: dict[str, dict[str, Any]] = {}
    duplicate_record_packages: set[str] = set()
    for record in output:
        package = record.get("packagePath")
        if not isinstance(package, str):
            continue
        if package in records_by_package:
            duplicate_record_packages.add(package)
        records_by_package[package] = record
    if duplicate_record_packages:
        joined = ", ".join(sorted(duplicate_record_packages))
        raise ValueError(f"catalogue record package was duplicated: {joined}")

    unresolved: list[dict[str, Any]] = []
    layout_anomalies: list[dict[str, Any]] = []
    weapons: dict[str, _Weapon] = {}
    attachments: dict[str, _Attachment] = {}
    for package, record in records_by_package.items():
        kind = record.get("kind")
        if kind != "weapon" and kind not in _ATTACHMENT_KINDS:
            continue
        asset = assets_by_package.get(package)
        effective = materialized.get(package)
        if asset is None or effective is None:
            record["compatibility"] = {
                "reasons": ["semantic candidate asset was unavailable"],
                "status": "unresolved",
            }
            unresolved.append(
                {
                    "id": record.get("id", package),
                    "reason": "semantic candidate asset was unavailable",
                }
            )
            continue
        if kind == "weapon":
            weapon = _weapon_from_asset(record, asset, effective)
            weapons[package] = weapon
            counts = {
                slot_kind: sum(slot["kind"] == slot_kind for slot in weapon.visible_slots)
                for slot_kind in ("augment", "component", "other", "trait")
            }
            if counts != {"augment": 1, "component": 3, "other": 0, "trait": 1}:
                layout_anomalies.append(
                    {"id": weapon.record_id, "playerVisibleSlotCounts": counts}
                )
        else:
            attachment = _attachment_from_asset(record, effective)
            attachments[package] = attachment

    resolved_weapons = [weapon for weapon in weapons.values() if weapon.complete]
    resolved_attachments = [
        attachment for attachment in attachments.values() if attachment.complete
    ]
    matches_by_slot: dict[tuple[str, int], list[str]] = {}
    weapons_by_attachment: dict[str, list[str]] = {
        attachment.package_path: [] for attachment in resolved_attachments
    }
    for weapon in resolved_weapons:
        for slot in weapon.visible_slots:
            compatible: list[str] = []
            for attachment in resolved_attachments:
                if not _attachment_fits_slot(attachment, slot):
                    continue
                if not _attachment_fits_weapon(attachment, weapon):
                    continue
                compatible.append(attachment.record_id)
                weapons_by_attachment[attachment.package_path].append(weapon.record_id)
            matches_by_slot[(weapon.package_path, int(slot["index"]))] = sorted(set(compatible))

    for package, weapon in weapons.items():
        record = records_by_package[package]
        if not weapon.complete:
            reasons = list(weapon.reasons) or ["weapon semantic inheritance was incomplete"]
            record["compatibility"] = {"reasons": reasons, "status": "unresolved"}
            unresolved.append({"id": weapon.record_id, "reason": "; ".join(reasons)})
            continue
        slots: list[dict[str, Any]] = []
        compatible_by_kind: dict[str, set[str]] = {
            "augment": set(),
            "component": set(),
            "trait": set(),
        }
        for raw_slot in weapon.visible_slots:
            slot = copy.deepcopy(raw_slot)
            compatible_ids = matches_by_slot[(package, int(slot["index"]))]
            slot["compatibleIds"] = compatible_ids
            if slot["kind"] in compatible_by_kind:
                compatible_by_kind[slot["kind"]].update(compatible_ids)
            slots.append(slot)
        record["compatibility"] = {
            "chassisTags": list(weapon.chassis_tags),
            "collectionCategory": _normalized_enum(weapon.gun_type_raw),
            "collectionCategoryRaw": weapon.gun_type_raw,
            "compatibleAugmentIds": sorted(compatible_by_kind["augment"]),
            "compatibleModIds": sorted(compatible_by_kind["component"]),
            "compatibleTraitIds": sorted(compatible_by_kind["trait"]),
            "hiddenOrAppearanceSlotCount": len(weapon.all_slots) - len(weapon.visible_slots),
            "kitIgnoreTags": list(weapon.kit_ignore_tags),
            "kitTags": list(weapon.kit_tags),
            "propertyOwners": weapon.property_owners,
            "slots": slots,
            "source": "serialized-uasset",
            "status": "resolved",
            "weaponRole": _normalized_enum(weapon.gun_avo_type_raw),
            "weaponRoleRaw": weapon.gun_avo_type_raw,
            "weaponSubType": _normalized_enum(weapon.gun_sub_type_raw),
            "weaponSubTypeRaw": weapon.gun_sub_type_raw,
        }

    for package, attachment in attachments.items():
        record = records_by_package[package]
        if not attachment.complete:
            reasons = list(attachment.reasons) or ["attachment semantic inheritance was incomplete"]
            record["compatibility"] = {"reasons": reasons, "status": "unresolved"}
            unresolved.append({"id": attachment.record_id, "reason": "; ".join(reasons)})
            continue
        record["compatibility"] = {
            "compatibleWeaponIds": sorted(set(weapons_by_attachment.get(package, []))),
            "propertyOwners": attachment.property_owners,
            "rules": [copy.deepcopy(rule) for rule in attachment.rules],
            "source": "serialized-uasset",
            "status": "resolved",
            "tags": list(attachment.tags),
        }

    coverage = {
        "attachmentsResolved": len(resolved_attachments),
        "attachmentsTotal": len(attachments),
        "compatibilityPairs": sum(
            len(set(values)) for values in weapons_by_attachment.values()
        ),
        "recordsEnriched": len(weapons) + len(attachments),
        "weaponsResolved": len(resolved_weapons),
        "weaponsTotal": len(weapons),
    }
    return WeaponCompatibilityBuild(
        records=output,
        coverage=coverage,
        diagnostics={
            "layoutAnomalies": sorted(layout_anomalies, key=lambda item: str(item["id"])),
            "unresolved": sorted(unresolved, key=lambda item: str(item["id"])),
        },
    )
