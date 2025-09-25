import os
import re
import json
import time
from web3 import Web3
from eth_account import Account
from tqdm import tqdm
from typing import List, Tuple, Dict, Optional
from mnemonic import Mnemonic
import gc  # For manual garbage collection
import signal
import sys
from pathlib import Path
import hashlib
import base58
import traceback
from bip_utils import (
    Bip39SeedGenerator,
    Bip44,
    Bip44Coins,
    Bip44Changes,
    Secp256k1PrivateKey,
    AvaxXChainAddr
)

# Disable non-secure key generation warnings
Account.enable_unaudited_hdwallet_features()

# File containing extracted seed phrases in your specified format
INPUT_FILE = "filtered_seeds.txt"
PRIVATE_KEYS_FILE = "private_keys.txt"  # New file for private keys

# Output files with timestamps
timestamp = time.strftime("%Y%m%d_%H%M%S")
OFFLINE_WALLETS_FILE = f"offline_wallets_{timestamp}.txt"
PRIVATE_KEY_WALLETS_FILE = f"private_key_wallets_{timestamp}.txt"  # New output file for private key derived wallets

# Number of wallets to derive per seed
WALLETS_PER_SEED = 10

# Security settings
CLEAR_MEMORY_INTERVAL = 10
MAX_FAILED_ATTEMPTS = 3

# Chunk size for reading large files (1MB)
CHUNK_SIZE = 1024 * 1024

# Ensure BIP39 support
try:
    from mnemonic import Mnemonic
except ImportError:
    raise ImportError("Please run: pip install mnemonic web3 tqdm hdwallet")

mnemo = Mnemonic("english")

def secure_clear_variables(*variables):
    """Securely clear sensitive variables from memory."""
    for var in variables:
        if isinstance(var, str):
            var = '0' * len(var)
        elif isinstance(var, list):
            for i in range(len(var)):
                var[i] = '0' * len(str(var[i]))
        elif isinstance(var, dict):
            for k in var:
                var[k] = '0' * len(str(var[k]))
    gc.collect()

def log(message: str, end="\n", flush=True):
    """Print log message with immediate flush for PowerShell compatibility."""
    print(message, end=end, flush=True)
    sys.stdout.flush()  # Extra flush for PowerShell
    if flush:  # Force buffer clear
        sys.stdout.write("\r")  # Carriage return for PowerShell
        sys.stdout.flush()

def extract_seeds(filepath: str) -> List[Tuple[str, str]]:
    """Process large file in chunks and extract valid seed phrases.
    Supports three formats:
    1. Original format with ========= blocks
    2. Simple format with seed phrases separated by empty lines
    3. Source info format: [TIMESTAMP] Found in: PATH followed by seed phrase
    """
    seeds = []
    current_block = []
    is_in_block = False
    total_lines = sum(1 for _ in open(filepath, 'r', encoding='utf-8'))
    
    log(f"[+] Opening file: {filepath}")
    log(f"[+] Total lines to process: {total_lines:,}")
    log("[+] Starting seed phrase extraction...")
    
    try:
        with open(filepath, 'r', encoding='utf-8') as file:
            # First, try to detect the format by reading first non-empty line
            first_line = ""
            while True:
                line = file.readline().strip()
                if line:
                    first_line = line
                    break
            
            # Reset file pointer
            file.seek(0)
            
            # Determine format based on first non-empty line
            is_block_format = first_line.startswith('=' * 80)
            is_source_info_format = first_line.startswith('[') and '] Found in:' in first_line
            
            if is_block_format:
                # Original block format processing
                for line_num, line in enumerate(tqdm(file, total=total_lines, desc="Reading file"), 1):
                    line = line.strip()
                    
                    if line.startswith('=' * 80):
                        if is_in_block:
                            seed_info = process_block(current_block)
                            if seed_info:
                                seeds.append(seed_info)
                            current_block = []
                        is_in_block = True
                        continue
                    
                    if is_in_block:
                        current_block.append(line)
                
                # Process any remaining block
                if current_block:
                    seed_info = process_block(current_block)
                    if seed_info:
                        seeds.append(seed_info)
                        
            elif is_source_info_format:
                # Source info format processing (like private keys format)
                current_source = ""
                for line_num, line in enumerate(tqdm(file, total=total_lines, desc="Reading file"), 1):
                    line = line.strip()
                    
                    if not line:
                        continue
                        
                    if line.startswith('[') and '] Found in:' in line:
                        current_source = line
                    else:
                        # Check if line looks like a seed phrase (words separated by spaces)
                        words = line.split()
                        if len(words) in [12, 15, 18, 21, 24] and all(len(word) >= 3 for word in words):
                            if mnemo.check(' '.join(words)):
                                seeds.append((' '.join(words).lower(), current_source or f"[Line: {line_num}]"))
                        current_source = ""
                        
            else:
                # Simple format processing - seed phrases separated by empty lines
                current_phrase = ""
                for line_num, line in enumerate(tqdm(file, total=total_lines, desc="Reading file"), 1):
                    line = line.strip()
                    
                    if line:  # Non-empty line
                        words = line.split()
                        if len(words) in [12, 15, 18, 21, 24] and all(len(word) >= 3 for word in words):
                            if mnemo.check(' '.join(words)):
                                seeds.append((' '.join(words).lower(), f"[Line: {line_num}]"))
    
    except Exception as e:
        log(f"[!] Error reading file: {e}")
        return []
    
    log(f"[+] Found {len(seeds):,} valid seed phrases")
    return seeds


def process_block(block: List[str]) -> Tuple[str, str]:
    """
    Process a block of lines to extract seed phrase and source info.
    Returns tuple of (seed_phrase, source_info) or None if invalid.
    """
    seed_phrase = None
    timestamp = None
    quality = None
    word_count = None
    source_file = None
    
    for line in block:
        if line.startswith("TIMESTAMP: "):
            timestamp = line[11:]
        elif line.startswith("QUALITY: "):
            quality = line[9:]
        elif line.startswith("WORD COUNT: "):
            word_count = line[12:]
        elif line.startswith("SOURCE FILE: "):
            source_file = line[13:]
        elif line.startswith("SEED PHRASE: "):
            seed_phrase = line[13:].strip().lower()
    
    if seed_phrase and mnemo.check(seed_phrase):
        source_info = f"[Timestamp: {timestamp}] [Quality: {quality}] [Words: {word_count}] [Source: {source_file}]"
        return (seed_phrase, source_info)
    
    return None


def validate_mnemonic(mnemonic: str) -> Tuple[bool, str]:
    """Validate a mnemonic phrase including BIP39 checksum.
    Returns (is_valid, reason)"""
    try:
        # Split and check word count
        words = mnemonic.split()
        if len(words) not in [12, 15, 18, 21, 24]:
            return False, f"Invalid word count: {len(words)} (must be 12, 15, 18, 21, or 24)"
            
        # Check if it's a valid mnemonic (this includes checksum verification)
        if not mnemo.check(mnemonic):
            return False, "Failed BIP39 checksum verification"
            
        return True, "Valid"
    except Exception as e:
        return False, f"Validation error: {str(e)}"

def derive_evm_wallets(seed_phrase: str, count: int = WALLETS_PER_SEED) -> List[Tuple[str, str]]:
    """Derive multiple EVM wallets from a single seed phrase.
    Returns list of (address, derivation_path) tuples."""
    wallets = []
    try:
        # Validate mnemonic first
        is_valid, reason = validate_mnemonic(seed_phrase)
        if not is_valid:
            log(f"Skipping EVM derivation - {reason}")
            return []
            
        for i in range(count):
            # Derive with different paths for each wallet
            derivation_path = f"m/44'/60'/0'/0/{i}"
            acct = Account.from_mnemonic(seed_phrase, account_path=derivation_path)
            wallets.append((acct.address, derivation_path))
            log(f"Derived EVM address {i}: {acct.address} (path: {derivation_path})")
    except Exception as e:
        log(f"Error deriving EVM wallets: {e}")
    return wallets


def create_xchain_address(public_key: bytes) -> str:
    try:
        sha256_hash = hashlib.sha256(public_key).digest()
        ripemd160_hash = hashlib.new('ripemd160', sha256_hash).digest()
        
        version_byte = b'\x00'  # Version byte for X-Chain
        payload = version_byte + ripemd160_hash
        
        checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
        binary_address = payload + checksum
        
        address = base58.b58encode(binary_address).decode('utf-8')
        return f"X-{address}"
    except Exception as e:
        log(f"Error creating X-Chain address: {str(e)}\nTraceback: {traceback.format_exc()}")
        return ""


def derive_xchain_wallets(seed_phrase: str, num_wallets: int) -> List[str]:
    """Derive Avalanche X-Chain wallets using BIP44 with built-in AVAX support."""
    try:
        # Validate mnemonic with checksum
        is_valid, reason = validate_mnemonic(seed_phrase)
        if not is_valid:
            log(f"Skipping X-Chain derivation - {reason}")
            return []
            
        try:
            # Generate seed bytes
            seed_bytes = Bip39SeedGenerator(seed_phrase).Generate()
            
            # Use BIP44 derivation path for AVAX X-Chain specifically
            bip44_ctx = Bip44.FromSeed(seed_bytes, Bip44Coins.AVAX_X_CHAIN)
            
            addresses = []
            for idx in range(num_wallets):
                try:
                    # Get the full derivation path and derive address
                    acc = bip44_ctx.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(idx)
                    address = acc.PublicKey().ToAddress()
                    if address:
                        addresses.append(address)
                        log(f"Derived X-Chain address {idx}: {address}")
                        
                except Exception as e:
                    log(f"Error deriving address at index {idx}: {e}")
                    continue
            
            return addresses
            
        except Exception as e:
            log(f"Error in wallet derivation: {str(e)}")
            return []
        
    except Exception as e:
        log(f"Error deriving X-Chain wallets: {str(e)}\nTraceback: {traceback.format_exc()}")
        return []


class WalletGroup:
    def __init__(self, seed: str, source_info: str):
        self.seed = seed
        self.source_info = source_info
        self.evm_wallets: List[Tuple[str, str]] = []  # (address, path)
        self.xchain_wallets: List[str] = []  # List of X-Chain addresses

    def __str__(self) -> str:
        output = f"\n{'=' * 80}\n"
        output += f"=== Seed Group ===\n"
        output += f"SEED PHRASE: {self.seed}\n"
        output += f"Source Info: {self.source_info}\n\n"
        
        output += "=== EVM Wallets ===\n"
        for idx, (address, path) in enumerate(self.evm_wallets, 1):
            output += f"EVM Wallet {idx}:\n"
            output += f"  Address: {address}\n"
            output += f"  Path: {path}\n"
        
        output += "\n=== X-Chain Wallets ===\n"
        for idx, address in enumerate(self.xchain_wallets, 1):
            output += f"X-Chain Wallet {idx}:\n"
            output += f"  Address: {address}\n"
        
        output += f"\n{'=' * 80}\n"
        return output

def derive_all_wallets(seed_entries: List[Tuple[str, str]]) -> List[WalletGroup]:
    """Derive all wallets offline without making any API calls."""
    wallet_groups = []
    total_seeds = len(seed_entries)
    valid_seeds = 0
    invalid_seeds = 0
    
    log(f"[+] Starting wallet derivation for {total_seeds:,} seed phrases")
    log(f"[+] Deriving {WALLETS_PER_SEED} wallets per seed")
    log("[+] This process is completely offline - no API calls will be made")
    
    for idx, (seed, source_info) in enumerate(tqdm(seed_entries, desc="Deriving wallets"), 1):
        log(f"\n{'='*80}")
        log(f"Processing seed {idx}/{total_seeds}")
        log(f"Source info: {source_info}")
        
        # Validate seed first
        is_valid, reason = validate_mnemonic(seed)
        if not is_valid:
            log(f"Invalid seed - {reason}")
            invalid_seeds += 1
            continue
            
        valid_seeds += 1
        group = WalletGroup(seed, source_info)
        
        # Derive EVM wallets
        log(f"\nDeriving EVM wallets:")
        group.evm_wallets = derive_evm_wallets(seed)
        
        log(f"\nDeriving X-Chain wallets:")
        group.xchain_wallets = derive_xchain_wallets(seed, WALLETS_PER_SEED)
        
        wallet_groups.append(group)
        
        # Clear memory periodically
        if len(wallet_groups) % CLEAR_MEMORY_INTERVAL == 0:
            log(f"\n[+] Clearing memory at seed {idx}/{total_seeds}")
            gc.collect()
    
    log(f"\n[+] Derivation complete:")
    log(f"    - Total seeds processed: {total_seeds:,}")
    log(f"    - Valid seeds: {valid_seeds:,}")
    log(f"    - Invalid seeds: {invalid_seeds:,}")
    log(f"    - Total valid wallets derived: {valid_seeds * WALLETS_PER_SEED:,}")
    return wallet_groups

def setup_security_handlers():
    """Setup handlers for graceful shutdown and secure memory clearing."""
    def signal_handler(signum, frame):
        print("\n\nReceived shutdown signal. Clearing sensitive data...")
        gc.collect()
        # Overwrite memory with zeros
        try:
            import ctypes
            if hasattr(ctypes, 'memset'):
                ctypes.memset(id(frame), 0, sys.getsizeof(frame))
        except:
            pass
        sys.exit(0)

    # Handle Ctrl+C and system termination
    signal.signal(signal.SIGINT, signal_handler)
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, signal_handler)

def secure_file_write(filepath: str, content: str):
    """Securely write content to file with proper permissions."""
    try:
        # Create directory if it doesn't exist
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        
        # Write with restricted permissions (user read/write only)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        # Set file permissions to user read/write only
        os.chmod(filepath, 0o600)
    except Exception as e:
        print(f"Error writing to {filepath}: {e}")
        traceback.print_exc()

def save_offline_wallets(wallet_groups: List[WalletGroup]):
    """Save derived wallets to offline file without making any API calls."""
    content = "OFFLINE WALLET DERIVATION RESULTS\n"
    content += f"Generated on: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
    content += "WARNING: This file contains sensitive information. Keep it secure.\n\n"
    
    for idx, group in enumerate(wallet_groups, 1):
        content += f"\n{'=' * 80}\n"
        content += f"=== Seed Group {idx} ===\n"
        content += f"Seed Phrase: {group.seed}\n"
        content += f"Source Info: {group.source_info}\n\n"
        
        content += "=== EVM Wallets ===\n"
        for idx, (address, path) in enumerate(group.evm_wallets, 1):
            content += f"EVM Wallet {idx}:\n"
            content += f"  Address: {address}\n"
            content += f"  Path: {path}\n"
        
        content += "\n=== X-Chain Wallets ===\n"
        for idx, address in enumerate(group.xchain_wallets, 1):
            content += f"X-Chain Wallet {idx}:\n"
            content += f"  Address: {address}\n"
        content += f"\n{'=' * 80}\n"
    
    secure_file_write(OFFLINE_WALLETS_FILE, content)
    print(f"\n[+] Offline wallet derivation results saved to: {OFFLINE_WALLETS_FILE}")
    print("[!] WARNING: This file contains sensitive information. Store it securely!")

def extract_private_keys(filepath: str) -> List[Tuple[str, str]]:
    """Extract private keys and their source information from the specified file.
    Returns a list of tuples (private_key, source_info).
    
    Supports format:
    [TIMESTAMP] FILEPATH:
    PRIVATE_KEY
    """
    private_keys = []
    current_source = ""
    
    try:
        with open(filepath, 'r', encoding='utf-8') as file:
            for line in file:
                line = line.strip()
                
                # Skip empty lines
                if not line:
                    continue
                
                # Check if this is a source info line (starts with timestamp)
                if line.startswith('[20'):  # Matches timestamps starting with [20xx
                    current_source = line
                    continue
                
                # If we have a hex string that looks like a private key (64 characters)
                if re.match(r'^[0-9a-fA-F]{64}$', line):
                    if current_source:
                        private_keys.append((line.lower(), current_source))
                    else:
                        private_keys.append((line.lower(), "[No source info]"))
                    current_source = ""  # Reset source info for next key
        
        log(f"[+] Found {len(private_keys):,} private keys")
        return private_keys
        
    except Exception as e:
        log(f"[!] Error reading private keys file: {e}")
        return []

def create_xchain_address_from_private_key(private_key_bytes: bytes) -> str:
    """Create X-Chain address from a private key using bip_utils library."""
    try:
        # Create private key object using bip_utils
        priv_key_obj = Secp256k1PrivateKey.FromBytes(private_key_bytes)
        
        # Get public key and encode directly to AVAX X-Chain address
        pub_key = priv_key_obj.PublicKey()
        xchain_address = AvaxXChainAddr.EncodeKey(pub_key)
        
        if not xchain_address:
            log(f"Warning: Failed to generate X-Chain address")
            return ""
            
        return xchain_address
        
    except Exception as e:
        log(f"Error creating X-Chain address: {str(e)}")
        traceback.print_exc()
        return ""

def derive_wallet_from_private_key(private_key: str) -> Optional[Tuple[str, str, str]]:
    """Derive both EVM and X-Chain wallet addresses from a private key.
    Returns tuple of (evm_address, xchain_address, private_key) or None if invalid."""
    try:
        # Add '0x' prefix if not present for EVM
        if not private_key.startswith('0x'):
            private_key_with_prefix = '0x' + private_key
        else:
            private_key_with_prefix = private_key
            
        # Create EVM account
        account = Account.from_key(private_key_with_prefix)
        evm_address = account.address
        
        # Derive X-Chain address using bip_utils
        try:
            # Convert private key to bytes (remove 0x if present)
            private_key_bytes = bytes.fromhex(private_key.replace('0x', ''))
            
            # Create X-Chain address
            xchain_address = create_xchain_address_from_private_key(private_key_bytes)
            
            if xchain_address:
                log(f"Successfully derived addresses:")
                log(f"  EVM: {evm_address}")
                log(f"  X-Chain: {xchain_address}")
                return (evm_address, xchain_address, private_key_with_prefix)
            else:
                log(f"Warning: Failed to derive X-Chain address for EVM address: {evm_address}")
                return (evm_address, None, private_key_with_prefix)
                
        except Exception as xe:
            log(f"X-Chain derivation error for EVM address {evm_address}: {str(xe)}")
            traceback.print_exc()
            return (evm_address, None, private_key_with_prefix)
            
    except Exception as e:
        log(f"Error deriving wallets: {str(e)}")
        traceback.print_exc()
        return None

def process_private_keys(private_key_entries: List[Tuple[str, str]]) -> List[Tuple[str, str, str, str]]:
    """Process private keys and derive their corresponding wallet addresses.
    Returns list of tuples (evm_address, xchain_address, private_key, source_info)."""
    processed_wallets = []
    total_keys = len(private_key_entries)
    successful_xchain = 0
    failed_xchain = 0
    
    print(f"\n[+] Processing {total_keys:,} private keys")
    
    # Create progress bar
    pbar = tqdm(total=total_keys, desc="Processing private keys")
    
    try:
        for idx, (private_key, source_info) in enumerate(private_key_entries, 1):
            result = derive_wallet_from_private_key(private_key)
            if result:
                evm_address, xchain_address, key = result
                processed_wallets.append((evm_address, xchain_address, key, source_info))
                
                # Update statistics
                if xchain_address:
                    successful_xchain += 1
                else:
                    failed_xchain += 1
                
                # Update progress bar with both addresses
                desc = f"[{idx}/{total_keys}] EVM: {evm_address}"
                if xchain_address:
                    desc += f" | X: {xchain_address}"
                pbar.set_description(desc)
            
            # Update progress
            pbar.update(1)
            
            # Show X-Chain statistics every 1000 keys
            if idx % 1000 == 0:
                print(f"\nX-Chain derivation stats:")
                print(f"Successful: {successful_xchain}")
                print(f"Failed: {failed_xchain}")
                print(f"Success rate: {(successful_xchain/(successful_xchain+failed_xchain))*100:.1f}%")
            
            # Clear memory periodically
            if idx % CLEAR_MEMORY_INTERVAL == 0:
                gc.collect()
                
    except Exception as e:
        print(f"Error in processing: {str(e)}")
        traceback.print_exc()
    finally:
        pbar.close()
        
        # Print final statistics
        print(f"\nFinal X-Chain derivation stats:")
        print(f"Successful: {successful_xchain}")
        print(f"Failed: {failed_xchain}")
        if successful_xchain + failed_xchain > 0:
            print(f"Success rate: {(successful_xchain/(successful_xchain+failed_xchain))*100:.1f}%")
    
    return processed_wallets

def save_private_key_wallets(wallets: List[Tuple[str, str, str, str]]):
    """Save private key derived wallets to a separate file."""
    content = "PRIVATE KEY DERIVED WALLETS\n"
    content += f"Generated on: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
    content += "WARNING: This file contains sensitive information. Keep it secure.\n\n"
    
    for evm_address, xchain_address, private_key, source_info in wallets:
        content += f"\n{'=' * 80}\n"
        content += f"Source: {source_info}\n"
        content += f"Private Key: {private_key}\n"
        content += f"EVM Address: {evm_address}\n"
        if xchain_address:
            content += f"X-Chain Address: {xchain_address}\n"
    
    secure_file_write(PRIVATE_KEY_WALLETS_FILE, content)
    print(f"\n[+] Private key wallet results saved to: {PRIVATE_KEY_WALLETS_FILE}")
    print("[!] WARNING: This file contains sensitive information. Store it securely!")

def main():
    log("[+] Starting wallet derivation script")
    log(f"[+] Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Setup security handlers
    setup_security_handlers()
    
    # Ask user if they want to scan for private keys
    scan_private_keys = input("\nWould you like to scan for private keys? (yes/no): ").lower().startswith('y')
    
    try:
        if scan_private_keys:
            log(f"\n[+] Phase 1: Processing private keys")
            log(f"[+] Reading private keys from: {PRIVATE_KEYS_FILE}")
            
            private_key_entries = extract_private_keys(PRIVATE_KEYS_FILE)
            if private_key_entries:
                processed_wallets = process_private_keys(private_key_entries)
                save_private_key_wallets(processed_wallets)
                
                # Clear sensitive data
                secure_clear_variables(private_key_entries)
                secure_clear_variables(processed_wallets)
                gc.collect()
        
        log(f"\n[+] Phase 2: Processing seed phrases")
        log(f"[+] Reading seed phrases from: {INPUT_FILE}")
        
        seed_entries = extract_seeds(INPUT_FILE)
        if not seed_entries:
            log("[!] No valid seed phrases found.")
            if not scan_private_keys:
                return
        else:
            # Derive all wallets offline
            log("\n[+] Phase 3: Offline wallet derivation from seeds")
            wallet_groups = derive_all_wallets(seed_entries)
            
            # Save offline results
            save_offline_wallets(wallet_groups)
            
            # Display all derived wallets
            log("\n[+] Phase 4: Review derived wallets")
            for idx, group in enumerate(wallet_groups, 1):
                log(f"\nWallet Group {idx}:")
                log(str(group))
            
            # Clear sensitive data
            secure_clear_variables(wallet_groups)
            gc.collect()
        
    except FileNotFoundError as e:
        log(f"\n[!] Error: File not found - {str(e)}")
    except Exception as e:
        log(f"\n[!] Error: {e}")
        log(traceback.format_exc())
    finally:
        # Final cleanup
        log("\n[+] Cleaning up...")
        gc.collect()
        log("[+] Memory cleared.")
        log("\n[+] Script execution completed.")

if __name__ == "__main__":
    main()


