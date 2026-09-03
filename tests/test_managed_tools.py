from __future__ import annotations

import contextlib
import io
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


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from afe2_catalogue.cli import (  # noqa: E402
    SEMANTIC_PYTHON_SOURCES,
    _managed_tools_for_extract,
    _record_tool_provenance,
    build_parser,
)
from afe2_catalogue.errors import CatalogueError  # noqa: E402
from afe2_catalogue.managed_tools import (  # noqa: E402
    ManagedTool,
    ToolSpec,
    ensure_managed_tools,
)


def run_git(repository: Path, *arguments: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repository), *arguments],
        text=True,
    ).strip()


class ManagedToolBootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.origin = self.root / "synthetic-origin"
        self.origin.mkdir()
        subprocess.run(["git", "init", "-q", str(self.origin)], check=True)
        run_git(self.origin, "config", "user.name", "Synthetic Test")
        run_git(self.origin, "config", "user.email", "synthetic@example.invalid")
        (self.origin / ".gitignore").write_text("/target/\n", encoding="utf-8")
        (self.origin / "Cargo.toml").write_text(
            "[package]\nname = \"synthetic_cli\"\nversion = \"1.2.3\"\n",
            encoding="utf-8",
        )
        (self.origin / "Cargo.lock").write_text(
            "# Synthetic lockfile for managed-tool tests.\n",
            encoding="utf-8",
        )
        run_git(self.origin, "add", ".")
        run_git(self.origin, "commit", "-q", "-m", "synthetic source")
        run_git(self.origin, "tag", "-a", "v1.2.3", "-m", "synthetic release")
        revision = run_git(self.origin, "rev-parse", "HEAD")
        self.spec = ToolSpec(
            name="synthetic",
            repository=str(self.origin.resolve()),
            tag="v1.2.3",
            revision=revision,
            version="1.2.3",
            cargo_package="synthetic_cli",
            binary_name="synthetic",
        )
        self.specs = {self.spec.name: self.spec}
        self.cargo_log = self.root / "cargo-log.jsonl"
        self.fake_cargo = self.root / "fake-cargo"
        self.fake_cargo.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import json
                import os
                from pathlib import Path
                import sys

                arguments = sys.argv[1:]
                for name in os.environ.get("FAKE_REJECT_ENV", "").split(","):
                    if name and name in os.environ:
                        raise SystemExit("secret environment variable was inherited: " + name)
                if arguments == ["-Vv"]:
                    print("cargo 1.85.0")
                    print("host: synthetic-host")
                    raise SystemExit(0)
                with Path(os.environ["FAKE_CARGO_LOG"]).open("a", encoding="utf-8") as log:
                    log.write(json.dumps(arguments) + "\\n")
                target = Path(arguments[arguments.index("--target-dir") + 1])
                host = arguments[arguments.index("--target") + 1]
                binary_name = arguments[arguments.index("--bin") + 1]
                version = os.environ.get("FAKE_TOOL_VERSION", "1.2.3")
                binary = target / host / "release" / binary_name
                binary.parent.mkdir(parents=True, exist_ok=True)
                binary.write_text(
                    "#!/usr/bin/env python3\\n"
                    "import os\\n"
                    "for name in os.environ.get('FAKE_REJECT_ENV', '').split(','):\\n"
                    "    if name and name in os.environ:\\n"
                    "        raise SystemExit('secret environment variable was inherited: ' + name)\\n"
                    "print('synthetic_cli " + version + "')\\n",
                    encoding="utf-8",
                )
                binary.chmod(0o755)
                """
            ),
            encoding="utf-8",
        )
        self.fake_cargo.chmod(0o755)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def ensure(
        self,
        *,
        cargo: Path | None = None,
        secret_environment_names: tuple[str, ...] = (),
    ) -> ManagedTool:
        with mock.patch.dict(
            os.environ,
            {"FAKE_CARGO_LOG": str(self.cargo_log)},
            clear=False,
        ):
            return ensure_managed_tools(
                self.project,
                ("synthetic",),
                specs=self.specs,
                cargo_executable=cargo or self.fake_cargo,
                secret_environment_names=secret_environment_names,
            )["synthetic"]

    def cargo_invocations(self) -> list[list[str]]:
        if not self.cargo_log.is_file():
            return []
        return [json.loads(line) for line in self.cargo_log.read_text().splitlines()]

    def test_first_run_clones_pinned_source_and_builds_with_locked_arguments(self) -> None:
        tool = self.ensure()

        self.assertFalse(tool.reused)
        self.assertEqual(tool.checkout, self.project / ".tools" / "synthetic")
        self.assertEqual(tool.binary, tool.checkout / "target/release/synthetic")
        self.assertEqual(run_git(tool.checkout, "rev-parse", "HEAD"), self.spec.revision)
        self.assertEqual(run_git(tool.checkout, "remote", "get-url", "origin"), self.spec.repository)
        self.assertEqual(run_git(tool.checkout, "status", "--porcelain"), "")
        self.assertEqual(tool.binary.read_text(encoding="utf-8").count("1.2.3"), 1)
        marker = tool.binary.parent / ".afe2-managed-tool.json"
        self.assertEqual(json.loads(marker.read_text())["revision"], self.spec.revision)
        self.assertTrue(json.loads(marker.read_text())["binaryDigest"].startswith("sha256:"))

        invocations = self.cargo_invocations()
        self.assertEqual(len(invocations), 1)
        arguments = invocations[0]
        self.assertEqual(arguments[0], "build")
        self.assertIn("--locked", arguments)
        self.assertEqual(arguments[arguments.index("--target") + 1], "synthetic-host")
        self.assertEqual(arguments[arguments.index("--package") + 1], "synthetic_cli")
        self.assertEqual(arguments[arguments.index("--bin") + 1], "synthetic")
        self.assertEqual(
            Path(arguments[arguments.index("--target-dir") + 1]),
            tool.checkout / "target",
        )
        self.assertEqual(
            Path(arguments[arguments.index("--manifest-path") + 1]),
            tool.checkout / "Cargo.toml",
        )

    def test_cached_tool_is_reused_without_cargo(self) -> None:
        first = self.ensure()
        missing_cargo = self.root / "cargo-does-not-exist"

        second = self.ensure(cargo=missing_cargo)

        self.assertFalse(first.reused)
        self.assertTrue(second.reused)
        self.assertEqual(first.binary, second.binary)
        self.assertEqual(len(self.cargo_invocations()), 1)

    def test_wrong_binary_version_is_rebuilt(self) -> None:
        first = self.ensure()
        first.binary.write_text(
            "#!/usr/bin/env python3\nprint('synthetic_cli 0.0.0')\n",
            encoding="utf-8",
        )
        first.binary.chmod(0o755)

        rebuilt = self.ensure()

        self.assertFalse(rebuilt.reused)
        self.assertEqual(len(self.cargo_invocations()), 2)
        self.assertIn("1.2.3", rebuilt.binary.read_text(encoding="utf-8"))

    def test_missing_binary_with_stale_marker_is_rebuilt(self) -> None:
        first = self.ensure()
        first.binary.unlink()

        rebuilt = self.ensure()

        self.assertFalse(rebuilt.reused)
        self.assertTrue(rebuilt.binary.is_file())
        self.assertEqual(len(self.cargo_invocations()), 2)

    def test_same_version_foreign_binary_is_rebuilt_from_pinned_source(self) -> None:
        first = self.ensure()
        cargo_artifact = first.checkout / "target/synthetic-host/release/synthetic"
        first.binary.write_text(
            "#!/usr/bin/env python3\nprint('synthetic_cli 1.2.3')\n# foreign replacement\n",
            encoding="utf-8",
        )
        first.binary.chmod(0o755)
        self.assertNotIn("foreign replacement", cargo_artifact.read_text(encoding="utf-8"))

        rebuilt = self.ensure()

        self.assertFalse(rebuilt.reused)
        self.assertEqual(len(self.cargo_invocations()), 2)
        self.assertNotIn("foreign replacement", rebuilt.binary.read_text(encoding="utf-8"))

    def test_dirty_checkout_is_rejected_and_preserved(self) -> None:
        tool = self.ensure()
        sentinel = tool.checkout / "keep-me.txt"
        sentinel.write_text("user data\n", encoding="utf-8")

        with self.assertRaisesRegex(CatalogueError, "local changes"):
            self.ensure()

        self.assertEqual(sentinel.read_text(encoding="utf-8"), "user data\n")
        self.assertEqual(len(self.cargo_invocations()), 1)

    def test_unexpected_pinned_revision_never_publishes_checkout(self) -> None:
        wrong_spec = ToolSpec(
            **{**self.spec.__dict__, "revision": "0" * 40}
        )

        with self.assertRaisesRegex(CatalogueError, "expected"):
            ensure_managed_tools(
                self.project,
                ("synthetic",),
                specs={"synthetic": wrong_spec},
                cargo_executable=self.fake_cargo,
            )

        self.assertFalse((self.project / ".tools/synthetic").exists())
        self.assertEqual(list((self.project / ".tools").glob(".synthetic-clone-*")), [])

    def test_symlink_checkout_is_rejected_without_touching_target(self) -> None:
        tools_root = self.project / ".tools"
        tools_root.mkdir()
        target = self.root / "user-owned-directory"
        target.mkdir()
        sentinel = target / "sentinel"
        sentinel.write_text("unchanged", encoding="utf-8")
        (tools_root / "synthetic").symlink_to(target, target_is_directory=True)

        with self.assertRaisesRegex(CatalogueError, "must not be a symlink"):
            self.ensure()

        self.assertEqual(sentinel.read_text(encoding="utf-8"), "unchanged")

    def test_symlink_release_directory_cannot_redirect_a_build(self) -> None:
        tool = self.ensure()
        shutil.rmtree(tool.checkout / "target/release")
        external = self.root / "external-target"
        external.mkdir()
        sentinel = external / "sentinel"
        sentinel.write_text("unchanged", encoding="utf-8")
        (tool.checkout / "target/release").symlink_to(external, target_is_directory=True)

        with self.assertRaisesRegex(CatalogueError, "release directory must not be a symlink"):
            self.ensure()

        self.assertEqual(sentinel.read_text(encoding="utf-8"), "unchanged")
        self.assertFalse((external / "synthetic").exists())
        self.assertEqual(len(self.cargo_invocations()), 1)

    def test_archive_key_environment_is_not_inherited_by_bootstrap_commands(self) -> None:
        secret_name = "SYNTHETIC_ARCHIVE_KEY"
        with mock.patch.dict(
            os.environ,
            {
                secret_name: "synthetic-test-secret",
                "FAKE_REJECT_ENV": secret_name,
            },
            clear=False,
        ):
            tool = self.ensure(secret_environment_names=(secret_name,))

        self.assertTrue(tool.binary.is_file())

    def test_regular_file_at_tools_path_reports_a_controlled_error(self) -> None:
        tools_path = self.project / ".tools"
        tools_path.write_text("user data\n", encoding="utf-8")

        with self.assertRaisesRegex(CatalogueError, "could not create managed tools directory"):
            self.ensure()

        self.assertEqual(tools_path.read_text(encoding="utf-8"), "user data\n")

    def test_directory_at_lock_path_reports_a_controlled_error(self) -> None:
        tools_path = self.project / ".tools"
        tools_path.mkdir()
        lock_path = tools_path / ".bootstrap.lock"
        lock_path.mkdir()

        with self.assertRaisesRegex(CatalogueError, "could not open managed-tools lock"):
            self.ensure()

        self.assertTrue(lock_path.is_dir())


class ManagedToolCliTests(unittest.TestCase):
    def test_extract_selects_only_the_tools_needed_for_each_mode(self) -> None:
        cases = (
            (None, False, ["retoc", "repak"]),
            (None, True, ["retoc"]),
            (Path("pakstore.json"), False, ["repak"]),
            (Path("pakstore.json"), True, []),
        )
        for manifest, no_pak_index, expected in cases:
            with self.subTest(manifest=manifest, no_pak_index=no_pak_index), mock.patch(
                "afe2_catalogue.cli.ensure_managed_tools", return_value={}
            ) as ensure:
                args = mock.Mock(
                    manifest=manifest,
                    no_pak_index=no_pak_index,
                    aes_key_env="CUSTOM_AFE2_KEY",
                )
                self.assertEqual(_managed_tools_for_extract(args), {})
                self.assertEqual(ensure.call_args.args[1], expected)
                self.assertEqual(
                    ensure.call_args.kwargs["secret_environment_names"],
                    ("CUSTOM_AFE2_KEY",),
                )

    def test_cli_no_longer_accepts_external_tool_paths(self) -> None:
        parser = build_parser()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
            parser.parse_args(["doctor", "--retoc", "/tmp/retoc"])

        self.assertIn("unrecognized arguments: --retoc", stderr.getvalue())

    def test_extract_archives_by_default_and_archive_flags_are_exclusive(self) -> None:
        parser = build_parser()

        defaults = parser.parse_args(["extract"])
        self.assertFalse(defaults.no_archive)
        self.assertIsNone(defaults.archive_dir)

        custom = parser.parse_args(["extract", "--archive-dir", "/tmp/history"])
        self.assertEqual(custom.archive_dir, Path("/tmp/history"))
        self.assertFalse(custom.no_archive)

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
            parser.parse_args(
                ["extract", "--archive-dir", "/tmp/history", "--no-archive"]
            )
        self.assertIn("not allowed with argument", stderr.getvalue())

    def test_managed_provenance_is_added_to_adapter(self) -> None:
        spec = ToolSpec(
            name="synthetic",
            repository="https://example.invalid/synthetic.git",
            tag="v1.2.3",
            revision="1" * 40,
            version="1.2.3",
            cargo_package="synthetic_cli",
            binary_name="synthetic",
        )
        tool = ManagedTool(
            spec=spec,
            checkout=Path(".tools/synthetic"),
            binary=Path(".tools/synthetic/target/release/synthetic"),
            reused=True,
        )
        document = {"adapter": {"name": "synthetic", "version": "1.2.3"}}

        _record_tool_provenance(document, tool)

        self.assertEqual(
            document["adapter"],
            {
                "name": "synthetic",
                "repository": spec.repository,
                "revision": spec.revision,
                "tag": spec.tag,
                "version": spec.version,
            },
        )

    def test_semantic_provenance_covers_planner_normalization_modules(self) -> None:
        source_names = {path.name for path in SEMANTIC_PYTHON_SOURCES}

        self.assertTrue(
            {
                "collection.py",
                "planner_catalogue.py",
                "weapon_compatibility.py",
            }
            <= source_names
        )


if __name__ == "__main__":
    unittest.main()
