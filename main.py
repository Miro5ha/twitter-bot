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

DB_PATH = "tracked_users.db"
HEADERS = {"Authorization": f"Bearer {BEARER_TOKEN}"}


# --- DATABASE SETUP ---

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


def add_tracked_user(chat_id, username, last_tweet_id=""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO tracked (chat_id, username, last_tweet_id) VALUES (?, ?, ?)",
              (chat_id, username, last_tweet_id))
    conn.commit()
    conn.close()


def remove_tracked_user(chat_id, username):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM tracked WHERE chat_id = ? AND username = ?", (chat_id, username))
    conn.commit()
    conn.close()


def get_tracked_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT chat_id, username, last_tweet_id FROM tracked")
    result = c.fetchall()
    conn.close()
    return result


def update_last_tweet_id(chat_id, username, tweet_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE tracked SET last_tweet_id = ? WHERE chat_id = ? AND username = ?",
              (tweet_id, chat_id, username))
    conn.commit()
    conn.close()


def get_usernames_by_chat(chat_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT username FROM tracked WHERE chat_id = ?", (chat_id,))
    users = [row[0] for row in c.fetchall()]
    conn.close()
    return users


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


# --- HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет!\n\n"
        "@username — показывает 10 последних твитов автора\n"
        "@username текст — ищет текст в последних 10 твитах\n"
        "/list — список отслеживаемых\n"
        "/unsubscribe @username — удалить из отслеживания"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "@username — показывает 10 последних твитов автора\n"
        "@username текст — ищет текст в последних 10 твитах\n"
        "/list — список отслеживаемых\n"
        "/unsubscribe @username — удалить из отслеживания"
    )


async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    users = get_usernames_by_chat(chat_id)
    if not users:
        await update.message.reply_text("Вы пока никого не отслеживаете.")
    else:
        await update.message.reply_text("Отслеживаемые пользователи:\n" + "\n".join(f"@{u}" for u in users))


async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if len(context.args) != 1:
        await update.message.reply_text("Используй: /unsubscribe <username>")
        return

    username = context.args[0].lstrip("@").lower()
    users = get_usernames_by_chat(chat_id)

    if username in users:
        remove_tracked_user(chat_id, username)
        await update.message.reply_text(f"@{username} больше не отслеживается.")
    else:
        await update.message.reply_text(f"@{username} не найден в списке отслеживаемых.")


async def handle_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.startswith("@"):
        return

    parts = text.split(maxsplit=1)
    username = parts[0][1:].lower()
    query = parts[1].lower() if len(parts) == 2 else None

    user_id = await fetch_user_id(username, update, context)
    if not user_id:
        return

    tweets = await fetch_tweets(user_id, update, context)
    if query:
        for tweet in tweets:
            if query in tweet["text"].lower():
                await update.message.reply_text(f"@{username}:\n{tweet['text']}\n{tweet['created_at']}")
                return
        await update.message.reply_text("Ничего не найдено в последних твитах.")
    else:
        chat_id = update.effective_chat.id
        for tweet in reversed(tweets):
            await update.message.reply_text(f"@{username}:\n{tweet['text']}\n{tweet['created_at']}")
        if tweets:
            add_tracked_user(chat_id, username, tweets[0]["id"])


# --- TRACKER ---

async def tweet_checker(app):
    while True:
        all_tracked = get_tracked_users()
        for chat_id, username, last_id in all_tracked:
            user_id = await fetch_user_id(username)
            if not user_id:
                continue
            tweets = await fetch_tweets(user_id)
            if not tweets:
                continue
            latest = tweets[0]
            if latest["id"] != last_id:
                await app.bot.send_message(
                    chat_id=chat_id,
                    text=f"@{username}:\n{latest['text']}\n{latest['created_at']}"
                )
                update_last_tweet_id(chat_id, username, latest["id"])
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
