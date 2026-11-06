import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "./api";

export function useApi<T = any>(path: string | null, params?: Record<string, any>) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const key = JSON.stringify(params ?? {});
  const seq = useRef(0);

  const reload = useCallback(
    async (silent = false) => {
      if (!path) return;
      const current = ++seq.current;
      if (!silent) setLoading(true);
      try {
        const result = await api<T>(path, { params: JSON.parse(key) });
        if (current === seq.current) {
          setData(result);
          setError(null);
        }
      } catch (exc) {
        if (current === seq.current) setError(exc instanceof ApiError ? exc.message : "Something went wrong");
      } finally {
        if (current === seq.current) setLoading(false);
      }
    },
    [path, key],
  );

  useEffect(() => {
    reload();
  }, [reload]);

  return { data, error, loading, reload, setData };
}

export function useDebounced<T>(value: T, delay = 250): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(id);
  }, [value, delay]);
  return debounced;
}

export function useInterval(fn: () => void, ms: number | null) {
  const saved = useRef(fn);
  saved.current = fn;
  useEffect(() => {
    if (ms === null) return;
    const id = setInterval(() => saved.current(), ms);
    return () => clearInterval(id);
  }, [ms]);
}

export function useIsNarrow(width = 900) {
  const [narrow, setNarrow] = useState(() => window.innerWidth < width);
  useEffect(() => {
    const handler = () => setNarrow(window.innerWidth < width);
    window.addEventListener("resize", handler);
    return () => window.removeEventListener("resize", handler);
  }, [width]);
  return narrow;
}
