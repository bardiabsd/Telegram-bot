import os
import telebot
from flask import Flask, request

TOKEN = os.environ.get("BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)
server = Flask(__name__)

# هندلر برای /start
@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "ربات با موفقیت ران شد ✅")

# وبهوک
@server.route(f"/{TOKEN}", methods=['POST'])
def webhook():
    bot.process_new_updates([telebot.types.Update.de_json(request.stream.read().decode("utf-8"))])
    return "!", 200

# روت اصلی برای چک سلامتی
@server.route("/", methods=['GET'])
def index():
    return "Bot is running!", 200

if __name__ == "__main__":
    server.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))

# برای گونیکورن
app = server
