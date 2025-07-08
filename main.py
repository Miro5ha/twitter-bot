import os
import json
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

tracked_users = {}
user_last_tweet_ids = {}

HEADERS = {"Authorization": f"Bearer {BEARER_TOKEN}"}


async def fetch_user_id(username):
    url = f"https://api.twitter.com/2/users/by/username/{username}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=HEADERS) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("data", {}).get("id")
    return None


async def fetch_tweets(user_id):
    url = (
        f"https://api.twitter.com/2/users/{user_id}/tweets"
        f"?tweet.fields=created_at&max_results=10"
    )
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=HEADERS) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("data", [])
    return []


async def track_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.startswith("@"):
        return

    username = text[1:].lower()
    chat_id = update.effective_chat.id

    if chat_id not in tracked_users:
        tracked_users[chat_id] = []

    if username not in tracked_users[chat_id]:
        tracked_users[chat_id].append(username)
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
            await update.message.reply_text("Не удалось получить ID пользователя.")
    else:
        await update.message.reply_text(f"@{username} уже отслеживается.")


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
                    await app.bot.send_message(
                        chat_id=chat_id,
                        text=f"@{username}:\n{latest['text']}\n{latest['created_at']}"
                    )
        await asyncio.sleep(60)


async def handle_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.startswith("@"):
        return

    parts = text.split(maxsplit=1)
    if len(parts) != 2:
        return await track_user(update, context)

    username = parts[0][1:].lower()
    query = parts[1].lower()

    user_id = await fetch_user_id(username)
    if not user_id:
        await update.message.reply_text("Пользователь не найден.")
        return

    tweets = await fetch_tweets(user_id)
    for tweet in tweets:
        if query in tweet["text"].lower():
            await update.message.reply_text(
                f"@{username}:\n{tweet['text']}\n{tweet['created_at']}"
            )
            return

    await update.message.reply_text("Ничего не найдено в последних твитах.")


async def start_checker(app):
    asyncio.create_task(tweet_checker(app))


async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    users = tracked_users.get(chat_id, [])
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

    if chat_id in tracked_users and username in tracked_users[chat_id]:
        tracked_users[chat_id].remove(username)
        user_last_tweet_ids.pop(username, None)
        await update.message.reply_text(f"@{username} больше не отслеживается.")
    else:
        await update.message.reply_text(f"@{username} не найден в списке отслеживаемых.")


def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(start_checker).build()

    app.add_handler(CommandHandler("list", list_users))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_query))

    app.run_polling()


if __name__ == "__main__":
    main()
