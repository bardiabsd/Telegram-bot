import os
import telebot
from flask import Flask, request

# توکن ربات از Environment Variable
TOKEN = os.environ.get("BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)

# اپ Flask
server = Flask(__name__)

# هندلر دستور استارت
@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "سلام 👋 ربات روی وبهوک ران شده 🚀")

# مسیر برای دریافت آپدیت‌ها از تلگرام
@server.route('/' + TOKEN, methods=['POST'])
def getMessage():
    json_str = request.get_data().decode('UTF-8')
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "!", 200

# مسیر اصلی برای ست کردن وبهوک
@server.route("/")
def webhook():
    bot.remove_webhook()
    bot.set_webhook(url=f"{os.environ.get('APP_URL')}/{TOKEN}")
    return "Webhook set!", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    server.run(host="0.0.0.0", port=port)
