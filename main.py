import os
import telebot

# گرفتن توکن از Environment Variables
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise ValueError("❌ Environment variable 'TOKEN' پیدا نشد. لطفاً توی Koyeb ستش کنید.")

bot = telebot.TeleBot(TOKEN)

# دستور start
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "سلام 👋 به ربات من خوش اومدی!")

# دستور help
@bot.message_handler(commands=['help'])
def send_help(message):
    bot.reply_to(message, "دستورات:\n/start - شروع\n/help - راهنما")

# اکوی پیام‌ها (هرچی فرستادی همونو برمی‌گردونه)
@bot.message_handler(func=lambda message: True)
def echo_all(message):
    bot.reply_to(message, f"گفتی: {message.text}")

print("✅ Bot is running...")
bot.infinity_polling()
