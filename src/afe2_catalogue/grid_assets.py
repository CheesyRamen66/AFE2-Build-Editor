"""Pure discovery and publication helpers for the perk-grid UI asset bundle.

The archive and semantic-reader orchestration lives elsewhere.  This module
only selects indexed packages, follows the direct imports recorded in trimmed
widget assets, and turns complete reader outcomes into deterministic JSON and
binary payloads.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence

from .errors import CatalogueError
from .jsonio import canonical_bytes


_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_TEXTURE_PREFIXES = (
    "/Game/UI/Textures/Avo_PerkGrid/",
    "/Game/UI/Textures/PerkGrid/",
)
_WIDGET_PREFIXES = (
    "/Game/UI/Blueprints/Menus/WB_Menu_Kits_PerkGrid_",
    "/Game/UI/Blueprints/Menus/WB_Button_Equip_Content_PerkGrid",
)
_WIDGET_EXACT = frozenset(
    {
        "/Game/UI/Blueprints/Menus/I_UI_ColorPalette",
        "/Game/UI/Blueprints/Menus/WB_PerkAbilityReplacer",
        "/Game/UI/Blueprints/PerkGrid_Macros",
        "/Game/UI/Blueprints/WB_PerkAbilityReplacer",
        "/Game/UI/Blueprints/WB_UI_Colors_Functions",
    }
)

_CHIP_DIMENSION_NAME = re.compile(
    r"^T_UI_PerkGridChip_(Core|Modifier|Replacer)_"
    r"([1-9][0-9]*)x([1-9][0-9]*)(?:_(Right|Shortened))?$"
)
_CHIP_PICKUP_NAME = re.compile(
    r"^T_UI_PerkGridChip_(Core|Modifier|Replacer)_PickupReward$"
)
_CHIP_ROLE_NAME = re.compile(
    r"^T_UI_PerkGridChip_(Replacer)_(TacticalHz|UltimateHz)$"
)
_CHIP_ICON_FRAME_NAME = re.compile(
    r"^T_UI_PerkGridChip_IconFrame_(Core|Modifier)$"
)


@dataclass(frozen=True)
class GridAssetBuild:
    """One normalized grid-assets document and its publication payloads."""

    document: dict[str, Any]
    binary_files: dict[str, bytes]


def _is_dedicated_texture(package_path: str) -> bool:
    return any(package_path.startswith(prefix) for prefix in _TEXTURE_PREFIXES)


def _is_grid_widget(package_path: str) -> bool:
    return package_path in _WIDGET_EXACT or any(
        package_path.startswith(prefix) for prefix in _WIDGET_PREFIXES
    )


def _safe_package_path(package_path: Any) -> str:
    if (
        not isinstance(package_path, str)
        or not package_path.startswith("/Game/")
        or package_path.endswith("/")
        or "\\" in package_path
        or "\0" in package_path
    ):
        raise CatalogueError(f"unsafe grid asset package path: {package_path!r}")
    parsed = PurePosixPath(package_path)
    if parsed.parts[:2] != ("/", "Game") or any(
        part in {"", ".", ".."} for part in parsed.parts
    ):
        raise CatalogueError(f"unsafe grid asset package path: {package_path!r}")
    return package_path


def _safe_member_path(member_path: Any) -> str:
    if (
        not isinstance(member_path, str)
        or not member_path
        or "\\" in member_path
        or "\0" in member_path
    ):
        raise CatalogueError(f"unsafe grid asset member path: {member_path!r}")
    parsed = PurePosixPath(member_path)
    if (
        parsed.is_absolute()
        or parsed.as_posix() != member_path
        or any(part in {"", ".", ".."} for part in parsed.parts)
        or not member_path.casefold().endswith(".uasset")
    ):
        raise CatalogueError(f"unsafe grid asset member path: {member_path!r}")
    return member_path


def _selected_members(
    package_members: Mapping[str, str],
    predicate: Any,
) -> dict[str, str]:
    if not isinstance(package_members, Mapping):
        raise CatalogueError("grid package members must be a mapping")
    selected: dict[str, str] = {}
    for raw_package, raw_member in package_members.items():
        if not isinstance(raw_package, str) or not predicate(raw_package):
            continue
        package = _safe_package_path(raw_package)
        member = _safe_member_path(raw_member)
        selected[package] = member
    return dict(sorted(selected.items()))


def select_grid_widget_packages(
    package_members: Mapping[str, str],
) -> dict[str, str]:
    """Return every indexed perk-grid widget/helper package and member."""

    return _selected_members(package_members, _is_grid_widget)


def _normalize_import_package(value: str) -> str:
    # Some serializers expose a full object reference in the package import.
    # Unreal package names cannot contain a dot in their asset-name component,
    # so trimming the object suffix is unambiguous here.
    package = value.split(".", 1)[0]
    return _safe_package_path(package)


def _import_root(imports: Sequence[Any], position: int) -> str | None:
    current = -(position + 1)
    seen: set[int] = set()
    while current < 0:
        if current in seen:
            raise CatalogueError("grid widget import table contained a cycle")
        seen.add(current)
        current_position = -current - 1
        if current_position < 0 or current_position >= len(imports):
            raise CatalogueError("grid widget import table contained an invalid outer index")
        item = imports[current_position]
        if not isinstance(item, Mapping):
            raise CatalogueError("grid widget import table contained a malformed entry")
        object_name = item.get("objectName")
        if not isinstance(object_name, str):
            raise CatalogueError("grid widget import entry omitted its object name")
        if object_name.startswith("/Game/"):
            return _normalize_import_package(object_name)
        outer = item.get("outerIndex")
        if not isinstance(outer, int) or isinstance(outer, bool):
            raise CatalogueError("grid widget import entry omitted its outer index")
        current = outer
    return None


def direct_widget_texture_imports(widget_asset: Mapping[str, Any]) -> tuple[str, ...]:
    """Return direct ``/Game/UI/Textures`` package imports for one widget.

    Trimmed reader output retains Unreal's negative import indices.  Walking
    each entry's outer chain reconstructs the package root even when the leaf
    import only contains an object name such as ``T_UI_PerkGridBG``.
    """

    if not isinstance(widget_asset, Mapping):
        raise CatalogueError("grid widget asset must be an object")
    imports = widget_asset.get("imports")
    if not isinstance(imports, list):
        raise CatalogueError("grid widget asset omitted its imports table")
    textures: set[str] = set()
    for position in range(len(imports)):
        package = _import_root(imports, position)
        if package is not None and package.startswith("/Game/UI/Textures/"):
            textures.add(package)
    return tuple(sorted(textures))


def select_grid_texture_packages(
    package_members: Mapping[str, str],
    widget_assets: Sequence[Mapping[str, Any]] = (),
) -> dict[str, str]:
    """Return dedicated grid textures plus direct shared widget brushes."""

    selected = _selected_members(package_members, _is_dedicated_texture)
    imported = {
        package
        for asset in widget_assets
        for package in direct_widget_texture_imports(asset)
    }
    missing = sorted(imported - set(package_members))
    if missing:
        raise CatalogueError(
            "grid widget texture import had no indexed member: " + ", ".join(missing)
        )
    for package in sorted(imported):
        selected[_safe_package_path(package)] = _safe_member_path(package_members[package])
    return dict(sorted(selected.items()))


def _classification(
    role: str,
    *,
    family: str | None = None,
    footprint: Mapping[str, int] | None = None,
    variant: str | None = None,
) -> dict[str, Any]:
    return {
        "family": family,
        "footprint": dict(footprint) if footprint is not None else None,
        "role": role,
        "variant": variant,
    }


def classify_grid_texture(
    package_path: str,
    *,
    imported: bool = False,
) -> dict[str, Any]:
    """Classify a grid texture using only strict package-directory/name rules."""

    package = _safe_package_path(package_path)
    dedicated = _is_dedicated_texture(package)
    if not dedicated:
        if not imported or not package.startswith("/Game/UI/Textures/"):
            raise CatalogueError("texture was neither a dedicated grid asset nor a widget import")
        return _classification("shared-widget-texture")

    name = package.rsplit("/", 1)[-1]
    dimension_match = _CHIP_DIMENSION_NAME.fullmatch(name)
    if dimension_match:
        raw_family, raw_width, raw_height, raw_variant = dimension_match.groups()
        return _classification(
            "chip-body",
            family=raw_family.casefold(),
            footprint={"height": int(raw_height), "width": int(raw_width)},
            variant=raw_variant.casefold() if raw_variant else "default",
        )
    pickup_match = _CHIP_PICKUP_NAME.fullmatch(name)
    if pickup_match:
        return _classification(
            "chip-pickup-reward",
            family=pickup_match.group(1).casefold(),
            variant="default",
        )
    role_match = _CHIP_ROLE_NAME.fullmatch(name)
    if role_match:
        variants = {
            "TacticalHz": "tactical-horizontal",
            "UltimateHz": "ultimate-horizontal",
        }
        return _classification(
            "chip-body",
            family=role_match.group(1).casefold(),
            variant=variants[role_match.group(2)],
        )
    icon_frame_match = _CHIP_ICON_FRAME_NAME.fullmatch(name)
    if icon_frame_match:
        return _classification(
            "chip-icon-frame",
            family=icon_frame_match.group(1).casefold(),
            variant="default",
        )

    exact = {
        "T_UI_Icon_PerkGrid": _classification("board-icon", variant="default"),
        "T_UI_PerkGridBG": _classification("board-background", variant="default"),
        "T_UI_PerkGrid_Connector_Ghost": _classification("connector", variant="ghost"),
        "T_UI_PerkGrid_Frame_Closed": _classification("board-frame", variant="closed"),
        "T_UI_PerkGrid_Frame_Closed_Bot": _classification(
            "board-frame", variant="closed-bottom"
        ),
        "T_UI_PerkGrid_Frame_Open": _classification("board-frame", variant="open"),
        "T_UI_PerkGrid_Frame_Open_Bot": _classification(
            "board-frame", variant="open-bottom"
        ),
        "T_UI_PerkGrid_Frame_Tab": _classification("board-frame", variant="tab"),
        "T_UI_PerkGrid_Icon_Swappable": _classification(
            "interaction-icon", variant="swappable"
        ),
        "T_UI_PerkGrid_Locked_BorderCorner": _classification(
            "locked-region-border", variant="corner"
        ),
        "T_UI_PerkGrid_Locked_BorderLine": _classification(
            "locked-region-border", variant="horizontal"
        ),
        "T_UI_PerkGrid_Locked_BorderLine_Vertical": _classification(
            "locked-region-border", variant="vertical"
        ),
        "T_UI_PerkGrid_MoreShapesIcon": _classification(
            "interaction-icon", variant="more-shapes"
        ),
        "T_UI_PerkGrid_SlotEmpty": _classification("empty-slot", variant="default"),
    }
    return exact.get(name, _classification("unclassified-dedicated-texture"))


def resolve_chip_body_texture(
    texture_entries: Sequence[Mapping[str, Any]],
    *,
    family: str | None,
    width: int,
    height: int,
) -> Mapping[str, Any] | None:
    """Resolve a chip body using the same footprint-first contract we publish.

    Most footprints have one texture per gameplay family.  The shipped ten-cell
    body is intentionally different: its package is named ``Replacer`` but the
    game widget selects it for core and modifier chips too.  A unique-family
    footprint fallback captures that behavior without hard-coding either the
    footprint or a list of perk definitions.
    """

    if (
        not isinstance(width, int)
        or isinstance(width, bool)
        or width <= 0
        or not isinstance(height, int)
        or isinstance(height, bool)
        or height <= 0
    ):
        raise CatalogueError("chip body resolution requires a positive footprint")
    candidates: list[Mapping[str, Any]] = []
    for texture in texture_entries:
        footprint = texture.get("footprint") if isinstance(texture, Mapping) else None
        if (
            isinstance(texture, Mapping)
            and texture.get("role") == "chip-body"
            and texture.get("variant") == "default"
            and isinstance(footprint, Mapping)
            and footprint.get("width") == width
            and footprint.get("height") == height
        ):
            candidates.append(texture)
    preferred = [item for item in candidates if item.get("family") == family]
    if len(preferred) == 1:
        return preferred[0]
    if len(preferred) > 1:
        return None
    candidate_families = {item.get("family") for item in candidates}
    if len(candidates) == 1 and len(candidate_families) == 1:
        return candidates[0]
    return None


def _output_name(package_path: str, *, suffix: str) -> str:
    leaf = package_path.rsplit("/", 1)[-1]
    slug = re.sub(r"[^a-z0-9]+", "-", leaf.casefold()).strip("-")[:72] or "asset"
    identity = hashlib.sha256(package_path.encode("utf-8")).hexdigest()[:16]
    return f"{slug}--{identity}.{suffix}"


def _safe_output_path(path: str, *, root: str, suffix: str) -> str:
    parsed = PurePosixPath(path)
    if (
        not path.startswith(f"{root}/")
        or parsed.is_absolute()
        or parsed.as_posix() != path
        or any(part in {"", ".", ".."} for part in parsed.parts)
        or parsed.suffix.casefold() != suffix
    ):
        raise CatalogueError(f"unsafe generated grid asset path: {path}")
    return path


def _digest(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _positive_integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _expression_name(value: Any) -> str:
    type_name = value.get("$type") if isinstance(value, Mapping) else None
    if not isinstance(type_name, str):
        return ""
    return type_name.split(",", 1)[0].rsplit(".", 1)[-1]


def _field_path_name(value: Any) -> str | None:
    if isinstance(value, Mapping):
        path = value.get("Path")
        if isinstance(path, list) and path and all(isinstance(item, str) for item in path):
            return ".".join(path)
        for child in value.values():
            resolved = _field_path_name(child)
            if resolved:
                return resolved
    elif isinstance(value, list):
        for child in value:
            resolved = _field_path_name(child)
            if resolved:
                return resolved
    return None


def _linear_channel_to_srgb_byte(value: float) -> int:
    clamped = min(1.0, max(0.0, value))
    encoded = (
        clamped * 12.92
        if clamped <= 0.0031308
        else 1.055 * math.pow(clamped, 1.0 / 2.4) - 0.055
    )
    return int(encoded * 255.0 + 0.5)


def _perk_color_palette(widget_assets: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Conservatively normalize ReturnPerkColor's constant/switch bytecode."""

    source_asset: Mapping[str, Any] | None = None
    source_export: Mapping[str, Any] | None = None
    for asset in widget_assets:
        exports = asset.get("exports") if isinstance(asset, Mapping) else None
        if not isinstance(exports, list):
            continue
        for export in exports:
            if isinstance(export, Mapping) and export.get("objectName") == "ReturnPerkColor":
                source_asset = asset
                source_export = export
                break
        if source_export is not None:
            break
    unresolved = {
        "reason": "ReturnPerkColor bytecode did not match the conservative palette parser",
        "status": "unresolved",
    }
    if source_asset is None or source_export is None:
        return unresolved
    script = source_export.get("scriptBytecode")
    if not isinstance(script, list):
        return unresolved

    constants: dict[str, tuple[float, float, float, float]] = {}
    switch_cases: Mapping[str, Any] | None = None
    for instruction in script:
        if not isinstance(instruction, Mapping) or _expression_name(instruction) != "EX_Let":
            continue
        expression = instruction.get("Expression")
        if _expression_name(expression) == "EX_StructConst" and isinstance(expression, Mapping):
            raw_values = expression.get("Value")
            if not isinstance(raw_values, list) or len(raw_values) != 4:
                continue
            channels: list[float] = []
            for raw in raw_values:
                channel = raw.get("Value") if isinstance(raw, Mapping) else None
                if (
                    _expression_name(raw) != "EX_FloatConst"
                    or isinstance(channel, bool)
                    or not isinstance(channel, (int, float))
                    or not math.isfinite(float(channel))
                ):
                    channels = []
                    break
                channels.append(float(channel))
            variable = _field_path_name(instruction.get("Value"))
            if channels and variable:
                constants[variable] = tuple(channels)  # type: ignore[assignment]
        elif _expression_name(expression) == "EX_SwitchValue" and isinstance(expression, Mapping):
            switch_cases = expression
    if not constants or switch_cases is None:
        return unresolved
    raw_cases = switch_cases.get("Cases")
    if not isinstance(raw_cases, list):
        return unresolved
    indexed: dict[int, tuple[float, float, float, float]] = {}
    for case in raw_cases:
        if not isinstance(case, Mapping):
            return unresolved
        index_term = case.get("CaseIndexValueTerm")
        index = index_term.get("Value") if isinstance(index_term, Mapping) else None
        variable = _field_path_name(case.get("CaseTerm"))
        if (
            _expression_name(index_term) != "EX_IntConst"
            or not isinstance(index, int)
            or isinstance(index, bool)
            or not variable
            or variable not in constants
            or index in indexed
        ):
            return unresolved
        indexed[index] = constants[variable]
    if sorted(indexed) != list(range(len(indexed))) or not indexed:
        return unresolved

    colors: list[dict[str, Any]] = []
    for index in sorted(indexed):
        red, green, blue, alpha = indexed[index]
        rgba = [_linear_channel_to_srgb_byte(value) for value in (red, green, blue, alpha)]
        colors.append(
            {
                "index": index,
                "linearRgba": {"a": alpha, "b": blue, "g": green, "r": red},
                "srgbHex": "#" + "".join(f"{value:02x}" for value in rgba),
            }
        )
    return {
        "colors": colors,
        "indexRule": f"index modulo {len(colors)}",
        "sourceFunction": "ReturnPerkColor",
        "sourcePackagePath": source_asset.get("packagePath"),
        "status": "parsed",
    }


def _export_number(
    asset: Mapping[str, Any],
    *,
    export_name: str,
    property_name: str,
) -> float | None:
    exports = asset.get("exports")
    if not isinstance(exports, list):
        return None
    for export in exports:
        if not isinstance(export, Mapping) or export.get("objectName") != export_name:
            continue
        data = export.get("data")
        if not isinstance(data, list):
            return None
        for prop in data:
            value = prop.get("Value") if isinstance(prop, Mapping) else None
            if (
                isinstance(prop, Mapping)
                and prop.get("Name") == property_name
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(float(value))
            ):
                return float(value)
    return None


def _export_vector2d(
    asset: Mapping[str, Any],
    *,
    export_name: str,
    property_name: str,
) -> tuple[float, float] | None:
    """Return one conservatively parsed FVector2D export property.

    UAssetAPI retains a struct property as a one-item property-data list whose
    value is the actual ``FVector2D`` object.  Keeping this parser narrow makes
    a changed widget serialization fail visibly instead of silently publishing
    a guessed board size.
    """

    exports = asset.get("exports")
    if not isinstance(exports, list):
        return None
    for export in exports:
        if not isinstance(export, Mapping) or export.get("objectName") != export_name:
            continue
        data = export.get("data")
        if not isinstance(data, list):
            return None
        for prop in data:
            if not isinstance(prop, Mapping) or prop.get("Name") != property_name:
                continue
            serialized = prop.get("Value")
            if not isinstance(serialized, list) or len(serialized) != 1:
                return None
            wrapper = serialized[0]
            vector = wrapper.get("Value") if isinstance(wrapper, Mapping) else None
            if not isinstance(vector, Mapping):
                return None
            x = vector.get("X")
            y = vector.get("Y")
            if (
                isinstance(x, bool)
                or not isinstance(x, (int, float))
                or not math.isfinite(float(x))
                or isinstance(y, bool)
                or not isinstance(y, (int, float))
                or not math.isfinite(float(y))
            ):
                return None
            return float(x), float(y)
    return None


def _whole_cell_count(size_pixels: float, pitch_pixels: int) -> int | None:
    if size_pixels <= 0 or pitch_pixels <= 0:
        return None
    cells = size_pixels / pitch_pixels
    rounded = round(cells)
    if rounded <= 0 or not math.isclose(cells, rounded, rel_tol=0.0, abs_tol=1e-6):
        return None
    return int(rounded)


def _board_metrics(
    widget_assets: Sequence[Mapping[str, Any]],
    *,
    pitch_x: int,
    pitch_y: int,
) -> dict[str, Any]:
    package_path = "/Game/UI/Blueprints/Menus/WB_Menu_Kits_PerkGrid_Board"
    export_name = "Default__WB_Menu_Kits_PerkGrid_Board_C"
    property_name = "GridBaseSize"
    asset = next(
        (
            item
            for item in widget_assets
            if isinstance(item, Mapping) and item.get("packagePath") == package_path
        ),
        None,
    )
    if asset is None:
        return {
            "reason": "perk-grid board widget was unavailable",
            "status": "unresolved",
        }
    base_size = _export_vector2d(
        asset,
        export_name=export_name,
        property_name=property_name,
    )
    if base_size is None:
        return {
            "reason": "perk-grid board GridBaseSize was unavailable or malformed",
            "sourcePackagePath": package_path,
            "status": "unresolved",
        }
    width_pixels, height_pixels = base_size
    columns = _whole_cell_count(width_pixels, pitch_x)
    rows = _whole_cell_count(height_pixels, pitch_y)
    if columns is None or rows is None:
        return {
            "baseSizePixels": {
                "height": height_pixels,
                "width": width_pixels,
            },
            "reason": "perk-grid board size was not an exact multiple of the cell pitch",
            "sourcePackagePath": package_path,
            "sourceProperty": f"{export_name}.{property_name}",
            "status": "unresolved",
        }
    return {
        "baseSizePixels": {
            "height": height_pixels,
            "width": width_pixels,
        },
        "columns": columns,
        "rows": rows,
        "sourcePackagePath": package_path,
        "sourceProperty": f"{export_name}.{property_name}",
        "status": "parsed",
    }


def _layout_metrics(
    widget_assets: Sequence[Mapping[str, Any]],
    texture_entries: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    core_sizes: dict[tuple[int, int], tuple[int, int, str]] = {}
    for texture in texture_entries:
        footprint = texture.get("footprint")
        if (
            texture.get("role") == "chip-body"
            and texture.get("family") == "core"
            and texture.get("variant") == "default"
            and isinstance(footprint, Mapping)
            and isinstance(footprint.get("width"), int)
            and isinstance(footprint.get("height"), int)
            and isinstance(texture.get("width"), int)
            and isinstance(texture.get("height"), int)
            and isinstance(texture.get("packagePath"), str)
        ):
            core_sizes[(footprint["width"], footprint["height"])] = (
                texture["width"],
                texture["height"],
                texture["packagePath"],
            )
    one = core_sizes.get((1, 1))
    two_wide = core_sizes.get((2, 1))
    two_high = core_sizes.get((1, 2))
    if one is None or two_wide is None or two_high is None:
        return {
            "reason": "core 1x1, 2x1, and 1x2 texture dimensions were unavailable",
            "status": "unresolved",
        }
    pitch_x = two_wide[0] - one[0]
    pitch_y = two_high[1] - one[1]
    if pitch_x <= 0 or pitch_y <= 0:
        return {"reason": "chip texture dimensions did not establish a grid pitch", "status": "unresolved"}
    connector: dict[str, Any] | None = None
    for asset in widget_assets:
        width = _export_number(
            asset,
            export_name="ConnectorSizeBox",
            property_name="WidthOverride",
        )
        height = _export_number(
            asset,
            export_name="ConnectorSizeBox",
            property_name="HeightOverride",
        )
        if width is not None and height is not None:
            connector = {
                "heightPixels": height,
                "sourcePackagePath": asset.get("packagePath"),
                "widthPixels": width,
            }
            break
    result: dict[str, Any] = {
        "board": _board_metrics(
            widget_assets,
            pitch_x=pitch_x,
            pitch_y=pitch_y,
        ),
        "cell": {
            "gapPixels": {"x": pitch_x - one[0], "y": pitch_y - one[1]},
            "interiorPixels": {"height": one[1], "width": one[0]},
            "pitchPixels": {"x": pitch_x, "y": pitch_y},
        },
        "evidenceTexturePackagePaths": [one[2], two_wide[2], two_high[2]],
        "status": "parsed",
    }
    if connector is not None:
        result["connector"] = connector
    return result


def _normalized_failures(
    failures: Sequence[Mapping[str, Any]],
    *,
    expected_widgets: set[str],
    expected_textures: set[str],
) -> tuple[list[dict[str, str]], set[str], set[str]]:
    normalized: list[dict[str, str]] = []
    failed_widgets: set[str] = set()
    failed_textures: set[str] = set()
    seen: set[tuple[str, str]] = set()
    for failure in failures:
        if not isinstance(failure, Mapping):
            raise CatalogueError("grid reader returned a malformed failure")
        package = failure.get("packagePath")
        stage = failure.get("stage")
        reason = failure.get("reason")
        if not isinstance(package, str) or not isinstance(reason, str) or not reason:
            raise CatalogueError("grid reader returned a malformed failure")
        if stage in {"asset", "widget"}:
            normalized_stage = "widget"
            expected = expected_widgets
            failed = failed_widgets
        elif stage in {"icon", "texture"}:
            normalized_stage = "texture"
            expected = expected_textures
            failed = failed_textures
        else:
            raise CatalogueError("grid reader returned a failure with an unknown stage")
        if package not in expected:
            raise CatalogueError("grid reader returned a failure for an unrequested package")
        identity = (normalized_stage, package)
        if identity in seen:
            raise CatalogueError("grid reader returned a duplicate failure")
        seen.add(identity)
        failed.add(package)
        normalized.append(
            {"packagePath": package, "reason": reason, "stage": normalized_stage}
        )
    normalized.sort(key=lambda item: (item["stage"], item["packagePath"]))
    return normalized, failed_widgets, failed_textures


def build_grid_assets(
    *,
    package_members: Mapping[str, str],
    widget_assets: Sequence[Mapping[str, Any]],
    failures: Sequence[Mapping[str, Any]],
    texture_metadata: Sequence[Mapping[str, Any]],
    texture_bytes: Mapping[str, bytes],
    source_fingerprint: str,
) -> GridAssetBuild:
    """Build a deterministic grid asset manifest from complete reader outcomes."""

    if not isinstance(source_fingerprint, str) or not source_fingerprint:
        raise CatalogueError("grid assets require a source fingerprint")
    expected_widget_members = select_grid_widget_packages(package_members)
    expected_widgets = set(expected_widget_members)

    widgets_by_package: dict[str, Mapping[str, Any]] = {}
    for asset in widget_assets:
        if not isinstance(asset, Mapping) or not isinstance(asset.get("packagePath"), str):
            raise CatalogueError("grid reader returned a malformed widget asset")
        package = asset["packagePath"]
        if package not in expected_widgets:
            raise CatalogueError("grid reader returned an unrequested widget asset")
        if package in widgets_by_package:
            raise CatalogueError("grid reader returned a duplicate widget asset")
        member = asset.get("memberPath")
        if member != expected_widget_members[package]:
            raise CatalogueError("grid reader returned a widget with the wrong member path")
        widgets_by_package[package] = asset

    expected_texture_members = select_grid_texture_packages(
        package_members,
        tuple(widgets_by_package.values()),
    )
    expected_textures = set(expected_texture_members)
    normalized_failures, failed_widgets, failed_textures = _normalized_failures(
        failures,
        expected_widgets=expected_widgets,
        expected_textures=expected_textures,
    )
    if set(widgets_by_package) & failed_widgets:
        raise CatalogueError("grid reader both parsed and failed a widget")
    if set(widgets_by_package) | failed_widgets != expected_widgets:
        raise CatalogueError("grid reader did not partition every requested widget")

    metadata_by_package: dict[str, Mapping[str, Any]] = {}
    output_names: set[str] = set()
    for metadata in texture_metadata:
        if not isinstance(metadata, Mapping) or not isinstance(
            metadata.get("packagePath"), str
        ):
            raise CatalogueError("grid reader returned malformed texture metadata")
        package = metadata["packagePath"]
        output_name = metadata.get("outputName")
        if package not in expected_textures:
            raise CatalogueError("grid reader returned an unrequested texture")
        if package in metadata_by_package:
            raise CatalogueError("grid reader returned duplicate texture metadata")
        if not isinstance(output_name, str) or not output_name or output_name in output_names:
            raise CatalogueError("grid reader returned an invalid texture output name")
        output_names.add(output_name)
        metadata_by_package[package] = metadata
    if set(metadata_by_package) & failed_textures:
        raise CatalogueError("grid reader both decoded and failed a texture")
    if set(metadata_by_package) | failed_textures != expected_textures:
        raise CatalogueError("grid reader did not partition every requested texture")
    if set(texture_bytes) != output_names:
        raise CatalogueError("grid texture payloads did not match decoded metadata")

    imported_by_widget = {
        package: direct_widget_texture_imports(asset)
        for package, asset in widgets_by_package.items()
    }
    imported_textures = {
        texture
        for dependencies in imported_by_widget.values()
        for texture in dependencies
    }
    users_by_texture: dict[str, list[str]] = {}
    for widget, dependencies in imported_by_widget.items():
        for texture in dependencies:
            users_by_texture.setdefault(texture, []).append(widget)

    binary_files: dict[str, bytes] = {}
    widget_entries: list[dict[str, Any]] = []
    generated_paths: set[str] = set()
    for package in sorted(widgets_by_package):
        asset = widgets_by_package[package]
        payload = canonical_bytes(asset)
        path = _safe_output_path(
            f"grid-assets/widgets/{_output_name(package, suffix='json')}",
            root="grid-assets/widgets",
            suffix=".json",
        )
        if path in generated_paths:
            raise CatalogueError("generated grid widget paths were not unique")
        generated_paths.add(path)
        binary_files[path] = payload
        evidence: dict[str, Any] = {
            "memberPath": expected_widget_members[package],
            "type": "serialized-uasset",
        }
        if isinstance(asset.get("engineVersion"), str):
            evidence["engineVersion"] = asset["engineVersion"]
        widget_entries.append(
            {
                "evidence": evidence,
                "memberPath": expected_widget_members[package],
                "packagePath": package,
                "path": path,
                "sha256": _digest(payload),
                "textureDependencies": list(imported_by_widget[package]),
            }
        )

    texture_entries: list[dict[str, Any]] = []
    for package in sorted(metadata_by_package):
        metadata = metadata_by_package[package]
        output_name = metadata["outputName"]
        payload = texture_bytes[output_name]
        if not isinstance(payload, bytes) or not payload.startswith(_PNG_SIGNATURE):
            raise CatalogueError("grid reader returned an invalid PNG texture payload")
        width = _positive_integer(metadata.get("width"))
        height = _positive_integer(metadata.get("height"))
        pixel_format = metadata.get("pixelFormat")
        if width is None or height is None or not isinstance(pixel_format, str) or not pixel_format:
            raise CatalogueError("grid reader returned incomplete texture metadata")
        path = _safe_output_path(
            f"grid-assets/textures/{_output_name(package, suffix='png')}",
            root="grid-assets/textures",
            suffix=".png",
        )
        if path in generated_paths:
            raise CatalogueError("generated grid asset paths were not unique")
        generated_paths.add(path)
        binary_files[path] = payload
        selection_basis: list[str] = []
        if _is_dedicated_texture(package):
            selection_basis.append("dedicated-perk-grid-directory")
        if package in imported_textures:
            selection_basis.append("direct-widget-import")
        classification = classify_grid_texture(
            package,
            imported=package in imported_textures,
        )
        texture_entries.append(
            {
                **classification,
                "height": height,
                "packagePath": package,
                "path": path,
                "pixelFormat": pixel_format,
                "selectionBasis": selection_basis,
                "sha256": _digest(payload),
                "usedByWidgetPackagePaths": sorted(users_by_texture.get(package, [])),
                "width": width,
            }
        )

    document: dict[str, Any] = {
        "coverage": {
            "dedicatedTextures": sum(
                1 for package in expected_textures if _is_dedicated_texture(package)
            ),
            "sharedWidgetTextures": sum(
                1 for package in expected_textures if not _is_dedicated_texture(package)
            ),
            "textureDependencies": len(imported_textures),
            "texturesDecoded": len(metadata_by_package),
            "texturesFailed": len(failed_textures),
            "texturesRequested": len(expected_textures),
            "widgetsFailed": len(failed_widgets),
            "widgetsParsed": len(widgets_by_package),
            "widgetsRequested": len(expected_widgets),
        },
        "failures": normalized_failures,
        "layoutMetrics": _layout_metrics(tuple(widgets_by_package.values()), texture_entries),
        "perkColorPalette": _perk_color_palette(tuple(widgets_by_package.values())),
        "renderingContract": {
            "chipBody": {
                "candidateRule": (
                    "first filter default chip-body textures by the rotated footprint"
                ),
                "familyRecordField": "semantic-assets.json records[].chipVisual.family",
                "familyRule": (
                    "prefer the record family; when that family has no candidate and the "
                    "footprint has exactly one candidate family, use that sole family"
                ),
                "missingOrAmbiguousRule": "leave the chip body unresolved",
                "resolutionOrder": [
                    "filter-by-rotated-footprint",
                    "prefer-record-family",
                    "use-sole-candidate-family",
                    "unresolved",
                ],
                "rotationRule": (
                    "rotate the logical footprint, select the matching orientation texture, "
                    "and keep the content icon upright"
                ),
                "shapeRecordField": "semantic-assets.json records[].grid.shapes[]",
                "textureCandidateFields": [
                    "role=chip-body",
                    "variant=default",
                    "footprint.width",
                    "footprint.height",
                ],
                "texturePreferenceField": "family",
            },
            "compositionOrder": [
                "board-background-and-empty-slots",
                "connectors",
                "chip-body",
                "content-icon",
                "chip-icon-frame",
                "interaction-and-lock-overlays",
            ],
            "contentIconRecordField": "semantic-assets.json records[].icon.path",
        },
        "schemaVersion": 1,
        "selectionBasis": (
            "dedicated PerkGrid texture directories plus direct texture imports "
            "from dynamically selected perk-grid widgets and helpers"
        ),
        "sourceFingerprint": source_fingerprint,
        "textures": texture_entries,
        "widgets": widget_entries,
    }
    return GridAssetBuild(
        document=document,
        binary_files=dict(sorted(binary_files.items())),
    )


__all__ = [
    "GridAssetBuild",
    "build_grid_assets",
    "classify_grid_texture",
    "direct_widget_texture_imports",
    "resolve_chip_body_texture",
    "select_grid_texture_packages",
    "select_grid_widget_packages",
]
