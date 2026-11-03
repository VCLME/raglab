import {
  Children,
  createContext,
  isValidElement,
  useCallback,
  useContext,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactElement,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { CheckIcon, ChevronDownIcon } from "./Icon";

/** Label id of the surrounding FieldRow, so the trigger is named by its label. */
export const FieldLabelContext = createContext<string | null>(null);

/** Same shape as the native change event the pages already read (`e.target.value`). */
export interface SelectChangeEvent {
  target: { value: string };
}

interface Props {
  value: string;
  onChange?: (event: SelectChangeEvent) => void;
  /** `<option>` and `<optgroup>` children, exactly as for a native `<select>`. */
  children: ReactNode;
  disabled?: boolean;
  title?: string;
  id?: string;
  className?: string;
  style?: CSSProperties;
  "aria-label"?: string;
  /** Trigger size: `sm` for toolbars and the composer. */
  size?: "md" | "sm";
}

interface Item {
  value: string;
  label: ReactNode;
  text: string;
  disabled: boolean;
  group: string | null;
}

function textOf(node: ReactNode): string {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (isValidElement(node)) return textOf((node.props as { children?: ReactNode }).children);
  return "";
}

type OptionProps = { value?: string | number; children?: ReactNode; disabled?: boolean; label?: string };

function collect(children: ReactNode, group: string | null, out: Item[]) {
  Children.forEach(children, (child) => {
    if (!isValidElement(child)) return;
    const element = child as ReactElement<OptionProps & { children?: ReactNode }>;
    if (element.type === "optgroup") {
      collect(element.props.children, element.props.label ?? "", out);
    } else if (element.type === "option") {
      const label = element.props.children;
      const text = textOf(label);
      out.push({
        value: element.props.value != null ? String(element.props.value) : text,
        label,
        text,
        disabled: !!element.props.disabled,
        group,
      });
    } else if (element.props.children) {
      // Fragments wrapping options.
      collect(element.props.children, group, out);
    }
  });
}

const TYPEAHEAD_RESET_MS = 500;
const POPOVER_GAP = 4;
const POPOVER_MAX = 320;

interface Position {
  left: number;
  width: number;
  top?: number;
  bottom?: number;
  maxHeight: number;
}

/**
 * Drop-in replacement for `<select>`: a select-only combobox (WAI-ARIA APG)
 * whose listbox is rendered in a portal, so cards and scroll containers never
 * clip it. Focus stays on the trigger; the active option is announced through
 * `aria-activedescendant`.
 */
export function Select({
  value,
  onChange,
  children,
  disabled,
  title,
  id,
  className,
  style,
  size = "md",
  "aria-label": ariaLabel,
}: Props) {
  const items = useMemo(() => {
    const out: Item[] = [];
    collect(children, null, out);
    return out;
  }, [children]);
  const baseId = useId();
  const listId = `${baseId}-list`;
  const valueId = `${baseId}-value`;
  const fieldLabel = useContext(FieldLabelContext);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const listRef = useRef<HTMLUListElement | null>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [position, setPosition] = useState<Position | null>(null);
  const typeahead = useRef({ text: "", at: 0 });

  const selectedIndex = items.findIndex((item) => item.value === value);
  // Like a native select, an unknown value shows the first option.
  const shown = items[selectedIndex >= 0 ? selectedIndex : 0];

  const place = useCallback(() => {
    const trigger = triggerRef.current;
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    const below = window.innerHeight - rect.bottom - POPOVER_GAP - 8;
    const above = rect.top - POPOVER_GAP - 8;
    const width = Math.min(Math.max(rect.width, 180), window.innerWidth - 16);
    const left = Math.max(8, Math.min(rect.left, window.innerWidth - width - 8));
    if (below < 200 && above > below) {
      setPosition({ left, width, bottom: window.innerHeight - rect.top + POPOVER_GAP, maxHeight: Math.min(POPOVER_MAX, above) });
    } else {
      setPosition({ left, width, top: rect.bottom + POPOVER_GAP, maxHeight: Math.min(POPOVER_MAX, below) });
    }
  }, []);

  const enabledFrom = (start: number, step: 1 | -1): number => {
    for (let i = start; i >= 0 && i < items.length; i += step) {
      if (!items[i].disabled) return i;
    }
    return -1;
  };

  const openList = (focus?: number) => {
    if (disabled || items.length === 0) return;
    place();
    setOpen(true);
    setActive(focus ?? (selectedIndex >= 0 ? selectedIndex : enabledFrom(0, 1)));
  };

  const close = (refocus = true) => {
    setOpen(false);
    setActive(-1);
    if (refocus) triggerRef.current?.focus();
  };

  const choose = (index: number) => {
    const item = items[index];
    if (!item || item.disabled) return;
    if (item.value !== value) onChange?.({ target: { value: item.value } });
    close();
  };

  useLayoutEffect(() => {
    if (!open) return;
    const onMove = () => place();
    window.addEventListener("resize", onMove);
    window.addEventListener("scroll", onMove, true);
    return () => {
      window.removeEventListener("resize", onMove);
      window.removeEventListener("scroll", onMove, true);
    };
  }, [open, place]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const target = e.target as Node;
      if (triggerRef.current?.contains(target) || listRef.current?.contains(target)) return;
      close(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  // Keep the active option in view while navigating with the keyboard.
  useEffect(() => {
    if (!open || active < 0) return;
    listRef.current?.querySelector(`[data-index="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [open, active]);

  const matchTypeahead = (key: string): number => {
    const now = Date.now();
    const state = typeahead.current;
    state.text = now - state.at > TYPEAHEAD_RESET_MS ? key : state.text + key;
    state.at = now;
    const query = state.text.toLowerCase();
    const from = open ? active : selectedIndex;
    // One letter (or the same letter repeated) cycles through the options
    // starting with it; a longer prefix may keep the current option.
    const cycling = query.split("").every((c) => c === query[0]);
    const order = items.map((_, i) => (from + 1 + i) % items.length);
    const candidates = cycling ? order : [Math.max(from, 0), ...order];
    const prefix = cycling ? query[0] : query;
    return candidates.find((i) => !items[i].disabled && items[i].text.toLowerCase().startsWith(prefix)) ?? -1;
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>) => {
    if (disabled) return;
    const key = e.key;
    if (!open) {
      if (["ArrowDown", "ArrowUp", "Enter", " "].includes(key)) {
        e.preventDefault();
        openList();
      } else if (key === "Home" || key === "End") {
        e.preventDefault();
        openList(key === "Home" ? enabledFrom(0, 1) : enabledFrom(items.length - 1, -1));
      } else if (key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
        const match = matchTypeahead(key);
        openList(match >= 0 ? match : undefined);
      }
      return;
    }
    switch (key) {
      case "ArrowDown": {
        e.preventDefault();
        const next = enabledFrom(active + 1, 1);
        if (next >= 0) setActive(next);
        break;
      }
      case "ArrowUp": {
        e.preventDefault();
        if (e.altKey) {
          choose(active);
          break;
        }
        const prev = enabledFrom(active - 1, -1);
        if (prev >= 0) setActive(prev);
        break;
      }
      case "Home":
      case "PageUp":
        e.preventDefault();
        setActive(enabledFrom(0, 1));
        break;
      case "End":
      case "PageDown":
        e.preventDefault();
        setActive(enabledFrom(items.length - 1, -1));
        break;
      case "Enter":
      case " ":
        e.preventDefault();
        choose(active);
        break;
      case "Escape":
        e.preventDefault();
        close();
        break;
      case "Tab":
        // APG: Tab commits the active option, then focus moves on.
        if (active >= 0) choose(active);
        setOpen(false);
        break;
      default:
        if (key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
          const match = matchTypeahead(key);
          if (match >= 0) setActive(match);
        }
    }
  };

  const optionId = (index: number) => `${baseId}-opt-${index}`;
  const labelledBy = !ariaLabel && fieldLabel ? `${fieldLabel} ${valueId}` : undefined;

  const renderOption = (item: Item, index: number) => (
    <li
      key={`${index}-${item.value}`}
      id={optionId(index)}
      data-index={index}
      role="option"
      aria-selected={index === selectedIndex}
      aria-disabled={item.disabled || undefined}
      className={`select-option${index === active ? " active" : ""}${index === selectedIndex ? " selected" : ""}`}
      onMouseEnter={() => !item.disabled && setActive(index)}
      onMouseDown={(e) => e.preventDefault()}
      onClick={() => choose(index)}
    >
      <span className="select-option-label">{item.label}</span>
      {index === selectedIndex ? <CheckIcon size={14} className="select-check" /> : null}
    </li>
  );

  const grouped: ReactNode[] = [];
  items.forEach((item, index) => {
    const previous = items[index - 1];
    if (item.group !== null && previous?.group !== item.group) {
      const groupId = `${baseId}-g-${index}`;
      const members: ReactNode[] = [];
      for (let i = index; i < items.length && items[i].group === item.group; i++) members.push(renderOption(items[i], i));
      grouped.push(
        <li key={groupId} role="presentation" className="select-group">
          <div id={groupId} className="select-group-label" role="presentation">
            {item.group}
          </div>
          <ul role="group" aria-labelledby={groupId}>
            {members}
          </ul>
        </li>
      );
    } else if (item.group === null) {
      grouped.push(renderOption(item, index));
    }
  });

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        id={id}
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listId}
        aria-activedescendant={open && active >= 0 ? optionId(active) : undefined}
        aria-label={ariaLabel}
        aria-labelledby={labelledBy}
        disabled={disabled}
        title={title}
        style={style}
        className={`select-trigger${size === "sm" ? " sm" : ""}${open ? " open" : ""}${className ? ` ${className}` : ""}`}
        data-value={value}
        onClick={() => (open ? close() : openList())}
        onKeyDown={onKeyDown}
      >
        <span id={valueId} className="select-value">
          {shown ? shown.label : ""}
        </span>
        <ChevronDownIcon size={16} className="select-chevron" />
      </button>
      {open && position
        ? createPortal(
            <ul
              ref={listRef}
              id={listId}
              role="listbox"
              aria-labelledby={!ariaLabel && fieldLabel ? fieldLabel : undefined}
              aria-label={ariaLabel}
              className="select-popover"
              style={{
                left: position.left,
                minWidth: position.width,
                maxWidth: Math.max(position.width, Math.min(480, window.innerWidth - position.left - 8)),
                top: position.top,
                bottom: position.bottom,
                maxHeight: position.maxHeight,
              }}
            >
              {grouped}
            </ul>,
            document.body
          )
        : null}
    </>
  );
}
