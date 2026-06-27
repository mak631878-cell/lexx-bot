"""
Telegram-бот LEXX^  |  Версия 4.0
Структура меню:
  ⚖️ Юридическая помощь  → прайс → запись (с выбором даты)
  📸 Фотостудия          → прайс → бронирование
  🎬 Продакшен           → подменю: Фото / Видео / SMM / Дизайн / Маркетинг → заявка
  🎭 Кастинг             → заявка
  📢 Рассылка            → только для админа
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
    filters, ContextTypes
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
 # Юридическая
 LEGAL_MENU, LEGAL_DATE, LEGAL_TIME,
 # Студия
 STUDIO_MENU, BOOKING_DATE, BOOKING_TIME, BOOKING_COMMENT,
 # Продакшен → подменю → заявка
 PROD_MENU, PROD_CATEGORY,
 # Кастинг
 CASTING_ROLE, CASTING_PORTFOLIO,
 # Общая форма
 FORM_NAME, FORM_PHONE, FORM_CONSENT,
 # Рассылка
 BROADCAST_TEXT) = range(16)

# ── БД ────────────────────────────────────────────────────────────────────────
DB_PATH = os.environ.get("DB_PATH", "lexx_bot.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS bookings(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, slot_type TEXT, date TEXT, time TEXT,
        name TEXT, phone TEXT, username TEXT, comment TEXT,
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

def register_user(user_id: int, username: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT OR IGNORE INTO users(user_id, username) VALUES(?,?)",
                 (user_id, username))
    conn.commit(); conn.close()

def get_all_users():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT user_id FROM users").fetchall()
    conn.close()
    return [r[0] for r in rows]

def is_slot_booked(slot_type: str, date: str, time: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    r = conn.execute(
        "SELECT id FROM bookings WHERE slot_type=? AND date=? AND time=?",
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

# ── УТИЛИТЫ ───────────────────────────────────────────────────────────────────
def fmt(p: int) -> str:
    return f"{p:,}".replace(",", " ") + " ₽"

def validate_phone(p: str) -> bool:
    return len(re.sub(r"\D", "", p)) >= 10

def get_uname(user) -> str:
    return f"@{user.username}" if user.username else f"ID:{user.id}"

async def notify_admin(context, text: str):
    try:
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=text, parse_mode="HTML")
    except Exception as e:
        logger.error("Ошибка уведомления: %s", e)

# ── ТЕКСТЫ МЕНЮ ───────────────────────────────────────────────────────────────
WELCOME = (
    "👋 Добро пожаловать в <b>LEXX^</b>!\n\n"
    "Мы — многофункциональное креативное агентство в Крыму.\n"
    "Выберите нужное направление:"
)

# ─── ЮРИДИКА ──────────────────────────────────────────────────────────────────
LEGAL_INFO = (
    "⚖️ <b>Юридическая помощь LEXX^</b>\n\n"
    "Мы оказываем полный спектр юридических услуг.\n"
    "Мы <b>не адвокаты</b> — не ходим в суд вместо вас,\n"
    "но берём на себя всю подготовку и стратегию.\n\n"

    "━━━━━━━━━━━━━━━━━━━━━━\n\n"

    "🗣 <b>1. Устная консультация</b>\n"
    "    <b>3 000 ₽ / час</b>\n\n"
    "   • Разбор ситуации: гражданские, трудовые,\n"
    "     семейные, жилищные споры, долги, недвижимость\n"
    "   • Анализ перспектив и судебных рисков\n"
    "   • Разъяснение норм закона под вашу ситуацию\n"
    "   • Пошаговый план: что делать, куда идти,\n"
    "     какие документы собирать\n"
    "   • Экспресс-анализ ваших документов\n\n"

    "━━━━━━━━━━━━━━━━━━━━━━\n\n"

    "📄 <b>2. Составление документов</b>\n"
    "    <b>от 2 000 ₽ / документ</b>\n\n"
    "   Договоры (купли-продажи, аренды, займа, дарения,\n"
    "   найма, подряда, оказания услуг)\n"
    "   Претензии, исковые заявления, возражения на иск\n"
    "   Жалобы: апелляция, кассация, частные жалобы\n"
    "   Заявления в полицию, прокуратуру, Роспотребнадзор,\n"
    "   Жилинспекцию и другие госорганы\n"
    "   Требования о возмещении ущерба\n\n"

    "━━━━━━━━━━━━━━━━━━━━━━\n\n"

    "🔍 <b>3. Досудебная подготовка и аналитика</b>\n"
    "    <b>от 3 000 ₽</b> (индивидуально)\n\n"
    "   • Правовая экспертиза договоров —\n"
    "     ищем «опасные» пункты\n"
    "   • Сбор доказательной базы и пакета для суда\n"
    "   • Расчёт неустоек, пеней, % по ст. 395 ГК РФ\n"
    "   • Ответ на чужую претензию или иск\n\n"

    "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "Выберите действие:"
)

# ─── ФОТОСТУДИЯ ───────────────────────────────────────────────────────────────
STUDIO_INFO = (
    "📸 <b>Фотостудия LEXX^</b>\n\n"
    "Современное пространство для съёмок.\n"
    "Снимайте сами или закажите специалиста — всё в одном месте.\n\n"

    "━━━━━━━━━━━━━━━━━━━━━━\n\n"

    "🏠 <b>Аренда студии</b>\n"
    "   <b>2 000 ₽ / час</b>\n"
    "   Зал + свет + базовый реквизит\n"
    "   Минимальный заказ — 1 час\n\n"

    "🎙 <b>Пакет «Подкаст»</b>\n"
    "   <b>от 5 000 ₽ / час</b>\n"
    "   Зал + профессиональный микрофон + видеосъёмка\n"
    "   ⚠️ Минимум — <b>2 часа</b>\n"
    "   Идеально для интервью, YouTube, подкастов\n\n"

    "━━━━━━━━━━━━━━━━━━━━━━\n\n"

    "👥 <b>Специалисты (на съёмку)</b>\n\n"

    "📷 Фотограф — <b>3 000 ₽ / час</b>\n"
    "   Съёмка + базовый отбор кадров\n\n"

    "🎬 Рилсмейкер — <b>1 500 ₽ / час</b>\n"
    "   Съёмка и монтаж Reels / Shorts / TikTok\n"
    "   ✅ Количество видео <b>не ограничено</b>\n\n"

    "🎥 Видеограф — <b>3 000 ₽ / час</b>\n"
    "   Рекламные ролики, корпоративное видео,\n"
    "   мероприятия\n\n"

    "━━━━━━━━━━━━━━━━━━━━━━\n\n"

    "💡 <b>Популярные комбо:</b>\n"
    "   Студия 2ч + Рилсмейкер 2ч = <b>7 000 ₽</b>\n"
    "   Студия 2ч + Фотограф 2ч = <b>10 000 ₽</b>\n\n"

    "Работаем с 8:00 до 21:00, шаг — 1 час.\n"
    "Нажмите кнопку ниже, чтобы забронировать:"
)

# ─── ПРОДАКШЕН ────────────────────────────────────────────────────────────────
PROD_CATEGORIES = {
    "photo": {
        "label": "📷 Фотосъёмка",
        "text": (
            "📷 <b>Фотосъёмка</b>\n\n"
            "Профессиональная съёмка для бизнеса.\n"
            "Все работы — с ретушью и отбором.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"• Фуд-съёмка (до 20 блюд + ретушь) — <b>{fmt(45_000)}</b>\n"
            f"• Предметная съёмка (до 30 предметов) — <b>{fmt(35_000)}</b>\n"
            f"• Съёмка команды / сотрудников (до 15 чел.) — <b>{fmt(30_000)}</b>\n"
            f"• Репортажная съёмка события (до 8 ч.) — <b>{fmt(55_000)}</b>\n"
            f"• Лукбук — fashion / бренд (до 10 образов) — <b>{fmt(90_000)}</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "💬 <i>Точная стоимость — после брифинга.\n"
            "Оставьте заявку — рассчитаем и пришлём КП.</i>"
        )
    },
    "video": {
        "label": "🎬 Видеопроизводство",
        "text": (
            "🎬 <b>Видеопроизводство</b>\n\n"
            "Полный цикл: идея → сценарий → съёмка → монтаж → файл.\n"
            "Всё под ключ — без вашего участия на производстве.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"• Рекламный ролик 15–60 сек — <b>{fmt(180_000)}</b>\n"
            f"• Корпоративный фильм 3–7 мин — <b>{fmt(280_000)}</b>\n"
            f"• Рилс / Shorts (1 шт.) — <b>{fmt(35_000)}</b>\n"
            f"• Пакет рилс × 4 шт. — <b>{fmt(110_000)}</b>\n"
            f"• Тизер / анонс события 30–45 сек — <b>{fmt(70_000)}</b>\n"
            f"• Видео-кейс / отзыв клиента — <b>{fmt(55_000)}</b>\n"
            f"• Мероприятие — полный день (highlights) — <b>{fmt(150_000)}</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "💬 <i>Производство — 3 до 14 рабочих дней.\n"
            "Оставьте заявку — обсудим детали и дедлайн.</i>"
        )
    },
    "smm": {
        "label": "📱 SMM",
        "text": (
            "📱 <b>SMM-услуги</b>\n\n"
            "Системная работа с соцсетями.\n"
            "Instagram, VK, Telegram, TikTok.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"• Аудит аккаунта (PDF-отчёт) — <b>{fmt(18_000)}</b>\n"
            f"• Оформление профиля под ключ — <b>{fmt(22_000)}</b>\n"
            f"• Контент-стратегия (ЦА, рубрики, KPI) — <b>{fmt(35_000)}</b>\n"
            f"• Сценарии для Reels × 8 шт. — <b>{fmt(24_000)}</b>\n"
            f"• Ведение Telegram-канала (1 мес.) — <b>{fmt(40_000)}</b>\n"
            f"• Экспресс-рилс под ключ (1 шт.) — <b>{fmt(12_000)}</b>\n"
            f"• Пакет Reels × 4 шт. — <b>{fmt(42_000)}</b>\n"
            f"• Reels-марафон × 12 роликов / мес. — <b>{fmt(95_000)}</b>\n"
            f"• Комьюнити-менеджмент (1 мес.) — <b>{fmt(28_000)}</b>\n"
            f"• Таргет ВКонтакте — быстрый старт — <b>{fmt(35_000)}</b>\n"
            f"• Продвижение через Reels — органика (1 мес.) — <b>{fmt(45_000)}</b>\n"
            f"• Ежемесячный отчёт + аналитика — <b>{fmt(12_000)}</b>\n"
            f"• Реанимация аккаунта после простоя — <b>{fmt(32_000)}</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "💬 <i>Один менеджер на весь проект.\n"
            "Рекламный бюджет — отдельно, только по факту расхода.</i>"
        )
    },
    "design": {
        "label": "🎨 Дизайн",
        "text": (
            "🎨 <b>Дизайн</b>\n\n"
            "От брендбука до баннеров — всё для узнаваемого визуала.\n"
            "Исходники — ваши. Правки до 3 итераций включены.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"• Фирменный стиль — брендбук lite — <b>{fmt(120_000)}</b>\n"
            f"• Дизайн упаковки (1 SKU) — <b>{fmt(65_000)}</b>\n"
            f"• Шаблоны для соцсетей (15 шт.) — <b>{fmt(45_000)}</b>\n"
            f"• Презентация до 20 слайдов — <b>{fmt(40_000)}</b>\n"
            f"• Баннеры — пакет 8 форматов — <b>{fmt(30_000)}</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "💬 <i>Оставьте заявку — пришлём портфолио\n"
            "и обсудим стиль.</i>"
        )
    },
    "marketing": {
        "label": "📣 Реклама и маркетинг",
        "text": (
            "📣 <b>Реклама и маркетинг</b>\n\n"
            "Запускаем трафик туда, где уже есть доверие.\n"
            "Без слива бюджета на холодную аудиторию.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"• Таргет ВКонтакте / myTarget (1 мес.) — <b>{fmt(55_000)}</b>\n"
            f"• Яндекс.Директ (1 мес.) — <b>{fmt(65_000)}</b>\n"
            f"• SMM-стратегия на 3 мес. — <b>{fmt(80_000)}</b>\n"
            f"• Ведение соцсетей — 1 платформа (1 мес.) — <b>{fmt(45_000)}</b>\n"
            f"• Email-рассылки (стратегия + 4 письма) — <b>{fmt(55_000)}</b>\n"
            f"• SEO-аудит сайта — <b>{fmt(40_000)}</b>\n"
            f"• Контент-план на 3 месяца — <b>{fmt(30_000)}</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "💬 <i>Рекламный бюджет — отдельно, только по факту.\n"
            "Ведём отчётность в реальном времени.</i>"
        )
    },
    "packages": {
        "label": "🏖️ Пакеты сезона 2026",
        "text": (
            "🏖️ <b>Пакеты — Крымский сезон 2026</b>\n\n"
            "Готовые решения для крымского бизнеса.\n"
            "Всё включено: съёмка, монтаж, публикация.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💡 <b>Контент-основа — старт</b> — <b>{fmt(69_000)}</b>\n"
            "   6 роликов, адаптация под VK / Reels / Shorts\n\n"
            f"⭐ <b>Контент под ключ — ФЛАГМАН</b> — <b>{fmt(89_000)}</b>\n"
            "   8 роликов, смыслы, стратегия, рекомендации\n\n"
            f"🚀 <b>Контент + заявки — максимум</b> — <b>{fmt(119_000)}</b>\n"
            "   12 роликов, воронка, консультация по продажам\n\n"
            f"🌊 <b>Старт сезона (экспресс, 7 дней)</b> — <b>{fmt(49_000)}</b>\n"
            "   Аудит + оформление + 4 сезонных рилс\n\n"
            f"🏨 <b>Туристический хит</b> — <b>{fmt(99_000)}</b>\n"
            "   8 роликов, фото 20 кадров, Stories, VK+Instagram\n\n"
            f"🍕 <b>Ресторан в топе</b> — <b>{fmt(85_000)}</b>\n"
            "   8 фуд-роликов, фотосессия 15 блюд, геометки\n\n"
            f"🌅 <b>Летний поток — максимум</b> — <b>{fmt(149_000)}</b>\n"
            "   12 роликов/мес., таргет, воронка, аналитика\n\n"
            f"🍷 <b>Крымский бренд</b> — <b>{fmt(79_000)}</b>\n"
            "   6 роликов с историей, лукбук, интеграция в паблики\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "💬 <i>Пакеты адаптируются под вашу нишу.\n"
            "Оставьте заявку — составим индивидуальное предложение.</i>"
        )
    },
}

# ── КЛАВИАТУРЫ ────────────────────────────────────────────────────────────────
def kb_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚖️ Юридическая помощь",       callback_data="go_legal")],
        [InlineKeyboardButton("📸 Фотостудия",               callback_data="go_studio")],
        [InlineKeyboardButton("🎬 Продакшен и контент",      callback_data="go_prod")],
        [InlineKeyboardButton("🎭 Кастинг",                  callback_data="go_casting")],
    ])

def kb_legal():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Записаться на консультацию", callback_data="legal_book")],
        [InlineKeyboardButton("📄 Заявка на документ",         callback_data="legal_form_doc")],
        [InlineKeyboardButton("🔍 Досудебная подготовка",      callback_data="legal_form_analysis")],
        [InlineKeyboardButton("🏠 Главное меню",               callback_data="go_home")],
    ])

def kb_studio():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Забронировать студию",  callback_data="studio_book")],
        [InlineKeyboardButton("🏠 Главное меню",          callback_data="go_home")],
    ])

def kb_prod():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📷 Фотосъёмка",            callback_data="prod_photo")],
        [InlineKeyboardButton("🎬 Видеопроизводство",     callback_data="prod_video")],
        [InlineKeyboardButton("📱 SMM",                   callback_data="prod_smm")],
        [InlineKeyboardButton("🎨 Дизайн",               callback_data="prod_design")],
        [InlineKeyboardButton("📣 Реклама и маркетинг",  callback_data="prod_marketing")],
        [InlineKeyboardButton("🏖️ Пакеты сезона 2026",   callback_data="prod_packages")],
        [InlineKeyboardButton("🏠 Главное меню",          callback_data="go_home")],
    ])

def kb_prod_detail():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📩 Оставить заявку",  callback_data="prod_apply")],
        [InlineKeyboardButton("⬅️ Назад",            callback_data="go_prod")],
        [InlineKeyboardButton("🏠 Главное меню",     callback_data="go_home")],
    ])

def kb_home():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Главное меню", callback_data="go_home")]
    ])

def kb_back_home():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Назад",        callback_data="go_back"),
        InlineKeyboardButton("🏠 Главное меню", callback_data="go_home"),
    ]])

def kb_consent():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Даю согласие на обработку персональных данных",
                              callback_data="consent_yes")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="go_home")],
    ])

def kb_dates(slot_type: str):
    """Календарь на 30 дней"""
    today = datetime.now(); buttons = []; row = []
    for i in range(30):
        d   = today + timedelta(days=i)
        lbl = d.strftime("%d.%m") + (" (сег.)" if i == 0 else "")
        cb  = f"date_{slot_type}_{d.strftime('%Y-%m-%d')}"
        row.append(InlineKeyboardButton(lbl, callback_data=cb))
        if len(row) == 3: buttons.append(row); row = []
    if row: buttons.append(row)
    buttons.append([
        InlineKeyboardButton("⬅️ Назад",        callback_data="go_back"),
        InlineKeyboardButton("🏠 Главное меню", callback_data="go_home"),
    ])
    return InlineKeyboardMarkup(buttons)

def kb_times(slot_type: str, selected_date: str):
    """Временные слоты 8–21"""
    buttons = []; row = []
    for h in range(8, 22):
        ts  = f"{h:02d}:00"
        busy = is_slot_booked(slot_type, selected_date, ts)
        lbl  = f"❌ {ts}" if busy else f"✅ {ts}"
        cb   = f"time_busy_{ts}" if busy else f"time_{slot_type}_{ts}"
        row.append(InlineKeyboardButton(lbl, callback_data=cb))
        if len(row) == 3: buttons.append(row); row = []
    if row: buttons.append(row)
    buttons.append([
        InlineKeyboardButton("⬅️ Назад",        callback_data="go_back"),
        InlineKeyboardButton("🏠 Главное меню", callback_data="go_home"),
    ])
    return InlineKeyboardMarkup(buttons)

# ── ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ───────────────────────────────────────────────────
async def show_main(update: Update, context: ContextTypes.DEFAULT_TYPE, edit=False):
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

async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /broadcast — только для администратора"""
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔️ У вас нет доступа к этой команде.")
        return ConversationHandler.END
    await update.message.reply_text(
        "📢 <b>Рассылка</b>\n\n"
        "Введите текст сообщения, которое получат все пользователи бота.\n"
        "Поддерживается HTML-форматирование: <b>жирный</b>, <i>курсив</i>, <code>код</code>.\n\n"
        "Для отмены напишите /cancel",
        parse_mode="HTML")
    return BROADCAST_TEXT

async def broadcast_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получаем текст рассылки и рассылаем"""
    text = update.message.text.strip()
    if not text:
        await update.message.reply_text("⚠️ Пустое сообщение. Введите текст рассылки:")
        return BROADCAST_TEXT
    users = get_all_users()
    sent = 0; failed = 0
    status_msg = await update.message.reply_text(
        f"⏳ Рассылка запущена...\nПолучателей: {len(users)}")
    for uid in users:
        try:
            await context.bot.send_message(chat_id=uid, text=text, parse_mode="HTML")
            sent += 1
        except Exception:
            failed += 1
    await status_msg.edit_text(
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"📤 Отправлено: {sent}\n"
        f"❌ Не доставлено: {failed}\n"
        f"👥 Всего в базе: {len(users)}",
        parse_mode="HTML")
    return ConversationHandler.END

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Действие отменено.")
    return ConversationHandler.END

# ── ГЛАВНОЕ МЕНЮ — РОУТЕР ─────────────────────────────────────────────────────
async def main_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    data  = query.data

    if data == "go_home":
        context.user_data.clear()
        await show_main(update, context, edit=True)
        return MAIN_MENU

    if data == "go_legal":
        await query.edit_message_text(LEGAL_INFO, reply_markup=kb_legal(), parse_mode="HTML")
        return LEGAL_MENU

    if data == "go_studio":
        await query.edit_message_text(STUDIO_INFO, reply_markup=kb_studio(), parse_mode="HTML")
        return STUDIO_MENU

    if data == "go_prod":
        await query.edit_message_text(
            "🎬 <b>Продакшен и контент</b>\n\n"
            "Выберите направление — покажем цены\n"
            "и поможем оставить заявку:",
            reply_markup=kb_prod(), parse_mode="HTML")
        return PROD_MENU

    if data == "go_casting":
        context.user_data.update({"service": "casting", "service_name": "🎭 Кастинг"})
        await query.edit_message_text(
            "🎭 <b>Заявка на кастинг</b>\n\n"
            "Заполните анкету — рассмотрим и свяжемся.\n\n"
            "Укажите ваше <b>амплуа / роль</b>\n"
            "(например: актёр, модель, ведущий, диктор):",
            reply_markup=kb_back_home(), parse_mode="HTML")
        return CASTING_ROLE

    return MAIN_MENU

# ── ЮРИДИКА ───────────────────────────────────────────────────────────────────
async def legal_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    data  = query.data

    if data == "go_home":
        context.user_data.clear(); await show_main(update, context, edit=True); return MAIN_MENU

    # Запись на консультацию — выбор даты
    if data == "legal_book":
        context.user_data.update({
            "service": "legal_consult",
            "service_name": "⚖️ Консультация",
            "slot_type": "legal"
        })
        await query.edit_message_text(
            "📅 <b>Запись на консультацию</b>\n\n"
            "Выберите удобную <b>дату</b>:",
            reply_markup=kb_dates("legal"), parse_mode="HTML")
        return LEGAL_DATE

    # Заявка на документ
    if data == "legal_form_doc":
        context.user_data.update({
            "service": "legal_docs",
            "service_name": "📄 Составление документа"
        })
        await query.edit_message_text(
            "📄 <b>Заявка на составление документа</b>\n\n"
            "Опишите, какой документ вам нужен,\n"
            "после сбора данных мы свяжемся и рассчитаем стоимость.\n\n"
            "Введите ваше <b>имя</b>:",
            reply_markup=kb_home(), parse_mode="HTML")
        return FORM_NAME

    # Заявка на досудебную подготовку
    if data == "legal_form_analysis":
        context.user_data.update({
            "service": "legal_analysis",
            "service_name": "🔍 Досудебная подготовка"
        })
        await query.edit_message_text(
            "🔍 <b>Досудебная подготовка и аналитика</b>\n\n"
            "Стоимость рассчитывается индивидуально.\n"
            "Оставьте заявку — юрист свяжется и уточнит детали.\n\n"
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
    parts = query.data.split("_", 2)   # date_legal_YYYY-MM-DD
    sd = parts[2]; context.user_data["booking_date"] = sd
    dd = datetime.strptime(sd, "%Y-%m-%d").strftime("%d.%m.%Y")
    await query.edit_message_text(
        f"📅 Дата: <b>{dd}</b>\n\n✅ — свободно   ❌ — занято\n\nВыберите <b>время</b>:",
        reply_markup=kb_times("legal", sd), parse_mode="HTML")
    return LEGAL_TIME

async def legal_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if query.data == "go_home":
        context.user_data.clear(); await show_main(update, context, edit=True); return MAIN_MENU
    if query.data == "go_back":
        sd = context.user_data.get("booking_date","")
        await query.edit_message_text(
            "📅 <b>Запись на консультацию</b>\n\nВыберите <b>дату</b>:",
            reply_markup=kb_dates("legal"), parse_mode="HTML")
        return LEGAL_DATE
    if query.data.startswith("time_busy_"):
        await query.answer("❌ Это время уже занято. Выберите другое.", show_alert=True)
        return LEGAL_TIME
    # time_legal_HH:MM
    parts = query.data.split("_", 2); st = parts[2]
    context.user_data["booking_time"] = st
    sd = context.user_data["booking_date"]
    dd = datetime.strptime(sd, "%Y-%m-%d").strftime("%d.%m.%Y")
    await query.edit_message_text(
        f"📅 Дата: <b>{dd}</b>\n🕐 Время: <b>{st}</b>\n\n"
        "Отлично! Осталось заполнить контактные данные.\n\n"
        "Введите ваше <b>имя</b>:",
        reply_markup=kb_home(), parse_mode="HTML")
    return FORM_NAME

# ── ФОТОСТУДИЯ ────────────────────────────────────────────────────────────────
async def studio_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if query.data == "go_home":
        context.user_data.clear(); await show_main(update, context, edit=True); return MAIN_MENU
    if query.data == "studio_book":
        context.user_data.update({
            "service": "studio",
            "service_name": "📸 Фотостудия",
            "slot_type": "studio"
        })
        await query.edit_message_text(
            "📅 <b>Бронирование фотостудии</b>\n\n"
            "Работаем с 8:00 до 21:00, шаг — 1 час.\n\n"
            "Выберите <b>дату</b>:",
            reply_markup=kb_dates("studio"), parse_mode="HTML")
        return BOOKING_DATE
    return STUDIO_MENU

async def booking_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if query.data == "go_home":
        context.user_data.clear(); await show_main(update, context, edit=True); return MAIN_MENU
    if query.data == "go_back":
        await query.edit_message_text(STUDIO_INFO, reply_markup=kb_studio(), parse_mode="HTML")
        return STUDIO_MENU
    parts = query.data.split("_", 2); sd = parts[2]
    context.user_data["booking_date"] = sd
    dd = datetime.strptime(sd, "%Y-%m-%d").strftime("%d.%m.%Y")
    await query.edit_message_text(
        f"📅 Дата: <b>{dd}</b>\n\n✅ — свободно   ❌ — занято\n\nВыберите <b>время</b>:",
        reply_markup=kb_times("studio", sd), parse_mode="HTML")
    return BOOKING_TIME

async def booking_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if query.data == "go_home":
        context.user_data.clear(); await show_main(update, context, edit=True); return MAIN_MENU
    if query.data == "go_back":
        await query.edit_message_text(
            "📅 <b>Бронирование</b>\n\nВыберите <b>дату</b>:",
            reply_markup=kb_dates("studio"), parse_mode="HTML")
        return BOOKING_DATE
    if query.data.startswith("time_busy_"):
        await query.answer("❌ Это время занято. Выберите другое.", show_alert=True)
        return BOOKING_TIME
    parts = query.data.split("_", 2); st = parts[2]
    context.user_data["booking_time"] = st
    sd = context.user_data["booking_date"]
    dd = datetime.strptime(sd, "%Y-%m-%d").strftime("%d.%m.%Y")
    await query.edit_message_text(
        f"📅 Дата: <b>{dd}</b>\n🕐 Время: <b>{st}</b>\n\n"
        "Укажите <b>комментарий</b> (необязательно):\n"
        "тип съёмки, нужен ли специалист, кол-во человек.\n\n"
        "Или введите <b>«—»</b> чтобы пропустить:",
        reply_markup=kb_back_home(), parse_mode="HTML")
    return BOOKING_COMMENT

async def booking_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["booking_comment"] = "" if text == "—" else text
    await update.message.reply_text(
        "Введите ваше <b>имя</b>:", reply_markup=kb_home(), parse_mode="HTML")
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

    if data.startswith("prod_") and not data == "prod_apply":
        cat_key = data.replace("prod_", "")
        if cat_key in PROD_CATEGORIES:
            context.user_data["prod_cat"] = cat_key
            context.user_data["service"]  = f"prod_{cat_key}"
            context.user_data["service_name"] = PROD_CATEGORIES[cat_key]["label"]
            await query.edit_message_text(
                PROD_CATEGORIES[cat_key]["text"],
                reply_markup=kb_prod_detail(), parse_mode="HTML")
            return PROD_CATEGORY

    if data == "prod_apply":
        await query.edit_message_text(
            f"📩 <b>Заявка: {context.user_data.get('service_name','')}</b>\n\n"
            "Введите ваше <b>имя</b>:",
            reply_markup=kb_home(), parse_mode="HTML")
        return FORM_NAME

    return PROD_MENU

async def prod_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик внутри просмотра категории продакшена"""
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
            "Введите ваше <b>имя</b>:",
            reply_markup=kb_home(), parse_mode="HTML")
        return FORM_NAME

    return PROD_CATEGORY

# ── КАСТИНГ ───────────────────────────────────────────────────────────────────
async def casting_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if len(text) < 2:
        await update.message.reply_text(
            "⚠️ Слишком коротко. Укажите <b>амплуа</b> подробнее:",
            reply_markup=kb_home(), parse_mode="HTML"); return CASTING_ROLE
    context.user_data["casting_role"] = text
    await update.message.reply_text(
        "Укажите <b>ссылку на портфолио</b> (необязательно).\n"
        "Или введите <b>«—»</b> чтобы пропустить:",
        reply_markup=kb_home(), parse_mode="HTML")
    return CASTING_PORTFOLIO

async def casting_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["casting_portfolio"] = "" if text == "—" else text
    await update.message.reply_text(
        "Введите ваше <b>имя</b>:", reply_markup=kb_home(), parse_mode="HTML")
    return FORM_NAME

# ── ОБЩАЯ ФОРМА ───────────────────────────────────────────────────────────────
async def form_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            "⚠️ Некорректный номер.\nВведите <b>телефон</b> (минимум 10 цифр):",
            reply_markup=kb_home(), parse_mode="HTML"); return FORM_PHONE
    context.user_data["form_phone"]    = phone
    context.user_data["form_username"] = get_uname(update.effective_user)
    service      = context.user_data.get("service", "")
    service_name = context.user_data.get("service_name", "Услуга")

    s = (f"📋 <b>Проверьте данные заявки</b>\n\n"
         f"🔹 Услуга: {service_name}\n"
         f"🔹 Имя: {context.user_data['form_name']}\n"
         f"🔹 Телефон: {phone}\n"
         f"🔹 Telegram: {context.user_data['form_username']}\n")

    if service in ("studio", "legal_consult"):
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

    if service in ("studio", "legal_consult"):
        d    = context.user_data.get("booking_date","")
        t    = context.user_data.get("booking_time","")
        stype = "legal" if service == "legal_consult" else "studio"
        if is_slot_booked(stype, d, t):
            await query.edit_message_text(
                "⚠️ Это время уже <b>занято</b>.\n\nПожалуйста, начните заново и выберите другой слот.",
                reply_markup=kb_home(), parse_mode="HTML"); return MAIN_MENU
        save_booking(uid, stype, d, t, name, phone, username,
                     context.user_data.get("booking_comment",""))
        additional = {"date": d, "time": t,
                      "comment": context.user_data.get("booking_comment","")}

    elif service == "casting":
        additional = {"role":      context.user_data.get("casting_role",""),
                      "portfolio": context.user_data.get("casting_portfolio","")}
    else:
        additional = {"cat": context.user_data.get("prod_cat","")}

    save_application(uid, service, name, phone, username, additional)

    # Уведомление администратору
    admin = (f"🔔 <b>НОВАЯ ЗАЯВКА — LEXX^</b>\n\n"
             f"📋 Услуга: <b>{service_name}</b>\n"
             f"👤 {name} | 📞 {phone} | 💬 {username}\n🆔 {uid}\n")
    if service in ("studio","legal_consult"):
        d  = additional.get("date","")
        dd = datetime.strptime(d,"%Y-%m-%d").strftime("%d.%m.%Y") if d else "—"
        admin += f"📅 {dd}  🕐 {additional.get('time','—')}\n"
        if additional.get("comment"): admin += f"📝 {additional['comment']}\n"
    elif service == "casting":
        admin += f"🎭 Амплуа: {additional.get('role','—')}\n"
        if additional.get("portfolio"): admin += f"🔗 {additional['portfolio']}\n"
    else:
        admin += f"🗂 Категория: {additional.get('cat','—')}\n"
    admin += f"\n🕒 {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    await notify_admin(context, admin)

    await query.edit_message_text(
        "✅ <b>Заявка принята!</b>\n\n"
        "Мы свяжемся с вами в ближайшее время. 🙌\n\n"
        "Если появятся вопросы — возвращайтесь в меню:",
        reply_markup=kb_main(), parse_mode="HTML")
    context.user_data.clear()
    return MAIN_MENU

# ── СЛУЖЕБНЫЕ ─────────────────────────────────────────────────────────────────
async def go_home_any(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    context.user_data.clear()
    await show_main(update, context, edit=True)
    return MAIN_MENU

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤔 Используйте кнопки меню.\nНажмите /start чтобы начать заново.",
        reply_markup=kb_home())

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Ошибка: %s", context.error, exc_info=context.error)

# ── ИНЛАЙН-РЕЖИМ ──────────────────────────────────────────────────────────────
async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = (update.inline_query.query or "").lower()
    items = [
        ("legal",  "⚖️ Юридические услуги",
         "Консультации от 3 000 ₽/ч | Документы от 2 000 ₽ | Досудебная подготовка от 3 000 ₽",
         "⚖️ ЮРИДИЧЕСКИЕ УСЛУГИ LEXX^\n\n"
         "🗣 Консультация — 3 000 ₽/час\n"
         "📄 Составление документов — от 2 000 ₽\n"
         "🔍 Досудебная подготовка — от 3 000 ₽\n\n"
         "Запись: @lexx_agency_bot"),
        ("studio", "📸 Фотостудия",
         "Аренда 2 000 ₽/ч | Подкаст от 5 000 ₽/ч | Специалисты от 1 500 ₽/ч",
         "📸 ФОТОСТУДИЯ LEXX^\n\n"
         "🏠 Аренда — 2 000 ₽/час\n"
         "🎙 Подкаст — от 5 000 ₽/час (мин. 2 часа)\n\n"
         "👥 Специалисты:\n"
         "📷 Фотограф — 3 000 ₽/час\n"
         "🎬 Рилсмейкер — 1 500 ₽/час (без ограничений)\n"
         "🎥 Видеограф — 3 000 ₽/час\n\n"
         "Бронирование: @lexx_agency_bot"),
        ("packages","🏖️ Пакеты сезона 2026",
         "Готовые решения для крымского бизнеса от 49 000 ₽",
         "🏖️ ПАКЕТЫ — КРЫМСКИЙ СЕЗОН 2026\n\n"
         "💡 Контент-основа (6 роликов) — 69 000 ₽\n"
         "⭐ Контент под ключ — ФЛАГМАН — 89 000 ₽\n"
         "🚀 Контент + заявки — 119 000 ₽\n"
         "🌊 Старт сезона (7 дней) — 49 000 ₽\n"
         "🏨 Туристический хит — 99 000 ₽\n"
         "🍕 Ресторан в топе — 85 000 ₽\n"
         "🌅 Летний поток — максимум — 149 000 ₽\n"
         "🍷 Крымский бренд — 79 000 ₽\n\n"
         "Заявка: @lexx_agency_bot"),
    ]
    results = []
    for key, title, desc, text in items:
        if q and q not in title.lower() and q not in desc.lower():
            continue
        results.append(InlineQueryResultArticle(
            id=key, title=title, description=desc,
            input_message_content=InputTextMessageContent(message_text=text)))
    await update.inline_query.answer(results, cache_time=300)

# ── ЗАПУСК ────────────────────────────────────────────────────────────────────
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    # ConversationHandler — основной диалог
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start",  cmd_start),
            CallbackQueryHandler(go_home_any, pattern="^go_home$"),
        ],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(main_router, pattern="^go_"),
            ],
            # ── Юридика
            LEGAL_MENU: [
                CallbackQueryHandler(legal_menu,
                    pattern="^legal_book$|^legal_form_doc$|^legal_form_analysis$|^go_home$"),
                CallbackQueryHandler(go_home_any, pattern="^go_home$"),
            ],
            LEGAL_DATE: [
                CallbackQueryHandler(legal_date, pattern="^date_legal_|^go_back$|^go_home$"),
            ],
            LEGAL_TIME: [
                CallbackQueryHandler(legal_time, pattern="^time_|^go_back$|^go_home$"),
            ],
            # ── Студия
            STUDIO_MENU: [
                CallbackQueryHandler(studio_menu, pattern="^studio_book$|^go_home$"),
            ],
            BOOKING_DATE: [
                CallbackQueryHandler(booking_date, pattern="^date_studio_|^go_back$|^go_home$"),
            ],
            BOOKING_TIME: [
                CallbackQueryHandler(booking_time, pattern="^time_|^go_back$|^go_home$"),
            ],
            BOOKING_COMMENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, booking_comment),
                CallbackQueryHandler(go_home_any, pattern="^go_home$"),
            ],
            # ── Продакшен
            PROD_MENU: [
                CallbackQueryHandler(prod_menu,
                    pattern="^prod_|^go_prod$|^go_home$"),
            ],
            PROD_CATEGORY: [
                CallbackQueryHandler(prod_category,
                    pattern="^prod_apply$|^go_prod$|^go_home$"),
            ],
            # ── Кастинг
            CASTING_ROLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, casting_role),
                CallbackQueryHandler(go_home_any, pattern="^go_home$"),
            ],
            CASTING_PORTFOLIO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, casting_portfolio),
                CallbackQueryHandler(go_home_any, pattern="^go_home$"),
            ],
            # ── Общая форма
            FORM_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, form_name),
                CallbackQueryHandler(go_home_any, pattern="^go_home$"),
            ],
            FORM_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, form_phone),
                CallbackQueryHandler(go_home_any, pattern="^go_home$"),
            ],
            FORM_CONSENT: [
                CallbackQueryHandler(form_consent, pattern="^consent_yes$|^go_home$"),
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

    # ConversationHandler — рассылка (отдельный, чтобы не конфликтовать)
    broadcast_conv = ConversationHandler(
        entry_points=[CommandHandler("broadcast", cmd_broadcast)],
        states={
            BROADCAST_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_text),
            ],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
    )

    app.add_handler(broadcast_conv)   # сначала — он специфичнее
    app.add_handler(conv)
    app.add_handler(InlineQueryHandler(inline_query))
    app.add_error_handler(on_error)

    logger.info("Бот LEXX^ v4.0 запущен 🚀")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
