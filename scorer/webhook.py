"""Webhook sender: POST suspect trades to Make, with retry and local fallback."""

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import requests

from scorer.config import (
    FALLBACK_DIR,
    MAKE_WEBHOOK_URL,
    WEBHOOK_RETRY_DELAY,
    WEBHOOK_TIMEOUT,
)

logger = logging.getLogger(__name__)


def send_webhook(payload: dict[str, Any]) -> bool:
    """Send a suspect trade payload to the Make webhook.

    Retries once after WEBHOOK_RETRY_DELAY seconds on failure.
    Falls back to local JSON file if both attempts fail.

    Args:
        payload: The full suspect trade payload (trade + scoring + wallet_profile).

    Returns:
        True if the webhook succeeded, False if it fell back to local storage.
    """
    if not MAKE_WEBHOOK_URL:
        logger.warning("MAKE_WEBHOOK_URL not configured — saving locally")
        _save_fallback(payload)
        return False

    for attempt in range(2):
        try:
            resp = requests.post(
                MAKE_WEBHOOK_URL,
                json=payload,
                timeout=WEBHOOK_TIMEOUT,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            logger.info("Webhook sent successfully (attempt %d)", attempt + 1)
            return True
        except requests.RequestException as e:
            logger.warning(
                "Webhook attempt %d failed: %s",
                attempt + 1,
                e,
            )
            if attempt == 0:
                logger.info("Retrying in %ds...", WEBHOOK_RETRY_DELAY)
                time.sleep(WEBHOOK_RETRY_DELAY)

    # Both attempts failed — save locally
    logger.error("Webhook failed after 2 attempts — saving to local fallback")
    _save_fallback(payload)
    return False


def _save_fallback(payload: dict[str, Any]) -> None:
    """Save a failed webhook payload to a local JSON file.

    Files are saved to FALLBACK_DIR with a timestamp-based filename.
    """
    os.makedirs(FALLBACK_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    tx_hash = payload.get("trade", {}).get("transaction_hash", "unknown")[:16]
    filename = f"suspect_{ts}_{tx_hash}.json"
    filepath = os.path.join(FALLBACK_DIR, filename)

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        logger.info("Payload saved to %s", filepath)
    except OSError as e:
        logger.error("Failed to save fallback file: %s", e)
