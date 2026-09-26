"use client";

import { useEffect, useRef, useState } from "react";
import { useSWRConfig } from "swr";
import { Icon } from "@/components/ui/Icon";
import { VerdictIcon } from "@/components/ui/Verdict";
import { api } from "@/lib/api";
import { TREASURY_CONTROL_URL, USE_FIXTURES } from "@/lib/config";
import { describeError } from "@/lib/errors";
import { usePersistentFlag } from "@/lib/persist";
import { SCENARIOS } from "@/lib/scenarios";
import type { RunScenario, RunStatus } from "@/lib/types";
import styles from "./demobar.module.css";

/**
 * Demo controls (P1): run S1 to S6 through the treasury control API (POST /run, then
 * GET /runs/{id} for log lines) and reset the gate (POST /v1/demo/reset).
 */
export function DemoBar() {
  const { mutate } = useSWRConfig();
  const [open, setOpen] = usePersistentFlag("sekisho.demoBar.open", true);
  const [logOpen, setLogOpen] = useState(false);
  const [run, setRun] = useState<RunStatus | null>(null);
  const [message, setMessage] = useState<{ tone: "info" | "error"; text: string } | null>(null);
  const [starting, setStarting] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);

  const runId = run?.run_id;
  const running = run?.status === "running";
  const lineCount = run?.lines.length ?? 0;

  useEffect(() => {
    if (!runId || !running) return;
    let cancelled = false;
    const timer = setInterval(async () => {
      try {
        const next = await api.control.getRun(runId);
        if (!cancelled) setRun(next);
      } catch (error) {
        if (!cancelled) setMessage({ tone: "error", text: describeError(error).message });
      }
    }, 700);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [runId, running]);

  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lineCount, logOpen]);

  const start = async (scenario: RunScenario) => {
    setMessage(null);
    setStarting(true);
    try {
      const { run_id } = await api.control.run(scenario);
      setRun({ run_id, scenario, status: "running", lines: [], started_at: new Date().toISOString(), finished_at: null });
      setLogOpen(true);
    } catch (error) {
      setMessage({ tone: "error", text: describeError(error).message });
    } finally {
      setStarting(false);
    }
  };

  const reset = async () => {
    setConfirmReset(false);
    setMessage(null);
    try {
      const result = await api.demoReset();
      setMessage({
        tone: "info",
        text: `Reset done: ${result.archived} ${result.archived === 1 ? "case" : "cases"} archived, ${result.overrides_cleared} officer ${result.overrides_cleared === 1 ? "override" : "overrides"} cleared.`,
      });
      await mutate(() => true);
    } catch (error) {
      setMessage({ tone: "error", text: describeError(error).message });
    }
  };

  if (!open) {
    return (
      <button type="button" className={styles.reopen} onClick={() => setOpen(true)}>
        <Icon name="terminal" size={18} />
        Demo controls
        <Icon name="chevronUp" size={16} />
      </button>
    );
  }

  const active = run ? SCENARIOS.find((s) => s.id === run.scenario) : undefined;
  const statusText = message
    ? message.text
    : run
      ? `${run.scenario === "all" ? "All scenarios" : `${run.scenario} ${active?.name ?? ""}`} ${
          run.status === "running" ? "running" : run.status === "succeeded" ? "finished" : "failed"
        }${active?.label ? ` · ${active.label}` : ""}`
      : USE_FIXTURES
        ? "Fixture mode: runs are simulated in the browser"
        : `Runs through ${TREASURY_CONTROL_URL}`;

  return (
    <div className={styles.bar} role="region" aria-label="Demo controls">
      {logOpen ? (
        <div className={styles.log} ref={logRef} aria-live="polite" aria-label="Run log">
          {run?.lines.length ? (
            run.lines.map((line, i) => (
              <div key={i} className={styles.logLine}>
                {line}
              </div>
            ))
          ) : (
            <div className={styles.logEmpty}>{run ? "Waiting for the first log line…" : "Run a scenario to see its log here."}</div>
          )}
        </div>
      ) : null}
      <div className={styles.inner}>
        <span className={styles.title}>
          <Icon name="terminal" size={18} />
          Demo
        </span>
        <div className={styles.scenarios} role="group" aria-label="Run a scenario">
          {SCENARIOS.map((s) => (
            <button
              key={s.id}
              type="button"
              className={styles.scenario}
              data-tone={s.expect === "ALLOW" ? "allow" : s.expect === "HOLD" ? "hold" : "block"}
              disabled={starting || running}
              onClick={() => void start(s.id)}
              title={`Run ${s.id}: ${s.name}. Expected ${s.expect}${s.label ? ` (${s.label})` : ""}`}
            >
              <span className={styles.scenarioIcon}>
                <VerdictIcon verdict={s.expect} size={16} />
              </span>
              <span className={styles.scenarioId}>{s.id}</span>
              <span className={styles.scenarioName}>{s.name}</span>
            </button>
          ))}
          <button type="button" className={styles.scenario} disabled={starting || running} onClick={() => void start("all")} title="Run S1, S3, S2, S4, S5 in order">
            <Icon name="play" size={14} />
            <span className={styles.scenarioId}>All</span>
          </button>
        </div>
        <span className={styles.status} data-tone={message?.tone === "error" ? "error" : undefined} role="status">
          {running ? <Icon name="spinner" size={16} className={styles.spin} /> : null}
          {statusText}
        </span>
        <div className={styles.tools}>
          <button type="button" className={styles.tool} onClick={() => setLogOpen(!logOpen)} aria-expanded={logOpen}>
            Log
            <Icon name={logOpen ? "chevronDown" : "chevronUp"} size={15} />
          </button>
          {confirmReset ? (
            <span className={styles.confirm}>
              Archive every case?
              <button type="button" className={`${styles.tool} ${styles.danger}`} onClick={() => void reset()}>
                Reset
              </button>
              <button type="button" className={styles.tool} onClick={() => setConfirmReset(false)}>
                Cancel
              </button>
            </span>
          ) : (
            <button type="button" className={styles.tool} onClick={() => setConfirmReset(true)} disabled={running}>
              <Icon name="reset" size={15} />
              Reset demo
            </button>
          )}
          <button type="button" className={styles.tool} onClick={() => setOpen(false)} aria-label="Hide demo controls">
            <Icon name="chevronDown" size={16} />
          </button>
        </div>
      </div>
    </div>
  );
}
