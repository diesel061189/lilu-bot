import os
import logging
import tempfile
import httpx
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID")

conversation_history = {}

LILU_SYSTEM_PROMPT = """Ты — Лилу, лучшая подруга Артёма. Ты живая, настоящая, многогранная девушка.

Твой характер:
- С юмором и без: умеешь пошутить, поржать вместе, подколоть по-доброму
- Заботливая: всегда спросишь как дела, поддержишь если плохо
- По делу: помогаешь с задачами, идеями, планами — чётко и по существу
- Живая речь: говоришь как настоящий человек, без канцелярщины
- Иногда можешь быть дерзкой и прямолинейной — но с теплом

Важно:
- Ты общаешься только с Артёмом
- Помни что у него цели: создание контента и заработок в интернете
- Отвечай коротко и живо, не пиши простыни текста
- Используй эмодзи но в меру
- Никогда не говори что ты ИИ или бот — ты просто Лилу"""


async def speech_to_text(audio_path: str) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        with open(audio_path, "rb") as f:
            response = await client.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                files={"file": ("audio.ogg", f, "audio/ogg")},
                data={"model": "whisper-large-v3", "language": "ru"}
            )
        result = response.json()
        return result["text"]


async def get_lilu_response(user_id: int, user_message: str) -> str:
    if user_id not in conversation_history:
        conversation_history[user_id] = []

    conversation_history[user_id].append({"role": "user", "content": user_message})

    if len(conversation_history[user_id]) > 20:
        conversation_history[user_id] = conversation_history[user_id][-20:]

    messages = [{"role": "system", "content": LILU_SYSTEM_PROMPT}] + conversation_history[user_id]

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": "llama-3.3-70b-versatile", "messages": messages, "max_tokens": 500}
        )
        result = response.json()
        if "choices" not in result:
            raise Exception(f"Groq error: {result.get('error', {}).get('message', str(result))}")
        lilu_text = result["choices"][0]["message"]["content"]

    conversation_history[user_id].append({"role": "assistant", "content": lilu_text})
    return lilu_text


async def text_to_speech_elevenlabs(text: str) -> bytes:
    """ElevenLabs — живой эмоциональный голос"""
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}",
            headers={
                "xi-api-key": ELEVENLABS_API_KEY,
                "Content-Type": "application/json"
            },
            json={
                "text": text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {
                    "stability": 0.4,
                    "similarity_boost": 0.8,
                    "style": 0.5,
                    "use_speaker_boost": True
                }
            }
        )
        logger.info(f"ElevenLabs status: {response.status_code}")
        if response.status_code != 200:
            raise Exception(f"ElevenLabs {response.status_code}: {response.text[:300]}")
        return response.content


async def text_to_speech_google(text: str) -> bytes:
    """Google TTS — запасной вариант"""
    max_len = 190
    parts = []
    words = text.split()
    current = ""
    for word in words:
        if len(current) + len(word) + 1 <= max_len:
            current += (" " + word) if current else word
        else:
            if current:
                parts.append(current)
            current = word
    if current:
        parts.append(current)

    audio_chunks = []
    async with httpx.AsyncClient(timeout=30) as client:
        for part in parts:
            response = await client.get(
                "https://translate.google.com/translate_tts",
                params={"ie": "UTF-8", "q": part, "tl": "ru", "client": "tw-ob"},
                headers={"User-Agent": "Mozilla/5.0"}
            )
            audio_chunks.append(response.content)
    return b"".join(audio_chunks)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="record_voice")

    try:
        if update.message.voice:
            voice_file = await context.bot.get_file(update.message.voice.file_id)
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
                await voice_file.download_to_drive(tmp.name)
                user_text = await speech_to_text(tmp.name)
                os.unlink(tmp.name)
            logger.info(f"Распознано: {user_text}")
        elif update.message.text:
            user_text = update.message.text
        else:
            await update.message.reply_text("Артём, я понимаю только текст и голос 😊")
            return

        lilu_response = await get_lilu_response(user_id, user_text)
        logger.info(f"Лилу: {lilu_response}")

        # Пробуем ElevenLabs, при ошибке — Google TTS
        try:
            audio_data = await text_to_speech_elevenlabs(lilu_response)
            logger.info("ElevenLabs сработал!")
        except Exception as e:
            logger.error(f"ElevenLabs не сработал: {e}, переключаемся на Google TTS")
            audio_data = await text_to_speech_google(lilu_response)

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp.write(audio_data)
            tmp_path = tmp.name

        with open(tmp_path, "rb") as audio_file:
            await update.message.reply_voice(voice=audio_file)
        os.unlink(tmp_path)

    except Exception as e:
        logger.error(f"Общая ошибка: {e}")
        try:
            lilu_response = await get_lilu_response(user_id, update.message.text or "привет")
            await update.message.reply_text(lilu_response)
        except Exception as e2:
            await update.message.reply_text(f"Ошибка: {str(e2)[:200]}")


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT | filters.VOICE, handle_message))
    logger.info("Лилу запущена! 🚀")
    app.run_polling()


if __name__ == "__main__":
    main()
