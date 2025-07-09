import sqlite3
import json

DB_PATH = "tracked_users.db"
JSON_PATH = "tracked_users.json"

def migrate():
    try:
        with open(JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Ошибка при чтении JSON: {e}")
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    for username, info in data.items():
        chat_id = info["chat_id"]
        last_tweet_id = info.get("last_tweet_id", "")
        try:
            c.execute("""
                INSERT OR IGNORE INTO tracked (chat_id, username, last_tweet_id)
                VALUES (?, ?, ?)
            """, (chat_id, username.lower(), last_tweet_id))
        except Exception as e:
            print(f"Ошибка при добавлении {username}: {e}")

    conn.commit()
    conn.close()
    print("✅ Миграция завершена!")

if __name__ == "__main__":
    migrate()