import os
import tempfile
import telebot
import google.generativeai as genai
from threading import Thread
from flask import Flask
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    app.run(host='0.0.0.0', port=10000)

Thread(target=run_flask).start()

# Инициализация токенов
TG_TOKEN = os.environ.get("TG_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_KEY")

bot = telebot.TeleBot(TG_TOKEN)
genai.configure(api_key=GEMINI_KEY)

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
model = genai.GenerativeModel(
    model_name="gemini-1.5-flash", 
    system_instruction=SPANISH_PROMPT
)

# Хранилище истории диалогов (текстовых) для каждого пользователя
chats = {}

# ОБРАБОТКА КОМАНД /start и /reset
@bot.message_handler(commands=['start', 'reset'])
def send_welcome(message):
    chats[message.chat.id] = []  # Создаем пустую историю
    bot.reply_to(message, "¡Hola! Soy tu profesor de español. ¿De qué te gustaría hablar hoy?\n(Привет! Я твой учитель испанского. О чем бы ты хотел поговорить?)")

# ОБРАБОТКА ТЕКСТОВЫХ СООБЩЕНИЙ (ТОЛЬКО текст!)
@bot.message_handler(content_types=['text'])
def handle_text(message):
    user_id = message.chat.id
    if user_id not in chats:
        chats[user_id] = []
    
    user_msg = message.text
    
    # Добавляем сообщение пользователя в историю
    chats[user_id].append({"role": "user", "parts": [user_msg]})
        
    try:
        # Отправляем всю историю диалога в модель
        response = model.generate_content(chats[user_id])
        
        # Добавляем ответ модели в историю
        chats[user_id].append({"role": "model", "parts": [response.text]})
        
        bot.reply_to(message, response.text)
    except Exception as e:
        bot.reply_to(message, "Lo siento, hubo un error. (Произошла ошибка, попробуй еще раз.)")
        print(f"Ошибка: {e}")

# ОБРАБОТКА ГОЛОСОВЫХ СООБЩЕНИЙ
@bot.message_handler(content_types=['voice'])
def handle_voice(message):
    user_id = message.chat.id
    if user_id not in chats:
        chats[user_id] = []
        
    try:
        # 1. Получаем информацию о файле голосового сообщения
        file_info = bot.get_file(message.voice.file_id)
        # 2. Скачиваем аудиофайл в память
        downloaded_file = bot.download_file(file_info.file_path)
        
        # 3. Создаем временный файл, чтобы правильно определить MIME-тип
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp.write(downloaded_file)
            tmp_path = tmp.name

        # 4. Читаем данные из временного файла
        with open(tmp_path, "rb") as audio_file:
            audio_bytes = audio_file.read()

        # 5. Запрос к Gemini специально для анализа аудио
        prompt = "Прослушай это голосовое сообщение от ученика и ответь согласно своей инструкции."
        response = model.generate_content([
            prompt,
            {"mime_type": "audio/ogg", "data": audio_bytes}
        ])
        
        # 6. После получения ответа от модели, добавляем и запрос, и ответ в историю чата
        chats[user_id].append({"role": "user", "parts": ["[Голосовое сообщение]"]})
        chats[user_id].append({"role": "model", "parts": [response.text]})
        
        # 7. Отправляем ответ пользователю
        bot.infinity_polling(skip_pending=True)
        
        # 8. Удаляем временный файл
        os.unlink(tmp_path)
        
    except Exception as e:
        bot.reply_to(message, "Не удалось обработать голосовое сообщение. Попробуй сказать четче или написать текстом.")
        print(f"Ошибка обработки голосового: {e}")

# Запуск бота
if __name__ == "__main__":
    bot.infinity_polling()
