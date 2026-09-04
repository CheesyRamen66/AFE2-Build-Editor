import type { KitRecord } from "../model/catalogue";
import { RecordVisual } from "./RecordVisual";

interface KitSelectorProps {
  kits: KitRecord[];
  selectedKitId: string;
  onSelect: (kitId: string) => void;
}

export function KitSelector({ kits, selectedKitId, onSelect }: KitSelectorProps) {
  return (
    <aside className="kit-section" id="kit" aria-label="Kit selector">
      <label className="kit-select-mobile">
        <span className="sr-only">Choose a kit</span>
        <select value={selectedKitId} onChange={(event) => onSelect(event.target.value)}>
          {kits.map((kit) => <option value={kit.id} key={kit.id}>{kit.displayName}</option>)}
        </select>
      </label>

      <div className="kit-list" role="radiogroup" aria-label="Available kits">
        {kits.map((kit, kitIndex) => {
          const selected = kit.id === selectedKitId;
          return (
            <button
              type="button"
              role="radio"
              aria-checked={selected}
              tabIndex={selected ? 0 : -1}
              className={`kit-card ${selected ? "is-selected" : ""}`}
              key={kit.id}
              onClick={() => onSelect(kit.id)}
              onKeyDown={(event) => {
                let nextIndex: number | undefined;
                switch (event.key) {
                  case "ArrowLeft":
                  case "ArrowUp":
                    nextIndex = (kitIndex - 1 + kits.length) % kits.length;
                    break;
                  case "ArrowRight":
                  case "ArrowDown":
                    nextIndex = (kitIndex + 1) % kits.length;
                    break;
                  case "Home":
                    nextIndex = 0;
                    break;
                  case "End":
                    nextIndex = kits.length - 1;
                    break;
                  default:
                    return;
                }

                event.preventDefault();
                const radios = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>(
                  '[role="radio"]',
                );
                radios?.[nextIndex]?.focus();
                onSelect(kits[nextIndex].id);
              }}
            >
              <RecordVisual record={kit} />
              <span className="kit-card__copy">
                <strong>{kit.displayName}</strong>
              </span>
            </button>
          );
        })}
      </div>
    </aside>
  );
}
