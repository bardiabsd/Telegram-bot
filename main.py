import json
import os
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")  # توکن از Secret کویب خونده میشه
STORAGE_FILE = "storage.json"

# ======== توابع کمکی ======== #
def load_data():
    if not os.path.exists(STORAGE_FILE):
        return {"users": {}, "transactions": []}
    with open(STORAGE_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(STORAGE_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_user(user_id):
    data = load_data()
    if str(user_id) not in data["users"]:
        data["users"][str(user_id)] = {"wallet": 0}
        save_data(data)
    return data

# ======== دستورات ======== #
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["💰 کیف پول", "🛒 خرید"], ["📞 پشتیبانی"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("سلام! به ربات خوش اومدی 🌹", reply_markup=reply_markup)

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    data = get_user(user_id)

    text = update.message.text

    if text == "💰 کیف پول":
        wallet = data["users"][str(user_id)]["wallet"]
        await update.message.reply_text(f"موجودی کیف پول شما: {wallet} تومان")

    elif text == "🛒 خرید":
        await update.message.reply_text("در حال حاضر خرید فعال نیست 🙂")

    elif text == "📞 پشتیبانی":
        await update.message.reply_text("برای پشتیبانی به @YourSupport پیام دهید.")

    elif text.startswith("شارژ "):  # مثلا: شارژ 1000
        try:
            amount = int(text.split()[1])
            data["users"][str(user_id)]["wallet"] += amount
            data["transactions"].append({"user": user_id, "amount": amount, "type": "charge"})
            save_data(data)
            await update.message.reply_text(f"✅ کیف پول شما {amount} تومان شارژ شد.")
        except:
            await update.message.reply_text("❌ فرمت شارژ درست نیست. مثلا بفرست: شارژ 1000")

    else:
        await update.message.reply_text("دستور نامعتبر ❌")

# ======== ران ربات ======== #
def main():
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    application.run_polling()

if __name__ == "__main__":
    main()
