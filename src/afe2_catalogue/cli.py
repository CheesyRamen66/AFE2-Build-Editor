"""Command-line orchestration for the read-only AFE2 catalogue pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

from .archives import (
    parse_retoc_manifest,
    scan_iostore,
    scan_paks,
    validate_repak_key,
    validate_retoc_key,
)
from .classify import classify_packages
from .diffing import diff_catalogues, diff_record_lists
from .discovery import DiscoveryError, SourceInventory, discover_source_inventory
from .errors import CatalogueError
from .jsonio import digest_file, digest_value, publish_documents, read_json, write_json_atomic
from .managed_tools import ManagedTool, ensure_managed_tools
from .overrides import apply_overrides
from .planner_catalogue import build_planner_catalogue
from .save_evidence import build_save_evidence, load_character_save
from .semantic_assets import apply_semantic_evidence, build_semantic_assets
from .semantic_reader import ManagedSemanticReader, ensure_semantic_reader
from .secrets import resolve_key
from .validate import validate_outputs
from .version import __version__

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RULES = PROJECT_ROOT / "config/categories.json"
DEFAULT_OVERRIDES = PROJECT_ROOT / "overrides/catalogue.json"
DEFAULT_OUTPUT = PROJECT_ROOT / ".local/catalogue"
DEFAULT_SAVE_EVIDENCE = PROJECT_ROOT / ".local/save-evidence.json"
SEMANTIC_PYTHON_SOURCES = (
    PROJECT_ROOT / "src/afe2_catalogue/collection.py",
    PROJECT_ROOT / "src/afe2_catalogue/grid_assets.py",
    PROJECT_ROOT / "src/afe2_catalogue/planner_catalogue.py",
    PROJECT_ROOT / "src/afe2_catalogue/semantic_assets.py",
    PROJECT_ROOT / "src/afe2_catalogue/semantic_reader.py",
    PROJECT_ROOT / "src/afe2_catalogue/weapon_compatibility.py",
)


def _path(value: str) -> Path:
    return Path(value).expanduser()


def _existing_catalogue(path: Path) -> dict[str, Any]:
    candidate = path / "catalogue.json" if path.is_dir() else path
    value = read_json(candidate)
    if not isinstance(value, dict):
        raise CatalogueError(f"catalogue root must be an object: {candidate}")
    return value


def _optional_sibling_document(path: Path, filename: str) -> dict[str, Any] | None:
    root = path if path.is_dir() else path.parent
    candidate = root / filename
    if not candidate.is_file():
        return None
    value = read_json(candidate)
    if not isinstance(value, dict):
        raise CatalogueError(f"generated document root must be an object: {candidate}")
    return value


def _largest_archive(inventory: SourceInventory, archive_type: str) -> Path:
    matches = [item for item in inventory.archives if item.archive_type == archive_type]
    if not matches:
        raise CatalogueError(f"the game install has no .{archive_type} archive")
    selected = max(matches, key=lambda item: (item.size_bytes, item.relative_path))
    return inventory.installation.paks_dir / selected.relative_path


def _resolve_archive_key(
    args: argparse.Namespace,
    inventory: SourceInventory,
    retoc: Path | None,
    repak: Path | None,
) -> tuple[str, str]:
    if retoc:
        archive = _largest_archive(inventory, "utoc")
        validator = lambda candidate: validate_retoc_key(retoc, archive, candidate)
    elif repak:
        archive = _largest_archive(inventory, "pak")
        validator = lambda candidate: validate_repak_key(repak, archive, candidate)
    else:
        raise CatalogueError("no archive tool is available to validate an AES key")
    return resolve_key(
        executable=inventory.installation.shipping_executable,
        validator=validator,
        environment_name=args.aes_key_env,
        key_file=args.key_file,
        allow_executable_scan=not args.no_executable_key_scan,
    )


def _source_archives(
    inventory: SourceInventory,
    *,
    iostore_status: str,
    pak_result: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    failed_paks = {
        failure["archive"]
        for failure in (pak_result or {}).get("failures", [])
        if isinstance(failure, dict) and isinstance(failure.get("archive"), str)
    }
    values: list[dict[str, Any]] = []
    for archive in inventory.archives:
        game_relative = f"AFE2/Content/Paks/{archive.relative_path}"
        if archive.archive_type == "utoc":
            status = iostore_status
        elif archive.archive_type == "ucas":
            status = "paired-data"
        elif pak_result is None:
            status = "unscanned"
        elif game_relative in failed_paks:
            status = "failed"
        else:
            status = "scanned"
        values.append(
            {
                "archiveType": archive.archive_type,
                "container": f"AFE2/Content/Paks/{archive.container_name}",
                "relativePath": game_relative,
                "scanStatus": status,
                "sizeBytes": archive.size_bytes,
            }
        )
    return sorted(values, key=lambda item: item["relativePath"])


def _manifest_input(path: Path) -> dict[str, Any]:
    value = read_json(path)
    if not isinstance(value, dict):
        raise CatalogueError("retoc manifest input must be a JSON object")
    packages, warnings = parse_retoc_manifest(value)
    return {
        "adapter": {"name": "retoc-manifest-input", "version": "unknown"},
        "packages": packages,
        "warnings": warnings,
    }


def _record_tool_provenance(document: dict[str, Any], tool: ManagedTool) -> None:
    adapter = document.get("adapter")
    if not isinstance(adapter, dict):
        raise CatalogueError(f"{tool.spec.name} adapter metadata was malformed")
    adapter.update(tool.adapter_provenance())


def _managed_tools_for_extract(args: argparse.Namespace) -> dict[str, ManagedTool]:
    names: list[str] = []
    if not args.manifest or not args.no_semantic_assets:
        names.append("retoc")
    if not args.no_pak_index:
        names.append("repak")
    return ensure_managed_tools(
        PROJECT_ROOT,
        names,
        progress=print,
        secret_environment_names=(args.aes_key_env,),
    )


def _semantic_provenance(reader: ManagedSemanticReader) -> dict[str, Any]:
    provenance = reader.adapter_provenance()
    provenance["orchestrationSourceDigest"] = digest_value(
        {path.name: digest_file(path) for path in SEMANTIC_PYTHON_SOURCES}
    )
    return provenance


def _make_documents(
    args: argparse.Namespace,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, bytes]]:
    try:
        inventory = discover_source_inventory(args.game_dir)
    except DiscoveryError as exc:
        raise CatalogueError(str(exc)) from exc

    output = args.output.resolve()
    game_root = inventory.installation.root.resolve()
    if output == game_root or output.is_relative_to(game_root) or game_root.is_relative_to(output):
        raise CatalogueError("output must not be inside, equal to, or contain the game installation")
    if PROJECT_ROOT.resolve().is_relative_to(output):
        raise CatalogueError("output must not be the repository root or one of its parent directories")
    if args.archive_dir:
        archive_root = args.archive_dir.resolve()
        if (
            archive_root == game_root
            or archive_root.is_relative_to(game_root)
            or game_root.is_relative_to(archive_root)
        ):
            raise CatalogueError("archive directory must be disjoint from the game installation")

    if args.manifest:
        iostore = _manifest_input(args.manifest)
    else:
        iostore = None

    managed = _managed_tools_for_extract(args)
    retoc_tool = managed.get("retoc")
    repak_tool = managed.get("repak")
    retoc = retoc_tool.binary if retoc_tool else None
    repak = repak_tool.binary if repak_tool else None
    semantic_reader = None
    semantic_provenance: dict[str, Any] | None = None
    if not args.no_semantic_assets:
        semantic_reader = ensure_semantic_reader(
            PROJECT_ROOT,
            progress=print,
            secret_environment_names=(args.aes_key_env,),
        )
        semantic_provenance = _semantic_provenance(semantic_reader)
        if retoc_tool is None:
            raise CatalogueError("managed retoc metadata was unavailable for semantic extraction")
        semantic_provenance["archiveConverter"] = {
            "name": retoc_tool.spec.name,
            "version": retoc_tool.spec.version,
            **retoc_tool.adapter_provenance(),
        }
    archive_key: str | None = None
    if iostore is None:
        if retoc is None or retoc_tool is None:  # Defensive: selection above always requests it.
            raise CatalogueError("managed retoc was not prepared")
        archive_key, _ = _resolve_archive_key(args, inventory, retoc, repak)
        iostore = scan_iostore(inventory.installation.paks_dir, retoc, archive_key)
        _record_tool_provenance(iostore, retoc_tool)

    pak_result: dict[str, Any] | None = None
    pak_paths = [
        inventory.installation.paks_dir / archive.relative_path
        for archive in inventory.archives
        if archive.archive_type == "pak"
    ]
    if repak and pak_paths:
        if archive_key is None:
            archive_key, _ = _resolve_archive_key(args, inventory, retoc, repak)
        pak_result = scan_paks(pak_paths, repak, archive_key, inventory.installation.root)
        if repak_tool is None:  # Defensive: a repak path always comes from a managed tool.
            raise CatalogueError("managed repak metadata was not available")
        _record_tool_provenance(pak_result, repak_tool)

    archives = _source_archives(
        inventory,
        iostore_status="unverified" if args.manifest else "scanned",
        pak_result=pak_result,
    )
    installation = inventory.installation
    game = {
        "buildId": installation.build_id,
        "steamAppId": "3448650",
    }
    package_index: dict[str, Any] = {
        "schemaVersion": 1,
        "packages": iostore["packages"],
        "pakMembers": (pak_result or {}).get("members", []),
    }
    fingerprint_seed = {
        "archives": [
            {key: value for key, value in archive.items() if key != "scanStatus"}
            for archive in archives
        ],
        "game": game,
        "packages": package_index["packages"],
        "pakMembers": package_index["pakMembers"],
        "overridesDigest": digest_file(args.overrides),
        "rulesDigest": digest_file(args.rules),
        "semanticAssets": semantic_provenance or {"enabled": False},
    }
    source_fingerprint = digest_value(fingerprint_seed)
    package_index["sourceFingerprint"] = source_fingerprint

    adapters: list[dict[str, Any]] = [iostore["adapter"]]
    if pak_result:
        adapters.append(pak_result["adapter"])
    if semantic_provenance:
        adapters.append(semantic_provenance)
    adapter_warnings = [
        {"adapter": "retoc", "message": message} for message in iostore.get("warnings", [])
    ]
    source_manifest: dict[str, Any] = {
        "schemaVersion": 1,
        "adapters": sorted(adapters, key=lambda item: item["name"]),
        "adapterWarnings": adapter_warnings,
        "archives": archives,
        "coverage": {
            "iostorePackages": len(package_index["packages"]),
            "pakMembers": len(package_index["pakMembers"]),
        },
        "extractor": {"name": "afe2-catalogue", "version": __version__},
        "game": game,
        "overridesDigest": fingerprint_seed["overridesDigest"],
        "rulesDigest": fingerprint_seed["rulesDigest"],
        "sourceFingerprint": source_fingerprint,
    }

    candidates = classify_packages(package_index, args.rules)
    candidates["sourceFingerprint"] = source_fingerprint
    catalogue, activity = apply_overrides(
        candidates,
        args.overrides,
        build_id=installation.build_id,
    )
    catalogue["sourceFingerprint"] = source_fingerprint

    binary_files: dict[str, bytes] = {}
    semantic_document: dict[str, Any] | None = None
    collection_document: dict[str, Any] | None = None
    grid_document: dict[str, Any] | None = None
    planner_document: dict[str, Any] | None = None
    if semantic_reader is not None:
        if retoc is None:
            raise CatalogueError("managed retoc was not prepared for semantic extraction")
        if archive_key is None:
            archive_key, _ = _resolve_archive_key(args, inventory, retoc, repak)
        print(f"Extracting serialized properties and icon dependencies for {len(candidates['records'])} candidates")
        semantic_build = build_semantic_assets(
            paks_dir=inventory.installation.paks_dir,
            retoc=retoc,
            archive_key=archive_key,
            reader=semantic_reader,
            package_index=package_index,
            candidates=candidates,
            source_fingerprint=source_fingerprint,
            secret_environment_names=(args.aes_key_env,),
        )
        semantic_document = semantic_build.document
        collection_document = semantic_build.collection_document
        grid_document = semantic_build.grid_document
        if collection_document is None:
            raise CatalogueError("semantic extraction omitted the canonical Collection index")
        if grid_document is None:
            raise CatalogueError("semantic extraction omitted the PerkGrid UI asset bundle")
        binary_files = semantic_build.binary_files
        apply_semantic_evidence(
            candidates=candidates,
            catalogue=catalogue,
            semantic=semantic_document,
        )
        planner_document = build_planner_catalogue(
            semantic=semantic_document,
            collection=collection_document,
            grid_assets=grid_document,
            game=source_manifest["game"],
            extractor=source_manifest["extractor"],
            source_fingerprint=source_fingerprint,
        )
        source_manifest["coverage"]["semanticAssets"] = semantic_document["coverage"]
        source_manifest["coverage"]["collectionAssets"] = collection_document["coverage"]
        source_manifest["coverage"]["gridAssets"] = grid_document["coverage"]
        source_manifest["coverage"]["plannerCatalogue"] = planner_document["coverage"]

    baseline: dict[str, Any] | None = None
    baseline_documents_path: Path | None = None
    baseline_path = args.baseline
    if baseline_path:
        baseline = _existing_catalogue(baseline_path)
        baseline_documents_path = baseline_path
    elif (args.output / "catalogue.json").is_file():
        baseline = _existing_catalogue(args.output / "catalogue.json")
        baseline_documents_path = args.output
    changes = diff_catalogues(baseline, catalogue)
    old_candidates = (
        _optional_sibling_document(baseline_documents_path, "candidate-records.json")
        if baseline_documents_path
        else None
    )
    old_activity = (
        _optional_sibling_document(baseline_documents_path, "override-activity.json")
        if baseline_documents_path
        else None
    )
    candidate_baseline_available = baseline_documents_path is None or old_candidates is not None
    changes["candidateBaselineAvailable"] = candidate_baseline_available
    changes["candidateChanges"] = (
        diff_record_lists(
            old_candidates.get("records", []) if old_candidates else None,
            candidates["records"],
        )
        if candidate_baseline_available
        else {"added": [], "changed": [], "removed": []}
    )
    current_unresolved = set(record["id"] for record in candidates["records"]) - set(
        activity["promotedCandidateIds"]
    ) - set(activity["suppressedCandidateIds"])
    if old_candidates is not None:
        old_candidate_ids = {record["id"] for record in old_candidates.get("records", [])}
        old_promoted = set((old_activity or {}).get("promotedCandidateIds", []))
        old_suppressed = set((old_activity or {}).get("suppressedCandidateIds", []))
        old_unresolved = old_candidate_ids - old_promoted - old_suppressed
    else:
        old_unresolved = set()
    changes["unresolvedCandidateChanges"] = {
        "added": sorted(current_unresolved - old_unresolved) if candidate_baseline_available else [],
        "removed": sorted(old_unresolved - current_unresolved) if candidate_baseline_available else [],
    }
    changes["fromSourceFingerprint"] = baseline.get("sourceFingerprint") if baseline else None
    changes["toSourceFingerprint"] = source_fingerprint

    validation = validate_outputs(
        source_manifest=source_manifest,
        package_index=package_index,
        candidates=candidates,
        catalogue=catalogue,
        override_activity=activity,
        collection_assets=collection_document,
        grid_assets=grid_document,
        planner_catalogue=planner_document,
        strict=args.strict,
    )
    documents = {
        "candidate-records.json": candidates,
        "catalogue.json": catalogue,
        "changes.json": changes,
        "override-activity.json": activity,
        "package-index.json": package_index,
        "source-manifest.json": source_manifest,
        "validation.json": validation,
    }
    if semantic_document is not None:
        documents["semantic-assets.json"] = semantic_document
    if collection_document is not None:
        documents["collection-assets.json"] = collection_document
    if grid_document is not None:
        documents["grid-assets.json"] = grid_document
    if planner_document is not None:
        documents["planner-catalogue.json"] = planner_document
    return documents, validation, binary_files


def command_extract(args: argparse.Namespace) -> int:
    documents, validation, binary_files = _make_documents(args)
    if not validation["valid"]:
        raise CatalogueError(
            f"generated data failed validation with {len(validation['errors'])} error(s); output was not replaced"
        )
    archive_root = None
    if not args.no_archive:
        archive_root = args.archive_dir or (
            args.output.parent / f"{args.output.name}-archive"
        )
    archived = publish_documents(
        args.output,
        documents,
        archive_root=archive_root,
        binary_files=binary_files,
    )
    summary = validation["summary"]
    counts = ", ".join(f"{kind}={count}" for kind, count in summary["candidateCounts"].items())
    print(f"Wrote catalogue extraction to {args.output.resolve()}")
    if archived is not None:
        print(f"Preserved the previous publication at {archived}")
    print(f"Indexed {summary['packages']} IoStore packages; candidates: {counts}")
    print(
        f"Promoted {summary['catalogueRecords']} override-backed record(s); "
        f"{summary['unresolvedCandidates']} candidate(s) remain unresolved"
    )
    semantic = documents.get("semantic-assets.json")
    if isinstance(semantic, dict):
        coverage = semantic["coverage"]
        print(
            f"Parsed {coverage['candidateAssetsParsed']} semantic asset(s), "
            f"decoded {coverage['iconsDecoded']} icon(s), and proved "
            f"{coverage['mechanicalStats']} mechanical stat operation(s)"
        )
    grid_assets = documents.get("grid-assets.json")
    if isinstance(grid_assets, dict):
        coverage = grid_assets["coverage"]
        print(
            f"Compiled {coverage['widgetsParsed']} PerkGrid widget/helper definition(s) "
            f"and {coverage['texturesDecoded']} source texture(s)"
        )
    planner = documents.get("planner-catalogue.json")
    if isinstance(planner, dict):
        counts = ", ".join(
            f"{kind}={count}"
            for kind, count in planner["coverage"]["recordsByKind"].items()
        )
        print(f"Built Collection-filtered planner catalogue: {counts}")
    skipped = [
        archive for archive in documents["source-manifest.json"]["archives"]
        if archive["scanStatus"] in {"unscanned", "unverified", "failed"}
    ]
    if skipped:
        print(f"Coverage warning: {len(skipped)} archive index(es) were not scanned")
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    try:
        inventory = discover_source_inventory(args.game_dir)
    except DiscoveryError as exc:
        raise CatalogueError(str(exc)) from exc
    managed = ensure_managed_tools(
        PROJECT_ROOT,
        progress=print,
        secret_environment_names=(args.aes_key_env,),
    )
    retoc_tool = managed["retoc"]
    repak_tool = managed["repak"]
    retoc = retoc_tool.binary
    repak = repak_tool.binary
    semantic_reader = ensure_semantic_reader(
        PROJECT_ROOT,
        progress=print,
        secret_environment_names=(args.aes_key_env,),
    )
    print(f"Game: {inventory.installation.root}")
    print(f"Steam build: {inventory.installation.build_id or 'unknown'}")
    counts = Counter(item.archive_type for item in inventory.archives)
    print("Archives: " + ", ".join(f".{kind}={counts[kind]}" for kind in sorted(counts)))
    print(
        f"retoc: {retoc_tool.spec.version} at {retoc} "
        f"({retoc_tool.spec.tag}@{retoc_tool.spec.revision[:12]})"
    )
    print(
        f"semantic reader: {semantic_reader.adapter_provenance()['version']} "
        f"at {semantic_reader.dll} ({semantic_reader.adapter_provenance()['targetFramework']})"
    )
    print(
        f"repak: {repak_tool.spec.version} at {repak} "
        f"({repak_tool.spec.tag}@{repak_tool.spec.revision[:12]})"
    )
    _, source = _resolve_archive_key(args, inventory, retoc, repak)
    print(f"AES key: validated from {source}; value not persisted")
    return 0


def command_bootstrap_tools(_args: argparse.Namespace) -> int:
    managed = ensure_managed_tools(PROJECT_ROOT, progress=print)
    for name in ("retoc", "repak"):
        tool = managed[name]
        print(
            f"{name}: {tool.spec.version} at {tool.binary} "
            f"({tool.spec.tag}@{tool.spec.revision[:12]})"
        )
    reader = ensure_semantic_reader(PROJECT_ROOT, progress=print)
    print(
        f"semantic reader: {reader.adapter_provenance()['version']} at {reader.dll} "
        f"({reader.adapter_provenance()['targetFramework']})"
    )
    return 0


def command_validate(args: argparse.Namespace) -> int:
    root = args.input if args.input.is_dir() else args.input.parent
    required = {
        name: read_json(root / name)
        for name in (
            "source-manifest.json",
            "package-index.json",
            "candidate-records.json",
            "catalogue.json",
            "override-activity.json",
        )
    }
    result = validate_outputs(
        source_manifest=required["source-manifest.json"],
        package_index=required["package-index.json"],
        candidates=required["candidate-records.json"],
        catalogue=required["catalogue.json"],
        override_activity=required["override-activity.json"],
        collection_assets=_optional_sibling_document(root, "collection-assets.json"),
        grid_assets=_optional_sibling_document(root, "grid-assets.json"),
        planner_catalogue=_optional_sibling_document(root, "planner-catalogue.json"),
        strict=args.strict,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["valid"] else 1


def command_diff(args: argparse.Namespace) -> int:
    result = diff_catalogues(_existing_catalogue(args.old), _existing_catalogue(args.new))
    if args.output:
        write_json_atomic(args.output, result)
        print(f"Wrote diff to {args.output.resolve()}")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def command_inspect_save(args: argparse.Namespace) -> int:
    catalogue_root = args.catalogue_dir.resolve()
    if not catalogue_root.is_dir():
        raise CatalogueError(f"catalogue directory does not exist: {catalogue_root}")
    output = args.output.resolve()
    if output == args.save.resolve():
        raise CatalogueError("save evidence output must not replace the source save")
    if output == catalogue_root or output.is_relative_to(catalogue_root):
        raise CatalogueError("save evidence output must be outside the generated catalogue directory")
    package_index = read_json(catalogue_root / "package-index.json")
    candidates = read_json(catalogue_root / "candidate-records.json")
    catalogue = read_json(catalogue_root / "catalogue.json")
    if not all(isinstance(value, dict) for value in (package_index, candidates, catalogue)):
        raise CatalogueError("catalogue evidence inputs must be JSON objects")

    save, normalization = load_character_save(args.save)
    evidence = build_save_evidence(
        save,
        normalization=normalization,
        package_index=package_index,
        candidates=candidates,
        catalogue=catalogue,
    )
    write_json_atomic(output, evidence)
    summary = evidence["summary"]
    print(f"Wrote partial save evidence to {output}")
    print(
        f"Observed {summary['assets']} assets in {summary['assetOccurrences']} reference(s); "
        f"indexed={summary['indexedAssets']}, candidates={summary['candidateAssets']}, "
        f"catalogue={summary['catalogueAssets']}, aliases={summary['catalogueAliasedAssets']}"
    )
    if summary["missingPackageAssets"]:
        print(
            f"Coverage warning: {summary['missingPackageAssets']} save asset(s) "
            "were absent from the package index"
        )
    return 0


def _add_install_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--game-dir", type=_path, help="game installation root; otherwise auto-detect Steam")
    parser.add_argument(
        "--aes-key-env",
        default="AFE2_AES_KEY",
        metavar="NAME",
        help="environment variable containing the key (default: AFE2_AES_KEY)",
    )
    parser.add_argument("--key-file", type=_path, help="mode-0600 file containing the key")
    parser.add_argument(
        "--no-executable-key-scan",
        action="store_true",
        help="do not search the owned shipping executable for key candidates",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build_catalogue.py",
        description="Build a deterministic, evidence-labelled AFE2 catalogue seed from an installed game.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap = subparsers.add_parser(
        "bootstrap-tools",
        help="prepare pinned retoc, repak, and semantic reader builds under .tools",
    )
    bootstrap.set_defaults(handler=command_bootstrap_tools)

    doctor = subparsers.add_parser("doctor", help="check install, tools, and archive-key access")
    _add_install_arguments(doctor)
    doctor.set_defaults(handler=command_doctor)

    extract = subparsers.add_parser("extract", help="index archives and build candidate catalogue JSON")
    _add_install_arguments(extract)
    extract.add_argument("--manifest", type=_path, help="use an existing retoc pakstore.json")
    extract.add_argument(
        "--no-pak-index",
        action="store_true",
        help="skip the managed repak tool and leave PAK archives unindexed",
    )
    extract.add_argument(
        "--no-semantic-assets",
        action="store_true",
        help="skip Unreal property parsing and PNG icon extraction",
    )
    extract.add_argument("--rules", type=_path, default=DEFAULT_RULES)
    extract.add_argument("--overrides", type=_path, default=DEFAULT_OVERRIDES)
    extract.add_argument("--baseline", type=_path, help="old catalogue or generated output directory")
    extract.add_argument("--output", type=_path, default=DEFAULT_OUTPUT)
    archive_options = extract.add_mutually_exclusive_group()
    archive_options.add_argument(
        "--archive-dir",
        type=_path,
        help=(
            "directory for prior complete publications; defaults to a sibling "
            "named <output>-archive"
        ),
    )
    archive_options.add_argument(
        "--no-archive",
        action="store_true",
        help="replace the previous publication without retaining it after a successful run",
    )
    extract.add_argument("--strict", action="store_true", help="treat coverage and unresolved warnings as errors")
    extract.set_defaults(handler=command_extract)

    validate = subparsers.add_parser("validate", help="revalidate a generated output directory")
    validate.add_argument("input", type=_path)
    validate.add_argument("--strict", action="store_true")
    validate.set_defaults(handler=command_validate)

    diff = subparsers.add_parser("diff", help="compare two catalogue JSON files or output directories")
    diff.add_argument("old", type=_path)
    diff.add_argument("new", type=_path)
    diff.add_argument("--output", type=_path, help="JSON file to write; otherwise print the diff")
    diff.set_defaults(handler=command_diff)

    inspect_save = subparsers.add_parser(
        "inspect-save",
        help="record positive per-asset evidence from a partial decoded character save",
    )
    inspect_save.add_argument("save", type=_path, help="readable AFE2 char.dec file")
    inspect_save.add_argument(
        "--catalogue-dir",
        type=_path,
        default=DEFAULT_OUTPUT,
        help="generated catalogue directory used to join package and candidate IDs",
    )
    inspect_save.add_argument("--output", type=_path, default=DEFAULT_SAVE_EVIDENCE)
    inspect_save.set_defaults(handler=command_inspect_save)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (CatalogueError, DiscoveryError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
