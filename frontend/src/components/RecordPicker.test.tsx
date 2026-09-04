import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AugmentRecord, WeaponRecord } from "../model/catalogue";
import { RecordPicker } from "./RecordPicker";

afterEach(() => {
  cleanup();
  document.body.style.overflow = "";
});

function weapon(overrides: Partial<WeaponRecord> & Pick<WeaponRecord, "id" | "displayName">): WeaponRecord {
  return {
    kind: "weapon",
    componentSlots: [],
    compatibility: {},
    ...overrides,
  };
}

function augment(
  overrides: Partial<AugmentRecord> & Pick<AugmentRecord, "id" | "displayName">,
): AugmentRecord {
  return {
    kind: "augment",
    ...overrides,
  };
}

describe("RecordPicker attachment descriptions", () => {
  it("retains rows and conditional indentation for expanded attachment copy", () => {
    render(
      <RecordPicker
        config={{
          title: "Choose an augment",
          records: [
            augment({
              id: "augment-formatted",
              displayName: "Formatted Augment",
              description: (
                "Summary.\r\n\r\n"
                + "+20.0% Reload Speed\r\n\r\n"
                + "<Bold>On Hit</>:\r\n"
                + "  +10% Damage"
              ),
            }),
          ],
          onSelect: vi.fn(),
        }}
        onClose={vi.fn()}
      />,
    );

    const option = screen.getByRole("button", { name: /Formatted Augment/i });
    expect(option).toHaveAttribute("data-record-kind", "augment");
    expect(option.querySelector(".picker-option__copy small")?.textContent).toBe(
      "Summary.\n\n+20.0% Reload Speed\n\nOn Hit:\n  +10% Damage",
    );
  });
});

describe("RecordPicker weapon artwork", () => {
  it("uses textured GunIcon art when it is available", () => {
    render(
      <RecordPicker
        config={{
          title: "Choose a weapon",
          eyebrow: "Primary",
          records: [
            weapon({
              id: "weapon-textured",
              displayName: "Textured Rifle",
              icon: { path: "icons/textured-rifle.png" },
              silhouetteIcon: { path: "icons/silhouette-rifle.png" },
            }),
          ],
          onSelect: vi.fn(),
        }}
        onClose={vi.fn()}
      />,
    );

    const option = screen.getByRole("button", { name: /Textured Rifle/i });
    expect(option.querySelector("img")).toHaveAttribute(
      "src",
      "/catalogue/icons/textured-rifle.png",
    );
  });

  it("keeps the silhouette when a weapon icon is marked as fallback artwork", () => {
    render(
      <RecordPicker
        config={{
          title: "Choose a weapon",
          eyebrow: "Primary",
          records: [
            weapon({
              id: "weapon-fallback",
              displayName: "Fallback Rifle",
              icon: {
                path: "icons/trait-placeholder.png",
                fallback: { type: "trait-icon" },
              },
              silhouetteIcon: { path: "icons/silhouette-rifle.png" },
            }),
          ],
          onSelect: vi.fn(),
        }}
        onClose={vi.fn()}
      />,
    );

    const option = screen.getByRole("button", { name: /Fallback Rifle/i });
    expect(option.querySelector("img")).toHaveAttribute(
      "src",
      "/catalogue/icons/silhouette-rifle.png",
    );
  });
});

describe("RecordPicker centered dialog", () => {
  it("omits the eyebrow line when a picker does not provide one", () => {
    render(
      <RecordPicker
        config={{
          title: "Choose Primary weapon",
          records: [weapon({ id: "weapon-alpha", displayName: "Alpha Rifle" })],
          onSelect: vi.fn(),
        }}
        onClose={vi.fn()}
      />,
    );

    const dialog = screen.getByRole("dialog", { name: "Choose Primary weapon" });
    expect(dialog.querySelector(".eyebrow")).not.toBeInTheDocument();
  });

  it("exposes a centered modal contract with an internally scrollable options region", () => {
    render(
      <RecordPicker
        config={{
          title: "Choose a weapon",
          eyebrow: "Primary",
          records: [weapon({ id: "weapon-alpha", displayName: "Alpha Rifle" })],
          onSelect: vi.fn(),
        }}
        onClose={vi.fn()}
      />,
    );

    const dialog = screen.getByRole("dialog", { name: "Choose a weapon" });
    const overlay = dialog.parentElement;
    expect(screen.getByText("Primary", { selector: ".eyebrow" })).toBeInTheDocument();
    expect(dialog).toHaveClass("picker-dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(overlay).toHaveClass("picker-overlay");
    expect(overlay).toHaveAttribute("data-placement", "center");
    expect(dialog.querySelector(":scope > .picker-dialog__body")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Choose a weapon options" }))
      .toHaveClass("picker-options");
    expect(screen.getByRole("searchbox", { name: "Search Choose a weapon" })).toHaveFocus();
    expect(document.body.style.overflow).toBe("hidden");
    expect(document.querySelector(".picker-sheet")).not.toBeInTheDocument();
    expect(document.querySelector(".picker-backdrop")).not.toBeInTheDocument();
  });

  it("closes from the backdrop, close button, or Escape without treating dialog clicks as backdrop clicks", () => {
    const onClose = vi.fn();
    render(
      <RecordPicker
        config={{
          title: "Choose a weapon",
          eyebrow: "Primary",
          records: [weapon({ id: "weapon-alpha", displayName: "Alpha Rifle" })],
          onSelect: vi.fn(),
        }}
        onClose={onClose}
      />,
    );

    const dialog = screen.getByRole("dialog", { name: "Choose a weapon" });
    const overlay = dialog.parentElement!;
    fireEvent.mouseDown(dialog);
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.mouseDown(overlay);
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Close picker" }));
    expect(onClose).toHaveBeenCalledTimes(2);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(3);
  });

  it("traps keyboard focus and restores the previously focused control when it unmounts", () => {
    const opener = document.createElement("button");
    opener.textContent = "Open picker";
    document.body.append(opener);
    opener.focus();

    const view = render(
      <RecordPicker
        config={{
          title: "Choose a weapon",
          eyebrow: "Primary",
          records: [weapon({ id: "weapon-alpha", displayName: "Alpha Rifle" })],
          onSelect: vi.fn(),
        }}
        onClose={vi.fn()}
      />,
    );

    const close = screen.getByRole("button", { name: "Close picker" });
    const option = screen.getByRole("button", { name: /Alpha Rifle/i });
    close.focus();
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(option).toHaveFocus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(close).toHaveFocus();

    view.unmount();
    expect(opener).toHaveFocus();
    expect(document.body.style.overflow).toBe("");
    opener.remove();
  });

  it("preserves selected and empty choices and publishes additional records into the scroll region", () => {
    const onSelect = vi.fn();
    const records = Array.from({ length: 61 }, (_, index) => weapon({
      id: `weapon-${index}`,
      displayName: `Weapon ${String(index).padStart(2, "0")}`,
    }));
    render(
      <RecordPicker
        config={{
          title: "Choose a weapon",
          eyebrow: "Primary",
          records,
          selectedId: null,
          allowEmpty: true,
          emptyLabel: "No primary weapon",
          onSelect,
        }}
        onClose={vi.fn()}
      />,
    );

    const empty = screen.getByRole("button", { name: /No primary weapon/i });
    const first = screen.getByRole("button", { name: /Weapon 00/i });
    expect(empty).toHaveAttribute("aria-pressed", "true");
    expect(first).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(first);
    expect(onSelect).toHaveBeenCalledWith("weapon-0");
    fireEvent.click(empty);
    expect(onSelect).toHaveBeenCalledWith(null);

    const options = screen.getByRole("region", { name: "Choose a weapon options" });
    expect(options.querySelectorAll(".picker-option")).toHaveLength(61);
    fireEvent.click(screen.getByRole("button", { name: "Show 1 more" }));
    expect(options.querySelectorAll(".picker-option")).toHaveLength(62);
    expect(screen.getByRole("button", { name: /Weapon 60/i })).toBeInTheDocument();
  });
});

describe("RecordPicker search result count", () => {
  it("puts the filtered record count in the placeholder without counting None", () => {
    render(
      <RecordPicker
        config={{
          title: "Choose a weapon",
          records: [
            weapon({ id: "weapon-alpha", displayName: "Alpha Rifle" }),
            weapon({ id: "weapon-beta", displayName: "Beta Shotgun" }),
            weapon({ id: "weapon-gamma", displayName: "Gamma Pistol" }),
          ],
          allowEmpty: true,
          emptyLabel: "None",
          onSelect: vi.fn(),
        }}
        onClose={vi.fn()}
      />,
    );

    const dialog = screen.getByRole("dialog", { name: "Choose a weapon" });
    const search = screen.getByRole("searchbox", { name: "Search Choose a weapon" });
    const options = screen.getByRole("region", { name: "Choose a weapon options" });
    expect(search).toHaveAttribute("placeholder", "Search 3 options");
    expect(options.querySelectorAll(".picker-option")).toHaveLength(4);
    expect(dialog).not.toHaveAttribute("aria-describedby");
    expect(dialog.querySelector(".picker-count")).not.toBeInTheDocument();

    fireEvent.change(search, { target: { value: "rifle" } });
    expect(search).toHaveAttribute("placeholder", "Search 1 options");
    expect(options.querySelectorAll(".picker-option")).toHaveLength(2);
    expect(screen.getByRole("button", { name: /None/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Alpha Rifle/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Beta Shotgun/i })).not.toBeInTheDocument();

    fireEvent.change(search, { target: { value: "no result" } });
    expect(search).toHaveAttribute("placeholder", "Search 0 options");
    expect(options.querySelectorAll(".picker-option")).toHaveLength(1);
    expect(screen.getByText("No matching gear")).toBeInTheDocument();
  });
});
