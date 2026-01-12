import logging
import asyncio
import random
import json
import os
import time
import heapq
import shutil
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from functools import wraps

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    BotCommand, BotCommandScopeAllPrivateChats
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
    ConversationHandler
)

# --- إعدادات البوت ---
TOKEN = "6741306329:AAG-or3-0oGmr3QJWN-kCC7tYxP7FTLlYgo"
DEVELOPER_ID = 778375826
ADMINS_IDS = [778375826]
APPLICATION = None

# --- إعداد التسجيل ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    filename='bot.log'
)
logger = logging.getLogger(__name__)

# --- قاعدة البيانات (SQLAlchemy) ---
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text, func, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.exc import SQLAlchemyError

engine = create_engine('sqlite:///bot_data.db', echo=False, connect_args={"check_same_thread": False})
Base = declarative_base()
Session = sessionmaker(bind=engine)

# --- نماذج قاعدة البيانات ---

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, unique=True, index=True)
    username = Column(String, nullable=True)
    is_admin = Column(Boolean, default=False)
    is_banned = Column(Boolean, default=False)
    is_subscribed = Column(Boolean, default=False)
    is_premium = Column(Boolean, default=False)
    join_date = Column(DateTime, default=datetime.now)
    last_activity = Column(DateTime, default=datetime.now)
    preferred_language = Column(String, default='ar')
    theme = Column(String, default='default')
    
    notifications = relationship("Notification", back_populates="user")
    security_logs = relationship("SecurityLog", back_populates="user")

class Channel(Base):
    __tablename__ = 'channels'
    id = Column(Integer, primary_key=True)
    channel_id = Column(Integer, unique=True, index=True)
    title = Column(String)
    category = Column(String, default="عام")
    msg_format = Column(String, default="normal")
    is_active = Column(Boolean, default=True)
    added_by = Column(Integer, nullable=True)
    added_at = Column(DateTime, default=datetime.now)

class Content(Base):
    __tablename__ = 'content'
    id = Column(Integer, primary_key=True)
    category = Column(String, index=True)
    text = Column(Text)
    added_by = Column(Integer, nullable=True)
    added_at = Column(DateTime, default=datetime.now)
    is_active = Column(Boolean, default=True)
    view_count = Column(Integer, default=0)

class Filter(Base):
    __tablename__ = 'filters'
    id = Column(Integer, primary_key=True)
    word = Column(String, unique=True)
    replacement = Column(String)
    added_by = Column(Integer, nullable=True)
    added_at = Column(DateTime, default=datetime.now)
    is_active = Column(Boolean, default=True)
    usage_count = Column(Integer, default=0)

class BotSettings(Base):
    __tablename__ = 'settings'
    key = Column(String, primary_key=True)
    value = Column(String)

class ActivityLog(Base):
    __tablename__ = 'logs'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    action = Column(String)
    details = Column(Text)
    timestamp = Column(DateTime, default=datetime.now)

class Notification(Base):
    __tablename__ = 'notifications'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.user_id'), index=True)
    message = Column(Text)
    scheduled_time = Column(DateTime)
    is_sent = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)
    user = relationship("User", back_populates="notifications")

class Analytics(Base):
    __tablename__ = 'analytics'
    id = Column(Integer, primary_key=True)
    date = Column(DateTime, default=datetime.now)
    action = Column(String)
    channel_id = Column(Integer, nullable=True)
    content_id = Column(Integer, nullable=True)
    user_id = Column(Integer, nullable=True)
    meta_data = Column(String, nullable=True)

class SecurityLog(Base):
    __tablename__ = 'security_logs'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.user_id'), index=True)
    action = Column(String)
    timestamp = Column(DateTime, default=datetime.now)
    user = relationship("User", back_populates="security_logs")

class Backup(Base):
    __tablename__ = 'backups'
    id = Column(Integer, primary_key=True)
    filename = Column(String)
    size = Column(Integer)
    created_at = Column(DateTime, default=datetime.now)
    is_active = Column(Boolean, default=True)

# إنشاء جداول قاعدة البيانات
Base.metadata.create_all(engine)

# --- دوال مساعدة ---

def get_session():
    return Session()

def db_log_action(user_id, action, details=""):
    session = get_session()
    try:
        log = ActivityLog(user_id=user_id, action=action, details=details)
        session.add(log)
        session.commit()
    except Exception as e:
        logger.error(f"Log Error: {e}")
    finally:
        session.close()

def get_role(user_id):
    if user_id == DEVELOPER_ID: return "dev"
    if user_id in ADMINS_IDS: return "admin"
    session = get_session()
    try:
        user = session.query(User).filter_by(user_id=user_id).first()
        if user and user.is_admin: return "admin"
        if user and user.is_banned: return "banned"
        if user and user.is_premium: return "premium"
        return "user"
    finally:
        session.close()

def get_required_channel():
    session = get_session()
    try:
        setting = session.query(BotSettings).filter_by(key='required_channel').first()
        return setting.value if setting else None
    finally:
        session.close()

async def check_subscription(user_id, required_channel):
    if not required_channel: return True
    try:
        member = await APPLICATION.bot.get_chat_member(required_channel, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except:
        return False

def get_stats():
    session = get_session()
    try:
        users_count = session.query(User).count()
        channels_count = session.query(Channel).count()
        content_count = session.query(Content).count()
        return f"📊 <b>إحصائيات البوت:</b>\n\n👥 المستخدمين: {users_count}\n📢 القنوات: {channels_count}\n📝 المحتوى: {content_count}"
    finally:
        session.close()

CATEGORIES = [
    ("❤️ حب", "حب"), ("🎂 عيد ميلاد", "عيد ميلاد"), ("💭 اقتباسات", "اقتباسات"),
    ("📜 شعر", "شعر"), ("📚 ديني", "ديني"), ("😂 مضحك", "مضحك")
]

# --- الكيبوردات ---

def get_main_menu(role):
    buttons = []
    if role in ["dev", "admin"]:
        buttons = [
            [InlineKeyboardButton("📢 إضافة قناة", callback_data="add_channel_start"), InlineKeyboardButton("📢 إدارة القنوات", callback_data="manage_channels")],
            [InlineKeyboardButton("📝 رفع محتوى", callback_data="upload_content_menu"), InlineKeyboardButton("📂 إدارة المحتوى", callback_data="manage_content")],
            [InlineKeyboardButton("🔍 ترشيحات", callback_data="filters_menu"), InlineKeyboardButton("📊 الإحصائيات", callback_data="stats")],
            [InlineKeyboardButton("🔔 الإشعارات", callback_data="notifications_menu"), InlineKeyboardButton("💾 النسخ الاحتياطي", callback_data="backup_menu")]
        ]
    else:
        buttons = [
            [InlineKeyboardButton("📂 الأقسام", callback_data="user_categories"), InlineKeyboardButton("🔖 اقتباس عشوائي", callback_data="user_random")],
            [InlineKeyboardButton("🔍 بحث", callback_data="search_menu"), InlineKeyboardButton("💎 المميز", callback_data="premium_menu")],
            [InlineKeyboardButton("📝 مساهمة", callback_data="upload_content_menu")]
        ]
    title = "لوحة التحكم 🔧" if role in ["dev", "admin"] else "القائمة الرئيسية 🏠"
    return InlineKeyboardMarkup(buttons), title

def get_categories_keyboard(prefix):
    buttons = [[InlineKeyboardButton(name, callback_data=f"{prefix}_{code}")] for name, code in CATEGORIES]
    buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_main")])
    return InlineKeyboardMarkup(buttons)

# --- معالجات الأحداث ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username
    session = get_session()
    user = session.query(User).filter_by(user_id=user_id).first()
    if not user:
        user = User(user_id=user_id, username=username)
        session.add(user)
        session.commit()
    session.close()
    
    role = get_role(user_id)
    kb, title = get_main_menu(role)
    await update.message.reply_text(f"أهلاً بك! 👋\n\n🔹 <b>{title}</b> 🔹", reply_markup=kb, parse_mode='HTML')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    role = get_role(user_id)

    if data == "back_main":
        kb, title = get_main_menu(role)
        await query.edit_message_text(f"🔹 <b>{title}</b> 🔹", reply_markup=kb, parse_mode='HTML')
    
    elif data == "stats":
        await query.edit_message_text(get_stats(), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]]), parse_mode='HTML')

    elif data == "add_channel_start":
        context.user_data['mode'] = 'add_channel_link'
        await query.edit_message_text("🔗 أرسل رابط القناة (مثال: @my_channel):", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]]))

    elif data.startswith("set_cat_"):
        link = context.user_data.get('temp_channel_link')
        category = data.split("_")[-1]
        try:
            chat = await APPLICATION.bot.get_chat(link)
            session = get_session()
            new_ch = Channel(channel_id=chat.id, title=chat.title, category=category, added_by=user_id)
            session.add(new_ch)
            session.commit()
            session.close()
            await query.edit_message_text(f"✅ تمت إضافة القناة: {chat.title}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]]))
        except Exception as e:
            await query.edit_message_text(f"❌ خطأ: {e}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]]))
        context.user_data['mode'] = None

    elif data == "upload_content_menu":
        await query.edit_message_text("اختر القسم لرفع المحتوى:", reply_markup=get_categories_keyboard("upload"))

    elif data.startswith("upload_"):
        category = data.split("_")[-1]
        context.user_data['temp_category'] = category
        btns = [
            [InlineKeyboardButton("✏️ نص يدوي", callback_data=f"manual_{category}")],
            [InlineKeyboardButton("📁 رفع ملف .txt", callback_data=f"file_{category}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="upload_content_menu")]
        ]
        await query.edit_message_text(f"اختر طريقة الرفع لقسم {category}:", reply_markup=InlineKeyboardMarkup(btns))

    elif data.startswith("manual_"):
        category = data.split("_")[-1]
        context.user_data['mode'] = 'upload_manual'
        context.user_data['temp_category'] = category
        await query.edit_message_text(f"✏️ أرسل النص الآن:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]]))

    elif data.startswith("file_"):
        category = data.split("_")[-1]
        context.user_data['mode'] = 'upload_file'
        context.user_data['temp_category'] = category
        await query.edit_message_text(f"📁 أرسل ملف .txt الآن:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]]))

    elif data == "search_menu":
        context.user_data['mode'] = 'search'
        await query.edit_message_text("🔍 أرسل كلمة البحث:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]]))

    elif data == "notifications_menu":
        context.user_data['mode'] = 'add_notif'
        await query.edit_message_text("🔔 أرسل نص الإشعار لإرساله لجميع المستخدمين:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]]))

    elif data == "user_categories":
        await query.edit_message_text("اختر القسم:", reply_markup=get_categories_keyboard("user_cat"))

    elif data.startswith("user_cat_"):
        cat = data.split("_")[-1]
        session = get_session()
        content = session.query(Content).filter_by(category=cat).order_by(func.random()).first()
        if content:
            await query.edit_message_text(f"✨ <b>{cat}</b>\n\n{content.text}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 غيرها", callback_data=f"user_cat_{cat}")], [InlineKeyboardButton("🔙 رجوع", callback_data="user_categories")]]), parse_mode='HTML')
        else:
            await query.edit_message_text("📭 لا يوجد محتوى حالياً.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="user_categories")]]))
        session.close()

    elif data == "manage_channels":
        session = get_session()
        channels = session.query(Channel).all()
        if not channels:
            await query.edit_message_text("لا توجد قنوات.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]]))
        else:
            text = "📢 <b>القنوات:</b>\n"
            btns = []
            for c in channels:
                text += f"- {c.title}\n"
                btns.append([InlineKeyboardButton(f"🗑️ حذف {c.title}", callback_data=f"del_ch_{c.id}")])
            btns.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_main")])
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(btns), parse_mode='HTML')
        session.close()

    elif data.startswith("del_ch_"):
        ch_id = int(data.split("_")[-1])
        session = get_session()
        session.query(Channel).filter_by(id=ch_id).delete()
        session.commit()
        session.close()
        await query.edit_message_text("✅ تم حذف القناة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="manage_channels")]]))

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get('mode')
    text = update.message.text
    user_id = update.effective_user.id

    if mode == 'add_channel_link':
        context.user_data['temp_channel_link'] = text
        context.user_data['mode'] = 'add_channel_category'
        btns = [[InlineKeyboardButton(n, callback_data=f"set_cat_{c}")] for n, c in CATEGORIES]
        await update.message.reply_text("اختر فئة القناة:", reply_markup=InlineKeyboardMarkup(btns))

    elif mode == 'upload_manual':
        cat = context.user_data.get('temp_category')
        session = get_session()
        new_content = Content(category=cat, text=text, added_by=user_id)
        session.add(new_content)
        session.commit()
        session.close()
        await update.message.reply_text("✅ تم الحفظ!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 القائمة", callback_data="back_main")]]))
        context.user_data['mode'] = None

    elif mode == 'search':
        session = get_session()
        results = session.query(Content).filter(Content.text.contains(text)).limit(5).all()
        if not results:
            await update.message.reply_text("❌ لا توجد نتائج.")
        else:
            res_text = "🔍 <b>نتائج البحث:</b>\n\n"
            for r in results:
                res_text += f"📌 {r.text[:100]}...\n\n"
            await update.message.reply_text(res_text, parse_mode='HTML')
        session.close()
        context.user_data['mode'] = None

    elif mode == 'add_notif':
        session = get_session()
        users = session.query(User).all()
        count = 0
        for u in users:
            try:
                await context.bot.send_message(u.user_id, f"🔔 <b>إشعار جديد:</b>\n\n{text}", parse_mode='HTML')
                count += 1
            except: pass
        await update.message.reply_text(f"✅ تم إرسال الإشعار لـ {count} مستخدم.")
        session.close()
        context.user_data['mode'] = None

async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get('mode')
    if mode == 'upload_file':
        doc = update.message.document
        if not doc.file_name.endswith('.txt'):
            await update.message.reply_text("❌ يرجى إرسال ملف بصيغة .txt فقط.")
            return
        
        file = await doc.get_file()
        content_bytes = await file.download_as_bytearray()
        content_text = content_bytes.decode('utf-8')
        
        cat = context.user_data.get('temp_category')
        lines = content_text.split('\n')
        session = get_session()
        added = 0
        for line in lines:
            if line.strip():
                new_c = Content(category=cat, text=line.strip(), added_by=update.effective_user.id)
                session.add(new_c)
                added += 1
        session.commit()
        session.close()
        await update.message.reply_text(f"✅ تم رفع {added} نص بنجاح!")
        context.user_data['mode'] = None

async def backup_database():
    try:
        shutil.copy2("bot_data.db", f"backup_{datetime.now().strftime('%Y%m%d')}.db")
        logger.info("Backup created.")
    except:
        logger.error("Backup failed.")

def main():
    global APPLICATION
    APPLICATION = Application.builder().token(TOKEN).build()
    APPLICATION.add_handler(CommandHandler("start", start))
    APPLICATION.add_handler(CallbackQueryHandler(button_handler))
    APPLICATION.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    APPLICATION.add_handler(MessageHandler(filters.Document.ALL, document_handler))
    
    logger.info("Bot started...")
    APPLICATION.run_polling()

if __name__ == "__main__":
    main()
