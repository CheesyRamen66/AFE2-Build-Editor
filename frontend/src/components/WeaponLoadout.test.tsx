import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { attachmentSlotKey, createBuildForKit } from "../model/build";
import {
  createCatalogueIndex,
  type KitRecord,
  type PlannerCatalogue,
  type WeaponRecord,
} from "../model/catalogue";
import { createSyntheticPlannerCatalogue } from "../test/fixtures/plannerCatalogue";
import { WeaponLoadout } from "./WeaponLoadout";

afterEach(cleanup);

function threeSlotFixture() {
  const catalogue: PlannerCatalogue = createSyntheticPlannerCatalogue();
  const kit = catalogue.records.find((record): record is KitRecord => (
    record.kind === "kit" && record.id === "kit-alpha"
  ));
  const weapon = catalogue.records.find((record): record is WeaponRecord => (
    record.kind === "weapon" && record.id === "weapon-alpha"
  ));
  const trait = catalogue.records.find((record) => record.id === "trait-alpha");
  if (!kit || !weapon || !trait) throw new Error("Synthetic weapon fixture is incomplete");

  weapon.description = "A reliable rifle for synthetic missions.";
  trait.description = (
    "Improves handling while firing.\r\n\r\n"
    + "+20.0% Handling\r\n\r\n"
    + "<Bold>On Hit</>:\r\n"
    + "  +10% Accuracy"
  );
  const sourceSlot = kit.weaponSlots[0];
  kit.weaponSlots = [
    { ...sourceSlot, index: 0, slotType: "primary" },
    { ...sourceSlot, index: 1, slotType: "signature" },
    { ...sourceSlot, index: 2, slotType: "sidearm" },
  ];

  const index = createCatalogueIndex(catalogue);
  const build = createBuildForKit(index, kit.id);
  const traitSlot = weapon.compatibility.traitSlot;
  if (!traitSlot) throw new Error("Synthetic weapon fixture has no trait slot");
  const traitKey = attachmentSlotKey(traitSlot);
  for (const weaponBuild of build.weapons) weaponBuild.attachments[traitKey] = trait.id;

  return {
    build,
    index,
    kit,
    weapon,
  };
}

function renderLoadout() {
  const fixture = threeSlotFixture();
  const onChooseWeapon = vi.fn();
  const onChooseAttachment = vi.fn();
  render(
    <WeaponLoadout
      index={fixture.index}
      kit={fixture.kit}
      build={fixture.build}
      onChooseWeapon={onChooseWeapon}
      onChooseAttachment={onChooseAttachment}
    />,
  );
  return { ...fixture, onChooseAttachment, onChooseWeapon };
}

describe("WeaponLoadout", () => {
  it("renders primary, signature, and sidearm as parallel card siblings without option chrome", () => {
    renderLoadout();

    expect(screen.getByRole("region", { name: "Weapons" })).toBeInTheDocument();
    expect(screen.queryByText("Assemble your loadout", { exact: true })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Weapons" })).not.toBeInTheDocument();
    expect(screen.queryByText("Every choice is filtered to the selected kit, weapon, and socket."))
      .not.toBeInTheDocument();

    const list = document.querySelector(".weapon-list");
    const cards = [...document.querySelectorAll<HTMLElement>(".weapon-card")];
    expect(list).not.toBeNull();
    expect(cards).toHaveLength(3);
    expect(cards.every((card) => card.parentElement === list)).toBe(true);
    expect(cards.map((card) => card.dataset.weaponSlot)).toEqual([
      "primary",
      "signature",
      "sidearm",
    ]);
    expect(cards.map((card) => within(card).getByText(/Primary|Signature|Sidearm/).textContent))
      .toEqual(["Primary", "Signature", "Sidearm"]);

    for (const card of cards) {
      const weaponChoice = within(card).getByRole("button", { name: /Choose weapon for/i });
      expect(weaponChoice).toHaveClass("weapon-card__hero");
      expect(weaponChoice.tagName).toBe("BUTTON");
      expect(weaponChoice.querySelector(".weapon-card__name")).toHaveTextContent("Alpha Rifle");
      expect(weaponChoice.querySelector(":scope > .record-visual")).toBeVisible();
      expect(within(card).getAllByRole("button", { name: /Choose attachment/i }))
        .toHaveLength(2);
    }

    expect(document.querySelector(".slot-number")).not.toBeInTheDocument();
    expect(document.querySelector(".attachment-slot__action")).not.toBeInTheDocument();
  });

  it("keeps each full weapon and attachment area interactive with the existing callbacks", () => {
    const { kit, onChooseAttachment, onChooseWeapon, weapon } = renderLoadout();
    const cards = [...document.querySelectorAll<HTMLElement>(".weapon-card")];
    const signatureCard = cards[1];

    fireEvent.click(within(signatureCard).getByText("Alpha Rifle"));
    expect(onChooseWeapon).toHaveBeenCalledWith(kit.weaponSlots[1]);

    const emptyMagazine = within(signatureCard).getByRole("button", {
      name: "Magazine: empty. Choose attachment.",
    });
    fireEvent.click(within(emptyMagazine).getByText("Choose"));
    expect(onChooseAttachment).toHaveBeenCalledWith(
      1,
      weapon,
      weapon.componentSlots[0],
      null,
    );

    const filledTrait = within(signatureCard).getByRole("button", {
      name: "Trait: Alpha Trait. Choose attachment.",
    });
    fireEvent.click(filledTrait.querySelector(".attachment-slot__icon")!);
    expect(onChooseAttachment).toHaveBeenCalledWith(
      1,
      weapon,
      weapon.compatibility.traitSlot,
      "trait-alpha",
    );
  });

  it("moves descriptions into name-first tooltips on weapon hover and attachment focus", () => {
    renderLoadout();
    const primaryCard = document.querySelector<HTMLElement>(".weapon-card")!;
    const weaponChoice = within(primaryCard).getByRole("button", {
      name: /Choose weapon for Primary slot/i,
    });

    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    expect(screen.queryByText("A reliable rifle for synthetic missions."))
      .not.toBeInTheDocument();

    fireEvent.mouseEnter(weaponChoice);
    let tooltip = screen.getByRole("tooltip");
    expect([...tooltip.children].map((child) => child.textContent)).toEqual([
      "Alpha Rifle",
      "A reliable rifle for synthetic missions.",
    ]);
    expect(weaponChoice).toHaveAttribute("aria-describedby", tooltip.id);

    fireEvent.mouseLeave(weaponChoice);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

    const traitChoice = within(primaryCard).getByRole("button", {
      name: "Trait: Alpha Trait. Choose attachment.",
    });
    fireEvent.focus(traitChoice);
    tooltip = screen.getByRole("tooltip");
    expect([...tooltip.children].map((child) => child.textContent)).toEqual([
      "Alpha Trait",
      "Improves handling while firing.\n\n"
        + "+20.0% Handling\n\n"
        + "On Hit:\n"
        + "  +10% Accuracy",
    ]);
    expect(traitChoice).toHaveAttribute("aria-describedby", tooltip.id);

    fireEvent.blur(traitChoice);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

    const emptyMagazine = within(primaryCard).getByRole("button", {
      name: "Magazine: empty. Choose attachment.",
    });
    fireEvent.mouseEnter(emptyMagazine);
    tooltip = screen.getByRole("tooltip");
    expect([...tooltip.children].map((child) => child.textContent)).toEqual([
      "Magazine",
      "No attachment selected.",
    ]);
  });

  it("does not reopen weapon or attachment tooltips when picker cleanup restores focus", () => {
    renderLoadout();
    const primaryCard = document.querySelector<HTMLElement>(".weapon-card")!;
    const choices = [
      within(primaryCard).getByRole("button", {
        name: /Choose weapon for Primary slot/i,
      }),
      within(primaryCard).getByRole("button", {
        name: "Trait: Alpha Trait. Choose attachment.",
      }),
    ];

    for (const choice of choices) {
      const pickerOverlay = document.createElement("div");
      pickerOverlay.className = "picker-overlay";

      fireEvent.mouseEnter(choice);
      fireEvent.focus(choice);
      expect(screen.getByRole("tooltip")).toBeInTheDocument();

      // Opening the picker dismisses the tooltip. While it is open, focus
      // leaves this control and the pointer can move elsewhere.
      fireEvent.click(choice);
      fireEvent.mouseLeave(choice);
      document.body.append(pickerOverlay);

      // StrictMode probes RecordPicker's effect with an extra cleanup/setup,
      // producing an intermediate restoration before the real one on close.
      fireEvent.blur(choice);
      fireEvent.focus(choice);
      fireEvent.blur(choice);
      pickerOverlay.remove();
      fireEvent.focus(choice);

      expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
      expect(choice).not.toHaveAttribute("aria-describedby");

      // A later deliberate focus move releases the restoration suppression,
      // keeping the tooltip available to keyboard users.
      fireEvent.blur(choice);
      fireEvent.focus(choice);
      expect(screen.getByRole("tooltip")).toBeInTheDocument();
      fireEvent.blur(choice);
    }
  });
});
