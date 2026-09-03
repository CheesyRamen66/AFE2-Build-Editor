from __future__ import annotations

import copy
from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from afe2_catalogue.weapon_compatibility import (  # noqa: E402
    build_weapon_compatibility,
    evaluate_equip_rules,
)


WEAPON = "/Game/Test/Weapons/FutureRifle"
WEAPON_BASE = "/Game/Test/Weapons/BaseFutureRifle"
ATTACHMENT_BASE = "/Game/Test/Attachments/BaseAttachment"
INTERNAL_BASE = "/Game/Test/Attachments/BaseInternalMagazine"
INTERNAL = "/Game/Test/Attachments/InternalMagazine"
TRAIT = "/Game/Test/Traits/NoInternalTrait"
AUGMENT = "/Game/Test/Augments/AutoAugment"


def prop(
    name: str,
    value: object,
    type_name: str = "ObjectPropertyData",
    **extra: object,
) -> dict[str, object]:
    return {
        "$type": f"UAssetAPI.PropertyTypes.{type_name}, UAssetAPI",
        "Name": name,
        "Value": value,
        **extra,
    }


def enum_prop(name: str, enum_type: str, value: str) -> dict[str, object]:
    return prop(name, f"{enum_type}::{value}", "Objects.EnumPropertyData", EnumType=enum_type)


def tag_container(name: str, tags: list[str]) -> dict[str, object]:
    return prop(
        name,
        [prop(name, tags, "Structs.GameplayTagContainerPropertyData")],
        "Structs.StructPropertyData",
    )


def soft_object(name: str, package: str) -> dict[str, object]:
    return prop(
        name,
        {
            "AssetPath": {
                "PackageName": None,
                "AssetName": f"{package}.{package.rsplit('/', 1)[-1]}_C",
            },
            "SubPathString": None,
        },
        "Objects.SoftObjectPropertyData",
    )


def soft_object_array(name: str, packages: list[str]) -> dict[str, object]:
    return prop(
        name,
        [soft_object(str(index), package) for index, package in enumerate(packages)],
        "Objects.ArrayPropertyData",
        ArrayType="SoftObjectProperty",
    )


def rule(
    rule_type: str,
    *,
    chassis: str | None = None,
    chassis_list: list[str] | None = None,
    gun_type: str = "Handgun",
    gun_sub_type: str = "Any",
    required: list[str] | None = None,
    forbidden: list[str] | None = None,
) -> dict[str, object]:
    fields: list[dict[str, object]] = [
        enum_prop("RuleType", "EGunModEquipRuleType", rule_type),
        soft_object_array("ChassisList", chassis_list or []),
        enum_prop("GunType", "EGunType", gun_type),
        enum_prop("GunSubType", "EGunSubType", gun_sub_type),
        tag_container("RequiredChassisTags", required or []),
        tag_container("ForbiddenChassisTags", forbidden or []),
    ]
    if chassis is not None:
        fields.insert(1, soft_object("Chassis", chassis))
    return prop(
        "GunEquipRules",
        fields,
        "Structs.StructPropertyData",
        StructType="GunModEquipRule",
    )


def rules(*values: dict[str, object]) -> dict[str, object]:
    return prop(
        "GunEquipRules",
        list(values),
        "Objects.ArrayPropertyData",
        ArrayType="StructProperty",
    )


def slot(
    required: str,
    *,
    hidden: bool = False,
    appearance_only: bool = False,
    level: int = 0,
    display_name: str | None = None,
) -> dict[str, object]:
    fields: list[dict[str, object]] = [
        tag_container("RequiredModTags", [required]),
        tag_container("SlotTags", []),
        prop("DefaultSlottedMod", 0, "Objects.ObjectPropertyData"),
        prop("RequiredLevel", level, "Objects.IntPropertyData"),
        prop("bIsAppearanceOnlySlot", appearance_only, "Objects.BoolPropertyData"),
        prop("bHideFromUI", hidden, "Objects.BoolPropertyData"),
    ]
    if display_name is not None:
        fields.append(
            prop(
                "SlotDisplayName",
                "TEXT-HASH",
                "Objects.TextPropertyData",
                CultureInvariantString=display_name,
            )
        )
    return prop(
        "PartSlots",
        fields,
        "Structs.StructPropertyData",
        StructType="ModSlotDef",
    )


def slots(*values: dict[str, object]) -> dict[str, object]:
    return prop(
        "PartSlots",
        list(values),
        "Objects.ArrayPropertyData",
        ArrayType="StructProperty",
    )


def asset(path: str, parent: str, properties: list[dict[str, object]]) -> dict[str, object]:
    if parent.startswith("/Game/"):
        parent_leaf = f"{parent.rsplit('/', 1)[-1]}_C"
        imports = [
            {"objectName": parent_leaf, "outerIndex": -2},
            {"objectName": parent, "outerIndex": 0},
        ]
    else:
        script, parent_leaf = parent.rsplit(".", 1)
        imports = [
            {"objectName": parent_leaf, "outerIndex": -2},
            {"objectName": script, "outerIndex": 0},
        ]
    leaf = path.rsplit("/", 1)[-1]
    return {
        "exports": [
            {"data": [], "objectName": f"{leaf}_C", "superIndex": -1},
            {"data": properties, "objectName": f"Default__{leaf}_C"},
        ],
        "imports": imports,
        "packagePath": path,
    }


def record(path: str, kind: str) -> dict[str, object]:
    return {"id": path, "kind": kind, "packagePath": path, "status": "verified"}


class EquipRuleTests(unittest.TestCase):
    def evaluate(self, rules_value: list[dict[str, object]], **changes: object) -> bool:
        arguments: dict[str, object] = {
            "chassis_tags": ["Chassis.Heatsink.Advanced"],
            "gun_sub_type": "Auto",
            "gun_type": "Rifle",
            "part_slot_required_tags": [["Item.Attachment.Magazine.Internal"]],
            "weapon_package_path": WEAPON,
        }
        arguments.update(changes)
        return evaluate_equip_rules(rules_value, **arguments)  # type: ignore[arg-type]

    def test_every_positive_native_rule_type(self) -> None:
        matching_rules = [
            {"type": "Default"},
            {"type": "GunType", "gunType": "Rifle"},
            {"type": "GunSubType", "gunSubType": "Auto"},
            {"type": "GunTypeAndSubType", "gunType": "Rifle", "gunSubType": "Auto"},
            {"type": "SpecificChassis", "chassisId": WEAPON},
            {"type": "SpecificChassisList", "chassisIds": ["/Game/Other", WEAPON]},
            {"type": "ChassisTags", "requiredTags": ["Chassis.Heatsink"]},
            {
                "type": "ComplexChassisTags",
                "requiredTags": ["Chassis.Heatsink"],
                "forbiddenTags": ["Chassis.Flamethrower"],
            },
            {
                "type": "ComplexAttachmentTags",
                "requiredTags": ["Item.Attachment.Magazine"],
                "forbiddenTags": ["Item.Attachment.Barrel"],
            },
        ]
        for value in matching_rules:
            with self.subTest(rule=value["type"]):
                self.assertTrue(self.evaluate([value]))

    def test_rules_are_ordered_alternatives_with_an_early_forbidden_veto(self) -> None:
        self.assertTrue(
            self.evaluate(
                [
                    {"type": "GunType", "gunType": "Precision"},
                    {"type": "GunSubType", "gunSubType": "Auto"},
                ]
            )
        )
        self.assertFalse(
            self.evaluate(
                [
                    {"type": "ForbiddenChassisList", "chassisIds": [WEAPON]},
                    {"type": "Default"},
                ]
            )
        )
        self.assertTrue(
            self.evaluate(
                [
                    {"type": "ForbiddenChassisList", "chassisIds": ["/Game/Other"]},
                    {"type": "Default"},
                ]
            )
        )

    def test_complex_attachment_rule_uses_slot_required_tags_and_tag_parents(self) -> None:
        self.assertFalse(
            self.evaluate(
                [
                    {
                        "type": "ComplexAttachmentTags",
                        "requiredTags": [],
                        "forbiddenTags": ["Item.Attachment.Magazine.Internal"],
                    }
                ]
            )
        )
        self.assertTrue(
            self.evaluate(
                [
                    {
                        "type": "ComplexAttachmentTags",
                        "requiredTags": [],
                        "forbiddenTags": ["Item.Attachment.Magazine.Internal"],
                    }
                ],
                part_slot_required_tags=[["Item.Attachment.Magazine.Medium"]],
            )
        )


class CompatibilityBuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self.weapon_parent = asset(
            WEAPON_BASE,
            "/Script/Endeavor.CoreGun",
            [
                enum_prop("GunAvoType", "EGunAvoType", "Primary"),
                enum_prop("GunType", "EGunType", "Rifle"),
                enum_prop("GunSubType", "EGunSubType", "Auto"),
                tag_container("GunKitTags", ["Kit.Future", "Kit.Custom"]),
                tag_container("GunKitIgnoreTags", ["Kit.Blocked"]),
                tag_container("ChassisTags", ["Chassis.Heatsink.Advanced"]),
                slots(slot("Item.Attachment.Stock")),
            ],
        )
        self.weapon = asset(
            WEAPON,
            WEAPON_BASE,
            [
                # This array replaces, rather than extends, the parent's stock slot.
                slots(
                    slot("Item.Attachment.Magazine.Internal", display_name="Internal Magazine"),
                    slot("Item.Attachment.Barrel"),
                    slot("Item.Attachment.Armature"),
                    slot("Item.Attachment.Muzzle.Small", appearance_only=True),
                    slot("Item.Attachment.Mod", level=2),
                    slot("Item.Attachment.Overclock", level=5),
                )
            ],
        )
        self.attachment_parent = asset(
            ATTACHMENT_BASE,
            "/Script/Endeavor.GunModDef",
            [tag_container("Tags", ["Item.Attachment"]), rules(rule("Default"))],
        )
        self.internal_parent = asset(
            INTERNAL_BASE,
            ATTACHMENT_BASE,
            [
                tag_container("Tags", ["Item.Attachment.Magazine.Internal"]),
                rules(rule("ChassisTags", required=["Chassis.Heatsink"])),
            ],
        )
        self.internal = asset(INTERNAL, INTERNAL_BASE, [])
        self.trait = asset(
            TRAIT,
            ATTACHMENT_BASE,
            [
                tag_container("Tags", ["Item.Attachment.Mod"]),
                rules(
                    rule(
                        "ComplexAttachmentTags",
                        forbidden=["Item.Attachment.Magazine.Internal"],
                    )
                ),
            ],
        )
        self.augment = asset(
            AUGMENT,
            ATTACHMENT_BASE,
            [
                tag_container("Tags", ["Item.Attachment.Overclock.High"]),
                rules(rule("GunTypeAndSubType", gun_type="Rifle", gun_sub_type="Auto")),
            ],
        )

    def test_build_materializes_parent_properties_and_exact_slot_compatibility(self) -> None:
        records = [
            record(WEAPON, "weapon"),
            record(INTERNAL, "mod"),
            record(TRAIT, "trait"),
            record(AUGMENT, "augment"),
        ]
        original = copy.deepcopy(records)
        result = build_weapon_compatibility(
            records=records,
            candidate_assets=[self.weapon, self.internal, self.trait, self.augment],
            parent_assets=[self.weapon_parent, self.attachment_parent, self.internal_parent],
        )

        self.assertEqual(records, original, "the pure builder must not mutate caller records")
        by_id = {item["id"]: item for item in result.records}
        weapon = by_id[WEAPON]["compatibility"]
        self.assertEqual(weapon["status"], "resolved")
        self.assertEqual(weapon["collectionCategory"], "rifle")
        self.assertEqual(weapon["weaponRole"], "primary")
        self.assertEqual(weapon["weaponSubType"], "auto")
        self.assertEqual(weapon["kitTags"], ["Kit.Custom", "Kit.Future"])
        self.assertEqual(weapon["kitIgnoreTags"], ["Kit.Blocked"])
        self.assertEqual(weapon["propertyOwners"]["GunKitTags"], WEAPON_BASE)
        self.assertEqual(weapon["propertyOwners"]["GunKitIgnoreTags"], WEAPON_BASE)
        self.assertEqual(weapon["propertyOwners"]["GunType"], WEAPON_BASE)
        self.assertEqual(weapon["propertyOwners"]["PartSlots"], WEAPON)
        self.assertEqual([item["kind"] for item in weapon["slots"]], [
            "component",
            "component",
            "component",
            "trait",
            "augment",
        ])
        self.assertEqual([item["index"] for item in weapon["slots"]], [0, 1, 2, 4, 5])
        self.assertNotIn("Item.Attachment.Stock", {
            tag for item in weapon["slots"] for tag in item["requiredModTags"]
        })
        self.assertEqual(weapon["slots"][0]["compatibleIds"], [INTERNAL])
        self.assertEqual(weapon["compatibleModIds"], [INTERNAL])
        self.assertEqual(weapon["compatibleTraitIds"], [])
        self.assertEqual(weapon["compatibleAugmentIds"], [AUGMENT])
        self.assertEqual(by_id[INTERNAL]["compatibility"]["compatibleWeaponIds"], [WEAPON])
        self.assertEqual(by_id[TRAIT]["compatibility"]["compatibleWeaponIds"], [])
        self.assertEqual(by_id[AUGMENT]["compatibility"]["compatibleWeaponIds"], [WEAPON])
        self.assertEqual(result.coverage["compatibilityPairs"], 2)
        self.assertEqual(result.diagnostics["layoutAnomalies"], [])

    def test_missing_blueprint_parent_is_unresolved_not_guessed(self) -> None:
        missing_parent_mod = asset(
            "/Game/Test/Attachments/MissingParentMod",
            "/Game/Test/Attachments/NotExtracted",
            [],
        )
        result = build_weapon_compatibility(
            records=[
                record(WEAPON, "weapon"),
                record("/Game/Test/Attachments/MissingParentMod", "mod"),
            ],
            candidate_assets=[self.weapon, missing_parent_mod],
            parent_assets=[self.weapon_parent],
        )
        by_id = {item["id"]: item for item in result.records}
        unresolved = by_id["/Game/Test/Attachments/MissingParentMod"]["compatibility"]
        self.assertEqual(unresolved["status"], "unresolved")
        self.assertNotIn("compatibleWeaponIds", unresolved)
        self.assertEqual(by_id[WEAPON]["compatibility"]["compatibleModIds"], [])
        self.assertEqual(len(result.diagnostics["unresolved"]), 1)

    def test_missing_weapon_parent_does_not_publish_guessed_kit_tags(self) -> None:
        result = build_weapon_compatibility(
            records=[record(WEAPON, "weapon")],
            candidate_assets=[self.weapon],
        )

        compatibility = result.records[0]["compatibility"]
        self.assertEqual(compatibility["status"], "unresolved")
        self.assertNotIn("kitTags", compatibility)
        self.assertNotIn("kitIgnoreTags", compatibility)
        self.assertIn(
            f"Blueprint parent asset was unavailable: {WEAPON_BASE}",
            compatibility["reasons"],
        )


if __name__ == "__main__":
    unittest.main()
