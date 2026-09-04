import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createBuildForKit } from "../model/build";
import { createCatalogueIndex } from "../model/catalogue";
import { createSyntheticPlannerCatalogue } from "../test/fixtures/plannerCatalogue";
import { ItemLoadout } from "./ItemLoadout";

afterEach(cleanup);

describe("ItemLoadout", () => {
  it("renders Minor above Major without section chrome or slot numbers", () => {
    const index = createCatalogueIndex(createSyntheticPlannerCatalogue());
    const build = createBuildForKit(index, "kit-alpha");

    render(<ItemLoadout index={index} build={build} onChooseItem={vi.fn()} />);

    expect(screen.getByRole("region", { name: "Items" })).toBeInTheDocument();
    expect(screen.queryByText("04", { exact: true })).not.toBeInTheDocument();
    expect(screen.queryByText("Mission support", { exact: true })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Items" })).not.toBeInTheDocument();
    expect(screen.queryByText("One Major and one Minor item, as defined by the game’s inventory slots."))
      .not.toBeInTheDocument();

    const itemCards = screen.getAllByRole("button", { name: /Choose item\.$/i });
    expect(itemCards).toHaveLength(2);
    expect(itemCards.map((card) => card.getAttribute("aria-label"))).toEqual([
      "Minor item: empty. Choose item.",
      "Major item: empty. Choose item.",
    ]);
    expect(document.querySelector(".slot-number")).not.toBeInTheDocument();
    expect(document.querySelector(".item-card__tier")).not.toBeInTheDocument();
  });

  it("uses the attachment-slot plus glyph for empty items and keeps each card interactive", () => {
    const index = createCatalogueIndex(createSyntheticPlannerCatalogue());
    const build = createBuildForKit(index, "kit-alpha");
    const onChooseItem = vi.fn();

    render(<ItemLoadout index={index} build={build} onChooseItem={onChooseItem} />);

    const emptyMinor = screen.getByRole("button", {
      name: "Minor item: empty. Choose item.",
    });
    const emptyIcons = document.querySelectorAll(".item-card__visual > .lucide-plus");
    expect(emptyIcons).toHaveLength(2);
    expect(document.querySelector(".lucide-package-open")).not.toBeInTheDocument();

    fireEvent.click(emptyMinor);
    expect(onChooseItem).toHaveBeenCalledWith(
      expect.objectContaining({ displayName: "Minor item", itemTier: "minor" }),
    );
  });
});
