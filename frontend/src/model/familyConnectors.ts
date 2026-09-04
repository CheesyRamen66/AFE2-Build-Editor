import {
  occupiedCells,
  type BuildState,
  type PlacedPerk,
} from "./build";
import type { CatalogueIndex, GridCell, KitGridLayout, PerkRecord } from "./catalogue";

export type FamilyConnectorOrientation = "horizontal" | "vertical";

/**
 * A boundary between two orthogonally adjacent chips in the same perk family.
 * `row` and `column` identify the left cell for a horizontal connector and the
 * upper cell for a vertical connector.
 */
export interface FamilyConnector {
  key: string;
  orientation: FamilyConnectorOrientation;
  row: number;
  column: number;
  familyId: string;
  fromNodeId: string;
  toNodeId: string;
  fromCell: GridCell;
  toCell: GridCell;
}

interface FamilyNode {
  nodeId: string;
  familyId: string;
  cells: GridCell[];
}

const cellKey = (cell: GridCell): string => `${cell.row}:${cell.column}`;

function modifierCandidateIds(perk: PerkRecord): string[] {
  return perk.dependencies?.targetSelection?.candidateIds ??
    perk.dependencies?.possibleTargetPerkIds ?? [];
}

/**
 * Calculates the white connector bars shown between distinct chips belonging
 * to one resolved ability/core family. Invalid and unlinked modifiers are not
 * included in a family, so they cannot produce connectors.
 */
export function calculateFamilyConnectors(
  index: CatalogueIndex,
  layout: KitGridLayout,
  build: BuildState,
  linkIssueIds: ReadonlySet<string> = new Set<string>(),
): FamilyConnector[] {
  if (layout.kitId !== build.kitId) return [];

  const kit = index.byId.get(build.kitId);
  if (!kit || kit.kind !== "kit") return [];

  const nodes: FamilyNode[] = [];
  const terminalFamilyByRecordId = new Map<string, string>();

  for (const slot of kit.abilitySlots) {
    const abilityId = build.abilityIds[slot.index];
    const anchor = layout.anchors.find((candidate) => candidate.role === slot.role);
    if (!abilityId || !anchor || index.byId.get(abilityId)?.kind !== "ability") continue;
    terminalFamilyByRecordId.set(abilityId, abilityId);
    nodes.push({
      nodeId: `ability:${slot.index}`,
      familyId: abilityId,
      cells: anchor.cells,
    });
  }

  const placementsById = new Map<string, PlacedPerk>();
  for (const placement of build.perks) {
    placementsById.set(placement.perkId, placement);
    const perk = index.byId.get(placement.perkId);
    if (!perk || perk.kind !== "perk" || perk.perkType !== "core") continue;
    terminalFamilyByRecordId.set(perk.id, perk.id);
    nodes.push({
      nodeId: `perk:${perk.id}`,
      familyId: perk.id,
      cells: occupiedCells(perk, placement),
    });
  }

  const familyMemo = new Map<string, string | null>();
  const resolveModifierFamily = (
    perkId: string,
    visiting: ReadonlySet<string> = new Set<string>(),
  ): string | null => {
    if (familyMemo.has(perkId)) return familyMemo.get(perkId) ?? null;
    if (linkIssueIds.has(perkId) || visiting.has(perkId)) return null;

    const placement = placementsById.get(perkId);
    const perk = index.byId.get(perkId);
    if (!placement || !perk || perk.kind !== "perk" || perk.perkType !== "modifier") {
      familyMemo.set(perkId, null);
      return null;
    }

    const targetId = placement.targetId;
    if (!targetId || !modifierCandidateIds(perk).includes(targetId)) {
      familyMemo.set(perkId, null);
      return null;
    }

    const terminalFamily = terminalFamilyByRecordId.get(targetId);
    if (terminalFamily) {
      familyMemo.set(perkId, terminalFamily);
      return terminalFamily;
    }

    const familyId = resolveModifierFamily(targetId, new Set(visiting).add(perkId));
    familyMemo.set(perkId, familyId);
    return familyId;
  };

  for (const placement of build.perks) {
    const perk = index.byId.get(placement.perkId);
    if (!perk || perk.kind !== "perk" || perk.perkType !== "modifier") continue;
    const familyId = resolveModifierFamily(perk.id);
    if (!familyId) continue;
    nodes.push({
      nodeId: `perk:${perk.id}`,
      familyId,
      cells: occupiedCells(perk, placement),
    });
  }

  const nodesByCell = new Map<string, FamilyNode | null>();
  for (const node of nodes) {
    for (const cell of node.cells) {
      const key = cellKey(cell);
      // A valid build cannot overlap. Treat an overlapping cell in a transient
      // or manually constructed build as ambiguous instead of drawing through it.
      nodesByCell.set(key, nodesByCell.has(key) ? null : node);
    }
  }

  const connectors: FamilyConnector[] = [];
  const seen = new Set<string>();
  const directions: ReadonlyArray<{
    orientation: FamilyConnectorOrientation;
    rowDelta: number;
    columnDelta: number;
  }> = [
    { orientation: "horizontal", rowDelta: 0, columnDelta: 1 },
    { orientation: "vertical", rowDelta: 1, columnDelta: 0 },
  ];

  for (const node of nodes) {
    for (const fromCell of node.cells) {
      if (nodesByCell.get(cellKey(fromCell)) !== node) continue;
      for (const direction of directions) {
        const toCell = {
          row: fromCell.row + direction.rowDelta,
          column: fromCell.column + direction.columnDelta,
        };
        const neighbor = nodesByCell.get(cellKey(toCell));
        if (!neighbor || neighbor === node || neighbor.familyId !== node.familyId) continue;

        const key = `${direction.orientation}:${fromCell.row}:${fromCell.column}`;
        if (seen.has(key)) continue;
        seen.add(key);
        connectors.push({
          key,
          orientation: direction.orientation,
          row: fromCell.row,
          column: fromCell.column,
          familyId: node.familyId,
          fromNodeId: node.nodeId,
          toNodeId: neighbor.nodeId,
          fromCell: { ...fromCell },
          toCell,
        });
      }
    }
  }

  return connectors.sort((left, right) =>
    left.row - right.row ||
    left.column - right.column ||
    left.orientation.localeCompare(right.orientation),
  );
}
