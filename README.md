# AFE2 Build Planner — catalogue extractor

This repository currently contains the read-only catalogue-extraction foundation for an **Aliens: Fireteam Elite 2** build planner. The planner UI and build save/load work are intentionally deferred.

The extractor discovers the Steam installation, indexes the game archives, classifies likely build-planner records, converts selected UE4.27 packages, reads serialized properties and effect definitions, exports PNG icons, validates the result, and reports catalogue changes between game updates. It never modifies the game installation.

## Start here

If you just want to install, run, update, or troubleshoot the extractor, use
the plain-language [operator runbook](RUNBOOK.md). The rest of this README is
the technical reference for the extraction model and generated data contract.

## Current boundary

AFE2 uses two encrypted archive systems:

- IoStore (`.utoc` + `.ucas`) contains Unreal packages. [`retoc`](https://github.com/trumank/retoc) exports its package manifest.
- Standalone `.pak` files contain the asset registry, configuration, localization, and other auxiliary files. [`repak`](https://github.com/trumank/repak) indexes these separately.

Package paths are exact game evidence, but a matching path alone does not prove a player-facing name, grid shape, icon, stat, or compatibility relationship. For that reason:

- `candidate-records.json` contains every path-classified candidate and attaches serialized name, description, icon, effect, grid, kit-role, dependency, and mechanically proven stat evidence when available.
- `semantic-assets.json` is the normalized evidence layer. It also contains the canonical kit-ability concepts, class-authored display icons, and the exact pre-mission Major/Minor item slots, and records per-stage coverage and unresolved dependencies; editor admission and compatibility are resolved by the later canonical projection rather than by parse success alone.
- `collection-assets.json` is the canonical player-visible index. It resolves the authored `Store_MainHub_Credits` categories through product and reward wrappers to their terminal records, separately traces starting and earned class-unlock rewards to exact kit records under `kitMembership`, and audits every observed Collection category as included, deliberately ignored, or unknown. It preserves membership, acquisition evidence, and fail-closed unresolved references for both routes.
- `grid-assets.json` inventories the source-derived PerkGrid art, widget/layout definitions, shared brush dependencies, palette, dimensions, and rendering lookup contract. Its PNG and serialized-widget artifacts live under `grid-assets/`.
- `planner-catalogue.json` is the flat, fail-closed projection consumed by the v0 editor. It combines canonical Store and kit membership, class-authored abilities and perk unlock evidence, and normalized progression rewards, and contains only editor-selectable identities and relationships. Every record carries authored player-facing text; package paths remain stable IDs, never fallback labels.
- Path candidates that are not admitted by authored game data remain available in the evidence layers; they are never silently promoted into the editor dataset.

The build editor reads `planner-catalogue.json`, not the path-classified
candidate superset. A record enters the planner only through an
authored player-facing source: canonical Store membership, canonical
starting/earned kit membership, a class's ability or `ChipEntitlements` lists
after that class's kit has been admitted, or another explicitly normalized
game progression registry. A `KitUnlock_*`-shaped path is candidate evidence
only; it does not admit a kit by itself. This keeps new content dynamic without
admitting false-positive path candidates.

## Requirements

- Python 3.10+
- A locally owned Steam installation of AFE2
- Git
- Stable Rust and Cargo 1.85 or newer
- A native C toolchain/linker and zlib development files
- .NET 9 SDK and `Microsoft.NETCore.App` 9 runtime

The script owns its tool setup. On first use it clones the pinned `retoc` 0.1.5 and `repak` 0.2.3 sources into `.tools/`, verifies their exact source revisions, and builds the CLI binaries with Cargo's lockfiles. It also restores the repository's exact NuGet lock and builds `afe2-semantic-reader` under `.tools/`; all direct package versions and content hashes are committed in `tools/semantic-reader/packages.lock.json`. `.tools/` is ignored by Git. Later runs validate and reuse the cached builds; they do not pull or silently replace a dirty or mismatched checkout.

## Run it

No Python packages need to be installed.

```bash
python3 scripts/build_catalogue.py bootstrap-tools

python3 scripts/build_catalogue.py doctor

python3 scripts/build_catalogue.py extract \
  --output .local/catalogue

python3 scripts/build_catalogue.py validate .local/catalogue
```

`bootstrap-tools` is optional: `doctor` and `extract` automatically prepare the tools they need. The initial clone, locked restore, and builds require network access and can take several minutes. Managed outputs stay below ignored `.tools/`.

Steam discovery supports common Linux Steam locations. Use `--game-dir "/path/to/Aliens Fireteam Elite 2"` or set `AFE2_GAME_DIR` if auto-detection cannot find it.

An existing `retoc manifest` export can be parsed with `--manifest /path/to/pakstore.json`. Semantic extraction remains enabled and therefore still prepares `retoc` plus the .NET reader and validates the archive key. Add `--no-semantic-assets --no-pak-index` for a manifest-only/offline index run that prepares neither archive tool. A valid game directory is still required for source inventory and build metadata. Because the script cannot bind an arbitrary supplied manifest to every installed container, IoStore coverage is labelled `unverified` and `--strict` rejects that mode.

Semantic extraction is archive-candidate based, not save-observation based: every classified candidate is requested even if it never appeared in the supplied character save. Use `--no-semantic-assets` only when package conversion/icon extraction is intentionally out of scope.

Large semantic-reader requests are split across isolated .NET child processes.
`--jobs N` controls the upper bound (`1` through `16`); the default is half of
the detected logical CPUs, capped at four. Use `--jobs 1` for a serial diagnostic
run. Small graph-traversal requests remain serial, and `retoc` keeps its own
internal Rayon parallelism. Output is independent of the selected job count.

## Inspect a partial character save

A readable `char.dec` can add positive, per-asset evidence without becoming the
canonical catalogue or a completeness check:

```bash
python3 scripts/build_catalogue.py inspect-save \
  "/path/to/AFE2/Saved/SaveGames/<profile>/char.dec" \
  --catalogue-dir .local/catalogue \
  --output .local/save-evidence.json
```

This command is entirely read-only with respect to the save. It accepts normal
`CharacterDoc` JSON and the observed decoded-save variant whose final `}` is a
literal `?`; that one byte is normalized only in memory. It never auto-discovers
a Steam profile or writes account IDs, names, GUIDs, timestamps, or the save's
absolute path to the report.

`save-evidence.json` records every referenced `/Game` asset, its normalized
package ID, safe save contexts, exact package/candidate/planner joins, saved
perk placements and rotations, weapon-component pairings, inventory fields, and
reviewable kit-class aliases. It is deliberately marked `partial-save` and
`absenceMeans: not-observed`: an asset missing from one player's save is never
treated as locked, invalid, incompatible, or absent from the game. Likewise,
`assignedToSavedLoadout` means only that the serialized character instance
references it; it does not prove deliberate or recent use. Inventory
`bUnlocked` values are retained as literal evidence and are not interpreted.

The report remains under ignored `.local/` because even identity-stripped
loadout and ownership evidence can describe a player's progress.

## Archive-key handling

The script intentionally has no `--aes-key VALUE` option.

Key resolution order is:

1. `AFE2_AES_KEY` (or the variable named by `--aes-key-env`)
2. A mode-`0600` file passed with `--key-file`
3. Read-only candidate discovery in the installed shipping executable, using the public signature-scanning technique documented by [AESDumpster-rs](https://github.com/yuhkix/aesdumpster-rs)

Every candidate is validated against an encrypted archive. The value is never printed or persisted by the script. `retoc` and `repak` accept encryption keys only as command-line arguments, so the key is briefly visible in the child process arguments to the same local user while those tools run. Use `--no-executable-key-scan` to require an explicit environment variable or key file.

Never commit keys, extracted assets, `pakstore.json`, or generated `.local/` output.

## Generated files

A default semantic extraction publishes these files together:

- `source-manifest.json` — game build, archive inventory, adapter versions, coverage, and source fingerprint
- `package-index.json` — exact IoStore packages/chunks plus PAK member paths
- `candidate-records.json` — evidence-labelled class, ability, perk, grid, weapon, mod, trait, augment, and item candidates
- `semantic-assets.json` — normalized serialized text, parent/effect/icon links, class-authored perk boards, ability and weapon slots, the two player item slots, chip entitlements, canonical kit abilities and class icons, perk-grid shapes, tag-derived dependencies, raw effect settings, mechanically proven stat operations, failures, and explicit coverage gaps
- `collection-assets.json` — normalized Store/Collection categories, a complete included/ignored/unknown category audit, product rows, wrapper chains, terminal memberships, canonical starting/earned kit membership, `RewardTable_Settings_V1` progression perks, acquisition metadata, and any fail-closed unresolved entries
- `planner-catalogue.json` — the validated flat v0 editor dataset: source build metadata, a UI-text contract, visible kits, abilities, globally equipable unlocked perks, weapons, labelled attachment slots and choices, traits, augment concepts, Major/Minor item slots and choices, authored UI-description groups, compatibility edges, and per-kit board contracts
- `icons/*.png` — deterministic, content-hashed UI textures referenced by semantic records
- `grid-assets.json` — deterministic PerkGrid asset manifest, exact texture/widget dependencies, dimensions, family/footprint labels, palette, render-order contract, failures, and coverage
- `grid-assets/textures/*.png` — dedicated chip, frame, connector, lock-region, slot, background, and interaction art plus every directly imported shared UI texture
- `grid-assets/widgets/*.json` — serialized board/placement/connector/slot/lock/frame/helper definitions, including WidgetTree properties and Kismet bytecode needed to recover layout, state behavior, and palette constants
- `validation.json` — structural errors, coverage warnings, and source/editor record counts
- `changes.json` — schema-v2, sorted added/removed/field-level changes for the editor record source plus a separate candidate-evidence diff, versus `--baseline` or the previous output
- `publication.json` — deterministic ownership metadata and hashes for the complete generated publication

The optional, separately generated `.local/save-evidence.json` is not part of
this archive-derived publication set, is never included in catalogue archives,
and never changes their source fingerprint.

JSON is UTF-8, recursively key-sorted, two-space indented, and excludes absolute paths, timestamps, archive names, and temporary names. Every successful `extract` is a clean, whole-directory rebuild: all new files are staged and validated before the existing managed output is moved, so stale generated files cannot survive. A failed extraction leaves the last valid publication in place, and a handled installation failure rolls it back. The publisher refuses to replace an unrecognized directory or one containing extra user files.

By default, an existing publication is retained in a sibling directory named
`<output>-archive` before the staged replacement is installed. With the default
output, this is `.local/catalogue-archive/`; it is covered by the repository's
`.local/` ignore rule. Archive names include the old game build and a digest of
the complete snapshot. Content-identical snapshots reuse an existing archive
instead of consuming another copy. Use `--archive-dir PATH` to choose another
same-filesystem location, or `--no-archive` to keep rollback safety without
retaining the previous publication after success. `--baseline` still controls
diff generation only; it does not change which current publication is archived.

Two clean runs against the same sources and baseline produce byte-identical
current files. Local archive naming and history never enter those files.

The classification rules live in [`config/categories.json`](config/categories.json). They identify the broad evidence superset; canonical game membership and relationships determine editor admission later in the pipeline.

`--strict` turns incomplete or unverified evidence coverage into errors. It
audits the broader evidence publication as well as the planner. Whenever
semantic extraction is enabled, `planner-catalogue.json` is built and validated
fail-closed; an index-only `--no-semantic-assets` run intentionally omits it.

## Editor-facing catalogue contract

`planner-catalogue.json` is deliberately flat: the frontend can filter one
record array by `kind` and compatibility without forcing the player through
internal weapon families or implementation assets. Its admission rules are
derived from authored game data rather than directory names:

- Weapons, component mods, traits, augment packs, items, and Wrench perks come
  from terminal membership in the live `Store_MainHub_Credits` categories used
  by Collection. Product and reward-table wrappers are resolved before a
  terminal record is admitted.
- Kits are admitted through authored unlock rewards, not by matching a
  `KitUnlock_*` path. Starting classes must occur in exact
  `CharacterUnlockToken` rows under
  `/Game/Design/Rewards/DefaultStarting_Rewards`. A non-starting class must be
  reached through a reward-table Blueprint imported by a live Metagame
  registry package. In both cases, the row's exact `CharacterUnlock` target
  must map to exactly one candidate kit's serialized `CharacterClass`
  reference.
  Latent path candidates outside those chains remain excluded. If some chain
  evidence is unresolved, a normal extraction warns and consumes only proven
  `kitMembership.memberIds`; `--strict` rejects the incomplete evidence.
- For each admitted kit, ability choices come from its class's authored role
  lists and board slots. `ChipEntitlements`, Store membership, and progression
  rewards are unlock provenance for ordinary perks, not permanent class
  restrictions: once any admitted route unlocks an ordinary perk, every
  admitted kit can equip it. Ability modifiers remain useful only where their
  dependency tags resolve a compatible target. A future class, ability, or
  entitlement using the same schemas becomes selectable after a normal
  extraction once an authored starting or live-registry unlock chain reaches
  that class; there is no class-name allowlist.
- Progression-only perks are discovered by traversing
  `/Game/Design/Rewards/RewardTable_Settings_V1.UnlockRewardTablesMap` through
  its authored reward tables, rather than by naming the perks in code. In the
  current verified snapshot, the `Mission` branch adds exactly two such
  planner-visible rewards: Stun Baton Mastery from Deadly Descendants and
  Veteran Marine from Queen Fight. `collection-assets.json.progressionPerks`
  preserves the source branch, root, step, and terminal evidence for that
  traversal. That snapshot proves 36 unique progression perk IDs in total; 34
  already overlap Store membership. Two absent Wave-table references remain
  explicit unresolved diagnostics: normal extraction consumes only the proven
  IDs, while `--strict` rejects the incomplete progression coverage.
- Dependency edges never admit another record. Perks publish their authored
  selection sources, and compatibility/dependency IDs are filtered to records
  already present in the same planner file; an admitted modifier with no
  selectable compatible target fails projection instead of expanding it.

The store-category audit is deliberately separate from admission. Known
non-build categories (`Challenge Cards` and `Divider` in the current build) are
reported as ignored. A new unknown category is not made selectable by guesswork:
normal validation warns, and `--strict` rejects it for review.

Every selected weapon publishes exactly three ordered `componentSlots`, one
`traitSlot`, and one `augmentSlot`. Each slot contains only compatible visible
choices; the weapon also publishes their aggregate IDs, while mods and traits
publish the reverse `compatibleWeaponIds` relation. Extraction fails instead of
publishing a weapon with an unresolved or differently shaped selectable slot
set. Internal magazine variants and weapon-specific choices remain ordinary
flat mod records—the slot relation, not a frontend family guess, determines
whether they can be selected.

Kit weapon choices follow the game's loadout-menu dispatch rather than
conjoining every serialized slot field. For the fully unlocked projection, a
non-`Any` slot accepts the exact `weaponRole`, except when its kit tag appears
in the weapon's published `kitIgnoreTags` inherited from `GunKitIgnoreTags`;
its type and subtype do not add another filter. An `Any` role instead selects
by a non-`Any` subtype, or by type when the subtype is also `Any`. Published
`kitTags`, inherited from `GunKitTags`, prove a Signature weapon's native,
pre-mastery kit access, but are not a permanent whitelist: mastered Signature
weapons become cross-kit unless explicitly ignored. The current Collection
therefore supplies 18 Primary, 15 Signature, and four Sidearm choices.
Duelist's authored second slot is another Primary slot, so it receives the same
18-role pool rather than a weapon-family submenu.

Augments are also flat at the UI boundary. In the current verified Steam build
`25057376`, the 60 Collection augment packs become 60 planner concepts. Each
concept retains its compatible weapons and an `implementationByWeaponId` map to
the correct weapon-specific asset, so those implementation assets do not appear
as hundreds of duplicate choices. The same snapshot contains 15 minor and 11
major item records. The exact `DefaultPlayerCharacter.PartSlots` evidence
publishes one `Major Item` picker and one `Minor Item` picker, each filtered to
its matching Collection choices. Items retain their `itemTier` and are made
available to all extracted kits; mission inventory slots and quantities are out
of the v0 contract.

Each kit layout exposes exactly 42 placeable cells: `A1:J1` and `B2:I5`. The
remaining authored board placements are ability anchors, including their role,
footprint, selectable ability IDs, and resolved body texture; the passive anchor
extends the render area below the five-row placeable board. Perks publish all
four quarter-turn rotations and exact occupied-cell masks. Modifier placement
uses orthogonal connectivity, not diagonal contact: a modifier must join the
connected group of a compatible ability, passive, or core perk. When a modifier
can target more than one record, the saved build must also record the chosen
`targetId`.

Every planner record must have a nonblank authored `displayName` and a decoded,
relative `icons/*.png` asset. Names and every authored description are checked
against their semantic source, and internal package/object/localization syntax
is rejected as display text. Plain `description` and structured
`conditionalDescriptions` retain the game's Unreal rich-text tags for a
frontend parser; they must not be injected as raw HTML. An explicit empty
serialized description remains null rather than being replaced with a guessed
path or generated stat copy. Every selectable perk must also have a resolved
chip-body binding, and each ability
anchor must have its resolved slot-controlled body texture. Attachments and
traits may also publish the game's authored `conditionalDescriptions`: ordered
condition text and UI stat lines with `statText`, `statValue`, `displayType`,
and `result`. `conditionText` and `statText` are nullable because the shipped
data uses empty sentinel lines; the frontend should omit those text nodes. Here
`statValue` is the value authored for formatting that UI line, not the deferred
normalized weapon-stat or gameplay-effect model. Numeric
mechanics and gameplay-effect payloads remain available in the semantic
evidence layer, but are intentionally omitted from `planner-catalogue.json`
for v0; the validator rejects them if they leak into the editor dataset.

## Weapon icon evidence

Every current gun CDO serializes two distinct UI textures below
`Attributes.UIVisuals`: `GunIcon` is the full-colour static weapon art, while
`AmmoIcon` is a white silhouette. The extractor follows the exact nested
`GunIcon` object reference rather than deriving a texture name from the weapon
package, and publishes the corresponding `AmmoIcon` as `silhouetteIcon`. This
also handles the L36, whose image remains in the older
`/Game/Weapons/Icons/Guns/` directory.

The static Collection/store tiles use `GunIcon` directly. The in-game loadout
can instead call `GenerateThumbnailForGunInstance` and render a configured gun
to a transient `TextureRenderTarget2D`; that path reflects the player's
attachments and colorway but produces no archive image for an offline web
catalogue. The static `GunIcon` is therefore the deterministic default image.

All 67 current weapon candidates have a decoded planner-facing primary icon,
including all 37 weapons in the canonical Collection list. One shipped-data
exception remains:
Mondo Heat 9000 points its serialized `GunIcon` at the generic Kramer rifle
art. While that exact placeholder reference remains, the extractor preserves it
as `serializedIcon` and publishes Mondo's trait icon as the planner-facing
`icon`. Its Mondo-specific `AmmoIcon` remains independently available as
`silhouetteIcon`. The fallback is deliberately guarded by the known Kramer
package path: if a future game build supplies a different, dedicated Mondo
`GunIcon`, that serialized art wins automatically.

## Kit icon evidence

An admitted kit's primary icon follows its CharacterClass CDO's exact
`ClassDisplayIcon` reference. The older `KitUnlock.Icon` is retained only as an
evidence-labelled fallback when the class property has no single resolvable
texture; neither discovery nor fallback names a kit. The current six kits all
resolve distinct 300x300 class icons with source package, property, and member
provenance, so no fallback is active.

Some retoc-reconstructed Texture2D packages serialize a cooked-platform skip
offset short of the true export boundary. The pinned reader validates the
UAssetAPI export bounds and repairs that offset only in a private temporary copy
before CUE4Parse decoding. Ambiguous or malformed layouts fail per icon, and the
original loose extraction is never modified. This prevents a valid texture such
as the current Technician icon from hanging a complete catalogue run.

## Kit ability evidence

Kit candidate discovery has no class-name allowlist and no expected kit,
ability, or slot count, but discovery alone does not make a kit selectable.
Starting classes are proven by exact `CharacterUnlockToken` rows in
`DefaultStarting_Rewards`; non-starting class reward tables are considered only
when their Blueprint defaults are imported by live Metagame registry packages.
Each resulting `CharacterUnlock` target must map exactly to one `KitUnlock_*`
candidate's serialized `CharacterClass` reference. The extractor then follows
that admitted class asset to its `ChipBoardDef`, `GunLoadoutData`, and
`ChipEntitlements` arrays and follows the board's `BoardLockedPlacements`.
Unreached latent kit paths stay out of the planner. A future class following
both the authored unlock chain and class schema is therefore included by the
next ordinary extraction without a code change.

`collection-assets.json.kitMembership` publishes `status`, `source`,
`memberIds`, `entries`, `coverage`, and `unresolved`. Each entry preserves the
exact kit/class match plus its starting or Metagame reward sources and traversal
steps. An `incomplete` status does not promote uncertain kits: normal
validation warns while the planner consumes only the proven IDs, and
`--strict` turns that warning into an error.

Selectable abilities are perk-board chips whose serialized fields identify
their role, originating kit, eligible kits, and gameplay implementation. The
known game enum values `ClassAbilityType::Ultimate`, `Tactical`, and `Passive`
normalize to `primary`, `secondary`, and `passive`; a future unknown value is
retained as `unresolved-role` and reported by validation instead of being
dropped. Cross-kit wrappers are identified by differing serialized origin and
restriction references and merge only when an exact gameplay-ability target
identifies one native chip. Slot placeholders require two independent data
signals: a pure role-receptacle chip and an owner kit that imports cross-kit
abilities. None of this logic names Specialist or any starting class.

`semantic-assets.json` publishes flattened concepts in `kitAbilities`. Each
concept records `role`, `originKitId`, `availableToKitIds`,
`gameplayAbilityPackagePath`, and every merged source chip under
`sourceChipIds`. Every kit publishes `abilityPerkIdsByRole`, including empty
`primary`, `secondary`, or `passive` lists when its board has no such slot. Its
`abilitySlots` retain the board position and locked chip, `weaponSlots` retain
the serialized slot/type/subtype/default-weapon sequence, `chipEntitlements`
retain rank and grant evidence, and `perkBoard.lockedPlacements` retains the
complete board anchors. The editor must iterate these arrays; it must not assume
one slot per ability role or any particular class name. Weapon attachment slots
are a separate, deliberately fixed contract described above.

The current build is a snapshot, not an invariant: its 40 `GA_*` paths are
gameplay-implementation candidates, while its boards resolve to 35 canonical
selectable abilities. Marauder, Duelist, Hunter, Medic, and Machinist currently
contribute three primaries, three secondaries, and one passive apiece.
Specialist can select all 15 primaries, 15 secondaries, and five passives through
15 exact-target aliases plus 20 chips that directly declare Specialist
eligibility; three data-proven role placeholders are excluded. A matching
`GA_*` record may point back through `implementationForAbilityIds`, but remains
implementation evidence rather than a separate selectable ability.

Duelist does have a primary ability slot. Its current irregularity is in
`GunLoadoutData`: two `Primary` weapon slots followed by one `Sidearm`, with no
`Signature` slot. That is emitted exactly as serialized rather than represented
by a Duelist-specific exception.

## Perk grid and dependency evidence

Every perk record now carries `grid.allowedRotations` for `Default`,
`Clockwise90`, `Clockwise180`, and `Clockwise270`. Each entry in
`grid.shapes` preserves the serialized `width`, `height`, row-major
`collisionMask`, and the derived nonzero `occupiedCells`, `cellCount`, and
normalized `size`. Of the 521 current perk candidates, 494 serialize
`PossibleShapes`; the other 27 directly inherit the native `ModChipDef`
default, published as an evidence-labelled inferred 2x2 shape. The verified
normalized size counts are 22 1x1, 202 1x2, 152 1x3, 107 1x4, 27 2x2, and 11
1x10 records.

The editor projection currently admits 465 ordinary perks: 104 explicit
`perkType: core` records and 361 `perkType: modifier` records, derived from the
resolved `chipVisual.family` rather than a name or directory. Every one appears
in every admitted kit's `selectablePerkIds`; its `selectionSources` and detailed
`availability` still explain where it is unlocked. Modifier dependency targets,
not origin-kit metadata, determine whether and where a modifier can function.

Modifier relationships are derived from the game's serialized gameplay tags,
not perk names. A modifier's `Tags` become `dependencies.providedTags`, while a
potential target's deliberately misspelled `ModifierCompatability` property
becomes `dependencies.acceptedModifierTags`. A provided tag matches an exact
accepted tag or one of its descendants; the comparison is directional. The
normalizer publishes `possibleTargetPerkIds` on the modifier,
`possibleModifierPerkIds` on the target, and
`requiresConnectedCompatibleTarget: true`. In the game, the compatible target
may be anywhere in the same orthogonally connected chip group rather than
directly touching the modifier, and modifier-to-modifier chains are valid.

## Perk-grid UI asset evidence

The extractor does not cut artwork out of screenshots. It dynamically selects
the game's `WB_Menu_Kits_PerkGrid_*` and
`WB_Button_Equip_Content_PerkGrid*` widgets plus the palette, macro, and ability
replacer helpers; it then decodes both dedicated PerkGrid texture directories
and every `/Game/UI/Textures/` package directly imported by those definitions.
A future helper following those widget prefixes or a future texture in either
dedicated directory is included on the next extraction without a named
allowlist entry.

In Steam build `25057376` this produces 14 widget/helper definitions and 62
textures with no failures: 57 dedicated textures and five shared dependencies
(the solid-white tint brush, lock, double-arrow, alert brackets, and loadout
divider). The dedicated set includes all orientation-specific `core`,
`modifier`, and `replacer` chip bodies, icon frames, empty slot, ghost
connector, board background/frame pieces, lock-region pieces, and interaction
icons. The PNGs retain their alpha channels; most chip art is deliberately
neutral source art that the widgets tint at runtime.

`grid-assets.json.layoutMetrics` derives a 90x90-pixel cell interior, a
100x100-pixel pitch, a 10-pixel gap, and a 52x14-pixel connector directly from
the decoded textures and widget properties. `perkColorPalette` conservatively
parses the eight exact linear RGBA constants and switch order from
`ReturnPerkColor` bytecode and also supplies CSS-ready sRGB hex values. The raw
widget artifacts preserve the rest of the board behavior instead of replacing
it with screenshot guesses.

Each semantic perk now carries `chipVisual.family`. The resolver uses serialized
`ClassAbilityType`/`ReplacerType` for ability-replacer art, explicit `Type` for
modifier art, then follows any Blueprint parent chain before accepting the
native `ModChipDef` core default. It does not use perk names, directories, kit
names, or a fixed record count. The current result is 105 core, 362 modifier,
and 53 replacer records; `Perk_Generic_Special_Proc` remains explicitly
unresolved because its native `CoreProcAbility` superclass does not prove that
it is a placeable chip.

For rendering, rotate the logical footprint first and select the matching
orientation-specific body texture; do not rotate a completed composite, because
the perk icon remains upright. The current authored board resolves to a
10-column, five-row placeable base plus the locked passive anchor on row six.
The planner validates the resulting 42-cell editor contract explicitly; if a
game update changes that contract, extraction fails for review instead of
silently publishing a differently shaped board.

## Priming Chamber evidence

The current asset is `/Game/Blueprints/Venus_Weapons/Attachments/Magazines/Magazines_Tubular/Avo_Magazine_Tubular_Priming`. It serializes `Priming Chamber`, an explicitly empty description, and the tubular-magazine icon. Its configured effect links to `Avo_Weapon_ReloadSpeed` with raw float32 magnitude `1.2000000476837158`; that effect applies a SetByCaller `Division` modifier to `TimeToReload`. The semantic evidence therefore normalizes the formula as `TimeToReload / 1.2`: +20% reload rate, a `0.833333` time multiplier, or 16.666667% less reload time. The extractor does not attach the unused legacy `Attachment_PrimingMagazine` fire-rate effect or the legacy `Priming Magazine` text.

The current Store/Collection data lists Priming Chamber directly as Magazines
entry 89, marked non-purchasable. That canonical membership admits it to
`planner-catalogue.json` despite its presently unobtainable state. If a later
build removes the authored Collection entry, a clean extraction removes it from
the editor catalogue unless another canonical player-facing source admits it.

## Verified local smoke result

Against Steam build `25057376`, the extractor indexed:

- 61,600 IoStore packages
- 33,338 PAK members
- 6 class-backed kit candidates and 35 canonical selectable abilities: 15
  primary, 15 secondary, and 5 passive, with six resolved class-display icons
- 465 ordinary perks available to all six kits: 104 core and 361 modifier, with
  resolved shapes, render bindings, and dependency targets
- 37 Collection weapons, each with a decoded default icon and a resolved
  three-component/one-trait/one-augment compatibility contract
- 60 flat Collection augment concepts backed by their compatible
  weapon-specific implementations
- 15 minor and 11 major Collection item choices, available through exactly one
  authored Minor and one authored Major loadout slot
- 875 selectable records with 875 human-readable names; 630 have plain
  descriptions and 140 have conditional-description groups. The remaining 82
  mods and 23 traits explicitly author no UI copy and remain null.
- one validated 42-placeable-cell layout per kit, with resolved ability anchors
  and grid art

Both PAK indexes and all IoStore containers were covered in that run. These are
current verified snapshot counts, not hard-coded expectations: archive or
Collection additions should change them on the next extraction. A schema change
that cannot satisfy the editor contract instead fails validation for review.

The canonical `kitMembership` stage completed in that whole-publication run and
authorized all six current kits with no unresolved references: five through
`DefaultStarting_Rewards`, and Specialist through the class-unlock reward
imported by `AchievementMetaMissions`.

## Tests

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q src scripts
```

Tests use only synthetic data. Public CI never needs a game installation, archive tool, or encryption key.
