import sqlite3
import time
from random import uniform

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters
)

DB_PATH = "breast_bot.db"
COOLDOWN_SECONDS = 60 * 60  # 1 час

# 🔑 твой токен
TOKEN = "8383787249:AAENs2jqlQAIV8FdgIFWPXDw7CUkFSFKRZY"

# 👑 список админов (впиши реальные ID)
ADMINS = [123456789, 987654321]


def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            last_ts INTEGER DEFAULT 0,
            total_added REAL DEFAULT 0
        )
        """
    )
    con.commit()
    con.close()


def get_user(user_id: int):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT last_ts, total_added FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    if row is None:
        cur.execute(
            "INSERT INTO users (user_id, last_ts, total_added) VALUES (?, ?, ?)",
            (user_id, 0, 0.0),
        )
        con.commit()
        row = (0, 0.0)
    con.close()
    return row


def update_user(user_id: int, last_ts: int, total_added: float):
    # ограничение значений от 0 до 1000
    total_added = max(-10000, min(total_added, 10000))
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        "UPDATE users SET last_ts=?, total_added=? WHERE user_id=?",
        (last_ts, total_added, user_id),
    )
    con.commit()
    con.close()


def fmt_left(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    return (f"{m} мин {s} сек" if m and s else f"{m} мин" if m else f"{s} сек")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    last_ts, total_added = get_user(uid)
    now = int(time.time())
    elapsed = now - last_ts

    if elapsed < COOLDOWN_SECONDS:
        left = COOLDOWN_SECONDS - elapsed
        await update.message.reply_html(
            f"⏳ {user.mention_html()} ещё рановато! "
            f"Следующий прирост через <b>{fmt_left(left)}</b>."
        )
        return

    inc = round(uniform(1, 5), 2)
    total_added = round(total_added + inc, 2)
    update_user(uid, now, total_added)

    await update.message.reply_html(
        f"🎉 {user.mention_html()} получил(а) прирост <b>+{inc} см</b>!\n"
        f"📈 Суммарно: <b>{total_added} см</b>.\n"
        f"⛔️ Повторно — через 1 час."
    )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    last_ts, total_added = get_user(uid)
    now = int(time.time())
    left = max(0, COOLDOWN_SECONDS - (now - last_ts))
    tip = (f"Следующая попытка через {fmt_left(left)}."
           if left > 0 else "Можно получать прирост прямо сейчас командой /start.")
    await update.message.reply_html(
        f"📊 {user.mention_html()}, ваш суммарный прирост: <b>{total_added} см</b>.\n{tip}"
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    if uid not in ADMINS:
        await update.message.reply_text("🚫 Эта команда доступна только для админов.")
        return
    last_ts, total_added = get_user(uid)
    update_user(uid, 0, total_added)
    await update.message.reply_text("✅ Кулдаун сброшен. Можно снова /start.")


async def set_size(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    uid = update.effective_user.id
    if uid not in ADMINS:
        await msg.reply_text("🚫 Эта команда только для админов.")
        return
    if not context.args or len(context.args) < 2:
        await msg.reply_text("⚠️ Использование: /setSize <user_id> <число>")
        return
    try:
        target_user_id = int(context.args[0])
        size = float(context.args[1])
        size = max(-10000, min(size, 10000))
    except ValueError:
        await msg.reply_text("⚠️ Неверные данные. Пример: /setSize 123456789 50")
        return

    last_ts, _ = get_user(target_user_id)
    update_user(target_user_id, last_ts, size)

    await msg.reply_html(
        f"⚒ Размер для <a href='tg://user?id={target_user_id}'>пользователя</a> "
        f"установлен на <b>{size} см</b>."
    )


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat

    # достаём всех пользователей из БД
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT user_id, total_added FROM users")
    rows = cur.fetchall()
    con.close()

    leaderboard = []
    for uid, total in rows:
        try:
            cm = await context.bot.get_chat_member(chat.id, uid)
            # считаем участником, если не ушёл и не кикнут
            if cm.status not in ("left", "kicked"):
                leaderboard.append((uid, float(total)))
        except Exception:
            # пользователя нет в этом чате или нет доступа — пропускаем
            continue

    # сортируем по размеру
    leaderboard.sort(key=lambda x: x[1], reverse=True)

    if not leaderboard:
        await update.message.reply_text("Пока никто из участников этого чата ничего не нарастил.")
        return

    # собираем красивый текст ответа
    lines = ["🏆 Топ участников этого чата:"]
    for i, (uid, total) in enumerate(leaderboard[:10], start=1):
        lines.append(f"{i}. <a href='tg://user?id={uid}'>user</a> — {total:.2f} см")

    await update.message.reply_html("\n".join(lines))


async def macat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    actor = update.effective_user
    if not msg or not msg.reply_to_message or not msg.reply_to_message.from_user:
        await msg.reply_text("Ответьте на сообщение человека и напишите «мацать».")
        return
    target = msg.reply_to_message.from_user
    text = f"🤏 {actor.mention_html()} помацал(а) {target.mention_html()} 😳"
    await msg.reply_html(text)


async def shchipok_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    actor = update.effective_user
    if not msg or not msg.reply_to_message or not msg.reply_to_message.from_user:
        await msg.reply_text("Ответьте на сообщение человека и напишите «ущипнуть».")
        return
    target = msg.reply_to_message.from_user
    text = f"👉 {actor.mention_html()} ущипнул(а) {target.mention_html()} за жопу 🍑"
    await msg.reply_html(text)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Команды:\n"
        "/start — прирост (раз в час)\n"
        "/stats — статистика\n"
        "/top — топ участников чата\n"
        "/setSize — админская команда (установить размер)\n"
        "/help — помощь\n"
        "(в группе) ответьте на сообщение и напишите «мацать» или «ущипнуть»\n"
        "(/reset — только для админов)"
    )


def main():
    init_db()
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler(["start", "growchest"], start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("setSize", set_size))
    app.add_handler(CommandHandler("top", top))

    macat_filter = filters.TEXT & filters.Regex(r"(?i)\bмацать\b") & filters.REPLY
    shchipok_filter = filters.TEXT & filters.Regex(r"(?i)\bущипнуть\b") & filters.REPLY
    app.add_handler(MessageHandler(macat_filter, macat_handler))
    app.add_handler(MessageHandler(shchipok_filter, shchipok_handler))

    print("Bot is running…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
