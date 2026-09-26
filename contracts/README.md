# Sekisho contracts

Foundry project for Sekisho's decision registry and test-USDC escrow. The original
design is retained in the [development archive](../docs/archive/PRD.md); current
behaviour is defined by the contracts and tests.

Base Sepolia deployment and verified rehearsal receipts: [LIVE-EVIDENCE.md](../docs/LIVE-EVIDENCE.md).
The full provider-triggered HOLD journey is still unverified; the operator-driven
escrow release/refund rehearsal is verified separately.

| Path | What it is |
|---|---|
| `src/ComplianceRegistry.sol` | Audit trail of screenings. The gate's screener key records each verdict; an officer can override it |
| `src/ComplianceEscrow.sol` | Holds USDC for HOLD payments; pays out only to a payee the registry shows as cleared |
| `test/` | 18 tests, including 2 fuzz tests. `test/mocks/MockUSDC.sol` is a 6-decimal test token |
| `script/Deploy.s.sol` | Deploys both contracts, grants the roles and links both into MultiBaas |

## Invariants the tests prove

- Only `SCREENER_ROLE` writes screenings; only `OFFICER_ROLE` overrides them.
- An ALLOW expires; a BLOCK does not.
- The escrow refuses deposits to blocked payees.
- Held funds can only be released to a payee with a fresh ALLOW in the registry.
- A hold can be settled once.
- The payer can reclaim only after `reclaimAfter`.
- Escrow accounting returns to zero after all test deposits are settled.

## Setup

Tested with Foundry 1.5.1 and solc 0.8.28 (forge downloads solc on the first build). The
dependencies are git submodules of the repo, pinned in `foundry.lock`:

| `lib/` | Pin |
|---|---|
| `forge-std` | tag `v1.12.0` (`7117c90`) |
| `openzeppelin-contracts` | tag `v5.4.0` (`c64a1ed`) |
| `forge-multibaas` | commit `8e84d1c` on `main` (the repo has no tags) |

`make install` runs `git submodule update --init`. The nested submodules
(OpenZeppelin's own test libs, forge-multibaas's copy of forge-std) are not needed:
`git submodule update --init` is enough, and the build and tests pass without them.

## Build and test

```bash
cd contracts
forge build
forge test -vv    # 18 tests passed, 0 failed
```

Or run `make contracts-test` from the repo root. forge-lint prints three notes asking for
SCREAMING_SNAKE_CASE on the immutables `token`, `registry` and `reclaimAfter`. They are
style notes, and those names are ABI getters the gate reads, so leave them.

## Deploy

From the repo root, with `.env` filled in (keys from `make wallets`, funded with testnet gas):

```bash
make deploy                              # deploy, then link both contracts into MultiBaas
scripts/deploy_contracts.sh --no-link    # deploy only, then link by hand
scripts/deploy_contracts.sh --verify     # also verify both on Blockscout (failure is not fatal)
```

The script:
- reads `DEPLOYER_PK`, `GATE_SCREENER_PK`, `OFFICER_PK`, `USDC_ADDRESS`,
  `CONTRACTS_RPC_URL`, plus `MB_URL` and `MB_ADMIN_API_KEY` when linking;
- refuses any chain except 84532, 11155111 and 31337;
- checks that USDC has code, the deployer has ETH and the MultiBaas key works;
- runs `forge script script/Deploy.s.sol:Deploy --broadcast --ffi --slow`;
- prints both addresses, deploy blocks and the `REGISTRY_ADDRESS=` / `ESCROW_ADDRESS=`
  lines to add to `.env`.

It never prints keys and never edits `.env`. It exits 2 when the contracts deployed but
linking was not confirmed. `ENV_FILE=path` points it at another env file. Keep raw broadcast artifacts local. Publish reviewed addresses, block numbers and
transaction links in the evidence document; all broadcast output is gitignored.

Local dry run:

```bash
anvil &
forge create test/mocks/MockUSDC.sol:MockUSDC --rpc-url http://127.0.0.1:8545 --private-key <anvil key 0> --broadcast
# then use an ENV_FILE with the anvil keys, the MockUSDC address, CONTRACTS_RPC_URL=http://127.0.0.1:8545
ENV_FILE=/path/to/anvil.env scripts/deploy_contracts.sh --no-link
```

### How forge-multibaas links

- Forge runs `python3 lib/forge-multibaas/main.py` over FFI (`ffi = true`). It needs Python
  3 (3.9 works), standard library only, with no pip packages. It also runs
  `forge config --json`, so `forge` must be on PATH; the script makes sure of that.
- It reads `MULTIBAAS_URL` and `MULTIBAAS_API_KEY` (an Administrators-group key). The
  script sets them from `MB_URL` and `MB_ADMIN_API_KEY`.
- It talks to `<MULTIBAAS_URL>/api/v0` on chain path `ethereum`, meaning the deployment's
  one network. It never checks that the RPC is on that network, so keep `CONTRACTS_RPC_URL`
  on the same chain as the MultiBaas deployment.
- For each contract it:
  - uploads `out/<Name>.sol/<Name>.json` as label `compliance_registry` or
    `compliance_escrow`, version `1.0`;
  - creates the alias of the same name;
  - links it with `startingBlock: "-10"`, passed through unchanged. MultiBaas then starts
    indexing 10 blocks before its latest block at link time.
- **It links during forge's local simulation, before anything is broadcast.** If the
  broadcast then fails, the aliases point at addresses with no code. Re-running the script
  fixes that, because an unchanged nonce gives the same addresses.
- A re-run that produces new addresses gets a 409 on the aliases unless
  `MULTIBAAS_ALLOW_UPDATE_ADDRESS=true`. Changed bytecode under version `1.0` also needs
  `MULTIBAAS_ALLOW_UPDATE_CONTRACT=true`. The script defaults both to `true`, so a redeploy
  re-points the aliases.
- It exits 0 even when MultiBaas rejects a call. That is why the script checks the key
  first and then expects `Contract linked successfully` twice.
- Never run `forge script` with `LINK_MULTIBAAS=true` and without `--broadcast`: it still
  links.
- forge-multibaas pins no Foundry version: its README names none, and its CI builds with
  `nightly`. Its last commit is from March 2025. Here it was tested with Foundry 1.5.1,
  against a local stand-in for the MultiBaas API. The published deployment used
Foundry 1.8.3 with `--no-link`, followed by explicit MultiBaas linking at the actual
deployment blocks. Do not confuse deployment-tool simulation with a confirmed broadcast.

## Interface reference (checked against the compiled ABI)

Enums are ABI `uint8`. `Verdict`: 0 NONE (rejected on write), 1 ALLOW, 2 HOLD, 3 BLOCK.
`Status` (escrow): 0 NONE, 1 HELD, 2 RELEASED, 3 REFUNDED.

| Function | Selector | Caller |
|---|---|---|
| `recordScreening(address subject, uint8 verdict, uint8 riskScore, uint64 ttlSeconds, bytes32 reportHash, bytes32 policyId, bytes32 caseId)` | `0x59b9e257` | `SCREENER_ROLE` |
| `overrideVerdict(address subject, uint8 next, uint64 ttlSeconds, bytes32 noteHash, bytes32 caseId)` | `0x8663113b` | `OFFICER_ROLE` (registry) |
| `deposit(address payee, uint256 amount, bytes32 caseId) returns (uint256 holdId)` | `0x26b3293f` | anyone, after `approve` |
| `release(uint256 holdId)` | `0x37bdc99b` | `OFFICER_ROLE` (escrow) |
| `refund(uint256 holdId)` | `0x278ecde1` | officer any time; payer after `reclaimAfter` |

`ttlSeconds` must be non-zero for every verdict, BLOCK included; `riskScore` must be at
most 100.

| Error | Selector | Raised by |
|---|---|---|
| `NotCleared()` | `0x92a032ca` | `release` while the payee lacks a fresh ALLOW |
| `NotHeld()` | `0x845eadf1` | `release`/`refund` on a settled or unknown hold |
| `PayeeBlocked()` | `0xecbe11eb` | `deposit` to a BLOCKed payee |
| `ZeroAmount()` | `0x1f2a2005` | `deposit` of 0 |
| `NotPayer()` | `0x1435e357` | `refund` by someone who is neither officer nor payer |
| `TooEarly()` | `0x085de625` | payer `refund` before `reclaimAfter` |
| `InvalidVerdict()` | `0xfbcebe72` | verdict NONE in `recordScreening`/`overrideVerdict` |
| `InvalidScore()` | `0x15561365` | `riskScore > 100` |
| `InvalidTtl()` | `0x3dc68a66` | `ttlSeconds == 0` |
| `AccessControlUnauthorizedAccount(address,bytes32)` | `0xe2517d3f` | missing role |
| `ReentrancyGuardReentrantCall()` | `0x3ee5aeb5` | reentrancy (escrow) |
| `SafeERC20FailedOperation(address)` | `0x5274afe7` | a token transfer returned false (escrow) |

A token revert inside `deposit` (missing approval, low balance) bubbles up unchanged. That
is `ERC20InsufficientAllowance` `0xfb8f41b2` or `ERC20InsufficientBalance` `0xe450d38c`
from MockUSDC; real USDC is expected to revert with a plain `Error(string)` `0x08c379a0`
(not checked on Base Sepolia).

| Event | topic0 |
|---|---|
| `Screened(address,uint8,uint8,bytes32,bytes32,uint64,address,bytes32)` | `0xd0f03db3375a9d43ae9ea915ca87a9e9048f6b3c175545330d03f5802263084a` |
| `VerdictOverridden(address,uint8,uint8,bytes32,address,bytes32)` | `0x78be9509b961062b993c75c5b10b56bfb7a23bcd17503833210b8bdce3de6ed0` |
| `Held(uint256,bytes32,address,address,uint256)` | `0x41c317a5936935e04bbc8a86acb4fcab534208071947137b57c6c10d2aa74920` |
| `Released(uint256,bytes32,address,uint256,address)` | `0x26eb1f7387345797fe3a8bff389e3ff40ae4ea2698d0ffac3ba0b7709f484a5a` |
| `Refunded(uint256,bytes32,address,uint256,address)` | `0x8a82ee56bf92c2b40bef867848d18dbc4b989f501f6bae8b1944edd958a60b0e` |

Indexed inputs: `Screened` (subject, screener, caseId), `VerdictOverridden` (subject,
officer, caseId), `Held` (holdId, caseId, payer), `Released` (holdId, caseId, payee),
`Refunded` (holdId, caseId, payer). Role ids: `SCREENER_ROLE` `0xe2826fa7…90f3`,
`OFFICER_ROLE` `0xbbecb256…1b53` (keccak256 of the names), `DEFAULT_ADMIN_ROLE` `0x00…00`.
