from __future__ import annotations

from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from afe2_catalogue.attachment_descriptions import (  # noqa: E402
    project_attachment_description,
)


def metadata(*rows: dict[str, object]) -> dict[str, object]:
    return {
        "packagePath": "/Game/Design/AttributeMetaData/AttributeMetaData",
        "rows": list(rows),
        "status": "parsed",
    }


def row(
    attribute: str,
    display_name: str,
    display_type: str,
    operation: str,
    result: str,
    sort_order: int,
) -> dict[str, object]:
    return {
        "attribute": attribute,
        "displayName": display_name,
        "displayType": display_type,
        "modifierOperation": operation,
        "result": result,
        "sortOrder": sort_order,
    }


def effect(
    package_leaf: str,
    magnitude: float,
    *attributes: tuple[str, str],
    visible: bool = True,
    normalize: bool = False,
    override_display_stat_tag: str | None = None,
) -> dict[str, object]:
    definition: dict[str, object] = {
        "modifiers": [
            {
                "attribute": attribute.rsplit(".", 1)[-1],
                "magnitudeCalculationType": "setbycaller",
                "operation": operation,
                "qualifiedAttribute": attribute,
            }
            for attribute, operation in attributes
        ],
        "status": "parsed",
    }
    if override_display_stat_tag is not None:
        definition["overrideDisplayStatTag"] = override_display_stat_tag
    return {
        "configuredMagnitude": magnitude,
        "definition": definition,
        "effectPackagePath": (
            "/Game/Blueprints/Gameplay/GameplayEffects/AvoMods/" + package_leaf
        ),
        "serializedFlags": {
            "bInterpretTableLookupAsPercent": True,
            "bNormalizePercentForEffectMagnitude": normalize,
            "bVisibleOnUI": visible,
        },
    }


def scalable_effect(
    package_leaf: str,
    *modifiers: tuple[str, str, float],
) -> dict[str, object]:
    return {
        "configuredMagnitude": 1.0,
        "definition": {
            "modifiers": [
                {
                    "attribute": attribute.rsplit(".", 1)[-1],
                    "magnitudeCalculationType": "scalablefloat",
                    "operation": operation,
                    "qualifiedAttribute": attribute,
                    "scalableFloatMagnitude": {
                        "curveRowName": None,
                        "curveTablePackagePath": None,
                        "value": magnitude,
                    },
                }
                for attribute, operation, magnitude in modifiers
            ],
            "status": "parsed",
        },
        "effectPackagePath": (
            "/Game/Blueprints/Gameplay/GameplayEffects/AvoMods/" + package_leaf
        ),
        "serializedFlags": {"bVisibleOnUI": True},
    }


class AttachmentDescriptionTests(unittest.TestCase):
    def test_augment_uses_gun_mod_rows_and_composes_every_visible_section(self) -> None:
        source = {
            "conditionalDescriptions": [
                {
                    "conditionText": "<Bold>On Hit</>:",
                    "statLines": [
                        {
                            "displayType": "Percent",
                            "result": "HigherIsBetter",
                            "statText": "Weak Point DMG Bonus",
                            "statValue": -75.0,
                        },
                        {
                            "displayType": "None",
                            "result": "HigherIsBetter",
                            "statText": "Lasts <Bold>5 seconds</>.",
                            "statValue": 0.0,
                        },
                    ],
                }
            ],
            "description": "Detailed effect.",
            "descriptionShort": "Summary.",
            "effects": [
                effect(
                    "Avo_Weapon_Damage",
                    1.1,
                    ("DealsDamageAttributes.DamageMagnitude_Primary", "multiply"),
                    ("DealsDamageAttributes.DamageMagnitude_Secondary", "multiply"),
                ),
                effect(
                    "Avo_Weapon_ReloadSpeed",
                    1.2,
                    ("GunGameplayAttributes.TimeToReload", "divide"),
                ),
            ],
            "flavorText": "Flavor text.",
            "kind": "augment",
        }

        description, lines = project_attachment_description(
            source,
            attribute_metadata=metadata(
                row(
                    "DealsDamageAttributes.DamageMagnitude_Primary",
                    "Damage",
                    "Integer",
                    "Multiply",
                    "HigherIsBetter",
                    1,
                ),
                row(
                    "DealsDamageAttributes.DamageMagnitude_Secondary",
                    "Explosive Damage",
                    "Integer",
                    "Multiply",
                    "HigherIsBetter",
                    2,
                ),
                row(
                    "GunGameplayAttributes.TimeToReload",
                    "Reload Time",
                    "Time",
                    "Divide",
                    "LowerIsBetter",
                    13,
                ),
            ),
        )

        self.assertEqual(
            [line["displayText"] for line in lines],
            ["+10.0% Damage", "+20.0% Reload Speed"],
        )
        self.assertEqual(lines[1]["result"], "HigherIsBetter")
        self.assertEqual(
            description,
            (
                "Detailed effect.\r\n"
                "Flavor text.\r\n"
                "Summary.\r\n"
                "+10.0% Damage\r\n"
                "+20.0% Reload Speed\r\n"
                "<Bold>On Hit</>:\r\n"
                "  -75% Weak Point DMG Bonus\r\n"
                "  Lasts <Bold>5 seconds</>."
            ),
        )

    def test_conditional_float_keeps_unreal_decimal_suffix(self) -> None:
        source = {
            "conditionalDescriptions": [
                {
                    "conditionText": None,
                    "statLines": [
                        {
                            "displayType": "Float",
                            "result": "HigherIsBetter",
                            "statText": "Bullet Penetration",
                            "statValue": 1.0,
                        }
                    ],
                }
            ],
            "description": None,
            "kind": "mod",
        }

        description, lines = project_attachment_description(
            source,
            attribute_metadata=metadata(
                row(
                    "GunGameplayAttributes.TimeToReload",
                    "Reload Time",
                    "Time",
                    "Divide",
                    "LowerIsBetter",
                    13,
                )
            ),
        )

        self.assertEqual(lines, [])
        self.assertEqual(description, "+1.0 Bullet Penetration")

    def test_priming_uses_client_reload_label_and_division_percentage(self) -> None:
        source = {
            "description": None,
            "effects": [
                effect(
                    "Avo_Weapon_ReloadSpeed",
                    1.2000000476837158,
                    ("GunGameplayAttributes.TimeToReload", "divide"),
                )
            ],
            "kind": "mod",
        }

        description, lines = project_attachment_description(
            source,
            attribute_metadata=metadata(
                row(
                    "GunGameplayAttributes.TimeToReload",
                    "Reload Time",
                    "Time",
                    "Divide",
                    "LowerIsBetter",
                    13,
                )
            ),
        )

        self.assertEqual(description, "+20.0% Reload Speed")
        self.assertEqual(
            lines,
            [
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
            ],
        )

    def test_combines_static_and_conditional_sections_without_raw_calculation(self) -> None:
        source = {
            "conditionalDescriptions": [
                {
                    "conditionText": "<Bold>When Magazine is Empty</>:",
                    "statLines": [
                        {
                            "displayType": "Percent",
                            "result": "HigherIsBetter",
                            "statText": "Reload Speed",
                            "statValue": 10.0,
                        }
                    ],
                }
            ],
            "description": None,
            "effects": [
                effect(
                    "Weapon_AmmoPerMag",
                    1.15,
                    ("GunGameplayAttributes.AmmoPerMag", "multiply"),
                ),
                effect(
                    "Weapon_MaxAmmo",
                    1.04,
                    ("GunGameplayAttributes.MaxAmmo", "multiply"),
                ),
            ],
            "kind": "mod",
        }

        description, lines = project_attachment_description(
            source,
            attribute_metadata=metadata(
                row(
                    "GunGameplayAttributes.AmmoPerMag",
                    "Magazine Capacity",
                    "Integer",
                    "Multiply",
                    "HigherIsBetter",
                    16,
                ),
                row(
                    "GunGameplayAttributes.MaxAmmo",
                    "Max Ammo",
                    "Integer_Truncated",
                    "Multiply",
                    "HigherIsBetter",
                    23,
                ),
            ),
        )

        self.assertEqual(
            [line["displayText"] for line in lines],
            ["+15.0% Magazine Capacity", "+4.0% Max Ammo"],
        )
        self.assertEqual(
            description,
            (
                "+15.0% Magazine Capacity\r\n"
                "+4.0% Max Ammo\r\n"
                "<Bold>When Magazine is Empty</>:\r\n"
                "  +10% Reload Speed"
            ),
        )

    def test_hidden_effect_does_not_create_a_player_facing_row(self) -> None:
        source = {
            "description": None,
            "effects": [
                effect(
                    "Avo_Weapon_ReloadSpeed",
                    1.2,
                    ("GunGameplayAttributes.TimeToReload", "divide"),
                    visible=False,
                )
            ],
            "kind": "mod",
        }

        description, lines = project_attachment_description(
            source,
            attribute_metadata=metadata(
                row(
                    "GunGameplayAttributes.TimeToReload",
                    "Reload Time",
                    "Time",
                    "Divide",
                    "LowerIsBetter",
                    13,
                )
            ),
        )

        self.assertIsNone(description)
        self.assertEqual(lines, [])

    def test_mondo_style_trait_keeps_static_and_conditional_sections(self) -> None:
        source = {
            "conditionalDescriptions": [
                {
                    "conditionText": "<Bold>When Magazine is Empty</>:",
                    "statLines": [
                        {
                            "displayType": "Percent",
                            "result": "LowerIsBetter",
                            "statText": "Reload Speed",
                            "statValue": -20.0,
                        }
                    ],
                }
            ],
            "description": None,
            "effects": [
                effect(
                    "Avo_Weapon_ReloadSpeed",
                    1.2,
                    ("GunGameplayAttributes.TimeToReload", "divide"),
                )
            ],
            "kind": "trait",
        }

        description, lines = project_attachment_description(
            source,
            attribute_metadata=metadata(
                row(
                    "GunGameplayAttributes.TimeToReload",
                    "Reload Time",
                    "Time",
                    "Divide",
                    "LowerIsBetter",
                    13,
                )
            ),
        )

        self.assertEqual(
            [line["displayText"] for line in lines],
            ["+20.0% Reload Speed"],
        )
        self.assertEqual(
            description,
            (
                "+20.0% Reload Speed\r\n"
                "<Bold>When Magazine is Empty</>:\r\n  -20% Reload Speed"
            ),
        )

    def test_accuracy_effect_uses_exact_spread_row_and_positive_glyph(self) -> None:
        source = {
            "description": None,
            "effects": [
                effect(
                    "Avo_Weapon_Accuracy",
                    0.9,
                    ("GunGameplayAttributes.MinimumSpread", "multiply"),
                )
            ],
            "kind": "mod",
        }

        description, lines = project_attachment_description(
            source,
            attribute_metadata=metadata(
                row(
                    "GunGameplayAttributes.AccuracyIndicator",
                    "Accuracy",
                    "Integer",
                    "JankyIndicatorStatMath",
                    "HigherIsBetter",
                    17,
                ),
                row(
                    "GunGameplayAttributes.MinimumSpread",
                    "Spread",
                    "Integer",
                    "Multiply",
                    "LowerIsBetter",
                    19,
                ),
            ),
        )

        self.assertEqual(description, "+10.0% Spread")
        self.assertEqual(lines[0]["attribute"], "GunGameplayAttributes.MinimumSpread")
        self.assertEqual(lines[0]["statValue"], 10.0)

    def test_effect_ui_override_replaces_handling_internals_with_combined_row(self) -> None:
        source = {
            "description": None,
            "effects": [
                effect(
                    "Avo_Weapon_Handling",
                    0.8,
                    ("GunGameplayAttributes.TimeToEquip", "divide"),
                    ("GunGameplayAttributes.TimeToADS", "divide"),
                    normalize=True,
                    override_display_stat_tag="Stats.Combined.Handling",
                )
            ],
            "kind": "mod",
        }

        description, lines = project_attachment_description(
            source,
            attribute_metadata=metadata(
                row(
                    "GunGameplayAttributes.TimeToEquip",
                    "Equip Time",
                    "Time",
                    "Divide",
                    "LowerIsBetter",
                    21,
                ),
                row(
                    "GunGameplayAttributes.TimeToADS",
                    "Aim Time",
                    "Time",
                    "Divide",
                    "LowerIsBetter",
                    22,
                ),
                row(
                    "Stats.Combined.Handling",
                    "Handling",
                    "NegativePercent",
                    "MultiplyShowNegative",
                    "LowerIsBetter",
                    40,
                ),
            ),
        )

        self.assertEqual(description, "+20.0% Handling")
        self.assertEqual(
            [line["attribute"] for line in lines],
            ["Stats.Combined.Handling"],
        )

    def test_aim_assist_ui_override_emits_the_authored_combined_row(self) -> None:
        source = {
            "description": None,
            "effects": [
                effect(
                    "Avo_Weapon_AimAssist",
                    1.1,
                    ("GunGameplayAttributes.AimSensitivityMultiplier", "multiply"),
                    override_display_stat_tag="Stats.Combined.AimAssist",
                )
            ],
            "kind": "mod",
        }

        description, lines = project_attachment_description(
            source,
            attribute_metadata=metadata(
                row(
                    "Stats.Combined.AimAssist",
                    "Aim Assist",
                    "Percent",
                    "Multiply",
                    "HigherIsBetter",
                    41,
                )
            ),
        )

        self.assertEqual(description, "+10.0% Aim Assist")
        self.assertEqual(lines[0]["attribute"], "Stats.Combined.AimAssist")

    def test_trait_keeps_rows_filtered_only_by_the_mod_widget(self) -> None:
        source = {
            "description": None,
            "effects": [
                effect(
                    "Avo_Weapon_StoppingPower",
                    1.065,
                    ("DealsDamageAttributes.StoppingPower", "multiply"),
                    (
                        "DealsDamageAttributes.StoppingPower_Secondary",
                        "multiply",
                    ),
                    (
                        "DealsDamageAttributes.StoppingPowerPerSecond",
                        "multiply",
                    ),
                )
            ],
            "kind": "trait",
        }

        description, lines = project_attachment_description(
            source,
            attribute_metadata=metadata(
                row(
                    "DealsDamageAttributes.StoppingPower",
                    "Stopping Power",
                    "Integer",
                    "Multiply",
                    "HigherIsBetter",
                    4,
                ),
                row(
                    "DealsDamageAttributes.StoppingPower_Secondary",
                    "Explosive Stopping Power",
                    "Integer",
                    "Multiply",
                    "HigherIsBetter",
                    5,
                ),
                row(
                    "DealsDamageAttributes.StoppingPowerPerSecond",
                    "Stopping Power Per Second",
                    "Integer",
                    "Multiply",
                    "HigherIsBetter",
                    6,
                ),
            ),
        )

        self.assertEqual(
            description,
            (
                "+6.5% Stopping Power\r\n"
                "+6.5% Explosive Stopping Power\r\n"
                "+6.5% Stopping Power Per Second"
            ),
        )
        self.assertEqual(len(lines), 3)

    def test_trait_picker_uses_its_explicit_reload_label_override(self) -> None:
        source = {
            "description": None,
            "effects": [
                effect(
                    "Avo_Weapon_ReloadSpeed",
                    1.2,
                    ("GunGameplayAttributes.TimeToReload", "divide"),
                )
            ],
            "kind": "trait",
        }

        description, lines = project_attachment_description(
            source,
            attribute_metadata=metadata(
                row(
                    "GunGameplayAttributes.TimeToReload",
                    "Reload Time",
                    "Time",
                    "Divide",
                    "LowerIsBetter",
                    13,
                )
            ),
        )

        self.assertEqual(description, "+20.0% Reload Speed")
        self.assertEqual(lines[0]["result"], "LowerIsBetter")

    def test_authored_trait_description_suppresses_computed_stats(self) -> None:
        source = {
            "description": "-7.5% Cooldown.",
            "effects": [
                effect(
                    "Avo_Weapon_ReloadSpeed",
                    1.2,
                    ("GunGameplayAttributes.TimeToReload", "divide"),
                )
            ],
            "kind": "trait",
        }

        description, lines = project_attachment_description(
            source,
            attribute_metadata=metadata(
                row(
                    "GunGameplayAttributes.TimeToReload",
                    "Reload Time",
                    "Time",
                    "Divide",
                    "LowerIsBetter",
                    13,
                )
            ),
        )

        self.assertEqual(lines, [])
        self.assertEqual(description, "-7.5% Cooldown.")

    def test_normalize_flag_does_not_reciprocal_transform_direct_magnitude(self) -> None:
        source = {
            "description": None,
            "effects": [
                effect(
                    "Avo_Weapon_ReloadSpeed",
                    0.8,
                    ("GunGameplayAttributes.TimeToReload", "divide"),
                    normalize=True,
                )
            ],
            "kind": "mod",
        }

        description, lines = project_attachment_description(
            source,
            attribute_metadata=metadata(
                row(
                    "GunGameplayAttributes.TimeToReload",
                    "Reload Time",
                    "Time",
                    "Divide",
                    "LowerIsBetter",
                    13,
                )
            ),
        )

        self.assertEqual(description, "+20.0% Reload Speed")
        self.assertEqual(lines[0]["statValue"], 20.0)

    def test_scalable_float_stats_precede_the_authored_conditional_section(self) -> None:
        source = {
            "conditionalDescriptions": [
                {
                    "conditionText": "<Bold>While Stationary</>:",
                    "statLines": [
                        {
                            "displayType": "Percent",
                            "result": "HigherIsBetter",
                            "statText": "Stopping Power",
                            "statValue": 20.0,
                        },
                        {
                            "displayType": "Percent",
                            "result": "HigherIsBetter",
                            "statText": "Recoil",
                            "statValue": -20.0,
                        },
                        {
                            "displayType": "Percent",
                            "result": "HigherIsBetter",
                            "statText": "Aim Assist",
                            "statValue": 25.0,
                        },
                    ],
                }
            ],
            "description": None,
            "effects": [
                scalable_effect(
                    "Avo_Attachment_Muzzle_Large_TrianglulatedBrake_Gun_GE",
                    ("DealsDamageAttributes.StoppingPower", "multiply", 1.2),
                    ("GunGameplayAttributes.RecoilMultiplier", "multiply", 0.8),
                    (
                        "GunGameplayAttributes.AimGravityRegionSize",
                        "add",
                        25.0,
                    ),
                )
            ],
            "kind": "mod",
        }

        description, lines = project_attachment_description(
            source,
            attribute_metadata=metadata(
                row(
                    "DealsDamageAttributes.StoppingPower",
                    "Stopping Power",
                    "Integer",
                    "Multiply",
                    "HigherIsBetter",
                    4,
                ),
                row(
                    "GunGameplayAttributes.RecoilMultiplier",
                    "Recoil",
                    "Integer",
                    "Multiply",
                    "LowerIsBetter",
                    20,
                ),
            ),
        )

        self.assertEqual(
            [line["displayText"] for line in lines],
            ["+20.0% Stopping Power", "+20.0% Recoil"],
        )
        self.assertEqual(
            description,
            (
                "+20.0% Stopping Power\r\n"
                "+20.0% Recoil\r\n"
                "<Bold>While Stationary</>:\r\n"
                "  +20% Stopping Power\r\n"
                "  -20% Recoil\r\n"
                "  +25% Aim Assist"
            ),
        )

    def test_mod_hides_equal_fire_rate_limit_row_like_the_client(self) -> None:
        source = {
            "description": None,
            "effects": [
                effect(
                    "Avo_Weapon_FireRate",
                    0.9,
                    ("GunGameplayAttributes.TimeBetweenShots", "divide"),
                    ("GunGameplayAttributes.TimeBetweenShotsLimit", "divide"),
                )
            ],
            "kind": "mod",
        }
        fire_rate_metadata = metadata(
            row(
                "GunGameplayAttributes.TimeBetweenShots",
                "Fire Rate",
                "RoundsPerMinute",
                "Divide",
                "LowerIsBetter",
                11,
            ),
            row(
                "GunGameplayAttributes.TimeBetweenShotsLimit",
                "Fire Rate Limit",
                "RoundsPerMinute",
                "Divide",
                "LowerIsBetter",
                12,
            ),
        )

        description, lines = project_attachment_description(
            source,
            attribute_metadata=fire_rate_metadata,
        )

        self.assertEqual(description, "+10.0% Fire Rate")
        self.assertEqual(
            [line["attribute"] for line in lines],
            ["GunGameplayAttributes.TimeBetweenShots"],
        )

    def test_later_distinct_fire_rate_limit_replaces_the_duplicate(self) -> None:
        source = {
            "description": None,
            "effects": [
                effect(
                    "Avo_Weapon_FireRate",
                    0.9,
                    ("GunGameplayAttributes.TimeBetweenShots", "divide"),
                    ("GunGameplayAttributes.TimeBetweenShotsLimit", "divide"),
                ),
                effect(
                    "Avo_Weapon_FireRateLimit",
                    1.35,
                    ("GunGameplayAttributes.TimeBetweenShotsLimit", "divide"),
                ),
            ],
            "kind": "mod",
        }

        description, lines = project_attachment_description(
            source,
            attribute_metadata=metadata(
                row(
                    "GunGameplayAttributes.TimeBetweenShots",
                    "Fire Rate",
                    "RoundsPerMinute",
                    "Divide",
                    "LowerIsBetter",
                    11,
                ),
                row(
                    "GunGameplayAttributes.TimeBetweenShotsLimit",
                    "Fire Rate Limit",
                    "RoundsPerMinute",
                    "Divide",
                    "LowerIsBetter",
                    12,
                ),
            ),
        )

        self.assertEqual(
            description,
            "+10.0% Fire Rate\r\n+35.0% Fire Rate Limit",
        )
        self.assertEqual([line["statValue"] for line in lines], [10.0, 35.0])

    def test_fire_rate_limit_dedup_compares_projected_values(self) -> None:
        source = {
            "description": None,
            "effects": [
                effect(
                    "Avo_Weapon_FireRate",
                    0.9,
                    ("GunGameplayAttributes.TimeBetweenShots", "divide"),
                ),
                effect(
                    "Avo_Weapon_FireRateLimit",
                    1.1,
                    ("GunGameplayAttributes.TimeBetweenShotsLimit", "divide"),
                ),
            ],
            "kind": "mod",
        }

        description, lines = project_attachment_description(
            source,
            attribute_metadata=metadata(
                row(
                    "GunGameplayAttributes.TimeBetweenShots",
                    "Fire Rate",
                    "RoundsPerMinute",
                    "Divide",
                    "LowerIsBetter",
                    11,
                ),
                row(
                    "GunGameplayAttributes.TimeBetweenShotsLimit",
                    "Fire Rate Limit",
                    "RoundsPerMinute",
                    "Divide",
                    "LowerIsBetter",
                    12,
                ),
            ),
        )

        self.assertEqual(description, "+10.0% Fire Rate")
        self.assertEqual(len(lines), 1)


if __name__ == "__main__":
    unittest.main()
