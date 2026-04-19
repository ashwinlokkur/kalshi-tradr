from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from ..config import Settings
from ..db import Database, PendingBet
from ..kalshi.client import KalshiAPIError, KalshiAsyncClient
from ..kalshi.types import Market
from ..strategy import matcher, scanner, sizing
from . import format as fmt

log = logging.getLogger(__name__)

HELP_TEXT = (
    "Kalshi trading bot\n"
    "\n"
    "Commands:\n"
    "  /scan              — lopsided markets closing in 1–3h\n"
    "  /bet <text> [amt]  — e.g. /bet warriors vs lakers 25\n"
    "  /search <text>     — list open events whose title matches <text>\n"
    "  /status            — balance, positions, resting orders\n"
    "  /help              — this message\n"
    "\n"
    "If no amount is given, Quarter-Kelly sizing is used (capped by MAX_BET_USD)."
)


@dataclass(slots=True)
class Deps:
    settings: Settings
    db: Database
    kalshi: KalshiAsyncClient


def _authorized(update: Update, settings: Settings) -> bool:
    chat = update.effective_chat
    if chat is None:
        return False
    return chat.id in settings.allowed_chat_ids


def _deps(context: ContextTypes.DEFAULT_TYPE) -> Deps:
    d = context.application.bot_data.get("deps")
    if d is None:
        raise RuntimeError("Bot deps not initialized")
    return d


async def _reject(update: Update) -> None:
    if update.effective_chat is not None:
        log.warning("rejected command from chat_id=%s", update.effective_chat.id)
    if update.message is not None:
        await update.message.reply_text("This bot is locked to a private allow-list.")


# ---------------------------------------------------------------------------- /


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update, _deps(context).settings):
        return await _reject(update)
    if update.message is not None:
        await update.message.reply_text(HELP_TEXT)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    return await cmd_start(update, context)


# ---------------------------------------------------------------------- /status


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Diagnostic: list up to 15 open events whose title matches the query tokens."""
    deps = _deps(context)
    if not _authorized(update, deps.settings):
        return await _reject(update)
    assert update.message is not None

    raw = " ".join(context.args or []).strip()
    if not raw:
        await update.message.reply_text("Usage: /search <text>\nEx: /search nba")
        return

    tokens = matcher.tokenize(raw)
    if not tokens:
        await update.message.reply_text("No searchable tokens in query (all stopwords).")
        return

    try:
        events = await deps.kalshi.list_open_events()
    except KalshiAPIError as e:
        await update.message.reply_text(f"Kalshi error: {e}")
        return

    scored = [(matcher.score_event(tokens, e), e) for e in events]
    scored = [(s, e) for s, e in scored if s > 0]
    scored.sort(key=lambda t: -t[0])
    top = scored[:15]

    lines = [
        f"env: {deps.settings.kalshi_env}   tokens: {', '.join(tokens)}",
        f"scanned {len(events)} open events; {len(scored)} matched.",
    ]
    if not top:
        lines.append("")
        lines.append("No matches. Sample of what's in the data right now:")
        lines.extend(f"- {e.title}" for e in events[:10] if e.title)
    else:
        lines.append("")
        lines.append("Top matches:")
        for s, e in top:
            lines.append(f"[{s:.0f}] {e.event_ticker}  {e.title[:80]}")
    await update.message.reply_text("\n".join(lines))


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    deps = _deps(context)
    if not _authorized(update, deps.settings):
        return await _reject(update)
    assert update.message is not None
    try:
        balance = await deps.kalshi.get_balance()
        positions = await deps.kalshi.get_positions()
        orders = await deps.kalshi.get_resting_orders()
    except KalshiAPIError as e:
        await update.message.reply_text(f"Kalshi error: {e}")
        return
    await update.message.reply_text(fmt.fmt_status(balance, positions, orders))


# ------------------------------------------------------------------------ /scan


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    deps = _deps(context)
    if not _authorized(update, deps.settings):
        return await _reject(update)
    assert update.message is not None
    s = deps.settings
    try:
        hits = await scanner.find_lopsided(
            deps.kalshi,
            params=scanner.ScanParams(
                min_hours=s.scan_min_hours,
                max_hours=s.scan_max_hours,
                min_prob=s.scan_min_prob,
                limit=s.scan_limit,
            ),
        )
    except KalshiAPIError as e:
        await update.message.reply_text(f"Kalshi error: {e}")
        return

    if not hits:
        await update.message.reply_text("No markets match the filter right now.")
        return

    text = fmt.fmt_scan(hits)
    # One "Bet" button per row, carrying ticker + side in the callback.
    buttons = []
    for idx, h in enumerate(hits, start=1):
        buttons.append(
            [
                InlineKeyboardButton(
                    f"Bet #{idx}  {h.side.upper()} @ {h.price_cents}¢",
                    callback_data=f"scanbet:{h.market.ticker}:{h.side}:{h.price_cents}",
                )
            ]
        )
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))


# ------------------------------------------------------------------------- /bet


async def cmd_bet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    deps = _deps(context)
    if not _authorized(update, deps.settings):
        return await _reject(update)
    assert update.message is not None

    raw = " ".join(context.args or []).strip()
    log.info("cmd_bet: chat=%s user=%s raw=%r", update.effective_chat.id if update.effective_chat else None, update.effective_user.id if update.effective_user else None, raw)
    if not raw:
        await update.message.reply_text("Usage: /bet <text> [amount]\nEx: /bet warriors vs lakers 25")
        return

    query_text, amount_usd = matcher.parse_amount_tail(raw)
    log.info("cmd_bet: query_text=%r amount_usd=%s", query_text, amount_usd)
    try:
        result = await matcher.find_candidates(deps.kalshi, query_text, top_k=3)
    except KalshiAPIError as e:
        await update.message.reply_text(f"Kalshi error: {e}")
        return

    if not result.candidates:
        lines = [
            f"No matching market for: {query_text!r}",
            f"Tokens searched: {', '.join(result.tokens) or '(none)'}",
            f"Scanned {result.total_events} open events; {result.matched_events} matched on tokens but had no usable markets.",
            f"Kalshi env: {deps.settings.kalshi_env}",
        ]
        if result.sample_titles:
            lines.append("")
            lines.append("A few open events right now:")
            lines.extend(f"- {t}" for t in result.sample_titles)
        await update.message.reply_text("\n".join(lines))
        return

    if len(result.candidates) > 1:
        buttons = [
            [
                InlineKeyboardButton(
                    f"{c.market.ticker}  ({c.event.title[:40]})",
                    callback_data=f"pick:{c.market.ticker}:{amount_usd or ''}",
                )
            ]
            for c in result.candidates
        ]
        await update.message.reply_text(
            "Multiple markets match — pick one:", reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    # Exactly one match
    c = result.candidates[0]
    log.info("cmd_bet: single match ticker=%s score=%.2f", c.market.ticker, c.score)
    await _propose_bet(
        update=update,
        context=context,
        market=c.market,
        amount_usd=amount_usd,
    )


# ---------------------------------------------------------- shared bet proposer


def _infer_side_and_price(market: Market) -> tuple[str, int] | None:
    """Pick the favored side (higher ask) and its ask price."""
    y = market.yes_ask
    n = market.no_ask
    if y is None and n is None:
        return None
    if y is None:
        return "no", int(n)  # type: ignore[arg-type]
    if n is None:
        return "yes", int(y)
    return ("yes", int(y)) if y >= n else ("no", int(n))


async def _propose_bet(
    *,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    market: Market,
    amount_usd: float | None,
    side_override: str | None = None,
    price_override: int | None = None,
) -> None:
    deps = _deps(context)
    s = deps.settings

    if side_override and price_override:
        side, price_cents = side_override, price_override
    else:
        picked = _infer_side_and_price(market)
        if picked is None:
            msg = update.effective_message
            if msg is not None:
                await msg.reply_text(f"No tradable quote for {market.ticker} right now.")
            return
        side, price_cents = picked

    if price_cents <= 0 or price_cents >= 100:
        msg = update.effective_message
        if msg is not None:
            await msg.reply_text(f"Market {market.ticker} price out of range: {price_cents}¢")
        return

    try:
        balance = await deps.kalshi.get_balance()
    except KalshiAPIError as e:
        msg = update.effective_message
        if msg is not None:
            await msg.reply_text(f"Kalshi error: {e}")
        return

    bankroll = balance.balance_usd
    if amount_usd is not None:
        sz = sizing.size_from_explicit_usd(amount_usd=amount_usd, price_cents=price_cents)
    else:
        prob = min(price_cents / 100.0 + s.edge_buffer, 0.99)
        sz = sizing.size_bet(
            bankroll_usd=bankroll,
            price_cents=price_cents,
            prob=prob,
            fraction=s.kelly_fraction,
            cap_usd=s.max_bet_usd,
        )

    if sz.count <= 0 or sz.stake_usd <= 0:
        msg = update.effective_message
        if msg is not None:
            await msg.reply_text(f"Sizing produced 0 contracts ({sz.reason}). Skipping.")
        return

    if sz.stake_usd > bankroll:
        msg = update.effective_message
        if msg is not None:
            await msg.reply_text(
                f"Stake ${sz.stake_usd:.2f} exceeds balance ${bankroll:.2f}. Skipping."
            )
        return

    chat = update.effective_chat
    user = update.effective_user
    assert chat is not None and user is not None

    pending = await deps.db.create_pending_bet(
        chat_id=chat.id,
        user_id=user.id,
        ticker=market.ticker,
        side=side,
        count=sz.count,
        price_cents=price_cents,
        est_cost_usd=sz.stake_usd,
        reason=sz.reason,
    )

    text = fmt.fmt_confirm(
        market=market,
        side=side,
        count=sz.count,
        price_cents=price_cents,
        stake_usd=sz.stake_usd,
        reason=sz.reason,
    )

    if s.bet_confirm_required:
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Confirm", callback_data=f"confirm:{pending.id}"),
                    InlineKeyboardButton("Cancel", callback_data=f"cancel:{pending.id}"),
                ]
            ]
        )
        msg = update.effective_message
        if msg is not None:
            await msg.reply_text(text + "\n\nTap Confirm within 5 min.", reply_markup=kb)
    else:
        msg = update.effective_message
        if msg is not None:
            await msg.reply_text(text + "\n\n(auto-confirm on: placing now)")
        await _place_confirmed(update, context, pending)


# --------------------------------------------------------- callback dispatching


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    deps = _deps(context)
    if not _authorized(update, deps.settings):
        return await _reject(update)
    q = update.callback_query
    if q is None or q.data is None:
        return
    await q.answer()
    parts = q.data.split(":", 3)
    kind = parts[0]

    if kind == "confirm":
        await _on_confirm(update, context, uuid.UUID(parts[1]))
    elif kind == "cancel":
        await _on_cancel(update, context, uuid.UUID(parts[1]))
    elif kind == "scanbet":
        ticker, side, price = parts[1], parts[2], int(parts[3])
        try:
            market = await deps.kalshi.get_market(ticker)
        except KalshiAPIError as e:
            await q.edit_message_text(f"Kalshi error: {e}")
            return
        await _propose_bet(
            update=update,
            context=context,
            market=market,
            amount_usd=None,
            side_override=side,
            price_override=price,
        )
    elif kind == "pick":
        ticker = parts[1]
        amt_raw = parts[2] if len(parts) > 2 else ""
        amount = float(amt_raw) if amt_raw else None
        try:
            market = await deps.kalshi.get_market(ticker)
        except KalshiAPIError as e:
            await q.edit_message_text(f"Kalshi error: {e}")
            return
        await _propose_bet(
            update=update, context=context, market=market, amount_usd=amount
        )
    else:
        await q.edit_message_text(f"Unknown action: {kind}")


async def _on_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE, pending_id: uuid.UUID
) -> None:
    deps = _deps(context)
    q = update.callback_query
    chat = update.effective_chat
    assert q is not None and chat is not None
    taken = await deps.db.take_pending_bet(pending_id, chat.id)
    if taken is None:
        await q.edit_message_text("Nothing to cancel (already handled or expired).")
        return
    await q.edit_message_text("Cancelled.")


async def _on_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE, pending_id: uuid.UUID
) -> None:
    deps = _deps(context)
    q = update.callback_query
    chat = update.effective_chat
    assert q is not None and chat is not None
    pending = await deps.db.take_pending_bet(pending_id, chat.id)
    if pending is None:
        await q.edit_message_text("Confirmation expired or already handled.")
        return
    await _place_confirmed(update, context, pending, via_callback=True)


async def _place_confirmed(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    pending: PendingBet,
    *,
    via_callback: bool = False,
) -> None:
    deps = _deps(context)
    q = update.callback_query
    msg = update.effective_message

    client_order_id = f"tg-{pending.id.hex[:20]}"
    try:
        result = await deps.kalshi.place_order(
            ticker=pending.ticker,
            side=pending.side,
            count=pending.count,
            price_cents=pending.price_cents,
            client_order_id=client_order_id,
        )
    except KalshiAPIError as e:
        await deps.db.record_placed_bet(
            chat_id=pending.chat_id,
            user_id=pending.user_id,
            kalshi_order_id=None,
            ticker=pending.ticker,
            side=pending.side,
            count=pending.count,
            price_cents=pending.price_cents,
            cost_usd=float(pending.est_cost_usd),
            status="failed",
            error=str(e),
        )
        text = f"Order failed: {e}"
        if via_callback and q is not None:
            await q.edit_message_text(text)
        elif msg is not None:
            await msg.reply_text(text)
        return

    await deps.db.record_placed_bet(
        chat_id=pending.chat_id,
        user_id=pending.user_id,
        kalshi_order_id=result.order_id,
        ticker=pending.ticker,
        side=pending.side,
        count=pending.count,
        price_cents=pending.price_cents,
        cost_usd=float(pending.est_cost_usd),
        status="submitted",
    )
    text = (
        f"Submitted {pending.count} x {pending.side.upper()} "
        f"@ {pending.price_cents}¢ on {pending.ticker}\n"
        f"order_id={result.order_id}  status={result.status}"
    )
    if via_callback and q is not None:
        await q.edit_message_text(text)
    elif msg is not None:
        await msg.reply_text(text)
