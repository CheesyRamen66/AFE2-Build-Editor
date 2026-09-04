import { Search, X } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { plainGameText } from "../data/catalogue";
import type { CatalogueRecord } from "../model/catalogue";
import { RecordVisual } from "./RecordVisual";

export interface PickerConfig {
  title: string;
  eyebrow?: string;
  records: CatalogueRecord[];
  selectedId?: string | null;
  allowEmpty?: boolean;
  emptyLabel?: string;
  onSelect: (recordId: string | null) => void;
}

interface RecordPickerProps {
  config: PickerConfig;
  onClose: () => void;
}

const PAGE_SIZE = 60;

function shouldUseWeaponSilhouette(record: CatalogueRecord): boolean {
  if (record.kind !== "weapon") return false;

  // GunIcon is the authored, textured weapon render. Keep AmmoIcon as a
  // fail-safe for records whose GunIcon could not be decoded or is explicitly
  // marked as fallback evidence (currently Mondo Heat 9000).
  return !record.icon?.path || Boolean(record.icon.fallback);
}

export function RecordPicker({ config, onClose }: RecordPickerProps) {
  const [query, setQuery] = useState("");
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const titleId = useId();
  const searchRef = useRef<HTMLInputElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    searchRef.current?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = [...dialogRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])',
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
  }, [onClose]);

  const matches = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    if (!normalized) return config.records;
    return config.records.filter((record) => {
      const haystack = `${record.displayName} ${plainGameText(record.description)}`.toLocaleLowerCase();
      return haystack.includes(normalized);
    });
  }, [config.records, query]);
  const visible = matches.slice(0, visibleCount);

  return createPortal(
    <div
      className="picker-overlay"
      data-placement="center"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        className="picker-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <header className="picker-header">
          <div>
            {config.eyebrow && <span className="eyebrow">{config.eyebrow}</span>}
            <h2 id={titleId}>{config.title}</h2>
          </div>
          <button className="icon-button" type="button" onClick={onClose} aria-label="Close picker">
            <X size={20} />
          </button>
        </header>

        <div className="picker-dialog__body">
          <label className="search-field">
            <Search size={18} aria-hidden="true" />
            <span className="sr-only">Search {config.title}</span>
            <input
              ref={searchRef}
              type="search"
              value={query}
              placeholder={`Search ${matches.length} options`}
              onChange={(event) => {
                setQuery(event.target.value);
                setVisibleCount(PAGE_SIZE);
              }}
            />
            {query && (
              <button type="button" onClick={() => setQuery("")} aria-label="Clear search">
                <X size={16} />
              </button>
            )}
          </label>

          <div
            className="picker-options"
            role="region"
            aria-label={`${config.title} options`}
          >
            {config.allowEmpty && (
              <button
                type="button"
                className={`picker-option picker-option--empty ${!config.selectedId ? "is-selected" : ""}`}
                onClick={() => config.onSelect(null)}
                aria-pressed={!config.selectedId}
              >
                <span className="picker-option__empty-mark">—</span>
                <span>
                  <strong>{config.emptyLabel ?? "None"}</strong>
                  <small>Leave this slot empty</small>
                </span>
              </button>
            )}
            {visible.map((record) => (
              <button
                type="button"
                className={`picker-option ${record.id === config.selectedId ? "is-selected" : ""}`}
                data-record-kind={record.kind}
                key={record.id}
                onClick={() => config.onSelect(record.id)}
                aria-pressed={record.id === config.selectedId}
              >
                <RecordVisual record={record} silhouette={shouldUseWeaponSilhouette(record)} />
                <span className="picker-option__copy">
                  <span className="picker-option__meta">{record.kind}</span>
                  <strong>{record.displayName}</strong>
                  <small>{plainGameText(record.description) || "No description available."}</small>
                </span>
                <span className="picker-option__check" aria-hidden="true">✓</span>
              </button>
            ))}
            {!matches.length && (
              <div className="empty-state">
                <Search size={28} aria-hidden="true" />
                <strong>No matching gear</strong>
                <span>Try a shorter or broader search.</span>
              </div>
            )}
          </div>

          {visibleCount < matches.length && (
            <button
              type="button"
              className="button button--secondary picker-more"
              onClick={() => setVisibleCount((count) => count + PAGE_SIZE)}
            >
              Show {Math.min(PAGE_SIZE, matches.length - visibleCount)} more
            </button>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
