import sqlite3
import logging
from datetime import datetime, date, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import warnings
import re
from telegram.helpers import escape_markdown

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
ADMIN_USER_IDS = [7610385492, 8209692488, 8221083095]
ADMIN_USERNAMES_TO_EXCLUDE = [@V1nceent_Vega, @Jules_W1nnf1eld, @BUTCH_C00L1DGE]

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
                        archived_date TIMESTAMP,
                        chat_id INTEGER
                    )
                ''')

                self._add_column_if_not_exists(cursor, 'applications', 'chat_id', 'INTEGER')
                self._add_column_if_not_exists(cursor, 'applications', 'bank', 'TEXT')
                self._add_column_if_not_exists(cursor, 'applications', 'processing_user', 'TEXT')
                self._add_column_if_not_exists(cursor, 'applications', 'blocking_date', 'TIMESTAMP')
                self._add_column_if_not_exists(cursor, 'applications', 'archived_date', 'TIMESTAMP')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS preserved_stats (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        app_id INTEGER NOT NULL,
                        chat_id INTEGER NOT NULL,
                        user_nickname TEXT NOT NULL,
                        initial_amount REAL NOT NULL,
                        status TEXT NOT NULL,
                        bank TEXT,
                        processing_user TEXT,
                        blocking_date TIMESTAMP NOT NULL,
                        saved_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
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

    def _add_column_if_not_exists(self, cursor, table_name: str, column_name: str, column_type: str):
        """Добавление колонки, если ее нет"""
        try:
            cursor.execute(f'SELECT {column_name} FROM {table_name} LIMIT 1')
        except sqlite3.OperationalError:
            try:
                cursor.execute(f'ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}')
                logger.info(f"Добавлена колонка {column_name} в таблицу {table_name}")
            except Exception as e:
                logger.warning(f"Не удалось добавить колонку {column_name} в {table_name}: {e}")

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
    
    def is_admin_chat(self, chat_id):
        """Проверка, является ли чат админским"""
        admin_chat_id = self.get_setting('admin_chat_id')
        return abs(chat_id - admin_chat_id) < 0.0001
    
    def is_admin(self, user_id):
        """Проверка, является ли пользователь администратором"""
        return user_id in ADMIN_USER_IDS

# Создание экземпляра бота
try:
    bot_instance = FinancistBot()
except Exception as e:
    logger.error(f"Не удалось создать экземпляр бота: {e}")
    exit(1)

# ================== УТИЛИТАРНЫЕ ФУНКЦИИ ==================

def get_app_id_from_reply(update: Update):
    """Извлекает ID заявки из сообщения, на которое был дан ответ."""
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

def get_processing_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Определяет пользователя-исполнителя из аргументов или текущего пользователя."""
    if context.args and context.args[-1].startswith('@'):
        return context.args[-1]
    return "@" + (update.effective_user.username or update.effective_user.first_name)

# ================== КОМАНДЫ ==================

async def set_rate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /percent [число]"""
    if not bot_instance.is_admin(update.effective_user.id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
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
        await update.message.reply_text(f"✅ Новая процентная ставка установлена: *{rate:.1f}%*.", parse_mode='Markdown')
        
    except ValueError:
        await update.message.reply_text("❌ Неверный формат числа.")
    except Exception as e:
        logger.error(f"Ошибка в команде /percent: {e}")
        await update.message.reply_text("❌ Произошла ошибка при выполнении команды.")

async def create_application_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /app [ник_пользователя] [сумма] [банк]"""
    if not bot_instance.is_admin(update.effective_user.id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return
    try:
        if not context.args or len(context.args) != 3:
            await update.message.reply_text("❌ Использование: /app [ник_пользователя] [сумма] [банк]")
            return
        
        user_nickname = context.args[0]
        initial_amount = float(context.args[1])
        bank = context.args[2]
        chat_id = update.effective_chat.id
        
        if initial_amount <= 0:
            await update.message.reply_text("❌ Сумма должна быть положительной.")
            return
        
        current_rate = bot_instance.get_setting('current_rate')
        final_amount = initial_amount * (1 - current_rate / 100)
        
        with sqlite3.connect(bot_instance.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO applications (user_nickname, initial_amount, rate_percentage, final_amount, bank, chat_id)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_nickname, initial_amount, current_rate, final_amount, bank, chat_id))
            
            app_id = cursor.lastrowid
            conn.commit()
        
        message = f"""#️⃣ Заявка №{app_id}
Сумма: {initial_amount:.0f}₽
Банк: {escape_markdown(bank)}
Ставка: {current_rate:.1f}%
К переводу: {final_amount:.0f}₽
Статус: В ожидании"""
        
        await update.message.reply_text(message, parse_mode='Markdown')
        
    except ValueError:
        await update.message.reply_text("❌ Неверный формат суммы.")
    except Exception as e:
        logger.error(f"Ошибка при создании заявки: {e}")
        await update.message.reply_text("❌ Произошла ошибка при создании заявки.")

async def in_progress_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /in_progress [номер_заявки] [ник_исполнителя] или ответ на сообщение"""
    if not bot_instance.is_admin(update.effective_user.id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return
    try:
        app_id = None
        if context.args:
            app_id = int(re.sub(r'[^0-9]', '', context.args[0]))
        else:
            app_id = get_app_id_from_reply(update)
        
        if not app_id:
            await update.message.reply_text("❌ Укажите номер заявки или дайте ответ на сообщение с заявкой.")
            return

        with sqlite3.connect(bot_instance.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM applications WHERE id = ? AND status = ? AND chat_id = ?',
                           (app_id, 'active', update.effective_chat.id))
            application = cursor.fetchone()
            
            if not application:
                await update.message.reply_text("❌ Активная заявка с таким номером в этом чате не найдена.")
                return

            processing_user = get_processing_user(update, context)
            cursor.execute('''
                UPDATE applications
                SET status = 'in_progress', processing_user = ?
                WHERE id = ?
            ''', (processing_user, app_id))
            conn.commit()
            
            message = f"""🔄 Заявка №{app_id}
Статус: *в работе*
Сумма: {application[2]:.0f}₽
Банк: {escape_markdown(application[5])}
Ставка: {application[3]:.1f}%
К переводу: {application[4]:.0f}₽
Принимал: {escape_markdown(processing_user)}"""
            
            await update.message.reply_text(message, parse_mode='Markdown')
            
    except ValueError:
        await update.message.reply_text("❌ Неверный формат номера заявки.")
    except Exception as e:
        logger.error(f"Ошибка в команде /in_progress: {e}")
        await update.message.reply_text("❌ Произошла ошибка при выполнении команды.")


async def accept_application_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /accept [номер_заявки] [ник_исполнителя] или ответ на сообщение"""
    if not bot_instance.is_admin(update.effective_user.id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return
    try:
        app_id = None
        if context.args:
            app_id = int(re.sub(r'[^0-9]', '', context.args[0]))
        else:
            app_id = get_app_id_from_reply(update)

        if not app_id:
            await update.message.reply_text("❌ Укажите номер заявки или дайте ответ на сообщение с заявкой.")
            return
        
        with sqlite3.connect(bot_instance.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM applications WHERE id = ? AND status IN (?, ?) AND chat_id = ?',
                           (app_id, 'active', 'in_progress', update.effective_chat.id))
            application = cursor.fetchone()
            
            if not application:
                await update.message.reply_text("❌ Активная заявка с таким номером в этом чате не найдена.")
                return
            
            processing_user = get_processing_user(update, context)
            blocking_date = datetime.now()
            cursor.execute('''
                UPDATE applications
                SET status = 'completed', blocking_date = ?, processing_user = ?
                WHERE id = ?
            ''', (blocking_date, processing_user, app_id))
            conn.commit()
            
            message = f"""✅ Заявка №{app_id}
Статус: *завершена*
Принимал: {escape_markdown(processing_user)}"""
            
            await update.message.reply_text(message, parse_mode='Markdown')
            
    except ValueError:
        await update.message.reply_text("❌ Неверный формат номера заявки.")
    except Exception as e:
        logger.error(f"Ошибка при завершении заявки: {e}")
        await update.message.reply_text("❌ Произошла ошибка при завершении заявки.")


async def chewed_application_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /chewed [номер_заявки] [ник_исполнителя] или ответ на сообщение"""
    if not bot_instance.is_admin(update.effective_user.id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return
    try:
        app_id = None
        if context.args:
            app_id = int(re.sub(r'[^0-9]', '', context.args[0]))
        else:
            app_id = get_app_id_from_reply(update)

        if not app_id:
            await update.message.reply_text("❌ Укажите номер заявки или дайте ответ на сообщение с заявкой.")
            return
        
        with sqlite3.connect(bot_instance.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM applications WHERE id = ? AND status IN (?, ?) AND chat_id = ?',
                           (app_id, 'active', 'in_progress', update.effective_chat.id))
            application = cursor.fetchone()
            
            if not application:
                await update.message.reply_text("❌ Активная заявка с таким номером в этом чате не найдена.")
                return
            
            processing_user = get_processing_user(update, context)
            blocking_date = datetime.now()
            cursor.execute('''
                UPDATE applications
                SET status = 'chewed', blocking_date = ?, processing_user = ?
                WHERE id = ?
            ''', (blocking_date, processing_user, app_id))
            conn.commit()
            
            message = f"""⚠️ Заявка №{app_id}
Сумма: {application[2]:.0f}₽
Банк: {escape_markdown(application[5])}
Принимал: {escape_markdown(processing_user)}
Статус: *Банкомат зажевал*"""
            
            await update.message.reply_text(message, parse_mode='Markdown')
            
    except ValueError:
        await update.message.reply_text("❌ Неверный формат номера заявки.")
    except Exception as e:
        logger.error(f"Ошибка в команде /chewed: {e}")
        await update.message.reply_text("❌ Произошла ошибка при выполнении команды.")

async def block_application_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /block [номер_заявки] [ник_исполнителя] или ответ на сообщение"""
    if not bot_instance.is_admin(update.effective_user.id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return
    try:
        app_id = None
        if context.args:
            app_id = int(re.sub(r'[^0-9]', '', context.args[0]))
        else:
            app_id = get_app_id_from_reply(update)

        if not app_id:
            await update.message.reply_text("❌ Укажите номер заявки или дайте ответ на сообщение с заявкой.")
            return
        
        with sqlite3.connect(bot_instance.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM applications WHERE id = ? AND status IN (?, ?) AND chat_id = ?',
                           (app_id, 'active', 'in_progress', update.effective_chat.id))
            application = cursor.fetchone()
            
            if not application:
                await update.message.reply_text("❌ Активная заявка с таким номером в этом чате не найдена.")
                return
            
            processing_user = get_processing_user(update, context)
            blocking_date = datetime.now()
            cursor.execute('''
                UPDATE applications
                SET status = 'blocked', blocking_date = ?, processing_user = ?
                WHERE id = ?
            ''', (blocking_date, processing_user, app_id))
            conn.commit()
            
            message = f"""❌ Заявка №{app_id}
Сумма: {application[2]:.0f}₽
Банк: {escape_markdown(application[5])}
Принимал: {escape_markdown(processing_user)}
Статус: *Заблокирована*"""
            
            await update.message.reply_text(message, parse_mode='Markdown')
            
    except ValueError:
        await update.message.reply_text("❌ Неверный формат номера заявки.")
    except Exception as e:
        logger.error(f"Ошибка в команде /block: {e}")
        await update.message.reply_text("❌ Произошла ошибка при выполнении команды.")

async def delete_application_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /delete [номер_заявки] или ответ на сообщение"""
    if not bot_instance.is_admin(update.effective_user.id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return
    try:
        app_id = None
        if context.args:
            app_id = int(re.sub(r'[^0-9]', '', context.args[0]))
        else:
            app_id = get_app_id_from_reply(update)

        if not app_id:
            await update.message.reply_text("❌ Укажите номер заявки или дайте ответ на сообщение с заявкой.")
            return
        
        with sqlite3.connect(bot_instance.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT id FROM applications WHERE id = ? AND chat_id = ?',
                           (app_id, update.effective_chat.id))
            application = cursor.fetchone()
            
            if not application:
                await update.message.reply_text(f"❌ Заявка с номером {app_id} в этом чате не найдена.")
                return
            
            cursor.execute('DELETE FROM applications WHERE id = ?', (app_id,))
            conn.commit()
            
            await update.message.reply_text(f"✅ Заявка №{app_id} успешно удалена.")
            
    except ValueError:
        await update.message.reply_text("❌ Неверный формат номера заявки.")
    except Exception as e:
        logger.error(f"Ошибка при удалении заявки: {e}")
        await update.message.reply_text("❌ Произошла ошибка при удалении заявки.")


async def add_debt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /debt [пользователь] [сумма]"""
    if not bot_instance.is_admin(update.effective_user.id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
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
            f"✅ Записано: **{escape_markdown(user_nickname)}** теперь должен **{new_amount:.0f}₽**", parse_mode='Markdown'
        )
        
    except ValueError:
        await update.message.reply_text("❌ Неверный формат суммы.")
    except Exception as e:
        logger.error(f"Ошибка при добавлении долга: {e}")
        await update.message.reply_text("❌ Произошла ошибка при добавлении долга.")

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /balance [сумма] - пополнить или показать баланс"""
    if not bot_instance.is_admin(update.effective_user.id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
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
            await update.message.reply_text(f"💰 Текущий баланс: **{current_balance:.2f}$**", parse_mode='Markdown')
            return
            
        amount = float(context.args[0])
        
        with sqlite3.connect(bot_instance.db_path) as conn:
            cursor = conn.cursor()
            new_balance = current_balance + amount
            cursor.execute('UPDATE balance SET total_profit = ? WHERE id = 1', (new_balance,))
            conn.commit()
        
        await update.message.reply_text(
            f"✅ Баланс пополнен на **{amount:.2f}$**. Текущий баланс: **{new_balance:.2f}$**", parse_mode='Markdown'
        )
        
    except ValueError:
        await update.message.reply_text("❌ Неверный формат суммы.")
    except Exception as e:
        logger.error(f"Ошибка при пополнении баланса: {e}")
        await update.message.reply_text("❌ Произошла ошибка при пополнении баланса.")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /stats - показывает статистику только для текущего чата."""
    if not bot_instance.is_admin(update.effective_user.id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return
    try:
        chat_title = update.effective_chat.title or "Личный чат"
        chat_id = update.effective_chat.id
        current_date = datetime.now().strftime('%d.%m.%Y')
        
        with sqlite3.connect(bot_instance.db_path) as conn:
            cursor = conn.cursor()
            
            currency_rate = bot_instance.get_setting('currency_rate')
            
            cursor.execute('''
                SELECT id, initial_amount, rate_percentage, final_amount, user_nickname, bank, status
                FROM applications WHERE (status = 'active' OR status = 'in_progress') AND chat_id = ?
                ORDER BY id
            ''', (chat_id,))
            active_applications = cursor.fetchall()
            
            today = date.today().isoformat()
            cursor.execute('''
                SELECT id, initial_amount, rate_percentage, final_amount, user_nickname, bank, processing_user
                FROM applications
                WHERE status = 'completed' AND date(blocking_date) = ? AND chat_id = ?
                ORDER BY id
            ''', (today, chat_id))
            today_completed = cursor.fetchall()

            cursor.execute('''
                SELECT id, initial_amount, rate_percentage, final_amount, user_nickname, bank, processing_user
                FROM applications
                WHERE status = 'blocked' AND date(blocking_date) = ? AND chat_id = ?
                ORDER BY id
            ''', (today, chat_id))
            today_blocked = cursor.fetchall()
            
            cursor.execute('''
                SELECT id, initial_amount, rate_percentage, final_amount, user_nickname, bank, processing_user
                FROM applications
                WHERE status = 'chewed' AND date(blocking_date) = ? AND chat_id = ?
                ORDER BY id
            ''', (today, chat_id))
            today_chewed = cursor.fetchall()
            
            cursor.execute('SELECT SUM(initial_amount) FROM applications WHERE (status = "active" OR status = "in_progress") AND chat_id = ?', (chat_id,))
            total_waiting = cursor.fetchone()[0] or 0
            
            cursor.execute('''
                SELECT SUM(initial_amount) FROM applications WHERE status = "completed" AND chat_id = ?
            ''', (chat_id,))
            total_processed_rub = cursor.fetchone()[0] or 0
            
            cursor.execute('''
                SELECT SUM(initial_amount) FROM applications WHERE status = "blocked" AND chat_id = ?
            ''', (chat_id,))
            total_blocked_rub = cursor.fetchone()[0] or 0

            cursor.execute('''
                SELECT SUM(initial_amount) FROM applications WHERE status = "chewed" AND chat_id = ?
            ''', (chat_id,))
            total_chewed_rub = cursor.fetchone()[0] or 0
            
            cursor.execute('''
                SELECT SUM(final_amount) FROM applications WHERE status = "completed" AND chat_id = ?
            ''', (chat_id,))
            total_paid_rub = cursor.fetchone()[0] or 0
            total_paid_usd = total_paid_rub / currency_rate if currency_rate > 0 else 0
            
            cursor.execute('SELECT user_nickname, debt_amount FROM debts WHERE debt_amount > 0')
            debtors = cursor.fetchall()
            
        message = f"""*👨‍💻 {escape_markdown(chat_title)} | {current_date}*
*⚜️ Статистика для этого чата:*

*Активные заявки (в ожидании и в работе):*"""
        
        if active_applications:
            for app in active_applications:
                app_id, initial, _, _, nickname, bank, status = app
                status_emoji = "🕐" if status == 'active' else "🔄"
                message += f"\n{status_emoji} Заявка №{app_id} | {escape_markdown(nickname)} | {initial:.0f}₽ | {escape_markdown(bank)}"
        else:
            message += "\nНет активных заявок"
        
        message += f"\n\n*Выполненные заявки за сегодня ({len(today_completed)}):*"
        
        if today_completed:
            for app in today_completed:
                app_id, initial, rate, final, nickname, bank, processing_user = app
                usd_amount = final / currency_rate if currency_rate > 0 else 0
                message += f"\n✅ Заявка №{app_id} | {escape_markdown(nickname)} | {initial:.0f}₽ ({escape_markdown(bank)}) - {rate:.1f}% = {usd_amount:.2f}$ | Принимал: {escape_markdown(processing_user)}"
        else:
            message += "\nНет выполненных заявок за сегодня"

        message += f"\n\n*Заблокированные заявки за сегодня ({len(today_blocked)}):*"
        if today_blocked:
            for app in today_blocked:
                app_id, initial, _, _, nickname, bank, processing_user = app
                message += f"\n❌ Заявка №{app_id} | {escape_markdown(nickname)} | {initial:.0f}₽ ({escape_markdown(bank)}) | Принимал: {escape_markdown(processing_user)}"
        else:
            message += "\nНет заблокированных заявок за сегодня"
        
        message += f"\n\n*Зажеванные заявки за сегодня ({len(today_chewed)}):*"
        if today_chewed:
            for app in today_chewed:
                app_id, initial, _, _, nickname, bank, processing_user = app
                message += f"\n⚠️ Заявка №{app_id} | {escape_markdown(nickname)} | {initial:.0f}₽ ({escape_markdown(bank)}) | Принимал: {escape_markdown(processing_user)}"
        else:
            message += "\nНет зажеванных заявок за сегодня"

        message += f"""

*Общая сводка:*
🕐 Ожидаем: {total_waiting:.0f}₽
✅ Обработанные заявки на сумму: {total_processed_rub:.0f}₽
❌ Заблокировано заявок на сумму: {total_blocked_rub:.0f}₽
⚠️ Зажевано заявок на сумму: {total_chewed_rub:.0f}₽
💸 Выплачено: {total_paid_usd:.2f}$

*Должники:*"""
        
        if debtors:
            for nickname, amount in debtors:
                message += f"\n- {escape_markdown(nickname)}: {amount:.0f}₽"
        else:
            message += "\nНет должников"
        
        # Add per-user statistics to the stats command
        message += await get_all_user_stats(chat_id)
        
        await update.message.reply_text(message, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Ошибка при генерации статистики: {e}")
        await update.message.reply_text("❌ Произошла ошибка при генерации статистики.")

async def get_all_user_stats(chat_id):
    """Generates statistics for all users in the specified chat."""
    try:
        with sqlite3.connect(bot_instance.db_path) as conn:
            cursor = conn.cursor()

            # Get all users who have processed applications
            cursor.execute('''
                SELECT DISTINCT processing_user FROM applications WHERE chat_id = ? AND processing_user IS NOT NULL
                UNION
                SELECT DISTINCT processing_user FROM preserved_stats WHERE chat_id = ? AND processing_user IS NOT NULL
            ''', (chat_id, chat_id))
            all_users = [row[0] for row in cursor.fetchall() if row[0] not in ADMIN_USERNAMES_TO_EXCLUDE]

            if not all_users:
                return "\n\n*📊 Статистика по работникам:* \nНет данных по работникам."

            stats_message = "\n\n*📊 Статистика по работникам:*"
            for user in sorted(all_users):
                # Stats from main applications table
                cursor.execute('''
                    SELECT status, COUNT(*), SUM(initial_amount)
                    FROM applications
                    WHERE processing_user = ? AND chat_id = ? AND status IN ('completed', 'blocked', 'chewed')
                    GROUP BY status
                ''', (user, chat_id))
                current_stats = {row[0]: (row[1], row[2]) for row in cursor.fetchall()}

                # Stats from preserved_stats table
                cursor.execute('''
                    SELECT status, COUNT(*), SUM(initial_amount)
                    FROM preserved_stats
                    WHERE processing_user = ? AND chat_id = ?
                    GROUP BY status
                ''', (user, chat_id))
                preserved_stats = {row[0]: (row[1], row[2]) for row in cursor.fetchall()}

                completed_count = current_stats.get('completed', (0, 0))[0] + preserved_stats.get('completed', (0, 0))[0]
                completed_amount = (current_stats.get('completed', (0, 0))[1] or 0) + (preserved_stats.get('completed', (0, 0))[1] or 0)

                blocked_count = current_stats.get('blocked', (0, 0))[0] + preserved_stats.get('blocked', (0, 0))[0]
                blocked_amount = (current_stats.get('blocked', (0, 0))[1] or 0) + (preserved_stats.get('blocked', (0, 0))[1] or 0)

                chewed_count = current_stats.get('chewed', (0, 0))[0] + preserved_stats.get('chewed', (0, 0))[0]
                chewed_amount = (current_stats.get('chewed', (0, 0))[1] or 0) + (preserved_stats.get('chewed', (0, 0))[1] or 0)

                stats_message += f"""
👤 {escape_markdown(user)}:
  ✅ Выполнено: {completed_count} на {completed_amount:.0f}₽
  ❌ Заблокировано: {blocked_count} на {blocked_amount:.0f}₽
  ⚠️ Зажевано: {chewed_count} на {chewed_amount:.0f}₽"""

        return stats_message

    except Exception as e:
        logger.error(f"Ошибка при генерации статистики по всем пользователям: {e}")
        return "\n\n❌ Произошла ошибка при получении статистики по работникам."

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /reset - сбрасывает все активные заявки и отправляет дневной отчет
    в админский чат, сохраняя заблокированные и зажеванные заявки.
    """
    if not bot_instance.is_admin(update.effective_user.id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return
    
    admin_chat_id = bot_instance.get_setting('admin_chat_id')
    
    if not admin_chat_id:
        await update.message.reply_text("❌ Сначала нужно установить админский чат командой /set_admin_chat.")
        return
        
    try:
        with sqlite3.connect(bot_instance.db_path) as conn:
            cursor = conn.cursor()
            
            # Select all blocked and chewed applications
            cursor.execute('''
                SELECT id, chat_id, user_nickname, initial_amount, status, bank, processing_user, blocking_date
                FROM applications
                WHERE status IN ('blocked', 'chewed')
            ''')
            preserved_apps = cursor.fetchall()
            
            # Save them into the new table
            if preserved_apps:
                cursor.executemany('''
                    INSERT INTO preserved_stats (app_id, chat_id, user_nickname, initial_amount, status, bank, processing_user, blocking_date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (preserved_apps))
                conn.commit()

        daily_stats_message = await generate_full_daily_stats()
        if daily_stats_message:
            await context.bot.send_message(chat_id=int(admin_chat_id), text="📈 **Дневной отчёт перед сбросом:**\n\n" + daily_stats_message, parse_mode='Markdown')
            await update.message.reply_text("✅ Статистика за день была успешно отправлена в админский чат.")

        # Archive all other applications (active, in_progress, completed)
        with sqlite3.connect(bot_instance.db_path) as conn:
            cursor = conn.cursor()
            archived_date = datetime.now()
            
            cursor.execute('''
                UPDATE applications
                SET status = 'archived', archived_date = ?
                WHERE status IN ('active', 'in_progress', 'completed')
            ''', (archived_date,))
            
            rows_updated = cursor.rowcount
            conn.commit()
            
        await update.message.reply_text(f"✅ Заявки успешно сброшены. Всего заархивировано: {rows_updated}")
        
    except Exception as e:
        logger.error(f"Ошибка при сбросе заявок: {e}")
        await update.message.reply_text("❌ Произошла ошибка при сбросе заявок.")

async def generate_full_daily_stats():
    """
    Генерирует полный отчет за текущий день для всех чатов.
    Включает данные из preserved_stats.
    """
    try:
        with sqlite3.connect(bot_instance.db_path) as conn:
            cursor = conn.cursor()
            
            currency_rate = bot_instance.get_setting('currency_rate')
            today = date.today().isoformat()

            stats_message = f"🗓️ **Полный отчет за {datetime.now().strftime('%d.%m.%Y')}**\n\n"

            cursor.execute('SELECT DISTINCT chat_id FROM applications')
            all_chat_ids = [row[0] for row in cursor.fetchall() if row[0] is not None]

            total_profit_all_usd = 0
            for chat_id in all_chat_ids:
                try:
                    chat_info = await Application.builder().token(BOT_TOKEN).build().bot.get_chat(chat_id)
                    chat_name = escape_markdown(chat_info.title or f"Приватный чат ({chat_id})")
                except Exception:
                    chat_name = f"Неизвестный чат ({chat_id})"
                
                stats_message += f"--- Отчет для чата '{chat_name}' ---\n"
                
                cursor.execute('''
                    SELECT id, initial_amount, final_amount, user_nickname, bank, status, processing_user
                    FROM applications
                    WHERE date(blocking_date) = ? AND chat_id = ?
                    ORDER BY blocking_date
                ''', (today, chat_id))
                today_applications = cursor.fetchall()

                cursor.execute('''
                    SELECT app_id, initial_amount, status, user_nickname, bank, processing_user
                    FROM preserved_stats
                    WHERE chat_id = ? AND date(saved_date) = ?
                ''', (chat_id, today))
                preserved_stats_today = cursor.fetchall()
                
                if not today_applications and not preserved_stats_today:
                    stats_message += "Нет выполненных заявок за сегодня.\n\n"
                    continue

                total_completed_rub = sum(app[1] for app in today_applications if app[5] == 'completed')
                total_paid_rub = sum(app[2] for app in today_applications if app[5] == 'completed')
                
                today_blocked_rub = sum(app[1] for app in today_applications if app[5] == 'blocked')
                today_chewed_rub = sum(app[1] for app in today_applications if app[5] == 'chewed')
                
                preserved_blocked_rub = sum(app[1] for app in preserved_stats_today if app[2] == 'blocked')
                preserved_chewed_rub = sum(app[1] for app in preserved_stats_today if app[2] == 'chewed')
                
                total_blocked_rub = today_blocked_rub + preserved_blocked_rub
                total_chewed_rub = today_chewed_rub + preserved_chewed_rub
                
                total_profit_rub = total_completed_rub - total_paid_rub
                total_profit_usd = total_profit_rub / currency_rate if currency_rate > 0 else 0
                total_profit_all_usd += total_profit_usd
                
                stats_message += "**--- Завершенные заявки ---**\n"
                for app in today_applications:
                    if app[5] == 'completed':
                        final_usd = app[2] / currency_rate if currency_rate > 0 else 0
                        stats_message += f"✅ #{app[0]} | {escape_markdown(app[3])} | {app[1]:.0f}₽ ({escape_markdown(app[4])}) -> {final_usd:.2f}$ | Принимал: {escape_markdown(app[6])}\n"
                
                stats_message += "\n**--- Заблокированные и зажеванные заявки ---**\n"
                all_preserved_apps = [app for app in today_applications if app[5] in ('blocked', 'chewed')] + list(preserved_stats_today)
                for app in all_preserved_apps:
                    if len(app) == 7: # Application from the main table
                        app_id, initial_amount, _, _, nickname, bank, processing_user = app
                        status = app[5]
                    else: # Application from preserved_stats table
                        app_id, initial_amount, status, nickname, bank, processing_user = app
                    
                    if status == 'blocked':
                        stats_message += f"❌ #{app_id} | {escape_markdown(nickname)} | {initial_amount:.0f}₽ ({escape_markdown(bank)}) | Принимал: {escape_markdown(processing_user)}\n"
                    elif status == 'chewed':
                        stats_message += f"⚠️ #{app_id} | {escape_markdown(nickname)} | {initial_amount:.0f}₽ ({escape_markdown(bank)}) | Принимал: {escape_markdown(processing_user)}\n"

                stats_message += f"\n**--- Общий итог для чата ---**\n"
                stats_message += f"✅ Завершено: {len([a for a in today_applications if a[5] == 'completed'])} на {total_completed_rub:.0f}₽\n"
                stats_message += f"❌ Заблокировано: {len([a for a in today_applications if a[5] == 'blocked']) + len([a for a in preserved_stats_today if a[2] == 'blocked'])} на {total_blocked_rub:.0f}₽\n"
                stats_message += f"⚠️ Зажевано: {len([a for a in today_applications if a[5] == 'chewed']) + len([a for a in preserved_stats_today if a[2] == 'chewed'])} на {total_chewed_rub:.0f}₽\n"
                stats_message += f"💰 Прибыль: {total_profit_rub:.0f}₽ ({total_profit_usd:.2f}$)\n\n"

            stats_message += "**--- Общая статистика для всех чатов ---**\n"
            
            cursor.execute('SELECT SUM(initial_amount) FROM applications WHERE status = "completed" AND date(blocking_date) = ?', (today,))
            total_completed_all_rub = cursor.fetchone()[0] or 0

            cursor.execute('SELECT SUM(initial_amount) FROM applications WHERE status = "blocked" AND date(blocking_date) = ?', (today,))
            total_blocked_all_rub = cursor.fetchone()[0] or 0
            
            cursor.execute('SELECT SUM(initial_amount) FROM applications WHERE status = "chewed" AND date(blocking_date) = ?', (today,))
            total_chewed_all_rub = cursor.fetchone()[0] or 0
            
            cursor.execute('SELECT SUM(initial_amount) FROM preserved_stats')
            total_preserved_rub = cursor.fetchone()[0] or 0

            total_profit_all_rub = total_completed_all_rub * bot_instance.get_setting('current_rate') / 100
            total_profit_all_usd = total_profit_all_rub / currency_rate if currency_rate > 0 else 0

            stats_message += f"✅ Завершено (все чаты): {total_completed_all_rub:.0f}₽\n"
            stats_message += f"❌ Заблокировано (все чаты): {total_blocked_all_rub:.0f}₽\n"
            stats_message += f"⚠️ Зажевано (все чаты): {total_chewed_all_rub:.0f}₽\n"
            stats_message += f"💰 Общая прибыль: {total_profit_all_rub:.0f}₽ ({total_profit_all_usd:.2f}$)\n"
            stats_message += f"\n_Общая статистика с учётом всех сохранённых заявок:\n❌ Заблокировано: {total_blocked_all_rub + total_preserved_rub:.0f}₽\n⚠️ Зажевано: {total_chewed_all_rub + total_preserved_rub:.0f}₽_"

            return stats_message
            
    except Exception as e:
        logger.error(f"Ошибка при генерации полного дневного отчета: {e}")
        return "❌ Не удалось сгенерировать полный отчет."


async def set_admin_chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /set_admin_chat - для установки текущего чата как админского"""
    if not bot_instance.is_admin(update.effective_user.id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
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
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
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
        await update.message.reply_text(f"✅ Курс валют установлен: **{rate:.2f}**", parse_mode='Markdown')
        
    except ValueError:
        await update.message.reply_text("❌ Неверный формат числа.")
    except Exception as e:
        logger.error(f"Ошибка при установке курса: {e}")
        await update.message.reply_text("❌ Произошла ошибка при установке курса.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help - справка по командам"""
    if not bot_instance.is_admin(update.effective_user.id):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return
    help_text = """**🤖 Бот «Финансист» - Доступные команды:**

*📋 Общие команды:*
- /app [ник] [сумма] [банк] - создать новую заявку
- /in или /in_progress [номер] [ник_исполнителя] - взять заявку в работу
- /accept [номер] [ник_исполнителя] - завершить заявку
- /block [номер] [ник_исполнителя] - заблокировать заявку
- /chewed [номер] [ник_исполнителя] - пометить заявку как зажеванную
- /del [номер] - удалить заявку
- /debt [пользователь] [сумма] - записать выданный долг
- /stats - показать статистику (только для этого чата)

*⚙️ Команды для настройки:*
- /set_admin_chat - установить текущий чат как админский
- /percent [число] - установить процентную ставку
- /rate [число] - установить курс валют
- /balance [сумма] - пополнить баланс
- /reset - сбросить все заявки и отправить полный отчет по всем чатам
- /help - показать эту справку

*📝 Примеры:*
- /app @user 100000 Альфа
- /in 1 @butch
- /accept 2 @krip
- /block 3 @butch
- /chewed 4 @butch
- /del 5
- /debt @user 5000
- /percent 6
- /rate 95.5"""
    
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start - начальное приветствие"""
    await update.message.reply_text("🤖 Бот «Финансист» запущен. Используйте /help для списка команд.")

def main():
    """Основная функция запуска бота"""
    if BOT_TOKEN == "YOUR_BOT_TOKEN":
        print("❌ Ошибка: Не установлен токен бота!")
        print("Замените BOT_TOKEN в файле на токен, полученный от @BotFather")
        return

    try:
        application = Application.builder().token(BOT_TOKEN).build()
        
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("percent", set_rate_command))
        application.add_handler(CommandHandler("app", create_application_command))
        application.add_handler(CommandHandler(["in_progress", "in"], in_progress_command))
        application.add_handler(CommandHandler("accept", accept_application_command))
        application.add_handler(CommandHandler("chewed", chewed_application_command))
        application.add_handler(CommandHandler(["delete", "del"], delete_application_command))
        application.add_handler(CommandHandler("debt", add_debt_command))
        application.add_handler(CommandHandler("block", block_application_command))
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
