# -*- coding: utf-8 -*-
# Telegram Shop Bot – Full Version (Flask + Webhook + PyTelegramBotAPI + SQLAlchemy)
# Author: you 🤝
#
# ⛳️ خلاصه امکانات:
# - خرید پلن با موجودی مخزن (متن + عکس)، کد تخفیف، پرداخت با کیف پول/کارت‌به‌کارت
# - کیف پول با تراکنش‌ها، شارژ، «شارژ همین مقدار» در خرید
# - رسیدها: ثبت/نمایش برای کاربر + اینباکس ادمین، تأیید/رد
# - تیکت پشتیبانی (ترد)، حساب کاربری و سفارش‌ها
# - پنل ادمین: مدیریت پلن‌ها، مخزن، کد تخفیف، کاربران، اعلان همگانی، گزارش‌ها
# - نوتیف انقضا: مسیر کران /cron/<secret> برای یادآوری 3 روز مانده
#
# ⚙️ نکته: برای سادگی Stateهای موقت در حافظه‌اند؛ موارد مهم در DB ذخیره می‌شوند.

import os
import json
import logging
from datetime import datetime, timedelta
from io import BytesIO
from collections import defaultdict

from flask import Flask, request, abort

import telebot
from telebot import types

from sqlalchemy import (create_engine, Column, Integer, String, Boolean, DateTime,
                        Text, ForeignKey, func)
from sqlalchemy.orm import sessionmaker, declarative_base, relationship

# =========[ تنظیمات ]=========
TOKEN = "8339013760:AAEgr1PBFX59xc4cfTN2fWinWJHJUGWivdo"  # توکن شما (طبق درخواستی که دادی جایگزین شد)
WEBHOOK_PATHS = ["/webhook", f"/webhook/{TOKEN}"]          # هرکدام ست شده باشد کار می‌کند
ADMIN_IDS = {5790904709}  # 👈 آیدی‌های عددی ادمین‌ها (می‌تونی اضافه/حذف کنی، داخل بات هم دستور داره)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_URL = f"sqlite:///{os.path.join(BASE_DIR, 'data.db')}"
CRON_SECRET = os.environ.get("CRON_SECRET", "cron123")  # برای مسیر /cron/<secret>
PORT = int(os.environ.get("PORT", 8080))

# دامنه‌ی Koyeb (برای اطلاعات): نیازی به ست‌کردن در کد نیست چون وبهوک را دستی ست می‌کنی
# نمونه وبهوک فعال فعلی: https://live-avivah-bardiabsd-cd8d676a.koyeb.app/webhook

# =========[ لاگینگ ]=========
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot")

# =========[ DB ]=========
Base = declarative_base()
engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
Session = sessionmaker(bind=engine)

# ---- مدل‌ها
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    tg_id = Column(Integer, unique=True, index=True, nullable=False)
    username = Column(String(64))
    first_name = Column(String(128))
    is_banned = Column(Boolean, default=False)
    wallet = Column(Integer, default=0)  # تومان
    created_at = Column(DateTime, default=datetime.utcnow)

    orders = relationship("Order", back_populates="user")
    txs = relationship("WalletTx", back_populates="user")

class Plan(Base):
    __tablename__ = "plans"
    id = Column(Integer, primary_key=True)
    name = Column(String(64), nullable=False)
    days = Column(Integer, default=30)
    volume_gb = Column(Integer, default=0)  # می‌تونی صفر بذاری اگر پلن حجمی نیست
    price = Column(Integer, default=0)      # تومان
    desc = Column(Text, default="")
    active = Column(Boolean, default=True)

    items = relationship("InventoryItem", back_populates="plan")
    orders = relationship("Order", back_populates="plan")

class InventoryItem(Base):
    __tablename__ = "inventory_items"
    id = Column(Integer, primary_key=True)
    plan_id = Column(Integer, ForeignKey("plans.id"))
    text = Column(Text, default="")
    photo_id = Column(String(256))  # file_id تلگرام
    used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    used_order_id = Column(Integer, ForeignKey("orders.id"))

    plan = relationship("Plan", back_populates="items")

class Coupon(Base):
    __tablename__ = "coupons"
    id = Column(Integer, primary_key=True)
    code = Column(String(64), unique=True, index=True)
    percent = Column(Integer, default=0)  # 10 یعنی 10%
    only_plan_id = Column(Integer, ForeignKey("plans.id"), nullable=True)  # None = همه پلن‌ها
    expires_at = Column(DateTime, nullable=True)
    use_limit = Column(Integer, default=0)   # 0 = بدون محدودیت
    used_count = Column(Integer, default=0)
    active = Column(Boolean, default=True)

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    plan_id = Column(Integer, ForeignKey("plans.id"))
    price_paid = Column(Integer, default=0)
    coupon_code = Column(String(64))
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)
    config_text = Column(Text, default="")
    config_photo_id = Column(String(256))
    expiry_notified = Column(Boolean, default=False)

    user = relationship("User", back_populates="orders")
    plan = relationship("Plan", back_populates="orders")

class WalletTx(Base):
    __tablename__ = "wallet_txs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    amount = Column(Integer, default=0)  # تومان؛ مثبت=افزایش، منفی=کسر
    kind = Column(String(32))            # charge / purchase / adjust
    note = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="txs")

class Receipt(Base):
    __tablename__ = "receipts"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    status = Column(String(16), default="pending")  # pending/approved/rejected
    kind = Column(String(16), default="wallet")     # wallet/purchase/topup_for_purchase
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=True)
    expected_amount = Column(Integer, default=0)    # برای خرید/شارژِ هدف‌دار
    amount_confirmed = Column(Integer, default=0)
    file_id = Column(String(256))
    file_type = Column(String(16))                  # photo/document/text
    caption = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    admin_id = Column(Integer, nullable=True)
    reject_reason = Column(Text, default="")

class Ticket(Base):
    __tablename__ = "tickets"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    subject = Column(String(128))
    status = Column(String(16), default="open")     # open/closed
    created_at = Column(DateTime, default=datetime.utcnow)

class TicketMsg(Base):
    __tablename__ = "ticket_msgs"
    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"))
    sender = Column(String(16))  # user/admin
    text = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

class Admin(Base):
    __tablename__ = "admins"
    id = Column(Integer, primary_key=True)
    tg_id = Column(Integer, unique=True, index=True)

Base.metadata.create_all(engine)

# =========[ BOT/WEB ]=========
bot = telebot.TeleBot(TOKEN, parse_mode="HTML")
app = Flask(__name__)

# Stateهای کوتاه‌مدت در حافظه (ایمن برای دیپلوی ساده)
user_state = defaultdict(dict)   # user_state[user_id] = {...}
admin_state = defaultdict(dict)

# =========[ ابزارک‌ها ]=========
def money(n):
    return f"{n:,} تومان"

def get_user(session, tg_user):
    u = session.query(User).filter_by(tg_id=tg_user.id).first()
    if not u:
        u = User(
            tg_id=tg_user.id,
            username=tg_user.username or "",
            first_name=tg_user.first_name or "",
        )
        session.add(u)
        session.commit()
    return u

def is_admin(tg_id):
    # هم از لیست ثابت و هم از جدول
    if tg_id in ADMIN_IDS:
        return True
    with Session() as s:
        return bool(s.query(Admin).filter_by(tg_id=tg_id).first())

def stock_count(session, plan_id):
    return session.query(InventoryItem).filter_by(plan_id=plan_id, used=False).count()

def apply_coupon(session, plan_id, price, code):
    if not code:
        return price, None, "بدون کد تخفیف"
    c = session.query(Coupon).filter(func.lower(Coupon.code) == code.lower()).first()
    if not c or not c.active:
        return price, None, "کد نامعتبر است."
    if c.expires_at and c.expires_at < datetime.utcnow():
        return price, None, "کد منقضی شده است."
    if c.only_plan_id and c.only_plan_id != plan_id:
        return price, None, "این کد مخصوص پلن دیگری است."
    if c.use_limit and c.used_count >= c.use_limit:
        return price, None, "سقف استفاده این کد تکمیل شده است."
    new_price = max(0, round(price * (100 - c.percent) / 100))
    return new_price, c, f"کد اعمال شد: {c.percent}% تخفیف"

def main_menu_kb(is_admin_user=False):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("📦 خرید پلن", "🪙 کیف پول")
    kb.row("🧾 رسیدها", "🎫 تیکت پشتیبانی")
    kb.row("👤 حساب کاربری")
    if is_admin_user:
        kb.row("🛠 پنل ادمین")
    return kb

def back_btn():
    m = types.InlineKeyboardMarkup()
    m.add(types.InlineKeyboardButton("⬅️ بازگشت", callback_data="back:home"))
    return m

# =========[ دستورات عمومی ]=========
@bot.message_handler(commands=["start"])
def cmd_start(msg):
    with Session() as s:
        u = get_user(s, msg.from_user)
        if u.is_banned:
            bot.reply_to(msg, "اکانت شما مسدود است.")
            return
    text = (
        "سلام! 👋\n"
        "به ربات فروش خوش آمدید.\n"
        "از منوی زیر انتخاب کنید:"
    )
    bot.send_message(msg.chat.id, text, reply_markup=main_menu_kb(is_admin(msg.from_user.id)))

@bot.message_handler(func=lambda m: m.text == "📦 خرید پلن")
def buy_plans(msg):
    with Session() as s:
        lines = ["<b>لیست پلن‌ها</b>"]
        kb = types.InlineKeyboardMarkup()
        for p in s.query(Plan).filter_by(active=True).all():
            sc = stock_count(s, p.id)
            title = f"{p.name} – {money(p.price)} | موجودی: {sc}"
            if sc == 0:
                kb.add(types.InlineKeyboardButton(f"❌ {title}", callback_data="noop"))
            else:
                kb.add(types.InlineKeyboardButton(title, callback_data=f"plan:{p.id}"))
        kb.add(types.InlineKeyboardButton("بازگشت", callback_data="back:home"))
        bot.send_message(msg.chat.id, "\n".join(lines), reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "noop")
def cb_noop(c):
    bot.answer_callback_query(c.id, "ناموجود است")

@bot.callback_query_handler(func=lambda c: c.data.startswith("back:"))
def cb_back(c):
    if c.data == "back:home":
        bot.edit_message_text("بازگشت به منو.", c.message.chat.id, c.message.message_id)
        bot.send_message(c.message.chat.id, "منو:", reply_markup=main_menu_kb(is_admin(c.from_user.id)))

@bot.callback_query_handler(func=lambda c: c.data.startswith("plan:"))
def cb_plan(c):
    plan_id = int(c.data.split(":")[1])
    with Session() as s:
        p = s.query(Plan).get(plan_id)
        if not p or not p.active:
            bot.answer_callback_query(c.id, "پلن در دسترس نیست")
            return
        sc = stock_count(s, plan_id)
        if sc == 0:
            bot.answer_callback_query(c.id, "موجودی تمام شده ❌")
            return
        # نگه داشتن انتخاب کاربر
        user_state[c.from_user.id] = {"plan_id": plan_id, "coupon": None}
        text = (
            f"<b>{p.name}</b>\n"
            f"مدت: {p.days} روز | حجم: {p.volume_gb} گیگ\n"
            f"قیمت: {money(p.price)}\n\n"
            f"{p.desc or ''}\n\n"
            "می‌تونی روش پرداخت رو انتخاب کنی یا کد تخفیف اعمال کنی:"
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🏷 اعمال/حذف کد تخفیف", callback_data="coupon:ask"))
        kb.row(
            types.InlineKeyboardButton("💳 کارت‌به‌کارت", callback_data="pay:card"),
            types.InlineKeyboardButton("🪙 پرداخت با کیف پول", callback_data="pay:wallet")
        )
        kb.add(types.InlineKeyboardButton("انصراف", callback_data="back:home"))
        bot.edit_message_text(text, c.message.chat.id, c.message.message_id, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "coupon:ask")
def cb_coupon_ask(c):
    st = user_state.get(c.from_user.id, {})
    if not st.get("plan_id"):
        bot.answer_callback_query(c.id, "ابتدا پلن را انتخاب کنید")
        return
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "کد تخفیف را بفرستید (یا /cancel):")
    user_state[c.from_user.id]["await_coupon"] = True

@bot.message_handler(commands=["cancel"])
def cmd_cancel(msg):
    if user_state.get(msg.from_user.id):
        user_state[msg.from_user.id].pop("await_coupon", None)
        user_state[msg.from_user.id].pop("await_receipt", None)
        admin_state[msg.from_user.id].clear()
    bot.reply_to(msg, "لغو شد.", reply_markup=main_menu_kb(is_admin(msg.from_user.id)))

@bot.message_handler(func=lambda m: user_state.get(m.from_user.id, {}).get("await_coupon"))
def on_coupon(msg):
    code = (msg.text or "").strip()
    st = user_state[msg.from_user.id]
    with Session() as s:
        p = s.query(Plan).get(st["plan_id"])
        final, cpn, msgtxt = apply_coupon(s, p.id, p.price, code)
        if cpn:
            st["coupon"] = cpn.code
        else:
            st["coupon"] = None
        text = (
            f"{msgtxt}\n"
            f"قیمت قبل: {money(p.price)}\n"
            f"قیمت بعد:  {money(final)}"
        )
        bot.reply_to(msg, text)
    st.pop("await_coupon", None)

@bot.callback_query_handler(func=lambda c: c.data in ("pay:card", "pay:wallet"))
def cb_pay(c):
    st = user_state.get(c.from_user.id, {})
    if not st.get("plan_id"):
        bot.answer_callback_query(c.id, "ابتدا پلن را انتخاب کنید")
        return
    with Session() as s:
        p = s.query(Plan).get(st["plan_id"])
        final, cpn, _ = apply_coupon(s, p.id, p.price, st.get("coupon"))
        if c.data == "pay:wallet":
            u = get_user(s, c.from_user)
            if u.wallet >= final:
                # پرداخت و ارسال
                u.wallet -= final
                s.add(WalletTx(user_id=u.id, amount=-final, kind="purchase", note=f"خرید پلن {p.name}"))
                # انتخاب کانفیگ از مخزن
                item = s.query(InventoryItem).filter_by(plan_id=p.id, used=False).order_by(InventoryItem.id.asc()).first()
                if not item:
                    bot.answer_callback_query(c.id, "متأسفانه موجودی همین الان صفر شد.")
                    s.commit()
                    return
                item.used = True
                order = Order(
                    user_id=u.id, plan_id=p.id, price_paid=final, coupon_code=st.get("coupon") or "",
                    created_at=datetime.utcnow(), expires_at=datetime.utcnow()+timedelta(days=p.days),
                    config_text=item.text or "", config_photo_id=item.photo_id or ""
                )
                s.add(order)
                s.commit()
                # ارسال به کاربر
                send_config(c.message.chat.id, item)
                bot.answer_callback_query(c.id, "خرید با کیف پول انجام شد ✅")
                bot.edit_message_text("خرید موفق. کانفیگ ارسال شد.", c.message.chat.id, c.message.message_id)
            else:
                need = final - u.wallet
                kb = types.InlineKeyboardMarkup()
                kb.add(types.InlineKeyboardButton(f"شارژ همین مقدار ({money(need)})", callback_data=f"topup_need:{need}:{p.id}:{final}:{st.get('coupon') or ''}"))
                bot.answer_callback_query(c.id)
                bot.send_message(c.message.chat.id, f"موجودی کافی نیست.\nکمبود: {money(need)}", reply_markup=kb)
        else:
            # کارت‌به‌کارت → درخواست رسید
            bot.answer_callback_query(c.id)
            bot.send_message(c.message.chat.id,
                             f"لطفاً رسید پرداخت ({money(final)}) را ارسال کنید. سپس توسط ادمین تأیید می‌شود.",
                             reply_markup=back_btn())
            st["await_receipt"] = {"kind": "purchase", "plan_id": p.id, "expected": final, "coupon": st.get("coupon")})

def send_config(chat_id, item: InventoryItem):
    if item.photo_id:
        bot.send_photo(chat_id, item.photo_id, caption=item.text or "کانفیگ شما:")
    else:
        bot.send_message(chat_id, item.text or "کانفیگ شما:")

@bot.callback_query_handler(func=lambda c: c.data.startswith("topup_need:"))
def cb_topup_need(c):
    _, need, plan_id, final, coupon = c.data.split(":")
    need, plan_id, final = int(need), int(plan_id), int(final)
    st = user_state[c.from_user.id] = {"await_receipt": {
        "kind": "topup_for_purchase",
        "need": need,
        "plan_id": plan_id,
        "final": final,
        "coupon": (coupon or None)
    }}
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, f"لطفاً رسید کارت‌به‌کارت برای {money(need)} را ارسال کنید.", reply_markup=back_btn())

# دریافت رسید از کاربر
@bot.message_handler(content_types=["photo", "document", "text"], func=lambda m: user_state.get(m.from_user.id, {}).get("await_receipt"))
def on_user_receipt(msg):
    st = user_state[msg.from_user.id]["await_receipt"]
    with Session() as s:
        u = get_user(s, msg.from_user)
        # استخراج فایل
        f_id, f_type, caption = None, None, (msg.caption or msg.text or "")
        if msg.photo:
            f_id, f_type = msg.photo[-1].file_id, "photo"
        elif msg.document:
            f_id, f_type = msg.document.file_id, "document"
        else:
            f_id, f_type = None, "text"

        r = Receipt(
            user_id=u.id,
            status="pending",
            kind=st["kind"],
            plan_id=st.get("plan_id"),
            expected_amount=st.get("expected", st.get("need", 0)),
            file_id=f_id or "",
            file_type=f_type,
            caption=caption
        )
        s.add(r); s.commit()
        bot.reply_to(msg, "رسید شما ثبت شد؛ منتظر تأیید ادمین… 🔔")

        # ارسال به ادمین‌ها
        for adm in list(ADMIN_IDS) + [a.tg_id for a in s.query(Admin).all()]:
            try:
                text = (f"🧾 رسید جدید #{r.id}\n"
                        f"کاربر: @{u.username or '-'} ({u.tg_id})\n"
                        f"نوع: {r.kind}\n"
                        f"مبلغ/انتظار: {money(r.expected_amount)}\n"
                        f"پلن: {r.plan_id or '-'}\n"
                        f"شرح: {r.caption or '-'}")
                kb = types.InlineKeyboardMarkup()
                if r.kind in ("wallet", "topup_for_purchase"):
                    kb.add(types.InlineKeyboardButton("✅ تأیید (وارد کردن مبلغ)", callback_data=f"rcpt:approve_amount:{r.id}"))
                else:
                    kb.add(types.InlineKeyboardButton("✅ تأیید خرید", callback_data=f"rcpt:approve:{r.id}"))
                kb.add(types.InlineKeyboardButton("❌ رد رسید", callback_data=f"rcpt:reject:{r.id}"))
                if f_type == "photo":
                    bot.send_photo(adm, f_id, caption=text, reply_markup=kb)
                elif f_type == "document":
                    bot.send_document(adm, f_id, caption=text, reply_markup=kb)
                else:
                    bot.send_message(adm, text, reply_markup=kb)
            except Exception as e:
                log.warning(f"Send to admin failed: {e}")

        # پاک کردن انتظار
        user_state[msg.from_user.id].pop("await_receipt", None)
        s.commit()

# ========== [ کیف پول ] ==========
@bot.message_handler(func=lambda m: m.text == "🪙 کیف پول")
def wallet_menu(msg):
    with Session() as s:
        u = get_user(s, msg.from_user)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("➕ شارژ کیف پول", callback_data="wallet:charge"))
        kb.add(types.InlineKeyboardButton("📜 تاریخچه تراکنش‌ها", callback_data="wallet:history"))
        bot.send_message(msg.chat.id, f"موجودی فعلی: <b>{money(u.wallet)}</b>", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "wallet:charge")
def cb_wallet_charge(c):
    user_state[c.from_user.id]["await_receipt"] = {"kind": "wallet"}
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "رسید شارژ کیف پول را ارسال کنید.", reply_markup=back_btn())

@bot.callback_query_handler(func=lambda c: c.data == "wallet:history")
def cb_wallet_history(c):
    with Session() as s:
        u = s.query(User).filter_by(tg_id=c.from_user.id).first()
        txs = s.query(WalletTx).filter_by(user_id=u.id).order_by(WalletTx.id.desc()).limit(15).all()
        if not txs:
            bot.answer_callback_query(c.id)
            bot.send_message(c.message.chat.id, "هیچ تراکنشی ثبت نشده.")
            return
        lines = ["<b>تاریخچه کیف پول</b>"]
        for t in txs:
            sign = "+" if t.amount > 0 else ""
            lines.append(f"{t.created_at:%Y-%m-%d %H:%M} | {sign}{money(t.amount)} | {t.kind}")
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id, "\n".join(lines))

# ========== [ رسیدهای من ] ==========
@bot.message_handler(func=lambda m: m.text == "🧾 رسیدها")
def my_receipts(msg):
    with Session() as s:
        u = get_user(s, msg.from_user)
        rs = s.query(Receipt).filter_by(user_id=u.id).order_by(Receipt.id.desc()).limit(10).all()
        if not rs:
            bot.send_message(msg.chat.id, "رسیدی ندارید.")
            return
        lines = ["<b>رسیدهای اخیر</b>"]
        for r in rs:
            lines.append(f"#{r.id} | {r.kind} | {r.status} | {money(r.expected_amount)} | {r.created_at:%Y-%m-%d}")
        bot.send_message(msg.chat.id, "\n".join(lines))

# ========== [ تیکت پشتیبانی ] ==========
@bot.message_handler(func=lambda m: m.text == "🎫 تیکت پشتیبانی")
def ticket_menu(msg):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("ایجاد تیکت جدید", callback_data="ticket:new"))
    kb.add(types.InlineKeyboardButton("تیکت‌های من", callback_data="ticket:list"))
    bot.send_message(msg.chat.id, "پشتیبانی:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "ticket:new")
def cb_ticket_new(c):
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "موضوع تیکت را بفرستید (یا /cancel):")
    user_state[c.from_user.id]["await_ticket_subject"] = True

@bot.message_handler(func=lambda m: user_state.get(m.from_user.id, {}).get("await_ticket_subject"))
def on_ticket_subject(msg):
    subj = msg.text.strip()
    with Session() as s:
        u = get_user(s, msg.from_user)
        t = Ticket(user_id=u.id, subject=subj, status="open")
        s.add(t); s.commit()
        s.add(TicketMsg(ticket_id=t.id, sender="user", text="(شروع تیکت)"))
        s.commit()
        bot.reply_to(msg, f"تیکت #{t.id} ایجاد شد. پیامت را بفرست.")
        user_state[msg.from_user.id] = {"ticket_reply_to": t.id}

@bot.message_handler(func=lambda m: user_state.get(m.from_user.id, {}).get("ticket_reply_to"))
def on_ticket_message(msg):
    tid = user_state[msg.from_user.id]["ticket_reply_to"]
    with Session() as s:
        u = get_user(s, msg.from_user)
        t = s.query(Ticket).get(tid)
        if not t or t.status == "closed":
            bot.reply_to(msg, "این تیکت بسته است.")
            user_state[msg.from_user.id].pop("ticket_reply_to", None)
            return
        s.add(TicketMsg(ticket_id=t.id, sender="user", text=msg.text))
        s.commit()
        bot.reply_to(msg, "پیام شما ثبت شد.")
        # ارسال به ادمین‌ها
        for adm in list(ADMIN_IDS) + [a.tg_id for a in s.query(Admin).all()]:
            try:
                kb = types.InlineKeyboardMarkup()
                kb.add(types.InlineKeyboardButton(f"پاسخ به تیکت #{t.id}", callback_data=f"ticket:reply:{t.id}:{u.tg_id}"))
                bot.send_message(adm, f"پیام جدید تیکت #{t.id} از {u.tg_id}:\n{subj_or('','')}{msg.text}", reply_markup=kb)
            except: pass

def subj_or(a, b): return a or b

@bot.callback_query_handler(func=lambda c: c.data.startswith("ticket:reply:"))
def cb_ticket_reply(c):
    _, _, tid, user_tg = c.data.split(":")
    admin_state[c.from_user.id] = {"reply_ticket": int(tid), "user_tg": int(user_tg)}
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, f"پاسخ خود را برای تیکت #{tid} بفرستید:")

@bot.message_handler(func=lambda m: admin_state.get(m.from_user.id, {}).get("reply_ticket"))
def on_admin_ticket_reply(msg):
    st = admin_state[msg.from_user.id]
    tid, user_tg = st["reply_ticket"], st["user_tg"]
    with Session() as s:
        s.add(TicketMsg(ticket_id=tid, sender="admin", text=msg.text)); s.commit()
    bot.send_message(user_tg, f"پاسخ پشتیبانی به تیکت #{tid}:\n{msg.text}")
    bot.reply_to(msg, "ارسال شد.")
    admin_state[msg.from_user.id].clear()

@bot.callback_query_handler(func=lambda c: c.data == "ticket:list")
def cb_ticket_list(c):
    with Session() as s:
        u = s.query(User).filter_by(tg_id=c.from_user.id).first()
        ts = s.query(Ticket).filter_by(user_id=u.id).order_by(Ticket.id.desc()).limit(10).all()
        if not ts:
            bot.send_message(c.message.chat.id, "تیکتی ندارید.")
            return
        lines = ["<b>تیکت‌های شما</b>"]
        for t in ts:
            lines.append(f"#{t.id} | {t.subject} | {t.status} | {t.created_at:%Y-%m-%d}")
        bot.send_message(c.message.chat.id, "\n".join(lines))

# ========== [ حساب کاربری ] ==========
@bot.message_handler(func=lambda m: m.text == "👤 حساب کاربری")
def account(msg):
    with Session() as s:
        u = get_user(s, msg.from_user)
        cnt = s.query(Order).filter_by(user_id=u.id).count()
        lines = [
            "<b>حساب کاربری</b>",
            f"ID: <code>{u.tg_id}</code>",
            f"Username: @{u.username or '-'}",
            f"تعداد کانفیگ‌های خریداری شده: {cnt}",
            f"موجودی کیف پول: {money(u.wallet)}",
            "",
            "سفارش‌های من (10 مورد اخیر):"
        ]
        orders = s.query(Order).filter_by(user_id=u.id).order_by(Order.id.desc()).limit(10).all()
        for o in orders:
            lines.append(f"#{o.id} | {o.plan.name} | {money(o.price_paid)} | تا {o.expires_at:%Y-%m-%d}")
        bot.send_message(msg.chat.id, "\n".join(lines))

# ========== [ ادمین: اینباکس رسید ] ==========
@bot.callback_query_handler(func=lambda c: c.data.startswith("rcpt:"))
def cb_receipt_admin(c):
    with Session() as s:
        if not is_admin(c.from_user.id):
            bot.answer_callback_query(c.id, "دسترسی ندارید.")
            return
        parts = c.data.split(":")
        action = parts[1]
        rid = int(parts[2])
        r = s.query(Receipt).get(rid)
        if not r or r.status != "pending":
            bot.answer_callback_query(c.id, "این رسید دیگر در انتظار نیست.")
            return

        if action == "approve":
            # خرید مستقیم
            u = s.query(User).get(r.user_id)
            p = s.query(Plan).get(r.plan_id)
            item = s.query(InventoryItem).filter_by(plan_id=p.id, used=False).order_by(InventoryItem.id.asc()).first()
            if not item:
                bot.answer_callback_query(c.id, "موجودی مخزن خالی است.")
                return
            item.used = True
            order = Order(
                user_id=u.id, plan_id=p.id, price_paid=r.expected_amount,
                coupon_code="", created_at=datetime.utcnow(),
                expires_at=datetime.utcnow()+timedelta(days=p.days),
                config_text=item.text or "", config_photo_id=item.photo_id or ""
            )
            r.status = "approved"; r.admin_id = c.from_user.id
            s.add(order); s.commit()
            send_config(u.tg_id, item)
            bot.answer_callback_query(c.id, "تأیید شد و ارسال گردید.")
            return

        if action == "approve_amount":
            admin_state[c.from_user.id] = {"await_amount_for_receipt": rid}
            bot.answer_callback_query(c.id)
            bot.send_message(c.message.chat.id, f"مبلغ واریزی را برای رسید #{rid} به تومان وارد کنید:")
            return

        if action == "reject":
            r.status = "rejected"; r.admin_id = c.from_user.id
            s.commit()
            u = s.query(User).get(r.user_id)
            bot.answer_callback_query(c.id, "رسید رد شد.")
            bot.send_message(u.tg_id, "❌ رسید شما رد شد. در صورت مشکل با پشتیبانی تماس بگیرید.")
            return

@bot.message_handler(func=lambda m: admin_state.get(m.from_user.id, {}).get("await_amount_for_receipt"))
def on_admin_amount(msg):
    if not is_admin(msg.from_user.id):
        return
    rid = admin_state[msg.from_user.id]["await_amount_for_receipt"]
    try:
        amount = int(str(msg.text).replace(",", "").strip())
    except:
        bot.reply_to(msg, "عدد معتبر وارد کنید.")
        return
    with Session() as s:
        r = s.query(Receipt).get(rid)
        if not r or r.status != "pending":
            bot.reply_to(msg, "این رسید دیگر در انتظار نیست.")
            admin_state[msg.from_user.id].clear()
            return
        u = s.query(User).get(r.user_id)

        if r.kind == "wallet":
            u.wallet += amount
            s.add(WalletTx(user_id=u.id, amount=amount, kind="charge", note=f"تأیید رسید #{r.id}"))
            r.status = "approved"; r.admin_id = msg.from_user.id; r.amount_confirmed = amount
            s.commit()
            bot.reply_to(msg, "شارژ کیف پول انجام شد ✅")
            bot.send_message(u.tg_id, f"✅ رسید شما تأیید شد. کیف پول شما {money(amount)} شارژ شد.\nموجودی فعلی: {money(u.wallet)}")
        elif r.kind == "topup_for_purchase":
            # اول شارژ، بعد تکمیل خرید
            p = s.query(Plan).get(r.plan_id)
            u.wallet += amount
            s.add(WalletTx(user_id=u.id, amount=amount, kind="charge", note=f"Topup for purchase #{r.id}"))
            r.status = "approved"; r.amount_confirmed = amount; r.admin_id = msg.from_user.id
            s.commit()
            # آیا کافی شد؟
            final, _, _ = apply_coupon(s, p.id, p.price, None)
            # ولی مبلغ نهایی را همان expected در r قرار داده بودیم
            need = r.expected_amount
            if amount >= need and u.wallet >= need:
                u.wallet -= need
                s.add(WalletTx(user_id=u.id, amount=-need, kind="purchase", note=f"خرید پلن {p.name}"))
                item = s.query(InventoryItem).filter_by(plan_id=p.id, used=False).order_by(InventoryItem.id.asc()).first()
                if item:
                    item.used = True
                    order = Order(
                        user_id=u.id, plan_id=p.id, price_paid=need,
                        created_at=datetime.utcnow(), expires_at=datetime.utcnow()+timedelta(days=p.days),
                        config_text=item.text or "", config_photo_id=item.photo_id or ""
                    )
                    s.add(order); s.commit()
                    send_config(u.tg_id, item)
                    bot.send_message(u.tg_id, "خرید شما تکمیل شد و کانفیگ ارسال شد ✅")
            else:
                s.commit()
                bot.send_message(u.tg_id, f"شارژ شما تأیید شد: {money(amount)}\nبرای تکمیل خرید، موجودی کافی کنید.")
            bot.reply_to(msg, "ثبت شد.")

        else:
            bot.reply_to(msg, "نوع رسید پشتیبانی نشده.")
    admin_state[msg.from_user.id].clear()

# ========== [ پنل ادمین ] ==========
@bot.message_handler(func=lambda m: m.text == "🛠 پنل ادمین")
def admin_panel(msg):
    if not is_admin(msg.from_user.id):
        bot.reply_to(msg, "دسترسی ندارید.")
        return
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("📦 مدیریت پلن‌ها", callback_data="adm:plans"))
    kb.add(types.InlineKeyboardButton("📚 مخزن کانفیگ‌ها", callback_data="adm:stock"))
    kb.add(types.InlineKeyboardButton("🏷 کدهای تخفیف", callback_data="adm:coupons"))
    kb.add(types.InlineKeyboardButton("👥 مدیریت کاربران", callback_data="adm:users"))
    kb.add(types.InlineKeyboardButton("📢 اعلان همگانی", callback_data="adm:broadcast"))
    kb.add(types.InlineKeyboardButton("📊 آمار و گزارش", callback_data="adm:reports"))
    kb.add(types.InlineKeyboardButton("🔧 ادمین‌ها", callback_data="adm:admins"))
    bot.send_message(msg.chat.id, "پنل ادمین:", reply_markup=kb)

# ---- مدیریت پلن‌ها
@bot.callback_query_handler(func=lambda c: c.data == "adm:plans" and is_admin(c.from_user.id))
def cb_adm_plans(c):
    with Session() as s:
        lines = ["<b>پلن‌ها</b>"]
        kb = types.InlineKeyboardMarkup()
        for p in s.query(Plan).order_by(Plan.id.asc()).all():
            sc = stock_count(s, p.id)
            lines.append(f"#{p.id} {p.name} | {money(p.price)} | {p.days} روز | موجودی {sc} | {'فعال' if p.active else 'غیرفعال'}")
            kb.add(types.InlineKeyboardButton(f"ویرایش {p.name}", callback_data=f"adm:plan:edit:{p.id}"))
        kb.add(types.InlineKeyboardButton("➕ افزودن پلن", callback_data="adm:plan:add"))
        bot.edit_message_text("\n".join(lines), c.message.chat.id, c.message.message_id, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "adm:plan:add" and is_admin(c.from_user.id))
def cb_adm_plan_add(c):
    admin_state[c.from_user.id] = {"add_plan": {}}
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "نام پلن را بفرستید:")

@bot.message_handler(func=lambda m: admin_state.get(m.from_user.id, {}).get("add_plan") is not None)
def on_admin_add_plan(msg):
    st = admin_state[msg.from_user.id]["add_plan"]
    with Session() as s:
        if "name" not in st:
            st["name"] = msg.text.strip()
            bot.reply_to(msg, "مدت (روز)؟")
            return
        if "days" not in st:
            st["days"] = int(msg.text.strip())
            bot.reply_to(msg, "حجم (گیگ، اگر ندارد 0):")
            return
        if "vol" not in st:
            st["vol"] = int(msg.text.strip())
            bot.reply_to(msg, "قیمت (تومان):")
            return
        if "price" not in st:
            st["price"] = int(msg.text.strip().replace(",", ""))
            bot.reply_to(msg, "توضیح کوتاه:")
            return
        if "desc" not in st:
            st["desc"] = msg.text
            p = Plan(name=st["name"], days=st["days"], volume_gb=st["vol"], price=st["price"], desc=st["desc"], active=True)
            s.add(p); s.commit()
            bot.reply_to(msg, f"پلن «{p.name}» اضافه شد.")
            admin_state[msg.from_user.id].clear()

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:plan:edit:") and is_admin(c.from_user.id))
def cb_adm_plan_edit(c):
    pid = int(c.data.split(":")[-1])
    with Session() as s:
        p = s.query(Plan).get(pid)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("نام", callback_data=f"adm:plan:set:name:{pid}"))
        kb.add(types.InlineKeyboardButton("روز", callback_data=f"adm:plan:set:days:{pid}"))
        kb.add(types.InlineKeyboardButton("حجم", callback_data=f"adm:plan:set:vol:{pid}"))
        kb.add(types.InlineKeyboardButton("قیمت", callback_data=f"adm:plan:set:price:{pid}"))
        kb.add(types.InlineKeyboardButton("توضیح", callback_data=f"adm:plan:set:desc:{pid}"))
        kb.add(types.InlineKeyboardButton("فعال/غیرفعال", callback_data=f"adm:plan:toggle:{pid}"))
        kb.add(types.InlineKeyboardButton("🗑 حذف پلن", callback_data=f"adm:plan:del:{pid}"))
        bot.edit_message_text(f"ویرایش پلن #{p.id} - {p.name}", c.message.chat.id, c.message.message_id, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:plan:set:") and is_admin(c.from_user.id))
def cb_adm_plan_set(c):
    _, _, field, pid = c.data.split(":")
    pid = int(pid)
    admin_state[c.from_user.id] = {"edit_plan": {"pid": pid, "field": field}}
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, f"مقدار جدید برای {field} را ارسال کنید:")

@bot.message_handler(func=lambda m: admin_state.get(m.from_user.id, {}).get("edit_plan"))
def on_adm_plan_set_value(msg):
    st = admin_state[msg.from_user.id]["edit_plan"]
    pid, field = st["pid"], st["field"]
    with Session() as s:
        p = s.query(Plan).get(pid)
        val = msg.text
        if field in ("days", "vol", "price"):
            val = int(val.replace(",", ""))
        setattr(p, {"name":"name","days":"days","vol":"volume_gb","price":"price","desc":"desc"}[field], val)
        s.commit()
    bot.reply_to(msg, "ذخیره شد.")
    admin_state[msg.from_user.id].clear()

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:plan:toggle:") and is_admin(c.from_user.id))
def cb_adm_plan_toggle(c):
    pid = int(c.data.split(":")[-1])
    with Session() as s:
        p = s.query(Plan).get(pid)
        p.active = not p.active
        s.commit()
    bot.answer_callback_query(c.id, "بروزرسانی شد.")

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:plan:del:") and is_admin(c.from_user.id))
def cb_adm_plan_del(c):
    pid = int(c.data.split(":")[-1])
    with Session() as s:
        s.query(Plan).filter_by(id=pid).delete()
        s.commit()
    bot.answer_callback_query(c.id, "حذف شد.")

# ---- مخزن
@bot.callback_query_handler(func=lambda c: c.data == "adm:stock" and is_admin(c.from_user.id))
def cb_adm_stock(c):
    with Session() as s:
        kb = types.InlineKeyboardMarkup()
        for p in s.query(Plan).order_by(Plan.id.asc()).all():
            kb.add(types.InlineKeyboardButton(f"{p.name} (افزودن/لیست)", callback_data=f"adm:stock:plan:{p.id}"))
        bot.edit_message_text("پلن موردنظر برای مدیریت مخزن:", c.message.chat.id, c.message.message_id, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:stock:plan:") and is_admin(c.from_user.id))
def cb_adm_stock_plan(c):
    pid = int(c.data.split(":")[-1])
    with Session() as s:
        p = s.query(Plan).get(pid)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("➕ افزودن کانفیگ", callback_data=f"adm:stock:add:{pid}"))
        kb.add(types.InlineKeyboardButton("📜 لیست موجودی", callback_data=f"adm:stock:list:{pid}"))
        bot.edit_message_text(f"مخزن پلن {p.name}:", c.message.chat.id, c.message.message_id, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:stock:add:") and is_admin(c.from_user.id))
def cb_adm_stock_add(c):
    pid = int(c.data.split(":")[-1])
    admin_state[c.from_user.id] = {"add_item": {"pid": pid}}
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "متن کانفیگ را بفرستید (عکس اختیاری بعدش). /skip برای بدون عکس")

@bot.message_handler(commands=["skip"])
def cmd_skip(msg):
    if admin_state.get(msg.from_user.id, {}).get("add_item"):
        on_admin_item_save(msg, photo=None)

@bot.message_handler(func=lambda m: admin_state.get(m.from_user.id, {}).get("add_item") and m.content_type in ("text", "photo"))
def on_admin_add_item(msg):
    if msg.photo:
        # اگر عکس آمد، اول متن را از state بخوانیم
        st = admin_state[msg.from_user.id]["add_item"]
        if "text" not in st:
            st["text"] = msg.caption or ""
        on_admin_item_save(msg, photo=msg.photo[-1].file_id)
    else:
        st = admin_state[msg.from_user.id]["add_item"]
        st["text"] = msg.text
        bot.reply_to(msg, "اگر می‌خواهید عکس هم اضافه کنید همین الان بفرستید، یا /skip بزنید.")

def on_admin_item_save(msg, photo=None):
    st = admin_state[msg.from_user.id]["add_item"]
    with Session() as s:
        it = InventoryItem(plan_id=st["pid"], text=st.get("text",""), photo_id=photo or "", used=False)
        s.add(it); s.commit()
    bot.reply_to(msg, "آیتم به مخزن اضافه شد ✅")
    admin_state[msg.from_user.id].clear()

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:stock:list:") and is_admin(c.from_user.id))
def cb_adm_stock_list(c):
    pid = int(c.data.split(":")[-1])
    with Session() as s:
        items = s.query(InventoryItem).filter_by(plan_id=pid, used=False).order_by(InventoryItem.id.asc()).all()
        if not items:
            bot.answer_callback_query(c.id)
            bot.send_message(c.message.chat.id, "موجودی این پلن خالی است.")
            return
        lines = [f"<b>موجودی پلن #{pid}</b>"]
        for it in items[:30]:
            lines.append(f"#{it.id} | {it.created_at:%Y-%m-%d}")
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id, "\n".join(lines))

# ---- کد تخفیف
@bot.callback_query_handler(func=lambda c: c.data == "adm:coupons" and is_admin(c.from_user.id))
def cb_adm_coupons(c):
    with Session() as s:
        cs = s.query(Coupon).order_by(Coupon.id.desc()).limit(30).all()
        lines = ["<b>کدهای تخفیف</b>"]
        for x in cs:
            lines.append(f"#{x.id} | {x.code} | {x.percent}% | plan={x.only_plan_id or 'همه'} | used {x.used_count}/{x.use_limit or '∞'} | {'فعال' if x.active else 'خاموش'}")
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("➕ ساخت کد", callback_data="adm:coupon:add"))
        bot.edit_message_text("\n".join(lines), c.message.chat.id, c.message.message_id, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "adm:coupon:add" and is_admin(c.from_user.id))
def cb_adm_coupon_add(c):
    admin_state[c.from_user.id] = {"add_coupon": {}}
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "درصد تخفیف را بفرستید (مثلاً 15):")

@bot.message_handler(func=lambda m: admin_state.get(m.from_user.id, {}).get("add_coupon") is not None)
def on_adm_coupon_wizard(msg):
    st = admin_state[msg.from_user.id]["add_coupon"]
    with Session() as s:
        if "percent" not in st:
            st["percent"] = int(msg.text.strip())
            bot.reply_to(msg, "کد/نام (مثلاً OFF15):")
            return
        if "code" not in st:
            st["code"] = msg.text.strip()
            bot.reply_to(msg, "آی‌دی پلن خاص؟ (عدد یا 0 برای همه)")
            return
        if "plan" not in st:
            plan = int(msg.text.strip())
            st["plan"] = plan if plan != 0 else None
            bot.reply_to(msg, "تعداد سقف استفاده؟ (0 برای نامحدود)")
            return
        if "limit" not in st:
            st["limit"] = int(msg.text.strip())
            bot.reply_to(msg, "تاریخ انقضا؟ (YYYY-MM-DD یا 0 برای بدون انقضا)")
            return
        if "exp" not in st:
            val = msg.text.strip()
            exp = None if val == "0" else datetime.strptime(val, "%Y-%m-%d")
            cpn = Coupon(code=st["code"], percent=st["percent"], only_plan_id=st["plan"],
                         expires_at=exp, use_limit=st["limit"], used_count=0, active=True)
            s.add(cpn); s.commit()
            bot.reply_to(msg, f"کد {cpn.code} ساخته شد ✅")
            admin_state[msg.from_user.id].clear()

# ---- کاربران
@bot.callback_query_handler(func=lambda c: c.data == "adm:users" and is_admin(c.from_user.id))
def cb_adm_users(c):
    admin_state[c.from_user.id] = {"user_search": True}
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "آیدی عددی یا @یوزرنیم را بفرستید:")

@bot.message_handler(func=lambda m: admin_state.get(m.from_user.id, {}).get("user_search"))
def on_adm_user_search(msg):
    q = msg.text.strip().lstrip("@")
    with Session() as s:
        u = s.query(User).filter((User.username.ilike(q)) | (User.tg_id==q) | (User.tg_id==int(q) if q.isdigit() else False)).first()
        if not u:
            bot.reply_to(msg, "کاربری یافت نشد.")
            return
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("بن/آنبن", callback_data=f"adm:user:ban:{u.tg_id}"))
        kb.add(types.InlineKeyboardButton("شارژ دستی", callback_data=f"adm:user:charge:{u.tg_id}"))
        bot.reply_to(msg, f"کاربر: {u.tg_id}\nکیف پول: {money(u.wallet)}\nتعداد خرید: {len(u.orders)}", reply_markup=kb)
    admin_state[msg.from_user.id].clear()

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:user:ban:") and is_admin(c.from_user.id))
def cb_adm_user_ban(c):
    uid = int(c.data.split(":")[-1])
    with Session() as s:
        u = s.query(User).filter_by(tg_id=uid).first()
        u.is_banned = not u.is_banned; s.commit()
    bot.answer_callback_query(c.id, "به‌روزرسانی شد.")

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:user:charge:") and is_admin(c.from_user.id))
def cb_adm_user_charge(c):
    uid = int(c.data.split(":")[-1])
    admin_state[c.from_user.id] = {"charge_user": uid}
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "مبلغ شارژ (+) یا کسر (-) را وارد کنید (تومان):")

@bot.message_handler(func=lambda m: admin_state.get(m.from_user.id, {}).get("charge_user"))
def on_adm_user_charge(msg):
    uid = admin_state[msg.from_user.id]["charge_user"]
    try:
        amount = int(msg.text.replace(",", ""))
    except:
        bot.reply_to(msg, "عدد معتبر وارد کنید.")
        return
    with Session() as s:
        u = s.query(User).filter_by(tg_id=uid).first()
        u.wallet += amount
        kind = "adjust"
        s.add(WalletTx(user_id=u.id, amount=amount, kind=kind, note="manual admin"))
        s.commit()
        bot.reply_to(msg, "ثبت شد.")
        bot.send_message(uid, f"بروزرسانی کیف پول: {money(amount)} | موجودی جدید: {money(u.wallet)}")
    admin_state[msg.from_user.id].clear()

# ---- اعلان همگانی
@bot.callback_query_handler(func=lambda c: c.data == "adm:broadcast" and is_admin(c.from_user.id))
def cb_adm_broadcast(c):
    admin_state[c.from_user.id] = {"broadcast": True}
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, "متن پیام همگانی را بفرستید:")

@bot.message_handler(func=lambda m: admin_state.get(m.from_user.id, {}).get("broadcast"))
def on_adm_broadcast(msg):
    with Session() as s:
        ids = [u.tg_id for u in s.query(User).all()]
    ok = 0
    for i in ids:
        try:
            bot.send_message(i, msg.text)
            ok += 1
        except: pass
    bot.reply_to(msg, f"ارسال شد به {ok} کاربر.")
    admin_state[msg.from_user.id].clear()

# ---- گزارش‌ها
@bot.callback_query_handler(func=lambda c: c.data == "adm:reports" and is_admin(c.from_user.id))
def cb_adm_reports(c):
    with Session() as s:
        total_income = sum(o.price_paid for o in s.query(Order).all())
        by_plan = s.query(Plan.name, func.count(Order.id), func.sum(Order.price_paid))\
                   .join(Order, Plan.id==Order.plan_id).group_by(Plan.id).all()
        lines = [f"<b>گزارش فروش</b>\nدرآمد کل: {money(total_income)}", ""]
        for nm, cnt, amt in by_plan:
            lines.append(f"{nm}: {cnt} فروش | {money(amt or 0)}")
        bot.edit_message_text("\n".join(lines), c.message.chat.id, c.message.message_id)

# ---- ادمین‌ها
@bot.callback_query_handler(func=lambda c: c.data == "adm:admins" and is_admin(c.from_user.id))
def cb_adm_admins(c):
    with Session() as s:
        ids = [a.tg_id for a in s.query(Admin).all()]
    lines = ["<b>ادمین‌ها</b>"] + [str(i) for i in ids] + [f"(ثابت‌ها: {', '.join(map(str, ADMIN_IDS))})"]
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("➕ افزودن", callback_data="adm:admin:add"))
    kb.add(types.InlineKeyboardButton("➖ حذف", callback_data="adm:admin:del"))
    bot.edit_message_text("\n".join(lines), c.message.chat.id, c.message.message_id, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data in ("adm:admin:add","adm:admin:del") and is_admin(c.from_user.id))
def cb_adm_admins_set(c):
    mode = "add" if c.data.endswith("add") else "del"
    admin_state[c.from_user.id] = {"admin_set": mode}
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, f"آیدی عددی ادمین برای {('افزودن' if mode=='add' else 'حذف')}:")

@bot.message_handler(func=lambda m: admin_state.get(m.from_user.id, {}).get("admin_set"))
def on_adm_admins_set_val(msg):
    mode = admin_state[msg.from_user.id]["admin_set"]
    try:
        tid = int(msg.text.strip())
    except:
        bot.reply_to(msg, "آیدی نامعتبر.")
        return
    with Session() as s:
        if mode == "add":
            if not s.query(Admin).filter_by(tg_id=tid).first():
                s.add(Admin(tg_id=tid)); s.commit()
            bot.reply_to(msg, "اضافه شد.")
        else:
            s.query(Admin).filter_by(tg_id=tid).delete(); s.commit()
            bot.reply_to(msg, "حذف شد.")
    admin_state[msg.from_user.id].clear()

# ========== [ نوتیفِ انقضا – کران ] ==========
@app.get(f"/cron/<secret>")
def cron(secret):
    if secret != CRON_SECRET:
        return "nope", 403
    with Session() as s:
        now = datetime.utcnow()
        soon = now + timedelta(days=3)
        to_notify = s.query(Order).filter(Order.expires_at <= soon, Order.expires_at > now, Order.expiry_notified == False).all()
        for o in to_notify:
            try:
                bot.send_message(o.user.tg_id, f"⏳ {o.plan.name} شما تا 3 روز دیگر منقضی می‌شود. برای تمدید اقدام کنید.")
                o.expiry_notified = True
            except: pass
        s.commit()
    return f"ok {len(to_notify)}"

# ========== [ وبهوک ] ==========
@app.get("/")
def index():
    return "OK"

@app.post("/webhook")
@app.post(f"/webhook/{TOKEN}")
def webhook():
    if request.headers.get("content-type") == "application/json":
        update = telebot.types.Update.de_json(request.data.decode("utf-8"))
        bot.process_new_updates([update])
        return "ok"
    abort(403)

# ========== [ اجرای Flask ] ==========
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
