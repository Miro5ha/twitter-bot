import os
import json
import asyncio
import logging
import aiohttp
from telegram import Update
from telegram.error import TelegramError
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
BEARER_TOKEN = os.getenv("BEARER_TOKEN")
TRACKED_USERS_FILE = "tracked_users.json"

tracked_users = {}  # chat_id: [usernames]
user_last_tweet_ids = {}  # username: last_tweet_id
HEADERS = {"Authorization": f"Bearer {BEARER_TOKEN}"}


def load_tracked_users():
    global tracked_users
    if os.path.exists(TRACKED_USERS_FILE):
        with open(TRACKED_USERS_FILE, "r", encoding="utf-8") as f:
            tracked_users = json.load(f)
    else:
        tracked_users = {}


def save_tracked_users():
    with open(TRACKED_USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(tracked_users, f, ensure_ascii=False, indent=2)


async def fetch_user_id(username):
    url = f"https://api.twitter.com/2/users/by/username/{username}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=HEADERS) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("data", {}).get("id")
            logging.error(f"Ошибка получения ID @{username}: [{resp.status}] {await resp.text()}")
    return None


async def fetch_tweets(user_id):
    url = f"https://api.twitter.com/2/users/{user_id}/tweets?tweet.fields=created_at&max_results=10"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=HEADERS) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("data", [])
            logging.error(f"Ошибка получения твитов user_id={user_id}: [{resp.status}] {await resp.text()}")
    return []


async def track_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.startswith("@"):
        return

    username = text[1:].lower()
    chat_id = str(update.effective_chat.id)

    if chat_id not in tracked_users:
        tracked_users[chat_id] = []

    if username not in tracked_users[chat_id]:
        tracked_users[chat_id].append(username)
        save_tracked_users()
        await update.message.reply_text(f"Теперь отслеживаю @{username}")

        user_id = await fetch_user_id(username)
        if user_id:
            tweets = await fetch_tweets(user_id)
            for tweet in reversed(tweets):
                await update.message.reply_text(
                    f"@{username}:\n{tweet['text']}\n{tweet['created_at']}"
                )
                user_last_tweet_ids[username] = tweet["id"]
        else:
            await update.message.reply_text("❌ Не удалось получить ID пользователя.")
    else:
        await update.message.reply_text(f"@{username} уже отслеживается.")


async def handle_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.startswith("@"):
        return

    parts = text.split(maxsplit=1)
    if len(parts) != 2:
        return

    username = parts[0][1:].lower()
    query = parts[1].lower()

    user_id = await fetch_user_id(username)
    if not user_id:
        await update.message.reply_text("❌ Пользователь не найден.")
        return

    tweets = await fetch_tweets(user_id)
    for tweet in tweets:
        if query in tweet["text"].lower():
            await update.message.reply_text(
                f"@{username}:\n{tweet['text']}\n{tweet['created_at']}"
            )
            return

    await update.message.reply_text("🔍 Ничего не найдено в последних твитах.")


async def tweet_checker(app):
    while True:
        for chat_id, usernames in tracked_users.items():
            for username in usernames:
                user_id = await fetch_user_id(username)
                if not user_id:
                    continue
                tweets = await fetch_tweets(user_id)
                if not tweets:
                    continue
                latest = tweets[0]
                last_id = user_last_tweet_ids.get(username)
                if latest["id"] != last_id:
                    user_last_tweet_ids[username] = latest["id"]
                    try:
                        await app.bot.send_message(
                            chat_id=chat_id,
                            text=f"@{username}:\n{latest['text']}\n{latest['created_at']}"
                        )
                    except TelegramError as e:
                        logging.error(f"Ошибка отправки сообщения: {e}")
        await asyncio.sleep(60)


async def start_checker(app):
    asyncio.create_task(tweet_checker(app))


async def main():
    load_tracked_users()

    app = (
        ApplicationBuilder()
        .token(TELEGRAM_TOKEN)
        .post_init(start_checker)
        .build()
    )

    await app.bot.delete_webhook(drop_pending_updates=True)

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_query))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, track_user))

    await app.run_polling()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logging.critical(f"❌ Бот не запустился: {e}")
