import logging
import asyncio
import random
import json
import os
from datetime import datetime, timedelta
from typing import Optional, Dict

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
TOKEN = "6741306329:AAG-or3-0oGmr3QJWN-kCC7tYxP7FTLlYgo"  # ضع التوكن هنا
DEVELOPER_ID = 778375826       # ضع آيديك الرقمي هنا
ADMINS_IDS = [778375826]

# --- إعداد التسجيل ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    filename='bot.log'
)
logger = logging.getLogger(__name__)

# --- قاعدة البيانات (SQLAlchemy) ---
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text, func
from sqlalchemy.orm import declarative_base, sessionmaker

# إضافة connect_args لإصلاح مشكلة الترابط مع SQLite
engine = create_engine('sqlite:///bot_data.db', echo=False, connect_args={"check_same_thread": False})
Base = declarative_base()
Session = sessionmaker(bind=engine)

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, unique=True, index=True)
    username = Column(String, nullable=True)
    is_admin = Column(Boolean, default=False)
    is_banned = Column(Boolean, default=False)
    is_subscribed = Column(Boolean, default=False)
    join_date = Column(DateTime, default=datetime.now)

class Channel(Base):
    __tablename__ = 'channels'
    id = Column(Integer, primary_key=True)
    channel_id = Column(Integer, unique=True, index=True)
    title = Column(String)
    category = Column(String, default="عام")
    msg_format = Column(String, default="normal")
    time_type = Column(String, default="default")
    time_value = Column(String, nullable=True)
    last_post_at = Column(DateTime, nullable=True)
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

class Filter(Base):
    __tablename__ = 'filters'
    id = Column(Integer, primary_key=True)
    word = Column(String, unique=True)
    replacement = Column(String)
    added_by = Column(Integer, nullable=True)
    added_at = Column(DateTime, default=datetime.now)

class BotSettings(Base):
    __tablename__ = 'settings'
    key = Column(String, primary_key=True)
    value = Column(String)
    updated_by = Column(Integer, nullable=True)
    updated_at = Column(DateTime, default=datetime.now)

class ActivityLog(Base):
    __tablename__ = 'logs'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    action = Column(String)
    details = Column(Text)
    timestamp = Column(DateTime, default=datetime.now)

Base.metadata.create_all(engine)

# --- دوال مساعدة ---
def db_log_action(user_id, action, details=""):
    # استخدام 0 للمستخدم في العمليات الذاتية للبوت لتجنب الأخطاء
    uid = user_id if user_id else 0
    session = Session()
    try:
        log = ActivityLog(user_id=uid, action=action, details=details)
        session.add(log)
        session.commit()
    except Exception as e:
        logger.error(f"Log Error: {e}")
    finally:
        session.close()

def get_role(user_id):
    if user_id == DEVELOPER_ID: return "dev"
    if user_id in ADMINS_IDS: return "admin"
    
    session = Session()
    try:
        user = session.query(User).filter_by(user_id=user_id).first()
        if user and user.is_admin: return "admin"
        if user and user.is_banned: return "banned"
    finally:
        session.close()
    return "user"

def get_required_channel():
    session = Session()
    try:
        setting = session.query(BotSettings).filter_by(key='required_channel').first()
        return setting.value if setting else None
    finally:
        session.close()

async def check_subscription(user_id, required_channel):
    if not required_channel:
        return True
    
    try:
        member = await application.bot.get_chat_member(required_channel, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Subscription check error for user {user_id}: {e}")
        return False

def get_filters():
    session = Session()
    try:
        return {f.word: f.replacement for f in session.query(Filter).all()}
    finally:
        session.close()

async def filter_text(text):
    filters_dict = get_filters()
    for word, replacement in filters_dict.items():
        text = text.replace(word, replacement)
    return text

def get_stats():
    session = Session()
    try:
        users_count = session.query(User).count()
        active_users = session.query(User).filter_by(is_banned=False).count()
        admins_count = session.query(User).filter_by(is_admin=True).count()
        channels_count = session.query(Channel).count()
        active_channels = session.query(Channel).filter_by(is_active=True).count()
        content_count = session.query(Content).count()
        filters_count = session.query(Filter).count()
        return f"📊 <b>إحصائيات البوت:</b>\n\n👥 المستخدمين: {users_count} (نشط: {active_users})\n🛡️ المشرفين: {admins_count}\n📢 القنوات: {channels_count} (نشط: {active_channels})\n📝 المحتوى: {content_count} نص\n🔍 الترشيحات: {filters_count} قاعدة"
    finally:
        session.close()

async def get_detailed_stats():
    session = Session()
    try:
        stats = {
            'total_users': session.query(User).count(),
            'active_users': session.query(User).filter_by(is_banned=False).count(),
            'total_channels': session.query(Channel).count(),
            'active_channels': session.query(Channel).filter_by(is_active=True).count(),
            'total_content': session.query(Content).count(),
            'total_filters': session.query(Filter).count(),
            'categories': {}
        }
        
        for name, code in CATEGORIES:
            count = session.query(Content).filter_by(category=code).count()
            stats['categories'][name] = count
        
        return stats
    finally:
        session.close()

# --- الثوابت ---
CATEGORIES = [
    ("❤️ حب", "حب"),
    ("🎂 عيد ميلاد", "عيد ميلاد"),
    ("💭 اقتباسات عامة", "اقتباسات عامة"),
    ("📜 ابيات شعرية", "ابيات شعرية"),
    ("📚 ديني", "ديني"),
    ("😂 مضحك", "مضحك")
]

# حالات المحادثة
STATE_ADD_CHANNEL_LINK = 1
STATE_ADD_CHANNEL_CATEGORY = 2
STATE_ADD_CHANNEL_FORMAT = 3
STATE_ADD_CHANNEL_TIME = 4
STATE_BROADCAST_MSG = 5
STATE_BAN_USER_ID = 6
STATE_UPLOAD_CONTENT = 7
STATE_FILTERS_MENU = 8
STATE_ADD_FILTER = 9
STATE_SET_REQUIRED_CHANNEL = 10

# --- الكيبوردات ---
def get_main_menu(role):
    if role == "dev":
        buttons = [
            [InlineKeyboardButton("📢 إضافة قناة", callback_data="add_channel_start")],
            [InlineKeyboardButton("📢 إدارة القنوات", callback_data="manage_channels")],
            [InlineKeyboardButton("📝 رفع محتوى", callback_data="upload_content_menu")],
            [InlineKeyboardButton("📂 إدارة المحتوى", callback_data="manage_content")],
            [InlineKeyboardButton("🔍 ترشيحات", callback_data="filters_menu")],
            [InlineKeyboardButton("🔧 إعدادات البوت", callback_data="bot_settings")],
            [InlineKeyboardButton("📊 الإحصائيات", callback_data="stats")],
        ]
    elif role == "admin":
        buttons = [
            [InlineKeyboardButton("📢 إضافة قناة", callback_data="add_channel_start")],
            [InlineKeyboardButton("📢 إدارة القنوات", callback_data="manage_channels")],
            [InlineKeyboardButton("📝 رفع محتوى", callback_data="upload_content_menu")],
            [InlineKeyboardButton("📂 إدارة المحتوى", callback_data="manage_content")],
            [InlineKeyboardButton("🔍 ترشيحات", callback_data="filters_menu")],
            [InlineKeyboardButton("📊 الإحصائيات", callback_data="stats")],
            [InlineKeyboardButton("🚀 نشر الآن", callback_data="force_post_now")]
        ]
    else:
        buttons = [
            [InlineKeyboardButton("📂 الأقسام", callback_data="user_categories")],
            [InlineKeyboardButton("🔖 اقتباس عشوائي", callback_data="user_random")],
            [InlineKeyboardButton("📝 مساهمة (رفع محتوى)", callback_data="upload_content_menu")],
        ]
    title = "لوحة المطور 🔧" if role == "dev" else "لوحة المشرف 👨‍💼" if role == "admin" else "القائمة الرئيسية 🏠"
    return InlineKeyboardMarkup(buttons), title

def get_back_keyboard(role):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"back_{role}")]])

def get_categories_keyboard(prefix):
    buttons = [[InlineKeyboardButton(name, callback_data=f"{prefix}_{code}")] for name, code in CATEGORIES]
    buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_admin")])
    return InlineKeyboardMarkup(buttons)

def get_format_keyboard(prefix):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 نص عادي", callback_data=f"{prefix}_normal")],
        [InlineKeyboardButton("💎 Blockquote", callback_data=f"{prefix}_blockquote")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_admin")]
    ])

def get_time_keyboard(prefix):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏰ ساعات محددة", callback_data=f"{prefix}_fixed")],
        [InlineKeyboardButton("⏳ كل X دقيقة", callback_data=f"{prefix}_interval")],
        [InlineKeyboardButton("🚫 افتراضي (عشوائي)", callback_data=f"{prefix}_default")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_admin")]
    ])

def get_filters_keyboard():
    session = Session()
    try:
        filters_list = session.query(Filter).all()
        buttons = []
        for f in filters_list:
            buttons.append([InlineKeyboardButton(f"🔍 {f.word} → {f.replacement}", callback_data=f"edit_filter_{f.id}")])
        buttons.append([InlineKeyboardButton("➕ إضافة ترشيح", callback_data="add_filter")])
        buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_dev")])
        return InlineKeyboardMarkup(buttons)
    finally:
        session.close()

# --- معالجة الأوامر ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username
    
    # التحقق من الاشتراك الإجباري
    required_channel = get_required_channel()
    if required_channel:
        is_subscribed = await check_subscription(user_id, required_channel)
        if not is_subscribed:
            await update.message.reply_text(
                "🔒 يرجى الاشتراك في القناة أولاً:\n\n"
                f"👉 [انضم للقناة](https://t.me/{required_channel.lstrip('@')})",
                disable_web_page_preview=True
            )
            return
    
    role = get_role(user_id)
    if role == "banned":
        await update.message.reply_text("⛔️ تم حظرك من استخدام البوت.")
        return

    session = Session()
    try:
        user = session.query(User).filter_by(user_id=user_id).first()
        if not user:
            user = User(user_id=user_id, username=username, is_banned=False, is_subscribed=is_subscribed)
            session.add(user)
            session.commit()
            db_log_action(user_id, "JOIN", f"New user: @{username}")
        elif user.username != username:
            user.username = username
            user.is_subscribed = is_subscribed
            session.commit()
        elif not user.is_subscribed and is_subscribed:
            user.is_subscribed = True
            session.commit()
    except Exception as e:
        logger.error(f"DB Error in start: {e}")
    finally:
        session.close()

    kb, title = get_main_menu(role)
    text = f"أهلاً بك {update.effective_user.first_name}! 👋\n\n🔹 <b>{title}</b> 🔹"
    await update.message.reply_text(text, reply_markup=kb, parse_mode='HTML')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    role = get_role(user_id)
    data = query.data

    # التحقق مرة أخرى من الاشتراك للواجهات الداخلية
    required_channel = get_required_channel()
    if required_channel and role == "user":
        is_subscribed = await check_subscription(user_id, required_channel)
        if not is_subscribed:
            await query.edit_message_text(
                "🔒 يرجى الاشتراك في القناة أولاً:\n\n"
                f"👉 [انضم للقناة](https://t.me/{required_channel.lstrip('@')})",
                disable_web_page_preview=True
            )
            return

    if data.startswith("back_"):
        target_role = data.split("_")[1]
        if target_role == "admin" and role == "dev": target_role = "dev"
        kb, title = get_main_menu(target_role)
        await query.edit_message_text(f"🔹 <b>{title}</b> 🔹", reply_markup=kb, parse_mode='HTML')
        return

    if role == "user":
        if data == "user_random":
            cat_code = random.choice([c[1] for c in CATEGORIES])
            await send_user_content(query, cat_code)
        elif data.startswith("user_cat_"):
            cat_code = data.split("_")[-1]
            await send_user_content(query, cat_code)
        elif data == "user_categories":
            await query.edit_message_text("اختر القسم:", reply_markup=get_categories_keyboard("user_cat"))
        return

    # --- إعدادات البوت (للمطور فقط) ---
    if role == "dev":
        if data == "bot_settings":
            required_channel = get_required_channel()
            txt = f"🔧 <b>إعدادات البوت:</b>\n\n"
            txt += f"📢 القناة الإلزامية: {'✅' if required_channel else '❌'}\n"
            if required_channel:
                txt += f"   🆔 {required_channel}\n"
            txt += f"🔍 نظام الترشيح: {'✅' if session.query(Filter).count() > 0 else '❌'}\n"
            txt += f"📊 البوت نشط: {'✅' if get_global_status() else '❌'}"
            
            buttons = []
            if required_channel:
                buttons.append([InlineKeyboardButton("🔄 تغيير القناة", callback_data="set_required_channel")])
            else:
                buttons.append([InlineKeyboardButton("➕ إضافة قناة", callback_data="set_required_channel")])
            
            buttons.extend([
                [InlineKeyboardButton("🔍 إدارة الترشيحات", callback_data="filters_menu")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="back_dev")]
            ])
            await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(buttons), parse_mode='HTML')
            return

        if data == "set_required_channel":
            context.user_data.clear()
            await query.edit_message_text("⚙️ <b>تعيين قناة الاشتراك الإجباري:</b>\n\nأرسل معرف القناة (@channel) أو رابطها:", reply_markup=get_back_keyboard("dev"), parse_mode='HTML')
            return STATE_SET_REQUIRED_CHANNEL

        if data == "filters_menu":
            await query.edit_message_text("🔍 <b>قواعد الترشيح:</b>\n\nاختر الترشيح لتعديله:", reply_markup=get_filters_keyboard(), parse_mode='HTML')
            return

        if data == "add_filter":
            context.user_data.clear()
            await query.edit_message_text("⚙️ <b>إضافة ترشيح جديد:</b>\n\nأرسل النص بالصيغة: الكلمة → البديل\n\nمثال: سلام → السلام عليكم", reply_markup=get_back_keyboard("dev"), parse_mode='HTML')
            return STATE_ADD_FILTER

        if data.startswith("edit_filter_"):
            filter_id = int(data.split("_")[2])
            session = Session()
            try:
                f = session.query(Filter).filter_by(id=filter_id).first()
                if f:
                    await query.edit_message_text(f"🔍 <b>تعديل الترشيح:</b>\n\nالنص الحالي: {f.word} → {f.replacement}\n\nأرسل النص الجديد بالصيغة: الكلمة → البديل", reply_markup=get_back_keyboard("dev"), parse_mode='HTML')
                    context.user_data['edit_filter_id'] = filter_id
                    return STATE_ADD_FILTER
            finally:
                session.close()

    # --- القنوات ---
    if data == "add_channel_start":
        context.user_data.clear()
        await query.edit_message_text("⚙️ <b>خطوة 1/4:</b>\n\nيرجى إرسال رابط القناة (مثل @channel) أو تحويل رسالة.", reply_markup=get_back_keyboard(role), parse_mode='HTML')
        return STATE_ADD_CHANNEL_LINK

    if data == "manage_channels":
        await show_channels_list(query, role)

    if data.startswith("toggle_channel_"):
        ch_id = int(data.split("_")[2])
        toggle_channel_status(ch_id, query, role)

    if data.startswith("delete_channel_"):
        ch_id = int(data.split("_")[2])
        delete_channel(ch_id, query, role)

    # --- المحتوى ---
    if data == "manage_content":
        buttons = []
        for name, code in CATEGORIES:
            session = Session()
            count = session.query(Content).filter_by(category=code).count()
            session.close()
            buttons.append([InlineKeyboardButton(f"{name} ({count})", callback_data=f"cat_content_{code}")])
        buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"back_{role}")])
        await query.edit_message_text("إحصائيات المحتوى:", reply_markup=InlineKeyboardMarkup(buttons))

    if data.startswith("cat_content_"):
        cat_code = data.split("_")[-1]
        context.user_data['manage_cat'] = cat_code
        buttons = [
            [InlineKeyboardButton("🗑️ حذف المحتوى بالكامل", callback_data="clear_cat_confirm")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="manage_content")]
        ]
        cat_name = next((n for n, c in CATEGORIES if c == cat_code), cat_code)
        await query.edit_message_text(f"قسم: <b>{cat_name}</b>\nاختر إجراء:", reply_markup=InlineKeyboardMarkup(buttons), parse_mode='HTML')

    if data == "clear_cat_confirm":
        cat = context.user_data.get('manage_cat')
        session = Session()
        try:
            deleted = session.query(Content).filter_by(category=cat).delete()
            session.commit()
            await query.edit_message_text(f"✅ تم حذف {deleted} سطر.", reply_markup=get_back_keyboard(role))
        except Exception as e:
            await query.edit_message_text("❌ حدث خطأ.", reply_markup=get_back_keyboard(role))
        finally:
            session.close()

    if data == "upload_content_menu":
        buttons = [[InlineKeyboardButton(name, callback_data=f"upload_{code}")] for name, code in CATEGORIES]
        buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"back_{role}")])
        await query.edit_message_text("اختر القسم لرفع ملف نصي (.txt):", reply_markup=InlineKeyboardMarkup(buttons))

    if data.startswith("upload_"):
        cat = data.split("_")[1]
        context.user_data['upload_category'] = cat
        await query.edit_message_text(f"أرسل ملف .txt الآن.", reply_markup=get_back_keyboard(role))
        return STATE_UPLOAD_CONTENT

    # --- خطوات إضافة القناة ---
    if data.startswith("cat_select_"):
        cat = data.split("_")[-1]
        context.user_data['add_cat'] = cat
        await query.edit_message_text("⚙️ <b>خطوة 3/4:</b>\n\nاختر شكل الرسالة:", reply_markup=get_format_keyboard("fmt_select"), parse_mode='HTML')
        return STATE_ADD_CHANNEL_FORMAT

    if data.startswith("fmt_select_"):
        fmt = data.split("_")[-1]
        context.user_data['add_fmt'] = fmt
        await query.edit_message_text("⚙️ <b>خطوة 4/4:</b>\n\nاختر توقيت النشر:", reply_markup=get_time_keyboard("time_select"), parse_mode='HTML')
        return STATE_ADD_CHANNEL_TIME

    if data.startswith("time_select_"):
        time_type = data.split("_")[-1]
        context.user_data['add_time_type'] = time_type
        
        if time_type == "default":
            save_new_channel(context, user_id)
            await query.edit_message_text("✅ تم إضافة القناة بنجاح (توقيت افتراضي).", reply_markup=get_main_menu(role)[0])
            return ConversationHandler.END
        else:
            msg = "أرسل التوقيت الآن:"
            if time_type == "fixed": msg = "أرسل الساعات مفصولة بفاصلة (مثال: 10, 14, 20):"
            elif time_type == "interval": msg = "أرسل عدد الدقائق (مثال: 60):"
            await query.edit_message_text(msg, reply_markup=get_back_keyboard(role))
            return STATE_ADD_CHANNEL_TIME

    # --- أوامر أخرى ---
    if data == "force_post_now":
        await query.edit_message_text("⏳ جاري النشر...")
        await post_to_channels_logic(context.bot, force_run=True)
        await query.edit_message_text("✅ تم.", reply_markup=get_back_keyboard(role))
    
    if data == "stats":
        txt = get_stats()
        await query.edit_message_text(txt, reply_markup=get_back_keyboard(role), parse_mode='HTML')

async def show_channels_list(query, role):
    session = Session()
    try:
        channels = session.query(Channel).all()
        buttons = []
        for ch in channels:
            status = "🟢" if ch.is_active else "🔴"
            btn_text = f"{status} {ch.title}"
            if role == "dev":
                buttons.append([
                    InlineKeyboardButton(btn_text, callback_data=f"info_channel_{ch.id}"),
                    InlineKeyboardButton("🗑️", callback_data=f"delete_channel_{ch.id}")
                ])
            else:
                buttons.append([InlineKeyboardButton(btn_text, callback_data=f"toggle_channel_{ch.id}")])
        buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"back_{role}")])
        await query.edit_message_text("قائمة القنوات:", reply_markup=InlineKeyboardMarkup(buttons))
    finally:
        session.close()

def toggle_channel_status(ch_id, query, role):
    session = Session()
    try:
        ch = session.query(Channel).filter_by(id=ch_id).first()
        if ch:
            ch.is_active = not ch.is_active
            session.commit()
            show_channels_list(query, role)
    finally:
        session.close()

def delete_channel(ch_id, query, role):
    session = Session()
    try:
        ch = session.query(Channel).filter_by(id=ch_id).first()
        if ch:
            session.delete(ch)
            session.commit()
            show_channels_list(query, role)
    finally:
        session.close()

async def send_user_content(query, cat_code):
    session = Session()
    try:
        content = session.query(Content).filter_by(category=cat_code).order_by(func.random()).first()
        session.close()
        cat_name = next((n for n, c in CATEGORIES if c == cat_code), cat_code)
        if content:
            text = f"✨ <b>{cat_name}</b>\n\n<blockquote>{content.text}</blockquote>"
        else:
            text = f"📭 لا يوجد محتوى."
        buttons = [
            [InlineKeyboardButton("🔄 غيرها", callback_data=f"user_cat_{cat_code}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="user_categories")]
        ]
        try:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode='HTML')
        except:
            pass
    finally:
        session.close()

# --- معالجات النصوص والملفات (منفصلة لكل حالة) ---

async def handle_channel_link_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    info, error = await resolve_channel(context.bot, update.message.text, update.message.forward_from_chat)
    
    if info:
        context.user_data['pending_channel'] = info
        context.user_data['adder_id'] = user_id
        await update.message.reply_text(
            f"✅ تم العثور على القناة: <b>{info['title']}</b>\n\n⚙️ <b>خطوة 2/4:</b>\n\nاختر القسم:",
            reply_markup=get_categories_keyboard("cat_select"),
            parse_mode='HTML'
        )
        return STATE_ADD_CHANNEL_CATEGORY
    else:
        await update.message.reply_text(f"❌ فشل التحقق: {error}\n\nيرجى إعادة المحاولة.")
        return STATE_ADD_CHANNEL_LINK

async def handle_channel_time_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    time_type = context.user_data.get('add_time_type')
    val = update.message.text.strip()
    
    valid = False
    if time_type == "fixed":
        valid = all(x.strip().isdigit() for x in val.split(','))
    elif time_type == "interval":
        valid = val.isdigit()
    
    if valid:
        context.user_data['add_time_value'] = val
        save_new_channel(context, user_id)
        role = get_role(user_id)
        await update.message.reply_text("✅ تمت إضافة القناة بنجاح!", reply_markup=get_main_menu(role)[0])
        return ConversationHandler.END
    else:
        await update.message.reply_text("❌ صيغة التوقيت غير صحيحة. حاول مرة أخرى.")
        return STATE_ADD_CHANNEL_TIME

async def handle_broadcast_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    await update.message.reply_text("⏳ جاري الإرسال...")
    asyncio.create_task(broadcast_worker(context.bot, text))
    role = get_role(update.effective_user.id)
    await update.message.reply_text("✅ تمت الإذاعة بنجاح.", reply_markup=get_main_menu(role)[0])
    return ConversationHandler.END

async def handle_upload_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    cat = context.user_data.get('upload_category')
    
    if doc.mime_type != "text/plain":
        await update.message.reply_text("❌ ملف .txt فقط.")
        return STATE_UPLOAD_CONTENT
    
    await update.message.reply_text("⏳ جاري المعالجة...")
    try:
        file = await doc.get_file()
        bytes_io = await file.download_as_bytearray()
        content_list = bytes_io.decode('utf-8').splitlines()
        count = 0
        session = Session()
        for line in content_list:
            if line.strip():
                content = Content(category=cat, text=line.strip(), added_by=update.effective_user.id)
                session.add(content)
                count += 1
        session.commit()
        session.close()
        role = get_role(update.effective_user.id)
        await update.message.reply_text(f"✅ تمت إضافة {count} نص.", reply_markup=get_main_menu(role)[0], parse_mode='HTML')
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Upload error: {e}")
        await update.message.reply_text("❌ حدث خطأ أثناء المعالجة.")
        return STATE_UPLOAD_CONTENT

async def handle_filter_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if ' → ' not in text:
        await update.message.reply_text("❌ الصيغة غير صحيحة. استخدم: الكلمة → البديل")
        return STATE_ADD_FILTER
    
    word, replacement = text.split(' → ', 1)
    
    session = Session()
    try:
        if 'edit_filter_id' in context.user_data:
            # تعديل ترشيح موجود
            f = session.query(Filter).filter_by(id=context.user_data['edit_filter_id']).first()
            if f:
                f.word = word.strip()
                f.replacement = replacement.strip()
                db_log_action(update.effective_user.id, "EDIT_FILTER", f"{f.word} → {f.replacement}")
        else:
            # إضافة ترشيح جديد
            existing = session.query(Filter).filter_by(word=word.strip()).first()
            if existing:
                await update.message.reply_text("❌ هذه الكلمة موجودة مسبقًا.")
                return STATE_ADD_FILTER
            
            f = Filter(word=word.strip(), replacement=replacement.strip(), added_by=update.effective_user.id)
            session.add(f)
            db_log_action(update.effective_user.id, "ADD_FILTER", f"{f.word} → {f.replacement}")
        
        session.commit()
        role = get_role(update.effective_user.id)
        await update.message.reply_text("✅ تم حفظ الترشيح.", reply_markup=get_main_menu(role)[0])
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Filter error: {e}")
        await update.message.reply_text("❌ حدث خطأ.")
        return STATE_ADD_FILTER
    finally:
        session.close()

async def handle_required_channel_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    if not text.startswith('@'):
        await update.message.reply_text("❌ يجب أن يكون المعيد بداية بـ @")
        return STATE_SET_REQUIRED_CHANNEL
    
    session = Session()
    try:
        channel_info, error = await resolve_channel(context.bot, text, None)
        if not channel_info:
            await update.message.reply_text(f"❌ {error}")
            return STATE_SET_REQUIRED_CHANNEL
        
        # التحقق من أن البوت مشرف في القناة
        member = await context.bot.get_chat_member(channel_info['id'], context.bot.id)
        if member.status not in ['administrator', 'creator']:
            await update.message.reply_text("❌ البوت ليس مشرفًا في هذه القناة.")
            return STATE_SET_REQUIRED_CHANNEL
        
        # حفظ الإعدادات
        setting = session.query(BotSettings).filter_by(key='required_channel').first()
        if setting:
            setting.value = text
            setting.updated_by = update.effective_user.id
        else:
            setting = BotSettings(key='required_channel', value=text, updated_by=update.effective_user.id)
            session.add(setting)
        
        session.commit()
        db_log_action(update.effective_user.id, "SET_REQUIRED_CHANNEL", text)
        
        role = get_role(update.effective_user.id)
        await update.message.reply_text(f"✅ تم تعيين القناة: {channel_info['title']}", reply_markup=get_main_menu(role)[0])
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Required channel error: {e}")
        await update.message.reply_text("❌ حدث خطأ.")
        return STATE_SET_REQUIRED_CHANNEL
    finally:
        session.close()

# --- دالة حل القنوات المحسنة ---
async def resolve_channel(bot, text, forward_chat):
    chat_id, title = None, None
    
    if forward_chat:
        if forward_chat.type in ['channel', 'supergroup']:
            chat_id = forward_chat.id
            title = forward_chat.title
        else:
            return None, "الرسالة المحولة ليست من قناة."
    
    if not chat_id:
        txt = text.strip()
        try:
            if "t.me/+" in txt or "joinchat" in txt:
                return None, "روابط الانضمام غير مدعومة. استخدم المعرف أو التحويل."
            if "t.me/c/" in txt:
                return None, "الروابط العميقة غير مدعومة مباشرة."

            if txt.startswith("@"):
                chat_obj = await bot.get_chat(txt)
                chat_id = chat_obj.id
                title = chat_obj.title
            elif "t.me/" in txt:
                username = txt.split("t.me/")[-1].split("/")[0].split("?")[0]
                chat_obj = await bot.get_chat(f"@{username}")
                chat_id = chat_obj.id
                title = chat_obj.title
        except Exception as e:
            err_str = str(e)
            if "Chat not found" in err_str: return None, "القناة غير موجودة."
            if "Forbidden" in err_str: return None, "البوت ليس مشرفًا أو محظور."
            return None, f"خطأ: {err_str}"
    
    if not chat_id: return None, "لم أستطع تحديد القناة."

    try:
        member = await bot.get_chat_member(chat_id, bot.id)
        if member.status in ['administrator', 'creator']:
            return {'id': chat_id, 'title': title}, None
        else:
            return None, "البوت ليس مشرفًا في هذه القناة."
    except Exception as e:
        return None, f"فشل التحقق: {e}"

def get_global_status():
    session = Session()
    try:
        setting = session.query(BotSettings).filter_by(key='global_status').first()
        return setting.value == 'on' if setting else True
    finally:
        session.close()

def save_new_channel(context, user_id):
    data = context.user_data.get('pending_channel')
    if not data: return
    
    session = Session()
    try:
        exists = session.query(Channel).filter_by(channel_id=data['id']).first()
        if exists: return

        new_ch = Channel(
            channel_id=data['id'],
            title=data['title'],
            category=context.user_data.get('add_cat', 'عام'),
            msg_format=context.user_data.get('add_fmt', 'normal'),
            time_type=context.user_data.get('add_time_type', 'default'),
            time_value=context.user_data.get('add_time_value'),
            is_active=True,
            added_by=user_id,
            added_at=datetime.now()
        )
        session.add(new_ch)
        session.commit()
        db_log_action(user_id, "ADD_CHANNEL", f"Added {data['title']}")
    except Exception as e:
        logger.error(f"Error saving channel: {e}")
    finally:
        session.close()

async def post_to_channels_logic(bot, force_run=False):
    session = Session()
    try:
        global_set = session.query(BotSettings).filter_by(key='global_status').first()
        if not force_run and (not global_set or global_set.value == 'off'):
            session.close()
            return

        channels = session.query(Channel).filter_by(is_active=True).all()
        now = datetime.now()
        
        for ch in channels:
            try:
                should_post = False
                if force_run: should_post = True
                elif ch.time_type == 'default':
                    # تغيير النسبة من 5% إلى 2%
                    if random.random() < 0.02: should_post = True
                elif ch.time_type == 'fixed':
                    if ch.time_value:
                        hours = [int(h) for h in ch.time_value.split(',')]
                        if now.hour in hours:
                            if not ch.last_post_at or ch.last_post_at.hour != now.hour: should_post = True
                elif ch.time_type == 'interval':
                    if ch.time_value:
                        mins = int(ch.time_value)
                        if not ch.last_post_at: should_post = True
                        elif (now - ch.last_post_at).total_seconds() >= (mins * 60): should_post = True
                
                if should_post:
                    content = session.query(Content).filter_by(category=ch.category).order_by(func.random()).first()
                    if content:
                        text = await filter_text(content.text)
                        if ch.msg_format == 'blockquote': 
                            text = f"<blockquote>{text}</blockquote>"
                        try:
                            await bot.send_message(ch.channel_id, text, parse_mode='HTML')
                            ch.last_post_at = now
                            session.commit()
                            logger.info(f"Posted to {ch.title}")
                            await asyncio.sleep(1) 
                        except Exception as e:
                            logger.error(f"Failed to post to {ch.title}: {e}")
                            if "chat not found" in str(e).lower() or "forbidden" in str(e).lower():
                                logger.warning(f"Channel {ch.title} may have been deleted, deactivating...")
                                ch.is_active = False
                                session.commit()
            except Exception as e:
                logger.error(f"Error in loop for channel {ch.title if ch else 'Unknown'}: {e}")
    finally:
        session.close()

async def broadcast_worker(bot, text):
    session = Session()
    try:
        users = session.query(User).filter(User.is_banned == False).all()
        count = 0
        failed_count = 0
        updated_users = 0
        
        for u in users:
            try:
                await bot.send_message(u.user_id, text)
                count += 1
                await asyncio.sleep(0.1)
            except Exception as e:
                failed_count += 1
                if "user is deactivated" in str(e).lower() or "user not found" in str(e).lower():
                    # تحديث حالة المستخدم إذا كان محذوفًا
                    user = session.query(User).filter_by(user_id=u.user_id).first()
                    if user:
                        user.is_banned = True
                        updated_users += 1
        
        if updated_users > 0:
            session.commit()
        
        logger.info(f"Broadcast completed: {count} sent, {failed_count} failed, {updated_users} users updated")
    finally:
        session.close()

# --- التشغيل ---
def main():
    global application
    application = Application.builder().token(TOKEN).build()

    # محادثة إضافة قناة
    add_channel_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern="^add_channel_start$")],
        states={
            STATE_ADD_CHANNEL_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_channel_link_step)],
            STATE_ADD_CHANNEL_CATEGORY: [CallbackQueryHandler(button_handler, pattern="^cat_select_")],
            STATE_ADD_CHANNEL_FORMAT: [CallbackQueryHandler(button_handler, pattern="^fmt_select_")],
            STATE_ADD_CHANNEL_TIME: [
                CallbackQueryHandler(button_handler, pattern="^time_select_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_channel_time_step)
            ],
        },
        fallbacks=[CallbackQueryHandler(button_handler, pattern="^back_")],
        name="add_channel_conv",
        persistent=False
    )

    # محادثة رفع المحتوى
    upload_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern="^upload_")],
        states={
            STATE_UPLOAD_CONTENT: [MessageHandler(filters.Document.ALL, handle_upload_step)]
        },
        fallbacks=[CallbackQueryHandler(button_handler, pattern="^back_")],
        name="upload_conv",
        persistent=False
    )
    
    # محادثة الترشيحات
    filters_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern="^(add_filter|set_required_channel)$")],
        states={
            STATE_ADD_FILTER: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_filter_step)],
            STATE_SET_REQUIRED_CHANNEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_required_channel_step)]
        },
        fallbacks=[CallbackQueryHandler(button_handler, pattern="^back_")],
        name="filters_conv",
        persistent=False
    )

    # تسجيل الهاندلرز
    application.add_handler(CommandHandler("start", start))
    application.add_handler(add_channel_conv)
    application.add_handler(upload_conv)
    application.add_handler(filters_conv)
    application.add_handler(CallbackQueryHandler(button_handler))

    if application.job_queue:
        application.job_queue.run_repeating(post_to_channels_logic, interval=60, first=10)

    logger.info("Bot started polling...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
