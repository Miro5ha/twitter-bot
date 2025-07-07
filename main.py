import os
import json
import asyncio
import logging
import aiohttp
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    filters,
)
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
BEARER_TOKEN = os.getenv("BEARER_TOKEN")
HEADERS = {"Authorization": f"Bearer {BEARER_TOKEN}"}
TRACKED_FILE = "tracked_users.json"
TRACKED_USERS = {}

logging.basicConfig(level=logging.INFO)

async def fetch_user_id(username):
    url = f"https://api.twitter.com/2/users/by/username/{username}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=HEADERS) as resp:
            data = await resp.json()
            return data.get("data", {}).get("id")

async def fetch_tweets(user_id, since_id=None):
    url = f"https://api.twitter.com/2/users/{user_id}/tweets?max_results=10&tweet.fields=created_at"
    if since_id:
        url += f"&since_id={since_id}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=HEADERS) as resp:
            data = await resp.json()
            return data.get("data", [])

def save_users():
    with open(TRACKED_FILE, "w") as f:
        json.dump(TRACKED_USERS, f)

def load_users():
    global TRACKED_USERS
    if os.path.exists(TRACKED_FILE):
        with open(TRACKED_FILE) as f:
            TRACKED_USERS = json.load(f)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Просто напиши @username, чтобы отслеживать твиты.")

async def track_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.text.startswith("@"):
        return
    username = update.message.text[1:].strip().lower()
    chat_id = str(update.effective_chat.id)

    user_id = await fetch_user_id(username)
    if not user_id:
        await update.message.reply_text("Пользователь не найден.")
        return

    if username not in TRACKED_USERS:
        TRACKED_USERS[username] = {"id": user_id, "chats": [chat_id], "last_id": None}
    else:
        if chat_id not in TRACKED_USERS[username]["chats"]:
            TRACKED_USERS[username]["chats"].append(chat_id)

    save_users()
    tweets = await fetch_tweets(user_id)
    TRACKED_USERS[username]["last_id"] = tweets[0]["id"] if tweets else None
    await update.message.reply_text(f"Теперь отслеживаю @{username}.")

async def tweet_checker(app):
    while True:
        for username, info in TRACKED_USERS.items():
            tweets = await fetch_tweets(info["id"], info.get("last_id"))
            if tweets:
                tweets = list(reversed(tweets))
                info["last_id"] = tweets[-1]["id"]
                for tweet in tweets:
                    text = f"@{username}:\n{tweet['text']}\n{tweet['created_at']}"
                    for chat_id in info["chats"]:
                        await app.bot.send_message(chat_id=chat_id, text=text)
        save_users()
        await asyncio.sleep(60)

async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    removed = []
    for username in list(TRACKED_USERS):
        if chat_id in TRACKED_USERS[username]["chats"]:
            TRACKED_USERS[username]["chats"].remove(chat_id)
            if not TRACKED_USERS[username]["chats"]:
                del TRACKED_USERS[username]
            removed.append(username)
    save_users()
    if removed:
        await update.message.reply_text(f"Отписка от: {', '.join(removed)}.")
    else:
        await update.message.reply_text("Вы никого не отслеживали.")

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Напиши: /поиск <текст>")
        return

    query = " ".join(context.args).lower()
    results = []
    for username, info in TRACKED_USERS.items():
        tweets = await fetch_tweets(info["id"])
        for tweet in tweets:
            if query in tweet["text"].lower():
                results.append(f"@{username}: {tweet['text'][:100]}")

    if results:
        await update.message.reply_text("\n\n".join(results[:10]))
    else:
        await update.message.reply_text("Ничего не найдено.")

def main():
    load_users()
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("поиск", search_command))
    app.add_handler(CommandHandler("отписка", unsubscribe))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, track_user))

    asyncio.create_task(tweet_checker(app))
    app.run_polling()

if __name__ == "__main__":
    main()
