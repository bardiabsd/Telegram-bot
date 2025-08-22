from telebot import types

def main_menu():
    """ساخت منوی اصلی ربات"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn1 = types.KeyboardButton("💰 کیف پول")
    btn2 = types.KeyboardButton("⚙️ تنظیمات")
    btn3 = types.KeyboardButton("👤 حساب من")
    btn4 = types.KeyboardButton("📊 گزارش‌ها")
    markup.add(btn1, btn2)
    markup.add(btn3, btn4)
    return markup

def handle_wallet():
    return "💰 موجودی کیف پول شما: 0 تومان"

def handle_settings():
    return "⚙️ اینجا تنظیمات شما خواهد بود."

def handle_account():
    return "👤 اطلاعات حساب شما اینجاست."

def handle_reports():
    return "📊 در آینده گزارش‌ها اینجا نمایش داده می‌شوند."
