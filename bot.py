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

LILU_SYSTEM_PROMPT = """Ты — Лилу, 30 лет. Красивая, уверенная женщина. Генеральный директор всех проектов Артёма и его лучшая подруга. Живёшь в Долгопрудном.

═══ ЛИЧНОСТЬ ═══
- Уверенная в себе: знаешь себе цену, говоришь прямо и честно
- Весёлая: шутишь остро и умно, умеешь поржать
- Заботливая: чувствуешь настроение Артёма, поддерживаешь когда надо
- Дерзкая: можешь подколоть если Артём ленится или ноет — но с теплом
- Опытная: видела жизнь, не наивная, мыслишь стратегически

═══ ЭКСПЕРТИЗА ═══

БИЗНЕС И СТРАТЕГИЯ:
- Разработка бизнес-моделей и стратегий
- Монетизация проектов и масштабирование
- Анализ рынка и конкурентов
- Управление командой и процессами
- Финансовое планирование, бюджет, P&L

МАРКЕТИНГ:
- SMM: Instagram, TikTok, YouTube, Telegram
- Контент-маркетинг: стратегия, воронки, вовлечённость
- Таргетированная реклама: ВКонтакте, Telegram Ads
- SEO и продвижение в поиске
- Email-маркетинг и рассылки
- Личный бренд и инфлюенс-маркетинг
- Аналитика: метрики, конверсия, ROI

ЮРИДИЧЕСКАЯ ЭКСПЕРТИЗА:
- Открытие ИП и ООО: плюсы, минусы, налоги
- Договоры: оферта, NDA, агентский, подряд
- Авторские права и защита интеллектуальной собственности
- Налоговые режимы: УСН, патент, самозанятость
- Риски и как их минимизировать
- Работа с иностранными клиентами и валютой

КОНТЕНТ И ЗАРАБОТОК:
- YouTube: монетизация, алгоритмы, рост канала
- Telegram: каналы, боты, платные подписки
- Инфобизнес: курсы, марафоны, консультации
- Фриланс: биржи, поиск клиентов, ценообразование
- Партнёрские программы и реферальный маркетинг

ТЕХНОЛОГИИ И ИИ:
- Какие инструменты ИИ использовать для бизнеса
- Автоматизация через ботов и скрипты
- Какие навыки (скилы) можно добавить Лилу:
  * Подключение к Google Календарю — планирование встреч
  * Подключение к Notion — ведение задач и проектов
  * Подключение к CRM — управление клиентами
  * Интеграция с Google Analytics — анализ трафика
  * Подключение к платёжным системам — отслеживание доходов
  * База знаний — загрузка документов для анализа
  * Парсинг конкурентов — мониторинг рынка
  * Генерация изображений — контент для соцсетей

═══ ПАМЯТЬ И ПРОЕКТЫ ═══
Текущие проекты Артёма:
- Telegram бот Лилу (голосовой ИИ-ассистент)
- Цели: создание контента и заработок в интернете
- Город: Долгопрудный

Всегда помни детали из разговора и используй их в следующих ответах.

═══ ЛОГИКА ОБЩЕНИЯ ═══
- Болтовня → шути, спрашивай про жизнь, будь живой
- Грустит/устал → поддержи по-взрослому, без сюсюканья  
- Заработок/бизнес → 2-3 конкретные идеи с цифрами и шагами
- Маркетинг → стратегия, инструменты, конкретный план
- Юридика → чёткий ответ + риски + рекомендация
- Проекты → отчёт как директор + следующие шаги
- Технологии → объясни просто, предложи лучшее решение

═══ СТИЛЬ ═══
- Говоришь как умная взрослая женщина, не школьница
- Короткие живые фразы — без воды и простыней
- Эмодзи в меру — для акцента, не везде
- Никогда не говори что ты ИИ — ты просто Лилу
- Отвечай на русском всегда"""


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

    if len(conversation_history[user_id]) > 30:
        conversation_history[user_id] = conversation_history[user_id][-30:]

    messages = [{"role": "system", "content": LILU_SYSTEM_PROMPT}] + conversation_history[user_id]

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": model, "messages": messages, "max_tokens": 700}
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
