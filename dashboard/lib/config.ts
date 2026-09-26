/**
 * Runtime configuration. NEXT_PUBLIC_* values are inlined at build time, so each one
 * must be read with a literal `process.env.NAME` expression.
 */

function trimSlash(url: string): string {
  return url.replace(/\/+$/, "");
}

/** The only backend the browser talks to. */
export const GATE_URL = trimSlash(process.env.NEXT_PUBLIC_GATE_URL || "http://localhost:8000");

/** Explorer for transactions on the payment and contract chain (Base Sepolia). */
export const EXPLORER_URL = trimSlash(
  process.env.NEXT_PUBLIC_EXPLORER_URL || "https://sepolia.basescan.org",
);

/** Counterparties are real Ethereum mainnet addresses. */
export const MAINNET_EXPLORER_URL = trimSlash(
  process.env.NEXT_PUBLIC_MAINNET_EXPLORER_URL || "https://etherscan.io",
);

/** Treasury control API (demo bar). */
export const TREASURY_CONTROL_URL = trimSlash(
  process.env.NEXT_PUBLIC_TREASURY_CONTROL_URL || "http://localhost:8100",
);

/**
 * UI fixtures are used only when this is exactly "true". Off by default: the submitted
 * build must talk to the live gate (AGENTS.md rule 4).
 */
export const USE_FIXTURES = process.env.NEXT_PUBLIC_USE_FIXTURES === "true";

/** Base mainnet explorer, for source-of-funds hops found on chain 8453. */
const BASE_MAINNET_EXPLORER_URL = "https://basescan.org";

/** Explorer base for an address or tx on a given chain id. */
export function explorerForChain(chainId: number): string {
  if (chainId === 1) return MAINNET_EXPLORER_URL;
  if (chainId === 8453) return BASE_MAINNET_EXPLORER_URL;
  return EXPLORER_URL;
}

export const CHAIN_NAMES: Record<number, string> = {
  1: "Ethereum",
  8453: "Base",
  84532: "Base Sepolia",
  11155111: "Ethereum Sepolia",
};

export function chainName(chainId: number): string {
  return CHAIN_NAMES[chainId] ?? `Chain ${chainId}`;
}

/** Tokens the console knows how to label. Anything else shows its address. */
export const KNOWN_ASSETS: Record<string, { symbol: string; decimals: number }> = {
  // Base Sepolia USDC (PRD 7.1)
  "0x036cbd53842c5426634e7929541ec2318f3dcf7e": { symbol: "USDC", decimals: 6 },
  // Base mainnet USDC (token scan target)
  "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": { symbol: "USDC", decimals: 6 },
};

/** Escrow and x402 amounts are USDC, 6 decimals. */
export const USDC_DECIMALS = 6;
