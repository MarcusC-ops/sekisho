"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { USE_FIXTURES } from "@/lib/config";
import { useHealth, useHoldCases } from "@/lib/hooks";
import { useStreamStatus } from "@/lib/stream";
import { awaitingOfficer } from "@/lib/cases";
import { Icon } from "@/components/ui/Icon";
import styles from "./shell.module.css";
import { OperatorSession } from "./OperatorSession";

const NAV = [
  { href: "/", label: "Live decisions" },
  { href: "/review", label: "Hold queue" },
  { href: "/audit", label: "Audit log" },
  { href: "/treasury", label: "Treasury" },
  { href: "/policy", label: "Policy" },
  { href: "/integrate", label: "Integrate" },
];

function isActive(pathname: string, href: string) {
  if (href === "/") return pathname === "/" || pathname.startsWith("/cases/");
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function FixtureBanner() {
  return (
    <div className={styles.fixtureBanner} role="note" aria-label="Fixture data notice">
      <div className={styles.fixtureInner}>
        <span className={styles.fixtureLabel}>
          <Icon name="alert" size={16} />
          FIXTURE DATA
        </span>
        <span className={styles.fixtureText}>
          Synthetic sample cases for console development. Not live screening results or real Intercepta output.
        </span>
        <span className={styles.fixtureEnv}>NEXT_PUBLIC_USE_FIXTURES=true</span>
      </div>
    </div>
  );
}

function StreamIndicator() {
  const { status, attempts } = useStreamStatus();
  const label =
    status === "live"
      ? "Live"
      : status === "reconnecting"
        ? "Reconnecting"
        : status === "fixtures"
          ? "Simulated stream"
          : "Connecting";
  const title =
    status === "live"
      ? "Connected to the gate's event stream (/v1/stream)"
      : status === "reconnecting"
        ? `Lost the event stream; retrying with backoff (attempt ${attempts})`
        : status === "fixtures"
          ? "Fixture mode: events are simulated in the browser"
          : "Opening the event stream";
  return (
    <span className={styles.stream} data-status={status} title={title} role="status" aria-live="polite">
      <span className={styles.dot} aria-hidden="true" />
      {label}
    </span>
  );
}

function GateHealth() {
  const { data, error } = useHealth();
  const state = error ? "down" : !data ? "loading" : data.status === "ok" ? "ok" : "degraded";
  const label = state === "down" ? "Gate unreachable" : state === "loading" ? "Gate" : state === "ok" ? "Gate ok" : "Gate degraded";
  return (
    <details className={styles.health}>
      <summary className={styles.healthSummary} data-state={state} aria-label={`${label}. Show gate health`}>
        <span className={styles.dot} aria-hidden="true" />
        <span className={styles.healthLabel}>{label}</span>
        <Icon name="chevronDown" size={14} />
      </summary>
      <div className={styles.healthPanel}>
        {error ? (
          <p>{error instanceof Error ? error.message : String(error)}</p>
        ) : !data ? (
          <p>Checking the gate…</p>
        ) : (
          <>
            <ul className={styles.healthList}>
              {Object.entries(data.checks).map(([name, check]) => (
                <li key={name} className={styles.healthRow} data-ok={check.ok}>
                  <Icon name={check.ok ? "allow" : "error"} size={18} />
                  <span>
                    <span className={styles.healthName}>{name}</span>
                    <br />
                    <span className={styles.healthDetail}>{check.detail}</span>
                  </span>
                </li>
              ))}
            </ul>
            <div className={styles.healthMeta}>
              <span>Policy v{data.policy.version}</span>
              <span className="mono" title={data.policy.id}>
                {data.policy.id.slice(0, 10)}…
              </span>
              {data.demo_mode ? <span>· DEMO_MODE on</span> : null}
            </div>
          </>
        )}
      </div>
    </details>
  );
}

function HoldBadge() {
  const { data } = useHoldCases();
  const count = data?.items.filter(awaitingOfficer).length ?? 0;
  if (!count) return null;
  return (
    <span className={styles.badge} data-tone="hold" aria-label={`${count} awaiting an officer`}>
      {count}
    </span>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "/";
  return (
    <>
      <div className={styles.sticky}>
        {USE_FIXTURES ? <FixtureBanner /> : null}
        <header className={styles.topbar}>
          <div className={styles.topbarInner}>
            <Link href="/" className={styles.brand} aria-label="Sekisho compliance console, live decisions">
              <span className={styles.brandSeal} aria-hidden="true" lang="ja">
                関所
              </span>
              <span className={styles.wordmark}>Sekisho</span>
              <span className={styles.product}>Compliance Console</span>
            </Link>
            <nav className={styles.nav} aria-label="Console">
              {NAV.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className={styles.navLink}
                  aria-current={isActive(pathname, item.href) ? "page" : undefined}
                >
                  {item.label}
                  {item.href === "/review" ? <HoldBadge /> : null}
                </Link>
              ))}
            </nav>
            <div className={styles.status}>
              {!USE_FIXTURES ? <OperatorSession /> : null}
              <GateHealth />
              <StreamIndicator />
            </div>
          </div>
        </header>
      </div>
      <main className={styles.main} id="main">
        {children}
      </main>
    </>
  );
}
