import { useEffect, useState } from "react";
import { get } from "../api/client";
import type { ConfigResponse } from "../api/types";

let cache: ConfigResponse | null = null;
let pending: Promise<ConfigResponse> | null = null;
const listeners = new Set<(c: ConfigResponse) => void>();

// While the API is not up yet, try again on this period.
const RETRY_MS = 3000;

async function load(): Promise<ConfigResponse> {
  if (cache) return cache;
  if (!pending) {
    pending = get<ConfigResponse>("/api/config")
      .then((c) => {
        cache = c;
        listeners.forEach((l) => l(c));
        return c;
      })
      .catch((e) => {
        // Forget the failure so the next call asks the API again.
        pending = null;
        throw e;
      });
  }
  return pending;
}

/** Update the cached config after a runtime switch, so every page sees it without a reload. */
export function patchConfig(update: Partial<ConfigResponse>): void {
  if (!cache) return;
  cache = { ...cache, ...update };
  const next = cache;
  listeners.forEach((l) => l(next));
}

export function useConfig(): ConfigResponse | null {
  const [config, setConfig] = useState<ConfigResponse | null>(cache);
  useEffect(() => {
    listeners.add(setConfig);
    let timer: ReturnType<typeof setTimeout> | undefined;
    const attempt = () => {
      if (cache) return setConfig(cache);
      load()
        .then(setConfig)
        .catch(() => {
          // The page renders without the server defaults meanwhile.
          timer = setTimeout(attempt, RETRY_MS);
        });
    };
    if (!config) attempt();
    return () => {
      listeners.delete(setConfig);
      if (timer) clearTimeout(timer);
    };
  }, [config]);
  return config;
}
