"""
Telegram-бот LEXX^
Версия: 3.0.0 — полный прайс: юридические услуги + фотостудия + инлайн-режим
"""

import logging
import sqlite3
import json
import re
import os
from datetime import datetime, timedelta
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultArticle,
    InputTextMessageContent
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, InlineQueryHandler,
    filters, ContextTypes
)

# ─── НАСТРОЙКИ ───────────────────────────────────────────────────────────────
BOT_TOKEN     = os.environ.get("BOT_TOKEN", "")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "0"))

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан!")
if not ADMIN_CHAT_ID:
    raise ValueError("ADMIN_CHAT_ID не задан!")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── СОСТОЯНИЯ ───────────────────────────────────────────────────────────────
MAIN_MENU = 0
BOOKING_DATE, BOOKING_TIME, BOOKING_COMMENT = 10, 11, 12
CASTING_ROLE, CASTING_PORTFOLIO = 20, 21
PRODUCTION_TYPE, PRODUCTION_BUDGET = 30, 31
SMM_NETWORKS, SMM_NICHE = 40, 41
FORM_NAME, FORM_PHONE, FORM_CONSENT = 50, 51, 52
PRICES_MENU = 60

# ─── БАЗА ДАННЫХ ─────────────────────────────────────────────────────────────
DB_PATH = os.environ.get("DB_PATH", "lexx_bot.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL, date TEXT NOT NULL, time TEXT NOT NULL,
        name TEXT NOT NULL, phone TEXT NOT NULL, username TEXT, comment TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL, service_type TEXT NOT NULL,
        name TEXT NOT NULL, phone TEXT NOT NULL, username TEXT,
        consent INTEGER DEFAULT 0, additional_data TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    conn.commit(); conn.close()
    logger.info("БД инициализирована: %s", DB_PATH)

def is_time_booked(date, time):
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.execute("SELECT id FROM bookings WHERE date=? AND time=?", (date, time))
    r = cur.fetchone(); conn.close(); return r is not None

def save_booking(user_id, date, time, name, phone, username, comment=""):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO bookings(user_id,date,time,name,phone,username,comment) VALUES(?,?,?,?,?,?,?)",
                 (user_id, date, time, name, phone, username, comment))
    conn.commit(); conn.close()

def save_application(user_id, service_type, name, phone, username, additional_data):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO applications(user_id,service_type,name,phone,username,consent,additional_data) VALUES(?,?,?,?,?,1,?)",
                 (user_id, service_type, name, phone, username,
                  json.dumps(additional_data, ensure_ascii=False)))
    conn.commit(); conn.close()

# ─────────────────────────────────────────────────────────────────────────────
#  ТЕКСТЫ ПРАЙС-ЛИСТОВ
# ─────────────────────────────────────────────────────────────────────────────

# ── Главное меню цен ─────────────────────────────────────────────────────────
TEXT_PRICES_MAIN = (
    "💰 <b>Прайс-лист LEXX^</b>\n\n"
    "Выберите раздел, чтобы узнать стоимость.\n"
    "По каждой позиции можно сразу оставить заявку — ответим в течение часа.\n\n"
    "🏖️ <b>Пакеты сезона</b> — самый выгодный старт для крымского бизнеса\n"
    "⚖️ <b>Юридические услуги</b> — документы, консультации, стратегия\n"
    "📸 <b>Фотостудия</b> — аренда, персонал, пакеты\n"
    "📷 <b>Фотосъёмка</b> — предметная, фуд, репортаж, лукбук\n"
    "🎬 <b>Видеопроизводство</b> — ролики, корпфильмы, рилс\n"
    "🎨 <b>Дизайн</b> — брендбук, упаковка, шаблоны\n"
    "📣 <b>Маркетинг</b> — таргет, контекст, стратегии\n"
    "📱 <b>SMM</b> — ведение соцсетей, контент, аналитика"
)

# ── Юридические услуги ───────────────────────────────────────────────────────
TEXT_LEGAL_MAIN = (
    "⚖️ <b>Юридические услуги LEXX^</b>\n\n"
    "Мы оказываем полный спектр письменных юридических услуг и устных консультаций.\n\n"
    "🔹 Мы <b>не адвокаты</b> и не представляем вас в судебных заседаниях — "
    "мы не ходим в суд вместо вас.\n"
    "🔹 Зато мы берём на себя <b>всю подготовительную работу и стратегию</b>: "
    "документы, расчёты, позиция, план действий.\n\n"
    "Выберите направление, чтобы узнать подробности и стоимость:"
)

TEXT_LEGAL_CONSULT = (
    "⚖️ <b>Устные консультации</b>\n\n"
    "💵 <b>Стоимость: 3 000 ₽ / час</b>\n\n"
    "Разберём вашу ситуацию и дадим конкретный план — без воды и общих фраз.\n\n"
    "<b>Что входит в консультацию:</b>\n\n"
    "📌 Разбор вашей ситуации\n"
    "   Гражданские, трудовые, семейные, жилищные споры,\n"
    "   долги, вопросы с недвижимостью\n\n"
    "📌 Анализ перспектив дела\n"
    "   Честная оценка судебных рисков — говорим как есть\n\n"
    "📌 Разъяснение норм законодательства\n"
    "   Применительно к вашей конкретной ситуации, не абстрактно\n\n"
    "📌 Пошаговый план действий\n"
    "   Что делать, куда идти, какие документы собирать\n\n"
    "📌 Экспресс-анализ ваших документов\n"
    "   Договоры, акты, письма — смотрим прямо на консультации\n\n"
    "💬 <i>Консультация проводится устно (Telegram, звонок или очно).\n"
    "Для записи нажмите кнопку ниже — перезвоним и согласуем время.</i>"
)

TEXT_LEGAL_DOCS = (
    "⚖️ <b>Составление юридических документов</b>\n\n"
    "💵 <b>Стоимость: от 2 000 ₽ за документ</b>\n\n"
    "Готовим документ «под ключ» по вашим вводным данным — "
    "вы получаете итоговый файл, готовый к подписанию или подаче.\n\n"
    "<b>Какие документы составляем:</b>\n\n"
    "📄 <b>Договоры</b>\n"
    "   Купли-продажи, аренды, найма, подряда, оказания услуг, займа, дарения\n\n"
    "📄 <b>Доп. соглашения и приложения</b>\n"
    "   К любым действующим договорам\n\n"
    "📄 <b>Претензии</b>\n"
    "   Досудебные требования к контрагентам, соседям, страховым компаниям\n\n"
    "📄 <b>Исковые заявления</b>\n"
    "   В суды общей юрисдикции и арбитраж\n\n"
    "📄 <b>Возражения и отзывы на иск</b>\n"
    "   Если вам предъявлен чужой иск\n\n"
    "📄 <b>Жалобы</b>\n"
    "   Апелляционные, кассационные, частные\n\n"
    "📄 <b>Заявления и ходатайства</b>\n"
    "   В полицию, прокуратуру, Роспотребнадзор,\n"
    "   Жилинспекцию и другие госорганы\n\n"
    "📄 <b>Заявления о взыскании судебных расходов</b>\n\n"
    "📄 <b>Требования о возмещении ущерба</b>\n\n"
    "💬 <i>Точная стоимость зависит от сложности и объёма документа.\n"
    "Оставьте заявку — рассчитаем стоимость бесплатно.</i>"
)

TEXT_LEGAL_ANALYSIS = (
    "⚖️ <b>Досудебная подготовка и аналитика</b>\n\n"
    "💵 <b>Стоимость: от 3 000 ₽</b> (рассчитывается индивидуально)\n\n"
    "Если у вас уже есть документы или ситуация требует глубокого анализа — "
    "мы проведём правовую экспертизу и подготовим всё необходимое.\n\n"
    "<b>Что входит в услугу:</b>\n\n"
    "🔍 <b>Правовая экспертиза документов</b>\n"
    "   Проверим ваш договор на «опасные» пункты — те, что могут\n"
    "   обернуться проблемами при споре\n\n"
    "🔍 <b>Сбор доказательной базы</b>\n"
    "   Поможем понять, каких документов не хватает для суда,\n"
    "   и подготовим полный пакет к подаче\n\n"
    "🔍 <b>Расчёт неустоек, пеней и процентов</b>\n"
    "   По ст. 395 ГК РФ и условиям вашего договора\n\n"
    "🔍 <b>Ответ на чужую претензию или иск</b>\n"
    "   Разберём требования оппонента и подготовим грамотный ответ\n\n"
    "💬 <i>Стоимость зависит от объёма и сложности.\n"
    "Оставьте заявку — свяжемся и обсудим детали.</i>"
)

# ── Фотостудия ───────────────────────────────────────────────────────────────
TEXT_STUDIO_MAIN = (
    "📸 <b>Фотостудия LEXX^</b>\n\n"
    "Профессиональное пространство для съёмок в центре Крыма.\n"
    "Снимайте сами или воспользуйтесь нашими специалистами — "
    "фотографом, рилсмейкером или видеографом.\n\n"
    "Выберите раздел, чтобы узнать стоимость:"
)

TEXT_STUDIO_RENT = (
    "📸 <b>Аренда фотостудии</b>\n\n"
    "Современное пространство с профессиональным оборудованием и освещением.\n"
    "Подходит для фотосессий, видеосъёмки, подкастов, интервью и контент-съёмок.\n\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n"
    "🏠 <b>Базовая аренда</b>\n"
    "   <b>2 000 ₽ / час</b>\n"
    "   Зал + свет + базовый реквизит\n"
    "   Минимальный заказ — 1 час\n\n"
    "🎙 <b>Пакет «Подкаст»</b>\n"
    "   <b>от 5 000 ₽ / час</b>\n"
    "   Зал + профессиональный микрофон + видеосъёмка\n"
    "   ⚠️ Минимальная аренда — <b>2 часа</b>\n"
    "   Идеально для интервью, подкастов, YouTube-формата\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "💬 <i>Бронирование по часам, 8:00 — 21:00.\n"
    "Конфликт расписания проверяется автоматически.\n"
    "Оставьте заявку — подтвердим слот и пришлём детали.</i>"
)

TEXT_STUDIO_STAFF = (
    "📸 <b>Специалисты на съёмку</b>\n\n"
    "Наши специалисты работают как в студии, так и на выезде.\n"
    "Можно совмещать: например, взять студию + рилсмейкера.\n\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n"
    "📷 <b>Фотограф</b>\n"
    "   <b>3 000 ₽ / час</b>\n"
    "   Съёмка, базовый отбор кадров\n"
    "   Ретушь — по отдельному тарифу\n\n"
    "🎬 <b>Рилсмейкер</b>\n"
    "   <b>1 500 ₽ / час</b>\n"
    "   Съёмка и монтаж Reels / Shorts / TikTok\n"
    "   ✅ Количество видео за час <b>не ограничено</b>\n"
    "   Работает быстро и на результат\n\n"
    "🎥 <b>Видеограф</b>\n"
    "   <b>3 000 ₽ / час</b>\n"
    "   Профессиональная видеосъёмка:\n"
    "   рекламные ролики, корпоративные видео, мероприятия\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "💡 <b>Популярные комбо:</b>\n"
    "   Студия 2ч + Рилсмейкер 2ч = <b>7 000 ₽</b> — контент на неделю\n"
    "   Студия 2ч + Фотограф 2ч = <b>10 000 ₽</b> — полная фотосессия\n\n"
    "💬 <i>Уточните запрос в заявке — подберём оптимальный пакет.</i>"
)

# ── Остальные категории прайса ────────────────────────────────────────────────
PRICES = {
    "photo": {
        "label": "📷 Фотосъёмка",
        "intro": "Профессиональная съёмка для бизнеса: еда, товары, команда, события.\nВсе работы с ретушью и отбором, если не указано иное.",
        "items": [
            ("Фуд-фотосъёмка (до 20 блюд, ретушь)", 45_000),
            ("Предметная съёмка (до 30 предметов)", 35_000),
            ("Съёмка команды / сотрудников (до 15 чел.)", 30_000),
            ("Репортажная съёмка мероприятия (до 8 ч.)", 55_000),
            ("Лукбук — fashion / бренд (до 10 образов)", 90_000),
        ],
        "outro": "Точная стоимость согласуется после брифинга.\nОставьте заявку — рассчитаем и пришлём КП."
    },
    "video": {
        "label": "🎬 Видеопроизводство",
        "intro": "Полный цикл: идея → сценарий → съёмка → монтаж → финальный файл.\nВсё под ключ, без вашего участия на производственном этапе.",
        "items": [
            ("Рекламный ролик 15–60 сек (съёмка + монтаж)", 180_000),
            ("Корпоративный фильм 3–7 мин", 280_000),
            ("Рилс / Shorts для соцсетей (1 шт.)", 35_000),
            ("Пакет рилс × 4 шт.", 110_000),
            ("Тизер / анонс события 30–45 сек", 70_000),
            ("Видео-кейс / отзыв клиента", 55_000),
            ("Съёмка мероприятия — полный день (highlights)", 150_000),
        ],
        "outro": "Производство — от 3 до 14 рабочих дней в зависимости от формата.\nОставьте заявку — обсудим детали и дедлайн."
    },
    "design": {
        "label": "🎨 Дизайн",
        "intro": "От брендбука до баннеров — всё, что нужно бизнесу для узнаваемого визуала.",
        "items": [
            ("Фирменный стиль — брендбук lite", 120_000),
            ("Дизайн упаковки (1 SKU)", 65_000),
            ("Шаблоны для соцсетей (15 шт. посты + сторис)", 45_000),
            ("Презентация до 20 слайдов (PPTX)", 40_000),
            ("Баннеры — пакет 8 форматов (HTML/PNG)", 30_000),
        ],
        "outro": "Все исходники — ваши. Правки включены в стоимость (до 3 итераций)."
    },
    "marketing": {
        "label": "📣 Реклама и маркетинг",
        "intro": "Запускаем трафик туда, где уже есть доверие. Без слива бюджета на холодную аудиторию.",
        "items": [
            ("Таргет ВКонтакте / myTarget (настройка + 1 мес.)", 55_000),
            ("Контекстная реклама Яндекс.Директ (1 мес.)", 65_000),
            ("SMM-стратегия (анализ + контент-план на 3 мес.)", 80_000),
            ("Ведение соцсетей — 1 платформа (1 мес.)", 45_000),
            ("Email-рассылки (стратегия + 4 письма)", 55_000),
            ("SEO-аудит сайта", 40_000),
            ("Контент-план на 3 месяца", 30_000),
        ],
        "outro": "Рекламный бюджет — отдельно, только по факту расхода.\nВедём отчётность в реальном времени."
    },
    "smm": {
        "label": "📱 SMM-услуги",
        "intro": "Системная работа с соцсетями: от аудита до ежемесячного ведения.\nРаботаем с Instagram, VK, Telegram, TikTok.",
        "items": [
            ("Аудит аккаунта VK / Instagram (PDF-отчёт)", 18_000),
            ("Оформление профиля под ключ", 22_000),
            ("Контент-стратегия (ЦА, рубрики, KPI)", 35_000),
            ("Сценарии для Reels × 8 шт.", 24_000),
            ("Ведение Telegram-канала (1 мес., до 20 постов)", 40_000),
            ("Экспресс-рилс под ключ (1 шт.)", 12_000),
            ("Пакет Reels под ключ × 4 шт.", 42_000),
            ("Reels-марафон × 12 роликов (1 мес.)", 95_000),
            ("Комьюнити-менеджмент (1 мес.)", 28_000),
            ("Таргет ВКонтакте — быстрый старт", 35_000),
            ("Продвижение через Reels — органика (1 мес.)", 45_000),
            ("Ежемесячный отчёт + аналитика", 12_000),
            ("Реанимация аккаунта после простоя", 32_000),
        ],
        "outro": "Один менеджер на весь проект — никакой чехарды и потери контекста."
    },
    "packages": {
        "label": "🏖️ Пакеты — Крымский сезон 2026",
        "intro": "Готовые решения для крымского бизнеса. Всё включено: съёмка, монтаж, публикация.\nМожно адаптировать под вашу нишу.",
        "items": [
            ("💡 Контент-основа — старт\n   6 роликов, адаптация под VK/Reels/Shorts", 69_000),
            ("⭐ Контент под ключ — ФЛАГМАН\n   8 роликов, смыслы, стратегия, рекомендации", 89_000),
            ("🚀 Контент + заявки — максимум\n   12 роликов, воронка, консультация по продажам", 119_000),
            ("🌊 Старт сезона (экспресс, 7 дней)\n   Аудит + оформление + 4 сезонных рилс", 49_000),
            ("🏨 Туристический хит\n   8 роликов, фото 20 кадров, Stories, VK+Instagram", 99_000),
            ("🍕 Ресторан в топе\n   8 фуд-роликов, фотосессия 15 блюд, геометки", 85_000),
            ("🌅 Летний поток — максимум\n   12 роликов/мес., таргет, воронка, аналитика", 149_000),
            ("🍷 Крымский бренд\n   6 роликов с историей, лукбук, интеграция в паблики", 79_000),
        ],
        "outro": "Пакеты можно комбинировать и адаптировать.\nОставьте заявку — составим индивидуальное предложение под ваш сезон."
    },
}

def fmt(price):
    return f"{price:,}".replace(",", " ") + " ₽"

def build_price_text(cat_key):
    """Формирует текст прайса для стандартных категорий"""
    cat = PRICES[cat_key]
    lines = [f"<b>{cat['label']}</b>\n", f"<i>{cat['intro']}</i>\n\n━━━━━━━━━━━━━━━━━━━━━━"]
    for name, price in cat["items"]:
        lines.append(f"\n• {name}\n  <b>{fmt(price)}</b>")
    lines.append(f"\n━━━━━━━━━━━━━━━━━━━━━━\n\n💬 <i>{cat['outro']}</i>")
    return "\n".join(lines)

# ─────────────────────────────────────────────────────────────────────────────
#  КЛАВИАТУРЫ
# ─────────────────────────────────────────────────────────────────────────────

def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Цены и услуги",            callback_data="menu_prices")],
        [InlineKeyboardButton("⚖️ Юридическая помощь",       callback_data="service_legal")],
        [InlineKeyboardButton("📸 Бронирование фотостудии",  callback_data="service_studio")],
        [InlineKeyboardButton("🎭 Подать заявку на кастинг", callback_data="service_casting")],
        [InlineKeyboardButton("🎬 Заказать продакшен",       callback_data="service_production")],
        [InlineKeyboardButton("📱 Заказать SMM",             callback_data="service_smm")],
    ])

def prices_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏖️ Пакеты — сезон 2026",   callback_data="price_packages")],
        [InlineKeyboardButton("⚖️ Юридические услуги",    callback_data="price_legal")],
        [InlineKeyboardButton("📸 Фотостудия",            callback_data="price_studio")],
        [InlineKeyboardButton("📷 Фотосъёмка",            callback_data="price_photo")],
        [InlineKeyboardButton("🎬 Видеопроизводство",     callback_data="price_video")],
        [InlineKeyboardButton("🎨 Дизайн",                callback_data="price_design")],
        [InlineKeyboardButton("📣 Реклама и маркетинг",   callback_data="price_marketing")],
        [InlineKeyboardButton("📱 SMM-услуги",            callback_data="price_smm")],
        [InlineKeyboardButton("🏠 Главное меню",           callback_data="go_home")],
    ])

def legal_submenu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗣 Устные консультации",          callback_data="legal_consult")],
        [InlineKeyboardButton("📄 Составление документов",       callback_data="legal_docs")],
        [InlineKeyboardButton("🔍 Досудебная подготовка",        callback_data="legal_analysis")],
        [InlineKeyboardButton("📩 Оставить заявку",              callback_data="service_legal")],
        [InlineKeyboardButton("⬅️ Назад к ценам",               callback_data="menu_prices")],
        [InlineKeyboardButton("🏠 Главное меню",                 callback_data="go_home")],
    ])

def legal_detail_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📩 Оставить заявку",    callback_data="service_legal")],
        [InlineKeyboardButton("⬅️ Назад к юруслугам", callback_data="price_legal")],
        [InlineKeyboardButton("🏠 Главное меню",       callback_data="go_home")],
    ])

def studio_submenu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Аренда студии",       callback_data="studio_rent")],
        [InlineKeyboardButton("👥 Специалисты",         callback_data="studio_staff")],
        [InlineKeyboardButton("📩 Забронировать",       callback_data="service_studio")],
        [InlineKeyboardButton("⬅️ Назад к ценам",      callback_data="menu_prices")],
        [InlineKeyboardButton("🏠 Главное меню",        callback_data="go_home")],
    ])

def studio_detail_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📩 Забронировать",      callback_data="service_studio")],
        [InlineKeyboardButton("⬅️ Назад к студии",    callback_data="price_studio")],
        [InlineKeyboardButton("🏠 Главное меню",       callback_data="go_home")],
    ])

def price_detail_keyboard(cat_key):
    service_map = {
        "photo": "service_studio", "video": "service_production",
        "design": "service_production", "marketing": "service_smm",
        "smm": "service_smm", "packages": "service_production",
    }
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📩 Оставить заявку",   callback_data=service_map.get(cat_key, "service_production"))],
        [InlineKeyboardButton("⬅️ Назад к ценам",    callback_data="menu_prices")],
        [InlineKeyboardButton("🏠 Главное меню",      callback_data="go_home")],
    ])

def back_and_home_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Назад",      callback_data="go_back"),
        InlineKeyboardButton("🏠 Главное меню", callback_data="go_home"),
    ]])

def home_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Главное меню", callback_data="go_home")]
    ])

def consent_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Даю согласие на обработку персональных данных",
                              callback_data="consent_yes")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="go_home")],
    ])

def date_keyboard():
    today = datetime.now(); buttons = []; row = []
    for i in range(30):
        d   = today + timedelta(days=i)
        lbl = d.strftime("%d.%m") + (" (сег.)" if i == 0 else "")
        row.append(InlineKeyboardButton(lbl, callback_data=f"date_{d.strftime('%Y-%m-%d')}"))
        if len(row) == 3: buttons.append(row); row = []
    if row: buttons.append(row)
    buttons.append([
        InlineKeyboardButton("⬅️ Назад",      callback_data="go_back"),
        InlineKeyboardButton("🏠 Главное меню", callback_data="go_home"),
    ])
    return InlineKeyboardMarkup(buttons)

def time_keyboard(selected_date):
    buttons = []; row = []
    for h in range(8, 22):
        ts = f"{h:02d}:00"
        if is_time_booked(selected_date, ts):
            row.append(InlineKeyboardButton(f"❌ {ts}", callback_data=f"time_busy_{ts}"))
        else:
            row.append(InlineKeyboardButton(f"✅ {ts}", callback_data=f"time_{ts}"))
        if len(row) == 3: buttons.append(row); row = []
    if row: buttons.append(row)
    buttons.append([
        InlineKeyboardButton("⬅️ Назад",      callback_data="go_back"),
        InlineKeyboardButton("🏠 Главное меню", callback_data="go_home"),
    ])
    return InlineKeyboardMarkup(buttons)

def production_type_keyboard():
    types = ["Реклама", "Клип", "Фильм", "Корпоративное видео", "Другое"]
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(t, callback_data=f"prod_type_{t}")] for t in types] +
        [[InlineKeyboardButton("⬅️ Назад", callback_data="go_back"),
          InlineKeyboardButton("🏠 Главное меню", callback_data="go_home")]]
    )

# ─────────────────────────────────────────────────────────────────────────────
#  ТЕКСТЫ
# ─────────────────────────────────────────────────────────────────────────────
WELCOME_TEXT = (
    "👋 Добро пожаловать в <b>LEXX^</b> — многофункциональное креативное агентство!\n\n"
    "Мы объединяем под одной крышей:\n\n"
    "💰 <b>Прайс-лист</b> — все цены на услуги\n"
    "⚖️ <b>Юридическая помощь</b> — консультации, документы, договоры\n"
    "📸 <b>Фотостудия</b> — профессиональная съёмка, бронирование\n"
    "🎭 <b>Кастинги</b> — участие в проектах агентства\n"
    "🎬 <b>Продакшен</b> — полный цикл производства видео и контента\n"
    "📱 <b>SMM-услуги</b> — ведение соцсетей, стратегии, контент\n\n"
    "Выберите нужное направление:"
)

# ─────────────────────────────────────────────────────────────────────────────
#  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ─────────────────────────────────────────────────────────────────────────────
def validate_phone(p): return len(re.sub(r"\D","",p)) >= 10
def get_username(u): return f"@{u.username}" if u.username else f"ID:{u.id}"

async def send_admin(context, text):
    try: await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=text, parse_mode="HTML")
    except Exception as e: logger.error("Ошибка уведомления: %s", e)

async def show_main_menu(update, context, edit=False):
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(
            WELCOME_TEXT, reply_markup=main_menu_keyboard(), parse_mode="HTML")
    else:
        tgt = update.message or update.callback_query.message
        await tgt.reply_text(WELCOME_TEXT, reply_markup=main_menu_keyboard(), parse_mode="HTML")

# ─────────────────────────────────────────────────────────────────────────────
#  ИНЛАЙН-РЕЖИМ  (@botname запрос)
# ─────────────────────────────────────────────────────────────────────────────
INLINE_ITEMS = [
    ("packages", "🏖️ Пакеты сезона 2026",         "Готовые решения для крымского бизнеса"),
    ("legal",    "⚖️ Юридические услуги",           "Консультации, документы, досудебная подготовка"),
    ("studio",   "📸 Фотостудия — аренда и персонал","Студия, подкаст, фотограф, рилсмейкер, видеограф"),
    ("photo",    "📷 Фотосъёмка",                   "Фуд, предметная, репортаж, лукбук"),
    ("video",    "🎬 Видеопроизводство",             "Рекламные ролики, корпфильмы, рилс"),
    ("design",   "🎨 Дизайн",                       "Брендбук, упаковка, шаблоны, презентации"),
    ("marketing","📣 Реклама и маркетинг",           "Таргет, контекст, SMM-стратегии"),
    ("smm",      "📱 SMM-услуги",                   "Аудит, ведение, контент, рилс-пакеты"),
]

def inline_price_text(key):
    """Текст для инлайн-результата"""
    if key == "legal":
        return (
            "⚖️ ЮРИДИЧЕСКИЕ УСЛУГИ LEXX^\n\n"
            "1️⃣ Устная консультация — 3 000 ₽/час\n"
            "2️⃣ Составление документов — от 2 000 ₽\n"
            "3️⃣ Досудебная подготовка — от 3 000 ₽\n\n"
            "Пишите @lexx_agency_bot — ответим и рассчитаем стоимость."
        )
    if key == "studio":
        return (
            "📸 ФОТОСТУДИЯ LEXX^\n\n"
            "🏠 Аренда студии — 2 000 ₽/час\n"
            "🎙 Пакет «Подкаст» — от 5 000 ₽/час (мин. 2 часа)\n\n"
            "👥 Специалисты:\n"
            "• Фотограф — 3 000 ₽/час\n"
            "• Рилсмейкер — 1 500 ₽/час (видео не ограничено)\n"
            "• Видеограф — 3 000 ₽/час\n\n"
            "Бронирование: @lexx_agency_bot"
        )
    if key in PRICES:
        cat = PRICES[key]
        lines = [f"{cat['label'].upper()}\n\n{cat['intro']}\n"]
        for name, price in cat["items"]:
            clean = name.replace("\n   ", " — ")
            lines.append(f"• {clean}: {fmt(price)}")
        lines.append(f"\n{cat['outro']}")
        lines.append("\nПодробнее: @lexx_agency_bot")
        return "\n".join(lines)
    return "Прайс LEXX^: @lexx_agency_bot"

async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик инлайн-запросов: @botname [текст]"""
    query_text = (update.inline_query.query or "").lower().strip()
    results = []
    for key, title, description in INLINE_ITEMS:
        # Фильтруем по запросу если он есть
        if query_text and query_text not in title.lower() and query_text not in description.lower():
            continue
        text = inline_price_text(key)
        results.append(InlineQueryResultArticle(
            id=key,
            title=title,
            description=description,
            input_message_content=InputTextMessageContent(
                message_text=text,
                parse_mode=None  # plain text для совместимости
            ),
            thumb_emoji=title[0]
        ))
    await update.inline_query.answer(results, cache_time=300)

# ─────────────────────────────────────────────────────────────────────────────
#  КОМАНДЫ
# ─────────────────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        WELCOME_TEXT, reply_markup=main_menu_keyboard(), parse_mode="HTML")
    return MAIN_MENU

async def cmd_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /prices — быстрый доступ к прайсу"""
    await update.message.reply_text(
        TEXT_PRICES_MAIN, reply_markup=prices_main_keyboard(), parse_mode="HTML")
    return PRICES_MENU

# ─────────────────────────────────────────────────────────────────────────────
#  РАЗДЕЛ ЦЕН
# ─────────────────────────────────────────────────────────────────────────────
async def prices_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    await query.edit_message_text(
        TEXT_PRICES_MAIN, reply_markup=prices_main_keyboard(), parse_mode="HTML")
    return PRICES_MENU

async def price_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    data  = query.data

    if data == "go_home":
        context.user_data.clear()
        await show_main_menu(update, context, edit=True)
        return MAIN_MENU

    if data == "menu_prices":
        await query.edit_message_text(
            TEXT_PRICES_MAIN, reply_markup=prices_main_keyboard(), parse_mode="HTML")
        return PRICES_MENU

    # ── Юридические услуги — подменю ──
    if data == "price_legal":
        await query.edit_message_text(
            TEXT_LEGAL_MAIN, reply_markup=legal_submenu_keyboard(), parse_mode="HTML")
        return PRICES_MENU

    if data == "legal_consult":
        await query.edit_message_text(
            TEXT_LEGAL_CONSULT, reply_markup=legal_detail_keyboard(), parse_mode="HTML")
        return PRICES_MENU

    if data == "legal_docs":
        await query.edit_message_text(
            TEXT_LEGAL_DOCS, reply_markup=legal_detail_keyboard(), parse_mode="HTML")
        return PRICES_MENU

    if data == "legal_analysis":
        await query.edit_message_text(
            TEXT_LEGAL_ANALYSIS, reply_markup=legal_detail_keyboard(), parse_mode="HTML")
        return PRICES_MENU

    # ── Фотостудия — подменю ──
    if data == "price_studio":
        await query.edit_message_text(
            TEXT_STUDIO_MAIN, reply_markup=studio_submenu_keyboard(), parse_mode="HTML")
        return PRICES_MENU

    if data == "studio_rent":
        await query.edit_message_text(
            TEXT_STUDIO_RENT, reply_markup=studio_detail_keyboard(), parse_mode="HTML")
        return PRICES_MENU

    if data == "studio_staff":
        await query.edit_message_text(
            TEXT_STUDIO_STAFF, reply_markup=studio_detail_keyboard(), parse_mode="HTML")
        return PRICES_MENU

    # ── Остальные категории ──
    cat_key = data.replace("price_", "")
    if cat_key in PRICES:
        context.user_data["price_category"] = cat_key
        await query.edit_message_text(
            build_price_text(cat_key),
            reply_markup=price_detail_keyboard(cat_key),
            parse_mode="HTML")
        return PRICES_MENU

    return PRICES_MENU

# ─────────────────────────────────────────────────────────────────────────────
#  ВЫБОР УСЛУГИ
# ─────────────────────────────────────────────────────────────────────────────
async def handle_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    data  = query.data

    if data == "go_home":
        context.user_data.clear()
        await show_main_menu(update, context, edit=True)
        return MAIN_MENU

    if data == "menu_prices":
        await query.edit_message_text(
            TEXT_PRICES_MAIN, reply_markup=prices_main_keyboard(), parse_mode="HTML")
        return PRICES_MENU

    if data == "service_legal":
        context.user_data.update({"service": "legal", "service_name": "⚖️ Юридическая помощь"})
        await query.edit_message_text(
            "⚖️ <b>Юридическая помощь</b>\n\n"
            "Оставьте заявку — юрист свяжется с вами в течение часа,\n"
            "уточнит ситуацию и предложит оптимальное решение.\n\n"
            "Введите ваше <b>имя</b>:",
            reply_markup=back_and_home_keyboard(), parse_mode="HTML")
        return FORM_NAME

    elif data == "service_studio":
        context.user_data.update({"service": "studio", "service_name": "📸 Бронирование фотостудии"})
        await query.edit_message_text(
            "📸 <b>Бронирование фотостудии</b>\n\n"
            "🕐 Работаем с <b>8:00 до 21:00</b>, шаг — 1 час\n\n"
            "Выберите <b>дату</b>:",
            reply_markup=date_keyboard(), parse_mode="HTML")
        return BOOKING_DATE

    elif data == "service_casting":
        context.user_data.update({"service": "casting", "service_name": "🎭 Кастинг"})
        await query.edit_message_text(
            "🎭 <b>Заявка на кастинг</b>\n\n"
            "Укажите ваше <b>амплуа / роль</b>\n"
            "(например: актёр, модель, ведущий):",
            reply_markup=back_and_home_keyboard(), parse_mode="HTML")
        return CASTING_ROLE

    elif data == "service_production":
        context.user_data.update({"service": "production", "service_name": "🎬 Продакшен"})
        await query.edit_message_text(
            "🎬 <b>Заказ продакшн-услуг</b>\n\n"
            "Полный цикл: от идеи до готового продукта.\n\n"
            "Выберите <b>тип проекта</b>:",
            reply_markup=production_type_keyboard(), parse_mode="HTML")
        return PRODUCTION_TYPE

    elif data == "service_smm":
        context.user_data.update({"service": "smm", "service_name": "📱 SMM"})
        await query.edit_message_text(
            "📱 <b>Заказ SMM-услуг</b>\n\n"
            "Ведение соцсетей, контент, рекламные стратегии.\n\n"
            "Укажите <b>соцсети для ведения</b>\n"
            "(например: Instagram, VK, TikTok):",
            reply_markup=back_and_home_keyboard(), parse_mode="HTML")
        return SMM_NETWORKS

    return MAIN_MENU

# ─────────────────────────────────────────────────────────────────────────────
#  БРОНИРОВАНИЕ ФОТОСТУДИИ
# ─────────────────────────────────────────────────────────────────────────────
async def booking_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if query.data == "go_home":
        context.user_data.clear(); await show_main_menu(update, context, edit=True); return MAIN_MENU
    if query.data == "go_back":
        await query.edit_message_text(WELCOME_TEXT, reply_markup=main_menu_keyboard(), parse_mode="HTML")
        return MAIN_MENU
    sd = query.data.replace("date_",""); context.user_data["booking_date"] = sd
    dd = datetime.strptime(sd,"%Y-%m-%d").strftime("%d.%m.%Y")
    await query.edit_message_text(
        f"📅 Дата: <b>{dd}</b>\n\n✅ — свободно   ❌ — занято\n\nВыберите <b>время</b>:",
        reply_markup=time_keyboard(sd), parse_mode="HTML")
    return BOOKING_TIME

async def booking_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if query.data == "go_home":
        context.user_data.clear(); await show_main_menu(update, context, edit=True); return MAIN_MENU
    if query.data == "go_back":
        await query.edit_message_text(
            "📸 <b>Бронирование</b>\n\nВыберите <b>дату</b>:",
            reply_markup=date_keyboard(), parse_mode="HTML"); return BOOKING_DATE
    if query.data.startswith("time_busy_"):
        await query.answer("❌ Это время занято. Выберите другое.", show_alert=True); return BOOKING_TIME
    st = query.data.replace("time_",""); context.user_data["booking_time"] = st
    sd = context.user_data["booking_date"]
    dd = datetime.strptime(sd,"%Y-%m-%d").strftime("%d.%m.%Y")
    await query.edit_message_text(
        f"📅 Дата: <b>{dd}</b>\n🕐 Время: <b>{st}</b>\n\n"
        "Оставьте <b>комментарий</b> (необязательно).\n"
        "Тип съёмки, кол-во человек, нужен ли специалист.\n\n"
        "Или введите <b>«—»</b> чтобы пропустить.",
        reply_markup=back_and_home_keyboard(), parse_mode="HTML")
    return BOOKING_COMMENT

async def booking_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["booking_comment"] = "" if text == "—" else text
    await update.message.reply_text(
        "Введите ваше <b>имя</b>:", reply_markup=home_keyboard(), parse_mode="HTML")
    return FORM_NAME

# ─────────────────────────────────────────────────────────────────────────────
#  КАСТИНГ
# ─────────────────────────────────────────────────────────────────────────────
async def casting_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if len(text) < 2:
        await update.message.reply_text("⚠️ Укажите амплуа (мин. 2 символа):", reply_markup=home_keyboard())
        return CASTING_ROLE
    context.user_data["casting_role"] = text
    await update.message.reply_text(
        "Укажите <b>ссылку на портфолио</b> (необязательно).\nИли введите <b>«—»</b>:",
        reply_markup=home_keyboard(), parse_mode="HTML")
    return CASTING_PORTFOLIO

async def casting_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["casting_portfolio"] = "" if text == "—" else text
    await update.message.reply_text(
        "Введите ваше <b>имя</b>:", reply_markup=home_keyboard(), parse_mode="HTML")
    return FORM_NAME

# ─────────────────────────────────────────────────────────────────────────────
#  ПРОДАКШЕН
# ─────────────────────────────────────────────────────────────────────────────
async def production_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if query.data == "go_home":
        context.user_data.clear(); await show_main_menu(update, context, edit=True); return MAIN_MENU
    if query.data == "go_back":
        await query.edit_message_text(WELCOME_TEXT, reply_markup=main_menu_keyboard(), parse_mode="HTML")
        return MAIN_MENU
    pt = query.data.replace("prod_type_",""); context.user_data["production_type"] = pt
    await query.edit_message_text(
        f"🎬 Тип проекта: <b>{pt}</b>\n\n"
        "Укажите <b>бюджет проекта</b> (необязательно).\nИли введите <b>«—»</b>:",
        reply_markup=back_and_home_keyboard(), parse_mode="HTML")
    return PRODUCTION_BUDGET

async def production_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["production_budget"] = "" if text == "—" else text
    await update.message.reply_text(
        "Введите ваше <b>имя</b>:", reply_markup=home_keyboard(), parse_mode="HTML")
    return FORM_NAME

# ─────────────────────────────────────────────────────────────────────────────
#  SMM
# ─────────────────────────────────────────────────────────────────────────────
async def smm_networks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if len(text) < 2:
        await update.message.reply_text("⚠️ Укажите хотя бы одну соцсеть:", reply_markup=home_keyboard())
        return SMM_NETWORKS
    context.user_data["smm_networks"] = text
    await update.message.reply_text(
        "Укажите <b>тематику / нишу</b> бизнеса\n(например: ресторан, beauty, строительство):",
        reply_markup=home_keyboard(), parse_mode="HTML")
    return SMM_NICHE

async def smm_niche(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if len(text) < 2:
        await update.message.reply_text("⚠️ Укажите тематику / нишу:", reply_markup=home_keyboard())
        return SMM_NICHE
    context.user_data["smm_niche"] = text
    await update.message.reply_text(
        "Введите ваше <b>имя</b>:", reply_markup=home_keyboard(), parse_mode="HTML")
    return FORM_NAME

# ─────────────────────────────────────────────────────────────────────────────
#  ОБЩАЯ ФОРМА ЗАЯВКИ
# ─────────────────────────────────────────────────────────────────────────────
async def form_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if len(text) < 2:
        await update.message.reply_text(
            "⚠️ Имя слишком короткое. Введите <b>имя</b> ещё раз:",
            reply_markup=home_keyboard(), parse_mode="HTML"); return FORM_NAME
    context.user_data["form_name"] = text
    await update.message.reply_text(
        f"Приятно познакомиться, <b>{text}</b>! 👋\n\nВведите ваш <b>номер телефона</b>:",
        reply_markup=home_keyboard(), parse_mode="HTML")
    return FORM_PHONE

async def form_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    if not validate_phone(phone):
        await update.message.reply_text(
            "⚠️ Некорректный номер. Введите <b>телефон</b> (минимум 10 цифр):",
            reply_markup=home_keyboard(), parse_mode="HTML"); return FORM_PHONE
    context.user_data["form_phone"]    = phone
    context.user_data["form_username"] = get_username(update.effective_user)
    service      = context.user_data.get("service","")
    service_name = context.user_data.get("service_name","Услуга")
    s = (f"📋 <b>Проверьте данные заявки:</b>\n\n"
         f"🔹 Услуга: {service_name}\n"
         f"🔹 Имя: {context.user_data['form_name']}\n"
         f"🔹 Телефон: {phone}\n"
         f"🔹 Telegram: {context.user_data['form_username']}\n")
    if service == "studio":
        d  = context.user_data.get("booking_date","")
        dd = datetime.strptime(d,"%Y-%m-%d").strftime("%d.%m.%Y") if d else "—"
        s += f"🔹 Дата: {dd}\n🔹 Время: {context.user_data.get('booking_time','—')}\n"
        if context.user_data.get("booking_comment"):
            s += f"🔹 Комментарий: {context.user_data['booking_comment']}\n"
    elif service == "casting":
        s += f"🔹 Амплуа: {context.user_data.get('casting_role','—')}\n"
        if context.user_data.get("casting_portfolio"):
            s += f"🔹 Портфолио: {context.user_data['casting_portfolio']}\n"
    elif service == "production":
        s += f"🔹 Тип: {context.user_data.get('production_type','—')}\n"
        if context.user_data.get("production_budget"):
            s += f"🔹 Бюджет: {context.user_data['production_budget']}\n"
    elif service == "smm":
        s += f"🔹 Соцсети: {context.user_data.get('smm_networks','—')}\n"
        s += f"🔹 Ниша: {context.user_data.get('smm_niche','—')}\n"
    s += "\n📌 Для отправки необходимо дать согласие на обработку персональных данных:"
    await update.message.reply_text(s, reply_markup=consent_keyboard(), parse_mode="HTML")
    return FORM_CONSENT

async def form_consent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if query.data == "go_home":
        context.user_data.clear(); await show_main_menu(update, context, edit=True); return MAIN_MENU
    if query.data != "consent_yes": return FORM_CONSENT
    uid          = update.effective_user.id
    service      = context.user_data.get("service","unknown")
    service_name = context.user_data.get("service_name","Услуга")
    name         = context.user_data.get("form_name","")
    phone        = context.user_data.get("form_phone","")
    username     = context.user_data.get("form_username","")
    additional   = {}
    if service == "studio":
        additional = {"date": context.user_data.get("booking_date",""),
                      "time": context.user_data.get("booking_time",""),
                      "comment": context.user_data.get("booking_comment","")}
        if is_time_booked(additional["date"], additional["time"]):
            await query.edit_message_text(
                "⚠️ Это время уже <b>занято</b>.\n\nНачните бронирование заново.",
                reply_markup=home_keyboard(), parse_mode="HTML"); return MAIN_MENU
        save_booking(uid, additional["date"], additional["time"],
                     name, phone, username, additional.get("comment",""))
    elif service == "casting":
        additional = {"role": context.user_data.get("casting_role",""),
                      "portfolio": context.user_data.get("casting_portfolio","")}
    elif service == "production":
        additional = {"type": context.user_data.get("production_type",""),
                      "budget": context.user_data.get("production_budget","")}
    elif service == "smm":
        additional = {"networks": context.user_data.get("smm_networks",""),
                      "niche": context.user_data.get("smm_niche","")}
    save_application(uid, service, name, phone, username, additional)
    admin = (f"🔔 <b>НОВАЯ ЗАЯВКА — LEXX^</b>\n\n"
             f"📋 Услуга: <b>{service_name}</b>\n"
             f"👤 {name}\n📞 {phone}\n💬 {username}\n🆔 {uid}\n")
    if service == "studio":
        d  = additional.get("date","")
        dd = datetime.strptime(d,"%Y-%m-%d").strftime("%d.%m.%Y") if d else "—"
        admin += f"📅 {dd} 🕐 {additional.get('time','—')}\n"
        if additional.get("comment"): admin += f"💬 {additional['comment']}\n"
    elif service == "casting":
        admin += f"🎭 {additional.get('role','—')}\n"
        if additional.get("portfolio"): admin += f"🔗 {additional['portfolio']}\n"
    elif service == "production":
        admin += f"🎬 {additional.get('type','—')}\n"
        if additional.get("budget"): admin += f"💰 {additional['budget']}\n"
    elif service == "smm":
        admin += f"📱 {additional.get('networks','—')}\n🏷 {additional.get('niche','—')}\n"
    admin += f"\n🕒 {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    await send_admin(context, admin)
    await query.edit_message_text(
        "✅ <b>Спасибо! Ваша заявка принята.</b>\n\n"
        "Мы свяжемся с вами в ближайшее время. 🙌",
        reply_markup=home_keyboard(), parse_mode="HTML")
    context.user_data.clear()
    return ConversationHandler.END

# ─────────────────────────────────────────────────────────────────────────────
#  СЛУЖЕБНЫЕ
# ─────────────────────────────────────────────────────────────────────────────
async def go_home_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    context.user_data.clear()
    await show_main_menu(update, context, edit=True)
    return MAIN_MENU

async def unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤔 Используйте кнопки меню.\nНажмите /start чтобы начать заново.",
        reply_markup=home_keyboard())

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Ошибка: %s", context.error, exc_info=context.error)

# ─────────────────────────────────────────────────────────────────────────────
#  ЗАПУСК
# ─────────────────────────────────────────────────────────────────────────────
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start",  start),
            CommandHandler("prices", cmd_prices),
            CallbackQueryHandler(go_home_callback, pattern="^go_home$"),
        ],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(prices_menu_handler, pattern="^menu_prices$"),
                CallbackQueryHandler(handle_service,      pattern="^service_|^go_home$"),
            ],
            PRICES_MENU: [
                CallbackQueryHandler(price_category, pattern=(
                    "^price_|^menu_prices$|^go_home$|"
                    "^legal_consult$|^legal_docs$|^legal_analysis$|"
                    "^studio_rent$|^studio_staff$"
                )),
                CallbackQueryHandler(handle_service, pattern="^service_"),
            ],
            BOOKING_DATE:      [CallbackQueryHandler(booking_date,    pattern="^date_|^go_back$|^go_home$")],
            BOOKING_TIME:      [CallbackQueryHandler(booking_time,    pattern="^time_|^go_back$|^go_home$")],
            BOOKING_COMMENT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, booking_comment),
                                CallbackQueryHandler(go_home_callback, pattern="^go_home$")],
            CASTING_ROLE:      [MessageHandler(filters.TEXT & ~filters.COMMAND, casting_role),
                                CallbackQueryHandler(go_home_callback, pattern="^go_home$")],
            CASTING_PORTFOLIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, casting_portfolio),
                                CallbackQueryHandler(go_home_callback, pattern="^go_home$")],
            PRODUCTION_TYPE:   [CallbackQueryHandler(production_type, pattern="^prod_type_|^go_back$|^go_home$")],
            PRODUCTION_BUDGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, production_budget),
                                CallbackQueryHandler(go_home_callback, pattern="^go_home$")],
            SMM_NETWORKS:      [MessageHandler(filters.TEXT & ~filters.COMMAND, smm_networks),
                                CallbackQueryHandler(go_home_callback, pattern="^go_home$")],
            SMM_NICHE:         [MessageHandler(filters.TEXT & ~filters.COMMAND, smm_niche),
                                CallbackQueryHandler(go_home_callback, pattern="^go_home$")],
            FORM_NAME:         [MessageHandler(filters.TEXT & ~filters.COMMAND, form_name),
                                CallbackQueryHandler(go_home_callback, pattern="^go_home$")],
            FORM_PHONE:        [MessageHandler(filters.TEXT & ~filters.COMMAND, form_phone),
                                CallbackQueryHandler(go_home_callback, pattern="^go_home$")],
            FORM_CONSENT:      [CallbackQueryHandler(form_consent, pattern="^consent_yes$|^go_home$")],
        },
        fallbacks=[
            CommandHandler("start",  start),
            CommandHandler("prices", cmd_prices),
            CallbackQueryHandler(go_home_callback, pattern="^go_home$"),
            MessageHandler(filters.ALL, unknown_message),
        ],
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_handler(InlineQueryHandler(inline_query))
    app.add_error_handler(error_handler)
    logger.info("Бот LEXX^ v3.0 запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
