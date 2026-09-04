import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { createCatalogueIndex, type KitRecord } from "./model/catalogue";
import { createSyntheticPlannerCatalogue } from "./test/fixtures/plannerCatalogue";
import { BuildEditor } from "./App";

afterEach(() => {
  cleanup();
  localStorage.clear();
});

describe("BuildEditor chrome", () => {
  it("leaves the future account slot empty and shows the indexed Steam build in the footer", () => {
    const index = createCatalogueIndex(createSyntheticPlannerCatalogue());

    render(<BuildEditor index={index} />);

    expect(screen.queryByText("Local draft", { exact: true })).not.toBeInTheDocument();
    expect(screen.queryByText("Saved in this browser", { exact: true })).not.toBeInTheDocument();
    expect(screen.queryByText("Local data boundary", { exact: true })).not.toBeInTheDocument();
    expect(screen.queryByText("Hosting-ready IDs", { exact: true })).not.toBeInTheDocument();
    expect(screen.getByText(/STEAM BUILD test-build/)).toBeInTheDocument();
  });

  it("renders the complete AFE2 brand mark", () => {
    const index = createCatalogueIndex(createSyntheticPlannerCatalogue());

    render(<BuildEditor index={index} />);

    const brand = screen.getByRole("link", { name: "AFE2 Build Editor home" });
    expect(brand.querySelector(".brand__mark")).toHaveTextContent("AFE2");
  });

  it("shows the site sections without numeric prefixes", () => {
    const index = createCatalogueIndex(createSyntheticPlannerCatalogue());

    render(<BuildEditor index={index} />);

    const navigation = screen.getByRole("navigation", { name: "Site sections" });
    expect(within(navigation).getByRole("link", { name: "Editor" })).toBeInTheDocument();
    expect(within(navigation).getByRole("button", { name: "Builds (not available yet)" }))
      .toBeInTheDocument();
    expect(within(navigation).getByRole("button", { name: "Database (not available yet)" }))
      .toBeInTheDocument();
    expect(navigation).not.toHaveTextContent(/01|02|03/);
  });

  it("labels a second primary-family weapon slot as Primary in its card and picker", () => {
    const catalogue = createSyntheticPlannerCatalogue();
    const kit = catalogue.records.find((record): record is KitRecord => (
      record.kind === "kit" && record.id === "kit-alpha"
    ));
    if (!kit) throw new Error("Synthetic kit fixture is missing");
    const sourceSlot = kit.weaponSlots[0];
    kit.displayName = "Duelist";
    kit.weaponSlots = [
      sourceSlot,
      {
        ...sourceSlot,
        index: 1,
        slotType: "primary",
        weaponType: "cqw",
        weaponSubtype: "shotgun",
      },
    ];
    const index = createCatalogueIndex(catalogue);

    render(<BuildEditor index={index} />);

    const weaponCards = document.querySelectorAll<HTMLElement>(".weapon-card");
    expect(weaponCards).toHaveLength(2);
    expect([...document.querySelectorAll(".weapon-card__slot strong")].map(
      (label) => label.textContent,
    )).toEqual(["Primary", "Primary"]);

    fireEvent.click(within(weaponCards[1]).getByRole("button", {
      name: /Choose weapon for Primary slot/i,
    }));
    const dialog = screen.getByRole("dialog", { name: "Choose Primary weapon" });
    expect(dialog.querySelector(".eyebrow")).not.toBeInTheDocument();
    expect(screen.queryByText("Duelist · Primary", { exact: true })).not.toBeInTheDocument();
  });

  it("places the item region after the three-weapon region in one loadout row", () => {
    const index = createCatalogueIndex(createSyntheticPlannerCatalogue());

    render(<BuildEditor index={index} />);

    const row = document.querySelector(".loadout-row");
    expect(row).not.toBeNull();
    expect([...row!.children]).toEqual([
      screen.getByRole("region", { name: "Weapons" }),
      screen.getByRole("region", { name: "Items" }),
    ]);
  });
});
