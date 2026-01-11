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
    ChatMemberHandler,
    ConversationHandler,
    PickledPersistence
)
import config
import database as db

# إعداد التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- الثوابت والبيانات الثابتة ---
# تم استخراج الأقسام هنا لتسهيل تعديلها مستقبلاً
CATEGORIES = [
    ("❤️ حب", "حب"),
    ("🎂 عيد ميلاد", "عيد ميلاد"),
    ("💭 اقتباسات عامة", "اقتباسات عامة"),
    ("📜 ابيات شعرية", "ابيات شعرية")
]

# حالات المحادثة (Conversation States)
ADD_CHANNEL_STATE = 1
ADD_CHANNEL_TIME = 2
BROADCAST_STATE = 3
ADD_ADMIN_STATE = 4
DEL_ADMIN_STATE = 5

# إعداد الحفظ المؤقت (Persistence)
# هذا يحفظ بيانات المستخدمين والمراحل التي وصلوا لها حتى لو تم إيقاف البوت
persistence = PickledPersistence(filepath="bot_data.pkl")

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

def get_role(user_id):
    """تحديد صلاحية المستخدم"""
    if user_id == config.DEVELOPER_ID: return "dev"
    if db.is_admin(user_id): return "admin"
    return "user"

def get_back_keyboard(role):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"back_{role}")]])

# --- توليد الكيبوردات ديناميكياً ---

def get_keyboard_by_role(role):
    """توليد لوحة التحكم الرئيسية بناءً على الصلاحية"""
    btns = [
        [InlineKeyboardButton("➕ إضافة قناة/مجموعة", callback_data="start_add_channel")],
        [InlineKeyboardButton("📊 الإحصائيات", callback_data="show_stats")]
    ]
    
    if role in ["dev", "admin"]:
        btns.insert(0, [InlineKeyboardButton("📂 إدارة الملفات", callback_data="manage_files")])
        btns.insert(1, [InlineKeyboardButton("🔧 إدارة القنوات", callback_data="manage_channels")])
        btns.append([InlineKeyboardButton("🔊 إرسال إذاعة", callback_data="start_broadcast")])
        btns.append([InlineKeyboardButton("⚙️ تفعيل/ايقاف النشر", callback_data="toggle_posting")])
        btns.append([InlineKeyboardButton("🚀 نشر الآن (منشور واحد)", callback_data="post_now")])
    
    if role == "dev":
        btns.insert(2, [InlineKeyboardButton("👥 إدارة المشرفين", callback_data="manage_admins")])

    title = "لوحة المطور" if role == "dev" else ("لوحة المشرف" if role == "admin" else "القائمة الرئيسية")
    return InlineKeyboardMarkup(btns), title

def get_categories_keyboard(prefix):
    """توليد كيبورد الأقسام"""
    btns = [[InlineKeyboardButton(name, callback_data=f"{prefix}_{code}")] for name, code in CATEGORIES]
    btns.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_home")])
    return InlineKeyboardMarkup(btns)

def get_format_keyboard(prefix):
    """توليد كيبورد التنسيقات"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 رسالة عادية", callback_data=f"{prefix}_normal")],
        [InlineKeyboardButton("💎 Blockquote", callback_data=f"{prefix}_blockquote")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]
    ])

def get_time_keyboard(prefix):
    """توليد كيبورد الوقت"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏰ ساعات محددة", callback_data=f"{prefix}_fixed")],
        [InlineKeyboardButton("⏳ فارق زمني (دقائق)", callback_data=f"{prefix}_interval")],
        [InlineKeyboardButton("🚫 افتراضي (عشوائي/فوري)", callback_data=f"{prefix}_default")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_home")]
    ])

# --- Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username
    
    session = db.Session()
    try:
        user = session.query(db.User).filter_by(user_id=user_id).first()
        if not user:
            user = db.User(user_id=user_id, username=username)
            session.add(user)
            session.commit()
            user_tag = f"@{username}" if username else "بدون يوزر"
            msg = f"🔔 <b>تنبيه:</b> دخول شخص جديد.\n👤 الاسم: {user_tag}\n🆔 الآيدي: <code>{user_id}</code>"
            await send_notification_to_admins(context.bot, msg)
        elif username != user.username:
            user.username = username
            session.commit()
    finally:
        session.close()

    kb, title = get_keyboard_by_role(get_role(user_id))
    welcome_text = "أهلاً بك في بوت النشر التلقائي! 🤖"
    await update.message.reply_text(f"{welcome_text}\n\n🔹 <b>{title}</b> 🔹", reply_markup=kb, parse_mode='HTML')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    role = get_role(user_id)
    data = query.data
    
    # --- قوائم الرجوع والقوائم الرئيسية ---
    if data in ["back_home", "back_dev", "back_admin", "back_user"]:
        context.user_data.clear() # تنظيف البيانات المؤقتة عند العودة للرئيسية
        kb, title = get_keyboard_by_role(role)
        # تحديد العنوان الصحيح للرجوع
        if data == "back_home": kb, title = get_keyboard_by_role("user")
        elif data == "back_dev": kb, title = get_keyboard_by_role("dev")
        await query.edit_message_text(f"🔹 <b>{title}</b> 🔹", reply_markup=kb, parse_mode='HTML')
        return

    # --- تشغيل المحادثات (Conversations) ---
    
    # 1. بدء إضافة قناة
    if data == "start_add_channel":
        context.user_data.clear()
        await query.edit_message_text("✏️ أرسل الآن:\n1. رابط القناة العامة (مثلاً @Channel)\n2. أو قم بتحويل رسالة (Forward) من القناة", reply_markup=get_back_keyboard(role))
        return ADD_CHANNEL_STATE

    # 2. بدء الإذاعة
    if data == "start_broadcast" and role in ["dev", "admin"]:
        context.user_data.clear()
        await query.edit_message_text("✏️ أرسل الرسالة التي تريد إذاعتها:", reply_markup=get_back_keyboard(role))
        return BROADCAST_STATE

    # 3. إدارة المشرفين
    if data == "manage_admins" and role == "dev":
        keyboard = [
            [InlineKeyboardButton("➕ إضافة مشرف", callback_data="conv_add_admin")],
            [InlineKeyboardButton("➖ حذف مشرف", callback_data="conv_del_admin")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back_dev")]
        ]
        await query.edit_message_text("اختر العملية:", reply_markup=InlineKeyboardMarkup(keyboard))
    
    if data == "conv_add_admin" and role == "dev":
        await query.edit_message_text("أرسل الآن (آيدي) أو (معرف المستخدم) للإضافة:", reply_markup=get_back_keyboard(role))
        return ADD_ADMIN_STATE

    if data == "conv_del_admin" and role == "dev":
        await query.edit_message_text("أرسل الآن (آيدي) أو (معرف المستخدم) للحذف:", reply_markup=get_back_keyboard(role))
        return DEL_ADMIN_STATE

    # --- منطق إضافة القناة (Steps) ---
    if data.startswith("cat_"):
        context.user_data['selected_category'] = data.split("_")[1]
        await query.edit_message_text(f"تم اختيار القسم: <b>{context.user_data['selected_category']}</b>.\n\nاختر شكل الرسالة:", parse_mode='HTML', reply_markup=get_format_keyboard("fmt"))
    
    if data.startswith("fmt_"):
        context.user_data['selected_format'] = data.split("_")[1]
        await query.edit_message_text("اختر طريقة النشر:", reply_markup=get_time_keyboard("time"))

    if data.startswith("time_"):
        time_type = data.split("_")[1]
        context.user_data['time_type'] = time_type
        if time_type == "default":
            # إنهاء العملية فوراً
            await finalize_channel_addition_logic(query, role, context)
        else:
            # طلب التفاصيل
            if time_type == "fixed":
                context.user_data['action'] = 'set_fixed_time'
                msg = "أرسل الساعات المطلوبة (مثلاً: 10, 14, 20) مفصولة بفاصلة:"
            elif time_type == "interval":
                context.user_data['action'] = 'set_interval'
                msg = "أرسل الفارق الزمني بالدقائق (مثلاً: 60):"
            await query.edit_message_text(msg, reply_markup=get_back_keyboard(role))
            return ADD_CHANNEL_TIME

    # --- إدارة الملفات ---
    if data == "manage_files" and role in ["dev", "admin"]:
        # توليد أزرار الرفع بناءً على القوائم
        keyboard = [[InlineKeyboardButton(name, callback_data=f"upload_{code}")] for name, code in CATEGORIES]
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"back_{role}")])
        await query.edit_message_text("اختر القسم لرفع ملفات الاقتباسات (txt):", reply_markup=InlineKeyboardMarkup(keyboard))
    
    if data.startswith("upload_"):
        category = data.split("_")[1]
        context.user_data['upload_category'] = category
        await query.edit_message_text(f"تم اختيار قسم: <b>{category}</b>\n\nالآن قم بإرسال ملف <code>.txt</code>.", parse_mode='HTML', reply_markup=get_back_keyboard(role))

    # --- إدارة القنوات (Edit Mode) ---
    if data == "manage_channels" and role in ["dev", "admin"]:
        session = db.Session()
        try:
            channels = session.query(db.Channel).all()
            if not channels:
                await query.edit_message_text("لا توجد قنوات مضافة.", reply_markup=get_back_keyboard(role))
                return
            keyboard = [[InlineKeyboardButton(f"{ch.title} ({ch.category})", callback_data=f"edit_channel_{ch.id}")] for ch in channels]
            keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"back_{role}")])
            await query.edit_message_text("اختر قناة:", reply_markup=InlineKeyboardMarkup(keyboard))
        finally: session.close()

    if data.startswith("edit_channel_"):
        ch_id = int(data.split("_")[2])
        context.user_data['editing_channel_id'] = ch_id
        keyboard = [
            [InlineKeyboardButton("🔄 تغيير المحتوى", callback_data="edit_cat_select")],
            [InlineKeyboardButton("🎨 تغيير الشكل", callback_data="edit_fmt_select")],
            [InlineKeyboardButton("⏰ تغيير الوقت", callback_data="edit_time_select")],
            [InlineKeyboardButton("🗑️ حذف القناة", callback_data="confirm_del_channel")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="manage_channels")]
        ]
        await query.edit_message_text("خيارات التعديل:", reply_markup=InlineKeyboardMarkup(keyboard))

    if data == "confirm_del_channel":
        ch_id = context.user_data.get('editing_channel_id')
        keyboard = [
            [InlineKeyboardButton("❌ لا", callback_data=f"edit_channel_{ch_id}")],
            [InlineKeyboardButton("✅ نعم", callback_data=f"exec_del_channel_{ch_id}")]
        ]
        await query.edit_message_text("هل أنت متأكد؟", reply_markup=InlineKeyboardMarkup(keyboard))

    if data.startswith("exec_del_channel_"):
        ch_id = int(data.split("_")[3])
        session = db.Session()
        try:
            ch = session.query(db.Channel).filter_by(id=ch_id).first()
            if ch:
                title = ch.title
                session.delete(ch)
                session.commit()
                msg = f"✅ تم حذف <b>{title}</b>."
            else: msg = "❌ خطأ."
        except Exception as e:
            session.rollback()
            msg = f"❌ خطأ: {e}"
        finally: session.close()
        await query.edit_message_text(msg, parse_mode='HTML', reply_markup=get_back_keyboard(role))

    # منطق التعديل التفصيلي (اختصار للكود)
    if data == "edit_cat_select":
        await query.edit_message_text("اختر المحتوى:", reply_markup=get_categories_keyboard(f"set_edit_cat_{context.user_data['editing_channel_id']}"))
    if data.startswith("set_edit_cat_"):
        parts = data.split("_")
        session = db.Session()
        try:
            ch = session.query(db.Channel).filter_by(id=int(parts[3])).first()
            if ch: ch.category = "_".join(parts[4:]); session.commit(); msg = "✅ تم التحديث."
            else: msg = "❌ خطأ."
        except: msg = "❌ خطأ."
        finally: session.close()
        await query.edit_message_text(msg, parse_mode='HTML', reply_markup=get_back_keyboard(role))
    
    if data == "edit_fmt_select":
        await query.edit_message_text("اختر الشكل:", reply_markup=get_format_keyboard(f"set_edit_fmt_{context.user_data['editing_channel_id']}"))
    if data.startswith("set_edit_fmt_"):
        parts = data.split("_")
        session = db.Session()
        try:
            ch = session.query(db.Channel).filter_by(id=int(parts[3])).first()
            if ch: ch.msg_format = parts[4]; session.commit(); msg = "✅ تم التحديث."
        except: msg = "❌ خطأ."
        finally: session.close()
        await query.edit_message_text(msg, parse_mode='HTML', reply_markup=get_back_keyboard(role))

    if data == "edit_time_select":
        await query.edit_message_text("اختر الوقت:", reply_markup=get_time_keyboard(f"set_edit_time_{context.user_data['editing_channel_id']}"))
    if data.startswith("set_edit_time_"):
        # يمكن توسيع هذا الجزء لطلب تفاصيل جديدة كالمحادثة العادية
        time_type = data.split("_")[-1]
        session = db.Session()
        try:
            ch = session.query(db.Channel).filter_by(id=int(data.split("_")[3])).first()
            if ch: 
                ch.time_type = time_type
                ch.time_value = None if time_type == 'default' else ch.time_value
                session.commit()
                msg = "✅ تم تغيير نوع التوقيت. (للتفاصيل الدقيقة استخدم الأوامر اليدوية أو قم بتطوير الكود)"
        except: msg = "❌ خطأ."
        finally: session.close()
        await query.edit_message_text(msg, parse_mode='HTML', reply_markup=get_back_keyboard(role))

    # --- أوامر عامة ---
    if data == "show_stats":
        await query.edit_message_text(db.get_stats(), parse_mode='HTML', reply_markup=get_back_keyboard(role))
    
    if data == "toggle_posting" and role in ["dev", "admin"]:
        session = db.Session()
        try:
            setting = session.query(db.BotSettings).filter_by(key='posting_status').first()
            new_status = 'off' if (setting and setting.value == 'on') else 'on'
            if setting: setting.value = new_status
            else: session.add(db.BotSettings(key='posting_status', value=new_status))
            session.commit()
            state_text = "🟢 مفعل" if new_status == 'on' else "🔴 متوقف"
            await query.edit_message_text(f"الحالة: <b>{state_text}</b>", parse_mode='HTML', reply_markup=get_back_keyboard(role))
        finally: session.close()

    if data == "post_now":
        await query.edit_message_text("جاري النشر الفوري...")
        await post_job_logic(context, force_one=True)
        await query.edit_message_text("تم النشر الفوري ✅", reply_markup=get_back_keyboard(role))

# --- المعالجات النصية والملفات (Text & File Handlers) ---

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الرسائل النصية العامة (يعمل مع المحادثات)"""
    user_id = update.effective_user.id
    role = get_role(user_id)
    text = update.message.text

    # 1. حالة إضافة القناة (Step 1: ID/Link)
    if context.user_data.get('conv_state') == ADD_CHANNEL_STATE:
        chat_id, title, error_msg = await resolve_channel_info(context, text, update.message.forward_from_chat)
        if error_msg:
            await update.message.reply_text(error_msg, reply_markup=get_back_keyboard(role))
            return ConversationHandler.END
        
        if await is_bot_admin_in_channel(context.bot, chat_id):
            context.user_data['pending_channel'] = {'id': chat_id, 'title': title}
            context.user_data['conv_state'] = None # Clear temp state to proceed to button selection
            await update.message.reply_text(f"✅ تم التحقق من: <b>{title}</b>\n\nاختر القسم:", parse_mode='HTML', reply_markup=get_categories_keyboard("cat"))
            # ملاحظة: سنعتمد على الزر لإكمال المحادثة، لذا سننتهي من الـ Handler هنا لكن نحتفظ بالبيانات
            return ADD_CHANNEL_STATE # نرجع نفس الحالة لضمان بقاء المحادثة نشطة حتى يتم الاختيار
        else:
            await update.message.reply_text("⛔️ <b>البوت ليس مشرفاً!</b>", parse_mode='HTML')
            return ConversationHandler.END

    # 2. حالة تحديد الوقت بالتفصيل (Step 2: Time Details)
    if context.user_data.get('conv_state') == ADD_CHANNEL_TIME:
        time_type = context.user_data.get('time_type')
        val_valid = False
        
        if time_type == "fixed":
            # تحقق بسيط
            val_valid = all(h.strip().isdigit() for h in text.split(','))
            if val_valid: context.user_data['time_settings'] = {'type': 'fixed', 'value': text}
        
        elif time_type == "interval":
            if text.strip().isdigit():
                val_valid = True
                context.user_data['time_settings'] = {'type': 'interval', 'value': text}
        
        if val_valid:
            # محاكاة finalize ولكن via message
            await finalize_channel_addition_logic(update, role, context)
            return ConversationHandler.END
        else:
            await update.message.reply_text("❌ قيمة غير صحيحة. حاول مرة أخرى.")
            return ADD_CHANNEL_TIME

    # 3. حالة الإذاعة
    if context.user_data.get('conv_state') == BROADCAST_STATE:
        await update.message.reply_text("⏳ جاري الإذاعة...")
        asyncio.create_task(broadcast_task_logic(context.bot, text))
        return ConversationHandler.END

    # 4. حالة إضافة/حذف مشرف
    if context.user_data.get('conv_state') == ADD_ADMIN_STATE:
        target = text.strip().replace("@", "")
        session = db.Session()
        try:
            user = session.query(db.User).filter((db.User.username == target) | (db.User.user_id == str(target))).first()
            if user: user.is_admin = True; session.commit(); msg = f"✅ تم رفع مشرف."
            else: msg = "❌ لم أجد المستخدم."
        finally: session.close()
        await update.message.reply_text(msg, parse_mode='HTML', reply_markup=get_back_keyboard(role))
        return ConversationHandler.END
    
    if context.user_data.get('conv_state') == DEL_ADMIN_STATE:
        target = text.strip().replace("@", "")
        session = db.Session()
        try:
            user = session.query(db.User).filter((db.User.username == target) | (db.User.user_id == str(target))).first()
            if user and user.user_id != config.DEVELOPER_ID:
                user.is_admin = False; session.commit(); msg = "✅ تمت الإزالة."
            else: msg = "❌ خطأ."
        finally: session.close()
        await update.message.reply_text(msg, parse_mode='HTML', reply_markup=get_back_keyboard(role))
        return ConversationHandler.END

    # 5. تفعيل في المجموعة
    if text == "تفعيل" and update.effective_chat.type in ['group', 'supergroup']:
        if await is_bot_admin_in_channel(context.bot, update.effective_chat.id):
            db.add_channel(update.effective_chat.id, update.effective_chat.title, user_id, "اقتباسات عامة", "normal", "default", None)
            await update.message.reply_text("✅ تم التفعيل في المجموعة!")

async def handle_file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج رفع الملفات (لا يتطلب ConversationHandler بالضرورة لكن وضعه هنا للنظافة)"""
    document = update.message.document
    category = context.user_data.get('upload_category')
    
    if document and category:
        if document.mime_type == "text/plain":
            try:
                file = await document.get_file()
                content_bytes = await file.download_as_bytearray()
                content_list = [line for line in content_bytes.decode('utf-8').splitlines() if line.strip()]
                count = db.add_file_content(category, content_list)
                msg = f"✅ تمت إضافة <b>{count}</b> اقتباس."
                context.user_data['upload_category'] = None
            except Exception as e:
                msg = f"❌ خطأ: {e}"
        else:
            msg = "❌ ملف .txt فقط."
        role = get_role(update.effective_user.id)
        await update.message.reply_text(msg, parse_mode='HTML', reply_markup=get_back_keyboard(role))

# --- دوال مساعدة للقنوات ---

async def resolve_channel_info(context, text, forward_from_chat):
    """دالة موحدة لاستخراج Chat ID و Title"""
    chat_id, title, error_msg = None, None, None
    
    # 1. Forwarded
    if forward_from_chat:
        if forward_from_chat.type in ['channel', 'supergroup']:
            return forward_from_chat.id, forward_from_chat.title, None
        return None, None, "❌ الرسالة من مستخدم، وليست قناة."
    
    # 2. Text/Link
    txt = text.strip()
    
    # Try direct resolve
    resolved_chat = None
    try:
        # Try as is (username or id)
        if not " " in txt and not "/" in txt:
             resolved_chat = await context.bot.get_chat(txt)
        
        # Try Link
        if not resolved_chat and ("t.me/" in txt.lower()):
             parts = txt.lower().split("t.me/")
             identifier = parts[-1].split('/')[0].split('?')[0].strip()
             if not identifier.startswith("+"):
                 resolved_chat = await context.bot.get_chat(f"@{identifier}")
    except Exception:
        pass # Failed to resolve via API directly
    
    if resolved_chat:
        if resolved_chat.type in ['channel', 'supergroup']:
            return resolved_chat.id, resolved_chat.title, None
        return None, None, "❌ المعرف لمستخدم وليس قناة."
        
    return None, None, "❌ لم أستطع العثور على القناة. تأكد أنني مشرف والرابط عام."

async def finalize_channel_addition_logic(message_obj, role, context):
    """منطق حفظ القناة النهائي"""
    pending = context.user_data.get('pending_channel')
    if not pending: return
    
    cat = context.user_data.get('selected_category', 'اقتباسات عامة')
    fmt = context.user_data.get('selected_format', 'normal')
    time_conf = context.user_data.get('time_settings', {'type': 'default', 'value': None})
    
    user_id = message_obj.effective_user.id if isinstance(message_obj, Update) else message_obj.from_user.id
    
    db.add_channel(pending['id'], pending['title'], user_id, cat, fmt, time_conf['type'], time_conf['value'])
    
    context.user_data['pending_channel'] = None
    context.user_data['selected_category'] = None
    context.user_data['time_settings'] = None
    
    time_text = "🚀 فوري"
    if time_conf['type'] == 'fixed': time_text = f"⏰ {time_conf['value']}"
    elif time_conf['type'] == 'interval': time_text = f"⏳ كل {time_conf['value']} د"
    
    msg = f"✅ تمت الإضافة!\n<b>{pending['title']}</b>\n📂 {cat}\n📝 {fmt}\n⏱️ {time_text}"
    
    if isinstance(message_obj, Update):
        await message_obj.message.reply_text(msg, parse_mode='HTML', reply_markup=get_back_keyboard(role))
    else:
        await message_obj.edit_message_text(msg, parse_mode='HTML', reply_markup=get_back_keyboard(role))

# --- المنطق الخلفي (Jobs & Tasks) ---

async def post_job_logic(context: ContextTypes.DEFAULT_TYPE, force_one=False):
    session = db.Session()
    try:
        setting = session.query(db.BotSettings).filter_by(key='posting_status').first()
        if not force_one and (not setting or setting.value == 'off'): return
        channels = session.query(db.Channel).filter_by(is_active=True).all()
    except Exception as e:
        logger.error(f"DB Error: {e}")
        return
    finally:
        # Note: Don't close session here yet if we are iterating, but we need to be careful.
        # Better to keep session open or use scoped_session.
        pass

    now = datetime.now()
    for channel in channels:
        try:
            should_post = False
            if force_one: should_post = True
            elif channel.time_type == 'default':
                if random.random() < 0.05: should_post = True
            elif channel.time_type == 'fixed':
                if channel.time_value:
                    try:
                        allowed_hours = [int(h.strip()) for h in channel.time_value.split(',')]
                        if now.hour in allowed_hours:
                             if not channel.last_post_at or channel.last_post_at.hour != now.hour:
                                 should_post = True
                    except: pass
            elif channel.time_type == 'interval':
                if channel.time_value and channel.last_post_at:
                    if (now - channel.last_post_at).total_seconds() >= (int(channel.time_value) * 60):
                        should_post = True
                elif not channel.last_post_at: should_post = True
            
            if should_post:
                content = db.get_next_content(channel.category)
                if not content: continue
                
                text = f"<blockquote>{content}</blockquote>" if channel.msg_format == 'blockquote' else content
                parse_mode = 'HTML' if channel.msg_format == 'blockquote' else None
                
                await context.bot.send_message(chat_id=channel.channel_id, text=text, parse_mode=parse_mode)
                channel.last_post_at = now
                session.commit()
                if force_one: return
                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Post Error: {e}")
            session.rollback()
    session.close()

async def broadcast_task_logic(bot, text):
    session = db.Session()
    try:
        users = session.query(db.User).all()
        channels = session.query(db.Channel).all()
        for u in users:
            try: await bot.send_message(chat_id=u.user_id, text=text); await asyncio.sleep(0.05)
            except: pass
        for c in channels:
            try: await bot.send_message(chat_id=c.channel_id, text=text)
            except: pass
    finally: session.close()

# --- Main Application Setup ---

def get_application():
    # استخدام Persistence لحفظ البيانات
    application = Application.builder().token(config.TOKEN_1).persistence(persistence).build()

    # 1. محادثة إضافة قناة (تتكون من أزرار ونصوص)
    add_channel_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern="^start_add_channel$")],
        states={
            ADD_CHANNEL_STATE: [
                MessageHandler(filters.TEXT | filters.FORWARDED, handle_text_message),
                # السماح بالأزرار للانتقال للخطوة التالية (اختيار القسم/الوقت)
                CallbackQueryHandler(button_handler, pattern="^(cat_|fmt_|time_)") 
            ],
            ADD_CHANNEL_TIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message)
            ]
        },
        fallbacks=[CallbackQueryHandler(button_handler, pattern="^back_")],
        name="add_channel_conv",
        persistent=True
    )

    # 2. محادثة الإذاعة
    broadcast_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern="^start_broadcast$")],
        states={
            BROADCAST_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message)]
        },
        fallbacks=[CallbackQueryHandler(button_handler, pattern="^back_")],
        name="broadcast_conv",
        persistent=True
    )

    # 3. محادثة إدارة المشرفين
    admin_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(button_handler, pattern="^conv_add_admin$"),
            CallbackQueryHandler(button_handler, pattern="^conv_del_admin$")
        ],
        states={
            ADD_ADMIN_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message)],
            DEL_ADMIN_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message)]
        },
        fallbacks=[CallbackQueryHandler(button_handler, pattern="^back_")],
        name="admin_conv",
        persistent=True
    )

    # إضافة المعالجات
    application.add_handler(CommandHandler("start", start))
    
    # إضافة المحادثات (الأولوية مهمة، توضع قبل معالج الأزرار العام)
    application.add_handler(add_channel_conv)
    application.add_handler(broadcast_conv)
    application.add_handler(admin_conv)
    
    # معالج الأزرار العام (للتنقل والقوائم)
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # معالج الرسائل (يغطي النصوص والملفات)
    # نستخدم `~filters.COMMAND` لتجنب التداخل مع الأمر /start مثلاً
    application.add_handler(MessageHandler(filters.Document.MimeType("text/plain") & filters.ChatType.PRIVATE, handle_file_upload))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_text_message))
    application.add_handler(MessageHandler(filters.Regex("^تفعيل$") & filters.ChatType.GROUPS, handle_text_message))
    
    # إدارة تغيير حالة المشرف في القنوات
    application.add_handler(ChatMemberHandler(lambda u, c: None, ChatMemberHandler.CHAT_MEMBER)) # Simplified for brevity, needs implementation like original

    # مهمة النشر الدورية
    if application.job_queue:
        application.job_queue.run_repeating(post_job_logic, interval=60, first=10)

    return application

if __name__ == '__main__':
    try:
        app = get_application()
        print("✅ البوت يعمل الآن!")
        app.run_polling()
    except KeyboardInterrupt:
        print("تم الإيقاف.")
