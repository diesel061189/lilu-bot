import os
import logging
import tempfile
import httpx
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
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
    import base64
    with open(audio_path, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode()

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}",
            json={"contents": [{"parts": [
                {"inline_data": {"mime_type": "audio/ogg", "data": audio_b64}},
                {"text": "Транскрибируй это аудио на русском языке. Напиши только текст, без пояснений."}
            ]}]}
        )
        result = response.json()
        logger.info(f"STT response: {result}")
        return result["candidates"][0]["content"]["parts"][0]["text"]


async def get_lilu_response(user_id: int, user_message: str) -> str:
    if user_id not in conversation_history:
        conversation_history[user_id] = []

    conversation_history[user_id].append({
        "role": "user",
        "parts": [{"text": user_message}]
    })

    if len(conversation_history[user_id]) > 20:
        conversation_history[user_id] = conversation_history[user_id][-20:]

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}",
            json={
                "system_instruction": {"parts": [{"text": LILU_SYSTEM_PROMPT}]},
                "contents": conversation_history[user_id]
            }
        )
        result = response.json()
        logger.info(f"Gemini response: {result}")

        if "candidates" not in result:
            error_msg = result.get("error", {}).get("message", str(result))
            raise Exception(f"Gemini error: {error_msg}")

        lilu_text = result["candidates"][0]["content"]["parts"][0]["text"]

    conversation_history[user_id].append({
        "role": "model",
        "parts": [{"text": lilu_text}]
    })

    return lilu_text


async def text_to_speech(text: str) -> bytes:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}",
            headers={"xi-api-key": ELEVENLABS_API_KEY},
            json={
                "text": text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.8, "style": 0.3}
            }
        )
        if response.status_code != 200:
            raise Exception(f"ElevenLabs error {response.status_code}: {response.text[:200]}")
        return response.content


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

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

        try:
            audio_data = await text_to_speech(lilu_response)
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                tmp.write(audio_data)
                tmp_path = tmp.name
            with open(tmp_path, "rb") as audio_file:
                await update.message.reply_voice(voice=audio_file)
            os.unlink(tmp_path)
        except Exception as e:
            logger.error(f"Ошибка голоса: {e}")
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
