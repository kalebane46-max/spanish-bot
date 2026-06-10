import os
import tempfile
import telebot
import google.generativeai as genai
from threading import Thread
from flask import Flask
import logging

# Настройка подробных логов
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    app.run(host='0.0.0.0', port=10000)

Thread(target=run_flask).start()

# Инициализация токенов с проверкой
TG_TOKEN = os.environ.get("TG_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_KEY")

# Проверка наличия ключей
if not TG_TOKEN:
    logger.error("❌ TG_TOKEN не найден в переменных окружения!")
if not GEMINI_KEY:
    logger.error("❌ GEMINI_KEY не найден в переменных окружения!")
else:
    logger.info(f"✅ GEMINI_KEY загружен, начинается на: {GEMINI_KEY[:10]}...")

bot = telebot.TeleBot(TG_TOKEN)

# Настройка Gemini
try:
    genai.configure(api_key=GEMINI_KEY)
    logger.info("✅ Gemini API настроен успешно")
except Exception as e:
    logger.error(f"❌ Ошибка настройки Gemini API: {e}")

# СТРОГАЯ ИНСТРУКЦИЯ ДЛЯ ПРЕПОДАВАТЕЛЯ ИСПАНСКОГО
SPANISH_PROMPT = (
    "Ты — профессиональный, дружелюбный преподаватель испанского языка. "
    "Твоя задача — вести со мной диалог ТОЛЬКО на испанском языке. "
    "ЕСЛИ я допускаю грамматическую, орфографическую или стилистическую ошибку в своем сообщении "
    "(неважно, текстом или голосом), ты ОБЯЗАН:\n"
    "1. Сначала мягко исправить меня, написав правильный вариант.\n"
    "2. На русском языке кратко объяснить, в чем именно заключалась ошибка и какое правило здесь работает.\n"
    "3. Ответить на мою реплику по существу на испанском языке, чтобы продолжить беседу."
    "Объяснение ошибки всегда давай на русском языке."
)

# Используем модель, которая умеет работать и с текстом, и с аудио
try:
    model = genai.GenerativeModel(
        model_name="gemini-1.5-flash", 
        system_instruction=SPANISH_PROMPT
    )
    logger.info("✅ Модель Gemini загружена успешно")
except Exception as e:
    logger.error(f"❌ Ошибка загрузки модели: {e}")
    model = None

# Хранилище истории диалогов
chats = {}

# ОБРАБОТКА КОМАНД /start и /reset
@bot.message_handler(commands=['start', 'reset'])
def send_welcome(message):
    chats[message.chat.id] = []
    bot.reply_to(message, "¡Hola! Soy tu profesor de español. ¿De qué te gustaría hablar hoy?\n(Привет! Я твой учитель испанского. О чем бы ты хотел поговорить?)")

# ОБРАБОТКА ТЕКСТОВЫХ СООБЩЕНИЙ
@bot.message_handler(content_types=['text'])
def handle_text(message):
    user_id = message.chat.id
    logger.info(f"📩 Получено текстовое сообщение от {user_id}: {message.text[:50]}...")
    
    if user_id not in chats:
        chats[user_id] = []
    
    user_msg = message.text
    chats[user_id].append({"role": "user", "parts": [user_msg]})
        
    try:
        if model is None:
            raise Exception("Модель не загружена")
        
        logger.info("🤖 Отправляю запрос к Gemini API...")
        response = model.generate_content(chats[user_id])
        logger.info("✅ Ответ от Gemini получен")
        
        chats[user_id].append({"role": "model", "parts": [response.text]})
        bot.reply_to(message, response.text)
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"❌ Ошибка при обработке текста: {error_msg}")
        
        # Проверяем тип ошибки и даём понятный ответ
        if "429" in error_msg or "quota" in error_msg.lower():
            bot.reply_to(message, "Превышен лимит запросов к Gemini. Попробуй через минуту.")
        elif "404" in error_msg or "not found" in error_msg.lower():
            bot.reply_to(message, "Проблема с доступом к API Gemini. Проверь ключ или модель.")
        else:
            bot.reply_to(message, f"❌ Ошибка: {error_msg[:100]}")

# ОБРАБОТКА ГОЛОСОВЫХ СООБЩЕНИЙ
@bot.message_handler(content_types=['voice'])
def handle_voice(message):
    user_id = message.chat.id
    logger.info(f"🎤 Получено голосовое сообщение от {user_id}")
    
    if user_id not in chats:
        chats[user_id] = []
        
    try:
        file_info = bot.get_file(message.voice.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp.write(downloaded_file)
            tmp_path = tmp.name

        with open(tmp_path, "rb") as audio_file:
            audio_bytes = audio_file.read()

        prompt = "Прослушай это голосовое сообщение от ученика и ответь согласно своей инструкции."
        response = model.generate_content([
            prompt,
            {"mime_type": "audio/ogg", "data": audio_bytes}
        ])
        
        chats[user_id].append({"role": "user", "parts": ["[Голосовое сообщение]"]})
        chats[user_id].append({"role": "model", "parts": [response.text]})
        
        bot.reply_to(message, response.text)
        os.unlink(tmp_path)
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"❌ Ошибка обработки голосового: {error_msg}")
        bot.reply_to(message, f"❌ Ошибка голосового: {error_msg[:100]}")

# Запуск бота
if __name__ == "__main__":
    logger.info("🚀 Запуск бота...")
    bot.infinity_polling(skip_pending=True)
