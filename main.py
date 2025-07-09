import os
import sqlite3
import asyncio
import logging
import aiohttp
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    ContextTypes,
    filters,
    CommandHandler,
)

logging.basicConfig(level=logging.INFO)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
BEARER_TOKEN = os.getenv("BEARER_TOKEN")
HEADERS = {"Authorization": f"Bearer {BEARER_TOKEN}"}
DB_PATH = "tracked_users.db"

# --- DB SETUP ---

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS tracked (
            chat_id INTEGER,
            username TEXT,
            last_tweet_id TEXT,
            PRIMARY KEY (chat_id, username)
        )
    """)
    conn.commit()
    conn.close()

# --- TWITTER API ---

async def fetch_user_id(username, update=None, context=None):
    url = f"https://api.twitter.com/2/users/by/username/{username}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=HEADERS) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("data", {}).get("id")
            elif resp.status == 401 and update and context:
                await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Bearer Token истёк. Обнови токен.")
            elif resp.status == 429 and update and context:
                await context.bot.send_message(chat_id=update.effective_chat.id, text="⚠️ Слишком много запросов. Подожди немного.")
            elif update and context:
                await context.bot.send_message(chat_id=update.effective_chat.id, text=f"❌ Ошибка {resp.status}: {await resp.text()}")
    return None

async def fetch_tweets(user_id, update=None, context=None):
    url = f"https://api.twitter.com/2/users/{user_id}/tweets?tweet.fields=created_at&max_results=10"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=HEADERS) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("data", [])
            elif resp.status == 401 and update and context:
                await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Bearer Token истёк. Обнови токен.")
            elif resp.status == 429 and update and context:
                await context.bot.send_message(chat_id=update.effective_chat.id, text="⚠️ Слишком много запросов. Подожди немного.")
            elif update and context:
                await context.bot.send_message(chat_id=update.effective_chat.id, text=f"❌ Ошибка {resp.status}: {await resp.text()}")
    return []

# --- COMMANDS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет!\n\n"
        "@username — показывает 10 последних твитов\n"
        "@username текст — ищет текст в последних 10 твитах\n"
        "/list — список отслеживаемых\n"
        "/unsubscribe @username — удалить из отслеживания"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "@username — показывает 10 последних твитов\n"
        "@username текст — ищет текст в последних 10 твитах\n"
        "/list — список отслеживаемых\n"
        "/unsubscribe @username — удалить из отслеживания"
    )

async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT username FROM tracked WHERE chat_id = ?", (update.effective_chat.id,))
    users = [f"@{row[0]}" for row in c.fetchall()]
    conn.close()
    if users:
        await update.message.reply_text("Отслеживаемые:\n" + "\n".join(users))
    else:
        await update.message.reply_text("Пока никого не отслеживаете.")

async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        return await update.message.reply_text("Используй: /unsubscribe <@username>")
    username = context.args[0].lstrip("@").lower()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM tracked WHERE chat_id = ? AND username = ?", (update.effective_chat.id, username))
    conn.commit()
    deleted = c.rowcount
    conn.close()
    if deleted:
        await update.message.reply_text(f"@{username} больше не отслеживается.")
    else:
        await update.message.reply_text(f"@{username} не найден в списке.")

# --- TRACKING LOGIC ---

async def track_user(update: Update, context: ContextTypes.DEFAULT_TYPE, username: str):
    chat_id = update.effective_chat.id
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT 1 FROM tracked WHERE chat_id = ? AND username = ?", (chat_id, username))
    if c.fetchone():
        await update.message.reply_text(f"@{username} уже отслеживается.")
        conn.close()
        return
    user_id = await fetch_user_id(username, update, context)
    if not user_id:
        conn.close()
        return await update.message.reply_text("Не удалось получить ID пользователя.")
    tweets = await fetch_tweets(user_id, update, context)
    last_id = None
    for tweet in reversed(tweets):
        await update.message.reply_text(f"@{username}:\n{tweet['text']}\n{tweet['created_at']}")
        last_id = tweet["id"]
    if last_id:
        c.execute("INSERT OR REPLACE INTO tracked VALUES (?, ?, ?)", (chat_id, username, last_id))
        conn.commit()
    conn.close()
    await update.message.reply_text(f"Теперь отслеживаю @{username}")

async def handle_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.startswith("@"):
        return
    parts = text.split(maxsplit=1)
    username = parts[0][1:].lower()
    if len(parts) == 1:
        return await track_user(update, context, username)

    query = parts[1].lower()
    user_id = await fetch_user_id(username, update, context)
    if not user_id:
        return await update.message.reply_text("Пользователь не найден.")
    tweets = await fetch_tweets(user_id, update, context)
    for tweet in tweets:
        if query in tweet["text"].lower():
            return await update.message.reply_text(f"@{username}:\n{tweet['text']}\n{tweet['created_at']}")
    await update.message.reply_text("Ничего не найдено в последних твитах.")

async def tweet_checker(app):
    while True:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT chat_id, username, last_tweet_id FROM tracked")
        rows = c.fetchall()
        for chat_id, username, last_tweet_id in rows:
            user_id = await fetch_user_id(username)
            if not user_id:
                continue
            tweets = await fetch_tweets(user_id)
            if tweets and tweets[0]["id"] != last_tweet_id:
                latest = tweets[0]
                c.execute("UPDATE tracked SET last_tweet_id = ? WHERE chat_id = ? AND username = ?",
                          (latest["id"], chat_id, username))
                await app.bot.send_message(chat_id=chat_id, text=f"@{username}:\n{latest['text']}\n{latest['created_at']}")
        conn.commit()
        conn.close()
        await asyncio.sleep(60)

async def start_checker(app):
    asyncio.create_task(tweet_checker(app))

# --- MAIN ---

def main():
    init_db()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(start_checker).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("list", list_users))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_query))

    app.run_polling()

if __name__ == "__main__":
    main()
