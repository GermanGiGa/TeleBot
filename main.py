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

# 🔑 токен (как просил — прямо в коде)
TOKEN = "8383787249:AAENs2jqlQAIV8FdgIFWPXDw7CUkFSFKRZY"

# 👑 список админов (замени на реальные ID)
ADMINS = [1338785758, 6540420056]

def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    # per-chat прогресс
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS progress (
            chat_id     INTEGER NOT NULL,
            user_id     INTEGER NOT NULL,
            display_name TEXT,
            last_ts     INTEGER DEFAULT 0,
            total_added REAL    DEFAULT 0,
            PRIMARY KEY (chat_id, user_id)
        )
        """
    )
    con.commit()
    con.close()

def get_row(chat_id: int, user_id: int):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT last_ts, total_added, display_name FROM progress WHERE chat_id=? AND user_id=?",
                (chat_id, user_id))
    row = cur.fetchone()
    con.close()
    return row  # None | (last_ts, total_added, display_name)

def upsert_row(chat_id: int, user_id: int, *, display_name: str = None,
               last_ts: int = None, total_added: float = None):
    """Создаёт запись при отсутствии и обновляет переданные поля."""
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    # ensure exists
    cur.execute("INSERT OR IGNORE INTO progress (chat_id, user_id, display_name, last_ts, total_added) VALUES (?, ?, ?, 0, 0.0)",
                (chat_id, user_id, display_name or ""))
    # динамический апдейт
    sets = []
    params = []
    if display_name is not None:
        sets.append("display_name=?"); params.append(display_name)
    if last_ts is not None:
        sets.append("last_ts=?"); params.append(last_ts)
    if total_added is not None:
        sets.append("total_added=?"); params.append(total_added)
    if sets:
        params.extend([chat_id, user_id])
        cur.execute(f"UPDATE progress SET {', '.join(sets)} WHERE chat_id=? AND user_id=?", params)
    con.commit()
    con.close()

def fmt_left(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    return (f"{m} мин {s} сек" if m and s else f"{m} мин" if m else f"{s} сек")

def mention_html_by_id(user_id: int, name: str) -> str:
    return f'<a href="tg://user?id={user_id}">{html.escape(name)}</a>'

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    chat_id, uid = chat.id, user.id
    display_name = user.full_name

    row = get_row(chat_id, uid)
    if row is None:
        last_ts, total_added, _ = 0, 0.0, ""
    else:
        last_ts, total_added, _ = row

    now = int(time.time())
    elapsed = now - last_ts

    # обновим имя на всякий случай
    upsert_row(chat_id, uid, display_name=display_name)

    if elapsed < COOLDOWN_SECONDS:
        left = COOLDOWN_SECONDS - elapsed
        await update.message.reply_html(
            f"⏳ {user.mention_html()} ещё рановато! "
            f"Следующий прирост через <b>{fmt_left(left)}</b>."
        )
        return

    inc = round(uniform(1, 5), 2)
    total_added = round(total_added + inc, 2)
    upsert_row(chat_id, uid, last_ts=now, total_added=total_added)

    await update.message.reply_html(
        f"🎉 {user.mention_html()} получил(а) прирост <b>+{inc} см</b>!\n"
        f"📈 Суммарно в этом чате: <b>{total_added} см</b>.\n"
        f"⛔️ Повторно — через 1 час."
    )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    uid = user.id

    row = get_row(chat_id, uid)
    if row is None:
        last_ts, total_added, _ = 0, 0.0, ""
    else:
        last_ts, total_added, _ = row

    now = int(time.time())
    left = max(0, COOLDOWN_SECONDS - (now - last_ts))
    tip = (f"Следующая попытка через {fmt_left(left)}."
           if left > 0 else "Можно получать прирост прямо сейчас командой /start.")
    await update.message.reply_html(
        f"📊 {user.mention_html()}, ваш суммарный прирост в этом чате: <b>{total_added} см</b>.\n{tip}"
    )

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    uid = user.id
    if uid not in ADMINS:
        await update.message.reply_text("🚫 Эта команда доступна только для админов.")
        return
    row = get_row(chat_id, uid)
    if row is None:
        upsert_row(chat_id, uid, last_ts=0, total_added=0.0)
    else:
        _, total_added, _ = row
        upsert_row(chat_id, uid, last_ts=0, total_added=total_added)
    await update.message.reply_text("✅ Кулдаун сброшен. Можно снова /start.")

# Лидерборд по текущему чату
async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    chat_id = chat.id

    # сколько показать: /top 5  (по умолчанию 10)
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
        "/stats — статистика по вам (в этом чате)\n"
        "/top [N] — топ участников этого чата\n"
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
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("reset", reset))

    # мацать (нужно /setprivacy Disable у бота)
    macat_filter = filters.TEXT & filters.Regex(r"(?i)\bмацать\b") & filters.REPLY
    app.add_handler(MessageHandler(macat_filter, macat_handler))

    print("Bot is running…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
