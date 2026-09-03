"""Archive-driven semantic export, dependency analysis, and icon publication."""

from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

from .collection import (
    CollectionFormatError,
    build_collection_document,
    build_kit_membership_index,
    build_progression_perk_index,
    collection_product_package_paths,
    collection_wrapper_dependency_paths,
    kit_reward_registry_dependency_paths,
    kit_reward_table_dependency_paths,
    kit_reward_table_package_paths,
    progression_reward_table_dependency_paths,
    progression_reward_table_package_paths,
)
from .errors import CatalogueError
from .grid_assets import (
    build_grid_assets,
    select_grid_texture_packages,
    select_grid_widget_packages,
)
from .jsonio import write_json_atomic
from .semantic_reader import ManagedSemanticReader
from .tools import run_secret_command
from .weapon_compatibility import build_weapon_compatibility


_MISSING = object()
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_OPERATION_NAMES = {
    "Additive": "add",
    "Division": "divide",
    "Multiplicitive": "multiply",
    "Multiplicative": "multiply",
    "Override": "override",
}
_ABILITY_ROLE_NAMES = {
    "Passive": "passive",
    "Tactical": "secondary",
    "Ultimate": "primary",
}
_GRID_ROTATIONS = ("Default", "Clockwise90", "Clockwise180", "Clockwise270")
_MONDO_WEAPON = "/Game/Blueprints/Venus_Weapons/Guns/Rifles/Venus_Rifle_Auto_HerkMondo"
_MONDO_TRAIT = "/Game/Blueprints/Venus_Weapons/Perks/Mastery/Avo_GunPerk_HerkMondo"
_MONDO_PLACEHOLDER_ICON = "/Game/UI/Textures/Avo_Weapons/Icon_Venus_Rifle_Auto_Kramer"
_COLLECTION_STORE = "/Game/Blueprints/Stores/Store_MainHub_Credits"
_PROGRESSION_SETTINGS = "/Game/Design/Rewards/RewardTable_Settings_V1"
_DEFAULT_STARTING_REWARDS = "/Game/Design/Rewards/DefaultStarting_Rewards"
_DEFAULT_PLAYER_CHARACTER = "/Game/Blueprints/Character/DefaultPlayerCharacter"
_PLAYER_ITEM_INVENTORY_TAGS = {
    "Ability.Consumable.InventoryType.Major": "major",
    "Ability.Consumable.InventoryType.Minor": "minor",
}
_PLAYER_ITEM_SLOT_TAG = "Slot.Consumable.Custom"
_KIT_REWARD_REGISTRY = re.compile(
    r"^/Game/Metagame/(?:[^/]+/)*(?:[^/]*MetaMissions|[^/]*MetaMissionTables)$"
)
_FALLBACK_ARG_MAX = 32 * 1024
_READER_MIN_REQUESTS_PER_JOB = 128
MAX_SEMANTIC_READER_JOBS = 16


@dataclass(frozen=True)
class SemanticBuild:
    document: dict[str, Any]
    binary_files: dict[str, bytes]
    collection_document: dict[str, Any] | None = None
    grid_document: dict[str, Any] | None = None


def _member_map(package_index: Mapping[str, Any]) -> dict[str, str]:
    packages = package_index.get("packages")
    if not isinstance(packages, list):
        raise CatalogueError("package index has no packages array for semantic extraction")
    result: dict[str, str] = {}
    for package in packages:
        if not isinstance(package, dict) or not isinstance(package.get("packagePath"), str):
            continue
        package_path = package["packagePath"]
        if not package_path.startswith("/Game/"):
            # Engine and plugin packages have different mount-to-member mappings
            # and are outside the archive-candidate semantic selection.
            continue
        package_parts = PurePosixPath(package_path).parts
        if "\\" in package_path or ".." in package_parts:
            raise CatalogueError("package index contained an unsafe /Game package path")
        expected_member = f"AFE2/Content/{package_path[6:]}.uasset"
        members: list[str] = []
        for chunk in package.get("chunks", []):
            if not isinstance(chunk, dict) or chunk.get("kind") != "package":
                continue
            member = chunk.get("memberPath")
            if not isinstance(member, str) or not member.casefold().endswith(".uasset"):
                continue
            if member.casefold() != expected_member.casefold():
                # Never bind a package identity to a merely similar member.
                continue
            parsed = PurePosixPath(member)
            if (
                parsed.is_absolute()
                or "\\" in member
                or ".." in parsed.parts
                or parsed.parts[:2] != ("AFE2", "Content")
            ):
                raise CatalogueError("package index contained an unsafe Unreal member path")
            members.append(str(parsed))
        if members:
            distinct = sorted(set(members))
            if len(distinct) != 1:
                raise CatalogueError(
                    f"package index had ambiguous case-insensitive members for {package_path}"
                )
            # Preserve the manifest's actual casing so extraction works on Linux.
            result[package_path] = distinct[0]
    return result


def _argument_bytes(arguments: Sequence[str]) -> int:
    """Conservatively estimate exec argument storage, including pointer overhead."""

    return sum(len(os.fsencode(argument)) + 1 + 8 for argument in arguments)


def _process_argv_budget() -> int:
    """Return a portable, headroom-adjusted budget for a child process argv."""

    try:
        configured = os.sysconf("SC_ARG_MAX")
        arg_max = int(configured) if int(configured) > 0 else _FALLBACK_ARG_MAX
    except (AttributeError, OSError, TypeError, ValueError):
        arg_max = _FALLBACK_ARG_MAX
    environment_bytes = sum(
        len(os.fsencode(name)) + len(os.fsencode(value)) + 2 + 16
        for name, value in os.environ.items()
    )
    # execve shares ARG_MAX between argv and the environment.  Retain at least
    # 16 KiB beyond the measured environment for libc/platform bookkeeping and
    # for environment growth between planning and process creation.
    reserve = environment_bytes + max(16 * 1024, arg_max // 8)
    # A nearly full environment may leave no safe argv capacity.  Preserve that
    # result so _filter_argument_batches fails before execve instead of flooring
    # it to a value the operating system cannot actually accommodate.
    return arg_max - reserve


def _filter_argument_batches(
    base_arguments: Sequence[str],
    members: Sequence[str],
    *,
    budget: int | None = None,
) -> list[list[str]]:
    """Pack ``--filter`` pairs without approaching the platform argv limit."""

    limit = _process_argv_budget() if budget is None else budget
    base = list(base_arguments)
    base_size = _argument_bytes(base)
    if limit <= base_size:
        raise CatalogueError("archive converter command exceeded the safe argument budget")
    batches: list[list[str]] = []
    current = list(base)
    current_size = base_size
    for member in members:
        pair = ["--filter", member]
        pair_size = _argument_bytes(pair)
        if base_size + pair_size > limit:
            raise CatalogueError("an archive member path exceeded the safe argument budget")
        if len(current) > len(base) and current_size + pair_size > limit:
            batches.append(current)
            current = list(base)
            current_size = base_size
        current.extend(pair)
        current_size += pair_size
    if len(current) > len(base):
        batches.append(current)
    return batches


def _extract_members(
    *,
    paks_dir: Path,
    retoc: Path,
    key: str,
    loose_root: Path,
    members: Iterable[str],
) -> None:
    selected = sorted(set(members))
    base_arguments = [
        str(retoc),
        "--aes-key",
        key,
        "to-legacy",
        str(paks_dir),
        str(loose_root),
        "--no-shaders",
        "--no-script-objects",
        "--version",
        "UE4_27",
    ]
    for arguments in _filter_argument_batches(base_arguments, selected):
        result = run_secret_command(arguments, secret=key, timeout=1200)
        if result.returncode:
            # retoc may echo its invocation, including the key. Never attach its output.
            raise CatalogueError("retoc could not convert selected Unreal assets")


def _reader_environment(secret_environment_names: Sequence[str]) -> dict[str, str]:
    environment = os.environ.copy()
    for name in {"AFE2_AES_KEY", *secret_environment_names}:
        if name:
            environment.pop(name, None)
    return environment


def _reader_icon_output_path(icons_root: Path, output_name: Any) -> Path:
    if (
        not isinstance(output_name, str)
        or not output_name
        or "\\" in output_name
        or Path(output_name).name != output_name
    ):
        raise CatalogueError("semantic reader returned an unsafe icon output")
    path = icons_root / output_name
    if path.is_symlink() or not path.is_file():
        raise CatalogueError("semantic reader omitted a decoded icon")
    return path


def _run_reader_once(
    reader: ManagedSemanticReader,
    *,
    request: Mapping[str, Any],
    loose_root: Path,
    work: Path,
    label: str,
    secret_environment_names: Sequence[str],
    require_asset_success: bool = True,
) -> tuple[dict[str, Any], Path]:
    if work.is_symlink() or loose_root.is_symlink() or not work.is_dir() or not loose_root.is_dir():
        raise CatalogueError("semantic reader roots must be fresh normal directories")
    if work.resolve() == loose_root.resolve() or work.resolve().is_relative_to(loose_root.resolve()):
        raise CatalogueError("semantic reader work and asset roots must be disjoint")
    requested_assets = request.get("assets")
    requested_icons = request.get("icons")
    if not isinstance(requested_assets, list) or not isinstance(requested_icons, list):
        raise CatalogueError("semantic reader request lists were malformed")
    asset_packages = [item.get("packagePath") for item in requested_assets if isinstance(item, dict)]
    asset_members = [item.get("memberPath") for item in requested_assets if isinstance(item, dict)]
    icon_packages = [item.get("packagePath") for item in requested_icons if isinstance(item, dict)]
    icon_members = [item.get("memberPath") for item in requested_icons if isinstance(item, dict)]
    icon_outputs = [item.get("outputName") for item in requested_icons if isinstance(item, dict)]
    if (
        len(asset_packages) != len(requested_assets)
        or len(icon_packages) != len(requested_icons)
        or len(set(asset_packages)) != len(asset_packages)
        or len(set(asset_members)) != len(asset_members)
        or len(set(icon_packages)) != len(icon_packages)
        or len(set(icon_members)) != len(icon_members)
        or len(set(icon_outputs)) != len(icon_outputs)
    ):
        raise CatalogueError("semantic reader request identities must be complete and unique")
    request_path = work / f"{label}-request.json"
    output_path = work / f"{label}-output.json"
    icons_root = work / f"{label}-icons"
    icons_root.mkdir()
    write_json_atomic(request_path, request)
    try:
        result = subprocess.run(
            [
                *reader.command,
                "inspect",
                str(request_path),
                str(loose_root),
                str(output_path),
                str(icons_root),
            ],
            env=_reader_environment(secret_environment_names),
            check=False,
            capture_output=True,
            text=True,
            timeout=1200,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise CatalogueError("semantic reader failed to execute; command details were suppressed") from None
    if result.returncode or output_path.is_symlink() or not output_path.is_file():
        raise CatalogueError("semantic reader failed; child output was suppressed")
    try:
        document = json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogueError("semantic reader produced unreadable JSON") from exc
    if not isinstance(document, dict) or document.get("schemaVersion") != 1:
        raise CatalogueError("semantic reader produced an unsupported document")
    failures = document.get("failures")
    if not isinstance(failures, list):
        raise CatalogueError("semantic reader omitted its failures list")
    actual_assets = document.get("assets")
    actual_icons = document.get("icons")
    if not isinstance(actual_assets, list) or not isinstance(actual_icons, list):
        raise CatalogueError("semantic reader response lists were malformed")
    if any(
        not isinstance(item, Mapping)
        for values in (actual_assets, actual_icons, failures)
        for item in values
    ):
        raise CatalogueError("semantic reader response elements were malformed")
    returned_asset_pairs = [
        (item.get("packagePath"), item.get("memberPath"))
        for item in actual_assets
    ]
    expected_asset_pairs = [
        (item["packagePath"], item["memberPath"]) for item in requested_assets
    ]
    returned_icon_pairs = [
        (item.get("packagePath"), item.get("outputName"))
        for item in actual_icons
    ]
    expected_icon_pairs = [
        (item["packagePath"], item["outputName"]) for item in requested_icons
    ]
    failure_pairs = [
        (item.get("stage"), item.get("packagePath"))
        for item in failures
    ]
    if any(
        stage not in {"asset", "icon"} or not isinstance(package, str)
        for stage, package in failure_pairs
    ):
        raise CatalogueError("semantic reader returned a malformed failure")
    if len(set(returned_asset_pairs)) != len(returned_asset_pairs):
        raise CatalogueError("semantic reader returned a duplicate asset")
    if len(set(returned_icon_pairs)) != len(returned_icon_pairs):
        raise CatalogueError("semantic reader returned a duplicate icon")
    if len(set(failure_pairs)) != len(failure_pairs):
        raise CatalogueError("semantic reader returned a duplicate failure")
    expected_assets_by_package = dict(expected_asset_pairs)
    expected_icons_by_package = dict(expected_icon_pairs)
    if any(expected_assets_by_package.get(package) != member for package, member in returned_asset_pairs):
        raise CatalogueError("semantic reader returned an unrequested asset")
    if any(expected_icons_by_package.get(package) != output for package, output in returned_icon_pairs):
        raise CatalogueError("semantic reader returned an unrequested icon")
    asset_outcomes = {package for package, _ in returned_asset_pairs} | {
        package for stage, package in failure_pairs if stage == "asset"
    }
    icon_outcomes = {package for package, _ in returned_icon_pairs} | {
        package for stage, package in failure_pairs if stage == "icon"
    }
    if asset_outcomes != set(expected_assets_by_package):
        raise CatalogueError("semantic reader did not partition every requested asset")
    if icon_outcomes != set(expected_icons_by_package):
        raise CatalogueError("semantic reader did not partition every requested icon")
    if set(package for package, _ in returned_asset_pairs) & {
        package for stage, package in failure_pairs if stage == "asset"
    }:
        raise CatalogueError("semantic reader both succeeded and failed an asset")
    if set(package for package, _ in returned_icon_pairs) & {
        package for stage, package in failure_pairs if stage == "icon"
    }:
        raise CatalogueError("semantic reader both succeeded and failed an icon")
    for item in actual_icons:
        _reader_icon_output_path(icons_root, item.get("outputName"))
    if require_asset_success and requested_assets and not actual_assets:
        raise CatalogueError("semantic reader could not parse any requested assets")
    return document, icons_root


def _reader_shard_count(request_count: int, jobs: int) -> int:
    if (
        isinstance(jobs, bool)
        or not isinstance(jobs, int)
        or not 1 <= jobs <= MAX_SEMANTIC_READER_JOBS
    ):
        raise CatalogueError(
            f"semantic reader jobs must be between 1 and {MAX_SEMANTIC_READER_JOBS}"
        )
    return min(jobs, max(1, request_count // _READER_MIN_REQUESTS_PER_JOB))


def _run_reader(
    reader: ManagedSemanticReader,
    *,
    request: Mapping[str, Any],
    loose_root: Path,
    work: Path,
    label: str,
    secret_environment_names: Sequence[str],
    jobs: int = 1,
) -> tuple[dict[str, Any], Path]:
    """Run one or more isolated reader processes and merge their results."""

    requested_assets = request.get("assets")
    requested_icons = request.get("icons")
    if not isinstance(requested_assets, list) or not isinstance(requested_icons, list):
        raise CatalogueError("semantic reader request lists were malformed")
    shard_count = _reader_shard_count(len(requested_assets) + len(requested_icons), jobs)
    if shard_count == 1:
        return _run_reader_once(
            reader,
            request=request,
            loose_root=loose_root,
            work=work,
            label=label,
            secret_environment_names=secret_environment_names,
        )

    if (
        work.is_symlink()
        or loose_root.is_symlink()
        or not work.is_dir()
        or not loose_root.is_dir()
    ):
        raise CatalogueError("semantic reader roots must be fresh normal directories")
    if work.resolve() == loose_root.resolve() or work.resolve().is_relative_to(
        loose_root.resolve()
    ):
        raise CatalogueError("semantic reader work and asset roots must be disjoint")

    # Validate identities across the complete request before partitioning them.
    asset_packages = [
        item.get("packagePath") for item in requested_assets if isinstance(item, dict)
    ]
    asset_members = [
        item.get("memberPath") for item in requested_assets if isinstance(item, dict)
    ]
    icon_packages = [
        item.get("packagePath") for item in requested_icons if isinstance(item, dict)
    ]
    icon_members = [
        item.get("memberPath") for item in requested_icons if isinstance(item, dict)
    ]
    icon_outputs = [
        item.get("outputName") for item in requested_icons if isinstance(item, dict)
    ]
    if (
        len(asset_packages) != len(requested_assets)
        or len(icon_packages) != len(requested_icons)
        or len(set(asset_packages)) != len(asset_packages)
        or len(set(asset_members)) != len(asset_members)
        or len(set(icon_packages)) != len(icon_packages)
        or len(set(icon_members)) != len(icon_members)
        or len(set(icon_outputs)) != len(icon_outputs)
    ):
        raise CatalogueError("semantic reader request identities must be complete and unique")

    shard_root = work / f"{label}-shards"
    try:
        shard_root.mkdir()
        shard_work = [shard_root / f"{index:03d}" for index in range(shard_count)]
        for directory in shard_work:
            directory.mkdir()
    except OSError as exc:
        raise CatalogueError("semantic reader shard roots could not be created") from exc

    asset_shards: list[list[Any]] = [[] for _ in range(shard_count)]
    icon_shards: list[list[Any]] = [[] for _ in range(shard_count)]
    for index, item in enumerate(requested_assets):
        asset_shards[index % shard_count].append(item)
    for index, item in enumerate(requested_icons):
        icon_shards[index % shard_count].append(item)

    def run_shard(index: int) -> tuple[dict[str, Any], Path]:
        shard_request = {
            **request,
            "assets": asset_shards[index],
            "icons": icon_shards[index],
        }
        return _run_reader_once(
            reader,
            request=shard_request,
            loose_root=loose_root,
            work=shard_work[index],
            label="reader",
            secret_environment_names=secret_environment_names,
            require_asset_success=False,
        )

    with ThreadPoolExecutor(max_workers=shard_count, thread_name_prefix="semantic-reader") as pool:
        futures = [pool.submit(run_shard, index) for index in range(shard_count)]
        shard_results = [future.result() for future in futures]

    merged_assets: list[dict[str, Any]] = []
    merged_icons: list[dict[str, Any]] = []
    merged_failures: list[dict[str, Any]] = []
    metadata: dict[str, Any] | None = None
    for document, _ in shard_results:
        shard_metadata = {
            key: value
            for key, value in document.items()
            if key not in {"assets", "icons", "failures"}
        }
        if metadata is None:
            metadata = shard_metadata
        elif shard_metadata != metadata:
            raise CatalogueError("semantic reader shards returned inconsistent metadata")
        merged_assets.extend(document["assets"])
        merged_icons.extend(document["icons"])
        merged_failures.extend(document["failures"])

    merged_assets.sort(key=lambda item: item["packagePath"])
    merged_icons.sort(key=lambda item: item["packagePath"])
    merged_failures.sort(key=lambda item: (item["packagePath"], item["stage"]))
    merged = {
        **(metadata or {"schemaVersion": 1}),
        "assets": merged_assets,
        "icons": merged_icons,
        "failures": merged_failures,
    }

    # Reuse the complete-request outcome rules, including exact global
    # success/failure partitioning.  The subprocess already wrote each shard;
    # this validation is deliberately independent of filesystem layout.
    expected_assets = set(asset_packages)
    expected_icons = set(icon_packages)
    returned_assets = {item.get("packagePath") for item in merged_assets}
    returned_icons = {item.get("packagePath") for item in merged_icons}
    failed_assets = {
        item.get("packagePath") for item in merged_failures if item.get("stage") == "asset"
    }
    failed_icons = {
        item.get("packagePath") for item in merged_failures if item.get("stage") == "icon"
    }
    if returned_assets | failed_assets != expected_assets:
        raise CatalogueError("semantic reader did not partition every requested asset")
    if returned_icons | failed_icons != expected_icons:
        raise CatalogueError("semantic reader did not partition every requested icon")
    if returned_assets & failed_assets:
        raise CatalogueError("semantic reader both succeeded and failed an asset")
    if returned_icons & failed_icons:
        raise CatalogueError("semantic reader both succeeded and failed an icon")
    if requested_assets and not merged_assets:
        raise CatalogueError("semantic reader could not parse any requested assets")

    icons_root = work / f"{label}-icons"
    try:
        icons_root.mkdir()
        for document, source_root in shard_results:
            for item in document["icons"]:
                output_name = item["outputName"]
                source = _reader_icon_output_path(source_root, output_name)
                shutil.copyfile(source, icons_root / output_name)
    except CatalogueError:
        raise
    except OSError as exc:
        raise CatalogueError("semantic reader icons could not be merged") from exc
    return merged, icons_root


def _import_package(asset: Mapping[str, Any], index: Any) -> str | None:
    imports = asset.get("imports")
    if not isinstance(imports, list) or not isinstance(index, int) or index >= 0:
        return None
    seen: set[int] = set()
    current = index
    while current < 0 and current not in seen:
        seen.add(current)
        position = -current - 1
        if position < 0 or position >= len(imports) or not isinstance(imports[position], dict):
            return None
        item = imports[position]
        name = item.get("objectName")
        if isinstance(name, str) and name.startswith("/Game/"):
            return name
        outer = item.get("outerIndex")
        if not isinstance(outer, int):
            return None
        current = outer
    return None


def _import_parent_identity(asset: Mapping[str, Any], index: Any) -> str | None:
    """Return a Blueprint package or native script class for a superclass import."""

    imports = asset.get("imports")
    if not isinstance(imports, list) or not isinstance(index, int) or index >= 0:
        return None
    position = -index - 1
    if position < 0 or position >= len(imports) or not isinstance(imports[position], dict):
        return None
    leaf = imports[position].get("objectName")
    if not isinstance(leaf, str):
        return None
    seen: set[int] = set()
    current = index
    while current < 0 and current not in seen:
        seen.add(current)
        current_position = -current - 1
        if (
            current_position < 0
            or current_position >= len(imports)
            or not isinstance(imports[current_position], dict)
        ):
            return None
        item = imports[current_position]
        name = item.get("objectName")
        if isinstance(name, str) and name.startswith("/Game/"):
            return name.split(".", 1)[0]
        if isinstance(name, str) and name.startswith("/Script/"):
            return name if leaf == name else f"{name}.{leaf}"
        outer = item.get("outerIndex")
        if not isinstance(outer, int):
            return None
        current = outer
    return None


def _default_export(asset: Mapping[str, Any]) -> Mapping[str, Any] | None:
    exports = asset.get("exports")
    if not isinstance(exports, list):
        return None
    values = [item for item in exports if isinstance(item, dict)]
    for item in values:
        if str(item.get("objectName", "")).startswith("Default__"):
            return item
    return values[0] if values else None


def _blueprint_parent_package(asset: Mapping[str, Any]) -> str | None:
    """Return the direct game-content Blueprint superclass, when there is one."""

    exports = asset.get("exports")
    if not isinstance(exports, list):
        return None
    class_export = next(
        (
            item
            for item in exports
            if isinstance(item, Mapping)
            and str(item.get("objectName", "")).endswith("_C")
            and not str(item.get("objectName", "")).startswith("Default__")
        ),
        None,
    )
    if class_export is None:
        return None
    parent = _import_parent_identity(asset, class_export.get("superIndex"))
    return parent if isinstance(parent, str) and parent.startswith("/Game/") else None


def _properties(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _property_map(value: Any) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for item in _properties(value):
        name = item.get("Name")
        if isinstance(name, str) and name not in result:
            result[name] = item
    return result


def _authored_blueprint_property_names(asset: Mapping[str, Any]) -> frozenset[str]:
    """Return properties serialized on the actual Blueprint CDO, if present."""

    exports = asset.get("exports")
    if not isinstance(exports, list):
        return frozenset()
    default_export = next(
        (
            item
            for item in exports
            if isinstance(item, Mapping)
            and str(item.get("objectName", "")).startswith("Default__")
        ),
        None,
    )
    if default_export is None:
        return frozenset()
    return frozenset(_property_map(default_export.get("data")))


def _materialized_property_map(
    asset: Mapping[str, Any],
    parent_assets_by_package: Mapping[str, Mapping[str, Any]],
) -> dict[str, tuple[Mapping[str, Any], Mapping[str, Any], str]]:
    """Merge authored Blueprint CDO properties while retaining their owner.

    The owner is essential for resolving negative Unreal object indexes: an
    inherited property still indexes the import table of the parent package in
    which it was serialized.
    """

    merged: dict[str, tuple[Mapping[str, Any], Mapping[str, Any], str]] = {}
    visiting: set[str] = set()

    def add_layer(current: Mapping[str, Any]) -> None:
        package = current.get("packagePath")
        identity = package if isinstance(package, str) else f"object:{id(current)}"
        if identity in visiting:
            raise CatalogueError("Blueprint parent graph contained a cycle")
        visiting.add(identity)
        parent = _blueprint_parent_package(current)
        if parent is not None and parent in parent_assets_by_package:
            add_layer(parent_assets_by_package[parent])
        export = _default_export(current)
        if export is not None:
            export_name = str(export.get("objectName", ""))
            for name, prop in _property_map(export.get("data")).items():
                merged[name] = (prop, current, export_name)
        visiting.remove(identity)

    add_layer(asset)
    return merged


def _text(prop: Mapping[str, Any] | None) -> object:
    if prop is None:
        return _MISSING
    for key in ("CultureInvariantString", "SourceValue"):
        value = prop.get(key)
        if isinstance(value, str):
            return value
    if prop.get("HistoryType") == "None" and prop.get("Value") is None:
        return None
    return _MISSING


def _conditional_mod_descriptions(
    prop: Mapping[str, Any],
) -> list[dict[str, Any]] | None:
    """Normalize AFE2's authored attachment/trait UI description groups."""

    raw_groups = prop.get("Value")
    if not isinstance(raw_groups, list):
        return None
    if not raw_groups:
        return []
    groups: list[dict[str, Any]] = []
    has_visible_text = False
    for raw_group in raw_groups:
        if not isinstance(raw_group, Mapping):
            return None
        fields = _property_map(raw_group.get("Value"))
        condition_text = _text(fields.get("ConditionText"))
        if condition_text is _MISSING or (
            condition_text is not None and not isinstance(condition_text, str)
        ):
            return None
        raw_lines = (fields.get("StatList") or {}).get("Value")
        if not isinstance(raw_lines, list) or not raw_lines:
            return None
        stat_lines: list[dict[str, Any]] = []
        for raw_line in raw_lines:
            if not isinstance(raw_line, Mapping):
                return None
            line_fields = _property_map(raw_line.get("Value"))
            stat_text = _text(line_fields.get("StatText"))
            stat_value = _finite_number(
                (line_fields.get("StatNumber") or {}).get("Value")
            )
            display_type = _enum_tail(_enum(line_fields.get("ModDisplayType")))
            result = _enum_tail(_enum(line_fields.get("StatResult")))
            if (
                stat_text is _MISSING
                or (stat_text is not None and not isinstance(stat_text, str))
                or stat_value is None
                or not display_type
                or not result
            ):
                return None
            stat_lines.append(
                {
                    "displayType": display_type,
                    "result": result,
                    "statText": stat_text,
                    "statValue": stat_value,
                }
            )
            has_visible_text = has_visible_text or bool(
                isinstance(stat_text, str) and stat_text.strip()
            )
        groups.append(
            {
                "conditionText": condition_text,
                "statLines": stat_lines,
            }
        )
        has_visible_text = has_visible_text or bool(
            isinstance(condition_text, str) and condition_text.strip()
        )
    return groups if has_visible_text else None


def _enum(prop: Mapping[str, Any] | None) -> str | None:
    if prop is None:
        return None
    for key in ("EnumValue", "Value"):
        value = prop.get(key)
        if isinstance(value, str):
            return value
    return None


def _enum_tail(value: str | None) -> str | None:
    return value.rsplit("::", 1)[-1] if value else None


def _finite_number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value if math.isfinite(float(value)) else None
    if isinstance(value, str):
        try:
            parsed = float(value)
        except ValueError:
            return None
        return parsed if math.isfinite(parsed) else None
    return None


def _soft_object_packages(value: Any) -> list[str]:
    """Return normalized package identities from serialized soft-object paths."""

    packages: list[str] = []
    if isinstance(value, list):
        for child in value:
            packages.extend(_soft_object_packages(child))
    elif isinstance(value, dict):
        asset_path = value.get("AssetPath")
        if isinstance(asset_path, dict):
            for key in ("PackageName", "AssetName"):
                raw = asset_path.get(key)
                if isinstance(raw, str) and raw.startswith("/Game/"):
                    packages.append(raw.split(".", 1)[0])
                    break
        for key, child in value.items():
            if key != "AssetPath" and isinstance(child, (dict, list)):
                packages.extend(_soft_object_packages(child))
    return list(dict.fromkeys(packages))


def _gameplay_tags(value: Any) -> list[str]:
    """Read an Unreal GameplayTagContainer without collecting metadata strings."""

    tags: list[str] = []
    if isinstance(value, list):
        for child in value:
            tags.extend(_gameplay_tags(child))
    elif isinstance(value, dict):
        type_name = str(value.get("$type", ""))
        raw = value.get("Value")
        if "GameplayTagContainerPropertyData" in type_name and isinstance(raw, list):
            tags.extend(item for item in raw if isinstance(item, str) and item)
        elif value.get("Name") == "TagName" and isinstance(raw, str) and raw:
            tags.append(raw)
        else:
            for child in value.values():
                if isinstance(child, (dict, list)):
                    tags.extend(_gameplay_tags(child))
    return sorted(set(tags))


def _item_slots_from_default_player(
    asset: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Return only the hub-selectable item slots authored on the player CDO."""

    if asset.get("packagePath") != _DEFAULT_PLAYER_CHARACTER:
        return []
    export = _default_export(asset)
    if export is None or not str(export.get("objectName", "")).startswith("Default__"):
        return []
    export_name = str(export.get("objectName"))
    part_slots = _property_map(export.get("data")).get("PartSlots")
    if part_slots is None:
        return []

    slots: list[dict[str, Any]] = []
    for index, entry in enumerate(_properties(part_slots.get("Value"))):
        fields = _property_map(entry.get("Value"))
        required_tags = _gameplay_tags(fields.get("RequiredModTags"))
        slot_tags = _gameplay_tags(fields.get("SlotTags"))
        matching_inventory_tags = [
            tag for tag in _PLAYER_ITEM_INVENTORY_TAGS if tag in required_tags
        ]
        if (
            len(matching_inventory_tags) != 1
            or _PLAYER_ITEM_SLOT_TAG not in slot_tags
        ):
            continue
        inventory_tag = matching_inventory_tags[0]
        slots.append(
            {
                "evidence": {
                    "engineVersion": asset.get("engineVersion"),
                    "memberPath": asset.get("memberPath"),
                    "packagePath": _DEFAULT_PLAYER_CHARACTER,
                    "property": f"{export_name}.PartSlots[{index}]",
                    "source": "serialized-uasset",
                },
                "index": index,
                "inventoryTypeTag": inventory_tag,
                "itemTier": _PLAYER_ITEM_INVENTORY_TAGS[inventory_tag],
                "requiredModTags": required_tags,
                "slotTags": slot_tags,
            }
        )
    return slots


def _positive_int(value: Any) -> int | None:
    number = _finite_number(value)
    if number is None or float(number) <= 0 or not float(number).is_integer():
        return None
    return int(number)


def _integer(value: Any, *, minimum: int | None = None) -> int | None:
    number = _finite_number(value)
    if number is None or not float(number).is_integer():
        return None
    result = int(number)
    return result if minimum is None or result >= minimum else None


def _grid_shape(
    *,
    width: int,
    height: int,
    collision_mask: Sequence[int],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    occupied = [
        {"column": index % width, "row": index // width}
        for index, value in enumerate(collision_mask)
        if value != 0
    ]
    return {
        "cellCount": len(occupied),
        "collisionMask": list(collision_mask),
        "evidence": dict(evidence),
        "height": height,
        "occupiedCells": occupied,
        "size": f"{min(width, height)}x{max(width, height)}",
        "width": width,
    }


def _grid_shapes(
    prop: Mapping[str, Any] | None,
    *,
    export_name: str,
) -> list[dict[str, Any]]:
    shapes: list[dict[str, Any]] = []
    for index, entry in enumerate(_properties((prop or {}).get("Value"))):
        fields = _property_map(entry.get("Value"))
        width = _positive_int((fields.get("Width") or {}).get("Value"))
        height = _positive_int((fields.get("Height") or {}).get("Value"))
        raw_mask = [
            item.get("Value")
            for item in _properties((fields.get("CollisionMask") or {}).get("Value"))
        ]
        if width is None or height is None or len(raw_mask) != width * height:
            continue
        if not all(isinstance(value, int) and not isinstance(value, bool) for value in raw_mask):
            continue
        shapes.append(
            _grid_shape(
                width=width,
                height=height,
                collision_mask=raw_mask,
                evidence={
                    "property": f"{export_name}.PossibleShapes[{index}]",
                    "source": "serialized-uasset",
                },
            )
        )
    return shapes


def _native_default_grid_shape() -> dict[str, Any]:
    return _grid_shape(
        width=2,
        height=2,
        collision_mask=(1, 1, 1, 1),
        evidence={
            "reason": (
                "PossibleShapes is omitted on a direct native ModChipDef subclass; "
                "the shipped native/default footprint is the observed 2x2 core shape"
            ),
            "source": "native-default-inferred",
        },
    )


def _chip_visual_family(
    *,
    export_name: str,
    raw_perk_type: str | None,
    raw_role: str | None,
    raw_replacer_type: str | None,
) -> dict[str, Any]:
    """Resolve the chip-art family without relying on a perk or kit name."""

    if raw_role or raw_replacer_type:
        evidence: dict[str, Any] = {"source": "serialized-enum"}
        if raw_role:
            evidence.update(
                {
                    "property": f"{export_name}.ClassAbilityType",
                    "valueRaw": raw_role,
                }
            )
        else:
            evidence.update(
                {
                    "property": f"{export_name}.ReplacerType",
                    "valueRaw": raw_replacer_type,
                }
            )
        if raw_replacer_type:
            evidence["replacerTypeProperty"] = f"{export_name}.ReplacerType"
            evidence["replacerTypeRaw"] = raw_replacer_type
        return {
            "evidence": evidence,
            "family": "replacer",
            "status": "resolved",
        }
    perk_type = (_enum_tail(raw_perk_type) or "").casefold()
    if perk_type in {"core", "modifier", "replacer"}:
        return {
            "evidence": {
                "property": f"{export_name}.Type",
                "source": "serialized-enum",
                "valueRaw": raw_perk_type,
            },
            "family": perk_type,
            "status": "resolved",
        }
    if raw_perk_type:
        return {
            "evidence": {
                "property": f"{export_name}.Type",
                "source": "serialized-enum",
                "valueRaw": raw_perk_type,
            },
            "reason": "serialized perk type has no known grid-art family",
            "status": "unresolved-family",
        }
    return {"status": "inheritance-pending"}


def _resolve_chip_visual_families(records: Sequence[dict[str, Any]]) -> None:
    """Resolve inherited chip families, failing open on missing/cyclic parents."""

    perks_by_package = {
        record["packagePath"]: record
        for record in records
        if record.get("kind") == "perk" and isinstance(record.get("packagePath"), str)
    }
    resolving: set[str] = set()

    def resolve(record: dict[str, Any]) -> Mapping[str, Any]:
        package = record["packagePath"]
        visual = record.get("chipVisual")
        if not isinstance(visual, dict) or visual.get("status") != "inheritance-pending":
            return visual if isinstance(visual, Mapping) else {}
        parent = record.get("parentPackagePath")
        native_parent = record.get("parentClassPath")
        if not isinstance(parent, str) and (
            isinstance(native_parent, str)
            and native_parent.rsplit(".", 1)[-1] == "ModChipDef"
        ):
            resolved = {
                "evidence": {
                    "parentClassPath": native_parent,
                    "reason": (
                        "Type is omitted on a direct native ModChipDef subclass and no "
                        "ClassAbilityType override is serialized"
                    ),
                    "source": "native-default-inferred",
                },
                "family": "core",
                "status": "inferred",
            }
            record["chipVisual"] = resolved
            return resolved
        if not isinstance(parent, str):
            unresolved = {
                "evidence": {
                    "parentClassPath": native_parent,
                    "source": "native-or-unresolved-parent",
                },
                "reason": "perk superclass did not prove the native ModChipDef default",
                "status": "unresolved-family",
            }
            record["chipVisual"] = unresolved
            return unresolved
        if package in resolving:
            unresolved = {
                "evidence": {"parentPackagePath": parent, "source": "blueprint-parent"},
                "reason": "perk Blueprint parent chain contained a cycle",
                "status": "unresolved-family",
            }
            record["chipVisual"] = unresolved
            return unresolved
        parent_record = perks_by_package.get(parent)
        if parent_record is None:
            unresolved = {
                "evidence": {"parentPackagePath": parent, "source": "blueprint-parent"},
                "reason": "perk Blueprint parent was unavailable for family inheritance",
                "status": "unresolved-family",
            }
            record["chipVisual"] = unresolved
            return unresolved
        resolving.add(package)
        parent_visual = resolve(parent_record)
        resolving.discard(package)
        family = parent_visual.get("family")
        if family in {"core", "modifier", "replacer"}:
            inherited = {
                "evidence": {
                    "parentPackagePath": parent,
                    "source": "blueprint-parent",
                },
                "family": family,
                "status": "inferred",
            }
            record["chipVisual"] = inherited
            return inherited
        unresolved = {
            "evidence": {"parentPackagePath": parent, "source": "blueprint-parent"},
            "reason": "perk Blueprint parent family was unresolved",
            "status": "unresolved-family",
        }
        record["chipVisual"] = unresolved
        return unresolved

    for perk in perks_by_package.values():
        resolve(perk)


def _object_references(
    value: Any,
    asset: Mapping[str, Any],
    *,
    path: str,
) -> list[tuple[str, str]]:
    references: list[tuple[str, str]] = []
    if isinstance(value, list):
        for index, child in enumerate(value):
            references.extend(_object_references(child, asset, path=f"{path}[{index}]"))
    elif isinstance(value, dict):
        name = value.get("Name")
        current_path = f"{path}.{name}" if isinstance(name, str) and path else (name or path)
        if "ObjectPropertyData" in str(value.get("$type", "")):
            package = _import_package(asset, value.get("Value"))
            if package:
                references.append((str(current_path), package))
        for key, child in value.items():
            if key not in {"$type", "Name"} and isinstance(child, (dict, list)):
                references.extend(_object_references(child, asset, path=str(current_path)))
    return references


def _weapon_visual_references(
    data: Any,
    asset: Mapping[str, Any],
    property_name: str,
) -> list[tuple[str, str]]:
    """Return exact named UI-visual references from a gun CDO.

    AFE2 serializes both ``AmmoIcon`` (the white silhouette) and ``GunIcon``
    (the pre-rendered default-colour art) below ``Attributes.UIVisuals``.  The
    same values can be repeated beneath fire-mode attributes, so callers
    deduplicate package identities after retaining their property evidence.
    """

    return [
        (path, package)
        for path, package in _object_references(data, asset, path="")
        if path == property_name or path.endswith(f".{property_name}")
    ]


def _weapon_icon_references(data: Any, asset: Mapping[str, Any]) -> list[tuple[str, str]]:
    return _weapon_visual_references(data, asset, "GunIcon")


def _weapon_silhouette_references(
    data: Any,
    asset: Mapping[str, Any],
) -> list[tuple[str, str]]:
    return _weapon_visual_references(data, asset, "AmmoIcon")


def _effect_links(asset: Mapping[str, Any], data: Any) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    for prop in _properties(data):
        name = prop.get("Name")
        if not isinstance(name, str) or "effect" not in name.casefold():
            continue
        for entry_index, entry in enumerate(_properties(prop.get("Value"))):
            fields = _property_map(entry.get("Value"))
            effect_def = fields.get("EffectDef")
            package = _import_package(asset, effect_def.get("Value") if effect_def else None)
            if not package:
                continue
            link: dict[str, Any] = {
                "effectPackagePath": package,
                "evidence": {
                    "effectDefProperty": f"{name}[{entry_index}].EffectDef",
                },
            }
            magnitude = _finite_number((fields.get("Magnitude") or {}).get("Value"))
            if magnitude is not None:
                link["configuredMagnitude"] = magnitude
                link["evidence"]["magnitudeProperty"] = f"{name}[{entry_index}].Magnitude"
            flag_names = (
                "bInterpretTableLookupAsPercent",
                "bNormalizePercentForEffectMagnitude",
                "bEnableApplyToGunsInsteadCheckbox",
                "bApplyToGunsInstead",
                "bVisibleOnUI",
            )
            flags = {
                flag: fields[flag].get("Value")
                for flag in flag_names
                if flag in fields and isinstance(fields[flag].get("Value"), bool)
            }
            if flags:
                link["serializedFlags"] = flags
            links.append(link)
    return links


def _candidate_semantics(
    candidate: Mapping[str, Any],
    asset: Mapping[str, Any],
    parent_assets_by_package: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    package_path = str(candidate["packagePath"])
    record: dict[str, Any] = {
        "evidence": [
            {
                "engineVersion": asset.get("engineVersion"),
                "memberPath": asset.get("memberPath"),
                "type": "serialized-uasset",
            }
        ],
        "id": candidate.get("id", package_path),
        "kind": candidate.get("kind"),
        "packagePath": package_path,
        "status": "parsed",
    }
    if candidate.get("kind") == "mod":
        record["compatibility"] = {
            "reason": "equip-rule inheritance was not materialized by this semantic pass",
            "status": "partial",
        }
    export = _default_export(asset)
    if export is None:
        record["status"] = "no-export"
        return record
    data = export.get("data")
    materialized = _materialized_property_map(asset, parent_assets_by_package or {})
    fields = {name: value[0] for name, value in materialized.items()}
    export_name = str(export.get("objectName", ""))

    def field_context(name: str) -> tuple[Mapping[str, Any] | None, Mapping[str, Any], str]:
        resolved = materialized.get(name)
        if resolved is None:
            return None, asset, export_name
        return resolved

    if candidate.get("kind") == "kit":
        character_class_prop, character_class_asset, _ = field_context("CharacterClass")
        character_classes = [
            package
            for _, package in _object_references(
                character_class_prop,
                character_class_asset,
                path="",
            )
        ]
        if character_classes:
            record["characterClassPackagePath"] = character_classes[0]

    if candidate.get("kind") == "item":
        item_tags = _gameplay_tags(fields.get("Tags"))
        inventory_types = {
            tag.rsplit(".", 1)[-1].casefold()
            for tag in item_tags
            if tag.startswith("Ability.Consumable.InventoryType.")
        }
        if len(inventory_types) == 1:
            record["itemTier"] = next(iter(inventory_types))
        elif inventory_types:
            record["itemTierResolution"] = {
                "candidateValues": sorted(inventory_types),
                "reason": "serialized item tags declared multiple inventory tiers",
                "status": "unresolved",
            }

    if candidate.get("kind") == "perk":
        raw_perk_type = _enum(fields.get("Type"))
        perk_type = _enum_tail(raw_perk_type)
        if perk_type:
            record["perkType"] = perk_type.casefold()

        shape_property, _, shape_export = field_context("PossibleShapes")
        shapes = _grid_shapes(shape_property, export_name=shape_export)
        if shape_property is None:
            shapes = [_native_default_grid_shape()]
        grid: dict[str, Any] = {
            "allowedRotations": list(_GRID_ROTATIONS),
            "shapes": shapes,
        }
        if shape_property is not None and not shapes:
            grid["reason"] = "serialized PossibleShapes could not be normalized"
            grid["status"] = "unresolved"
        record["grid"] = grid

        provided_tags = _gameplay_tags(fields.get("Tags"))
        accepted_tags = _gameplay_tags(fields.get("ModifierCompatability"))
        dependencies: dict[str, Any] = {}
        if provided_tags:
            dependencies["providedTags"] = provided_tags
        if accepted_tags:
            dependencies["acceptedModifierTags"] = accepted_tags
        if raw_perk_type:
            dependencies["perkTypeEvidence"] = f"{export_name}.Type"
        if dependencies:
            record["dependencies"] = dependencies

        restricted_classes = _soft_object_packages(fields.get("KitRestriction"))
        alternative_classes = _soft_object_packages(fields.get("AlternativeKitsAllowed"))
        origin_classes = _soft_object_packages(fields.get("OriginKit"))
        eligibility: dict[str, Any] = {}
        if restricted_classes:
            eligibility["restrictedKitClassPackagePath"] = restricted_classes[0]
        if alternative_classes:
            eligibility["alternativeKitClassPackagePaths"] = alternative_classes
        if origin_classes:
            eligibility["originKitClassPackagePath"] = origin_classes[0]
        if eligibility:
            record["kitEligibility"] = eligibility

        raw_role = _enum(fields.get("ClassAbilityType"))
        raw_replacer_type = _enum(fields.get("ReplacerType"))
        role = _ABILITY_ROLE_NAMES.get(_enum_tail(raw_role) or "")
        if raw_role:
            ability: dict[str, Any] = {
                "evidence": {"roleProperty": f"{export_name}.ClassAbilityType"},
                "roleRaw": raw_role,
            }
            if role:
                ability["role"] = role
            else:
                ability["reason"] = "serialized ClassAbilityType is not mapped to an editor role"
                ability["status"] = "unresolved-role"
            input_bind = _enum(fields.get("InputBind"))
            if input_bind:
                ability["inputBindRaw"] = input_bind
            if raw_replacer_type:
                ability["replacerTypeRaw"] = raw_replacer_type
                ability["evidence"]["replacerTypeProperty"] = (
                    f"{export_name}.ReplacerType"
                )
            gameplay_property = (
                "GrantedAbilityOverride"
                if fields.get("GrantedAbilityOverride") is not None
                else "GrantedAbility"
            )
            gameplay_packages = _soft_object_packages(fields.get(gameplay_property))
            if gameplay_packages:
                ability["gameplayAbilityPackagePath"] = gameplay_packages[0]
                ability["evidence"]["gameplayAbilityProperty"] = (
                    f"{export_name}.{gameplay_property}"
                )
            record["ability"] = ability
        _, _, type_export = field_context("Type")
        _, _, role_export = field_context("ClassAbilityType")
        record["chipVisual"] = _chip_visual_family(
            export_name=role_export if raw_role or raw_replacer_type else type_export,
            raw_perk_type=raw_perk_type,
            raw_role=raw_role,
            raw_replacer_type=raw_replacer_type,
        )

    name = _MISSING
    name_property: str | None = None
    for key in ("DisplayName", "Name", "Title"):
        value = _text(fields.get(key))
        if value is not _MISSING:
            name = value
            name_property = key
            break
    if isinstance(name, str):
        record["displayName"] = name
        record["displayNameEvidence"] = f"{export.get('objectName')}.{name_property}"

    description = _MISSING
    description_property: str | None = None
    for key in ("DisplayDescription", "Description", "Desc", "Tooltip"):
        value = _text(fields.get(key))
        if value is not _MISSING:
            description = value
            description_property = key
            break
    if description is not _MISSING:
        # An explicit serialized empty FText remains JSON null; it is not filled
        # from similarly named legacy/archive assets.
        record["description"] = description
        record["descriptionEvidence"] = f"{export.get('objectName')}.{description_property}"

    conditional_property, conditional_asset, conditional_export = field_context(
        "ConditionalModDescriptions"
    )
    if conditional_property is not None:
        conditional_descriptions = _conditional_mod_descriptions(
            conditional_property
        )
        evidence = {
            "memberPath": conditional_asset.get("memberPath"),
            "property": f"{conditional_export}.ConditionalModDescriptions",
            "sourcePackagePath": conditional_asset.get("packagePath"),
        }
        if conditional_descriptions is None:
            record["conditionalDescriptionsResolution"] = {
                "evidence": evidence,
                "reason": "serialized ConditionalModDescriptions could not be normalized",
                "status": "unresolved",
            }
        elif not conditional_descriptions:
            record["conditionalDescriptionsResolution"] = {
                "evidence": evidence,
                "status": "authored-empty",
            }
        else:
            record["conditionalDescriptions"] = conditional_descriptions
            record["conditionalDescriptionsEvidence"] = evidence

    exports = asset.get("exports")
    if isinstance(exports, list):
        class_export = next(
            (
                item
                for item in exports
                if isinstance(item, dict)
                and str(item.get("objectName", "")).endswith("_C")
                and not str(item.get("objectName", "")).startswith("Default__")
            ),
            None,
        )
        if class_export:
            parent = _import_parent_identity(asset, class_export.get("superIndex"))
            if parent and parent != package_path:
                if parent.startswith("/Game/"):
                    record["parentPackagePath"] = parent
                elif parent.startswith("/Script/"):
                    record["parentClassPath"] = parent

    icon_references: list[tuple[str, str]] = []
    silhouette_references: list[tuple[str, str]] = []
    if candidate.get("kind") == "weapon":
        icon_references.extend(_weapon_icon_references(data, asset))
        silhouette_references.extend(_weapon_silhouette_references(data, asset))
    for prop, owner_asset, _ in materialized.values():
        prop_name = str(prop.get("Name", ""))
        if candidate.get("kind") == "weapon":
            icon_references.extend(_weapon_icon_references([prop], owner_asset))
            silhouette_references.extend(_weapon_silhouette_references([prop], owner_asset))
        if "icon" in prop_name.casefold() or "brush" in prop_name.casefold():
            icon_references.extend(_object_references(prop, owner_asset, path=""))
    ranked_icon_references = sorted(
        icon_references,
        key=lambda item: (
            0
            if item[0] == "GunIcon" or item[0].endswith(".GunIcon")
            else 1
            if item[0].startswith("Icon") and item[0].endswith(".ResourceObject")
            else 2
            if item[0].startswith("Icon")
            else 3,
            item[0].count("."),
            item[0],
            item[1],
        ),
    )
    icon_packages = list(dict.fromkeys(package for _, package in ranked_icon_references))
    if icon_packages:
        record["icon"] = {
            "packagePath": icon_packages[0],
            "referenceEvidence": next(
                path for path, package in ranked_icon_references if package == icon_packages[0]
            ),
        }
        if len(icon_packages) > 1:
            record["additionalIconPackagePaths"] = icon_packages[1:]

    ranked_silhouette_references = sorted(
        silhouette_references,
        key=lambda item: (item[0].count("."), item[0], item[1]),
    )
    silhouette_packages = list(
        dict.fromkeys(package for _, package in ranked_silhouette_references)
    )
    if silhouette_packages:
        record["silhouetteIcon"] = {
            "packagePath": silhouette_packages[0],
            "referenceEvidence": next(
                path
                for path, package in ranked_silhouette_references
                if package == silhouette_packages[0]
            ),
        }
        if len(silhouette_packages) > 1:
            record["additionalSilhouetteIconPackagePaths"] = silhouette_packages[1:]

    effects: list[dict[str, Any]] = []
    for prop, owner_asset, _ in materialized.values():
        effects.extend(_effect_links(owner_asset, [prop]))
    if effects:
        record["effects"] = effects
    return record


def _effect_definition(asset: Mapping[str, Any]) -> dict[str, Any]:
    definition: dict[str, Any] = {"packagePath": asset.get("packagePath")}
    export = _default_export(asset)
    if export is None:
        definition["status"] = "no-export"
        return definition
    fields = _property_map(export.get("data"))
    raw_duration = _enum(fields.get("DurationPolicy"))
    if raw_duration:
        definition["durationPolicyRaw"] = raw_duration
        definition["durationPolicy"] = (_enum_tail(raw_duration) or "").casefold()
    modifiers: list[dict[str, Any]] = []
    modifier_property = fields.get("Modifiers")
    for index, entry in enumerate(_properties((modifier_property or {}).get("Value"))):
        item_fields = _property_map(entry.get("Value"))
        attribute_fields = _property_map((item_fields.get("Attribute") or {}).get("Value"))
        attribute = (attribute_fields.get("AttributeName") or {}).get("Value")
        raw_operation = _enum(item_fields.get("ModifierOp"))
        magnitude_fields = _property_map(
            (item_fields.get("ModifierMagnitude") or {}).get("Value")
        )
        raw_calculation = _enum(magnitude_fields.get("MagnitudeCalculationType"))
        modifier: dict[str, Any] = {
            "evidence": f"Modifiers[{index}]",
        }
        if isinstance(attribute, str):
            modifier["attribute"] = attribute
        if raw_operation:
            modifier["operationRaw"] = raw_operation
            tail = _enum_tail(raw_operation)
            if tail in _OPERATION_NAMES:
                modifier["operation"] = _OPERATION_NAMES[tail]
        if raw_calculation:
            modifier["magnitudeCalculationTypeRaw"] = raw_calculation
            modifier["magnitudeCalculationType"] = (
                _enum_tail(raw_calculation) or ""
            ).casefold()
        modifiers.append(modifier)
    definition["modifiers"] = modifiers
    definition["status"] = "parsed"
    return definition


def _icon_output_name(package_path: str) -> str:
    leaf = package_path.rsplit("/", 1)[-1]
    slug = re.sub(r"[^a-z0-9]+", "-", leaf.casefold()).strip("-")[:56] or "icon"
    identity = hashlib.sha256(package_path.encode("utf-8")).hexdigest()[:16]
    return f"{slug}--{identity}.png"


def _mechanical_stats(
    effect: Mapping[str, Any],
    definition: Mapping[str, Any],
) -> list[dict[str, Any]]:
    operand = _finite_number(effect.get("configuredMagnitude"))
    if operand is None:
        return []
    planner_operand = float(f"{float(operand):.7g}")
    stats: list[dict[str, Any]] = []
    for modifier in definition.get("modifiers", []):
        if not isinstance(modifier, dict):
            continue
        attribute = modifier.get("attribute")
        operation = modifier.get("operation")
        calculation = modifier.get("magnitudeCalculationType")
        if (
            not isinstance(attribute, str)
            or operation not in {"add", "divide", "multiply", "override"}
            or calculation != "setbycaller"
        ):
            continue
        symbol = {"add": "+", "divide": "/", "multiply": "*", "override": "="}[operation]
        stat: dict[str, Any] = {
            "attribute": attribute,
            "durationPolicy": definition.get("durationPolicy"),
            "effectPackagePath": effect.get("effectPackagePath"),
            "evidence": {
                "effectDefinition": modifier.get("evidence"),
                "linkage": (effect.get("evidence") or {}).get("effectDefProperty"),
                "magnitude": (effect.get("evidence") or {}).get("magnitudeProperty"),
                "magnitudeCalculationType": modifier.get("magnitudeCalculationTypeRaw"),
            },
            "expression": f"{attribute} {symbol} {planner_operand}",
            "operand": planner_operand,
            "operation": operation,
            "serializedOperand": operand,
        }
        if operation == "divide" and planner_operand > 0 and attribute == "TimeToReload":
            stat["derived"] = {
                "rateIncreasePercent": round((planner_operand - 1.0) * 100.0, 6),
                "timeMultiplier": round(1.0 / planner_operand, 6),
                "timeReductionPercent": round(
                    (1.0 - (1.0 / planner_operand)) * 100.0,
                    6,
                ),
            }
        stats.append(stat)
    return stats


def _apply_icon_fallbacks(records: Sequence[dict[str, Any]]) -> None:
    """Apply reviewed fallbacks for shipped records whose primary art is wrong."""

    by_id = {
        record.get("id"): record
        for record in records
        if isinstance(record.get("id"), str)
    }
    weapon = by_id.get(_MONDO_WEAPON)
    trait = by_id.get(_MONDO_TRAIT)
    if not isinstance(weapon, dict) or not isinstance(trait, dict):
        return
    trait_icon = trait.get("icon")
    if not isinstance(trait_icon, dict) or not isinstance(trait_icon.get("packagePath"), str):
        return
    serialized = weapon.get("icon")
    if (
        not isinstance(serialized, dict)
        or serialized.get("packagePath") != _MONDO_PLACEHOLDER_ICON
    ):
        return
    weapon["serializedIcon"] = copy.deepcopy(serialized)
    fallback = copy.deepcopy(trait_icon)
    fallback["fallback"] = {
        "reason": "serialized Mondo weapon icon is generic Kramer artwork",
        "sourceRecordId": _MONDO_TRAIT,
        "type": "trait-icon",
    }
    fallback["referenceEvidence"] = f"fallback:{_MONDO_TRAIT}.Icon"
    weapon["icon"] = fallback


def _provided_tag_matches_accepted(provided: str, accepted: str) -> bool:
    return provided == accepted or provided.startswith(f"{accepted}.")


def _ability_owning_kit_id(perk: Mapping[str, Any]) -> str | None:
    eligibility = perk.get("kitEligibility")
    if not isinstance(eligibility, Mapping):
        return None
    origin = eligibility.get("originKitId")
    if isinstance(origin, str):
        return origin
    restricted = eligibility.get("restrictedKitId")
    return restricted if isinstance(restricted, str) else None


def _is_cross_kit_ability_chip(perk: Mapping[str, Any]) -> bool:
    eligibility = perk.get("kitEligibility")
    if not isinstance(eligibility, Mapping):
        return False
    origin = eligibility.get("originKitId")
    restricted = eligibility.get("restrictedKitId")
    return isinstance(origin, str) and isinstance(restricted, str) and origin != restricted


def _ability_slot_placeholder_signals(
    perk: Mapping[str, Any],
    *,
    importing_kit_ids: set[str],
) -> tuple[bool, bool]:
    """Identify a replaceable board slot from serialized tags, not a kit name.

    AFE2's generic ability slots are pure role-tag receptacles owned by a kit
    that imports cross-kit abilities. Both signals are required; either alone
    is deliberately insufficient so a new native ability fails open instead
    of disappearing from the catalogue.
    """

    ability = perk.get("ability")
    dependencies = perk.get("dependencies")
    if not isinstance(ability, Mapping) or not isinstance(dependencies, Mapping):
        return False, False
    if ability.get("role") not in {"primary", "secondary", "passive"}:
        return False, False
    raw_role = ability.get("roleRaw")
    role_tail = _enum_tail(raw_role if isinstance(raw_role, str) else None)
    if not role_tail:
        return False, False
    role_tag = f"Item.Chip.AbilityType.{role_tail}"
    accepted = dependencies.get("acceptedModifierTags")
    provided = dependencies.get("providedTags")
    accepted_tags = {
        value for value in accepted if isinstance(value, str)
    } if isinstance(accepted, list) else set()
    provided_tags = {
        value for value in provided if isinstance(value, str)
    } if isinstance(provided, list) else set()
    pure_role_receptacle = (
        accepted_tags == {role_tag}
        and bool(provided_tags)
        and provided_tags <= {"Item.Chip.Core.Active", "Item.Chip.Core.Passive"}
        and role_tag not in provided_tags
    )
    eligibility = perk.get("kitEligibility")
    restricted = (
        eligibility.get("restrictedKitId")
        if isinstance(eligibility, Mapping)
        else None
    )
    importing_owner = (
        isinstance(restricted, str) and restricted in importing_kit_ids
    )
    origin = (
        eligibility.get("originKitId")
        if isinstance(eligibility, Mapping)
        else None
    )
    native_slot_context = (
        importing_owner
        and not _is_cross_kit_ability_chip(perk)
        and not isinstance(ability.get("replacerTypeRaw"), str)
        and (not isinstance(origin, str) or origin == restricted)
    )
    return pure_role_receptacle, native_slot_context


def _is_ability_slot_placeholder(
    perk: Mapping[str, Any],
    *,
    importing_kit_ids: set[str],
) -> bool:
    pure_role_receptacle, importing_owner = _ability_slot_placeholder_signals(
        perk,
        importing_kit_ids=importing_kit_ids,
    )
    return pure_role_receptacle and importing_owner


def _enrich_record_relationships(
    records: Sequence[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Resolve kit abilities and tag-driven perk relationships across records."""

    by_id = {
        record.get("id"): record
        for record in records
        if isinstance(record.get("id"), str)
    }
    kit_by_class = {
        record["characterClassPackagePath"]: record
        for record in records
        if record.get("kind") == "kit"
        and isinstance(record.get("characterClassPackagePath"), str)
    }
    perks = [record for record in records if record.get("kind") == "perk"]

    for perk in perks:
        eligibility = perk.get("kitEligibility")
        if not isinstance(eligibility, dict):
            continue
        restricted = kit_by_class.get(eligibility.get("restrictedKitClassPackagePath"))
        if restricted:
            eligibility["restrictedKitId"] = restricted["id"]
        origin = kit_by_class.get(eligibility.get("originKitClassPackagePath"))
        if origin:
            eligibility["originKitId"] = origin["id"]
        alternatives = [
            kit_by_class[path]["id"]
            for path in eligibility.get("alternativeKitClassPackagePaths", [])
            if path in kit_by_class
        ]
        if alternatives:
            eligibility["alternativeKitIds"] = list(dict.fromkeys(alternatives))

    targets = [
        perk
        for perk in perks
        if isinstance((perk.get("dependencies") or {}).get("acceptedModifierTags"), list)
    ]
    modifiers = [
        perk
        for perk in perks
        if isinstance(perk.get("chipVisual"), Mapping)
        and perk["chipVisual"].get("family") == "modifier"
    ]
    dependency_edges = 0
    for modifier in modifiers:
        dependencies = modifier.setdefault("dependencies", {})
        provided = dependencies.get("providedTags", [])
        possible_targets: list[str] = []
        for target in targets:
            if target.get("id") == modifier.get("id"):
                continue
            accepted = (target.get("dependencies") or {}).get("acceptedModifierTags", [])
            if any(
                _provided_tag_matches_accepted(provided_tag, accepted_tag)
                for provided_tag in provided
                for accepted_tag in accepted
            ):
                possible_targets.append(target["id"])
                target_dependencies = target.setdefault("dependencies", {})
                target_dependencies.setdefault("possibleModifierPerkIds", []).append(
                    modifier["id"]
                )
        dependencies["requiresConnectedCompatibleTarget"] = True
        dependencies["possibleTargetPerkIds"] = sorted(set(possible_targets))
        dependency_edges += len(dependencies["possibleTargetPerkIds"])
    for target in targets:
        dependencies = target.get("dependencies")
        if isinstance(dependencies, dict) and "possibleModifierPerkIds" in dependencies:
            dependencies["possibleModifierPerkIds"] = sorted(
                set(dependencies["possibleModifierPerkIds"])
            )

    unresolved_roles = sum(
        1
        for perk in perks
        if isinstance(perk.get("ability"), dict)
        and (perk.get("ability") or {}).get("status") == "unresolved-role"
    )
    ability_records = [
        perk
        for perk in perks
        if isinstance(perk.get("ability"), dict)
        and perk["ability"].get("role") in {"primary", "secondary", "passive"}
        and isinstance(perk["ability"].get("gameplayAbilityPackagePath"), str)
    ]
    importing_kit_ids: set[str] = set()
    for perk in perks:
        eligibility = perk.get("kitEligibility")
        if (
            isinstance(perk.get("ability"), dict)
            and _is_cross_kit_ability_chip(perk)
            and isinstance(eligibility, dict)
            and isinstance(eligibility.get("restrictedKitId"), str)
        ):
            importing_kit_ids.add(eligibility["restrictedKitId"])
    placeholders = 0
    unresolved_placeholder_candidates = 0
    for perk in perks:
        ability = perk.get("ability")
        if not isinstance(ability, dict):
            continue
        placeholder_signals = _ability_slot_placeholder_signals(
            perk,
            importing_kit_ids=importing_kit_ids,
        )
        if _is_ability_slot_placeholder(
            perk,
            importing_kit_ids=importing_kit_ids,
        ):
            ability["placeholder"] = True
            placeholders += 1
        elif any(placeholder_signals) and not _is_cross_kit_ability_chip(perk):
            ability["placeholderResolution"] = {
                "importingKit": placeholder_signals[1],
                "pureRoleReceptacle": placeholder_signals[0],
                "reason": (
                    "only one of the two class-name-independent slot-placeholder "
                    "signals was present; record retained as a selectable ability"
                ),
                "status": "unresolved",
            }
            unresolved_placeholder_candidates += 1
        elif not isinstance(ability.get("gameplayAbilityPackagePath"), str):
            ability["relationshipStatus"] = "unresolved-gameplay-ability"

    selectable_ability_records = [
        perk
        for perk in ability_records
        if not (perk.get("ability") or {}).get("placeholder")
    ]
    records_by_gameplay: dict[str, list[dict[str, Any]]] = {}
    for perk in selectable_ability_records:
        records_by_gameplay.setdefault(
            perk["ability"]["gameplayAbilityPackagePath"], []
        ).append(perk)

    aliases_by_canonical: dict[str, list[dict[str, Any]]] = {}
    aliased_ids: set[str] = set()
    unresolved_aliases = 0
    for perk in selectable_ability_records:
        if not _is_cross_kit_ability_chip(perk):
            continue
        ability = perk.get("ability")
        if not isinstance(ability, dict):
            continue
        origin_kit_id = _ability_owning_kit_id(perk)
        matches = [
            candidate
            for candidate in records_by_gameplay.get(
                ability["gameplayAbilityPackagePath"], []
            )
            if candidate.get("id") != perk.get("id")
            and not _is_cross_kit_ability_chip(candidate)
            and _ability_owning_kit_id(candidate) == origin_kit_id
            and (candidate.get("ability") or {}).get("role") == ability.get("role")
        ]
        if len(matches) == 1:
            canonical = matches[0]
            ability["aliasOf"] = canonical["id"]
            aliases_by_canonical.setdefault(canonical["id"], []).append(perk)
            aliased_ids.add(perk["id"])
        else:
            ability["aliasResolution"] = {
                "candidateIds": sorted(
                    candidate["id"]
                    for candidate in matches
                    if isinstance(candidate.get("id"), str)
                ),
                "reason": (
                    "cross-kit ability did not resolve to exactly one source chip "
                    "with the same gameplay target, role, and origin kit"
                ),
                "status": "unresolved",
            }
            unresolved_aliases += 1

    canonical_ability_records = [
        perk
        for perk in selectable_ability_records
        if perk.get("id") not in aliased_ids
    ]

    concepts: list[dict[str, Any]] = []
    unresolved_kits = 0
    for perk in sorted(canonical_ability_records, key=lambda item: str(item.get("id", ""))):
        ability = perk["ability"]
        eligibility = perk.get("kitEligibility") or {}
        origin_kit_id = _ability_owning_kit_id(perk)
        if not isinstance(origin_kit_id, str):
            ability["relationshipStatus"] = "unresolved-origin-kit"
            unresolved_kits += 1
            continue
        aliases = aliases_by_canonical.get(perk["id"], [])
        available = [origin_kit_id]
        restricted_kit_id = eligibility.get("restrictedKitId")
        if isinstance(restricted_kit_id, str):
            available.append(restricted_kit_id)
        available.extend(eligibility.get("alternativeKitIds", []))
        for alias in aliases:
            alias_eligibility = alias.get("kitEligibility") or {}
            restricted = alias_eligibility.get("restrictedKitId")
            if isinstance(restricted, str):
                available.append(restricted)
            available.extend(alias_eligibility.get("alternativeKitIds", []))
        available_ids = list(dict.fromkeys(available))
        source_chip_ids = [perk["id"], *sorted(alias["id"] for alias in aliases)]
        concept: dict[str, Any] = {
            "availableToKitIds": available_ids,
            "gameplayAbilityPackagePath": ability["gameplayAbilityPackagePath"],
            "id": perk["id"],
            "originKitId": origin_kit_id,
            "role": ability["role"],
            "sourceChipIds": source_chip_ids,
        }
        if isinstance(perk.get("displayName"), str):
            concept["displayName"] = perk["displayName"]
        ability.update(
            {
                "availableToKitIds": available_ids,
                "originKitId": origin_kit_id,
                "sourceChipIds": source_chip_ids,
            }
        )
        implementation = by_id.get(ability["gameplayAbilityPackagePath"])
        if isinstance(implementation, dict):
            implementation.setdefault("implementationForAbilityIds", []).append(perk["id"])
        concepts.append(concept)

    for record in records:
        implementations = record.get("implementationForAbilityIds")
        if isinstance(implementations, list):
            record["implementationForAbilityIds"] = sorted(set(implementations))

    for kit in kit_by_class.values():
        by_role = {
            role: sorted(
                concept["id"]
                for concept in concepts
                if role == concept["role"] and kit["id"] in concept["availableToKitIds"]
            )
            for role in ("primary", "secondary", "passive")
        }
        kit["abilityPerkIdsByRole"] = by_role

    explicit_shapes = 0
    inferred_shapes = 0
    for perk in perks:
        shapes = (perk.get("grid") or {}).get("shapes", [])
        if not shapes:
            continue
        source = (shapes[0].get("evidence") or {}).get("source")
        if source == "serialized-uasset":
            explicit_shapes += 1
        elif source == "native-default-inferred":
            inferred_shapes += 1
    return concepts, {
        "kitAbilities": len(concepts),
        "kitAbilityAliases": sum(len(values) for values in aliases_by_canonical.values()),
        "kitAbilityAliasesUnresolved": unresolved_aliases,
        "kitAbilityPlaceholders": placeholders,
        "kitAbilityPlaceholderCandidatesUnresolved": unresolved_placeholder_candidates,
        "kitAbilitiesWithUnresolvedKit": unresolved_kits,
        "kitAbilityRolesUnresolved": unresolved_roles,
        "perkDependencyEdges": dependency_edges,
        "perkGridShapesExplicit": explicit_shapes,
        "perkGridShapesInferred": inferred_shapes,
        "perkModifiers": len(modifiers),
        "perkTargetsAcceptingModifiers": len(targets),
    }


def _first_object_package(
    prop: Mapping[str, Any] | None,
    asset: Mapping[str, Any],
) -> str | None:
    references = _object_references(prop, asset, path="")
    return references[0][1] if references else None


def _character_class_display_icon(
    asset: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Resolve the class-select art authored by a CharacterClass CDO.

    Kit unlock records can carry placeholder art.  The admitted CharacterClass
    is the runtime owner of the class-select icon, so retain that CDO as the
    structured provenance for either the resolved icon or an explicit fallback.
    """

    export = _default_export(asset)
    export_name = str(export.get("objectName", "")) if export is not None else ""
    property_path = (
        f"{export_name}.ClassDisplayIcon" if export_name else "ClassDisplayIcon"
    )
    provenance: dict[str, Any] = {
        "memberPath": asset.get("memberPath"),
        "property": property_path,
        "sourcePackagePath": asset.get("packagePath"),
        "type": "serialized-character-class-cdo",
    }
    if export is None:
        provenance["status"] = "no-export"
        return None, provenance

    field = _property_map(export.get("data")).get("ClassDisplayIcon")
    if field is None:
        provenance["status"] = "not-authored"
        return None, provenance

    references = _object_references(field, asset, path="")
    packages = list(dict.fromkeys(package for _, package in references))
    if len(packages) != 1:
        provenance["status"] = "no-single-object-reference"
        if packages:
            provenance["candidatePackagePaths"] = packages
        return None, provenance

    package = packages[0]
    reference_path = next(path for path, value in references if value == package)
    provenance["status"] = "resolved"
    return (
        {
            "packagePath": package,
            "provenance": provenance,
            "referenceEvidence": (
                f"{export_name}.{reference_path}" if export_name else reference_path
            ),
        },
        provenance,
    )


def _character_class_display_icon_packages(
    class_assets: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    """Return every resolvable CharacterClass display-icon dependency."""

    return tuple(
        sorted(
            {
                icon["packagePath"]
                for asset in class_assets
                for icon, _ in [_character_class_display_icon(asset)]
                if icon is not None
            }
        )
    )


def _normalized_enum(prop: Mapping[str, Any] | None) -> tuple[str | None, str | None]:
    raw = _enum(prop)
    tail = _enum_tail(raw)
    return raw, tail.casefold() if tail else None


def _weapon_slots_from_class(
    asset: Mapping[str, Any],
    records_by_id: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]] | None:
    export = _default_export(asset)
    if export is None:
        return None
    export_name = str(export.get("objectName", ""))
    fields = _property_map(export.get("data"))
    loadout = fields.get("GunLoadoutData")
    if loadout is None:
        return None
    result: list[dict[str, Any]] = []
    for index, entry in enumerate(_properties(loadout.get("Value"))):
        slot_fields = _property_map(entry.get("Value"))
        slot: dict[str, Any] = {
            "evidence": f"{export_name}.GunLoadoutData[{index}]",
            "index": index,
        }
        for property_name, value_name, raw_name in (
            ("GunSlotAvoType", "slotType", "slotTypeRaw"),
            ("GunSlotType", "weaponType", "weaponTypeRaw"),
            ("GunSlotSubType", "weaponSubtype", "weaponSubtypeRaw"),
        ):
            raw, normalized = _normalized_enum(slot_fields.get(property_name))
            if normalized:
                slot[value_name] = normalized
            if raw:
                slot[raw_name] = raw
        kit_tags = _gameplay_tags(slot_fields.get("GunKitTag"))
        if kit_tags and kit_tags[0] != "None":
            slot["kitTag"] = kit_tags[0]
        default_weapons = _soft_object_packages(slot_fields.get("GunClass"))
        if default_weapons:
            package = default_weapons[0]
            slot["defaultWeaponPackagePath"] = package
            candidate = records_by_id.get(package)
            if isinstance(candidate, Mapping) and candidate.get("kind") == "weapon":
                slot["defaultWeaponId"] = package
        result.append(slot)
    return result


def _chip_entitlements_from_class(
    asset: Mapping[str, Any],
    records_by_id: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]] | None:
    export = _default_export(asset)
    if export is None:
        return None
    export_name = str(export.get("objectName", ""))
    fields = _property_map(export.get("data"))
    entitlement_property = fields.get("ChipEntitlements")
    if entitlement_property is None:
        return None
    result: list[dict[str, Any]] = []
    for index, entry in enumerate(_properties(entitlement_property.get("Value"))):
        entitlement_fields = _property_map(entry.get("Value"))
        entitlement: dict[str, Any] = {
            "evidence": f"{export_name}.ChipEntitlements[{index}]",
            "index": index,
        }
        package = _first_object_package(
            entitlement_fields.get("ChipCDO"),
            asset,
        )
        if package:
            entitlement["perkPackagePath"] = package
            candidate = records_by_id.get(package)
            if isinstance(candidate, Mapping) and candidate.get("kind") == "perk":
                entitlement["perkId"] = package
        required_rank = _integer(
            (entitlement_fields.get("RequiredRank") or {}).get("Value"),
            minimum=0,
        )
        if required_rank is not None:
            entitlement["requiredRank"] = required_rank
        granted_by = _soft_object_packages(entitlement_fields.get("GrantedBy"))
        if granted_by:
            entitlement["grantedByPackagePath"] = granted_by[0]
        result.append(entitlement)
    return result


def _locked_placements_from_board(
    asset: Mapping[str, Any],
    records_by_id: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]] | None:
    export = _default_export(asset)
    if export is None:
        return None
    export_name = str(export.get("objectName", ""))
    fields = _property_map(export.get("data"))
    placement_property = fields.get("BoardLockedPlacements")
    if placement_property is None:
        return None
    result: list[dict[str, Any]] = []
    for index, entry in enumerate(_properties(placement_property.get("Value"))):
        placement_fields = _property_map(entry.get("Value"))
        placement: dict[str, Any] = {
            "evidence": f"{export_name}.BoardLockedPlacements[{index}]",
            "index": index,
        }
        package = _first_object_package(
            placement_fields.get("LockedSpecificChip"),
            asset,
        )
        if package:
            placement["chipPackagePath"] = package
            candidate = records_by_id.get(package)
            if isinstance(candidate, Mapping) and candidate.get("kind") == "perk":
                placement["chipId"] = package
        for property_name, output_name in (("Row", "row"), ("Column", "column")):
            value = _integer(
                (placement_fields.get(property_name) or {}).get("Value"),
                minimum=0,
            )
            if value is not None:
                placement[output_name] = value
        result.append(placement)
    return result


def _enrich_kit_class_data(
    records: Sequence[dict[str, Any]],
    *,
    candidate_assets_by_package: Mapping[str, Mapping[str, Any]],
    class_assets: Sequence[Mapping[str, Any]],
    kit_abilities: Sequence[dict[str, Any]],
) -> dict[str, int]:
    """Attach class-authored board, ability-slot, loadout, and unlock data."""

    records_by_id = {
        record["id"]: record
        for record in records
        if isinstance(record.get("id"), str)
    }
    classes_by_package = {
        asset["packagePath"]: asset
        for asset in class_assets
        if isinstance(asset, Mapping) and isinstance(asset.get("packagePath"), str)
    }
    referenced_classes = 0
    parsed_classes = 0
    class_display_icons = 0
    kit_unlock_icon_fallbacks = 0
    kits_with_boards = 0
    kits_with_weapon_slots = 0
    ability_slots = 0
    weapon_slots = 0
    default_weapons_unresolved = 0
    entitlements = 0
    entitlement_perks_unresolved = 0

    for kit in (record for record in records if record.get("kind") == "kit"):
        class_package = kit.get("characterClassPackagePath")
        if not isinstance(class_package, str):
            continue
        referenced_classes += 1
        class_asset = classes_by_package.get(class_package)
        if class_asset is None:
            continue
        parsed_classes += 1
        class_icon, class_icon_provenance = _character_class_display_icon(
            class_asset
        )
        if class_icon is not None:
            kit["icon"] = class_icon
            class_display_icons += 1
        else:
            unlock_icon = kit.get("icon")
            if isinstance(unlock_icon, dict):
                unlock_icon["fallback"] = {
                    "classDisplayIconProvenance": class_icon_provenance,
                    "reason": (
                        "admitted CharacterClass CDO has no single resolvable "
                        "ClassDisplayIcon"
                    ),
                    "sourceRecordId": kit.get("id"),
                    "type": "kit-unlock-icon",
                }
                kit_unlock_icon_fallbacks += 1
        export = _default_export(class_asset)
        if export is None:
            continue
        class_fields = _property_map(export.get("data"))

        slots = _weapon_slots_from_class(class_asset, records_by_id)
        if slots is not None:
            kit["weaponSlots"] = slots
            kits_with_weapon_slots += 1
            weapon_slots += len(slots)
            default_weapons_unresolved += sum(
                1
                for slot in slots
                if "defaultWeaponPackagePath" in slot and "defaultWeaponId" not in slot
            )

        class_entitlements = _chip_entitlements_from_class(
            class_asset,
            records_by_id,
        )
        if class_entitlements is not None:
            kit["chipEntitlements"] = class_entitlements
            entitlements += len(class_entitlements)
            entitlement_perks_unresolved += sum(
                1
                for entitlement in class_entitlements
                if "perkPackagePath" in entitlement and "perkId" not in entitlement
            )

        board_package = _first_object_package(
            class_fields.get("ChipBoardDef"),
            class_asset,
        )
        if not board_package:
            continue
        board: dict[str, Any] = {"packagePath": board_package}
        board_record = records_by_id.get(board_package)
        if isinstance(board_record, Mapping) and board_record.get("kind") == "gridShape":
            board["recordId"] = board_package
        board_asset = candidate_assets_by_package.get(board_package)
        if board_asset is not None:
            locked = _locked_placements_from_board(board_asset, records_by_id)
            if locked is not None:
                board["lockedPlacements"] = locked
        kit["perkBoard"] = board
        kits_with_boards += 1

        kit_roles = kit.get("abilityPerkIdsByRole")
        available_by_role = kit_roles if isinstance(kit_roles, dict) else {}
        locked_placements = board.get("lockedPlacements")
        if isinstance(locked_placements, list) and all(
            isinstance(placement, Mapping)
            and (
                "chipPackagePath" not in placement
                or "chipId" in placement
            )
            for placement in locked_placements
        ):
            supported_roles: set[str] = set()
            for placement in locked_placements:
                chip_id = placement.get("chipId")
                chip = records_by_id.get(chip_id) if isinstance(chip_id, str) else None
                ability = chip.get("ability") if isinstance(chip, Mapping) else None
                role = ability.get("role") if isinstance(ability, Mapping) else None
                if role in {"primary", "secondary", "passive"}:
                    supported_roles.add(role)
            removed_ability_ids: set[str] = set()
            for role in ("primary", "secondary", "passive"):
                choices = available_by_role.get(role, [])
                if role not in supported_roles and isinstance(choices, list):
                    removed_ability_ids.update(
                        value for value in choices if isinstance(value, str)
                    )
                    available_by_role[role] = []
            if removed_ability_ids:
                for concept in kit_abilities:
                    if concept.get("id") not in removed_ability_ids:
                        continue
                    availability = concept.get("availableToKitIds")
                    if isinstance(availability, list):
                        concept["availableToKitIds"] = [
                            value for value in availability if value != kit.get("id")
                        ]
                    source = records_by_id.get(concept.get("id"))
                    source_ability = (
                        source.get("ability") if isinstance(source, Mapping) else None
                    )
                    source_availability = (
                        source_ability.get("availableToKitIds")
                        if isinstance(source_ability, dict)
                        else None
                    )
                    if isinstance(source_availability, list):
                        source_ability["availableToKitIds"] = [
                            value
                            for value in source_availability
                            if value != kit.get("id")
                        ]
        resolved_slots: list[dict[str, Any]] = []
        for placement in board.get("lockedPlacements", []):
            if not isinstance(placement, Mapping):
                continue
            chip_id = placement.get("chipId")
            chip = records_by_id.get(chip_id) if isinstance(chip_id, str) else None
            ability = chip.get("ability") if isinstance(chip, Mapping) else None
            role = ability.get("role") if isinstance(ability, Mapping) else None
            if role not in {"primary", "secondary", "passive"}:
                continue
            slot = {
                key: placement[key]
                for key in ("column", "index", "row")
                if key in placement
            }
            slot["lockedChipId"] = chip_id
            slot["role"] = role
            input_bind = ability.get("inputBindRaw")
            if isinstance(input_bind, str):
                slot["inputBindRaw"] = input_bind
            selectable = available_by_role.get(role, [])
            slot["selectableAbilityPerkIds"] = (
                list(selectable) if isinstance(selectable, list) else []
            )
            resolved_slots.append(slot)
        kit["abilitySlots"] = resolved_slots
        ability_slots += len(resolved_slots)

    return {
        "characterClassesParsed": parsed_classes,
        "characterClassesReferenced": referenced_classes,
        "characterClassesUnresolved": referenced_classes - parsed_classes,
        "kitClassDisplayIcons": class_display_icons,
        "kitUnlockIconFallbacks": kit_unlock_icon_fallbacks,
        "chipEntitlements": entitlements,
        "chipEntitlementPerksUnresolved": entitlement_perks_unresolved,
        "kitAbilitySlots": ability_slots,
        "kitsWithPerkBoard": kits_with_boards,
        "kitsWithWeaponSlots": kits_with_weapon_slots,
        "weaponSlotDefaultWeaponsUnresolved": default_weapons_unresolved,
        "weaponSlots": weapon_slots,
    }


def normalize_semantic_document(
    *,
    candidates: Sequence[Mapping[str, Any]],
    candidate_assets: Sequence[Mapping[str, Any]],
    candidate_failures: Sequence[Mapping[str, Any]],
    effect_assets: Sequence[Mapping[str, Any]],
    dependency_failures: Sequence[Mapping[str, Any]],
    icon_metadata: Sequence[Mapping[str, Any]],
    icon_bytes: Mapping[str, bytes],
    source_fingerprint: str,
    class_assets: Sequence[Mapping[str, Any]] = (),
    item_slot_assets: Sequence[Mapping[str, Any]] = (),
    parent_assets: Sequence[Mapping[str, Any]] = (),
    resolve_weapon_compatibility: bool = False,
) -> SemanticBuild:
    """Pure normalization boundary, suitable for game-free synthetic fixtures."""

    assets_by_package = {
        item["packagePath"]: item
        for item in candidate_assets
        if isinstance(item, Mapping) and isinstance(item.get("packagePath"), str)
    }
    parent_assets_by_package = {
        item["packagePath"]: item
        for item in parent_assets
        if isinstance(item, Mapping) and isinstance(item.get("packagePath"), str)
    }
    failed_by_package = {
        item.get("packagePath"): item.get("reason")
        for item in candidate_failures
        if isinstance(item, Mapping)
    }
    records: list[dict[str, Any]] = []
    for candidate in sorted(candidates, key=lambda item: str(item.get("id", ""))):
        package = candidate.get("packagePath")
        asset = assets_by_package.get(package)
        if asset is None:
            records.append(
                {
                    "failure": failed_by_package.get(package, "reader-returned-no-asset"),
                    "id": candidate.get("id", package),
                    "kind": candidate.get("kind"),
                    "packagePath": package,
                    "status": "unreadable",
                }
            )
            continue
        records.append(
            _candidate_semantics(
                candidate,
                asset,
                parent_assets_by_package=parent_assets_by_package,
            )
        )

    _resolve_chip_visual_families(records)
    _apply_icon_fallbacks(records)
    kit_abilities, relationship_coverage = _enrich_record_relationships(records)
    class_coverage = _enrich_kit_class_data(
        records,
        candidate_assets_by_package=assets_by_package,
        class_assets=class_assets,
        kit_abilities=kit_abilities,
    )
    default_player_asset = next(
        (
            asset
            for asset in item_slot_assets
            if asset.get("packagePath") == _DEFAULT_PLAYER_CHARACTER
        ),
        None,
    )
    item_slots = (
        _item_slots_from_default_player(default_player_asset)
        if default_player_asset is not None
        else []
    )
    compatibility_coverage: dict[str, int] = {}
    compatibility_diagnostics: dict[str, list[dict[str, Any]]] | None = None
    if resolve_weapon_compatibility:
        try:
            compatibility_build = build_weapon_compatibility(
                records=records,
                candidate_assets=candidate_assets,
                parent_assets=parent_assets,
            )
        except ValueError as exc:
            raise CatalogueError(f"weapon compatibility normalization failed: {exc}") from exc
        records = compatibility_build.records
        compatibility_coverage = {
            f"weaponCompatibility{key[:1].upper()}{key[1:]}": value
            for key, value in compatibility_build.coverage.items()
        }
        compatibility_diagnostics = compatibility_build.diagnostics

    effect_definitions = {
        item["packagePath"]: _effect_definition(item)
        for item in effect_assets
        if isinstance(item, Mapping) and isinstance(item.get("packagePath"), str)
    }
    metadata_by_package = {
        item["packagePath"]: item
        for item in icon_metadata
        if isinstance(item, Mapping) and isinstance(item.get("packagePath"), str)
    }
    binaries: dict[str, bytes] = {}
    decoded_icon_packages: set[str] = set()
    stat_count = 0
    effect_link_count = 0
    mechanically_resolved_effects = 0
    records_with_display_name = 0
    records_with_conditional_descriptions = 0
    records_with_icon = 0
    records_with_silhouette_icon = 0
    records_with_stats = 0
    perk_visual_families_inferred = 0
    perk_visual_families_resolved = 0
    perk_visual_families_unresolved = 0
    compatibility_partial = 0
    effect_references: set[str] = set()
    icon_references: set[str] = set()
    for record in records:
        chip_visual = record.get("chipVisual")
        if isinstance(chip_visual, Mapping):
            if chip_visual.get("status") == "resolved":
                perk_visual_families_resolved += 1
            elif chip_visual.get("status") == "inferred":
                perk_visual_families_inferred += 1
            else:
                perk_visual_families_unresolved += 1
        if isinstance(record.get("displayName"), str):
            records_with_display_name += 1
        if isinstance(record.get("conditionalDescriptions"), list):
            records_with_conditional_descriptions += 1
        if (record.get("compatibility") or {}).get("status") == "partial":
            compatibility_partial += 1
        effects = record.get("effects")
        stats: list[dict[str, Any]] = []
        if isinstance(effects, list):
            for effect in effects:
                if not isinstance(effect, dict):
                    continue
                effect_link_count += 1
                package = effect.get("effectPackagePath")
                if isinstance(package, str):
                    effect_references.add(package)
                    definition = effect_definitions.get(package)
                    if definition:
                        effect["definition"] = definition
                        produced = _mechanical_stats(effect, definition)
                        if produced:
                            mechanically_resolved_effects += 1
                        stats.extend(produced)
        if stats:
            record["stats"] = stats
            stat_count += len(stats)
            records_with_stats += 1

        for field in ("icon", "silhouetteIcon"):
            icon = record.get(field)
            if not isinstance(icon, dict) or not isinstance(icon.get("packagePath"), str):
                continue
            package = icon["packagePath"]
            icon_references.add(package)
            metadata = metadata_by_package.get(package)
            if not metadata:
                continue
            output_name = metadata.get("outputName")
            payload = icon_bytes.get(str(output_name))
            if payload is None or not payload.startswith(_PNG_SIGNATURE):
                continue
            relative = f"icons/{output_name}"
            binaries[relative] = payload
            icon.update(
                {
                    "height": metadata.get("height"),
                    "path": relative,
                    "pixelFormat": metadata.get("pixelFormat"),
                    "sha256": f"sha256:{hashlib.sha256(payload).hexdigest()}",
                    "width": metadata.get("width"),
                }
            )
            decoded_icon_packages.add(package)
            if field == "icon":
                records_with_icon += 1
            else:
                records_with_silhouette_icon += 1

    failures = [
        {
            "packagePath": item.get("packagePath"),
            "reason": item.get("reason"),
            "stage": item.get("stage"),
        }
        for item in [*candidate_failures, *dependency_failures]
        if isinstance(item, Mapping)
    ]
    failures.sort(key=lambda item: (str(item.get("packagePath")), str(item.get("stage"))))
    document: dict[str, Any] = {
        "coverage": {
            "candidateAssetsFailed": len(candidates) - len(assets_by_package),
            "candidateAssetsParsed": len(assets_by_package),
            "candidateAssetsRequested": len(candidates),
            "blueprintParentsParsed": len(parent_assets),
            "effectDefinitionsParsed": len(effect_definitions),
            "effectDefinitionsReferenced": len(effect_references),
            "effectDefinitionsUnresolved": len(effect_references - set(effect_definitions)),
            "iconsDecoded": len(decoded_icon_packages),
            "iconsReferenced": len(icon_references),
            "iconsUnresolved": len(icon_references - decoded_icon_packages),
            "itemSlotSourceAssetsParsed": int(default_player_asset is not None),
            "itemSlots": len(item_slots),
            "mechanicalStats": stat_count,
            "mechanicsEffectLinks": effect_link_count,
            "mechanicsEffectLinksUnresolved": effect_link_count - mechanically_resolved_effects,
            "perkVisualFamiliesInferred": perk_visual_families_inferred,
            "perkVisualFamiliesResolved": perk_visual_families_resolved,
            "perkVisualFamiliesUnresolved": perk_visual_families_unresolved,
            "recordsCompatibilityPartial": compatibility_partial,
            "recordsWithConditionalDescriptions": records_with_conditional_descriptions,
            "recordsWithDisplayName": records_with_display_name,
            "recordsWithIcon": records_with_icon,
            "recordsWithMechanicalStats": records_with_stats,
            "recordsWithSilhouetteIcon": records_with_silhouette_icon,
            **relationship_coverage,
            **class_coverage,
            **compatibility_coverage,
        },
        "effectDefinitions": [effect_definitions[key] for key in sorted(effect_definitions)],
        "engineVersion": "UE4_27",
        "failures": failures,
        "itemSlots": item_slots,
        "kitAbilities": kit_abilities,
        "records": records,
        "schemaVersion": 1,
        "selectionBasis": "archive-candidates",
        "sourceFingerprint": source_fingerprint,
    }
    if compatibility_diagnostics is not None:
        document["weaponCompatibilityDiagnostics"] = compatibility_diagnostics
    return SemanticBuild(document=document, binary_files=dict(sorted(binaries.items())))


def apply_semantic_evidence(
    *,
    candidates: dict[str, Any],
    semantic: Mapping[str, Any],
) -> None:
    """Attach planner-useful semantic fields and stable cross-document identities."""

    semantic_by_id = {
        item["id"]: item
        for item in semantic.get("records", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    fields = (
        "ability",
        "abilityPerkIdsByRole",
        "abilitySlots",
        "characterClassPackagePath",
        "chipEntitlements",
        "chipVisual",
        "conditionalDescriptions",
        "conditionalDescriptionsResolution",
        "displayName",
        "dependencies",
        "description",
        "grid",
        "implementationForAbilityIds",
        "itemTier",
        "itemTierResolution",
        "kitEligibility",
        "parentClassPath",
        "parentPackagePath",
        "perkBoard",
        "perkType",
        "compatibility",
        "icon",
        "serializedIcon",
        "silhouetteIcon",
        "effects",
        "stats",
        "weaponSlots",
    )
    for candidate in candidates.get("records", []):
        if not isinstance(candidate, dict):
            continue
        resolved = semantic_by_id.get(candidate.get("id"))
        if not resolved:
            continue
        candidate["semanticRecord"] = {
            "document": "semantic-assets.json",
            "id": resolved["id"],
            "status": resolved.get("status"),
        }
        for field in fields:
            if field in resolved:
                candidate[field] = copy.deepcopy(resolved[field])
        missing = candidate.get("missingFields")
        if isinstance(missing, list):
            removed = {"exports"}
            if isinstance(resolved.get("displayName"), str):
                removed.add("localizedDisplayName")
            candidate["missingFields"] = [value for value in missing if value not in removed]


def _extract_blueprint_parent_assets(
    *,
    seed_assets: Sequence[Mapping[str, Any]],
    members: Mapping[str, str],
    paks_dir: Path,
    retoc: Path,
    archive_key: str,
    reader: ManagedSemanticReader,
    loose_root: Path,
    work: Path,
    secret_environment_names: Sequence[str],
    jobs: int = 1,
    label_prefix: str = "blueprint-parents",
    stop_at_authored_properties: frozenset[str] = frozenset(),
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Materialize the finite Blueprint-parent closure of selected assets.

    UAsset exports contain only properties overridden by that Blueprint.  Exact
    attachment compatibility and inherited player-facing metadata therefore
    require the authored parent CDOs as well as the leaf candidate CDO.
    """

    def needs_parent(asset: Mapping[str, Any]) -> bool:
        return not (
            stop_at_authored_properties
            & _authored_blueprint_property_names(asset)
        )

    known: dict[str, Mapping[str, Any]] = {
        item["packagePath"]: item
        for item in seed_assets
        if isinstance(item, Mapping) and isinstance(item.get("packagePath"), str)
    }
    auxiliary: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, str]] = []
    attempted = set(known)
    pending = {
        parent
        for asset in known.values()
        if needs_parent(asset)
        if (parent := _blueprint_parent_package(asset)) is not None
        and parent not in attempted
    }
    round_index = 0
    while pending:
        if round_index >= 32:
            raise CatalogueError("Blueprint parent graph exceeded the safe traversal limit")
        round_index += 1
        requested: list[dict[str, str]] = []
        for package in sorted(pending):
            attempted.add(package)
            member = members.get(package)
            if member is None:
                failures.append(
                    {
                        "packagePath": package,
                        "reason": "blueprint-parent-had-no-uasset-member",
                        "stage": "parent-index",
                    }
                )
            else:
                requested.append({"memberPath": member, "packagePath": package})
        if not requested:
            pending = set()
            continue
        _extract_members(
            paks_dir=paks_dir,
            retoc=retoc,
            key=archive_key,
            loose_root=loose_root,
            members=(item["memberPath"] for item in requested),
        )
        result, _ = _run_reader(
            reader,
            request={"assets": requested, "icons": [], "schemaVersion": 1},
            loose_root=loose_root,
            work=work,
            label=f"{label_prefix}-{round_index}",
            secret_environment_names=secret_environment_names,
            jobs=jobs,
        )
        parsed = [item for item in result.get("assets", []) if isinstance(item, dict)]
        for item in parsed:
            package = item.get("packagePath")
            if isinstance(package, str):
                known[package] = item
                auxiliary[package] = item
        failures.extend(
            {
                "packagePath": str(item.get("packagePath")),
                "reason": str(item.get("reason")),
                "stage": "parent-reader",
            }
            for item in result.get("failures", [])
            if isinstance(item, Mapping)
        )
        pending = {
            parent
            for asset in parsed
            if needs_parent(asset)
            if (parent := _blueprint_parent_package(asset)) is not None
            and parent not in attempted
        }
    return [auxiliary[key] for key in sorted(auxiliary)], failures


def _extract_collection_document(
    *,
    seed_assets: Sequence[Mapping[str, Any]],
    candidate_records: Sequence[Mapping[str, Any]],
    members: Mapping[str, str],
    paks_dir: Path,
    retoc: Path,
    archive_key: str,
    reader: ManagedSemanticReader,
    loose_root: Path,
    work: Path,
    source_fingerprint: str,
    secret_environment_names: Sequence[str],
    jobs: int = 1,
) -> tuple[dict[str, Any], list[dict[str, str]], list[dict[str, Any]]]:
    """Read the live hub store and only the product graph reachable from it."""

    store_member = members.get(_COLLECTION_STORE)
    if store_member is None:
        raise CatalogueError("archive contained no canonical main-hub credit store")
    _extract_members(
        paks_dir=paks_dir,
        retoc=retoc,
        key=archive_key,
        loose_root=loose_root,
        members=(store_member,),
    )
    store_result, _ = _run_reader(
        reader,
        request={
            "assets": [
                {"memberPath": store_member, "packagePath": _COLLECTION_STORE}
            ],
            "icons": [],
            "schemaVersion": 1,
        },
        loose_root=loose_root,
        work=work,
        label="collection-store",
        secret_environment_names=secret_environment_names,
        jobs=jobs,
    )
    store_assets = [
        item for item in store_result.get("assets", []) if isinstance(item, dict)
    ]
    if len(store_assets) != 1:
        raise CatalogueError("canonical main-hub credit store could not be parsed")
    store_asset = store_assets[0]

    known_terminal = {
        item["packagePath"]
        for item in seed_assets
        if isinstance(item, Mapping) and isinstance(item.get("packagePath"), str)
    }
    attempted = set(known_terminal) | {_COLLECTION_STORE}
    wrappers: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, str]] = []
    try:
        pending = set(collection_product_package_paths(store_asset)) - attempted
    except CollectionFormatError as exc:
        raise CatalogueError(f"canonical Collection store was malformed: {exc}") from exc

    round_index = 0
    while pending:
        if round_index >= 16:
            raise CatalogueError("Collection product graph exceeded the safe traversal limit")
        round_index += 1
        requests: list[dict[str, str]] = []
        for package in sorted(pending):
            attempted.add(package)
            member = members.get(package)
            if member is None:
                failures.append(
                    {
                        "packagePath": package,
                        "reason": "collection-product-had-no-uasset-member",
                        "stage": "collection-index",
                    }
                )
            else:
                requests.append({"memberPath": member, "packagePath": package})
        if not requests:
            break
        _extract_members(
            paks_dir=paks_dir,
            retoc=retoc,
            key=archive_key,
            loose_root=loose_root,
            members=(item["memberPath"] for item in requests),
        )
        result, _ = _run_reader(
            reader,
            request={"assets": requests, "icons": [], "schemaVersion": 1},
            loose_root=loose_root,
            work=work,
            label=f"collection-products-{round_index}",
            secret_environment_names=secret_environment_names,
            jobs=jobs,
        )
        parsed = [item for item in result.get("assets", []) if isinstance(item, dict)]
        for item in parsed:
            package = item.get("packagePath")
            if isinstance(package, str):
                wrappers[package] = item
        failures.extend(
            {
                "packagePath": str(item.get("packagePath")),
                "reason": str(item.get("reason")),
                "stage": "collection-reader",
            }
            for item in result.get("failures", [])
            if isinstance(item, Mapping)
        )
        dependencies = set(collection_wrapper_dependency_paths(wrappers.values()))
        pending = dependencies - attempted

    try:
        document = build_collection_document(
            store_asset=store_asset,
            wrapper_assets=[wrappers[key] for key in sorted(wrappers)],
            terminal_assets=seed_assets,
            candidate_records=candidate_records,
            source_fingerprint=source_fingerprint,
        )
    except CollectionFormatError as exc:
        raise CatalogueError(f"canonical Collection store was malformed: {exc}") from exc
    return document, failures, [wrappers[key] for key in sorted(wrappers)]


def _select_kit_reward_registry_packages(
    package_index: Mapping[str, Any],
) -> tuple[str, ...]:
    """Select live metagame registry assets without naming individual kits."""

    packages = package_index.get("packages")
    if not isinstance(packages, list):
        raise CatalogueError("package index has no packages array for kit registries")
    return tuple(
        sorted(
            {
                package
                for item in packages
                if isinstance(item, Mapping)
                and isinstance((package := item.get("packagePath")), str)
                and _KIT_REWARD_REGISTRY.fullmatch(package)
            }
        )
    )


def _extract_kit_membership_index(
    *,
    kit_records: Sequence[Mapping[str, Any]],
    members: Mapping[str, str],
    registry_package_paths: Sequence[str],
    paks_dir: Path,
    retoc: Path,
    archive_key: str,
    reader: ManagedSemanticReader,
    loose_root: Path,
    work: Path,
    secret_environment_names: Sequence[str],
    jobs: int = 1,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Read canonical class-unlock rewards and map them to KitUnlock records."""

    starting_member = members.get(_DEFAULT_STARTING_REWARDS)
    if starting_member is None:
        raise CatalogueError("archive contained no canonical default-starting rewards")
    selected_registry_packages = tuple(sorted(set(registry_package_paths)))
    if not selected_registry_packages:
        raise CatalogueError("archive contained no live metagame reward registries")
    registry_members = {
        package: members[package]
        for package in selected_registry_packages
        if package in members
    }

    source_requests = [
        {
            "memberPath": member,
            "packagePath": package,
        }
        for package, member in sorted(
            {_DEFAULT_STARTING_REWARDS: starting_member, **registry_members}.items()
        )
    ]
    _extract_members(
        paks_dir=paks_dir,
        retoc=retoc,
        key=archive_key,
        loose_root=loose_root,
        members=(item["memberPath"] for item in source_requests),
    )
    source_result, _ = _run_reader(
        reader,
        request={"assets": source_requests, "icons": [], "schemaVersion": 1},
        loose_root=loose_root,
        work=work,
        label="kit-membership-sources",
        secret_environment_names=secret_environment_names,
        jobs=jobs,
    )
    source_assets = {
        item["packagePath"]: item
        for item in source_result.get("assets", [])
        if isinstance(item, dict) and isinstance(item.get("packagePath"), str)
    }
    starting_asset = source_assets.get(_DEFAULT_STARTING_REWARDS)
    if starting_asset is None:
        raise CatalogueError("canonical default-starting rewards could not be parsed")
    registry_assets = [
        source_assets[package]
        for package in sorted(registry_members)
        if package in source_assets
    ]
    failures: list[dict[str, str]] = [
        {
            "packagePath": str(item.get("packagePath")),
            "reason": str(item.get("reason")),
            "stage": "kit-membership-source-reader",
        }
        for item in source_result.get("failures", [])
        if isinstance(item, Mapping)
    ]

    imported_paths = set(kit_reward_registry_dependency_paths(registry_assets))
    imported_requests: list[dict[str, str]] = []
    for package in sorted(imported_paths):
        member = members.get(package)
        if member is None:
            failures.append(
                {
                    "packagePath": package,
                    "reason": "registry-imported-class-had-no-uasset-member",
                    "stage": "kit-membership-index",
                }
            )
        else:
            imported_requests.append({"memberPath": member, "packagePath": package})

    referenced: dict[str, dict[str, Any]] = {}
    if imported_requests:
        _extract_members(
            paks_dir=paks_dir,
            retoc=retoc,
            key=archive_key,
            loose_root=loose_root,
            members=(item["memberPath"] for item in imported_requests),
        )
        imported_result, _ = _run_reader(
            reader,
            request={"assets": imported_requests, "icons": [], "schemaVersion": 1},
            loose_root=loose_root,
            work=work,
            label="kit-membership-registry-imports",
            secret_environment_names=secret_environment_names,
            jobs=jobs,
        )
        for item in imported_result.get("assets", []):
            if isinstance(item, dict) and isinstance(item.get("packagePath"), str):
                referenced[item["packagePath"]] = item
        failures.extend(
            {
                "packagePath": str(item.get("packagePath")),
                "reason": str(item.get("reason")),
                "stage": "kit-membership-import-reader",
            }
            for item in imported_result.get("failures", [])
            if isinstance(item, Mapping)
        )

    parent_assets, parent_failures = _extract_blueprint_parent_assets(
        seed_assets=list(referenced.values()),
        members=members,
        paks_dir=paks_dir,
        retoc=retoc,
        archive_key=archive_key,
        reader=reader,
        loose_root=loose_root,
        work=work,
        secret_environment_names=secret_environment_names,
        jobs=jobs,
        label_prefix="kit-membership-parents",
        stop_at_authored_properties=frozenset({"RewardTable"}),
    )
    for item in parent_assets:
        package = item.get("packagePath")
        if isinstance(package, str):
            referenced[package] = item
    failures.extend(parent_failures)

    registry_roots = set(
        kit_reward_table_package_paths(
            registry_assets=registry_assets,
            referenced_assets=referenced.values(),
        )
    )
    graph_roots = {_DEFAULT_STARTING_REWARDS, *registry_roots}
    graph_assets: dict[str, dict[str, Any]] = {
        _DEFAULT_STARTING_REWARDS: starting_asset,
        **referenced,
    }
    attempted = set(graph_assets)
    round_index = 0
    while True:
        pending = set(
            kit_reward_table_dependency_paths(
                reward_table_assets=graph_assets.values(),
                root_package_paths=graph_roots,
            )
        ) - attempted
        if not pending:
            break
        if round_index >= 32:
            raise CatalogueError("kit reward-table graph exceeded the safe traversal limit")
        round_index += 1
        requests: list[dict[str, str]] = []
        for package in sorted(pending):
            attempted.add(package)
            member = members.get(package)
            if member is None:
                failures.append(
                    {
                        "packagePath": package,
                        "reason": "kit-reward-table-dependency-had-no-uasset-member",
                        "stage": "kit-membership-index",
                    }
                )
            else:
                requests.append({"memberPath": member, "packagePath": package})
        if not requests:
            continue
        _extract_members(
            paks_dir=paks_dir,
            retoc=retoc,
            key=archive_key,
            loose_root=loose_root,
            members=(item["memberPath"] for item in requests),
        )
        result, _ = _run_reader(
            reader,
            request={"assets": requests, "icons": [], "schemaVersion": 1},
            loose_root=loose_root,
            work=work,
            label=f"kit-membership-reward-dependencies-{round_index}",
            secret_environment_names=secret_environment_names,
            jobs=jobs,
        )
        for item in result.get("assets", []):
            if isinstance(item, dict) and isinstance(item.get("packagePath"), str):
                graph_assets[item["packagePath"]] = item
        failures.extend(
            {
                "packagePath": str(item.get("packagePath")),
                "reason": str(item.get("reason")),
                "stage": "kit-membership-reward-reader",
            }
            for item in result.get("failures", [])
            if isinstance(item, Mapping)
        )

    try:
        document = build_kit_membership_index(
            starting_asset=starting_asset,
            registry_assets=registry_assets,
            reward_table_assets=[graph_assets[key] for key in sorted(graph_assets)],
            kit_records=kit_records,
        )
    except CollectionFormatError as exc:
        raise CatalogueError(f"canonical kit reward sources were malformed: {exc}") from exc

    missing_registry_members = sorted(
        set(selected_registry_packages) - set(registry_members)
    )
    missing_registry_assets = sorted(set(registry_members) - set(source_assets))
    if missing_registry_members or missing_registry_assets:
        document["source"]["registryPackagePaths"] = list(
            selected_registry_packages
        )
        document["coverage"]["registryAssets"] = len(selected_registry_packages)
        document["unresolved"].extend(
            {
                "packagePath": package,
                "reason": "metamission-registry-had-no-uasset-member",
                "sourceKind": "metamission-registry",
            }
            for package in missing_registry_members
        )
        document["unresolved"].extend(
            {
                "packagePath": package,
                "reason": "metamission-registry-unresolved",
                "sourceKind": "metamission-registry",
            }
            for package in missing_registry_assets
        )
        document["unresolved"].sort(
            key=lambda value: (
                str(value.get("registryPackagePath", "")),
                str(value.get("rootRewardTablePackagePath", "")),
                str(value.get("packagePath", "")),
                str(value.get("reason", "")),
            )
        )
        document["coverage"]["unresolvedReferences"] = len(document["unresolved"])
        document["status"] = "incomplete"
    return document, failures


def _extract_progression_perk_index(
    *,
    candidate_records: Sequence[Mapping[str, Any]],
    members: Mapping[str, str],
    paks_dir: Path,
    retoc: Path,
    archive_key: str,
    reader: ManagedSemanticReader,
    loose_root: Path,
    work: Path,
    secret_environment_names: Sequence[str],
    jobs: int = 1,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Read the authored progression registry and its reachable table graph."""

    settings_member = members.get(_PROGRESSION_SETTINGS)
    if settings_member is None:
        raise CatalogueError("archive contained no canonical reward-table settings asset")
    _extract_members(
        paks_dir=paks_dir,
        retoc=retoc,
        key=archive_key,
        loose_root=loose_root,
        members=(settings_member,),
    )
    settings_result, _ = _run_reader(
        reader,
        request={
            "assets": [
                {
                    "memberPath": settings_member,
                    "packagePath": _PROGRESSION_SETTINGS,
                }
            ],
            "icons": [],
            "schemaVersion": 1,
        },
        loose_root=loose_root,
        work=work,
        label="progression-settings",
        secret_environment_names=secret_environment_names,
        jobs=jobs,
    )
    settings_assets = [
        item for item in settings_result.get("assets", []) if isinstance(item, dict)
    ]
    if len(settings_assets) != 1:
        raise CatalogueError("canonical reward-table settings asset could not be parsed")
    settings_asset = settings_assets[0]

    try:
        pending = set(progression_reward_table_package_paths(settings_asset))
    except CollectionFormatError as exc:
        raise CatalogueError(f"canonical progression settings were malformed: {exc}") from exc

    attempted = {_PROGRESSION_SETTINGS}
    reward_tables: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, str]] = []
    round_index = 0
    while pending:
        round_index += 1
        requests: list[dict[str, str]] = []
        for package in sorted(pending):
            attempted.add(package)
            member = members.get(package)
            if member is None:
                failures.append(
                    {
                        "packagePath": package,
                        "reason": "progression-reward-table-had-no-uasset-member",
                        "stage": "progression-index",
                    }
                )
            else:
                requests.append({"memberPath": member, "packagePath": package})
        if not requests:
            break
        _extract_members(
            paks_dir=paks_dir,
            retoc=retoc,
            key=archive_key,
            loose_root=loose_root,
            members=(item["memberPath"] for item in requests),
        )
        result, _ = _run_reader(
            reader,
            request={"assets": requests, "icons": [], "schemaVersion": 1},
            loose_root=loose_root,
            work=work,
            label=f"progression-reward-tables-{round_index}",
            secret_environment_names=secret_environment_names,
            jobs=jobs,
        )
        parsed = [item for item in result.get("assets", []) if isinstance(item, dict)]
        for item in parsed:
            package = item.get("packagePath")
            if isinstance(package, str):
                reward_tables[package] = item
        failures.extend(
            {
                "packagePath": str(item.get("packagePath")),
                "reason": str(item.get("reason")),
                "stage": "progression-reader",
            }
            for item in result.get("failures", [])
            if isinstance(item, Mapping)
        )
        dependencies = set(
            progression_reward_table_dependency_paths(reward_tables.values())
        )
        pending = dependencies - attempted

    try:
        document = build_progression_perk_index(
            settings_asset=settings_asset,
            reward_table_assets=[reward_tables[key] for key in sorted(reward_tables)],
            candidate_records=candidate_records,
        )
    except CollectionFormatError as exc:
        raise CatalogueError(f"canonical progression settings were malformed: {exc}") from exc
    return document, failures


def build_semantic_assets(
    *,
    paks_dir: Path,
    retoc: Path,
    archive_key: str,
    reader: ManagedSemanticReader,
    package_index: Mapping[str, Any],
    candidates: Mapping[str, Any],
    source_fingerprint: str,
    secret_environment_names: Sequence[str] = (),
    jobs: int = 1,
) -> SemanticBuild:
    """Convert catalogue semantics and the source-derived perk-grid UI bundle."""

    candidate_records = candidates.get("records")
    if not isinstance(candidate_records, list):
        raise CatalogueError("candidate records were unavailable for semantic extraction")
    members = _member_map(package_index)
    requests: list[dict[str, str]] = []
    missing_candidate_failures: list[dict[str, str]] = []
    for candidate in candidate_records:
        if not isinstance(candidate, dict) or not isinstance(candidate.get("packagePath"), str):
            continue
        package = candidate["packagePath"]
        member = members.get(package)
        if member:
            requests.append({"memberPath": member, "packagePath": package})
        else:
            missing_candidate_failures.append(
                {
                    "packagePath": package,
                    "reason": "package-had-no-uasset-member",
                    "stage": "candidate-index",
                }
            )

    if missing_candidate_failures:
        raise CatalogueError(
            f"{len(missing_candidate_failures)} archive candidate(s) had no extractable uasset; "
            "semantic output was not generated"
        )

    with tempfile.TemporaryDirectory(prefix="afe2-semantic-assets-") as temporary:
        work = Path(temporary)
        loose = work / "loose"
        loose.mkdir()
        _extract_members(
            paks_dir=paks_dir,
            retoc=retoc,
            key=archive_key,
            loose_root=loose,
            members=(item["memberPath"] for item in requests),
        )
        first, _ = _run_reader(
            reader,
            request={"assets": requests, "icons": [], "schemaVersion": 1},
            loose_root=loose,
            work=work,
            label="candidates",
            secret_environment_names=secret_environment_names,
            jobs=jobs,
        )
        first_assets = first.get("assets", [])
        first_failures = [*missing_candidate_failures, *first.get("failures", [])]

        parent_assets, parent_failures = _extract_blueprint_parent_assets(
            seed_assets=[item for item in first_assets if isinstance(item, Mapping)],
            members=members,
            paks_dir=paks_dir,
            retoc=retoc,
            archive_key=archive_key,
            reader=reader,
            loose_root=loose,
            work=work,
            secret_environment_names=secret_environment_names,
            jobs=jobs,
        )
        collection_document, collection_failures, collection_wrapper_assets = (
            _extract_collection_document(
                seed_assets=[item for item in first_assets if isinstance(item, Mapping)],
                candidate_records=[
                    item for item in candidate_records if isinstance(item, Mapping)
                ],
                members=members,
                paks_dir=paks_dir,
                retoc=retoc,
                archive_key=archive_key,
                reader=reader,
                loose_root=loose,
                work=work,
                source_fingerprint=source_fingerprint,
                secret_environment_names=secret_environment_names,
                jobs=jobs,
            )
        )
        progression_perks, progression_failures = _extract_progression_perk_index(
            candidate_records=[
                item for item in candidate_records if isinstance(item, Mapping)
            ],
            members=members,
            paks_dir=paks_dir,
            retoc=retoc,
            archive_key=archive_key,
            reader=reader,
            loose_root=loose,
            work=work,
            secret_environment_names=secret_environment_names,
            jobs=jobs,
        )
        collection_document["progressionPerks"] = progression_perks
        collection_document["coverage"]["progressionPerks"] = len(
            progression_perks["memberIds"]
        )
        collection_document["coverage"]["progressionUnresolvedReferences"] = (
            progression_perks["coverage"]["unresolvedReferences"]
        )
        augment_category = next(
            (
                item
                for item in collection_document.get("categories", [])
                if isinstance(item, Mapping) and item.get("key") == "AugmentPacks"
            ),
            None,
        )
        augment_concept_packages = sorted(
            {
                item.get("id")
                for item in (augment_category or {}).get("entries", [])
                if isinstance(item, Mapping)
                and item.get("status") == "resolved"
                and isinstance(item.get("id"), str)
            }
        )
        collection_wrapper_by_package = {
            item["packagePath"]: item
            for item in collection_wrapper_assets
            if isinstance(item.get("packagePath"), str)
        }
        augment_concept_candidates = [
            {"id": package, "kind": "augment", "packagePath": package}
            for package in augment_concept_packages
        ]
        augment_concept_assets = [
            collection_wrapper_by_package[package]
            for package in augment_concept_packages
            if package in collection_wrapper_by_package
        ]
        if len(augment_concept_assets) != len(augment_concept_candidates):
            raise CatalogueError("resolved Collection augment concept omitted its definition asset")

        preliminary = normalize_semantic_document(
            candidates=[item for item in candidate_records if isinstance(item, dict)],
            candidate_assets=first_assets if isinstance(first_assets, list) else [],
            candidate_failures=first_failures,
            effect_assets=[],
            dependency_failures=[],
            icon_metadata=[],
            icon_bytes={},
            source_fingerprint=source_fingerprint,
            parent_assets=parent_assets,
            resolve_weapon_compatibility=True,
        ).document
        kit_membership, kit_membership_failures = _extract_kit_membership_index(
            kit_records=[
                item
                for item in preliminary["records"]
                if isinstance(item, Mapping) and item.get("kind") == "kit"
            ],
            members=members,
            registry_package_paths=_select_kit_reward_registry_packages(
                package_index
            ),
            paks_dir=paks_dir,
            retoc=retoc,
            archive_key=archive_key,
            reader=reader,
            loose_root=loose,
            work=work,
            secret_environment_names=secret_environment_names,
            jobs=jobs,
        )
        collection_document["kitMembership"] = kit_membership
        collection_document["coverage"]["kitMembership"] = len(
            kit_membership["memberIds"]
        )
        collection_document["coverage"]["kitMembershipUnresolvedReferences"] = (
            kit_membership["coverage"]["unresolvedReferences"]
        )
        preliminary_augment_concepts = [
            _candidate_semantics(candidate, collection_wrapper_by_package[candidate["id"]])
            for candidate in augment_concept_candidates
        ]
        effect_packages = sorted(
            {
                effect["effectPackagePath"]
                for record in preliminary["records"]
                for effect in record.get("effects", [])
                if isinstance(effect, dict) and isinstance(effect.get("effectPackagePath"), str)
            }
        )
        class_packages = sorted(
            {
                record["characterClassPackagePath"]
                for record in preliminary["records"]
                if record.get("kind") == "kit"
                and isinstance(record.get("characterClassPackagePath"), str)
            }
        )
        icon_packages = sorted(
            {
                record[field]["packagePath"]
                for record in [*preliminary["records"], *preliminary_augment_concepts]
                for field in ("icon", "silhouetteIcon")
                if isinstance(record.get(field), dict)
                and isinstance(record[field].get("packagePath"), str)
            }
        )

        dependency_failures: list[dict[str, str]] = [
            *parent_failures,
            *collection_failures,
            *progression_failures,
            *kit_membership_failures,
        ]
        effect_requests: list[dict[str, str]] = []
        class_requests: list[dict[str, str]] = []
        item_slot_requests: list[dict[str, str]] = []
        icon_requests: list[dict[str, str]] = []
        dependency_members: set[str] = set()
        for package in effect_packages:
            member = members.get(package)
            if member:
                effect_requests.append({"memberPath": member, "packagePath": package})
                dependency_members.add(member)
            else:
                dependency_failures.append(
                    {
                        "packagePath": package,
                        "reason": "effect-package-had-no-uasset-member",
                        "stage": "dependency-index",
                    }
                )
        for package in class_packages:
            member = members.get(package)
            if member:
                class_requests.append({"memberPath": member, "packagePath": package})
                dependency_members.add(member)
            else:
                dependency_failures.append(
                    {
                        "packagePath": package,
                        "reason": "character-class-package-had-no-uasset-member",
                        "stage": "class-index",
                    }
                )
        item_slot_member = members.get(_DEFAULT_PLAYER_CHARACTER)
        if item_slot_member:
            if _DEFAULT_PLAYER_CHARACTER not in class_packages:
                item_slot_requests.append(
                    {
                        "memberPath": item_slot_member,
                        "packagePath": _DEFAULT_PLAYER_CHARACTER,
                    }
                )
            dependency_members.add(item_slot_member)
        else:
            dependency_failures.append(
                {
                    "packagePath": _DEFAULT_PLAYER_CHARACTER,
                    "reason": "default-player-character-had-no-uasset-member",
                    "stage": "item-slot-index",
                }
            )
        for package in icon_packages:
            member = members.get(package)
            if member:
                icon_requests.append(
                    {
                        "memberPath": member,
                        "outputName": _icon_output_name(package),
                        "packagePath": package,
                    }
                )
                dependency_members.add(member)
            else:
                dependency_failures.append(
                    {
                        "packagePath": package,
                        "reason": "icon-package-had-no-uasset-member",
                        "stage": "dependency-index",
                    }
                )

        _extract_members(
            paks_dir=paks_dir,
            retoc=retoc,
            key=archive_key,
            loose_root=loose,
            members=dependency_members,
        )
        second, icons_root = _run_reader(
            reader,
            request={
                "assets": [*effect_requests, *class_requests, *item_slot_requests],
                "icons": icon_requests,
                "schemaVersion": 1,
            },
            loose_root=loose,
            work=work,
            label="dependencies",
            secret_environment_names=secret_environment_names,
            jobs=jobs,
        )
        dependency_failures.extend(
            item for item in second.get("failures", []) if isinstance(item, dict)
        )
        icon_payloads: dict[str, bytes] = {}
        for metadata in second.get("icons", []):
            if not isinstance(metadata, dict) or not isinstance(metadata.get("outputName"), str):
                continue
            name = metadata["outputName"]
            path = icons_root / name
            if path.is_file() and not path.is_symlink():
                icon_payloads[name] = path.read_bytes()

        class_assets = [
            item
            for item in second.get("assets", [])
            if isinstance(item, dict) and item.get("packagePath") in class_packages
        ]
        class_icon_requests: list[dict[str, str]] = []
        for package in _character_class_display_icon_packages(class_assets):
            if package in icon_packages:
                continue
            member = members.get(package)
            if member:
                class_icon_requests.append(
                    {
                        "memberPath": member,
                        "outputName": _icon_output_name(package),
                        "packagePath": package,
                    }
                )
            else:
                dependency_failures.append(
                    {
                        "packagePath": package,
                        "reason": "class-display-icon-had-no-uasset-member",
                        "stage": "class-icon-index",
                    }
                )

        class_icon_result: dict[str, Any] = {"failures": [], "icons": []}
        if class_icon_requests:
            _extract_members(
                paks_dir=paks_dir,
                retoc=retoc,
                key=archive_key,
                loose_root=loose,
                members=(item["memberPath"] for item in class_icon_requests),
            )
            class_icon_result, class_icons_root = _run_reader(
                reader,
                request={
                    "assets": [],
                    "icons": class_icon_requests,
                    "schemaVersion": 1,
                },
                loose_root=loose,
                work=work,
                label="class-display-icons",
                secret_environment_names=secret_environment_names,
                jobs=jobs,
            )
            dependency_failures.extend(
                item
                for item in class_icon_result.get("failures", [])
                if isinstance(item, dict)
            )
            for metadata in class_icon_result.get("icons", []):
                if not isinstance(metadata, dict) or not isinstance(
                    metadata.get("outputName"), str
                ):
                    continue
                name = metadata["outputName"]
                path = class_icons_root / name
                if path.is_file() and not path.is_symlink():
                    icon_payloads[name] = path.read_bytes()
        semantic_icon_metadata = [
            item
            for item in [*second.get("icons", []), *class_icon_result.get("icons", [])]
            if isinstance(item, dict)
        ]

        grid_widget_packages = select_grid_widget_packages(members)
        if not grid_widget_packages:
            raise CatalogueError("the archive contained no PerkGrid UI widget packages")
        grid_widget_requests = [
            {
                "includeScriptBytecode": True,
                "memberPath": member,
                "packagePath": package,
            }
            for package, member in sorted(grid_widget_packages.items())
        ]
        _extract_members(
            paks_dir=paks_dir,
            retoc=retoc,
            key=archive_key,
            loose_root=loose,
            members=grid_widget_packages.values(),
        )
        grid_widgets, _ = _run_reader(
            reader,
            request={"assets": grid_widget_requests, "icons": [], "schemaVersion": 1},
            loose_root=loose,
            work=work,
            label="grid-widgets",
            secret_environment_names=secret_environment_names,
            jobs=jobs,
        )
        grid_widget_assets = [
            item for item in grid_widgets.get("assets", []) if isinstance(item, dict)
        ]
        grid_failures: list[dict[str, Any]] = [
            item for item in grid_widgets.get("failures", []) if isinstance(item, dict)
        ]
        grid_texture_packages = select_grid_texture_packages(
            members,
            widget_assets=grid_widget_assets,
        )
        grid_texture_requests = [
            {
                "memberPath": member,
                "outputName": _icon_output_name(package),
                "packagePath": package,
            }
            for package, member in sorted(grid_texture_packages.items())
        ]
        _extract_members(
            paks_dir=paks_dir,
            retoc=retoc,
            key=archive_key,
            loose_root=loose,
            members=grid_texture_packages.values(),
        )
        grid_textures, grid_texture_root = _run_reader(
            reader,
            request={"assets": [], "icons": grid_texture_requests, "schemaVersion": 1},
            loose_root=loose,
            work=work,
            label="grid-textures",
            secret_environment_names=secret_environment_names,
            jobs=jobs,
        )
        grid_failures.extend(
            item for item in grid_textures.get("failures", []) if isinstance(item, dict)
        )
        grid_texture_payloads: dict[str, bytes] = {}
        for metadata in grid_textures.get("icons", []):
            if not isinstance(metadata, dict) or not isinstance(metadata.get("outputName"), str):
                continue
            name = metadata["outputName"]
            path = grid_texture_root / name
            if path.is_file() and not path.is_symlink():
                grid_texture_payloads[name] = path.read_bytes()

        normalized = normalize_semantic_document(
            candidates=[item for item in candidate_records if isinstance(item, dict)],
            candidate_assets=first_assets if isinstance(first_assets, list) else [],
            candidate_failures=first_failures,
            effect_assets=[
                item
                for item in second.get("assets", [])
                if isinstance(item, dict) and item.get("packagePath") in effect_packages
            ],
            dependency_failures=dependency_failures,
            icon_metadata=semantic_icon_metadata,
            icon_bytes=icon_payloads,
            source_fingerprint=source_fingerprint,
            class_assets=class_assets,
            item_slot_assets=[
                item
                for item in second.get("assets", [])
                if isinstance(item, dict)
                and item.get("packagePath") == _DEFAULT_PLAYER_CHARACTER
            ],
            parent_assets=parent_assets,
            resolve_weapon_compatibility=True,
        )
        normalized_augment_concepts = normalize_semantic_document(
            candidates=augment_concept_candidates,
            candidate_assets=augment_concept_assets,
            candidate_failures=[],
            effect_assets=[],
            dependency_failures=[],
            icon_metadata=semantic_icon_metadata,
            icon_bytes=icon_payloads,
            source_fingerprint=source_fingerprint,
        )
        collection_document["conceptRecords"] = normalized_augment_concepts.document["records"]
        collection_document["coverage"]["conceptRecords"] = len(
            normalized_augment_concepts.document["records"]
        )
        grid = build_grid_assets(
            package_members=members,
            widget_assets=grid_widget_assets,
            failures=grid_failures,
            texture_metadata=[
                item for item in grid_textures.get("icons", []) if isinstance(item, dict)
            ],
            texture_bytes=grid_texture_payloads,
            source_fingerprint=source_fingerprint,
        )
        semantic_binaries = {
            **normalized.binary_files,
            **normalized_augment_concepts.binary_files,
        }
        overlap = set(semantic_binaries) & set(grid.binary_files)
        if overlap:
            raise CatalogueError("semantic and grid asset output paths collided")
        return SemanticBuild(
            document=normalized.document,
            binary_files=dict(sorted({**semantic_binaries, **grid.binary_files}.items())),
            collection_document=collection_document,
            grid_document=grid.document,
        )


__all__ = [
    "MAX_SEMANTIC_READER_JOBS",
    "SemanticBuild",
    "apply_semantic_evidence",
    "build_semantic_assets",
    "normalize_semantic_document",
]
