import { beforeEach, describe, expect, it } from "vitest";

import { createSyntheticPlannerCatalogue } from "../test/fixtures/plannerCatalogue";
import { createBuildForKit, type BuildState, type PlacedPerk } from "./build";
import {
  createCatalogueIndex,
  type CatalogueIndex,
  type KitGridLayout,
} from "./catalogue";
import { calculateFamilyConnectors } from "./familyConnectors";

function placed(
  perkId: string,
  row: number,
  column: number,
  targetId?: string,
): PlacedPerk {
  return { perkId, row, column, rotation: "Default", targetId };
}

describe("family connectors", () => {
  let index: CatalogueIndex;
  let layout: KitGridLayout;
  let baseBuild: BuildState;

  beforeEach(() => {
    index = createCatalogueIndex(createSyntheticPlannerCatalogue());
    layout = index.layoutByKitId.get("kit-alpha")!;
    baseBuild = createBuildForKit(index, "kit-alpha");
  });

  it("links an active ability to every valid modifier in its resolved chain", () => {
    const build: BuildState = {
      ...baseBuild,
      perks: [
        placed("perk-modifier", 0, 1, "ability-primary"),
        placed("perk-modifier-b", 0, 2, "perk-modifier"),
      ],
    };

    expect(calculateFamilyConnectors(index, layout, build)).toEqual([
      {
        key: "horizontal:0:0",
        orientation: "horizontal",
        row: 0,
        column: 0,
        familyId: "ability-primary",
        fromNodeId: "ability:0",
        toNodeId: "perk:perk-modifier",
        fromCell: { row: 0, column: 0 },
        toCell: { row: 0, column: 1 },
      },
      {
        key: "horizontal:0:1",
        orientation: "horizontal",
        row: 0,
        column: 1,
        familyId: "ability-primary",
        fromNodeId: "perk:perk-modifier",
        toNodeId: "perk:perk-modifier-b",
        fromCell: { row: 0, column: 1 },
        toCell: { row: 0, column: 2 },
      },
    ]);
  });

  it("emits horizontal and vertical boundaries once while ignoring a chip's own cells", () => {
    const horizontal: BuildState = {
      ...baseBuild,
      perks: [
        placed("perk-core", 1, 1),
        placed("perk-modifier", 1, 2, "perk-core"),
        placed("perk-bar", 3, 0),
      ],
    };
    expect(calculateFamilyConnectors(index, layout, horizontal)).toMatchObject([
      {
        key: "horizontal:1:1",
        orientation: "horizontal",
        familyId: "perk-core",
        fromNodeId: "perk:perk-core",
        toNodeId: "perk:perk-modifier",
      },
    ]);

    const vertical: BuildState = {
      ...baseBuild,
      perks: [
        placed("perk-core", 1, 1),
        placed("perk-modifier", 2, 1, "perk-core"),
      ],
    };
    expect(calculateFamilyConnectors(index, layout, vertical)).toMatchObject([
      {
        key: "vertical:1:1",
        orientation: "vertical",
        row: 1,
        column: 1,
        familyId: "perk-core",
      },
    ]);
  });

  it("does not connect adjacent chips from different terminal families", () => {
    const build: BuildState = {
      ...baseBuild,
      perks: [placed("perk-core", 0, 1)],
    };

    expect(calculateFamilyConnectors(index, layout, build)).toEqual([]);
  });

  it("excludes unresolved, invalid, and explicitly reported modifier branches", () => {
    const unresolved: BuildState = {
      ...baseBuild,
      perks: [placed("perk-modifier", 0, 1)],
    };
    expect(calculateFamilyConnectors(index, layout, unresolved)).toEqual([]);

    const invalidTarget: BuildState = {
      ...baseBuild,
      perks: [placed("perk-modifier", 0, 1, "ability-secondary")],
    };
    expect(calculateFamilyConnectors(index, layout, invalidTarget)).toEqual([]);

    const reported: BuildState = {
      ...baseBuild,
      perks: [
        placed("perk-modifier", 0, 1, "ability-primary"),
        placed("perk-modifier-b", 0, 2, "perk-modifier"),
      ],
    };
    expect(
      calculateFamilyConnectors(index, layout, reported, new Set(["perk-modifier"])),
    ).toEqual([]);
  });

  it("returns no connectors when the layout belongs to another kit", () => {
    const specialistLayout = index.layoutByKitId.get("kit-specialist")!;
    const build: BuildState = {
      ...baseBuild,
      perks: [placed("perk-modifier", 0, 1, "ability-primary")],
    };

    expect(calculateFamilyConnectors(index, specialistLayout, build)).toEqual([]);
  });
});
