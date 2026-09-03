"""Pure normalization of the player-visible AFE2 armory catalogue.

The shipping ``Store_MainHub_Credits`` asset is the authoritative list of
entries shown by the armory/Collection UI.  Most products point directly at a
catalogue definition.  Augments are the exception: the store points at an
``AugmentPackDef``, which points at a reward table whose selected reward rows
point at the weapon-specific augment implementations.

This module deliberately has no archive or filesystem dependencies.  It works
on the trimmed asset dictionaries emitted by ``afe2-semantic-reader`` so the
extractor can discover dependencies in stages and normalize them afterwards.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence


PLANNER_CATEGORY_KINDS: dict[str, str] = {
    "Weapons": "weapon",
    "Magazines": "mod",
    "Optics": "mod",
    "Underbarrel": "mod",
    "Muzzles": "mod",
    "Barrels": "mod",
    "Armature": "mod",
    "Traits": "trait",
    "AugmentPacks": "augment",
    "Items": "item",
    "Perks": "perk",
}

# These are present in the same authored store but are deliberately outside the
# build planner.  Keeping the ignore set explicit lets validation distinguish a
# known non-build tab from a newly introduced category that needs review.
IGNORED_COLLECTION_CATEGORIES = frozenset({"Challenge Cards", "Divider"})

_ITEM_TIER_TAGS = {
    "Ability.Consumable.InventoryType.Major": "major",
    "Ability.Consumable.InventoryType.Minor": "minor",
}

_CHARACTER_UNLOCK_TOKEN = "/Script/Endeavor.CharacterUnlockToken"
_NATIVE_REWARD_TABLE = "/Script/Endeavor.RewardTable"


class CollectionFormatError(ValueError):
    """Raised when the canonical store asset itself cannot be normalized."""


def _properties(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


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


def _blueprint_default_export(asset: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Return only an authored Blueprint class-default object.

    Reward-table inheritance is catalogue-admission evidence. Falling back to
    a ClassExport (as the permissive generic helper does) can make a malformed
    child appear to inherit an otherwise valid reward table.
    """

    exports = asset.get("exports")
    if not isinstance(exports, list):
        return None
    return next(
        (
            item
            for item in exports
            if isinstance(item, Mapping)
            and str(item.get("objectName", "")).startswith("Default__")
        ),
        None,
    )


def _package_path(value: Any) -> str | None:
    """Normalize a serialized Unreal object path to its package identity."""

    if not isinstance(value, str) or not value.startswith("/Game/"):
        return None
    dot = value.find(".", value.rfind("/"))
    return value[:dot] if dot >= 0 else value


def _soft_packages(value: Any) -> list[str]:
    result: list[str] = []
    if isinstance(value, list):
        for child in value:
            result.extend(_soft_packages(child))
    elif isinstance(value, Mapping):
        asset_path = value.get("AssetPath")
        if isinstance(asset_path, Mapping):
            for key in ("PackageName", "AssetName"):
                package = _package_path(asset_path.get(key))
                if package:
                    result.append(package)
                    break
        for key, child in value.items():
            if key != "AssetPath" and isinstance(child, (list, Mapping)):
                result.extend(_soft_packages(child))
    return list(dict.fromkeys(result))


def _import_package(asset: Mapping[str, Any], index: Any) -> str | None:
    imports = asset.get("imports")
    if not isinstance(imports, list) or not isinstance(index, int) or index >= 0:
        return None
    seen: set[int] = set()
    current = index
    while current < 0 and current not in seen:
        seen.add(current)
        position = -current - 1
        if position >= len(imports) or not isinstance(imports[position], Mapping):
            return None
        item = imports[position]
        package = _package_path(item.get("objectName"))
        if package:
            return package
        outer = item.get("outerIndex")
        if not isinstance(outer, int):
            return None
        current = outer
    return None


def _reference_packages(prop: Mapping[str, Any] | None, asset: Mapping[str, Any]) -> list[str]:
    if prop is None:
        return []
    result = _soft_packages(prop.get("Value"))
    imported = _import_package(asset, prop.get("Value"))
    if imported:
        result.append(imported)
    return list(dict.fromkeys(result))


def _text(prop: Mapping[str, Any] | None) -> str | None:
    if prop is None:
        return None
    for key in ("CultureInvariantString", "SourceValue"):
        value = prop.get(key)
        if isinstance(value, str):
            return value
    value = prop.get("Value")
    return value if isinstance(value, str) and prop.get("HistoryType") != "Base" else None


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


def _gameplay_tags(value: Any) -> list[str]:
    tags: list[str] = []
    if isinstance(value, list):
        for child in value:
            tags.extend(_gameplay_tags(child))
    elif isinstance(value, Mapping):
        type_name = str(value.get("$type", ""))
        raw = value.get("Value")
        if "GameplayTagContainerPropertyData" in type_name and isinstance(raw, list):
            tags.extend(item for item in raw if isinstance(item, str))
        elif value.get("Name") == "TagName" and isinstance(raw, str):
            tags.append(raw)
        else:
            for child in value.values():
                if isinstance(child, (list, Mapping)):
                    tags.extend(_gameplay_tags(child))
    return sorted(set(tags))


def _integer(prop: Mapping[str, Any] | None) -> int | None:
    value = (prop or {}).get("Value")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _boolean(prop: Mapping[str, Any] | None) -> bool | None:
    value = (prop or {}).get("Value")
    return value if isinstance(value, bool) else None


def _number(prop: Mapping[str, Any] | None) -> int | float | None:
    value = (prop or {}).get("Value")
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _blueprint_parent_package(asset: Mapping[str, Any]) -> str | None:
    exports = asset.get("exports")
    if not isinstance(exports, list):
        return None
    class_export = next(
        (
            item
            for item in exports
            if isinstance(item, Mapping)
            and not str(item.get("objectName", "")).startswith("Default__")
            and (
                str(item.get("objectName", "")).endswith("_C")
                or "ClassExport" in str(item.get("type", ""))
            )
        ),
        None,
    )
    return _import_package(asset, (class_export or {}).get("superIndex"))


def _import_object_path(asset: Mapping[str, Any], index: Any) -> str | None:
    """Return the fully-qualified identity of one serialized import."""

    imports = asset.get("imports")
    if not isinstance(imports, list) or not isinstance(index, int) or index >= 0:
        return None
    position = -index - 1
    if position >= len(imports) or not isinstance(imports[position], Mapping):
        return None
    item = imports[position]
    object_name = item.get("objectName")
    if not isinstance(object_name, str) or not object_name:
        return None
    if object_name.startswith(("/Game/", "/Script/")):
        return object_name

    seen: set[int] = set()
    current = item.get("outerIndex")
    while isinstance(current, int) and current < 0 and current not in seen:
        seen.add(current)
        outer_position = -current - 1
        if outer_position >= len(imports) or not isinstance(
            imports[outer_position], Mapping
        ):
            return None
        outer = imports[outer_position]
        outer_name = outer.get("objectName")
        if isinstance(outer_name, str) and outer_name.startswith(("/Game/", "/Script/")):
            return f"{outer_name}.{object_name}"
        current = outer.get("outerIndex")
    return None


def _blueprint_super_object_path(asset: Mapping[str, Any]) -> str | None:
    exports = asset.get("exports")
    if not isinstance(exports, list):
        return None
    class_export = next(
        (
            item
            for item in exports
            if isinstance(item, Mapping)
            and not str(item.get("objectName", "")).startswith("Default__")
            and (
                str(item.get("objectName", "")).endswith("_C")
                or "ClassExport" in str(item.get("type", ""))
            )
        ),
        None,
    )
    return _import_object_path(asset, (class_export or {}).get("superIndex"))


def _store_categories(store_asset: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    export = _default_export(store_asset)
    if export is None:
        raise CollectionFormatError("canonical store asset had no default export")
    fields = _property_map(export.get("data"))
    categories = fields.get("Categories")
    if categories is None:
        raise CollectionFormatError("canonical store asset had no Categories property")
    values = _properties(categories.get("Value"))
    if not values:
        raise CollectionFormatError("canonical store asset had no category entries")
    return values


def _product_reference(
    product_fields: Mapping[str, Mapping[str, Any]],
    asset: Mapping[str, Any],
) -> tuple[str | None, str | None, str | None]:
    raw_type = _enum(product_fields.get("ProductType"))
    product_type = _enum_tail(raw_type)
    preferred = {
        "Gun": ("GunUnlockClass",),
        "Droppable": ("ItemClass",),
        "Character": ("CharacterUnlockClass",),
        "RewardPack": ("RewardPackClass",),
    }.get(product_type, ())
    fallback = ("ItemClass", "GunUnlockClass", "RewardPackClass", "CharacterUnlockClass")
    for name in (*preferred, *(name for name in fallback if name not in preferred)):
        packages = _reference_packages(product_fields.get(name), asset)
        if packages:
            return packages[0], name, raw_type
    return None, None, raw_type


def collection_product_package_paths(
    store_asset: Mapping[str, Any],
    *,
    category_kinds: Mapping[str, str] = PLANNER_CATEGORY_KINDS,
) -> tuple[str, ...]:
    """Return first-hop product packages needed by the planner categories."""

    packages: set[str] = set()
    for category in _store_categories(store_asset):
        fields = _property_map(category.get("Value"))
        key = (fields.get("Category") or {}).get("Value")
        if not isinstance(key, str) or key not in category_kinds:
            continue
        for entry in _properties((fields.get("SoldItems") or {}).get("Value")):
            entry_fields = _property_map(entry.get("Value"))
            product_fields = _property_map((entry_fields.get("Product") or {}).get("Value"))
            package, _, _ = _product_reference(product_fields, store_asset)
            if package:
                packages.add(package)
    return tuple(sorted(packages))


def _reward_table_dependencies(asset: Mapping[str, Any]) -> list[str]:
    export = _default_export(asset)
    if export is None:
        return []
    fields = _property_map(export.get("data"))
    reward_table = fields.get("RewardTable")
    if reward_table is None:
        return []
    table_fields = _property_map(reward_table.get("Value"))
    if "Rewards" not in table_fields:
        # AugmentPackDef stores a soft class reference to its table.
        return _reference_packages(reward_table, asset)

    # Reward-table definitions embed rows.  Only the field selected by the
    # RewardType discriminant is meaningful; other fields contain native
    # defaults and must not be traversed.
    result: list[str] = []
    for entry in _properties((table_fields.get("Rewards") or {}).get("Value")):
        entry_fields = _property_map(entry.get("Value"))
        reward_fields = _property_map((entry_fields.get("Reward") or {}).get("Value"))
        reward_type = _enum_tail(_enum(entry_fields.get("RewardType")))
        if reward_type == "Droppable":
            result.extend(_reference_packages(reward_fields.get("Droppable"), asset))
        elif reward_type == "Gun":
            result.extend(_reference_packages(reward_fields.get("GunUnlock"), asset))
        elif reward_type == "Character":
            result.extend(_reference_packages(reward_fields.get("CharacterUnlock"), asset))
        elif reward_type == "RewardTable":
            result.extend(_reference_packages(entry_fields.get("RewardTable"), asset))
    return list(dict.fromkeys(result))


def collection_wrapper_dependency_paths(
    wrapper_assets: Iterable[Mapping[str, Any]],
) -> tuple[str, ...]:
    """Return selected RewardTable dependencies from already-read wrappers."""

    return tuple(
        sorted(
            {
                package
                for asset in wrapper_assets
                for package in _reward_table_dependencies(asset)
            }
        )
    )


@dataclass(frozen=True)
class _ProgressionRoot:
    category: str
    category_index: int
    package_path: str | None
    reason: str | None
    root_index: int
    source_property: str
    unlock_description: str | None


def _progression_roots(
    settings_asset: Mapping[str, Any],
) -> tuple[int, tuple[_ProgressionRoot, ...]]:
    export = _default_export(settings_asset)
    if export is None:
        raise CollectionFormatError("progression settings asset had no default export")
    fields = _property_map(export.get("data"))
    unlock_map = fields.get("UnlockRewardTablesMap")
    if unlock_map is None:
        raise CollectionFormatError(
            "progression settings asset had no UnlockRewardTablesMap property"
        )
    raw_categories = unlock_map.get("Value")
    if not isinstance(raw_categories, list) or not raw_categories:
        raise CollectionFormatError("progression UnlockRewardTablesMap was empty or malformed")

    roots: list[_ProgressionRoot] = []
    for category_index, pair in enumerate(raw_categories):
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or not all(isinstance(item, Mapping) for item in pair)
        ):
            raise CollectionFormatError(
                f"progression unlock category {category_index} was malformed"
            )
        key_property, value_property = pair
        category = key_property.get("Value")
        if not isinstance(category, str) or not category:
            raise CollectionFormatError(
                f"progression unlock category {category_index} had no key"
            )
        category_fields = _property_map(value_property.get("Value"))
        reward_tables = category_fields.get("RewardTables")
        raw_tables = (reward_tables or {}).get("Value")
        if not isinstance(raw_tables, list):
            raise CollectionFormatError(
                f"progression unlock category {category} had no RewardTables array"
            )
        unlock_description = _text(category_fields.get("UnlockDescription"))
        for root_index, reference in enumerate(raw_tables):
            source_property = (
                f"UnlockRewardTablesMap[{category_index}]."
                f"RewardTables[{root_index}]"
            )
            if not isinstance(reference, Mapping):
                roots.append(
                    _ProgressionRoot(
                        category=category,
                        category_index=category_index,
                        package_path=None,
                        reason="root-reward-table-reference-malformed",
                        root_index=root_index,
                        source_property=source_property,
                        unlock_description=unlock_description,
                    )
                )
                continue
            packages = _reference_packages(reference, settings_asset)
            reason = None
            if not packages:
                reason = "root-reward-table-had-no-game-package"
            elif len(packages) != 1:
                reason = "root-reward-table-reference-ambiguous"
            roots.append(
                _ProgressionRoot(
                    category=category,
                    category_index=category_index,
                    package_path=packages[0] if len(packages) == 1 else None,
                    reason=reason,
                    root_index=root_index,
                    source_property=source_property,
                    unlock_description=unlock_description,
                )
            )
    return len(raw_categories), tuple(roots)


def progression_reward_table_package_paths(
    settings_asset: Mapping[str, Any],
) -> tuple[str, ...]:
    """Return authored reward-table roots from ``UnlockRewardTablesMap``."""

    _, roots = _progression_roots(settings_asset)
    return tuple(
        sorted(
            {
                root.package_path
                for root in roots
                if isinstance(root.package_path, str)
            }
        )
    )


def _progression_objectives(settings_asset: Mapping[str, Any]) -> dict[str, str | None]:
    export = _default_export(settings_asset)
    fields = _property_map((export or {}).get("data"))
    objective_map = fields.get("RewardTableObjectivesMap")
    if objective_map is None:
        return {}
    raw_entries = objective_map.get("Value")
    if not isinstance(raw_entries, list):
        raise CollectionFormatError("progression RewardTableObjectivesMap was malformed")
    result: dict[str, str | None] = {}
    for index, pair in enumerate(raw_entries):
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or not all(isinstance(item, Mapping) for item in pair)
        ):
            raise CollectionFormatError(
                f"progression reward-table objective {index} was malformed"
            )
        reference, objective = pair
        packages = _reference_packages(reference, settings_asset)
        if len(packages) != 1:
            raise CollectionFormatError(
                f"progression reward-table objective {index} had no unique table"
            )
        package = packages[0]
        text = _text(objective)
        if package in result and result[package] != text:
            raise CollectionFormatError(
                f"progression reward-table objective {package} was duplicated"
            )
        result[package] = text
    return result


@dataclass(frozen=True)
class _RewardTableRows:
    owner_asset: Mapping[str, Any] | None = None
    owner_package_path: str | None = None
    problem_package_path: str | None = None
    reason: str | None = None
    rows: tuple[Any, ...] = ()


def _materialized_reward_table_rows(
    package_path: str,
    assets: Mapping[str, Mapping[str, Any]],
    *,
    trail: tuple[str, ...] = (),
) -> _RewardTableRows:
    if package_path in trail:
        return _RewardTableRows(
            problem_package_path=package_path,
            reason="reward-table-parent-cycle",
        )
    asset = assets.get(package_path)
    if asset is None:
        return _RewardTableRows(
            problem_package_path=package_path,
            reason="reward-table-asset-unresolved",
        )
    export = _blueprint_default_export(asset)
    if export is None:
        return _RewardTableRows(
            problem_package_path=package_path,
            reason="reward-table-had-no-default-export",
        )
    fields = _property_map(export.get("data"))
    reward_table = fields.get("RewardTable")
    if reward_table is not None:
        table_fields = _property_map(reward_table.get("Value"))
        rewards = table_fields.get("Rewards")
        if rewards is None:
            rows: tuple[Any, ...] = ()
        elif isinstance(rewards.get("Value"), list):
            rows = tuple(rewards["Value"])
        else:
            return _RewardTableRows(
                problem_package_path=package_path,
                reason="reward-table-rewards-array-malformed",
            )
        return _RewardTableRows(
            owner_asset=asset,
            owner_package_path=package_path,
            rows=rows,
        )

    parent = _blueprint_parent_package(asset)
    if parent is not None:
        return _materialized_reward_table_rows(
            parent,
            assets,
            trail=(*trail, package_path),
        )

    # A direct subclass of the native RewardTable type can legitimately leave
    # the CDO empty, which means its native-default Rewards array is empty.
    return _RewardTableRows(
        owner_asset=asset,
        owner_package_path=package_path,
        rows=(),
    )


def progression_reward_table_dependency_paths(
    reward_table_assets: Iterable[Mapping[str, Any]],
) -> tuple[str, ...]:
    """Return Blueprint parents and discriminant-selected nested tables."""

    assets = {
        item["packagePath"]: item
        for item in reward_table_assets
        if isinstance(item.get("packagePath"), str)
    }
    dependencies: set[str] = set()
    for package_path, asset in assets.items():
        export = _default_export(asset)
        fields = _property_map((export or {}).get("data"))
        if export is not None and "RewardTable" not in fields:
            parent = _blueprint_parent_package(asset)
            if parent is not None:
                dependencies.add(parent)
        view = _materialized_reward_table_rows(package_path, assets)
        if view.owner_asset is None:
            continue
        for raw_row in view.rows:
            if not isinstance(raw_row, Mapping):
                continue
            fields = _property_map(raw_row.get("Value"))
            if _enum_tail(_enum(fields.get("RewardType"))) != "RewardTable":
                continue
            dependencies.update(
                _reference_packages(fields.get("RewardTable"), view.owner_asset)
            )
    return tuple(sorted(dependencies))


def _raw_object_paths(value: Any) -> list[str]:
    result: list[str] = []
    if isinstance(value, list):
        for child in value:
            result.extend(_raw_object_paths(child))
    elif isinstance(value, Mapping):
        asset_path = value.get("AssetPath")
        if isinstance(asset_path, Mapping):
            for key in ("PackageName", "AssetName"):
                raw = asset_path.get(key)
                if isinstance(raw, str) and raw not in {"", "None"}:
                    result.append(raw)
                    break
        for key, child in value.items():
            if key != "AssetPath" and isinstance(child, (list, Mapping)):
                result.extend(_raw_object_paths(child))
    return list(dict.fromkeys(result))


def _progression_step(
    *,
    fields: Mapping[str, Mapping[str, Any]],
    owner_package_path: str,
    reward_index: int,
    reward_type: str,
    table_package_path: str,
) -> dict[str, Any]:
    reward_fields = _property_map((fields.get("Reward") or {}).get("Value"))
    return {
        "chance": _number(fields.get("Chance")),
        "maxLevel": _integer(fields.get("MaxLevel")),
        "minLevel": _integer(fields.get("MinLevel")),
        "requiredFeatureUnlockRaw": _enum(fields.get("RequiredFeatureUnlock")),
        "reward": {
            "alternativeCashRewardCount": _integer(
                reward_fields.get("AlternativeCashRewardCount")
            ),
            "count": _integer(reward_fields.get("Count")),
            "level": _integer(reward_fields.get("Level")),
            "maxCount": _integer(reward_fields.get("MaxCount")),
            "minCount": _integer(reward_fields.get("MinCount")),
            "showAsPostGameReward": _boolean(
                reward_fields.get("bShowAsPostGameReward")
            ),
        },
        "rewardIndex": reward_index,
        "rewardType": reward_type,
        "serializedByPackagePath": owner_package_path,
        "showAsPostGameReward": _boolean(fields.get("bShowAsPostGameReward")),
        "tablePackagePath": table_package_path,
    }


def build_progression_perk_index(
    *,
    settings_asset: Mapping[str, Any],
    reward_table_assets: Sequence[Mapping[str, Any]],
    candidate_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build the canonical perk membership proven by authored unlock tables."""

    source_package = settings_asset.get("packagePath")
    if not isinstance(source_package, str):
        raise CollectionFormatError("progression settings asset had no packagePath")
    category_count, roots = _progression_roots(settings_asset)
    objectives = _progression_objectives(settings_asset)
    assets = {
        item["packagePath"]: item
        for item in reward_table_assets
        if isinstance(item.get("packagePath"), str)
    }
    candidates = {
        item["packagePath"]: item
        for item in candidate_records
        if isinstance(item.get("packagePath"), str)
    }

    sources_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    record_by_id: dict[str, dict[str, str]] = {}
    unresolved: list[dict[str, Any]] = []
    tables_traversed: set[str] = set()
    row_keys: set[tuple[str, int]] = set()
    nested_edges: set[tuple[str, int, str]] = set()
    droppable_rows: set[tuple[str, int]] = set()
    droppable_references: set[tuple[str, int, str]] = set()
    non_game_droppables: set[tuple[str, int, str]] = set()
    non_perk_droppables: set[tuple[str, int, str]] = set()
    parent_tables_used: set[str] = set()
    root_tables_resolved = 0

    def source_for(
        root: _ProgressionRoot,
        steps: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        source: dict[str, Any] = {
            "rootRewardTableIndex": root.root_index,
            "rootRewardTablePackagePath": root.package_path,
            "sourceProperty": root.source_property,
            "steps": [dict(step) for step in steps],
            "unlockCategory": root.category,
            "unlockCategoryIndex": root.category_index,
            "unlockDescription": root.unlock_description,
        }
        objective = objectives.get(root.package_path or "")
        if objective is not None:
            source["objective"] = objective
        return source

    def add_problem(
        root: _ProgressionRoot,
        *,
        package_path: str | None,
        reason: str,
        steps: Sequence[Mapping[str, Any]] = (),
    ) -> None:
        unresolved.append(
            {
                "packagePath": package_path,
                "reason": reason,
                **source_for(root, steps),
            }
        )

    def walk(
        root: _ProgressionRoot,
        table_package_path: str,
        *,
        steps: tuple[Mapping[str, Any], ...] = (),
        trail: tuple[str, ...] = (),
    ) -> bool:
        if table_package_path in trail:
            add_problem(
                root,
                package_path=table_package_path,
                reason="nested-reward-table-cycle",
                steps=steps,
            )
            return False
        view = _materialized_reward_table_rows(table_package_path, assets)
        if view.owner_asset is None or view.owner_package_path is None:
            add_problem(
                root,
                package_path=view.problem_package_path or table_package_path,
                reason=view.reason or "reward-table-unresolved",
                steps=steps,
            )
            return False
        tables_traversed.add(table_package_path)
        if view.owner_package_path != table_package_path:
            parent_tables_used.add(view.owner_package_path)

        for reward_index, raw_row in enumerate(view.rows):
            row_keys.add((table_package_path, reward_index))
            if not isinstance(raw_row, Mapping):
                add_problem(
                    root,
                    package_path=table_package_path,
                    reason="reward-table-row-malformed",
                    steps=steps,
                )
                continue
            fields = _property_map(raw_row.get("Value"))
            reward_type = _enum_tail(_enum(fields.get("RewardType")))
            if not reward_type:
                add_problem(
                    root,
                    package_path=table_package_path,
                    reason="reward-table-row-had-no-discriminant",
                    steps=steps,
                )
                continue
            step = _progression_step(
                fields=fields,
                owner_package_path=view.owner_package_path,
                reward_index=reward_index,
                reward_type=reward_type,
                table_package_path=table_package_path,
            )
            next_steps = (*steps, step)
            if reward_type == "RewardTable":
                packages = _reference_packages(
                    fields.get("RewardTable"),
                    view.owner_asset,
                )
                if len(packages) != 1:
                    add_problem(
                        root,
                        package_path=table_package_path,
                        reason="selected-nested-reward-table-had-no-unique-target",
                        steps=next_steps,
                    )
                    continue
                target = packages[0]
                step["targetPackagePath"] = target
                nested_edges.add((table_package_path, reward_index, target))
                walk(
                    root,
                    target,
                    steps=next_steps,
                    trail=(*trail, table_package_path),
                )
                continue
            if reward_type != "Droppable":
                continue

            droppable_rows.add((table_package_path, reward_index))
            reward_fields = _property_map((fields.get("Reward") or {}).get("Value"))
            selected = reward_fields.get("Droppable")
            packages = _reference_packages(selected, view.owner_asset)
            raw_paths = _raw_object_paths((selected or {}).get("Value"))
            if not packages:
                if raw_paths:
                    for raw_path in raw_paths:
                        non_game_droppables.add(
                            (table_package_path, reward_index, raw_path)
                        )
                else:
                    add_problem(
                        root,
                        package_path=table_package_path,
                        reason="selected-droppable-had-no-target",
                        steps=next_steps,
                    )
                continue
            if len(packages) != 1:
                add_problem(
                    root,
                    package_path=table_package_path,
                    reason="selected-droppable-had-ambiguous-target",
                    steps=next_steps,
                )
                continue
            target = packages[0]
            step["targetPackagePath"] = target
            droppable_references.add((table_package_path, reward_index, target))
            candidate = candidates.get(target)
            if candidate is None or candidate.get("kind") != "perk":
                non_perk_droppables.add((table_package_path, reward_index, target))
                continue
            record_id = candidate.get("id")
            if not isinstance(record_id, str):
                add_problem(
                    root,
                    package_path=target,
                    reason="progression-perk-candidate-had-no-id",
                    steps=next_steps,
                )
                continue
            record_by_id[record_id] = {
                "id": record_id,
                "kind": "perk",
                "packagePath": target,
            }
            sources_by_id[record_id].append(source_for(root, next_steps))
        return True

    for root in roots:
        if root.package_path is None:
            add_problem(
                root,
                package_path=source_package,
                reason=root.reason or "root-reward-table-unresolved",
            )
            continue
        if walk(root, root.package_path):
            root_tables_resolved += 1

    entries: list[dict[str, Any]] = []
    perk_occurrences = 0
    for record_id in sorted(record_by_id):
        unique_sources: dict[tuple[Any, ...], dict[str, Any]] = {}
        for source in sources_by_id[record_id]:
            step_identity = tuple(
                (
                    step.get("tablePackagePath"),
                    step.get("rewardIndex"),
                    step.get("targetPackagePath"),
                )
                for step in source["steps"]
            )
            identity = (
                source["unlockCategoryIndex"],
                source["rootRewardTableIndex"],
                step_identity,
            )
            unique_sources[identity] = source
        sources = [unique_sources[key] for key in sorted(unique_sources)]
        perk_occurrences += len(sources)
        entries.append({**record_by_id[record_id], "sources": sources})

    unresolved.sort(
        key=lambda value: (
            value.get("unlockCategoryIndex", -1),
            value.get("rootRewardTableIndex", -1),
            str(value.get("packagePath")),
            value.get("reason", ""),
        )
    )
    return {
        "coverage": {
            "blueprintParentTablesUsed": len(parent_tables_used),
            "droppableRewardReferences": len(droppable_references),
            "droppableRewardRows": len(droppable_rows),
            "nestedRewardTableEdges": len(nested_edges),
            "nonGameDroppableRewards": len(non_game_droppables),
            "nonPerkDroppableReferences": len(non_perk_droppables),
            "perkRewardOccurrences": perk_occurrences,
            "rewardRowsVisited": len(row_keys),
            "rewardTablesTraversed": len(tables_traversed),
            "rootTableReferences": len(roots),
            "rootTablesResolved": root_tables_resolved,
            "uniquePerks": len(entries),
            "unlockCategories": category_count,
            "unresolvedReferences": len(unresolved),
        },
        "entries": entries,
        "memberIds": sorted(record_by_id),
        "source": {
            "packagePath": source_package,
            "property": "UnlockRewardTablesMap",
        },
        "status": "complete" if not unresolved else "incomplete",
        "unresolved": unresolved,
    }


@dataclass(frozen=True)
class _RegistryClassReference:
    default_object_name: str
    import_index: int
    package_path: str
    registry_package_path: str


def _registry_class_references(
    registry_assets: Iterable[Mapping[str, Any]],
) -> tuple[_RegistryClassReference, ...]:
    """Return external Blueprint classes referenced by canonical registries.

    A DataTable's row bytes are not materialized by the trimmed reader, but its
    serialized import table retains the exact generated class/default-object
    dependencies selected by those rows.  Restricting this to imported default
    objects avoids treating every package import as a possible reward source.
    """

    references: dict[tuple[str, str, int], _RegistryClassReference] = {}
    for asset in registry_assets:
        registry_package = asset.get("packagePath")
        imports = asset.get("imports")
        if not isinstance(registry_package, str) or not isinstance(imports, list):
            continue
        for import_index, item in enumerate(imports):
            if not isinstance(item, Mapping):
                continue
            object_name = item.get("objectName")
            class_package = _package_path(item.get("classPackage"))
            if (
                not isinstance(object_name, str)
                or not object_name.startswith("Default__")
                or class_package is None
            ):
                continue
            reference = _RegistryClassReference(
                default_object_name=object_name,
                import_index=import_index,
                package_path=class_package,
                registry_package_path=registry_package,
            )
            references[(registry_package, class_package, import_index)] = reference
    return tuple(references[key] for key in sorted(references))


def _registry_import_problems(
    registry_assets: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Diagnose structurally incomplete registry import evidence.

    An empty import array is valid. A missing/malformed array, malformed entry,
    or external default object without a usable class package is not: silently
    treating those cases as an empty registry could hide a newly added kit.
    """

    problems: list[dict[str, Any]] = []
    for asset in registry_assets:
        registry_package = asset.get("packagePath")
        if not isinstance(registry_package, str):
            problems.append(
                {
                    "packagePath": None,
                    "reason": "metamission-registry-had-no-package-path",
                    "sourceKind": "metamission-registry",
                }
            )
            continue
        imports = asset.get("imports")
        if not isinstance(imports, list):
            problems.append(
                {
                    "packagePath": registry_package,
                    "reason": "metamission-registry-imports-malformed",
                    "registryPackagePath": registry_package,
                    "sourceKind": "metamission-registry",
                }
            )
            continue
        for import_index, item in enumerate(imports):
            if not isinstance(item, Mapping):
                problems.append(
                    {
                        "packagePath": registry_package,
                        "reason": "metamission-registry-import-entry-malformed",
                        "registryImportIndex": import_index,
                        "registryPackagePath": registry_package,
                        "sourceKind": "metamission-registry",
                    }
                )
                continue
            object_name = item.get("objectName")
            if not isinstance(object_name, str) or not object_name.startswith(
                "Default__"
            ):
                continue
            class_package = item.get("classPackage")
            if isinstance(class_package, str) and (
                _package_path(class_package) is not None
                or class_package.startswith(("/Script/", "/Engine/"))
            ):
                continue
            problems.append(
                {
                    "defaultObjectName": object_name,
                    "packagePath": registry_package,
                    "reason": "metamission-registry-default-import-had-no-class-package",
                    "registryImportIndex": import_index,
                    "registryPackagePath": registry_package,
                    "sourceKind": "metamission-registry",
                }
            )
    return tuple(problems)


def kit_reward_registry_dependency_paths(
    registry_assets: Iterable[Mapping[str, Any]],
) -> tuple[str, ...]:
    """Return source-derived Blueprint dependencies of metagame registries."""

    return tuple(
        sorted(
            {
                reference.package_path
                for reference in _registry_class_references(registry_assets)
            }
        )
    )


def _reward_table_blueprint_state(
    package_path: str,
    assets: Mapping[str, Mapping[str, Any]],
    *,
    trail: tuple[str, ...] = (),
) -> tuple[bool | None, str | None]:
    """Classify a Blueprint by its authored RewardTableDef/inheritance chain."""

    if package_path in trail:
        return None, "reward-table-parent-cycle"
    asset = assets.get(package_path)
    if asset is None:
        return None, "registry-imported-class-asset-unresolved"
    export = _blueprint_default_export(asset)
    if export is None:
        return None, "registry-imported-class-had-no-default-export"
    fields = _property_map(export.get("data"))
    reward_table = fields.get("RewardTable")
    if _is_reward_table_definition_property(reward_table):
        return True, None

    parent = _blueprint_parent_package(asset)
    if parent is not None:
        if parent not in assets:
            return None, "reward-table-parent-asset-unresolved"
        return _reward_table_blueprint_state(
            parent,
            assets,
            trail=(*trail, package_path),
        )
    if _blueprint_super_object_path(asset) == _NATIVE_REWARD_TABLE:
        return True, None
    return False, None


def _is_reward_table_definition_property(
    prop: Mapping[str, Any] | None,
) -> bool:
    if prop is None or "StructPropertyData" not in str(prop.get("$type", "")):
        return False
    return prop.get("StructType") == "RewardTableDef" or "Rewards" in _property_map(
        prop.get("Value")
    )


def kit_reward_table_package_paths(
    *,
    registry_assets: Iterable[Mapping[str, Any]],
    referenced_assets: Iterable[Mapping[str, Any]],
) -> tuple[str, ...]:
    """Return registry-imported classes proven to be reward tables."""

    assets = {
        item["packagePath"]: item
        for item in referenced_assets
        if isinstance(item.get("packagePath"), str)
    }
    return tuple(
        sorted(
            {
                reference.package_path
                for reference in _registry_class_references(registry_assets)
                if _reward_table_blueprint_state(
                    reference.package_path,
                    assets,
                )[0]
                is True
            }
        )
    )


def kit_reward_table_dependency_paths(
    *,
    reward_table_assets: Iterable[Mapping[str, Any]],
    root_package_paths: Iterable[str],
) -> tuple[str, ...]:
    """Return parent and selected nested-table dependencies of kit roots."""

    assets = {
        item["packagePath"]: item
        for item in reward_table_assets
        if isinstance(item.get("packagePath"), str)
    }
    dependencies: set[str] = set()
    pending = list(sorted(set(root_package_paths), reverse=True))
    visited: set[str] = set()
    while pending:
        package_path = pending.pop()
        if package_path in visited:
            continue
        visited.add(package_path)
        asset = assets.get(package_path)
        if asset is None:
            continue
        export = _default_export(asset)
        fields = _property_map((export or {}).get("data"))
        if export is not None and not _is_reward_table_definition_property(
            fields.get("RewardTable")
        ):
            parent = _blueprint_parent_package(asset)
            if parent is not None and parent not in assets:
                dependencies.add(parent)
        view = _materialized_reward_table_rows(package_path, assets)
        if view.owner_asset is None:
            continue
        for raw_row in view.rows:
            if not isinstance(raw_row, Mapping):
                continue
            row_fields = _property_map(raw_row.get("Value"))
            if _enum_tail(_enum(row_fields.get("RewardType"))) != "RewardTable":
                continue
            for target in _reference_packages(
                row_fields.get("RewardTable"), view.owner_asset
            ):
                dependencies.add(target)
                if target in assets:
                    pending.append(target)
    return tuple(sorted(dependencies))


def _kit_reward_step(
    *,
    fields: Mapping[str, Mapping[str, Any]],
    owner_package_path: str,
    reward_index: int,
    reward_type: str,
    table_package_path: str,
) -> dict[str, Any]:
    return {
        "chance": _number(fields.get("Chance")),
        "maxLevel": _integer(fields.get("MaxLevel")),
        "minLevel": _integer(fields.get("MinLevel")),
        "requiredFeatureUnlockRaw": _enum(fields.get("RequiredFeatureUnlock")),
        "rewardIndex": reward_index,
        "rewardType": reward_type,
        "serializedByPackagePath": owner_package_path,
        "showAsPostGameReward": _boolean(fields.get("bShowAsPostGameReward")),
        "tablePackagePath": table_package_path,
    }


def build_kit_membership_index(
    *,
    starting_asset: Mapping[str, Any],
    registry_assets: Sequence[Mapping[str, Any]],
    reward_table_assets: Sequence[Mapping[str, Any]],
    kit_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build canonical selectable-kit membership from authored unlock rewards."""

    starting_package = starting_asset.get("packagePath")
    if not isinstance(starting_package, str):
        raise CollectionFormatError("default starting rewards had no packagePath")
    registry_packages = sorted(
        {
            value
            for asset in registry_assets
            if isinstance((value := asset.get("packagePath")), str)
        }
    )
    assets = {
        item["packagePath"]: item
        for item in [starting_asset, *reward_table_assets]
        if isinstance(item.get("packagePath"), str)
    }
    references = _registry_class_references(registry_assets)
    roots: list[dict[str, Any]] = [
        {
            "rootRewardTablePackagePath": starting_package,
            "sourceKind": "default-starting-rewards",
            "sourcePackagePath": starting_package,
        }
    ]
    registry_import_problems = _registry_import_problems(registry_assets)
    unresolved: list[dict[str, Any]] = list(registry_import_problems)
    ignored_registry_imports = 0
    registry_reward_packages: set[str] = set()
    for reference in references:
        state, reason = _reward_table_blueprint_state(reference.package_path, assets)
        if state is False:
            ignored_registry_imports += 1
            continue
        source = {
            "defaultObjectName": reference.default_object_name,
            "registryImportIndex": reference.import_index,
            "registryPackagePath": reference.registry_package_path,
            "rootRewardTablePackagePath": reference.package_path,
            "sourceKind": "metamission-registry",
        }
        if state is None:
            unresolved.append(
                {
                    **source,
                    "packagePath": reference.package_path,
                    "reason": reason or "registry-reward-table-unresolved",
                }
            )
            continue
        registry_reward_packages.add(reference.package_path)
        roots.append(source)

    sources_by_class: dict[str, list[dict[str, Any]]] = defaultdict(list)
    tables_traversed: set[str] = set()
    rows_visited: set[tuple[str, int]] = set()
    nested_edges: set[tuple[str, int, str]] = set()
    character_rows: set[tuple[str, int, str]] = set()
    starting_character_rows: set[tuple[str, int, str]] = set()
    root_tables_resolved = 0
    parent_tables_used: set[str] = set()

    def add_problem(
        source: Mapping[str, Any],
        *,
        package_path: str | None,
        reason: str,
        steps: Sequence[Mapping[str, Any]] = (),
    ) -> None:
        unresolved.append(
            {
                **dict(source),
                "packagePath": package_path,
                "reason": reason,
                "steps": [dict(step) for step in steps],
            }
        )

    def walk(
        source: Mapping[str, Any],
        table_package_path: str,
        *,
        steps: tuple[Mapping[str, Any], ...] = (),
        trail: tuple[str, ...] = (),
    ) -> bool:
        if table_package_path in trail:
            add_problem(
                source,
                package_path=table_package_path,
                reason="nested-reward-table-cycle",
                steps=steps,
            )
            return False
        state, reason = _reward_table_blueprint_state(table_package_path, assets)
        if state is not True:
            add_problem(
                source,
                package_path=table_package_path,
                reason=reason or "selected-package-was-not-reward-table",
                steps=steps,
            )
            return False
        view = _materialized_reward_table_rows(table_package_path, assets)
        if view.owner_asset is None or view.owner_package_path is None:
            add_problem(
                source,
                package_path=view.problem_package_path or table_package_path,
                reason=view.reason or "reward-table-unresolved",
                steps=steps,
            )
            return False
        tables_traversed.add(table_package_path)
        if view.owner_package_path != table_package_path:
            parent_tables_used.add(view.owner_package_path)

        for reward_index, raw_row in enumerate(view.rows):
            rows_visited.add((table_package_path, reward_index))
            if not isinstance(raw_row, Mapping):
                add_problem(
                    source,
                    package_path=table_package_path,
                    reason="reward-table-row-malformed",
                    steps=steps,
                )
                continue
            fields = _property_map(raw_row.get("Value"))
            reward_type = _enum_tail(_enum(fields.get("RewardType")))
            if not reward_type:
                add_problem(
                    source,
                    package_path=table_package_path,
                    reason="reward-table-row-had-no-discriminant",
                    steps=steps,
                )
                continue
            step = _kit_reward_step(
                fields=fields,
                owner_package_path=view.owner_package_path,
                reward_index=reward_index,
                reward_type=reward_type,
                table_package_path=table_package_path,
            )
            next_steps = (*steps, step)
            if reward_type == "RewardTable":
                targets = _reference_packages(
                    fields.get("RewardTable"), view.owner_asset
                )
                if len(targets) != 1:
                    add_problem(
                        source,
                        package_path=table_package_path,
                        reason="selected-nested-reward-table-had-no-unique-target",
                        steps=next_steps,
                    )
                    continue
                target = targets[0]
                step["targetPackagePath"] = target
                nested_edges.add((table_package_path, reward_index, target))
                walk(
                    source,
                    target,
                    steps=next_steps,
                    trail=(*trail, table_package_path),
                )
                continue

            reward_fields = _property_map((fields.get("Reward") or {}).get("Value"))
            if reward_type == "Droppable":
                selected_paths = _raw_object_paths(
                    (reward_fields.get("Droppable") or {}).get("Value")
                )
                if _CHARACTER_UNLOCK_TOKEN not in selected_paths:
                    continue
                step["selectedToken"] = _CHARACTER_UNLOCK_TOKEN
            elif reward_type != "Character":
                continue

            targets = _reference_packages(
                reward_fields.get("CharacterUnlock"), view.owner_asset
            )
            if len(targets) != 1:
                add_problem(
                    source,
                    package_path=table_package_path,
                    reason="selected-character-unlock-had-no-unique-target",
                    steps=next_steps,
                )
                continue
            target = targets[0]
            step["targetCharacterClassPackagePath"] = target
            character_rows.add((table_package_path, reward_index, target))
            if source.get("sourceKind") == "default-starting-rewards":
                starting_character_rows.add((table_package_path, reward_index, target))
            sources_by_class[target].append(
                {**dict(source), "steps": [dict(value) for value in next_steps]}
            )
        return True

    starting_state, starting_reason = _reward_table_blueprint_state(
        starting_package, assets
    )
    if starting_state is not True:
        source = roots[0]
        add_problem(
            source,
            package_path=starting_package,
            reason=starting_reason or "default-starting-source-was-not-reward-table",
        )

    starting_root_traversed = False
    for root in roots:
        if (
            root.get("sourceKind") == "default-starting-rewards"
            and starting_state is not True
        ):
            continue
        traversed = walk(root, root["rootRewardTablePackagePath"])
        if root.get("sourceKind") == "default-starting-rewards":
            starting_root_traversed = traversed
        if traversed:
            root_tables_resolved += 1

    if starting_root_traversed and not starting_character_rows:
        unresolved.append(
            {
                "packagePath": starting_package,
                "reason": "default-starting-rewards-had-no-character-unlocks",
                "rootRewardTablePackagePath": starting_package,
                "sourceKind": "default-starting-rewards",
                "sourcePackagePath": starting_package,
            }
        )

    kits_by_class: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    candidate_kit_ids: set[str] = set()
    for record in kit_records:
        if record.get("kind") != "kit" or not isinstance(record.get("id"), str):
            continue
        candidate_kit_ids.add(record["id"])
        class_package = record.get("characterClassPackagePath")
        if isinstance(class_package, str):
            kits_by_class[class_package].append(record)

    entries: list[dict[str, Any]] = []
    for class_package in sorted(sources_by_class):
        matches = kits_by_class.get(class_package, [])
        if len(matches) != 1:
            unresolved.append(
                {
                    "characterClassPackagePath": class_package,
                    "matchingKitIds": sorted(
                        {
                            value["id"]
                            for value in matches
                            if isinstance(value.get("id"), str)
                        }
                    ),
                    "packagePath": class_package,
                    "reason": (
                        "authorized-character-class-had-no-kit"
                        if not matches
                        else "authorized-character-class-mapped-to-multiple-kits"
                    ),
                }
            )
            continue
        kit = matches[0]
        unique_sources: dict[tuple[Any, ...], dict[str, Any]] = {}
        for source in sources_by_class[class_package]:
            identity = (
                str(source.get("sourceKind", "")),
                str(source.get("registryPackagePath", "")),
                int(source.get("registryImportIndex", -1)),
                str(source.get("rootRewardTablePackagePath", "")),
                tuple(
                    (
                        step.get("tablePackagePath"),
                        step.get("rewardIndex"),
                        step.get("targetCharacterClassPackagePath"),
                    )
                    for step in source.get("steps", [])
                    if isinstance(step, Mapping)
                ),
            )
            unique_sources[identity] = source
        entries.append(
            {
                "characterClassPackagePath": class_package,
                "id": kit["id"],
                "kind": "kit",
                "packagePath": kit.get("packagePath"),
                "sources": [unique_sources[key] for key in sorted(unique_sources)],
            }
        )

    entries.sort(key=lambda value: value["id"])
    member_ids = [value["id"] for value in entries]
    unresolved.sort(
        key=lambda value: (
            str(value.get("registryPackagePath", "")),
            str(value.get("rootRewardTablePackagePath", "")),
            str(value.get("packagePath", "")),
            str(value.get("reason", "")),
        )
    )
    return {
        "coverage": {
            "authorizedCharacterClasses": len(sources_by_class),
            "blueprintParentTablesUsed": len(parent_tables_used),
            "candidateKitRecords": len(candidate_kit_ids),
            "characterUnlockOccurrences": len(character_rows),
            "excludedCandidateKits": len(candidate_kit_ids - set(member_ids)),
            "ignoredRegistryClassImports": ignored_registry_imports,
            "malformedRegistryImports": len(registry_import_problems),
            "mappedKits": len(entries),
            "nestedRewardTableEdges": len(nested_edges),
            "registryAssets": len(registry_packages),
            "registryImportedClasses": len(references),
            "registryRewardTableRoots": len(registry_reward_packages),
            "rewardRowsVisited": len(rows_visited),
            "rewardTablesTraversed": len(tables_traversed),
            "rootTableReferences": len(roots),
            "rootTablesResolved": root_tables_resolved,
            "unresolvedReferences": len(unresolved),
        },
        "entries": entries,
        "memberIds": member_ids,
        "source": {
            "basis": (
                "DefaultStarting_Rewards plus RewardTable Blueprint defaults "
                "imported by live metagame registries"
            ),
            "registryPackagePaths": registry_packages,
            "startingRewardTablePackagePath": starting_package,
        },
        "status": "complete" if not unresolved else "incomplete",
        "unresolved": unresolved,
    }


def _item_terminal(asset: Mapping[str, Any]) -> dict[str, Any] | None:
    package_path = asset.get("packagePath")
    export = _default_export(asset)
    if not isinstance(package_path, str) or export is None:
        return None
    fields = _property_map(export.get("data"))
    tags = _gameplay_tags(fields.get("Tags"))
    tiers = sorted({_ITEM_TIER_TAGS[tag] for tag in tags if tag in _ITEM_TIER_TAGS})
    if len(tiers) != 1:
        return None
    return {
        "id": package_path,
        "itemTier": tiers[0],
        "kind": "item",
        "packagePath": package_path,
    }


@dataclass(frozen=True)
class _Resolution:
    terminals: tuple[dict[str, Any], ...] = ()
    wrappers: tuple[str, ...] = ()
    problems: tuple[dict[str, str], ...] = ()


def _resolve_target(
    package_path: str,
    *,
    expected_kind: str,
    candidates: Mapping[str, Mapping[str, Any]],
    items: Mapping[str, Mapping[str, Any]],
    wrappers: Mapping[str, Mapping[str, Any]],
    trail: tuple[str, ...] = (),
) -> _Resolution:
    candidate = candidates.get(package_path)
    if candidate is not None:
        kind = candidate.get("kind")
        record_id = candidate.get("id")
        if kind != expected_kind or not isinstance(record_id, str):
            return _Resolution(
                problems=(
                    {
                        "packagePath": package_path,
                        "reason": "terminal-kind-mismatch",
                    },
                )
            )
        terminal = {"id": record_id, "kind": kind, "packagePath": package_path}
        item_tier = candidate.get("itemTier")
        if kind == "item" and item_tier not in {"major", "minor"}:
            item_tier = (items.get(package_path) or {}).get("itemTier")
        if kind == "item":
            if item_tier not in {"major", "minor"}:
                return _Resolution(
                    problems=(
                        {
                            "packagePath": package_path,
                            "reason": "item-tier-unresolved",
                        },
                    )
                )
            terminal["itemTier"] = item_tier
        return _Resolution(terminals=(terminal,))

    item = items.get(package_path)
    if item is not None:
        if expected_kind != "item":
            return _Resolution(
                problems=({"packagePath": package_path, "reason": "terminal-kind-mismatch"},)
            )
        return _Resolution(terminals=(dict(item),))

    wrapper = wrappers.get(package_path)
    if wrapper is None:
        return _Resolution(
            problems=({"packagePath": package_path, "reason": "unresolved-product-target"},)
        )
    if package_path in trail:
        return _Resolution(
            wrappers=(package_path,),
            problems=({"packagePath": package_path, "reason": "wrapper-cycle"},),
        )
    dependencies = _reward_table_dependencies(wrapper)
    if not dependencies:
        return _Resolution(
            wrappers=(package_path,),
            problems=({"packagePath": package_path, "reason": "wrapper-had-no-selected-rewards"},),
        )

    terminals: dict[tuple[str, str], dict[str, Any]] = {}
    wrapper_paths: set[str] = {package_path}
    problems: list[dict[str, str]] = []
    for dependency in dependencies:
        resolved = _resolve_target(
            dependency,
            expected_kind=expected_kind,
            candidates=candidates,
            items=items,
            wrappers=wrappers,
            trail=(*trail, package_path),
        )
        for terminal in resolved.terminals:
            terminals[(terminal["id"], terminal["packagePath"])] = terminal
        wrapper_paths.update(resolved.wrappers)
        problems.extend(resolved.problems)
    return _Resolution(
        terminals=tuple(terminals[key] for key in sorted(terminals)),
        wrappers=tuple(sorted(wrapper_paths)),
        problems=tuple(
            {"packagePath": package, "reason": reason}
            for package, reason in sorted(
                {(problem["packagePath"], problem["reason"]) for problem in problems}
            )
        ),
    )


def build_collection_document(
    *,
    store_asset: Mapping[str, Any],
    wrapper_assets: Sequence[Mapping[str, Any]],
    terminal_assets: Sequence[Mapping[str, Any]],
    candidate_records: Sequence[Mapping[str, Any]],
    source_fingerprint: str,
    category_kinds: Mapping[str, str] = PLANNER_CATEGORY_KINDS,
    ignored_category_keys: frozenset[str] = IGNORED_COLLECTION_CATEGORIES,
) -> dict[str, Any]:
    """Build a deterministic, fail-closed player-visible catalogue index."""

    if not isinstance(source_fingerprint, str) or not source_fingerprint:
        raise CollectionFormatError("collection source fingerprint was missing")
    source_package = store_asset.get("packagePath")
    if not isinstance(source_package, str):
        raise CollectionFormatError("canonical store asset had no packagePath")

    candidate_by_package = {
        record["packagePath"]: record
        for record in candidate_records
        if isinstance(record.get("packagePath"), str)
    }
    wrapper_by_package = {
        asset["packagePath"]: asset
        for asset in wrapper_assets
        if isinstance(asset.get("packagePath"), str)
    }
    item_by_package = {
        terminal["packagePath"]: terminal
        for asset in terminal_assets
        if (terminal := _item_terminal(asset)) is not None
    }

    raw_categories = _store_categories(store_asset)
    observed_category_keys = {
        key
        for raw_category in raw_categories
        for fields in (_property_map(raw_category.get("Value")),)
        for key in ((fields.get("Category") or {}).get("Value"),)
        if isinstance(key, str) and key
    }
    category_audit = {
        "ignoredKeys": sorted(observed_category_keys & set(ignored_category_keys)),
        "includedKeys": sorted(observed_category_keys & set(category_kinds)),
        "observedKeys": sorted(observed_category_keys),
        "unknownKeys": sorted(
            observed_category_keys
            - set(category_kinds)
            - set(ignored_category_keys)
        ),
    }

    categories: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    reverse: dict[str, list[dict[str, Any]]] = defaultdict(list)
    resolved_entries = 0
    product_rows = 0
    terminal_links = 0
    seen_wrappers: set[str] = set()

    for category_index, raw_category in enumerate(raw_categories):
        fields = _property_map(raw_category.get("Value"))
        key = (fields.get("Category") or {}).get("Value")
        if not isinstance(key, str) or key not in category_kinds:
            continue
        expected_kind = category_kinds[key]
        entries: list[dict[str, Any]] = []
        member_ids: set[str] = set()
        for entry_index, raw_entry in enumerate(
            _properties((fields.get("SoldItems") or {}).get("Value"))
        ):
            product_rows += 1
            entry_fields = _property_map(raw_entry.get("Value"))
            product_fields = _property_map((entry_fields.get("Product") or {}).get("Value"))
            package, reference_property, raw_product_type = _product_reference(
                product_fields,
                store_asset,
            )
            product: dict[str, Any] = {
                "count": _integer(product_fields.get("Count")),
                "packagePath": package,
                "productType": _enum_tail(raw_product_type),
                "productTypeRaw": raw_product_type,
                "referenceProperty": reference_property,
            }
            for source_name, output_name in (
                ("bPermaUnlock", "permanentUnlock"),
                ("bSkipAutoSlot", "skipAutoSlot"),
                ("bCanReceive", "canReceive"),
            ):
                product[output_name] = _boolean(product_fields.get(source_name))
            availability = {
                "cost": _integer(entry_fields.get("Cost")),
                "featureUnlockRequirementRaw": _enum(
                    entry_fields.get("FeatureUnlockRequirement")
                ),
                "purchasable": _boolean(entry_fields.get("Purchasable")),
            }

            if package is None:
                resolution = _Resolution(
                    problems=(
                        {
                            "packagePath": source_package,
                            "reason": "store-product-had-no-target",
                        },
                    )
                )
                entry_id = f"{source_package}#category-{category_index}-entry-{entry_index}"
            else:
                resolution = _resolve_target(
                    package,
                    expected_kind=expected_kind,
                    candidates=candidate_by_package,
                    items=item_by_package,
                    wrappers=wrapper_by_package,
                )
                entry_id = package

            seen_wrappers.update(resolution.wrappers)
            terminal_links += len(resolution.terminals)
            status = (
                "resolved" if resolution.terminals and not resolution.problems else "unresolved"
            )
            if status == "resolved":
                resolved_entries += 1
                member_ids.add(entry_id)
                for terminal in resolution.terminals:
                    reverse[terminal["id"]].append(
                        {
                            "categoryKey": key,
                            "entryId": entry_id,
                            "entryIndex": entry_index,
                        }
                    )
            for problem in resolution.problems:
                unresolved.append(
                    {
                        "categoryKey": key,
                        "entryIndex": entry_index,
                        **problem,
                    }
                )
            entries.append(
                {
                    "availability": availability,
                    "entryIndex": entry_index,
                    "id": entry_id,
                    "product": product,
                    "status": status,
                    "terminalRecords": [dict(value) for value in resolution.terminals],
                    "wrapperPackagePaths": list(resolution.wrappers),
                }
            )

        categories.append(
            {
                "categoryIndex": category_index,
                "displayName": _text(fields.get("DisplayName")),
                "entries": entries,
                "expectedKind": expected_kind,
                "key": key,
                "memberIds": sorted(member_ids),
                "source": {
                    "packagePath": source_package,
                    "property": f"Categories[{category_index}]",
                },
            }
        )

    unresolved.sort(
        key=lambda value: (
            value["categoryKey"],
            value["entryIndex"],
            value["packagePath"],
            value["reason"],
        )
    )
    memberships = {
        record_id: sorted(
            values,
            key=lambda value: (value["categoryKey"], value["entryIndex"], value["entryId"]),
        )
        for record_id, values in sorted(reverse.items())
    }
    return {
        "categoryAudit": category_audit,
        "categories": categories,
        "coverage": {
            "categories": len(categories),
            "ignoredCategories": len(category_audit["ignoredKeys"]),
            "unknownCategories": len(category_audit["unknownKeys"]),
            "productRows": product_rows,
            "resolvedProductRows": resolved_entries,
            "terminalLinks": terminal_links,
            "uniqueTerminalRecords": len(memberships),
            "unresolvedProductRows": product_rows - resolved_entries,
            "wrappersTraversed": len(seen_wrappers),
        },
        "memberships": memberships,
        "schemaVersion": 1,
        "source": {
            "basis": "Store_MainHub_Credits.Categories[].SoldItems[]",
            "packagePath": source_package,
        },
        "sourceFingerprint": source_fingerprint,
        "status": "complete" if not unresolved else "incomplete",
        "unresolved": unresolved,
    }


__all__ = [
    "CollectionFormatError",
    "IGNORED_COLLECTION_CATEGORIES",
    "PLANNER_CATEGORY_KINDS",
    "build_collection_document",
    "build_kit_membership_index",
    "build_progression_perk_index",
    "collection_product_package_paths",
    "collection_wrapper_dependency_paths",
    "kit_reward_registry_dependency_paths",
    "kit_reward_table_dependency_paths",
    "kit_reward_table_package_paths",
    "progression_reward_table_dependency_paths",
    "progression_reward_table_package_paths",
]
