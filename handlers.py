@bot.message_handler(func=lambda message: True)
def message_handler(message):
    if message.text == "💰 کیف پول":
        bot.send_message(message.chat.id, handlers.handle_wallet(), reply_markup=handlers.main_menu())

    elif message.text == "⚙️ تنظیمات":
        bot.send_message(message.chat.id, handlers.handle_settings(), reply_markup=handlers.main_menu())

    elif message.text == "👤 حساب من":
        bot.send_message(message.chat.id, handlers.handle_account(), reply_markup=handlers.main_menu())

    elif message.text == "📊 گزارش‌ها":
        bot.send_message(message.chat.id, handlers.handle_reports(), reply_markup=handlers.main_menu())

    else:
        bot.send_message(message.chat.id, "سلام 👋 به ربات خوش اومدی!", reply_markup=handlers.main_menu())
