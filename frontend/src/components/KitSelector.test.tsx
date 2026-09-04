import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createCatalogueIndex } from "../model/catalogue";
import { createSyntheticPlannerCatalogue } from "../test/fixtures/plannerCatalogue";
import { KitSelector } from "./KitSelector";

afterEach(cleanup);

describe("KitSelector", () => {
  it("presents the kit choices without a heading or sequence numbers", () => {
    const index = createCatalogueIndex(createSyntheticPlannerCatalogue());
    const onSelect = vi.fn();

    render(
      <KitSelector
        kits={index.kits}
        selectedKitId="kit-alpha"
        onSelect={onSelect}
      />,
    );

    expect(screen.getByLabelText("Kit selector")).toBeInTheDocument();
    expect(screen.getByRole("radiogroup", { name: "Available kits" })).toBeInTheDocument();
    expect(screen.queryByText("Choose your role", { exact: true })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Kit" })).not.toBeInTheDocument();
    expect(document.querySelector(".kit-card__number")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("radio", { name: "Specialist" }));
    expect(onSelect).toHaveBeenCalledWith("kit-specialist");
  });
});
