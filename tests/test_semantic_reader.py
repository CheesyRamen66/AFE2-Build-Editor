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
from afe2_catalogue.semantic_assets import _reader_environment, _run_reader  # noqa: E402
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

                _, request_name, _loose, output_name, _icons = sys.argv[1:]
                request = json.loads(Path(request_name).read_text())
                requested = request["assets"]
                all_fail = os.environ.get("FAKE_ALL_FAIL") == "1"
                successes = [] if all_fail else requested[:1]
                failures = requested if all_fail else requested[1:]
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
                    "icons": [],
                    "failures": [
                        {
                            "stage": "asset",
                            "packagePath": item["packagePath"],
                            "reason": "parse-failed:Synthetic",
                        }
                        for item in failures
                    ],
                }
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


if __name__ == "__main__":
    unittest.main()
