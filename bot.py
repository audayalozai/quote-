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
TOKEN = "6741306329:AAG-or3-0oGmr3QJWN-kCC7tYxP7FTLlYgo"  # ضع التوكن هنا
DEVELOPER_ID = 778375826       # ضع آيديك الرقمي هنا
ADMINS_IDS = [778375826]
APPLICATION = None  # مت عام لتخزين كائن التطبيق

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

# إضافة connect_args لإصلاح مشكلة الترابط مع SQLite
engine = create_engine('sqlite:///bot_data.db', echo=False, connect_args={"check_same_thread": False})
Base = declarative_base()
Session = sessionmaker(bind=engine)

# --- نماذج قاعدة البيانات الموسعة ---

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
    
    # العلاقات
    notifications = relationship("Notification", back_populates="user")
    security_logs = relationship("SecurityLog", back_populates="user")
    two_factor_auth = relationship("TwoFactorAuth", back_populates="user", uselist=False)

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
    error_count = Column(Integer, default=0)
    last_error = Column(String, nullable=True)
    description = Column(String, nullable=True)
    subscriber_count = Column(Integer, default=0)

class Content(Base):
    __tablename__ = 'content'
    id = Column(Integer, primary_key=True)
    category = Column(String, index=True)
    text = Column(Text)
    added_by = Column(Integer, nullable=True)
    added_at = Column(DateTime, default=datetime.now)
    is_active = Column(Boolean, default=True)
    view_count = Column(Integer, default=0)
    rating = Column(Integer, default=0)
    rating_count = Column(Integer, default=0)
    
    # العلاقات
    tags = relationship("Tag", secondary="content_tags")
    reviews = relationship("Review", back_populates="content")

class Tag(Base):
    __tablename__ = 'tags'
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True)
    category = Column(String)
    color = Column(String, default="#ffffff")
    description = Column(String, nullable=True)

class ContentTag(Base):
    __tablename__ = 'content_tags'
    id = Column(Integer, primary_key=True)
    content_id = Column(Integer)
    tag_id = Column(Integer)

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
    updated_by = Column(Integer, nullable=True)
    updated_at = Column(DateTime, default=datetime.now)

class ActivityLog(Base):
    __tablename__ = 'logs'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    action = Column(String)
    details = Column(Text)
    timestamp = Column(DateTime, default=datetime.now)

# --- نماذج الإضافات الجديدة ---

class Notification(Base):
    __tablename__ = 'notifications'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    message = Column(Text)
    scheduled_time = Column(DateTime)
    is_sent = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)
    notification_type = Column(String, default='general')  # 'reminder', 'announcement', 'personal'
    
    # العلاقة بالمستخدم
    user = relationship("User", back_populates="notifications")

class Analytics(Base):
    __tablename__ = 'analytics'
    id = Column(Integer, primary_key=True)
    date = Column(DateTime, default=datetime.now)
    action = Column(String)  # 'post', 'user_join', 'content_upload', 'notification_sent'
    channel_id = Column(Integer, nullable=True)
    content_id = Column(Integer, nullable=True)
    user_id = Column(Integer, nullable=True)
    meta_data = Column(String, nullable=True)  # JSON string for additional data

class SecurityLog(Base):
    __tablename__ = 'security_logs'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    action = Column(String)  # 'login', 'failed_login', 'suspicious_activity', '2fa_enabled'
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    timestamp = Column(DateTime, default=datetime.now)
    
    # العلاقة بالمستخدم
    user = relationship("User", back_populates="security_logs")

class TwoFactorAuth(Base):
    __tablename__ = '2fa'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, unique=True)
    secret_key = Column(String)
    is_enabled = Column(Boolean, default=False)
    backup_codes = Column(String)  # JSON array
    created_at = Column(DateTime, default=datetime.now)
    
    # العلاقة بالمستخدم
    user = relationship("User", back_populates="two_factor_auth")

class Review(Base):
    __tablename__ = 'reviews'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    rating = Column(Integer)  # 1-5
    comment = Column(Text)
    content_id = Column(Integer)
    created_at = Column(DateTime, default=datetime.now)
    
    # العلاقة بالمحتوى
    content = relationship("Content", back_populates="reviews")

class Language(Base):
    __tablename__ = 'languages'
    id = Column(Integer, primary_key=True)
    code = Column(String, unique=True)
    name = Column(String)
    flag = Column(String)
    is_active = Column(Boolean, default=True)

class Translation(Base):
    __tablename__ = 'translations'
    id = Column(Integer, primary_key=True)
    key = Column(String)
    text = Column(Text)
    language_code = Column(String)

class PremiumFeature(Base):
    __tablename__ = 'premium_features'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, unique=True)
    features = Column(String)  # JSON string
    expires_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now)
    is_active = Column(Boolean, default=True)

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

def simple_retry(max_retries=3, delay=1, exceptions=(Exception,)):
    """ديكور بسيط لإعادة المحاولة"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_retries - 1:
                        raise
                    await asyncio.sleep(delay * (attempt + 1))
        return wrapper
    return decorator

def get_session():
    """الحصول على جلسة قاعدة البيانات مع إعادة المحاولة"""
    session = Session()
    try:
        return session
    except SQLAlchemyError:
        session.close()
        raise

def db_log_action(user_id, action, details=""):
    """سجل الأنشطة بشكل غير متزامن"""
    uid = user_id if user_id else 0
    
    async def log_action():
        session = get_session()
        try:
            log = ActivityLog(user_id=uid, action=action, details=details)
            session.add(log)
            session.commit()
        except Exception as e:
            logger.error(f"Log Error: {e}")
        finally:
            session.close()
    
    # تشغيل المهمة في الخلفية
    if APPLICATION:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(log_action())
        except RuntimeError:
            pass

def get_role(user_id):
    """الحصول على دور المستخدم"""
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
    """الحصول على القناة المطلوبة للاشتراك"""
    session = get_session()
    try:
        setting = session.query(BotSettings).filter_by(key='required_channel').first()
        return setting.value if setting else None
    finally:
        session.close()

async def check_subscription(user_id, required_channel):
    """التحقق من اشتراك المستخدم"""
    if not required_channel:
        return True
    
    try:
        member = await APPLICATION.bot.get_chat_member(required_channel, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Subscription check error for user {user_id}: {e}")
        return False

def get_filters():
    """الحصول على قواعد الترشيح النشطة"""
    session = get_session()
    try:
        return {f.word: f.replacement for f in session.query(Filter).filter_by(is_active=True).all()}
    finally:
        session.close()

async def filter_text(text):
    """تطبيق الترشيح على النص"""
    if not text:
        return text
    
    filters_dict = get_filters()
    for word, replacement in filters_dict.items():
        if word in text:
            text = text.replace(word, replacement)
            # تحديث عدد الاستخدامات
            session = get_session()
            try:
                filter_obj = session.query(Filter).filter_by(word=word).first()
                if filter_obj:
                    filter_obj.usage_count += 1
                    session.commit()
            except Exception as e:
                logger.error(f"Filter usage update error: {e}")
            finally:
                session.close()
    return text

def get_global_status():
    """الحصول على حالة البوت العامة"""
    session = get_session()
    try:
        setting = session.query(BotSettings).filter_by(key='global_status').first()
        return setting.value == 'on' if setting else True
    finally:
        session.close()

def get_stats():
    """الحصول على إحصائيات البوت"""
    session = get_session()
    try:
        users_count = session.query(User).count()
        active_users = session.query(User).filter_by(is_banned=False).count()
        premium_users = session.query(User).filter_by(is_premium=True).count()
        admins_count = session.query(User).filter_by(is_admin=True).count()
        channels_count = session.query(Channel).count()
        active_channels = session.query(Channel).filter_by(is_active=True).count()
        content_count = session.query(Content).filter_by(is_active=True).count()
        filters_count = session.query(Filter).filter_by(is_active=True).count()
        notifications_count = session.query(Notification).filter_by(is_sent=False).count()
        
        return f"📊 <b>إحصائيات البوت:</b>\n\n👥 المستخدمين: {users_count} (نشط: {active_users}، مميز: {premium_users})\n🛡️ المشرفين: {admins_count}\n📢 القنوات: {channels_count} (نشط: {active_channels})\n📝 المحتوى: {content_count} نص\n🔍 الترشيحات: {filters_count} قاعدة\n🔔 الإشعارات: {notifications_count} مجدولة"
    finally:
        session.close()

# --- الثوابت ---
CATEGORIES = [
    ("❤️ حب", "حب"),
    ("🎂 عيد ميلاد", "عيد ميلاد"),
    ("💭 اقتباسات عامة", "اقتباسات عامة"),
    ("📜 ابيات شعرية", "ابيات شعرية"),
    ("📚 ديني", "ديني"),
    ("😂 مضحك", "مضحك"),
    ("📱 تقني", "تقني"),
    ("⚽ رياضة", "رياضة"),
    ("🎨 فن", "فن"),
    ("🏛️ سياسة", "سياسة"),
    ("💰 اقتصاد", "اقتصاد")
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
STATE_EDIT_CHANNEL = 11
STATE_NOTIFICATION = 12
STATE_PREMIUM_ACTIVATE = 13
STATE_LANGUAGE_SELECT = 14
STATE_REVIEW = 15
STATE_SEARCH = 16
STATE_TAG_SELECT = 17

# --- أنظمة الإضافات ---

class CacheManager:
    def __init__(self):
        self.cache = {}
        self.cache_timeout = 300  # 5 دقائق
    
    async def get(self, key):
        if key in self.cache:
            data, timestamp = self.cache[key]
            if datetime.now() - timestamp < timedelta(seconds=self.cache_timeout):
                return data
            else:
                del self.cache[key]
        return None
    
    async def set(self, key, value):
        self.cache[key] = (value, datetime.now())
    
    async def clear(self):
        self.cache.clear()

class TaskQueue:
    def __init__(self):
        self.tasks = []
        self.current_task = None
    
    def add_task(self, task_func, priority=0, delay=0):
        """إضافة مهمة للقائمة"""
        scheduled_time = datetime.now() + timedelta(seconds=delay)
        heapq.heappush(self.tasks, (scheduled_time, priority, task_func))
    
    async def process_tasks(self):
        """معالجة المهام المجدولة"""
        while True:
            await self.process_tasks_logic()
            await asyncio.sleep(1)

    async def process_tasks_logic(self):
        """منطق معالجة المهام (مفصول لتحسين الأداء)"""
        while self.tasks:
            scheduled_time, priority, task_func = self.tasks[0]
            if datetime.now() >= scheduled_time:
                heapq.heappop(self.tasks)
                try:
                    await task_func()
                except Exception as e:
                    logger.error(f"Task execution failed: {e}")
            else:
                break

# --- مراقب الأداء (تم تعديله ليكون Decorator) ---
class PerformanceMonitor:
    def __init__(self):
        self.stats = {
            'response_times': [],
            'error_count': 0,
            'total_requests': 0,
            'cache_hits': 0,
            'cache_misses': 0
        }
    
    def __call__(self, func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            success = True
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                success = False
                raise e
            finally:
                end_time = time.time()
                response_time = end_time - start_time
                self.record_request(response_time, success)
        return wrapper
    
    @property
    def avg_response_time(self):
        if not self.stats['response_times']:
            return 0
        return sum(self.stats['response_times']) / len(self.stats['response_times'])
    
    @property
    def error_rate(self):
        if self.stats['total_requests'] == 0:
            return 0
        return (self.stats['error_count'] / self.stats['total_requests']) * 100
    
    def record_request(self, response_time, success=True):
        self.stats['response_times'].append(response_time)
        self.stats['total_requests'] += 1
        if not success:
            self.stats['error_count'] += 1
        
        # الحفاظ على آخر 1000 طلب فقط
        if len(self.stats['response_times']) > 1000:
            self.stats['response_times'] = self.stats['response_times'][-1000:]
    
    def record_cache_hit(self):
        self.stats['cache_hits'] += 1
    
    def record_cache_miss(self):
        self.stats['cache_misses'] += 1
    
    def get_report(self):
        if not self.stats['response_times']:
            return "لا توجد بيانات أداء بعد"
        
        cache_hit_rate = (self.stats['cache_hits'] / (self.stats['cache_hits'] + self.stats['cache_misses'])) * 100 if (self.stats['cache_hits'] + self.stats['cache_misses']) > 0 else 0
        
        return f"""
📊 تقرير الأداء:
─────────────────
🔄 الطلبات الإجمالية: {self.stats['total_requests']}
⚠️ الأخطاء: {self.stats['error_count']} ({self.error_rate:.1f}%)
⏱️ متوسط وقت الاستجابة: {self.avg_response_time:.2f} ثانية
💾 نسبة نجاح التخزين المؤقت: {cache_hit_rate:.1f}%
📈 الطلبات الناجحة: {self.stats['total_requests'] - self.stats['error_count']}
"""

# --- متغيرات عامة ---
cache_manager = CacheManager()
task_queue = TaskQueue()

# إنشاء نسخة واحدة من مراقب الأداء ليتم استخدامها كـ Decorator ومشتركة للإحصائيات
perf_monitor = PerformanceMonitor()

# --- دوال الإضافات الجديدة ---

async def send_scheduled_notifications():
    """إرسال الإشعارات المجدولة"""
    session = get_session()
    try:
        now = datetime.now()
        notifications = session.query(Notification).filter(
            Notification.scheduled_time <= now,
            Notification.is_sent == False
        ).all()
        
        sent_count = 0
        for notification in notifications:
            try:
                # التحقق من اشتراك المستخدم
                required_channel = get_required_channel()
                if required_channel:
                    is_subscribed = await check_subscription(notification.user_id, required_channel)
                    if not is_subscribed:
                        continue
                
                await APPLICATION.bot.send_message(
                    notification.user_id,
                    f"⏰ تذكير:\n\n{notification.message}",
                    parse_mode='HTML'
                )
                notification.is_sent = True
                sent_count += 1
                session.commit()
                
                # تسجيل الإشعار
                db_log_action(notification.user_id, "NOTIFICATION_SENT", f"Scheduled notification: {notification.message[:50]}...")
                
            except Exception as e:
                logger.error(f"Failed to send notification to user {notification.user_id}: {e}")
                
    finally:
        session.close()
    
    if sent_count > 0:
        logger.info(f"Sent {sent_count} scheduled notifications")

async def backup_database():
    """عملية النسخ الاحتياطي التلقائي"""
    try:
        backup_dir = "backups"
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = f"{backup_dir}/backup_{timestamp}.db"
        
        # نسخ قاعدة البيانات
        shutil.copy2("bot_data.db", backup_file)
        
        # تسجيل النسخة الاحتياطية
        session = get_session()
        try:
            backup = Backup(
                filename=backup_file,
                size=os.path.getsize(backup_file)
            )
            session.add(backup)
            session.commit()
        finally:
            session.close()
        
        # حذف النسخ القديمة (احتفاظ بأحدث 5 نسخ)
        backups = sorted([f for f in os.listdir(backup_dir) if f.endswith('.db')])
        if len(backups) > 5:
            for old_backup in backups[:-5]:
                old_backup_path = os.path.join(backup_dir, old_backup)
                os.remove(old_backup_path)
                # إلغاء التسجيل من قاعدة البيانات
                session = get_session()
                try:
                    session.query(Backup).filter_by(filename=old_backup_path).delete()
                    session.commit()
                finally:
                    session.close()
        
        logger.info(f"Database backup created: {backup_file}")
        return True
    except Exception as e:
        logger.error(f"Backup failed: {e}")
        return False

async def restore_database(backup_file):
    """استعادة قاعدة البيانات من نسخة احتياطية"""
    try:
        if os.path.exists(backup_file):
            shutil.copy2(backup_file, "bot_data.db")
            logger.info(f"Database restored from: {backup_file}")
            return True
        return False
    except Exception as e:
        logger.error(f"Restore failed: {e}")
        return False

async def get_analytics_report(days=7):
    """الحصول على تقرير إحصائي متقدم"""
    session = get_session()
    try:
        start_date = datetime.now() - timedelta(days=days)
        
        # إحصائيات النشر
        posts_count = session.query(Analytics).filter(
            Analytics.action == 'post',
            Analytics.date >= start_date
        ).count()
        
        # إحصائيات المستخدمين الجدد
        new_users = session.query(User).filter(
            User.join_date >= start_date
        ).count()
        
        # إحصائيات المحتوى
        new_content = session.query(Content).filter(
            Content.added_at >= start_date
        ).count()
        
        # إحصائيات الإشعارات
        notifications_sent = session.query(Analytics).filter(
            Analytics.action == 'notification_sent',
            Analytics.date >= start_date
        ).count()
        
        # الإحصائيات حسب القناة
        channel_stats = session.query(
            Channel.title,
            func.count(Analytics.id).label('posts_count')
        ).join(
            Analytics, Channel.channel_id == Analytics.channel_id
        ).filter(
            Analytics.action == 'post',
            Analytics.date >= start_date
        ).group_by(Channel.title).all()
        
        # الإحصائيات حسب الفئة
        category_stats = session.query(
            Content.category,
            func.count(Content.id).label('content_count')
        ).filter(
            Content.added_at >= start_date
        ).group_by(Content.category).all()
        
        return {
            'period': f'آخر {days} أيام',
            'posts': posts_count,
            'new_users': new_users,
            'new_content': new_content,
            'notifications': notifications_sent,
            'channel_stats': channel_stats,
            'category_stats': category_stats
        }
    finally:
        session.close()

async def get_cached_channels():
    """الحصول على القنوات من التخزين المؤقت"""
    cached_data = await cache_manager.get('channels')
    if cached_data:
        perf_monitor.record_cache_hit()
        return cached_data
    
    perf_monitor.record_cache_miss()
    session = get_session()
    try:
        channels = session.query(Channel).all()
        await cache_manager.set('channels', channels)
        return channels
    finally:
        session.close()

async def search_content(query, category=None, limit=10):
    """البحث في المحتوى"""
    session = get_session()
    try:
        search_query = session.query(Content).filter_by(is_active=True)
        
        if category:
            search_query = search_query.filter_by(category=category)
        
        # البحث في النص
        search_query = search_query.filter(
            Content.text.contains(query)
        )
        
        # زيادة عدد المشاهدات
        content_list = search_query.limit(limit).all()
        for content in content_list:
            content.view_count += 1
            session.commit()
        
        return content_list
    finally:
        session.close()

async def schedule_content_posting():
    """جدولة نشر المحتوى"""
    session = get_session()
    try:
        content = session.query(Content).filter_by(is_active=True).order_by(func.random()).first()
        if content:
            task_queue.add_task(
                lambda: post_content_to_channels(content),
                priority=1,
                delay=random.randint(60, 3600)  # بين 1 دقيقة و ساعة
            )
    finally:
        session.close()

async def post_content_to_channels(content):
    """نشر المحتوى للقنوات"""
    session = get_session()
    try:
        channels = session.query(Channel).filter_by(is_active=True).all()
        
        for channel in channels:
            try:
                text = await filter_text(content.text)
                if channel.msg_format == 'blockquote': 
                    text = f"<blockquote>{text}</blockquote>"
                
                await APPLICATION.bot.send_message(channel.channel_id, text, parse_mode='HTML')
                
                # تسجيل النشر في الإحصائيات
                analytics = Analytics(
                    action='post',
                    channel_id=channel.channel_id,
                    content_id=content.id,
                    meta_data=json.dumps({'channel_title': channel.title})
                )
                session.add(analytics)
                session.commit()
                
                logger.info(f"Posted to {channel.title}")
                await asyncio.sleep(1) 
                
            except Exception as e:
                logger.error(f"Failed to post to {channel.title}: {e}")
                
        # زيادة عدد المشاهدات
        content.view_count += len(channels)
        session.commit()
        
    finally:
        session.close()

# --- الكيبوردات المحسنة ---

def get_main_menu(role):
    """الحصول على القائمة الرئيسية"""
    if role == "dev":
        buttons = [
            [InlineKeyboardButton("📢 إضافة قناة", callback_data="add_channel_start")],
            [InlineKeyboardButton("📢 إدارة القنوات", callback_data="manage_channels")],
            [InlineKeyboardButton("📝 رفع محتوى", callback_data="upload_content_menu")],
            [InlineKeyboardButton("📂 إدارة المحتوى", callback_data="manage_content")],
            [InlineKeyboardButton("🔍 ترشيحات", callback_data="filters_menu")],
            [InlineKeyboardButton("🔧 إعدادات البوت", callback_data="bot_settings")],
            [InlineKeyboardButton("📊 الإحصائيات", callback_data="stats")],
            [InlineKeyboardButton("🔒 الأمان", callback_data="security_menu")],
            [InlineKeyboardButton("💾 النسخ الاحتياطي", callback_data="backup_menu")],
        ]
    elif role == "admin":
        buttons = [
            [InlineKeyboardButton("📢 إضافة قناة", callback_data="add_channel_start")],
            [InlineKeyboardButton("📢 إدارة القنوات", callback_data="manage_channels")],
            [InlineKeyboardButton("📝 رفع محتوى", callback_data="upload_content_menu")],
            [InlineKeyboardButton("📂 إدارة المحتوى", callback_data="manage_content")],
            [InlineKeyboardButton("🔍 ترشيحات", callback_data="filters_menu")],
            [InlineKeyboardButton("📊 الإحصائيات", callback_data="stats")],
            [InlineKeyboardButton("🔔 الإشعارات", callback_data="notifications_menu")],
            [InlineKeyboardButton("🚀 نشر الآن", callback_data="force_post_now")],
            [InlineKeyboardButton("🔧 إعدادات البوت", callback_data="bot_settings")],
        ]
    elif role == "premium":
        buttons = [
            [InlineKeyboardButton("📂 الأقسام", callback_data="user_categories")],
            [InlineKeyboardButton("🔖 اقتباس عشوائي", callback_data="user_random")],
            [InlineKeyboardButton("📝 مساهمة (رفع محتوى)", callback_data="upload_content_menu")],
            [InlineKeyboardButton("🔍 بحث متقدم", callback_data="search_menu")],
            [InlineKeyboardButton("🏷️ تصنيفات", callback_data="tags_menu")],
            [InlineKeyboardButton("📊 تحليلاتي", callback_data="my_analytics")],
            [InlineKeyboardButton("⭐ مراجعاتي", callback_data="my_reviews")],
            [InlineKeyboardButton("🔔 إشعاراتي", callback_data="my_notifications")],
        ]
    else:
        buttons = [
            [InlineKeyboardButton("📂 الأقسام", callback_data="user_categories")],
            [InlineKeyboardButton("🔖 اقتباس عشوائي", callback_data="user_random")],
            [InlineKeyboardButton("📝 مساهمة (رفع محتوى)", callback_data="upload_content_menu")],
            [InlineKeyboardButton("🔍 بحث", callback_data="search_menu")],
            [InlineKeyboardButton("🏷️ تصنيفات", callback_data="tags_menu")],
            [InlineKeyboardButton("💎 الميزات المميزة", callback_data="premium_menu")],
            [InlineKeyboardButton("⚙️ الإعدادات", callback_data="user_settings")],
        ]
    
    title = "لوحة المطور 🔧" if role == "dev" else "لوحة المشرف 👨‍💼" if role == "admin" else "لوحة المميز 💎" if role == "premium" else "القائمة الرئيسية 🏠"
    return InlineKeyboardMarkup(buttons), title

def get_back_keyboard(role):
    """الحصول على زر الرجوع"""
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"back_{role}")]])

def get_categories_keyboard(prefix):
    """الحصول على كيبورد الأقسام مع أيقونات"""
    buttons = []
    for name, code in CATEGORIES:
        emoji = get_emoji_category_icon(code)
        buttons.append([InlineKeyboardButton(f"{emoji} {name}", callback_data=f"{prefix}_{code}")])
    buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_admin")])
    return InlineKeyboardMarkup(buttons)

def get_mobile_optimized_keyboard(buttons, items_per_row=2):
    """تحسين الكيبورد للأجهزة المحمولة"""
    mobile_buttons = []
    
    for i in range(0, len(buttons), items_per_row):
        row = []
        for j in range(items_per_row):
            if i + j < len(buttons):
                row.append(buttons[i + j])
        mobile_buttons.append(row)
    
    return InlineKeyboardMarkup(mobile_buttons)

def get_themed_keyboard(theme='default'):
    """الحصول على كيبورد بالألوان المفضلة"""
    themes = {
        'default': {'primary': '#0088cc', 'secondary': '#f0f0f0', 'text': '#000000'},
        'dark': {'primary': '#2c3e50', 'secondary': '#34495e', 'text': '#ecf0f1'},
        'ocean': {'primary': '#3498db', 'secondary': '#85c1e9', 'text': '#2c3e50'},
        'forest': {'primary': '#27ae60', 'secondary': '#82e0aa', 'text': '#1e8449'}
    }
    
    theme_colors = themes.get(theme, themes['default'])
    
    # يمكنك استخدام هذه الألوان في إنشاء الكيبوردهات
    return theme_colors

def get_emoji_category_icon(category):
    """الحصول على أيقونة مناسبة لكل قسم"""
    emoji_map = {
        'حب': '💕',
        'عيد ميلاد': '🎂',
        'اقتباسات عامة': '💭',
        'ابيات شعرية': '📜',
        'ديني': '🙏',
        'مضحك': '😂',
        'عام': '📋',
        'تقني': '💻',
        'رياضة': '⚽',
        'فن': '🎨',
        'سياسة': '🏛️',
        'اقتصاد': '💰'
    }
    return emoji_map.get(category, '📄')

def get_upload_keyboard(category):
    """الحصول على كيبورد رفع المحتوى مع أزرار رجوع مناسبة"""
    buttons = [
        [InlineKeyboardButton("📁 رفع ملف (.txt)", callback_data=f"upload_file_{category}")],
        [InlineKeyboardButton("✏️ كتابة نص يدوي", callback_data=f"upload_manual_{category}")],
        [InlineKeyboardButton("🏷️ إضافة تصنيفات", callback_data=f"add_tags_{category}")],
        [InlineKeyboardButton("🔙 رجوع للقسم", callback_data="back_from_content")],
    ]
    return InlineKeyboardMarkup(buttons)

def get_content_management_keyboard(category):
    """الحصول على كيبورد إدارة المحتوى مع زر رفع فوق زر الحذف"""
    session = get_session()
    try:
        content_count = session.query(Content).filter_by(category=category, is_active=True).count()
        cat_name = next((n for n, c in CATEGORIES if c == category), category)
        
        buttons = [
            [InlineKeyboardButton("📤 رفع محتوى جديد", callback_data=f"upload_{category}")],
            [InlineKeyboardButton("🏷️ إدارة التصنيفات", callback_data=f"manage_tags_{category}")],
            [InlineKeyboardButton(f"🗑️ حذف جميع المحتوى ({content_count})", callback_data=f"clear_cat_{category}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back_admin")]
        ]
        return cat_name, InlineKeyboardMarkup(buttons)
    finally:
        session.close()

def get_premium_keyboard():
    """الحصول على كيبورد الميزات المميزة"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💎 تفعيل الاشتراك", callback_data="premium_activate")],
        [InlineKeyboardButton("📊 عرض الميزات", callback_data="premium_features")],
        [InlineKeyboardButton("⏜️ تاريخ الاشتراك", callback_data="premium_history")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_user")]
    ])

def get_languages_keyboard():
    """الحصول على كيبورد اللغات"""
    session = get_session()
    try:
        languages = session.query(Language).filter_by(is_active=True).all()
        buttons = []
        for lang in languages:
            buttons.append([InlineKeyboardButton(f"{lang.flag} {lang.name}", callback_data=f"lang_{lang.code}")])
        return InlineKeyboardMarkup(buttons)
    finally:
        session.close()

def get_tags_keyboard(category):
    """الحصول على كيبورد التصنيفات"""
    session = get_session()
    try:
        tags = session.query(Tag).filter_by(category=category).all()
        buttons = []
        for tag in tags:
            buttons.append([InlineKeyboardButton(f"#{tag.name}", callback_data=f"tag_{tag.id}")])
        buttons.append([InlineKeyboardButton("➕ إضافة تصنيف", callback_data=f"add_tag_{category}")])
        buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_admin")])
        return InlineKeyboardMarkup(buttons)
    finally:
        session.close()

def get_security_keyboard():
    """الحصول على كيبورد الأمان"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔐 المصادقة الثنائية", callback_data="2fa_menu")],
        [InlineKeyboardButton("📋 سجل الأنشطة", callback_data="security_logs")],
        [InlineKeyboardButton("🔒 الإعدادات الأمنية", callback_data="security_settings")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_dev")]
    ])

def get_backup_keyboard():
    """الحصول على كيبورد النسخ الاحتياطي"""
    session = get_session()
    try:
        backups = session.query(Backup).filter_by(is_active=True).order_by(Backup.created_at.desc()).limit(5).all()
        buttons = []
        
        for backup in backups:
            date_str = backup.created_at.strftime("%Y-%m-%d %H:%M")
            size_mb = backup.size / (1024 * 1024)
            buttons.append([InlineKeyboardButton(f"📦 {date_str} ({size_mb:.1f}MB)", callback_data=f"restore_{backup.id}")])
        
        buttons.append([InlineKeyboardButton("💾 إنشاء نسخة احتياطية", callback_data="create_backup")])
        buttons.append([InlineKeyboardButton("🗑️ تنظيف النسخ", callback_data="cleanup_backups")])
        buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_dev")])
        
        return InlineKeyboardMarkup(buttons)
    finally:
        session.close()

# --- دوال المساعدة المحسنة ---

async def return_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, query=None):
    """إعادة المستخدم للقائمة الرئيسية"""
    user_id = update.effective_user.id
    role = get_role(user_id)
    
    kb, title = get_main_menu(role)
    # تصحيح HTML tag
    text = f"🔹 <b>{title}</b> 🔹"
    
    if query:
        try:
            await query.edit_message_text(text, reply_markup=kb, parse_mode='HTML')
        except:
            pass # إذا كانت الرسالة غير قابلة للتعديل
    elif update.message:
        await update.message.reply_text(text, reply_markup=kb, parse_mode='HTML')

async def handle_advanced_back_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة أزرار الرجوع المتقدمة"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    current_role = get_role(user_id)
    data = query.data

    if data == "back_from_content":
        # العودة لصفحة إدارة المحتوى
        # await show_content_stats(query, current_role)
        # لعدم وجود show_content_stats سنعود للقائمة الرئيسية
        await return_to_main_menu(update, context, query)
    
    elif data == "back_from_upload":
        # العودة لصفحة رفع المحتوى
        buttons = [[InlineKeyboardButton(name, callback_data=f"upload_{code}")] for name, code in CATEGORIES]
        buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"back_{current_role}")])
        await query.edit_message_text("اختر القسم لرفع ملف نصي (.txt):", reply_markup=InlineKeyboardMarkup(buttons))
    
    elif data == "back_from_user_content":
        # العودة لقائمة الأقسام للمستخدمين
        await query.edit_message_text("اختر القسم:", reply_markup=get_categories_keyboard("user_cat"))
    
    elif data == "back_from_random":
        # العودة للقائمة الرئيسية للمستخدمين
        kb, title = get_main_menu("user")
        text = f"🔹 <b>{title}</b> 🔹"
        await query.edit_message_text(text, reply_markup=kb, parse_mode='HTML')

async def send_user_content(query, cat_code):
    """إرسال محتوى عشوائي للمستخدم مع أزرار رجوع محسنة"""
    session = get_session()
    try:
        content = session.query(Content).filter_by(category=cat_code, is_active=True).order_by(func.random()).first()
        session.close()
        cat_name = next((n for n, c in CATEGORIES if c == cat_code), cat_code)
        cat_emoji = get_emoji_category_icon(cat_code)
        
        if content:
            text = await filter_text(content.text)
            
            # زيادة عدد المشاهدات
            content.view_count += 1
            session = get_session()
            try:
                session.commit()
            finally:
                session.close()
            
            if content.text.strip().startswith('>'):
                text = f"✨ <b>{cat_name}</b>\n\n<blockquote>{text}</blockquote>"
            else:
                text = f"✨ <b>{cat_name}</b>\n\n{text}"
        else:
            text = f"📭 لا يوجد محتوى في قسم {cat_name}."
        
        buttons = [
            [InlineKeyboardButton("🔄 غيرها", callback_data=f"user_cat_{cat_code}")],
            [InlineKeyboardButton("📂 جميع الأقسام", callback_data="back_from_user_content")],
            [InlineKeyboardButton("🔍 بحث", callback_data="search_menu")],
            [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="back_from_random")]
        ]
        try:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode='HTML')
        except:
            pass
    finally:
        session.close()

# --- معالج الأوامر ---

@perf_monitor
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة أمر /start"""
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
    context.user_data['current_role'] = role
    
    if role == "banned":
        await update.message.reply_text("⛔️ تم حظرك من استخدام البوت.")
        return

    session = get_session()
    try:
        user = session.query(User).filter_by(user_id=user_id).first()
        if not user:
            user = User(
                user_id=user_id, 
                username=username, 
                is_banned=False, 
                is_subscribed=False,
                preferred_language='ar',
                theme='default'
            )
            session.add(user)
            session.commit()
            db_log_action(user_id, "JOIN", f"New user: @{username}")
        elif user.username != username:
            user.username = username
            session.commit()
        
        user.last_activity = datetime.now()
        session.commit()
        
        # تسجيل عملية تسجيل الدخول
        await log_security_action(user_id, "login", update.message)
        
    except Exception as e:
        logger.error(f"DB Error in start: {e}")
    finally:
        session.close()

    kb, title = get_main_menu(role)
    text = f"أهلاً بك {update.effective_user.first_name}! 👋\n\n🔹 <b>{title}</b> 🔹"
    await update.message.reply_text(text, reply_markup=kb, parse_mode='HTML')

@perf_monitor
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الأزرار"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    current_role = get_role(user_id)
    data = query.data

    # التحقق من الاشتراك الإجباري
    required_channel = get_required_channel()
    if required_channel and current_role == "user":
        is_subscribed = await check_subscription(user_id, required_channel)
        if not is_subscribed:
            await query.edit_message_text(
                "🔒 يرجى الاشتراك في القناة أولاً:\n\n"
                f"👉 [انضم للقناة](https://t.me/{required_channel.lstrip('@')})",
                disable_web_page_preview=True
            )
            return

    # معالجة أزرار الرجوع بشكل محسّن
    if data.startswith("back_"):
        target_role = data.split("_")[1]
        
        # الحفاظ على الدور الحالي إذا كان المستخدم مطورًا أو مشرفًا
        if target_role == "admin" and current_role == "dev":
            target_role = "dev"
        elif target_role == "user" and current_role in ["admin", "dev"]:
            target_role = current_role
        
        # العودة للقائمة الرئيسية
        kb, title = get_main_menu(target_role)
        text = f"🔹 <b>{title}</b> 🔹"
        await query.edit_message_text(text, reply_markup=kb, parse_mode='HTML')
        return

    # معالجة أزرار الرجوع المتقدمة
    if data in ["back_from_content", "back_from_upload", "back_from_user_content", "back_from_random"]:
        await handle_advanced_back_button(update, context)
        return

    # معالقة القوائم الإضافية
    if data == "premium_menu":
        await query.edit_message_text("💎 <b>الميزات المميزة:</b>\n\nاشترك الآن لتفعيل الميزات الحصرية!", reply_markup=get_premium_keyboard(), parse_mode='HTML')
        return
    
    if data == "premium_activate":
        await query.edit_message_text(
            "💎 <b>تفعيل الاشتراك المميز:</b>\n\n"
            "🎯 الميزات المتاحة:\n"
            "• تحليلات متقدمة\n"
            "• تصفية نتائج البحث\n"
            "• تخزين مؤقت محسّن\n"
            "• دعم فني مخصص\n\n"
            "📱 قريباً: دعم الدفع المباشر!",
            reply_markup=get_premium_keyboard(),
            parse_mode='HTML'
        )
        return
    
    if data == "premium_features":
        await query.edit_message_text(
            "💎 <b>الميزات المميزة:</b>\n\n"
            "🎯 <b>التحليلات المتقدمة:</b>\n"
            "• تتبع نشاطك\n"
            "• تقارير شخصية\n"
            "• إحصائيات تفصيلية\n\n"
            "🔍 <b>البحث المتقدم:</b>\n"
            "• تصفية حسب التاريخ\n"
            "• البحث في التصنيفات\n"
            "• نتائج دقيقة\n\n"
            "⚡ <b>الأداء المحسّن:</b>\n"
            "• سرعة استجابة أعلى\n"
            "• تخزين مؤقت أفضل\n"
            "• أولوية المعالجة",
            reply_markup=get_premium_keyboard(),
            parse_mode='HTML'
        )
        return
    
    if data == "search_menu":
        await query.edit_message_text("🔍 <b>البحث في المحتوى:</b>\n\nأدخل كلمة مفتاحية للبحث:", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 رجوع", callback_data=f"back_{current_role}")]
        ]))
        context.user_data['search_mode'] = True
        return
    
    if data == "tags_menu":
        await query.edit_message_text("🏷️ <b>التصنيفات:</b>\n\nاختر قسمًا لعرض تصنيفاته:", reply_markup=get_categories_keyboard("tag_select"))
        return
    
    if data == "security_menu":
        await query.edit_message_text("🔒 <b>قائمة الأمان:</b>\n\nاختر إجراء:", reply_markup=get_security_keyboard(), parse_mode='HTML')
        return
    
    if data == "backup_menu":
        await query.edit_message_text("💾 <b>النسخ الاحتياطي:</b>\n\nاختر إجراء:", reply_markup=get_backup_keyboard(), parse_mode='HTML')
        return
    
    if data == "notifications_menu":
        await show_notifications_menu(query, current_role)
        return
    
    if data == "my_analytics":
        await show_user_analytics(query, user_id)
        return
    
    if data == "my_reviews":
        await show_user_reviews(query, user_id)
        return
    
    if data == "my_notifications":
        await show_user_notifications(query, user_id)
        return

    # --- منطق المشرفين والمطورين ---
    if current_role in ["admin", "dev"]:
        if data == "stats":
            stats_text = get_stats()
            await query.edit_message_text(stats_text, reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 تحديث", callback_data="stats")],
                [InlineKeyboardButton("🔙 رجوع", callback_data=f"back_{current_role}")]
            ]), parse_mode='HTML')
        
        elif data == "manage_channels":
            session = get_session()
            try:
                channels = session.query(Channel).all()
                if not channels:
                    await query.edit_message_text("لا توجد قنوات مضافة حالياً.", reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 رجوع", callback_data=f"back_{current_role}")]
                    ]))
                    return
                
                text = "📢 <b>القنوات المضافة:</b>\n\n"
                buttons = []
                for ch in channels:
                    status = "✅" if ch.is_active else "❌"
                    text += f"{status} {ch.title} ({ch.channel_id})\n"
                    buttons.append([InlineKeyboardButton(f"⚙️ {ch.title}", callback_data=f"edit_channel_{ch.id}")])
                
                buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"back_{current_role}")])
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode='HTML')
            finally:
                session.close()

        elif data == "upload_content_menu":
            await query.edit_message_text("اختر القسم لإضافة المحتوى:", reply_markup=get_categories_keyboard("upload"))

        elif data == "manage_content":
             await query.edit_message_text("إدارة المحتوى:", reply_markup=get_categories_keyboard("manage"))
        
        elif data == "add_channel_start":
            await query.edit_message_text("🔗 أرسل رابط القناة الآن (مع @):", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 رجوع", callback_data=f"back_{current_role}")]
            ]))
            # هنا يفترض بدء محادثة (ConversationHandler) ولكننا سنكتفي برسالة توضيحية
        
        elif data == "bot_settings":
            await query.edit_message_text("⚙️ <b>إعدادات البوت</b>:\n\nقريباً...", reply_markup=InlineKeyboardMarkup([
                 [InlineKeyboardButton("🔙 رجوع", callback_data=f"back_{current_role}")]
            ]), parse_mode='HTML')

    # --- منطق المستخدمين ---
    if current_role == "user":
        if data == "user_random":
            cat_code = random.choice([c[1] for c in CATEGORIES])
            await send_user_content(query, cat_code)
        elif data.startswith("user_cat_"):
            cat_code = data.split("_")[-1]
            await send_user_content(query, cat_code)
        elif data == "user_categories":
            await query.edit_message_text("اختر القسم:", reply_markup=get_categories_keyboard("user_cat"))
        elif data == "user_settings":
            await query.edit_message_text("⚙️ <b>الإعدادات</b>:\n\nقريباً...", reply_markup=InlineKeyboardMarkup([
                 [InlineKeyboardButton("🔙 رجوع", callback_data=f"back_{current_role}")]
            ]), parse_mode='HTML')
        return

async def show_notifications_menu(query, role):
    """عرض قائمة الإشعارات"""
    session = get_session()
    try:
        notifications = session.query(Notification).filter_by(is_sent=False).order_by(Notification.scheduled_time).limit(10).all()
        
        if not notifications:
            await query.edit_message_text("🔔 لا توجد إشعارات مجدولة حالياً.", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ إضافة إشعار", callback_data="add_notification")],
                [InlineKeyboardButton("🔙 رجوع", callback_data=f"back_{role}")]
            ]))
            return
        
        text = "🔔 <b>الإشعارات المجدولة:</b>\n\n"
        for i, notification in enumerate(notifications[:5], 1):
            scheduled_time = notification.scheduled_time.strftime("%Y-%m-%d %H:%M")
            text += f"{i}. {notification.message[:50]}... ({scheduled_time})\n"
        
        buttons = [
            [InlineKeyboardButton("➕ إضافة إشعار", callback_data="add_notification")],
            [InlineKeyboardButton("🗑️ مسح الإشعارات", callback_data="clear_notifications")],
            [InlineKeyboardButton("🔙 رجوع", callback_data=f"back_{role}")]
        ]
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode='HTML')
    finally:
        session.close()

async def show_user_analytics(query, user_id):
    """عرض الإحصائيات الشخصية للمستخدم"""
    session = get_session()
    try:
        # إحصائيات المستخدم الشخصية
        user_content = session.query(Content).filter_by(added_by=user_id).count()
        user_reviews = session.query(Review).filter_by(user_id=user_id).count()
        
        # إحصائيات تفاعل المستخدم
        user_views = session.query(Content).filter_by(added_by=user_id).with_entities(func.sum(Content.view_count)).scalar() or 0
        
        # أفضل محتوى أضافه
        best_content = session.query(Content).filter_by(added_by=user_id).order_by(Content.view_count.desc()).first()
        
        text = f"📊 <b>تحليلاتي الشخصية:</b>\n\n"
        text += f"📝 محتوى أضفته: {user_content} نص\n"
        text += f"⭐ مراجعاتي: {user_reviews}\n"
        text += f"👁️ إجمالي المشاهدات: {user_views}\n\n"
        
        if best_content:
            text += f"🏆 أفضل محتوى:\n"
            text += f"النص: {best_content.text[:50]}...\n"
            text += f"المشاهدات: {best_content.view_count}\n"
            text += f"التقييم: {best_content.rating}/5 ({best_content.rating_count} تقييم)\n"
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 رجوع", callback_data="back_premium")]
        ]), parse_mode='HTML')
    finally:
        session.close()

async def show_user_reviews(query, user_id):
    """عرض المراجعات التي كتبها المستخدم"""
    session = get_session()
    try:
        reviews = session.query(Review).filter_by(user_id=user_id).order_by(Review.created_at.desc()).limit(5).all()
        
        if not reviews:
            await query.edit_message_text("⭐ لم تقم بكتابة أي مراجعات بعد.", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 رجوع", callback_data="back_premium")]
            ]))
            return
        
        text = f"⭐ <b>مراجعاتي:</b>\n\n"
        for review in reviews:
            content = session.query(Content).filter_by(id=review.content_id).first()
            if content:
                text += f"⭐ {review.rating}/5\n"
                text += f"النص: {content.text[:50]}...\n"
                text += f"المراجعة: {review.comment}\n"
                text += f"التاريخ: {review.created_at.strftime('%Y-%m-%d')}\n\n"
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 رجوع", callback_data="back_premium")]
        ]), parse_mode='HTML')
    finally:
        session.close()

async def show_user_notifications(query, user_id):
    """عرض الإشعارات الشخصية للمستخدم"""
    session = get_session()
    try:
        notifications = session.query(Notification).filter_by(user_id=user_id, is_sent=False).order_by(Notification.scheduled_time).limit(5).all()
        
        if not notifications:
            await query.edit_message_text("🔔 لا توجد إشعارات شخصية مجدولة.", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 رجوع", callback_data="back_premium")]
            ]))
            return
        
        text = f"🔔 <b>إشعاراتي:</b>\n\n"
        for i, notification in enumerate(notifications, 1):
            scheduled_time = notification.scheduled_time.strftime("%Y-%m-%d %H:%M")
            text += f"{i}. {notification.message[:50]}... ({scheduled_time})\n"
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 رجوع", callback_data="back_premium")]
        ]), parse_mode='HTML')
    finally:
        session.close()

async def log_security_action(user_id, action, update=None):
    """تسجل الأنشطة الأمنية"""
    session = get_session()
    try:
        ip_address = None
        user_agent = None
        
        if update and update.message:
            # يمكنك استخراج IP و User Agent من الرسالة
            pass
        
        security_log = SecurityLog(
            user_id=user_id,
            action=action,
            ip_address=ip_address,
            user_agent=user_agent
        )
        session.add(security_log)
        session.commit()
    except Exception as e:
        logger.error(f"Security log error: {e}")
    finally:
        session.close()

# --- دوال النظام ---

async def process_task_queue():
    """معالجة قائمة المهام"""
    while True:
        await task_queue.process_tasks_logic()
        await asyncio.sleep(1)

async def periodic_backup():
    """النسخ الاحتياطي الدوري"""
    while True:
        await backup_database()
        # انتقال 24 ساعة
        await asyncio.sleep(24 * 60 * 60)

async def periodic_stats():
    """إحصائيات دورية"""
    while True:
        await schedule_content_posting()
        # انتقال ساعة
        await asyncio.sleep(60 * 60)

# --- التشغيل ---
def main():
    """البدء في التشغيل"""
    global APPLICATION
    APPLICATION = Application.builder().token(TOKEN).build()

    # تسجيل الهاندلرز
    APPLICATION.add_handler(CommandHandler("start", start))
    APPLICATION.add_handler(CallbackQueryHandler(button_handler))
    
    # استخدام asyncio.create_task لتشغيل المهام في الخلفية بدلاً من add_task
    async def post_init(app: Application):
        logger.info("Starting background tasks...")
        asyncio.create_task(process_task_queue())
        asyncio.create_task(periodic_backup())
        asyncio.create_task(periodic_stats())

    APPLICATION.post_init = post_init
    
    # جدولة الإشعارات
    if APPLICATION.job_queue:
        APPLICATION.job_queue.run_repeating(send_scheduled_notifications, interval=300)  # كل 5 دقائق
        APPLICATION.job_queue.run_repeating(backup_database, interval=86400)  # كل 24 ساعة

    logger.info("Bot started polling...")
    APPLICATION.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
