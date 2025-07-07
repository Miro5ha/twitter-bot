import time
import requests
import os
import json
from telegram import Update
from dotenv import load_dotenv
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    CallbackContext,
)

load_dotenv()

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
BEARER_TOKEN = os.environ.get("BEARER_TOKEN")

TRACKED_FILE = "tracked.json"


def load_tracked_users():
    if os.path.exists(TRACKED_FILE):
        with open(TRACKED_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_tracked_users():
    with open(TRACKED_FILE, "w", encoding="utf-8") as f:
        json.dump(tracked_users, f, ensure_ascii=False, indent=2)


tracked_users = load_tracked_users()


def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "Привет! Напиши мне запрос в формате:\n@username или @username текст_твита"
    )


def unsubscribe(update: Update, context: CallbackContext):
    chat_id = str(update.message.chat_id)
    if chat_id in tracked_users:
        del tracked_users[chat_id]
        save_tracked_users()
        update.message.reply_text("✅ Вы отписались от всех уведомлений.")
    else:
        update.message.reply_text("❌ Вы не подписаны ни на один аккаунт.")


def get_user_id(username):
    headers = {"Authorization": f"Bearer {BEARER_TOKEN}"}
    url = f"https://api.twitter.com/2/users/by/username/{username}"
    try:
        r = requests.get(url, headers=headers)
        if r.status_code == 200:
            return r.json()["data"]["id"]
        elif r.status_code == 429:
            return "RATE_LIMIT"
    except:
        pass
    return None


def fetch_latest_tweet(username):
    headers = {"Authorization": f"Bearer {BEARER_TOKEN}"}
    url = "https://api.twitter.com/2/tweets/search/recent"
    params = {
        "query": f"from:{username}",
        "max_results": 10,
        "tweet.fields": "created_at",
    }
    try:
        r = requests.get(url, headers=headers, params=params)
        if r.status_code == 200 and "data" in r.json():
            return r.json()["data"][0]
    except:
        pass
    return None


def auto_update(context: CallbackContext):
    for chat_id, users in tracked_users.items():
        for username, last_id in users.items():
            latest = fetch_latest_tweet(username)
            if latest and latest["id"] != last_id:
                tweet_text = latest["text"]
                tweet_id = latest["id"]
                tweet_url = f"https://twitter.com/{username}/status/{tweet_id}"
                context.bot.send_message(
                    chat_id=int(chat_id),
                    text=f'📢 <b>Новый твит от @{username}</b>\n\n{tweet_text}\n\n🔗 <a href="{tweet_url}">Открыть в Twitter</a>',
                    parse_mode="HTML",
                )
                users[username] = tweet_id
    save_tracked_users()


def search_tweet(update: Update, context: CallbackContext):
    message = update.message.text.strip()
    if not message.startswith("@"):
        update.message.reply_text(
            "Неправильный формат. Используй: @username или @username текст"
        )
        return

    parts = message.split(" ", 1)
    username = parts[0][1:]
    query_text = parts[1] if len(parts) > 1 else ""

    user_id = get_user_id(username)
    if user_id == "RATE_LIMIT":
        update.message.reply_text(
            "⚠️ Превышен лимит запросов к Twitter API. Попробуй позже."
        )
        return
    if not user_id:
        update.message.reply_text("❌ Пользователь не найден или ошибка доступа.")
        return

    headers = {"Authorization": f"Bearer {BEARER_TOKEN}"}
    search_url = "https://api.twitter.com/2/tweets/search/recent"
    query = f"from:{username} {query_text}".strip()
    params = {
        "query": query,
        "max_results": 10,
        "tweet.fields": "created_at",
    }

    r = requests.get(search_url, headers=headers, params=params)
    if r.status_code == 429:
        update.message.reply_text(
            "⚠️ Превышен лимит запросов к Twitter API. Попробуй позже."
        )
        return
    if r.status_code != 200 or "data" not in r.json():
        update.message.reply_text("❌ Не найдено твитов по запросу.")
        return

    tweets = r.json()["data"]
    for tweet in tweets:
        tweet_id = tweet["id"]
        tweet_text = tweet["text"]
        tweet_url = f"https://twitter.com/{username}/status/{tweet_id}"
        update.message.reply_text(
            f'📢 <b>Твит от @{username}</b>\n\n{tweet_text}\n\n🔗 <a href="{tweet_url}">Открыть в Twitter</a>',
            parse_mode="HTML",
        )

    chat_id = str(update.message.chat_id)
    if chat_id not in tracked_users:
        tracked_users[chat_id] = {}
    tracked_users[chat_id][username] = tweets[0]["id"]
    save_tracked_users()


def main():
    updater = Updater(TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("unsubscribe", unsubscribe))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, search_tweet))

    job_queue = updater.job_queue
    job_queue.run_repeating(auto_update, interval=3600, first=10)

    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()