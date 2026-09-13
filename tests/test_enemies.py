from __future__ import annotations

from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from afe2_catalogue.enemies import (  # noqa: E402
    build_enemy_record,
    parent_package,
    parse_class_def_csv,
    parse_difficulty_slider,
    resolve_properties,
    select_enemy_packages,
)
from afe2_catalogue.errors import CatalogueError  # noqa: E402


VENUS_QUEEN = "/Game/Blueprints/Character/VenusEnemies/Xenomorphs/Critter_Avo_Xeno_Queen"
BASE_CRITTER = "/Game/Blueprints/Character/Critters/BaseCritterCharacter"


def text_property(name: str, key: str, invariant: str | None) -> dict[str, object]:
    return {
        "Name": name,
        "Value": key,
        "CultureInvariantString": invariant,
    }


def string_property(name: str, value: str) -> dict[str, object]:
    return {"Name": name, "Value": value}


def asset(
    package_path: str,
    *,
    default_properties: list[dict[str, object]] | None = None,
    component_properties: list[dict[str, object]] | None = None,
    parent_index: int | None = None,
    imports: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    leaf = package_path.rsplit("/", 1)[-1]
    exports: list[dict[str, object]] = [
        {
            "objectName": f"{leaf}_C",
            "superIndex": parent_index if parent_index is not None else 0,
            "data": [],
        },
        {
            "objectName": f"Default__{leaf}_C",
            "data": list(default_properties or []),
        },
    ]
    if component_properties is not None:
        exports.append(
            {
                "objectName": "CritterCharacterComponent_GEN_VARIABLE",
                "data": list(component_properties),
            }
        )
    return {
        "packagePath": package_path,
        "exports": exports,
        "imports": list(imports or []),
    }


class SelectEnemyPackagesTests(unittest.TestCase):
    def test_selects_both_generations_and_rejects_support_assets(self) -> None:
        index = {
            "packages": [
                {"packagePath": VENUS_QUEEN},
                {"packagePath": "/Game/Blueprints/Character/Critters/Xenomorphs/Critter_Xenos_Warrior"},
                # Support assets share the Critter_ prefix but carry no balance.
                {"packagePath": "/Game/Blueprints/Character/Critters/Xenomorphs/AudioMap_Xenos_Queen"},
                {"packagePath": "/Game/Blueprints/Character/Critters/Xenomorphs/Critter_Queen_Ragdoll_DeathAbility"},
                {"packagePath": "/Game/Blueprints/Character/VenusEnemies/Hyperdyne/CritterWeapons/Critter_Avo_Hyperdyne_TurretGun"},
                {"packagePath": "/Game/Blueprints/Character/VenusEnemies/Xenomorphs/Abilities/Critter_Xeno_Melee"},
                {"packagePath": "/Game/Blueprints/Venus_Weapons/Guns/Heavy/Venus_Heavy_Machinegun_SMB94"},
            ]
        }
        self.assertEqual(
            select_enemy_packages(index),
            [
                "/Game/Blueprints/Character/Critters/Xenomorphs/Critter_Xenos_Warrior",
                VENUS_QUEEN,
            ],
        )

    def test_requires_a_packages_array(self) -> None:
        with self.assertRaises(CatalogueError):
            select_enemy_packages({})


class ClassDefParsingTests(unittest.TestCase):
    def test_collapses_constant_rows_and_keeps_varying_ones(self) -> None:
        parsed = parse_class_def_csv(
            ",1,2,3\n"
            "TakesDamageAttributes.HealthMax ,100,200,300\n"
            "TakesDamageAttributes.PenetrationResistance,8,8,8\n"
        )
        self.assertEqual(parsed["levels"], [1, 2, 3])
        self.assertEqual(
            parsed["attributes"]["TakesDamageAttributes.HealthMax"],
            {"status": "byLevel", "byLevel": [100.0, 200.0, 300.0]},
        )
        # A flat row keeps its single authored value rather than N repeats.
        self.assertEqual(
            parsed["attributes"]["TakesDamageAttributes.PenetrationResistance"],
            {"status": "constant", "value": 8.0},
        )

    def test_trailing_whitespace_in_attribute_names_is_stripped(self) -> None:
        parsed = parse_class_def_csv(",1\nTakesDamageAttributes.HealthMax ,10\n")
        self.assertIn("TakesDamageAttributes.HealthMax", parsed["attributes"])

    def test_rejects_a_sheet_without_level_columns(self) -> None:
        with self.assertRaises(CatalogueError):
            parse_class_def_csv(",Easy,Normal\nHealth,1,2\n")

    def test_rejects_duplicated_attribute_rows(self) -> None:
        with self.assertRaises(CatalogueError):
            parse_class_def_csv(",1\nHealth,1\nHealth,2\n")


class DifficultySliderTests(unittest.TestCase):
    def test_parses_named_difficulty_columns(self) -> None:
        parsed = parse_difficulty_slider(
            ",Easy,Normal,Hard\nXPModifier,1,1,1.5\nFriendlyFire,0,0,0.1\n"
        )
        self.assertEqual(parsed["difficulties"], ["Easy", "Normal", "Hard"])
        self.assertEqual(parsed["settings"]["XPModifier"]["Hard"], 1.5)
        self.assertEqual(parsed["settings"]["FriendlyFire"]["Easy"], 0.0)

    def test_rejects_an_empty_sheet(self) -> None:
        with self.assertRaises(CatalogueError):
            parse_difficulty_slider("")


class InheritanceTests(unittest.TestCase):
    def test_parent_package_walks_the_import_outer_chain(self) -> None:
        child = asset(
            VENUS_QUEEN,
            parent_index=-1,
            imports=[
                {"objectName": "BaseCritterCharacter_C", "outerIndex": -2},
                {"objectName": BASE_CRITTER, "outerIndex": 0},
            ],
        )
        self.assertEqual(parent_package(child), BASE_CRITTER)

    def test_identity_is_inherited_when_the_child_does_not_override_it(self) -> None:
        child = asset(
            VENUS_QUEEN,
            default_properties=[string_property("AttributeCSVFileOverride", "AvoCSV_Queen")],
            parent_index=-1,
            imports=[
                {"objectName": "BaseCritterCharacter_C", "outerIndex": -2},
                {"objectName": BASE_CRITTER, "outerIndex": 0},
            ],
        )
        parent = asset(
            BASE_CRITTER,
            component_properties=[
                text_property("DisplayName", "KEY", "Xenomorph Queen"),
                string_property("Rank", "ECritterRank::Elite"),
            ],
        )
        merged, inherited_from, chain = resolve_properties(
            VENUS_QUEEN, {VENUS_QUEEN: child, BASE_CRITTER: parent}
        )
        self.assertEqual(chain, [VENUS_QUEEN, BASE_CRITTER])
        self.assertEqual(inherited_from["DisplayName"], BASE_CRITTER)
        # A row the child does author is not attributed to the parent.
        self.assertNotIn("AttributeCSVFileOverride", inherited_from)
        self.assertEqual(merged["Rank"]["Value"], "ECritterRank::Elite")


class EnemyRecordTests(unittest.TestCase):
    def record(self, sheet: dict[str, object] | None = None) -> dict[str, object]:
        queen = asset(
            VENUS_QUEEN,
            default_properties=[string_property("AttributeCSVFileOverride", "AvoCSV_Queen")],
            component_properties=[
                text_property("DisplayName", "KEY", "Xenomorph Queen"),
                string_property("Rank", "ECritterRank::Elite"),
                string_property("CritterGroup", "ECritterType::Xenomorphs"),
                {"Name": "IsMiniboss", "Value": True},
            ],
        )
        return build_enemy_record(
            package_path=VENUS_QUEEN,
            assets_by_package={VENUS_QUEEN: queen},
            class_defs={"AvoCSV_Queen": sheet} if sheet is not None else {},
        )

    def test_projects_identity_and_defence_rows(self) -> None:
        sheet = parse_class_def_csv(
            ",1,2\n"
            "TakesDamageAttributes.HealthMax,32500,34125\n"
            "TakesDamageAttributes.ShieldMax,10000,10000\n"
            "TakesDamageAttributes.PenetrationResistance,8,8\n"
            "TakesDamageAttributes.PenetrationResistance_Armor,4,4\n"
            "TakesDamageAttributes.ThermalDamage_PercentResistance,-0.1,-0.1\n"
            "TakesDamageAttributes.AcidDamage_PercentResistance,1,1\n"
            "TakesDamageAttributes.BleedBuildUpResistance,-0.2,-0.2\n"
        )
        record = self.record(sheet)
        self.assertEqual(record["displayName"], "Xenomorph Queen")
        self.assertEqual(record["displayNameSource"], "culture-invariant-string")
        self.assertEqual(record["generation"], "venus")
        self.assertEqual(record["rank"], "Elite")
        self.assertEqual(record["critterGroup"], "Xenomorphs")
        self.assertIs(record["isMiniboss"], True)

        stats = record["stats"]
        self.assertEqual(stats["status"], "parsed")
        self.assertEqual(stats["defense"]["penetrationResistance"]["value"], 8.0)
        self.assertEqual(stats["defense"]["penetrationResistanceArmor"]["value"], 4.0)
        self.assertEqual(stats["defense"]["health"]["byLevel"], [32500.0, 34125.0])
        # Bleed follows the elemental sign convention, so a negative value is a
        # vulnerability rather than a resistance.
        self.assertEqual(stats["defense"]["bleedBuildUpResistance"]["value"], -0.2)

        # A negative percent resistance takes extra damage, so it is a weakness;
        # a full 1.0 removes the damage entirely.
        self.assertEqual(stats["elemental"]["weakTo"], ["Thermal"])
        self.assertEqual(stats["elemental"]["immuneTo"], ["Acid"])

    def test_missing_sheet_is_reported_rather_than_dropped(self) -> None:
        record = self.record(None)
        self.assertEqual(record["stats"]["status"], "unresolved")
        self.assertIn("AvoCSV_Queen", record["stats"]["reason"])

    def test_blueprint_without_a_sheet_reference_is_marked_inherited(self) -> None:
        bare = asset(VENUS_QUEEN, default_properties=[])
        record = build_enemy_record(
            package_path=VENUS_QUEEN,
            assets_by_package={VENUS_QUEEN: bare},
            class_defs={},
        )
        self.assertEqual(record["stats"]["status"], "inherited-or-absent")
        self.assertEqual(record["derivedName"], "Critter_Avo_Xeno_Queen")


if __name__ == "__main__":
    unittest.main()
