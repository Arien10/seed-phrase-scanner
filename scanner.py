import os
import json
import re
from datetime import datetime
from tqdm import tqdm
import logging
import sys

# Set up logging with immediate flush
class ImmediateFlushHandler(logging.StreamHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[ImmediateFlushHandler(sys.stdout)]
)

# Load BIP39 word list
try:
    with open("bip39_english_wordlist.txt", "r", encoding="utf-8") as f:
        bip39_words = set(f.read().splitlines())
    logging.info(f"Loaded {len(bip39_words)} BIP39 words")
except FileNotFoundError:
    logging.error("BIP39 wordlist file not found! Please ensure 'bip39_english_wordlist.txt' exists in the same directory.")
    exit(1)

def is_valid_private_key(text):
    # Check for hex strings of length 64 (32 bytes) that could be private keys
    # Optionally prefixed with 0x
    pattern = r'(?:0x)?[a-fA-F0-9]{64}'
    matches = re.findall(pattern, text)
    return [match.lower() for match in matches]

def is_valid_seed(words):
    word_count = len(words)
    logging.debug(f"Checking seed phrase with {word_count} words")
    
    # Print status of each word
    for word in words:
        in_wordlist = word in bip39_words
        logging.debug(f"Word '{word}': {'✓' if in_wordlist else '✗'} (in wordlist: {in_wordlist})")
    
    if word_count not in [12, 18, 24]:
        logging.debug(f"Invalid word count: {word_count} (must be 12, 18, or 24)")
        return False
    
    invalid_words = [word for word in words if word not in bip39_words]
    if invalid_words:
        logging.debug(f"Invalid words found in potential seed phrase: {invalid_words}")
        return False
    
    logging.debug(f"Valid seed phrase found with {word_count} words!")
    return True

def extract_seeds(text):
    if not isinstance(text, str):
        return []
    
    # Split on any whitespace and filter out empty strings
    words = [word.lower() for word in re.findall(r'\b[a-z]+\b', text.lower()) if word.strip()]
    logging.debug(f"Found {len(words)} words in text: {words}")
    
    matches = []
    # First try to find exact matches of valid lengths
    word_counts = [12, 18, 24]
    if len(words) in word_counts:
        logging.debug(f"Checking exact match of {len(words)} words")
        if is_valid_seed(words):
            matches.append(" ".join(words))
            return matches

    # If no exact match, try sliding window
    logging.debug("Trying sliding window search")
    for count in word_counts:
        if len(words) >= count:
            for i in range(len(words) - count + 1):
                chunk = words[i:i+count]
                if is_valid_seed(chunk):
                    matches.append(" ".join(chunk))
    
    return matches

def scan_discord_json(folder, scan_seeds=True, scan_private_keys=True):
    if not os.path.exists(folder):
        logging.error(f"Discord folder not found: {folder}")
        return

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    seeds_file = f"found_seed_phrases_{timestamp}.txt" if scan_seeds else None
    private_keys_file = f"found_private_keys_{timestamp}.txt" if scan_private_keys else None
    
    json_files = []

    # First, collect all JSON files
    for root, _, files in os.walk(folder):
        for file in files:
            if file.endswith(".json"):
                json_files.append(os.path.join(root, file))

    logging.info(f"Found {len(json_files)} JSON files to scan")
    
    seeds_out = open(seeds_file, "w", encoding="utf-8") if scan_seeds else None
    keys_out = open(private_keys_file, "w", encoding="utf-8") if scan_private_keys else None

    try:
        # Create progress bar
        for file_path in tqdm(json_files, desc="Scanning files"):
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    logging.debug(f"Processing file: {file_path}")
                    content = f.read()
                    
                    # Handle messages.json files differently
                    if file_path.endswith("messages.json"):
                        lines = content.strip().split('\n')
                        for line in lines:
                            try:
                                line = line.strip().rstrip(',')
                                if not line:
                                    continue
                                entry = json.loads(line)
                                if isinstance(entry, dict):
                                    message_content = entry.get("Contents") or entry.get("content")
                                    if message_content:
                                        timestamp = entry.get('Timestamp') or entry.get('timestamp', 'UNKNOWN')
                                        
                                        # Scan for seed phrases
                                        if scan_seeds:
                                            seeds = extract_seeds(message_content)
                                            for seed in seeds:
                                                seeds_out.write(f"[{timestamp}] {file_path}:\n{seed}\n\n")
                                                seeds_out.flush()
                                                logging.info(f"Found seed phrase in {file_path}")
                                        
                                        # Scan for private keys
                                        if scan_private_keys:
                                            private_keys = is_valid_private_key(message_content)
                                            for key in private_keys:
                                                keys_out.write(f"[{timestamp}] {file_path}:\n{key}\n\n")
                                                keys_out.flush()
                                                logging.info(f"Found private key in {file_path}")
                            except json.JSONDecodeError:
                                continue
                    else:
                        try:
                            data = json.loads(content)
                            if isinstance(data, list):
                                for entry in data:
                                    if isinstance(entry, dict):
                                        message_content = entry.get("Contents") or entry.get("content")
                                        if message_content:
                                            timestamp = entry.get('Timestamp') or entry.get('timestamp', 'UNKNOWN')
                                            
                                            # Scan for seed phrases
                                            if scan_seeds:
                                                seeds = extract_seeds(message_content)
                                                for seed in seeds:
                                                    seeds_out.write(f"[{timestamp}] {file_path}:\n{seed}\n\n")
                                                    seeds_out.flush()
                                                    logging.info(f"Found seed phrase in {file_path}")
                                            
                                            # Scan for private keys
                                            if scan_private_keys:
                                                private_keys = is_valid_private_key(message_content)
                                                for key in private_keys:
                                                    keys_out.write(f"[{timestamp}] {file_path}:\n{key}\n\n")
                                                    keys_out.flush()
                                                    logging.info(f"Found private key in {file_path}")
                        except json.JSONDecodeError:
                            logging.warning(f"Invalid JSON file: {file_path}")
                                
            except Exception as e:
                logging.error(f"Error processing {file_path}: {str(e)}")
    finally:
        if seeds_out:
            seeds_out.close()
        if keys_out:
            keys_out.close()

    if scan_seeds:
        logging.info(f"✅ Seed phrase results saved to: {seeds_file}")
    if scan_private_keys:
        logging.info(f"✅ Private key results saved to: {private_keys_file}")

if __name__ == "__main__":
    # Interactive prompts
    print("\nWelcome to Discord Scanner")
    print("-------------------------")
    
    scan_seeds = input("Scan for seed phrases? (y/n): ").lower().strip() == 'y'
    scan_private_keys = input("Scan for private keys? (y/n): ").lower().strip() == 'y'
    
    if not scan_seeds and not scan_private_keys:
        print("No scan options selected. Exiting...")
        sys.exit(0)
    
    # Use raw string for Windows path to avoid escape character issues
    discord_folder = r"C:\Users\......"
    
    print("\nStarting scan...")
    print(f"Scanning for: {'seed phrases ' if scan_seeds else ''}{'and ' if scan_seeds and scan_private_keys else ''}{'private keys' if scan_private_keys else ''}")
    print("-------------------------\n")
    
    scan_discord_json(discord_folder, scan_seeds, scan_private_keys)
