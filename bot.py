"""
LEXX^ Telegram Bot  |  v5.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Панель администратора, напоминания, история заявок,
рассылка с медиа, обновлённые тексты.
"""

import logging, sqlite3, json, re, os
from datetime import datetime, timedelta
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    InlineQueryResultArticle, InputTextMessageContent
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, InlineQueryHandler,
    filters, ContextTypes, JobQueue
)

# ── НАСТРОЙКИ ─────────────────────────────────────────────────────────────────
BOT_TOKEN     = os.environ.get("BOT_TOKEN", "")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "0"))
if not BOT_TOKEN:     raise ValueError("BOT_TOKEN не задан!")
if not ADMIN_CHAT_ID: raise ValueError("ADMIN_CHAT_ID не задан!")

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ── СОСТОЯНИЯ ─────────────────────────────────────────────────────────────────
(MAIN_MENU,
 LEGAL_MENU, LEGAL_DATE, LEGAL_TIME,
 STUDIO_MENU, BOOKING_DATE, BOOKING_TIME, BOOKING_COMMENT,
 PROD_MENU, PROD_CATEGORY,
 CASTING_ROLE, CASTING_PORTFOLIO,
 FORM_NAME, FORM_PHONE, FORM_CONSENT,
 BROADCAST_TEXT) = range(16)

# ── ЦЕНЫ (для расчёта выручки) ────────────────────────────────────────────────
SERVICE_PRICES = {
    "legal_consult":   3_000,
    "legal_docs":      2_000,
    "legal_analysis":  3_000,
    "studio":          2_000,
    "casting":         0,
    "prod_photo":      35_000,
    "prod_video":      35_000,
    "prod_smm":        18_000,
    "prod_design":     30_000,
    "prod_marketing":  45_000,
    "prod_packages":   69_000,
}

# ── БД ────────────────────────────────────────────────────────────────────────
DB_PATH = os.environ.get("DB_PATH", "lexx_bot.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS bookings(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, slot_type TEXT, date TEXT, time TEXT,
        name TEXT, phone TEXT, username TEXT, comment TEXT,
        reminded INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS applications(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, service_type TEXT, name TEXT,
        phone TEXT, username TEXT, consent INTEGER DEFAULT 0,
        additional_data TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS users(
        user_id INTEGER PRIMARY KEY,
        username TEXT, first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    conn.commit(); conn.close()
    logger.info("БД готова: %s", DB_PATH)

def register_user(user_id, username):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT OR IGNORE INTO users(user_id,username) VALUES(?,?)", (user_id, username))
    conn.commit(); conn.close()

def get_all_users():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT user_id FROM users").fetchall()
    conn.close(); return [r[0] for r in rows]

def get_users_count():
    conn = sqlite3.connect(DB_PATH)
    n = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    conn.close(); return n

def is_slot_booked(slot_type, date, time):
    conn = sqlite3.connect(DB_PATH)
    r = conn.execute("SELECT id FROM bookings WHERE slot_type=? AND date=? AND time=?",
                     (slot_type, date, time)).fetchone()
    conn.close(); return r is not None

def save_booking(user_id, slot_type, date, time, name, phone, username, comment=""):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO bookings(user_id,slot_type,date,time,name,phone,username,comment)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (user_id, slot_type, date, time, name, phone, username, comment))
    conn.commit(); conn.close()

def save_application(user_id, service_type, name, phone, username, additional):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO applications(user_id,service_type,name,phone,username,consent,additional_data)"
        " VALUES(?,?,?,?,?,1,?)",
        (user_id, service_type, name, phone, username,
         json.dumps(additional, ensure_ascii=False)))
    conn.commit(); conn.close()

def get_today_bookings():
    today = datetime.now().strftime("%Y-%m-%d")
    conn  = sqlite3.connect(DB_PATH)
    rows  = conn.execute(
        "SELECT slot_type,time,name,phone,username,comment FROM bookings"
        " WHERE date=? ORDER BY time", (today,)).fetchall()
    conn.close(); return rows

def get_tomorrow_bookings():
    tom  = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id,user_id,slot_type,time,name FROM bookings"
        " WHERE date=? AND reminded=0", (tom,)).fetchall()
    conn.close(); return rows

def mark_reminded(booking_id):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE bookings SET reminded=1 WHERE id=?", (booking_id,))
    conn.commit(); conn.close()

def get_recent_applications(limit=10):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT service_type,name,phone,username,created_at FROM applications"
        " ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    conn.close(); return rows

def get_user_history(user_id):
    conn = sqlite3.connect(DB_PATH)
    apps = conn.execute(
        "SELECT service_type,additional_data,created_at FROM applications"
        " WHERE user_id=? ORDER BY created_at DESC LIMIT 10", (user_id,)).fetchall()
    books = conn.execute(
        "SELECT slot_type,date,time,comment,created_at FROM bookings"
        " WHERE user_id=? ORDER BY created_at DESC LIMIT 10", (user_id,)).fetchall()
    conn.close(); return apps, books

def get_stats():
    conn = sqlite3.connect(DB_PATH)
    total_apps   = conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
    total_books  = conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]
    total_users  = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    today        = datetime.now().strftime("%Y-%m-%d")
    today_books  = conn.execute("SELECT COUNT(*) FROM bookings WHERE date=?", (today,)).fetchone()[0]
    month_start  = datetime.now().strftime("%Y-%m-01")
    month_apps   = conn.execute(
        "SELECT service_type FROM applications WHERE created_at>=?", (month_start,)).fetchall()
    conn.close()
    revenue = sum(SERVICE_PRICES.get(r[0], 0) for r in month_apps)
    return total_apps, total_books, total_users, today_books, revenue

# ── УТИЛИТЫ ───────────────────────────────────────────────────────────────────
def fmt(p): return f"{p:,}".replace(",", " ") + " ₽"
def validate_phone(p): return len(re.sub(r"\D","",p)) >= 10
def get_uname(user): return f"@{user.username}" if user.username else f"ID:{user.id}"

SERVICE_LABELS = {
    "legal_consult":  "⚖️ Консультация",
    "legal_docs":     "📄 Документ",
    "legal_analysis": "🔍 Досудебная подготовка",
    "studio":         "📸 Фотостудия",
    "casting":        "🎭 Кастинг",
    "prod_photo":     "📷 Фотосъёмка",
    "prod_video":     "🎬 Видеопроизводство",
    "prod_smm":       "📱 SMM",
    "prod_design":    "🎨 Дизайн",
    "prod_marketing": "📣 Маркетинг",
    "prod_packages":  "🏖️ Пакет сезона",
}

async def notify_admin(context, text):
    try: await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=text, parse_mode="HTML")
    except Exception as e: logger.error("Ошибка уведомления: %s", e)

# ── ТЕКСТЫ ────────────────────────────────────────────────────────────────────
WELCOME = (
    "👋 Привет! Вы в <b>LEXX^</b> — агентстве, где одна команда\n"
    "закрывает все задачи вашего бизнеса.\n\n"
    "⚖️ <b>Юридическая помощь</b>\n"
    "   Документы, консультации, досудебная стратегия\n\n"
    "📸 <b>Фотостудия</b>\n"
    "   Аренда, фотографы, рилсмейкеры, видеографы\n\n"
    "🎬 <b>Продакшен и контент</b>\n"
    "   Фото · Видео · SMM · Дизайн · Маркетинг\n\n"
    "🎭 <b>Кастинг</b>\n"
    "   Участие в проектах агентства\n\n"
    "Выберите направление — и мы сделаем всё остальное 👇"
)

LEGAL_INFO = (
    "⚖️ <b>Юридическая помощь LEXX^</b>\n\n"
    "Юридические проблемы — это стресс и потеря времени.\n"
    "Мы берём на себя всю подготовительную работу:\n"
    "документы, анализ, стратегию — вы просто принимаете решения.\n\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "🗣 <b>Устная консультация — 3 000 ₽/час</b>\n\n"
    "   Разбор вашей ситуации без воды и общих фраз.\n"
    "   Гражданские, трудовые, семейные, жилищные вопросы,\n"
    "   долги, споры с контрагентами, недвижимость.\n\n"
    "   Что вы получаете:\n"
    "   • Честную оценку шансов — без прикрас\n"
    "   • Конкретный план: что делать, куда идти,\n"
    "     какие документы собирать\n"
    "   • Экспресс-анализ ваших документов прямо на встрече\n\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "📄 <b>Составление документов — от 2 000 ₽</b>\n\n"
    "   Документ «под ключ» по вашим вводным.\n"
    "   Договоры · Претензии · Исковые заявления\n"
    "   Жалобы · Заявления в госорганы · Возражения на иск\n"
    "   Апелляция · Кассация · Требования о возмещении ущерба\n\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "🔍 <b>Досудебная подготовка — от 3 000 ₽</b>\n\n"
    "   Правовая экспертиза договоров — находим «мины»\n"
    "   до того как они взорвались. Сбор доказательной\n"
    "   базы, расчёт неустоек и пеней по ст. 395 ГК РФ,\n"
    "   ответ на чужую претензию или иск.\n\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "❗️ Мы не адвокаты — не представляем вас в суде.\n"
    "   Но мы делаем всё, чтобы вы пришли туда подготовленными.\n\n"
    "Выберите действие 👇"
)

STUDIO_INFO = (
    "📸 <b>Фотостудия LEXX^</b>\n\n"
    "Профессиональное пространство в Крыму.\n"
    "Берите студию под себя или работайте\n"
    "с нашими специалистами — результат будет.\n\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "🏠 <b>Аренда студии — 2 000 ₽/час</b>\n"
    "   Зал + свет + базовый реквизит\n"
    "   Минимальный заказ — 1 час\n\n"
    "🎙 <b>Пакет «Подкаст» — от 5 000 ₽/час</b>\n"
    "   Зал + микрофон + видеосъёмка\n"
    "   ⚠️ Минимум — 2 часа\n"
    "   Для интервью, YouTube, подкастов\n\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "👥 <b>Специалисты на съёмку</b>\n\n"
    "📷 <b>Фотограф — 3 000 ₽/час</b>\n"
    "   Профессиональная съёмка + отбор кадров\n\n"
    "🎬 <b>Рилсмейкер — 1 500 ₽/час</b>\n"
    "   Reels · Shorts · TikTok — без ограничения по числу\n"
    "   Снимает и монтирует сразу на площадке\n\n"
    "🎥 <b>Видеограф — 3 000 ₽/час</b>\n"
    "   Реклама, корпоративные видео, мероприятия\n\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "💡 <b>Выгодные комбо:</b>\n"
    "   Студия 2 ч + Рилсмейкер 2 ч = <b>7 000 ₽</b>\n"
    "   Студия 2 ч + Фотограф 2 ч = <b>10 000 ₽</b>\n\n"
    "Работаем 8:00–21:00. Бронируйте слот 👇"
)

PROD_CATEGORIES = {
    "photo": {
        "label": "📷 Фотосъёмка",
        "text": (
            "📷 <b>Фотосъёмка для бизнеса</b>\n\n"
            "Фото, которые продают — не просто красивые картинки.\n"
            "Каждый снимок создаётся с пониманием вашей аудитории\n"
            "и задачи: привлечь, убедить, запомниться.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🍽 Фуд-съёмка (до 20 блюд + ретушь) — <b>{fmt(45_000)}</b>\n"
            f"📦 Предметная съёмка (до 30 предметов) — <b>{fmt(35_000)}</b>\n"
            f"👥 Команда / сотрудники (до 15 чел.) — <b>{fmt(30_000)}</b>\n"
            f"📹 Репортаж мероприятия (до 8 ч.) — <b>{fmt(55_000)}</b>\n"
            f"👗 Лукбук — fashion / бренд (до 10 образов) — <b>{fmt(90_000)}</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "💬 <i>Стоимость уточняется после брифинга.\n"
            "Оставьте заявку — пришлём КП в течение часа.</i>"
        )
    },
    "video": {
        "label": "🎬 Видеопроизводство",
        "text": (
            "🎬 <b>Видеопроизводство под ключ</b>\n\n"
            "От идеи до готового файла — без вашего участия\n"
            "на производственном этапе. Сценарий, съёмка,\n"
            "монтаж, звук, графика — всё внутри.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📺 Рекламный ролик 15–60 сек — <b>{fmt(180_000)}</b>\n"
            f"🎞 Корпоративный фильм 3–7 мин — <b>{fmt(280_000)}</b>\n"
            f"📱 Рилс / Shorts (1 шт.) — <b>{fmt(35_000)}</b>\n"
            f"📱 Пакет рилс × 4 шт. — <b>{fmt(110_000)}</b>\n"
            f"⚡️ Тизер / анонс 30–45 сек — <b>{fmt(70_000)}</b>\n"
            f"🌟 Видео-кейс / отзыв клиента — <b>{fmt(55_000)}</b>\n"
            f"🎪 Мероприятие — полный день (highlights) — <b>{fmt(150_000)}</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "💬 <i>Производство — 3–14 рабочих дней.\n"
            "Оставьте заявку — обсудим формат и дедлайн.</i>"
        )
    },
    "smm": {
        "label": "📱 SMM",
        "text": (
            "📱 <b>SMM — присутствие, которое работает</b>\n\n"
            "Соцсети — это не про красивые картинки.\n"
            "Это про то, чтобы клиент вспомнил вас первым,\n"
            "когда появится потребность.\n\n"
            "Работаем с Instagram · VK · Telegram · TikTok\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🔍 Аудит аккаунта (PDF-отчёт) — <b>{fmt(18_000)}</b>\n"
            f"✨ Оформление профиля под ключ — <b>{fmt(22_000)}</b>\n"
            f"🗺 Контент-стратегия (ЦА, рубрики, KPI) — <b>{fmt(35_000)}</b>\n"
            f"📝 Сценарии для Reels × 8 шт. — <b>{fmt(24_000)}</b>\n"
            f"✈️ Ведение Telegram-канала / мес. — <b>{fmt(40_000)}</b>\n"
            f"⚡️ Экспресс-рилс под ключ (1 шт.) — <b>{fmt(12_000)}</b>\n"
            f"📦 Пакет Reels × 4 шт. — <b>{fmt(42_000)}</b>\n"
            f"🚀 Reels-марафон × 12 роликов / мес. — <b>{fmt(95_000)}</b>\n"
            f"💬 Комьюнити-менеджмент / мес. — <b>{fmt(28_000)}</b>\n"
            f"🎯 Таргет ВКонтакте — быстрый старт — <b>{fmt(35_000)}</b>\n"
            f"📈 Продвижение через Reels — органика — <b>{fmt(45_000)}</b>\n"
            f"📊 Ежемесячный отчёт + аналитика — <b>{fmt(12_000)}</b>\n"
            f"💊 Реанимация аккаунта после простоя — <b>{fmt(32_000)}</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "💬 <i>Один менеджер — весь проект. Рекламный бюджет\n"
            "отдельно, только по факту расхода.</i>"
        )
    },
    "design": {
        "label": "🎨 Дизайн",
        "text": (
            "🎨 <b>Дизайн, который узнают</b>\n\n"
            "Ваш визуал — это первое что видит клиент.\n"
            "Мы создаём дизайн, который доносит ценность\n"
            "ещё до того, как человек прочитал первое слово.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🏛 Фирменный стиль — брендбук lite — <b>{fmt(120_000)}</b>\n"
            f"📦 Дизайн упаковки (1 SKU) — <b>{fmt(65_000)}</b>\n"
            f"🖼 Шаблоны для соцсетей (15 шт.) — <b>{fmt(45_000)}</b>\n"
            f"📊 Презентация до 20 слайдов — <b>{fmt(40_000)}</b>\n"
            f"🖥 Баннеры — пакет 8 форматов — <b>{fmt(30_000)}</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "💬 <i>Исходники — ваши. До 3 итераций правок включены.\n"
            "Оставьте заявку — пришлём портфолио.</i>"
        )
    },
    "marketing": {
        "label": "📣 Реклама и маркетинг",
        "text": (
            "📣 <b>Реклама, которая окупается</b>\n\n"
            "Мы не запускаем рекламу ради цифр в отчёте.\n"
            "Мы строим воронку: сначала доверие,\n"
            "потом трафик — так конверсия в разы выше.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🎯 Таргет ВКонтакте / myTarget (1 мес.) — <b>{fmt(55_000)}</b>\n"
            f"🔎 Яндекс.Директ (1 мес.) — <b>{fmt(65_000)}</b>\n"
            f"🗺 SMM-стратегия на 3 мес. — <b>{fmt(80_000)}</b>\n"
            f"📲 Ведение соцсетей — 1 платформа (1 мес.) — <b>{fmt(45_000)}</b>\n"
            f"📧 Email-рассылки (стратегия + 4 письма) — <b>{fmt(55_000)}</b>\n"
            f"🔍 SEO-аудит сайта — <b>{fmt(40_000)}</b>\n"
            f"📋 Контент-план на 3 месяца — <b>{fmt(30_000)}</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "💬 <i>Рекламный бюджет — отдельно, только по факту.\n"
            "Ведём отчётность в реальном времени.</i>"
        )
    },
    "packages": {
        "label": "🏖️ Пакеты сезона 2026",
        "text": (
            "🏖️ <b>Пакеты — Крымский сезон 2026</b>\n\n"
            "Лето в Крыму — это 3 месяца, за которые решается\n"
            "весь год. Пока конкуренты молчат — вы в ленте\n"
            "у каждого туриста, который приедет в этот город.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💡 <b>Контент-основа — старт</b> — <b>{fmt(69_000)}</b>\n"
            "   6 роликов · VK / Reels / Shorts\n\n"
            f"⭐️ <b>Контент под ключ — ФЛАГМАН</b> — <b>{fmt(89_000)}</b>\n"
            "   8 роликов · смыслы · стратегия · рекомендации\n\n"
            f"🚀 <b>Контент + заявки — максимум</b> — <b>{fmt(119_000)}</b>\n"
            "   12 роликов · воронка · консультация по продажам\n\n"
            f"🌊 <b>Старт сезона (экспресс, 7 дней)</b> — <b>{fmt(49_000)}</b>\n"
            "   Аудит · оформление · 4 сезонных рилс\n\n"
            f"🏨 <b>Туристический хит</b> — <b>{fmt(99_000)}</b>\n"
            "   8 роликов · фото 20 кадров · Stories · VK+Instagram\n\n"
            f"🍕 <b>Ресторан в топе</b> — <b>{fmt(85_000)}</b>\n"
            "   8 фуд-роликов · фотосессия 15 блюд · геометки\n\n"
            f"🌅 <b>Летний поток — максимум</b> — <b>{fmt(149_000)}</b>\n"
            "   12 роликов/мес · таргет · воронка · аналитика\n\n"
            f"🍷 <b>Крымский бренд</b> — <b>{fmt(79_000)}</b>\n"
            "   6 роликов с историей · лукбук · интеграция в паблики\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "💬 <i>Каждый пакет адаптируется под вашу нишу.\n"
            "Оставьте заявку — составим предложение под ваш сезон.</i>"
        )
    },
}

# ── КЛАВИАТУРЫ ────────────────────────────────────────────────────────────────
def kb_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚖️ Юридическая помощь",      callback_data="go_legal")],
        [InlineKeyboardButton("📸 Фотостудия",              callback_data="go_studio")],
        [InlineKeyboardButton("🎬 Продакшен и контент",     callback_data="go_prod")],
        [InlineKeyboardButton("🎭 Кастинг",                 callback_data="go_casting")],
        [InlineKeyboardButton("📋 Мои заявки",              callback_data="my_apps")],
    ])

def kb_legal():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Записаться на консультацию", callback_data="legal_book")],
        [InlineKeyboardButton("📄 Заявка — составить документ", callback_data="legal_form_doc")],
        [InlineKeyboardButton("🔍 Досудебная подготовка",      callback_data="legal_form_analysis")],
        [InlineKeyboardButton("🏠 Главное меню",               callback_data="go_home")],
    ])

def kb_studio():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Забронировать студию", callback_data="studio_book")],
        [InlineKeyboardButton("🏠 Главное меню",         callback_data="go_home")],
    ])

def kb_prod():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📷 Фотосъёмка",           callback_data="prod_photo")],
        [InlineKeyboardButton("🎬 Видеопроизводство",    callback_data="prod_video")],
        [InlineKeyboardButton("📱 SMM",                  callback_data="prod_smm")],
        [InlineKeyboardButton("🎨 Дизайн",              callback_data="prod_design")],
        [InlineKeyboardButton("📣 Реклама и маркетинг", callback_data="prod_marketing")],
        [InlineKeyboardButton("🏖️ Пакеты сезона 2026",  callback_data="prod_packages")],
        [InlineKeyboardButton("🏠 Главное меню",         callback_data="go_home")],
    ])

def kb_prod_detail():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📩 Оставить заявку", callback_data="prod_apply")],
        [InlineKeyboardButton("⬅️ Назад",           callback_data="go_prod")],
        [InlineKeyboardButton("🏠 Главное меню",    callback_data="go_home")],
    ])

def kb_home():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Главное меню", callback_data="go_home")]])

def kb_back_home():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Назад", callback_data="go_back"),
        InlineKeyboardButton("🏠 Главное меню", callback_data="go_home"),
    ]])

def kb_consent():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Даю согласие на обработку данных", callback_data="consent_yes")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="go_home")],
    ])

def kb_dates(slot_type):
    today = datetime.now(); buttons = []; row = []
    for i in range(30):
        d = today + timedelta(days=i)
        lbl = d.strftime("%d.%m") + (" (сег.)" if i == 0 else "")
        row.append(InlineKeyboardButton(lbl, callback_data=f"date_{slot_type}_{d.strftime('%Y-%m-%d')}"))
        if len(row) == 3: buttons.append(row); row = []
    if row: buttons.append(row)
    buttons.append([
        InlineKeyboardButton("⬅️ Назад", callback_data="go_back"),
        InlineKeyboardButton("🏠 Главное меню", callback_data="go_home"),
    ])
    return InlineKeyboardMarkup(buttons)

def kb_times(slot_type, selected_date):
    buttons = []; row = []
    for h in range(8, 22):
        ts = f"{h:02d}:00"
        busy = is_slot_booked(slot_type, selected_date, ts)
        lbl = f"❌ {ts}" if busy else f"✅ {ts}"
        cb  = f"time_busy_{ts}" if busy else f"time_{slot_type}_{ts}"
        row.append(InlineKeyboardButton(lbl, callback_data=cb))
        if len(row) == 3: buttons.append(row); row = []
    if row: buttons.append(row)
    buttons.append([
        InlineKeyboardButton("⬅️ Назад", callback_data="go_back"),
        InlineKeyboardButton("🏠 Главное меню", callback_data="go_home"),
    ])
    return InlineKeyboardMarkup(buttons)

# ── ПАНЕЛЬ АДМИНИСТРАТОРА ─────────────────────────────────────────────────────
def kb_admin():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Статистика и выручка",  callback_data="adm_stats")],
        [InlineKeyboardButton("📅 Занятость сегодня",     callback_data="adm_today")],
        [InlineKeyboardButton("📋 Последние заявки",      callback_data="adm_apps")],
        [InlineKeyboardButton("📢 Рассылка",              callback_data="adm_broadcast")],
        [InlineKeyboardButton("🏠 Главное меню",          callback_data="go_home")],
    ])

async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔️ Нет доступа."); return
    total_apps, total_books, total_users, today_books, revenue = get_stats()
    text = (
        "🛠 <b>Панель администратора LEXX^</b>\n\n"
        f"👥 Пользователей в базе: <b>{total_users}</b>\n"
        f"📋 Всего заявок: <b>{total_apps}</b>\n"
        f"📅 Всего бронирований: <b>{total_books}</b>\n"
        f"📅 Бронирований сегодня: <b>{today_books}</b>\n"
        f"💰 Планируемая выручка за месяц: <b>{fmt(revenue)}</b>\n\n"
        "Выберите раздел 👇"
    )
    await update.message.reply_text(text, reply_markup=kb_admin(), parse_mode="HTML")

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if update.effective_user.id != ADMIN_CHAT_ID:
        await query.answer("⛔️ Нет доступа.", show_alert=True); return
    data = query.data

    if data == "adm_stats":
        total_apps, total_books, total_users, today_books, revenue = get_stats()
        text = (
            "📊 <b>Статистика LEXX^</b>\n\n"
            f"👥 Пользователей: <b>{total_users}</b>\n"
            f"📋 Заявок всего: <b>{total_apps}</b>\n"
            f"📅 Бронирований всего: <b>{total_books}</b>\n"
            f"📅 Бронирований сегодня: <b>{today_books}</b>\n\n"
            f"💰 <b>Планируемая выручка за текущий месяц</b>\n"
            f"   {fmt(revenue)}\n\n"
            f"<i>Рассчитана по минимальным ценам каждой услуги.</i>"
        )
        await query.edit_message_text(text, reply_markup=kb_admin(), parse_mode="HTML")

    elif data == "adm_today":
        rows = get_today_bookings()
        today_str = datetime.now().strftime("%d.%m.%Y")
        if not rows:
            text = f"📅 <b>Занятость на {today_str}</b>\n\nСвободно — записей нет."
        else:
            lines = [f"📅 <b>Занятость на {today_str}</b>\n"]
            slot_labels = {"legal": "⚖️ Консультация", "studio": "📸 Студия"}
            for slot_type, time, name, phone, username, comment in rows:
                lbl = slot_labels.get(slot_type, slot_type)
                lines.append(
                    f"🕐 <b>{time}</b> — {lbl}\n"
                    f"   👤 {name} | 📞 {phone} | {username}"
                )
                if comment: lines.append(f"   📝 {comment}")
                lines.append("")
            text = "\n".join(lines)
        await query.edit_message_text(text, reply_markup=kb_admin(), parse_mode="HTML")

    elif data == "adm_apps":
        rows = get_recent_applications(15)
        if not rows:
            text = "📋 Заявок пока нет."
        else:
            lines = ["📋 <b>Последние 15 заявок</b>\n"]
            for stype, name, phone, username, created_at in rows:
                lbl = SERVICE_LABELS.get(stype, stype)
                dt  = created_at[:16] if created_at else "—"
                lines.append(f"• {lbl}\n  {name} | {phone} | {username}\n  🕒 {dt}\n")
            text = "\n".join(lines)
        await query.edit_message_text(text, reply_markup=kb_admin(), parse_mode="HTML")

    elif data == "adm_broadcast":
        context.user_data["admin_broadcast"] = True
        await query.edit_message_text(
            "📢 <b>Рассылка</b>\n\n"
            "Отправьте сообщение, которое получат все пользователи.\n\n"
            "Поддерживается:\n"
            "✅ Текст (с HTML-форматированием)\n"
            "✅ Фото\n"
            "✅ Видео\n"
            "✅ Документы\n\n"
            "Просто отправьте сообщение следующим сообщением.\n"
            "Для отмены — /cancel",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Отмена", callback_data="adm_cancel_broadcast")
            ]])
        )
        return BROADCAST_TEXT

    elif data == "adm_cancel_broadcast":
        context.user_data.pop("admin_broadcast", None)
        await query.edit_message_text(
            "❌ Рассылка отменена.", reply_markup=kb_admin())

    elif data == "go_home":
        context.user_data.clear()
        await show_main(update, context, edit=True)
        return MAIN_MENU

# ── РАССЫЛКА С МЕДИА ──────────────────────────────────────────────────────────
async def broadcast_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получаем медиа или текст для рассылки"""
    if not context.user_data.get("admin_broadcast"):
        return await form_name(update, context)  # передаём в обычную форму

    msg    = update.message
    users  = get_all_users()
    sent   = 0; failed = 0

    status = await msg.reply_text(f"⏳ Рассылка запущена... Получателей: {len(users)}")

    for uid in users:
        try:
            if msg.photo:
                await context.bot.send_photo(
                    chat_id=uid,
                    photo=msg.photo[-1].file_id,
                    caption=msg.caption or "",
                    parse_mode="HTML")
            elif msg.video:
                await context.bot.send_video(
                    chat_id=uid,
                    video=msg.video.file_id,
                    caption=msg.caption or "",
                    parse_mode="HTML")
            elif msg.document:
                await context.bot.send_document(
                    chat_id=uid,
                    document=msg.document.file_id,
                    caption=msg.caption or "",
                    parse_mode="HTML")
            else:
                await context.bot.send_message(
                    chat_id=uid,
                    text=msg.text or "",
                    parse_mode="HTML")
            sent += 1
        except Exception:
            failed += 1

    context.user_data.pop("admin_broadcast", None)
    await status.edit_text(
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"📤 Отправлено: <b>{sent}</b>\n"
        f"❌ Не доставлено: <b>{failed}</b>\n"
        f"👥 Всего в базе: <b>{len(users)}</b>",
        parse_mode="HTML")
    return ConversationHandler.END

# ── ИСТОРИЯ ЗАЯВОК ПОЛЬЗОВАТЕЛЯ ───────────────────────────────────────────────
async def my_applications(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    uid   = update.effective_user.id
    apps, books = get_user_history(uid)

    if not apps and not books:
        await query.edit_message_text(
            "📋 <b>Мои заявки</b>\n\nУ вас пока нет заявок и бронирований.\n\n"
            "Выберите услугу — и мы займёмся вашим проектом! 💪",
            reply_markup=kb_home(), parse_mode="HTML")
        return MAIN_MENU

    lines = ["📋 <b>Ваши заявки и бронирования</b>\n"]

    if books:
        lines.append("📅 <b>Бронирования:</b>")
        slot_labels = {"legal": "⚖️ Консультация", "studio": "📸 Студия"}
        for slot_type, date, time, comment, created_at in books:
            lbl = slot_labels.get(slot_type, slot_type)
            try: dd = datetime.strptime(date, "%Y-%m-%d").strftime("%d.%m.%Y")
            except: dd = date
            lines.append(f"  • {lbl} — {dd} в {time}")
            if comment: lines.append(f"    📝 {comment}")
        lines.append("")

    if apps:
        lines.append("📩 <b>Заявки на услуги:</b>")
        for stype, additional_data, created_at in apps:
            lbl = SERVICE_LABELS.get(stype, stype)
            dt  = created_at[:10] if created_at else "—"
            try: dd = datetime.strptime(dt, "%Y-%m-%d").strftime("%d.%m.%Y")
            except: dd = dt
            lines.append(f"  • {lbl} — {dd}")

    lines.append(
        "\n<i>Если у вас вопросы по заявке — просто напишите нам,\n"
        "мы всегда на связи.</i>")

    await query.edit_message_text(
        "\n".join(lines), reply_markup=kb_home(), parse_mode="HTML")
    return MAIN_MENU

# ── НАПОМИНАНИЯ ───────────────────────────────────────────────────────────────
async def send_reminders(context: ContextTypes.DEFAULT_TYPE):
    """Запускается каждый день в 10:00 — рассылает напоминания за день до записи"""
    rows = get_tomorrow_bookings()
    if not rows:
        return
    slot_labels = {"legal": "юридической консультации", "studio": "съёмки в фотостудии"}
    tom = (datetime.now() + timedelta(days=1)).strftime("%d.%m.%Y")
    for booking_id, user_id, slot_type, time, name in rows:
        lbl = slot_labels.get(slot_type, "записи")
        text = (
            f"🔔 <b>Напоминание от LEXX^</b>\n\n"
            f"Привет, {name}! 👋\n\n"
            f"Напоминаем, что завтра — <b>{tom}</b> в <b>{time}</b>\n"
            f"у вас запланирована {lbl}.\n\n"
            f"Если что-то изменилось — напишите нам заранее,\n"
            f"мы перенесём без проблем. 🙏"
        )
        try:
            await context.bot.send_message(chat_id=user_id, text=text, parse_mode="HTML")
            mark_reminded(booking_id)
            logger.info("Напоминание отправлено: user_id=%s, booking_id=%s", user_id, booking_id)
        except Exception as e:
            logger.error("Ошибка напоминания для %s: %s", user_id, e)

# ── ПОКАЗ ГЛАВНОГО МЕНЮ ───────────────────────────────────────────────────────
async def show_main(update, context, edit=False):
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(
            WELCOME, reply_markup=kb_main(), parse_mode="HTML")
    else:
        tgt = update.message or update.callback_query.message
        await tgt.reply_text(WELCOME, reply_markup=kb_main(), parse_mode="HTML")

# ── КОМАНДЫ ───────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    register_user(update.effective_user.id, get_uname(update.effective_user))
    await update.message.reply_text(WELCOME, reply_markup=kb_main(), parse_mode="HTML")
    return MAIN_MENU

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "❌ Действие отменено.\n\nВернуться в меню — /start")
    return ConversationHandler.END

# ── ГЛАВНЫЙ РОУТЕР ────────────────────────────────────────────────────────────
async def main_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    data  = query.data

    if data == "go_home":
        context.user_data.clear(); await show_main(update, context, edit=True); return MAIN_MENU
    if data == "my_apps":  return await my_applications(update, context)
    if data == "go_legal":
        await query.edit_message_text(LEGAL_INFO, reply_markup=kb_legal(), parse_mode="HTML")
        return LEGAL_MENU
    if data == "go_studio":
        await query.edit_message_text(STUDIO_INFO, reply_markup=kb_studio(), parse_mode="HTML")
        return STUDIO_MENU
    if data == "go_prod":
        await query.edit_message_text(
            "🎬 <b>Продакшен и контент</b>\n\n"
            "Выберите направление — покажем цены и поможем с заявкой:",
            reply_markup=kb_prod(), parse_mode="HTML")
        return PROD_MENU
    if data == "go_casting":
        context.user_data.update({"service": "casting", "service_name": "🎭 Кастинг"})
        await query.edit_message_text(
            "🎭 <b>Кастинг LEXX^</b>\n\n"
            "Мы постоянно работаем над новыми проектами\n"
            "и ищем интересные лица и голоса.\n\n"
            "Укажите ваше <b>амплуа / роль</b>\n"
            "(актёр, модель, ведущий, диктор, танцор…):",
            reply_markup=kb_back_home(), parse_mode="HTML")
        return CASTING_ROLE
    return MAIN_MENU

# ── ЮРИДИКА ───────────────────────────────────────────────────────────────────
async def legal_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    data  = query.data
    if data == "go_home":
        context.user_data.clear(); await show_main(update, context, edit=True); return MAIN_MENU
    if data == "legal_book":
        context.user_data.update({"service": "legal_consult", "service_name": "⚖️ Консультация", "slot_type": "legal"})
        await query.edit_message_text(
            "📅 <b>Запись на консультацию</b>\n\n"
            "Выберите удобную дату:",
            reply_markup=kb_dates("legal"), parse_mode="HTML")
        return LEGAL_DATE
    if data == "legal_form_doc":
        context.user_data.update({"service": "legal_docs", "service_name": "📄 Составление документа"})
        await query.edit_message_text(
            "📄 <b>Заявка на составление документа</b>\n\n"
            "Расскажите задачу — мы подберём формат\n"
            "и рассчитаем стоимость за 1 час.\n\n"
            "Введите ваше <b>имя</b>:",
            reply_markup=kb_home(), parse_mode="HTML")
        return FORM_NAME
    if data == "legal_form_analysis":
        context.user_data.update({"service": "legal_analysis", "service_name": "🔍 Досудебная подготовка"})
        await query.edit_message_text(
            "🔍 <b>Досудебная подготовка</b>\n\n"
            "Стоимость рассчитывается индивидуально.\n"
            "Юрист свяжется и уточнит детали.\n\n"
            "Введите ваше <b>имя</b>:",
            reply_markup=kb_home(), parse_mode="HTML")
        return FORM_NAME
    return LEGAL_MENU

async def legal_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if query.data == "go_home":
        context.user_data.clear(); await show_main(update, context, edit=True); return MAIN_MENU
    if query.data == "go_back":
        await query.edit_message_text(LEGAL_INFO, reply_markup=kb_legal(), parse_mode="HTML")
        return LEGAL_MENU
    sd = query.data.split("_", 2)[2]; context.user_data["booking_date"] = sd
    dd = datetime.strptime(sd, "%Y-%m-%d").strftime("%d.%m.%Y")
    await query.edit_message_text(
        f"📅 Дата: <b>{dd}</b>\n\n✅ — свободно   ❌ — занято\n\nВыберите время:",
        reply_markup=kb_times("legal", sd), parse_mode="HTML")
    return LEGAL_TIME

async def legal_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if query.data == "go_home":
        context.user_data.clear(); await show_main(update, context, edit=True); return MAIN_MENU
    if query.data == "go_back":
        await query.edit_message_text(
            "📅 <b>Запись на консультацию</b>\n\nВыберите дату:",
            reply_markup=kb_dates("legal"), parse_mode="HTML")
        return LEGAL_DATE
    if query.data.startswith("time_busy_"):
        await query.answer("❌ Это время занято. Выберите другое.", show_alert=True)
        return LEGAL_TIME
    st = query.data.split("_", 2)[2]; context.user_data["booking_time"] = st
    sd = context.user_data["booking_date"]
    dd = datetime.strptime(sd, "%Y-%m-%d").strftime("%d.%m.%Y")
    await query.edit_message_text(
        f"📅 Дата: <b>{dd}</b>  🕐 Время: <b>{st}</b>\n\n"
        "Отлично! Юрист будет ждать вас.\n\n"
        "Введите ваше <b>имя</b>:",
        reply_markup=kb_home(), parse_mode="HTML")
    return FORM_NAME

# ── СТУДИЯ ────────────────────────────────────────────────────────────────────
async def studio_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if query.data == "go_home":
        context.user_data.clear(); await show_main(update, context, edit=True); return MAIN_MENU
    if query.data == "studio_book":
        context.user_data.update({"service": "studio", "service_name": "📸 Фотостудия", "slot_type": "studio"})
        await query.edit_message_text(
            "📅 <b>Бронирование студии</b>\n\nРаботаем 8:00–21:00.\nВыберите дату:",
            reply_markup=kb_dates("studio"), parse_mode="HTML")
        return BOOKING_DATE
    return STUDIO_MENU

async def booking_date_h(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if query.data == "go_home":
        context.user_data.clear(); await show_main(update, context, edit=True); return MAIN_MENU
    if query.data == "go_back":
        await query.edit_message_text(STUDIO_INFO, reply_markup=kb_studio(), parse_mode="HTML")
        return STUDIO_MENU
    sd = query.data.split("_", 2)[2]; context.user_data["booking_date"] = sd
    dd = datetime.strptime(sd, "%Y-%m-%d").strftime("%d.%m.%Y")
    await query.edit_message_text(
        f"📅 Дата: <b>{dd}</b>\n\n✅ — свободно   ❌ — занято\n\nВыберите время:",
        reply_markup=kb_times("studio", sd), parse_mode="HTML")
    return BOOKING_TIME

async def booking_time_h(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if query.data == "go_home":
        context.user_data.clear(); await show_main(update, context, edit=True); return MAIN_MENU
    if query.data == "go_back":
        await query.edit_message_text(
            "📅 <b>Бронирование</b>\n\nВыберите дату:",
            reply_markup=kb_dates("studio"), parse_mode="HTML")
        return BOOKING_DATE
    if query.data.startswith("time_busy_"):
        await query.answer("❌ Это время занято.", show_alert=True); return BOOKING_TIME
    st = query.data.split("_", 2)[2]; context.user_data["booking_time"] = st
    sd = context.user_data["booking_date"]
    dd = datetime.strptime(sd, "%Y-%m-%d").strftime("%d.%m.%Y")
    await query.edit_message_text(
        f"📅 Дата: <b>{dd}</b>  🕐 Время: <b>{st}</b>\n\n"
        "Укажите комментарий (необязательно):\n"
        "тип съёмки, нужен ли специалист, кол-во человек.\n\n"
        "Или введите <b>«—»</b> чтобы пропустить:",
        reply_markup=kb_back_home(), parse_mode="HTML")
    return BOOKING_COMMENT

async def booking_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["booking_comment"] = "" if text == "—" else text
    await update.message.reply_text("Введите ваше <b>имя</b>:", reply_markup=kb_home(), parse_mode="HTML")
    return FORM_NAME

# ── ПРОДАКШЕН ─────────────────────────────────────────────────────────────────
async def prod_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    data  = query.data
    if data == "go_home":
        context.user_data.clear(); await show_main(update, context, edit=True); return MAIN_MENU
    if data == "go_prod":
        await query.edit_message_text(
            "🎬 <b>Продакшен и контент</b>\n\nВыберите направление:",
            reply_markup=kb_prod(), parse_mode="HTML")
        return PROD_MENU
    if data.startswith("prod_") and data != "prod_apply":
        cat_key = data.replace("prod_", "")
        if cat_key in PROD_CATEGORIES:
            context.user_data.update({
                "prod_cat": cat_key,
                "service": f"prod_{cat_key}",
                "service_name": PROD_CATEGORIES[cat_key]["label"]
            })
            await query.edit_message_text(
                PROD_CATEGORIES[cat_key]["text"],
                reply_markup=kb_prod_detail(), parse_mode="HTML")
            return PROD_CATEGORY
    return PROD_MENU

async def prod_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    data  = query.data
    if data == "go_home":
        context.user_data.clear(); await show_main(update, context, edit=True); return MAIN_MENU
    if data == "go_prod":
        await query.edit_message_text(
            "🎬 <b>Продакшен и контент</b>\n\nВыберите направление:",
            reply_markup=kb_prod(), parse_mode="HTML")
        return PROD_MENU
    if data == "prod_apply":
        await query.edit_message_text(
            f"📩 <b>Заявка: {context.user_data.get('service_name','')}</b>\n\n"
            "Мы свяжемся и обсудим детали проекта.\n\n"
            "Введите ваше <b>имя</b>:",
            reply_markup=kb_home(), parse_mode="HTML")
        return FORM_NAME
    return PROD_CATEGORY

# ── КАСТИНГ ───────────────────────────────────────────────────────────────────
async def casting_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if len(text) < 2:
        await update.message.reply_text("⚠️ Укажите амплуа подробнее:", reply_markup=kb_home()); return CASTING_ROLE
    context.user_data["casting_role"] = text
    await update.message.reply_text(
        "Укажите <b>ссылку на портфолио</b> (необязательно).\n"
        "Или введите <b>«—»</b>:", reply_markup=kb_home(), parse_mode="HTML")
    return CASTING_PORTFOLIO

async def casting_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["casting_portfolio"] = "" if text == "—" else text
    await update.message.reply_text("Введите ваше <b>имя</b>:", reply_markup=kb_home(), parse_mode="HTML")
    return FORM_NAME

# ── ОБЩАЯ ФОРМА ───────────────────────────────────────────────────────────────
async def form_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Если это рассылка от админа — перехватываем
    if context.user_data.get("admin_broadcast"):
        return await broadcast_receive(update, context)
    text = update.message.text.strip()
    if len(text) < 2:
        await update.message.reply_text(
            "⚠️ Имя слишком короткое. Введите <b>имя</b> ещё раз:",
            reply_markup=kb_home(), parse_mode="HTML"); return FORM_NAME
    context.user_data["form_name"] = text
    await update.message.reply_text(
        f"Приятно познакомиться, <b>{text}</b>! 👋\n\nВведите ваш <b>номер телефона</b>:",
        reply_markup=kb_home(), parse_mode="HTML")
    return FORM_PHONE

async def form_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    if not validate_phone(phone):
        await update.message.reply_text(
            "⚠️ Некорректный номер. Введите <b>телефон</b> (минимум 10 цифр):",
            reply_markup=kb_home(), parse_mode="HTML"); return FORM_PHONE
    context.user_data["form_phone"]    = phone
    context.user_data["form_username"] = get_uname(update.effective_user)
    service      = context.user_data.get("service","")
    service_name = context.user_data.get("service_name","Услуга")
    s = (f"📋 <b>Проверьте данные заявки</b>\n\n"
         f"🔹 Услуга: {service_name}\n"
         f"🔹 Имя: {context.user_data['form_name']}\n"
         f"🔹 Телефон: {phone}\n"
         f"🔹 Telegram: {context.user_data['form_username']}\n")
    if service in ("studio","legal_consult"):
        d  = context.user_data.get("booking_date","")
        dd = datetime.strptime(d,"%Y-%m-%d").strftime("%d.%m.%Y") if d else "—"
        s += f"🔹 Дата: {dd}\n🔹 Время: {context.user_data.get('booking_time','—')}\n"
        if service == "studio" and context.user_data.get("booking_comment"):
            s += f"🔹 Комментарий: {context.user_data['booking_comment']}\n"
    elif service == "casting":
        s += f"🔹 Амплуа: {context.user_data.get('casting_role','—')}\n"
        if context.user_data.get("casting_portfolio"):
            s += f"🔹 Портфолио: {context.user_data['casting_portfolio']}\n"
    s += "\n📌 Для отправки необходимо дать согласие\nна обработку персональных данных:"
    await update.message.reply_text(s, reply_markup=kb_consent(), parse_mode="HTML")
    return FORM_CONSENT

async def form_consent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if query.data == "go_home":
        context.user_data.clear(); await show_main(update, context, edit=True); return MAIN_MENU
    if query.data != "consent_yes": return FORM_CONSENT
    uid          = update.effective_user.id
    service      = context.user_data.get("service","unknown")
    service_name = context.user_data.get("service_name","Услуга")
    name         = context.user_data.get("form_name","")
    phone        = context.user_data.get("form_phone","")
    username     = context.user_data.get("form_username","")
    additional   = {}
    if service in ("studio","legal_consult"):
        d = context.user_data.get("booking_date","")
        t = context.user_data.get("booking_time","")
        stype = "legal" if service == "legal_consult" else "studio"
        if is_slot_booked(stype, d, t):
            await query.edit_message_text(
                "⚠️ Это время уже <b>занято</b>.\n\nНачните заново и выберите другой слот.",
                reply_markup=kb_home(), parse_mode="HTML"); return MAIN_MENU
        save_booking(uid, stype, d, t, name, phone, username, context.user_data.get("booking_comment",""))
        additional = {"date": d, "time": t, "comment": context.user_data.get("booking_comment","")}
    elif service == "casting":
        additional = {"role": context.user_data.get("casting_role",""), "portfolio": context.user_data.get("casting_portfolio","")}
    else:
        additional = {"cat": context.user_data.get("prod_cat","")}
    save_application(uid, service, name, phone, username, additional)
    # Уведомление
    admin = (f"🔔 <b>НОВАЯ ЗАЯВКА — LEXX^</b>\n\n"
             f"📋 Услуга: <b>{service_name}</b>\n"
             f"👤 {name} | 📞 {phone} | {username} | 🆔{uid}\n")
    if service in ("studio","legal_consult"):
        d  = additional.get("date","")
        dd = datetime.strptime(d,"%Y-%m-%d").strftime("%d.%m.%Y") if d else "—"
        admin += f"📅 {dd}  🕐 {additional.get('time','—')}\n"
        if additional.get("comment"): admin += f"📝 {additional['comment']}\n"
    elif service == "casting":
        admin += f"🎭 {additional.get('role','—')}\n"
        if additional.get("portfolio"): admin += f"🔗 {additional['portfolio']}\n"
    else:
        admin += f"🗂 {additional.get('cat','—')}\n"
    admin += f"\n🕒 {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    await notify_admin(context, admin)
    await query.edit_message_text(
        "✅ <b>Заявка принята!</b>\n\n"
        "Мы свяжемся с вами в ближайшее время.\n\n"
        "Пока можно изучить другие направления 👇",
        reply_markup=kb_main(), parse_mode="HTML")
    context.user_data.clear()
    return MAIN_MENU

# ── СЛУЖЕБНЫЕ ─────────────────────────────────────────────────────────────────
async def go_home_any(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    context.user_data.clear(); await show_main(update, context, edit=True); return MAIN_MENU

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("admin_broadcast"):
        return await broadcast_receive(update, context)
    await update.message.reply_text(
        "🤔 Используйте кнопки меню.\nНажмите /start чтобы начать заново.",
        reply_markup=kb_home())

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Ошибка: %s", context.error, exc_info=context.error)

# ── ИНЛАЙН ────────────────────────────────────────────────────────────────────
async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = (update.inline_query.query or "").lower()
    items = [
        ("legal",  "⚖️ Юридические услуги",
         "Консультации · Документы · Досудебная подготовка",
         "⚖️ ЮРИДИЧЕСКИЕ УСЛУГИ LEXX^\n\n🗣 Консультация — 3 000 ₽/час\n📄 Документы — от 2 000 ₽\n🔍 Досудебная — от 3 000 ₽\n\n@lexx_agency_bot"),
        ("studio", "📸 Фотостудия",
         "Аренда · Подкаст · Фотограф · Рилсмейкер · Видеограф",
         "📸 ФОТОСТУДИЯ LEXX^\n\n🏠 Аренда — 2 000 ₽/ч\n🎙 Подкаст — от 5 000 ₽/ч\n📷 Фотограф — 3 000 ₽/ч\n🎬 Рилсмейкер — 1 500 ₽/ч\n🎥 Видеограф — 3 000 ₽/ч\n\n@lexx_agency_bot"),
        ("packages","🏖️ Пакеты сезона 2026",
         "Готовые решения для крымского бизнеса от 49 000 ₽",
         "🏖️ ПАКЕТЫ LEXX^ — СЕЗОН 2026\n\n💡 Старт (6 роликов) — 69 000 ₽\n⭐️ Флагман (8 роликов) — 89 000 ₽\n🚀 Максимум (12 роликов) — 119 000 ₽\n🌊 Экспресс 7 дней — 49 000 ₽\n🏨 Туристический хит — 99 000 ₽\n🍕 Ресторан в топе — 85 000 ₽\n🌅 Летний поток — 149 000 ₽\n🍷 Крымский бренд — 79 000 ₽\n\n@lexx_agency_bot"),
    ]
    results = []
    for key, title, desc, text in items:
        if q and q not in title.lower() and q not in desc.lower(): continue
        results.append(InlineQueryResultArticle(
            id=key, title=title, description=desc,
            input_message_content=InputTextMessageContent(message_text=text)))
    await update.inline_query.answer(results, cache_time=300)

# ── ЗАПУСК ────────────────────────────────────────────────────────────────────
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    # Напоминания — каждый день в 10:00
    # Требует: pip install "python-telegram-bot[job-queue]"
    if app.job_queue is not None:
        from datetime import time as dtime
        app.job_queue.run_daily(
            send_reminders,
            time=dtime(hour=10, minute=0),
            name="daily_reminders"
        )
        logger.info("Напоминания: активированы (10:00 ежедневно)")
    else:
        logger.warning("JobQueue недоступен — напоминания отключены. "
                       "Установите: pip install 'python-telegram-bot[job-queue]'")

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start",  cmd_start),
            CallbackQueryHandler(go_home_any, pattern="^go_home$"),
        ],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(main_router, pattern="^go_|^my_apps$"),
            ],
            LEGAL_MENU: [
                CallbackQueryHandler(legal_menu,
                    pattern="^legal_book$|^legal_form_doc$|^legal_form_analysis$|^go_home$"),
            ],
            LEGAL_DATE: [
                CallbackQueryHandler(legal_date, pattern="^date_legal_|^go_back$|^go_home$"),
            ],
            LEGAL_TIME: [
                CallbackQueryHandler(legal_time, pattern="^time_|^go_back$|^go_home$"),
            ],
            STUDIO_MENU: [
                CallbackQueryHandler(studio_menu, pattern="^studio_book$|^go_home$"),
            ],
            BOOKING_DATE: [
                CallbackQueryHandler(booking_date_h, pattern="^date_studio_|^go_back$|^go_home$"),
            ],
            BOOKING_TIME: [
                CallbackQueryHandler(booking_time_h, pattern="^time_|^go_back$|^go_home$"),
            ],
            BOOKING_COMMENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, booking_comment),
                CallbackQueryHandler(go_home_any, pattern="^go_home$"),
            ],
            PROD_MENU: [
                CallbackQueryHandler(prod_menu, pattern="^prod_|^go_prod$|^go_home$"),
            ],
            PROD_CATEGORY: [
                CallbackQueryHandler(prod_category, pattern="^prod_apply$|^go_prod$|^go_home$"),
            ],
            CASTING_ROLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, casting_role),
                CallbackQueryHandler(go_home_any, pattern="^go_home$"),
            ],
            CASTING_PORTFOLIO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, casting_portfolio),
                CallbackQueryHandler(go_home_any, pattern="^go_home$"),
            ],
            FORM_NAME: [
                MessageHandler(filters.ALL & ~filters.COMMAND, form_name),
                CallbackQueryHandler(go_home_any, pattern="^go_home$"),
            ],
            FORM_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, form_phone),
                CallbackQueryHandler(go_home_any, pattern="^go_home$"),
            ],
            FORM_CONSENT: [
                CallbackQueryHandler(form_consent, pattern="^consent_yes$|^go_home$"),
            ],
            BROADCAST_TEXT: [
                MessageHandler(filters.ALL & ~filters.COMMAND, broadcast_receive),
                CallbackQueryHandler(admin_callback, pattern="^adm_cancel_broadcast$"),
            ],
        },
        fallbacks=[
            CommandHandler("start",  cmd_start),
            CommandHandler("cancel", cmd_cancel),
            CallbackQueryHandler(go_home_any, pattern="^go_home$"),
            MessageHandler(filters.ALL, unknown),
        ],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^adm_"))
    app.add_handler(conv)
    app.add_handler(InlineQueryHandler(inline_query))
    app.add_error_handler(on_error)

    logger.info("Бот LEXX^ v5.0 запущен 🚀")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
