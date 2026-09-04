import { beforeEach, describe, expect, it } from "vitest";

import { createSyntheticPlannerCatalogue } from "../test/fixtures/plannerCatalogue";
import {
  attachmentSlotKey,
  availableModifierTargetIds,
  createBuildForKit,
  hydrateLocalBuild,
  nextRotation,
  reduceBuild,
  resolveModifierTargets,
  rotateShape,
  validateGridLinks,
  validatePlacement,
  type BuildState,
  type PlacedPerk,
} from "./build";
import {
  createCatalogueIndex,
  type CatalogueIndex,
  type KitGridLayout,
  type PerkRecord,
  type PerkShape,
  type Rotation,
} from "./catalogue";

function placement(
  perkId: string,
  row: number,
  column: number,
  rotation: Rotation = "Default",
): PlacedPerk {
  return { perkId, row, column, rotation };
}

describe("build model", () => {
  let index: CatalogueIndex;
  let layout: KitGridLayout;

  beforeEach(() => {
    index = createCatalogueIndex(createSyntheticPlannerCatalogue());
    layout = index.layoutByKitId.get("kit-alpha")!;
  });

  describe("perk rotation", () => {
    const asymmetricShape: PerkShape = {
      width: 2,
      height: 3,
      cellCount: 4,
      size: "L",
      occupiedCells: [
        { row: 0, column: 0 },
        { row: 1, column: 0 },
        { row: 2, column: 0 },
        { row: 2, column: 1 },
      ],
    };

    it("rotates an asymmetric footprint in every quarter turn without mutating it", () => {
      expect(rotateShape(asymmetricShape, "Clockwise90")).toMatchObject({
        width: 3,
        height: 2,
        occupiedCells: [
          { row: 0, column: 2 },
          { row: 0, column: 1 },
          { row: 0, column: 0 },
          { row: 1, column: 0 },
        ],
      });
      expect(rotateShape(asymmetricShape, "Clockwise180")).toMatchObject({
        width: 2,
        height: 3,
        occupiedCells: [
          { row: 2, column: 1 },
          { row: 1, column: 1 },
          { row: 0, column: 1 },
          { row: 0, column: 0 },
        ],
      });
      expect(rotateShape(asymmetricShape, "Clockwise270")).toMatchObject({
        width: 3,
        height: 2,
        occupiedCells: [
          { row: 1, column: 0 },
          { row: 1, column: 1 },
          { row: 1, column: 2 },
          { row: 0, column: 2 },
        ],
      });
      expect(asymmetricShape).toMatchObject({
        width: 2,
        height: 3,
        occupiedCells: [
          { row: 0, column: 0 },
          { row: 1, column: 0 },
          { row: 2, column: 0 },
          { row: 2, column: 1 },
        ],
      });
    });

    it("cycles through only the rotations allowed by the perk", () => {
      const perk = index.byId.get("perk-bar") as PerkRecord;

      expect(nextRotation(perk, "Default")).toBe("Clockwise90");
      expect(nextRotation(perk, "Clockwise270")).toBe("Default");
    });
  });

  describe("perk placement", () => {
    it("rejects cells outside the board and cells reserved by the layout", () => {
      const outOfBounds = validatePlacement(
        index,
        layout,
        [],
        placement("perk-bar", 1, 4),
      );
      const abilityAnchor = validatePlacement(
        index,
        layout,
        [],
        placement("perk-core", 0, 0),
      );
      const reservedHole = validatePlacement(
        index,
        layout,
        [],
        placement("perk-core", 2, 2),
      );

      expect(outOfBounds).toMatchObject({ valid: false, reason: "The perk does not fit at F2." });
      expect(abilityAnchor).toMatchObject({ valid: false, reason: "The perk does not fit at A1." });
      expect(reservedHole).toMatchObject({ valid: false, reason: "The perk does not fit at C3." });
    });

    it("rejects overlaps and placing the same perk twice", () => {
      const placed = [placement("perk-bar", 1, 1)];

      expect(
        validatePlacement(index, layout, placed, placement("perk-core", 1, 2)),
      ).toMatchObject({ valid: false, reason: "C2 is already occupied." });
      expect(
        validatePlacement(index, layout, placed, placement("perk-bar", 3, 0)),
      ).toMatchObject({ valid: false, reason: "Each perk can only be placed once." });
    });

    it("rejects a catalogue perk that is not selectable by the current kit", () => {
      const state = createBuildForKit(index, "kit-alpha");
      const rejected = reduceBuild(index, state, {
        type: "place-perk",
        placement: placement("perk-foreign", 4, 4),
      });

      expect(rejected).toBe(state);
      expect(rejected.perks).toEqual([]);
    });
  });

  describe("kit and equipment selection", () => {
    it("creates the kit's default weapon with trait slots empty", () => {
      const state = createBuildForKit(index, "kit-alpha");

      expect(state.weapons).toEqual([
        {
          slotIndex: 0,
          weaponId: "weapon-alpha",
          attachments: {
            "component:0:magazine": null,
            "trait:1:trait": null,
          },
        },
      ]);
      expect(state.abilityIds).toEqual(["ability-primary"]);
      expect(state.itemIds).toEqual([null, null]);
    });

    it("initializes and hydrates unresolved Specialist ability placeholders as empty slots", () => {
      const initial = createBuildForKit(index, "kit-specialist");

      expect(initial.abilityIds).toEqual([null, null, null]);

      let selected = reduceBuild(index, initial, {
        type: "select-ability",
        slotIndex: 0,
        abilityId: "ability-alternate",
      });
      selected = reduceBuild(index, selected, {
        type: "select-ability",
        slotIndex: 1,
        abilityId: "ability-secondary",
      });
      selected = reduceBuild(index, selected, {
        type: "select-ability",
        slotIndex: 2,
        abilityId: "ability-passive",
      });

      expect(selected.abilityIds).toEqual([
        "ability-alternate",
        "ability-secondary",
        "ability-passive",
      ]);
      expect(hydrateLocalBuild(index, JSON.stringify(selected))?.abilityIds).toEqual(
        selected.abilityIds,
      );
    });

    it("resets one ability or the whole grid to each kit's authored defaults", () => {
      let standard = createBuildForKit(index, "kit-alpha");
      standard = reduceBuild(index, standard, {
        type: "select-ability",
        slotIndex: 0,
        abilityId: "ability-alternate",
      });
      standard = reduceBuild(index, standard, {
        type: "place-perk",
        placement: placement("perk-core", 1, 1),
      });

      const resetStandardAbility = reduceBuild(index, standard, {
        type: "reset-ability",
        slotIndex: 0,
      });
      expect(resetStandardAbility.abilityIds).toEqual(["ability-primary"]);
      expect(resetStandardAbility.perks).toHaveLength(1);

      const clearedStandardGrid = reduceBuild(index, standard, { type: "clear-perks" });
      expect(clearedStandardGrid.abilityIds).toEqual(["ability-primary"]);
      expect(clearedStandardGrid.perks).toEqual([]);

      let specialist = createBuildForKit(index, "kit-specialist");
      specialist = reduceBuild(index, specialist, {
        type: "select-ability",
        slotIndex: 0,
        abilityId: "ability-primary",
      });
      specialist = reduceBuild(index, specialist, {
        type: "select-ability",
        slotIndex: 1,
        abilityId: "ability-secondary",
      });
      specialist = reduceBuild(index, specialist, {
        type: "select-ability",
        slotIndex: 2,
        abilityId: "ability-passive",
      });
      specialist = reduceBuild(index, specialist, {
        type: "place-perk",
        placement: placement("perk-core", 1, 1),
      });

      const resetSpecialistAbility = reduceBuild(index, specialist, {
        type: "reset-ability",
        slotIndex: 1,
      });
      expect(resetSpecialistAbility.abilityIds).toEqual([
        "ability-primary",
        null,
        "ability-passive",
      ]);
      expect(resetSpecialistAbility.perks).toHaveLength(1);

      const clearedSpecialistGrid = reduceBuild(index, specialist, { type: "clear-perks" });
      expect(clearedSpecialistGrid.abilityIds).toEqual([null, null, null]);
      expect(clearedSpecialistGrid.perks).toEqual([]);
    });

    it("clears the old attachment map when the selected weapon changes", () => {
      const initial = createBuildForKit(index, "kit-alpha");
      const alphaWeapon = index.byId.get("weapon-alpha");
      if (!alphaWeapon || alphaWeapon.kind !== "weapon") throw new Error("Missing fixture weapon");
      const magazineKey = attachmentSlotKey(alphaWeapon.componentSlots[0]);
      const customized = reduceBuild(index, initial, {
        type: "select-attachment",
        weaponSlotIndex: 0,
        attachmentKey: magazineKey,
        recordId: "mod-alpha",
      });

      expect(customized.weapons[0].attachments[magazineKey]).toBe("mod-alpha");

      const swapped = reduceBuild(index, customized, {
        type: "select-weapon",
        slotIndex: 0,
        weaponId: "weapon-beta",
      });

      expect(swapped.weapons[0]).toEqual({
        slotIndex: 0,
        weaponId: "weapon-beta",
        attachments: {
          "component:0:muzzle": null,
          "augment:1:augment": "augment-beta",
        },
      });
      expect(swapped.weapons[0].attachments).not.toHaveProperty(magazineKey);
    });

    it("defaults traits empty while preserving explicit saved trait selections", () => {
      const initial = createBuildForKit(index, "kit-alpha");
      const alphaWeapon = index.byId.get("weapon-alpha");
      if (!alphaWeapon || alphaWeapon.kind !== "weapon") throw new Error("Missing fixture weapon");
      const traitSlot = alphaWeapon.compatibility.traitSlot;
      if (!traitSlot) throw new Error("Missing fixture trait slot");
      const traitKey = attachmentSlotKey(traitSlot);

      expect(initial.weapons[0].attachments[traitKey]).toBeNull();

      const explicitlySelected = reduceBuild(index, initial, {
        type: "select-attachment",
        weaponSlotIndex: 0,
        attachmentKey: traitKey,
        recordId: "trait-alpha",
      });
      const selectedRoundTrip = hydrateLocalBuild(index, JSON.stringify(explicitlySelected));

      expect(selectedRoundTrip?.weapons[0].attachments[traitKey]).toBe("trait-alpha");

      const missingKey = createBuildForKit(index, "kit-alpha");
      delete missingKey.weapons[0].attachments[traitKey];
      const missingKeyRoundTrip = hydrateLocalBuild(index, JSON.stringify(missingKey));

      expect(missingKeyRoundTrip?.weapons[0].attachments[traitKey]).toBeNull();
    });

    it("falls back to the first compatible weapon when a slot has no authored default", () => {
      const catalogue = createSyntheticPlannerCatalogue();
      const kit = catalogue.records.find((record) => record.id === "kit-alpha");
      if (!kit || kit.kind !== "kit") throw new Error("Missing fixture kit");
      delete kit.weaponSlots[0].defaultWeaponId;
      kit.weaponSlots[0].compatibleWeaponIds = ["weapon-beta", "weapon-alpha"];

      const fallbackIndex = createCatalogueIndex(catalogue);
      const state = createBuildForKit(fallbackIndex, kit.id);

      expect(state.weapons).toEqual([
        {
          slotIndex: 0,
          weaponId: "weapon-beta",
          attachments: {
            "component:0:muzzle": null,
            "augment:1:augment": "augment-beta",
          },
        },
      ]);
    });

    it("skips missing weapon references while choosing a default", () => {
      const catalogue = createSyntheticPlannerCatalogue();
      const kit = catalogue.records.find((record) => record.id === "kit-alpha");
      if (!kit || kit.kind !== "kit") throw new Error("Missing fixture kit");
      kit.weaponSlots[0].defaultWeaponId = "weapon-missing";
      kit.weaponSlots[0].compatibleWeaponIds = ["weapon-missing", "weapon-beta"];

      const fallbackIndex = createCatalogueIndex(catalogue);
      const state = createBuildForKit(fallbackIndex, kit.id);

      expect(state.weapons[0]?.weaponId).toBe("weapon-beta");
    });

    it("accepts only items compatible with the selected item slot and permits clearing", () => {
      const initial = createBuildForKit(index, "kit-alpha");
      const selected = reduceBuild(index, initial, {
        type: "select-item",
        slotIndex: 0,
        itemId: "item-major",
      });

      expect(selected.itemIds).toEqual(["item-major", null]);

      const incompatible = reduceBuild(index, selected, {
        type: "select-item",
        slotIndex: 0,
        itemId: "item-minor",
      });
      expect(incompatible).toBe(selected);

      const cleared = reduceBuild(index, selected, {
        type: "select-item",
        slotIndex: 0,
        itemId: null,
      });
      expect(cleared.itemIds).toEqual([null, null]);
    });

    it("preserves non-contiguous ability and item slot indexes through create, select, and hydrate", () => {
      const catalogue = createSyntheticPlannerCatalogue();
      const kit = catalogue.records.find((record) => record.id === "kit-alpha");
      if (!kit || kit.kind !== "kit") throw new Error("Missing fixture kit");
      kit.abilitySlots[0].index = 2;
      catalogue.itemSlots[0].index = 1;
      catalogue.itemSlots[1].index = 4;

      const sparseIndex = createCatalogueIndex(catalogue);
      const created = createBuildForKit(sparseIndex, kit.id);

      expect(created.abilityIds).toHaveLength(3);
      expect(created.abilityIds[0]).toBeNull();
      expect(created.abilityIds[2]).toBe("ability-primary");
      expect(created.itemIds).toHaveLength(5);
      expect(created.itemIds[0]).toBeUndefined();
      expect(created.itemIds[1]).toBeNull();
      expect(created.itemIds[4]).toBeNull();

      let selected = reduceBuild(sparseIndex, created, {
        type: "select-ability",
        slotIndex: 2,
        abilityId: "ability-alternate",
      });
      selected = reduceBuild(sparseIndex, selected, {
        type: "select-item",
        slotIndex: 1,
        itemId: "item-major",
      });
      selected = reduceBuild(sparseIndex, selected, {
        type: "select-item",
        slotIndex: 4,
        itemId: "item-minor",
      });

      const hydrated = hydrateLocalBuild(sparseIndex, JSON.stringify(selected));

      expect(hydrated?.abilityIds).toHaveLength(3);
      expect(hydrated?.abilityIds[0]).toBeNull();
      expect(hydrated?.abilityIds[2]).toBe("ability-alternate");
      expect(hydrated?.itemIds).toHaveLength(5);
      expect(hydrated?.itemIds[0]).toBeUndefined();
      expect(hydrated?.itemIds[1]).toBe("item-major");
      expect(hydrated?.itemIds[4]).toBe("item-minor");
    });
  });

  describe("modifier links", () => {
    function stateWithModifierAt(row: number, column: number): BuildState {
      const state = createBuildForKit(index, "kit-alpha");
      return resolveModifierTargets(index, {
        ...state,
        perks: [placement("perk-modifier", row, column)],
      });
    }

    it("resolves an orthogonally adjacent compatible ability as the target", () => {
      const resolved = stateWithModifierAt(0, 1);

      expect(resolved.perks[0].targetId).toBe("ability-primary");
      expect(validateGridLinks(index, resolved)).toEqual([]);
    });

    it("does not connect a diagonally adjacent modifier", () => {
      const resolved = stateWithModifierAt(1, 1);

      expect(resolved.perks[0].targetId).toBeUndefined();
      expect(validateGridLinks(index, resolved)).toEqual([
        expect.objectContaining({
          code: "disconnected-modifier",
          perkId: "perk-modifier",
        }),
      ]);
    });

    it("preserves an explicit target when both a core and ability are valid", () => {
      let state = createBuildForKit(index, "kit-alpha");
      state = reduceBuild(index, state, {
        type: "place-perk",
        placement: placement("perk-core", 0, 2),
      });
      state = reduceBuild(index, state, {
        type: "place-perk",
        placement: placement("perk-modifier", 0, 1),
      });

      expect(availableModifierTargetIds(index, state, "perk-modifier")).toEqual([
        "ability-primary",
        "perk-core",
      ]);
      expect(state.perks.find((entry) => entry.perkId === "perk-modifier")?.targetId).toBe(
        "ability-primary",
      );

      const selected = reduceBuild(index, state, {
        type: "select-perk-target",
        perkId: "perk-modifier",
        targetId: "perk-core",
      });

      expect(selected.perks.find((entry) => entry.perkId === "perk-modifier")?.targetId).toBe(
        "perk-core",
      );
      expect(resolveModifierTargets(index, selected)).toEqual(selected);
    });

    it("excludes and rejects a modifier target that would create a cycle", () => {
      let state = createBuildForKit(index, "kit-alpha");
      for (const nextPlacement of [
        placement("perk-core", 3, 3),
        placement("perk-modifier-b", 3, 2),
        placement("perk-modifier", 3, 1),
      ]) {
        state = reduceBuild(index, state, { type: "place-perk", placement: nextPlacement });
      }
      state = reduceBuild(index, state, {
        type: "select-perk-target",
        perkId: "perk-modifier-b",
        targetId: "perk-modifier",
      });

      expect(
        state.perks.find((entry) => entry.perkId === "perk-modifier")?.targetId,
      ).toBe("perk-core");
      expect(
        state.perks.find((entry) => entry.perkId === "perk-modifier-b")?.targetId,
      ).toBe("perk-modifier");
      expect(availableModifierTargetIds(index, state, "perk-modifier")).toEqual([
        "perk-core",
      ]);

      const rejected = reduceBuild(index, state, {
        type: "select-perk-target",
        perkId: "perk-modifier",
        targetId: "perk-modifier-b",
      });

      expect(rejected).toBe(state);
    });
  });
});
