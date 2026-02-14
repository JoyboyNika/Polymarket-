"""Bloc 2 — Scorer + Wallet Profiler orchestration.

Receives enriched trades from Bloc 1, scores them in 2 passes,
profiles wallets for suspects, and sends alerts to Bloc 3 via webhook.

Usage (standalone test):
    python -m scorer.main

    Runs the Maduro test case and prints the full scoring result.
"""

import json
import logging
import re
import time
from typing import Any

from scorer.aggregator import AggregationTracker
from scorer.config import (
    BOT_MARKETS_THRESHOLD,
    BOT_WIN_RATE_THRESHOLD,
    MIN_GAIN_POTENTIEL,
    PASS1_THRESHOLD,
    PASS2_THRESHOLD,
    PUBLIC_RESOLUTION_PATTERNS,
    WEBHOOK_SEQUENTIAL_DELAY,
)
from scorer.market_classifier import classify_market, get_alert_threshold
from scorer.profiler import build_wallet_profile
from scorer.scoring import ScoringResult, score_pass1, score_pass2
from scorer.webhook import build_flat_payload, send_aggregated_webhook, send_webhook

logger = logging.getLogger(__name__)


def process_enriched_trades(
    trades: list[dict[str, Any]],
    aggregation_tracker: AggregationTracker | None = None,
) -> list[dict[str, Any]]:
    """Score a batch of enriched trades from Bloc 1.

    This is the main entry point called by the ingestor's process_trades().

    For each trade:
    0. Category filter: skip if usdc_size < category threshold
    1. Pass 1: score trade+market (no external calls)
    2. If score >= PASS1_THRESHOLD: profile wallet + Pass 2
    3. If total score >= PASS2_THRESHOLD: build payload + send webhook
    4. Feed trade to aggregation tracker for funder-level split detection

    Args:
        trades: List of enriched trade dicts from Bloc 1.
        aggregation_tracker: Optional tracker for funder×market aggregation.
            When provided, sub-threshold trades are still fed to the tracker
            so that split trades can be detected.

    Returns:
        List of suspect trade payloads that were sent (or attempted).
    """
    suspects = []
    webhooks_sent = 0

    for trade in trades:
        try:
            result = _process_single_trade(trade, aggregation_tracker)
            if result is not None:
                suspects.append(result)
                webhooks_sent += 1
                # Ticket #10: space out webhook sends to avoid Anthropic
                # rate limits on the Make→Haiku path.  Sleep *after* each
                # webhook so the next one fires ≥5s later.
                if WEBHOOK_SEQUENTIAL_DELAY > 0:
                    logger.info(
                        "Webhook %d sent — waiting %ds before next (rate-limit guard)",
                        webhooks_sent,
                        WEBHOOK_SEQUENTIAL_DELAY,
                    )
                    time.sleep(WEBHOOK_SEQUENTIAL_DELAY)
        except Exception as e:
            tx_hash = trade.get("transaction_hash", "unknown")
            logger.error("Failed to score trade %s: %s", tx_hash, e, exc_info=True)

    logger.info(
        "Scoring complete: %d/%d trades are suspect (threshold: %d pts)",
        len(suspects),
        len(trades),
        PASS2_THRESHOLD,
    )
    return suspects


def _compute_gain_potentiel(trade: dict[str, Any]) -> float:
    """Compute potential gain: usdc_size × (1/price − 1)."""
    price = trade.get("price") or 0
    usdc_size = trade.get("usdc_size") or 0
    if price > 0:
        return usdc_size * (1.0 / price - 1.0)
    return 0.0


def _is_public_resolution_market(trade: dict[str, Any]) -> bool:
    """Check if market has publicly observable resolution (price feeds, etc.)."""
    slug = (trade.get("slug") or "").lower()
    title = (trade.get("title") or "").lower()
    text = f"{slug} {title}"
    return any(pattern in text for pattern in PUBLIC_RESOLUTION_PATTERNS)


def _parse_win_rate(win_loss: str | None) -> float | None:
    """Parse win rate from 'XW/YL' string. Returns None if unparseable."""
    if not win_loss:
        return None
    match = re.match(r"(\d+)W/(\d+)L", win_loss)
    if not match:
        return None
    wins = int(match.group(1))
    losses = int(match.group(2))
    total = wins + losses
    if total == 0:
        return None
    return wins / total


def _is_bot_arbitrageur(wallet_profile: dict[str, Any]) -> bool:
    """Check if wallet profile matches bot/arbitrageur pattern.

    Criteria: markets_count > 30 AND win_rate > 80%.
    """
    markets_count = wallet_profile.get("markets_count") or 0
    if markets_count <= BOT_MARKETS_THRESHOLD:
        return False
    win_rate = _parse_win_rate(wallet_profile.get("win_loss"))
    if win_rate is None:
        return False
    return win_rate > BOT_WIN_RATE_THRESHOLD


def _process_single_trade(
    trade: dict[str, Any],
    aggregation_tracker: AggregationTracker | None = None,
) -> dict[str, Any] | None:
    """Process a single trade through the full scoring pipeline.

    Pipeline order (Ticket #8 + Forensic Carmin Feb 2026):
    0. Category filter: usdc_size vs category threshold (crypto $10K / standard $4K)
    1. Entry filter: gain potentiel minimum ($500)
    2. Entry filter: public resolution market
    3. Pass 1 scoring (trade + market)
    4. If Pass 1 >= threshold: profile wallet
    5. Feed trade to aggregation tracker (even sub-threshold trades)
    6. Entry filter: bot/arbitrageur (needs wallet data)
    7. Pass 2 scoring (wallet characteristics)
    8. If total >= threshold: build payload + send webhook

    Returns:
        Suspect payload dict if the trade is suspect, None otherwise.
    """
    tx_hash = trade.get("transaction_hash", "unknown")
    usdc_size = trade.get("usdc_size") or 0

    # ── Entry filter 0: category-based amount threshold ──
    market_category = classify_market(trade)
    alert_threshold = get_alert_threshold(trade)
    if usdc_size < alert_threshold:
        logger.debug(
            "Trade %s — FILTERED: %.0f USDC < %d threshold (%s category)",
            tx_hash[:12], usdc_size, alert_threshold, market_category,
        )
        # Sub-threshold trades still feed the aggregation tracker so that
        # split trades across multiple wallets from the same funder can
        # be detected when their combined volume crosses the threshold.
        if aggregation_tracker is not None:
            _feed_aggregation_sub_threshold(trade, aggregation_tracker)
        return None

    # ── Entry filter 1: minimum gain potential ──
    gain = _compute_gain_potentiel(trade)
    if gain < MIN_GAIN_POTENTIEL:
        logger.debug(
            "Trade %s — FILTERED: gain potentiel $%.0f < $%.0f minimum",
            tx_hash[:12], gain, MIN_GAIN_POTENTIEL,
        )
        return None

    # ── Entry filter 2: public resolution market ──
    if _is_public_resolution_market(trade):
        logger.debug(
            "Trade %s — FILTERED: public resolution market (%s)",
            tx_hash[:12], trade.get("slug", ""),
        )
        return None

    # ── Pass 1 scoring ──
    result = score_pass1(trade)
    logger.debug(
        "Trade %s — Pass 1: %d pts, flags: %s",
        tx_hash[:12],
        result.score_pass1,
        result.flags_triggered,
    )

    if result.score_pass1 < PASS1_THRESHOLD:
        logger.debug("Trade %s — below Pass 1 threshold (%d), skipping", tx_hash[:12], PASS1_THRESHOLD)
        return None

    # ── Profile wallet ──
    wallet = trade.get("proxy_wallet", "")
    logger.info(
        "Trade %s — Pass 1 score %d >= %d, profiling wallet %s...",
        tx_hash[:12],
        result.score_pass1,
        PASS1_THRESHOLD,
        wallet[:12],
    )

    wallet_profile = _safe_profile_wallet(wallet)

    # ── Feed aggregation tracker (above-threshold trades too) ──
    if aggregation_tracker is not None:
        agg_alert = aggregation_tracker.add_trade(trade, wallet_profile)
        if agg_alert is not None:
            send_aggregated_webhook(agg_alert)

    # ── Entry filter 3: bot/arbitrageur ──
    if _is_bot_arbitrageur(wallet_profile):
        logger.info(
            "Trade %s — FILTERED: bot/arbitrageur pattern (markets=%s, win_loss=%s)",
            tx_hash[:12],
            wallet_profile.get("markets_count"),
            wallet_profile.get("win_loss"),
        )
        return None

    # ── Pass 2 scoring ──
    score_pass2(wallet_profile, result)
    logger.info(
        "Trade %s — Total score: %d (P1: %d, P2: %d), flags: %s [%s]",
        tx_hash[:12],
        result.score_total,
        result.score_pass1,
        result.score_pass2,
        result.flags_triggered,
        market_category,
    )

    if result.score_total < PASS2_THRESHOLD:
        logger.debug(
            "Trade %s — below Pass 2 threshold (%d), not alerting",
            tx_hash[:12],
            PASS2_THRESHOLD,
        )
        return None

    # ── Build and send alert payload ──
    payload = _build_payload(trade, result, wallet_profile)
    payload["market_category"] = market_category
    payload["alert_threshold"] = alert_threshold
    send_webhook(payload)
    return payload


def _safe_profile_wallet(wallet: str) -> dict[str, Any]:
    """Profile a wallet, returning fallback profile on failure."""
    try:
        return build_wallet_profile(wallet)
    except Exception as e:
        logger.error("Wallet profiling failed for %s: %s", wallet, e)
        return {
            "age_days": None,
            "tx_count": None,
            "markets_count": 0,
            "win_loss": None,
            "funding_source": "non_disponible",
            "first_polymarket_trade": None,
        }


def _feed_aggregation_sub_threshold(
    trade: dict[str, Any],
    aggregation_tracker: AggregationTracker,
) -> None:
    """Profile a sub-threshold trade's wallet and feed the aggregation tracker.

    Sub-threshold trades (below the category amount filter) are still
    interesting for aggregation: a funder may split a $12K trade into
    4 x $3K across different wallets. We profile the wallet to get the
    funding_source, then feed it to the aggregation tracker.
    """
    wallet = trade.get("proxy_wallet", "")
    if not wallet:
        return
    wallet_profile = _safe_profile_wallet(wallet)
    agg_alert = aggregation_tracker.add_trade(trade, wallet_profile)
    if agg_alert is not None:
        send_aggregated_webhook(agg_alert)


def _build_payload(
    trade: dict[str, Any],
    result: ScoringResult,
    wallet_profile: dict[str, Any],
) -> dict[str, Any]:
    """Build the webhook payload for a suspect trade.

    Returns a flat, null-safe payload for Make.com consumption.
    """
    return build_flat_payload(trade, result, wallet_profile)


# ── Standalone test (Maduro case) ────────────────────────────


def _run_maduro_test() -> None:
    """Run the Maduro test case to verify scoring logic."""
    from scorer.scoring import score_trade

    print("=" * 60)
    print("BLOC 2 — Maduro Test Case")
    print("=" * 60)
    print()

    # Maduro trade (from Bloc 1 output format)
    trade = {
        "proxy_wallet": "0xTEST_MADURO_WALLET",
        "condition_id": "test-maduro-condition-id",
        "transaction_hash": "test-tx-hash-0x1234",
        "usdc_size": 32000.0,
        "price": 0.07,
        "side": "BUY",
        "slug": "will-maduro-leave-office-before-jan-31",
        "title": "Will Maduro leave office before Jan 31?",
        "market_probability": 0.055,
        "market_volume_24h": 85000.0,
        "market_end_date": "2025-01-31T00:00:00Z",
        "ingested_at": "2025-01-15T12:00:00Z",
    }

    # Maduro wallet profile (simulated)
    wallet_profile = {
        "age_days": 3,
        "tx_count": 4,
        "markets_count": 1,
        "win_loss": None,
        "funding_source": "transfer from 0xCoinbase... (35000 USDC)",
        "first_polymarket_trade": None,
    }

    print("Trade:")
    print(f"  Title: {trade['title']}")
    print(f"  Size: {trade['usdc_size']} USDC")
    print(f"  Price: {trade['price']}")
    print(f"  Side: {trade['side']}")
    print(f"  Market prob: {trade['market_probability']}")
    print(f"  Market vol: {trade['market_volume_24h']}")
    print()

    # Pass 1 only
    result_p1 = score_pass1(trade)
    print(f"Pass 1 score: {result_p1.score_pass1}")
    print(f"  Flags: {result_p1.flags_triggered}")
    for flag, detail in result_p1.flags_detail.items():
        print(f"    {flag}: {detail['points']}pts — {detail['evidence']}")
    print(f"  Passes threshold ({PASS1_THRESHOLD})? {'YES' if result_p1.score_pass1 >= PASS1_THRESHOLD else 'NO'}")
    print()

    # Full scoring (Pass 1 + 2)
    result = score_trade(trade, wallet_profile)
    print(f"Pass 2 score: {result.score_pass2}")
    pass2_flags = [f for f in result.flags_triggered if f not in result_p1.flags_triggered]
    for flag in pass2_flags:
        detail = result.flags_detail[flag]
        print(f"    {flag}: {detail['points']}pts — {detail['evidence']}")
    print()

    print(f"TOTAL SCORE: {result.score_total} (P1: {result.score_pass1}, P2: {result.score_pass2})")
    print(f"  Passes alert threshold ({PASS2_THRESHOLD})? {'YES' if result.score_total >= PASS2_THRESHOLD else 'NO'}")
    print(f"  All flags: {result.flags_triggered}")
    print()

    # Build payload (flat, null-safe)
    payload = _build_payload(trade, result, wallet_profile)
    print("Webhook payload (flat format):")
    print(json.dumps(payload, indent=2, ensure_ascii=False))

    # Verify criteria
    print()
    print("=" * 60)
    print("VERIFICATION")
    print("=" * 60)
    assert result.score_pass1 >= 5, f"Pass 1 should be >= 5, got {result.score_pass1}"
    print(f"  Pass 1 >= 5: PASS ({result.score_pass1})")
    assert result.score_pass2 >= 7, f"Pass 2 should add >= 7, got {result.score_pass2}"
    print(f"  Pass 2 >= 7: PASS ({result.score_pass2})")
    assert result.score_total >= 12, f"Total should be >= 12, got {result.score_total}"
    print(f"  Total >= 12: PASS ({result.score_total})")
    assert "wallet_neuf" in result.flags_triggered
    assert "mise_massive" in result.flags_triggered or "marché_improbable" in result.flags_triggered
    print("  Key flags present: PASS")

    # Verify flat payload: no nested dicts, no null values
    payload_json = json.dumps(payload)
    assert "null" not in payload_json, f"Payload contains null: {payload_json}"
    print("  No null in payload: PASS")
    for key, val in payload.items():
        assert not isinstance(val, dict), f"Payload key '{key}' is nested dict"
    print("  No nested objects: PASS")
    print()
    print("All Maduro test assertions passed!")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    _run_maduro_test()
