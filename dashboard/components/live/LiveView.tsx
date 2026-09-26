"use client";

import { PageHeader } from "@/components/shell/PageHeader";
import { DecisionFeed } from "./DecisionFeed";
import { DemoBar } from "./DemoBar";
import { KpiStrip } from "./KpiStrip";
import { LiveRail } from "./LiveRail";
import styles from "./live.module.css";

export function LiveView() {
  return (
    <div className={styles.withDemoBar}>
      <PageHeader
        title="Live decisions"
        lede="Every payment our agents make or accept is screened before anything is signed: allowed, held for an officer, or blocked."
      />
      <KpiStrip />
      <div className={styles.layout}>
        <DecisionFeed />
        <LiveRail />
      </div>
      <DemoBar />
    </div>
  );
}
