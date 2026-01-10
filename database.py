# ==========================================
# ملف قاعدة البيانات (SQLAlchemy)
# ==========================================

from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from config import DATABASE_URL
from datetime import datetime

# إنشاء المحرك (Engine)
engine = create_engine(DATABASE_URL, echo=False)

# إنشاء القاعدة الأساسية (Base)
Base = declarative_base()

# إنشاء صانع الجلسات (Session Maker)
Session = sessionmaker(bind=engine)

# ==========================================
# تعريف الجداول (Tables)
# ==========================================

class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, unique=True, nullable=False)
    username = Column(String(50), nullable=True)
    is_admin = Column(Boolean, default=False)
    join_date = Column(DateTime, default=datetime.utcnow)

class Channel(Base):
    __tablename__ = 'channels'
    
    id = Column(Integer, primary_key=True)
    channel_id = Column(Integer, unique=True, nullable=False) # المعرف الحقيقي للقناة (-100...)
    title = Column(String(100), nullable=False)
    category = Column(String(50), default="اقتباسات عامة")
    msg_format = Column(String(20), default="normal") # normal or blockquote
    time_type = Column(String(20), default="default") # default, fixed, interval
    time_value = Column(String(100), nullable=True) # ساعات أو دقائق
    last_post_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    added_by = Column(Integer, nullable=True)

class Content(Base):
    __tablename__ = 'content'
    
    id = Column(Integer, primary_key=True)
    category = Column(String(50), nullable=False)
    text_content = Column(Text, nullable=False)
    used_count = Column(Integer, default=0)

class BotSettings(Base):
    __tablename__ = 'bot_settings'
    
    id = Column(Integer, primary_key=True)
    key = Column(String(50), unique=True)
    value = Column(String(50))

# ==========================================
# إنشاء الجداول في قاعدة البيانات
# ==========================================

def init_db():
    Base.metadata.create_all(engine)
    # إضافة الإعدادات الافتراضية إذا لم تكن موجودة
    session = Session()
    try:
        if not session.query(BotSettings).filter_by(key='posting_status').first():
            session.add(BotSettings(key='posting_status', value='on'))
            session.commit()
            print("Database initialized.")
    finally:
        session.close()

# ==========================================
# دوال مساعدة (Helpers)
# ==========================================

def is_admin(user_id):
    session = Session()
    try:
        user = session.query(User).filter_by(user_id=user_id).first()
        if user:
            return user.is_admin or user.user_id == config.DEVELOPER_ID
        return False
    finally:
        session.close()

def add_channel(ch_id, title, added_by, cat, fmt, time_type, time_val):
    session = Session()
    try:
        # التحقق من وجود القناة
        existing = session.query(Channel).filter_by(channel_id=ch_id).first()
        if existing:
            # تحديث القناة إذا وجدت
            existing.title = title
            existing.category = cat
            existing.msg_format = fmt
            existing.time_type = time_type
            existing.time_value = time_val
            existing.is_active = True
            session.commit()
        else:
            new_ch = Channel(
                channel_id=ch_id, 
                title=title, 
                added_by=added_by, 
                category=cat, 
                msg_format=fmt, 
                time_type=time_type, 
                time_value=time_val
            )
            session.add(new_ch)
            session.commit()
    finally:
        session.close()

def remove_channel_db(chat_id):
    session = Session()
    try:
        ch = session.query(Channel).filter_by(channel_id=chat_id).first()
        if ch:
            session.delete(ch)
            session.commit()
    finally:
        session.close()

def add_file_content(category, lines):
    session = Session()
    count = 0
    try:
        for line in lines:
            content = Content(category=category, text_content=line)
            session.add(content)
            count += 1
        session.commit()
    finally:
        session.close()
    return count

def get_next_content(category):
    """استرجاع محتوى عشوائي بالكامل"""
    session = Session()
    try:
        # التعديل هنا: استخدام func.random() بدلاً من order_by
        content = session.query(Content).filter_by(category=category).order_by(func.random()).first()
        if content:
            content.used_count += 1
            session.commit()
            return content.text_content
        return None
    finally:
        session.close()

def get_stats():
    session = Session()
    try:
        users_count = session.query(User).count()
        channels_count = session.query(Channel).filter_by(is_active=True).count()
        posts_count = session.query(Content).count()
        txt = f"📊 <b>إحصائيات البوت:</b>\n\n👥 المستخدمين: {users_count}\n📢 القنوات النشطة: {channels_count}\n📝 الاقتباسات: {posts_count}"
        return txt
    finally:
        session.close()