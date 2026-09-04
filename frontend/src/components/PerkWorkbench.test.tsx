import { cleanup, createEvent, fireEvent, render, screen, within } from "@testing-library/react";
import { useReducer } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createBuildForKit,
  reduceBuild,
  type BuildAction,
  type BuildState,
} from "../model/build";
import { createCatalogueIndex } from "../model/catalogue";
import { createSyntheticPlannerCatalogue } from "../test/fixtures/plannerCatalogue";
import { PerkWorkbench } from "./PerkWorkbench";

afterEach(cleanup);

function renderWorkbench(buildOverride?: Partial<BuildState>) {
  const index = createCatalogueIndex(createSyntheticPlannerCatalogue());
  const kit = index.kits.find((candidate) => candidate.id === "kit-alpha")!;
  const layout = index.layoutByKitId.get(kit.id)!;
  const build = { ...createBuildForKit(index, kit.id), ...buildOverride };
  const dispatch = vi.fn();

  render(
    <PerkWorkbench
      index={index}
      kit={kit}
      layout={layout}
      build={build}
      dispatch={dispatch}
      onChooseAbility={vi.fn()}
      notify={vi.fn()}
    />,
  );

  return { dispatch };
}

function renderStatefulWorkbench() {
  const index = createCatalogueIndex(createSyntheticPlannerCatalogue());
  const kit = index.kits.find((candidate) => candidate.id === "kit-alpha")!;
  const layout = index.layoutByKitId.get(kit.id)!;

  function Harness() {
    const [build, dispatch] = useReducer(
      (state: BuildState, action: BuildAction) => reduceBuild(index, state, action),
      createBuildForKit(index, kit.id),
    );
    return (
      <PerkWorkbench
        index={index}
        kit={kit}
        layout={layout}
        build={build}
        dispatch={dispatch}
        onChooseAbility={vi.fn()}
        notify={vi.fn()}
      />
    );
  }

  render(<Harness />);
}

function mockGridGeometry() {
  const board = document.querySelector<HTMLElement>(".perk-board")!;
  board.style.columnGap = "6px";
  board.style.rowGap = "6px";
  const boardRect = {
    x: 100,
    y: 100,
    top: 100,
    right: 410,
    bottom: 410,
    left: 100,
    width: 310,
    height: 310,
    toJSON: () => ({}),
  };
  vi.spyOn(board, "getBoundingClientRect").mockReturnValue(boardRect);
  for (const cell of board.querySelectorAll<HTMLElement>(".perk-cell")) {
    const row = Number(cell.dataset.row);
    const column = Number(cell.dataset.column);
    const left = 113 + column * 58;
    const top = 113 + row * 58;
    vi.spyOn(cell, "getBoundingClientRect").mockReturnValue({
      x: left,
      y: top,
      top,
      right: left + 52,
      bottom: top + 52,
      left,
      width: 52,
      height: 52,
      toJSON: () => ({}),
    });
  }
  return board;
}

describe("PerkWorkbench pickup interaction", () => {
  it("asks which terminal family owns a modifier placed against two families", () => {
    renderStatefulWorkbench();
    const board = mockGridGeometry();

    fireEvent.click(screen.getByRole("button", {
      name: "Pick up Core Perk for placement",
    }), { clientX: 700, clientY: 120 });
    fireEvent.click(board.querySelector<HTMLElement>(
      ".perk-cell[data-row='0'][data-column='2']",
    )!);

    fireEvent.click(screen.getByRole("button", {
      name: "Pick up Linked Modifier for placement",
    }), { clientX: 700, clientY: 120 });
    fireEvent.click(board.querySelector<HTMLElement>(
      ".perk-cell[data-row='0'][data-column='1']",
    )!);

    const dialog = screen.getByRole("dialog", {
      name: /Choose a family for Linked Modifier/i,
    });
    const primaryChoice = within(dialog).getByRole("button", { name: /Primary Ability/i });
    const coreChoice = within(dialog).getByRole("button", { name: /Core Perk/i });
    expect(primaryChoice).toBeInTheDocument();
    expect(coreChoice).toBeInTheDocument();
    fireEvent.click(coreChoice);

    expect(screen.queryByRole("dialog", {
      name: /Choose a family for Linked Modifier/i,
    })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Linked Modifier, 1×1, at B1/ }))
      .toHaveAttribute("data-link-status", "linked");
    const connectors = document.querySelectorAll(".family-connector");
    expect(connectors).toHaveLength(1);
    expect(connectors[0]).toHaveAttribute("data-family-id", "perk-core");
  });

  it("uses the active compatibility family without prompting on ambiguous placement", () => {
    renderStatefulWorkbench();
    const board = mockGridGeometry();

    fireEvent.click(screen.getByRole("button", {
      name: "Pick up Core Perk for placement",
    }), { clientX: 700, clientY: 120 });
    fireEvent.click(board.querySelector<HTMLElement>(
      ".perk-cell[data-row='0'][data-column='2']",
    )!);

    const primaryAbility = screen.getByRole("button", {
      name: /primary ability: Primary Ability/i,
    });
    fireEvent.mouseEnter(primaryAbility);
    fireEvent.keyDown(window, { key: "r" });
    expect(screen.getByRole("button", { name: "Show all perks" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", {
      name: "Pick up Linked Modifier for placement",
    }), { clientX: 700, clientY: 120 });
    fireEvent.click(board.querySelector<HTMLElement>(
      ".perk-cell[data-row='0'][data-column='1']",
    )!);

    expect(screen.queryByRole("dialog", {
      name: /Choose a family for Linked Modifier/i,
    })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Linked Modifier, 1×1, at B1/ }))
      .toHaveAttribute("data-link-status", "linked");
    const connectors = document.querySelectorAll(".family-connector");
    expect(connectors).toHaveLength(1);
    expect(connectors[0]).toHaveAttribute("data-family-id", "ability-primary");
  });

  it("targets a newly mounted brick with D and F before mouse re-entry", () => {
    renderStatefulWorkbench();
    const board = mockGridGeometry();

    fireEvent.click(screen.getByRole("button", { name: "Pick up Bar Perk for placement" }), {
      clientX: 700,
      clientY: 120,
    });
    fireEvent.pointerMove(window, { clientX: 224, clientY: 198 });
    fireEvent.click(board, { clientX: 224, clientY: 198 });
    expect(screen.getByRole("button", { name: /^Bar Perk, 2×1, at B2/ })).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "d" });
    expect(screen.getByRole("button", { name: /^Bar Perk, 1×2, at B2/ })).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "f" });
    expect(screen.queryByRole("button", { name: /^Bar Perk,/ })).not.toBeInTheDocument();
  });

  it("targets a newly mounted core with R before mouse re-entry", () => {
    renderStatefulWorkbench();
    const board = mockGridGeometry();

    fireEvent.click(screen.getByRole("button", { name: "Pick up Core Perk for placement" }), {
      clientX: 700,
      clientY: 120,
    });
    fireEvent.pointerMove(window, { clientX: 224, clientY: 198 });
    fireEvent.click(board, { clientX: 224, clientY: 198 });
    expect(screen.getByRole("button", { name: /^Core Perk, 1×1, at B2/ })).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "r" });
    expect(screen.getByRole("button", { name: "Show all perks" })).toBeInTheDocument();
  });

  it("attaches a clicked library perk to the pointer until it is placed", () => {
    const { dispatch } = renderWorkbench();
    const board = mockGridGeometry();

    fireEvent.click(screen.getByRole("button", { name: "Pick up Bar Perk for placement" }), {
      clientX: 700,
      clientY: 120,
    });

    const preview = screen.getByTestId("perk-cursor-preview");
    expect(preview).toHaveAttribute("data-placement-mode", "new");
    expect(preview).toHaveStyle({ width: "110px", height: "52px" });

    // A1 is blocked by the ability anchor, so the closest shape-fitting origin
    // magnetizes to B1 without occupancy influencing the choice.
    fireEvent.pointerMove(window, { clientX: 224, clientY: 140 });
    expect(preview).toHaveAttribute("data-snap-row", "0");
    expect(preview).toHaveAttribute("data-snap-column", "1");
    expect(preview).toHaveAttribute("data-snap-state", "valid");
    expect(preview.style.transform).toBe("translate3d(171px, 113px, 0)");

    fireEvent.click(board, { clientX: 224, clientY: 140 });
    expect(dispatch).toHaveBeenCalledWith(expect.objectContaining({
      type: "place-perk",
      placement: expect.objectContaining({ perkId: "perk-bar", row: 0, column: 1 }),
    }));
    expect(screen.queryByTestId("perk-cursor-preview")).not.toBeInTheDocument();
  });

  it("keeps the exact grabbed part of an installed brick under the pointer", () => {
    const { dispatch } = renderWorkbench({
      perks: [{ perkId: "perk-bar", row: 1, column: 0, rotation: "Default" }],
    });
    const board = mockGridGeometry();
    const placed = screen.getByRole("button", { name: /^Bar Perk, 2×1, at A2/ });
    vi.spyOn(placed, "getBoundingClientRect").mockReturnValue({
      x: 113,
      y: 171,
      top: 171,
      right: 223,
      bottom: 223,
      left: 113,
      width: 110,
      height: 52,
      toJSON: () => ({}),
    });

    // Pick up the brick near the right edge, inside its second grid segment.
    fireEvent.click(placed, { clientX: 213, clientY: 191 });

    const preview = screen.getByTestId("perk-cursor-preview");
    expect(preview).toHaveStyle({ width: "110px", height: "52px" });
    expect(preview.style.transform).toBe("translate3d(113px, 171px, 0)");

    fireEvent.pointerMove(window, { clientX: 329, clientY: 191 });
    expect(preview).toHaveAttribute("data-snap-row", "1");
    expect(preview).toHaveAttribute("data-snap-column", "2");
    expect(preview.style.transform).toBe("translate3d(229px, 171px, 0)");

    fireEvent.click(board, { clientX: 329, clientY: 191 });
    expect(dispatch).toHaveBeenCalledWith({
      type: "move-perk",
      perkId: "perk-bar",
      row: 1,
      column: 2,
    });
  });

  it("rotates the grab point with a held brick", () => {
    const { dispatch } = renderWorkbench();
    const board = mockGridGeometry();

    fireEvent.click(screen.getByRole("button", { name: "Pick up Bar Perk for placement" }), {
      clientX: 700,
      clientY: 120,
    });
    fireEvent.click(screen.getByRole("button", { name: /Rotate/ }));

    const preview = screen.getByTestId("perk-cursor-preview");
    expect(preview).toHaveStyle({ width: "52px", height: "110px" });

    fireEvent.pointerMove(window, { clientX: 197, clientY: 226 });
    expect(preview).toHaveAttribute("data-snap-row", "1");
    expect(preview).toHaveAttribute("data-snap-column", "1");
    expect(preview.style.transform).toBe("translate3d(171px, 171px, 0)");

    fireEvent.click(board, { clientX: 197, clientY: 226 });
    expect(dispatch).toHaveBeenCalledWith(expect.objectContaining({
      type: "place-perk",
      placement: expect.objectContaining({
        row: 1,
        column: 1,
        rotation: "Clockwise90",
      }),
    }));
  });

  it("preserves the grabbed segment during a native drag", () => {
    const { dispatch } = renderWorkbench({
      perks: [{ perkId: "perk-bar", row: 1, column: 0, rotation: "Default" }],
    });
    const board = mockGridGeometry();
    const placed = screen.getByRole("button", { name: /^Bar Perk, 2×1, at A2/ });
    vi.spyOn(placed, "getBoundingClientRect").mockReturnValue({
      x: 113,
      y: 171,
      top: 171,
      right: 223,
      bottom: 223,
      left: 113,
      width: 110,
      height: 52,
      toJSON: () => ({}),
    });
    const values = new Map<string, string>();
    const dataTransfer = {
      effectAllowed: "none",
      getData: vi.fn((type: string) => values.get(type) ?? ""),
      setData: vi.fn((type: string, value: string) => values.set(type, value)),
      setDragImage: vi.fn(),
    };

    const dragStart = createEvent.dragStart(placed, { dataTransfer });
    Object.defineProperties(dragStart, {
      clientX: { value: 213 },
      clientY: { value: 191 },
    });
    fireEvent(placed, dragStart);
    expect(dataTransfer.setDragImage).toHaveBeenCalledWith(placed, 100, 20);
    const drop = createEvent.drop(board, { dataTransfer });
    Object.defineProperties(drop, {
      clientX: { value: 329 },
      clientY: { value: 191 },
    });
    fireEvent(board, drop);

    expect(dispatch).toHaveBeenCalledWith({
      type: "move-perk",
      perkId: "perk-bar",
      row: 1,
      column: 2,
    });
  });

  it("picks up an installed perk without leaving a selected state or selected-only controls", () => {
    const { dispatch } = renderWorkbench({
      perks: [{ perkId: "perk-bar", row: 1, column: 0, rotation: "Default" }],
    });
    const board = mockGridGeometry();

    fireEvent.click(screen.getByRole("button", { name: /^Bar Perk, 2×1, at A2/ }), {
      clientX: 680,
      clientY: 160,
    });

    expect(screen.getByTestId("perk-cursor-preview")).toHaveAttribute("data-placement-mode", "move");
    expect(document.querySelector(".placed-perk.is-moving")).toBeInTheDocument();
    expect(document.querySelector(".placed-perk.is-selected")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Move" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove" })).not.toBeInTheDocument();

    fireEvent.pointerMove(window, { clientX: 284, clientY: 313 });
    fireEvent.click(board, { clientX: 284, clientY: 313 });
    expect(dispatch).toHaveBeenCalledWith(expect.objectContaining({
      type: "move-perk",
      perkId: "perk-bar",
    }));
    expect(screen.queryByTestId("perk-cursor-preview")).not.toBeInTheDocument();
  });

  it("cancels an unplaced perk cleanly when a native drag ends outside the grid", () => {
    renderWorkbench();
    const perk = screen.getByRole("button", { name: "Pick up Bar Perk for placement" });
    const dataTransfer = {
      effectAllowed: "none",
      setData: vi.fn(),
    };

    fireEvent.dragStart(perk, { dataTransfer });
    expect(perk).toHaveClass("is-pending");

    fireEvent.dragEnd(perk, { dataTransfer });
    expect(perk).not.toHaveClass("is-pending");
    expect(screen.queryByTestId("perk-cursor-preview")).not.toBeInTheDocument();
    expect(document.querySelectorAll(".perk-cell.is-legal-footprint")).toHaveLength(0);
  });

  it("shows the nearest fitting overlap in red and refuses to drop it", () => {
    const { dispatch } = renderWorkbench({
      perks: [{ perkId: "perk-core", row: 0, column: 1, rotation: "Default" }],
    });
    const board = mockGridGeometry();

    fireEvent.click(screen.getByRole("button", { name: "Pick up Bar Perk for placement" }), {
      clientX: 700,
      clientY: 120,
    });
    fireEvent.pointerMove(window, { clientX: 224, clientY: 140 });

    const preview = screen.getByTestId("perk-cursor-preview");
    expect(preview).toHaveAttribute("data-snap-row", "0");
    expect(preview).toHaveAttribute("data-snap-column", "1");
    expect(preview).toHaveAttribute("data-snap-state", "overlap");

    fireEvent.click(board, { clientX: 224, clientY: 140 });
    expect(dispatch).not.toHaveBeenCalled();
    expect(screen.getByTestId("perk-cursor-preview")).toHaveAttribute(
      "data-snap-state",
      "overlap",
    );
  });

  it("uses F to discard a new held brick or remove a held installed brick", () => {
    const first = renderWorkbench();
    mockGridGeometry();
    fireEvent.click(screen.getByRole("button", { name: "Pick up Bar Perk for placement" }), {
      clientX: 700,
      clientY: 120,
    });
    fireEvent.keyDown(window, { key: "f" });
    expect(screen.queryByTestId("perk-cursor-preview")).not.toBeInTheDocument();
    expect(first.dispatch).not.toHaveBeenCalled();

    cleanup();
    const second = renderWorkbench({
      perks: [{ perkId: "perk-bar", row: 1, column: 0, rotation: "Default" }],
    });
    mockGridGeometry();
    fireEvent.click(screen.getByRole("button", { name: /^Bar Perk, 2×1, at A2/ }), {
      clientX: 700,
      clientY: 120,
    });
    fireEvent.keyDown(window, { key: "F" });
    expect(second.dispatch).toHaveBeenCalledWith({ type: "remove-perk", perkId: "perk-bar" });
    expect(screen.queryByTestId("perk-cursor-preview")).not.toBeInTheDocument();
  });

  it("removes a held installed brick when it is dropped just outside the grid", () => {
    const { dispatch } = renderWorkbench({
      perks: [{ perkId: "perk-bar", row: 1, column: 0, rotation: "Default" }],
    });
    mockGridGeometry();
    fireEvent.click(screen.getByRole("button", { name: /^Bar Perk, 2×1, at A2/ }), {
      clientX: 700,
      clientY: 120,
    });

    fireEvent.click(window, { clientX: 422, clientY: 250 });

    expect(dispatch).toHaveBeenCalledWith({ type: "remove-perk", perkId: "perk-bar" });
    expect(screen.queryByTestId("perk-cursor-preview")).not.toBeInTheDocument();
  });
});

describe("PerkWorkbench grid presentation", () => {
  it("shows library perk details in the shared black tooltip on hover and focus", () => {
    renderWorkbench();

    const core = screen.getByRole("button", { name: "Pick up Core Perk for placement" });
    fireEvent.mouseEnter(core);

    let tooltip = screen.getByRole("tooltip");
    expect(tooltip).toHaveClass("grid-chip-tooltip");
    expect([...tooltip.children].map((child) => child.textContent)).toEqual([
      "Core Perk",
      "Anchors compatible modifiers.",
    ]);
    expect(core).toHaveAttribute("aria-describedby", tooltip.id);
    expect(core).not.toHaveAttribute("title");

    fireEvent.mouseLeave(core);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

    const unfulfilled = screen.getByRole("button", {
      name: "Pick up Second Linked Modifier for placement",
    });
    fireEvent.focus(unfulfilled);
    tooltip = screen.getByRole("tooltip");
    expect([...tooltip.children].map((child) => child.textContent)).toEqual([
      "Second Linked Modifier",
      "No description available.\nNeeds a compatible active target.",
    ]);
    expect(unfulfilled).toHaveAttribute("aria-describedby", tooltip.id);
    expect(unfulfilled).not.toHaveAttribute("title");

    fireEvent.scroll(document.querySelector(".perk-list")!);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    expect(unfulfilled).not.toHaveAttribute("aria-describedby");
  });

  it("counts the post-search and type-filter results, including visible unfulfilled perks", () => {
    renderWorkbench();

    const search = screen.getByRole("searchbox", { name: /Search \d+ perks/ });
    expect(search).toHaveAttribute("placeholder", "Search 4 perks");

    fireEvent.click(screen.getByRole("button", { name: "modifier" }));
    expect(search).toHaveAttribute("placeholder", "Search 2 perks");
    expect(screen.getByRole("button", {
      name: "Pick up Second Linked Modifier for placement",
    })).toHaveAttribute("data-dependency-status", "unfulfilled");

    fireEvent.change(search, { target: { value: "Second" } });
    expect(search).toHaveAttribute("placeholder", "Search 1 perks");
    expect(screen.queryByRole("button", { name: "Pick up Linked Modifier for placement" }))
      .not.toBeInTheDocument();

    fireEvent.change(search, { target: { value: "no result" } });
    expect(search).toHaveAttribute("placeholder", "Search 0 perks");
  });

  it("excludes placed perks from the library and compatibility count", () => {
    renderWorkbench({
      perks: [{ perkId: "perk-core", row: 1, column: 1, rotation: "Default" }],
    });

    const library = screen.getByLabelText("Perk library");
    const search = screen.getByRole("searchbox", { name: /Search \d+ perks/ });
    expect(search).toHaveAttribute("placeholder", "Search 3 perks");
    expect(within(library).queryByRole("button", {
      name: "Pick up Core Perk for placement",
    })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "core" }));
    expect(search).toHaveAttribute("placeholder", "Search 1 perks");

    fireEvent.click(screen.getByRole("button", { name: "all" }));
    const placedCore = screen.getByRole("button", { name: /^Core Perk, 1×1, at B2/ });
    fireEvent.mouseEnter(placedCore);
    fireEvent.keyDown(window, { key: "r" });
    expect(search).toHaveAttribute("placeholder", "Search 2 perks");
  });

  it("removes a perk from the library count as soon as it is placed", () => {
    renderStatefulWorkbench();
    const board = mockGridGeometry();
    const search = screen.getByRole("searchbox", { name: /Search \d+ perks/ });
    const library = screen.getByLabelText("Perk library");
    expect(search).toHaveAttribute("placeholder", "Search 4 perks");

    fireEvent.click(screen.getByRole("button", { name: "Pick up Core Perk for placement" }), {
      clientX: 700,
      clientY: 120,
    });
    fireEvent.pointerMove(window, { clientX: 224, clientY: 198 });
    fireEvent.click(board, { clientX: 224, clientY: 198 });

    expect(search).toHaveAttribute("placeholder", "Search 3 perks");
    expect(within(library).queryByRole("button", {
      name: "Pick up Core Perk for placement",
    })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Core Perk, 1×1, at B2/ }))
      .toBeInTheDocument();
  });

  it("omits idle library chrome while keeping active placement guidance and controls", () => {
    renderWorkbench();
    mockGridGeometry();

    expect(document.querySelector(".perk-library__heading")).not.toBeInTheDocument();
    expect(screen.queryByText("Library", { exact: true })).not.toBeInTheDocument();
    expect(screen.queryByText(/available perks/i)).not.toBeInTheDocument();
    expect(document.querySelector(".placement-prompt")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Pick up Bar Perk for placement" }), {
      clientX: 700,
      clientY: 120,
    });

    expect(document.querySelector(".placement-prompt")).toHaveTextContent("Placing Bar Perk");
    expect(screen.getByRole("button", { name: "Cancel perk placement" })).toBeInTheDocument();
    expect(document.querySelector(".perk-library__actions--active")).toBeInTheDocument();
  });

  it("reports an unlinked brick in the fixed toolbar without adding a layout row", () => {
    renderWorkbench({
      perks: [{
        perkId: "perk-modifier",
        row: 4,
        column: 4,
        rotation: "Default",
      }],
    });

    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("1 unlinked");
    expect(status).toHaveAttribute("title", expect.stringContaining("Diagonal contact"));
    expect(document.querySelector(".link-notice")).not.toBeInTheDocument();
  });

  it("uses orange or gray library cards with semantic green, blue, and red wells", () => {
    renderWorkbench();

    const core = screen.getByRole("button", { name: "Pick up Core Perk for placement" });
    const modifier = screen.getByRole("button", {
      name: "Pick up Linked Modifier for placement",
    });
    const unfulfilled = screen.getByRole("button", {
      name: "Pick up Second Linked Modifier for placement",
    });

    expect(core).toHaveAttribute("data-card-tone", "orange");
    expect(core).toHaveAttribute("data-well-tone", "green");
    expect(core.style.getPropertyValue("--perk-library-well")).toBe("#c9fe90");
    expect(modifier).toHaveAttribute("data-card-tone", "orange");
    expect(modifier).toHaveAttribute("data-well-tone", "blue");
    expect(modifier.style.getPropertyValue("--perk-library-well")).toBe("#8acaf8");
    expect(unfulfilled).toHaveAttribute("data-card-tone", "gray");
    expect(unfulfilled).toHaveAttribute("data-well-tone", "red");
    expect(unfulfilled.style.getPropertyValue("--perk-library-well")).toBe("#ff5f57");

    expect(screen.queryByRole("button", { name: "Show more perks" })).not.toBeInTheDocument();
  });

  it("shows only the perk type beneath a library name and keeps status in the right box", () => {
    renderWorkbench();

    const core = screen.getByRole("button", { name: "Pick up Core Perk for placement" });
    expect(core.querySelector(".perk-list-item__copy small")).toHaveTextContent(/^core$/);
    expect(core.querySelector(".perk-list-item__copy")).not.toHaveTextContent("1×1");
    expect(core.querySelector(".perk-state")).toHaveTextContent(/^1×1$/);

    const unfulfilled = screen.getByRole("button", {
      name: "Pick up Second Linked Modifier for placement",
    });
    expect(unfulfilled.querySelector(".perk-list-item__copy small"))
      .toHaveTextContent(/^modifier$/);
    expect(unfulfilled.querySelector(".perk-list-item__copy")).not.toHaveTextContent("1×1");
    expect(unfulfilled.querySelector(".perk-state")).toHaveTextContent(/^TARGET$/);
  });

  it("keeps names off the bricks and presents name plus info in a hover tooltip", () => {
    renderWorkbench({
      perks: [{ perkId: "perk-core", row: 1, column: 1, rotation: "Default" }],
    });

    const board = screen.getByRole("group", { name: /perk grid/ });
    const core = screen.getByRole("button", { name: /^Core Perk, 1×1, at B2/ });
    expect(board).not.toHaveTextContent("Core Perk");
    expect(board).not.toHaveTextContent("Primary Ability");

    fireEvent.mouseEnter(core);
    const tooltip = screen.getByRole("tooltip");
    expect(tooltip).toHaveTextContent("Core Perk");
    expect(tooltip).toHaveTextContent("Anchors compatible modifiers.");

    fireEvent.mouseLeave(core);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

    const ability = screen.getByRole("button", { name: /primary ability: Primary Ability/i });
    fireEvent.focus(ability);
    expect(screen.getByRole("tooltip")).toHaveTextContent("Launches the primary test payload.");
    fireEvent.blur(ability);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("highlights a compatibility root and every valid attached descendant", () => {
    renderWorkbench({
      perks: [
        { perkId: "perk-core", row: 1, column: 1, rotation: "Default" },
        {
          perkId: "perk-modifier",
          row: 1,
          column: 2,
          rotation: "Default",
          targetId: "perk-core",
        },
        {
          perkId: "perk-modifier-b",
          row: 1,
          column: 3,
          rotation: "Default",
          targetId: "perk-modifier",
        },
        { perkId: "perk-bar", row: 3, column: 0, rotation: "Default" },
      ],
    });

    const core = screen.getByRole("button", { name: /^Core Perk, 1×1, at B2/ });
    fireEvent.mouseEnter(core);
    fireEvent.keyDown(window, { key: "r" });

    expect(core).toHaveClass("is-compatibility-context");
    expect(screen.getByRole("button", { name: /^Linked Modifier, 1×1, at C2/ }))
      .toHaveClass("is-compatibility-context");
    expect(screen.getByRole("button", { name: /^Second Linked Modifier, 1×1, at D2/ }))
      .toHaveClass("is-compatibility-context");
    expect(screen.getByRole("button", { name: /^Bar Perk, 2×1, at A4/ }))
      .not.toHaveClass("is-compatibility-context");
    expect(document.querySelector(".modifier-context")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show all perks" })).toBeInTheDocument();
  });

  it.each(["all", "core", "modifier"] as const)(
    "toggles compatibility off and restores the prior %s category",
    (startingFilter) => {
      renderWorkbench({
        perks: [{ perkId: "perk-core", row: 1, column: 1, rotation: "Default" }],
      });
      fireEvent.click(screen.getByRole("button", { name: startingFilter }));
      const core = screen.getByRole("button", { name: /^Core Perk, 1×1, at B2/ });
      fireEvent.mouseEnter(core);

      fireEvent.keyDown(window, { key: "r" });
      expect(screen.getByRole("button", { name: "modifier" })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
      expect(screen.getByRole("button", { name: "Show all perks" })).toBeInTheDocument();

      fireEvent.keyDown(window, { key: "R" });
      expect(screen.queryByRole("button", { name: "Show all perks" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: startingFilter })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
      expect(core).not.toHaveClass("is-compatibility-context");
    },
  );

  it("highlights the union of cells used by every legal position and orientation", () => {
    renderWorkbench({
      perks: [{ perkId: "perk-core", row: 1, column: 1, rotation: "Default" }],
    });
    mockGridGeometry();

    fireEvent.click(screen.getByRole("button", { name: "Pick up Bar Perk for placement" }), {
      clientX: 700,
      clientY: 120,
    });

    const highlighted = document.querySelectorAll(".perk-cell.is-legal-footprint");
    expect(highlighted).toHaveLength(22);
    expect(document.querySelector(".perk-cell[data-row='0'][data-column='0']"))
      .not.toHaveClass("is-legal-footprint");
    expect(document.querySelector(".perk-cell[data-row='2'][data-column='2']"))
      .not.toHaveClass("is-legal-footprint");
    expect(document.querySelector(".perk-cell[data-row='1'][data-column='1']"))
      .not.toHaveClass("is-legal-footprint");
    // A2 can only participate vertically because B2 is occupied. Its presence
    // proves that allowed rotations are unioned rather than only the current one.
    expect(document.querySelector(".perk-cell[data-row='1'][data-column='0']"))
      .toHaveClass("is-legal-footprint");
  });

  it("marks a snapped disconnected modifier red but still permits the drop", () => {
    const { dispatch } = renderWorkbench({
      perks: [{ perkId: "perk-core", row: 1, column: 1, rotation: "Default" }],
    });
    const board = mockGridGeometry();
    fireEvent.click(screen.getByRole("button", { name: "Pick up Linked Modifier for placement" }), {
      clientX: 700,
      clientY: 120,
    });

    fireEvent.pointerMove(window, { clientX: 255, clientY: 197 });
    expect(screen.getByTestId("perk-cursor-preview")).toHaveAttribute(
      "data-snap-state",
      "valid",
    );

    fireEvent.pointerMove(window, { clientX: 371, clientY: 371 });
    const preview = screen.getByTestId("perk-cursor-preview");
    expect(preview).toHaveAttribute("data-snap-row", "4");
    expect(preview).toHaveAttribute("data-snap-column", "4");
    expect(preview).toHaveAttribute("data-snap-state", "unlinked");

    fireEvent.click(board, { clientX: 371, clientY: 371 });
    expect(dispatch).toHaveBeenCalledWith({
      type: "place-perk",
      placement: {
        perkId: "perk-modifier",
        row: 4,
        column: 4,
        rotation: "Default",
      },
    });
  });

  it("draws one white connector at each boundary in a valid family", () => {
    renderWorkbench({
      perks: [
        { perkId: "perk-core", row: 1, column: 1, rotation: "Default" },
        {
          perkId: "perk-modifier",
          row: 1,
          column: 2,
          rotation: "Default",
          targetId: "perk-core",
        },
        {
          perkId: "perk-modifier-b",
          row: 1,
          column: 3,
          rotation: "Default",
          targetId: "perk-modifier",
        },
        { perkId: "perk-bar", row: 3, column: 0, rotation: "Default" },
      ],
    });

    const connectors = document.querySelectorAll(".family-connector");
    expect(connectors).toHaveLength(2);
    expect(document.querySelectorAll(".family-connector--horizontal")).toHaveLength(2);
    expect([...connectors].map((connector) => connector.getAttribute("data-family-id")))
      .toEqual(["perk-core", "perk-core"]);
  });

  it("does not draw a family connector for an unresolved modifier", () => {
    renderWorkbench({
      perks: [
        { perkId: "perk-core", row: 1, column: 1, rotation: "Default" },
        { perkId: "perk-modifier", row: 1, column: 2, rotation: "Default" },
      ],
    });

    expect(document.querySelectorAll(".family-connector")).toHaveLength(0);
  });

  it("marks an unlinked modifier as the red-priority state", () => {
    renderWorkbench({
      perks: [{ perkId: "perk-modifier", row: 4, column: 4, rotation: "Default" }],
    });

    const modifier = screen.getByRole("button", {
      name: /^Linked Modifier, 1×1, at E5, connection required/,
    });
    expect(modifier).toHaveClass("has-issue");
    expect(modifier).not.toHaveClass("is-compatibility-context");
    expect(modifier).toHaveAttribute("data-link-status", "unlinked");
  });

  it("uses the extracted restriction class to choose normal chip color", () => {
    renderWorkbench({
      perks: [
        { perkId: "perk-core", row: 1, column: 1, rotation: "Default" },
        {
          perkId: "perk-modifier",
          row: 1,
          column: 2,
          rotation: "Default",
          targetId: "perk-core",
        },
      ],
    });

    const core = screen.getByRole("button", { name: /^Core Perk, 1×1, at B2/ });
    const modifier = screen.getByRole("button", { name: /^Linked Modifier, 1×1, at C2/ });
    expect(core.style.getPropertyValue("--chip-color")).toBe("#c9fe90");
    expect(modifier.style.getPropertyValue("--chip-color")).toBe("#8acaf8");
  });
});
