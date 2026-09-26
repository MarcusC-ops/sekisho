// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {IAccessControl} from "@openzeppelin/contracts/access/IAccessControl.sol";
import {ComplianceRegistry} from "../src/ComplianceRegistry.sol";

contract ComplianceRegistryTest is Test {
    ComplianceRegistry reg;
    address admin = makeAddr("admin");
    address screener = makeAddr("screener");
    address officer = makeAddr("officer");
    address subject = makeAddr("subject");
    bytes32 constant REPORT = keccak256("report-json");
    bytes32 constant POLICY = keccak256("policy-v1");
    bytes32 constant CASE_ID = keccak256("case-1");

    event Screened(
        address indexed subject,
        ComplianceRegistry.Verdict verdict,
        uint8 riskScore,
        bytes32 reportHash,
        bytes32 policyId,
        uint64 expiresAt,
        address indexed screener,
        bytes32 indexed caseId
    );

    function setUp() public {
        reg = new ComplianceRegistry(admin);
        vm.startPrank(admin);
        reg.grantRole(reg.SCREENER_ROLE(), screener);
        reg.grantRole(reg.OFFICER_ROLE(), officer);
        vm.stopPrank();
    }

    function _record(ComplianceRegistry.Verdict v, uint8 score, uint64 ttl) internal {
        vm.prank(screener);
        reg.recordScreening(subject, v, score, ttl, REPORT, POLICY, CASE_ID);
    }

    function test_RecordScreening_StoresAndEmits() public {
        uint64 expected = uint64(block.timestamp) + 3600;
        vm.expectEmit(true, true, true, true);
        emit Screened(subject, ComplianceRegistry.Verdict.ALLOW, 12, REPORT, POLICY, expected, screener, CASE_ID);
        _record(ComplianceRegistry.Verdict.ALLOW, 12, 3600);

        ComplianceRegistry.Screening memory s = reg.latest(subject);
        assertEq(uint8(s.verdict), uint8(ComplianceRegistry.Verdict.ALLOW));
        assertEq(s.riskScore, 12);
        assertEq(s.expiresAt, expected);
        assertEq(s.reportHash, REPORT);
        assertEq(s.policyId, POLICY);
        assertEq(s.screener, screener);
        assertEq(reg.screeningCount(), 1);
    }

    function test_RecordScreening_RevertsWithoutRole() public {
        vm.expectRevert(
            abi.encodeWithSelector(
                IAccessControl.AccessControlUnauthorizedAccount.selector, address(this), reg.SCREENER_ROLE()
            )
        );
        reg.recordScreening(subject, ComplianceRegistry.Verdict.ALLOW, 0, 60, REPORT, POLICY, CASE_ID);
    }

    function test_RecordScreening_RejectsBadInput() public {
        vm.startPrank(screener);
        vm.expectRevert(ComplianceRegistry.InvalidVerdict.selector);
        reg.recordScreening(subject, ComplianceRegistry.Verdict.NONE, 0, 60, REPORT, POLICY, CASE_ID);
        vm.expectRevert(ComplianceRegistry.InvalidScore.selector);
        reg.recordScreening(subject, ComplianceRegistry.Verdict.ALLOW, 101, 60, REPORT, POLICY, CASE_ID);
        vm.expectRevert(ComplianceRegistry.InvalidTtl.selector);
        reg.recordScreening(subject, ComplianceRegistry.Verdict.ALLOW, 0, 0, REPORT, POLICY, CASE_ID);
        vm.stopPrank();
    }

    function test_IsCleared_OnlyForFreshAllow() public {
        assertFalse(reg.isCleared(subject)); // never screened
        _record(ComplianceRegistry.Verdict.ALLOW, 5, 100);
        assertTrue(reg.isCleared(subject));
        vm.warp(block.timestamp + 101);
        assertFalse(reg.isCleared(subject)); // expired
    }

    function test_IsCleared_FalseForHold() public {
        _record(ComplianceRegistry.Verdict.HOLD, 55, 100);
        assertFalse(reg.isCleared(subject));
        assertFalse(reg.isBlocked(subject));
    }

    function test_IsBlocked_DoesNotExpire() public {
        _record(ComplianceRegistry.Verdict.BLOCK, 100, 60);
        assertTrue(reg.isBlocked(subject));
        vm.warp(block.timestamp + 365 days);
        assertTrue(reg.isBlocked(subject));
        assertFalse(reg.isCleared(subject));
    }

    function test_Override_OfficerClearsHold() public {
        _record(ComplianceRegistry.Verdict.HOLD, 55, 100);
        vm.prank(officer);
        reg.overrideVerdict(subject, ComplianceRegistry.Verdict.ALLOW, 600, keccak256("note"), CASE_ID);

        ComplianceRegistry.Screening memory s = reg.latest(subject);
        assertEq(uint8(s.verdict), uint8(ComplianceRegistry.Verdict.ALLOW));
        assertEq(s.riskScore, 55); // kept from the automated screening
        assertEq(s.reportHash, REPORT);
        assertEq(s.screener, officer);
        assertTrue(reg.isCleared(subject));
    }

    function test_Override_RevertsForNonOfficer() public {
        _record(ComplianceRegistry.Verdict.HOLD, 55, 100);
        vm.expectRevert(
            abi.encodeWithSelector(
                IAccessControl.AccessControlUnauthorizedAccount.selector, screener, reg.OFFICER_ROLE()
            )
        );
        vm.prank(screener); // the automated screener cannot clear its own holds
        reg.overrideVerdict(subject, ComplianceRegistry.Verdict.ALLOW, 600, bytes32(0), CASE_ID);
    }

    function testFuzz_ExpiryBoundary(uint64 ttl) public {
        ttl = uint64(bound(ttl, 1, 365 days));
        _record(ComplianceRegistry.Verdict.ALLOW, 0, ttl);
        vm.warp(block.timestamp + ttl);
        assertTrue(reg.isCleared(subject)); // valid up to and including expiresAt
        vm.warp(block.timestamp + 1);
        assertFalse(reg.isCleared(subject));
    }
}
