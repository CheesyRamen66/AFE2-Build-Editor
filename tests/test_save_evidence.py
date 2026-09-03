from __future__ import annotations

import copy
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from afe2_catalogue.errors import CatalogueError  # noqa: E402
from afe2_catalogue.cli import main  # noqa: E402
from afe2_catalogue.jsonio import canonical_bytes  # noqa: E402
from afe2_catalogue.save_evidence import (  # noqa: E402
    build_save_evidence,
    load_character_save,
    normalize_object_reference,
)


KIT_CLASS = "/Game/Blueprints/Avocado_Classes/Custom/Player_Custom"
KIT_UNLOCK = "/Game/Blueprints/Avocado_Classes/ClassUnlocks/KitUnlock_Custom"
PERK = "/Game/Blueprints/Avocado_Classes/Perks/Modifiers/Perk_Generic_Mod_Test"
WEAPON = "/Game/Blueprints/Venus_Weapons/Guns/Rifles/Venus_Test"
MUZZLE = "/Game/Blueprints/Venus_Weapons/Attachments/Muzzles/Avo_Muzzle_Test"
OVERCLOCK = "/Game/Blueprints/Venus_Weapons/Attachments/Overclocks/Test/Avo_Overclock_Test"
TRAIT = "/Game/Blueprints/Venus_Weapons/Perks/Mastery/Avo_GunPerk_Test"
EMOTE = "/Game/Blueprints/Emotes/EmoteMod_Test"
COSMETIC = "/Game/GeneratedCustomizationData/HeadGearDefinitions/HGDef_Test"
CANDIDATE_ONLY = "/Game/Blueprints/Venus_Weapons/Guns/Rifles/Venus_NotInThisSave"


def object_path(package_path: str) -> str:
    name = package_path.rsplit("/", 1)[-1]
    return f"{package_path}.{name}_C"


def synthetic_save() -> dict[str, object]:
    return {
        "_Type": "CharacterDoc",
        "AccountId": "private-account-value",
        "CharacterName": "private-character-name",
        "LastClassPlayed": object_path(KIT_CLASS),
        "CharacterInventory": {
            "CharacterKits": [
                {
                    "CharacterClass": object_path(KIT_CLASS),
                    "CharacterInstances": [
                        {
                            "AssignedGuns": [101],
                            "AssignedModChipBoard": 201,
                            "AssignedMods": {
                                "AssignedModClasses": [object_path(EMOTE), None, "None"]
                            },
                        }
                    ],
                    "ModChipBoardInstances": [
                        {
                            "_Guid": 201,
                            "CurrentState": {
                                "ModGroups": [
                                    {
                                        "PlacedChips": [
                                            {
                                                "ModDef": object_path(PERK),
                                                "Row": 2,
                                                "Column": 4,
                                                "Rotation": "Clockwise90",
                                            }
                                        ]
                                    }
                                ]
                            }
                        }
                    ],
                }
            ]
        },
        "GunInventory": {
            "GunFrames": [
                {
                    "GunClass": object_path(WEAPON),
                    "LevelData": {"Level": 5},
                    "GunInstances": [
                        {
                            "_Guid": 101,
                            "AssignedMods": {
                                "AssignedModClasses": [
                                    object_path(MUZZLE),
                                    object_path(OVERCLOCK),
                                    object_path(TRAIT),
                                    None,
                                    "None",
                                ]
                            },
                        }
                    ],
                }
            ]
        },
        "ModInventory": {
            "UnlimitedModStorage": [
                {
                    "ModDef": object_path(OVERCLOCK),
                    "OwnedCount": 2,
                    "EquippableCount": 1,
                    "bUnlocked": False,
                }
            ]
        },
        "GeneralInventory": {"Items": [{"Class": object_path(COSMETIC), "Count": 1}]},
    }


def catalogue_documents() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    all_packages = [KIT_CLASS, PERK, WEAPON, MUZZLE, OVERCLOCK, TRAIT, EMOTE, COSMETIC]
    package_index = {
        "sourceFingerprint": "sha256:synthetic",
        "packages": [{"packagePath": value} for value in all_packages],
    }
    candidates = {
        "sourceFingerprint": "sha256:synthetic",
        "records": [
            {"id": WEAPON, "kind": "weapon", "packagePath": WEAPON},
            {"id": TRAIT, "kind": "trait", "packagePath": TRAIT},
            {"id": CANDIDATE_ONLY, "kind": "weapon", "packagePath": CANDIDATE_ONLY},
        ],
    }
    planner_catalogue = {
        "sourceFingerprint": "sha256:synthetic",
        "records": [
            {
                "characterClassPackagePath": KIT_CLASS,
                "id": KIT_UNLOCK,
                "kind": "kit",
            },
            {"id": WEAPON, "kind": "weapon", "packagePath": WEAPON},
            {"id": TRAIT, "kind": "trait", "packagePath": TRAIT},
        ],
    }
    return package_index, candidates, planner_catalogue


def evidence_for(save: dict[str, object] | None = None) -> dict[str, object]:
    package_index, candidates, planner_catalogue = catalogue_documents()
    return build_save_evidence(
        synthetic_save() if save is None else save,
        normalization="none",
        package_index=package_index,
        candidates=candidates,
        planner_catalogue=planner_catalogue,
    )


class SaveLoadingTests(unittest.TestCase):
    def test_loads_ordinary_json_without_normalization(self) -> None:
        document = {"_Type": "CharacterDoc", "Value": 1}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "char.dec"
            path.write_text(json.dumps(document), encoding="utf-8")

            loaded, normalization = load_character_save(path)

            self.assertEqual(loaded, document)
            self.assertEqual(normalization, "none")

    def test_normalizes_only_a_terminal_question_mark_without_writing_the_save(self) -> None:
        document = {"_Type": "CharacterDoc", "Value": 1}
        encoded = json.dumps(document).encode("utf-8")
        encoded = encoded[:-1] + b"?"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "char.dec"
            path.write_bytes(encoded)

            loaded, normalization = load_character_save(path)

            self.assertEqual(loaded, document)
            self.assertEqual(normalization, "terminal-question-mark-to-closing-brace")
            self.assertEqual(path.read_bytes(), encoded)

    def test_rejects_invalid_json_and_non_character_documents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "char.dec"
            path.write_text('{"_Type":"CharacterDoc","bad":?}', encoding="utf-8")
            with self.assertRaisesRegex(CatalogueError, "not readable"):
                load_character_save(path)

            path.write_text('{"_Type":"SomethingElse"}', encoding="utf-8")
            with self.assertRaisesRegex(CatalogueError, "CharacterDoc"):
                load_character_save(path)

            path.write_bytes(b'{"_Type":"CharacterDoc"?\n')
            with self.assertRaisesRegex(CatalogueError, "not readable"):
                load_character_save(path)

    def test_object_reference_normalization_uses_the_package_prefix(self) -> None:
        self.assertEqual(
            normalize_object_reference("/Game/Path/MixedAsset.mixedasset_C"),
            "/Game/Path/MixedAsset",
        )
        self.assertEqual(normalize_object_reference("/Game/Path/PackageOnly"), "/Game/Path/PackageOnly")
        self.assertEqual(
            normalize_object_reference("/Game/Path.v1/MixedAsset.mixedasset_C"),
            "/Game/Path.v1/MixedAsset",
        )
        self.assertEqual(
            normalize_object_reference("/Game/Path.v1/PackageOnly"),
            "/Game/Path.v1/PackageOnly",
        )
        self.assertEqual(
            normalize_object_reference("/Game/Cafe\u0301/Asset.Asset_C"),
            "/Game/Caf\u00e9/Asset",
        )
        self.assertIsNone(normalize_object_reference("/Script/CoreUObject.Object"))
        self.assertIsNone(normalize_object_reference("None"))


class SaveEvidenceTests(unittest.TestCase):
    def test_collects_positive_asset_roles_relations_and_inventory_facts(self) -> None:
        result = evidence_for()
        records = {record["id"]: record for record in result["records"]}

        self.assertEqual(result["schemaVersion"], 2)
        self.assertEqual(result["scope"]["completeness"], "partial-save")
        self.assertEqual(result["scope"]["absenceMeans"], "not-observed")
        self.assertEqual(result["source"]["directIdentifiersIncluded"], False)
        self.assertNotIn(CANDIDATE_ONLY, records)
        self.assertNotIn("private-account-value", canonical_bytes(result).decode("utf-8"))
        self.assertNotIn("private-character-name", canonical_bytes(result).decode("utf-8"))

        self.assertEqual(records[WEAPON]["candidateKinds"], ["weapon"])
        self.assertEqual(records[WEAPON]["plannerKinds"], ["weapon"])
        self.assertEqual(
            records[WEAPON]["weaponUsage"],
            {
                "assignedInstanceCount": 1,
                "frameCount": 1,
                "instanceCount": 1,
            },
        )
        self.assertEqual(records[MUZZLE]["kindEvidence"][0]["kind"], "mod")
        self.assertEqual(records[OVERCLOCK]["kindEvidence"][0]["kind"], "augment")
        self.assertEqual(records[TRAIT]["kindEvidence"][0]["kind"], "trait")
        self.assertEqual(records[OVERCLOCK]["weaponAssignments"][0]["weaponId"], WEAPON)
        self.assertTrue(
            records[OVERCLOCK]["weaponAssignments"][0]["assignedToSavedLoadout"]
        )
        self.assertEqual(
            records[OVERCLOCK]["modInventory"],
            {
                "entries": 1,
                "equippableCount": 1,
                "ownedCount": 2,
                "unlockedFalseEntries": 1,
                "unlockedTrueEntries": 0,
            },
        )

        placement = records[PERK]["perkPlacements"][0]
        self.assertTrue(placement["assignedToSavedLoadout"])
        self.assertEqual(
            {key: placement[key] for key in ("kitClassId", "row", "column", "rotation")},
            {
                "kitClassId": KIT_CLASS,
                "row": 2,
                "column": 4,
                "rotation": "Clockwise90",
            },
        )
        self.assertEqual(records[KIT_CLASS]["plannerAliases"], [KIT_UNLOCK])
        self.assertEqual(
            result["kitAliases"][0]["method"],
            "character-class-package-path",
        )
        self.assertEqual(
            records[WEAPON]["kitWeaponAssignments"],
            [{"count": 1, "kitClassId": KIT_CLASS, "savedGunSlotIndex": 0}],
        )
        self.assertEqual(records[COSMETIC]["generalInventory"], {"count": 1, "entries": 1})
        self.assertEqual(result["diagnostics"]["unresolvedGunReferenceCount"], 0)
        self.assertEqual(result["diagnostics"]["unresolvedBoardReferenceCount"], 0)

    def test_character_assigned_mods_are_not_weapon_components(self) -> None:
        records = {record["id"]: record for record in evidence_for()["records"]}

        self.assertNotIn("weaponAssignments", records[EMOTE])
        self.assertEqual(records[EMOTE]["kindEvidence"], [])
        self.assertEqual(
            records[EMOTE]["saveRoles"],
            [{"occurrences": 1, "role": "character-loadout-item"}],
        )

    def test_output_is_deterministic_when_object_key_order_changes(self) -> None:
        first = evidence_for()
        reordered = {key: copy.deepcopy(synthetic_save()[key]) for key in reversed(synthetic_save())}
        second = evidence_for(reordered)

        self.assertEqual(canonical_bytes(first), canonical_bytes(second))

    def test_reports_package_gaps_without_dropping_the_asset(self) -> None:
        save = synthetic_save()
        missing = "/Game/Synthetic/ObservedButNotIndexed"
        save["GeneralInventory"]["Items"].append(
            {"Class": object_path(missing), "Count": 1}
        )

        result = evidence_for(save)
        records = {record["id"]: record for record in result["records"]}

        self.assertIn(missing, records)
        self.assertFalse(records[missing]["packageIndexed"])
        self.assertEqual(result["summary"]["missingPackageAssets"], 1)

    def test_user_controlled_text_that_looks_like_an_asset_is_not_emitted(self) -> None:
        save = synthetic_save()
        marker = "/Game/private-marker.Private_C"
        save["Name"] = marker
        save["Nickname"] = marker

        result = evidence_for(save)

        self.assertNotIn("/Game/private-marker", {record["id"] for record in result["records"]})
        self.assertNotIn(marker, canonical_bytes(result).decode("utf-8"))

    def test_rejects_mixed_catalogue_fingerprints(self) -> None:
        package_index, candidates, planner_catalogue = catalogue_documents()
        planner_catalogue["sourceFingerprint"] = "sha256:different"

        with self.assertRaisesRegex(CatalogueError, "different source fingerprints"):
            build_save_evidence(
                synthetic_save(),
                normalization="none",
                package_index=package_index,
                candidates=candidates,
                planner_catalogue=planner_catalogue,
            )

    def test_rejects_malformed_or_duplicate_planner_records(self) -> None:
        package_index, candidates, planner_catalogue = catalogue_documents()
        for records, message in (([42], "invalid record"), ([{"id": "same"}] * 2, "duplicate ID")):
            malformed = {**planner_catalogue, "records": records}
            with self.subTest(message=message), self.assertRaisesRegex(
                CatalogueError,
                message,
            ):
                build_save_evidence(
                    synthetic_save(),
                    normalization="none",
                    package_index=package_index,
                    candidates=candidates,
                    planner_catalogue=malformed,
                )


class SaveEvidenceCliTests(unittest.TestCase):
    def test_inspect_save_writes_a_separate_report_without_changing_inputs(self) -> None:
        package_index, candidates, planner_catalogue = catalogue_documents()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalogue_root = root / "catalogue"
            catalogue_root.mkdir()
            for filename, document in (
                ("package-index.json", package_index),
                ("candidate-records.json", candidates),
                ("planner-catalogue.json", planner_catalogue),
            ):
                (catalogue_root / filename).write_text(json.dumps(document), encoding="utf-8")
            save_path = root / "char.dec"
            save_bytes = json.dumps(synthetic_save()).encode("utf-8")
            save_bytes = save_bytes[:-1] + b"?"
            save_path.write_bytes(save_bytes)
            output = root / "save-evidence.json"

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                result = main(
                    [
                        "inspect-save",
                        str(save_path),
                        "--catalogue-dir",
                        str(catalogue_root),
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(result, 0)
            self.assertEqual(save_path.read_bytes(), save_bytes)
            self.assertEqual(json.loads(output.read_text())["summary"]["assets"], 8)
            self.assertIn("partial save evidence", stdout.getvalue())
            self.assertIn("planner=", stdout.getvalue())

    def test_inspect_save_refuses_output_inside_the_catalogue_publication(self) -> None:
        package_index, candidates, planner_catalogue = catalogue_documents()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalogue_root = root / "catalogue"
            catalogue_root.mkdir()
            for filename, document in (
                ("package-index.json", package_index),
                ("candidate-records.json", candidates),
                ("planner-catalogue.json", planner_catalogue),
            ):
                (catalogue_root / filename).write_text(json.dumps(document), encoding="utf-8")
            save_path = root / "char.dec"
            save_path.write_text(json.dumps(synthetic_save()), encoding="utf-8")
            output = catalogue_root / "save-evidence.json"

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                result = main(
                    [
                        "inspect-save",
                        str(save_path),
                        "--catalogue-dir",
                        str(catalogue_root),
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(result, 2)
            self.assertFalse(output.exists())
            self.assertIn("outside the generated catalogue", stderr.getvalue())

    def test_inspect_save_refuses_to_replace_a_json_named_source_save(self) -> None:
        package_index, candidates, planner_catalogue = catalogue_documents()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalogue_root = root / "catalogue"
            catalogue_root.mkdir()
            for filename, document in (
                ("package-index.json", package_index),
                ("candidate-records.json", candidates),
                ("planner-catalogue.json", planner_catalogue),
            ):
                (catalogue_root / filename).write_text(json.dumps(document), encoding="utf-8")
            save_path = root / "character.json"
            original = json.dumps(synthetic_save())
            save_path.write_text(original, encoding="utf-8")

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                result = main(
                    [
                        "inspect-save",
                        str(save_path),
                        "--catalogue-dir",
                        str(catalogue_root),
                        "--output",
                        str(save_path),
                    ]
                )

            self.assertEqual(result, 2)
            self.assertEqual(save_path.read_text(encoding="utf-8"), original)
            self.assertIn("must not replace the source save", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
