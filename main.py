from fastapi import FastAPI
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import os

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "1743359080"))

app = FastAPI()

telegram_app = Application.builder().token(TOKEN).build()

# مثال: دستور /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("سلام ✌️ ربات با موفقیت ران شد!")

telegram_app.add_handler(CommandHandler("start", start))

@app.on_event("startup")
async def startup_event():
    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.updater.start_polling()

@app.on_event("shutdown")
async def shutdown_event():
    await telegram_app.stop() 
