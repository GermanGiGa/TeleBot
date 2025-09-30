import sqlite3
import time
from random import uniform

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters
)

DB_PATH = "breast_bot.db"
COOLDOWN_SECONDS = 60 * 60  # 1 час

# 🔑 твой токен (как просил — прямо в коде)
TOKEN = "8383787249:AAENs2jqlQAIV8FdgIFWPXDw7CUkFSFKRZY"

# 👑 список админов (впиши сюда свои user_id и друзей)
ADMINS = [1338785758, 6540420056]  # <-- замени на реальные ID


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


# «мацать» — без слэша, только если это reply на чьё-то сообщение
async def macat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    actor = update.effective_user
    if not msg or not msg.reply_to_message or not msg.reply_to_message.from_user:
        await msg.reply_text("Ответьте на сообщение человека и напишите «мацать».")
        return
    target = msg.reply_to_message.from_user
    text = f"🤏 {actor.mention_html()} помацал(а) {target.mention_html()} 😳"
    await msg.reply_html(text)


# 🔥 /top — лидерборд среди УЧАСТНИКОВ ТЕКУЩЕГО ЧАТА по их глобальному total_added
async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    try:
        limit = int(context.args[0]) if context.args else 10
        limit = max(1, min(50, limit))
    except Exception:
        limit = 10

    # берём всех пользователей из глобальной таблицы и фильтруем тех, кто состоит в этом чате
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT user_id, total_added FROM users ORDER BY total_added DESC")
    all_rows = cur.fetchall()
    con.close()

    rows = []
    for uid, total in all_rows:
        try:
            member = await context.bot.get_chat_member(chat.id, uid)
            if member.status not in ("left", "kicked"):
                rows.append((member.user, total))  # сохраняем объект User, чтобы красиво упомянуть
        except:
            continue
        if len(rows) >= limit:
            break

    if not rows:
        await update.message.reply_text("В этом чате пока никто ничего не нарастил 😅")
        return

    lines = []
    for i, (user_obj, total) in enumerate(rows, start=1):
        lines.append(f"{i}. {user_obj.mention_html()} — <b>{total} см</b>")

    await update.message.reply_html("🏆 Топ участников этого чата:\n" + "\n".join(lines))


# 👑 /setSize — только для админов
# Использование:
#   1) Ответь на сообщение человека и напиши: /setSize 123.45
#   2) Или: /setSize <user_id> 123.45
async def set_size(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caller = update.effective_user
    if caller.id not in ADMINS:
        await update.message.reply_text("🚫 Эта команда доступна только для админов.")
        return

    msg = update.message

    target_user_id = None
    new_size = None

    # Вариант 1: reply -> /setSize 123.45
    if msg.reply_to_message and msg.reply_to_message.from_user:
        if not context.args:
            await msg.reply_text("⚠️ Использование: ответьте на сообщение и введите /setSize <число>")
            return
        try:
            new_size = float(context.args[0])
        except ValueError:
            await msg.reply_text("⚠️ Укажите корректное число.")
            return
        target_user_id = msg.reply_to_message.from_user.id

    # Вариант 2: /setSize <user_id> <число>
    else:
        if len(context.args) < 2:
            await msg.reply_text("⚠️ Использование: /setSize <user_id> <число>  (или по reply: /setSize <число>)")
            return
        try:
            target_user_id = int(context.args[0])
        except ValueError:
            await msg.reply_text("⚠️ Вместо <user_id> нужно указать числовой ID пользователя.")
            return
        try:
            new_size = float(context.args[1])
        except ValueError:
            await msg.reply_text("⚠️ Укажите корректное число.")
            return

    # Обновляем БД
    last_ts, _ = get_user(target_user_id)  # создаст запись, если нет
    update_user(target_user_id, last_ts, float(new_size))

    # Для красивого подтверждения попробуем получить профиль (если бот в чате с этим пользователем)
    mention_html = f"<a href=\"tg://user?id={target_user_id}\">user {target_user_id}</a>"
    try:
        member = await context.bot.get_chat_member(update.effective_chat.id, target_user_id)
        mention_html = member.user.mention_html()
    except:
        pass

    await msg.reply_html(f"✅ Размер для {mention_html} установлен: <b>{float(new_size)} см</b>")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Команды:\n"
        "/start — прирост (раз в час)\n"
        "/stats — статистика\n"
        "/top [N] — топ участников ЭТОГО чата\n"
        "/setSize — (только админы) reply: /setSize <число>  или  /setSize <user_id> <число>\n"
        "/help — помощь\n"
        "(в группе) ответьте на сообщение и напишите «мацать»\n"
        "(/reset — только для админов)"
    )


def main():
    init_db()
    app = Application.builder().token(TOKEN).build()

    # команды
    app.add_handler(CommandHandler(["start", "growchest"], start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("setSize", set_size))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("reset", reset))

    # мацать (нужно /setprivacy Disable у бота)
    macat_filter = filters.TEXT & filters.Regex(r"(?i)\bмацать\b") & filters.REPLY
    app.add_handler(MessageHandler(macat_filter, macat_handler))

    print("Bot is running…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
