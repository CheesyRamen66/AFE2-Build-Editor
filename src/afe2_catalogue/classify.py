"""Path-evidence candidate classification.

These rules identify likely catalogue records; they do not decode Unreal
exports and therefore never claim to verify display text or compatibility.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import CatalogueError


CANDIDATE_KINDS = (
    "ability",
    "augment",
    "gridShape",
    "item",
    "kit",
    "mod",
    "perk",
    "trait",
    "weapon",
)


@dataclass(frozen=True)
class Rule:
    id: str
    kind: str
    include: tuple[re.Pattern[str], ...]
    exclude: tuple[re.Pattern[str], ...]
    confidence: str

    def matches(self, package_path: str) -> bool:
        return any(pattern.search(package_path) for pattern in self.include) and not any(
            pattern.search(package_path) for pattern in self.exclude
        )


def load_rules(path: Path) -> tuple[int, list[Rule], list[str]]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogueError(f"could not read classification rules: {path}") from exc
    version = document.get("schemaVersion")
    if not isinstance(version, int):
        raise CatalogueError("classification rules need an integer schemaVersion")
    roots = document.get("relevantRoots", [])
    if not isinstance(roots, list) or not all(isinstance(value, str) for value in roots):
        raise CatalogueError("classification rules have invalid relevantRoots")
    rules: list[Rule] = []
    seen_ids: set[str] = set()
    for item in document.get("rules", []):
        if not isinstance(item, dict):
            raise CatalogueError("classification rule must be an object")
        rule_id = item.get("id")
        if not isinstance(rule_id, str) or not rule_id or rule_id in seen_ids:
            raise CatalogueError("classification rule IDs must be unique strings")
        seen_ids.add(rule_id)
        try:
            include = tuple(re.compile(value) for value in item["include"])
            exclude = tuple(re.compile(value) for value in item.get("exclude", []))
        except (KeyError, TypeError, re.error) as exc:
            raise CatalogueError(f"classification rule {rule_id} has invalid patterns") from exc
        if not include:
            raise CatalogueError(f"classification rule {rule_id} has no include pattern")
        kind = str(item.get("kind", ""))
        if kind not in CANDIDATE_KINDS:
            raise CatalogueError(
                f"classification rule {rule_id} has unsupported kind: {kind}"
            )
        rules.append(
            Rule(
                id=rule_id,
                kind=kind,
                include=include,
                exclude=exclude,
                confidence=str(item.get("confidence", "path-heuristic")),
            )
        )
    return version, rules, sorted(set(roots))


def _basename(package_path: str) -> str:
    return package_path.rsplit("/", 1)[-1]


def _humanize(value: str) -> str:
    for prefix in ("KitUnlock_", "PerkBoard_", "Perk_", "GA_", "Venus_", "Avo_GunPerk_", "Avo_Perk_", "Avo_"):
        if value.startswith(prefix):
            value = value[len(prefix) :]
            break
    value = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value)
    return " ".join(value.replace("_", " ").split())


def _inferred_fields(path: str, kind: str) -> dict[str, str]:
    fields = {"nameHint": _humanize(_basename(path))}
    kit_match = re.search(r"/Avocado_Classes/([^/]+)/", path)
    if kit_match and kit_match.group(1) not in {"ClassUnlocks", "Perks", "Shared"}:
        fields["kitHint"] = kit_match.group(1)
    if kind == "mod":
        socket = re.search(
            r"/Attachments/(Armatures|Barrels|Magazines|Muzzles|Optics|Underbarrel)/",
            path,
        )
        if socket:
            fields["socketHint"] = socket.group(1).removesuffix("s").lower()
    if "/PerksOld/" in path:
        fields["lifecycleHint"] = "legacy-path"
    if path.startswith("/Game/Blueprints/Avocado_Classes/Perks/"):
        fields["scopeHint"] = "generic"
    if "/Attachments/Overclocks/" in path:
        fields["familyHint"] = "overclock"
    return fields


def classify_packages(package_index: dict[str, Any], rules_path: Path) -> dict[str, Any]:
    rules_version, rules, roots = load_rules(rules_path)
    records: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    unclassified: list[str] = []

    packages = package_index.get("packages")
    if not isinstance(packages, list):
        raise CatalogueError("package index has no packages array")
    for package in packages:
        path = package.get("packagePath") if isinstance(package, dict) else None
        if not isinstance(path, str):
            continue
        matched = [rule for rule in rules if rule.matches(path)]
        if not matched:
            if any(path.startswith(root) for root in roots):
                unclassified.append(path)
            continue
        kinds = sorted({rule.kind for rule in matched})
        if len(kinds) != 1:
            ambiguous.append({"packagePath": path, "possibleKinds": kinds, "rules": sorted(rule.id for rule in matched)})
            continue
        kind = kinds[0]
        records.append(
            {
                "confidence": "path-heuristic",
                "evidence": [
                    {
                        "rule": rule.id,
                        "type": "package-path",
                    }
                    for rule in sorted(matched, key=lambda value: value.id)
                ],
                "id": path,
                "inferred": _inferred_fields(path, kind),
                "kind": kind,
                "missingFields": ["exports", "localizedDisplayName", "compatibility"],
                "packagePath": path,
                "sourceChunks": package.get("chunks", []),
                "status": "candidate",
            }
        )

    records.sort(key=lambda item: (item["kind"], item["id"]))
    ambiguous.sort(key=lambda item: item["packagePath"])
    return {
        "schemaVersion": 1,
        "rulesVersion": rules_version,
        "records": records,
        "diagnostics": {
            "ambiguous": ambiguous,
            "unclassifiedRelevantPackages": sorted(unclassified),
        },
    }
