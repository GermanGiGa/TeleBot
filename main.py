import sqlite3
import time
import html
from random import uniform

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters
)

DB_PATH = "breast_bot.db"
COOLDOWN_SECONDS = 60 * 60  # 1 час

# 🔑 токен
TOKEN = "8383787249:AAENs2jqlQAIV8FdgIFWPXDw7CUkFSFKRZY"

# 👑 список админов
ADMINS = [1338785758, 6540420056]  # замени на реальные ID


# ====== БАЗА ДАННЫХ ======
def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    # Глобальные данные пользователя (не зависят от чата)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id      INTEGER PRIMARY KEY,
            last_ts      INTEGER DEFAULT 0,
            total_total  REAL    DEFAULT 0   -- глобальный рекорд
        )
        """
    )
    # Пер-чатовый прогресс для лидербордов
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS progress (
            chat_id      INTEGER NOT NULL,
            user_id      INTEGER NOT NULL,
            display_name TEXT,
            total_added  REAL    DEFAULT 0,  -- сумма по этому чату
            PRIMARY KEY (chat_id, user_id)
        )
        """
    )
    con.commit()
    con.close()


def get_user_global(user_id: int):
    """Вернёт (last_ts, total_total); создаст запись при отсутствии."""
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT last_ts, total_total FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    if row is None:
        cur.execute("INSERT INTO users (user_id, last_ts, total_total) VALUES (?, ?, ?)", (user_id, 0, 0.0))
        con.commit()
        row = (0, 0.0)
    con.close()
    return row


def set_user_global(user_id: int, *, last_ts: int = None, total_total: float = None):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    sets, params = [], []
    if last_ts is not None:
        sets.append("last_ts=?"); params.append(last_ts)
    if total_total is not None:
        sets.append("total_total=?"); params.append(total_total)
    if sets:
        params.append(user_id)
        cur.execute(f"UPDATE users SET {', '.join(sets)} WHERE user_id=?", params)
        con.commit()
    con.close()


def get_progress(chat_id: int, user_id: int):
    """Вернёт (total_added, display_name) по чату; создаст запись при отсутствии (с нулём)."""
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT total_added, display_name FROM progress WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    row = cur.fetchone()
    if row is None:
        cur.execute("INSERT INTO progress (chat_id, user_id, display_name, total_added) VALUES (?, ?, ?, 0.0)",
                    (chat_id, user_id, "",))
        con.commit()
        row = (0.0, "")
    con.close()
    return row


def set_progress(chat_id: int, user_id: int, *, display_name: str = None, total_added: float = None):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    # ensure exists
    cur.execute("INSERT OR IGNORE INTO progress (chat_id, user_id, display_name, total_added) VALUES (?, ?, ?, 0.0)",
                (chat_id, user_id, display_name or ""))
    sets, params = [], []
    if display_name is not None:
        sets.append("display_name=?"); params.append(display_name)
    if total_added is not None:
        sets.append("total_added=?"); params.append(total_added)
    if sets:
        params.extend([chat_id, user_id])
        cur.execute(f"UPDATE progress SET {', '.join(sets)} WHERE chat_id=? AND user_id=?", params)
        con.commit()
    con.close()


# ====== УТИЛИТЫ ======
def fmt_left(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    return (f"{m} мин {s} сек" if m and s else f"{m} мин" if m else f"{s} сек")


def mention_html_by_id(user_id: int, name: str) -> str:
    return f'<a href="tg://user?id={user_id}">{html.escape(name)}</a>'


# ====== КОМАНДЫ ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    chat_id, uid = chat.id, user.id
    display_name = user.full_name

    # Глобальная часть (кулдаун и общий рекорд)
    last_ts, total_total = get_user_global(uid)
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
    total_total = round(total_total + inc, 2)
    # обновляем глобально
    set_user_global(uid, last_ts=now, total_total=total_total)

    # Обновляем по текущему чату
    chat_total, _ = get_progress(chat_id, uid)
    chat_total = round(chat_total + inc, 2)
    set_progress(chat_id, uid, display_name=display_name, total_added=chat_total)

    await update.message.reply_html(
        f"🎉 {user.mention_html()} получил(а) прирост <b>+{inc} см</b>!\n"
        f"📈 В этом чате: <b>{chat_total} см</b>\n"
        f"🌍 Глобально: <b>{total_total} см</b>\n"
        f"⛔️ Повторно — через 1 час."
    )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    chat_id, uid = chat.id, user.id

    last_ts, total_total = get_user_global(uid)
    chat_total, _ = get_progress(chat_id, uid)

    now = int(time.time())
    left = max(0, COOLDOWN_SECONDS - (now - last_ts))
    tip = (f"Следующая попытка через {fmt_left(left)}."
           if left > 0 else "Можно получать прирост прямо сейчас командой /start.")
    await update.message.reply_html(
        f"📊 {user.mention_html()}, ваш прогресс:\n"
        f"• В этом чате: <b>{chat_total} см</b>\n"
        f"• Глобально: <b>{total_total} см</b>\n"
        f"{tip}"
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сброс кулдауна (глобально) админу себе или по reply — указанному пользователю."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    if user.id not in ADMINS:
        await update.message.reply_text("🚫 Эта команда доступна только для админов.")
        return

    # по reply — сбрасываем выбранному пользователю (глобальный кулдаун)
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        target = update.message.reply_to_message.from_user
        last_ts, total_total = get_user_global(target.id)
        set_user_global(target.id, last_ts=0)  # только кулдаун
        await update.message.reply_html(f"♻️ Кулдаун сброшен у {target.mention_html()}")
    else:
        # иначе — себе
        last_ts, total_total = get_user_global(user.id)
        set_user_global(user.id, last_ts=0)
        await update.message.reply_text("♻️ Ваш кулдаун сброшен.")


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Топ текущего чата (по сумме именно в этом чате)."""
    chat = update.effective_chat
    chat_id = chat.id

    try:
        limit = int(context.args[0]) if context.args else 10
        limit = max(1, min(50, limit))
    except Exception:
        limit = 10

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        "SELECT user_id, display_name, total_added FROM progress "
        "WHERE chat_id=? ORDER BY total_added DESC LIMIT ?",
        (chat_id, limit),
    )
    rows = cur.fetchall()
    con.close()

    if not rows:
        await update.message.reply_text("Пока никто ничего не нарастил в этом чате 😅")
        return

    lines = []
    for i, (uid, name, total) in enumerate(rows, start=1):
        mention = mention_html_by_id(uid, name or f"id:{uid}")
        lines.append(f"{i}. {mention} — <b>{total} см</b>")

    await update.message.reply_html("🏆 Топ по этому чату:\n" + "\n".join(lines))


# «мацать» — без слэша, работает только по reply
async def macat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    actor = update.effective_user
    if not msg or not msg.reply_to_message or not msg.reply_to_message.from_user:
        await msg.reply_text("Ответьте на сообщение человека и напишите «мацать».")
        return
    target = msg.reply_to_message.from_user
    text = f"🤏 {actor.mention_html()} помацал(а) {target.mention_html()} 😳"
    await msg.reply_html(text)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Команды:\n"
        "/start — прирост (раз в час)\n"
        "/stats — ваша статистика (этот чат + глобально)\n"
        "/top [N] — топ участников этого чата\n"
        "/help — помощь\n"
        "(в группе) ответьте на сообщение и напишите «мацать»\n"
        "(/reset — только для админов, по reply — выбранному пользователю, без reply — себе)"
    )


def main():
    init_db()
    app = Application.builder().token(TOKEN).build()

    # команды
    app.add_handler(CommandHandler(["start", "growchest"], start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("reset", reset))

    # слово «мацать» (нужно /setprivacy Disable у бота)
    macat_filter = filters.TEXT & filters.Regex(r"(?i)\bмацать\b") & filters.REPLY
    app.add_handler(MessageHandler(macat_filter, macat_handler))

    print("Bot is running…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
