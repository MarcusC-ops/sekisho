"use client";

/**
 * Tiny external stores shared across the console:
 * - which cases just arrived over the stream (so their cards animate in once),
 * - a polite screen-reader announcement for new decisions,
 * - a shared clock for relative times ("4 min ago") without calling Date.now() in render.
 */
import { useSyncExternalStore } from "react";

// ---------- fresh cases

const FRESH_FOR_MS = 8000;
const fresh = new Map<string, number>();

export function markFresh(caseId: string) {
  const now = Date.now();
  fresh.set(caseId, now);
  for (const [id, at] of fresh) if (now - at > 60_000) fresh.delete(id);
}

/** True for a case that arrived over the stream in the last few seconds. */
export function isFresh(caseId: string): boolean {
  const at = fresh.get(caseId);
  return at !== undefined && Date.now() - at < FRESH_FOR_MS;
}

// ---------- announcements (aria-live)

let announcement = "";
const announcementListeners = new Set<() => void>();

export function announce(text: string) {
  announcement = text;
  announcementListeners.forEach((l) => l());
}

export function useAnnouncement(): string {
  return useSyncExternalStore(
    (listener) => {
      announcementListeners.add(listener);
      return () => announcementListeners.delete(listener);
    },
    () => announcement,
    () => "",
  );
}

// ---------- shared clock

let nowValue = 0;
const clockListeners = new Set<() => void>();
let clockTimer: ReturnType<typeof setInterval> | null = null;

function subscribeClock(listener: () => void) {
  clockListeners.add(listener);
  nowValue = Date.now();
  if (!clockTimer) {
    clockTimer = setInterval(() => {
      nowValue = Date.now();
      clockListeners.forEach((l) => l());
    }, 5000);
  }
  return () => {
    clockListeners.delete(listener);
    if (!clockListeners.size && clockTimer) {
      clearInterval(clockTimer);
      clockTimer = null;
    }
  };
}

/** Current time in ms, refreshed every 5 s. 0 during server rendering (render absolute times then). */
export function useNow(): number {
  return useSyncExternalStore(
    subscribeClock,
    () => nowValue,
    () => 0,
  );
}
