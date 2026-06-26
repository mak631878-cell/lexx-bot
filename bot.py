"""
Telegram-бот LEXX^
Многофункциональный бот-ассистент для креативного агентства LEXX^
Версия: 1.0.0
"""

import logging
import sqlite3
import json
import re
import os
from datetime import datetime, timedelta
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, filters, ContextTypes
)

# ─── НАСТРОЙКИ ───────────────────────────────────────────────────────────────
# Читаем из переменных окружения (обязательно для Railway)
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "0"))

if not BOT_TOKEN:
    raise ValueError("Переменная окружения BOT_TOKEN не задана!")
if not ADMIN_CHAT_ID:
    raise ValueError("Переменная окружения ADMIN_CHAT_ID не задана!")

# ─── ЛОГИРОВАНИЕ ─────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── СОСТОЯНИЯ CONVERSATION HANDLER ──────────────────────────────────────────
MAIN_MENU = 0
BOOKING_DATE, BOOKING_TIME, BOOKING_COMMENT = 10, 11, 12
CASTING_ROLE, CASTING_PORTFOLIO = 20, 21
PRODUCTION_TYPE, PRODUCTION_BUDGET = 30, 31
SMM_NETWORKS, SMM_NICHE = 40, 41
FORM_NAME, FORM_PHONE, FORM_CONSENT = 50, 51, 52

# ─── БАЗА ДАННЫХ ─────────────────────────────────────────────────────────────

# Путь к БД — в Railway используем /tmp (эфемерный), либо Volume
DB_PATH = os.environ.get("DB_PATH", "lexx_bot.db")

def init_db():
    """Инициализация базы данных SQLite"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            username TEXT,
            comment TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            service_type TEXT NOT NULL,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            username TEXT,
            consent INTEGER DEFAULT 0,
            additional_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()
    logger.info("База данных инициализирована: %s", DB_PATH)


def is_time_booked(date: str, time: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id FROM bookings WHERE date=? AND time=?", (date, time))
    result = cur.fetchone()
    conn.close()
    return result is not None


def save_booking(user_id, date, time, name, phone, username, comment=""):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO bookings (user_id, date, time, name, phone, username, comment)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user_id, date, time, name, phone, username, comment))
    conn.commit()
    conn.close()


def save_application(user_id, service_type, name, phone, username, additional_data):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO applications
        (user_id, service_type, name, phone, username, consent, additional_data)
        VALUES (?, ?, ?, ?, ?, 1, ?)
    """, (user_id, service_type, name, phone, username,
          json.dumps(additional_data, ensure_ascii=False)))
    conn.commit()
    conn.close()

# ─── КЛАВИАТУРЫ ──────────────────────────────────────────────────────────────

def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚖️ Юридическая помощь", callback_data="service_legal")],
        [InlineKeyboardButton("📸 Бронирование фотостудии", callback_data="service_studio")],
        [InlineKeyboardButton("🎭 Подать заявку на кастинг", callback_data="service_casting")],
        [InlineKeyboardButton("🎬 Заказать продакшен", callback_data="service_production")],
        [InlineKeyboardButton("📱 Заказать SMM", callback_data="service_smm")],
    ])


def back_and_home_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Назад", callback_data="go_back"),
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
    today = datetime.now()
    buttons = []
    row = []
    for i in range(30):
        date = today + timedelta(days=i)
        label = date.strftime("%d.%m") + (" (сег.)" if i == 0 else "")
        cb = f"date_{date.strftime('%Y-%m-%d')}"
        row.append(InlineKeyboardButton(label, callback_data=cb))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([
        InlineKeyboardButton("⬅️ Назад", callback_data="go_back"),
        InlineKeyboardButton("🏠 Главное меню", callback_data="go_home"),
    ])
    return InlineKeyboardMarkup(buttons)


def time_keyboard(selected_date: str):
    buttons = []
    row = []
    for hour in range(8, 22):
        time_str = f"{hour:02d}:00"
        if is_time_booked(selected_date, time_str):
            label = f"❌ {time_str}"
            cb = f"time_busy_{time_str}"
        else:
            label = f"✅ {time_str}"
            cb = f"time_{time_str}"
        row.append(InlineKeyboardButton(label, callback_data=cb))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([
        InlineKeyboardButton("⬅️ Назад", callback_data="go_back"),
        InlineKeyboardButton("🏠 Главное меню", callback_data="go_home"),
    ])
    return InlineKeyboardMarkup(buttons)


def production_type_keyboard():
    types = ["Реклама", "Клип", "Фильм", "Корпоративное видео", "Другое"]
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(t, callback_data=f"prod_type_{t}")] for t in types] +
        [[
            InlineKeyboardButton("⬅️ Назад", callback_data="go_back"),
            InlineKeyboardButton("🏠 Главное меню", callback_data="go_home"),
        ]]
    )

# ─── ТЕКСТЫ ──────────────────────────────────────────────────────────────────

WELCOME_TEXT = """
👋 Добро пожаловать в <b>LEXX^</b> — многофункциональное креативное агентство!

Мы объединяем под одной крышей:

⚖️ <b>Юридическая помощь</b> — консультации, документы, проверка договоров

📸 <b>Фотостудия</b> — профессиональная съёмка, бронирование времени

🎭 <b>Кастинги</b> — участие в проектах агентства

🎬 <b>Продакшен</b> — полный цикл производства видео и контента

📱 <b>SMM-услуги</b> — ведение соцсетей, стратегии, контент

Выберите нужное направление:
"""

# ─── ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ─────────────────────────────────────────────────

def validate_phone(phone: str) -> bool:
    return len(re.sub(r"\D", "", phone)) >= 10


def get_username(user) -> str:
    return f"@{user.username}" if user.username else f"ID:{user.id}"


async def send_admin_notification(context, text: str):
    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID, text=text, parse_mode="HTML"
        )
    except Exception as e:
        logger.error("Ошибка уведомления администратора: %s", e)


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE,
                         edit: bool = False):
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(
            WELCOME_TEXT, reply_markup=main_menu_keyboard(), parse_mode="HTML"
        )
    else:
        target = update.message or update.callback_query.message
        await target.reply_text(
            WELCOME_TEXT, reply_markup=main_menu_keyboard(), parse_mode="HTML"
        )

# ─── КОМАНДЫ ─────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        WELCOME_TEXT, reply_markup=main_menu_keyboard(), parse_mode="HTML"
    )
    return MAIN_MENU

# ─── ВЫБОР УСЛУГИ ────────────────────────────────────────────────────────────

async def handle_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "go_home":
        context.user_data.clear()
        await show_main_menu(update, context, edit=True)
        return MAIN_MENU

    if data == "service_legal":
        context.user_data.update({"service": "legal", "service_name": "⚖️ Юридическая помощь"})
        await query.edit_message_text(
            "⚖️ <b>Юридическая помощь</b>\n\n"
            "Наши юристы помогут с:\n"
            "• Консультациями по любым вопросам\n"
            "• Подготовкой и анализом документов\n"
            "• Проверкой договоров\n\n"
            "⚠️ <i>Мы НЕ занимаемся представительством в суде.</i>\n\n"
            "Введите ваше <b>имя</b>:",
            reply_markup=back_and_home_keyboard(), parse_mode="HTML"
        )
        return FORM_NAME

    elif data == "service_studio":
        context.user_data.update({"service": "studio", "service_name": "📸 Бронирование фотостудии"})
        await query.edit_message_text(
            "📸 <b>Бронирование фотостудии</b>\n\n"
            "🕐 Работаем с <b>8:00 до 21:00</b>, шаг — 1 час\n\n"
            "Выберите <b>дату</b>:",
            reply_markup=date_keyboard(), parse_mode="HTML"
        )
        return BOOKING_DATE

    elif data == "service_casting":
        context.user_data.update({"service": "casting", "service_name": "🎭 Кастинг"})
        await query.edit_message_text(
            "🎭 <b>Заявка на кастинг</b>\n\n"
            "Укажите ваше <b>амплуа / роль</b>\n"
            "(например: актёр, модель, ведущий):",
            reply_markup=back_and_home_keyboard(), parse_mode="HTML"
        )
        return CASTING_ROLE

    elif data == "service_production":
        context.user_data.update({"service": "production", "service_name": "🎬 Продакшен"})
        await query.edit_message_text(
            "🎬 <b>Заказ продакшн-услуг</b>\n\n"
            "Полный цикл: от идеи до готового продукта.\n\n"
            "Выберите <b>тип проекта</b>:",
            reply_markup=production_type_keyboard(), parse_mode="HTML"
        )
        return PRODUCTION_TYPE

    elif data == "service_smm":
        context.user_data.update({"service": "smm", "service_name": "📱 SMM"})
        await query.edit_message_text(
            "📱 <b>Заказ SMM-услуг</b>\n\n"
            "Ведение соцсетей, контент, рекламные стратегии.\n\n"
            "Укажите <b>соцсети для ведения</b>\n"
            "(например: Instagram, VK, TikTok):",
            reply_markup=back_and_home_keyboard(), parse_mode="HTML"
        )
        return SMM_NETWORKS

    return MAIN_MENU

# ─── ФОТОСТУДИЯ ──────────────────────────────────────────────────────────────

async def booking_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "go_home":
        context.user_data.clear()
        await show_main_menu(update, context, edit=True)
        return MAIN_MENU
    if query.data == "go_back":
        await query.edit_message_text(WELCOME_TEXT, reply_markup=main_menu_keyboard(), parse_mode="HTML")
        return MAIN_MENU
    selected_date = query.data.replace("date_", "")
    context.user_data["booking_date"] = selected_date
    display_date = datetime.strptime(selected_date, "%Y-%m-%d").strftime("%d.%m.%Y")
    await query.edit_message_text(
        f"📅 Дата: <b>{display_date}</b>\n\n✅ — свободно   ❌ — занято\n\nВыберите <b>время</b>:",
        reply_markup=time_keyboard(selected_date), parse_mode="HTML"
    )
    return BOOKING_TIME


async def booking_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "go_home":
        context.user_data.clear()
        await show_main_menu(update, context, edit=True)
        return MAIN_MENU
    if query.data == "go_back":
        await query.edit_message_text(
            "📸 <b>Бронирование</b>\n\nВыберите <b>дату</b>:",
            reply_markup=date_keyboard(), parse_mode="HTML"
        )
        return BOOKING_DATE
    if query.data.startswith("time_busy_"):
        await query.answer("❌ Это время занято. Выберите другое.", show_alert=True)
        return BOOKING_TIME
    selected_time = query.data.replace("time_", "")
    context.user_data["booking_time"] = selected_time
    selected_date = context.user_data["booking_date"]
    display_date = datetime.strptime(selected_date, "%Y-%m-%d").strftime("%d.%m.%Y")
    await query.edit_message_text(
        f"📅 Дата: <b>{display_date}</b>\n🕐 Время: <b>{selected_time}</b>\n\n"
        "Оставьте <b>комментарий</b> (необязательно).\n"
        "Тип съёмки, кол-во человек и т.д.\n\n"
        "Или введите <b>«—»</b> чтобы пропустить.",
        reply_markup=back_and_home_keyboard(), parse_mode="HTML"
    )
    return BOOKING_COMMENT


async def booking_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["booking_comment"] = "" if text == "—" else text
    await update.message.reply_text(
        "Введите ваше <b>имя</b>:", reply_markup=home_keyboard(), parse_mode="HTML"
    )
    return FORM_NAME

# ─── КАСТИНГ ─────────────────────────────────────────────────────────────────

async def casting_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if len(text) < 2:
        await update.message.reply_text("⚠️ Укажите амплуа (минимум 2 символа):", reply_markup=home_keyboard())
        return CASTING_ROLE
    context.user_data["casting_role"] = text
    await update.message.reply_text(
        "Укажите <b>ссылку на портфолио</b> (необязательно).\nИли введите <b>«—»</b>:",
        reply_markup=home_keyboard(), parse_mode="HTML"
    )
    return CASTING_PORTFOLIO


async def casting_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["casting_portfolio"] = "" if text == "—" else text
    await update.message.reply_text(
        "Введите ваше <b>имя</b>:", reply_markup=home_keyboard(), parse_mode="HTML"
    )
    return FORM_NAME

# ─── ПРОДАКШЕН ───────────────────────────────────────────────────────────────

async def production_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "go_home":
        context.user_data.clear()
        await show_main_menu(update, context, edit=True)
        return MAIN_MENU
    if query.data == "go_back":
        await query.edit_message_text(WELCOME_TEXT, reply_markup=main_menu_keyboard(), parse_mode="HTML")
        return MAIN_MENU
    prod_type = query.data.replace("prod_type_", "")
    context.user_data["production_type"] = prod_type
    await query.edit_message_text(
        f"🎬 Тип проекта: <b>{prod_type}</b>\n\n"
        "Укажите <b>бюджет</b> (необязательно).\nИли введите <b>«—»</b>:",
        reply_markup=back_and_home_keyboard(), parse_mode="HTML"
    )
    return PRODUCTION_BUDGET


async def production_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["production_budget"] = "" if text == "—" else text
    await update.message.reply_text(
        "Введите ваше <b>имя</b>:", reply_markup=home_keyboard(), parse_mode="HTML"
    )
    return FORM_NAME

# ─── SMM ─────────────────────────────────────────────────────────────────────

async def smm_networks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if len(text) < 2:
        await update.message.reply_text("⚠️ Укажите хотя бы одну соцсеть:", reply_markup=home_keyboard())
        return SMM_NETWORKS
    context.user_data["smm_networks"] = text
    await update.message.reply_text(
        "Укажите <b>тематику / нишу</b> бизнеса\n(например: ресторан, beauty, строительство):",
        reply_markup=home_keyboard(), parse_mode="HTML"
    )
    return SMM_NICHE


async def smm_niche(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if len(text) < 2:
        await update.message.reply_text("⚠️ Укажите тематику / нишу:", reply_markup=home_keyboard())
        return SMM_NICHE
    context.user_data["smm_niche"] = text
    await update.message.reply_text(
        "Введите ваше <b>имя</b>:", reply_markup=home_keyboard(), parse_mode="HTML"
    )
    return FORM_NAME

# ─── ОБЩАЯ ФОРМА ─────────────────────────────────────────────────────────────

async def form_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if len(text) < 2:
        await update.message.reply_text(
            "⚠️ Имя слишком короткое. Введите <b>имя</b> ещё раз:",
            reply_markup=home_keyboard(), parse_mode="HTML"
        )
        return FORM_NAME
    context.user_data["form_name"] = text
    await update.message.reply_text(
        f"Приятно познакомиться, <b>{text}</b>! 👋\n\nВведите ваш <b>номер телефона</b>:",
        reply_markup=home_keyboard(), parse_mode="HTML"
    )
    return FORM_PHONE


async def form_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    if not validate_phone(phone):
        await update.message.reply_text(
            "⚠️ Некорректный номер. Введите <b>телефон</b> (минимум 10 цифр):",
            reply_markup=home_keyboard(), parse_mode="HTML"
        )
        return FORM_PHONE
    context.user_data["form_phone"] = phone
    context.user_data["form_username"] = get_username(update.effective_user)

    service_name = context.user_data.get("service_name", "Услуга")
    service = context.user_data.get("service", "")

    summary = (
        f"📋 <b>Проверьте данные заявки:</b>\n\n"
        f"🔹 Услуга: {service_name}\n"
        f"🔹 Имя: {context.user_data['form_name']}\n"
        f"🔹 Телефон: {phone}\n"
        f"🔹 Telegram: {context.user_data['form_username']}\n"
    )
    if service == "studio":
        d = context.user_data.get("booking_date", "")
        dd = datetime.strptime(d, "%Y-%m-%d").strftime("%d.%m.%Y") if d else "—"
        summary += f"🔹 Дата: {dd}\n🔹 Время: {context.user_data.get('booking_time','—')}\n"
        if context.user_data.get("booking_comment"):
            summary += f"🔹 Комментарий: {context.user_data['booking_comment']}\n"
    elif service == "casting":
        summary += f"🔹 Амплуа: {context.user_data.get('casting_role','—')}\n"
        if context.user_data.get("casting_portfolio"):
            summary += f"🔹 Портфолио: {context.user_data['casting_portfolio']}\n"
    elif service == "production":
        summary += f"🔹 Тип проекта: {context.user_data.get('production_type','—')}\n"
        if context.user_data.get("production_budget"):
            summary += f"🔹 Бюджет: {context.user_data['production_budget']}\n"
    elif service == "smm":
        summary += f"🔹 Соцсети: {context.user_data.get('smm_networks','—')}\n"
        summary += f"🔹 Ниша: {context.user_data.get('smm_niche','—')}\n"

    summary += "\n📌 Для отправки необходимо дать согласие на обработку персональных данных:"
    await update.message.reply_text(summary, reply_markup=consent_keyboard(), parse_mode="HTML")
    return FORM_CONSENT


async def form_consent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "go_home":
        context.user_data.clear()
        await show_main_menu(update, context, edit=True)
        return MAIN_MENU
    if query.data != "consent_yes":
        return FORM_CONSENT

    user_id      = update.effective_user.id
    service      = context.user_data.get("service", "unknown")
    service_name = context.user_data.get("service_name", "Услуга")
    name         = context.user_data.get("form_name", "")
    phone        = context.user_data.get("form_phone", "")
    username     = context.user_data.get("form_username", "")
    additional   = {}

    if service == "studio":
        additional = {
            "date":    context.user_data.get("booking_date", ""),
            "time":    context.user_data.get("booking_time", ""),
            "comment": context.user_data.get("booking_comment", ""),
        }
        if is_time_booked(additional["date"], additional["time"]):
            await query.edit_message_text(
                "⚠️ Это время уже <b>занято</b>.\n\nНачните бронирование заново.",
                reply_markup=home_keyboard(), parse_mode="HTML"
            )
            return MAIN_MENU
        save_booking(user_id, additional["date"], additional["time"],
                     name, phone, username, additional.get("comment",""))
    elif service == "casting":
        additional = {
            "role":      context.user_data.get("casting_role", ""),
            "portfolio": context.user_data.get("casting_portfolio", ""),
        }
    elif service == "production":
        additional = {
            "type":   context.user_data.get("production_type", ""),
            "budget": context.user_data.get("production_budget", ""),
        }
    elif service == "smm":
        additional = {
            "networks": context.user_data.get("smm_networks", ""),
            "niche":    context.user_data.get("smm_niche", ""),
        }

    save_application(user_id, service, name, phone, username, additional)

    # Уведомление администратору
    admin_text = (
        f"🔔 <b>НОВАЯ ЗАЯВКА — LEXX^</b>\n\n"
        f"📋 Услуга: <b>{service_name}</b>\n"
        f"👤 Имя: {name}\n📞 Телефон: {phone}\n"
        f"💬 Telegram: {username}\n🆔 User ID: {user_id}\n"
    )
    if service == "studio":
        d = additional.get("date", "")
        dd = datetime.strptime(d, "%Y-%m-%d").strftime("%d.%m.%Y") if d else "—"
        admin_text += f"📅 Дата: {dd}\n🕐 Время: {additional.get('time','—')}\n"
        if additional.get("comment"):
            admin_text += f"💬 Комментарий: {additional['comment']}\n"
    elif service == "casting":
        admin_text += f"🎭 Амплуа: {additional.get('role','—')}\n"
        if additional.get("portfolio"):
            admin_text += f"🔗 Портфолио: {additional['portfolio']}\n"
    elif service == "production":
        admin_text += f"🎬 Тип: {additional.get('type','—')}\n"
        if additional.get("budget"):
            admin_text += f"💰 Бюджет: {additional['budget']}\n"
    elif service == "smm":
        admin_text += f"📱 Соцсети: {additional.get('networks','—')}\n"
        admin_text += f"🏷 Ниша: {additional.get('niche','—')}\n"
    admin_text += f"\n🕒 {datetime.now().strftime('%d.%m.%Y %H:%M')}"

    await send_admin_notification(context, admin_text)

    await query.edit_message_text(
        "✅ <b>Спасибо! Ваша заявка принята.</b>\n\n"
        "Мы свяжемся с вами в ближайшее время.\n\n"
        "Хотите выбрать ещё одну услугу?",
        reply_markup=home_keyboard(), parse_mode="HTML"
    )
    context.user_data.clear()
    return ConversationHandler.END

# ─── СЛУЖЕБНЫЕ ОБРАБОТЧИКИ ───────────────────────────────────────────────────

async def go_home_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await show_main_menu(update, context, edit=True)
    return MAIN_MENU


async def unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤔 Используйте кнопки меню.\nНажмите /start чтобы начать заново.",
        reply_markup=home_keyboard()
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Ошибка бота: %s", context.error, exc_info=context.error)

# ─── ЗАПУСК ──────────────────────────────────────────────────────────────────

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CallbackQueryHandler(go_home_callback, pattern="^go_home$"),
        ],
        states={
            MAIN_MENU:        [CallbackQueryHandler(handle_service, pattern="^service_|^go_home$")],
            BOOKING_DATE:     [CallbackQueryHandler(booking_date, pattern="^date_|^go_back$|^go_home$")],
            BOOKING_TIME:     [CallbackQueryHandler(booking_time, pattern="^time_|^go_back$|^go_home$")],
            BOOKING_COMMENT:  [
                MessageHandler(filters.TEXT & ~filters.COMMAND, booking_comment),
                CallbackQueryHandler(go_home_callback, pattern="^go_home$"),
            ],
            CASTING_ROLE:     [
                MessageHandler(filters.TEXT & ~filters.COMMAND, casting_role),
                CallbackQueryHandler(go_home_callback, pattern="^go_home$"),
            ],
            CASTING_PORTFOLIO:[
                MessageHandler(filters.TEXT & ~filters.COMMAND, casting_portfolio),
                CallbackQueryHandler(go_home_callback, pattern="^go_home$"),
            ],
            PRODUCTION_TYPE:  [CallbackQueryHandler(production_type, pattern="^prod_type_|^go_back$|^go_home$")],
            PRODUCTION_BUDGET:[
                MessageHandler(filters.TEXT & ~filters.COMMAND, production_budget),
                CallbackQueryHandler(go_home_callback, pattern="^go_home$"),
            ],
            SMM_NETWORKS:     [
                MessageHandler(filters.TEXT & ~filters.COMMAND, smm_networks),
                CallbackQueryHandler(go_home_callback, pattern="^go_home$"),
            ],
            SMM_NICHE:        [
                MessageHandler(filters.TEXT & ~filters.COMMAND, smm_niche),
                CallbackQueryHandler(go_home_callback, pattern="^go_home$"),
            ],
            FORM_NAME:        [
                MessageHandler(filters.TEXT & ~filters.COMMAND, form_name),
                CallbackQueryHandler(go_home_callback, pattern="^go_home$"),
            ],
            FORM_PHONE:       [
                MessageHandler(filters.TEXT & ~filters.COMMAND, form_phone),
                CallbackQueryHandler(go_home_callback, pattern="^go_home$"),
            ],
            FORM_CONSENT:     [CallbackQueryHandler(form_consent, pattern="^consent_yes$|^go_home$")],
        },
        fallbacks=[
            CommandHandler("start", start),
            CallbackQueryHandler(go_home_callback, pattern="^go_home$"),
            MessageHandler(filters.ALL, unknown_message),
        ],
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_error_handler(error_handler)
    logger.info("Бот LEXX^ запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
