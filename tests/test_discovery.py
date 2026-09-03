from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from afe2_catalogue.discovery import (  # noqa: E402
    APP_ID,
    ArchiveFile,
    DiscoveryError,
    common_libraryfolders_paths,
    discover_game_installation,
    discover_source_inventory,
    inventory_archives,
    parse_app_manifest,
    parse_library_folders,
    validate_game_directory,
)


class DiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def make_game(
        self, game_dir: Path, archives: dict[str, bytes] | None = None
    ) -> Path:
        paks_dir = game_dir / "AFE2/Content/Paks"
        shipping_executable = (
            game_dir / "AFE2/Binaries/Win64/AFE2-Win64-Shipping.exe"
        )
        paks_dir.mkdir(parents=True, exist_ok=True)
        shipping_executable.parent.mkdir(parents=True, exist_ok=True)
        shipping_executable.write_bytes(b"")
        for relative_path, content in (archives or {}).items():
            archive_path = paks_dir / relative_path
            archive_path.parent.mkdir(parents=True, exist_ok=True)
            archive_path.write_bytes(content)
        return game_dir

    def write_manifest(
        self,
        library_root: Path,
        *,
        install_dir: str = "Aliens Fireteam Elite 2",
        build_id: str = "24968193",
        app_id: str = APP_ID,
    ) -> Path:
        manifest_path = library_root / "steamapps" / f"appmanifest_{APP_ID}.acf"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            f'''"AppState"
{{
    // Only this subset is required by discovery.
    "appid" "{app_id}"
    "installdir" "{install_dir}"
    "buildid" "{build_id}"
}}
''',
            encoding="utf-8",
        )
        return manifest_path

    def test_parse_app_manifest_required_fields(self) -> None:
        library_root = self.root / "library"
        manifest_path = self.write_manifest(library_root)

        manifest = parse_app_manifest(manifest_path)

        self.assertEqual(manifest.app_id, APP_ID)
        self.assertEqual(manifest.build_id, "24968193")
        self.assertEqual(manifest.install_dir, "Aliens Fireteam Elite 2")
        self.assertEqual(manifest.path, manifest_path.resolve())

    def test_parse_app_manifest_rejects_wrong_app_and_unsafe_install_dir(self) -> None:
        wrong_app = self.write_manifest(self.root / "wrong", app_id="123")
        with self.assertRaisesRegex(DiscoveryError, "expected 3448650"):
            parse_app_manifest(wrong_app)

        unsafe = self.write_manifest(self.root / "unsafe", install_dir="../AFE2")
        with self.assertRaisesRegex(DiscoveryError, "unsafe installdir"):
            parse_app_manifest(unsafe)

    def test_parse_current_and_legacy_libraryfolders(self) -> None:
        first_library = self.root / "A Library"
        second_library = self.root / "B Library"
        current_path = self.root / "current.vdf"
        current_path.write_text(
            f'''"libraryfolders"
{{
    "0"
    {{
        "path" "{second_library.as_posix()}"
        "apps" {{ "{APP_ID}" "1" }}
    }}
    "1" {{ "path" "{first_library.as_posix()}" }}
}}
''',
            encoding="utf-8",
        )
        legacy_path = self.root / "legacy.vdf"
        legacy_path.write_text(
            f'''"LibraryFolders"
{{
    "TimeNextStatsReport" "0"
    "1" "{second_library.as_posix()}"
}}
''',
            encoding="utf-8",
        )

        self.assertEqual(
            parse_library_folders(current_path),
            (first_library, second_library),
        )
        self.assertEqual(parse_library_folders(legacy_path), (second_library,))

    def test_explicit_directory_precedes_environment(self) -> None:
        explicit_game = self.make_game(self.root / "explicit")
        environment_game = self.make_game(self.root / "environment")

        installation = discover_game_installation(
            explicit_game,
            environ={"AFE2_GAME_DIR": str(environment_game)},
        )

        self.assertEqual(installation.root, explicit_game.resolve())
        self.assertEqual(installation.discovery_source, "explicit")
        self.assertIsNone(installation.manifest)

    def test_environment_directory_is_supported(self) -> None:
        game_dir = self.make_game(self.root / "environment")

        installation = discover_game_installation(
            environ={"AFE2_GAME_DIR": str(game_dir)},
            libraryfolders_paths=(),
        )

        self.assertEqual(installation.root, game_dir.resolve())
        self.assertEqual(installation.discovery_source, "environment")

    def test_discovers_manifest_from_common_linux_libraryfolders(self) -> None:
        home = self.root / "home"
        primary_steam = home / ".local/share/Steam"
        library_root = self.root / "secondary-library"
        install_dir = "Aliens Fireteam Elite 2"
        game_dir = self.make_game(
            library_root / "steamapps" / "common" / install_dir
        )
        self.write_manifest(library_root, install_dir=install_dir)

        metadata_path = primary_steam / "steamapps/libraryfolders.vdf"
        metadata_path.parent.mkdir(parents=True)
        metadata_path.write_text(
            f'''"libraryfolders"
{{
    "0" {{ "path" "{primary_steam.as_posix()}" }}
    "1"
    {{
        "path" "{library_root.as_posix()}"
        "apps" {{ "{APP_ID}" "1" }}
    }}
}}
''',
            encoding="utf-8",
        )

        installation = discover_game_installation(environ={}, home=home)

        self.assertEqual(installation.root, game_dir.resolve())
        self.assertEqual(installation.discovery_source, "steam")
        self.assertEqual(installation.build_id, "24968193")
        self.assertEqual(
            installation.manifest.path,
            (library_root / "steamapps" / f"appmanifest_{APP_ID}.acf").resolve(),
        )

    def test_common_libraryfolders_paths_are_stable(self) -> None:
        home = self.root / "home"

        paths = common_libraryfolders_paths(home)

        self.assertEqual(len(paths), 4)
        self.assertEqual(
            paths[0], home / ".local/share/Steam/steamapps/libraryfolders.vdf"
        )
        self.assertEqual(
            paths[-1],
            home
            / (
                ".var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/"
                "libraryfolders.vdf"
            ),
        )

    def test_validation_requires_paks_and_shipping_executable(self) -> None:
        game_dir = self.root / "incomplete"
        game_dir.mkdir()
        with self.assertRaisesRegex(DiscoveryError, "Paks directory"):
            validate_game_directory(game_dir)

        (game_dir / "AFE2/Content/Paks").mkdir(parents=True)
        (game_dir / "AFE2.exe").write_bytes(b"launcher is not the shipping exe")
        with self.assertRaisesRegex(DiscoveryError, "shipping executable"):
            validate_game_directory(game_dir)

        self.make_game(game_dir)
        root, paks_dir, executable = validate_game_directory(game_dir)
        self.assertEqual(root, game_dir.resolve())
        self.assertEqual(paks_dir, root / "AFE2/Content/Paks")
        self.assertEqual(
            executable, root / "AFE2/Binaries/Win64/AFE2-Win64-Shipping.exe"
        )

    def test_archive_inventory_is_metadata_only_and_deterministic(self) -> None:
        game_dir = self.make_game(
            self.root / "game",
            {
                "zeta.pak": b"standalone",
                "alpha.utoc": b"index",
                "alpha.ucas": b"container-data",
                "nested/beta.pak": b"nested",
                "ignore.txt": b"not an archive",
            },
        )

        with mock.patch.object(
            Path, "read_bytes", side_effect=AssertionError("archive content read")
        ), mock.patch.object(
            Path, "read_text", side_effect=AssertionError("archive content read")
        ):
            archives = inventory_archives(game_dir)

        self.assertEqual(
            archives,
            (
                ArchiveFile("alpha.ucas", 14, "ucas", "alpha", None),
                ArchiveFile("alpha.utoc", 5, "utoc", "alpha", "pending"),
                ArchiveFile(
                    "nested/beta.pak", 6, "pak", "nested/beta", "unscanned"
                ),
                ArchiveFile("zeta.pak", 10, "pak", "zeta", "unscanned"),
            ),
        )
        self.assertEqual(archives, inventory_archives(game_dir))

    def test_source_inventory_combines_discovery_and_archive_metadata(self) -> None:
        library_root = self.root / "library"
        install_dir = "Aliens Fireteam Elite 2"
        game_dir = self.make_game(
            library_root / "steamapps/common" / install_dir,
            {"pakchunk0-WindowsNoEditor.utoc": b"toc"},
        )
        manifest_path = self.write_manifest(library_root, install_dir=install_dir)
        libraryfolders_path = library_root / "steamapps/libraryfolders.vdf"
        libraryfolders_path.write_text(
            f'''"libraryfolders"
{{
    "0" {{ "path" "{library_root.as_posix()}" }}
}}
''',
            encoding="utf-8",
        )

        inventory = discover_source_inventory(
            environ={}, libraryfolders_paths=(libraryfolders_path,)
        )

        self.assertEqual(inventory.installation.root, game_dir.resolve())
        self.assertEqual(inventory.installation.manifest.path, manifest_path.resolve())
        self.assertEqual(
            inventory.archives,
            (
                ArchiveFile(
                    "pakchunk0-WindowsNoEditor.utoc",
                    3,
                    "utoc",
                    "pakchunk0-WindowsNoEditor",
                    "pending",
                ),
            ),
        )

    def test_missing_install_reports_actionable_discovery_error(self) -> None:
        with self.assertRaisesRegex(
            DiscoveryError, "provide game_dir or set AFE2_GAME_DIR"
        ):
            discover_game_installation(
                environ={}, libraryfolders_paths=(self.root / "missing.vdf",)
            )


if __name__ == "__main__":
    unittest.main()
