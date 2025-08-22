from flask import Flask
import telebot
import threading
import os

# گرفتن توکن از Environment Variables
TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)

# ساخت اپ Flask برای health check
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ Bot is running on Koyeb!"

# هندلر ساده برای تست
@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "سلام! ربات روشنه 🎉")

# اجرای ربات روی یک thread جدا
def run_bot():
    bot.polling(none_stop=True)

if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    app.run(host="0.0.0.0", port=8000)
