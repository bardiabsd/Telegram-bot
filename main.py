import telebot
from flask import Flask, request

TOKEN = "8339013760:AAEgr1PBFX59xc4cfTN2fWinWJHJUGWivdo"  # توکن رباتت
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# هندلر برای پیام‌های متنی
@bot.message_handler(func=lambda message: True)
def echo_all(message):
    bot.reply_to(message, f"پیام شما دریافت شد ✅\n\nمتن: {message.text}")

# روت وبهوک
@app.route("/webhook", methods=["POST"])
def webhook():
    if request.headers.get("content-type") == "application/json":
        json_str = request.get_data().decode("UTF-8")
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return "ok", 200
    else:
        return "unsupported method", 403

# تست صفحه اصلی
@app.route("/", methods=["GET"])
def index():
    return "ربات تلگرام روی Koyeb فعال است ✅", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
