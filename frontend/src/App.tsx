import {
  Menu,
  RefreshCw,
  WifiOff,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useReducer, useState } from "react";
import { browserBuildDraftStore } from "./data/buildDraftStore";
import { loadCatalogue } from "./data/catalogue";
import {
  attachmentSlotKey,
  createBuildForKit,
  reduceBuild,
  type BuildAction,
  type BuildState,
} from "./model/build";
import {
  weaponSlotDisplayName,
  type AbilitySlot,
  type CatalogueIndex,
  type CatalogueRecord,
  type ComponentSlot,
  type EquipmentSlot,
  type ItemSlot,
  type WeaponRecord,
  type WeaponSlot,
} from "./model/catalogue";
import { ItemLoadout } from "./components/ItemLoadout";
import { KitSelector } from "./components/KitSelector";
import { PerkWorkbench } from "./components/PerkWorkbench";
import { RecordPicker, type PickerConfig } from "./components/RecordPicker";
import { WeaponLoadout } from "./components/WeaponLoadout";

function recordsFor(index: CatalogueIndex, ids: string[]): CatalogueRecord[] {
  return ids.flatMap((id) => {
    const record = index.byId.get(id);
    return record ? [record] : [];
  });
}

function LoadingScreen() {
  return (
    <main className="boot-screen">
      <div className="boot-mark"><span>AFE</span><span>2</span></div>
      <span className="eyebrow">Local systems</span>
      <h1>Loading catalogue</h1>
      <div className="boot-progress"><span /></div>
      <p>Indexing kits, perks, weapons, and mission items…</p>
    </main>
  );
}

function ErrorScreen({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <main className="boot-screen boot-screen--error">
      <WifiOff size={38} />
      <span className="eyebrow">Catalogue offline</span>
      <h1>Local game data is unavailable</h1>
      <p>{message}</p>
      <code>python3 scripts/build_catalogue.py extract --output .local/catalogue</code>
      <button type="button" className="button button--primary" onClick={onRetry}>
        <RefreshCw size={16} /> Retry
      </button>
    </main>
  );
}

export function BuildEditor({ index }: { index: CatalogueIndex }) {
  const initialBuild = useMemo(() => {
    if (!index.kits.length) throw new Error("The planner catalogue contains no kits.");
    return browserBuildDraftStore.load(index) ??
      createBuildForKit(index, index.kits[0].id);
  }, [index]);
  const [build, baseDispatch] = useReducer(
    (state: BuildState, action: BuildAction) => reduceBuild(index, state, action),
    initialBuild,
  );
  const [picker, setPicker] = useState<PickerConfig | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    browserBuildDraftStore.save(build);
  }, [build]);

  // Deliberately screen-reader only: grid feedback is announced, never shown.
  const notify = useCallback((message: string) => {
    setAnnouncement(message);
  }, []);
  const dispatch = useCallback((action: BuildAction) => baseDispatch(action), []);
  const closePicker = useCallback(() => setPicker(null), []);

  const kit = index.byId.get(build.kitId);
  const layout = index.layoutByKitId.get(build.kitId);
  if (!kit || kit.kind !== "kit" || !layout) {
    throw new Error(`The selected kit is missing its planner contract: ${build.kitId}`);
  }

  const chooseAbility = (slot: AbilitySlot) => {
    const selectedId = build.abilityIds[slot.index];
    setPicker({
      eyebrow: `${kit.displayName} · ${slot.role}`,
      title: `Choose ${slot.role} ability`,
      records: recordsFor(index, slot.selectableAbilityIds),
      selectedId,
      onSelect: (abilityId) => {
        if (abilityId) {
          dispatch({ type: "select-ability", slotIndex: slot.index, abilityId });
          notify("Ability updated. Perk links have been rechecked.");
        }
        setPicker(null);
      },
    });
  };

  const chooseWeapon = (slot: WeaponSlot) => {
    const selected = build.weapons.find((weapon) => weapon.slotIndex === slot.index)?.weaponId;
    const slotName = weaponSlotDisplayName(slot);
    setPicker({
      title: `Choose ${slotName} weapon`,
      records: recordsFor(index, slot.compatibleWeaponIds),
      selectedId: selected,
      onSelect: (weaponId) => {
        if (weaponId) {
          dispatch({ type: "select-weapon", slotIndex: slot.index, weaponId });
          notify("Weapon updated. Its attachment sockets are ready.");
        }
        setPicker(null);
      },
    });
  };

  const chooseAttachment = (
    weaponSlotIndex: number,
    weapon: WeaponRecord,
    slot: ComponentSlot | EquipmentSlot,
    selectedId: string | null,
  ) => {
    const attachmentKey = attachmentSlotKey(slot);
    setPicker({
      eyebrow: `${weapon.displayName} · ${slot.kind}`,
      title: `Choose ${slot.displayName}`,
      records: recordsFor(index, slot.compatibleIds),
      selectedId,
      allowEmpty: true,
      emptyLabel: `No ${slot.displayName}`,
      onSelect: (recordId) => {
        dispatch({
          type: "select-attachment",
          weaponSlotIndex,
          attachmentKey,
          recordId,
        });
        notify(recordId ? `${slot.displayName} selected.` : `${slot.displayName} cleared.`);
        setPicker(null);
      },
    });
  };

  const chooseItem = (slot: ItemSlot) => {
    setPicker({
      eyebrow: "Mission equipment",
      title: `Choose ${slot.displayName}`,
      records: recordsFor(index, slot.compatibleItemIds),
      selectedId: build.itemIds[slot.index],
      allowEmpty: true,
      emptyLabel: `No ${slot.displayName}`,
      onSelect: (itemId) => {
        dispatch({ type: "select-item", slotIndex: slot.index, itemId });
        notify(itemId ? `${slot.displayName} selected.` : `${slot.displayName} cleared.`);
        setPicker(null);
      },
    });
  };

  const navItems = [
    { available: true, href: "#top", label: "Editor" },
    { available: false, label: "Builds" },
    { available: false, label: "Database" },
  ];

  return (
    <div className="app-shell">
      <header className="site-header">
        <a className="brand" href="#top" aria-label="AFE2 Build Editor home">
          <span className="brand__mark"><span>AFE</span><span>2</span></span>
          <span className="brand__copy">
            <strong>Build Editor</strong>
            <small>Aliens: Fireteam Elite 2</small>
          </span>
        </a>

        <nav className={mobileMenuOpen ? "is-open" : ""} aria-label="Site sections">
          {navItems.map((item) => item.available ? (
            <a
              className="is-active"
              href={item.href}
              key={item.label}
              aria-current="page"
              onClick={() => setMobileMenuOpen(false)}
            >
              {item.label}
            </a>
          ) : (
            <button
              type="button"
              key={item.label}
              disabled
              aria-label={`${item.label} (not available yet)`}
              title="Not available yet"
            >
              {item.label}
            </button>
          ))}
        </nav>

        <button
          type="button"
          className="mobile-menu-button"
          onClick={() => setMobileMenuOpen((open) => !open)}
          aria-expanded={mobileMenuOpen}
          aria-label="Toggle navigation"
        >
          {mobileMenuOpen ? <X /> : <Menu />}
        </button>
      </header>

      <main id="top">
        <h1 className="sr-only">AFE2 Build Editor</h1>
        <div className="editor-content">
          <div className="editor-stage">
            <KitSelector
              kits={index.kits}
              selectedKitId={kit.id}
              onSelect={(kitId) => {
                if (kitId === kit.id) return;
                const nextKit = index.byId.get(kitId);
                dispatch({ type: "select-kit", kitId });
                notify(`${nextKit?.displayName ?? "Kit"} loaded with its default gear.`);
              }}
            />

            <PerkWorkbench
              index={index}
              kit={kit}
              layout={layout}
              build={build}
              dispatch={dispatch}
              onChooseAbility={chooseAbility}
              notify={notify}
            />
          </div>

          <div className="loadout-row">
            <WeaponLoadout
              index={index}
              kit={kit}
              build={build}
              onChooseWeapon={chooseWeapon}
              onChooseAttachment={chooseAttachment}
            />

            <ItemLoadout index={index} build={build} onChooseItem={chooseItem} />
          </div>
        </div>
      </main>

      <footer>
        <span>AFE2 BUILD EDITOR // LOCAL PROTOTYPE</span>
        <span>
          STEAM BUILD {index.catalogue.game.buildId} // CATALOGUE {index.catalogue.sourceFingerprint.slice(0, 22)}…
        </span>
      </footer>

      {picker && <RecordPicker config={picker} onClose={closePicker} />}
      <div className="sr-only" aria-live="polite" aria-atomic="true">{announcement}</div>
    </div>
  );
}

export default function App() {
  const [index, setIndex] = useState<CatalogueIndex | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    loadCatalogue(controller.signal)
      .then(setIndex)
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setError(reason instanceof Error ? reason.message : "Unknown catalogue error");
      });
    return () => controller.abort();
  }, [attempt]);

  if (error) return <ErrorScreen message={error} onRetry={() => setAttempt((value) => value + 1)} />;
  if (!index) return <LoadingScreen />;
  return <BuildEditor index={index} />;
}
