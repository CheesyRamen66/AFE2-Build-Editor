from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from afe2_catalogue.errors import CatalogueError  # noqa: E402
from afe2_catalogue.planner_catalogue import (  # noqa: E402
    _project_augment_description,
    _project_kit_weapon_slots,
    build_planner_catalogue,
)


def shape(width: int, height: int) -> dict[str, object]:
    cells = [
        {"column": column, "row": row}
        for row in range(height)
        for column in range(width)
    ]
    return {
        "cellCount": len(cells),
        "height": height,
        "occupiedCells": cells,
        "width": width,
    }


class PlannerCatalogueTests(unittest.TestCase):
    def test_augment_description_includes_authored_static_and_conditional_sections(
        self,
    ) -> None:
        source = {
            "conditionalDescriptions": [
                {
                    "conditionText": None,
                    "statLines": [
                        {
                            "displayType": "Integer",
                            "result": "HigherIsBetter",
                            "statText": "Explosion Radius",
                            "statValue": 150.0,
                        }
                    ],
                }
            ],
            "description": None,
            "descriptionShort": "Explosives detonate on impact.",
            "flavorText": None,
            "kind": "augment",
            "staticStatLines": [
                {
                    "displayText": "+10.0% Magazine Capacity",
                }
            ],
        }

        description, panel = _project_augment_description(source)

        self.assertEqual(
            description,
            (
                "Explosives detonate on impact.\r\n\r\n"
                "+10.0% Magazine Capacity\r\n\r\n"
                "+150 Explosion Radius"
            ),
        )
        self.assertEqual(
            panel,
            {
                "description": None,
                "descriptionSecondary": None,
                "descriptionUpper": "Explosives detonate on impact.",
            },
        )

    def test_projects_fully_unlocked_kit_weapon_picker_semantics(self) -> None:
        def weapon(
            *,
            category: str,
            ignore_tags: list[str],
            role: str,
            subtype: str,
        ) -> dict[str, object]:
            return {
                "compatibility": {
                    "collectionCategory": category,
                    "kitIgnoreTags": ignore_tags,
                    "kitTags": ["Kit.SomeOtherClass"],
                    "status": "resolved",
                    "weaponRole": role,
                    "weaponSubType": subtype,
                }
            }

        records = {
            "weapon:primary-rifle": weapon(
                category="rifle", ignore_tags=[], role="primary", subtype="automatic"
            ),
            "weapon:primary-cqw": weapon(
                category="cqw", ignore_tags=[], role="primary", subtype="shotgun"
            ),
            "weapon:signature-other-kit": weapon(
                category="heavy", ignore_tags=[], role="signature", subtype="machinegun"
            ),
            "weapon:signature-ignored": weapon(
                category="heavy",
                ignore_tags=["Kit.Test"],
                role="signature",
                subtype="machinegun",
            ),
            "weapon:sidearm-auto": weapon(
                category="handgun", ignore_tags=[], role="sidearm", subtype="automatic"
            ),
        }
        slots = [
            {
                "index": 0,
                "slotType": "primary",
                "weaponSubtype": "any",
                "weaponType": "rifle",
            },
            {
                "index": 1,
                "kitTag": "Kit.Test",
                "slotType": "signature",
                "weaponSubtype": "any",
                "weaponType": "heavy",
            },
            {
                "index": 2,
                "slotType": "any",
                "weaponSubtype": "automatic",
                "weaponType": "cqw",
            },
        ]

        result = _project_kit_weapon_slots(
            slots,
            records_by_id=records,
            visible_weapon_ids=set(records),
        )

        self.assertEqual(
            result[0]["compatibleWeaponIds"],
            ["weapon:primary-cqw", "weapon:primary-rifle"],
        )
        self.assertEqual(
            result[1]["compatibleWeaponIds"],
            ["weapon:signature-other-kit"],
        )
        self.assertEqual(
            result[2]["compatibleWeaponIds"],
            ["weapon:primary-rifle", "weapon:sidearm-auto"],
        )

    def test_filters_to_authored_membership_and_compiles_board_contract(self) -> None:
        fingerprint = "sha256:fixture"
        primary = "perk:primary"
        secondary = "perk:secondary"
        passive = "perk:passive"
        core = "perk:core"
        modifier = "perk:modifier"
        source_metadata = {
            "extractor": {"name": "afe2-catalogue", "version": "test"},
            "game": {"buildId": "fixture-build", "steamAppId": "3448650"},
        }
        semantic = {
            "itemSlots": [
                {
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
            "kitAbilities": [
                {
                    "availableToKitIds": ["kit:one", "kit:latent"],
                    "gameplayAbilityPackagePath": "ga:primary",
                    "id": primary,
                    "originKitId": "kit:one",
                    "role": "primary",
                    "sourceChipIds": [primary, "perk:primary-alias"],
                },
                {
                    "availableToKitIds": ["kit:one"],
                    "gameplayAbilityPackagePath": "ga:secondary",
                    "id": secondary,
                    "originKitId": "kit:one",
                    "role": "secondary",
                    "sourceChipIds": [secondary],
                },
                {
                    "availableToKitIds": ["kit:one"],
                    "gameplayAbilityPackagePath": "ga:passive",
                    "id": passive,
                    "originKitId": "kit:one",
                    "role": "passive",
                    "sourceChipIds": [passive],
                },
            ],
            "records": [
                {
                    "abilityPerkIdsByRole": {
                        "passive": [passive],
                        "primary": [primary],
                        "secondary": [secondary],
                    },
                    "abilitySlots": [
                        {
                            "column": 0,
                            "lockedChipId": primary,
                            "role": "primary",
                            "row": 1,
                            "selectableAbilityPerkIds": ["perk:primary-alias"],
                        },
                        {
                            "column": 9,
                            "lockedChipId": secondary,
                            "role": "secondary",
                            "row": 1,
                            "selectableAbilityPerkIds": [secondary],
                        },
                        {
                            "column": 3,
                            "lockedChipId": passive,
                            "role": "passive",
                            "row": 5,
                            "selectableAbilityPerkIds": [passive],
                        },
                    ],
                    "chipEntitlements": [
                        {"perkId": core, "requiredRank": 2},
                        {"perkId": modifier, "requiredRank": 3},
                        {"perkId": "perk:primary-alias", "requiredRank": 4},
                    ],
                    "displayName": "One",
                    "id": "kit:one",
                    "kind": "kit",
                    "packagePath": "kit:one",
                    "perkBoard": {
                        "lockedPlacements": [
                            {"chipId": primary, "column": 0, "row": 1},
                            {"chipId": secondary, "column": 9, "row": 1},
                            {"chipId": passive, "column": 3, "row": 5},
                        ]
                    },
                    "weaponSlots": [
                        {
                            "defaultWeaponId": "weapon:visible",
                            "index": 0,
                            "slotType": "primary",
                            "weaponSubtype": "any",
                            "weaponType": "rifle",
                        }
                    ],
                },
                {
                    "characterClassPackagePath": "class:latent",
                    "id": "kit:latent",
                    "kind": "kit",
                    "packagePath": "kit:latent",
                },
                {
                    "description": "Primary description",
                    "displayName": "Primary",
                    "grid": {"allowedRotations": ["Default"], "shapes": [shape(1, 4)]},
                    "id": primary,
                    "kind": "perk",
                    "packagePath": primary,
                },
                {
                    "ability": {"aliasOf": primary, "role": "primary"},
                    "id": "perk:primary-alias",
                    "kind": "perk",
                    "packagePath": "perk:primary-alias",
                },
                {
                    "description": "Secondary description",
                    "displayName": "Secondary",
                    "grid": {"allowedRotations": ["Default"], "shapes": [shape(1, 4)]},
                    "id": secondary,
                    "kind": "perk",
                    "packagePath": secondary,
                },
                {
                    "description": "Passive description",
                    "displayName": "Passive",
                    "grid": {"allowedRotations": ["Default"], "shapes": [shape(4, 1)]},
                    "id": passive,
                    "kind": "perk",
                    "packagePath": passive,
                },
                {
                    "displayName": "Rampage",
                    "chipVisual": {"family": "core", "status": "resolved"},
                    "effects": ["must not leak"],
                    "grid": {"allowedRotations": ["Default"], "shapes": [shape(1, 1)]},
                    "id": core,
                    "kind": "perk",
                    "kitEligibility": {"restrictedKitId": "kit:one"},
                    "packagePath": core,
                    "stats": ["out of scope"],
                    "visualClassification": {
                        "evidence": {
                            "property": "Default__Rampage_C.RestrictionType",
                            "source": "serialized-enum",
                            "valueRaw": "EModChipRestrictionType::Kit",
                        },
                        "restrictionType": "kit",
                        "restrictionTypeRaw": "EModChipRestrictionType::Kit",
                        "status": "resolved",
                    },
                },
                {
                    "dependencies": {
                        "possibleTargetPerkIds": [
                            "perk:primary-alias",
                            core,
                            "perk:latent",
                        ],
                        "requiresConnectedCompatibleTarget": True,
                    },
                    "chipVisual": {"family": "modifier", "status": "resolved"},
                    "displayName": "Single Targeting",
                    "grid": {"allowedRotations": ["Default"], "shapes": [shape(1, 1)]},
                    "id": modifier,
                    "kind": "perk",
                    "kitEligibility": {"restrictedKitId": "kit:one"},
                    "packagePath": modifier,
                    "perkType": "modifier",
                },
                {"id": "perk:latent", "kind": "perk", "packagePath": "perk:latent"},
                {
                    "chipVisual": {"family": "core", "status": "resolved"},
                    "description": "Store perk description",
                    "displayName": "Store Perk",
                    "grid": {"allowedRotations": ["Default"], "shapes": [shape(1, 1)]},
                    "id": "perk:store",
                    "kind": "perk",
                    "packagePath": "perk:store",
                },
                {
                    "chipVisual": {"family": "core", "status": "resolved"},
                    "description": "Mission perk description",
                    "displayName": "Mission Perk",
                    "grid": {"allowedRotations": ["Default"], "shapes": [shape(1, 1)]},
                    "id": "perk:mission",
                    "kind": "perk",
                    "packagePath": "perk:mission",
                },
                {
                    "chipVisual": {"family": "core", "status": "resolved"},
                    "description": "Latent-origin store perk description",
                    "displayName": "Latent-origin Store Perk",
                    "grid": {"allowedRotations": ["Default"], "shapes": [shape(1, 1)]},
                    "id": "perk:latent-kit-only",
                    "kind": "perk",
                    "kitEligibility": {"restrictedKitId": "kit:latent"},
                    "packagePath": "perk:latent-kit-only",
                },
                {
                    "compatibility": {
                        "slots": [
                            {"compatibleIds": ["mod:magazine", "mod:latent"], "index": 0, "kind": "component", "requiredModTags": ["Item.Attachment.Magazine"]},
                            {"compatibleIds": ["mod:optic"], "index": 1, "kind": "component", "requiredModTags": ["Item.Attachment.Optic"]},
                            {"compatibleIds": ["mod:muzzle"], "index": 2, "kind": "component", "requiredModTags": ["Item.Attachment.Muzzle"]},
                            {"compatibleIds": ["trait:visible", "trait:latent"], "index": 3, "kind": "trait", "requiredModTags": ["Item.Attachment.Mod"]},
                            {"compatibleIds": ["augment:rifle-variant"], "index": 4, "kind": "augment", "requiredModTags": ["Item.Attachment.Overclock"]},
                        ],
                        "source": "serialized-uasset",
                        "status": "resolved",
                        "collectionCategory": "rifle",
                        "kitIgnoreTags": [],
                        "kitTags": [],
                        "weaponRole": "primary",
                        "weaponSubType": "automatic",
                    },
                    "displayName": "Visible Rifle",
                    "icon": {"path": "icons/rifle.png"},
                    "id": "weapon:visible",
                    "kind": "weapon",
                    "packagePath": "weapon:visible",
                    "stats": ["must not leak"],
                },
                {
                    "displayName": "Latent Rifle",
                    "id": "weapon:latent",
                    "kind": "weapon",
                    "packagePath": "weapon:latent",
                },
                *[
                    {
                        "compatibility": {
                            "compatibleWeaponIds": ["weapon:visible", "weapon:latent"],
                            "source": "serialized-uasset",
                            "status": "resolved",
                        },
                        "displayName": mod_id.split(":", 1)[-1].title(),
                        "id": mod_id,
                        "kind": "mod",
                        "packagePath": mod_id,
                    }
                    for mod_id in ("mod:magazine", "mod:optic", "mod:muzzle")
                ],
                {
                    "compatibility": {
                        "compatibleWeaponIds": ["weapon:visible", "weapon:latent"],
                        "source": "serialized-uasset",
                        "status": "resolved",
                    },
                    "displayName": "Visible Trait",
                    "id": "trait:visible",
                    "kind": "trait",
                    "packagePath": "trait:visible",
                },
                {
                    "description": "Item description",
                    "displayName": "Frag Grenade",
                    "id": "item:frag",
                    "itemTier": "minor",
                    "kind": "item",
                    "packagePath": "item:frag",
                },
                {
                    "description": "Major item description",
                    "displayName": "Sentry Gun",
                    "id": "item:sentry",
                    "itemTier": "major",
                    "kind": "item",
                    "packagePath": "item:sentry",
                },
                {
                    "compatibility": {
                        "compatibleWeaponIds": ["weapon:visible", "weapon:latent"],
                        "status": "resolved",
                    },
                    "description": None,
                    "descriptionShort": "Rifle-specific payload summary.",
                    "displayName": "Rifle-specific payload",
                    "flavorText": "Rifle-specific payload flavor text.",
                    "icon": {"path": "icons/rifle-specific-payload.png"},
                    "id": "augment:rifle-variant",
                    "kind": "augment",
                    "packagePath": "augment:rifle-variant",
                },
            ],
            "sourceFingerprint": fingerprint,
        }
        second_kit = deepcopy(semantic["records"][0])
        second_kit.update(
            {
                "chipEntitlements": [],
                "displayName": "Two",
                "id": "kit:two",
                "packagePath": "kit:two",
            }
        )
        semantic["records"].insert(1, second_kit)
        for concept in semantic["kitAbilities"]:
            concept["availableToKitIds"].append("kit:two")
        magazine = next(
            record
            for record in semantic["records"]
            if record["id"] == "mod:magazine"
        )
        magazine["description"] = None
        magazine["staticStatLines"] = [
            {
                "attribute": "GunGameplayAttributes.TimeToReload",
                "displayText": "+20.0% Reload Speed",
                "displayType": "Percent",
                "displayValue": "+20.0%",
                "effectPackagePath": "effect:reload-speed",
                "result": "HigherIsBetter",
                "sortOrder": 13,
                "statText": "Reload Speed",
                "statValue": 20.0,
            }
        ]
        magazine["conditionalDescriptions"] = [
            {
                "conditionText": "<Bold>On Reload</>:",
                "statLines": [
                    {
                        "displayType": "Percent",
                        "result": "HigherIsBetter",
                        "statText": "Reload Speed",
                        "statValue": 10.0,
                    }
                ],
            }
        ]
        collection = {
            "categories": [
                {"key": "Weapons", "memberIds": ["weapon:visible"]},
                {"key": "Magazines", "memberIds": ["mod:magazine"]},
                {"key": "Optics", "memberIds": ["mod:optic"]},
                {"key": "Muzzles", "memberIds": ["mod:muzzle"]},
                {"key": "Traits", "memberIds": ["trait:visible"]},
                {
                    "key": "Items",
                    "memberIds": ["item:frag", "item:sentry"],
                },
                {
                    "key": "Perks",
                    "memberIds": ["perk:store", "perk:latent-kit-only"],
                },
                {
                    "entries": [
                        {
                            "availability": {"purchasable": True},
                            "id": "augment:concept",
                            "status": "resolved",
                            "terminalRecords": [{"id": "augment:rifle-variant"}],
                        }
                    ],
                    "key": "AugmentPacks",
                    "memberIds": ["augment:concept"],
                },
            ],
            "conceptRecords": [
                {
                    "description": "Concept description",
                    "displayName": "Payload",
                    "icon": {"path": "icons/payload.png"},
                    "id": "augment:concept",
                    "kind": "augment",
                    "packagePath": "augment:concept",
                }
            ],
            "kitMembership": {
                "coverage": {
                    "mappedKits": 2,
                    "unresolvedReferences": 0,
                },
                "entries": [
                    {
                        "characterClassPackagePath": "class:one",
                        "id": "kit:one",
                        "kind": "kit",
                        "packagePath": "kit:one",
                        "sources": [{"sourceKind": "default-starting-rewards"}],
                    },
                    {
                        "characterClassPackagePath": "class:two",
                        "id": "kit:two",
                        "kind": "kit",
                        "packagePath": "kit:two",
                        "sources": [{"sourceKind": "default-starting-rewards"}],
                    },
                ],
                "memberIds": ["kit:one", "kit:two"],
                "status": "complete",
                "unresolved": [],
            },
            "progressionPerks": {
                "coverage": {"unresolvedReferences": 2},
                "memberIds": ["perk:mission"],
                "status": "incomplete",
            },
            "sourceFingerprint": fingerprint,
        }
        perk_color_palette = {
            "colors": [
                {
                    "index": 0,
                    "linearRgba": {"a": 1.0, "b": 0.2, "g": 0.6, "r": 0.5},
                    "srgbHex": "#bcd079ff",
                },
                {
                    "index": 1,
                    "linearRgba": {"a": 1.0, "b": 0.6, "g": 0.7, "r": 0.3},
                    "srgbHex": "#95dacbff",
                },
            ],
            "indexRule": "index modulo 2",
            "sourceFunction": "ReturnPerkColor",
            "sourcePackagePath": "/Game/UI/Blueprints/WB_UI_Colors_Functions",
            "status": "parsed",
        }
        grid = {
            "layoutMetrics": {
                "board": {"columns": 10, "rows": 5, "status": "parsed"}
            },
            "perkColorPalette": perk_color_palette,
            "sourceFingerprint": fingerprint,
            "textures": [
                {
                    "family": "core",
                    "footprint": {"height": 1, "width": 1},
                    "packagePath": "texture:core-1x1",
                    "path": "grid-assets/textures/core.png",
                    "role": "chip-body",
                    "sha256": "sha256:" + "1" * 64,
                    "variant": "default",
                },
                {
                    "family": "modifier",
                    "footprint": {"height": 1, "width": 1},
                    "packagePath": "texture:modifier-1x1",
                    "path": "grid-assets/textures/modifier.png",
                    "role": "chip-body",
                    "sha256": "sha256:" + "2" * 64,
                    "variant": "default",
                },
                {
                    "family": "replacer",
                    "footprint": {"height": 4, "width": 1},
                    "packagePath": "texture:replacer-1x4",
                    "path": "grid-assets/textures/replacer-1x4.png",
                    "role": "chip-body",
                    "sha256": "sha256:" + "3" * 64,
                    "variant": "default",
                },
                {
                    "family": "replacer",
                    "footprint": {"height": 4, "width": 1},
                    "packagePath": "texture:replacer-1x4-right",
                    "path": "grid-assets/textures/replacer-1x4-right.png",
                    "role": "chip-body",
                    "sha256": "sha256:" + "4" * 64,
                    "variant": "right",
                },
                {
                    "family": "replacer",
                    "footprint": {"height": 1, "width": 4},
                    "packagePath": "texture:replacer-4x1",
                    "path": "grid-assets/textures/replacer-4x1.png",
                    "role": "chip-body",
                    "sha256": "sha256:" + "5" * 64,
                    "variant": "default",
                },
                {
                    "family": None,
                    "footprint": None,
                    "packagePath": "texture:connector-ghost",
                    "path": "grid-assets/textures/connector-ghost.png",
                    "role": "connector",
                    "sha256": "sha256:" + "6" * 64,
                    "variant": "ghost",
                },
            ],
        }
        for texture in grid["textures"]:
            texture["pixelFormat"] = "PF_B8G8R8A8"

        result = build_planner_catalogue(
            semantic=semantic,
            collection=collection,
            grid_assets=grid,
            **source_metadata,
            source_fingerprint=fingerprint,
        )

        records = {record["id"]: record for record in result["records"]}
        self.assertIn("weapon:visible", records)
        self.assertNotIn("kit:latent", records)
        self.assertNotIn("kit:latent", repr(result))
        self.assertNotIn("weapon:latent", records)
        self.assertNotIn("perk:latent", records)
        self.assertIn("perk:latent-kit-only", records)
        self.assertNotIn("perk:primary-alias", records)
        self.assertIn("perk:store", records)
        self.assertIn("perk:mission", records)
        all_kit_ids = ["kit:one", "kit:two"]
        ordinary_perk_ids = {
            core,
            modifier,
            "perk:latent-kit-only",
            "perk:mission",
            "perk:store",
        }
        self.assertEqual(records["perk:store"]["availableToKitIds"], all_kit_ids)
        self.assertEqual(
            records["perk:mission"]["selectionSources"],
            ["progression-unlock"],
        )
        for perk_id in ordinary_perk_ids:
            self.assertEqual(records[perk_id]["availableToKitIds"], all_kit_ids)
        for kit_id in all_kit_ids:
            self.assertEqual(
                set(records[kit_id]["selectablePerkIds"]), ordinary_perk_ids
            )
        self.assertEqual(records[core]["displayName"], "Rampage")
        self.assertEqual(records[core]["perkType"], "core")
        self.assertEqual(
            records[core]["visualClassification"],
            {
                "evidence": {
                    "property": "Default__Rampage_C.RestrictionType",
                    "source": "serialized-enum",
                    "valueRaw": "EModChipRestrictionType::Kit",
                },
                "restrictionType": "kit",
                "restrictionTypeRaw": "EModChipRestrictionType::Kit",
                "status": "resolved",
            },
        )
        self.assertEqual(
            records[core]["availability"],
            [{"kitId": "kit:one", "requiredRank": 2}],
        )
        self.assertEqual(records[core]["selectionSources"], ["class-entitlement"])
        self.assertEqual(records[modifier]["displayName"], "Single Targeting")
        self.assertEqual(records[modifier]["perkType"], "modifier")
        self.assertEqual(
            records["kit:one"]["weaponSlots"][0]["compatibleWeaponIds"],
            ["weapon:visible"],
        )
        self.assertEqual(
            result["sourceCoverage"]["progressionPerks"],
            {
                "coverage": {"unresolvedReferences": 2},
                "status": "incomplete",
            },
        )
        self.assertNotIn("augment:concept", records)
        self.assertIn("augment:rifle-variant", records)
        augment = records["augment:rifle-variant"]
        self.assertEqual(
            augment["collectionConceptId"],
            "augment:concept",
        )
        self.assertEqual(
            augment["availability"],
            {"purchasable": True},
        )
        self.assertEqual(
            augment["compatibleWeaponIds"],
            ["weapon:visible"],
        )
        self.assertEqual(
            augment["displayName"],
            "Rifle-specific payload",
        )
        self.assertEqual(
            augment["icon"],
            {"path": "icons/rifle-specific-payload.png"},
        )
        self.assertEqual(
            augment["description"],
            (
                "Rifle-specific payload flavor text.\r\n\r\n"
                "Rifle-specific payload summary."
            ),
        )
        self.assertEqual(
            augment["descriptionPanel"],
            {
                "description": None,
                "descriptionSecondary": "Rifle-specific payload flavor text.",
                "descriptionUpper": "Rifle-specific payload summary.",
            },
        )
        self.assertNotIn("effects", records[core])
        self.assertNotIn("stats", records[core])
        self.assertEqual(records["item:frag"]["availableToKitIds"], all_kit_ids)
        self.assertEqual(records["item:sentry"]["availableToKitIds"], all_kit_ids)
        self.assertEqual(result["game"], source_metadata["game"])
        self.assertEqual(result["extractor"], source_metadata["extractor"])
        self.assertFalse(result["textContract"]["packagePathIsDisplayText"])
        self.assertEqual(
            [
                (slot["index"], slot["itemTier"], slot["displayName"])
                for slot in result["itemSlots"]
            ],
            [(2, "minor", "Minor Item"), (4, "major", "Major Item")],
        )
        self.assertEqual(
            result["itemSlots"][0]["compatibleItemIds"], ["item:frag"]
        )
        self.assertEqual(
            result["itemSlots"][1]["compatibleItemIds"], ["item:sentry"]
        )
        self.assertEqual(len(records["weapon:visible"]["componentSlots"]), 3)
        self.assertEqual(
            records["weapon:visible"]["componentSlots"][0]["slotCategory"],
            "magazine",
        )
        self.assertEqual(
            records["weapon:visible"]["componentSlots"][0]["displayName"],
            "Magazine",
        )
        self.assertEqual(
            records["weapon:visible"]["compatibility"]["compatibleAugmentIds"],
            ["augment:rifle-variant"],
        )
        self.assertEqual(
            records["weapon:visible"]["compatibility"]["augmentSlot"][
                "compatibleIds"
            ],
            ["augment:rifle-variant"],
        )
        self.assertEqual(
            records["mod:magazine"]["compatibility"]["compatibleWeaponIds"],
            ["weapon:visible"],
        )
        self.assertEqual(
            records["mod:magazine"]["conditionalDescriptions"],
            magazine["conditionalDescriptions"],
        )
        self.assertEqual(
            records["mod:magazine"]["staticStatLines"],
            magazine["staticStatLines"],
        )
        self.assertIsNone(records["mod:magazine"]["authoredDescription"])
        self.assertEqual(
            records["mod:magazine"]["description"],
            (
                "+20.0% Reload Speed\r\n\r\n"
                "<Bold>On Reload</>:\r\n  +10% Reload Speed"
            ),
        )
        self.assertNotIn("effects", records["mod:magazine"])
        self.assertNotIn("stats", records["mod:magazine"])
        self.assertEqual(
            result["coverage"]["recordsWithConditionalDescriptions"],
            1,
        )
        self.assertEqual(result["coverage"]["recordsWithStaticStatLines"], 1)
        self.assertEqual(result["coverage"]["augmentPacks"], 1)
        self.assertEqual(result["coverage"]["augmentImplementations"], 1)
        self.assertEqual(
            result["textContract"]["augmentDescriptionComposition"],
            {
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
        )
        self.assertEqual(
            result["textContract"]["attachmentDescriptionComposition"],
            {
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
        )
        self.assertEqual(
            records[modifier]["dependencies"]["targetSelection"]["candidateIds"],
            [core, primary],
        )
        layout = result["perkGrid"]["kitLayouts"][0]
        primary_anchor = next(
            anchor for anchor in layout["anchors"] if anchor["role"] == "primary"
        )
        self.assertEqual(primary_anchor["selectableAbilityIds"], [primary])
        self.assertEqual(
            primary_anchor["rendering"]["chipBody"]["pixelFormat"],
            "PF_B8G8R8A8",
        )
        self.assertEqual(
            records[core]["rendering"]["chipBodyByFootprint"][0]["pixelFormat"],
            "PF_B8G8R8A8",
        )
        self.assertEqual(layout["placeableCellCount"], 42)
        labels = {cell["label"] for cell in layout["placeableCells"]}
        self.assertEqual(
            labels,
            {
                *(f"{column}1" for column in "ABCDEFGHIJ"),
                *(f"{column}{row}" for row in range(2, 6) for column in "BCDEFGHI"),
            },
        )
        self.assertEqual(layout["renderExtent"], {"columns": 10, "rows": 6})
        self.assertEqual(result["perkGrid"]["perkColorPalette"], perk_color_palette)
        self.assertEqual(
            result["perkGrid"]["familyConnector"]["path"],
            "grid-assets/textures/connector-ghost.png",
        )

        no_primary_semantic = deepcopy(semantic)
        no_primary_kit = next(
            record
            for record in no_primary_semantic["records"]
            if record["id"] == "kit:one"
        )
        no_primary_kit["abilityPerkIdsByRole"]["primary"] = []
        no_primary_kit["abilitySlots"] = [
            slot
            for slot in no_primary_kit["abilitySlots"]
            if slot["role"] != "primary"
        ]
        no_primary_kit["perkBoard"]["lockedPlacements"] = [
            placement
            for placement in no_primary_kit["perkBoard"]["lockedPlacements"]
            if placement["chipId"] != primary
        ]
        no_primary_kit["chipEntitlements"] = [
            entitlement
            for entitlement in no_primary_kit["chipEntitlements"]
            if entitlement["perkId"] != "perk:primary-alias"
        ]
        no_primary_concept = next(
            concept
            for concept in no_primary_semantic["kitAbilities"]
            if concept["id"] == primary
        )
        no_primary_concept["availableToKitIds"].remove("kit:one")
        no_primary = build_planner_catalogue(
            semantic=no_primary_semantic,
            collection=collection,
            grid_assets=grid,
            **source_metadata,
            source_fingerprint=fingerprint,
        )
        no_primary_layout = no_primary["perkGrid"]["kitLayouts"][0]
        no_primary_anchor = next(
            anchor
            for anchor in no_primary_layout["anchors"]
            if anchor["role"] == "primary"
        )
        self.assertEqual(no_primary_layout["placeableCellCount"], 42)
        self.assertEqual(no_primary_anchor["selectableAbilityIds"], [])
        self.assertEqual(no_primary_anchor["anchorSource"], "fixed-reserved-slot")

        empty_membership = deepcopy(collection)
        empty_membership["kitMembership"]["memberIds"] = []
        empty_membership["kitMembership"]["entries"] = []
        with self.assertRaises(CatalogueError):
            build_planner_catalogue(
                semantic=semantic,
                collection=empty_membership,
                grid_assets=grid,
                **source_metadata,
                source_fingerprint=fingerprint,
            )

        missing_visual = deepcopy(semantic)
        missing_visual_core = next(
            record
            for record in missing_visual["records"]
            if record["id"] == core
        )
        del missing_visual_core["chipVisual"]
        with self.assertRaisesRegex(
            CatalogueError, "no resolved core/modifier chip visual"
        ):
            build_planner_catalogue(
                semantic=missing_visual,
                collection=collection,
                grid_assets=grid,
                **source_metadata,
                source_fingerprint=fingerprint,
            )

        mismatched_type = deepcopy(semantic)
        mismatched_core = next(
            record
            for record in mismatched_type["records"]
            if record["id"] == core
        )
        mismatched_core["perkType"] = "modifier"
        with self.assertRaisesRegex(CatalogueError, "disagreed with its chip visual"):
            build_planner_catalogue(
                semantic=mismatched_type,
                collection=collection,
                grid_assets=grid,
                **source_metadata,
                source_fingerprint=fingerprint,
            )

        duplicate_item_tier = deepcopy(semantic)
        duplicate_item_tier["itemSlots"].append(
            {
                **deepcopy(duplicate_item_tier["itemSlots"][0]),
                "index": 5,
            }
        )
        with self.assertRaisesRegex(
            CatalogueError, "exactly one major and one minor"
        ):
            build_planner_catalogue(
                semantic=duplicate_item_tier,
                collection=collection,
                grid_assets=grid,
                **source_metadata,
                source_fingerprint=fingerprint,
            )

        internal_name = deepcopy(semantic)
        internal_name_weapon = next(
            record
            for record in internal_name["records"]
            if record["id"] == "weapon:visible"
        )
        internal_name_weapon["displayName"] = "/Game/UI/T_NotHuman"
        with self.assertRaisesRegex(CatalogueError, "human-readable authored"):
            build_planner_catalogue(
                semantic=internal_name,
                collection=collection,
                grid_assets=grid,
                **source_metadata,
                source_fingerprint=fingerprint,
            )


if __name__ == "__main__":
    unittest.main()
