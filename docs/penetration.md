# Penetration, armor, and penetration resistance

This is a mechanics reference for **Aliens: Fireteam Elite 2**'s bullet-penetration
system, compiled from the extracted catalogue, the standalone-pak design CSVs
(`Design/ClassDefs`), and static disassembly of the shipping executable
(build `25057376`, `AFE2-Win64-Shipping.exe`,
SHA-256 `e604af0c56d33ec2d5f75429df563892d434db390437332b6bce993c35819da1`).

It is written for the eventual build-crafting database: this document covers
the mechanic, [`damage.md`](damage.md) covers how much a hit that gets through
actually does, and [`enemy-assets.json`](../src/afe2_catalogue/enemies.py)
covers the per-creature data that plugs into both. Every claim below is
graded:

- **Confirmed** — read directly from a parsed asset, or from disassembled
  control flow with no interpretive gap.
- **Inferred** — a structural or numeric coincidence strong enough to act on,
  but not mechanically traced end to end.
- **Unknown** — flagged explicitly rather than guessed at.

Two disassembly limits shape what follows. Ability and damage-resolution logic
in this game is largely authored as Blueprint graphs, and the shipping binary
only contains the *compiled bytecode* for those graphs, not recoverable
pseudocode — a native `objdump` pass sees the reflection plumbing around a
Blueprint function (its exec thunk, its registration entry) but not what the
graph itself does. Several of the functions below present exactly that shape:
present in the reflection tables, never called directly from native code, and
therefore Blueprint-graph-only as far as static analysis can tell.

## The three numbers

Every enemy that has combat-relevant defense carries three constant attributes,
sourced from `AFE2/Content/Design/ClassDefs/<Sheet>.csv` via each blueprint's
`AttributeCSVFileOverride`:

| Attribute | What it is |
|---|---|
| `TakesDamageAttributes.PenetrationResistance` | How much attacker `Penetration` a hit needs to pass through this enemy rather than stop in it. Varies a lot by enemy: 0.5 (Facehugger) to 8 (the Queen). |
| `TakesDamageAttributes.PenetrationResistance_Armor` | A second, mostly-shared threshold — **Confirmed constant at exactly `4.0` on 37 of the 44 AFE2-generation enemies with the row.** The three exceptions are the Exploder pair (3.0) and Chestburster/Facehugger (1.0). |
| `TakesDamageAttributes.PenetrationResistanceWeakpointMultiplier` | **Confirmed constant at exactly `0.5`** on every one of those same 41 enemies. |

**Confirmed:** all three rows are flat across every level column on every
enemy that has them — `enemy-assets.json` records each as `"status":
"constant"`, never `"byLevel"`. This holds regardless of how many level
columns that enemy's sheet actually has: sheet length is **not** uniform
across the roster (it's 12, 20, 40, or 60 depending on the enemy — the Queen's
current sheet happens to be 20, but e.g. BULWARK and BOMBARDIER run to 40, and
several legacy-generation sheets run to 60). Penetration breakpoints do not
move with enemy level or (as far as the data shows — see the difficulty
section below) with mission difficulty. A given enemy's armor gate is the
same number at its lowest authored level and its highest.

**Confirmed absent:** the legacy (previous-title) `Critter_*` roster under
`/Character/Critters/` carries none of these three rows at all — only the
current `/Character/VenusEnemies/` generation is wired to them. `generation:
"legacy"` in the enemy document is the marker.

Full current-generation table (`PenetrationResistance_Armor` /
`WeakpointMultiplier` omitted from rows where both equal 4.0 / 0.5, which is
the overwhelming majority):

| Enemy | Rank | Faction | PenetrationResistance | Armor | Weakpoint× |
|---|---|---|---|---|---|
| Xenomorph Queen | Elite | Xenomorphs | 8.0 | 4.0 | 0.5 |
| BULWARK | Elite | Hyperdyne | 7.0 | 4.0 | 0.5 |
| Xenomorph Warden | Elite | Xenomorphs | 7.0 | 4.0 | 0.5 |
| BOMBARDIER | Elite | Hyperdyne | 6.0 | 4.0 | 0.5 |
| Heavy Synth | Elite | — | 6.0 | 4.0 | 0.5 |
| IGNITER | Elite | Hyperdyne | 6.0 | 4.0 | 0.5 |
| Xenomorph Praetorian | Elite | Xenomorphs | 6.0 | 4.0 | 0.5 |
| Pathogen Engineer Hybrid | Elite | Pathogen | 5.0 | 4.0 | 0.5 |
| Xenomorph Crusher | Elite | Xenomorphs | 5.0 | 4.0 | 0.5 |
| Xenomorph Warrior | Elite | Xenomorphs | 4.5 | 4.0 | 0.5 |
| Incinerator Synth | Elite | — | 4.0 | 4.0 | 0.5 |
| Pathogen Brute | Elite | Pathogen | 4.0 | 4.0 | 0.5 |
| Xenomorph Drone | — | Xenomorphs | 4.0 | 4.0 | 0.5 |
| —Turret / Gun Turret / Rocket Turret | — | Hyperdyne | 4.0 | 4.0 | 0.5 |
| PEACEKEEPER | Fodder | Hyperdyne | 4.0 | 4.0 | 0.5 |
| HUNTSMAN, SPIDER, Pathogen Harbinger | — | Hyperdyne / Pathogen | 3.0 | 4.0 | 0.5 |
| Xenomorph Prowler, Siren, Spitter, Wraith | Fodder / — | Xenomorphs | 3.0 | 4.0 | 0.5 |
| Xeno Egg / Egg Clutch / Egg Empty | Fodder | Xenomorphs | 3.0 | *none* | *none* |
| Trooper Synth | — | — | 2.5 | 4.0 | 0.5 |
| Enforcer Synth, Jammer Synth, Sniper Synth | Fodder / — | — | 2.0 | 4.0 | 0.5 |
| Pathogen Blight, Xenomorph Burster | — / Fodder | Pathogen / Xenomorphs | 2.0 | 4.0 | 0.5 |
| Pathogen Gasbag, Xenomorph Runner | — / Fodder | Pathogen / Xenomorphs | 1.5 | 4.0 | 0.5 |
| Royal Xenomorph Exploder, Xenomorph Exploder | Standard | Xenomorphs | 1.5 | **3.0** | 0.5 |
| Containment Synth, Synth Detonator, Wey Yu Worker, Mutated Runner | Fodder / — | mixed | 1.0 | 4.0 | 0.5 |
| Pathogen Popper | Fodder | Pathogen | 0.5 | 4.0 | 0.5 |
| Xenomorph Chestburster, Facehugger | Fodder | Xenomorphs | 0.5 | **1.0** | 0.5 |

## Weapon-side: the `Penetration` attribute

Every gun has a base `DealsDamageAttributes.Penetration` in its
`Design/ChassisDefs/VenusCSV_<Gun>.csv`. A representative sample:

| Weapon | Subtype | Base Penetration |
|---|---|---|
| SMB-94 Zephyr, M10 Auto Pistol | heavy MG, machine pistol | 1 |
| M39A2 Submachine Gun, M37A3 Pump Shotgun | SMG, shotgun | 2 |
| M41A2 Pulse Rifle | assault | 3 |
| HNT-1 El Alamein, M42A2 Scout Rifle | DMR | 4 |
| L33 Pike, Type 102 Directed Force | sniper | 5 |

**Confirmed:** three Gameplay Effects touch this attribute, and — this is the
load-bearing fact for anyone stacking attachments — **they run on two
different evaluation channels**, read directly from each GE's serialized
`FGameplayModifierInfo`:

| Effect | Used by | Op | Magnitude | Channel |
|---|---|---|---|---|
| `Avo_Weapon_Penetration` | every "±N Bullet Penetration" line on augments/mods (Trenchant Plasma, Micro Flechettes, Smart-Aim's −0.5, Alloyed Magazine, …) | Additive | SetByCaller, one value per attachment | **Channel1** |
| `Avo_Mastery_F44AA_Gun_GE` | the F44AA trait's conditional "+2 while stationary" | Additive | ScalableFloat 2.0 | **Channel1** |
| `Avo_Weapon_Penetration_Set` | High Explosive Rounds (all variants) | **Override** | ScalableFloat **0.0** | **Channel9** |

Unreal's `FAggregator` evaluates evaluation channels in ascending order,
threading each channel's result into the next as its base. Every additive
penetration source in the game shares Channel1, so they sum normally — that
part matches the catalogue's displayed math (base + Σ attachments). But
Channel9 is evaluated *after* Channel1, and an `Override` modifier on any
channel discards whatever that channel's base carries in and substitutes its
own value outright.

**Confirmed consequence:** slotting **High Explosive Rounds alongside any
other penetration source is not additive with it — it is a hard reset to
zero.** The catalogue's own display text for that mod (`+0.0 Bullet
Penetration`) undersells this badly; it reads as a no-op, but it actually
overrides and discards +3 from Trenchant, +3 from Micro Flechettes, whatever
the base weapon carries, all of it. Never pair High Explosive Rounds with a
build that depends on a penetration floor.

*(The channel-chaining behavior itself — later channels overriding earlier
ones — is standard Unreal Gameplay Ability System semantics, not something
re-derived from this binary; what's confirmed from the binary is which
channel each of this game's three penetration GEs actually uses.)*

## The `4.0` constant — solved: it is a UI label threshold

**This section previously carried an inference that the 4.0 constant was an
armour-damage gate. That was wrong.** The consuming code has now been located
and decompiled, and it is user-interface code. The record below is what the
game actually does.

The compiled binary exports a Blueprint-callable `GetPenetrationThreshold` on
`GunGameplayAttributes`. Its entire native body:

```asm
mov  DWORD PTR [r8], 0x40800000   ; *out = 4.0f
ret
```

**Confirmed:** it unconditionally returns `4.0`, ignoring its context
argument. It has **zero direct native call sites**. Searching every Blueprint
in the shipped game for the name finds exactly **one** consumer:

`/Game/UI/Blueprints/HUD/BPFL_ElementalUtilities` → function
**`Get Damage Type From Stats Block`**

Decompiling that function's K2 bytecode gives the whole story. It loops over a
weapon's stat-comparison list and, for each entry, evaluates:

```
AbilitySystemBlueprintLibrary::EqualEqual_GameplayAttributeGameplayAttribute(
        entry.RowData.Attribute,
        /Script/Endeavor.DealsDamageAttributes:Penetration )
  AND
KismetMathLibrary::GreaterEqual_FloatFloat(
        <entry value>,
        GunGameplayAttributes::GetPenetrationThreshold() )   // 4.0
```

and when both are true:

```
KismetArrayLibrary::Array_Add( LocalDamageTypes, ByteConst 6 )
```

`EEndeavorDamageType` member strings sit at exact 32-byte intervals in the
binary, giving unambiguous ordering: `Basic=0, Thermal=1, Cryo=2, Electric=3,
Neurotoxin=4, Acid=5, `**`Piercing=6`**`, Morphic=7, Melee=8, Lancer=9`. That
ordering independently matches the order the elemental resistance rows appear
in every enemy's ClassDefs sheet.

**So: a weapon whose Penetration stat is ≥ 4 gets the "Piercing" damage-type
badge shown on its stats panel. That is the entire function of the 4.0
constant.** It is never consulted during damage resolution, it is never
compared against any enemy attribute, and it is not an armour gate.

The numeric convergence noted earlier is still real and still looks
deliberate — `PenetrationResistance_Armor` is 4.0 on 37 of 44 enemies, and the
UI calls a gun "Piercing" at exactly that number — but it is a *design*
convergence, not a shared code path. The UI threshold tells you the designers
consider 4 the meaningful armour-defeating number; it does not prove what the
damage code does with it.

## What actually modifies enemy penetration resistance

Three separate systems write to these attributes, each on its own evaluation
channel (base CSV value arrives on Channel0):

| Effect | Attribute(s) | Op | Channel | Applied to |
|---|---|---|---|---|
| `GE_CasualStandardPenetrationResistance` | `PenetrationResistance` | **Override → 1.0** | Channel3 | **the player / AI companions** |
| `Avo_StatusEffect_PlayerAbility_PenetrationDebuff` | `PenetrationResistance` + `_Armor` | Multiplicative (SetByCaller) | Channel3 | enemies (player debuff ability) |
| `GE_WeakEnemyArmor` (mission card) | `PenetrationResistance` + `_Armor` | Additive **−3.5** | Channel4 | enemies |

**Confirmed — and this corrects a natural misreading of the first row:**
`GE_CasualStandardPenetrationResistance` is applied with
`BP_ApplyGameplayEffectToSelf` from `DefaultPlayerCharacter`'s
`DifficultySwitchFunction`, which is a switch on the difficulty enum:

```
difficulty == 0 (Easy/Casual) or 1 (Normal/Standard) -> GE_CasualStandardPenetrationResistance
difficulty == 2 (Hard/Intense)                       -> GE_ReviveSpeed_Hard
difficulty == 3 (Extreme)                            -> GE_ReviveSpeed_Extreme
difficulty == 4 (Insane)                             -> GE_ReviveSpeed_Insane
```

It raises **the player's own** penetration resistance to 1.0 on the two
lowest difficulties — plausibly so an enemy bullet stops on the first player
rather than passing through into a teammate. It does **not** touch enemies.

**Confirmed:** enemy classes carry no difficulty logic at all —
`BaseCritterCharacter` has no difficulty reference, and its only "Penetration"
string is `PenetrationDepth`, an unrelated physics collision field. Combined
with the level-invariance above, **an enemy's penetration breakpoints are
fixed**: they do not move with level, and no difficulty-driven effect
modifies them.

The mission-card and player-debuff effects are the only things that do. The
debuff effect is the mechanism behind the Demolisher perk *Breaching Blast*
("reduces Penetration Resistance and Penetration Armor by 25%").

## Weak points and the 0.5 multiplier

**Confirmed:** weak points are authored **per bone**. A `HitZoneData` asset
(e.g. `Pathogen_Brute_HitZoneData`) lists `BoneInfos`, each entry carrying a
`BoneName` and a **`bHeadshot`** flag — on the Brute, only
`XenosBiped_Neck_TopSHJnt` has `bHeadshot = True`, with every other listed
bone `False` (and `bSnappable = True` for dismemberment). So "weak point" is a
concrete per-bone property, not a damage-type concept.

**Confirmed:** `PenetrationResistanceWeakpointMultiplier` is `0.5` on every
enemy that has the row, and it has **zero consumers in any Blueprint in the
shipped game** — searched across all 7,224 `/Game/Blueprints/` packages and a
further 11,548 across UI, Weapons, Data, Design, Annihilation, Archive and
Metagame. It is read only by native C++.

**Inferred, still:** its name is unambiguous, so a weak-point hit most likely
needs half the penetration a body hit does — the Queen's faceplate needing 4.0
rather than 8.0, and the universal "armour 4.0" tier needing 2.0 on a weak
point. Unlike the 4.0 threshold, this one could not be closed: the native
damage-resolution function was not located (see below), so the multiplier's
actual application remains unverified. It stays the highest-value thing to
test in-game.

## What the community numbers map onto

The build-crafting rule of thumb — "4 penetration for elite faceplates, 8 for
the Queen's" — reconciles cleanly against the extracted data, but as **two
different attributes**, which is probably why it's confusing in the wild:

- **"4 for elite faceplates"** = `PenetrationResistance_Armor`, which is
  exactly `4.0` on 37 of the 44 current-generation enemies that carry it.
- **"8 for the Queen"** = the Queen's own `PenetrationResistance`, `8.0`.

Both numbers are real, authored, and level-invariant. They are not two points
on one scale; they are separate rows that presumably gate different things
(armoured hit zones vs. general pass-through).

## Grey-Market / Handmade Rounds and the penetration-outcome tags

Separately from armor, penetration decides whether a bullet **passes through
a target or stops in it**, which matters because Grey-Market Rounds and
Handmade Rounds are implemented as a proc ability
(`Avo_Overclock_AutoRifle_GreyMarketRounds_Proc`) gated on the exact
gameplay-event tag `GameplayEvent.Outgoing.Hit.Bullet.NoPenetrating`
(`bRequireExactTag = true`).

**Confirmed:** the tag hierarchy defines three sibling shot-outcome tags, and
across all 102 proc-ability assets in the game, usage is lopsided:

| Tag | Subscriber count |
|---|---|
| `Bullet.NoPenetrating` | 2 (Grey-Market Rounds, Handmade Rounds) |
| `Bullet.FirstOnly` | 31 (Type 111, Acclimization, most on-hit procs) |
| `Bullet.Penetrating` | 0 |

**Inferred:** the natural reading of `NoPenetrating` is "this shot did not
punch through" — i.e. it fires only on the terminal impact of a bullet that
stopped in its target, governed by the same `Penetration` vs
`PenetrationResistance` comparison as the armor question above. Under that
reading, **overshooting a target's `PenetrationResistance` silences
Grey-Market and Handmade Rounds on that target** — the bullet passes through
without ever emitting the hit outcome those procs listen for. This was
observed independently in build-crafting practice before this document
existed (a Zephyr build at 6.5 penetration correctly stopped procing against
mid-resistance enemies) and is consistent with the tag-usage data, but the
emission site itself was not located, so treat it as strong inference, not a
traced fact.

**Practical takeaway if the inference holds:** when running Grey-Market or
Handmade Rounds, build penetration to *just clear* the armor gate (≈4.0–4.5)
rather than stacking every available point — overshooting a target's
`PenetrationResistance` turns the bullet into a pass-through and stops the
proc from firing on that target.

## Difficulty and enemy level

Out of scope for the penetration mechanic specifically — the three
resistance rows are level-invariant, so none of this changes a breakpoint —
but recorded here since it came up alongside this investigation and belongs
next to the enemy data.

**Confirmed:** `Design/Difficulty/DifficultySlider.csv` is entirely
player-side (revive timers, XP/resource multipliers, friendly fire, ammo
crate pickups). It contains no enemy health, damage, or resistance scaling.
`DefaultGame.ini` sets `HardcoreTierScalingStartsAtLevel = 3` and
`HardcoreMaxPossibleTier = 50`, confirming Hardcore ties to a level-like tier
axis, and the compiled binary exports a family of spawn-time level-modifier
functions (`SpawnedCritterLevelModifier`, `SpawnLevelModifier`,
`SpawnLevelDelta`, `ModifyJobCritterLevel`, `ResetJobCritterLevel`).

**Confirmed:** difficulty *is* dispatched in Blueprint, via
`DefaultPlayerCharacter::DifficultySwitchFunction` — a switch on the
difficulty enum (`Easy=0, Normal=1, Hard=2, Extreme=3, Insane=4`, matching
`DifficultySlider.csv` column order) that applies one player-side gameplay
effect per branch. Every effect it applies targets the player
(`BP_ApplyGameplayEffectToSelf`); none touch enemies. `GE_ReviveSpeed_Hard`,
`_Extreme` and `_Insane` are the other three branches.

**Unknown:** no static difficulty-to-critter-level lookup table exists
anywhere in the shipped data (mission CSVs, `MissionZones`, the design
spreadsheet, or config). The mission CSVs do carry six per-difficulty
numeric columns per mission, but their range (3–24, exceeding the 20-level
ClassDefs sheets, and pinned flat across most of the campaign on
Extreme/Insane) reads as a *recommended player level*, not an enemy level —
inferred from shape, not confirmed. The actual assignment appears to be a
runtime spawn-time modifier system (the functions above), which would need
native tracing beyond what this pass covered to resolve definitively. Note
that whatever that system does, it cannot move a penetration breakpoint: the
three resistance rows are flat across every level column on every enemy.

## Deflection is a player stat, not an enemy one

There is a deflection system in the binary, and it is **not** what makes bullets
skip off a charging Crusher.

**Confirmed.** `DeflectionChance` and `DeflectionSeverity` are real
`TakesDamageAttributes` (struct +0x390/+0x3a8, `CurrentValue` +0x3a0/+0x3b8), and
the native side implements the mechanic: the tags `DamageEvent.Deflected` and
`GameplayEvent.Deflected` both exist, and the per-shot result struct
`FWeaponTrace_ForRPC` carries a `bDeflected` field immediately beside
`bDealtAnyDamage` — so a deflected shot is a server-authoritative outcome that
can be replicated to clients as having dealt nothing.

**Confirmed.** A census of all 187 `Design/ClassDefs` sheets finds deflection
rows on exactly 13, and every one of them is a player:

| Sheets carrying a deflection row | Row | Value |
|---|---|---|
| `Player_{Tank, Mechanist, Phalanx, Technician, Doc, Operator, Haywire, Torch, Gunner, Recon, Sharpshooter, Demolisher, Radio}.csv` | `TakesDamageAttributes.DeflectionSeverity` | `0.5`, flat across every level column |

No enemy sheet carries either attribute. Neither do the AFE2-era
`Avo_Player_*.csv` sheets — deflection rows survive only on the thirteen
legacy (AFE1) player classes. `DeflectionChance` is authored nowhere at all.

**Confirmed.** Across 7,224 extracted content assets there are **zero**
references to `DeflectionChance` or `DeflectionSeverity`. The only deflection
token that appears in content is `bCanBeDeflected` (627 occurrences), a
per-targeted-effect opt-in flag — necessary for a deflect, but not sufficient
when nothing ever sets a deflect chance.

Supporting this reading, `EAttributeName::Deflect` sits in the player-facing
stat enum, among `Health`, `Armor`, `Stamina`, `BleedoutTime`, `ReviveSpeed`,
`Avoidance`, `XPGain` and the elemental resistances — the list of stats a
player sees on gear, not anything an enemy has.

**So what is actually happening when rounds skip off a faceplate?** Two
separate systems being read as one (*Inferred*):

1. **The sound and the spark are surface-driven.**
   `Blueprints/Weapons/Impacts/BaseImpactEffect` maps physical surface types to
   impact FX and Wwise events, and the palette distinguishes `ArmoredFlesh` and
   `Carapace_Shield` from plain `Xeno_Flesh`. A round striking an armored plate
   produces a hard metallic impact regardless of what it did to the health pool.
2. **The damage difference is the penetration gate**, described above. The
   relevant numbers for the two enemies in question, both level- and
   difficulty-invariant:

   | Enemy | `PenetrationResistance` | `PenetrationResistance_Armor` | `…WeakpointMultiplier` | `WeakpointMultiplier` |
   |---|---|---|---|---|
   | Xenomorph Crusher | 5 | 4 | 0.5 | 2.5 |
   | Xenomorph Warden | 7 | 4 | 0.5 | 2.5 |
   | Xenomorph Queen | 8 | 4 | 0.5 | 1.5 |

   Note that `_Armor` is *lower* than the body number on all three, and that the
   weak-point multiplier halves whichever gate applies. A face that is both
   armored and a weak point sits at `4 × 0.5 = 2` — which is why a sub-8
   penetration round can still damage the Queen's head, while the same round
   accomplishes little against a plate whose applicable gate it does not clear.

## Bleed is a real system with no penetration input

**Correction to an earlier reading in this document's history:** enemy sheets
*do* carry bleed data. Eight of them do, all level-invariant across 40 columns:

| Sheet | `TakesDamageAttributes.BleedBuildUpResistance` |
|---|---|
| `AvoCSV_Critter_Xeno_Ravager` | **−0.2** (bleeds *more* readily) |
| `AvoCSV_Critter_Xeno_Warrior` | 0.1 |
| `AvoCSV_Critter_Xeno_Burster` | 0.2 |
| `AvoCSV_Critter_Xeno_Spitter` (Venus) | 0.2 |
| `AvoCSV_Critter_Xeno_Exploder` (Venus) | 0.2 |
| `AvoCSV_Critter_Synth_Trooper` | 0.2 |
| `AvoCSV_Critter_Pathogen_EngineerHusk` | 0.2 |
| `AvoCSV_Critter_Xeno_Egg` | 1.0 (immune) |

The sign convention matches the elemental resistances: negative is a
vulnerability, `1.0` is immunity. Every other critter is unauthored and falls
back to the native default. This row is now projected into
`enemy-assets.json` → `records[].stats.defense.bleedBuildUpResistance`.

**Confirmed.** The native system is a build-up-to-threshold model, not a
per-hit DoT. The reflected names are `BleedBuildUpAmount`,
`BleedBuildUpThreshold`, `BleedBuildUpResistance`, `BleedBuildUpDecayRate`,
`BleedBuildUpDecayPeriod` and `BleedBuildUpDecayDelay` on the attribute side,
with `AddToBleedAmount`, `GetCurrentBleedAmount`, `ResetBleedAmount`,
`BleedStack`, `MaxBleedPerSecond` and `BleedTargetedEffect` driving it, and the
tags `Applied.DoT.Bleed` / `Debuff.DoT.Bleed` marking an afflicted target.
Damage accumulates into `BleedBuildUpAmount`, crossing `BleedBuildUpThreshold`
procs the bleed, and the amount decays back down when the target stops taking
qualifying hits.

**Confirmed.** What contributes to build-up is an explicit opt-in: an effect
must declare `EffectType = FEndeavorTargetedEffectType::Bleed`. Exactly nine
content assets do:

| Asset | Source |
|---|---|
| `AvoStatus/ETE_Bleed` | the shared bleed targeted-effect definition |
| `Avocado_Classes/Gunner/Perks/Gun/Proc_Avo_Gunner_Gun_Bleed` | Gunner gun perk — the only gunfire-borne bleed |
| `Avocado_Classes/Gunner/Projectile_Gunner_Grenade_Shrapnel` | Gunner shrapnel grenade |
| `Avocado_Classes/Gunner/Perks/Grenade/GA_Gunner_Grenade_Replacer_Remote` | Gunner grenade perk |
| `Avocado_Classes/Technician/Perks/Explosion_Technician_Shrapnel` | Technician shrapnel |
| `Avocado_Classes/Lancer/Projectile_Lancer_Javelin` | Lancer javelin |
| `Avocado_Classes/Lancer/BP_SpreadDOT` | Lancer spread DoT |
| `Avocado_Classes/Demolisher/Perks/TitanRockets/…_Mod_FireNForget` | Demolisher rocket mod |
| `Venus_Weapons/Guns/Projectiles/Projectile_Venus_Launcher_M12A2_Bodyguard` | M12A2 Bodyguard launcher |

**Confirmed.** None of them is penetration-related, and there is no data path
from penetration to bleed anywhere: `BleedBuildUpAmount` has zero content
references, no asset links `Piercing` or `Penetration` to `Bleed`, and no
gameplay tag joins the two families. **A high penetration value does not cause
a hidden bleed effect.**

*Inferred* — the likely origin of the rumour is the Piercing badge documented
above: a gun crossing `Penetration >= 4` visibly gains a new damage-type icon
in the UI with no stat-line explanation, which is easy to remember as a hidden
effect switching on at high penetration.

## How far the hit-time formula is pinned down

The exact arithmetic that turns `Penetration` and the resistance numbers into a
damage result was **not** fully recovered. What the reflection data does settle:

**Confirmed — penetration produces a fraction, not a boolean.** The binary
carries a reflected field named **`PenetrationPercent`**, emitted in the
property table of `StoppingPowerCalc` alongside:

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

Its siblings are all per-hit scalars — `DistanceDamageMultiplier` is the range
falloff described in [`damage.md`](damage.md). A *percent* sitting in that
company means the penetration check resolves to a scaling factor applied to a
hit, not a pass/fail switch. That is a meaningful constraint on the model even
without the formula: partial outcomes exist.

**Confirmed — the outcome ladder is graded.** The damage-event tag family
contains `DamageEvent.Blocked`, `DamageEvent.PartiallyBlocked` and
`DamageEvent.Deflected` as distinct outcomes. A hit can be reduced rather than
stopped.

**Confirmed — the per-shot result carries the outcome.** Three structs record
it: `FWeaponTrace` (`bShieldDamage`, `bShieldBreak`, `bHitSpecialCritPoint`,
`bPenetratingShot`, `bHitEnemy`, `bHitDead`), `FWeaponTrace_ForRPC`
(`bDealtAnyDamage`, `bDeflected`) and the damage-number widget (`bMyDamage`,
`bPenetrated`). The floater knows whether the shot penetrated, so the
information is available client-side even though no Blueprint reads it.

**Unknown.** The function mapping `(Penetration, PenetrationResistance,
PenetrationResistance_Armor, PenetrationResistanceWeakpointMultiplier)` onto
`PenetrationPercent` is not recovered. Recording the search so it is not
repeated:

- **Not in Blueprints.** `PenetrationResistanceWeakpointMultiplier` has zero
  Blueprint references across 18,772 extracted packages;
  `PenetrationResistance_Armor` has exactly two, both gameplay effects that
  shift it rather than read it (tabled above). `PenetrationPercent`,
  `StoppingPowerCalc`, `DamageEvent.Blocked`, `DamageEvent.PartiallyBlocked`,
  `DamageEvent.Deflected` and `GameplayEvent.Outgoing.Hit.Bullet.Penetrating`
  have **zero** content consumers — the whole outcome layer is C++.
- **Attribute accessors have no native callers.** `GetPenetration_GameplayAttribute`,
  `GetPenetrationResistance_GameplayAttribute` and `GetPenetrationThreshold`
  have zero direct `call` sites in `.text`; GAS getters are inlined at their use
  sites, so the call graph leads nowhere.
- **Offset scanning is not viable at this precision.** Field offsets were
  recovered from the `OnRep_*` functions:

  | Attribute | Struct | `CurrentValue` |
  |---|---|---|
  | `DealsDamageAttributes::Penetration` | +0xf0 | +0x100 |
  | `TakesDamageAttributes::PenetrationResistance` | +0x2b8 | +0x2c8 |
  | `…PenetrationResistanceWeakpointMultiplier` | +0x2d0 | +0x2e0 |
  | `…PenetrationResistance_Armor` | +0x2e8 | +0x2f8 |
  | `…DeflectionChance` | +0x390 | +0x3a0 |
  | `…DeflectionSeverity` | +0x3a8 | +0x3b8 |
  | `…BleedBuildUpAmount` | +0x300 | +0x310 |
  | `…BleedBuildUpResistance` | +0x318 | +0x328 |

  Instruction-aware scanning (decoding SSE scalar ops with `disp32` operands
  rather than matching raw bytes) narrows 58,395 candidate sites to a handful of
  functions touching two or more of these offsets — but disassembling them shows
  vectorised loops walking *every* attribute in sequence, each scaled by one of
  two weights and accumulated. That is the level-interpolation path blending
  adjacent ClassDefs level columns, not a penetration gate. Struct offsets in
  the 0x2xx range are too common for this technique to discriminate.
- **There is no damage `ExecutionCalculation`.** The binary's GAS execution
  calculations are `UBreakIncapacitation…`, `UCharmAdded…`, `UCharmRemoved…`,
  `UGrantTemporaryHealth…`, `UHealConsumable…`, `UHealConsumablePercentage…`,
  `UKillDowned…`, `UMaxStack…` and `UNonLethalDeal…`. Damage is resolved in the
  weapon/hit pipeline, not as a GAS exec calc, so the usual capture-definition
  foothold does not exist here.

Closing this needs a decompiler with type reconstruction (IDA or Ghidra)
starting from `FWeaponTrace` and `PenetrationPercent`, rather than `objdump`
plus pattern scanning.

### An untested player hypothesis, recorded as such

From play experience, not from the data: that damage scales linearly from full
at full penetration down to zero at half the required penetration. The
existence of `PenetrationPercent` and `DamageEvent.PartiallyBlocked` is
consistent with *some* continuous scaling, and rules out a pure binary gate —
but neither the linear shape nor the half-penetration floor is attested
anywhere in the extracted data. Treat it as an open conjecture.


## Source pointers

- Enemy resistance rows: [`src/afe2_catalogue/enemies.py`](../src/afe2_catalogue/enemies.py), `enemy-assets.json` → `records[].stats.defense`.
- Weapon base `Penetration` and attachment stat lines:
  [`src/afe2_catalogue/attachment_descriptions.py`](../src/afe2_catalogue/attachment_descriptions.py),
  `planner-catalogue.json` → `records[].staticStatLines`.
- GE channel/operation data referenced above is not currently surfaced by the
  extractor's normalized `semantic-assets.json` → `effectDefinitions` (it
  captures `operationRaw` but not `Channel`); it was read from the raw
  semantic-reader output. Worth adding to the extractor.
- Blueprint K2 bytecode (used to decompile `Get Damage Type From Stats Block`
  and `DifficultySwitchFunction`) is available from the existing semantic
  reader by passing `includeScriptBytecode: true` on an asset request — the
  flag already exists in `tools/semantic-reader/Program.cs` and is not used by
  any current extractor stage.
- Bleed resistance is projected into `enemy-assets.json` →
  `records[].stats.defense.bleedBuildUpResistance`. Other authored rows this
  summary does not lift out (`IncomingStumbleChanceMultiplier`,
  `CryoSlowResistance`, `FreezeShatterRadius`, the `*_FlatResistance` series)
  are still preserved verbatim under `records[].stats.statsByLevel`.
- The full `Design/ClassDefs` set — 187 sheets covering enemies, players,
  companions and destructibles — extracts in one pass with
  `repak unpack -i AFE2/Content/Design/ClassDefs <pak>`; the attribute-row
  census quoted above was taken from that. The same directory also contains
  the designers' `EnemiesBalanceMaster.xlsx` (see [`damage.md`](damage.md)).
- Deflection, bleed and hit-outcome field names were read from the shipping
  executable's reflection string tables. The offset-scanning script used for
  the SSE instruction decode is throwaway tooling and was not kept.
