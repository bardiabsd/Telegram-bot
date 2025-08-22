from flask import Flask, request
import telebot
import os

TOKEN = "8339013760:AAEgr1PBFX59xc4cfTN2fWinWJHJUGWivdo"
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# اینجا پیام‌های ورودی رو هندل می‌کنیم
@app.route('/' + TOKEN, methods=['POST'])
def getMessage():
    json_str = request.get_data().decode('UTF-8')
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "!", 200

# فقط برای تست: وقتی پیام /start بیاد جواب بده
@bot.message_handler(commands=['start'])
def start_message(message):
    bot.reply_to(message, "ربات روشنه ✅")

# روت اصلی برای تست وب
@app.route('/')
def webhook():
    return "Bot is running!", 200

if __name__ == "__main__":
    # ست کردن وبهوک (هر بار دیپلوی که شد اجرا میشه)
    bot.remove_webhook()
    bot.set_webhook(url="https://live-avivah-bardiabsd-cd8d676a.koyeb.app/" + TOKEN)
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))
