// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {ComplianceRegistry} from "./ComplianceRegistry.sol";

/// @title ComplianceEscrow
/// @notice Holds stablecoin payments to medium-risk counterparties until a compliance
///         officer clears the counterparty in the ComplianceRegistry and releases the funds.
/// @dev The rule "held funds only move to a cleared counterparty" is enforced here, onchain.
contract ComplianceEscrow is AccessControl, ReentrancyGuard {
    using SafeERC20 for IERC20;

    bytes32 public constant OFFICER_ROLE = keccak256("OFFICER_ROLE");

    enum Status {
        NONE,
        HELD,
        RELEASED,
        REFUNDED
    }

    struct Hold {
        address payer;
        address payee;
        uint256 amount;
        uint64 createdAt;
        Status status;
        bytes32 caseId;
    }

    IERC20 public immutable token;
    ComplianceRegistry public immutable registry;
    /// @notice Seconds after which the payer may reclaim an unresolved hold.
    uint64 public immutable reclaimAfter;

    uint256 public nextHoldId = 1;
    uint256 public totalHeld;
    mapping(uint256 holdId => Hold) public holds;

    event Held(uint256 indexed holdId, bytes32 indexed caseId, address indexed payer, address payee, uint256 amount);
    event Released(
        uint256 indexed holdId, bytes32 indexed caseId, address indexed payee, uint256 amount, address officer
    );
    event Refunded(uint256 indexed holdId, bytes32 indexed caseId, address indexed payer, uint256 amount, address by);

    error PayeeBlocked();
    error ZeroAmount();
    error NotHeld();
    error NotCleared();
    error NotPayer();
    error TooEarly();

    constructor(IERC20 token_, ComplianceRegistry registry_, address admin, uint64 reclaimAfter_) {
        token = token_;
        registry = registry_;
        reclaimAfter = reclaimAfter_;
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
    }

    /// @notice Payer agent locks funds for a payee under review. Caller must approve `amount` first.
    function deposit(address payee, uint256 amount, bytes32 caseId) external nonReentrant returns (uint256 holdId) {
        if (amount == 0) revert ZeroAmount();
        if (registry.isBlocked(payee)) revert PayeeBlocked();

        holdId = nextHoldId++;
        holds[holdId] = Hold({
            payer: msg.sender,
            payee: payee,
            amount: amount,
            createdAt: uint64(block.timestamp),
            status: Status.HELD,
            caseId: caseId
        });
        totalHeld += amount;

        token.safeTransferFrom(msg.sender, address(this), amount);
        emit Held(holdId, caseId, msg.sender, payee, amount);
    }

    /// @notice Officer releases held funds. Reverts unless the registry shows the payee as cleared.
    function release(uint256 holdId) external onlyRole(OFFICER_ROLE) nonReentrant {
        Hold storage h = holds[holdId];
        if (h.status != Status.HELD) revert NotHeld();
        if (!registry.isCleared(h.payee)) revert NotCleared();

        h.status = Status.RELEASED;
        totalHeld -= h.amount;

        token.safeTransfer(h.payee, h.amount);
        emit Released(holdId, h.caseId, h.payee, h.amount, msg.sender);
    }

    /// @notice Officer refunds at any time; the payer can reclaim after `reclaimAfter` seconds.
    function refund(uint256 holdId) external nonReentrant {
        Hold storage h = holds[holdId];
        if (h.status != Status.HELD) revert NotHeld();
        if (!hasRole(OFFICER_ROLE, msg.sender)) {
            if (msg.sender != h.payer) revert NotPayer();
            if (block.timestamp < uint256(h.createdAt) + reclaimAfter) revert TooEarly();
        }

        h.status = Status.REFUNDED;
        totalHeld -= h.amount;

        token.safeTransfer(h.payer, h.amount);
        emit Refunded(holdId, h.caseId, h.payer, h.amount, msg.sender);
    }
}
