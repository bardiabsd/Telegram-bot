import telebot
from flask import Flask, request

# --- توکن رباتت ---
TOKEN = "8339013760:AAEgr1PBFX59xc4cfTN2fWinWJHJUGWivdo"
bot = telebot.TeleBot(TOKEN)

# --- Flask app ---
app = Flask(__name__)

# هندل پیام‌های متنی
@bot.message_handler(func=lambda message: True)
def echo_all(message):
    bot.reply_to(message, f"پیامت رسید ✅\n\nمتن: {message.text}")

# روت برای وبهوک
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    json_str = request.get_data().decode("UTF-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "ok", 200

# روت تست
@app.route("/", methods=["GET"])
def home():
    return "ربات فعاله ✅", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
