import logging
import asyncio
import random
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
    ChatMemberHandler
)
import config
import database as db

# التأكد من تهيئة قاعدة البيانات
db.init_db()

# إعداد التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- دوال مساعدة ---

async def is_bot_admin_in_channel(bot, channel_id):
    """التحقق ما إذا كان البوت مشرف في القناة"""
    try:
        chat_member = await bot.get_chat_member(channel_id, bot.id)
        return chat_member.status in ['administrator', 'creator']
    except Exception as e:
        logger.error(f"Error checking admin status: {e}")
        return False

async def send_notification_to_admins(bot, message: str):
    """إرسال تنبيه للمطور والمشرفين"""
    session = db.Session()
    try:
        admins = session.query(db.User).filter_by(is_admin=True).all()
        for admin in admins:
            try:
                await bot.send_message(chat_id=admin.user_id, text=message, parse_mode='HTML')
            except Exception:
                pass
        
        try:
            await bot.send_message(chat_id=config.DEVELOPER_ID, text=message, parse_mode='HTML')
        except Exception:
            pass
    finally:
        session.close()

# --- Keyboards ---

def get_dev_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📂 إدارة الملفات", callback_data="manage_files")],
        [InlineKeyboardButton("🔧 إدارة القنوات", callback_data="manage_channels")],
        [InlineKeyboardButton("👥 إدارة المشرفين", callback_data="manage_admins")],
        [InlineKeyboardButton("➕ إضافة قناة نشر", callback_data="add_channel_prompt")],
        [InlineKeyboardButton("📊 الإحصائيات", callback_data="show_stats")],
        [InlineKeyboardButton("🔊 إرسال إذاعة", callback_data="broadcast_menu")],
        [InlineKeyboardButton("⚙️ تفعيل/ايقاف النشر", callback_data="toggle_posting")],
        [InlineKeyboardButton("🚀 نشر الآن (منشور واحد)", callback_data="post_now")]
    ])

def get_admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📂 إدارة الملفات", callback_data="manage_files")],
        [InlineKeyboardButton("🔧 إدارة القنوات", callback_data="manage_channels")],
        [InlineKeyboardButton("➕ إضافة قناة نشر", callback_data="add_channel_prompt")],
        [InlineKeyboardButton("📊 الإحصائيات", callback_data="show_stats")],
        [InlineKeyboardButton("🔊 إرسال إذاعة", callback_data="broadcast_menu")],
        [InlineKeyboardButton("⚙️ تفعيل/ايقاف النشر", callback_data="toggle_posting")],
        [InlineKeyboardButton("🚀 نشر الآن (منشور واحد)", callback_data="post_now")]
    ])

def get_user_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة قناة/مجموعة", callback_data="add_channel_prompt")],
        [InlineKeyboardButton("📊 الإحصائيات", callback_data="show_stats")]
    ])

def get_back_keyboard(role):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"back_{role}")]])

def get_categories_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❤️ حب", callback_data="cat_حب")],
        [InlineKeyboardButton("🎂 عيد ميلاد", callback_data="cat_عيد ميلاد")],
        [InlineKeyboardButton("💭 اقتباسات عامة", callback_data="cat_اقتباسات عامة")],
        [InlineKeyboardButton("📜 ابيات شعرية", callback_data="cat_ابيات شعرية")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]
    ])

def get_format_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 رسالة عادية", callback_data="fmt_normal")],
        [InlineKeyboardButton("💎 Blockquote", callback_data="fmt_blockquote")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]
    ])

def get_time_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏰ ساعات محددة", callback_data="time_fixed")],
        [InlineKeyboardButton("⏳ فارق زمني (دقائق)", callback_data="time_interval")],
        [InlineKeyboardButton("🚫 افتراضي (عشوائي/فوري)", callback_data="time_default")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]
    ])

def get_files_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❤️ حب", callback_data="upload_حب")],
        [InlineKeyboardButton("🎂 عيد ميلاد", callback_data="upload_عيد ميلاد")],
        [InlineKeyboardButton("💭 اقتباسات عامة", callback_data="upload_اقتباسات عامة")],
        [InlineKeyboardButton("📜 ابيات شعرية", callback_data="upload_ابيات شعرية")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_admin")]
    ])

def get_categories_keyboard_edit(ch_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❤️ حب", callback_data=f"set_edit_cat_{ch_id}_حب")],
        [InlineKeyboardButton("🎂 عيد ميلاد", callback_data=f"set_edit_cat_{ch_id}_عيد ميلاد")],
        [InlineKeyboardButton("💭 اقتباسات عامة", callback_data=f"set_edit_cat_{ch_id}_اقتباسات عامة")],
        [InlineKeyboardButton("📜 ابيات شعرية", callback_data=f"set_edit_cat_{ch_id}_ابيات شعرية")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=f"edit_channel_{ch_id}")]
    ])

def get_format_keyboard_edit(ch_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 رسالة عادية", callback_data=f"set_edit_fmt_{ch_id}_normal")],
        [InlineKeyboardButton("💎 Blockquote", callback_data=f"set_edit_fmt_{ch_id}_blockquote")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=f"edit_channel_{ch_id}")]
    ])

# --- Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username
    
    session = db.Session()
    try:
        user = session.query(db.User).filter_by(user_id=user_id).first()
        is_new_user = False
        if not user:
            user = db.User(user_id=user_id, username=username)
            session.add(user)
            session.commit()
            is_new_user = True
        elif username != user.username:
            user.username = username
            session.commit()
            
        if is_new_user:
            user_tag = f"@{username}" if username else "بدون يوزر"
            msg = f"🔔 <b>تنبيه:</b> دخول شخص جديد.\n👤 الاسم: {user_tag}\n🆔 الآيدي: <code>{user_id}</code>"
            await send_notification_to_admins(context.bot, msg)
    finally:
        session.close()

    welcome_text = "أهلاً بك في بوت النشر التلقائي! 🤖"
    
    kb = get_dev_keyboard() if user_id == config.DEVELOPER_ID else (get_admin_keyboard() if db.is_admin(user_id) else get_user_keyboard())
    title = "لوحة المطور" if user_id == config.DEVELOPER_ID else ("لوحة المشرف" if db.is_admin(user_id) else "القائمة الرئيسية")
    
    await update.message.reply_text(f"{welcome_text}\n\n🔹 <b>{title}</b> 🔹", reply_markup=kb, parse_mode='HTML')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    
    role = "dev" if user_id == config.DEVELOPER_ID else ("admin" if db.is_admin(user_id) else "user")

    # إدارة القنوات
    if data == "manage_channels" and role in ["dev", "admin"]:
        session = db.Session()
        try:
            channels = session.query(db.Channel).all()
            if not channels:
                await query.edit_message_text("لا توجد قنوات مضافة حالياً.", reply_markup=get_back_keyboard(role))
                return
            keyboard = [[InlineKeyboardButton(f"{ch.title} ({ch.category})", callback_data=f"edit_channel_{ch.id}")] for ch in channels]
            keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"back_{role}")])
            await query.edit_message_text("اختر قناة لإعداداتها:", reply_markup=InlineKeyboardMarkup(keyboard))
        finally:
            session.close()
        return

    if data.startswith("edit_channel_") and data != "edit_channel_time":
        if role not in ["dev", "admin"]: return
        try: ch_id = int(data.split("_")[2])
        except: return
        context.user_data['editing_channel_id'] = ch_id
        keyboard = [
            [InlineKeyboardButton("🔄 تغيير نوع المحتوى", callback_data="change_cat_select")],
            [InlineKeyboardButton("🎨 تغيير شكل الرسالة", callback_data="change_fmt_select")],
            [InlineKeyboardButton("⏰ تغيير الوقت", callback_data="edit_channel_time")], 
            [InlineKeyboardButton("🗑️ حذف القناة", callback_data="confirm_del_channel")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="manage_channels")]
        ]
        await query.edit_message_text("خيارات القناة:", reply_markup=InlineKeyboardMarkup(keyboard))

    if data == "confirm_del_channel":
        ch_id = context.user_data.get('editing_channel_id')
        keyboard = [
            [InlineKeyboardButton("❌ لا، ارجع", callback_data=f"edit_channel_{ch_id}")],
            [InlineKeyboardButton("✅ نعم، احذف القناة", callback_data=f"delete_channel_{ch_id}")]
        ]
        await query.edit_message_text("⚠️ هل أنت متأكد من حذف هذه القناة من النظام؟", reply_markup=InlineKeyboardMarkup(keyboard))

    if data.startswith("delete_channel_"):
        ch_id = int(data.split("_")[2])
        session = db.Session()
        try:
            ch = session.query(db.Channel).filter_by(id=ch_id).first()
            if ch:
                title = ch.title
                session.delete(ch)
                session.commit()
                msg = f"✅ تم حذف القناة <b>{title}</b> بنجاح."
            else:
                msg = "❌ لم يتم العثور على القناة."
            context.user_data['editing_channel_id'] = None
        except Exception as e:
            session.rollback()
            msg = f"❌ خطأ: {e}"
        finally:
            session.close()
        await query.edit_message_text(msg, parse_mode='HTML', reply_markup=get_back_keyboard(role))

    if data == "change_cat_select":
        ch_id = context.user_data.get('editing_channel_id')
        await query.edit_message_text("اختر نوع المحتوى الجديد:", reply_markup=get_categories_keyboard_edit(ch_id))

    if data.startswith("set_edit_cat_"):
        try:
            parts = data.split("_")
            ch_id = int(parts[3])
            new_cat = parts[4]
            session = db.Session()
            try:
                ch = session.query(db.Channel).filter_by(id=ch_id).first()
                if ch:
                    ch.category = new_cat
                    session.commit()
                    msg = f"✅ تم تغيير نوع المحتوى إلى <b>{new_cat}</b>."
                else:
                    msg = "❌ حدث خطأ."
            finally:
                session.close()
            await query.edit_message_text(msg, parse_mode='HTML', reply_markup=get_back_keyboard(role))
        except: pass

    if data == "change_fmt_select":
        ch_id = context.user_data.get('editing_channel_id')
        await query.edit_message_text("اختر شكل الرسالة الجديد:", reply_markup=get_format_keyboard_edit(ch_id))

    if data.startswith("set_edit_fmt_"):
        try:
            parts = data.split("_")
            ch_id = int(parts[3])
            new_fmt = parts[4]
            session = db.Session()
            try:
                ch = session.query(db.Channel).filter_by(id=ch_id).first()
                if ch:
                    ch.msg_format = new_fmt
                    session.commit()
                    msg = f"✅ تم تغيير شكل الرسالة إلى <b>{new_fmt}</b>."
                else:
                    msg = "❌ حدث خطأ."
            finally:
                session.close()
            await query.edit_message_text(msg, parse_mode='HTML', reply_markup=get_back_keyboard(role))
        except: pass

    if data == "edit_channel_time":
        ch_id = context.user_data.get('editing_channel_id')
        context.user_data['mode'] = 'edit'
        await query.edit_message_text("اختر طريقة النشر الجديدة:", reply_markup=get_time_keyboard())

    # إدارة المشرفين (Dev Only)
    if data == "manage_admins":
        if role != "dev":
            await query.edit_message_text("⛔️ هذا القسم للمطور فقط.", reply_markup=get_back_keyboard(role))
            return
        keyboard = [
            [InlineKeyboardButton("➕ إضافة مشرف", callback_data="add_admin_step1")],
            [InlineKeyboardButton("➖ حذف مشرف", callback_data="del_admin_step1")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back_dev")]
        ]
        await query.edit_message_text("اختر العملية:", reply_markup=InlineKeyboardMarkup(keyboard))

    if data == "add_admin_step1":
        context.user_data['action'] = 'add_admin'
        await query.edit_message_text("أرسل الآن (آيدي) أو (معرف المستخدم) للإضافة:", reply_markup=get_back_keyboard(role))

    if data == "del_admin_step1":
        context.user_data['action'] = 'del_admin'
        await query.edit_message_text("أرسل الآن (آيدي) أو (معرف المستخدم) للحذف:", reply_markup=get_back_keyboard(role))

    # إدارة الملفات
    if data == "manage_files" and role in ["dev", "admin"]:
        await query.edit_message_text("اختر القسم لرفع ملفات الاقتباسات (txt):", reply_markup=get_files_keyboard())

    if data.startswith("upload_"):
        category = data.split("_")[1]
        context.user_data['upload_category'] = category
        await query.edit_message_text(f"تم اختيار قسم: <b>{category}</b>\n\nالآن قم بإرسال ملف <code>.txt</code> يحتوي على الاقتباسات.", parse_mode='HTML', reply_markup=get_back_keyboard(role))

    if data == "add_channel_prompt":
        context.user_data['step'] = 'waiting_channel'
        await query.edit_message_text("✏️ أرسل الآن:\n1. رابط القناة العامة (مثلاً @Channel أو https://t.me/...)\n2. أو قم بتحويل رسالة (Forward) من القناة", reply_markup=get_back_keyboard(role))

    # اختيار القسم/التنسيق/الوقت أثناء الإضافة
    if data.startswith("cat_"):
        category = data.split("_")[1]
        context.user_data['selected_category'] = category
        await query.edit_message_text(f"تم اختيار القسم: <b>{category}</b>.\n\nاختر شكل الرسالة:", parse_mode='HTML', reply_markup=get_format_keyboard())

    if data.startswith("fmt_"):
        fmt = data.split("_")[1]
        context.user_data['selected_format'] = fmt
        await query.edit_message_text("اختر طريقة النشر:", reply_markup=get_time_keyboard())

    if data.startswith("time_"):
        time_type = data.split("_")[1]
        context.user_data['time_type'] = time_type
        
        # إذا كان وضع التعديل
        if context.user_data.get('mode') == 'edit':
            ch_id = context.user_data.get('editing_channel_id')
            session = db.Session()
            try:
                ch = session.query(db.Channel).filter_by(id=ch_id).first()
                if ch:
                    ch.time_type = time_type
                    if time_type == "default":
                        ch.time_value = None
                        session.commit()
                        await query.edit_message_text("✅ تم تغيير الوقت إلى <b>افتراضي</b>.", parse_mode='HTML', reply_markup=get_back_keyboard(role))
                    else:
                        msg = f"أرسل القيمة الجديدة للوقت:\n"
                        if time_type == "fixed": msg += "الساعات (مثلاً: 10, 14, 20)"
                        elif time_type == "interval": msg += "الدقائق (مثلاً: 60)"
                        context.user_data['action'] = f'set_{time_type}_time_edit'
                        await query.edit_message_text(msg, reply_markup=get_back_keyboard(role))
            finally:
                session.close()
        else:
            # وضع الإضافة
            if time_type == "default":
                await finalize_channel_addition_logic(query, role, context)
            else:
                msg = ""
                if time_type == "fixed":
                    context.user_data['action'] = 'set_fixed_time'
                    msg = "أرسل الساعات المطلوبة (مثلاً: 10, 14, 20) مفصولة بفاصلة:"
                elif time_type == "interval":
                    context.user_data['action'] = 'set_interval'
                    msg = "أرسل الفارق الزمني بالدقائق (مثلاً: 60):"
                await query.edit_message_text(msg, reply_markup=get_back_keyboard(role))

    if data == "show_stats":
        stats = db.get_stats()
        await query.edit_message_text(stats, parse_mode='HTML', reply_markup=get_back_keyboard(role))

    # زر الرجوع
    if data in ["back_home", "back_dev", "back_admin", "back_user"]:
        context.user_data.clear()
        if data == "back_home": kb = get_user_keyboard(); title = "القائمة الرئيسية:"
        elif data == "back_dev": kb = get_dev_keyboard(); title = "لوحة المطور:"
        elif data == "back_admin": kb = get_admin_keyboard(); title = "لوحة المشرف:"
        else: kb = get_user_keyboard(); title = "القائمة الرئيسية:"
        await query.edit_message_text(title, reply_markup=kb)

    if data == "toggle_posting" and role in ["dev", "admin"]:
        session = db.Session()
        try:
            setting = session.query(db.BotSettings).filter_by(key='posting_status').first()
            new_status = 'off' if (setting and setting.value == 'on') else 'on'
            if setting:
                setting.value = new_status
            else:
                session.add(db.BotSettings(key='posting_status', value=new_status))
            session.commit()
            state_text = "🟢 مفعل" if new_status == 'on' else "🔴 متوقف"
            await query.edit_message_text(f"تم تغيير حالة النشر إلى: <b>{state_text}</b>", parse_mode='HTML', reply_markup=get_back_keyboard(role))
        finally:
            session.close()

    if data == "post_now":
        await query.edit_message_text("جاري بدء النشر الفوري...")
        await post_job_logic(context, force_one=True)
        await query.edit_message_text("تم النشر الفوري بنجاح ✅", reply_markup=get_back_keyboard(role))

    if data == "broadcast_menu" and role in ["dev", "admin"]:
        context.user_data['action'] = 'waiting_broadcast'
        await query.edit_message_text("✏️ أرسل الرسالة التي تريد إذاعتها للخاص والقنوات:", reply_markup=get_back_keyboard(role))

# --- تم تعديل message_handler هنا ---
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user: 
        return
    
    user_id = update.effective_user.id
    text = update.message.text
    document = update.message.document
    
    # إصلاح: استخدام getattr لتجنب الخطأ إذا لم تكن السمة موجودة
    forward_from_chat = getattr(update.message, 'forward_from_chat', None)
    
    role = "dev" if user_id == config.DEVELOPER_ID else ("admin" if db.is_admin(user_id) else "user")

    # ---------------------------------------------------------
    # 1. إضافة/حذف المشرفين
    # ---------------------------------------------------------
    if context.user_data.get('action') == 'add_admin':
        target = text.strip().replace("@", "")
        session = db.Session()
        try:
            user = session.query(db.User).filter((db.User.username == target) | (db.User.user_id == str(target))).first()
            if user:
                user.is_admin = True
                session.commit()
                msg = f"✅ تم رفع @{user.username} مشرفاً."
            else:
                msg = "❌ المستخدم غير موجود."
        except Exception:
            session.rollback()
            msg = "❌ حدث خطأ."
        finally:
            session.close()
        context.user_data['action'] = None
        await update.message.reply_text(msg, parse_mode='HTML', reply_markup=get_back_keyboard(role))
        return

    if context.user_data.get('action') == 'del_admin':
        target = text.strip().replace("@", "")
        session = db.Session()
        try:
            user = session.query(db.User).filter((db.User.username == target) | (db.User.user_id == str(target))).first()
            if user and user.user_id != config.DEVELOPER_ID:
                user.is_admin = False
                session.commit()
                msg = "✅ تمت الإزالة."
            else:
                msg = "❌ خطأ أو تحاول حذف المطور."
        except Exception:
            session.rollback()
            msg = "❌ خطأ."
        finally:
            session.close()
        context.user_data['action'] = None
        await update.message.reply_text(msg, parse_mode='HTML', reply_markup=get_back_keyboard(role))
        return

    # ---------------------------------------------------------
    # 2. رفع الملفات
    # ---------------------------------------------------------
    if document and context.user_data.get('upload_category'):
        category = context.user_data['upload_category']
        if document.mime_type == "text/plain":
            try:
                file = await document.get_file()
                content_bytes = await file.download_as_bytearray()
                content_text = content_bytes.decode('utf-8').splitlines()
                content_list = [line for line in content_text if line.strip()]
                count = db.add_file_content(category, content_list)
                msg = f"✅ تمت إضافة <b>{count}</b> اقتباس."
                context.user_data['upload_category'] = None
            except Exception as e:
                msg = f"❌ خطأ في قراءة الملف: {e}"
        else:
            msg = "❌ ملف .txt فقط."
        await update.message.reply_text(msg, parse_mode='HTML', reply_markup=get_back_keyboard(role))
        return

    # ---------------------------------------------------------
    # 3. إضافة قناة
    # ---------------------------------------------------------
    if context.user_data.get('step') == 'waiting_channel':
        
        chat_id = None
        title = None
        error_message = None

        # الحالة أ: التوجية (Forward)
        if forward_from_chat:
            # نقبل القنوات والمجموعات الفائقة
            if forward_from_chat.type in ['channel', 'supergroup']:
                chat_id = forward_from_chat.id
                title = forward_from_chat.title
            else:
                error_message = "❌ يرجى توجيه رسالة من قناة أو مجموعة، وليس من مستخدم خاص."
        
        # الحالة ب: النص (رابط أو معرف)
        elif text:
            txt = text.strip()
            
            # دالة مساعدة لمحاولة جلب المحادثة
            async def try_resolve_chat(identifier):
                try:
                    return await context.bot.get_chat(identifier)
                except Exception:
                    return None

            resolved_chat = None

            # 1. المعرف الصريح (@Channel)
            if txt.startswith("@"):
                resolved_chat = await try_resolve_chat(txt)
            
            # 2. المعرف الرقمي (-100...)
            elif txt.startswith("-100"):
                resolved_chat = await try_resolve_chat(txt)

            # 3. الرابط (t.me/...)
            elif "t.me/" in txt.lower() or "https://" in txt.lower():
                try:
                    parts = txt.lower().split("t.me/")
                    identifier_part = parts[-1].split('/')[0].split('?')[0].strip()
                    
                    if identifier_part:
                        if not identifier_part.startswith("+"): # تجاهل روابط الانضمام المشفرة
                            if not identifier_part.startswith("@"):
                                identifier_part = f"@{identifier_part}"
                            resolved_chat = await try_resolve_chat(identifier_part)
                except Exception as e:
                    logger.warning(f"Failed to parse link: {e}")

            # 4. مجرد نص (قد يكون اسم مستخدم بدون @)
            elif not " " in txt: 
                resolved_chat = await try_resolve_chat(txt)

            # التحقق من النتيجة
            if resolved_chat:
                if resolved_chat.type in ['channel', 'supergroup']:
                    chat_id = resolved_chat.id
                    title = resolved_chat.title
                else:
                    error_message = "❌ هذا المعرف لمستخدم عادي، وليس لقناة."
            else:
                error_message = "❌ لم أستطع العثور على القناة.\nتأكد أن البوت مشرف وأن الرابط عام."

        # -----------------------------------------------------
        # التحقق النهائي والحفظ
        # -----------------------------------------------------
        if chat_id and title:
            # التحقق من أن البوت مشرف
            if await is_bot_admin_in_channel(context.bot, chat_id):
                context.user_data['pending_channel'] = {'id': chat_id, 'title': title}
                context.user_data['step'] = None
                await update.message.reply_text(f"✅ تم التحقق من القناة: <b>{title}</b>\n\nاختر نوع الاقتباسات:", parse_mode='HTML', reply_markup=get_categories_keyboard())
                return
            else:
                await update.message.reply_text(f"⛔️ <b>البوت ليس مشرفاً!</b>\n\nأنا وجدت القناة <b>{title}</b> ولكن ليس لدي صلاحيات النشر.\nيرجى ترقيتي إلى مشرف أولاً.", parse_mode='HTML')
                context.user_data['step'] = None
                return
        
        # في حالة وجود خطأ
        if error_message:
            await update.message.reply_text(error_message, reply_markup=get_back_keyboard(role))
            context.user_data['step'] = None
            return

    # ---------------------------------------------------------
    # 4. تعديل الوقت
    # ---------------------------------------------------------
    if context.user_data.get('action') == 'set_fixed_time':
        time_input = text.strip()
        pending = context.user_data.get('pending_channel')
        if pending:
            context.user_data['time_settings'] = {'type': 'fixed', 'value': time_input}
            await finalize_channel_addition_logic(update, role, context)
        else:
            ch_id = context.user_data.get('editing_channel_id')
            session = db.Session()
            try:
                ch = session.query(db.Channel).filter_by(id=ch_id).first()
                if ch:
                    ch.time_value = time_input
                    session.commit()
                    await update.message.reply_text(f"✅ تم التحديث.", reply_markup=get_back_keyboard(role))
            finally:
                session.close()
        context.user_data['action'] = None
        return

    if context.user_data.get('action') == 'set_interval':
        try:
            val = int(text.strip())
        except:
            await update.message.reply_text("❌ رقم غير صحيح.", reply_markup=get_back_keyboard(role))
            return
        pending = context.user_data.get('pending_channel')
        if pending:
            context.user_data['time_settings'] = {'type': 'interval', 'value': str(val)}
            await finalize_channel_addition_logic(update, role, context)
        else:
            ch_id = context.user_data.get('editing_channel_id')
            session = db.Session()
            try:
                ch = session.query(db.Channel).filter_by(id=ch_id).first()
                if ch:
                    ch.time_value = str(val)
                    session.commit()
                    await update.message.reply_text(f"✅ تم التحديث.", reply_markup=get_back_keyboard(role))
            finally:
                session.close()
        context.user_data['action'] = None
        return

    # ---------------------------------------------------------
    # 5. الإذاعة
    # ---------------------------------------------------------
    if context.user_data.get('action') == 'waiting_broadcast':
        msg_to_send = text or update.message.caption
        if not msg_to_send: return
        await update.message.reply_text("⏳ جاري الإذاعة...")
        asyncio.create_task(broadcast_task_logic(context.bot, msg_to_send))
        context.user_data['action'] = None
        return

    # ---------------------------------------------------------
    # 6. تفعيل في المجموعة
    # ---------------------------------------------------------
    if text == "تفعيل":
        if update.effective_chat.type in ['group', 'supergroup']:
            if not await is_bot_admin_in_channel(context.bot, update.effective_chat.id):
                await update.message.reply_text("يجب أن أكون مشرفاً.")
                return
            db.add_channel(update.effective_chat.id, update.effective_chat.title, user_id, "اقتباسات عامة", "normal", "default", None)
            await update.message.reply_text("✅ تم التفعيل في المجموعة!")

async def finalize_channel_addition_logic(message_obj, role, context):
    pending = context.user_data.get('pending_channel')
    if not pending: return
    
    cat = context.user_data.get('selected_category')
    fmt = context.user_data.get('selected_format', 'normal')
    time_conf = context.user_data.get('time_settings', {'type': 'default', 'value': None})
    
    # استخراج user_id بشكل صحيح
    user_id = None
    if isinstance(message_obj, Update):
        user_id = message_obj.effective_user.id
    elif hasattr(message_obj, 'from_user'): # CallbackQuery
        user_id = message_obj.from_user.id
    
    if not user_id:
        logger.error("Could not determine user ID in finalize_channel_addition_logic")
        return

    db.add_channel(pending['id'], pending['title'], user_id, cat, fmt, time_conf['type'], time_conf['value'])
    
    context.user_data['pending_channel'] = None
    context.user_data['selected_category'] = None
    context.user_data['time_settings'] = None
    
    time_text = "🚀 فوري/عشوائي"
    if time_conf['type'] == 'fixed': time_text = f"⏰ الساعات: {time_conf['value']}"
    elif time_conf['type'] == 'interval': time_text = f"⏳ كل: {time_conf['value']} دقيقة"
    
    msg = f"✅ تمت إضافة القناة بنجاح!\n📂 القسم: <b>{cat}</b>\n📝 الشكل: {fmt}\n⏱️ الوقت: {time_text}"
    
    if isinstance(message_obj, Update):
        await message_obj.message.reply_text(msg, parse_mode='HTML', reply_markup=get_back_keyboard(role))
    else:
        await message_obj.edit_message_text(msg, parse_mode='HTML', reply_markup=get_back_keyboard(role))

async def broadcast_task_logic(bot, text):
    """دالة الإذاعة تعمل في الخلفية"""
    session = db.Session()
    try:
        users = session.query(db.User).all()
        channels = session.query(db.Channel).all()
    finally:
        session.close()

    success_count = 0
    for u in users:
        try:
            await bot.send_message(chat_id=u.user_id, text=text)
            success_count +=1
            await asyncio.sleep(0.05)
        except: pass
            
    for c in channels:
        try:
            await bot.send_message(chat_id=c.channel_id, text=text)
            success_count += 1
        except: pass
    logger.info(f"Broadcast finished. Sent to {success_count} chats.")

async def post_job_logic(context: ContextTypes.DEFAULT_TYPE, force_one=False):
    """منطق النشر الرئيسي (يعمل كل دقيقة)"""
    session = db.Session()
    try:
        setting = session.query(db.BotSettings).filter_by(key='posting_status').first()
        status_val = setting.value if setting else 'off'
        
        if not force_one and status_val == 'off':
            return

        channels = session.query(db.Channel).filter_by(is_active=True).all()
    except Exception as e:
        logger.error(f"Error fetching settings/channels: {e}")
        session.close()
        return
    
    if not channels:
        session.close()
        return

    now = datetime.now()
    
    try:
        for channel in channels:
            try:
                should_post = False
                
                if force_one:
                    should_post = True
                elif channel.time_type == 'default':
                    if random.random() < 0.05: should_post = True
                elif channel.time_type == 'fixed':
                    if channel.time_value:
                        try:
                            allowed_hours = [int(h.strip()) for h in channel.time_value.split(',')]
                            if now.hour in allowed_hours:
                                if not channel.last_post_at or channel.last_post_at.hour != now.hour:
                                    should_post = True
                        except ValueError:
                            pass # تجاهل الأخطاء في تفسير الوقت
                elif channel.time_type == 'interval':
                    if channel.time_value and channel.last_post_at:
                        if (now - channel.last_post_at).total_seconds() >= (int(channel.time_value) * 60):
                            should_post = True
                    elif not channel.last_post_at:
                        should_post = True
                
                if should_post:
                    text_content = db.get_next_content(channel.category)
                    if not text_content: continue
                    
                    final_text = text_content
                    parse_mode = None
                    if channel.msg_format == 'blockquote':
                        final_text = f"<blockquote>{text_content}</blockquote>"
                        parse_mode = 'HTML'
                    
                    await context.bot.send_message(chat_id=channel.channel_id, text=final_text, parse_mode=parse_mode)
                    
                    # استخدام نفس الـ session للتحديث
                    channel.last_post_at = now
                    session.commit()
                    
                    if force_one: return
                    await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Error posting to {channel.title}: {e}")
    finally:
        session.close()

async def chat_member_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.chat_member
    if result.old_chat_member.status in ['administrator', 'member'] and \
       result.new_chat_member.status in ['left', 'kicked']:
        chat_id = update.effective_chat.id
        chat_title = update.effective_chat.title
        asyncio.create_task(send_notification_to_admins(context.bot, f"⚠️ تم حذف البوت من <b>{chat_title}</b>"))
        db.remove_channel_db(chat_id)

# =========================================
# إعداد التطبيق
# =========================================

# تم إضافة drop_pending_updates=True لإنهاء أي صراع (Conflict) قديم وتنظيف السجلات
application = Application.builder().token(config.TOKEN_1).build()
application.updater.drop_pending_updates = True

def get_application():
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & (filters.TEXT | filters.FORWARDED), message_handler))
    application.add_handler(MessageHandler(filters.Document.MimeType("text/plain") & filters.ChatType.PRIVATE, message_handler))
    application.add_handler(MessageHandler(filters.Regex("^تفعيل$") & filters.ChatType.GROUPS, message_handler))
    application.add_handler(ChatMemberHandler(chat_member_handler, ChatMemberHandler.CHAT_MEMBER))
    
    if application.job_queue:
        application.job_queue.run_repeating(post_job_logic, interval=60, first=10)
        
    return application

async def run_bot1():
    app = get_application()
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    
    print("✅ البوت يعمل الآن! اضغط Ctrl+C للإيقاف.")
    
    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        print("Bot 1 is stopping...")
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

if __name__ == '__main__':
    try:
        asyncio.run(run_bot1())
    except KeyboardInterrupt:
        print("تم إيقاف البوت.")
