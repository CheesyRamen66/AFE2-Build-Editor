from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from afe2_catalogue.diffing import diff_catalogues, diff_record_lists  # noqa: E402
from afe2_catalogue.errors import CatalogueError  # noqa: E402
from afe2_catalogue.jsonio import (  # noqa: E402
    LEGACY_GENERATED_FILENAMES,
    PUBLICATION_MANIFEST,
    canonical_bytes,
    digest_value,
    publish_documents,
    read_json,
    write_json_atomic,
)


class CatalogueDiffTests(unittest.TestCase):
    def test_reports_added_removed_and_nested_field_changes(self) -> None:
        old = {
            "records": {
                "kit": [
                    {
                        "id": "/Game/Synthetic/Changed",
                        "kind": "kit",
                        "displayName": "Before",
                        "metadata": {"a/b": "old", "gone": 3},
                        "tags": ["one"],
                    },
                    {"id": "/Game/Synthetic/Removed", "kind": "kit"},
                ]
            }
        }
        new = {
            "records": {
                "kit": [
                    {"id": "/Game/Synthetic/Added", "kind": "kit"},
                    {
                        "id": "/Game/Synthetic/Changed",
                        "kind": "kit",
                        "displayName": "After",
                        "metadata": {"a/b": "new", "added": 4},
                        "tags": ["two"],
                    },
                ]
            }
        }

        changes = diff_catalogues(old, new)

        self.assertEqual(changes["added"], ["/Game/Synthetic/Added"])
        self.assertEqual(changes["removed"], ["/Game/Synthetic/Removed"])
        self.assertEqual(
            changes["changed"],
            [
                {
                    "id": "/Game/Synthetic/Changed",
                    "fields": [
                        {"path": "/displayName", "before": "Before", "after": "After"},
                        {"path": "/metadata/a~1b", "before": "old", "after": "new"},
                        {"path": "/metadata/added", "before": None, "after": 4},
                        {"path": "/metadata/gone", "before": 3, "after": None},
                        {"path": "/tags", "before": ["one"], "after": ["two"]},
                    ],
                }
            ],
        )

    def test_initial_catalogue_reports_all_ids_as_added_in_sorted_order(self) -> None:
        new = {
            "records": {
                "perk": [{"id": "z", "kind": "perk"}],
                "kit": [{"id": "a", "kind": "kit"}],
            }
        }

        self.assertEqual(diff_catalogues(None, new)["added"], ["a", "z"])

    def test_rejects_duplicate_ids_across_categories(self) -> None:
        document = {
            "records": {
                "kit": [{"id": "same", "kind": "kit"}],
                "perk": [{"id": "same", "kind": "perk"}],
            }
        }

        with self.assertRaisesRegex(CatalogueError, "duplicate ID"):
            diff_catalogues(None, document)

    def test_candidate_record_list_diff_reports_rule_changes(self) -> None:
        old = [{"id": "/Game/A", "kind": "perk", "evidence": ["old"]}]
        new = [
            {"id": "/Game/A", "kind": "perk", "evidence": ["new"]},
            {"id": "/Game/B", "kind": "weapon"},
        ]

        changes = diff_record_lists(old, new)

        self.assertEqual(changes["added"], ["/Game/B"])
        self.assertEqual(changes["removed"], [])
        self.assertEqual(changes["changed"][0]["id"], "/Game/A")
        self.assertEqual(changes["changed"][0]["fields"][0]["path"], "/evidence")


class CanonicalJsonTests(unittest.TestCase):
    def test_key_insertion_order_does_not_change_bytes_or_digest(self) -> None:
        first = {"z": 1, "nested": {"beta": 2, "alpha": "Caf\u00e9"}, "a": 3}
        second = {"a": 3, "nested": {"alpha": "Caf\u00e9", "beta": 2}, "z": 1}

        self.assertEqual(canonical_bytes(first), canonical_bytes(second))
        self.assertEqual(digest_value(first), digest_value(second))

    def test_canonical_json_is_utf8_sorted_indented_and_newline_terminated(self) -> None:
        value = {"z": "Caf\u00e9", "a": 1}

        self.assertEqual(
            canonical_bytes(value),
            '{\n  "a": 1,\n  "z": "Caf\u00e9"\n}\n'.encode("utf-8"),
        )

    def test_publication_refuses_to_replace_unexpected_user_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "catalogue"
            output.mkdir()
            note = output / "notes.txt"
            note.write_text("user data", encoding="utf-8")

            with self.assertRaisesRegex(CatalogueError, "unexpected entries"):
                publish_documents(output, {"catalogue.json": {"schemaVersion": 1}})

            self.assertEqual(note.read_text(encoding="utf-8"), "user data")

    def test_publication_replaces_only_expected_generated_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "catalogue"
            publish_documents(output, {"catalogue.json": {"value": "old"}})
            publish_documents(output, {"catalogue.json": {"value": "new"}})

            self.assertEqual(
                (output / "catalogue.json").read_bytes(),
                canonical_bytes({"value": "new"}),
            )

    def test_publication_archives_the_whole_previous_directory_and_removes_stale_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "catalogue"
            archives = root / "catalogue-archive"
            publish_documents(
                output,
                {
                    "catalogue.json": {"value": "old"},
                    "obsolete-generated.json": {"remove": True},
                },
            )

            archived = publish_documents(
                output,
                {"catalogue.json": {"value": "new"}},
                archive_root=archives,
            )

            self.assertIsNotNone(archived)
            assert archived is not None
            self.assertEqual(
                set(path.name for path in output.iterdir()),
                {"catalogue.json", PUBLICATION_MANIFEST},
            )
            self.assertEqual(
                (archived / "catalogue.json").read_bytes(),
                canonical_bytes({"value": "old"}),
            )
            self.assertTrue((archived / "obsolete-generated.json").is_file())
            self.assertTrue((archived / PUBLICATION_MANIFEST).is_file())

    def test_publication_manages_recursive_binary_files_and_manifest_integrity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "catalogue"
            archives = root / "catalogue-archive"
            icon = b"\x89PNG\r\nsynthetic"
            publish_documents(
                output,
                {"catalogue.json": {"value": "old"}},
                binary_files={"icons/abc.png": icon},
            )

            marker = read_json(output / PUBLICATION_MANIFEST)
            icon_record = next(
                record for record in marker["files"] if record["name"] == "icons/abc.png"
            )
            self.assertEqual(icon_record["sizeBytes"], len(icon))
            self.assertEqual((output / "icons/abc.png").read_bytes(), icon)

            archived = publish_documents(
                output,
                {"catalogue.json": {"value": "new"}},
                archive_root=archives,
            )

            assert archived is not None
            self.assertEqual((archived / "icons/abc.png").read_bytes(), icon)
            self.assertFalse((output / "icons").exists())

    def test_publication_refuses_a_tampered_managed_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "catalogue"
            publish_documents(output, {"catalogue.json": {"value": "old"}})
            (output / "catalogue.json").write_bytes(b"tampered\n")

            with self.assertRaisesRegex(CatalogueError, "integrity check"):
                publish_documents(output, {"catalogue.json": {"value": "new"}})

            self.assertEqual((output / "catalogue.json").read_bytes(), b"tampered\n")

    def test_publication_refuses_nested_symlinks_and_unexpected_empty_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "catalogue"
            publish_documents(
                output,
                {"catalogue.json": {}},
                binary_files={"icons/abc.png": b"icon"},
            )
            (output / "icons/abc.png").unlink()
            (output / "icons/abc.png").symlink_to(root / "missing")

            with self.assertRaisesRegex(CatalogueError, "contains a symlink"):
                publish_documents(output, {"catalogue.json": {"value": "new"}})

            (output / "icons/abc.png").unlink()
            (output / "icons/abc.png").write_bytes(b"icon")
            (output / "unexpected-empty").mkdir()
            with self.assertRaisesRegex(CatalogueError, "unexpected entries"):
                publish_documents(output, {"catalogue.json": {"value": "new"}})

    def test_publication_refuses_output_leaf_symlink_before_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target"
            publish_documents(target, {"catalogue.json": {"value": "keep"}})
            output = root / "catalogue"
            output.symlink_to(target, target_is_directory=True)

            with self.assertRaisesRegex(CatalogueError, "symlink output"):
                publish_documents(output, {"catalogue.json": {"value": "replace"}})

            self.assertEqual(
                (target / "catalogue.json").read_bytes(),
                canonical_bytes({"value": "keep"}),
            )

    def test_tampered_archive_is_not_reused_for_an_identical_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "catalogue"
            archives = root / "catalogue-archive"
            old = {"catalogue.json": {"value": "old"}}
            new = {"catalogue.json": {"value": "new"}}

            publish_documents(output, old)
            first_old_archive = publish_documents(output, new, archive_root=archives)
            assert first_old_archive is not None
            (first_old_archive / "catalogue.json").write_bytes(b"tampered\n")
            publish_documents(output, old, archive_root=archives)
            second_old_archive = publish_documents(output, new, archive_root=archives)

            self.assertNotEqual(second_old_archive, first_old_archive)
            assert second_old_archive is not None
            self.assertTrue(second_old_archive.name.endswith("-01"))
            self.assertEqual(
                (second_old_archive / "catalogue.json").read_bytes(),
                canonical_bytes({"value": "old"}),
            )

    def test_generated_file_and_directory_paths_cannot_collide(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(CatalogueError, "paths collide"):
                publish_documents(
                    Path(temporary) / "catalogue",
                    {"catalogue.json": {}},
                    binary_files={"icons": b"file", "icons/abc.png": b"nested"},
                )

    def test_reserved_manifest_ancestors_and_dot_paths_are_rejected_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "catalogue"
            for unsafe in (".", f"{PUBLICATION_MANIFEST}/child.png"):
                with self.subTest(unsafe=unsafe):
                    with self.assertRaisesRegex(CatalogueError, "unsafe generated filename"):
                        publish_documents(
                            output,
                            {"catalogue.json": {}},
                            binary_files={unsafe: b"payload"},
                        )
            self.assertFalse(output.exists())

    def test_publication_manifest_rejects_boolean_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "catalogue"
            publish_documents(output, {"catalogue.json": {"value": "old"}})
            marker = read_json(output / PUBLICATION_MANIFEST)
            marker["schemaVersion"] = True
            (output / PUBLICATION_MANIFEST).write_bytes(canonical_bytes(marker))

            with self.assertRaisesRegex(CatalogueError, "marker was malformed"):
                publish_documents(output, {"catalogue.json": {"value": "new"}})

    def test_content_identical_previous_publication_reuses_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "catalogue"
            archives = root / "catalogue-archive"
            old = {"catalogue.json": {"value": "old"}}
            new = {"catalogue.json": {"value": "new"}}

            publish_documents(output, old)
            first_old_archive = publish_documents(output, new, archive_root=archives)
            publish_documents(output, old, archive_root=archives)
            second_old_archive = publish_documents(output, new, archive_root=archives)

            self.assertEqual(second_old_archive, first_old_archive)
            self.assertEqual(len(list(archives.iterdir())), 2)

    def test_install_failure_restores_previous_publication_from_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "catalogue"
            archives = root / "catalogue-archive"
            publish_documents(output, {"catalogue.json": {"value": "old"}})
            original_replace = __import__("os").replace
            calls = 0

            def fail_install(source: object, destination: object) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("synthetic install failure")
                original_replace(source, destination)

            with mock.patch("afe2_catalogue.jsonio.os.replace", side_effect=fail_install):
                with self.assertRaisesRegex(OSError, "synthetic install failure"):
                    publish_documents(
                        output,
                        {"catalogue.json": {"value": "new"}},
                        archive_root=archives,
                    )

            self.assertEqual(
                (output / "catalogue.json").read_bytes(),
                canonical_bytes({"value": "old"}),
            )
            self.assertEqual(list(archives.iterdir()), [])

    def test_archive_must_be_disjoint_from_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "catalogue"
            publish_documents(output, {"catalogue.json": {"value": "old"}})

            with self.assertRaisesRegex(CatalogueError, "must not contain each other"):
                publish_documents(
                    output,
                    {"catalogue.json": {"value": "new"}},
                    archive_root=output / "archive",
                )

            self.assertEqual(
                (output / "catalogue.json").read_bytes(),
                canonical_bytes({"value": "old"}),
            )

    def test_legacy_complete_publication_can_be_rebuilt_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "catalogue"
            output.mkdir()
            for name in LEGACY_GENERATED_FILENAMES:
                document = (
                    {"extractor": {"name": "afe2-catalogue"}}
                    if name == "source-manifest.json"
                    else {}
                )
                (output / name).write_bytes(canonical_bytes(document))

            archived = publish_documents(
                output,
                {"catalogue.json": {"value": "new"}},
                archive_root=root / "catalogue-archive",
            )

            self.assertIsNotNone(archived)
            self.assertEqual(
                set(path.name for path in output.iterdir()),
                {"catalogue.json", PUBLICATION_MANIFEST},
            )

    def test_single_json_output_does_not_replace_its_parent_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary) / "existing"
            parent.mkdir()
            preserved = parent / "catalogue.json"
            preserved.write_text("keep", encoding="utf-8")

            destination = parent / "changes.json"
            write_json_atomic(destination, {"added": []})

            self.assertEqual(preserved.read_text(encoding="utf-8"), "keep")
            self.assertEqual(destination.read_bytes(), canonical_bytes({"added": []}))

    def test_single_json_output_refuses_a_symlink_leaf(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target.json"
            target.write_text("keep", encoding="utf-8")
            destination = root / "changes.json"
            destination.symlink_to(target)

            with self.assertRaisesRegex(CatalogueError, "not a regular file"):
                write_json_atomic(destination, {"added": []})

            self.assertEqual(target.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
