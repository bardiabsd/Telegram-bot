import telebot
from telebot import types
import sqlite3
import os
from flask import Flask, request

TOKEN = os.getenv("TOKEN")
APP_NAME = os.getenv("APP_NAME")  # مثلا mybotapp
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# ================== دیتابیس ==================
def init_db():
    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER UNIQUE,
        wallet REAL DEFAULT 0
    )
    """)
    conn.commit()
    conn.close()

# ================== دستورات ربات ==================
@bot.message_handler(commands=["start"])
def start(message):
    user_id = message.from_user.id
    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("🛒 ثبت سفارش", "💳 کیف پول")
    markup.row("🎟 کد تخفیف", "📩 تیکت پشتیبانی")

    bot.send_message(
        message.chat.id,
        "سلام 👋 به ربات خوش اومدی!\n\nاز منوی زیر یکی رو انتخاب کن:",
        reply_markup=markup
    )

# ====== کیف پول ======
@bot.message_handler(func=lambda m: m.text == "💳 کیف پول")
def wallet(message):
    user_id = message.from_user.id
    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT wallet FROM users WHERE user_id=?", (user_id,))
    wallet_balance = cursor.fetchone()[0]
    conn.close()

    bot.send_message(message.chat.id, f"موجودی کیف پول شما: 💰 {wallet_balance} تومان")

# ================== وبهوک ==================
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    json_str = request.get_data().decode("UTF-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "!", 200

@app.route("/")
def index():
    return "Bot is running!", 200

if __name__ == "__main__":
    init_db()
    bot.remove_webhook()
    bot.set_webhook(url=f"https://{APP_NAME}.koyeb.app/{TOKEN}")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000))) 
