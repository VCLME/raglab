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
  useEffect(
    () => () => {
      mounted.current = false;
    },
    []
  );

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

export function useApiLoad<T>(
  fn: () => Promise<T>,
  deps: unknown[] = []
): ApiState<T> & { refresh: () => void } {
  const [state, setState] = useState<ApiState<T>>({
    data: null,
    loading: true,
    error: null,
  });
  const refresh = useCallback(() => {
    setState((s) => ({ ...s, loading: true, error: null }));
    fn()
      .then((data) => setState({ data, loading: false, error: null }))
      .catch((e) =>
        setState({
          data: null,
          loading: false,
          error:
            e instanceof ApiError
              ? e.message
              : e instanceof Error
              ? e.message
              : "Erreur inconnue",
        })
      );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => {
    refresh();
  }, [refresh]);
  return { ...state, refresh };
}
