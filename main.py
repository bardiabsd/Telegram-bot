import os
import uvicorn
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# گرفتن توکن و آیدی ادمین از env
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 1743359080))

# ساخت اپلیکیشن
app = FastAPI()
application = Application.builder().token(BOT_TOKEN).build()


# دستور /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"سلام {user.first_name} 🌹\n"
        "به ربات خوش اومدی ✨\n"
        "از منوی زیر یکی از گزینه‌ها رو انتخاب کن 👇"
    )


application.add_handler(CommandHandler("start", start))


# هندل کردن وبهوک
@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return {"ok": True}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8080))) 
