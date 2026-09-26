// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script, console2} from "forge-std/Script.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {MultiBaas} from "forge-multibaas/MultiBaas.sol";
import {ComplianceRegistry} from "../src/ComplianceRegistry.sol";
import {ComplianceEscrow} from "../src/ComplianceEscrow.sol";

/// @notice Deploys the registry and escrow, grants roles, and links both into MultiBaas.
/// Env: PRIVATE_KEY (deployer = admin), SCREENER_ADDRESS, OFFICER_ADDRESS, USDC_ADDRESS,
///      RECLAIM_AFTER_SECONDS (optional, default 86400), LINK_MULTIBAAS ("true" to link),
///      MULTIBAAS_URL and MULTIBAAS_API_KEY (admin key) when linking.
contract Deploy is Script {
    function run() external {
        uint256 pk = vm.envUint("PRIVATE_KEY");
        address admin = vm.addr(pk);
        address screener = vm.envAddress("SCREENER_ADDRESS");
        address officer = vm.envAddress("OFFICER_ADDRESS");
        address usdc = vm.envAddress("USDC_ADDRESS");
        uint64 reclaimAfter = uint64(vm.envOr("RECLAIM_AFTER_SECONDS", uint256(86400)));
        bool linkMb = vm.envOr("LINK_MULTIBAAS", false);

        vm.startBroadcast(pk);

        ComplianceRegistry registry = new ComplianceRegistry(admin);
        ComplianceEscrow escrow = new ComplianceEscrow(IERC20(usdc), registry, admin, reclaimAfter);

        registry.grantRole(registry.SCREENER_ROLE(), screener);
        registry.grantRole(registry.OFFICER_ROLE(), officer);
        escrow.grantRole(escrow.OFFICER_ROLE(), officer);

        if (linkMb) {
            // Label = ABI name in the MultiBaas library, alias = name for the deployed address.
            MultiBaas.linkContractWithOptions(
                "ComplianceRegistry",
                address(registry),
                MultiBaas.withOptions("compliance_registry", "compliance_registry", "1.0", "-10")
            );
            MultiBaas.linkContractWithOptions(
                "ComplianceEscrow",
                address(escrow),
                MultiBaas.withOptions("compliance_escrow", "compliance_escrow", "1.0", "-10")
            );
        }

        vm.stopBroadcast();

        console2.log("ComplianceRegistry:", address(registry));
        console2.log("ComplianceEscrow:  ", address(escrow));
    }
}
