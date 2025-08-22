from telebot import types
import database as db

def main_menu():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📦 خرید پلن", callback_data="buy_plan"))
    markup.add(types.InlineKeyboardButton("🪙 کیف پول", callback_data="wallet"))
    markup.add(types.InlineKeyboardButton("🧾 ارسال رسید", callback_data="receipt"))
    markup.add(types.InlineKeyboardButton("🎫 پشتیبانی", callback_data="support"))
    markup.add(types.InlineKeyboardButton("👤 حساب کاربری", callback_data="profile"))
    return markup

def admin_menu():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📦 مدیریت پلن‌ها", callback_data="admin_plans"))
    markup.add(types.InlineKeyboardButton("🪙 مدیریت کیف پول", callback_data="admin_wallet"))
    markup.add(types.InlineKeyboardButton("🧾 رسیدها و سفارش‌ها", callback_data="admin_receipts"))
    markup.add(types.InlineKeyboardButton("👥 مدیریت کاربران", callback_data="admin_users"))
    markup.add(types.InlineKeyboardButton("🏷 کد تخفیف", callback_data="admin_discounts"))
    markup.add(types.InlineKeyboardButton("📢 اعلان همگانی", callback_data="admin_broadcast"))
    markup.add(types.InlineKeyboardButton("📊 آمار و گزارش‌ها", callback_data="admin_stats"))
    return markup
