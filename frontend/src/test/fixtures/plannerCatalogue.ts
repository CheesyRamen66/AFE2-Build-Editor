import type { GridCell, PlannerCatalogue } from "../../model/catalogue";

const placeableCells: GridCell[] = [];
for (let row = 0; row < 5; row += 1) {
  for (let column = 0; column < 5; column += 1) {
    const isAbilityAnchor = row === 0 && column === 0;
    const isReservedCell = row === 2 && column === 2;
    if (!isAbilityAnchor && !isReservedCell) placeableCells.push({ row, column });
  }
}

const specialistAnchorCells: GridCell[] = [
  { row: 0, column: 0 },
  { row: 0, column: 4 },
  { row: 4, column: 2 },
];
const specialistPlaceableCells: GridCell[] = [];
for (let row = 0; row < 5; row += 1) {
  for (let column = 0; column < 5; column += 1) {
    if (!specialistAnchorCells.some((cell) => cell.row === row && cell.column === column)) {
      specialistPlaceableCells.push({ row, column });
    }
  }
}

export function createSyntheticPlannerCatalogue(): PlannerCatalogue {
  return {
    schemaVersion: 1,
    sourceFingerprint: "synthetic-test-catalogue",
    game: {
      buildId: "test-build",
      steamAppId: "0",
    },
    records: [
      {
        id: "kit-alpha",
        kind: "kit",
        displayName: "Alpha",
        abilitySlots: [
          {
            index: 0,
            role: "primary",
            row: 0,
            column: 0,
            lockedChipId: "ability-primary",
            selectableAbilityIds: ["ability-alternate", "ability-primary"],
          },
        ],
        selectablePerkIds: [
          "perk-bar",
          "perk-core",
          "perk-modifier",
          "perk-modifier-b",
        ],
        weaponSlots: [
          {
            index: 0,
            slotType: "primary",
            weaponType: "rifle",
            defaultWeaponId: "weapon-alpha",
            compatibleWeaponIds: ["weapon-alpha", "weapon-beta"],
          },
        ],
      },
      {
        id: "kit-specialist",
        kind: "kit",
        displayName: "Specialist",
        abilitySlots: [
          {
            index: 0,
            role: "primary",
            row: 0,
            column: 0,
            lockedChipId: "placeholder-specialist-primary",
            selectableAbilityIds: ["ability-primary", "ability-alternate"],
          },
          {
            index: 1,
            role: "secondary",
            row: 0,
            column: 4,
            lockedChipId: "placeholder-specialist-secondary",
            selectableAbilityIds: ["ability-secondary"],
          },
          {
            index: 2,
            role: "passive",
            row: 4,
            column: 2,
            lockedChipId: "placeholder-specialist-passive",
            selectableAbilityIds: ["ability-passive"],
          },
        ],
        selectablePerkIds: ["perk-core"],
        weaponSlots: [],
      },
      {
        id: "ability-primary",
        kind: "ability",
        displayName: "Primary Ability",
        description: "Launches the primary test payload.",
      },
      {
        id: "ability-alternate",
        kind: "ability",
        displayName: "Alternate Ability",
      },
      {
        id: "ability-secondary",
        kind: "ability",
        displayName: "Secondary Ability",
      },
      {
        id: "ability-passive",
        kind: "ability",
        displayName: "Passive Ability",
      },
      {
        id: "perk-bar",
        kind: "perk",
        displayName: "Bar Perk",
        perkType: "core",
        availableToKitIds: ["kit-alpha"],
        grid: {
          allowedRotations: ["Default", "Clockwise90", "Clockwise180", "Clockwise270"],
          shapes: [
            {
              width: 2,
              height: 1,
              cellCount: 2,
              size: "2x1",
              occupiedCells: [
                { row: 0, column: 0 },
                { row: 0, column: 1 },
              ],
            },
          ],
        },
      },
      {
        id: "perk-core",
        kind: "perk",
        displayName: "Core Perk",
        description: "Anchors compatible modifiers.",
        perkType: "core",
        availableToKitIds: ["kit-alpha"],
        visualClassification: {
          restrictionType: "kit",
          restrictionTypeRaw: "EModChipRestrictionType::Kit",
          status: "resolved",
          evidence: { source: "serialized-enum" },
        },
        grid: {
          allowedRotations: ["Default"],
          shapes: [
            {
              width: 1,
              height: 1,
              cellCount: 1,
              size: "1x1",
              occupiedCells: [{ row: 0, column: 0 }],
            },
          ],
        },
      },
      {
        id: "perk-modifier",
        kind: "perk",
        displayName: "Linked Modifier",
        description: "Improves its connected parent.",
        perkType: "modifier",
        availableToKitIds: ["kit-alpha"],
        visualClassification: {
          restrictionType: "role",
          restrictionTypeRaw: "EModChipRestrictionType::Role",
          status: "resolved",
          evidence: { source: "serialized-enum" },
        },
        grid: {
          allowedRotations: ["Default"],
          shapes: [
            {
              width: 1,
              height: 1,
              cellCount: 1,
              size: "1x1",
              occupiedCells: [{ row: 0, column: 0 }],
            },
          ],
        },
        dependencies: {
          possibleTargetPerkIds: ["ability-primary", "perk-core", "perk-modifier-b"],
          requiresConnectedCompatibleTarget: true,
          targetSelection: {
            candidateIds: ["ability-primary", "perk-core", "perk-modifier-b"],
            required: true,
          },
        },
      },
      {
        id: "perk-modifier-b",
        kind: "perk",
        displayName: "Second Linked Modifier",
        perkType: "modifier",
        availableToKitIds: ["kit-alpha"],
        grid: {
          allowedRotations: ["Default"],
          shapes: [
            {
              width: 1,
              height: 1,
              cellCount: 1,
              size: "1x1",
              occupiedCells: [{ row: 0, column: 0 }],
            },
          ],
        },
        dependencies: {
          possibleTargetPerkIds: ["perk-modifier", "perk-core"],
          requiresConnectedCompatibleTarget: true,
          targetSelection: {
            candidateIds: ["perk-modifier", "perk-core"],
            required: true,
          },
        },
      },
      {
        id: "perk-foreign",
        kind: "perk",
        displayName: "Foreign Perk",
        perkType: "core",
        availableToKitIds: [],
        grid: {
          allowedRotations: ["Default"],
          shapes: [
            {
              width: 1,
              height: 1,
              cellCount: 1,
              size: "1x1",
              occupiedCells: [{ row: 0, column: 0 }],
            },
          ],
        },
      },
      {
        id: "weapon-alpha",
        kind: "weapon",
        displayName: "Alpha Rifle",
        componentSlots: [
          {
            index: 0,
            kind: "component",
            displayName: "Magazine",
            slotCategory: "magazine",
            compatibleIds: ["mod-alpha"],
          },
        ],
        compatibility: {
          traitSlot: {
            index: 1,
            kind: "trait",
            displayName: "Trait",
            slotCategory: "trait",
            compatibleIds: ["trait-alpha"],
            defaultAttachmentId: "trait-alpha",
          },
        },
      },
      {
        id: "weapon-beta",
        kind: "weapon",
        displayName: "Beta Rifle",
        componentSlots: [
          {
            index: 0,
            kind: "component",
            displayName: "Muzzle",
            slotCategory: "muzzle",
            compatibleIds: ["mod-beta"],
          },
        ],
        compatibility: {
          augmentSlot: {
            index: 1,
            kind: "augment",
            displayName: "Augment",
            slotCategory: "augment",
            compatibleIds: ["augment-beta"],
            defaultAttachmentId: "augment-beta",
          },
        },
      },
      {
        id: "mod-alpha",
        kind: "mod",
        displayName: "Alpha Magazine",
      },
      {
        id: "mod-beta",
        kind: "mod",
        displayName: "Beta Muzzle",
      },
      {
        id: "trait-alpha",
        kind: "trait",
        displayName: "Alpha Trait",
      },
      {
        id: "augment-beta",
        kind: "augment",
        displayName: "Beta Augment",
      },
      {
        id: "item-major",
        kind: "item",
        displayName: "Major Item",
        itemTier: "major",
      },
      {
        id: "item-minor",
        kind: "item",
        displayName: "Minor Item",
        itemTier: "minor",
      },
    ],
    itemSlots: [
      {
        index: 0,
        displayName: "Major item",
        itemTier: "major",
        compatibleItemIds: ["item-major"],
      },
      {
        index: 1,
        displayName: "Minor item",
        itemTier: "minor",
        compatibleItemIds: ["item-minor"],
      },
    ],
    perkGrid: {
      coordinateSystem: {},
      kitLayouts: [
        {
          kitId: "kit-alpha",
          baseBoard: { rows: 5, columns: 5 },
          renderExtent: { rows: 5, columns: 5 },
          placeableCellCount: placeableCells.length,
          placeableCells: placeableCells.map((cell) => ({ ...cell })),
          anchors: [
            {
              role: "primary",
              row: 0,
              column: 0,
              lockedChipId: "ability-primary",
              cells: [{ row: 0, column: 0 }],
            },
          ],
        },
        {
          kitId: "kit-specialist",
          baseBoard: { rows: 5, columns: 5 },
          renderExtent: { rows: 5, columns: 5 },
          placeableCellCount: specialistPlaceableCells.length,
          placeableCells: specialistPlaceableCells.map((cell) => ({ ...cell })),
          anchors: [
            {
              role: "primary",
              row: 0,
              column: 0,
              lockedChipId: "placeholder-specialist-primary",
              cells: [{ row: 0, column: 0 }],
            },
            {
              role: "secondary",
              row: 0,
              column: 4,
              lockedChipId: "placeholder-specialist-secondary",
              cells: [{ row: 0, column: 4 }],
            },
            {
              role: "passive",
              row: 4,
              column: 2,
              lockedChipId: "placeholder-specialist-passive",
              cells: [{ row: 4, column: 2 }],
            },
          ],
        },
      ],
      placementRules: {},
    },
  };
}
