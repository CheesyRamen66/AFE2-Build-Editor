"""Compile weapon-attachment presentation rows from authored game evidence.

The game does not generally serialize prose in ``GunModDef.Description``.
Instead, its equipment panel combines comparable-attribute rows derived from
``Effects`` with separately authored ``ConditionalModDescriptions``.  This
module performs that projection once in the catalogue backend so the frontend
only has to render strings; it never has to reproduce gameplay arithmetic.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from .errors import CatalogueError


ATTACHMENT_DESCRIPTION_SECTION_SEPARATOR = "\r\n\r\n"
ATTACHMENT_DESCRIPTION_LINE_SEPARATOR = "\r\n"
ATTACHMENT_DESCRIPTION_CONDITIONAL_STAT_INDENT = "  "
AUGMENT_DESCRIPTION_PANEL_ORDER = (
    "description",
    "descriptionSecondary",
    "descriptionUpper",
)

_UI_FILTERED_ATTRIBUTES = {
    # PopulateWithGunMod supplies these exact exclusions to the game's
    # comparable-stat query so compound effects result in one player-facing
    # row rather than primary/secondary/internal duplicates.
    "DealsDamageAttributes.DamageMagnitude_Secondary",
    "DealsDamageAttributes.DamagePerSecond",
    "DealsDamageAttributes.StoppingPower_Secondary",
    "DealsDamageAttributes.StoppingPowerPerSecond",
    "GunGameplayAttributes.Range",
    "GunGameplayAttributes.NearDamageDistance",
    "GunGameplayAttributes.VeryFarDamageDistance",
    "GunGameplayAttributes.VeryFarDamageDistanceMultiplier",
    "GunGameplayAttributes.RangeDamageDistanceMultiplier",
}

_MOD_STAT_LABEL_OVERRIDES = {
    # WB_Stat_Compare_Entry.SetEntryStats applies these labels when its context
    # is a gun mod.  They intentionally describe the player-facing direction
    # (Reload Speed), not merely the backing attribute (Reload Time).
    "DealsDamageAttributes.DamageMagnitude_Primary": "Damage",
    "DealsDamageAttributes.StoppingPower": "Stopping Power",
    "GunGameplayAttributes.FarDamageDistance": "Weapon Range",
    "GunGameplayAttributes.OverheatTime": "Overheat Duration",
    "GunGameplayAttributes.TimeToReload": "Reload Speed",
}

_TRAIT_STAT_LABEL_OVERRIDES = {
    # WB_Button_Equip_Content_GunPerk.ReturnPerkDescription applies these two
    # player-facing names while composing the weapon-trait picker text.
    "GunGameplayAttributes.OverheatTime": "Overheat Duration",
    "GunGameplayAttributes.TimeToReload": "Reload Speed",
}

_MOD_RESULT_OVERRIDES = {
    "GunGameplayAttributes.TimeToReload": "HigherIsBetter",
}

def _uses_gun_mod_stat_ui(kind: str) -> bool:
    """Return whether PopulateWithGunMod applies its comparison transforms."""

    return kind in {"augment", "mod"}


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _metadata_rows(
    attribute_metadata: Mapping[str, Any] | None,
) -> tuple[list[Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    if not isinstance(attribute_metadata, Mapping):
        raise CatalogueError("semantic assets omitted canonical attribute metadata")
    rows = attribute_metadata.get("rows")
    if attribute_metadata.get("status") != "parsed" or not isinstance(rows, list) or not rows:
        raise CatalogueError("canonical attribute metadata was not parsed")

    normalized: list[Mapping[str, Any]] = []
    by_attribute: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise CatalogueError("canonical attribute metadata contained a malformed row")
        attribute = row.get("attribute")
        if (
            not isinstance(attribute, str)
            or not attribute
            or attribute in by_attribute
            or not isinstance(row.get("displayName"), str)
            or not row["displayName"].strip()
            or not isinstance(row.get("displayType"), str)
            or not isinstance(row.get("modifierOperation"), str)
            or row.get("result") not in {"HigherIsBetter", "LowerIsBetter"}
            or type(row.get("sortOrder")) is not int
        ):
            raise CatalogueError("canonical attribute metadata contained an invalid row")
        normalized.append(row)
        by_attribute[attribute] = row
    return normalized, by_attribute


def _effect_leaf(effect: Mapping[str, Any]) -> str:
    path = effect.get("effectPackagePath")
    return path.rsplit("/", 1)[-1] if isinstance(path, str) else ""


def _modifier_rows_for_effect(
    effect: Mapping[str, Any],
    *,
    kind: str,
    rows: Sequence[Mapping[str, Any]],
    by_attribute: Mapping[str, Mapping[str, Any]],
) -> list[tuple[Mapping[str, Any], Mapping[str, Any]]]:
    definition = effect.get("definition")
    modifiers = definition.get("modifiers") if isinstance(definition, Mapping) else None
    if not isinstance(modifiers, list) or not modifiers:
        raise CatalogueError(
            "visible attachment effect had no parsed modifiers: " + _effect_leaf(effect)
        )

    override_attribute = definition.get("overrideDisplayStatTag")
    if override_attribute is not None:
        metadata = (
            by_attribute.get(override_attribute)
            if isinstance(override_attribute, str)
            else None
        )
        first_set_by_caller = next(
            (
                modifier
                for modifier in modifiers
                if isinstance(modifier, Mapping)
                and modifier.get("magnitudeCalculationType") == "setbycaller"
            ),
            None,
        )
        if metadata is None or first_set_by_caller is None:
            raise CatalogueError(
                "visible attachment effect had an invalid comparison-stat override: "
                + _effect_leaf(effect)
            )
        # UCoreGameplayEffect_OverrideComparisonStat makes the native
        # effect-to-comparable conversion emit one canonical combined row and
        # bypass its ordinary per-modifier fallback.  Aim Assist and Handling
        # use this path in the shipped data.
        return [(metadata, first_set_by_caller)]

    direct: dict[
        str,
        tuple[Mapping[str, Any], Mapping[str, Any]],
    ] = {}
    for modifier in modifiers:
        if not isinstance(modifier, Mapping):
            continue
        qualified = modifier.get("qualifiedAttribute")
        row = by_attribute.get(qualified) if isinstance(qualified, str) else None
        if row is not None and (
            not _uses_gun_mod_stat_ui(kind)
            or row["attribute"] not in _UI_FILTERED_ATTRIBUTES
        ):
            direct[row["attribute"]] = (row, modifier)
            continue

        # Synthetic fixtures and older evidence documents may not retain the
        # owner.  Accept an unqualified leaf only when it identifies exactly
        # one canonical row; never strip ADS/Primary/Secondary suffixes.
        unqualified = modifier.get("attribute")
        suffix_matches = [
            candidate
            for candidate in rows
            if isinstance(unqualified, str)
            and candidate["attribute"].rsplit(".", 1)[-1] == unqualified
            and (
                not _uses_gun_mod_stat_ui(kind)
                or candidate["attribute"] not in _UI_FILTERED_ATTRIBUTES
            )
        ]
        if len(suffix_matches) == 1:
            direct[suffix_matches[0]["attribute"]] = (
                suffix_matches[0],
                modifier,
            )

    # Unless explicit effect UIData overrides it above, an effect name is not
    # an alias for a combined weapon stat: Accuracy, for example, maps to its
    # exact MinimumSpread metadata row rather than Stats.Combined.Accuracy.
    return sorted(
        direct.values(),
        key=lambda item: (item[0]["sortOrder"], item[0]["attribute"]),
    )


def _normalized_effect_magnitude(effect: Mapping[str, Any]) -> float:
    magnitude = _finite_number(effect.get("configuredMagnitude"))
    if magnitude is None:
        raise CatalogueError(
            "visible attachment effect omitted its configured magnitude: "
            + _effect_leaf(effect)
        )
    # GetSingleGunModClassStats evaluates direct/no-curve effects with a power
    # scalar of one.  Under that exact client path, both interpreted and plain
    # magnitudes resolve to their configured value; the normalize flag only
    # participates when a valid curve-table row is present.
    return float(f"{magnitude:.7g}")


def _modifier_magnitude(
    effect: Mapping[str, Any],
    modifier: Mapping[str, Any],
) -> float:
    calculation_type = modifier.get("magnitudeCalculationType")
    if calculation_type == "setbycaller":
        return _normalized_effect_magnitude(effect)
    if calculation_type == "scalablefloat":
        scalable = modifier.get("scalableFloatMagnitude")
        if not isinstance(scalable, Mapping):
            raise CatalogueError(
                "visible scalable-float attachment modifier omitted its magnitude: "
                + _effect_leaf(effect)
            )
        if scalable.get("curveTablePackagePath") or scalable.get("curveRowName"):
            raise CatalogueError(
                "visible attachment modifier used an unsupported scalable-float curve: "
                + _effect_leaf(effect)
            )
        magnitude = _finite_number(scalable.get("value"))
        if magnitude is None:
            raise CatalogueError(
                "visible scalable-float attachment modifier had no finite magnitude: "
                + _effect_leaf(effect)
            )
        return float(f"{magnitude:.7g}")
    raise CatalogueError(
        "visible attachment modifier used an unsupported magnitude calculation: "
        + _effect_leaf(effect)
    )


def _comparison_value(
    magnitude: float,
    *,
    display_type: str,
    modifier_operation: str,
) -> tuple[float, str]:
    if modifier_operation == "Add":
        if display_type in {"Percent", "NegativePercent", "ZeroBasedPercent"}:
            return magnitude * 100.0, "Percent"
        if display_type in {"Integer", "Integer_Truncated"}:
            return magnitude, "Integer"
        if display_type == "Float":
            return magnitude, "Float"
        raise CatalogueError(
            f"unsupported additive attachment display type: {display_type}"
        )
    if modifier_operation in {
        "Divide",
        "JankyIndicatorStatMath",
        "Multiply",
    }:
        effective = magnitude if magnitude != 0.0 else 1.0
        # The client formats the distance from the neutral multiplier and uses
        # the factor's sign bit for the glyph; a positive factor below one is
        # therefore still rendered with ``+``.  Whether that numeric change is
        # desirable remains the independent metadata ``result`` direction.
        direction = -1.0 if effective < 0.0 else 1.0
        return direction * abs((effective - 1.0) * 100.0), "Percent"
    if modifier_operation in {"DivideShowNegative", "MultiplyShowNegative"}:
        effective = magnitude if magnitude != 0.0 else 1.0
        return (1.0 - effective) * 100.0, "Percent"
    raise CatalogueError(
        f"unsupported attachment comparable-stat operation: {modifier_operation}"
    )


def _clean_number(value: float) -> float:
    cleaned = round(value, 6)
    return 0.0 if cleaned == 0.0 else cleaned


def _compact_number(value: float) -> str:
    rounded = round(value, 6)
    if rounded == 0.0:
        rounded = 0.0
    return f"{rounded:.6f}".rstrip("0").rstrip(".")


def _ue_float_string(value: float) -> str:
    """Match Conv_FloatToString while avoiding binary-float noise."""

    compact = _compact_number(value)
    return compact if "." in compact else f"{compact}.0"


def _comparison_display_value(value: float, display_type: str) -> str:
    sign = "+" if value >= 0.0 else "-"
    absolute = abs(value)
    if display_type == "Percent":
        number = f"{absolute:.1f}"
        return f"{sign}{number}%"
    if display_type == "Integer":
        return f"{sign}{int(math.floor(absolute + 0.5))}"
    if display_type == "Float":
        return f"{sign}{absolute:.1f}"
    raise CatalogueError(f"unsupported attachment comparison display type: {display_type}")


def _is_heat_attachment(source: Mapping[str, Any]) -> bool:
    compatibility = source.get("compatibility")
    tags = compatibility.get("tags") if isinstance(compatibility, Mapping) else None
    return isinstance(tags, list) and any(
        isinstance(tag, str)
        and tag.startswith("Item.Attachment.Magazine.Heatsink")
        for tag in tags
    )


def _static_stat_label(
    source: Mapping[str, Any],
    *,
    attribute: str,
    kind: str,
    metadata_name: str,
) -> str:
    if kind == "trait":
        return _TRAIT_STAT_LABEL_OVERRIDES.get(attribute, metadata_name)
    if _is_heat_attachment(source):
        if attribute == "GunGameplayAttributes.AmmoPerMag":
            return "Heat Sink Capacity"
        if attribute == "GunGameplayAttributes.MaxAmmo":
            return "Max Heat Sinks"
    return _MOD_STAT_LABEL_OVERRIDES.get(attribute, metadata_name)


def _static_stat_lines(
    source: Mapping[str, Any],
    *,
    attribute_metadata: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    rows, by_attribute = _metadata_rows(attribute_metadata)
    effects = source.get("effects")
    if not isinstance(effects, list):
        return []
    kind = source.get("kind")

    # The trait panel suppresses computed stats only when its selected authored
    # Description field is non-empty. Conditional rows are an independent
    # section and do not suppress static effects (Mondo is a shipped example).
    if (
        source.get("kind") == "trait"
        and isinstance(source.get("description"), str)
        and source["description"].strip()
    ):
        return []

    comparable_by_attribute: dict[str, tuple[dict[str, Any], float]] = {}
    trait_rows: list[dict[str, Any]] = []
    for effect in effects:
        if not isinstance(effect, Mapping):
            continue
        flags = effect.get("serializedFlags")
        if not isinstance(flags, Mapping) or flags.get("bVisibleOnUI") is not True:
            continue
        for metadata, modifier in _modifier_rows_for_effect(
            effect,
            kind=str(kind),
            rows=rows,
            by_attribute=by_attribute,
        ):
            magnitude = _modifier_magnitude(effect, modifier)
            stat_value, display_type = _comparison_value(
                magnitude,
                display_type=metadata["displayType"],
                modifier_operation=metadata["modifierOperation"],
            )
            stat_value = _clean_number(stat_value)
            attribute = metadata["attribute"]
            stat_text = (
                _static_stat_label(
                    source,
                    attribute=attribute,
                    kind=str(kind),
                    metadata_name=metadata["displayName"],
                )
            )
            result = (
                _MOD_RESULT_OVERRIDES.get(attribute, metadata["result"])
                if _uses_gun_mod_stat_ui(str(kind))
                else metadata["result"]
            )
            display_value = _comparison_display_value(stat_value, display_type)
            line = {
                "attribute": attribute,
                "displayText": f"{display_value} {stat_text}",
                "displayType": display_type,
                "displayValue": display_value,
                "effectPackagePath": effect.get("effectPackagePath"),
                "result": result,
                "sortOrder": metadata["sortOrder"],
                "statText": stat_text,
                "statValue": stat_value,
            }
            if _uses_gun_mod_stat_ui(str(kind)):
                # The shared gun-mod widget turns comparable rows into a map
                # keyed by exact attribute before applying its visual
                # overrides. A later effect for the same attribute therefore
                # replaces the earlier row.
                comparable_by_attribute[attribute] = (line, stat_value)
            else:
                # PopulateWithGunPerk consumes the native comparison list
                # directly; it does not run the mod widget's map transform.
                trait_rows.append(line)

    if _uses_gun_mod_stat_ui(str(kind)):
        fire_rate = comparable_by_attribute.get(
            "GunGameplayAttributes.TimeBetweenShots"
        )
        fire_rate_limit = comparable_by_attribute.get(
            "GunGameplayAttributes.TimeBetweenShotsLimit"
        )
        if (
            fire_rate is not None
            and fire_rate_limit is not None
            and fire_rate[1] == fire_rate_limit[1]
        ):
            del comparable_by_attribute[
                "GunGameplayAttributes.TimeBetweenShotsLimit"
            ]

    output = (
        [line for line, _ in comparable_by_attribute.values()]
        if _uses_gun_mod_stat_ui(str(kind))
        else trait_rows
    )
    output.sort(
        key=lambda line: (
            line["sortOrder"],
            line["attribute"],
            line["effectPackagePath"] or "",
        )
    )
    return output


def _conditional_display_text(line: Mapping[str, Any]) -> str | None:
    stat_text = line.get("statText")
    if not isinstance(stat_text, str) or not stat_text.strip():
        return None
    display_type = line.get("displayType")
    if display_type == "None":
        return stat_text
    value = _finite_number(line.get("statValue"))
    if value is None:
        raise CatalogueError("conditional attachment stat line had no finite value")
    sign = "+" if value >= 0.0 else "-"
    absolute = abs(value)
    if display_type == "Float":
        display_value = f"{sign}{_ue_float_string(absolute)}"
    elif display_type == "Integer":
        display_value = f"{sign}{int(math.floor(absolute + 0.5))}"
    elif display_type == "Percent":
        display_value = f"{sign}{int(math.floor(absolute + 0.5))}%"
    else:
        raise CatalogueError(
            f"conditional attachment stat line used unsupported display type: {display_type}"
        )
    return f"{display_value} {stat_text}"


def _conditional_sections(source: Mapping[str, Any]) -> list[str]:
    groups = source.get("conditionalDescriptions")
    if not isinstance(groups, list):
        return []
    sections: list[str] = []
    for group in groups:
        if not isinstance(group, Mapping):
            raise CatalogueError("conditional attachment description group was malformed")
        parts: list[str] = []
        condition = group.get("conditionText")
        has_condition = isinstance(condition, str) and bool(condition.strip())
        if has_condition:
            parts.append(condition)
        lines = group.get("statLines")
        if not isinstance(lines, list):
            raise CatalogueError("conditional attachment description lines were malformed")
        for line in lines:
            if not isinstance(line, Mapping):
                continue
            display = _conditional_display_text(line)
            if display is None:
                continue
            parts.append(
                ATTACHMENT_DESCRIPTION_CONDITIONAL_STAT_INDENT + display
                if has_condition
                else display
            )
        if parts:
            sections.append(ATTACHMENT_DESCRIPTION_LINE_SEPARATOR.join(parts))
    return sections


def augment_description_panel(source: Mapping[str, Any]) -> dict[str, Any]:
    """Return PopulateWithGunMod's three independent authored text regions."""

    return {
        "description": source.get("description"),
        "descriptionSecondary": source.get("flavorText"),
        "descriptionUpper": source.get("descriptionShort"),
    }


def compose_attachment_description(
    source: Mapping[str, Any],
    *,
    static_lines: Sequence[Mapping[str, Any]],
) -> str | None:
    """Compose the simple-client text view from already-normalized sections."""

    sections: list[str] = []
    authored_values = (
        augment_description_panel(source).values()
        if source.get("kind") == "augment"
        else (source.get("description"),)
    )
    sections.extend(
        value
        for value in authored_values
        if isinstance(value, str) and value.strip()
    )
    if static_lines:
        if any(
            not isinstance(line, Mapping)
            or not isinstance(line.get("displayText"), str)
            or not line["displayText"].strip()
            for line in static_lines
        ):
            raise CatalogueError("attachment static-stat display text was malformed")
        sections.append(
            ATTACHMENT_DESCRIPTION_LINE_SEPARATOR.join(
                line["displayText"] for line in static_lines
            )
        )
    sections.extend(_conditional_sections(source))
    return ATTACHMENT_DESCRIPTION_SECTION_SEPARATOR.join(sections) if sections else None


def project_attachment_description(
    source: Mapping[str, Any],
    *,
    attribute_metadata: Mapping[str, Any] | None,
) -> tuple[str | None, list[dict[str, Any]]]:
    """Return the ready-to-render description and structured static stat rows."""

    if source.get("kind") not in {"augment", "mod", "trait"}:
        raise CatalogueError(
            "attachment description projection requires an augment, mod, or trait"
        )
    static_lines = _static_stat_lines(source, attribute_metadata=attribute_metadata)
    return (
        compose_attachment_description(source, static_lines=static_lines),
        static_lines,
    )


__all__ = [
    "ATTACHMENT_DESCRIPTION_CONDITIONAL_STAT_INDENT",
    "ATTACHMENT_DESCRIPTION_LINE_SEPARATOR",
    "ATTACHMENT_DESCRIPTION_SECTION_SEPARATOR",
    "AUGMENT_DESCRIPTION_PANEL_ORDER",
    "augment_description_panel",
    "compose_attachment_description",
    "project_attachment_description",
]
