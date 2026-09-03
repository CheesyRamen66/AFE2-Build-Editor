from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from afe2_catalogue.errors import CatalogueError  # noqa: E402
from afe2_catalogue.overrides import (  # noqa: E402
    CATEGORY_BY_KIND,
    apply_overrides,
)


KIT_ID = "/Game/Synthetic/KitUnlock_Test"
PERK_ID = "/Game/Synthetic/Perk_Test"


def candidate(candidate_id: str, kind: str) -> dict[str, object]:
    return {
        "id": candidate_id,
        "kind": kind,
        "packagePath": candidate_id,
        "status": "candidate",
    }


class OverrideTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.candidates = {
            "schemaVersion": 1,
            "records": [candidate(KIT_ID, "kit"), candidate(PERK_ID, "perk")],
        }

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write_operations(self, operations: list[dict[str, object]]) -> Path:
        path = self.root / "overrides.json"
        path.write_text(
            json.dumps({"schemaVersion": 1, "operations": operations}),
            encoding="utf-8",
        )
        return path

    def test_promote_replace_suppress_and_build_filter(self) -> None:
        operations = [
            {
                "op": "promote",
                "candidateId": KIT_ID,
                "reason": "Synthetic promotion for a unit test.",
                "record": {
                    "displayName": "Before",
                    "metadata": {"label": "old"},
                },
            },
            {
                "op": "replace",
                "candidateId": KIT_ID,
                "reason": "Exercise an auditable field correction.",
                "path": "/metadata/label",
                "value": "new",
            },
            {
                "op": "suppress",
                "candidateId": PERK_ID,
                "reason": "Synthetic false positive.",
            },
            {
                "op": "replace",
                "candidateId": KIT_ID,
                "reason": "Only applies to another synthetic build.",
                "buildIds": ["other-build"],
                "path": "/displayName",
                "value": "Skipped",
            },
        ]

        catalogue, activity = apply_overrides(
            self.candidates,
            self.write_operations(operations),
            build_id="current-build",
        )

        self.assertEqual(set(catalogue["records"]), set(CATEGORY_BY_KIND.values()))
        self.assertEqual(catalogue["game"]["buildId"], "current-build")
        self.assertEqual(catalogue["records"]["perks"], [])
        self.assertEqual(
            catalogue["records"]["kits"],
            [
                {
                    "id": KIT_ID,
                    "kind": "kit",
                    "displayName": "Before",
                    "metadata": {"label": "new"},
                    "source": {
                        "candidateId": KIT_ID,
                        "packagePath": KIT_ID,
                        "resolution": "override",
                    },
                }
            ],
        )
        self.assertEqual(activity["promotedCandidateIds"], [KIT_ID])
        self.assertEqual(activity["suppressedCandidateIds"], [PERK_ID])
        self.assertEqual(len(activity["applied"]), 3)
        self.assertEqual(
            activity["skipped"],
            [{"candidateId": KIT_ID, "index": 3, "reason": "build does not match"}],
        )

    def test_replace_requires_a_prior_promotion(self) -> None:
        path = self.write_operations(
            [
                {
                    "op": "replace",
                    "candidateId": KIT_ID,
                    "reason": "Invalid ordering.",
                    "path": "/displayName",
                    "value": "Nope",
                }
            ]
        )

        with self.assertRaisesRegex(CatalogueError, "replace must follow promote"):
            apply_overrides(self.candidates, path, build_id=None)

    def test_rejects_two_replacements_of_the_same_field(self) -> None:
        path = self.write_operations(
            [
                {
                    "op": "promote",
                    "candidateId": KIT_ID,
                    "reason": "Synthetic promotion.",
                    "record": {"displayName": "Before"},
                },
                {
                    "op": "replace",
                    "candidateId": KIT_ID,
                    "reason": "First correction.",
                    "path": "/displayName",
                    "value": "First",
                },
                {
                    "op": "replace",
                    "candidateId": KIT_ID,
                    "reason": "Conflicting correction.",
                    "path": "/displayName",
                    "value": "Second",
                },
            ]
        )

        with self.assertRaisesRegex(CatalogueError, "same target"):
            apply_overrides(self.candidates, path, build_id=None)

    def test_rejects_promoting_and_suppressing_the_same_candidate(self) -> None:
        path = self.write_operations(
            [
                {
                    "op": "promote",
                    "candidateId": KIT_ID,
                    "reason": "Synthetic promotion.",
                    "record": {"displayName": "Test"},
                },
                {
                    "op": "suppress",
                    "candidateId": KIT_ID,
                    "reason": "Contradicts the promotion.",
                },
            ]
        )

        with self.assertRaisesRegex(CatalogueError, "promot|suppress|conflict"):
            apply_overrides(self.candidates, path, build_id=None)

    def test_rejects_protected_promoted_fields(self) -> None:
        path = self.write_operations(
            [
                {
                    "op": "promote",
                    "candidateId": KIT_ID,
                    "reason": "Attempt to overwrite provenance.",
                    "record": {"id": "different"},
                }
            ]
        )

        with self.assertRaisesRegex(CatalogueError, "protected field"):
            apply_overrides(self.candidates, path, build_id=None)


if __name__ == "__main__":
    unittest.main()
