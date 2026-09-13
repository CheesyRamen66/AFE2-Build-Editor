# Damage calculation

Companion to [`penetration.md`](penetration.md): where that document covers
whether a hit gets through, this one covers how much it does once it lands.
Same source basis (extracted catalogue, standalone-pak design CSVs, static
disassembly of build `25057376`) and the same confidence grading:

- **Confirmed** — read directly from a parsed asset, or from disassembled
  control flow with no interpretive gap.
- **Inferred** — a structural or numeric pattern strong enough to act on, but
  not mechanically traced end to end.
- **Unknown** — flagged explicitly rather than guessed at.

The short answer to "does the game use damage buckets": **yes, in three
distinct, unrelated ways** — a named three-zone range-falloff curve, a
small discrete palette of elemental resistance values authored onto a
continuous attribute, and (for at least Hardcore) named level-scaling curve
tables. None of them are "buckets" in the sense of one unified system; they're
three separate authored mechanics that each happen to be bucket-shaped. Each
is covered below, along with the parts of the formula that are plain
continuous multiplication.

## The damage attribute is really three attributes

`DealsDamageAttributes` splits a hit's damage into three independently
tracked sub-attributes, each with its own stopping-power counterpart:

| Damage bucket | Attribute | Stopping-power counterpart |
|---|---|---|
| Direct hit | `DamageMagnitude_Primary` | `StoppingPower` |
| Explosive/splash | `DamageMagnitude_Secondary` | `StoppingPower_Secondary` |
| Damage-over-time | `DamagePerSecond` | `StoppingPowerPerSecond` |

**Confirmed:** all six are independent GAS attributes, each aggregated
through its own channel stack exactly like `Penetration` in the companion
document. `Avo_Weapon_Damage` (the effect behind every "+X% Damage" stat
line) and `Avo_Attachment_Mag_Large_ArmorPiercing_Gun_GE` (a representative
conditional attachment effect) both drive all three Primary/Secondary/DPS
sub-attributes **Multiplicative on Channel1** — the same channel every
ordinary Damage and StoppingPower attachment modifier uses, confirmed by
direct inspection of the effect assets. So the ordinary case (stacking two or
three "+X% Damage" attachments) is exactly the arithmetic the catalogue
displays: `1 + Σ(magnitude − 1)`, same bias-sum rule as every other
multiplicative attribute in the game.

**Confirmed, lower confidence on scope:** two additional effects exist —
`Avo_Weapon_Damage_Secondary_ToPrimary` and
`Avo_Weapon_StoppingPower_Secondary_ToPrimary` — that **Override** the
Secondary attribute with a snapshotted copy of the Primary/StoppingPower
value (`MagnitudeCalculationType: AttributeBased`, capturing
`DamageMagnitude_Primary` / `StoppingPower` from the target at apply time).
These also run on **Channel1**, the same channel as ordinary Secondary
modifiers — not a later channel — so this is not the same kind of guaranteed
override as the Penetration trap in the companion doc. Where one of these
"sync" effects is active, GAS's within-channel precedence (Override beats
Multiplicative) means it wins over any attachment's Secondary bonus running
in that same channel. **Unknown:** which weapons carry this sync effect and
under what condition — it reads as a "this weapon has no real secondary
damage type, so mirror Primary" convenience for non-explosive guns, but that
wiring wasn't traced back to specific `GunDef` assets.

## Range falloff: an authored three-zone bucket system

Every weapon's `Design/ChassisDefs` sheet carries a small, consistent set of
distance attributes, and their catalogue display names spell out the
structure directly:

| Attribute | Display name | Role |
|---|---|---|
| `NearDamageDistance` | Near Distance | Full damage out to here |
| `FarDamageDistance` | Effective Range | First falloff breakpoint |
| `FarDamageDistanceMultiplier` | Falloff Multiplier | Damage multiplier applied at/beyond Effective Range |
| `VeryFarDamageDistance` | Ineffective Range | Second falloff breakpoint |
| `VeryFarDamageDistanceMultiplier` | Max Falloff Multiplier | Damage multiplier applied at/beyond Ineffective Range |
| `Range` | Maximum Range | Hard cutoff |
| `RangeDamageDistanceMultiplier` | Range Falloff Multiplier | Present on every weapon checked; role unconfirmed (see below) |

**Confirmed:** three named zones (Near / Effective / Ineffective) plus a hard
Maximum Range cap is the authored shape, straight from the metadata table's
own display names — this isn't inference, the game's own UI vocabulary calls
these zones out.

**Confirmed, four representative weapons (all distances in game units):**

| Weapon | Near | Effective (Far) | Ineffective (VeryFar) | Max Range | Falloff× | Max Falloff× |
|---|---|---|---|---|---|---|
| SMB-94 Zephyr | 2,300 | 4,600 | 5,000 | 10,000 | 0.70 | 0.20 |
| L33 Pike | 6,000 | 8,000 | 12,000 | 20,000 | 0.967 | 0.70 |
| M10 Auto Pistol | 1,200 | 2,600 | 3,600 | 20,000 | 0.75 | 0.35 |
| M37A3 Pump Shotgun | 700 | 1,400 | 4,800 | 6,000 | 0.50 | 0.25 |

`RangeDamageDistanceMultiplier` was `0` on all four sampled weapons.
**Unknown:** whether that's "damage drops to zero beyond Maximum Range" (a
fourth, harshest bucket) or an unrelated interpolation parameter that simply
defaults to 0 — this pass didn't locate the falloff-evaluation code (same
Blueprint-graph wall as the penetration threshold check), and every sample
happened to share the same value, so no contrast case turned up either.
**Unknown:** whether the transition between zones is a hard step (full damage
right up to Effective Range, then an instant drop to the Falloff multiplier)
or a smooth interpolation across the zone boundary — the data only proves the
breakpoints and endpoint multipliers exist, not the curve shape between them.

**Confirmed:** these seven attributes are excluded from the attachment
comparison UI (`_UI_FILTERED_ATTRIBUTES` in
[`attachment_descriptions.py`](../src/afe2_catalogue/attachment_descriptions.py)).
Attachments that affect range instead surface a separate, friendlier
"+X% Weapon Range" comparable stat line (seen on several barrels and optics)
— **inferred** to be a synthesized view over one or more of the raw
distance attributes above, though the exact mapping wasn't traced.

## Elemental resistance: a continuous attribute, an authored discrete palette

Each `*Damage_PercentResistance` row (Basic, Thermal, Cryo, Electric,
Piercing, Neurotoxin, Acid, Morphic — matching the `EEndeavorDamageType`
enum, which also defines `Melee` and `Lancer` entries with no corresponding
resistance row found on any enemy) is a plain float attribute. But **across
every value on every enemy in the current roster, the authored numbers
cluster overwhelmingly on a small palette** rather than spreading
continuously:

```
0.0 (baseline)                          — 605 of 1,112 distinct values recorded
±0.05, ±0.10, ±0.15, ±0.20, ±0.25, ±0.30, ±0.35, ±0.40, ±0.50   — the rest, in round 5-point steps
1.0 (full immunity)                     — 18
```

(counting each distinct value an enemy's row takes — a row that's flat across
its whole level range counts once; a row that steps through several values
across its levels, like the two below, counts once per distinct value it
takes. 1,112 is the total across all resistance rows on all 107
current-generation enemies with elemental data, eight elements each.)

A negative value increases the damage the enemy takes (a weakness); a
positive value reduces it (a resistance); `1.0` removes it outright. This is
the basis for `weakTo` / `immuneTo` in `enemy-assets.json`. A handful of
non-round outliers exist (`-0.65`, `-0.575`, `0.175`, `0.33`, `0.9`, …) — rare
enough (1–3 occurrences each) to read as one-off boss tuning rather than a
break in the underlying palette.

**Confirmed and worth flagging directly against the companion document's
level-invariance claim for penetration:** elemental resistance is **not**
always flat across an enemy's level range the way the penetration triplet
is. Two Hyperdyne minibosses ramp their Thermal and Electric resistance in
discrete level bands:

| Element | Levels 1–4 | 5–8 | 9–12 | 13–40 |
|---|---|---|---|---|
| Thermal | +40% | +60% | +75% | +90% |
| Cryo | −15% | −5% | 0% | 0% |
| Electric | −35% | −35% | −35% | −40% |

(identical on both IGNITER and BOMBARDIER — a matched pair of 40-level
Hyperdyne sheets, per the level-count table in the companion document). Read
literally: both get dramatically more thermal-resistant as they level,
capping at 90% resistance, while staying persistently weak to Electric
throughout and losing an early, mild Cryo weakness by level 9. Whether other
enemies also ramp resistance by level wasn't exhaustively checked beyond
confirming these two examples and that most rows are constant.

## Crit, weak points, and the multipliers around a hit

`DealsDamageAttributes.CriticalChance` (display: **Critical Chance**,
`ZeroBasedPercent`, Additive) sits at **0 base on every weapon checked** —
crit is entirely attachment/trait-driven, additive onto nothing.
`DealsDamageAttributes.CriticalMultiplier` (display: **Critical Multiplier**,
Additive) is typically **1.5** base. `GunGameplayAttributes.HeadshotMultiplier`
(**Weak Point DMG Bonus**) and `.WeakpointStoppingPowerMultiplier` (**Weak
Point SP Bonus**)
are the separate weak-point multipliers used throughout the companion
document's build math, both Additive, both starting at 1.0 on most weapons
(the Pike is a notable exception at a base 1.5).

**Inferred, not independently re-derived here:** the practical model used
successfully throughout the build-crafting conversation this pair of
documents grew out of — expected damage per shot ≈ `base × (1 + critChance ×
(critMultiplier − 1)) × headshotMultiplier` on a weak-point hit — is a
standard expected-value treatment of an additive crit-chance/multiplier pair.
It wasn't re-verified against the hit-resolution code in this pass.
**Unknown:** how crit is rolled on multi-projectile weapons — once per
trigger-pull, or once per pellet/projectile (relevant for the M37A3 Pump
Shotgun's 12 pellets, among others).

## Armor vs. health: two named pools, order unconfirmed

`TakesDamageAttributes.ShieldMax` displays as **"Maximum Armor"** in the
attribute metadata — not a recharging energy shield in the usual sense, at
least on enemies checked: the Xenomorph Queen's `ShieldRechargeValue` and
`ShieldRechargePeriod` are both `0`, so her 10,000-point "Shield" pool does
not regenerate and reads more like a second, non-regenerating health bar
(armor plating) than a rechargeable shield. `HealthMax` displays as
**"Maximum Health"**. Both pools exist as fully independent attributes with
their own regen fields (`HealthRegenPeriod/Value/Delay`,
`ShieldRechargePeriod/Value/Delay`) on both players and enemies.

The naming is settled by the designers' own glossary, quoted in the next
section: `ShieldMax` is documented in-house as "The maximum Armor of a
critter". Per-shot flags confirm it is a genuinely separate pool —
`FWeaponTrace` carries `bShieldDamage` and `bShieldBreak` as distinct booleans
alongside the health-side fields.

**Unknown:** the depletion order and interaction between the two pools —
whether Armor absorbs all damage before Health starts taking any, whether
some damage types or hit locations bypass Armor, or whether it's a
percentage split. Not traced in this pass.

## The shipped designer documentation

`AFE2/Content/Design/ClassDefs/EnemiesBalanceMaster.xlsx` ships inside
`pakchunk0` — the designers' own balance workbook, 35 sheets, left in the
cooked build. Two of them are directly authoritative for this document.

**`AttributeReference`** is an in-house glossary of the `ClassDefs` rows.
Quoting it verbatim (*Confirmed*):

| Row | Designers' description |
|---|---|
| `TakesDamageAttributes.HealthMax` | "The maximum Health of a critter" |
| `TakesDamageAttributes.ShieldMax` | **"The maximum Armor of a critter"** |
| `…<Element>Damage_PercentResistance` | "How much less damage a critter takes. (Ex. 0.5 = halves damage taken, 1.0 = critter is immune to damage.)" |
| `TakesDamageAttributes.HealthRegenDelay` | "How long after taking damage does regen start ticking." |
| `TakesDamageAttributes.HealthRegenPeriod` | "How often RegenValue is triggered (Ex. '0.1' will trigger 10 times in a 1 second window.)" |
| `DealsDamageAttributes.GlobalDamageStrength` | "Increases all damage dealt by the critter. Generally defaulted to 1.0" |
| `DealsDamageAttributes.DamageMagnitude_Secondary` | "Rarely used for critters … for secondary attacks, such as grenades, if so desired (not recommended.)" |

This settles the shield-versus-armor naming outright: `ShieldMax` **is** the
armor pool, and the percent-resistance convention (`1.0` = immune) is the
designers' own wording, not an inference from the value distribution.

Worth noting what the sheet does *not* document: `PenetrationResistance`,
`PenetrationResistance_Armor`, `PenetrationResistanceWeakpointMultiplier` and
`WeakpointMultiplier` are all listed as rows with their description cells left
**blank**. The penetration model was undocumented internally too.

**`StandardsOverview`** records the derivation the enemy numbers were built
from — a base value multiplied by faction, class, role and trait modifiers
(Xeno ×1.2 health, Elite ×6, Tank trait ×3, and so on). It is AFE1-era
derivation math and does not match shipped AFE2 values, so it is useful for
understanding *intent*, not for computing current numbers. Its one mechanically
interesting disclosure is a **reaction threshold** ladder — Light / Medium /
Heavy, at ×0.5 / ×1 / ×2 of a per-enemy base — which is the stagger tier
system that `StoppingPower` feeds.

## Per-hit multipliers and the shape of a resolved hit

**Confirmed.** The binary's reflection data exposes the per-hit scalar set
through the property table of `StoppingPowerCalc`:

```
PenetrationPercent
DistanceDamageMultiplier
ChargeStoppingPowerBonus
bWeakPointHit
WeakpointStoppingPowerMultiplier
WeakpointStoppingPowerBaseMult
StoppingPowerResistance
bCrit
GlobalMultiplier
```

`DistanceDamageMultiplier` is the range-falloff factor from the three-zone
system above, and `PenetrationPercent` is the penetration result expressed as a
fraction — see [`penetration.md`](penetration.md), where the consequence is
that penetration scales a hit rather than gating it outright. Weak points
carry *separate* stopping-power multipliers (`WeakpointStoppingPowerMultiplier`,
`WeakpointStoppingPowerBaseMult`) from their damage multiplier
(`WeakpointMultiplier`), so a head hit's stagger contribution and its damage
contribution are computed independently.

**Confirmed.** The outcome of a resolved hit is recorded across three structs:

| Struct | Fields |
|---|---|
| `FWeaponTrace` | `bHitEnemy`, `bHitDead`, `bHitMovableActor`, `bHitCoreCharacter`, `bShieldDamage`, `bShieldBreak`, `bHitSpecialCritPoint`, `bPenetratingShot` |
| `FWeaponTrace_ForRPC` | `bDealtAnyDamage`, `bDeflected` |
| damage-number widget | `bMyDamage`, `bPenetrated` |

`bShieldDamage` and `bShieldBreak` being distinct per-shot flags confirms armor
is tracked as its own depletable pool with its own break event, alongside — not
merged into — health.

**Confirmed.** The damage-event tag family names the graded outcomes:
`DamageEvent.Blocked`, `DamageEvent.PartiallyBlocked`, `DamageEvent.Deflected`,
plus `DamageEvent.Crit`, `DamageEvent.Headshot`, `DamageEvent.AOE`,
`DamageEvent.FriendlyFire`, one tag per element (`Basic`, `Thermal`, `Cryo`,
`Electric`, `Neurotoxin`, `Acid`, `Piercing`, `Morphic`, `Lancer`, `Melee`) and
a parallel `DamageEvent.StoppingPower.<Element>` set. Stopping power is tagged
per element exactly as damage is, i.e. it travels through the same pipeline as
a second, parallel quantity rather than being derived from final damage.

**Unknown.** None of these tags or fields has a single Blueprint consumer, so
the arithmetic combining them remains native-only. The depletion order between
armor and health in particular is still untraced.


## Level- and difficulty-based scaling curves

`AFE2/Content/Design/AttributeTables/Common_PowerTables` is a `CurveTable`
asset (`RCIM_Linear` interpolation, `RCCE_Constant` extrapolation beyond the
endpoints) whose row names are, **confirmed** from the asset's own name
table:

- `CharacterLevel_GunDamage`
- `CharacterLevel_AbilityDamage`
- `CritterLevel_Hcscaling_Dmg`
- `CritterLevel_Hcscaling_HP`

This is a genuine, named, level-indexed damage-scaling system — the first
two almost certainly scale player gun/ability damage up with character level
(the standard way a live-service shooter keeps damage relevant as enemy HP
scales), and the last two are explicitly named for Hardcore critter
scaling, tying directly into `HardcoreTierScalingStartsAtLevel = 3` from
`DefaultGame.ini` (see the companion document's difficulty section).

**Unknown:** the actual keyframe values. `UCurveTable` uses a custom binary
row format (not a plain UProperty list), and the current semantic-reader
pipeline — built for reading ordinary Blueprint/GameplayEffect assets —
doesn't decode it; this would need a dedicated CurveTable parser added to
the extractor. This is the single most valuable near-term addition to make
the level-scaling half of both documents concrete rather than structural.

**Related but unconfirmed:** `DefaultGame.ini` also sets
`CritterExplosionDamagePercents[0..5] = 0.0, 0.33, 0.66, 1.0, 1.0, 1.0` under
`[/Script/Endeavor.CoreCritterCharacterComponent]` — a six-entry array, the
same length as the six difficulty tiers, but its name and flat plateau at the
top three indices (rather than continuing to climb through Hardcore) don't
confidently support a difficulty-index reading. Recorded here as a discrete
lookup table worth revisiting, not asserted as a difficulty scalar.

## Source pointers

- Weapon range-falloff and base stats: `Design/ChassisDefs/VenusCSV_<Gun>.csv`,
  not currently extracted by the catalogue pipeline as structured data (read
  directly via `repak get` for this document).
- Damage/StoppingPower GE channel and operation data: same gap noted in the
  companion document — read from raw semantic-reader output, not from
  `semantic-assets.json`'s normalized `effectDefinitions` (which captures
  `operationRaw` but not `Channel`).
- Elemental resistance values and per-level series:
  [`src/afe2_catalogue/enemies.py`](../src/afe2_catalogue/enemies.py),
  `enemy-assets.json` → `records[].stats.elemental`.
- `Common_PowerTables` / `CombatRatingTables`: not decoded by any existing
  extractor stage; `UCurveTable`/`UDataTable` support would be new work.
- Designer glossary and balance derivation:
  `AFE2/Content/Design/ClassDefs/EnemiesBalanceMaster.xlsx` inside `pakchunk0`
  (sheets `AttributeReference` and `StandardsOverview`). Read with `repak
  unpack -i AFE2/Content/Design/ClassDefs`; it is a plain `.xlsx`, readable
  without any UE tooling. Not consumed by the extractor.
- Per-hit multiplier and hit-outcome field names were read from the shipping
  executable's reflection string tables, not from content.
