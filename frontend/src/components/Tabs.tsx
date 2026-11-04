import { useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { SlideIndicator } from "./SlideIndicator";

export interface TabItem<K extends string> {
  key: K;
  label: ReactNode;
  /** Small figure after the label (runs, models...); omitted when undefined. */
  count?: number;
}

interface Props<K extends string> {
  items: TabItem<K>[];
  value: K;
  onChange: (key: K) => void;
  /** Accessible name of the tab list. */
  label: string;
  /** Prefix of the tab and panel ids, unique on the page. */
  idBase: string;
}

/** Props of the panel that shows the active tab's content. */
export function tabPanelProps(idBase: string, key: string) {
  return {
    role: "tabpanel" as const,
    id: `${idBase}-panel-${key}`,
    "aria-labelledby": `${idBase}-tab-${key}`,
    tabIndex: 0,
  };
}

/**
 * Underline tabs (WAI-ARIA tablist, automatic activation): arrow keys,
 * Home and End move between tabs. The indicator slides on a click and jumps
 * on a key press, so keyboard navigation never waits for an animation.
 */
export function Tabs<K extends string>({ items, value, onChange, label, idBase }: Props<K>) {
  const listRef = useRef<HTMLDivElement>(null);
  const [instant, setInstant] = useState(false);

  const select = (key: K, fromKeyboard: boolean) => {
    setInstant(fromKeyboard);
    onChange(key);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const index = items.findIndex((item) => item.key === value);
    const last = items.length - 1;
    const next =
      event.key === "ArrowRight"
        ? (index + 1) % items.length
        : event.key === "ArrowLeft"
        ? (index - 1 + items.length) % items.length
        : event.key === "Home"
        ? 0
        : event.key === "End"
        ? last
        : null;
    if (next === null) return;
    event.preventDefault();
    select(items[next].key, true);
    listRef.current?.querySelector<HTMLElement>(`#${idBase}-tab-${items[next].key}`)?.focus();
  };

  return (
    <div
      ref={listRef}
      className="tablist"
      role="tablist"
      aria-label={label}
      data-instant={instant || undefined}
      onKeyDown={onKeyDown}
    >
      <SlideIndicator activeKey={value} variant="underline" />
      {items.map((item) => {
        const active = item.key === value;
        return (
          <button
            key={item.key}
            type="button"
            role="tab"
            id={`${idBase}-tab-${item.key}`}
            aria-selected={active}
            aria-controls={`${idBase}-panel-${item.key}`}
            tabIndex={active ? 0 : -1}
            data-active={active}
            onClick={() => select(item.key, false)}
          >
            {item.label}
            {item.count !== undefined ? <span className="tab-count">{item.count}</span> : null}
          </button>
        );
      })}
    </div>
  );
}
