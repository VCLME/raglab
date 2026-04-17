import { useCallback, useEffect, useState } from "react";

export function useLocalHistory<T>(key: string, limit: number = 20) {
  const [items, setItems] = useState<T[]>(() => {
    try {
      const raw = localStorage.getItem(key);
      return raw ? (JSON.parse(raw) as T[]) : [];
    } catch {
      return [];
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(items));
    } catch {
      /* quota or privacy mode — silently ignore */
    }
  }, [key, items]);

  const push = useCallback(
    (item: T) => {
      setItems((prev) => [item, ...prev].slice(0, limit));
    },
    [limit]
  );

  const clear = useCallback(() => setItems([]), []);

  return { items, push, clear };
}
