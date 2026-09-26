"use client";

/**
 * One EventSource on GET /v1/stream for the whole console, with reconnect and backoff.
 * In fixture mode it subscribes to the in-browser simulation instead.
 */
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { useSWRConfig } from "swr";
import { applyStreamEvent, revalidateAll } from "./cache";
import { GATE_URL, USE_FIXTURES } from "./config";
import type { StreamEventMap, StreamEventName } from "./types";

export type StreamStatus = "connecting" | "live" | "reconnecting" | "fixtures";

interface StreamState {
  status: StreamStatus;
  attempts: number;
}

const EVENT_NAMES: StreamEventName[] = ["case.created", "case.updated", "chain.event", "metrics.updated"];
const MAX_BACKOFF_MS = 15_000;

const StreamContext = createContext<StreamState>({ status: USE_FIXTURES ? "fixtures" : "connecting", attempts: 0 });

export function useStreamStatus(): StreamState {
  return useContext(StreamContext);
}

export function StreamProvider({ children }: { children: ReactNode }) {
  const { mutate, cache } = useSWRConfig();
  const [state, setState] = useState<StreamState>({ status: USE_FIXTURES ? "fixtures" : "connecting", attempts: 0 });

  useEffect(() => {
    const handle = <K extends StreamEventName>(event: K, data: StreamEventMap[K]) =>
      applyStreamEvent(mutate, cache, event, data);

    if (USE_FIXTURES) {
      let unsubscribe = () => {};
      let cancelled = false;
      void import("./fixtures/server").then((fixtures) => {
        if (!cancelled) unsubscribe = fixtures.subscribeFixtureStream(handle);
      });
      return () => {
        cancelled = true;
        unsubscribe();
      };
    }

    let source: EventSource | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    let attempts = 0;
    let everOpened = false;
    let closed = false;

    const connect = () => {
      source = new EventSource(`${GATE_URL}/v1/stream`);
      source.onopen = () => {
        if (everOpened) revalidateAll(mutate); // catch up on anything missed while offline
        everOpened = true;
        attempts = 0;
        setState({ status: "live", attempts: 0 });
      };
      for (const name of EVENT_NAMES) {
        source.addEventListener(name, (message) => {
          try {
            handle(name, JSON.parse((message as MessageEvent<string>).data));
          } catch {
            // A malformed event must never break the stream.
          }
        });
      }
      source.onerror = () => {
        source?.close();
        if (closed) return;
        const delay = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** attempts) * (0.8 + Math.random() * 0.4);
        attempts += 1;
        setState({ status: "reconnecting", attempts });
        retryTimer = setTimeout(connect, delay);
      };
    };

    connect();
    return () => {
      closed = true;
      if (retryTimer) clearTimeout(retryTimer);
      source?.close();
    };
  }, [mutate, cache]);

  return <StreamContext.Provider value={state}>{children}</StreamContext.Provider>;
}
