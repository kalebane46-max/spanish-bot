import os
import tempfile
import telebot
import google.generativeai as genai
from threading import Thread
from flask import Flask
import logging
import time
import asyncio
import edge_tts

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    app.run(host='0.0.0.0', port=10000)

Thread(target=run_flask).start()

TG_TOKEN = os.environ.get("TG_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_KEY")

# Удаляем вебхук перед созданием бота
import requests as req
req.get(f"https://api.telegram.org/bot{TG_TOKEN}/deleteWebhook?drop_pending_updates=True")
time.sleep(1)

bot = telebot.TeleBot(TG_TOKEN)
genai.configure(api_key=GEMINI_KEY)

SPANISH_PROMPT = (
    "Ты — профессиональный, дружелюбный преподаватель испанского языка. "
    "Твоя задача — вести со мной диалог ТОЛЬКО на испанском языке. "
    "ЕСЛИ я допускаю грамматическую, орфографическую или стилистическую ошибку в своем сообщении "
    "(неважно, текстом или голосом), ты ОБЯЗАН:\n"
    "1. Сначала мягко исправить меня, написав правильный вариант.\n"
    "2. На русском языке кратко объяснить, в чем именно заключалась ошибка и какое правило здесь работает.\n"
    "3. Ответить на мою реплику по существу на испанском языке, чтобы продолжить беседу.\n"
    "Объяснение ошибки всегда давай на русском языке."
)

model = genai.GenerativeModel(
    model_name="gemini-3-flash-preview",
    system_instruction=SPANISH_PROMPT
)

chats = {}

# Функция озвучки через Microsoft Edge TTS (полностью бесплатно, без ключей)
async def text_to_speech_async(text):
    """Преобразует текст в голосовое сообщение используя Microsoft Edge TTS"""
    try:
        # Испанский женский голос (можно заменить на мужской es-MX-JorgeNeural)
        voice = "es-ES-ElviraNeural"
        
        # Создаем временный файл
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            output_path = tmp.name
        
        # Генерируем речь
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_path)
        
        # Читаем файл
        with open(output_path, "rb") as f:
            audio_data = f.read()
        
        # Удаляем временный файл
        os.unlink(output_path)
        
        return audio_data
    except Exception as e:
        logger.error(f"Ошибка озвучки: {e}")
        return None

def text_to_speech(text):
    """Обёртка для асинхронной функции"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(text_to_speech_async(text))
        loop.close()
        return result
    except Exception as e:
        logger.error(f"Ошибка TTS: {e}")
        return None

@bot.message_handler(commands=['start', 'reset'])
def send_welcome(message):
    chats[message.chat.id] = []
    bot.reply_to(message, "¡Hola! Soy tu profesor de español. ¿De qué te gustaría hablar hoy?\n(Привет! Я твой учитель испанского. О чем бы ты хотел поговорить?)")

@bot.message_handler(content_types=['text'])
def handle_text(message):
    user_id = message.chat.id
    logger.info(f"📩 Сообщение от {user_id}: {message.text[:50]}...")
    
    if user_id not in chats:
        chats[user_id] = []
    
    chats[user_id].append({"role": "user", "parts": [message.text]})
        
    try:
        logger.info("🤖 Запрос к Gemini...")
        response = model.generate_content(chats[user_id])
        logger.info(f"✅ Ответ: {response.text[:50]}...")
        
        chats[user_id].append({"role": "model", "parts": [response.text]})
        
        # Отправляем текст
        bot.reply_to(message, response.text)
        
        # Отправляем голос (только испанскую часть, если есть)
        audio_data = text_to_speech(response.text)
        if audio_data:
            bot.send_voice(message.chat.id, audio_data)
            logger.info("🎤 Голосовое отправлено")
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"❌ Ошибка: {error_msg}")
        
        if "429" in error_msg:
            bot.reply_to(message, "⏳ Слишком много запросов. Подожди минуту.")
        elif "404" in error_msg:
            bot.reply_to(message, f"❌ Модель не найдена.")
        else:
            bot.reply_to(message, f"❌ {error_msg[:200]}")

@bot.message_handler(content_types=['voice'])
def handle_voice(message):
    user_id = message.chat.id
    logger.info(f"🎤 Голосовое от {user_id}")
    
    if user_id not in chats:
        chats[user_id] = []
        
    try:
        file_info = bot.get_file(message.voice.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp.write(downloaded_file)
            tmp_path = tmp.name

        with open(tmp_path, "rb") as f:
            audio_bytes = f.read()

        response = model.generate_content([
            "Прослушай это голосовое сообщение от ученика и ответь согласно своей инструкции.",
            {"mime_type": "audio/ogg", "data": audio_bytes}
        ])
        
        chats[user_id].append({"role": "user", "parts": ["[Голосовое сообщение]"]})
        chats[user_id].append({"role": "model", "parts": [response.text]})
        
        # Отправляем текст
        bot.reply_to(message, response.text)
        
        # Отправляем голос
        audio_data = text_to_speech(response.text)
        if audio_data:
            bot.send_voice(message.chat.id, audio_data)
            logger.info("🎤 Голосовое отправлено")
        
        os.unlink(tmp_path)
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"❌ Ошибка голосового: {error_msg}")
        bot.reply_to(message, f"❌ {error_msg[:200]}")

if __name__ == "__main__":
    logger.info("🚀 Бот запущен!")
    bot.infinity_polling(timeout=30, long_polling_timeout=15)
