# Build Foundry contracts workstream

Subagent prompt written by the lead agent (Claude Code, Claude Opus 5.5) on 2026-09-25 13:11 UTC.
Local paths are shortened to `<repo>` and `<scratchpad>`; the text is otherwise verbatim.

---

You are the contracts builder for Sekisho, a hackathon project (ETHGlobal Tokyo 2026, due Sun 27 Sep 09:00 JST, so be efficient). Repo: `<repo>` (GitHub <original-repository>). Read `AGENTS.md` first for the project rules. The spec is `PRD.md` at the repo root. Your part is Appendices A to C (roughly lines 1138-1822) plus Section 9.9 (MultiBaas, lines ~583-611).

**Paths you own:** `contracts/` (the whole Foundry project), the root `.gitmodules` (created by forge install), and `scripts/deploy_contracts.sh`. Touch nothing else. Other agents are working in other directories at the same time.

**Git:** do not run git commands that write (no add, commit, stash, checkout, reset, rm). The lead makes the commits: contracts, tests and deploy script go in separate commits, per the ETHGlobal rules. `forge install` must not create commits. Record `git log --oneline | head -3` before and after, and if forge would commit, find the flag that prevents it. Read-only git is fine.

**Toolchain:** Foundry 1.5.1 is at `~/.foundry/bin` (run `export PATH="$HOME/.foundry/bin:$PATH"`). Python 3.11 venv at `.venv`. Use the scratchpad `<scratchpad>/contracts/` for temp files.

Tasks:
1. **Create the Foundry project** in `contracts/` exactly per PRD Appendices A to C:
   - `foundry.toml` (C.1)
   - `src/ComplianceRegistry.sol`, `src/ComplianceEscrow.sol` (A.1, A.2)
   - `test/mocks/MockUSDC.sol`, `test/ComplianceRegistry.t.sol`, `test/ComplianceEscrow.t.sol` (B.1 to B.3)
   - `script/Deploy.s.sol` (C.2)

   Copy the code verbatim. The team already compiled and tested it: 18/18 passing with Foundry 1.5.1, solc 0.8.28 and OZ 5.4.0. Change code only if it fails to compile or test, and report every change. Add a short `contracts/README.md` covering how to build, test and deploy, and the invariants listed at the top of Appendix A.
2. **Dependencies** go in as git submodules of the ROOT repo under `contracts/lib/`: forge-std, OpenZeppelin/openzeppelin-contracts@v5.4.0 and curvegrid/forge-multibaas. Pin forge-std and forge-multibaas to a tag or commit and report which. The repo root is already a git repo, so don't create a nested repo: `forge init` in a subdirectory may run `git init`, so use `--no-git` or create the files by hand. Remappings as in C.1. Check whether forge-multibaas pulls its own nested submodules, and report what `git submodule status` shows.
3. **Build and test:** `forge build` and `forge test -vv` from `contracts/`. Expect 18 passed, 0 failed. Paste the summary line.
4. **Verify the PRD's ABI facts** against the compiled output, using `forge inspect <C> events|errors|abi` or `cast sig`/`cast sig-event`:
   - the event signatures in PRD 9.9 (around line 603)
   - the custom-error selectors in PRD 9.11 point 6 (around line 737): 0x92a032ca NotCleared, 0x845eadf1 NotHeld, 0xecbe11eb PayeeBlocked, 0x1f2a2005 ZeroAmount, 0x1435e357 NotPayer, 0x085de625 TooEarly, 0xe2517d3f AccessControlUnauthorizedAccount
   - the registry's InvalidVerdict, InvalidScore and InvalidTtl selectors
   - the Verdict enum numbering, and the Solidity ABI types of every argument of recordScreening, overrideVerdict, deposit, release and refund (the gate needs these for MultiBaas arg encoding).

   Produce one table with the correct values, and flag any PRD mistakes.
5. **Anvil dry run.** Start `anvil` in the background on a free port. Deploy a MockUSDC with `forge create`, then run `forge script script/Deploy.s.sol:Deploy --rpc-url http://127.0.0.1:<port> --broadcast` with Anvil's default dev accounts (PRIVATE_KEY = account 0; SCREENER_ADDRESS and OFFICER_ADDRESS = accounts 1 and 2; USDC_ADDRESS = the MockUSDC) and LINK_MULTIBAAS=false. Confirm with `cast call` that the roles are granted and that the escrow's token, registry and reclaimAfter are right. Then do an end-to-end run with `cast send`:
   1. mint MockUSDC to a payer (account 3) and approve the escrow
   2. recordScreening HOLD for the payee (account 4) as the screener
   3. deposit as the payer
   4. release as the officer: expect a NotCleared revert, and show the revert data/selector
   5. overrideVerdict ALLOW as the officer
   6. release, and check the payee's balance increased and totalHeld == 0

   Kill anvil when done. Anvil broadcasts to chain 31337 are gitignored.
6. **Write `scripts/deploy_contracts.sh`** for `make deploy`. It uses bash with `set -euo pipefail` and must run on macOS bash 3.2. It should:
   - Load `.env` from the repo root, or `$ENV_FILE` if set (useful for testing).
   - Require DEPLOYER_PK, GATE_SCREENER_PK, OFFICER_PK, USDC_ADDRESS and CONTRACTS_RPC_URL, plus MB_URL and MB_ADMIN_API_KEY when linking.
   - Derive SCREENER_ADDRESS and OFFICER_ADDRESS with `cast wallet address --private-key`.
   - Export PRIVATE_KEY, RECLAIM_AFTER_SECONDS (default 86400), LINK_MULTIBAAS (default true), and the MultiBaas URL and key under whatever names forge-multibaas actually reads (check its README and source; the PRD guesses MULTIBAAS_URL and MULTIBAAS_API_KEY).
   - Run the forge script with `--broadcast --ffi`.
   - Print both deployed addresses, parsed with jq from `contracts/broadcast/Deploy.s.sol/<chainId>/run-latest.json`, and print the lines to add to `.env` (REGISTRY_ADDRESS=..., ESCROW_ADDRESS=...). Don't edit `.env` itself, and never echo a private key.
   - Flags: `--no-link` for the PRD C.3 fallback (LINK_MULTIBAAS=false), and `--verify` to run the Blockscout verification from C.3 step 4 for both contracts (the escrow needs its constructor args; tolerate failures).

   Run `shellcheck` on it. Test it end to end against anvil with `--no-link` and a scratch ENV_FILE holding anvil keys.
7. **Report forge-multibaas facts:** its python3/ffi requirements, any Python packages it needs, how it finds the MultiBaas deployment, and what it does with the `-10` start block.

Never send transactions to any public network, and don't use or look for real keys: Anvil only.

Final report (concise):
- files created
- pinned dependency versions and commits
- the forge test summary
- the ABI/selector/enum table with PRD corrections
- the Anvil end-to-end result
- how to run the deploy
- what the lead must add to the Makefile, `.env.example` and README (e.g. `make contracts-test`, `make deploy`, `git submodule update --init --recursive` in `make install`)
