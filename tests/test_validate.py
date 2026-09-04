from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from afe2_catalogue.validate import validate_outputs  # noqa: E402


def valid_grid() -> dict[str, object]:
    return {
        "allowedRotations": [
            "Default",
            "Clockwise90",
            "Clockwise180",
            "Clockwise270",
        ],
        "shapes": [
            {
                "cellCount": 2,
                "collisionMask": [1, 1],
                "height": 1,
                "occupiedCells": [
                    {"column": 0, "row": 0},
                    {"column": 1, "row": 0},
                ],
                "size": "1x2",
                "width": 2,
            }
        ],
    }


def valid_conditional_descriptions() -> list[dict[str, object]]:
    return [
        {
            "conditionText": "<Bold>On Taking Damage</>:",
            "statLines": [
                {
                    "displayType": "Percent",
                    "result": "HigherIsBetter",
                    "statText": "Damage Resistance",
                    "statValue": 25.0,
                },
                {
                    "displayType": "None",
                    "result": "HigherIsBetter",
                    "statText": "Lasts <Bold>5 seconds</>.",
                    "statValue": 0.0,
                },
            ],
        }
    ]


def valid_static_stat_lines() -> list[dict[str, object]]:
    return [
        {
            "attribute": "GunGameplayAttributes.TimeToReload",
            "displayText": "+20.0% Reload Speed",
            "displayType": "Percent",
            "displayValue": "+20.0%",
            "effectPackagePath": (
                "/Game/Blueprints/Gameplay/GameplayEffects/AvoMods/"
                "Avo_Weapon_ReloadSpeed"
            ),
            "result": "HigherIsBetter",
            "sortOrder": 13,
            "statText": "Reload Speed",
            "statValue": 20.0,
        }
    ]


def valid_reload_speed_effect() -> dict[str, object]:
    return {
        "configuredMagnitude": 1.2,
        "definition": {
            "modifiers": [
                {
                    "attribute": "TimeToReload",
                    "magnitudeCalculationType": "setbycaller",
                    "operation": "divide",
                    "qualifiedAttribute": "GunGameplayAttributes.TimeToReload",
                }
            ],
            "status": "parsed",
        },
        "effectPackagePath": (
            "/Game/Blueprints/Gameplay/GameplayEffects/AvoMods/"
            "Avo_Weapon_ReloadSpeed"
        ),
        "serializedFlags": {
            "bInterpretTableLookupAsPercent": True,
            "bNormalizePercentForEffectMagnitude": False,
            "bVisibleOnUI": True,
        },
    }


def planner_record(
    arguments: dict[str, object], record_id: str
) -> dict[str, object]:
    return next(
        record
        for record in arguments["planner_catalogue"]["records"]
        if record["id"] == record_id
    )


def source_record(
    arguments: dict[str, object], record_id: str
) -> dict[str, object]:
    return next(
        record
        for record in arguments["candidates"]["records"]
        if record["id"] == record_id
    )


def valid_semantic_candidates() -> list[dict[str, object]]:
    start_kit = "kit:start"
    custom_kit = "kit:custom"
    implementation = "ability:implementation"
    base = "perk:base"
    alias = "perk:alias"
    modifier = "perk:modifier"
    return [
        {
            "abilityPerkIdsByRole": {
                "passive": [],
                "primary": [],
                "secondary": [base],
            },
            "id": start_kit,
            "kind": "kit",
        },
        {
            "abilityPerkIdsByRole": {
                "passive": [],
                "primary": [],
                "secondary": [base],
            },
            "id": custom_kit,
            "kind": "kit",
        },
        {
            "id": implementation,
            "implementationForAbilityIds": [base],
            "kind": "ability",
        },
        {
            "ability": {
                "availableToKitIds": [start_kit, custom_kit],
                "originKitId": start_kit,
                "role": "secondary",
                "sourceChipIds": [base, alias],
            },
            "dependencies": {"possibleModifierPerkIds": [modifier]},
            "grid": valid_grid(),
            "id": base,
            "kind": "perk",
            "kitEligibility": {
                "alternativeKitIds": [custom_kit],
                "originKitId": start_kit,
                "restrictedKitId": start_kit,
            },
        },
        {
            "ability": {
                "aliasOf": base,
                "role": "secondary",
            },
            "grid": valid_grid(),
            "id": alias,
            "kind": "perk",
            "kitEligibility": {
                "originKitId": start_kit,
                "restrictedKitId": custom_kit,
            },
        },
        {
            "dependencies": {
                "possibleTargetPerkIds": [base],
                "requiresConnectedCompatibleTarget": True,
            },
            "grid": valid_grid(),
            "id": modifier,
            "kind": "perk",
            "kitEligibility": {
                "alternativeKitIds": [custom_kit],
                "restrictedKitId": start_kit,
            },
        },
    ]


def valid_planner_arguments() -> dict[str, object]:
    fingerprint = "sha256:planner-fixture"
    kit_id = "kit:one"
    ability_id = "ability:primary"
    perk_id = "perk:core"
    weapon_id = "weapon:one"
    mod_ids = ["mod:magazine", "mod:barrel", "mod:armature"]
    trait_id = "trait:one"
    augment_id = "augment:concept"
    augment_implementation_id = "augment:implementation"
    item_id = "item:one"
    major_item_id = "item:major"
    augment_icon = {
        "height": 64,
        "path": "icons/augment-implementation.png",
        "pixelFormat": "PF_DXT5",
        "sha256": "sha256:" + "c" * 64,
        "width": 64,
    }

    candidate_records = [
        {
            "characterClassPackagePath": "class:one",
            "chipEntitlements": [{"perkId": perk_id}],
            "id": kit_id,
            "kind": "kit",
            "packagePath": kit_id,
            "weaponSlots": [
                {
                    "defaultWeaponId": weapon_id,
                    "index": 0,
                    "slotType": "primary",
                    "weaponSubtype": "any",
                    "weaponType": "rifle",
                }
            ],
        },
        {"id": ability_id, "kind": "perk"},
        {
            "chipVisual": {"family": "core", "status": "resolved"},
            "id": perk_id,
            "kind": "perk",
        },
        {"id": weapon_id, "kind": "weapon"},
        *({"id": mod_id, "kind": "mod"} for mod_id in mod_ids),
        {"id": trait_id, "kind": "trait"},
        {
            "compatibility": {
                "compatibleWeaponIds": [weapon_id],
                "status": "resolved",
            },
            "description": "Augment effect",
            "descriptionShort": "Augment summary",
            "displayName": "Rifle Augment",
            "flavorText": "Augment flavor",
            "icon": deepcopy(augment_icon),
            "id": augment_implementation_id,
            "kind": "augment",
            "packagePath": augment_implementation_id,
        },
        {"id": item_id, "kind": "item"},
        {"id": major_item_id, "kind": "item"},
    ]

    component_categories = ("magazine", "barrel", "armature")
    component_slots = [
        {
            "compatibleIds": [mod_id],
            "displayName": category.title(),
            "displayNameSource": "derived-required-mod-tag",
            "index": index,
            "kind": "component",
            "requiredModTags": [f"Item.Attachment.{category.title()}"],
            "slotCategory": category,
            "slotCategoryDisplayName": category.title(),
        }
        for index, (mod_id, category) in enumerate(
            zip(mod_ids, component_categories, strict=True)
        )
    ]
    trait_slot = {
        "compatibleIds": [trait_id],
        "displayName": "Trait",
        "displayNameSource": "derived-slot-kind",
        "index": 3,
        "kind": "trait",
        "requiredModTags": ["Item.Attachment.Mod"],
        "slotCategory": "trait",
        "slotCategoryDisplayName": "Trait",
    }
    augment_slot = {
        "compatibleIds": [augment_implementation_id],
        "displayName": "Augment",
        "displayNameSource": "derived-slot-kind",
        "index": 4,
        "kind": "augment",
        "requiredModTags": ["Item.Attachment.Overclock"],
        "slotCategory": "augment",
        "slotCategoryDisplayName": "Augment",
    }

    weapon_compatibility = {
        "augmentSlot": augment_slot,
        "compatibleAugmentIds": [augment_implementation_id],
        "compatibleModIds": list(mod_ids),
        "compatibleTraitIds": [trait_id],
        "componentSlots": component_slots,
        "collectionCategory": "rifle",
        "kitIgnoreTags": [],
        "kitTags": [],
        "status": "resolved",
        "traitSlot": trait_slot,
        "weaponRole": "primary",
        "weaponSubType": "automatic",
    }
    records: list[dict[str, object]] = [
        {
            "displayName": "One",
            "id": kit_id,
            "kind": "kit",
            "abilitySlots": [
                {
                    "role": "primary",
                    "selectableAbilityIds": [ability_id],
                }
            ],
            "selectableAbilityIdsByRole": {
                "passive": [],
                "primary": [ability_id],
                "secondary": [],
            },
            "selectablePerkIds": [perk_id],
            "weaponSlots": [
                {
                    "compatibleWeaponIds": [weapon_id],
                    "defaultWeaponId": weapon_id,
                    "index": 0,
                    "slotType": "primary",
                    "weaponSubtype": "any",
                    "weaponType": "rifle",
                }
            ],
        },
        {
            "description": "Primary ability",
            "displayName": "Primary",
            "id": ability_id,
            "kind": "ability",
            "availableToKitIds": [kit_id],
            "rendering": {"status": "slot-controlled"},
            "role": "primary",
        },
        {
            "chipVisual": {"family": "core", "status": "resolved"},
            "description": "Core perk",
            "displayName": "Core",
            "grid": valid_grid(),
            "id": perk_id,
            "kind": "perk",
            "perkType": "core",
            "availableToKitIds": [kit_id],
            "rendering": {
                "chipBodyByFootprint": [
                    {
                        "footprint": {"height": height, "width": width},
                        "height": 64,
                        "path": f"grid-assets/textures/core-{width}x{height}.png",
                        "pixelFormat": "PF_DXT5",
                        "sha256": "sha256:" + str(width + height) * 64,
                        "width": 64,
                    }
                    for width, height in ((1, 2), (2, 1))
                ],
                "status": "resolved",
            },
            "selectionSources": ["class-entitlement"],
        },
        {
            "compatibility": weapon_compatibility,
            "componentSlots": deepcopy(component_slots),
            "description": "Weapon",
            "displayName": "Weapon",
            "icon": {
                "height": 256,
                "path": "icons/weapon.png",
                "pixelFormat": "PF_DXT5",
                "sha256": "sha256:" + "1" * 64,
                "width": 512,
            },
            "id": weapon_id,
            "kind": "weapon",
        },
        *(
            {
                "compatibility": {
                    "compatibleWeaponIds": [weapon_id],
                    "status": "resolved",
                },
                "authoredDescription": f"Mod {index}",
                "description": f"Mod {index}",
                "displayName": f"Mod {index}",
                "id": mod_id,
                "kind": "mod",
            }
            for index, mod_id in enumerate(mod_ids)
        ),
        {
            "compatibility": {
                "compatibleWeaponIds": [weapon_id],
                "status": "resolved",
            },
            "authoredDescription": "Trait",
            "description": "Trait",
            "displayName": "Trait",
            "id": trait_id,
            "kind": "trait",
        },
        {
            "availability": {"purchasable": True},
            "collectionCategory": "AugmentPacks",
            "collectionConceptId": augment_id,
            "compatibleWeaponIds": [weapon_id],
            "description": (
                "Augment effect\r\n\r\nAugment flavor\r\n\r\nAugment summary"
            ),
            "descriptionPanel": {
                "description": "Augment effect",
                "descriptionSecondary": "Augment flavor",
                "descriptionUpper": "Augment summary",
            },
            "displayName": "Rifle Augment",
            "icon": deepcopy(augment_icon),
            "id": augment_implementation_id,
            "kind": "augment",
            "packagePath": augment_implementation_id,
        },
        {
            "description": "Item",
            "displayName": "Item",
            "id": item_id,
            "itemTier": "minor",
            "kind": "item",
            "availableToKitIds": [kit_id],
        },
        {
            "description": "Major item",
            "displayName": "Major Item Choice",
            "id": major_item_id,
            "itemTier": "major",
            "kind": "item",
            "availableToKitIds": [kit_id],
        },
    ]
    for index, record in enumerate(records):
        record.setdefault(
            "icon",
            {
                "height": 64,
                "path": f"icons/fixture-{index}.png",
                "pixelFormat": "PF_DXT5",
                "sha256": "sha256:" + "a" * 64,
                "width": 64,
            },
        )
    candidate_by_id = {record["id"]: record for record in candidate_records}
    for record in records:
        if record["kind"] == "augment":
            continue
        source = candidate_by_id[record["id"]]
        for field in ("displayName", "description", "conditionalDescriptions"):
            if field in record:
                source[field] = deepcopy(record[field])

    placeable_cells = [
        {"column": column, "label": f"{chr(ord('A') + column)}1", "row": 0}
        for column in range(10)
    ] + [
        {
            "column": column,
            "label": f"{chr(ord('A') + column)}{row + 1}",
            "row": row,
        }
        for row in range(1, 5)
        for column in range(1, 9)
    ]

    def anchor(role: str, index: int) -> dict[str, object]:
        column, row, width, height = {
            "primary": (0, 1, 1, 4),
            "secondary": (9, 1, 1, 4),
            "passive": (3, 5, 4, 1),
        }[role]
        return {
            "cells": [
                {
                    "column": column + dx,
                    "label": f"{chr(ord('A') + column + dx)}{row + dy + 1}",
                    "row": row + dy,
                }
                for dy in range(height)
                for dx in range(width)
            ],
            "column": column,
            "role": role,
            "row": row,
            "rendering": {
                "chipBody": {
                    "height": 64,
                    "path": f"grid-assets/textures/{role}.png",
                    "pixelFormat": "PF_B8G8R8A8",
                    "sha256": "sha256:" + str(index) * 64,
                    "width": 64,
                },
                "status": "resolved",
            },
            "selectableAbilityIds": [ability_id] if role == "primary" else [],
        }

    planner_catalogue = {
        "coverage": {
            "augmentImplementations": 1,
            "augmentPacks": 1,
            "collectionAugmentImplementations": 1,
            "collectionMembersByKind": {
                "augment": 1,
                "item": 2,
                "mod": 3,
                "trait": 1,
                "weapon": 1,
            },
            "records": len(records),
            "recordsByKind": {
                "ability": 1,
                "augment": 1,
                "item": 2,
                "kit": 1,
                "mod": 3,
                "perk": 1,
                "trait": 1,
                "weapon": 1,
            },
            "recordsMissingDescription": 1,
            "recordsMissingDisplayName": 0,
            "recordsWithConditionalDescriptions": 0,
            "recordsWithStaticStatLines": 0,
            "itemSlots": 2,
        },
        "extractor": {"name": "afe2-catalogue", "version": "test"},
        "game": {"buildId": "fixture-build", "steamAppId": "3448650"},
        "itemSlots": [
            {
                "compatibleItemIds": [item_id],
                "displayName": "Minor Item",
                "displayNameSource": "derived-inventory-type-tag",
                "evidence": {"source": "serialized-uasset"},
                "index": 2,
                "inventoryTypeTag": "Ability.Consumable.InventoryType.Minor",
                "itemTier": "minor",
                "requiredModTags": [
                    "Ability.Consumable.InventoryType.Minor"
                ],
                "slotTags": ["Slot.Consumable.Custom"],
            },
            {
                "compatibleItemIds": [major_item_id],
                "displayName": "Major Item",
                "displayNameSource": "derived-inventory-type-tag",
                "evidence": {"source": "serialized-uasset"},
                "index": 4,
                "inventoryTypeTag": "Ability.Consumable.InventoryType.Major",
                "itemTier": "major",
                "requiredModTags": [
                    "Ability.Consumable.InventoryType.Major"
                ],
                "slotTags": ["Slot.Consumable.Custom"],
            },
        ],
        "perkGrid": {
            "kitLayouts": [
                {
                    "anchors": [
                        anchor("primary", 2),
                        anchor("secondary", 3),
                        anchor("passive", 4),
                    ],
                    "baseBoard": {"columns": 10, "rows": 5},
                    "kitId": kit_id,
                    "placeableCellCount": 42,
                    "placeableCells": placeable_cells,
                    "renderExtent": {"columns": 10, "rows": 6},
                }
            ],
            "placementRules": {
                "modifier": {
                    "adjacency": "orthogonal-only",
                    "adjacencyOffsets": [
                        {"column": -1, "row": 0},
                        {"column": 0, "row": -1},
                        {"column": 0, "row": 1},
                        {"column": 1, "row": 0},
                    ],
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
        },
        "records": records,
        "schemaVersion": 1,
        "sourceCoverage": {
            "kitMembership": {
                "coverage": {"mappedKits": 1, "unresolvedReferences": 0},
                "status": "complete",
            },
            "progressionPerks": {
                "coverage": {"uniquePerks": 0, "unresolvedReferences": 0},
                "status": "complete",
            },
        },
        "sourceFingerprint": fingerprint,
        "textContract": {
            "attachmentDescriptionComposition": {
                "authoredDescriptionField": "authoredDescription",
                "conditionalDescriptionField": "conditionalDescriptions",
                "conditionalStatIndent": "  ",
                "descriptionField": "description",
                "lineSeparator": "\r\n",
                "order": [
                    "authoredDescription",
                    "staticStatLines",
                    "conditionalDescriptions",
                ],
                "sectionSeparator": "\r\n\r\n",
                "staticStatField": "staticStatLines",
            },
            "augmentDescriptionComposition": {
                "componentField": "descriptionPanel",
                "conditionalDescriptionField": "conditionalDescriptions",
                "conditionalStatIndent": "  ",
                "descriptionField": "description",
                "lineSeparator": "\r\n",
                "order": [
                    "descriptionPanel",
                    "staticStatLines",
                    "conditionalDescriptions",
                ],
                "panelOrder": [
                    "description",
                    "descriptionSecondary",
                    "descriptionUpper",
                ],
                "sectionSeparator": "\r\n\r\n",
                "staticStatField": "staticStatLines",
            },
            "conditionalDescriptionField": "conditionalDescriptions",
            "descriptionField": "description",
            "displayNameField": "displayName",
            "packagePathIsDisplayText": False,
            "richTextFormat": "unreal-rich-text-subset",
        },
    }
    return {
        "candidates": {
            "attributeMetadata": {
                "packagePath": "/Game/Design/AttributeMetaData/AttributeMetaData",
                "rows": [
                    {
                        "attribute": "GunGameplayAttributes.TimeToReload",
                        "displayName": "Reload Time",
                        "displayType": "Time",
                        "modifierOperation": "Divide",
                        "result": "LowerIsBetter",
                        "sortOrder": 13,
                    }
                ],
                "status": "parsed",
            },
            "records": candidate_records,
        },
        "collection_assets": {
            "categoryAudit": {
                "ignoredKeys": [],
                "includedKeys": ["AugmentPacks"],
                "observedKeys": ["AugmentPacks"],
                "unknownKeys": [],
            },
            "categories": [
                {
                    "entries": [
                        {
                            "availability": {"purchasable": True},
                            "id": augment_id,
                            "status": "resolved",
                            "terminalRecords": [
                                {
                                    "id": augment_implementation_id,
                                    "kind": "augment",
                                    "packagePath": augment_implementation_id,
                                }
                            ],
                        }
                    ],
                    "key": "AugmentPacks",
                }
            ],
            "conceptRecords": [
                {
                    "description": "Concept description",
                    "displayName": "Concept Augment",
                    "id": augment_id,
                    "kind": "augment",
                }
            ],
            "coverage": {
                "kitMembership": 1,
                "kitMembershipUnresolvedReferences": 0,
                "ignoredCategories": 0,
                "unknownCategories": 0,
                "uniqueTerminalRecords": 8,
            },
            "memberships": {
                weapon_id: [{"categoryKey": "Weapons"}],
                mod_ids[0]: [{"categoryKey": "Magazines"}],
                mod_ids[1]: [{"categoryKey": "Barrels"}],
                mod_ids[2]: [{"categoryKey": "Armature"}],
                trait_id: [{"categoryKey": "Traits"}],
                augment_implementation_id: [{"categoryKey": "AugmentPacks"}],
                item_id: [{"categoryKey": "Items"}],
                major_item_id: [{"categoryKey": "Items"}],
            },
            "kitMembership": {
                "coverage": {
                    "mappedKits": 1,
                    "unresolvedReferences": 0,
                },
                "entries": [
                    {
                        "characterClassPackagePath": "class:one",
                        "id": kit_id,
                        "kind": "kit",
                        "packagePath": kit_id,
                        "sources": [
                            {"sourceKind": "default-starting-rewards"}
                        ],
                    }
                ],
                "memberIds": [kit_id],
                "status": "complete",
                "unresolved": [],
            },
            "progressionPerks": {
                "coverage": {"uniquePerks": 0, "unresolvedReferences": 0},
                "entries": [],
                "memberIds": [],
                "status": "complete",
                "unresolved": [],
            },
            "schemaVersion": 1,
            "sourceFingerprint": fingerprint,
            "status": "complete",
            "unresolved": [],
        },
        "package_index": {
            "packages": [
                {"packagePath": record["id"]} for record in candidate_records
            ]
        },
        "planner_catalogue": planner_catalogue,
        "source_manifest": {
            "archives": [],
            "extractor": {"name": "afe2-catalogue", "version": "test"},
            "game": {"buildId": "fixture-build", "steamAppId": "3448650"},
            "sourceFingerprint": fingerprint,
        },
        "strict": False,
    }


def add_visible_planner_weapon(
    arguments: dict[str, object],
    *,
    weapon_id: str,
    collection_category: str,
    weapon_role: str,
    weapon_subtype: str,
    kit_tags: list[str] | None = None,
    kit_ignore_tags: list[str] | None = None,
) -> None:
    records = arguments["planner_catalogue"]["records"]
    template = next(record for record in records if record["kind"] == "weapon")
    weapon = deepcopy(template)
    weapon["id"] = weapon_id
    weapon["displayName"] = "Additional " + weapon_id.replace(":", " ").title()
    weapon["icon"]["path"] = f"icons/{weapon_id.replace(':', '-')}.png"
    compatibility = weapon["compatibility"]
    compatibility["collectionCategory"] = collection_category
    compatibility["kitIgnoreTags"] = list(kit_ignore_tags or [])
    compatibility["kitTags"] = list(kit_tags or [])
    compatibility["weaponRole"] = weapon_role
    compatibility["weaponSubType"] = weapon_subtype
    records.append(weapon)
    arguments["planner_catalogue"]["coverage"]["records"] += 1
    arguments["planner_catalogue"]["coverage"]["recordsByKind"]["weapon"] += 1
    arguments["planner_catalogue"]["coverage"]["collectionMembersByKind"][
        "weapon"
    ] += 1

    arguments["candidates"]["records"].append(
        {
            "description": weapon["description"],
            "displayName": weapon["displayName"],
            "id": weapon_id,
            "kind": "weapon",
        }
    )
    arguments["package_index"]["packages"].append({"packagePath": weapon_id})
    arguments["collection_assets"]["memberships"][weapon_id] = [
        {"categoryKey": "Weapons"}
    ]
    arguments["collection_assets"]["coverage"]["uniqueTerminalRecords"] += 1

    for record in records:
        if record.get("kind") in {"mod", "trait"}:
            record["compatibility"]["compatibleWeaponIds"].append(weapon_id)
        elif record.get("kind") == "augment":
            record["compatibleWeaponIds"].append(weapon_id)
            record["compatibleWeaponIds"].sort()
            source = next(
                candidate
                for candidate in arguments["candidates"]["records"]
                if candidate["id"] == record["id"]
            )
            source["compatibility"]["compatibleWeaponIds"].append(weapon_id)
            source["compatibility"]["compatibleWeaponIds"].sort()


class ValidationTests(unittest.TestCase):
    def test_accepts_complete_planner_contract(self) -> None:
        result = validate_outputs(**valid_planner_arguments())

        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["errors"], [])

    def test_flat_augment_projection_uses_only_visible_terminal_records(self) -> None:
        arguments = valid_planner_arguments()
        hidden_id = "augment:hidden-implementation"
        hidden = {
            "compatibility": {
                "compatibleWeaponIds": ["weapon:hidden"],
                "status": "resolved",
            },
            "descriptionShort": "Hidden augment summary",
            "displayName": "Hidden Augment",
            "icon": {
                "height": 64,
                "path": "icons/hidden-augment.png",
                "pixelFormat": "PF_DXT5",
                "sha256": "sha256:" + "d" * 64,
                "width": 64,
            },
            "id": hidden_id,
            "kind": "augment",
            "packagePath": hidden_id,
        }
        arguments["candidates"]["records"].append(hidden)
        arguments["package_index"]["packages"].append(
            {"packagePath": hidden_id}
        )
        arguments["collection_assets"]["categories"][0]["entries"][0][
            "terminalRecords"
        ].append(
            {
                "id": hidden_id,
                "kind": "augment",
                "packagePath": hidden_id,
            }
        )
        arguments["collection_assets"]["memberships"][hidden_id] = [
            {"categoryKey": "AugmentPacks"}
        ]
        arguments["collection_assets"]["coverage"][
            "uniqueTerminalRecords"
        ] += 1
        arguments["planner_catalogue"]["coverage"][
            "collectionAugmentImplementations"
        ] += 1

        hidden_result = validate_outputs(**arguments)

        self.assertTrue(hidden_result["valid"], hidden_result["errors"])

        hidden["compatibility"]["compatibleWeaponIds"] = ["weapon:one"]
        visible_result = validate_outputs(**arguments)

        self.assertFalse(visible_result["valid"])
        projection = next(
            error
            for error in visible_result["errors"]
            if error["code"] == "planner-collection-projection-mismatch"
            and error.get("expectedKind") == "augment"
        )
        self.assertEqual(projection["missingIds"], [hidden_id])

    def test_requires_exact_terminal_augment_fields_and_relationships(self) -> None:
        def planner_augment(arguments: dict[str, object]) -> dict[str, object]:
            return next(
                record
                for record in arguments["planner_catalogue"]["records"]
                if record["kind"] == "augment"
            )

        def source_augment(arguments: dict[str, object]) -> dict[str, object]:
            return next(
                record
                for record in arguments["candidates"]["records"]
                if record["kind"] == "augment"
            )

        cases = (
            (
                "terminal-name",
                lambda arguments: planner_augment(arguments).update(
                    {"displayName": "Concept Augment"}
                ),
                "planner-record-text-source-mismatch",
            ),
            (
                "terminal-icon",
                lambda arguments: planner_augment(arguments)["icon"].update(
                    {"sha256": "sha256:" + "e" * 64}
                ),
                "planner-record-text-source-mismatch",
            ),
            (
                "terminal-conditional-description",
                lambda arguments: source_augment(arguments).update(
                    {"conditionalDescriptions": valid_conditional_descriptions()}
                ),
                "planner-conditional-description-source-mismatch",
            ),
            (
                "collection-concept",
                lambda arguments: planner_augment(arguments).update(
                    {"collectionConceptId": "augment:wrong-concept"}
                ),
                "planner-augment-collection-concept-mismatch",
            ),
            (
                "collection-availability",
                lambda arguments: planner_augment(arguments).update(
                    {"availability": {"purchasable": False}}
                ),
                "planner-augment-availability-source-mismatch",
            ),
            (
                "description-panel",
                lambda arguments: planner_augment(arguments)[
                    "descriptionPanel"
                ].update({"descriptionSecondary": "Wrong flavor"}),
                "planner-augment-description-panel-mismatch",
            ),
            (
                "flattened-description",
                lambda arguments: planner_augment(arguments).update(
                    {"description": "Augment effect Augment flavor Augment summary"}
                ),
                "planner-augment-description-composition-mismatch",
            ),
            (
                "compatible-weapons",
                lambda arguments: planner_augment(arguments).update(
                    {"compatibleWeaponIds": []}
                ),
                "planner-augment-compatibility-source-mismatch",
            ),
        )
        for label, mutate, expected_code in cases:
            with self.subTest(label=label):
                arguments = valid_planner_arguments()
                mutate(arguments)

                result = validate_outputs(**arguments)

                self.assertFalse(result["valid"])
                self.assertIn(
                    expected_code,
                    {error["code"] for error in result["errors"]},
                )

    def test_augment_enrichment_is_recomputed_from_effect_evidence(self) -> None:
        arguments = valid_planner_arguments()
        source = source_record(arguments, "augment:implementation")
        planner = planner_record(arguments, "augment:implementation")
        static_lines = valid_static_stat_lines()
        conditional = valid_conditional_descriptions()
        source["effects"] = [valid_reload_speed_effect()]
        source["staticStatLines"] = deepcopy(static_lines)
        source["conditionalDescriptions"] = deepcopy(conditional)
        planner["staticStatLines"] = deepcopy(static_lines)
        planner["conditionalDescriptions"] = deepcopy(conditional)
        planner["description"] = (
            "Augment effect\r\n\r\n"
            "Augment flavor\r\n\r\n"
            "Augment summary\r\n\r\n"
            "+20.0% Reload Speed\r\n\r\n"
            "<Bold>On Taking Damage</>:\r\n"
            "  +25% Damage Resistance\r\n"
            "  Lasts <Bold>5 seconds</>."
        )
        arguments["planner_catalogue"]["coverage"].update(
            {
                "recordsWithConditionalDescriptions": 1,
                "recordsWithStaticStatLines": 1,
            }
        )

        result = validate_outputs(**arguments)

        self.assertTrue(result["valid"], result["errors"])

        self_consistent_but_wrong = deepcopy(arguments)
        for document in (
            source_record(self_consistent_but_wrong, "augment:implementation"),
            planner_record(self_consistent_but_wrong, "augment:implementation"),
        ):
            document["staticStatLines"][0].update(
                {
                    "displayText": "+999.0% Reload Speed",
                    "displayValue": "+999.0%",
                    "statValue": 999.0,
                }
            )
        planner_record(self_consistent_but_wrong, "augment:implementation")[
            "description"
        ] = planner["description"].replace("+20.0%", "+999.0%")

        wrong_result = validate_outputs(**self_consistent_but_wrong)

        self.assertIn(
            "planner-attachment-description-projection-mismatch",
            {error["code"] for error in wrong_result["errors"]},
        )
        self.assertIn(
            "planner-augment-description-composition-mismatch",
            {error["code"] for error in wrong_result["errors"]},
        )

    def test_requires_exact_augment_description_contract_and_coverage(self) -> None:
        baseline = valid_planner_arguments()
        baseline["planner_catalogue"]["textContract"][
            "augmentDescriptionComposition"
        ]["separator"] = "\n\n"

        contract_result = validate_outputs(**baseline)

        self.assertFalse(contract_result["valid"])
        self.assertIn(
            "invalid-planner-text-contract",
            {error["code"] for error in contract_result["errors"]},
        )

        for field, expected_code in (
            ("augmentImplementations", "planner-augment-coverage-mismatch"),
            ("augmentPacks", "planner-augment-coverage-mismatch"),
            (
                "collectionAugmentImplementations",
                "planner-augment-coverage-mismatch",
            ),
            (
                "collectionMembersByKind",
                "planner-collection-member-coverage-mismatch",
            ),
            ("recordsByKind", "planner-record-kind-coverage-mismatch"),
        ):
            with self.subTest(field=field):
                arguments = valid_planner_arguments()
                coverage = arguments["planner_catalogue"]["coverage"]
                if isinstance(coverage[field], dict):
                    coverage[field]["augment"] = 999
                else:
                    coverage[field] = 999

                result = validate_outputs(**arguments)

                self.assertFalse(result["valid"])
                self.assertIn(
                    expected_code,
                    {error["code"] for error in result["errors"]},
                )

    def test_requires_reciprocal_terminal_augment_weapon_slot(self) -> None:
        arguments = valid_planner_arguments()
        weapon = next(
            record
            for record in arguments["planner_catalogue"]["records"]
            if record["kind"] == "weapon"
        )
        weapon["compatibility"]["augmentSlot"]["compatibleIds"] = []
        weapon["compatibility"]["compatibleAugmentIds"] = []

        result = validate_outputs(**arguments)

        self.assertFalse(result["valid"])
        self.assertIn(
            "planner-compatibility-reciprocity-mismatch",
            {error["code"] for error in result["errors"]},
        )

    def test_semantic_publication_requires_planner_catalogue(self) -> None:
        arguments = valid_planner_arguments()
        arguments["planner_catalogue"] = None
        arguments["source_manifest"]["coverage"] = {"semanticAssets": {}}

        result = validate_outputs(**arguments)

        self.assertFalse(result["valid"])
        self.assertIn(
            "missing-planner-catalogue",
            {error["code"] for error in result["errors"]},
        )

    def test_unknown_collection_category_warns_and_strict_mode_rejects(self) -> None:
        arguments = valid_planner_arguments()
        audit = arguments["collection_assets"]["categoryAudit"]
        audit["observedKeys"].append("Experimental Attachments")
        audit["unknownKeys"].append("Experimental Attachments")
        arguments["collection_assets"]["coverage"]["unknownCategories"] = 1

        result = validate_outputs(**arguments)

        self.assertTrue(result["valid"], result["errors"])
        warning = next(
            warning
            for warning in result["warnings"]
            if warning["code"] == "collection-unknown-category-keys"
        )
        self.assertEqual(warning["keys"], ["Experimental Attachments"])

        arguments["strict"] = True
        strict_result = validate_outputs(**arguments)
        self.assertFalse(strict_result["valid"])
        self.assertTrue(
            any(
                error["code"] == "strict-warning"
                and error["warning"]["code"] == "collection-unknown-category-keys"
                for error in strict_result["errors"]
            )
        )

    def test_requires_frontend_metadata_item_slots_and_slot_labels(self) -> None:
        for mutation, expected_code in (
            (
                lambda arguments: arguments["planner_catalogue"].pop("game"),
                "planner-catalogue-game-metadata-mismatch",
            ),
            (
                lambda arguments: arguments["planner_catalogue"]["itemSlots"][0].update(
                    {"compatibleItemIds": []}
                ),
                "invalid-planner-item-slots",
            ),
            (
                lambda arguments: (
                    arguments["planner_catalogue"]["itemSlots"].append(
                        {
                            **deepcopy(
                                arguments["planner_catalogue"]["itemSlots"][0]
                            ),
                            "index": 99,
                        }
                    ),
                    arguments["planner_catalogue"]["coverage"].update(
                        {"itemSlots": 3}
                    ),
                ),
                "invalid-planner-item-slots",
            ),
            (
                lambda arguments: next(
                    record
                    for record in arguments["planner_catalogue"]["records"]
                    if record["kind"] == "weapon"
                )["componentSlots"][0].pop("slotCategory"),
                "planner-weapons-invalid-slot-layout",
            ),
        ):
            with self.subTest(expected_code=expected_code):
                arguments = valid_planner_arguments()
                mutation(arguments)
                result = validate_outputs(**arguments)
                self.assertFalse(result["valid"])
                self.assertIn(
                    expected_code,
                    {error["code"] for error in result["errors"]},
                )

    def test_requires_human_authored_text_and_exact_source_projection(self) -> None:
        arguments = valid_planner_arguments()
        for document in (
            planner_record(arguments, "weapon:one"),
            source_record(arguments, "weapon:one"),
        ):
            document["displayName"] = "/Game/UI/T_NotHuman"
        result = validate_outputs(**arguments)
        self.assertIn(
            "planner-records-invalid-ui-text",
            {error["code"] for error in result["errors"]},
        )

        arguments = valid_planner_arguments()
        planner_record(arguments, "weapon:one")["displayName"] = "Different Weapon"
        result = validate_outputs(**arguments)
        self.assertIn(
            "planner-record-text-source-mismatch",
            {error["code"] for error in result["errors"]},
        )

        arguments = valid_planner_arguments()
        planner_record(arguments, "weapon:one").pop("description")
        result = validate_outputs(**arguments)
        self.assertIn(
            "planner-record-text-source-mismatch",
            {error["code"] for error in result["errors"]},
        )

        arguments = valid_planner_arguments()
        conditional = valid_conditional_descriptions()
        conditional[0]["statLines"][0]["statText"] = "/Game/UI/T_NotHuman"
        for document in (
            planner_record(arguments, "mod:magazine"),
            source_record(arguments, "mod:magazine"),
        ):
            document["conditionalDescriptions"] = deepcopy(conditional)
        arguments["planner_catalogue"]["coverage"][
            "recordsWithConditionalDescriptions"
        ] = 1
        result = validate_outputs(**arguments)
        self.assertIn(
            "invalid-planner-conditional-descriptions",
            {error["code"] for error in result["errors"]},
        )

    def test_conditional_descriptions_are_validated_and_count_as_ui_copy(self) -> None:
        arguments = valid_planner_arguments()
        planner_mod = next(
            record
            for record in arguments["planner_catalogue"]["records"]
            if record["id"] == "mod:magazine"
        )
        source_mod = next(
            record
            for record in arguments["candidates"]["records"]
            if record["id"] == "mod:magazine"
        )
        authored = valid_conditional_descriptions()
        planner_mod["conditionalDescriptions"] = deepcopy(authored)
        source_mod["conditionalDescriptions"] = deepcopy(authored)
        source_mod["description"] = None
        planner_mod["authoredDescription"] = None
        planner_mod["description"] = (
            "<Bold>On Taking Damage</>:\r\n"
            "  +25% Damage Resistance\r\n"
            "  Lasts <Bold>5 seconds</>."
        )
        arguments["planner_catalogue"]["coverage"][
            "recordsWithConditionalDescriptions"
        ] = 1

        result = validate_outputs(**arguments)

        self.assertTrue(result["valid"], result["errors"])
        missing_warning_ids = {
            record_id
            for warning in result["warnings"]
            if warning["code"] == "planner-records-missing-description"
            for record_id in warning["ids"]
        }
        self.assertNotIn("mod:magazine", missing_warning_ids)

    def test_static_stat_lines_are_validated_and_count_as_ui_copy(self) -> None:
        arguments = valid_planner_arguments()
        planner_mod = planner_record(arguments, "mod:magazine")
        source_mod = source_record(arguments, "mod:magazine")
        lines = valid_static_stat_lines()
        source_mod["description"] = None
        source_mod["effects"] = [valid_reload_speed_effect()]
        source_mod["staticStatLines"] = deepcopy(lines)
        planner_mod["authoredDescription"] = None
        planner_mod["description"] = "+20.0% Reload Speed"
        planner_mod["staticStatLines"] = deepcopy(lines)
        arguments["planner_catalogue"]["coverage"]["recordsWithStaticStatLines"] = 1

        result = validate_outputs(**arguments)

        self.assertTrue(result["valid"], result["errors"])
        missing_warning_ids = {
            record_id
            for warning in result["warnings"]
            if warning["code"] == "planner-records-missing-description"
            for record_id in warning["ids"]
        }
        self.assertNotIn("mod:magazine", missing_warning_ids)

        rewritten = deepcopy(arguments)
        planner_record(rewritten, "mod:magazine")["staticStatLines"][0][
            "statValue"
        ] = 16.666667
        rewritten_result = validate_outputs(**rewritten)
        self.assertIn(
            "planner-static-stat-line-source-mismatch",
            {error["code"] for error in rewritten_result["errors"]},
        )

        malformed = deepcopy(arguments)
        for document in (
            planner_record(malformed, "mod:magazine"),
            source_record(malformed, "mod:magazine"),
        ):
            document["staticStatLines"][0]["statValue"] = "20"
        malformed_result = validate_outputs(**malformed)
        self.assertIn(
            "invalid-planner-static-stat-lines",
            {error["code"] for error in malformed_result["errors"]},
        )

        bad_description = deepcopy(arguments)
        planner_record(bad_description, "mod:magazine")["description"] = (
            "-16.7% Reload Time"
        )
        bad_description_result = validate_outputs(**bad_description)
        self.assertIn(
            "planner-attachment-description-composition-mismatch",
            {error["code"] for error in bad_description_result["errors"]},
        )

        self_consistent_but_wrong = deepcopy(arguments)
        for document in (
            planner_record(self_consistent_but_wrong, "mod:magazine"),
            source_record(self_consistent_but_wrong, "mod:magazine"),
        ):
            document["staticStatLines"][0].update(
                {
                    "displayText": "+999.0% Reload Speed",
                    "displayValue": "+999.0%",
                    "statValue": 999.0,
                }
            )
        planner_record(self_consistent_but_wrong, "mod:magazine")[
            "description"
        ] = "+999.0% Reload Speed"

        wrong_result = validate_outputs(**self_consistent_but_wrong)

        self.assertIn(
            "planner-attachment-description-projection-mismatch",
            {error["code"] for error in wrong_result["errors"]},
        )

    def test_rejects_malformed_or_unprojected_conditional_descriptions(self) -> None:
        malformed = valid_planner_arguments()
        planner_mod = next(
            record
            for record in malformed["planner_catalogue"]["records"]
            if record["id"] == "mod:magazine"
        )
        source_mod = next(
            record
            for record in malformed["candidates"]["records"]
            if record["id"] == "mod:magazine"
        )
        authored = valid_conditional_descriptions()
        authored[0]["statLines"][0]["statValue"] = "25"
        planner_mod["conditionalDescriptions"] = deepcopy(authored)
        source_mod["conditionalDescriptions"] = deepcopy(authored)
        del planner_mod["description"]
        malformed["planner_catalogue"]["coverage"].update(
            {
                "recordsMissingDescription": 2,
                "recordsWithConditionalDescriptions": 0,
            }
        )

        malformed_result = validate_outputs(**malformed)

        self.assertFalse(malformed_result["valid"])
        self.assertIn(
            "invalid-planner-conditional-descriptions",
            {error["code"] for error in malformed_result["errors"]},
        )

        unprojected = valid_planner_arguments()
        source_mod = next(
            record
            for record in unprojected["candidates"]["records"]
            if record["id"] == "mod:magazine"
        )
        source_mod["conditionalDescriptions"] = valid_conditional_descriptions()

        unprojected_result = validate_outputs(**unprojected)

        self.assertFalse(unprojected_result["valid"])
        self.assertIn(
            "planner-conditional-description-source-mismatch",
            {error["code"] for error in unprojected_result["errors"]},
        )

        unresolved = valid_planner_arguments()
        source_mod = next(
            record
            for record in unresolved["candidates"]["records"]
            if record["id"] == "mod:magazine"
        )
        source_mod["conditionalDescriptionsResolution"] = {
            "reason": "malformed fixture",
            "status": "unresolved",
        }

        unresolved_result = validate_outputs(**unresolved)

        self.assertFalse(unresolved_result["valid"])
        self.assertIn(
            "planner-conditional-descriptions-unresolved",
            {error["code"] for error in unresolved_result["errors"]},
        )

    def test_surfaces_incomplete_progression_without_discarding_proven_members(self) -> None:
        arguments = valid_planner_arguments()
        progression = arguments["collection_assets"]["progressionPerks"]
        progression["status"] = "incomplete"
        progression["unresolved"] = [
            {"packagePath": "/Game/Missing", "reason": "reward-table-asset-unresolved"}
        ]
        progression["coverage"]["unresolvedReferences"] = 1
        arguments["planner_catalogue"]["sourceCoverage"]["progressionPerks"] = {
            "coverage": deepcopy(progression["coverage"]),
            "status": "incomplete",
        }

        result = validate_outputs(**arguments)

        self.assertTrue(result["valid"], result["errors"])
        self.assertIn(
            "collection-progression-incomplete",
            {warning["code"] for warning in result["warnings"]},
        )

    def test_surfaces_incomplete_kit_membership_without_promoting_unproven_kits(self) -> None:
        arguments = valid_planner_arguments()
        membership = arguments["collection_assets"]["kitMembership"]
        membership["status"] = "incomplete"
        membership["unresolved"] = [
            {
                "packagePath": "/Game/Classes/Player_Future",
                "reason": "authorized-character-class-had-no-kit",
            }
        ]
        membership["coverage"]["unresolvedReferences"] = 1
        arguments["collection_assets"]["coverage"][
            "kitMembershipUnresolvedReferences"
        ] = 1
        arguments["planner_catalogue"]["sourceCoverage"]["kitMembership"] = {
            "coverage": deepcopy(membership["coverage"]),
            "status": "incomplete",
        }

        result = validate_outputs(**arguments)

        self.assertTrue(result["valid"], result["errors"])
        self.assertIn(
            "collection-kit-membership-incomplete",
            {warning["code"] for warning in result["warnings"]},
        )

    def test_rejects_complete_but_empty_kit_membership(self) -> None:
        arguments = valid_planner_arguments()
        membership = arguments["collection_assets"]["kitMembership"]
        membership["memberIds"] = []
        membership["entries"] = []
        membership["coverage"]["mappedKits"] = 0
        arguments["collection_assets"]["coverage"]["kitMembership"] = 0

        result = validate_outputs(**arguments)

        self.assertFalse(result["valid"])
        self.assertIn(
            "invalid-collection-kit-members",
            {error["code"] for error in result["errors"]},
        )
        self.assertIn(
            "collection-kit-starting-source-missing",
            {error["code"] for error in result["errors"]},
        )

    def test_rejects_planner_kit_outside_canonical_membership(self) -> None:
        arguments = valid_planner_arguments()
        membership = arguments["collection_assets"]["kitMembership"]
        membership["memberIds"] = ["kit:other"]
        membership["entries"][0]["id"] = "kit:other"
        membership["entries"][0]["packagePath"] = "kit:other"
        membership["coverage"]["mappedKits"] = 1
        arguments["candidates"]["records"].append(
            {
                "characterClassPackagePath": "class:one",
                "id": "kit:other",
                "kind": "kit",
                "packagePath": "kit:other",
            }
        )
        arguments["package_index"]["packages"].append(
            {"packagePath": "kit:other"}
        )

        result = validate_outputs(**arguments)

        self.assertFalse(result["valid"])
        self.assertIn(
            "planner-kit-membership-projection-mismatch",
            {error["code"] for error in result["errors"]},
        )

    def test_requires_every_progression_perk_and_its_selection_source(self) -> None:
        arguments = valid_planner_arguments()
        progression = arguments["collection_assets"]["progressionPerks"]
        progression["memberIds"] = ["perk:core"]
        progression["entries"] = [
            {
                "id": "perk:core",
                "kind": "perk",
                "packagePath": "perk:core",
                "sources": [{"unlockCategory": "Mission"}],
            }
        ]
        progression["coverage"]["uniquePerks"] = 1
        arguments["planner_catalogue"]["sourceCoverage"]["progressionPerks"] = {
            "coverage": deepcopy(progression["coverage"]),
            "status": "complete",
        }
        core = next(
            record
            for record in arguments["planner_catalogue"]["records"]
            if record["id"] == "perk:core"
        )
        core["selectionSources"].append("progression-unlock")
        self.assertTrue(validate_outputs(**arguments)["valid"])

        core["selectionSources"].remove("progression-unlock")
        result = validate_outputs(**arguments)

        self.assertFalse(result["valid"])
        self.assertIn(
            "planner-progression-perk-source-mismatch",
            {error["code"] for error in result["errors"]},
        )

    def test_rejects_non_42_grid_and_unresolved_anchor_rendering(self) -> None:
        arguments = valid_planner_arguments()
        layout = arguments["planner_catalogue"]["perkGrid"]["kitLayouts"][0]
        layout["placeableCells"].pop()
        layout["placeableCellCount"] = 41
        del layout["anchors"][0]["rendering"]["chipBody"]["sha256"]

        result = validate_outputs(**arguments)

        self.assertFalse(result["valid"])
        self.assertEqual(
            {error["code"] for error in result["errors"]},
            {
                "invalid-planner-kit-grid",
                "planner-ability-anchors-unresolved-render",
            },
        )

    def test_requires_exact_decoded_perk_render_bindings(self) -> None:
        baseline = valid_planner_arguments()

        for label, mutate in (
            (
                "empty",
                lambda bindings: bindings.clear(),
            ),
            (
                "missing-metadata",
                lambda bindings: bindings[0].pop("pixelFormat"),
            ),
            (
                "wrong-footprint",
                lambda bindings: bindings[0]["footprint"].update({"width": 99}),
            ),
            (
                "duplicate-footprint",
                lambda bindings: bindings.append(deepcopy(bindings[0])),
            ),
        ):
            with self.subTest(label=label):
                arguments = deepcopy(baseline)
                perk = next(
                    record
                    for record in arguments["planner_catalogue"]["records"]
                    if record["id"] == "perk:core"
                )
                mutate(perk["rendering"]["chipBodyByFootprint"])

                result = validate_outputs(**arguments)

                self.assertFalse(result["valid"])
                self.assertIn(
                    "planner-perk-render-bindings-invalid",
                    {error["code"] for error in result["errors"]},
                )

    def test_requires_a_grid_layout_for_every_visible_kit(self) -> None:
        arguments = valid_planner_arguments()
        arguments["planner_catalogue"]["perkGrid"]["kitLayouts"] = []

        result = validate_outputs(**arguments)

        self.assertFalse(result["valid"])
        self.assertIn(
            "planner-kit-grid-coverage-mismatch",
            {error["code"] for error in result["errors"]},
        )

    def test_rejects_shifted_placeable_cells_and_missing_anchor_contract(self) -> None:
        arguments = valid_planner_arguments()
        layout = arguments["planner_catalogue"]["perkGrid"]["kitLayouts"][0]
        for cell in layout["placeableCells"]:
            cell["column"] += 100
            cell["row"] += 100
        layout["anchors"] = []

        result = validate_outputs(**arguments)

        self.assertFalse(result["valid"])
        self.assertEqual(
            {error["code"] for error in result["errors"]},
            {
                "invalid-planner-ability-anchor-contract",
                "invalid-planner-kit-grid",
            },
        )

    def test_requires_decoded_icon_for_every_planner_record_kind(self) -> None:
        baseline = valid_planner_arguments()
        records_by_kind = {
            record["kind"]: record
            for record in baseline["planner_catalogue"]["records"]
        }

        for kind, record in records_by_kind.items():
            with self.subTest(kind=kind):
                arguments = deepcopy(baseline)
                broken = next(
                    candidate
                    for candidate in arguments["planner_catalogue"]["records"]
                    if candidate["id"] == record["id"]
                )
                broken["icon"] = {"path": "/absolute/or/source-only.uasset"}

                result = validate_outputs(**arguments)

                self.assertFalse(result["valid"])
                error = next(
                    error
                    for error in result["errors"]
                    if error["code"] == "planner-records-missing-decoded-icon"
                )
                self.assertEqual(error["ids"], [record["id"]])

    def test_requires_major_or_minor_item_tier(self) -> None:
        arguments = valid_planner_arguments()
        records = {
            record["id"]: record
            for record in arguments["planner_catalogue"]["records"]
        }
        records["item:one"]["itemTier"] = "consumable"

        result = validate_outputs(**arguments)

        self.assertFalse(result["valid"])
        self.assertEqual(
            {error["code"] for error in result["errors"]},
            {"invalid-planner-item-slots", "planner-items-invalid-tier"},
        )

    def test_requires_exact_published_weapon_slot_layout(self) -> None:
        arguments = valid_planner_arguments()
        weapon = next(
            record
            for record in arguments["planner_catalogue"]["records"]
            if record.get("kind") == "weapon"
        )
        weapon["compatibility"]["componentSlots"].pop()
        weapon["componentSlots"].pop()

        result = validate_outputs(**arguments)

        self.assertFalse(result["valid"])
        self.assertEqual(
            {error["code"] for error in result["errors"]},
            {"planner-weapons-invalid-slot-layout"},
        )

    def test_requires_a_visible_choice_in_every_weapon_slot(self) -> None:
        arguments = valid_planner_arguments()
        records = {
            record["id"]: record
            for record in arguments["planner_catalogue"]["records"]
        }
        weapon = records["weapon:one"]
        weapon["compatibility"]["componentSlots"][0]["compatibleIds"] = []
        weapon["componentSlots"][0]["compatibleIds"] = []
        weapon["compatibility"]["compatibleModIds"].remove("mod:magazine")
        records["mod:magazine"]["compatibility"]["compatibleWeaponIds"] = []

        result = validate_outputs(**arguments)

        self.assertFalse(result["valid"])
        self.assertIn(
            "planner-weapons-invalid-slot-layout",
            {error["code"] for error in result["errors"]},
        )

    def test_requires_reciprocal_attachment_compatibility(self) -> None:
        arguments = valid_planner_arguments()
        mod = next(
            record
            for record in arguments["planner_catalogue"]["records"]
            if record["id"] == "mod:magazine"
        )
        mod["compatibility"]["compatibleWeaponIds"] = []

        result = validate_outputs(**arguments)

        self.assertFalse(result["valid"])
        self.assertIn(
            "planner-compatibility-reciprocity-mismatch",
            {error["code"] for error in result["errors"]},
        )

    def test_rejects_collection_kind_record_not_in_collection(self) -> None:
        arguments = valid_planner_arguments()
        hidden_id = "item:hidden"
        arguments["candidates"]["records"].append({"id": hidden_id, "kind": "item"})
        arguments["package_index"]["packages"].append({"packagePath": hidden_id})
        arguments["planner_catalogue"]["records"].append(
            {
                "availableToKitIds": ["kit:one"],
                "description": "Hidden",
                "displayName": "Hidden",
                "icon": {
                    "height": 64,
                    "path": "icons/hidden.png",
                    "pixelFormat": "PF_DXT5",
                    "sha256": "sha256:" + "b" * 64,
                    "width": 64,
                },
                "id": hidden_id,
                "itemTier": "minor",
                "kind": "item",
            }
        )
        arguments["planner_catalogue"]["coverage"]["records"] += 1

        result = validate_outputs(**arguments)

        self.assertFalse(result["valid"])
        self.assertIn(
            "planner-collection-projection-mismatch",
            {error["code"] for error in result["errors"]},
        )

    def test_rejects_unproven_wrench_source_and_modifier_without_dependencies(self) -> None:
        arguments = valid_planner_arguments()
        core = next(
            record
            for record in arguments["planner_catalogue"]["records"]
            if record["id"] == "perk:core"
        )
        core["selectionSources"].append("wrench-collection")
        core["chipVisual"] = {"family": "modifier", "status": "resolved"}
        core["perkType"] = "modifier"

        result = validate_outputs(**arguments)

        self.assertFalse(result["valid"])
        self.assertEqual(
            {
                "invalid-planner-perk-selection-source",
                "planner-modifier-missing-dependency",
            },
            {error["code"] for error in result["errors"]},
        )

    def test_requires_global_perk_availability_and_explicit_visual_type(self) -> None:
        duplicate_availability = valid_planner_arguments()
        core = next(
            record
            for record in duplicate_availability["planner_catalogue"]["records"]
            if record["id"] == "perk:core"
        )
        core["availableToKitIds"] = ["kit:one", "kit:one"]

        result = validate_outputs(**duplicate_availability)

        self.assertFalse(result["valid"])
        self.assertIn(
            "invalid-planner-perk-availability",
            {error["code"] for error in result["errors"]},
        )

        missing_type = valid_planner_arguments()
        core = next(
            record
            for record in missing_type["planner_catalogue"]["records"]
            if record["id"] == "perk:core"
        )
        del core["perkType"]

        result = validate_outputs(**missing_type)

        self.assertFalse(result["valid"])
        self.assertIn(
            "invalid-planner-perk-type",
            {error["code"] for error in result["errors"]},
        )

        mismatched_visual = valid_planner_arguments()
        core = next(
            record
            for record in mismatched_visual["planner_catalogue"]["records"]
            if record["id"] == "perk:core"
        )
        core["chipVisual"]["family"] = "modifier"

        result = validate_outputs(**mismatched_visual)

        self.assertFalse(result["valid"])
        self.assertIn(
            "planner-perk-type-visual-mismatch",
            {error["code"] for error in result["errors"]},
        )

    def test_rejects_compatibility_ids_outside_planner_projection(self) -> None:
        arguments = valid_planner_arguments()
        records = {
            record["id"]: record
            for record in arguments["planner_catalogue"]["records"]
        }
        compatibility = records["weapon:one"]["compatibility"]
        compatibility["componentSlots"][0]["compatibleIds"] = ["mod:hidden"]
        records["weapon:one"]["componentSlots"][0]["compatibleIds"] = [
            "mod:hidden"
        ]
        compatibility["compatibleModIds"] = [
            "mod:hidden",
            "mod:barrel",
            "mod:armature",
        ]
        compatibility["augmentSlot"]["compatibleIds"] = [
            "augment:hidden"
        ]
        compatibility["compatibleAugmentIds"] = ["augment:hidden"]
        records["mod:magazine"]["compatibility"]["compatibleWeaponIds"] = [
            "weapon:hidden"
        ]

        result = validate_outputs(**arguments)

        self.assertFalse(result["valid"])
        failures = [
            error
            for error in result["errors"]
            if error["code"] == "nonvisible-planner-compatibility-reference"
        ]
        self.assertTrue(failures)
        self.assertEqual(
            {
                target
                for failure in failures
                for target in failure.get("targets", [])
            },
            {"augment:hidden", "mod:hidden", "weapon:hidden"},
        )

    def test_requires_resolved_attachment_compatibility(self) -> None:
        arguments = valid_planner_arguments()
        trait = next(
            record
            for record in arguments["planner_catalogue"]["records"]
            if record.get("kind") == "trait"
        )
        trait["compatibility"]["status"] = "unresolved"

        result = validate_outputs(**arguments)

        self.assertFalse(result["valid"])
        self.assertIn(
            "planner-records-unresolved-compatibility",
            {error["code"] for error in result["errors"]},
        )

    def test_requires_valid_kit_weapon_slot_constraints_and_unique_indexes(self) -> None:
        baseline = valid_planner_arguments()
        for case in ("non-integer", "negative", "duplicate", "missing-role"):
            with self.subTest(case=case):
                arguments = deepcopy(baseline)
                kit = next(
                    record
                    for record in arguments["planner_catalogue"]["records"]
                    if record["kind"] == "kit"
                )
                if case == "non-integer":
                    kit["weaponSlots"][0]["index"] = "0"
                elif case == "negative":
                    kit["weaponSlots"][0]["index"] = -1
                elif case == "duplicate":
                    kit["weaponSlots"].append(deepcopy(kit["weaponSlots"][0]))
                else:
                    del kit["weaponSlots"][0]["slotType"]

                result = validate_outputs(**arguments)

                self.assertFalse(result["valid"])
                self.assertIn(
                    "invalid-planner-kit-weapon-slots",
                    {error["code"] for error in result["errors"]},
                )

    def test_requires_unique_nonempty_visible_kit_weapon_choices(self) -> None:
        baseline = valid_planner_arguments()
        for case, choices in (
            ("empty", []),
            ("duplicate", ["weapon:one", "weapon:one"]),
            ("nonvisible", ["weapon:hidden"]),
        ):
            with self.subTest(case=case):
                arguments = deepcopy(baseline)
                kit = next(
                    record
                    for record in arguments["planner_catalogue"]["records"]
                    if record["kind"] == "kit"
                )
                kit["weaponSlots"][0]["compatibleWeaponIds"] = choices

                result = validate_outputs(**arguments)

                self.assertFalse(result["valid"])
                self.assertIn(
                    "invalid-planner-kit-weapon-choices",
                    {error["code"] for error in result["errors"]},
                )

    def test_requires_kit_default_weapon_to_be_a_slot_choice(self) -> None:
        arguments = valid_planner_arguments()
        kit = next(
            record
            for record in arguments["planner_catalogue"]["records"]
            if record["kind"] == "kit"
        )
        kit["weaponSlots"][0]["defaultWeaponId"] = "weapon:hidden"

        result = validate_outputs(**arguments)

        self.assertFalse(result["valid"])
        self.assertIn(
            "planner-kit-default-weapon-mismatch",
            {error["code"] for error in result["errors"]},
        )

    def test_requires_exact_role_based_kit_weapon_choices(self) -> None:
        arguments = valid_planner_arguments()
        add_visible_planner_weapon(
            arguments,
            weapon_id="weapon:primary-cqw",
            collection_category="cqw",
            weapon_role="primary",
            weapon_subtype="shotgun",
        )
        kit = next(
            record
            for record in arguments["planner_catalogue"]["records"]
            if record["kind"] == "kit"
        )

        missing = validate_outputs(**arguments)

        self.assertFalse(missing["valid"])
        failure = next(
            error
            for error in missing["errors"]
            if error["code"] == "planner-kit-weapon-compatibility-mismatch"
        )
        self.assertEqual(failure["missingIds"], ["weapon:primary-cqw"])

        kit["weaponSlots"][0]["compatibleWeaponIds"].append(
            "weapon:primary-cqw"
        )
        complete = validate_outputs(**arguments)
        self.assertTrue(complete["valid"], complete["errors"])

    def test_rejects_extra_weapon_with_the_wrong_slot_role(self) -> None:
        arguments = valid_planner_arguments()
        add_visible_planner_weapon(
            arguments,
            weapon_id="weapon:sidearm",
            collection_category="handgun",
            weapon_role="sidearm",
            weapon_subtype="pistol",
        )
        kit = next(
            record
            for record in arguments["planner_catalogue"]["records"]
            if record["kind"] == "kit"
        )
        kit["weaponSlots"][0]["compatibleWeaponIds"].append("weapon:sidearm")

        result = validate_outputs(**arguments)

        self.assertFalse(result["valid"])
        failure = next(
            error
            for error in result["errors"]
            if error["code"] == "planner-kit-weapon-compatibility-mismatch"
        )
        self.assertEqual(failure["extraIds"], ["weapon:sidearm"])

    def test_signature_kit_tags_are_not_a_fully_unlocked_whitelist(self) -> None:
        arguments = valid_planner_arguments()
        source_kit = next(
            record
            for record in arguments["candidates"]["records"]
            if record["kind"] == "kit"
        )
        planner_kit = next(
            record
            for record in arguments["planner_catalogue"]["records"]
            if record["kind"] == "kit"
        )
        for kit in (source_kit, planner_kit):
            kit["weaponSlots"][0].update(
                {
                    "kitTag": "Kit.Test",
                    "slotType": "signature",
                }
            )
        weapon = next(
            record
            for record in arguments["planner_catalogue"]["records"]
            if record["kind"] == "weapon"
        )
        weapon["compatibility"].update(
            {
                "kitTags": ["Kit.Other"],
                "weaponRole": "signature",
            }
        )

        fully_unlocked = validate_outputs(**arguments)

        self.assertTrue(fully_unlocked["valid"], fully_unlocked["errors"])

        weapon["compatibility"]["kitIgnoreTags"] = ["Kit.Test"]
        ignored = validate_outputs(**arguments)

        self.assertFalse(ignored["valid"])
        self.assertIn(
            "planner-kit-weapon-compatibility-mismatch",
            {error["code"] for error in ignored["errors"]},
        )

    def test_any_role_slot_uses_subtype_before_weapon_type(self) -> None:
        arguments = valid_planner_arguments()
        source_kit = next(
            record
            for record in arguments["candidates"]["records"]
            if record["kind"] == "kit"
        )
        planner_kit = next(
            record
            for record in arguments["planner_catalogue"]["records"]
            if record["kind"] == "kit"
        )
        for kit in (source_kit, planner_kit):
            kit["weaponSlots"][0].update(
                {
                    "slotType": "any",
                    "weaponSubtype": "automatic",
                    "weaponType": "precision",
                }
            )

        result = validate_outputs(**arguments)

        self.assertTrue(result["valid"], result["errors"])

    def test_rejects_kit_weapon_constraints_changed_from_authored_slot(self) -> None:
        arguments = valid_planner_arguments()
        kit = next(
            record
            for record in arguments["planner_catalogue"]["records"]
            if record["kind"] == "kit"
        )
        kit["weaponSlots"][0]["weaponType"] = "precision"

        result = validate_outputs(**arguments)

        self.assertFalse(result["valid"])
        self.assertIn(
            "planner-kit-weapon-slot-source-mismatch",
            {error["code"] for error in result["errors"]},
        )

    def test_requires_weapon_loadout_role_type_subtype_and_tag_arrays(self) -> None:
        arguments = valid_planner_arguments()
        weapon = next(
            record
            for record in arguments["planner_catalogue"]["records"]
            if record["kind"] == "weapon"
        )
        del weapon["compatibility"]["kitIgnoreTags"]

        result = validate_outputs(**arguments)

        self.assertFalse(result["valid"])
        self.assertIn(
            "planner-weapons-invalid-loadout-compatibility",
            {error["code"] for error in result["errors"]},
        )

    def test_validates_grid_asset_manifest_and_texture_edges(self) -> None:
        fingerprint = "sha256:fixture"
        coverage = {
            "dedicatedTextures": 1,
            "sharedWidgetTextures": 0,
            "textureDependencies": 1,
            "texturesDecoded": 1,
            "texturesFailed": 0,
            "texturesRequested": 1,
            "widgetsFailed": 0,
            "widgetsParsed": 1,
            "widgetsRequested": 1,
        }
        texture = "/Game/UI/Textures/PerkGrid/T_UI_PerkGridBG"
        grid_assets = {
            "coverage": coverage,
            "failures": [],
            "layoutMetrics": {"reason": "fixture", "status": "unresolved"},
            "perkColorPalette": {"reason": "fixture", "status": "unresolved"},
            "renderingContract": {},
            "schemaVersion": 1,
            "sourceFingerprint": fingerprint,
            "textures": [
                {
                    "height": 16,
                    "packagePath": texture,
                    "path": "grid-assets/textures/background.png",
                    "pixelFormat": "PF_B8G8R8A8",
                    "role": "board-background",
                    "sha256": "sha256:" + "1" * 64,
                    "width": 16,
                }
            ],
            "widgets": [
                {
                    "packagePath": "/Game/UI/Blueprints/Menus/WB_Menu_Kits_PerkGrid_Board",
                    "path": "grid-assets/widgets/board.json",
                    "sha256": "sha256:" + "2" * 64,
                    "textureDependencies": [texture],
                }
            ],
        }
        source_manifest = {
            "archives": [],
            "coverage": {"gridAssets": coverage},
            "sourceFingerprint": fingerprint,
        }
        arguments = {
            "candidates": {"records": []},
            "grid_assets": grid_assets,
            "package_index": {"packages": []},
            "source_manifest": source_manifest,
            "strict": False,
        }

        valid = validate_outputs(**arguments)
        self.assertTrue(valid["valid"])

        broken = deepcopy(grid_assets)
        broken["widgets"][0]["textureDependencies"] = ["/Game/UI/Textures/Missing"]
        invalid = validate_outputs(**{**arguments, "grid_assets": broken})
        self.assertIn(
            "dangling-grid-widget-texture",
            {error["code"] for error in invalid["errors"]},
        )

    def validate(
        self,
        *,
        candidates: list[dict[str, object]],
    ) -> dict[str, object]:
        return validate_outputs(
            source_manifest={"archives": []},
            package_index={"packages": [{"packagePath": value["id"]} for value in candidates]},
            candidates={"records": candidates},
            strict=False,
        )

    def test_accepts_valid_candidate_semantic_graph_and_grid(self) -> None:
        result = self.validate(
            candidates=valid_semantic_candidates(),
        )

        self.assertTrue(result["valid"])
        self.assertEqual(result["errors"], [])

    def test_rejects_malformed_candidate_perk_grids(self) -> None:
        candidates = deepcopy(valid_semantic_candidates())
        by_id = {record["id"]: record for record in candidates}
        by_id["perk:base"]["grid"]["allowedRotations"] = ["Default"]
        by_id["perk:modifier"]["grid"]["shapes"][0]["collisionMask"] = [1]

        result = self.validate(candidates=candidates)

        self.assertFalse(result["valid"])
        self.assertEqual(
            {(error["code"], error.get("id")) for error in result["errors"]},
            {
                ("invalid-perk-grid-rotations", "perk:base"),
                ("invalid-perk-grid-shape", "perk:modifier"),
            },
        )

    def test_rejects_dangling_and_wrong_kind_nested_candidate_references(self) -> None:
        candidates = deepcopy(valid_semantic_candidates())
        by_id = {record["id"]: record for record in candidates}

        by_id["perk:base"]["kitEligibility"] = {
            "alternativeKitIds": ["perk:modifier"],
            "originKitId": "ability:implementation",
            "restrictedKitId": "missing:kit",
        }
        by_id["perk:base"]["ability"] = {
            "aliasOf": "kit:start",
            "availableToKitIds": ["missing:kit"],
            "originKitId": "perk:modifier",
            "role": "secondary",
            "sourceChipIds": ["ability:implementation"],
        }
        by_id["ability:implementation"]["implementationForAbilityIds"] = [
            "missing:perk",
            "kit:start",
        ]
        by_id["kit:start"]["abilityPerkIdsByRole"] = {
            "passive": ["perk:base"],
            "primary": ["ability:implementation"],
            "secondary": ["missing:perk"],
        }
        by_id["perk:modifier"]["dependencies"] = {
            "possibleModifierPerkIds": ["missing:perk"],
            "possibleTargetPerkIds": ["kit:start"],
            "requiresConnectedCompatibleTarget": True,
        }

        result = self.validate(candidates=candidates)

        self.assertFalse(result["valid"])
        failures = {
            (error["code"], error.get("field"))
            for error in result["errors"]
            if error["code"]
            in {"candidate-reference-kind-mismatch", "dangling-candidate-reference"}
        }
        self.assertEqual(
            failures,
            {
                ("candidate-reference-kind-mismatch", "ability.aliasOf"),
                ("candidate-reference-kind-mismatch", "ability.originKitId"),
                ("candidate-reference-kind-mismatch", "ability.sourceChipIds"),
                (
                    "candidate-reference-kind-mismatch",
                    "abilityPerkIdsByRole.primary",
                ),
                (
                    "candidate-reference-kind-mismatch",
                    "dependencies.possibleTargetPerkIds",
                ),
                (
                    "candidate-reference-kind-mismatch",
                    "implementationForAbilityIds",
                ),
                (
                    "candidate-reference-kind-mismatch",
                    "kitEligibility.alternativeKitIds",
                ),
                ("candidate-reference-kind-mismatch", "kitEligibility.originKitId"),
                ("dangling-candidate-reference", "ability.availableToKitIds"),
                ("dangling-candidate-reference", "abilityPerkIdsByRole.secondary"),
                (
                    "dangling-candidate-reference",
                    "dependencies.possibleModifierPerkIds",
                ),
                ("dangling-candidate-reference", "implementationForAbilityIds"),
                ("dangling-candidate-reference", "kitEligibility.restrictedKitId"),
            },
        )

    def test_validates_character_class_enrichment_references(self) -> None:
        candidates = [
            *deepcopy(valid_semantic_candidates()),
            {"id": "grid:board", "kind": "gridShape"},
            {"id": "weapon:default", "kind": "weapon"},
        ]
        by_id = {record["id"]: record for record in candidates}
        by_id["kit:start"].update(
            {
                "abilitySlots": [
                    {
                        "index": 0,
                        "lockedChipId": "perk:base",
                        "role": "secondary",
                        "selectableAbilityPerkIds": ["perk:base"],
                    }
                ],
                "chipEntitlements": [
                    {"index": 0, "perkId": "perk:base", "requiredRank": 2}
                ],
                "perkBoard": {
                    "lockedPlacements": [
                        {"chipId": "perk:base", "column": 9, "index": 0, "row": 1}
                    ],
                    "recordId": "grid:board",
                },
                "weaponSlots": [
                    {"defaultWeaponId": "weapon:default", "index": 0}
                ],
            }
        )

        valid = self.validate(candidates=candidates)
        self.assertTrue(valid["valid"])

        invalid = deepcopy(candidates)
        by_id = {record["id"]: record for record in invalid}
        kit = by_id["kit:start"]
        kit["abilitySlots"][0]["lockedChipId"] = "kit:custom"
        kit["abilitySlots"][0]["selectableAbilityPerkIds"] = ["missing:perk"]
        kit["chipEntitlements"][0]["perkId"] = "missing:entitlement"
        kit["perkBoard"]["recordId"] = "perk:base"
        kit["perkBoard"]["lockedPlacements"][0]["chipId"] = (
            "ability:implementation"
        )
        kit["weaponSlots"][0]["defaultWeaponId"] = "perk:base"

        result = self.validate(candidates=invalid)

        self.assertFalse(result["valid"])
        failures = {
            (error["code"], error.get("field"))
            for error in result["errors"]
            if error["code"]
            in {"candidate-reference-kind-mismatch", "dangling-candidate-reference"}
        }
        self.assertEqual(
            failures,
            {
                (
                    "candidate-reference-kind-mismatch",
                    "abilitySlots[0].lockedChipId",
                ),
                (
                    "candidate-reference-kind-mismatch",
                    "perkBoard.lockedPlacements[0].chipId",
                ),
                (
                    "candidate-reference-kind-mismatch",
                    "perkBoard.recordId",
                ),
                (
                    "candidate-reference-kind-mismatch",
                    "weaponSlots[0].defaultWeaponId",
                ),
                (
                    "dangling-candidate-reference",
                    "abilitySlots[0].selectableAbilityPerkIds",
                ),
                (
                    "dangling-candidate-reference",
                    "chipEntitlements[0].perkId",
                ),
            },
        )


if __name__ == "__main__":
    unittest.main()
