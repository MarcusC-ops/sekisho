"use client";

import type { ReactNode } from "react";
import { SWRConfig } from "swr";
import { GateError } from "@/lib/errors";
import { StreamProvider } from "@/lib/stream";

export function Providers({ children }: { children: ReactNode }) {
  return (
    <SWRConfig
      value={{
        dedupingInterval: 1500,
        // The stream keeps data fresh; retry only errors worth retrying (not 4xx).
        onErrorRetry: (error, _key, _config, revalidate, { retryCount }) => {
          if (error instanceof GateError && error.status >= 400 && error.status < 500) return;
          if (retryCount >= 10) return;
          setTimeout(() => void revalidate({ retryCount }), Math.min(15_000, 1000 * 2 ** retryCount));
        },
      }}
    >
      <StreamProvider>{children}</StreamProvider>
    </SWRConfig>
  );
}
