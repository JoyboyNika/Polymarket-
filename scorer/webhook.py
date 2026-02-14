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


# ── Default values for null-safety (Make IML cannot handle undefined/null) ──

_FIELD_DEFAULTS: dict[str, Any] = {
    "title": "Sans titre",
    "slug": "N/A",
    "score": 0,
    "score_pass1": 0,
    "score_pass2": 0,
    "montant": 0.0,
    "price": 0.0,
    "gain_potentiel": 0.0,
    "wallet": "0x0",
    "condition_id": "N/A",
    "transaction_hash": "N/A",
    "market_probability": 0.0,
    "market_volume_24h": 0.0,
    "market_end_date": "",
    "ingested_at": "",
    "side": "N/A",
    "outcome_side": "UNKNOWN",
    "flags": "",
    "flags_detail": "",
    "age_days": "inconnu",
    "tx_count": 0,
    "markets_count": 0,
    "win_loss": "N/A",
    "funding_source": "N/A",
    "market_category": "standard",
    "alert_threshold": 4000,
}


def _safe(value: Any, default: Any) -> Any:
    """Return *value* unless it is None, in which case return *default*."""
    return value if value is not None else default


def build_flat_payload(
    trade: dict[str, Any],
    scoring_result: Any,
    wallet_profile: dict[str, Any],
) -> dict[str, Any]:
    """Build a flat, null-safe webhook payload for Make.com.

    Every value is guaranteed non-null so that Make IML never resolves
    a field to ``undefined``.

    Args:
        trade: Enriched trade dict from Bloc 1.
        scoring_result: A ScoringResult (or any object with score_total,
            score_pass1, score_pass2, flags_triggered, flags_detail).
        wallet_profile: Wallet profile dict from the profiler.

    Returns:
        A single-level dict with no nested objects and no null values.
    """
    # Stringify flags_detail dict → one readable line per flag
    flags_detail_parts: list[str] = []
    for flag, detail in (scoring_result.flags_detail or {}).items():
        evidence = detail.get("evidence", "") if isinstance(detail, dict) else str(detail)
        flags_detail_parts.append(f"{flag}: {evidence}")
    flags_detail_str = "\n".join(flags_detail_parts)

    # Convert flags list → comma-separated string (Make IML needs flat strings)
    flags_list = scoring_result.flags_triggered or []
    flags_str = ", ".join(flags_list) if flags_list else _FIELD_DEFAULTS["flags"]

    # Convert age_days (int | None) → human-readable string
    age_raw = wallet_profile.get("age_days")
    if age_raw is not None:
        age_days = f"{age_raw} jours"
    else:
        age_days = _FIELD_DEFAULTS["age_days"]

    # Compute gain_potentiel: usdc_size × (1/price − 1)
    price = trade.get("price") or 0
    usdc_size = trade.get("usdc_size") or 0
    if price > 0:
        gain_potentiel = round(usdc_size * (1.0 / price - 1.0), 2)
    else:
        gain_potentiel = 0.0

    payload: dict[str, Any] = {
        "title": _safe(trade.get("title"), _FIELD_DEFAULTS["title"]),
        "slug": _safe(trade.get("slug"), _FIELD_DEFAULTS["slug"]),
        "score": _safe(scoring_result.score_total, _FIELD_DEFAULTS["score"]),
        "score_pass1": _safe(scoring_result.score_pass1, _FIELD_DEFAULTS["score_pass1"]),
        "score_pass2": _safe(scoring_result.score_pass2, _FIELD_DEFAULTS["score_pass2"]),
        "montant": _safe(trade.get("usdc_size"), _FIELD_DEFAULTS["montant"]),
        "price": _safe(trade.get("price"), _FIELD_DEFAULTS["price"]),
        "gain_potentiel": gain_potentiel,
        "wallet": _safe(trade.get("proxy_wallet"), _FIELD_DEFAULTS["wallet"]),
        "condition_id": _safe(trade.get("condition_id"), _FIELD_DEFAULTS["condition_id"]),
        "transaction_hash": _safe(trade.get("transaction_hash"), _FIELD_DEFAULTS["transaction_hash"]),
        "market_probability": _safe(trade.get("market_probability"), _FIELD_DEFAULTS["market_probability"]),
        "market_volume_24h": _safe(trade.get("market_volume_24h"), _FIELD_DEFAULTS["market_volume_24h"]),
        "market_end_date": _safe(trade.get("market_end_date"), _FIELD_DEFAULTS["market_end_date"]),
        "ingested_at": _safe(trade.get("ingested_at"), _FIELD_DEFAULTS["ingested_at"]),
        "side": _safe(trade.get("side"), _FIELD_DEFAULTS["side"]),
        "outcome_side": _safe(trade.get("outcome_side"), _FIELD_DEFAULTS["outcome_side"]),
        "flags": flags_str,
        "flags_detail": flags_detail_str if flags_detail_str else _FIELD_DEFAULTS["flags_detail"],
        "age_days": age_days,
        "tx_count": _safe(wallet_profile.get("tx_count"), _FIELD_DEFAULTS["tx_count"]),
        "markets_count": _safe(wallet_profile.get("markets_count"), _FIELD_DEFAULTS["markets_count"]),
        "win_loss": _safe(wallet_profile.get("win_loss"), _FIELD_DEFAULTS["win_loss"]),
        "funding_source": _safe(wallet_profile.get("funding_source"), _FIELD_DEFAULTS["funding_source"]),
    }

    # Belt-and-suspenders: replace any remaining None with field default
    for key, value in payload.items():
        if value is None:
            payload[key] = _FIELD_DEFAULTS.get(key, "")

    return payload


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
    tx_hash = payload.get("transaction_hash", "unknown")[:16]
    filename = f"suspect_{ts}_{tx_hash}.json"
    filepath = os.path.join(FALLBACK_DIR, filename)

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        logger.info("Payload saved to %s", filepath)
    except OSError as e:
        logger.error("Failed to save fallback file: %s", e)


def send_aggregated_webhook(alert: dict[str, Any]) -> bool:
    """Send an aggregated funder alert to the Make webhook.

    Builds a payload compatible with the build_flat_payload format so that
    Make/Haiku can generate a complete fiche from an aggregated alert.

    Mapping from aggregator fields → flat payload fields:
        market_title   → title
        total_volume   → montant
        funder         → funding_source
        wallets        → wallet
        condition_id   → condition_id
        market_category→ market_category
        alert_threshold→ alert_threshold
        trade_count, wallet_count, transactions → flags_detail

    Args:
        alert: Aggregated alert dict from AggregationTracker._build_alert().

    Returns:
        True if the webhook succeeded, False otherwise.
    """
    wallet_count = alert.get("wallet_count", 0)
    trade_count = alert.get("trade_count", 0)
    total_volume = alert.get("total_volume", 0)
    funder = alert.get("funder", "N/A")
    wallets_str = alert.get("wallets", "")
    transactions_str = alert.get("transactions", "")
    market_category = alert.get("market_category", _FIELD_DEFAULTS["market_category"])
    alert_threshold = alert.get("alert_threshold", _FIELD_DEFAULTS["alert_threshold"])

    # Build flags_detail with aggregation evidence
    detail_lines = [
        f"alerte_agrégée: Volume agrégé {total_volume:.0f} USDC "
        f"via {wallet_count} wallet(s) / {trade_count} trade(s) "
        f"depuis le même financeur",
        f"financeur: {funder}",
        f"wallets: {wallets_str}",
        f"transactions: {transactions_str}",
    ]
    flags_detail_str = "\n".join(detail_lines)

    now_iso = datetime.now(timezone.utc).isoformat()

    payload: dict[str, Any] = {
        "title": _safe(alert.get("market_title"), _FIELD_DEFAULTS["title"]),
        "slug": _FIELD_DEFAULTS["slug"],
        "score": 0,
        "score_pass1": 0,
        "score_pass2": 0,
        "montant": round(total_volume, 2),
        "price": _FIELD_DEFAULTS["price"],
        "gain_potentiel": _FIELD_DEFAULTS["gain_potentiel"],
        "wallet": wallets_str if wallets_str else _FIELD_DEFAULTS["wallet"],
        "condition_id": _safe(alert.get("condition_id"), _FIELD_DEFAULTS["condition_id"]),
        "transaction_hash": transactions_str if transactions_str else _FIELD_DEFAULTS["transaction_hash"],
        "market_probability": _FIELD_DEFAULTS["market_probability"],
        "market_volume_24h": _FIELD_DEFAULTS["market_volume_24h"],
        "market_end_date": _FIELD_DEFAULTS["market_end_date"],
        "ingested_at": now_iso,
        "side": _FIELD_DEFAULTS["side"],
        "outcome_side": _FIELD_DEFAULTS["outcome_side"],
        "flags": "alerte_agrégée",
        "flags_detail": flags_detail_str,
        "age_days": _FIELD_DEFAULTS["age_days"],
        "tx_count": trade_count,
        "markets_count": _FIELD_DEFAULTS["markets_count"],
        "win_loss": _FIELD_DEFAULTS["win_loss"],
        "funding_source": funder if funder else _FIELD_DEFAULTS["funding_source"],
        "market_category": market_category,
        "alert_threshold": alert_threshold,
    }

    # Belt-and-suspenders: no None values
    for key, value in payload.items():
        if value is None:
            payload[key] = _FIELD_DEFAULTS.get(key, "")

    logger.info(
        "Sending AGGREGATED alert: funder=%s market=%s volume=%.0f (%d wallets, %d trades)",
        funder[:30],
        alert.get("market_title", "?")[:40],
        total_volume,
        wallet_count,
        trade_count,
    )
    return send_webhook(payload)
