# Sekisho: external service verification memo

Checked 25 Sep 2026 against official docs, official Curvegrid code and the read-only calls listed in the brief.

- **CONFIRMED**: the docs or live data agree with the PRD.
- **CORRECTED**: the PRD is wrong or incomplete; use the fix given here.
- **UNKNOWN**: not documented, and not testable without a key; verify on day one.

Raw material next to this file:
- `blockscout-samples/*.json`: trimmed live responses.
- `multibaas-docs/openapi.yaml`: the MultiBaas OpenAPI 3.0.3 spec from `curvegrid/multibaas-sdk-go` v1.1.1. The docs' API pages are generated from it.
- `intercepta-docs/*.md` and `forge-multibaas/*`: copies of the docs and library files read.

---

## 0. Fix list (read first)

| # | PRD | Status | What to do |
|---|---|---|---|
| 1 | 9.5 labels | CORRECTED | Blockscout `from.public_tags` was `[]` on all 93 live items. The labels are in `from.metadata.tags[].name` (for example "Exploit", "Phish / Hack", "SANCTIONED", "Poisoning Address"), with more text in `.slug` and `.meta.info` (for example "OFAC Sanctioned"). Match keywords there (code in §3). If you don't, the `label:*` flags never fire and S2 taint may read 0 |
| 2 | 9.5 scam tokens | CORRECTED | Token objects have no `is_scam`. Use `token.reputation == "scam"`. Token endpoints already hide scam tokens unless you send the `show-scam-tokens` header. The address-level fields `from.is_scam` and `from.reputation` do exist |
| 3 | 9.5 token field | CORRECTED | The field is `token.address_hash` (spec and live). `token.address` does not exist |
| 4 | 9.13 fallback poller | CORRECTED | `GET /events` has no sort parameter, its order is undocumented and the default `limit` is 10. `?contract_address=…&limit=20` may therefore return the oldest events. Poll with `?tx_hash=<pending tx hash>` instead |
| 5 | 9.13 handler | CORRECTED | The contract alias field is `contract.addressAlias` in the current spec but `addressLabel` in the docs' webhook sample. Read both, or route on `contract.address` (lowercased) |
| 6 | 9.9 step 6 | CORRECTED | The newest official sample (Curvegrid, pushed 25 Sep 2026) uses a bare `eventName: "Transfer"`. Older official tests use `"LogDeposited(address,uint256)"`. Use `"Held"` and `"Released"`, and fall back to the full signature if rejected. Result-row keys come back lowercased, so keep aliases lowercase. Never send `"filter": {}` (Curvegrid's Sheets add-on notes it returns 502) |
| 7 | 9.8 submit | UNKNOWN | The only official example sends `signedTx` hex **without** `0x`, while the PRD adds `0x`. Send it without the prefix; if that is rejected, retry with it. The tx hash is `result.tx.hash`, a required field, so the keccak fallback is not needed |
| 8 | C.2/C.3 deploy | RISK | forge-multibaas calls MultiBaas through FFI while Forge simulates the script locally, before anything is broadcast. If the broadcast then fails, the aliases already point at addresses with no contract. Re-runs with the fixed version `"1.0"` and fixed aliases get 409 unless `MULTIBAAS_ALLOW_UPDATE_CONTRACT=true` and `MULTIBAAS_ALLOW_UPDATE_ADDRESS=true` are set, so export both |
| 9 | 9.3 fresh wallets | UNKNOWN | The docs define only a 200 response, with `toxicScore` and `traits` both required. Nothing is documented for 404 or empty bodies. Keep the PRD's tolerant handling, and make the buyer address the first live call (1 request). Alternative: the new `check-activity` endpoint (1 request, returns `{hasActivity}`) |
| 10 | 9.3 limits | UNKNOWN | No rate limit and no quota-exhausted status code is documented; only 403 (bad key) is. The hackathon key gives 1,000 requests. Treat 429 and any other non-2xx as `status:"error"` and log the body verbatim |
| 11 | 9.5 first page | RISK | Page 1 holds the 50 most recent items. Live: 25 of the 50 native inbound txs to the Ronin exploiter were 0-value dust, and the 173,600 ETH that funded it arrived as a single internal tx. Consider `sort=value&order=desc` on `/transactions` and `include_zero_value=false` on `/internal-transactions` |
| 12 | 9.9 plan | RISK | The free plan indexes events at most 2 per second, starting at most 100 blocks back. Keep USDC sync off. On day one, call `GET /api/v0/plan` and read `event_logging_retention_hours` (affects the audit page) and `api_calls_per_sec` |
| 13 | 9.5 keyless hosts | RISK | Public `eth.blockscout.com` and `base.blockscout.com` can answer 403 with an HTML "Just a moment..." bot challenge. Use them for development only and handle non-JSON bodies |
| 14 | 9.5 rate limit | minor | `Semaphore(4)` caps concurrency, not rate: with 0.5 s responses it allows about 8 requests per second, over the 5 RPS limit. Use a 4 RPS token bucket |
| 15 | 9.2 / rule 11 | RISK | Base USDC (`0x8335…2913`) is an upgradeable proxy with a blocklist, and the token-scan detector list includes `PROXY_PATTERN` and `WHITELIST_OR_BLOCKLIST_LOGIC`. If Intercepta returns `action: "warn"` for it, rule 11 turns **every** payment into a HOLD. Check the real `action` with one call on day one; if it is `warn`, allowlist that asset |
| 16 | 9.4 / 9.5 mixers | RISK | Background knowledge, not verified today: OFAC removed Tornado Cash from the SDN list in March 2025, so the Chainalysis oracle probably no longer flags Tornado contracts. For S2, mixer exposure therefore depends on Intercepta traits and the Blockscout labels in item 1, not on the oracle |

Everything else checked is CONFIRMED; details below.

---

## 1. Intercepta (PRD 9.3)

**Docs.** The docs are at docs.web3antivirus.io. `/llms.txt` works, and appending `.md` to any page gives markdown. `/llms-full.txt` returns 404. The hackathon page (intercepta.io/ethglobal) links to the same docs. `docs.intercepta.io` does not resolve, and `api.intercepta.io` is a marketing page, not the API.

**Base URL and auth: CONFIRMED.** Base URL `https://api.web3antivirus.io`, header `X-API-KEY: <key>`. A bad key returns 403 (per the docs, and seen live). Live response to a request with no key (verbatim; note the curly apostrophe):
```
HTTP/2 403
{"status":403,"response":"This authentication key is incorrect or doesn’t exist","errors":[{"field":"","message":"This authentication key is incorrect or doesn’t exist"}]}
```

| PRD row | Path | Status | Notes |
|---|---|---|---|
| Quick Scan | `GET /api/public/v2/extension/account/{address}/quick-scan` | CONFIRMED | Path param is an address or ENS name. No chain parameter |
| Deep Scan | `GET /api/public/v2/extension/account/{address}/toxic-score` | CONFIRMED | Same response schema as Quick Scan |
| Impersonation | `GET /api/public/v1/extension/poisoning-attack/check-address/{address}` | CONFIRMED | No chain parameter |
| Scan Token | `GET /api/public/v2/extension/token-intelligence/token/{address}/risks?chainId=8453` | CONFIRMED | `chainId` is an optional string enum that includes `"1"` and `"8453"` |
| Summarize (P2) | `GET /api/public/v1/extension/security/{address}/overview` | CONFIRMED | No chain parameter; the response has a `network` field |
| (new) Check Activity | `GET /api/public/v1/extension/account/{address}/check-activity?chainId=1` | new | Returns `{"hasActivity": bool}`: true if the address has any tx, a non-zero native balance, or is a contract |

**Response shapes.** These come from the OpenAPI schemas. The docs have no example bodies for these five endpoints; the only example in the docs is for an endpoint the PRD doesn't use.

- **Quick Scan and Deep Scan** (`ToxicScoreShortResponseV2`). All fields are required.
  ```json
  {"toxicScore": 0, "traits": [{"name": "mixer_transfers", "risk": 0, "txsCount": 0, "description": "<text>"}]}
  ```
  - `toxicScore`, `risk` and `txsCount` are numbers.
  - The trait `name` enum is CONFIRMED: identical to the PRD's 15 names.
  - The ranges of `toxicScore` and `risk` are UNKNOWN. The docs don't state them; the PRD's 0 to 100 is an assumption.
- **Impersonation** (`PoisoningCheck`). Both fields are required.
  ```json
  {"isAddressPoisoned": false, "originalAddress": "0x…"}
  ```
  `isAddressPoisoned` means the queried address is itself a poisoning lookalike. `originalAddress` is the address it imitates.
- **Scan Token** (`TokenRiskAnalysisV2Response`). All fields are required.
  ```json
  {"apiVersion": "2.3.1", "riskScore": 70, "riskLevel": "neutral|low|medium|high",
   "category": "malicious|restricted|suspicious|availability|sanctioned|unverified|info",
   "trust": "whitelist|blocklist|neutral", "action": "block|warn|info",
   "detectors": [{"code": "FAKE_TOKEN", "description": "<text>"}],
   "token": {"chainId": "8453", "address": "0x…", "symbol": "…"},
   "saleTax": {"currentValue": 0, "minValue": 0, "maxValue": 0}, "buyTax": {"currentValue": 0, "minValue": 0, "maxValue": 0}}
  ```
  Detector codes include `KNOWN_MALICIOUS`, `HONEYPOT`, `FAKE_TOKEN`, `SANCTIONED_TOKEN`, `BLOCKLIST_TOKEN`, `SCAM_AIRDROP_TOKEN`, `PROXY_PATTERN`, `HIGH_REPUTATION_TOKEN`, `SUSPICIOUS_DEPLOYER` and 19 more.
- **Summarize Address** fields: `address`, `ens` (nullable), `network` ("ethereum"), `firstTxDate`, `lastTxDate`, `fundedBy`, `txCount`, `contractCreatedCount`, `approvalReceivedCount`, `isContract`, `contract` (nullable), `project` (nullable). `fundedBy` is typed as a number but described as "Entity or address that funded…", so treat it as untyped.

**Addresses with no history, rate limits, error codes: UNKNOWN.** See fix list items 9 and 10. What is confirmed (intercepta.io/ethglobal):
- Each hackathon key has 1,000 requests and stays valid through judging.
- Intercepta extends keys by hand, "usually within the hour": X or Telegram `@intercepta_`, or email.
- Plans are credit-based, and no per-endpoint credit costs are published.

---

## 2. Curvegrid MultiBaas (PRD 9.8, 9.9, 9.13)

**Sources.** The OpenAPI spec (above); the docs pages (webhooks, build-a-backend, event-indexing, api-keys); Curvegrid's own code in `matsuri-stablecoin-sample-app`, `multibaas-for-google-sheets` and `forge-multibaas`.

**Common to all calls: CONFIRMED.**
- Base `https://<deployment>.multibaas.com/api/v0`, header `Authorization: Bearer <key>`.
- The chain segment is literally `ethereum` in every path.
- Success envelope: `{"status": int, "message": str, "result": …}`.
- Errors come back on 4XX/5XX as `{"status": int, "message": str}`.

### 2a. Call a contract function: CONFIRMED, with details

`POST /api/v0/chains/ethereum/addresses/{address-or-alias}/contracts/{contract-label}/methods/{method}`

**Request body** (`PostMethodArgs`; every field is optional):

| Field | Type | Use |
|---|---|---|
| `args` | array | Function arguments |
| `from` | address or alias | Sender for writes |
| `signer` | address or alias | Purpose not documented beyond its type; do not send |
| `signature` | `"fn(type,…)"` | Only needed for overloaded functions |
| `nonce`, `gas`, `gasFeeCap`, `gasTipCap`, `gasPrice` | int | Overrides |
| `value` | string | Wei |
| `formatInts` | `auto` \| `as_numbers` \| `as_strings` | How integers come back in read results |
| `contractOverride` | bool | Call without the address and contract being linked |
| `signAndSubmit`, `nonceManagement` | bool | Cloud Wallet / HSM only |
| `preEIP1559` | bool | Force a legacy tx |
| `blockNumber`, `timestamp` | string | Historical reads; paid feature |

- **Writes:** send `{"args": [...], "from": signer.address}`, as the official samples do.
- **Argument encoding (PRD): CONFIRMED for strings and numbers.** Official samples pass uint256 amounts as decimal strings, small ints as JSON numbers, and aliases in address slots. `bytes32` as `0x` plus 64 hex characters is the standard encoding but isn't shown in the docs. Enums are `uint8`, so pass a number.
- **Nonce:** where MultiBaas gets the nonce for a non-HSM `from` is UNKNOWN. With one queue per signer key, pass `"nonce"` explicitly, taken from `eth_getTransactionCount(addr, "pending")`.

**Write response.** `result.kind == "TransactionToSignResponse"`, `result.submitted` is a bool, and `result.tx` has these fields:

| Field | Type | Notes |
|---|---|---|
| `to` | string or null | |
| `from` | string | |
| `nonce`, `gas`, `type` | int | `type` is 2 on Base Sepolia |
| `gasFeeCap`, `gasTipCap`, `gasPrice` | string | Decimal: the official Go sample parses them in base 10, and the TS sample uses `BigInt()` |
| `value` | string | Wei, decimal |
| `data` | hex string | |
| `hash` | string | In the schema; not the final signed-tx hash, so ignore it |
| `chainID` | **absent** | CORRECTED. Use the `CHAIN_ID` env var, or read `result.chainID` from `GET /api/v0/chains/ethereum/status`, as the docs sample does |

**Read response.** `result.kind == "MethodCallResponse"` and the value is in `result.output`: a scalar, or an array when the function returns several values. Send `"formatInts": "as_strings"` so that uint64 and uint256 values come back as strings.

**Reverts at compose time: UNKNOWN.** The docs say nothing. Search `message` for the 4-byte error selector as the PRD plans, and log one real failure on day one.

### 2b. Submit a signed transaction: CONFIRMED

`POST /api/v0/chains/ethereum/transactions/submit` with body `{"signedTx": "<raw tx hex>"}`.

- The response `result.tx` is the full transaction: `type, chainId, nonce, to, from, gas, maxFeePerGas, maxPriorityFeePerGas, value, input, v, r, s, hash, …`, all as strings.
- `hash` is a required field, so the tx hash is `result.tx.hash`.
- For the `0x` prefix, see fix list item 7.

Compose, sign and submit:
```python
def _int(v):  # MultiBaas sends ints as JSON numbers or decimal strings; hex tolerated
    if v is None: return 0
    if isinstance(v, int): return v
    s = str(v); return int(s, 16) if s[:2].lower() == "0x" else int(s)

r = (await http.post(f"{MB}/chains/ethereum/addresses/{alias}/contracts/{label}/methods/{method}",
                     headers=H, json={"args": args, "from": signer.address, "nonce": nonce})).json()["result"]
assert r["kind"] == "TransactionToSignResponse" and r["tx"]["type"] == 2
t = r["tx"]
signed = signer.sign_transaction({"to": t["to"], "nonce": _int(t["nonce"]), "gas": _int(t["gas"]),
    "maxFeePerGas": _int(t["gasFeeCap"]), "maxPriorityFeePerGas": _int(t["gasTipCap"]),
    "data": t["data"], "value": _int(t.get("value")), "chainId": CHAIN_ID, "type": 2})
s = (await http.post(f"{MB}/chains/ethereum/transactions/submit", headers=H,
                     json={"signedTx": bytes(signed.raw_transaction).hex()})).json()  # no 0x, as in the docs example
tx_hash = s["result"]["tx"]["hash"]   # should equal "0x" + signed.hash.hex()
```

### 2c. Webhooks: CONFIRMED, except one field name

**Managing the webhook.**
- **Create:** `POST /api/v0/webhooks` with `{"label": "sekisho-gate", "url": "<PUBLIC_GATE_URL>/webhooks/multibaas", "subscriptions": ["event.emitted"]}`. Labels may use lowercase letters, digits, `_` and `-`, and must not start with `0x`.
- **Secret:** returned as `result.secret` in the create response, and also by `GET /api/v0/webhooks/{id}`.
- **Change the tunnel URL** (every cloudflared restart gives a new one): `PUT /api/v0/webhooks/{id}` with the same body. Then read `result.secret` again.
- **List:** `GET /api/v0/webhooks`. **Delivery log:** `GET /api/v0/webhooks/{id}/events`.
- **Retries:** endpoint objects carry `failedCalls`, `lastError` and `nextAttempt`, which suggests failed deliveries are retried. Keep the handler idempotent and return 2xx quickly.

**Headers and HMAC.**
- The headers are `X-MultiBaas-Signature` and `X-MultiBaas-Timestamp`. They arrive as `X-Multibaas-…`, which doesn't matter because Starlette header lookups ignore case.
- Signature: HMAC-SHA256, keyed with the secret, over the raw body bytes **followed by** the timestamp (Unix seconds as a decimal string), as lowercase hex. The PRD 9.13 code is CONFIRMED.
- Add a freshness check (not in the docs): reject when `abs(time.time() - int(ts)) > 300`.

**What fires.**
- `event.emitted` fires only for contracts with event sync on.
- `transaction.included` fires only for Cloud Wallet transactions, so it will never fire for us.

**Body.** A JSON array of `{"id": "<uuid>", "event": "event.emitted", "data": <Event>}`. `data` has the same shape as an item from `GET /events`. Abridged from the docs sample:
```json
[{"id": "952699ad-…", "event": "event.emitted",
  "data": {"triggeredAt": "2023-11-10T11:11:30+09:00",
   "event": {"name": "Mint", "signature": "Mint(address,address,uint256)",
     "inputs": [{"name": "minter", "value": "0xF945…7172", "hashed": false, "type": "address"},
                {"name": "value", "value": "123.456", "hashed": false, "type": "uint256"}],
     "rawFields": "{\"address\":\"0x9dee…\",\"topics\":[…],\"blockNumber\":\"0xa\",\"logIndex\":\"0x0\",…}",
     "contract": {"address": "0x9deE…D67a", "addressLabel": "autotoken", "name": "MltiToken", "label": "mltitoken"},
     "indexInLog": 0},
   "transaction": {"from": "0xF945…", "txData": "0xa0712d68…", "txHash": "0xe613…14b2", "txIndexInBlock": 0,
     "blockHash": "0xa63e…", "blockNumber": 10, "contract": {"…": "same as event.contract"},
     "method": {"name": "mint", "signature": "mint(uint256)", "inputs": [{"name": "_amount", "value": "123.456", "type": "uint256"}]}}}}]
```

**Where the handler finds each field:**

| Need | Field |
|---|---|
| Event name | `data.event.name` |
| Inputs | `data.event.inputs[]`, each `{name, value, hashed, type}` |
| Tx hash | `data.transaction.txHash` |
| Block number | `data.transaction.blockNumber` (int) |
| Log index | `data.event.indexInLog` |
| Contract | `data.event.contract.address` or `.label`; the alias is `addressAlias` in the spec but `addressLabel` in this sample (fix list item 5) |

- Input values are strings. A per-contract "type conversion" can reformat uints, as the `"123.456"` in the sample shows, so do not configure one.
- The idempotency key `txHash + indexInLog` is valid.

### 2d. List events: CONFIRMED (ordering unknown)

`GET /api/v0/events`
- **Query params:** `contract_address`, `contract_label`, `event_signature`, `tx_hash`, `block_number`, `block_hash`, `tx_index_in_block`, `event_index_in_log`, `from_constructor`, `limit` (default 10), `offset`.
- **No sort parameter.** See fix list item 4.
- **Response:** `result: [Event]`, same shape as in 2c.
- `GET /api/v0/events/count` takes the same filters.

### 2e. Event Queries: CONFIRMED (eventName: see fix list item 6)

**Endpoints.**
- **Save or update:** `PUT /api/v0/queries/{label}`, body = EventQuery.
- **Run a saved query:** `GET /api/v0/queries/{label}/results?offset=0&limit=50`, which returns `result.rows: [{<alias>: value, …}]`.
- **Run without saving:** `POST /api/v0/queries?offset=0&limit=50`, body = EventQuery. Use this to test the JSON before saving it.
- Also: `GET /api/v0/queries/{label}` (the definition), `GET …/{label}/count`, `DELETE …/{label}`, and `GET /api/v0/queries` (list).

**Schema.**
- Top level: `{"events": [{"eventName": str, "select": [Field], "filter": Filter?}], "groupBy": str?, "orderBy": str?, "order": "ASC"|"DESC"}`. The default order is ASC.
- **Field:** `{"type": FieldType, "name": str (or "inputIndex": int), "alias": str, "aggregator": "add"|"subtract"|"last"|"first"|"min"|"max"|null}`. When `groupBy` is set, every field except the group-by field needs an aggregator.
- **Filter:** `{"rule": "and"|"or", "fieldType": FieldType, "inputIndex": int, "operator": "equal"|"notequal"|"lessthan"|"greaterthan"|"lessthanorequal"|"greaterthanorequal", "value": str, "children": [Filter]}`.
  - `rule` can be left out on the last filter.
  - Filters have **no `name` property**, so filter on event inputs by `inputIndex`.
- **FieldType values:** `input`, `contract_label`, `contract_name`, `contract_address`, `contract_address_alias`, `block_number`, `triggered_at`, `event_signature`, `block_hash`, `tx_hash`, `tx_from`.

**Queries to save.** `exposure_by_payee` (Held inputs: 0 holdId, 1 caseId, 2 payer, 3 payee, 4 amount). This follows the format of the official stablecoin sample:
```json
{"events": [{"eventName": "Held",
   "select": [{"type": "input", "inputIndex": 3, "alias": "payee"},
              {"type": "input", "inputIndex": 4, "alias": "total", "aggregator": "add"}],
   "filter": {"fieldType": "contract_address_alias", "operator": "equal", "value": "compliance_escrow"}}],
 "groupBy": "payee", "orderBy": "total", "order": "DESC"}
```
- `released_by_payee` is the same with `"eventName": "Released"`, payee `inputIndex` 2 and amount `inputIndex` 3.
- The schema also allows `"name": "payee"` in select.
- Row values may come back as JSON numbers or as strings; parse them with `Decimal(str(v))`.

### 2f. Upload an ABI, alias USDC, sync off: CONFIRMED

These are the same calls forge-multibaas's `main.py` makes:
```http
POST /api/v0/contracts/erc20
{"label": "erc20", "contractName": "ERC20", "version": "1.0", "rawAbi": "<json.dumps(abi): a STRING, not an array>"}

POST /api/v0/chains/ethereum/addresses
{"alias": "usdc", "address": "0x036CbD53842c5426634e7929541eC2318f3dCF7e"}

POST /api/v0/chains/ethereum/addresses/usdc/contracts
{"label": "erc20", "version": "1.0"}
```
- **Sync off:** leave `startingBlock` out of the link call. The spec says: "If absent, event indexing will be disabled". Setting `"startingBlock"` to `"-10"`, `"latest"` or a block number turns it on.
- **Check:** `GET /api/v0/chains/ethereum/addresses/usdc/contracts/erc20/status`.
- **UNKNOWN:** whether a link with sync off counts toward the "5 active contracts". `GET /plan` reports `contracts` and `linked_contracts` as separate limits.

### 2g. forge-multibaas (README, `src/MultiBaas.sol`, `main.py`): CONFIRMED

**Functions.**
- `MultiBaas.withOptions(contractLabel, addressAlias, contractVersion, startingBlock)` takes four strings and returns `bytes`. The PRD's `("compliance_registry", "compliance_registry", "1.0", "-10")` is label, alias, version, start block: CONFIRMED.
- `MultiBaas.linkContractWithOptions(contractName, address, bytes encodedOptions)`: the PRD's usage is CONFIRMED.
- `linkContract(name, addr)` uses defaults: label and alias are the lowercase contract name, version `1.0` (auto-incremented if left empty), start block `-100`.

**Environment variables.**
- `MULTIBAAS_URL`, including `https://`.
- `MULTIBAAS_API_KEY`, a key in the Administrators group.
- Optional safeguard overrides: `MULTIBAAS_ALLOW_UPDATE_CONTRACT=true` and `MULTIBAAS_ALLOW_UPDATE_ADDRESS=true` (fix list item 8).
- The README's own example uses `NETWORK_RPC_URL` and a `0x`-prefixed `PRIVATE_KEY`.

**Requirements.**
- `python3` on PATH. `main.py` uses only the standard library, so there is nothing to pip install.
- `forge` on PATH, because `main.py` runs `forge config --json` to find the `out` directory.
- `--ffi` on the command line, or `ffi = true` in `foundry.toml`.
- `libs = ["lib"]` in `foundry.toml`.
- The script path is hard-coded to `<projectRoot>/lib/forge-multibaas/main.py`, so run forge from `contracts/`.
- The artifact must be at `<out>/<Name>.sol/<Name>.json`, so each file must be named after its contract. The PRD's files are.

**Foundry version: UNKNOWN.** The README doesn't state one. CI builds against `nightly`, and the last commit was 19 Mar 2025. The library only uses `vm.ffi` and `vm.projectRoot`, so the PRD's Foundry 1.5.1 should work.

### 2h. CORS via the API: CONFIRMED

`GET /api/v0/cors`, `POST /api/v0/cors` with `{"origin": "http://localhost:3000"}`, and `DELETE /api/v0/cors/{originID}`. P0 doesn't need CORS at all, because the browser never calls MultiBaas.

### 2i. Base Sepolia and the free plan: CONFIRMED

**Base Sepolia.**
- Chain 84532 is listed as "General Availability" with event indexing on. Source: `assets.multibaas.com/chains.json`, the data behind the docs' Supported Networks page.
- Nothing says whether the free-plan network dropdown offers it, so keep the PRD 7.1 check.
- The network cannot be changed once a deployment is created. Deployments can be deleted and recreated, even on the free plan.

**Free plan** (Curvegrid pricing FAQ):
- 3 users, 5 active contracts, 1 cloud wallet, 30,000 API calls per month.
- Event indexing is capped at 2 events per second and starts at most 100 blocks back from the chain head.

**Live limits:** `GET /api/v0/plan` returns `limits[] {name, limit, count}` and `features[]`.
- Limits: `api_calls_per_sec`, `api_calls_per_day`, `api_calls_per_month`, `events_per_sec`, `users`, `contracts`, `linked_contracts`, `event_query_max_results`, `event_logging_retention_hours`, `past_logs_max_concurrency`, `past_logs_max_depth`, `cloud_wallets`.
- Features: `event_queries_feature`, `historical_blocks_feature`, `hsm_feature`, and others.
- Call it once on day one.

---

## 3. Blockscout (PRD 9.5)

**PRO API: CONFIRMED.**
- URL format: `https://api.blockscout.com/{chainId}/api/v2/...?apikey=proapi_…`. The key can also go in the header `Authorization: Bearer <key>`.
- A key is required on every PRO tier, including free.
- Chains 1, 8453 and 84532 are all in the PRO chain config.

**Free-tier limits.**
- 5 RPS and 100K credits per day. Credits reset at 00:00 UTC; once they run out, requests fail.
- Credit cost per call: `/transactions` 20, `/token-transfers` 30, `/internal-transactions` 40. That is 90 credits per address per chain, or about 450 for one full hop-1 plus hop-2 trace.
- Response headers: `x-credits-remaining`, `x-ratelimit-limit`, `x-ratelimit-remaining`, and `x-ratelimit-reset` (in ms).

**Errors.**
- 401: the key isn't being sent correctly. 429: over the RPS limit.
- Errors raised by the PRO proxy itself look like `{"error": "...", "source": "internal"|"upstream"}`: 404 "Network not supported", 502, 503, 504, and so on.

**Keyless hosts.** Observed `x-ratelimit-limit: 180`, with the window resetting in about 21 to 24 s. See also fix list item 13.

**Live keyless calls** (Ethereum, address `0x098B…2F96`; trimmed copies in `blockscout-samples/`):

| Endpoint | HTTP | Items | Does `filter=to` work? | `next_page_params` |
|---|---|---|---|---|
| `token-transfers?type=ERC-20&filter=to` | 200 | 42 | Yes: 42 of 42 have `to.hash` = address. 2 are self-transfers (from = to); drop them | `null` |
| `transactions?filter=to` | 200 | 50 | Yes: 50 of 50 (25 are 0-value) | `{"index":10,"value":"0","filter":"to","hash":"0x9114a6ee…7bc5","inserted_at":"2022-04-19T09:38:16.206532Z","block_number":14614467,"fee":"1126800000000000","items_count":50}` |
| `internal-transactions?filter=to` | 200 | 1 | Yes. The docs list `filter` = `to` \| `from` on all three endpoints | `null` |

**Field names actually present.**
- **Token transfers:** all the fields the PRD lists are there, except that `token.address` doesn't exist:
  - `from.hash`, `from.is_scam` (bool), `from.name`, `from.ens_domain_name`
  - `from.public_tags`: present, but empty on every item
  - `total.value` and `total.decimals`: both strings (for example "18")
  - `token.symbol`, `token.address_hash`, `timestamp`, `transaction_hash`

  Also present: `from.reputation` (`ok` or `scam`), `from.metadata.tags[]`, `token.decimals` (string), `token.reputation`, `token.type`, `log_index`, `block_number`, `method`.
- **Transactions:** `value` (string, wei), `from` (the same address object), `hash`, `timestamp`. Also `status` ("ok"), `result` ("success") and `transaction_types`.
- **Internal transactions:** `value` (string, wei), `from`, `transaction_hash`, `timestamp`. Also `success` (bool), `error`, `type` ("call") and `index`.

Live excerpt: the single internal tx, trimmed.
```json
{"block_number":14442835,"transaction_hash":"0xc28fad5e8d5e0ce6a2eaf67b6687be5d58113e16be590824d6cfa1a94467d0b7","timestamp":"2022-03-23T13:29:09.000000Z","value":"173600000000000000000000","success":true,"type":"call",
 "from":{"hash":"0x1A2a1c938CE3eC39b6D47113c7955bAa9DD454F2","name":"MainchainGatewayProxy","is_scam":false,"reputation":"ok","public_tags":[],"ens_domain_name":null,
   "metadata":{"tags":[{"name":"Ronin Bridge V1","slug":"ronin-bridge-v1-1","tagType":"name","ordinal":10,"meta":{"…":"…"}},{"name":"Bridge","slug":"bridge","tagType":"generic","ordinal":0,"meta":{}},{"name":"note_0","slug":"note0","tagType":"note","ordinal":0,"meta":{"alertStatus":"info","data":"…"}}]}}}
```
- Sender tag names seen across the three calls: "Exploit", "Phish / Hack", "Euler Finance Exploiter 2", "Poisoning Address", "SANCTIONED", "BLOCKED", "HOT WALLET", "Exchange", "Bridge", "Ronin Bridge V1".
- `tagType` is one of `name`, `generic`, `classifier`, `information`, `note`, `protocol`.

**Label extraction** (fix list item 1):
```python
def bs_labels(a: dict) -> list[str]:
    out = [a.get("name"), a.get("ens_domain_name")]
    out += [t.get("display_name") or t.get("label") for t in a.get("public_tags") or []]
    for t in (a.get("metadata") or {}).get("tags") or []:
        meta = t.get("meta") or {}
        if t.get("tagType") != "note":
            out += [t.get("name"), t.get("slug")]
        if isinstance(meta.get("info"), list):
            out += meta["info"]                      # e.g. "OFAC Sanctioned", "Blocked By USDC"
    return [x for x in out if x]

def bs_is_scam(a: dict) -> bool:
    return bool(a.get("is_scam")) or a.get("reputation") == "scam"
```
Consider adding `sanction` to the keyword list.

**Pagination.**
- Keyset pagination with a fixed page of 50.
- To get the next page, add every key of `next_page_params` to the query; stop when it is `null`.
- `items_count` is part of the cursor, not a page size.

**Other useful parameters:**
- `/transactions`: `sort=block_number|value|fee` together with `order=asc|desc`.
- `/internal-transactions`: `include_zero_value=false`.
- `/token-transfers`: `token=<contract address>` to restrict to one token.

---

## 4. Chainalysis sanctions oracle (PRD 9.4): CONFIRMED

- **Addresses** (go.chainalysis.com/chainalysis-oracle-docs.html):
  - Ethereum `0x40C57923924B5c5c5455c48D93317139ADDaC8fb`. The same address is used on Polygon, BNB Chain, Avalanche, Optimism, Arbitrum, Fantom, Celo and Blast.
  - Base `0x3A91A31cB3dC49b4db9Ce721F50a9D076c8D739B`.
- **Selector:** `isSanctioned(address)` = `0xdf592f7d`. 4byte returns exactly one match, and a local keccak computation gives the same value.
- **Calldata:** `0xdf592f7d000000000000000000000000098b716b8aaf21512996dc57eb0615e2383e2f96`
- **Ethereum** (ethereum-rpc.publicnode.com): `{"jsonrpc":"2.0","id":1,"result":"0x0000000000000000000000000000000000000000000000000000000000000001"}`. This is **true**, as expected.
- **Base** (mainnet.base.org): `{"jsonrpc":"2.0","result":"0x0000000000000000000000000000000000000000000000000000000000000001","id":1}`. This is also **true**, so rule 1 fires on both chains.

---

## 5. x402 facilitators: CONFIRMED

**x402.org:** `GET https://x402.org/facilitator/supported` returned 200.
- It lists `{"x402Version":2,"scheme":"exact","network":"eip155:84532"}`.
- Also listed: `upto` and `batch-settlement` on 84532, and v1 `exact` on `base-sepolia`.
- The EVM signer (`signers["eip155:*"]`) is `0xd407e409E34E0b9afb99EcCeb609bDbcD5e7f1bf`.
- `extensions`: `["builder-code","eip2612GasSponsoring","erc20ApprovalGasSponsoring"]`.
- No key needed.

**PayAI:** `GET https://facilitator.payai.network/supported` returned 200.
- It lists `{"x402Version":2,"scheme":"exact","network":"eip155:84532"}`, plus v2 `exact` on 8453 and others.
- `pricing.rates` for `eip155:84532` / `exact` (both `eip3009` and `permit2`) is `"credits":"0.00","usd":"0"`.
- PayAI's docs say ordinary exact payments need no API key and testnet settlements are free.
- Edge rate limits answer 429 or 503; respect `Retry-After`.

---

## 6. Base Sepolia USDC (PRD 7.1): CONFIRMED

- **Address:** Circle's docs list `0x036CbD53842c5426634e7929541eC2318f3dCF7e` for Base Sepolia.
- **eth_call on sepolia.base.org** (`eth_chainId` = `0x14a34`, i.e. 84532): `name()` = "USDC", `version()` = "2", `decimals()` = 6, `symbol()` = "USDC".
- **EIP-712 domain, fully verified.**
  - `DOMAIN_SEPARATOR()` returns `0x71f17a3b2ff373b803d70a5a07c046c1a2bc8e89c09ef722fcb047abe94c9818`.
  - Recomputing keccak over EIP712Domain("USDC", "2", 84532, 0x036C…) locally gives exactly this value.
  - So the x402 domain `name "USDC", version "2"` is right. "USD Coin" would give a different separator.
- **Related addresses** from Circle's docs:
  - Base mainnet USDC `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`, used by the PRD's token-scan mapping: CONFIRMED.
  - Ethereum Sepolia USDC `0x1c7D4B196Cb0C7B01d743Fbc6116a902379C7238`, for the PRD 7.1 fallback.
- **Faucet** (faucet.circle.com): 20 USDC every 2 hours, per address and per chain. Base Sepolia is listed.

---

## Appendix: calls made, and sources

**Calls.**
- Every call listed in the brief was made exactly once.
- Extra read-only calls, none of which used a key or cost quota:
  - one Intercepta Quick Scan GET with no key (returned 403), to capture the error body;
  - `symbol()`, `DOMAIN_SEPARATOR()` and `eth_chainId` on sepolia.base.org;
  - 4byte reverse lookups of standard selectors;
  - public JSON data files (MultiBaas `chains.json`, Blockscout PRO `chains-config.json`);
  - GitHub reads of public Curvegrid repositories.
- Nothing was signed up for, keyed, sent or changed.

**Sources.**
- **Intercepta:**
  - https://docs.web3antivirus.io/llms.txt
  - https://docs.web3antivirus.io/reference/quick-scan-address.md (also `scan-address.md`, `detect-address-impersonation.md`, `scan-token.md`, `summarize-address.md`, `check-address-activity.md`, `getting-started-1.md`, `api-overview.md`)
  - https://intercepta.io/ethglobal
- **MultiBaas:**
  - https://docs.curvegrid.com/multibaas/webhooks
  - https://docs.curvegrid.com/multibaas/getting-started/build-a-backend
  - https://docs.curvegrid.com/multibaas/event-indexing
  - https://docs.curvegrid.com/multibaas/api-keys
  - https://docs.curvegrid.com/multibaas/getting-started/account-and-deployment
  - https://docs.curvegrid.com/multibaas/networks/supported-networks (data: https://assets.multibaas.com/chains.json)
  - https://github.com/curvegrid/multibaas-sdk-go/blob/main/api/openapi.yaml
  - https://github.com/curvegrid/matsuri-stablecoin-sample-app (`apps/web/src/lib/eventQueries.ts`, `multibaas.ts`, `tx.ts`)
  - https://github.com/curvegrid/multibaas-for-google-sheets (`src/Code.spec.js`, `src/library/Build.js`)
  - https://github.com/curvegrid/forge-multibaas (`README.md`, `src/MultiBaas.sol`, `main.py`, `.github/workflows/test.yml`)
  - https://www.curvegrid.com/pricing (redirects to /blockchain-platform; see its FAQ)
- **Blockscout:**
  - https://docs.blockscout.com/devs/pro-api-responses-and-routes
  - https://docs.blockscout.com/make-your-first-call
  - https://docs.blockscout.com/rate-limits
  - https://docs.blockscout.com/devs/error-responses
  - https://docs.blockscout.com/best-practices
  - https://docs.blockscout.com/api-reference/addresses/list-token-transfers-involving-a-specific-address-with-filtering-options.md (plus the transactions and internal-transactions reference pages)
  - https://github.com/blockscout/backend-configs/blob/main/pro-api/prod/chains-config.json
- **Chainalysis and 4byte:**
  - https://go.chainalysis.com/chainalysis-oracle-docs.html
  - https://www.4byte.directory/api/v1/signatures/?text_signature=isSanctioned(address)
- **x402:**
  - https://x402.org/facilitator/supported
  - https://facilitator.payai.network/supported
  - https://docs.payai.network/x402/facilitators/authentication.md (also `pricing.md`, `capacity-and-limits.md`)
- **Circle:**
  - https://developers.circle.com/stablecoins/usdc-contract-addresses
  - https://faucet.circle.com
