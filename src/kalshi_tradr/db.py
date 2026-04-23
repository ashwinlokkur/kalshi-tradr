from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import asyncpg

log = logging.getLogger(__name__)

PENDING_TTL = timedelta(minutes=5)

SCHEMA = """
CREATE TABLE IF NOT EXISTS pending_bets (
  id           UUID PRIMARY KEY,
  chat_id      BIGINT NOT NULL,
  user_id      BIGINT NOT NULL,
  ticker       TEXT NOT NULL,
  side         TEXT NOT NULL,
  count        INT NOT NULL,
  price_cents  INT NOT NULL,
  est_cost_usd NUMERIC(10,2) NOT NULL,
  reason       TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at   TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS pending_bets_chat_idx ON pending_bets(chat_id);

CREATE TABLE IF NOT EXISTS placed_bets (
  id              UUID PRIMARY KEY,
  chat_id         BIGINT NOT NULL,
  user_id         BIGINT NOT NULL,
  kalshi_order_id TEXT,
  ticker          TEXT NOT NULL,
  side            TEXT NOT NULL,
  count           INT NOT NULL,
  price_cents     INT NOT NULL,
  cost_usd        NUMERIC(10,2) NOT NULL,
  status          TEXT NOT NULL,
  error           TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS placed_bets_chat_idx ON placed_bets(chat_id);
"""


@dataclass(slots=True)
class PendingBet:
    id: uuid.UUID
    chat_id: int
    user_id: int
    ticker: str
    side: str
    count: int
    price_cents: int
    est_cost_usd: Decimal
    reason: str | None
    expires_at: datetime


@dataclass(slots=True)
class PlacedBetRow:
    ticker: str
    side: str
    count: int
    price_cents: int
    cost_usd: Decimal
    status: str
    error: str | None
    created_at: datetime


class Database:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    @classmethod
    async def connect(cls, dsn: str) -> Database:
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)
        db = cls(pool)
        await db._bootstrap()
        return db

    async def close(self) -> None:
        await self.pool.close()

    async def _bootstrap(self) -> None:
        async with self.pool.acquire() as con:
            await con.execute(SCHEMA)

    async def create_pending_bet(
        self,
        *,
        chat_id: int,
        user_id: int,
        ticker: str,
        side: str,
        count: int,
        price_cents: int,
        est_cost_usd: float,
        reason: str | None = None,
    ) -> PendingBet:
        pb = PendingBet(
            id=uuid.uuid4(),
            chat_id=chat_id,
            user_id=user_id,
            ticker=ticker,
            side=side,
            count=count,
            price_cents=price_cents,
            est_cost_usd=Decimal(f"{est_cost_usd:.2f}"),
            reason=reason,
            expires_at=datetime.now(timezone.utc) + PENDING_TTL,
        )
        await self.pool.execute(
            """
            INSERT INTO pending_bets
              (id, chat_id, user_id, ticker, side, count, price_cents, est_cost_usd, reason, expires_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            """,
            pb.id,
            pb.chat_id,
            pb.user_id,
            pb.ticker,
            pb.side,
            pb.count,
            pb.price_cents,
            pb.est_cost_usd,
            pb.reason,
            pb.expires_at,
        )
        return pb

    async def take_pending_bet(self, pending_id: uuid.UUID, chat_id: int) -> PendingBet | None:
        """Atomically delete + return a pending bet if it belongs to chat_id and isn't expired."""
        row = await self.pool.fetchrow(
            """
            DELETE FROM pending_bets
            WHERE id = $1 AND chat_id = $2 AND expires_at > now()
            RETURNING id, chat_id, user_id, ticker, side, count, price_cents,
                      est_cost_usd, reason, expires_at
            """,
            pending_id,
            chat_id,
        )
        if row is None:
            return None
        return PendingBet(
            id=row["id"],
            chat_id=row["chat_id"],
            user_id=row["user_id"],
            ticker=row["ticker"],
            side=row["side"],
            count=row["count"],
            price_cents=row["price_cents"],
            est_cost_usd=row["est_cost_usd"],
            reason=row["reason"],
            expires_at=row["expires_at"],
        )

    async def recent_placed_bets(self, chat_id: int, *, limit: int = 5) -> list[PlacedBetRow]:
        rows = await self.pool.fetch(
            """
            SELECT ticker, side, count, price_cents, cost_usd, status, error, created_at
            FROM placed_bets
            WHERE chat_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            chat_id,
            limit,
        )
        return [
            PlacedBetRow(
                ticker=r["ticker"],
                side=r["side"],
                count=r["count"],
                price_cents=r["price_cents"],
                cost_usd=r["cost_usd"],
                status=r["status"],
                error=r["error"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    async def record_placed_bet(
        self,
        *,
        chat_id: int,
        user_id: int,
        kalshi_order_id: str | None,
        ticker: str,
        side: str,
        count: int,
        price_cents: int,
        cost_usd: float,
        status: str,
        error: str | None = None,
    ) -> uuid.UUID:
        bet_id = uuid.uuid4()
        await self.pool.execute(
            """
            INSERT INTO placed_bets
              (id, chat_id, user_id, kalshi_order_id, ticker, side, count, price_cents,
               cost_usd, status, error)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
            """,
            bet_id,
            chat_id,
            user_id,
            kalshi_order_id,
            ticker,
            side,
            count,
            price_cents,
            Decimal(f"{cost_usd:.2f}"),
            status,
            error,
        )
        return bet_id
