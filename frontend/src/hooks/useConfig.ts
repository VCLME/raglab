import { useEffect, useState } from "react";
import { get } from "../api/client";
import type { ConfigResponse } from "../api/types";

let cache: ConfigResponse | null = null;
let pending: Promise<ConfigResponse> | null = null;
const listeners = new Set<(c: ConfigResponse) => void>();

async function load(): Promise<ConfigResponse> {
  if (cache) return cache;
  if (!pending) {
    pending = get<ConfigResponse>("/api/config").then((c) => {
      cache = c;
      listeners.forEach((l) => l(c));
      return c;
    });
  }
  return pending;
}

export function useConfig(): ConfigResponse | null {
  const [config, setConfig] = useState<ConfigResponse | null>(cache);
  useEffect(() => {
    if (!config) {
      load()
        .then(setConfig)
        .catch(() => {
          /* ignore — page displays without default values */
        });
    }
    listeners.add(setConfig);
    return () => {
      listeners.delete(setConfig);
    };
  }, [config]);
  return config;
}
