import os
import logging
from flask import Flask, request
from telegram import Bot, Update
from telegram.ext import Dispatcher, CommandHandler, MessageHandler, Filters

TOKEN = "8339013760:AAEgr1PBFX59xc4cfTN2fWinWJHJUGWivdo"
URL = "https://live-avivah-bardiabsd-cd8d676a.koyeb.app"   # لینک Koyeb

# لاگ‌ها برای دیباگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

app = Flask(__name__)
bot = Bot(token=TOKEN)

# دیسپچر برای هندلرها
dispatcher = Dispatcher(bot, None, workers=0)

# دستور /start
def start(update: Update, context):
    update.message.reply_text("ربات روی Koyeb ران شد 🚀")

# پیام‌های عادی
def echo(update: Update, context):
    update.message.reply_text(update.message.text)

# ثبت هندلرها
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, echo))


@app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return "ok"


@app.route('/')
def index():
    return "ربات فعاله ✅"


if __name__ == "__main__":
    # ست کردن وبهوک
    bot.set_webhook(f"{URL}/{TOKEN}")
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))
