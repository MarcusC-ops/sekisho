"""Check names, evidence ids and per-check timeouts (PRD 9.2), shared by the pipeline,
the policy engine, the report builder and the analyst."""

QUICK_SCAN = "intercepta.quick_scan"
ORACLE = "sanctions.oracle"
TRACE = "trace.source_of_funds"
IMPERSONATION = "intercepta.impersonation"
TOKEN = "intercepta.token"
DEEP_SCAN = "intercepta.deep_scan"

# Evidence ids are fixed per check so reasons, the report and the analyst agree.
EVIDENCE_IDS = {
    QUICK_SCAN: "E1",
    ORACLE: "E2",
    TRACE: "E3",
    IMPERSONATION: "E4",
    TOKEN: "E5",
    DEEP_SCAN: "E6",
}

# Order in which checks are listed in decisions and reports.
CHECK_ORDER = [QUICK_SCAN, ORACLE, TRACE, IMPERSONATION, TOKEN]

# Seconds (PRD 9.2).
TIMEOUTS_S = {
    QUICK_SCAN: 3.0,
    ORACLE: 2.0,
    TRACE: 6.0,
    IMPERSONATION: 3.0,
    TOKEN: 3.0,
    DEEP_SCAN: 5.0,
}
OVERALL_BUDGET_S = 8.0

CHAIN_NAMES = {"1": "Ethereum", "8453": "Base", "84532": "Base Sepolia", "11155111": "Sepolia"}
