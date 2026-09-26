"use client";

import { useCallback, useSyncExternalStore } from "react";

/** A per-viewer boolean preference in localStorage (a convenience only; safe when storage is blocked). */
const listeners = new Set<() => void>();

function read(key: string, fallback: boolean): boolean {
  try {
    const value = window.localStorage.getItem(key);
    return value === null ? fallback : value === "1";
  } catch {
    return fallback;
  }
}

export function usePersistentFlag(key: string, fallback: boolean): [boolean, (next: boolean) => void] {
  const value = useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => read(key, fallback),
    () => fallback,
  );
  const set = useCallback(
    (next: boolean) => {
      try {
        window.localStorage.setItem(key, next ? "1" : "0");
      } catch {
        // Storage blocked (private window): the preference just won't persist.
      }
      listeners.forEach((l) => l());
    },
    [key],
  );
  return [value, set];
}
