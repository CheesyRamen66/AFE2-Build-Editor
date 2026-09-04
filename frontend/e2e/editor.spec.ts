import { expect, test } from "@playwright/test";

test("builds a local kit, perk, weapon, and item loadout", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  await page.goto("/");
  await page.evaluate(() => localStorage.clear());
  await page.reload();

  await expect(page.getByText("Choose a kit. Shape the perk grid.", { exact: false })).toHaveCount(0);
  await expect(page.locator(".hero")).toHaveCount(0);
  const siteSections = page.getByRole("navigation", { name: "Site sections" });
  await expect(siteSections.getByRole("link", { name: /Editor/ })).toHaveAttribute("aria-current", "page");
  await expect(siteSections.getByRole("button", { name: /Builds/ })).toBeDisabled();
  await expect(siteSections.getByRole("button", { name: /Database/ })).toBeDisabled();
  await expect(siteSections.locator(":scope > * > span")).toHaveCount(0);
  for (const formerSection of ["Kit", "Perks", "Weapons", "Items"]) {
    await expect(siteSections.getByText(formerSection, { exact: true })).toHaveCount(0);
  }
  await expect(page.getByText("Local draft", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Saved in this browser", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Local data boundary", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Hosting-ready IDs", { exact: true })).toHaveCount(0);
  await expect(page.locator(".brand__mark")).toHaveText("AFE2");
  await expect(page.locator("footer")).toContainText(/STEAM BUILD \d+/);
  await expect(page.getByRole("group", { name: /perk grid/ })).toBeVisible();
  await expect(page.getByText("Choose your role", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Kit", exact: true })).toHaveCount(0);
  await expect(page.locator(".kit-card__number")).toHaveCount(0);
  await expect(page.getByText("Library", { exact: true })).toHaveCount(0);
  await expect(page.getByText(/available perks/i)).toHaveCount(0);
  await expect(page.getByText("Pick up a perk from the library to begin.", { exact: true }))
    .toHaveCount(0);
  const firstLibraryPerk = page.locator(".perk-list-item").first();
  await expect(firstLibraryPerk.locator(".perk-list-item__copy small")).not.toContainText("×");
  await expect(firstLibraryPerk.locator(".perk-state")).toContainText("×");
  await expect(page.locator(".kit-card__copy strong")).toHaveText([
    "Duelist",
    "Machinist",
    "Marauder",
    "Hunter",
    "Medic",
    "Specialist",
  ]);
  await expect(page.locator(".kit-card.is-selected .kit-card__copy strong")).toHaveCSS(
    "color",
    "rgb(217, 123, 38)",
  );
  await expect(page.locator(".site-header")).toHaveCSS(
    "border-top-color",
    "rgba(184, 91, 24, 0.52)",
  );

  const kitRailBox = await page.locator(".kit-section").boundingBox();
  const boardBox = await page.locator(".board-panel").boundingBox();
  const perkRailBox = await page.locator(".perk-library").boundingBox();
  const boardScrollBox = await page.locator(".board-scroll").boundingBox();
  const perkBoardBox = await page.locator(".perk-board").boundingBox();
  const workbenchBox = await page.locator(".perk-workbench").boundingBox();
  if (!kitRailBox || !boardBox || !perkRailBox || !boardScrollBox || !perkBoardBox || !workbenchBox) {
    throw new Error("Editor rails are not visible");
  }
  expect(kitRailBox.x + kitRailBox.width).toBeLessThanOrEqual(boardBox.x + 1);
  expect(boardBox.x + boardBox.width).toBeLessThanOrEqual(perkRailBox.x + 1);
  expect(perkBoardBox.x).toBeGreaterThanOrEqual(boardScrollBox.x);
  expect(perkBoardBox.x + perkBoardBox.width)
    .toBeLessThanOrEqual(boardScrollBox.x + boardScrollBox.width + 1);
  expect(boardBox.y).toBeLessThan(140);
  expect(workbenchBox.height).toBeLessThanOrEqual(640);
  await page.getByRole("radio", { name: /Duelist/ }).click();
  await expect(page.getByRole("radio", { name: /Duelist/ })).toHaveAttribute("aria-checked", "true");
  await expect(page.locator(".weapon-card__slot strong")).toHaveText([
    "Primary",
    "Primary",
    "Sidearm",
  ]);
  expect((await page.locator(".weapon-card__slot").allTextContents()).join(" ")).not.toMatch(/rifle|cqw|handgun/i);
  await expect(page.getByRole("button", { name: /Change weapon/ })).toHaveCount(0);
  await expect(page.getByText("Equipped", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Assemble your loadout", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Weapons", exact: true })).toHaveCount(0);
  await expect(page.getByText("Every choice is filtered to the selected kit, weapon, and socket."))
    .toHaveCount(0);
  await expect(page.getByText("Mission support", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Items", exact: true })).toHaveCount(0);
  await expect(page.getByText("One Major and one Minor item, as defined by the game’s inventory slots."))
    .toHaveCount(0);
  await expect(page.locator(".slot-number, .attachment-slot__action")).toHaveCount(0);

  const weaponCards = page.locator(".weapon-card");
  await expect(weaponCards).toHaveCount(3);
  const weaponCardBoxes = await weaponCards.evaluateAll((cards) => cards.map((card) => {
    const box = card.getBoundingClientRect();
    return { x: box.x, y: box.y, width: box.width };
  }));
  expect(new Set(weaponCardBoxes.map(({ y }) => Math.round(y))).size).toBe(1);
  expect(weaponCardBoxes[0].x + weaponCardBoxes[0].width).toBeLessThan(weaponCardBoxes[1].x);
  expect(weaponCardBoxes[1].x + weaponCardBoxes[1].width).toBeLessThan(weaponCardBoxes[2].x);

  const itemCards = page.locator(".item-card");
  await expect(itemCards).toHaveCount(2);
  const itemCardBoxes = await itemCards.evaluateAll((cards) => cards.map((card) => {
    const box = card.getBoundingClientRect();
    return { x: box.x, y: box.y, width: box.width };
  }));
  expect(weaponCardBoxes[2].x + weaponCardBoxes[2].width).toBeLessThan(itemCardBoxes[0].x);
  expect(itemCardBoxes[0].x).toBeCloseTo(itemCardBoxes[1].x, 0);
  expect(itemCardBoxes[0].y).toBeLessThan(itemCardBoxes[1].y);
  await expect(itemCards.nth(0)).toHaveAttribute("aria-label", /Minor item: empty/i);
  await expect(itemCards.nth(1)).toHaveAttribute("aria-label", /Major item: empty/i);
  await expect(itemCards.locator(".item-card__visual > .lucide-plus")).toHaveCount(2);

  const firstWeapon = page.locator(".weapon-card").first();
  const emptyTrait = firstWeapon.getByRole("button", { name: /Trait: empty/i });
  await expect(emptyTrait).toHaveAttribute("aria-label", /Trait: empty/i);

  const firstWeaponButton = firstWeapon.getByRole("button", { name: /Choose weapon for Primary slot/ });
  await expect(firstWeaponButton).toBeVisible();
  await firstWeaponButton.hover();
  await expect(page.getByRole("tooltip").locator("strong")).toHaveText("M41A2 Pulse Rifle");
  await expect(page.getByRole("tooltip").locator("span")).not.toHaveText("");
  await firstWeapon.locator(".weapon-card__name").click();
  const picker = page.getByRole("dialog");
  await expect(picker).toBeVisible();
  await expect(picker.locator(".picker-count")).toHaveCount(0);
  await expect(page.locator(".picker-overlay")).toHaveAttribute("data-placement", "center");
  const pickerBox = await picker.boundingBox();
  if (!pickerBox) throw new Error("Centered picker is not visible");
  expect(Math.abs((pickerBox.x + pickerBox.width / 2) - 640)).toBeLessThanOrEqual(2);
  expect(Math.abs((pickerBox.y + pickerBox.height / 2) - 360)).toBeLessThanOrEqual(2);
  const weaponChoice = page.locator(".picker-option").filter({ hasText: "F44AA Pulse Rifle" });
  await expect(weaponChoice).toBeVisible();
  await expect(weaponChoice.locator("img")).toHaveAttribute(
    "src",
    /icon-venus-rifle-auto-f44aa--f4f5cd0ac3cf52a7\.png$/,
  );
  await expect(weaponChoice.locator("img")).not.toHaveAttribute("src", /icon-sil-/);
  await weaponChoice.click();
  await expect(firstWeapon.locator(".weapon-card__name")).toHaveText(/F44AA Pulse Rifle/);

  const firstSocket = firstWeapon.locator(".attachment-slot").first();
  await firstSocket.hover();
  await expect(page.getByRole("tooltip").locator("strong")).not.toHaveText("");
  await expect(page.getByRole("tooltip").locator("span")).toHaveText("No attachment selected.");
  await firstSocket.click();
  const attachmentChoice = page.locator(".picker-option").filter({ hasText: "Assault Brake" });
  const attachmentCopy = attachmentChoice.locator(".picker-option__copy small");
  await expect(attachmentChoice).toHaveAttribute("data-record-kind", "mod");
  await expect(attachmentCopy).toHaveCSS("white-space", "pre-wrap");
  await expect(attachmentCopy).toHaveText(
    "+20.0% Stopping Power\n"
      + "+35.0% Recoil\n\n"
      + "While Stationary:\n"
      + "  +20% Stopping Power\n"
      + "  -35% Recoil",
  );
  await attachmentChoice.click();
  await expect(firstSocket).toHaveClass(/is-filled/);
  await firstSocket.hover();
  await expect(page.getByRole("tooltip").locator("span")).toHaveCSS("white-space", "pre-wrap");

  const secondPrimaryWeapon = weaponCards.nth(1).getByRole("button", {
    name: /Choose weapon for Primary slot/,
  });
  await secondPrimaryWeapon.hover();
  await secondPrimaryWeapon.click();
  await expect(page.getByRole("dialog", { name: "Choose Primary weapon" })).toBeVisible();
  await expect(page.locator(".picker-header .eyebrow")).toHaveCount(0);
  await page.locator(".picker-option:not(.is-selected)").first().click();
  await page.mouse.move(4, 4);
  await expect(page.getByRole("tooltip")).toHaveCount(0);

  const perkSearch = page.getByRole("searchbox", { name: /Search \d+ perks/ });
  await perkSearch.fill("Tough Hombre");
  const perkChoice = page.locator(".perk-list-item").filter({ hasText: "Tough Hombre" });
  await expect(perkSearch).toHaveAttribute("placeholder", "Search 1 perks");
  await perkChoice.hover();
  await expect(page.getByRole("tooltip").locator("strong")).toHaveText("Tough Hombre");
  await expect(page.getByRole("tooltip").locator("span")).not.toHaveText("");
  await perkChoice.click();
  await expect(page.locator(".placement-prompt")).toContainText("Placing Tough Hombre");
  await expect.poll(async () => (await page.locator(".perk-workbench").boundingBox())?.height)
    .toBeCloseTo(workbenchBox.height, 0);
  await expect.poll(async () => {
    const currentBoard = await page.locator(".board-panel").boundingBox();
    const currentWorkbench = await page.locator(".perk-workbench").boundingBox();
    return currentBoard && currentWorkbench ? currentBoard.y - currentWorkbench.y : undefined;
  }).toBeCloseTo(boardBox.y - workbenchBox.y, 0);
  await expect.poll(async () => {
    const currentPerkBoard = await page.locator(".perk-board").boundingBox();
    const currentBoard = await page.locator(".board-panel").boundingBox();
    return currentPerkBoard && currentBoard ? currentPerkBoard.y - currentBoard.y : undefined;
  }).toBeCloseTo(perkBoardBox.y - boardBox.y, 0);
  const cursorPreview = page.getByTestId("perk-cursor-preview");
  await expect(cursorPreview).toBeVisible();
  await expect(cursorPreview).toHaveAttribute("data-placement-mode", "new");
  const initialPreviewTransform = await cursorPreview.evaluate((element) =>
    (element as HTMLElement).style.transform
  );
  await page.mouse.move(360, 180);
  await expect.poll(() => cursorPreview.evaluate((element) =>
    (element as HTMLElement).style.transform
  )).not.toBe(initialPreviewTransform);
  await page.keyboard.press("d");
  const placementTarget = page.locator(".perk-cell[data-row='1'][data-column='1']");
  await placementTarget.scrollIntoViewIfNeeded();
  await placementTarget.click();
  await expect(perkChoice).toHaveCount(0);
  await expect(cursorPreview).toHaveCount(0);
  await expect(page.locator(".placement-prompt")).toHaveCount(0);
  // The library pickup is centered, so dropping its lower segment on B2 keeps
  // that segment under the pointer and makes B1 the brick origin.
  const placedPerk = page.getByRole("button", { name: /Tough Hombre, 1×2, at B1/ });
  await expect(placedPerk).toBeVisible();
  // The new brick mounts under a stationary pointer. Shortcuts must work
  // immediately, without a synthetic hover or a mouse-out/mouse-in cycle.
  await page.keyboard.press("d");
  const rotatedPerk = page.getByRole("button", { name: /Tough Hombre, 2×1, at B1/ });
  await expect(rotatedPerk).toBeVisible();
  await rotatedPerk.hover();
  await expect(rotatedPerk).toHaveText("");
  const tooltip = page.getByRole("tooltip");
  await expect(tooltip.locator("strong")).toHaveText("Tough Hombre");
  await expect(tooltip.locator("span")).not.toHaveText("");
  await rotatedPerk.click();
  await expect(page.getByTestId("perk-cursor-preview")).toHaveAttribute("data-placement-mode", "move");
  await expect(page.locator(".placed-perk.is-moving")).toHaveCount(1);
  await expect(page.locator(".placed-perk.is-selected")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Move", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Remove", exact: true })).toHaveCount(0);
  await page.locator(".perk-cell[data-row='1'][data-column='2']").click();
  await expect(page.getByTestId("perk-cursor-preview")).toHaveCount(0);
  // Clicking the brick center grabs its right segment; landing that segment on
  // C2 therefore places the brick origin at B2.
  await expect(page.getByRole("button", { name: /Tough Hombre, 2×1, at B2/ })).toBeVisible();

  const movingPerk = page.getByRole("button", { name: /Tough Hombre, 2×1, at B2/ });
  const movingBox = await movingPerk.boundingBox();
  if (!movingBox) throw new Error("Placed perk is not visible for dragging");
  await page.mouse.move(movingBox.x + movingBox.width / 2, movingBox.y + movingBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(movingBox.x + movingBox.width / 2 + 12, movingBox.y + movingBox.height / 2, {
    steps: 3,
  });
  const moveTarget = page.locator(".perk-cell[data-row='1'][data-column='3']");
  await expect(moveTarget).toBeVisible();
  const moveTargetBox = await moveTarget.boundingBox();
  if (!moveTargetBox) throw new Error("Perk move target is not visible");
  await page.mouse.move(
    moveTargetBox.x + moveTargetBox.width / 2,
    moveTargetBox.y + moveTargetBox.height / 2,
    { steps: 16 },
  );
  await page.mouse.up();
  await expect(page.getByRole("button", { name: /Tough Hombre, 2×1, at C2/ })).toBeVisible();

  await page.getByRole("button", { name: /Major Item: empty/ }).click();
  const itemPicker = page.getByRole("dialog", { name: /Choose Major Item/i });
  await expect(itemPicker.locator(".picker-count")).toHaveCount(0);
  const itemOptionCount = await itemPicker.locator(
    ".picker-option:not(.picker-option--empty)",
  ).count();
  await expect(itemPicker.getByRole("searchbox")).toHaveAttribute(
    "placeholder",
    `Search ${itemOptionCount} options`,
  );
  await expect(itemPicker.locator(".picker-option--empty")).toHaveCount(1);
  await page.locator(".picker-option").filter({ hasText: "Ammo Supply Kit" }).click();
  await expect(page.getByRole("button", { name: /Major Item: Ammo Supply Kit/ })).toBeVisible();

  await page.reload();
  await expect(page.getByRole("radio", { name: /Duelist/ })).toHaveAttribute("aria-checked", "true");
  await expect(page.getByRole("button", { name: /Tough Hombre, 2×1, at C2/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /Major Item: Ammo Supply Kit/ })).toBeVisible();
  await expect(page.locator(".toast-region")).toHaveCount(0);
  expect(consoleErrors).toEqual([]);
});

test("hover shortcuts filter, rotate, remove, and reset against game catalogue IDs", async ({ page }) => {
  await page.goto("/");
  await page.evaluate(() => localStorage.clear());
  await page.reload();

  await page.getByRole("radio", { name: /Duelist/ }).click();
  const availableCount = await page.locator(".perk-list-item").count();
  expect(availableCount).toBeGreaterThan(72);
  await expect(page.locator(".perk-list-item")).toHaveCount(availableCount);
  const countedPerkSearch = page.getByRole("searchbox", { name: /Search \d+ perks/ });
  await expect(countedPerkSearch).toHaveAttribute("placeholder", `Search ${availableCount} perks`);
  await expect(page.getByRole("button", { name: "Show more perks" })).toHaveCount(0);
  for (const tone of ["green", "blue"]) {
    const item = page.locator(`.perk-list-item[data-well-tone="${tone}"]`).first();
    await expect(item).toBeVisible();
    await expect(item).toHaveAttribute("data-card-tone", "orange");
    await expect(item).toHaveCSS("color", "rgb(255, 255, 255)");
    await expect(item).toHaveCSS("border-top-color", "rgba(255, 255, 255, 0.38)");
    await expect(item.locator(".record-visual")).toHaveCSS("color", "rgb(255, 255, 255)");
    await expect(item.locator(".perk-state")).toHaveCSS("color", "rgb(255, 255, 255)");
  }
  const secondaryAbility = page.locator(".ability-anchor--secondary");
  await expect(secondaryAbility).toHaveAttribute("aria-label", /Shrapnel Grenade/);
  await expect(secondaryAbility.getByText("Shrapnel Grenade", { exact: true })).toHaveCount(0);
  await secondaryAbility.hover();
  await expect(page.getByRole("tooltip").locator("strong")).toHaveText("Shrapnel Grenade");
  await expect(page.getByRole("tooltip").locator("span")).not.toHaveText("");
  const workbenchHeight = (await page.locator(".perk-workbench").boundingBox())?.height;
  if (!workbenchHeight) throw new Error("Perk workbench is not visible");
  await page.keyboard.press("r");
  await expect(page.locator(".modifier-context")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Show all perks" })).toBeVisible();
  await expect(page.getByRole("button", { name: "modifier", exact: true }))
    .toHaveAttribute("aria-pressed", "true");
  expect(await page.locator(".perk-list-item").count()).toBeLessThan(availableCount);
  await expect(countedPerkSearch).toHaveAttribute(
    "placeholder",
    `Search ${await page.locator(".perk-list-item").count()} perks`,
  );
  await expect(secondaryAbility).toHaveClass(/is-compatibility-context/);
  await expect.poll(async () => (await page.locator(".perk-workbench").boundingBox())?.height)
    .toBeCloseTo(workbenchHeight, 0);

  const quickCharge = page.locator(".perk-list-item").filter({
    has: page.getByText("Quick Charge I", { exact: true }),
  });
  await expect(quickCharge).toBeVisible();
  await quickCharge.click();
  await page.locator(".perk-cell[data-row='1'][data-column='8']").click();

  const placedModifier = page.getByRole("button", { name: /Quick Charge I, 1×1, at I2/ });
  await expect(page.locator(".family-connector")).toHaveCount(1);
  await page.keyboard.press("r");
  await expect(page.locator(".modifier-context")).toHaveCount(0);
  await expect(secondaryAbility).not.toHaveClass(/is-compatibility-context/);
  await expect(placedModifier).not.toHaveClass(/is-compatibility-context/);
  await expect(page.getByRole("button", { name: "Show all perks" })).toHaveCount(0);

  await page.keyboard.press("r");
  await expect(secondaryAbility).toHaveClass(/is-compatibility-context/);
  await expect(placedModifier).toHaveClass(/is-compatibility-context/);
  await expect(page.locator(".is-compatibility-context")).toHaveCount(2);
  await expect.poll(async () => (await page.locator(".perk-workbench").boundingBox())?.height)
    .toBeCloseTo(workbenchHeight, 0);

  await placedModifier.hover();
  await page.keyboard.press("f");
  await expect(page.getByRole("button", { name: /Quick Charge I, 1×1, at I2/ })).toHaveCount(0);
  await expect(page.locator(".family-connector")).toHaveCount(0);

  await page.getByRole("button", { name: "Show all perks" }).click();
  await page.getByRole("button", { name: "all", exact: true }).click();
  const perkSearch = page.getByRole("searchbox", { name: /Search \d+ perks/ });
  await perkSearch.fill("Tough Hombre");
  await page.locator(".perk-list-item").filter({
    has: page.getByText("Tough Hombre", { exact: true }),
  }).click();
  await page.locator(".perk-cell[data-row='4'][data-column='2']").click();
  const edgePerk = page.getByRole("button", { name: /Tough Hombre, 2×1, at B5/ });
  await page.keyboard.press("d");
  await expect(edgePerk).toBeVisible();
  await expect(page.getByRole("button", { name: /Tough Hombre, 1×2, at B5/ })).toHaveCount(0);
  await page.keyboard.press("f");

  await perkSearch.fill("Physician");
  await page.locator(".perk-list-item").filter({
    has: page.getByText("Physician", { exact: true }),
  }).click();
  await page.locator(".perk-cell[data-row='1'][data-column='2']").click();
  const physician = page.getByRole("button", { name: /Physician, 3×1, at B2/ });
  await physician.hover();
  await page.keyboard.press("r");
  await expect(page.locator(".modifier-context")).toHaveCount(0);
  await expect(physician).toHaveClass(/is-compatibility-context/);
  await expect(page.locator(".perk-list-item")).toHaveCount(6);

  await page.getByRole("button", { name: "Show all perks" }).click();
  await page.getByRole("button", { name: "modifier", exact: true }).click();
  const dependencyStatuses = await page.locator(".perk-list-item").evaluateAll((items) =>
    items.map((item) => item.getAttribute("data-dependency-status")),
  );
  const firstUnfulfilled = dependencyStatuses.indexOf("unfulfilled");
  expect(firstUnfulfilled).toBeGreaterThan(0);
  expect(dependencyStatuses.slice(firstUnfulfilled)).not.toContain("ready");
  const firstUnfulfilledPerk = page.locator(
    '.perk-list-item[data-dependency-status="unfulfilled"]',
  ).first();
  await expect(firstUnfulfilledPerk).toHaveCSS("color", "rgb(255, 255, 255)");
  await expect(firstUnfulfilledPerk).toHaveCSS(
    "border-top-color",
    "rgba(255, 255, 255, 0.38)",
  );
  await expect(firstUnfulfilledPerk).toHaveAttribute("data-card-tone", "gray");
  await expect(firstUnfulfilledPerk).toHaveAttribute("data-well-tone", "red");

  const boardBeforeUnlinked = await page.locator(".perk-board").boundingBox();
  const boardScrollBeforeUnlinked = await page.locator(".board-scroll").boundingBox();
  if (!boardBeforeUnlinked || !boardScrollBeforeUnlinked) {
    throw new Error("Perk board is not visible before unlinked placement");
  }
  await firstUnfulfilledPerk.click();
  await page.locator(".perk-cell.is-legal-footprint").last().click();
  await expect(page.locator('.placed-perk[data-link-status="unlinked"]')).toHaveCount(1);
  await expect(page.locator(".status-warning")).toContainText("1 unlinked");
  await expect(page.locator(".link-notice")).toHaveCount(0);
  await expect.poll(async () => (await page.locator(".perk-board").boundingBox())?.y)
    .toBeCloseTo(boardBeforeUnlinked.y, 0);
  await expect.poll(async () => (await page.locator(".board-scroll").boundingBox())?.height)
    .toBeCloseTo(boardScrollBeforeUnlinked.height, 0);
  await page.keyboard.press("f");
  await expect(page.locator('.placed-perk[data-link-status="unlinked"]')).toHaveCount(0);
});

test("Specialist ability slots start empty and clear or F returns kit defaults", async ({ page }) => {
  await page.goto("/");
  await page.evaluate(() => localStorage.clear());
  await page.reload();

  await page.getByRole("radio", { name: /Specialist/ }).click();
  const primary = page.locator(".ability-anchor--primary");
  const secondary = page.locator(".ability-anchor--secondary");
  const passive = page.locator(".ability-anchor--passive");
  await expect(primary).toHaveAttribute("aria-label", /ability: empty/);
  await expect(secondary).toHaveAttribute("aria-label", /ability: empty/);
  await expect(passive).toHaveAttribute("aria-label", /ability: empty/);

  await primary.click();
  const firstChoice = page.locator(".picker-option").first();
  await expect(firstChoice).toBeVisible();
  await expect(page.locator(".picker-option strong").filter({ hasText: /^Empty\b/i })).toHaveCount(0);
  await firstChoice.click();
  await expect(primary).not.toHaveAttribute("aria-label", /ability: empty/);
  await primary.hover();
  await page.keyboard.press("f");
  await expect(primary).toHaveAttribute("aria-label", /ability: empty/);

  await primary.click();
  await page.locator(".picker-option").first().click();
  await page.getByRole("button", { name: "Clear", exact: true }).click();
  await expect(primary).toHaveAttribute("aria-label", /ability: empty/);

  await page.getByRole("radio", { name: /Marauder/ }).click();
  await expect(primary).toHaveAttribute("aria-label", /Titan Rockets/);
  await primary.click();
  const alternateAbility = page.getByRole("button", { name: /ability Phosphorus Rocket/ });
  await alternateAbility.click();
  await primary.hover();
  await page.keyboard.press("f");
  await expect(primary).toHaveAttribute("aria-label", /Titan Rockets/);
});
