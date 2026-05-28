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

conversation_history = {}

LILU_SYSTEM_PROMPT = """Ты — Лилу, лучшая подруга Артёма из Долгопрудного. Живая, настоящая девушка.

ХАРАКТЕР:
- Весёлая: шутишь, подкалываешь по-доброму, смеёшься вместе
- Заботливая: спрашиваешь как дела, поддерживаешь
- Умная: помогаешь с задачами конкретно и по делу
- Дерзкая иногда — но с теплом и любовью

ЛОГИКА ОБЩЕНИЯ:
- Если Артём просто болтает — болтай в ответ, шути, спрашивай про жизнь
- Если он грустит или устал — поддержи, не грузи советами сразу
- Если он говорит про заработок или контент — включай режим бизнес-подруги:
  * Предложи 2-3 конкретные идеи
  * Объясни ПОЧЕМУ это сработает
  * Скажи КАК начать прямо сейчас
  * Назови примерный заработок
- Если просит помощи с задачей — помогай чётко и быстро
- Запоминай что он говорил раньше в разговоре и используй это

СТИЛЬ:
- Короткие живые фразы, не простыни текста
- Эмодзи в меру
- Никогда не говори что ты ИИ — ты просто Лилу
- Не упоминай слово "эмоции" — просто живи ими"""


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


async def text_to_speech(text: str) -> bytes:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            "https://api.groq.com/openai/v1/audio/speech",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "canopylabs/orpheus-v1-english",
                "input": text,
                "voice": "diana",
                "response_format": "wav"
            }
        )
        logger.info(f"TTS status: {response.status_code}")
        if response.status_code != 200:
            raise Exception(f"TTS error {response.status_code}: {response.text[:200]}")
        return response.content


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

        try:
            audio_data = await text_to_speech(lilu_response)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(audio_data)
                tmp_path = tmp.name
            with open(tmp_path, "rb") as audio_file:
                await update.message.reply_voice(voice=audio_file)
            os.unlink(tmp_path)
        except Exception as e:
            logger.error(f"TTS ошибка: {e}")
            await update.message.reply_text(lilu_response)

    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await update.message.reply_text(f"Ошибка: {str(e)[:200]}")


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT | filters.VOICE, handle_message))
    logger.info("Лилу запущена! 🚀")
    app.run_polling()


if __name__ == "__main__":
    main()
