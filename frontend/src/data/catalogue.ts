import {
  createCatalogueIndex,
  isCatalogueRecord,
  type CatalogueIndex,
  type PlannerCatalogue,
} from "../model/catalogue";

const catalogueBase = `${import.meta.env.BASE_URL}catalogue/`;

export function catalogueAssetUrl(path?: string | null): string | undefined {
  if (!path) return undefined;
  const segments = path.split("/");
  if (
    !["icons", "grid-assets"].includes(segments[0]) ||
    segments.some((segment) => !segment || segment === "." || segment === ".." || segment.includes("\\"))
  ) {
    return undefined;
  }
  return `${catalogueBase}${segments.map(encodeURIComponent).join("/")}`;
}

export function plainGameText(value?: string | null): string {
  if (!value) return "";
  return value
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<[^>]+>/g, "")
    .replace(/\r/g, "")
    .trim();
}

export async function loadCatalogue(signal?: AbortSignal): Promise<CatalogueIndex> {
  const response = await fetch(`${catalogueBase}planner-catalogue.json`, { signal });
  if (!response.ok) {
    throw new Error(`Catalogue request failed (${response.status} ${response.statusText})`);
  }

  const catalogue = (await response.json()) as Partial<PlannerCatalogue>;
  if (catalogue.schemaVersion !== 1) {
    throw new Error(`Unsupported planner catalogue schema: ${String(catalogue.schemaVersion)}`);
  }
  if (!Array.isArray(catalogue.records) || !catalogue.records.every(isCatalogueRecord)) {
    throw new Error("Planner catalogue records are missing or malformed");
  }
  if (!Array.isArray(catalogue.itemSlots) || !Array.isArray(catalogue.perkGrid?.kitLayouts)) {
    throw new Error("Planner catalogue selection contracts are missing");
  }

  return createCatalogueIndex(catalogue as PlannerCatalogue);
}
