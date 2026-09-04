from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from afe2_catalogue.semantic_assets import (  # noqa: E402
    _character_class_display_icon_packages,
    _chip_visual_family,
    _effect_definition,
    _import_parent_identity,
    _member_map,
    _perk_visual_classification,
    _resolve_chip_visual_families,
    apply_semantic_evidence,
    normalize_semantic_document,
)


PRIMING = (
    "/Game/Blueprints/Venus_Weapons/Attachments/Magazines/"
    "Magazines_Tubular/Avo_Magazine_Tubular_Priming"
)
EFFECT = "/Game/Blueprints/Gameplay/GameplayEffects/AvoMods/Avo_Weapon_ReloadSpeed"
ICON = "/Game/UI/Textures/Avo_OverlockIcons/T_UI_Icon_Overlock_High_Grey-MarketRounds"
BASE = "/Game/Blueprints/Venus_Weapons/Attachments/Magazines/Avo_BaseMagazine_Tubular"
WEAPON = "/Game/Blueprints/Venus_Weapons/Guns/Rifles/Venus_Rifle_Auto_M41A2"
MONDO = "/Game/Blueprints/Venus_Weapons/Guns/Rifles/Venus_Rifle_Auto_HerkMondo"
KRAMER_ICON = "/Game/UI/Textures/Avo_Weapons/Icon_Venus_Rifle_Auto_Kramer"
MONDO_SILHOUETTE = "/Game/UI/Textures/Avo_Weapons/Sil/Icon_Sil_Venus_Rifle_Auto_HerkMondo"
DEFAULT_PLAYER_CHARACTER = "/Game/Blueprints/Character/DefaultPlayerCharacter"


def prop(name: str, value: object, type_name: str = "ObjectPropertyData", **extra: object) -> dict[str, object]:
    return {"$type": f"UAssetAPI.PropertyTypes.{type_name}, UAssetAPI", "Name": name, "Value": value, **extra}


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


def tag_container(name: str, tags: list[str]) -> dict[str, object]:
    return prop(
        name,
        [prop(name, tags, "Structs.GameplayTagContainerPropertyData")],
        "Structs.StructPropertyData",
    )


def item_part_slot(
    required_tags: list[str],
    slot_tags: list[str],
) -> dict[str, object]:
    return prop(
        "PartSlots",
        [
            tag_container("RequiredModTags", required_tags),
            tag_container("SlotTags", slot_tags),
        ],
        "Structs.StructPropertyData",
        StructType="ModSlotDef",
    )


def default_player_item_slot_asset() -> dict[str, object]:
    slots = [
        item_part_slot(
            ["Ability.Consumable.InventoryType.Unlimited"],
            ["Slot.Consumable.Mission"],
        ),
        item_part_slot(
            [
                "Ability.Consumable.Tool",
                "Ability.Consumable.InventoryType.Minor",
                "Ability.Consumable.Combat",
            ],
            ["Slot.Consumable.Custom"],
        ),
        item_part_slot(
            ["Ability.Consumable.CombatUnique"],
            ["Slot.Consumable.Mission"],
        ),
        item_part_slot(
            [
                "Ability.Consumable.InventoryType.Major",
                "Ability.Consumable.Sensor",
                "Ability.Consumable.Ammo",
            ],
            ["Slot.Consumable.Custom"],
        ),
        item_part_slot(
            ["Ability.Consumable.Health", "Ability.Consumable.Wounds"],
            ["Slot.Consumable.Mission"],
        ),
    ]
    return {
        "packagePath": DEFAULT_PLAYER_CHARACTER,
        "memberPath": "AFE2/Content/Blueprints/Character/DefaultPlayerCharacter.uasset",
        "engineVersion": "VER_UE4_27",
        "imports": [],
        "exports": [
            {
                "objectName": "Default__DefaultPlayerCharacter_C",
                "data": [
                    prop(
                        "PartSlots",
                        slots,
                        "Objects.ArrayPropertyData",
                        ArrayType="StructProperty",
                    )
                ],
            }
        ],
    }


def possible_shape(width: int, height: int, mask: list[int]) -> dict[str, object]:
    shape = prop(
        "PossibleShapes",
        [
            prop(
                "CollisionMask",
                [prop(str(index), value, "Objects.IntPropertyData") for index, value in enumerate(mask)],
                "Objects.ArrayPropertyData",
            ),
            prop("Width", width, "Objects.IntPropertyData"),
            prop("Height", height, "Objects.IntPropertyData"),
        ],
        "Structs.StructPropertyData",
    )
    return prop("PossibleShapes", [shape], "Objects.ArrayPropertyData")


def localized_text(name: str, value: str | None) -> dict[str, object]:
    return prop(
        name,
        "LOCALIZATION-KEY" if value is not None else None,
        "Objects.TextPropertyData",
        CultureInvariantString=value,
        HistoryType="Base" if value is not None else "None",
    )


def conditional_stat_line(
    text_value: str | None,
    number: object,
    *,
    display_type: str,
    result: str,
) -> dict[str, object]:
    return prop(
        "StatList",
        [
            localized_text("StatText", text_value),
            prop(
                "ModDisplayType",
                f"EStatDisplayType::{display_type}",
                "Objects.EnumPropertyData",
            ),
            prop("StatNumber", number, "Objects.FloatPropertyData"),
            prop(
                "StatResult",
                f"EComparableStatSign::{result}",
                "Objects.EnumPropertyData",
            ),
        ],
        "Structs.StructPropertyData",
    )


def conditional_description_group(
    condition: str | None,
    lines: list[dict[str, object]],
) -> dict[str, object]:
    return prop(
        "ConditionalModDescriptions",
        [
            localized_text("ConditionText", condition),
            prop("StatList", lines, "Objects.ArrayPropertyData"),
        ],
        "Structs.StructPropertyData",
    )


def conditional_descriptions(
    groups: list[dict[str, object]],
) -> dict[str, object]:
    return prop(
        "ConditionalModDescriptions",
        groups,
        "Objects.ArrayPropertyData",
    )


def candidate_asset() -> dict[str, object]:
    return {
        "packagePath": PRIMING,
        "memberPath": f"AFE2/Content/{PRIMING[6:]}.uasset",
        "engineVersion": "VER_UE4_27",
        "imports": [
            {"objectName": "Avo_Weapon_ReloadSpeed_C", "outerIndex": -2},
            {"objectName": EFFECT, "outerIndex": 0},
            {"objectName": "T_UI_Icon_Overlock_High_Grey-MarketRounds", "outerIndex": -4},
            {"objectName": ICON, "outerIndex": 0},
            {"objectName": "Avo_BaseMagazine_Tubular_C", "outerIndex": -6},
            {"objectName": BASE, "outerIndex": 0},
        ],
        "exports": [
            {
                "objectName": "Avo_Magazine_Tubular_Priming_C",
                "superIndex": -5,
                "data": [],
            },
            {
                "objectName": "Default__Avo_Magazine_Tubular_Priming_C",
                "data": [
                    prop(
                        "Effects",
                        [
                            prop(
                                "Effects",
                                [
                                    prop("EffectDef", -1),
                                    prop("Magnitude", 1.2000000476837158, "FloatPropertyData"),
                                    prop(
                                        "bInterpretTableLookupAsPercent",
                                        True,
                                        "BoolPropertyData",
                                    ),
                                    prop(
                                        "bNormalizePercentForEffectMagnitude",
                                        False,
                                        "BoolPropertyData",
                                    ),
                                    prop(
                                        "bEnableApplyToGunsInsteadCheckbox",
                                        False,
                                        "BoolPropertyData",
                                    ),
                                    prop(
                                        "bApplyToGunsInstead",
                                        False,
                                        "BoolPropertyData",
                                    ),
                                    prop("bVisibleOnUI", True, "BoolPropertyData"),
                                ],
                                "StructPropertyData",
                            )
                        ],
                        "ArrayPropertyData",
                    ),
                    {
                        "Name": "Name",
                        "$type": "TextPropertyData",
                        "CultureInvariantString": "Priming Chamber",
                        "HistoryType": "Base",
                        "Value": "HASH-NOT-DISPLAY-TEXT",
                    },
                    {
                        "Name": "Description",
                        "$type": "TextPropertyData",
                        "CultureInvariantString": None,
                        "HistoryType": "None",
                        "Value": None,
                    },
                    prop(
                        "Icon",
                        [prop("ResourceObject", -3)],
                        "StructPropertyData",
                    ),
                ],
            },
        ],
    }


def effect_asset() -> dict[str, object]:
    attribute = prop(
        "Attribute",
        [
            prop("AttributeName", "TimeToReload", "StrPropertyData"),
            prop(
                "Attribute",
                {"Path": ["TimeToReload"], "ResolvedOwner": -1},
                "FieldPathPropertyData",
            ),
        ],
        "StructPropertyData",
    )
    magnitude = prop(
        "ModifierMagnitude",
        [
            prop(
                "MagnitudeCalculationType",
                "EGameplayEffectMagnitudeCalculation::SetByCaller",
                "EnumPropertyData",
            )
        ],
        "StructPropertyData",
    )
    modifier = prop(
        "Modifiers",
        [
            attribute,
            {
                "Name": "ModifierOp",
                "$type": "BytePropertyData",
                "EnumValue": "EGameplayModOp::Division",
            },
            magnitude,
        ],
        "StructPropertyData",
    )
    return {
        "packagePath": EFFECT,
        "memberPath": f"AFE2/Content/{EFFECT[6:]}.uasset",
        "engineVersion": "VER_UE4_27",
        "imports": [
            {"objectName": "GunGameplayAttributes", "outerIndex": -2},
            {"objectName": "/Script/Endeavor", "outerIndex": 0},
        ],
        "exports": [
            {
                "objectName": "Default__Avo_Weapon_ReloadSpeed_C",
                "data": [
                    prop(
                        "DurationPolicy",
                        "EGameplayEffectDurationType::Infinite",
                        "EnumPropertyData",
                    ),
                    prop("Modifiers", [modifier], "ArrayPropertyData"),
                ],
            }
        ],
    }


def scalable_effect_asset() -> dict[str, object]:
    attribute = prop(
        "Attribute",
        [
            prop("AttributeName", "RecoilMultiplier", "StrPropertyData"),
            prop(
                "Attribute",
                {"Path": ["RecoilMultiplier"], "ResolvedOwner": -1},
                "FieldPathPropertyData",
            ),
        ],
        "StructPropertyData",
    )
    scalable_float = prop(
        "ScalableFloatMagnitude",
        [
            prop("Value", 0.800000011920929, "FloatPropertyData"),
            prop(
                "Curve",
                [
                    prop("CurveTable", 0, "ObjectPropertyData"),
                    prop("RowName", "None", "NamePropertyData"),
                ],
                "StructPropertyData",
            ),
        ],
        "StructPropertyData",
    )
    modifier = prop(
        "Modifiers",
        [
            attribute,
            prop(
                "ModifierOp",
                "EGameplayModOp::Multiplicitive",
                "BytePropertyData",
                EnumValue="EGameplayModOp::Multiplicitive",
            ),
            # This legacy sibling is zero in the cooked assets and is not the
            # GameplayEffectModifierMagnitude used by the client.
            prop(
                "Magnitude",
                [prop("Value", 0.0, "FloatPropertyData")],
                "StructPropertyData",
            ),
            prop(
                "ModifierMagnitude",
                [
                    prop(
                        "MagnitudeCalculationType",
                        "EGameplayEffectMagnitudeCalculation::ScalableFloat",
                        "EnumPropertyData",
                    ),
                    scalable_float,
                ],
                "StructPropertyData",
            ),
        ],
        "StructPropertyData",
    )
    return {
        "packagePath": "/Game/Test/Avo_Attachment_Custom_Gun_GE",
        "imports": [
            {"objectName": "GunGameplayAttributes", "outerIndex": -2},
            {"objectName": "/Script/Endeavor", "outerIndex": 0},
        ],
        "exports": [
            {
                "objectName": "Default__Avo_Attachment_Custom_Gun_GE_C",
                "data": [prop("Modifiers", [modifier], "ArrayPropertyData")],
            }
        ],
    }


def attribute_metadata_asset() -> dict[str, object]:
    return {
        "packagePath": "/Game/Design/AttributeMetaData/AttributeMetaData",
        "memberPath": "AFE2/Content/Design/AttributeMetaData/AttributeMetaData.uasset",
        "exports": [
            {
                "objectName": "AttributeMetaData",
                "data": [],
                "table": {
                    "Data": [
                        prop(
                            "13",
                            [
                                prop(
                                    "AttributeName",
                                    "GunGameplayAttributes.TimeToReload",
                                    "StrPropertyData",
                                ),
                                {
                                    "Name": "AttributeDisplayName",
                                    "$type": "TextPropertyData",
                                    "CultureInvariantString": "Reload Time",
                                    "HistoryType": "Base",
                                    "Value": "13_AttributeDisplayName",
                                },
                                prop(
                                    "DisplayType",
                                    "EComparableStatDisplayType::Time",
                                    "EnumPropertyData",
                                ),
                                prop(
                                    "ModOp",
                                    "EComparableStatOperator::Divide",
                                    "EnumPropertyData",
                                ),
                                prop(
                                    "Sign",
                                    "EComparableStatSign::LowerIsBetter",
                                    "EnumPropertyData",
                                ),
                                prop("SortOrder", 13, "IntPropertyData"),
                            ],
                            "StructPropertyData",
                        )
                    ]
                },
            }
        ],
    }


class SemanticNormalizationTests(unittest.TestCase):
    def test_effect_definition_reads_comparison_stat_ui_override(self) -> None:
        asset = deepcopy(effect_asset())
        asset["exports"][0]["data"].append(prop("UIData", 2, "ObjectPropertyData"))
        asset["exports"].append(
            {
                "objectName": "CoreGameplayEffect_OverrideComparisonStat_0",
                "data": [
                    prop(
                        "OverrideDisplayStatTag",
                        [prop("TagName", "Stats.Combined.Handling", "NamePropertyData")],
                        "StructPropertyData",
                    )
                ],
            }
        )

        definition = _effect_definition(asset)

        self.assertEqual(
            definition["overrideDisplayStatTag"],
            "Stats.Combined.Handling",
        )
        self.assertEqual(
            definition["overrideDisplayStatTagEvidence"],
            (
                "Default__Avo_Weapon_ReloadSpeed_C.UIData -> "
                "CoreGameplayEffect_OverrideComparisonStat_0."
                "OverrideDisplayStatTag"
            ),
        )

    def test_effect_definition_reads_modifier_scalable_float_magnitude(self) -> None:
        definition = _effect_definition(scalable_effect_asset())

        self.assertEqual(definition["status"], "parsed")
        self.assertEqual(
            definition["modifiers"],
            [
                {
                    "attribute": "RecoilMultiplier",
                    "attributeOwner": "GunGameplayAttributes",
                    "evidence": "Modifiers[0]",
                    "magnitudeCalculationType": "scalablefloat",
                    "magnitudeCalculationTypeRaw": (
                        "EGameplayEffectMagnitudeCalculation::ScalableFloat"
                    ),
                    "operation": "multiply",
                    "operationRaw": "EGameplayModOp::Multiplicitive",
                    "qualifiedAttribute": (
                        "GunGameplayAttributes.RecoilMultiplier"
                    ),
                    "scalableFloatMagnitude": {
                        "curveRowName": None,
                        "curveTablePackagePath": None,
                        "value": 0.8,
                    },
                }
            ],
        )

    def test_perk_visual_classification_normalizes_serialized_restrictions(self) -> None:
        classification = _perk_visual_classification(
            export_name="Default__Perk_Future_C",
            parent_class_path="/Script/Endeavor.ModChipDef",
            raw_restriction_type="EModChipRestrictionType::Kit",
            raw_role_restriction="EClassRole::Technician",
            role_restriction_export_name="Default__Perk_Future_C",
        )

        self.assertEqual(
            classification,
            {
                "evidence": {
                    "property": "Default__Perk_Future_C.RestrictionType",
                    "roleRestrictionProperty": (
                        "Default__Perk_Future_C.RoleRestriction"
                    ),
                    "source": "serialized-enum",
                    "valueRaw": "EModChipRestrictionType::Kit",
                },
                "restrictionType": "kit",
                "restrictionTypeRaw": "EModChipRestrictionType::Kit",
                "roleRestrictionRaw": "EClassRole::Technician",
                "status": "resolved",
            },
        )

    def test_perk_visual_classification_infers_native_none_default(self) -> None:
        classification = _perk_visual_classification(
            export_name="Default__Perk_Future_C",
            parent_class_path="/Script/Endeavor.ModChipDef",
            raw_restriction_type=None,
            raw_role_restriction=None,
            role_restriction_export_name="Default__Perk_Future_C",
        )

        self.assertEqual(classification["restrictionType"], "none")
        self.assertEqual(classification["status"], "inferred")
        self.assertEqual(
            classification["evidence"]["source"],
            "native-default-inferred",
        )

    def test_perk_visual_classification_preserves_unknown_future_enum(self) -> None:
        classification = _perk_visual_classification(
            export_name="Default__Perk_Future_C",
            parent_class_path="/Script/Endeavor.ModChipDef",
            raw_restriction_type="EModChipRestrictionType::Faction",
            raw_role_restriction=None,
            role_restriction_export_name="Default__Perk_Future_C",
        )

        self.assertEqual(
            classification["restrictionTypeRaw"],
            "EModChipRestrictionType::Faction",
        )
        self.assertEqual(
            classification["status"],
            "unresolved-restriction-type",
        )
        self.assertNotIn("restrictionType", classification)

    def test_semantic_perk_record_and_candidate_publish_visual_classification(self) -> None:
        package = "/Game/Synthetic/Perks/Perk_VisualClassification"
        asset = {
            "packagePath": package,
            "memberPath": f"AFE2/Content/{package[6:]}.uasset",
            "engineVersion": "VER_UE4_27",
            "imports": [
                {"objectName": "ModChipDef", "outerIndex": -2},
                {"objectName": "/Script/Endeavor", "outerIndex": 0},
            ],
            "exports": [
                {
                    "objectName": "Perk_VisualClassification_C",
                    "superIndex": -1,
                    "data": [],
                },
                {
                    "objectName": "Default__Perk_VisualClassification_C",
                    "data": [
                        prop(
                            "RestrictionType",
                            "EModChipRestrictionType::Role",
                            "Objects.EnumPropertyData",
                        ),
                        prop(
                            "RoleRestriction",
                            "EPlayerRole::Support",
                            "Objects.EnumPropertyData",
                        ),
                    ],
                },
            ],
        }
        result = normalize_semantic_document(
            candidates=[{"id": package, "kind": "perk", "packagePath": package}],
            candidate_assets=[asset],
            candidate_failures=[],
            effect_assets=[],
            dependency_failures=[],
            icon_metadata=[],
            icon_bytes={},
            source_fingerprint="sha256:fixture",
        )
        classification = result.document["records"][0]["visualClassification"]

        self.assertEqual(classification["restrictionType"], "role")
        self.assertEqual(
            classification["roleRestrictionRaw"],
            "EPlayerRole::Support",
        )
        candidates = {"records": [{"id": package, "kind": "perk"}]}
        apply_semantic_evidence(candidates=candidates, semantic=result.document)
        self.assertEqual(
            candidates["records"][0]["visualClassification"],
            classification,
        )

    def test_chip_visual_family_uses_serialized_enums_and_native_default(self) -> None:
        modifier = _chip_visual_family(
            export_name="Default__FutureModifier_C",
            raw_perk_type="EModChipType::Modifier",
            raw_role=None,
            raw_replacer_type=None,
        )
        replacer = _chip_visual_family(
            export_name="Default__FutureShieldSwap_C",
            raw_perk_type=None,
            raw_role="EClassAbilityType::Shield",
            raw_replacer_type="EReplacerType::ClassAbility4",
        )
        standalone_replacer = _chip_visual_family(
            export_name="Default__FutureInheritedRoleSwap_C",
            raw_perk_type=None,
            raw_role=None,
            raw_replacer_type="EReplacerType::ClassAbility4",
        )
        core = _chip_visual_family(
            export_name="Default__FutureCore_C",
            raw_perk_type=None,
            raw_role=None,
            raw_replacer_type=None,
        )
        unknown = _chip_visual_family(
            export_name="Default__FutureUnknown_C",
            raw_perk_type="EModChipType::Experimental",
            raw_role=None,
            raw_replacer_type=None,
        )

        self.assertEqual((modifier["family"], modifier["status"]), ("modifier", "resolved"))
        self.assertEqual((replacer["family"], replacer["status"]), ("replacer", "resolved"))
        self.assertEqual(standalone_replacer["family"], "replacer")
        self.assertEqual(core["status"], "inheritance-pending")
        self.assertEqual(unknown["status"], "unresolved-family")
        self.assertNotIn("family", unknown)

        parent = {
            "chipVisual": core,
            "id": "/Game/Future/Parent",
            "kind": "perk",
            "packagePath": "/Game/Future/Parent",
            "parentClassPath": "/Script/AFE2.ModChipDef",
        }
        child = {
            "chipVisual": {"status": "inheritance-pending"},
            "id": "/Game/Future/Child",
            "kind": "perk",
            "packagePath": "/Game/Future/Child",
            "parentPackagePath": "/Game/Future/Parent",
        }
        _resolve_chip_visual_families([child, parent])
        self.assertEqual((parent["chipVisual"]["family"], parent["chipVisual"]["status"]), ("core", "inferred"))
        self.assertEqual((child["chipVisual"]["family"], child["chipVisual"]["status"]), ("core", "inferred"))

        native_asset = {
            "imports": [
                {"objectName": "ModChipDef", "outerIndex": -2},
                {"objectName": "/Script/AFE2", "outerIndex": 0},
            ]
        }
        self.assertEqual(
            _import_parent_identity(native_asset, -1),
            "/Script/AFE2.ModChipDef",
        )

        missing_parent = {
            "chipVisual": {"status": "inheritance-pending"},
            "id": "/Game/Future/MissingParent",
            "kind": "perk",
            "packagePath": "/Game/Future/MissingParent",
            "parentPackagePath": "/Game/Future/NotExtracted",
        }
        _resolve_chip_visual_families([missing_parent])
        self.assertEqual(missing_parent["chipVisual"]["status"], "unresolved-family")

    def ability_role_record(self, raw_role: str) -> dict[str, object]:
        package = f"/Game/Synthetic/Perks/Perk_{raw_role}"
        asset = {
            "packagePath": package,
            "memberPath": f"AFE2/Content/{package[6:]}.uasset",
            "engineVersion": "VER_UE4_27",
            "imports": [],
            "exports": [
                {
                    "objectName": f"Default__Perk_{raw_role}_C",
                    "data": [
                        prop(
                            "ClassAbilityType",
                            f"EClassAbilityType::{raw_role}",
                            "Objects.EnumPropertyData",
                        )
                    ],
                }
            ],
        }
        result = normalize_semantic_document(
            candidates=[{"id": package, "kind": "perk", "packagePath": package}],
            candidate_assets=[asset],
            candidate_failures=[],
            effect_assets=[],
            dependency_failures=[],
            icon_metadata=[],
            icon_bytes={},
            source_fingerprint="sha256:fixture",
        )
        return result.document["records"][0]

    def role_receptacle_fixture(self):
        source_kit = (
            "/Game/Blueprints/Avocado_Classes/ClassUnlocks/KitUnlock_Artillerist"
        )
        importing_kit = (
            "/Game/Blueprints/Avocado_Classes/ClassUnlocks/KitUnlock_Bulwark"
        )
        future_native_kit = (
            "/Game/Blueprints/Avocado_Classes/ClassUnlocks/KitUnlock_Warden"
        )
        source_class = (
            "/Game/Blueprints/Avocado_Classes/Artillerist/Player_Artillerist"
        )
        importing_class = (
            "/Game/Blueprints/Avocado_Classes/Bulwark/Player_Bulwark"
        )
        future_native_class = (
            "/Game/Blueprints/Avocado_Classes/Warden/Player_Warden"
        )
        source_ability = (
            "/Game/Blueprints/Avocado_Classes/Artillerist/Perks/RallyPoint/"
            "Perk_Artillerist_RallyPoint_Base_Tactical"
        )
        cross_kit_wrapper = (
            "/Game/Blueprints/Avocado_Classes/Bulwark/Perks/RallyPoint/"
            "Perk_Bulwark_RallyPoint_Replacer_Tactical"
        )
        importing_native_slot = (
            "/Game/Blueprints/Avocado_Classes/Bulwark/Perks/"
            "Perk_Bulwark_Ultimate"
        )
        future_native_ability = (
            "/Game/Blueprints/Avocado_Classes/Warden/Perks/Aegis/"
            "Perk_Warden_Aegis_Base_Ultimate"
        )
        rally_gameplay = "/Game/Synthetic/Abilities/GA_Artillerist_RallyPoint"
        slot_gameplay = "/Game/Synthetic/Abilities/GA_Bulwark_Ultimate_Dummy"
        aegis_gameplay = "/Game/Synthetic/Abilities/GA_Warden_Aegis"

        def kit_asset(package: str, character_class: str) -> dict[str, object]:
            return {
                "packagePath": package,
                "memberPath": f"AFE2/Content/{package[6:]}.uasset",
                "engineVersion": "VER_UE4_27",
                "imports": [
                    {"objectName": character_class, "outerIndex": 0},
                    {
                        "objectName": f"{character_class.rsplit('/', 1)[-1]}_C",
                        "outerIndex": -1,
                    },
                ],
                "exports": [
                    {
                        "objectName": f"Default__{package.rsplit('/', 1)[-1]}_C",
                        "data": [prop("CharacterClass", -2)],
                    }
                ],
            }

        def ability_asset(
            package: str,
            *,
            role: str,
            restricted_class: str,
            gameplay_ability: str,
            origin_class: str | None = None,
            wrapper: bool = False,
            pure_role_receptacle: bool = False,
        ) -> dict[str, object]:
            data = [
                prop(
                    "ClassAbilityType",
                    f"EClassAbilityType::{role}",
                    "Objects.EnumPropertyData",
                ),
                soft_object("KitRestriction", restricted_class),
                soft_object(
                    "GrantedAbilityOverride" if wrapper else "GrantedAbility",
                    gameplay_ability,
                ),
            ]
            if origin_class is not None:
                data.append(soft_object("OriginKit", origin_class))
            if wrapper:
                data.append(
                    prop(
                        "ReplacerType",
                        "EReplacerType::ClassAbility2",
                        "Objects.EnumPropertyData",
                    )
                )
            if pure_role_receptacle:
                data.extend(
                    [
                        tag_container(
                            "ModifierCompatability",
                            [f"Item.Chip.AbilityType.{role}"],
                        ),
                        tag_container("Tags", ["Item.Chip.Core.Active"]),
                    ]
                )
            return {
                "packagePath": package,
                "memberPath": f"AFE2/Content/{package[6:]}.uasset",
                "engineVersion": "VER_UE4_27",
                "imports": [],
                "exports": [
                    {
                        "objectName": f"Default__{package.rsplit('/', 1)[-1]}_C",
                        "data": data,
                    }
                ],
            }

        candidates = [
            {"id": source_kit, "kind": "kit", "packagePath": source_kit},
            {"id": importing_kit, "kind": "kit", "packagePath": importing_kit},
            {
                "id": future_native_kit,
                "kind": "kit",
                "packagePath": future_native_kit,
            },
            *[
                {"id": package, "kind": "perk", "packagePath": package}
                for package in (
                    source_ability,
                    cross_kit_wrapper,
                    importing_native_slot,
                    future_native_ability,
                )
            ],
        ]
        result = normalize_semantic_document(
            candidates=candidates,
            candidate_assets=[
                kit_asset(source_kit, source_class),
                kit_asset(importing_kit, importing_class),
                kit_asset(future_native_kit, future_native_class),
                ability_asset(
                    source_ability,
                    role="Tactical",
                    restricted_class=source_class,
                    gameplay_ability=rally_gameplay,
                    origin_class=source_class,
                ),
                ability_asset(
                    cross_kit_wrapper,
                    role="Tactical",
                    restricted_class=importing_class,
                    gameplay_ability=rally_gameplay,
                    origin_class=source_class,
                    wrapper=True,
                    pure_role_receptacle=True,
                ),
                ability_asset(
                    importing_native_slot,
                    role="Ultimate",
                    restricted_class=importing_class,
                    gameplay_ability=slot_gameplay,
                    pure_role_receptacle=True,
                ),
                ability_asset(
                    future_native_ability,
                    role="Ultimate",
                    restricted_class=future_native_class,
                    gameplay_ability=aegis_gameplay,
                    pure_role_receptacle=True,
                ),
            ],
            candidate_failures=[],
            effect_assets=[],
            dependency_failures=[],
            icon_metadata=[],
            icon_bytes={},
            source_fingerprint="sha256:fixture",
        )
        ids = {
            "sourceAbility": source_ability,
            "sourceKit": source_kit,
            "importingKit": importing_kit,
            "importingNativeSlot": importing_native_slot,
            "crossKitWrapper": cross_kit_wrapper,
            "futureNativeAbility": future_native_ability,
            "futureNativeKit": future_native_kit,
        }
        return result, ids

    def test_ultimate_class_ability_is_player_facing_primary(self) -> None:
        record = self.ability_role_record("Ultimate")

        self.assertEqual(record["ability"]["role"], "primary")
        self.assertEqual(
            record["ability"]["roleRaw"],
            "EClassAbilityType::Ultimate",
        )

    def test_passive_class_ability_remains_player_facing_passive(self) -> None:
        record = self.ability_role_record("Passive")

        self.assertEqual(record["ability"]["role"], "passive")
        self.assertEqual(
            record["ability"]["roleRaw"],
            "EClassAbilityType::Passive",
        )

    def test_unknown_future_ability_role_is_retained_as_unresolved_evidence(self) -> None:
        record = self.ability_role_record("Defensive")

        self.assertEqual(record["ability"]["status"], "unresolved-role")
        self.assertEqual(
            record["ability"]["roleRaw"],
            "EClassAbilityType::Defensive",
        )
        self.assertNotIn("role", record["ability"])

    def test_importing_kit_native_role_receptacle_is_a_placeholder(self) -> None:
        result, ids = self.role_receptacle_fixture()
        records = {item["id"]: item for item in result.document["records"]}
        concept_ids = {item["id"] for item in result.document["kitAbilities"]}

        slot = records[ids["importingNativeSlot"]]
        self.assertTrue(slot["ability"]["placeholder"])
        self.assertNotIn(ids["importingNativeSlot"], concept_ids)
        self.assertEqual(result.document["coverage"]["kitAbilityPlaceholders"], 1)
        self.assertEqual(
            records[ids["importingKit"]]["abilityPerkIdsByRole"]["primary"],
            [],
        )

    def test_non_importing_future_kit_role_receptacle_fails_open(self) -> None:
        result, ids = self.role_receptacle_fixture()
        records = {item["id"]: item for item in result.document["records"]}
        concepts = {item["id"]: item for item in result.document["kitAbilities"]}

        ability = records[ids["futureNativeAbility"]]["ability"]
        self.assertNotIn("placeholder", ability)
        self.assertEqual(
            ability["placeholderResolution"],
            {
                "importingKit": False,
                "pureRoleReceptacle": True,
                "reason": (
                    "only one of the two class-name-independent slot-placeholder "
                    "signals was present; record retained as a selectable ability"
                ),
                "status": "unresolved",
            },
        )
        self.assertEqual(
            concepts[ids["futureNativeAbility"]]["availableToKitIds"],
            [ids["futureNativeKit"]],
        )

    def test_pure_role_cross_kit_wrapper_is_aliased_not_dropped(self) -> None:
        result, ids = self.role_receptacle_fixture()
        records = {item["id"]: item for item in result.document["records"]}
        concepts = {item["id"]: item for item in result.document["kitAbilities"]}

        wrapper = records[ids["crossKitWrapper"]]["ability"]
        self.assertNotIn("placeholder", wrapper)
        self.assertEqual(wrapper["aliasOf"], ids["sourceAbility"])
        self.assertNotIn(ids["crossKitWrapper"], concepts)
        self.assertEqual(
            concepts[ids["sourceAbility"]]["sourceChipIds"],
            [ids["sourceAbility"], ids["crossKitWrapper"]],
        )
        self.assertEqual(
            concepts[ids["sourceAbility"]]["availableToKitIds"],
            [ids["sourceKit"], ids["importingKit"]],
        )

    def test_member_map_skips_other_mounts_and_requires_exact_game_binding(self) -> None:
        index = {
            "packages": [
                {
                    "packagePath": "/Engine/Plugins/Runtime/Example",
                    "chunks": [
                        {
                            "kind": "package",
                            "memberPath": "Engine/Plugins/Runtime/Example.uasset",
                        }
                    ],
                },
                {
                    "packagePath": "/Game/Exact/Asset",
                    "chunks": [
                        {"kind": "package", "memberPath": "AFE2/Content/Exact/ASSET.uasset"}
                    ],
                },
                {
                    "packagePath": "/Game/Wrong/Identity",
                    "chunks": [
                        {"kind": "package", "memberPath": "AFE2/Content/Other/Asset.uasset"}
                    ],
                },
            ]
        }

        self.assertEqual(_member_map(index), {"/Game/Exact/Asset": "AFE2/Content/Exact/ASSET.uasset"})

    def test_default_player_item_slots_publish_only_custom_major_and_minor(self) -> None:
        result = normalize_semantic_document(
            candidates=[],
            candidate_assets=[],
            candidate_failures=[],
            effect_assets=[],
            dependency_failures=[],
            icon_metadata=[],
            icon_bytes={},
            source_fingerprint="sha256:fixture",
            item_slot_assets=[default_player_item_slot_asset()],
        )

        self.assertEqual(result.document["coverage"]["itemSlotSourceAssetsParsed"], 1)
        self.assertEqual(result.document["coverage"]["itemSlots"], 2)
        self.assertEqual(
            [(slot["index"], slot["itemTier"]) for slot in result.document["itemSlots"]],
            [(1, "minor"), (3, "major")],
        )
        minor, major = result.document["itemSlots"]
        self.assertEqual(
            minor["inventoryTypeTag"],
            "Ability.Consumable.InventoryType.Minor",
        )
        self.assertEqual(
            major["inventoryTypeTag"],
            "Ability.Consumable.InventoryType.Major",
        )
        self.assertEqual(minor["slotTags"], ["Slot.Consumable.Custom"])
        self.assertEqual(
            minor["evidence"],
            {
                "engineVersion": "VER_UE4_27",
                "memberPath": (
                    "AFE2/Content/Blueprints/Character/DefaultPlayerCharacter.uasset"
                ),
                "packagePath": DEFAULT_PLAYER_CHARACTER,
                "property": "Default__DefaultPlayerCharacter_C.PartSlots[1]",
                "source": "serialized-uasset",
            },
        )
        serialized = json.dumps(result.document["itemSlots"])
        self.assertNotIn("Unlimited", serialized)
        self.assertNotIn("CombatUnique", serialized)
        self.assertNotIn("Ability.Consumable.Health", serialized)
        self.assertNotIn("LoadoutCount", serialized)

    def test_item_slots_require_exact_inventory_and_custom_slot_tags(self) -> None:
        source = default_player_item_slot_asset()
        part_slots = source["exports"][0]["data"][0]["Value"]
        part_slots.extend(
            [
                item_part_slot(
                    ["Ability.Consumable.InventoryType.Major.Experimental"],
                    ["Slot.Consumable.Custom"],
                ),
                item_part_slot(
                    ["Ability.Consumable.InventoryType.Minor"],
                    ["Slot.Consumable.Mission"],
                ),
                item_part_slot(
                    [
                        "Ability.Consumable.InventoryType.Major",
                        "Ability.Consumable.InventoryType.Minor",
                    ],
                    ["Slot.Consumable.Custom"],
                ),
            ]
        )
        result = normalize_semantic_document(
            candidates=[],
            candidate_assets=[],
            candidate_failures=[],
            effect_assets=[],
            dependency_failures=[],
            icon_metadata=[],
            icon_bytes={},
            source_fingerprint="sha256:fixture",
            item_slot_assets=[source],
        )

        self.assertEqual(
            [(slot["index"], slot["itemTier"]) for slot in result.document["itemSlots"]],
            [(1, "minor"), (3, "major")],
        )

    def normalize(
        self,
        source: dict[str, object] | None = None,
        *,
        kind: str = "mod",
    ):
        png = b"\x89PNG\r\n\x1a\nsynthetic"
        return normalize_semantic_document(
            candidates=[{"id": PRIMING, "kind": kind, "packagePath": PRIMING}],
            candidate_assets=[source or candidate_asset()],
            candidate_failures=[],
            effect_assets=[effect_asset()],
            attribute_metadata_assets=[attribute_metadata_asset()],
            dependency_failures=[],
            icon_metadata=[
                {
                    "packagePath": ICON,
                    "outputName": "priming--fixture.png",
                    "width": 220,
                    "height": 220,
                    "pixelFormat": "PF_B8G8R8A8",
                }
            ],
            icon_bytes={"priming--fixture.png": png},
            source_fingerprint="sha256:fixture",
        )

    def test_priming_uses_current_serialized_text_icon_and_mechanical_effect(self) -> None:
        result = self.normalize()
        record = result.document["records"][0]

        self.assertEqual(record["displayName"], "Priming Chamber")
        self.assertIsNone(record["description"])
        self.assertEqual(record["parentPackagePath"], BASE)
        self.assertEqual(record["icon"]["packagePath"], ICON)
        self.assertEqual(record["icon"]["path"], "icons/priming--fixture.png")
        self.assertEqual(record["effects"][0]["effectPackagePath"], EFFECT)
        self.assertEqual(record["effects"][0]["configuredMagnitude"], 1.2000000476837158)
        self.assertEqual(
            record["effects"][0]["definition"]["modifiers"][0]["qualifiedAttribute"],
            "GunGameplayAttributes.TimeToReload",
        )
        self.assertEqual(
            result.document["attributeMetadata"],
            {
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
        )
        self.assertEqual(result.document["coverage"]["attributeMetadataRows"], 1)
        self.assertEqual(
            record["staticStatLines"],
            [
                {
                    "attribute": "GunGameplayAttributes.TimeToReload",
                    "displayText": "+20.0% Reload Speed",
                    "displayType": "Percent",
                    "displayValue": "+20.0%",
                    "effectPackagePath": EFFECT,
                    "result": "HigherIsBetter",
                    "sortOrder": 13,
                    "statText": "Reload Speed",
                    "statValue": 20.0,
                }
            ],
        )

        stat = record["stats"][0]
        self.assertEqual(stat["expression"], "TimeToReload / 1.2")
        self.assertEqual(stat["operand"], 1.2)
        self.assertEqual(stat["serializedOperand"], 1.2000000476837158)
        self.assertEqual(stat["derived"]["rateIncreasePercent"], 20.0)
        self.assertEqual(stat["derived"]["timeMultiplier"], 0.833333)
        self.assertEqual(stat["derived"]["timeReductionPercent"], 16.666667)
        self.assertNotIn("Attachment_PrimingMagazine", json.dumps(record))
        self.assertNotIn("Priming Magazine", json.dumps(record))

    def test_augment_candidates_receive_player_facing_static_stat_lines(self) -> None:
        result = self.normalize(kind="augment")
        record = result.document["records"][0]

        self.assertEqual(record["kind"], "augment")
        self.assertEqual(
            [line["displayText"] for line in record["staticStatLines"]],
            ["+20.0% Reload Speed"],
        )
        self.assertEqual(result.document["coverage"]["recordsWithStaticStatLines"], 1)

    def test_preserves_short_and_flavor_text_with_explicit_nulls_and_evidence(self) -> None:
        source = deepcopy(candidate_asset())
        default_export = next(
            export
            for export in source["exports"]
            if export["objectName"].startswith("Default__")
        )
        default_export["data"].extend(
            [
                localized_text(
                    "DescriptionShort",
                    "Target chill duration increased.",
                ),
                localized_text("FlavorText", None),
            ]
        )

        result = self.normalize(source)
        record = result.document["records"][0]

        self.assertEqual(
            record["descriptionShort"],
            "Target chill duration increased.",
        )
        self.assertEqual(
            record["descriptionShortEvidence"],
            "Default__Avo_Magazine_Tubular_Priming_C.DescriptionShort",
        )
        self.assertIn("flavorText", record)
        self.assertIsNone(record["flavorText"])
        self.assertEqual(
            record["flavorTextEvidence"],
            "Default__Avo_Magazine_Tubular_Priming_C.FlavorText",
        )

        candidates = {
            "records": [{"id": PRIMING, "kind": "mod", "packagePath": PRIMING}]
        }
        apply_semantic_evidence(candidates=candidates, semantic=result.document)
        enriched = candidates["records"][0]
        self.assertEqual(enriched["descriptionShort"], record["descriptionShort"])
        self.assertIn("flavorText", enriched)
        self.assertIsNone(enriched["flavorText"])

    def test_conditional_mod_descriptions_preserve_authored_ui_groups(self) -> None:
        source = deepcopy(candidate_asset())
        default = next(
            export
            for export in source["exports"]
            if export["objectName"].startswith("Default__")
        )
        default["data"].append(
            conditional_descriptions(
                [
                    conditional_description_group(
                        None,
                        [
                            conditional_stat_line(
                                "Damage Resistance",
                                25.0,
                                display_type="Percent",
                                result="HigherIsBetter",
                            ),
                            conditional_stat_line(
                                "Lasts <Bold>5 seconds</>.",
                                "+0",
                                display_type="None",
                                result="LowerIsBetter",
                            ),
                        ],
                    ),
                    conditional_description_group(
                        "<Bold>On Kill</>:",
                        [
                            conditional_stat_line(
                                "Accuracy",
                                1.5,
                                display_type="Float",
                                result="HigherIsBetter",
                            )
                        ],
                    ),
                ]
            )
        )

        result = normalize_semantic_document(
            candidates=[{"id": PRIMING, "kind": "mod", "packagePath": PRIMING}],
            candidate_assets=[source],
            candidate_failures=[],
            effect_assets=[],
            dependency_failures=[],
            icon_metadata=[],
            icon_bytes={},
            source_fingerprint="sha256:fixture",
        )
        record = result.document["records"][0]

        self.assertEqual(
            record["conditionalDescriptions"],
            [
                {
                    "conditionText": None,
                    "statLines": [
                        {
                            "displayType": "Percent",
                            "result": "HigherIsBetter",
                            "statText": "Damage Resistance",
                            "statValue": 25.0,
                        },
                        {
                            "displayType": "None",
                            "result": "LowerIsBetter",
                            "statText": "Lasts <Bold>5 seconds</>.",
                            "statValue": 0.0,
                        },
                    ],
                },
                {
                    "conditionText": "<Bold>On Kill</>:",
                    "statLines": [
                        {
                            "displayType": "Float",
                            "result": "HigherIsBetter",
                            "statText": "Accuracy",
                            "statValue": 1.5,
                        }
                    ],
                },
            ],
        )
        self.assertEqual(
            record["conditionalDescriptionsEvidence"]["sourcePackagePath"],
            PRIMING,
        )
        self.assertEqual(
            result.document["coverage"]["recordsWithConditionalDescriptions"],
            1,
        )

    def test_conditional_descriptions_inherit_and_empty_child_override_clears(self) -> None:
        parent = {
            "packagePath": BASE,
            "memberPath": f"AFE2/Content/{BASE[6:]}.uasset",
            "imports": [],
            "exports": [
                {
                    "objectName": "Default__Avo_BaseMagazine_Tubular_C",
                    "data": [
                        conditional_descriptions(
                            [
                                conditional_description_group(
                                    "<Bold>On Reload</>:",
                                    [
                                        conditional_stat_line(
                                            "Reload Speed",
                                            10.0,
                                            display_type="Percent",
                                            result="HigherIsBetter",
                                        )
                                    ],
                                )
                            ]
                        )
                    ],
                }
            ],
        }
        inherited = normalize_semantic_document(
            candidates=[{"id": PRIMING, "kind": "mod", "packagePath": PRIMING}],
            candidate_assets=[candidate_asset()],
            candidate_failures=[],
            effect_assets=[],
            dependency_failures=[],
            icon_metadata=[],
            icon_bytes={},
            source_fingerprint="sha256:fixture",
            parent_assets=[parent],
        ).document["records"][0]
        self.assertEqual(
            inherited["conditionalDescriptionsEvidence"]["sourcePackagePath"],
            BASE,
        )
        self.assertEqual(
            inherited["conditionalDescriptions"][0]["statLines"][0]["statText"],
            "Reload Speed",
        )

        overriding_child = deepcopy(candidate_asset())
        overriding_default = next(
            export
            for export in overriding_child["exports"]
            if export["objectName"].startswith("Default__")
        )
        overriding_default["data"].append(
            conditional_descriptions(
                [
                    conditional_description_group(
                        "<Bold>On Hit</>:",
                        [
                            conditional_stat_line(
                                "Accuracy",
                                2,
                                display_type="Integer",
                                result="LowerIsBetter",
                            )
                        ],
                    )
                ]
            )
        )
        overridden = normalize_semantic_document(
            candidates=[{"id": PRIMING, "kind": "mod", "packagePath": PRIMING}],
            candidate_assets=[overriding_child],
            candidate_failures=[],
            effect_assets=[],
            dependency_failures=[],
            icon_metadata=[],
            icon_bytes={},
            source_fingerprint="sha256:fixture",
            parent_assets=[parent],
        ).document["records"][0]
        self.assertEqual(len(overridden["conditionalDescriptions"]), 1)
        self.assertEqual(
            overridden["conditionalDescriptions"][0],
            {
                "conditionText": "<Bold>On Hit</>:",
                "statLines": [
                    {
                        "displayType": "Integer",
                        "result": "LowerIsBetter",
                        "statText": "Accuracy",
                        "statValue": 2,
                    }
                ],
            },
        )
        self.assertEqual(
            overridden["conditionalDescriptionsEvidence"]["sourcePackagePath"],
            PRIMING,
        )

        child = deepcopy(candidate_asset())
        default = next(
            export
            for export in child["exports"]
            if export["objectName"].startswith("Default__")
        )
        default["data"].append(conditional_descriptions([]))
        cleared = normalize_semantic_document(
            candidates=[{"id": PRIMING, "kind": "mod", "packagePath": PRIMING}],
            candidate_assets=[child],
            candidate_failures=[],
            effect_assets=[],
            dependency_failures=[],
            icon_metadata=[],
            icon_bytes={},
            source_fingerprint="sha256:fixture",
            parent_assets=[parent],
        ).document["records"][0]
        self.assertNotIn("conditionalDescriptions", cleared)
        self.assertEqual(
            cleared["conditionalDescriptionsResolution"]["status"],
            "authored-empty",
        )

    def test_malformed_conditional_descriptions_remain_unresolved(self) -> None:
        source = deepcopy(candidate_asset())
        default = next(
            export
            for export in source["exports"]
            if export["objectName"].startswith("Default__")
        )
        default["data"].append(
            conditional_descriptions(
                [conditional_description_group("<Bold>On Hit</>:", [])]
            )
        )

        record = normalize_semantic_document(
            candidates=[{"id": PRIMING, "kind": "mod", "packagePath": PRIMING}],
            candidate_assets=[source],
            candidate_failures=[],
            effect_assets=[],
            dependency_failures=[],
            icon_metadata=[],
            icon_bytes={},
            source_fingerprint="sha256:fixture",
        ).document["records"][0]

        self.assertNotIn("conditionalDescriptions", record)
        self.assertEqual(
            record["conditionalDescriptionsResolution"]["status"],
            "unresolved",
        )

    def test_weapon_icon_follows_nested_gun_icon_not_ammo_silhouette(self) -> None:
        cases = (
            (
                "/Game/UI/Textures/Avo_Weapons/Icon_Venus_Rifle_Auto_M41A2",
                "/Game/UI/Textures/Avo_Weapons/Sil/Icon_Sil_Venus_Rifle_Auto_M41A2",
            ),
            (
                "/Game/Weapons/Icons/Guns/Rifle/Icon_L36",
                "/Game/Weapons/Icons/Guns/Silhouettes/Icon_Sil_L36",
            ),
        )
        for icon, silhouette in cases:
            with self.subTest(icon=icon):
                asset = {
                    "packagePath": WEAPON,
                    "memberPath": f"AFE2/Content/{WEAPON[6:]}.uasset",
                    "engineVersion": "VER_UE4_27",
                    "imports": [
                        {"className": "Package", "objectName": icon, "outerIndex": 0},
                        {
                            "className": "Texture2D",
                            "objectName": icon.rsplit("/", 1)[-1],
                            "outerIndex": -1,
                        },
                        {"className": "Package", "objectName": silhouette, "outerIndex": 0},
                        {
                            "className": "Texture2D",
                            "objectName": silhouette.rsplit("/", 1)[-1],
                            "outerIndex": -3,
                        },
                    ],
                    "exports": [
                        {
                            "objectName": "Default__Venus_Rifle_Auto_M41A2_C",
                            "data": [
                                prop(
                                    "DisplayDescription",
                                    "DISPLAY-DESCRIPTION-KEY",
                                    "Objects.TextPropertyData",
                                    CultureInvariantString="The authored Collection weapon description.",
                                    HistoryType="Base",
                                ),
                                prop(
                                    "Description",
                                    "GENERIC-DESCRIPTION-KEY",
                                    "Objects.TextPropertyData",
                                    CultureInvariantString="A lower-priority generic description.",
                                    HistoryType="Base",
                                ),
                                prop(
                                    "Attributes",
                                    [
                                        prop(
                                            "UIVisuals",
                                            [
                                                prop("AmmoIcon", -4),
                                                prop("GunIcon", -2),
                                            ],
                                            "StructPropertyData",
                                        )
                                    ],
                                    "StructPropertyData",
                                ),
                                prop(
                                    "FireModes",
                                    [
                                        prop(
                                            "Attributes",
                                            [
                                                prop(
                                                    "UIVisuals",
                                                    [prop("GunIcon", -2)],
                                                    "StructPropertyData",
                                                )
                                            ],
                                            "StructPropertyData",
                                        )
                                    ],
                                    "ArrayPropertyData",
                                ),
                            ],
                        }
                    ],
                }
                result = normalize_semantic_document(
                    candidates=[{"id": WEAPON, "kind": "weapon", "packagePath": WEAPON}],
                    candidate_assets=[asset],
                    candidate_failures=[],
                    effect_assets=[],
                    dependency_failures=[],
                    icon_metadata=[
                        {
                            "packagePath": icon,
                            "outputName": "weapon--fixture.png",
                            "width": 1024,
                            "height": 512,
                            "pixelFormat": "PF_DXT5",
                        },
                        {
                            "packagePath": silhouette,
                            "outputName": "silhouette--fixture.png",
                            "width": 256,
                            "height": 128,
                            "pixelFormat": "PF_DXT5",
                        },
                    ],
                    icon_bytes={
                        "weapon--fixture.png": b"\x89PNG\r\n\x1a\nweapon",
                        "silhouette--fixture.png": b"\x89PNG\r\n\x1a\nsilhouette",
                    },
                    source_fingerprint="sha256:fixture",
                )

                record = result.document["records"][0]
                self.assertEqual(
                    record["description"],
                    "The authored Collection weapon description.",
                )
                self.assertTrue(
                    record["descriptionEvidence"].endswith(".DisplayDescription")
                )
                self.assertEqual(record["icon"]["packagePath"], icon)
                self.assertEqual(record["icon"]["path"], "icons/weapon--fixture.png")
                self.assertTrue(record["icon"]["referenceEvidence"].endswith(".GunIcon"))
                self.assertNotIn("FireModes", record["icon"]["referenceEvidence"])
                self.assertEqual(record["silhouetteIcon"]["packagePath"], silhouette)
                self.assertEqual(
                    record["silhouetteIcon"]["path"],
                    "icons/silhouette--fixture.png",
                )
                self.assertTrue(
                    record["silhouetteIcon"]["referenceEvidence"].endswith(".AmmoIcon")
                )
                self.assertNotEqual(record["icon"]["packagePath"], silhouette)
                self.assertEqual(
                    result.document["coverage"]["recordsWithSilhouetteIcon"],
                    1,
                )

    def test_mondo_trusts_serialized_misnamed_icon_and_keeps_silhouette(self) -> None:
        weapon_asset = {
            "packagePath": MONDO,
            "memberPath": f"AFE2/Content/{MONDO[6:]}.uasset",
            "engineVersion": "VER_UE4_27",
            "imports": [
                {"objectName": KRAMER_ICON, "outerIndex": 0},
                {"objectName": "Icon_Venus_Rifle_Auto_Kramer", "outerIndex": -1},
                {"objectName": MONDO_SILHOUETTE, "outerIndex": 0},
                {"objectName": "Icon_Sil_Venus_Rifle_Auto_HerkMondo", "outerIndex": -3},
            ],
            "exports": [
                {
                    "objectName": "Default__Venus_Rifle_Auto_HerkMondo_C",
                    "data": [
                        prop(
                            "Attributes",
                            [
                                prop(
                                    "UIVisuals",
                                    [prop("AmmoIcon", -4), prop("GunIcon", -2)],
                                    "StructPropertyData",
                                )
                            ],
                            "StructPropertyData",
                        )
                    ],
                }
            ],
        }
        result = normalize_semantic_document(
            candidates=[{"id": MONDO, "kind": "weapon", "packagePath": MONDO}],
            candidate_assets=[weapon_asset],
            candidate_failures=[],
            effect_assets=[],
            dependency_failures=[],
            icon_metadata=[
                {
                    "packagePath": KRAMER_ICON,
                    "outputName": "mondo-gun.png",
                    "width": 512,
                    "height": 256,
                    "pixelFormat": "PF_DXT5",
                },
                {
                    "packagePath": MONDO_SILHOUETTE,
                    "outputName": "mondo-silhouette.png",
                    "width": 256,
                    "height": 128,
                    "pixelFormat": "PF_DXT5",
                },
            ],
            icon_bytes={
                "mondo-gun.png": b"\x89PNG\r\n\x1a\ngun",
                "mondo-silhouette.png": b"\x89PNG\r\n\x1a\nsilhouette",
            },
            source_fingerprint="sha256:fixture",
        )

        record = next(item for item in result.document["records"] if item["id"] == MONDO)
        self.assertEqual(record["icon"]["packagePath"], KRAMER_ICON)
        self.assertEqual(record["icon"]["path"], "icons/mondo-gun.png")
        self.assertTrue(record["icon"]["referenceEvidence"].endswith(".GunIcon"))
        self.assertNotIn("fallback", record["icon"])
        self.assertNotIn("serializedIcon", record)
        self.assertEqual(record["silhouetteIcon"]["packagePath"], MONDO_SILHOUETTE)
        self.assertEqual(record["silhouetteIcon"]["path"], "icons/mondo-silhouette.png")

    def test_kit_icon_prefers_character_class_cdo_and_has_unlock_fallback(self) -> None:
        preferred_kit = "/Game/Synthetic/Kits/KitUnlock_Future"
        preferred_class = "/Game/Synthetic/Kits/Player_Future"
        preferred_unlock_icon = "/Game/Synthetic/UI/T_KitUnlock_Placeholder"
        class_icon = "/Game/Synthetic/UI/T_Class_Future"
        fallback_kit = "/Game/Synthetic/Kits/KitUnlock_Legacy"
        fallback_class = "/Game/Synthetic/Kits/Player_Legacy"
        fallback_unlock_icon = "/Game/Synthetic/UI/T_KitUnlock_Legacy"

        def kit_asset(
            package: str,
            character_class: str,
            unlock_icon: str,
        ) -> dict[str, object]:
            return {
                "packagePath": package,
                "memberPath": f"AFE2/Content/{package[6:]}.uasset",
                "engineVersion": "VER_UE4_27",
                "imports": [
                    {"objectName": character_class, "outerIndex": 0},
                    {
                        "objectName": f"{character_class.rsplit('/', 1)[-1]}_C",
                        "outerIndex": -1,
                    },
                    {"objectName": unlock_icon, "outerIndex": 0},
                    {
                        "objectName": unlock_icon.rsplit("/", 1)[-1],
                        "outerIndex": -3,
                    },
                ],
                "exports": [
                    {
                        "objectName": f"Default__{package.rsplit('/', 1)[-1]}_C",
                        "data": [
                            prop("CharacterClass", -2),
                            prop(
                                "Icon",
                                [prop("ResourceObject", -4)],
                                "Structs.StructPropertyData",
                            ),
                        ],
                    }
                ],
            }

        preferred_class_asset = {
            "packagePath": preferred_class,
            "memberPath": f"AFE2/Content/{preferred_class[6:]}.uasset",
            "engineVersion": "VER_UE4_27",
            "imports": [
                {"objectName": class_icon, "outerIndex": 0},
                {"objectName": class_icon.rsplit("/", 1)[-1], "outerIndex": -1},
            ],
            "exports": [
                {
                    "objectName": "Default__Player_Future_C",
                    "data": [prop("ClassDisplayIcon", -2)],
                }
            ],
        }
        fallback_class_asset = {
            "packagePath": fallback_class,
            "memberPath": f"AFE2/Content/{fallback_class[6:]}.uasset",
            "engineVersion": "VER_UE4_27",
            "imports": [],
            "exports": [
                {
                    "objectName": "Default__Player_Legacy_C",
                    "data": [],
                }
            ],
        }
        class_assets = [preferred_class_asset, fallback_class_asset]
        result = normalize_semantic_document(
            candidates=[
                {"id": preferred_kit, "kind": "kit", "packagePath": preferred_kit},
                {"id": fallback_kit, "kind": "kit", "packagePath": fallback_kit},
            ],
            candidate_assets=[
                kit_asset(preferred_kit, preferred_class, preferred_unlock_icon),
                kit_asset(fallback_kit, fallback_class, fallback_unlock_icon),
            ],
            candidate_failures=[],
            effect_assets=[],
            dependency_failures=[],
            icon_metadata=[
                {
                    "packagePath": preferred_unlock_icon,
                    "outputName": "preferred-unlock.png",
                    "width": 300,
                    "height": 300,
                    "pixelFormat": "PF_DXT5",
                },
                {
                    "packagePath": class_icon,
                    "outputName": "preferred-class.png",
                    "width": 300,
                    "height": 300,
                    "pixelFormat": "PF_DXT5",
                },
                {
                    "packagePath": fallback_unlock_icon,
                    "outputName": "fallback-unlock.png",
                    "width": 300,
                    "height": 300,
                    "pixelFormat": "PF_DXT5",
                },
            ],
            icon_bytes={
                "preferred-unlock.png": b"\x89PNG\r\n\x1a\nunlock-placeholder",
                "preferred-class.png": b"\x89PNG\r\n\x1a\nclass",
                "fallback-unlock.png": b"\x89PNG\r\n\x1a\nfallback",
            },
            source_fingerprint="sha256:fixture",
            class_assets=class_assets,
        )
        records = {item["id"]: item for item in result.document["records"]}

        preferred = records[preferred_kit]
        self.assertEqual(preferred["icon"]["packagePath"], class_icon)
        self.assertEqual(preferred["icon"]["path"], "icons/preferred-class.png")
        self.assertEqual(
            preferred["icon"]["referenceEvidence"],
            "Default__Player_Future_C.ClassDisplayIcon",
        )
        self.assertEqual(
            preferred["icon"]["provenance"]["sourcePackagePath"],
            preferred_class,
        )
        self.assertEqual(
            preferred["icon"]["provenance"]["type"],
            "serialized-character-class-cdo",
        )
        self.assertNotIn("fallback", preferred["icon"])
        self.assertNotIn("icons/preferred-unlock.png", result.binary_files)

        fallback = records[fallback_kit]
        self.assertEqual(fallback["icon"]["packagePath"], fallback_unlock_icon)
        self.assertEqual(fallback["icon"]["path"], "icons/fallback-unlock.png")
        self.assertEqual(fallback["icon"]["fallback"]["sourceRecordId"], fallback_kit)
        self.assertEqual(
            fallback["icon"]["fallback"]["classDisplayIconProvenance"]["status"],
            "not-authored",
        )
        self.assertEqual(result.document["coverage"]["kitClassDisplayIcons"], 1)
        self.assertEqual(result.document["coverage"]["kitUnlockIconFallbacks"], 1)
        self.assertEqual(
            _character_class_display_icon_packages(class_assets),
            (class_icon,),
        )

    def test_alternative_kit_membership_grants_specialist_ability_access(self) -> None:
        start_kit = "/Game/Synthetic/Kits/KitUnlock_Start"
        specialist_kit = "/Game/Synthetic/Kits/KitUnlock_Custom"
        start_class = "/Game/Synthetic/Kits/Player_Start"
        specialist_class = "/Game/Synthetic/Kits/Player_Custom"
        ability = "/Game/Synthetic/Perks/Perk_Start_Primary_Replacer"
        gameplay = "/Game/Synthetic/Abilities/GA_Start_Primary_Replacer"

        def kit_asset(package: str, character_class: str) -> dict[str, object]:
            return {
                "packagePath": package,
                "memberPath": f"AFE2/Content/{package[6:]}.uasset",
                "engineVersion": "VER_UE4_27",
                "imports": [
                    {"objectName": character_class, "outerIndex": 0},
                    {
                        "objectName": f"{character_class.rsplit('/', 1)[-1]}_C",
                        "outerIndex": -1,
                    },
                ],
                "exports": [
                    {
                        "objectName": f"Default__{package.rsplit('/', 1)[-1]}_C",
                        "data": [prop("CharacterClass", -2)],
                    }
                ],
            }

        ability_asset = {
            "packagePath": ability,
            "memberPath": f"AFE2/Content/{ability[6:]}.uasset",
            "engineVersion": "VER_UE4_27",
            "imports": [],
            "exports": [
                {
                    "objectName": "Default__Perk_Start_Primary_Replacer_C",
                    "data": [
                        prop(
                            "ClassAbilityType",
                            "EClassAbilityType::Ultimate",
                            "Objects.EnumPropertyData",
                        ),
                        soft_object("KitRestriction", start_class),
                        soft_object("OriginKit", start_class),
                        prop(
                            "AlternativeKitsAllowed",
                            [soft_object("0", specialist_class)],
                            "Objects.ArrayPropertyData",
                        ),
                        soft_object("GrantedAbilityOverride", gameplay),
                    ],
                }
            ],
        }
        result = normalize_semantic_document(
            candidates=[
                {"id": start_kit, "kind": "kit", "packagePath": start_kit},
                {
                    "id": specialist_kit,
                    "kind": "kit",
                    "packagePath": specialist_kit,
                },
                {"id": ability, "kind": "perk", "packagePath": ability},
            ],
            candidate_assets=[
                kit_asset(start_kit, start_class),
                kit_asset(specialist_kit, specialist_class),
                ability_asset,
            ],
            candidate_failures=[],
            effect_assets=[],
            dependency_failures=[],
            icon_metadata=[],
            icon_bytes={},
            source_fingerprint="sha256:fixture",
        )
        records = {item["id"]: item for item in result.document["records"]}

        self.assertEqual(
            result.document["kitAbilities"][0]["availableToKitIds"],
            [start_kit, specialist_kit],
        )
        self.assertEqual(
            records[specialist_kit]["abilityPerkIdsByRole"]["primary"],
            [ability],
        )

    def test_future_kit_roles_new_abilities_and_cross_kit_aliases_are_data_driven(
        self,
    ) -> None:
        marauder_kit = (
            "/Game/Blueprints/Avocado_Classes/ClassUnlocks/KitUnlock_Marauder"
        )
        bulwark_kit = (
            "/Game/Blueprints/Avocado_Classes/ClassUnlocks/KitUnlock_Bulwark"
        )
        marauder_class = (
            "/Game/Blueprints/Avocado_Classes/Marauder/Player_Marauder"
        )
        bulwark_class = (
            "/Game/Blueprints/Avocado_Classes/Bulwark/Player_Bulwark"
        )

        marauder_primary = (
            "/Game/Blueprints/Avocado_Classes/Marauder/Perks/TitanRockets/"
            "Perk_Marauder_TitanRockets_Base_Ultimate"
        )
        newly_added_primary = (
            "/Game/Blueprints/Avocado_Classes/Marauder/Perks/BreachingRockets/"
            "Perk_Marauder_BreachingRockets_Base_Ultimate"
        )
        shared_secondary = (
            "/Game/Blueprints/Avocado_Classes/Marauder/Perks/RallyPoint/"
            "Perk_Marauder_RallyPoint_Base_Tactical"
        )
        bulwark_wrapper = (
            "/Game/Blueprints/Avocado_Classes/Bulwark/Perks/RallyPoint/"
            "Perk_Bulwark_RallyPoint_Replacer_Tactical"
        )
        bulwark_secondary = (
            "/Game/Blueprints/Avocado_Classes/Bulwark/Perks/ShieldWall/"
            "Perk_Bulwark_ShieldWall_Base_Tactical"
        )
        bulwark_passive = (
            "/Game/Blueprints/Avocado_Classes/Bulwark/Perks/Phalanx/"
            "Perk_Bulwark_Phalanx_Base_Passive"
        )

        titan_rockets = "/Game/Synthetic/Abilities/GA_Marauder_TitanRockets"
        breaching_rockets = "/Game/Synthetic/Abilities/GA_Marauder_BreachingRockets"
        rally_point = "/Game/Synthetic/Abilities/GA_Marauder_RallyPoint"
        shield_wall = "/Game/Synthetic/Abilities/GA_Bulwark_ShieldWall"
        phalanx = "/Game/Synthetic/Abilities/GA_Bulwark_Phalanx"

        def kit_asset(package: str, character_class: str) -> dict[str, object]:
            return {
                "packagePath": package,
                "memberPath": f"AFE2/Content/{package[6:]}.uasset",
                "engineVersion": "VER_UE4_27",
                "imports": [
                    {"objectName": character_class, "outerIndex": 0},
                    {
                        "objectName": f"{character_class.rsplit('/', 1)[-1]}_C",
                        "outerIndex": -1,
                    },
                ],
                "exports": [
                    {
                        "objectName": f"Default__{package.rsplit('/', 1)[-1]}_C",
                        "data": [prop("CharacterClass", -2)],
                    }
                ],
            }

        def ability_asset(
            package: str,
            *,
            role: str,
            restricted_class: str,
            origin_class: str,
            gameplay_ability: str,
            wrapper: bool = False,
        ) -> dict[str, object]:
            granted_property = "GrantedAbilityOverride" if wrapper else "GrantedAbility"
            return {
                "packagePath": package,
                "memberPath": f"AFE2/Content/{package[6:]}.uasset",
                "engineVersion": "VER_UE4_27",
                "imports": [],
                "exports": [
                    {
                        "objectName": f"Default__{package.rsplit('/', 1)[-1]}_C",
                        "data": [
                            prop(
                                "ClassAbilityType",
                                f"EClassAbilityType::{role}",
                                "Objects.EnumPropertyData",
                            ),
                            soft_object("KitRestriction", restricted_class),
                            soft_object("OriginKit", origin_class),
                            soft_object(granted_property, gameplay_ability),
                        ],
                    }
                ],
            }

        ability_specs = [
            (
                marauder_primary,
                "Ultimate",
                marauder_class,
                marauder_class,
                titan_rockets,
                False,
            ),
            (
                newly_added_primary,
                "Ultimate",
                marauder_class,
                marauder_class,
                breaching_rockets,
                False,
            ),
            (
                shared_secondary,
                "Tactical",
                marauder_class,
                marauder_class,
                rally_point,
                False,
            ),
            (
                bulwark_wrapper,
                "Tactical",
                bulwark_class,
                marauder_class,
                rally_point,
                True,
            ),
            (
                bulwark_secondary,
                "Tactical",
                bulwark_class,
                bulwark_class,
                shield_wall,
                False,
            ),
            (
                bulwark_passive,
                "Passive",
                bulwark_class,
                bulwark_class,
                phalanx,
                False,
            ),
        ]
        candidates = [
            {"id": marauder_kit, "kind": "kit", "packagePath": marauder_kit},
            {"id": bulwark_kit, "kind": "kit", "packagePath": bulwark_kit},
            *[
                {"id": package, "kind": "perk", "packagePath": package}
                for package, *_ in ability_specs
            ],
        ]
        result = normalize_semantic_document(
            candidates=candidates,
            candidate_assets=[
                kit_asset(marauder_kit, marauder_class),
                kit_asset(bulwark_kit, bulwark_class),
                *[
                    ability_asset(
                        package,
                        role=role,
                        restricted_class=restricted_class,
                        origin_class=origin_class,
                        gameplay_ability=gameplay_ability,
                        wrapper=wrapper,
                    )
                    for (
                        package,
                        role,
                        restricted_class,
                        origin_class,
                        gameplay_ability,
                        wrapper,
                    ) in ability_specs
                ],
            ],
            candidate_failures=[],
            effect_assets=[],
            dependency_failures=[],
            icon_metadata=[],
            icon_bytes={},
            source_fingerprint="sha256:fixture",
        )
        records = {item["id"]: item for item in result.document["records"]}
        concepts = {item["id"]: item for item in result.document["kitAbilities"]}

        self.assertEqual(
            set(concepts),
            {
                marauder_primary,
                newly_added_primary,
                shared_secondary,
                bulwark_secondary,
                bulwark_passive,
            },
        )
        self.assertNotIn(bulwark_wrapper, concepts)
        self.assertEqual(records[bulwark_wrapper]["ability"]["aliasOf"], shared_secondary)
        self.assertEqual(
            concepts[shared_secondary]["availableToKitIds"],
            [marauder_kit, bulwark_kit],
        )
        self.assertEqual(
            records[marauder_kit]["abilityPerkIdsByRole"]["primary"],
            sorted([marauder_primary, newly_added_primary]),
        )
        self.assertEqual(
            records[bulwark_kit]["abilityPerkIdsByRole"],
            {
                "primary": [],
                "secondary": sorted([shared_secondary, bulwark_secondary]),
                "passive": [bulwark_passive],
            },
        )
        self.assertEqual(result.document["coverage"]["kitAbilities"], 5)
        self.assertEqual(result.document["coverage"]["kitAbilityAliases"], 1)

    def test_character_class_assets_define_future_kit_slots_and_entitlements(
        self,
    ) -> None:
        kit = "/Game/Blueprints/Avocado_Classes/ClassUnlocks/KitUnlock_Bulwark"
        character_class = "/Game/Blueprints/Avocado_Classes/Bulwark/Player_Bulwark"
        board = "/Game/Blueprints/Avocado_Classes/Bulwark/Perks/PerkBoard_Bulwark"
        secondary = (
            "/Game/Blueprints/Avocado_Classes/Bulwark/Perks/ShieldWall/"
            "Perk_Bulwark_ShieldWall_Base_Tactical"
        )
        passive = (
            "/Game/Blueprints/Avocado_Classes/Bulwark/Perks/Phalanx/"
            "Perk_Bulwark_Phalanx_Base_Passive"
        )
        stray_primary = (
            "/Game/Blueprints/Avocado_Classes/Bulwark/Perks/Prototype/"
            "Perk_Bulwark_Prototype_Ultimate"
        )
        entitled_perk = (
            "/Game/Blueprints/Avocado_Classes/Bulwark/Perks/"
            "Perk_Bulwark_ShieldTraining"
        )
        referenced_only_perk = (
            "/Game/Blueprints/Avocado_Classes/Perks/"
            "Perk_Generic_Core_ShieldEfficiency"
        )
        rifle = "/Game/Blueprints/Venus_Weapons/Guns/Rifles/Venus_Rifle_Test"
        shield_weapon = (
            "/Game/Blueprints/Venus_Weapons/Guns/Bulwark/"
            "Venus_CQW_Shield_Test"
        )
        sidearm = "/Game/Blueprints/Venus_Weapons/Guns/Handguns/Venus_Handgun_Test"

        def import_pair(package: str, outer_index: int) -> list[dict[str, object]]:
            return [
                {
                    "objectName": f"{package.rsplit('/', 1)[-1]}_C",
                    "outerIndex": outer_index,
                },
                {"objectName": package, "outerIndex": 0},
            ]

        kit_asset = {
            "packagePath": kit,
            "memberPath": f"AFE2/Content/{kit[6:]}.uasset",
            "engineVersion": "VER_UE4_27",
            "imports": import_pair(character_class, -2),
            "exports": [
                {
                    "objectName": "Default__KitUnlock_Bulwark_C",
                    "data": [prop("CharacterClass", -1)],
                }
            ],
        }

        board_asset = {
            "packagePath": board,
            "memberPath": f"AFE2/Content/{board[6:]}.uasset",
            "engineVersion": "VER_UE4_27",
            "imports": [
                *import_pair(secondary, -2),
                *import_pair(passive, -4),
            ],
            "exports": [
                {
                    "objectName": "Default__PerkBoard_Bulwark_C",
                    "data": [
                        prop(
                            "BoardLockedPlacements",
                            [
                                prop(
                                    "BoardLockedPlacements",
                                    [
                                        prop("LockedSpecificChip", -1),
                                        prop("Row", 1, "Objects.IntPropertyData"),
                                        prop("Column", 9, "Objects.IntPropertyData"),
                                    ],
                                    "Structs.StructPropertyData",
                                    StructType="ModChipLockedPlacement",
                                ),
                                prop(
                                    "BoardLockedPlacements",
                                    [
                                        prop("LockedSpecificChip", -3),
                                        prop("Row", 5, "Objects.IntPropertyData"),
                                        prop("Column", 3, "Objects.IntPropertyData"),
                                    ],
                                    "Structs.StructPropertyData",
                                    StructType="ModChipLockedPlacement",
                                ),
                            ],
                            "Objects.ArrayPropertyData",
                            ArrayType="StructProperty",
                        )
                    ],
                }
            ],
        }

        def gun_slot(
            default_weapon: str,
            *,
            avo_type: str,
            gun_type: str,
            subtype: str,
            kit_tag: str,
        ) -> dict[str, object]:
            return prop(
                "GunLoadoutData",
                [
                    soft_object("GunClass", default_weapon),
                    prop(
                        "GunSlotAvoType",
                        f"EGunAvoType::{avo_type}",
                        "Objects.EnumPropertyData",
                    ),
                    prop(
                        "GunSlotType",
                        f"EGunType::{gun_type}",
                        "Objects.EnumPropertyData",
                    ),
                    prop(
                        "GunSlotSubType",
                        f"EGunSubType::{subtype}",
                        "Objects.EnumPropertyData",
                    ),
                    prop(
                        "GunKitTag",
                        [
                            prop(
                                "TagName",
                                kit_tag,
                                "Objects.NamePropertyData",
                            )
                        ],
                        "Structs.StructPropertyData",
                        StructType="GameplayTag",
                    ),
                ],
                "Structs.StructPropertyData",
                StructType="GunSlotDef",
            )

        def entitlement(chip_index: int, rank: int) -> dict[str, object]:
            return prop(
                "ChipEntitlements",
                [
                    prop("ChipCDO", chip_index),
                    prop("RequiredRank", rank, "Objects.IntPropertyData"),
                    soft_object("GrantedBy", "None"),
                ],
                "Structs.StructPropertyData",
                StructType="ModChipEntitlement",
            )

        class_asset = {
            "packagePath": character_class,
            "memberPath": f"AFE2/Content/{character_class[6:]}.uasset",
            "engineVersion": "VER_UE4_27",
            "imports": [
                *import_pair(board, -2),
                *import_pair(entitled_perk, -4),
                *import_pair(referenced_only_perk, -6),
            ],
            "exports": [
                {
                    "objectName": "Default__Player_Bulwark_C",
                    "data": [
                        prop("ChipBoardDef", -1),
                        prop(
                            "GunLoadoutData",
                            [
                                gun_slot(
                                    rifle,
                                    avo_type="Primary",
                                    gun_type="Rifle",
                                    subtype="Any",
                                    kit_tag="None",
                                ),
                                gun_slot(
                                    shield_weapon,
                                    avo_type="Primary",
                                    gun_type="CQW",
                                    subtype="Shotgun",
                                    kit_tag="Kit.Bulwark",
                                ),
                                gun_slot(
                                    sidearm,
                                    avo_type="Sidearm",
                                    gun_type="Handgun",
                                    subtype="Any",
                                    kit_tag="None",
                                ),
                            ],
                            "Objects.ArrayPropertyData",
                            ArrayType="StructProperty",
                        ),
                        prop(
                            "ChipEntitlements",
                            [entitlement(-3, 2), entitlement(-5, 7)],
                            "Objects.ArrayPropertyData",
                            ArrayType="StructProperty",
                        ),
                    ],
                }
            ],
        }

        def ability_asset(
            package: str,
            *,
            role: str,
            gameplay: str,
        ) -> dict[str, object]:
            return {
                "packagePath": package,
                "memberPath": f"AFE2/Content/{package[6:]}.uasset",
                "engineVersion": "VER_UE4_27",
                "imports": [],
                "exports": [
                    {
                        "objectName": f"Default__{package.rsplit('/', 1)[-1]}_C",
                        "data": [
                            prop(
                                "ClassAbilityType",
                                f"EClassAbilityType::{role}",
                                "Objects.EnumPropertyData",
                            ),
                            soft_object("KitRestriction", character_class),
                            soft_object("OriginKit", character_class),
                            soft_object("GrantedAbility", gameplay),
                        ],
                    }
                ],
            }

        candidates = [
            {"id": kit, "kind": "kit", "packagePath": kit},
            {"id": board, "kind": "gridShape", "packagePath": board},
            {"id": secondary, "kind": "perk", "packagePath": secondary},
            {"id": passive, "kind": "perk", "packagePath": passive},
            {"id": stray_primary, "kind": "perk", "packagePath": stray_primary},
            {"id": entitled_perk, "kind": "perk", "packagePath": entitled_perk},
            {"id": rifle, "kind": "weapon", "packagePath": rifle},
            {"id": sidearm, "kind": "weapon", "packagePath": sidearm},
        ]
        result = normalize_semantic_document(
            candidates=candidates,
            candidate_assets=[
                kit_asset,
                board_asset,
                ability_asset(
                    secondary,
                    role="Tactical",
                    gameplay="/Game/Synthetic/Abilities/GA_Bulwark_ShieldWall",
                ),
                ability_asset(
                    passive,
                    role="Passive",
                    gameplay="/Game/Synthetic/Abilities/GA_Bulwark_Phalanx",
                ),
                ability_asset(
                    stray_primary,
                    role="Ultimate",
                    gameplay="/Game/Synthetic/Abilities/GA_Bulwark_Prototype",
                ),
            ],
            class_assets=[class_asset],
            candidate_failures=[],
            effect_assets=[],
            dependency_failures=[],
            icon_metadata=[],
            icon_bytes={},
            source_fingerprint="sha256:fixture",
        )
        records = {item["id"]: item for item in result.document["records"]}
        normalized = records[kit]

        self.assertEqual(normalized["perkBoard"]["packagePath"], board)
        self.assertEqual(normalized["perkBoard"]["recordId"], board)
        self.assertEqual(
            normalized["abilitySlots"],
            [
                {
                    "column": 9,
                    "index": 0,
                    "lockedChipId": secondary,
                    "role": "secondary",
                    "row": 1,
                    "selectableAbilityPerkIds": [secondary],
                },
                {
                    "column": 3,
                    "index": 1,
                    "lockedChipId": passive,
                    "role": "passive",
                    "row": 5,
                    "selectableAbilityPerkIds": [passive],
                },
            ],
        )
        self.assertEqual(normalized["abilityPerkIdsByRole"]["primary"], [])
        self.assertNotIn(
            stray_primary,
            [
                ability_id
                for slot in normalized["abilitySlots"]
                for ability_id in slot["selectableAbilityPerkIds"]
            ],
        )

        self.assertEqual(
            [slot["slotType"] for slot in normalized["weaponSlots"]],
            ["primary", "primary", "sidearm"],
        )
        self.assertNotIn(
            "signature",
            [slot["slotType"] for slot in normalized["weaponSlots"]],
        )
        self.assertEqual(normalized["weaponSlots"][0]["defaultWeaponId"], rifle)
        self.assertEqual(
            normalized["weaponSlots"][1]["defaultWeaponPackagePath"],
            shield_weapon,
        )
        self.assertNotIn("defaultWeaponId", normalized["weaponSlots"][1])
        self.assertEqual(normalized["weaponSlots"][1]["kitTag"], "Kit.Bulwark")
        self.assertNotIn("kitTag", normalized["weaponSlots"][0])

        entitlements = normalized["chipEntitlements"]
        self.assertEqual(len(entitlements), 2)
        self.assertEqual(entitlements[0]["perkPackagePath"], entitled_perk)
        self.assertEqual(entitlements[0]["perkId"], entitled_perk)
        self.assertEqual(entitlements[0]["requiredRank"], 2)
        self.assertEqual(entitlements[1]["perkPackagePath"], referenced_only_perk)
        self.assertNotIn("perkId", entitlements[1])
        self.assertEqual(entitlements[1]["requiredRank"], 7)

    def test_malformed_present_possible_shapes_stays_unresolved(self) -> None:
        perk = "/Game/Synthetic/Perks/Perk_MalformedShape"
        asset = {
            "packagePath": perk,
            "memberPath": f"AFE2/Content/{perk[6:]}.uasset",
            "engineVersion": "VER_UE4_27",
            "imports": [],
            "exports": [
                {
                    "objectName": "Default__Perk_MalformedShape_C",
                    "data": [possible_shape(2, 2, [1, 1, 1])],
                }
            ],
        }
        result = normalize_semantic_document(
            candidates=[{"id": perk, "kind": "perk", "packagePath": perk}],
            candidate_assets=[asset],
            candidate_failures=[],
            effect_assets=[],
            dependency_failures=[],
            icon_metadata=[],
            icon_bytes={},
            source_fingerprint="sha256:fixture",
        )
        record = result.document["records"][0]

        self.assertEqual(record["grid"]["status"], "unresolved")
        self.assertEqual(record["grid"]["shapes"], [])
        self.assertNotIn("2x2", json.dumps(record["grid"]))
        self.assertEqual(result.document["coverage"]["perkGridShapesExplicit"], 0)
        self.assertEqual(result.document["coverage"]["perkGridShapesInferred"], 0)

    def test_kit_abilities_perk_shapes_and_modifier_dependencies_are_resolved(self) -> None:
        start_kit = "/Game/Blueprints/Avocado_Classes/ClassUnlocks/KitUnlock_Demolisher"
        custom_kit = "/Game/Blueprints/Avocado_Classes/ClassUnlocks/KitUnlock_Custom"
        start_class = "/Game/Blueprints/Avocado_Classes/Demolisher/Player_Demolisher_V2"
        custom_class = "/Game/Blueprints/Avocado_Classes/Custom/Player_Custom"
        base = (
            "/Game/Blueprints/Avocado_Classes/Demolisher/Perks/BlastCannon/"
            "Perk_Demolisher_BlastCannon_Base_Tactical"
        )
        wrapper = (
            "/Game/Blueprints/Avocado_Classes/Custom/Perks/"
            "Perk_Custom_Tactical_Replacer_BlastCannon"
        )
        modifier = (
            "/Game/Blueprints/Avocado_Classes/Demolisher/Perks/BlastCannon/"
            "Perk_Demolisher_BlastCannon_Mod_Test"
        )
        wrong_target = (
            "/Game/Blueprints/Avocado_Classes/Demolisher/Perks/BlastCannon/"
            "Perk_Demolisher_BlastCannon_Mod_WrongDirection"
        )
        gameplay = (
            "/Game/Blueprints/Avocado_Classes/Demolisher/Perks/BlastCannon/"
            "GA_Demolisher_BlastCannon_Base"
        )

        def kit_asset(package: str, character_class: str) -> dict[str, object]:
            return {
                "packagePath": package,
                "memberPath": f"AFE2/Content/{package[6:]}.uasset",
                "engineVersion": "VER_UE4_27",
                "imports": [
                    {"objectName": character_class, "outerIndex": 0},
                    {"objectName": f"{character_class.rsplit('/', 1)[-1]}_C", "outerIndex": -1},
                ],
                "exports": [
                    {
                        "objectName": f"Default__{package.rsplit('/', 1)[-1]}_C",
                        "data": [prop("CharacterClass", -2)],
                    }
                ],
            }

        def perk_asset(package: str, data: list[dict[str, object]]) -> dict[str, object]:
            return {
                "packagePath": package,
                "memberPath": f"AFE2/Content/{package[6:]}.uasset",
                "engineVersion": "VER_UE4_27",
                "imports": [],
                "exports": [
                    {
                        "objectName": f"Default__{package.rsplit('/', 1)[-1]}_C",
                        "data": data,
                    }
                ],
            }

        base_asset = perk_asset(
            base,
            [
                {
                    "$type": "TextPropertyData",
                    "Name": "Name",
                    "CultureInvariantString": "Blast Cannon",
                    "HistoryType": "Base",
                },
                prop(
                    "ClassAbilityType",
                    "EClassAbilityType::Tactical",
                    "Objects.EnumPropertyData",
                ),
                soft_object("KitRestriction", start_class),
                soft_object("GrantedAbility", gameplay),
                possible_shape(1, 4, [1, 1, 1, 1]),
                tag_container(
                    "ModifierCompatability",
                    ["Item.Chip.Modifier.Kit.Demolisher.Guardian"],
                ),
            ],
        )
        wrapper_asset = perk_asset(
            wrapper,
            [
                prop(
                    "ClassAbilityType",
                    "EClassAbilityType::Tactical",
                    "Objects.EnumPropertyData",
                ),
                soft_object("KitRestriction", custom_class),
                soft_object("OriginKit", start_class),
                soft_object("GrantedAbilityOverride", gameplay),
            ],
        )
        modifier_asset = perk_asset(
            modifier,
            [
                prop("Type", "EModChipType::Modifier", "Objects.EnumPropertyData"),
                tag_container(
                    "Tags",
                    ["Item.Chip.Modifier.Kit.Demolisher.Guardian.Damage"],
                ),
                possible_shape(2, 1, [1, 1]),
            ],
        )
        wrong_target_asset = perk_asset(
            wrong_target,
            [
                tag_container(
                    "ModifierCompatability",
                    ["Item.Chip.Modifier.Kit.Demolisher.Guardian.Damage.Deep"],
                )
            ],
        )
        candidates = [
            {"id": start_kit, "kind": "kit", "packagePath": start_kit},
            {"id": custom_kit, "kind": "kit", "packagePath": custom_kit},
            {"id": base, "kind": "perk", "packagePath": base},
            {"id": wrapper, "kind": "perk", "packagePath": wrapper},
            {"id": modifier, "kind": "perk", "packagePath": modifier},
            {"id": wrong_target, "kind": "perk", "packagePath": wrong_target},
        ]
        result = normalize_semantic_document(
            candidates=candidates,
            candidate_assets=[
                kit_asset(start_kit, start_class),
                kit_asset(custom_kit, custom_class),
                base_asset,
                wrapper_asset,
                modifier_asset,
                wrong_target_asset,
            ],
            candidate_failures=[],
            effect_assets=[],
            dependency_failures=[],
            icon_metadata=[],
            icon_bytes={},
            source_fingerprint="sha256:fixture",
        )
        records = {item["id"]: item for item in result.document["records"]}

        self.assertEqual(result.document["kitAbilities"][0]["id"], base)
        self.assertEqual(result.document["kitAbilities"][0]["role"], "secondary")
        self.assertEqual(
            result.document["kitAbilities"][0]["availableToKitIds"],
            [start_kit, custom_kit],
        )
        self.assertEqual(records[wrapper]["ability"]["aliasOf"], base)
        self.assertEqual(records[start_kit]["abilityPerkIdsByRole"]["secondary"], [base])
        self.assertEqual(records[custom_kit]["abilityPerkIdsByRole"]["secondary"], [base])

        self.assertEqual(records[base]["grid"]["shapes"][0]["size"], "1x4")
        self.assertEqual(records[modifier]["grid"]["shapes"][0]["size"], "1x2")
        self.assertEqual(records[wrong_target]["grid"]["shapes"][0]["size"], "2x2")
        self.assertEqual(
            records[wrong_target]["grid"]["shapes"][0]["evidence"]["source"],
            "native-default-inferred",
        )
        self.assertEqual(
            records[modifier]["dependencies"]["possibleTargetPerkIds"],
            [base],
        )
        self.assertEqual(
            records[base]["dependencies"]["possibleModifierPerkIds"],
            [modifier],
        )
        self.assertNotIn(
            wrong_target,
            records[modifier]["dependencies"]["possibleTargetPerkIds"],
        )
        self.assertEqual(result.document["coverage"]["kitAbilities"], 1)
        self.assertEqual(result.document["coverage"]["perkDependencyEdges"], 1)

        enriched_candidates = {
            "records": [
                {"id": start_kit, "kind": "kit", "packagePath": start_kit},
                {"id": base, "kind": "perk", "packagePath": base},
                {"id": modifier, "kind": "perk", "packagePath": modifier},
            ]
        }
        apply_semantic_evidence(
            candidates=enriched_candidates,
            semantic=result.document,
        )
        enriched = {item["id"]: item for item in enriched_candidates["records"]}
        self.assertEqual(enriched[start_kit]["abilityPerkIdsByRole"]["secondary"], [base])
        self.assertEqual(enriched[base]["grid"]["shapes"][0]["size"], "1x4")
        self.assertEqual(
            enriched[modifier]["dependencies"]["possibleTargetPerkIds"],
            [base],
        )

    def test_enrichment_reaches_candidate_record(self) -> None:
        result = self.normalize()
        candidates = {
            "records": [
                {
                    "id": PRIMING,
                    "kind": "mod",
                    "missingFields": ["exports", "localizedDisplayName", "compatibility"],
                    "packagePath": PRIMING,
                }
            ]
        }
        apply_semantic_evidence(
            candidates=candidates,
            semantic=result.document,
        )

        candidate = candidates["records"][0]
        self.assertEqual(candidate["stats"][0]["expression"], "TimeToReload / 1.2")
        self.assertEqual(candidate["missingFields"], ["compatibility"])
        self.assertEqual(candidate["icon"]["path"], "icons/priming--fixture.png")
        self.assertEqual(candidate["stats"][0]["operation"], "divide")
        self.assertIsNone(candidate["description"])
        self.assertEqual(candidate["compatibility"]["status"], "partial")


if __name__ == "__main__":
    unittest.main()
