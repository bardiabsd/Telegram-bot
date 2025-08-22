from telegram.ext import Application, CommandHandler
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base  # فایل مدل‌هایی که ساختیم (users, wallet و غیره)

import os

TOKEN = os.getenv("BOT_TOKEN")  # توکن از Environment گرفته بشه

# تنظیمات دیتابیس
engine = create_engine("sqlite:///bot_database.db")
Session = sessionmaker(bind=engine)

# اینجا دیتابیس رو می‌سازه اگه وجود نداشته باشه
Base.metadata.create_all(engine)


# نمونه هندلر تست
async def start(update, context):
    await update.message.reply_text("سلام! دیتابیس آماده‌ست ✅")

def main():
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))

    application.run_polling()

if __name__ == "__main__":
    main()
