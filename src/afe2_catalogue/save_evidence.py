"""Read-only, privacy-filtered evidence extraction from an AFE2 character save.

Save data is deliberately kept separate from the planner catalogue. A save
can prove that an asset was observed in a particular role, but its absence can
never prove that the asset does not exist or is not player-usable.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from .diffing import document_records
from .errors import CatalogueError


_FINAL_BYTE_NORMALIZATION = "terminal-question-mark-to-closing-brace"


def normalize_object_reference(value: Any) -> str | None:
    """Return the package portion of an Unreal ``/Game`` object reference."""

    if not isinstance(value, str) or not value.startswith("/Game/"):
        return None
    value = unicodedata.normalize("NFC", value)
    dot = value.rfind(".")
    package_path = value[:dot] if dot > value.rfind("/") else value
    if package_path == "/Game/" or any(character.isspace() for character in package_path):
        return None
    return package_path


def load_character_save(path: Path) -> tuple[dict[str, Any], str]:
    """Load a decoded CharacterDoc without ever changing the source file."""

    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise CatalogueError(f"could not read AFE2 character save: {path}") from exc
    if not payload:
        raise CatalogueError("AFE2 character save is empty")

    normalization = "none"
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        if payload[-1:] != b"?":
            raise CatalogueError("AFE2 character save is not readable CharacterDoc JSON") from exc
        try:
            document = json.loads((payload[:-1] + b"}").decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as normalized_exc:
            raise CatalogueError(
                "AFE2 character save is not readable CharacterDoc JSON"
            ) from normalized_exc
        normalization = _FINAL_BYTE_NORMALIZATION
    if not isinstance(document, dict) or document.get("_Type") != "CharacterDoc":
        raise CatalogueError("AFE2 character save root must be a CharacterDoc object")
    return document, normalization


def _pointer(path: tuple[str | int, ...]) -> str:
    parts = []
    for part in path:
        if isinstance(part, int):
            parts.append("*")
        else:
            parts.append(part.replace("~", "~0").replace("/", "~1"))
    return "/" + "/".join(parts)


def _walk_asset_references(
    value: Any,
    path: tuple[str | int, ...] = (),
) -> Iterator[tuple[str, str, str]]:
    if isinstance(value, dict):
        for key in sorted(value):
            yield from _walk_asset_references(value[key], path + (key,))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_asset_references(item, path + (index,))
    elif isinstance(value, str):
        package_path = normalize_object_reference(value)
        if package_path:
            yield package_path, value, _pointer(path)


def _role_for_location(location: str) -> str | None:
    if location == "/LastClassPlayed":
        return "last-played-kit-class"
    if (
        location.startswith("/CharacterInventory/CharacterKits/*/")
        and location.endswith("/CharacterClass")
    ):
        return "character-kit-class"
    if location.endswith("/CachedListOfAttainedKitLevels/*/KitClass"):
        return "cached-kit-class"
    if "/PlacedChips/*/ModDef" in location:
        return "perk-grid-placement"
    if "/CharacterInstances/*/AssignedMods/AssignedModClasses/*" in location:
        return "character-loadout-item"
    if "/CharacterInstances/*/" in location and any(
        marker in location
        for marker in (
            "/AssignedHeadDecal",
            "/AssignedHeadGear",
            "/AssignedKitSkinItem",
            "/AssignedPatternOption",
            "/AssignedTorsoDecals/",
            "/KitSkinOverrideLegs",
            "/KitSkinOverrideTorso",
        )
    ):
        return "character-cosmetic"
    if location.startswith("/GunInventory/GunFrames/*/") and location.endswith("/GunClass"):
        return "weapon-class"
    if "/GunInstances/*/AssignedMods/AssignedModClasses/*" in location:
        return "weapon-component-assignment"
    if "/GunInstances/*/AssignedColorway" in location:
        return "gun-colorway"
    if "/GunInstances/*/AssignedDecals/*/Class" in location:
        return "gun-decal"
    if location == "/ModInventory/UnlimitedModStorage/*/ModDef":
        return "mod-inventory"
    if location == "/GeneralInventory/Items/*/Class":
        return "general-inventory"
    if location.startswith("/DLCRecords/") and location.endswith("/DroppableClass"):
        return "dlc-reward"
    if location.endswith("/MeleeFrames/*/MeleeClass"):
        return "melee-class"
    if location.endswith("/RewardPacks/*/RewardPackClass"):
        return "reward-pack"
    if location.startswith("/CharacterAppearance/"):
        return "tailor-option"
    return None


def _kind_for_role(package_path: str, role: str | None) -> tuple[str, str] | None:
    if role in {"cached-kit-class", "character-kit-class", "last-played-kit-class"}:
        return "kit", "character-class-save-field"
    if role == "weapon-class":
        return "weapon", "gun-class-save-field"
    if role == "perk-grid-placement":
        return "perk", "placed-chip-save-field"
    if role == "weapon-component-assignment":
        if "/Attachments/Overclocks/" in package_path:
            return "augment", "assigned-overclock-path"
        if "/Perks/Mastery/" in package_path:
            return "trait", "assigned-mastery-path"
        if "/Attachments/" in package_path:
            return "mod", "assigned-attachment-path"
    return None


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _sequence(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _integer(value: Any) -> int | None:
    return value if type(value) is int else None


@dataclass
class _AssetObservation:
    object_paths: Counter[str] = field(default_factory=Counter)
    locations: Counter[str] = field(default_factory=Counter)
    roles: Counter[str] = field(default_factory=Counter)
    kind_evidence: Counter[tuple[str, str]] = field(default_factory=Counter)
    placements: Counter[tuple[str, int, int, str, bool]] = field(default_factory=Counter)
    weapon_assignments: Counter[tuple[str, bool]] = field(default_factory=Counter)
    kit_weapon_assignments: Counter[tuple[str, int]] = field(default_factory=Counter)
    weapon_frame_count: int = 0
    weapon_instance_count: int = 0
    assigned_weapon_instance_count: int = 0
    mod_inventory_entries: int = 0
    owned_count: int = 0
    equippable_count: int = 0
    unlocked_true_entries: int = 0
    unlocked_false_entries: int = 0
    general_inventory_entries: int = 0
    general_inventory_count: int = 0


def _document_fingerprint(*documents: dict[str, Any]) -> str:
    fingerprints = [document.get("sourceFingerprint") for document in documents]
    if not all(isinstance(value, str) and value for value in fingerprints):
        raise CatalogueError("save-evidence inputs need source fingerprints")
    if len(set(fingerprints)) != 1:
        raise CatalogueError("save-evidence inputs have different source fingerprints")
    return fingerprints[0]


def _assigned_gun_contexts(save: dict[str, Any]) -> dict[int, Counter[tuple[str, int]]]:
    result: dict[int, Counter[tuple[str, int]]] = {}
    character_inventory = _mapping(save.get("CharacterInventory"))
    for raw_kit in _sequence(character_inventory.get("CharacterKits")):
        kit = _mapping(raw_kit)
        kit_id = normalize_object_reference(kit.get("CharacterClass"))
        if not kit_id:
            continue
        for character in _sequence(kit.get("CharacterInstances")):
            for slot_index, guid in enumerate(_sequence(_mapping(character).get("AssignedGuns"))):
                integer = _integer(guid)
                if integer is not None:
                    result.setdefault(integer, Counter())[(kit_id, slot_index)] += 1
    return result


def _guid_diagnostics(save: dict[str, Any]) -> dict[str, int]:
    gun_guids: Counter[int] = Counter()
    board_guids: Counter[int] = Counter()
    gun_references: list[int] = []
    board_references: list[int] = []

    for raw_frame in _sequence(_mapping(save.get("GunInventory")).get("GunFrames")):
        for raw_instance in _sequence(_mapping(raw_frame).get("GunInstances")):
            guid = _integer(_mapping(raw_instance).get("_Guid"))
            if guid is not None:
                gun_guids[guid] += 1

    character_inventory = _mapping(save.get("CharacterInventory"))
    for raw_kit in _sequence(character_inventory.get("CharacterKits")):
        kit = _mapping(raw_kit)
        for raw_board in _sequence(kit.get("ModChipBoardInstances")):
            guid = _integer(_mapping(raw_board).get("_Guid"))
            if guid is not None:
                board_guids[guid] += 1
        for raw_character in _sequence(kit.get("CharacterInstances")):
            character = _mapping(raw_character)
            for raw_guid in _sequence(character.get("AssignedGuns")):
                guid = _integer(raw_guid)
                if guid is not None:
                    gun_references.append(guid)
            board_guid = _integer(character.get("AssignedModChipBoard"))
            if board_guid is not None:
                board_references.append(board_guid)

    return {
        "duplicateBoardGuidCount": sum(count - 1 for count in board_guids.values() if count > 1),
        "duplicateGunGuidCount": sum(count - 1 for count in gun_guids.values() if count > 1),
        "unresolvedBoardReferenceCount": sum(board_guids[guid] != 1 for guid in board_references),
        "unresolvedGunReferenceCount": sum(gun_guids[guid] != 1 for guid in gun_references),
    }


def _record_placements(save: dict[str, Any], assets: dict[str, _AssetObservation]) -> None:
    character_inventory = _mapping(save.get("CharacterInventory"))
    for raw_kit in _sequence(character_inventory.get("CharacterKits")):
        kit = _mapping(raw_kit)
        kit_id = normalize_object_reference(kit.get("CharacterClass"))
        if not kit_id:
            continue
        assigned_board_guids = {
            guid
            for raw_character in _sequence(kit.get("CharacterInstances"))
            if (
                guid := _integer(_mapping(raw_character).get("AssignedModChipBoard"))
            ) is not None
        }
        for raw_board in _sequence(kit.get("ModChipBoardInstances")):
            board = _mapping(raw_board)
            assigned_to_loadout = _integer(board.get("_Guid")) in assigned_board_guids
            state = _mapping(board.get("CurrentState"))
            for raw_group in _sequence(state.get("ModGroups")):
                for raw_chip in _sequence(_mapping(raw_group).get("PlacedChips")):
                    chip = _mapping(raw_chip)
                    asset_id = normalize_object_reference(chip.get("ModDef"))
                    row = _integer(chip.get("Row"))
                    column = _integer(chip.get("Column"))
                    rotation = chip.get("Rotation")
                    if (
                        asset_id
                        and row is not None
                        and column is not None
                        and isinstance(rotation, str)
                    ):
                        assets.setdefault(asset_id, _AssetObservation()).placements[
                            (kit_id, row, column, rotation, assigned_to_loadout)
                        ] += 1


def _record_weapon_usage(save: dict[str, Any], assets: dict[str, _AssetObservation]) -> None:
    assigned_contexts = _assigned_gun_contexts(save)
    gun_inventory = _mapping(save.get("GunInventory"))
    for raw_frame in _sequence(gun_inventory.get("GunFrames")):
        frame = _mapping(raw_frame)
        weapon_id = normalize_object_reference(frame.get("GunClass"))
        if not weapon_id:
            continue
        observation = assets.setdefault(weapon_id, _AssetObservation())
        observation.weapon_frame_count += 1
        for raw_instance in _sequence(frame.get("GunInstances")):
            instance = _mapping(raw_instance)
            guid = _integer(instance.get("_Guid"))
            contexts = assigned_contexts.get(guid, Counter())
            assigned_to_loadout = bool(contexts)
            observation.weapon_instance_count += 1
            observation.assigned_weapon_instance_count += int(assigned_to_loadout)
            observation.kit_weapon_assignments.update(contexts)
            assigned = _mapping(instance.get("AssignedMods"))
            for value in _sequence(assigned.get("AssignedModClasses")):
                component_id = normalize_object_reference(value)
                if component_id:
                    assets.setdefault(component_id, _AssetObservation()).weapon_assignments[
                        (weapon_id, assigned_to_loadout)
                    ] += 1


def _record_inventory(save: dict[str, Any], assets: dict[str, _AssetObservation]) -> None:
    mod_inventory = _mapping(save.get("ModInventory"))
    for raw_slot in _sequence(mod_inventory.get("UnlimitedModStorage")):
        slot = _mapping(raw_slot)
        asset_id = normalize_object_reference(slot.get("ModDef"))
        if not asset_id:
            continue
        observation = assets.setdefault(asset_id, _AssetObservation())
        observation.mod_inventory_entries += 1
        owned = _integer(slot.get("OwnedCount"))
        equippable = _integer(slot.get("EquippableCount"))
        if owned is not None:
            observation.owned_count += owned
        if equippable is not None:
            observation.equippable_count += equippable
        unlocked = slot.get("bUnlocked")
        if unlocked is True:
            observation.unlocked_true_entries += 1
        elif unlocked is False:
            observation.unlocked_false_entries += 1

    general_inventory = _mapping(save.get("GeneralInventory"))
    for raw_slot in _sequence(general_inventory.get("Items")):
        slot = _mapping(raw_slot)
        asset_id = normalize_object_reference(slot.get("Class"))
        if not asset_id:
            continue
        observation = assets.setdefault(asset_id, _AssetObservation())
        observation.general_inventory_entries += 1
        count = _integer(slot.get("Count"))
        if count is not None:
            observation.general_inventory_count += count


def _kit_aliases(
    assets: dict[str, _AssetObservation],
    planner_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    kits_by_character_class: dict[str, list[dict[str, Any]]] = {}
    kits_by_internal_name: dict[str, list[dict[str, Any]]] = {}
    for record in planner_records:
        if record.get("kind") != "kit":
            continue
        character_class = record.get("characterClassPackagePath")
        if isinstance(character_class, str):
            kits_by_character_class.setdefault(character_class, []).append(record)
        internal_name = record.get("internalName")
        if not isinstance(internal_name, str):
            kit_id = record.get("id")
            if isinstance(kit_id, str):
                internal_name = kit_id.rsplit("/", 1)[-1].removeprefix("KitUnlock_")
        if isinstance(internal_name, str) and internal_name:
            kits_by_internal_name.setdefault(internal_name.casefold(), []).append(record)

    result: list[dict[str, Any]] = []
    for asset_id, observation in assets.items():
        if not ({"character-kit-class", "last-played-kit-class"} & set(observation.roles)):
            continue
        exact_matches = kits_by_character_class.get(asset_id, [])
        if len(exact_matches) == 1 and isinstance(exact_matches[0].get("id"), str):
            result.append(
                {
                    "characterClassId": asset_id,
                    "confidence": "authored-reference",
                    "method": "character-class-package-path",
                    "plannerKitId": exact_matches[0]["id"],
                }
            )
            continue
        basename = asset_id.rsplit("/", 1)[-1]
        internal_name = basename.removeprefix("Player_")
        internal_name = re.sub(r"_V\d+$", "", internal_name)
        matches = kits_by_internal_name.get(internal_name.casefold(), [])
        if len(matches) != 1 or not isinstance(matches[0].get("id"), str):
            continue
        result.append(
            {
                "characterClassId": asset_id,
                "confidence": "name-heuristic",
                "internalName": internal_name,
                "method": "player-class-to-internal-name",
                "plannerKitId": matches[0]["id"],
            }
        )
    return sorted(result, key=lambda item: (item["characterClassId"], item["plannerKitId"]))


def build_save_evidence(
    save: dict[str, Any],
    *,
    normalization: str,
    package_index: dict[str, Any],
    candidates: dict[str, Any],
    planner_catalogue: dict[str, Any],
) -> dict[str, Any]:
    """Build deterministic positive evidence for every ``/Game`` asset in a save."""

    packages = package_index.get("packages")
    candidate_records = candidates.get("records")
    if not isinstance(packages, list):
        raise CatalogueError("package index has no packages array")
    if not isinstance(candidate_records, list):
        raise CatalogueError("candidate document has no records array")
    planner_records = document_records(planner_catalogue, label="planner catalogue")
    source_fingerprint = _document_fingerprint(package_index, candidates, planner_catalogue)

    package_ids = {
        package.get("packagePath")
        for package in packages
        if isinstance(package, dict) and isinstance(package.get("packagePath"), str)
    }
    candidate_kinds: dict[str, set[str]] = {}
    for record in candidate_records:
        if not isinstance(record, dict):
            continue
        asset_id = record.get("packagePath") or record.get("id")
        kind = record.get("kind")
        if isinstance(asset_id, str) and isinstance(kind, str):
            candidate_kinds.setdefault(asset_id, set()).add(kind)
    planner_kinds: dict[str, set[str]] = {}
    for record in planner_records:
        asset_id = record.get("packagePath") or record.get("id")
        kind = record.get("kind")
        if isinstance(asset_id, str) and isinstance(kind, str):
            planner_kinds.setdefault(asset_id, set()).add(kind)

    assets: dict[str, _AssetObservation] = {}
    for asset_id, object_path, location in _walk_asset_references(save):
        role = _role_for_location(location)
        if role is None:
            continue
        observation = assets.setdefault(asset_id, _AssetObservation())
        observation.object_paths[object_path] += 1
        observation.locations[location] += 1
        observation.roles[role] += 1
        kind = _kind_for_role(asset_id, role)
        if kind:
            observation.kind_evidence[kind] += 1

    _record_placements(save, assets)
    _record_weapon_usage(save, assets)
    _record_inventory(save, assets)
    aliases = _kit_aliases(assets, planner_records)
    aliases_by_asset: dict[str, list[str]] = {}
    for alias in aliases:
        aliases_by_asset.setdefault(alias["characterClassId"], []).append(alias["plannerKitId"])

    records: list[dict[str, Any]] = []
    for asset_id in sorted(assets):
        observation = assets[asset_id]
        record: dict[str, Any] = {
            "candidateKinds": sorted(candidate_kinds.get(asset_id, set())),
            "id": asset_id,
            "kindEvidence": [
                {
                    "basis": basis,
                    "kind": kind,
                    "occurrences": count,
                    "strength": "save-context-heuristic",
                }
                for (kind, basis), count in sorted(observation.kind_evidence.items())
            ],
            "objectPaths": sorted(observation.object_paths),
            "packageIndexed": asset_id in package_ids,
            "plannerAliases": sorted(aliases_by_asset.get(asset_id, [])),
            "plannerKinds": sorted(planner_kinds.get(asset_id, set())),
            "saveLocations": [
                {"occurrences": count, "path": path}
                for path, count in sorted(observation.locations.items())
            ],
            "saveOccurrences": sum(observation.object_paths.values()),
            "saveRoles": [
                {"occurrences": count, "role": role}
                for role, count in sorted(observation.roles.items())
            ],
        }
        if observation.placements:
            record["perkPlacements"] = [
                {
                    "assignedToSavedLoadout": assigned_to_loadout,
                    "column": column,
                    "count": count,
                    "kitClassId": kit_id,
                    "rotation": rotation,
                    "row": row,
                }
                for (kit_id, row, column, rotation, assigned_to_loadout), count in sorted(
                    observation.placements.items()
                )
            ]
        if observation.weapon_assignments:
            record["weaponAssignments"] = [
                {
                    "assignedToSavedLoadout": assigned_to_loadout,
                    "instanceOccurrences": count,
                    "weaponId": weapon_id,
                }
                for (weapon_id, assigned_to_loadout), count in sorted(
                    observation.weapon_assignments.items()
                )
            ]
        if observation.weapon_frame_count:
            record["weaponUsage"] = {
                "assignedInstanceCount": observation.assigned_weapon_instance_count,
                "frameCount": observation.weapon_frame_count,
                "instanceCount": observation.weapon_instance_count,
            }
            record["kitWeaponAssignments"] = [
                {
                    "count": count,
                    "kitClassId": kit_id,
                    "savedGunSlotIndex": slot_index,
                }
                for (kit_id, slot_index), count in sorted(
                    observation.kit_weapon_assignments.items()
                )
            ]
        if observation.mod_inventory_entries:
            record["modInventory"] = {
                "entries": observation.mod_inventory_entries,
                "equippableCount": observation.equippable_count,
                "ownedCount": observation.owned_count,
                "unlockedFalseEntries": observation.unlocked_false_entries,
                "unlockedTrueEntries": observation.unlocked_true_entries,
            }
        if observation.general_inventory_entries:
            record["generalInventory"] = {
                "count": observation.general_inventory_count,
                "entries": observation.general_inventory_entries,
            }
        records.append(record)

    role_assets: Counter[str] = Counter()
    role_occurrences: Counter[str] = Counter()
    kind_assets: Counter[str] = Counter()
    for observation in assets.values():
        for role in observation.roles:
            role_assets[role] += 1
        for role, count in observation.roles.items():
            role_occurrences[role] += count
        for kind in {kind for kind, _basis in observation.kind_evidence}:
            kind_assets[kind] += 1

    guid_diagnostics = _guid_diagnostics(save)
    hinted_but_unclassified = sorted(
        asset_id
        for asset_id, observation in assets.items()
        if (
            observation.kind_evidence
            and asset_id not in candidate_kinds
            and asset_id not in aliases_by_asset
        )
    )
    unindexed = sorted(asset_id for asset_id in assets if asset_id not in package_ids)

    return {
        "schemaVersion": 2,
        "plannerSourceFingerprint": source_fingerprint,
        "diagnostics": {
            **guid_diagnostics,
            "hintedButUnclassifiedPackageIds": hinted_but_unclassified,
            "unindexedPackageIds": unindexed,
        },
        "kitAliases": aliases,
        "records": records,
        "scope": {
            "absenceMeans": "not-observed",
            "completeness": "partial-save",
            "semanticLimits": [
                "does-not-prove-planner-catalogue-completeness",
                "does-not-prove-compatibility-rules",
                "does-not-prove-grid-footprints-or-legality",
                "does-not-prove-player-facing-names",
                "does-not-prove-deliberate-use-or-unlock-state",
                "does-not-interpret-inventory-unlock-flags",
            ],
        },
        "source": {
            "format": "AFE2 CharacterDoc",
            "normalization": normalization,
            "directIdentifiersIncluded": False,
            "sensitiveLocalEvidence": True,
        },
        "summary": {
            "assetOccurrences": sum(
                sum(observation.object_paths.values()) for observation in assets.values()
            ),
            "assets": len(assets),
            "candidateAssets": sum(asset_id in candidate_kinds for asset_id in assets),
            "distinctAssetsByKindEvidence": dict(sorted(kind_assets.items())),
            "distinctAssetsByObservedRole": dict(sorted(role_assets.items())),
            "indexedAssets": sum(asset_id in package_ids for asset_id in assets),
            "missingPackageAssets": sum(asset_id not in package_ids for asset_id in assets),
            "occurrencesByObservedRole": dict(sorted(role_occurrences.items())),
            "plannerAliasedAssets": len(aliases_by_asset),
            "plannerAssets": sum(asset_id in planner_kinds for asset_id in assets),
        },
    }
