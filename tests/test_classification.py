from __future__ import annotations

import copy
from pathlib import Path
import sys
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from afe2_catalogue.classify import classify_packages  # noqa: E402
from afe2_catalogue.errors import CatalogueError  # noqa: E402
from afe2_catalogue.jsonio import canonical_bytes  # noqa: E402


RULES = REPOSITORY_ROOT / "config/categories.json"


def package(path: str, chunk: str = "01") -> dict[str, object]:
    return {
        "packagePath": path,
        "chunks": [
            {
                "chunkId": chunk,
                "kind": "package",
                "memberPath": f"AFE2/Content/{path.rsplit('/', 1)[-1]}.uasset",
            }
        ],
        "occurrences": 1,
    }


class ClassificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.matching_paths = {
            "kit": "/Game/Blueprints/Avocado_Classes/ClassUnlocks/KitUnlock_Custom",
            "gridShape": "/Game/Blueprints/Avocado_Classes/Custom/Perks/PerkBoard_Custom",
            "ability": "/Game/Blueprints/Avocado_Classes/Custom/Perks/GA_ShockPulse",
            "perk": "/Game/Blueprints/Avocado_Classes/Custom/Perks/Perk_QuickHands",
            "weapon": "/Game/Blueprints/Venus_Weapons/Guns/Rifles/Venus_Artemis",
            "mod": "/Game/Blueprints/Venus_Weapons/Attachments/Optics/Rare/Avo_Cyclops",
            "trait": "/Game/Blueprints/Venus_Weapons/Perks/Mastery/Avo_GunPerk_Overclock",
            "augment": "/Game/Blueprints/Venus_Weapons/Attachments/Overclocks/Rifles/Avo_Overclock_Damage",
        }

    def test_classifies_each_configured_category_and_infers_hints(self) -> None:
        packages = [package(path, f"{index:02x}") for index, path in enumerate(self.matching_paths.values(), 1)]
        packages.extend(
            [
                package("/Game/Blueprints/Venus_Weapons/Guns/Rifles/Venus_Artemis_PR"),
                package("/Game/Blueprints/Venus_Weapons/Unknown/RelevantButUnknown"),
                package("/Game/UI/Unrelated"),
            ]
        )

        result = classify_packages({"packages": packages}, RULES)

        by_kind = {record["kind"]: record for record in result["records"]}
        self.assertEqual(set(by_kind), set(self.matching_paths))
        for kind, expected_path in self.matching_paths.items():
            self.assertEqual(by_kind[kind]["id"], expected_path)
            self.assertEqual(by_kind[kind]["packagePath"], expected_path)
            self.assertEqual(by_kind[kind]["status"], "candidate")
            self.assertEqual(by_kind[kind]["confidence"], "path-heuristic")
            self.assertEqual(len(by_kind[kind]["sourceChunks"]), 1)

        self.assertEqual(by_kind["kit"]["inferred"]["nameHint"], "Custom")
        self.assertEqual(by_kind["ability"]["inferred"]["kitHint"], "Custom")
        self.assertEqual(by_kind["perk"]["inferred"]["nameHint"], "Quick Hands")
        self.assertEqual(by_kind["mod"]["inferred"]["socketHint"], "optic")
        self.assertEqual(
            result["diagnostics"]["unclassifiedRelevantPackages"],
            [
                "/Game/Blueprints/Venus_Weapons/Guns/Rifles/Venus_Artemis_PR",
                "/Game/Blueprints/Venus_Weapons/Unknown/RelevantButUnknown",
            ],
        )
        self.assertEqual(result["diagnostics"]["ambiguous"], [])

    def test_output_is_canonical_when_input_package_order_changes(self) -> None:
        packages = [package(path) for path in self.matching_paths.values()]
        forward = classify_packages({"packages": copy.deepcopy(packages)}, RULES)
        reverse = classify_packages({"packages": list(reversed(copy.deepcopy(packages)))}, RULES)

        self.assertEqual(canonical_bytes(forward), canonical_bytes(reverse))

    def test_future_class_name_is_discovered_without_a_named_class_rule(self) -> None:
        future_paths = {
            "/Game/Blueprints/Avocado_Classes/ClassUnlocks/KitUnlock_Bulwark": "kit",
            "/Game/Blueprints/Avocado_Classes/Bulwark/Perks/PerkBoard_Bulwark": "gridShape",
            (
                "/Game/Blueprints/Avocado_Classes/Bulwark/Perks/ShieldWall/"
                "GA_Bulwark_ShieldWall"
            ): "ability",
            (
                "/Game/Blueprints/Avocado_Classes/Bulwark/Perks/ShieldWall/"
                "Perk_Bulwark_ShieldWall_Base_Tactical"
            ): "perk",
            "/Game/Blueprints/Venus_Weapons/Guns/Gunner/Venus_Gunner_ServicePistol": "weapon",
            "/Game/Blueprints/Avocado_Classes/Perks/Perk_Generic_Core_ShieldBlock": "perk",
        }

        result = classify_packages(
            {"packages": [package(path) for path in future_paths]},
            RULES,
        )
        by_id = {record["id"]: record for record in result["records"]}

        self.assertEqual(
            {path: by_id[path]["kind"] for path in future_paths},
            future_paths,
        )
        self.assertEqual(
            by_id[
                "/Game/Blueprints/Avocado_Classes/Bulwark/Perks/ShieldWall/"
                "Perk_Bulwark_ShieldWall_Base_Tactical"
            ]["inferred"]["kitHint"],
            "Bulwark",
        )
        self.assertEqual(result["diagnostics"]["ambiguous"], [])
        self.assertEqual(
            result["diagnostics"]["unclassifiedRelevantPackages"],
            [],
        )

    def test_save_observed_path_families_remain_evidence_labelled_candidates(self) -> None:
        overclock_info = "/Game/Blueprints/Venus_Weapons/Attachments/Overclocks/Avo_Overclock_Info"
        expected = {
            "/Game/Blueprints/Avocado_Classes/Demolisher/Perks/PerksOld/Perk_Demolisher_Legacy": "perk",
            "/Game/Blueprints/Avocado_Classes/Perks/Modifiers/Perk_Generic_Mod_Test": "perk",
            "/Game/Blueprints/Venus_Weapons/Perks/Perkboard/Avo_Perk_Damage": "perk",
            "/Game/Blueprints/Venus_Weapons/Attachments/Muzzles/Muzzles_Medium/Avo_Muzzle_Test": "mod",
            "/Game/Blueprints/Venus_Weapons/Attachments/Underbarrel/Avo_Underbarrel_Test": "mod",
            "/Game/Blueprints/Venus_Weapons/Attachments/Overclocks/Rifle/Avo_Overclock_Test": "augment",
        }

        result = classify_packages(
            {"packages": [package(path) for path in (*expected, overclock_info)]},
            RULES,
        )
        by_id = {record["id"]: record for record in result["records"]}

        self.assertEqual({path: by_id[path]["kind"] for path in by_id}, expected)
        self.assertEqual(by_id[next(path for path in expected if "/Muzzles/" in path)]["inferred"]["socketHint"], "muzzle")
        self.assertEqual(
            by_id[next(path for path in expected if "/Underbarrel/" in path)]["inferred"]["socketHint"],
            "underbarrel",
        )
        self.assertEqual(
            by_id[next(path for path in expected if "/PerksOld/" in path)]["inferred"]["lifecycleHint"],
            "legacy-path",
        )
        self.assertEqual(
            by_id[next(path for path in expected if "/Overclocks/" in path)]["inferred"]["familyHint"],
            "overclock",
        )
        self.assertNotIn(overclock_info, by_id)
        self.assertIn(overclock_info, result["diagnostics"]["unclassifiedRelevantPackages"])

    def test_conflicting_configured_kinds_become_an_ambiguity(self) -> None:
        rules = {
            "schemaVersion": 7,
            "relevantRoots": ["/Game/Synthetic/"],
            "rules": [
                {
                    "id": "as-kit",
                    "kind": "kit",
                    "include": ["^/Game/Synthetic/Item$"],
                },
                {
                    "id": "as-perk",
                    "kind": "perk",
                    "include": ["^/Game/Synthetic/Item$"],
                },
            ],
        }

        with tempfile.TemporaryDirectory() as temporary:
            rules_path = Path(temporary) / "rules.json"
            rules_path.write_text(__import__("json").dumps(rules), encoding="utf-8")
            result = classify_packages(
                {"packages": [package("/Game/Synthetic/Item")]}, rules_path
            )

        self.assertEqual(result["records"], [])
        self.assertEqual(
            result["diagnostics"]["ambiguous"],
            [
                {
                    "packagePath": "/Game/Synthetic/Item",
                    "possibleKinds": ["kit", "perk"],
                    "rules": ["as-kit", "as-perk"],
                }
            ],
        )

    def test_rejects_package_index_without_packages(self) -> None:
        with self.assertRaisesRegex(CatalogueError, "packages array"):
            classify_packages({}, RULES)

    def test_rejects_unsupported_rule_kind(self) -> None:
        rules = {
            "schemaVersion": 1,
            "relevantRoots": [],
            "rules": [
                {
                    "id": "obsolete-review-kind",
                    "include": ["synthetic"],
                    "kind": "review",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "rules.json"
            path.write_text(__import__("json").dumps(rules), encoding="utf-8")
            with self.assertRaisesRegex(CatalogueError, "unsupported kind"):
                classify_packages({"packages": []}, path)


if __name__ == "__main__":
    unittest.main()
