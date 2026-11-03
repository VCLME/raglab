import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";

export interface ApiState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

export function useApiAction<TArgs extends unknown[], T>(
  fn: (...args: TArgs) => Promise<T>
) {
  const [state, setState] = useState<ApiState<T>>({
    data: null,
    loading: false,
    error: null,
  });
  const mounted = useRef(true);
  useEffect(() => {
    // StrictMode mounts, unmounts and remounts in dev: set the flag on every
    // mount, or it stays false and results are dropped (stuck `loading`).
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const run = useCallback(
    async (...args: TArgs) => {
      setState({ data: null, loading: true, error: null });
      try {
        const data = await fn(...args);
        if (mounted.current) setState({ data, loading: false, error: null });
        return data;
      } catch (e) {
        const message =
          e instanceof ApiError
            ? e.message
            : e instanceof Error
            ? e.message
            : "Erreur inconnue";
        if (mounted.current) setState({ data: null, loading: false, error: message });
        throw e;
      }
    },
    [fn]
  );

  const reset = useCallback(
    () => setState({ data: null, loading: false, error: null }),
    []
  );

  return { ...state, run, reset };
}

export interface LoadOptions {
  /**
   * Retry every `retryMs` while the call fails, e.g. when the UI is up before
   * the API: the page fills itself once the API answers, no reload needed.
   */
  retryMs?: number;
}

export function useApiLoad<T>(
  fn: () => Promise<T>,
  deps: unknown[] = [],
  options: LoadOptions = {}
): ApiState<T> & { refresh: () => void } {
  const [state, setState] = useState<ApiState<T>>({
    data: null,
    loading: true,
    error: null,
  });
  // Ignores the answer of a superseded call (deps changed meanwhile).
  const generation = useRef(0);
  const refresh = useCallback(() => {
    const call = ++generation.current;
    setState((s) => ({ ...s, loading: true, error: null }));
    fn()
      .then((data) => {
        if (call === generation.current) setState({ data, loading: false, error: null });
      })
      .catch((e) => {
        if (call !== generation.current) return;
        setState({
          data: null,
          loading: false,
          error:
            e instanceof ApiError
              ? e.message
              : e instanceof Error
              ? e.message
              : "Erreur inconnue",
        });
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => {
    refresh();
  }, [refresh]);
  const { retryMs } = options;
  useEffect(() => {
    if (!retryMs || !state.error) return;
    const id = setTimeout(refresh, retryMs);
    return () => clearTimeout(id);
  }, [retryMs, state.error, refresh]);
  return { ...state, refresh };
}
