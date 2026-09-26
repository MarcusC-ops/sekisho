import styles from "./ui.module.css";

/** A single ratio against a limit. `ticks` mark thresholds (e.g. policy lines). */
export function Meter({
  value,
  max = 100,
  fill,
  label,
  ticks = [],
}: {
  value: number;
  max?: number;
  fill?: string;
  label: string;
  ticks?: { at: number; label: string }[];
}) {
  const pct = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  return (
    <div
      className={styles.meter}
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={max}
      aria-valuenow={Math.round(value * 10) / 10}
    >
      <div className={styles.meterFill} style={{ width: `${pct}%`, ["--meter-fill" as string]: fill }} />
      {ticks.map((t) => (
        <span key={t.at} className={styles.meterTick} style={{ left: `calc(${(t.at / max) * 100}% - 1px)` }} title={t.label} />
      ))}
    </div>
  );
}
