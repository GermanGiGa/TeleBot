import asyncio
import sqlite3
import time
from random import uniform

from telegram import Update
from telegram.error import RetryAfter
from telegram.ext import (Application, CommandHandler, 
    MessageHandler, ContextTypes, filters,)
    

DB_PATH = "breast_bot.db"
COOLDOWN_SECONDS = 60 * 60  # 1 час

# 🔑 твой токен
TOKEN = "8383787249:AAENs2jqlQAIV8FdgIFWPXDw7CUkFSFKRZY"

# 👑 список админов (впиши реальные ID)
ADMINS = [8147146526, 7689278428, 6540420056, 1338785758]


# ======================= БАЗА ДАННЫХ =======================

def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    # Более устойчивый режим записи
    cur.execute("PRAGMA journal_mode=WAL;")
    cur.execute("PRAGMA synchronous=NORMAL;")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            last_ts INTEGER DEFAULT 0,
            total_added REAL DEFAULT 0
        )
        """
    )
    # Индексы не нужны, т.к. PK уже на user_id
    con.commit()
    con.close()


def get_user(user_id: int):
    """Надёжно возвращает (last_ts, total_added) и создаёт запись при её отсутствии."""
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    # Безгоночная инициализация
    cur.execute(
        "INSERT OR IGNORE INTO users (user_id, last_ts, total_added) VALUES (?, 0, 0.0)",
        (user_id,)
    )
    con.commit()
    cur.execute("SELECT last_ts, total_added FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    con.close()
    # row гарантированно есть
    return row[0], row[1]


def update_user(user_id: int, last_ts: int, total_added: float):
    """Обновляет пользователя с жёстким лимитом значений."""
    # Ограничение значений от -10000 до 10000
   con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        "UPDATE users SET last_ts=?, total_added=? WHERE user_id=?",
        (last_ts, total_added, user_id),
    )
    con.commit()
    con.close()


def fmt_left(seconds: int) -> str:
    m, s = divmod(int(seconds), 60)
    return (f"{m} мин {s} сек" if m and s else f"{m} мин" if m else f"{s} сек")


# ======================= КОМАНДЫ =======================

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


# 👑 /setSize — админ: по reply ИЛИ по user_id
async def set_size(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    caller_id = update.effective_user.id

    if caller_id not in ADMINS:
        await msg.reply_text("🚫 Эта команда доступна только для админов.")
        return

    target_user = None
    size = None

    # Вариант 1: ответ на сообщение — /setSize 123.45
    if msg.reply_to_message and msg.reply_to_message.from_user:
        target_user = msg.reply_to_message.from_user
        if len(context.args) < 1:
            await msg.reply_text("⚠ Укажите размер. Пример: /setSize 25")
            return
        try:
            size = float(context.args[0])
        except ValueError:
            await msg.reply_text("⚠ Размер должен быть числом.")
            return

    # Вариант 2: /setSize <user_id> <size>
    elif len(context.args) >= 2:
        try:
            target_user_id = int(context.args[0])
            # берём юзера из чата, чтобы красиво упомянуть
            member = await context.bot.get_chat_member(update.effective_chat.id, target_user_id)
            target_user = member.user
            size = float(context.args[1])
        except ValueError:
            await msg.reply_text("⚠ Используйте: /setSize <user_id> <size>")
            return
        except Exception:
            # если юзер не в этом чате, всё равно установим по ID и упомянем как ссылку
            target_user = type("Dummy", (), {})()
            target_user.id = target_user_id
            target_user.first_name = f"user {target_user_id}"
            target_user.mention_html = lambda: f"<a href='tg://user?id={target_user_id}'>user {target_user_id}</a>"
    else:
        await msg.reply_text("⚠ Ответьте на сообщение или используйте: /setSize <user_id> <size>")
        return

    # Лимит значений
    size = max(-10000, min(size, 10000))   # лимит только для setSize
    # Обновляем БД
    last_ts, _ = get_user(target_user.id)
    update_user(target_user.id, last_ts, size)

    # Читаем обратно и подтверждаем
    _, check_total = get_user(target_user.id)
    await msg.reply_html(
        f"✅ Размер для {target_user.mention_html()} установлен: <b>{check_total:.2f} см</b>"
    )


# /top — только участники текущего чата, значения глобальные
async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat

    # Берём всех юзеров из БД
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT user_id, total_added FROM users")
    rows = cur.fetchall()
    con.close()

    # Фильтруем по тем, кто реально состоит в ЭТОМ чате
    leaderboard = []
    for uid, total in rows:
        try:
            cm = await context.bot.get_chat_member(chat.id, int(uid))
            if cm.status not in ("left", "kicked"):  # участник здесь
                leaderboard.append((cm.user, float(total)))
        except Exception:
            continue

    # Сортировка
    leaderboard.sort(key=lambda x: x[1], reverse=True)

    if not leaderboard:
        await update.message.reply_text("Пока никто из участников этого чата ничего не нарастил.")
        return

    # Красивый вывод
    lines = ["🏆 Топ участников этого чата:"]
    for i, (u, total) in enumerate(leaderboard[:10], start=1):
        lines.append(f"{i}. {u.mention_html()} — {total:.2f} см")

    await update.message.reply_html("\n".join(lines))


# «мацать» — без слэша, только reply
async def macat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    actor = update.effective_user
    if not msg or not msg.reply_to_message or not msg.reply_to_message.from_user:
        await msg.reply_text("Ответьте на сообщение человека и напишите «мацать».")
        return
    target = msg.reply_to_message.from_user
    text = f"🤏 {actor.mention_html()} помацал(а) {target.mention_html()} 😳"
    await msg.reply_html(text)


# «ущипнуть» — без слэша, только reply
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


# ======================= ОШИБКИ/ЛИМИТЫ =======================

async def on_error(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Тихо переждать лимит Telegram
    if isinstance(context.error, RetryAfter):
        try:
            await asyncio.sleep(context.error.retry_after)
        except Exception:
            pass
        return
    # Можно логировать остальные ошибки короче, чтобы не забивать Railway
    # print(f"Error: {context.error}")


# ======================= MAIN =======================

def main():
    init_db()
    app = (
        Application
        .builder()
        .token(TOKEN)
        .concurrent_updates(False)        # по одному апдейту за раз
        .build()
    )

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

    app.add_error_handler(on_error)

    print("Bot is running…")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
