import type { CatalogueRecord } from "../model/catalogue";
import { catalogueAssetUrl } from "../data/catalogue";

interface RecordVisualProps {
  record?: CatalogueRecord;
  className?: string;
  silhouette?: boolean;
}

export function RecordVisual({ record, className = "", silhouette = false }: RecordVisualProps) {
  const icon = record?.kind === "weapon" && silhouette
    ? record.silhouetteIcon ?? record.icon
    : record?.icon;
  const source = catalogueAssetUrl(icon?.path);

  if (source) {
    return (
      <img
        className={`record-visual ${className}`}
        src={source}
        alt=""
        loading="lazy"
        draggable={false}
      />
    );
  }

  return (
    <span className={`record-visual record-visual--fallback ${className}`} aria-hidden="true">
      {record?.displayName.slice(0, 2).toUpperCase() ?? "?"}
    </span>
  );
}
