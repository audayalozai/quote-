import logging
import asyncio
import random
import json
import io
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional

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

# --- إعدادات البوت (هام جداً: عدل هذه القيم) ---
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

# --- قاعدة البيانات ---
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text, func
from sqlalchemy.orm import declarative_base, sessionmaker

engine = create_engine('sqlite:///bot_data.db', echo=False)
Base = declarative_base()
Session = sessionmaker(bind=engine)

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, unique=True, index=True)
    username = Column(String, nullable=True)
    is_admin = Column(Boolean, default=False)
    is_banned = Column(Boolean, default=False)
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

class Content(Base):
    __tablename__ = 'content'
    id = Column(Integer, primary_key=True)
    category = Column(String, index=True)
    text = Column(Text)
    added_at = Column(DateTime, default=datetime.now)

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

Base.metadata.create_all(engine)

# --- دوال مساعدة ---
def db_log_action(user_id, action, details=""):
    session = Session()
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
    
    session = Session()
    try:
        user = session.query(User).filter_by(user_id=user_id).first()
        if user and user.is_admin: return "admin"
        if user and user.is_banned: return "banned"
    finally:
        session.close()
    return "user"

# --- الثوابت ---
CATEGORIES = [
    ("❤️ حب", "حب"),
    ("🎂 عيد ميلاد", "عيد ميلاد"),
    ("💭 اقتباسات عامة", "اقتباسات عامة"),
    ("📜 ابيات شعرية", "ابيات شعرية"),
    ("📚 ديني", "ديني"),
    ("😂 مضحك", "مضحك")
]

STATE_ADD_CHANNEL_LINK = 1
STATE_ADD_CHANNEL_CATEGORY = 2
STATE_ADD_CHANNEL_FORMAT = 3
STATE_ADD_CHANNEL_TIME = 4
STATE_BROADCAST_MSG = 5
STATE_BAN_USER_ID = 6
STATE_UPLOAD_CONTENT = 7

# --- الكيبوردات ---
def get_main_menu(role):
    if role == "dev":
        buttons = [
            [InlineKeyboardButton("📢 إضافة قناة", callback_data="add_channel_start")],
            [InlineKeyboardButton("📢 إدارة القنوات", callback_data="manage_channels")],
            [InlineKeyboardButton("📝 رفع محتوى", callback_data="upload_content_menu")],
            [InlineKeyboardButton("📂 إدارة المحتوى", callback_data="manage_content")],
            [InlineKeyboardButton("📊 الإحصائيات", callback_data="stats")],
        ]
    elif role == "admin":
        buttons = [
            [InlineKeyboardButton("📢 إضافة قناة", callback_data="add_channel_start")],
            [InlineKeyboardButton("📢 إدارة القنوات", callback_data="manage_channels")],
            [InlineKeyboardButton("📝 رفع محتوى", callback_data="upload_content_menu")],
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

# --- معالجة الأوامر ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username
    
    role = get_role(user_id)
    if role == "banned":
        await update.message.reply_text("⛔️ تم حظرك من استخدام البوت.")
        return

    session = Session()
    try:
        user = session.query(User).filter_by(user_id=user_id).first()
        if not user:
            user = User(user_id=user_id, username=username)
            session.add(user)
            session.commit()
            db_log_action(user_id, "JOIN", f"New user: @{username}")
        elif user.username != username:
            user.username = username
            session.commit()
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

    # --- القنوات ---
    if data == "add_channel_start":
        context.user_data.clear()
        # تعيين الحالة يدوياً
        context.user_data['state'] = STATE_ADD_CHANNEL_LINK
        await query.edit_message_text("⚙️ <b>خطوة 1/4:</b>\n\nيرجى إرسال رابط القناة (معرف مثل @channel) أو تحويل رسالة منها.", reply_markup=get_back_keyboard(role), parse_mode='HTML')
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
        context.user_data['state'] = STATE_UPLOAD_CONTENT
        await query.edit_message_text(f"أرسل ملف .txt الآن.", reply_markup=get_back_keyboard(role))
        return STATE_UPLOAD_CONTENT

    # --- خطوات إضافة القناة ---
    if data.startswith("cat_select_"):
        cat = data.split("_")[-1]
        context.user_data['add_cat'] = cat
        context.user_data['state'] = STATE_ADD_CHANNEL_FORMAT # تحديث الحالة
        await query.edit_message_text("⚙️ <b>خطوة 3/4:</b>\n\nاختر شكل الرسالة:", reply_markup=get_format_keyboard("fmt_select"))
        return STATE_ADD_CHANNEL_FORMAT

    if data.startswith("fmt_select_"):
        fmt = data.split("_")[-1]
        context.user_data['add_fmt'] = fmt
        context.user_data['state'] = STATE_ADD_CHANNEL_TIME # تحديث الحالة
        await query.edit_message_text("⚙️ <b>خطوة 4/4:</b>\n\nاختر توقيت النشر:", reply_markup=get_time_keyboard("time_select"))
        return STATE_ADD_CHANNEL_TIME

    if data.startswith("time_select_"):
        time_type = data.split("_")[-1]
        context.user_data['add_time_type'] = time_type
        
        if time_type == "default":
            save_new_channel(context)
            await query.edit_message_text("✅ تم إضافة القناة بنجاح (توقيت افتراضي).", reply_markup=get_main_menu(role)[0])
            return ConversationHandler.END
        else:
            msg = "أرسل التوقيت الآن:"
            if time_type == "fixed": msg = "أرسل الساعات مفصولة بفاصلة (مثال: 10, 14, 20):"
            elif time_type == "interval": msg = "أرسل عدد الدقائق (مثال: 60):"
            await query.edit_message_text(msg, reply_markup=get_back_keyboard(role))
            # نستمر في نفس الحالة TIME بانتظار النص
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
    session.close()
    await query.edit_message_text("قائمة القنوات:", reply_markup=InlineKeyboardMarkup(buttons))

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

# --- معالجة النصوص والملفات (التحسين الجديد) ---

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get('state')
    
    # 1. حالة إضافة رابط القناة
    if state == STATE_ADD_CHANNEL_LINK:
        info, error = await resolve_channel(context.bot, update.message.text, update.message.forward_from_chat)
        
        if info:
            context.user_data['pending_channel'] = info
            context.user_data['state'] = STATE_ADD_CHANNEL_CATEGORY
            await update.message.reply_text(
                f"✅ تم العثور على القناة: <b>{info['title']}</b>\n\n⚙️ <b>خطوة 2/4:</b>\n\nاختر القسم:",
                reply_markup=get_categories_keyboard("cat_select"),
                parse_mode='HTML'
            )
        else:
            # عند الخطأ، نظهر الرسالة ولكن **لا نغلق المحادثة** ولا نمسح الحالة ليسمح بإعادة المحاولة
            await update.message.reply_text(f"❌ فشل التحقق: {error}\n\nتأكد من إرسال معرف (مثل @channel) أو تحويل رسالة، وأن البوت مشرف في القناة.")
        return

    # 2. حالة توقيت النشر
    if state == STATE_ADD_CHANNEL_TIME:
        time_type = context.user_data.get('add_time_type')
        val = update.message.text.strip()
        
        valid = False
        if time_type == "fixed":
            valid = all(x.strip().isdigit() for x in val.split(','))
        elif time_type == "interval":
            valid = val.isdigit()
        
        if valid:
            context.user_data['add_time_value'] = val
            save_new_channel(context)
            role = get_role(update.effective_user.id)
            await update.message.reply_text("✅ تمت إضافة القناة بنجاح!", reply_markup=get_main_menu(role)[0])
            context.user_data.clear() # مسح البيانات فقط عند النجاح النهائي
        else:
            await update.message.reply_text("❌ صيغة التوقيت غير صحيحة. حاول مرة أخرى.")
        return

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('state') == STATE_UPLOAD_CONTENT:
        doc = update.message.document
        cat = context.user_data.get('upload_category')
        
        if doc.mime_type != "text/plain":
            await update.message.reply_text("❌ ملف .txt فقط.")
            return
        
        await update.message.reply_text("⏳ جاري المعالجة...")
        try:
            file = await doc.get_file()
            bytes_io = await file.download_as_bytearray()
            content_list = bytes_io.decode('utf-8').splitlines()
            count = 0
            session = Session()
            for line in content_list:
                if line.strip():
                    session.add(Content(category=cat, text=line.strip()))
                    count += 1
            session.commit()
            session.close()
            role = get_role(update.effective_user.id)
            await update.message.reply_text(f"✅ تمت إضافة {count} نص.", reply_markup=get_main_menu(role)[0], parse_mode='HTML')
            context.user_data.clear()
        except Exception as e:
            logger.error(f"Upload error: {e}")
            await update.message.reply_text("❌ حدث خطأ.")

# --- دالة حل القنوات المحسنة ---
async def resolve_channel(bot, text, forward_chat):
    """
    ترجع (dict_info, None) عند النجاح أو (None, error_message) عند الفشل.
    """
    chat_id, title = None, None
    
    # 1. محاولة من الرسالة المحولة (أفضل طريقة)
    if forward_chat:
        if forward_chat.type in ['channel', 'supergroup']:
            chat_id = forward_chat.id
            title = forward_chat.title
        else:
            return None, "الرسالة المحولة ليست من قناة أو مجموعة."
    
    # 2. محاولة من النص (الرابط أو المعرف)
    if not chat_id:
        txt = text.strip()
        try:
            # التحقق من الروابط غير المدعومة أولاً لتوضيح الأمر للمستخدم
            if "t.me/+" in txt or "joinchat" in txt:
                return None, "روابط الانضمام (t.me/+) غير مدعومة. استخدم معرف القناة (مثل @name) أو قم بتحويل رسالة."
            
            if "t.me/c/" in txt:
                return None, "الروابط العميقة (Deep Links) غير مدعومة مباشرة. يرجى تحويل رسالة من القناة."

            # المحاولة عبر المعرف
            if txt.startswith("@"):
                chat_obj = await bot.get_chat(txt)
                chat_id = chat_obj.id
                title = chat_obj.title
            
            # المحاولة عبر الرابط العام
            elif "t.me/" in txt:
                username = txt.split("t.me/")[-1].split("/")[0].split("?")[0]
                chat_obj = await bot.get_chat(f"@{username}")
                chat_id = chat_obj.id
                title = chat_obj.title
            
        except Exception as e:
            # رسائل خطأ واضحة
            err_str = str(e)
            if "Chat not found" in err_str:
                return None, "لم يتم العثور على القناة. تأكد من المعرف أو أن البوت عضو فيها."
            if "Forbidden" in err_str or "bot was blocked" in err_str:
                return None, "البوت محظور أو ليس لديه صلاحيات للوصول للقناة."
            return None, f"خطأ غير متوقع: {err_str}"
    
    if not chat_id:
        return None, "لم أستطع تحديد القناة من النص المرسل."

    # 3. التحقق من صلاحيات البوت (هل هو مشرف؟)
    try:
        member = await bot.get_chat_member(chat_id, bot.id)
        if member.status in ['administrator', 'creator']:
            return {'id': chat_id, 'title': title}, None
        else:
            return None, "البوت موجود في القناة لكنه ليس مشرفاً. يجب رفع البوت مشرفاً أولاً."
    except Exception as e:
        return None, f"فشل التحقق من الصلاحيات: {e}"

def save_new_channel(context):
    data = context.user_data.get('pending_channel')
    if not data: return
    
    session = Session()
    try:
        # التأكد من عدم وجود تكرار
        exists = session.query(Channel).filter_by(channel_id=data['id']).first()
        if exists:
            logger.info(f"Channel {data['title']} already exists.")
            return

        new_ch = Channel(
            channel_id=data['id'],
            title=data['title'],
            category=context.user_data.get('add_cat', 'عام'),
            msg_format=context.user_data.get('add_fmt', 'normal'),
            time_type=context.user_data.get('add_time_type', 'default'),
            time_value=context.user_data.get('add_time_value'),
            is_active=True
        )
        session.add(new_ch)
        session.commit()
        db_log_action(context._user_id, "ADD_CHANNEL", f"Added {data['title']}")
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
                    if random.random() < 0.05: should_post = True
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
                        text = content.text
                        if ch.msg_format == 'blockquote': text = f"<blockquote>{text}</blockquote>"
                        try:
                            await bot.send_message(ch.channel_id, text, parse_mode='HTML')
                            ch.last_post_at = now
                            session.commit()
                            logger.info(f"Posted to {ch.title}")
                            await asyncio.sleep(1) 
                        except Exception as e:
                            logger.error(f"Failed to post to {ch.title}: {e}")
                            if "Forbidden" in str(e) or "chat not found" in str(e):
                                ch.is_active = False
                                session.commit()
            except Exception as e:
                logger.error(f"Error in loop: {e}")
    finally:
        session.close()

def get_stats():
    session = Session()
    try:
        u = session.query(User).count()
        c = session.query(Content).count()
        return f"👥 {u} مستخدم | 📝 {c} نص."
    finally:
        session.close()

# --- التشغيل ---
def main():
    application = Application.builder().token(TOKEN).build()

    add_channel_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern="^add_channel_start$")],
        states={
            STATE_ADD_CHANNEL_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)],
            STATE_ADD_CHANNEL_CATEGORY: [CallbackQueryHandler(button_handler, pattern="^cat_select_")],
            STATE_ADD_CHANNEL_FORMAT: [CallbackQueryHandler(button_handler, pattern="^fmt_select_")],
            STATE_ADD_CHANNEL_TIME: [
                CallbackQueryHandler(button_handler, pattern="^time_select_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
            ],
        },
        fallbacks=[CallbackQueryHandler(button_handler, pattern="^back_")],
        name="add_channel_conv"
    )

    upload_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern="^upload_")],
        states={
            STATE_UPLOAD_CONTENT: [MessageHandler(filters.Document.ALL, handle_document)]
        },
        fallbacks=[CallbackQueryHandler(button_handler, pattern="^back_")],
        name="upload_conv"
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(add_channel_conv)
    application.add_handler(upload_conv)
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    if application.job_queue:
        application.job_queue.run_repeating(post_to_channels_logic, interval=60, first=10)

    logger.info("Bot started...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
