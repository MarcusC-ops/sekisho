# Verify external service APIs

Subagent prompt written by the lead agent (Claude Code, Claude Opus 5.5) on 2026-09-25 13:00 UTC.
Local paths are shortened to `<repo>` and `<scratchpad>`; the text is otherwise verbatim.

---

You are verifying external service APIs for a hackathon build called Sekisho (an AML/compliance checkpoint for AI-agent payments over x402 on Base Sepolia). The PRD is at `<downloads>/PRD (2).md (now committed as PRD.md)`. The relevant parts are Sections 7 (lines ~279-317), 9.2 to 9.5, 9.8 and 9.9 (lines ~401-612), and 9.13 (lines ~749-763). The PRD marks several details as unconfirmed. Confirm or correct them against current official docs (today is 25 Sep 2026), so builders can code from your memo.

Hard rules: do not sign up for anything, use any API keys, send any transaction, or change anything on any service. Only read docs and make the few public, read-only calls listed below.

1. **Intercepta** (formerly Web3 Antivirus) API. Start at docs.web3antivirus.io/reference/api-overview and try `/llms.txt`. Confirm the base URL, auth header and every endpoint path in the PRD 9.3 table. Give the response JSON shapes and field names: toxicScore and traits[] {name, risk, txsCount, description}; impersonation isAddressPoisoned/originalAddress; the token risks fields. Also cover the behaviour for addresses with no history (404? empty body?), rate limits and error codes. Include one verbatim example response per endpoint if the docs have one.
2. **Curvegrid MultiBaas** REST API (docs.curvegrid.com/multibaas):
   (a) Call contract function: the exact path, the request body (args encoding, `from`, `signer`?), and the response shape for writes (`result.tx` fields: to, from, nonce, gas, gasFeeCap, gasTipCap, data, value, type, chainID?) versus reads (`result.output`).
   (b) The submit-signed-transaction endpoint, its body and its response.
   (c) Webhooks: the create endpoint and body; where the secret comes from; the delivery headers (`X-MultiBaas-Signature`, `X-MultiBaas-Timestamp`); the exact HMAC construction (algorithm; is the message body+timestamp or timestamp+body; hex or base64?); and the delivered payload shape for `event.emitted` (field names for event name, inputs, txHash, block number, contract alias/address, log index).
   (d) The events list endpoint and its query params.
   (e) Event Queries: the create/update endpoint (`PUT /api/v0/queries/{label}`?), the results endpoint, and the query JSON schema (eventName format, select/aggregator/groupBy/orderBy/filter, fieldType values).
   (f) Uploading a contract ABI and linking an address with an alias via REST (needed to link USDC as alias `usdc` with label `erc20`), and how to turn event sync off.
   (g) The `curvegrid/forge-multibaas` README (GitHub): `MultiBaas.linkContractWithOptions` and `MultiBaas.withOptions(...)` parameter order, required env vars, the python3/ffi requirement and supported Foundry versions.
   (h) Can CORS origins be set via the API?
   (i) Base Sepolia support and free-plan limits.
3. **Blockscout**. Confirm the PRO API base format `https://api.blockscout.com/{chainId}/api/v2/...` with the `apikey` query param from docs.blockscout.com. Then make ONE live keyless GET for each of these (public, read-only):
   - `https://eth.blockscout.com/api/v2/addresses/0x098B716B8Aaf21512996dC57EB0615e2383E2f96/token-transfers?type=ERC-20&filter=to`
   - `.../transactions?filter=to`
   - `.../internal-transactions?filter=to`
   Save trimmed responses (the first 2 items plus `next_page_params`, via jq) under `<scratchpad>/research/blockscout-samples/`. Document the item field names actually present:
   - token transfers: from.hash, from.is_scam, from.public_tags, from.name, from.ens_domain_name, total.value, total.decimals, token.symbol, token.address_hash or token.address, timestamp, transaction_hash
   - transactions: value, from, hash, timestamp
   - internal txs: value, from, transaction_hash, timestamp
   Also note whether `filter=to` works on each endpoint, and how pagination works.
4. **Chainalysis sanctions oracle**. Confirm the contract addresses for Ethereum (`0x40C57923924B5c5c5455c48D93317139ADDaC8fb`) and Base (`0x3A91A31cB3dC49b4db9Ce721F50a9D076c8D739B`) from Chainalysis docs. Then do one JSON-RPC `eth_call` of `isSanctioned(0x098B716B8Aaf21512996dC57EB0615e2383E2f96)` via curl against https://ethereum-rpc.publicnode.com and one against the Base oracle via https://mainnet.base.org. Get the 4-byte selector for `isSanctioned(address)` from https://www.4byte.directory/api/v1/signatures/?text_signature=isSanctioned(address) (stdlib sha3 is not keccak). Report the raw results; true is expected on Ethereum.
5. **x402 facilitator**. Call `GET https://x402.org/facilitator/supported` and confirm it supports x402 v2, the `exact` scheme on `eip155:84532`. Do the same for the PayAI fallback, `https://facilitator.payai.network/supported`.
6. **Base Sepolia USDC**. Confirm `0x036CbD53842c5426634e7929541eC2318f3dCF7e`, its 6 decimals, and its EIP-712 name/version ("USDC", "2") via Circle docs, or via eth_call of `name()` and `version()` against https://sepolia.base.org.

Output: write the findings to `<scratchpad>/research/services.md`. Mark each item CONFIRMED, CORRECTED or UNKNOWN, with source URLs and verbatim example payloads where available. Keep it tight: builders will code directly from it. Your final message: a summary of at most 15 lines covering the corrections and anything that looks risky.
