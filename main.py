import os
import json
import asyncio
import logging
import aiohttp
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, ContextTypes, filters

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
BEARER_TOKEN = os.environ["BEARER_TOKEN"]
TRACKED_USERS_FILE = "tracked_users.json"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if not os.path.exists(TRACKED_USERS_FILE):
    with open(TRACKED_USERS_FILE, "w") as f:
        json.dump({}, f)

def load_tracked_users():
    with open(TRACKED_USERS_FILE, "r") as f:
        return json.load(f)

def save_tracked_users(data):
    with open(TRACKED_USERS_FILE, "w") as f:
        json.dump(data, f)

async def fetch_user_id(username, session):
    url = f"https://api.twitter.com/2/users/by/username/{username}"
    headers = {"Authorization": f"Bearer {BEARER_TOKEN}"}
    async with session.get(url, headers=headers) as response:
        data = await response.json()
        return data.get("data", {}).get("id")

async def fetch_latest_tweet(user_id, session):
    url = f"https://api.twitter.com/2/users/{user_id}/tweets?max_results=5&tweet.fields=created_at"
    headers = {"Authorization": f"Bearer {BEARER_TOKEN}"}
    async with session.get(url, headers=headers) as response:
        data = await response.json()
        tweets = data.get("data", [])
        return tweets[0] if tweets else None

async def tweet_checker(app: Application):
    await app.bot.wait_until_ready()
    while True:
        try:
            users = load_tracked_users()
            async with aiohttp.ClientSession() as session:
                for username, info in users.items():
                    user_id = info.get("user_id")
                    last_id = info.get("last_tweet_id")
                    chat_ids = info.get("chat_ids", [])
                    tweet = await fetch_latest_tweet(user_id, session)
                    if tweet and tweet["id"] != last_id:
                        users[username]["last_tweet_id"] = tweet["id"]
                        for chat_id in chat_ids:
                            await app.bot.send_message(chat_id, f"🧵 Новый твит от @{username}:\nhttps://twitter.com/{username}/status/{tweet['id']}")
                        save_tracked_users(users)
        except Exception as e:
            logger.error(f"Ошибка при проверке твитов: {e}")
        await asyncio.sleep(90)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Просто отправь мне @username, и я начну отслеживать твиты. Чтобы отписаться — /unsubscribe @username. Посмотреть — /list")

async def list_subs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_tracked_users()
    chat_id = str(update.message.chat_id)
    result = [f"@{u}" for u, v in users.items() if chat_id in v.get("chat_ids", [])]
    text = "Ты подписан на:\n" + "\n".join(result) if result else "Ты ни на кого не подписан."
    await update.message.reply_text(text)

async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Укажи имя: /unsubscribe @username")
    username = context.args[0].lstrip("@")
    users = load_tracked_users()
    chat_id = str(update.message.chat_id)
    if username in users and chat_id in users[username]["chat_ids"]:
        users[username]["chat_ids"].remove(chat_id)
        if not users[username]["chat_ids"]:
            users.pop(username)
        save_tracked_users(users)
        await update.message.reply_text(f"Больше не слежу за @{username}.")
    else:
        await update.message.reply_text("Ты не подписан на этого пользователя.")

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if not text.startswith("@"):
        return
    username = text.lstrip("@")
    chat_id = str(update.message.chat_id)
    users = load_tracked_users()
    if username in users and chat_id in users[username].get("chat_ids", []):
        return await update.message.reply_text(f"Ты уже подписан на @{username}.")
    async with aiohttp.ClientSession() as session:
        user_id = await fetch_user_id(username, session)
        if not user_id:
            return await update.message.reply_text("Пользователь не найден.")
        tweet = await fetch_latest_tweet(user_id, session)
        users.setdefault(username, {
            "user_id": user_id,
            "last_tweet_id": tweet["id"] if tweet else None,
            "chat_ids": []
        })["chat_ids"].append(chat_id)
        save_tracked_users(users)
        await update.message.reply_text(f"Теперь слежу за @{username}.")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("list", list_subs))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, subscribe))
    app.job_queue.run_once(lambda *_: asyncio.create_task(tweet_checker(app)), when=1)
    app.run_polling()

if __name__ == "__main__":
    main()
