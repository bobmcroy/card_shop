# providers/ebay_browse.py
from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests

from utils.config import EbayConfig


SCOPE_BUY_BROWSE = "https://api.ebay.com/oauth/api_scope"


@dataclass
class OAuthToken:
    access_token: str
    expires_in: int
    token_type: str
    created_at_epoch: float

    @property
    def is_expired(self) -> bool:
        # Refresh a little early
        return time.time() >= (self.created_at_epoch + self.expires_in - 60)


class EbayBrowseClient:
    def __init__(self, config: EbayConfig, timeout_s: int = 30) -> None:
        self.config = config
        self.timeout_s = timeout_s
        self._token: Optional[OAuthToken] = None

    def _basic_auth_header(self) -> str:
        raw = f"{self.config.client_id}:{self.config.client_secret}".encode("utf-8")
        return "Basic " + base64.b64encode(raw).decode("ascii")

    def get_application_token(self) -> OAuthToken:
        if self._token and not self._token.is_expired:
            return self._token

        resp = requests.post(
            self.config.oauth_url,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": self._basic_auth_header(),
            },
            data={
                "grant_type": "client_credentials",
                "scope": SCOPE_BUY_BROWSE,
            },
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        data = resp.json()

        self._token = OAuthToken(
            access_token=data["access_token"],
            expires_in=int(data["expires_in"]),
            token_type=data.get("token_type", ""),
            created_at_epoch=time.time(),
        )
        return self._token

    def search_items(
        self,
        query: str,
        *,
        limit: int = 10,
        offset: int = 0,
        filter_expr: str | None = None,
        sort: str | None = None,
    ) -> Dict[str, Any]:
        token = self.get_application_token()

        params: Dict[str, Any] = {
            "q": query,
            "limit": limit,
            "offset": offset,
        }
        if filter_expr:
            params["filter"] = filter_expr
        if sort:
            params["sort"] = sort

        resp = requests.get(
            f"{self.config.browse_base_url}/item_summary/search",
            headers={
                "Authorization": f"Bearer {token.access_token}",
                "X-EBAY-C-MARKETPLACE-ID": self.config.marketplace_id,
                "Accept": "application/json",
            },
            params=params,
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        return resp.json()