"""Policy engine: one case per rule 0 to 13 (PRD 9.6), override semantics, the risk
score formula, trait classes and headlines."""

from __future__ import annotations

import pytest
from gate_testkit import error_outcome, oracle_outcome, score_outcome, trace_outcome

from sekisho_gate.config import REPO_ROOT
from sekisho_gate.policy import Override, Policy
from sekisho_gate.screening.types import CheckOutcome

POLICY_ID = "0xd55f2a7678cc2571a18073afd351f2fc13ffe4aa9c570632b94a8190f9c14719"


@pytest.fixture(scope="module")
def policy() -> Policy:
    return Policy(REPO_ROOT / "gate" / "policy" / "policy.yaml")


def trait(name: str, risk: int = 50, txs: int = 1, desc: str | None = None) -> dict:
    return {"name": name, "risk": risk, "txsCount": txs, "description": desc or f"verbatim text for {name}"}


def evidence(
    *,
    toxic: float = 0,
    traits: list | None = None,
    oracle: tuple = (False, False),
    taint: float = 0.0,
    poisoned: bool = False,
    token_action: str = "info",
    quick: CheckOutcome | None = None,
) -> dict[str, CheckOutcome]:
    return {
        "intercepta.quick_scan": quick
        or score_outcome("intercepta.quick_scan", {"toxicScore": toxic, "traits": traits or []}),
        "sanctions.oracle": oracle_outcome(*oracle),
        "trace.source_of_funds": trace_outcome(taint, ["Tornado Cash: Router → counterparty"] if taint else []),
        "intercepta.impersonation": CheckOutcome(
            name="intercepta.impersonation", status="ok",
            data={"isAddressPoisoned": poisoned, "originalAddress": "0xabc" if poisoned else None},
        ),
        "intercepta.token": CheckOutcome(
            name="intercepta.token", status="ok",
            data={"riskScore": 0, "riskLevel": "neutral", "trust": "neutral", "action": token_action, "detectors": []},
        ),
    }


ALLOW_OVERRIDE = Override(verdict="ALLOW", expires_at=4_102_444_800, case_id="cs_PRIOR", tx_hash="0x" + "1" * 64)
BLOCK_OVERRIDE = Override(verdict="BLOCK", expires_at=4_102_444_800, case_id="cs_PRIOR", tx_hash="0x" + "2" * 64)

# (id, evidence kwargs, eval kwargs, expected verdict, rule that must trigger, expected risk_score)
RULE_TABLE = [
    ("r0_block_override", {}, {"override": BLOCK_OVERRIDE}, "BLOCK", "officer_override", 0),
    ("r0_allow_override_skips_hold_trait", {"toxic": 30, "traits": [trait("mixer_transfers", 60)]},
     {"override": ALLOW_OVERRIDE}, "ALLOW", "officer_override", 60),
    ("r1_sanctions_oracle", {"oracle": (True, False)}, {}, "BLOCK", "sanctions_oracle", 100),
    ("r2_hard_block_trait", {"traits": [trait("known_scammer", 80)]}, {}, "BLOCK", "hard_block_trait:known_scammer", 95),
    ("r3_address_poisoned", {"poisoned": True}, {}, "BLOCK", "address_poisoned", 90),
    ("r4_token_block", {"token_action": "block"}, {}, "BLOCK", "token_block", 90),
    ("r5_toxic_score_block", {"toxic": 85}, {}, "BLOCK", "toxic_score_block", 85),
    ("r6_taint_block", {"taint": 60.0}, {}, "BLOCK", "taint_block", 60),
    ("r7_screening_error", {"quick": error_outcome("intercepta.quick_scan", "timeout after 3000 ms")}, {},
     "HOLD", "screening_error", 50),
    ("r8_hold_trait", {"traits": [trait("mixer_transfers", 30)]}, {}, "HOLD", "hold_trait:mixer_transfers", 50),
    ("r9_toxic_score_hold", {"toxic": 45}, {}, "HOLD", "toxic_score_hold", 45),
    ("r10_taint_hold", {"taint": 12.4}, {}, "HOLD", "taint_hold", 45),
    ("r11_token_warn", {"token_action": "warn"}, {}, "HOLD", "token_warn", 40),
    ("r12_first_time_large", {}, {"amount_usd": 30.0, "has_prior_allow": False}, "HOLD", "first_time_large", 40),
    ("r13_default", {}, {}, "ALLOW", "default", 0),
]


@pytest.mark.parametrize("case_id,ev,kw,verdict,rule,risk", RULE_TABLE, ids=[r[0] for r in RULE_TABLE])
def test_rule_table(policy, case_id, ev, kw, verdict, rule, risk):
    kw = {"amount_usd": 0.05, **kw}
    d = policy.evaluate(evidence(**ev), **kw)
    assert d.verdict == verdict
    assert rule in d.triggered_rules
    assert d.risk_score == risk
    # Every block/hold reason is one triggered rule; ALLOW has no reasons.
    assert {r["rule"] for r in d.reasons} <= set(d.triggered_rules)
    if verdict == "ALLOW":
        assert d.reasons == []
    else:
        assert any(r["rule"] == rule for r in d.reasons)
        assert all(r["severity"] in ("block", "hold") for r in d.reasons)


def test_policy_id_is_keccak_of_file_bytes(policy):
    assert policy.id == POLICY_ID
    assert policy.version == "1.0.0"
    assert policy.name == "sekisho-demo-policy"
    assert policy.ttl_for("ALLOW") == 86400 and policy.ttl_for("BLOCK") == 31536000
    assert policy.officer_clear_ttl_seconds == 3600


def test_first_time_large_needs_no_prior_allow(policy):
    d = policy.evaluate(evidence(), amount_usd=30.0, has_prior_allow=True)
    assert d.verdict == "ALLOW"
    assert policy.evaluate(evidence(), amount_usd=25.0).verdict == "ALLOW"  # strictly greater than 25


@pytest.mark.parametrize(
    "ev,expected_rule",
    [
        ({"oracle": (True, True)}, "sanctions_oracle"),
        ({"traits": [trait("sanction_address", 100)]}, "hard_block_trait:sanction_address"),
    ],
)
def test_allow_override_never_skips_sanctions(policy, ev, expected_rule):
    d = policy.evaluate(evidence(**ev), amount_usd=0.05, override=ALLOW_OVERRIDE)
    assert d.verdict == "BLOCK"
    assert expected_rule in d.triggered_rules and "officer_override" in d.triggered_rules


def test_allow_override_never_skips_fail_closed(policy):
    ev = evidence(quick=error_outcome("intercepta.quick_scan", "HTTP 500"))
    d = policy.evaluate(ev, amount_usd=0.05, override=ALLOW_OVERRIDE)
    assert d.verdict == "HOLD"
    assert "screening_error" in d.triggered_rules


@pytest.mark.parametrize(
    "ev,kw",
    [
        ({"poisoned": True}, {}),
        ({"token_action": "block"}, {}),
        ({"toxic": 95}, {}),
        ({"taint": 75.0}, {}),
        ({"token_action": "warn"}, {}),
        ({}, {"amount_usd": 100.0}),
        ({"traits": [trait("non_kyc_transfers")]}, {}),
    ],
)
def test_allow_override_skips_rules_3_to_6_and_8_to_12(policy, ev, kw):
    d = policy.evaluate(evidence(**ev), **{"amount_usd": 0.05, **kw}, override=ALLOW_OVERRIDE)
    assert d.verdict == "ALLOW"
    assert d.headline == "Cleared by a compliance officer"
    assert d.reasons == []


def test_block_override_is_block_and_keeps_other_reasons(policy):
    d = policy.evaluate(evidence(traits=[trait("mixer_transfers")]), amount_usd=0.05, override=BLOCK_OVERRIDE)
    assert d.verdict == "BLOCK"
    assert d.reasons[0]["rule"] == "officer_override" and d.reasons[0]["source"] == "officer"
    assert "hold_trait:mixer_transfers" in d.triggered_rules
    assert d.headline == "Counterparty blocked by a compliance officer"


def test_info_traits_never_change_the_verdict(policy):
    traits = [trait("fake_phishing_transfer", 99, 40), trait("zero_address_risk", 99, 12)]
    d = policy.evaluate(evidence(traits=traits), amount_usd=0.05)
    assert d.verdict == "ALLOW"
    assert d.risk_score == 0  # info trait risk is not in the formula
    assert d.triggered_rules == ["default"]


def test_unknown_traits_are_other_and_inert(policy):
    d = policy.evaluate(evidence(traits=[trait("brand_new_trait", 90)]), amount_usd=0.05)
    assert d.verdict == "ALLOW"
    assert policy.classify_trait("brand_new_trait") == "other"


def test_trait_classes(policy):
    assert policy.classify_trait("sanction_address") == "hard_block"
    assert policy.classify_trait("blacklist") == "hard_block"
    assert policy.classify_trait("mixer_transfers") == "hold"
    assert policy.classify_trait("suspicious_dex_pair_deployer") == "hold"
    assert policy.classify_trait("fake_phishing_transfer") == "info"
    assert policy.classify_trait("zero_address_risk") == "info"
    traits = policy.classified_traits([trait("mixer_transfers"), trait("zero_address_risk"), "junk"])
    assert [t["class"] for t in traits] == ["hold", "info"]
    assert traits[0]["description"] == "verbatim text for mixer_transfers"


def test_strongest_outcome_wins_and_every_rule_is_collected(policy):
    ev = evidence(toxic=50, traits=[trait("mixer_transfers", 70), trait("blacklist", 60)], taint=15.0)
    d = policy.evaluate(ev, amount_usd=0.05)
    assert d.verdict == "BLOCK"
    assert d.triggered_rules == [
        "hard_block_trait:blacklist", "hold_trait:mixer_transfers", "toxic_score_hold", "taint_hold",
    ]
    assert [r["severity"] for r in d.reasons] == ["block", "hold", "hold", "hold"]
    assert d.risk_score == 95


def test_risk_score_formula_is_capped(policy):
    ev = evidence(toxic=140, traits=[trait("mixer_transfers", 250)], taint=180.0)
    assert policy.evaluate(ev, amount_usd=0.05).risk_score == 100


def test_intercepta_reasons_are_verbatim_with_risk_and_txs(policy):
    text = "Address has direct transactions with mixers — “quoted” text, unchanged."
    d = policy.evaluate(evidence(toxic=45, traits=[trait("mixer_transfers", 61, 7, text)]), amount_usd=0.05)
    r = next(r for r in d.reasons if r["rule"] == "hold_trait:mixer_transfers")
    assert r["detail"] == text
    assert r["label"] == "mixer_transfers"
    assert (r["risk"], r["txs_count"], r["evidence_id"], r["source"]) == (61, 7, "E1", "intercepta")
    other = next(r for r in d.reasons if r["rule"] == "toxic_score_hold")
    assert "risk" not in other and "txs_count" not in other


def test_sanctions_reason_and_headline(policy):
    d = policy.evaluate(evidence(oracle=(True, True)), amount_usd=0.05)
    r = d.reasons[0]
    assert r == {
        "rule": "sanctions_oracle", "severity": "block", "source": "chainalysis",
        "label": "Sanctioned address (onchain oracle)", "detail": "isSanctioned = true on Ethereum and Base",
        "evidence_id": "E2",
    }
    assert d.headline == "Counterparty is on a sanctions list"


def test_partial_oracle_failure_still_blocks(policy):
    ev = evidence()
    ev["sanctions.oracle"] = oracle_outcome(None, True)
    assert policy.evaluate(ev, amount_usd=0.05).verdict == "BLOCK"


@pytest.mark.parametrize(
    "quick",
    [
        CheckOutcome(name="intercepta.quick_scan", status="ok", data={"traits": []}),
        CheckOutcome(name="intercepta.quick_scan", status="ok", data={"toxicScore": "high", "traits": []}),
        CheckOutcome(name="intercepta.quick_scan", status="ok", data={"toxicScore": 0, "traits": "none"}),
        CheckOutcome(name="intercepta.quick_scan", status="ok", data=None),
        CheckOutcome(name="intercepta.quick_scan", status="skipped", summary="quota"),
    ],
)
def test_unusable_quick_scan_fails_closed(policy, quick):
    d = policy.evaluate(evidence(quick=quick), amount_usd=0.05)
    assert d.verdict == "HOLD"
    assert "screening_error" in d.triggered_rules


def test_missing_quick_scan_fails_closed(policy):
    ev = evidence()
    del ev["intercepta.quick_scan"]
    assert policy.evaluate(ev, amount_usd=0.05).verdict == "HOLD"


def test_failed_optional_checks_do_not_trigger_rules(policy):
    ev = evidence()
    ev["trace.source_of_funds"] = error_outcome("trace.source_of_funds")
    ev["intercepta.impersonation"] = error_outcome("intercepta.impersonation")
    ev["intercepta.token"] = CheckOutcome(name="intercepta.token", status="skipped", summary="disabled by config")
    assert policy.evaluate(ev, amount_usd=0.05).verdict == "ALLOW"


def test_headlines(policy):
    assert policy.evaluate(evidence(), amount_usd=0.05).headline == "No policy rule triggered"
    q = error_outcome("intercepta.quick_scan")
    assert policy.evaluate(evidence(quick=q), amount_usd=0.05).headline == "Screening unavailable, payment held"
    assert (
        policy.evaluate(evidence(quick=q), amount_usd=0.05, direction="inbound").headline
        == "Screening unavailable, payer held for review"
    )
    assert policy.evaluate(evidence(traits=[trait("mixer_transfers")]), amount_usd=0.05).headline == (
        "Counterparty has mixer exposure"
    )


def test_evaluation_is_deterministic(policy):
    ev = evidence(toxic=50, traits=[trait("mixer_transfers", 70)], taint=15.0)
    a = policy.evaluate(ev, amount_usd=0.05)
    b = policy.evaluate(ev, amount_usd=0.05)
    assert a == b
