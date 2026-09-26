"use client";

import { useState } from "react";
import { setOperatorToken } from "@/lib/operator-session";
import { Button } from "@/components/ui/Button";
import styles from "./operator.module.css";

export function OperatorSession() {
  const [saved, setSaved] = useState(false);
  return (
    <details className={styles.session}>
      <summary>{saved ? "Operator token set" : "Operator access"}</summary>
      <form className={styles.panel} onSubmit={(event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const token = String(new FormData(form).get("operatorToken") ?? "").trim();
        setOperatorToken(token);
        setSaved(Boolean(token));
        form.reset();
      }}>
        <label htmlFor="operator-token">Operator token</label>
        <input id="operator-token" name="operatorToken" type="password" autoComplete="off" required />
        <p>Required for review decisions, scenario runs and demo reset. Cleared when this page reloads.</p>
        <Button type="submit" small>Use token</Button>
        {saved ? <Button small onClick={() => { setOperatorToken(""); setSaved(false); }}>Clear token</Button> : null}
        <span role="status">{saved ? "Token set; validated when an action is submitted." : "Viewing without operator access."}</span>
      </form>
    </details>
  );
}
