/**
 * Canonical JSON, the JavaScript twin of the gate's canonical bytes (PRD 9.7):
 *   json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
 *
 * Used ONLY to build fixture reports (scripts/gen-fixtures.mjs and the in-browser
 * fixture simulator). Verify never re-serialises: it hashes the exact text the gate
 * served (Appendix F). Shared as .mjs so Node scripts and the app import one copy.
 *
 * @param {unknown} value
 * @returns {string}
 */
export function canonical(value) {
  if (value === null || typeof value !== "object") {
    if (typeof value === "number" && !Number.isFinite(value)) return "null";
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  const record = /** @type {Record<string, unknown>} */ (value);
  const keys = Object.keys(record)
    .filter((key) => record[key] !== undefined)
    .sort();
  return `{${keys.map((key) => `${JSON.stringify(key)}:${canonical(record[key])}`).join(",")}}`;
}
