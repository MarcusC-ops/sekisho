#!/usr/bin/env bash
# Deploy ComplianceRegistry + ComplianceEscrow and link both into MultiBaas (PRD Appendix C).
#
# Usage: scripts/deploy_contracts.sh [--no-link] [--verify]    (make deploy runs it with no flags)
#   --no-link  deploy only (LINK_MULTIBAAS=false); then link by hand (PRD C.3 fallback)
#   --verify   verify both contracts on Blockscout afterwards (failures are reported, not fatal)
#
# Reads .env at the repo root, or $ENV_FILE. Values already set in the environment win.
#   Required: DEPLOYER_PK GATE_SCREENER_PK OFFICER_PK USDC_ADDRESS CONTRACTS_RPC_URL
#   Linking:  MB_URL MB_ADMIN_API_KEY (passed to forge-multibaas as MULTIBAAS_URL/MULTIBAAS_API_KEY)
#   Optional: RECLAIM_AFTER_SECONDS (86400), LINK_MULTIBAAS (true), CHAIN_ID (checked against
#             the RPC), BLOCKSCOUT_VERIFIER_URL (default from the chain id), and
#             MULTIBAAS_ALLOW_UPDATE_CONTRACT / _ADDRESS (both default true, so a re-run re-links).
# Prints addresses, never keys. Does not edit .env.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
CONTRACTS="$ROOT/contracts"

say() { printf '%s\n' "$*"; }
warn() { printf 'warning: %s\n' "$*" >&2; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }
usage() { sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; }

# KEY=value lines only; nothing is evaluated, so placeholders like https://<id>.multibaas.com are
# safe. Strips `export `, surrounding quotes and unquoted " # comments". The environment wins.
load_env() {
  local line key val
  while IFS= read -r line || [ -n "$line" ]; do
    line=${line%$'\r'}
    line=${line#"${line%%[![:space:]]*}"}
    case $line in '' | '#'*) continue ;; esac
    case $line in 'export '*) line=${line#export } ;; esac
    key=${line%%=*}
    case $key in "$line" | '' | [0-9]* | *[!A-Za-z0-9_]*) continue ;; esac
    val=${line#*=}
    case $val in
      \"*) val=${val#\"} && val=${val%%\"*} ;;
      \'*) val=${val#\'} && val=${val%%\'*} ;;
      *) val=${val%%[[:space:]]#*} && val=${val%"${val##*[![:space:]]}"} ;;
    esac
    [ -n "${!key:-}" ] || export "$key=$val"
  done <"$1"
}

require() {
  local v
  for v in "$@"; do [ -n "${!v:-}" ] || die "$v is not set (in $ENV_FILE or the environment)"; done
}

hexkey() { case $1 in 0x* | 0X*) printf '%s' "$1" ;; *) printf '0x%s' "$1" ;; esac; }

keyaddr() { # $1 = name of the variable holding the key; prints the address, never the key
  cast wallet address --private-key "$(hexkey "${!1}")" 2>/dev/null || die "$1 is not a valid private key"
}

LINK_FLAG="" VERIFY=false
for arg in "$@"; do
  case $arg in
    --no-link) LINK_FLAG=false ;;
    --verify) VERIFY=true ;;
    -h | --help) usage && exit 0 ;;
    *) usage >&2 && die "unknown option: $arg" ;;
  esac
done

ENV_FILE=${ENV_FILE:-$ROOT/.env}
[ -f "$ENV_FILE" ] || die "$ENV_FILE not found (cp .env.example .env && make wallets)"
load_env "$ENV_FILE"

command -v forge >/dev/null 2>&1 || PATH="$HOME/.foundry/bin:$PATH"
export PATH # forge-multibaas runs python3, which runs `forge config`
for tool in forge cast jq curl; do
  command -v "$tool" >/dev/null 2>&1 || die "$tool not found (Foundry: https://getfoundry.sh)"
done

require DEPLOYER_PK GATE_SCREENER_PK OFFICER_PK USDC_ADDRESS CONTRACTS_RPC_URL

LINK_MULTIBAAS=$(printf '%s' "${LINK_FLAG:-${LINK_MULTIBAAS:-true}}" | tr '[:upper:]' '[:lower:]')
case $LINK_MULTIBAAS in
  true | 1 | yes) LINK_MULTIBAAS=true ;;
  false | 0 | no) LINK_MULTIBAAS=false ;;
  *) die "LINK_MULTIBAAS must be true or false" ;;
esac
RECLAIM_AFTER_SECONDS=${RECLAIM_AFTER_SECONDS:-86400}
case $RECLAIM_AFTER_SECONDS in '' | *[!0-9]*) die "RECLAIM_AFTER_SECONDS must be whole seconds" ;; esac

PRIVATE_KEY=$(hexkey "$DEPLOYER_PK")
ADMIN_ADDRESS=$(keyaddr DEPLOYER_PK)
SCREENER_ADDRESS=$(keyaddr GATE_SCREENER_PK)
OFFICER_ADDRESS=$(keyaddr OFFICER_PK)
[ "$SCREENER_ADDRESS" != "$OFFICER_ADDRESS" ] ||
  die "GATE_SCREENER_PK and OFFICER_PK must be different keys (the screener must not clear its own holds)"
export PRIVATE_KEY SCREENER_ADDRESS OFFICER_ADDRESS USDC_ADDRESS RECLAIM_AFTER_SECONDS LINK_MULTIBAAS

# ---------- preflight (read-only RPC calls) ----------
CHAIN=$(cast chain-id --rpc-url "$CONTRACTS_RPC_URL" 2>/dev/null) || die "cannot reach CONTRACTS_RPC_URL"
case $CHAIN in
  84532 | 11155111 | 31337) ;; # Base Sepolia, Ethereum Sepolia (PRD 7.1 fallback), Anvil
  *) die "chain $CHAIN is not an allowed testnet (84532, 11155111 or 31337); refusing to deploy" ;;
esac
[ -z "${CHAIN_ID:-}" ] || [ "$CHAIN_ID" = "$CHAIN" ] || die "CHAIN_ID=$CHAIN_ID but CONTRACTS_RPC_URL is chain $CHAIN"
USDC_CODE=$(cast code "$USDC_ADDRESS" --rpc-url "$CONTRACTS_RPC_URL" 2>/dev/null) || die "USDC_ADDRESS is not a valid address"
[ "$USDC_CODE" != 0x ] || die "USDC_ADDRESS $USDC_ADDRESS has no code on chain $CHAIN"
[ "$(cast balance "$ADMIN_ADDRESS" --rpc-url "$CONTRACTS_RPC_URL")" != 0 ] ||
  die "deployer $ADMIN_ADDRESS has no ETH on chain $CHAIN"
for who in SCREENER_ADDRESS OFFICER_ADDRESS; do
  [ "$(cast balance "${!who}" --rpc-url "$CONTRACTS_RPC_URL")" != 0 ] ||
    warn "${who%_ADDRESS} ${!who} has no ETH yet; fund it before running the gate"
done

if [ "$LINK_MULTIBAAS" = true ]; then
  require MB_URL MB_ADMIN_API_KEY
  case $MB_URL in *'<'* | *'>'*) die "MB_URL still holds the .env.example placeholder (or use --no-link)" ;; esac
  command -v python3 >/dev/null 2>&1 || die "forge-multibaas needs python3 on PATH (or use --no-link)"
  export MULTIBAAS_URL=${MB_URL%/} MULTIBAAS_API_KEY=$MB_ADMIN_API_KEY
  # The label/alias/version are fixed ("1.0"), so without these a re-run gets a 409 from
  # forge-multibaas instead of re-pointing the aliases at the new addresses.
  export MULTIBAAS_ALLOW_UPDATE_CONTRACT=${MULTIBAAS_ALLOW_UPDATE_CONTRACT:-true}
  export MULTIBAAS_ALLOW_UPDATE_ADDRESS=${MULTIBAAS_ALLOW_UPDATE_ADDRESS:-true}
  # forge-multibaas exits 0 even when MultiBaas rejects it, so check the key before deploying.
  # The header goes through curl's stdin config, which keeps the key out of the process list.
  status=$(printf 'header = "Authorization: Bearer %s"\n' "$MULTIBAAS_API_KEY" |
    curl -sS -o /dev/null -w '%{http_code}' -K - "$MULTIBAAS_URL/api/v0/currentuser" 2>/dev/null) || status=000
  [ "$status" = 200 ] || die "MultiBaas check failed (HTTP $status from $MULTIBAAS_URL/api/v0/currentuser): check MB_URL and MB_ADMIN_API_KEY, or use --no-link"
fi

# ---------- deploy ----------
say "Deploying to chain $CHAIN from $ADMIN_ADDRESS"
say "  screener $SCREENER_ADDRESS, officer $OFFICER_ADDRESS, USDC $USDC_ADDRESS"
say "  reclaimAfter ${RECLAIM_AFTER_SECONDS}s, link MultiBaas: $LINK_MULTIBAAS"
SIM_NOTE="forge-multibaas links during forge's local simulation, before anything is broadcast. If the broadcast fails, MultiBaas keeps aliases for addresses that were never deployed; re-run this script to fix them (MULTIBAAS_ALLOW_UPDATE_*=true lets the re-run re-point them)."
[ "$LINK_MULTIBAAS" = false ] || warn "$SIM_NOTE"
LOG=$(mktemp "${TMPDIR:-/tmp}/sekisho-deploy.XXXXXX")
trap 'rm -f "$LOG"' EXIT
START_MS=$(($(date +%s) * 1000))
if ! (cd "$CONTRACTS" && forge script script/Deploy.s.sol:Deploy --rpc-url "$CONTRACTS_RPC_URL" --broadcast --ffi --slow) 2>&1 | tee "$LOG"; then
  [ "$LINK_MULTIBAAS" = false ] || ! grep -q 'Link Contract:' "$LOG" || warn "$SIM_NOTE"
  die "forge script failed (see above)"
fi

RUN="$CONTRACTS/broadcast/Deploy.s.sol/$CHAIN/run-latest.json"
[ -f "$RUN" ] || die "no broadcast record at $RUN"
[ "$(jq -r '.timestamp // 0' "$RUN")" -ge "$START_MS" ] || die "$RUN predates this run; was anything broadcast?"

created() { # contract name -> checksummed address of its CREATE transaction
  local a
  a=$(jq -r --arg n "$1" '[.transactions[] | select(.transactionType == "CREATE" and .contractName == $n) | .contractAddress][0] // empty' "$RUN")
  [ -n "$a" ] || die "no $1 deployment in $RUN"
  cast to-check-sum-address "$a"
}
deploy_block() { # address -> decimal block number of its creation receipt
  local b
  b=$(jq -r --arg a "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" \
    '[.receipts[] | select((.contractAddress // "" | ascii_downcase) == $a) | .blockNumber][0] // empty' "$RUN")
  [ -n "$b" ] || die "no receipt for $1 in $RUN"
  printf '%d' "$b"
}
REGISTRY_ADDRESS=$(created ComplianceRegistry)
ESCROW_ADDRESS=$(created ComplianceEscrow)
REGISTRY_BLOCK=$(deploy_block "$REGISTRY_ADDRESS")
ESCROW_BLOCK=$(deploy_block "$ESCROW_ADDRESS")
for a in "$REGISTRY_ADDRESS" "$ESCROW_ADDRESS"; do
  [ "$(cast code "$a" --rpc-url "$CONTRACTS_RPC_URL")" != 0x ] || die "no code at $a on chain $CHAIN"
done

LINK_OK=true
if [ "$LINK_MULTIBAAS" = true ] && [ "$(grep -c 'Contract linked successfully' "$LOG" || true)" -lt 2 ]; then
  LINK_OK=false
fi

# ---------- optional Blockscout verification ----------
if [ "$VERIFY" = true ]; then
  VERIFIER_URL=${BLOCKSCOUT_VERIFIER_URL:-}
  if [ -z "$VERIFIER_URL" ]; then
    case $CHAIN in
      84532) VERIFIER_URL=https://base-sepolia.blockscout.com/api/ ;;
      11155111) VERIFIER_URL=https://eth-sepolia.blockscout.com/api/ ;;
    esac
  fi
  verify() { # address, contract path:name, abi-encoded constructor args
    (cd "$CONTRACTS" && forge verify-contract --verifier blockscout --verifier-url "$VERIFIER_URL" \
      --chain "$CHAIN" --constructor-args "$3" --watch "$1" "$2") ||
      warn "verification failed for $2 at $1 (non-fatal; retry later or use the Blockscout UI)"
  }
  if [ -z "$VERIFIER_URL" ]; then
    warn "no Blockscout verifier known for chain $CHAIN; set BLOCKSCOUT_VERIFIER_URL to verify"
  else
    verify "$REGISTRY_ADDRESS" src/ComplianceRegistry.sol:ComplianceRegistry \
      "$(cast abi-encode 'constructor(address)' "$ADMIN_ADDRESS")"
    verify "$ESCROW_ADDRESS" src/ComplianceEscrow.sol:ComplianceEscrow \
      "$(cast abi-encode 'constructor(address,address,address,uint64)' \
        "$USDC_ADDRESS" "$REGISTRY_ADDRESS" "$ADMIN_ADDRESS" "$RECLAIM_AFTER_SECONDS")"
  fi
fi

# ---------- summary ----------
say ""
say "Deployed on chain $CHAIN:"
say "  ComplianceRegistry $REGISTRY_ADDRESS (block $REGISTRY_BLOCK)"
say "  ComplianceEscrow   $ESCROW_ADDRESS (block $ESCROW_BLOCK)"
if [ -n "${EXPLORER_URL:-}" ] && [ "$CHAIN" != 31337 ]; then
  say "  ${EXPLORER_URL%/}/address/$REGISTRY_ADDRESS"
  say "  ${EXPLORER_URL%/}/address/$ESCROW_ADDRESS"
fi
say "Broadcast record: ${RUN#"$ROOT"/}"
say ""
say "Add these lines to .env:"
say "REGISTRY_ADDRESS=$REGISTRY_ADDRESS"
say "ESCROW_ADDRESS=$ESCROW_ADDRESS"

if [ "$LINK_MULTIBAAS" = false ] || [ "$LINK_OK" = false ]; then
  say ""
  say "Link in the MultiBaas UI (PRD C.3 fallback): upload contracts/out/ComplianceRegistry.sol/ComplianceRegistry.json"
  say "and contracts/out/ComplianceEscrow.sol/ComplianceEscrow.json as labels compliance_registry and"
  say "compliance_escrow, link each address under the alias of the same name, turn Sync Events on and"
  say "set the starting blocks to $REGISTRY_BLOCK and $ESCROW_BLOCK."
fi
if [ "$LINK_OK" = false ]; then
  warn "the contracts are deployed but forge-multibaas did not report 'Contract linked successfully' for both (see the 'Link Contract:' lines above)"
  warn "if this re-ran a failed broadcast, the links may already exist: check both aliases in the MultiBaas UI before linking by hand"
  exit 2
fi
