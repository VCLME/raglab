import { useLayoutEffect, useRef, useState } from "react";

interface Props {
  /** Changes when the active segment changes (the value, the route...). */
  activeKey: unknown;
  /**
   * "pill": a raised pill behind equal-width segments (moves with translateX).
   * "underline": the 2 px bar under tabs of any width (translateX + scaleX of a
   * 1 px bar, invisible distortion at that height).
   */
  variant: "pill" | "underline";
}

interface Box {
  x: number;
  w: number;
}

/**
 * Active-segment indicator that slides from one segment to the next
 * (transform only, ~200 ms ease-out; `prefers-reduced-motion` turns the
 * transition off through the global rule). Place it as the first child of a
 * positioned segmented control or tab list whose active child carries
 * `data-active="true"`. The first position is set without animation, so
 * nothing slides in on page load.
 */
export function SlideIndicator({ activeKey, variant }: Props) {
  const ref = useRef<HTMLSpanElement | null>(null);
  const [box, setBox] = useState<Box | null>(null);
  const [animate, setAnimate] = useState(false);

  useLayoutEffect(() => {
    // Its own parent: a ref on the container is not attached yet when a
    // child's layout effect first runs.
    const container = ref.current?.parentElement;
    if (!container) return;
    const measure = () => {
      const active = container.querySelector<HTMLElement>('[data-active="true"]');
      setBox(active ? { x: active.offsetLeft, w: active.offsetWidth } : null);
    };
    measure();
    // Labels hidden on phones, the web font arriving, a bold active tab, a
    // resized window: segments change size without the container always
    // doing so, so each one is observed.
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(measure) : null;
    observer?.observe(container);
    Array.from(container.children)
      .filter((child) => child !== ref.current)
      .forEach((child) => observer?.observe(child));
    let live = true;
    document.fonts?.ready.then(() => live && measure());
    return () => {
      live = false;
      observer?.disconnect();
    };
  }, [activeKey]);

  // Enable the transition only after the first position has been painted.
  useLayoutEffect(() => {
    if (!box || animate) return;
    const id = requestAnimationFrame(() => setAnimate(true));
    return () => cancelAnimationFrame(id);
  }, [box, animate]);

  const style = !box
    ? { visibility: "hidden" as const }
    : variant === "pill"
    ? { width: box.w, transform: `translateX(${box.x}px)` }
    : { transform: `translateX(${box.x}px) scaleX(${box.w})` };
  return (
    <span
      ref={ref}
      className={`slide-indicator ${variant}${animate ? " animate" : ""}`}
      style={style}
      aria-hidden="true"
    />
  );
}
