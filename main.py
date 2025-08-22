import os
from flask import Flask, request
import telebot

# گرفتن توکن از Environment Variables
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("❌ BOT_TOKEN در محیط تعریف نشده!")

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# هندلر دکمه استارت
@bot.message_handler(commands=['start'])
def start(message):
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("💰 کیف پول", "⚙️ تنظیمات")
    markup.row("📊 گزارش‌ها", "👤 حساب من")
    bot.send_message(message.chat.id, "سلام 👋 به ربات خوش اومدی!", reply_markup=markup)

# وبهوک
@app.route('/' + TOKEN, methods=['POST'])
def webhook():
    update = request.stream.read().decode("utf-8")
    bot.process_new_updates([telebot.types.Update.de_json(update)])
    return "!", 200

@app.route("/")
def index():
    return "ربات فعاله ✅", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
