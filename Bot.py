import telebot
from telebot import types
from flask import Flask
import threading

# توکن رباتت رو اینجا بذار
TOKEN = "YOUR_BOT_TOKEN"
bot = telebot.TeleBot(TOKEN)

# ================================
# دستورات و دکمه‌ها
# ================================
@bot.message_handler(commands=['start'])
def start(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("پلن 30 روزه", callback_data="plan30"))
    markup.add(types.InlineKeyboardButton("پلن 60 روزه", callback_data="plan60"))
    markup.add(types.InlineKeyboardButton("پلن 90 روزه", callback_data="plan90"))
    bot.send_message(message.chat.id, "سلام! یکی از پلن‌ها رو انتخاب کن:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    if call.data == "plan30":
        bot.answer_callback_query(call.id, "پلن 30 روزه انتخاب شد ✅")
        bot.send_message(call.message.chat.id, "شما پلن 30 روزه رو انتخاب کردید.")
    elif call.data == "plan60":
        bot.answer_callback_query(call.id, "پلن 60 روزه انتخاب شد ✅")
        bot.send_message(call.message.chat.id, "شما پلن 60 روزه رو انتخاب کردید.")
    elif call.data == "plan90":
        bot.answer_callback_query(call.id, "پلن 90 روزه انتخاب شد ✅")
        bot.send_message(call.message.chat.id, "شما پلن 90 روزه رو انتخاب کردید.")

# ================================
# Flask برای Koyeb
# ================================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    app.run(host="0.0.0.0", port=8080)

# ================================
# اجرای همزمان Bot + Flask
# ================================
def run_bot():
    print("🤖 Bot is running...")
    bot.infinity_polling()

if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    run_bot() 
