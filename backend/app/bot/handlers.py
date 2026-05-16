"""Command + callback handlers for the Telegram bot.

Each handler is an ``async`` function that receives a :class:`HandlerContext`
and is responsible for replying via the :class:`TelegramClient`.  Handlers
never raise — recoverable errors are reported back to the user, programming
errors bubble to the dispatcher which logs and replies with a generic
"please try again" message.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.client import TelegramApiError, TelegramClient
from app.bot.commands import BOT_COMMANDS
from app.bot.keyboards import balance_actions, main_menu, referral_share
from app.core.config import Settings
from app.core.logging import get_logger
from app.services.bot_users import register_or_update_user
from app.services.composio import ComposioClient
from app.services.image_generation import (
    QUALITY_COST,
    QUALITY_STANDARD,
    ImageGenerationService,
    ImageProviderError,
    InvalidPromptError,
)
from app.services.payment_packages import list_packages
from app.services.payments import (
    InvoiceNotFoundError,
    InvoicePayloadInvalidError,
    PackageNotFoundError,
    PaymentService,
)
from app.services.token_service import (
    InsufficientTokensError,
    UserNotFoundError,
)
from app.services.users import find_user_by_telegram_id
from app.services.video_generation import (
    SUPPORTED_TARIFFS,
    TARIFF_COST,
    TARIFF_DURATION,
    TARIFF_SHORT,
    InvalidReferenceImageError,
    InvalidTariffError,
    VideoGenerationService,
    VideoJobView,
    VideoProviderError,
)
from app.services.video_generation import (
    InvalidPromptError as VideoInvalidPromptError,
)

logger = get_logger(__name__)


@dataclass
class HandlerContext:
    """Everything a handler needs to do its job.

    ``message`` is set for command messages; ``callback_query`` is set for
    inline-button taps.  The dispatcher fills exactly one of them.

    ``composio`` is optional so legacy call sites and tests that only
    exercise Phase 1 handlers don't need to wire a mock client; the
    handlers that need it (``/image``) raise a friendly error when it's
    missing.
    """

    update: dict[str, Any]
    settings: Settings
    client: TelegramClient
    session: AsyncSession
    composio: ComposioClient | None = None
    message: dict[str, Any] | None = None
    callback_query: dict[str, Any] | None = None

    @property
    def chat_id(self) -> int | None:
        msg = self.message or (self.callback_query or {}).get("message")
        if not msg:
            return None
        chat = msg.get("chat") or {}
        return chat.get("id")

    @property
    def from_user(self) -> dict[str, Any] | None:
        if self.callback_query:
            return self.callback_query.get("from")
        if self.message:
            return self.message.get("from")
        return None


# ----------------------------------------------------------------- formatting

def _format_balance_text(token_balance: int, is_premium: bool) -> str:
    premium = " · ⭐ Premium" if is_premium else ""
    return (
        "💰 <b>Your balance</b>\n"
        f"Tokens available: <b>{token_balance}</b>{premium}\n\n"
        "Tap <i>Buy tokens</i> to top up or <i>Invite friends</i> to earn more."
    )


def _format_help_text() -> str:
    lines = ["<b>Available commands</b>"]
    for c in BOT_COMMANDS:
        lines.append(f"• /{c.command} — {c.description}")
    lines.append("")
    lines.append("Need a hand? Tap a button below to get started.")
    return "\n".join(lines)


def _build_referral_link(bot_username: str, referral_code: str) -> str:
    if not bot_username:
        return f"start=REF:{referral_code}"
    return f"https://t.me/{bot_username}?start={referral_code}"


def _parse_start_payload(text: str | None) -> str | None:
    if not text:
        return None
    parts = text.strip().split(maxsplit=1)
    if len(parts) < 2:
        return None
    return parts[1].strip() or None


# ----------------------------------------------------------------- commands


async def handle_start(ctx: HandlerContext) -> None:
    if ctx.chat_id is None or ctx.from_user is None:
        return

    payload = _parse_start_payload((ctx.message or {}).get("text"))
    result = await register_or_update_user(
        ctx.session,
        telegram_user=ctx.from_user,
        referral_payload=payload,
        signup_bonus_tokens=ctx.settings.telegram_signup_bonus_tokens,
        super_admin_ids=ctx.settings.super_admin_ids,
    )

    name = (result.user.first_name or "friend").strip() or "friend"
    if result.created:
        greeting = (
            f"👋 Welcome, {name}!\n"
            f"You received <b>{result.bonus_credited} tokens</b> "
            "as a signup bonus."
        )
        if result.referrer:
            inviter = result.referrer.first_name or result.referrer.username or "a friend"
            greeting += f"\n\nReferred by <b>{inviter}</b> — thank you both!"
    else:
        greeting = f"👋 Welcome back, {name}!\nYour balance: <b>{result.user.token_balance}</b> tokens."

    await ctx.client.send_message(
        ctx.chat_id,
        greeting,
        reply_markup=main_menu(mini_app_url=ctx.settings.telegram_mini_app_url or None),
    )


async def handle_help(ctx: HandlerContext) -> None:
    if ctx.chat_id is None:
        return
    await ctx.client.send_message(
        ctx.chat_id,
        _format_help_text(),
        reply_markup=main_menu(mini_app_url=ctx.settings.telegram_mini_app_url or None),
    )


async def handle_balance(ctx: HandlerContext) -> None:
    if ctx.chat_id is None or ctx.from_user is None:
        return
    user = await find_user_by_telegram_id(ctx.session, int(ctx.from_user["id"]))
    if user is None:
        await ctx.client.send_message(
            ctx.chat_id,
            "I don't recognise you yet — send /start to register.",
        )
        return
    await ctx.client.send_message(
        ctx.chat_id,
        _format_balance_text(user.token_balance, user.is_premium),
        reply_markup=balance_actions(),
    )


def _packages_keyboard() -> dict[str, Any]:
    """Inline keyboard listing every active Stars package."""
    rows: list[list[dict[str, Any]]] = []
    for pkg in list_packages():
        label = f"{pkg.title} — {pkg.stars} ⭐"
        if pkg.is_subscription:
            label = f"{pkg.title} — {pkg.stars} ⭐ / month"
        rows.append([{"text": label, "callback_data": f"buy:{pkg.code}"}])
    return {"inline_keyboard": rows}


def _format_packages_text() -> str:
    lines = ["🛒 <b>Token packages</b>", ""]
    for pkg in list_packages():
        suffix = " / month" if pkg.is_subscription else ""
        lines.append(
            f"• <b>{pkg.title}</b> — {pkg.stars} ⭐ "
            f"for {pkg.tokens} tokens{suffix}"
        )
    lines.append("")
    lines.append("Tap a package below to receive a payment link.")
    return "\n".join(lines)


async def handle_buy(ctx: HandlerContext) -> None:
    if ctx.chat_id is None:
        return
    await ctx.client.send_message(
        ctx.chat_id,
        _format_packages_text(),
        reply_markup=_packages_keyboard(),
    )


async def handle_buy_package(ctx: HandlerContext, *, package_code: str) -> None:
    """Issue a Stars invoice for ``package_code`` and DM the link to the user."""
    if ctx.chat_id is None or ctx.from_user is None:
        return
    user = await find_user_by_telegram_id(ctx.session, int(ctx.from_user["id"]))
    if user is None:
        await ctx.client.send_message(
            ctx.chat_id,
            "I don't recognise you yet — send /start to register.",
        )
        return

    service = PaymentService(ctx.session, client=ctx.client)
    try:
        invoice = await service.create_invoice(
            user_id=user.id,
            package_code=package_code,
        )
    except PackageNotFoundError:
        await ctx.client.send_message(
            ctx.chat_id,
            "That package is no longer available. Tap /buy to see the latest catalog.",
        )
        return
    except TelegramApiError as exc:
        logger.warning(
            "payment.invoice_link_failed",
            user_id=user.id,
            package=package_code,
            error=str(exc),
        )
        await ctx.client.send_message(
            ctx.chat_id,
            "Couldn't create an invoice right now — please try again in a moment.",
        )
        return

    keyboard: dict[str, Any] = {
        "inline_keyboard": [
            [{"text": f"Pay {invoice.stars_amount} ⭐", "url": invoice.telegram_invoice_link}],
        ],
    }
    sub_line = (
        "\n♻️ Renews automatically every 30 days. Cancel anytime."
        if invoice.is_subscription
        else ""
    )
    await ctx.client.send_message(
        ctx.chat_id,
        (
            f"🧾 <b>{invoice.package_code.title()}</b> — "
            f"{invoice.stars_amount} ⭐ for {invoice.tokens_amount} tokens.{sub_line}"
            "\n\nTap the button below to complete the payment."
        ),
        reply_markup=keyboard,
    )


def _parse_image_args(text: str | None) -> str | None:
    """Extract the prompt that follows ``/image`` in the command text."""
    if not text:
        return None
    parts = text.strip().split(maxsplit=1)
    if len(parts) < 2:
        return None
    return parts[1].strip() or None


async def handle_image(ctx: HandlerContext) -> None:
    """Generate an image from a free-form prompt: ``/image <prompt>``."""
    if ctx.chat_id is None or ctx.from_user is None:
        return

    prompt = _parse_image_args((ctx.message or {}).get("text"))
    if not prompt:
        await ctx.client.send_message(
            ctx.chat_id,
            (
                "🎨 <b>Image generation</b>\n"
                "Usage: <code>/image &lt;prompt&gt;</code>\n\n"
                f"Cost: <b>{QUALITY_COST[QUALITY_STANDARD]}</b> tokens "
                "per standard image."
            ),
        )
        return

    user = await find_user_by_telegram_id(ctx.session, int(ctx.from_user["id"]))
    if user is None:
        await ctx.client.send_message(
            ctx.chat_id,
            "I don't recognise you yet — send /start to register.",
        )
        return

    if ctx.composio is None:
        logger.error("bot.image.composio_unconfigured", user_id=user.id)
        await ctx.client.send_message(
            ctx.chat_id,
            "Image generation is temporarily unavailable. Please try again later.",
        )
        return

    service = ImageGenerationService(ctx.session, ctx.composio)
    try:
        outcome = await service.generate(
            user_id=user.id,
            prompt=prompt,
            quality=QUALITY_STANDARD,
        )
    except InvalidPromptError as exc:
        await ctx.client.send_message(
            ctx.chat_id,
            f"❌ {exc}",
        )
        return
    except InsufficientTokensError as exc:
        await ctx.client.send_message(
            ctx.chat_id,
            (
                "💸 Not enough tokens. "
                f"Need <b>{exc.required}</b>, you have <b>{exc.available}</b>.\n"
                "Tap /buy to top up."
            ),
        )
        return
    except UserNotFoundError:
        await ctx.client.send_message(
            ctx.chat_id,
            "I don't recognise you yet — send /start to register.",
        )
        return
    except ImageProviderError as exc:
        await ctx.session.rollback()
        logger.warning(
            "bot.image.provider_error",
            user_id=user.id,
            error=str(exc),
            provider_error=exc.provider_error,
        )
        await ctx.client.send_message(
            ctx.chat_id,
            "🛠 The image service is having trouble right now — please try again in a moment.",
        )
        return

    caption = (
        f"🎨 Generated for <i>{prompt[:160]}</i>\n"
        f"Cost: <b>{outcome.tokens_spent}</b> tokens · "
        f"Balance: <b>{outcome.new_balance}</b>"
    )
    try:
        await ctx.client.send_photo(
            ctx.chat_id,
            outcome.result_url,
            caption=caption,
        )
    except TelegramApiError as exc:
        # Telegram couldn't fetch the URL — fall back to a plain link.
        logger.warning(
            "bot.image.send_photo_failed",
            user_id=user.id,
            error=str(exc),
        )
        await ctx.client.send_message(
            ctx.chat_id,
            f"{caption}\n\n🔗 {outcome.result_url}",
        )


def _parse_video_args(text: str | None) -> tuple[str | None, str | None]:
    """Parse the ``/video [tariff] <prompt>`` argument string.

    The optional first token, when one of the catalog tariffs or a
    matching ``5s`` / ``15s`` / ``60s`` shorthand, is treated as the
    tariff selector; the remainder is the prompt.  When no tariff is
    given, the prompt is the full argument string and the caller falls
    back to the default tariff.
    """
    if not text:
        return None, None
    parts = text.strip().split(maxsplit=1)
    if len(parts) < 2:
        return None, None
    args = parts[1].strip()
    if not args:
        return None, None
    first, _, rest = args.partition(" ")
    first_norm = first.strip().lower()
    if first_norm in SUPPORTED_TARIFFS:
        return first_norm, rest.strip() or None
    if first_norm in ("5s", "15s", "60s"):
        mapping = {"5s": "short_5s", "15s": "medium_15s", "60s": "long_60s"}
        return mapping[first_norm], rest.strip() or None
    return None, args


def _format_video_tariff_help() -> str:
    lines = ["🎬 <b>Video generation</b>", ""]
    lines.append("Usage:")
    lines.append("• <code>/video &lt;prompt&gt;</code> — short clip (default)")
    lines.append("• <code>/video &lt;tariff&gt; &lt;prompt&gt;</code> — pick a tariff")
    lines.append("")
    lines.append("<b>Tariffs</b>")
    for tariff in ("short_5s", "medium_15s", "long_60s"):
        duration = TARIFF_DURATION[tariff]
        cost = TARIFF_COST[tariff]
        lines.append(
            f"• <code>{tariff}</code> — {duration}s — <b>{cost}</b> tokens"
        )
    return "\n".join(lines)


def _format_video_progress(view: VideoJobView, prompt: str) -> str:
    status_label = {
        "pending": "⏳ Queued",
        "queued": "⏳ Queued",
        "in_progress": "🎬 Rendering",
        "succeeded": "✅ Ready",
        "failed": "❌ Failed",
        "refunded": "↩️ Refunded",
    }.get(view.status, view.status)
    short_prompt = (prompt[:160] + "…") if len(prompt) > 160 else prompt
    return (
        f"{status_label} — <b>{view.tariff}</b> ({view.duration_s}s)\n"
        f"Prompt: <i>{short_prompt}</i>\n"
        f"Cost: <b>{view.tokens_cost}</b> tokens · "
        f"Job: <code>#{view.id}</code>"
    )


async def handle_video(ctx: HandlerContext) -> None:
    """Submit a video-generation job: ``/video [tariff] <prompt>``.

    The handler returns immediately after submission so the user sees a
    "queued" message right away; the polling worker drives the job to
    completion in the background.  Status updates are not pushed from
    this handler — use ``GET /api/v1/generate/video/{job_id}`` from the
    Mini App, or ``/video`` again to start another job.
    """
    if ctx.chat_id is None or ctx.from_user is None:
        return

    tariff, prompt = _parse_video_args((ctx.message or {}).get("text"))
    if not prompt:
        await ctx.client.send_message(ctx.chat_id, _format_video_tariff_help())
        return

    user = await find_user_by_telegram_id(ctx.session, int(ctx.from_user["id"]))
    if user is None:
        await ctx.client.send_message(
            ctx.chat_id,
            "I don't recognise you yet — send /start to register.",
        )
        return

    if ctx.composio is None:
        logger.error("bot.video.composio_unconfigured", user_id=user.id)
        await ctx.client.send_message(
            ctx.chat_id,
            "Video generation is temporarily unavailable. Please try again later.",
        )
        return

    service = VideoGenerationService(ctx.session, ctx.composio)
    request_id = uuid.uuid4().hex
    try:
        view = await service.create(
            user_id=user.id,
            prompt=prompt,
            tariff=tariff or TARIFF_SHORT,
            request_id=request_id,
        )
    except VideoInvalidPromptError as exc:
        await ctx.client.send_message(ctx.chat_id, f"❌ {exc}")
        return
    except InvalidTariffError as exc:
        await ctx.client.send_message(
            ctx.chat_id,
            f"❌ {exc}\n\n{_format_video_tariff_help()}",
        )
        return
    except InvalidReferenceImageError as exc:
        await ctx.client.send_message(ctx.chat_id, f"❌ {exc}")
        return
    except InsufficientTokensError as exc:
        await ctx.client.send_message(
            ctx.chat_id,
            (
                "💸 Not enough tokens. "
                f"Need <b>{exc.required}</b>, you have <b>{exc.available}</b>.\n"
                "Tap /buy to top up."
            ),
        )
        return
    except UserNotFoundError:
        await ctx.client.send_message(
            ctx.chat_id,
            "I don't recognise you yet — send /start to register.",
        )
        return
    except VideoProviderError as exc:
        logger.warning(
            "bot.video.provider_error",
            user_id=user.id,
            error=str(exc),
            provider_error=exc.provider_error,
        )
        await ctx.client.send_message(
            ctx.chat_id,
            "🛠 The video service is having trouble right now — please try again in a moment.",
        )
        return

    text = _format_video_progress(view, prompt)
    if view.status == "succeeded" and view.result_url:
        # Provider returned a URL on the submit call — happy path for
        # toolkits that render synchronously even though the API is async.
        try:
            await ctx.client.send_video(
                ctx.chat_id,
                view.result_url,
                caption=text,
                duration=view.duration_s,
            )
        except TelegramApiError as exc:
            logger.warning(
                "bot.video.send_video_failed",
                user_id=user.id,
                job_id=view.id,
                error=str(exc),
            )
            await ctx.client.send_message(
                ctx.chat_id,
                f"{text}\n\n🔗 {view.result_url}",
            )
        return
    if view.status in ("failed", "refunded"):
        # The service refunded already; tell the user what happened.
        reason = view.error_message or "video generation failed"
        await ctx.client.send_message(
            ctx.chat_id,
            (
                f"❌ {reason}\n"
                f"Refunded <b>{view.tokens_cost}</b> tokens — your balance is safe."
            ),
        )
        return

    await ctx.client.send_message(
        ctx.chat_id,
        text + "\n\nI'll keep working on it — check back in a moment.",
    )


async def handle_profile(ctx: HandlerContext) -> None:
    if ctx.chat_id is None or ctx.from_user is None:
        return
    user = await find_user_by_telegram_id(ctx.session, int(ctx.from_user["id"]))
    if user is None:
        await ctx.client.send_message(
            ctx.chat_id,
            "I don't recognise you yet — send /start to register.",
        )
        return
    username_line = f"@{user.username}" if user.username else "—"
    text = (
        "👤 <b>Your profile</b>\n"
        f"Name: {user.first_name or '—'}\n"
        f"Username: {username_line}\n"
        f"Language: {user.language_code or '—'}\n"
        f"Balance: <b>{user.token_balance}</b> tokens\n"
        f"Total spent: {user.total_tokens_spent}\n"
        f"Total requests: {user.total_requests}\n"
        f"Referral code: <code>{user.referral_code}</code>"
    )
    await ctx.client.send_message(ctx.chat_id, text)


async def handle_referral(ctx: HandlerContext) -> None:
    if ctx.chat_id is None or ctx.from_user is None:
        return
    user = await find_user_by_telegram_id(ctx.session, int(ctx.from_user["id"]))
    if user is None:
        await ctx.client.send_message(
            ctx.chat_id,
            "I don't recognise you yet — send /start to register.",
        )
        return
    link = _build_referral_link(ctx.settings.telegram_bot_username, user.referral_code)
    text = (
        "🔗 <b>Invite friends</b>\n"
        f"Share this link to earn bonus tokens when friends sign up:\n\n"
        f"<code>{link}</code>"
    )
    await ctx.client.send_message(
        ctx.chat_id,
        text,
        reply_markup=referral_share(link),
    )


# ----------------------------------------------------------------- callbacks


_CALLBACK_TO_COMMAND = {
    "menu:balance": handle_balance,
    "menu:buy": handle_buy,
    "menu:profile": handle_profile,
    "menu:referral": handle_referral,
    "menu:chat": None,  # handled inline
}


async def handle_callback_query(ctx: HandlerContext) -> None:
    if ctx.callback_query is None:
        return
    data = (ctx.callback_query.get("data") or "").strip()
    try:
        await ctx.client.answer_callback_query(ctx.callback_query["id"])
    except Exception as exc:  # noqa: BLE001 — ack failures are non-fatal
        logger.warning("bot.callback.ack_failed", error=str(exc))

    if data == "menu:chat":
        if ctx.chat_id is not None:
            await ctx.client.send_message(
                ctx.chat_id,
                "💬 Just type your question — AI chat lands in Phase 2.",
            )
        return

    if data.startswith("buy:"):
        await handle_buy_package(ctx, package_code=data.split(":", 1)[1])
        return

    handler = _CALLBACK_TO_COMMAND.get(data)
    if handler is None:
        logger.info("bot.callback.unknown", data=data)
        return
    await handler(ctx)


# ----------------------------------------------------------------- payments


async def handle_pre_checkout_query(ctx: HandlerContext) -> None:
    """Confirm or reject a Telegram ``pre_checkout_query``.

    Telegram requires the answer within 10 seconds, so we keep the work
    light: validate the payload against the package catalog, look up the
    pending invoice, and reply.  Any unexpected error answers ``ok=False``
    so the user isn't charged.
    """
    query = ctx.update.get("pre_checkout_query") or {}
    query_id = query.get("id")
    if not query_id:
        return

    service = PaymentService(ctx.session, client=ctx.client)
    try:
        await service.confirm_pre_checkout(
            payload=str(query.get("invoice_payload") or ""),
            total_amount=int(query.get("total_amount") or 0),
            currency=str(query.get("currency") or ""),
        )
    except (
        PackageNotFoundError,
        InvoiceNotFoundError,
        InvoicePayloadInvalidError,
    ) as exc:
        logger.warning(
            "payment.pre_checkout.rejected",
            query_id=query_id,
            error=str(exc),
        )
        try:
            await ctx.client.answer_pre_checkout_query(
                query_id,
                ok=False,
                error_message=(
                    "We couldn't verify this invoice. Please open /buy "
                    "and try again."
                ),
            )
        except TelegramApiError as send_exc:
            logger.warning(
                "payment.pre_checkout.ack_failed", error=str(send_exc)
            )
        return
    except Exception as exc:  # noqa: BLE001 — never let pre_checkout charge a user on error
        logger.exception("payment.pre_checkout.unhandled", error=str(exc))
        try:
            await ctx.client.answer_pre_checkout_query(
                query_id,
                ok=False,
                error_message="Internal error — please try again.",
            )
        except TelegramApiError as send_exc:
            logger.warning(
                "payment.pre_checkout.ack_failed", error=str(send_exc)
            )
        return

    try:
        await ctx.client.answer_pre_checkout_query(query_id, ok=True)
    except TelegramApiError as exc:
        logger.warning("payment.pre_checkout.ack_failed", error=str(exc))


async def handle_successful_payment(ctx: HandlerContext) -> None:
    """Credit tokens after Telegram confirms a Stars payment."""
    if ctx.message is None:
        return
    payment = ctx.message.get("successful_payment")
    if not isinstance(payment, dict):
        return
    from_user = ctx.message.get("from") or {}
    telegram_user_id = int(from_user.get("id") or 0)

    service = PaymentService(ctx.session, client=ctx.client)
    try:
        result = await service.finalize_successful_payment(
            telegram_user_id=telegram_user_id,
            payload=str(payment.get("invoice_payload") or ""),
            total_amount=int(payment.get("total_amount") or 0),
            currency=str(payment.get("currency") or ""),
            telegram_payment_charge_id=str(
                payment.get("telegram_payment_charge_id") or ""
            ),
            provider_payment_charge_id=payment.get(
                "provider_payment_charge_id"
            ),
            is_recurring=bool(payment.get("is_recurring") or False),
        )
    except (PackageNotFoundError, InvoicePayloadInvalidError) as exc:
        logger.error(
            "payment.success.invalid_payload",
            telegram_user_id=telegram_user_id,
            error=str(exc),
        )
        if ctx.chat_id is not None:
            await ctx.client.send_message(
                ctx.chat_id,
                "Payment received but I couldn't match it to a package — "
                "please contact support.",
            )
        return

    if ctx.chat_id is None:
        return
    if result.already_processed:
        # Telegram retried — stay silent so we don't spam the user.
        return

    suffix = (
        f"\n\n♻️ Premium active until <b>{result.expires_at:%Y-%m-%d}</b>."
        if result.is_subscription and result.expires_at is not None
        else ""
    )
    await ctx.client.send_message(
        ctx.chat_id,
        (
            f"✅ Payment received! "
            f"Credited <b>{result.tokens_credited}</b> tokens. "
            f"Balance: <b>{result.new_balance}</b>." + suffix
        ),
    )


# ----------------------------------------------------------------- registry

COMMAND_HANDLERS = {
    "start": handle_start,
    "help": handle_help,
    "balance": handle_balance,
    "buy": handle_buy,
    "image": handle_image,
    "video": handle_video,
    "profile": handle_profile,
    "referral": handle_referral,
}
