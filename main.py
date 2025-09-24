#8362535744:AAHL5qlEzxHuRDootKsgt6yGCOBlD-BA5n8 токен бота

import telebot
from telebot import types
import sqlite3
import re
import random
import time
from datetime import datetime
import os

# ========== Настройки ==========
TOKEN = "8362535744:AAHL5qlEzxHuRDootKsgt6yGCOBlD-BA5n8"
ADMIN_ID = 7136544022
DB_FILE = "insight.db"
MODERATION_DELAY = 0      # секунды (0 для теста)
COOLDOWN_MINUTES = 1      # кулдаун между запросами
MAX_INSIGHTS_PER_HOUR = 5  # сколько инсайтов можно отправить в час

bot = telebot.TeleBot(TOKEN)

# ========== DB helpers ==========
def get_conn():
    return sqlite3.connect(DB_FILE)



def init_db():
    conn = sqlite3.connect("insight.db")
    cur = conn.cursor()

    # --- Users ---
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        reg_date TEXT,
        has_posted INTEGER DEFAULT 0,
        last_request REAL DEFAULT 0,
        messages_sent INTEGER DEFAULT 0,
        last_post_time REAL DEFAULT 0,
        posts_in_hour INTEGER DEFAULT 0
    )
    """)

    # --- Insights ---
    cur.execute("""
    CREATE TABLE IF NOT EXISTS insights (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        author_id INTEGER,
        text TEXT,
        is_flagged INTEGER DEFAULT 0,
        created_at REAL
    )
    """)

    # --- Delivered ---
    cur.execute("""
    CREATE TABLE IF NOT EXISTS delivered (
        user_id INTEGER,
        insight_id INTEGER,
        PRIMARY KEY (user_id, insight_id)
    )
    """)

    # --- Reports ---
    cur.execute("""
    CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        insight_id INTEGER,
        user_id INTEGER,
        reason TEXT,
        created_at REAL
    )
    """)

    conn.commit()
    conn.close()

init_db()

# ========== Валидация текста ==========
BAD_WORD_ROOTS = ["бляд", "ху", "пизд", "еба", "бля", "сука", "муд", "гандон", "твар"]
CONTACT_RE = re.compile(r"(\+?\d[\d\-\s]{6,}\d|@[\w_]{3,}|https?://\S+|www\.\S+|\S+@\S+\.\S+)", re.IGNORECASE)

def normalize_for_profanity(s: str) -> str:
    s = s.lower()
    subs = {'6':'б','3':'е','4':'ч','1':'л','0':'о','@':'а','$':'с','5':'с'}
    for k,v in subs.items():
        s = s.replace(k, v)
    s = re.sub(r'[^а-яa-z]', '', s)
    s = re.sub(r'(.)\1{2,}', r'\1', s)
    return s

def validate_insight_text(text: str):
    if not text or not text.strip():
        return "Пожалуйста, напиши текст инсайта."
    if len(text) > 800 or len(text) < 3:
        return "Текст слишком длинный (макс 800) либо слишком кроткий (мин 3). Поправь, пожалуйста."
    if CONTACT_RE.search(text):
        return "Похоже, в тексте есть контакты или ссылки. Удали личные данные и попробуй снова."
    norm = normalize_for_profanity(text)
    for root in BAD_WORD_ROOTS:
        if root in norm:
            return "🚫 В сообщении найдены запрещённые слова."
    return None

# ========== DB операции ==========
def ensure_user(uid, username=""):
    conn = sqlite3.connect("insight.db")
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO users (user_id, username, reg_date) VALUES (?, ?, ?)",
        (uid, username or "", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )
    if cur.rowcount > 0:  # новый пользователь добавлен
        log_new_user(uid, username)
    conn.commit()
    conn.close()

def get_username(uid):
    conn = sqlite3.connect("insight.db")
    cur = conn.cursor()
    cur.execute("SELECT username FROM users WHERE user_id=?", (uid,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row and row[0] else "(нет имени)"

def log_new_user(user_id, username):
    text = f"👤 Новый пользователь:\nID: {user_id}\nUsername: @{username or 'не указан'}"
    bot.send_message(LOG_CHAT_ID, text)

def save_insight(uid, text):
    conn = sqlite3.connect("insight.db")
    cur = conn.cursor()
    cur.execute("INSERT INTO insights (author_id, text, created_at) VALUES (?, ?, ?)",
                (uid, text, time.time()))
    iid = cur.lastrowid
    conn.commit()
    conn.close()

    username = get_username(uid)
    log_event("new_insight", insight_id=iid, username=username, text=text)
    return iid

def mark_user_posted(user_id):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE users SET has_posted=1, messages_sent = messages_sent + 1 WHERE user_id=?", (user_id,))
    conn.commit(); conn.close()

def get_user_info(user_id):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT username, reg_date, has_posted, messages_sent, last_request FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone(); conn.close()
    return row

def get_random_insight_for_requester(requester_id, min_age_seconds=MODERATION_DELAY):
    cutoff = time.time() - max(0, min_age_seconds)
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""
        SELECT id, text, author_id FROM insights
        WHERE is_flagged=0 AND author_id != ? AND created_at < ?
        AND id NOT IN (SELECT insight_id FROM delivered WHERE user_id=?)
        ORDER BY RANDOM() LIMIT 1
    """, (requester_id, cutoff, requester_id))
    row = cur.fetchone(); conn.close()
    return row

def mark_delivered(user_id, insight_id):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO delivered (user_id, insight_id) VALUES (?, ?)", (user_id, insight_id))
    conn.commit(); conn.close()

def set_user_cooldown(user_id, minutes=COOLDOWN_MINUTES):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE users SET last_request=? WHERE user_id=?", (time.time() + minutes*60, user_id))
    conn.commit(); conn.close()

def check_cooldown(user_id):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT last_request FROM users WHERE user_id=?", (user_id,))
    r = cur.fetchone(); conn.close()
    if r and r[0] and r[0] > time.time():
        remaining = int((r[0] - time.time()) // 60) + 1
        return remaining
    return 0

def flag_insight(insight_id):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE insights SET is_flagged=1 WHERE id=?", (insight_id,))
    conn.commit(); conn.close()

def get_insight_by_id(iid):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT id, author_id, text, is_flagged, created_at FROM insights WHERE id=?", (iid,))
    row = cur.fetchone(); conn.close()
    return row


def save_report(insight_id, user_id, reason, is_general=False):
    """
    Сохраняет жалобу в БД и шлёт лог в LOG_CHAT_ID.
    :param insight_id: ID инсайта (или None для общей жалобы)
    :param user_id: ID пользователя
    :param reason: текст жалобы
    :param is_general: True если это общая жалоба, False если на инсайт
    """
    conn = sqlite3.connect("insight.db")
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO reports (insight_id, user_id, reason, created_at)
        VALUES (?, ?, ?, ?)
    """, (insight_id, user_id, reason, time.time()))
    conn.commit()
    conn.close()

    # лог в чат
    if is_general:
        text = f"⚠️ Общая жалоба\nОт пользователя {user_id}\nТекст: {reason}"
    else:
        text = f"🚨 Жалоба на инсайт #{insight_id}\nОт пользователя {user_id}\nПричина: {reason}"

    try:
        bot.send_message(LOG_CHAT_ID, text)
    except Exception as e:
        print("[LOG ERROR]", e)

# ========== Temp preview storage ==========
# temp_previews[temp_id] = (user_id, text)
temp_previews = {}
def make_temp_id():
    return int(time.time() * 1000) ^ random.randint(1, 999999)

# ========== Очистка устаревших сообщений ==========
def cleanup_old_data():
    """
    Удаляет инсайты и жалобы старше 7 дней.
    Запускать ежедневно в 00:00 по МСК через threading или cron.
    """
    conn = sqlite3.connect("insight.db")
    cur = conn.cursor()
    seven_days_ago = time.time() - 7*24*60*60

    # Удаляем инсайты старше 7 дней
    cur.execute("DELETE FROM insights WHERE created_at < ?", (seven_days_ago,))

    # Удаляем жалобы старше 7 дней
    cur.execute("DELETE FROM reports WHERE created_at < ?", (seven_days_ago,))

    # Очищаем таблицу delivered, чтобы не ссылалась на удалённые инсайты
    cur.execute("""
        DELETE FROM delivered 
        WHERE insight_id NOT IN (SELECT id FROM insights)
    """)

    conn.commit()
    conn.close()
    print("[CLEANUP] Старые инсайты и жалобы удалены.")

def schedule_cleanup():
    import time
    import threading
    from datetime import timedelta

    def run_daily():
        while True:
            now = datetime.now()
            # Расчёт до следующей 00:00
            next_run = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
            wait_seconds = (next_run - now).total_seconds()
            time.sleep(wait_seconds)
            cleanup_old_data()

    threading.Thread(target=run_daily, daemon=True).start()

# Вставить после инициализации бота
schedule_cleanup()


LOG_CHAT_ID = -1003026651234  # Можно заменить на айди группы/канала для логов

def log_event(event_type, **kwargs):
    """
    Логирование событий в Telegram и консоль.
    event_type: "new_user", "new_insight", "report_insight", "general_report"
    kwargs: дополнительные данные
    """
    text = ""
    if event_type == "new_user":
        uid = kwargs.get("user_id")
        username = kwargs.get("username") or "(нет имени)"
        text = f"🆕 Новый пользователь\nID: {uid}\nUsername: {username}"

    elif event_type == "new_insight":
        iid = kwargs.get("insight_id")
        username = kwargs.get("username") or "(нет имени)"
        text = kwargs.get("text")
        text = f"✍ Новый инсайт\nID инсайта: {iid}\nАвтор: @{username}\nТекст:{text}"

    elif event_type == "report_insight":
        iid = kwargs.get("insight_id")
        reporter = kwargs.get("reporter_id")
        reason = kwargs.get("reason")
        text = (f"🚨 Жалоба на инсайт\nID инсайта: {iid}\n"
                f"От пользователя: {reporter}\nПричина: {reason}")

    elif event_type == "general_report":
        reporter = kwargs.get("reporter_id")
        reason = kwargs.get("reason")
        text = f"⚠️ Общая жалоба\nОт пользователя: {reporter}\nТекст: {reason}"

    if text:
        print("[LOG]", text)  # В консоль
        try:
            bot.send_message(LOG_CHAT_ID, text)  # В чат логов
        except Exception as e:
            print("[LOG ERROR]", e)

# ========== UI клавиатуры ==========
def main_menu_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("🖊 Написать инсайт", "🎲 Получить инсайт")
    kb.add("ℹ️ О боте", "⚠️ Пожаловаться")
    return kb

def insight_inline_kb(iid):
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("🔁 Ещё инсайт", callback_data="more"),
        types.InlineKeyboardButton("📤 Поделиться", callback_data=f"share:{iid}"),
        types.InlineKeyboardButton("🚩 Пожаловаться", callback_data=f"report:{iid}")
    )
    return kb

def can_post_n_per_hour(uid):
    """Проверяет, сколько инсайтов отправлено за последние 60 минут."""
    conn = sqlite3.connect("insight.db")
    cur = conn.cursor()
    cutoff = time.time() - 3600  # 1 час назад
    cur.execute("SELECT COUNT(*) FROM insights WHERE author_id=? AND created_at>=?", (uid, cutoff))
    count = cur.fetchone()[0]
    conn.close()
    if count >= MAX_INSIGHTS_PER_HOUR:
        return False, MAX_INSIGHTS_PER_HOUR - count
    return True, MAX_INSIGHTS_PER_HOUR - count

def can_post_insight(uid):
    conn = sqlite3.connect("insight.db")
    cur = conn.cursor()
    cur.execute("SELECT last_post_time, posts_in_hour FROM users WHERE user_id=?", (uid,))
    row = cur.fetchone()

    now = time.time()
    if not row:
        conn.close()
        return True  # если юзера нет в БД — считаем, что можно постить

    last_post_time, posts_in_hour = row

    # если прошло больше часа — сбрасываем счётчик
    if now - last_post_time > 3600:
        cur.execute("UPDATE users SET posts_in_hour=0, last_post_time=? WHERE user_id=?",
                    (now, uid))
        conn.commit()
        conn.close()
        return True

    # если превысил лимит
    if posts_in_hour >= MAX_INSIGHTS_PER_HOUR:
        conn.close()
        return False

    conn.close()
    return True


def increment_post_counter(uid):
    conn = sqlite3.connect("insight.db")
    cur = conn.cursor()
    cur.execute("SELECT last_post_time, posts_in_hour FROM users WHERE user_id=?", (uid,))
    row = cur.fetchone()

    now = time.time()
    if not row:
        cur.execute("INSERT OR IGNORE INTO users (user_id, last_post_time, posts_in_hour) VALUES (?, ?, ?)",
                    (uid, now, 1))
    else:
        last_post_time, posts_in_hour = row
        if now - last_post_time > 3600:
            cur.execute("UPDATE users SET posts_in_hour=1, last_post_time=? WHERE user_id=?",
                        (now, uid))
        else:
            cur.execute("UPDATE users SET posts_in_hour=posts_in_hour+1, last_post_time=? WHERE user_id=?",
                        (now, uid))

    conn.commit()
    conn.close()

def preview_kb(temp_id):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("✅ Отправить анонимно", callback_data=f"preview_send:{temp_id}"))
    kb.add(types.InlineKeyboardButton("✏️ Редактировать", callback_data=f"preview_edit:{temp_id}"),
           types.InlineKeyboardButton("❌ Отмена", callback_data=f"preview_cancel:{temp_id}"))
    return kb

START_TEXT = (
    "Привет! Я — Анонимный инсайт — бот, который пересылает анонимные мысли других людей.\n"
    "Отправляй короткую мысль — и получай чужую в ответ.\n\n"
    "Важно: не пишите личных данных (телефоны, ФИО, пароли). Отправляя — вы соглашаетесь на анонимную рассылку.\n"
    "Главное меню: 🖊 Написать / 🎲 Получить / ℹ️ О боте"
)

ABOUT_TEXT = (
    "Как работает:\n\n"
    "Ты пишешь анонимный инсайт.\n"
    "Другому пользователю случайно приходит твоя мысль.\n\n"
    "Ты можешь получить чужую мысль — но только после того, как сам написал.\n"
    "Правила: максимум 800 символов, минимум 3; запрещено публиковать контакты, ссылки и экстремизм.\n"
    "Нажми 🖊 чтобы начать."
)

# ========== HANDLERS ==========

@bot.message_handler(commands=["admin"])
def cmd_admin(m):
    if m.from_user.id != ADMIN_ID:
        bot.send_message(m.chat.id, "У тебя нет доступа к панели администратора.")
        return

    # прямо тут формируем клавиатуру
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("Список пользователей🤵", callback_data="admin_users"),
        types.InlineKeyboardButton("Список инсайтов🎫", callback_data="admin_insights"),
        types.InlineKeyboardButton("Список жалоб🔴", callback_data="admin_reports")
    )
    bot.send_message(m.chat.id, "👑 Панель администратора", reply_markup=kb)

@bot.message_handler(commands=["start"])
def cmd_start(m):
    ensure_user(m.from_user.id, m.from_user.username or "")
    ensure_user(m.from_user.id, getattr(m.from_user, "username", "") or "")
    bot.send_message(m.chat.id, START_TEXT, reply_markup=main_menu_kb())

@bot.message_handler(func=lambda m: m.text == "ℹ️ О боте")
def cmd_about(m):
    ensure_user(m.from_user.id, m.from_user.username or "")
    bot.send_message(m.chat.id, ABOUT_TEXT, reply_markup=main_menu_kb())

# --- Написать инсайт ---
@bot.message_handler(func=lambda m: m.text == "🖊 Написать инсайт")
def cmd_write(m):
    ensure_user(m.from_user.id, m.from_user.username or "")
    ensure_user(m.from_user.id, getattr(m.from_user, "username", "") or "")
    sent = bot.send_message(m.chat.id,
                            "Напиши свой инсайт в одном сообщении (макс 800 символов, мин 3). Не указывай личные данные, номера, e-mail и ссылки.\nКогда отправишь — появится кнопка «Отправить анонимно».",
                            reply_markup=types.ReplyKeyboardRemove())
    bot.register_next_step_handler(sent, step_preview)

def step_preview(message):
    err = validate_insight_text(message.text)
    if err:
        bot.send_message(message.chat.id, err, reply_markup=main_menu_kb())
        return
    temp_id = make_temp_id()
    temp_previews[temp_id] = (message.from_user.id, message.text)
    bot.send_message(message.chat.id, f"Ты отправляешь анонимно:\n«{message.text}»", reply_markup=preview_kb(temp_id))

# --- Получить инсайт ---
@bot.message_handler(func=lambda m: m.text == "🎲 Получить инсайт")
def cmd_get(m):
    ensure_user(m.from_user.id, m.from_user.username or "")
    ensure_user(m.from_user.id, getattr(m.from_user, "username", "") or "")
    info = get_user_info(m.from_user.id)
    if not info or int(info[2]) == 0:  # has_posted at index 2
        bot.send_message(m.chat.id, "Чтобы получить инсайт, сначала отправь свой. Нажми 🖊 Написать инсайт.", reply_markup=main_menu_kb())
        return

    cd = check_cooldown(m.from_user.id)
    if cd > 0:
        bot.send_message(m.chat.id, f"Пожалуйста, подожди: ещё рано запрашивать новый инсайт (кулдаун {cd} мин).")
        return

    row = get_random_insight_for_requester(m.from_user.id)
    if not row:
        bot.send_message(m.chat.id, "Сейчас нет доступных инсайтов — попробуй позже.", reply_markup=main_menu_kb())
        return

    iid, text, author_id = row
    mark_delivered(m.from_user.id, iid)
    set_user_cooldown(m.from_user.id, minutes=COOLDOWN_MINUTES)
    bot.send_message(m.chat.id, f"Вот инсайт:\n«{text}»", reply_markup=insight_inline_kb(iid))

# --- Жалоба из меню (общая) ---
waiting_general_report = set()

@bot.message_handler(func=lambda m: m.text == "⚠️ Пожаловаться")
def cmd_general_report(m):
    ensure_user(m.from_user.id, m.from_user.username or "")
    ensure_user(m.from_user.id, getattr(m.from_user, "username", "") or "")
    waiting_general_report.add(m.from_user.id)
    sent = bot.send_message(m.chat.id, "Напиши текст жалобы или пришли фото.", reply_markup=types.ReplyKeyboardRemove())

    def after_general(msg):
        reason = msg.text or "(без текста)"
        save_report(None, msg.from_user.id, reason, is_general=True)

        # ✅ пользователю
        bot.send_message(msg.chat.id, "✅ Жалоба отправлена модератору. Спасибо!", reply_markup=main_menu_kb())

        # 📢 админу
        bot.send_message(
            ADMIN_ID,
            f"⚠️ Общая жалоба от @{msg.from_user.username or msg.from_user.id}:\n{reason}"
        )

    bot.register_next_step_handler(sent, after_general)

def handle_general_report(message):
    uid = message.from_user.id
    waiting_general_report.discard(uid)
    if message.content_type == "text":
        reason = message.text
        save_report(None, uid, reason)
        bot.send_message(message.chat.id, "Спасибо! Твоя жалоба отправлена админу.", reply_markup=main_menu_kb())
        bot.send_message(ADMIN_ID, f"⚠️ Общая жалоба от {uid}:\n{reason}")
    elif message.content_type == "photo":
        caption = message.caption or ""
        save_report(None, uid, f"[photo] {caption}")
        bot.send_message(message.chat.id, "Спасибо! Твоя жалоба отправлена админу.", reply_markup=main_menu_kb())
        bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=f"⚠️ Общая жалоба (фото) от {uid}:\n{caption}")
    else:
        save_report(None, uid, "(без текста)")
        bot.send_message(message.chat.id, "Спасибо! Твоя жалоба отправлена админу.", reply_markup=main_menu_kb())
        bot.send_message(ADMIN_ID, f"⚠️ Общая жалоба от {uid}: (без текста)")

# ========== Универсальный обработчик inline callback'ов ==========
@bot.callback_query_handler(func=lambda call: True)
def callback_router(call):
    data = call.data or ""
    uid = call.from_user.id
    print(f"[callback] from {uid}: {data}")  # лог для отладки

    # parse key:arg where arg optional
    parts = data.split(":", 1)
    key = parts[0]
    arg = parts[1] if len(parts) > 1 else None

    # --- админские кнопки ---
    if uid == ADMIN_ID:
        # Панель админа и кнопки
        if key == "admin_insights_back":
            # прямо тут формируем клавиатуру
            kb = types.InlineKeyboardMarkup()
            kb.add(
                types.InlineKeyboardButton("Список пользователей🤵", callback_data="admin_users"),
                types.InlineKeyboardButton("Список инсайтов🎫", callback_data="admin_insights"),
                types.InlineKeyboardButton("Список жалоб🔴", callback_data="admin_reports")
            )
            bot.edit_message_text(
                "👑 Панель администратора",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=kb
            )
            return

        if key == "admin_users":
            show_admin_users(call)
            return

        if key == "admin_insights":
            show_admin_insights(call)
            return

        if key == "admin_insight_detail":
            try:
                iid = int(arg)
                show_insight_detail(call, iid)
            except:
                bot.answer_callback_query(call.id, "Ошибка идентификатора.", show_alert=True)
            return

        if key == "admin_reports":
            show_admin_reports(call)
            return

    # parse key:arg where arg optional
    parts = data.split(":", 1)
    key = parts[0]
    arg = parts[1] if len(parts) > 1 else None

    # --- preview send/edit/cancel ---
    if key == "preview_send":
        allowed, remaining = can_post_n_per_hour(uid)
        if not allowed:
            bot.answer_callback_query(call.id, f"⏱ Лимит исчерпан. Можно отправить ещё через час.", show_alert=True)
            return

        bot.answer_callback_query(call.id, "Отправляю...")
        temp_id = int(arg)
        if temp_id not in temp_previews:
            bot.answer_callback_query(call.id, "Временные данные не найдены или истекли.", show_alert=True)
            return
        owner_id, text = temp_previews[temp_id]
        if owner_id != uid:
            bot.answer_callback_query(call.id, "Эта кнопка не для вас.", show_alert=True)
            return

        iid = save_insight(owner_id, text)
        mark_user_posted(owner_id)  # можно оставить для флага has_posted
        del temp_previews[temp_id]
        bot.send_message(owner_id,
                         f"Спасибо — твой инсайт принят. Сейчас ты можешь отправить ещё {remaining - 1} инсайтов в час.",
                         reply_markup=main_menu_kb())

    if key == "preview_edit":
        bot.answer_callback_query(call.id, "Редактирование...")
        try:
            temp_id = int(arg)
        except:
            bot.answer_callback_query(call.id, "Ошибка превью.", show_alert=True)
            return
        if temp_id not in temp_previews:
            bot.answer_callback_query(call.id, "Временные данные не найдены.", show_alert=True)
            return
        owner_id, _ = temp_previews[temp_id]
        if owner_id != uid:
            bot.answer_callback_query(call.id, "Эта кнопка не для вас.", show_alert=True)
            return
        sent = bot.send_message(uid, "Отправь отредактированный текст (макс 800 символов).", reply_markup=types.ReplyKeyboardRemove())
        bot.register_next_step_handler(sent, lambda m, tid=temp_id: handle_preview_edit(m, tid))
        return

    if key == "preview_cancel":
        bot.answer_callback_query(call.id, "Отменено.")
        try:
            temp_id = int(arg)
            if temp_id in temp_previews and temp_previews[temp_id][0] == uid:
                del temp_previews[temp_id]
        except:
            pass
        bot.send_message(uid, "Отменено.", reply_markup=main_menu_kb())
        return

    # --- Ещё инсайт ---
    if key == "more":
        bot.answer_callback_query(call.id, "Генерирую ещё инсайт...")
        info = get_user_info(uid)
        if not info or int(info[2]) == 0:
            bot.send_message(uid, "Чтобы получить инсайт, сначала отправь свой. Нажми 🖊 Написать инсайт.", reply_markup=main_menu_kb())
            return
        cd = check_cooldown(uid)
        if cd > 0:
            bot.send_message(uid, f"Пожалуйста, подожди: ещё рано запрашивать новый инсайт (кулдаун {cd} мин).")
            return
        row = get_random_insight_for_requester(uid)
        if not row:
            bot.send_message(uid, "Сейчас нет доступных инсайтов — попробуй позже.", reply_markup=main_menu_kb())
            return
        iid, text, author = row
        mark_delivered(uid, iid)
        set_user_cooldown(uid, minutes=COOLDOWN_MINUTES)
        bot.send_message(uid, f"Вот инсайт:\n«{text}»", reply_markup=insight_inline_kb(iid))
        return

    # --- Поделиться ---
    if key == "share":
        bot.answer_callback_query(call.id)
        try:
            iid = int(arg)
        except:
            bot.answer_callback_query(call.id, "Ошибка идентификатора.", show_alert=True)
            return

        row = get_insight_by_id(iid)
        if not row:
            bot.answer_callback_query(call.id, "Инсайт не найден.", show_alert=True)
            return

        _, _, text, is_flagged, _ = row
        if is_flagged:
            bot.answer_callback_query(call.id, "Этот инсайт недоступен для репоста.", show_alert=True)
            return

        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("Сформировать текст для репоста", callback_data=f"make_share:{iid}"))
        kb.add(types.InlineKeyboardButton("Закрыть", callback_data="share_close"))

        bot.send_message(uid,
                         "Можешь переслать этот инсайт друзьям или в канал. "
                         "Хочешь, чтобы я сформировал короткий текст для репоста?",
                         reply_markup=kb)
        return

    # --- Сформировать текст для репоста ---
    if key == "make_share":
        try:
            iid = int(arg)
        except:
            bot.answer_callback_query(call.id, "Ошибка идентификатора.", show_alert=True)
            return
        row = get_insight_by_id(iid)
        if not row:
            bot.answer_callback_query(call.id, "Инсайт не найден.", show_alert=True)
            return
        text = row[2]
        share_text = f"«{text}»–\nАноним\n\nХочешь почитать чужие мысли?\n@SoulShare1_bot"
        bot.answer_callback_query(call.id, "Готово")
        bot.send_message(uid, share_text)
        return

    if key in ("share_close", "close"):
        bot.answer_callback_query(call.id, "Закрыто.")
        return

    # --- Жалоба на инсайт (inline) ---
    if key == "report":
        try:
            iid = int(arg)
        except:
            bot.answer_callback_query(call.id, "Ошибка идентификатора.", show_alert=True)
            return
        bot.answer_callback_query(call.id, "Открываю форму жалобы...")
        sent = bot.send_message(uid, "Укажите причину жалобы (коротко). Примеры: «оскорбление», «угроза», «личные данные», «спам».")

        def after_reason(m):
            reason = m.text or "(без текста)"
            save_report(iid, m.from_user.id, reason, is_general=False)

            # ✅ пользователю
            bot.send_message(m.chat.id, "✅ Жалоба отправлена модератору. Спасибо!")

            # 📢 админу
            kb = types.InlineKeyboardMarkup()
            kb.add(
                types.InlineKeyboardButton("❌ Удалить инсайт", callback_data=f"delete:{iid}")
            )
            bot.send_message(
                ADMIN_ID,
                f"🚨 Жалоба на инсайт #{iid}\n"
                f"Отправитель: @{m.from_user.username or m.from_user.id}\n"
                f"Причина: {reason}",
                reply_markup=kb
            )

        bot.register_next_step_handler(sent, after_reason)

    # --- Админ: delete (удалить сразу) ---
    if key == "delete":
        # доступ только админу
        if uid != ADMIN_ID:
            bot.answer_callback_query(call.id, "У тебя нет прав.", show_alert=True)
            return
        try:
            iid = int(arg)
        except:
            bot.answer_callback_query(call.id, "Ошибка идентификатора.", show_alert=True)
            return
        try:
            flag_insight(iid)
        except Exception as e:
            print("flag_insight error:", e)
            bot.answer_callback_query(call.id, "Ошибка при удалении.", show_alert=True)
            return
        bot.answer_callback_query(call.id, "Инсайт удалён ✅")
        # убрать кнопки у сообщения чтобы нельзя было нажать снова
        try:
            bot.edit_message_reply_markup(chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=None)
        except Exception:
            pass
        bot.send_message(ADMIN_ID, f"❌ Инсайт #{iid} помечен как удалён (is_flagged=1).")
        return

    # default
    bot.answer_callback_query(call.id, "Неподдерживаемое действие.", show_alert=True)
    return

# ========== Вспомогательные обработчики ==========
def handle_preview_edit(message, temp_id):
    err = validate_insight_text(message.text)
    if err:
        bot.send_message(message.chat.id, err, reply_markup=main_menu_kb())
        return
    if temp_id not in temp_previews or temp_previews[temp_id][0] != message.from_user.id:
        bot.send_message(message.chat.id, "Временные данные устарели.", reply_markup=main_menu_kb())
        return
    temp_previews[temp_id] = (message.from_user.id, message.text)
    bot.send_message(message.chat.id, f"Отредактированный превью:\n«{message.text}»", reply_markup=preview_kb(temp_id))

def handle_report_submission(message, insight_id):
    reason = message.text or "(без текста)"
    save_report(insight_id, message.from_user.id, reason)
    bot.send_message(message.chat.id, "🚩 Жалоба отправлена модератору. Спасибо!", reply_markup=main_menu_kb())
    # уведомляем админа с кнопкой удалить
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("❌ Удалить инсайт", callback_data=f"delete:{insight_id}"))
    insight = get_insight_by_id(insight_id)
    text = insight[2] if insight else "(не найден)"
    bot.send_message(ADMIN_ID, f"🚨 Жалоба на инсайт #{insight_id}\nТекст: {text}\nПричина: {reason}", reply_markup=kb)

# ========== fallback: любой текст предлагается как инсайт-превью ==========
@bot.message_handler(func=lambda m: True, content_types=['text'])
def fallback(m):
    txt = m.text.strip()
    if txt in ("🖊 Написать инсайт", "🎲 Получить инсайт", "ℹ️ О боте", "⚠️ Пожаловаться"):
        return
    err = validate_insight_text(txt)
    if err:
        bot.send_message(m.chat.id, err, reply_markup=main_menu_kb())
        return
    temp_id = make_temp_id()
    temp_previews[temp_id] = (m.from_user.id, txt)
    bot.send_message(m.chat.id, f"Ты отправляешь анонимно:\n«{txt}»", reply_markup=preview_kb(temp_id))

# ========== АДМИН: ПАНЕЛЬ ==========
# --- 1. Список игроков ---
def show_admin_users(call):
    conn = sqlite3.connect("insight.db")
    cur = conn.cursor()
    cur.execute("SELECT user_id, username, has_posted, messages_sent FROM users ORDER BY reg_date DESC")
    users = cur.fetchall()
    conn.close()

    if not users:
        bot.send_message(call.from_user.id, "Список игроков пуст.")
        return

    text = "👥 Список игроков:\n\n"
    for u in users:
        text += f"ID: {u[0]} | @{u[1] or 'не указан'} | Отправил инсайт: {'Да' if u[2] else 'Нет'} | Сообщений: {u[3]}\n"

    bot.send_message(call.from_user.id, text)

# --- 2. Список инсайтов ---
def show_admin_insights(call):
    conn = sqlite3.connect("insight.db")
    cur = conn.cursor()
    cur.execute("SELECT id, author_id, text, is_flagged FROM insights ORDER BY created_at DESC")
    insights = cur.fetchall()
    conn.close()

    if not insights:
        bot.send_message(call.from_user.id, "Список инсайтов пуст.")
        return

    kb = types.InlineKeyboardMarkup()
    for i in insights:
        display_text = (i[2][:30] + "...") if len(i[2]) > 30 else i[2]
        kb.add(types.InlineKeyboardButton(f"#{i[0]}: {display_text}", callback_data=f"admin_insight_detail:{i[0]}"))
    kb.add(types.InlineKeyboardButton("⬅ Назад", callback_data="admin_insights_back"))

    bot.send_message(call.from_user.id, "📝 Список инсайтов:", reply_markup=kb)

# --- 3. Просмотр инсайта с кнопками удалить/назад ---
def show_insight_detail(call, iid):
    insight = get_insight_by_id(iid)
    if not insight:
        bot.send_message(call.from_user.id, f"Инсайт #{iid} не найден.")
        return

    text = f"📄 Инсайт #{iid}\nАвтор: {insight[1]}\n\n{(insight[2][:300] + "...") if len(insight[2]) > 300 else insight[2]}\n\nФлаг: {'Да' if insight[3] else 'Нет'}"
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("❌ Удалить инсайт", callback_data=f"delete:{iid}"))
    kb.add(types.InlineKeyboardButton("⬅ Назад", callback_data="admin_insights"))

    bot.send_message(call.from_user.id, text, reply_markup=kb)

# --- 4. Список жалоб на инсайты ---
def show_admin_reports(call):
    conn = sqlite3.connect("insight.db")
    cur = conn.cursor()
    cur.execute("""
        SELECT r.id, r.insight_id, r.user_id, r.reason, i.text
        FROM reports r
        LEFT JOIN insights i ON r.insight_id = i.id
        ORDER BY r.created_at DESC
    """)
    reports = cur.fetchall()
    conn.close()

    if not reports:
        bot.send_message(call.from_user.id, "Список жалоб пуст.")
        return

    for r in reports:
        iid = r[1]
        report_text = r[4] if r[4] else "(Инсайт удалён)"
        msg = (
            f"🚨 Жалоба #{r[0]}\n"
            f"Инсайт ID: {iid}\n"
            f"От пользователя: {r[2]}\n"
            f"Текст инсайта: {report_text}\n"
            f"Причина: {r[3]}"
        )
        kb = types.InlineKeyboardMarkup()
        if iid:
            kb.add(types.InlineKeyboardButton("❌ Удалить инсайт", callback_data=f"delete:{iid}"))
        bot.send_message(call.from_user.id, msg, reply_markup=kb)


# ========== Запуск ==========
if __name__ == "__main__":
    print("Bot started")
    bot.infinity_polling(timeout=60, long_polling_timeout=60)