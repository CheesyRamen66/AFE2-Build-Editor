import { describe, expect, it } from "vitest";
import {
  createCatalogueIndex,
  weaponSlotDisplayName,
  type KitRecord,
  type PlannerCatalogue,
} from "./catalogue";

function kit(idLeaf: string, displayName: string): KitRecord {
  return {
    id: `/Game/Blueprints/Avocado_Classes/ClassUnlocks/${idLeaf}`,
    kind: "kit",
    displayName,
    abilitySlots: [],
    selectablePerkIds: [],
    weaponSlots: [],
  };
}

describe("createCatalogueIndex", () => {
  it("orders known kits for the editor and keeps future kits in source order", () => {
    const catalogue: PlannerCatalogue = {
      schemaVersion: 1,
      sourceFingerprint: "kit-order-test",
      game: { buildId: "test", steamAppId: "0" },
      records: [
        kit("KitUnlock_Scout", "Scout"),
        kit("KitUnlock_Custom", "Specialist"),
        kit("KitUnlock_Lancer", "Hunter"),
        kit("KitUnlock_Technician", "Machinist"),
        kit("KitUnlock_Engineer", "Engineer"),
        kit("KitUnlock_Gunner", "Duelist"),
        kit("KitUnlock_Medic", "Medic"),
        kit("KitUnlock_Demolisher", "Marauder"),
      ],
      itemSlots: [],
      perkGrid: {
        coordinateSystem: {},
        kitLayouts: [],
        placementRules: {},
      },
    };
    const sourceOrder = catalogue.records.map((record) => record.id);

    const index = createCatalogueIndex(catalogue);

    expect(index.kits.map((record) => record.displayName)).toEqual([
      "Duelist",
      "Machinist",
      "Marauder",
      "Hunter",
      "Medic",
      "Specialist",
      "Scout",
      "Engineer",
    ]);
    expect(catalogue.records.map((record) => record.id)).toEqual(sourceOrder);
  });
});

describe("weaponSlotDisplayName", () => {
  it("uses the slot's semantic family before its position", () => {
    expect(weaponSlotDisplayName({ index: 0, slotType: "primary" })).toBe("Primary");
    expect(weaponSlotDisplayName({ index: 1, slotType: "primary" })).toBe("Primary");
    expect(weaponSlotDisplayName({ index: 1, slotType: "signature" })).toBe("Signature");
    expect(weaponSlotDisplayName({ index: 2, slotType: "sidearm" })).toBe("Sidearm");
  });

  it("accepts raw enum-style semantic values and hides low-level weapon categories", () => {
    expect(weaponSlotDisplayName({ index: 1, slotType: "EGunAvoType::Primary" }))
      .toBe("Primary");
    expect(weaponSlotDisplayName({ index: 0, slotType: "rifle" })).toBe("Primary");
    expect(weaponSlotDisplayName({ index: 1, slotType: "cqw" })).toBe("Signature");
    expect(weaponSlotDisplayName({ index: 2, slotType: "handgun" })).toBe("Sidearm");
  });
});
