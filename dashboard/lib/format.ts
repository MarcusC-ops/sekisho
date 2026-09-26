import { formatUnits } from "viem";
import { KNOWN_ASSETS, USDC_DECIMALS } from "./config";

/** `0x098B716B8Aaf21512996dC57EB0615e2383E2f96` → `0x098B…2F96` */
export function shortAddress(value: string | null | undefined): string {
  if (!value) return "—";
  if (value.length <= 12) return value;
  return `${value.slice(0, 6)}…${value.slice(-4)}`;
}

/** Tx hashes and bytes32 values, same shape as addresses. */
export const shortHash = shortAddress;

export function assetInfo(asset: string | null | undefined): { symbol: string; decimals: number } {
  if (!asset) return { symbol: "USDC", decimals: USDC_DECIMALS };
  return KNOWN_ASSETS[asset.toLowerCase()] ?? { symbol: shortAddress(asset), decimals: USDC_DECIMALS };
}

/** Atomic units to a display amount with at least `minFraction` decimals: "50000" → "0.05". */
export function formatTokenAmount(
  atomic: string | number | bigint | null | undefined,
  decimals: number = USDC_DECIMALS,
  minFraction = 2,
): string {
  if (atomic === null || atomic === undefined || atomic === "") return "—";
  let text: string;
  try {
    text = formatUnits(BigInt(atomic), decimals);
  } catch {
    return String(atomic);
  }
  const negative = text.startsWith("-");
  const [intPart, fracPart = ""] = (negative ? text.slice(1) : text).split(".");
  const grouped = BigInt(intPart).toLocaleString("en-US");
  const fraction = fracPart.padEnd(minFraction, "0");
  return `${negative ? "-" : ""}${grouped}${fraction ? `.${fraction}` : ""}`;
}

/** "0.05 USDC" */
export function formatAssetAmount(atomic: string, asset: string | null | undefined): string {
  const { symbol, decimals } = assetInfo(asset);
  return `${formatTokenAmount(atomic, decimals)} ${symbol}`;
}

const USD = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const USD_WHOLE = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

export function formatUsd(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  if (Math.abs(value) >= 10_000) return USD_WHOLE.format(value);
  if (value !== 0 && Math.abs(value) < 0.01) return `<${USD.format(0.01)}`;
  return USD.format(value);
}

export function formatInt(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return Math.round(value).toLocaleString("en-US");
}

/** "312 ms", "2,140 ms" */
export function formatMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return "— ms";
  return `${Math.round(ms).toLocaleString("en-US")} ms`;
}

/** "1.84 s" (or "840 ms" under a second) */
export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(ms < 10_000 ? 2 : 1)} s`;
}

export function formatPct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${value.toFixed(digits)}%`;
}

function toDate(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

const CLOCK = new Intl.DateTimeFormat("en-GB", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});
const DATE_TIME = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
  timeZoneName: "short",
});
const DATE_ONLY = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" });

/** Local wall-clock time, "19:21:33". */
export function formatClock(iso: string | null | undefined): string {
  const d = toDate(iso);
  return d ? CLOCK.format(d) : "—";
}

/** "26 Sep 2026, 19:21:33 GMT+9" */
export function formatDateTime(iso: string | null | undefined): string {
  const d = toDate(iso);
  return d ? DATE_TIME.format(d) : "—";
}

export function formatDate(value: Date | string | null | undefined): string {
  const d = value instanceof Date ? value : toDate(value);
  return d ? DATE_ONLY.format(d) : "—";
}

/** Unix seconds (number or decimal string) to a date. */
export function unixToDate(value: number | string | null | undefined): Date | null {
  if (value === null || value === undefined) return null;
  const n = Number(value);
  return Number.isFinite(n) ? new Date(n * 1000) : null;
}

/** Compact age: "45 s", "4 min", "2 h", "3 d". `now` of 0 means unknown. */
export function formatAge(iso: string | null | undefined, now: number): string {
  const d = toDate(iso);
  if (!d || !now) return "—";
  const s = Math.max(0, Math.round((now - d.getTime()) / 1000));
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h} h`;
  return `${Math.floor(h / 24)} d`;
}

export function formatAgo(iso: string | null | undefined, now: number): string {
  const age = formatAge(iso, now);
  if (age === "—") return formatClock(iso);
  return age === "0 s" ? "just now" : `${age} ago`;
}

export function pluralise(n: number, one: string, many = `${one}s`): string {
  return `${formatInt(n)} ${n === 1 ? one : many}`;
}
