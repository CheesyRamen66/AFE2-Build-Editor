from __future__ import annotations

from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from afe2_catalogue.archives import parse_repak_list, parse_retoc_manifest  # noqa: E402
from afe2_catalogue.errors import CatalogueError  # noqa: E402


class RetocManifestTests(unittest.TestCase):
    def test_normalizes_merges_and_sorts_package_entries(self) -> None:
        decomposed_path = "/Game/Blueprints/Cafe\u0301/Perk_Test"
        document = {
            "oplog": {
                "entries": [
                    {
                        "packagestoreentry": {"packagename": "/Game/Zeta"},
                        "packagedata": [
                            {
                                "id": "AABB",
                                "filename": "../../../AFE2\\Content\\Zeta.uasset",
                            }
                        ],
                    },
                    {
                        "packagestoreentry": {"packagename": decomposed_path},
                        "packagedata": [
                            {
                                "id": "CAFE",
                                "filename": "../../../AFE2/Content/Cafe\u0301.uasset",
                            }
                        ],
                    },
                    {
                        "packagestoreentry": {"packagename": "/Game/Zeta"},
                        "packagedata": [
                            {
                                "id": "aabb",
                                "filename": "../../../AFE2/Content/Zeta.uasset",
                            }
                        ],
                        "bulkdata": [
                            {
                                "id": "CCDD",
                                "filename": "../../../AFE2/Content/Zeta.ubulk",
                            }
                        ],
                    },
                ]
            }
        }

        packages, warnings = parse_retoc_manifest(document)

        self.assertEqual(warnings, [])
        self.assertEqual(
            [package["packagePath"] for package in packages],
            ["/Game/Blueprints/Caf\u00e9/Perk_Test", "/Game/Zeta"],
        )
        self.assertEqual(packages[0]["occurrences"], 1)
        self.assertEqual(
            packages[0]["chunks"],
            [
                {
                    "chunkId": "cafe",
                    "kind": "package",
                    "memberPath": "AFE2/Content/Caf\u00e9.uasset",
                }
            ],
        )
        self.assertEqual(packages[1]["occurrences"], 2)
        self.assertEqual(
            packages[1]["chunks"],
            [
                {
                    "chunkId": "ccdd",
                    "kind": "bulk",
                    "memberPath": "AFE2/Content/Zeta.ubulk",
                },
                {
                    "chunkId": "aabb",
                    "kind": "package",
                    "memberPath": "AFE2/Content/Zeta.uasset",
                },
            ],
        )

    def test_reports_malformed_entries_without_inventing_packages(self) -> None:
        document = {
            "oplog": {
                "entries": [
                    "not-an-object",
                    {"packagestoreentry": {}},
                    {
                        "packagestoreentry": {"packagename": "/Game/Valid"},
                        "packagedata": "not-an-array",
                    },
                ]
            }
        }

        packages, warnings = parse_retoc_manifest(document)

        self.assertEqual(
            packages,
            [{"packagePath": "/Game/Valid", "chunks": [], "occurrences": 1}],
        )
        self.assertEqual(
            warnings,
            [
                "/Game/Valid had malformed packagedata",
                "manifest entry 0 was not an object",
                "manifest entry 1 had no absolute package name",
            ],
        )

    def test_rejects_document_without_retoc_entries(self) -> None:
        with self.assertRaisesRegex(CatalogueError, r"oplog\.entries"):
            parse_retoc_manifest({"oplog": {}})


class RepakListTests(unittest.TestCase):
    def test_normalizes_deduplicates_and_sorts_members(self) -> None:
        output = """
            AFE2/Content/Zeta.uasset
            ./AFE2/Content/Alpha.uasset
            AFE2\\Content\\Zeta.uasset

        """

        self.assertEqual(
            parse_repak_list(output),
            ["AFE2/Content/Alpha.uasset", "AFE2/Content/Zeta.uasset"],
        )

    def test_rejects_absolute_member_path(self) -> None:
        with self.assertRaisesRegex(CatalogueError, "unsafe archive member"):
            parse_repak_list("/outside/the/archive")

    def test_rejects_parent_traversal_before_normalization(self) -> None:
        with self.assertRaisesRegex(CatalogueError, "unsafe archive member"):
            parse_repak_list("../../outside/the/archive")


if __name__ == "__main__":
    unittest.main()
