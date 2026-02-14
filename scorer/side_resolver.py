"""Outcome side resolver: determine if a trade bought YES or NO tokens.

Pipeline:
1. Fetch token_ids from CLOB API (condition_id → YES/NO token_ids)
2. Fetch transaction receipt via Alchemy (tx_hash → ERC1155 transfer logs)
3. Match the transferred tokenId against YES/NO token_ids

Returns "YES", "NO", or "UNKNOWN".
"""

import logging
from typing import Any

import requests

from scorer.config import (
    ALCHEMY_API_KEY,
    ALCHEMY_NETWORK,
    CLOB_API_URL,
    CTF_CONTRACT_ADDRESS,
    REQUEST_TIMEOUT,
)

logger = logging.getLogger(__name__)

# ERC1155 TransferSingle event signature:
# keccak256("TransferSingle(address,address,address,uint256,uint256)")
_TRANSFER_SINGLE_TOPIC = (
    "0xc3d58168c5ae7397731d063d5bbf3d657854427343f4c083240f7aacaa2d0f62"
)

# ERC1155 TransferBatch event signature:
# keccak256("TransferBatch(address,address,address,uint256[],uint256[])")
_TRANSFER_BATCH_TOPIC = (
    "0x4a39dc06d4c0dbc64b70af90fd698a233a518aa5d07e595d983b8c0526c8f7fb"
)

# Cache: condition_id → {"yes": token_id_str, "no": token_id_str}
_clob_cache: dict[str, dict[str, str] | None] = {}


def clear_clob_cache() -> None:
    """Clear the CLOB token_ids cache (call between cycles)."""
    _clob_cache.clear()


def resolve_outcome_side(
    condition_id: str,
    tx_hash: str,
    proxy_wallet: str,
) -> str:
    """Determine whether a trade bought YES or NO tokens.

    Args:
        condition_id: Market condition ID (0x hex string).
        tx_hash: Transaction hash of the trade.
        proxy_wallet: Wallet address that received the tokens.

    Returns:
        "YES", "NO", or "UNKNOWN".
    """
    if not condition_id or not tx_hash:
        logger.debug("Missing condition_id or tx_hash — side UNKNOWN")
        return "UNKNOWN"

    # Step 1: Get YES/NO token_ids from CLOB API
    token_ids = _fetch_clob_token_ids(condition_id)
    if token_ids is None:
        return "UNKNOWN"

    # Step 2: Get transaction receipt and extract transferred tokenId
    if not ALCHEMY_API_KEY:
        logger.warning(
            "ALCHEMY_API_KEY not set — cannot resolve outcome side from tx receipt"
        )
        return "UNKNOWN"

    transferred_token_id = _get_transferred_token_id(tx_hash, proxy_wallet)
    if transferred_token_id is None:
        return "UNKNOWN"

    # Step 3: Match
    if transferred_token_id == token_ids["yes"]:
        logger.info(
            "Trade %s — outcome side: YES (token matched)", tx_hash[:12]
        )
        return "YES"
    elif transferred_token_id == token_ids["no"]:
        logger.info(
            "Trade %s — outcome side: NO (token matched)", tx_hash[:12]
        )
        return "NO"
    else:
        logger.warning(
            "Trade %s — tokenId %s matches neither YES (%s) nor NO (%s)",
            tx_hash[:12],
            transferred_token_id[:20],
            token_ids["yes"][:20],
            token_ids["no"][:20],
        )
        return "UNKNOWN"


# ── Step 1: CLOB API ────────────────────────────────────────────


def _fetch_clob_token_ids(condition_id: str) -> dict[str, str] | None:
    """Fetch YES/NO token_ids from the Polymarket CLOB API.

    GET https://clob.polymarket.com/markets/{condition_id}

    Returns:
        {"yes": "<token_id>", "no": "<token_id>"} or None on error.
    """
    if condition_id in _clob_cache:
        return _clob_cache[condition_id]

    url = f"{CLOB_API_URL}/markets/{condition_id}"
    logger.debug("GET %s", url)

    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.warning("CLOB API failed for %s: %s", condition_id[:16], e)
        _clob_cache[condition_id] = None
        return None

    data = resp.json()
    tokens = data.get("tokens")
    if not tokens or len(tokens) < 2:
        logger.warning(
            "CLOB API returned unexpected tokens for %s: %s",
            condition_id[:16],
            tokens,
        )
        _clob_cache[condition_id] = None
        return None

    # tokens[0] = Yes, tokens[1] = No (per Polymarket convention)
    result = {
        "yes": str(tokens[0].get("token_id", "")),
        "no": str(tokens[1].get("token_id", "")),
    }

    if not result["yes"] or not result["no"]:
        logger.warning("CLOB API returned empty token_ids for %s", condition_id[:16])
        _clob_cache[condition_id] = None
        return None

    logger.debug(
        "CLOB token_ids for %s: YES=%s..., NO=%s...",
        condition_id[:16],
        result["yes"][:20],
        result["no"][:20],
    )
    _clob_cache[condition_id] = result
    return result


# ── Step 2: Transaction receipt via Alchemy ──────────────────────


def _alchemy_rpc_url() -> str:
    return f"https://{ALCHEMY_NETWORK}.g.alchemy.com/v2/{ALCHEMY_API_KEY}"


def _alchemy_json_rpc(method: str, params: list) -> Any:
    """Make a JSON-RPC call to Alchemy."""
    url = _alchemy_rpc_url()
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }

    try:
        resp = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            logger.warning("Alchemy RPC error (%s): %s", method, data["error"])
            return None
        return data.get("result")
    except requests.RequestException as e:
        logger.warning("Alchemy RPC failed (%s): %s", method, e)
        return None


def _get_transferred_token_id(tx_hash: str, wallet: str) -> str | None:
    """Extract the ERC1155 tokenId received by wallet from a transaction.

    Uses eth_getTransactionReceipt to get logs, then parses
    TransferSingle events from the CTF contract where `to` matches
    the wallet address.

    Returns:
        The tokenId as a decimal string, or None if not found.
    """
    receipt = _alchemy_json_rpc("eth_getTransactionReceipt", [tx_hash])
    if receipt is None:
        logger.warning("Could not fetch tx receipt for %s", tx_hash[:12])
        return None

    logs = receipt.get("logs", [])
    if not logs:
        logger.debug("No logs in tx receipt for %s", tx_hash[:12])
        return None

    ctf_lower = CTF_CONTRACT_ADDRESS.lower()
    wallet_lower = wallet.lower()
    # Pad wallet to 32 bytes for topic matching (address is 20 bytes, left-padded)
    wallet_topic = "0x" + wallet_lower[2:].zfill(64)

    for log in logs:
        # Filter: must be from the CTF contract
        log_address = (log.get("address") or "").lower()
        if log_address != ctf_lower:
            continue

        topics = log.get("topics", [])
        if not topics:
            continue

        topic0 = topics[0].lower()

        # TransferSingle: topics = [sig, operator, from, to], data = [id, value]
        if topic0 == _TRANSFER_SINGLE_TOPIC and len(topics) >= 4:
            to_address = topics[3].lower()
            if to_address == wallet_topic:
                data = log.get("data", "0x")
                return _parse_uint256_from_data(data, offset=0)

        # TransferBatch: topics = [sig, operator, from, to], data = ABI-encoded arrays
        if topic0 == _TRANSFER_BATCH_TOPIC and len(topics) >= 4:
            to_address = topics[3].lower()
            if to_address == wallet_topic:
                token_id = _parse_first_id_from_batch(log.get("data", "0x"))
                if token_id is not None:
                    return token_id

    logger.debug(
        "No ERC1155 transfer to %s found in tx %s (%d logs scanned)",
        wallet[:12],
        tx_hash[:12],
        len(logs),
    )
    return None


def _parse_uint256_from_data(data: str, offset: int = 0) -> str | None:
    """Parse a uint256 from ABI-encoded data at the given 32-byte slot offset.

    Args:
        data: Hex string starting with 0x.
        offset: Slot index (0 = first 32 bytes, 1 = second 32 bytes, etc.)

    Returns:
        The uint256 as a decimal string, or None on error.
    """
    try:
        # Strip 0x prefix
        hex_data = data[2:] if data.startswith("0x") else data
        start = offset * 64
        end = start + 64
        if len(hex_data) < end:
            return None
        return str(int(hex_data[start:end], 16))
    except (ValueError, IndexError):
        return None


def _parse_first_id_from_batch(data: str) -> str | None:
    """Parse the first tokenId from a TransferBatch event data.

    TransferBatch data layout (ABI-encoded):
        offset 0: offset to ids array (uint256)
        offset 1: offset to values array (uint256)
        offset 2: ids array length (uint256)
        offset 3: ids[0] (uint256) ← this is what we want

    Returns:
        The first tokenId as a decimal string, or None on error.
    """
    try:
        hex_data = data[2:] if data.startswith("0x") else data
        # ABI encoding: slot 0 = offset to ids (usually 0x40 = 64 bytes = 2 slots)
        # slot at that offset = array length, next slot = first element
        ids_offset_slot = int(hex_data[0:64], 16) // 32  # Convert byte offset to slot
        length_slot = ids_offset_slot
        first_id_slot = length_slot + 1
        start = first_id_slot * 64
        end = start + 64
        if len(hex_data) < end:
            return None
        return str(int(hex_data[start:end], 16))
    except (ValueError, IndexError):
        return None
