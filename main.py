import logging
import threading
from flask import Flask
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler

# ----------------- تنظیمات -----------------
TOKEN = "8339013760:AAEgr1PBFX59xc4cfTN2fWinWJHJUGWivdo"
PORT = 8000

# ----------------- وب سرور -----------------
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running ✅"

def run_flask():
    app.run(host="0.0.0.0", port=PORT)

# ----------------- ربات تلگرام -----------------
logging.basicConfig(level=logging.INFO)

def start(update, context):
    update.message.reply_text("سلام! ربات روشنه ✅")

def help_cmd(update, context):
    update.message.reply_text("دستورات: /start - /help")

def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    # دستورات
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_cmd))

    # شروع ربات
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    # اجرای Flask در یک Thread جدا
    threading.Thread(target=run_flask).start()
    main()
