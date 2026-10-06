import os
import html
import hashlib
from datetime import datetime, timedelta, timezone

from aiohttp import web
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatMemberStatus, ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, ChatPermissions, BotCommand
from aiogram.exceptions import TelegramBadRequest
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from db import Database
from smart import analyze_text, analyze_behavior, fingerprint

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN", "").strip()
OWNER_ID = int(os.getenv("OWNER_ID", "0") or 0)
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

BOT_NICKNAMES = {
    x.strip().lower()
    for x in os.getenv("BOT_NICKNAMES", "сглыпа,sglypa,сглып").split(",")
    if x.strip()
}
PAVLOVA_NAMES = {
    x.strip().lower()
    for x in os.getenv("PAVLOVA_NAMES", "павлова,pavlova,@pav.p3").split(",")
    if x.strip()
}

WEBHOOK_PATH = "/telegram/webhook"
BASE_URL = (
    os.getenv("WEBHOOK_BASE_URL", "").strip()
    or os.getenv("RENDER_EXTERNAL_URL", "").strip()
).rstrip("/")

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
if not WEBHOOK_SECRET and TOKEN:
    WEBHOOK_SECRET = hashlib.sha256((TOKEN + ":brv-webhook").encode()).hexdigest()[:32]

PORT = int(os.getenv("PORT", "10000"))

db = Database(DATABASE_URL)
dp = Dispatcher()
bot = Bot(TOKEN) if TOKEN else None
BOT_ID = 0

RULE_NAMES = {
    "RESPECT": "Уважительное общение",
    "SPAM": "Спам / флуд",
    "AD": "Реклама",
    "PAVLOVA": "Правило про Павлову",
    "MANUAL": "Ручное наказание",
}


async def is_admin(bot: Bot, chat_id: int, user_id: int):
    if user_id == OWNER_ID:
        return True
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in {
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.CREATOR,
        }
    except Exception:
        return False


async def mute(bot: Bot, chat_id: int, user_id: int, minutes: int):
    await bot.restrict_chat_member(
        chat_id,
        user_id,
        permissions=ChatPermissions(can_send_messages=False),
        until_date=datetime.now(timezone.utc) + timedelta(minutes=minutes),
    )


def ladder(rule: str, previous: int, severity: int):
    n = previous + 1

    if rule == "PAVLOVA":
        if n == 1:
            return "mute", 720, "мут 12 часов"
        if n == 2:
            return "mute", 4320, "мут 3 суток"
        return "ban", 0, "бан"

    if rule == "SPAM":
        if n == 1:
            return "warn", 0, "варн"
        if n == 2:
            return "mute", 60, "мут 1 час"
        if n == 3:
            return "mute", 1440, "мут 24 часа"
        return "kick", 0, "кик"

    if rule == "AD":
        if n == 1:
            return "warn", 0, "варн"
        if n == 2:
            return "mute", 1440, "мут 24 часа"
        return "ban", 0, "бан"

    if n == 1:
        return "warn", 0, "варн"
    if n == 2:
        return "mute", 360, "мут 6 часов"
    if n == 3:
        return "mute", 1440, "мут 24 часа"
    return "ban", 0, "бан"


async def punish(message: Message, detection):
    user = message.from_user
    if await is_admin(message.bot, message.chat.id, user.id):
        return

    previous = await db.count_violations(
        message.chat.id, user.id, detection.rule_code, 30
    )

    await db.add_violation(
        message.chat.id,
        user.id,
        detection.rule_code,
        detection.severity,
        detection.reason,
        message.text or message.caption or "",
        message.message_id,
    )

    action, minutes, label = ladder(
        detection.rule_code, previous, detection.severity
    )

    try:
        await message.delete()
    except Exception:
        pass

    try:
        if action == "mute":
            await mute(message.bot, message.chat.id, user.id, minutes)
        elif action == "kick":
            await message.bot.ban_chat_member(message.chat.id, user.id)
            await message.bot.unban_chat_member(message.chat.id, user.id)
        elif action == "ban":
            await message.bot.ban_chat_member(message.chat.id, user.id)
    except TelegramBadRequest:
        await message.answer(
            "⚠️ Нарушение найдено, но мне не хватает админ-прав для наказания."
        )

    await db.add_punishment(
        message.chat.id, user.id, action, minutes, detection.rule_code
    )

    await message.answer(
        f"⚠️ <b>{html.escape(user.full_name)}</b>\n"
        f"Правило: <b>{html.escape(RULE_NAMES.get(detection.rule_code, detection.rule_code))}</b>\n"
        f"Причина: {html.escape(detection.reason)}\n"
        f"Smart-score: <b>{detection.score}/100</b>\n"
        f"Нарушение по этому правилу за 30 дней: <b>#{previous + 1}</b>\n"
        f"Наказание: <b>{label}</b>",
        parse_mode=ParseMode.HTML,
    )


@dp.message(CommandStart())
async def start_cmd(message: Message):
    await message.answer(
        "🤖 Умный модератор готов.\n\n"
        "В группе:\n"
        "/activate — начать учёт с текущего момента\n"
        "/top — топ чата\n"
        "/stats — статистика\n"
        "/history — история нарушений"
    )


@dp.message(Command("activate"))
async def activate_cmd(message: Message):
    if message.chat.type == "private":
        return
    if not await is_admin(
        message.bot, message.chat.id, message.from_user.id
    ):
        return await message.answer("Только админ может активировать.")

    await db.activate_chat(message.chat.id, message.chat.title or "")
    await message.answer(
        "✅ База активирована с этого момента. Старые сообщения не учитываются."
    )


@dp.message(Command("top"))
async def top_cmd(message: Message):
    rows = await db.top_chat(message.chat.id, 10)
    if not rows:
        return await message.answer("Пока нет статистики.")

    lines = ["🏆 <b>Топ чата</b>"]
    for i, row in enumerate(rows, 1):
        username = row["username"]
        name = row["display_name"]
        count = row["messages"]
        rep = row["reputation"]
        who = f"@{html.escape(username)}" if username else html.escape(name)
        lines.append(f"{i}. {who} — <b>{count}</b> сообщ. • репутация {rep}")

    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)


@dp.message(Command("stats"))
async def stats_cmd(message: Message):
    target = message.from_user

    if (
        message.reply_to_message
        and message.reply_to_message.from_user
        and await is_admin(
            message.bot, message.chat.id, message.from_user.id
        )
    ):
        target = message.reply_to_message.from_user

    user_row, rules, punishments = await db.user_stats(
        message.chat.id, target.id
    )

    messages = int(user_row["messages"]) if user_row else 0
    reputation = int(user_row["reputation"]) if user_row else 100

    lines = [
        f"📊 <b>{html.escape(target.full_name)}</b>",
        f"Сообщений: <b>{messages}</b>",
        f"Репутация: <b>{reputation}/100</b>",
    ]

    if rules:
        lines.append("\nНарушения:")
        for row in rules:
            rule = row["rule_code"]
            count = row["count"]
            lines.append(
                f"• {html.escape(RULE_NAMES.get(rule, rule))}: {count}"
            )

    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)


@dp.message(Command("history"))
async def history_cmd(message: Message):
    target = message.from_user

    if (
        message.reply_to_message
        and message.reply_to_message.from_user
        and await is_admin(
            message.bot, message.chat.id, message.from_user.id
        )
    ):
        target = message.reply_to_message.from_user

    rows = await db.history(message.chat.id, target.id, 10)
    if not rows:
        return await message.answer("История нарушений пустая.")

    lines = [f"🧾 <b>История: {html.escape(target.full_name)}</b>"]
    for row in rows:
        dt = datetime.fromtimestamp(row["created_at"]).strftime("%d.%m %H:%M")
        rule = row["rule_code"]
        reason = row["reason"] or ""
        lines.append(
            f"• {dt} — {html.escape(RULE_NAMES.get(rule, rule))}: "
            f"{html.escape(reason)}"
        )

    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)


@dp.message(Command("clearwarns"))
async def clearwarns_cmd(message: Message):
    if not await is_admin(
        message.bot, message.chat.id, message.from_user.id
    ):
        return
    if not message.reply_to_message or not message.reply_to_message.from_user:
        return await message.answer(
            "Ответь командой /clearwarns на сообщение пользователя."
        )

    user = message.reply_to_message.from_user
    await db.clear_user_violations(message.chat.id, user.id)
    await message.answer(
        f"✅ История нарушений {html.escape(user.full_name)} очищена.",
        parse_mode=ParseMode.HTML,
    )


@dp.message(Command("warn"))
async def warn_cmd(message: Message):
    if not await is_admin(
        message.bot, message.chat.id, message.from_user.id
    ):
        return
    if not message.reply_to_message or not message.reply_to_message.from_user:
        return await message.answer("Ответь /warn на сообщение пользователя.")

    user = message.reply_to_message.from_user
    await db.add_violation(
        message.chat.id,
        user.id,
        "MANUAL",
        1,
        "Ручной варн",
        message.reply_to_message.text or "",
        message.reply_to_message.message_id,
    )
    await message.answer(
        f"⚠️ {html.escape(user.full_name)} получил ручной варн.",
        parse_mode=ParseMode.HTML,
    )


@dp.message(Command("mute"))
async def mute_cmd(message: Message):
    if not await is_admin(
        message.bot, message.chat.id, message.from_user.id
    ):
        return
    if not message.reply_to_message or not message.reply_to_message.from_user:
        return await message.answer(
            "Ответь /mute 60 на сообщение пользователя."
        )

    parts = (message.text or "").split()
    minutes = 60
    if len(parts) > 1 and parts[1].isdigit():
        minutes = max(1, min(int(parts[1]), 10080))

    user = message.reply_to_message.from_user
    await mute(message.bot, message.chat.id, user.id, minutes)
    await db.add_punishment(
        message.chat.id, user.id, "mute", minutes, "MANUAL"
    )
    await message.answer(
        f"🔇 {html.escape(user.full_name)} — мут {minutes} мин.",
        parse_mode=ParseMode.HTML,
    )


@dp.message(Command("ban"))
async def ban_cmd(message: Message):
    if not await is_admin(
        message.bot, message.chat.id, message.from_user.id
    ):
        return
    if not message.reply_to_message or not message.reply_to_message.from_user:
        return await message.answer("Ответь /ban на сообщение пользователя.")

    user = message.reply_to_message.from_user
    await message.bot.ban_chat_member(message.chat.id, user.id)
    await db.add_punishment(
        message.chat.id, user.id, "ban", 0, "MANUAL"
    )
    await message.answer(
        f"⛔ {html.escape(user.full_name)} забанен.",
        parse_mode=ParseMode.HTML,
    )


@dp.message(F.chat.type.in_({"group", "supergroup"}))
async def moderate(message: Message):
    global BOT_ID

    if not message.from_user or message.from_user.is_bot:
        return

    activated = await db.ensure_chat(
        message.chat.id, message.chat.title or ""
    )

    # Second safety gate: never count a message older than activation.
    if int(message.date.timestamp()) < activated:
        return

    text = message.text or message.caption or ""

    if text and not text.startswith("/"):
        await db.bump_user(message.chat.id, message.from_user)

    if not text:
        return

    reply_to_bot = bool(
        message.reply_to_message
        and message.reply_to_message.from_user
        and message.reply_to_message.from_user.id == BOT_ID
    )

    content_detection = analyze_text(
        text,
        BOT_NICKNAMES,
        PAVLOVA_NAMES,
        reply_to_bot=reply_to_bot,
    )

    behavior_detection = await analyze_behavior(
        db, message.chat.id, message.from_user.id, text
    )

    await db.add_recent_message(
        message.chat.id,
        message.from_user.id,
        fingerprint(text),
        text,
    )

    candidates = [
        x for x in (content_detection, behavior_detection) if x
    ]
    if not candidates:
        return

    detection = sorted(
        candidates,
        key=lambda x: (x.severity, x.score),
        reverse=True,
    )[0]

    await punish(message, detection)


async def health(_request):
    return web.json_response({
        "ok": True,
        "service": "BRV Sglypa Smart Moderator",
        "webhook_path": WEBHOOK_PATH,
    })


async def on_startup(app: web.Application):
    global BOT_ID

    if not TOKEN:
        raise RuntimeError("BOT_TOKEN is empty")
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is empty")
    if not BASE_URL:
        raise RuntimeError(
            "Webhook base URL is empty. Set WEBHOOK_BASE_URL to "
            "https://YOUR-SERVICE.onrender.com"
        )

    await db.init()

    me = await bot.get_me()
    BOT_ID = me.id

    await bot.set_my_commands([
        BotCommand(command="activate", description="Начать учёт сейчас"),
        BotCommand(command="top", description="Топ чата"),
        BotCommand(command="stats", description="Статистика"),
        BotCommand(command="history", description="История нарушений"),
    ])

    webhook_url = BASE_URL + WEBHOOK_PATH

    # Important: discard pending old Telegram updates at deploy time.
    await bot.set_webhook(
        url=webhook_url,
        secret_token=WEBHOOK_SECRET,
        drop_pending_updates=True,
        allowed_updates=dp.resolve_used_update_types(),
    )

    print(f"Bot @{me.username} ready")
    print(f"Webhook: {webhook_url}")


async def on_shutdown(app: web.Application):
    try:
        await bot.delete_webhook(drop_pending_updates=False)
    except Exception:
        pass
    await db.close()


def create_app():
    app = web.Application()

    app.router.add_get("/", health)
    app.router.add_get("/health", health)

    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=WEBHOOK_SECRET,
    ).register(app, path=WEBHOOK_PATH)

    setup_application(app, dp, bot=bot)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    return app


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN is empty")

    web.run_app(
        create_app(),
        host="0.0.0.0",
        port=PORT,
    )
