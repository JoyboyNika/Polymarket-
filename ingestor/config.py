"""Ingestor configuration loaded from environment variables."""

import os

from dotenv import load_dotenv

load_dotenv()

POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "300"))
FILTER_AMOUNT_USDC = int(os.getenv("FILTER_AMOUNT_USDC", "1000"))
DEDUP_WINDOW_HOURS = int(os.getenv("DEDUP_WINDOW_HOURS", "24"))
API_BASE_URL = os.getenv("API_BASE_URL", "https://data-api.polymarket.com").rstrip("/")
GAMMA_API_URL = os.getenv("GAMMA_API_URL", "https://gamma-api.polymarket.com").rstrip("/")

# Max trades per API request (Polymarket hard limit: 500)
API_PAGE_LIMIT = 500

# Request timeout in seconds
REQUEST_TIMEOUT = 30
