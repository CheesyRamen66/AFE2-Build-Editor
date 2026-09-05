import { Plus } from "lucide-react";
import { useRef, useState } from "react";
import { plainGameText } from "../data/catalogue";
import {
  attachmentSlotKey,
  weaponEquipmentSlots,
  type BuildState,
} from "../model/build";
import {
  attachmentSlotDisplayName,
  weaponSlotDisplayName,
  type CatalogueIndex,
  type ComponentSlot,
  type EquipmentSlot,
  type KitRecord,
  type WeaponRecord,
  type WeaponSlot,
} from "../model/catalogue";
import { RecordVisual } from "./RecordVisual";

interface WeaponLoadoutProps {
  index: CatalogueIndex;
  kit: KitRecord;
  build: BuildState;
  onChooseWeapon: (slot: WeaponSlot) => void;
  onChooseAttachment: (
    weaponSlotIndex: number,
    weapon: WeaponRecord,
    slot: ComponentSlot | EquipmentSlot,
    selectedId: string | null,
  ) => void;
}

function LoadoutTooltip({
  id,
  name,
  description,
}: {
  id: string;
  name: string;
  description: string;
}) {
  return (
    <span className="loadout-tooltip" id={id} role="tooltip">
      <strong>{name}</strong>
      <span>{description}</span>
    </span>
  );
}

export function WeaponLoadout({
  index,
  kit,
  build,
  onChooseWeapon,
  onChooseAttachment,
}: WeaponLoadoutProps) {
  const [hoveredChoice, setHoveredChoice] = useState<string | null>(null);
  const [focusedChoice, setFocusedChoice] = useState<string | null>(null);
  const suppressRestoredFocusTooltipRef = useRef<string | null>(null);
  const activeTooltip = hoveredChoice ?? focusedChoice;

  const openPickerForChoice = (choiceKey: string, openPicker: () => void) => {
    // RecordPicker restores focus to the control that opened it. Keep the
    // opener suppressed until the user genuinely interacts with it again:
    // StrictMode can run the picker's effect cleanup once during mounting and
    // then again when the picker really closes.
    suppressRestoredFocusTooltipRef.current = choiceKey;
    setHoveredChoice(null);
    setFocusedChoice(null);
    openPicker();
  };

  const focusChoice = (choiceKey: string) => {
    if (suppressRestoredFocusTooltipRef.current === choiceKey) {
      setFocusedChoice(null);
      return;
    }
    setFocusedChoice(choiceKey);
  };

  const hoverChoice = (choiceKey: string) => {
    if (suppressRestoredFocusTooltipRef.current === choiceKey) {
      suppressRestoredFocusTooltipRef.current = null;
    }
    setHoveredChoice(choiceKey);
  };

  const blurChoice = (choiceKey: string) => {
    setFocusedChoice((current) => current === choiceKey ? null : current);
    // Focus moving into an open picker is part of its restoration lifecycle,
    // including StrictMode's development probe. Once no picker exists, a blur
    // represents a later user focus move and may release the suppression.
    if (
      suppressRestoredFocusTooltipRef.current === choiceKey &&
      !document.querySelector(".picker-overlay")
    ) {
      suppressRestoredFocusTooltipRef.current = null;
    }
  };

  return (
    <section className="section" id="weapons" aria-label="Weapons">
      <div className="weapon-list">
        {kit.weaponSlots.map((kitSlot) => {
          const selection = build.weapons.find((weapon) => weapon.slotIndex === kitSlot.index);
          const weapon = selection ? index.byId.get(selection.weaponId) : undefined;
          if (!selection || !weapon || weapon.kind !== "weapon") return null;
          const equipmentSlots = weaponEquipmentSlots(weapon);
          const slotName = weaponSlotDisplayName(kitSlot);
          const weaponChoiceKey = `weapon:${kitSlot.index}`;
          const weaponTooltipId = `weapon-tooltip-${kitSlot.index}`;
          return (
            <article
              className="weapon-card"
              data-weapon-slot={slotName.toLocaleLowerCase()}
              key={kitSlot.index}
            >
              <button
                type="button"
                className="weapon-card__hero"
                onClick={() => openPickerForChoice(
                  weaponChoiceKey,
                  () => onChooseWeapon(kitSlot),
                )}
                onMouseEnter={() => hoverChoice(weaponChoiceKey)}
                onMouseLeave={() => setHoveredChoice((current) => (
                  current === weaponChoiceKey ? null : current
                ))}
                onFocus={() => focusChoice(weaponChoiceKey)}
                onBlur={() => blurChoice(weaponChoiceKey)}
                aria-describedby={activeTooltip === weaponChoiceKey ? weaponTooltipId : undefined}
                aria-label={`Choose weapon for ${slotName} slot. Currently ${weapon.displayName}.`}
              >
                <span className="weapon-card__slot">
                  <strong>{slotName}</strong>
                </span>
                <RecordVisual record={weapon} />
                <span className="weapon-card__copy">
                  <strong className="weapon-card__name">{weapon.displayName}</strong>
                </span>
                {activeTooltip === weaponChoiceKey && (
                  <LoadoutTooltip
                    id={weaponTooltipId}
                    name={weapon.displayName}
                    description={plainGameText(weapon.description) || "No weapon description available."}
                  />
                )}
              </button>

              <div className="attachment-strip">
                {equipmentSlots.map((slot) => {
                  const key = attachmentSlotKey(slot);
                  const selectedId = selection.attachments[key] ?? null;
                  const record = selectedId ? index.byId.get(selectedId) : undefined;
                  const attachmentChoiceKey = `attachment:${kitSlot.index}:${key}`;
                  const attachmentTooltipId = `attachment-tooltip-${kitSlot.index}-${slot.kind}-${slot.index}`;
                  const attachmentSlotName = attachmentSlotDisplayName(slot);
                  const tooltipName = record?.displayName ?? attachmentSlotName;
                  const tooltipDescription = record
                    ? plainGameText(record.description) || "No attachment description available."
                    : "No attachment selected.";
                  return (
                    <button
                      type="button"
                      className={`attachment-slot ${record ? "is-filled" : ""}`}
                      key={key}
                      onClick={() => openPickerForChoice(
                        attachmentChoiceKey,
                        () => onChooseAttachment(kitSlot.index, weapon, slot, selectedId),
                      )}
                      onMouseEnter={() => hoverChoice(attachmentChoiceKey)}
                      onMouseLeave={() => setHoveredChoice((current) => (
                        current === attachmentChoiceKey ? null : current
                      ))}
                      onFocus={() => focusChoice(attachmentChoiceKey)}
                      onBlur={() => blurChoice(attachmentChoiceKey)}
                      aria-describedby={activeTooltip === attachmentChoiceKey
                        ? attachmentTooltipId
                        : undefined}
                      aria-label={`${attachmentSlotName}: ${record?.displayName ?? "empty"}. Choose attachment.`}
                    >
                      <span className="attachment-slot__icon">
                        {record ? <RecordVisual record={record} /> : <Plus size={18} />}
                      </span>
                      <span className="attachment-slot__copy">
                        <small>{attachmentSlotName}</small>
                        {record && <strong>{record.displayName}</strong>}
                      </span>
                      {activeTooltip === attachmentChoiceKey && (
                        <LoadoutTooltip
                          id={attachmentTooltipId}
                          name={tooltipName}
                          description={tooltipDescription}
                        />
                      )}
                    </button>
                  );
                })}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
