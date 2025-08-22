from flask import Flask, request
import telegram

# --------------------
# تنظیمات
# --------------------
TOKEN = "8339013760:AAEgr1PBFX59xc4cfTN2fWinWJHJUGWivdo"
bot = telegram.Bot(token=TOKEN)

app = Flask(__name__)

# --------------------
# روت وبهوک
# --------------------
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json(force=True)
    update = telegram.Update.de_json(data, bot)

    if update.message:  # اگه پیام متنی بود
        chat_id = update.message.chat.id
        text = update.message.text

        # جواب ساده
        bot.send_message(chat_id=chat_id, text=f"پیام گرفتم: {text}")

    return "ok", 200

# --------------------
# تست ساده (برای چک سالم بودن)
# --------------------
@app.route('/')
def home():
    return "Bot is running!", 200

# --------------------
# اجرای اپ (لوکال تست)
# --------------------
if __name__ == '__main__':
    app.run(host="0.0.0.0", port=8000)
