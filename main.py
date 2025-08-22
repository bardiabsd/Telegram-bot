import telebot
from flask import Flask, request
import threading
import os

# --- Bot Token ---
TOKEN = os.getenv("BOT_TOKEN")  # بهتره از Environment Variable استفاده کنی
bot = telebot.TeleBot(TOKEN)

# --- Flask App ---
app = Flask(__name__)

# Telegram webhook endpoint
@app.route("/" + TOKEN, methods=["POST"])
def getMessage():
    json_str = request.get_data().decode("UTF-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "!", 200

@app.route("/")
def webhook():
    bot.remove_webhook()
    bot.set_webhook(url="https://YOUR-KOYEB-APP-URL/" + TOKEN)  # اینجا آدرس کویب رو بذار
    return "Webhook set!", 200

# --- Bot Handlers ---
@bot.message_handler(commands=["start"])
def start_message(message):
    bot.reply_to(message, "سلام 🌹 ربات روشنه و درست کار می‌کنه ✅")

# --- Run Bot in Thread ---
def run_bot():
    bot.infinity_polling()

if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    app.run(host="0.0.0.0", port=8000)
