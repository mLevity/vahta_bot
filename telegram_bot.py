# telegram_bot.py
import json
import re
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# --- Загрузка конфигурации ---
try:
    with open('config.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
except Exception as e:
    print(f"[CRITICAL] Ошибка загрузки config.json: {e}")
    exit()

BOT_TOKEN = config.get("TELEGRAM_BOT_TOKEN")
ALLOWED_CHAT_ID = config.get("ALLOWED_CHAT_ID")
ADMIN_IDS = config.get("ADMIN_USER_IDS", [])

if not BOT_TOKEN or BOT_TOKEN == "ВАШ_ТОКЕН_ОТ_BOTFATHER":
    print("[CRITICAL] Укажите токен вашего бота в файле config.json")
    exit()

bot = telebot.TeleBot(BOT_TOKEN)
print("[INFO] Бот инициализирован.")

user_steps = {}

# --- Класс QASystem и функция normalize_text (без изменений) ---
def normalize_text(text: str) -> str:
    return re.sub(r'[^\w\s]', '', text.lower())
class QASystem:
    def __init__(self, qa_data_path: str, threshold: float):
        self.qa_data = self._load_data(qa_data_path); self.threshold = threshold
        self.vectorizer = TfidfVectorizer(); self.corpus_vectors = self._prepare_model()
    def _load_data(self, path: str) -> list:
        try:
            with open(path, 'r', encoding='utf-8') as f: return json.load(f)
        except Exception as e: print(f"[ERROR] Не удалось загрузить базу знаний: {e}"); return []
    def _prepare_model(self):
        if not self.qa_data: return None
        print("[TF-IDF] Подготовка TF-IDF модели..."); corpus = [normalize_text(item['question']) for item in self.qa_data]
        vectors = self.vectorizer.fit_transform(corpus); print("[OK] TF-IDF модель подготовлена."); return vectors
    def find_answer(self, user_question: str) -> str | None:
        if self.corpus_vectors is None: return None
        normalized_question = normalize_text(user_question)
        question_vector = self.vectorizer.transform([normalized_question])
        similarities = cosine_similarity(question_vector, self.corpus_vectors)
        best_match_idx = similarities.argmax(); best_match_score = similarities[0, best_match_idx]
        print(f"[TF-IDF] Лучшее совпадение для '{user_question}': '{self.qa_data[best_match_idx]['question']}' (Сходство: {best_match_score:.4f})")
        if best_match_score >= self.threshold: return self.qa_data[best_match_idx]['answer']
        return None
qa_system = QASystem(qa_data_path='qa_data.json', threshold=config["SIMILARITY_THRESHOLD"])

# --- Вспомогательные функции (без изменений) ---
def is_admin(message: telebot.types.Message) -> bool:
    return message.from_user.id in ADMIN_IDS
def cancel_markup():
    markup = InlineKeyboardMarkup(); markup.add(InlineKeyboardButton("Отмена", callback_data="cancel_add")); return markup
def confirm_markup():
    markup = InlineKeyboardMarkup(); markup.row(InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_add"), InlineKeyboardButton("❌ Отмена", callback_data="cancel_add")); return markup

# --- Основные обработчики команд ---

@bot.message_handler(commands=['start'])
def send_welcome(message: telebot.types.Message):
    welcome_text = "Здравствуйте! Я бот-помощник."
    if is_admin(message):
        welcome_text += "\n\n*Вы администратор.*\nВам доступна команда `/add` в личном чате для добавления новых вопросов."
    welcome_text += "\n\nИспользуйте /help, чтобы увидеть список всех команд."
    bot.reply_to(message, welcome_text, parse_mode="Markdown")

@bot.message_handler(commands=['help'])
def send_help(message: telebot.types.Message):
    help_text = config["HELP_MESSAGE"]
    if is_admin(message):
        help_text += "\n\n*Для администраторов:*\n`/add` - запустить добавление нового вопроса-ответа (только в личном чате)."
    bot.reply_to(message, help_text, parse_mode="Markdown")

@bot.message_handler(commands=['ask'])
def handle_question(message: telebot.types.Message):
    # Эта команда работает только в разрешенном чате (если он указан)
    if ALLOWED_CHAT_ID != 0 and message.chat.id != ALLOWED_CHAT_ID:
        bot.reply_to(message, "Эта команда для вопросов работает только в назначенном рабочем чате.")
        print(f"[WARN] Попытка использовать /ask в неразрешенном чате: ID={message.chat.id}")
        return
    
    question = message.text.replace('/ask', '', 1).strip()
    print(f"[MSG] Получен вопрос: '{question}' от {message.from_user.username}")
    if not question:
        answer = "Пожалуйста, задайте ваш вопрос после команды. Пример: /ask какая погода?"
    else:
        answer = qa_system.find_answer(question) or config["DEFAULT_ANSWER"]
    bot.reply_to(message, answer)

# --- ИЗМЕНЕННАЯ ЛОГИКА ДОБАВЛЕНИЯ ---

@bot.message_handler(commands=['add'])
def handle_add(message: telebot.types.Message):
    """Шаг 1: Запуск процесса добавления. Проверяет, что это админ и что чат - личный."""
    # --- НОВЫЕ ПРОВЕРКИ ---
    if not is_admin(message):
        bot.reply_to(message, "Эта команда доступна только администраторам.")
        return
    if message.chat.type != "private":
        bot.reply_to(message, "Добавлять новые вопросы можно только в личном чате с ботом.")
        print(f"[WARN] Админ {message.from_user.username} попытался использовать /add в групповом чате.")
        return
        
    print(f"[CMD] Админ {message.from_user.username} инициировал добавление Q/A в личном чате.")
    msg = bot.reply_to(message, "Хорошо. Теперь отправьте мне текст **вопроса**.", reply_markup=cancel_markup())
    bot.register_next_step_handler(msg, process_question_step)

# --- Логика пошагового диалога (остается без изменений) ---
def process_question_step(message: telebot.types.Message):
    user_id = message.from_user.id; user_steps[user_id] = {'question': message.text}
    msg = bot.reply_to(message, "Отлично. Теперь отправьте мне текст **ответа**.", reply_markup=cancel_markup())
    bot.register_next_step_handler(msg, process_answer_step)
def process_answer_step(message: telebot.types.Message):
    user_id = message.from_user.id; user_steps[user_id]['answer'] = message.text
    question = user_steps[user_id]['question']; answer = user_steps[user_id]['answer']
    confirmation_text = f"Проверьте и подтвердите:\n\n❓ **Вопрос:**\n`{question}`\n\n✅ **Ответ:**\n`{answer}`"
    bot.reply_to(message, confirmation_text, parse_mode="Markdown", reply_markup=confirm_markup())
@bot.callback_query_handler(func=lambda call: call.data in ["confirm_add", "cancel_add"])
def callback_add_handler(call: telebot.types.CallbackQuery):
    user_id = call.from_user.id
    if call.data == "confirm_add":
        if user_id not in user_steps: bot.edit_message_text("Ошибка. Попробуйте /add снова.", call.message.chat.id, call.message.message_id); return
        question = user_steps[user_id]['question']; answer = user_steps[user_id]['answer']
        try:
            with open('qa_data.json', 'r+', encoding='utf-8') as f:
                data = json.load(f); data.append({"question": question, "answer": answer})
                f.seek(0); json.dump(data, f, ensure_ascii=False, indent=4); f.truncate()
            bot.edit_message_text("✅ **Добавлено!**\n\n*Перезапустите бота, чтобы он начал отвечать на новый вопрос.*", call.message.chat.id, call.message.message_id, parse_mode="Markdown")
            print(f"[OK] Админ {call.from_user.username} добавил новый Q/A.")
        except Exception as e: bot.edit_message_text(f"❌ Ошибка записи в файл: {e}", call.message.chat.id, call.message.message_id); print(f"[ERROR] Ошибка записи: {e}")
    elif call.data == "cancel_add":
        bot.edit_message_text("❌ Операция отменена.", call.message.chat.id, call.message.message_id); print(f"[INFO] Админ {call.from_user.username} отменил добавление.")
    if user_id in user_steps: del user_steps[user_id]
    bot.answer_callback_query(call.id)
# --- Конец логики добавления ---

@bot.message_handler(func=lambda message: True)
def get_chat_id(message: telebot.types.Message):
    """Ловит любое другое сообщение, чтобы сообщить ID чата/пользователя."""
    if ALLOWED_CHAT_ID == 0 or not ADMIN_IDS:
         print(f"[INFO] Получено сообщение из чата '{message.chat.title or 'личный чат'}' (ID: {message.chat.id}) от пользователя '{message.from_user.username}' (ID: {message.from_user.id})")
         print("[INFO] Скопируйте ID чата и/или пользователя и вставьте в config.json.")

# --- Запуск бота ---
if __name__ == '__main__':
    print("[INFO] Бот запускается...")
    bot.polling(non_stop=True)
