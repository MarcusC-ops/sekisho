// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";

/// @title ComplianceRegistry
/// @notice Onchain audit trail of counterparty screenings made before agent payments.
/// @dev Subjects are screened on mainnet data; the attestation lives on the demo chain.
///      Addresses are chain-agnostic, so the same 20-byte address is recorded.
contract ComplianceRegistry is AccessControl {
    /// @notice Held by the Sekisho gate backend signer. Writes screening results.
    bytes32 public constant SCREENER_ROLE = keccak256("SCREENER_ROLE");
    /// @notice Held by human compliance officers. Can override a verdict.
    bytes32 public constant OFFICER_ROLE = keccak256("OFFICER_ROLE");

    enum Verdict {
        NONE, // 0: never screened
        ALLOW, // 1: payment may proceed
        HOLD, // 2: payment must go through escrow and human review
        BLOCK // 3: payment refused
    }

    struct Screening {
        Verdict verdict;
        uint8 riskScore; // 0-100, from the policy engine
        uint64 screenedAt; // unix seconds
        uint64 expiresAt; // unix seconds; ALLOW is only valid until then
        bytes32 reportHash; // keccak256 of the canonical JSON report stored offchain
        bytes32 policyId; // keccak256 of the policy file that produced the verdict
        address screener; // gate signer or officer who wrote the current verdict
    }

    mapping(address subject => Screening) private _latest;
    uint256 public screeningCount;

    event Screened(
        address indexed subject,
        Verdict verdict,
        uint8 riskScore,
        bytes32 reportHash,
        bytes32 policyId,
        uint64 expiresAt,
        address indexed screener,
        bytes32 indexed caseId
    );

    event VerdictOverridden(
        address indexed subject,
        Verdict previous,
        Verdict next,
        bytes32 noteHash,
        address indexed officer,
        bytes32 indexed caseId
    );

    error InvalidVerdict();
    error InvalidScore();
    error InvalidTtl();

    constructor(address admin) {
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
    }

    /// @notice Record the result of an automated screening.
    function recordScreening(
        address subject,
        Verdict verdict,
        uint8 riskScore,
        uint64 ttlSeconds,
        bytes32 reportHash,
        bytes32 policyId,
        bytes32 caseId
    ) external onlyRole(SCREENER_ROLE) {
        if (verdict == Verdict.NONE) revert InvalidVerdict();
        if (riskScore > 100) revert InvalidScore();
        if (ttlSeconds == 0) revert InvalidTtl();

        uint64 nowTs = uint64(block.timestamp);
        uint64 expiresAt = nowTs + ttlSeconds;
        _latest[subject] = Screening({
            verdict: verdict,
            riskScore: riskScore,
            screenedAt: nowTs,
            expiresAt: expiresAt,
            reportHash: reportHash,
            policyId: policyId,
            screener: msg.sender
        });
        unchecked {
            screeningCount++;
        }
        emit Screened(subject, verdict, riskScore, reportHash, policyId, expiresAt, msg.sender, caseId);
    }

    /// @notice A human officer overrides the current verdict (e.g. clears a HOLD after review).
    /// @param noteHash keccak256 of the officer's review note stored offchain.
    function overrideVerdict(address subject, Verdict next, uint64 ttlSeconds, bytes32 noteHash, bytes32 caseId)
        external
        onlyRole(OFFICER_ROLE)
    {
        if (next == Verdict.NONE) revert InvalidVerdict();
        if (ttlSeconds == 0) revert InvalidTtl();

        Screening storage s = _latest[subject];
        Verdict previous = s.verdict;
        uint64 nowTs = uint64(block.timestamp);
        s.verdict = next;
        s.screenedAt = nowTs;
        s.expiresAt = nowTs + ttlSeconds;
        s.screener = msg.sender;
        // riskScore, reportHash and policyId are kept from the automated screening for audit.
        emit VerdictOverridden(subject, previous, next, noteHash, msg.sender, caseId);
    }

    function latest(address subject) external view returns (Screening memory) {
        return _latest[subject];
    }

    /// @notice True if the subject has a non-expired ALLOW verdict.
    function isCleared(address subject) public view returns (bool) {
        Screening storage s = _latest[subject];
        return s.verdict == Verdict.ALLOW && block.timestamp <= s.expiresAt;
    }

    /// @notice True if the subject's latest verdict is BLOCK. Blocks do not expire.
    function isBlocked(address subject) public view returns (bool) {
        return _latest[subject].verdict == Verdict.BLOCK;
    }
}
