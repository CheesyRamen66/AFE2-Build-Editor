from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from afe2_catalogue.errors import CatalogueError  # noqa: E402
from afe2_catalogue.grid_assets import (  # noqa: E402
    _layout_metrics,
    _perk_color_palette,
    build_grid_assets,
    classify_grid_texture,
    direct_widget_texture_imports,
    resolve_chip_body_texture,
    select_grid_texture_packages,
    select_grid_widget_packages,
)
from afe2_catalogue.jsonio import canonical_bytes  # noqa: E402


BOARD = "/Game/UI/Blueprints/Menus/WB_Menu_Kits_PerkGrid_Board"
FUTURE_WIDGET = "/Game/UI/Blueprints/Menus/WB_Menu_Kits_PerkGrid_RadialFuture"
ABILITY_REPLACER = "/Game/UI/Blueprints/Menus/WB_PerkAbilityReplacer"
CORE_2X3 = "/Game/UI/Textures/PerkGrid/T_UI_PerkGridChip_Core_2x3"
LONG_SHORTENED = (
    "/Game/UI/Textures/Avo_PerkGrid/"
    "T_UI_PerkGridChip_Replacer_10x1_Shortened"
)
SHARED_CIRCUIT = "/Game/UI/Textures/Common/T_UI_SharedCircuit"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def member_path(package: str) -> str:
    return f"AFE2/Content/{package[6:]}.uasset"


def import_pair(package: str) -> list[dict[str, object]]:
    return [
        {"objectName": package.rsplit("/", 1)[-1], "outerIndex": -2},
        {"objectName": package, "outerIndex": 0},
    ]


def widget_asset(
    package: str,
    *,
    texture_imports: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "exports": [{"data": [{"Name": "Fixture", "Value": 7}], "objectName": "Widget_C"}],
        "imports": [entry for texture in texture_imports for entry in import_pair(texture)],
        "engineVersion": "VER_UE4_27",
        "memberPath": member_path(package),
        "packagePath": package,
    }


def published_path(package: str, *, root: str, suffix: str) -> str:
    leaf = package.rsplit("/", 1)[-1]
    slug = re.sub(r"[^a-z0-9]+", "-", leaf.casefold()).strip("-")[:72]
    identity = hashlib.sha256(package.encode("utf-8")).hexdigest()[:16]
    return f"{root}/{slug}--{identity}.{suffix}"


class GridAssetTests(unittest.TestCase):
    def test_perk_palette_is_compiled_from_constant_switch_bytecode(self) -> None:
        color_variable = {
            "$type": "KismetPropertyPointer",
            "New": {"$type": "FFieldPath", "Path": ["Color0"]},
        }
        palette_asset = {
            "exports": [
                {
                    "objectName": "ReturnPerkColor",
                    "scriptBytecode": [
                        {
                            "$type": "EX_Let",
                            "Expression": {
                                "$type": "EX_StructConst",
                                "Value": [
                                    {"$type": "EX_FloatConst", "Value": 1.0},
                                    {"$type": "EX_FloatConst", "Value": 0.0},
                                    {"$type": "EX_FloatConst", "Value": 0.0},
                                    {"$type": "EX_FloatConst", "Value": 1.0},
                                ],
                            },
                            "Value": color_variable,
                        },
                        {
                            "$type": "EX_Let",
                            "Expression": {
                                "$type": "EX_SwitchValue",
                                "Cases": [
                                    {
                                        "CaseIndexValueTerm": {
                                            "$type": "EX_IntConst",
                                            "Value": 0,
                                        },
                                        "CaseTerm": color_variable,
                                    }
                                ],
                            },
                        },
                    ],
                }
            ],
            "packagePath": "/Game/UI/Blueprints/WB_UI_Colors_Functions",
        }

        result = _perk_color_palette([palette_asset])

        self.assertEqual(result["status"], "parsed")
        self.assertEqual(result["indexRule"], "index modulo 1")
        self.assertEqual(result["colors"][0]["srgbHex"], "#ff0000ff")

    def build_fixture(self, *, reverse: bool = False):
        packages = [BOARD, FUTURE_WIDGET, CORE_2X3, LONG_SHORTENED, SHARED_CIRCUIT]
        package_members = {package: member_path(package) for package in packages}
        widgets = [
            widget_asset(BOARD, texture_imports=(SHARED_CIRCUIT, CORE_2X3)),
            widget_asset(FUTURE_WIDGET, texture_imports=(SHARED_CIRCUIT,)),
        ]
        metadata = [
            {
                "height": 192,
                "outputName": "reader-core.png",
                "packagePath": CORE_2X3,
                "pixelFormat": "PF_B8G8R8A8",
                "width": 128,
            },
            {
                "height": 64,
                "outputName": "reader-long.png",
                "packagePath": LONG_SHORTENED,
                "pixelFormat": "PF_B8G8R8A8",
                "width": 640,
            },
            {
                "height": 256,
                "outputName": "reader-shared.png",
                "packagePath": SHARED_CIRCUIT,
                "pixelFormat": "PF_DXT5",
                "width": 256,
            },
        ]
        payloads = {
            "reader-core.png": PNG_SIGNATURE + b"core",
            "reader-long.png": PNG_SIGNATURE + b"long",
            "reader-shared.png": PNG_SIGNATURE + b"shared",
        }
        if reverse:
            package_members = dict(reversed(list(package_members.items())))
            widgets.reverse()
            metadata.reverse()
            payloads = dict(reversed(list(payloads.items())))
        return {
            "failures": [],
            "package_members": package_members,
            "source_fingerprint": "sha256:fixture",
            "texture_bytes": payloads,
            "texture_metadata": metadata,
            "widget_assets": widgets,
        }

    def test_widget_seed_selection_accepts_future_names_without_an_allowlist(self) -> None:
        button_future = (
            "/Game/UI/Blueprints/Menus/"
            "WB_Button_Equip_Content_PerkGridRadialFuture"
        )
        macros = "/Game/UI/Blueprints/PerkGrid_Macros"
        unrelated = "/Game/UI/Blueprints/Menus/WB_Menu_Kits_Inventory"
        wrong_directory = "/Game/UI/Blueprints/Other/WB_Menu_Kits_PerkGrid_Board"
        members = {
            unrelated: member_path(unrelated),
            FUTURE_WIDGET: member_path(FUTURE_WIDGET),
            wrong_directory: member_path(wrong_directory),
            ABILITY_REPLACER: member_path(ABILITY_REPLACER),
            button_future: member_path(button_future),
            BOARD: member_path(BOARD),
            macros: member_path(macros),
        }

        self.assertEqual(
            select_grid_widget_packages(members),
            {
                ABILITY_REPLACER: member_path(ABILITY_REPLACER),
                BOARD: member_path(BOARD),
                button_future: member_path(button_future),
                FUTURE_WIDGET: member_path(FUTURE_WIDGET),
                macros: member_path(macros),
            },
        )

    def test_direct_widget_imports_discover_dedicated_and_shared_textures(self) -> None:
        full_object_reference = f"{CORE_2X3}.{CORE_2X3.rsplit('/', 1)[-1]}"
        asset = widget_asset(BOARD)
        asset["imports"] = [
            *import_pair(SHARED_CIRCUIT),
            {"objectName": full_object_reference, "outerIndex": 0},
            {"objectName": "NotATexture", "outerIndex": -5},
            {"objectName": "/Game/UI/Blueprints/WB_Unrelated", "outerIndex": 0},
        ]

        self.assertEqual(
            direct_widget_texture_imports(asset),
            (SHARED_CIRCUIT, CORE_2X3),
        )

        members = {
            CORE_2X3: member_path(CORE_2X3),
            LONG_SHORTENED: member_path(LONG_SHORTENED),
            SHARED_CIRCUIT: member_path(SHARED_CIRCUIT),
        }
        self.assertEqual(
            select_grid_texture_packages(members, [asset]),
            dict(sorted(members.items())),
        )
        missing_asset = widget_asset(BOARD, texture_imports=(SHARED_CIRCUIT,))
        with self.assertRaisesRegex(CatalogueError, "had no indexed member"):
            select_grid_texture_packages({}, [missing_asset])

    def test_texture_classification_uses_strict_families_and_footprints(self) -> None:
        cases = {
            CORE_2X3: {
                "family": "core",
                "footprint": {"height": 3, "width": 2},
                "role": "chip-body",
                "variant": "default",
            },
            LONG_SHORTENED: {
                "family": "replacer",
                "footprint": {"height": 1, "width": 10},
                "role": "chip-body",
                "variant": "shortened",
            },
            "/Game/UI/Textures/PerkGrid/T_UI_PerkGridChip_Replacer_TacticalHz": {
                "family": "replacer",
                "footprint": None,
                "role": "chip-body",
                "variant": "tactical-horizontal",
            },
            "/Game/UI/Textures/PerkGrid/T_UI_PerkGridChip_IconFrame_Modifier": {
                "family": "modifier",
                "footprint": None,
                "role": "chip-icon-frame",
                "variant": "default",
            },
            "/Game/UI/Textures/PerkGrid/T_UI_PerkGrid_Locked_BorderLine_Vertical": {
                "family": None,
                "footprint": None,
                "role": "locked-region-border",
                "variant": "vertical",
            },
        }
        for package, expected in cases.items():
            with self.subTest(package=package):
                self.assertEqual(classify_grid_texture(package), expected)

        for leaf in (
            "T_UI_PerkGridChip_Core_0x1",
            "T_UI_PerkGridChip_Core_01x1",
            "T_UI_PerkGridChip_Weapon_2x2",
            "T_UI_PerkGridChip_Core_2x2_Left",
            "T_UI_PerkGridChip_core_2x2",
        ):
            with self.subTest(unclassified=leaf):
                self.assertEqual(
                    classify_grid_texture(f"/Game/UI/Textures/PerkGrid/{leaf}"),
                    {
                        "family": None,
                        "footprint": None,
                        "role": "unclassified-dedicated-texture",
                        "variant": None,
                    },
                )
        self.assertEqual(
            classify_grid_texture(SHARED_CIRCUIT, imported=True),
            {
                "family": None,
                "footprint": None,
                "role": "shared-widget-texture",
                "variant": None,
            },
        )
        with self.assertRaisesRegex(CatalogueError, "neither a dedicated grid asset"):
            classify_grid_texture(SHARED_CIRCUIT)
        with self.assertRaisesRegex(CatalogueError, "neither a dedicated grid asset"):
            classify_grid_texture("/Game/Environment/T_SharedCircuit", imported=True)

    def test_layout_metrics_publish_native_board_dimensions_in_cells(self) -> None:
        board = widget_asset(BOARD)
        board["exports"].append(
            {
                "data": [
                    {
                        "Name": "GridBaseSize",
                        "Value": [
                            {
                                "$type": "Vector2DPropertyData",
                                "Name": "GridBaseSize",
                                "Value": {
                                    "$type": "FVector2D",
                                    "X": 1000.0,
                                    "Y": 500.0,
                                },
                            }
                        ],
                    }
                ],
                "objectName": "Default__WB_Menu_Kits_PerkGrid_Board_C",
            }
        )
        textures = [
            {
                "family": "core",
                "footprint": {"height": 1, "width": 1},
                "height": 90,
                "packagePath": "/Game/UI/Textures/PerkGrid/Core_1x1",
                "role": "chip-body",
                "variant": "default",
                "width": 90,
            },
            {
                "family": "core",
                "footprint": {"height": 1, "width": 2},
                "height": 90,
                "packagePath": "/Game/UI/Textures/PerkGrid/Core_2x1",
                "role": "chip-body",
                "variant": "default",
                "width": 190,
            },
            {
                "family": "core",
                "footprint": {"height": 2, "width": 1},
                "height": 190,
                "packagePath": "/Game/UI/Textures/PerkGrid/Core_1x2",
                "role": "chip-body",
                "variant": "default",
                "width": 90,
            },
        ]

        metrics = _layout_metrics([board], textures)

        self.assertEqual(metrics["status"], "parsed")
        self.assertEqual(
            metrics["board"],
            {
                "baseSizePixels": {"height": 500.0, "width": 1000.0},
                "columns": 10,
                "rows": 5,
                "sourcePackagePath": BOARD,
                "sourceProperty": (
                    "Default__WB_Menu_Kits_PerkGrid_Board_C.GridBaseSize"
                ),
                "status": "parsed",
            },
        )
        self.assertEqual(metrics["cell"]["pitchPixels"], {"x": 100, "y": 100})

    def test_chip_body_resolution_uses_unique_footprint_family_fallback(self) -> None:
        def texture(family: str, width: int, height: int, package: str):
            return {
                "family": family,
                "footprint": {"height": height, "width": width},
                "packagePath": package,
                "role": "chip-body",
                "variant": "default",
            }

        core_square = texture("core", 1, 1, "/Game/CoreSquare")
        modifier_square = texture("modifier", 1, 1, "/Game/ModifierSquare")
        long_body = texture("replacer", 10, 1, "/Game/GenericLongBody")
        textures = [core_square, modifier_square, long_body]

        self.assertIs(
            resolve_chip_body_texture(textures, family="core", width=1, height=1),
            core_square,
        )
        self.assertIs(
            resolve_chip_body_texture(textures, family="core", width=10, height=1),
            long_body,
        )
        self.assertIs(
            resolve_chip_body_texture(
                textures,
                family="modifier",
                width=10,
                height=1,
            ),
            long_body,
        )
        self.assertIsNone(
            resolve_chip_body_texture(textures, family="replacer", width=1, height=1)
        )
        with self.assertRaisesRegex(CatalogueError, "positive footprint"):
            resolve_chip_body_texture(textures, family="core", width=0, height=1)

    def test_build_is_deterministic_and_publishes_raw_widgets_and_pngs(self) -> None:
        forward = build_grid_assets(**self.build_fixture())
        reverse = build_grid_assets(**self.build_fixture(reverse=True))

        self.assertEqual(forward.document, reverse.document)
        self.assertEqual(forward.binary_files, reverse.binary_files)
        self.assertEqual(list(forward.binary_files), sorted(forward.binary_files))
        self.assertEqual(
            forward.document["coverage"],
            {
                "dedicatedTextures": 2,
                "sharedWidgetTextures": 1,
                "textureDependencies": 2,
                "texturesDecoded": 3,
                "texturesFailed": 0,
                "texturesRequested": 3,
                "widgetsFailed": 0,
                "widgetsParsed": 2,
                "widgetsRequested": 2,
            },
        )
        self.assertEqual(
            forward.document["renderingContract"]["chipBody"]["resolutionOrder"],
            [
                "filter-by-rotated-footprint",
                "prefer-record-family",
                "use-sole-candidate-family",
                "unresolved",
            ],
        )

        widgets = {
            entry["packagePath"]: entry for entry in forward.document["widgets"]
        }
        board_path = published_path(
            BOARD,
            root="grid-assets/widgets",
            suffix="json",
        )
        self.assertEqual(widgets[BOARD]["path"], board_path)
        expected_widget = widget_asset(
            BOARD,
            texture_imports=(SHARED_CIRCUIT, CORE_2X3),
        )
        self.assertEqual(forward.binary_files[board_path], canonical_bytes(expected_widget))
        self.assertEqual(
            json.loads(forward.binary_files[board_path]),
            expected_widget,
        )
        self.assertEqual(
            widgets[BOARD]["sha256"],
            "sha256:" + hashlib.sha256(canonical_bytes(expected_widget)).hexdigest(),
        )
        self.assertEqual(
            widgets[BOARD]["textureDependencies"],
            [SHARED_CIRCUIT, CORE_2X3],
        )

        textures = {
            entry["packagePath"]: entry for entry in forward.document["textures"]
        }
        core_path = published_path(
            CORE_2X3,
            root="grid-assets/textures",
            suffix="png",
        )
        core_payload = PNG_SIGNATURE + b"core"
        self.assertEqual(textures[CORE_2X3]["path"], core_path)
        self.assertEqual(forward.binary_files[core_path], core_payload)
        self.assertEqual(
            textures[CORE_2X3]["sha256"],
            "sha256:" + hashlib.sha256(core_payload).hexdigest(),
        )
        self.assertEqual(
            textures[CORE_2X3]["selectionBasis"],
            ["dedicated-perk-grid-directory", "direct-widget-import"],
        )
        self.assertEqual(
            textures[SHARED_CIRCUIT]["usedByWidgetPackagePaths"],
            [BOARD, FUTURE_WIDGET],
        )

    def test_reader_failures_partition_outputs_and_missing_outcomes_are_rejected(self) -> None:
        members = {
            BOARD: member_path(BOARD),
            CORE_2X3: member_path(CORE_2X3),
        }
        result = build_grid_assets(
            package_members=members,
            widget_assets=[],
            failures=[
                {"packagePath": CORE_2X3, "reason": "texture decode failed", "stage": "icon"},
                {"packagePath": BOARD, "reason": "widget parse failed", "stage": "asset"},
            ],
            texture_metadata=[],
            texture_bytes={},
            source_fingerprint="sha256:fixture",
        )

        self.assertEqual(
            result.document["failures"],
            [
                {"packagePath": CORE_2X3, "reason": "texture decode failed", "stage": "texture"},
                {"packagePath": BOARD, "reason": "widget parse failed", "stage": "widget"},
            ],
        )
        self.assertEqual(result.document["coverage"]["texturesFailed"], 1)
        self.assertEqual(result.document["coverage"]["widgetsFailed"], 1)
        self.assertEqual(result.binary_files, {})
        with self.assertRaisesRegex(CatalogueError, "partition every requested widget"):
            build_grid_assets(
                package_members={BOARD: member_path(BOARD)},
                widget_assets=[],
                failures=[],
                texture_metadata=[],
                texture_bytes={},
                source_fingerprint="sha256:fixture",
            )

        with self.assertRaisesRegex(CatalogueError, "partition every requested texture"):
            build_grid_assets(
                package_members={CORE_2X3: member_path(CORE_2X3)},
                widget_assets=[],
                failures=[],
                texture_metadata=[],
                texture_bytes={},
                source_fingerprint="sha256:fixture",
            )

    def test_duplicate_reader_outcomes_are_rejected(self) -> None:
        asset = widget_asset(BOARD)
        with self.assertRaisesRegex(CatalogueError, "duplicate widget asset"):
            build_grid_assets(
                package_members={BOARD: member_path(BOARD)},
                widget_assets=[asset, asset],
                failures=[],
                texture_metadata=[],
                texture_bytes={},
                source_fingerprint="sha256:fixture",
            )

        metadata = {
            "height": 32,
            "outputName": "core.png",
            "packagePath": CORE_2X3,
            "pixelFormat": "PF_B8G8R8A8",
            "width": 32,
        }
        with self.assertRaisesRegex(CatalogueError, "duplicate texture metadata"):
            build_grid_assets(
                package_members={CORE_2X3: member_path(CORE_2X3)},
                widget_assets=[],
                failures=[],
                texture_metadata=[metadata, metadata],
                texture_bytes={"core.png": PNG_SIGNATURE + b"core"},
                source_fingerprint="sha256:fixture",
            )

        failure = {"packagePath": BOARD, "reason": "broken", "stage": "widget"}
        with self.assertRaisesRegex(CatalogueError, "duplicate failure"):
            build_grid_assets(
                package_members={BOARD: member_path(BOARD)},
                widget_assets=[],
                failures=[failure, failure],
                texture_metadata=[],
                texture_bytes={},
                source_fingerprint="sha256:fixture",
            )

    def test_malformed_imports_metadata_and_payloads_are_rejected(self) -> None:
        malformed_import_assets = [
            {"packagePath": BOARD},
            {"packagePath": BOARD, "imports": [{"outerIndex": 0}]},
            {
                "packagePath": BOARD,
                "imports": [
                    {"objectName": "CycleA", "outerIndex": -2},
                    {"objectName": "CycleB", "outerIndex": -1},
                ],
            },
            {
                "packagePath": BOARD,
                "imports": [{"objectName": "InvalidOuter", "outerIndex": -99}],
            },
        ]
        for asset in malformed_import_assets:
            with self.subTest(asset=asset), self.assertRaises(CatalogueError):
                direct_widget_texture_imports(asset)

        base = {
            "package_members": {CORE_2X3: member_path(CORE_2X3)},
            "widget_assets": [],
            "failures": [],
            "source_fingerprint": "sha256:fixture",
        }
        with self.assertRaisesRegex(CatalogueError, "incomplete texture metadata"):
            build_grid_assets(
                **base,
                texture_metadata=[
                    {
                        "height": 32,
                        "outputName": "core.png",
                        "packagePath": CORE_2X3,
                        "width": 32,
                    }
                ],
                texture_bytes={"core.png": PNG_SIGNATURE + b"core"},
            )
        with self.assertRaisesRegex(CatalogueError, "invalid PNG"):
            build_grid_assets(
                **base,
                texture_metadata=[
                    {
                        "height": 32,
                        "outputName": "core.png",
                        "packagePath": CORE_2X3,
                        "pixelFormat": "PF_B8G8R8A8",
                        "width": 32,
                    }
                ],
                texture_bytes={"core.png": b"not a png"},
            )


if __name__ == "__main__":
    unittest.main()
