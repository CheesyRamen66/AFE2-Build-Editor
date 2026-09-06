import {
  Link2,
  MousePointer2,
  RotateCw,
  Search,
  Unlink,
  X,
} from "lucide-react";
import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type DragEvent,
} from "react";
import { createPortal } from "react-dom";
import { catalogueAssetUrl, plainGameText } from "../data/catalogue";
import {
  availableModifierFamilyChoices,
  canRotate,
  gridCellLabel,
  nextRotation,
  occupiedCells,
  resolveModifierTargets,
  rotateShape,
  validateGridLinks,
  validatePlacement,
  type BuildAction,
  type BuildState,
  type ModifierFamilyChoice,
  type PlacedPerk,
} from "../model/build";
import type {
  AbilitySlot,
  CatalogueIndex,
  GridCell,
  KitGridLayout,
  KitRecord,
  PerkRecord,
  Rotation,
} from "../model/catalogue";
import { calculateFamilyConnectors } from "../model/familyConnectors";
import { RecordVisual } from "./RecordVisual";

interface PerkWorkbenchProps {
  index: CatalogueIndex;
  kit: KitRecord;
  layout: KitGridLayout;
  build: BuildState;
  dispatch: (action: BuildAction) => void;
  onChooseAbility: (slot: AbilitySlot) => void;
  notify: (message: string) => void;
}

interface GridMetrics {
  cellWidth: number;
  cellHeight: number;
  columnGap: number;
  rowGap: number;
}

interface GrabOffset {
  x: number;
  y: number;
}

interface GridBounds {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

interface SnappedPlacement {
  placement: PlacedPerk;
  cells: GridCell[];
  left: number;
  top: number;
  overlaps: boolean;
  familyLinked: boolean;
}

type PerkFilter = "all" | "core" | "modifier";

interface GridChipTooltip {
  chipKey: string;
  title: string;
  description: string;
  x: number;
  y: number;
  placement: "above" | "below";
}

type FamilyAssignmentKind = "place" | "move" | "rotate";

interface PendingFamilyAssignment {
  kind: FamilyAssignmentKind;
  placement: PlacedPerk;
  choices: ModifierFamilyChoice[];
  successMessage: string;
}

const FALLBACK_GRID_METRICS: GridMetrics = {
  cellWidth: 47,
  cellHeight: 47,
  columnGap: 6,
  rowGap: 6,
};

const ROTATION_TURNS: Record<Rotation, number> = {
  Default: 0,
  Clockwise90: 1,
  Clockwise180: 2,
  Clockwise270: 3,
};

const GAME_CHIP_COLORS = {
  kit: "#c9fe90",
  role: "#8acaf8",
} as const;

type HoveredGridChip =
  | { kind: "ability"; slotIndex: number }
  | { kind: "perk"; perkId: string };

function cellKey(cell: GridCell): string {
  return `${cell.row}:${cell.column}`;
}

function gridCellAtPoint(board: Element | null, clientX: number, clientY: number): GridCell | undefined {
  if (!board) return undefined;
  for (const cell of board.querySelectorAll<HTMLElement>(".perk-cell")) {
    const bounds = cell.getBoundingClientRect();
    if (
      clientX >= bounds.left && clientX <= bounds.right &&
      clientY >= bounds.top && clientY <= bounds.bottom
    ) {
      const row = Number(cell.dataset.row);
      const column = Number(cell.dataset.column);
      if (Number.isInteger(row) && Number.isInteger(column)) return { row, column };
    }
  }
  return undefined;
}

function pointInBounds(bounds: GridBounds, clientX: number, clientY: number): boolean {
  return clientX >= bounds.left && clientX <= bounds.right &&
    clientY >= bounds.top && clientY <= bounds.bottom;
}

function gridBounds(
  board: HTMLElement | null,
  layout: KitGridLayout,
  metrics: GridMetrics,
): GridBounds | undefined {
  if (!board) return undefined;
  const boardRect = board.getBoundingClientRect();
  if (boardRect.width > 0 && boardRect.height > 0) {
    return {
      left: boardRect.left,
      top: boardRect.top,
      right: boardRect.right,
      bottom: boardRect.bottom,
    };
  }

  const firstCell = board.querySelector<HTMLElement>(".perk-cell[data-row='0'][data-column='0']") ??
    board.querySelector<HTMLElement>(".perk-cell");
  const firstRect = firstCell?.getBoundingClientRect();
  if (!firstRect || firstRect.width <= 0 || firstRect.height <= 0) return undefined;
  return {
    left: firstRect.left,
    top: firstRect.top,
    right: firstRect.left + layout.renderExtent.columns * metrics.cellWidth +
      Math.max(0, layout.renderExtent.columns - 1) * metrics.columnGap,
    bottom: firstRect.top + layout.renderExtent.rows * metrics.cellHeight +
      Math.max(0, layout.renderExtent.rows - 1) * metrics.rowGap,
  };
}

function gridCellPosition(
  board: HTMLElement | null,
  row: number,
  column: number,
  metrics: GridMetrics,
): { left: number; top: number } | undefined {
  if (!board) return undefined;
  const exactCell = board.querySelector<HTMLElement>(
    `.perk-cell[data-row='${row}'][data-column='${column}']`,
  );
  const exactRect = exactCell?.getBoundingClientRect();
  if (exactRect && exactRect.width > 0 && exactRect.height > 0) {
    return { left: exactRect.left, top: exactRect.top };
  }
  const firstCell = board.querySelector<HTMLElement>(".perk-cell[data-row='0'][data-column='0']") ??
    board.querySelector<HTMLElement>(".perk-cell");
  const firstRect = firstCell?.getBoundingClientRect();
  if (firstRect && firstRect.width > 0 && firstRect.height > 0) {
    return {
      left: firstRect.left + column * (metrics.cellWidth + metrics.columnGap),
      top: firstRect.top + row * (metrics.cellHeight + metrics.rowGap),
    };
  }

  const boardRect = board.getBoundingClientRect();
  if (boardRect.width <= 0 || boardRect.height <= 0) return undefined;
  const style = window.getComputedStyle(board);
  const paddingLeft = finiteNonNegative(style.paddingLeft, 13);
  const paddingTop = finiteNonNegative(style.paddingTop, 13);
  return {
    left: boardRect.left + paddingLeft + column * (metrics.cellWidth + metrics.columnGap),
    top: boardRect.top + paddingTop + row * (metrics.cellHeight + metrics.rowGap),
  };
}

function fittingPlacements(
  perk: PerkRecord,
  rotation: Rotation,
  layout: KitGridLayout,
): PlacedPerk[] {
  const placeable = new Set(layout.placeableCells.map(cellKey));
  const placements: PlacedPerk[] = [];
  for (let row = 0; row < layout.renderExtent.rows; row += 1) {
    for (let column = 0; column < layout.renderExtent.columns; column += 1) {
      const placement = { perkId: perk.id, row, column, rotation };
      if (occupiedCells(perk, placement).every((cell) => placeable.has(cellKey(cell)))) {
        placements.push(placement);
      }
    }
  }
  return placements;
}

function finitePositive(value: string | number, fallback: number): number {
  const parsed = typeof value === "number" ? value : Number.parseFloat(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function finiteNonNegative(value: string | number, fallback: number): number {
  const parsed = typeof value === "number" ? value : Number.parseFloat(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
}

function measureGridMetrics(board: HTMLElement | null): GridMetrics {
  if (!board) return FALLBACK_GRID_METRICS;
  const firstCell = board.querySelector<HTMLElement>(".perk-cell");
  const cellBounds = firstCell?.getBoundingClientRect();
  const style = window.getComputedStyle(board);
  return {
    cellWidth: finitePositive(cellBounds?.width ?? 0, FALLBACK_GRID_METRICS.cellWidth),
    cellHeight: finitePositive(cellBounds?.height ?? 0, FALLBACK_GRID_METRICS.cellHeight),
    columnGap: finiteNonNegative(style.columnGap, FALLBACK_GRID_METRICS.columnGap),
    rowGap: finiteNonNegative(style.rowGap, FALLBACK_GRID_METRICS.rowGap),
  };
}

function footprintDimensions(
  shape: { width: number; height: number },
  metrics: GridMetrics,
): { width: number; height: number } {
  return {
    width: shape.width * metrics.cellWidth + Math.max(0, shape.width - 1) * metrics.columnGap,
    height: shape.height * metrics.cellHeight + Math.max(0, shape.height - 1) * metrics.rowGap,
  };
}

function centeredGrabOffset(
  shape: { width: number; height: number },
  metrics: GridMetrics,
): GrabOffset {
  const dimensions = footprintDimensions(shape, metrics);
  return { x: dimensions.width / 2, y: dimensions.height / 2 };
}

function grabOffsetFromBounds(
  bounds: DOMRect,
  clientX: number,
  clientY: number,
  shape: { width: number; height: number },
  metrics: GridMetrics,
): GrabOffset {
  const dimensions = footprintDimensions(shape, metrics);
  if (
    !bounds.width ||
    !bounds.height ||
    !Number.isFinite(clientX) ||
    !Number.isFinite(clientY)
  ) {
    return centeredGrabOffset(shape, metrics);
  }
  return {
    x: Math.min(dimensions.width, Math.max(0, clientX - bounds.left)),
    y: Math.min(dimensions.height, Math.max(0, clientY - bounds.top)),
  };
}

function axisAnchor(offset: number, count: number, cellSize: number, gap: number): number {
  if (count <= 1) return 0;
  const footprintSize = count * cellSize + (count - 1) * gap;
  const clamped = Math.min(Math.max(0, offset), Math.max(0, footprintSize - 0.001));
  const step = cellSize + gap;
  // Split the gap between its neighbouring cells so picking up an edge or seam
  // still resolves to the visually nearest segment of the brick.
  return Math.min(count - 1, Math.floor((clamped + gap / 2) / step));
}

function grabAnchor(
  offset: GrabOffset,
  shape: { width: number; height: number },
  metrics: GridMetrics,
): GridCell {
  return {
    row: axisAnchor(offset.y, shape.height, metrics.cellHeight, metrics.rowGap),
    column: axisAnchor(offset.x, shape.width, metrics.cellWidth, metrics.columnGap),
  };
}

function rotateGrabOffset(
  offset: GrabOffset,
  fromShape: { width: number; height: number },
  toShape: { width: number; height: number },
  fromRotation: Rotation,
  toRotation: Rotation,
  metrics: GridMetrics,
): GrabOffset {
  const from = footprintDimensions(fromShape, metrics);
  const to = footprintDimensions(toShape, metrics);
  let x = from.width ? offset.x / from.width : 0.5;
  let y = from.height ? offset.y / from.height : 0.5;
  const turns = (ROTATION_TURNS[toRotation] - ROTATION_TURNS[fromRotation] + 4) % 4;
  for (let turn = 0; turn < turns; turn += 1) [x, y] = [1 - y, x];
  return {
    x: Math.min(to.width, Math.max(0, x * to.width)),
    y: Math.min(to.height, Math.max(0, y * to.height)),
  };
}

function chipBodyPath(perk: PerkRecord, rotation: Rotation): string | undefined {
  const shape = rotateShape(perk.grid.shapes[0], rotation);
  const match = perk.rendering?.chipBodyByFootprint?.find(
    (body) => body.footprint?.width === shape.width && body.footprint?.height === shape.height,
  );
  return match?.path ?? perk.rendering?.chipBodyByFootprint?.[0]?.path;
}

function footprintLabel(perk: PerkRecord, rotation: Rotation = "Default"): string {
  const shape = rotateShape(perk.grid.shapes[0], rotation);
  return `${shape.width}×${shape.height}`;
}

function modifierCandidateIds(perk: PerkRecord): string[] {
  return perk.dependencies?.targetSelection?.candidateIds ??
    perk.dependencies?.possibleTargetPerkIds ?? [];
}

function terminalCandidateIds(
  index: CatalogueIndex,
  perk: PerkRecord,
  visiting = new Set<string>(),
): Set<string> {
  if (visiting.has(perk.id)) return new Set();
  const nextVisiting = new Set(visiting).add(perk.id);
  const terminalIds = new Set<string>();
  for (const candidateId of modifierCandidateIds(perk)) {
    const candidate = index.byId.get(candidateId);
    if (candidate?.kind === "ability" || (candidate?.kind === "perk" && candidate.perkType === "core")) {
      terminalIds.add(candidateId);
    } else if (candidate?.kind === "perk" && candidate.perkType === "modifier") {
      terminalCandidateIds(index, candidate, nextVisiting).forEach((id) => terminalIds.add(id));
    }
  }
  return terminalIds;
}

function placedModifierTerminalId(
  index: CatalogueIndex,
  build: BuildState,
  perkId: string,
): string | undefined {
  const visited = new Set<string>();
  let currentId: string | undefined = perkId;
  while (currentId && !visited.has(currentId)) {
    visited.add(currentId);
    const record = index.byId.get(currentId);
    if (record?.kind === "ability" || (record?.kind === "perk" && record.perkType === "core")) {
      return currentId;
    }
    if (record?.kind !== "perk" || record.perkType !== "modifier") return undefined;
    currentId = build.perks.find((placement) => placement.perkId === currentId)?.targetId;
  }
  return undefined;
}

function familyLinkedAtPlacement(
  index: CatalogueIndex,
  build: BuildState,
  candidate: PlacedPerk,
  movingPerkId?: string,
): boolean {
  const perk = index.byId.get(candidate.perkId);
  if (!perk || perk.kind !== "perk") return false;

  const previousRootId = movingPerkId
    ? (perk.perkType === "core"
        ? perk.id
        : placedModifierTerminalId(index, build, movingPerkId))
    : undefined;
  const previousFamilyIds = previousRootId
    ? build.perks
        .filter((placement) => (
          placement.perkId === previousRootId ||
          placedModifierTerminalId(index, build, placement.perkId) === previousRootId
        ))
        .map((placement) => placement.perkId)
    : [];

  const existing = movingPerkId
    ? build.perks.find((placement) => placement.perkId === movingPerkId)
    : undefined;
  const nextPlacement = existing ? { ...existing, ...candidate } : candidate;
  const nextPerks = movingPerkId
    ? build.perks.map((placement) => (
        placement.perkId === movingPerkId ? nextPlacement : placement
      ))
    : [...build.perks, nextPlacement];
  const hypothetical = resolveModifierTargets(index, { ...build, perks: nextPerks });

  if (perk.dependencies?.requiresConnectedCompatibleTarget) {
    const choices = availableModifierFamilyChoices(index, hypothetical, perk.id);
    if (nextPlacement.targetFamilyId) {
      if (!choices.some((choice) => choice.familyId === nextPlacement.targetFamilyId)) {
        return false;
      }
    } else if (!choices.length) {
      return false;
    }
  }

  if (!previousRootId || previousFamilyIds.length <= 1) return true;
  return previousFamilyIds.every((perkId) => {
    if (perkId === previousRootId) return true;
    return placedModifierTerminalId(index, hypothetical, perkId) === previousRootId;
  });
}

function snappedPlacementAtPoint(
  index: CatalogueIndex,
  layout: KitGridLayout,
  build: BuildState,
  perk: PerkRecord,
  rotation: Rotation,
  movingPerkId: string | undefined,
  board: HTMLElement | null,
  metrics: GridMetrics,
  offset: GrabOffset,
  clientX: number,
  clientY: number,
): SnappedPlacement | undefined {
  const bounds = gridBounds(board, layout, metrics);
  if (!bounds || !pointInBounds(bounds, clientX, clientY)) return undefined;

  let closest: { placement: PlacedPerk; left: number; top: number; distance: number } | undefined;
  for (const placement of fittingPlacements(perk, rotation, layout)) {
    const position = gridCellPosition(board, placement.row, placement.column, metrics);
    if (!position) continue;
    const deltaX = position.left + offset.x - clientX;
    const deltaY = position.top + offset.y - clientY;
    const distance = deltaX * deltaX + deltaY * deltaY;
    if (!closest || distance < closest.distance) {
      closest = { placement, ...position, distance };
    }
  }
  if (!closest) return undefined;

  const result = validatePlacement(
    index,
    layout,
    build.perks,
    closest.placement,
    movingPerkId,
  );
  return {
    placement: closest.placement,
    cells: occupiedCells(perk, closest.placement),
    left: closest.left,
    top: closest.top,
    overlaps: !result.valid,
    familyLinked: familyLinkedAtPlacement(index, build, closest.placement, movingPerkId),
  };
}

function snappedPlacementAtCell(
  index: CatalogueIndex,
  layout: KitGridLayout,
  build: BuildState,
  perk: PerkRecord,
  rotation: Rotation,
  movingPerkId: string | undefined,
  grabbedCell: GridCell,
  grabOffset: GrabOffset,
  metrics: GridMetrics,
): SnappedPlacement | undefined {
  const shape = rotateShape(perk.grid.shapes[0], rotation);
  const anchor = grabAnchor(grabOffset, shape, metrics);
  const desiredOrigin = {
    row: grabbedCell.row - anchor.row,
    column: grabbedCell.column - anchor.column,
  };
  const placements = fittingPlacements(perk, rotation, layout);
  const placement = placements.reduce<PlacedPerk | undefined>((closest, candidate) => {
    if (!closest) return candidate;
    const candidateDistance = (candidate.row - desiredOrigin.row) ** 2 +
      (candidate.column - desiredOrigin.column) ** 2;
    const closestDistance = (closest.row - desiredOrigin.row) ** 2 +
      (closest.column - desiredOrigin.column) ** 2;
    return candidateDistance < closestDistance ? candidate : closest;
  }, undefined);
  if (!placement) return undefined;
  const result = validatePlacement(index, layout, build.perks, placement, movingPerkId);
  return {
    placement,
    cells: occupiedCells(perk, placement),
    left: 0,
    top: 0,
    overlaps: !result.valid,
    familyLinked: familyLinkedAtPlacement(index, build, placement, movingPerkId),
  };
}

function pointJustOutsideBounds(
  bounds: GridBounds,
  clientX: number,
  clientY: number,
  margin: number,
): boolean {
  if (pointInBounds(bounds, clientX, clientY)) return false;
  return clientX >= bounds.left - margin && clientX <= bounds.right + margin &&
    clientY >= bounds.top - margin && clientY <= bounds.bottom + margin;
}

function visualRestrictionType(record: unknown): string | undefined {
  if (!record || typeof record !== "object") return undefined;
  const classification = (record as {
    visualClassification?: { restrictionType?: unknown };
  }).visualClassification;
  return typeof classification?.restrictionType === "string"
    ? classification.restrictionType.toLocaleLowerCase()
    : undefined;
}

function perkChipColor(perk: PerkRecord, kitCount: number): string {
  const restrictionType = visualRestrictionType(perk);
  if (restrictionType === "kit") return GAME_CHIP_COLORS.kit;
  if (restrictionType === "role" || restrictionType === "none") return GAME_CHIP_COLORS.role;

  // Older local catalogues predate visualClassification. Eligibility provides a
  // deterministic approximation until they are regenerated by the extractor.
  return new Set(perk.availableToKitIds).size < kitCount
    ? GAME_CHIP_COLORS.kit
    : GAME_CHIP_COLORS.role;
}

function abilityChipColor(record: unknown, role: string): string {
  if (!record) return GAME_CHIP_COLORS.kit;
  const restrictionType = visualRestrictionType(record);
  if (restrictionType === "kit") return GAME_CHIP_COLORS.kit;
  if (restrictionType === "role" || restrictionType === "none") return GAME_CHIP_COLORS.role;
  return role === "passive" ? GAME_CHIP_COLORS.role : GAME_CHIP_COLORS.kit;
}

function chipBodyStyle(path: string | undefined, color: string): CSSProperties {
  const body = path ? `url("${catalogueAssetUrl(path)}")` : "none";
  return {
    "--chip-body": body,
    "--chip-color": color,
    backgroundImage: path ? body : undefined,
  } as CSSProperties;
}

function isEditableTarget(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && (
    target.isContentEditable ||
    target.matches("input, textarea, select, [contenteditable='true']")
  );
}

interface ModifierFamilyDialogProps {
  index: CatalogueIndex;
  perk: PerkRecord;
  choices: ModifierFamilyChoice[];
  onSelect: (choice: ModifierFamilyChoice) => void;
  onCancel: () => void;
}

function ModifierFamilyDialog({
  index,
  perk,
  choices,
  onSelect,
  onCancel,
}: ModifierFamilyDialogProps) {
  const titleId = useId();
  const descriptionId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const firstChoiceRef = useRef<HTMLButtonElement>(null);
  const cancelRef = useRef(onCancel);
  cancelRef.current = onCancel;

  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    firstChoiceRef.current?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        cancelRef.current();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = [...dialogRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [tabindex]:not([tabindex="-1"])',
      )];
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = originalOverflow;
      document.removeEventListener("keydown", onKeyDown);
      previous?.focus();
    };
  }, []);

  return createPortal(
    <div
      className="picker-overlay modifier-family-overlay"
      data-placement="center"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onCancel();
      }}
    >
      <div
        ref={dialogRef}
        className="picker-dialog modifier-family-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
      >
        <header className="picker-header modifier-family-dialog__header">
          <div>
            <span className="eyebrow">Modifier target required</span>
            <h2 id={titleId}>Choose a family for {perk.displayName}</h2>
          </div>
          <button
            className="icon-button"
            type="button"
            onClick={onCancel}
            aria-label="Cancel family selection"
          >
            <X size={20} />
          </button>
        </header>

        <div className="modifier-family-dialog__body">
          <p id={descriptionId}>
            This position touches more than one compatible ability family. Choose which one this
            modifier should affect.
          </p>
          <div className="modifier-family-options">
            {choices.flatMap((choice, choiceIndex) => {
              const record = index.byId.get(choice.familyId);
              if (!record) return [];
              return [
                <button
                  ref={choiceIndex === 0 ? firstChoiceRef : undefined}
                  type="button"
                  className="modifier-family-option"
                  key={choice.familyId}
                  onClick={() => onSelect(choice)}
                >
                  <RecordVisual record={record} />
                  <span>
                    <small>Attach to</small>
                    <strong>{record.displayName}</strong>
                    <span>{plainGameText(record.description) || "Compatible family"}</span>
                  </span>
                </button>,
              ];
            })}
          </div>
          <button
            type="button"
            className="button button--secondary modifier-family-dialog__cancel"
            onClick={onCancel}
          >
            Cancel placement
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

export function PerkWorkbench({
  index,
  kit,
  layout,
  build,
  dispatch,
  onChooseAbility,
  notify,
}: PerkWorkbenchProps) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<PerkFilter>("all");
  const [pendingPerkId, setPendingPerkId] = useState<string | null>(null);
  const [pendingRotation, setPendingRotation] = useState<Rotation>("Default");
  const [movingPerkId, setMovingPerkId] = useState<string | null>(null);
  const [draggingPerkId, setDraggingPerkId] = useState<string | null>(null);
  const [pointerPosition, setPointerPosition] = useState<{ x: number; y: number } | null>(null);
  const [gridMetrics, setGridMetrics] = useState<GridMetrics>(FALLBACK_GRID_METRICS);
  const [grabOffset, setGrabOffset] = useState<GrabOffset | null>(null);
  const [modifierTargetId, setModifierTargetId] = useState<string | null>(null);
  const [pendingFamilyAssignment, setPendingFamilyAssignment] =
    useState<PendingFamilyAssignment | null>(null);
  const [gridChipTooltip, setGridChipTooltip] = useState<GridChipTooltip | null>(null);
  const [blockedRotationPerkId, setBlockedRotationPerkId] = useState<string | null>(null);
  const blockedRotationTimerRef = useRef<number | undefined>(undefined);
  const hoveredGridChipRef = useRef<HoveredGridChip | null>(null);
  const focusedGridChipRef = useRef<HoveredGridChip | null>(null);
  const lastPointerPositionRef = useRef<{ x: number; y: number } | null>(null);
  const libraryRef = useRef<HTMLElement>(null);
  const perkListRef = useRef<HTMLDivElement>(null);
  const boardRef = useRef<HTMLDivElement>(null);
  const gridMetricsRef = useRef<GridMetrics>(FALLBACK_GRID_METRICS);
  const grabOffsetRef = useRef<GrabOffset | null>(null);
  const pendingFamilyFilterIdRef = useRef<string | null>(null);
  const suppressPickupClickRef = useRef(false);
  const filterBeforeCompatibilityRef = useRef<PerkFilter>("all");

  const updateGrabOffset = (offset: GrabOffset | null) => {
    grabOffsetRef.current = offset;
    setGrabOffset(offset);
  };

  const refreshGridMetrics = () => {
    const measured = measureGridMetrics(boardRef.current);
    gridMetricsRef.current = measured;
    setGridMetrics((current) => (
      current.cellWidth === measured.cellWidth &&
      current.cellHeight === measured.cellHeight &&
      current.columnGap === measured.columnGap &&
      current.rowGap === measured.rowGap
        ? current
        : measured
    ));
    return measured;
  };

  useEffect(() => {
    setPendingPerkId(null);
    setPendingRotation("Default");
    setMovingPerkId(null);
    setDraggingPerkId(null);
    setPointerPosition(null);
    updateGrabOffset(null);
    hoveredGridChipRef.current = null;
    focusedGridChipRef.current = null;
    setFilter(filterBeforeCompatibilityRef.current);
    setModifierTargetId(null);
    pendingFamilyFilterIdRef.current = null;
    setPendingFamilyAssignment(null);
    setGridChipTooltip(null);
    setBlockedRotationPerkId(null);
  }, [kit.id]);

  useEffect(() => () => window.clearTimeout(blockedRotationTimerRef.current), []);

  useEffect(() => {
    const refresh = () => refreshGridMetrics();
    refresh();
    window.addEventListener("resize", refresh, { passive: true });
    const observer = typeof ResizeObserver === "undefined"
      ? null
      : new ResizeObserver(refresh);
    if (boardRef.current) observer?.observe(boardRef.current);
    return () => {
      window.removeEventListener("resize", refresh);
      observer?.disconnect();
    };
  }, [layout.renderExtent.columns, layout.renderExtent.rows]);

  const kitPerkIds = useMemo(() => new Set(kit.selectablePerkIds), [kit.selectablePerkIds]);
  const placedIds = useMemo(() => new Set(build.perks.map((perk) => perk.perkId)), [build.perks]);
  const links = useMemo(() => validateGridLinks(index, build), [build, index]);
  const linkIssueIds = useMemo(
    () => new Set(links.map((issue) => issue.perkId)),
    [links],
  );
  const familyConnectors = useMemo(
    () => calculateFamilyConnectors(index, layout, build, linkIssueIds),
    [build, index, layout, linkIssueIds],
  );
  const activeTerminalIds = useMemo(() => {
    const ids = new Set(build.abilityIds.filter((id): id is string => id !== null));
    for (const placement of build.perks) {
      const perk = index.byId.get(placement.perkId);
      if (perk?.kind === "perk" && perk.perkType === "core") ids.add(perk.id);
    }
    return ids;
  }, [build.abilityIds, build.perks, index]);
  const compatibilityChipIds = useMemo(() => {
    const ids = new Set<string>();
    if (!modifierTargetId) return ids;
    ids.add(modifierTargetId);

    let added = true;
    while (added) {
      added = false;
      for (const placement of build.perks) {
        if (
          !ids.has(placement.perkId) &&
          !linkIssueIds.has(placement.perkId) &&
          placement.targetId &&
          ids.has(placement.targetId)
        ) {
          ids.add(placement.perkId);
          added = true;
        }
      }
    }
    return ids;
  }, [build.perks, linkIssueIds, modifierTargetId]);
  const unfulfilledPerkIds = useMemo(() => {
    const ids = new Set<string>();
    for (const perk of index.perks) {
      if (perk.perkType !== "modifier" || !perk.dependencies?.requiresConnectedCompatibleTarget) {
        continue;
      }
      if (placedIds.has(perk.id)) {
        if (linkIssueIds.has(perk.id)) ids.add(perk.id);
        continue;
      }
      const hasActiveTerminal = modifierCandidateIds(perk)
        .some((candidateId) => activeTerminalIds.has(candidateId));
      const hasResolvedModifier = modifierCandidateIds(perk).some((candidateId) => {
        const candidate = index.byId.get(candidateId);
        return candidate?.kind === "perk" && candidate.perkType === "modifier" &&
          !!placedModifierTerminalId(index, build, candidateId);
      });
      if (!hasActiveTerminal && !hasResolvedModifier) ids.add(perk.id);
    }
    return ids;
  }, [activeTerminalIds, build, index, linkIssueIds, placedIds]);
  const availablePerks = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    return index.perks
      .filter((perk) => {
        if (!kitPerkIds.has(perk.id)) return false;
        if (placedIds.has(perk.id)) return false;
        if (modifierTargetId) {
          if (perk.perkType !== "modifier" || !terminalCandidateIds(index, perk).has(modifierTargetId)) {
            return false;
          }
        } else if (filter !== "all" && perk.perkType !== filter) {
          return false;
        }
        if (!normalized) return true;
        return `${perk.displayName} ${plainGameText(perk.description)}`
          .toLocaleLowerCase()
          .includes(normalized);
      })
      .sort((left, right) =>
        Number(unfulfilledPerkIds.has(left.id)) - Number(unfulfilledPerkIds.has(right.id)),
      );
  }, [filter, index.perks, kitPerkIds, modifierTargetId, placedIds, query, unfulfilledPerkIds]);
  const showGridChipTooltip = (
    element: HTMLElement,
    chipKey: string,
    title: string,
    description: string,
  ) => {
    const bounds = element.getBoundingClientRect();
    const maxWidth = Math.min(320, Math.max(200, window.innerWidth - 24));
    const halfWidth = maxWidth / 2;
    const x = Math.min(
      window.innerWidth - halfWidth - 12,
      Math.max(halfWidth + 12, bounds.left + bounds.width / 2),
    );
    const placement = bounds.top > 190 ? "above" : "below";
    setGridChipTooltip({
      chipKey,
      title,
      description: plainGameText(description) || "No description available.",
      x,
      y: placement === "above" ? bounds.top - 10 : bounds.bottom + 10,
      placement,
    });
  };

  const hideGridChipTooltip = (chipKey?: string) => {
    setGridChipTooltip((current) => (
      !chipKey || current?.chipKey === chipKey ? null : current
    ));
  };

  const placeable = useMemo(() => new Set(layout.placeableCells.map(cellKey)), [layout]);
  const pendingPerk = pendingPerkId
    ? (index.byId.get(pendingPerkId) as PerkRecord | undefined)
    : undefined;
  const activeMovePerkId = movingPerkId ?? draggingPerkId;
  const movingPlacement = activeMovePerkId
    ? build.perks.find((placement) => placement.perkId === activeMovePerkId)
    : undefined;
  const movingPerk = movingPlacement
    ? (index.byId.get(movingPlacement.perkId) as PerkRecord | undefined)
    : undefined;
  const activePerk = pendingPerk ?? movingPerk;
  const activeRotation = pendingPerk ? pendingRotation : movingPlacement?.rotation;
  const cursorPerk = pendingPerk ?? (movingPerkId ? movingPerk : undefined);
  const cursorRotation = pendingPerk ? pendingRotation : movingPlacement?.rotation;
  const activeShape = activePerk && activeRotation
    ? rotateShape(activePerk.grid.shapes[0], activeRotation)
    : undefined;
  const activeGrabOffset = activeShape
    ? grabOffset ?? centeredGrabOffset(activeShape, gridMetrics)
    : null;
  const occupyingPerkByCell = new Map<string, PerkRecord>();
  const usedCellCount = build.perks.reduce((count, placement) => {
    const perk = index.byId.get(placement.perkId);
    if (perk?.kind !== "perk") return count;
    occupiedCells(perk, placement).forEach((cell) => occupyingPerkByCell.set(cellKey(cell), perk));
    return count + occupiedCells(perk, placement).length;
  }, 0);

  const legalFootprintCells = useMemo(() => {
    const cells = new Set<string>();
    if (!activePerk) return cells;
    for (const rotation of activePerk.grid.allowedRotations) {
      for (const placement of fittingPlacements(activePerk, rotation, layout)) {
        const result = validatePlacement(
          index,
          layout,
          build.perks,
          placement,
          activeMovePerkId ?? undefined,
        );
        if (!result.valid) continue;
        result.cells.forEach((cell) => cells.add(cellKey(cell)));
      }
    }
    return cells;
  }, [activeMovePerkId, activePerk, build.perks, index, layout]);

  const snappedPlacement = activePerk && activeRotation && activeGrabOffset && pointerPosition
    ? snappedPlacementAtPoint(
        index,
        layout,
        build,
        activePerk,
        activeRotation,
        activeMovePerkId ?? undefined,
        boardRef.current,
        gridMetrics,
        activeGrabOffset,
        pointerPosition.x,
        pointerPosition.y,
      )
    : undefined;

  const closeCompatibilityFilter = () => {
    setModifierTargetId(null);
    setFilter(filterBeforeCompatibilityRef.current);
    if (perkListRef.current) perkListRef.current.scrollTop = 0;
  };

  useEffect(() => {
    if (modifierTargetId && !activeTerminalIds.has(modifierTargetId)) {
      closeCompatibilityFilter();
    }
  }, [activeTerminalIds, modifierTargetId]);

  useEffect(() => {
    if (!movingPerkId || build.perks.some((placement) => placement.perkId === movingPerkId)) {
      return;
    }
    setMovingPerkId(null);
    setPointerPosition(null);
    updateGrabOffset(null);
  }, [build.perks, movingPerkId]);

  useEffect(() => {
    const followPointer = (event: PointerEvent) => {
      const point = { x: event.clientX, y: event.clientY };
      lastPointerPositionRef.current = point;
      if (cursorPerk) setPointerPosition(point);
    };
    if (!cursorPerk) setPointerPosition(null);
    window.addEventListener("pointermove", followPointer, { passive: true });
    return () => window.removeEventListener("pointermove", followPointer);
  }, [cursorPerk]);

  const choosePerk = (perk: PerkRecord, x: number, y: number) => {
    hideGridChipTooltip();
    const metrics = refreshGridMetrics();
    const placement = build.perks.find((candidate) => candidate.perkId === perk.id);
    const rotation = placement?.rotation ?? "Default";
    const shape = rotateShape(perk.grid.shapes[0], rotation);
    updateGrabOffset(centeredGrabOffset(shape, metrics));
    if (placedIds.has(perk.id)) {
      pendingFamilyFilterIdRef.current = null;
      setPendingPerkId(null);
      setPendingRotation("Default");
      setMovingPerkId(perk.id);
      setDraggingPerkId(null);
      setPointerPosition({ x, y });
      notify(`${perk.displayName} picked up. Choose a highlighted grid cell.`);
      return;
    }
    pendingFamilyFilterIdRef.current = modifierTargetId;
    setPendingPerkId(perk.id);
    setPendingRotation("Default");
    setMovingPerkId(null);
    setDraggingPerkId(null);
    setPointerPosition({ x, y });
    notify(`${perk.displayName} armed. Choose a highlighted grid cell.`);
  };

  const clearHeldState = () => {
    setPendingPerkId(null);
    setPendingRotation("Default");
    setMovingPerkId(null);
    setDraggingPerkId(null);
    setPointerPosition(null);
    updateGrabOffset(null);
    pendingFamilyFilterIdRef.current = null;
  };

  const discardHeldPerk = () => {
    const heldMoveId = movingPerkId ?? draggingPerkId;
    const heldRecord = heldMoveId ? index.byId.get(heldMoveId) : pendingPerk;
    if (heldMoveId) dispatch({ type: "remove-perk", perkId: heldMoveId });
    clearHeldState();
    hoveredGridChipRef.current = null;
    focusedGridChipRef.current = null;
    notify(`${heldRecord?.displayName ?? "Perk"} removed.`);
  };

  const dispatchPlacement = (
    kind: FamilyAssignmentKind,
    placement: PlacedPerk,
    successMessage: string,
  ) => {
    if (kind === "place") {
      dispatch({ type: "place-perk", placement });
    } else if (kind === "move") {
      dispatch({
        type: "move-perk",
        perkId: placement.perkId,
        row: placement.row,
        column: placement.column,
        targetId: placement.targetId,
        targetFamilyId: placement.targetFamilyId,
      });
    } else {
      dispatch({
        type: "rotate-perk",
        perkId: placement.perkId,
        rotation: placement.rotation,
        targetId: placement.targetId,
        targetFamilyId: placement.targetFamilyId,
      });
    }

    if (kind !== "rotate") clearHeldState();
    hoveredGridChipRef.current = { kind: "perk", perkId: placement.perkId };
    notify(successMessage);
  };

  const stagePlacement = (
    kind: FamilyAssignmentKind,
    candidate: PlacedPerk,
    successMessage: string,
  ): boolean => {
    const perk = index.byId.get(candidate.perkId);
    if (perk?.kind !== "perk" || perk.perkType !== "modifier") {
      dispatchPlacement(kind, candidate, successMessage);
      return true;
    }

    const hypotheticalPerks = kind === "place"
      ? [...build.perks, candidate]
      : build.perks.map((placement) => (
          placement.perkId === candidate.perkId ? candidate : placement
        ));
    const hypothetical = { ...build, perks: hypotheticalPerks };
    const familySlotOrder = new Map(
      kit.abilitySlots.map((slot) => {
        const roleOrder = slot.role === "primary" ? 0
          : slot.role === "secondary" ? 1
            : slot.role === "passive" ? 2
              : 3;
        return [build.abilityIds[slot.index], roleOrder * 100 + slot.index] as const;
      }).filter((entry): entry is readonly [string, number] => entry[0] !== null),
    );
    const choices = availableModifierFamilyChoices(index, hypothetical, candidate.perkId)
      .sort((left, right) => (
        (familySlotOrder.get(left.familyId) ?? Number.MAX_SAFE_INTEGER) -
        (familySlotOrder.get(right.familyId) ?? Number.MAX_SAFE_INTEGER)
      ));

    const prepareForFamily = (
      familyId: string,
      choice?: ModifierFamilyChoice,
    ): PlacedPerk => {
      const { targetId: _targetId, ...withoutTarget } = candidate;
      return {
        ...withoutTarget,
        targetFamilyId: familyId,
        ...(choice ? { targetId: choice.targetId } : {}),
      };
    };

    const placementFilterId = kind === "place" ? pendingFamilyFilterIdRef.current : null;
    if (placementFilterId) {
      const filteredChoice = choices.find((choice) => choice.familyId === placementFilterId);
      dispatchPlacement(
        kind,
        prepareForFamily(placementFilterId, filteredChoice),
        successMessage,
      );
      return true;
    }

    if (candidate.targetFamilyId) {
      const existingChoice = choices.find(
        (choice) => choice.familyId === candidate.targetFamilyId,
      );
      dispatchPlacement(
        kind,
        prepareForFamily(candidate.targetFamilyId, existingChoice),
        successMessage,
      );
      return true;
    }

    if (choices.length === 1) {
      const [choice] = choices;
      dispatchPlacement(kind, prepareForFamily(choice.familyId, choice), successMessage);
      return true;
    }

    if (choices.length > 1) {
      clearHeldState();
      hideGridChipTooltip();
      setPendingFamilyAssignment({ kind, placement: candidate, choices, successMessage });
      return true;
    }

    const {
      targetId: _targetId,
      targetFamilyId: _targetFamilyId,
      ...withoutTarget
    } = candidate;
    dispatchPlacement(kind, withoutTarget, successMessage);
    return true;
  };

  const tryPlace = (perkId: string, row: number, column: number, rotation: Rotation): boolean => {
    const perk = index.byId.get(perkId);
    if (!perk || perk.kind !== "perk" || !kitPerkIds.has(perkId)) {
      notify("That perk is not available to this kit.");
      return false;
    }
    const candidate: PlacedPerk = { perkId, row, column, rotation };
    const result = validatePlacement(index, layout, build.perks, candidate);
    if (!result.valid) {
      notify(result.reason ?? "That perk cannot be placed there.");
      return false;
    }
    return stagePlacement(
      "place",
      candidate,
      `${perk.displayName} placed at ${gridCellLabel({ row, column })}.`,
    );
  };

  const movePerk = (perkId: string, row: number, column: number): boolean => {
    const current = build.perks.find((placement) => placement.perkId === perkId);
    const perk = index.byId.get(perkId);
    if (!current || !perk || perk.kind !== "perk") return false;
    const candidate = { ...current, row, column };
    const result = validatePlacement(index, layout, build.perks, candidate, perkId);
    if (!result.valid) {
      notify(result.reason ?? "That perk cannot be moved there.");
      return false;
    }
    return stagePlacement(
      "move",
      candidate,
      `${perk.displayName} moved to ${gridCellLabel({ row, column })}.`,
    );
  };

  const commitSnappedPlacement = (snapped: SnappedPlacement | undefined) => {
    if (!snapped || !activePerk) {
      notify("That perk cannot fit on this grid.");
      return;
    }
    if (snapped.overlaps) {
      notify("That placement overlaps another brick.");
      return;
    }
    const { row, column } = snapped.placement;
    if (movingPerk) movePerk(movingPerk.id, row, column);
    else if (pendingPerk) tryPlace(pendingPerk.id, row, column, snapped.placement.rotation);
  };

  const snapHeldAtCell = (cell: GridCell): SnappedPlacement | undefined => {
    if (!activePerk || !activeRotation || !activeGrabOffset) return undefined;
    return snappedPlacementAtCell(
      index,
      layout,
      build,
      activePerk,
      activeRotation,
      activeMovePerkId ?? undefined,
      cell,
      activeGrabOffset,
      gridMetrics,
    );
  };

  const snapHeldAtPoint = (clientX: number, clientY: number): SnappedPlacement | undefined => {
    if (!activePerk || !activeRotation || !activeGrabOffset) return undefined;
    return snappedPlacementAtPoint(
      index,
      layout,
      build,
      activePerk,
      activeRotation,
      activeMovePerkId ?? undefined,
      boardRef.current,
      gridMetricsRef.current,
      activeGrabOffset,
      clientX,
      clientY,
    );
  };

  const onBoardDrop = (event: DragEvent) => {
    event.preventDefault();
    event.stopPropagation();
    lastPointerPositionRef.current = { x: event.clientX, y: event.clientY };
    const movingId = event.dataTransfer.getData("application/x-afe2-placed-perk");
    if (movingId) {
      const placement = build.perks.find((candidate) => candidate.perkId === movingId);
      const perk = index.byId.get(movingId);
      if (!placement || perk?.kind !== "perk") return;
      const offset = grabOffsetRef.current ?? centeredGrabOffset(
        rotateShape(perk.grid.shapes[0], placement.rotation),
        gridMetricsRef.current,
      );
      const fallbackCell = gridCellAtPoint(boardRef.current, event.clientX, event.clientY) ??
        (() => {
          const element = event.target instanceof Element
            ? event.target.closest<HTMLElement>(".perk-cell")
            : null;
          const row = Number(element?.dataset.row);
          const column = Number(element?.dataset.column);
          return Number.isInteger(row) && Number.isInteger(column) ? { row, column } : undefined;
        })();
      const snapped = snappedPlacementAtPoint(
        index,
        layout,
        build,
        perk,
        placement.rotation,
        movingId,
        boardRef.current,
        gridMetricsRef.current,
        offset,
        event.clientX,
        event.clientY,
      ) ?? (fallbackCell
        ? snappedPlacementAtCell(
            index,
            layout,
            build,
            perk,
            placement.rotation,
            movingId,
            fallbackCell,
            offset,
            gridMetricsRef.current,
          )
        : undefined);
      if (snapped?.overlaps) {
        notify("That placement overlaps another brick.");
        return;
      }
      if (snapped) movePerk(movingId, snapped.placement.row, snapped.placement.column);
      return;
    }
    const perkId = event.dataTransfer.getData("application/x-afe2-perk");
    if (!perkId) return;
    const perk = index.byId.get(perkId);
    const requestedRotation = event.dataTransfer.getData("application/x-afe2-rotation") as Rotation;
    const rotation = perk?.kind === "perk" && perk.grid.allowedRotations.includes(requestedRotation)
      ? requestedRotation
      : "Default";
    if (perk?.kind !== "perk") return;
    const offset = grabOffsetRef.current ?? centeredGrabOffset(
      rotateShape(perk.grid.shapes[0], rotation),
      gridMetricsRef.current,
    );
    const fallbackCell = gridCellAtPoint(boardRef.current, event.clientX, event.clientY) ??
      (() => {
        const element = event.target instanceof Element
          ? event.target.closest<HTMLElement>(".perk-cell")
          : null;
        const row = Number(element?.dataset.row);
        const column = Number(element?.dataset.column);
        return Number.isInteger(row) && Number.isInteger(column) ? { row, column } : undefined;
      })();
    const snapped = snappedPlacementAtPoint(
      index,
      layout,
      build,
      perk,
      rotation,
      undefined,
      boardRef.current,
      gridMetricsRef.current,
      offset,
      event.clientX,
      event.clientY,
    ) ?? (fallbackCell
      ? snappedPlacementAtCell(
          index,
          layout,
          build,
          perk,
          rotation,
          undefined,
          fallbackCell,
          offset,
          gridMetricsRef.current,
        )
      : undefined);
    if (snapped?.overlaps) {
      notify("That placement overlaps another brick.");
      return;
    }
    if (snapped) tryPlace(perkId, snapped.placement.row, snapped.placement.column, rotation);
  };

  useEffect(() => {
    if (!cursorPerk) return;
    const dropOutsideGrid = (event: MouseEvent) => {
      if (pendingFamilyAssignment) return;
      const board = boardRef.current;
      if (!board || (event.target instanceof Node && board.contains(event.target))) return;
      // Controls that own the held brick themselves: rotating it, cancelling it,
      // picking up a different one, or resolving its family in a dialog. Clicking
      // one of those is not the same as putting the brick down.
      if (
        event.target instanceof Element &&
        event.target.closest(
          ".perk-list-item, .board-actions, .perk-library__actions, [role='dialog']",
        )
      ) {
        return;
      }
      // Releasing a brick anywhere off the grid throws it away, mirroring the
      // native drag-out gesture. The click is spent on the drop and nothing else.
      event.preventDefault();
      event.stopImmediatePropagation();
      discardHeldPerk();
    };
    window.addEventListener("click", dropOutsideGrid, true);
    return () => window.removeEventListener("click", dropOutsideGrid, true);
  });

  const flagBlockedRotation = (perkId: string) => {
    window.clearTimeout(blockedRotationTimerRef.current);
    setBlockedRotationPerkId(perkId);
    blockedRotationTimerRef.current = window.setTimeout(
      () => setBlockedRotationPerkId(null),
      450,
    );
  };

  const rotatePlaced = (perkId: string) => {
    const placement = build.perks.find((candidate) => candidate.perkId === perkId);
    const perk = index.byId.get(perkId);
    if (!placement || !perk || perk.kind !== "perk") return;
    const rotation = nextRotation(perk, placement.rotation);
    if (rotation === placement.rotation) return;
    const candidate = { ...placement, rotation };
    const result = validatePlacement(
      index,
      layout,
      build.perks,
      candidate,
      placement.perkId,
    );
    if (!result.valid) {
      // Messages are announced, not shown, so mark the chip itself as refused.
      flagBlockedRotation(perkId);
      notify(result.reason ?? "There is not enough room to rotate this perk.");
      return;
    }
    if (movingPerkId === perkId || draggingPerkId === perkId) {
      const fromShape = rotateShape(perk.grid.shapes[0], placement.rotation);
      const toShape = rotateShape(perk.grid.shapes[0], rotation);
      const currentOffset = grabOffsetRef.current ?? centeredGrabOffset(fromShape, gridMetricsRef.current);
      updateGrabOffset(rotateGrabOffset(
        currentOffset,
        fromShape,
        toShape,
        placement.rotation,
        rotation,
        gridMetricsRef.current,
      ));
    }
    stagePlacement(
      "rotate",
      candidate,
      `${perk.displayName} rotated to ${footprintLabel(perk, rotation)}.`,
    );
  };

  const rotatePending = () => {
    if (!pendingPerk) return;
    const rotation = nextRotation(pendingPerk, pendingRotation);
    if (rotation === pendingRotation) return;
    const fromShape = rotateShape(pendingPerk.grid.shapes[0], pendingRotation);
    const toShape = rotateShape(pendingPerk.grid.shapes[0], rotation);
    const currentOffset = grabOffsetRef.current ?? centeredGrabOffset(fromShape, gridMetricsRef.current);
    updateGrabOffset(rotateGrabOffset(
      currentOffset,
      fromShape,
      toShape,
      pendingRotation,
      rotation,
      gridMetricsRef.current,
    ));
    setPendingRotation(rotation);
  };

  const openCompatibleModifiers = (hovered: HoveredGridChip) => {
    hideGridChipTooltip();
    let targetId: string | undefined;
    if (hovered.kind === "ability") {
      targetId = build.abilityIds[hovered.slotIndex] ?? undefined;
    } else {
      const record = index.byId.get(hovered.perkId);
      if (record?.kind === "perk" && record.perkType === "core") targetId = record.id;
      if (record?.kind === "perk" && record.perkType === "modifier") {
        targetId = placedModifierTerminalId(index, build, record.id);
      }
    }
    if (!targetId) {
      notify("That modifier does not have a resolved parent yet.");
      return;
    }
    filterBeforeCompatibilityRef.current = filter;
    setModifierTargetId(targetId);
    setFilter("modifier");
    setQuery("");
    setPendingPerkId(null);
    setPendingRotation("Default");
    setMovingPerkId(null);
    setPointerPosition(null);
    updateGrabOffset(null);
    window.requestAnimationFrame(() => {
      if (perkListRef.current) perkListRef.current.scrollTop = 0;
      libraryRef.current?.scrollIntoView({ block: "nearest" });
    });
  };

  const removeHoveredChip = (hovered: HoveredGridChip) => {
    hideGridChipTooltip();
    if (hovered.kind === "ability") {
      const abilityId = build.abilityIds[hovered.slotIndex];
      const record = abilityId ? index.byId.get(abilityId) : undefined;
      dispatch({ type: "reset-ability", slotIndex: hovered.slotIndex });
      notify(`${record?.displayName ?? "Ability slot"} reset.`);
      return;
    }
    const perk = index.byId.get(hovered.perkId);
    dispatch({ type: "remove-perk", perkId: hovered.perkId });
    if (movingPerkId === hovered.perkId) setMovingPerkId(null);
    if (draggingPerkId === hovered.perkId) setDraggingPerkId(null);
    setPointerPosition(null);
    updateGrabOffset(null);
    hoveredGridChipRef.current = null;
    focusedGridChipRef.current = null;
    notify(`${perk?.displayName ?? "Perk"} removed.`);
  };

  const choosePendingFamily = (choice: ModifierFamilyChoice) => {
    if (!pendingFamilyAssignment) return;
    const {
      targetId: _targetId,
      targetFamilyId: _targetFamilyId,
      ...withoutTarget
    } = pendingFamilyAssignment.placement;
    const placement = {
      ...withoutTarget,
      targetId: choice.targetId,
      targetFamilyId: choice.familyId,
    };
    const { kind, successMessage } = pendingFamilyAssignment;
    setPendingFamilyAssignment(null);
    dispatchPlacement(kind, placement, successMessage);
  };

  const cancelPendingFamily = () => {
    if (!pendingFamilyAssignment) return;
    const message = pendingFamilyAssignment.kind === "rotate"
      ? "Rotation cancelled."
      : "Placement cancelled.";
    setPendingFamilyAssignment(null);
    notify(message);
  };

  const gridChipAtPointer = (): HoveredGridChip | null | undefined => {
    const point = lastPointerPositionRef.current;
    const board = boardRef.current;
    if (!point || !board || typeof document.elementFromPoint !== "function") return undefined;
    const element = document.elementFromPoint(point.x, point.y);
    if (!element || !board.contains(element)) return null;

    const placedPerk = element.closest<HTMLElement>(".placed-perk[data-perk-id]");
    if (placedPerk && board.contains(placedPerk) && placedPerk.dataset.perkId) {
      return { kind: "perk", perkId: placedPerk.dataset.perkId };
    }

    const ability = element.closest<HTMLElement>(".ability-anchor[data-ability-slot-index]");
    const slotIndex = Number(ability?.dataset.abilitySlotIndex);
    if (ability && board.contains(ability) && Number.isInteger(slotIndex)) {
      return { kind: "ability", slotIndex };
    }
    return null;
  };

  const shortcutGridChip = (): HoveredGridChip | null => {
    const pointedChip = gridChipAtPointer();
    if (pointedChip === undefined) {
      return hoveredGridChipRef.current ?? focusedGridChipRef.current;
    }
    return pointedChip ?? focusedGridChipRef.current;
  };

  useEffect(() => {
    const onShortcut = (event: KeyboardEvent) => {
      if (pendingFamilyAssignment) return;
      if (event.repeat || event.ctrlKey || event.metaKey || event.altKey || isEditableTarget(event.target)) {
        return;
      }
      const key = event.key.toLocaleLowerCase();
      if (key === "escape") {
        if (pendingPerk || movingPerk || draggingPerkId) {
          event.preventDefault();
          clearHeldState();
          notify("Placement cancelled.");
          return;
        }
        if (modifierTargetId) {
          event.preventDefault();
          closeCompatibilityFilter();
        }
        return;
      }
      if (key === "d") {
        const activeGridChip = shortcutGridChip();
        if (movingPerk) {
          event.preventDefault();
          rotatePlaced(movingPerk.id);
        } else if (pendingPerk) {
          event.preventDefault();
          rotatePending();
        } else if (activeGridChip?.kind === "perk") {
          event.preventDefault();
          rotatePlaced(activeGridChip.perkId);
        }
        return;
      }
      const activeGridChip = shortcutGridChip();
      if (key === "r") {
        if (modifierTargetId) {
          event.preventDefault();
          closeCompatibilityFilter();
        } else if (activeGridChip) {
          event.preventDefault();
          openCompatibleModifiers(activeGridChip);
        }
        return;
      }
      if (key === "f") {
        if (pendingPerk || movingPerk || draggingPerkId) {
          event.preventDefault();
          discardHeldPerk();
        } else if (activeGridChip) {
          event.preventDefault();
          removeHoveredChip(activeGridChip);
        }
      }
    };
    window.addEventListener("keydown", onShortcut);
    return () => window.removeEventListener("keydown", onShortcut);
  });

  const renderCells = [];
  for (let row = 0; row < layout.renderExtent.rows; row += 1) {
    for (let column = 0; column < layout.renderExtent.columns; column += 1) {
      const cell = { row, column };
      const isPlaceable = placeable.has(cellKey(cell));
      const occupyingPerk = occupyingPerkByCell.get(cellKey(cell));
      const isLegalFootprint = !!activePerk && legalFootprintCells.has(cellKey(cell));
      renderCells.push(
        !isPlaceable ? (
          <span
            className="perk-cell perk-cell--blocked"
            data-row={row}
            data-column={column}
            style={{ gridRow: row + 1, gridColumn: column + 1 }}
            key={cellKey(cell)}
            aria-hidden="true"
          />
        ) : isLegalFootprint ? (
          <button
            type="button"
            className="perk-cell is-legal-footprint"
            data-row={row}
            data-column={column}
            style={{ gridRow: row + 1, gridColumn: column + 1 }}
            key={cellKey(cell)}
            aria-label={`${gridCellLabel(cell)}, possible footprint for ${activePerk.displayName}`}
          >
            <span>{gridCellLabel(cell)}</span>
          </button>
        ) : (
          <span
            className={`perk-cell ${occupyingPerk ? "is-occupied" : ""}`}
            data-row={row}
            data-column={column}
            style={{ gridRow: row + 1, gridColumn: column + 1 }}
            key={cellKey(cell)}
            aria-hidden="true"
          />
        ),
      );
    }
  }

  const cursorShape = cursorPerk && cursorRotation
    ? rotateShape(cursorPerk.grid.shapes[0], cursorRotation)
    : undefined;
  const cursorDimensions = cursorShape
    ? footprintDimensions(cursorShape, gridMetrics)
    : { width: 0, height: 0 };
  const cursorGrabOffset = cursorShape
    ? grabOffset ?? centeredGrabOffset(cursorShape, gridMetrics)
    : { x: 0, y: 0 };
  const cursorPreviewLeft = snappedPlacement?.left ??
    (pointerPosition ? pointerPosition.x - cursorGrabOffset.x : 0);
  const cursorPreviewTop = snappedPlacement?.top ??
    (pointerPosition ? pointerPosition.y - cursorGrabOffset.y : 0);
  const cursorSnapState = !snappedPlacement
    ? "free"
    : snappedPlacement.overlaps
      ? "overlap"
      : snappedPlacement.familyLinked
        ? "valid"
        : "unlinked";

  return (
    <section className="section" id="perks" aria-labelledby="perks-heading">
      <div className="section-heading">
        <div>
          <span className="section-index">02</span>
          <div>
            <span className="eyebrow">Configure your board</span>
            <h2 id="perks-heading">Perk grid</h2>
          </div>
        </div>
        <p>Pick up or drag a perk, then place it in one of the 42 open cells.</p>
      </div>

      <div className="perk-workbench">
        <div className="board-panel">
          <div className="board-toolbar">
            <div className="board-status">
              <span className="status-dot" />
              <span><strong>{usedCellCount}</strong> / {layout.placeableCellCount} cells</span>
              <span className="board-status__divider" />
              <span
                className={links.length ? "status-warning" : "status-ok"}
                role="status"
                aria-live="polite"
                aria-atomic="true"
                title={links.length
                  ? `${links[0].message} Diagonal contact does not count.`
                  : "All perk links are valid."}
              >
                {links.length ? <><Unlink size={14} /> {links.length} unlinked</> : <><Link2 size={14} /> links valid</>}
                {!!links.length && (
                  <span className="sr-only">
                    {links[0].message} Diagonal contact does not count.
                  </span>
                )}
              </span>
            </div>
            {activePerk && (
              <div className="placement-prompt is-active" aria-live="polite">
                <MousePointer2 size={18} />
                {pendingPerk ? (
                  <span>
                    Placing <strong>{pendingPerk.displayName}</strong> · {footprintLabel(pendingPerk, pendingRotation)}
                  </span>
                ) : movingPerk ? (
                  <span>
                    Moving <strong>{movingPerk.displayName}</strong> · choose a highlighted cell
                  </span>
                ) : null}
              </div>
            )}
            <div className="board-actions">
              {pendingPerk && canRotate(pendingPerk) && (
                <button
                  type="button"
                  className="button button--tool"
                  onClick={rotatePending}
                >
                  <RotateCw size={15} /> Rotate
                  <kbd>D</kbd>
                </button>
              )}
              <button
                type="button"
                className="button button--tool"
                onClick={() => {
                  dispatch({ type: "clear-perks" });
                  setPendingPerkId(null);
                  setMovingPerkId(null);
                  setDraggingPerkId(null);
                  setPointerPosition(null);
                  updateGrabOffset(null);
                  hoveredGridChipRef.current = null;
                  focusedGridChipRef.current = null;
                  closeCompatibilityFilter();
                  hideGridChipTooltip();
                  notify("Perk grid and abilities reset.");
                }}
                title="Remove every placed perk and return all three ability slots to this kit's defaults."
              >
                Reset board
              </button>
            </div>
          </div>

          <div className="board-scroll">
            <div
              className="perk-board"
              ref={boardRef}
              role="group"
              aria-label={`${kit.displayName} perk grid`}
              onPointerMoveCapture={(event) => {
                if (cursorPerk || !(event.target instanceof Element)) return;
                const placed = event.target.closest<HTMLElement>(".placed-perk");
                const perkId = placed?.dataset.perkId;
                if (perkId) {
                  hoveredGridChipRef.current = { kind: "perk", perkId };
                } else if (!event.target.closest(".ability-anchor")) {
                  hoveredGridChipRef.current = null;
                }
              }}
              onClickCapture={(event) => {
                if (!cursorPerk) return;
                lastPointerPositionRef.current = { x: event.clientX, y: event.clientY };
                event.preventDefault();
                event.stopPropagation();
                const targetCell = event.target instanceof Element
                  ? event.target.closest<HTMLElement>(".perk-cell")
                  : null;
                const row = Number(targetCell?.dataset.row);
                const column = Number(targetCell?.dataset.column);
                const fallbackCell = Number.isInteger(row) && Number.isInteger(column)
                  ? { row, column }
                  : undefined;
                commitSnappedPlacement(
                  snapHeldAtPoint(event.clientX, event.clientY) ??
                    (fallbackCell ? snapHeldAtCell(fallbackCell) : undefined),
                );
              }}
              onDragOver={(event) => event.preventDefault()}
              onDrop={onBoardDrop}
              style={
                {
                  "--board-columns": layout.renderExtent.columns,
                  "--board-rows": layout.renderExtent.rows,
                } as CSSProperties
              }
            >
              {renderCells}

              {familyConnectors.map((connector) => {
                const connectorPath = index.catalogue.perkGrid.familyConnector?.path;
                return (
                  <span
                    className={`family-connector family-connector--${connector.orientation} ${connectorPath ? "has-texture" : ""}`}
                    data-family-id={connector.familyId}
                    data-from-node={connector.fromNodeId}
                    data-orientation={connector.orientation}
                    data-to-node={connector.toNodeId}
                    key={connector.key}
                    style={{
                      gridRow: connector.row + 1,
                      gridColumn: connector.column + 1,
                      ...(connectorPath
                        ? {
                            "--family-connector-image": `url("${catalogueAssetUrl(connectorPath)}")`,
                          }
                        : {}),
                    } as CSSProperties}
                    aria-hidden="true"
                  />
                );
              })}

              {layout.anchors.map((anchor) => {
                const slot = kit.abilitySlots.find((candidate) => candidate.role === anchor.role);
                const abilityId = slot ? build.abilityIds[slot.index] : null;
                const record = abilityId ? index.byId.get(abilityId) : undefined;
                const rowSpan = Math.max(...anchor.cells.map((cell) => cell.row)) - anchor.row + 1;
                const columnSpan = Math.max(...anchor.cells.map((cell) => cell.column)) - anchor.column + 1;
                const chipKey = `ability:${slot?.index ?? anchor.role}`;
                const isCompatibilityContext = !!abilityId && compatibilityChipIds.has(abilityId);
                const style = {
                  ...chipBodyStyle(
                    anchor.rendering?.chipBody?.path,
                    abilityChipColor(record, anchor.role),
                  ),
                  gridRow: `${anchor.row + 1} / span ${rowSpan}`,
                  gridColumn: `${anchor.column + 1} / span ${columnSpan}`,
                } as CSSProperties;
                if (!slot) {
                  return (
                    <span
                      className={`ability-anchor ability-anchor--${anchor.role} is-unavailable`}
                      key={anchor.role}
                      style={style}
                      aria-label={`${anchor.role} ability unavailable`}
                    >
                      <span className="ability-anchor__empty-mark" aria-hidden="true">∅</span>
                    </span>
                  );
                }
                return (
                  <button
                    type="button"
                    className={`ability-anchor ability-anchor--${anchor.role} ${isCompatibilityContext ? "is-compatibility-context" : ""}`}
                    key={anchor.role}
                    style={style}
                    data-ability-slot-index={slot.index}
                    onClick={() => {
                      hideGridChipTooltip(chipKey);
                      onChooseAbility(slot);
                    }}
                    onMouseEnter={(event) => {
                      hoveredGridChipRef.current = {
                        kind: "ability",
                        slotIndex: slot.index,
                      };
                      showGridChipTooltip(
                        event.currentTarget,
                        chipKey,
                        record?.displayName ?? `Empty ${anchor.role} ability`,
                        record?.description ?? `Choose a ${anchor.role} ability for this slot.`,
                      );
                    }}
                    onMouseLeave={() => {
                      hoveredGridChipRef.current = null;
                      hideGridChipTooltip(chipKey);
                    }}
                    onFocus={(event) => {
                      focusedGridChipRef.current = { kind: "ability", slotIndex: slot.index };
                      showGridChipTooltip(
                        event.currentTarget,
                        chipKey,
                        record?.displayName ?? `Empty ${anchor.role} ability`,
                        record?.description ?? `Choose a ${anchor.role} ability for this slot.`,
                      );
                    }}
                    onBlur={() => {
                      focusedGridChipRef.current = null;
                      hideGridChipTooltip(chipKey);
                    }}
                    aria-keyshortcuts="R F"
                    aria-label={`${anchor.role} ability: ${record?.displayName ?? "empty"}`}
                    aria-describedby={gridChipTooltip?.chipKey === chipKey ? "grid-chip-tooltip" : undefined}
                  >
                    {record
                      ? <RecordVisual record={record} />
                      : <span className="ability-anchor__empty-mark" aria-hidden="true">∅</span>}
                  </button>
                );
              })}

              {build.perks.map((placement) => {
                const perk = index.byId.get(placement.perkId);
                if (!perk || perk.kind !== "perk") return null;
                const shape = rotateShape(perk.grid.shapes[0], placement.rotation);
                const hasIssue = linkIssueIds.has(perk.id);
                const isCompatibilityContext = compatibilityChipIds.has(perk.id);
                const isMoving = movingPerkId === perk.id;
                const isDragging = draggingPerkId === perk.id;
                const bodyPath = chipBodyPath(perk, placement.rotation);
                const chipKey = `perk:${perk.id}`;
                // Connectors show that a chip is wired to something, not which
                // ability it feeds, so name the family the run terminates at.
                const family = placement.targetFamilyId
                  ? index.byId.get(placement.targetFamilyId)
                  : undefined;
                const attachment = !hasIssue && family && family.id !== perk.id
                  ? `Attached to ${family.displayName}.`
                  : "";
                const chipDescription = [
                  plainGameText(perk.description) || "No description available.",
                  attachment,
                ].filter(Boolean).join("\n");
                return (
                  <button
                    type="button"
                    className={`placed-perk placed-perk--${perk.perkType} ${hasIssue ? "has-issue" : ""} ${isCompatibilityContext ? "is-compatibility-context" : ""} ${isMoving ? "is-moving" : ""} ${isDragging ? "is-dragging" : ""}`}
                    style={{
                      ...chipBodyStyle(bodyPath, perkChipColor(perk, index.kits.length)),
                      gridRow: `${placement.row + 1} / span ${shape.height}`,
                      gridColumn: `${placement.column + 1} / span ${shape.width}`,
                    } as CSSProperties}
                    draggable={!isMoving}
                    aria-keyshortcuts="D R F"
                    data-perk-id={perk.id}
                    data-link-status={hasIssue ? "unlinked" : "linked"}
                    data-rotation-blocked={blockedRotationPerkId === perk.id ? "true" : undefined}
                    onDragStart={(event) => {
                      hideGridChipTooltip(chipKey);
                      pendingFamilyFilterIdRef.current = null;
                      suppressPickupClickRef.current = true;
                      const metrics = refreshGridMetrics();
                      const offset = grabOffsetFromBounds(
                        event.currentTarget.getBoundingClientRect(),
                        event.clientX,
                        event.clientY,
                        shape,
                        metrics,
                      );
                      updateGrabOffset(offset);
                      event.dataTransfer.setData("application/x-afe2-placed-perk", perk.id);
                      event.dataTransfer.effectAllowed = "move";
                      event.dataTransfer.setDragImage?.(event.currentTarget, offset.x, offset.y);
                      setDraggingPerkId(perk.id);
                    }}
                    onDragEnd={(event) => {
                      const bounds = gridBounds(boardRef.current, layout, gridMetricsRef.current);
                      const margin = Math.max(
                        28,
                        Math.min(
                          56,
                          Math.max(
                            gridMetricsRef.current.cellWidth,
                            gridMetricsRef.current.cellHeight,
                          ),
                        ),
                      );
                      if (
                        bounds &&
                        pointJustOutsideBounds(bounds, event.clientX, event.clientY, margin)
                      ) {
                        dispatch({ type: "remove-perk", perkId: perk.id });
                        notify(`${perk.displayName} removed.`);
                      }
                      setDraggingPerkId(null);
                      updateGrabOffset(null);
                      pendingFamilyFilterIdRef.current = null;
                      window.requestAnimationFrame(() => {
                        suppressPickupClickRef.current = false;
                      });
                    }}
                    onMouseEnter={(event) => {
                      hoveredGridChipRef.current = { kind: "perk", perkId: perk.id };
                      showGridChipTooltip(
                        event.currentTarget,
                        chipKey,
                        perk.displayName,
                        chipDescription,
                      );
                    }}
                    onMouseLeave={() => {
                      hoveredGridChipRef.current = null;
                      hideGridChipTooltip(chipKey);
                    }}
                    onFocus={(event) => {
                      focusedGridChipRef.current = { kind: "perk", perkId: perk.id };
                      showGridChipTooltip(
                        event.currentTarget,
                        chipKey,
                        perk.displayName,
                        chipDescription,
                      );
                    }}
                    onBlur={() => {
                      focusedGridChipRef.current = null;
                      hideGridChipTooltip(chipKey);
                    }}
                    onClick={(event) => {
                      if (suppressPickupClickRef.current) return;
                      hideGridChipTooltip(chipKey);
                      const metrics = refreshGridMetrics();
                      updateGrabOffset(grabOffsetFromBounds(
                        event.currentTarget.getBoundingClientRect(),
                        event.clientX,
                        event.clientY,
                        shape,
                        metrics,
                      ));
                      setPendingPerkId(null);
                      setPendingRotation("Default");
                      pendingFamilyFilterIdRef.current = null;
                      setMovingPerkId(perk.id);
                      setDraggingPerkId(null);
                      setPointerPosition({ x: event.clientX, y: event.clientY });
                      notify(`${perk.displayName} picked up. Choose a highlighted grid cell.`);
                    }}
                    key={perk.id}
                    aria-label={`${perk.displayName}, ${footprintLabel(perk, placement.rotation)}, at ${gridCellLabel(placement)}${hasIssue ? ", connection required" : ""}${attachment ? `, attached to ${family?.displayName}` : ""}`}
                    aria-describedby={gridChipTooltip?.chipKey === chipKey ? "grid-chip-tooltip" : undefined}
                  >
                    <RecordVisual record={perk} />
                    {hasIssue && <Unlink className="placed-perk__warning" size={15} />}
                  </button>
                );
              })}
            </div>
          </div>

        </div>
        <aside className="perk-library" aria-label="Perk library" ref={libraryRef}>
          <div className="perk-library__search-row">
            <label className="search-field search-field--compact">
              <Search size={16} aria-hidden="true" />
              <span className="sr-only">Search {availablePerks.length} perks</span>
              <input
                type="search"
                placeholder={`Search ${availablePerks.length} perks`}
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  if (perkListRef.current) perkListRef.current.scrollTop = 0;
                }}
              />
            </label>
            {(modifierTargetId || pendingPerk || movingPerk) && (
              <div className="perk-library__actions perk-library__actions--active">
                {modifierTargetId && (
                  <button
                    type="button"
                    className="icon-button"
                    onClick={closeCompatibilityFilter}
                    aria-label="Show all perks"
                    title="Show all perks"
                  >
                    <X size={17} />
                  </button>
                )}
                {(pendingPerk || movingPerk) && (
                  <button
                    type="button"
                    className="icon-button"
                    onClick={clearHeldState}
                    aria-label={movingPerk ? "Cancel perk move" : "Cancel perk placement"}
                  >
                    <X size={17} />
                  </button>
                )}
              </div>
            )}
          </div>

          <div className="segmented-control" aria-label="Filter perks">
            {(["all", "core", "modifier"] as const).map((value) => (
              <button
                type="button"
                className={filter === value ? "is-active" : ""}
                aria-pressed={filter === value}
                key={value}
                onClick={() => {
                  setModifierTargetId(null);
                  filterBeforeCompatibilityRef.current = value;
                  setFilter(value);
                  if (perkListRef.current) perkListRef.current.scrollTop = 0;
                }}
              >
                {value}
              </button>
            ))}
          </div>

          <div
            className="perk-list"
            ref={perkListRef}
            onScroll={() => hideGridChipTooltip()}
          >
            {availablePerks.map((perk) => {
              const pending = pendingPerkId === perk.id;
              const unfulfilled = unfulfilledPerkIds.has(perk.id);
              const tooltipKey = `library-perk:${perk.id}`;
              const tooltipDescription = [
                plainGameText(perk.description) || "No description available.",
                unfulfilled ? "Needs a compatible active target." : "",
              ].filter(Boolean).join("\n");
              const wellColor = unfulfilled
                ? "#ff5f57"
                : perkChipColor(perk, index.kits.length);
              const wellTone = unfulfilled
                ? "red"
                : wellColor === GAME_CHIP_COLORS.kit ? "green" : "blue";
              return (
                <button
                  type="button"
                  className={`perk-list-item ${pending ? "is-pending" : ""} ${unfulfilled ? "is-unfulfilled" : ""}`}
                  key={perk.id}
                  data-card-tone={unfulfilled ? "gray" : "orange"}
                  data-well-tone={wellTone}
                  data-dependency-status={unfulfilled ? "unfulfilled" : "ready"}
                  style={{ "--perk-library-well": wellColor } as CSSProperties}
                  draggable
                  onDragStart={(event) => {
                    hideGridChipTooltip(tooltipKey);
                    pendingFamilyFilterIdRef.current = modifierTargetId;
                    const rotation = pendingPerkId === perk.id ? pendingRotation : "Default";
                    const metrics = refreshGridMetrics();
                    const shape = rotateShape(perk.grid.shapes[0], rotation);
                    updateGrabOffset(centeredGrabOffset(shape, metrics));
                    event.dataTransfer.setData("application/x-afe2-perk", perk.id);
                    event.dataTransfer.setData("application/x-afe2-rotation", rotation);
                    event.dataTransfer.effectAllowed = "copy";
                    setPendingPerkId(perk.id);
                    setPendingRotation(rotation);
                    setMovingPerkId(null);
                    setDraggingPerkId(null);
                    setPointerPosition(null);
                  }}
                  onDragEnd={() => {
                    setPendingPerkId(null);
                    setPendingRotation("Default");
                    setPointerPosition(null);
                    updateGrabOffset(null);
                    pendingFamilyFilterIdRef.current = null;
                  }}
                  onClick={(event) => choosePerk(perk, event.clientX, event.clientY)}
                  onMouseEnter={(event) => showGridChipTooltip(
                    event.currentTarget,
                    tooltipKey,
                    perk.displayName,
                    tooltipDescription,
                  )}
                  onMouseLeave={() => hideGridChipTooltip(tooltipKey)}
                  onFocus={(event) => showGridChipTooltip(
                    event.currentTarget,
                    tooltipKey,
                    perk.displayName,
                    tooltipDescription,
                  )}
                  onBlur={() => hideGridChipTooltip(tooltipKey)}
                  aria-pressed={pending}
                  aria-label={`Pick up ${perk.displayName} for placement`}
                  aria-describedby={gridChipTooltip?.chipKey === tooltipKey
                    ? "grid-chip-tooltip"
                    : undefined}
                >
                  <RecordVisual record={perk} />
                  <span className="perk-list-item__copy">
                    <strong>{perk.displayName}</strong>
                    <small>{perk.perkType}</small>
                  </span>
                  <span className={`perk-state perk-state--${unfulfilled ? "unfulfilled" : perk.perkType}`}>
                    {unfulfilled ? "TARGET" : footprintLabel(perk)}
                  </span>
                </button>
              );
            })}
            {!availablePerks.length && (
              <div className="empty-state empty-state--small">
                <Search size={22} />
                <strong>No matching perks</strong>
              </div>
            )}
          </div>
        </aside>
      </div>

      {cursorPerk && cursorRotation && cursorShape && pointerPosition && (
        <div
          className={`perk-cursor-preview perk-cursor-preview--${cursorPerk.perkType}`}
          data-placement-mode={movingPerkId ? "move" : "new"}
          data-snap-state={cursorSnapState}
          data-snap-row={snappedPlacement?.placement.row}
          data-snap-column={snappedPlacement?.placement.column}
          data-testid="perk-cursor-preview"
          style={{
            ...chipBodyStyle(
              chipBodyPath(cursorPerk, cursorRotation),
              perkChipColor(cursorPerk, index.kits.length),
            ),
            width: cursorDimensions.width,
            height: cursorDimensions.height,
            transform: `translate3d(${cursorPreviewLeft}px, ${cursorPreviewTop}px, 0)`,
          } as CSSProperties}
          aria-hidden="true"
        >
          <RecordVisual record={cursorPerk} />
        </div>
      )}

      {gridChipTooltip && (
        <div
          className="grid-chip-tooltip"
          data-placement={gridChipTooltip.placement}
          id="grid-chip-tooltip"
          role="tooltip"
          style={{ left: gridChipTooltip.x, top: gridChipTooltip.y }}
        >
          <strong>{gridChipTooltip.title}</strong>
          <span>{gridChipTooltip.description}</span>
        </div>
      )}

      {pendingFamilyAssignment && (() => {
        const perk = index.byId.get(pendingFamilyAssignment.placement.perkId);
        return perk?.kind === "perk" ? (
          <ModifierFamilyDialog
            index={index}
            perk={perk}
            choices={pendingFamilyAssignment.choices}
            onSelect={choosePendingFamily}
            onCancel={cancelPendingFamily}
          />
        ) : null;
      })()}
    </section>
  );
}
