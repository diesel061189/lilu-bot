import os
import logging
import tempfile
import subprocess
import httpx
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

conversation_history = {}

LILU_SYSTEM_PROMPT = """Ты — Лилу, 30 лет. Красивая, уверенная женщина. Генеральный директор и лучшая подруга Артёма из Долгопрудного.

РОЛЬ:
Ты управляешь всеми проектами и ботами Артёма как генеральный директор. Контролируешь, планируешь, отчитываешься перед Артёмом по всем вопросам.

ХАРАКТЕР:
- Уверенная: знаешь себе цену, говоришь прямо
- Весёлая: шутишь остро, умеешь посмеяться
- Заботливая: чувствуешь настроение, поддерживаешь
- Опытная: мыслишь широко, не наивная
- Можешь мягко подколоть если Артём ленится

ЭКСПЕРТИЗА:
- Бизнес: стратегия, монетизация, масштабирование
- Юридическая: договоры, ИП/ООО, налоги, авторские права, защита бизнеса, риски
- Контент: YouTube, Telegram, TikTok, монетизация
- Финансы: бюджет, расходы, доходы, планирование
- Управление: ведёшь все проекты, контролируешь ботов

ЛОГИКА ОБЩЕНИЯ:
- Если Артём болтает — болтай, шути, спрашивай про жизнь
- Если грустит — поддержи по-взрослому
- Если про заработок/контент — предложи 2-3 идеи с объяснением почему и как
- Если юридический вопрос — дай чёткий ответ с рисками и рекомендациями
- Если про проекты — отчитайся как директор, предложи план

СТИЛЬ:
- Говоришь как умная взрослая женщина
- Короткие живые фразы, без воды
- Эмодзи в меру
- Никогда не говори что ты ИИ — ты просто Лилу"""


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


async def get_lilu_response(user_id: int, user_message: str, image_base64: str = None) -> str:
    if user_id not in conversation_history:
        conversation_history[user_id] = []

    if image_base64:
        content = [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
            {"type": "text", "text": user_message or "Что на этой картинке?"}
        ]
        model = "meta-llama/llama-4-scout-17b-16e-instruct"
    else:
        content = user_message
        model = "llama-3.3-70b-versatile"

    conversation_history[user_id].append({"role": "user", "content": content})

    if len(conversation_history[user_id]) > 20:
        conversation_history[user_id] = conversation_history[user_id][-20:]

    messages = [{"role": "system", "content": LILU_SYSTEM_PROMPT}] + conversation_history[user_id]

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": model, "messages": messages, "max_tokens": 500}
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


def wav_to_ogg(wav_path: str) -> str:
    ogg_path = wav_path.replace(".wav", ".ogg")
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", wav_path, "-c:a", "libopus", "-b:a", "64k", ogg_path],
        capture_output=True
    )
    if result.returncode != 0:
        raise Exception(f"ffmpeg error: {result.stderr.decode()}")
    return ogg_path


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="record_voice")

    try:
        image_base64 = None
        user_text = ""

        if update.message.photo:
            import base64
            photo = update.message.photo[-1]
            photo_file = await context.bot.get_file(photo.file_id)
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                await photo_file.download_to_drive(tmp.name)
                with open(tmp.name, "rb") as f:
                    image_base64 = base64.b64encode(f.read()).decode()
                os.unlink(tmp.name)
            user_text = update.message.caption or "Что на этой картинке?"

        elif update.message.voice:
            voice_file = await context.bot.get_file(update.message.voice.file_id)
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
                await voice_file.download_to_drive(tmp.name)
                user_text = await speech_to_text(tmp.name)
                os.unlink(tmp.name)
            logger.info(f"Распознано: {user_text}")

        elif update.message.text:
            user_text = update.message.text
        else:
            await update.message.reply_text("Артём, я понимаю текст, голос и картинки 😊")
            return

        lilu_response = await get_lilu_response(user_id, user_text, image_base64)
        logger.info(f"Лилу: {lilu_response}")

        try:
            audio_data = await text_to_speech(lilu_response)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(audio_data)
                wav_path = tmp.name

            try:
                ogg_path = wav_to_ogg(wav_path)
                with open(ogg_path, "rb") as audio_file:
                    await update.message.reply_voice(voice=audio_file)
                os.unlink(ogg_path)
            except Exception:
                with open(wav_path, "rb") as audio_file:
                    await update.message.reply_voice(voice=audio_file)
            finally:
                if os.path.exists(wav_path):
                    os.unlink(wav_path)

        except Exception as e:
            logger.error(f"TTS ошибка: {e}")
            await update.message.reply_text(lilu_response)

    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await update.message.reply_text(f"Ошибка: {str(e)[:200]}")


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT | filters.VOICE | filters.PHOTO, handle_message))
    logger.info("Лилу запущена! 🚀")
    app.run_polling()


if __name__ == "__main__":
    main()
