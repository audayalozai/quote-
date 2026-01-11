import logging
import asyncio
import random
import json
import io
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
    ConversationHandler
)

# استيراد الملفات المحلية (تأكد من وجودها في نفس المسار)
import config
import database as db

# --- التهيئة الأولية ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# تهيئة قاعدة البيانات مع معالجة الأخطاء للتوافق مع Railway
try:
    db.init_db()
    logger.info("✅ Database initialized successfully.")
except Exception as e:
    logger.error(f"❌ Database initialization failed: {e}")

# --- الثوابت والبيانات الثابتة ---
CATEGORIES = [
    ("❤️ حب", "حب"),
    ("🎂 عيد ميلاد", "عيد ميلاد"),
    ("💭 اقتباسات عامة", "اقتباسات عامة"),
    ("📜 ابيات شعرية", "ابيات شعرية")
]

# حالات المحادثة (States)
CHANNEL_INPUT = 1
CHANNEL_TIME_INPUT = 2
BROADCAST_INPUT = 3
ADD_ADMIN_INPUT = 4
DEL_ADMIN_INPUT = 5
RESTORE_CONFIRM = 6

# --- دوال مساعدة ---

async def is_bot_admin_in_channel(bot, channel_id):
    try:
        chat_member = await bot.get_chat_member(channel_id, bot.id)
        return chat_member.status in ['administrator', 'creator']
    except Exception as e:
        logger.error(f"Error checking admin status: {e}")
        return False

async def send_notification_to_admins(bot, message: str):
    session = db.Session()
    try:
        admins = session.query(db.User).filter_by(is_admin=True).all()
        for admin in admins:
            try:
                await bot.send_message(chat_id=admin.user_id, text=message, parse_mode='HTML')
            except Exception:
                continue
        try:
            await bot.send_message(chat_id=config.DEVELOPER_ID, text=message, parse_mode='HTML')
        except Exception:
            pass
    finally:
        session.close()

def get_role(user_id):
    if user_id == config.DEVELOPER_ID: return "dev"
    if db.is_admin(user_id): return "admin"
    return "user"

def get_back_keyboard(role):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"back_{role}")]])

# --- توليد الكيبوردات (تم تحديث الترتيب والمحتوى) ---

def get_keyboard_by_role(role):
    btns = []
    
    if role == "dev":
        # لوحة المطور
        btns = [
            [InlineKeyboardButton("🔄 النسخ الاحتياطي", callback_data="backup_menu")],
            [InlineKeyboardButton("👥 إدارة المشرفين", callback_data="manage_admins")],
            [InlineKeyboardButton("👤 قائمة المستخدمين", callback_data="view_users")], # زر جديد
            [InlineKeyboardButton("📊 الإحصائيات", callback_data="show_stats")],
            [InlineKeyboardButton("📂 إدارة الملفات", callback_data="manage_files")],
            [InlineKeyboardButton("🔧 إدارة القنوات", callback_data="manage_channels")],
            [InlineKeyboardButton("🔊 إرسال إذاعة", callback_data="start_broadcast")],
            [InlineKeyboardButton("⚙️ تفعيل/ايقاف النشر", callback_data="toggle_posting")],
            [InlineKeyboardButton("🚀 نشر الآن", callback_data="post_now")]
        ]
        title = "لوحة المطور 🔧"
        
    elif role == "admin":
        # لوحة المشرف
        btns = [
            [InlineKeyboardButton("➕ إضافة قناة", callback_data="start_add_channel")],
            [InlineKeyboardButton("📊 الإحصائيات", callback_data="show_stats")],
            [InlineKeyboardButton("📂 إدارة الملفات", callback_data="manage_files")],
            [InlineKeyboardButton("🔧 إدارة القنوات", callback_data="manage_channels")],
            [InlineKeyboardButton("🔊 إرسال إذاعة", callback_data="start_broadcast")],
            [InlineKeyboardButton("⚙️ تفعيل/ايقاف النشر", callback_data="toggle_posting")],
            [InlineKeyboardButton("🚀 نشر الآن", callback_data="post_now")]
        ]
        title = "لوحة المشرف 👨‍💼"
        
    else:
        # --- القائمة الجديدة والمحسنة للمستخدم العادي ---
        btns = [
            [InlineKeyboardButton("💭 تصفح الأقسام", callback_data="user_browse_categories")],
            [InlineKeyboardButton("🔖 اقتباس عشوائي", callback_data="user_random_quote")],
            [InlineKeyboardButton("📢 القناة الرسمية", url="https://t.me/YourChannel")], # ضع رابط قناتك هنا
            [InlineKeyboardButton("❓ كيف يعمل البوت؟", callback_data="user_help")]
        ]
        title = "القائمة الرئيسية 🏠"

    return InlineKeyboardMarkup(btns), title

def get_categories_keyboard(prefix):
    btns = [[InlineKeyboardButton(name, callback_data=f"{prefix}_{code}")] for name, code in CATEGORIES]
    btns.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_dev")])
    return InlineKeyboardMarkup(btns)

def get_format_keyboard(prefix):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 رسالة عادية", callback_data=f"{prefix}_normal")],
        [InlineKeyboardButton("💎 Blockquote", callback_data=f"{prefix}_blockquote")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_dev")]
    ])

def get_time_keyboard(prefix):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏰ ساعات محددة", callback_data=f"{prefix}_fixed")],
        [InlineKeyboardButton("⏳ فارق زمني (دقائق)", callback_data=f"{prefix}_interval")],
        [InlineKeyboardButton("🚫 افتراضي (عشوائي)", callback_data=f"{prefix}_default")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_dev")]
    ])

# --- المعالجات الرئيسية (Handlers) ---

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
    except Exception as e:
        logger.error(f"Error in start: {e}")
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
    
    # --- الرجوع للخلف ---
    if data.startswith("back_"):
        target_role = data.split("_")[1]
        # التحقق من الصلاحيات
        if target_role == "dev" and role != "dev": target_role = role
        if target_role == "admin" and role not in ["dev", "admin"]: target_role = role
        
        kb, title = get_keyboard_by_role(target_role)
        await query.edit_message_text(f"🔹 <b>{title}</b> 🔹", reply_markup=kb, parse_mode='HTML')
        return

    # --- منطق أزرار المستخدم العادي (جديد ومحسّن) ---
    
    # زر "اقتباس عشوائي" مباشرة
    if data == "user_random_quote":
        random_cat = random.choice([c[1] for c in CATEGORIES])
        content = db.get_next_content(random_cat)
        
        if content:
            text = f"✨ <b>اقتباس عشوائي:</b>\n\n{content}"
        else:
            text = "❌ لا توجد اقتباسات حالياً."
        
        keyboard = [[InlineKeyboardButton("🔄 اقتباس آخر", callback_data="user_random_quote")], [InlineKeyboardButton("🔙 رجوع", callback_data="back_user")]]
        await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # زر "تصفح الأقسام" (عرض القائمة)
    if data == "user_browse_categories":
        keyboard = [[InlineKeyboardButton(name, callback_data=f"user_cat_{code}")] for name, code in CATEGORIES]
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_user")])
        await query.edit_message_text("اختر القسم الذي تريد تصفحه:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # عند اختيار قسم معين
    if data.startswith("user_cat_"):
        category = data.split("_")[-1]
        content = db.get_next_content(category)
        
        if content:
            text = f"📂 <b>قسم: {category}</b>\n\n{content}"
        else:
            text = "📭 هذا القسم فارغ حالياً."
            
        keyboard = [
            [InlineKeyboardButton("🔄 اقتباس آخر", callback_data=f"user_cat_{category}")],
            [InlineKeyboardButton("🔙 رجوع للأقسام", callback_data="user_browse_categories")]
        ]
        await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # زر المساعدة
    if data == "user_help":
        help_text = (
            "🤖 <b>كيف أستخدم البوت؟</b>\n\n"
            "1. استطيع قراءة الاقتباسات من الأقسام المختلفة.\n"
            "2. يمكنك الضغط على 'اقتباس عشوائي' للحصول على رسالة فورية.\n"
            "3. لاستخدامي في مجموعتك، قم برفعي مشرفاً."
        )
        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="back_user")]]
        await query.edit_message_text(help_text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # --- منطق المطور والمشرف ---

    # --- نظام النسخ الاحتياطي ---
    if data == "backup_menu" and role == "dev":
        keyboard = [
            [InlineKeyboardButton("⬇️ تحميل نسخة احتياطية", callback_data="do_backup")],
            [InlineKeyboardButton("⬆️ استعادة نسخة احتياطية", callback_data="start_restore")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back_dev")]
        ]
        await query.edit_message_text("🛡️ نظام النسخ الاحتياطي:", reply_markup=InlineKeyboardMarkup(keyboard))

    if data == "do_backup" and role == "dev":
        await query.edit_message_text("⏳ جاري إنشاء النسخة الاحتياطية...")
        await create_backup(context.bot, user_id)
        await asyncio.sleep(2)
        kb, title = get_keyboard_by_role("dev")
        await query.edit_message_text(f"🔹 <b>{title}</b> 🔹", reply_markup=kb, parse_mode='HTML')

    # --- قائمة المستخدمين (جديد) ---
    if data == "view_users" and role == "dev":
        session = db.Session()
        try:
            users = session.query(db.User).order_by(db.User.user_id.desc()).limit(20).all()
            if not users:
                await query.edit_message_text("لا يوجد مستخدمين.", reply_markup=get_back_keyboard("dev"))
                return

            text = "👥 <b>آخر 20 مستخدم:</b>\n\n"
            for user in users:
                status = "👨‍💼 (مشرف)" if user.is_admin else "👤 (مستخدم)"
                username = f"@{user.username}" if user.username else "بدون يوزر"
                text += f"{status}\n🆔 <code>{user.user_id}</code>\n📝 {username}\n{'─'*20}\n"
            
            # نرسل رسالة جديدة لتجنب مشكلة طول الرسالة في edit_message_text
            await query.message.reply_text(text, parse_mode='HTML')
            kb, title = get_keyboard_by_role("dev")
            await query.edit_message_text(f"🔹 <b>{title}</b> 🔹", reply_markup=kb, parse_mode='HTML')
            
        except Exception as e:
            logger.error(f"Error viewing users: {e}")
            await query.edit_message_text("حدث خطأ.", reply_markup=get_back_keyboard("dev"))
        finally:
            session.close()

    # --- بداية المحادثات (Conversations) ---
    if data == "start_add_channel":
        context.user_data.clear()
        await query.edit_message_text("✏️ أرسل الآن:\n1. رابط القناة العامة (مثلاً @Channel)\n2. أو قم بتحويل رسالة (Forward) من القناة", reply_markup=get_back_keyboard(role))
        return CHANNEL_INPUT

    if data == "start_broadcast" and role in ["dev", "admin"]:
        context.user_data.clear()
        await query.edit_message_text("✏️ أرسل الرسالة التي تريد إذاعتها:", reply_markup=get_back_keyboard(role))
        return BROADCAST_STATE

    if data == "manage_admins" and role == "dev":
        keyboard = [
            [InlineKeyboardButton("➕ إضافة مشرف", callback_data="conv_add_admin")],
            [InlineKeyboardButton("➖ حذف مشرف", callback_data="conv_del_admin")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back_dev")]
        ]
        await query.edit_message_text("اختر العملية:", reply_markup=InlineKeyboardMarkup(keyboard))
    
    if data == "conv_add_admin" and role == "dev":
        await query.edit_message_text("أرسل الآن (آيدي) أو (معرف المستخدم) للإضافة:", reply_markup=get_back_keyboard(role))
        return ADD_ADMIN_INPUT

    if data == "conv_del_admin" and role == "dev":
        await query.edit_message_text("أرسل الآن (آيدي) أو (معرف المستخدم) للحذف:", reply_markup=get_back_keyboard(role))
        return DEL_ADMIN_INPUT

    # --- خطوات إضافة قناة (Flow) ---
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
            await finalize_channel_addition_logic(query, role, context)
            return ConversationHandler.END
        else:
            if time_type == "fixed":
                context.user_data['action'] = 'set_fixed_time'
                msg = "أرسل الساعات المطلوبة (مثلاً: 10, 14, 20) مفصولة بفاصلة:"
            elif time_type == "interval":
                context.user_data['action'] = 'set_interval'
                msg = "أرسل الفارق الزمني بالدقائق (مثلاً: 60):"
            await query.edit_message_text(msg, reply_markup=get_back_keyboard(role))
            return CHANNEL_TIME_INPUT

    # --- إدارة الملفات ---
    if data == "manage_files" and role in ["dev", "admin"]:
        keyboard = [[InlineKeyboardButton(name, callback_data=f"upload_{code}")] for name, code in CATEGORIES]
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"back_{role}")])
        await query.edit_message_text("اختر القسم لرفع ملفات الاقتباسات (txt):", reply_markup=InlineKeyboardMarkup(keyboard))
    
    if data.startswith("upload_"):
        category = data.split("_")[1]
        context.user_data['upload_category'] = category
        await query.edit_message_text(f"تم اختيار قسم: <b>{category}</b>\n\nالآن قم بإرسال ملف <code>.txt</code>.", parse_mode='HTML', reply_markup=get_back_keyboard(role))

    # --- إدارة القنوات (عرض وحذف) ---
    if data == "manage_channels" and role in ["dev", "admin"]:
        session = db.Session()
        try:
            channels = session.query(db.Channel).all()
            if not channels:
                await query.edit_message_text("لا توجد قنوات مضافة.", reply_markup=get_back_keyboard(role))
                return
            keyboard = [[InlineKeyboardButton(f"{ch.title} ({ch.category})", callback_data=f"edit_channel_{ch.id}")] for ch in channels]
            keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"back_{role}")])
            await query.edit_message_text("اختر قناة للتعديل أو الحذف:", reply_markup=InlineKeyboardMarkup(keyboard))
        finally: session.close()

    if data.startswith("edit_channel_"):
        ch_id = int(data.split("_")[2])
        context.user_data['editing_channel_id'] = ch_id
        keyboard = [
            [InlineKeyboardButton("🔄 تغيير المحتوى", callback_data="edit_cat_select")],
            [InlineKeyboardButton("🎨 تغيير الشكل", callback_data="edit_fmt_select")],
            [InlineKeyboardButton("⏰ تغيير الوقت", callback_data="edit_time_select")],
            [InlineKeyboardButton("🗑️ حذف القناة", callback_data="confirm_del_channel")],
            [InlineKeyboardButton("🔙 رجوع", callback_data=f"back_{role}")]
        ]
        await query.edit_message_text("خيارات التعديل:", reply_markup=InlineKeyboardMarkup(keyboard))

    if data == "confirm_del_channel":
        ch_id = context.user_data.get('editing_channel_id')
        keyboard = [
            [InlineKeyboardButton("❌ لا", callback_data=f"edit_channel_{ch_id}")],
            [InlineKeyboardButton("✅ نعم، احذف", callback_data=f"exec_del_channel_{ch_id}")]
        ]
        await query.edit_message_text("هل أنت متأكد من حذف القناة؟", reply_markup=InlineKeyboardMarkup(keyboard))

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

    # --- منطق التعديل (مبسط) ---
    if data == "edit_cat_select":
        await query.edit_message_text("اختر المحتوى:", reply_markup=get_categories_keyboard(f"set_edit_cat_{context.user_data['editing_channel_id']}"))
    if data.startswith("set_edit_cat_"):
        parts = data.split("_")
        session = db.Session()
        try:
            ch_id = int(parts[3])
            category = "_".join(parts[4:]) 
            ch = session.query(db.Channel).filter_by(id=ch_id).first()
            if ch: 
                ch.category = category
                session.commit()
                msg = "✅ تم تحديث المحتوى."
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
            if ch: 
                ch.msg_format = parts[4]
                session.commit()
                msg = "✅ تم تحديث الشكل."
        except: msg = "❌ خطأ."
        finally: session.close()
        await query.edit_message_text(msg, parse_mode='HTML', reply_markup=get_back_keyboard(role))

    if data == "edit_time_select":
        await query.edit_message_text("اختر الوقت:", reply_markup=get_time_keyboard(f"set_edit_time_{context.user_data['editing_channel_id']}"))
    if data.startswith("set_edit_time_"):
        time_type = data.split("_")[-1]
        session = db.Session()
        try:
            ch = session.query(db.Channel).filter_by(id=int(data.split("_")[3])).first()
            if ch: 
                ch.time_type = time_type
                ch.time_value = None if time_type == 'default' else ch.time_value
                session.commit()
                msg = "✅ تم تغيير التوقيت."
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
            await query.edit_message_text(f"تم تغيير الحالة إلى: <b>{state_text}</b>", parse_mode='HTML', reply_markup=get_back_keyboard(role))
        finally: session.close()

    if data == "post_now":
        await query.edit_message_text("جاري النشر الفوري...")
        await post_job_logic(context, force_one=True)
        await query.edit_message_text("تم النشر الفوري ✅", reply_markup=get_back_keyboard(role))

# --- معالجة النصوص والملفات ---

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    role = get_role(user_id)
    text = update.message.text
    current_state = context.user_data.get('conv_state')

    # منطق إضافة القناة
    if current_state == CHANNEL_INPUT:
        chat_id, title, error_msg = await resolve_channel_info(context, text, update.message.forward_from_chat)
        if error_msg:
            await update.message.reply_text(error_msg, reply_markup=get_back_keyboard(role))
            return ConversationHandler.END
        
        if await is_bot_admin_in_channel(context.bot, chat_id):
            context.user_data['pending_channel'] = {'id': chat_id, 'title': title}
            context.user_data['conv_state'] = None
            await update.message.reply_text(f"✅ تم التحقق من: <b>{title}</b>\n\nاختر القسم:", parse_mode='HTML', reply_markup=get_categories_keyboard("cat"))
            return CHANNEL_INPUT 
        else:
            await update.message.reply_text("⛔️ <b>البوت ليس مشرفاً في القناة!</b>", parse_mode='HTML')
            return ConversationHandler.END

    # منطق وقت القناة
    if current_state == CHANNEL_TIME_INPUT:
        time_type = context.user_data.get('time_type')
        val_valid = False
        
        if time_type == "fixed":
            val_valid = all(h.strip().isdigit() for h in text.split(','))
            if val_valid: context.user_data['time_settings'] = {'type': 'fixed', 'value': text}
        
        elif time_type == "interval":
            if text.strip().isdigit():
                val_valid = True
                context.user_data['time_settings'] = {'type': 'interval', 'value': text}
        
        if val_valid:
            await finalize_channel_addition_logic(update, role, context)
            return ConversationHandler.END
        else:
            await update.message.reply_text("❌ قيمة غير صحيحة. حاول مرة أخرى.")
            return CHANNEL_TIME_INPUT

    # منطق الإذاعة
    if current_state == BROADCAST_STATE:
        await update.message.reply_text("⏳ جاري الإذاعة...")
        asyncio.create_task(broadcast_task_logic(context.bot, text))
        return ConversationHandler.END

    # منطق إدارة المشرفين
    if current_state == ADD_ADMIN_INPUT:
        target = text.strip().replace("@", "")
        session = db.Session()
        try:
            user = session.query(db.User).filter((db.User.username == target) | (db.User.user_id == str(target))).first()
            if user: 
                user.is_admin = True
                session.commit()
                msg = f"✅ تم رفع المشرف {user.username or user.user_id}."
            else: 
                msg = "❌ لم أجد المستخدم في قاعدة البيانات."
        finally: session.close()
        await update.message.reply_text(msg, parse_mode='HTML', reply_markup=get_back_keyboard(role))
        return ConversationHandler.END
    
    if current_state == DEL_ADMIN_INPUT:
        target = text.strip().replace("@", "")
        session = db.Session()
        try:
            user = session.query(db.User).filter((db.User.username == target) | (db.User.user_id == str(target))).first()
            if user and user.user_id != config.DEVELOPER_ID:
                user.is_admin = False
                session.commit()
                msg = "✅ تمت الإزالة."
            elif user and user.user_id == config.DEVELOPER_ID:
                msg = "❌ لا يمكنك حذف المطور!"
            else: 
                msg = "❌ خطأ."
        finally: session.close()
        await update.message.reply_text(msg, parse_mode='HTML', reply_markup=get_back_keyboard(role))
        return ConversationHandler.END

    # تفعيل المجموعة
    if text == "تفعيل" and update.effective_chat.type in ['group', 'supergroup']:
        if await is_bot_admin_in_channel(context.bot, update.effective_chat.id):
            db.add_channel(update.effective_chat.id, update.effective_chat.title, user_id, "اقتباسات عامة", "normal", "default", None)
            await update.message.reply_text("✅ تم التفعيل في المجموعة!")

async def handle_file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    category = context.user_data.get('upload_category')
    
    if document and category:
        if document.mime_type == "text/plain":
            try:
                file = await document.get_file()
                content_bytes = await file.download_as_bytearray()
                content_list = [line for line in content_bytes.decode('utf-8').splitlines() if line.strip()]
                count = db.add_file_content(category, content_list)
                msg = f"✅ تمت إضافة <b>{count}</b> سطر/اقتباس."
                context.user_data['upload_category'] = None
            except Exception as e:
                msg = f"❌ خطأ: {e}"
                logger.error(f"Upload Error: {e}")
        else:
            msg = "❌ ملف .txt فقط."
        role = get_role(update.effective_user.id)
        await update.message.reply_text(msg, parse_mode='HTML', reply_markup=get_back_keyboard(role))

# --- دوال النسخ الاحتياطي (Backup Logic) ---

async def create_backup(bot, user_id):
    session = db.Session()
    try:
        backup_data = {
            "users": [],
            "channels": [],
            "settings": [],
            "content": []
        }

        for u in session.query(db.User).all():
            backup_data["users"].append({
                "user_id": u.user_id, "username": u.username, "is_admin": u.is_admin
            })
        
        for ch in session.query(db.Channel).all():
            backup_data["channels"].append({
                "id": ch.id, "channel_id": ch.channel_id, "title": ch.title, 
                "category": ch.category, "msg_format": ch.msg_format,
                "time_type": ch.time_type, "time_value": ch.time_value, "is_active": ch.is_active
            })

        for s in session.query(db.BotSettings).all():
            backup_data["settings"].append({"key": s.key, "value": s.value})

        if hasattr(db, 'FileContent'):
            for c in session.query(db.FileContent).all():
                backup_data["content"].append({"category": c.category, "text": c.text})

        json_str = json.dumps(backup_data, ensure_ascii=False, indent=4)
        file_bytes = io.BytesIO(json_str.encode('utf-8'))
        file_bytes.name = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        await bot.send_document(chat_id=user_id, document=file_bytes, caption="✅ النسخة الاحتياطية جاهزة.")
        
    except Exception as e:
        logger.error(f"Backup Error: {e}")
        await bot.send_message(chat_id=user_id, text=f"❌ فشل النسخ الاحتياطي: {e}")
    finally:
        session.close()

async def handle_restore_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    if document.mime_type == "application/json" or document.file_name.endswith('.json'):
        await update.message.reply_text("⏳ جاري قراءة الملف واستعادة البيانات...")
        try:
            file = await document.get_file()
            content_bytes = await file.download_as_bytearray()
            data = json.loads(content_bytes.decode('utf-8'))
            
            session = db.Session()
            try:
                session.query(db.Channel).delete()
                session.query(db.BotSettings).delete()
                if hasattr(db, 'FileContent'):
                    session.query(db.FileContent).delete()
                
                dev_id = config.DEVELOPER_ID
                session.query(db.User).filter(db.User.user_id != dev_id).delete()
                
                for u_data in data.get("users", []):
                    if u_data['user_id'] == dev_id: continue 
                    user = session.query(db.User).filter_by(user_id=u_data['user_id']).first()
                    if not user:
                        user = db.User(user_id=u_data['user_id'])
                    user.username = u_data['username']
                    user.is_admin = u_data['is_admin']
                    session.add(user)
                
                for ch_data in data.get("channels", []):
                    ch = db.Channel(**ch_data)
                    session.add(ch)

                for s_data in data.get("settings", []):
                    setting = db.BotSettings(**s_data)
                    session.add(setting)
                
                if hasattr(db, 'FileContent'):
                    for c_data in data.get("content", []):
                        content = db.FileContent(**c_data)
                        session.add(content)

                session.commit()
                await update.message.reply_text("✅ تمت استعادة النسخة الاحتياطية بنجاح!", reply_markup=get_back_keyboard("dev"))
            except Exception as e:
                session.rollback()
                raise e
            finally:
                session.close()
                
        except Exception as e:
            logger.error(f"Restore Error: {e}")
            await update.message.reply_text(f"❌ ملف تالف أو خطأ في البيانات: {e}")
            return RESTORE_CONFIRM 
    else:
        await update.message.reply_text("❌ يرجى رفع ملف بصيغة .json فقط.")
        return RESTORE_CONFIRM
    
    return ConversationHandler.END

# --- Helper Functions ---

async def resolve_channel_info(context, text, forward_from_chat):
    chat_id, title, error_msg = None, None, None
    
    if forward_from_chat:
        if forward_from_chat.type in ['channel', 'supergroup']:
            return forward_from_chat.id, forward_from_chat.title, None
        return None, None, "❌ الرسالة من مستخدم، وليست قناة."
    
    txt = text.strip()
    resolved_chat = None
    try:
        if not " " in txt and not "/" in txt:
             resolved_chat = await context.bot.get_chat(txt)
        if not resolved_chat and ("t.me/" in txt.lower()):
             parts = txt.lower().split("t.me/")
             identifier = parts[-1].split('/')[0].split('?')[0].strip()
             if not identifier.startswith("+"):
                 resolved_chat = await context.bot.get_chat(f"@{identifier}")
    except Exception:
        pass 
    
    if resolved_chat:
        if resolved_chat.type in ['channel', 'supergroup']:
            return resolved_chat.id, resolved_chat.title, None
        return None, None, "❌ المعرف لمستخدم وليس قناة."
    return None, None, "❌ لم أستطع العثور على القناة."

async def finalize_channel_addition_logic(message_obj, role, context):
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

# --- Background Logic ---

async def post_job_logic(context: ContextTypes.DEFAULT_TYPE, force_one=False):
    session = db.Session()
    try:
        setting = session.query(db.BotSettings).filter_by(key='posting_status').first()
        if not force_one and (not setting or setting.value == 'off'): return
        channels = session.query(db.Channel).filter_by(is_active=True).all()
    except Exception as e:
        logger.error(f"DB Error: {e}")
        return

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

# --- Main Setup ---

def get_application():
    application = Application.builder().token(config.TOKEN_1).build()

    # --- إضافة المحادثات (Conversations) ---
    
    # 1. محادثة إضافة قناة
    add_channel_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern="^start_add_channel$")],
        states={
            CHANNEL_INPUT: [
                MessageHandler(filters.TEXT | filters.FORWARDED, handle_text_message),
                CallbackQueryHandler(button_handler, pattern="^(cat_|fmt_|time_)")
            ],
            CHANNEL_TIME_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message)
            ]
        },
        fallbacks=[CallbackQueryHandler(button_handler, pattern="^back_")],
        name="add_channel_conv",
        persistent=False
    )

    # 2. محادثة الإذاعة
    broadcast_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern="^start_broadcast$")],
        states={
            BROADCAST_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message)]
        },
        fallbacks=[CallbackQueryHandler(button_handler, pattern="^back_")],
        name="broadcast_conv",
        persistent=False
    )

    # 3. محادثة المشرفين
    admin_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(button_handler, pattern="^conv_add_admin$"),
            CallbackQueryHandler(button_handler, pattern="^conv_del_admin$")
        ],
        states={
            ADD_ADMIN_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message)],
            DEL_ADMIN_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message)]
        },
        fallbacks=[CallbackQueryHandler(button_handler, pattern="^back_")],
        name="admin_conv",
        persistent=False
    )

    # 4. محادثة استعادة النسخة الاحتياطية
    restore_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern="^start_restore$")],
        states={
            RESTORE_CONFIRM: [MessageHandler(filters.Document.Extension("json") | filters.Document.MimeType("application/json"), handle_restore_file)]
        },
        fallbacks=[CallbackQueryHandler(button_handler, pattern="^back_dev$")],
        name="restore_conv",
        persistent=False
    )

    # --- تسجيل المعالجات ---
    application.add_handler(CommandHandler("start", start))
    
    application.add_handler(add_channel_conv)
    application.add_handler(broadcast_conv)
    application.add_handler(admin_conv)
    application.add_handler(restore_conv)
    
    application.add_handler(CallbackQueryHandler(button_handler))
    
    application.add_handler(MessageHandler(filters.Document.MimeType("text/plain") & filters.ChatType.PRIVATE, handle_file_upload))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_text_message))
    application.add_handler(MessageHandler(filters.Regex("^تفعيل$") & filters.ChatType.GROUPS, handle_text_message))
    
    if application.job_queue:
        application.job_queue.run_repeating(post_job_logic, interval=60, first=10)

    return application

if __name__ == '__main__':
    try:
        app = get_application()
        logger.info("✅ البوت يعمل الآن!")
        app.run_polling(drop_pending_updates=True)
    except KeyboardInterrupt:
        logger.info("تم الإيقاف.")
    except Exception as e:
        logger.error(f"Critical Error: {e}")
