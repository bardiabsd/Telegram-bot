import os
import telebot
from flask import Flask, request

TOKEN = os.getenv("BOT_TOKEN")  # توکن ربات
bot = telebot.TeleBot(TOKEN)

app = Flask(__name__)

# روت برای تست سلامت
@app.route("/")
def index():
    return "Bot is running on Koyeb 🚀"

# روت برای ست کردن وبهوک
@app.route("/setwebhook", methods=["GET"])
def set_webhook():
    webhook_url = f"https://{os.getenv('KOYEB_APP_NAME')}.koyeb.app/webhook"
    success = bot.set_webhook(url=webhook_url)
    if success:
        return f"Webhook set to {webhook_url}"
    else:
        return "Webhook setting failed!"

# روت وبهوک
@app.route("/webhook", methods=["POST"])
def webhook():
    if request.headers.get("content-type") == "application/json":
        update = request.get_data().decode("utf-8")
        bot.process_new_updates([telebot.types.Update.de_json(update)])
        return "", 200
    return "Unsupported Media Type", 415

# یک دستور تست
@bot.message_handler(commands=["start"])
def send_welcome(message):
    bot.reply_to(message, "سلام! ربات روی Koyeb بالا اومد 🚀")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000))) 
