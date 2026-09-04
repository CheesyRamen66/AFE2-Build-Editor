import type {
  CatalogueIndex,
  ComponentSlot,
  EquipmentSlot,
  GridCell,
  KitGridLayout,
  KitRecord,
  PerkRecord,
  PerkShape,
  Rotation,
  WeaponRecord,
} from "./catalogue";

export const BUILD_SCHEMA_VERSION = 1;

export interface PlacedPerk {
  perkId: string;
  row: number;
  column: number;
  rotation: Rotation;
  targetId?: string;
}

export interface WeaponBuild {
  slotIndex: number;
  weaponId: string;
  attachments: Record<string, string | null>;
}

export interface BuildState {
  schemaVersion: typeof BUILD_SCHEMA_VERSION;
  sourceFingerprint: string;
  kitId: string;
  abilityIds: Array<string | null>;
  perks: PlacedPerk[];
  weapons: WeaponBuild[];
  itemIds: Array<string | null>;
}

export type BuildAction =
  | { type: "select-kit"; kitId: string }
  | { type: "select-ability"; slotIndex: number; abilityId: string }
  | { type: "reset-ability"; slotIndex: number }
  | { type: "place-perk"; placement: PlacedPerk }
  | { type: "move-perk"; perkId: string; row: number; column: number }
  | { type: "rotate-perk"; perkId: string; rotation: Rotation }
  | { type: "select-perk-target"; perkId: string; targetId: string }
  | { type: "remove-perk"; perkId: string }
  | { type: "clear-perks" }
  | { type: "select-weapon"; slotIndex: number; weaponId: string }
  | {
      type: "select-attachment";
      weaponSlotIndex: number;
      attachmentKey: string;
      recordId: string | null;
    }
  | { type: "select-item"; slotIndex: number; itemId: string | null };

export interface PlacementResult {
  valid: boolean;
  reason?: string;
  cells: GridCell[];
}

export interface GridIssue {
  code: "disconnected-modifier" | "invalid-target";
  perkId: string;
  message: string;
}

const ROTATION_TURNS: Record<Rotation, number> = {
  Default: 0,
  Clockwise90: 1,
  Clockwise180: 2,
  Clockwise270: 3,
};

export function attachmentSlotKey(slot: ComponentSlot | EquipmentSlot): string {
  return `${slot.kind}:${slot.index}:${slot.slotCategory}`;
}

export function weaponEquipmentSlots(weapon: WeaponRecord): Array<ComponentSlot | EquipmentSlot> {
  const slots: Array<ComponentSlot | EquipmentSlot> = [...weapon.componentSlots];
  if (weapon.compatibility.traitSlot) slots.push(weapon.compatibility.traitSlot);
  if (weapon.compatibility.augmentSlot) slots.push(weapon.compatibility.augmentSlot);
  return slots;
}

function createWeaponBuild(index: CatalogueIndex, slotIndex: number, weaponId: string): WeaponBuild {
  const weapon = index.byId.get(weaponId);
  if (!weapon || weapon.kind !== "weapon") {
    return { slotIndex, weaponId, attachments: {} };
  }

  return {
    slotIndex,
    weaponId,
    attachments: Object.fromEntries(
      weaponEquipmentSlots(weapon).map((slot) => {
        const defaultId = slot.kind === "trait" ? undefined : slot.defaultAttachmentId;
        const validDefault = defaultId && slot.compatibleIds.includes(defaultId) ? defaultId : null;
        return [attachmentSlotKey(slot), validDefault];
      }),
    ),
  };
}

function defaultAbilityId(
  index: CatalogueIndex,
  slot: KitRecord["abilitySlots"][number],
): string | null {
  const lockedAbility = index.byId.get(slot.lockedChipId);
  return lockedAbility?.kind === "ability" &&
    slot.selectableAbilityIds.includes(slot.lockedChipId)
    ? slot.lockedChipId
    : null;
}

function defaultAbilityIds(index: CatalogueIndex, kit: KitRecord): Array<string | null> {
  const highestSlotIndex = kit.abilitySlots.reduce(
    (highest, slot) => Math.max(highest, slot.index),
    -1,
  );
  const abilityIds = Array<string | null>(highestSlotIndex + 1).fill(null);
  for (const slot of kit.abilitySlots) abilityIds[slot.index] = defaultAbilityId(index, slot);
  return abilityIds;
}

function defaultWeaponId(
  index: CatalogueIndex,
  slot: KitRecord["weaponSlots"][number],
): string | undefined {
  const candidateIds = slot.defaultWeaponId && slot.compatibleWeaponIds.includes(slot.defaultWeaponId)
    ? [slot.defaultWeaponId, ...slot.compatibleWeaponIds]
    : slot.compatibleWeaponIds;
  return candidateIds.find((weaponId) => index.byId.get(weaponId)?.kind === "weapon");
}

export function createBuildForKit(index: CatalogueIndex, kitId: string): BuildState {
  const kit = index.byId.get(kitId);
  if (!kit || kit.kind !== "kit") {
    throw new Error(`Unknown kit: ${kitId}`);
  }

  const abilityIds = defaultAbilityIds(index, kit);

  const itemIds: Array<string | null> = [];
  for (const slot of index.catalogue.itemSlots) itemIds[slot.index] = null;

  return {
    schemaVersion: BUILD_SCHEMA_VERSION,
    sourceFingerprint: index.catalogue.sourceFingerprint,
    kitId,
    abilityIds,
    perks: [],
    weapons: kit.weaponSlots.flatMap((slot) => {
      const weaponId = defaultWeaponId(index, slot);
      return weaponId ? [createWeaponBuild(index, slot.index, weaponId)] : [];
    }),
    itemIds,
  };
}

export function hydrateLocalBuild(index: CatalogueIndex, raw: string | null): BuildState | null {
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as Partial<BuildState>;
    const kit = typeof value.kitId === "string" ? index.byId.get(value.kitId) : undefined;
    if (value.schemaVersion !== BUILD_SCHEMA_VERSION || !kit || kit.kind !== "kit") return null;

    const fresh = createBuildForKit(index, kit.id);
    let hydrated: BuildState = {
      ...fresh,
      abilityIds: Array.isArray(value.abilityIds) ? [...value.abilityIds] : fresh.abilityIds,
      perks: Array.isArray(value.perks) ? value.perks.filter(isPlacedPerk) : [],
      weapons: Array.isArray(value.weapons) ? value.weapons.filter(isWeaponBuild) : fresh.weapons,
      itemIds: Array.isArray(value.itemIds) ? value.itemIds : fresh.itemIds,
    };

    hydrated = sanitizeBuild(index, hydrated);
    return resolveModifierTargets(index, hydrated);
  } catch {
    return null;
  }
}

function isPlacedPerk(value: unknown): value is PlacedPerk {
  if (!value || typeof value !== "object") return false;
  const placement = value as Partial<PlacedPerk>;
  return (
    typeof placement.perkId === "string" &&
    Number.isInteger(placement.row) &&
    Number.isInteger(placement.column) &&
    typeof placement.rotation === "string" &&
    placement.rotation in ROTATION_TURNS
  );
}

function isWeaponBuild(value: unknown): value is WeaponBuild {
  if (!value || typeof value !== "object") return false;
  const weapon = value as Partial<WeaponBuild>;
  return (
    Number.isInteger(weapon.slotIndex) &&
    typeof weapon.weaponId === "string" &&
    !!weapon.attachments &&
    typeof weapon.attachments === "object"
  );
}

function sanitizeBuild(index: CatalogueIndex, state: BuildState): BuildState {
  const kit = index.byId.get(state.kitId);
  const layout = index.layoutByKitId.get(state.kitId);
  if (!kit || kit.kind !== "kit" || !layout) return createBuildForKit(index, index.kits[0].id);

  const clean = createBuildForKit(index, kit.id);
  clean.abilityIds = defaultAbilityIds(index, kit);
  for (const slot of kit.abilitySlots) {
    const candidate = state.abilityIds[slot.index];
    clean.abilityIds[slot.index] = typeof candidate === "string" &&
      index.byId.get(candidate)?.kind === "ability" &&
      slot.selectableAbilityIds.includes(candidate)
      ? candidate
      : defaultAbilityId(index, slot);
  }

  for (const placement of state.perks) {
    const perk = index.byId.get(placement.perkId);
    if (!perk || perk.kind !== "perk" || !kit.selectablePerkIds.includes(perk.id)) continue;
    if (!perk.grid.allowedRotations.includes(placement.rotation)) continue;
    const result = validatePlacement(index, layout, clean.perks, placement);
    if (result.valid) clean.perks.push({ ...placement });
  }

  clean.weapons = kit.weaponSlots.flatMap((slot) => {
    const saved = state.weapons.find((weapon) => weapon.slotIndex === slot.index);
    const savedRecord = saved ? index.byId.get(saved.weaponId) : undefined;
    const weaponId = saved && savedRecord?.kind === "weapon" &&
      slot.compatibleWeaponIds.includes(saved.weaponId)
      ? saved.weaponId
      : defaultWeaponId(index, slot);
    if (!weaponId) return [];
    const next = createWeaponBuild(index, slot.index, weaponId);
    const record = index.byId.get(weaponId);
    if (!saved || !record || record.kind !== "weapon") return [next];
    for (const equipmentSlot of weaponEquipmentSlots(record)) {
      const key = attachmentSlotKey(equipmentSlot);
      if (!Object.prototype.hasOwnProperty.call(saved.attachments, key)) continue;
      const selected = saved.attachments[key];
      if (selected === null || (selected && equipmentSlot.compatibleIds.includes(selected))) {
        next.attachments[key] = selected;
      }
    }
    return [next];
  });

  clean.itemIds = [];
  for (const slot of index.catalogue.itemSlots) {
    const selected = state.itemIds[slot.index];
    clean.itemIds[slot.index] = selected && slot.compatibleItemIds.includes(selected)
      ? selected
      : null;
  }
  return clean;
}

export function reduceBuild(
  index: CatalogueIndex,
  state: BuildState,
  action: BuildAction,
): BuildState {
  switch (action.type) {
    case "select-kit":
      return createBuildForKit(index, action.kitId);
    case "select-ability": {
      const kit = index.byId.get(state.kitId);
      if (!kit || kit.kind !== "kit") return state;
      const slot = kit.abilitySlots.find((candidate) => candidate.index === action.slotIndex);
      if (
        !slot?.selectableAbilityIds.includes(action.abilityId) ||
        index.byId.get(action.abilityId)?.kind !== "ability"
      ) {
        return state;
      }
      const abilityIds = [...state.abilityIds];
      abilityIds[action.slotIndex] = action.abilityId;
      return resolveModifierTargets(index, { ...state, abilityIds });
    }
    case "reset-ability": {
      const kit = index.byId.get(state.kitId);
      if (!kit || kit.kind !== "kit") return state;
      const slot = kit.abilitySlots.find((candidate) => candidate.index === action.slotIndex);
      if (!slot) return state;
      const abilityIds = [...state.abilityIds];
      abilityIds[action.slotIndex] = defaultAbilityId(index, slot);
      return resolveModifierTargets(index, { ...state, abilityIds });
    }
    case "place-perk": {
      const kit = index.byId.get(state.kitId);
      const layout = index.layoutByKitId.get(state.kitId);
      if (
        !kit ||
        kit.kind !== "kit" ||
        !kit.selectablePerkIds.includes(action.placement.perkId) ||
        !layout ||
        !validatePlacement(index, layout, state.perks, action.placement).valid
      ) {
        return state;
      }
      return resolveModifierTargets(index, {
        ...state,
        perks: [...state.perks, action.placement],
      });
    }
    case "select-perk-target": {
      if (!availableModifierTargetIds(index, state, action.perkId).includes(action.targetId)) {
        return state;
      }
      return resolveModifierTargets(index, {
        ...state,
        perks: state.perks.map((placement) =>
          placement.perkId === action.perkId
            ? { ...placement, targetId: action.targetId }
            : placement,
        ),
      });
    }
    case "move-perk": {
      const layout = index.layoutByKitId.get(state.kitId);
      const current = state.perks.find((placement) => placement.perkId === action.perkId);
      if (!layout || !current) return state;
      const moved = { ...current, row: action.row, column: action.column };
      if (!validatePlacement(index, layout, state.perks, moved, action.perkId).valid) return state;
      return resolveModifierTargets(index, {
        ...state,
        perks: state.perks.map((placement) =>
          placement.perkId === action.perkId ? moved : placement,
        ),
      });
    }
    case "rotate-perk": {
      const layout = index.layoutByKitId.get(state.kitId);
      const current = state.perks.find((placement) => placement.perkId === action.perkId);
      if (!layout || !current) return state;
      const rotated = { ...current, rotation: action.rotation };
      if (!validatePlacement(index, layout, state.perks, rotated, action.perkId).valid) return state;
      return resolveModifierTargets(index, {
        ...state,
        perks: state.perks.map((placement) =>
          placement.perkId === action.perkId ? rotated : placement,
        ),
      });
    }
    case "remove-perk":
      return resolveModifierTargets(index, {
        ...state,
        perks: state.perks.filter((placement) => placement.perkId !== action.perkId),
      });
    case "clear-perks": {
      const kit = index.byId.get(state.kitId);
      if (!kit || kit.kind !== "kit") return state;
      return {
        ...state,
        abilityIds: defaultAbilityIds(index, kit),
        perks: [],
      };
    }
    case "select-weapon": {
      const kit = index.byId.get(state.kitId);
      if (!kit || kit.kind !== "kit") return state;
      const slot = kit.weaponSlots.find((candidate) => candidate.index === action.slotIndex);
      const weapon = index.byId.get(action.weaponId);
      if (!slot?.compatibleWeaponIds.includes(action.weaponId) || weapon?.kind !== "weapon") {
        return state;
      }
      const replacement = createWeaponBuild(index, slot.index, action.weaponId);
      return {
        ...state,
        weapons: state.weapons.map((weapon) =>
          weapon.slotIndex === slot.index ? replacement : weapon,
        ),
      };
    }
    case "select-attachment": {
      const selectedWeapon = state.weapons.find(
        (weapon) => weapon.slotIndex === action.weaponSlotIndex,
      );
      if (!selectedWeapon) return state;
      const weapon = index.byId.get(selectedWeapon.weaponId);
      if (!weapon || weapon.kind !== "weapon") return state;
      const slot = weaponEquipmentSlots(weapon).find(
        (candidate) => attachmentSlotKey(candidate) === action.attachmentKey,
      );
      if (!slot || (action.recordId !== null && !slot.compatibleIds.includes(action.recordId))) {
        return state;
      }
      return {
        ...state,
        weapons: state.weapons.map((entry) =>
          entry.slotIndex === selectedWeapon.slotIndex
            ? {
                ...entry,
                attachments: { ...entry.attachments, [action.attachmentKey]: action.recordId },
              }
            : entry,
        ),
      };
    }
    case "select-item": {
      const slot = index.catalogue.itemSlots.find((candidate) => candidate.index === action.slotIndex);
      if (!slot || (action.itemId !== null && !slot.compatibleItemIds.includes(action.itemId))) {
        return state;
      }
      const itemIds = [...state.itemIds];
      itemIds[action.slotIndex] = action.itemId;
      return { ...state, itemIds };
    }
  }
}

export function rotateShape(shape: PerkShape, rotation: Rotation): PerkShape {
  const turns = ROTATION_TURNS[rotation];
  let width = shape.width;
  let height = shape.height;
  let cells = shape.occupiedCells.map(({ row, column }) => ({ row, column }));

  for (let turn = 0; turn < turns; turn += 1) {
    cells = cells.map(({ row, column }) => ({ row: column, column: height - 1 - row }));
    [width, height] = [height, width];
  }

  return { ...shape, width, height, occupiedCells: cells };
}

export function occupiedCells(perk: PerkRecord, placement: PlacedPerk): GridCell[] {
  const shape = rotateShape(perk.grid.shapes[0], placement.rotation);
  return shape.occupiedCells.map((cell) => ({
    row: placement.row + cell.row,
    column: placement.column + cell.column,
  }));
}

function cellKey(cell: GridCell): string {
  return `${cell.row}:${cell.column}`;
}

export function validatePlacement(
  index: CatalogueIndex,
  layout: KitGridLayout,
  placements: PlacedPerk[],
  candidate: PlacedPerk,
  ignorePerkId?: string,
): PlacementResult {
  const record = index.byId.get(candidate.perkId);
  if (!record || record.kind !== "perk") {
    return { valid: false, reason: "That perk is not in this catalogue.", cells: [] };
  }
  if (!record.grid.allowedRotations.includes(candidate.rotation)) {
    return { valid: false, reason: "That rotation is not allowed for this perk.", cells: [] };
  }
  if (placements.some((placement) => placement.perkId === candidate.perkId && placement.perkId !== ignorePerkId)) {
    return { valid: false, reason: "Each perk can only be placed once.", cells: [] };
  }

  const cells = occupiedCells(record, candidate);
  const placeable = new Set(layout.placeableCells.map(cellKey));
  const unavailable = cells.find((cell) => !placeable.has(cellKey(cell)));
  if (unavailable) {
    return {
      valid: false,
      reason: `The perk does not fit at ${gridCellLabel(unavailable)}.`,
      cells,
    };
  }

  const occupied = new Set<string>();
  for (const placement of placements) {
    if (placement.perkId === ignorePerkId) continue;
    const perk = index.byId.get(placement.perkId);
    if (!perk || perk.kind !== "perk") continue;
    occupiedCells(perk, placement).forEach((cell) => occupied.add(cellKey(cell)));
  }
  const collision = cells.find((cell) => occupied.has(cellKey(cell)));
  if (collision) {
    return {
      valid: false,
      reason: `${gridCellLabel(collision)} is already occupied.`,
      cells,
    };
  }
  return { valid: true, cells };
}

export function gridCellLabel(cell: GridCell): string {
  return `${String.fromCharCode(65 + cell.column)}${cell.row + 1}`;
}

export function nextRotation(perk: PerkRecord, rotation: Rotation): Rotation {
  const rotations = perk.grid.allowedRotations;
  const index = rotations.indexOf(rotation);
  return rotations[(index + 1 + rotations.length) % rotations.length] ?? "Default";
}

interface GridNode {
  id: string;
  cells: GridCell[];
  terminal: boolean;
}

function nodesTouch(left: GridNode, right: GridNode): boolean {
  return left.cells.some((a) =>
    right.cells.some((b) => Math.abs(a.row - b.row) + Math.abs(a.column - b.column) === 1),
  );
}

function buildGridNodes(index: CatalogueIndex, state: BuildState): GridNode[] {
  const nodes: GridNode[] = [];
  for (const placement of state.perks) {
    const perk = index.byId.get(placement.perkId);
    if (!perk || perk.kind !== "perk") continue;
    nodes.push({
      id: perk.id,
      cells: occupiedCells(perk, placement),
      terminal: perk.perkType === "core",
    });
  }

  const kit = index.byId.get(state.kitId);
  const layout = index.layoutByKitId.get(state.kitId);
  if (!kit || kit.kind !== "kit" || !layout) return nodes;
  for (const slot of kit.abilitySlots) {
    const anchor = layout.anchors.find((candidate) => candidate.role === slot.role);
    const abilityId = state.abilityIds[slot.index];
    if (anchor && abilityId) nodes.push({ id: abilityId, cells: anchor.cells, terminal: true });
  }
  return nodes;
}

function connectedNodeIds(nodes: GridNode[], sourceId: string): Set<string> {
  const source = nodes.find((node) => node.id === sourceId);
  if (!source) return new Set();
  const connected = new Set([source.id]);
  const queue = [source];
  while (queue.length) {
    const current = queue.shift()!;
    for (const candidate of nodes) {
      if (!connected.has(candidate.id) && nodesTouch(current, candidate)) {
        connected.add(candidate.id);
        queue.push(candidate);
      }
    }
  }
  return connected;
}

function targetChainReachesTerminal(
  nodes: GridNode[],
  state: BuildState,
  candidateId: string,
  blockedId: string,
  visiting = new Set<string>(),
): boolean {
  if (candidateId === blockedId || visiting.has(candidateId)) return false;
  const node = nodes.find((entry) => entry.id === candidateId);
  if (!node) return false;
  if (node.terminal) return true;
  const nextTargetId = state.perks.find((placement) => placement.perkId === candidateId)?.targetId;
  if (!nextTargetId) return false;
  return targetChainReachesTerminal(
    nodes,
    state,
    nextTargetId,
    blockedId,
    new Set(visiting).add(candidateId),
  );
}

export function resolveModifierTargets(index: CatalogueIndex, state: BuildState): BuildState {
  const nodes = buildGridNodes(index, state);
  const placementsById = new Map(state.perks.map((placement) => [placement.perkId, placement]));
  const resolved = new Map<string, string>();

  const resolveTarget = (perkId: string, visiting: Set<string>): string | undefined => {
    if (resolved.has(perkId)) return resolved.get(perkId);
    if (visiting.has(perkId)) return undefined;
    const perk = index.byId.get(perkId);
    if (!perk || perk.kind !== "perk" || perk.perkType !== "modifier") return undefined;
    const component = connectedNodeIds(nodes, perkId);
    const candidateIds = perk.dependencies?.targetSelection?.candidateIds ??
      perk.dependencies?.possibleTargetPerkIds ?? [];
    const available = candidateIds.filter((candidateId) => component.has(candidateId));
    const selectedTarget = placementsById.get(perkId)?.targetId;
    const ordered = selectedTarget && available.includes(selectedTarget)
      ? [selectedTarget, ...available.filter((candidateId) => candidateId !== selectedTarget)]
      : available;

    const nextVisiting = new Set(visiting).add(perkId);
    for (const candidateId of ordered) {
      const candidateNode = nodes.find((node) => node.id === candidateId);
      if (candidateNode?.terminal) {
        resolved.set(perkId, candidateId);
        return candidateId;
      }
      if (resolveTarget(candidateId, nextVisiting)) {
        resolved.set(perkId, candidateId);
        return candidateId;
      }
    }
    return undefined;
  };

  const perks = state.perks.map((placement) => {
    const perk = index.byId.get(placement.perkId);
    if (!perk || perk.kind !== "perk" || perk.perkType !== "modifier") {
      const { targetId: _targetId, ...withoutTarget } = placement;
      return withoutTarget;
    }
    const targetId = resolveTarget(perk.id, new Set());
    return targetId ? { ...placement, targetId } : { ...placement, targetId: undefined };
  });
  return { ...state, perks };
}

export function availableModifierTargetIds(
  index: CatalogueIndex,
  state: BuildState,
  perkId: string,
): string[] {
  const perk = index.byId.get(perkId);
  if (!perk || perk.kind !== "perk" || perk.perkType !== "modifier") return [];
  const nodes = buildGridNodes(index, state);
  const component = connectedNodeIds(nodes, perkId);
  const candidateIds = perk.dependencies?.targetSelection?.candidateIds ??
    perk.dependencies?.possibleTargetPerkIds ?? [];
  return candidateIds.filter(
    (candidateId) => component.has(candidateId) &&
      targetChainReachesTerminal(nodes, state, candidateId, perkId),
  );
}

export function validateGridLinks(index: CatalogueIndex, state: BuildState): GridIssue[] {
  const issues: GridIssue[] = [];
  for (const placement of state.perks) {
    const perk = index.byId.get(placement.perkId);
    if (
      !perk ||
      perk.kind !== "perk" ||
      !perk.dependencies?.requiresConnectedCompatibleTarget
    ) {
      continue;
    }
    if (!placement.targetId) {
      issues.push({
        code: "disconnected-modifier",
        perkId: perk.id,
        message: `${perk.displayName} needs an orthogonal connection to a compatible perk or ability.`,
      });
      continue;
    }
    const candidates = perk.dependencies.targetSelection?.candidateIds ??
      perk.dependencies.possibleTargetPerkIds ?? [];
    if (!candidates.includes(placement.targetId)) {
      issues.push({
        code: "invalid-target",
        perkId: perk.id,
        message: `${perk.displayName} is linked to an incompatible target.`,
      });
    }
  }
  return issues;
}
