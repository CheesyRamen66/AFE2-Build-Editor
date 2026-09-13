"""Compile enemy (critter) identity and balance rows from authored game evidence.

Enemy balance is not serialized on the pawn blueprints.  Each ``Critter_*``
blueprint names an ``AttributeCSVFileOverride`` row set, and the matching
``Design/ClassDefs/<name>.csv`` carries one column per critter level.  Those
CSVs live in the standalone ``.pak`` rather than IoStore, so they never reach
the package index that drives the rest of semantic extraction; this module
reads them directly and projects the defensive rows the planner cares about.

The level axis is the game's own: every ClassDefs sheet is indexed 1..N with no
difficulty dimension.  ``Design/Difficulty/DifficultySlider.csv`` is captured
alongside it but is a player-side sheet (revive timers, XP and resource
multipliers, friendly fire); it contains no enemy health or armour scaling, so
no difficulty-to-level mapping is asserted here.
"""

from __future__ import annotations

import csv
import io
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .archives import read_pak_member
from .errors import CatalogueError

ENEMY_SCHEMA_VERSION = 1

CLASS_DEFS_DIRECTORY = "AFE2/Content/Design/ClassDefs"
DIFFICULTY_SLIDER_MEMBER = "AFE2/Content/Design/Difficulty/DifficultySlider.csv"

# AFE2's own roster lives under ``VenusEnemies``; ``Critters`` is the carried-over
# tree from the previous title.  Both ship, and both are indexed, but only the
# ``Venus`` generation is wired to the ``AvoCSV_`` balance sheets that carry the
# penetration-resistance rows.
_CRITTER_PATH_MARKERS = ("/Character/VenusEnemies/", "/Character/Critters/")
_GENERATION_BY_MARKER = {
    "/Character/VenusEnemies/": "venus",
    "/Character/Critters/": "legacy",
}
_CRITTER_NAME_PREFIX = "Critter_"

# Ability, animation, audio and component blueprints share the ``Critter_``
# prefix but carry no balance rows of their own.
_EXCLUDED_NAME_FRAGMENTS = (
    "Ability",
    "Anims",
    "AudioMap",
    "Footstep",
    "Interface",
    "Component",
    "Projectile_",
    "_GE",
    "Passive",
    "Ragdoll",
    "HitZoneData",
    "AbilitySet",
    "_VO_",
    "SlamShake",
    "Struct",
    "Grapple",
    "_AoE",
)
_EXCLUDED_PATH_FRAGMENTS = ("/Abilities/", "/CritterWeapons/", "/Data/")

# Rows projected into the ``defense`` summary.  Everything the sheet carries is
# still preserved verbatim under ``statsByLevel``.
_HEALTH_ATTRIBUTE = "TakesDamageAttributes.HealthMax"
_ARMOR_ATTRIBUTE = "TakesDamageAttributes.ShieldMax"
_PENETRATION_ATTRIBUTES = {
    "penetrationResistance": "TakesDamageAttributes.PenetrationResistance",
    "penetrationResistanceArmor": "TakesDamageAttributes.PenetrationResistance_Armor",
    "penetrationResistanceWeakpointMultiplier": (
        "TakesDamageAttributes.PenetrationResistanceWeakpointMultiplier"
    ),
}
_MITIGATION_ATTRIBUTES = {
    "weakpointMultiplier": "TakesDamageAttributes.WeakpointMultiplier",
    "aoeAvoidance": "TakesDamageAttributes.AOEAvoidance",
    "fieldEffectResistance": "TakesDamageAttributes.FieldEffectResistance",
    # Authored on only a handful of sheets, and it follows the elemental
    # convention: negative means the critter bleeds more readily.
    "bleedBuildUpResistance": "TakesDamageAttributes.BleedBuildUpResistance",
}

_RESISTANCE_SUFFIX = "Damage_PercentResistance"
_FLAT_REDUCTION_SUFFIX = "Damage_FlatReduction"
_RESISTANCE_PREFIX = "TakesDamageAttributes."


def _generation(package_path: str) -> str | None:
    for marker, generation in _GENERATION_BY_MARKER.items():
        if marker in package_path:
            return generation
    return None


def _is_enemy_package(package_path: str) -> bool:
    if not any(marker in package_path for marker in _CRITTER_PATH_MARKERS):
        return False
    if any(fragment in package_path for fragment in _EXCLUDED_PATH_FRAGMENTS):
        return False
    name = package_path.rsplit("/", 1)[-1]
    if not name.startswith(_CRITTER_NAME_PREFIX):
        return False
    return not any(fragment in name for fragment in _EXCLUDED_NAME_FRAGMENTS)


def select_enemy_packages(package_index: Mapping[str, Any]) -> list[str]:
    """Return the critter blueprint packages that may carry balance rows."""

    packages = package_index.get("packages")
    if not isinstance(packages, list):
        raise CatalogueError("package index has no packages array for enemy extraction")
    selected = {
        package["packagePath"]
        for package in packages
        if isinstance(package, dict)
        and isinstance(package.get("packagePath"), str)
        and _is_enemy_package(package["packagePath"])
    }
    return sorted(selected)


def _number(value: str) -> float | None:
    text = value.strip()
    if not text:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    return parsed


def _collapse(values: Sequence[float | None]) -> dict[str, Any]:
    """Collapse a level series that never varies into a single value.

    Most rows are flat across all twenty levels; storing one number instead of
    twenty keeps the document readable without discarding the level axis where
    it genuinely moves.
    """

    present = [value for value in values if value is not None]
    if not present:
        return {"status": "absent"}
    if len(present) == len(values) and len(set(present)) == 1:
        return {"status": "constant", "value": present[0]}
    return {"status": "byLevel", "byLevel": list(values)}


def parse_class_def_csv(text: str) -> dict[str, Any]:
    """Parse one ``Design/ClassDefs`` sheet into level-indexed attribute rows."""

    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise CatalogueError("class definition sheet was empty")
    header = rows[0]
    levels: list[int] = []
    for cell in header[1:]:
        parsed = _number(cell)
        if parsed is None:
            continue
        levels.append(int(parsed))
    if not levels:
        raise CatalogueError("class definition sheet declared no level columns")

    attributes: dict[str, dict[str, Any]] = {}
    for row in rows[1:]:
        if not row:
            continue
        name = row[0].strip()
        if not name:
            continue
        values = [_number(cell) for cell in row[1 : len(levels) + 1]]
        while len(values) < len(levels):
            values.append(None)
        if name in attributes:
            # A duplicated row is authored data we cannot silently merge.
            raise CatalogueError(f"class definition sheet repeated attribute: {name}")
        attributes[name] = _collapse(values)
    if not attributes:
        raise CatalogueError("class definition sheet carried no attribute rows")
    return {"levels": levels, "attributes": attributes}


def parse_difficulty_slider(text: str) -> dict[str, Any]:
    """Parse ``Design/Difficulty/DifficultySlider.csv`` into named columns."""

    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise CatalogueError("difficulty slider sheet was empty")
    difficulties = [cell.strip() for cell in rows[0][1:] if cell.strip()]
    if not difficulties:
        raise CatalogueError("difficulty slider sheet declared no difficulty columns")
    settings: dict[str, dict[str, float | None]] = {}
    for row in rows[1:]:
        if not row:
            continue
        name = row[0].strip()
        if not name:
            continue
        values = [_number(cell) for cell in row[1 : len(difficulties) + 1]]
        while len(values) < len(difficulties):
            values.append(None)
        settings[name] = dict(zip(difficulties, values))
    if not settings:
        raise CatalogueError("difficulty slider sheet carried no setting rows")
    return {"difficulties": difficulties, "settings": settings}


def _default_export(asset: Mapping[str, Any]) -> Mapping[str, Any] | None:
    exports = asset.get("exports")
    if not isinstance(exports, list):
        return None
    for export in exports:
        if not isinstance(export, dict):
            continue
        name = export.get("objectName")
        if isinstance(name, str) and name.startswith("Default__"):
            return export
    return None


def _import_package(asset: Mapping[str, Any], index: Any) -> str | None:
    """Walk an import's outer chain up to its owning ``/Game/`` package."""

    imports = asset.get("imports")
    if not isinstance(imports, list) or not isinstance(index, int) or index >= 0:
        return None
    current = index
    seen: set[int] = set()
    while current < 0 and current not in seen:
        seen.add(current)
        position = -current - 1
        if position >= len(imports) or not isinstance(imports[position], Mapping):
            return None
        item = imports[position]
        name = item.get("objectName")
        if isinstance(name, str) and name.startswith("/Game/"):
            return name.split(".", 1)[0]
        outer = item.get("outerIndex")
        if not isinstance(outer, int):
            return None
        current = outer
    return None


def parent_package(asset: Mapping[str, Any]) -> str | None:
    """Return the package of the blueprint class this asset derives from."""

    exports = asset.get("exports")
    if not isinstance(exports, list):
        return None
    for export in exports:
        if not isinstance(export, Mapping):
            continue
        name = str(export.get("objectName", ""))
        if name.endswith("_C") and not name.startswith("Default__"):
            return _import_package(asset, export.get("superIndex"))
    return None


def _properties(export: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    data = export.get("data")
    if not isinstance(data, list):
        return {}
    found: dict[str, Mapping[str, Any]] = {}
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("Name"), str):
            found.setdefault(item["Name"], item)
    return found


# Balance config sits on the class default object, but the player-facing name,
# rank and faction live on the attached ``CritterCharacterComponent`` template.
_IDENTITY_COMPONENT_MARKER = "CritterCharacterComponent"


def _asset_properties(asset: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    """Merge the class default object with the critter identity component."""

    merged: dict[str, Mapping[str, Any]] = {}
    default = _default_export(asset)
    if default is not None:
        merged.update(_properties(default))
    exports = asset.get("exports")
    if not isinstance(exports, list):
        return merged
    for export in exports:
        if not isinstance(export, Mapping):
            continue
        if _IDENTITY_COMPONENT_MARKER not in str(export.get("objectName", "")):
            continue
        for name, prop in _properties(export).items():
            merged.setdefault(name, prop)
    return merged


def _text_value(prop: Mapping[str, Any] | None) -> tuple[str | None, str]:
    """Return authored display text and the evidence it came from."""

    if not isinstance(prop, Mapping):
        return None, "absent"
    invariant = prop.get("CultureInvariantString")
    if isinstance(invariant, str) and invariant.strip():
        return invariant, "culture-invariant-string"
    key = prop.get("Value")
    if isinstance(key, str) and key.strip():
        return None, "localization-key-only"
    return None, "absent"


def _string_value(prop: Mapping[str, Any] | None) -> str | None:
    if not isinstance(prop, Mapping):
        return None
    value = prop.get("Value")
    if isinstance(value, str) and value.strip():
        return value
    return None


def _bool_value(prop: Mapping[str, Any] | None) -> bool | None:
    if not isinstance(prop, Mapping):
        return None
    value = prop.get("Value")
    return value if isinstance(value, bool) else None


def _enum_tail(value: str | None) -> str | None:
    if not isinstance(value, str) or "::" not in value:
        return value
    return value.split("::", 1)[1]


def _gameplay_tags(prop: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(prop, Mapping):
        return []
    collected: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str) and node and node != "None":
            collected.append(node)

    walk(prop.get("Value"))
    return sorted(dict.fromkeys(collected))


def _elemental_rows(attributes: Mapping[str, Any]) -> dict[str, Any]:
    """Split the elemental mitigation rows out of a parsed sheet."""

    resistances: dict[str, Any] = {}
    flat_reductions: dict[str, Any] = {}
    for name, row in attributes.items():
        if not name.startswith(_RESISTANCE_PREFIX):
            continue
        tail = name[len(_RESISTANCE_PREFIX) :]
        if tail.endswith(_RESISTANCE_SUFFIX):
            element = tail[: -len(_RESISTANCE_SUFFIX)]
            if element:
                resistances[element] = row
        elif tail.endswith(_FLAT_REDUCTION_SUFFIX):
            element = tail[: -len(_FLAT_REDUCTION_SUFFIX)]
            if element:
                flat_reductions[element] = row
    return {"resistances": resistances, "flatReductions": flat_reductions}


def _row_values(row: Mapping[str, Any] | None) -> list[float]:
    if not isinstance(row, Mapping):
        return []
    if row.get("status") == "constant":
        value = row.get("value")
        return [value] if isinstance(value, (int, float)) else []
    if row.get("status") == "byLevel":
        series = row.get("byLevel")
        if isinstance(series, list):
            return [value for value in series if isinstance(value, (int, float))]
    return []


def _derive_element_summary(resistances: Mapping[str, Any]) -> dict[str, list[str]]:
    """Name the elements the sheet treats as weaknesses or immunities.

    A negative ``*Damage_PercentResistance`` increases incoming damage, so it is
    the authored weakness signal; a value at or above 1.0 removes the damage
    entirely.
    """

    weaknesses: list[str] = []
    immunities: list[str] = []
    for element, row in resistances.items():
        values = _row_values(row)
        if not values:
            continue
        if min(values) < 0:
            weaknesses.append(element)
        if min(values) >= 1.0:
            immunities.append(element)
    return {"weakTo": sorted(weaknesses), "immuneTo": sorted(immunities)}


def _defense_summary(parsed: Mapping[str, Any]) -> dict[str, Any]:
    attributes = parsed["attributes"]
    summary: dict[str, Any] = {
        "health": attributes.get(_HEALTH_ATTRIBUTE, {"status": "absent"}),
        "armor": attributes.get(_ARMOR_ATTRIBUTE, {"status": "absent"}),
    }
    for key, attribute in _PENETRATION_ATTRIBUTES.items():
        summary[key] = attributes.get(attribute, {"status": "absent"})
    for key, attribute in _MITIGATION_ATTRIBUTES.items():
        summary[key] = attributes.get(attribute, {"status": "absent"})
    return summary


_INHERITED_PROPERTIES = (
    "DisplayName",
    "AttributeCSVFileOverride",
    "Rank",
    "CritterGroup",
    "IsMiniboss",
    "CritterGroupTags",
    "OwnedGameplayTags",
    "TeamNumber",
)

_MAX_PARENT_DEPTH = 12


def resolve_properties(
    package_path: str,
    assets_by_package: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Mapping[str, Any]], dict[str, str], list[str]]:
    """Merge a blueprint's own defaults with those inherited from its parents.

    Venus-generation critters override only the rows that differ from
    ``BaseCritterCharacter``, so identity fields have to be read through the
    class chain rather than off the leaf blueprint.
    """

    merged: dict[str, Mapping[str, Any]] = {}
    inherited_from: dict[str, str] = {}
    chain: list[str] = []
    current: str | None = package_path
    seen: set[str] = set()
    while current and current not in seen and len(chain) < _MAX_PARENT_DEPTH:
        seen.add(current)
        chain.append(current)
        asset = assets_by_package.get(current)
        if asset is None:
            break
        for name, prop in _asset_properties(asset).items():
            if name in _INHERITED_PROPERTIES and name not in merged:
                merged[name] = prop
                if current != package_path:
                    inherited_from[name] = current
        current = parent_package(asset)
    return merged, inherited_from, chain


def build_enemy_record(
    *,
    package_path: str,
    assets_by_package: Mapping[str, Mapping[str, Any]],
    class_defs: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Project one critter blueprint and its balance sheet into a record."""

    properties, inherited_from, chain = resolve_properties(package_path, assets_by_package)
    display_name, display_name_source = _text_value(properties.get("DisplayName"))
    csv_name = _string_value(properties.get("AttributeCSVFileOverride"))

    record: dict[str, Any] = {
        "id": package_path,
        "packagePath": package_path,
        "kind": "enemy",
        "generation": _generation(package_path),
        "displayName": display_name,
        "displayNameSource": display_name_source,
        # The Venus roster does not author a per-enemy display name, so the
        # blueprint stem is kept as a stable, clearly-derived fallback label.
        "derivedName": package_path.rsplit("/", 1)[-1],
        "classChain": chain,
        "inheritedFrom": inherited_from,
        "rank": _enum_tail(_string_value(properties.get("Rank"))),
        "critterGroup": _enum_tail(_string_value(properties.get("CritterGroup"))),
        "isMiniboss": _bool_value(properties.get("IsMiniboss")),
        "critterGroupTags": _gameplay_tags(properties.get("CritterGroupTags")),
        "ownedGameplayTags": _gameplay_tags(properties.get("OwnedGameplayTags")),
        "attributeCsvName": csv_name,
    }

    if csv_name is None:
        record["stats"] = {
            "status": "inherited-or-absent",
            "reason": "blueprint declared no AttributeCSVFileOverride",
        }
        return record

    parsed = class_defs.get(csv_name)
    if parsed is None:
        record["stats"] = {
            "status": "unresolved",
            "reason": f"no Design/ClassDefs sheet named {csv_name}",
        }
        return record

    elemental = _elemental_rows(parsed["attributes"])
    record["stats"] = {
        "status": "parsed",
        "source": f"{CLASS_DEFS_DIRECTORY}/{csv_name}.csv",
        "levels": parsed["levels"],
        "defense": _defense_summary(parsed),
        "elemental": {
            **elemental,
            **_derive_element_summary(elemental["resistances"]),
        },
        "statsByLevel": parsed["attributes"],
    }
    return record


def _read_design_member(
    design_paks: Sequence[Path],
    repak: Path,
    archive_key: str,
    member_path: str,
) -> str:
    """Read a design member from whichever standalone pak carries it."""

    last: CatalogueError | None = None
    for pak in design_paks:
        try:
            return read_pak_member(pak, repak, archive_key, member_path)
        except CatalogueError as exc:
            last = exc
    raise last or CatalogueError(f"no standalone pak carried member: {member_path}")


def _load_class_defs(
    *,
    design_paks: Sequence[Path],
    repak: Path,
    archive_key: str,
    names: Iterable[str],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    parsed: dict[str, Any] = {}
    failures: list[dict[str, str]] = []
    for name in sorted(dict.fromkeys(names)):
        member = f"{CLASS_DEFS_DIRECTORY}/{name}.csv"
        try:
            text = _read_design_member(design_paks, repak, archive_key, member)
        except CatalogueError:
            failures.append(
                {"stage": "class-defs", "name": name, "reason": "member-unreadable"}
            )
            continue
        try:
            parsed[name] = parse_class_def_csv(text)
        except CatalogueError as exc:
            failures.append(
                {"stage": "class-defs", "name": name, "reason": str(exc)}
            )
    return parsed, failures


def build_enemy_assets(
    *,
    paks_dir: Path,
    design_paks: Sequence[Path],
    retoc: Path,
    repak: Path,
    archive_key: str,
    reader: Any,
    package_index: Mapping[str, Any],
    source_fingerprint: str,
    secret_environment_names: Sequence[str] = (),
    jobs: int = 1,
) -> dict[str, Any]:
    """Build the enemy balance document from critter blueprints and design CSVs."""

    # Imported lazily: these helpers are internal to semantic extraction and
    # importing them at module scope would make the dependency cyclic.
    from .semantic_assets import _extract_members, _member_map, _run_reader

    packages = select_enemy_packages(package_index)
    members = _member_map(package_index)
    requests: list[dict[str, str]] = []
    failures: list[dict[str, str]] = []
    for package in packages:
        member = members.get(package)
        if member:
            requests.append({"memberPath": member, "packagePath": package})
        else:
            failures.append(
                {
                    "stage": "package-index",
                    "packagePath": package,
                    "reason": "package-had-no-uasset-member",
                }
            )

    def read_packages(pending: Sequence[Mapping[str, str]], label: str) -> list[Mapping[str, Any]]:
        if not pending:
            return []
        with tempfile.TemporaryDirectory(prefix="afe2-enemy-assets-") as temporary:
            work = Path(temporary)
            loose = work / "loose"
            loose.mkdir()
            _extract_members(
                paks_dir=paks_dir,
                retoc=retoc,
                key=archive_key,
                loose_root=loose,
                members=(item["memberPath"] for item in pending),
            )
            document, _ = _run_reader(
                reader,
                request={"assets": list(pending), "icons": [], "schemaVersion": 1},
                loose_root=loose,
                work=work,
                label=label,
                secret_environment_names=secret_environment_names,
                jobs=jobs,
            )
        raw_assets = document.get("assets")
        if not isinstance(raw_assets, list):
            raise CatalogueError("enemy reader returned no asset array")
        for failure in document.get("failures") or []:
            if isinstance(failure, dict):
                failures.append(
                    {"stage": "reader", **{key: str(value) for key, value in failure.items()}}
                )
        return [asset for asset in raw_assets if isinstance(asset, dict)]

    assets_by_package: dict[str, Mapping[str, Any]] = {}
    for asset in read_packages(requests, "enemies"):
        if isinstance(asset.get("packagePath"), str):
            assets_by_package[asset["packagePath"]] = asset

    # Identity rows live on parent classes; follow the chain to closure so the
    # merge in ``resolve_properties`` sees every level it needs.
    for _ in range(_MAX_PARENT_DEPTH):
        wanted: list[dict[str, str]] = []
        queued: set[str] = set()
        for asset in list(assets_by_package.values()):
            parent = parent_package(asset)
            # Siblings share parents; the reader rejects duplicate identities.
            if not parent or parent in assets_by_package or parent in queued:
                continue
            queued.add(parent)
            member = members.get(parent)
            if member is None:
                failures.append(
                    {
                        "stage": "parent-chain",
                        "packagePath": parent,
                        "reason": "package-had-no-uasset-member",
                    }
                )
                assets_by_package.setdefault(parent, {"packagePath": parent, "exports": []})
                continue
            wanted.append({"memberPath": member, "packagePath": parent})
        if not wanted:
            break
        for asset in read_packages(wanted, "enemy-parents"):
            if isinstance(asset.get("packagePath"), str):
                assets_by_package.setdefault(asset["packagePath"], asset)

    enemy_packages = [
        package for package in packages if package in assets_by_package
    ]
    csv_names: list[str] = []
    for package in enemy_packages:
        properties, _, _ = resolve_properties(package, assets_by_package)
        name = _string_value(properties.get("AttributeCSVFileOverride"))
        if name:
            csv_names.append(name)
    class_defs, class_def_failures = _load_class_defs(
        design_paks=design_paks,
        repak=repak,
        archive_key=archive_key,
        names=csv_names,
    )
    failures.extend(class_def_failures)

    records = [
        build_enemy_record(
            package_path=package,
            assets_by_package=assets_by_package,
            class_defs=class_defs,
        )
        for package in enemy_packages
    ]
    records.sort(key=lambda record: record["id"])

    difficulty: dict[str, Any]
    try:
        difficulty = {
            "status": "parsed",
            "source": DIFFICULTY_SLIDER_MEMBER,
            "scope": "player-side",
            **parse_difficulty_slider(
                _read_design_member(
                    design_paks, repak, archive_key, DIFFICULTY_SLIDER_MEMBER
                )
            ),
        }
    except CatalogueError as exc:
        difficulty = {"status": "unresolved", "reason": str(exc)}
        failures.append({"stage": "difficulty-slider", "reason": str(exc)})

    parsed_count = sum(
        1 for record in records if record.get("stats", {}).get("status") == "parsed"
    )
    return {
        "schemaVersion": ENEMY_SCHEMA_VERSION,
        "sourceFingerprint": source_fingerprint,
        "coverage": {
            "selectedPackages": len(packages),
            "records": len(records),
            "recordsWithStats": parsed_count,
            "classDefSheets": len(class_defs),
            "failures": len(failures),
        },
        "difficultySlider": difficulty,
        "records": records,
        "failures": failures,
    }
