import telebot
from telebot import types
import sqlite3
import os

# گرفتن توکن از متغیر محیطی (Koyeb -> Settings -> Environment variables)
TOKEN = os.getenv("TOKEN")

bot = telebot.TeleBot(TOKEN)

# ================== دیتابیس ==================
def init_db():
    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()

    # جدول کاربران
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER UNIQUE,
        wallet REAL DEFAULT 0
    )
    """)

    # جدول سفارش‌ها
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        service TEXT,
        status TEXT
    )
    """)

    # جدول تیکت‌ها
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        message TEXT,
        status TEXT DEFAULT 'open'
    )
    """)

    # جدول کد تخفیف
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS discounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT,
        percent INTEGER,
        expire_date TEXT
    )
    """)

    conn.commit()
    conn.close()

# ================== دستورات ربات ==================
@bot.message_handler(commands=["start"])
def start(message):
    user_id = message.from_user.id

    # ثبت کاربر اگه جدید بود
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

# ================== اجرای ربات ==================
if __name__ == "__main__":
    init_db()
    bot.polling(none_stop=True)
