"use client";

import { useState } from "react";
import { EXPLORER_URL, MAINNET_EXPLORER_URL, explorerForChain } from "@/lib/config";
import { shortAddress, shortHash } from "@/lib/format";
import { Icon } from "./Icon";
import styles from "./ui.module.css";

export function CopyButton({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async (event: React.MouseEvent) => {
    event.preventDefault();
    event.stopPropagation();
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };
  return (
    <button
      type="button"
      className={`${styles.iconButton} ${copied ? styles.copied : ""}`}
      onClick={copy}
      aria-label={copied ? "Copied" : label}
      title={copied ? "Copied" : label}
    >
      <Icon name={copied ? "check" : "copy"} size={16} />
    </button>
  );
}

type AddressChain = "mainnet" | "payment" | number;

function addressUrl(address: string, chain: AddressChain): { url: string; name: string } {
  if (chain === "mainnet") return { url: `${MAINNET_EXPLORER_URL}/address/${address}`, name: "Etherscan (mainnet)" };
  if (chain === "payment") return { url: `${EXPLORER_URL}/address/${address}`, name: "Base Sepolia explorer" };
  const base = explorerForChain(chain);
  return { url: `${base}/address/${address}`, name: chain === 1 ? "Etherscan (mainnet)" : "block explorer" };
}

/**
 * An address in monospace, shortened `0x098B…2F96`, with copy and explorer buttons.
 * Counterparties are real mainnet addresses (Etherscan); our own wallets live on Base Sepolia.
 */
export function Address({
  address,
  chain = "mainnet",
  full = false,
}: {
  address: string | null | undefined;
  chain?: AddressChain;
  full?: boolean;
}) {
  if (!address) return <span className={styles.address}>—</span>;
  const { url, name } = addressUrl(address, chain);
  return (
    <span className={styles.address}>
      <span className={styles.addressText} title={address}>
        {full ? address : shortAddress(address)}
      </span>
      <CopyButton value={address} label="Copy address" />
      <a
        className={styles.iconButton}
        href={url}
        target="_blank"
        rel="noreferrer"
        aria-label={`Open ${shortAddress(address)} on ${name}`}
        title={`Open on ${name}`}
        onClick={(e) => e.stopPropagation()}
      >
        <Icon name="external" size={16} />
      </a>
    </span>
  );
}

/** A transaction hash linking to the Base Sepolia explorer (or the given explorer URL). */
export function TxLink({ hash, url, label }: { hash: string | null | undefined; url?: string | null; label?: string }) {
  if (!hash) return <span className="mono">—</span>;
  const href = url || `${EXPLORER_URL}/tx/${hash}`;
  return (
    <a
      className={styles.txLink}
      href={href}
      target="_blank"
      rel="noreferrer"
      title={`${hash} (opens the block explorer)`}
      onClick={(e) => e.stopPropagation()}
    >
      {label ?? shortHash(hash)}
      <Icon name="external" size={14} />
    </a>
  );
}

/** A full bytes32 value (hash, id) with a copy button. */
export function HashValue({ value, label }: { value: string | null | undefined; label: string }) {
  if (!value) return <span className="mono">—</span>;
  return (
    <span className={styles.address} style={{ whiteSpace: "normal", alignItems: "flex-start" }}>
      <span className={styles.hashFull}>{value}</span>
      <CopyButton value={value} label={`Copy ${label}`} />
    </span>
  );
}
