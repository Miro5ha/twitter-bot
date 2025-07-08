import os
import sqlite3
import asyncio
import logging
import aiohttp
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(level=logging.INFO)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
BEARER_TOKEN = os.getenv("BEARER_TOKEN")
HEADERS = {"Authorization": f"Bearer {BEARER_TOKEN}"}


# === DATABASE SETUP ===
conn = sqlite3.connect("/app/data/tracked_users.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS tracked (
    chat_id INTEGER,
    username TEXT,
    last_tweet_id TEXT,
    PRIMARY KEY (chat_id, username)
)
""")
conn.commit()


# === TWITTER API ===
async def fetch_user_id(username):
    url = f"https://api.twitter.com/2/users/by/username/{username}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=HEADERS) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("data", {}).get("id")
    return None


async def fetch_tweets(user_id):
    url = f"https://api.twitter.com/2/users/{user_id}/tweets?tweet.fields=created_at&max_results=10"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=HEADERS) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("data", [])
    return []


# === COMMANDS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет!\n"
        "@username — показать последние 10 твитов\n"
        "@username текст — найти твит по тексту\n"
        "/unsubscribe @username — отписаться\n"
        "/list — список отслеживаемых пользователей"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "@username — показать последние 10 твитов\n"
        "@username текст — найти твит по тексту\n"
        "/unsubscribe @username — отписаться\n"
        "/list — список отслеживаемых пользователей"
    )


async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    cursor.execute("SELECT username FROM tracked WHERE chat_id = ?", (chat_id,))
    rows = cursor.fetchall()

    if not rows:
        await update.message.reply_text("Вы пока никого не отслеживаете.")
    else:
        await update.message.reply_text("Отслеживаемые пользователи:\n" + "\n".join(f"@{row[0]}" for row in rows))


async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if len(context.args) != 1:
        await update.message.reply_text("Используй: /unsubscribe <username>")
        return

    username = context.args[0].lstrip("@").lower()
    cursor.execute("DELETE FROM tracked WHERE chat_id = ? AND username = ?", (chat_id, username))
    conn.commit()

    await update.message.reply_text(f"@{username} больше не отслеживается.")


# === HANDLERS ===
async def track_user(update: Update, context: ContextTypes.DEFAULT_TYPE, username, query=None):
    chat_id = update.effective_chat.id

    cursor.execute("SELECT 1 FROM tracked WHERE chat_id = ? AND username = ?", (chat_id, username))
    if not cursor.fetchone():
        user_id = await fetch_user_id(username)
        if not user_id:
            await update.message.reply_text("Пользователь не найден.")
            return

        tweets = await fetch_tweets(user_id)
        if not tweets:
            await update.message.reply_text("Нет твитов.")
            return

        cursor.execute("INSERT INTO tracked (chat_id, username, last_tweet_id) VALUES (?, ?, ?)",
                       (chat_id, username, tweets[0]["id"]))
        conn.commit()

        await update.message.reply_text(f"Теперь отслеживаю @{username}")
        for tweet in reversed(tweets):
            await update.message.reply_text(f"@{username}:\n{tweet['text']}\n{tweet['created_at']}")

    elif query:
        user_id = await fetch_user_id(username)
        if not user_id:
            await update.message.reply_text("Пользователь не найден.")
            return

        tweets = await fetch_tweets(user_id)
        for tweet in tweets:
            if query.lower() in tweet["text"].lower():
                await update.message.reply_text(f"@{username}:\n{tweet['text']}\n{tweet['created_at']}")
                return
        await update.message.reply_text("Ничего не найдено.")
    else:
        await update.message.reply_text(f"@{username} уже отслеживается.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.startswith("@"):
        return

    parts = text.split(maxsplit=1)
    username = parts[0][1:].lower()
    query = parts[1] if len(parts) > 1 else None

    await track_user(update, context, username, query)


# === BACKGROUND CHECKER ===
async def tweet_checker(app):
    while True:
        cursor.execute("SELECT DISTINCT chat_id, username, last_tweet_id FROM tracked")
        for chat_id, username, last_id in cursor.fetchall():
            user_id = await fetch_user_id(username)
            if not user_id:
                continue

            tweets = await fetch_tweets(user_id)
            if tweets and tweets[0]["id"] != last_id:
                latest = tweets[0]
                cursor.execute("UPDATE tracked SET last_tweet_id = ? WHERE chat_id = ? AND username = ?",
                               (latest["id"], chat_id, username))
                conn.commit()

                await app.bot.send_message(
                    chat_id=chat_id,
                    text=f"@{username}:\n{latest['text']}\n{latest['created_at']}"
                )

        await asyncio.sleep(60)


async def start_checker(app):
    asyncio.create_task(tweet_checker(app))


# === RUN APP ===
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(start_checker).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("list", list_users))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.run_polling()


if __name__ == "__main__":
    main()
