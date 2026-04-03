# utils/config.py
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class EbayConfig:
    client_id: str
    client_secret: str
    marketplace_id: str = "EBAY_US"
    environment: str = "production"  # "production" or "sandbox"

    @property
    def oauth_url(self) -> str:
        if self.environment == "sandbox":
            return "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
        return "https://api.ebay.com/identity/v1/oauth2/token"

    @property
    def browse_base_url(self) -> str:
        if self.environment == "sandbox":
            return "https://api.sandbox.ebay.com/buy/browse/v1"
        return "https://api.ebay.com/buy/browse/v1"


def load_ebay_config() -> EbayConfig:
    client_id = os.getenv("EBAY_CLIENT_ID", "").strip()
    client_secret = os.getenv("EBAY_CLIENT_SECRET", "").strip()
    marketplace_id = os.getenv("EBAY_MARKETPLACE_ID", "EBAY_US").strip()
    environment = os.getenv("EBAY_ENV", "production").strip().lower()

    missing = []
    if not client_id:
        missing.append("EBAY_CLIENT_ID")
    if not client_secret:
        missing.append("EBAY_CLIENT_SECRET")

    if missing:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}"
        )

    return EbayConfig(
        client_id=client_id,
        client_secret=client_secret,
        marketplace_id=marketplace_id,
        environment=environment,
    )