# Wallet Tools Suite

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![Offline-first](https://img.shields.io/badge/Mode-Offline--first-informational)](#security-notes)
[![Status](https://img.shields.io/badge/Status-Experimental-orange)](#status)
[![License](https://img.shields.io/badge/License-TBD-lightgrey)](#license)

A small set of local tools that help you find leaked seed phrases, validate them, derive wallets, and check balances. Everything runs on your machine. No accounts, no servers.

> ⚠️ These scripts handle sensitive data. Work on a separate machine if possible. Keep outputs encrypted or delete them when done.

---

## Contents

* [`ULTIMATESEEDPHRASECSCANNER.py`](#ultimateseedphrasecscannerpy) — system-wide multi format scanner that hunts for BIP39 seed phrases across many file types
* [`scanner.py`](#scannerpy) — focused scanner for Discord JSON dumps and plain text folders
* [`seedchecker.py`](#seedcheckerpy) — offline validator and wallet derivation from seed phrases and optional raw private keys
* [`balance_checker.py`](#balance_checkerpy) — balance triage for derived wallets using public RPCs

---

## Quick comparison

| Script                          | Purpose                                     | Inputs                                            | Main outputs                                                          |
| ------------------------------- | ------------------------------------------- | ------------------------------------------------- | --------------------------------------------------------------------- |
| `ULTIMATESEEDPHRASECSCANNER.py` | System-wide seed phrase discovery           | Folders or drives                                 | `output/high_quality_seeds.txt`, `output/low_quality_seeds.txt`, logs |
| `scanner.py`                    | Chat export seed and key discovery          | Discord JSON folder or text folder                | `found_seed_phrases_*.txt`, `found_private_keys_*.txt`                |
| `seedchecker.py`                | Validate seeds and derive wallets offline   | `filtered_seeds.txt`, optional `private_keys.txt` | `offline_wallets_*.txt`, `private_key_wallets_*.txt`                  |
| `balance_checker.py`            | Find non zero balances on derived addresses | `offline_wallets_*.txt` or `offline_wallets.txt`  | `wallet_balances_<timestamp>.json`                                    |

---

## Install

Create a virtual environment and install what you need for each script.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate

# Base utilities
pip install tqdm

# For seed derivation and AVAX X Chain encoding
pip install web3 eth-account mnemonic bip-utils base58

# For the ULTIMATE scanner file formats
pip install python-magic pymupdf python-docx openpyxl python-pptx textract
```

Place a BIP39 English wordlist file next to the scanners if you do not already have one, for example `bip39_english_wordlist.txt`.

---

## ULTIMATESEEDPHRASECSCANNER.py

**Plain overview**

Runs across a whole computer to search for leaked crypto seed phrases. You choose where to scan. It reads common file types like text, PDFs, Word, Excel, PowerPoint, ODT, ODS, ODP, SQLite databases, and ZIP archives. It looks for 12, 18, or 24 word BIP39 phrases, filters out obvious false alarms, labels results as high or low quality, and writes everything to `output/` with full file paths.

**When to use**

Security hygiene on old drives, incident response, and cleaning datasets before sharing so you do not leak wallet recovery phrases.

**What it does**

* Recursively scans local and network paths on Windows, macOS, and Linux
* Reads many file types: text, code files, PDF, DOC, DOCX, RTF, ODT, XLS, XLSX, ODS, PPT, PPTX, ODP, SQLite databases, and ZIP archives
* Uses sliding window detection for 12, 18, or 24 word phrases from the BIP39 wordlist
* De duplicates results and labels hits as high or low quality using simple scoring
* Supports time filters for last 24h, 7d, 30d, or a custom start date
* Skips noisy system folders and very large files by default, with configurable limits
* Keeps resume state in a small SQLite database and shows live progress and stats
* Logs protected or unreadable files for an audit trail

**Inputs**

* Start path or drive letters to scan
* `bip39_english_wordlist.txt` in the working folder

**Outputs**

* `output/high_quality_seeds.txt`
* `output/low_quality_seeds.txt`
* Scan logs in `scan_logs/`

**Quick start**

```bash
python ULTIMATESEEDPHRASECSCANNER.py
```

Follow the prompts to select OS, folders or drives, time filter, and exclusions.

---

## scanner.py

**Plain overview**

A simple command line scanner for exported chat logs. It is tuned for Discord JSON exports and plain text folders. It looks for likely BIP39 seed phrases and 64 character hex private keys, then writes timestamped result files that include the source path for every hit.

**When to use**

Quick checks on chat exports before sharing them. Recovery of accidentally pasted secrets in chat history.

**What it does**

* Scans a chosen folder for Discord JSON files or plain text files
* Detects 12, 18, or 24 word BIP39 seed phrases using a local wordlist
* Detects 64 hex private keys with or without `0x`
* Shows progress bars and logs as it runs
* Writes timestamped results with the source file path for traceability

**Inputs**

* Discord export folder or a folder of text files
* `bip39_english_wordlist.txt` in the working folder

**Outputs**

* `found_seed_phrases_YYYYMMDD_HHMMSS.txt`
* `found_private_keys_YYYYMMDD_HHMMSS.txt`

**Quick start**

```bash
python scanner.py
```

Use the y/n prompts to choose what to scan.

---

## seedchecker.py

**Plain overview**

Validates BIP39 seed phrases and derives wallets completely offline. It also has an option to process raw private keys. You get clean, timestamped reports with addresses and derivation paths.

**When to use**

After you have collected seed phrases from a scan and want to verify them and derive addresses without touching the internet.

**What it does**

* Parses seed phrases from a text file in three formats: block format, source info plus phrase, or simple phrases separated by blank lines
* Validates mnemonics with the BIP39 checksum
* Derives wallets offline

  * EVM addresses using path `m/44'/60'/0'/0/i` for `i = 0..N-1` with `N` default 10
  * Avalanche X Chain addresses using `bip_utils`
* Optionally reads raw 64 hex private keys from `private_keys.txt` and derives matching EVM and Avalanche X Chain addresses
* Writes timestamped reports with restrictive file permissions and shows progress bars

**Inputs**

* `filtered_seeds.txt` with seed phrases in one of the supported formats
* Optional `private_keys.txt` with raw 64 hex private keys

**Outputs**

* `offline_wallets_YYYYMMDD_HHMMSS.txt`
* `private_key_wallets_YYYYMMDD_HHMMSS.txt`

**Quick start**

```bash
python seedchecker.py
```

Answer the prompt about scanning `private_keys.txt` first or not.

---

## balance_checker.py

**Plain overview**

Reads a wallet derivation report and checks which addresses actually hold funds. It rotates through multiple public RPCs per chain, handles basic retries, and writes a compact JSON with only the wallets that have non zero balances.

**When to use**

After running `seedchecker.py` you can quickly see which derived addresses are worth investigating.

**What it does**

* Parses `offline_wallets_*.txt` or `offline_wallets.txt` for EVM addresses with index and derivation path, plus Avalanche X Chain addresses
* Queries native coin balances and a small set of ERC 20 tokens on Ethereum, BSC, Polygon, and Avalanche C Chain
* Uses `avm.getAllBalances` for Avalanche X Chain
* Rotates among multiple RPC endpoints per chain with light rate limiting and retries
* Writes only the positive balance hits to a timestamped JSON file

**Inputs**

* `offline_wallets_*.txt` from `seedchecker.py` or a file renamed to `offline_wallets.txt`

**Outputs**

* `wallet_balances_<timestamp>.json`

**Quick start**

```bash
python balance_checker.py
```

Make sure the input file path inside the script matches your latest `offline_wallets_*.txt` or provide `offline_wallets.txt`.

---

## Security notes

* All derivation and scanning happens locally. No RPC keys are required. The balance checker talks to public endpoints, but you can replace them with your own.
* Never commit real seeds, private keys, or output files to Git. Consider running these tools in a VM or on an air gapped machine.
* Delete or securely store outputs when finished. Use encrypted volumes if possible.

---

## Status

Experimental. I made this to personally test my own skills (and to find a lost wallet)

---


