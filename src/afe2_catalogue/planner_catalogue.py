"""Build the small, fail-closed projection consumed by the build editor.

The archive-wide semantic document deliberately remains an evidence superset.
This module is the boundary that admits only records backed by the live hub
store (the same authored inventory used by Collection), by a kit's authored
perk/ability entitlements, or by the game's authored progression-reward index.
"""

from __future__ import annotations

import copy
import re
from collections import defaultdict
from typing import Any, Mapping, Sequence

from .attachment_descriptions import (
    ATTACHMENT_DESCRIPTION_CONDITIONAL_STAT_INDENT,
    ATTACHMENT_DESCRIPTION_LINE_SEPARATOR,
    ATTACHMENT_DESCRIPTION_SECTION_SEPARATOR,
    AUGMENT_DESCRIPTION_PANEL_ORDER,
    augment_description_panel,
    compose_attachment_description,
)
from .errors import CatalogueError
from .grid_assets import resolve_chip_body_texture


_COMMON_FIELDS = (
    "chipVisual",
    "conditionalDescriptions",
    "description",
    "displayName",
    "grid",
    "icon",
    "itemTier",
    "silhouetteIcon",
    "staticStatLines",
    "visualClassification",
)

_ABILITY_ANCHOR_LAYOUT: dict[str, tuple[int, int, int, int]] = {
    # role: column, row, width, height
    "primary": (0, 1, 1, 4),
    "secondary": (9, 1, 1, 4),
    "passive": (3, 5, 4, 1),
}

_ATTACHMENT_TAG_PREFIX = "Item.Attachment."
_ITEM_INVENTORY_TAG_BY_TIER = {
    "major": "Ability.Consumable.InventoryType.Major",
    "minor": "Ability.Consumable.InventoryType.Minor",
}
_PLAYER_ITEM_SLOT_TAG = "Slot.Consumable.Custom"

_UNREAL_TEXT_MARKERS = (
    "/game/",
    "/script/",
    ".uasset",
    "default__",
    "nsloctext(",
    "loctext(",
    "invarianttext(",
    "stringtable(",
)
_GENERATED_OBJECT_NAME = re.compile(r"[A-Za-z0-9_./:\\-]+_C(?:_\d+)?")


def is_human_ui_text(value: Any, *, identities: Sequence[Any] = ()) -> bool:
    """Return whether a serialized UI string is safe to present as authored copy.

    IDs remain useful stable keys in the planner, but they are never acceptable
    substitutes for player-facing text.  This deliberately recognizes only
    unmistakable Unreal/package syntax; terse legitimate labels such as weapon
    model numbers and numeric stat lines remain valid.
    """

    if not isinstance(value, str) or not value.strip():
        return False
    text = value.strip()
    folded = text.casefold()
    if any(marker in folded for marker in _UNREAL_TEXT_MARKERS):
        return False
    if _GENERATED_OBJECT_NAME.fullmatch(text):
        return False

    forbidden: set[str] = set()
    for identity in identities:
        if not isinstance(identity, str) or not identity.strip():
            continue
        normalized = identity.strip().replace("\\", "/")
        forbidden.add(normalized.casefold())
        leaf = normalized.rsplit("/", 1)[-1]
        forbidden.add(leaf.casefold())
        if "." in leaf:
            forbidden.add(leaf.split(".", 1)[0].casefold())
    return folded not in forbidden


def _assert_human_record_text(source: Mapping[str, Any]) -> None:
    identities = (source.get("id"), source.get("packagePath"))
    if not is_human_ui_text(source.get("displayName"), identities=identities):
        raise CatalogueError(
            "selectable record had no human-readable authored display name: "
            + str(source.get("id"))
        )

    description = source.get("description")
    if (
        isinstance(description, str)
        and description.strip()
        and not is_human_ui_text(description, identities=identities)
    ):
        raise CatalogueError(
            "selectable record had internal-looking authored description text: "
            + str(source.get("id"))
        )

    for field in ("descriptionShort", "flavorText"):
        value = source.get(field)
        if (
            isinstance(value, str)
            and value.strip()
            and not is_human_ui_text(value, identities=identities)
        ):
            raise CatalogueError(
                f"selectable record had internal-looking authored {field} text: "
                + str(source.get("id"))
            )

    groups = source.get("conditionalDescriptions")
    if not isinstance(groups, list):
        return
    for group in groups:
        if not isinstance(group, Mapping):
            continue
        values = [group.get("conditionText")]
        lines = group.get("statLines")
        if isinstance(lines, list):
            values.extend(
                line.get("statText")
                for line in lines
                if isinstance(line, Mapping)
            )
        if any(
            isinstance(value, str)
            and value.strip()
            and not is_human_ui_text(value, identities=identities)
            for value in values
        ):
            raise CatalogueError(
                "selectable record had internal-looking conditional UI text: "
                + str(source.get("id"))
            )


def _category_token(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).casefold())


def _collection_members(
    collection: Mapping[str, Any],
) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    reverse = collection.get("memberships")
    if isinstance(reverse, Mapping):
        for record_id, memberships in reverse.items():
            if not isinstance(record_id, str) or not isinstance(memberships, list):
                continue
            for membership in memberships:
                if not isinstance(membership, Mapping):
                    continue
                token = _category_token(membership.get("categoryKey"))
                if token:
                    result[token].add(record_id)
        if result:
            return result
    categories = collection.get("categories")
    if not isinstance(categories, list):
        raise CatalogueError("collection document omitted its categories array")
    for category in categories:
        if not isinstance(category, Mapping):
            continue
        token = _category_token(
            category.get("key")
            or category.get("displayName")
            or category.get("category")
        )
        member_ids = category.get("memberIds")
        if not token or not isinstance(member_ids, list):
            continue
        result[token].update(value for value in member_ids if isinstance(value, str))
    return result


def _members_for(
    memberships: Mapping[str, set[str]],
    *aliases: str,
) -> set[str]:
    wanted = {_category_token(value) for value in aliases}
    result: set[str] = set()
    for token, values in memberships.items():
        if token in wanted or any(token.endswith(alias) for alias in wanted):
            result.update(values)
    return result


def _project_common(source: Mapping[str, Any], *, kind: str | None = None) -> dict[str, Any]:
    _assert_human_record_text(source)
    record = {
        "id": source.get("id"),
        "kind": kind or source.get("kind"),
        "packagePath": source.get("packagePath", source.get("id")),
    }
    for field in _COMMON_FIELDS:
        if field in source:
            record[field] = copy.deepcopy(source[field])
    return record


def _project_augment_description(source: Mapping[str, Any]) -> tuple[str | None, dict[str, Any]]:
    """Mirror every player-facing section in PopulateWithGunMod.

    Collection reward-pack copy is a different player-visible presentation and
    must not be used as fallback text for a weapon-specific implementation.
    The flattened description gives simple consumers the complete authored,
    comparable-stat, and conditional copy. The component fields and structured
    rows retain enough information for a closer panel rendering.
    """

    panel = copy.deepcopy(augment_description_panel(source))
    static_stat_lines = source.get("staticStatLines", [])
    if not isinstance(static_stat_lines, list):
        raise CatalogueError("Collection-visible augment static stat lines were malformed")
    return (
        compose_attachment_description(
            source,
            static_lines=static_stat_lines,
        ),
        panel,
    )


def _has_ui_description(record: Mapping[str, Any]) -> bool:
    description = record.get("description")
    return bool(
        (isinstance(description, str) and description.strip())
        or (
            isinstance(record.get("conditionalDescriptions"), list)
            and record["conditionalDescriptions"]
        )
    )


def _resolved_compatibility(
    source: Mapping[str, Any],
    *,
    label: str,
) -> Mapping[str, Any]:
    compatibility = source.get("compatibility")
    if not isinstance(compatibility, Mapping) or compatibility.get("status") != "resolved":
        raise CatalogueError(f"Collection-visible {label} compatibility was unresolved")
    return compatibility


def _filtered_attachment_compatibility(
    source: Mapping[str, Any],
    *,
    label: str,
    visible_weapon_ids: set[str],
) -> dict[str, Any]:
    compatibility = _resolved_compatibility(source, label=label)
    compatible_weapon_ids = sorted(
        {
            value
            for value in compatibility.get("compatibleWeaponIds", [])
            if isinstance(value, str) and value in visible_weapon_ids
        }
    )
    # Rules and effective tags remain in semantic-assets.json as audit evidence.
    # The editor-facing projection needs only the proven, visibility-filtered
    # relationship.
    return {
        "compatibleWeaponIds": compatible_weapon_ids,
        "source": compatibility.get("source"),
        "status": "resolved",
    }


def _project_slot(
    slot: Mapping[str, Any],
    *,
    compatible_ids: Sequence[str],
) -> dict[str, Any]:
    result = {
        key: copy.deepcopy(slot[key])
        for key in (
            "displayName",
            "index",
            "kind",
            "requiredLevel",
            "requiredModTags",
            "slotTags",
        )
        if key in slot
    }
    kind = slot.get("kind")
    authored_name = slot.get("displayName")
    if isinstance(authored_name, str):
        authored_name = authored_name.strip()
    else:
        authored_name = ""
    if kind == "component":
        raw_tags = slot.get("requiredModTags")
        attachment_tags = (
            [
                value[len(_ATTACHMENT_TAG_PREFIX) :]
                for value in raw_tags
                if isinstance(value, str)
                and value.startswith(_ATTACHMENT_TAG_PREFIX)
                and value != _ATTACHMENT_TAG_PREFIX
            ]
            if isinstance(raw_tags, list)
            else []
        )
        if len(attachment_tags) != 1:
            raise CatalogueError(
                "weapon component slot did not identify exactly one attachment category"
            )
        parts = [part for part in attachment_tags[0].split(".") if part]
        if not parts:
            raise CatalogueError("weapon component slot attachment category was empty")
        slot_category = ".".join(part.casefold() for part in parts)
        category_name = (
            " ".join([*parts[1:], parts[0]]) if len(parts) > 1 else parts[0]
        )
        name_source = "authored" if authored_name else "derived-required-mod-tag"
    elif kind in {"trait", "augment"}:
        slot_category = kind
        category_name = kind.title()
        name_source = "authored" if authored_name else "derived-slot-kind"
    else:
        raise CatalogueError("weapon slot had an unknown editor kind")
    result["displayName"] = authored_name or category_name
    result["displayNameSource"] = name_source
    result["slotCategory"] = slot_category
    result["slotCategoryDisplayName"] = category_name
    result["compatibleIds"] = sorted(set(compatible_ids))
    default_id = slot.get("defaultAttachmentId")
    if isinstance(default_id, str) and default_id in result["compatibleIds"]:
        result["defaultAttachmentId"] = default_id
    return result


def _project_item_slots(
    semantic: Mapping[str, Any],
    *,
    visible_items: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Publish the authored pre-mission Major/Minor picker slots."""

    raw_slots = semantic.get("itemSlots")
    if not isinstance(raw_slots, list) or not raw_slots:
        raise CatalogueError("semantic document omitted its player item slots")
    item_ids_by_tier: dict[str, list[str]] = defaultdict(list)
    for item in visible_items:
        item_id = item.get("id")
        tier = item.get("itemTier")
        if isinstance(item_id, str) and tier in _ITEM_INVENTORY_TAG_BY_TIER:
            item_ids_by_tier[tier].append(item_id)

    result: list[dict[str, Any]] = []
    indexes: set[int] = set()
    for raw_slot in raw_slots:
        if not isinstance(raw_slot, Mapping):
            raise CatalogueError("player item slot was malformed")
        index = raw_slot.get("index")
        tier = raw_slot.get("itemTier")
        inventory_tag = raw_slot.get("inventoryTypeTag")
        required_tags = raw_slot.get("requiredModTags")
        slot_tags = raw_slot.get("slotTags")
        evidence = raw_slot.get("evidence")
        expected_inventory_tag = _ITEM_INVENTORY_TAG_BY_TIER.get(tier)
        compatible_ids = sorted(set(item_ids_by_tier.get(str(tier), [])))
        if (
            type(index) is not int
            or index < 0
            or index in indexes
            or expected_inventory_tag is None
            or inventory_tag != expected_inventory_tag
            or not isinstance(required_tags, list)
            or not all(isinstance(value, str) and value for value in required_tags)
            or expected_inventory_tag not in required_tags
            or not isinstance(slot_tags, list)
            or not all(isinstance(value, str) and value for value in slot_tags)
            or _PLAYER_ITEM_SLOT_TAG not in slot_tags
            or not isinstance(evidence, Mapping)
            or evidence.get("source") != "serialized-uasset"
            or not compatible_ids
        ):
            raise CatalogueError("player item slot contract was malformed or had no choices")
        indexes.add(index)
        result.append(
            {
                "compatibleItemIds": compatible_ids,
                "displayName": f"{str(tier).title()} Item",
                "displayNameSource": "derived-inventory-type-tag",
                "evidence": copy.deepcopy(evidence),
                "index": index,
                "inventoryTypeTag": inventory_tag,
                "itemTier": tier,
                "requiredModTags": copy.deepcopy(required_tags),
                "slotTags": copy.deepcopy(slot_tags),
            }
        )
    if set(item_ids_by_tier) != set(_ITEM_INVENTORY_TAG_BY_TIER):
        raise CatalogueError("Collection did not expose both major and minor item choices")
    if (
        len(result) != 2
        or sorted(slot["itemTier"] for slot in result) != ["major", "minor"]
    ):
        raise CatalogueError(
            "player item slots did not expose exactly one major and one minor tier"
        )
    return result


def _source_metadata(
    *,
    game: Mapping[str, Any],
    extractor: Mapping[str, Any],
) -> tuple[dict[str, str], dict[str, str]]:
    published_game = {
        key: game.get(key)
        for key in ("buildId", "steamAppId")
    }
    published_extractor = {
        key: extractor.get(key)
        for key in ("name", "version")
    }
    if not all(
        isinstance(value, str) and value.strip()
        for value in [*published_game.values(), *published_extractor.values()]
    ):
        raise CatalogueError("planner source game/extractor metadata was malformed")
    return (
        {key: str(value) for key, value in published_game.items()},
        {key: str(value) for key, value in published_extractor.items()},
    )


def _filtered_weapon_compatibility(
    source: Mapping[str, Any],
    *,
    visible_mod_ids: set[str],
    visible_trait_ids: set[str],
    visible_augment_ids: set[str],
) -> dict[str, Any]:
    compatibility = _resolved_compatibility(source, label="weapon")
    raw_slots = compatibility.get("slots")
    if not isinstance(raw_slots, list) or not all(
        isinstance(slot, Mapping) for slot in raw_slots
    ):
        raise CatalogueError("Collection-visible weapon omitted its resolved slot list")

    by_kind: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    indexes: set[int] = set()
    for slot in raw_slots:
        index = slot.get("index")
        kind = slot.get("kind")
        if type(index) is not int or not isinstance(kind, str) or index in indexes:
            raise CatalogueError("Collection-visible weapon had malformed or duplicate slots")
        indexes.add(index)
        by_kind[kind].append(slot)
    if {kind: len(by_kind.get(kind, [])) for kind in ("component", "trait", "augment")} != {
        "component": 3,
        "trait": 1,
        "augment": 1,
    } or set(by_kind) != {"component", "trait", "augment"}:
        raise CatalogueError(
            "Collection-visible weapon did not have exactly three component, one trait, "
            "and one augment slot"
        )

    component_slots: list[dict[str, Any]] = []
    compatible_mod_ids: set[str] = set()
    for slot in sorted(by_kind["component"], key=lambda value: int(value["index"])):
        ids = sorted(
            {
                value
                for value in slot.get("compatibleIds", [])
                if isinstance(value, str) and value in visible_mod_ids
            }
        )
        if not ids:
            raise CatalogueError(
                "Collection-visible weapon component slot had no Collection-visible choices"
            )
        component_slots.append(_project_slot(slot, compatible_ids=ids))
        compatible_mod_ids.update(ids)

    trait_source = by_kind["trait"][0]
    trait_ids = sorted(
        {
            value
            for value in trait_source.get("compatibleIds", [])
            if isinstance(value, str) and value in visible_trait_ids
        }
    )
    if not trait_ids:
        raise CatalogueError(
            "Collection-visible weapon trait slot had no Collection-visible choices"
        )
    trait_slot = _project_slot(trait_source, compatible_ids=trait_ids)

    augment_source = by_kind["augment"][0]
    augment_ids = sorted(
        {
            value
            for value in augment_source.get("compatibleIds", [])
            if isinstance(value, str) and value in visible_augment_ids
        }
    )
    if not augment_ids:
        raise CatalogueError(
            "Collection-visible weapon augment slot had no Collection-visible choices"
        )
    augment_slot = _project_slot(augment_source, compatible_ids=augment_ids)

    result = {
        key: copy.deepcopy(compatibility[key])
        for key in (
            "collectionCategory",
            "collectionCategoryRaw",
            "kitIgnoreTags",
            "kitTags",
            "source",
            "weaponRole",
            "weaponRoleRaw",
            "weaponSubType",
            "weaponSubTypeRaw",
        )
        if key in compatibility
    }
    result.update(
        {
            "augmentSlot": augment_slot,
            "compatibleAugmentIds": augment_ids,
            "compatibleModIds": sorted(compatible_mod_ids),
            "compatibleTraitIds": trait_ids,
            "componentSlots": component_slots,
            "status": "resolved",
            "traitSlot": trait_slot,
        }
    )
    return result


def _kit_weapon_slot_matches(
    slot: Mapping[str, Any],
    weapon_compatibility: Mapping[str, Any],
) -> bool:
    """Mirror the fully-unlocked loadout picker dispatch and native role filter."""

    slot_role = slot.get("slotType")
    weapon_role = weapon_compatibility.get("weaponRole")
    kit_tags = weapon_compatibility.get("kitTags")
    ignore_tags = weapon_compatibility.get("kitIgnoreTags")
    if (
        not isinstance(slot_role, str)
        or not isinstance(weapon_role, str)
        or not isinstance(kit_tags, list)
        or not all(isinstance(value, str) for value in kit_tags)
        or not isinstance(ignore_tags, list)
        or not all(isinstance(value, str) for value in ignore_tags)
    ):
        raise CatalogueError("resolved weapon omitted its loadout-picker constraints")

    if slot_role != "any":
        if weapon_role != slot_role:
            return False
        kit_tag = slot.get("kitTag")
        return not isinstance(kit_tag, str) or kit_tag not in ignore_tags

    slot_subtype = slot.get("weaponSubtype")
    if not isinstance(slot_subtype, str):
        raise CatalogueError("kit weapon slot omitted its normalized subtype")
    if slot_subtype != "any":
        weapon_subtype = weapon_compatibility.get("weaponSubType")
        if not isinstance(weapon_subtype, str):
            raise CatalogueError("resolved weapon omitted its normalized subtype")
        return slot_subtype == weapon_subtype

    slot_type = slot.get("weaponType")
    weapon_type = weapon_compatibility.get("collectionCategory")
    if not isinstance(slot_type, str) or not isinstance(weapon_type, str):
        raise CatalogueError("kit or weapon omitted its normalized weapon type")
    return slot_type == "any" or slot_type == weapon_type


def _project_kit_weapon_slots(
    source_slots: Any,
    *,
    records_by_id: Mapping[str, Mapping[str, Any]],
    visible_weapon_ids: set[str],
) -> list[dict[str, Any]]:
    if not isinstance(source_slots, list) or not source_slots:
        raise CatalogueError("kit omitted its authored weapon slots")
    projected: list[dict[str, Any]] = []
    indexes: set[int] = set()
    for raw_slot in source_slots:
        if not isinstance(raw_slot, Mapping):
            raise CatalogueError("kit weapon slot was malformed")
        index = raw_slot.get("index")
        if (
            type(index) is not int
            or index in indexes
            or not all(
                isinstance(raw_slot.get(field), str) and raw_slot.get(field)
                for field in ("slotType", "weaponSubtype", "weaponType")
            )
            or (
                "kitTag" in raw_slot
                and (
                    not isinstance(raw_slot.get("kitTag"), str)
                    or not raw_slot.get("kitTag")
                )
            )
        ):
            raise CatalogueError(
                "kit weapon slot constraints or index were malformed or duplicated"
            )
        indexes.add(index)
        compatible: list[str] = []
        for weapon_id in sorted(visible_weapon_ids):
            weapon = records_by_id.get(weapon_id)
            compatibility = (
                weapon.get("compatibility") if isinstance(weapon, Mapping) else None
            )
            if not isinstance(compatibility, Mapping) or compatibility.get(
                "status"
            ) != "resolved":
                raise CatalogueError(
                    "Collection-visible weapon compatibility was unresolved while "
                    "building a kit loadout slot"
                )
            if _kit_weapon_slot_matches(raw_slot, compatibility):
                compatible.append(weapon_id)
        if not compatible:
            raise CatalogueError("kit weapon slot had no compatible Collection weapons")
        slot = copy.deepcopy(dict(raw_slot))
        slot["compatibleWeaponIds"] = compatible
        default_id = slot.get("defaultWeaponId")
        if isinstance(default_id, str) and default_id not in compatible:
            raise CatalogueError(
                "kit default weapon was not compatible and Collection-visible"
            )
        projected.append(slot)
    return sorted(projected, key=lambda value: int(value["index"]))


def _perk_availability(
    kits: Sequence[Mapping[str, Any]],
    ability_aliases: Mapping[str, str],
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for kit in kits:
        kit_id = kit.get("id")
        if not isinstance(kit_id, str):
            continue
        entitlements = kit.get("chipEntitlements")
        if not isinstance(entitlements, list):
            continue
        for entitlement in entitlements:
            if not isinstance(entitlement, Mapping):
                continue
            perk_id = entitlement.get("perkId")
            if not isinstance(perk_id, str):
                continue
            perk_id = ability_aliases.get(perk_id, perk_id)
            entry: dict[str, Any] = {"kitId": kit_id}
            for field in ("requiredRank", "grantedByPackagePath"):
                if field in entitlement:
                    entry[field] = copy.deepcopy(entitlement[field])
            result[perk_id].append(entry)
    for perk_id, values in list(result.items()):
        unique: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
        for item in values:
            identity = (
                item.get("kitId"),
                item.get("requiredRank"),
                item.get("grantedByPackagePath"),
            )
            unique[identity] = item
        result[perk_id] = sorted(
            unique.values(),
            key=lambda item: (str(item.get("kitId")), int(item.get("requiredRank", -1))),
        )
    return result


def _normalized_ordinary_perk_type(source: Mapping[str, Any]) -> str:
    """Return the authored chip family used by the editor, or fail closed.

    A perk's class entitlement and kit-eligibility metadata describe how it is
    unlocked, not whether an unlocked perk can be equipped by a kit.  The
    core/modifier distinction instead comes from the resolved semantic chip
    visual.  In particular, never guess it from a package path or display name.
    """

    visual = source.get("chipVisual")
    family = visual.get("family") if isinstance(visual, Mapping) else None
    status = visual.get("status") if isinstance(visual, Mapping) else None
    if family not in {"core", "modifier"} or status not in {"resolved", "inferred"}:
        raise CatalogueError(
            "selectable ordinary perk had no resolved core/modifier chip visual: "
            + str(source.get("id"))
        )
    if "perkType" in source and source.get("perkType") != family:
        raise CatalogueError(
            "selectable ordinary perk type disagreed with its chip visual: "
            + str(source.get("id"))
        )
    return family


def _shape_cells(shape: Mapping[str, Any]) -> list[tuple[int, int]]:
    occupied = shape.get("occupiedCells")
    if not isinstance(occupied, list):
        return []
    result: list[tuple[int, int]] = []
    for cell in occupied:
        if not isinstance(cell, Mapping):
            continue
        column = cell.get("column")
        row = cell.get("row")
        if type(column) is int and type(row) is int and column >= 0 and row >= 0:
            result.append((column, row))
    return result


def _cell_label(column: int, row: int) -> str:
    value = column + 1
    letters = ""
    while value:
        value, remainder = divmod(value - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return f"{letters}{row + 1}"


def _published_texture(texture: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(texture[key])
        for key in (
            "family",
            "height",
            "packagePath",
            "path",
            "pixelFormat",
            "sha256",
            "variant",
            "width",
        )
        if key in texture
    }


def _ability_anchor_texture(
    textures: Sequence[Mapping[str, Any]],
    *,
    role: str,
    column: int,
    width: int,
    height: int,
    board_columns: int,
) -> Mapping[str, Any] | None:
    # The widget uses role-specific horizontal art for active-ability anchors.
    if height == 1 and role in {"primary", "secondary"}:
        variant = "ultimate-horizontal" if role == "primary" else "tactical-horizontal"
        matches = [
            item
            for item in textures
            if item.get("role") == "chip-body"
            and item.get("family") == "replacer"
            and item.get("variant") == variant
        ]
        return matches[0] if len(matches) == 1 else None

    # The vertical secondary anchor abuts the right edge and uses the authored
    # right-handed cap. This follows layout position rather than a kit name.
    if column + width == board_columns:
        matches = [
            item
            for item in textures
            if item.get("role") == "chip-body"
            and item.get("family") == "replacer"
            and item.get("variant") == "right"
            and isinstance(item.get("footprint"), Mapping)
            and item["footprint"].get("width") == width
            and item["footprint"].get("height") == height
        ]
        if len(matches) == 1:
            return matches[0]

    return resolve_chip_body_texture(
        textures,
        family="replacer",
        width=width,
        height=height,
    )


def _kit_grid_layout(
    kit: Mapping[str, Any],
    records_by_id: Mapping[str, Mapping[str, Any]],
    *,
    columns: int,
    rows: int,
    textures: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    slots = kit.get("abilitySlots")
    if not isinstance(slots, list):
        raise CatalogueError("kit omitted its authored ability slots")
    choices_by_role = kit.get("selectableAbilityIdsByRole")
    if not isinstance(choices_by_role, Mapping) or set(choices_by_role) != set(
        _ABILITY_ANCHOR_LAYOUT
    ):
        raise CatalogueError("kit omitted its normalized ability role choices")
    slot_by_identity = {
        (slot.get("column"), slot.get("row"), slot.get("lockedChipId")): slot
        for slot in slots
        if isinstance(slot, Mapping)
    }
    perk_board = kit.get("perkBoard")
    placements = perk_board.get("lockedPlacements") if isinstance(perk_board, Mapping) else None
    if not isinstance(placements, list):
        raise CatalogueError("kit perk board omitted its authored locked placements")
    authored_by_role: dict[str, dict[str, Any]] = {}
    for placement in placements:
        if not isinstance(placement, Mapping):
            raise CatalogueError("kit perk board contained a malformed locked placement")
        column = placement.get("column")
        row = placement.get("row")
        chip_id = placement.get("chipId")
        if type(column) is not int or type(row) is not int or not isinstance(chip_id, str):
            raise CatalogueError("kit perk board locked placement could not be resolved")
        slot = slot_by_identity.get((column, row, chip_id), {})
        chip = records_by_id.get(chip_id) if isinstance(chip_id, str) else None
        ability = chip.get("ability") if isinstance(chip, Mapping) else None
        role = slot.get("role") if isinstance(slot, Mapping) else None
        if not isinstance(role, str) and isinstance(ability, Mapping):
            role = ability.get("role")
        if role not in {"primary", "secondary", "passive"}:
            raise CatalogueError("locked ability placement had no normalized editor role")
        if role in authored_by_role:
            raise CatalogueError("kit perk board contained duplicate ability-role anchors")
        shapes = (chip.get("grid") or {}).get("shapes") if isinstance(chip, Mapping) else None
        shape = (
            shapes[0]
            if isinstance(shapes, list)
            and len(shapes) == 1
            and isinstance(shapes[0], Mapping)
            else None
        )
        relative_cells = _shape_cells(shape or {})
        if not relative_cells:
            raise CatalogueError("locked ability placement had no unique normalized footprint")
        absolute = sorted((column + dx, row + dy) for dx, dy in relative_cells)
        shape_width = shape.get("width") if isinstance(shape, Mapping) else None
        shape_height = shape.get("height") if isinstance(shape, Mapping) else None
        if type(shape_width) is not int or type(shape_height) is not int:
            raise CatalogueError("locked ability placement footprint dimensions were invalid")
        expected_column, expected_row, expected_width, expected_height = (
            _ABILITY_ANCHOR_LAYOUT[role]
        )
        expected_cells = sorted(
            (expected_column + dx, expected_row + dy)
            for dy in range(expected_height)
            for dx in range(expected_width)
        )
        if (
            (column, row, shape_width, shape_height)
            != (expected_column, expected_row, expected_width, expected_height)
            or absolute != expected_cells
        ):
            raise CatalogueError(
                f"authored {role} anchor did not match the fixed editor board contract"
            )
        authored_by_role[role] = {
            "lockedChipId": chip_id,
            "slot": slot,
        }

    anchors: list[dict[str, Any]] = []
    for role, (column, row, shape_width, shape_height) in _ABILITY_ANCHOR_LAYOUT.items():
        choices = choices_by_role.get(role)
        if not isinstance(choices, list) or not all(
            isinstance(value, str) for value in choices
        ):
            raise CatalogueError("kit ability role choices were malformed")
        authored = authored_by_role.get(role)
        if authored is None and choices:
            raise CatalogueError(
                f"kit exposed {role} ability choices without an authored board anchor"
            )
        anchor_texture = _ability_anchor_texture(
            textures,
            role=role,
            column=column,
            width=shape_width,
            height=shape_height,
            board_columns=columns,
        )
        if anchor_texture is None:
            raise CatalogueError("locked ability slot had no unique authored body texture")
        absolute = sorted(
            (column + dx, row + dy)
            for dy in range(shape_height)
            for dx in range(shape_width)
        )
        anchor: dict[str, Any] = {
            "anchorSource": (
                "authored-locked-placement" if authored is not None else "fixed-reserved-slot"
            ),
            "cells": [
                {"column": x, "label": _cell_label(x, y), "row": y}
                for x, y in absolute
            ],
            "column": column,
            "role": role,
            "row": row,
            "renderingControlledBySlot": True,
            "rendering": {
                "chipBody": _published_texture(anchor_texture),
                "status": "resolved",
            },
            "selectableAbilityIds": list(choices),
        }
        if authored is not None:
            anchor["lockedChipId"] = authored["lockedChipId"]
        anchors.append(anchor)

    placeable = [
        (column, row)
        for row in range(rows)
        for column in range(columns)
        if row == 0 or 1 <= column < columns - 1
    ]
    return {
        "anchors": sorted(anchors, key=lambda item: (item["row"], item["column"], item["role"])),
        "baseBoard": {"columns": columns, "rows": rows},
        "kitId": kit.get("id"),
        "placeableCellCount": len(placeable),
        "placeableCells": [
            {"column": column, "label": _cell_label(column, row), "row": row}
            for column, row in placeable
        ],
        "renderExtent": {"columns": columns, "rows": rows + 1},
    }


def _grid_contract(
    *,
    kits: Sequence[Mapping[str, Any]],
    records_by_id: Mapping[str, Mapping[str, Any]],
    grid_assets: Mapping[str, Any],
) -> dict[str, Any]:
    board = (grid_assets.get("layoutMetrics") or {}).get("board")
    if not isinstance(board, Mapping) or board.get("status") != "parsed":
        raise CatalogueError("planner catalogue requires parsed perk-grid board dimensions")
    columns = board.get("columns")
    rows = board.get("rows")
    if type(columns) is not int or type(rows) is not int or columns <= 0 or rows <= 0:
        raise CatalogueError("perk-grid board dimensions were invalid")
    if (columns, rows) != (10, 5):
        raise CatalogueError("perk-grid board did not match the 10x5 editor contract")
    textures = grid_assets.get("textures")
    if not isinstance(textures, list):
        raise CatalogueError("grid asset document omitted its texture array")
    layouts = [
        _kit_grid_layout(
            kit,
            records_by_id,
            columns=columns,
            rows=rows,
            textures=[item for item in textures if isinstance(item, Mapping)],
        )
        for kit in kits
    ]
    invalid_counts = [
        layout.get("kitId")
        for layout in layouts
        if layout.get("placeableCellCount") != 42
    ]
    if invalid_counts:
        raise CatalogueError(
            "perk-grid layout did not expose the required 42 placeable cells for kit(s): "
            + ", ".join(str(value) for value in invalid_counts)
        )
    contract: dict[str, Any] = {
        "coordinateSystem": {
            "columnOrigin": 0,
            "displayLabels": "spreadsheet-style, one-based rows",
            "rowOrigin": 0,
        },
        "kitLayouts": layouts,
        # Hand-authored editor policy, not serialized evidence. No package
        # states these rules, so they carry a status marker rather than sitting
        # unlabelled beside extracted fields and reading as proven.
        "placementRules": {
            "status": "authored-editor-policy",
            "reason": (
                "placement and connection behaviour is authored from observed play, not "
                "recovered from the packages; correct it here when the board disagrees"
            ),
            "core": {"mayOccupyAnyPlaceableCells": True},
            "modifier": {
                "adjacency": "orthogonal-only",
                "adjacencyOffsets": [
                    {"column": -1, "row": 0},
                    {"column": 0, "row": -1},
                    {"column": 0, "row": 1},
                    {"column": 1, "row": 0},
                ],
                "connectionRule": (
                    "every modifier selects one dependency-compatible target; following "
                    "modifier targets recursively must be acyclic and terminate at a core "
                    "perk, passive, or ability; a modifier joins that family only by "
                    "orthogonally touching a chip already in it, so each family is one "
                    "connected run of its own chips and chips of other families do not "
                    "conduct"
                ),
                "diagonalAdjacencyCounts": False,
                "selectedTargetField": "targetId",
                "targetSelectionRequired": True,
                "targetTraversal": "directed-and-acyclic",
            },
            "rotation": {
                "allowed": True,
                "recordField": "records[].grid.allowedRotations",
            },
        },
    }
    perk_color_palette = grid_assets.get("perkColorPalette")
    if isinstance(perk_color_palette, Mapping):
        contract["perkColorPalette"] = copy.deepcopy(perk_color_palette)
    family_connectors = [
        item
        for item in textures
        if isinstance(item, Mapping)
        and item.get("role") == "connector"
        and item.get("variant") == "ghost"
        and isinstance(item.get("path"), str)
    ]
    if len(family_connectors) == 1:
        contract["familyConnector"] = copy.deepcopy(family_connectors[0])
    return contract


def _attach_render_bindings(
    records: Sequence[dict[str, Any]],
    grid_assets: Mapping[str, Any],
) -> tuple[int, int]:
    textures = grid_assets.get("textures")
    if not isinstance(textures, list):
        raise CatalogueError("grid asset document omitted its texture array")
    resolved_count = 0
    unresolved_count = 0
    for record in records:
        if record.get("kind") == "ability":
            record["rendering"] = {
                "reason": (
                    "ability chip bodies are selected by the fixed slot role, side, and "
                    "orientation; generic family-plus-footprint resolution is insufficient"
                ),
                "status": "slot-controlled",
            }
            continue
        if record.get("kind") != "perk":
            continue
        grid = record.get("grid")
        shapes = grid.get("shapes") if isinstance(grid, Mapping) else None
        if not isinstance(shapes, list) or not shapes:
            record["rendering"] = {
                "reason": "selectable grid record had no normalized shape",
                "status": "unresolved",
            }
            unresolved_count += 1
            continue
        rotations = grid.get("allowedRotations", [])
        quarter_turn = isinstance(rotations, list) and any(
            value in {"Clockwise90", "Clockwise270"} for value in rotations
        )
        footprints: set[tuple[int, int]] = set()
        for shape in shapes:
            if not isinstance(shape, Mapping):
                continue
            width = shape.get("width")
            height = shape.get("height")
            if type(width) is int and type(height) is int and width > 0 and height > 0:
                footprints.add((width, height))
                if quarter_turn:
                    footprints.add((height, width))
        chip_visual = record.get("chipVisual")
        family = chip_visual.get("family") if isinstance(chip_visual, Mapping) else None
        bindings: list[dict[str, Any]] = []
        missing: list[dict[str, int]] = []
        for width, height in sorted(footprints):
            texture = resolve_chip_body_texture(
                textures,
                family=family if isinstance(family, str) else None,
                width=width,
                height=height,
            )
            if texture is None:
                missing.append({"height": height, "width": width})
                continue
            bindings.append(
                _published_texture(texture)
                | {"footprint": {"height": height, "width": width}}
            )
        if bindings and not missing and len(bindings) == len(footprints):
            record["rendering"] = {
                "chipBodyByFootprint": bindings,
                "contentIconPath": (record.get("icon") or {}).get("path"),
                "status": "resolved",
            }
            resolved_count += 1
        else:
            record["rendering"] = {
                "chipBodyByFootprint": bindings,
                "missingFootprints": missing,
                "reason": "one or more rotated footprints had no unique chip-body texture",
                "status": "unresolved",
            }
            unresolved_count += 1
    return resolved_count, unresolved_count


def build_planner_catalogue(
    *,
    semantic: Mapping[str, Any],
    collection: Mapping[str, Any],
    grid_assets: Mapping[str, Any],
    game: Mapping[str, Any],
    extractor: Mapping[str, Any],
    source_fingerprint: str,
) -> dict[str, Any]:
    """Return a deterministic flat catalogue containing editor-selectable data."""

    published_game, published_extractor = _source_metadata(
        game=game,
        extractor=extractor,
    )
    for name, document in (("semantic", semantic), ("collection", collection), ("grid", grid_assets)):
        if document.get("sourceFingerprint") != source_fingerprint:
            raise CatalogueError(f"{name} source fingerprint did not match planner catalogue")
    source_records = [
        item for item in semantic.get("records", []) if isinstance(item, Mapping)
    ]
    by_id = {
        item["id"]: item
        for item in source_records
        if isinstance(item.get("id"), str)
    }
    all_kits = {
        item["id"]: item
        for item in source_records
        if item.get("kind") == "kit" and isinstance(item.get("id"), str)
    }
    kit_membership = collection.get("kitMembership")
    if not isinstance(kit_membership, Mapping):
        raise CatalogueError("collection document omitted its canonical kit membership")
    kit_members = kit_membership.get("memberIds")
    kit_membership_status = kit_membership.get("status")
    if (
        kit_membership_status not in {"complete", "incomplete"}
        or not isinstance(kit_members, list)
        or not kit_members
        or not all(isinstance(value, str) for value in kit_members)
        or len(set(kit_members)) != len(kit_members)
    ):
        raise CatalogueError("canonical kit membership was malformed")
    unknown_kit_members = sorted(set(kit_members) - set(all_kits))
    if unknown_kit_members:
        raise CatalogueError("canonical kit membership referenced an unknown semantic kit")
    kits = sorted(
        (all_kits[value] for value in kit_members),
        key=lambda item: str(item.get("id")),
    )
    kit_ids = [item["id"] for item in kits if isinstance(item.get("id"), str)]
    collection_by_category = _collection_members(collection)

    selected: dict[str, set[str]] = {
        "weapon": _members_for(collection_by_category, "weapons"),
        "mod": _members_for(
            collection_by_category,
            "magazines",
            "optics",
            "underbarrel",
            "muzzles",
            "barrels",
            "armature",
            "armatures",
        ),
        "trait": _members_for(collection_by_category, "traits", "weapontraits"),
        "item": _members_for(collection_by_category, "items"),
    }
    store_perks = _members_for(collection_by_category, "perks", "kitperks")
    all_ability_concepts = [
        item for item in semantic.get("kitAbilities", []) if isinstance(item, Mapping)
    ]
    ability_aliases = {
        source_id: concept["id"]
        for concept in all_ability_concepts
        if isinstance(concept.get("id"), str)
        for source_id in concept.get("sourceChipIds", [])
        if isinstance(source_id, str)
    }
    concepts_by_id = {
        item["id"]: item
        for item in all_ability_concepts
        if isinstance(item.get("id"), str)
    }
    authored_ability_kits: dict[str, set[str]] = defaultdict(set)
    authored_ability_roles: dict[str, set[str]] = defaultdict(set)
    for kit in kits:
        roles = kit.get("abilityPerkIdsByRole")
        if not isinstance(roles, Mapping):
            raise CatalogueError("kit omitted its authored ability choices")
        for role in ("primary", "secondary", "passive"):
            values = roles.get(role)
            if not isinstance(values, list):
                raise CatalogueError("kit ability role list was malformed")
            for value in values:
                if not isinstance(value, str):
                    raise CatalogueError("kit ability role list contained a malformed ID")
                canonical = ability_aliases.get(value, value)
                if canonical not in concepts_by_id:
                    raise CatalogueError("kit ability list referenced an unknown concept")
                authored_ability_kits[canonical].add(kit["id"])
                authored_ability_roles[canonical].add(role)
    ability_ids = set(authored_ability_kits)
    ability_concepts = [concepts_by_id[value] for value in sorted(ability_ids)]
    for concept in ability_concepts:
        concept_id = concept["id"]
        available = {
            value
            for value in concept.get("availableToKitIds", [])
            if isinstance(value, str) and value in set(kit_ids)
        }
        if available != authored_ability_kits[concept_id]:
            raise CatalogueError("ability concept availability disagreed with kit-authored choices")
        if authored_ability_roles[concept_id] != {concept.get("role")}:
            raise CatalogueError("ability concept role disagreed with kit-authored choices")
    availability = _perk_availability(kits, ability_aliases)
    store_perks = {ability_aliases.get(value, value) for value in store_perks}
    progression = collection.get("progressionPerks")
    if not isinstance(progression, Mapping):
        raise CatalogueError("collection document omitted its progression perk index")
    progression_members = progression.get("memberIds")
    progression_status = progression.get("status")
    if progression_status not in {"complete", "incomplete"} or not isinstance(
        progression_members, list
    ) or not all(isinstance(value, str) for value in progression_members):
        raise CatalogueError("canonical progression perk index was malformed")
    progression_perks = {
        ability_aliases.get(value, value) for value in progression_members
    }
    candidate_selectable_perk_ids = set(availability) | store_perks | progression_perks
    ordinary_perk_ids = candidate_selectable_perk_ids - ability_ids
    # ChipEntitlements, Store membership, and progression rewards prove how a
    # perk is unlocked. Once unlocked, every ordinary perk is selectable by
    # every admitted kit; placement remains constrained by dependencies below.
    perk_kit_ids = {
        perk_id: set(kit_ids)
        for perk_id in ordinary_perk_ids
    }
    selectable_perk_ids = candidate_selectable_perk_ids
    selectable_ids = selectable_perk_ids | ability_ids

    records: list[dict[str, Any]] = []
    projected_kits: list[dict[str, Any]] = []
    for source in kits:
        record = _project_common(source)
        authored_roles = source.get("abilityPerkIdsByRole")
        if not isinstance(authored_roles, Mapping):
            raise CatalogueError("kit omitted its authored ability choices")
        normalized_roles: dict[str, list[str]] = {}
        for role in ("primary", "secondary", "passive"):
            values = authored_roles.get(role)
            if not isinstance(values, list):
                raise CatalogueError("kit ability role list was malformed")
            normalized = sorted(
                {ability_aliases.get(value, value) for value in values if isinstance(value, str)}
            )
            if any(value not in ability_ids for value in normalized):
                raise CatalogueError("kit ability list referenced a non-selectable ability")
            normalized_roles[role] = normalized
        record["selectableAbilityIdsByRole"] = normalized_roles
        for field in (
            "characterClassPackagePath",
            "perkBoard",
        ):
            if field in source:
                record[field] = copy.deepcopy(source[field])
        record["weaponSlots"] = _project_kit_weapon_slots(
            source.get("weaponSlots"),
            records_by_id=by_id,
            visible_weapon_ids=selected["weapon"],
        )
        source_slots = source.get("abilitySlots")
        if not isinstance(source_slots, list):
            raise CatalogueError("kit omitted its authored ability slots")
        record["abilitySlots"] = copy.deepcopy(source_slots)
        for slot in record["abilitySlots"]:
            if not isinstance(slot, dict):
                raise CatalogueError("kit ability slot was malformed")
            role = slot.get("role")
            if role not in {"primary", "secondary", "passive"}:
                raise CatalogueError("kit ability slot had no normalized editor role")
            choices = slot.get("selectableAbilityPerkIds")
            if not isinstance(choices, list):
                raise CatalogueError("kit ability slot omitted its selectable choices")
            canonical = sorted(
                {
                    ability_aliases.get(value, value)
                    for value in choices
                    if isinstance(value, str)
                }
            )
            if any(value not in ability_ids for value in canonical):
                raise CatalogueError("kit ability slot referenced a non-selectable ability")
            if canonical != normalized_roles[role]:
                raise CatalogueError("kit ability slot choices disagreed with its authored role list")
            slot["selectableAbilityIds"] = canonical
            slot.pop("selectableAbilityPerkIds", None)
        per_kit = sorted(
            perk_id
            for perk_id, allowed in perk_kit_ids.items()
            if source.get("id") in allowed
        )
        record["selectablePerkIds"] = per_kit
        records.append(record)
        projected_kits.append(record)

    for concept in sorted(ability_concepts, key=lambda item: str(item.get("id"))):
        source = by_id.get(concept.get("id"))
        if source is None:
            raise CatalogueError("authored ability concept had no semantic source record")
        record = _project_common(source, kind="ability")
        for field in ("gameplayAbilityPackagePath", "role", "sourceChipIds"):
            if field in concept:
                record[field] = copy.deepcopy(concept[field])
        record["availableToKitIds"] = sorted(
            {
                value
                for value in concept.get("availableToKitIds", [])
                if isinstance(value, str) and value in set(kit_ids)
            }
        )
        origin_kit_id = concept.get("originKitId")
        if isinstance(origin_kit_id, str) and origin_kit_id in set(kit_ids):
            record["originKitId"] = origin_kit_id
        if "dependencies" in source:
            record["dependencies"] = copy.deepcopy(source["dependencies"])
        records.append(record)

    for perk_id in sorted(selectable_perk_ids - ability_ids):
        source = by_id.get(perk_id)
        if source is None or source.get("kind") != "perk":
            raise CatalogueError("authored selectable perk had no semantic perk record")
        record = _project_common(source)
        entries = copy.deepcopy(availability.get(perk_id, []))
        if entries:
            record["availability"] = entries
        record["availableToKitIds"] = sorted(perk_kit_ids[perk_id])
        record["selectionSources"] = sorted(
            source_name
            for source_name, selected_ids in (
                ("class-entitlement", set(availability)),
                ("progression-unlock", progression_perks),
                ("wrench-collection", store_perks),
            )
            if perk_id in selected_ids
        )
        record["perkType"] = _normalized_ordinary_perk_type(source)
        if "dependencies" in source:
            record["dependencies"] = copy.deepcopy(source["dependencies"])
        records.append(record)

    concept_by_id = {
        item["id"]: item
        for item in collection.get("conceptRecords", [])
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    }
    augment_category = next(
        (
            item
            for item in collection.get("categories", [])
            if isinstance(item, Mapping)
            and _category_token(item.get("key")) == "augmentpacks"
        ),
        None,
    )
    augment_records = 0
    augment_packs = 0
    collection_augment_implementations: set[str] = set()
    visible_weapon_ids = selected["weapon"]
    augment_concept_by_terminal_id: dict[str, str] = {}
    visible_augment_ids: set[str] = set()
    for entry in (augment_category or {}).get("entries", []):
        if not isinstance(entry, Mapping) or entry.get("status") != "resolved":
            continue
        concept_id = entry.get("id")
        concept = concept_by_id.get(concept_id)
        if not isinstance(concept_id, str) or concept is None:
            raise CatalogueError("Collection augment entry had no normalized concept record")
        terminal_ids = sorted(
            {
                item.get("id")
                for item in entry.get("terminalRecords", [])
                if isinstance(item, Mapping) and isinstance(item.get("id"), str)
            }
        )
        visible_variants = 0
        implementation_by_weapon: dict[str, str] = {}
        for terminal_id in terminal_ids:
            source = by_id.get(terminal_id)
            if source is None or source.get("kind") != "augment":
                raise CatalogueError("Collection augment concept referenced a missing implementation")
            collection_augment_implementations.add(terminal_id)
            previous_concept = augment_concept_by_terminal_id.get(terminal_id)
            if previous_concept is not None and previous_concept != concept_id:
                raise CatalogueError(
                    "one Collection augment implementation belonged to multiple concepts"
                )
            augment_concept_by_terminal_id[terminal_id] = concept_id
            compatibility = source.get("compatibility")
            if not isinstance(compatibility, Mapping) or compatibility.get("status") != "resolved":
                raise CatalogueError("Collection augment implementation compatibility was unresolved")
            visible_compatibility = sorted(
                value
                for value in compatibility.get("compatibleWeaponIds", [])
                if isinstance(value, str) and value in visible_weapon_ids
            )
            if not visible_compatibility:
                continue
            for weapon_id in visible_compatibility:
                previous = implementation_by_weapon.get(weapon_id)
                if previous is not None and previous != terminal_id:
                    raise CatalogueError(
                        "augment pack resolved multiple implementations for one visible weapon"
                    )
                implementation_by_weapon[weapon_id] = terminal_id
            variant = _project_common(source)
            description, description_panel = _project_augment_description(source)
            variant.update(
                {
                    "availability": copy.deepcopy(entry.get("availability")),
                    "collectionCategory": "AugmentPacks",
                    "collectionConceptId": concept_id,
                    "compatibleWeaponIds": visible_compatibility,
                    "description": description,
                    "descriptionPanel": description_panel,
                }
            )
            records.append(variant)
            visible_augment_ids.add(terminal_id)
            augment_records += 1
            visible_variants += 1
        if not visible_variants:
            raise CatalogueError("Collection augment concept had no visible compatible implementation")
        augment_packs += 1

    for kind in ("weapon", "mod", "trait", "item"):
        for record_id in sorted(selected[kind]):
            source = by_id.get(record_id)
            if source is None or source.get("kind") != kind:
                raise CatalogueError(
                    f"Collection-visible {kind} had no matching semantic record"
                )
            record = _project_common(source)
            for field in (
                "collectionCategory",
                "gunSubtype",
                "gunType",
                "socket",
            ):
                if field in source:
                    record[field] = copy.deepcopy(source[field])
            if kind == "weapon":
                record["compatibility"] = _filtered_weapon_compatibility(
                    source,
                    visible_mod_ids=selected["mod"],
                    visible_trait_ids=selected["trait"],
                    visible_augment_ids=visible_augment_ids,
                )
                # Keep the fixed component slots at the top level as the most
                # common frontend lookup while retaining the complete relation
                # under compatibility.
                record["componentSlots"] = copy.deepcopy(
                    record["compatibility"]["componentSlots"]
                )
            elif kind in {"mod", "trait"}:
                if "description" in source:
                    record["authoredDescription"] = copy.deepcopy(source["description"])
                static_stat_lines = source.get("staticStatLines", [])
                if not isinstance(static_stat_lines, list):
                    raise CatalogueError(
                        f"Collection-visible {kind} static stat lines were malformed"
                    )
                record["description"] = compose_attachment_description(
                    source,
                    static_lines=static_stat_lines,
                )
                record["compatibility"] = _filtered_attachment_compatibility(
                    source,
                    label=kind,
                    visible_weapon_ids=visible_weapon_ids,
                )
            else:
                if record.get("itemTier") not in {"major", "minor"}:
                    raise CatalogueError("Collection-visible item had no major/minor tier")
                record["availableToKitIds"] = list(kit_ids)
            records.append(record)

    record_ids = {record.get("id") for record in records}
    for record in records:
        dependencies = record.get("dependencies")
        if not isinstance(dependencies, dict):
            continue
        for field in ("possibleTargetPerkIds", "possibleModifierPerkIds"):
            values = dependencies.get(field)
            if isinstance(values, list):
                dependencies[field] = sorted(
                    {
                        canonical
                        for value in values
                        if isinstance(value, str)
                        for canonical in (ability_aliases.get(value, value),)
                        if canonical in selectable_ids and canonical in record_ids
                    }
                )
        if dependencies.get("requiresConnectedCompatibleTarget") is True:
            targets = dependencies.get("possibleTargetPerkIds", [])
            if not isinstance(targets, list) or not targets:
                raise CatalogueError(
                    "selectable modifier had no compatible selectable dependency target: "
                    + str(record.get("id"))
                )
            dependencies["targetSelection"] = {
                "candidateIds": list(targets) if isinstance(targets, list) else [],
                "recordField": "targetId",
                "required": True,
            }

    records.sort(key=lambda item: (str(item.get("kind")), str(item.get("id"))))
    item_slots = _project_item_slots(
        semantic,
        visible_items=[record for record in records if record.get("kind") == "item"],
    )
    rendered, render_unresolved = _attach_render_bindings(records, grid_assets)
    coverage = {
        "augmentImplementations": augment_records,
        "augmentPacks": augment_packs,
        "collectionAugmentImplementations": len(collection_augment_implementations),
        "collectionMembersByKind": {
            **{kind: len(values) for kind, values in sorted(selected.items())},
            "augment": augment_packs,
        },
        "records": len(records),
        "recordsByKind": {
            kind: sum(1 for record in records if record.get("kind") == kind)
            for kind in sorted({str(record.get("kind")) for record in records})
        },
        "recordsWithConditionalDescriptions": sum(
            1
            for record in records
            if isinstance(record.get("conditionalDescriptions"), list)
            and bool(record["conditionalDescriptions"])
        ),
        "recordsWithStaticStatLines": sum(
            1
            for record in records
            if isinstance(record.get("staticStatLines"), list)
            and bool(record["staticStatLines"])
        ),
        "recordsMissingDescription": sum(
            1 for record in records if not _has_ui_description(record)
        ),
        "recordsMissingDisplayName": sum(
            1
            for record in records
            if not isinstance(record.get("displayName"), str)
            or not record["displayName"].strip()
        ),
        "itemSlots": len(item_slots),
        "selectablePerksBySource": {
            "classEntitlement": len(
                (set(availability) - ability_ids) & selectable_perk_ids
            ),
            "progressionUnlock": len(
                (progression_perks - ability_ids) & selectable_perk_ids
            ),
            "wrenchCollection": len(
                (store_perks - ability_ids) & selectable_perk_ids
            ),
        },
        "selectableGridRecordsRenderResolved": rendered,
        "selectableGridRecordsRenderUnresolved": render_unresolved,
        "sourceSemanticRecordsExcluded": len(source_records)
        - len({record.get("id") for record in records if record.get("id") in by_id}),
    }
    return {
        "coverage": coverage,
        "extractor": published_extractor,
        "game": published_game,
        "itemSlots": item_slots,
        "perkGrid": _grid_contract(
            kits=projected_kits,
            records_by_id=by_id,
            grid_assets=grid_assets,
        ),
        "records": records,
        "schemaVersion": 1,
        "selectionBasis": (
            "authored class-unlock rewards, live Store_MainHub_Credits membership, "
            "class-authored ability and ChipEntitlement lists, plus "
            "RewardTable_Settings_V1 progression rewards"
        ),
        "sourceCoverage": {
            "kitMembership": {
                "coverage": copy.deepcopy(kit_membership.get("coverage", {})),
                "status": kit_membership_status,
            },
            "progressionPerks": {
                "coverage": copy.deepcopy(progression.get("coverage", {})),
                "status": progression_status,
            }
        },
        "sourceFingerprint": source_fingerprint,
        "textContract": {
            "attachmentDescriptionComposition": {
                "authoredDescriptionField": "authoredDescription",
                "conditionalDescriptionField": "conditionalDescriptions",
                "conditionalStatIndent": ATTACHMENT_DESCRIPTION_CONDITIONAL_STAT_INDENT,
                "descriptionField": "description",
                "lineSeparator": ATTACHMENT_DESCRIPTION_LINE_SEPARATOR,
                "order": [
                    "authoredDescription",
                    "staticStatLines",
                    "conditionalDescriptions",
                ],
                "sectionSeparator": ATTACHMENT_DESCRIPTION_SECTION_SEPARATOR,
                "staticStatField": "staticStatLines",
            },
            "augmentDescriptionComposition": {
                "componentField": "descriptionPanel",
                "conditionalDescriptionField": "conditionalDescriptions",
                "conditionalStatIndent": ATTACHMENT_DESCRIPTION_CONDITIONAL_STAT_INDENT,
                "descriptionField": "description",
                "lineSeparator": ATTACHMENT_DESCRIPTION_LINE_SEPARATOR,
                "order": [
                    "descriptionPanel",
                    "staticStatLines",
                    "conditionalDescriptions",
                ],
                "panelOrder": list(AUGMENT_DESCRIPTION_PANEL_ORDER),
                "sectionSeparator": ATTACHMENT_DESCRIPTION_SECTION_SEPARATOR,
                "staticStatField": "staticStatLines",
            },
            "conditionalDescriptionField": "conditionalDescriptions",
            "descriptionField": "description",
            "displayNameField": "displayName",
            "packagePathIsDisplayText": False,
            "richTextFormat": "unreal-rich-text-subset",
        },
    }


__all__ = ["build_planner_catalogue", "is_human_ui_text"]
