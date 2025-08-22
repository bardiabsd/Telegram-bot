from flask import Flask, request
import telebot

API_TOKEN = "8339013760:AAEgr1PBFX59xc4cfTN2fWinWJHJUGWivdo"
bot = telebot.TeleBot(API_TOKEN)
app = Flask(__name__)

@app.route("/webhook", methods=["POST"])
def webhook():
    json_str = request.get_data().decode("UTF-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "ok", 200

@bot.message_handler(commands=["start"])
def send_welcome(message):
    bot.reply_to(message, "سلام! ربات فعاله ✅")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
