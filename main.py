
import asyncio, os, time, html
from datetime import datetime,timedelta,timezone

from dotenv import load_dotenv
from aiogram import Bot,Dispatcher,F
from aiogram.enums import ChatMemberStatus,ParseMode
from aiogram.filters import Command,CommandStart
from aiogram.types import Message,ChatPermissions,BotCommand
from aiogram.exceptions import TelegramBadRequest

from db import Database
from smart import analyze_text, analyze_behavior, fingerprint

load_dotenv()

TOKEN=os.getenv("BOT_TOKEN","").strip()
OWNER_ID=int(os.getenv("OWNER_ID","0") or 0)
DB_PATH=os.getenv("DB_PATH","moderator.db")
BOT_NICKNAMES={x.strip().lower() for x in os.getenv("BOT_NICKNAMES","сглыпа,sglypa,сглып").split(",") if x.strip()}
PAVLOVA_NAMES={x.strip().lower() for x in os.getenv("PAVLOVA_NAMES","павлова,pavlova,@pav.p3").split(",") if x.strip()}

db=Database(DB_PATH)
dp=Dispatcher()
BOT_ID=0

RULE_NAMES={
 "RESPECT":"Уважительное общение",
 "SPAM":"Спам / флуд",
 "AD":"Реклама",
 "PAVLOVA":"Правило про Павлову",
 "MANUAL":"Ручное наказание"
}

async def is_admin(bot,chat_id,user_id):
    if user_id==OWNER_ID:
        return True
    try:
        m=await bot.get_chat_member(chat_id,user_id)
        return m.status in {ChatMemberStatus.ADMINISTRATOR,ChatMemberStatus.CREATOR}
    except:
        return False

async def mute(bot,chat_id,user_id,minutes):
    await bot.restrict_chat_member(
        chat_id,user_id,
        permissions=ChatPermissions(can_send_messages=False),
        until_date=datetime.now(timezone.utc)+timedelta(minutes=minutes)
    )

def ladder(rule,previous,severity):
    n=previous+1
    if rule=="PAVLOVA":
        if n==1:return ("mute",720,"мут 12 часов")
        if n==2:return ("mute",4320,"мут 3 суток")
        return ("ban",0,"бан")
    if rule=="SPAM":
        if n==1:return ("warn",0,"варн")
        if n==2:return ("mute",60,"мут 1 час")
        if n==3:return ("mute",1440,"мут 24 часа")
        return ("kick",0,"кик")
    if rule=="AD":
        if n==1:return ("warn",0,"варн")
        if n==2:return ("mute",1440,"мут 24 часа")
        return ("ban",0,"бан")
    # respect
    if n==1:return ("warn",0,"варн")
    if n==2:return ("mute",360,"мут 6 часов")
    if n==3:return ("mute",1440,"мут 24 часа")
    return ("ban",0,"бан")

async def punish(message,d):
    u=message.from_user
    if await is_admin(message.bot,message.chat.id,u.id):
        return

    previous=await db.count_violations(message.chat.id,u.id,d.rule_code,30)
    await db.add_violation(
        message.chat.id,u.id,d.rule_code,d.severity,d.reason,
        message.text or message.caption or "",message.message_id
    )
    action,minutes,label=ladder(d.rule_code,previous,d.severity)

    try:
        await message.delete()
    except:
        pass

    try:
        if action=="mute":
            await mute(message.bot,message.chat.id,u.id,minutes)
        elif action=="kick":
            await message.bot.ban_chat_member(message.chat.id,u.id)
            await message.bot.unban_chat_member(message.chat.id,u.id)
        elif action=="ban":
            await message.bot.ban_chat_member(message.chat.id,u.id)
    except TelegramBadRequest:
        await message.answer("⚠️ Нарушение найдено, но не хватает прав админа.")

    await db.add_punishment(message.chat.id,u.id,action,minutes,d.rule_code)

    await message.answer(
        f"⚠️ <b>{html.escape(u.full_name)}</b>\n"
        f"Правило: <b>{html.escape(RULE_NAMES.get(d.rule_code,d.rule_code))}</b>\n"
        f"Причина: {html.escape(d.reason)}\n"
        f"Smart-score: <b>{d.score}/100</b>\n"
        f"Нарушение по этому правилу за 30 дней: <b>#{previous+1}</b>\n"
        f"Наказание: <b>{label}</b>",
        parse_mode=ParseMode.HTML
    )

@dp.message(CommandStart())
async def start(m:Message):
    await m.answer(
        "🤖 Умный модератор готов.\n\n"
        "В группе:\n"
        "/activate — начать учёт с текущего момента\n"
        "/top — топ чата\n"
        "/stats — статистика\n"
        "/history — история нарушений"
    )

@dp.message(Command("activate"))
async def activate_cmd(m:Message):
    if m.chat.type=="private":
        return
    if not await is_admin(m.bot,m.chat.id,m.from_user.id):
        return await m.answer("Только админ может активировать.")
    await db.activate_chat(m.chat.id,m.chat.title or "")
    await m.answer("✅ База активирована с этого момента. Старые сообщения не учитываются.")

@dp.message(Command("top"))
async def top_cmd(m:Message):
    rows=await db.top_chat(m.chat.id,10)
    if not rows:
        return await m.answer("Пока нет статистики.")
    lines=["🏆 <b>Топ чата</b>"]
    for i,(uid,username,name,count,rep) in enumerate(rows,1):
        who=f"@{html.escape(username)}" if username else html.escape(name or str(uid))
        lines.append(f"{i}. {who} — <b>{count}</b> сообщ. • репутация {rep}")
    await m.answer("\n".join(lines),parse_mode=ParseMode.HTML)

@dp.message(Command("stats"))
async def stats_cmd(m:Message):
    target=m.from_user
    if m.reply_to_message and m.reply_to_message.from_user and await is_admin(m.bot,m.chat.id,m.from_user.id):
        target=m.reply_to_message.from_user

    (messages,reputation),rules,punishments=await db.user_stats(m.chat.id,target.id)
    lines=[
        f"📊 <b>{html.escape(target.full_name)}</b>",
        f"Сообщений: <b>{messages}</b>",
        f"Репутация: <b>{reputation}/100</b>"
    ]
    if rules:
        lines.append("\nНарушения:")
        for rule,count in rules:
            lines.append(f"• {html.escape(RULE_NAMES.get(rule,rule))}: {count}")
    await m.answer("\n".join(lines),parse_mode=ParseMode.HTML)

@dp.message(Command("history"))
async def history_cmd(m:Message):
    target=m.from_user
    if m.reply_to_message and m.reply_to_message.from_user and await is_admin(m.bot,m.chat.id,m.from_user.id):
        target=m.reply_to_message.from_user

    rows=await db.history(m.chat.id,target.id,10)
    if not rows:
        return await m.answer("История нарушений пустая.")
    lines=[f"🧾 <b>История: {html.escape(target.full_name)}</b>"]
    for rule,reason,ts in rows:
        dt=datetime.fromtimestamp(ts).strftime("%d.%m %H:%M")
        lines.append(f"• {dt} — {html.escape(RULE_NAMES.get(rule,rule))}: {html.escape(reason)}")
    await m.answer("\n".join(lines),parse_mode=ParseMode.HTML)

@dp.message(Command("clearwarns"))
async def clearwarns_cmd(m:Message):
    if not await is_admin(m.bot,m.chat.id,m.from_user.id):
        return
    if not m.reply_to_message or not m.reply_to_message.from_user:
        return await m.answer("Ответь /clearwarns на сообщение пользователя.")
    u=m.reply_to_message.from_user
    await db.clear_user_violations(m.chat.id,u.id)
    await m.answer(f"✅ История нарушений {html.escape(u.full_name)} очищена.",parse_mode=ParseMode.HTML)

@dp.message(Command("warn"))
async def warn_cmd(m:Message):
    if not await is_admin(m.bot,m.chat.id,m.from_user.id):
        return
    if not m.reply_to_message or not m.reply_to_message.from_user:
        return await m.answer("Ответь /warn на сообщение пользователя.")
    u=m.reply_to_message.from_user
    await db.add_violation(m.chat.id,u.id,"MANUAL",1,"Ручной варн","",m.reply_to_message.message_id)
    await m.answer(f"⚠️ {html.escape(u.full_name)} получил ручной варн.",parse_mode=ParseMode.HTML)

@dp.message(Command("mute"))
async def mute_cmd(m:Message):
    if not await is_admin(m.bot,m.chat.id,m.from_user.id):
        return
    if not m.reply_to_message or not m.reply_to_message.from_user:
        return await m.answer("Ответь /mute 60 на сообщение пользователя.")
    parts=(m.text or "").split()
    minutes=60
    if len(parts)>1 and parts[1].isdigit():
        minutes=max(1,min(int(parts[1]),10080))
    u=m.reply_to_message.from_user
    await mute(m.bot,m.chat.id,u.id,minutes)
    await db.add_punishment(m.chat.id,u.id,"mute",minutes,"MANUAL")
    await m.answer(f"🔇 {html.escape(u.full_name)} — мут {minutes} мин.",parse_mode=ParseMode.HTML)

@dp.message(Command("ban"))
async def ban_cmd(m:Message):
    if not await is_admin(m.bot,m.chat.id,m.from_user.id):
        return
    if not m.reply_to_message or not m.reply_to_message.from_user:
        return await m.answer("Ответь /ban на сообщение пользователя.")
    u=m.reply_to_message.from_user
    await m.bot.ban_chat_member(m.chat.id,u.id)
    await db.add_punishment(m.chat.id,u.id,"ban",0,"MANUAL")
    await m.answer(f"⛔ {html.escape(u.full_name)} забанен.",parse_mode=ParseMode.HTML)

@dp.message(F.chat.type.in_({"group","supergroup"}))
async def moderate(m:Message):
    global BOT_ID
    if not m.from_user or m.from_user.is_bot:
        return

    activated=await db.ensure_chat(m.chat.id,m.chat.title or "")
    if int(m.date.timestamp()) < activated:
        return

    text=m.text or m.caption or ""

    if text and not text.startswith("/"):
        await db.bump_user(m.chat.id,m.from_user)

    if not text:
        return

    # Analyze message content before writing it into recent_messages.
    reply_to_bot=bool(
        m.reply_to_message and m.reply_to_message.from_user
        and m.reply_to_message.from_user.id==BOT_ID
    )
    content_detection=analyze_text(
        text,BOT_NICKNAMES,PAVLOVA_NAMES,reply_to_bot=reply_to_bot
    )

    behavior_detection=await analyze_behavior(db,m.chat.id,m.from_user.id,text)

    fp=fingerprint(text)
    await db.add_recent_message(m.chat.id,m.from_user.id,fp,text)

    # One message = one punishment, choose the stronger signal.
    candidates=[x for x in (content_detection,behavior_detection) if x]
    if not candidates:
        return
    d=sorted(candidates,key=lambda x:(x.severity,x.score),reverse=True)[0]
    await punish(m,d)

async def main():
    global BOT_ID
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN не заполнен в .env")

    await db.init()
    bot=Bot(TOKEN)
    me=await bot.get_me()
    BOT_ID=me.id

    await bot.set_my_commands([
        BotCommand(command="activate",description="Начать учёт сейчас"),
        BotCommand(command="top",description="Топ чата"),
        BotCommand(command="stats",description="Статистика"),
        BotCommand(command="history",description="История нарушений")
    ])

    print(f"Smart moderator started: @{me.username}")
    await dp.start_polling(bot)

if __name__=="__main__":
    asyncio.run(main())
