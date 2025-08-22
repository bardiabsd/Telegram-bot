import telebot
from flask import Flask, request

TOKEN = "8339013760:AAEgr1PBFX59xc4cfTN2fWinWJHJUGWivdo"
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# وقتی کاربر /start بزند
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "سلام! 👋 ربات روشنه ✅")

# وبهوک
@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.get_json()
    if update:
        print(update)  # لاگ برای تست
        bot.process_new_updates([telebot.types.Update.de_json(update)])
    return "OK", 200

@app.route('/')
def index():
    return "ربات تلگرام فعال است ✅", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
