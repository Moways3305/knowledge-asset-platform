import { useCallback } from "react";
import { useLocation, useSearchParams } from "react-router-dom";

export function queryChoice<T extends string>(
  query: URLSearchParams,
  key: string,
  choices: readonly T[],
  fallback: T,
): T {
  const value = query.get(key);
  return choices.includes(value as T) ? (value as T) : fallback;
}

export function queryPage(query: URLSearchParams): number {
  const value = Number(query.get("page"));
  return Number.isSafeInteger(value) && value > 0 ? value : 1;
}

export function queryDate(query: URLSearchParams, key: string): string {
  const value = query.get(key) ?? "";
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return "";
  const timestamp = Date.parse(`${value}T00:00:00Z`);
  return Number.isFinite(timestamp) && new Date(timestamp).toISOString().slice(0, 10) === value
    ? value
    : "";
}

// Applied filters live in the URL; editable search text stays local until submit.
// Update all fields from one user action together so browser history is atomic.
export function useKnowledgeQueryState() {
  const location = useLocation();
  const [query, setSearchParams] = useSearchParams();
  const updateQuery = useCallback(
    (
      patch: Record<string, string | number | boolean | null>,
      options: { resetPage?: boolean; replace?: boolean } = {},
    ) => {
      const next = new URLSearchParams(query);
      if (options.resetPage !== false) next.delete("page");
      for (const [key, value] of Object.entries(patch)) {
        if (value === null || value === "" || value === false) next.delete(key);
        else next.set(key, value === true ? "1" : String(value));
      }
      if (next.toString() !== query.toString()) {
        setSearchParams(next, { replace: options.replace, state: location.state });
      }
    },
    [query, setSearchParams, location.state],
  );
  return { query, updateQuery, currentPath: `${location.pathname}${location.search}` };
}
