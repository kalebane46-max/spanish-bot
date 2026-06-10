import os
import tempfile
import telebot
import google.generativeai as genai
from threading import Thread
from flask import Flask
import logging
import time
import requests
import base64

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    app.run(host='0.0.0.0', port=10000)

Thread(target=run_flask).start()

# Токены
TG_TOKEN = os.environ.get("TG_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_KEY")
ELEVENLABS_KEY = os.environ.get("ELEVENLABS_KEY")

bot = telebot.TeleBot(TG_TOKEN)
genai.configure(api_key=GEMINI_KEY)

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

model = genai.GenerativeModel(
    model_name="gemini-3-flash-preview",
    system_instruction=SPANISH_PROMPT
)

chats = {}

# Функция для создания голосового сообщения через ElevenLabs
def text_to_speech(text, voice_id="pNInz6obpgDQGcFmaJgB"):
    """
    Преобразует текст в голосовое сообщение.
    voice_id: Adam (мужской голос, хорошо звучит на испанском)
    """
    if not ELEVENLABS_KEY:
        logger.warning("ELEVENLABS_KEY не найден, пропускаю озвучку")
        return None
    
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": ELEVENLABS_KEY
    }
    data = {
        "text": text,
        "model_id": "eleven_flash_2_5",  # Быстрая и бесплатная модель
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.7
        }
    }
    
    try:
        response = requests.post(url, json=data, headers=headers, timeout=15)
        if response.status_code == 200:
            return response.content
        else:
            logger.error(f"ElevenLabs ошибка: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        logger.error(f"Ошибка ElevenLabs: {e}")
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
        logger.info(f"🤖 Запрос к Gemini...")
        response = model.generate_content(chats[user_id])
        logger.info(f"✅ Ответ: {response.text[:50]}...")
        
        chats[user_id].append({"role": "model", "parts": [response.text]})
        
        # Отправляем текстовый ответ
        bot.reply_to(message, response.text)
        
        # Отправляем голосовой ответ
        audio_data = text_to_speech(response.text)
        if audio_data:
            bot.send_voice(message.chat.id, audio_data)
            logger.info("🎤 Голосовой ответ отправлен")
        
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
        
        # Отправляем текстовый ответ
        bot.reply_to(message, response.text)
        
        # Отправляем голосовой ответ
        audio_data = text_to_speech(response.text)
        if audio_data:
            bot.send_voice(message.chat.id, audio_data)
            logger.info("🎤 Голосовой ответ отправлен")
        
        os.unlink(tmp_path)
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"❌ Ошибка голосового: {error_msg}")
        bot.reply_to(message, f"❌ {error_msg[:200]}")

if __name__ == "__main__":
    logger.info("🚀 Запуск бота...")
    bot.remove_webhook()
    time.sleep(2)
    
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=10)
        except Exception as e:
            logger.error(f"❌ Ошибка соединения: {e}")
            time.sleep(5)
