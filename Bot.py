import telebot
from telebot import types
import sqlite3

# =========================
# تنظیمات
# =========================
TOKEN = "8339013760:AAEgr1PBFX59xc4cfTN2fWinWJHJUGWivdo"
bot = telebot.TeleBot(TOKEN)

# =========================
# دیتابیس
# =========================
def init_db():
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT
                )''')
    conn.commit()
    conn.close()

init_db()

def add_user(user):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user.id,))
    if not c.fetchone():
        c.execute("INSERT INTO users (user_id, username, first_name, last_name) VALUES (?, ?, ?, ?)",
                  (user.id, user.username, user.first_name, user.last_name))
        conn.commit()
    conn.close()

# =========================
# هندلر ها
# =========================
@bot.message_handler(commands=['start'])
def start(message):
    add_user(message.from_user)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn1 = types.KeyboardButton("🛒 خرید پلن")
    btn2 = types.KeyboardButton("📞 پشتیبانی")
    btn3 = types.KeyboardButton("ℹ️ درباره ما")
    markup.add(btn1, btn2, btn3)
    bot.send_message(message.chat.id, "سلام 👋\nبه ربات ما خوش اومدی 🌹", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "🛒 خرید پلن")
def buy_plan(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("پلن ۳۰ روزه - 50,000", callback_data="plan30"))
    markup.add(types.InlineKeyboardButton("پلن ۶۰ روزه - 90,000", callback_data="plan60"))
    markup.add(types.InlineKeyboardButton("پلن ۹۰ روزه - 130,000", callback_data="plan90"))
    bot.send_message(message.chat.id, "📦 لطفا یکی از پلن‌ها رو انتخاب کن:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "📞 پشتیبانی")
def support(message):
    bot.send_message(message.chat.id, "برای پشتیبانی به آیدی زیر پیام بدید:\n@YourSupportID")

@bot.message_handler(func=lambda m: m.text == "ℹ️ درباره ما")
def about(message):
    bot.send_message(message.chat.id, "این ربات برای فروش سرویس‌های ما طراحی شده 🌐")

# =========================
# کال‌بک‌ها
# =========================
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    if call.data == "plan30":
        bot.answer_callback_query(call.id, "پلن ۳۰ روزه انتخاب شد ✅")
        bot.send_message(call.message.chat.id, "لطفا هزینه رو پرداخت کنید و رسید رو بفرستید.")
    elif call.data == "plan60":
        bot.answer_callback_query(call.id, "پلن ۶۰ روزه انتخاب شد ✅")
        bot.send_message(call.message.chat.id, "لطفا هزینه رو پرداخت کنید و رسید رو بفرستید.")
    elif call.data == "plan90":
        bot.answer_callback_query(call.id, "پلن ۹۰ روزه انتخاب شد ✅")
        bot.send_message(call.message.chat.id, "لطفا هزینه رو پرداخت کنید و رسید رو بفرستید.")

# =========================
# اجرا
# =========================
print("🤖 Bot is running...")
bot.infinity_polling()
