from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from afe2_catalogue.errors import CatalogueError  # noqa: E402
from afe2_catalogue.semantic_assets import (  # noqa: E402
    _READER_MIN_REQUESTS_PER_JOB,
    _argument_bytes,
    _filter_argument_batches,
    _process_argv_budget,
    _reader_environment,
    _reader_shard_count,
    _run_reader,
)
from afe2_catalogue.semantic_reader import (  # noqa: E402
    ManagedSemanticReader,
    PACKAGE_VERSIONS,
    TARGET_FRAMEWORK,
)


class SemanticReaderLockTests(unittest.TestCase):
    def test_direct_packages_are_exactly_pinned_and_content_locked(self) -> None:
        project = ET.parse(ROOT / "tools/semantic-reader/Afe2.SemanticReader.csproj")
        references = {
            item.attrib["Include"]: item.attrib["Version"].strip("[]")
            for item in project.findall(".//PackageReference")
        }
        lock = json.loads((ROOT / "tools/semantic-reader/packages.lock.json").read_text())
        locked = lock["dependencies"][TARGET_FRAMEWORK]

        self.assertEqual(references, dict(PACKAGE_VERSIONS))
        for name, version in PACKAGE_VERSIONS.items():
            self.assertEqual(locked[name]["type"], "Direct")
            self.assertEqual(locked[name]["resolved"], version)
            self.assertEqual(locked[name]["requested"], f"[{version}, {version}]")
            self.assertTrue(locked[name]["contentHash"])

    def test_semantic_child_environment_never_inherits_archive_key_variables(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"AFE2_AES_KEY": "default-secret", "CUSTOM_ARCHIVE_KEY": "custom-secret"},
            clear=False,
        ):
            environment = _reader_environment(("CUSTOM_ARCHIVE_KEY",))

        self.assertNotIn("AFE2_AES_KEY", environment)
        self.assertNotIn("CUSTOM_ARCHIVE_KEY", environment)

    def test_texture_package_normalizer_rejects_unsafe_shapes_and_is_idempotent(self) -> None:
        dotnet = shutil.which("dotnet")
        if dotnet is None:
            self.skipTest("dotnet is unavailable")
        environment = os.environ.copy()
        environment["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1"
        environment["DOTNET_NOLOGO"] = "1"
        environment["NUGET_PACKAGES"] = str(ROOT / ".tools/nuget-packages")
        restore = subprocess.run(
            [
                dotnet,
                "restore",
                str(ROOT / "tools/semantic-reader/Afe2.SemanticReader.csproj"),
                "--locked-mode",
                "--nologo",
            ],
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(restore.returncode, 0, restore.stderr)
        result = subprocess.run(
            [
                dotnet,
                "run",
                "--project",
                str(ROOT / "tools/semantic-reader/Afe2.SemanticReader.csproj"),
                "--no-restore",
                "--",
                "--self-test-normalizer",
            ],
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(),
            "texture package normalizer self-test passed",
        )


class ReaderPartitionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.work = self.root / "work"
        self.loose = self.root / "loose"
        self.work.mkdir()
        self.loose.mkdir()
        self.script = self.root / "fake-reader.py"
        self.script.write_text(
            textwrap.dedent(
                """\
                import json
                import os
                from pathlib import Path
                import sys

                _, request_name, _loose, output_name, icons_name = sys.argv[1:]
                request = json.loads(Path(request_name).read_text())
                requested = request["assets"]
                requested_icons = request["icons"]
                all_fail = os.environ.get("FAKE_ALL_FAIL") == "1"
                crash_package = os.environ.get("FAKE_CRASH_PACKAGE")
                if any(
                    item["packagePath"] == crash_package
                    for item in [*requested, *requested_icons]
                ):
                    raise SystemExit(9)
                failures = (
                    requested
                    if all_fail
                    else [item for item in requested if item["packagePath"] == "/Game/Two"]
                )
                successes = [item for item in requested if item not in failures]
                icons_root = Path(icons_name)
                for item in requested_icons:
                    if os.environ.get("FAKE_OMIT_ICON") != "1":
                        (icons_root / item["outputName"]).write_bytes(
                            item["packagePath"].encode()
                        )
                output = {
                    "schemaVersion": 1,
                    "readerVersion": "0.1.0",
                    "assets": [
                        {
                            **item,
                            "engineVersion": "VER_UE4_27",
                            "imports": [],
                            "exports": [],
                        }
                        for item in successes
                    ],
                    "icons": [
                        {
                            "packagePath": item["packagePath"],
                            "outputName": item["outputName"],
                            "width": 1,
                            "height": 1,
                            "pixelFormat": "Synthetic",
                        }
                        for item in requested_icons
                    ],
                    "failures": [
                        {
                            "stage": "asset",
                            "packagePath": item["packagePath"],
                            "reason": "parse-failed:Synthetic",
                        }
                        for item in failures
                    ],
                }
                malformed = os.environ.get("FAKE_MALFORMED_ELEMENT")
                if malformed in {"asset", "icon", "failure"}:
                    response_list = {
                        "asset": "assets",
                        "icon": "icons",
                        "failure": "failures",
                    }[malformed]
                    output[response_list].append("not-an-object")
                Path(output_name).write_text(json.dumps(output))
                """
            ),
            encoding="utf-8",
        )
        self.reader = ManagedSemanticReader(
            dotnet=Path(sys.executable),
            dll=self.script,
            source_digest="sha256:fixture",
            lock_digest="sha256:fixture",
            reused=True,
        )
        self.assets = [
            {
                "packagePath": "/Game/One",
                "memberPath": "AFE2/Content/One.uasset",
            },
            {
                "packagePath": "/Game/Two",
                "memberPath": "AFE2/Content/Two.uasset",
            },
        ]

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_exact_success_failure_partition_is_retained(self) -> None:
        document, _ = _run_reader(
            self.reader,
            request={"schemaVersion": 1, "assets": self.assets, "icons": []},
            loose_root=self.loose,
            work=self.work,
            label="partition",
            secret_environment_names=(),
        )

        self.assertEqual([item["packagePath"] for item in document["assets"]], ["/Game/One"])
        self.assertEqual(
            [item["packagePath"] for item in document["failures"]],
            ["/Game/Two"],
        )

    def test_nonempty_request_with_no_parseable_assets_is_systemic_failure(self) -> None:
        with mock.patch.dict(os.environ, {"FAKE_ALL_FAIL": "1"}, clear=False):
            with self.assertRaisesRegex(CatalogueError, "could not parse any"):
                _run_reader(
                    self.reader,
                    request={"schemaVersion": 1, "assets": self.assets, "icons": []},
                    loose_root=self.loose,
                    work=self.work,
                    label="all-fail",
                    secret_environment_names=(),
                )

    def test_sharding_starts_only_when_each_child_has_enough_work(self) -> None:
        boundary = 2 * _READER_MIN_REQUESTS_PER_JOB

        self.assertEqual(_reader_shard_count(boundary - 1, 4), 1)
        self.assertEqual(_reader_shard_count(boundary, 4), 2)
        self.assertEqual(_reader_shard_count(10_000, 4), 4)
        with self.assertRaisesRegex(CatalogueError, "between 1 and 16"):
            _reader_shard_count(10_000, 17)

    def test_parallel_merge_and_icon_copy_are_deterministic(self) -> None:
        assets = [
            {
                "packagePath": f"/Game/Asset{index:03d}",
                "memberPath": f"AFE2/Content/Asset{index:03d}.uasset",
            }
            for index in range(_READER_MIN_REQUESTS_PER_JOB)
        ]
        icons = [
            {
                "packagePath": f"/Game/Icon{index:03d}",
                "memberPath": f"AFE2/Content/Icon{index:03d}.uasset",
                "outputName": f"icon-{index:03d}.png",
            }
            for index in range(_READER_MIN_REQUESTS_PER_JOB)
        ]

        document, icons_root = _run_reader(
            self.reader,
            request={"schemaVersion": 1, "assets": assets, "icons": icons},
            loose_root=self.loose,
            work=self.work,
            label="parallel",
            secret_environment_names=(),
            jobs=4,
        )
        serial_work = self.root / "serial-work"
        serial_work.mkdir()
        serial_document, serial_icons_root = _run_reader(
            self.reader,
            request={"schemaVersion": 1, "assets": assets, "icons": icons},
            loose_root=self.loose,
            work=serial_work,
            label="serial",
            secret_environment_names=(),
            jobs=1,
        )

        self.assertEqual(document, serial_document)
        self.assertEqual(
            [item["packagePath"] for item in document["icons"]],
            sorted(item["packagePath"] for item in icons),
        )
        self.assertEqual(
            (icons_root / "icon-127.png").read_bytes(),
            b"/Game/Icon127",
        )
        self.assertEqual(
            (icons_root / "icon-127.png").read_bytes(),
            (serial_icons_root / "icon-127.png").read_bytes(),
        )
        self.assertTrue((self.work / "parallel-shards/000/reader-request.json").is_file())
        self.assertTrue((self.work / "parallel-shards/001/reader-request.json").is_file())

    def test_parallel_child_crash_fails_the_whole_request(self) -> None:
        assets = [
            {
                "packagePath": f"/Game/Asset{index:03d}",
                "memberPath": f"AFE2/Content/Asset{index:03d}.uasset",
            }
            for index in range(2 * _READER_MIN_REQUESTS_PER_JOB)
        ]
        with mock.patch.dict(
            os.environ,
            {"FAKE_CRASH_PACKAGE": "/Game/Asset001"},
            clear=False,
        ):
            with self.assertRaisesRegex(CatalogueError, "child output was suppressed"):
                _run_reader(
                    self.reader,
                    request={"schemaVersion": 1, "assets": assets, "icons": []},
                    loose_root=self.loose,
                    work=self.work,
                    label="crash",
                    secret_environment_names=(),
                    jobs=2,
                )

    def test_serial_reader_rejects_missing_successful_icon_output(self) -> None:
        icon = {
            "packagePath": "/Game/Icon",
            "memberPath": "AFE2/Content/Icon.uasset",
            "outputName": "icon.png",
        }
        with mock.patch.dict(os.environ, {"FAKE_OMIT_ICON": "1"}, clear=False):
            with self.assertRaisesRegex(CatalogueError, "omitted a decoded icon"):
                _run_reader(
                    self.reader,
                    request={"schemaVersion": 1, "assets": [], "icons": [icon]},
                    loose_root=self.loose,
                    work=self.work,
                    label="missing-icon",
                    secret_environment_names=(),
                    jobs=1,
                )

    def test_serial_reader_rejects_nonobject_response_elements(self) -> None:
        for kind in ("asset", "icon", "failure"):
            with self.subTest(kind=kind):
                work = self.root / f"malformed-{kind}"
                work.mkdir()
                with mock.patch.dict(
                    os.environ,
                    {"FAKE_MALFORMED_ELEMENT": kind},
                    clear=False,
                ):
                    with self.assertRaisesRegex(
                        CatalogueError, "response elements were malformed"
                    ):
                        _run_reader(
                            self.reader,
                            request={
                                "schemaVersion": 1,
                                "assets": self.assets,
                                "icons": [],
                            },
                            loose_root=self.loose,
                            work=work,
                            label="malformed",
                            secret_environment_names=(),
                            jobs=1,
                        )

    def test_parallel_reader_rejects_nonobject_response_elements(self) -> None:
        assets = [
            {
                "packagePath": f"/Game/Asset{index:03d}",
                "memberPath": f"AFE2/Content/Asset{index:03d}.uasset",
            }
            for index in range(2 * _READER_MIN_REQUESTS_PER_JOB)
        ]
        with mock.patch.dict(
            os.environ,
            {"FAKE_MALFORMED_ELEMENT": "asset"},
            clear=False,
        ):
            with self.assertRaisesRegex(
                CatalogueError, "response elements were malformed"
            ):
                _run_reader(
                    self.reader,
                    request={"schemaVersion": 1, "assets": assets, "icons": []},
                    loose_root=self.loose,
                    work=self.work,
                    label="malformed-parallel",
                    secret_environment_names=(),
                    jobs=2,
                )


class ArchiveArgumentBatchTests(unittest.TestCase):
    def test_batching_obeys_encoded_byte_budget(self) -> None:
        base = ["retoc", "--aes-key", "secret", "to-legacy"]
        members = [f"AFE2/Content/Asset{index}.uasset" for index in range(4)]
        pair_size = _argument_bytes(["--filter", members[0]])
        budget = _argument_bytes(base) + pair_size * 2

        batches = _filter_argument_batches(base, members, budget=budget)

        self.assertEqual(len(batches), 2)
        self.assertTrue(all(batch[: len(base)] == base for batch in batches))
        self.assertTrue(all(_argument_bytes(batch) <= budget for batch in batches))

    def test_linux_sized_budget_fits_current_catalogue_in_one_launch(self) -> None:
        base = ["retoc", "--aes-key", "secret", "to-legacy"]
        members = [
            f"AFE2/Content/Blueprints/Generated/Asset_{index:04d}.uasset"
            for index in range(1_189)
        ]

        batches = _filter_argument_batches(base, members, budget=2 * 1024 * 1024)

        self.assertEqual(len(batches), 1)

    def test_argv_budget_uses_conservative_fallback_without_sysconf(self) -> None:
        with mock.patch(
            "afe2_catalogue.semantic_assets.os.sysconf", side_effect=OSError
        ), mock.patch.dict(os.environ, {}, clear=True):
            budget = _process_argv_budget()

        self.assertEqual(budget, 16 * 1024)

    def test_argv_budget_does_not_overpromise_with_nearly_full_environment(self) -> None:
        with mock.patch(
            "afe2_catalogue.semantic_assets.os.sysconf", return_value=32 * 1024
        ), mock.patch.dict(os.environ, {"BLOAT": "x" * (30 * 1024)}, clear=True):
            budget = _process_argv_budget()

        self.assertLess(budget, _argument_bytes(["retoc", "to-legacy"]))
        with self.assertRaisesRegex(CatalogueError, "exceeded the safe argument budget"):
            _filter_argument_batches(
                ["retoc", "to-legacy"],
                ["AFE2/Content/Asset.uasset"],
                budget=budget,
            )


if __name__ == "__main__":
    unittest.main()
