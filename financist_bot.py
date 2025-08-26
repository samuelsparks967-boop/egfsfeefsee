import sqlite3
import logging
from datetime import datetime, date, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
import warnings
import re
import os

# Подавление предупреждений о совместимости
warnings.filterwarnings("ignore", category=DeprecationWarning)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Конфигурация ---
# !!! ЗАМЕНИТЕ ЭТО НА ВАШИ ДАННЫЕ !!!
BOT_TOKEN = "8403274842:AAE5e8NrcWqUR09Ula9224-8hSA00KMGqp0"  # Замените на ваш токен бота
ADMIN_USER_IDS = [7610385492]

# --- Управление базой данных ---
class FinancistBot:
    def __init__(self, db_path="financist.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Инициализация базы данных"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY,
                        value REAL
                    )
                ''')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS applications (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_nickname TEXT NOT NULL,
                        initial_amount REAL NOT NULL,
                        rate_percentage REAL NOT NULL,
                        final_amount REAL NOT NULL,
                        bank TEXT,
                        status TEXT DEFAULT 'active',
                        creation_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        processing_user TEXT,
                        blocking_date TIMESTAMP,
                        archived_date TIMESTAMP
                    )
                ''')
                
                try:
                    cursor.execute('ALTER TABLE applications ADD COLUMN bank TEXT')
                    conn.commit()
                except sqlite3.OperationalError:
                    pass

                try:
                    cursor.execute('ALTER TABLE applications ADD COLUMN processing_user TEXT')
                    conn.commit()
                except sqlite3.OperationalError:
                    pass

                try:
                    cursor.execute('ALTER TABLE applications ADD COLUMN blocking_date TIMESTAMP')
                    conn.commit()
                except sqlite3.OperationalError:
                    pass

                try:
                    cursor.execute('ALTER TABLE applications ADD COLUMN archived_date TIMESTAMP')
                    conn.commit()
                except sqlite3.OperationalError:
                    pass
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS debts (
                        user_nickname TEXT PRIMARY KEY,
                        debt_amount REAL DEFAULT 0
                    )
                ''')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS balance (
                        id INTEGER PRIMARY KEY DEFAULT 1,
                        total_profit REAL DEFAULT 0
                    )
                ''')
                
                cursor.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', 
                               ('current_rate', 5.0))
                cursor.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', 
                               ('admin_chat_id', 0))
                cursor.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', 
                               ('currency_rate', 100.0))
                
                cursor.execute('INSERT OR IGNORE INTO balance (id, total_profit) VALUES (?, ?)', 
                               (1, 0.0))
                
                conn.commit()
                logger.info("База данных успешно инициализирована")
        except Exception as e:
            logger.error(f"Ошибка при инициализации базы данных: {e}")
            raise
    
    def get_setting(self, key):
        """Получить настройку"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
                result = cursor.fetchone()
                return result[0] if result else None
        except Exception as e:
            logger.error(f"Ошибка при получении настройки {key}: {e}")
            return None
    
    def set_setting(self, key, value):
        """Установить настройку"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', 
                               (key, value))
                conn.commit()
                logger.info(f"Настройка {key} установлена в значение {value}")
        except Exception as e:
            logger.error(f"Ошибка при установке настройки {key}: {e}")
            raise
    
    def is_admin(self, user_id):
        """Проверка, является ли пользователь администратором"""
        return user_id in ADMIN_USER_IDS
    
    def is_admin_chat(self, chat_id):
        """Проверка, является ли чат админским"""
        admin_chat_id = self.get_setting('admin_chat_id')
        return abs(chat_id - admin_chat_id) < 0.0001

# Создание экземпляра бота
try:
    bot_instance = FinancistBot()
except Exception as e:
    logger.error(f"Не удалось создать экземпляр бота: {e}")
    exit(1)

# ================== УТИЛИТАРНЫЕ ФУНКЦИИ ==================

def get_app_id_from_reply(update: Update):
    """Извлекает ID заявки из сообщения, на которое был сделан ответ."""
    try:
        if not update.message.reply_to_message:
            return None
        
        text = update.message.reply_to_message.text
        if not text:
            return None
            
        match = re.search(r'Заявка №(\d+)', text)
        return int(match.group(1)) if match else None
    except Exception as e:
        logger.error(f"Ошибка при получении ID заявки из ответа: {e}")
        return None

# ================== КОМАНДЫ ==================

async def set_rate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /percent [число]"""
    if not bot_instance.is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Доступ запрещен. Команда только для администраторов.")
        return
    
    try:
        if not context.args or len(context.args) != 1:
            await update.message.reply_text("❌ Использование: /percent [число]")
            return
        
        rate = float(context.args[0])
        if rate < 0 or rate > 100:
            await update.message.reply_text("❌ Процентная ставка должна быть от 0 до 100.")
            return
        
        bot_instance.set_setting('current_rate', rate)
        await update.message.reply_text(f"✅ Новая процентная ставка установлена: {rate:.1f}%")
        
    except ValueError:
        await update.message.reply_text("❌ Неверный формат числа.")
    except Exception as e:
        logger.error(f"Ошибка в команде /percent: {e}")
        await update.message.reply_text("❌ Произошла ошибка при выполнении команды.")

async def create_application_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /app [ник_пользователя] [сумма] [банк]"""
    if not bot_instance.is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Доступ запрещен. Команда только для администраторов.")
        return

    try:
        if not context.args or len(context.args) != 3:
            await update.message.reply_text("❌ Использование: /app [ник_пользователя] [сумма] [банк]")
            return
        
        user_nickname = context.args[0]
        initial_amount = float(context.args[1])
        bank = context.args[2]
        
        if initial_amount <= 0:
            await update.message.reply_text("❌ Сумма должна быть положительной.")
            return
        
        current_rate = bot_instance.get_setting('current_rate')
        final_amount = initial_amount * (1 - current_rate / 100)
        
        with sqlite3.connect(bot_instance.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO applications (user_nickname, initial_amount, rate_percentage, final_amount, bank)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_nickname, initial_amount, current_rate, final_amount, bank))
            
            app_id = cursor.lastrowid
            conn.commit()
        
        message = f"""#️⃣ Заявка №{app_id}
Сумма: {initial_amount:.0f}₽
Банк: {bank}
Ставка: {current_rate:.1f}%
К переводу: {final_amount:.0f}₽
Статус: В ожидании"""
        
        await update.message.reply_text(message)
        
    except ValueError:
        await update.message.reply_text("❌ Неверный формат суммы.")
    except Exception as e:
        logger.error(f"Ошибка при создании заявки: {e}")
        await update.message.reply_text("❌ Произошла ошибка при создании заявки.")

async def in_progress_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /in_progress [номер_заявки] или ответ на сообщение"""
    if not bot_instance.is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Доступ запрещен. Команда только для администраторов.")
        return

    try:
        app_id = None
        if context.args:
            app_id = int(context.args[0])
        else:
            app_id = get_app_id_from_reply(update)
        
        if not app_id:
            await update.message.reply_text("❌ Укажите номер заявки или ответьте на сообщение с заявкой.")
            return

        with sqlite3.connect(bot_instance.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM applications WHERE id = ? AND status = ?', 
                           (app_id, 'active'))
            application = cursor.fetchone()
            
            if not application:
                await update.message.reply_text("❌ Активная заявка с таким номером не найдена.")
                return

            processing_user = update.effective_user.username or update.effective_user.first_name
            cursor.execute('''
                UPDATE applications 
                SET status = 'in_progress', processing_user = ?
                WHERE id = ?
            ''', (processing_user, app_id))
            conn.commit()
            
            message = f"""🔄 Заявка №{app_id}
Статус: в работе
Сумма: {application[2]:.0f}₽
Банк: {application[5]}
Ставка: {application[3]:.1f}%
К переводу: {application[4]:.0f}₽
Принимал: @{processing_user}"""
            
            await update.message.reply_text(message)
            
    except ValueError:
        await update.message.reply_text("❌ Неверный формат номера заявки.")
    except Exception as e:
        logger.error(f"Ошибка в команде /in_progress: {e}")
        await update.message.reply_text("❌ Произошла ошибка при выполнении команды.")


async def accept_application_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /accept [номер_заявки] или ответ на сообщение"""
    if not bot_instance.is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Доступ запрещен. Команда только для администраторов.")
        return

    try:
        app_id = None
        if context.args:
            app_id = int(context.args[0])
        else:
            app_id = get_app_id_from_reply(update)

        if not app_id:
            await update.message.reply_text("❌ Укажите номер заявки или ответьте на сообщение с заявкой.")
            return
        
        with sqlite3.connect(bot_instance.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM applications WHERE id = ? AND status IN (?, ?)', 
                           (app_id, 'active', 'in_progress'))
            application = cursor.fetchone()
            
            if not application:
                await update.message.reply_text("❌ Активная заявка с таким номером не найдена.")
                return
            
            processing_user = update.effective_user.username or update.effective_user.first_name
            blocking_date = datetime.now()
            cursor.execute('''
                UPDATE applications 
                SET status = 'completed', blocking_date = ?, processing_user = ?
                WHERE id = ?
            ''', (blocking_date, processing_user, app_id))
            conn.commit()
            
            message = f"""✅ Заявка №{app_id}
Статус: завершена
Принимал: @{processing_user}"""
            
            await update.message.reply_text(message)
            
    except ValueError:
        await update.message.reply_text("❌ Неверный формат номера заявки.")
    except Exception as e:
        logger.error(f"Ошибка при завершении заявки: {e}")
        await update.message.reply_text("❌ Произошла ошибка при завершении заявки.")


async def chewed_application_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /chewed [номер_заявки] или ответ на сообщение"""
    if not bot_instance.is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Доступ запрещен. Команда только для администраторов.")
        return
        
    try:
        app_id = None
        if context.args:
            app_id = int(context.args[0])
        else:
            app_id = get_app_id_from_reply(update)

        if not app_id:
            await update.message.reply_text("❌ Укажите номер заявки или ответьте на сообщение с заявкой.")
            return
        
        with sqlite3.connect(bot_instance.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM applications WHERE id = ? AND status IN (?, ?)', 
                           (app_id, 'active', 'in_progress'))
            application = cursor.fetchone()
            
            if not application:
                await update.message.reply_text("❌ Активная заявка с таким номером не найдена.")
                return
            
            processing_user = update.effective_user.username or update.effective_user.first_name
            blocking_date = datetime.now()
            cursor.execute('''
                UPDATE applications 
                SET status = 'chewed', blocking_date = ?, processing_user = ?
                WHERE id = ?
            ''', (blocking_date, processing_user, app_id))
            conn.commit()
            
            message = f"""⚠️ Заявка №{app_id}
Сумма: {application[2]:.0f}₽
Банк: {application[5]}
Принимал: @{processing_user}
Статус: Банкомат зажевал"""
            
            await update.message.reply_text(message)
            
    except ValueError:
        await update.message.reply_text("❌ Неверный формат номера заявки.")
    except Exception as e:
        logger.error(f"Ошибка в команде /chewed: {e}")
        await update.message.reply_text("❌ Произошла ошибка при выполнении команды.")


async def add_debt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /debt [пользователь] [сумма]"""
    if not bot_instance.is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Доступ запрещен. Команда только для администраторов.")
        return
        
    try:
        if not context.args or len(context.args) != 2:
            await update.message.reply_text("❌ Использование: /debt [пользователь] [сумма]")
            return
        
        user_nickname = context.args[0]
        amount = float(context.args[1])
        
        if amount <= 0:
            await update.message.reply_text("❌ Сумма должна быть положительной.")
            return
        
        with sqlite3.connect(bot_instance.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT debt_amount FROM debts WHERE user_nickname = ?', 
                           (user_nickname,))
            existing_debt = cursor.fetchone()
            
            if existing_debt:
                new_amount = existing_debt[0] + amount
                cursor.execute('UPDATE debts SET debt_amount = ? WHERE user_nickname = ?', 
                               (new_amount, user_nickname))
            else:
                new_amount = amount
                cursor.execute('INSERT INTO debts (user_nickname, debt_amount) VALUES (?, ?)', 
                               (user_nickname, amount))
            
            conn.commit()
            
        await update.message.reply_text(
            f"✅ Записано: {user_nickname} теперь должен {new_amount:.0f}₽"
        )
        
    except ValueError:
        await update.message.reply_text("❌ Неверный формат суммы.")
    except Exception as e:
        logger.error(f"Ошибка при добавлении долга: {e}")
        await update.message.reply_text("❌ Произошла ошибка при добавлении долга.")

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /balance [сумма] - пополнить или показать баланс"""
    if not bot_instance.is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Доступ запрещен. Команда только для администраторов.")
        return
        
    try:
        chat_id = update.effective_chat.id
        
        if not bot_instance.is_admin_chat(chat_id):
            await update.message.reply_text("❌ Эта команда доступна только в админском чате.")
            return
        
        with sqlite3.connect(bot_instance.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT total_profit FROM balance WHERE id = 1')
            current_balance = cursor.fetchone()[0]
        
        if not context.args:
            await update.message.reply_text(f"💰 Текущий баланс: {current_balance:.2f}$")
            return
            
        amount = float(context.args[0])
        
        with sqlite3.connect(bot_instance.db_path) as conn:
            cursor = conn.cursor()
            new_balance = current_balance + amount
            cursor.execute('UPDATE balance SET total_profit = ? WHERE id = 1', (new_balance,))
            conn.commit()
        
        await update.message.reply_text(
            f"✅ Баланс пополнен на {amount:.2f}$. Текущий баланс: {new_balance:.2f}$"
        )
        
    except ValueError:
        await update.message.reply_text("❌ Неверный формат суммы.")
    except Exception as e:
        logger.error(f"Ошибка при пополнении баланса: {e}")
        await update.message.reply_text("❌ Произошла ошибка при пополнении баланса.")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /stats"""
    if not bot_instance.is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Доступ запрещен. Команда только для администраторов.")
        return

    try:
        chat_title = update.effective_chat.title or "Личный чат"
        current_date = datetime.now().strftime('%d.%m.%Y')
        
        with sqlite3.connect(bot_instance.db_path) as conn:
            cursor = conn.cursor()
            
            currency_rate = bot_instance.get_setting('currency_rate')
            
            cursor.execute('''
                SELECT id, initial_amount, rate_percentage, final_amount, user_nickname, bank, status 
                FROM applications WHERE status = 'active' OR status = 'in_progress'
                ORDER BY id
            ''')
            active_applications = cursor.fetchall()
            
            today = date.today().isoformat()
            cursor.execute('''
                SELECT id, initial_amount, rate_percentage, final_amount, user_nickname, bank 
                FROM applications 
                WHERE status = 'completed' AND date(blocking_date) = ?
                ORDER BY id
            ''', (today,))
            today_completed = cursor.fetchall()

            cursor.execute('''
                SELECT id, initial_amount, rate_percentage, final_amount, user_nickname, bank 
                FROM applications 
                WHERE status = 'blocked' AND date(blocking_date) = ?
                ORDER BY id
            ''', (today,))
            today_blocked = cursor.fetchall()
            
            cursor.execute('''
                SELECT id, initial_amount, rate_percentage, final_amount, user_nickname, bank
                FROM applications 
                WHERE status = 'chewed' AND date(blocking_date) = ?
                ORDER BY id
            ''', (today,))
            today_chewed = cursor.fetchall()
            
            cursor.execute('SELECT SUM(initial_amount) FROM applications WHERE status = "active" OR status = "in_progress"')
            total_waiting = cursor.fetchone()[0] or 0
            
            cursor.execute('''
                SELECT SUM(initial_amount) FROM applications WHERE status = "completed"
            ''')
            total_processed_rub = cursor.fetchone()[0] or 0
            
            cursor.execute('''
                SELECT SUM(initial_amount) FROM applications WHERE status = "blocked"
            ''')
            total_blocked_rub = cursor.fetchone()[0] or 0

            cursor.execute('''
                SELECT SUM(initial_amount) FROM applications WHERE status = "chewed"
            ''')
            total_chewed_rub = cursor.fetchone()[0] or 0
            
            cursor.execute('''
                SELECT SUM(final_amount) FROM applications WHERE status = "completed"
            ''')
            total_paid_rub = cursor.fetchone()[0] or 0
            total_paid_usd = total_paid_rub / currency_rate if currency_rate > 0 else 0
            
            cursor.execute('SELECT user_nickname, debt_amount FROM debts WHERE debt_amount > 0')
            debtors = cursor.fetchall()
            
        message = f"""👨‍💻 {chat_title} | {current_date}
⚜️ Статистика:

Активные заявки (в ожидании и в работе):"""
        
        if active_applications:
            for app in active_applications:
                app_id, initial, _, _, nickname, bank, status = app
                status_emoji = "🕐" if status == 'active' else "🔄"
                message += f"\n{status_emoji} Заявка №{app_id} | {nickname} | {initial:.0f}₽ | {bank}"
        else:
            message += "\nНет активных заявок"
        
        message += f"\n\nВыполненные заявки за сегодня ({len(today_completed)}):"
        
        if today_completed:
            for app in today_completed:
                app_id, initial, rate, final, nickname, bank = app
                usd_amount = final / currency_rate if currency_rate > 0 else 0
                message += f"\n✅ Заявка №{app_id} | {nickname} | {initial:.0f}₽ ({bank}) - {rate:.1f}% = {usd_amount:.2f}$"
        else:
            message += "\nНет выполненных заявок за сегодня"

        message += f"\n\nЗаблокированные заявки за сегодня ({len(today_blocked)}):"
        if today_blocked:
            for app in today_blocked:
                app_id, initial, _, _, nickname, bank = app
                message += f"\n❌ Заявка №{app_id} | {nickname} | {initial:.0f}₽ ({bank})"
        else:
            message += "\nНет заблокированных заявок за сегодня"
        
        message += f"\n\nЗажеванные заявки за сегодня ({len(today_chewed)}):"
        if today_chewed:
            for app in today_chewed:
                app_id, initial, _, _, nickname, bank = app
                message += f"\n⚠️ Заявка №{app_id} | {nickname} | {initial:.0f}₽ ({bank})"
        else:
            message += "\nНет зажеванных заявок за сегодня"

        message += f"""

Общая сводка:
🕐 Ожидаем: {total_waiting:.0f}₽
✅ Обработано заявок на сумму: {total_processed_rub:.0f}₽
❌ Заблокировано заявок на сумму: {total_blocked_rub:.0f}₽
⚠️ Зажевано заявок на сумму: {total_chewed_rub:.0f}₽
💸 Выплачено: {total_paid_usd:.2f}$

Должники:"""
        
        if debtors:
            for nickname, amount in debtors:
                message += f"\n- {nickname}: {amount:.0f}₽"
        else:
            message += "\nНет должников"
        
        await update.message.reply_text(message)
        
    except Exception as e:
        logger.error(f"Ошибка при генерации статистики: {e}")
        await update.message.reply_text("❌ Произошла ошибка при генерации статистики.")


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /reset - сбрасывает все активные заявки и отправляет дневной отчёт
    в админский чат.
    """
    user_id = update.effective_user.id
    
    if not bot_instance.is_admin(user_id):
        await update.message.reply_text("❌ Доступ запрещен. Команда только для администраторов.")
        return
        
    admin_chat_id = bot_instance.get_setting('admin_chat_id')
    if not admin_chat_id:
        await update.message.reply_text("❌ Админский чат не установлен. Используйте /set_admin_chat.")
        return

    daily_stats_message = await generate_daily_stats()
    if daily_stats_message:
        await context.bot.send_message(chat_id=int(admin_chat_id), text="📈 **Дневной отчёт перед сбросом:**\n\n" + daily_stats_message, parse_mode='Markdown')
        await update.message.reply_text("✅ Статистика за день была успешно отправлена в админский чат.")

    try:
        with sqlite3.connect(bot_instance.db_path) as conn:
            cursor = conn.cursor()
            
            archived_date = datetime.now()
            
            cursor.execute('''
                UPDATE applications
                SET status = 'archived', archived_date = ?
                WHERE status IN ('active', 'in_progress', 'chewed', 'blocked')
            ''', (archived_date,))
            
            rows_updated = cursor.rowcount
            conn.commit()
            
        await update.message.reply_text(f"✅ Заявки успешно сброшены. Всего архивировано: {rows_updated}")
        
    except Exception as e:
        logger.error(f"Ошибка при сбросе заявок: {e}")
        await update.message.reply_text("❌ Произошла ошибка при сбросе заявок.")

async def generate_daily_stats():
    """
    Генерирует полный отчёт за текущий день.
    """
    try:
        with sqlite3.connect(bot_instance.db_path) as conn:
            cursor = conn.cursor()
            
            currency_rate = bot_instance.get_setting('currency_rate')
            today = date.today().isoformat()

            cursor.execute('''
                SELECT id, initial_amount, final_amount, user_nickname, bank, status, processing_user
                FROM applications 
                WHERE date(blocking_date) = ?
                ORDER BY blocking_date
            ''', (today,))
            today_applications = cursor.fetchall()
            
            total_completed_rub = sum(app[1] for app in today_applications if app[5] == 'completed')
            total_blocked_rub = sum(app[1] for app in today_applications if app[5] == 'blocked')
            total_chewed_rub = sum(app[1] for app in today_applications if app[5] == 'chewed')
            total_paid_rub = sum(app[2] for app in today_applications if app[5] == 'completed')
            total_profit_rub = total_completed_rub - total_paid_rub
            total_profit_usd = total_profit_rub / currency_rate if currency_rate > 0 else 0
            
            stats_message = f"🗓️ **Отчёт за {datetime.now().strftime('%d.%m.%Y')}**\n\n"
            
            stats_message += "--- Завершенные заявки ---\n"
            if any(app[5] == 'completed' for app in today_applications):
                for app in today_applications:
                    if app[5] == 'completed':
                        final_usd = app[2] / currency_rate if currency_rate > 0 else 0
                        stats_message += f"✅ #{app[0]} | {app[3]} | {app[1]:.0f}₽ ({app[4]}) -> {final_usd:.2f}$ | Принимал: @{app[6]}\n"
            else:
                stats_message += "Нет выполненных заявок\n"
                
            stats_message += "\n--- Заблокированные заявки ---\n"
            if any(app[5] == 'blocked' for app in today_applications):
                for app in today_applications:
                    if app[5] == 'blocked':
                        stats_message += f"❌ #{app[0]} | {app[3]} | {app[1]:.0f}₽ ({app[4]}) | Принимал: @{app[6]}\n"
            else:
                stats_message += "Нет заблокированных заявок\n"

            stats_message += "\n--- Зажеванные заявки ---\n"
            if any(app[5] == 'chewed' for app in today_applications):
                for app in today_applications:
                    if app[5] == 'chewed':
                        stats_message += f"⚠️ #{app[0]} | {app[3]} | {app[1]:.0f}₽ ({app[4]}) | Принимал: @{app[6]}\n"
            else:
                stats_message += "Нет зажеванных заявок\n"
            
            stats_message += f"\n--- Итого ---\n"
            stats_message += f"✅ Завершено: {len([a for a in today_applications if a[5] == 'completed'])} на {total_completed_rub:.0f}₽\n"
            stats_message += f"❌ Заблокировано: {len([a for a in today_applications if a[5] == 'blocked'])} на {total_blocked_rub:.0f}₽\n"
            stats_message += f"⚠️ Зажевано: {len([a for a in today_applications if a[5] == 'chewed'])} на {total_chewed_rub:.0f}₽\n"
            stats_message += f"💰 Прибыль: {total_profit_rub:.0f}₽ ({total_profit_usd:.2f}$)\n"
            
            return stats_message
            
    except Exception as e:
        logger.error(f"Ошибка при генерации дневной статистики: {e}")
        return None

async def set_admin_chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /set_admin_chat - для установки текущего чата как админского"""
    if not bot_instance.is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Доступ запрещен. Команда только для администраторов.")
        return
        
    try:
        chat_id = update.effective_chat.id
        bot_instance.set_setting('admin_chat_id', chat_id)
        await update.message.reply_text(f"✅ Админский чат установлен: {chat_id}")
        
    except Exception as e:
        logger.error(f"Ошибка при установке админского чата: {e}")
        await update.message.reply_text("❌ Произошла ошибка при установке админского чата.")

async def set_currency_rate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /rate [число] - для установки курса валют"""
    if not bot_instance.is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Доступ запрещен. Команда только для администраторов.")
        return
        
    try:
        if not context.args or len(context.args) != 1:
            await update.message.reply_text("❌ Использование: /rate [число]")
            return
        
        rate = float(context.args[0])
        if rate <= 0:
            await update.message.reply_text("❌ Курс должен быть положительным числом.")
            return
        
        bot_instance.set_setting('currency_rate', rate)
        await update.message.reply_text(f"✅ Курс валют установлен: {rate:.2f}")
        
    except ValueError:
        await update.message.reply_text("❌ Неверный формат числа.")
    except Exception as e:
        logger.error(f"Ошибка при установке курса: {e}")
        await update.message.reply_text("❌ Произошла ошибка при установке курса.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help - справка по командам"""
    if not bot_instance.is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Доступ запрещен. Команда только для администраторов.")
        return

    help_text = """🤖 Бот «Финансист» - Доступные команды:

📋 Общие команды:
• /app [ник] [сумма] [банк] - создать новую заявку
• /in или /in_progress [номер] - взять заявку в работу (или ответить на сообщение)
• /accept [номер] - завершить заявку (или ответить на сообщение)
• /chewed [номер] - отметить заявку как зажеванную (или ответить на сообщение)
• /debt [пользователь] [сумма] - записать выданный долг
• /stats - показать статистику
• /reset - сбросить все заявки и отправить дневной отчёт
• /help - показать эту справку

⚙️ Административные команды:
• /percent [число] - установить процентную ставку
• /rate [число] - установить курс валют
• /balance [сумма] - пополнить баланс (только в админском чате)
• /set_admin_chat - установить текущий чат как админский

📝 Примеры:
• /app @user 100000 Альфа
• /in 1
• /accept 2
• /chewed 4
• /debt @user 5000
• /percent 6
• /rate 95.5"""
    
    await update.message.reply_text(help_text)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start - начальное приветствие и проверка доступа"""
    if not bot_instance.is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Доступ запрещен. Этот бот предназначен только для администраторов.")
        return
        
    await update.message.reply_text("🤖 Бот «Финансист» запущен. Используйте /help для списка команд.")

def main():
    """Основная функция запуска бота"""
    if BOT_TOKEN == "YOUR_BOT_TOKEN":
        print("❌ Ошибка: Не установлен токен бота!")
        print("Замените BOT_TOKEN в файле на токен, полученный от @BotFather")
        return
    
    if ADMIN_USER_IDS == [YOUR_ADMIN_ID]:
        print("⚠️ Предупреждение: Не установлены ID администраторов!")
        print("Измените ADMIN_USER_IDS в файле на ваши Telegram User ID")
    
    try:
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Регистрация обработчиков команд
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("percent", set_rate_command))
        application.add_handler(CommandHandler("app", create_application_command))
        application.add_handler(CommandHandler(["in_progress", "in"], in_progress_command))
        application.add_handler(CommandHandler("accept", accept_application_command))
        application.add_handler(CommandHandler("chewed", chewed_application_command))
        application.add_handler(CommandHandler("debt", add_debt_command))
        application.add_handler(CommandHandler("balance", balance_command))
        application.add_handler(CommandHandler("stats", stats_command))
        application.add_handler(CommandHandler("reset", reset_command))
        application.add_handler(CommandHandler("set_admin_chat", set_admin_chat_command))
        application.add_handler(CommandHandler("rate", set_currency_rate_command))
        
        print("✅ Бот «Финансист» запущен успешно!")
        print("Нажмите Ctrl+C для остановки")
        logger.info("Запуск бота...")
        application.run_polling(drop_pending_updates=True)
        
    except Exception as e:
        logger.error(f"Критическая ошибка при запуске бота: {e}")
        print(f"❌ Ошибка: {e}")
        print("\n🔧 Проверьте:")
        print("1. Правильность токена бота")
        print("2. Интернет-соединение")
        print("3. Установлена ли библиотека: pip install python-telegram-bot")

if __name__ == '__main__':
    main()

