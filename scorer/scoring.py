"""Pure scoring functions — no I/O, fully testable.

score_trade() is the single entry point. It takes an enriched trade dict
(from Bloc 1) and an optional wallet profile dict (from the profiler),
and returns a ScoringResult with the total score, per-pass breakdown,
triggered flags, and detailed evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from scorer.config import (
    CONTRE_COURANT_THRESHOLD,
    IMPROBABLE_PROBABILITY_THRESHOLD,
    LOW_PRICE_THRESHOLD,
    MARKET_VOLUME_LOW_THRESHOLD,
    PASS1_WEIGHTS,
    PASS2_WEIGHTS,
    SPIKE_VOLUME_MULTIPLIER,
    TIMING_CLOSE_DAYS,
    TRADE_SIZE_RATIO_THRESHOLD,
    WALLET_AGE_NEW_DAYS,
    WALLET_AGE_RECENT_DAYS,
    WALLET_FEW_TX_THRESHOLD,
    WALLET_LOW_MARKETS_THRESHOLD,
)


@dataclass
class FlagDetail:
    points: int
    evidence: str


@dataclass
class ScoringResult:
    score_total: int = 0
    score_pass1: int = 0
    score_pass2: int = 0
    flags_triggered: list[str] = field(default_factory=list)
    flags_detail: dict[str, dict[str, Any]] = field(default_factory=dict)

    def add_flag(self, name: str, points: int, evidence: str, pass_num: int) -> None:
        self.flags_triggered.append(name)
        self.flags_detail[name] = {"points": points, "evidence": evidence}
        self.score_total += points
        if pass_num == 1:
            self.score_pass1 += points
        else:
            self.score_pass2 += points


# ── Pass 1 — Trade + Market (no external calls) ──────────────


def _check_mise_massive(trade: dict[str, Any], result: ScoringResult) -> None:
    """Trade size disproportionate vs market volume."""
    usdc_size = trade.get("usdc_size", 0) or 0
    volume = trade.get("market_volume_24h") or 0
    if volume > 0 and usdc_size > volume * TRADE_SIZE_RATIO_THRESHOLD:
        ratio = usdc_size / volume
        result.add_flag(
            "mise_massive",
            PASS1_WEIGHTS["mise_massive"],
            f"Trade {usdc_size:.0f} USDC = {ratio:.1%} of 24h volume ({volume:.0f})",
            pass_num=1,
        )


def _check_marche_improbable(trade: dict[str, Any], result: ScoringResult) -> None:
    """BUY on highly improbable outcome."""
    side = (trade.get("side") or "").upper()
    prob = trade.get("market_probability")
    if side == "BUY" and prob is not None and prob < IMPROBABLE_PROBABILITY_THRESHOLD:
        result.add_flag(
            "marché_improbable",
            PASS1_WEIGHTS["marché_improbable"],
            f"BUY at probability {prob:.1%} (threshold: {IMPROBABLE_PROBABILITY_THRESHOLD:.0%})",
            pass_num=1,
        )


def _check_marche_niche(trade: dict[str, Any], result: ScoringResult) -> None:
    """Low-liquidity / niche market."""
    volume = trade.get("market_volume_24h")
    if volume is not None and volume < MARKET_VOLUME_LOW_THRESHOLD:
        result.add_flag(
            "marché_niche",
            PASS1_WEIGHTS["marché_niche"],
            f"24h volume {volume:.0f} USDC < {MARKET_VOLUME_LOW_THRESHOLD:.0f} threshold",
            pass_num=1,
        )


def _check_prix_bas(trade: dict[str, Any], result: ScoringResult) -> None:
    """Very low entry price."""
    price = trade.get("price", 0) or 0
    if 0 < price < LOW_PRICE_THRESHOLD:
        result.add_flag(
            "mouvement_prix",
            PASS1_WEIGHTS["mouvement_prix"],
            f"Entry price {price:.2f} < {LOW_PRICE_THRESHOLD:.2f}",
            pass_num=1,
        )


def _check_timing_serre(trade: dict[str, Any], result: ScoringResult) -> None:
    """Trade close to market resolution date."""
    end_date_str = trade.get("market_end_date")
    if not end_date_str:
        return
    try:
        end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        days_left = (end_date - now).total_seconds() / 86400
        if 0 < days_left <= TIMING_CLOSE_DAYS:
            result.add_flag(
                "timing_serré",
                PASS1_WEIGHTS["timing_serré"],
                f"Market ends in {days_left:.1f} days (threshold: {TIMING_CLOSE_DAYS})",
                pass_num=1,
            )
    except (ValueError, TypeError):
        pass


def _check_spike_volume(trade: dict[str, Any], result: ScoringResult) -> None:
    """Trade size is a spike relative to market volume (simple heuristic)."""
    usdc_size = trade.get("usdc_size", 0) or 0
    volume = trade.get("market_volume_24h") or 0
    if volume > 0:
        # Average trade size heuristic: volume / 100 trades per day
        avg_trade = volume / 100
        if avg_trade > 0 and usdc_size > avg_trade * SPIKE_VOLUME_MULTIPLIER:
            result.add_flag(
                "spike_volume",
                PASS1_WEIGHTS["spike_volume"],
                f"Trade {usdc_size:.0f} > {SPIKE_VOLUME_MULTIPLIER}x avg ({avg_trade:.0f})",
                pass_num=1,
            )


def _check_contre_courant(trade: dict[str, Any], result: ScoringResult) -> None:
    """BUY against market consensus (but not extreme enough for marché_improbable)."""
    side = (trade.get("side") or "").upper()
    prob = trade.get("market_probability")
    if (
        side == "BUY"
        and prob is not None
        and IMPROBABLE_PROBABILITY_THRESHOLD <= prob < CONTRE_COURANT_THRESHOLD
    ):
        result.add_flag(
            "comportement_brutal",
            PASS1_WEIGHTS["comportement_brutal"],
            f"BUY against consensus at probability {prob:.1%}",
            pass_num=1,
        )


def score_pass1(trade: dict[str, Any]) -> ScoringResult:
    """Run all Pass 1 checks on an enriched trade.

    Args:
        trade: Enriched trade dict from Bloc 1.

    Returns:
        ScoringResult with Pass 1 flags and score.
    """
    result = ScoringResult()
    _check_mise_massive(trade, result)
    _check_marche_improbable(trade, result)
    _check_marche_niche(trade, result)
    _check_prix_bas(trade, result)
    _check_timing_serre(trade, result)
    _check_spike_volume(trade, result)
    _check_contre_courant(trade, result)
    return result


# ── Pass 2 — Wallet profile ─────────────────────────────────


def _check_wallet_neuf(profile: dict[str, Any], result: ScoringResult) -> None:
    """Brand new wallet (< 7 days)."""
    age = profile.get("age_days")
    if age is not None and age < WALLET_AGE_NEW_DAYS:
        result.add_flag(
            "wallet_neuf",
            PASS2_WEIGHTS["wallet_neuf"],
            f"Wallet age: {age} days (threshold: {WALLET_AGE_NEW_DAYS})",
            pass_num=2,
        )


def _check_compte_recent(profile: dict[str, Any], result: ScoringResult) -> None:
    """Recent but not brand-new wallet (7-30 days)."""
    age = profile.get("age_days")
    if age is not None and WALLET_AGE_NEW_DAYS <= age < WALLET_AGE_RECENT_DAYS:
        result.add_flag(
            "compte_récent",
            PASS2_WEIGHTS["compte_récent"],
            f"Wallet age: {age} days (recent: {WALLET_AGE_NEW_DAYS}-{WALLET_AGE_RECENT_DAYS})",
            pass_num=2,
        )


def _check_peu_tx(profile: dict[str, Any], result: ScoringResult) -> None:
    """Very few on-chain transactions."""
    tx_count = profile.get("tx_count")
    if tx_count is not None and tx_count < WALLET_FEW_TX_THRESHOLD:
        result.add_flag(
            "peu_tx",
            PASS2_WEIGHTS["peu_tx"],
            f"Only {tx_count} lifetime transactions (threshold: {WALLET_FEW_TX_THRESHOLD})",
            pass_num=2,
        )


def _check_activite_concentree(profile: dict[str, Any], result: ScoringResult) -> None:
    """Trades concentrated on very few markets."""
    markets_count = profile.get("markets_count")
    if markets_count is not None and markets_count <= WALLET_LOW_MARKETS_THRESHOLD:
        result.add_flag(
            "activité_concentrée",
            PASS2_WEIGHTS["activité_concentrée"],
            f"Active on only {markets_count} market(s) (threshold: {WALLET_LOW_MARKETS_THRESHOLD})",
            pass_num=2,
        )


def _check_pattern_maduro(profile: dict[str, Any], result: ScoringResult) -> None:
    """First-ever Polymarket activity (no prior trades)."""
    first_trade = profile.get("first_polymarket_trade")
    if first_trade is None:
        result.add_flag(
            "pattern_maduro",
            PASS2_WEIGHTS["pattern_maduro"],
            "No prior Polymarket trading history found",
            pass_num=2,
        )


def _check_correlation_temporelle(profile: dict[str, Any], result: ScoringResult) -> None:
    """No resolved trades in history (win/loss unknown)."""
    win_loss = profile.get("win_loss")
    if win_loss is None or win_loss == "":
        result.add_flag(
            "corrélation_temporelle",
            PASS2_WEIGHTS["corrélation_temporelle"],
            "No resolved trades in history — W/L unknown",
            pass_num=2,
        )


def _check_financement_suspect(profile: dict[str, Any], result: ScoringResult) -> None:
    """Suspicious funding source."""
    funding = profile.get("funding_source") or ""
    if "mixer" in funding.lower() or "tornado" in funding.lower() or "suspect" in funding.lower():
        result.add_flag(
            "financement_suspect",
            PASS2_WEIGHTS["financement_suspect"],
            f"Funding source flagged: {funding}",
            pass_num=2,
        )


def score_pass2(profile: dict[str, Any], result: ScoringResult) -> ScoringResult:
    """Run all Pass 2 checks on a wallet profile.

    Args:
        profile: Wallet profile dict from the profiler.
        result: Existing ScoringResult from Pass 1 (mutated in place).

    Returns:
        The same ScoringResult with Pass 2 flags added.
    """
    _check_wallet_neuf(profile, result)
    _check_compte_recent(profile, result)
    _check_peu_tx(profile, result)
    _check_activite_concentree(profile, result)
    _check_pattern_maduro(profile, result)
    _check_correlation_temporelle(profile, result)
    _check_financement_suspect(profile, result)
    return result


# ── Combined entry point ─────────────────────────────────────


def score_trade(
    trade: dict[str, Any],
    wallet_profile: dict[str, Any] | None = None,
) -> ScoringResult:
    """Score a trade across both passes.

    This is the main entry point for testing. It's a pure function —
    no I/O, no network calls.

    Args:
        trade: Enriched trade dict from Bloc 1.
        wallet_profile: Optional wallet profile dict. If None, only
            Pass 1 is executed.

    Returns:
        ScoringResult with full breakdown.
    """
    result = score_pass1(trade)
    if wallet_profile is not None:
        score_pass2(wallet_profile, result)
    return result
