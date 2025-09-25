import os
import re
import json
import time
import sys
import requests
from web3 import Web3
from typing import List, Dict, Optional, Tuple

# Chain configurations
CHAIN_CONFIG = {
    "Ethereum": {
        "rpc_endpoints": [
            "https://cloudflare-eth.com",
            "https://ethereum.publicnode.com",
            "https://eth.public-rpc.com",
            "https://eth.nownodes.io"
        ],
        "tokens": {
            "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
            "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
            "WETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        }
    },
    "BSC": {
        "rpc_endpoints": [
            "https://bsc-dataseed1.binance.org",
            "https://bsc-dataseed2.binance.org",
            "https://bsc-dataseed3.binance.org",
            "https://bsc-dataseed4.binance.org"
        ],
        "tokens": {
            "USDT": "0x55d398326f99059fF775485246999027B3197955",
            "USDC": "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d",
            "CAKE": "0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82",
        }
    },
    "Polygon": {
        "rpc_endpoints": [
            "https://polygon-rpc.com",
            "https://rpc-mainnet.matic.network",
            "https://matic-mainnet.chainstacklabs.com"
        ],
        "tokens": {
            "USDT": "0xc2132D05D31c914a87C6611C10748AEb04B58e8F",
            "USDC": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
            "WMATIC": "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
        }
    },
    "Avalanche": {
        "rpc_endpoints": [
            "https://api.avax.network/ext/bc/C/rpc"  # Keep your working Avalanche RPC
        ],
        "tokens": {
            "USDT": "0x9702230A8Ea53601f5cD2dc00fDBc13d4dF4A8c7",
            "USDC": "0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E",
            "WAVAX": "0xB31f66AA3C1e785363F0875A1B74E27b85FD66c7",
        }
    }
}

# Avalanche X-Chain API endpoint
AVAX_X_CHAIN_API = "https://api.avax.network/ext/bc/X"

# Standard ERC20 ABI for balanceOf
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function"
    }
]

# Rate limiting settings
RATE_LIMIT_DELAY = 0.2  # 200ms between calls
MAX_RETRIES = 3

def log(message: str, end: str = "\n"):
    """Print message with immediate flush for PowerShell."""
    print(message, end=end, flush=True)
    sys.stdout.flush()

def check_token_balance(w3: Web3, token_address: str, wallet_address: str) -> Tuple[float, int]:
    """Check ERC20 token balance."""
    try:
        token_contract = w3.eth.contract(address=token_address, abi=ERC20_ABI)
        decimals = token_contract.functions.decimals().call()
        balance = token_contract.functions.balanceOf(wallet_address).call()
        return float(balance) / (10 ** decimals), decimals
    except Exception as e:
        log(f"Error checking token {token_address}: {e}")
        return 0.0, 18

def get_working_provider(chain: str, max_retries: int = 3) -> Optional[Web3]:
    """
    Try to connect to each RPC endpoint with retries until a working one is found.
    """
    if chain not in CHAIN_CONFIG:
        raise ValueError(f"Unsupported chain: {chain}")
    
    endpoints = CHAIN_CONFIG[chain]["rpc_endpoints"]
    
    for endpoint in endpoints:
        for attempt in range(max_retries):
            try:
                w3 = Web3(Web3.HTTPProvider(endpoint))
                # Verify connection by trying to get the latest block
                if w3.is_connected() and w3.eth.block_number > 0:
                    log(f"  Connected to {chain} using {endpoint}")
                    return w3
            except Exception as e:
                if attempt == max_retries - 1:
                    log(f"  Failed to connect to {endpoint} after {max_retries} attempts")
                time.sleep(1)  # Wait 1 second between retries
    
    return None

def check_evm_balances(address: str, chain: str) -> Dict:
    """Check both native and token balances for an EVM address."""
    balances = {"native": 0.0, "tokens": {}}
    
    w3 = get_working_provider(chain)
    if not w3:
        log(f"  Failed to connect to any {chain} RPC endpoint")
        return balances
    
    # Check native balance
    try:
        native_balance = w3.eth.get_balance(address)
        native_balance_eth = float(w3.from_wei(native_balance, 'ether'))
        if native_balance_eth > 0:
            balances["native"] = native_balance_eth
    except Exception as e:
        log(f"  Error checking native balance: {e}")
    
    # Check token balances
    for token_symbol, token_address in CHAIN_CONFIG[chain]["tokens"].items():
        time.sleep(RATE_LIMIT_DELAY)
        balance, decimals = check_token_balance(w3, token_address, address)
        if balance > 0:
            balances["tokens"][token_symbol] = {
                "balance": balance,
                "decimals": decimals
            }
    
    return balances

def check_xchain_balance(address: str) -> Dict:
    """Check X-Chain AVAX and asset balances."""
    assets = {}
    api_address = address[2:] if address.startswith("X-") else address
    
    try:
        response = requests.post(
            AVAX_X_CHAIN_API,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "avm.getAllBalances",
                "params": {"address": api_address}
            },
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        if response.status_code == 200:
            result = response.json().get("result", {})
            for balance in result.get("balances", []):
                asset_id = balance.get("asset", "AVAX")
                amount = float(balance.get("balance", 0))
                if asset_id == "AVAX":
                    amount /= 1e9  # Convert nAVAX to AVAX
                if amount > 0:
                    assets[asset_id] = amount
                    
    except Exception as e:
        log(f"Error checking X-Chain assets: {e}")
    
    return assets

def extract_addresses(group_text: str) -> Tuple[List[Dict], List[Dict]]:
    """Extract EVM and X-Chain addresses from text."""
    evm_wallets = []
    xchain_wallets = []
    
    # Extract source info for reference
    source_match = re.search(r"Source Info: \[(.+?)\]", group_text)
    source_info = source_match.group(1) if source_match else "Unknown source"
    
    # Extract EVM addresses with their index and path
    evm_section = re.search(r"=== EVM Wallets ===\n(.*?)\n(?===|\Z)", group_text, re.DOTALL)
    if evm_section:
        evm_matches = re.finditer(
            r"EVM Wallet (\d+):\n\s+Address: (0x[a-fA-F0-9]{40})\n\s+Path: (m/[0-9'/]+)",
            evm_section.group(1)
        )
        for match in evm_matches:
            index, address, path = match.groups()
            evm_wallets.append({
                "index": int(index),
                "address": address,
                "path": path
            })
    
    # Extract X-Chain addresses with their index
    xchain_section = re.search(r"=== X-Chain Wallets ===\n(.*?)(?:\n\n|\Z)", group_text, re.DOTALL)
    if xchain_section:
        xchain_matches = re.finditer(
            r"X-Chain Wallet (\d+):\n\s+Address: (X-[a-zA-Z0-9]+)",
            xchain_section.group(1)
        )
        for match in xchain_matches:
            index, address = match.groups()
            xchain_wallets.append({
                "index": int(index),
                "address": address
            })
    
    return evm_wallets, xchain_wallets

def check_balances(input_file: str, output_file: str):
    """Extract addresses and check their balances."""
    try:
        log("\n=== Starting Balance Check ===")
        log(f"Input file: {input_file}")
        log(f"Output file: {output_file}")
        
        log("\nReading input file...", end="")
        with open(input_file, 'r', encoding='utf-8') as f:
            content = f.read()
        log(" ✓")
        
        # Split into groups and process
        groups = [g.strip() for g in content.split("=" * 80) if g.strip()]
        total_groups = len(groups)
        log(f"Found {total_groups} wallet groups to process")
        
        results = []
        non_empty_wallets = 0
        
        for idx, group_text in enumerate(groups, 1):
            log(f"\n{'-' * 40}")
            log(f"Processing group {idx}/{total_groups}")
            
            # Extract source info for reference
            source_match = re.search(r"Source Info: \[(.+?)\]", group_text)
            source_info = source_match.group(1) if source_match else "Unknown source"
            
            evm_wallets, xchain_wallets = extract_addresses(group_text)
            group_has_balance = False
            
            group_result = {
                "source_info": source_info,
                "evm_balances": {},
                "xchain_balances": {}
            }
            
            # Check EVM balances
            for wallet in evm_wallets:
                address = wallet["address"]
                log(f"\nChecking EVM Wallet {wallet['index']} ({address})")
                log(f"  Path: {wallet['path']}")
                address_has_balance = False
                
                for chain in CHAIN_CONFIG:
                    balances = check_evm_balances(address, chain)
                    if balances["native"] > 0 or balances["tokens"]:
                        group_has_balance = True
                        address_has_balance = True
                        group_result["evm_balances"][address] = {
                            "index": wallet["index"],
                            "path": wallet["path"],
                            "chains": group_result["evm_balances"].get(address, {})
                        }
                        group_result["evm_balances"][address]["chains"][chain] = balances
                
                if address_has_balance:
                    log("  Found balance!")
                else:
                    log("  No balance found")
            
            # Check X-Chain balances
            for wallet in xchain_wallets:
                address = wallet["address"]
                log(f"\nChecking X-Chain Wallet {wallet['index']} ({address})")
                balances = check_xchain_balance(address)
                if balances:
                    group_has_balance = True
                    group_result["xchain_balances"][address] = {
                        "index": wallet["index"],
                        "balances": balances
                    }
                    log("  Found balance!")
                else:
                    log("  No balance found")
            
            # Save if any balances found
            if group_has_balance:
                non_empty_wallets += 1
                results.append(group_result)
                
                # Save progress
                log("\nSaving progress...", end="")
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump({
                        "total_groups_checked": idx,
                        "non_empty_wallets": non_empty_wallets,
                        "last_updated": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "wallet_balances": results
                    }, f, indent=2)
                log(" ✓")
        
        log(f"\n{'-' * 40}")
        log("=== Balance Check Complete ===")
        log(f"Total groups checked: {total_groups}")
        log(f"Groups with balances: {non_empty_wallets}")
        log(f"Results saved to: {output_file}")
        
    except Exception as e:
        log(f"\n❌ Error processing file: {str(e)}")

if __name__ == "__main__":
    INPUT_FILE = "offline_wallets.txt"
    OUTPUT_FILE = f"wallet_balances_{int(time.time())}.json"
    
    if not os.path.exists(INPUT_FILE):
        log(f"❌ Error: Input file '{INPUT_FILE}' not found!")
    else:
        check_balances(INPUT_FILE, OUTPUT_FILE) 
