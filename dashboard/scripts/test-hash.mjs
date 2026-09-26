#!/usr/bin/env node
/**
 * Hash tests (PRD 12 "Hashing", Appendix F). Run: npm run test:hash
 *
 * 1. The Appendix F test vector: viem keccak256(stringToBytes(text)) must equal the
 *    hash Python produces for the same canonical bytes.
 * 2. The fixtures: every served report text hashes to its case's report_hash and to the
 *    onchain Screened.reportHash, except the one deliberately tampered case.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { keccak256, stringToBytes } from "viem";
import { canonical } from "../lib/canonical.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURES = join(HERE, "..", "fixtures");

let failures = 0;
let passes = 0;
function check(name, ok, detail = "") {
  if (ok) {
    passes += 1;
    console.log(`  ok    ${name}`);
  } else {
    failures += 1;
    console.log(`  FAIL  ${name}${detail ? `\n        ${detail}` : ""}`);
  }
}

// ---------- 1. Appendix F test vector
console.log("Appendix F test vector");
const VECTOR_TEXT =
  '{"amount":"50000","case_id":"cs_TEST","note":"関所 checkpoint","risk_score":100,"schema":"sekisho.report.v1","verdict":"BLOCK"}';
const VECTOR_HASH = "0xfbe83695c30cc9bec0d70c46a9b9a6e7941ef44d8cdf59361458684fe261f653";
const VECTOR_CASE_B32 = "0x0dbc5c13a5822f5f601f519456a1b21d496e046c7b40f14d82e23a5ccccebf6d";

const vectorHash = keccak256(stringToBytes(VECTOR_TEXT));
check("keccak256(stringToBytes(text)) equals the Python hash", vectorHash === VECTOR_HASH, `got ${vectorHash}`);
check(
  'case_id_b32 for "cs_TEST" equals keccak(text="cs_TEST")',
  keccak256(stringToBytes("cs_TEST")) === VECTOR_CASE_B32,
);
const vectorObject = {
  verdict: "BLOCK",
  schema: "sekisho.report.v1",
  risk_score: 100,
  note: "関所 checkpoint",
  case_id: "cs_TEST",
  amount: "50000",
};
check("canonical() reproduces the canonical bytes", canonical(vectorObject) === VECTOR_TEXT);

// ---------- 2. Fixtures
console.log("\nFixtures (dashboard/fixtures)");
const read = (name) => JSON.parse(readFileSync(join(FIXTURES, name), "utf8"));
const cases = read("cases.json");
const reports = read("reports.json");
const audit = read("audit.json");
const policy = read("policy.json");

check("policy.yaml text hashes to the policy id", keccak256(stringToBytes(policy.yaml)) === policy.id);

let tampered = 0;
for (const c of cases) {
  const label = `${c.case_id} ${c.verdict}`;
  const served = reports[c.report_hash];
  if (typeof served !== "string") {
    check(`${label}: report text exists`, false);
    continue;
  }
  const computed = keccak256(stringToBytes(served));
  const isTamperCase = c.purpose.includes("tampered");
  const screened = audit.find((e) => e.name === "Screened" && e.case_id === c.case_id);
  check(`${label}: case_id_b32 = keccak(case_id)`, keccak256(stringToBytes(c.case_id)) === c.case_id_b32);
  check(`${label}: served text is canonical JSON`, canonical(JSON.parse(served)) === served);
  if (isTamperCase) {
    tampered += 1;
    check(`${label}: tampered report does NOT match (Verify shows Mismatch)`, computed !== c.report_hash);
  } else {
    check(`${label}: served text hashes to report_hash`, computed === c.report_hash, `got ${computed}`);
  }
  if (screened) {
    check(`${label}: Screened.reportHash = report_hash`, screened.inputs.reportHash === c.report_hash);
  } else {
    check(`${label}: no Screened event only when attestation is not confirmed`, c.attestation.status !== "confirmed");
  }
}
check("exactly one deliberately tampered case", tampered === 1);

console.log(`\n${passes} passed, ${failures} failed`);
process.exit(failures ? 1 : 0);
