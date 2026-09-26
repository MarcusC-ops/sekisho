"use client";

import "@xyflow/react/dist/style.css";
import { Background, Controls, Handle, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import { useMemo } from "react";
import { chainName } from "@/lib/config";
import { formatUsd, shortAddress } from "@/lib/format";
import type { TraceResult } from "@/lib/types";
import { hopTone } from "./trace";
import styles from "./traceGraph.module.css";

type HopData = {
  kind: "center" | "hop1" | "hop2";
  address: string;
  label?: string;
  usd?: number | null;
  share?: number | null;
  chainId?: number;
  flags: string[];
  tone: "block" | "hold" | "neutral" | "accent";
};

type HopNode = Node<HopData, "hop">;

const HIDDEN_HANDLE = { top: "50%", left: "50%", opacity: 0, pointerEvents: "none" as const };

function HopNodeView({ data }: NodeProps<HopNode>) {
  const title = [
    data.address,
    data.label,
    data.usd !== undefined && data.usd !== null ? formatUsd(data.usd) : null,
    data.chainId ? chainName(data.chainId) : null,
    data.flags.length ? `flags: ${data.flags.join(", ")}` : null,
  ]
    .filter(Boolean)
    .join("\n");
  return (
    <div className={styles.node} data-kind={data.kind} data-tone={data.tone} title={title}>
      <Handle type="target" position={Position.Top} style={HIDDEN_HANDLE} isConnectable={false} />
      <Handle type="source" position={Position.Bottom} style={HIDDEN_HANDLE} isConnectable={false} />
      {data.kind === "center" ? <span className={styles.kicker}>Counterparty</span> : null}
      {data.flags.length ? <span className={styles.flagged}>⚑ {data.tone === "block" ? "flagged: block-level" : "flagged"}</span> : null}
      <span className={styles.addr}>{shortAddress(data.address)}</span>
      {data.label ? <span className={styles.label}>{data.label}</span> : null}
      {data.kind !== "center" && data.usd !== undefined && data.usd !== null ? (
        <span className={styles.usd}>
          {formatUsd(data.usd)}
          {data.share !== undefined && data.share !== null ? ` · ${data.share.toFixed(1)}%` : ""}
        </span>
      ) : null}
    </div>
  );
}

const NODE_TYPES = { hop: HopNodeView };

function toneOf(flags: string[]): HopData["tone"] {
  return hopTone(flags) ?? "neutral";
}

function layout(trace: TraceResult, counterparty: string): { nodes: HopNode[]; edges: Edge[] } {
  const nodes: HopNode[] = [
    {
      id: "center",
      type: "hop",
      position: { x: 0, y: 0 },
      origin: [0.5, 0.5],
      data: { kind: "center", address: counterparty, flags: [], tone: "accent" },
    },
  ];
  const edges: Edge[] = [];
  const n = trace.hop1.length;
  const angleOf = new Map<string, number>();
  trace.hop1.forEach((hop, i) => {
    const angle = -Math.PI / 2 + (i * 2 * Math.PI) / Math.max(n, 1) + (n === 2 ? Math.PI / 2 : 0);
    angleOf.set(hop.address, angle);
    const id = `h1:${hop.address}`;
    nodes.push({
      id,
      type: "hop",
      position: { x: Math.cos(angle) * 300, y: Math.sin(angle) * 190 },
      origin: [0.5, 0.5],
      data: {
        kind: "hop1",
        address: hop.address,
        label: hop.labels[0],
        usd: hop.usd,
        share: hop.share_pct,
        chainId: hop.chain_id,
        flags: hop.flags,
        tone: toneOf(hop.flags),
      },
    });
    const tone = hopTone(hop.flags);
    edges.push({
      id: `e:${id}`,
      source: id,
      target: "center",
      type: "straight",
      animated: Boolean(tone),
      style: {
        stroke: tone ? `var(--verdict-${tone}-mark)` : "var(--border-strong)",
        strokeWidth: 1.5 + ((hop.share_pct ?? 0) / 100) * 6,
      },
    });
  });
  const perVia = new Map<string, number>();
  trace.hop2.forEach((hop) => {
    const base = angleOf.get(hop.via);
    if (base === undefined) return;
    const k = perVia.get(hop.via) ?? 0;
    perVia.set(hop.via, k + 1);
    const angle = base + (k - 0.5) * 0.42;
    const id = `h2:${hop.via}:${hop.address}`;
    nodes.push({
      id,
      type: "hop",
      position: { x: Math.cos(angle) * 560, y: Math.sin(angle) * 330 },
      origin: [0.5, 0.5],
      data: { kind: "hop2", address: hop.address, usd: hop.usd, chainId: hop.chain_id, flags: hop.flags, tone: toneOf(hop.flags) },
    });
    const tone = hopTone(hop.flags);
    edges.push({
      id: `e:${id}`,
      source: id,
      target: `h1:${hop.via}`,
      type: "straight",
      animated: Boolean(tone),
      style: { stroke: tone ? `var(--verdict-${tone}-mark)` : "var(--border-strong)", strokeWidth: 1.5, strokeDasharray: "5 4" },
    });
  });
  return { nodes, edges };
}

/** Source-of-funds graph (P1): the counterparty in the centre, direct funders around it, second hops outside. */
export default function TraceGraph({ trace, counterparty }: { trace: TraceResult; counterparty: string }) {
  const { nodes, edges } = useMemo(() => layout(trace, counterparty), [trace, counterparty]);
  return (
    <div className={styles.canvas}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        fitView
        fitViewOptions={{ padding: 0.15 }}
        nodesConnectable={false}
        elementsSelectable={false}
        zoomOnScroll={false}
        panOnScroll={false}
        preventScrolling={false}
        minZoom={0.3}
        maxZoom={1.6}
      >
        <Background gap={24} size={1} color="var(--border)" />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
