import os
import asyncio
import logging
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultArticle, InputTextMessageContent
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, InlineQueryHandler, ContextTypes, filters
import yt_dlp

# إعداد التسجيل (Logging)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# التوكن الخاص بالبوت (يجب استبداله بالتوكن الحقيقي من BotFather)
BOT_TOKEN = '6741306329:AAF9gyhoD_li410vEdu62s7WlhZVVpKJu58'

# الحد الأقصى لحجم الملف (50 ميجابايت)
MAX_FILE_SIZE = 50 * 1024 * 1024

# خيارات yt-dlp الأساسية لتخطي الحظر
YDL_OPTIONS_BASE = {
    'quiet': True,
    'no_warnings': True,
    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'referer': 'https://www.google.com/',
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "أهلاً بك في بوت التنزيل الفوري! 🚀\n\n"
        "أنا هنا لمساعدتك في تحميل الفيديوهات والمقاطع الصوتية من مختلف المنصات بكل سهولة.\n\n"
        "**كيفية الاستخدام:**\n"
        "*   **للتحميل:** فقط أرسل لي رابط الفيديو من (يوتيوب، انستغرام، تيك توك، فيسبوك، تويتر، أو بنترست).\n"
        "*   **للبحث:** اكتب اسم البوت ثم مسافة ثم اسم الفيديو الذي تبحث عنه.\n\n"
        "لنبدأ!"
    )
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    if not re.match(r'http[s]?://', url):
        return

    status_msg = await update.message.reply_text("جاري فحص الرابط... 🔍")

    try:
        with yt_dlp.YoutubeDL(YDL_OPTIONS_BASE) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # التحقق من الحجم (إذا كان متاحاً)
            filesize = info.get('filesize') or info.get('filesize_approx')
            if filesize and filesize > MAX_FILE_SIZE:
                await status_msg.edit_text(f"عذراً، حجم الملف ({filesize / (1024*1024):.1f}MB) يتجاوز الحد المسموح به (50MB).")
                return

            title = info.get('title', 'فيديو')
            keyboard = [
                [
                    InlineKeyboardButton("فيديو 🎬", callback_data=f"vid|{url}"),
                    InlineKeyboardButton("صوت 🎵", callback_data=f"aud|{url}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await status_msg.edit_text(f"تم العثور على: {title}\nاختر الصيغة المطلوبة:", reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Error extracting info: {e}")
        await status_msg.edit_text("عذراً، حدث خطأ أثناء معالجة الرابط. تأكد من صحة الرابط أو حاول لاحقاً.")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data.split('|')
    mode = data[0]
    url = data[1]
    
    await query.edit_message_text("جاري التحميل... ⏳")
    
    file_path = f"download_{query.from_user.id}"
    
    ydl_opts = YDL_OPTIONS_BASE.copy()
    if mode == 'vid':
        ydl_opts.update({
            'format': 'best[ext=mp4]/best',
            'outtmpl': f'{file_path}.%(ext)s',
            'max_filesize': MAX_FILE_SIZE,
        })
    else:
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': f'{file_path}.%(ext)s',
            'max_filesize': MAX_FILE_SIZE,
        })

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            if mode == 'aud':
                filename = filename.rsplit('.', 1)[0] + '.mp3'

        if os.path.exists(filename):
            if os.path.getsize(filename) > MAX_FILE_SIZE:
                await query.edit_message_text("عذراً، الملف الناتج تجاوز الحد المسموح به (50MB).")
            else:
                with open(filename, 'rb') as f:
                    if mode == 'vid':
                        await query.message.reply_video(video=f, caption=info.get('title'))
                    else:
                        await query.message.reply_audio(audio=f, title=info.get('title'))
                await query.delete_message()
            
            # حذف الملف بعد الإرسال (لا يحتفظ بالسجلات)
            if os.path.exists(filename):
                os.remove(filename)
        else:
            await query.edit_message_text("فشل التحميل، حاول مرة أخرى.")

    except Exception as e:
        logger.error(f"Download error: {e}")
        await query.edit_message_text("حدث خطأ أثناء التحميل. قد يكون الملف كبيراً جداً أو الرابط غير مدعوم.")

async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query
    if not query:
        return

    results = []
    try:
        search_opts = YDL_OPTIONS_BASE.copy()
        search_opts.update({'extract_flat': True})
        with yt_dlp.YoutubeDL(search_opts) as ydl:
            search_results = ydl.extract_info(f"ytsearch5:{query}", download=False)['entries']
            
            for i, entry in enumerate(search_results):
                results.append(
                    InlineQueryResultArticle(
                        id=str(i),
                        title=entry['title'],
                        input_message_content=InputTextMessageContent(entry['url']),
                        description=f"رابط: {entry['url']}"
                    )
                )
    except Exception as e:
        logger.error(f"Inline search error: {e}")

    await update.inline_query.answer(results)

if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(InlineQueryHandler(inline_query))
    
    print("البوت يعمل الآن...")
    app.run_polling()
