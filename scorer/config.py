"""Scorer configuration: thresholds, red flag weights, API keys.

All values are loaded from environment variables with sensible defaults.
Red flag weights are defined as a dict so they can be overridden without
touching scoring logic.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# ── Pass thresholds ────────────────────────────────────────────
PASS1_THRESHOLD = int(os.getenv("PASS1_THRESHOLD", "5"))
PASS2_THRESHOLD = int(os.getenv("PASS2_THRESHOLD", "10"))

# ── Pass 1 parameter thresholds ────────────────────────────────
TRADE_SIZE_RATIO_THRESHOLD = float(os.getenv("TRADE_SIZE_RATIO_THRESHOLD", "0.02"))
IMPROBABLE_PROBABILITY_THRESHOLD = float(os.getenv("IMPROBABLE_PROBABILITY_THRESHOLD", "0.10"))
MARKET_VOLUME_LOW_THRESHOLD = float(os.getenv("MARKET_VOLUME_LOW_THRESHOLD", "50000"))
LOW_PRICE_THRESHOLD = float(os.getenv("LOW_PRICE_THRESHOLD", "0.10"))
TIMING_CLOSE_DAYS = int(os.getenv("TIMING_CLOSE_DAYS", "7"))
SPIKE_VOLUME_MULTIPLIER = float(os.getenv("SPIKE_VOLUME_MULTIPLIER", "5.0"))
CONTRE_COURANT_THRESHOLD = float(os.getenv("CONTRE_COURANT_THRESHOLD", "0.30"))

# ── Entry filters (Ticket #8 — anti-noise) ───────────────────────
MIN_GAIN_POTENTIEL = float(os.getenv("MIN_GAIN_POTENTIEL", "500"))
BOT_MARKETS_THRESHOLD = int(os.getenv("BOT_MARKETS_THRESHOLD", "30"))
BOT_WIN_RATE_THRESHOLD = float(os.getenv("BOT_WIN_RATE_THRESHOLD", "0.80"))
MARCHE_IMPROBABLE_PRICE_CEILING = float(os.getenv("MARCHE_IMPROBABLE_PRICE_CEILING", "0.70"))
PUBLIC_RESOLUTION_PATTERNS: list[str] = [
    "price-of",
    "be-between",
    "be-less-than",
    "be-above",
    "be-greater-than",
]

# ── Pass 2 parameter thresholds ────────────────────────────────
WALLET_AGE_NEW_DAYS = int(os.getenv("WALLET_AGE_NEW_DAYS", "7"))
WALLET_AGE_RECENT_DAYS = int(os.getenv("WALLET_AGE_RECENT_DAYS", "30"))
WALLET_FEW_TX_THRESHOLD = int(os.getenv("WALLET_FEW_TX_THRESHOLD", "5"))
WALLET_LOW_MARKETS_THRESHOLD = int(os.getenv("WALLET_LOW_MARKETS_THRESHOLD", "3"))
FUNDING_RECENT_HOURS = int(os.getenv("FUNDING_RECENT_HOURS", "48"))

# ── Red flag weights ──────────────────────────────────────────
# Pass 1 flags (trade + market)
PASS1_WEIGHTS: dict[str, int] = {
    "mise_massive": int(os.getenv("WEIGHT_MISE_MASSIVE", "3")),
    "marché_improbable": int(os.getenv("WEIGHT_MARCHE_IMPROBABLE", "3")),
    "marché_niche": int(os.getenv("WEIGHT_MARCHE_NICHE", "3")),
    "mouvement_prix": int(os.getenv("WEIGHT_MOUVEMENT_PRIX", "1")),
    "timing_serré": int(os.getenv("WEIGHT_TIMING_SERRE", "1")),
    "spike_volume": int(os.getenv("WEIGHT_SPIKE_VOLUME", "1")),
    "comportement_brutal": int(os.getenv("WEIGHT_COMPORTEMENT_BRUTAL", "1")),
}

# Pass 2 flags (wallet)
PASS2_WEIGHTS: dict[str, int] = {
    "wallet_neuf": int(os.getenv("WEIGHT_WALLET_NEUF", "3")),
    "activité_concentrée": int(os.getenv("WEIGHT_ACTIVITE_CONCENTREE", "2")),
    "peu_tx": int(os.getenv("WEIGHT_PEU_TX", "2")),
    "financement_suspect": int(os.getenv("WEIGHT_FINANCEMENT_SUSPECT", "2")),
    "compte_récent": int(os.getenv("WEIGHT_COMPTE_RECENT", "1")),
    "pattern_maduro": int(os.getenv("WEIGHT_PATTERN_MADURO", "2")),
    "corrélation_temporelle": int(os.getenv("WEIGHT_CORRELATION_TEMPORELLE", "2")),
}

# ── Webhook ────────────────────────────────────────────────────
MAKE_WEBHOOK_URL = os.getenv("MAKE_WEBHOOK_URL", "")
WEBHOOK_TIMEOUT = int(os.getenv("WEBHOOK_TIMEOUT", "15"))
WEBHOOK_RETRY_DELAY = int(os.getenv("WEBHOOK_RETRY_DELAY", "5"))

# ── Alchemy ────────────────────────────────────────────────────
ALCHEMY_API_KEY = os.getenv("ALCHEMY_API_KEY", "")
ALCHEMY_NETWORK = os.getenv("ALCHEMY_NETWORK", "polygon-mainnet")

# ── API (reuse from ingestor) ──────────────────────────────────
API_BASE_URL = os.getenv("API_BASE_URL", "https://data-api.polymarket.com").rstrip("/")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))

# ── Local fallback ─────────────────────────────────────────────
FALLBACK_DIR = os.getenv("SCORER_FALLBACK_DIR", "data/failed_webhooks")

# ── Known suspicious addresses (basic heuristic) ──────────────
KNOWN_MIXERS = {
    "0xd90e2f925da726b50c4ed8d0fb90ad053324f31b",  # Tornado Cash proxy
    "0x722122df12d4e14e13ac3b6895a86e84145b6967",  # Tornado Cash router
    "0xba214c1c1928a32bffe790263e38b4af9bfcd659",  # Tornado Cash
}
