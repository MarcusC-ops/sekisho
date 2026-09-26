"use client";

import type { ReactNode } from "react";
import { Icon, type IconName } from "@/components/ui/Icon";
import { Meter } from "@/components/ui/Meter";
import { describeError } from "@/lib/errors";
import { formatDuration, formatInt, formatUsd } from "@/lib/format";
import { useMetrics } from "@/lib/hooks";
import styles from "./live.module.css";

function Kpi({
  label,
  value,
  sub,
  tone,
  icon,
  title,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: "allow" | "hold" | "block";
  icon?: IconName;
  title?: string;
}) {
  return (
    <div className={styles.kpi} data-tone={tone} title={title}>
      <span className={styles.kpiLabel}>
        {icon ? <Icon name={icon} size={17} strokeWidth={2.4} /> : null}
        {label}
      </span>
      <span className={styles.kpiValue}>{value}</span>
      {sub ? <span className={styles.kpiSub}>{sub}</span> : null}
    </div>
  );
}

/** KPI strip from GET /v1/metrics, kept live by `metrics.updated` events. */
export function KpiStrip() {
  const { data: m, error } = useMetrics();
  const window = m?.window === "since_reset" ? "since reset" : m?.window;
  const used = m?.intercepta_calls_used ?? null;
  const quota = m?.intercepta_quota ?? null;

  return (
    <>
      <section className={styles.kpis} aria-label="Key figures">
        <Kpi label="Screened" value={formatInt(m?.screened)} sub={window ? `${formatUsd(m?.value_screened_usd)} ${window}` : "—"} />
        <Kpi label="Allowed" icon="allow" tone="allow" value={formatInt(m?.allow)} sub="policy permits signing" />
        <Kpi label="Held" icon="hold" tone="hold" value={formatInt(m?.hold)} sub="signing paused" />
        <Kpi label="Blocked" icon="block" tone="block" value={formatInt(m?.block)} sub="policy refuses signing" />
        <Kpi
          label="Held request amount"
          value={formatUsd(m?.value_held_usd)}
          sub={m ? `Refused requests: ${formatUsd(m.value_blocked_usd)}` : "Request amounts, not losses prevented"}
          title="Amounts attached to HOLD and BLOCK decisions. Not confirmed escrow balances or proven losses prevented."
        />
        <Kpi
          label="p50 decision time"
          value={formatDuration(m?.latency_ms_p50)}
          sub={m ? `p95 ${formatDuration(m.latency_ms_p95)}` : "—"}
          title="Median time from request to verdict"
        />
        <Kpi
          label="Intercepta calls"
          value={
            <>
              {formatInt(used)}
              <span className={styles.kpiValueUnit}> / {formatInt(quota)}</span>
            </>
          }
          sub={
            used !== null && quota ? (
              <span className={styles.kpiMeter} style={{ display: "block" }}>
                <Meter
                  value={used}
                  max={quota}
                  label={`Intercepta calls used: ${used} of ${quota}`}
                  fill={used / quota >= 0.8 ? "var(--state-warn)" : undefined}
                />
              </span>
            ) : (
              "quota"
            )
          }
          title="Hackathon key quota"
        />
      </section>
      {error && !m ? <p className={styles.kpiError}>Metrics unavailable: {describeError(error).message}</p> : null}
    </>
  );
}
