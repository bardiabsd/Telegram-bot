import os
import telebot
from flask import Flask, request

# گرفتن توکن ربات و اسم اپ از متغیرهای محیطی
TOKEN = os.environ.get("TOKEN")
APP_NAME = os.environ.get("APP_NAME")

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# 📌 یک دستور تست ساده
@bot.message_handler(commands=["start"])
def start(message):
    bot.reply_to(message, "سلام ✌️ رباتت روی Koyeb با موفقیت فعاله 🚀")

# 📌 این روت برای وبهوک
@app.route(f"/webhook/{TOKEN}", methods=["POST"])
def webhook():
    json_str = request.get_data().decode("UTF-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "ok", 200

# 📌 ست کردن وبهوک
@app.route("/setwebhook", methods=["GET"])
def set_webhook():
    url = f"https://{APP_NAME}.koyeb.app/webhook/{TOKEN}"
    bot.remove_webhook()
    success = bot.set_webhook(url=url)
    if success:
        return f"وبهوک ست شد ✅ \n{url}"
    else:
        return "خطا در ست وبهوک ❌"

# 📌 اجرای سرور
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
