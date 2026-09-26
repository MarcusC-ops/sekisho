#!/usr/bin/env python3
"""MultiBaas setup, PRD 9.9 steps 4 to 6. Idempotent: safe to re-run.

4. Upload a minimal ERC-20 ABI as label `erc20` and link Base Sepolia USDC at alias
   `usdc` with event sync off (the link call has no `startingBlock`).
5. Create the webhook `sekisho-gate` -> ${PUBLIC_GATE_URL}/webhooks/multibaas for
   `event.emitted`, and write its secret to the MB_WEBHOOK_SECRET line of .env (the
   secret is never printed). `--update-webhook` repoints an existing webhook when the
   tunnel URL changes.
6. Save the Event Queries `exposure_by_payee` and `released_by_payee` (bare eventName
   first, as in Curvegrid's newest sample; the full signature if that is rejected).
Also: add CONSOLE_ORIGIN as a CORS origin, and check the registry and escrow aliases.

Usage:
  python scripts/setup_multibaas.py               # apply
  python scripts/setup_multibaas.py --dry-run     # print what would be sent (no calls)
  python scripts/setup_multibaas.py --update-webhook
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
try:
    from sekisho_gate.config import Settings, get_settings
except ImportError:  # running without the editable install
    sys.path.insert(0, str(REPO_ROOT / "gate"))
    from sekisho_gate.config import Settings, get_settings

from sekisho_gate.chain.multibaas import MultiBaasError

WEBHOOK_LABEL = "sekisho-gate"
WEBHOOK_PATH = "/webhooks/multibaas"
ERC20_CONTRACT_NAME = "ERC20"
ERC20_VERSION = "1.0"

ERC20_ABI = [
    {"type": "function", "name": "approve", "stateMutability": "nonpayable",
     "inputs": [{"name": "spender", "type": "address"}, {"name": "value", "type": "uint256"}],
     "outputs": [{"name": "", "type": "bool"}]},
    {"type": "function", "name": "allowance", "stateMutability": "view",
     "inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}],
     "outputs": [{"name": "", "type": "uint256"}]},
    {"type": "function", "name": "balanceOf", "stateMutability": "view",
     "inputs": [{"name": "account", "type": "address"}],
     "outputs": [{"name": "", "type": "uint256"}]},
    {"type": "function", "name": "decimals", "stateMutability": "view",
     "inputs": [], "outputs": [{"name": "", "type": "uint8"}]},
    {"type": "function", "name": "transfer", "stateMutability": "nonpayable",
     "inputs": [{"name": "to", "type": "address"}, {"name": "value", "type": "uint256"}],
     "outputs": [{"name": "", "type": "bool"}]},
    {"type": "event", "name": "Transfer", "anonymous": False,
     "inputs": [{"name": "from", "type": "address", "indexed": True},
                {"name": "to", "type": "address", "indexed": True},
                {"name": "value", "type": "uint256", "indexed": False}]},
]

# Event Queries (PRD 9.9 step 6). Inputs by index: Held(holdId, caseId, payer, payee,
# amount), Released(holdId, caseId, payee, amount, officer). Aliases stay lowercase
# because MultiBaas returns result keys lowercased.
QUERY_EVENTS = {
    "exposure_by_payee": ("Held", "Held(uint256,bytes32,address,address,uint256)", 3, 4),
    "released_by_payee": ("Released", "Released(uint256,bytes32,address,uint256,address)", 2, 3),
}


def event_query(escrow_alias: str, event_name: str, payee_index: int, amount_index: int) -> dict:
    return {
        "events": [{
            "eventName": event_name,
            "select": [
                {"type": "input", "inputIndex": payee_index, "alias": "payee"},
                {"type": "input", "inputIndex": amount_index, "alias": "total", "aggregator": "add"},
            ],
            "filter": {"fieldType": "contract_address_alias", "operator": "equal", "value": escrow_alias},
        }],
        "groupBy": "payee",
        "orderBy": "total",
        "order": "DESC",
    }


def update_env_file(path: Path, key: str, value: str) -> None:
    """Set KEY=value in a dotenv file: replace the first KEY= line or append one.
    Written atomically; keeps the file mode (0600 for a new file)."""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True) if path.exists() else []
    if re.search(r"[\s#'\"]", value):
        value = '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    pattern = re.compile(rf"^\s*(export\s+)?{re.escape(key)}\s*=")
    new_line = f"{key}={value}\n"
    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = new_line
            break
    else:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(new_line)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".env.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.writelines(lines)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def read_env_value(path: Path, key: str) -> str:
    if not path.exists():
        return ""
    pattern = re.compile(rf"^\s*(export\s+)?{re.escape(key)}\s*=\s*(.*)$")
    for line in path.read_text(encoding="utf-8").splitlines():
        m = pattern.match(line)
        if m:
            v = m.group(2).strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            return v
    return ""


def _done(mb: "MB", message: str) -> None:
    """Report a completed change (a dry run already printed the request instead)."""
    if not mb.dry_run:
        print(f"  {message}")


def _is_placeholder(value: str) -> bool:
    return not value or "<" in value


class MB:
    """Small sync MultiBaas REST helper. Returns the envelope's `result`; raises
    MultiBaasError (status 404 when the object does not exist)."""

    def __init__(self, url: str, key: str, http: httpx.Client, dry_run: bool) -> None:
        self.api = url.rstrip("/") + "/api/v0"
        self.key = key
        self.http = http
        self.dry_run = dry_run

    def call(self, method: str, path: str, body: Any = None, params: dict | None = None) -> Any:
        if self.dry_run:
            shown = json.dumps(body, indent=None) if body is not None else ""
            qs = ("?" + "&".join(f"{k}={v}" for k, v in params.items())) if params else ""
            print(f"  [dry-run] {method} {self.api}{path}{qs}  (Authorization: Bearer ***) {shown}")
            return None
        resp = self.http.request(
            method, self.api + path, json=body, params=params,
            headers={"Authorization": f"Bearer {self.key}", "Accept": "application/json"},
            timeout=20.0,
        )
        if resp.status_code >= 400:
            raise MultiBaasError.from_http(f"{method} {path}", resp.status_code, resp.text)
        try:
            data = resp.json()
        except ValueError:
            raise MultiBaasError(f"{method} {path}: non-JSON response", status=resp.status_code,
                                 body=resp.text[:2000]) from None
        return data.get("result") if isinstance(data, dict) else data

    def get_or_none(self, path: str, params: dict | None = None) -> Any:
        try:
            return self.call("GET", path, params=params)
        except MultiBaasError as exc:
            if exc.status == 404:
                return None
            raise


def ensure_erc20(mb: MB, s: Settings) -> None:
    label, alias, usdc = s.usdc_label, s.usdc_alias, s.usdc_address
    print(f"Step 4: ABI '{label}' and USDC alias '{alias}' -> {usdc} (event sync off)")
    contract = None if mb.dry_run else mb.get_or_none(f"/contracts/{label}")
    if contract:
        print(f"  contract '{label}' already uploaded (version {contract.get('version')})")
    else:
        mb.call("POST", f"/contracts/{label}", {
            "label": label, "contractName": ERC20_CONTRACT_NAME, "version": ERC20_VERSION,
            # MultiBaas requires non-null bytecode even for an ABI-only library.
            # `bin` is the upload field used by forge-multibaas; no deployment occurs.
            "bin": "0x", "language": "solidity",
            "rawAbi": json.dumps(ERC20_ABI),
        })
        _done(mb, f"uploaded contract '{label}' {ERC20_VERSION}")

    address = None if mb.dry_run else mb.get_or_none(f"/chains/ethereum/addresses/{alias}")
    if address:
        if str(address.get("address", "")).lower() != usdc.lower():
            raise MultiBaasError(
                f"alias '{alias}' points at {address.get('address')}, not {usdc}; "
                "delete or rename it in the MultiBaas console"
            )
        print(f"  alias '{alias}' already set")
    else:
        mb.call("POST", "/chains/ethereum/addresses", {"alias": alias, "address": usdc})
        _done(mb, f"created alias '{alias}'")

    linked = {c.get("label") for c in (address or {}).get("contracts") or [] if isinstance(c, dict)}
    if label in linked:
        print(f"  '{alias}' already linked to '{label}'")
    else:
        # No startingBlock: event indexing stays off for USDC (saves the event budget).
        mb.call("POST", f"/chains/ethereum/addresses/{alias}/contracts",
                {"label": label, "version": ERC20_VERSION})
        _done(mb, f"linked '{alias}' to '{label}' with event sync off")


def ensure_webhook(mb: MB, s: Settings, env_file: Path, update: bool) -> bool:
    public = s.public_gate_url.strip().rstrip("/")
    url = f"{public}{WEBHOOK_PATH}" if not _is_placeholder(public) else ""
    print(f"Step 5: webhook '{WEBHOOK_LABEL}' -> {url or '(PUBLIC_GATE_URL not set)'}")
    body = {"label": WEBHOOK_LABEL, "url": url, "subscriptions": ["event.emitted"]}

    hooks = [] if mb.dry_run else (mb.call("GET", "/webhooks", params={"limit": 100}) or [])
    existing = next((h for h in hooks if isinstance(h, dict) and h.get("label") == WEBHOOK_LABEL), None)

    result = None
    if existing is None:
        if not url:
            print("  PUBLIC_GATE_URL is not set: webhook not created (set it and re-run)")
            return False
        result = mb.call("POST", "/webhooks", body)
        _done(mb, "created webhook")
    else:
        stale = existing.get("url") != url or "event.emitted" not in (existing.get("subscriptions") or [])
        if stale and update and url:
            result = mb.call("PUT", f"/webhooks/{existing.get('id')}", body)
            _done(mb, f"updated webhook {existing.get('id')} (was {existing.get('url')})")
        elif stale:
            print(f"  webhook points at {existing.get('url')}; re-run with --update-webhook to repoint it")
            result = existing
        else:
            print("  webhook already up to date")
            result = existing

    if mb.dry_run:
        print("  [dry-run] would write the webhook secret to MB_WEBHOOK_SECRET in .env")
        return True
    secret = (result or {}).get("secret") if isinstance(result, dict) else None
    if not secret and existing is not None:
        detail = mb.call("GET", f"/webhooks/{existing.get('id')}") or {}
        secret = detail.get("secret")
    if not secret:
        print("  WARNING: MultiBaas returned no webhook secret; MB_WEBHOOK_SECRET not changed")
        return False
    if read_env_value(env_file, "MB_WEBHOOK_SECRET") == secret:
        print(f"  MB_WEBHOOK_SECRET in {env_file.name} already matches")
    else:
        update_env_file(env_file, "MB_WEBHOOK_SECRET", secret)
        print(f"  wrote the webhook secret to MB_WEBHOOK_SECRET in {env_file.name} (not shown)")
    return True


def ensure_queries(mb: MB, s: Settings) -> bool:
    print(f"Step 6: Event Queries on '{s.escrow_alias}'")
    ok = True
    for name, (bare, signature, payee_idx, amount_idx) in QUERY_EVENTS.items():
        saved = None
        for event_name in (bare, signature):
            try:
                mb.call("PUT", f"/queries/{name}", event_query(s.escrow_alias, event_name, payee_idx, amount_idx))
                if not mb.dry_run:  # run it once: a wrong eventName fails here, not on save
                    mb.call("GET", f"/queries/{name}/results", params={"limit": 1})
            except MultiBaasError as exc:
                print(f"  '{name}' with eventName '{event_name}' rejected: {exc}")
                continue
            saved = event_name
            break
        if saved is None:
            ok = False
            print(f"  FAILED to save '{name}'")
        else:
            _done(mb, f"saved '{name}' (eventName '{saved}')")
    return ok


def ensure_cors(mb: MB, origins: list[str]) -> None:
    wanted = [o.rstrip("/") for o in origins if o and not _is_placeholder(o)]
    print(f"CORS origins: {', '.join(wanted) or '(none)'}")
    current = [] if mb.dry_run else (mb.call("GET", "/cors") or [])
    have = {str(c.get("origin", "")).rstrip("/") for c in current if isinstance(c, dict)}
    for origin in wanted:
        if origin in have:
            print(f"  {origin} already allowed")
        else:
            mb.call("POST", "/cors", {"origin": origin})
            _done(mb, f"added {origin}")


def check_contracts(mb: MB, s: Settings) -> None:
    print("Check: registry and escrow aliases (linked by the deploy script)")
    for alias, label in ((s.registry_alias, s.registry_label), (s.escrow_alias, s.escrow_label)):
        info = mb.get_or_none(f"/chains/ethereum/addresses/{alias}")
        if not info:
            print(f"  WARNING: alias '{alias}' not found; run the deploy script (PRD Appendix C)")
            continue
        labels = {c.get("label") for c in info.get("contracts") or [] if isinstance(c, dict)}
        state = "linked" if label in labels else f"NOT linked to '{label}'"
        print(f"  '{alias}' = {info.get('address')} ({state})")


def main(argv: list[str] | None = None, *, http: httpx.Client | None = None,
         settings: Settings | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="print the requests, send nothing")
    parser.add_argument("--update-webhook", action="store_true", help="repoint an existing webhook")
    parser.add_argument("--env-file", type=Path, default=REPO_ROOT / ".env", help="dotenv file for the secret")
    parser.add_argument("--cors-origin", action="append", default=[], help="extra CORS origin (repeatable)")
    args = parser.parse_args(argv)

    s = settings or get_settings()
    url = s.mb_url.strip()
    key = s.mb_admin_api_key.get_secret_value().strip()
    if not args.dry_run and (_is_placeholder(url) or not key):
        print("MB_URL and MB_ADMIN_API_KEY must be set in .env (or use --dry-run)", file=sys.stderr)
        return 2
    if args.dry_run:
        print("Dry run: nothing is sent. Existing objects would be skipped or updated.")

    own = http is None
    client = http or httpx.Client()
    mb = MB(url or "https://<deployment>.multibaas.com", key, client, args.dry_run)
    failures = 0
    steps = [
        ("erc20", lambda: ensure_erc20(mb, s)),
        ("webhook", lambda: ensure_webhook(mb, s, args.env_file, args.update_webhook)),
        ("queries", lambda: ensure_queries(mb, s)),
        ("cors", lambda: ensure_cors(mb, [s.console_origin, *args.cors_origin])),
    ]
    if not args.dry_run:
        steps.append(("check", lambda: check_contracts(mb, s)))
    try:
        for name, step in steps:
            try:
                if step() is False:
                    failures += 1
            except (MultiBaasError, httpx.HTTPError) as exc:
                failures += 1
                print(f"  ERROR in {name}: {exc}", file=sys.stderr)
    finally:
        if own:
            client.close()
    print("Done." if not failures else f"Finished with {failures} problem(s).")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
