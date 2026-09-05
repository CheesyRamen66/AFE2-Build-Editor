export type RecordKind =
  | "kit"
  | "ability"
  | "perk"
  | "weapon"
  | "mod"
  | "trait"
  | "augment"
  | "item";

export type Rotation = "Default" | "Clockwise90" | "Clockwise180" | "Clockwise270";

export interface CatalogueIcon {
  path: string;
  width?: number;
  height?: number;
  fallback?: {
    type?: string;
    reason?: string;
    sourceRecordId?: string;
  };
}

export interface CatalogueRecordBase {
  id: string;
  kind: RecordKind;
  displayName: string;
  description?: string | null;
  icon?: CatalogueIcon | null;
  packagePath?: string;
}

export interface AttachmentStaticStatLine {
  attribute: string;
  displayText: string;
  displayType: "Float" | "Integer" | "Percent";
  displayValue: string;
  effectPackagePath: string;
  result: "HigherIsBetter" | "LowerIsBetter";
  sortOrder: number;
  statText: string;
  statValue: number;
}

export interface AttachmentConditionalStatLine {
  displayType: "Float" | "Integer" | "None" | "Percent";
  result: "HigherIsBetter" | "LowerIsBetter";
  statText: string | null;
  statValue: number;
}

export interface AttachmentConditionalDescription {
  conditionText: string | null;
  statLines: AttachmentConditionalStatLine[];
}

export interface AttachmentDescriptionFields {
  /** The attachment's serialized prose before derived and conditional sections. */
  authoredDescription?: string | null;
  /** Backend-formatted client stat rows; the browser must not recalculate them. */
  staticStatLines?: AttachmentStaticStatLine[];
  /** Authored conditional sections and their already-decoded stat values. */
  conditionalDescriptions?: AttachmentConditionalDescription[];
}

export interface AbilitySlot {
  index: number;
  role: "primary" | "secondary" | "passive" | string;
  row: number;
  column: number;
  lockedChipId: string;
  selectableAbilityIds: string[];
}

export interface WeaponSlot {
  index: number;
  slotType: string;
  weaponType: string;
  weaponSubtype?: string;
  defaultWeaponId?: string;
  compatibleWeaponIds: string[];
}

const EDITOR_WEAPON_SLOT_NAMES = ["Primary", "Signature", "Sidearm"] as const;
const EDITOR_WEAPON_SLOT_NAME_BY_TYPE: Record<string, string> = {
  primary: "Primary",
  signature: "Signature",
  sidearm: "Sidearm",
};

export function weaponSlotDisplayName(
  slot: Pick<WeaponSlot, "index" | "slotType">,
): string {
  const normalizedSlotType = slot.slotType
    .trim()
    .replace(/^.*::/, "")
    .toLocaleLowerCase();
  const semanticName = EDITOR_WEAPON_SLOT_NAME_BY_TYPE[normalizedSlotType];
  if (semanticName) return semanticName;

  const indexedName = EDITOR_WEAPON_SLOT_NAMES[slot.index];
  if (indexedName) return indexedName;
  return slot.slotType
    .replace(/[._-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

/**
 * The game serializes attachment slot names both abbreviated and spelled out —
 * "Int Magazine" on thirteen weapons and "Internal Magazine" on three, the same
 * split for Sml/Small, Med/Medium and Lrg/Large. Editor labels use the
 * spelled-out form the catalogue itself already attests.
 */
const ATTACHMENT_SIZE_WORDS: Record<string, string> = {
  int: "Internal",
  lrg: "Large",
  med: "Medium",
  sml: "Small",
};

export function attachmentSlotDisplayName(slot: { displayName: string }): string {
  return slot.displayName
    .split(/\s+/)
    .map((word) => ATTACHMENT_SIZE_WORDS[word.toLocaleLowerCase()] ?? word)
    .join(" ");
}

export interface KitRecord extends CatalogueRecordBase {
  kind: "kit";
  abilitySlots: AbilitySlot[];
  selectablePerkIds: string[];
  weaponSlots: WeaponSlot[];
}

export interface GridCell {
  row: number;
  column: number;
  label?: string;
}

export interface PerkColorPaletteEntry {
  index: number;
  linearRgba: {
    r: number;
    g: number;
    b: number;
    a: number;
  };
  srgbHex: string;
}

export interface PerkColorPalette {
  colors?: PerkColorPaletteEntry[];
  indexRule?: string;
  sourceFunction?: string;
  sourcePackagePath?: string | null;
  status?: string;
  reason?: string;
}

export interface PerkShape {
  width: number;
  height: number;
  cellCount: number;
  size: string;
  occupiedCells: GridCell[];
}

export interface ChipBodyAsset extends CatalogueIcon {
  family?: string;
  footprint?: { width: number; height: number };
  variant?: string;
}

export interface FamilyConnectorAsset extends CatalogueIcon {
  packagePath?: string;
  pixelFormat?: string;
  role?: "connector" | string;
  sha256?: string;
  variant?: "ghost" | string;
}

export interface PerkDependencies {
  possibleTargetPerkIds?: string[];
  requiresConnectedCompatibleTarget?: boolean;
  targetSelection?: {
    candidateIds?: string[];
    recordField?: string;
    required?: boolean;
  };
}

export interface PerkVisualClassification {
  restrictionType?: "kit" | "role" | "none";
  restrictionTypeRaw?: string;
  roleRestrictionRaw?: string;
  status: "resolved" | "inferred" | "unresolved-restriction-type" | string;
  reason?: string;
  evidence: {
    source: string;
    property?: string;
    valueRaw?: string;
    roleRestrictionProperty?: string;
    parentClassPath?: string | null;
    reason?: string;
  };
}

export interface PerkRecord extends CatalogueRecordBase {
  kind: "perk";
  perkType: "core" | "modifier" | string;
  availableToKitIds: string[];
  grid: {
    allowedRotations: Rotation[];
    shapes: PerkShape[];
  };
  dependencies?: PerkDependencies | null;
  visualClassification?: PerkVisualClassification;
  rendering?: {
    status?: string;
    contentIconPath?: string;
    chipBodyByFootprint?: ChipBodyAsset[];
  } | null;
}

export interface AbilityRecord extends CatalogueRecordBase {
  kind: "ability";
  visualClassification?: PerkVisualClassification;
  rendering?: {
    chipBodyByFootprint?: ChipBodyAsset[];
    contentIconPath?: string;
  } | null;
}

export interface ComponentSlot {
  index: number;
  kind: "component";
  displayName: string;
  slotCategory: string;
  slotCategoryDisplayName?: string;
  compatibleIds: string[];
  defaultAttachmentId?: string;
}

export interface EquipmentSlot {
  index: number;
  kind: "trait" | "augment";
  displayName: string;
  slotCategory: string;
  compatibleIds: string[];
  defaultAttachmentId?: string;
}

export interface WeaponRecord extends CatalogueRecordBase {
  kind: "weapon";
  silhouetteIcon?: CatalogueIcon | null;
  componentSlots: ComponentSlot[];
  compatibility: {
    collectionCategory?: string;
    weaponRole?: string;
    weaponSubType?: string;
    traitSlot?: EquipmentSlot;
    augmentSlot?: EquipmentSlot;
  };
}

export interface ModRecord extends CatalogueRecordBase, AttachmentDescriptionFields {
  kind: "mod";
}

export interface TraitRecord extends CatalogueRecordBase, AttachmentDescriptionFields {
  kind: "trait";
}

export interface AugmentAvailability {
  cost: number;
  featureUnlockRequirementRaw: string;
  purchasable: boolean;
}

export interface AugmentDescriptionPanel {
  description: string | null;
  descriptionSecondary: string | null;
  descriptionUpper: string | null;
}

export interface AugmentRecord extends CatalogueRecordBase, AttachmentDescriptionFields {
  kind: "augment";
  availability?: AugmentAvailability;
  collectionCategory?: string;
  collectionConceptId?: string;
  compatibleWeaponIds?: string[];
  descriptionPanel?: AugmentDescriptionPanel;
}

export interface ItemRecord extends CatalogueRecordBase {
  kind: "item";
  itemTier: "major" | "minor" | string;
  availableToKitIds?: string[];
}

export type CatalogueRecord =
  | KitRecord
  | AbilityRecord
  | PerkRecord
  | WeaponRecord
  | ModRecord
  | TraitRecord
  | AugmentRecord
  | ItemRecord;

export interface AbilityAnchor {
  role: string;
  row: number;
  column: number;
  lockedChipId: string;
  cells: GridCell[];
  rendering?: { chipBody?: ChipBodyAsset; status?: string };
}

export interface KitGridLayout {
  kitId: string;
  baseBoard: { rows: number; columns: number };
  renderExtent: { rows: number; columns: number };
  placeableCellCount: number;
  placeableCells: GridCell[];
  anchors: AbilityAnchor[];
}

export interface ItemSlot {
  index: number;
  displayName: string;
  itemTier: string;
  compatibleItemIds: string[];
}

export interface PlannerCatalogue {
  schemaVersion: number;
  sourceFingerprint: string;
  game: { buildId: string; steamAppId: string };
  records: CatalogueRecord[];
  itemSlots: ItemSlot[];
  perkGrid: {
    coordinateSystem: Record<string, unknown>;
    familyConnector?: FamilyConnectorAsset;
    kitLayouts: KitGridLayout[];
    perkColorPalette?: PerkColorPalette;
    placementRules: Record<string, unknown>;
  };
}

export interface CatalogueIndex {
  catalogue: PlannerCatalogue;
  byId: Map<string, CatalogueRecord>;
  kits: KitRecord[];
  perks: PerkRecord[];
  weapons: WeaponRecord[];
  items: ItemRecord[];
  layoutByKitId: Map<string, KitGridLayout>;
}

const PREFERRED_KIT_ID_LEAVES = [
  "KitUnlock_Gunner",
  "KitUnlock_Technician",
  "KitUnlock_Demolisher",
  "KitUnlock_Lancer",
  "KitUnlock_Medic",
  "KitUnlock_Custom",
] as const;

const preferredKitRank = new Map<string, number>(
  PREFERRED_KIT_ID_LEAVES.map((id, index) => [id, index]),
);

function orderKitsForEditor(kits: KitRecord[]): KitRecord[] {
  return kits
    .map((kit, sourceIndex) => {
      const idLeaf = kit.id.slice(kit.id.lastIndexOf("/") + 1);
      return {
        kit,
        rank: preferredKitRank.get(idLeaf) ?? PREFERRED_KIT_ID_LEAVES.length,
        sourceIndex,
      };
    })
    .sort((left, right) => left.rank - right.rank || left.sourceIndex - right.sourceIndex)
    .map(({ kit }) => kit);
}

export function createCatalogueIndex(catalogue: PlannerCatalogue): CatalogueIndex {
  const byId = new Map(catalogue.records.map((record) => [record.id, record]));
  const kits = orderKitsForEditor(
    catalogue.records.filter((record): record is KitRecord => record.kind === "kit"),
  );
  return {
    catalogue,
    byId,
    kits,
    perks: catalogue.records.filter((record): record is PerkRecord => record.kind === "perk"),
    weapons: catalogue.records.filter(
      (record): record is WeaponRecord => record.kind === "weapon",
    ),
    items: catalogue.records.filter((record): record is ItemRecord => record.kind === "item"),
    layoutByKitId: new Map(
      catalogue.perkGrid.kitLayouts.map((layout) => [layout.kitId, layout]),
    ),
  };
}

export function isCatalogueRecord(value: unknown): value is CatalogueRecord {
  if (!value || typeof value !== "object") return false;
  const record = value as Partial<CatalogueRecord>;
  return typeof record.id === "string" && typeof record.displayName === "string";
}
