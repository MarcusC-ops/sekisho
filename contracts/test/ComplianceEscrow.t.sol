// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {IAccessControl} from "@openzeppelin/contracts/access/IAccessControl.sol";
import {ComplianceRegistry} from "../src/ComplianceRegistry.sol";
import {ComplianceEscrow} from "../src/ComplianceEscrow.sol";
import {MockUSDC} from "./mocks/MockUSDC.sol";

contract ComplianceEscrowTest is Test {
    ComplianceRegistry reg;
    ComplianceEscrow escrow;
    MockUSDC usdc;

    address admin = makeAddr("admin");
    address screener = makeAddr("screener");
    address officer = makeAddr("officer");
    address payer = makeAddr("payerAgent");
    address payee = makeAddr("payeeAgent");
    bytes32 constant CASE_ID = keccak256("case-42");
    uint64 constant RECLAIM_AFTER = 1 days;
    uint256 constant AMOUNT = 5_000_000; // 5 USDC

    function setUp() public {
        usdc = new MockUSDC();
        reg = new ComplianceRegistry(admin);
        escrow = new ComplianceEscrow(usdc, reg, admin, RECLAIM_AFTER);

        vm.startPrank(admin);
        reg.grantRole(reg.SCREENER_ROLE(), screener);
        reg.grantRole(reg.OFFICER_ROLE(), officer);
        escrow.grantRole(escrow.OFFICER_ROLE(), officer);
        vm.stopPrank();

        usdc.mint(payer, 100_000_000);
        vm.prank(payer);
        usdc.approve(address(escrow), type(uint256).max);
    }

    function _screen(ComplianceRegistry.Verdict v) internal {
        vm.prank(screener);
        reg.recordScreening(payee, v, 50, 1 hours, keccak256("r"), keccak256("p"), CASE_ID);
    }

    function _deposit() internal returns (uint256 id) {
        vm.prank(payer);
        id = escrow.deposit(payee, AMOUNT, CASE_ID);
    }

    function test_Deposit_LocksFunds() public {
        _screen(ComplianceRegistry.Verdict.HOLD);
        uint256 id = _deposit();
        assertEq(id, 1);
        assertEq(usdc.balanceOf(address(escrow)), AMOUNT);
        assertEq(escrow.totalHeld(), AMOUNT);
        (address p, address q, uint256 amt,, ComplianceEscrow.Status st, bytes32 c) = escrow.holds(id);
        assertEq(p, payer);
        assertEq(q, payee);
        assertEq(amt, AMOUNT);
        assertEq(uint8(st), uint8(ComplianceEscrow.Status.HELD));
        assertEq(c, CASE_ID);
    }

    function test_Deposit_RevertsForBlockedPayee() public {
        _screen(ComplianceRegistry.Verdict.BLOCK);
        vm.prank(payer);
        vm.expectRevert(ComplianceEscrow.PayeeBlocked.selector);
        escrow.deposit(payee, AMOUNT, CASE_ID);
    }

    function test_Deposit_RevertsOnZero() public {
        vm.prank(payer);
        vm.expectRevert(ComplianceEscrow.ZeroAmount.selector);
        escrow.deposit(payee, 0, CASE_ID);
    }

    function test_Release_RevertsUntilCleared_ThenPays() public {
        _screen(ComplianceRegistry.Verdict.HOLD);
        uint256 id = _deposit();

        vm.prank(officer);
        vm.expectRevert(ComplianceEscrow.NotCleared.selector);
        escrow.release(id); // onchain rule: no release while counterparty is on HOLD

        vm.prank(officer);
        reg.overrideVerdict(payee, ComplianceRegistry.Verdict.ALLOW, 1 hours, keccak256("reviewed"), CASE_ID);

        vm.prank(officer);
        escrow.release(id);
        assertEq(usdc.balanceOf(payee), AMOUNT);
        assertEq(escrow.totalHeld(), 0);

        vm.prank(officer);
        vm.expectRevert(ComplianceEscrow.NotHeld.selector);
        escrow.release(id); // cannot release twice
    }

    function test_Release_RevertsIfClearanceExpired() public {
        _screen(ComplianceRegistry.Verdict.HOLD);
        uint256 id = _deposit();
        vm.prank(officer);
        reg.overrideVerdict(payee, ComplianceRegistry.Verdict.ALLOW, 60, bytes32(0), CASE_ID);
        vm.warp(block.timestamp + 61);
        vm.prank(officer);
        vm.expectRevert(ComplianceEscrow.NotCleared.selector);
        escrow.release(id);
    }

    function test_Release_OnlyOfficer() public {
        _screen(ComplianceRegistry.Verdict.HOLD);
        uint256 id = _deposit();
        vm.expectRevert(
            abi.encodeWithSelector(
                IAccessControl.AccessControlUnauthorizedAccount.selector, payer, escrow.OFFICER_ROLE()
            )
        );
        vm.prank(payer);
        escrow.release(id);
    }

    function test_Refund_ByOfficerAnytime() public {
        _screen(ComplianceRegistry.Verdict.HOLD);
        uint256 id = _deposit();
        uint256 before = usdc.balanceOf(payer);
        vm.prank(officer);
        escrow.refund(id);
        assertEq(usdc.balanceOf(payer), before + AMOUNT);
        assertEq(escrow.totalHeld(), 0);
    }

    function test_Refund_ByPayerOnlyAfterTimeout() public {
        _screen(ComplianceRegistry.Verdict.HOLD);
        uint256 id = _deposit();

        vm.prank(payer);
        vm.expectRevert(ComplianceEscrow.TooEarly.selector);
        escrow.refund(id);

        vm.prank(payee);
        vm.expectRevert(ComplianceEscrow.NotPayer.selector);
        escrow.refund(id);

        vm.warp(block.timestamp + RECLAIM_AFTER);
        vm.prank(payer);
        escrow.refund(id);
        assertEq(escrow.totalHeld(), 0);
    }

    function testFuzz_DepositReleaseAccounting(uint256 amount) public {
        amount = bound(amount, 1, 100_000_000);
        _screen(ComplianceRegistry.Verdict.HOLD);
        vm.prank(payer);
        uint256 id = escrow.deposit(payee, amount, CASE_ID);
        assertEq(escrow.totalHeld(), amount);

        vm.startPrank(officer);
        reg.overrideVerdict(payee, ComplianceRegistry.Verdict.ALLOW, 1 hours, bytes32(0), CASE_ID);
        escrow.release(id);
        vm.stopPrank();

        assertEq(usdc.balanceOf(payee), amount);
        assertEq(usdc.balanceOf(address(escrow)), 0);
        assertEq(escrow.totalHeld(), 0);
    }
}
