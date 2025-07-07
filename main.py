import os
import asyncio
import logging
import aiohttp
import json
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
)
from datetime import datetime

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
BEARER_TOKEN = os.getenv("BEARER_TOKEN")

tracked_users = {}  # {username: {"chat_id": ..., "last_tweet_id": ...}}

TWEET_COUNT = 10
HEADERS = {"Authorization": f"Bearer {BEARER_TOKEN}"}

logging.basicConfig(level=logging.INFO)

# ---------------------- Tweet Fetcher ----------------------

async def fetch_tweets(username):
    url = f"https://api.twitter.com/2/tweets/search/recent?query=from:{username}&tweet.fields=created_at&max_results={TWEET_COUNT}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=HEADERS) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            return data.get("data", [])

# ---------------------- Command Handlers ----------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Просто напиши @username чтобы отслеживать пользователя.")

async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not tracked_users:
        await update.message.reply_text("Никто не отслеживается.")
        return
    users = "\n".join([f"@{user}" for user in tracked_users])
    await update.message.reply_text(f"Отслеживаемые:\n{users}")

async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("Используй: /unsubscribe @username")
        return

    username = context.args[0].lstrip("@").lower()
    if username in tracked_users and tracked_users[username]["chat_id"] == update.effective_chat.id:
        del tracked_users[username]
        save_tracked_users()
        await update.message.reply_text(f"Пользователь @{username} удалён из отслеживания.")
    else:
        await update.message.reply_text(f"@{username} не найден.")

# ---------------------- Message Handler ----------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    if not text.startswith("@"):
        return

    parts = text.split(maxsplit=1)
    username = parts[0].lstrip("@").lower()
    query = parts[1] if len(parts) > 1 else None

    tweets = await fetch_tweets(username)
    if not tweets:
        await update.message.reply_text(f"Не удалось получить твиты @{username}.")
        return

    if query:
        for tweet in tweets:
            if query.lower() in tweet["text"].lower():
                await update.message.reply_text(f'https://twitter.com/{username}/status/{tweet["id"]}')
                return
        await update.message.reply_text("Твит с таким текстом не найден.")
    else:
        tracked_users[username] = {
            "chat_id": update.effective_chat.id,
            "last_tweet_id": tweets[0]["id"] if tweets else None,
        }
        save_tracked_users()
        await update.message.reply_text(f"Теперь отслеживаю @{username}.\nПоследние {TWEET_COUNT} твитов:")
        for tweet in tweets:
            await update.message.reply_text(f'https://twitter.com/{username}/status/{tweet["id"]}')

# ---------------------- Tweet Checker ----------------------

async def tweet_checker(application):
    while True:
        for username, data in tracked_users.items():
            tweets = await fetch_tweets(username)
            if not tweets:
                continue

            new_tweets = []
            for tweet in tweets:
                if tweet["id"] == data.get("last_tweet_id"):
                    break
                new_tweets.append(tweet)

            if new_tweets:
                tracked_users[username]["last_tweet_id"] = tweets[0]["id"]
                for tweet in reversed(new_tweets):
                    text = f"@{username} новый твит:\nhttps://twitter.com/{username}/status/{tweet['id']}"
                    try:
                        await application.bot.send_message(chat_id=data["chat_id"], text=text)
                    except Exception as e:
                        logging.error(f"Ошибка отправки твита @{username}: {e}")

        save_tracked_users()
        await asyncio.sleep(60)

# ---------------------- Save/Load ----------------------

SAVE_FILE = "tracked_users.json"

def save_tracked_users():
    with open(SAVE_FILE, "w") as f:
        json.dump(tracked_users, f)

def load_tracked_users():
    global tracked_users
    if os.path.exists(SAVE_FILE):
        with open(SAVE_FILE, "r") as f:
            tracked_users = json.load(f)

# ---------------------- Main ----------------------

def main():
    load_tracked_users()

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("list", list_users))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.job_queue.run_once(lambda *_: asyncio.create_task(tweet_checker(app)), when=1)

    app.run_polling()

if __name__ == "__main__":
    main()
