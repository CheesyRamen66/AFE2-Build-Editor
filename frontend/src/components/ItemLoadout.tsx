import { ChevronRight, Plus } from "lucide-react";
import { plainGameText } from "../data/catalogue";
import type { BuildState } from "../model/build";
import type { CatalogueIndex, ItemSlot } from "../model/catalogue";
import { RecordVisual } from "./RecordVisual";

interface ItemLoadoutProps {
  index: CatalogueIndex;
  build: BuildState;
  onChooseItem: (slot: ItemSlot) => void;
}

export function ItemLoadout({ index, build, onChooseItem }: ItemLoadoutProps) {
  const itemSlots = [...index.catalogue.itemSlots].sort((left, right) => {
    const tierOrder = (tier: string) => {
      const normalizedTier = tier.toLowerCase();
      if (normalizedTier === "minor") return 0;
      if (normalizedTier === "major") return 1;
      return 2;
    };

    return tierOrder(left.itemTier) - tierOrder(right.itemTier) || left.index - right.index;
  });

  return (
    <section className="section" id="items" aria-label="Items">
      <div className="item-grid">
        {itemSlots.map((slot) => {
          const itemId = build.itemIds[slot.index];
          const item = itemId ? index.byId.get(itemId) : undefined;
          return (
            <button
              type="button"
              className={`item-card ${item ? "is-filled" : ""}`}
              key={slot.index}
              onClick={() => onChooseItem(slot)}
              aria-label={`${slot.displayName}: ${item?.displayName ?? "empty"}. Choose item.`}
            >
              <span className="item-card__visual">
                {item ? <RecordVisual record={item} /> : <Plus size={18} />}
              </span>
              <span className="item-card__copy">
                <small>{slot.displayName}</small>
                <strong>{item?.displayName ?? "Choose an item"}</strong>
                <span>
                  {item
                    ? plainGameText(item.description) || "No description available."
                    : `${slot.compatibleItemIds.length} compatible choices`}
                </span>
              </span>
              <ChevronRight size={19} />
            </button>
          );
        })}
      </div>
    </section>
  );
}
