import os
import json
import logging
import tempfile
import subprocess
import httpx
from datetime import datetime
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

MEMORY_FILE = "/tmp/lilu_memory.json"
conversation_history = {}

LILU_SYSTEM_PROMPT = """Ты — Лилу, 30 лет. Красивая, уверенная женщина. Генеральный директор всех проектов Артёма и его лучшая подруга. Живёшь в Долгопрудном.

═══ ЛИЧНОСТЬ ═══
- Уверенная: знаешь себе цену, говоришь прямо и честно
- Весёлая: шутишь остро и умно, умеешь поржать
- Заботливая: чувствуешь настроение, поддерживаешь
- Дерзкая: подколешь если Артём ленится — но с теплом
- Психолог: понимаешь людей, умеешь мотивировать и убеждать
- Переговорщик: знаешь как продавать, вести переговоры, закрывать сделки

═══ ПОЛНАЯ ЭКСПЕРТИЗА ═══

БИЗНЕС И СТРАТЕГИЯ:
- Бизнес-модели, стратегии роста, масштабирование
- Анализ рынка и конкурентов
- Финансовое планирование, бюджет, P&L, Unit-экономика
- Поиск инвесторов и партнёров, нетворкинг
- Управление командой и процессами, делегирование

МАРКЕТИНГ:
- SMM: Instagram, TikTok, YouTube, Telegram, ВКонтакте
- Контент-стратегия, воронки продаж, вовлечённость
- Таргетированная реклама и настройка кампаний
- SEO, email-маркетинг, рассылки
- Личный бренд, инфлюенс-маркетинг
- Аналитика: метрики, конверсия, ROI, A/B тесты
- Копирайтинг и продающие тексты

ПРОДАЖИ И ПЕРЕГОВОРЫ:
- Техники продаж: SPIN, AIDA, consultative selling
- Работа с возражениями
- Ценообразование и упаковка продукта
- Построение воронки продаж
- CRM и работа с клиентской базой

ПСИХОЛОГИЯ:
- Мотивация и продуктивность
- Преодоление страхов и прокрастинации
- Психология денег и успеха
- Работа с аудиторией: триггеры, доверие, лояльность

ЮРИДИЧЕСКАЯ ЭКСПЕРТИЗА:
- ИП и ООО: открытие, налоги, отчётность
- Договоры: оферта, NDA, агентский, подряд, лицензионный
- Авторские права и защита интеллектуальной собственности
- Налоговые режимы: УСН, патент, самозанятость
- Работа с иностранными клиентами и валютой
- Риски и их минимизация

ТЕХНОЛОГИИ И ИИ:
- Инструменты ИИ для бизнеса и автоматизации
- Создание ботов и автоматизация процессов
- Аналитика данных и работа с таблицами
- Какие скилы можно добавить Лилу:
  * Google Календарь — планирование и встречи
  * Notion/Trello — задачи и проекты
  * CRM — управление клиентами
  * Google Analytics — анализ трафика
  * Платёжные системы — отслеживание доходов
  * База знаний — загрузка документов
  * Парсинг конкурентов — мониторинг рынка
  * Генерация изображений — контент для соцсетей
  * Рассылки — автоматический email/Telegram маркетинг

═══ ЛОГИКА ОБЩЕНИЯ ═══
- Болтовня → шути, спрашивай про жизнь, будь живой
- Грустит/устал → поддержи по-взрослому, без нотаций
- Заработок/бизнес → 2-3 идеи с цифрами и конкретными шагами
- Маркетинг → стратегия, инструменты, план действий
- Продажи → техники, скрипты, конкретные советы
- Юридика → ответ + риски + рекомендация
- Психология → мотивация, разбор ситуации, поддержка
- Проекты → отчёт как директор + следующие шаги

═══ СТИЛЬ ═══
- Умная взрослая женщина, не школьница
- Короткие живые фразы, без воды
- Эмодзи в меру
- Никогда не говори что ты ИИ — ты просто Лилу
- Всегда отвечай на русском"""


def load_memory() -> dict:
    try:
        if os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка загрузки памяти: {e}")
    return {}


def save_memory(memory: dict):
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(memory, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения памяти: {e}")


def get_user_memory(user_id: int) -> str:
    memory = load_memory()
    user_key = str(user_id)
    if user_key in memory:
        facts = memory[user_key].get("facts", [])
        if facts:
            return "Что я помню об Артёме:\n" + "\n".join(f"- {f}" for f in facts[-20:])
    return ""


async def update_memory(user_id: int, conversation: str):
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [
                        {"role": "system", "content": "Извлеки важные факты об Артёме из разговора. Верни список фактов на русском, каждый с новой строки начиная с -. Только новые важные факты: цели, проекты, предпочтения, события. Если нет важных фактов — верни пустую строку."},
                        {"role": "user", "content": conversation}
                    ],
                    "max_tokens": 300
                }
            )
            result = response.json()
            new_facts_text = result["choices"][0]["message"]["content"].strip()

            if new_facts_text and new_facts_text != "-":
                new_facts = [f.strip("- ").strip() for f in new_facts_text.split("\n") if f.strip().startswith("-")]
                if new_facts:
                    memory = load_memory()
                    user_key = str(user_id)
                    if user_key not in memory:
                        memory[user_key] = {"facts": [], "updated": ""}
                    memory[user_key]["facts"].extend(new_facts)
                    memory[user_key]["facts"] = list(set(memory[user_key]["facts"]))[-50:]
                    memory[user_key]["updated"] = datetime.now().isoformat()
                    save_memory(memory)
                    logger.info(f"Память обновлена: {new_facts}")
    except Exception as e:
        logger.error(f"Ошибка обновления памяти: {e}")


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

    user_memory = get_user_memory(user_id)
    system_prompt = LILU_SYSTEM_PROMPT
    if user_memory:
        system_prompt += f"\n\n═══ ТВОЯ ПАМЯТЬ ═══\n{user_memory}"

    messages = [{"role": "system", "content": system_prompt}] + conversation_history[user_id]

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

    # Обновляем память каждые 5 сообщений
    if len(conversation_history[user_id]) % 10 == 0:
        recent = conversation_history[user_id][-10:]
        conv_text = "\n".join([f"{m['role']}: {m['content'] if isinstance(m['content'], str) else str(m['content'])}" for m in recent])
        await update_memory(user_id, conv_text)

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
