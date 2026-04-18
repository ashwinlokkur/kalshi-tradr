"""Async HTTP client for the Kalshi v2 trading API.

Uses RSA-PSS request signing as documented at
https://docs.kalshi.com/getting_started/quick_start_create_order.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import time
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from .types import Balance, Event, Market, OrderResult, Position, RestingOrder

log = logging.getLogger(__name__)

_MAX_RETRIES = 5
_BASE_BACKOFF = 1.0
_MAX_BACKOFF = 60.0


def _parse_market(d: dict[str, Any]) -> Market:
    return Market(
        ticker=d.get("ticker", ""),
        event_ticker=d.get("event_ticker", ""),
        title=d.get("title", ""),
        subtitle=d.get("subtitle") or d.get("yes_sub_title") or "",
        status=d.get("status", ""),
        close_ts=_ts(d.get("close_time")),
        yes_bid=d.get("yes_bid"),
        yes_ask=d.get("yes_ask"),
        no_bid=d.get("no_bid"),
        no_ask=d.get("no_ask"),
        last_price=d.get("last_price"),
        volume=d.get("volume"),
        raw=d,
    )


def _parse_event(d: dict[str, Any]) -> Event:
    markets = [_parse_market(m) for m in d.get("markets", []) or []]
    return Event(
        event_ticker=d.get("event_ticker", ""),
        series_ticker=d.get("series_ticker", ""),
        title=d.get("title", ""),
        sub_title=d.get("sub_title", ""),
        markets=markets,
        raw=d,
    )


def _ts(value: Any) -> int:
    """Accept either Unix seconds (int) or ISO-8601 string and return Unix seconds."""
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        from datetime import datetime

        # Kalshi returns RFC3339, e.g. "2026-04-18T20:00:00Z"
        s = value.replace("Z", "+00:00")
        return int(datetime.fromisoformat(s).timestamp())
    return 0


class KalshiAsyncClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key_id: str,
        private_key_pem: str,
        timeout: float = 20.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key_id = api_key_id
        self._private_key = self._load_key(private_key_pem)
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout)

    @staticmethod
    def _load_key(pem: str) -> rsa.RSAPrivateKey:
        key = serialization.load_pem_private_key(pem.encode(), password=None)
        if not isinstance(key, rsa.RSAPrivateKey):
            raise ValueError("Kalshi API key must be an RSA private key")
        return key

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------ signing

    def _sign(self, method: str, path: str) -> dict[str, str]:
        # Kalshi signs "<timestamp_ms><METHOD><path>" with RSA-PSS(SHA-256)
        ts_ms = str(int(time.time() * 1000))
        message = (ts_ms + method.upper() + path).encode()
        sig = self._private_key.sign(
            message,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )
        return {
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(),
            "KALSHI-ACCESS-TIMESTAMP": ts_ms,
            "Accept": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # Sign just the path (no query string) per Kalshi spec.
        if not path.startswith("/trade-api/"):
            sign_path = "/trade-api/v2" + path
        else:
            sign_path = path
        url = path if path.startswith("/trade-api/") else path

        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            headers = self._sign(method, sign_path)
            if json is not None:
                headers["Content-Type"] = "application/json"
            try:
                resp = await self._client.request(
                    method, url, params=params, json=json, headers=headers
                )
            except httpx.HTTPError as e:
                last_exc = e
                await asyncio.sleep(min(_BASE_BACKOFF * (2**attempt), _MAX_BACKOFF))
                continue

            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After") or 0.0)
                wait = max(retry_after, min(_BASE_BACKOFF * (2**attempt), _MAX_BACKOFF))
                log.warning("Kalshi 429; retrying in %.1fs", wait)
                await asyncio.sleep(wait)
                continue
            if 500 <= resp.status_code < 600:
                await asyncio.sleep(min(_BASE_BACKOFF * (2**attempt), _MAX_BACKOFF))
                continue

            if resp.status_code >= 400:
                raise KalshiAPIError(
                    f"{method} {path} failed: {resp.status_code} {resp.text}"
                )
            if not resp.content:
                return {}
            return resp.json()

        raise KalshiAPIError(f"{method} {path} failed after {_MAX_RETRIES} retries: {last_exc}")

    # ---------------------------------------------------------------- endpoints

    async def get_balance(self) -> Balance:
        data = await self._request("GET", "/portfolio/balance")
        return Balance(
            balance_cents=int(data.get("balance", 0)),
            payout_cents=int(data.get("payout", 0)),
        )

    async def get_positions(self) -> list[Position]:
        data = await self._request("GET", "/portfolio/positions", params={"limit": 200})
        out: list[Position] = []
        for d in data.get("market_positions", []) or []:
            if int(d.get("position", 0)) == 0:
                continue
            out.append(
                Position(
                    ticker=d.get("ticker", ""),
                    position=int(d.get("position", 0)),
                    market_exposure=int(d.get("market_exposure", 0)),
                    realized_pnl=int(d.get("realized_pnl", 0)),
                    raw=d,
                )
            )
        return out

    async def get_resting_orders(self) -> list[RestingOrder]:
        data = await self._request(
            "GET", "/portfolio/orders", params={"status": "resting", "limit": 200}
        )
        out: list[RestingOrder] = []
        for d in data.get("orders", []) or []:
            side = d.get("side") or ""
            price_cents = int(d.get("yes_price") if side == "yes" else d.get("no_price") or 0)
            out.append(
                RestingOrder(
                    order_id=d.get("order_id", ""),
                    ticker=d.get("ticker", ""),
                    side=side,
                    action=d.get("action", ""),
                    count=int(d.get("count", 0)),
                    remaining_count=int(d.get("remaining_count", 0)),
                    price_cents=price_cents,
                    status=d.get("status", ""),
                    raw=d,
                )
            )
        return out

    async def list_open_markets(
        self,
        *,
        min_close_ts: int | None = None,
        max_close_ts: int | None = None,
        page_size: int = 200,
        max_pages: int = 20,
    ) -> list[Market]:
        params: dict[str, Any] = {"status": "open", "limit": page_size}
        if min_close_ts is not None:
            params["min_close_ts"] = min_close_ts
        if max_close_ts is not None:
            params["max_close_ts"] = max_close_ts

        out: list[Market] = []
        cursor: str | None = None
        for _ in range(max_pages):
            p = dict(params)
            if cursor:
                p["cursor"] = cursor
            data = await self._request("GET", "/markets", params=p)
            for m in data.get("markets", []) or []:
                out.append(_parse_market(m))
            cursor = data.get("cursor") or None
            if not cursor:
                break
        return out

    async def list_open_events(self, *, page_size: int = 200, max_pages: int = 10) -> list[Event]:
        params: dict[str, Any] = {"status": "open", "limit": page_size, "with_nested_markets": "true"}
        out: list[Event] = []
        cursor: str | None = None
        for _ in range(max_pages):
            p = dict(params)
            if cursor:
                p["cursor"] = cursor
            data = await self._request("GET", "/events", params=p)
            for e in data.get("events", []) or []:
                out.append(_parse_event(e))
            cursor = data.get("cursor") or None
            if not cursor:
                break
        return out

    async def get_market(self, ticker: str) -> Market:
        data = await self._request("GET", f"/markets/{ticker}")
        return _parse_market(data.get("market") or data)

    async def place_order(
        self,
        *,
        ticker: str,
        side: str,  # 'yes' | 'no'
        count: int,
        price_cents: int,
        action: str = "buy",
        client_order_id: str,
        order_type: str = "limit",
    ) -> OrderResult:
        body: dict[str, Any] = {
            "ticker": ticker,
            "side": side,
            "action": action,
            "count": count,
            "type": order_type,
            "client_order_id": client_order_id,
        }
        if side == "yes":
            body["yes_price"] = price_cents
        else:
            body["no_price"] = price_cents

        data = await self._request("POST", "/portfolio/orders", json=body)
        order = data.get("order") or data
        return OrderResult(
            order_id=order.get("order_id"),
            status=order.get("status", "unknown"),
            filled_count=int(order.get("filled_count", 0) or 0),
            remaining_count=int(order.get("remaining_count", 0) or 0),
            raw=order,
        )


class KalshiAPIError(RuntimeError):
    pass
